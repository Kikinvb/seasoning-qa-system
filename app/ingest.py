import csv
import hashlib
import io
import re
from datetime import date
from functools import lru_cache
from itertools import batched
from pathlib import Path

import jieba
from psycopg.types.json import Jsonb

FORMATS = {".pdf", ".docx", ".xlsx", ".csv"}
SEED_FILE = Path("/seed/食品安全知识库_知识条目.csv")
STANDARD = re.compile(r"\bGB\s*(?:/\s*T\s*)?\d+(?:\.\d+)?(?:\s*[-—–－]\s*\d{4})?", re.I)
CLAUSE = re.compile(r"第[零一二三四五六七八九十百千0-9]+条")


def keyword_text(text):
    return " ".join(token.lower() for token in jieba.cut_for_search(text) if token.isalnum())


@lru_cache(maxsize=1)
def model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("BAAI/bge-small-zh-v1.5", device="cpu")


def vectors(texts):
    return model().encode(texts, batch_size=32, normalize_embeddings=True).tolist()


def vector_literal(vector):
    return "[" + ",".join(map(str, vector)) + "]"


def parts(text, position, **fields):
    text = text.strip()
    while text:
        end = len(text)
        if end > 1100:
            end = max(text.rfind("\n", 650, 1100), text.rfind("。", 650, 1100)) + 1 or 1100
        yield {"content": text[:end], "position": position, **fields}
        text = text[end:].lstrip()


def file_chunks(data, suffix):
    if suffix == ".pdf":
        import pymupdf

        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            for page in pdf:
                text = page.get_text(sort=True)
                if not text.strip():
                    try:
                        textpage = page.get_textpage_ocr(language="chi_sim+eng", dpi=300, full=True)
                        text = page.get_text(textpage=textpage, sort=True)
                    except RuntimeError as exc:
                        raise ValueError(
                            f"第 {page.number + 1} 页需要 OCR，但识别失败。"
                            "请确认已安装 Tesseract 及简体中文、英文语言包。"
                        ) from exc
                yield from parts(text, f"第 {page.number + 1} 页", page_no=page.number + 1)
    elif suffix == ".docx":
        from docx import Document
        from docx.table import Table

        heading = ""
        for index, block in enumerate(Document(io.BytesIO(data)).iter_inner_content(), 1):
            if isinstance(block, Table):
                headers = [cell.text for cell in block.rows[0].cells] if block.rows else []
                for row_index, row in enumerate(block.rows, 1):
                    values = [cell.text for cell in row.cells]
                    line = " | ".join(f"{key}: {value}" for key, value in zip(headers, values))
                    yield from parts(line, f"第 {index} 个内容块 · 表格第 {row_index} 行", heading_path=heading)
            else:
                if block.style and re.search(r"heading|标题", block.style.name, re.I):
                    heading = block.text
                yield from parts(block.text, f"第 {index} 个内容块", heading_path=heading)
    elif suffix == ".xlsx":
        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            for sheet in book.worksheets:
                yield from table_chunks(sheet.values, sheet.title)
        finally:
            book.close()
    else:
        yield from table_chunks(csv.reader(io.StringIO(data.decode("utf-8-sig"))), "CSV")


def table_chunks(rows, label):
    headers = None
    for index, row in enumerate(rows, 1):
        values = [str(value) if value is not None else "" for value in row]
        if not any(value.strip() for value in values):
            continue
        if headers is None:
            headers = values
        line = " | ".join(
            f"{headers[column] or f'列 {column + 1}'}: {value}" if column < len(headers) else value
            for column, value in enumerate(values) if value.strip()
        )
        yield from parts(line, f"{label} · 第 {index} 行", heading_path=label)


def date_or_none(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def crawl_documents(data):
    groups = {}
    for row in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
        doc, chunks = groups.setdefault(row["doc_id"], ({
            "external_doc_id": row["doc_id"], "title": row["doc_title"],
            "authority_level": row["doc_type"], "category": row["subcategory"],
            "standard_no": row["doc_number"], "version_label": row["version"],
            "scope_text": row["scope"], "status": row["status"] or "页面未明示",
            "effective_date": date_or_none(row["effective_at"]),
            "publish_date": date_or_none(row["published_at"]),
            "source_format": "csv", "file_uri": row["source_url"],
            "extra": Jsonb({"scope_status": row["scope_status"]}),
        }, []))
        chunks.append({
            "external_entry_id": row["entry_id"], "heading_path": row["section"],
            "content": row["content"], "position": f"条目 {row['entry_id']}", "seq": int(row["seq"]),
        })
    yield from groups.values()


def queue_source(conn, filename, data, source_type="upload"):
    digest = hashlib.sha256(data).hexdigest()
    row = conn.execute(
        """INSERT INTO kb_source (filename, original_bytes, content_hash, source_type)
           VALUES (%s, %s, %s, %s) ON CONFLICT (content_hash) DO NOTHING RETURNING id""",
        (filename, data, digest, source_type),
    ).fetchone()
    if row is not None:
        return row["id"], False
    return conn.execute("SELECT id FROM kb_source WHERE content_hash=%s", (digest,)).fetchone()["id"], True


def index_source(conn, source):
    data = source["original_bytes"]
    filename = source["filename"]
    suffix = Path(filename).suffix.lower()
    if source["source_type"] == "foodmate":
        documents = crawl_documents(data)
    else:
        documents = [({"title": filename, "source_format": suffix[1:]}, file_chunks(data, suffix))]

    indexed = 0
    with conn.transaction(), conn.cursor() as cursor:
        for document, chunks in documents:
            columns = ", ".join(document)
            placeholders = ", ".join(["%s"] * len(document))
            doc_id = cursor.execute(
                f"INSERT INTO kb_document (source_id, {columns}) VALUES (%s, {placeholders}) RETURNING id",
                (source["id"], *document.values()),
            ).fetchone()["id"]
            for batch in batched(enumerate(chunks, 1), 64):
                texts = [
                    " ".join(filter(None, [document.get("standard_no"), document["title"],
                                           chunk.get("heading_path"), chunk["content"]]))
                    for _, chunk in batch
                ]
                rows = []
                for (index, chunk), text, embedding in zip(batch, texts, vectors(texts), strict=True):
                    clause = CLAUSE.search(chunk["content"][:40])
                    rows.append((
                        doc_id, chunk.get("external_entry_id"), clause.group() if clause else None,
                        chunk.get("heading_path"), chunk["content"], chunk.get("page_no"),
                        chunk["position"], chunk.get("seq", index), keyword_text(text),
                        vector_literal(embedding),
                    ))
                cursor.executemany(
                    """INSERT INTO kb_chunk
                       (document_id, external_entry_id, clause_no, heading_path, content, page_no,
                        position, seq, keywords, embedding)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,to_tsvector('simple',%s),%s::vector)""", rows
                )
                indexed += len(rows)
        if not indexed:
            raise ValueError("未提取到文字。请检查文件内容；扫描版 PDF 经 OCR 后仍未识别到文字。")
        cursor.execute("UPDATE kb_source SET parse_status='ok' WHERE id=%s", (source["id"],))


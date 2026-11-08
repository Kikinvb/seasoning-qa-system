import re

from .ingest import CLAUSE, STANDARD, keyword_text, vector_literal, vectors

SEARCH = """
WITH query AS (
    SELECT to_tsquery('simple', %s) AS words, %s::vector AS embedding
),
eligible AS MATERIALIZED (
    SELECT c.id, c.embedding, c.keywords, c.clause_no, d.standard_no
    FROM kb_chunk c
    JOIN kb_document d ON d.id=c.document_id
    JOIN kb_source s ON s.id=d.source_id
    WHERE s.parse_status='ok'
      AND (d.publish_date IS NULL OR d.publish_date <= %s)
      AND (
        (d.status NOT IN ('已废止/失效', '即将实施') AND (d.effective_date IS NULL OR d.effective_date <= %s))
        OR (%s AND d.effective_date <= %s)
        OR (d.status='即将实施' AND d.effective_date <= %s)
      )
      AND (%s = '' OR regexp_replace(upper(coalesce(d.standard_no, '')), '[[:space:]—–－]', '', 'g')
          LIKE %s OR (coalesce(d.standard_no, '') = '' AND
          strpos(regexp_replace(upper(d.title || ' ' || c.content), '[[:space:]—–－]', '', 'g'), %s) > 0))
),
semantic AS (
    SELECT e.id, row_number() OVER (ORDER BY e.embedding <=> q.embedding, e.id) AS rank
    FROM eligible e CROSS JOIN query q ORDER BY rank LIMIT 30
),
lexical AS (
    SELECT e.id, row_number() OVER (
        ORDER BY (coalesce(e.clause_no, '') = %s) DESC, ts_rank_cd(e.keywords, q.words) DESC, e.id
    ) AS rank
    FROM eligible e CROSS JOIN query q
    WHERE e.keywords @@ q.words OR e.clause_no = %s
    ORDER BY rank LIMIT 30
),
ranked AS (
    SELECT id, sum(score) AS score FROM (
        SELECT id, 1.0 / (30 + rank) AS score FROM semantic
        UNION ALL
        SELECT id, 1.0 / (30 + rank) AS score FROM lexical
    ) matches GROUP BY id ORDER BY score DESC, id LIMIT 8
)
SELECT c.id, c.content, c.position, c.clause_no, c.heading_path,
       d.title, d.standard_no, d.version_label, d.scope_text, d.status,
       d.effective_date, d.file_uri, d.authority_level, s.filename, s.id AS source_id,
       (1 - (c.embedding <=> q.embedding)) AS similarity, c.keywords @@ q.words AS keyword_match
FROM ranked r
JOIN kb_chunk c ON c.id=r.id
JOIN kb_document d ON d.id=c.document_id
JOIN kb_source s ON s.id=d.source_id CROSS JOIN query q
ORDER BY r.score DESC, c.id
"""


def retrieve(conn, question, prior, as_of, historical):
    if not conn.execute(
        "SELECT 1 FROM kb_source WHERE parse_status='ok' LIMIT 1"
    ).fetchone():
        return []
    tokens = list(dict.fromkeys(keyword_text(question).split()))[:80]
    words = " | ".join("'" + token + "'" for token in tokens)
    reference = STANDARD.search(question)
    standard = re.sub(r"[\s—–－]", "", reference.group().upper()) if reference else ""
    clause = CLAUSE.search(question)
    clause = clause.group() if clause else ""
    context = f"{prior[-1]}\n{question}" if prior else question
    embedding = vector_literal(vectors(["为这个句子生成表示以用于检索相关文章：" + context[-1000:]])[0])
    rows = conn.execute(SEARCH, (
        words, embedding, as_of, as_of, historical, as_of, as_of,
        standard, standard + "%", standard, clause, clause,
    )).fetchall()
    return [
        {key: value for key, value in row.items() if key not in {"similarity", "keyword_match"}}
        for row in rows if row["similarity"] >= 0.52 or (row["keyword_match"] and (standard or row["similarity"] >= 0.40))
    ]


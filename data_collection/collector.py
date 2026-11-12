"""Standalone public-resource collector. All persistence is local files."""
import argparse
import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

AGENT = "SeasoningResearchCollector/0.1"
FIELDS = ["record_id", "source_id", "resource_type", "region", "publisher",
          "doc_title", "published_at", "date_status", "source_url", "collected_at",
          "content", "content_hash", "raw_file", "review_status", "attachments"]


class Collector:
    def __init__(self, output):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = AGENT
        self.robots = {}
        self.last_request = 0

    def request(self, url):
        if urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError("Only HTTP(S) URLs are supported")
        time.sleep(max(0, 2 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        response = self.session.get(url, timeout=(15, 60), allow_redirects=False,
                                    stream=True)
        if 300 <= response.status_code < 400:
            response.close()
            raise ValueError("Redirect requires checking and configuring the final URL")
        response.raise_for_status()
        data = bytearray()
        for block in response.iter_content(65536):
            data.extend(block)
            if len(data) > 25 * 1024 * 1024:
                response.close()
                raise ValueError("Resource exceeds 25 MB")
        response.close()
        return response, bytes(data)

    def allowed(self, url):
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self.robots:
            parser = RobotFileParser()
            try:
                _, data = self.request(root + "/robots.txt")
                parser.parse(data.decode("utf-8", errors="replace").splitlines())
            except requests.HTTPError as exc:
                if exc.response.status_code == 404:
                    parser.parse([])
                else:
                    raise
            self.robots[root] = parser
        return self.robots[root].can_fetch(AGENT, url)

    def fetch(self, url):
        if not self.allowed(url):
            raise ValueError("robots.txt disallows collection")
        return self.request(url)

    def log(self, **event):
        with (self.output / "runs.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(),
                                     **event}, ensure_ascii=False) + "\n")

    def page(self, source, url):
        response, data = self.fetch(url)
        digest = hashlib.sha256(data).hexdigest()
        folder = self.output / "raw"
        folder.mkdir(exist_ok=True)
        raw = folder / (digest + ".html")
        raw.write_bytes(data)
        # Preserve HTML bytes; BeautifulSoup detects declared document encoding.
        soup = BeautifulSoup(data, "html.parser")
        if source.get("page_type") == "listing" or source.get("resource_type") == "directory":
            self.log(status="listing_saved", url=url, raw_file=str(raw))
            return soup
        body = soup.select_one(source.get("body_selector", "body"))
        if body is None:
            raise ValueError("Configured body selector did not match")
        title = soup.title.get_text(" ", strip=True) if soup.title else url
        title_meta = soup.select_one('meta[name="ArticleTitle"]')
        if title_meta:
            title = title_meta.get("content", title)
        date_node = soup.select_one(source["date_selector"]) if source.get("date_selector") else None
        published = date_node.get_text(" ", strip=True) if date_node else ""
        date_meta = soup.select_one('meta[name="PubDate"]')
        if date_meta:
            published = date_meta.get("content", "")[:10]
        issues = []
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
            issues.append("发布日期缺失或格式待核对")
        elif source.get("date_from") and published < source["date_from"]:
            self.log(status="outside_date_range", url=url, published_at=published)
            return soup
        elif published > datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            issues.append("发布日期晚于采集日期")
        if len(body.get_text(strip=True)) < source.get("min_content_chars", 150):
            issues.append("正文过短")
        links = [(a.get_text(" ", strip=True), urljoin(url, a["href"]))
                 for a in body.select("a[href]")]
        for node in soup.select("[onclick]"):
            match = re.search(r"downloadFj\('([^']*)','([^']*)'\)", node.get("onclick", ""))
            if match:
                links.append((match[1], urljoin(url, match[2])))
        for node in body.select("script, style, nav, footer"):
            node.decompose()
        record = dict.fromkeys(FIELDS, "")
        record.update(record_id=hashlib.sha256(url.encode()).hexdigest(),
                      source_id=source["id"], resource_type=source["resource_type"],
                      region=source.get("region", ""), publisher=source.get("publisher", ""),
                      doc_title=title, published_at=published,
                      date_status="待核对" if published else "未提取",
                      source_url=url, collected_at=datetime.now(timezone.utc).isoformat(),
                      content=body.get_text("\n", strip=True), content_hash=digest,
                      raw_file=raw.relative_to(self.output).as_posix(), review_status="待审核")
        record["review_status"] = "待核对：" + "；".join(issues) if issues else "待审核"
        paragraphs = body.select("p")
        if paragraphs and not body.select("table"):
            record["content"] = "\n".join(p.get_text("", strip=True) for p in paragraphs
                                             if p.get_text(strip=True))
        attachments = []
        records = self.output / ("quarantine" if issues else "records")
        records.mkdir(exist_ok=True)
        (records / (record["record_id"] + ".json")).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if source.get("download_attachments"):
            for label, link in links:
                suffix = Path(urlsplit(link).path).suffix.lower()
                if suffix not in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv"}:
                    continue
                if urlsplit(link).netloc != urlsplit(url).netloc:
                    continue
                try:
                    _, attachment = self.fetch(link)
                    target = folder / (hashlib.sha256(attachment).hexdigest() + suffix)
                    target.write_bytes(attachment)
                    attachments.append({"label": label, "url": link,
                                        "file": target.relative_to(self.output).as_posix(),
                                        "status": "saved"})
                    self.log(status="attachment_saved", parent=url, url=link,
                             label=label, file=target.relative_to(self.output).as_posix())
                except Exception as exc:
                    attachments.append({"label": label, "url": link,
                                        "status": "failed", "error": str(exc)})
                    self.log(status="attachment_failed", url=link, error=str(exc))
        record["attachments"] = json.dumps(attachments, ensure_ascii=False)
        (records / (record["record_id"] + ".json")).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(status="saved", url=url, content_hash=digest)
        return soup

    def run(self, sources):
        failures = 0
        for source in sources:
            if not source.get("enabled", False):
                continue
            try:
                soup = self.page(source, source["url"])
                details = list(source.get("detail_urls", []))
                selector = source.get("list_link_selector")
                if selector:
                    details.extend(urljoin(source["url"], a["href"])
                                   for a in soup.select(selector) if a.get("href"))
                for url in list(dict.fromkeys(details))[:source.get("max_details", 10)]:
                    if urlsplit(url).netloc != urlsplit(source["url"]).netloc:
                        continue
                    try:
                        self.page({**source, "page_type": "detail"}, url)
                    except Exception as exc:
                        failures += 1
                        self.log(status="failed", url=url, error=str(exc))
            except Exception as exc:
                failures += 1
                self.log(status="failed", source_id=source.get("id"), error=str(exc))
        with (self.output / "records.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for path in sorted((self.output / "records").glob("*.json")):
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("resource_type") == "directory":
                    continue
                writer.writerow(record)
        return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/sources.json")
    parser.add_argument("--output", default="output")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    raise SystemExit(1 if Collector(args.output).run(config["sources"]) else 0)

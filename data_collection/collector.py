"""Standalone public-resource collector. All persistence is local files."""
import argparse
import csv
import hashlib
import json
import re
import time
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from attachment_validation import validate_attachment

AGENT = "SeasoningResearchCollector/0.1"
BEIJING = timezone(timedelta(hours=8))


def safe_name(value, limit=70):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip().rstrip('. ')
    value = value[:limit].rstrip('. ') or '未命名'
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL'} | {
            f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)}:
        value = '_' + value
    return value


def wcm_next(soup, url):
    # Parse literal pagination metadata, never execute website JavaScript.
    for script in soup.select('script'):
        match = re.search(r'createPage\(\s*(\d+)\s*,\s*(\d+)\s*,\s*[\"\'](\w+)[\"\']\s*,\s*[\"\'](html?)[\"\']\s*\)', script.get_text())
        if match:
            count, current = int(match[1]), int(match[2])
            if current + 1 < count:
                return urljoin(url, f'{match[3]}_{current + 1}.{match[4]}')
            return None
    raise ValueError('WCM pagination metadata not found')


def five_years_ago(today):
    try:
        return today.replace(year=today.year - 5)
    except ValueError:
        return today.replace(year=today.year - 5, day=28)


FIELDS = ["record_id", "source_id", "resource_type", "region", "publisher",
          "doc_title", "published_at", "date_status", "source_url", "collected_at",
          "content", "content_hash", "raw_file", "review_status", "attachments"]


class Collector:
    def __init__(self, output, force_attachments=False, resume=False):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = AGENT
        self.robots = {}
        self.last_request = 0
        self.today = datetime.now(BEIJING).date()
        self.counts = Counter()
        self.errors = []
        self.coverage = []
        self.force_attachments = force_attachments
        self.resume = resume
        self.tasks = []

    def checkpoint(self):
        target = self.output / 'tasks.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.tasks, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(target)

    def execute_task(self, task):
        task['status'] = 'running'
        self.checkpoint()
        before = len(self.errors)
        try:
            self.page({**task['source'], 'page_type': 'detail'}, task['url'])
            task['status'] = 'failed' if len(self.errors) > before else 'completed'
            task.pop('error', None)
        except Exception as exc:
            task['status'] = 'failed'
            task['error'] = str(exc)
            self.log(status='failed', url=task['url'], error=str(exc))
        self.checkpoint()

    def previous_attachments(self, record_id):
        for state in ('records', 'quarantine', 'excluded'):
            path = self.output / state / (record_id + '.json')
            if path.exists():
                record = json.loads(path.read_text(encoding='utf-8-sig'))
                items = record.get('attachments') or []
                return json.loads(items) if isinstance(items, str) else items
        return []

    def reusable_attachment(self, previous, link):
        if self.force_attachments:
            return None
        for item in previous:
            if item.get('url') != link or item.get('status') != 'saved' or not item.get('sha256'):
                continue
            path = (self.output / item.get('file', '')).resolve()
            if not path.is_relative_to(self.output.resolve()) or not path.is_file():
                continue
            try:
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != item['sha256']:
                    continue
                validate_attachment(data, path.suffix.lower())
            except (OSError, ValueError):
                continue
            return dict(item)
        return None

    def save_record(self, record, category):
        filename = record["record_id"] + ".json"
        target = self.output / category / filename
        target.parent.mkdir(exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
        for other in {"records", "quarantine", "excluded"} - {category}:
            (self.output / other / filename).unlink(missing_ok=True)

    def save_attachment(self, record, label, link, data, suffix):
        digest = hashlib.sha256(data).hexdigest()
        directory = self.output / 'attachments' / (
            safe_name(record['published_at'] or '日期未知', 10) + '_' +
            safe_name(record['doc_title'], 45) + '_' + record['record_id'][:10])
        directory.mkdir(parents=True, exist_ok=True)
        name = label or unquote(Path(urlsplit(link).path).name)
        if name.lower().endswith(suffix):
            name = name[:-len(suffix)]
        stem = safe_name(name, 65)
        target = directory / (stem + suffix)
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            target = directory / (stem + '_' + digest + suffix)
        if not target.exists():
            temporary = target.with_suffix(target.suffix + '.tmp')
            temporary.write_bytes(data)
            temporary.replace(target)
        return {'label': label, 'url': link,
                'file': target.relative_to(self.output).as_posix(),
                'sha256': digest, 'status': 'saved'}

    def export_attachments(self):
        fields = ['record_id', 'doc_title', 'source_url', 'record_state',
                  'label', 'url', 'file', 'sha256', 'status', 'error', 'etag', 'last_modified', 'checked_at']
        with (self.output / 'attachments.csv').open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for state in ('records', 'quarantine', 'excluded'):
                for path in sorted((self.output / state).glob('*.json')):
                    record = json.loads(path.read_text(encoding='utf-8'))
                    attachments = record.get('attachments') or []
                    if isinstance(attachments, str):
                        attachments = json.loads(attachments)
                    for attachment in attachments:
                        row = {key: record.get(key, '') for key in ('record_id', 'doc_title', 'source_url')}
                        row.update(record_state=state)
                        row.update({key: attachment.get(key, '') for key in fields[4:]})
                        writer.writerow(row)

    def request(self, url, headers=None):
        for attempt in range(1, 4):
            try:
                return self.request_once(url, headers) if headers else self.request_once(url)
            except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError,
                    requests.HTTPError) as exc:
                response = getattr(exc, 'response', None)
                status = response.status_code if response is not None else None
                if isinstance(exc, requests.HTTPError) and status not in {429, 500, 502, 503, 504}:
                    raise
                if attempt == 3:
                    raise
                delay = 2 ** attempt
                retry_after = response.headers.get('Retry-After') if response is not None else None
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        try:
                            delay = max(delay, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            pass
                if delay > 60:
                    self.log(status='retry_deferred', url=url, wait_seconds=delay,
                             reason='服务器要求等待超过60秒，请稍后重新运行')
                    raise
                self.log(status='request_retry', url=url, attempt=attempt,
                         wait_seconds=delay, error=str(exc), http_status=status)
                time.sleep(delay)

    def request_once(self, url, headers=None):
        if urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError("Only HTTP(S) URLs are supported")
        time.sleep(max(0, 2 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        response = self.session.get(url, timeout=(15, 60), allow_redirects=False,
                                    stream=True, headers=headers)
        try:
            if response.status_code == 304 and headers:
                return response, b''
            if 300 <= response.status_code < 400:
                raise ValueError("Redirect requires checking and configuring the final URL")
            response.raise_for_status()
            data = bytearray()
            for block in response.iter_content(65536):
                data.extend(block)
                if len(data) > 25 * 1024 * 1024:
                    raise ValueError("Resource exceeds 25 MB")
            return response, bytes(data)
        finally:
            response.close()

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

    def fetch(self, url, headers=None):
        if not self.allowed(url):
            raise ValueError("robots.txt disallows collection")
        return self.request(url, headers) if headers else self.request(url)

    def log(self, **event):
        self.counts[event["status"]] += 1
        if event["status"] in {"failed", "attachment_failed"}:
            self.errors.append(event)
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
        try:
            parsed_date = date.fromisoformat(published)
        except ValueError:
            parsed_date = None
        outside = False
        if parsed_date is None:
            issues.append("发布日期缺失或格式待核对")
        elif source.get("lookback_years") == 5 and parsed_date < five_years_ago(self.today):
            outside = True
            self.log(status="outside_date_range", url=url, published_at=published)
        elif parsed_date > self.today:
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
        previous = self.previous_attachments(record['record_id'])
        category = "excluded" if outside else ("quarantine" if issues else "records")
        if source.get("download_attachments") and not outside:
            seen_links = set()
            for label, link in links:
                if link in seen_links:
                    continue
                seen_links.add(link)
                suffix = Path(urlsplit(link).path).suffix.lower()
                if suffix not in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv"}:
                    continue
                if urlsplit(link).netloc != urlsplit(url).netloc:
                    continue
                try:
                    reusable = self.reusable_attachment(previous, link)
                    if reusable:
                        headers = {}
                        if reusable.get('etag'):
                            headers['If-None-Match'] = reusable['etag']
                        elif reusable.get('last_modified'):
                            headers['If-Modified-Since'] = reusable['last_modified']
                        response, attachment = self.fetch(link, headers) if headers else self.fetch(link)
                        if response is not None and response.status_code == 304:
                            reusable['label'] = label
                            reusable['checked_at'] = datetime.now(BEIJING).isoformat()
                            attachments.append(reusable)
                            self.log(status='attachment_not_modified', parent=url, url=link,
                                     file=reusable['file'])
                            continue
                    else:
                        response, attachment = self.fetch(link)
                    validate_attachment(attachment, suffix)
                    saved = self.save_attachment(record, label, link, attachment, suffix)
                    saved.update(etag=response.headers.get('ETag', '') if response is not None else '',
                                 last_modified=response.headers.get('Last-Modified', '') if response is not None else '',
                                 checked_at=datetime.now(BEIJING).isoformat())
                    attachments.append(saved)
                    self.log(status="attachment_saved", parent=url, url=link,
                             label=label, file=saved['file'])
                except Exception as exc:
                    attachments.append({"label": label, "url": link,
                                        "status": "failed", "error": str(exc)})
                    self.log(status="attachment_failed", url=link, error=str(exc))
        record["attachments"] = json.dumps(attachments, ensure_ascii=False)
        self.save_record(record, category)
        self.log(status={"records": "saved", "quarantine": "quarantined", "excluded": "excluded"}[category],
                 url=url, content_hash=digest)
        return soup

    def run(self, sources):
        failures = 0
        if not self.resume:
            self.tasks = []
            self.checkpoint()
        if self.resume:
            path = self.output / 'tasks.json'
            if not path.exists():
                raise ValueError('No tasks.json found; run a normal collection first')
            self.tasks = json.loads(path.read_text(encoding='utf-8-sig'))
            enabled = {source['id']: source for source in sources if source.get('enabled', False)}
            for task in self.tasks:
                if task['source']['id'] not in enabled or task['status'] == 'completed':
                    continue
                source = enabled[task['source']['id']]
                if urlsplit(task['url']).netloc != urlsplit(source['url']).netloc:
                    self.log(status='failed', url=task['url'], error='Resume task domain differs from configured source')
                    continue
                task['source'] = source
                self.execute_task(task)
            sources = []
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
                listing_url = source['url']
                visited = {listing_url}
                for _ in range(max(0, source.get('max_list_pages', 1) - 1)):
                    next_selector = source.get('next_page_selector')
                    if source.get('pagination') == 'wcm':
                        next_url = wcm_next(soup, listing_url)
                    else:
                        node = soup.select_one(next_selector) if next_selector else None
                        next_url = urljoin(listing_url, node['href']) if node and node.get('href') else None
                    if not next_url:
                        break
                    if next_url in visited or urlsplit(next_url).netloc != urlsplit(source['url']).netloc:
                        break
                    visited.add(next_url)
                    listing_url = next_url
                    soup = self.page({**source, 'page_type': 'listing'}, listing_url)
                    if selector:
                        details.extend(urljoin(listing_url, a['href'])
                                       for a in soup.select(selector) if a.get('href'))
                unique_details = list(dict.fromkeys(details))
                self.coverage.append({'source_id': source['id'], 'list_pages': len(visited),
                                      'discovered_details': len(unique_details),
                                      'selected_details': min(len(unique_details), source.get('max_details', 10)),
                                      'detail_limit_reached': len(unique_details) > source.get('max_details', 10)})
                selected = []
                for url in unique_details[:source.get("max_details", 10)]:
                    if urlsplit(url).netloc != urlsplit(source["url"]).netloc:
                        continue
                    task = {'url': url, 'source': source, 'status': 'pending'}
                    self.tasks.append(task)
                    selected.append(task)
                self.checkpoint()
                for task in selected:
                    self.execute_task(task)
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
        self.export_attachments()
        failures = len(self.errors)
        summary = {"finished_at": datetime.now(BEIJING).isoformat(),
                   "date_from": five_years_ago(self.today).isoformat(),
                   "date_to": self.today.isoformat(), "counts": dict(self.counts),
                   "status": "partial_failure" if failures else (
                       "needs_review" if self.counts["quarantined"] else "success"),
                   "errors": self.errors,
                   "sources": self.coverage,
                   "mode": 'resume' if self.resume else 'normal',
                   "task_counts": dict(Counter(task['status'] for task in self.tasks)),
                   "coverage": "仅覆盖配置的列表页数与详情数量；不代表五年全量"}
        (self.output / "run_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        message = f"状态：{summary['status']}\n本次事件统计：{dict(self.counts)}\n失败数：{failures}\n{summary['coverage']}\n"
        (self.output / "run_summary.txt").write_text(message, encoding="utf-8")
        print(message)
        return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/sources.json")
    parser.add_argument("--output", default="output")
    parser.add_argument('--force-attachments', action='store_true',
                        help='Redownload attachments even when verified local copies exist')
    parser.add_argument('--resume', action='store_true', help='Retry unfinished details from tasks.json without fetching lists')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    raise SystemExit(1 if Collector(args.output, args.force_attachments, args.resume).run(config["sources"]) else 0)

import json
import csv
import tempfile
import unittest
import requests
from datetime import date
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup

from collector import Collector, five_years_ago, safe_name, wcm_next


class CollectorTests(unittest.TestCase):
    def test_resume_retries_only_unfinished_details(self):
        source = {'id': 'test', 'enabled': True, 'url': 'https://example.org/list/'}
        with tempfile.TemporaryDirectory() as output:
            initial = Collector(output)
            initial.tasks = [{'source': source, 'url': 'https://example.org/' + state, 'status': state}
                             for state in ('completed', 'pending', 'running', 'failed')]
            initial.checkpoint()
            resumed = Collector(output, resume=True)
            with patch.object(resumed, 'page') as page:
                resumed.run([source])
                self.assertEqual([call.args[1] for call in page.call_args_list],
                    ['https://example.org/pending', 'https://example.org/running', 'https://example.org/failed'])
            saved = json.loads((Path(output) / 'tasks.json').read_text())
            self.assertTrue(all(task['status'] == 'completed' for task in saved))

    def test_attachment_failure_keeps_task_retryable(self):
        source = {'id': 'test', 'enabled': True, 'url': 'https://example.org/list/'}
        with tempfile.TemporaryDirectory() as output:
            collector = Collector(output)
            task = {'source': source, 'url': 'https://example.org/a', 'status': 'pending'}
            collector.tasks = [task]
            with patch.object(collector, 'page', side_effect=lambda *args: collector.log(
                    status='attachment_failed', url='https://example.org/a.pdf', error='timeout')):
                collector.execute_task(task)
            self.assertEqual(task['status'], 'failed')

    def test_verified_reuse_and_corruption_recovery(self):
        html = b'<meta name="PubDate" content="2020-01-01"><article>text<a href="a.pdf">report</a></article>'
        source = {'id': 'test', 'url': 'https://example.org/a', 'resource_type': 'test',
                  'body_selector': 'article', 'min_content_chars': 1, 'download_attachments': True}
        with tempfile.TemporaryDirectory() as output:
            collector = Collector(output)
            response = requests.Response()
            response.status_code = 200
            response.headers['ETag'] = '"v1"'
            not_modified = requests.Response()
            not_modified.status_code = 304
            with patch.object(collector, 'fetch', side_effect=[(None, html), (response, b'%PDF-test')]):
                collector.page(source, source['url'])
            with patch.object(collector, 'fetch', side_effect=[(None, html), (not_modified, b'')]) as fetch:
                collector.page(source, source['url'])
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(fetch.call_args.args[1], {'If-None-Match': '"v1"'})
                self.assertEqual(collector.counts['attachment_not_modified'], 1)
            local = next((Path(output) / 'attachments').rglob('*.pdf'))
            local.write_bytes(b'corrupted')
            with patch.object(collector, 'fetch', side_effect=[(None, html), (None, b'%PDF-test')]) as fetch:
                collector.page(source, source['url'])
                self.assertEqual(fetch.call_count, 2)
            collector.force_attachments = True
            with patch.object(collector, 'fetch', side_effect=[(None, html), (None, b'%PDF-updated')]) as fetch:
                collector.page(source, source['url'])
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(len(fetch.call_args.args), 1)

    def test_retry_recovery_and_exhaustion(self):
        with tempfile.TemporaryDirectory() as output:
            collector = Collector(output)
            with patch.object(collector, 'request_once', side_effect=[requests.Timeout('slow'), (None, b'ok')]) as request, patch('collector.time.sleep'):
                self.assertEqual(collector.request('https://example.org'), (None, b'ok'))
                self.assertEqual(request.call_count, 2)
            with patch.object(collector, 'request_once', side_effect=requests.Timeout('slow')) as request, patch('collector.time.sleep'):
                with self.assertRaises(requests.Timeout):
                    collector.request('https://example.org')
                self.assertEqual(request.call_count, 3)

    def test_no_retry_for_forbidden_and_long_retry_after(self):
        for status, headers in [(403, {}), (429, {'Retry-After': '120'})]:
            with tempfile.TemporaryDirectory() as output:
                collector = Collector(output)
                response = requests.Response()
                response.status_code = status
                response.headers.update(headers)
                error = requests.HTTPError('blocked', response=response)
                with patch.object(collector, 'request_once', side_effect=error) as request, patch('collector.time.sleep') as sleep:
                    with self.assertRaises(requests.HTTPError):
                        collector.request('https://example.org')
                    self.assertEqual(request.call_count, 1)
                    sleep.assert_not_called()

    def test_wcm_pagination(self):
        soup = BeautifulSoup('<script>createPage(2, 0, "index", "html");</script>', 'html.parser')
        self.assertEqual(wcm_next(soup, 'https://example.org/list/'), 'https://example.org/list/index_1.html')
        soup = BeautifulSoup('<script>createPage(2, 1, "index", "html");</script>', 'html.parser')
        self.assertIsNone(wcm_next(soup, 'https://example.org/list/index_1.html'))
        with self.assertRaises(ValueError):
            wcm_next(BeautifulSoup('', 'html.parser'), 'https://example.org/')

    def test_pagination_deduplicates_and_stops_loop(self):
        source = {'id': 'test', 'enabled': True, 'url': 'https://example.org/list/',
                  'page_type': 'listing', 'list_link_selector': 'a.detail',
                  'next_page_selector': 'a.next', 'max_list_pages': 4, 'max_details': 5}
        first = BeautifulSoup('<a class="detail" href="/a"></a><a class="next" href="page2.html"></a>', 'html.parser')
        second = BeautifulSoup('<a class="detail" href="/a"></a><a class="detail" href="/b"></a><a class="next" href="./"></a>', 'html.parser')
        with tempfile.TemporaryDirectory() as output:
            collector = Collector(output)
            with patch.object(collector, 'page', side_effect=[first, second, first, first]) as page:
                self.assertEqual(collector.run([source]), 0)
                self.assertEqual([c.args[1] for c in page.call_args_list],
                                 ['https://example.org/list/', 'https://example.org/list/page2.html',
                                  'https://example.org/a', 'https://example.org/b'])

    def test_readable_names_and_conflicts(self):
        self.assertEqual(safe_name('CON'), '_CON')
        self.assertNotIn('/', safe_name('../../危险:*文件'))
        self.assertLessEqual(len(safe_name('长' * 200)), 70)
        with tempfile.TemporaryDirectory() as output:
            collector = Collector(output)
            record = {'record_id': 'a' * 64, 'published_at': '2026-11-17',
                      'doc_title': '抽检公告'}
            first = collector.save_attachment(record, '不合格信息.xlsx', 'https://example.org/a.xlsx', b'one', '.xlsx')
            repeated = collector.save_attachment(record, '不合格信息.xlsx', 'https://example.org/a.xlsx', b'one', '.xlsx')
            changed = collector.save_attachment(record, '不合格信息.xlsx', 'https://example.org/a.xlsx', b'two', '.xlsx')
            self.assertEqual(first['file'], repeated['file'])
            self.assertNotEqual(first['file'], changed['file'])
            self.assertEqual((Path(output) / first['file']).read_bytes(), b'one')
            self.assertIn('不合格信息.xlsx', first['file'])
            record['attachments'] = json.dumps([first, {'label': '失败文件', 'status': 'failed', 'error': 'timeout'}])
            collector.save_record(record, 'quarantine')
            collector.export_attachments()
            with (Path(output) / 'attachments.csv').open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['record_state'], 'quarantine')
            self.assertEqual(rows[0]['sha256'], first['sha256'])
            self.assertEqual(rows[1]['error'], 'timeout')

    def test_calendar_window(self):
        self.assertEqual(five_years_ago(date(2026, 11, 17)), date(2021, 11, 17))
        self.assertEqual(five_years_ago(date(2024, 2, 29)), date(2019, 2, 28))

    def test_record_moves_between_states(self):
        with tempfile.TemporaryDirectory() as output:
            collector = Collector(output)
            record = {"record_id": "example"}
            for state in ["records", "quarantine", "records", "excluded"]:
                collector.save_record(record, state)
                files = list(Path(output).glob("*/*.json"))
                self.assertEqual(files, [Path(output) / state / "example.json"])

    def test_attachment_failure_summary_and_invalid_date(self):
        source = {"id": "test", "url": "https://example.org/a", "enabled": True,
                  "resource_type": "抽检公告", "body_selector": "article",
                  "download_attachments": True, "min_content_chars": 1,
                  "lookback_years": 5}
        with tempfile.TemporaryDirectory() as output:
            collector = Collector(output)
            collector.today = date(2026, 11, 17)
            html = b'<meta name="PubDate" content="2026-02-30"><article>text<a href="file.xlsx">file</a></article>'
            with patch.object(collector, "fetch", side_effect=[(None, html), RuntimeError("timeout")]):
                self.assertEqual(collector.run([source]), 1)
            summary = json.loads((Path(output) / "run_summary.json").read_text())
            self.assertEqual(summary["counts"]["attachment_failed"], 1)
            self.assertEqual(summary["counts"]["quarantined"], 1)
            self.assertEqual(summary["status"], "partial_failure")
            self.assertEqual(len(list((Path(output) / "records").glob("*.json"))), 0)


if __name__ == "__main__":
    unittest.main()

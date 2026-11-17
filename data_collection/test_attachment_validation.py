import io
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from attachment_validation import validate_attachment
from collector import Collector


class AttachmentValidationTests(unittest.TestCase):
    def test_office_container_matches_extension(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('[Content_Types].xml', '<Types/>')
            archive.writestr('xl/workbook.xml', '<workbook/>')
        validate_attachment(stream.getvalue(), '.xlsx')
        with self.assertRaises(ValueError):
            validate_attachment(stream.getvalue(), '.docx')

    def test_bad_payloads_rejected(self):
        for data, suffix in [(b'', '.pdf'), (b'<html>denied</html>', '.xlsx'),
                             (b'not zip', '.xlsx'), (b'not pdf', '.pdf'),
                             (b'not office', '.xls'), (b'abc\x00', '.csv')]:
            with self.subTest(suffix=suffix, data=data), self.assertRaises(ValueError):
                validate_attachment(data, suffix)

    def test_invalid_download_reported_without_saving(self):
        html = b'<meta name="PubDate" content="2020-01-01"><article>text<a href="a.xlsx">download</a></article>'
        source = {'id': 'test', 'enabled': True, 'url': 'https://example.org/a',
                  'resource_type': 'test', 'body_selector': 'article',
                  'min_content_chars': 1, 'download_attachments': True}
        with tempfile.TemporaryDirectory() as output:
            collector = Collector(output)
            with patch.object(collector, 'fetch', side_effect=[(None, html), (None, b'<html>error</html>')]), patch.object(collector, 'save_attachment') as save:
                self.assertEqual(collector.run([source]), 1)
                save.assert_not_called()
                self.assertEqual(collector.counts['attachment_failed'], 1)

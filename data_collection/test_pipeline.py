import csv
import tempfile
import unittest
from pathlib import Path
from pipeline import report


class PipelineTests(unittest.TestCase):
    def test_report_separates_review_from_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'extracted').mkdir()
            with (root / 'extracted/inspection_rows.csv').open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=['product', 'parse_status'])
                writer.writeheader()
                writer.writerow({'product': '酱油', 'parse_status': '多样本检测方案，需人工核对'})
            extraction = {'rows': 1, 'items': 1, 'issues': []}
            self.assertEqual(report(root, {}, extraction), '完成，有内容待核对')
            self.assertIn('酱油', (root / 'review_required.csv').read_text(encoding='utf-8-sig'))
            self.assertEqual(report(root, {'errors': ['failure']}, extraction), '有失败，请检查')

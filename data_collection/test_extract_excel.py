import tempfile
import unittest
import zipfile
import json
import csv
from unittest.mock import patch
from pathlib import Path

from extract_excel import sheets, extract, parse_items, business_values


class ExcelTests(unittest.TestCase):
    def test_business_fields_do_not_guess_combined_dates_or_category(self):
        fields = business_values({'B': '标识生产企业名称', 'I': '生产日期/批号'},
                                 {'B': '某食品厂', 'I': '2026-01-01/批次A'}, 7)
        self.assertEqual(fields['manufacturer'], '某食品厂')
        self.assertEqual(fields['production_date_or_batch'], '2026-01-01/批次A')
        self.assertEqual(fields['production_date'], '')
        self.assertEqual(fields['batch_no'], '')
        self.assertEqual(fields['food_category'], '')
        self.assertEqual(json.loads(fields['field_cells'])['manufacturer'], 'B7')

    def test_multi_items_preserve_limits_and_reject_ambiguous_text(self):
        sample = '菌落总数║1.0×104；3.4×105；1.9×105CFU/mL║n=5，c=2，m=5000，M=50000CFU/mL'
        self.assertEqual(parse_items(sample), [sample.split('║')])
        self.assertEqual(parse_items('铅║0.2mg/kg║≤0.1mg/kg；菌落总数║100CFU/g║不得检出'),
                         [['铅', '0.2mg/kg', '≤0.1mg/kg'], ['菌落总数', '100CFU/g', '不得检出']])
        self.assertEqual(parse_items('项目║结果║标准\n解释说明'), [])
        self.assertEqual(parse_items('项目║║标准'), [])
        self.assertEqual(parse_items(''), [])

    def test_coverage_accounts_for_every_row_and_reports_skip(self):
        def cells(row, values):
            return {f'{column}{row}': {'value': value, 'formula': False}
                    for column, value in values.items()}
        rows = [(1, cells(1, {'A': '标题'})), (2, cells(2, {'A': '序号', 'B': '食品名称'})),
                (3, cells(3, {'A': '1', 'B': '酱油'})),
                (4, cells(4, {'A': '2', 'B': ''})), (5, cells(5, {'A': ''}))]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'records').mkdir()
            record = {'record_id': 'test', 'doc_title': '公告', 'source_url': 'https://example.org',
                      'attachments': [{'status': 'saved', 'file': 'test.xlsx'}]}
            (root / 'records/test.json').write_text(json.dumps(record), encoding='utf-8')
            with patch('extract_excel.sheets', return_value=[('表1', rows)]):
                report = extract(root)
            stats = report['sheets'][0]
            self.assertEqual(stats['total_rows'], sum(stats[k] for k in (
                'blank_rows', 'header_rows', 'before_header_rows', 'output_rows', 'skipped_rows')))
            self.assertEqual(stats['skipped_rows'], 1)
            self.assertEqual(report['status'], 'needs_review')
            with (root / 'extracted/skipped_rows.csv').open(encoding='utf-8-sig', newline='') as handle:
                skipped = list(csv.DictReader(handle))
            self.assertEqual(skipped[-1]['row'], '4')
            self.assertEqual(skipped[-1]['reason'], '缺产品名称')

    def test_actual_coordinates_inline_strings_and_formula_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.xlsx'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="检查表" r:id="r1"/></sheets></workbook>')
                z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
                z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="7"><c r="F7" t="inlineStr"><is><t>酱油</t></is></c><c r="J7"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>')
            name, rows = list(sheets(path))[0]
            self.assertEqual(name, '检查表')
            self.assertEqual(rows[0][0], 7)
            self.assertEqual(rows[0][1]['F7']['value'], '酱油')
            self.assertEqual(rows[0][1]['J7'], {'value': '2', 'formula': True})

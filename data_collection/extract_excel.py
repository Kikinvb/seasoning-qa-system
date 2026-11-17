"""Read-only XLSX extraction with source-cell provenance; no compliance judgment."""
import argparse
import csv
import json
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
BUSINESS_FIELDS = {
    'manufacturer': ['标称生产企业名称', '标识生产企业名称'],
    'manufacturer_address': ['标称生产企业地址', '标识生产企业地址'],
    'sampled_unit': ['被抽样单位名称'], 'sampled_address': ['被抽样单位地址'],
    'sampled_province': ['被抽样单位所在省份'], 'sampled_district': ['被抽样单位所在区/县'],
    'specification': ['规格型号', '规格'], 'brand': ['商标'],
    'production_date': ['生产日期'], 'batch_no': ['批号'],
    'production_date_or_batch': ['生产日期/批号'],
    'food_category': ['食品类别', '食品分类'],
    'test_agency': ['检验机构'], 'tested_items_raw': ['检验项目'], 'remarks': ['备注']}


def business_values(headers, values, row):
    normalized = {re.sub(r'\s+', '', title): col for col, title in headers.items()}
    result, locations = {}, {}
    for field, aliases in BUSINESS_FIELDS.items():
        column = next((normalized[a] for a in aliases if a in normalized), None)
        result[field] = values.get(column, '') if column else ''
        if column:
            locations[field] = f'{column}{row}'
    result['field_cells'] = json.dumps(locations, ensure_ascii=False)
    return result


def parse_items(raw):
    if not raw.strip():
        return []
    # Semicolons can separate measurements of ONE item, not only different items.
    single = [part.strip() for part in raw.split('║')]
    if len(single) == 3 and all(single) and not any('\n' in part or '\r' in part for part in single):
        return [single]
    segments = [part.strip() for part in re.split(r'[\r\n；;]+', raw) if part.strip()]
    items = []
    for segment in segments:
        parts = [part.strip() for part in segment.split('║')]
        if len(parts) != 3 or not all(parts):
            return []
        items.append(parts)
    return items


def sheets(path):
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > 150 * 1024 * 1024:
            raise ValueError('Uncompressed XLSX exceeds 150 MB')
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(n.itertext()) for n in ET.fromstring(
                archive.read('xl/sharedStrings.xml')).findall('m:si', NS)]
        relations = {n.get('Id'): n.get('Target') for n in ET.fromstring(
            archive.read('xl/_rels/workbook.xml.rels')) if n.get('TargetMode') != 'External'}
        for sheet in ET.fromstring(archive.read('xl/workbook.xml')).findall('m:sheets/m:sheet', NS):
            target = relations[sheet.get('{' + REL + '}id')]
            target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            rows = []
            for row in ET.fromstring(archive.read(target)).findall('.//m:sheetData/m:row', NS):
                cells = {}
                for cell in row:
                    value = cell.find('m:v', NS)
                    text = value.text or '' if value is not None else ''
                    if cell.get('t') == 's':
                        text = strings[int(text)]
                    elif cell.get('t') == 'inlineStr':
                        text = ''.join(cell.find('m:is', NS).itertext())
                    cells[cell.get('r')] = {'value': text,
                                          'formula': cell.find('m:f', NS) is not None}
                rows.append((int(row.get('r')), cells))
            yield sheet.get('name'), rows


def extract(output):
    output = Path(output).resolve()
    destination = output / 'extracted'
    destination.mkdir(exist_ok=True)
    fields = ['record_id', 'doc_title', 'source_url', 'attachment_name', 'attachment_url',
              'attachment_file', 'sheet', 'row', 'product', 'batch', 'item',
              'test_result', 'standard_value', 'result_cell', 'raw_result', 'parse_status', 'raw_cells']
    fields += list(BUSINESS_FIELDS) + ['field_cells']
    report = {'files': 0, 'rows': 0, 'issues': [], 'sheets': [], 'skipped_rows': []}
    with (destination / 'inspection_rows.csv').open('w', encoding='utf-8-sig', newline='') as handle, \
            (destination / 'inspection_items.csv').open('w', encoding='utf-8-sig', newline='') as item_handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        item_writer = csv.DictWriter(item_handle, fieldnames=fields + ['item_seq'])
        item_writer.writeheader()
        report['items'] = 0
        report['unparsed_result_rows'] = 0
        report['sampling_plan_rows'] = 0
        for path in sorted((output / 'records').glob('*.json')):
            record = json.loads(path.read_text(encoding='utf-8-sig'))
            attachments = record.get('attachments') or []
            if isinstance(attachments, str):
                attachments = json.loads(attachments)
            for attachment in attachments:
                if attachment.get('status') != 'saved' or not attachment.get('file', '').lower().endswith('.xlsx'):
                    continue
                try:
                    local = (output / attachment['file']).resolve()
                    if not local.is_relative_to(output):
                        raise ValueError('Attachment outside output directory')
                    report['files'] += 1
                    for name, rows in sheets(local):
                        headers = None
                        coverage = {'file': attachment['file'], 'sheet': name,
                                    'total_rows': len(rows), 'blank_rows': 0, 'header_rows': 0,
                                    'before_header_rows': 0, 'output_rows': 0, 'skipped_rows': 0}
                        report['sheets'].append(coverage)
                        for number, cells in rows:
                            values = {re.sub(r'\d+', '', key): c['value'] for key, c in cells.items()}
                            if not any(v.strip() for v in values.values()):
                                coverage['blank_rows'] += 1
                                continue
                            if any(v in ('食品名称', '标称产品名称') for v in values.values()) and '序号' in values.values():
                                headers = values
                                coverage['header_rows'] += 1
                                continue
                            if headers is None:
                                coverage['before_header_rows'] += 1
                                report['skipped_rows'].append({'file': attachment['file'], 'sheet': name,
                                    'row': number, 'reason': '表头前内容或未识别表头',
                                    'raw_cells': json.dumps(cells, ensure_ascii=False)})
                                continue
                            def field(fragment):
                                return next((values.get(col, '') for col, title in headers.items() if fragment in title), '')
                            product = field('食品名称') or field('标称产品名称')
                            if not product or not field('序号').isdigit():
                                coverage['skipped_rows'] += 1
                                report['skipped_rows'].append({'file': attachment['file'], 'sheet': name,
                                    'row': number, 'reason': '缺产品名称' if not product else '序号不是纯数字',
                                    'raw_cells': json.dumps(cells, ensure_ascii=False)})
                                continue
                            result_col = next((col for col, title in headers.items() if '不合格项目' in title), '')
                            raw = values.get(result_col, '')
                            items = parse_items(raw)
                            if raw.strip() and not items:
                                report['unparsed_result_rows'] += 1
                            parsed = len(items) == 1
                            parts = items[0] if parsed else []
                            status = '待核对' if raw and not parsed else ('已拆分待审核' if parsed else '无不合格项目列')
                            if len(items) > 1:
                                status = '多项目已拆分待审核，见inspection_items.csv'
                            if items and any(re.search(r'\bn\s*=\s*\d+', standard) for _, _, standard in items):
                                status = '多样本检测方案，需人工核对'
                                report['sampling_plan_rows'] += 1
                            if any(c['formula'] for c in cells.values()):
                                status = '含公式缓存值，待核对'
                            extracted_row = dict(record_id=record['record_id'], doc_title=record['doc_title'],
                                source_url=record['source_url'], attachment_name=attachment.get('label', ''),
                                attachment_url=attachment.get('url', ''), attachment_file=attachment['file'],
                                sheet=name, row=number, product=product, batch=field('生产日期'),
                                item=parts[0] if parsed else '', test_result=parts[1] if parsed else '',
                                standard_value=parts[2] if parsed else '', result_cell=f'{result_col}{number}' if result_col else '',
                                raw_result=raw, parse_status=status, raw_cells=json.dumps(cells, ensure_ascii=False))
                            extracted_row.update(business_values(headers, values, number))
                            writer.writerow(extracted_row)
                            for index, (item, result, standard) in enumerate(items, 1):
                                item_writer.writerow({**extracted_row, 'item': item,
                                    'test_result': result, 'standard_value': standard, 'item_seq': index})
                                report['items'] += 1
                            report['rows'] += 1
                            coverage['output_rows'] += 1
                        if coverage['skipped_rows']:
                            report['issues'].append({'file': attachment['file'], 'sheet': name,
                                'error': '表头后存在跳过行，需核查', 'count': coverage['skipped_rows']})
                        if headers is None and any(c['value'].strip() for _, cells in rows for c in cells.values()):
                            report['issues'].append({'file': attachment['file'], 'sheet': name, 'error': '未识别抽检表头'})
                except Exception as exc:
                    report['issues'].append({'file': attachment['file'], 'error': str(exc)})
    for filename, entries, columns in [
        ('sheet_coverage.csv', report['sheets'], ['file', 'sheet', 'total_rows', 'blank_rows', 'header_rows', 'before_header_rows', 'output_rows', 'skipped_rows']),
        ('skipped_rows.csv', report.pop('skipped_rows'), ['file', 'sheet', 'row', 'reason', 'raw_cells'])]:
        with (destination / filename).open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(entries)
    report['status'] = 'needs_review' if report['issues'] or report['unparsed_result_rows'] or report['sampling_plan_rows'] else 'completed_pending_review'
    (destination / 'extraction_summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'sheets'}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='output')
    args = parser.parse_args()
    raise SystemExit(1 if extract(args.output)['issues'] else 0)

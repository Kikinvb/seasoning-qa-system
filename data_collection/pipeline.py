"""One-command collection, local extraction and human-readable review report."""
import argparse
import csv
import json
from pathlib import Path

from collector import Collector
from extract_excel import extract


def report(output, collection, extraction):
    output = Path(output)
    with (output / 'extracted/inspection_rows.csv').open(encoding='utf-8-sig', newline='') as handle:
        pending = [row for row in csv.DictReader(handle)
                   if '待核对' in row['parse_status'] or '需人工' in row['parse_status']]
    fields = ['product', 'parse_status', 'raw_result', 'attachment_file',
              'sheet', 'row', 'result_cell', 'source_url', 'attachment_url']
    with (output / 'review_required.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(pending)
    failures = collection.get('errors', [])
    issues = extraction['issues']
    status = '有失败，请检查' if failures or issues else ('完成，有内容待核对' if pending else '完成，仍需抽查')
    lines = ['# 本轮处理结果', '', f'- 结果：{status}',
             f'- 本次采集统计：{collection.get("counts", {})}',
             f'- 已保存资料中的产品记录：{extraction["rows"]}',
             f'- 检测项目明细：{extraction["items"]}',
             f'- 待核对产品记录：{len(pending)}（见 review_required.csv）',
             f'- 表格读取/覆盖问题：{len(issues)}（见 extracted/extraction_summary.json）',
             '', '## 本次采集范围', '']
    for source in collection.get('sources', []):
        lines.append(f'- {source["source_id"]}：访问 {source["list_pages"]} 页，发现 {source["discovered_details"]} 篇，选取 {source["selected_details"]} 篇；数量上限截断：{source["detail_limit_reached"]}')
    if collection.get('mode') == 'resume':
        lines.append('- 本次为恢复模式，没有重新检查列表或发现新增公告。')
    if collection.get('mode') == 'local_only':
        lines.append('- 本次仅整理本地文件，没有访问网站；不能据此判断远端采集是否成功。')
    lines += ['', '## 工作人员接下来做什么', '',
              '1. 有失败先看 run_summary.json 的 errors；确认原因后使用恢复命令。',
              '2. 打开 review_required.csv，按附件、工作表及行号回到原文核对。',
              '3. 查看 extracted/skipped_rows.csv，区别标题说明与可能漏掉的数据。',
              '4. 抽查产品、日期、检测值和单位；没有异常也不代表业务审核通过。',
              '', '说明：提取统计包含当前已保存的全部正常档案，可能含历史资料；采集失败时旧资料仍可能存在。',
              '当前只整理 XLSX；其他类型保留原件，未进入表格明细。当前公开列表不等于五年历史完整覆盖。']
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config/sources.json')
    parser.add_argument('--output', default='output')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--force-attachments', action='store_true')
    parser.add_argument('--local-only', action='store_true', help='Extract existing files without accessing websites')
    args = parser.parse_args()
    output = Path(args.output)
    if args.local_only:
        collection = {'mode': 'local_only', 'counts': {}, 'errors': []}
    else:
        config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        Collector(output, args.force_attachments, args.resume).run(config['sources'])
        collection = json.loads((output / 'run_summary.json').read_text(encoding='utf-8'))
    extraction = extract(output)
    print(report(output, collection, extraction))
    print(f'请查看：{output / "REPORT.md"}')
    return 1 if collection.get('errors') or extraction['issues'] else 0


if __name__ == '__main__':
    raise SystemExit(main())

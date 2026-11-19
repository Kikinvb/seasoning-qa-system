import { readFileSync, writeFileSync } from 'node:fs';

// Keep the upstream checkout intact. Fail the build if its integration points change.
function edit(path, replacements) {
  let source = readFileSync(path, 'utf8').replaceAll('\r\n', '\n');
  for (const [target, replacement] of replacements) {
    if (!source.includes(target)) throw new Error(`Cannot integrate ${path}: ${target}`);
    source = source.replace(target, replacement);
  }
  writeFileSync(path, source);
}

edit('server/app.ts', [
  ["import express from 'express';", "import express from 'express';\nimport { installIdentity } from './identity.js';"],
  ["  const failures = new Map", "  installIdentity(app, db);\n  const failures = new Map"],
  ["    const token = (req.headers.cookie || '')", "    if (req.user) return next();\n    const token = (req.headers.cookie || '')"],
  ['      crawlState: crawlState(db),', "      crawlState: crawlState(db),\n      schedulerEnabled: process.env.SCHEDULER_ENABLED !== 'false',"],
]);

edit('src/tasks.tsx', [
  ["fetch('/api' + path)", "fetch('/api/warning' + path)"],
  ["value.error || '加载失败'", "value.error || value.detail || '加载失败'"],
  ['<p>自动采集：每 24 小时 · 下次计划：{full(state?.nextRunAt)}</p>',
    "<p>{overview?.schedulerEnabled === false ? '自动采集已关闭，可手动发起试采。' : '自动采集：每 24 小时 · 下次计划：' + full(state?.nextRunAt)}</p>"],
]);

edit('server/pipeline.ts', [
  ["import { canonicalUrl, fingerprint, fetchHtml, type extractArticle } from './crawler.js';",
    "import { canonicalUrl, fingerprint, fetchHtml, type extractArticle } from './crawler.js';\nimport { parseAttachmentInProcess } from './attachment-process.js';"],
  ['        const content=await (await pdf.getPage(p)).getTextContent();',
    "        if (p > 150) throw new Error('PDF页数超过自动解析限制，需人工核查');\n        const content=await (await pdf.getPage(p)).getTextContent();"],
  ['    const rows=XLSX.utils.sheet_to_json<any[]>(book.Sheets[name]', `    const sheet=book.Sheets[name];
    if (!sheet['!ref']) continue;
    const range=XLSX.utils.decode_range(sheet['!ref']);
    const cells=(range.e.r-range.s.r+1)*(range.e.c-range.s.c+1);
    if (!Number.isSafeInteger(cells) || cells < 1 || cells > 250000)
      throw new Error('Excel工作表范围过大，需人工核查');
    const rows=XLSX.utils.sheet_to_json<any[]>(sheet`],
  ['    const text=await attachmentText(await fetchBinary(a.url),a.url);',
    '    const text=await parseAttachmentInProcess(await fetchBinary(a.url),a.url);'],
]);

edit('src/failures.tsx', [
  ['fetch(`/api/admin/failures?page=', 'fetch(`/api/warning/admin/failures?page='],
  ['fetch(`/api/admin/failures/${i.id}/retry', 'fetch(`/api/warning/admin/failures/${i.id}/retry'],
  ['new Error(v.error);setData(v);', "new Error(v.error || v.detail || '加载失败');setData(v);setError('');"],
]);

edit('vite.config.ts', [
  ['  plugins:', "  base: '/api/warning-ui/',\n  plugins:"],
]);

edit('index.html', [
  ['食安瞭望 · 食品安全预警系统', '调味品安全风险监测预警及问答系统'],
]);

edit('server/model.ts', [
  ['      temperature: 0.1,', `      temperature: 0.1,
      ...(new URL(base).origin === 'https://api.deepseek.com' ? {
        thinking: { type: 'disabled' },
        response_format: { type: 'json_object' },
      } : {}),`],
]);

edit('src/main.tsx', [
  ["import './styles.css';", "import './styles.css';\nimport './theme.css';"],
  ["fetch('/api' + path", "fetch('/api/warning' + path"],
  ['          <section className="panel">\n            <div className="section-heading">\n              <h2>模型与分析提示词</h2>',
    '          {!embeddedTab && <section className="panel">\n            <div className="section-heading">\n              <h2>模型与分析提示词</h2>'],
  ["          </section>\n        </div>\n      )}\n      {tab === 'users'", "          </section>}\n        </div>\n      )}\n      {tab === 'users'"],
  ['          <span className="eyebrow">SAFETY INTELLIGENCE / 风险动态</span>\n          <h1>\n            食品安全预警\n            <span className="live">\n              <i /> 实时关注\n            </span>\n          </h1>\n          <p>从新闻中发现风险，让关注更有依据。</p>',
    '          <h1>调味品安全风险监测预警</h1>\n          <p>查看已发布的风险预警、涉及产品及原文来源。</p>'],
  ['每 {data.intervalHours || 24} 小时自动采集', '采集间隔设置：{data.intervalHours || 24} 小时'],
  ['近期预警动态 <span>RECENT ALERTS</span>', '近期风险预警'],
  ['            <p>聚焦具体对象，关注风险变化</p>\n', ''],
  ["  const [autoScroll, setAutoScroll] = useState(true);", "  const [autoScroll, setAutoScroll] = useState(false);"],
  ["onClick={() => setAutoScroll((v) => !v)}", 'aria-pressed={autoScroll} onClick={() => setAutoScroll((v) => !v)}'],
  ["className={filter === 'all' ? 'active' : ''} onClick", "className={filter === 'all' ? 'active' : ''} aria-pressed={filter === 'all'} onClick"],
  ["className={filter === 'unread' ? 'active' : ''} onClick", "className={filter === 'unread' ? 'active' : ''} aria-pressed={filter === 'unread'} onClick"],
  ["function Admin({ notify }: { notify: (s: string) => void }) {\n  const [tab, setTab] = useState('overview');",
    "function Admin({ notify, embeddedTab }: { notify: (s: string) => void; embeddedTab?: string }) {\n  const [tab, setTab] = useState(embeddedTab ?? 'overview');"],
  ['      <div className="page-heading">\n        <div>\n          <span className="eyebrow">DEVELOPER WORKSPACE',
    '      {!embeddedTab && <> <div className="page-heading">\n        <div>\n          <span className="eyebrow">DEVELOPER WORKSPACE'],
  ['      {error && <div className="error">{error}</div>}\n      {tab', '      </>}\n      {error && <div className="error">{error}</div>}\n      {tab'],
  ["createRoot(document.getElementById('root')!).render(<App />);", `function EmbeddedWarning() {
  const view = new URLSearchParams(location.search).get('view') ?? 'dashboard';
  const [toast, setToast] = useState('');
  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(''), 10000);
    return () => window.clearTimeout(timeout);
  }, [toast]);
  return <main className="main">
    {view === 'dashboard' ? <Dashboard notify={setToast} /> : <Admin embeddedTab={view} notify={setToast} />}
    {toast && <div className="toast" role="status">
      <span>{toast}</span>
      <button className="icon-button" onClick={() => setToast('')} aria-label="关闭提醒"><X size={16} /></button>
    </div>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<EmbeddedWarning />);`],
]);

edit('src/styles.css', [
  ["  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;", '  font-family: var(--font-ui);'],
  ['  color: #223a34;', '  color: var(--text);'],
  ['  background: #f5f7f6;', '  background: var(--page);'],
  ['  --green: #136653;\n  --ink: #163e33;\n  --muted: #80908a;\n  --border: #e3eae6;\n', ''],
  ['.feed,\n.panel {\n  background: #fff;\n  border: 1px solid var(--border);\n  border-radius: 10px;',
    '.feed,\n.panel {\n  background: var(--surface);\n  border: 1px solid var(--border);\n  border-radius: var(--radius-panel);'],
  ['  border: 1px solid #dfe7dd;\n  border-radius: 5px;',
    '  border: 1px solid var(--border-strong);\n  border-radius: var(--radius-control);'],
  ['  color: #31513e;\n  font-size: 12px;', '  color: var(--text);\n  font-size: 12px;'],
]);

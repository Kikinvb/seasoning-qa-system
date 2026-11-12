import {useEffect, useRef, useState} from 'react'
import type {ReactNode} from 'react'
import {createRoot} from 'react-dom/client'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {visit, SKIP} from 'unist-util-visit'
import type {Root, PhrasingContent} from 'mdast'
import './style.css'
import Help from './Help'

const logo = new URL('./logo.svg', import.meta.url).href

type Chat = {id: string; title: string; updated_at?: string}
type Source = {replaces_id: string | null; created_at: string; category: string; description: string; publication: string; id: string; filename: string; source_type: string; parse_status: string; parse_error: string | null; documents: number; chunks: number}
type Citation = {id: string; title: string; standard_no: string | null; version_label: string | null; position: string; status: string; content: string; file_uri: string | null; source_id: string; effective_date: string | null; heading_path: string | null; scope_text: string | null}
type Message = {role: 'user' | 'assistant'; content: string; citations: Citation[]}
type StreamEvent = {type: 'text' | 'error'; value: string} | {type: 'citations'; value: Citation[]} | {type: 'done'; value: true}

function remarkCitations(count: number) {
  return (tree: Root) => {
    const cited = new Set<number>()
    visit(tree, (node, index, parent) => {
      if (node.type === 'link' || node.type === 'linkReference') return SKIP
      if (node.type !== 'text' || !parent || index === undefined) return
      const parts = node.value.split(/(\[\d+\])/g)
      if (parts.length === 1) return
      const replacement: PhrasingContent[] = []
      for (const part of parts) {
        if (!part) continue
        const match = /^\[(\d+)\]$/.exec(part)
        const number = match ? Number(match[1]) : 0
        if (number > 0 && number <= count) {
          cited.add(number)
          replacement.push({type: 'link', url: '#kb-cite-' + number, children: [{type: 'text', value: String(number)}]})
        } else {
          replacement.push({type: 'text', value: part})
        }
      }
      const children = parent.children as Array<(typeof parent.children)[number] | PhrasingContent>
      children.splice(index, 1, ...replacement)
      return index + replacement.length
    })
    if (cited.size) {
      tree.children.push({
        type: 'paragraph',
        data: {hName: 'section', hProperties: {'data-citation-numbers': [...cited].join(',')}},
        children: [],
      })
    }
  }
}
const statuses: Record<string, string> = {pending: '等待导入', processing: '解析与索引中', ok: '已就绪', failed: '导入失败'}

async function request(path: string, init?: RequestInit) {
  const response = await fetch('/api' + path, init)
  if (response.status === 401 && !path.startsWith('/auth/')) {location.reload(); throw new Error('登录已失效，请重新登录。')}
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(typeof error.detail === 'string' ? error.detail : '请求失败（' + response.status + '）')
  }
  return response
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  return (await request(path, init)).json()
}

function json(method: string, value: unknown): RequestInit {
  return {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(value)}
}

type User = {id: string; username: string; role: string; active?: boolean}
const categories = ['未分类','法律法规','部门规章','国家标准','行业标准','地方标准','企业标准','文献资料','业务资料']
const roles: Record<string, string> = {user: '业务人员', maintainer: '知识库维护人员', admin: '系统管理员'}

function ResourceModal({label, onClose, children}: {label: string; onClose: () => void; children: ReactNode}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current
    const previous = document.activeElement as HTMLElement | null
    element?.showModal()
    return () => {element?.close(); previous?.focus()}
  }, [])
  return <dialog ref={dialog} className="resource-modal" aria-label={label} onCancel={e => {e.preventDefault(); onClose()}} onClick={e => {
    if (e.target !== e.currentTarget) return
    const rect = e.currentTarget.getBoundingClientRect()
    if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) onClose()
  }}>{children}</dialog>
}

function AccountMenu({user, onPassword}: {user: User; onPassword: () => void}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {if (!root.current?.contains(event.target as Node)) setOpen(false)}
    const escape = (event: KeyboardEvent) => {if (event.key === 'Escape') {setOpen(false); trigger.current?.focus()}}
    document.addEventListener('pointerdown',outside); document.addEventListener('keydown',escape)
    return () => {document.removeEventListener('pointerdown',outside); document.removeEventListener('keydown',escape)}
  },[open])
  return <div className="account-menu" ref={root} onBlur={e => {if (!e.currentTarget.contains(e.relatedTarget as Node)) setOpen(false)}}>
    <button ref={trigger} className="account-trigger" aria-expanded={open} aria-controls="account-actions" onClick={() => setOpen(!open)}><span className="account-avatar" aria-hidden="true">{user.username.slice(0,1).toUpperCase()}</span><span className="account-identity"><strong>{user.username}</strong><small>{roles[user.role]}</small></span><svg className={open ? 'expanded' : ''} viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.5"/></svg></button>
    {open && <div id="account-actions" className="account-dropdown"><div className="account-dropdown-heading"><strong>{user.username}</strong><small>{roles[user.role]}</small></div><button onClick={() => {setOpen(false); onPassword()}}>修改密码<span aria-hidden="true">→</span></button><button className="account-logout" onClick={() => void api('/auth/logout',{method:'POST'}).then(() => {location.hash='/home'; location.reload()}).catch(e => window.alert(e.message))}>退出登录<span aria-hidden="true">↗</span></button></div>}
  </div>
}

type Page = 'home' | 'chat' | 'library' | 'maintenance' | 'tasks' | 'users' | 'audit' | 'help'
const pageTitles: Record<Page,string> = {home:'工作台',chat:'问答助手',library:'资料中心',maintenance:'知识库维护',tasks:'导入任务',users:'用户管理',audit:'操作日志',help:'使用帮助'}
function allowedPage(user: User): Page {
  const value = location.hash.replace(/^#\/?/, '') as Page
  if (!Object.prototype.hasOwnProperty.call(pageTitles, value)) return 'home'
  if ((value === 'users' || value === 'audit') && user.role !== 'admin') return 'home'
  if ((value === 'maintenance' || value === 'tasks') && user.role === 'user') return 'home'
  return value
}

function App({user}: {user: User}) {
  const pendingDetail = useRef<string | undefined>(undefined)
  const [page, updatePage] = useState<Page>(() => allowedPage(user))
  const setPage = (value: Page) => {location.hash = '/' + value}
  const canMaintain = user.role !== 'user'
  const managing = page === 'maintenance' && canMaintain
  const [historyOpen, setHistoryOpen] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [taskStatus, setTaskStatus] = useState('')
  useEffect(() => {
    const sync = () => {const next = allowedPage(user); updatePage(next); setDetailId(next === 'library' ? pendingDetail.current : undefined); pendingDetail.current = undefined; setEditing(undefined); setCitation(undefined); setError(''); setNotice(''); if (location.hash !== '#/'+next) location.replace('#/'+next)}
    sync(); window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [user])
  const [chats, setChats] = useState<Chat[]>([])
  const [session, setSession] = useState<string>()
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [filter, setFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [detailId, setDetailId] = useState<string>()
  const [editing, setEditing] = useState<Source>()
  const [sources, setSources] = useState<Source[]>([])
  const filteredSources = sources.filter(source => source.filename.toLowerCase().includes(filter.trim().toLowerCase()) && (!categoryFilter || source.category === categoryFilter))
  const detail = sources.find(s => s.id === detailId)
  const [model, setModel] = useState<{model: string; configured: boolean}>()
  const [citation, setCitation] = useState<Citation>()
  const [uploading, setUploading] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  const selection = useRef(0)
  const seed = sources.find(source => source.source_type === 'foodmate')

  const showError = (cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause))
  const refreshChats = async () => setChats(await api<Chat[]>('/chats'))
  const refreshSources = async () => setSources(await api<Source[]>('/sources'))

  useEffect(() => {
    void refreshChats().catch(showError)
    void api<{model: string; configured: boolean}>('/status').then(setModel).catch(showError)
  }, [])
  useEffect(() => {
    if (!['home','library','maintenance','tasks'].includes(page)) return
    void refreshSources().catch(showError)
    const timer = window.setInterval(() => void refreshSources().catch(showError), 2000)
    return () => window.clearInterval(timer)
  }, [page])
  useEffect(() => {end.current?.scrollIntoView({block: 'end'})}, [messages])

  async function openChat(id?: string) {
    const ticket = ++selection.current
    setPage('chat')
    setError('')
    setNotice('')
    setCitation(undefined)
    setSession(id)
    setMessages([])
    setDraft('')
    if (id) {
      setBusy(true)
      try {
        const history = await api<Message[]>('/chats/' + id)
        if (ticket === selection.current) setMessages(history)
      } catch (cause) {showError(cause)}
      finally {setBusy(false)}
    }
  }

  async function ask(text: string) {
    const question = text.trim()
    if (busy || !question) return
    setError('')
    setBusy(true)
    setDraft('')
    const previous = messages
    try {
      const id = session ?? (await api<Chat>('/chats', {method: 'POST'})).id
      setSession(id)
      const answer: Message = {role: 'assistant', content: '', citations: []}
      const display = () => setMessages([...previous, {role: 'user', content: question, citations: []}, {...answer}])
      display()
      const response = await request('/chats/' + id + '/ask', json('POST', {question}))
      const reader = response.body?.pipeThrough(new TextDecoderStream()).getReader()
      if (!reader) throw new Error('浏览器无法读取流式回答。')
      let buffer = ''
      let complete = false
      try {
        while (true) {
          const {done, value} = await reader.read()
          if (done) break
          buffer += value
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) {
            if (!line) continue
            const event: StreamEvent = JSON.parse(line)
            if (event.type === 'error') throw new Error(event.value)
            if (event.type === 'text') answer.content += event.value
            if (event.type === 'citations') answer.citations = event.value
            if (event.type === 'done') complete = true
          }
          display()
        }
      } finally {await reader.cancel().catch(() => undefined)}
      if (!complete || !answer.content || buffer) throw new Error('回答未完整接收，请重试。')
      void refreshChats().catch(showError)
    } catch (cause) {
      setMessages(previous)
      setDraft(question)
      showError(cause)
    } finally {setBusy(false)}
  }

  async function deleteChat(chat: Chat) {
    if (busy || !window.confirm('删除这段会话及其全部消息？')) return
    setBusy(true)
    setError('')
    try {
      await api('/chats/' + chat.id, {method: 'DELETE'})
      setChats(current => current.filter(item => item.id !== chat.id))
      if (session === chat.id) {
        setSession(undefined)
        setMessages([])
        setDraft('')
        setCitation(undefined)
      }
    } catch (cause) {showError(cause)}
    finally {setBusy(false)}
  }

  async function changeSource(path: string, init: RequestInit) {
    setError('')
    setNotice('')
    try {
      const result = await api<{duplicate?: boolean}>(path, init)
      if (path === '/sources/seed') setNotice(result.duplicate ? '首批资料已在文件列表中。' : '已提交首批资料导入。')
      else if (result.duplicate) setNotice('相同文件已存在。可在列表中查看导入状态。')
      await refreshSources()
      return true
    } catch (cause) {showError(cause); return false}
  }

  async function upload(files: FileList | null) {
    if (!files?.length || uploading) return
    setUploading(true)
    try {
      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        await changeSource('/sources', {method: 'POST', body: form})
      }
    } finally {setUploading(false)}
  }

  return <div className="layout">
    <aside className="sidebar">
      <div className="brand"><img className="brand-logo" src={logo} alt="" /><div>食品安全助手<small>调味品知识与问答</small></div></div>
      <button className="primary" disabled={busy} onClick={() => void openChat()}>＋ 新对话</button>
      <nav className="sidebar-nav" aria-label="功能导航"><button className={page === 'home' ? 'selected' : ''} disabled={busy} onClick={() => setPage('home')}>⌂ <span>工作台</span></button><button className={page === 'library' ? 'selected' : ''} disabled={busy} onClick={() => setPage('library')}>▤ <span>资料中心</span></button>
      {canMaintain && <details className="sidebar-management"><summary>管理 <span>⌄</span></summary>{(['maintenance','tasks',...(user.role === 'admin' ? ['users','audit'] : [])] as Page[]).map(item => <button key={item} className={page === item ? 'selected' : ''} disabled={busy} onClick={() => setPage(item)}>{pageTitles[item]}</button>)}</details>}</nav>
      <div className="history"><div className="history-heading"><small>最近会话</small><button disabled={busy} onClick={() => setHistoryOpen(true)}>搜索 / 全部</button></div>{chats.slice(0,10).map(chat => <div key={chat.id} className={'history-row' + (page === 'chat' && chat.id === session ? ' selected' : '')}>
        <button className="history-title" title={chat.title} disabled={busy} onClick={() => void openChat(chat.id)}>{chat.title}</button>
        <details className="chat-options"><summary aria-label={'操作会话：'+chat.title}>⋯</summary><div><button disabled={busy} onClick={async () => {const title=window.prompt('重命名会话',chat.title); if(!title?.trim()) return; try {await api('/chats/'+chat.id,json('PATCH',{title})); await refreshChats()} catch(e) {showError(e)}}}>重命名</button><button disabled={busy} onClick={() => void deleteChat(chat)}>删除</button></div></details>
      </div>)}{!chats.length && <p className="history-empty">暂无会话</p>}</div>
      <button className="sidebar-help" onClick={() => setPage('help')}>使用帮助 ↗</button>
      <div className="model" title={model?.configured ? 'API 已配置' : '等待配置 API 密钥'}><span className={model?.configured ? 'dot ready' : 'dot'} />{model?.model === 'deepseek-flash' || !model ? 'DeepSeek Flash' : model.model}{model && !model.configured && ' · 待配置'}</div>
    </aside>
    <main>
      <header><span>{pageTitles[page]}</span><AccountMenu user={user} onPassword={() => setPasswordOpen(true)}/></header>
      {error && <div className="alert" role="alert">{error}</div>}
      {notice && <div className="notice" role="status">{notice}</div>}
      {page === 'home' ? <section className="library dashboard">
        <div className="dashboard-welcome"><span className="eyebrow">食品安全 · 日常工作</span><h1>你好，{user.username}</h1><p>{user.role === 'admin' ? '管理人员访问，查看系统操作，保持知识库有序运行。' : canMaintain ? '更新资料、跟踪导入，让知识库保持可用。' : '从一个问题开始，或查阅你需要的资料。'}</p></div>
        <div className="dashboard-actions">
          <button className="dashboard-main" onClick={() => user.role === 'admin' ? setPage('users') : canMaintain ? setPage('maintenance') : void openChat()}><span>{user.role === 'admin' ? '人员与权限' : canMaintain ? '资料更新' : '知识问答'}</span><strong>{user.role === 'admin' ? '管理用户' : canMaintain ? '维护知识库' : '开始新对话'} <span aria-hidden="true">↗</span></strong><small>{user.role === 'admin' ? '创建账号、分配角色与管理访问权限' : canMaintain ? '上传文件、更新版本与发布资料' : '围绕食品、指标和标准连续提问'}</small></button>
          <button onClick={() => setPage(user.role === 'admin' ? 'audit' : 'library')}><span className="eyebrow">{user.role === 'admin' ? '变更追踪' : '资料查阅'}</span><strong>{user.role === 'admin' ? '查看操作日志' : '打开资料中心'} →</strong><small>{user.role === 'admin' ? '核查资料维护与账号管理记录' : '浏览已收录文件和版本信息'}</small></button>
          <button onClick={() => canMaintain ? setPage('tasks') : setPage('help')}><span className="eyebrow">{canMaintain ? '处理进度' : '操作指南'}</span><strong>{canMaintain ? '查看导入任务' : '使用帮助'} →</strong><small>{canMaintain ? `${sources.filter(s => ['pending','processing'].includes(s.parse_status)).length} 个处理中 · ${sources.filter(s => s.parse_status === 'failed').length} 个失败` : '了解问答、资料和账号的使用方式'}</small></button>
        </div>
        <div className="dashboard-columns"><section className="dashboard-section"><div className="dashboard-section-head"><h2>最新资料</h2><button onClick={() => setPage('library')}>全部资料 →</button></div><p className="dashboard-caption">按收录时间展示已发布资料</p>{sources.filter(s => s.publication === 'published').slice(0,5).map(source => <button className="dashboard-list-item" key={source.id} onClick={() => {pendingDetail.current=source.id; setPage('library')}}><span><strong>{source.filename}</strong><small>{source.category} · 收录于 {new Date(source.created_at).toLocaleDateString()}</small></span><span aria-hidden="true">→</span></button>)}{!sources.some(s => s.publication === 'published') && <p className="library-empty">暂无已发布资料</p>}</section>
        <section className="dashboard-section"><div className="dashboard-section-head"><h2>最近对话</h2><button onClick={() => void openChat()}>新对话 →</button></div>{chats.slice(0,5).map(chat => <button className="dashboard-list-item" key={chat.id} onClick={() => void openChat(chat.id)}><strong>{chat.title}</strong><span aria-hidden="true">→</span></button>)}{!chats.length && <p className="library-empty">还没有对话，从一个问题开始。</p>}<button className="dashboard-help" onClick={() => setPage('help')}>需要帮助？查看使用指南 →</button></section></div>
      </section> : page === 'chat' ? <>
        <section className="conversation" aria-label="对话">
          {messages.length === 0 && <div className="welcome">
            <img className="welcome-logo" src={logo} alt="" /><h1>今天想了解什么？</h1>
            <p>可以问日常问题，也可以查调味品标准。相关资料会随答案附上。</p>
          </div>}
          {messages.map((message, index) => <article key={index} className={'message ' + message.role}>
            <div className="speaker">{message.role === 'user' ? '你' : '知识库助手'}</div>
            {message.role === 'user' ? <div className="message-text">{message.content}</div> : (
              <div className="answer-text">
                {message.content ? <Markdown skipHtml remarkPlugins={[remarkGfm, [remarkCitations, message.citations.length]]} components={{
                  a: ({href, children}) => {
                    const match = /^#kb-cite-(\d+)$/.exec(href ?? '')
                    const item = match && message.citations[Number(match[1]) - 1]
                    return item
                      ? <button className="cite" aria-label={'查看来源 ' + match[1]} onClick={() => setCitation(item)}>{children}</button>
                      : <a href={href} target="_blank" rel="noreferrer">{children}</a>
                  },
                  table: ({children}) => <div className="answer-table" tabIndex={0} role="region" aria-label="回答中的表格"><table>{children}</table></div>,
                  section: ({node}) => {
                    const numbers = String(node?.properties['data-citation-numbers'] ?? '').split(',').map(Number)
                    return <section className="answer-sources" aria-label="引用来源">
                      <h3>引用来源</h3>
                      <ul>{numbers.map(number => {
                        const item = message.citations[number - 1]
                        if (!item) return null
                        const standard = item.standard_no && !item.title.includes(item.standard_no) ? item.standard_no : null
                        return <li key={number}>
                          <button type="button" className="source-link" onClick={() => setCitation(item)}>
                            <span className="source-number" aria-label={'来源 ' + number}>{number}</span>
                            <span className="source-details">
                              <strong>{item.title}</strong>
                              <small>{[standard, item.position].filter(Boolean).join(' · ')}</small>
                            </span>
                            <span className="source-action">查看原文</span>
                          </button>
                        </li>
                      })}</ul>
                    </section>
                  },
                }}>{message.content}</Markdown> : busy && '正在准备回答…'}
              </div>
            )}
          </article>)}
          <div ref={end} />
        </section>
        <form className="composer" onSubmit={event => {event.preventDefault(); void ask(draft)}}>
          <textarea rows={1} value={draft} maxLength={2000} onChange={event => setDraft(event.target.value)} aria-label="问题" placeholder="输入你的问题…" onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); void ask(draft)}
          }} />
          <button className="send-button" type="submit" aria-label={busy ? '回答中' : '发送问题'} title={busy ? '回答中' : '发送问题'} disabled={busy || !draft.trim()}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              {busy ? <path d="M5 12h.01M12 12h.01M19 12h.01" strokeWidth="3" /> : <path d="M12 19V5m-6 6 6-6 6 6" />}
            </svg>
          </button>
        </form>
      </> : page === 'help' ? <Help role={user.role}/> : page === 'audit' ? <AuditLog /> : page === 'users' ? <UserManagement /> : page === 'tasks' ? <section className="library">
        <h1>导入任务</h1><p>查看文件处理进度，失败任务可重试。每两秒自动更新。</p>
        <div className="task-summary">{Object.entries(statuses).map(([key,label]) => <button key={key} className={taskStatus === key ? 'selected' : ''} onClick={() => setTaskStatus(taskStatus === key ? '' : key)}><strong>{sources.filter(s => s.parse_status === key).length}</strong><span>{label}</span></button>)}</div>
        <div className="library-toolbar"><h2>任务记录</h2><select className="library-category" aria-label="筛选任务状态" value={taskStatus} onChange={e => setTaskStatus(e.target.value)}><option value="">全部状态</option>{Object.entries(statuses).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></div>
        {sources.filter(s => !taskStatus || s.parse_status === taskStatus).map(source => <article className="source task-row" key={source.id}><div><strong>{source.filename}</strong><p>{new Date(source.created_at).toLocaleString()} · {statuses[source.parse_status]}</p><small>{source.documents} 份文档 · {source.chunks} 条切片</small>{source.parse_error && <p className="task-error">{source.parse_error}</p>}</div><div className="actions"><a href={'/api/sources/'+source.id+'/file'}>原文件</a>{source.parse_status === 'failed' && <button onClick={() => void changeSource('/sources/'+source.id+'/retry',{method:'POST'})}>重试导入</button>}</div></article>)}
        {!sources.some(s => !taskStatus || s.parse_status === taskStatus) && <div className="library-empty">暂无匹配的导入任务</div>}
      </section> : <section className="library">
        <h1>{managing ? '知识库维护' : '资料中心'}</h1><p>{managing ? '上传、更新和发布资料，维护知识库的有效版本。' : '按文件名或分类查阅资料，查看原文件和版本信息。'}</p>
        {managing && <div className="upload-box">
          <h2>导入资料</h2><p>支持 XLSX、DOCX、文字版 PDF 和 UTF-8 CSV，每份最多 25 MB。</p>
          <div className="actions">
            <label className={'primary file-button' + (uploading ? ' disabled' : '')}>{uploading ? '上传中…' : '选择文件'}<input type="file" multiple accept=".pdf,.docx,.xlsx,.csv" disabled={uploading} onChange={event => {void upload(event.target.files); event.target.value = ''}} /></label>
            {!seed && <button onClick={() => void changeSource('/sources/seed', {method: 'POST'})}>导入首批资料</button>}
          </div>
        </div>
        }
        <div className="library-toolbar">
          <div className="library-list-heading"><h2>文件列表</h2><span aria-live="polite">{filter.trim() || categoryFilter ? `${filteredSources.length} / ${sources.length}` : sources.length} 个文件</span></div>
          <div className="library-filters"><select className="library-category" aria-label="按分类筛选资料" value={categoryFilter} onChange={e => setCategoryFilter(e.target.value)}><option value="">全部分类</option>{categories.map(c => <option key={c} value={c}>{c}</option>)}</select><div className="library-search">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>
            <input aria-label="按文件名搜索资料" placeholder="搜索文件名" value={filter} onChange={e => setFilter(e.target.value)}/>
            {filter && <button type="button" aria-label="清空筛选" title="清空筛选" onClick={() => setFilter('')}>×</button>}
          </div></div>
        </div>
        {detail && <ResourceModal label="资料详情与版本" onClose={() => setDetailId(undefined)}><section className="resource-panel" aria-label="资料详情">
          <div className="resource-panel-head"><div><span className="eyebrow">资料详情 / 版本记录</span><h2>{detail.filename}</h2></div><button className="quiet-button" onClick={() => setDetailId(undefined)}>关闭详情</button></div>
          <div className="resource-panel-body">
            <div className="resource-badges"><span>{detail.category}</span><span data-state={detail.publication}>{{draft:'草稿',published:'已发布',disabled:'已停用'}[detail.publication]}</span><span>{statuses[detail.parse_status]}</span></div>
            <dl className="resource-facts"><div><dt>创建时间</dt><dd>{new Date(detail.created_at).toLocaleString()}</dd></div><div><dt>内容规模</dt><dd>{detail.documents} 份文档 <span> / </span> {detail.chunks} 条切片</dd></div></dl>
            <h3>资料说明</h3><p className="resource-description">{detail.description || '暂无说明'}</p>
            <h3>版本关联</h3><div className="version-links">
              {detail.replaces_id ? <button onClick={() => setDetailId(detail.replaces_id!)}><small>← 上一版本</small><strong>{sources.find(s => s.id === detail.replaces_id)?.filename ?? '原版本'}</strong></button> : <div className="version-empty">这是最早的版本</div>}
              {sources.filter(s => s.replaces_id === detail.id).map(s => <button key={s.id} onClick={() => setDetailId(s.id)}><small>下一版本 →</small><strong>{s.filename}</strong></button>)}
              {!sources.some(s => s.replaces_id === detail.id) && <div className="version-empty">暂无后续版本</div>}
            </div><p className="resource-hint">新版本发布前，旧版本保持原状态；发布新版后自动停用旧版。</p>
          </div>
        </section></ResourceModal>}
        {managing && editing && <ResourceModal label="编辑与发布" onClose={() => setEditing(undefined)}><form className="resource-panel" onSubmit={async e => {e.preventDefault(); const saved = await changeSource('/sources/'+editing.id, json('PATCH', {category:editing.category,description:editing.description,publication:editing.publication})); if (saved) setEditing(undefined)}}>
          <div className="resource-panel-head"><div><span className="eyebrow">资料维护</span><h2>编辑与发布</h2><p>{editing.filename}</p></div><button type="button" className="quiet-button" onClick={() => setEditing(undefined)}>取消</button></div>
          <div className="resource-panel-body resource-form">
            {error && <div className="alert full-width" role="alert">{error}</div>}
            <label>资料分类<select value={editing.category} onChange={e => setEditing({...editing,category:e.target.value})}>{categories.map(c => <option key={c}>{c}</option>)}</select><small>按文件的主要内容选择分类。</small></label>
            <label>发布状态<select value={editing.publication} onChange={e => setEditing({...editing,publication:e.target.value})}><option value="draft">草稿</option><option value="published" disabled={editing.parse_status !== 'ok'}>已发布</option><option value="disabled">已停用</option></select><small>{editing.parse_status !== 'ok' ? '解析成功后才能发布。' : '已发布的资料参与问答；草稿和停用资料不参与。'}</small></label>
            <label className="full-width">资料说明<textarea rows={4} placeholder="填写适用范围、资料用途或需要注意的内容…" value={editing.description} onChange={e => setEditing({...editing,description:e.target.value})} maxLength={2000}/><small>{editing.description.length} / 2000</small></label>
          </div><div className="resource-panel-footer"><span>保存后立即生效</span><div className="actions"><button type="button" onClick={() => setEditing(undefined)}>取消</button><button className="primary">保存修改</button></div></div>
        </form></ResourceModal>}
        {sources.length === 0 && <p className="library-empty">暂未导入资料。</p>}
        {sources.length > 0 && filteredSources.length === 0 && <div className="library-empty"><strong>未找到匹配的文件</strong><p>试试其他文件名或分类，或清空筛选查看全部资料。</p><button onClick={() => {setFilter(''); setCategoryFilter('')}}>清空筛选</button></div>}
        {filteredSources.map(source => <article className="source" key={source.id}>
          <div><strong>{source.filename}</strong><p>{source.category} · {{draft:'草稿',published:'已发布',disabled:'已停用'}[source.publication]} · {source.description}</p><p>{statuses[source.parse_status] ?? source.parse_status} · {source.documents} 份文档 · {source.chunks} 条切片</p>{source.parse_error && <p>{source.parse_error}</p>}</div>
          <div className="actions">
            <button onClick={() => {setDetailId(source.id); setEditing(undefined)}}>详情与版本</button>
            <a href={'/api/sources/' + source.id + '/file'}>原文件</a>
            {managing && source.source_type !== 'foodmate' && !sources.some(s => s.replaces_id === source.id) && <label className="file-button">上传新版本<input type="file" accept=".pdf,.docx,.xlsx,.csv" disabled={uploading} onChange={async e => {const file=e.target.files?.[0]; e.target.value=''; if (!file) return; const form=new FormData(); form.append('file',file); setUploading(true); try {await changeSource('/sources/'+source.id+'/replacement',{method:'POST',body:form})} finally {setUploading(false)}}}/></label>}
            {managing && <button onClick={() => {setEditing({...source}); setDetailId(undefined)}}>编辑与发布</button>}
            {managing && source.parse_status === 'failed' && <button onClick={() => void changeSource('/sources/' + source.id + '/retry', {method: 'POST'})}>重试</button>}
            {managing && <button disabled={source.parse_status === 'processing'} onClick={() => {
              if (window.confirm('删除该文件及其检索索引？')) void changeSource('/sources/' + source.id, {method: 'DELETE'})
            }}>删除</button>}
          </div>
        </article>)}
      </section>}
    </main>
    {historyOpen && <ResourceModal label="搜索会话历史" onClose={() => setHistoryOpen(false)}><ChatHistory onClose={() => setHistoryOpen(false)} onOpen={id => {setHistoryOpen(false); void openChat(id)}}/></ResourceModal>}
    {passwordOpen && <ResourceModal label="修改密码" onClose={() => setPasswordOpen(false)}><PasswordForm /></ResourceModal>}
    {citation && <aside className="evidence">
      <div className="evidence-top"><strong>引用来源</strong><button onClick={() => setCitation(undefined)} aria-label="关闭引用">×</button></div>
      <h2>{citation.title}</h2>
      <p>{[citation.standard_no, citation.version_label, citation.position, citation.heading_path].filter(Boolean).join(' · ')}</p>
      <p>{citation.status}{citation.effective_date ? ' · 实施日期 ' + citation.effective_date : ''}</p>
      {citation.scope_text && <p>适用范围 · {citation.scope_text}</p>}
      <div className="excerpt">{citation.content}</div>
      {citation.file_uri && /^https?:\/\//i.test(citation.file_uri)
        ? <a href={citation.file_uri} target="_blank" rel="noreferrer">打开来源网页 ↗</a>
        : <a href={'/api/sources/' + citation.source_id + '/file'}>下载原文件 ↓</a>}
    </aside>}
  </div>
}

function ChatHistory({onOpen,onClose}: {onOpen:(id:string)=>void;onClose:()=>void}) {
  const [q,setQ] = useState('')
  const [page,setPage] = useState(1)
  const [rows,setRows] = useState<Chat[]>([])
  const [loading,setLoading] = useState(true)
  const [error,setError] = useState('')
  useEffect(() => {let active=true; setLoading(true); const timer=setTimeout(() => {void api<Chat[]>('/chats?q='+encodeURIComponent(q)+'&page='+page+'&size=20').then(data => {if(active){setRows(data);setError('')}}).catch(e => {if(active) setError(e.message)}).finally(() => {if(active) setLoading(false)})},250); return () => {active=false;clearTimeout(timer)}},[q,page])
  const group = (value?:string) => {const date=value ? new Date(value) : new Date(0);const today=new Date();const yesterday=new Date();yesterday.setDate(today.getDate()-1);return date.toDateString()===today.toDateString() ? '今天' : date.toDateString()===yesterday.toDateString() ? '昨天' : '更早'}
  return <section className="resource-panel"><div className="resource-panel-head"><div><span className="eyebrow">个人会话</span><h2>搜索历史</h2></div><button type="button" className="quiet-button" onClick={onClose} aria-label="关闭会话搜索">关闭 ×</button></div><div className="resource-panel-body"><div className="library-search"><input autoFocus aria-label="搜索会话标题" placeholder="搜索会话标题" value={q} maxLength={200} onChange={e => {setQ(e.target.value);setPage(1)}}/></div>{error && <p role="alert">{error}</p>}{loading ? <p role="status">正在加载…</p> : rows.map((chat,index) => <div key={chat.id}>{(index===0 || group(rows[index-1].updated_at)!==group(chat.updated_at)) && <h3>{group(chat.updated_at)}</h3>}<button className="dashboard-list-item" onClick={() => onOpen(chat.id)}><span><strong>{chat.title}</strong><small>{chat.updated_at ? new Date(chat.updated_at).toLocaleString() : ''}</small></span><span>→</span></button></div>)}{!loading && !error && !rows.length && <p className="library-empty">暂无匹配会话</p>}</div><div className="resource-panel-footer"><span>第 {page} 页</span><div className="actions"><button disabled={page===1 || loading} onClick={() => setPage(page-1)}>上一页</button><button disabled={rows.length<20 || loading} onClick={() => setPage(page+1)}>下一页</button></div></div></section>
}

type AuditEntry = {id: number;created_at:string;username:string;action:string;target:string;status_code:number}
function AuditLog() {
  const [page,setPage] = useState(1)
  const [result,setResult] = useState('all')
  const [data,setData] = useState<{items:AuditEntry[];total:number}>({items:[],total:0})
  const [error,setError] = useState('')
  const [loading,setLoading] = useState(false)
  const [refresh,setRefresh] = useState(0)
  useEffect(() => {let active=true; setLoading(true); setError(''); void api<{items:AuditEntry[];total:number}>('/audit?page='+page+'&result='+result).then(value => {if(active) setData(value)}).catch(e => {if(active) setError(e.message)}).finally(() => {if(active) setLoading(false)}); return () => {active=false}},[page,result,refresh])
  return <section className="library"><h1>操作日志</h1><p>追踪资料维护与账号管理操作，按时间倒序显示。</p><div className="library-toolbar"><select className="library-category" aria-label="操作结果" value={result} onChange={e => {setResult(e.target.value);setPage(1)}}><option value="all">全部结果</option><option value="success">成功</option><option value="failure">失败</option></select><button disabled={loading} onClick={() => setRefresh(refresh+1)}>刷新日志</button></div>{error && <p role="alert">{error}</p>}
    {loading ? <p role="status">正在加载…</p> : <><div className="audit-table"><table><thead><tr><th>时间</th><th>操作人</th><th>操作</th><th>对象</th><th>结果</th></tr></thead><tbody>{data.items.map(row => <tr key={row.id}><td>{new Date(row.created_at).toLocaleString()}</td><td>{row.username}</td><td>{row.action}</td><td>{row.target}</td><td><span className={row.status_code<400 ? 'audit-success' : 'audit-failure'}>{row.status_code<400 ? '成功' : '失败'} · {row.status_code}</span></td></tr>)}</tbody></table></div>{!data.items.length && <p className="library-empty">暂无操作记录</p>}</>}
    <div className="library-toolbar"><small>共 {data.total} 条 · 第 {page} 页</small><div className="actions"><button disabled={page===1 || loading} onClick={() => setPage(page-1)}>上一页</button><button disabled={page*30>=data.total || loading} onClick={() => setPage(page+1)}>下一页</button></div></div></section>
}

function PasswordForm() {
  const [error, setError] = useState('')
  return <form className="resource-panel" onSubmit={async e => {
    e.preventDefault(); const data = new FormData(e.currentTarget)
    if (data.get('password') !== data.get('confirm')) {setError('两次新密码不一致。'); return}
    try {await api('/auth/password',json('POST',{current_password:data.get('current_password'),password:data.get('password')})); location.reload()} catch(e) {setError((e as Error).message)}
  }}><div className="resource-panel-head"><h2>修改密码</h2></div><div className="resource-panel-body resource-form"><label className="full-width">当前密码<input name="current_password" type="password" required maxLength={128} autoComplete="current-password"/></label><label className="full-width">新密码<input name="password" type="password" required minLength={10} maxLength={128} autoComplete="new-password"/></label><label className="full-width">确认新密码<input name="confirm" type="password" required minLength={10} maxLength={128} autoComplete="new-password"/></label>{error && <p role="alert" className="full-width">{error}</p>}<small className="full-width">至少10位，保存后需要重新登录。按 Esc 可关闭。</small></div><div className="resource-panel-footer"><button className="primary">保存并重新登录</button></div></form>
}

function UserManagement() {
  const [users, setUsers] = useState<User[]>([])
  const [account, setAccount] = useState<User>()
  const [error, setError] = useState('')
  const refresh = () => api<User[]>('/users').then(setUsers).catch(e => setError(String(e.message)))
  useEffect(() => {void refresh()}, [])
  return <section className="library"><h1>用户管理</h1><p>创建人员账号并分配职责。停用账号将立即撤销其登录会话。</p>
    {error && <p role="alert">{error}</p>}
    <form className="account-form" onSubmit={async e => {
      e.preventDefault(); const form = e.currentTarget; const data = new FormData(form)
      try {await api('/users', json('POST', Object.fromEntries(data))); form.reset(); setError(''); await refresh()} catch(e) {setError((e as Error).message)}
    }}><input name="username" placeholder="账号" required maxLength={64}/><input name="password" type="password" placeholder="初始密码（至少10位）" required minLength={10} maxLength={128}/><select name="role">{Object.entries(roles).map(([key,value]) => <option key={key} value={key}>{value}</option>)}</select><button className="primary">创建账号</button></form>
    {account && <ResourceModal label="调整账号" onClose={() => setAccount(undefined)}><form className="resource-panel" onSubmit={async e => {e.preventDefault(); const data = new FormData(e.currentTarget); try {await api('/users/'+account.id,json('PATCH',{role:data.get('role'),password:data.get('password') || null})); setAccount(undefined); setError(''); await refresh()} catch(e) {setError((e as Error).message)}}}><div className="resource-panel-head"><h2>调整账号 · {account.username}</h2><button type="button" onClick={() => setAccount(undefined)}>取消</button></div><div className="resource-panel-body resource-form"><label className="full-width">角色<select name="role" defaultValue={account.role}>{Object.entries(roles).map(([key,value]) => <option key={key} value={key}>{value}</option>)}</select></label><label className="full-width">重置密码<input name="password" type="password" placeholder="留空则保留原密码" minLength={10} maxLength={128} autoComplete="new-password"/></label><small className="full-width">保存后撤销此账号的全部登录会话。</small>{error && <p className="full-width" role="alert">{error}</p>}</div><div className="resource-panel-footer"><button className="primary">保存修改</button></div></form></ResourceModal>}
    {users.map(u => <article className="source" key={u.id}><div><strong>{u.username}</strong><p>{roles[u.role]} · {u.active ? '正常' : '已停用'}</p></div><button onClick={() => {setError(''); setAccount({...u})}}>角色与密码</button><button onClick={async () => {try {await api('/users/'+u.id+'/active', {method:'PATCH'}); await refresh(); setError('')} catch(e) {setError((e as Error).message)}}}>{u.active ? '停用' : '启用'}</button></article>)}
  </section>
}

function Entry() {
  const [user, setUser] = useState<User>()
  const [setup, setSetup] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {void (async () => {
    try {const state = await api<{setup_required:boolean}>('/auth/state'); setSetup(state.setup_required)
      if (!state.setup_required) {const response = await fetch('/api/auth/me'); if (response.ok) setUser(await response.json()); else if (response.status !== 401) throw new Error('无法获取登录状态')}
    } catch(e) {setError((e as Error).message)} finally {setLoading(false)}
  })()}, [])
  if (loading) return <div className="login">正在加载…</div>
  if (user) return <App user={user}/>
  return <div className="login"><form className="login-card" onSubmit={async e => {
    e.preventDefault(); const value = Object.fromEntries(new FormData(e.currentTarget)); setError('')
    try {if (setup) await api('/auth/setup', json('POST', value)); await api('/auth/login', json('POST',value)); setUser(await api<User>('/auth/me'))} catch(e) {setError((e as Error).message); const state = await api<{setup_required:boolean}>('/auth/state'); setSetup(state.setup_required)}
  }}><img src={logo} width="48"/><h1>{setup ? '初始化管理员' : '登录食品安全助手'}</h1><p>{setup ? '首次使用，请创建管理员账号。历史会话将归属此账号。' : '请使用管理员分配的账号登录。'}</p><label>账号<input name="username" required maxLength={64} autoComplete="username"/></label><label>密码<input name="password" type="password" required minLength={10} maxLength={128} autoComplete={setup ? 'new-password' : 'current-password'}/></label>{error && <p role="alert">{error}</p>}<button className="primary">{setup ? '创建并进入系统' : '登录'}</button></form></div>
}
createRoot(document.getElementById('root')!).render(<Entry />)

import {useEffect, useRef, useState} from 'react'
import {createRoot} from 'react-dom/client'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {visit, SKIP} from 'unist-util-visit'
import type {Root, PhrasingContent} from 'mdast'
import './style.css'

const logo = new URL('./logo.svg', import.meta.url).href

type Chat = {id: string; title: string}
type Source = {id: string; filename: string; source_type: string; parse_status: string; parse_error: string | null; documents: number; chunks: number}
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

function App() {
  const [page, setPage] = useState<'chat' | 'library'>('chat')
  const [chats, setChats] = useState<Chat[]>([])
  const [session, setSession] = useState<string>()
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [sources, setSources] = useState<Source[]>([])
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
    if (page !== 'library') return
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
    } catch (cause) {showError(cause)}
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
      <button className={page === 'library' ? 'selected' : ''} disabled={busy} onClick={() => {setPage('library'); setCitation(undefined); setError(''); setNotice('')}}>知识库管理</button>
      <div className="history"><small>会话历史</small>{chats.map(chat => <div key={chat.id} className={'history-row' + (page === 'chat' && chat.id === session ? ' selected' : '')}>
        <button className="history-title" title={chat.title} disabled={busy} onClick={() => void openChat(chat.id)}>{chat.title}</button>
        <button className="history-delete" title="删除会话" aria-label={'删除会话：' + chat.title} disabled={busy} onClick={() => void deleteChat(chat)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5" /></svg>
        </button>
      </div>)}</div>
      <div className="model" title={model?.configured ? 'API 已配置' : '等待配置 API 密钥'}><span className={model?.configured ? 'dot ready' : 'dot'} />{model?.model === 'deepseek-flash' || !model ? 'DeepSeek Flash' : model.model}{model && !model.configured && ' · 待配置'}</div>
    </aside>
    <main>
      <header>{page === 'chat' ? '问答助手' : '知识库管理'}</header>
      {error && <div className="alert" role="alert">{error}</div>}
      {notice && <div className="notice" role="status">{notice}</div>}
      {page === 'chat' ? <>
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
      </> : <section className="library">
        <h1>本地资料</h1><p>管理文件和索引状态。</p>
        <div className="upload-box">
          <h2>导入资料</h2><p>支持 XLSX、DOCX、文字版 PDF 和 UTF-8 CSV，每份最多 25 MB。</p>
          <div className="actions">
            <label className={'primary file-button' + (uploading ? ' disabled' : '')}>{uploading ? '上传中…' : '选择文件'}<input type="file" multiple accept=".pdf,.docx,.xlsx,.csv" disabled={uploading} onChange={event => {void upload(event.target.files); event.target.value = ''}} /></label>
            {!seed && <button onClick={() => void changeSource('/sources/seed', {method: 'POST'})}>导入首批资料</button>}
          </div>
        </div>
        <h2>文件列表</h2>
        {sources.length === 0 && <p>暂未导入资料。</p>}
        {sources.map(source => <article className="source" key={source.id}>
          <div><strong>{source.filename}</strong><p>{statuses[source.parse_status] ?? source.parse_status} · {source.documents} 份文档 · {source.chunks} 条切片</p>{source.parse_error && <p>{source.parse_error}</p>}</div>
          <div className="actions">
            <a href={'/api/sources/' + source.id + '/file'}>原文件</a>
            {source.parse_status === 'failed' && <button onClick={() => void changeSource('/sources/' + source.id + '/retry', {method: 'POST'})}>重试</button>}
            <button disabled={source.parse_status === 'processing'} onClick={() => {
              if (window.confirm('删除该文件及其检索索引？')) void changeSource('/sources/' + source.id, {method: 'DELETE'})
            }}>删除</button>
          </div>
        </article>)}
      </section>}
    </main>
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

createRoot(document.getElementById('root')!).render(<App />)


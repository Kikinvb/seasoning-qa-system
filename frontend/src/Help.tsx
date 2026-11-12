export default function Help({role}: {role: string}) {
  return <section className="library help-page">
    <div className="help-intro"><span className="eyebrow">使用指南</span><h1>从提问到资料更新</h1><p>了解常用操作、发布规则和问题处理方式。</p></div>
    <div className="help-grid">
      <article className="help-card"><h2>开始问答</h2><ol><li>点击“新对话”，描述食品、指标及需要核查的问题。</li><li>可以在同一会话继续提问，并点击回答中的引用核对原文。</li><li>会话仅本人可查看；删除后无法在界面恢复。</li></ol><p>引用是否充分仍需结合原文核查。扫描件 OCR 可能存在错字，请核对原始文件。</p></article>
      <article className="help-card"><h2>查阅资料</h2><ol><li>进入资料中心，按文件名搜索或选择分类，两项条件可以组合。</li><li>点击“详情与版本”查看说明和前后版本。</li><li>点击“原文件”下载。弹窗可通过关闭按钮或 Esc 退出。</li></ol><p>草稿和停用资料可浏览、下载，但不参与新问题检索；旧会话中的引用保留。</p></article>
      <article className="help-card"><h2>管理自己的账号</h2><p>右上角账户菜单提供修改密码与退出登录。新密码至少 10 位，修改后需重新登录。</p><p>忘记密码、账号停用或需要调整角色时，请联系管理员。不要向他人提供密码。</p></article>
      <article className="help-card"><h2>理解两种状态</h2><dl><dt>处理状态</dt><dd>等待导入 → 解析与索引中 → 已就绪，或导入失败。</dd><dt>发布状态</dt><dd>草稿：尚未启用；已发布：参与新问题检索；已停用：停止参与检索。</dd></dl><p>处理成功不等于已发布，新上传资料需要维护人员手动发布。</p></article>
      {role !== 'user' && <><article className="help-card"><h2>上传与发布</h2><ol><li>在知识库维护中上传 PDF、DOCX、XLSX 或 UTF-8 CSV，单文件不超过 25 MB。</li><li>在导入任务中查看状态，完成后编辑分类和说明。</li><li>确认内容后选择“已发布”并保存。</li></ol><p>PDF 无文字层页面会使用中英文 OCR，扫描件处理可能较慢；表格和文字识别结果需人工核对。</p></article>
      <article className="help-card"><h2>更新文件版本</h2><ol><li>在最新版本点击“上传新版本”，新文件默认草稿。</li><li>等待解析成功并核查文件，再发布新版。</li><li>新版发布时旧版自动停用，旧文件与引用保留。</li></ol><p>已有新版发布时不能重新发布旧版；停用新版不会自动恢复旧版。首批混合 CSV 不支持整体替换。</p></article></>}
    </div>
    <h2 className="help-section-title">常见问题</h2>
    <div className="help-faq">
      <details><summary>为什么上传成功后问答仍然没有使用该文件？</summary><p>检查资料是否已经解析成功且处于“已发布”。即使发布，具体问题也不一定命中该文件；可先在资料中心下载并核对内容。</p></details>
      <details><summary>为什么提示登录失效？</summary><p>登录有效期为 12 小时；修改密码、管理员调整角色、重置密码或停用账号也会撤销登录。请重新登录，仍失败则联系管理员。</p></details>
      {role !== 'user' && <details><summary>导入失败或长时间处理中怎么办？</summary><p>在导入任务查看失败原因，检查格式、文件完整性及文字内容。修正文件后重新上传，或对暂时性失败点击重试。长时间处理中时请管理员检查服务日志、模型下载及 OCR 运行情况，不要连续重复上传。</p></details>}
      {role === 'admin' && <details><summary>如何管理人员和排查变更？</summary><p>在用户管理创建、启停账号或调整角色与密码；在操作日志按成功／失败筛选。日志从功能上线后开始积累，不包含问答正文和登录失败记录。</p></details>}
    </div>
  </section>
}

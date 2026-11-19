# 调味品安全风险监测预警及问答系统

系统提供标准问答、风险预警和开发者工作台。问答和预警服务通过 Docker Compose 一起部署，浏览器统一访问 `http://127.0.0.1:8000`。

## Windows 本地部署

**准备**：安装 Git，并启动 Docker Desktop（Linux 容器）。以下命令在 PowerShell 中执行。

### 1. 获取源码并初始化本地文件

首次部署先克隆主仓库，再进入项目目录。如果已有主仓库，直接在现有项目根目录继续。

```powershell
git clone https://github.com/Kikinvb/seasoning-qa-system.git
cd seasoning-qa-system
```

在项目根目录准备预警源码、环境文件和服务间签名密钥。以下命令会保留现有本地配置。

```powershell
if (-not (Test-Path warning-system)) {
  git clone https://github.com/xiaotianxucode/food-safety-warning-system.git warning-system
}
git -C warning-system checkout 8fd7242599c870d1fea0c19baa334549e7e2f49a

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (-not (Test-Path warning-system/.env)) {
  (Get-Content warning-system/.env.example) -replace '^SCHEDULER_ENABLED=.*$', 'SCHEDULER_ENABLED=false' |
    Set-Content -LiteralPath warning-system/.env -Encoding ascii
}
if (-not (Test-Path .warning-secret)) {
  $warningSecretBytes = New-Object byte[] 32
  $warningSecretGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $warningSecretGenerator.GetBytes($warningSecretBytes)
    ([BitConverter]::ToString($warningSecretBytes) -replace '-') |
      Set-Content -LiteralPath .warning-secret -Encoding ascii -NoNewline
  } finally {
    $warningSecretGenerator.Dispose()
  }
}
```

### 2. 配置共享模型并启动

在项目根目录新建 `.model.env`，将占位符替换为自己的 DeepSeek API 密钥。已有文件直接编辑。这三个变量会同时配置问答和预警，优先于各服务的旧模型配置。

```dotenv
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-flash
MODEL_API_KEY=YOUR_DEEPSEEK_API_KEY
```

```powershell
docker compose -f compose.yaml -f compose.warning.yaml up -d --build --wait
docker compose -f compose.yaml -f compose.warning.yaml ps
```

### 3. 登录并做首次检查

1. 打开 [本地系统](http://127.0.0.1:8000)。新数据库按页面提示创建管理员，密码至少 10 位。已有环境使用原问答系统账号。
2. 进入「开发者工作台 → 系统管理 → 模型管理」，分别测试标准问答和风险预警的连接。两套提示词可分别编辑和保存。
3. 进入「开发者工作台 → 预警管理 → 采集配置」，只勾选所需来源并保存。例如试用时只启用「重庆市市场监督管理局·食品安全」。随后在「任务中心」点击「立即采集」。
4. 确认试采正常后，在 `warning-system/.env` 中将 `SCHEDULER_ENABLED` 改成 `true`，再运行下方命令。自动采集按 24 小时周期运行，只处理已启用的来源。首次采集默认查看近 72 小时，后续按各来源的采集进度增量处理。

```powershell
docker compose -f compose.yaml -f compose.warning.yaml up -d --wait warning
```

## 问答资料与权限

- **标准问答**：可按调味品名称、指标或标准提问，打开引用核对依据。在问答页面的会话侧栏可搜索、重命名和删除自己的会话。
- **风险预警**：可查看已发布的预警、原文和个人已读状态。采集到的文章通过模型判断是否需要预警。
- **开发者工作台**：仅管理员可见。知识库维护支持上传、发布、替换版本和导入重试，也可导入首批资料。支持 XLSX、DOCX、PDF 和 UTF-8 CSV，单文件上限 25 MB。资料发布后参与问答检索。首次索引需要下载中文向量模型。
- **升级时的角色调整**：现有知识库维护人员会转为普通用户，账号和历史会话保留，需重新登录。预警旧站的账号使用独立数据库，统一入口使用问答系统账号。
- 现有首批 CSV 中的 GB 2760 条目为已废止的 2014 版。需要验收现行添加剂限量时，请先导入适用版本和相应食品类别表格。

## 更新与排查

已有部署先备份 PostgreSQL 和预警 SQLite，再更新项目源码。保留本地环境文件、签名密钥和数据卷，使用与首次部署相同的 Compose 命令重建。数据库表和字段随应用启动升级。

```powershell
docker compose -f compose.yaml -f compose.warning.yaml up -d --build --wait
docker compose -f compose.yaml -f compose.warning.yaml logs --tail 100 app warning
```

- 用 `docker compose -f compose.yaml -f compose.warning.yaml stop` 停止服务。不要用 `down -v` 停机，它会删除数据卷。
- PostgreSQL、向量模型缓存和预警 SQLite 使用 Docker 数据卷持久化。预警服务经 Docker 内网接入，浏览器统一使用端口 8000。
- `.env`、`.model.env`、`.warning-secret` 和预警服务本地环境文件由部署者保管，均不随 Git 提交分发。
- 问答模型会收到当前问题、上一条问题和命中的资料片段。预警模型会收到待分析的新闻及附件提取文本。使用外部 API 时，这些内容会发送到配置的模型服务。
- 独立的资料采集工具见 [data_collection/README.md](data_collection/README.md)。

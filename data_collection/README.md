# 独立资料采集工具

仅访问公开来源并保存文件。不读取父项目配置，不连接问答系统、业务数据库或知识库。

## 运行

先启动 Docker Desktop，等待引擎就绪，再在 PowerShell 中进入本目录。下面的命令使用本目录的 compose.yaml：

```powershell
cd D:\lizhao\lab_proj\seasoning-qa-system\data_collection
```

### 1. 构建采集环境

```powershell
docker compose build
```

这条命令根据 Dockerfile 构建采集工具的镜像：准备 Python 环境、安装 requirements.txt 中的依赖，并把 collector.py 放入镜像。首次构建需要联网下载基础镜像和依赖。

**构建只准备运行环境，不会开始爬取数据。** 首次使用，以及修改采集代码、依赖或 Dockerfile 后，需要执行这条命令。仅修改 config/sources.json 中的采集配置，无需重新构建。

### 2. 执行一次采集

```powershell
docker compose run --rm collector
```

这条命令使用已构建的镜像，启动一个临时容器，执行 compose.yaml 中名为 collector 的采集任务。程序读取 config/sources.json，访问启用的来源，并把采集结果写入本机 data_collection/output 文件夹。

任务完成后程序退出；--rm 表示自动删除本次临时容器，**不会删除本机 output 中的结果文件，也不会删除已构建的镜像**。这条命令执行一次就采集一次，不会自动定时运行。以后需要再次采集时，重新执行即可，无需每次都构建。

当前配置采集重庆市市场监督管理局“检查结果及后处置”栏目首页的前五篇公告及公开附件。已按 2021-11-12 设置日期下限，但尚未遍历历史分页，因此不是五年全量采集。公告涉及多个食品类别，当前保留整篇，不把提到“调味品”视为每一条均属于调味品。

无需启动问答系统。退出码 1 表示存在失败，可用下面的命令查看最近的记录，处理原因后重新运行：

```powershell
Get-Content .\output\runs.jsonl -Tail 20
```

## 输出

- output/raw：按内容 SHA256 保存原始网页和附件，相同内容复用文件。
- output/records：按来源 URL 保存最新 JSON 记录。
- output/records.csv：汇总当前记录，UTF-8 BOM，便于 Excel 打开。
- output/runs.jsonl：追加采集和附件溯源记录及失败原因。

同一 URL 重采会更新结构化记录；旧原件仍保留。本版每次重新请求配置中的页面，并非基于发布日期的增量爬取。CSV 可能包含网页原文，使用表格软件打开时勿执行来自网页的公式内容。

## 来源配置

config/sources.json 独立管理来源。列表页仅用于发现详情链接和保留原件，不进入正式 CSV。旧版食品伙伴网目录记录保留在原文件中，但汇总时排除。每站应先抽样检查正文、日期及列表选择器，再启用批量采集。

当前重庆来源采用正文区域和官方页面元数据提取标题、日期；缺日期、日期异常或正文过短的页面进入 output/quarantine，不进入 CSV。附件支持普通链接和该站 downloadFj 按钮，attachments 字段记录下载状态及路径。附件失败仍保留公告，必须结合附件状态审核。附件尚未解析成产品和检测项目明细。

字段：id、enabled、url、resource_type、region、publisher、body_selector、date_selector（可选）、list_link_selector、detail_urls、max_details、download_attachments。

列表详情只访问同域，数量受 max_details 限制；附件仅下载同域常见文档，每份上限 25 MB。两次请求至少间隔两秒，遵循 robots.txt；访问拒绝、重定向或验证页面应人工检查，不绕过限制。重定向需要核实最终地址后更新配置。请勿直接使用通用 body 选择器进行生产批量采集。

## 已确认业务范围及后续接入

调味品、原料、添加剂及通用食品安全要求；重庆市级优先，区县第二批。公告及案例追溯五年；现行适用法规标准不受发布年份限制，历史判断保留所需旧版。

尚需接入历史分页及其他栏目、食品分类和指标规则提取、法规责任关联。附件当前仅留存原件，未做 PDF/OCR/表格解析；本工具输出均待审核，不能直接作为合规结论。

不修改父项目 Compose。需要统一部署时另行明确集成范围。

## 实验记录

### 2026-11-12

- 首次运行仅获取食品伙伴网数据库导航首页，正文混入导航和页脚，没有具体条款或指标，不作为有效业务资料。
- 改为采集重庆市市场监督管理局“检查结果及后处置”栏目，定向提取公告标题、发布日期和正文；目录页不进入正式 CSV，缺日期、日期异常或正文过短的记录单独隔离。
- 补充该站 downloadFj 附件按钮识别，记录附件名称、来源链接、本地路径和下载状态，并优化正文段落排版。
- 已重新构建独立 Docker 镜像并实际运行，成功保存栏目首页前 5 篇公告及 16 个附件，检查了标题、日期、正文和附件记录。结果位于 output/records.csv、output/records、output/raw，日志位于 output/runs.jsonl。
- 当前仅为小批量验证，尚未遍历五年历史分页，也未将附件解析为产品、指标及检测值明细。下一步继续完善历史采集与附件结构化提取。
- 本次改动仅位于 data_collection，未接入问答系统接口、数据库或知识库。

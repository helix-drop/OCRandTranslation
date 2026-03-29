# 外文文献阅读器 - 开发文档

这份文档只放发布后仍然稳定的说明，重点回答 4 个问题：

1. 项目主流程是什么
2. 核心代码分别放在哪
3. 主要函数和代码块各做什么
4. 发布后维护时，先看哪里、先测什么

## 项目定位与主流程

这是一个完全本地运行的外文文献阅读工具。主流程固定为：

上传 PDF / 图片 -> 调 PaddleOCR 做版面解析 -> 整理页文本与段落 -> 调 LLM 翻译 -> 在阅读页核对原文 / 译文 / 脚注 -> 导出 Markdown

当前主链路事实：

- Web 框架是 Flask
- 数据主链路是 SQLite
- 用户配置写入仓库内 `local_data/user_data/`
- 默认只在本机 `localhost:8080` 使用
- 改状态接口统一要求 CSRF token

## 运行方式与本地数据目录

### 启动入口

| 入口 | 作用 |
|---|---|
| [start.sh](/Users/hao/OCRandTranslation/start.sh) | macOS / Linux 一键建环境并启动 |
| [start.ps1](/Users/hao/OCRandTranslation/start.ps1) | Windows PowerShell 一键启动 |
| [start.bat](/Users/hao/OCRandTranslation/start.bat) | Windows 双击入口，内部转调 `start.ps1` |
| `python3 app.py` | 直接启动 Flask |

默认端口：`8080`

### 本地数据目录

| 路径 | 内容 |
|---|---|
| `local_data/user_data/config.json` | API Key、术语表、当前模型模式、预设模型 key、单条自定义模型配置、部分阅读设置 |
| `local_data/user_data/data/app.db` | SQLite 主库 |
| `local_data/user_data/data/documents/{doc_id}/source.pdf` | 文档原始 PDF 副本 |
| `local_data/user_data/data/documents/{doc_id}/toc_source.csv/xlsx` | 当前生效的目录索引原文件；会一直保留，直到被新上传文件替换 |

### SQLite 当前核心表

- `documents`
- `pages`
- `translate_runs`
- `translation_pages`
- `translation_segments`
- `translate_failures`
- `app_state`

当前稳定约定：

- `translate_runs` 与 `translation_pages` 都会保存 `model_source`、`model_key`、`model_id`、`provider`
- `documents` 会保存目录文件元数据：`toc_file_name`、`toc_file_uploaded_at`
- 当前 SQLite schema 版本是 `5`

## 当前模型配置约定

当前模型配置已经改成“一等公民自定义模型”结构，稳定字段如下：

- `active_model_mode`：`builtin` 或 `custom`
- `active_builtin_model_key`：当前启用的预设模型 key
- `custom_model`：单条自定义模型配置，字段固定为
  - `enabled`
  - `display_name`
  - `provider_type`：`qwen` / `deepseek` / `openai_compatible`
  - `model_id`
  - `base_url`
  - `qwen_region`：`cn` / `sg` / `us`
  - `api_key_mode`：`builtin_dashscope` / `builtin_deepseek` / `custom`
  - `custom_api_key`
  - `extra_body`

生效模型统一通过 [storage.py](/Users/hao/OCRandTranslation/storage.py) 的 `ResolvedModelSpec` 解析：

- 入口目标只允许 `builtin:<key>` 或 `custom`
- 返回统一字段：`model_source`、`model_key`、`model_id`、`provider`、`base_url`、`api_key`、`display_label`、`request_overrides`
- `qwen` 自定义模型会按 `qwen_region` 选择 DashScope 兼容地址，默认 `cn`
- `qwen` 自定义模型默认携带 `extra_body={"enable_thinking": false}`
- `openai_compatible` 自定义模型只使用用户填写的 `base_url + custom_api_key`，不复用 DashScope / DeepSeek 全局 Key

翻译任务当前还有两个稳定约定：

- `tasks.py` 在进入 `structure_page`、`translate_paragraph`、`stream_translate_paragraph` 前，会先把 `ResolvedModelSpec` 收敛成真正的请求字段白名单，只透传 `model_id`、`api_key`、`provider`、`base_url`、`request_overrides`
- `model_key`、`model_source`、`display_label` 这类展示 / 落盘字段只用于页面状态和 SQLite 记录，不直接传给模型 SDK，避免参数签名漂移时把翻译链打断

## 模块总览

以下行数基于当前代码库。

| 文件 | 行数 | 作用 |
|---|---:|---|
| [app.py](/Users/hao/OCRandTranslation/app.py) | 1507 | Flask 入口、页面路由、改状态接口、导出与 PDF 接口 |
| [tasks.py](/Users/hao/OCRandTranslation/tasks.py) | 2250 | OCR 任务、翻译 worker、流式状态、停止与恢复逻辑 |
| [translator.py](/Users/hao/OCRandTranslation/translator.py) | 947 | Prompt、模型调用、流式翻译、术语约束 |
| [text_processing.py](/Users/hao/OCRandTranslation/text_processing.py) | 964 | 页文本整理、段落切分、脚注归属、翻译上下文 |
| [sqlite_store.py](/Users/hao/OCRandTranslation/sqlite_store.py) | 1141 | SQLite schema、连接、事务、仓储接口 |
| [config.py](/Users/hao/OCRandTranslation/config.py) | 768 | 配置读写、术语表（含批量文件解析）、多文档、自定义模型配置与迁移 |
| [storage.py](/Users/hao/OCRandTranslation/storage.py) | 571 | 页数据落盘、模型解析、目录恢复、Markdown 导出、应用状态汇总 |
| [pdf_extract.py](/Users/hao/OCRandTranslation/pdf_extract.py) | 496 | PDF 文字层提取、TOC 提取、xlsx/csv 目录解析、页面渲染、版面合并 |
| [ocr_client.py](/Users/hao/OCRandTranslation/ocr_client.py) | 160 | PaddleOCR 远程接口请求 |
| [templates/reading.html](/Users/hao/OCRandTranslation/templates/reading.html) | 3714 | 阅读页模板、工具栏、PDF 面板、前端状态脚本 |
| [templates/home.html](/Users/hao/OCRandTranslation/templates/home.html) | 807 | 首页、上传入口、文档列表、OCR 进度、术语词典与目录导入模态框 |
| [templates/settings.html](/Users/hao/OCRandTranslation/templates/settings.html) | 421 | 设置页、模型、并发、术语表、目录文件状态与清理动作 |
| [templates/input.html](/Users/hao/OCRandTranslation/templates/input.html) | 103 | OCR 配额提示与进入设置 |
| [templates/base.html](/Users/hao/OCRandTranslation/templates/base.html) | 46 | 全局页面骨架、CSRF token 注入 |
| [static/style.css](/Users/hao/OCRandTranslation/static/style.css) | 1472 | 全局样式 |

## 主要函数与代码块

### `app.py`

`app.py` 负责把页面、状态接口和后端能力接到浏览器。

| 名称 | 作用 | 上下游关系 |
|---|---|---|
| CSRF 令牌与校验 | 生成 token、注入模板、拦截改状态请求 | 上游是 Flask session；下游是全部 `POST/PUT/PATCH/DELETE` 路由 |
| 展示文本清理与预览构造 | 清理展示文本中的表格 / JSON 泄漏并生成预览段落 | 上游是翻译结果；下游是阅读页渲染 |
| 设置页跳转与模型切换辅助 | 统一 `doc_id`、设置页重定向、并发设置、自定义模型保存 / 启用 | 上游是设置表单；下游是 `config.py`、`storage.py` |
| `home` / `input_page` / `settings` | 首页、输入页、设置页渲染入口 | 上游是浏览器 GET；下游是模板 |
| `reading` | 阅读页主入口，组装当前页、PDF、术语、翻译状态、目录和 UI 参数 | 上游是 SQLite、配置、存储；下游是 `templates/reading.html` |
| 上传与重解析 | 上传文件、整书重解析、单页重解析 | 下游是 `tasks.py` OCR 任务与 SSE |
| SSE 任务流 | 输出 OCR 任务事件流和整书翻译事件流 | 上游是 `tasks.py` 任务事件 |
| 从头开始 / 继续翻译 / 重译 | 启动翻译、继续下一页、按显式 `target` 重译当前页 | 下游是 `tasks.py` 翻译状态机 |
| 人工修订与历史 | 保存段级修订、查看历史、重译前警告 | 下游是 SQLite 段级历史 |
| 状态与用量接口 | 当前翻译状态、API 用量、Paddle 配额状态 | 下游是阅读页轮询与设置页提示 |
| 术语表与目录 API | 术语 CRUD / 导入、目录导入、目录偏移保存、目录元数据返回 | 下游是设置页、首页模态框与阅读页目录入口 |
| 导出与 PDF 接口 | 导出 Markdown、读取 PDF 文件、PDF 单页、TOC | 下游是阅读页和下载 |
| 清空翻译 / 清空全部 | 清空译文、重置当前文档或整库状态 | 下游是 `storage.py`、`sqlite_store.py`、`config.py` |

### `tasks.py`

`tasks.py` 是 OCR 与翻译主流程的状态机中心。

| 名称 | 作用 | 上下游关系 |
|---|---|---|
| 任务事件缓存 | 维护 OCR / 解析任务的进度事件与最终状态 | 下游是 `/process_sse` |
| `process_file` | 处理上传文件，拆页、OCR、落盘 | 上游是 `upload_file`；下游是 `storage.py`、`pdf_extract.py` |
| LLM 修补辅助 | 判断 OCR 段落是否需要 LLM 修补并执行修补 | 上游是 OCR 页面文本；下游是页结构化 |
| 段落作业构建 | 构造段级翻译 job、上下文、并发窗口、页条目结构 | 下游是单页翻译和流式翻译 |
| 请求参数白名单 | 从 `ResolvedModelSpec` 展平后的状态字典里筛出真正给模型调用的字段，避免把 `model_key` 之类的展示字段误传到底层 provider | 下游是结构分析、同步翻译、流式翻译 |
| `translate_page` | 同步翻译单页并生成页条目 | 上游是页文本、术语、模型参数；下游是 SQLite |
| `translate_page_stream` | 流式翻译单页，持续推送段落进度、部分失败、用量 | 下游是阅读页 SSE |
| 流式草稿与默认状态 | 初始化翻译草稿状态和总状态默认值 | 下游是阅读页恢复、轮询展示 |
| 状态计算与规范化 | 计算页进度、恢复页、统一 `phase/resume_bp/failed` 语义 | 下游是整书翻译状态机 |
| 状态持久化 | 保存 / 读取翻译状态、草稿、失败页 | 上游是 worker；下游是 API 与阅读页 |
| 成功 / 失败收口 | 单页翻译完成或失败后的状态收口 | 下游是继续翻译、停止、恢复 |
| 快照与运行态查询 | 读取当前快照、是否运行、是否请求停止、停止当前任务 | 下游是 `/translate_status`、停止按钮 |
| `start_translate_task` / `_translate_all_worker` | 启动整书翻译线程并执行整书翻译核心 worker | 下游是 SQLite、SSE、阅读页 |
| `reparse_file` / `reparse_single_page` | 整书重解析与单页重解析 | 上游是首页 / 阅读页重解析入口 |

### `translator.py`

`translator.py` 只关心“如何向模型发请求并把结果变成可用译文”。

| 名称 | 作用 | 上下游关系 |
|---|---|---|
| provider 异常分类 | 识别限流、暂时性错误、额度耗尽 | 下游是 worker 重试与错误展示 |
| prompt 与消息构造 | 生成系统 prompt、用户消息、前后文和脚注输入 | 上游是术语表、页上下文；下游是 provider 调用 |
| 术语强约束 | 找出必须命中的术语并在必要时重写结果 | 下游是最终译文落库 |
| JSON 解析与文本规范化 | 容错解析模型输出、提取预览、规范化译文 | 上游是模型返回文本；下游是段落结果 |
| 同步 / 流式 provider 调用 | 调 Qwen / DeepSeek / OpenAI-compatible 接口、支持停止与增量文本 | 下游是 `translate_paragraph`、`stream_translate_paragraph` |
| `structure_page` | 用 LLM 结构化一整页文本 | 上游是 OCR 页面；下游是 `tasks.py` |
| `_prepare_translate_request` | 统一翻译请求所需的 prompt / message / glossary | 下游是同步与流式翻译共用 |
| `translate_paragraph` / `stream_translate_paragraph` | 同步和流式翻译段落并附带用量 | 下游是 `translate_page`、`translate_page_stream` |

### `config.py`

`config.py` 负责本地配置、多文档和术语表状态。

| 名称 | 作用 | 上下游关系 |
|---|---|---|
| 基础配置校验 | 整数 / 布尔配置规整，并发配置读写 | 下游是设置页和阅读页 |
| 目录与 JSON 读写 | 检查写权限、创建目录、原子写配置、旧位置迁移 | 上游是应用启动；下游是全部配置接口 |
| API Key 读写 | Paddle、DeepSeek、DashScope Key 持久化 | 下游是设置页和翻译调用 |
| 术语表 | 按 `doc_id` 读写术语表、CRUD；`parse_glossary_file` 解析上传的 csv/xlsx 文件并返回规范化列表 | 下游是设置页、首页导入接口与翻译 prompt |
| 当前模型与自定义模型 | `active_model_mode`、`active_builtin_model_key`、`custom_model` 归一化、旧配置迁移、显式启用 / 停用 | 下游是设置页和 `storage.py` |
| 多文档管理 | 创建文档、切换当前文档、文档目录、元数据、删除 | 下游是首页与阅读页文档切换 |

### `storage.py`

`storage.py` 负责磁盘落盘和“当前应用状态”的聚合读取。

| 名称 | 作用 | 上下游关系 |
|---|---|---|
| 文档与页路径辅助 | 统一页文件、旧目录、条目目录路径 | 下游是 OCR 和清空流程 |
| 页面与条目落盘 | 保存 / 读取页面、单页条目、游标、清空旧条目目录 | 上游是 OCR / 翻译结果；下游是导出与阅读 |
| PDF 与目录辅助 | 判断 PDF、返回 PDF 路径、保存 / 读取 TOC、读取目录文件元数据 | 下游是阅读页 PDF 面板和目录入口 |
| 用户目录恢复 | 当 `documents.toc_source='user'` 且 `toc_json` 丢失时，从 `documents/{doc_id}/toc_source.csv/xlsx` 自动解析并回写 SQLite；自动 PDF 书签不会覆盖用户目录 | 下游是首页模态框、设置页和阅读页目录按钮 |
| 生效模型解析 | 解析 `builtin:<key>` / `custom`，返回统一 `ResolvedModelSpec` 与请求覆盖项 | 上游是设置页；下游是 `tasks.py`、`translator.py` |
| Markdown 辅助与脚注归属 | 高亮术语、清理文本、把脚注归到段落 | 下游是导出 |
| `gen_markdown` | 把当前条目生成 Markdown | 下游是导出接口 |
| `get_app_state` | 汇总当前文档状态、历史、页范围与导出所需摘要 | 下游是首页、阅读页 |

### `sqlite_store.py`

`sqlite_store.py` 是所有业务真相数据的主仓储。

| 名称 | 作用 | 上下游关系 |
|---|---|---|
| schema 创建 | PRAGMA、字段补齐、全量 schema 初始化；迁移 `model_source/model_id/provider` 到运行和页结果表，并维护目录文件元数据字段 | 上游是应用启动；下游是全部业务表 |
| 连接与事务 | 统一连接、初始化、读写事务上下文 | 下游是 `SQLiteRepository` |
| `SQLiteRepository` | 文档、页面、翻译 run、段落、失败页、修订历史的增删改查 | 上游是 `app.py`、`tasks.py`、`storage.py` |

### `text_processing.py`

`text_processing.py` 负责把 OCR 页面整理成“可翻译的段落结构”。

| 名称 | 行段 | 块行数 | 作用 | 上下游关系 |
|---|---|---:|---|---|
| `build_paragraphs` | `24-84` | 61 | 按页范围拼出基础段落序列 | 上游是 OCR 页面；下游是翻译任务 |
| `find_next_paras` | `105-148` | 44 | 为当前段提供前后文窗口 | 下游是 prompt 构造 |
| `get_page_paragraphs` | `214-261` | 48 | 取得单页段落并保留元信息 | 下游是阅读页和翻译 |
| `parse_page_markdown` | `275-494` | 220 | 从 OCR markdown 解析单页结构，处理续段、标题、脚注 | 上游是 OCR markdown；下游是页结构化 |
| `_fallback_blocks_to_paragraphs` | `568-615` | 48 | markdown 解析失败时退回块级解析 | 下游是 OCR 失败兜底 |
| `get_paragraph_bboxes` | `618-662` | 45 | 给段落匹配页面 bbox | 下游是 PDF 高亮 |
| 脚注归属系列 | `672-883` | 212 | 规范化脚注标记、提取页脚注、映射到段落 | 下游是阅读页和导出 |
| `get_page_context_for_translate` | `886-926` | 41 | 生成单页翻译上下文 | 下游是 `tasks.py` / `translator.py` |
| 页面文本与页码范围 | `931-964` | 34 | 取当前页文本、下一页、文档页范围 | 下游是阅读页导航 |

### `pdf_extract.py`

`pdf_extract.py` 处理 PDF 文字层、目录和页面渲染。

| 名称 | 作用 | 上下游关系 |
|---|---|---|
| `parse_toc_file` | 解析用户上传的 csv/xlsx 目录文件；当前对 `.xlsx` 支持 `openpyxl` 和轻量 zip/xml 后备解析，两者任一可用即可恢复目录 | 下游是目录导入、目录自动恢复 |
| `extract_pdf_text` | 从 PDF 文字层提取页面文本和 bbox | 下游是 OCR / PDF 混合解析 |
| `extract_pdf_toc` | 提取 PDF 目录并转成扁平 TOC | 下游是 `documents.toc_json` |
| 文字层可读性判断 | 判断 PDF 文本层是否可靠 | 下游是混合解析策略 |
| `combine_sources` | 合并 OCR 版面结果和 PDF 文字层 | 下游是 `process_file` |
| `render_pdf_page` | 把单页 PDF 渲染成图片 bytes | 下游是 `/pdf_page` |
| `extract_single_page_pdf` | 抽取单页 PDF 供下载或局部处理 | 下游是单页核对 |

### 模板与前端代码块

#### `templates/base.html`

| 代码块 | 行段 | 块行数 | 作用 |
|---|---|---:|---|
| `<head>` 与全局资源 | `1-15` | 15 | 注入标题、样式、CSRF meta |
| `<body>` 主骨架 | `17-24` | 8 | 包住页面内容与返回顶部按钮 |
| 全局 CSRF JS | `30-45` | 16 | 提供 `getCsrfToken()` 和 `withCsrfHeaders()` |

#### `templates/home.html`

| 代码块 | 作用 |
|---|---|
| 页面标题与主卡片 | 上传、重解析、当前状态、操作按钮 |
| 文档列表 | 当前文档高亮、进度、切换 / 管理术语词典与目录 / 清空翻译 / 删除 |
| 术语词典与目录模态框 | 弹层：词典文件导入、目录文件导入、当前目录文件名 / 导入时间 / 偏移显示 |
| 前端脚本 | 上传 XHR、OCR SSE、阅读入口禁用逻辑、术语词典与目录模态框交互 |

#### `templates/input.html`

| 代码块 | 作用 |
|---|---|
| 页面主体 | 配额提示、设置入口、当前文档说明 |
| 前端脚本 | 拉取 Paddle 配额状态并更新提示 |

#### `templates/settings.html`

| 代码块 | 作用 |
|---|---|
| API Key 区域 | Paddle、DeepSeek、DashScope 保存 |
| 模型与并发设置 | 模型切换、单条自定义模型保存 / 启用、段内并发 |
| 目录索引文件区域 | 当前目录文件名、导入时间、目录条数、偏移展示，以及替换上传 |
| 术语表与数据管理 | 术语表编辑、清空、重置动作 |
| 前端脚本 | 术语行增删、自定义模型面板、并发输入状态、目录文件替换上传 |

#### `templates/reading.html`

`reading.html` 是最复杂的前端页面，既有模板渲染，也有大段原生 JS 状态管理。

| 代码块 | 作用 |
|---|---|
| 页面级内联样式 | 阅读页专属样式、PDF 面板、导航、状态块 |
| 导出弹窗 | 导出 Markdown 模态框 |
| 顶部导航与工具栏 | 页码导航、模型菜单、目录入口、术语表入口、清空翻译 |
| 翻译进度与用量面板 | 翻译进度条、停止按钮、使用量仪表盘 |
| 主体布局 | PDF 面板、译文 / 原文 / 脚注、段落操作、页进度点 |
| 浮动页导航与 PDF 切换按钮 | 底部上一页 / 下一页与折叠 PDF 入口 |
| 前端状态仓库与分发 | 页面 store、dispatch、翻译草稿状态、UI 切换 |
| 阅读与 PDF 同步 | 原文显示、布局切换、PDF 懒加载、导航 URL 同步、PDF 高亮 |
| 目录导航 | 基于 `toc_items + toc_offset + page_map` 渲染目录按钮、章节高亮和跳转；只有用户目录存在时才显示 |
| 流式草稿与页导航渲染 | 流式段落草稿、错误重试、页码面板渲染 |
| 用量与翻译状态面板 | 用量统计、阶段标签、进度快照、恢复翻译按钮 |
| 翻译 / 重译 / 重解析动作 | 启动翻译、停止、重译确认、单页重解析、SSE 监听 |
| 收尾交互 | PDF 拖拽调宽、导出复制、菜单外点关闭、页面初始化 |

## 稳定接口与主数据流

### 页面入口

- `GET /`
- `GET /input`
- `GET /reading`
- `GET /settings`

### 稳定只读接口

- `GET /translate_status`
- `GET /translate_api_usage`
- `GET /translate_api_usage_data`
- `GET /segment_history`
- `GET /check_retranslate_warnings`
- `GET /pdf_toc`
- `GET /pdf_page/<file_idx>`
- `GET /pdf_file`
- `GET /download_md`
- `GET /export_md`
- `GET /process_sse`
- `GET /translate_all_sse`

### 稳定改状态接口

这些接口统一要求 CSRF token：

- `POST /upload_file`
- `POST /reparse`
- `POST /reparse_page/<page_bp>`
- `POST /start_from_beginning`
- `POST /start_reading`
- `POST /fetch_next`
- `POST /retranslate/<bp>`
- `POST /save_manual_revision`
- `POST /start_translate_all`
- `POST /stop_translate`
- `POST /save_settings`
- `POST /save_glossary`
- `POST /api/glossary`
- `POST /api/glossary/import`
- `POST /api/toc/import`
- `POST /api/toc/set_offset`
- `PUT/PATCH /api/glossary/<term>`
- `DELETE /api/glossary/<term>`
- `POST /set_model/<key>`
- `POST /set_pref`
- `POST /switch_doc/<doc_id>`
- `POST /delete_doc/<doc_id>`
- `POST /reset_text`
- `POST /reset_text_action`
- `POST /reset_all`

其中 `POST /retranslate/<bp>` 还要求显式目标参数：

- `target=custom`
- `target=builtin:<key>`

### 主数据流

1. `upload_file` 把原始文件交给 `tasks.process_file`
2. `process_file` 调 `ocr_client.py` / `pdf_extract.py`，再写入 `storage.py` 和 `sqlite_store.py`
3. 阅读页 `reading` 从 `config.py`、`storage.py`、`sqlite_store.py` 组装当前页
4. 用户触发翻译后，由 `tasks.start_translate_task` / `_translate_all_worker` 跑整书翻译
5. 单页翻译内部调用 `translator.py`，结果写回 SQLite
6. 阅读页通过 SSE + 轮询拿进度、用量、段落草稿
7. 导出时由 `storage.gen_markdown` 生成 Markdown

## 测试分层与发布回归入口

### 自动回归

| 文件 | 作用 |
|---|---|
| [test_backend_backlog.py](/Users/hao/OCRandTranslation/test_backend_backlog.py) | 后端 backlog 回归与接口约束 |
| [test_sqlite_store.py](/Users/hao/OCRandTranslation/test_sqlite_store.py) | SQLite 仓储与 schema 回归 |
| [test_sqlite_mainline.py](/Users/hao/OCRandTranslation/test_sqlite_mainline.py) | SQLite 主链路回归 |
| [test_tasks_streaming.py](/Users/hao/OCRandTranslation/test_tasks_streaming.py) | 任务流、流式翻译、阅读页状态回归 |
| [test_translate_stop_flow_real_docs.py](/Users/hao/OCRandTranslation/test_translate_stop_flow_real_docs.py) | 真实文档主流程回归 |
| [test_translator_streaming.py](/Users/hao/OCRandTranslation/test_translator_streaming.py) | provider 流式翻译与错误处理 |
| [testsupport.py](/Users/hao/OCRandTranslation/testsupport.py) | CSRF 与 test client 辅助 |

发布前核心自动回归命令：

```bash
python3 -m unittest test_backend_backlog.py test_sqlite_store.py test_sqlite_mainline.py test_tasks_streaming.py test_translate_stop_flow_real_docs.py test_translator_streaming.py
```

### 真实联调

浏览器级联调脚本：

- [test_e2e_full.py](/Users/hao/OCRandTranslation/test_e2e_full.py)

发布前真实联调命令：

```bash
python3 -c "import app; app.app.run(debug=False, port=8081, threaded=True)"
python3 -c "import test_e2e_full as t; t.BASE='http://127.0.0.1:8081'; t.test_with_playwright()"
```

### 人工模拟测试

- [test_reader_sim.py](/Users/hao/OCRandTranslation/test_reader_sim.py)

这个脚本保留用于人工阅读体验复核，不作为发布前必须通过的自动门禁。

## 维护原则

1. `DEV.md` 只写稳定事实，不写当天任务过程。
2. 路径、端口、行数、接口名以当前代码为准，代码改了就同步更新。
3. 历史验证放 [verification.md](/Users/hao/OCRandTranslation/verification.md)，未来反馈和下一步开发放 [PROGRESS.md](/Users/hao/OCRandTranslation/PROGRESS.md)。

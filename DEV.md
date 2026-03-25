# 外文文献阅读器 — 技术文档

基于 Flask 的外文学术文献 OCR + 翻译阅读工具。上传 PDF/图片 → PaddleOCR 版面解析 → LLM 逐段翻译 → 双语对照阅读/导出。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.14 + Flask |
| OCR | PaddleOCR-VL-1.5（远程 API） |
| 翻译 | Anthropic Claude / 阿里 Qwen（DashScope） |
| PDF 处理 | pypdf（文字层提取）、PyMuPDF（页面渲染） |
| 前端 | Jinja2 模板 + 原生 JS，SSE 实时推送 |
| 数据存储 | 本地 JSON 文件（`~/.foreign_lit_reader/`） |

### 依赖（requirements.txt）

```
flask>=3.0.0
anthropic>=0.40.0
openai>=1.30.0       # Qwen DashScope 兼容接口
requests>=2.31.0
pypdf>=4.0.0
PyMuPDF>=1.24.0
```

## 项目结构

```
├── .gitignore          # Git 忽略规则（本地数据、系统文件、缓存等）
├── app.py              # Flask 主应用，路由定义
├── config.py           # 配置管理，多文档管理，API Key 存取
├── ocr_client.py       # PaddleOCR API 客户端（分片上传）
├── ocr_parser.py       # OCR 结果解析，页码插值，页眉页脚清理
├── text_processing.py  # 段落构建引擎，跨页合并，对外统一导出
├── text_utils.py       # 基础工具：HTML清理，标题提取，元数据检测
├── translator.py       # LLM 翻译（Claude/Qwen），页面结构分析
├── pdf_extract.py      # PDF 文字层提取，OCR+PDF 合并，页面渲染
├── storage.py          # 磁盘持久化，模板变量，Markdown 导出
├── tasks.py            # 后台任务：OCR 处理，翻译 worker，状态管理
├── start.sh            # 一键启动脚本
├── requirements.txt    # Python 依赖
├── templates/
│   ├── base.html       # 基础布局模板
│   ├── home.html       # 首页（文档列表）
│   ├── input.html      # 解析结果预览 / 翻译起始页选择
│   ├── reading.html    # 双语对照阅读页
│   ├── settings.html   # 设置页（API Key、术语词典）
│   └── translate_api_usage.html  # API 用量页面
├── static/
│   └── style.css       # 全局样式
└── local_data/         # 本地数据文件夹（gitignore，不同步到 GitHub）
    ├── example/        # 示例 PDF 和 OCR 结果
    ├── data/           # 运行时临时数据
    └── README.md       # 本地数据文件夹说明
```

### 数据存储策略

| 路径 | 状态 | 说明 |
|---|---|---|
| `.gitignore` | 已跟踪 | 定义忽略规则 |
| `local_data/user_data/` | 已忽略 | API 密钥、PDF 原文、OCR 结果、翻译数据 |
| `local_data/example/` | 已忽略 | 示例文档（可手动放置） |
| `__pycache__/` | 已忽略 | Python 缓存文件 |
| `.DS_Store` | 已忽略 | macOS 系统文件 |
| `.venv/` | 已忽略 | Python 虚拟环境 |

**重要**：
- 所有敏感数据存储在项目目录下的 `local_data/user_data/`，便于备份和便携
- 首次启动时自动创建目录结构
- 旧版本数据（`~/.foreign_lit_reader/`）会自动迁移
- 分发时需确保安装到用户有写入权限的目录

## 核心数据流

```
上传 PDF/图片
    │
    ▼
┌─────────────────────────────────┐
│ ocr_client.call_paddle_ocr_bytes│  大 PDF 自动分片（90页/片）
│ → PaddleOCR API                 │  返回 layoutParsingResults
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ ocr_parser.parse_ocr            │  解析 blocks，插值页码
│ ocr_parser.clean_header_footer  │  移除页眉页脚
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ pdf_extract.extract_pdf_text    │  提取 PDF 文字层（如有）
│ pdf_extract.combine_sources     │  PDF 文字覆盖 OCR 文字，保留 OCR 布局
└─────────────────────────────────┘
    │
    ▼
  storage.save_pages_to_disk      →  pages.json（每文档独立目录）
    │
    ▼
┌─────────────────────────────────┐
│ text_processing                 │
│   .parse_page_markdown          │  逐页解析 markdown → 段落
│   .get_page_context_for_translate│ 组装翻译所需上下文
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ translator.translate_paragraph  │  逐段调用 LLM 翻译
│ translator.structure_page       │  LLM 修正段落结构（可选）
└─────────────────────────────────┘
    │
    ▼
  storage.save_entries_to_disk    →  entries.json（翻译结果）
    │
    ▼
  reading.html 双语对照阅读
```

## 模块详解

### config.py — 配置与多文档管理

存储路径：`~/.foreign_lit_reader/`

| 函数 | 说明 |
|---|---|
| `ensure_dirs()` | 确保配置/数据目录存在 |
| `load_config()` / `save_config(cfg)` | 读写 `config.json` |
| `get/set_paddle_token()` | PaddleOCR API 令牌 |
| `get/set_anthropic_key()` | Anthropic API Key |
| `get/set_dashscope_key()` | DashScope API Key |
| `get/set_glossary()` | 术语词典 `[[term, defn], ...]` |
| `get/set_model_key()` | 当前翻译模型（默认 `"sonnet"`） |
| `create_doc(name) → doc_id` | 创建文档目录，写入 `meta.json` |
| `get_current_doc_id()` / `set_current_doc(doc_id)` | 当前活跃文档 |
| `list_docs() → [meta]` | 列出所有文档，按创建时间倒序 |
| `update_doc_meta(doc_id, **kwargs)` | 更新文档元数据 |
| `delete_doc(doc_id)` | 删除文档目录 |
| `migrate_legacy_data()` | 旧单文件结构迁移到多文档 |

支持的模型（`MODELS` 字典）：

| key | model_id | provider |
|---|---|---|
| `sonnet` | claude-sonnet-4-6 | anthropic |
| `opus` | claude-opus-4-6 | anthropic |
| `qwen-plus` | qwen-plus | qwen |
| `qwen-max` | qwen-max | qwen |
| `qwen-turbo` | qwen-turbo | qwen |

### ocr_client.py — PaddleOCR API 客户端

API 地址：`https://e2k8b6b77ba5qei2.aistudio-app.com/layout-parsing`

| 函数 | 说明 |
|---|---|
| `call_paddle_ocr_bytes(file_bytes, token, file_type, on_progress) → dict` | 主入口。PDF 超过 90 页自动分片上传，合并结果。`file_type`: 0=PDF, 1=图片 |
| `get_pdf_page_count(file_bytes) → int` | 获取 PDF 页数 |
| `_send_ocr_request(b64, token, file_type, ...) → dict` | 单次 API 请求 |
| `_split_pdf_bytes(file_bytes, chunk_size) → [bytes]` | 大 PDF 按页切割 |
| `_merge_ocr_results(results) → dict` | 合并多分片 OCR 结果 |

### ocr_parser.py — OCR 结果解析

| 函数 | 说明 |
|---|---|
| `parse_ocr(data) → {"pages": [...], "log": [...]}` | 主解析入口。支持多种输入格式（layoutParsingResults / pages / results）。逐页提取 blocks，按 Y 坐标排序，识别页码（number label），插值计算所有页的 bookPage，过滤插图页，确保页码严格递增 |
| `clean_header_footer(pages) → {"pages": [...], "log": [...]}` | 统计频率法检测页眉页脚：顶部 12% / 底部 8% 区域内的短文本，在 >25% 页面重复出现则移除 |
| `_is_figure_page(p) → bool` | 插图页检测：`<img>` 标签、全图片 blocks、短文本、高数字占比 |

**页面数据结构**（parse_ocr 输出的每个 page）：

```python
{
    "fileIdx": int,        # PDF 文件中的页索引（从 0 开始）
    "bookPage": int,       # 书籍页码（插值计算）
    "detectedPage": int,   # OCR 检测到的页码（可能为 None）
    "imgW": int,           # OCR 图像宽度
    "imgH": int,           # OCR 图像高度
    "blocks": [            # 正文区块列表
        {
            "text": str,
            "x": float,           # 左上角 X 坐标
            "bbox": [x1,y1,x2,y2],
            "label": str,         # OCR 标签：text, paragraph_title, doc_title 等
            "is_meta": bool,      # 是否为元数据
            "heading_level": int,  # 0=正文, 1-6=标题
        }
    ],
    "fnBlocks": [...],     # 脚注区块
    "footnotes": str,      # 脚注文本（拼接）
    "indent": float,       # 页面缩进基准线
    "textSource": str,     # "ocr" 或 "pdf"
    "markdown": str,       # OCR 返回的连续 markdown 文本
}
```

### text_processing.py — 段落构建引擎

对外统一导出接口（兼容已有 import），re-export 了 `ocr_parser`、`pdf_extract`、`text_utils` 的函数。

#### 核心：基于 markdown 的页面解析

| 函数 | 说明 |
|---|---|
| `parse_page_markdown(pages, bp) → [{"heading_level", "text", "cross_page"}]` | 主段落解析。逐行解析 markdown，识别标题（`#` 标记 + 全大写检测），合并 OCR 行间断裂和短碎片，检测跨页段落并向后追链合并 |
| `get_page_context_for_translate(pages, bp) → dict` | 组装翻译上下文：段落列表 + 脚注 + 前后页片段 |
| `get_paragraph_bboxes(pages, bp, paragraphs) → [[bbox]]` | 将段落文本匹配回 OCR blocks 的 bbox 坐标 |
| `get_page_range(pages) → (first, last)` | 返回首尾页码 |
| `get_next_page_bp(pages, current_bp) → int\|None` | 获取下一个有内容的页码 |

#### 跨页检测逻辑

- `_is_continuation_from_prev(text, prev_md)`：当前段落首字母小写，或上一页末尾未以句号结束 → 承接上页
- `_is_continuation_to_next(text, next_md)`：当前段落末尾未以句号结束，且下页首字母小写 → 续下页
- 跨页段落处理：承接上页的段落丢弃（由上一页负责合并），续下页的段落向后追链合并

#### 智能合并规则

- 连续标题合并：同级全大写标题、罗马数字前缀
- OCR 行间断裂：上段末尾无句号 + 下段首字母小写 → 合并
- 连字符断词：末尾 `-` 直接拼接
- 短碎片（<60字且无句号结尾）：附加到前一段

#### 旧段落引擎（基于 blocks）

| 函数 | 说明 |
|---|---|
| `build_paragraphs(pages, from_bp, to_bp) → [units]` | 基于 blocks 构建段落，处理跨页合并、缩进检测、短行合并 |
| `find_para_at(pages, bp) → dict` | 定位包含指定页码的段落 |
| `find_next_paras(pages, end_bp, raw_text, count) → [dict]` | 查找后续段落 |
| `get_page_paragraphs(pages, bp) → [dict]` | 获取指定页全部段落 |

#### 脚注处理

| 函数 | 说明 |
|---|---|
| `get_footnotes(pages, from_bp, to_bp) → str` | 获取页面范围内的脚注 |
| `_filter_footnote_lines(text) → str` | 过滤通讯作者/地址等样板脚注 |
| `_is_boilerplate_footnote(text) → bool` | 检测整段脚注是否为样板内容 |

### text_utils.py — 基础文本工具

| 函数 | 说明 |
|---|---|
| `strip_html(s) → str` | 移除 HTML 标签 |
| `extract_heading_level(s) → (level, clean_text)` | 提取 markdown `#` 标题层级 |
| `_is_meta_line(line) → bool` | 检测元数据行（DOI、URL、版权、期刊名等） |
| `_is_metadata(text) → bool` | 同上，兼容旧接口 |
| `ends_mid(text) → bool` | 判断文本是否在句中结束（未以 `.;:?!` 等结尾） |
| `starts_low(text) → bool` | 判断文本是否以小写字母开头 |

### translator.py — LLM 翻译模块

| 函数 | 说明 |
|---|---|
| `translate_paragraph(para_text, para_pages, footnotes, glossary, model_id, api_key, provider) → dict` | 翻译单个段落。构建 system prompt（含术语词典），正文和脚注分别用 `===` 标记包裹发送，解析返回的 JSON（`{pages, original, translation, footnotes, footnotes_translation}`） |
| `structure_page(blocks, markdown, model_id, api_key, provider, page_num) → [{"heading_level", "text"}]` | 用 LLM 分析页面结构。输入 OCR 标签摘要 + markdown 连续文本，输出正确的段落划分（JSON 数组） |
| `build_prompt(gloss_str) → str` | 构建翻译 system prompt |
| `parse_json_response(text) → dict\|None` | 从 API 返回中提取 JSON 对象（处理 ```json 标记、未转义换行等异常） |
| `_call_anthropic(sys, user, model_id, key) → str` | 调用 Anthropic Claude API |
| `_call_qwen(sys, user, model_id, key) → str` | 调用 Qwen DashScope API（OpenAI 兼容接口） |

### pdf_extract.py — PDF 处理

| 函数 | 说明 |
|---|---|
| `extract_pdf_text(file_bytes) → [{"pageIdx", "pdfW", "pdfH", "items", "fullText"}]` | 提取 PDF 文字层。用 pypdf visitor 获取带坐标的文字项。总字符数 < 页数×20 或控制字符污染 > 30% 则判定无有效文字层 |
| `combine_sources(layout_pages, pdf_pages) → {"pages", "log"}` | 将 PDF 文字项按坐标映射到 OCR 布局块。PDF 坐标 → OCR 坐标（缩放换算），按 Y-X 排序重组行，连字符断词处理 |
| `render_pdf_page(pdf_path, file_idx, scale=2.0) → bytes` | 用 PyMuPDF 渲染指定页为 PNG（带 LRU 缓存，maxsize=64） |
| `extract_single_page_pdf(source_pdf_path, file_idx) → bytes\|None` | 从源 PDF 提取单页为独立 PDF |

### storage.py — 数据持久化

| 函数 | 说明 |
|---|---|
| `save_pages_to_disk(pages, name, doc_id)` | 保存页面数据到 `pages.json` |
| `load_pages_from_disk(doc_id) → (pages, name)` | 加载页面数据 |
| `save_entries_to_disk(entries, title, idx, doc_id)` | 保存翻译条目到 `entries.json` |
| `load_entries_from_disk(doc_id) → (entries, title, idx)` | 加载翻译条目 |
| `has_pdf(doc_id) → bool` | 检查是否有 PDF 文件 |
| `get_pdf_path(doc_id) → str` | 获取 PDF 路径 |
| `get_translate_args(model_key) → {"model_id", "api_key", "provider"}` | 组装翻译参数 |
| `highlight_terms(text, glossary) → str` | 术语高亮（返回带 `<span>` 的 HTML） |
| `_ensure_str(val) → str` | 确保值为字符串（API 有时返回列表） |
| `gen_markdown(entries) → str` | 生成导出用 Markdown |
| `get_app_state() → dict` | 获取所有模板共享变量 |

### tasks.py — 后台任务

#### OCR 任务管理

内存字典 `_tasks`，线程锁保护。

| 函数 | 说明 |
|---|---|
| `create_task(task_id, file_path, file_name, file_type)` | 创建 OCR 任务 |
| `get_task(task_id) → dict\|None` | 获取任务 |
| `get_task_events(task_id, cursor) → (events, exists)` | 获取从 cursor 开始的 SSE 事件 |
| `task_push(task_id, event_type, data)` | 推送事件 |
| `remove_task(task_id)` | 清除任务 |
| `process_file(task_id)` | 后台线程：完整 OCR 流水线（OCR → 解析 → PDF文字层 → 清理 → 保存） |
| `reparse_file(task_id, doc_id)` | 后台线程：对已有文档重新 OCR |
| `reparse_single_page(task_id, doc_id, target_bp, file_idx)` | 后台线程：单页重新 OCR |

#### 翻译核心

| 函数 | 说明 |
|---|---|
| `translate_page(pages, target_bp, model_key, t_args, glossary) → dict` | 旧同步页翻译路径：解析段落 → 判断是否需要 LLM 修正结构 → 获取 bbox → 段落翻译。仍保留供单页重译等路径使用 |
| `translate_page_stream(pages, target_bp, model_key, t_args, glossary, doc_id, stop_checker) → dict` | 新流式页翻译路径：逐段消费流式翻译事件，整页完成后才返回 entry；中断时抛 `TranslateStreamAborted`，当前页不落盘 |
| `_needs_llm_fix(paragraphs) → bool` | 判断是否需要 LLM 修正段落结构（短碎片多则需要；参考文献页则跳过） |
| `_llm_fix_paragraphs(paragraphs, page_md, t_args, page_num) → list` | 调用 `structure_page` 修正段落 |

#### 后台连续翻译

内存字典 `_translate_task` + 磁盘状态文件 `translate_state.json`。

| 函数 | 说明 |
|---|---|
| `start_translate_task(doc_id, start_bp, doc_title) → bool` | 启动指定文档的后台翻译线程 |
| `_translate_all_worker(doc_id, start_bp, doc_title)` | 后台线程：从 start_bp 逐页翻译，跳过已翻译页；已改为调用 `translate_page_stream(...)` |
| `get_translate_snapshot(doc_id) → dict` | 获取指定文档的完整翻译快照（磁盘优先） |
| `is_translate_running(doc_id) → bool` | 检查指定文档翻译状态 |
| `is_stop_requested(doc_id) → bool` | 检查指定文档是否请求停止 |
| `request_stop_translate(doc_id)` | 请求停止指定文档后台翻译（持久化到磁盘） |
| `get_translate_events(cursor, doc_id) → (events, running)` | 获取指定文档的翻译 SSE 事件 |
| `translate_push(event_type, data)` | 推送翻译事件 |

#### 流式翻译事件

后台翻译 SSE 当前支持两类事件：

页级事件：

- `init`
- `page_start`
- `page_done`
- `page_error`
- `all_done`
- `stopped`
- `error`

流式页内事件：

- `stream_page_init`
- `stream_para_delta`
- `stream_usage`
- `stream_para_done`
- `stream_page_aborted`

## 数据存储结构

```
local_data/user_data/                 # 项目目录下的用户数据（便于备份和便携）
├── config.json                       # 全局配置
│   {
│     "paddle_token": "...",
│     "anthropic_key": "...",
│     "dashscope_key": "...",
│     "model_key": "sonnet",
│     "glossary": [["term", "定义"], ...]
│   }
│
└── data/
    ├── current.txt                   # 当前活跃文档 ID
    └── documents/
        └── {doc_id}/                 # 每个文档一个目录
            ├── meta.json             # 文档元数据
            │   {"id", "name", "created", "page_count", "entry_count"}
            ├── pages.json            # OCR 解析结果
            │   {"name": "文件名", "pages": [page, ...]}
            ├── entries/              # 翻译结果（按页存储）
            │   ├── meta.json         # {"title": "标题", "idx": 0}
            │   └── pages/
            │       └── {bp:06d}.json # 每页一个文件
            ├── source.pdf            # PDF 副本（供预览）
            └── translate_state.json  # 翻译状态（运行时）
                {
                  "doc_id": str,
                  "phase": "idle|running|stopping|stopped|done|error",
                  "running": bool,
                  "stop_requested": bool,
                  ...
                }
```

**跨平台路径**：
- Windows: `项目目录\local_data\user_data\`
- macOS/Linux: `项目目录/local_data/user_data/`

**旧版本迁移**：首次启动时自动从 `~/.foreign_lit_reader/` 迁移数据。

**entry 数据结构**（entries.json 中的每个 entry）：

```python
{
    "_pageBP": int,         # 页码
    "_model": str,          # 使用的模型 key
    "_usage": {             # 页级 token 统计
        "prompt_tokens": int,
        "completion_tokens": int,
        "total_tokens": int,
        "request_count": int,
    },
    "pages": str,           # 页码字符串
    "_page_entries": [      # 该页所有段落的翻译结果
        {
            "original": str,              # 校正后的原文
            "translation": str,           # 中文翻译
            "footnotes": str,             # 脚注原文
            "footnotes_translation": str, # 脚注翻译
            "heading_level": int,         # 0=正文, 1-6=标题
            "pages": str,
            "_rawText": str,              # 原始段落文本
            "_startBP": int,
            "_endBP": int,
            "_cross_page": str|None,      # 跨页标记
            "_bboxes": [[x1,y1,x2,y2]],  # 对应的 OCR bbox 坐标
        }
    ]
}
```

## API 路由表

### 首页与文档管理

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/` | 首页，显示文档列表 |
| GET | `/switch_doc/<doc_id>` | 切换到指定文档 |
| GET | `/delete_doc/<doc_id>` | 删除指定文档 |
| GET | `/input` | 解析结果预览页 |

### 上传与 OCR

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/upload_file` | 上传文件，返回 `{"task_id"}` |
| POST | `/reparse` | 当前文档重新 OCR |
| POST | `/reparse_page/<page_bp>` | 指定页重新 OCR |
| GET | `/process_sse?task_id=xxx` | SSE：推送 OCR 处理进度。事件类型：`progress`、`log`、`done`、`error_msg` |

### 翻译

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/start_from_beginning` | 从首页开始阅读 |
| POST | `/start_reading` | 指定起始页开始阅读 |
| GET | `/fetch_next` | 翻译下一页 |
| GET | `/retranslate/<bp>/<model>` | 用指定模型重译指定物理页 |
| POST | `/start_translate_all` | 启动后台连续翻译 |
| GET | `/stop_translate` | 停止后台翻译 |
| GET | `/translate_status` | 查询指定文档的完整翻译快照 |
| GET | `/translate_all_sse` | SSE：推送页级事件 + 流式页内事件 |
| GET | `/translate_api_usage` | 旧 API 用量入口；现重定向回阅读页并展开仪表盘 |
| GET | `/translate_api_usage_data` | 返回当前文档的 API usage JSON 数据 |

### 阅读

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/reading?bp=1&auto=1&start_bp=1` | 双语对照阅读页；主导航单位已改为物理页 `bp` |

### 设置

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/settings` | 设置页 |
| POST | `/save_settings` | 保存 API Key（按 section 区分） |
| POST | `/save_glossary` | 保存术语词典 |
| GET | `/set_model/<key>` | 切换翻译模型 |
| POST | `/set_pref` | 保存用户偏好（如双栏模式） |

### 导出

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/download_md` | 下载 Markdown 文件 |
| GET | `/export_md` | API：返回 Markdown JSON |

### PDF 预览

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/pdf_file` | 提供 PDF 原文件 |
| GET | `/pdf_page/<file_idx>` | 渲染指定页为 PNG |

### 重置

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/reset_text` | 清除翻译数据，保留页面 |
| GET | `/reset_text_action` | 从设置页清除翻译数据 |
| GET | `/reset_all` | 删除当前文档 |

## 前端页面

### home.html — 首页

- 文档列表（卡片形式，显示名称、页数、翻译进度）
- 上传新文件（支持 PDF、JPG、PNG 等）
- 上传后 SSE 实时显示 OCR 进度条和日志

### input.html — 解析预览

- 显示 OCR 解析后的页面范围
- 设置文档标题和起始页码
- 跳转到阅读页

### reading.html — 双语阅读

- 原文/译文双栏对照显示，支持切换单栏
- 阅读页主导航单位为物理页 `bp`
- 未翻译页也可直接打开，显示页级占位卡片
- 术语高亮（悬停显示定义）
- 后台连续翻译（SSE 页级进度条）
- API 用量仪表盘内嵌到阅读页，可显示/隐藏
- 当前页流式草稿区已接入，可显示整页段落列表
- 重译当前页（可选择不同模型）
- PDF 原文预览（按页渲染 PNG）
- 导出 Markdown

### settings.html — 设置

- PaddleOCR 令牌
- Anthropic / DashScope API Key
- 术语词典（动态增删行）
- 模型选择
- 数据重置

## 启动

```bash
./start.sh
# 或手动：
source .venv/bin/activate
python3 app.py
# 浏览器打开 http://localhost:8080
```

 # 外文文献阅读器 - 开发文档

这份文档只放发布后仍然稳定的说明，重点回答 4 个问题：

1. 项目主流程是什么
2. 核心代码分别放在哪
3. 主要模块各做什么
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
- 源码已经完成第二轮包化，不再依赖旧根目录 `tasks.py` / `storage.py` / `text_processing.py` 这类单文件入口

## 运行方式与本地数据目录

### 启动入口

| 入口 | 作用 |
|---|---|
| [start_managed.sh](/Users/hao/OCRandTranslation/start_managed.sh) | macOS / Linux 官方启动入口；关闭专用浏览器窗口后会自动结束应用 |
| [start_managed.ps1](/Users/hao/OCRandTranslation/start_managed.ps1) | Windows PowerShell 官方启动入口；关闭专用浏览器窗口后会自动结束应用 |
| [start_managed.bat](/Users/hao/OCRandTranslation/start_managed.bat) | Windows 双击入口，内部转调 `start_managed.ps1` |
| `python3 app.py` | 直接启动 Flask |

默认端口：`8080`

### 本地数据目录

| 路径 | 内容 |
|---|---|
| `local_data/user_data/config.json` | API Key、术语表、两组三槽模型池、部分阅读设置 |
| `local_data/user_data/data/catalog.db` | SQLite 目录库（`documents` + 全局 `app_state`） |
| `local_data/user_data/data/documents/{doc_id}/doc.db` | 文档私有 SQLite（页面、翻译、FNM、文档级状态） |
| `local_data/user_data/data/app.db` | 旧单库（迁移来源/备份，不再作为运行时主链） |
| `local_data/user_data/data/documents/{doc_id}/source.pdf` | 文档原始 PDF 副本 |
| `local_data/user_data/data/documents/{doc_id}/toc_visual_source.pdf` | 用户手动上传的目录 PDF；自动视觉目录会优先使用它，而不是再从整本 PDF 猜目录页 |
| `local_data/user_data/data/documents/{doc_id}/toc_visual_screenshots/` | 用户手动上传的目录截图页（按顺序保存） |
| `local_data/user_data/data/documents/{doc_id}/toc_visual_input_manifest.json` | 手动目录输入模式、原始文件名与顺序清单 |
| `local_data/user_data/data/documents/{doc_id}/logs/` | 当前文档的 OCR / 重解析 / 普通翻译 / glossary / FNM 独立任务日志 |
| `local_data/user_data/data/documents/{doc_id}/toc_source.csv/xlsx` | 当前生效的目录索引原文件；会一直保留，直到被新上传文件替换 |

### SQLite 当前核心表

- `catalog.db`：`documents`、`app_state`
- `doc.db`：`documents`、`pages`、`translate_runs`、`translation_pages`、`translation_segments`、`translate_failures`、`translation_page_revisions`、`fnm_runs`、`fnm_pages`、`fnm_chapters`、`fnm_heading_candidates`、`fnm_section_heads`、`fnm_note_regions`、`fnm_chapter_note_modes`、`fnm_note_items`、`fnm_body_anchors`、`fnm_note_links`、`fnm_structure_reviews`、`fnm_translation_units`、`fnm_paragraph_footnotes`、`fnm_chapter_endnotes`、`fnm_chapter_anchor_alignment`、`app_state`

当前稳定约定：

- `translate_runs` 与 `translation_pages` 都会保存 `model_source`、`model_key`、`model_id`、`provider`
- `translate_runs` 还会保存 `translation_model_label/id` 与 `companion_model_label/id`，供阅读页任务卡展示“正文模型 / 脚注回退模型”
- `documents` 会保存目录文件元数据：`toc_file_name`、`toc_file_uploaded_at`
- 当前 SQLite schema 版本是 `24`
- 旧 FNM 表 `fnm_notes / fnm_page_entries / fnm_page_revisions` 已删除
- FNM 诊断页所需的页投影与注释摘要改为现算，不再依赖旧持久化页表

## 当前代码结构

### 顶层约定

- [app.py](/Users/hao/OCRandTranslation/app.py) 现在只保留 `app = create_app()`、`main()` 和启动前检查
- [web/app_factory.py](/Users/hao/OCRandTranslation/web/app_factory.py) 负责创建 Flask app、注册 CSRF 和挂载路由
- [web/services.py](/Users/hao/OCRandTranslation/web/services.py) 负责按领域构造冻结 dataclass service，替代旧的大 `deps` dict
- [docs/code-ownership.md](/Users/hao/OCRandTranslation/docs/code-ownership.md) 是当前模块归属清单；判断某段代码属于正式主链、只读诊断还是继续清理时，以它为准
- `FootNoteMachine/` 只是构建 FNM 时参考的外部目录，不属于本项目主代码结构

### 源码包布局

| 目录 | 作用 |
|---|---|
| [document](/Users/hao/OCRandTranslation/document) | 文本切分、OCR 解析、PDF 文字层、注释检测等文档处理基础模块 |
| [persistence](/Users/hao/OCRandTranslation/persistence) | SQLite schema / repository、页面落盘、TOC、Markdown 导出和状态聚合 |
| [translation](/Users/hao/OCRandTranslation/translation) | 页级翻译 helper、后台翻译启动 / 运行态 / worker / 状态持久化 |
| [pipeline](/Users/hao/OCRandTranslation/pipeline) | 上传、整书重解析、单页重解析、FNM 前置视觉目录与手动视觉目录任务 |
| [FNM_RE](/Users/hao/OCRandTranslation/FNM_RE) | FNM 七模块主链（`toc_structure -> book_assemble`）、状态汇总与修复工具 |
| [web](/Users/hao/OCRandTranslation/web) | 路由服务层与阅读页 / 页编辑展示 helper |
| [tests](/Users/hao/OCRandTranslation/tests) | 统一测试目录，入口固定为 `python3 -m unittest discover -s tests -p 'test_*.py'` |

### 关键模块

| 文件 | 作用 | 行数（2026-04-21） |
|---|---|---|
| [app.py](/Users/hao/OCRandTranslation/app.py) | 启动入口壳：导出全局 `app`，并在 `main()` 中做本地启动前检查 | 41 |
| [web/app_factory.py](/Users/hao/OCRandTranslation/web/app_factory.py) | Flask app factory：指向仓库根 `templates/` 与 `static/`，注册全部 route module | 45 |
| [web/services.py](/Users/hao/OCRandTranslation/web/services.py) | Web 层 service dataclass 与依赖装配 | 506 |
| [web/document_routes.py](/Users/hao/OCRandTranslation/web/document_routes.py) | 首页、上传、整书重解析、单页重解析、OCR 任务 SSE | 475 |
| [web/reading_routes.py](/Users/hao/OCRandTranslation/web/reading_routes.py) | 阅读页与阅读模式切换 | 338 |
| [web/translation_routes.py](/Users/hao/OCRandTranslation/web/translation_routes.py) | 连续翻译、继续翻译、重译、停止、状态、FNM 状态与使用量 | 1336 |
| [web/settings_routes.py](/Users/hao/OCRandTranslation/web/settings_routes.py) | 设置页、词典 CRUD / 导入、模型切换、重置 | 321 |
| [web/toc_routes.py](/Users/hao/OCRandTranslation/web/toc_routes.py) | 用户目录编辑、视觉目录草稿、offset 与提交接口 | 323 |
| [web/export_routes.py](/Users/hao/OCRandTranslation/web/export_routes.py) | Markdown 导出、PDF 文件 / 单页、目录章节与文档处理状态接口 | 309 |
| [web/page_editor_routes.py](/Users/hao/OCRandTranslation/web/page_editor_routes.py) | 标准整页编辑接口；FNM 视图在这里统一拦成只读 | 78 |
| [web/reading_view.py](/Users/hao/OCRandTranslation/web/reading_view.py) | 阅读页与视觉目录编辑器共用的展示 helper | 691 |
| [web/page_editor.py](/Users/hao/OCRandTranslation/web/page_editor.py) | 标准整页编辑服务层；FNM 视图在这里统一拦成只读 | 235 |
| [pipeline/task_document_pipeline.py](/Users/hao/OCRandTranslation/pipeline/task_document_pipeline.py) | OCR 上传、整书重解析、单页重解析与自动重译 | 838 |
| [pipeline/visual_toc/runtime.py](/Users/hao/OCRandTranslation/pipeline/visual_toc/runtime.py) | 自动视觉目录主编排；`pipeline/visual_toc/` 包内还拆分了 `scan_plan / manual_inputs / organization / vision / shared` | 914 |
| [pipeline/task_registry.py](/Users/hao/OCRandTranslation/pipeline/task_registry.py) | OCR / 解析任务事件缓存、SSE 和最终状态 | 117 |
| [translation/service.py](/Users/hao/OCRandTranslation/translation/service.py) | 页级翻译 helper、词典补重译、后台 worker 依赖装配与翻译领域服务 | 1549 |
| [translation/translate_launch.py](/Users/hao/OCRandTranslation/translation/translate_launch.py) | 后台翻译任务启动：连续翻译、词典补重译、FNM 翻译 | 302 |
| [translation/translate_runtime.py](/Users/hao/OCRandTranslation/translation/translate_runtime.py) | 翻译运行态 helper：事件缓存、快照读取、停止控制、空闲等待 | 359 |
| [translation/translate_worker_common.py](/Users/hao/OCRandTranslation/translation/translate_worker_common.py) | 连续翻译 / 词典补重译 / FNM worker 共享骨架 | 640 |
| [translation/translate_worker_continuous.py](/Users/hao/OCRandTranslation/translation/translate_worker_continuous.py) | 连续翻译 worker | 170 |
| [translation/translate_worker_glossary.py](/Users/hao/OCRandTranslation/translation/translate_worker_glossary.py) | 词典补重译 worker | 151 |
| [translation/translate_worker_fnm.py](/Users/hao/OCRandTranslation/translation/translate_worker_fnm.py) | FNM 翻译 worker | 613 |
| [translation/translator.py](/Users/hao/OCRandTranslation/translation/translator.py) | Prompt、模型调用、流式翻译、术语约束 | 1496 |
| [document/text_processing.py](/Users/hao/OCRandTranslation/document/text_processing.py) | 页文本整理、段落切分、脚注归属、翻译上下文 | 1433 |
| [document/text_utils.py](/Users/hao/OCRandTranslation/document/text_utils.py) | 文本处理基础工具与句尾明确结束判断 | 167 |
| [document/text_layer_fixer.py](/Users/hao/OCRandTranslation/document/text_layer_fixer.py) | PDF文字层乱码检测与修复：检测非标准编码、尝试常见偏移修复、无法修复时提供诊断 | 379 |
| [document/pdf_extract.py](/Users/hao/OCRandTranslation/document/pdf_extract.py) | PDF 文字层提取、目录提取、目录文件解析、页面渲染、版面合并 | 704 |
| [document/ocr_parser.py](/Users/hao/OCRandTranslation/document/ocr_parser.py) | OCR 结果解析与结构化，内置乱码自动修复 | 436 |
| [document/note_detection.py](/Users/hao/OCRandTranslation/document/note_detection.py) | 页级脚注 / 尾注检测 | 869 |
| [persistence/sqlite_schema.py](/Users/hao/OCRandTranslation/persistence/sqlite_schema.py) | SQLite schema、PRAGMA、建表、补列与数据回填 | 916 |
| [persistence/sqlite_store.py](/Users/hao/OCRandTranslation/persistence/sqlite_store.py) | `SQLiteRepository` 组合壳；领域仓储已拆到 `sqlite_repo_*.py` | 188 |
| [persistence/storage.py](/Users/hao/OCRandTranslation/persistence/storage.py) | 页数据落盘、模型解析、PDF 辅助、导出组合入口与请求级缓存 | 934 |
| [FNM_RE/modules/toc_structure.py](/Users/hao/OCRandTranslation/FNM_RE/modules/toc_structure.py) | FNM 模块一：目录结构与章节角色判定 | 354 |
| [FNM_RE/modules/chapter_split.py](/Users/hao/OCRandTranslation/FNM_RE/modules/chapter_split.py) | FNM 模块三：章节切分、注释区域绑定与材料化 | 872 |
| [FNM_RE/modules/note_linking.py](/Users/hao/OCRandTranslation/FNM_RE/modules/note_linking.py) | FNM 模块四：正文锚点与注释项链接闭合 | 1498 |
| [FNM_RE/modules/book_assemble.py](/Users/hao/OCRandTranslation/FNM_RE/modules/book_assemble.py) | FNM 模块七：整书组装、语义审计与导出收口 | 395 |
| [model_capabilities.py](/Users/hao/OCRandTranslation/model_capabilities.py) | 内置模型能力目录：chat / mt / vision 模型、流式模式与 companion fallback | 243 |

### 代码行数快照（2026-04-21）

统计口径：按 `*.py` 逐行统计，忽略运行产物目录（如 `.venv/`、`local_data/`、`logs/`、`output/`）。

| 范围 | 文件数 | 总行数 |
|---|---:|---:|
| 主链运行代码（`app/config/logging/launcher/model/ocr` + `document/` + `persistence/` + `pipeline/` + `translation/` + `web/`） | 72 | 31,247 |
| FNM_RE 模块链路（`FNM_RE/**/*.py`） | 51 | 25,960 |
| 自动化测试（`tests/**/*.py`） | 80 | 30,147 |
| 工程脚本（`scripts/**/*.py`） | 16 | 6,730 |

## 当前稳定约定

### 模型配置

当前模型配置已切到“两组三槽模型池”：

- `translation_model_pool`：标准连续翻译与 FNM 文本翻译共用，按 `slot1 -> slot2 -> slot3` 回退。
- `fnm_model_pool`：自动视觉目录、FNM 视觉判断与 LLM 修补共用，按 `slot1 -> slot2 -> slot3` 回退。
- `mimo_api_key`：MiMo 按量接口全局 Key；MiMo Token Plan 在槽位内单独填写 `base_url + custom_api_key`。
- `glm_api_key`：智谱 GLM 全局 Key，固定 OpenAI-compatible Base URL 为 `https://open.bigmodel.cn/api/paas/v4/`。
- `kimi_api_key`：Kimi / Moonshot 全局 Key，固定 OpenAI-compatible Base URL 为 `https://api.moonshot.ai/v1`。
- 旧 `active_model_mode/custom_model/visual_custom_model` 只在首次读取旧配置时迁移到新池结构；保存配置时不再长期双写旧字段。

生效模型统一通过 [persistence/storage.py](/Users/hao/OCRandTranslation/persistence/storage.py) 的 `ResolvedModelSpec` 解析：

- 返回统一字段：`model_source`、`model_key`、`model_id`、`provider`、`base_url`、`api_key`、`display_label`、`api_family`、`supports_translation`、`supports_vision`、`supports_stream`、`stream_mode`、`companion_chat_model_key`、`request_overrides`、`pool_name`、`slot_index`
- 翻译池可选 DeepSeek、Qwen、Qwen-MT、MiMo、GLM、Kimi 与 OpenAI Compatible；FNM 池只显示视觉/修补可用模型。
- 内置候选模型按能力筛选，不再把所有历史模型都显示出来：
  - 翻译池只显示文本/对话/专用翻译候选，当前主线包括 `qwen3.6-max-preview`、`qwen3.6-plus`、`qwen3.6-flash`、`qwen-mt-*`、`glm-5.1`、`kimi-k2.6/kimi-k2.5`、`mimo-v2.5-pro`、`deepseek-chat/deepseek-reasoner` 等。
  - FNM 池只显示同时具备视觉输入和文本输出能力的多模态候选，当前主线包括 `qwen3.6-plus`、`qwen3.6-flash`、`qwen3-vl-plus`、`qwen3-vl-flash`、`glm-5v-turbo`、`glm-4.6v`、`kimi-k2.6/kimi-k2.5`、`mimo-v2.5`、`mimo-v2-omni`。
  - 旧 `qwen-vl-plus/qwen-vl-max`、OCR 专用 `qwen-vl-ocr`、即将下线或旧 preview 模型只作为历史配置识别，不再作为设置页候选推荐。
- FNM 默认内置主模型是 `qwen3.6-plus`。
- MiMo 按量接口固定 `https://api.xiaomimimo.com/v1`；Token Plan 使用槽位专属 Base URL。
- 槽位可勾选 `thinking_enabled`；Qwen 会写入 `extra_body.enable_thinking`，DeepSeek / GLM / Kimi / 已标记支持的 MiMo 会写入 `extra_body.thinking.type=enabled|disabled`。
- 缺少凭据或能力不匹配的回退槽会被跳过，不参与请求。
- 设置页模型槽位采用渐进式表单：内置模型只显示模型选择和 thinking；自定义模型才展开 Provider、模型 ID，并按 provider 只显示必要的地域、Base URL 和专用 Key。

### 阅读页

阅读页现在有这些稳定约定：

- FNM 模式不再提供独立阅读 / 预览视图；`reading?view=fnm` 会回到标准阅读语义，FNM 状态、翻译、收尾和导出统一在首页 FNM 工作流卡片操作。
- `reading()` 会同时注入 `task_snapshot` 和 `reading_view_state`
- `/switch_reading_mode` 不再切到 FNM 视图；请求 `target_mode=fnm` 时会提示回首页 FNM 工作流卡片
- 阅读页只保留一套统一任务入口 `TranslationSessionCard`
- 标准视图仍支持整页段落编辑：`GET/POST /api/page_editor` 读取和保存完整有序段落数组，`GET /api/page_editor/history` 读取本页历史
- 标准页整页保存会写 `translation_page_revisions`
- `GET/POST /api/page_editor?view=fnm` 与 `GET /api/page_editor/history?view=fnm` 仍固定返回只读错误，避免旧 FNM 诊断视图被误当作可编辑入口

### 首页上传入口与分流

首页上传入口现在有这些稳定约定：

- 首页上传偏好对用户只保留一个稳定开关：`fnm_mode`
- 首页上传完成后不再停在首页等待用户手动决定，而是直接按解析模式分流
- `fnm_mode=true` 时，内部固定派生为 `clean_header_footer=true` 且 `auto_visual_toc=true`
- `fnm_mode=true` 时，上传与整书重解析链路会先同步生成视觉目录；正式 FNM 主链要求手动目录输入存在
- 视觉目录现优先读取用户手动上传的目录 PDF / 目录截图；没有手动目录输入时，自动选页只保留为诊断回退，不再具备正式 FNM 主链地位
- 自动视觉目录会先走 normal 候选扫描；文本层质量差时自动切到 degraded（首尾窗口 + 邻页重试），失败原因会落到 `toc_visual_message/detail`
- `fnm_mode=true` 时，分类成功后会进入首页的 `fnm_progress` 进度模式；如自动启动了 FNM 翻译，也仍留在首页查看进度、阻塞信息和导出状态，不再默认跳转到 `reading?view=fnm`
- FNM 正式主链当前要求手动目录输入；若无 `manual_pdf/manual_images`，状态会给出 `manual_toc_required=true`，真实翻译与正式导出都必须阻塞
- `fnm_mode=false` 时，固定走普通翻译路线：直接按标准连续翻译链路启动，并跳转到标准阅读页，带 `auto=1&start_bp=...`
- FNM 模式下如果自动视觉目录失败、没有有效目录项、FNM 分类失败或自动启动失败，首页会停留在当前页显示失败信息，不会静默降级成普通翻译
- 文档页里的 `POST /api/doc/run_visual_toc` 仍保留，作为高级维护入口；它继续走后台任务，不改变首页“单一 FNM 模式入口”的语义
- FNM 注释验收口径现分层：脚注以“页底可展示”为软门槛；尾注为硬门槛（run 内连续 + 注释区域一一对应），校验失败会输出 `endnote_non_contiguous`、`endnote_unpaired_reference`、`endnote_orphan_definition`、`endnote_duplicate_consumption`
- 自动视觉目录现作为后续“标题分层 + 正式章节切分”的主证据之一：章级目录骨架优先，页内弱证据只能补边界，不直接推翻目录主骨架
- FNM 章节骨架现在优先由视觉目录生成：自动判定 `chapter_level`，过滤 `contents/bibliography/index/appendix/notes/back matter`，再用页内证据补章内 `section_heads`
- 视觉目录正文覆盖现新增显式汇总：`toc_export_coverage_summary`（`resolved_body_items`、`exported_body_items`、`missing_body_items_preview`），并用于批测放行门槛
- 目录对齐收口新增显式汇总：`toc_alignment_summary`（`chapter_level_body_items`、`exported_chapter_count`、`missing_chapter_titles_preview`、`missing_section_titles_preview`、`misleveled_titles_preview`、`reanchored_titles_preview`）
- 目录语义收口新增显式汇总：`toc_semantic_summary`、`toc_semantic_contract_ok`、`toc_semantic_blocking_reasons`
- `summary` 与 `/api/doc/<doc_id>/fnm/status` 结构字段现包含：`chapter_source_summary`、`visual_toc_conflict_count`、`toc_export_coverage_summary`、`toc_alignment_summary`、`toc_semantic_summary`、`toc_semantic_contract_ok`、`toc_semantic_blocking_reasons`、`export_drift_summary`、`chapter_local_endnote_contract_ok`、`chapter_title_alignment_ok`、`chapter_section_alignment_ok`、`manual_toc_required`、`manual_toc_ready`、`manual_toc_summary`、`chapter_progress_summary`、`note_region_progress_summary`
- 当目录主层章节错位或目录语义不满足硬门槛时，结构状态会进入 `review_required`，并附加阻塞原因（如 `toc_chapter_title_mismatch`、`toc_partial_tail_capture`、`toc_nonbody_as_chapter`、`toc_mixed_part_and_chapter_levels`）；`chapter_section_alignment_ok` 默认作为复核提示，不单独阻塞导出
- FNM Obsidian 导出合同已切到“章节本地标准脚注”：每章统一 `[^n]`（从 1 重置），并强制清除 `[FN-*]`、`[FN-[`、`[^en-*]`、`{{NOTE_REF:*}}`、原始 `NOTES/ENDNOTES` 残留
- 章内标题投影已收紧为“少而准”：仅 `heading_family_guess=section` 且满足阈值的标题可导出为 `###`，并拒绝 `*`、`Ibid/Cf./See/supra/infra`、内联注释痕迹和长整句伪标题
- 章节边界冲突比对已支持重音归一（如 `Leçon`/`LECON`），避免因重音差异触发误报 `boundary_review_required`
- 五本基准书视觉目录快照固定落盘到 `test_example/<书名>/auto_visual_toc.{json,md}`；统一由 `python3 scripts/generate_visual_toc_snapshots.py` 生成（支持 `--doc-id` / `--folder` 单本重跑）
- `test_example/example_manifest.json` 现在是样本与批测的单一事实源；当前共维护 8 本样本（5 本 baseline + 3 本 extension）
- `scripts/apply_manual_toc_to_examples.py` 会把 `test_example/<书名>/目录.pdf` 绑定回对应 `doc_id` 的 `toc_visual_source.pdf`，并重跑自动视觉目录；这是当前 8 本样本验证手动目录主链的标准入口
- 新样本接入统一走 `python3 scripts/onboard_example_books.py`，它只做“导入 PDF + PaddleOCR + 自动视觉目录 + FNM 结构快照”，不会触发真实 FNM 翻译
- `scripts/test_fnm_batch.py` 默认已从 5 本扩展为 8 本，按 manifest 中 `include_in_default_batch=true` 的书目执行
- 批测脚本落盘策略已收口：只有导出通过且 `toc_semantic_contract_ok=true` 时才会更新 `test_example/<folder>/latest.fnm.obsidian.zip`
- 如果样本本轮被语义或结构门槛阻塞，批测脚本会把旧的 `latest.fnm.obsidian.zip` 改名为 `latest.fnm.obsidian.blocked.zip`，并写 `latest_export_status.json` 记录阻塞原因，避免人工误看旧包
- `scripts/audit_fnm_exports.py --group extension` 用于新样本导出抽样审计，默认检查扩展样本的分段、目录对齐、脚注/尾注闭合情况

### 任务日志

当前日志规则已经稳定如下：

- 全局日志按启动会话分文件写入 `logs/sessions/app_YYYYMMDD-HHMMSS_<pid>.log`
- 启动时自动清理历史会话日志，仅保留最近 30 次
- 文档级任务日志写到 `local_data/user_data/data/documents/{doc_id}/logs/`
- OCR 上传、整书重解析、单页重解析日志文件名会带 `task_id`
- 普通翻译、glossary 重译、FNM 翻译日志文件名会带任务类型和启动时间
- 同一任务只追加写同一文件，不会拆成多份碎日志
- 首页上传完成事件和阅读页任务卡都会带本次任务的相对日志路径 `log_relpath`

### 词典与补重译

- 每本书继续使用自己的独立词典，存储结构仍是 `[term, defn]`
- 翻译请求不再把整本词典全部塞进 prompt；现在只注入“当前翻译单元实际命中的术语”
- 普通正文段的术语命中范围是 `para_text + footnotes`；单条脚注 / 尾注翻译只检查该条文本本身
- `Qwen-MT` 走 `translation_options.terms` 时，也只会带当前翻译单元命中的术语
- 词典补重译不再按起点把后续机器段整段刷一遍；现在只处理“源文命中词典、但现有译文缺少指定译法”的机器段
- 已人工修订的术语问题段不会被自动覆盖，只会计入 `skipped_manual_segments`
- `/api/glossary_retranslate_preview` 现在会返回 `problem_segments`、`problem_list_truncated` 和 `target_segments_by_bp`
- glossary 补重译 worker 仍按页推进进度，但每页只重译 `target_segments_by_bp` 指定的段索引

### 阅读页模板与前端资源

阅读页模板与静态资源已经完成按领域归档：

- [templates/reading/index.html](/Users/hao/OCRandTranslation/templates/reading/index.html) 只保留页面骨架、bootstrap 数据和模块脚本引入
- 阅读页结构片段统一收进 [templates/reading/partials](/Users/hao/OCRandTranslation/templates/reading/partials)
- 阅读页专属样式统一收进 [static/reading/reading.css](/Users/hao/OCRandTranslation/static/reading/reading.css)
- 阅读页脚本统一收进 [static/reading](/Users/hao/OCRandTranslation/static/reading)

| 文件 | 作用 |
|---|---|
| [templates/reading/index.html](/Users/hao/OCRandTranslation/templates/reading/index.html) | 阅读页主模板壳：主体布局、bootstrap 数据、partial 组合、模块脚本入口 |
| [templates/reading/partials/_top_controls.html](/Users/hao/OCRandTranslation/templates/reading/partials/_top_controls.html) | 导出弹窗、页头导航、阅读视图切换与工具栏 |
| [templates/reading/partials/_translation_session_card.html](/Users/hao/OCRandTranslation/templates/reading/partials/_translation_session_card.html) | 统一后台翻译任务卡 |
| [templates/reading/partials/_entry_list.html](/Users/hao/OCRandTranslation/templates/reading/partials/_entry_list.html) | 标准视图 / FNM 视图共用正文渲染 |
| [templates/reading/partials/_page_action_bar.html](/Users/hao/OCRandTranslation/templates/reading/partials/_page_action_bar.html) | 页级重译 / OCR / FNM 页编辑动作 |
| [templates/reading/partials/_page_notes_panel.html](/Users/hao/OCRandTranslation/templates/reading/partials/_page_notes_panel.html) | 统一底部注释区 |
| [templates/reading/partials/_page_editor_modal.html](/Users/hao/OCRandTranslation/templates/reading/partials/_page_editor_modal.html) | 标准整页段落编辑器与本页历史 |
| [templates/reading/partials/_floating_controls.html](/Users/hao/OCRandTranslation/templates/reading/partials/_floating_controls.html) | 浮动翻页与折叠态 PDF 打开按钮 |
| [static/reading/core.js](/Users/hao/OCRandTranslation/static/reading/core.js) | bootstrap、store、dispatch、基础 UI 状态 |
| [static/reading/navigation.js](/Users/hao/OCRandTranslation/static/reading/navigation.js) | 阅读导航、URL 参数与跳页面板 |
| [static/reading/page_editor.js](/Users/hao/OCRandTranslation/static/reading/page_editor.js) | 标准页整页编辑器与 FNM 只读诊断适配 |
| [static/reading/task_session.js](/Users/hao/OCRandTranslation/static/reading/task_session.js) | 后台翻译任务卡、SSE 与轮询 |
| [static/reading/index.js](/Users/hao/OCRandTranslation/static/reading/index.js) | 页面级协调层：PDF 面板、导出、重解析、初始化桥接 |
| [static/reading/reading.css](/Users/hao/OCRandTranslation/static/reading/reading.css) | 阅读页专属样式：PDF 面板、导航、任务卡、浮动按钮、页编辑器、预览卡 |

### 翻译运行态

- 后台翻译启动统一走 [translation/translate_launch.py](/Users/hao/OCRandTranslation/translation/translate_launch.py)
- 翻译运行态与事件缓存统一走 [translation/translate_runtime.py](/Users/hao/OCRandTranslation/translation/translate_runtime.py)
- 路由层和后台 worker 现在都统一走 [persistence/storage.py](/Users/hao/OCRandTranslation/persistence/storage.py) 的 `get_translate_args()`
- FNM 正式真相层当前固定为：`fnm_chapters`、`fnm_section_heads`、`fnm_note_regions`、`fnm_note_items`、`fnm_note_links`、`fnm_translation_units`
- `fnm_translation_units` 现通过 `owner_kind / owner_id` 显式区分 `chapter` 与 `note_region`
- FNM 翻译顺序固定为：先按 `fnm_chapters` 顺序，再按章内正文块顺序；尾注区单独按 `note_region` 顺序处理
- `fnm_page_entries` 已从正式主链退出；诊断页需要的页投影统一现算，不再作为导出或状态主真相

### 跨页段落修复

- 跨页误拆修复已经接入 [document/text_processing.py](/Users/hao/OCRandTranslation/document/text_processing.py)
- 当前保守规则是：上一页末段未完句，且下一页首段是正文时，即使首字母大写，也会判断是否应续接
- 统一句尾判断收口在 [document/text_utils.py](/Users/hao/OCRandTranslation/document/text_utils.py)
- 审计命令在 [scripts/rebuild_doc_derivatives.py](/Users/hao/OCRandTranslation/scripts/rebuild_doc_derivatives.py)，支持 `--audit-segmentation`

### 文字层乱码修复

某些PDF使用非标准字体编码（如 Identity-H 无 Unicode 映射），导致提取的文字是乱码。

**处理流程**：
1. OCR解析时自动检测每个block的文本质量
2. 检测到乱码时，尝试常见偏移修复（+48、-48、+32等）
3. 修复成功则使用修复后的文本
4. 无法修复时保留原文，并在日志中记录

**核心模块**：[document/text_layer_fixer.py](/Users/hao/OCRandTranslation/document/text_layer_fixer.py)

**API**：
```python
from document.text_layer_fixer import detect_and_fix_text, GarbledTextError

# 自动检测修复
fixed_text, method = detect_and_fix_text(raw_text, raise_on_failure=False)
# method: 'original'=原文有效, 'offset_48'=用+48修复, None=修复失败

# 需要详细诊断时
try:
    fixed_text, method = detect_and_fix_text(raw_text, raise_on_failure=True)
except GarbledTextError as e:
    print(e)  # 包含乱码样本、已尝试偏移、诊断建议
```

**解析结果**：`parse_ocr()` 返回值新增 `garbled_stats` 字段：
```python
{
    "total_blocks": 1234,      # 总block数
    "fixed_blocks": 100,       # 成功修复的block数
    "failed_blocks": 50,       # 修复失败的block数
    "methods": {"offset_48": 80, "offset_32": 20},  # 使用的修复方法
    "failed_pages": [14, 45, 52]  # 有无法修复乱码的页码
}
```

## 稳定接口

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
- `GET /api/reading_view_state`
- `GET /api/doc/<doc_id>/fnm/status`
- `GET /api/doc/<doc_id>/fnm/notes`
- `GET /pdf_toc`
- `GET /pdf_page/<file_idx>`
- `GET /pdf_file`
- `GET /download_md`
- `GET /export_md`
- `GET /export_pages_json`
- `GET /export_source_markdown`
- `GET /process_sse`
- `GET /translate_all_sse`

### 稳定改状态接口

这些接口统一要求 CSRF token：

- `POST /upload_file`
- `POST /api/upload_preferences`
- `POST /reparse`
- `POST /api/doc/reparse_enhanced`
- `POST /reparse_page/<page_bp>`
- `POST /api/doc/run_visual_toc`
- `POST /start_from_beginning`
- `POST /start_reading`
- `POST /fetch_next`
- `POST /retranslate/<bp>`
- `POST /save_manual_original`
- `POST /save_manual_revision`
- `POST /start_translate_all`
- `POST /api/doc/<doc_id>/fnm/translate`
- `POST /stop_translate`
- `GET/POST /api/page_editor`
- `POST /save_settings`
- `POST /save_glossary`
- `GET/POST /api/glossary`
- `PUT/PATCH /api/glossary/<term>`
- `DELETE /api/glossary/<term>`
- `POST /api/glossary/import`
- `POST /start_glossary_retranslate`
- `POST /api/toc/import`
- `POST /api/toc/update_user`
- `POST /api/toc/set_offset`
- `POST /api/toc/resolve_visual_item`
- `POST /api/toc/update_auto_visual`
- `POST /api/toc/save_visual_draft`
- `POST /api/toc/commit_visual_draft`
- `POST /switch_doc/<doc_id>`
- `POST /delete_doc/<doc_id>`
- `POST /delete_docs_batch`
- `POST /reset_text`
- `POST /reset_text_action`
- `POST /reset_all`

旧的单模型切换接口 `POST /set_model/<key>` 与 `POST /set_visual_model/<key>` 已删除；模型选择只通过 `POST /save_settings` 保存两组三槽模型池。

其中 `POST /retranslate/<bp>` 还要求显式目标参数：

- `target=custom`
- `target=builtin:<key>`

## 主数据流

1. `upload_file` 把原始文件交给 [pipeline/task_document_pipeline.py](/Users/hao/OCRandTranslation/pipeline/task_document_pipeline.py) 的 `process_file`
2. 文档流水线调 [ocr_client.py](/Users/hao/OCRandTranslation/ocr_client.py) / [document/pdf_extract.py](/Users/hao/OCRandTranslation/document/pdf_extract.py)，再写入 [persistence/storage.py](/Users/hao/OCRandTranslation/persistence/storage.py) 和 `SQLiteRepository`
3. 阅读页 `reading` 从 [config.py](/Users/hao/OCRandTranslation/config.py)、[persistence/storage.py](/Users/hao/OCRandTranslation/persistence/storage.py)、`SQLiteRepository` 与 [web/reading_view.py](/Users/hao/OCRandTranslation/web/reading_view.py) 组装当前页
4. 用户触发翻译后，由 [web/translation_routes.py](/Users/hao/OCRandTranslation/web/translation_routes.py) 调 [translation/translate_launch.py](/Users/hao/OCRandTranslation/translation/translate_launch.py) 启动后台任务
5. 单页翻译内部调用 [translation/service.py](/Users/hao/OCRandTranslation/translation/service.py) + [translation/translator.py](/Users/hao/OCRandTranslation/translation/translator.py)，结果写回 SQLite
6. 阅读页通过 SSE + 轮询拿进度、用量、段落草稿和阅读视图状态
7. 导出时由 [persistence/storage.py](/Users/hao/OCRandTranslation/persistence/storage.py) 组合 `storage_markdown.py` / `storage_endnotes.py` 生成 Markdown

导出接口当前稳定参数：

- `bp_ranges=19-32,53-70`：按页码区间（章节）导出
- `exclude_boilerplate=1`：启用“非主体页过滤”（默认关闭）
- `format=fnm_obsidian`：
  - `GET /download_md` 返回 Obsidian 章节包 ZIP（`index.md` + `chapters/*.md`）
  - `GET /export_md` 返回导出预览 Markdown（用于阅读页弹窗预览）
  - 导出正文与定义统一使用章节本地 `[^n]`，每章编号从 1 重置

## 测试分层与发布回归入口

### 自动回归

| 路径 | 作用 |
|---|---|
| [tests/integration/test_backend_backlog.py](/Users/hao/OCRandTranslation/tests/integration/test_backend_backlog.py) | 后端 backlog 回归与接口约束 |
| [tests/integration/test_sqlite_store.py](/Users/hao/OCRandTranslation/tests/integration/test_sqlite_store.py) | SQLite 仓储与 schema 回归 |
| [tests/integration/test_sqlite_mainline.py](/Users/hao/OCRandTranslation/tests/integration/test_sqlite_mainline.py) | SQLite 主链路回归 |
| [tests/integration/test_tasks_streaming.py](/Users/hao/OCRandTranslation/tests/integration/test_tasks_streaming.py) | 任务流、流式翻译、阅读页状态回归 |
| [tests/integration/test_translate_stop_flow_real_docs.py](/Users/hao/OCRandTranslation/tests/integration/test_translate_stop_flow_real_docs.py) | 真实文档主流程回归 |
| [tests/unit/test_translator_streaming.py](/Users/hao/OCRandTranslation/tests/unit/test_translator_streaming.py) | provider 流式翻译与错误处理 |
| [testsupport.py](/Users/hao/OCRandTranslation/testsupport.py) | CSRF 与 test client 辅助 |

发布前核心自动回归命令：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

### 真实联调

浏览器级联调脚本：

- [scripts/e2e_full_manual.py](/Users/hao/OCRandTranslation/scripts/e2e_full_manual.py)

发布前真实联调命令：

```bash
python3 -c "import app; app.app.run(debug=False, port=8081, threaded=True)"
python3 -c "import scripts.e2e_full_manual as t; t.BASE='http://127.0.0.1:8081'; t.test_with_playwright()"
```

### 人工模拟测试

- [scripts/reader_sim_screenshots.py](/Users/hao/OCRandTranslation/scripts/reader_sim_screenshots.py)

这个脚本保留用于人工阅读体验复核，不作为发布前必须通过的自动门禁。

### scripts/ 目录

| 脚本 | 用途 |
|---|---|
| [scripts/e2e_full_manual.py](/Users/hao/OCRandTranslation/scripts/e2e_full_manual.py) | 浏览器级全流程联调脚本（非自动测试，需手动启动服务器） |
| [scripts/reader_sim_screenshots.py](/Users/hao/OCRandTranslation/scripts/reader_sim_screenshots.py) | 人文学者阅读模拟截图脚本（视觉验证用） |
| [scripts/analyze_segment_duplicates.py](/Users/hao/OCRandTranslation/scripts/analyze_segment_duplicates.py) | 段落重复分析 CLI 工具 |
| [scripts/audit_footnote_structures.py](/Users/hao/OCRandTranslation/scripts/audit_footnote_structures.py) | 脚注结构审计 CLI 工具 |
| [scripts/rebuild_doc_derivatives.py](/Users/hao/OCRandTranslation/scripts/rebuild_doc_derivatives.py) | 文档衍生数据重建与分段审计 |

## 维护原则

1. `DEV.md` 只写稳定事实，不写当天任务过程。
2. 路径、端口、目录名、接口名以当前代码为准，代码改了就同步更新。
3. 历史验证放 [verification.md](/Users/hao/OCRandTranslation/verification.md)，阶段进度和下一步计划放 [PROGRESS.md](/Users/hao/OCRandTranslation/PROGRESS.md)。

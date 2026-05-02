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
| [FNM_RE](/Users/hao/OCRandTranslation/FNM_RE) | FNM 七模块主链（`toc_structure -> book_assemble`），四层架构：`shared/`（工具层）→ `stages/`（阶段层）→ `modules/`（模块层）→ `app/`（应用层） |
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
### FNM_RE 四层架构

FNM_RE 采用严格的分层架构，依赖方向为 `shared ← stages ← modules ← app`：

| 层 | 目录 | 文件数 | 行数 | 职责 |
|---|---|---|---|---|
| 工具层 | `shared/` | 13 | 2,094 | 跨层常量、文本/注释/章节工具、ref 重写 |
| 阶段层 | `stages/` | 24 | 11,878 | 独立管道阶段（页面分区、注释区域、锚点、导出等） |
| 模块层 | `modules/` | 10 | 5,590 | 编排多个阶段的复合模块（TOC、切分、链接、合并等） |
| 应用层 | `app/` | 6 | 4,010 | 主链路接线（pipeline、mainline）、数据转换、持久化辅助 |
| 根目录 | — | 7 | 3,715 | 公开 API（`__init__.py`）、模型/常量定义、LLM 修补、翻译、状态 |

**关键 shared 模块**（2026-04-29 新增）：

| 文件 | 职责 |
|---|---|
| `shared/export_constants.py` | 导出相关正则常量、`_should_replace_definition_text`、`_UNICODE_SUPERSCRIPT_TRANSLATION` |
| `shared/ref_rewriter.py` | 注释引用重写（`replace_note_refs_with_local_labels` 等 4 个函数 + 辅助函数） |
| `shared/marker_sequences.py` | 原始 marker → note_id 序列构建（`_build_raw_marker_note_sequences`） |
| `shared/note_lookup.py` | 注释文本清理（`_sanitize_note_text`，由 `chapter_merge.py` 使用） |
| `shared/notes.py` | 注释解析 + 共享工具（`_safe_int`、`_safe_float`、`_split_contiguous_ranges`、`_collect_chapter_page_numbers`、`_chapter_mode_map`） |
| `shared/text.py` | 文本工具（`_looks_like_bibliography_entry`、`_summary_title_key`、`page_markdown_text`） |

**app/ 目录**（2026-04-29 拆分）：

| 文件 | 行数 | 职责 |
|---|---|---|
| `app/pipeline.py` | 1,310 | `build_phase1~6_structure()` 主链 + `build_module_pipeline_snapshot()` |
| `app/pipeline_converters.py` | 686 | `ModulePipelineSnapshot` + 数据转换函数（模块输出 → DB Record） |
| `app/mainline.py` | 1,404 | doc/repo 感知主线接线层（状态、导出 ZIP、诊断入口） |
| `app/mainline_repo.py` | 314 | DB 记录与 Record 类型互转函数 |
| `app/persist_helpers.py` | — | 序列化辅助函数（`_safe_list`、`serialize_*_for_repo` 等） |

**模块层关键文件**：

| 文件 | 行数 | 职责 |
|---|---|---|
| `modules/toc_structure.py` | 354 | 模块一：目录结构与章节角色判定 |
| `modules/book_note_type.py` | — | 模块二：章节注释模式判定 |
| `modules/chapter_split.py` | 872 | 模块三：章节切分、注释区域绑定与材料化 |
| `modules/note_linking.py` | 1,498 | 模块四：正文锚点与注释项链接闭合 |
| `modules/ref_freeze.py` | — | 模块五：引用冻结与翻译单元生成 |
| `modules/chapter_merge.py` | — | 模块六：单章 Markdown 合并 |
| `modules/book_assemble.py` | 395 | 模块七：整书组装、语义审计与导出收口 |
| [model_capabilities.py](/Users/hao/OCRandTranslation/model_capabilities.py) | 内置模型能力目录：chat / mt / vision 模型、流式模式与 companion fallback | 243 |

### Phase 职责边界（树状原则在架构层的体现）

每个 phase 只有一种决策权，不重复、不下放。详见 [AGENTS.md § FNM Pipeline 数据流与 phase 职责边界](/Users/hao/OCRandTranslation/AGENTS.md)。

| Phase | 唯一决策权 | 禁止 |
|---|---|---|
| 1 TOC | 页面 role + 章节边界 | 不判断 footnote/endnote |
| 2 Split | **note_kind 分类（全书唯一来源）** + chapter_note_mode（聚合） | 不匹配 link，不猜测 anchor |
| 3 Link | body anchor 检测 + link 匹配 + 修复 | **不能重分类 note_kind**，不能用 chapter_mode 跳过修复 |
| 3.5 LLM | LLM 合成 anchor + link override | 不能绕过 Phase2 的 note_kind |
| 4 Freeze | matched link 注入正文 + 翻译单元 | 不修改匹配结果 |
| 5 Merge | 章 markdown 合并 | 不修改 link |
| 6 Export | 整书组装 + 最终审计 | 不修改任何上游数据 |

**核心规则**：书型问题（某章是 footnote_primary 还是 chapter_endnote_primary，某个 item 是 footnote 还是 endnote）必须在 Phase 2 解决。下游 phase 只能消费 Phase 2 的分类结果，不能因为"chapter_mode 不匹配"就跳过处理。

### 代码行数快照（2026-04-29）

统计口径：按 `*.py` 逐行统计，忽略运行产物目录（如 `.venv/`、`local_data/`、`logs/`、`output/`）。

| 范围 | 文件数 | 总行数 |
|---|---:|---:|
| 主链运行代码（`app/config/logging/launcher/model/ocr` + `document/` + `persistence/` + `pipeline/` + `translation/` + `web/`） | 72 | ~31,000 |
| FNM_RE（`FNM_RE/**/*.py`） | 68 | 29,303 |
| 自动化测试（`tests/**/*.py`） | 87 | ~37,000 |
| 工程脚本（`scripts/**/*.py`） | 12 | 6,191 |
| 归档（`legacy/*.py`） | 7 | — |

### 测试当前状态（2026-04-29）

全部单元测试：`python3 -m unittest discover -s tests/unit -p 'test_*.py'`

| 指标 | 数值 | 说明 |
|------|------|------|
| 总测试数 | 1,046 | — |
| 失败 | 64 | 全部为 Biopolitics/Goldstein 等 fixture 数据断言失败（pre-existing） |
| 错误 | 1 | `test_run_post_translate_export_checks`（pre-existing） |
| 跳过 | 1 | — |

验收测试（重构 guardrail）：`python3 -m unittest tests.unit.test_fnm_re_phase6 tests.unit.test_fnm_re_module6_merge tests.unit.test_fnm_re_module7_export`

- 42 tests, 1 failure（`test_container_exported_as_chapter_is_blocking`，pre-existing）

### 工程脚本（2026-04-29 清理后）

保留的 13 个活跃脚本：

| 脚本 | 用途 |
|------|------|
| `test_fnm_incremental.py` | 单本或少量书的 FNM 增量验证；冻结已确认成果，层层推进 |
| `test_fnm_real_batch.py` | 多书回归批测（含 LLM repair + Obsidian 导出） |
| `onboard_example_books.py` | 新样本接入（导入 PDF + OCR + FNM 快照） |
| `generate_visual_toc_snapshots.py` | 生成/刷新 visual TOC 快照 |
| `audit_fnm_exports.py` | FNM 导出全量审计 |
| `apply_manual_toc_to_examples.py` | 手动目录绑定到样本 |
| `rebuild_doc_derivatives.py` | 重建文档衍生数据 |
| `reingest_fnm_from_snapshots.py` | 从快照重新注入 FNM 数据 |
| `run_fnm_llm_repair.py` | LLM 修补 CLI |
| `run_fnm_llm_tier1a.py` | Tier 1a 工作流批量 LLM 修补 |
| `analyze_segment_duplicates.py` | 段落重复分析工具 |
| `audit_footnote_structures.py` | 脚注结构审计工具 |

已归档至 `legacy/`：`migrate_split_sqlite.py`、`cleanup_orphan_state.py`、`e2e_full_manual.py`、`reader_sim_screenshots.py`

### FNM 测试脚本分层

三种测试脚本，数据源和产物不同，禁止混用。详细说明见 [AGENTS.md § FNM 测试脚本分层](/Users/hao/OCRandTranslation/AGENTS.md)。

| 脚本 | 用途 | LLM 消耗 | 产物 |
|---|---|---|---|
| `test_fnm_incremental.py` | 单书快速验证 + LLM repair，冻结已确认成果 | 可选（`--repair`） | 终端输出（含时间戳） |
| `test_fnm_real_batch.py` | 多书完整回归 | 视觉模型 + LLM repair | `latest.fnm.obsidian.zip` + `FNM_REAL_TEST_REPORT.md` 等 |

**时间戳约定**：
- 增量脚本每次运行输出 `run_ts`（UTC ISO8601），作为本次数据的唯一时间标识。
- Pipeline run 在 SQLite `fnm_runs` 表中记录 `created_at`。
- 实批报告 `FNM_REAL_TEST_REPORT.md` 的 `generated_at` 若早于最近一次 pipeline run，报告视为过期。
- **判断任何 blocker 前，先确认数据来源的时间戳。**

**Module vs Persisted 分叉**：
- `Module Phase 3` = `build_module_pipeline_snapshot()` 的模块管道输出，是 Phase 3 gate 的权威来源。
- `Persisted note_links` = SQLite 落库读回，是 Phase 4-6 持久化后的数据。
- 两者 matched 数不同时，Phase 4 blocker（如 `freeze_matched_ref_not_injected`）会解释原因。不能把 persisted readback 当成 Phase 3 gate 失败。

常用命令：

```bash
# 只跑 pipeline（Phase 1-6，无 LLM repair）
.venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics

# 多本书回归
.venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics,Germany_Madness

# 只读当前 DB，不重跑 pipeline
.venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics --check

# pipeline + LLM repair，会消耗 token
.venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics --repair
```

### FNM_RE 维护约定

**依赖方向**：`shared/` 不依赖任何 FNM_RE 内部模块；`stages/` 可依赖 `shared/`；`modules/` 可依赖 `stages/` + `shared/`；`app/` 可依赖所有层。

**死代码归档**：不再使用的函数迁移到 `legacy/` 目录（已在 `.gitignore` 中），保留 git history 可追溯。`legacy/` 下文件不入库。

**`dev/` 目录**：包含管道门控（`gates.py`）、阶段运行器（`phase_runner.py`）、诊断投影（`diagnostics.py`）、线程池（`thread_pool.py`）、导入/重置工具等。这些是生产代码，命名待改进（`dev/` 有误导性，实际是管道支撑模块）。

**重构记录**（2026-04-29 完成）：

*阶段 1-2：共享模块提取与文件拆分*
- 新建 5 个 shared 模块（`export_constants`、`ref_rewriter`、`marker_sequences`、`note_lookup`、`review_overrides`）
- 拆分 `pipeline.py`（1917→1310）+ `pipeline_converters.py`（686）
- 拆分 `mainline.py`（1848→1404）+ `mainline_repo.py`（314）
- 消除 `_safe_int`/`_safe_float`/`_split_contiguous_ranges`/`_chapter_mode_map`/`_collect_chapter_page_numbers` 等 11 处跨文件重复
- 消除 `_looks_like_bibliography_entry`/`_summary_title_key`/`_page_markdown` 等 5 处跨文件重复
- `group_review_overrides` 3 副本 → `shared/review_overrides.py` 单一来源
- `_build_export_chapters` → 公开 API `build_export_chapters`
- 死代码归档：`build_note_text_by_id_for_chapter`、`_overlay_repo_*`、`_apply_pipeline_state_override` → `legacy/`

*阶段 3-4：模块边界加固 + 效率优化*
- `chapter_merge.py` 两条跨层引用切换到 shared
- `toc_semantics.py` 9 个 page_partition 重复函数 → 导入
- `_build_chapter_note_modes` O(C×R) → O(C+R) 优化
- `_normalize_title_key` 3 个命名冲突 → 按语义重命名
- `_sanitize_note_text` 2 副本 → `shared/note_lookup.py`
- `__import__` 反模式 3 处 → 直接调用

*测试与脚本清理*
- 修复重构引入的 2 个回归 bug（`@dataclass` 误删、`_to_plain` 误删）
- 归档 1 个过时测试（`test_llm_repair_usage.py`）
- 归档 4 个过期脚本（迁移/清理/手动测试）
- 修复 `FNM_RE/__init__.py` 中 `run_llm_repair` → `request_llm_repair_actions`

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
- `scripts/test_fnm_real_batch.py` 默认按 manifest 中 `include_in_default_batch=true` 的书目执行
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

## Biopolitics 全量调试经验 — 贯通式问题的发现与修复

以下记录以 Biopolitics（福柯《生命政治的诞生》，1978-1979 年法兰西学院讲座）为样本，从头到尾串联全链调试，暴露了 9 个结构性缺陷。这些缺陷在单模块测试中几乎不可见，因为每本书的 OCR 噪声、TOC 版式、脚注与尾注的混排方式各不相同——单点测试用 mock 数据容易通过，但真实 PDF 端到端跑下来就会暴露。

### 0. 这本书的物理特征（理解问题的前提）

要理解下文所有问题，必须先知道 Biopolitics 作为一本学术书的物理结构。不了解这些，代码就不知道自己在处理什么。

**书的组成**：370 页 PDF。前半是封面/版权/Avertissement（P7-16），中间是 12 次讲座正文 + 章末尾注（P17-332），后半是 RÉSUMÉ DU COURS + SITUATION DES COURS + INDICES（P333-349）。

**版式特征**：
- **每章结构**：讲座正文 → 末尾连续 NOTES 页（尾注）。NOTES 页上是一张连续的编号列表（1, 2, 3, ...18），内容是学术文献引用。
- **页脚注**：正文页底部有一个水平分割线，线下是编辑者添加的脚注。脚注标记使用 `*`（星号），不是数字。内容多为"Manuscrit, p. 10: ..."、"M. Foucault ajoute: ..."、"Lapsus manifeste" 之类。
- **手稿札记**：第 1 讲末尾（p37-39），福柯准备了但没有在课上读完的讲稿提纲。法国编辑把这些手稿内容也排进了 p37 的脚注区域，标记为 1. 2. 3. 4. 和 a. b. c.。它们是福柯自己写的概念阐述（"Le libéralisme, c'est aussi une pratique..."），不是学术引用。
- **目录**：目录 PDF 列出了 12 讲 + RÉSUMÉ + SITUATION + INDICES。目录条目没有显式列出 NOTES——这是"每章末尾隐式接尾注"的版式。LLM 分析目录截图时返回 `endnotes_summary.present=false`，因为目录里确实没有叫"Notes"的条目。
- **尾注页没有标题**：p40 第一条直接是 "2. Robert Walpole..."（p39 有 `## NOTES` 标题，但 p40 没有）。OCR 的 note_scan 对无标题的连续尾注页判断为 `mixed_body_endnotes` 或 `body`，不出 `endnote_collection`。

**OCR 噪声特征**：
- 法语重音和 ligature（œ, æ, É, è, à, ç）经常被 OCR 错读
- 上标 `e`（如 XVIIe, XXe）被 OCR 误作 `°`、`º`、`®` 或 HTML `<sup>e</sup>`
- 尾注页上的数字上下文极其密集——出版年份（1979）、ISBN、卷号、页码全部是数字，OCR 容易把年份当 marker
- 跨页断词（"gouverne-" 在页末、"ment" 在下一页开头）普遍存在
- 脚注和尾注在 OCR 层难以区分——两者都在"页面底部"，OCR 引擎统一标为 footnote

### 1. page_role 在中转过程中被覆盖

**图书背景**：Biopolitics 有 65 页连续的尾注页（每章末尾 3-8 页 NOTES），这些页的内容全是编号文献引用。page_partition 阶段正确识别了 `note` 角色，但写入数据库时全部变成了 `other`。

**现象**：`build_page_partitions` 产出 page_role 计数为 note:65, body:282, other:15，但写入 SQLite 后变成 note:0, other:86。然而 `role_reason` 字段仍然保留了 `note_scan_collection` / `note_continuation`，说明早期识别是正确的，但在某个中转环节被覆盖了。

**后果链**：`note` 角色全部消失 → `first_note_page=None` → endnote region 无法识别（`_is_endnote_candidate_page` 要求 page_role=note）→ endnote_region_rows=[] → 所有尾注找不到归属章 → 大量 orphan_note → 多个阻塞原因。

**根因**：`FNM_RE/app/pipeline.py` 中的 `_legacy_page_role_from_toc_role` 函数只处理了三种角色，其余全部打成 `other`：

```python
if token in {"chapter", "post_body"}: return "body"
if token == "front_matter": return "front_matter"
return "other"  # ← note/noise 全部变成 other
```

函数名叫 `legacy_page_role`，但它是 Phase1→Phase2 的关键中转点。page_partition 正确产出的 `note` 角色在这里被丢弃。

**修法**：补 `note` 和 `noise` 透传分支。1 行修改，连锁消解 endnote region 从 0→13、first_note_page 从 None→p40。

**教训**：中转函数（legacy/fixup/map 类）是角色丢失的第一高发区。每增加一个新 role 值，必须同步更新全链所有中转点，不能假定角色白名单已覆盖全部情况。排查方法：对比 `build_page_partitions` 的角色分布和数据库 `fnm_pages` 的角色分布——两者的 `note` 计数应该一致。

### 2. 模块管道与 APP 管道口径分裂

**图书背景**：ch12（Leçon du 4 avril 1979）是最后一讲。正文页有多个脚注（编辑注），同时末尾有 33 条尾注。body anchor 扫描检测到了 7 个脚注标记但只有 2 个 endnote 标记——因为 ch12 的正文中尾注引用多用在讨论内部，锚点被 OCR 丢失或被脚注标记淹没。

**现象**：ch12 的 `note_mode` 在模块管道中被判为 `footnote_primary`，但实际有 33 条 endnote 和 1 个 chapter_endnotes region。ch12 导出时 refs=2（几乎全部变 `*`），与金标 refs=32 差距巨大。数据库里却看到 `chapter_endnotes` 模式——数据不一致。

**根因**：代码库中存在两条并行的管道，对同一个概念（chapter_note_mode）使用不同判定逻辑：

| 管道 | 数据源 | 判定依据 | 消费者 |
|---|---|---|---|
| APP 管道 | `_build_chapter_note_modes` | note_regions（看是否有 endnote 区域） | `build_phase4_status` |
| 模块管道 | `build_book_note_profile` → `book_type_result` | body anchor 分布（看 body 中哪种标记多） | `build_module_gate_status` |

模块管道只看 body 中哪种标记多，不知道章末有 33 条 endnote。APP 管道能看到 note_regions 所以会正确判定。但 batch test 走的是模块管道。

**修法**：三处协同修改。(1) 判定优先级从 `footnote 优先` 改为 `endnote 优先`——学术书中脚注+尾注混排是常态，有尾注区才是一章的主注释类型。(2) `build_chapter_layers` 中用 endnote region 检测结果覆盖 `mode_by_chapter`。(3) `status.py:_chapter_mode_summary_from_snapshot` 改为优先读取 `split_result` 中已修正的 policy，兜底用 `book_type_result`。

**教训**：学术书（尤其人文学科）几乎每章都是脚注+尾注混排。脚注是编辑者在页底的说明，尾注是章节末尾的完整文献列表。如果代码"先看到脚注就判为 footnote_primary 章"，等于把学术书最常见的情况当作异常。正确做法：**先看有没有尾注区，有尾注区就是尾注主章，脚注是附带的**。

### 3. OCR 的 footnote label 对下游的污染链

**图书背景**：p37 是第 1 讲最后一页正文。页底有一个水平分割线，线下是 PaddleOCR 标注为 `footnote` 的区域。这个区域里有：编辑器加的星号脚注（"Entre guillemets dans le manuscrit..."）、福柯手稿中的编号提纲（1-4）、手稿正文转录（a./b./c./[p.27]-[p.32]）。OCR 引擎看到"页面底部 + 数字编号 + 比正文字号小"，就全部归类为 footnote label。

**现象**：ch01 导出 `### Footnotes` 区段里出现了 "Le libéralisme, c'est aussi une pratique..." 等内容。经调用视觉模型（qwen3.6-plus）直接检查 p37 的页面图像，模型确认这些条目的 `is_printed_footnote=false, is_manuscript_note=true`——是福柯手稿中的讲课提纲，不是学术引用。

**后果链**：OCR `fnBlocks.label=footnote` → note_items 继承 `kind=footnote` → export 编进 `### Footnotes` 区段 → 手稿提纲被当作脚注定义占据编号 [^1][^2][^3] → endnote 区段从 [^4] 开始 → 编号跳跃，与金标差距大。

**修法**：分离 footnote/endnote 编号空间。`_local_endnote_ref_number` 根据 `note_kind_by_id` 判断是否分配 `[^N]`。footnote 返回 None（正文用 `*` 标记，不参与编号池），endnote 独占 `[^N]`。footnote 定义用 `[footnote] \* text` 内联到对应段落后。

**教训**：OCR 的 label 是源头信息但不是最终真相。必须在 note_items 阶段做二次验证。两个最可靠的判别信号：(1) 页码位置——`page_role=note` 页上的条目 100% 是 endnote，不可能是 footnote；(2) 内容模式——以 "Cf."、"Ibid."、"作者名 (" 开头的长文本是学术尾注，以 "M. Foucault dit/ajoute:"、"Manuscrit"、"Lapsus" 开头的是编辑脚注。

### 4. 一页脚注区中三种内容的版面混排

**图书背景**：法国学术书的出版惯例是，福柯在课上没读完的手稿内容，编辑会以脚注形式补充在对应页底部。p37 的脚注区内容有三层：
- **① 编辑脚注**（`*` 标记）："Entre guillemets dans le manuscrit. M. Foucault, ici, renonce à lire les dernières pages..."——告诉读者这一页的正文是手稿转录，福柯未在课上读完。
- **② 手稿提纲**（编号 1-4）：福柯在手稿上用 1. 2. 3. 4. 标记的概念阐述——"Acceptation du principe qu'il doit y avoir quelque part une limitation..."、"Le libéralisme, c'est aussi une pratique..." 等。
- **③ 手稿正文**（字母 a./b./c./，页号 [p.27]-[p.32]）：福柯手稿中更详细的分点阐述，编辑在印刷时保留了原样。

OCR 把三层全部识别为同一种东西（footnote），但它们的属性完全不同：① 是真正的 page footnote，② 是 lecture notes 性质的提纲，③ 实际是正文转录（金标把它放回了正文位置）。

**修法**：保留全部脚注内容（①②），以 `[footnote] \* text` 格式内联到对应段落后。③ 在导出时随着正文段落出现（page_role=body），不是脚注也不在尾注区。金标模板同期待遇。

**教训**：不要因为内容是"手稿札记"就删除——原书印刷版把它们排在了脚注位置，是书的正式组成部分（读者可以通过星号脚注知道这是手稿转录）。但也不应把它们混入学术尾注的 `### NOTES` 区段——那里应该只有编号的学术文献引用。

### 5. 出版年份被 OCR 误读为尾注 marker

**图书背景**：在尾注页上，一段典型的学术引用文本是这样的：
> "Paris, Gallimard-Le Seuil (« Hautes Études »), 1997."
> 或 "rééd. 1976, p. 410"

OCR 的 marker 提取器扫描这段文本时，会把 "1997" 或 "1976" 识别为下一条尾注的编号——因为它在行首附近、是纯数字、后面跟着句号或逗号。于是 note_item 的 marker 变成了 1997。

**现象**：8 个 note_item 的 marker 是年份值：1976, 1979, 1967, 1974, 1977, 1999 等。它们在数据库中产生了一条 marker=1976 的 note_item，body 中当然找不到 `[^1976]` 引用，于是产生 orphan_note。

**根因**：`scan_anchor_markers` 在 body 侧有 `looks_like_year_marker` 过滤器（排除 1500-2100），但只在 body anchor 提取方向生效。note_item 提取方向（`_parse_numbered_line` → `_NUMBERED_NOTE_RE`）没有同样的过滤——因为 "1976" 在纯数字正则 `\d{1,4}` 里是完全匹配的 4 位数字。

**具体数据**：en-00003 marker=1976 夹在 en-00002(marker=3) 和 en-00004(marker=4) 之间。邻接关系是 3, 1976, 4, 5——年份是幽灵条目，不该存在。

**修法**：`_fix_year_markers_in_place` 在 note_items 提取后遍历 marker 序列：若一个 1500-2100 的数字夹在两个连续整数之间（如 3, 1976, 4），直接删除该幽灵条目；若占据了一个数字位（如 3, 1976, 5），用 `prev+1` 插值替换。

**教训**：OCR 的 marker 提取在尾注页上远不可靠——尾注页是所有页面类型中数字密度最高的（ISBN、出版年、卷号、页码、日期全部是数字）。必须对 note_items 侧的 marker 做和 body 侧同等严格的年份过滤，或者在提取后做邻接序列修正。修正必须在 note_linking 之前完成，因为幽灵条目会污染整个 anchor-note 匹配表。

### 6. visual_toc_endnotes_summary 口径不一致

**图书背景**：Visual TOC 的 LLM 分析 Biopolitics 目录截图时，看到的是 12 讲 + RÉSUMÉ + SITUATION + INDICES。没有任何条目叫 "Notes"——因为 Biopolitics 的版式是"每章末尾直接接 NOTES，目录不单独列出"。LLM 返回 `endnotes_summary.present=false` 是正确的——它只能看到目录上有什么。

但 page_partition 检测到了 65 页 `note` 角色页面，说明这本书确实有大量尾注页——只是目录没有显式条目。系统应当在发现 LLM 漏检时自行补偿。

**现象**：Phase 5 在 `build_phase1_structure` 中检测到 note 页 ≥3 后合成了 `endnotes_summary={present:true, subentry_pattern:"implicit_chapter_appended"}`。但 `status.py` 读取的是另一个数据源——`toc_result.diagnostics.chapter_meta.visual_toc_endnotes_summary`，这是模块层 TOC 的原生输出，没有被合成更新。结果 `endnotes_summary.present=None` 在 status 报告中持续存在。

**根因**：管道中的数据流并非单层回写。Phase 5 合成的新值只写入了 `Phase1Summary`（APP 管道层），但 `status.py` 从 `snapshot.toc_result`（模块层原生输出）读取。两个数据源独立。

**修法**：在 `build_module_pipeline_snapshot` 中，`split_result` 建成后（此时已知有 endnote regions），若 `toc_result` 的 `endnotes_summary.present` 为 falsy 但 split 层有 ≥3 章 chapter_endnotes region，直接 mutate `toc_result.diagnostics.chapter_meta.visual_toc_endnotes_summary` 为合成的 `present=true`。

**教训**：任何在中间阶段合成的字段，必须**同步回填**到上游模块的原始输出中（toc_result / book_type_result / split_result 等）。下游消费者（status.py、export 层、batch report）都从同一套模块输出读取，不同步就会出现"数据结构正确但状态报告错误"的幽灵阻塞。排查方法：先看数据结构是否正确（数据库中的 link/note/page_role 数量对不对），再看 status 报告是否一致——不一致就是中间阶段合成后没回填模块输出。

### 7. 章节边界只含正文不含尾注

**图书背景**：ch01 正文结束于 p39（最后一页是福柯的课堂结语 "J'avais pensé pouvoir vous faire cette année un cours sur la biopolitique..."），尾注在 p40-42（"1. Citation de Virgile..." 到 "18. Helmut Schmidt..."）。ch02 正文从 p43 开始。p40-42 属于 ch01 还是 ch02？物理上是 ch01 的尾注，但在 PDF 页码上落在 ch01 最后一页正文和 ch02 第一页正文之间的空隙。

**现象**：所有 12 章的 `chapter.end_page` 停在正文最后一页（ch01=39, ch02=66, ch03=90...），尾注页全部落在章间空隙。`orphan_local_ref=68`——正文引用了尾注号，但这些尾注所属的页面不在本章范围内，导致同章 markdown 中找不到定义。

**根因**：`chapter_skeleton` 在设定 `end_page` 时只看 body 页（`_build_structured_body_pages_for_chapter` 的切割逻辑），不看绑定的 endnote region。尾注 region 虽然通过 `_chapter_id_for_page` 的"最近前置章节"兜底规则正确绑到了前章，但 `chapter.end_page` 从未被更新。

**修法**：`build_chapter_layers` 中，note_regions 绑定后，对每个 `kind=endnote + scope=chapter` 的 region，用 `dataclasses.replace` 将对应 `ChapterRecord` 的 `end_page` 扩展到 `max(end_page, region.page_end)`，并将 region 的 `pages` 合并到 `chapter.pages`。

**教训**：对于每章末尾都有尾注区的学术书（占比极高），章节边界应该定义为 `max(body_end_page, endnote_region_end_page)`，不是 body_end_page 单值。这是物理版面的真实边界——一个讲座单元 = 正文 + 它的注释。

### 8. TOC 角色白名单与角色枚举脱节

**图书背景**：Biopolitics 的 TOC 分析产出了 19 个条目：Avertissement(front_matter)、COURS(container)、12 讲(chapter)、RÉSUMÉ(post_body)、SITUATION(post_body)、INDICES(container)、Index des notions(back_matter)、Index des noms(back_matter)。`container` 角色表示目录中的分组标题（类似于 Part I / Part II），不是可导出章节。`endnotes` 角色表示尾注容器（目录中显式列出 Notes 条目时出现，Biopolitics 没有所以为 0）。

**现象**：`toc_pages_unclassified` 阻塞一直存在。TOC 分析已经正确把 `COURS` 和 `INDICES` 标为 `container`，但 gate 检查 `toc.pages_classified` 的白名单是 `{front_matter, chapter, post_body, back_matter}`——没有 `endnotes` 和 `container`。所以这两个条目被视为"未分类"→ 阻塞。

**修法**：扩展白名单为 `{front_matter, chapter, post_body, back_matter, endnotes, container}`。`endnotes` 角色虽然在 Biopolitics 中没有出现（隐式尾注），但对显式列出 Notes 条目的书目是必需的。`container` 是合法且常见的 TOC 条目类型。

**教训**：gate 检查的白名单必须与 TOC 的角色枚举保持同步。每次在 `_build_page_roles` 或 `toc_semantics` 中新增 role 值，必须同时检查全链消费该 role 的所有 gate、filter、whitelist。排查方法：找出 TOC 输出中所有 role 的 distinct 值，与 gate 白名单做差集——多出来的值就是误阻塞的来源。

### 9. footnote/endnote 在导出中共用编号池

**图书背景**：在 Obsidian markdown 中，`[^1]` 是一个全局脚注引用。如果正文同时有脚注 `*` 和尾注 `1`，导出时全部转为 `[^N]`，Obsidian 会把它们当同一类脚注处理。但实际上脚注和尾注在学术书中是两种完全不同的注释类型：脚注在页底（编辑注），尾注在章末（文献引用）。金标模板中脚注用 `[footnote] \* text` 格式、不参与 `[^N]` 编号，尾注独占 `[^N]` 从 1 开始。

**现象**：修复前，ch01 正文所有引用（`*` + `1` + `2` + `3`...）统一被 `_rewrite_body_text_with_local_refs` 转为 `[^1] [^2] [^3]...`。脚注标记 `*` 被分配了 `[^1]` 编号，尾注 1 变成了 `[^4]`。`### NOTES` 的第一条是 `[^4]: 4. M. Foucault ne revient pas...` 而不是 `[^1]: 1. Citation de Virgile...`。

**修法**：导出层的 `_local_endnote_ref_number` 新增 `note_kind_by_id` 参数。查询该 note_id 的 kind：若为 footnote，返回 None（不分配 `[^N]`，正文保留 `*`）；若为 endnote，正常递增编号。4 个 `_replace_*` 函数全部适配。`_rewrite_body_text_with_local_refs` 透传 `note_kind_by_id`。章末只写 `### NOTES`（endnote），footnote 用内联 `[footnote] \* text`。

**教训**：Obsidian 的 `[^N]` 语法是一个扁平的全局脚注命名空间，不支持"局部编号 + 按类型分区"。学术书需要的却是"endnote 独占 [^N] 空间从 1 开始 + footnote 用独立标记不参与编号"。这个张力必须在导出层解决——不能把两种类型塞进同一个编号池。解决方案：在 body 替换阶段用 `note_kind_by_id` 分流，而不是等到了 `### NOTES` 区段再靠内容区分。

---

## 维护原则

---

## 维护原则

1. `DEV.md` 只写稳定事实，不写当天任务过程。
2. 路径、端口、目录名、接口名以当前代码为准，代码改了就同步更新。
3. 历史验证放 [verification.md](/Users/hao/OCRandTranslation/verification.md)，阶段进度和下一步计划放 [PROGRESS.md](/Users/hao/OCRandTranslation/PROGRESS.md)。

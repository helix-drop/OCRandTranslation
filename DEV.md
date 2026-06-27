# 外文文献阅读器 - 开发文档

这份文档只记录发布后仍然稳定的仓库事实。临时进展写入 [PROGRESS.md](/Users/hao/OCRandTranslation/PROGRESS.md)，验证结果写入 [verification.md](/Users/hao/OCRandTranslation/verification.md)。

## 项目定位

OCRandTranslation 是一个本地运行的外文文献阅读工具。当前主流程是：

上传 PDF / 图片 -> PaddleOCR 版面解析 -> 整理页文本与段落 -> LLM 翻译 -> 阅读页核对原文 / 译文 / 页级脚注 -> 导出 Markdown

当前仓库保留：

- 标准 OCR、阅读、翻译、术语词典
- PDF / 手动目录 / 视觉目录导航
- 页级脚注检测、阅读页展示和 Markdown 导出
- SQLite 文档库、翻译记录、目录状态和导出状态

当前仓库不再维护结构化脚注/尾注整书管线。相关项目已迁到 `/Users/hao/FEnoteTransToMD`，不要在本仓库恢复相关 Web/API 入口、SQLite 表、任务类型、测试书或批测脚本。

## 运行方式

| 入口 | 作用 |
|---|---|
| [start_managed.sh](/Users/hao/OCRandTranslation/start_managed.sh) | macOS / Linux 官方启动入口 |
| [start_managed.ps1](/Users/hao/OCRandTranslation/start_managed.ps1) | Windows PowerShell 启动入口 |
| [start_managed.bat](/Users/hao/OCRandTranslation/start_managed.bat) | Windows 双击入口 |
| `python3 app.py` | 直接启动 Flask |

默认端口：`8080`

## 本地数据目录

| 路径 | 内容 |
|---|---|
| `local_data/user_data/config.json` | API Key、模型池、术语表和部分阅读设置 |
| `local_data/user_data/data/catalog.db` | SQLite 目录库，保存文档索引和全局状态 |
| `local_data/user_data/data/documents/{doc_id}/doc.db` | 文档私有 SQLite，保存页面、翻译、目录和文档级状态 |
| `local_data/user_data/data/app.db` | 旧单库迁移来源/备份，不再作为运行时主链 |
| `local_data/user_data/data/documents/{doc_id}/source.pdf` | 每份文档的 PDF 副本 |
| `local_data/user_data/data/documents/{doc_id}/toc_visual_source.pdf` | 用户手动上传的目录 PDF |
| `local_data/user_data/data/documents/{doc_id}/toc_visual_screenshots/` | 用户上传的目录截图 |
| `local_data/user_data/data/documents/{doc_id}/toc_source.csv` 或 `.xlsx` | 当前生效的手动目录文件 |
| `local_data/user_data/data/documents/{doc_id}/logs/` | 当前文档的 OCR、重解析、翻译和视觉目录日志 |

这些内容默认不提交到 Git。

## SQLite

当前 `SCHEMA_VERSION = 25`。

核心表：

- `catalog.db`：`documents`、`app_state`
- `doc.db`：`documents`、`pages`、`translation_pages`、`translation_segments`、`translate_runs`、`translate_failures`、`segment_revisions`、`translation_page_revisions`、`app_state`

当前正式 schema 不包含 `fnm_*` 表。迁移和补列逻辑在 [persistence/sqlite_schema.py](/Users/hao/OCRandTranslation/persistence/sqlite_schema.py)。

## 代码结构

| 路径 | 作用 |
|---|---|
| [app.py](/Users/hao/OCRandTranslation/app.py) | Flask 启动壳，导出 `app = create_app()` |
| [config.py](/Users/hao/OCRandTranslation/config.py) | 本地目录、配置读写、模型池配置和文档列表 |
| [document/](/Users/hao/OCRandTranslation/document) | OCR 结果解析、PDF 文字层、文本整理、页级脚注检测 |
| [persistence/](/Users/hao/OCRandTranslation/persistence) | SQLite schema/repository、页面落盘、目录状态、Markdown 导出 |
| [pipeline/](/Users/hao/OCRandTranslation/pipeline) | 上传、OCR、重解析、视觉目录任务编排 |
| [pipeline/visual_toc/](/Users/hao/OCRandTranslation/pipeline/visual_toc) | 自动视觉目录：候选页扫描、视觉调用、组织归一、手动输入合并 |
| [translation/](/Users/hao/OCRandTranslation/translation) | 标准连续翻译、术语词典补重译、任务运行态和模型调用 |
| [web/](/Users/hao/OCRandTranslation/web) | Flask 路由、CSRF、阅读页、设置页、导出和目录接口 |
| [templates/](/Users/hao/OCRandTranslation/templates) | Jinja 页面模板 |
| [static/](/Users/hao/OCRandTranslation/static) | 前端 JS/CSS |
| [tests/](/Users/hao/OCRandTranslation/tests) | 单元、集成和浏览器 e2e 测试 |
| [scripts/](/Users/hao/OCRandTranslation/scripts) | 视觉目录快照、页面视觉检查和段落重复诊断脚本 |

模块归属以 [docs/code-ownership.md](/Users/hao/OCRandTranslation/docs/code-ownership.md) 为准。

## 关键流程

### 上传与 OCR

入口在 [web/document_routes.py](/Users/hao/OCRandTranslation/web/document_routes.py)。任务编排在 [pipeline/task_document_pipeline.py](/Users/hao/OCRandTranslation/pipeline/task_document_pipeline.py)，OCR 解析和页级文本整理在 [document/ocr_parser.py](/Users/hao/OCRandTranslation/document/ocr_parser.py)、[document/pdf_extract.py](/Users/hao/OCRandTranslation/document/pdf_extract.py)、[document/text_processing.py](/Users/hao/OCRandTranslation/document/text_processing.py)。

### 翻译

标准翻译入口在 [web/translation_routes.py](/Users/hao/OCRandTranslation/web/translation_routes.py)。后台任务由 [translation/translate_launch.py](/Users/hao/OCRandTranslation/translation/translate_launch.py) 启动，[translation/translate_worker_continuous.py](/Users/hao/OCRandTranslation/translation/translate_worker_continuous.py) 执行，[translation/translator.py](/Users/hao/OCRandTranslation/translation/translator.py) 负责真实模型请求。

### 视觉目录

视觉目录保留为当前主链能力，服务于阅读页章节导航和 Markdown 章节选择。相关代码在 [pipeline/visual_toc/](/Users/hao/OCRandTranslation/pipeline/visual_toc)、[web/toc_routes.py](/Users/hao/OCRandTranslation/web/toc_routes.py)、[persistence/storage_toc.py](/Users/hao/OCRandTranslation/persistence/storage_toc.py)。

### Markdown 导出

导出入口在 [web/export_routes.py](/Users/hao/OCRandTranslation/web/export_routes.py)。核心组合逻辑在 [persistence/storage.py](/Users/hao/OCRandTranslation/persistence/storage.py)、[persistence/storage_markdown.py](/Users/hao/OCRandTranslation/persistence/storage_markdown.py)、[persistence/storage_endnotes.py](/Users/hao/OCRandTranslation/persistence/storage_endnotes.py)。

这里保留的是标准 Markdown 导出里的页级脚注/尾注文本整理，不是结构化脚注/尾注整书管线。

## 测试

常用命令：

```bash
.venv/bin/python -m pytest tests/unit tests/integration tests/e2e -q
```

若本机未安装 Playwright，浏览器 e2e 会自动跳过；单元和集成测试仍应正常运行。

本轮剥离检查实测结果见 [verification.md](/Users/hao/OCRandTranslation/verification.md)。

## 当前代码规模（2026-06-02）

统计口径：按 `*.py` 逐行统计，忽略 `.venv/`、`local_data/`、`logs/`、`output/`、`tmp/`、`归档/`。

| 范围 | 文件数 | 总行数 |
|---|---:|---:|
| 主链运行代码（`app/config/logging/launcher/model/ocr` + `document/` + `persistence/` + `pipeline/` + `translation/` + `web/`） | 75 | 29,348 |
| 自动化测试（`tests/**/*.py`） | 33 | 16,483 |
| 工程脚本（`scripts/*.py`） | 3 | 964 |
| 全部 Python 文件（含本地 skills/测试辅助，不含运行产物和归档） | 119 | 47,349 |

## 归档

本次发现的 FNM 残留已归档到：

- `/Users/hao/OCRandTranslation/归档/fnm_residuals_20260602/`

此前剥离动作已有归档：

- `/Users/hao/OCRandTranslation/归档/fnm_mode_removed_20260601/`

后续检查主树时，默认排除 `归档/`、`.git/`、`.venv/`、`__pycache__/`、`local_data/`、`output/`、`tmp/`。

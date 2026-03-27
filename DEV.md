# 外文文献阅读器 - 开发文档

这份文档只放稳定说明，目的是让人快速看懂项目是什么、代码放在哪、数据怎么存。

## 项目是什么

这是一个基于 Flask 的文献阅读工具，主流程是：
上传 PDF 或图片 -> OCR 版面解析 -> 按页整理文本 -> 调用 LLM 翻译 -> 在阅读页查看和导出。

## 现在的技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python + Flask |
| OCR | PaddleOCR 远程接口 |
| 翻译 | DeepSeek / 阿里 Qwen |
| PDF 处理 | `pypdf`、`PyMuPDF` |
| 前端 | Jinja2 模板 + 原生 JS |
| 实时更新 | SSE |
| 存储 | SQLite（主链路）+ 本地配置文件 |

## 代码入口

| 文件 | 作用 |
|---|---|
| [app.py](/Users/hao/OCRandTranslation/app.py) | Flask 路由和页面入口 |
| [tasks.py](/Users/hao/OCRandTranslation/tasks.py) | OCR 任务、翻译任务、状态流 |
| [translator.py](/Users/hao/OCRandTranslation/translator.py) | LLM 翻译和结构整理 |
| [text_processing.py](/Users/hao/OCRandTranslation/text_processing.py) | 页面文本整理、段落合并 |
| [ocr_client.py](/Users/hao/OCRandTranslation/ocr_client.py) | OCR 接口请求 |
| [pdf_extract.py](/Users/hao/OCRandTranslation/pdf_extract.py) | PDF 文字层提取和页面渲染 |
| [storage.py](/Users/hao/OCRandTranslation/storage.py) | 页数据和翻译结果落盘 |
| [config.py](/Users/hao/OCRandTranslation/config.py) | 本地配置、多文档、目录管理 |

## 页面和样式

| 位置 | 作用 |
|---|---|
| [templates/](/Users/hao/OCRandTranslation/templates) | 所有页面模板 |
| [templates/reading.html](/Users/hao/OCRandTranslation/templates/reading.html) | 阅读页，最复杂的页面 |
| [static/style.css](/Users/hao/OCRandTranslation/static/style.css) | 全局样式 |

## 运行方式

| 方式 | 说明 |
|---|---|
| [start.sh](/Users/hao/OCRandTranslation/start.sh) | 一键建环境、装依赖、启动应用 |
| [start.ps1](/Users/hao/OCRandTranslation/start.ps1) | Windows PowerShell 一键启动 |
| [start.bat](/Users/hao/OCRandTranslation/start.bat) | Windows 双击入口，实际转调 `start.ps1` |
| `python3 app.py` | 直接启动 Flask |

默认端口是 `8080`。

当前项目目录与数据目录都相对仓库根目录组织，不依赖系统级安装目录：

- 代码入口在仓库根目录
- 用户数据默认写入 `local_data/user_data/`
- Windows 启动链路为 `start.bat -> start.ps1 -> .venv\\Scripts\\python.exe -> app.py`

## 数据怎么存

项目业务主链路已切到 SQLite，用户数据仍统一放在 `local_data/user_data/`。

| 路径 | 内容 |
|---|---|
| `local_data/user_data/config.json` | API Key、术语表、模型偏好 |
| `local_data/user_data/data/app.db` | SQLite 主库（文档、页面、翻译状态、页级与段级结果、失败页、PDF 目录） |
| `local_data/user_data/data/documents/{doc_id}/source.pdf` | 原始 PDF 副本 |

当前核心业务表包括：

- `documents`
- `pages`
- `translate_runs`
- `translation_pages`
- `translation_segments`
- `translate_failures`
- `app_state`

旧数据会从 `~/.foreign_lit_reader/` 自动迁移到新位置。

`documents` 表当前包含 `toc_json` 字段，用于保存 PDF 目录（TOC）扁平结构（`title/depth/file_idx`）。

## 当前发布口径（已达成）

以下口径已与 `PROGRESS.md` 对齐，并作为当前实现事实：

1. SQLite 主链路口径已统一：`active run + 当前生效页结果` 为单一判定路径。
2. 旧 JSON 主路径已退场：不再作为业务真相来源，仅保留调试/排障用途。
3. 回归测试缺口已补齐：`resume_bp / phase / partial_failed / error`，并已覆盖 `p.7 / p.16 / p.50 / p.199` 真实文档联调。
4. 文档口径已同步：`PROGRESS.md` 与 `DEV.md` 对当前主链路描述保持一致。

## 当前平台口径

按仓库内代码与启动脚本的当前实现，项目已具备以下平台入口：

1. macOS / Linux：`start.sh`
2. Windows 10 / 11：`start.ps1` 或 `start.bat`
3. 核心路径处理统一走 `os.path.join(...)`，主数据目录固定在仓库内 `local_data/user_data/`

当前这一定义来自代码静态核查与本机脚本检查；本轮未新增 Windows 实机启动记录时，不把“已在 Windows 实机跑通”写成稳定事实。

## 稳定后端接口

以下接口已进入稳定实现，可直接用于前端集成：

1. `GET /pdf_toc?doc_id=...`
   - 返回当前文档 PDF 目录（TOC）数据，来自 SQLite `documents.toc_json`。
2. 术语表细粒度接口：
   - `GET /api/glossary`
   - `POST /api/glossary`
   - `PUT/PATCH /api/glossary/<term>`
   - `DELETE /api/glossary/<term>`
3. 兼容入口保留：`POST /save_glossary` 继续可用（整表保存）。

## 稳定交互约束

以下规则属于长期稳定约束，后续迭代默认保持：

1. 上传或重解析进行中时，当前文档阅读入口必须禁用；切换到已完成解析的文档时恢复可用。
2. 首页入口语义保持分离：
   - “从 p.首个页码 开始读”仅负责进入阅读。
   - “清空翻译数据”始终保持独立按钮，不与“开始读”合并。
3. 首页文档操作区按钮顺序保持为“切换 / 清空翻译数据 / 删除”。
4. 首页文档区标题保持为“OCR-JSON解析成功文档”。
5. 阅读页“从指定页开始翻译”在任务运行中默认启用抢占切换：会先停止当前翻译，再从用户指定页重启，无需手动先点“停止”。
6. 阅读页左侧 PDF 面板支持拖拽调宽；拖拽时 PDF 页宽会同步重算。
7. PDF 图片查看区在横向查看时会阻止浏览器“返回上一页”手势继续接管，以免误触浏览器历史返回。

## 说明文件分工

| 文档 | 作用 |
|---|---|
| [DEV.md](/Users/hao/OCRandTranslation/DEV.md) | 稳定说明、结构、运行方式、数据位置 |
| [PROGRESS.md](/Users/hao/OCRandTranslation/PROGRESS.md) | 当前进度、最近实测、下一步工作 |
| [AGENTS.md](/Users/hao/OCRandTranslation/AGENTS.md) | 当前仓库的操作约束和工作规则 |
| [CLAUDE.md](/Users/hao/OCRandTranslation/CLAUDE.md) | 给 Claude/同类代理看的简版约束 |
| [verification.md](/Users/hao/OCRandTranslation/verification.md) | 人工或代理执行后的验证记录 |

## 维护原则

1. `DEV.md` 只写稳定事实，不写临时任务和当天结论。
2. 路径、目录名和默认端口以代码为准，改代码后要同步改文档。
3. 新问题、新结论放 `PROGRESS.md`，不要塞回 `DEV.md`。

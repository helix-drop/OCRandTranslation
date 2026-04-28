# 代码归属清单

这份清单只描述**当前代码职责**，不写历史设计。用于判断哪些模块属于正式主链、哪些只保留诊断、哪些应继续清理。

## `mainline`

这些模块属于当前正式产品主链，改动时要优先保证行为稳定：

- `document/`
  - 文档解析、OCR 后文本整理、页级文本工具
- `pipeline/document_tasks.py`
  - 标准上传/OCR/目录处理任务编排
- `pipeline/task_document_pipeline.py`
  - 首页进入后的正式任务/进度路由
- `pipeline/visual_toc/`
  - 自动视觉目录子系统：运行编排、候选页扫描、manual TOC 合并、组织归一与视觉调用
- `persistence/sqlite_store.py`
  - SQLite 统一仓储入口
- `persistence/sqlite_schema.py`
  - 当前 SQLite 正式 schema（版本 24）与迁移
- `persistence/sqlite_repo_fnm.py`
  - FNM 结构真相与翻译单元仓储
- `persistence/storage.py`
  - 标准文档、页面、导出等存储入口
- `persistence/storage_toc.py`
  - 手动目录 PDF/截图输入与视觉目录存储
- `translation/`
  - 标准翻译与 FNM 顺序翻译主链
- `web/document_routes.py`
  - 文档上传、补传目录、基础文档操作
- `web/export_routes.py`
  - 标准导出与 FNM Obsidian 导出
- `web/translation_routes.py`
  - 标准翻译/FNM 翻译入口与状态接口
- `web/reading_routes.py`
  - 标准阅读页主路由
- `FNM_RE/app/mainline.py`
  - FNM 主线接线层：`run_phase6_pipeline_for_doc` 串联七模块
- `FNM_RE/app/pipeline.py`
  - FNM 分阶段总入口：`build_phase1~6_structure`
- `FNM_RE/modules/toc_structure.py`
  - 模块一：目录结构与章节角色判定
- `FNM_RE/modules/book_note_type.py`
  - 模块二：书籍注释类型分析
- `FNM_RE/modules/chapter_split.py`
  - 模块三：章节切分、注释区域绑定
- `FNM_RE/modules/note_linking.py`
  - 模块四：正文锚点与注释项链接闭合
- `FNM_RE/modules/ref_freeze.py`
  - 模块五：引用冻结与翻译单元构建
- `FNM_RE/modules/chapter_merge.py`
  - 模块六：章节 Markdown 合并
- `FNM_RE/modules/book_assemble.py`
  - 模块七：整书组装、语义审计与导出收口
- `FNM_RE/status.py`
  - FNM 结构/进度主状态汇总

## `diagnostic`

这些模块保留，但只承担只读诊断、批测、审计或样本维护职责，不允许反向污染主链：

- `FNM_RE/page_translate.py`
  - 仅保留翻译单元 helper 与只读诊断投影 helper
- `FNM_RE/stages/diagnostics.py`
  - 从结构真相现算诊断页投影与注释摘要
- `web/reading_view.py`
  - FNM 只读诊断阅读上下文构建
- `scripts/test_fnm_batch.py`
  - 8 本基线批测（占位翻译模式）
- `scripts/test_fnm_real_batch.py`
  - 8 本基线批测（真实 LLM 视觉+修补模式）
- `scripts/generate_visual_toc_snapshots.py`
  - 视觉目录快照与诊断摘要
- `scripts/rebuild_doc_derivatives.py`
  - 重新生成派生产物；仅作维护/诊断脚本
- `scripts/audit_fnm_exports.py`
  - 导出抽样/全量审计
- `scripts/reingest_fnm_from_snapshots.py`
  - 从 test_example 快照重新注入 FNM 数据
- `test_example/`
  - 样本书、目录输入、快照与最新导出包

## `legacy_to_remove`

这些内容不应继续进入正式主链；若仍有残留引用，应继续迁走或删除：

- `fnm/` 目录（已迁移到 `FNM_RE/`）
- 任何基于旧表的持久化逻辑：
  - `fnm_notes`
  - `fnm_page_entries`
  - `fnm_page_revisions`
- 任何把 `rendered_sections` 当正式真相层的路径
- FNM 页编辑/页历史相关代码与接口
- 旧的"自动猜目录页即可进入正式 FNM 主链"的逻辑

## 当前判定规则

- 主链代码若需要 FNM 页面内容，只能读：
  - `fnm_chapters`
  - `fnm_section_heads`
  - `fnm_note_regions`
  - `fnm_note_items`
  - `fnm_note_links`
  - `fnm_translation_units`
- 诊断页可以现算页投影，但不能要求旧持久化页表存在。
- 若某模块同时被 `mainline` 和 `diagnostic` 使用，必须以主链行为为准，诊断侧适配主链，不允许反向要求主链保留旧实现。

# 代码归属清单

这份清单只描述当前仓库职责，用于判断哪些模块属于正式主链、哪些只承担维护或诊断职责。

## `mainline`

这些模块属于当前正式产品主链，改动时要优先保证行为稳定：

- `document/`
  - 文档解析、OCR 后文本整理、页级文本工具
- `pipeline/document_tasks.py`
  - 标准上传、OCR、目录处理任务编排
- `pipeline/task_document_pipeline.py`
  - 首页进入后的正式任务和进度路由
- `pipeline/visual_toc/`
  - 自动视觉目录子系统：候选页扫描、manual TOC 合并、组织归一与视觉调用
- `persistence/sqlite_store.py`
  - SQLite 统一仓储入口
- `persistence/sqlite_schema.py`
  - 当前 SQLite 正式 schema 与迁移
- `persistence/storage.py`
  - 标准文档、页面、导出等存储入口
- `persistence/storage_toc.py`
  - 手动目录 PDF/截图输入与视觉目录存储
- `translation/`
  - 标准连续翻译、术语词典补重译、流式状态
- `web/document_routes.py`
  - 文档上传、补传目录、基础文档操作
- `web/export_routes.py`
  - 标准 Markdown 导出
- `web/translation_routes.py`
  - 标准翻译入口与状态接口
- `web/reading_routes.py`
  - 标准阅读页主路由

## `diagnostic`

这些模块保留为诊断、样本维护或历史验证使用，不允许反向污染主链：

- `scripts/analyze_segment_duplicates.py`
  - 段落重复诊断
- `scripts/generate_visual_toc_snapshots.py`
  - 视觉目录快照与诊断摘要
- `scripts/vision_page_check.py`
  - 单页视觉检查辅助脚本
- `test_example/`
  - 当前主树只保留空目录占位和本地样本入口；不要放回结构化脚注/尾注整书测试书

## 已剥离边界

脚注/尾注结构化整书管线已迁到 `/Users/hao/FEnoteTransToMD`。本仓库不再维护相关源码、Web/API 入口、任务类型、导出格式、测试书或批测脚本。

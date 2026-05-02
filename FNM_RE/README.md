# FNM_RE

FNM（脚注/尾注机）新实现目录。旧 `fnm/` 模块已退役，主链完全切到 FNM_RE。

## 架构

FNM_RE 按七模块组织：

| 模块 | 文件 | 作用 |
|---|---|---|
| M1 | `modules/toc_structure.py` | 目录结构与章节角色判定 |
| M2 | `modules/book_note_type.py` | 全书注释类型分析 |
| M3 | `modules/chapter_split.py` | 章节切分、注释区域绑定 |
| M4 | `modules/note_linking.py` | 正文锚点与注释项链接闭合 |
| M5 | `modules/ref_freeze.py` | 引用冻结与翻译单元构建 |
| M6 | `modules/chapter_merge.py` | 章节 Markdown 合并 |
| M7 | `modules/book_assemble.py` | 整书组装、语义审计与导出收口 |

## 目录结构

```
FNM_RE/
├── __init__.py          # 对外统一入口
├── constants.py         # 常量定义
├── models.py            # 数据模型（dataclass）
├── review.py            # 人工审查覆盖
├── llm_repair.py        # LLM 修补锚点/链接
├── page_translate.py    # 翻译单元与诊断 helper
├── status.py            # 状态构建
├── app/                 # 应用入口层
│   ├── mainline.py      # 主线接线：run_phase6_pipeline_for_doc
│   ├── pipeline.py      # 分阶段入口：build_phase1~6_structure
│   └── persist_helpers.py
├── modules/             # 七模块核心
│   ├── toc_structure.py
│   ├── book_note_type.py
│   ├── chapter_split.py
│   ├── note_linking.py
│   ├── ref_freeze.py
│   ├── chapter_merge.py
│   ├── book_assemble.py
│   ├── contracts.py
│   └── types.py
├── stages/              # 子阶段处理
├── shared/              # 共享工具
└── handoff/             # 交接文档
```

## 对外入口

```python
from FNM_RE import (
    run_doc_pipeline,           # 运行完整 FNM 流水线
    load_doc_structure,         # 加载文档结构快照
    build_doc_status,           # 构建结构状态报告
    build_export_zip_for_doc,   # 构建导出 ZIP
    run_llm_repair,             # LLM 修补
    audit_export_for_doc,       # 审计导出质量
)
```

## 当前状态

- 七模块主链已完整落地，旧 `fnm/` 模块已退役
- 样本批测脚本：`scripts/test_fnm_incremental.py`（增量，冻结已确认成果）和 `scripts/test_fnm_real_batch.py`（实批，多书完整回归）
- Biopolitics 在真实模式管道中因 4 项阻塞原因未能通过（2026-04-28）
- 处理流程：`reingest → visual_toc → pipeline → llm_repair → rebuild → structure_verify → placeholder_translate → export_verify → zip`

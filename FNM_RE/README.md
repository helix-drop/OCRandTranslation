# FNM_RE

FNM（Footnote/Endnote Machine）—— 基于 OCR 的学术脚注/尾注自动提取管道。核心 pipeline 已用 Rust 重写（`fnm_re_rs/` 10 crates），此包仅通过 `fnm-re-rs` pyo3 wheel 暴露 surface API。

## 状态

- `FNM_RE/__init__.py` 是 thin wrapper（40 个 surface API），全部通过 `fnm-re-rs` Rust binding 实现
- 原 Python 实现（`app/`, `stages/`, `modules/`, `shared/`, `dev/`）已归档到 `归档/FNM_RE/`
- 原 Python 测试（`tests/unit/` 57 个 parity 测试）已归档到 `归档/tests/unit/`

## 架构概览

```
┌──────────────────────────────────────────────┐
│  FNM_RE/__init__.py      40 个 surface API   │  ← Python thin wrapper
│  (序列化/反序列化 JSON，调用 pyo3 binding)     │
├──────────────────────────────────────────────┤
│  fnm_re_rs/fnm-py/       pyo3 binding        │  ← Rust → Python 桥
├──────────────────────────────────────────────┤
│  fnm_re_rs/  10 crates, Rust 实现           │
│                                              │
│  fnm-orchestrator   pipeline 编排 (phase1-6) │
│  fnm-phase1         目录结构与页面分区        │
│  fnm-phase2         注释区域与条目识别        │
│  fnm-phase3         锚点检测与链接匹配        │
│  fnm-phase4         引用冻结与翻译单元        │
│  fnm-phase5         章节 Markdown 合并       │
│  fnm-phase6         导出审计                 │
│  fnm-core           共享基础设施 (正则/数据   │
│                     结构/版本/PDFium 渲染)    │
└──────────────────────────────────────────────┘
```

Pipeline 共 6 个 phase，严格串行：

```
OCR 页面 → Phase 1 (TOC/分区) → Phase 2 (注释捕获)
  → Phase 3 (锚点匹配) → Phase 4 (引用冻结)
  → Phase 5 (Markdown 合并) → Phase 6 (导出审计)
```

## 安装

```bash
# 安装 Rust pyo3 wheel
cd fnm_re_rs/fnm-py && maturin develop
```

依赖：Python 3.10+，Rust toolchain，SQLite。

## 快速上手

```bash
# 5 分钟 smoke test（Biopolitics 测试书）
.venv/bin/python scripts/smoke_post_m2.py --doc-id biopolitics-seed --skip-translate
# 期望：9/9 step 通过，退出码 0
```

```python
import FNM_RE

# 运行完整 pipeline
result = FNM_RE.run_doc_pipeline(doc_id="biopolitics-seed", db_path="data/fnm/fnm_books.db")
print(result["run_id"])

# 加载章节结构
structure = FNM_RE.load_doc_structure(doc_id="biopolitics-seed", db_path="data/fnm/fnm_books.db")
print(f"{len(structure['chapters'])} 章")

# 运行 LLM 修补（需要 OPENAI_API_KEY）
repair = FNM_RE.run_llm_repair(doc_id="biopolitics-seed", db_path="data/fnm/fnm_books.db")
print(f"建议数: {repair['suggestion_count']}")
```

## Surface API（40 个）

### Pipeline 入口（2）

| 函数 | 说明 |
|---|---|
| `run_doc_pipeline` | DB-driven 完整 pipeline（phase1→6）|
| `build_module_pipeline_snapshot_rust` | 纯内存版（不持久化），接收 pages/toc_items list |

### 结构加载（2）

| 函数 | 说明 |
|---|---|
| `load_doc_structure` | 读取章节、页面、注释结构 |
| `build_doc_status` | 文档当前状态摘要（各 phase 完成情况）|

### 导出（4）

| 函数 | 说明 |
|---|---|
| `build_export_bundle_for_doc` | 构建导出包（JSON）|
| `build_export_zip_for_doc` | 构建 Obsidian ZIP 包 |
| `audit_export_for_doc` | 导出质量审计（can_ship 判断）|
| `run_post_translate_export_checks_for_doc` | 翻译后导出检查 |

### 诊断（3）

| 函数 | 说明 |
|---|---|
| `list_diagnostic_entries_for_doc` | 全书诊断条目列表 |
| `get_diagnostic_entry_for_page` | 单页诊断条目 |
| `list_diagnostic_notes_for_doc` | 诊断注释列表 |

### 翻译辅助（4）

| 函数 | 说明 |
|---|---|
| `prepare_page_translate_jobs` | 准备页面翻译任务 |
| `build_retry_summary` | 重试摘要 |
| `build_unit_progress` | 翻译单元进度 |
| `run_llm_repair` | LLM 修补残余 orphan 链接 |

### 翻译单元工具（7）

| 函数 | 说明 |
|---|---|
| `build_fnm_body_unit_jobs` | 构建正文单元任务 |
| `apply_body_unit_translations` | 应用正文单元翻译 |
| `apply_body_unit_entry_result` | 应用单元条目结果 |
| `list_fnm_units_with_indices` | 列出带索引的单元 |
| `sync_fnm_retry_state` | 同步重试状态 |
| `rebuild_fnm_diagnostic_page_entries` | 重建诊断页码条目 |
| `collect_fnm_unit_failed_locations` | 收集失败位置 |

### 文本工具（5）

| 函数 | 说明 |
|---|---|
| `serialize_segments` | 序列化 segment 列表 |
| `deserialize_segments_to_dicts` | 反序列化 segment 字典 |
| `replace_frozen_refs` | 替换 frozen ref token |
| `format_fnm_unit_label` | 格式化单元标签 |
| `format_fnm_unit_pages` | 格式化单元页码 |

### 导出审计 helper（3）

| 函数 | 说明 |
|---|---|
| `body_paragraphs` | 提取正文段落 |
| `definition_lines` | 提取注释定义行 |
| `split_body_and_definitions` | 拆分正文与注释定义 |

### 注释覆盖工具（3）

| 函数 | 说明 |
|---|---|
| `group_review_overrides` | 按 scope 分组 review override |
| `annotate_review_note_links` | 给 note_links 注入 review 状态 |
| `collect_llm_suggestions` | 收集 LLM 建议 |

### 上标恢复（2）

| 函数 | 说明 |
|---|---|
| `has_explicit_sup` | 检测 markdown 中是否有明确上标 |
| `recover_book` | 全书上标恢复 |

### LLM 工具（4）

| 函数 | 说明 |
|---|---|
| `dump_traces` | 导出 LLM 调用 traces |
| `write_summary_traces` | 写入汇总 traces |
| `resolve_repair_model_args` | 解析修复用模型参数 |
| `render_repair_page_data_url` | 渲染 PDF 页为 data URL（供 LLM 视觉）|

### 版本（1）

| 函数 | 说明 |
|---|---|
| `fnm_re_rs_version` | 返回已安装的 fnm_re_rs Rust binding 版本 |

## 验证

```bash
# 检查 API 数量
.venv/bin/python -c "import FNM_RE; print(len(FNM_RE.__all__))"
# 期望输出：40

# 检查 Rust binding 安装
.venv/bin/python -c "import FNM_RE; print(FNM_RE.fnm_re_rs_version())"
# 期望输出：0.1.0

# 运行 fnm-py 测试
.venv/bin/python -m pytest fnm_re_rs/fnm-py/tests/ -q

# 运行 Rust 测试
cargo test --workspace --no-fail-fast
```

## 历史计划

| 阶段 | 计划文档 |
|---|---|
| M1 | `归档/FNM_RE/plans/M1_DETAILED_PLAN.md`（12 API port）|
| M2 | `归档/FNM_RE/plans/M2_DETAILED_PLAN.md`（21 helper + 11 caller）|
| M3 | `归档/FNM_RE/plans/M3_DETAILED_PLAN.md`（DB-driven + TOC bug）|
| M4 | `归档/FNM_RE/plans/M4_DETAILED_PLAN.md`（归档 Python 实现）|
| M5 | `M5_DETAILED_PLAN.md`（工程化补全：warnings/PDFium/LLM/pytest/cleanup）|

M5 完成后本文件归档到 `归档/FNM_RE/plans/`。

## 开发者指南

Rust 端开发说明见 `fnm_re_rs/README.md`。主要 crate：

- **fnm-core**：共享类型、正则、数据工具。新增任何跨越多个 phase 的功能应优先放这里。
- **fnm-phase1..6**：各 phase 实现，严格串行。修改上游 phase 后必须回归下游。
- **fnm-orchestrator**：pipeline 编排，不包含业务逻辑。
- **fnm-py**：pyo3 binding。新增 surface API 需在 `FNM_RE/__init__.py` 同步加 thin wrapper 和 `__all__` 条目。

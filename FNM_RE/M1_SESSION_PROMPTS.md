# M1 Session Prompts — 12 个独立 session 的 cold-start prompt

> 文档日期：2026-05-20
> 用法：按 M1.1 → M1.12 顺序，每个 prompt 单独开一个 AI session 执行。
> 前一个 session 完成报告 commit hash 后，再开下一个 session。
> 详细技术规范见 [`M1_DETAILED_PLAN.md`](./M1_DETAILED_PLAN.md)。

---

## § 0 用法

1. **拷贝**：每个 step 下的 ` ``` ` 代码块**全部内容**就是要给 AI 的 prompt
2. **不拼接**：每个 prompt 是自包含的（含项目背景 + 必读 + 任务 + 验收），不需要先发其他文档
3. **顺序**：必须按 M1.1 → M1.2 → ... → M1.12 顺序，**前一个完成后再开下一个**
4. **session 隔离**：每个 prompt 在新会话中执行；不要在同一会话连续做两个 step

---

## M1.1 — `load_doc_structure`

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.1。

## 项目背景

OCRandTranslation 项目（/Users/hao/OCRandTranslation/）正把 Python FNM_RE pipeline
全量迁移到 Rust。10 个 Rust crate 已完成核心 pipeline 1:1 翻译，本任务是 M1 阶段
（暴露 12 个旧 Python API 的 Rust 等价）的第 1 个 step。

## 必读文档（按顺序，先读后做）

1. /Users/hao/OCRandTranslation/CLAUDE.md（项目约束 13 条）
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"（12 条铁律）
3. /Users/hao/OCRandTranslation/FNM_RE/NEXT_PHASE_PLAN.md § 0-3（高层视图）
4. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 通用约定 + § 1 M1.1

## 任务

完成 M1_DETAILED_PLAN.md § 1 "M1.1 — load_doc_structure" 的 Action Checklist 全部 8 项：

- [ ] fnm-orchestrator/src/load.rs 新增 load_phase6_structure(repo, doc_id, include_diag)
- [ ] fnm-orchestrator/src/lib.rs re-export
- [ ] fnm-py/src/lib.rs 加 #[pyfunction] load_doc_structure_json
- [ ] fnm-py/src/lib.rs::fnm_re_rs(_py, m) 加 m.add_function
- [ ] FNM_RE/__init__.py::load_doc_structure 改 thin Rust wrapper
- [ ] fnm-py/tests/test_load_doc_structure.py：用 smoke_test seed 的 DB → 调用 → 断言 phase6.chapters 长度 = 12
- [ ] cargo test --workspace ≥940 / 0 failed
- [ ] commit

## 关键约束

- CLAUDE.md §1：全部用中文回复
- CLAUDE.md §2：写代码前先说明方案
- CLAUDE.md §4：不写兼容性代码
- AGENTS.md 铁律 §5：每个 pub fn 标 `←→ Python xxx()` doc comment
- AGENTS.md 铁律 §4：mod.rs / lib.rs < 400 行

## 完成判据（必须全部通过）

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs
cargo test --workspace --no-fail-fast 2>&1 | grep "^test result:" \
  | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 0

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
# 期望：🛠 Installed fnm-re-rs-0.1.0

cd /Users/hao/OCRandTranslation
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_load_doc_structure.py -q
# 期望：1 passed
```

## 报告格式

完成后报告：
- commit hash（git log -1 --oneline）
- workspace tests passed/failed 数字
- pytest 通过情况
- 遇到的踩坑及处理
- 超出 M1_DETAILED_PLAN.md § 1 范围的发现（如有）
```

---

## M1.2 — `audit_export_for_doc`

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.2。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1 已完成
load_doc_structure 的 pyo3 暴露，本任务是 M1.2 audit_export_for_doc。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/NEXT_PHASE_PLAN.md § 0-3
4. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 2 M1.2

## 任务

完成 M1_DETAILED_PLAN.md § 2 "M1.2 — audit_export_for_doc" 的 Action Checklist 全部 6 项：

- [ ] fnm-py/src/lib.rs 加 #[pyfunction] audit_export_for_doc_json
- [ ] 内部分支：zip_path 非空 → 调 audit_phase6_export(path)；zip_bytes 非空 → 用临时文件 wrap；都空 → DB 读 export_bundle 回退
- [ ] FNM_RE/__init__.py::audit_export_for_doc 改 thin Rust wrapper
- [ ] fnm-py/tests/test_audit_export.py：seed DB（复用 M1.1 fixture）→ 跑 audit → 断言 contract_ok=True
- [ ] cargo test --workspace 验证
- [ ] commit

## 关键约束

- CLAUDE.md §1 §2 §4
- AGENTS.md 铁律 §5（←→ Python doc comment）
- 注意 pyo3 `Option<&PyBytes>` 取 `as_bytes()`
- `audit_phase6_export(zip_path: &Path)` 不支持 bytes 直传，bytes 需 tempfile::NamedTempFile 写盘

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' \
  | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 0

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_audit_export.py -q
# 期望：1 passed
```

## 报告格式

完成后报告：commit hash / tests passed / pytest 状态 / 踩坑 / 额外发现。
```

---

## M1.3 — `build_export_bundle_for_doc`

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.3。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1 + M1.2 已完成。
本任务是 M1.3 build_export_bundle_for_doc，从 DB 读 fnm_export_bundle 表返回 dict。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 3 M1.3

## 任务

完成 M1_DETAILED_PLAN.md § 3 的 Action Checklist 全部 5 项：

- [ ] fnm-py/src/lib.rs 加 #[pyfunction] build_export_bundle_for_doc_json
- [ ] 内部：repo.list_fnm_export_bundle(doc_id) → serde_json::to_string
- [ ] FNM_RE/__init__.py::build_export_bundle_for_doc 改 wrapper
- [ ] fnm-py/tests/test_export_bundle.py：seed DB → 断言 chapters: 12
- [ ] cargo test --workspace + commit

## 关键约束

- CLAUDE.md §1 §2 §4
- bundle 不存在时 Python 旧版抛 MISSING_PERSISTED_EXPORT_BUNDLE_MESSAGE；Rust 端用 PyRuntimeError::new_err

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 0

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_export_bundle.py -q
# 期望：1 passed
```

## 报告格式

完成后报告：commit hash / tests passed / pytest 状态 / 踩坑 / 额外发现。
```

---

## M1.4 — `build_export_zip_for_doc`

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.4。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1-M1.3 已完成。
本任务是 M1.4 build_export_zip_for_doc，返回 export zip 的 bytes。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 4 M1.4

## 任务

完成 M1_DETAILED_PLAN.md § 4 的 Action Checklist 全部 5 项：

- [ ] check fnm_export_bundle.zip_bytes 列是否存在；若无，需 migration 加列
- [ ] fnm-py/src/lib.rs 加 #[pyfunction] build_export_zip_for_doc_json 返回 Py<PyBytes>
- [ ] FNM_RE/__init__.py::build_export_zip_for_doc 改 wrapper
- [ ] fnm-py/tests/test_export_zip.py：seed DB → bytes 解压成功 + 含 README.md
- [ ] cargo test --workspace + commit

## 关键约束

- CLAUDE.md §1 §2 §4
- pyo3 返回 Py<PyBytes> 需 PyBytes::new_bound(py, bytes) 显式拷贝
- 若 zip_bytes 列缺失，回退到 fnm_phase6::build_module_export_bundle 重新生成 zip

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 0

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_export_zip.py -q
# 期望：1 passed
```

## 报告格式

完成后报告：commit hash / tests passed / pytest 状态 / 是否做 schema migration / 踩坑 / 额外发现。
```

---

## M1.5 — `list_diagnostic_entries_for_doc`

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.5。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1-M1.4 已完成。
本任务是 M1.5 list_diagnostic_entries_for_doc，从 DB 读 fnm_diagnostic_pages 返回 list[dict]。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 5 M1.5

## 任务

完成 M1_DETAILED_PLAN.md § 5 的 Action Checklist 全部 5 项：

- [ ] fnm-py/src/lib.rs 加 #[pyfunction] list_diagnostic_entries_for_doc_json（接 visible_bps: Option<Vec<i64>>）
- [ ] 内部：repo.list_fnm_diagnostic_pages → 按 visible_bps filter → serde
- [ ] FNM_RE/__init__.py::list_diagnostic_entries_for_doc 改 wrapper
- [ ] fnm-py/tests/test_diagnostic_entries.py：seed → 返回 list，长度 ≥0
- [ ] cargo test --workspace + commit

## 关键约束

- CLAUDE.md §1 §2 §4
- 旧 Python 版接受 pages kwarg 用于内存路径；Rust 版可忽略（仅 DB 模式）

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 0

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_diagnostic_entries.py -q
# 期望：1 passed
```

## 报告格式

完成后报告：commit hash / tests passed / pytest 状态 / 踩坑 / 额外发现。
```

---

## M1.6 — `list_diagnostic_notes_for_doc`

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.6。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1-M1.5 已完成。
本任务是 M1.6 list_diagnostic_notes_for_doc，从 DB 读 fnm_diagnostic_notes 返回 list[dict]。
M1.6 与 M1.5 平行，规模更小。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 6 M1.6

## 任务

完成 M1_DETAILED_PLAN.md § 6 的 Action Checklist 全部 4 项：

- [ ] fnm-py/src/lib.rs 加 #[pyfunction] list_diagnostic_notes_for_doc_json
- [ ] FNM_RE/__init__.py::list_diagnostic_notes_for_doc 改 wrapper
- [ ] fnm-py/tests/test_diagnostic_notes.py：seed → 返回 list，长度 ≥0
- [ ] cargo test --workspace + commit

## 关键约束

- CLAUDE.md §1 §2 §4

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 0

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_diagnostic_notes.py -q
# 期望：1 passed
```

## 报告格式

完成后报告：commit hash / tests passed / pytest 状态 / 踩坑 / 额外发现。
```

---

## M1.7 — `get_diagnostic_entry_for_page`

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.7。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1-M1.6 已完成。
本任务是 M1.7 get_diagnostic_entry_for_page，复用 M1.5 的 repo 方法 + page_no filter。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 7 M1.7

## 任务

完成 M1_DETAILED_PLAN.md § 7 的 Action Checklist 全部 3 项：

- [ ] fnm-py/src/lib.rs 加 #[pyfunction] get_diagnostic_entry_for_page_json(db_path, doc_id, bp, allow_fallback=true)
- [ ] 内部复用 M1.5 已有 repo 方法，filter page_no == bp；找不到 + allow_fallback=true → 返回 "null"
- [ ] FNM_RE/__init__.py::get_diagnostic_entry_for_page 改 wrapper
- [ ] fnm-py/tests/test_get_diagnostic_entry.py：seed → 已知 bp 返回 dict / 未知 bp 返回 None
- [ ] cargo test --workspace + commit

## 关键约束

- CLAUDE.md §1 §2 §4

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 0

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_get_diagnostic_entry.py -q
# 期望：1 passed
```

## 报告格式

完成后报告：commit hash / tests passed / pytest 状态 / 踩坑 / 额外发现。
```

---

## M1.8 — `run_doc_pipeline`

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.8。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1-M1.7 已完成。
本任务是 M1.8 run_doc_pipeline——Python 旧 API 的核心入口，从 DB 读 pages + toc 后跑 pipeline。

工作量大于平均（预计 2 commits / +200 LoC / 2 tests）。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/NEXT_PHASE_PLAN.md § 6 M3 章节
   （M3 是后续 step，但 M1.8 inline 实现的部分 M3 会重构出来）
4. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 8 M1.8

## 任务

完成 M1_DETAILED_PLAN.md § 8 的 Action Checklist 全部 8 项：

- [ ] check raw_pages 表 schema（看 persistence/sqlite_schema.py）
- [ ] fnm-py/src/lib.rs 加 fn load_raw_pages_inline(conn, doc_id) + load_toc_items_inline(conn, doc_id) helper
- [ ] 加 #[pyfunction] run_doc_pipeline_json(db_path, doc_id, max_body_chars, start_phase)
  组装 pages/toc/config → 调 fnm_orchestrator::run_pipeline_for_doc
- [ ] 写 fnm_run 表行（status=running → done/error）参考 FNM_RE/app/mainline.py:run_phase6_pipeline_for_doc
- [ ] FNM_RE/__init__.py::run_doc_pipeline 改 thin Rust wrapper
- [ ] fnm-py/tests/test_run_doc_pipeline.py：
  · seed empty DB + raw_pages
  · 跑 pipeline
  · 断言 phase6 chapters=12 / contract_ok=True
- [ ] cargo test --workspace
- [ ] commit（建议拆 2 个：1）load helpers; 2）pipeline entry + fnm_run）

## 关键约束

- CLAUDE.md §1 §2 §4
- progress_callback 暂不支持（Python callback 跨 FFI 复杂）；Python wrapper 接受但不传给 Rust
- start_phase != "toc" 暂不支持，传入时报 error；M3 完成后再补
- fnm_run 表写入需要 create_fnm_run / update_fnm_run repo 方法（可能需新增到 Repository trait）

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 0

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_run_doc_pipeline.py -q
# 期望：1 passed（端到端 ~3 秒）
```

## 报告格式

完成后报告：
- 2 个 commit hash
- tests passed/failed 数字
- pytest 通过情况 + 端到端运行耗时
- 是否新增了 Repository trait 方法（create_fnm_run / update_fnm_run）
- 踩坑（重点：raw_pages schema / fnm_run 状态机）
- 额外发现
```

---

## M1.9 — `run_llm_repair`（独立入口）

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.9。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1-M1.8 已完成。
本任务是 M1.9 run_llm_repair——把 fnm_orchestrator 中嵌入式 LLM repair 抽出为独立 pyo3 函数。

fnm_orchestrator::mainline::run_llm_repair_sync 已实现（嵌入 pipeline），本 step 抽独立 API。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 9 M1.9

参考实现：
- fnm_re_rs/fnm-orchestrator/src/mainline.rs::run_llm_repair_sync
- fnm_re_rs/fnm-py/src/lib.rs::PyRepairRenderer
- fnm_re_rs/fnm-py/src/lib.rs::run_pipeline_for_doc_with_llm_repair_json（参考调用方式）

## 任务

完成 M1_DETAILED_PLAN.md § 9 的 Action Checklist 全部 7 项：

- [ ] fnm-py/src/lib.rs 加 #[pyfunction] run_llm_repair_json
  签名：(db_path, doc_id, pdf_path, renderer=None, slug="",
        auto_apply=true, confidence_threshold=0.9, cluster_limit=None) -> str
- [ ] 内部用 tokio current_thread runtime block_on async run_llm_repair
- [ ] 复用现有 PyRepairRenderer 包装 Python callable
- [ ] FNM_RE/__init__.py::run_llm_repair 改 thin Rust wrapper
- [ ] fnm-py/tests/test_run_llm_repair.py：
  · seed DB（已 phase1-3，用 smoke_test fixture）+ NoopRenderer
  · 调用 run_llm_repair_json
  · 断言返回 dict 含 cluster_count / suggestion_count / auto_applied_count
- [ ] cargo test --workspace
- [ ] commit

## 关键约束

- CLAUDE.md §1 §2 §4
- LlmRepairReport 字段众多（cluster_count / suggestion_count / auto_applied / usage_summary / 等）需全 serde
- 现成代码可参考 fnm_orchestrator::mainline::run_llm_repair_sync——直接抽出独立函数

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 0

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_run_llm_repair.py -q
# 期望：1 passed
```

## 报告格式

完成后报告：commit hash / tests passed / pytest 状态 / NoopRenderer cluster_count / 踩坑 / 额外发现。
```

---

## M1.10 — `build_doc_status`（拆 3 个 commit）

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.10。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1-M1.9 已完成。
本任务是 M1.10 build_doc_status——port FNM_RE/app/status.py（748 行）到 fnm-orchestrator。

工作量较大：预计 3 commits / +500-700 LoC / 3-5 tests。请严格按 3 个 commit 拆分。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 10 M1.10
4. /Users/hao/OCRandTranslation/FNM_RE/app/status.py（Python 原版，要 1:1 port）

## 任务

完成 M1_DETAILED_PLAN.md § 10 的 Action Checklist，按 3 个 commit 拆分：

### Commit 10a：port status.py 核心 helper 到 fnm-orchestrator

- [ ] 新文件 fnm_re_rs/fnm-orchestrator/src/status.rs
- [ ] port build_phase4_status(phase4_structure) -> serde_json::Value
- [ ] port build_phase6_status(phase6_structure) -> serde_json::Value
- [ ] port classify_phase_state / resolve_blockers / 等 helper
- [ ] 单测覆盖各 gate 字段
- [ ] cargo test -p fnm-orchestrator 通过
- [ ] commit 10a

### Commit 10b：Repository 加 get_latest_fnm_run

- [ ] fnm-core/src/db/repository.rs 加 trait method get_latest_fnm_run(doc_id) -> Result<Option<Value>>
- [ ] SqliteRepository 实现（SELECT FROM fnm_run WHERE doc_id ORDER BY id DESC LIMIT 1）
- [ ] 单测
- [ ] commit 10b

### Commit 10c：pyo3 暴露 + Python wrapper

- [ ] fnm-orchestrator::build_doc_status(repo, doc_id, start_phase) -> StructureStatusRecord
- [ ] fnm-py/src/lib.rs 加 #[pyfunction] build_doc_status_json
- [ ] FNM_RE/__init__.py::build_doc_status 改 wrapper
- [ ] fnm-py/tests/test_build_doc_status.py：seed → 断言含 8 个关键字段
- [ ] cargo test --workspace
- [ ] commit 10c

## 关键约束

- CLAUDE.md §1 §2 §4
- gate 字段命名必须与 Python 完全一致（caller 在 web/ 读特定字段，详见 FNM_RE/app/status.py）
- _resolve_phase4_blockers 可能涉及枚举值映射，需 byte-equal Python golden
- 每个 commit 独立可编译可测试

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 + 新 status 测试 / 0 failed

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_build_doc_status.py -q
# 期望：1 passed
```

## 报告格式

完成后报告：
- 3 个 commit hash
- 各 commit 引入的 LoC
- tests passed/failed 数字
- 与 Python golden 的 gate 字段对比结果
- 踩坑（重点：枚举映射 / Python 隐式行为）
- 额外发现
```

---

## M1.11 — `prepare_page_translate_jobs` + `build_retry_summary` + `build_unit_progress`（拆 3 个 commit）

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.11。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1-M1.10 已完成。
本任务是 M1.11——port FNM_RE/app/page_translate.py（880 行）的 3 个公开函数。

工作量较大：预计 3 commits / +600-900 LoC / 3 tests。请按顺序：先 build_unit_progress（最简），
再 build_retry_summary，最后 prepare_page_translate_jobs（最复杂）。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 11 M1.11
4. /Users/hao/OCRandTranslation/FNM_RE/app/page_translate.py（Python 原版）

## 任务

按 3 个 commit 拆分：

### Commit 11a：build_unit_progress（最简，先做）

- [ ] 新文件 fnm_re_rs/fnm-orchestrator/src/page_translate.rs
- [ ] port build_unit_progress(repo, doc_id, use_lightweight) -> serde_json::Value
- [ ] 内部读 fnm_translation_units 统计 done/error/total/pending
- [ ] 单测
- [ ] fnm-py/src/lib.rs 加 build_unit_progress_json
- [ ] FNM_RE/__init__.py::build_unit_progress 改 wrapper
- [ ] pytest test_build_unit_progress.py
- [ ] commit 11a

### Commit 11b：build_retry_summary

- [ ] fnm-orchestrator::page_translate::build_retry_summary(repo, doc_id) -> serde_json::Value
- [ ] 读 fnm_run.validation_json + filter retry-able units
- [ ] 单测 + pyo3 + wrapper + pytest test_build_retry_summary.py
- [ ] commit 11b

### Commit 11c：prepare_page_translate_jobs（最复杂）

- [ ] fnm-orchestrator::page_translate::prepare_page_translate_jobs(pages, target_bp, t_args, doc_id, repo) -> (job, jobs, meta)
- [ ] **复杂度警告**：涉及 page → translation_unit 映射 + retry 状态合并
- [ ] 单测 + pyo3 + wrapper + pytest test_prepare_page_translate_jobs.py
- [ ] commit 11c

## 关键约束

- CLAUDE.md §1 §2 §4
- prepare_page_translate_jobs 返回 tuple，pyo3 端需返回 JSON 数组 [job, jobs, meta]，Python wrapper 端 unpack
- t_args: dict 内含 model_args 等业务字段，Rust 端透传不解析
- 每个 commit 独立可编译可测试

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 + 新 page_translate 测试 / 0 failed

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_build_unit_progress.py \
                                              fnm_re_rs/fnm-py/tests/test_build_retry_summary.py \
                                              fnm_re_rs/fnm-py/tests/test_prepare_page_translate_jobs.py -q
# 期望：3 passed
```

## 报告格式

完成后报告：
- 3 个 commit hash
- 各 commit 引入的 LoC
- tests passed/failed 数字
- prepare_page_translate_jobs 返回 tuple 的 unpack 方式
- 踩坑（重点：page → unit 映射 / retry 状态合并 / t_args 透传）
- 额外发现
```

---

## M1.12 — `run_post_translate_export_checks_for_doc`

```
你是一个独立的 Rust + Python 工程师 session，本次任务是 FNM_RE Rust 化项目的 M1.12（M1 最后一个 step）。

## 项目背景

OCRandTranslation 项目正把 Python FNM_RE pipeline 全量迁移到 Rust。M1.1-M1.11 已完成。
本任务是 M1.12 run_post_translate_export_checks_for_doc——翻译后 export 检查 + 自修复循环。

复用 M1.1 / M1.2 / M1.4 已实现的函数（load_doc_structure / audit_export / build_export_zip）。

## 必读文档（按顺序）

1. /Users/hao/OCRandTranslation/CLAUDE.md
2. /Users/hao/OCRandTranslation/AGENTS.md § "Rust 重构代码规范"
3. /Users/hao/OCRandTranslation/FNM_RE/M1_DETAILED_PLAN.md § 0 + § 12 M1.12
4. /Users/hao/OCRandTranslation/FNM_RE/app/mainline.py::run_post_translate_export_checks_for_doc
   （Python 原版，要 port 循环逻辑）

## 任务

完成 M1_DETAILED_PLAN.md § 12 的 Action Checklist 全部 7 项：

- [ ] fnm-orchestrator/src/post_translate.rs 新增 run_post_translate_export_checks(repo, doc_id, max_repair_rounds)
- [ ] 内部循环：load_phase6_structure → build_export_zip → audit_phase6_export → if issue → repair → max_rounds
- [ ] 复用 M1.1 load_phase6_structure
- [ ] 复用 M1.2 audit_phase6_export
- [ ] 复用 M1.4 build_export_zip
- [ ] pyo3 暴露 + Python wrapper
- [ ] fnm-py/tests/test_post_translate_export_checks.py（用已 export 的 fixture，max_repair_rounds=0 应直接通过）
- [ ] cargo test --workspace
- [ ] commit

## 关键约束

- CLAUDE.md §1 §2 §4
- max_repair_rounds=0 时不应触发 repair 循环，直接返回当前状态

## 完成判据

```bash
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast \
  2>&1 | grep "^test result:" | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 + 新 post_translate 测试 / 0 failed

cd fnm_re_rs/fnm-py && /Users/hao/OCRandTranslation/.venv/bin/maturin develop
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/test_post_translate_export_checks.py -q
# 期望：1 passed

# M1 整体验收（最后一个 step 完成后）
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/ -q
# 期望：≥12 passed（M1.1-M1.12 各 1 个测试，M1.10/11 共 5 个）
```

## 报告格式

完成后报告：
- commit hash
- tests passed/failed 数字
- M1 总验收：fnm-py/tests/ 全部 pytest 通过数
- 是否需要进入 NEXT_PHASE_PLAN.md § 5 M2 阶段
- 踩坑 / 额外发现
```

---

## § 13 M1 完成后续步骤

M1.12 报告完后，M1 全部完成。下一步是 M2 阶段（caller 切换 + e2e smoke）。

进入 M2 之前建议运行：

```bash
# 1. workspace 总测试
cd /Users/hao/OCRandTranslation/fnm_re_rs && cargo test --workspace --no-fail-fast

# 2. pytest 全套
/Users/hao/OCRandTranslation/.venv/bin/pytest fnm_re_rs/fnm-py/tests/ -v

# 3. Biopolitics e2e 真实跑（手动验证）
/Users/hao/OCRandTranslation/.venv/bin/python fnm_re_rs/fnm-py/smoke_test.py

# 4. 旧公开 API 全替换确认
grep -n "from FNM_RE.app\|from FNM_RE.modules\|from FNM_RE.stages\|from FNM_RE.shared" FNM_RE/__init__.py
# 期望：仅 thin wrapper 内部（lazy import）；理想为 0 行
```

M2 prompts 单独维护在 `M2_SESSION_PROMPTS.md`（待 M1 完成后写）。

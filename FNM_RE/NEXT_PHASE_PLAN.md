# FNM_RE 完全 Rust 化 · 收尾计划

> 文档日期：2026-05-20
> 前置完成：21 个 commit（fnm-core/phase1-6/llm-repair/orchestrator/py 10 个 crate + FNM_RE/__init__.py 加 Rust 入口 + Biopolitics e2e 跑通 2.844s）
> 上一份计划：[`docs/FNM_PHASE5_PHASE6_PLAN.md`](../归档/FNM_RE/docs/FNM_PHASE5_PHASE6_PLAN.md)（已完成归档）

---

## 0. 项目背景（30 秒）

`fnm_re_rs/` 10 个 Rust crate 已完成 FNM_RE 核心 pipeline 1:1 翻译；
Python 端 `FNM_RE/__init__.py` 通过 pyo3 wheel `fnm-re-rs` 已能调用 Rust pipeline。

**遗留事实**：`FNM_RE/app/` 6535 行 Python 仍是生产路径——`web/translation/scripts` 共 17 个文件
通过 12 个旧公开 API（`run_doc_pipeline` / `run_llm_repair` / `build_doc_status` / ...）
调用 Python `app/`，进而调用 `modules/` / `stages/` / `shared/`。

**本计划目标**：在 fnm-py pyo3 端暴露这 12 个 API 的 Rust 等价 → 切换 17 个 caller → 归档 `app/` + 残余 Python pipeline 实现 → 让 FNM_RE 真正只剩 `__init__.py` + `dev/` + `README.md` 的薄壳。

---

## 1. 任务量单位约定（AI 友好）

每个 Step 标注以下指标，便于 AI 一次会话中判断范围：

| 字段 | 含义 | 典型量级 |
|---|---|---|
| `commits` | 预期 git commit 数 | 1-3 |
| `files` | 修改/新增文件数 | 1-10 |
| `LoC` | 大约代码行数（净新增） | 20-500 |
| `tests` | 新增测试用例数 | 0-3 |
| `verify` | 验收条件（命令 + 期望输出） | 1-2 行 |

**不使用"天"作单位**——AI 不感知人类作息，按 step 完成度推进。

---

## 2. 当前状态总览

### 2.1 Rust 端（10 crate · 940 tests）

| crate | tests | 用途 |
|---|---:|---|
| fnm-core | 110 | 类型 / DB / 工具 |
| fnm-phase1 | 106 | TOC + chapter skeleton（chapter_boundary 12/12 byte-equal）|
| fnm-phase2 | 140 | note_regions + note_items + sup_recovery |
| fnm-phase3 | 26 | body_anchors + note_links（5 cascade tests ignored）|
| fnm-phase4 | 106 | ref_freeze + units + reviews |
| fnm-phase5 | 44 | chapter markdown merge |
| fnm-phase6 | 148 | export + audit + book_assemble |
| fnm-llm-repair | 121+39 | Step 3.5 LLM 修补 |
| fnm-orchestrator | 0 | pipeline 编排 + DB-driven + LLM repair 集成 |
| fnm-py | 0 | pyo3 binding（4 个 Python 函数）|

### 2.2 Python 端剩余

`FNM_RE/` 仍含约 **19,500 行 Python**（除 `__init__.py` / `README.md` / `dev/` 外全部待归档）。

`fnm-py` 当前公开 4 个函数：
- `run_pipeline_json` / `run_pipeline_for_doc_json` / `run_pipeline_for_doc_with_llm_repair_json` / `version`

待补完 12 个 Python 旧公开 API 的 Rust 等价，覆盖 `web/translation/scripts` 17 个 caller。

---

## 3. 大阶段总览

| 阶段 | 主目标 | step 数 | 总 commits | 状态 |
|---|---|---:|---:|---|
| **M1** | fnm-py 暴露 12 个旧公开 API 的 Rust 等价 | 12 | 12-15 | ✅ 完成 |
| **M2** | 21 个 helper 补 Rust 暴露 + 11 caller 切换 | 13 | 8 | ✅ 完成 |
| **M3** | DB-driven 输入桥接 + TOC 优先级 bug 修复 | 5 | 1-2 | ✅ 完成 |
| **M4** | 归档 `FNM_RE/{app,stages,modules,shared,dev,constants,models}` + tests/tools | 6 | 6-8 | 待做 |
| **M5** | 工程化补全（Rust 质量 + 测试 + 环境集成 + 文档） | 7 | 7-15 | 待做 |

**P0 总计 (M1-M5)**：43 step / ~40 commit

注：原"M5 fnm-py wheel CI 发布"已取消（暂不正式发布）；原 P1/P2 旁支问题归入新 M5。

---

## 4. M1 — fnm-py 暴露 12 个旧公开 API

### 目标
让 `FNM_RE/__init__.py` 里 12 个 lazy-import 函数走 Rust 实现，外部 caller import 路径不变。

### 完成判据
- `fnm-py` 新增 12 个 `#[pyfunction]`
- `FNM_RE/__init__.py` 12 个旧函数改为 thin wrapper 调 Rust
- `pytest fnm_re_rs/fnm-py/tests/` 全过
- workspace 940 tests + 新增 12 个 pytest 用例 0 failed

### Step 列表

#### Step M1.1 — `load_doc_structure`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 3 (`fnm-py/src/lib.rs`, `FNM_RE/__init__.py`, `fnm-py/tests/test_load_doc_structure.py`) |
| LoC | +80 |
| tests | 1 |
| verify | `pytest fnm_re_rs/fnm-py/tests/test_load_doc_structure.py -q` 1 passed |

**实现要点**：
- Rust 侧：`fn load_doc_structure_json(db_path: &str, doc_id: &str) -> PyResult<String>`
  内部从 `Repository` 读 phase1-6 表，拼成 `Phase6Structure` JSON
- Python 侧：`def load_doc_structure(doc_id, db_path=None, **kw)` 调上述函数后 `json.loads`

#### Step M1.2 — `audit_export_for_doc`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 3 |
| LoC | +60 |
| tests | 1 |
| verify | `pytest .../test_audit_export.py` + Biopolitics 已 export 的 DB 跑通 |

**实现要点**：
- 复用 `fnm_phase6::export_audit::audit_phase6_export(zip_path)`
- DB 读 export_bundle → 临时写 zip → 调 audit → 返回 `ExportAuditReportRecord` JSON

#### Step M1.3 — `build_export_bundle_for_doc`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 3 |
| LoC | +60 |
| tests | 1 |
| verify | 返回 dict 含 chapters / chapter_files / contract_ok 字段 |

#### Step M1.4 — `build_export_zip_for_doc`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 3 |
| LoC | +50 |
| tests | 1 |
| verify | 返回 `bytes`（zip 二进制）+ 写入本地能解压 |

#### Step M1.5 — `list_diagnostic_entries_for_doc`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 3 |
| LoC | +40 |
| tests | 1 |
| verify | DB 读 `fnm_diagnostic_pages` → 返回 list[dict] |

#### Step M1.6 — `list_diagnostic_notes_for_doc`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 3 |
| LoC | +40 |
| tests | 1 |
| verify | DB 读 `fnm_diagnostic_notes` |

#### Step M1.7 — `get_diagnostic_entry_for_page`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 3 |
| LoC | +30 |
| tests | 1 |
| verify | M1.5 + page_no filter |

#### Step M1.8 — `run_doc_pipeline`

| 字段 | 值 |
|---|---|
| commits | 1-2 |
| files | 3-4 |
| LoC | +120 |
| tests | 2 (in-memory + DB-driven) |
| verify | Biopolitics 跑通，phase6 chapters=12 contract_ok=True |

**实现要点**：
- 已有 `fnm_orchestrator::run_pipeline_for_doc`
- 增加从 DB 读 pages + toc_items 的 helper
- pyo3 暴露 `run_doc_pipeline_json(db_path, doc_id, pdf_path)`

#### Step M1.9 — `run_llm_repair`（独立入口）

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 3 |
| LoC | +80 |
| tests | 1 (NoopRenderer) |
| verify | 不嵌入 pipeline 单独调用 LLM repair，返回 LlmRepairReport JSON |

**实现要点**：
- 已有 `fnm_llm_repair::run::run_llm_repair`
- 复用 `PyRepairRenderer`
- pyo3 暴露 `run_llm_repair_json(db_path, doc_id, pdf_path, renderer, ...)`

#### Step M1.10 — `build_doc_status`

| 字段 | 值 |
|---|---|
| commits | 2-3 |
| files | 5-8 |
| LoC | +500-700 |
| tests | 2 |
| verify | 返回 `StructureStatusRecord` 等价 dict（含 phase4/6 各 8 个 gate 字段） |

**实现要点**：
- 需 port `FNM_RE/app/status.py` 的 build_phase4_status / build_phase6_status
- 在 fnm-orchestrator 加 `pub fn build_doc_status(repo, doc_id) -> StructureStatusRecord`
- pyo3 暴露 thin wrapper

**为什么大**：status.py 748 行，含多个 gate 计算 + Python ↔ Rust 字段映射。

#### Step M1.11 — `prepare_page_translate_jobs` + `build_retry_summary` + `build_unit_progress`

| 字段 | 值 |
|---|---|
| commits | 3 |
| files | 6-9 |
| LoC | +600-900 |
| tests | 3 |
| verify | translation/translate_worker_fnm.py 调用栈跑通（不实际翻译） |

**实现要点**：
- 三个函数都来自 `FNM_RE/app/page_translate.py` (880 行)
- 顺序 port：先 build_unit_progress（最简）→ build_retry_summary → prepare_page_translate_jobs
- 在 fnm-orchestrator 加 page_translate 子模块

#### Step M1.12 — `run_post_translate_export_checks_for_doc`

| 字段 | 值 |
|---|---|
| commits | 1-2 |
| files | 4-6 |
| LoC | +200-300 |
| tests | 1 |
| verify | 翻译完整本书后跑 export 检查通过 |

---

## 5. M2 — caller 切换（mechanical）

### 目标
17 个外部文件改 import 路径（M1 完成后 `FNM_RE.xxx` 已经 thin wrapper Rust，多数 caller 不需改）。

### 完成判据
- `grep -r "from FNM_RE.app\|from FNM_RE.stages\|from FNM_RE.modules\|from FNM_RE.shared" --include="*.py" .` 返回 0 行（除归档/、tests/）
- 6 个 web 路由 smoke 通过

### Step 列表

#### Step M2.1 — `web/` 6 文件 import 更新

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 6 (reading_routes / export_routes / translation_routes / dev_routes / services / reading_view) |
| LoC | ±50 |
| tests | 0（依赖 M2.5 e2e） |
| verify | `python -c "import web.reading_routes"` 等 6 个无 ImportError |

#### Step M2.2 — `translation/` 4 文件 import 更新

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 4 (service / translate_runtime / translate_worker_common / translate_worker_fnm) |
| LoC | ±30 |
| tests | 0 |
| verify | `python -c "import translation.service"` 等 4 个无 ImportError |

#### Step M2.3 — `scripts/` 7-8 文件 import 更新

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 7-8 |
| LoC | ±40 |
| tests | 0 |
| verify | `python scripts/test_fnm_real_batch.py --help` 退出码 0 |

#### Step M2.4 — `pipeline/document_tasks.py` import 更新

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 1 |
| LoC | ±10 |
| tests | 0 |
| verify | `python -c "import pipeline.document_tasks"` 无 ImportError |

#### Step M2.5 — e2e smoke（web + scripts）

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 1（`scripts/smoke_post_m2.py`） |
| LoC | +100 |
| tests | 1 |
| verify | 启动 web → 上传 Biopolitics PDF → pipeline → export ZIP 端到端 |

---

## 6. M3 — DB-driven 输入桥接

### 目标
让 fnm-orchestrator 直接从 SQLite `documents` / `raw_pages` / `visual_toc.manual_inputs` 读取输入，caller 只需 `doc_id`。

### 完成判据
- 新 API：`fnm_orchestrator::mainline::run_pipeline_from_db(repo, doc_id) -> Result<ModulePipelineSnapshot>`
- fnm-py 暴露 `run_pipeline_from_db_json(db_path, doc_id) -> str`

### Step 列表

#### Step M3.1 — `repo.load_raw_pages_for_doc`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 2 (`fnm-core/src/db/repository.rs` + `fnm-core/migrations/`) |
| LoC | +100 |
| tests | 1 |
| verify | 单测：写 5 个 raw_pages → 读 → 字段一致 |

#### Step M3.2 — `repo.load_toc_items_for_doc`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 2 |
| LoC | +80 |
| tests | 1 |
| verify | 从 visual_toc.manual_inputs 表读 TOC items |

#### Step M3.3 — `fnm_orchestrator::mainline::run_pipeline_from_db`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 2 (`fnm-orchestrator/src/mainline.rs` + `lib.rs`) |
| LoC | +60 |
| tests | 1 |
| verify | 单测：mock repo 跑 phase1-6 通过 |

#### Step M3.4 — fnm-py 暴露 `run_pipeline_from_db_json`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 2 (`fnm-py/src/lib.rs` + `FNM_RE/__init__.py`) |
| LoC | +50 |
| tests | 1 |
| verify | `fnm_re_rs.run_pipeline_from_db_json("test.db", "biopolitics-smoke")` 跑通 |

---

## 7. M4 — 归档剩余 Python 实现

### 目标
`FNM_RE/` 仅剩 `__init__.py` + `README.md` + `dev/` + 本计划文档（也归档）。

### 完成判据
- `ls FNM_RE/` 输出 ≤ 5 个条目
- `grep -r "from FNM_RE\.\(app\|stages\|modules\|shared\)" --include="*.py" . | grep -v 归档` 返回 0 行
- `grep -r "from FNM_RE.constants\|from FNM_RE.models" --include="*.py" . | grep -v 归档` 返回 0 行
- workspace 940 tests + 新增 pyo3 tests 全过

### Step 列表

#### Step M4.1 — 归档 `FNM_RE/{constants.py,models.py}`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | git mv 2 个 |
| LoC | 0（rename） |
| tests | 0 |
| verify | `find FNM_RE -name "constants.py" -o -name "models.py"` 返回空 |

#### Step M4.2 — 归档 `FNM_RE/{stages,modules,shared}/`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | git mv ~70 个 |
| LoC | 0（rename） |
| tests | 0 |
| verify | `ls FNM_RE/stages FNM_RE/modules FNM_RE/shared` 全部 No such file |

#### Step M4.3 — 归档 `FNM_RE/app/`

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | git mv 9 个 |
| LoC | 0（rename） |
| tests | 0 |
| verify | `ls FNM_RE/app` No such file |

#### Step M4.4 — `FNM_RE/__init__.py` 清理 + 重写 README + 归档本计划

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 3 (`__init__.py` / `README.md` / git mv `NEXT_PHASE_PLAN.md`) |
| LoC | -200（删旧 lazy-import），+50（新 README） |
| tests | 0 |
| verify | `ls FNM_RE/` 输出 `__init__.py README.md dev/`（+ `__pycache__/`） |

---

## 8. M5 — 工程化补全（原 P1 + P2 合并，7 step 平铺）

### 目标

收尾 Rust 代码质量、补足测试工程化、完善文档。M1-M4 已完成核心 Rust 化和归档，M5 处理"旁支但有价值"的工作。

### 完成判据

- `cargo build --workspace 2>&1 | grep -c warning` 输出 0
- `cargo test --workspace --no-fail-fast` 0 ignored / 0 failed（M5.2 完成后）
- `pytest fnm_re_rs/fnm-py/tests/` ≥80 passed（M5.5 完成后）
- 用户面向 README 通过 review

### Step 列表

#### Step M5.1 — Rust workspace 清 warnings

合并原 P1.1.1-3 三个子任务（phase1 6 + phase2 20 + phase4 11 = 37 warnings）。

| 字段 | 值 |
|---|---|
| commits | 1-3（按 crate 拆 commit）|
| files | 15-22（3 crate）|
| LoC | ±200 |
| tests | 0 |
| verify | `cargo build --workspace 2>&1 \| grep -c "^warning:"` 输出 ≤5（当前 41）|

主要工作：
- `cargo fix --workspace --allow-dirty` 自动修
- 手动处理 `dead_code` / `unused_variables` / `useless_assignment` 等需判断的
- 真正不该修的（如 trait method 占位）加 `#[allow(...)]` 注解

#### Step M5.2 — phase3 5 个 cascade ignored tests 修复

| 字段 | 值 |
|---|---|
| commits | 3-5（每个 test 1-2 commit）|
| files | 5-10 |
| LoC | +200-500 |
| tests | 解 ignore + 补单测 |
| verify | `cargo test --workspace --no-fail-fast -- --ignored` 5 个新通过 |

涉及测试（详见 [`fnm-phase3/tests/known_python_bugs.md`](../fnm_re_rs/fnm-phase3/tests/known_python_bugs.md) §7）：
1. `biopolitics_phase3_body_anchors_parity`
2. `biopolitics_phase3_chapter_contracts_parity`
3. `biopolitics_phase3_note_links_parity`
4. `biopolitics_phase3_summary_parity`
5. 第 5 个见 known_python_bugs.md

每个测试是 `#[ignore]` 标记，解 ignore 前先验证根因（通常是 cascade 数据依赖）。

#### Step M5.3 — PDFium binary 集成

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 2 (`fnm-core/Cargo.toml` + `.github/workflows/rust.yml`) |
| LoC | +30 |
| tests | 0（解 ignore）|
| verify | `cargo test -p fnm-phase1 chapter_skeleton::pdf_font` 通过 |

注：M5 不涉及 wheel 发布，CI workflow 调整仅为支持 PDFium-dependent 测试。

#### Step M5.4 — `llm_book_type_verify` e2e（需 API key）

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 1（`fnm_re_rs/fnm-phase2/tests/llm_book_type_verify_e2e.rs`）|
| LoC | ±20 |
| tests | 1 e2e |
| verify | 设 `OPENAI_API_KEY` 后 `real_book_type_verify` 通过；未设 env 时 skip |

#### Step M5.5 — fnm-py pytest e2e 完整套件

合并原 P2.1.1-3 三个子任务。

| 字段 | 值 |
|---|---|
| commits | 2-3 |
| files | 3 个新 pytest |
| LoC | +300-600 |
| tests | 8-15 用例 |
| verify | `pytest fnm_re_rs/fnm-py/tests/test_pipeline_e2e.py` 全过 |

文件列表：
- `fnm_re_rs/fnm-py/tests/test_pipeline_e2e.py`（Biopolitics 全 phase 端到端，含 audit）
- `fnm_re_rs/fnm-py/tests/test_llm_repair_pyo3.py`（NoopRenderer 验证）
- `fnm_re_rs/fnm-py/tests/test_shadow_mode.py`（`FNM_SHADOW_RUST_PHASES` env on/off）

#### Step M5.6 — Python ↔ Rust shadow diff 完整版

合并原 P2.2.1-3 三个子任务。**M4 后已无 Python pipeline，shadow diff 价值降低**，但保留作为历史 fixture 对照工具。

| 字段 | 值 |
|---|---|
| commits | 2-3 |
| files | 3-4 |
| LoC | +500-800 |
| tests | 5-10 |
| verify | `python scripts/shadow_diff.py --doc biopolitics` 报告无 diff |

子任务：
1. `dataclass_to_dict_recursive(obj)` helper（旧 Python dataclass → dict）—— 用 `归档/FNM_RE/` 内归档的 dataclass
2. `compare_python_vs_rust_snapshots(py_obj, rust_dict)` diff 函数
3. e2e diff 报告 + pytest

**风险**：M4 已归档 Python 实现，需从 `归档/FNM_RE/` 临时 import；若长期不需要 shadow diff，可降级为"延后或取消"。

#### Step M5.7 — 用户面向 README 重写

合并原 P2.3.1。

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 2 (`FNM_RE/README.md` + 根 `README.md`) |
| LoC | +150 |
| tests | 0 |
| verify | 文档 render 后链接全通；新用户按 README 能跑通 Biopolitics smoke |

内容：
- 项目背景（OCR + Rust pipeline）
- 快速上手（5 分钟跑 smoke）
- API 速查（37 个 FNM_RE surface API）
- 架构图（fnm_re_rs 8 个 crate + fnm-py + Python wrapper）
- 进阶（自定义 LLM 模型 / shadow mode / dev 工具说明）
- 历史计划（链接到 `归档/FNM_RE/plans/`）

---

## 9. 依赖图

```
M1 ✅ ─→ M2 ✅ ─→ M3 ✅ ─→ M4 ─→ (M5 可选)
                              ↓
                              M4 完成后 FNM_RE/ 只剩 thin wrapper

M5.1-M5.7 内部无强依赖，可任意顺序：
  M5.1 (warnings 清理) — 独立
  M5.2 (phase3 ignored) — 独立
  M5.3 (PDFium 集成)   — 独立
  M5.4 (LLM e2e)       — 独立
  M5.5 (pytest e2e)    — 建议 M4 后做（归档完毕后 e2e 范围清晰）
  M5.6 (shadow diff)   — 建议 M4 前做（M4 归档 Python 后 shadow 需从 归档/ import，复杂度增）
  M5.7 (README)        — 建议 M5 最后做（其他 step 完成后 README 内容确定）
```

---

## 10. 验收 checklist（P0 全完成后）

### M4 完成后

- [ ] `cargo test --workspace` ≥989 passed / 0 failed
- [ ] `pytest fnm_re_rs/fnm-py/tests/` ≥72 passed
- [ ] `FNM_RE/` 只剩 ≤5 个条目：`__init__.py` / `README.md` / `M4_DETAILED_PLAN.md` / `NEXT_PHASE_PLAN.md` / `__pycache__/`
- [ ] `grep -r "from FNM_RE.\(app\|stages\|modules\|shared\|dev\|constants\|models\)" --include="*.py" . | grep -v 归档/` 返回 0 行
- [ ] `len(FNM_RE.__all__) == 37`
- [ ] Biopolitics e2e 12/12 chapter byte-equal Python golden（用 `test_example/Biopolitics/golden/` fixture）
- [ ] web/translation/scripts/persistence caller 全部 import 通过
- [ ] `scripts/smoke_post_m2.py` 9/9 step 通过

### M5 完成后

- [ ] `cargo build --workspace 2>&1 | grep -c "^warning:"` 输出 0
- [ ] `cargo test --workspace --no-fail-fast` 0 ignored / 0 failed
- [ ] `cargo clippy --workspace -- -D warnings` 0 warning
- [ ] `pytest fnm_re_rs/fnm-py/tests/` ≥80 passed（M5.5 加 8+）
- [ ] 用户面向 README 完成且 link 全通

---

## 11. 风险与缓解（剩余 M4 + M5 风险）

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| M4.1 `tests/unit/` 内部交叉 import 漏归档导致 pytest collection 失败 | 中 | M4.1 卡 | 先跑 `pytest --collect-only` 验证；逐个 grep 内部 import |
| M4.2 `web/app_factory.py` 注册 dev_routes 时无 try/except，归档后 web 启动 fail | 中 | M4.2 卡 | M4.2 内先 read app_factory；如硬注册则需 commit 解除注册 |
| M4.4 业务 caller 残留 `from FNM_RE.app.` 未在 M2 切干净 | 极低 | M4.4 卡 | M2 验收已 grep 0 残留；M4 各 step 前再 grep 一遍 |
| M5.2 phase3 cascade ignored 涉及 phase2 数据 bug | 中 | M5.2 拖延 | 标 known issue 不阻断 M5；专项 phase2 audit |
| M5.6 shadow diff 在 M4 后需从 `归档/FNM_RE/` import Python，复杂度高 | 中 | M5.6 拖延或取消 | 建议 M5.6 提前到 M4 前；若 M4 已完成则评估是否取消 |
| 归档目录 `归档/` 已有同名文件 | 低 | git mv 失败 | M4 各 step 前 `ls 归档/` 检查 |
| pytest 配置未排除 `归档/`，归档后 collection 误扫 | 低 | 假绿/假红 | M4.1 内确认 `pyproject.toml` / `pytest.ini`；建议加 `--ignore=归档/` |

---

## 12. 下一步行动

**M3 已完成（含工作区 polish）；下一步推进 M4**：

按 M4.1 → M4.6 顺序执行，每个 step 一个独立 session。详细计划见 [`M4_DETAILED_PLAN.md`](./M4_DETAILED_PLAN.md)。

**M4 起点（M4.1）**：归档 tests/unit/ 52 个 parity 测试 + tools/ 6 个 generator。
- 1 commit / 58 个 git mv / 0 LoC（rename）
- 解锁后续 M4.3 归档 modules/stages/shared

**完成 M4 后**：根据需要启动 M5 任意 step。M5 平铺 7 step 互不依赖，可按优先级灵活选择。

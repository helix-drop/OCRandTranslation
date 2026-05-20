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

| 阶段 | 主目标 | step 数 | 总 commits |
|---|---|---:|---:|
| **M1** | fnm-py 暴露 12 个旧公开 API 的 Rust 等价 | 12 | 12-15 |
| **M2** | 17 个外部 caller 切换 import（mechanical） | 5 | 5 |
| **M3** | DB-driven 输入桥接（load_inputs_from_db） | 4 | 4-5 |
| **M4** | 归档 `FNM_RE/{app,stages,modules,shared,constants,models}` | 4 | 4 |
| **M5** | fnm-py wheel 正式 CI 发布 | 4 | 4 |
| P1.1 | 清 Rust warnings | 3 | 3 |
| P1.2 | phase3 5 个 cascade ignored | 5 | 5 |
| P1.3 | PDFium binary 集成 | 2 | 2 |
| P2.1 | fnm-py pytest e2e 套件 | 3 | 3 |
| P2.2 | Python ↔ Rust shadow diff 完整版 | 3 | 3 |
| P2.3 | 用户面向 README | 1 | 1 |

**P0 (M1-M5)**：29 step / ~30 commit
**P1**：10 step / ~10 commit
**P2**：7 step / ~7 commit

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

## 8. M5 — fnm-py wheel 正式 CI 发布

### Step 列表

#### Step M5.1 — `.github/workflows/rust.yml` 加 maturin job

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 1 |
| LoC | +60 |
| tests | 0（CI 验证） |
| verify | push 后 CI 跑 `maturin build --release` 三平台产出 wheel |

#### Step M5.2 — manylinux2014 docker base

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 1（workflow） |
| LoC | +20 |
| tests | 0 |
| verify | linux x86_64 wheel size < 50MB，glibc 2.17 兼容 |

#### Step M5.3 — wheel artifact 上传 + GitHub Release

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 1 |
| LoC | +30 |
| tests | 0 |
| verify | tag push 触发 release，3 个 wheel 附在 release |

#### Step M5.4 — README 安装章节

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 2 (`FNM_RE/README.md` + 根 `README.md` 链接) |
| LoC | +80 |
| tests | 0 |
| verify | 文档 render 后样例可执行 |

---

## 9. P1 — Rust 代码质量（可并行）

### Step P1.1.1 — 清 phase1 6 warnings

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 3-5 |
| LoC | ±30 |
| verify | `cargo build -p fnm-phase1 2>&1 | grep -c warning` 输出 0 |

### Step P1.1.2 — 清 phase2 20 warnings

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 8-10 |
| LoC | ±100 |
| verify | `cargo build -p fnm-phase2 2>&1 | grep -c warning` 输出 0 |

### Step P1.1.3 — 清 phase4 11 warnings

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 5-7 |
| LoC | ±60 |
| verify | `cargo build -p fnm-phase4 2>&1 | grep -c warning` 输出 0 |

### Step P1.2.1-5 — phase3 5 个 cascade ignored tests 修复

每个 step：
| 字段 | 值 |
|---|---|
| commits | 1-2 |
| files | 3-6 |
| LoC | +50-200 |
| tests | 解 ignore + 加单测 |
| verify | 对应 parity test pass |

涉及测试：
1. `biopolitics_phase3_body_anchors_parity`
2. `biopolitics_phase3_chapter_contracts_parity`
3. `biopolitics_phase3_note_links_parity`
4. `biopolitics_phase3_summary_parity`
5. 详见 [`known_python_bugs.md`](../fnm_re_rs/fnm-phase3/tests/known_python_bugs.md) §7

### Step P1.3.1 — PDFium binary 集成

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 2 (`fnm-core/Cargo.toml` + workflow) |
| LoC | +30 |
| verify | `cargo test -p fnm-phase1 chapter_skeleton::pdf_font` 通过 |

### Step P1.3.2 — llm_book_type_verify e2e（需 API key）

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 1 |
| LoC | ±20 |
| verify | 设 `OPENAI_API_KEY` 后 `real_book_type_verify` 通过 |

---

## 10. P2 — 工程化补全（可推迟）

### Step P2.1.1-3 — fnm-py pytest e2e 套件

3 个 step，每个 step:
| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 2-3 |
| LoC | +100-200 |
| tests | 3-5 |

文件列表：
- `tests/test_pipeline_e2e.py`（Biopolitics 全 phase）
- `tests/test_llm_repair_pyo3.py`（NoopRenderer）
- `tests/test_shadow_mode.py`（env on/off）

### Step P2.2.1-3 — Python ↔ Rust shadow diff 完整版

3 个 step：
1. `dataclass_to_dict_recursive(obj)` helper（200 行）
2. `compare_python_vs_rust_snapshots(py_obj, rust_dict)` diff 函数（300 行）
3. e2e diff 报告 + 单测

### Step P2.3.1 — 用户面向 README 重写

| 字段 | 值 |
|---|---|
| commits | 1 |
| files | 1（`FNM_RE/README.md`） |
| LoC | +150 |
| tests | 0 |

---

## 11. 依赖图

```
M1.1 ─ M1.2 ─ M1.3 ─ ... ─ M1.12         M1 内部 step 顺序无强依赖，建议按风险升序：
  │                                       M1.1-M1.7 先（薄包装）
  │                                       M1.8 中（pipeline 入口）
  └─→ M2.1 ─ M2.2 ─ M2.3 ─ M2.4 ─ M2.5    M1.9 (LLM repair)
       │                                   M1.10 (build_doc_status，大块）
       │                                   M1.11 (page_translate，大块）
       │   M3.1 ─ M3.2 ─ M3.3 ─ M3.4       M1.12 (post_translate_checks)
       │   │
       └───┴───→ M4.1 ─ M4.2 ─ M4.3 ─ M4.4
                                     │
                                     └─→ M5.1 ─ M5.2 ─ M5.3 ─ M5.4

P1.* / P2.* 不依赖 M1-M5，可任何时机插入
```

---

## 12. 验收 checklist（P0 全完成后）

- [ ] `cargo test --workspace` ≥ 940 passed / 0 failed
- [ ] `pytest fnm_re_rs/fnm-py/tests/` ≥ 12 passed
- [ ] `pip install dist/fnm_re_rs-*.whl` 在 macOS arm64 + linux x86_64 一键装好
- [ ] `python -c "import fnm_re_rs; fnm_re_rs.run_pipeline_from_db_json('x.db', 'doc-id')"` 跑通
- [ ] `FNM_RE/` 只剩 ≤4 个条目：`__init__.py` / `README.md` / `dev/` / `__pycache__/`
- [ ] `grep -r "from FNM_RE.\(app\|stages\|modules\|shared\)" --include="*.py" . | grep -v 归档/` 返回 0 行
- [ ] Biopolitics e2e 12/12 chapter byte-equal Python golden（用归档前的 golden fixture）
- [ ] web/ 6 个路由 smoke 通过
- [ ] scripts/test_fnm_real_batch.py 跑 ≥3 本书通过
- [ ] `cargo clippy --workspace -- -D warnings` 0 warning

---

## 13. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| M1.10 `build_doc_status` 大块 port 漏译隐式约束 | 中 | M2 caller smoke 失败 | 步骤拆 3 个 commit；snapshot diff 验证 |
| M1.11 `page_translate` 含翻译任务调度，pyo3 跨 FFI 复杂 | 中 | M1 拖延 | 先 port build_unit_progress（最简），逐步上 |
| M2 caller 切换破坏 web 生产路径 | 中 | 生产中断 | 保留 Python `归档/FNM_RE/python/` 一份可回滚 |
| M3 SQLite schema 不一致 Rust 读不到 raw_pages | 低 | M1.8 卡 | M3.1 先单独跑 schema validator |
| pyo3 cdylib manylinux2014 build | 中 | M5 wheel 失败 | macOS arm64 已验证；linux 用 manylinux docker；windows 可选不发 |
| phase3 cascade 涉及 phase2 数据 bug | 中 | P1.2 拖延 | 标 known issue 不阻断 P0；专项 phase2 audit |

---

## 14. 下一步行动

按依赖图，**M1.1-M1.7（薄包装 7 个 API）**是最低风险起点：
- 每个 step 1 commit / ~50-80 行 / 1 测试
- 不涉及新业务逻辑，仅 DB 读 + pyo3 adapter + Python wrapper

每个 step 模板：

1. Rust 侧加 `#[pyfunction]`（fnm_re_rs/fnm-py/src/lib.rs）
2. fnm-orchestrator 暴露对应 helper（如需要）
3. Python 侧 `FNM_RE/__init__.py` 旧 lazy-import 改为：
   ```python
   def load_doc_structure(*args, **kwargs):
       import fnm_re_rs
       return json.loads(fnm_re_rs.load_doc_structure_json(...))
   ```
4. 加 pytest 用例（fnm_re_rs/fnm-py/tests/test_load_doc_structure.py）
5. `cargo test --workspace` 验证 940 不退步
6. commit

完成 M1.1 后我会再次询问继续 M1.2 还是其他。

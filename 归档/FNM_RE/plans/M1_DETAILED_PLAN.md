# M1 详细执行计划 · fnm-py 暴露 12 个旧公开 API

> 文档日期：2026-05-20
> 父计划：[`NEXT_PHASE_PLAN.md`](./NEXT_PHASE_PLAN.md) § 4
> 范围：M1.1 - M1.12，12 个 step，12-15 个 commit

---

## 0. 通用约定

### 0.1 每个 step 完成判据（统一）

```bash
# 1. cargo build 不引入 warnings
cargo build --workspace 2>&1 | grep -c "^warning:" == BEFORE

# 2. 940 workspace tests 不退步
cargo test --workspace --no-fail-fast 2>&1 | grep "^test result:" \
  | awk -F': ' '{print $2}' | awk '{p+=$2; f+=$4} END {print p,f}'
# 期望：≥940 0

# 3. 新增 pytest 用例通过
maturin develop && pytest fnm_re_rs/fnm-py/tests/test_<step_name>.py -q
# 期望：1 passed

# 4. Python wrapper 通过
python -c "import FNM_RE; FNM_RE.<api_name>(<args>)"
# 期望：无异常
```

### 0.2 通用文件清单（每 step 至少修改）

- `fnm_re_rs/fnm-py/src/lib.rs`（新 `#[pyfunction]`）
- `fnm_re_rs/fnm-py/tests/test_<step>.py`（新 pytest 用例）
- `FNM_RE/__init__.py`（旧 lazy-import 改 thin Rust wrapper）

按需追加：
- `fnm_re_rs/fnm-orchestrator/src/<module>.rs`（如需要新 Rust helper）
- `fnm_re_rs/fnm-core/src/db/repository.rs`（如需要新 Repository 方法）

### 0.3 通用代码模板

#### Rust pyfunction 模板

```rust
#[pyfunction]
fn <api_name>_json(
    db_path: &str,
    doc_id: &str,
    // ... other args
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let result = fnm_orchestrator::<helper>(&repo, doc_id /* ... */)
        .map_err(|e| PyRuntimeError::new_err(format!("<api>: {}", e)))?;

    serde_json::to_string(&result)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}
```

#### Python wrapper 模板（替换 FNM_RE/__init__.py 中旧 lazy-import）

```python
def <api_name>(*args, **kwargs):
    """←→ Rust fnm_re_rs.<api_name>_json"""
    import json as _json
    import fnm_re_rs
    # 1. 提取 doc_id / db_path 等位置参数
    doc_id = args[0] if args else kwargs.get("doc_id", "")
    db_path = kwargs.get("db_path") or _default_db_path()
    # 2. 调 Rust
    result_json = fnm_re_rs.<api_name>_json(db_path, doc_id, ...)
    # 3. 反序列化
    return _json.loads(result_json)
```

`_default_db_path()` 需在 `FNM_RE/__init__.py` 中加：
```python
def _default_db_path() -> str:
    """复用 persistence/sqlite_store.SQLiteRepository 的默认 DB 路径。"""
    from persistence.sqlite_store import DEFAULT_DB_PATH
    return str(DEFAULT_DB_PATH)
```

#### pytest 用例模板

```python
# fnm_re_rs/fnm-py/tests/test_<step>.py
import json
import sqlite3
import tempfile
from pathlib import Path

import fnm_re_rs


def _seed_biopolitics_db() -> Path:
    """复用 smoke_test.py 的 fixture 跑过 pipeline 后的 DB。"""
    # 用 run_pipeline_for_doc_json 先 seed phase1-6 表
    ...
    return Path(db_path)


def test_<api>_returns_expected_shape(tmp_path):
    db_path = _seed_biopolitics_db()
    result_json = fnm_re_rs.<api>_json(str(db_path), "biopolitics-seed", ...)
    result = json.loads(result_json)
    assert <invariant>
```

---

## 1. Step M1.1 — `load_doc_structure`

### Python 签名

```python
def load_phase6_for_doc(
    doc_id: str,
    *,
    include_diagnostic_entries: bool = False,
    slug: str = "",
    repo: SQLiteRepository | None = None,
    max_body_chars: int | None = None,
    pipeline_state_override: str | None = None,
    pages: list[dict] | None = None,
    overlay_mode: str = "hash_guarded",
    start_phase: str = "note_link_table",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Phase6Structure
```

**实质语义**：从 DB 读 phase1-6 全部表 → 组装 `Phase6Structure`（无需重跑 pipeline）。

### DB 表（只读）

`documents`, `fnm_pages`, `fnm_chapters`, `fnm_section_heads`, `fnm_heading_candidates`,
`fnm_note_regions`, `fnm_note_items`, `fnm_chapter_note_modes`,
`fnm_body_anchors`, `fnm_note_links`, `fnm_translation_units`,
`fnm_structure_reviews`, `fnm_chapter_markdowns`,
`fnm_export_chapters`, `fnm_export_audit`, `fnm_diagnostic_pages`, `fnm_diagnostic_notes`

### 依赖检查

| 需要 | 已有 | 缺 |
|---|---|---|
| `Repository::list_fnm_pages/chapters/...` | ✅ 16 个 list 方法 | 0 |
| `Phase6Structure` 类型 | ✅ `fnm-core/src/records.rs` | 0 |
| `load_phase6_structure(repo, doc_id) -> Phase6Structure` 编排 | ❌ 需新增 | 1 |

### Rust pyfunction 签名

```rust
#[pyfunction]
fn load_doc_structure_json(
    db_path: &str,
    doc_id: &str,
    include_diagnostic_entries: bool,
) -> PyResult<String>
```

`include_diagnostic_entries=False` 时 diagnostic_pages/notes 不读，提速。

### Action Checklist

- [ ] `fnm-orchestrator/src/load.rs` 新增 `pub fn load_phase6_structure(repo, doc_id, include_diag) -> Phase6Structure`
- [ ] `fnm-orchestrator/src/lib.rs` re-export
- [ ] `fnm-py/src/lib.rs` 加 `#[pyfunction] load_doc_structure_json`
- [ ] `fnm-py/src/lib.rs::fnm_re_rs(_py, m)` 加 `m.add_function(...)?;`
- [ ] `FNM_RE/__init__.py::load_doc_structure` 改 thin Rust wrapper
- [ ] `fnm-py/tests/test_load_doc_structure.py`：用 smoke_test seed 的 DB → 调用 → 断言 phase6.chapters 长度 = 12
- [ ] `cargo test --workspace` ≥940 / 0 failed
- [ ] commit

### 踩坑

- `Phase6Structure.diagnostic_pages/notes` 默认 serialize 会很大；按 `include_diagnostic_entries` 决定是否填充
- 若 doc_id 在 documents 表不存在，Rust 端应返回明确错误而非空 Phase6Structure

---

## 2. Step M1.2 — `audit_export_for_doc`

### Python 签名

```python
def audit_phase6_export_for_doc(
    doc_id: str,
    *,
    slug: str = "",
    zip_path: str = "",
    zip_bytes: bytes | None = None,
    repo: SQLiteRepository | None = None,
    snapshot: Any | None = None,
) -> dict[str, Any]
```

**实质语义**：对已 export 的 zip 跑审计（chapter contract / footnote leak / 等）。
zip 来源三选一：`zip_path` / `zip_bytes` / `snapshot.export_bundle`。

### DB 表

- 读：`fnm_export_bundle`, `fnm_export_audit`（用于 read-back 路径）
- 写：`fnm_export_audit`（如果重新跑 audit）

### 依赖检查

| 需要 | 已有 |
|---|---|
| `fnm_phase6::export_audit::audit_phase6_export(zip_path)` | ✅ |
| `fnm_phase6::export_audit::read_zip_markdown_files(bytes)` | ✅ |
| `Repository::list_fnm_export_audit(doc_id)` | ✅ |

无需新增 Rust 编排。

### Rust pyfunction 签名

```rust
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, slug="", zip_path=None, zip_bytes=None))]
fn audit_export_for_doc_json(
    db_path: &str,
    doc_id: &str,
    slug: &str,
    zip_path: Option<&str>,
    zip_bytes: Option<&[u8]>,
) -> PyResult<String>
```

### Action Checklist

- [ ] `fnm-py/src/lib.rs` 加 `#[pyfunction] audit_export_for_doc_json`
- [ ] 内部分支：zip_path 非空 → 调 `audit_phase6_export(path)`；zip_bytes 非空 → 用临时文件 wrap；都空 → DB 读 export_bundle.zip_bytes 后回退
- [ ] `FNM_RE/__init__.py::audit_export_for_doc` 改 thin Rust wrapper
- [ ] `fnm-py/tests/test_audit_export.py`：seed DB（M1.1 fixture）→ 跑 audit → 断言 `contract_ok=True`
- [ ] `cargo test --workspace` 验证
- [ ] commit

### 踩坑

- `zip_bytes: Option<&[u8]>` 在 pyo3 中映射为 `Option<&PyBytes>` 需手动取 `as_bytes()`
- audit 函数签名是 `audit_phase6_export(zip_path: &Path)` 不支持 bytes 直传，bytes 需先 `tempfile::NamedTempFile` 写盘

---

## 3. Step M1.3 — `build_export_bundle_for_doc`

### Python 签名

```python
def build_phase6_export_bundle_for_doc(
    doc_id: str,
    *,
    include_diagnostic_entries: bool = False,
    repo: SQLiteRepository | None = None,
    snapshot: Any | None = None,
) -> dict[str, Any]
```

返回 `{chapters: [...], chapter_files: {...}, files: {...}, export_semantic_contract_ok: bool, ...}`，对应 `ExportBundleRecord` 字段。

### DB 表

- 读：`fnm_export_bundle`

### 依赖检查

| 需要 | 已有 |
|---|---|
| `Repository::list_fnm_export_bundle(doc_id) -> Option<ExportBundleRecord>` | ✅ |

### Rust pyfunction 签名

```rust
#[pyfunction]
fn build_export_bundle_for_doc_json(
    db_path: &str,
    doc_id: &str,
) -> PyResult<String>
```

### Action Checklist

- [ ] `fnm-py/src/lib.rs` 加 pyfunction
- [ ] 内部：repo.list_fnm_export_bundle(doc_id) → serde_json::to_string
- [ ] `FNM_RE/__init__.py::build_export_bundle_for_doc` 改 wrapper
- [ ] `fnm-py/tests/test_export_bundle.py`：seed DB → 断言 `chapters: 12`
- [ ] cargo test --workspace
- [ ] commit

### 踩坑

- bundle 不存在时 Python 旧版抛 `MISSING_PERSISTED_EXPORT_BUNDLE_MESSAGE`；Rust 端用 `PyRuntimeError::new_err`

---

## 4. Step M1.4 — `build_export_zip_for_doc`

### Python 签名

```python
def build_phase6_export_zip_for_doc(
    doc_id: str,
    *,
    include_diagnostic_entries: bool = False,
    repo: SQLiteRepository | None = None,
    snapshot: Any | None = None,
) -> bytes
```

### DB 表

- 读：`fnm_export_bundle.zip_bytes` 字段

### 依赖检查

| 需要 | 已有 / 缺 |
|---|---|
| zip_bytes 存到 export_bundle 表 | ⚠️ 当前 schema 不一定有 zip_bytes 列，需 check |

### Rust pyfunction 签名

```rust
#[pyfunction]
fn build_export_zip_for_doc_json(
    db_path: &str,
    doc_id: &str,
) -> PyResult<Py<PyBytes>>  // 注意返回 bytes 不是 String
```

### Action Checklist

- [ ] check `fnm_export_bundle.zip_bytes` 列存在；若无，需 migration 加列（追加 step）
- [ ] `fnm-py/src/lib.rs` 加 pyfunction，返回 `Py<PyBytes>`
- [ ] `FNM_RE/__init__.py::build_export_zip_for_doc` 改 wrapper
- [ ] `fnm-py/tests/test_export_zip.py`：seed DB → bytes 解压成功 + 含 README.md
- [ ] cargo test --workspace
- [ ] commit

### 踩坑

- pyo3 返回 `Py<PyBytes>` 需 `PyBytes::new_bound(py, bytes)` 显式拷贝
- 若 zip_bytes 列缺失，回退到 `build_module_export_bundle` 重新生成 zip

---

## 5. Step M1.5 — `list_diagnostic_entries_for_doc`

### Python 签名

```python
def list_phase6_diagnostic_entries_for_doc(
    doc_id: str,
    *,
    pages: list[dict] | None = None,
    visible_bps: list[int] | None = None,
    repo: SQLiteRepository | None = None,
) -> list[dict]
```

### DB 表

- 读：`fnm_diagnostic_pages`

### 依赖检查

| 需要 | 已有 |
|---|---|
| `Repository::list_fnm_diagnostic_pages` | ✅ |

### Rust pyfunction 签名

```rust
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, visible_bps=None))]
fn list_diagnostic_entries_for_doc_json(
    db_path: &str,
    doc_id: &str,
    visible_bps: Option<Vec<i64>>,
) -> PyResult<String>
```

### Action Checklist

- [ ] `fnm-py/src/lib.rs` 加 pyfunction
- [ ] 内部：repo.list_fnm_diagnostic_pages → 按 visible_bps filter → serde
- [ ] `FNM_RE/__init__.py::list_diagnostic_entries_for_doc` 改 wrapper
- [ ] `fnm-py/tests/test_diagnostic_entries.py`：seed → 返回 list，长度 ≥0
- [ ] cargo test --workspace
- [ ] commit

### 踩坑

- 旧 Python 版接受 `pages` kwarg 用于内存路径；Rust 版可忽略（仅 DB 模式）

---

## 6. Step M1.6 — `list_diagnostic_notes_for_doc`

### Python 签名

```python
def list_phase6_diagnostic_notes_for_doc(
    doc_id: str,
    *,
    repo: SQLiteRepository | None = None,
) -> list[dict]
```

### DB 表

- 读：`fnm_diagnostic_notes`

### 依赖检查

| 需要 | 已有 |
|---|---|
| `Repository::list_fnm_diagnostic_notes` | ✅ |

### Rust pyfunction 签名

```rust
#[pyfunction]
fn list_diagnostic_notes_for_doc_json(
    db_path: &str,
    doc_id: &str,
) -> PyResult<String>
```

### Action Checklist

与 M1.5 完全平行。规模更小。

- [ ] `fnm-py/src/lib.rs` 加 pyfunction
- [ ] wrapper + test + verify + commit

---

## 7. Step M1.7 — `get_diagnostic_entry_for_page`

### Python 签名

```python
def get_phase6_diagnostic_entry_for_doc(
    doc_id: str,
    bp: int,
    *,
    pages: list[dict] | None = None,
    allow_fallback: bool = True,
    repo: SQLiteRepository | None = None,
) -> dict | None
```

### DB 表

- 同 M1.5（filter 单个 bp）

### Rust pyfunction 签名

```rust
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, bp, allow_fallback=true))]
fn get_diagnostic_entry_for_page_json(
    db_path: &str,
    doc_id: &str,
    bp: i64,
    allow_fallback: bool,
) -> PyResult<String>  // 返回 "null" 或 JSON 对象
```

### Action Checklist

- [ ] 复用 M1.5 的 repo 方法，filter `page_no == bp`
- [ ] 找不到 + allow_fallback=true → 返回 `null`（JSON 序列化的 None）
- [ ] wrapper + test + verify + commit

---

## 8. Step M1.8 — `run_doc_pipeline`

### Python 签名

```python
def run_phase6_pipeline_for_doc(
    doc_id: str,
    *,
    max_body_chars: int | None = None,
    repo: SQLiteRepository | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    start_phase: str = "toc",
) -> dict[str, Any]
```

**关键不同**：Python 版会调 `repo.load_pages_phase1` 从 DB 读 pages，然后调
`build_module_pipeline_snapshot(pages, toc_items=..., ...)`。

### DB 表

- 读：`documents`, `raw_pages`（待 schema 确认）, `visual_toc.manual_inputs`
- 写：phase1-6 全部表 + `fnm_run`

### 依赖检查

| 需要 | 已有 / 缺 |
|---|---|
| `fnm_orchestrator::run_pipeline_for_doc` | ✅ |
| 从 DB 读 raw_pages 的 Repository 方法 | ⚠️ 当前 `list_fnm_pages` 返回的是 `PagePartitionRecord`（phase1 产物），不是 `RawPage`（OCR 原始） |
| 从 DB 读 visual_toc TOC items | ❌ 需新增 |

### 实施路径

依赖 **M3.1 + M3.2**（Repository 加 `load_raw_pages_for_doc` + `load_toc_items_for_doc`）先完成。

或者 M1.8 内置 inline 实现，M3 时重构出 Repository 方法。

**推荐**：M1.8 先在 fnm-py 内 inline 读 DB（用 rusqlite 直接 SELECT），M3 重构。

### Rust pyfunction 签名

```rust
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, max_body_chars=None, start_phase="toc"))]
fn run_doc_pipeline_json(
    db_path: &str,
    doc_id: &str,
    max_body_chars: Option<i64>,
    start_phase: &str,
) -> PyResult<String>
```

### Action Checklist

- [ ] check raw_pages 表 schema（看 `persistence/sqlite_schema.py`）
- [ ] `fnm-py/src/lib.rs` 加 `fn load_raw_pages_inline(conn, doc_id)` + `fn load_toc_items_inline(conn, doc_id)` helper
- [ ] 加 `#[pyfunction] run_doc_pipeline_json`：组装 pages/toc/config → 调 `fnm_orchestrator::run_pipeline_for_doc`
- [ ] `FNM_RE/__init__.py::run_doc_pipeline` 改 thin Rust wrapper
- [ ] 写 `fnm_run` 表行（status=running → done/error）—— 借鉴 Python 版逻辑
- [ ] `fnm-py/tests/test_run_doc_pipeline.py`：seed empty DB + raw_pages → 跑 → 断言 phase6 chapters=12
- [ ] `cargo test --workspace`
- [ ] commit

### 踩坑

- `progress_callback` 暂不支持（Python callback 跨 FFI 复杂）；Python wrapper 中接受但不传给 Rust
- `start_phase != "toc"` 暂不支持，传入时报 error；M3 完成后再补
- `fnm_run` 表写入需要 `create_fnm_run` / `update_fnm_run` repo 方法（可能需新增）

### 工作量大于平均

| 字段 | 值 |
|---|---|
| commits | 2 (load_helpers + pipeline_entry) |
| files | 4-5 |
| LoC | +200 |
| tests | 2 |

---

## 9. Step M1.9 — `run_llm_repair`（独立入口）

### Python 签名

```python
def run_llm_repair(
    doc_id: str,
    *,
    repo: SQLiteRepository | None = None,
    slug: str = "",
    cluster_limit: int | None = None,
    auto_apply: bool = True,
    confidence_threshold: float = 0.9,
    model_args: dict | None = None,
    max_matched_examples: int | None = None,
    max_unmatched_note_items: int | None = None,
    max_unmatched_anchors: int | None = None,
    clear_materialized_overrides: bool = True,
) -> dict
```

### DB 表

- 读：phase1-3 + 已有 review_overrides
- 写：`fnm_review_overrides_v2`

### 依赖检查

| 需要 | 已有 |
|---|---|
| `fnm_llm_repair::run::run_llm_repair(params) -> LlmRepairReport` | ✅ |
| `fnm_llm_repair::page_context::PyRepairRenderer` | ✅ |
| pyo3 包装 Python callable 为 renderer | ✅ 已在 M1 之前实现 |

### Rust pyfunction 签名

```rust
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, pdf_path, renderer=None, slug="",
                   auto_apply=true, confidence_threshold=0.9, cluster_limit=None))]
fn run_llm_repair_json(
    db_path: &str,
    doc_id: &str,
    pdf_path: &str,
    renderer: Option<Py<PyAny>>,
    slug: &str,
    auto_apply: bool,
    confidence_threshold: f64,
    cluster_limit: Option<usize>,
) -> PyResult<String>
```

### Action Checklist

- [ ] `fnm-py/src/lib.rs` 加 `#[pyfunction] run_llm_repair_json`
- [ ] 内部用 tokio current_thread runtime block_on async 调用
- [ ] PyRepairRenderer 包装（复用之前 LLM repair 集成的实现）
- [ ] `FNM_RE/__init__.py::run_llm_repair` 改 wrapper
- [ ] `fnm-py/tests/test_run_llm_repair.py`：seed DB（已 phase1-3） + NoopRenderer → 跑 → 断言 cluster_count ≥ 1
- [ ] `cargo test --workspace`
- [ ] commit

### 踩坑

- LlmRepairReport 字段众多（cluster_count / suggestion_count / auto_applied / usage_summary / 等）需全 serde
- 现成代码可参考 `fnm_orchestrator::mainline::run_llm_repair_sync`——直接抽出独立函数

---

## 10. Step M1.10 — `build_doc_status`

### Python 签名

```python
def build_phase6_status_for_doc(
    doc_id: str,
    *,
    snapshot: Any | None = None,
    repo: SQLiteRepository | None = None,
    start_phase: str = "toc",
) -> dict[str, Any]
```

返回 `StructureStatusRecord` 等价 dict，含 phase4/6 各 ~8 个 gate 字段。

### Python 实现规模

`FNM_RE/app/status.py` 共 748 行，含多个 helper：
- `build_phase4_status(phase4_structure)`
- `build_phase6_status(phase6_structure)`
- `_classify_phase_state(...)` / `_resolve_phase4_blockers(...)` / 等

### DB 表

- 读：`fnm_run`, `fnm_run.validation_json`，间接读 phase4/6 全部表

### 依赖检查

| 需要 | 已有 / 缺 |
|---|---|
| `StructureStatusRecord` 类型 | ✅ `fnm-core/src/records.rs` |
| `fnm_orchestrator::build_doc_status` | ❌ 需 port |
| Repository.get_latest_fnm_run | ❌ 需新增（看 Python 用了 `getattr(repo, "get_latest_fnm_run", None)`）|

### Rust pyfunction 签名

```rust
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, start_phase="toc"))]
fn build_doc_status_json(
    db_path: &str,
    doc_id: &str,
    start_phase: &str,
) -> PyResult<String>
```

### Action Checklist（拆 3 commit）

#### Commit 10a：port status.py 核心 helper 到 fnm-orchestrator

- [ ] 新文件 `fnm_re_rs/fnm-orchestrator/src/status.rs`
- [ ] port `build_phase4_status(phase4_structure) -> serde_json::Value`
- [ ] port `build_phase6_status(phase6_structure) -> serde_json::Value`
- [ ] port `classify_phase_state` / `resolve_blockers` / 等 helper
- [ ] 单测覆盖各 gate 字段
- [ ] `cargo test -p fnm-orchestrator`

#### Commit 10b：Repository 加 `get_latest_fnm_run`

- [ ] `fnm-core/src/db/repository.rs` 加 trait method + SqliteRepository 实现
- [ ] 单测

#### Commit 10c：pyo3 暴露 + Python wrapper

- [ ] `fnm-orchestrator::build_doc_status(repo, doc_id, start_phase) -> StructureStatusRecord`
- [ ] `fnm-py/src/lib.rs` 加 pyfunction
- [ ] `FNM_RE/__init__.py::build_doc_status` 改 wrapper
- [ ] `fnm-py/tests/test_build_doc_status.py`：seed → 断言含 8 个关键字段
- [ ] cargo test --workspace
- [ ] commit

### 踩坑

- gate 字段命名必须与 Python 完全一致（caller 在 web/ 读特定字段）
- `_resolve_phase4_blockers` 可能涉及枚举值映射，需 byte-equal Python golden

### 工作量

| 字段 | 值 |
|---|---|
| commits | 3 |
| files | 6-8 |
| LoC | +500-700 |
| tests | 3-5 |

---

## 11. Step M1.11 — `prepare_page_translate_jobs` + `build_retry_summary` + `build_unit_progress`

### 三个 Python 签名

```python
def prepare_page_translate_jobs(
    pages: list,
    target_bp: int,
    t_args: dict,
    doc_id: str,
    *,
    repo: SQLiteRepository | None = None,
) -> tuple[dict, list[dict], dict]

def build_retry_summary(
    doc_id: str,
    *,
    snapshot: dict | None = None,
    repo: SQLiteRepository | None = None,
) -> dict

def build_unit_progress(
    doc_id: str,
    *,
    repo: SQLiteRepository | None = None,
    snapshot: dict | None = None,
    use_lightweight: bool = False,
) -> dict
```

### Python 实现规模

`FNM_RE/app/page_translate.py` 共 880 行。

### DB 表

- 读：`fnm_translation_units`, `fnm_run.validation_json`, `translation.translate_store` 状态文件

### 依赖检查

| 需要 | 已有 / 缺 |
|---|---|
| `Repository::list_fnm_translation_units` | ✅ |
| `build_unit_progress` 等 helper | ❌ 需 port |

### Action Checklist（拆 3 commit）

#### Commit 11a：build_unit_progress（最简，先做）

- [ ] 新文件 `fnm_re_rs/fnm-orchestrator/src/page_translate.rs`
- [ ] port `build_unit_progress(repo, doc_id, use_lightweight) -> serde_json::Value`
- [ ] 内部读 fnm_translation_units 统计 done/error/total/pending
- [ ] 单测
- [ ] `fnm-py/src/lib.rs` 加 `build_unit_progress_json`
- [ ] `FNM_RE/__init__.py::build_unit_progress` 改 wrapper
- [ ] pytest
- [ ] commit

#### Commit 11b：build_retry_summary

- [ ] `fnm-orchestrator::page_translate::build_retry_summary(repo, doc_id) -> serde_json::Value`
- [ ] 读 fnm_run.validation_json + filter retry-able units
- [ ] 单测 + pyo3 + wrapper + pytest
- [ ] commit

#### Commit 11c：prepare_page_translate_jobs

- [ ] `fnm-orchestrator::page_translate::prepare_page_translate_jobs(pages, target_bp, t_args, doc_id, repo) -> (job, jobs, meta)`
- [ ] **复杂度警告**：涉及 page → translation_unit 映射 + retry 状态合并
- [ ] 单测 + pyo3 + wrapper + pytest
- [ ] commit

### 工作量

| 字段 | 值 |
|---|---|
| commits | 3 |
| files | 6-9 |
| LoC | +600-900 |
| tests | 3 |

### 踩坑

- `prepare_page_translate_jobs` 返回 tuple，pyo3 端需返回 JSON 数组 `[job, jobs, meta]`，Python wrapper 端 unpack
- `t_args: dict` 内含 model_args 等业务字段，Rust 端透传不解析

---

## 12. Step M1.12 — `run_post_translate_export_checks_for_doc`

### Python 签名

```python
def run_post_translate_export_checks_for_doc(
    doc_id: str,
    *,
    max_repair_rounds: int = 3,
    repo: SQLiteRepository | None = None,
) -> dict[str, Any]
```

**实质语义**：翻译完成后跑 export → 跑 audit → 检测 issue → 触发 max_repair_rounds 轮自修复。

### DB 表

- 读：phase1-6
- 写：可能写回 phase6（如果 repair）

### 依赖检查

| 需要 | 已有 / 缺 |
|---|---|
| 调用链：load_phase6 → build_export_zip → audit_export | M1.1 + M1.4 + M1.2 完成后已有 |
| `repair_rounds` 循环逻辑 | ❌ 需 port |

### Action Checklist

- [ ] `fnm-orchestrator/src/post_translate.rs` 新增 `run_post_translate_export_checks(repo, doc_id, max_repair_rounds)`
- [ ] 内部循环：load → export → audit → if issue → repair → max_rounds
- [ ] 复用 M1.1 / M1.2 / M1.4 已实现的函数
- [ ] pyo3 暴露 + Python wrapper
- [ ] pytest（用已 export 的 fixture，max_repair_rounds=0 应直接通过）
- [ ] cargo test --workspace
- [ ] commit

### 工作量

| 字段 | 值 |
|---|---|
| commits | 1-2 |
| files | 4-6 |
| LoC | +200-300 |
| tests | 1 |

---

## 13. M1 验收 checklist

完成 M1.1-M1.12 全部 step 后：

### 13.1 Rust 端

```bash
cargo build --workspace 2>&1 | grep -c "^warning:"
# 期望：≤37（不引入新 warnings；P1.1 单独清理）

cargo test --workspace --no-fail-fast 2>&1 | grep "^test result: ok" | wc -l
# 期望：≥29
```

### 13.2 Python 端

```bash
maturin develop
pytest fnm_re_rs/fnm-py/tests/ -q
# 期望：≥12 passed
```

### 13.3 公开 API

```python
import FNM_RE

# 所有旧 API 走 Rust（thin wrapper）
FNM_RE.load_doc_structure("biopolitics-seed")              # ✓
FNM_RE.audit_export_for_doc("biopolitics-seed")            # ✓
FNM_RE.build_export_bundle_for_doc("biopolitics-seed")     # ✓
FNM_RE.build_export_zip_for_doc("biopolitics-seed")        # ✓ bytes
FNM_RE.list_diagnostic_entries_for_doc("biopolitics-seed") # ✓
FNM_RE.list_diagnostic_notes_for_doc("biopolitics-seed")   # ✓
FNM_RE.get_diagnostic_entry_for_page("biopolitics-seed", 100)  # ✓
FNM_RE.run_doc_pipeline("biopolitics-seed", pdf_path="...")    # ✓
FNM_RE.run_llm_repair("biopolitics-seed", slug="biopolitics")  # ✓
FNM_RE.build_doc_status("biopolitics-seed")                # ✓
FNM_RE.prepare_page_translate_jobs(pages, 0, {}, "...")    # ✓
FNM_RE.build_retry_summary("biopolitics-seed")             # ✓
FNM_RE.build_unit_progress("biopolitics-seed")             # ✓
FNM_RE.run_post_translate_export_checks_for_doc("...")     # ✓
```

### 13.4 验证 Python 端不再依赖 `app/`

```bash
# FNM_RE/__init__.py 中除 thin wrapper 外不应再有 "from FNM_RE.app." import
grep "from FNM_RE.app" FNM_RE/__init__.py
# 期望：仅在 thin wrapper 内（如 audit_export_for_doc 的 fallback）；理想为 0 行
```

（注：M1 完成后 web/translation/scripts 仍直接 import `FNM_RE.app.*`——那是 M2 任务。）

---

## 14. M1 实施顺序

**严格按本文档章节顺序执行**：M1.1 → M1.2 → ... → M1.12。

**每个 step 1 个独立 AI session**：前一个 session 完成报告 commit hash 后，再开下一个 session。
不要在同一 session 连续做两个 step——上下文会膨胀且 cold-start 模式更可控。

完整 session prompt 见 [`M1_SESSION_PROMPTS.md`](./M1_SESSION_PROMPTS.md)，每个 step 一段 prompt
可直接复制给其他 AI（自包含 cold-start）。

---

## 15. 跨 step 依赖

```
fnm_orchestrator::load_phase6_structure (M1.1)
  ↑                                 │
  │                                 ├── M1.5/M1.6/M1.7 直接复用
  │                                 ├── M1.2 audit 内部用
  │                                 ├── M1.12 post_translate 用
  │
  └── 依赖 fnm-core Repository.list_* （已 ready）

fnm_orchestrator::run_pipeline_for_doc (已 ready)
  ↑
  └── M1.8 直接复用 + fnm_run 状态机包装

fnm_llm_repair::run_llm_repair (已 ready)
  ↑
  └── M1.9 直接 pyo3 暴露

fnm_orchestrator::status (M1.10a)
  ↑
  └── M1.10c pyo3 暴露

fnm_orchestrator::page_translate (M1.11a-c)
  ↑
  └── M1.11 pyo3 暴露
```

---

## 16. 完整 Session Prompts

12 个 step 的完整 cold-start prompt 见 [`M1_SESSION_PROMPTS.md`](./M1_SESSION_PROMPTS.md)。

每段 prompt 包含：
- 项目背景（30 秒）
- 必读文档（4 个，按顺序）
- 任务清单（本 step Action Checklist）
- 关键约束（引 CLAUDE.md / AGENTS.md 条款）
- 完成判据（cargo + maturin + pytest 命令）
- 报告格式（commit hash + tests + 踩坑 + 额外发现）

**用法**：把对应 step 的 ` ``` ` 代码块全部内容复制给其他 AI；
该 AI 在新 session 中读完必读文档后即可独立执行。

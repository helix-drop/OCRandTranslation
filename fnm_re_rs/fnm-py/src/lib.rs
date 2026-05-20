#![recursion_limit = "512"]

//! `fnm-py` — pyo3 Python binding for `fnm-orchestrator`。
//!
//! ←→ Python `FNM_RE/__init__.py`：从 Python 调用 Rust pipeline。
//!
//! ## 使用（Python 端）
//!
//! ```python
//! import json
//! from fnm_re_rs import run_pipeline_json
//!
//! pages_json = json.dumps(raw_pages)
//! toc_json = json.dumps(toc_items)
//! config_json = json.dumps({"doc_id": "demo", "slug": "demo", "pdf_path": ""})
//! result_json = run_pipeline_json(pages_json, toc_json, config_json)
//! result = json.loads(result_json)
//! ```
//!
//! ## 边界设计
//!
//! 当前版本采用 JSON 字符串边界（caller 自己 json.dumps/loads），避免 PyDict ↔ Rust struct
//! 双向转换的复杂度。后续可加 PyDict 直通版本（如 `run_pipeline_dict`）。

use std::path::Path;

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyTuple};

use fnm_core::db::{open_pool, Repository, SqliteRepository};
use fnm_llm_repair::page_context::{NoopRenderer, RepairImageRenderer};
use fnm_llm_repair::run::{run_llm_repair, RunLlmRepairParams};
use fnm_orchestrator::mainline::LlmRepairOptions;
use fnm_orchestrator::types::PipelineConfig;
use fnm_phase1::input::{RawPage, TocItem};

/// 包装 Python callable 实现 `RepairImageRenderer`。
///
/// Python 端签名：`(pdf_path: str, file_idx: int) -> Optional[str]`
/// 返回 `data:image/...;base64,...` 形式的 URL 或 None。
struct PyRepairRenderer {
    callback: Py<PyAny>,
}

impl PyRepairRenderer {
    fn new(callback: Py<PyAny>) -> Self {
        Self { callback }
    }
}

impl RepairImageRenderer for PyRepairRenderer {
    fn render_page_data_url(&self, pdf_path: &str, file_idx: i64) -> Option<String> {
        Python::with_gil(|py| -> Option<String> {
            let args = PyTuple::new_bound(py, &[pdf_path.into_py(py), file_idx.into_py(py)]);
            let result = self.callback.call1(py, args).ok()?;
            // 期望 Optional[str]：None / str / 抛错都视作 None
            result.extract::<Option<String>>(py).ok().flatten()
        })
    }
}

/// Pipeline 入口（JSON 字符串边界）。
///
/// 参数：
/// - `pages_json`：`list[dict]` JSON——每项对应一个 RawPage（含 bookPage / markdown / fnBlocks 等）
/// - `toc_items_json`：`list[dict]` JSON——每项对应一个 TocItem（含 title / target_pdf_page / role_hint）
/// - `config_json`：`dict` JSON——PipelineConfig 字段（doc_id / slug / pdf_path / toc_offset / ...）
///
/// 返回：`ModulePipelineSnapshot` JSON 字符串。
///
/// ←→ Python `FNM_RE/app/pipeline.py::build_module_pipeline_snapshot()`
#[pyfunction]
fn run_pipeline_json(
    pages_json: &str,
    toc_items_json: &str,
    config_json: &str,
) -> PyResult<String> {
    let pages: Vec<RawPage> = serde_json::from_str(pages_json)
        .map_err(|e| PyValueError::new_err(format!("invalid pages_json: {}", e)))?;
    let toc_items: Vec<TocItem> = serde_json::from_str(toc_items_json)
        .map_err(|e| PyValueError::new_err(format!("invalid toc_items_json: {}", e)))?;

    let config_value: serde_json::Value = serde_json::from_str(config_json)
        .map_err(|e| PyValueError::new_err(format!("invalid config_json: {}", e)))?;
    let config = parse_pipeline_config(&config_value)?;

    let snapshot = fnm_orchestrator::run_pipeline(pages, toc_items, config)
        .map_err(|e| PyRuntimeError::new_err(format!("pipeline error: {}", e)))?;

    serde_json::to_string(&snapshot)
        .map_err(|e| PyRuntimeError::new_err(format!("snapshot serialize: {}", e)))
}

fn parse_pipeline_config(value: &serde_json::Value) -> PyResult<PipelineConfig> {
    let obj = value
        .as_object()
        .ok_or_else(|| PyValueError::new_err("config_json must be a JSON object"))?;

    let get_str = |k: &str| -> String {
        obj.get(k)
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    };
    let get_i64 = |k: &str| -> i64 { obj.get(k).and_then(|v| v.as_i64()).unwrap_or(0) };
    let get_bool = |k: &str| -> bool { obj.get(k).and_then(|v| v.as_bool()).unwrap_or(false) };

    let start_phase = fnm_orchestrator::StartPhase::from_str(&get_str("start_phase"))
        .map_err(|e| PyValueError::new_err(format!("invalid start_phase: {}", e)))?;

    Ok(PipelineConfig {
        doc_id: get_str("doc_id"),
        slug: get_str("slug"),
        pdf_path: get_str("pdf_path"),
        toc_offset: get_i64("toc_offset"),
        max_body_chars: get_i64("max_body_chars"),
        include_diagnostic_entries: get_bool("include_diagnostic_entries"),
        manual_toc_ready: get_bool("manual_toc_ready"),
        pipeline_state: get_str("pipeline_state"),
        start_phase,
        review_overrides: obj.get("review_overrides").cloned(),
        visual_toc_bundle: obj.get("visual_toc_bundle").cloned(),
    })
}

/// DB-driven pipeline 入口（每个 phase 持久化到 SQLite）。
///
/// 参数：
/// - `db_path`：SQLite 数据库文件路径
/// - `doc_id`：文档 ID（决定 fnm_* 表的 doc_id 字段）
/// - `pages_json` / `toc_items_json` / `config_json`：同 `run_pipeline_json`
///
/// 返回：`ModulePipelineSnapshot` JSON 字符串（含 phase1-6 序列化体 + run_meta）。
///
/// ←→ Python `FNM_RE/app/mainline.py::run_phase6_pipeline_for_doc()`
#[pyfunction]
fn run_pipeline_for_doc_json(
    db_path: &str,
    doc_id: &str,
    pages_json: &str,
    toc_items_json: &str,
    config_json: &str,
) -> PyResult<String> {
    let pages: Vec<RawPage> = serde_json::from_str(pages_json)
        .map_err(|e| PyValueError::new_err(format!("invalid pages_json: {}", e)))?;
    let toc_items: Vec<TocItem> = serde_json::from_str(toc_items_json)
        .map_err(|e| PyValueError::new_err(format!("invalid toc_items_json: {}", e)))?;

    let config_value: serde_json::Value = serde_json::from_str(config_json)
        .map_err(|e| PyValueError::new_err(format!("invalid config_json: {}", e)))?;
    let config = parse_pipeline_config(&config_value)?;

    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let snapshot = fnm_orchestrator::run_pipeline_for_doc(
        &repo, doc_id, pages, toc_items, config, None,
    )
    .map_err(|e| PyRuntimeError::new_err(format!("pipeline error: {}", e)))?;

    serde_json::to_string(&snapshot)
        .map_err(|e| PyRuntimeError::new_err(format!("snapshot serialize: {}", e)))
}

/// DB-driven pipeline 入口 + LLM repair（Step 3.5）集成。
///
/// 参数：
/// - `db_path` / `doc_id` / `pages_json` / `toc_items_json` / `config_json`：
///   同 `run_pipeline_for_doc_json`
/// - `pdf_path`：PDF 文件路径（LLM vision 渲染用）
/// - `renderer`：Python callable `(pdf_path: str, file_idx: int) -> Optional[str]`
///   返回 `data:image/...;base64,...`，传 None 时用 NoopRenderer（不渲染）
/// - `auto_apply`：true → 直接写 review_overrides；false → 仅产生 suggestions
/// - `confidence_threshold`：自动应用的最小置信度，默认 0.9
///
/// 返回：`ModulePipelineSnapshot` JSON（含 run_meta.llm_repair 子段）
///
/// ←→ Python `FNM_RE/modules/llm_repair.py::run_llm_repair` 嵌入式调用
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, pages_json, toc_items_json, config_json, pdf_path, renderer=None, auto_apply=true, confidence_threshold=0.9))]
fn run_pipeline_for_doc_with_llm_repair_json(
    py: Python<'_>,
    db_path: &str,
    doc_id: &str,
    pages_json: &str,
    toc_items_json: &str,
    config_json: &str,
    pdf_path: &str,
    renderer: Option<Py<PyAny>>,
    auto_apply: bool,
    confidence_threshold: f64,
) -> PyResult<String> {
    let pages: Vec<RawPage> = serde_json::from_str(pages_json)
        .map_err(|e| PyValueError::new_err(format!("invalid pages_json: {}", e)))?;
    let toc_items: Vec<TocItem> = serde_json::from_str(toc_items_json)
        .map_err(|e| PyValueError::new_err(format!("invalid toc_items_json: {}", e)))?;

    let config_value: serde_json::Value = serde_json::from_str(config_json)
        .map_err(|e| PyValueError::new_err(format!("invalid config_json: {}", e)))?;
    let config = parse_pipeline_config(&config_value)?;

    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    // 释放 GIL：pipeline 内部不需要持有 Python 锁
    let snapshot_result = py.allow_threads(|| -> Result<_, fnm_orchestrator::OrchestratorError> {
        let py_renderer = renderer.map(PyRepairRenderer::new);
        let noop = NoopRenderer;
        let renderer_ref: &dyn RepairImageRenderer = match &py_renderer {
            Some(r) => r,
            None => &noop,
        };
        let llm_opts = LlmRepairOptions {
            renderer: renderer_ref,
            pdf_path,
            auto_apply,
            confidence_threshold,
        };
        fnm_orchestrator::run_pipeline_for_doc(
            &repo,
            doc_id,
            pages,
            toc_items,
            config,
            Some(llm_opts),
        )
    });
    let snapshot = snapshot_result
        .map_err(|e| PyRuntimeError::new_err(format!("pipeline error: {}", e)))?;

    serde_json::to_string(&snapshot)
        .map_err(|e| PyRuntimeError::new_err(format!("snapshot serialize: {}", e)))
}

/// 从 DB 加载 phase1-6 全部数据 → Phase6Structure JSON。
///
/// - `db_path`: SQLite 数据库文件路径
/// - `doc_id`: 文档 ID
/// - `include_diagnostic_entries`: 是否包含 diagnostic_pages/notes（默认 false，提速）
///
/// 返回 Phase6Structure JSON 字符串。
///
/// ←→ Python `FNM_RE/__init__.py::load_doc_structure`
#[pyfunction]
fn load_doc_structure_json(
    db_path: &str,
    doc_id: &str,
    include_diagnostic_entries: bool,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let structure = fnm_orchestrator::load_phase6_structure(&repo, doc_id, include_diagnostic_entries)
        .map_err(|e| PyRuntimeError::new_err(format!("load_phase6_structure: {}", e)))?;

    serde_json::to_string(&structure)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 审计 Phase 6 导出。
///
/// - `db_path`: SQLite 数据库文件路径
/// - `doc_id`: 文档 ID
/// - `slug`: 文档 slug（为空时使用 doc_id）
/// - `zip_path`: zip 文件路径（可选）
/// - `zip_bytes`: zip 文件字节（可选）
///
/// 返回 ExportAuditReportRecord JSON 字符串。
///
/// ←→ Python `FNM_RE/__init__.py::audit_export_for_doc`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, slug="", zip_path=None, zip_bytes=None))]
fn audit_export_for_doc_json(
    db_path: &str,
    doc_id: &str,
    slug: &str,
    zip_path: Option<&str>,
    zip_bytes: Option<&[u8]>,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);
    let slug = if slug.is_empty() { doc_id } else { slug };

    let phase6 = fnm_orchestrator::load_phase6_structure(&repo, doc_id, false)
        .map_err(|e| PyRuntimeError::new_err(format!("load_phase6_structure: {}", e)))?;

    let payload: Option<Vec<u8>> = if let Some(bytes) = zip_bytes {
        Some(bytes.to_vec())
    } else if let Some(path_str) = zip_path {
        let p = Path::new(path_str);
        if !path_str.is_empty() && p.exists() {
            Some(
                std::fs::read(p)
                    .map_err(|e| PyRuntimeError::new_err(format!("read zip file: {}", e)))?,
            )
        } else {
            None
        }
    } else {
        None
    };

    let (report, _summary) = fnm_phase6::export_audit::audit_phase6_export(
        &phase6,
        slug,
        payload.as_deref(),
    );

    serde_json::to_string(&report)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 从 DB 读取 export bundle 记录。
///
/// 返回 ExportBundleRecord JSON 字符串，含 chapters / chapter_files / files / contract_ok 等字段。
///
/// bundle 不存在时抛出 PyRuntimeError。
///
/// ←→ Python `FNM_RE/__init__.py::build_export_bundle_for_doc`
#[pyfunction]
fn build_export_bundle_for_doc_json(
    db_path: &str,
    doc_id: &str,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let bundle = repo
        .list_fnm_export_bundle(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("list_fnm_export_bundle: {}", e)))?
        .ok_or_else(|| {
            PyRuntimeError::new_err(format!(
                "export bundle not found for doc_id '{}' — run pipeline + export first",
                doc_id
            ))
        })?;

    serde_json::to_string(&bundle)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 从 DB 读取 export bundle 并构建 ZIP 字节。
///
/// 返回 ZIP 文件二进制字节（PyBytes）。
///
/// ←→ Python `FNM_RE/__init__.py::build_export_zip_for_doc`
#[pyfunction]
fn build_export_zip_for_doc_json(
    py: Python,
    db_path: &str,
    doc_id: &str,
) -> PyResult<Py<PyBytes>> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let bundle = repo
        .list_fnm_export_bundle(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("list_fnm_export_bundle: {}", e)))?
        .ok_or_else(|| {
            PyRuntimeError::new_err(format!(
                "export bundle not found for doc_id '{}' — run pipeline + export first",
                doc_id
            ))
        })?;

    let zip_bytes = fnm_phase6::export::zip::build_export_zip(&bundle)
        .map_err(|e| PyRuntimeError::new_err(format!("build_export_zip: {}", e)))?;

    Ok(PyBytes::new_bound(py, &zip_bytes).into())
}

/// 从 DB 读取 diagnostic entries（诊断页面）。
///
/// visible_bps 可选过滤；返回 DiagnosticPageRecord 数组 JSON。
///
/// ←→ Python `FNM_RE/__init__.py::list_diagnostic_entries_for_doc`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, visible_bps=None))]
fn list_diagnostic_entries_for_doc_json(
    db_path: &str,
    doc_id: &str,
    visible_bps: Option<Vec<i64>>,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let mut entries = repo
        .list_fnm_diagnostic_pages(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("list_fnm_diagnostic_pages: {}", e)))?;

    if let Some(ref bps) = visible_bps {
        let filter_set: std::collections::HashSet<i64> = bps.iter().copied().collect();
        entries.retain(|e| filter_set.contains(&e._page_bp));
    }

    serde_json::to_string(&entries)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 从 DB 读取单页 diagnostic entry。
///
/// 如果找不到且 allow_fallback=true，返回 JSON null。
///
/// ←→ Python `FNM_RE/__init__.py::get_diagnostic_entry_for_page`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, bp, allow_fallback=true))]
fn get_diagnostic_entry_for_page_json(
    db_path: &str,
    doc_id: &str,
    bp: i64,
    allow_fallback: bool,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let entries = repo
        .list_fnm_diagnostic_pages(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("list_fnm_diagnostic_pages: {}", e)))?;

    let matched = entries.into_iter().find(|e| e._page_bp == bp);

    match matched {
        Some(entry) => serde_json::to_string(&entry)
            .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e))),
        None if allow_fallback => Ok("null".to_string()),
        None => Err(PyRuntimeError::new_err(format!(
            "diagnostic entry not found for doc_id '{}' page_bp {}",
            doc_id, bp
        ))),
    }
}

/// 从 DB 读取 diagnostic notes。
///
/// 返回 DiagnosticNoteRecord 数组 JSON。
///
/// ←→ Python `FNM_RE/__init__.py::list_diagnostic_notes_for_doc`
#[pyfunction]
fn list_diagnostic_notes_for_doc_json(
    db_path: &str,
    doc_id: &str,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let notes = repo
        .list_fnm_diagnostic_notes(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("list_fnm_diagnostic_notes: {}", e)))?;

    serde_json::to_string(&notes)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 从 DB `pages` 表读取 RawPage 列表。
fn load_raw_pages_from_db(
    conn: &rusqlite::Connection,
    doc_id: &str,
) -> PyResult<Vec<RawPage>> {
    let mut stmt = conn
        .prepare("SELECT payload_json FROM pages WHERE doc_id = ?1 ORDER BY book_page ASC")
        .map_err(|e| PyRuntimeError::new_err(format!("prepare pages: {}", e)))?;

    let rows = stmt
        .query_map([doc_id], |row| {
            let payload: String = row.get(0)?;
            Ok(payload)
        })
        .map_err(|e| PyRuntimeError::new_err(format!("query pages: {}", e)))?;

    let mut pages = Vec::new();
    for row in rows {
        let payload = row.map_err(|e| PyRuntimeError::new_err(format!("page row: {}", e)))?;
        let page: RawPage = serde_json::from_str(&payload)
            .map_err(|e| PyRuntimeError::new_err(format!("deserialize page: {}", e)))?;
        pages.push(page);
    }
    Ok(pages)
}

/// 从 DB `documents` 表按优先级读取 TOC items。
fn load_toc_items_from_db(
    conn: &rusqlite::Connection,
    doc_id: &str,
) -> PyResult<Vec<TocItem>> {
    let columns = ["toc_auto_visual_json", "toc_auto_pdf_json", "toc_user_json"];
    for col in &columns {
        let sql = format!("SELECT {} FROM documents WHERE id = ?1", col);
        if let Ok(mut stmt) = conn.prepare(&sql) {
            let result: Result<Option<String>, _> =
                stmt.query_row([doc_id], |row| row.get(0));
            if let Ok(Some(json_str)) = result {
                let trimmed = json_str.trim();
                if !trimmed.is_empty() && trimmed != "null" {
                    if let Ok(items) = serde_json::from_str::<Vec<TocItem>>(trimmed) {
                        if !items.is_empty() {
                            return Ok(items);
                        }
                    }
                }
            }
        }
    }
    Ok(Vec::new())
}

/// 从 DB 拉页 + TOC → 跑完整 pipeline → 写 fnm_run → 返回摘要。
///
/// ←→ Python `FNM_RE/__init__.py::run_doc_pipeline`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, max_body_chars=None, start_phase="toc"))]
fn run_doc_pipeline_json(
    db_path: &str,
    doc_id: &str,
    max_body_chars: Option<i64>,
    start_phase: &str,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let conn = pool
        .get()
        .map_err(|e| PyRuntimeError::new_err(format!("get conn: {}", e)))?;

    let pages = load_raw_pages_from_db(&conn, doc_id)?;
    let page_count = pages.len();
    if page_count == 0 {
        return Err(PyRuntimeError::new_err(format!(
            "no pages found for doc_id '{}'",
            doc_id
        )));
    }
    let toc_items = load_toc_items_from_db(&conn, doc_id)?;

    let start_phase_parsed = fnm_orchestrator::types::StartPhase::from_str(start_phase)
        .map_err(|e| {
            PyRuntimeError::new_err(format!("invalid start_phase '{}': {}", start_phase, e))
        })?;
    let config = PipelineConfig {
        doc_id: doc_id.to_string(),
        slug: doc_id.to_string(),
        pdf_path: String::new(),
        toc_offset: 0,
        max_body_chars: max_body_chars.unwrap_or(6000),
        include_diagnostic_entries: false,
        manual_toc_ready: false,
        pipeline_state: "done".to_string(),
        start_phase: start_phase_parsed,
        review_overrides: None,
        visual_toc_bundle: None,
    };

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;

    let _run_count = conn
        .execute(
            "INSERT INTO fnm_runs (doc_id, status, page_count, created_at, updated_at) VALUES (?1, 'running', ?2, ?3, ?3)",
            rusqlite::params![doc_id, page_count as i64, now],
        )
        .map_err(|e| PyRuntimeError::new_err(format!("create fnm_run: {}", e)))?;
    let run_id = conn.last_insert_rowid();

    let repo = SqliteRepository::new(pool);
    let snapshot = fnm_orchestrator::mainline::run_pipeline_for_doc(
        &repo, doc_id, pages, toc_items, config, None,
    )
    .map_err(|e| PyRuntimeError::new_err(format!("pipeline: {}", e)))?;

    let section_count = snapshot
        .phase1
        .as_ref()
        .map(|p| p.chapters.len() as i64)
        .unwrap_or(0);
    let note_count = snapshot
        .phase2
        .as_ref()
        .map(|p| p.note_items.len() as i64)
        .unwrap_or(0);
    let unit_count = snapshot
        .phase4
        .as_ref()
        .map(|p| p.translation_units.len() as i64)
        .unwrap_or(0);

    let structure_state = snapshot
        .phase6
        .as_ref()
        .map(|p| p.export_audit.structure_state.clone())
        .unwrap_or_default();

    let blocking_reasons_json = serde_json::to_string(
        &snapshot
            .phase6
            .as_ref()
            .map(|p| &p.export_audit.blocking_reasons)
            .unwrap_or(&vec![]),
    )
    .unwrap_or_default();

    conn.execute(
        "UPDATE fnm_runs SET status = 'done', section_count = ?1, note_count = ?2, unit_count = ?3, structure_state = ?4, blocking_reasons_json = ?5, updated_at = ?6 WHERE id = ?7",
        rusqlite::params![section_count, note_count, unit_count, structure_state, blocking_reasons_json, now, run_id],
    )
    .map_err(|e| PyRuntimeError::new_err(format!("update fnm_run: {}", e)))?;

    let summary = serde_json::json!({
        "ok": true,
        "run_id": run_id,
        "page_count": page_count,
        "section_count": section_count,
        "note_count": note_count,
        "unit_count": unit_count,
        "structure_state": structure_state,
    });

    serde_json::to_string(&summary)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize summary: {}", e)))
}

/// 对已有 Phase1-3 数据运行 LLM repair。
///
/// 从 DB 拉 pages + phase1-3 → build unresolved clusters → 调 LLM → 物化 overrides。
///
/// ←→ Python `FNM_RE/__init__.py::run_llm_repair`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, pdf_path, renderer=None, slug="",
                   auto_apply=true, confidence_threshold=0.9, cluster_limit=None))]
fn run_llm_repair_json(
    py: Python<'_>,
    db_path: &str,
    doc_id: &str,
    pdf_path: &str,
    renderer: Option<Py<PyAny>>,
    slug: &str,
    auto_apply: bool,
    confidence_threshold: f64,
    cluster_limit: Option<usize>,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let raw_pages = {
        let conn = pool
            .get()
            .map_err(|e| PyRuntimeError::new_err(format!("get conn: {}", e)))?;
        load_raw_pages_from_db(&conn, doc_id)?
    };
    let repo = SqliteRepository::new(pool);

    let report = py.allow_threads(|| {
        let py_renderer = renderer.map(PyRepairRenderer::new);
        let noop = NoopRenderer;
        let renderer_ref: &dyn RepairImageRenderer = match &py_renderer {
            Some(r) => r,
            None => &noop,
        };

        let mut params = RunLlmRepairParams::new(
            doc_id, &repo, &raw_pages, pdf_path, renderer_ref,
        );
        params.slug = slug;
        params.auto_apply = auto_apply;
        params.confidence_threshold = confidence_threshold;
        params.cluster_limit = cluster_limit;

        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("tokio runtime");
        runtime
            .block_on(run_llm_repair(params))
            .expect("llm repair")
    });

    serde_json::to_string(&report)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 构建文档状态摘要（含 Phase4/6 gate 字段）。
///
/// ←→ Python `FNM_RE/__init__.py::build_doc_status`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, _start_phase="toc"))]
fn build_doc_status_json(
    db_path: &str,
    doc_id: &str,
    _start_phase: &str,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let phase6 = fnm_orchestrator::load_phase6_structure(&repo, doc_id, false)
        .map_err(|e| PyRuntimeError::new_err(format!("load phase6: {}", e)))?;

    let validation_json: Option<serde_json::Value> = repo
        .get_latest_fnm_run(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("get_latest_fnm_run: {}", e)))?
        .and_then(|r| {
            r.validation_json
                .and_then(|s| serde_json::from_str(&s).ok())
        });

    let toc_export_coverage = validation_json
        .as_ref()
        .and_then(|v| v.get("summary"))
        .and_then(|s| s.get("toc_export_coverage_summary"))
        .or_else(|| {
            validation_json
                .as_ref()
                .and_then(|v| v.get("toc_export_coverage_summary"))
        })
        .cloned()
        .unwrap_or(serde_json::Value::Null);

    let s = &phase6.status;
    let summary = &phase6.summary;
    let toc_export = if toc_export_coverage.is_object() {
        let obj = toc_export_coverage.as_object().unwrap();
        serde_json::json!({
            "resolved_body_items": obj.get("resolved_body_items").and_then(|v| v.as_i64()).unwrap_or(0),
            "exported_body_items": obj.get("exported_body_items").and_then(|v| v.as_i64()).unwrap_or(0),
            "missing_body_items_preview": obj.get("missing_body_items_preview")
                .and_then(|v| v.as_array())
                .map(|a| a.iter().take(8).cloned().collect::<Vec<_>>())
                .unwrap_or_default(),
        })
    } else {
        serde_json::Value::Null
    };

    fn or_empty(v: serde_json::Value) -> serde_json::Value {
        if v.is_null() || v.is_array() && v.as_array().unwrap().is_empty() {
            serde_json::Value::Object(Default::default())
        } else {
            v
        }
    }

    macro_rules! v {
        ($val:expr) => { or_empty(serde_json::to_value(&$val).unwrap_or_default()) };
    }

    let payload = serde_json::json!({
        "structure_state": &s.structure_state,
        "review_counts": v!(&s.review_counts),
        "blocking_reasons": &s.blocking_reasons,
        "link_summary": v!(&s.link_summary),
        "page_partition_summary": v!(&s.page_partition_summary),
        "chapter_mode_summary": v!(&s.chapter_mode_summary),
        "heading_review_summary": v!(&s.heading_review_summary),
        "heading_graph_summary": v!(&s.heading_graph_summary),
        "chapter_source_summary": v!(&s.chapter_source_summary),
        "visual_toc_conflict_count": s.visual_toc_conflict_count,
        "toc_export_coverage_summary": &toc_export,
        "toc_alignment_summary": v!(&s.toc_alignment_summary),
        "toc_semantic_summary": v!(&s.toc_semantic_summary),
        "toc_role_summary": v!(&s.toc_role_summary),
        "container_titles": &s.container_titles,
        "post_body_titles": &s.post_body_titles,
        "back_matter_titles": &s.back_matter_titles,
        "toc_semantic_contract_ok": s.toc_semantic_contract_ok,
        "toc_semantic_blocking_reasons": &s.toc_semantic_blocking_reasons,
        "chapter_title_alignment_ok": s.chapter_title_alignment_ok,
        "chapter_section_alignment_ok": s.chapter_section_alignment_ok,
        "chapter_endnote_region_alignment_ok": s.chapter_endnote_region_alignment_ok,
        "chapter_endnote_region_alignment_summary": v!(&s.chapter_endnote_region_alignment_summary),
        "export_drift_summary": v!(&s.export_drift_summary),
        "chapter_local_endnote_contract_ok": s.chapter_local_endnote_contract_ok,
        "export_semantic_contract_ok": s.export_semantic_contract_ok,
        "front_matter_leak_detected": s.front_matter_leak_detected,
        "toc_residue_detected": s.toc_residue_detected,
        "mid_paragraph_heading_detected": s.mid_paragraph_heading_detected,
        "duplicate_paragraph_detected": s.duplicate_paragraph_detected,
        "manual_toc_required": s.manual_toc_required,
        "manual_toc_ready": s.manual_toc_ready,
        "manual_toc_summary": v!(&s.manual_toc_summary),
        "chapter_progress_summary": v!(&s.chapter_progress_summary),
        "note_region_progress_summary": v!(&s.note_region_progress_summary),
        "chapter_binding_summary": v!(&s.chapter_binding_summary),
        "note_capture_summary": v!(&s.note_capture_summary),
        "footnote_synthesis_summary": v!(&s.footnote_synthesis_summary),
        "chapter_link_contract_summary": v!(&s.chapter_link_contract_summary),
        "book_endnote_stream_summary": v!(&s.book_endnote_stream_summary),
        "freeze_note_unit_summary": v!(&s.freeze_note_unit_summary),
        "chapter_issue_counts": v!(&s.chapter_issue_counts),
        "chapter_issue_summary": &s.chapter_issue_summary,
        "page_count": s.page_count,
        "chapter_count": s.chapter_count,
        "section_head_count": s.section_head_count,
        "review_count": s.review_count,
        "export_ready_test": s.export_ready_test,
        "export_ready_real": s.export_ready_real,
        "summary": serde_json::json!({
            "heading_review_summary": v!(&summary.heading_review_summary),
            "heading_graph_summary": v!(&summary.heading_graph_summary),
            "chapter_source_summary": v!(&summary.chapter_source_summary),
            "toc_alignment_summary": v!(&summary.toc_alignment_summary),
            "toc_semantic_summary": v!(&summary.toc_semantic_summary),
            "toc_role_summary": v!(&summary.toc_role_summary),
            "container_titles": &summary.container_titles,
            "post_body_titles": &summary.post_body_titles,
            "back_matter_titles": &summary.back_matter_titles,
            "toc_semantic_contract_ok": summary.toc_semantic_contract_ok,
            "toc_semantic_blocking_reasons": &summary.toc_semantic_blocking_reasons,
            "chapter_title_alignment_ok": summary.chapter_title_alignment_ok,
            "chapter_section_alignment_ok": summary.chapter_section_alignment_ok,
            "export_bundle_summary": v!(&summary.export_bundle_summary),
            "export_audit_summary": v!(&summary.export_audit_summary),
            "chapter_progress_summary": v!(&s.chapter_progress_summary),
            "note_region_progress_summary": v!(&s.note_region_progress_summary),
            "chapter_binding_summary": v!(&s.chapter_binding_summary),
            "note_capture_summary": v!(&s.note_capture_summary),
            "footnote_synthesis_summary": v!(&s.footnote_synthesis_summary),
            "chapter_link_contract_summary": v!(&s.chapter_link_contract_summary),
            "book_endnote_stream_summary": v!(&s.book_endnote_stream_summary),
            "freeze_note_unit_summary": v!(&s.freeze_note_unit_summary),
            "chapter_issue_counts": v!(&s.chapter_issue_counts),
            "chapter_issue_summary": &s.chapter_issue_summary,
            "export_drift_summary": v!(&s.export_drift_summary),
            "chapter_local_endnote_contract_ok": s.chapter_local_endnote_contract_ok,
            "export_semantic_contract_ok": s.export_semantic_contract_ok,
            "front_matter_leak_detected": s.front_matter_leak_detected,
            "toc_residue_detected": s.toc_residue_detected,
            "mid_paragraph_heading_detected": s.mid_paragraph_heading_detected,
            "duplicate_paragraph_detected": s.duplicate_paragraph_detected,
        }),
    });

    serde_json::to_string(&payload)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 构建重试摘要。
///
/// ←→ Python `FNM_RE/__init__.py::build_retry_summary`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id))]
fn build_retry_summary_json(
    db_path: &str,
    doc_id: &str,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let result = fnm_orchestrator::build_retry_summary(&repo, doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("build_retry_summary: {}", e)))?;

    serde_json::to_string(&result)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 构建翻译单元进度。
///
/// ←→ Python `FNM_RE/__init__.py::build_unit_progress`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, snapshot_json=None, use_lightweight=false))]
fn build_unit_progress_json(
    db_path: &str,
    doc_id: &str,
    snapshot_json: Option<&str>,
    use_lightweight: bool,
) -> PyResult<String> {
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let result = fnm_orchestrator::build_unit_progress(&repo, doc_id, snapshot_json, use_lightweight)
        .map_err(|e| PyRuntimeError::new_err(format!("build_unit_progress: {}", e)))?;

    serde_json::to_string(&result)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 准备翻译任务（页级）。
///
/// 返回 JSON 数组 `[ctx, jobs, meta]`，Python wrapper 端 unpack 为 tuple。
///
/// ←→ Python `FNM_RE/__init__.py::prepare_page_translate_jobs`
#[pyfunction]
#[pyo3(signature = (pages_json, target_bp, t_args_json, doc_id, db_path))]
fn prepare_page_translate_jobs_json(
    pages_json: &str,
    target_bp: i64,
    t_args_json: &str,
    doc_id: &str,
    db_path: &str,
) -> PyResult<String> {
    let _ = t_args_json; // 透传，当前暂不解析 model args
    let pages: Vec<RawPage> = serde_json::from_str(pages_json)
        .map_err(|e| PyRuntimeError::new_err(format!("parse pages_json: {}", e)))?;

    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let result = fnm_orchestrator::prepare_page_translate_jobs(&pages, target_bp, doc_id, &repo)
        .map_err(|e| PyRuntimeError::new_err(format!("prepare_page_translate_jobs: {}", e)))?;

    serde_json::to_string(&result)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 翻译后导出检查 + 自修复循环。
///
/// ←→ Python `FNM_RE/__init__.py::run_post_translate_export_checks_for_doc`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, slug, pdf_path, model_args_json, max_repair_rounds=3))]
fn run_post_translate_export_checks_for_doc_json(
    db_path: &str,
    doc_id: &str,
    slug: &str,
    pdf_path: &str,
    model_args_json: &str,
    max_repair_rounds: i64,
) -> PyResult<String> {
    let slug = if slug.is_empty() { doc_id } else { slug };
    let pool = open_pool(Path::new(db_path))
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool.clone());

    // Load pages from DB via inline SQL
    let pages = {
        let conn = pool
            .get()
            .map_err(|e| PyRuntimeError::new_err(format!("get conn: {}", e)))?;
        let mut stmt = conn
            .prepare("SELECT payload_json FROM pages WHERE doc_id = ?1 ORDER BY book_page ASC")
            .map_err(|e| PyRuntimeError::new_err(format!("prepare pages: {}", e)))?;
        let rows = stmt
            .query_map([doc_id], |row| {
                let payload: String = row.get(0)?;
                Ok(payload)
            })
            .map_err(|e| PyRuntimeError::new_err(format!("query pages: {}", e)))?;
        let mut pages = Vec::new();
        for row in rows {
            let payload = row.map_err(|e| PyRuntimeError::new_err(format!("page row: {}", e)))?;
            let page: RawPage = serde_json::from_str(&payload)
                .map_err(|e| PyRuntimeError::new_err(format!("parse page: {}", e)))?;
            pages.push(page);
        }
        pages
    };

    let result = fnm_orchestrator::run_post_translate_export_checks(
        &repo,
        doc_id,
        slug,
        &pages,
        pdf_path,
        model_args_json,
        max_repair_rounds,
    )
    .map_err(|e| PyRuntimeError::new_err(format!("post_translate_export_check: {}", e)))?;

    serde_json::to_string(&result)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 压缩序列化 page_segments 列表（JSON 入/出）。
///
/// ←→ Python `FNM_RE/shared/segment_codec.py::serialize_segments`
#[pyfunction]
fn serialize_segments_json(segments_json: &str) -> PyResult<String> {
    let segments: Vec<serde_json::Value> = serde_json::from_str(segments_json)
        .map_err(|e| PyValueError::new_err(format!("invalid segments_json: {}", e)))?;
    let result = fnm_core::segment_codec::serialize_segments(&segments);
    serde_json::to_string(&result)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 反序列化 page_segments 列表为完整 dict（JSON 入/出）。
///
/// ←→ Python `FNM_RE/shared/segment_codec.py::deserialize_segments_to_dicts`
#[pyfunction]
fn deserialize_segments_to_dicts_json(payload: &str) -> PyResult<String> {
    let raw: Vec<serde_json::Value> = serde_json::from_str(payload)
        .map_err(|e| PyValueError::new_err(format!("invalid payload_json: {}", e)))?;
    let result = fnm_core::segment_codec::deserialize_segments_to_dicts(&raw);
    serde_json::to_string(&result)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 获取 crate 版本（供 Python 端验证 wheel 安装正确）。
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Python 模块入口。
#[pymodule]
fn fnm_re_rs(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_pipeline_json, m)?)?;
    m.add_function(wrap_pyfunction!(run_pipeline_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(run_pipeline_for_doc_with_llm_repair_json, m)?)?;
    m.add_function(wrap_pyfunction!(load_doc_structure_json, m)?)?;
    m.add_function(wrap_pyfunction!(audit_export_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(build_export_bundle_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(build_export_zip_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(list_diagnostic_entries_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(list_diagnostic_notes_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(get_diagnostic_entry_for_page_json, m)?)?;
    m.add_function(wrap_pyfunction!(run_doc_pipeline_json, m)?)?;
    m.add_function(wrap_pyfunction!(run_llm_repair_json, m)?)?;
    m.add_function(wrap_pyfunction!(build_doc_status_json, m)?)?;
    m.add_function(wrap_pyfunction!(build_unit_progress_json, m)?)?;
    m.add_function(wrap_pyfunction!(prepare_page_translate_jobs_json, m)?)?;
    m.add_function(wrap_pyfunction!(run_post_translate_export_checks_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(build_retry_summary_json, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_segments_json, m)?)?;
    m.add_function(wrap_pyfunction!(deserialize_segments_to_dicts_json, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    Ok(())
}

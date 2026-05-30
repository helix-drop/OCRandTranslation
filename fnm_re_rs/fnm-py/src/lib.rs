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
use pyo3::types::PyBytes;

use fnm_core::db::{Repository, SqliteRepository};
use fnm_llm_repair::page_context::{NoopRenderer, RepairImageRenderer};
use fnm_llm_repair::run::{run_llm_repair, RunLlmRepairParams};
use fnm_orchestrator::mainline::LlmRepairOptions;
use fnm_orchestrator::types::PipelineConfig;
use fnm_phase1::input::{RawPage, TocItem};

mod helpers;
mod translate;

/// 进程级连接池缓存：按 db_path 复用池，避免每个 pyfunction 调用都新建池 + 跑 migrations。
/// 与 B1-3 的 `with_init(foreign_keys)` 协同——池缓存后 FK 设置只需正确一次。
fn get_or_create_pool(db_path: &str) -> Result<fnm_core::db::SqlitePool, String> {
    use std::collections::HashMap;
    use std::sync::Mutex;

    static POOL_CACHE: once_cell::sync::Lazy<Mutex<HashMap<String, fnm_core::db::SqlitePool>>> =
        once_cell::sync::Lazy::new(|| Mutex::new(HashMap::new()));

    let mut cache = POOL_CACHE.lock().map_err(|e| format!("pool cache lock: {e}"))?;
    if let Some(pool) = cache.get(db_path) {
        return Ok(pool.clone());
    }
    let pool = fnm_core::db::open_pool(Path::new(db_path)).map_err(|e| format!("open_pool: {e}"))?;
    cache.insert(db_path.to_string(), pool.clone());
    Ok(pool)
}

use helpers::{parse_pipeline_config, PyRepairRenderer};
pub use translate::*;

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

    let pool = get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let snapshot =
        fnm_orchestrator::run_pipeline_for_doc(&repo, doc_id, pages, toc_items, config, None)
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
/// `config_json` 必须包含 `doc_id`/`slug`/`pdf_path`，以及可选的 `pages`/`toc_items` 字段。
/// 当 `pages`/`toc_items` 存在时，优先使用 config 内的值而非单独的 JSON 参数。
///
/// ←→ Python `FNM_RE/modules/llm_repair.py::run_llm_repair` 嵌入式调用
#[pyfunction]
#[pyo3(signature = (db_path, config_json, renderer=None, auto_apply=true, confidence_threshold=0.9))]
fn run_pipeline_for_doc_with_llm_repair_json(
    py: Python<'_>,
    db_path: &str,
    config_json: &str,
    renderer: Option<Py<PyAny>>,
    auto_apply: bool,
    confidence_threshold: f64,
) -> PyResult<String> {
    let config_value: serde_json::Value = serde_json::from_str(config_json)
        .map_err(|e| PyValueError::new_err(format!("invalid config_json: {}", e)))?;
    let config = parse_pipeline_config(&config_value)?;

    let pages: Vec<RawPage> = serde_json::from_value(
        config_value
            .get("pages")
            .cloned()
            .unwrap_or(serde_json::json!([])),
    )
    .map_err(|e| PyValueError::new_err(format!("invalid pages in config: {}", e)))?;
    let toc_items: Vec<TocItem> = serde_json::from_value(
        config_value
            .get("toc_items")
            .cloned()
            .unwrap_or(serde_json::json!([])),
    )
    .map_err(|e| PyValueError::new_err(format!("invalid toc_items in config: {}", e)))?;
    let pdf_path = config_value
        .get("pdf_path")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    let doc_id = config.doc_id.clone();

    let pool = get_or_create_pool(db_path)
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
            pdf_path: &pdf_path,
            auto_apply,
            confidence_threshold,
        };
        fnm_orchestrator::run_pipeline_for_doc(
            &repo,
            &doc_id,
            pages,
            toc_items,
            config,
            Some(llm_opts),
        )
    });
    let snapshot =
        snapshot_result.map_err(|e| PyRuntimeError::new_err(format!("pipeline error: {}", e)))?;

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
    let pool = get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let structure =
        fnm_orchestrator::load_phase6_structure(&repo, doc_id, include_diagnostic_entries)
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
    let pool = get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);
    let slug = if slug.is_empty() { doc_id } else { slug };

    let phase6 = fnm_orchestrator::load_phase6_structure(&repo, doc_id, false)
        .map_err(|e| PyRuntimeError::new_err(format!("load_phase6_structure: {}", e)))?;

    let payload: Option<Vec<u8>> = if let Some(bytes) = zip_bytes {
        Some(bytes.to_vec())
    } else if let Some(path_str) = zip_path {
        let p = Path::new(path_str);
        if path_str.is_empty() {
            None
        } else if p.exists() {
            Some(
                std::fs::read(p)
                    .map_err(|e| PyRuntimeError::new_err(format!("read zip file: {}", e)))?,
            )
        } else {
            return Err(PyRuntimeError::new_err(format!(
                "zip_path does not exist: {}",
                path_str
            )));
        }
    } else {
        None
    };

    let (report, _summary) =
        fnm_phase6::export_audit::audit_phase6_export(&phase6, slug, doc_id, payload.as_deref());

    serde_json::to_string(&report).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 从 DB 读取 export bundle 记录。
///
/// 返回 ExportBundleRecord JSON 字符串，含 chapters / chapter_files / files / contract_ok 等字段。
///
/// bundle 不存在时抛出 PyRuntimeError。
///
/// ←→ Python `FNM_RE/__init__.py::build_export_bundle_for_doc`
#[pyfunction]
fn build_export_bundle_for_doc_json(db_path: &str, doc_id: &str) -> PyResult<String> {
    let pool = get_or_create_pool(db_path)
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

    serde_json::to_string(&bundle).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 从 DB 读取 export bundle 并构建 ZIP 字节。
///
/// 返回 ZIP 文件二进制字节（PyBytes）。
///
/// ←→ Python `FNM_RE/__init__.py::build_export_zip_for_doc`
#[pyfunction]
fn build_export_zip_for_doc_json(py: Python, db_path: &str, doc_id: &str) -> PyResult<Py<PyBytes>> {
    let pool = get_or_create_pool(db_path)
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

    let zip_bytes = fnm_phase6::build_export_zip(&bundle)
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
    let pool = get_or_create_pool(db_path)
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
    let pool = get_or_create_pool(db_path)
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
fn list_diagnostic_notes_for_doc_json(db_path: &str, doc_id: &str) -> PyResult<String> {
    let pool = get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let notes = repo
        .list_fnm_diagnostic_notes(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("list_fnm_diagnostic_notes: {}", e)))?;

    serde_json::to_string(&notes).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 从 DB `pages` 表读取 RawPage 列表。
/// 从 DB 按优先级加载 TOC items（用户 > 视觉 > PDF）。
///
/// 优先级验证的关键入口：结果顺序反映 column 优先级。
///
/// ←→ M3.4: thin pyfunction wrapper for `Repository::load_toc_items_for_doc`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id))]
fn load_toc_items_for_doc_json(db_path: &str, doc_id: &str) -> PyResult<String> {
    let pool = get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);
    let items = repo
        .load_toc_items_for_doc(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("load toc: {}", e)))?;
    serde_json::to_string(&items).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 从 DB 拉页 + TOC → 跑完整 pipeline → 写 fnm_run → 返回摘要。
///
/// ←→ Python `FNM_RE/__init__.py::run_doc_pipeline`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, max_body_chars=None, start_phase="toc", config_json=None))]
fn run_doc_pipeline_json(
    db_path: &str,
    doc_id: &str,
    max_body_chars: Option<i64>,
    start_phase: &str,
    config_json: Option<&str>,
) -> PyResult<String> {
    let pool = get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let start_phase_parsed: fnm_orchestrator::StartPhase = start_phase.parse().map_err(|e| {
        PyRuntimeError::new_err(format!("invalid start_phase '{}': {}", start_phase, e))
    })?;

    let mut config = PipelineConfig {
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
        skip_sup_recovery: true,
        skip_llm_verify: true,
    };

    if let Some(json_str) = config_json {
        if !json_str.is_empty() {
            let extra: serde_json::Value = serde_json::from_str(json_str)
                .map_err(|e| PyValueError::new_err(format!("invalid config_json: {}", e)))?;
            if let Some(v) = extra.get("pdf_path").and_then(|v| v.as_str()) {
                if !v.is_empty() {
                    config.pdf_path = v.to_string();
                }
            }
            if let Some(v) = extra.get("slug").and_then(|v| v.as_str()) {
                if !v.is_empty() {
                    config.slug = v.to_string();
                }
            }
            if let Some(v) = extra
                .get("include_diagnostic_entries")
                .and_then(|v| v.as_bool())
            {
                config.include_diagnostic_entries = v;
            }
            if let Some(v) = extra.get("toc_offset").and_then(|v| v.as_i64()) {
                config.toc_offset = v;
            }
            if let Some(v) = extra.get("manual_toc_ready").and_then(|v| v.as_bool()) {
                config.manual_toc_ready = v;
            }
            if let Some(v) = extra.get("pipeline_state").and_then(|v| v.as_str()) {
                config.pipeline_state = v.to_string();
            }
            config.review_overrides = extra.get("review_overrides").cloned();
            config.visual_toc_bundle = extra.get("visual_toc_bundle").cloned();
            if let Some(v) = extra.get("skip_sup_recovery").and_then(|v| v.as_bool()) {
                config.skip_sup_recovery = v;
            }
            if let Some(v) = extra.get("skip_llm_verify").and_then(|v| v.as_bool()) {
                config.skip_llm_verify = v;
            }
        }
    }

    // run_pipeline_from_db 负责 create/update fnm_run（含错误路径）
    let snapshot = fnm_orchestrator::mainline::run_pipeline_from_db(&repo, doc_id, config, None)
        .map_err(|e| PyRuntimeError::new_err(format!("pipeline: {}", e)))?;

    let page_count = repo
        .load_raw_pages_for_doc(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("load pages for summary: {}", e)))?
        .len();

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
    let blocking_reasons: Vec<String> = snapshot
        .phase6
        .as_ref()
        .map(|p| p.export_audit.blocking_reasons.clone())
        .unwrap_or_default();

    let run = repo
        .get_latest_fnm_run(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("get fnm_run: {}", e)))?
        .ok_or_else(|| PyRuntimeError::new_err("no fnm_run found after pipeline"))?;

    let summary = serde_json::json!({
        "ok": true,
        "run_id": run.id,
        "page_count": page_count,
        "section_count": section_count,
        "note_count": note_count,
        "unit_count": unit_count,
        "structure_state": structure_state,
        "blocking_reasons": blocking_reasons,
    });

    serde_json::to_string(&summary)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize summary: {}", e)))
}

/// 对已验收的持久化 Phase 1-3 仅回放 Phase 4-6，不调用任何模型。
///
/// ←→ Stage 5 下游集成验收入口。
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, slug="", max_body_chars=6000))]
fn replay_phase4_to6_json(
    db_path: &str,
    doc_id: &str,
    slug: &str,
    max_body_chars: i64,
) -> PyResult<String> {
    let pool = get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);
    let config = PipelineConfig {
        doc_id: doc_id.to_string(),
        slug: if slug.is_empty() {
            doc_id.to_string()
        } else {
            slug.to_string()
        },
        max_body_chars,
        start_phase: fnm_orchestrator::StartPhase::Toc,
        skip_sup_recovery: true,
        skip_llm_verify: true,
        pipeline_state: "downstream_replay".to_string(),
        ..Default::default()
    };
    let snapshot = fnm_orchestrator::replay_phase4_to6_from_db(&repo, doc_id, config)
        .map_err(|e| PyRuntimeError::new_err(format!("downstream replay: {}", e)))?;
    let phase4 = snapshot
        .phase4
        .as_ref()
        .ok_or_else(|| PyRuntimeError::new_err("downstream replay produced no phase4 output"))?;
    let phase6 = snapshot
        .phase6
        .as_ref()
        .ok_or_else(|| PyRuntimeError::new_err("downstream replay produced no phase6 output"))?;
    let result = serde_json::json!({
        "ok": true,
        "doc_id": doc_id,
        "slug": snapshot.slug,
        "pipeline_run_id": snapshot.pipeline_run_id,
        "unit_count": phase4.translation_units.len(),
        "review_count": phase4.structure_reviews.len(),
        "structure_state": phase6.export_audit.structure_state,
        "can_ship": phase6.export_audit.can_ship,
        "blocking_reasons": phase6.export_audit.blocking_reasons,
        "model_requests": 0,
    });
    serde_json::to_string(&result)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize summary: {}", e)))
}

/// 对已有 Phase1-3 数据运行 LLM repair。
///
/// 从 DB 拉 pages + phase1-3 → build unresolved clusters → 调 LLM → 物化 overrides。
///
/// `options_json` 可选字段：`slug`/`auto_apply`/`confidence_threshold`/`cluster_limit`/`trace_callback`。
///
/// ←→ Python `FNM_RE/__init__.py::run_llm_repair`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id, pdf_path, renderer=None, options_json=None, trace_callback=None))]
fn run_llm_repair_json(
    py: Python<'_>,
    db_path: &str,
    doc_id: &str,
    pdf_path: &str,
    renderer: Option<Py<PyAny>>,
    options_json: Option<&str>,
    trace_callback: Option<Py<PyAny>>,
) -> PyResult<String> {
    let opts: serde_json::Value = options_json
        .map(serde_json::from_str)
        .transpose()
        .map_err(|e| PyValueError::new_err(format!("invalid options_json: {}", e)))?
        .unwrap_or(serde_json::json!({}));

    let slug = opts
        .get("slug")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let auto_apply = opts
        .get("auto_apply")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let confidence_threshold = opts
        .get("confidence_threshold")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.9);
    let cluster_limit = opts
        .get("cluster_limit")
        .and_then(|v| v.as_u64())
        .map(|v| v as usize);

    let pool = get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);
    let raw_pages = repo
        .load_raw_pages_for_doc(doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("load pages: {}", e)))?;

    let py_renderer = renderer.map(PyRepairRenderer::new);
    let report = py
        .allow_threads(|| -> Result<_, String> {
            let noop = NoopRenderer;
            let renderer_ref: &dyn RepairImageRenderer = match &py_renderer {
                Some(ref r) => r,
                None => &noop,
            };
            let trace_bridge = |trace: serde_json::Value| -> Result<(), String> {
                let Some(callback) = &trace_callback else {
                    return Ok(());
                };
                Python::with_gil(|py| {
                    let trace_json = serde_json::to_string(&trace)
                        .map_err(|e| format!("serialize trace: {}", e))?;
                    let json_mod = py
                        .import_bound("json")
                        .map_err(|e| format!("import json: {}", e))?;
                    let trace_obj = json_mod
                        .call_method1("loads", (trace_json,))
                        .map_err(|e| format!("json.loads: {}", e))?;
                    callback
                        .call1(py, (trace_obj,))
                        .map_err(|e| format!("callback: {}", e))?;
                    Ok(())
                })
            };

            let mut params =
                RunLlmRepairParams::new(doc_id, &repo, &raw_pages, pdf_path, renderer_ref);
            params.slug = &slug;
            params.auto_apply = auto_apply;
            params.confidence_threshold = confidence_threshold;
            params.cluster_limit = cluster_limit;
            if trace_callback.is_some() {
                params.trace_callback = Some(&trace_bridge);
            }

            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(|e| format!("tokio runtime: {e}"))?;
            runtime
                .block_on(run_llm_repair(params))
                .map_err(|e| format!("llm repair: {e}"))
        })
        .map_err(PyRuntimeError::new_err)?;

    let mut report_value = serde_json::to_value(&report)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))?;

    // 注入 renderer 错误（P1-7）
    let errors: Vec<String> = py_renderer
        .as_ref()
        .map(|r| r.take_errors())
        .unwrap_or_default();
    if !errors.is_empty() {
        report_value["renderer_errors"] =
            serde_json::Value::Array(errors.into_iter().map(serde_json::Value::String).collect());
    }

    serde_json::to_string(&report_value)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 构建文档状态摘要（含 Phase4/6 gate 字段）。
///
/// 构建文档状态 JSON。
///
/// ←→ Python `FNM_RE/__init__.py::build_doc_status`
#[pyfunction]
#[pyo3(signature = (db_path, doc_id))]
fn build_doc_status_json(db_path: &str, doc_id: &str) -> PyResult<String> {
    let pool = get_or_create_pool(db_path)
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
        ($val:expr) => {
            or_empty(serde_json::to_value(&$val).unwrap_or_default())
        };
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
fn build_retry_summary_json(db_path: &str, doc_id: &str) -> PyResult<String> {
    let pool = get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let result = fnm_orchestrator::build_retry_summary(&repo, doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("build_retry_summary: {}", e)))?;

    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
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
    let pool = get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = SqliteRepository::new(pool);

    let result =
        fnm_orchestrator::build_unit_progress(&repo, doc_id, snapshot_json, use_lightweight)
            .map_err(|e| PyRuntimeError::new_err(format!("build_unit_progress: {}", e)))?;

    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
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
    let pool = get_or_create_pool(db_path)
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

    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 将全局 USAGE_RECORDS 逐条写入 llm_traces/ 目录。
///
/// ←→ Python `FNM_RE/shared/token_counter.py::dump_traces`
#[pyfunction]
#[pyo3(signature = (example_dir, doc_id=""))]
fn dump_traces_json(example_dir: &str, doc_id: &str) -> PyResult<i64> {
    fnm_llm_repair::trace::dump::dump_traces(example_dir, doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("dump_traces: {}", e)))
}

/// 将 usage_summary 按阶段写入 llm_traces/ 目录。
///
/// ←→ Python `FNM_RE/shared/token_counter.py::write_summary_traces`
#[pyfunction]
fn write_summary_traces_json(example_dir: &str, usage_summary_json: &str) -> PyResult<String> {
    let usage_summary: serde_json::Value = serde_json::from_str(usage_summary_json)
        .map_err(|e| PyValueError::new_err(format!("invalid usage_summary_json: {}", e)))?;
    let written =
        fnm_llm_repair::trace::dump::write_summary_traces(example_dir, &usage_summary, "")
            .map_err(|e| PyRuntimeError::new_err(format!("write_summary_traces: {}", e)))?;
    serde_json::to_string(&serde_json::json!({"written": written}))
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 检测 markdown 中是否已有 marker 的显式上标格式。
///
/// ←→ Python `FNM_RE/modules/sup_recovery.py::_has_marker`
#[pyfunction]
fn has_explicit_sup_json(markdown: &str, marker: &str) -> bool {
    fnm_phase2::sup_recovery::has_explicit_sup(markdown, marker)
}

/// 恢复入口：pages + pdf_path + chapter_markers → 恢复缺失上标。
///
/// `chapter_markers_json` 必须提供逐章 marker map（格式：`{"ch-1": ["1","2"], ...}`）。
///
/// ←→ Python `FNM_RE/modules/sup_recovery.py::recover_book_chapter_scoped`
#[pyfunction]
#[pyo3(signature = (pages_json, pdf_path, chapter_markers_json))]
fn recover_book_json(
    pages_json: &str,
    pdf_path: &str,
    chapter_markers_json: &str,
) -> PyResult<String> {
    let pages: Vec<fnm_phase1::input::RawPage> = serde_json::from_str(pages_json)
        .map_err(|e| PyValueError::new_err(format!("invalid pages_json: {}", e)))?;

    let chapter_markers: std::collections::HashMap<String, Vec<String>> =
        serde_json::from_str(chapter_markers_json)
            .map_err(|e| PyValueError::new_err(format!("invalid chapter_markers_json: {}", e)))?;

    let pdf_opt = if pdf_path.is_empty() {
        None
    } else {
        Some(pdf_path)
    };
    let result = fnm_phase2::sup_recovery::recover_book_chapter_scoped(
        &pages,
        &chapter_markers,
        pdf_opt,
        None, // no vision config
    );

    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 提取正文段落列表。
///
/// ←→ Python `FNM_RE/stages/export_audit.py::body_paragraphs`
#[pyfunction]
fn body_paragraphs_json(markdown: &str) -> PyResult<String> {
    let result = fnm_phase6::export_audit::helpers::body_paragraphs(markdown);
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 提取定义行列表。
///
/// ←→ Python `FNM_RE/stages/export_audit.py::definition_lines`
#[pyfunction]
fn definition_lines_json(markdown: &str) -> PyResult<String> {
    let result = fnm_phase6::export_audit::helpers::definition_lines(markdown);
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 分离正文和定义块。
///
/// ←→ Python `FNM_RE/stages/export_audit.py::split_body_and_definitions`
#[pyfunction]
fn split_body_and_definitions_json(markdown: &str) -> PyResult<String> {
    let (body, defs) = fnm_phase6::export_audit::helpers::split_body_and_definitions(markdown);
    let result = vec![body, defs];
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 解析主模型参数（取 fnm pool 第一个 spec）。
///
/// ←→ Python `FNM_RE/modules/llm_repair.py::_resolve_repair_model_args`
#[pyfunction]
fn resolve_repair_model_args_json() -> PyResult<String> {
    let args = fnm_llm_repair::llm_client::resolve_repair_model_args()
        .map_err(|e| PyRuntimeError::new_err(format!("resolve_repair_model_args: {}", e)))?;
    serde_json::to_string(&args).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 渲染 PDF 单页为 data:image/jpeg;base64,... data URL。
///
/// ←→ Python `FNM_RE/modules/pdf_render_subprocess.py::render_repair_page_data_url`
#[pyfunction]
#[pyo3(signature = (pdf_path, page_index, scale=1.3))]
fn render_repair_page_data_url_json(
    pdf_path: &str,
    page_index: i64,
    scale: f64,
) -> PyResult<String> {
    fnm_core::vision::pdfium::render_page_to_data_url(pdf_path, page_index, scale)
        .map_err(|e| PyRuntimeError::new_err(format!("render_page: {}", e)))
}

/// Python 模块入口。
#[pymodule]
fn fnm_re_rs(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_pipeline_json, m)?)?;
    m.add_function(wrap_pyfunction!(run_pipeline_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(
        run_pipeline_for_doc_with_llm_repair_json,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(load_doc_structure_json, m)?)?;
    m.add_function(wrap_pyfunction!(audit_export_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(build_export_bundle_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(build_export_zip_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(list_diagnostic_entries_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(list_diagnostic_notes_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(get_diagnostic_entry_for_page_json, m)?)?;
    m.add_function(wrap_pyfunction!(load_toc_items_for_doc_json, m)?)?;
    m.add_function(wrap_pyfunction!(run_doc_pipeline_json, m)?)?;
    m.add_function(wrap_pyfunction!(replay_phase4_to6_json, m)?)?;
    m.add_function(wrap_pyfunction!(run_llm_repair_json, m)?)?;
    m.add_function(wrap_pyfunction!(build_doc_status_json, m)?)?;
    m.add_function(wrap_pyfunction!(build_unit_progress_json, m)?)?;
    m.add_function(wrap_pyfunction!(prepare_page_translate_jobs_json, m)?)?;
    m.add_function(wrap_pyfunction!(
        run_post_translate_export_checks_for_doc_json,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(build_retry_summary_json, m)?)?;
    m.add_function(wrap_pyfunction!(dump_traces_json, m)?)?;
    m.add_function(wrap_pyfunction!(write_summary_traces_json, m)?)?;
    m.add_function(wrap_pyfunction!(has_explicit_sup_json, m)?)?;
    m.add_function(wrap_pyfunction!(recover_book_json, m)?)?;
    m.add_function(wrap_pyfunction!(body_paragraphs_json, m)?)?;
    m.add_function(wrap_pyfunction!(definition_lines_json, m)?)?;
    m.add_function(wrap_pyfunction!(split_body_and_definitions_json, m)?)?;
    m.add_function(wrap_pyfunction!(replace_frozen_refs_json, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_segments_json, m)?)?;
    m.add_function(wrap_pyfunction!(deserialize_segments_to_dicts_json, m)?)?;
    m.add_function(wrap_pyfunction!(format_fnm_unit_label_json, m)?)?;
    m.add_function(wrap_pyfunction!(format_fnm_unit_pages_json, m)?)?;
    m.add_function(wrap_pyfunction!(collect_fnm_unit_failed_locations_json, m)?)?;
    m.add_function(wrap_pyfunction!(list_fnm_units_with_indices_json, m)?)?;
    m.add_function(wrap_pyfunction!(sync_fnm_retry_state_json, m)?)?;
    m.add_function(wrap_pyfunction!(
        rebuild_fnm_diagnostic_page_entries_json,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(build_fnm_body_unit_jobs_json, m)?)?;
    m.add_function(wrap_pyfunction!(apply_body_unit_translations_json, m)?)?;
    m.add_function(wrap_pyfunction!(apply_body_unit_entry_result_json, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_repair_model_args_json, m)?)?;
    m.add_function(wrap_pyfunction!(render_repair_page_data_url_json, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    Ok(())
}

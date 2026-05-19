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
use pyo3::types::PyTuple;

use fnm_core::db::{open_pool, SqliteRepository};
use fnm_llm_repair::page_context::{NoopRenderer, RepairImageRenderer};
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
    m.add_function(wrap_pyfunction!(version, m)?)?;
    Ok(())
}

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

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

use fnm_orchestrator::types::PipelineConfig;
use fnm_phase1::input::{RawPage, TocItem};

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

/// 获取 crate 版本（供 Python 端验证 wheel 安装正确）。
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Python 模块入口。
#[pymodule]
fn fnm_re_rs(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_pipeline_json, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    Ok(())
}

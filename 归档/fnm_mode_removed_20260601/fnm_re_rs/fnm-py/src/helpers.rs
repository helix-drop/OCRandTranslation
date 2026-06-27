//! 辅助结构和函数：PyRepairRenderer + parse_pipeline_config。

use std::sync::{Arc, Mutex};

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyTuple;

use fnm_llm_repair::page_context::RepairImageRenderer;
use fnm_orchestrator::types::PipelineConfig;

/// 包装 Python callable 实现 `RepairImageRenderer`。
///
/// Python 端签名：`(pdf_path: str, file_idx: int) -> Optional[str]`
/// 返回 `data:image/...;base64,...` 形式的 URL 或 None。
///
/// 错误先收集到 `errors`，不 panic（P1-7）。
pub(crate) struct PyRepairRenderer {
    callback: Py<PyAny>,
    errors: Arc<Mutex<Vec<String>>>,
}

impl PyRepairRenderer {
    pub(crate) fn new(callback: Py<PyAny>) -> Self {
        Self {
            callback,
            errors: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub(crate) fn take_errors(&self) -> Vec<String> {
        std::mem::take(&mut *self.errors.lock().unwrap())
    }
}

impl RepairImageRenderer for PyRepairRenderer {
    fn render_page_data_url(&self, pdf_path: &str, file_idx: i64) -> Option<String> {
        Python::with_gil(|py| -> Option<String> {
            let args = PyTuple::new_bound(py, &[pdf_path.into_py(py), file_idx.into_py(py)]);
            match self.callback.call1(py, args) {
                Ok(result) => result.extract::<Option<String>>(py).ok().flatten(),
                Err(e) => {
                    let msg = format!(
                        "renderer callback failed for page {}: {}",
                        file_idx,
                        e.value_bound(py)
                            .str()
                            .map(|s| s.to_string())
                            .unwrap_or_default(),
                    );
                    self.errors.lock().unwrap().push(msg);
                    None
                }
            }
        })
    }
}

pub(crate) fn parse_pipeline_config(value: &serde_json::Value) -> PyResult<PipelineConfig> {
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

    let start_phase: fnm_orchestrator::StartPhase = get_str("start_phase")
        .parse()
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
        skip_sup_recovery: obj
            .get("skip_sup_recovery")
            .and_then(|v| v.as_bool())
            .unwrap_or(true),
        skip_llm_verify: obj
            .get("skip_llm_verify")
            .and_then(|v| v.as_bool())
            .unwrap_or(true),
    })
}

//! 页面翻译相关 pyfunctions：unit 管理、格式化、retry、段级任务。

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

/// 获取 crate 版本（供 Python 端验证 wheel 安装正确）。
#[pyfunction]
pub fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// 准备翻译任务（页级）。
///
/// 返回 JSON 数组 `[ctx, jobs, meta]`，Python wrapper 端 unpack 为 tuple。
///
/// ←→ Python `FNM_RE/__init__.py::prepare_page_translate_jobs`
#[pyfunction]
#[pyo3(signature = (pages_json, target_bp, t_args_json, doc_id, db_path))]
pub fn prepare_page_translate_jobs_json(
    pages_json: &str,
    target_bp: i64,
    t_args_json: &str,
    doc_id: &str,
    db_path: &str,
) -> PyResult<String> {
    // t_args_json 当前暂不解析 model args，但保留在签名中供 Python 端透传。
    // 用 `_t_args_json` 前缀（而非 `let _ = …`）确保 PyO3 仍按 signature 接收实参。
    let _t_args_json = t_args_json;
    let pages: Vec<fnm_phase1::input::RawPage> = serde_json::from_str(pages_json)
        .map_err(|e| PyRuntimeError::new_err(format!("parse pages_json: {}", e)))?;

    let pool = super::get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db pool: {}", e)))?;
    let repo = fnm_core::db::SqliteRepository::new(pool);

    let result = fnm_orchestrator::prepare_page_translate_jobs(&pages, target_bp, doc_id, &repo)
        .map_err(|e| PyRuntimeError::new_err(format!("prepare_page_translate_jobs: {}", e)))?;

    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 格式化 unit 标签（纯 JSON dict 入/出）。
///
/// ←→ Python `FNM_RE/app/page_translate.py::format_fnm_unit_label`
#[pyfunction]
pub fn format_fnm_unit_label_json(unit_json: &str) -> PyResult<String> {
    let unit: serde_json::Value = serde_json::from_str(unit_json)
        .map_err(|e| PyValueError::new_err(format!("invalid unit_json: {}", e)))?;
    let label = fnm_orchestrator::format_unit_label_value(&unit);
    Ok(label)
}

/// 格式化 unit 页码范围（纯 JSON dict 入/出）。
///
/// ←→ Python `FNM_RE/app/page_translate.py::format_fnm_unit_pages`
#[pyfunction]
pub fn format_fnm_unit_pages_json(unit_json: &str) -> PyResult<String> {
    let unit: serde_json::Value = serde_json::from_str(unit_json)
        .map_err(|e| PyValueError::new_err(format!("invalid unit_json: {}", e)))?;
    let pages = fnm_orchestrator::format_unit_pages_value(&unit);
    Ok(pages)
}

/// 收集 unit 内失败段落位置（纯 JSON dict 入/出）。
///
/// ←→ Python `FNM_RE/app/page_translate.py::collect_fnm_unit_failed_locations`
#[pyfunction]
pub fn collect_fnm_unit_failed_locations_json(unit_json: &str) -> PyResult<String> {
    let unit: serde_json::Value = serde_json::from_str(unit_json)
        .map_err(|e| PyValueError::new_err(format!("invalid unit_json: {}", e)))?;
    let locations = fnm_orchestrator::collect_unit_failed_locations_value(&unit);
    serde_json::to_string(&locations)
        .map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 列出所有翻译单元（DB 驱动）。
///
/// ←→ Python `FNM_RE/app/page_translate.py::list_fnm_units_with_indices`
#[pyfunction]
pub fn list_fnm_units_with_indices_json(db_path: &str, doc_id: &str) -> PyResult<String> {
    let pool = super::get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db: {}", e)))?;
    let repo = fnm_core::db::SqliteRepository::new(pool);
    let result = fnm_orchestrator::list_fnm_units_with_indices(&repo, doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("list_fnm_units_with_indices: {}", e)))?;
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 同步 retry 状态（返回 retry summary）。
///
/// ←→ Python `FNM_RE/app/page_translate.py::sync_fnm_retry_state`
#[pyfunction]
pub fn sync_fnm_retry_state_json(db_path: &str, doc_id: &str) -> PyResult<String> {
    let pool = super::get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db: {}", e)))?;
    let repo = fnm_core::db::SqliteRepository::new(pool);
    let result = fnm_orchestrator::sync_fnm_retry_state(&repo, doc_id)
        .map_err(|e| PyRuntimeError::new_err(format!("sync_fnm_retry_state: {}", e)))?;
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 从 DB 读取 diagnostic pages BPs。
///
/// ←→ Python `FNM_RE/app/page_translate.py::rebuild_fnm_diagnostic_page_entries`
#[pyfunction]
pub fn rebuild_fnm_diagnostic_page_entries_json(
    db_path: &str,
    doc_id: &str,
    pages_json: &str,
) -> PyResult<String> {
    let _pages: Vec<serde_json::Value> = serde_json::from_str(pages_json)
        .map_err(|e| PyValueError::new_err(format!("invalid pages_json: {}", e)))?;
    let pool = super::get_or_create_pool(db_path)
        .map_err(|e| PyRuntimeError::new_err(format!("open db: {}", e)))?;
    let repo = fnm_core::db::SqliteRepository::new(pool);
    let result =
        fnm_orchestrator::rebuild_fnm_diagnostic_page_entries(&repo, doc_id).map_err(|e| {
            PyRuntimeError::new_err(format!("rebuild_fnm_diagnostic_page_entries: {}", e))
        })?;
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 从 body unit 构建段级翻译任务（JSON 入/出）。
///
/// ←→ Python `FNM_RE/app/page_translate.py::build_fnm_body_unit_jobs`
#[pyfunction]
pub fn build_fnm_body_unit_jobs_json(unit_json: &str, pages_json: &str) -> PyResult<String> {
    let unit: serde_json::Value = serde_json::from_str(unit_json)
        .map_err(|e| PyValueError::new_err(format!("invalid unit_json: {}", e)))?;
    let pages: Vec<serde_json::Value> = serde_json::from_str(pages_json)
        .map_err(|e| PyValueError::new_err(format!("invalid pages_json: {}", e)))?;
    let result = fnm_orchestrator::build_fnm_body_unit_jobs(&unit, &pages);
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 将译文注入 body unit（JSON 入/出）。
///
/// ←→ Python `FNM_RE/app/page_translate.py::apply_body_unit_translations`
#[pyfunction]
pub fn apply_body_unit_translations_json(
    unit_json: &str,
    translated_paragraphs_json: &str,
) -> PyResult<String> {
    let unit: serde_json::Value = serde_json::from_str(unit_json)
        .map_err(|e| PyValueError::new_err(format!("invalid unit_json: {}", e)))?;
    let translated_paragraphs: Vec<serde_json::Value> =
        serde_json::from_str(translated_paragraphs_json).map_err(|e| {
            PyValueError::new_err(format!("invalid translated_paragraphs_json: {}", e))
        })?;
    let result = fnm_orchestrator::apply_body_unit_translations(&unit, &translated_paragraphs)
        .map_err(|e| PyRuntimeError::new_err(format!("apply_body_unit_translations: {}", e)))?;
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 将流式翻译结果合并到 unit（JSON 入/出）。
///
/// ←→ Python `FNM_RE/app/page_translate.py::apply_body_unit_entry_result`
#[pyfunction]
#[pyo3(signature = (unit_json, entry_json, apply_only_unresolved=false))]
pub fn apply_body_unit_entry_result_json(
    unit_json: &str,
    entry_json: &str,
    apply_only_unresolved: bool,
) -> PyResult<String> {
    let unit: serde_json::Value = serde_json::from_str(unit_json)
        .map_err(|e| PyValueError::new_err(format!("invalid unit_json: {}", e)))?;
    let entry: serde_json::Value = serde_json::from_str(entry_json)
        .map_err(|e| PyValueError::new_err(format!("invalid entry_json: {}", e)))?;
    let result =
        fnm_orchestrator::apply_body_unit_entry_result(&unit, &entry, apply_only_unresolved);
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 压缩序列化 page_segments 列表（JSON 入/出）。
///
/// ←→ Python `FNM_RE/shared/segment_codec.py::serialize_segments`
#[pyfunction]
pub fn serialize_segments_json(segments_json: &str) -> PyResult<String> {
    let segments: Vec<serde_json::Value> = serde_json::from_str(segments_json)
        .map_err(|e| PyValueError::new_err(format!("invalid segments_json: {}", e)))?;
    let result = fnm_core::segment_codec::serialize_segments(&segments);
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 反序列化 page_segments 列表为完整 dict（JSON 入/出）。
///
/// ←→ Python `FNM_RE/shared/segment_codec.py::deserialize_segments_to_dicts`
#[pyfunction]
pub fn deserialize_segments_to_dicts_json(payload: &str) -> PyResult<String> {
    let raw: Vec<serde_json::Value> = serde_json::from_str(payload)
        .map_err(|e| PyValueError::new_err(format!("invalid payload_json: {}", e)))?;
    let result = fnm_core::segment_codec::deserialize_segments_to_dicts(&raw);
    serde_json::to_string(&result).map_err(|e| PyRuntimeError::new_err(format!("serialize: {}", e)))
}

/// 替换冻结引用 token 为 markdown 脚注。
///
/// ←→ Python `FNM_RE/shared/refs.py::replace_frozen_refs`
#[pyfunction]
pub fn replace_frozen_refs_json(text: &str) -> PyResult<String> {
    Ok(fnm_core::refs::replace_frozen_refs(text))
}

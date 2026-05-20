//! `fnm-orchestrator` — FNM_RE pipeline 编排横切层。
//!
//! ←→ Python:
//! - `FNM_RE/app/pipeline.py::build_module_pipeline_snapshot()` → `pipeline::run_pipeline`
//! - `FNM_RE/app/mainline.py::run_phase6_pipeline_for_doc()` → 未来 `mainline::run_phase6_pipeline_for_doc`
//! - `FNM_RE/__init__.py` 公开 API → 未来通过 pyo3 wrap
//!
//! 当前 MVP 范围：纯内存顺序串联 phase1 → phase6，无 LLM repair 回环、无 pyo3、无 shadow mode。

#![deny(unused_must_use)]

pub mod error;
pub mod load;
pub mod mainline;
pub mod page_translate;
pub mod pipeline;
pub mod post_translate;
pub mod types;

pub use error::{OrchestratorError, Result};
pub use load::load_phase6_structure;
pub use mainline::{run_pipeline_for_doc, LlmRepairOptions};
pub use page_translate::{
    apply_body_unit_entry_result, apply_body_unit_translations, build_fnm_body_unit_jobs,
    build_retry_summary, build_unit_progress, collect_unit_failed_locations_value,
    format_unit_label_value, format_unit_pages_value, list_fnm_units_with_indices,
    prepare_page_translate_jobs, rebuild_fnm_diagnostic_page_entries, sync_fnm_retry_state,
    unit_page_numbers_value,
};
pub use pipeline::run_pipeline;
pub use post_translate::run_post_translate_export_checks;
pub use types::{
    ModulePipelineSnapshot, PipelineConfig, StartPhase,
};

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
pub mod types;

pub use error::{OrchestratorError, Result};
pub use load::load_phase6_structure;
pub use mainline::{run_pipeline_for_doc, LlmRepairOptions};
pub use page_translate::{build_retry_summary, build_unit_progress, prepare_page_translate_jobs};
pub use pipeline::run_pipeline;
pub use types::{
    ModulePipelineSnapshot, PipelineConfig, StartPhase,
};

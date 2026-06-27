//! ←→ Python `FNM_RE/app/page_translate.py`
//!
//! 翻译函数：
//! - `build_unit_progress` → `build_unit_progress`
//! - `build_retry_summary` → `build_retry_summary`
//! - `prepare_page_translate_jobs` → `prepare_page_translate_jobs`
//! - `build_fnm_body_unit_jobs` → M2.A1
//! - `apply_body_unit_translations` → M2.A1
//! - `apply_body_unit_entry_result` → M2.A1

mod apply;
mod format;
mod jobs;
mod jobs_builder;
mod progress;
mod retry;

#[cfg(test)]
mod tests;

// Re-export public functions
pub use apply::{apply_body_unit_entry_result, apply_body_unit_translations};
pub use format::{
    format_unit_label, format_unit_label_value, format_unit_pages, format_unit_pages_value,
    unit_page_numbers, unit_page_numbers_value,
};
pub use jobs::prepare_page_translate_jobs;
pub use jobs_builder::build_fnm_body_unit_jobs;
pub use progress::build_unit_progress;
pub use retry::{
    build_retry_summary, collect_unit_failed_locations_value, list_fnm_units_with_indices,
    rebuild_fnm_diagnostic_page_entries, sync_fnm_retry_state,
};

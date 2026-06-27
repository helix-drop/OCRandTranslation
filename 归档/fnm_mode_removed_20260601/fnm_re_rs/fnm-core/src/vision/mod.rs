//! Vision LLM 共享基础设施：PDFIUM 单例 + HTTP_CLIENT 单例 + 配置。
//!
//! 被 fnm-phase1 的 llm_book_type_verify 和 fnm-phase2 的 sup_recovery /
//! visual_anchor_recovery / llm_bare_digit_verify 共享。

pub mod http;
pub mod pdfium;
pub mod spec;

pub use http::{VisionConfig, HTTP_CLIENT};
pub use pdfium::{render_page_to_base64_png, render_page_to_data_url, PDFIUM};
pub use spec::{
    resolve_builtin_model_spec, resolve_custom_model_spec, resolve_fnm_model_pool_specs,
    resolve_fnm_repair_model_specs, resolve_translation_model_pool_specs,
    resolve_visual_model_spec, ResolvedModelSpec,
};

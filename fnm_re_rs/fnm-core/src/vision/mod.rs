//! Vision LLM 共享基础设施：PDFIUM 单例 + HTTP_CLIENT 单例 + 配置。
//!
//! 被 fnm-phase1 的 llm_book_type_verify 和 fnm-phase2 的 sup_recovery /
//! visual_anchor_recovery / llm_bare_digit_verify 共享。

pub mod http;
pub mod pdfium;

pub use http::{VisionConfig, HTTP_CLIENT};
pub use pdfium::{render_page_to_base64_png, PDFIUM};

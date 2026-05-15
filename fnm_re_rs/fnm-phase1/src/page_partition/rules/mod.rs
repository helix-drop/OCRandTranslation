//! 规则引擎：RuleMatch 类型 + 规则注册入口。
//! ←→ page_partition.py `_RuleMatch`, `_PageScanContext`, `_resolve_page_role`

pub mod archive_noise;
pub mod copyright;
pub mod course_listing;
pub mod early_other;
pub mod note_scan;
pub mod notes_heading;
pub mod rear_author;
pub mod rear_sparse;
pub mod rear_toc;
pub mod title_page;

use fnm_core::types::PageRole;

/// 规则匹配结果（对应 Python `_RuleMatch`）。
#[derive(Debug, Clone)]
pub struct RuleMatch {
    pub matched: bool,
    pub role: PageRole,
    pub confidence: f64,
    pub reason: String,
}

impl RuleMatch {
    pub fn new(role: PageRole, confidence: f64, reason: &str) -> Self {
        Self {
            matched: true,
            role,
            confidence,
            reason: reason.to_string(),
        }
    }

    pub fn no_match() -> Self {
        Self {
            matched: false,
            role: PageRole::Body,
            confidence: 0.0,
            reason: String::new(),
        }
    }
}

/// 页面扫描上下文（对应 Python `_PageScanContext`）。
#[derive(Debug, Clone)]
pub struct PageScanContext<'a> {
    pub page_no: i64,
    pub total_pages: i64,
    pub text: &'a str,
    pub note_scan: &'a serde_json::Value,
    pub headings: &'a [String],
}

/// 所有规则按优先级排列。
/// ←→ Python `_resolve_page_role` 的 rules tuple
pub fn all_rules() -> Vec<fn(&PageScanContext<'_>) -> RuleMatch> {
    vec![
        archive_noise::rule,
        course_listing::rule,
        copyright::rule,
        early_other::rule,
        rear_toc::rule,
        rear_author::rule,
        note_scan::rule,
        notes_heading::rule,
        rear_sparse::rule,
        title_page::rule,
    ]
}

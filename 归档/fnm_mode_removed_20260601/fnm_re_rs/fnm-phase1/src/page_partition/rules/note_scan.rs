//! ←→ Python `_rule_note_scan`

use super::{PageScanContext, RuleMatch};
use fnm_core::types::PageRole;

pub fn rule(ctx: &PageScanContext<'_>) -> RuleMatch {
    let page_kind = ctx
        .note_scan
        .get("page_kind")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    if page_kind == "endnote_collection" {
        return RuleMatch::new(PageRole::Note, 0.95, "note_scan_collection");
    }
    if page_kind == "mixed_body_endnotes" {
        return RuleMatch::new(PageRole::Body, 0.85, "mixed_body_endnotes");
    }
    RuleMatch::no_match()
}

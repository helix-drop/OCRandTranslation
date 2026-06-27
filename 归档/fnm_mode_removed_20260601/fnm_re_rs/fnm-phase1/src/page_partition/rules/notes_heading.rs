//! ←→ Python `_rule_notes_heading`

use super::{PageScanContext, RuleMatch};
use crate::page_partition::role_heuristics::is_notes_heading_match;
use fnm_core::types::PageRole;

pub fn rule(ctx: &PageScanContext<'_>) -> RuleMatch {
    let first_heading = ctx.headings.first().cloned().unwrap_or_default();
    let note_start_line_index = ctx
        .note_scan
        .get("note_start_line_index")
        .and_then(|v| v.as_i64())
        .unwrap_or(-1);
    if note_start_line_index == 0
        || (!first_heading.is_empty() && is_notes_heading_match(&first_heading))
    {
        return RuleMatch::new(PageRole::Note, 0.88, "notes_heading");
    }
    RuleMatch::no_match()
}

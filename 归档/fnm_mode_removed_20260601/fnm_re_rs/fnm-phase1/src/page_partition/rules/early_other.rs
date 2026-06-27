//! ←→ Python `_rule_early_other_list`

use super::{PageScanContext, RuleMatch};
use crate::page_partition::role_heuristics::{is_notes_heading_match, looks_like_early_other_page};

pub fn rule(ctx: &PageScanContext<'_>) -> RuleMatch {
    let first_heading = ctx.headings.first().cloned().unwrap_or_default();
    if !is_notes_heading_match(&first_heading)
        && looks_like_early_other_page(ctx.text, ctx.headings, ctx.page_no, ctx.total_pages)
    {
        return RuleMatch::new(fnm_core::types::PageRole::Other, 0.96, "early_other_list");
    }
    RuleMatch::no_match()
}

//! ←→ Python `_rule_rear_toc_tail`

use super::{PageScanContext, RuleMatch};
use crate::page_partition::role_heuristics::looks_like_rear_toc_tail_page;

pub fn rule(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_rear_toc_tail_page(ctx.text, ctx.headings, ctx.page_no, ctx.total_pages) {
        return RuleMatch::new(fnm_core::types::PageRole::Other, 0.95, "rear_toc_tail");
    }
    RuleMatch::no_match()
}

//! ←→ Python `_rule_rear_sparse_other`

use super::{PageScanContext, RuleMatch};
use crate::page_partition::role_heuristics::looks_like_rear_sparse_other_page;

pub fn rule(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_rear_sparse_other_page(ctx.text, ctx.page_no, ctx.total_pages) {
        return RuleMatch::new(fnm_core::types::PageRole::Other, 0.90, "rear_sparse_other");
    }
    RuleMatch::no_match()
}

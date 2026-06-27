//! ←→ Python `_rule_early_course_listing`

use super::{PageScanContext, RuleMatch};
use crate::page_partition::role_heuristics::looks_like_course_listing_page;

pub fn rule(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_course_listing_page(ctx.text, ctx.page_no, ctx.total_pages) {
        return RuleMatch::new(
            fnm_core::types::PageRole::Other,
            0.97,
            "early_course_listing",
        );
    }
    RuleMatch::no_match()
}

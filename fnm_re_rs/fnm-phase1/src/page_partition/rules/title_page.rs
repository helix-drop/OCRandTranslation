//! ←→ Python `_rule_title_page`

use super::{PageScanContext, RuleMatch};
use crate::page_partition::role_heuristics::looks_like_title_page;
use fnm_core::types::PageRole;

pub fn rule(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_title_page(ctx.text, ctx.headings, ctx.page_no, ctx.total_pages) {
        return RuleMatch::new(PageRole::FrontMatter, 0.92, "title_page");
    }
    RuleMatch::no_match()
}

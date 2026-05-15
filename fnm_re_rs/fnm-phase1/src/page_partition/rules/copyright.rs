//! ←→ Python `_rule_copyright_front_matter`

use super::{PageScanContext, RuleMatch};
use crate::page_partition::role_heuristics::looks_like_copyright_front_matter_page;

pub fn rule(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_copyright_front_matter_page(ctx.text, ctx.page_no, ctx.total_pages) {
        return RuleMatch::new(
            fnm_core::types::PageRole::FrontMatter,
            0.95,
            "copyright_front_matter",
        );
    }
    RuleMatch::no_match()
}

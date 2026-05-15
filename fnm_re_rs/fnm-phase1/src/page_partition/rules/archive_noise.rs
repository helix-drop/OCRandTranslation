//! ←→ Python `_rule_archive_noise`

use super::{PageScanContext, RuleMatch};
use crate::page_partition::role_heuristics::is_archive_noise;

pub fn rule(ctx: &PageScanContext<'_>) -> RuleMatch {
    if ctx.page_no <= (6).max(ctx.total_pages * 3 / 100) && is_archive_noise(ctx.text) {
        return RuleMatch::new(fnm_core::types::PageRole::Noise, 0.98, "archive_noise");
    }
    RuleMatch::no_match()
}

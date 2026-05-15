//! ←→ page_partition.py: _resolve_page_role
//! 规则链主入口，规则实现在 `rules/` 子模块。

use super::rules::{self, RuleMatch};
use fnm_core::title::guess_title_family;
use fnm_core::types::PageRole;

pub use super::rules::PageScanContext;

/// 按优先级依次匹配规则，首次命中返回。
/// ←→ Python `_resolve_page_role`
pub fn resolve_page_role(ctx: &PageScanContext<'_>) -> RuleMatch {
    // 1. 规则引擎子模块中的规则
    for rule_fn in rules::all_rules() {
        let m = rule_fn(ctx);
        if m.matched {
            return m;
        }
    }
    // 2. 内联规则（简化，不值得独立成文件）
    for rule_fn in &[
        rule_title_family as fn(&PageScanContext<'_>) -> RuleMatch,
        rule_blank_front_page,
    ] {
        let m = rule_fn(ctx);
        if m.matched {
            return m;
        }
    }
    // 3. 兜底
    rule_default_body(ctx)
}

fn rule_title_family(ctx: &PageScanContext<'_>) -> RuleMatch {
    let first_heading = ctx.headings.first().cloned().unwrap_or_default();
    if first_heading.is_empty() {
        return RuleMatch::no_match();
    }
    let family = guess_title_family(&first_heading, ctx.page_no, ctx.total_pages);
    match family {
        "front_matter" => RuleMatch::new(PageRole::FrontMatter, 0.90, "title_family"),
        "contents" | "illustrations" | "bibliography" | "index" | "appendix" => {
            RuleMatch::new(PageRole::Other, 0.94, family)
        }
        _ => RuleMatch::no_match(),
    }
}

fn rule_blank_front_page(ctx: &PageScanContext<'_>) -> RuleMatch {
    if ctx.page_no <= 2 && ctx.text.trim().is_empty() {
        return RuleMatch::new(PageRole::Noise, 0.60, "blank_front_page");
    }
    RuleMatch::no_match()
}

fn rule_default_body(ctx: &PageScanContext<'_>) -> RuleMatch {
    let conf = if ctx.headings.is_empty() { 0.62 } else { 0.72 };
    RuleMatch::new(PageRole::Body, conf, "default_body")
}

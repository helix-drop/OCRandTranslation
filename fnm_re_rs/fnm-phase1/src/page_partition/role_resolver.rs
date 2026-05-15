//! ←→ page_partition.py: _resolve_page_role + _PageScanContext + _RuleMatch
//! 规则链驱动的主判定流程。

use crate::page_partition::role_heuristics::*;
use fnm_core::types::PageRole;
use serde_json::Value;

#[derive(Debug, Clone)]
pub struct PageScanContext<'a> {
    pub page_no: i64,
    pub total_pages: i64,
    pub text: &'a str,
    pub note_scan: &'a Value,
    pub headings: &'a [String],
}

#[derive(Debug, Clone)]
pub struct RuleMatch {
    pub matched: bool,
    pub role: PageRole,
    pub confidence: f64,
    pub reason: String,
}

fn rule_match(role: PageRole, confidence: f64, reason: &str) -> RuleMatch {
    RuleMatch {
        matched: true,
        role,
        confidence,
        reason: reason.to_string(),
    }
}

fn no_match() -> RuleMatch {
    RuleMatch {
        matched: false,
        role: PageRole::Body,
        confidence: 0.0,
        reason: String::new(),
    }
}

pub fn resolve_page_role(ctx: &PageScanContext<'_>) -> RuleMatch {
    // 规则按优先级链依次匹配，首次命中返回。
    let rules: &[for<'a> fn(&PageScanContext<'a>) -> RuleMatch] = &[
        rule_archive_noise,
        rule_early_course_listing,
        rule_copyright_front_matter,
        rule_early_other_list,
        rule_rear_toc_tail,
        rule_rear_author_blurb,
        rule_note_scan,
        rule_notes_heading,
        rule_rear_sparse_other,
        rule_title_page,
        rule_title_family,
        rule_blank_front_page,
        rule_default_body,
    ];

    for rule_fn in rules {
        let m = rule_fn(ctx);
        if m.matched {
            return m;
        }
    }
    rule_default_body(ctx)
}

fn rule_archive_noise(ctx: &PageScanContext<'_>) -> RuleMatch {
    if ctx.page_no <= (6).max(ctx.total_pages * 3 / 100) && is_archive_noise(ctx.text) {
        return rule_match(PageRole::Noise, 0.98, "archive_noise");
    }
    no_match()
}

fn rule_early_course_listing(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_course_listing_page(ctx.text, ctx.page_no, ctx.total_pages) {
        return rule_match(PageRole::Other, 0.97, "early_course_listing");
    }
    no_match()
}

fn rule_copyright_front_matter(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_copyright_front_matter_page(ctx.text, ctx.page_no, ctx.total_pages) {
        return rule_match(PageRole::FrontMatter, 0.95, "copyright_front_matter");
    }
    no_match()
}

fn rule_early_other_list(ctx: &PageScanContext<'_>) -> RuleMatch {
    let first_heading = ctx.headings.first().cloned().unwrap_or_default();
    if !is_notes_heading_match(&first_heading)
        && looks_like_early_other_page(ctx.text, ctx.headings, ctx.page_no, ctx.total_pages)
    {
        return rule_match(PageRole::Other, 0.96, "early_other_list");
    }
    no_match()
}

fn rule_rear_toc_tail(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_rear_toc_tail_page(ctx.text, ctx.headings, ctx.page_no, ctx.total_pages) {
        return rule_match(PageRole::Other, 0.95, "rear_toc_tail");
    }
    no_match()
}

fn rule_rear_author_blurb(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_rear_author_blurb_page(ctx.text, ctx.headings, ctx.page_no, ctx.total_pages) {
        return rule_match(PageRole::Other, 0.95, "rear_author_blurb");
    }
    no_match()
}

fn rule_note_scan(ctx: &PageScanContext<'_>) -> RuleMatch {
    let page_kind = ctx
        .note_scan
        .get("page_kind")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    if page_kind == "endnote_collection" {
        return rule_match(PageRole::Note, 0.95, "note_scan_collection");
    }
    if page_kind == "mixed_body_endnotes" {
        return rule_match(PageRole::Body, 0.85, "mixed_body_endnotes");
    }
    no_match()
}

fn rule_notes_heading(ctx: &PageScanContext<'_>) -> RuleMatch {
    let first_heading = ctx.headings.first().cloned().unwrap_or_default();
    let note_start_line_index = ctx
        .note_scan
        .get("note_start_line_index")
        .and_then(|v| v.as_i64())
        .unwrap_or(-1);
    if note_start_line_index == 0
        || (!first_heading.is_empty() && is_notes_heading_match(&first_heading))
    {
        return rule_match(PageRole::Note, 0.88, "notes_heading");
    }
    no_match()
}

fn rule_rear_sparse_other(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_rear_sparse_other_page(ctx.text, ctx.page_no, ctx.total_pages) {
        return rule_match(PageRole::Other, 0.90, "rear_sparse_other");
    }
    no_match()
}

fn rule_title_page(ctx: &PageScanContext<'_>) -> RuleMatch {
    if looks_like_title_page(ctx.text, ctx.headings, ctx.page_no, ctx.total_pages) {
        return rule_match(PageRole::FrontMatter, 0.92, "title_page");
    }
    no_match()
}

fn rule_title_family(ctx: &PageScanContext<'_>) -> RuleMatch {
    let first_heading = ctx.headings.first().cloned().unwrap_or_default();
    if first_heading.is_empty() {
        return no_match();
    }
    let family = fnm_core::title::guess_title_family(&first_heading, ctx.page_no, ctx.total_pages);
    match family {
        "front_matter" => rule_match(PageRole::FrontMatter, 0.90, "title_family"),
        "contents" | "illustrations" | "bibliography" | "index" | "appendix" => {
            rule_match(PageRole::Other, 0.94, family)
        }
        _ => no_match(),
    }
}

fn rule_blank_front_page(ctx: &PageScanContext<'_>) -> RuleMatch {
    if ctx.page_no <= 2 && ctx.text.trim().is_empty() {
        return rule_match(PageRole::Noise, 0.60, "blank_front_page");
    }
    no_match()
}

fn rule_default_body(ctx: &PageScanContext<'_>) -> RuleMatch {
    let conf = if ctx.headings.is_empty() { 0.62 } else { 0.72 };
    rule_match(PageRole::Body, conf, "default_body")
}

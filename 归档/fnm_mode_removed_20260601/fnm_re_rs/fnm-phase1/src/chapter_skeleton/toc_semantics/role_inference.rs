//! TOC item role 推断：chapter / container / endnotes / front_matter / back_matter。
//! ←→ Python `_visual_toc_semantic_role()`。

use super::title_utils::*;
use fnm_core::title::normalize_title;
use once_cell::sync::Lazy;
use regex::Regex;

/// Appendix / annex 匹配正则（back_matter → post_body 提升）。
static APPENDIX_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^(?:appendix|appendices|annex(?:es)?)\b").unwrap());

/// Acknowledgments / remerciements 匹配正则（front_matter 判定）。
static ACKNOWLEDGMENTS_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^(?:acknowledg(?:e)?ments?|remerciements?|list of abbreviations|liste des abr[eé]viations|list of illustrations|liste des illustrations)\b",
    )
    .unwrap()
});

/// 多维 role 推断。对齐 Python `_visual_toc_semantic_role()`。
pub fn visual_toc_semantic_role(
    row: &super::title_utils::TocRow,
    chapter_level: i64,
    _total_pages: i64,
) -> String {
    let title = normalize_title(&row.title);
    if title.is_empty() {
        return "unknown".into();
    }
    let lowered = title.to_lowercase();
    let page_no = row.page_no;
    let page_role = &row.page_role;
    let explicit_role = super::normalize_visual_toc_role_hint(&row.explicit_role_hint);

    // 容器
    if explicit_role == "container" {
        return "part".into();
    }
    // 尾注
    if explicit_role == "endnotes" {
        return "endnotes".into();
    }
    // back_matter 中的 appendix → post_body
    if explicit_role == "back_matter"
        && APPENDIX_RE.find(&lowered).is_some()
        && page_no > 0
        && !matches!(page_role.as_str(), "note" | "noise")
    {
        return "post_body".into();
    }
    // 显式 role 直接返回
    if matches!(
        explicit_role.as_str(),
        "chapter" | "section" | "post_body" | "back_matter" | "front_matter"
    ) {
        return explicit_role;
    }

    let level = row.level;
    let family = &row.family;

    // non_body_title 或 excluded family
    if row.non_body_title || is_excluded_family(family) {
        if NOTES_HEADER_RE.is_match(&title) {
            return "endnotes".into();
        }
        if is_acknowledgments_or_similar(&lowered) {
            return "front_matter".into();
        }
        return "back_matter".into();
    }
    // Part title
    if is_toc_part_title(&title) {
        return "part".into();
    }
    // Notes heading
    if NOTES_HEADER_RE.is_match(&title) {
        return "endnotes".into();
    }
    // 显式 chapter title
    if is_visual_toc_explicit_chapter_title(&title) {
        return "chapter".into();
    }
    // front_matter 页 + 低层级
    if page_role == "front_matter" && level <= chapter_level {
        if uppercase_ratio(&title) >= 0.7 && title.split_whitespace().count() <= 8 {
            return "book_title".into();
        }
        return "front_matter".into();
    }
    // 层级判断
    if level > chapter_level {
        return "section".into();
    }
    if level == chapter_level {
        return "chapter".into();
    }
    if is_body_anchor_title(&title) {
        return "chapter".into();
    }
    if matches!(page_role.as_str(), "body" | "front_matter") {
        return "section".into();
    }
    "unknown".into()
}

fn is_excluded_family(family: &str) -> bool {
    matches!(
        family,
        "contents" | "illustrations" | "bibliography" | "index" | "appendix"
    )
}

fn is_acknowledgments_or_similar(lowered: &str) -> bool {
    ACKNOWLEDGMENTS_RE.find(lowered).is_some()
}

fn is_toc_part_title(title: &str) -> bool {
    super::TOC_PART_TITLE_RE.is_match(&normalize_title(title))
}

fn is_body_anchor_title(title: &str) -> bool {
    super::TOC_BODY_ANCHOR_TITLE_RE.is_match(title)
}

fn is_visual_toc_explicit_chapter_title(title: &str) -> bool {
    let normalized = normalize_title(title);
    if normalized.is_empty() {
        return false;
    }
    if TOC_FORCE_EXPORT_TITLE_RE.is_match(&normalized) {
        return true;
    }
    super::TOC_EXPLICIT_CHAPTER_TITLE_RE.is_match(&normalized)
}

//! ←→ page_partition.py: 前置页判定 + 正文入口 + 汇总。

use fnm_core::records::PagePartitionRecord;
use fnm_core::title::guess_title_family;
use regex::Regex;
use std::collections::HashMap;

use super::patterns::*;

pub(crate) fn is_archive_noise(text: &str) -> bool {
    ARCHIVE_NOISE_RE.is_match(text)
}

/// 完整版：YEAR_RANGE_RE + COURS_CF_RE + 页码天花板。
/// 简化版见 `chapter_skeleton::toc_semantics::page_resolve::looks_like_course_listing_page`（纯子串匹配）。
pub(crate) fn looks_like_course_listing_page(text: &str, page_no: i64, total_pages: i64) -> bool {
    if page_no > (20).max(total_pages * 8 / 100) {
        return false;
    }
    let lines = super::plain_text_lines(text);
    if lines.len() < 4 {
        return false;
    }
    let year_range_count = lines
        .iter()
        .filter(|l| YEAR_RANGE_RE.is_match(l))
        .take(24)
        .count();
    let course_hint = lines.iter().take(4).any(|l| COURS_CF_RE.is_match(l));
    year_range_count >= 3 && (course_hint || lines.len() >= 8)
}

/// 完整版：COPYRIGHT_RE 正则 + 页码天花板。
/// 简化版见 `chapter_skeleton::toc_semantics::page_resolve::looks_like_copyright_front_matter_page`（纯子串匹配）。
pub(crate) fn looks_like_copyright_front_matter_page(
    text: &str,
    page_no: i64,
    total_pages: i64,
) -> bool {
    if page_no > (20).max(total_pages * 8 / 100) {
        return false;
    }
    let lines: Vec<&str> = text.lines().take(20).collect();
    if lines.is_empty() {
        return false;
    }
    let re = &*COPYRIGHT_RE;
    let hits = lines.iter().filter(|l| re.is_match(l)).count();
    if hits >= 2 {
        return true;
    }
    lines.iter().any(|l| {
        l.to_lowercase()
            .contains("édition établie sous la direction")
    }) && hits >= 1
}

pub(crate) fn looks_like_early_other_page(
    text: &str,
    headings: &[String],
    page_no: i64,
    total_pages: i64,
) -> bool {
    if page_no > (25).max(total_pages * 8 / 100) {
        return false;
    }
    let first_heading = headings.first().cloned().unwrap_or_default();
    if !first_heading.is_empty()
        && matches!(
            guess_title_family(&first_heading, page_no, total_pages),
            "contents" | "illustrations" | "bibliography" | "index" | "appendix"
        )
    {
        return true;
    }
    let lines = super::plain_text_lines(text);
    if lines.is_empty() {
        return false;
    }
    let numbered_like = lines
        .iter()
        .take(24)
        .filter(|l| TOC_LINE_RE.is_match(l) || FIGURE_LIST_LINE_RE.is_match(l))
        .count();
    numbered_like >= 4
}

/// 完整版：FRONT_MATTER_PATTERNS + short_lines + uppercase_ratio + 页码天花板。
/// 简化版见 `chapter_skeleton::toc_semantics::page_resolve::looks_like_title_page`（仅行数+heading 判断）。
pub(crate) fn looks_like_title_page(
    text: &str,
    headings: &[String],
    page_no: i64,
    total_pages: i64,
) -> bool {
    if page_no > (18).max(total_pages * 8 / 100) {
        return false;
    }
    let lines = super::plain_text_lines(text);
    if lines.is_empty() {
        return false;
    }
    let first_heading = headings.first().cloned().unwrap_or_default();
    if !first_heading.is_empty()
        && super::chapter_keyword_strength(&first_heading) >= 1
        && looks_like_prose_after_heading(text)
    {
        return false;
    }
    if !headings.is_empty() && looks_like_prose_after_heading(text) {
        return false;
    }
    let lowered: Vec<String> = lines.iter().take(12).map(|l| l.to_lowercase()).collect();
    let front_matter_patterns: &Vec<Regex> = &FRONT_MATTER_PATTERNS;
    for re in front_matter_patterns {
        if lowered.iter().any(|l| re.is_match(l)) {
            return true;
        }
    }
    let short_lines = lines.iter().take(12).filter(|l| l.len() <= 40).count();
    let heading_like = headings.iter().any(|h| super::uppercase_ratio(h) >= 0.55);
    let line12: Vec<&String> = lines.iter().take(12).collect();
    if line12.len() <= 12
        && short_lines >= (2).max(line12.len().saturating_sub(2))
        && (heading_like
            || !headings.is_empty()
            || super::uppercase_ratio(&lines.iter().take(8).cloned().collect::<Vec<_>>().join(" "))
                >= 0.55)
    {
        return true;
    }
    false
}

/// 完整版：markdown_body_after_first_heading + note ref / SUP marker / 段落计数。
/// 简化版见 `chapter_skeleton::toc_semantics::page_resolve::looks_like_prose_after_heading`（仅 heading + 2 行散文）。
pub(crate) fn looks_like_prose_after_heading(text: &str) -> bool {
    let body = markdown_body_after_first_heading(text);
    if body.trim().is_empty() {
        return false;
    }
    if extract_note_ref_count(&body) > 0 {
        return true;
    }
    if SUP_MARKER_RE.is_match(&body) {
        return true;
    }
    let lines = super::plain_text_lines(&body);
    if lines.is_empty() {
        return false;
    }
    let top10: Vec<&String> = lines.iter().take(10).collect();
    let sentence_re = &*SENTENCE_END_RE;
    let sentence_like = top10
        .iter()
        .filter(|l| l.len() >= 40 && sentence_re.is_match(l))
        .count();
    let short_sentence_like = top10
        .iter()
        .filter(|l| l.len() >= 10 && sentence_re.is_match(l))
        .count();
    let long_lines = top10.iter().filter(|l| l.len() >= 60).count();
    let medium_lines = top10.iter().filter(|l| l.len() >= 30).count();
    let mixed_case_lines = top10.iter().filter(|l| LATIN_LETTER_RE.is_match(l)).count();
    let total_chars: usize = top10.iter().take(6).map(|l| l.len()).sum();
    long_lines >= 2
        || (long_lines >= 1 && medium_lines >= 3)
        || sentence_like >= 2
        || (sentence_like >= 1 && total_chars >= 180)
        || short_sentence_like >= 1
        || (mixed_case_lines >= 2 && total_chars >= 70)
}

fn markdown_body_after_first_heading(text: &str) -> String {
    let raw_lines: Vec<&str> = text.lines().collect();
    if raw_lines.is_empty() {
        return String::new();
    }
    if MARKDOWN_HEADING_RE.is_match(raw_lines[0].trim()) {
        return raw_lines[1..].join("\n").trim().to_string();
    }
    text.trim().to_string()
}

fn extract_note_ref_count(text: &str) -> usize {
    FROZEN_REF_RE.find_iter(text).count()
}

pub fn summarize_page_partitions(records: &[PagePartitionRecord]) -> HashMap<String, i64> {
    let mut counts = HashMap::from([
        ("noise".into(), 0i64),
        ("front_matter".into(), 0),
        ("body".into(), 0),
        ("note".into(), 0),
        ("other".into(), 0),
    ]);
    for r in records {
        let key = r.page_role.as_str();
        if let Some(v) = counts.get_mut(key) {
            *v += 1;
        }
    }
    let mut result = HashMap::new();
    result.insert("total_pages".into(), records.len() as i64);
    result.extend(counts);
    result
}

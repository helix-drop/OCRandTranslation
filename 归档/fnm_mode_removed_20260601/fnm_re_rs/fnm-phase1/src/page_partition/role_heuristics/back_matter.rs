//! ←→ page_partition.py: back matter 延续页 + 尾部页面判定。

use fnm_core::title::{guess_title_family, normalize_title};

use super::patterns::*;

pub(crate) fn looks_like_bibliography_continuation_page(text: &str) -> bool {
    let normalized: String = super::plain_text_lines(text).join(" ");
    if normalized.is_empty() {
        return false;
    }
    let author_entry_count = BIBLIO_AUTHOR_ENTRY_RE.find_iter(&normalized).count();
    let citation_hint_count = BIBLIO_CITATION_HINT_RE.find_iter(&normalized).count();
    let year_count = YEAR_TOKEN_RE.find_iter(&normalized).count();
    let quoted_title_count = normalized.matches('«').count() + normalized.matches('"').count();
    if author_entry_count >= 2 && year_count >= 2 {
        return true;
    }
    if citation_hint_count >= 3 && year_count >= 3 {
        return true;
    }
    quoted_title_count >= 2 && citation_hint_count >= 2 && year_count >= 2
}

pub(crate) fn looks_like_index_continuation_page(text: &str) -> bool {
    let normalized = text.trim();
    if normalized.is_empty() {
        return false;
    }
    INDEX_ENTRY_RE.find_iter(normalized).count() >= 2
}

pub(crate) fn looks_like_illustrations_continuation_page(text: &str) -> bool {
    let normalized: String = super::plain_text_lines(text).join(" ");
    if normalized.is_empty() {
        return false;
    }
    let numbered_entry_count = NUMBERED_ENTRY_RE.find_iter(&normalized).count();
    let hint_count = ILLUSTRATION_CONTENT_RE.find_iter(&normalized).count();
    numbered_entry_count >= 2 && hint_count >= 2
}

pub(crate) fn looks_like_back_matter_continuation_page(
    text: &str,
    family: &str,
    _page_no: i64,
    _total_pages: i64,
) -> bool {
    let normalized_family = family.trim().to_lowercase();
    match normalized_family.as_str() {
        "bibliography" => looks_like_bibliography_continuation_page(text),
        "index" => looks_like_index_continuation_page(text),
        "illustrations" => looks_like_illustrations_continuation_page(text),
        _ => false,
    }
}

/// 从 record 中尝试提取 back matter family。
/// ←→ Python `_seed_back_matter_family`
pub(crate) fn seed_back_matter_family(
    role: &str,
    reason: &str,
    headings: &[String],
    page_no: i64,
    total_pages: i64,
) -> String {
    let safe_total_pages = total_pages.max(1);
    let safe_page_no = page_no.max(1);
    if safe_total_pages > 20 && safe_page_no < (20).max((safe_total_pages as f64 * 0.6) as i64) {
        return String::new();
    }
    if role == "other" && matches!(reason, "bibliography" | "index" | "illustrations") {
        return reason.to_string();
    }
    let first_heading = headings.first().cloned().unwrap_or_default();
    if first_heading.is_empty() {
        return String::new();
    }
    let family = guess_title_family(&first_heading, page_no, total_pages);
    if matches!(family, "bibliography" | "index" | "illustrations") {
        return family.to_string();
    }
    String::new()
}

pub(crate) fn looks_like_rear_toc_tail_page(
    text: &str,
    headings: &[String],
    page_no: i64,
    total_pages: i64,
) -> bool {
    if total_pages < 40 {
        return false;
    }
    let tail_window = (12).max(total_pages * 4 / 100);
    if page_no < (total_pages - tail_window).max(1) {
        return false;
    }
    let lines = super::plain_text_lines(text);
    if lines.len() < 3 {
        return false;
    }
    let mut dotted_count = 0i64;
    let mut tocish_count = 0i64;
    let mut lecture_count = 0i64;
    let mut tail_listing_count = 0i64;
    for line in lines.iter().take(40) {
        let normalized = normalize_title(line);
        let lowered = normalized.to_lowercase();
        let has_dot_leader = DOT_LEADER_RE.is_match(&normalized) || lowered.contains(".....");
        if has_dot_leader {
            dotted_count += 1;
            if normalized.split_whitespace().count() <= 26 {
                tocish_count += 1;
            }
        }
        if TOC_LINE_RE.is_match(&normalized) || FIGURE_LIST_LINE_RE.is_match(&normalized) {
            tocish_count += 1;
        }
        if LECTURE_TITLE_RE.is_match(&lowered) {
            lecture_count += 1;
            if has_dot_leader || TRAILING_YEAR_RE.is_match(&lowered) {
                tocish_count += 1;
            }
        }
        if TRAILING_PAGENO_RE.is_match(&normalized)
            && normalized.split_whitespace().count() >= 3
            && normalized.split_whitespace().count() <= 18
        {
            tail_listing_count += 1;
        }
    }
    let normalized_headings: Vec<String> = headings
        .iter()
        .filter_map(|h| {
            let n = normalize_title(h);
            if n.is_empty() {
                None
            } else {
                Some(n.to_lowercase())
            }
        })
        .collect();
    let has_table_heading = normalized_headings
        .iter()
        .take(2)
        .any(|h| TABLE_TOC_HEADING_RE.is_match(h));
    if has_table_heading && (tocish_count >= 2 || dotted_count >= 2) {
        return true;
    }
    if lecture_count >= 2 && (tocish_count >= 3 || dotted_count >= 2) {
        return true;
    }
    if tocish_count >= 5 && dotted_count >= 1 {
        return true;
    }
    if tocish_count >= 6 {
        return true;
    }
    if tail_listing_count >= 5 {
        return true;
    }
    false
}

pub(crate) fn looks_like_rear_author_blurb_page(
    text: &str,
    headings: &[String],
    page_no: i64,
    total_pages: i64,
) -> bool {
    if total_pages < 40 {
        return false;
    }
    let tail_window = (12).max(total_pages * 4 / 100);
    if page_no < (total_pages - tail_window).max(1) {
        return false;
    }
    let lines: Vec<&str> = text.lines().take(24).collect();
    if lines.len() < 4 {
        return false;
    }
    let normalized_headings: Vec<String> = headings
        .iter()
        .filter_map(|h| {
            let n = normalize_title(h);
            if n.is_empty() {
                None
            } else {
                Some(n)
            }
        })
        .collect();
    if normalized_headings.len() < 2 {
        return false;
    }
    if super::chapter_keyword_strength(&normalized_headings[0]) >= 1
        || super::chapter_keyword_strength(&normalized_headings[1]) >= 1
    {
        return false;
    }
    if super::uppercase_ratio(&normalized_headings[1]) < 0.45 {
        return false;
    }
    let prose_re = &*PROSE_WORD_RE;
    let prose_lines = lines
        .iter()
        .filter(|l| l.len() >= 60 && prose_re.is_match(l))
        .count();
    let total_chars: usize = lines.iter().map(|l| l.len()).sum();
    prose_lines >= 2 || (prose_lines >= 1 && total_chars >= 150)
}

pub(crate) fn looks_like_rear_sparse_other_page(
    text: &str,
    page_no: i64,
    total_pages: i64,
) -> bool {
    if total_pages < 40 {
        return false;
    }
    let tail_window = (12).max(total_pages * 4 / 100);
    if page_no < (total_pages - tail_window).max(1) {
        return false;
    }
    let normalized = text.trim();
    if normalized.is_empty() {
        return true;
    }
    if normalized.to_lowercase().contains("<table") {
        return true;
    }
    let lines = super::plain_text_lines(normalized);
    if lines.is_empty() {
        return true;
    }
    let alnum_chars = normalized.chars().filter(|c| c.is_alphanumeric()).count();
    let digit_chars = normalized.chars().filter(|c| c.is_ascii_digit()).count();
    if alnum_chars > 0 && digit_chars as f64 / alnum_chars.max(1) as f64 >= 0.65 {
        return true;
    }
    let short_lines = lines.iter().take(20).filter(|l| l.len() <= 24).count();
    short_lines >= (4).max(lines.len().saturating_sub(1))
}

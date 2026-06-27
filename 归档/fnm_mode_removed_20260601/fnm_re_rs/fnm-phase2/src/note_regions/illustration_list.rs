//! ←→ note_regions.py: _looks_like_illustration_list_page + helper regexes.
//! 插图列表页识别（排除假阳性 endnote candidate）。

use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashMap;

static ILLUSTRATION_LIST_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:list(?:e)?\s+(?:of\s+)?(?:illustrations?|figures?|plates?)|liste\s+des\s+illustrations?)\b",
    )
    .unwrap()
});

static ILLUSTRATION_CONTENT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)(?:©|cm\b|mus[ée]e|biblioth[eè]que|gravure|huile|lithograph|dessin|eau-forte|collection)",
    )
    .unwrap()
});

static MD_PREFIX_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\s{0,3}#{1,6}\s*").unwrap());

/// 判断页面是否为插图列表页。
/// ←→ Python `_looks_like_illustration_list_page`
pub fn looks_like_illustration_list_page(
    page_no: i64,
    page_by_no: &HashMap<i64, &RawPage>,
) -> bool {
    let page = match page_by_no.get(&page_no) {
        Some(p) => p,
        None => return false,
    };

    let lines: Vec<&str> = page
        .markdown
        .lines()
        .map(|l| l.trim())
        .filter(|l| !l.is_empty())
        .collect();

    if lines.is_empty() {
        return false;
    }

    let first_line = MD_PREFIX_RE.replace(lines[0], "").trim().to_string();
    if ILLUSTRATION_LIST_RE.is_match(&first_line) {
        return true;
    }

    // Lookback up to 3 pages
    let mut prev_first_line = String::new();
    for lookback in 1..=3 {
        let prev_no = page_no - lookback;
        if let Some(prev_page) = page_by_no.get(&prev_no) {
            let prev_lines: Vec<&str> = prev_page
                .markdown
                .lines()
                .map(|l| l.trim())
                .filter(|l| !l.is_empty())
                .collect();
            if let Some(first) = prev_lines.first() {
                prev_first_line = MD_PREFIX_RE.replace(first, "").trim().to_string();
                if !prev_first_line.is_empty() {
                    break;
                }
            }
        }
    }

    if prev_first_line.is_empty() || !ILLUSTRATION_LIST_RE.is_match(&prev_first_line) {
        return false;
    }

    let mut numbered_prefix = 0i64;
    let mut illustration_hint_count = 0i64;
    for line in lines.iter().take(8) {
        let stripped = MD_PREFIX_RE.replace(line, "").trim().to_string();
        if REGEX_NUMBERED_PREFIX.is_match(&stripped) {
            numbered_prefix += 1;
        }
        if ILLUSTRATION_CONTENT_RE.is_match(&stripped) {
            illustration_hint_count += 1;
        }
    }

    numbered_prefix >= 2 && illustration_hint_count >= 2
}

static REGEX_NUMBERED_PREFIX: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\d{1,3}[\.)]\s+").unwrap());

//! ←→ page_partition.py: 所有 _looks_like_* / _is_* 启发式判定函数 + 正则池。

mod back_matter;
mod front_matter;
mod note_pages;
mod patterns;

// Re-export 所有 pub(crate) 函数，保持外部调用路径不变
pub(crate) use back_matter::*;
pub use front_matter::summarize_page_partitions;
pub(crate) use front_matter::*;
pub(crate) use note_pages::*;
pub(crate) use patterns::ENDNOTES_HINT_STOP_REASONS;

use fnm_core::title::normalize_title;

// ── 文本工具 ──────────────────────────────────────────────────

pub(crate) fn is_notes_heading_match(heading: &str) -> bool {
    let h = normalize_title(heading);
    !h.is_empty() && patterns::NOTES_HEADER_RE.is_match(&h)
}

pub(crate) fn plain_text_lines(text: &str) -> Vec<String> {
    let raw = patterns::MU_HTML_TAG_RE.replace_all(text, " ");
    raw.split('\n')
        .map(|line| {
            patterns::WHITESPACE_RE
                .replace_all(line.trim(), " ")
                .to_string()
        })
        .filter(|line| !line.is_empty())
        .collect()
}

pub(crate) fn uppercase_ratio(text: &str) -> f64 {
    let letters: Vec<char> = text.chars().filter(|c| c.is_alphabetic()).collect();
    if letters.is_empty() {
        return 0.0;
    }
    let uppers = letters.iter().filter(|c| c.is_uppercase()).count();
    uppers as f64 / letters.len().max(1) as f64
}

pub(crate) fn chapter_keyword_strength(title: &str) -> i64 {
    let text = normalize_title(title);
    if text.is_empty() {
        return 0;
    }
    if patterns::CHAPTER_KEYWORD_RE.is_match(&text) {
        return 2;
    }
    if patterns::MAIN_NUMBERED_TITLE_RE.is_match(&text) {
        return 1;
    }
    0
}

// ── 正文入口判定 ──────────────────────────────────────────────

pub(crate) fn is_body_entry_page(
    text: &str,
    headings: &[String],
    page_no: i64,
    total_pages: i64,
) -> bool {
    let normalized = normalize_title(text);
    if normalized.is_empty() {
        return false;
    }
    if is_notes_heading_match(&normalized) {
        return false;
    }
    if looks_like_course_listing_page(text, page_no, total_pages) {
        return false;
    }
    if looks_like_copyright_front_matter_page(text, page_no, total_pages) {
        return false;
    }
    if !headings.is_empty() && looks_like_prose_after_heading(text) {
        return true;
    }
    looks_like_prose_after_heading(text)
}

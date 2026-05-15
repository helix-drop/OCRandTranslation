//! Title key 提取。←→ Python `_heading_graph_title_key()`。

use fnm_core::title::{chapter_title_match_key, normalize_title};
use once_cell::sync::Lazy;
use regex::Regex;

static LATEX_NOTE_MARKER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\$?\^?\{?\d+\}?\$?").unwrap());
static INLINE_NOTE_MARKER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\[(?:\d{1,4}[a-z]?|[ivxlcdm]+)\]").unwrap());
static _TRAILING_NOTE_MARKER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\s*(?:\d{1,4}[a-z]?|[ivxlcdm]+)\s*$").unwrap());
static LEADING_QUOTES_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"^[\s\u{0022}\u{0027}\u{00AB}\u{00BB}\u{201C}\u{201D}\u{2018}\u{2019}]+"#).unwrap()
});
static LEADING_CHAPTER_LABEL_WITH_NUMBER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:chapter|chapitre|part|section)\s+(?:\d+|[ivxlcdm]+)\b[:\s\-]*").unwrap()
});
static LEADING_CHAPTER_LABEL_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:chapter|chapitre|part|section)\b[:\s\-]*").unwrap());
static LEADING_NUMBER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:\d+|[ivxlcdm]+)[\.\):\-]?\s+").unwrap());
static PLAIN_NUMBER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:\d+|[ivxlcdm]+)\s*$").unwrap());
static CHAPTER_NUMBER_LABEL_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:chapter|chapitre)\s+(\d+|[ivxlcdm]+)\s*$").unwrap());

/// 提取 heading_graph 用的 title key。
/// 剥离 LaTeX marker、引号、chapter label、编号。
pub fn heading_graph_title_key(title: &str) -> String {
    let mut text = normalize_title(title);
    if text.is_empty() {
        return String::new();
    }
    // 剥离 LaTeX note marker
    text = LATEX_NOTE_MARKER_RE.replace_all(&text, "").to_string();
    // 剥离 inline note marker [N]
    text = INLINE_NOTE_MARKER_RE.replace_all(&text, "").to_string();
    // 剥离引号
    text = LEADING_QUOTES_RE.replace(&text, "").to_string();
    // 剥离 chapter label + number
    text = LEADING_CHAPTER_LABEL_WITH_NUMBER_RE
        .replace(&text, "")
        .to_string();
    // 剥离 chapter label
    text = LEADING_CHAPTER_LABEL_RE.replace(&text, "").to_string();
    // 剥离前导编号
    text = LEADING_NUMBER_RE.replace(&text, "").to_string();
    text = text.trim().to_string();
    if text.is_empty() {
        return String::new();
    }
    chapter_title_match_key(&text)
}

/// 判断文本是否为纯章节编号（`1`、`Chapter I`）。
pub fn is_chapter_number_candidate(text: &str) -> bool {
    let normalized = normalize_title(text);
    PLAIN_NUMBER_RE.is_match(&normalized) || CHAPTER_NUMBER_LABEL_RE.is_match(&normalized)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn title_key_basic() {
        let key = heading_graph_title_key("Chapter 1: Introduction");
        assert!(!key.is_empty());
    }

    #[test]
    fn title_key_strips_latex() {
        let key = heading_graph_title_key(r"Title$^{42}$");
        assert!(!key.contains("42"));
    }

    #[test]
    fn chapter_number_candidate() {
        assert!(is_chapter_number_candidate("1"));
        assert!(is_chapter_number_candidate("Chapter I"));
        assert!(!is_chapter_number_candidate("Introduction"));
    }
}

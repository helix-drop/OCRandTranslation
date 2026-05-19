//! ←→ FNM_RE/stages/export.py `_looks_like_sentence_section_heading()`,
//! `_is_exportable_section_head()`, `_build_section_heads_by_page()`
//! and section_heads.py `_section_title_text_is_plausible()`

use std::collections::{HashMap, HashSet};

use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::records::SectionHeadRecord;
use fnm_core::title::normalize_title;

static SECTION_HEAD_FORBIDDEN_PREFIX_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\d+\.\s*(?:ibid|cf\.?|see|supra|infra)\b").unwrap());

static SECTION_HEAD_INLINE_NOTE_TRACE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)(?:<sup>|\[\^[^\]]+\]|\$\s*\^\{[^}]+\}\s*\$)").unwrap());

static SECTION_HEAD_QUOTE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r#"^\s*["\u201C\u201D\u00AB\u00BB\u2039\u203A\u300C\u300D\u300E\u300F].*["\u201C\u201D\u00AB\u00BB\u2039\u203A\u300C\u300D\u300E\u300F]\s*$"#,
    )
    .unwrap()
});

/// 匹配结尾的噪音词或空壳短语（从 section_heads.py 移植）。
static SECTION_TITLE_NOISE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:to the|and|or|the|a|an|in the|of the|for the|with the|by the|at the|on the|from the|is a|are|was|were|has|have|had|been|being|it is|that is|this is|there are|there is|\.\s*\)|\]\s*$|\b(?:tices|nomics|ology|ophy|istry|ments|ances|ities|tions|sions|ments)\s*$)\s*$",
    ).unwrap()
});

static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

/// 判断节标题是否是完整句子（应排除以免渲染为标题）。
///
/// ←→ Python `_looks_like_sentence_section_heading()` (export.py:139)
pub fn looks_like_sentence_section_heading(text: &str) -> bool {
    let normalized = WHITESPACE_RE.replace_all(text.trim(), " ");
    let normalized = normalized.trim().to_string();
    if normalized.is_empty() {
        return true;
    }
    let words: Vec<&str> = normalized.split(' ').filter(|p| !p.is_empty()).collect();
    if words.len() >= 16 || normalized.len() >= 110 {
        return true;
    }
    if normalized.ends_with('!') || normalized.ends_with(';') {
        return true;
    }
    if SENTENCE_SEPARATOR_RE.is_match(&normalized) {
        return true;
    }
    false
}

static SENTENCE_SEPARATOR_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"[.!;]\s+[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u00FF]").unwrap());

/// 判断节标题是否可导出（排除噪音、引用痕迹、句结构等）。
///
/// ←→ Python `_is_exportable_section_head()` (export.py:153)
pub fn is_exportable_section_head(head: &SectionHeadRecord) -> bool {
    let title = WHITESPACE_RE
        .replace_all(head.title.trim(), " ")
        .trim()
        .to_string();
    if title.is_empty() || title == "*" {
        return false;
    }
    if SECTION_HEAD_FORBIDDEN_PREFIX_RE.is_match(&title) {
        return false;
    }
    if SECTION_HEAD_INLINE_NOTE_TRACE_RE.is_match(&title) {
        return false;
    }
    if SECTION_HEAD_QUOTE_RE.is_match(&title) {
        return false;
    }
    if !section_title_text_is_plausible(&title) {
        return false;
    }
    if looks_like_sentence_section_heading(&title) {
        return false;
    }
    true
}

/// 节标题是否"合理"（噪音阈值检查，从 section_heads.py 移植）。
///
/// ←→ Python `_section_title_text_is_plausible()` (section_heads.py:63)
fn section_title_text_is_plausible(title: &str) -> bool {
    let normalized = normalize_title(title);
    if normalized.is_empty() {
        return false;
    }
    let words: Vec<&str> = normalized.split_whitespace().collect();
    if SECTION_TITLE_NOISE_RE.is_match(&normalized) {
        return false;
    }
    if words.len() == 1 && normalized.len() < 12 {
        return false;
    }
    if !section_title_starts_like_heading(&normalized) {
        return false;
    }
    if words.len() < 3 && normalized.len() < 18 {
        return section_title_starts_like_heading(&normalized);
    }
    true
}

const OPENING_QUOTES: &[char] = &[
    '"', '\u{201C}', '\u{201D}', '\u{00AB}', '\u{00BB}', '\u{2039}', '\u{203A}', '\u{300C}',
    '\u{300D}', '\u{300E}', '\u{300F}',
];

/// ←→ Python `_section_title_starts_like_heading()` (section_heads.py:57)
fn section_title_starts_like_heading(title: &str) -> bool {
    let stripped = normalize_title(title)
        .trim_start_matches(OPENING_QUOTES)
        .to_string();
    let first_alpha = stripped.chars().find(|c| c.is_alphabetic());
    first_alpha.is_none_or(|c| c.is_uppercase())
}

/// 按页构建可导出的节标题映射。
///
/// ←→ Python `_build_section_heads_by_page()` (export.py:356)
pub fn build_section_heads_by_page(
    chapter_id: &str,
    section_heads: &[SectionHeadRecord],
    chapter_pages: &HashSet<i64>,
) -> HashMap<i64, Vec<String>> {
    let mut payload: HashMap<i64, Vec<String>> = HashMap::new();
    for head in section_heads {
        if head.chapter_id != chapter_id {
            continue;
        }
        let page_no = head.page_no;
        if page_no <= 0 || (!chapter_pages.is_empty() && !chapter_pages.contains(&page_no)) {
            continue;
        }
        if !is_exportable_section_head(head) {
            continue;
        }
        let title = WHITESPACE_RE
            .replace_all(head.title.trim(), " ")
            .trim()
            .to_string();
        if title.is_empty() {
            continue;
        }
        payload.entry(page_no).or_default().push(title);
    }
    payload
}

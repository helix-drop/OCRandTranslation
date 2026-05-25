//! ←→ page_partition.py: 所有 _looks_like_* / _is_* 启发式判定函数 + 正则池。
#![allow(dead_code)]

use fnm_core::records::PagePartitionRecord;
use fnm_core::title::{guess_title_family, normalize_title};
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashMap;

// ── Regex 池 ──────────────────────────────────────────────────

static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

static COURS_CF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)cours (?:de|au).*(?:coll[eè]ge de france)").unwrap());

static COPYRIGHT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\b(?:isbn|all rights reserved|printed in|copyright|code de la propriété intellectuelle)\b|^[©©]",
    )
    .unwrap()
});

static TRAILING_YEAR_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\d{4}\s*$").unwrap());

static TRAILING_PAGENO_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b\d{1,4}\s*$").unwrap());

static PROSE_WORD_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?i)[a-zà-ÿ]{4,}").unwrap());

/// 12 个版权/论文等 front_matter 判定正则（预编译为 Vec，避免每次调用都重建）。
static FRONT_MATTER_PATTERNS: Lazy<Vec<Regex>> = Lazy::new(|| {
    [
        r"^a dissertation$",
        r"^presented to the faculty$",
        r"^of .*university$",
        r"^in candidacy for the degree$",
        r"^doctor of philosophy$",
        r"^copyright\b",
        r"^all rights reserved$",
        r"^library of congress\b",
        r"^printed in\b",
        r"^isbn\b",
        r"^[©©]",
        r"^code de la propriété intellectuelle\b",
    ]
    .iter()
    .map(|p| Regex::new(&format!("(?i){}", p)).unwrap())
    .collect()
});

static SUP_MARKER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\^\{\d+\}|\$\s*\^\{\d+\}\s*\$|<sup>\s*\d+\s*</sup>").unwrap());

static SENTENCE_END_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[.!?。！？]").unwrap());

static LATIN_LETTER_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[a-zà-ÿ]").unwrap());

/// 匹配 frozen ref token (NOTE_REF / FN_REF / EN_REF) 或可见 markdown 引用 [^N]。
static FROZEN_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\{\{(?:NOTE|FN|EN)_REF:[^}]+\}\}|\[\^[^\]]+\]").unwrap());

static NOTES_HEADER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:#+\s*)?(notes?|endnotes?|notes to pages?.*)\s*$").unwrap()
});

static MARKDOWN_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s{0,3}(#{1,6})\s*(.+?)\s*$").unwrap());

static ARCHIVE_NOISE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)(digitized by the internet archive|the quick brown fox)").unwrap()
});

static TOC_LINE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^\s*(?:\d+(?:\.\d+)*|[A-Za-z]?\d+(?:\.\d+)*)[\.\)]?\s+.+?\s+\d+\s*$").unwrap()
});

static FIGURE_LIST_LINE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:fig(?:ure)?\.?|table|appendix)\s*[A-Za-z0-9\.\-]*\s+.+?\s+\d+\s*$")
        .unwrap()
});

static DOT_LEADER_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\.{3,}\s*(?:\d{1,4})?\s*$").unwrap());

static LECTURE_TITLE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?i)\ble[cç]on du\b").unwrap());

static TABLE_TOC_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^(?:table|table des mati[eè]res|sommaire)\b").unwrap());

static YEAR_RANGE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?:\(|\b)(\d{4})\s*-\s*(\d{4})(?:\)|\b)").unwrap());

static YEAR_TOKEN_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\b(?:1[6-9]\d{2}|20\d{2})\b").unwrap());

static BIBLIO_CITATION_HINT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\b(?:Paris|Gallimard|Vrin|Press|University Press|trad\.?|pp\.|vol\.|n°|coll\.|Éditions?|Mercure de France|Cahiers du Sud|Rivages|Belin|Flammarion|Archimbaud)\b",
    )
    .unwrap()
});

static INDEX_ENTRY_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?m)(?:^|[\n])\s*[A-ZÀ-ÖØ-Þ][^:\n]{1,120}:\s*\d{1,4}(?:[-–]\d{1,4})?(?:,\s*\d{1,4}(?:[-–]\d{1,4})?){0,12}\.?",
    )
    .unwrap()
});

static ILLUSTRATION_CONTENT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)(?:©|cm\b|mus[ée]e|biblioth[eè]que|gravure|huile|lithograph|dessin|eau-forte|collection)").unwrap()
});

static CHAPTER_KEYWORD_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)\b(chapter|chapitre|lecture|lesson|le[cç]on|prologue|epilogue)\b|^\s*(?:part|partie|livre|book)\s+(?:[ivxlcm]+|\d+)\b").unwrap()
});

static MAIN_NUMBERED_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^(?:chapter\s+)?(?:\d+|[IVXLCMivxlcm]+)[\.\):\-]?\s+\S+").unwrap()
});

// TOC_FORCE_EXPORT_TITLE_RE 已 dedup → `fnm_core::title::FRONT_MATTER_FORCE_EXPORT_TITLE_RE`

static MU_HTML_TAG_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"<[^>]+>").unwrap());

static NOTE_DEF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(\d{1,4}[A-Za-z]?)\s*[\.,\)\]]\s*(.*\S.*)?$").unwrap());

static NOTE_DEF_OCR_SPLIT_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(\d{1,4}[A-Za-z]?)\s+[Il1]\s*[\.,\)\]]\s*(.*\S.*)?$").unwrap());

static LEADING_OCR_NOTE_PUNCT_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^[\.,:;·•]+").unwrap());

static TOC_EXPLICIT_CHAPTER_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"^(?:chapter|chapitre)\b|^(?:\d+|[ivxlcm]+)[\.\):\-]\s+\S+|\ble[cç]on du\b|\bcours\b|\bprologue\b|\bepilogue\b|\bconclusion\b",
    )
    .unwrap()
});

static BIBLIO_AUTHOR_ENTRY_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?:^|[.;]\s+)(?:[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'’\-]+(?:,\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'’\-]+){0,2},)",
    )
    .unwrap()
});

/// 插图延续页的编号入口检测。
static NUMBERED_ENTRY_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b\d{1,3}\.\s+\S").unwrap());

/// `_ENDNOTES_HINT_STOP_REASONS` — 遇到这些 reason 时停止 endnotes_start_page_hint 传播。
pub(crate) const ENDNOTES_HINT_STOP_REASONS: &[&str] = &[
    "rear_sparse_other",
    "rear_toc_tail",
    "rear_author_blurb",
    "bibliography",
    "index",
    "illustrations",
];

// ── 文本工具 ──────────────────────────────────────────────────

pub(crate) fn is_notes_heading_match(heading: &str) -> bool {
    let h = normalize_title(heading);
    !h.is_empty() && NOTES_HEADER_RE.is_match(&h)
}

fn strip_markdown_heading(text: &str) -> String {
    if let Some(caps) = MARKDOWN_HEADING_RE.captures(text.trim()) {
        return normalize_title(caps.get(2).map(|m| m.as_str()).unwrap_or(""));
    }
    normalize_title(text)
}

fn plain_text_lines(text: &str) -> Vec<String> {
    let raw = MU_HTML_TAG_RE.replace_all(text, " ");
    raw.split('\n')
        .map(|line| WHITESPACE_RE.replace_all(line.trim(), " ").to_string())
        .filter(|line| !line.is_empty())
        .collect()
}

fn uppercase_ratio(text: &str) -> f64 {
    let letters: Vec<char> = text.chars().filter(|c| c.is_alphabetic()).collect();
    if letters.is_empty() {
        return 0.0;
    }
    let uppers = letters.iter().filter(|c| c.is_uppercase()).count();
    uppers as f64 / letters.len().max(1) as f64
}

fn chapter_keyword_strength(title: &str) -> i64 {
    let text = normalize_title(title);
    if text.is_empty() {
        return 0;
    }
    if CHAPTER_KEYWORD_RE.is_match(&text) {
        return 2;
    }
    if MAIN_NUMBERED_TITLE_RE.is_match(&text) {
        return 1;
    }
    0
}

fn is_toc_force_export_title(title: &str) -> bool {
    fnm_core::title::matches_front_matter_force_export(&normalize_title(title))
}

pub(crate) fn is_visual_toc_explicit_chapter_title(title: &str) -> bool {
    let normalized = normalize_title(title);
    if normalized.is_empty() {
        return false;
    }
    if is_toc_force_export_title(&normalized) {
        return true;
    }
    if MAIN_NUMBERED_TITLE_RE.is_match(&normalized) {
        return true;
    }
    TOC_EXPLICIT_CHAPTER_TITLE_RE.is_match(&normalized)
}

/// 检查 text 是否可以用作强 body 边界判定。
/// ←→ Python `_is_strong_body_boundary_page`（简化版：直接传 headings 代替 page_row）
pub(crate) fn is_strong_body_boundary(headings: &[String], page_no: i64, total_pages: i64) -> bool {
    let first_heading = headings.first().cloned().unwrap_or_default();
    if first_heading.is_empty() {
        return false;
    }
    let normalized = normalize_title(&first_heading);
    if normalized.is_empty() {
        return false;
    }
    if is_notes_heading_match(&normalized) {
        return false;
    }
    if LECTURE_TITLE_RE.is_match(&normalized) {
        return true;
    }
    if is_visual_toc_explicit_chapter_title(&normalized) {
        return true;
    }
    let family = fnm_core::title::guess_title_family(&normalized, page_no, total_pages);
    family == "chapter"
}

/// 检查 body 入口页（简化版：直接传 text/headings 代替 page_row）。
/// ←→ Python `_is_body_entry_page`
pub(crate) fn is_body_entry_page(
    text: &str,
    headings: &[String],
    page_no: i64,
    total_pages: i64,
) -> bool {
    if is_strong_body_boundary(headings, page_no, total_pages) {
        return true;
    }
    let first_heading = headings.first().cloned().unwrap_or_default();
    let normalized = normalize_title(&first_heading);
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
    looks_like_prose_after_heading(text)
}

pub(crate) fn note_def_match(line: &str) -> bool {
    let candidate = line.trim();
    if candidate.is_empty() {
        return false;
    }
    let candidate = if MARKDOWN_HEADING_RE.is_match(candidate) {
        normalize_title(
            MARKDOWN_HEADING_RE
                .captures(candidate)
                .and_then(|c| c.get(2))
                .map(|m| m.as_str())
                .unwrap_or(""),
        )
    } else {
        candidate.to_string()
    };
    let candidate = LEADING_OCR_NOTE_PUNCT_RE.replace_all(&candidate, "");
    NOTE_DEF_RE.is_match(&candidate) || NOTE_DEF_OCR_SPLIT_RE.is_match(&candidate)
}

pub(crate) fn looks_like_note_continuation_page(
    text: &str,
    page_no: i64,
    total_pages: i64,
) -> bool {
    let normalized = text.trim();
    if normalized.is_empty() {
        return false;
    }
    if page_no <= (8).max((total_pages as f64 * 0.03) as i64) {
        return false;
    }
    let lines = plain_text_lines(normalized);
    if lines.is_empty() {
        return false;
    }
    if is_notes_heading_match(&lines[0]) {
        return true;
    }
    let note_def_count = lines.iter().filter(|l| note_def_match(l)).count();
    if note_def_count < 2 {
        return false;
    }
    if lines.len() < 5 {
        return false;
    }
    let first_note_index = lines.iter().position(|l| note_def_match(l));
    match first_note_index {
        None => return false,
        Some(idx) if idx > 3 => return false,
        Some(idx) => {
            let prelude_lines: Vec<&String> = lines.iter().take(idx).collect();
            if note_def_count >= 2
                && !prelude_lines.is_empty()
                && prelude_lines
                    .iter()
                    .all(|l| MARKDOWN_HEADING_RE.is_match(l.trim()) || l.len() <= 80)
            {
                return true;
            }
        }
    }
    let non_note_line_count = lines.len().saturating_sub(note_def_count);
    if non_note_line_count <= 1 && note_def_count >= 2 {
        return true;
    }
    let first_content = lines
        .iter()
        .find(|l| !is_notes_heading_match(l))
        .cloned()
        .unwrap_or_default();
    if !first_content.is_empty() && note_def_match(&first_content) {
        return note_def_count >= 2;
    }
    note_def_count >= (4).max(lines.len() / 2)
}

/// 判断紧邻已确认 note 区之前的页面是否也是尾注开头页。
///
/// 与 `looks_like_note_continuation_page` 不同，首张尾注页允许在编号定义前包含
/// 缩略语或章节标题；相邻 note 页由 caller 作为必要的正向证据。
/// ←→ Python `_looks_like_note_continuation_page` 的首张页缺口修复。
pub(crate) fn looks_like_note_leading_page(text: &str, page_no: i64, total_pages: i64) -> bool {
    if page_no <= (8).max((total_pages as f64 * 0.03) as i64) {
        return false;
    }
    let lines = plain_text_lines(text);
    if lines.iter().any(|line| is_notes_heading_match(line)) {
        return false;
    }
    lines.len() >= 4 && lines.iter().filter(|line| note_def_match(line)).count() >= 2
}

pub(crate) fn looks_like_bibliography_continuation_page(text: &str) -> bool {
    let normalized: String = plain_text_lines(text).join(" ");
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
    let normalized: String = plain_text_lines(text).join(" ");
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
    let family = fnm_core::title::guess_title_family(&first_heading, page_no, total_pages);
    if matches!(family, "bibliography" | "index" | "illustrations") {
        return family.to_string();
    }
    String::new()
}

// ── 启发式判定 ───────────────────────────────────────────────

pub(crate) fn is_archive_noise(text: &str) -> bool {
    ARCHIVE_NOISE_RE.is_match(text)
}

pub(crate) fn looks_like_course_listing_page(text: &str, page_no: i64, total_pages: i64) -> bool {
    if page_no > (20).max(total_pages * 8 / 100) {
        return false;
    }
    let lines = plain_text_lines(text);
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
    let lines = plain_text_lines(text);
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
    let lines = plain_text_lines(text);
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
    if chapter_keyword_strength(&normalized_headings[0]) >= 1
        || chapter_keyword_strength(&normalized_headings[1]) >= 1
    {
        return false;
    }
    if uppercase_ratio(&normalized_headings[1]) < 0.45 {
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
    let lines = plain_text_lines(normalized);
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

pub(crate) fn looks_like_title_page(
    text: &str,
    headings: &[String],
    page_no: i64,
    total_pages: i64,
) -> bool {
    if page_no > (18).max(total_pages * 8 / 100) {
        return false;
    }
    let lines = plain_text_lines(text);
    if lines.is_empty() {
        return false;
    }
    let first_heading = headings.first().cloned().unwrap_or_default();
    if !first_heading.is_empty()
        && chapter_keyword_strength(&first_heading) >= 1
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
    let heading_like = headings.iter().any(|h| uppercase_ratio(h) >= 0.55);
    let line12: Vec<&String> = lines.iter().take(12).collect();
    if line12.len() <= 12
        && short_lines >= (2).max(line12.len().saturating_sub(2))
        && (heading_like
            || !headings.is_empty()
            || uppercase_ratio(&lines.iter().take(8).cloned().collect::<Vec<_>>().join(" "))
                >= 0.55)
    {
        return true;
    }
    false
}

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
    let lines = plain_text_lines(&body);
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
    // 简化版：计算 NOTE_REF / FN_REF / EN_REF / [^...] 的出现次数
    FROZEN_REF_RE.find_iter(text).count()
}

// ── 汇总 ──────────────────────────────────────────────────────

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

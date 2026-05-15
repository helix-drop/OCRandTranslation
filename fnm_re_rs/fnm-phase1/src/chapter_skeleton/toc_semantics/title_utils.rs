//! 标题规范化工具链。←→ Python toc_semantics.py 中的标题工具函数。

use fnm_core::title::{chapter_title_match_key, normalize_title, normalized_title_key};
use once_cell::sync::Lazy;
use regex::Regex;

// ── 正则常量 ──────────────────────────────────────────────────────────────────

pub static TOC_LEADING_NUMBER_PREFIX_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:(?:chapter|chapitre|part|partie|section|book|livre)\s+)?(?:\d+|[ivxlcm]+)[\.\):\-–—]?\s+").unwrap()
});

pub static TOC_PURE_NUMBER_TITLE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:\d+|[ivxlcm]+)\s*$").unwrap());

pub static MARKDOWN_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s{0,3}#{1,6}\s*(.+?)\s*$").unwrap());

pub static NOTES_HEADER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:#+\s*)?(notes?|endnotes?|notes to pages?.*)\s*$").unwrap()
});

pub static NOTE_DEF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(?:\d{1,4}[A-Za-z]?\s*[\.\)\]]|\[[0-9]{1,4}\])\s+").unwrap());

pub static HTML_TAG_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"<[^>]+>").unwrap());

pub static LECTURE_TITLE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\ble[cç]on du\b").unwrap());

pub static MAIN_NUMBERED_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^(?:chapter\s+)?(?:\d+|[IVXLCMivxlcm]+)[\.\):\-]?\s+\S+").unwrap()
});

pub static TOC_NON_BODY_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(concat!(
        r"(?i)^\s*(?:",
        r"contents?|table(?:\s+of\s+contents)?|table des mati[eè]res|sommaire|",
        r"illustrations?|list of illustrations|liste des illustrations|tables and maps|figures and tables|",
        r"bibliograph(?:y|ie)?|references?|works cited|index|indices?|",
        r"appendix|appendices|annex(?:es)?|glossary|note on sources|sources?|",
        r"conventions|abbreviations?|list of abbreviations|liste des abr[eé]viations|",
        r"acknowledg(?:e)?ments?|remerciements?|",
        r"notes?(?:\s+to\b.*)?|endnotes?|back matter",
        r")\b",
    ))
    .unwrap()
});

pub static TOC_FORCE_EXPORT_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:introduction|avertissement|pr[eé]face|foreword|epilogue|conclusion)\b")
        .unwrap()
});

pub static TOC_EXCLUDED_FAMILIES: &[&str] = &[
    "contents",
    "illustrations",
    "bibliography",
    "index",
    "appendix",
];

/// 连续 dot-leader 字符（4+ 个 .·•…,:;）匹配。
pub(crate) static DOT_LEADER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\s[.\u{2026},:;•·]{4,}.*$").unwrap());

/// OCR 误读 "'=b" → "'emb" 修复。
static EMB_TYPO_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?i)'=b").unwrap());

/// 字母间单个 '=' 号 → "em" 修复。
static EQUAL_LIGATURE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"([A-Za-zÀ-ÿ])=([A-Za-zÀ-ÿ]{2,})").unwrap());

/// 保留字母数字和 -_ 的字符过滤。
static NON_ALPHANUM_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^0-9A-Za-z_\-]+").unwrap());

/// 年份匹配（1900s-2000s）。
static YEAR_19XX_20XX_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b(?:19|20)\d{2}\b").unwrap());

/// Notes to Something 标题匹配。
static NOTES_TO_SOMETHING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*notes?\s+to\s+\S+").unwrap());

static _CHAPTER_KEYWORD_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\b(?:chapter|chapitre|lecture|leçon|prologue|epilogue|postambule|appendix|appendices|part)\b",
    )
    .unwrap()
});

static VISUAL_TOC_CHAPTER_KEYWORD_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(concat!(
        r"(?i)\b(chapter|chapitre|lecture|lesson|le[cç]on|prologue|epilogue)\b",
        r"|^\s*(?:part|partie|livre|book)\s+(?:[ivxlcm]+|\d+)\b",
    ))
    .unwrap()
});

static LECTURE_TRAILING_PAGE_SUFFIX_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^(?P<title>.*\ble[cç]on du\b.+?)\s*(?:[+\-–—]\s*)?(?P<page>\d{1,4})\s*$")
        .unwrap()
});

static LECTURE_COLLECTION_EXCLUDED_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:cours,\s*ann[eé]e\s*1978-1979|avertissement|situation du cours)\s*$")
        .unwrap()
});

static LECTURE_COLLECTION_BOUNDARY_TITLE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:situation du cours)\s*$").unwrap());

static ENDNOTE_NAMED_SUBENTRY_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:chapter|chapitre|part|partie|book|livre|lecture|lesson|le[cç]on|section|introduction|conclusion|prologue|epilogue)\b",
    )
    .unwrap()
});

static ENDNOTE_NUMBERED_SUBENTRY_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:\d+|[ivxlcm]+)[\.\):\-]\s+\S+").unwrap());

static _YEAR_RANGE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?:\(|\b)(\d{4})\s*-\s*(\d{4})(?:\)|\b)").unwrap());

// ── 标题规范化工具 ────────────────────────────────────────────────────────────

/// 剥离 TOC 标题尾部的噪声字符（dot-leader、标点等）。
pub fn strip_trailing_toc_noise(title: &str) -> String {
    let mut normalized = normalize_title(title);
    while normalized.ends_with(|c: char| {
        matches!(
            c,
            ' ' | '.' | '·' | '•' | '…' | ',' | ':' | ';' | '\'' | '-'
        )
    }) {
        normalized.pop();
        normalized = normalized.trim_end().to_string();
    }
    normalized
}

/// 剥离 TOC 标题前导的编号前缀。
pub fn strip_leading_toc_number_prefix(title: &str) -> String {
    let mut normalized = strip_trailing_toc_noise(title);
    let mut previous = String::new();
    while normalized != previous {
        previous = normalized.clone();
        let replaced = TOC_LEADING_NUMBER_PREFIX_RE
            .replace(&normalized, "")
            .to_string();
        normalized = replaced.trim().to_string();
    }
    normalized
}

/// 生成语义 title key（可选剥离编号前缀）。
pub fn semantic_visual_toc_title_key(title: &str, strip_number_prefix: bool) -> String {
    let normalized = if strip_number_prefix {
        strip_leading_toc_number_prefix(title)
    } else {
        strip_trailing_toc_noise(title)
    };
    normalized_title_key(&normalized)
}

/// 判断标题是否有前导编号前缀。
pub fn has_leading_toc_number_prefix(title: &str) -> bool {
    let normalized = strip_trailing_toc_noise(title);
    if normalized.is_empty() {
        return false;
    }
    normalized != strip_leading_toc_number_prefix(title)
}

/// 判断标题是否为纯数字。
pub fn is_pure_number_toc_title(title: &str) -> bool {
    TOC_PURE_NUMBER_TITLE_RE.is_match(&strip_trailing_toc_noise(title))
}

/// 规范化 visual TOC item 标题：去 dot-leader、修 OCR 错误。
pub fn normalize_visual_toc_item_title(value: &str) -> String {
    let mut normalized = normalize_title(value);
    if normalized.is_empty() {
        return String::new();
    }
    // 剥离 dot-leader（连续 4+ 个 .·•…,:;）
    let re_dot_leader = &*DOT_LEADER_RE;
    normalized = re_dot_leader.replace(&normalized, "").to_string();
    // 修 OCR 错误 '=b' → 'emb'
    let re_emb = &*EMB_TYPO_RE;
    normalized = re_emb.replace_all(&normalized, "'emb").to_string();
    // 修 OCR 错误：字母间单个 = 号 → em
    let re_eq = &*EQUAL_LIGATURE_RE;
    normalized = re_eq.replace_all(&normalized, "${1}em${2}").to_string();
    normalize_title(&normalized)
}

/// 视觉 TOC title key（用 chapter_title_match_key）。
pub fn visual_toc_title_key(title: &str) -> String {
    chapter_title_match_key(title)
}

/// visual TOC row key: (page_no, title_key)。
pub fn visual_toc_row_key(page_no: i64, title: &str) -> (i64, String) {
    (page_no, visual_toc_title_key(title))
}

/// 去重 visual TOC rows（按 (page_no, title_key)）。
pub fn dedupe_visual_toc_rows(rows: &mut Vec<TocRow>) {
    let mut seen = std::collections::HashSet::new();
    rows.retain(|row| {
        let key = visual_toc_row_key(row.page_no, &row.title);
        seen.insert(key)
    });
}

/// TOC item level 推断。
pub fn visual_toc_level(item: &crate::input::TocItem) -> i64 {
    let role_hint = super::normalize_visual_toc_role_hint(&item.role_hint);
    let depth = item.depth;
    match role_hint.as_str() {
        "container" | "endnotes" => 1,
        "chapter" => 2,
        "section" => {
            let semantic_depth = depth.max(2);
            semantic_depth + 1
        }
        "front_matter" | "back_matter" | "post_body" => 0,
        _ => {
            if item.level > 0 {
                item.level
            } else if depth >= 0 {
                depth + 1
            } else {
                1
            }
        }
    }
}

/// chapter ID 规范化。
pub fn normalize_toc_chapter_id(raw_id: &str, order: usize, title: &str) -> String {
    let raw = raw_id.trim();
    if !raw.is_empty() {
        let re = &*NON_ALPHANUM_RE;
        let normalized = re.replace_all(raw, "-").to_string();
        let normalized = normalized.trim_matches('-');
        if !normalized.is_empty() {
            return format!("toc-{}", normalized);
        }
    }
    let title_key = chapter_title_match_key(title);
    if title_key.is_empty() {
        format!("toc-ch-{:03}", order)
    } else {
        let truncated: String = title_key.chars().take(24).collect();
        format!("toc-ch-{:03}-{}", order, truncated)
    }
}

/// TOC 章节关键词强度。
pub fn visual_toc_chapter_keyword_strength(title: &str) -> i64 {
    let text = normalize_title(title);
    if text.is_empty() {
        return 0;
    }
    if VISUAL_TOC_CHAPTER_KEYWORD_RE.is_match(&text) {
        return 2;
    }
    if MAIN_NUMBERED_TITLE_RE.is_match(&text) {
        return 1;
    }
    0
}

/// 判断标题是否是显式导出标题（introduction/avertissement/préface 等）。
pub fn is_toc_force_export_title(title: &str) -> bool {
    TOC_FORCE_EXPORT_TITLE_RE.is_match(&normalize_title(title))
}

/// 判断标题是否是讲座标题。
pub fn is_lecture_title(title: &str) -> bool {
    LECTURE_TITLE_RE.is_match(title)
}

/// 判断标题是否是讲座集排除标题。
pub fn is_lecture_collection_excluded(title: &str) -> bool {
    LECTURE_COLLECTION_EXCLUDED_TITLE_RE.is_match(&normalize_title(title))
}

/// 判断标题是否是讲座集边界标题。
pub fn is_lecture_collection_boundary(title: &str) -> bool {
    LECTURE_COLLECTION_BOUNDARY_TITLE_RE.is_match(&normalize_title(title))
}

/// 规范化讲座标题，剥离末尾页码后缀。
pub fn normalize_lecture_title_and_suffix(title: &str) -> (String, bool) {
    let normalized = normalize_title(title);
    if normalized.is_empty() || !LECTURE_TITLE_RE.is_match(&normalized) {
        return (normalized, false);
    }
    if let Some(caps) = LECTURE_TRAILING_PAGE_SUFFIX_RE.captures(&normalized) {
        let candidate = normalize_title(caps.name("title").map_or("", |m| m.as_str()));
        if candidate.is_empty() {
            return (normalized, false);
        }
        // 仅在标题已包含年份时，才把末尾数字视作目录页码噪声
        if YEAR_19XX_20XX_RE.find(&candidate).is_some() {
            return (candidate, true);
        }
    }
    (normalized, false)
}

/// 规范化讲座标题（无 suffix 信息）。
pub fn normalize_lecture_title(title: &str) -> String {
    normalize_lecture_title_and_suffix(title).0
}

/// compact unique titles。
pub fn compact_unique_titles(values: &[String]) -> Vec<String> {
    let mut compact = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for title in values {
        let normalized = normalize_title(title);
        if normalized.is_empty() {
            continue;
        }
        let key = chapter_title_match_key(&normalized);
        let key = if key.is_empty() {
            normalized.to_lowercase()
        } else {
            key
        };
        if seen.contains(&key) {
            continue;
        }
        seen.insert(key);
        compact.push(normalized);
    }
    compact
}

/// endnote 子条目匹配模式。
pub fn endnote_subentry_match_mode(title: &str) -> &'static str {
    let normalized = normalize_title(title);
    if normalized.is_empty() {
        return "unknown";
    }
    let lowered = normalized.to_lowercase();
    if NOTES_TO_SOMETHING_RE.find(&lowered).is_some() {
        return "named";
    }
    if ENDNOTE_NAMED_SUBENTRY_RE.is_match(&lowered) {
        return "named";
    }
    if ENDNOTE_NUMBERED_SUBENTRY_RE.is_match(&lowered) {
        return "numbered";
    }
    if !chapter_title_match_key(&normalized).is_empty() {
        return "chapter_title";
    }
    "unknown"
}

/// 判断 rows 是否在同一页附近。
pub fn visual_toc_rows_are_nearby(left_page: i64, right_page: i64, max_gap: i64) -> bool {
    if left_page <= 0 || right_page <= 0 {
        return true;
    }
    (left_page - right_page).unsigned_abs() as i64 <= max_gap.max(0)
}

/// title family 推断。
pub fn title_family(title: &str, page_no: i64, total_pages: i64) -> String {
    fnm_core::title::guess_title_family(&normalize_title(title), page_no.max(1), total_pages.max(1))
        .to_string()
}

/// uppercase ratio（用于 book_title 判定）。
pub fn uppercase_ratio(s: &str) -> f64 {
    let letters: Vec<char> = s.chars().filter(|c| c.is_alphabetic()).collect();
    if letters.is_empty() {
        return 0.0;
    }
    let upper = letters.iter().filter(|c| c.is_uppercase()).count();
    upper as f64 / letters.len() as f64
}

/// TOC row 中间结构。
#[derive(Debug, Clone, Default)]
pub struct TocRow {
    pub item_id: String,
    pub title: String,
    pub page_no: i64,
    pub level: i64,
    pub page_role: String,
    pub family: String,
    pub non_body_title: bool,
    pub order: i64,
    pub resolved_via_heading: bool,
    pub unresolved_page: bool,
    pub explicit_role_hint: String,
    pub role_hint: String,
    pub parent_title: String,
    pub body_candidate: Option<bool>,
    pub export_candidate: Option<bool>,
    pub semantic_role: String,
    pub source: String,
}

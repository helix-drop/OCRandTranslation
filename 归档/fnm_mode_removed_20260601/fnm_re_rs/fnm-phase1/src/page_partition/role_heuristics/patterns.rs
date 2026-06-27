//! ←→ page_partition.py: 正则常量池。
//!
//! 所有 `Lazy<Regex>` 静态常量集中管理，被其他子模块共享使用。

use once_cell::sync::Lazy;
use regex::Regex;

pub(crate) static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

pub(crate) static COURS_CF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)cours (?:de|au).*(?:coll[eè]ge de france)").unwrap());

pub(crate) static COPYRIGHT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\b(?:isbn|all rights reserved|printed in|copyright|code de la propriété intellectuelle)\b|^[©©]",
    )
    .unwrap()
});

pub(crate) static TRAILING_YEAR_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\d{4}\s*$").unwrap());

pub(crate) static TRAILING_PAGENO_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\b\d{1,4}\s*$").unwrap());

pub(crate) static PROSE_WORD_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)[a-zà-ÿ]{4,}").unwrap());

/// 12 个版权/论文等 front_matter 判定正则（预编译为 Vec，避免每次调用都重建）。
pub(crate) static FRONT_MATTER_PATTERNS: Lazy<Vec<Regex>> = Lazy::new(|| {
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

pub(crate) static SUP_MARKER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\^\{\d+\}|\$\s*\^\{\d+\}\s*\$|<sup>\s*\d+\s*</sup>").unwrap());

pub(crate) static SENTENCE_END_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[.!?。！？]").unwrap());

pub(crate) static LATIN_LETTER_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[a-zà-ÿ]").unwrap());

/// 匹配 frozen ref token (NOTE_REF / FN_REF / EN_REF) 或可见 markdown 引用 [^N]。
pub(crate) static FROZEN_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\{\{(?:NOTE|FN|EN)_REF:[^}]+\}\}|\[\^[^\]]+\]").unwrap());

pub(crate) static NOTES_HEADER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:#+\s*)?(notes?|endnotes?|notes to pages?.*)\s*$").unwrap()
});

pub(crate) static MARKDOWN_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s{0,3}(#{1,6})\s*(.+?)\s*$").unwrap());

pub(crate) static ARCHIVE_NOISE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)(digitized by the internet archive|the quick brown fox)").unwrap()
});

pub(crate) static TOC_LINE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^\s*(?:\d+(?:\.\d+)*|[A-Za-z]?\d+(?:\.\d+)*)[\.\)]?\s+.+?\s+\d+\s*$").unwrap()
});

pub(crate) static FIGURE_LIST_LINE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:fig(?:ure)?\.?|table|appendix)\s*[A-Za-z0-9\.\-]*\s+.+?\s+\d+\s*$")
        .unwrap()
});

pub(crate) static DOT_LEADER_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\.{3,}\s*(?:\d{1,4})?\s*$").unwrap());

pub(crate) static LECTURE_TITLE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\ble[cç]on du\b").unwrap());

pub(crate) static TABLE_TOC_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^(?:table|table des mati[eè]res|sommaire)\b").unwrap());

pub(crate) static YEAR_RANGE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?:\(|\b)(\d{4})\s*-\s*(\d{4})(?:\)|\b)").unwrap());

pub(crate) static YEAR_TOKEN_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\b(?:1[6-9]\d{2}|20\d{2})\b").unwrap());

pub(crate) static BIBLIO_CITATION_HINT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\b(?:Paris|Gallimard|Vrin|Press|University Press|trad\.?|pp\.|vol\.|n°|coll\.|Éditions?|Mercure de France|Cahiers du Sud|Rivages|Belin|Flammarion|Archimbaud)\b",
    )
    .unwrap()
});

pub(crate) static INDEX_ENTRY_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?m)(?:^|[\n])\s*[A-ZÀ-ÖØ-Þ][^:\n]{1,120}:\s*\d{1,4}(?:[-–]\d{1,4})?(?:,\s*\d{1,4}(?:[-–]\d{1,4})?){0,12}\.?",
    )
    .unwrap()
});

pub(crate) static ILLUSTRATION_CONTENT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)(?:©|cm\b|mus[ée]e|biblioth[eè]que|gravure|huile|lithograph|dessin|eau-forte|collection)").unwrap()
});

pub(crate) static CHAPTER_KEYWORD_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)\b(chapter|chapitre|lecture|lesson|le[cç]on|prologue|epilogue)\b|^\s*(?:part|partie|livre|book)\s+(?:[ivxlcm]+|\d+)\b").unwrap()
});

pub(crate) static MAIN_NUMBERED_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^(?:chapter\s+)?(?:\d+|[IVXLCMivxlcm]+)[\.\):\-]?\s+\S+").unwrap()
});

// TOC_FORCE_EXPORT_TITLE_RE 已 dedup → `fnm_core::title::FRONT_MATTER_FORCE_EXPORT_TITLE_RE`

pub(crate) static MU_HTML_TAG_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"<[^>]+>").unwrap());

pub(crate) static NOTE_DEF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(\d{1,4}[A-Za-z]?)\s*[\.,\)\]]\s*(.*\S.*)?$").unwrap());

pub(crate) static NOTE_DEF_OCR_SPLIT_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(\d{1,4}[A-Za-z]?)\s+[Il1]\s*[\.,\)\]]\s*(.*\S.*)?$").unwrap());

pub(crate) static LEADING_OCR_NOTE_PUNCT_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^[\.,:;·•]+").unwrap());

pub(crate) static BIBLIO_AUTHOR_ENTRY_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?:^|[.;]\s+)(?:[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'\-]+(?:,\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'\-]+){0,2},)",
    )
    .unwrap()
});

/// 插图延续页的编号入口检测。
pub(crate) static NUMBERED_ENTRY_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\b\d{1,3}\.\s+\S").unwrap());

/// `_ENDNOTES_HINT_STOP_REASONS` — 遇到这些 reason 时停止 endnotes_start_page_hint 传播。
pub(crate) const ENDNOTES_HINT_STOP_REASONS: &[&str] = &[
    "rear_sparse_other",
    "rear_toc_tail",
    "rear_author_blurb",
    "bibliography",
    "index",
    "illustrations",
];

//! ←→ FNM_RE/shared/export_constants.py
//! 导出相关共享常量与辅助函数。

use once_cell::sync::Lazy;
use regex::Regex;

pub const PENDING_TRANSLATION_TEXT: &str = "[待翻译]";
pub const OBSIDIAN_EXPORT_CHAPTERS_PREFIX: &str = "chapters/";
pub const OBSIDIAN_EXPORT_INDEX_MD: &str = "index.md";

pub static NOTE_TEXT_BODY_MARKUP_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\$\s*\^\{\s*\[?\d{1,4}[A-Za-z]?\]?\s*\}\s*\$|\$\s*\^\{\s*(\*{1,4})\s*\}\s*\$|<sup>\s*\[?\d{1,4}[A-Za-z]?\]?\s*</sup>",
    )
    .unwrap()
});

pub static LEADING_RAW_NOTE_MARKER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:\[\d{1,4}[A-Za-z]?\]|\d{1,4}[A-Za-z]?[.)]|\*{1,4}\s+|<sup>\s*\d{1,4}[A-Za-z]?\s*</sup>)\s*",
    )
    .unwrap()
});

pub static CORRUPTED_NOTE_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\{\{NOTE_REF:([^}\]]+)\]\}\}").unwrap());

pub static ANY_NOTE_REF_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\{\{NOTE_REF:([^}]+)\}\}|\{\{FN_REF:([^}]+)\}\}|\{\{EN_REF:([^}]+)\}\}|\[\^([^\]]+)\]",
    )
    .unwrap()
});

pub static TRAILING_IMAGE_ONLY_BLOCK_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?s)(?:\n\s*)*(?:<div[^>]*>\s*<img\b[^>]*>\s*</div>|!\[[^\]]*\]\([^)]+\))\s*$")
        .unwrap()
});

pub static FRONT_MATTER_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^(?:preface|foreword|acknowledg(?:e)?ments?|remerciements?|avant-propos|table of contents|contents|目录)\b",
    )
    .unwrap()
});

pub static TOC_RESIDUE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?im)^\s*(?:table of contents|contents|目录)\b").unwrap());

/// 匹配正文中的 [^N] 引用（contract_summary 使用）。
pub static LOCAL_FOOTNOTE_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\[\^([0-9]+)\]").unwrap());

/// 匹配行首的 [^N]: 定义行。
pub static LOCAL_FOOTNOTE_DEF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)^\[\^([0-9]+)\]:").unwrap());

// ref_rewriter 依赖的正则
pub static RAW_BRACKET_NOTE_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\[(\d{1,4}[A-Za-z]?)\]").unwrap());

pub static RAW_SUPERSCRIPT_NOTE_REF_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\$\s*\^\{\s*\[?(\d{1,4}[A-Za-z]?)\]?\s*\}\s*\$|\$\s*\^\{\s*(\*{1,4})\s*\}\s*\$|<sup>\s*\[?(\d{1,4}[A-Za-z]?)\]?\s*</sup>|\^\{(\d{1,4})\}",
    )
    .unwrap()
});

pub static RAW_UNICODE_SUPERSCRIPT_NOTE_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)").unwrap());

/// Unicode 上标 → ASCII 数字翻译表。与 Python `_UNICODE_SUPERSCRIPT_TRANSLATION` 一致。
pub fn unicode_superscript_to_ascii(c: char) -> char {
    match c {
        '⁰' => '0',
        '¹' => '1',
        '²' => '2',
        '³' => '3',
        '⁴' => '4',
        '⁵' => '5',
        '⁶' => '6',
        '⁷' => '7',
        '⁸' => '8',
        '⁹' => '9',
        other => other,
    }
}

/// 判断是否应替换 note 定义文本。
/// 与 Python `_should_replace_definition_text` 一致。
pub fn should_replace_definition_text(existing: &str, candidate: &str) -> bool {
    let current = existing.trim();
    let payload = candidate.trim();
    if payload.is_empty() {
        return false;
    }
    if current.is_empty() {
        return true;
    }
    let current_has_body = NOTE_TEXT_BODY_MARKUP_RE.is_match(current);
    let payload_has_body = NOTE_TEXT_BODY_MARKUP_RE.is_match(payload);
    if current_has_body && !payload_has_body {
        return true;
    }
    if !current_has_body && payload_has_body {
        return false;
    }
    payload.len() > current.len()
}

//! ←→ FNM_RE/stages/export.py `_escape_leading_asterisks()`, `_normalize_markdown_content()`,
//! `_clean_export_html()`, `_strip_trailing_image_only_block()`

use once_cell::sync::Lazy;
use regex::{Captures, Regex};

use fnm_core::export_constants::TRAILING_IMAGE_ONLY_BLOCK_RE;

static LEADING_ASTERISKS_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?m)^(\*{1,4})(\s)").unwrap());

static ORDINAL_SUP_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)<sup>\s*([^\d<]+?)\s*</sup>").unwrap());

static ANY_SUP_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?i)</?sup[^>]*>").unwrap());

static DIV_TAG_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?i)</?div[^>]*>").unwrap());

/// Escape leading * and ** at line start to prevent markdown italic/bold/list.
///
/// ←→ Python `_escape_leading_asterisks()` (export.py:91)
pub fn escape_leading_asterisks(text: &str) -> String {
    LEADING_ASTERISKS_RE
        .replace_all(text, |caps: &Captures| {
            let asterisks = caps.get(1).unwrap().as_str();
            let space = caps.get(2).unwrap().as_str();
            format!("{}{}", "\\*".repeat(asterisks.len()), space)
        })
        .to_string()
}

/// Normalize markdown content: strip then ensure trailing newline.
///
/// ←→ Python `_normalize_markdown_content()` (export.py:98)
pub fn normalize_markdown_content(content: &str) -> String {
    let text = content.trim();
    if text.is_empty() {
        String::new()
    } else {
        format!("{text}\n")
    }
}

/// Clean export HTML: ordinal superscripts, div/sup tags.
///
/// ←→ Python `_clean_export_html()` (export.py:111)
pub fn clean_export_html(text: &str) -> String {
    let cleaned = ORDINAL_SUP_RE.replace_all(text, "$1");
    let cleaned = DIV_TAG_RE.replace_all(&cleaned, "");
    ANY_SUP_RE.replace_all(&cleaned, "").to_string()
}

/// Strip trailing image-only block(s) from text.
///
/// ←→ Python `_strip_trailing_image_only_block()` (export.py:128)
pub fn strip_trailing_image_only_block(text: &str) -> String {
    let mut candidate = text.trim().to_string();
    if candidate.is_empty() {
        return String::new();
    }
    loop {
        let updated = TRAILING_IMAGE_ONLY_BLOCK_RE
            .replace_all(&candidate, "")
            .to_string();
        let updated = updated.trim().to_string();
        if updated == candidate {
            return candidate;
        }
        candidate = updated;
    }
}

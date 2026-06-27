//! ←→ FNM_RE/stages/export.py `_normalized_paragraph_key()`
//!
//! 段落键归一化：去除 footnote ref → 压缩空白 → 小写。

use once_cell::sync::Lazy;
use regex::Regex;

static FOOTNOTE_REF_IN_KEY_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[\^[^\]]+\]").unwrap());

static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

/// 归一化段落键——去除注引、压缩空白、转小写。
///
/// ←→ Python `_normalized_paragraph_key()` (export.py:659)
pub fn normalized_paragraph_key(text: &str) -> String {
    let normalized = text.trim().to_lowercase();
    let normalized = FOOTNOTE_REF_IN_KEY_RE.replace_all(&normalized, "");
    let normalized = WHITESPACE_RE.replace_all(&normalized, " ");
    normalized.trim().to_string()
}

//! ←→ FNM_RE/shared/note_lookup.py
//! Note text 清理共享工具。

use once_cell::sync::Lazy;
use regex::Regex;

static NOTE_TEXT_BODY_MARKUP_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"</?[biu]>|\[/?[biu]\]").unwrap());

static LEADING_RAW_NOTE_MARKER_RE: Lazy<Regex> = Lazy::new(|| {
    // ←→ Python `_LEADING_RAW_NOTE_MARKER_RE`（export_constants.py:21-23）:
    // 覆盖 [N], N. N) N], *..**** , <sup>N</sup> 等格式。
    Regex::new(
        r"^\s*(?:\[\d{1,4}[A-Za-z]?\]|\d{1,4}[A-Za-z]?[\.\)\]]|\*{1,4}\s+|<sup>\d{1,4}</sup>)\s*",
    )
    .unwrap()
});

static WHITESPACE_COLLAPSE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

/// 清理 note text：去除 body markup、leading marker、压缩空白。
/// 与 Python `_sanitize_note_text` 一致。
pub fn sanitize_note_text(text: &str) -> String {
    let payload = text.trim();
    let payload = NOTE_TEXT_BODY_MARKUP_RE.replace_all(payload, "");
    let payload = LEADING_RAW_NOTE_MARKER_RE.replace(&payload, "");
    let payload = WHITESPACE_COLLAPSE_RE.replace_all(&payload, " ");
    payload.trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_basic() {
        assert_eq!(sanitize_note_text("1. Some note text."), "Some note text.");
    }

    #[test]
    fn sanitize_markup() {
        assert_eq!(sanitize_note_text("[i]italic text[/i]"), "italic text");
    }

    #[test]
    fn sanitize_empty() {
        assert_eq!(sanitize_note_text(""), "");
    }
}

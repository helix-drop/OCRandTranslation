//! ←→ FNM_RE/shared/anchors.py 子集（resolve_anchor_kind + regex 常量）
//!
//! 不 port：`scan_anchor_markers`、`page_body_paragraphs` 等（留给 fnm-phase3）。

use crate::types::AnchorKind;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashSet;

// ── Regex 常量池 ────────────────────────────────────────────────

pub mod patterns {
    use super::*;
    pub static HTML_SUP_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"(?i)<sup>\s*(\d{1,4})\s*</sup>").unwrap());
    pub static LATEX_SUP_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"\$\s*\^\{(\d{1,4})\}\s*\$").unwrap());
    pub static PLAIN_SUP_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\^\{(\d{1,4})\}").unwrap());
    pub static FOOTNOTE_REF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[\^(\d{1,4})\]").unwrap());
    // 注：Rust regex 不支持 lookaround，去掉了 (?<!\d) 和 (?!\d)。
    // 消费方需结合 is_bracket_ref_valid() 过滤数字包围的情况。
    pub static BRACKET_REF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[(\d{1,4})\]").unwrap());
    pub static UNICODE_SUP_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+").unwrap());
    pub static APOSTROPHE_SUP_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"[\'`]\s*(\d{1,4})\b").unwrap());
    pub static HTML_SYMBOL_SUP_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"(?i)<sup>\s*(\*{1,4})\s*</sup>").unwrap());
    pub static LATEX_SYMBOL_SUP_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"\$\s*\^\{\s*(\*{1,4})\s*\}\s*\$").unwrap());
    // 注：去掉 lookahead (?=...)，捕获后续标点由消费方处理。
    pub static BARE_DIGIT_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s(\d{1,3})").unwrap());
    // 断裂左括号：[ 前紧跟字母/法文特殊字符，后紧跟标点（缺少右括号）。
    // 注：Rust regex 不支持 lookaround，改为连续匹配模式。
    pub static BROKEN_LEFT_BRACKET_REF_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(
            r#"[A-Za-zàâäéèêëïîôöùûüÿçœÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇŒ»"'')]\[(\d{1,4})[.,;:!?\u{2026}»"'')]]"#,
        )
        .unwrap()
    });
    // 括号后尾随符号：[N] 后跟 *、**、*** 等。
    pub static TRAILING_SYMBOL_AFTER_BRACKET_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"[\]](\*{1,4})").unwrap());
    // 引号后尾随符号：» 后跟 *、**、*** 等。
    pub static TRAILING_SYMBOL_AFTER_QUOTE_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"[»](\*{1,4})").unwrap());
}

// ── 公开 API ────────────────────────────────────────────────────

/// 判断 BRACKET_REF_RE 的捕获是否有效（前后不是数字）。
///
/// 替代 Python 端的 `(?<!\d)...(?!\d)` lookaround 断言。
/// BRACKET_REF_RE 捕获所有 `[NNNN]`，消费方须用此函数过滤伪匹配。
///
/// 注：新代码请优先用 [`valid_bracket_ref_iter`] 高阶 API——它把守卫与匹配
/// 在源头绑死，避免 caller 漏调守卫（CLAUDE.md §12 分类源头唯一）。
pub fn is_bracket_ref_valid(text: &str, match_start: usize, match_end: usize) -> bool {
    let before = match_start
        .checked_sub(1)
        .and_then(|i| text.as_bytes().get(i));
    let after = text.as_bytes().get(match_end);
    !before.is_some_and(|b| b.is_ascii_digit()) && !after.is_some_and(|b| b.is_ascii_digit())
}

/// 在 text 中按 `BRACKET_REF_RE` 扫描所有 `[NNNN]` 匹配并**已过滤伪匹配**。
///
/// 返回每个有效命中的 `(match_start, match_end, captured_marker)`——
/// 即 group(1) 捕获的数字串。把守卫与匹配在源头绑死，避免 caller 漏调
/// `is_bracket_ref_valid`（CLAUDE.md §12 第 1 条：分类源头唯一）。
///
/// # 用法
/// ```ignore
/// for (start, end, marker) in valid_bracket_ref_iter(line) {
///     if marker == target { /* ... */ }
/// }
/// ```
pub fn valid_bracket_ref_iter(text: &str) -> impl Iterator<Item = (usize, usize, &str)> {
    patterns::BRACKET_REF_RE
        .captures_iter(text)
        .filter_map(|caps| {
            let full = caps.get(0)?;
            let marker = caps.get(1)?;
            if !is_bracket_ref_valid(text, full.start(), full.end()) {
                return None;
            }
            Some((full.start(), full.end(), marker.as_str()))
        })
}

/// 判断 marker 是否像年份（1500–2100）。与 Python `looks_like_year_marker` 一致。
pub fn looks_like_year_marker(marker: &str) -> bool {
    let m = marker.trim();
    if m.len() != 4 {
        return false;
    }
    match m.parse::<i64>() {
        Ok(v) => (1500..=2100).contains(&v),
        Err(_) => false,
    }
}

/// 判定 body anchor 的 NoteKind。
/// 与 Python `resolve_anchor_kind` 一致，覆盖全部 7 个判定分支。
pub fn resolve_anchor_kind(
    has_page_footnote_band: bool,
    normalized_marker: &str,
    chapter_endnote_markers: Option<&HashSet<i64>>,
    pattern: &str,
) -> AnchorKind {
    let pat = pattern.trim();
    // 分支 1–2: bracket / broken_left_bracket → footnote if band else unknown
    if pat == "bracket" || pat == "broken_left_bracket" {
        return if has_page_footnote_band {
            AnchorKind::Footnote
        } else {
            AnchorKind::Unknown
        };
    }
    // 分支 3–5: 数字 + endnote_markers 命中 / 未命中 + band
    if let Ok(n) = normalized_marker.parse::<i64>() {
        if let Some(markers) = chapter_endnote_markers {
            if markers.contains(&n) {
                return AnchorKind::Endnote;
            }
        }
    }
    // 分支 6–7: 非 bracket + band → footnote else unknown
    if has_page_footnote_band {
        AnchorKind::Footnote
    } else {
        AnchorKind::Unknown
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn year_marker_true() {
        assert!(looks_like_year_marker("1984"));
        assert!(looks_like_year_marker("2000"));
    }

    #[test]
    fn year_marker_false() {
        assert!(!looks_like_year_marker("99"));
        assert!(!looks_like_year_marker("abcd"));
        assert!(!looks_like_year_marker("3000"));
    }

    #[test]
    fn resolve_bracket_with_band() {
        assert_eq!(
            resolve_anchor_kind(true, "1", None, "bracket"),
            AnchorKind::Footnote
        );
    }

    #[test]
    fn resolve_bracket_no_band() {
        assert_eq!(
            resolve_anchor_kind(false, "1", None, "bracket"),
            AnchorKind::Unknown
        );
    }

    #[test]
    fn resolve_endnote_match() {
        let mut markers = HashSet::new();
        markers.insert(5);
        assert_eq!(
            resolve_anchor_kind(false, "5", Some(&markers), "html"),
            AnchorKind::Endnote
        );
    }

    #[test]
    fn resolve_endnote_no_match() {
        let mut markers = HashSet::new();
        markers.insert(5);
        assert_eq!(
            resolve_anchor_kind(true, "10", Some(&markers), "html"),
            AnchorKind::Footnote
        );
    }

    #[test]
    fn resolve_non_digit_with_band() {
        assert_eq!(
            resolve_anchor_kind(true, "*", None, "latex_symbol_sup"),
            AnchorKind::Footnote
        );
    }

    #[test]
    fn bracket_ref_valid_simple() {
        assert!(is_bracket_ref_valid("[12] text", 0, 4));
        assert!(!is_bracket_ref_valid("1[12]3", 1, 5));
        assert!(!is_bracket_ref_valid("[12]3", 0, 4));
        assert!(!is_bracket_ref_valid("1[12]", 1, 5));
    }

    #[test]
    fn resolve_non_digit_no_band() {
        assert_eq!(
            resolve_anchor_kind(false, "*", None, "latex_symbol_sup"),
            AnchorKind::Unknown
        );
    }
}

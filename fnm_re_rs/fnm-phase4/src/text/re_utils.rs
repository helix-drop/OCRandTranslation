//! ←→ Python `document/text_utils.py`
//! 基础文本判断工具：heading 提取、元数据检测、句末/句中断判定、跨页续句检测。

use once_cell::sync::Lazy;
use regex::Regex;

// ── regex 常量（Lazy 静态） ──────────────────────────────────────

/// ←→ Python `r"^(#{1,6})\s+"`
static HEADING_PREFIX_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^(#{1,6})\s+").unwrap());

/// ←→ Python `_META_LINE_RE` 列表（13 个模式）
static META_LINE_PATTERNS: Lazy<Vec<Regex>> = Lazy::new(|| {
    [
        r"^https?://",
        r"^doi:\s*10\.",
        r"^10\.\d{4,}/",
        r"sagepub\.com|journals\.sagepub|springer\.com|wiley\.com",
        r"\u{00a9}.*\d{4}", // ©
        r"^article\s*reuse\s*guidelines",
        r"^SAGE$",
        r"^Article$",
        r"^\d{1,4}[\u{2013}\-]\d{1,4}$", // – or -
        r"^Vol\.\s*\d+",
        r"^Accepted:|^Received:|^Published:",
        r"^Corresponding\s+author",
        r"^(E-?mail:\s*)?\S+@\S+\.\S+$",
    ]
    .iter()
    .map(|s| Regex::new(&format!("(?i){}", s)).unwrap())
    .collect()
});

/// ←→ Python `_JOURNAL_RE`
static JOURNAL_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^(History|Journal|Annals|Bulletin|Review|Archives|Proceedings|Quarterly|American|British|European|International)\s+(of|for)\s+\w+",
    )
    .unwrap()
});

/// ←→ Python `_SUPERSCRIPT_DIGITS_RE`
static SUPERSCRIPT_DIGITS_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"[\u{2070}\u{00b9}\u{00b2}\u{00b3}\u{2074}\u{2075}\u{2076}\u{2077}\u{2078}\u{2079}]+$",
    )
    .unwrap()
});

/// ←→ Python `_BRACKET_FOOTNOTE_TAIL_RE`
static BRACKET_FOOTNOTE_TAIL_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\[\^?\d{1,4}\]\s*$").unwrap());

/// ←→ Python `_TEXTSUPERSCRIPT_TAIL_RE`
static TEXTSUPERSCRIPT_TAIL_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\\textsuperscript\{\d+\}\s*$").unwrap());

/// ←→ Python `_SENTENCE_END_RE`
/// 包含 Unicode 左右引号 \u{201c}\u{201d} 和右书名号 \u{00bb}
static SENTENCE_END_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"[.;:?!\u{3002}\u{ff1b}\u{ff1a}\u{ff01}\u{ff1f}\u{00bb}\u{201c}\u{201d}\u{2019})\]]\s*$",
    )
    .unwrap()
});

/// ←→ Python `_CONTINUATION_PREFIX_CHARS`
const CONTINUATION_PREFIX_CHARS: &str = ",.;:!?)]}\"'\u{ff0c}\u{3002}\u{ff1b}\u{ff1a}\u{ff01}\u{ff1f}\u{3001}\u{ff09}\u{300b}\u{3011}\u{300f}\u{201d}\u{2019}";

// ── 公共函数 ────────────────────────────────────────────────────

/// 提取 markdown 标题层级和纯文本。
///
/// ←→ Python `document/text_utils.py::extract_heading_level` (L18-30)
///
/// Returns: (heading_level, clean_text)
/// - heading_level: 0=正文, 1=一级标题, ..., 6=六级
pub fn extract_heading_level(s: &str) -> (i64, String) {
    if let Some(m) = HEADING_PREFIX_RE.find(s) {
        let level = m.as_str().trim_end().len() as i64;
        let clean = s[m.end()..].trim().to_string();
        (level, clean)
    } else {
        (0, s.trim().to_string())
    }
}

/// 判断单行文本是否为元数据（DOI、URL、版权声明等 13 个模式）。
///
/// ←→ Python `document/text_utils.py::_is_meta_line` (L60-71)
pub fn is_meta_line(line: &str) -> bool {
    let t = line.trim();
    if t.len() < 2 {
        return true;
    }
    for pat in META_LINE_PATTERNS.iter() {
        if pat.is_match(t) {
            return true;
        }
    }
    // 短行期刊名
    if t.len() < 60 && JOURNAL_RE.is_match(t) {
        return true;
    }
    false
}

/// 去掉句末脚注/上标标记，便于判断「真实」句末标点。
///
/// ←→ Python `document/text_utils.py::strip_trailing_footnote_markers` (L93-116)
pub fn strip_trailing_footnote_markers(text: &str) -> String {
    let mut s = text.trim_end().to_string();
    loop {
        let prev_len = s.len();
        if let Some(m) = SUPERSCRIPT_DIGITS_RE.find(&s) {
            if m.end() == s.len() {
                s = s[..m.start()].trim_end().to_string();
                continue;
            }
        }
        if let Some(m) = BRACKET_FOOTNOTE_TAIL_RE.find(&s) {
            if m.end() == s.len() {
                s = s[..m.start()].trim_end().to_string();
                continue;
            }
        }
        if let Some(m) = TEXTSUPERSCRIPT_TAIL_RE.find(&s) {
            if m.end() == s.len() {
                s = s[..m.start()].trim_end().to_string();
                continue;
            }
        }
        if s.len() == prev_len {
            break;
        }
    }
    s
}

/// 判断文本在剥离脚注尾标后，是否带有明确句终信号。
///
/// ←→ Python `document/text_utils.py::has_explicit_sentence_end` (L119-124)
pub fn has_explicit_sentence_end(text: &str) -> bool {
    let core = strip_trailing_footnote_markers(text.trim());
    if core.is_empty() {
        return false;
    }
    SENTENCE_END_RE.is_match(&core)
}

/// 判断文本是否在句子中间结束（无句终标点且长度 >= 10）。
///
/// ←→ Python `document/text_utils.py::ends_mid` (L127-133)
pub fn ends_mid(text: &str) -> bool {
    if text.is_empty() || text.trim().len() < 10 {
        return false;
    }
    let core = strip_trailing_footnote_markers(text.trim());
    if core.len() < 10 {
        return false;
    }
    !has_explicit_sentence_end(&core)
}

/// 判断文本是否以小写字母（含法语字符）开头。
///
/// ←→ Python `document/text_utils.py::starts_low` (L136-140)
pub fn starts_low(text: &str) -> bool {
    if text.is_empty() || text.trim().len() < 3 {
        return false;
    }
    let c = text.trim().chars().next().unwrap();
    c.is_lowercase() || "àâäéèêëïîôùûüÿçœæ".contains(c)
}

/// 判断文本是否以续句标点开头。
///
/// ←→ Python `document/text_utils.py::starts_with_continuation_punctuation` (L143-145)
pub fn starts_with_continuation_punctuation(text: &str) -> bool {
    let stripped = text.trim_start();
    if stripped.is_empty() {
        return false;
    }
    CONTINUATION_PREFIX_CHARS.contains(stripped.chars().next().unwrap())
}

/// 判断 next_text 是否像是 prev_text 跨页后的续句。
///
/// ←→ Python `document/text_utils.py::is_mid_sentence_continuation` (L148-167)
///
/// 规则（按优先级）：
/// 1. prev 以连字符 `-` 结尾 → true（OCR 断词）
/// 2. prev 不是句中结束 → false
/// 3. next 以小写或续句标点开头 → true
/// 4. allow_uppercase 且 next 大写开头且 prev 无显式句终 → true
pub fn is_mid_sentence_continuation(
    prev_text: &str,
    next_text: &str,
    allow_uppercase: bool,
) -> bool {
    let prev = prev_text.trim_end();
    let nxt = next_text.trim_start();
    if prev.is_empty() || nxt.is_empty() {
        return false;
    }
    if prev.ends_with('-') {
        return true;
    }
    if !ends_mid(prev) {
        return false;
    }
    if starts_low(nxt) || starts_with_continuation_punctuation(nxt) {
        return true;
    }
    if allow_uppercase
        && nxt.chars().next().unwrap().is_uppercase()
        && !has_explicit_sentence_end(prev)
    {
        return true;
    }
    false
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_heading_level_h1() {
        let (level, clean) = extract_heading_level("# Introduction");
        assert_eq!(level, 1);
        assert_eq!(clean, "Introduction");
    }

    #[test]
    fn test_extract_heading_level_h3() {
        let (level, clean) = extract_heading_level("### Deep Learning");
        assert_eq!(level, 3);
        assert_eq!(clean, "Deep Learning");
    }

    #[test]
    fn test_extract_heading_level_body() {
        let (level, clean) = extract_heading_level("plain text");
        assert_eq!(level, 0);
        assert_eq!(clean, "plain text");
    }

    #[test]
    fn test_is_meta_line_doi() {
        assert!(is_meta_line("doi: 10.1234/abc"));
    }

    #[test]
    fn test_is_meta_line_url() {
        assert!(is_meta_line("https://example.com"));
    }

    #[test]
    fn test_is_meta_line_short() {
        assert!(is_meta_line("x"));
    }

    #[test]
    fn test_is_meta_line_normal() {
        assert!(!is_meta_line("This is a normal line of text."));
    }

    #[test]
    fn test_has_explicit_sentence_end_period() {
        assert!(has_explicit_sentence_end("This is a sentence."));
    }

    #[test]
    fn test_has_explicit_sentence_end_no() {
        assert!(!has_explicit_sentence_end("This is not a sentence"));
    }

    #[test]
    fn test_strip_trailing_footnote_markers_superscript() {
        let result = strip_trailing_footnote_markers("some text.\u{2076}\u{2079}");
        assert!(!result.contains('\u{2076}'));
    }

    #[test]
    fn test_strip_trailing_footnote_markers_bracket() {
        let result = strip_trailing_footnote_markers("some text.[70]  ");
        assert_eq!(result, "some text.");
    }

    #[test]
    fn test_ends_mid_true() {
        assert!(ends_mid("this is not a complete sentence but long enough"));
    }

    #[test]
    fn test_ends_mid_false() {
        assert!(!ends_mid("This is a complete sentence."));
    }

    #[test]
    fn test_ends_mid_too_short() {
        assert!(!ends_mid("short"));
    }

    #[test]
    fn test_starts_low_true() {
        assert!(starts_low("  and then something"));
    }

    #[test]
    fn test_starts_low_false() {
        assert!(!starts_low("And then something"));
    }

    #[test]
    fn test_starts_with_continuation_punctuation() {
        assert!(starts_with_continuation_punctuation(", and then"));
    }

    #[test]
    fn test_is_mid_sentence_continuation_hyphen() {
        assert!(is_mid_sentence_continuation(
            "this is a bro-",
            "ken word",
            false
        ));
    }

    #[test]
    fn test_is_mid_sentence_continuation_lower() {
        assert!(is_mid_sentence_continuation(
            "this is not complete but long enough to be mid",
            "and continues here",
            false
        ));
    }

    #[test]
    fn test_is_mid_sentence_continuation_ended() {
        assert!(!is_mid_sentence_continuation(
            "This is a complete sentence.",
            "And a new one starts.",
            false
        ));
    }
}

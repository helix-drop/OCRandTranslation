//! ←→ FNM_RE/shared/notes.py 纯函数子集
//!
//! Port 的函数：
//! - `normalize_note_marker` (Python line 187)
//! - `strip_markdown_heading` (Python line 206)
//! - `is_notes_heading_line` (Python line 214)
//! - `first_notes_heading` (Python line 219)
//!
//! 不 port：`parse_note_items_from_text` 等复杂业务（留给 fnm-phase2）。

use once_cell::sync::Lazy;
use regex::Regex;

// ── Regex 常量 ──────────────────────────────────────────────────

static MARKDOWN_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s{0,3}#{1,6}\s*(.+?)\s*$").unwrap());

static NOTES_HEADING_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*|注释|脚注|尾注)\s*$")
        .unwrap()
});

static SYMBOLIC_MARKER_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^[\*†‡§¶]{1,4}$").unwrap());

static LETTER_MARKER_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^[a-zA-Z]$").unwrap());

// ── Unicode 上标 → ASCII 数字映射 ────────────────────────────────

fn unicode_superscript_to_digits(c: char) -> char {
    match c {
        '\u{2070}' => '0', // ⁰
        '\u{00B9}' => '1', // ¹
        '\u{00B2}' => '2', // ²
        '\u{00B3}' => '3', // ³
        '\u{2074}' => '4', // ⁴
        '\u{2075}' => '5', // ⁵
        '\u{2076}' => '6', // ⁶
        '\u{2077}' => '7', // ⁷
        '\u{2078}' => '8', // ⁸
        '\u{2079}' => '9', // ⁹
        other => other,
    }
}

fn ocr_digit_recovery(c: char) -> char {
    match c {
        'l' => '1',
        'I' => '1',
        'O' => '0',
        other => other,
    }
}

// ── 公开 API ────────────────────────────────────────────────────

/// 规范化注释 marker。与 Python `normalize_note_marker` 行为一致。
///
/// - 空白去除
/// - Unicode 上标数字 (¹²³...) → ASCII 数字
/// - OCR 误读恢复 (l→1, I→1, O→0)
/// - 符号型 marker (*, **, † 等) 原样保留
/// - 字母型 marker (a-z, A-Z) 保留
/// - 去除前导零
/// - 空结果 → ""
pub fn normalize_note_marker(raw: &str) -> String {
    let mut trimmed = raw.trim().to_string();
    if trimmed.is_empty() {
        return String::new();
    }

    // 符号型标记原样保留
    if SYMBOLIC_MARKER_RE.is_match(&trimmed) {
        return trimmed;
    }

    // 字母型标记保留
    if LETTER_MARKER_RE.is_match(&trimmed) {
        return trimmed;
    }

    // Unicode 上标 → ASCII 数字
    trimmed = trimmed.chars().map(unicode_superscript_to_digits).collect();

    // OCR 数字误读恢复
    trimmed = trimmed.chars().map(ocr_digit_recovery).collect();

    // 只保留数字
    let digits: String = trimmed.chars().filter(|c| c.is_ascii_digit()).collect();

    if digits.is_empty() {
        return String::new();
    }

    // 去除前导零
    let stripped = digits.trim_start_matches('0').to_string();
    if stripped.is_empty() {
        "0".to_string()
    } else {
        stripped
    }
}

/// 去除行首的 markdown heading 标记（`#` 开头），返回标题文本。
/// 与 Python `strip_markdown_heading` 一致。
pub fn strip_markdown_heading(line: &str) -> String {
    let text = line.trim();
    match MARKDOWN_HEADING_RE.captures(text) {
        Some(caps) => caps
            .get(1)
            .map(|m| m.as_str().trim().to_string())
            .unwrap_or_default(),
        None => text.to_string(),
    }
}

/// 判断一行是否是 notes heading（NOTES / ENDNOTES / 注释 等）。
/// 与 Python `is_notes_heading_line` 一致。
pub fn is_notes_heading_line(line: &str) -> bool {
    let text = strip_markdown_heading(line);
    !text.is_empty() && NOTES_HEADING_RE.is_match(&text)
}

/// 从 page markdown 文本中提取第一个 notes heading。
/// 只检查前 12 行。与 Python `first_notes_heading` 一致。
pub fn first_notes_heading(markdown: &str) -> String {
    for line in markdown.lines().take(12) {
        if is_notes_heading_line(line) {
            return strip_markdown_heading(line);
        }
    }
    String::new()
}

/// 判断 short_marker 的数字是否是 long_marker 数字的有序子序列。
///
/// ←→ Python `FNM_RE/shared/notes.py:marker_digits_are_ordered_subsequence`
///
/// 例：`marker_digits_are_ordered_subsequence("12", "123")` → true
///     `marker_digits_are_ordered_subsequence("13", "123")` → true
///     `marker_digits_are_ordered_subsequence("21", "123")` → false
pub fn marker_digits_are_ordered_subsequence(short_marker: &str, long_marker: &str) -> bool {
    let short_digits = normalize_note_marker(short_marker);
    let long_digits = normalize_note_marker(long_marker);
    if short_digits.is_empty() || long_digits.is_empty() || short_digits == long_digits {
        return false;
    }
    // 预收集 short 的字符，循环内 O(1) 索引（替代每次 `chars().nth(cursor)` 的 O(cursor) 重走）。
    // 整体从 O(n·m) 降到 O(n+m)；同时用字符数（而非字节 len）作边界，避免多字节潜在偏差。
    let short_chars: Vec<char> = short_digits.chars().collect();
    let mut cursor = 0;
    for ch in long_digits.chars() {
        if cursor < short_chars.len() && short_chars[cursor] == ch {
            cursor += 1;
            if cursor == short_chars.len() {
                return true;
            }
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_empty() {
        assert_eq!(normalize_note_marker(""), "");
        assert_eq!(normalize_note_marker("  "), "");
    }

    #[test]
    fn normalize_plain_digits() {
        assert_eq!(normalize_note_marker("12"), "12");
        assert_eq!(normalize_note_marker(" 1 2 "), "12");
        assert_eq!(normalize_note_marker("100"), "100");
        assert_eq!(normalize_note_marker("01"), "1");
        assert_eq!(normalize_note_marker("0"), "0");
    }

    #[test]
    fn normalize_unicode_superscript() {
        assert_eq!(normalize_note_marker("¹"), "1");
        assert_eq!(normalize_note_marker("²³"), "23");
        assert_eq!(normalize_note_marker(" ⁵ "), "5");
    }

    #[test]
    fn normalize_symbolic() {
        assert_eq!(normalize_note_marker("*"), "*");
        assert_eq!(normalize_note_marker("**"), "**");
        assert_eq!(normalize_note_marker("†"), "†");
        assert_eq!(normalize_note_marker("‡‡"), "‡‡");
        assert_eq!(normalize_note_marker("§"), "§");
        assert_eq!(normalize_note_marker("¶"), "¶");
    }

    #[test]
    fn normalize_letter() {
        assert_eq!(normalize_note_marker("a"), "a");
        assert_eq!(normalize_note_marker("Z"), "Z");
    }

    #[test]
    fn normalize_many_digits() {
        assert_eq!(normalize_note_marker("12345"), "12345");
        assert_eq!(normalize_note_marker("123456"), "123456");
    }

    #[test]
    fn normalize_junk() {
        assert_eq!(normalize_note_marker("abc"), "");
        assert_eq!(normalize_note_marker("1.2"), "12");
    }

    #[test]
    fn normalize_html_sup() {
        // <sup>5</sup> → digits only → "5"
        assert_eq!(normalize_note_marker("<sup>5</sup>"), "5");
    }

    #[test]
    fn strip_heading_basic() {
        assert_eq!(strip_markdown_heading("# Title"), "Title");
        assert_eq!(strip_markdown_heading("##  Subtitle "), "Subtitle");
        assert_eq!(strip_markdown_heading("   ### Deep"), "Deep");
    }

    #[test]
    fn strip_heading_not_heading() {
        assert_eq!(strip_markdown_heading("plain text"), "plain text");
        assert_eq!(strip_markdown_heading(""), "");
    }

    #[test]
    fn is_notes_heading() {
        assert!(is_notes_heading_line("NOTES"));
        assert!(is_notes_heading_line("## Notes"));
        assert!(is_notes_heading_line("ENDNOTES"));
        assert!(is_notes_heading_line("## Endnotes"));
        assert!(is_notes_heading_line("注释"));
        assert!(is_notes_heading_line("脚注"));
        assert!(is_notes_heading_line("尾注"));
    }

    #[test]
    fn is_not_notes_heading() {
        assert!(!is_notes_heading_line("Introduction"));
        assert!(!is_notes_heading_line("Chapter 1"));
        assert!(!is_notes_heading_line(""));
    }

    #[test]
    fn first_heading_found() {
        let md = "# Title\nSome text\n## Notes\nnote content";
        assert_eq!(first_notes_heading(md), "Notes");
    }

    #[test]
    fn first_heading_not_found() {
        let md = "# Title\n## Chapter 1\nSome text";
        assert_eq!(first_notes_heading(md), "");
    }

    #[test]
    fn ordered_subsequence_basic() {
        assert!(marker_digits_are_ordered_subsequence("12", "123"));
        assert!(marker_digits_are_ordered_subsequence("13", "123"));
        assert!(!marker_digits_are_ordered_subsequence("21", "123"));
        assert!(!marker_digits_are_ordered_subsequence("", "123"));
        assert!(!marker_digits_are_ordered_subsequence("123", "123"));
        assert!(!marker_digits_are_ordered_subsequence("4", "123"));
    }
}

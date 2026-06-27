//! ←→ Python `FNM_RE/stages/units.py`（L55-157，7 个文本切分 helper）
//!
//! 纯函数：页面文本切分与清理。

use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashMap;

use crate::text::markdown_parse::SyntheticMarkdownPage;

// ── 正则常量 ──────────────────────────────────────────────────────

/// ←→ Python `_NOTE_HEADING_RE` (units.py:34)
static NOTE_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?im)^\s{0,3}(?:##\s*)?(NOTES|ENDNOTES)\s*$").unwrap());

/// ←→ Python `_MARKDOWN_HEADING_LINE_RE` (units.py:35)
static MARKDOWN_HEADING_LINE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s{0,3}#{1,6}\s*(.+?)\s*$").unwrap());

/// ←→ Python `_MARKDOWN_NOTE_DEF_START_RE` (units.py:39-47)
static MARKDOWN_NOTE_DEF_START_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:\$\s*\^\{\s*\d{1,4}[A-Za-z]?\s*\}\s*\$|<sup>\s*\d{1,4}[A-Za-z]?\s*</sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹]+|\d{1,4}[A-Za-z]?\s*[\.\)\]])\s+",
    )
    .unwrap()
});

/// ←→ Python `_GAP_PAGE_NOISE_LINE_RE` (units.py:48-51)
static GAP_PAGE_NOISE_LINE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:<div\b.*|</div>\s*|<img\b.*|!\[.*\]\(.*\)\s*|fig\.\s*\d+.*)$").unwrap()
});

/// ←→ Python `_MARKDOWN_TAIL_LINE_LIMIT` (units.py:52)
const MARKDOWN_TAIL_LINE_LIMIT: usize = 40;

// ── 公开函数 ──────────────────────────────────────────────────────

/// ←→ Python `_normalize_title_key` (units.py:55-60)
///
/// 标题归一化：lowercase → 去 heading 前缀 → 去编号 → 去非字母数字。
pub fn normalize_title_key(text: &str) -> String {
    // Python: r"^\s{0,3}#{1,6}\s*" 只去掉 # 前缀，不捕获标题内容
    static HEADING_PREFIX_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\s{0,3}#{1,6}\s*").unwrap());
    static NUMBERING_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"^(?:\d+|[ivxlcm]+)[\.\)]\s*").unwrap());
    static NON_ALNUM_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^0-9a-zà-ÿ]+").unwrap());

    let lowered = text.trim().to_lowercase();
    let no_heading = HEADING_PREFIX_RE.replace(&lowered, "").trim().to_string();
    let no_numbering = NUMBERING_RE.replace(&no_heading, "").trim().to_string();
    let normalized = NON_ALNUM_RE.replace_all(&no_numbering, "").to_string();
    normalized
}

/// ←→ Python `_extract_note_heading_split` (units.py:63-72)
///
/// 检测 `## NOTES` / `## Endnotes` 等标题，返回 (body_text, note_text)。
pub fn extract_note_heading_split(text: &str) -> Option<(String, String)> {
    let raw = text;
    if raw.is_empty() {
        return None;
    }
    let matched = NOTE_HEADING_RE.find(raw)?;
    let body_text = raw[..matched.start()].trim().to_string();
    let note_text = raw[matched.end()..].trim().to_string();
    Some((body_text, note_text))
}

/// ←→ Python `_split_page_text_by_chapter_heading` (units.py:75-96)
///
/// 按章标题切分页面文本，返回 (before, after)。
pub fn split_page_text_by_chapter_heading(text: &str, title: &str) -> (String, String) {
    let raw = text;
    if raw.trim().is_empty() {
        return (String::new(), String::new());
    }
    let title_key = normalize_title_key(title);
    if title_key.is_empty() {
        return (String::new(), raw.trim().to_string());
    }
    for (index, raw_line) in raw.lines().enumerate() {
        let stripped = raw_line.trim();
        if stripped.is_empty() {
            continue;
        }
        let heading_text = if let Some(caps) = MARKDOWN_HEADING_LINE_RE.captures(stripped) {
            caps.get(1)
                .map(|m| m.as_str().trim())
                .unwrap_or("")
                .to_string()
        } else {
            stripped.to_string()
        };
        if normalize_title_key(&heading_text) != title_key {
            continue;
        }
        let before = raw
            .lines()
            .take(index)
            .collect::<Vec<_>>()
            .join("\n")
            .trim()
            .to_string();
        let after = raw
            .lines()
            .skip(index)
            .collect::<Vec<_>>()
            .join("\n")
            .trim()
            .to_string();
        return (before, after);
    }
    (String::new(), raw.trim().to_string())
}

/// ←→ Python `_split_page_text_at_first_heading` (units.py:99-110)
///
/// 找第一个 heading 行切分，返回 (before, after)。
pub fn split_page_text_at_first_heading(text: &str) -> (String, String) {
    let raw = text;
    if raw.trim().is_empty() {
        return (String::new(), String::new());
    }
    for (index, raw_line) in raw.lines().enumerate() {
        let stripped = raw_line.trim();
        if MARKDOWN_HEADING_LINE_RE.is_match(stripped) {
            let before = raw
                .lines()
                .take(index)
                .collect::<Vec<_>>()
                .join("\n")
                .trim()
                .to_string();
            let after = raw
                .lines()
                .skip(index)
                .collect::<Vec<_>>()
                .join("\n")
                .trim()
                .to_string();
            return (before, after);
        }
    }
    (raw.trim().to_string(), String::new())
}

/// ←→ Python `_trim_trailing_markdown_note_block` (units.py:113-130)
///
/// 删除尾部 note 定义块（如 `1. Note text...`）。
pub fn trim_trailing_markdown_note_block(text: &str) -> String {
    let raw = text.trim();
    if raw.is_empty() {
        return String::new();
    }
    let lines: Vec<&str> = raw.lines().collect();
    let tail_start = lines.len().saturating_sub(MARKDOWN_TAIL_LINE_LIMIT);
    let tail_lines = &lines[tail_start..];
    let mut first_note_idx: Option<usize> = None;
    for (idx, raw_line) in tail_lines.iter().enumerate() {
        let stripped = raw_line.trim();
        if stripped.is_empty() {
            continue;
        }
        if MARKDOWN_NOTE_DEF_START_RE.is_match(stripped) {
            first_note_idx = Some(idx);
            break;
        }
    }
    match first_note_idx {
        Some(idx) => {
            let keep_count = tail_start + idx;
            lines[..keep_count].join("\n").trim().to_string()
        }
        None => raw.to_string(),
    }
}

/// ←→ Python `_sanitize_gap_page_prefix` (units.py:133-140)
///
/// 清理 gap page 噪声行（fig、div、img 等）。
pub fn sanitize_gap_page_prefix(text: &str) -> String {
    let kept: Vec<&str> = text
        .lines()
        .filter(|line| {
            let stripped = line.trim();
            !GAP_PAGE_NOISE_LINE_RE.is_match(stripped)
        })
        .collect();
    kept.join("\n").trim().to_string()
}

/// ←→ Python `_synthetic_markdown_pages` (units.py:143-156)
///
/// 将 page_no → text map 转为 SyntheticMarkdownPage 列表。
pub fn synthetic_markdown_pages(pages_by_no: &HashMap<i64, String>) -> Vec<SyntheticMarkdownPage> {
    let mut page_nos: Vec<i64> = pages_by_no.keys().copied().collect();
    page_nos.sort();
    page_nos
        .into_iter()
        .map(|page_no| SyntheticMarkdownPage {
            book_page: page_no,
            file_idx: (page_no - 1).max(0),
            markdown: pages_by_no.get(&page_no).cloned().unwrap_or_default(),
            footnotes: String::new(),
            text_source: "fnm_re".to_string(),
            print_page_label: page_no.to_string(),
            ..Default::default()
        })
        .collect()
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_title_key_basic() {
        assert_eq!(
            normalize_title_key("## Chapter 1: Introduction"),
            "chapter1introduction"
        );
        assert_eq!(normalize_title_key("IV. The End"), "theend");
        assert_eq!(normalize_title_key(""), "");
    }

    #[test]
    fn test_extract_note_heading_split_found() {
        let text = "Body text here.\n\n## NOTES\n\n1. First note.";
        let result = extract_note_heading_split(text);
        assert!(result.is_some());
        let (body, notes) = result.unwrap();
        assert_eq!(body, "Body text here.");
        assert!(notes.contains("First note"));
    }

    #[test]
    fn test_extract_note_heading_split_not_found() {
        let text = "Just body text, no notes heading.";
        assert!(extract_note_heading_split(text).is_none());
    }

    #[test]
    fn test_split_page_text_by_chapter_heading_found() {
        let text = "Some prefix.\n\n# Chapter 1\n\nBody content.";
        let (before, after) = split_page_text_by_chapter_heading(text, "Chapter 1");
        assert_eq!(before, "Some prefix.");
        assert!(after.contains("# Chapter 1"));
        assert!(after.contains("Body content."));
    }

    #[test]
    fn test_split_page_text_by_chapter_heading_not_found() {
        let text = "No matching heading here.";
        let (before, after) = split_page_text_by_chapter_heading(text, "Chapter 99");
        assert!(before.is_empty());
        assert_eq!(after, "No matching heading here.");
    }

    #[test]
    fn test_split_page_text_at_first_heading() {
        let text = "Prefix line.\n\n# Heading\n\nBody.";
        let (before, after) = split_page_text_at_first_heading(text);
        assert_eq!(before, "Prefix line.");
        assert!(after.contains("# Heading"));
    }

    #[test]
    fn test_split_page_text_at_first_heading_no_heading() {
        let text = "No heading at all.";
        let (before, after) = split_page_text_at_first_heading(text);
        assert_eq!(before, "No heading at all.");
        assert!(after.is_empty());
    }

    #[test]
    fn test_trim_trailing_markdown_note_block() {
        let text = "Body paragraph.\n\n1. First note.\n2. Second note.";
        let result = trim_trailing_markdown_note_block(text);
        assert_eq!(result, "Body paragraph.");
    }

    #[test]
    fn test_trim_trailing_markdown_note_block_no_notes() {
        let text = "Just body text, no notes.";
        let result = trim_trailing_markdown_note_block(text);
        assert_eq!(result, "Just body text, no notes.");
    }

    #[test]
    fn test_sanitize_gap_page_prefix() {
        let text = "Real text.\n<img src=\"x\">\n<div>block</div>\nMore text.";
        let result = sanitize_gap_page_prefix(text);
        assert!(result.contains("Real text."));
        assert!(result.contains("More text."));
        assert!(!result.contains("<img"));
        assert!(!result.contains("<div"));
    }

    #[test]
    fn test_synthetic_markdown_pages_basic() {
        let mut map = HashMap::new();
        map.insert(1, "page 1 text".to_string());
        map.insert(3, "page 3 text".to_string());
        let result = synthetic_markdown_pages(&map);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].book_page, 1);
        assert_eq!(result[1].book_page, 3);
        assert_eq!(result[0].markdown, "page 1 text");
    }
}

//! ←→ FNM_RE/modules/book_assemble.py
//! 翻译的函数：
//!   split_markdown_prefix            ←→ _split_markdown_prefix (book_assemble.py:250)
//!   looks_like_garbled_export_block  ←→ _looks_like_garbled_export_block (book_assemble.py:262)
//!   repair_garbled_markdown_blocks   ←→ _repair_garbled_markdown_blocks (book_assemble.py:284)

use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::Value;

// ── 正则常量 ──────────────────────────────────────────────────

static CONTROL_CHAR_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]").unwrap());

static CJK_CHAR_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"[\u{3400}-\u{4dbf}\u{4e00}-\u{9fff}\u{f900}-\u{faff}]").unwrap());

static SUSPECT_ASCII_GARBLED_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"[A-Z0-9@;:<>=?]{12,}").unwrap());

static MULTI_SPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[ \t]{2,}").unwrap());

/// Markdown 行前缀模式：[^N]: / ### / - / 1. / >
static MARKDOWN_PREFIX_PATTERNS: [Lazy<Regex>; 5] = [
    Lazy::new(|| Regex::new(r"^(\s*\[\^[^\]]+\]:\s+)(.*)$").unwrap()),
    Lazy::new(|| Regex::new(r"^(\s*#{1,6}\s+)(.*)$").unwrap()),
    Lazy::new(|| Regex::new(r"^(\s*[-*+]\s+)(.*)$").unwrap()),
    Lazy::new(|| Regex::new(r"^(\s*\d+\.\s+)(.*)$").unwrap()),
    Lazy::new(|| Regex::new(r"^(\s*>\s+)(.*)$").unwrap()),
];

// ── 公开函数 ──────────────────────────────────────────────────

/// 分离行前缀与内容。
///
/// ←→ Python `_split_markdown_prefix()` (book_assemble.py:250)
pub fn split_markdown_prefix(line: &str) -> (String, String) {
    for pattern in &MARKDOWN_PREFIX_PATTERNS {
        if let Some(caps) = pattern.captures(line) {
            let prefix = caps
                .get(1)
                .map(|m| m.as_str().to_string())
                .unwrap_or_default();
            let content = caps
                .get(2)
                .map(|m| m.as_str().to_string())
                .unwrap_or_default();
            return (prefix, content);
        }
    }
    // 无匹配前缀，用空白前缀兜底
    let trimmed_start = line.len() - line.trim_start().len();
    let prefix: String = line.chars().take(trimmed_start).collect();
    let content = line[trimmed_start..].to_string();
    (prefix, content)
}

/// 判断文本是否看起来像乱码输出块。
///
/// ←→ Python `_looks_like_garbled_export_block()` (book_assemble.py:262)
pub fn looks_like_garbled_export_block(text: &str) -> bool {
    let sample = text.trim();
    if sample.is_empty() {
        return false;
    }
    let visible_chars: Vec<char> = sample.chars().filter(|c| !c.is_whitespace()).collect();
    if visible_chars.len() < 12 {
        return false;
    }
    let control_hit = CONTROL_CHAR_RE.is_match(sample);
    let ascii_run_hit = SUSPECT_ASCII_GARBLED_RE.is_match(sample);

    let suspect_ascii_count = visible_chars
        .iter()
        .filter(|&&c| {
            c.is_uppercase()
                || c.is_ascii_digit()
                || matches!(c, '@' | ';' | ':' | '<' | '=' | '>' | '?')
        })
        .count();

    let cjk_count = CJK_CHAR_RE.find_iter(sample).count();
    let total = visible_chars.len().max(1);
    let cjk_ratio = cjk_count as f64 / total as f64;
    let suspect_ascii_ratio = suspect_ascii_count as f64 / total as f64;

    if cjk_ratio >= 0.3 && !control_hit && !ascii_run_hit {
        return false;
    }
    control_hit || ascii_run_hit || suspect_ascii_ratio >= 0.55
}

/// 修复乱码 Markdown 块。
///
/// ←→ Python `_repair_garbled_markdown_blocks()` (book_assemble.py:284)
///
/// 注：detect_and_fix_text（Caesar cipher 修复）尚未移植到 Rust，
/// 仅执行控制字符清理。修复统计始终为 0。
pub fn repair_garbled_markdown_blocks(markdown_text: &str) -> (String, Value) {
    let mut repaired_lines: Vec<String> = Vec::new();
    let mut repaired_count: i64 = 0;
    let mut method_counts: std::collections::HashMap<String, i64> =
        std::collections::HashMap::new();

    // 按 \n 切分保留结尾，.lines() 会去掉换行符
    let lines_with_endings: Vec<&str> = if markdown_text.contains("\r\n") {
        markdown_text.split("\r\n").collect()
    } else {
        markdown_text.split('\n').collect()
    };
    let line_count = lines_with_endings.len();
    let has_trailing_newline = markdown_text.ends_with('\n');

    for (idx, line) in lines_with_endings.iter().enumerate() {
        let is_last = idx == line_count - 1;
        let line_ending = if is_last && !has_trailing_newline {
            ""
        } else {
            "\n"
        };
        let base_line = line;

        let (prefix, content) = split_markdown_prefix(base_line);

        if !looks_like_garbled_export_block(&content) {
            repaired_lines.push(format!("{}{}", base_line, line_ending));
            continue;
        }

        let sanitized_content = CONTROL_CHAR_RE.replace_all(&content, " ").to_string();
        let sanitized_content = MULTI_SPACE_RE
            .replace_all(&sanitized_content, " ")
            .trim()
            .to_string();
        if sanitized_content.is_empty() {
            repaired_lines.push(format!("{}{}", base_line, line_ending));
            continue;
        }

        // detect_and_fix_text（Caesar cipher 修复）未移植 ——
        // sanitized_content 不同于 content 认为是 control_char_cleanup
        if sanitized_content != content {
            repaired_count += 1;
            *method_counts
                .entry("control_char_cleanup".to_string())
                .or_insert(0) += 1;
            repaired_lines.push(format!("{}{}{}", prefix, sanitized_content, line_ending));
        } else {
            repaired_lines.push(format!("{}{}", base_line, line_ending));
        }
    }

    let mut garbled_methods: Vec<String> = method_counts.keys().cloned().collect();
    garbled_methods.sort();
    let repaired_markdown = repaired_lines.join("");
    let summary = serde_json::json!({
        "garbled_block_repair_applied": repaired_count > 0,
        "repaired_garbled_block_count": repaired_count,
        "garbled_repair_methods": garbled_methods,
        "garbled_repair_method_counts": method_counts,
    });
    (repaired_markdown, summary)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_prefix_def_line() {
        let (pre, content) = split_markdown_prefix("[^1]: This is a note.");
        assert_eq!(pre, "[^1]: ");
        assert_eq!(content, "This is a note.");
    }

    #[test]
    fn split_prefix_heading() {
        let (pre, content) = split_markdown_prefix("### Chapter 1");
        assert_eq!(pre, "### ");
        assert_eq!(content, "Chapter 1");
    }

    #[test]
    fn split_prefix_bullet() {
        let (pre, content) = split_markdown_prefix("- list item");
        assert_eq!(pre, "- ");
        assert_eq!(content, "list item");
    }

    #[test]
    fn split_prefix_numbered() {
        let (pre, content) = split_markdown_prefix("1. numbered item");
        assert_eq!(pre, "1. ");
        assert_eq!(content, "numbered item");
    }

    #[test]
    fn split_prefix_blockquote() {
        let (pre, content) = split_markdown_prefix("> quoted text");
        assert_eq!(pre, "> ");
        assert_eq!(content, "quoted text");
    }

    #[test]
    fn split_prefix_none() {
        let (pre, content) = split_markdown_prefix("Plain text");
        assert_eq!(pre, "");
        assert_eq!(content, "Plain text");
    }

    #[test]
    fn seems_garbled_short() {
        assert!(!looks_like_garbled_export_block("short"));
    }

    #[test]
    fn seems_garbled_cjk() {
        assert!(!looks_like_garbled_export_block(
            "这是一段正常的中文文本，包含足够的字符来触发 CJK 检测逻辑的实际运行。"
        ));
    }

    #[test]
    fn seems_garbled_control_char() {
        assert!(looks_like_garbled_export_block(
            "AAAA\x00BBBB\x01CCCC\x02DDDD\x03EEEE\x04FFFF\x05GGGG"
        ));
    }

    #[test]
    fn seems_garbled_long_ascii() {
        assert!(looks_like_garbled_export_block(
            "ABCDEF1234567890@;:>=?XXXX"
        ));
    }

    #[test]
    fn seems_garbled_high_caps_ratio() {
        assert!(looks_like_garbled_export_block(
            "AAAA BBBB CCCC DDDD EEEE FFFF GGGG HHHH IIII"
        ));
    }

    #[test]
    fn repair_normal_text() {
        let text = "Hello world.\nNormal text here.\n";
        let (repaired, summary) = repair_garbled_markdown_blocks(text);
        // The function adds \n after each line, so trailing \n for each split part
        assert!(repaired.contains("Hello world."));
        assert!(repaired.contains("Normal text here."));
        assert!(!summary["garbled_block_repair_applied"].as_bool().unwrap());
    }

    #[test]
    fn repair_control_chars() {
        let text = "Normal line\n\x00\x01CONTROL\x02\x03CHARS\x04\nLast line\n";
        let (repaired, summary) = repair_garbled_markdown_blocks(text);
        assert!(summary["garbled_block_repair_applied"].as_bool().unwrap());
        assert!(summary["repaired_garbled_block_count"].as_i64().unwrap() > 0);
        assert!(!repaired.contains('\x00'));
        assert!(!repaired.contains('\x01'));
    }
}

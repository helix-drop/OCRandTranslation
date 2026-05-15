//! ←→ FNM_RE/shared/segments.py
//! 段落与分页分段工具。

use regex::Regex;
use std::cmp;

/// 按连续空行拆分文本为段落。与 Python `split_fnm_paragraphs` 一致。
pub fn split_fnm_paragraphs(text: &str) -> Vec<String> {
    Regex::new(r"\n\s*\n")
        .unwrap()
        .split(text.trim())
        .map(|p| p.trim().to_string())
        .filter(|p| !p.is_empty())
        .collect()
}

/// 从 markdown 行提取 heading level 和清理后的文本。
/// 返回 (heading_level, clean_text)。与 Python `normalize_heading_text` 一致。
pub fn normalize_heading_text(text: &str) -> (i64, String) {
    let re = Regex::new(r"^\s{0,3}#{1,6}\s*(.+?)\s*$").unwrap();
    if let Some(caps) = re.captures(text.trim()) {
        let raw = text.trim();
        let hash_count = raw.chars().take_while(|c| *c == '#').count();
        let level = cmp::min(hash_count, 6) as i64;
        let clean = caps
            .get(1)
            .map(|m| m.as_str().trim().to_string())
            .unwrap_or_default();
        (level, clean)
    } else {
        (0, text.trim().to_string())
    }
}

/// 将段落列表合并回文本（用 \\n\\n 连接）。与 Python segment 的 source_text/display_text 构造一致。
pub fn join_paragraphs(paragraphs: &[String]) -> String {
    paragraphs
        .iter()
        .map(|p| p.trim())
        .filter(|p| !p.is_empty())
        .collect::<Vec<_>>()
        .join("\n\n")
        .trim()
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_basic() {
        let parts = split_fnm_paragraphs("a\n\nb\n\nc");
        assert_eq!(parts, vec!["a", "b", "c"]);
    }

    #[test]
    fn split_single() {
        let parts = split_fnm_paragraphs("single paragraph");
        assert_eq!(parts, vec!["single paragraph"]);
    }

    #[test]
    fn split_empty() {
        let parts = split_fnm_paragraphs("");
        assert!(parts.is_empty());
    }

    #[test]
    fn heading_level_1() {
        let (level, clean) = normalize_heading_text("# Title");
        assert_eq!(level, 1);
        assert_eq!(clean, "Title");
    }

    #[test]
    fn heading_level_3() {
        let (level, clean) = normalize_heading_text("### Deep");
        assert_eq!(level, 3);
        assert_eq!(clean, "Deep");
    }

    #[test]
    fn heading_plain_text() {
        let (level, clean) = normalize_heading_text("plain text");
        assert_eq!(level, 0);
        assert_eq!(clean, "plain text");
    }
}

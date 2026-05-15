//! ←→ FNM_RE/shared/text.py
//! 页面文本提取与 heading 检测工具。
//!
//! 输入 page 使用 `&serde_json::Value` 保持 Python dict 兼容。

use crate::title::{normalize_title, normalized_title_key};
use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::Value;

static MARKDOWN_HEADING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s{0,3}#{1,6}\s*(.+?)\s*$").unwrap());

static NOTES_HEADER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?im)^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*|注释|脚注|尾注)\s*$")
        .unwrap()
});

/// 从 page 对象提取 markdown 文本。与 Python `page_markdown_text` 一致。
pub fn page_markdown_text(page: &Value) -> String {
    if !page.is_object() {
        return String::new();
    }
    if let Some(md) = page
        .get("enriched_markdown")
        .or_else(|| page.get("markdown"))
    {
        if md.is_object() {
            return md
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string();
        }
        if let Some(s) = md.as_str() {
            return s.trim().to_string();
        }
    }
    if let Some(nested) = page.get("_page") {
        if nested.is_object() && nested.as_object() != page.as_object() {
            return page_markdown_text(nested);
        }
    }
    String::new()
}

/// 从 page 的 prunedResult 提取排序后的 block 列表。
/// 与 Python `page_blocks` 一致。
pub fn page_blocks(page: &Value) -> Vec<Value> {
    let blocks = page
        .get("prunedResult")
        .and_then(|p| p.get("parsing_res_list"))
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    if blocks.is_empty() {
        return vec![];
    }

    let mut blocks: Vec<Value> = blocks.into_iter().filter(|b| b.is_object()).collect();

    blocks.sort_by(|a, b| {
        let order_a = a
            .get("block_order")
            .and_then(|v| v.as_i64())
            .unwrap_or(i64::MAX);
        let order_b = b
            .get("block_order")
            .and_then(|v| v.as_i64())
            .unwrap_or(i64::MAX);
        if order_a != order_b {
            return order_a.cmp(&order_b);
        }
        let get_bbox_1 = |v: &Value| -> f64 {
            v.get("block_bbox")
                .and_then(|b| b.as_array())
                .and_then(|arr| arr.get(1))
                .and_then(|v| v.as_f64())
                .unwrap_or(0.0)
        };
        let y_a = get_bbox_1(a);
        let y_b = get_bbox_1(b);
        if y_a != y_b {
            return y_a.partial_cmp(&y_b).unwrap_or(std::cmp::Ordering::Equal);
        }
        let get_bbox_0 = |v: &Value| -> f64 {
            v.get("block_bbox")
                .and_then(|b| b.as_array())
                .and_then(|arr| arr.first())
                .and_then(|v| v.as_f64())
                .unwrap_or(0.0)
        };
        let x_a = get_bbox_0(a);
        let x_b = get_bbox_0(b);
        x_a.partial_cmp(&x_b).unwrap_or(std::cmp::Ordering::Equal)
    });

    blocks
}

/// 从 page 提取标题行（去重）。与 Python `extract_page_headings` 一致。
pub fn extract_page_headings(page: &Value) -> Vec<String> {
    let mut headings: Vec<String> = Vec::new();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();

    for block in page_blocks(page) {
        let label = block
            .get("block_label")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_lowercase();
        if label != "doc_title" && label != "paragraph_title" {
            continue;
        }
        let text = normalize_title(
            block
                .get("block_content")
                .and_then(|v| v.as_str())
                .unwrap_or(""),
        );
        let key = normalized_title_key(&text);
        if !text.is_empty() && !key.is_empty() && !seen.contains(&key) {
            seen.insert(key);
            headings.push(text);
        }
    }
    if !headings.is_empty() {
        return headings;
    }
    let md = page_markdown_text(page);
    for line in md.lines().take(8) {
        if let Some(caps) = MARKDOWN_HEADING_RE.captures(line) {
            let text = normalize_title(caps.get(1).map(|m| m.as_str()).unwrap_or(""));
            let key = normalized_title_key(&text);
            if !text.is_empty() && !key.is_empty() && !seen.contains(&key) {
                seen.insert(key);
                headings.push(text);
            }
        }
    }
    headings
}

/// 判断 page 是否包含 note heading。与 Python `has_note_heading` 一致。
pub fn has_note_heading(page: &Value) -> bool {
    NOTES_HEADER_RE.is_match(&page_markdown_text(page))
}

/// 返回 page 的第一个 section hint（标题或 note_scan section_hints）。
/// 与 Python `first_section_hint` 一致。
pub fn first_section_hint(page: &Value, note_scan: Option<&Value>) -> String {
    let headings = extract_page_headings(page);
    if let Some(h) = headings.first() {
        return h.clone();
    }
    if let Some(scan) = note_scan {
        if let Some(hints) = scan.get("section_hints").and_then(|v| v.as_array()) {
            if let Some(hint) = hints.first().and_then(|v| v.as_str()) {
                return hint.to_string();
            }
        }
    }
    String::new()
}

/// 生成 note_scan 的简短摘要。与 Python `note_scan_summary` 一致。
pub fn note_scan_summary(note_scan: &Value) -> Value {
    let mut summary = serde_json::Map::new();
    if let Some(kind) = note_scan.get("page_kind") {
        summary.insert("page_kind".into(), kind.clone());
    }
    let item_count = note_scan
        .get("items")
        .and_then(|v| v.as_array())
        .map(|a| a.len())
        .unwrap_or(0);
    summary.insert("item_count".into(), Value::Number(item_count.into()));
    summary.insert(
        "ambiguity_flags".into(),
        note_scan
            .get("ambiguity_flags")
            .cloned()
            .unwrap_or(Value::Array(vec![])),
    );
    if let Some(idx) = note_scan.get("note_start_line_index") {
        summary.insert("note_start_line_index".into(), idx.clone());
    }
    Value::Object(summary)
}

/// 按行拆分并去除空行/空白行。与 Python `plain_text_lines` 一致。
pub fn plain_text_lines(text: &str) -> Vec<String> {
    text.lines()
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn markdown_text_from_enriched() {
        let page = json!({"enriched_markdown": {"text": "## Notes\ncontent"}});
        assert_eq!(page_markdown_text(&page), "## Notes\ncontent");
    }

    #[test]
    fn markdown_text_from_raw() {
        let page = json!({"markdown": "plain text"});
        assert_eq!(page_markdown_text(&page), "plain text");
    }

    #[test]
    fn markdown_text_nested() {
        let page = json!({"_page": {"markdown": "nested text"}});
        assert_eq!(page_markdown_text(&page), "nested text");
    }

    #[test]
    fn markdown_text_empty() {
        assert_eq!(page_markdown_text(&json!(null)), "");
        assert_eq!(page_markdown_text(&json!({})), "");
    }

    #[test]
    fn has_note_heading_detect() {
        let page = json!({"markdown": "## Notes\ncontent"});
        assert!(has_note_heading(&page));
    }

    #[test]
    fn has_note_heading_false() {
        let page = json!({"markdown": "## Chapter 1"});
        assert!(!has_note_heading(&page));
    }

    #[test]
    fn plain_lines_basic() {
        let lines = plain_text_lines("  a  \n\n  b  \n  ");
        assert_eq!(lines, vec!["a", "b"]);
    }
}

//! ←→ FNM_RE/modules/chapter_merge.py
//! 保留函数：
//!   has_raw_marker_in_body           ←→ _has_raw_marker_in_body (chapter_merge.py:321)
//!   apply_notes_block_format         ←→ _apply_notes_block_format (chapter_merge.py:487)
//!   chapter_contract_items_by_section ←→ _chapter_contract_items_by_section (chapter_merge.py:572)
//!   has_legacy_note_token             ←→ _has_legacy_note_token (chapter_merge.py:581)
//!
//! 已移除（替代为 diagnostics + merge_reviews blocker）：
//!   rewrite_residual_raw_markers_for_chapter — 不再猜测替换正文 raw marker
//!   rewrite_chapters_for_merge               — 调用上述函数，已删除
//!   book_note_text_by_id / chapter_note_text_by_id / chapter_marker_sequences

use std::collections::HashMap;

use once_cell::sync::Lazy;
use regex::Regex;

use crate::diagnostic_helpers;

/// 定义行印刷编号前缀正则（用于幂等前缀检查）。
static DEF_LINE_PRINTED_PREFIX_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\[\^(\d+)\]:\s*(.*)$").unwrap());

/// 判断正文中是否残留原始标记（带数字边界检查）。
///
/// ←→ Python `_has_raw_marker_in_body()` (chapter_merge.py:321)
pub fn has_raw_marker_in_body(markdown_text: &str) -> bool {
    let body_text = diagnostic_helpers::split_body_and_definitions(markdown_text).0;
    fnm_core::ref_rewriter::has_raw_marker_leak(&body_text, markdown_text)
}

/// 统一章节 NOTES 块格式。
///
/// ←→ Python `_apply_notes_block_format()` (chapter_merge.py:487)
pub fn apply_notes_block_format(markdown_text: &str) -> String {
    let text: &str = markdown_text;
    if text.is_empty() {
        return text.to_string();
    }
    let raw_lines: Vec<&str> = text.lines().collect();
    let mut has_def_lines = false;
    let mut notes_heading_inserted = false;
    let mut saw_notes_heading_already = false;

    for line in &raw_lines {
        let stripped = line.trim();
        if stripped.starts_with("### NOTES") || stripped == "### NOTES" {
            saw_notes_heading_already = true;
            break;
        }
    }

    let mut output_lines: Vec<String> = Vec::new();
    for &line in &raw_lines {
        if let Some(caps) = DEF_LINE_PRINTED_PREFIX_RE.captures(line.trim_end()) {
            let number: i64 = caps[1].parse().unwrap_or(0);
            let mut body = caps[2].trim().to_string();
            if !has_def_lines && !saw_notes_heading_already && !notes_heading_inserted {
                while output_lines
                    .last()
                    .map(|l| l.trim().is_empty())
                    .unwrap_or(false)
                {
                    output_lines.pop();
                }
                if !output_lines.is_empty() {
                    output_lines.push(String::new());
                }
                output_lines.push("### NOTES".to_string());
                output_lines.push(String::new());
                notes_heading_inserted = true;
            }
            has_def_lines = true;
            let prefix = format!("{}. ", number);
            if !body.starts_with(&prefix) {
                body = format!("{}{}", prefix, body);
            }
            output_lines.push(format!("[^{}]: {}", number, body));
        } else {
            output_lines.push(line.to_string());
        }
    }
    let mut result = output_lines.join("\n").trim().to_string();
    if text.ends_with('\n') {
        result.push('\n');
    }
    result
}

/// 按 section 索引 contract 条目。
///
/// ←→ Python `_chapter_contract_items_by_section()` (chapter_merge.py:572)
pub fn chapter_contract_items_by_section(
    chapter_contract_summary: &serde_json::Value,
) -> HashMap<String, serde_json::Value> {
    let mut payload: HashMap<String, serde_json::Value> = HashMap::new();
    if let Some(items) = chapter_contract_summary
        .get("items")
        .and_then(|v| v.as_array())
    {
        for row in items {
            if let Some(item) = row.as_object() {
                let section_id = item
                    .get("section_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim()
                    .to_string();
                if !section_id.is_empty() {
                    payload.insert(section_id, serde_json::Value::Object(item.clone()));
                }
            }
        }
    }
    payload
}

/// 检查正文中是否残留旧版标注令牌。
///
/// ←→ Python `_has_legacy_note_token()` (chapter_merge.py:581)
pub fn has_legacy_note_token(markdown_text: &str) -> bool {
    let text = markdown_text.trim();
    diagnostic_helpers::LEGACY_FOOTNOTE_RE.is_match(text)
        || diagnostic_helpers::LEGACY_ENDNOTE_RE.is_match(text)
        || diagnostic_helpers::LEGACY_EN_BRACKET_RE.is_match(text)
        || diagnostic_helpers::LEGACY_NOTE_TOKEN_RE.is_match(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_has_legacy_note_token_none() {
        assert!(!has_legacy_note_token("Clean markdown text."));
        assert!(!has_legacy_note_token("[^1] Local ref."));
    }

    #[test]
    fn test_has_legacy_note_token_footnote() {
        assert!(has_legacy_note_token("Some [FN-note1] text."));
    }

    #[test]
    fn test_has_legacy_note_token_endnote() {
        assert!(has_legacy_note_token("Some [^en-note1] text."));
    }

    #[test]
    fn test_has_legacy_note_token_en_bracket() {
        assert!(has_legacy_note_token("Some [EN-note1] text."));
    }

    #[test]
    fn test_has_legacy_note_token_note_ref() {
        assert!(has_legacy_note_token("Some {{NOTE_REF:note1}} text."));
        assert!(has_legacy_note_token("Some {{FN_REF:note1}} text."));
        assert!(has_legacy_note_token("Some {{EN_REF:note1}} text."));
    }

    #[test]
    fn test_has_raw_marker_in_body_clean() {
        assert!(!has_raw_marker_in_body("No markers here."));
    }

    #[test]
    fn test_has_raw_marker_in_body_with_local_ref() {
        let md = "Body text [^1] with ref.\n\n[^1]: Definition text.";
        assert!(!has_raw_marker_in_body(md));
    }

    #[test]
    fn test_apply_notes_block_format_no_defs() {
        let input = "### NOTES\nSome text.";
        let result = apply_notes_block_format(input);
        assert_eq!(result, input);
    }

    #[test]
    fn test_apply_notes_block_format_def_without_heading() {
        let input = "Text body.\n\n[^1]: A note.";
        let result = apply_notes_block_format(input);
        assert!(result.contains("### NOTES"));
        assert!(result.contains("[^1]: 1. A note."));
    }

    #[test]
    fn test_apply_notes_block_format_existing_heading() {
        let input = "Text.\n\n### NOTES\n\n[^1]: A note.";
        let result = apply_notes_block_format(input);
        assert!(result.contains("### NOTES"));
        match result.matches("### NOTES").count() {
            1 => {} // ok
            _ => panic!("Expected exactly one ### NOTES heading"),
        }
    }

    /// 合同测试：apply_notes_block_format 在 Obsidian 脚注定义前添加打印编号前缀
    /// (如 [^1]: 1. Note text)。这是有意行为，用于对齐印刷体标记与显示编号。
    /// 调用多次应保持幂等，不重复前缀。
    #[test]
    fn contract_apply_notes_block_format_prefix_behavior() {
        // 无前缀时添加
        let input = "Text.\n\n[^1]: A note.";
        let result = apply_notes_block_format(input);
        assert!(result.contains("[^1]: 1. A note."));

        // 已有前缀时保持幂等（函数还会添加 ### NOTES 标题）
        let input2 = "Text.\n\n[^1]: 1. Already numbered.";
        let result2 = apply_notes_block_format(input2);
        assert!(result2.contains("[^1]: 1. Already numbered."));

        // 多定义行：每个独立编号
        let input3 = "Text.\n\n[^1]: First.\n[^2]: Second.";
        let result3 = apply_notes_block_format(input3);
        assert!(result3.contains("[^1]: 1. First."));
        assert!(result3.contains("[^2]: 2. Second."));
    }

    #[test]
    fn test_apply_notes_block_format_empty() {
        assert_eq!(apply_notes_block_format(""), "");
        assert_eq!(apply_notes_block_format("  "), "");
    }

    #[test]
    fn test_chapter_contract_items_by_section_empty() {
        let value = serde_json::json!({});
        let result = chapter_contract_items_by_section(&value);
        assert!(result.is_empty());
    }

    #[test]
    fn test_chapter_contract_items_by_section_with_items() {
        let value = serde_json::json!({
            "items": [
                {"section_id": "ch1", "missing_definition_count": 0},
                {"section_id": "ch2", "missing_definition_count": 2},
            ]
        });
        let result = chapter_contract_items_by_section(&value);
        assert_eq!(result.len(), 2);
        assert_eq!(result["ch1"]["missing_definition_count"].as_i64(), Some(0));
    }

    #[test]
    fn test_chapter_contract_items_by_section_skips_empty_id() {
        let value = serde_json::json!({
            "items": [
                {"section_id": "", "missing_definition_count": 0},
            ]
        });
        let result = chapter_contract_items_by_section(&value);
        assert!(result.is_empty());
    }

    #[test]
    fn test_has_legacy_note_token_empty() {
        assert!(!has_legacy_note_token(""));
        assert!(!has_legacy_note_token("   "));
    }
}

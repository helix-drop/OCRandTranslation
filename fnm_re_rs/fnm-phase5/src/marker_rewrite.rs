//! ←→ FNM_RE/modules/chapter_merge.py
//! 翻译的函数：
//!   has_raw_marker_in_body           ←→ _has_raw_marker_in_body (chapter_merge.py:321)
//!   chapter_note_text_by_id          ←→ _chapter_note_text_by_id (chapter_merge.py:338)
//!   book_note_text_by_id             ←→ _book_note_text_by_id (chapter_merge.py:355)
//!   chapter_marker_sequences         ←→ _chapter_marker_sequences (chapter_merge.py:366)
//!   rewrite_residual_raw_markers_for_chapter ←→ _rewrite_residual_raw_markers_for_chapter (chapter_merge.py:393)
//!   apply_notes_block_format         ←→ _apply_notes_block_format (chapter_merge.py:487)
//!   rewrite_chapters_for_merge       ←→ _rewrite_chapters_for_merge (chapter_merge.py:535)
//!   chapter_contract_items_by_section ←→ _chapter_contract_items_by_section (chapter_merge.py:572)
//!   has_legacy_note_token             ←→ _has_legacy_note_token (chapter_merge.py:581)

use std::collections::{HashMap, HashSet};

use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::records::{ChapterMarkdownEntry, FrozenUnits};
use fnm_core::ref_rewriter::{
    marker_aliases, replace_note_refs_with_local_labels, resolve_note_id,
};
use fnm_core::{export_constants, note_lookup};
use fnm_phase2::chapter_split::ChapterLayers;
use fnm_phase6::export_audit::helpers;

/// 旧版 EN 引用令牌正则。
static LEGACY_EN_NOTE_REF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[EN-([^\]]+)\]").unwrap());

/// 本地定义行正则。
static LOCAL_DEF_LINE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\[\^([0-9]+)\]:\s*(.*)$").unwrap());

/// 定义行印刷编号前缀正则（同 LOCAL_DEF_LINE_RE，用于幂等前缀检查）。
static DEF_LINE_PRINTED_PREFIX_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\[\^(\d+)\]:\s*(.*)$").unwrap());

/// 判断正文中是否残留原始标记。
///
/// ←→ Python `_has_raw_marker_in_body()` (chapter_merge.py:321)
pub fn has_raw_marker_in_body(markdown_text: &str) -> bool {
    let body_text = helpers::split_body_and_definitions(markdown_text).0;
    let allowed_markers: HashSet<String> = {
        let mut set: HashSet<String> = HashSet::new();
        for caps in helpers::LOCAL_REF_RE.captures_iter(&body_text) {
            if let Some(m) = caps.get(1) {
                set.insert(m.as_str().to_string());
            }
        }
        for caps in helpers::LOCAL_DEF_RE.captures_iter(markdown_text) {
            if let Some(m) = caps.get(1) {
                set.insert(m.as_str().to_string());
            }
        }
        set
    };
    if allowed_markers.is_empty() {
        return false;
    }
    if !helpers::iter_raw_note_marker_hits(&body_text, Some(&allowed_markers)).is_empty() {
        return true;
    }
    if !helpers::iter_raw_superscript_note_marker_hits(&body_text, Some(&allowed_markers))
        .is_empty()
    {
        return true;
    }
    false
}

/// 按章节 ID 收集注释文本。
///
/// ←→ Python `_chapter_note_text_by_id()` (chapter_merge.py:338)
pub fn chapter_note_text_by_id(
    frozen_units: &FrozenUnits,
    chapter_id: &str,
) -> HashMap<String, String> {
    let mut payload: HashMap<String, String> = HashMap::new();
    for unit in &frozen_units.note_units {
        if unit.section_id.trim() != chapter_id.trim() {
            continue;
        }
        let note_id = unit.note_id.trim().to_string();
        if note_id.is_empty() {
            continue;
        }
        let source = if unit.translated_text.trim().is_empty() {
            &unit.source_text
        } else {
            &unit.translated_text
        };
        let text = note_lookup::sanitize_note_text(source);
        if export_constants::should_replace_definition_text(
            payload.get(&note_id).map_or("", |s| s.as_str()),
            &text,
        ) {
            payload.insert(note_id, text);
        }
    }
    payload
}

/// 收集全书注释文本。
///
/// ←→ Python `_book_note_text_by_id()` (chapter_merge.py:355)
pub fn book_note_text_by_id(frozen_units: &FrozenUnits) -> HashMap<String, String> {
    let mut payload: HashMap<String, String> = HashMap::new();
    for unit in &frozen_units.note_units {
        let note_id = unit.note_id.trim().to_string();
        if note_id.is_empty() {
            continue;
        }
        let source = if unit.translated_text.trim().is_empty() {
            &unit.source_text
        } else {
            &unit.translated_text
        };
        let text = note_lookup::sanitize_note_text(source);
        if export_constants::should_replace_definition_text(
            payload.get(&note_id).map_or("", |s| s.as_str()),
            &text,
        ) {
            payload.insert(note_id, text);
        }
    }
    payload
}

/// 构建章节 marker 序列。
///
/// ←→ Python `_chapter_marker_sequences()` (chapter_merge.py:366)
pub fn chapter_marker_sequences(
    chapter_layers: &ChapterLayers,
    chapter_id: &str,
    note_text_by_id: &HashMap<String, String>,
) -> HashMap<String, Vec<String>> {
    let mut sequences: HashMap<String, Vec<String>> = HashMap::new();
    let mut chapter_items: Vec<&fnm_core::records::NoteItemRecord> = chapter_layers
        .note_items
        .iter()
        .filter(|item| item.chapter_id.trim() == chapter_id.trim())
        .collect();
    chapter_items.sort_by_key(|item| (item.page_no, item.note_item_id.clone()));
    for item in &chapter_items {
        let note_id = resolve_note_id(&item.note_item_id, note_text_by_id);
        if note_id.is_empty() {
            continue;
        }
        let mut candidates: HashSet<String> = HashSet::new();
        candidates.extend(marker_aliases(&note_id));
        candidates.extend(marker_aliases(&item.marker));
        for marker in &candidates {
            sequences
                .entry(marker.clone())
                .or_default()
                .push(note_id.clone());
        }
    }
    sequences
}

/// 替换定义文本中的 {{NOTE_REF:N}} 令牌。
///
/// ←→ Python `_replace_def_note_refs()` 闭包 (chapter_merge.py:441)
fn replace_def_note_refs(def_text: &str, local_ref_numbers: &HashMap<String, i64>) -> String {
    let ref_num_to_note_id: HashMap<i64, String> = local_ref_numbers
        .iter()
        .map(|(k, v)| (*v, k.clone()))
        .collect();
    let mut last_ref_num: i64 = 0;
    export_constants::ANY_NOTE_REF_RE
        .replace_all(def_text, |caps: &regex::Captures| {
            for idx in 1..=4 {
                let captured = caps.get(idx).map(|m| m.as_str().trim()).unwrap_or("");
                if captured.is_empty() {
                    continue;
                }
                if captured.to_lowercase() == "ibid" {
                    if last_ref_num > 0 {
                        return format!("[^{}]", last_ref_num);
                    }
                    return caps
                        .get(0)
                        .map(|m| m.as_str().to_string())
                        .unwrap_or_default();
                }
                if let Ok(ref_num) = captured.parse::<i64>() {
                    if let Some(note_id) = ref_num_to_note_id.get(&ref_num) {
                        if let Some(&target_num) = local_ref_numbers.get(note_id) {
                            if target_num > 0 {
                                last_ref_num = target_num;
                                return format!("[^{}]", target_num);
                            }
                        }
                    }
                }
                return caps
                    .get(0)
                    .map(|m| m.as_str().to_string())
                    .unwrap_or_default();
            }
            caps.get(0)
                .map(|m| m.as_str().to_string())
                .unwrap_or_default()
        })
        .to_string()
}

/// 重写章节中的残留标记。
///
/// ←→ Python `_rewrite_residual_raw_markers_for_chapter()` (chapter_merge.py:393)
pub fn rewrite_residual_raw_markers_for_chapter(
    chapter: &ChapterMarkdownEntry,
    note_text_by_id: &HashMap<String, String>,
    _marker_note_sequences: &HashMap<String, Vec<String>>,
    fallback_note_text_by_id: Option<&HashMap<String, String>>,
) -> String {
    let markdown_text = chapter.markdown_text.as_str();
    if markdown_text.trim().is_empty() {
        return markdown_text.to_string();
    }
    let mut resolved_note_text_by_id: HashMap<String, String> =
        fallback_note_text_by_id.cloned().unwrap_or_default();
    for (k, v) in note_text_by_id {
        resolved_note_text_by_id.insert(k.clone(), v.clone());
    }
    let (body_text, definition_text) = helpers::split_body_and_definitions(markdown_text);
    let existing_numbers: Vec<i64> = {
        let mut nums: HashSet<i64> = HashSet::new();
        for caps in helpers::LOCAL_REF_RE.captures_iter(&body_text) {
            if let Ok(n) = caps[1].parse::<i64>() {
                nums.insert(n);
            }
        }
        for caps in helpers::LOCAL_DEF_RE.captures_iter(markdown_text) {
            if let Ok(n) = caps[1].parse::<i64>() {
                nums.insert(n);
            }
        }
        let mut sorted: Vec<i64> = nums.into_iter().collect();
        sorted.sort();
        sorted
    };

    let mut local_ref_numbers: HashMap<String, i64> = HashMap::new();
    let mut ordered_note_ids: Vec<String> = Vec::new();
    for &num in &existing_numbers {
        let key = format!("__reserved_{}", num);
        local_ref_numbers.insert(key.clone(), num);
        ordered_note_ids.push(key);
    }

    let tokenized_body = LEGACY_EN_NOTE_REF_RE
        .replace_all(&body_text, "{{NOTE_REF:$1}}")
        .to_string();
    let updated_body = replace_note_refs_with_local_labels(
        &tokenized_body,
        &resolved_note_text_by_id,
        &HashMap::new(),
        &mut local_ref_numbers,
        &mut ordered_note_ids,
        None, // footnote_ids_seen
        None, // note_marker_by_id
    );
    if updated_body == body_text {
        return markdown_text.to_string();
    }

    let mut definitions: HashMap<i64, String> = HashMap::new();
    for line in definition_text.lines() {
        let line = line.trim_end();
        if let Some(caps) = LOCAL_DEF_LINE_RE.captures(line) {
            if let Ok(number) = caps[1].parse::<i64>() {
                let text = caps[2].trim().to_string();
                if number > 0 && !text.is_empty() {
                    definitions.insert(number, text);
                }
            }
        }
    }

    for note_id in &ordered_note_ids {
        if note_id.starts_with("__reserved_") {
            continue;
        }
        let number = local_ref_numbers.get(note_id).copied().unwrap_or(0);
        if number <= 0 || definitions.contains_key(&number) {
            continue;
        }
        let text = resolved_note_text_by_id
            .get(note_id)
            .map(|s| s.trim().to_string())
            .unwrap_or_default();
        if !text.is_empty() {
            let replaced = replace_def_note_refs(&text, &local_ref_numbers);
            definitions.insert(number, replaced);
        }
    }

    let mut lines: Vec<String> = Vec::new();
    lines.push(updated_body.trim().to_string());
    if !definitions.is_empty() {
        lines.push(String::new());
        let mut sorted_keys: Vec<i64> = definitions.keys().copied().collect();
        sorted_keys.sort();
        for number in sorted_keys {
            if let Some(text) = definitions.get(&number) {
                lines.push(format!("[^{}]: {}", number, text));
            }
        }
    }
    lines.join("\n").trim().to_string()
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

/// 重写所有章节以供合稿。
///
/// ←→ Python `_rewrite_chapters_for_merge()` (chapter_merge.py:535)
pub fn rewrite_chapters_for_merge(
    chapters: &[ChapterMarkdownEntry],
    frozen_units: &FrozenUnits,
    chapter_layers: &ChapterLayers,
) -> Vec<ChapterMarkdownEntry> {
    let book_ntbi = book_note_text_by_id(frozen_units);
    let mut rewritten: Vec<ChapterMarkdownEntry> = Vec::new();
    for row in chapters {
        let chapter_id = row.chapter_id.trim();
        let ntbi = chapter_note_text_by_id(frozen_units, chapter_id);
        let mns = chapter_marker_sequences(chapter_layers, chapter_id, &ntbi);
        let markdown_text =
            rewrite_residual_raw_markers_for_chapter(row, &ntbi, &mns, Some(&book_ntbi));
        let start_page = row.start_page;
        let end_page = if row.end_page > 0 {
            row.end_page
        } else {
            start_page
        };
        let pages: Vec<i64> = row.pages.iter().filter(|&&p| p > 0).copied().collect();
        rewritten.push(ChapterMarkdownEntry {
            order: row.order,
            chapter_id: row.chapter_id.clone(),
            title: row.title.clone(),
            path: row.path.clone(),
            markdown_text,
            start_page,
            end_page,
            pages,
        });
    }
    rewritten
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
    helpers::LEGACY_FOOTNOTE_RE.is_match(text)
        || helpers::LEGACY_ENDNOTE_RE.is_match(text)
        || helpers::LEGACY_EN_BRACKET_RE.is_match(text)
        || helpers::LEGACY_NOTE_TOKEN_RE.is_match(text)
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

    #[test]
    fn test_apply_notes_block_format_numbered_prefix_idempotent() {
        let input = "Text.\n\n[^1]: 1. Already numbered.";
        let result = apply_notes_block_format(input);
        assert!(result.contains("[^1]: 1. Already numbered."));
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
    fn test_book_note_text_by_id_empty() {
        let frozen = FrozenUnits::default();
        let result = book_note_text_by_id(&frozen);
        assert!(result.is_empty());
    }

    #[test]
    fn test_chapter_note_text_by_id_no_match() {
        let frozen = FrozenUnits::default();
        let result = chapter_note_text_by_id(&frozen, "nonexistent");
        assert!(result.is_empty());
    }

    #[test]
    fn test_has_legacy_note_token_empty() {
        assert!(!has_legacy_note_token(""));
        assert!(!has_legacy_note_token("   "));
    }

    #[test]
    fn test_rewrite_residual_raw_markers_no_markers() {
        let entry = ChapterMarkdownEntry {
            markdown_text: "Clean text without any markers.".to_string(),
            ..Default::default()
        };
        let ntbi = HashMap::new();
        let mns = HashMap::new();
        let result = rewrite_residual_raw_markers_for_chapter(&entry, &ntbi, &mns, None);
        assert_eq!(result, "Clean text without any markers.");
    }

    #[test]
    fn test_rewrite_residual_raw_markers_empty() {
        let entry = ChapterMarkdownEntry {
            markdown_text: "".to_string(),
            ..Default::default()
        };
        let ntbi = HashMap::new();
        let mns = HashMap::new();
        let result = rewrite_residual_raw_markers_for_chapter(&entry, &ntbi, &mns, None);
        assert_eq!(result, "");
    }
}

//! ←→ FNM_RE/stages/export.py `_resolve_body_unit_text()`,
//! `_rewrite_body_text_with_local_refs()`

use std::collections::HashMap;

use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::export_constants::PENDING_TRANSLATION_TEXT;
use fnm_core::records::TranslationUnitRecord;
use fnm_core::ref_rewriter::{
    replace_note_refs_with_local_labels, replace_raw_bracket_refs_with_local_labels,
    replace_raw_superscript_refs_with_local_labels,
    replace_raw_unicode_superscript_refs_with_local_labels,
};
use fnm_core::refs::{replace_frozen_refs, EndnoteMode};

/// 匹配残留的 {{NOTE_REF:...}} 引用。
static FROZEN_NOTE_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\{\{NOTE_REF:([^}]+)\}\}").unwrap());

/// 匹配本地引用标记前的空白。
static SPACE_BEFORE_LOCAL_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\s+(\[\^[^\]]+\])").unwrap());

/// 解析正文段落实体文本：优先翻译 → diagnostic → source → pending。
///
/// ←→ Python `_resolve_body_unit_text()` (export.py:252)
pub fn resolve_body_unit_text(
    unit: &TranslationUnitRecord,
    include_diagnostic_entries: bool,
    diagnostic_machine_by_page: &HashMap<i64, String>,
) -> String {
    let translated = unit.translated_text.trim();
    if !translated.is_empty() {
        return translated.to_string();
    }
    if include_diagnostic_entries {
        let page_numbers: Vec<i64> = {
            let mut nums: Vec<i64> = unit
                .page_segments
                .iter()
                .map(|s| s.page_no)
                .filter(|p| *p > 0)
                .collect();
            if nums.is_empty() && unit.page_start > 0 {
                let start = unit.page_start;
                let end = unit.page_end.max(start);
                nums = (start..=end).collect();
            }
            nums.sort();
            nums.dedup();
            nums
        };
        let diagnostic_parts: Vec<String> = page_numbers
            .iter()
            .filter_map(|pn| diagnostic_machine_by_page.get(pn))
            .map(|t| t.trim().to_string())
            .filter(|t| !t.is_empty())
            .collect();
        if !diagnostic_parts.is_empty() {
            return diagnostic_parts.join("\n\n");
        }
    }
    let source = unit.source_text.trim();
    if !source.is_empty() {
        source.to_string()
    } else {
        PENDING_TRANSLATION_TEXT.to_string()
    }
}

/// 重写正文文本中的引用标记为本地标签。
///
/// ←→ Python `_rewrite_body_text_with_local_refs()` (export.py:284)
///
/// Clippy lint `needless_option_as_deref` suppressed: the param is
/// `Option<&mut Vec<String>>` and must be reborrowed across 4 calls.
#[allow(clippy::too_many_arguments, clippy::needless_option_as_deref)]
pub fn rewrite_body_text_with_local_refs(
    text: &str,
    note_text_by_id: &HashMap<String, String>,
    note_kind_by_id: &HashMap<String, String>,
    marker_note_sequences: &HashMap<String, Vec<String>>,
    local_ref_numbers: &mut HashMap<String, i64>,
    ordered_note_ids: &mut Vec<String>,
    mut footnote_ids_seen: Option<&mut Vec<String>>,
    note_marker_by_id: Option<&HashMap<String, String>>,
) -> String {
    // Step 1: {{NOTE_REF:...}} → [^N] 标签
    let mut updated = replace_note_refs_with_local_labels(
        text,
        note_text_by_id,
        note_kind_by_id,
        local_ref_numbers,
        ordered_note_ids,
        footnote_ids_seen.as_deref_mut(),
        note_marker_by_id,
    );

    // Step 2-4: raw bracket → superscript → unicode superscript
    let mut marker_usage_index: HashMap<String, usize> = HashMap::new();
    updated = replace_raw_bracket_refs_with_local_labels(
        &updated,
        marker_note_sequences,
        &mut marker_usage_index,
        note_kind_by_id,
        local_ref_numbers,
        ordered_note_ids,
        footnote_ids_seen.as_deref_mut(),
        note_marker_by_id,
    );
    updated = replace_raw_superscript_refs_with_local_labels(
        &updated,
        marker_note_sequences,
        &mut marker_usage_index,
        note_kind_by_id,
        local_ref_numbers,
        ordered_note_ids,
        footnote_ids_seen.as_deref_mut(),
        note_marker_by_id,
    );
    updated = replace_raw_unicode_superscript_refs_with_local_labels(
        &updated,
        marker_note_sequences,
        &mut marker_usage_index,
        note_kind_by_id,
        local_ref_numbers,
        ordered_note_ids,
        footnote_ids_seen.as_deref_mut(),
        note_marker_by_id,
    );

    // Step 5: frozen ref 最终处理
    updated = replace_frozen_refs(&updated, EndnoteMode::Legacy);

    // Step 6: 残留 {{NOTE_REF:...}} 的兜底替换
    let refs_to_replace: Vec<(String, String)> = FROZEN_NOTE_REF_RE
        .captures_iter(&updated)
        .filter_map(|caps| {
            let nid = caps.get(1)?.as_str().trim().to_string();
            let ref_num = local_ref_numbers.get(&nid).copied().unwrap_or(0);
            if ref_num > 0 {
                Some((caps.get(0)?.as_str().to_string(), format!("[^{ref_num}]")))
            } else {
                None
            }
        })
        .collect();
    for (old, new) in &refs_to_replace {
        // 仅替换第一个出现（匹配 Python 的 .replace(match, replacement, 1)）
        if let Some(pos) = updated.find(old.as_str()) {
            updated = format!("{}{}{}", &updated[..pos], new, &updated[pos + old.len()..]);
        }
    }

    // Step 7: 清除本地引用标记前的空白
    updated = SPACE_BEFORE_LOCAL_REF_RE
        .replace_all(&updated, "$1")
        .to_string();

    updated
}

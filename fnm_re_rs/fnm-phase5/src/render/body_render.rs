use std::collections::HashMap;

use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::export_constants::{PENDING_TRANSLATION_TEXT, RAW_BRACKET_NOTE_REF_RE};
use fnm_core::records::TranslationUnitRecord;
use fnm_core::ref_rewriter::{
    replace_note_refs_with_local_labels, replace_raw_bracket_refs_with_local_labels,
    replace_raw_superscript_refs_with_local_labels,
    replace_raw_unicode_superscript_refs_with_local_labels,
};
use fnm_core::refs::replace_frozen_refs;

static FROZEN_NOTE_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\{\{NOTE_REF:([^}]+)\}\}").unwrap());

static SPACE_BEFORE_LOCAL_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\s+(\[\^[^\]]+\])").unwrap());

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

/// rewrite_body_text_with_local_refs 的只读上下文。
pub struct LocalRefContext<'a> {
    pub note_text_by_id: &'a HashMap<String, String>,
    pub note_kind_by_id: &'a HashMap<String, String>,
    pub marker_note_sequences: &'a HashMap<String, Vec<String>>,
    pub note_marker_by_id: Option<&'a HashMap<String, String>>,
}

pub fn rewrite_body_text_with_local_refs(
    text: &str,
    ctx: &LocalRefContext,
    local_ref_numbers: &mut HashMap<String, i64>,
    ordered_note_ids: &mut Vec<String>,
    mut footnote_ids_seen: Option<&mut Vec<String>>,
) -> String {
    let mut updated = replace_note_refs_with_local_labels(
        text,
        ctx.note_text_by_id,
        ctx.note_kind_by_id,
        local_ref_numbers,
        ordered_note_ids,
        footnote_ids_seen.as_deref_mut(),
        ctx.note_marker_by_id,
    );

    let mut marker_usage_index: HashMap<String, usize> = HashMap::new();
    let mut rewrite_ctx = fnm_core::ref_rewriter::MarkerRewriteContext {
        marker_note_sequences: ctx.marker_note_sequences,
        marker_usage_index: &mut marker_usage_index,
        note_kind_by_id: ctx.note_kind_by_id,
        local_ref_numbers,
        ordered_note_ids,
        footnote_ids_seen,
        note_marker_by_id: ctx.note_marker_by_id,
    };
    updated = replace_raw_bracket_refs_with_local_labels(&updated, &mut rewrite_ctx);
    updated = replace_raw_superscript_refs_with_local_labels(&updated, &mut rewrite_ctx);
    updated = replace_raw_unicode_superscript_refs_with_local_labels(&updated, &mut rewrite_ctx);

    use std::collections::HashSet;
    // 条件转换：对已在 local_ref_numbers 中但未被 raw_bracket 转换的 [N] 标记，补充转换为 [^N]
    // 不转换不在 local_ref_numbers 中的 [N]（避免误转日期/页码等非引用）
    let local_ref_set: HashSet<i64> = local_ref_numbers.values().copied().collect();
    updated = RAW_BRACKET_NOTE_REF_RE
        .replace_all(&updated, |caps: &regex::Captures| {
            let marker = caps.get(1).map(|m| m.as_str().trim()).unwrap_or("");
            if marker.is_empty() {
                return caps
                    .get(0)
                    .map(|m| m.as_str().to_string())
                    .unwrap_or_default();
            }
            if let Ok(n) = marker.parse::<i64>() {
                if local_ref_set.contains(&n) {
                    return format!("[^{}]", n);
                }
            }
            caps.get(0)
                .map(|m| m.as_str().to_string())
                .unwrap_or_default()
        })
        .to_string();

    updated = replace_frozen_refs(&updated);

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
        if let Some(pos) = updated.find(old.as_str()) {
            updated = format!("{}{}{}", &updated[..pos], new, &updated[pos + old.len()..]);
        }
    }

    updated = SPACE_BEFORE_LOCAL_REF_RE
        .replace_all(&updated, "$1")
        .to_string();

    updated
}

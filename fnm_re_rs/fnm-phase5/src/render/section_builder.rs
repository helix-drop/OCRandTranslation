//! Section markdown 构建逻辑。
//!
//! ←→ Python `section_render.py` 中的子步骤

use std::collections::{HashMap, HashSet};

use fnm_core::records::TranslationUnitRecord;

use super::body_render;

/// 构建 body units 的排序列表。
pub(super) fn sorted_body_units<'a>(
    body_units: &'a [TranslationUnitRecord],
    chapter_id: &str,
) -> Vec<&'a TranslationUnitRecord> {
    let mut sorted: Vec<&TranslationUnitRecord> = body_units
        .iter()
        .filter(|u| u.section_id == chapter_id)
        .collect();
    sorted.sort_by(|a, b| {
        a.page_start
            .cmp(&b.page_start)
            .then(
                a.page_end
                    .max(a.page_start)
                    .cmp(&b.page_end.max(b.page_start)),
            )
            .then(a.unit_id.cmp(&b.unit_id))
    });
    sorted
}

/// 处理单个 body unit 的只读上下文。
pub(super) struct BodyUnitContext<'a> {
    pub include_diagnostic_entries: bool,
    pub diagnostic_machine_by_page: &'a HashMap<i64, String>,
    pub note_text_by_id: &'a HashMap<String, String>,
    pub note_kind_by_id: &'a HashMap<String, String>,
    pub marker_note_sequences: &'a HashMap<String, Vec<String>>,
    pub note_marker_by_id: &'a HashMap<String, String>,
    pub section_heads_by_page: &'a HashMap<i64, Vec<String>>,
}

/// 处理单个 body unit，返回 (body_text, new_footnote_lines)。
pub(super) fn process_body_unit(
    unit: &TranslationUnitRecord,
    ctx: &BodyUnitContext,
    local_ref_numbers: &mut HashMap<String, i64>,
    ordered_note_ids: &mut Vec<String>,
    footnote_ids_written: &mut Vec<String>,
    seen_section_heads: &mut HashSet<(i64, String)>,
    lines: &mut Vec<String>,
) -> bool {
    use fnm_core::export_constants::ANY_NOTE_REF_RE;

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

    for page_no in &page_numbers {
        if let Some(titles) = ctx.section_heads_by_page.get(page_no) {
            for t in titles {
                let dedupe_key = (*page_no, t.to_lowercase());
                if seen_section_heads.contains(&dedupe_key) {
                    continue;
                }
                seen_section_heads.insert(dedupe_key);
                lines.push(format!("### {t}"));
                lines.push(String::new());
            }
        }
    }

    let body_text = body_render::resolve_body_unit_text(
        unit,
        ctx.include_diagnostic_entries,
        ctx.diagnostic_machine_by_page,
    );
    let prev_footnote_count = footnote_ids_written.len();
    let body_text = body_render::rewrite_body_text_with_local_refs(
        &body_text,
        &body_render::LocalRefContext {
            note_text_by_id: ctx.note_text_by_id,
            note_kind_by_id: ctx.note_kind_by_id,
            marker_note_sequences: ctx.marker_note_sequences,
            note_marker_by_id: Some(ctx.note_marker_by_id),
        },
        local_ref_numbers,
        ordered_note_ids,
        Some(footnote_ids_written),
    );

    let body_text = if unit.translated_text.trim().is_empty()
        && !ctx.include_diagnostic_entries
        && ctx.note_text_by_id.is_empty()
        && ANY_NOTE_REF_RE.is_match(&body_text)
    {
        fnm_core::export_constants::PENDING_TRANSLATION_TEXT.to_string()
    } else {
        body_text
    };

    let body_text = body_text.trim().to_string();
    if body_text.is_empty() {
        return false;
    }

    lines.push(body_text);

    let new_footnotes: Vec<String> = footnote_ids_written[prev_footnote_count..]
        .iter()
        .filter_map(|fn_id| {
            let fn_text = ctx
                .note_text_by_id
                .get(fn_id)
                .map(|t| t.trim().to_string())
                .unwrap_or_default();
            if fn_text.is_empty() {
                None
            } else {
                Some(format!("[footnote] \\* {fn_text}"))
            }
        })
        .collect();
    for fn_line in &new_footnotes {
        lines.push(fn_line.clone());
    }
    lines.push(String::new());

    true
}

/// 计算 contract summary（ref/def 计数）。
pub(super) fn compute_contract_summary(
    content: &str,
    known_unlinked_count: i64,
) -> HashMap<String, i64> {
    use fnm_core::export_constants::{LOCAL_FOOTNOTE_DEF_RE, LOCAL_FOOTNOTE_REF_RE};
    use once_cell::sync::Lazy;
    use regex::Regex;

    static INLINE_FOOTNOTE_LINE_RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"(?m)^\[footnote\]\\\*").unwrap());

    let body_part = if let Some(pos) = content.find("### NOTES") {
        &content[..pos]
    } else {
        content
    };

    let ref_nums: HashSet<i64> = LOCAL_FOOTNOTE_REF_RE
        .captures_iter(body_part)
        .filter_map(|c| c.get(1)?.as_str().parse::<i64>().ok())
        .collect();
    let def_nums: HashSet<i64> = LOCAL_FOOTNOTE_DEF_RE
        .captures_iter(content)
        .filter_map(|c| c.get(1)?.as_str().parse::<i64>().ok())
        .collect();
    let footnote_def_count = INLINE_FOOTNOTE_LINE_RE.captures_iter(content).count() as i64;

    let ref_count = ref_nums.len() as i64;
    let def_count = def_nums.len() as i64;
    let missing = ref_nums.difference(&def_nums).count() as i64;
    let effective_missing = (missing - footnote_def_count - known_unlinked_count).max(0);
    let orphan_def_count = def_nums.difference(&ref_nums).count() as i64;

    let mut summary = HashMap::new();
    summary.insert("local_ref_count".to_string(), ref_count);
    summary.insert(
        "local_definition_count".to_string(),
        def_count + footnote_def_count,
    );
    summary.insert("missing_definition_count".to_string(), effective_missing);
    summary.insert("orphan_definition_count".to_string(), orphan_def_count);
    summary.insert(
        "known_unlinked_definition_count".to_string(),
        known_unlinked_count,
    );
    summary.insert("inline_footnote_paragraph_attach_count".to_string(), 0);
    summary.insert("inline_footnote_page_fallback_count".to_string(), 0);
    summary.insert(
        "chapter_end_footnote_definition_count".to_string(),
        def_count + footnote_def_count,
    );

    summary
}

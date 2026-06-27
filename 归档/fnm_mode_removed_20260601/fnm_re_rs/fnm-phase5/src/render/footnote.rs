use std::collections::{HashMap, HashSet};

use fnm_core::records::{
    BodyAnchorRecord, NoteItemRecord, NoteLinkRecord, SectionHeadRecord, TranslationUnitRecord,
};

use super::body_render;
use super::chapter_pages;
use super::markdown_clean;
use super::note_lookup;
use super::section_head;
use super::title;
use crate::render::section_render::ChapterExportInput;

#[expect(clippy::too_many_arguments)]
pub fn build_inline_footnote_section_markdown(
    chapter: &ChapterExportInput,
    section_heads: &[SectionHeadRecord],
    body_units: &[TranslationUnitRecord],
    note_units: &[TranslationUnitRecord],
    _matched_links: &[NoteLinkRecord],
    _note_items_by_id: &HashMap<String, NoteItemRecord>,
    _body_anchors_by_id: &HashMap<String, BodyAnchorRecord>,
    include_diagnostic_entries: bool,
    diagnostic_machine_by_page: &HashMap<i64, String>,
    _skipped_note_ids: Option<&HashSet<String>>,
) -> (String, HashMap<String, i64>) {
    let chapter_id = &chapter.chapter_id;
    let chapter_title = title::format_chapter_title(&chapter.title, chapter_id);
    let chapter_pages_set: HashSet<i64> =
        chapter_pages::chapter_page_numbers(&chapter.pages, chapter.start_page, chapter.end_page)
            .into_iter()
            .collect();

    let note_text_by_id =
        note_lookup::build_note_text_by_id_for_chapter(Some(chapter_id), note_units);
    let section_heads_by_page =
        section_head::build_section_heads_by_page(chapter_id, section_heads, &chapter_pages_set);

    let mut lines: Vec<String> = vec![format!("## {chapter_title}"), String::new()];
    let mut seen_section_heads: HashSet<(i64, String)> = HashSet::new();
    let mut local_ref_numbers: HashMap<String, i64> = HashMap::new();
    let mut ordered_note_ids: Vec<String> = Vec::new();
    let mut chapter_has_body = false;

    let mut sorted_units: Vec<&TranslationUnitRecord> = body_units
        .iter()
        .filter(|u| u.section_id == *chapter_id)
        .collect();
    sorted_units.sort_by(|a, b| {
        a.page_start
            .cmp(&b.page_start)
            .then(
                a.page_end
                    .max(a.page_start)
                    .cmp(&b.page_end.max(b.page_start)),
            )
            .then(a.unit_id.cmp(&b.unit_id))
    });

    for unit in &sorted_units {
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
            if let Some(titles) = section_heads_by_page.get(page_no) {
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
            include_diagnostic_entries,
            diagnostic_machine_by_page,
        );
        let body_text = body_render::rewrite_body_text_with_local_refs(
            &body_text,
            &body_render::LocalRefContext {
                note_text_by_id: &note_text_by_id,
                note_kind_by_id: &HashMap::new(),
                marker_note_sequences: &HashMap::new(),
                note_marker_by_id: None,
            },
            &mut local_ref_numbers,
            &mut ordered_note_ids,
            None,
        );

        let body_text = body_text.trim().to_string();
        if body_text.is_empty() {
            continue;
        }
        chapter_has_body = true;
        lines.push(body_text);
        lines.push(String::new());
    }

    if !chapter_has_body {
        lines.push(fnm_core::export_constants::PENDING_TRANSLATION_TEXT.to_string());
        lines.push(String::new());
    }

    let joined = lines.join("\n").trim().to_string();
    let content = markdown_clean::strip_trailing_image_only_block(&joined);
    let content = markdown_clean::clean_export_html(&content);

    let mut contract_summary = HashMap::new();
    contract_summary.insert("local_ref_count".to_string(), 0);
    contract_summary.insert("local_definition_count".to_string(), 0);
    contract_summary.insert("missing_definition_count".to_string(), 0);
    contract_summary.insert("orphan_definition_count".to_string(), 0);
    contract_summary.insert("known_unlinked_definition_count".to_string(), 0);
    contract_summary.insert("inline_footnote_paragraph_attach_count".to_string(), 0);
    contract_summary.insert("inline_footnote_page_fallback_count".to_string(), 0);
    contract_summary.insert("chapter_end_footnote_definition_count".to_string(), 0);

    (content, contract_summary)
}

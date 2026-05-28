use std::collections::{HashMap, HashSet};

use anyhow::Result;
use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::marker_seq::build_raw_marker_note_sequences;
use fnm_core::records::{
    BodyAnchorRecord, NoteItemRecord, NoteLinkRecord, SectionHeadRecord, TranslationUnitRecord,
};
use fnm_core::types::NoteKind;

use super::chapter_pages;
use super::markdown_clean;
use super::note_lookup;
use super::section_builder;
use super::section_head;
use super::title;

static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

pub struct ChapterExportInput {
    pub chapter_id: String,
    pub title: String,
    pub pages: Vec<i64>,
    pub start_page: i64,
    pub end_page: i64,
}

pub struct SectionMarkdownInput<'a> {
    pub chapter: &'a ChapterExportInput,
    pub section_heads: &'a [SectionHeadRecord],
    pub body_units: &'a [TranslationUnitRecord],
    pub note_units: &'a [TranslationUnitRecord],
    pub matched_links: &'a [NoteLinkRecord],
    pub note_items_by_id: &'a HashMap<String, NoteItemRecord>,
    pub body_anchors_by_id: &'a HashMap<String, BodyAnchorRecord>,
    pub include_diagnostic_entries: bool,
    pub diagnostic_machine_by_page: &'a HashMap<i64, String>,
    pub book_type: &'a str,
    pub chapter_note_mode: &'a str,
    pub skipped_note_ids: Option<&'a HashSet<String>>,
}

#[derive(Debug)]
pub struct SectionMarkdownResult {
    pub content: String,
    pub contract_summary: HashMap<String, i64>,
}

fn safe_int(s: &str) -> i64 {
    s.trim().parse::<i64>().unwrap_or(0)
}

fn emit_definitions(
    ids: &[String],
    note_text_by_id: &HashMap<String, String>,
    global_note_text_by_id: &HashMap<String, String>,
    note_items_by_id: &HashMap<String, NoteItemRecord>,
    local_ref_numbers: &HashMap<String, i64>,
    skipped_note_ids: Option<&HashSet<String>>,
) -> (Vec<String>, i64) {
    let skip_ids: HashSet<&str> = match skipped_note_ids {
        Some(set) => set.iter().map(|s| s.as_str()).collect(),
        None => HashSet::new(),
    };

    let mut sorted_ids: Vec<&String> = ids.iter().collect();
    sorted_ids.sort_by(|a, b| {
        let a_item = note_items_by_id.get(*a);
        let b_item = note_items_by_id.get(*b);
        let a_val = a_item
            .and_then(|item| {
                let m = item.marker.trim();
                if m.is_empty() {
                    None
                } else {
                    let v = safe_int(m);
                    if v > 0 {
                        Some(v)
                    } else {
                        None
                    }
                }
            })
            .unwrap_or(999999);
        let b_val = b_item
            .and_then(|item| {
                let m = item.marker.trim();
                if m.is_empty() {
                    None
                } else {
                    let v = safe_int(m);
                    if v > 0 {
                        Some(v)
                    } else {
                        None
                    }
                }
            })
            .unwrap_or(999999);
        a_val.cmp(&b_val).then_with(|| (*a).cmp(b))
    });

    let mut rendered: Vec<String> = Vec::new();
    let mut known_unlinked_count: i64 = 0;

    for note_id in &sorted_ids {
        let text = note_text_by_id
            .get(note_id.as_str())
            .or_else(|| global_note_text_by_id.get(note_id.as_str()))
            .map(|t| t.trim().to_string())
            .unwrap_or_default();
        if text.is_empty() {
            continue;
        }
        if skip_ids.contains(note_id.as_str()) {
            known_unlinked_count += 1;
            let display_marker = note_items_by_id
                .get(note_id.as_str())
                .map(|item| item.marker.trim().to_string())
                .unwrap_or_default();
            if display_marker.is_empty() {
                rendered.push(format!("> {text}"));
            } else {
                rendered.push(format!("> {display_marker}. {text}"));
            }
        } else {
            let number = local_ref_numbers
                .get(note_id.as_str())
                .copied()
                .unwrap_or(0);
            if number <= 0 {
                continue;
            }
            // 修复：使用 [^N]: 而非 [N]:
            rendered.push(format!("[^{number}]: {text}"));
        }
    }

    if rendered.is_empty() {
        return (vec![], known_unlinked_count);
    }

    let mut lines = vec!["### NOTES".to_string(), String::new()];
    lines.extend(rendered);
    (lines, known_unlinked_count)
}

pub fn build_section_markdown(input: &SectionMarkdownInput) -> Result<SectionMarkdownResult> {
    let chapter_id = &input.chapter.chapter_id;
    let chapter_title = title::format_chapter_title(&input.chapter.title, chapter_id);
    let chapter_pages_set: HashSet<i64> = chapter_pages::chapter_page_numbers(
        &input.chapter.pages,
        input.chapter.start_page,
        input.chapter.end_page,
    )
    .into_iter()
    .collect();

    if input.book_type == "mixed" && input.chapter_note_mode == "footnote_primary" {
        let (content, contract_summary) = super::footnote::build_inline_footnote_section_markdown(
            input.chapter,
            input.section_heads,
            input.body_units,
            input.note_units,
            input.matched_links,
            input.note_items_by_id,
            input.body_anchors_by_id,
            input.include_diagnostic_entries,
            input.diagnostic_machine_by_page,
            input.skipped_note_ids,
        );
        return Ok(SectionMarkdownResult {
            content,
            contract_summary,
        });
    }

    let note_text_by_id =
        note_lookup::build_note_text_by_id_for_chapter(Some(chapter_id), input.note_units);
    let note_kind_by_id =
        note_lookup::build_note_kind_by_id_for_chapter(Some(chapter_id), input.note_units);
    let marker_note_sequences = build_raw_marker_note_sequences(
        chapter_id,
        input.matched_links,
        input.note_items_by_id,
        input.body_anchors_by_id,
        &note_text_by_id,
    );
    let section_heads_by_page = section_head::build_section_heads_by_page(
        chapter_id,
        input.section_heads,
        &chapter_pages_set,
    );

    let mut lines: Vec<String> = vec![format!("## {chapter_title}"), String::new()];
    let mut seen_section_heads: HashSet<(i64, String)> = HashSet::new();
    let mut local_ref_numbers: HashMap<String, i64> = HashMap::new();
    let mut ordered_note_ids: Vec<String> = Vec::new();
    let mut footnote_ids_written: Vec<String> = Vec::new();

    let note_marker_by_id: HashMap<String, String> = input
        .note_items_by_id
        .iter()
        .filter(|(_, item)| item.chapter_id == *chapter_id)
        .filter(|(_, item)| {
            let marker = item.marker.trim();
            !marker.is_empty() && marker.chars().all(|c| c.is_ascii_digit())
        })
        .map(|(nid, item)| (nid.clone(), item.marker.trim().to_string()))
        .collect();

    if let Some(skipped) = input.skipped_note_ids {
        for nid in skipped {
            if let Some(item) = input.note_items_by_id.get(nid) {
                if item.note_kind != NoteKind::Endnote {
                    continue;
                }
                if item.chapter_id != *chapter_id {
                    continue;
                }
                let marker = item.marker.trim();
                if marker.chars().all(|c| c.is_ascii_digit()) {
                    let reserved: i64 = safe_int(marker);
                    if reserved > 0 && !local_ref_numbers.contains_key(nid) {
                        local_ref_numbers.insert(nid.clone(), reserved);
                        ordered_note_ids.push(nid.clone());
                    }
                }
            }
        }
    }

    // 处理 body units
    let ctx = section_builder::BodyUnitContext {
        include_diagnostic_entries: input.include_diagnostic_entries,
        diagnostic_machine_by_page: input.diagnostic_machine_by_page,
        note_text_by_id: &note_text_by_id,
        note_kind_by_id: &note_kind_by_id,
        marker_note_sequences: &marker_note_sequences,
        note_marker_by_id: &note_marker_by_id,
        section_heads_by_page: &section_heads_by_page,
    };

    let sorted_units = section_builder::sorted_body_units(input.body_units, chapter_id);
    let mut chapter_has_body = false;
    for unit in &sorted_units {
        let has_body = section_builder::process_body_unit(
            unit,
            &ctx,
            &mut local_ref_numbers,
            &mut ordered_note_ids,
            &mut footnote_ids_written,
            &mut seen_section_heads,
            &mut lines,
        );
        if has_body {
            chapter_has_body = true;
        }
    }

    if !chapter_has_body {
        lines.push(fnm_core::export_constants::PENDING_TRANSLATION_TEXT.to_string());
        lines.push(String::new());
    }

    // 处理 section heads
    for head in input.section_heads {
        if head.chapter_id != *chapter_id {
            continue;
        }
        if !section_head::is_exportable_section_head(head) {
            continue;
        }
        let title = WHITESPACE_RE
            .replace_all(head.title.trim(), " ")
            .trim()
            .to_string();
        if title.is_empty() {
            continue;
        }
        let page_no = head.page_no;
        if page_no <= 0 || (!chapter_pages_set.is_empty() && !chapter_pages_set.contains(&page_no))
        {
            continue;
        }
        let dedupe_key = (page_no, title.to_lowercase());
        if seen_section_heads.contains(&dedupe_key) {
            continue;
        }
        seen_section_heads.insert(dedupe_key);
        lines.push(format!("### {title}"));
        lines.push(String::new());
    }

    // 处理 endnote definitions
    let endnote_ids: Vec<String> = ordered_note_ids
        .iter()
        .filter(|nid| note_kind_by_id.get(*nid).map(|k| k.as_str()) == Some("endnote"))
        .cloned()
        .collect();

    let global_note_text_by_id =
        note_lookup::build_note_text_by_id_for_chapter(None, input.note_units);

    let (definition_lines, known_unlinked_count) = emit_definitions(
        &endnote_ids,
        &note_text_by_id,
        &global_note_text_by_id,
        input.note_items_by_id,
        &local_ref_numbers,
        input.skipped_note_ids,
    );
    lines.extend(definition_lines);

    let joined = lines.join("\n").trim().to_string();
    let content = markdown_clean::strip_trailing_image_only_block(&joined);
    let content = markdown_clean::clean_export_html(&content);

    // 计算 contract summary
    let contract_summary =
        section_builder::compute_contract_summary(&content, known_unlinked_count);

    Ok(SectionMarkdownResult {
        content,
        contract_summary,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::NoteKind;

    #[test]
    fn test_endnote_definition_format_uses_caret() {
        let note_id = "n1".to_string();
        let mut note_items_by_id = HashMap::new();
        note_items_by_id.insert(
            note_id.clone(),
            NoteItemRecord {
                note_item_id: note_id.clone(),
                chapter_id: "ch1".to_string(),
                page_no: 5,
                marker: "1".to_string(),
                note_kind: NoteKind::Endnote,
                ..Default::default()
            },
        );

        let mut note_text_by_id = HashMap::new();
        note_text_by_id.insert(note_id.clone(), "First endnote text.".to_string());

        let global_note_text_by_id = HashMap::new();
        let mut local_ref_numbers = HashMap::new();
        local_ref_numbers.insert(note_id.clone(), 1_i64);

        let ids = vec![note_id.clone()];
        let (lines, unlinked) = emit_definitions(
            &ids,
            &note_text_by_id,
            &global_note_text_by_id,
            &note_items_by_id,
            &local_ref_numbers,
            None,
        );

        assert_eq!(unlinked, 0);
        assert!(!lines.is_empty(), "should produce definition lines");
        let joined = lines.join("\n");
        assert!(
            joined.contains("[^1]:"),
            "endnote definition must use [^N]: format, got: {joined}"
        );
        assert!(
            !joined.contains("[1]:"),
            "endnote definition must NOT use [N]: format (missing caret), got: {joined}"
        );
    }

    #[test]
    fn test_endnote_definition_skipped_format() {
        let note_id = "n_skipped".to_string();
        let mut note_items_by_id = HashMap::new();
        note_items_by_id.insert(
            note_id.clone(),
            NoteItemRecord {
                note_item_id: note_id.clone(),
                chapter_id: "ch1".to_string(),
                page_no: 5,
                marker: "1".to_string(),
                note_kind: NoteKind::Endnote,
                ..Default::default()
            },
        );

        let mut note_text_by_id = HashMap::new();
        note_text_by_id.insert(note_id.clone(), "Skipped endnote.".to_string());

        let global_note_text_by_id = HashMap::new();
        let local_ref_numbers = HashMap::new();

        let mut skipped = HashSet::new();
        skipped.insert(note_id.clone());

        let ids = vec![note_id.clone()];
        let (lines, unlinked) = emit_definitions(
            &ids,
            &note_text_by_id,
            &global_note_text_by_id,
            &note_items_by_id,
            &local_ref_numbers,
            Some(&skipped),
        );

        assert_eq!(unlinked, 1);
        let joined = lines.join("\n");
        assert!(joined.contains("> 1. "));
        assert!(!joined.contains("[^1]:"));
    }
}

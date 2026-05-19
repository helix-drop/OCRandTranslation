//! ←→ FNM_RE/stages/export_footnote.py
//! 翻译的函数：
//!   visible_segment_paragraphs             ←→ _visible_segment_paragraphs (export_footnote.py:44)
//!   paragraph_render_text                  ←→ _paragraph_render_text (export_footnote.py:53)
//!   emit_local_note_definitions            ←→ _emit_local_note_definitions (export_footnote.py:71)
//!   build_inline_footnote_targets           ←→ _build_inline_footnote_targets (export_footnote.py:107)
//!   note_marker                             ←→ _note_marker (export_footnote.py:155)
//!   is_numeric_note                         ←→ _is_numeric_note (export_footnote.py:160)
//!   split_numeric_note_ids                  ←→ _split_numeric_note_ids (export_footnote.py:164)
//!   emit_symbol_footnotes                   ←→ _emit_symbol_footnotes (export_footnote.py:179)
//!   build_inline_footnote_section_markdown  ←→ _build_inline_footnote_section_markdown (export_footnote.py:204)

use std::collections::{HashMap, HashSet};

use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::export_constants::{
    ANY_NOTE_REF_RE, LOCAL_FOOTNOTE_DEF_RE, LOCAL_FOOTNOTE_REF_RE, PENDING_TRANSLATION_TEXT,
};
use fnm_core::marker_seq::build_raw_marker_note_sequences;
use fnm_core::records::{
    BodyAnchorRecord, NoteItemRecord, NoteLinkRecord, SectionHeadRecord, TranslationUnitRecord,
    UnitPageSegmentRecord, UnitParagraphRecord,
};
use fnm_core::ref_rewriter::resolve_note_id;
use fnm_core::types::{LinkStatus, NoteKind};

use super::body_render::rewrite_body_text_with_local_refs;
use super::chapter_pages::chapter_page_numbers;
use super::markdown_clean::{
    clean_export_html, escape_leading_asterisks, strip_trailing_image_only_block,
};
use super::note_lookup::build_note_text_by_id_for_chapter;
use super::paragraph_key::normalized_paragraph_key;
use super::section_head::build_section_heads_by_page;
use super::section_render::ChapterExportInput;
use super::title::format_chapter_title;

static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

/// 从 segment 中过滤出可见段落（未 consumed）。
///
/// ←→ Python `_visible_segment_paragraphs()` (export_footnote.py:44)
pub fn visible_segment_paragraphs(segment: &UnitPageSegmentRecord) -> Vec<&UnitParagraphRecord> {
    segment
        .paragraphs
        .iter()
        .filter(|p| !p.consumed_by_prev)
        .collect()
}

/// 获取段落实体文本：优先 translated → display → source。
///
/// ←→ Python `_paragraph_render_text()` (export_footnote.py:53)
pub fn paragraph_render_text(paragraph: &UnitParagraphRecord) -> &str {
    let t = paragraph.translated_text.trim();
    if !t.is_empty() {
        return t;
    }
    let d = paragraph.display_text.trim();
    if !d.is_empty() {
        return d;
    }
    paragraph.source_text.trim()
}

/// 发射本地注释定义行 [^N]: text。
///
/// ←→ Python `_emit_local_note_definitions()` (export_footnote.py:71)
pub fn emit_local_note_definitions(
    note_ids: &[String],
    lines: &mut Vec<String>,
    emitted_note_ids: &mut HashSet<String>,
    local_ref_numbers: &HashMap<String, i64>,
    note_text_by_id: &HashMap<String, String>,
    skipped_note_ids: Option<&HashSet<String>>,
    note_items_by_id: &HashMap<String, NoteItemRecord>,
) -> i64 {
    let skip_ids: HashSet<&str> = match skipped_note_ids {
        Some(set) => set.iter().map(|s| s.as_str()).collect(),
        None => HashSet::new(),
    };
    let mut emitted: i64 = 0;
    for note_id in note_ids {
        if emitted_note_ids.contains(note_id) {
            continue;
        }
        let text = note_text_by_id
            .get(note_id.as_str())
            .map(|t| t.trim().to_string())
            .unwrap_or_default();
        if text.is_empty() {
            continue;
        }
        if skip_ids.contains(note_id.as_str()) {
            let display_marker = note_items_by_id
                .get(note_id.as_str())
                .map(|item| item.marker.trim().to_string())
                .unwrap_or_default();
            if display_marker.is_empty() {
                lines.push(format!("> {text}"));
            } else {
                lines.push(format!(
                    "> **{display_marker}**. {}",
                    escape_leading_asterisks(&text)
                ));
            }
            lines.push(String::new());
            emitted_note_ids.insert(note_id.clone());
            emitted += 1;
            continue;
        }
        let number = local_ref_numbers.get(note_id).copied().unwrap_or(0);
        if number <= 0 {
            continue;
        }
        lines.push(format!("[^{number}]: {}", escape_leading_asterisks(&text)));
        lines.push(String::new());
        emitted_note_ids.insert(note_id.clone());
        emitted += 1;
    }
    emitted
}

/// 构建内联脚注附着目标和页回退目标。
///
/// ←→ Python `_build_inline_footnote_targets()` (export_footnote.py:107)
#[allow(clippy::type_complexity)]
pub fn build_inline_footnote_targets(
    chapter_id: &str,
    matched_links: &[NoteLinkRecord],
    note_items_by_id: &HashMap<String, NoteItemRecord>,
    body_anchors_by_id: &HashMap<String, BodyAnchorRecord>,
    note_text_by_id: &HashMap<String, String>,
) -> (HashMap<(i64, i64), Vec<String>>, HashMap<i64, Vec<String>>) {
    let mut chapter_links: Vec<&NoteLinkRecord> = matched_links
        .iter()
        .filter(|link| {
            link.chapter_id == chapter_id
                && link.note_kind == NoteKind::Footnote
                && link.status == LinkStatus::Matched
                && !link.note_item_id.trim().is_empty()
        })
        .collect();
    chapter_links.sort_by(|a, b| {
        let a_anchor = body_anchors_by_id.get(a.anchor_id.trim());
        let b_anchor = body_anchors_by_id.get(b.anchor_id.trim());
        let a_page = a_anchor.map(|a| a.page_no).unwrap_or(0);
        let b_page = b_anchor.map(|a| a.page_no).unwrap_or(0);
        let a_para = a_anchor.map(|a| a.paragraph_index).unwrap_or(0);
        let b_para = b_anchor.map(|a| a.paragraph_index).unwrap_or(0);
        let a_char = a_anchor.map(|a| a.char_start).unwrap_or(0);
        let b_char = b_anchor.map(|a| a.char_start).unwrap_or(0);
        a_page
            .cmp(&b_page)
            .then(a_para.cmp(&b_para))
            .then(a_char.cmp(&b_char))
            .then(a.link_id.cmp(&b.link_id))
    });

    let mut attached: HashMap<(i64, i64), Vec<String>> = HashMap::new();
    let mut page_fallback: HashMap<i64, Vec<String>> = HashMap::new();

    for link in &chapter_links {
        let note_item_id = link.note_item_id.trim().to_string();
        let note_id = resolve_note_id(&note_item_id, note_text_by_id);
        if note_id.is_empty() {
            continue;
        }
        if note_text_by_id
            .get(&note_id)
            .map(|t| t.trim().is_empty())
            .unwrap_or(true)
        {
            continue;
        }

        let note_item = note_items_by_id.get(&note_item_id);
        let anchor = body_anchors_by_id.get(link.anchor_id.trim());
        let note_page = if let Some(anch) = anchor {
            if anch.page_no > 0 {
                anch.page_no
            } else {
                note_item
                    .map(|i| i.page_no)
                    .unwrap_or(0)
                    .max(0)
                    .max(link.page_no_start.max(0))
            }
        } else if let Some(item) = note_item {
            item.page_no.max(0)
        } else {
            link.page_no_start.max(0)
        };

        if let Some(anch) = anchor {
            if !anch.synthetic && anch.page_no > 0 {
                attached
                    .entry((anch.page_no, anch.paragraph_index))
                    .or_default()
                    .push(note_id);
                continue;
            }
        }
        if note_page > 0 {
            page_fallback.entry(note_page).or_default().push(note_id);
        }
    }

    (attached, page_fallback)
}

/// 获取 note_id 的原始 marker。
///
/// ←→ Python `_note_marker()` (export_footnote.py:155)
pub fn note_marker(note_id: &str, note_items_by_id: &HashMap<String, NoteItemRecord>) -> String {
    note_items_by_id
        .get(note_id.trim())
        .map(|item| item.marker.trim().to_string())
        .unwrap_or_default()
}

/// 判断 note_id 是否为数字 marker。
///
/// ←→ Python `_is_numeric_note()` (export_footnote.py:160)
pub fn is_numeric_note(note_id: &str, note_items_by_id: &HashMap<String, NoteItemRecord>) -> bool {
    let marker = note_marker(note_id, note_items_by_id);
    !marker.is_empty() && marker.chars().all(|c| c.is_ascii_digit())
}

/// 将 note_id 列表分为数字和符号两类。
///
/// ←→ Python `_split_numeric_note_ids()` (export_footnote.py:164)
pub fn split_numeric_note_ids(
    note_ids: &[String],
    note_items_by_id: &HashMap<String, NoteItemRecord>,
) -> (Vec<String>, Vec<String>) {
    let mut numeric: Vec<String> = Vec::new();
    let mut symbolic: Vec<String> = Vec::new();
    for note_id in note_ids {
        if is_numeric_note(note_id, note_items_by_id) {
            numeric.push(note_id.clone());
        } else {
            symbolic.push(note_id.clone());
        }
    }
    (numeric, symbolic)
}

/// 发射符号脚注行 [footnote] marker text。
///
/// ←→ Python `_emit_symbol_footnotes()` (export_footnote.py:179)
pub fn emit_symbol_footnotes(
    note_ids: &[String],
    lines: &mut Vec<String>,
    emitted_note_ids: &mut HashSet<String>,
    note_text_by_id: &HashMap<String, String>,
    note_items_by_id: &HashMap<String, NoteItemRecord>,
) -> i64 {
    let mut emitted: i64 = 0;
    for note_id in note_ids {
        if emitted_note_ids.contains(note_id) {
            continue;
        }
        let text = note_text_by_id
            .get(note_id.as_str())
            .map(|t| t.trim().to_string())
            .unwrap_or_default();
        if text.is_empty() {
            continue;
        }
        let marker = note_marker(note_id, note_items_by_id);
        let display_marker = if marker.is_empty() {
            "*".to_string()
        } else if marker.starts_with('*') {
            format!("\\{marker}")
        } else {
            marker
        };
        lines.push(format!(
            "[footnote] {display_marker} {}",
            escape_leading_asterisks(&text)
        ));
        lines.push(String::new());
        emitted_note_ids.insert(note_id.clone());
        emitted += 1;
    }
    emitted
}

/// 构建内联脚注章节 markdown（footnote_primary 章用）。
///
/// ←→ Python `_build_inline_footnote_section_markdown()` (export_footnote.py:204)
#[allow(clippy::too_many_arguments)]
pub fn build_inline_footnote_section_markdown(
    chapter: &ChapterExportInput,
    section_heads: &[SectionHeadRecord],
    body_units: &[TranslationUnitRecord],
    note_units: &[TranslationUnitRecord],
    matched_links: &[NoteLinkRecord],
    note_items_by_id: &HashMap<String, NoteItemRecord>,
    body_anchors_by_id: &HashMap<String, BodyAnchorRecord>,
    include_diagnostic_entries: bool,
    _diagnostic_machine_by_page: &HashMap<i64, String>,
    skipped_note_ids: Option<&HashSet<String>>,
) -> (String, HashMap<String, i64>) {
    let chapter_id = chapter.chapter_id.trim();
    let chapter_title = format_chapter_title(&chapter.title, chapter_id);
    let chapter_pages_set: HashSet<i64> =
        chapter_page_numbers(&chapter.pages, chapter.start_page, chapter.end_page)
            .into_iter()
            .collect();
    let note_text_by_id = build_note_text_by_id_for_chapter(Some(chapter_id), note_units);
    let marker_note_sequences = build_raw_marker_note_sequences(
        chapter_id,
        matched_links,
        note_items_by_id,
        body_anchors_by_id,
        &note_text_by_id,
    );
    let section_heads_by_page =
        build_section_heads_by_page(chapter_id, section_heads, &chapter_pages_set);
    let (attached_note_ids, page_fallback_note_ids) = build_inline_footnote_targets(
        chapter_id,
        matched_links,
        note_items_by_id,
        body_anchors_by_id,
        &note_text_by_id,
    );

    // ── page_paragraphs ──
    let mut page_paragraphs: HashMap<i64, Vec<UnitParagraphRecord>> = HashMap::new();
    let mut sorted_units: Vec<&TranslationUnitRecord> = body_units
        .iter()
        .filter(|u| u.section_id == chapter_id)
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
        let mut segments: Vec<&UnitPageSegmentRecord> = unit
            .page_segments
            .iter()
            .filter(|s| s.page_no > 0)
            .collect();
        segments.sort_by_key(|a| a.page_no);
        for segment in segments {
            let page_no = segment.page_no;
            let visible = visible_segment_paragraphs(segment);
            if !visible.is_empty() {
                page_paragraphs
                    .entry(page_no)
                    .or_default()
                    .extend(visible.into_iter().cloned());
                continue;
            }
            let fallback_text = if !segment.display_text.trim().is_empty() {
                segment.display_text.trim().to_string()
            } else {
                segment.source_text.trim().to_string()
            };
            if fallback_text.is_empty() {
                continue;
            }
            page_paragraphs
                .entry(page_no)
                .or_default()
                .push(UnitParagraphRecord {
                    kind: "body".to_string(),
                    display_text: fallback_text.clone(),
                    source_text: fallback_text,
                    ..Default::default()
                });
        }
    }

    let mut lines: Vec<String> = vec![format!("## {chapter_title}"), String::new()];
    let mut seen_section_heads: HashSet<(i64, String)> = HashSet::new();
    let mut local_ref_numbers: HashMap<String, i64> = HashMap::new();
    let mut ordered_note_ids: Vec<String> = Vec::new();
    let mut note_marker_by_id: HashMap<String, String> = HashMap::new();
    let mut inline_note_kind_by_id: HashMap<String, String> = HashMap::new();

    for (note_id, item) in note_items_by_id {
        if item.chapter_id != chapter_id {
            continue;
        }
        let marker = item.marker.trim().to_string();
        if !marker.is_empty() && marker.chars().all(|c| c.is_ascii_digit()) {
            note_marker_by_id.insert(note_id.clone(), marker);
        } else {
            inline_note_kind_by_id.insert(note_id.clone(), "footnote".to_string());
        }
    }

    let mut emitted_note_ids: HashSet<String> = HashSet::new();
    let mut chapter_has_body = false;
    let mut inline_attach_count: i64 = 0;
    let mut page_fallback_count: i64 = 0;

    let mut sorted_pages: Vec<i64> = page_paragraphs.keys().copied().collect();
    sorted_pages.sort();

    for page_no in sorted_pages {
        // page-level section heads
        if let Some(titles) = section_heads_by_page.get(&page_no) {
            for title in titles {
                let dedupe_key = (page_no, title.to_lowercase());
                if seen_section_heads.contains(&dedupe_key) {
                    continue;
                }
                seen_section_heads.insert(dedupe_key);
                lines.push(format!("### {title}"));
                lines.push(String::new());
            }
        }

        let mut body_paragraph_index: i64 = 0;
        let mut page_has_body = false;

        if let Some(paragraphs) = page_paragraphs.get(&page_no) {
            for paragraph in paragraphs {
                let kind = paragraph.kind.trim().to_lowercase();
                let text = paragraph_render_text(paragraph).to_string();
                if text.is_empty() {
                    body_paragraph_index += 1;
                    continue;
                }
                // skip paragraph that matches chapter title
                if normalized_paragraph_key(&text) == normalized_paragraph_key(&chapter_title) {
                    body_paragraph_index += 1;
                    continue;
                }
                if kind == "heading" {
                    let heading_title = WHITESPACE_RE.replace_all(&text, " ").trim().to_string();
                    if heading_title.is_empty()
                        || normalized_paragraph_key(&heading_title)
                            == normalized_paragraph_key(&chapter_title)
                    {
                        body_paragraph_index += 1;
                        continue;
                    }
                    let dedupe_key = (page_no, heading_title.to_lowercase());
                    if seen_section_heads.contains(&dedupe_key) {
                        body_paragraph_index += 1;
                        continue;
                    }
                    seen_section_heads.insert(dedupe_key);
                    lines.push(format!("### {heading_title}"));
                    lines.push(String::new());
                    body_paragraph_index += 1;
                    continue;
                }

                let body_text = rewrite_body_text_with_local_refs(
                    &text,
                    &note_text_by_id,
                    &inline_note_kind_by_id,
                    &marker_note_sequences,
                    &mut local_ref_numbers,
                    &mut ordered_note_ids,
                    None,
                    Some(&note_marker_by_id),
                );
                let body_text = if paragraph.translated_text.trim().is_empty()
                    && !include_diagnostic_entries
                    && note_text_by_id.is_empty()
                    && ANY_NOTE_REF_RE.is_match(&body_text)
                {
                    PENDING_TRANSLATION_TEXT.to_string()
                } else {
                    body_text.trim().to_string()
                };
                if body_text.is_empty() {
                    body_paragraph_index += 1;
                    continue;
                }
                lines.push(escape_leading_asterisks(&body_text));
                lines.push(String::new());
                chapter_has_body = true;
                page_has_body = true;

                // attached symbol footnotes at (page_no, body_paragraph_index)
                let attached_ids = attached_note_ids
                    .get(&(page_no, body_paragraph_index))
                    .cloned()
                    .unwrap_or_default();
                let (_numeric, symbol_note_ids) =
                    split_numeric_note_ids(&attached_ids, note_items_by_id);
                inline_attach_count += emit_symbol_footnotes(
                    &symbol_note_ids,
                    &mut lines,
                    &mut emitted_note_ids,
                    &note_text_by_id,
                    note_items_by_id,
                );
                body_paragraph_index += 1;
            }
        }

        // remaining note ids for this page
        let mut remaining_page_note_ids: Vec<String> = Vec::new();
        let mut attached_sorted: Vec<((i64, i64), &Vec<String>)> =
            attached_note_ids.iter().map(|(k, v)| (*k, v)).collect();
        attached_sorted.sort_by_key(|a| a.0);
        for ((target_page_no, target_para_idx), note_ids) in &attached_sorted {
            if *target_page_no != page_no {
                continue;
            }
            if *target_para_idx >= body_paragraph_index {
                remaining_page_note_ids.extend((*note_ids).clone());
            }
        }
        if let Some(fallback_ids) = page_fallback_note_ids.get(&page_no) {
            remaining_page_note_ids.extend(fallback_ids.clone());
        }
        if page_has_body {
            let (_numeric_remaining, symbol_remaining) =
                split_numeric_note_ids(&remaining_page_note_ids, note_items_by_id);
            page_fallback_count += emit_symbol_footnotes(
                &symbol_remaining,
                &mut lines,
                &mut emitted_note_ids,
                &note_text_by_id,
                note_items_by_id,
            );
        }
    }

    if !chapter_has_body {
        lines.push(PENDING_TRANSLATION_TEXT.to_string());
        lines.push(String::new());
    }

    let numeric_ordered_note_ids: Vec<String> = ordered_note_ids
        .iter()
        .filter(|nid| is_numeric_note(nid, note_items_by_id))
        .cloned()
        .collect();
    let chapter_end_count = emit_local_note_definitions(
        &numeric_ordered_note_ids,
        &mut lines,
        &mut emitted_note_ids,
        &local_ref_numbers,
        &note_text_by_id,
        skipped_note_ids,
        note_items_by_id,
    );

    let joined = lines.join("\n");
    let content = strip_trailing_image_only_block(joined.trim());
    let content = clean_export_html(&content);

    // contract_summary
    let refs: HashSet<String> = LOCAL_FOOTNOTE_REF_RE
        .captures_iter(&content)
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .collect();
    let defs: HashSet<String> = LOCAL_FOOTNOTE_DEF_RE
        .captures_iter(&content)
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .collect();
    let ref_count = refs.len() as i64;
    let def_count = defs.len() as i64;
    let missing = refs.difference(&defs).count() as i64;
    let orphan = defs.difference(&refs).count() as i64;

    let mut contract_summary = HashMap::new();
    contract_summary.insert("local_ref_count".to_string(), ref_count);
    contract_summary.insert("local_definition_count".to_string(), def_count);
    contract_summary.insert("missing_definition_count".to_string(), missing);
    contract_summary.insert("orphan_definition_count".to_string(), orphan);
    contract_summary.insert(
        "inline_footnote_paragraph_attach_count".to_string(),
        inline_attach_count,
    );
    contract_summary.insert(
        "inline_footnote_page_fallback_count".to_string(),
        page_fallback_count,
    );
    contract_summary.insert(
        "chapter_end_footnote_definition_count".to_string(),
        chapter_end_count,
    );

    (content, contract_summary)
}

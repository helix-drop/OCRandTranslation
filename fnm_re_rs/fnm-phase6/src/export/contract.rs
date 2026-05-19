//! ←→ FNM_RE/stages/export_contract.py
//! 翻译的函数：
//!   is_semantic_duplicate_candidate  ←→ _is_semantic_duplicate_candidate (export_contract.py:39)
//!   compute_export_semantic_contract ←→ _compute_export_semantic_contract (export_contract.py:53)
//!   build_export_chapters            ←→ build_export_chapters (export_contract.py:116)
//! local helper:
//!   looks_like_bibliography_entry    ←→ _looks_like_bibliography_entry (FNM_RE/shared/text.py:98)

use std::collections::{HashMap, HashSet};

use anyhow::Result;
use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::export_constants::{
    FRONT_MATTER_TITLE_RE, OBSIDIAN_EXPORT_CHAPTERS_PREFIX, TOC_RESIDUE_RE,
};
use fnm_core::records::{
    BodyAnchorRecord, ChapterRecord, ExportChapterRecord, NoteItemRecord, NoteLinkRecord,
    Phase5Structure, TranslationUnitRecord,
};
use fnm_core::types::LinkStatus;

use super::book_type::infer_book_note_type_from_modes;
use super::chapter_pages::chapter_page_numbers;
use super::diagnostic_text::diagnostic_machine_text_by_page;
use super::filename::build_chapter_filename;
use super::section_render::{build_section_markdown, ChapterExportInput, SectionMarkdownInput};

static DUPLICATE_CANDIDATE_PUNCT_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"[.!?;:。！？；：]").unwrap());
static BIB_YEAR_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\b\d{4}\.?\s*$").unwrap());
static BIB_COLON_YEAR_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r":\s*[^:]{6,},\s*\d{4}\.?\s*$").unwrap());
static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

/// 判断文本是否为语义重复候选段落。
///
/// ←→ Python `_is_semantic_duplicate_candidate()` (export_contract.py:39)
pub fn is_semantic_duplicate_candidate(text: &str) -> bool {
    let normalized = WHITESPACE_RE.replace_all(text.trim(), " ");
    let normalized = normalized.trim();
    if normalized.is_empty() {
        return false;
    }
    if normalized.starts_with('#') {
        return false;
    }
    if normalized.len() < 80 {
        return false;
    }
    let words: Vec<&str> = normalized.split(' ').filter(|w| !w.is_empty()).collect();
    if words.len() < 12 {
        return false;
    }
    DUPLICATE_CANDIDATE_PUNCT_RE.is_match(normalized)
}

/// 检测文本是否看起来像参考文献条目（结尾含年份）。
///
/// ←→ Python `_looks_like_bibliography_entry()` (FNM_RE/shared/text.py:98)
pub(crate) fn looks_like_bibliography_entry(text: &str) -> bool {
    let normalized = WHITESPACE_RE.replace_all(text.trim(), " ");
    let normalized = normalized.trim();
    if normalized.is_empty() {
        return false;
    }
    if !BIB_YEAR_RE.is_match(normalized) {
        return false;
    }
    BIB_COLON_YEAR_RE.is_match(normalized)
}

/// 计算导出语义合同检查结果。
///
/// ←→ Python `_compute_export_semantic_contract()` (export_contract.py:53)
pub fn compute_export_semantic_contract(
    chapters: &[ExportChapterRecord],
    chapter_files: &HashMap<String, String>,
) -> HashMap<String, bool> {
    let front_matter_leak_detected = chapters
        .iter()
        .any(|ch| FRONT_MATTER_TITLE_RE.is_match(ch.title.trim()));
    let toc_residue_detected = chapter_files
        .values()
        .any(|content| TOC_RESIDUE_RE.is_match(content));

    let mut mid_paragraph_heading_detected = false;
    for content in chapter_files.values() {
        let lines: Vec<&str> = content.lines().collect();
        for (idx, line) in lines.iter().enumerate() {
            let stripped = line.trim();
            if !stripped.starts_with("### ") {
                continue;
            }
            let prev = if idx > 0 { lines[idx - 1].trim() } else { "" };
            if !prev.is_empty() && !prev.starts_with('#') {
                mid_paragraph_heading_detected = true;
                break;
            }
        }
        if mid_paragraph_heading_detected {
            break;
        }
    }

    let mut duplicate_paragraph_detected = false;
    for content in chapter_files.values() {
        let mut seen: HashSet<String> = HashSet::new();
        for paragraph in content.split("\n\n") {
            if !is_semantic_duplicate_candidate(paragraph) {
                continue;
            }
            if looks_like_bibliography_entry(paragraph) {
                continue;
            }
            let key = super::paragraph_key::normalized_paragraph_key(paragraph);
            if key.len() < 60 {
                continue;
            }
            if seen.contains(&key) {
                duplicate_paragraph_detected = true;
                break;
            }
            seen.insert(key);
        }
        if duplicate_paragraph_detected {
            break;
        }
    }

    let export_semantic_contract_ok = !(front_matter_leak_detected
        || toc_residue_detected
        || mid_paragraph_heading_detected
        || duplicate_paragraph_detected);

    let mut result = HashMap::new();
    result.insert(
        "export_semantic_contract_ok".to_string(),
        export_semantic_contract_ok,
    );
    result.insert(
        "front_matter_leak_detected".to_string(),
        front_matter_leak_detected,
    );
    result.insert("toc_residue_detected".to_string(), toc_residue_detected);
    result.insert(
        "mid_paragraph_heading_detected".to_string(),
        mid_paragraph_heading_detected,
    );
    result.insert(
        "duplicate_paragraph_detected".to_string(),
        duplicate_paragraph_detected,
    );
    result
}

/// 构建导出章节记录 + summary。
///
/// ←→ Python `build_export_chapters()` (export_contract.py:116)
#[allow(clippy::too_many_arguments)]
pub fn build_export_chapters(
    phase5: &Phase5Structure,
    include_diagnostic_entries: bool,
    skipped_note_ids: Option<&HashSet<String>>,
) -> Result<(Vec<ExportChapterRecord>, serde_json::Value)> {
    // 1. 排序章节
    let mut chapters: Vec<&ChapterRecord> = phase5.chapters.iter().collect();
    chapters.sort_by(|a, b| {
        a.start_page
            .cmp(&b.start_page)
            .then(a.chapter_id.cmp(&b.chapter_id))
    });

    // 2. 分类 unit（cloned → SectionMarkdownInput 需要拥有型）
    let body_units: Vec<TranslationUnitRecord> = phase5
        .translation_units
        .iter()
        .filter(|u| u.kind == "body")
        .cloned()
        .collect();
    let note_units: Vec<TranslationUnitRecord> = phase5
        .translation_units
        .iter()
        .filter(|u| u.kind == "footnote" || u.kind == "endnote")
        .cloned()
        .collect();
    let matched_links: Vec<NoteLinkRecord> = phase5
        .effective_note_links
        .iter()
        .filter(|l| {
            l.status == LinkStatus::Matched
                && !l.note_item_id.trim().is_empty()
                && !l.anchor_id.trim().is_empty()
        })
        .cloned()
        .collect();

    // 3. HashMap 构建
    let note_items_by_id: HashMap<String, NoteItemRecord> = phase5
        .note_items
        .iter()
        .filter(|item| !item.note_item_id.trim().is_empty())
        .map(|item| (item.note_item_id.trim().to_string(), item.clone()))
        .collect();
    let body_anchors_by_id: HashMap<String, BodyAnchorRecord> = phase5
        .body_anchors
        .iter()
        .filter(|a| !a.anchor_id.trim().is_empty())
        .map(|a| (a.anchor_id.trim().to_string(), a.clone()))
        .collect();
    let diagnostic_machine_by_page = diagnostic_machine_text_by_page(&phase5.diagnostic_pages);
    let chapter_note_mode_by_id: HashMap<String, String> = phase5
        .chapter_note_modes
        .iter()
        .filter(|row| !row.chapter_id.trim().is_empty())
        .map(|row| {
            (
                row.chapter_id.trim().to_string(),
                row.note_mode.as_str().to_string(),
            )
        })
        .collect();

    // 4. book_type 推断
    let summary_book_type = phase5
        .summary
        .chapter_note_mode_summary
        .get("book_type")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let book_type = if matches!(
        summary_book_type.as_str(),
        "mixed" | "endnote_only" | "footnote_only" | "no_notes"
    ) {
        summary_book_type
    } else {
        infer_book_note_type_from_modes(&phase5.chapter_note_modes).to_string()
    };

    let mut used_filenames: HashSet<String> = HashSet::new();
    let mut chapter_records: Vec<ExportChapterRecord> = Vec::new();
    let mut contract_items: Vec<serde_json::Value> = Vec::new();
    let mut inline_footnote_paragraph_attach_count: i64 = 0;
    let mut inline_footnote_page_fallback_count: i64 = 0;
    let mut chapter_end_footnote_definition_count: i64 = 0;

    // 5. 逐章处理
    for (order, chapter) in chapters.iter().enumerate() {
        let order = order as i64 + 1;
        let chapter_id = chapter.chapter_id.trim().to_string();
        if chapter_id.is_empty() {
            continue;
        }
        let title = if chapter.title.trim().is_empty() {
            chapter_id.clone()
        } else {
            chapter.title.clone()
        };
        let chapter_input = ChapterExportInput {
            chapter_id: chapter_id.clone(),
            title: title.clone(),
            pages: chapter.pages.clone(),
            start_page: chapter.start_page,
            end_page: chapter.end_page,
        };
        let input = SectionMarkdownInput {
            chapter: &chapter_input,
            section_heads: &phase5.section_heads,
            body_units: &body_units,
            note_units: &note_units,
            matched_links: &matched_links,
            note_items_by_id: &note_items_by_id,
            body_anchors_by_id: &body_anchors_by_id,
            include_diagnostic_entries,
            diagnostic_machine_by_page: &diagnostic_machine_by_page,
            book_type: &book_type,
            chapter_note_mode: chapter_note_mode_by_id
                .get(&chapter_id)
                .map(|s| s.as_str())
                .unwrap_or("no_notes"),
            skipped_note_ids,
        };

        let result = build_section_markdown(&input)?;
        let contract_summary = result.contract_summary;

        inline_footnote_paragraph_attach_count += contract_summary
            .get("inline_footnote_paragraph_attach_count")
            .copied()
            .unwrap_or(0);
        inline_footnote_page_fallback_count += contract_summary
            .get("inline_footnote_page_fallback_count")
            .copied()
            .unwrap_or(0);
        chapter_end_footnote_definition_count += contract_summary
            .get("chapter_end_footnote_definition_count")
            .copied()
            .unwrap_or(0);

        let filename = build_chapter_filename(order, &title, &mut used_filenames);
        chapter_records.push(ExportChapterRecord {
            order,
            section_id: chapter_id.clone(),
            title: title.clone(),
            path: format!("{OBSIDIAN_EXPORT_CHAPTERS_PREFIX}{filename}"),
            content: result.content,
            start_page: chapter.start_page.max(0),
            end_page: chapter.end_page.max(chapter.start_page).max(0),
            pages: chapter_page_numbers(&chapter.pages, chapter.start_page, chapter.end_page),
        });

        let mut item = serde_json::Map::new();
        item.insert(
            "section_id".to_string(),
            serde_json::Value::String(chapter_id),
        );
        item.insert("title".to_string(), serde_json::Value::String(title));
        for (k, v) in &contract_summary {
            item.insert(k.clone(), serde_json::Value::Number((*v).into()));
        }
        contract_items.push(serde_json::Value::Object(item));
    }

    // 6. summary
    let ok_count = contract_items
        .iter()
        .filter(|item| {
            let missing = item
                .get("missing_definition_count")
                .and_then(|v| v.as_i64())
                .unwrap_or(-1);
            let orphan = item
                .get("orphan_definition_count")
                .and_then(|v| v.as_i64())
                .unwrap_or(-1);
            missing == 0 && orphan == 0
        })
        .count() as i64;

    let summary = serde_json::json!({
        "chapter_ref_contract_summary": {
            "chapter_count": contract_items.len(),
            "chapter_local_contract_ok_count": ok_count,
            "items": contract_items,
        },
        "inline_footnote_paragraph_attach_count": inline_footnote_paragraph_attach_count,
        "inline_footnote_page_fallback_count": inline_footnote_page_fallback_count,
        "chapter_end_footnote_definition_count": chapter_end_footnote_definition_count,
    });

    Ok((chapter_records, summary))
}

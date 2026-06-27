//! `fnm-phase5` — FNM_RE Phase 5: 章 markdown 合并。
//!
//! ←→ Python:
//! - `FNM_RE/modules/chapter_merge.py` (~827 行) → 本 crate
//!
//! 不依赖 fnm-phase6。章节 markdown 渲染移至 render/ 模块。

#![deny(unused_must_use)]

mod convert;
mod diagnostic_helpers;
mod diagnostics;
mod marker_rewrite;
mod phase5_shadow;
mod render;

use std::collections::{HashMap, HashSet};

use anyhow::Result;
use fnm_core::records::{ChapterMarkdownEntry, ChapterMarkdownSet, FrozenUnits, SectionHeadRecord};
use fnm_phase2::chapter_split::ChapterLayers;
use fnm_phase3::note_linking::NoteLinkTable;

/// 构建章 markdown 集合。
///
/// ←→ Python `build_chapter_markdown_set()` (chapter_merge.py:645)
pub fn build_chapter_markdown_set(
    frozen_units: &FrozenUnits,
    note_link_table: &NoteLinkTable,
    chapter_layers: &ChapterLayers,
    diagnostic_machine_by_page: Option<&HashMap<String, String>>,
    include_diagnostic_entries: bool,
    section_heads: Option<&[SectionHeadRecord]>,
) -> Result<ChapterMarkdownSet> {
    let phase5 = phase5_shadow::build_phase5_shadow(
        frozen_units,
        note_link_table,
        chapter_layers,
        diagnostic_machine_by_page,
        include_diagnostic_entries,
        section_heads,
    );

    // 收集无正文引用的注释
    let mut unlinked_note_ids: HashSet<String> = HashSet::new();
    for r in &frozen_units.ref_map {
        let nid = r.note_item_id.trim();
        if r.decision.trim() == "skipped" && !nid.is_empty() {
            unlinked_note_ids.insert(nid.to_string());
        }
    }
    let mut linked_note_ids: HashSet<String> = HashSet::new();
    for link in &note_link_table.effective_links {
        let nid = link.note_item_id.trim().to_string();
        if nid.is_empty() {
            continue;
        }
        linked_note_ids.insert(nid.clone());
        if link.status.as_str() == "orphan_note" || link.status.as_str() == "ignored" {
            unlinked_note_ids.insert(nid);
        } else if link.status.as_str() == "matched" {
            unlinked_note_ids.remove(&nid);
        }
    }
    for unit in &frozen_units.note_units {
        let nid = unit.note_id.trim().to_string();
        if !nid.is_empty() && !linked_note_ids.contains(&nid) {
            unlinked_note_ids.insert(nid);
        }
    }

    let skip_ids: Option<&HashSet<String>> = if unlinked_note_ids.is_empty() {
        None
    } else {
        Some(&unlinked_note_ids)
    };

    let (export_chapters, export_summary) =
        render::merge::build_export_chapters(&phase5, include_diagnostic_entries, skip_ids)?;

    let mut chapters: Vec<ChapterMarkdownEntry> = export_chapters
        .into_iter()
        .filter(|row| !row.section_id.trim().is_empty())
        .map(|row| {
            let start_page = row.start_page;
            let end_page = if row.end_page > 0 {
                row.end_page
            } else {
                start_page
            };
            let pages: Vec<i64> = row.pages.iter().filter(|&&p| p > 0).copied().collect();
            ChapterMarkdownEntry {
                order: row.order,
                chapter_id: row.section_id.clone(),
                title: row.title.clone(),
                path: row.path.clone(),
                markdown_text: row.content.clone(),
                start_page,
                end_page,
                pages,
            }
        })
        .collect();

    // 工单 #7：NOTES 块格式
    chapters = chapters
        .into_iter()
        .map(|row| {
            let md = marker_rewrite::apply_notes_block_format(&row.markdown_text);
            let start_page = row.start_page;
            let end_page = if row.end_page > 0 {
                row.end_page
            } else {
                start_page
            };
            let pages: Vec<i64> = row.pages.iter().filter(|&&p| p > 0).copied().collect();
            ChapterMarkdownEntry {
                order: row.order,
                chapter_id: row.chapter_id,
                title: row.title,
                path: row.path,
                markdown_text: md,
                start_page,
                end_page,
                pages,
            }
        })
        .collect();

    let expected_chapters: Vec<&fnm_core::records::ChapterRecord> = chapter_layers
        .chapters
        .iter()
        .filter(|row| !row.chapter_id.trim().is_empty())
        .collect();

    let chapter_contract_summary = export_summary
        .get("chapter_ref_contract_summary")
        .cloned()
        .unwrap_or(serde_json::Value::Null);

    let (chapter_issue_summary, chapter_issue_counts) =
        diagnostics::build_chapter_issue_diagnostics(&chapters, &chapter_contract_summary);

    let local_refs_closed = chapter_issue_counts
        .get("local_ref_contract_broken_chapter_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(0)
        == 0;
    let no_frozen_ref_leak = chapter_issue_counts
        .get("frozen_ref_leak_chapter_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(0)
        == 0;
    let no_raw_marker_leak_in_body = chapter_issue_counts
        .get("raw_marker_leak_chapter_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(0)
        == 0;

    let chapter_files_emitted = !chapters.is_empty()
        && chapters.len() == expected_chapters.len()
        && chapters.iter().all(|row| row.path.trim().ends_with(".md"));

    // 生成 merge reviews (结构化 blocker)
    let mut merge_reviews: Vec<fnm_core::records::StructureReviewRecord> = Vec::new();
    if !chapter_files_emitted {
        let expected_ids: Vec<&str> = expected_chapters
            .iter()
            .map(|c| c.chapter_id.as_str())
            .collect();
        let got_ids: Vec<&str> = chapters.iter().map(|c| c.chapter_id.as_str()).collect();
        merge_reviews.push(fnm_core::records::StructureReviewRecord {
            review_id: format!(
                "{}-merge_chapter_file_missing",
                expected_chapters
                    .first()
                    .map(|c| c.chapter_id.as_str())
                    .unwrap_or("__book__")
            ),
            review_type: "merge_chapter_file_missing".to_string(),
            chapter_id: String::new(),
            page_start: 0,
            page_end: 0,
            severity: "error".to_string(),
            payload: serde_json::json!({
                "message": format!("chapter count mismatch: expected {} ({}), got {} ({})",
                    expected_chapters.len(), expected_ids.join(", "),
                    chapters.len(), got_ids.join(", ")),
            }),
        });
    }
    for issue in &chapter_issue_summary {
        let ch_id = issue
            .get("chapter_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if issue
            .get("frozen_ref_leak")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
        {
            merge_reviews.push(fnm_core::records::StructureReviewRecord {
                review_id: format!("{ch_id}-merge_frozen_ref_leak"),
                review_type: "merge_frozen_ref_leak".to_string(),
                chapter_id: ch_id.to_string(),
                page_start: 0,
                page_end: 0,
                severity: "error".to_string(),
                payload: serde_json::json!({
                    "message": "frozen ref leak detected in chapter body",
                    "chapter_id": ch_id,
                }),
            });
        }
        if issue
            .get("raw_marker_leak")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
        {
            merge_reviews.push(fnm_core::records::StructureReviewRecord {
                review_id: format!("{ch_id}-merge_raw_marker_leak"),
                review_type: "merge_raw_marker_leak".to_string(),
                chapter_id: ch_id.to_string(),
                page_start: 0,
                page_end: 0,
                severity: "error".to_string(),
                payload: serde_json::json!({
                    "message": "raw note marker leak detected in chapter body",
                    "chapter_id": ch_id,
                }),
            });
        }
        if !issue
            .get("local_refs_closed")
            .and_then(|v| v.as_bool())
            .unwrap_or(true)
        {
            merge_reviews.push(fnm_core::records::StructureReviewRecord {
                review_id: format!("{ch_id}-merge_local_refs_unclosed"),
                review_type: "merge_local_refs_unclosed".to_string(),
                chapter_id: ch_id.to_string(),
                page_start: 0,
                page_end: 0,
                severity: "error".to_string(),
                payload: serde_json::json!({
                    "message": "local ref contract broken: missing/orphan definitions",
                    "missing_definition_count": issue.get("missing_definition_count"),
                    "orphan_definition_count": issue.get("orphan_definition_count"),
                }),
            });
        }
    }

    let image_tail_warn = chapters.is_empty()
        || chapters.iter().all(|row| {
            !fnm_core::export_constants::TRAILING_IMAGE_ONLY_BLOCK_RE.is_match(&row.markdown_text)
        });

    let section_heading_warn = chapters.is_empty()
        || chapters.iter().all(|row| {
            let body = diagnostic_helpers::split_body_and_definitions(&row.markdown_text).0;
            !diagnostic_helpers::detect_mid_paragraph_heading(&body)
        });

    let merge_summary = serde_json::json!({
        "chapter_count": chapters.len() as i64,
        "expected_chapter_count": expected_chapters.len() as i64,
        "include_diagnostic_entries": include_diagnostic_entries,
        "local_refs_closed": local_refs_closed,
        "no_frozen_ref_leak": no_frozen_ref_leak,
        "no_raw_marker_leak_in_body": no_raw_marker_leak_in_body,
        "image_tail_warn": image_tail_warn,
        "section_heading_warn": section_heading_warn,
        "chapter_issue_count": chapter_issue_counts.get("chapter_issue_count").and_then(|v| v.as_i64()).unwrap_or(0),
        "frozen_ref_leak_chapter_count": chapter_issue_counts.get("frozen_ref_leak_chapter_count").and_then(|v| v.as_i64()).unwrap_or(0),
        "raw_marker_leak_chapter_count": chapter_issue_counts.get("raw_marker_leak_chapter_count").and_then(|v| v.as_i64()).unwrap_or(0),
        "local_ref_contract_broken_chapter_count": chapter_issue_counts.get("local_ref_contract_broken_chapter_count").and_then(|v| v.as_i64()).unwrap_or(0),
        "inline_footnote_paragraph_attach_count": export_summary.get("inline_footnote_paragraph_attach_count").and_then(|v| v.as_i64()).unwrap_or(0),
        "inline_footnote_page_fallback_count": export_summary.get("inline_footnote_page_fallback_count").and_then(|v| v.as_i64()).unwrap_or(0),
        "chapter_end_footnote_definition_count": export_summary.get("chapter_end_footnote_definition_count").and_then(|v| v.as_i64()).unwrap_or(0),
    });

    Ok(ChapterMarkdownSet {
        chapters,
        chapter_contract_summary,
        merge_summary,
        diagnostic_pages: phase5.diagnostic_pages,
        diagnostic_notes: phase5.diagnostic_notes,
        merge_reviews,
        note_items: chapter_layers.note_items.clone(),
    })
}

//! `fnm-phase5` — FNM_RE Phase 5: 章 markdown 合并。
//!
//! ←→ Python:
//! - `FNM_RE/modules/chapter_merge.py` (~827 行) → 本 crate
//! - `FNM_RE/stages/export_contract.py` (via orchestrator)
//! - `FNM_RE/stages/export_footnote.py` (via orchestrator)

#![deny(unused_must_use)]

pub mod convert;
mod diagnostics;
pub mod marker_rewrite;
pub mod phase5_shadow;

use std::collections::HashSet;

use anyhow::Result;
use fnm_core::export_constants::TRAILING_IMAGE_ONLY_BLOCK_RE;
use fnm_core::records::{
    ChapterMarkdownEntry, ChapterMarkdownSet, ChapterRecord, ExportChapterRecord, FrozenUnits,
};
use fnm_phase2::chapter_split::ChapterLayers;
use fnm_phase3::note_linking::NoteLinkTable;
use once_cell::sync::Lazy;
use regex::Regex;

static LOCAL_DEF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\[(\d+)\]|^\^\[(\d+)\]|^\^?\[\d+\]\s*:").unwrap());

pub(crate) fn split_body_and_definitions(content: &str) -> (String, String) {
    let mut body_lines: Vec<String> = Vec::new();
    let mut definition_lines: Vec<String> = Vec::new();
    let mut in_definition_block = false;

    for raw_line in content.lines() {
        if LOCAL_DEF_RE.is_match(raw_line) {
            in_definition_block = true;
            definition_lines.push(raw_line.to_string());
            continue;
        }
        if in_definition_block && (raw_line.starts_with("    ") || raw_line.starts_with('\t')) {
            definition_lines.push(raw_line.to_string());
            continue;
        }
        in_definition_block = false;
        body_lines.push(raw_line.to_string());
    }

    (body_lines.join("\n"), definition_lines.join("\n"))
}

fn detect_mid_paragraph_heading(body_text: &str) -> bool {
    let lines: Vec<&str> = body_text.lines().collect();
    for (idx, line) in lines.iter().enumerate() {
        let stripped = line.trim();
        if !stripped.starts_with("### ") {
            continue;
        }
        let prev = if idx > 0 { lines[idx - 1].trim() } else { "" };
        if !prev.is_empty() && !prev.starts_with('#') {
            return true;
        }
    }
    false
}

/// 计算未链接的 note ID，供调用方控制跳过列表。
///
/// ←→ Python `build_chapter_markdown_set` 中的 unlinked_note_ids 计算。
pub fn compute_unlinked_note_ids(
    frozen_units: &FrozenUnits,
    note_link_table: &NoteLinkTable,
) -> HashSet<String> {
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
    unlinked_note_ids
}

/// 从 Phase5 影子结构和导出章节记录组装最终 ChapterMarkdownSet。
///
/// 调用方先构建 Phase5Structure + 调用 `build_export_chapters`，再通过此函数
/// 完成 marker_rewrite + notes_block_format + diagnostics。
///
/// ←→ Python `build_chapter_markdown_set()` (chapter_merge.py:645)
pub fn assemble_chapter_markdown_set(
    phase5_structure: &fnm_core::records::Phase5Structure,
    export_chapters: &[ExportChapterRecord],
    export_summary: &serde_json::Value,
    frozen_units: &FrozenUnits,
    chapter_layers: &ChapterLayers,
) -> Result<ChapterMarkdownSet> {
    let mut chapters: Vec<ChapterMarkdownEntry> = export_chapters
        .iter()
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

    // 重写章节以供合稿
    chapters = marker_rewrite::rewrite_chapters_for_merge(&chapters, frozen_units, chapter_layers);

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

    let expected_chapters: Vec<&ChapterRecord> = chapter_layers
        .chapters
        .iter()
        .filter(|row| !row.chapter_id.trim().is_empty())
        .collect();

    let chapter_contract_summary = export_summary
        .get("chapter_ref_contract_summary")
        .cloned()
        .unwrap_or(serde_json::Value::Null);

    let (_chapter_issue_summary, chapter_issue_counts) =
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

    let _chapter_files_emitted = !chapters.is_empty()
        && chapters.len() == expected_chapters.len()
        && chapters.iter().all(|row| row.path.trim().ends_with(".md"));

    let image_tail_warn = chapters.is_empty()
        || chapters
            .iter()
            .all(|row| !TRAILING_IMAGE_ONLY_BLOCK_RE.is_match(&row.markdown_text));

    let section_heading_warn = chapters.is_empty()
        || chapters.iter().all(|row| {
            let body = split_body_and_definitions(&row.markdown_text).0;
            !detect_mid_paragraph_heading(&body)
        });

    let merge_summary = serde_json::json!({
        "chapter_count": chapters.len() as i64,
        "expected_chapter_count": expected_chapters.len() as i64,
        "include_diagnostic_entries": false,
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
        diagnostic_pages: phase5_structure.diagnostic_pages.clone(),
        diagnostic_notes: phase5_structure.diagnostic_notes.clone(),
    })
}

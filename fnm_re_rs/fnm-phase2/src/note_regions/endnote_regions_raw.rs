//! ←→ note_regions.py: _build_endnote_regions_raw（核心算法）。
//! 从 endnote 候选页构建原始 endnote region（连续块）。

use fnm_core::note_marker::first_notes_heading;
use fnm_core::records::{ChapterRecord, NoteRegionRecord};
use fnm_core::types::{NoteKind, RegionScope, RegionSource};
use fnm_phase1::input::RawPage;
use std::collections::{HashMap, HashSet};

use crate::note_regions::endnote_candidate::{
    endnote_scope_for_page, is_endnote_candidate_page, start_reason_for_page,
};

fn first_endnote_marker(page: &RawPage) -> String {
    page.note_scan
        .as_ref()
        .and_then(|ns| ns.get("items"))
        .and_then(|v| v.as_array())
        .and_then(|items| {
            items
                .iter()
                .find(|item| item.get("kind").and_then(|v| v.as_str()) == Some("endnote"))
                .and_then(|item| {
                    item.get("marker")
                        .and_then(|v| v.as_str().map(String::from))
                })
        })
        .unwrap_or_default()
}

fn has_endnote_signal(page: &RawPage) -> bool {
    if !first_notes_heading(&page.markdown).is_empty() {
        return true;
    }
    if has_endnote_scan_items(page) {
        return true;
    }
    page.note_scan
        .as_ref()
        .and_then(|ns| ns.get("page_kind"))
        .and_then(|v| v.as_str())
        .map(|k| k == "endnote_collection")
        .unwrap_or(false)
}

fn has_endnote_scan_items(page: &RawPage) -> bool {
    page.note_scan
        .as_ref()
        .and_then(|ns| ns.get("items"))
        .and_then(|v| v.as_array())
        .map(|items| {
            items
                .iter()
                .any(|item| item.get("kind").and_then(|v| v.as_str()) == Some("endnote"))
        })
        .unwrap_or(false)
}

fn has_reclassified_endnotes(page: &RawPage) -> bool {
    page.note_scan
        .as_ref()
        .and_then(|ns| ns.get("has_reclassified_endnotes"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

#[allow(clippy::too_many_arguments)]
fn build_region_record(
    region_counter: &mut usize,
    pages: &[i64],
    chapter_id: &str,
    scope: &str,
    heading_text: &str,
    start_reason: &str,
    end_reason: &str,
    page_by_no: &HashMap<i64, &RawPage>,
) -> NoteRegionRecord {
    let start_page = *pages.first().unwrap_or(&0);
    let end_page = *pages.last().unwrap_or(&0);
    *region_counter += 1;

    let first_source_marker = page_by_no
        .get(&start_page)
        .map(|p| first_endnote_marker(p))
        .unwrap_or_default();

    NoteRegionRecord {
        region_id: format!("region-endnote-{:04}", region_counter),
        chapter_id: chapter_id.to_string(),
        page_start: start_page,
        page_end: end_page,
        pages: pages.to_vec(),
        note_kind: NoteKind::Endnote,
        scope: if scope == "book" {
            RegionScope::Book
        } else {
            RegionScope::Chapter
        },
        source: RegionSource::HeadingScan,
        heading_text: heading_text.to_string(),
        start_reason: start_reason.to_string(),
        end_reason: end_reason.to_string(),
        region_marker_alignment_ok: true,
        region_start_first_source_marker: first_source_marker,
        region_first_note_item_marker: String::new(),
        review_required: heading_text.is_empty(),
    }
}

/// 计算 body chapters 的 last_chapter_end_page 和 first_body_page。
/// ←→ Python `_build_endnote_regions_raw` 开头的间隙检测逻辑
fn compute_body_bounds(chapters: &[ChapterRecord]) -> (i64, i64) {
    if chapters.is_empty() {
        return (0, 0);
    }
    let mut sorted: Vec<&ChapterRecord> = chapters.iter().collect();
    sorted.sort_by_key(|ch| ch.end_page);

    let end_pages: Vec<i64> = sorted
        .iter()
        .map(|ch| ch.end_page)
        .filter(|&p| p > 0)
        .collect();
    let cut_idx = if end_pages.len() >= 3 {
        let gaps: Vec<(i64, usize)> = end_pages
            .windows(2)
            .enumerate()
            .map(|(i, w)| (w[1] - w[0], i))
            .collect();
        let (max_gap, gap_idx) = gaps
            .iter()
            .max_by_key(|(gap, _)| *gap)
            .copied()
            .unwrap_or((0, 0));
        if max_gap > 30 {
            gap_idx + 1
        } else {
            end_pages.len()
        }
    } else {
        end_pages.len()
    };

    let body_chapters = &sorted[..cut_idx.min(sorted.len())];
    let last_end = body_chapters
        .iter()
        .map(|ch| ch.end_page)
        .max()
        .unwrap_or(0);
    let first_start = body_chapters
        .iter()
        .map(|ch| ch.start_page)
        .filter(|&p| p > 0)
        .min()
        .unwrap_or(0);
    (last_end, first_start)
}

/// 构建原始 endnote regions（核心算法）。
/// ←→ Python `_build_endnote_regions_raw`
pub fn build_endnote_regions_raw(
    chapters: &[ChapterRecord],
    page_role_by_no: &HashMap<i64, String>,
    page_by_no: &HashMap<i64, &RawPage>,
    chapters_with_footnote_band: &HashSet<String>,
    sorted_page_nos: &[i64],
) -> Vec<NoteRegionRecord> {
    if sorted_page_nos.is_empty() {
        return vec![];
    }

    let (last_chapter_end_page, first_body_page) = compute_body_bounds(chapters);

    let mut regions: Vec<NoteRegionRecord> = Vec::new();
    let mut current_pages: Vec<i64> = Vec::new();
    let mut current_scope = String::new();
    let mut current_chapter_id = String::new();
    let mut current_heading = String::new();
    let mut current_start_reason = String::new();
    let mut region_counter: usize = 0;

    let flush_region = |region_counter: &mut usize,
                        current_pages: &mut Vec<i64>,
                        current_scope: &mut String,
                        current_chapter_id: &mut String,
                        current_heading: &mut String,
                        current_start_reason: &mut String,
                        end_reason: &str,
                        page_by_no: &HashMap<i64, &RawPage>|
     -> Option<NoteRegionRecord> {
        if current_pages.is_empty() {
            return None;
        }
        let r = build_region_record(
            region_counter,
            current_pages,
            current_chapter_id,
            current_scope,
            current_heading,
            current_start_reason,
            end_reason,
            page_by_no,
        );
        current_pages.clear();
        current_scope.clear();
        current_chapter_id.clear();
        current_heading.clear();
        current_start_reason.clear();
        Some(r)
    };

    for &page_no in sorted_page_nos {
        if !is_endnote_candidate_page(page_no, page_role_by_no, page_by_no, first_body_page) {
            if let Some(r) = flush_region(
                &mut region_counter,
                &mut current_pages,
                &mut current_scope,
                &mut current_chapter_id,
                &mut current_heading,
                &mut current_start_reason,
                "contiguous_break",
                page_by_no,
            ) {
                regions.push(r);
            }
            continue;
        }

        // fnBlocks guard
        let page = page_by_no.get(&page_no);
        if let Some(p) = page {
            if let Some(fnb) = p.fn_blocks.as_array() {
                if !fnb.is_empty() {
                    let signal = has_endnote_signal(p) || has_reclassified_endnotes(p);
                    if !signal {
                        if let Some(r) = flush_region(
                            &mut region_counter,
                            &mut current_pages,
                            &mut current_scope,
                            &mut current_chapter_id,
                            &mut current_heading,
                            &mut current_start_reason,
                            "contiguous_break",
                            page_by_no,
                        ) {
                            regions.push(r);
                        }
                        continue;
                    }
                }
            }
        }

        let (scope, chapter_id) = endnote_scope_for_page(page_no, chapters, last_chapter_end_page);

        // footnote_band guard: chapter-scope candidates in footnote_band chapters without reclass guard
        if scope == "chapter" && chapters_with_footnote_band.contains(&chapter_id) {
            let page_role = page_role_by_no
                .get(&page_no)
                .map(|s| s.as_str())
                .unwrap_or("");
            let heading = page.and_then(|p| {
                let h = first_notes_heading(&p.markdown);
                if h.is_empty() {
                    None
                } else {
                    Some(h)
                }
            });
            let reclass_guard = page.map(|p| has_reclassified_endnotes(p)).unwrap_or(false);
            if page_role != "note" && heading.is_none() && !reclass_guard {
                if let Some(r) = flush_region(
                    &mut region_counter,
                    &mut current_pages,
                    &mut current_scope,
                    &mut current_chapter_id,
                    &mut current_heading,
                    &mut current_start_reason,
                    "contiguous_break",
                    page_by_no,
                ) {
                    regions.push(r);
                }
                continue;
            }
        }

        let heading_text = page
            .and_then(|p| {
                let h = first_notes_heading(&p.markdown);
                if h.is_empty() {
                    None
                } else {
                    Some(h)
                }
            })
            .unwrap_or_default();
        let start_reason = start_reason_for_page(page_no, page_role_by_no, page_by_no);

        if current_pages.is_empty() {
            current_pages.push(page_no);
            current_scope = scope;
            current_chapter_id = chapter_id;
            current_heading = heading_text;
            current_start_reason = start_reason;
            continue;
        }

        let expected_next = *current_pages.last().unwrap() + 1;
        let same_group = page_no == expected_next
            && scope == current_scope
            && (scope == "book" || chapter_id == current_chapter_id);

        if same_group {
            current_pages.push(page_no);
            if current_heading.is_empty() && !heading_text.is_empty() {
                current_heading = heading_text;
            }
            continue;
        }

        if let Some(r) = flush_region(
            &mut region_counter,
            &mut current_pages,
            &mut current_scope,
            &mut current_chapter_id,
            &mut current_heading,
            &mut current_start_reason,
            "contiguous_break",
            page_by_no,
        ) {
            regions.push(r);
        }

        current_pages.push(page_no);
        current_scope = scope;
        current_chapter_id = chapter_id;
        current_heading = heading_text;
        current_start_reason = start_reason;
    }

    // Flush last
    if let Some(r) = flush_region(
        &mut region_counter,
        &mut current_pages,
        &mut current_scope,
        &mut current_chapter_id,
        &mut current_heading,
        &mut current_start_reason,
        "document_end",
        page_by_no,
    ) {
        regions.push(r);
    }

    regions
}

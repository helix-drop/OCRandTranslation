//! ←→ Python `note_linking.py:build_note_links_for_chapter`

use fnm_core::records::{BodyAnchorRecord, NoteLinkRecord};
use fnm_phase1::input::RawPage;
use fnm_phase2::chapter_split::ChapterLayers;
use std::collections::HashMap;

/// 从完整 Phase2Structure 筛单章 → build_body_anchors → build_note_links。
///
/// ←→ Python `build_note_links_for_chapter`
pub fn build_note_links_for_chapter(
    chapter_layers: &ChapterLayers,
    chapter_id: &str,
    pages: Option<&[RawPage]>,
) -> (Vec<BodyAnchorRecord>, Vec<NoteLinkRecord>) {
    // 按 Python 行为：复用 phase2 已有 ChapterRecord，不重建。
    let ch_records: Vec<fnm_core::records::ChapterRecord> = chapter_layers
        .chapters
        .iter()
        .filter(|c| c.chapter_id == chapter_id)
        .cloned()
        .collect();

    if ch_records.is_empty() {
        return (Vec::new(), Vec::new());
    }

    let start_p = ch_records[0].start_page;
    let end_p = ch_records[0].end_page;

    let ch_pp: Vec<RawPage> = pages
        .map(|ps| {
            ps.iter()
                .filter(|p| {
                    let book_page = p.book_page;
                    start_p > 0 && end_p >= start_p && book_page >= start_p && book_page <= end_p
                })
                .cloned()
                .collect()
        })
        .unwrap_or_default();

    let ch_page_records: Vec<fnm_core::records::PagePartitionRecord> = ch_pp
        .iter()
        .map(|p| fnm_core::records::PagePartitionRecord {
            page_no: p.book_page,
            target_pdf_page: p.book_page,
            page_role: fnm_core::types::PageRole::Body,
            confidence: 1.0,
            reason: "per_chapter".to_string(),
            section_hint: String::new(),
            has_note_heading: false,
            note_scan_summary: serde_json::Value::Null,
        })
        .collect();

    let ch_items: Vec<_> = chapter_layers
        .note_items
        .iter()
        .filter(|ni| {
            let ni_chapter = ni.chapter_id.trim();
            ni_chapter == chapter_id || ni_chapter.is_empty()
        })
        .cloned()
        .collect();

    let ch_regions: Vec<_> = chapter_layers
        .regions
        .iter()
        .filter(|nr| {
            let nr_chapter = nr.chapter_id.trim();
            nr_chapter == chapter_id || nr_chapter.is_empty() || nr.scope.as_str() == "book"
        })
        .cloned()
        .collect();

    let (anchors, _anchor_summary) = crate::body_anchors::build_body_anchors(
        &ch_records,
        &ch_page_records,
        &ch_regions,
        &ch_items,
        &ch_pp,
    );

    let ch_modes: Vec<fnm_core::records::ChapterNoteModeRecord> = chapter_layers
        .chapter_note_modes
        .iter()
        .filter(|m| m.chapter_id == chapter_id)
        .cloned()
        .collect();

    let mut anchors_mut = anchors.clone();
    let (links, _link_summary) = crate::note_links::build_note_links(
        &mut anchors_mut,
        &ch_items,
        &ch_pp,
        1,
        &ch_modes,
        &[],
        &HashMap::new(),
    );

    (anchors_mut, links)
}

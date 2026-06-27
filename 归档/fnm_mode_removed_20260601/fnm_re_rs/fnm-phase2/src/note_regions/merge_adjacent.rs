//! ←→ note_regions.py: _merge_adjacent_endnote_regions
//! 合并相邻的 endnote region（同 scope 且连续或重叠）。

use fnm_core::records::NoteRegionRecord;
use fnm_core::types::{NoteKind, RegionScope, RegionSource};

/// 合并相邻的 endnote region（同 scope 且连续或重叠）。
/// ←→ Python `_merge_adjacent_endnote_regions`
pub fn merge_adjacent_endnote_regions(
    regions: Vec<NoteRegionRecord>,
) -> (Vec<NoteRegionRecord>, usize) {
    let mut ordered: Vec<NoteRegionRecord> = regions;
    ordered.sort_by_key(|r| (r.page_start, r.page_end, r.region_id.clone()));

    let mut merged: Vec<NoteRegionRecord> = Vec::new();
    let mut merge_count = 0usize;

    for region in ordered {
        if region.note_kind != NoteKind::Endnote {
            merged.push(region);
            continue;
        }

        if merged.is_empty() {
            merged.push(region);
            continue;
        }

        let previous = &merged[merged.len() - 1];
        let can_merge = previous.note_kind == NoteKind::Endnote
            && previous.scope == region.scope
            && previous.page_end + 1 >= region.page_start
            && (previous.scope == RegionScope::Book || previous.chapter_id == region.chapter_id);

        if !can_merge {
            merged.push(region);
            continue;
        }

        // Merge into previous
        let mut merged_pages: Vec<i64> = previous
            .pages
            .iter()
            .copied()
            .chain(region.pages.iter().copied())
            .collect();
        merged_pages.sort_unstable();
        merged_pages.dedup();

        let previous_idx = merged.len() - 1;
        merged[previous_idx] = NoteRegionRecord {
            page_start: merged_pages[0],
            page_end: *merged_pages.last().unwrap(),
            pages: merged_pages,
            source: RegionSource::ContinuationMerge,
            end_reason: region.end_reason.clone(),
            review_required: previous.review_required || region.review_required,
            ..merged[previous_idx].clone()
        };
        merge_count += 1;
    }

    (merged, merge_count)
}

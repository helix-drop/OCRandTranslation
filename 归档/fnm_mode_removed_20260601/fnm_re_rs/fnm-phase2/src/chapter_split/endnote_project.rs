//! Endnote 投影。←→ Python `_project_endnotes_by_marker()` / `_fallback_assign_unowned_endnotes()`。
//!
//! 由于 fnm-core 的 NoteItemRecord 不含 owner_chapter_id 等字段，
//! 此模块计算投影结果为 HashMap，由调用方决定如何应用。

use fnm_core::records::{ChapterRecord, NoteItemRecord, NoteRegionRecord};
use fnm_core::types::{NoteKind, RegionScope, RegionSource};

/// 计算 endnote 投影结果。
/// 返回 (item_index → new_chapter_id) 映射。
pub fn compute_endnote_projections(
    note_items: &[NoteItemRecord],
    note_regions: &[NoteRegionRecord],
    chapter_marker_sets: &std::collections::HashMap<String, std::collections::HashSet<String>>,
    chapter_order: &[String],
    book_type: &str,
) -> std::collections::HashMap<usize, String> {
    let mut result = std::collections::HashMap::new();

    let mut marker_to_chapters: std::collections::HashMap<String, Vec<String>> =
        std::collections::HashMap::new();
    for chapter_id in chapter_order {
        if let Some(markers) = chapter_marker_sets.get(chapter_id) {
            for marker in markers {
                marker_to_chapters
                    .entry(marker.clone())
                    .or_default()
                    .push(chapter_id.clone());
            }
        }
    }

    let chapter_rank: std::collections::HashMap<String, usize> = chapter_order
        .iter()
        .enumerate()
        .map(|(i, id)| (id.clone(), i))
        .collect();

    let region_by_id: std::collections::HashMap<&str, &NoteRegionRecord> = note_regions
        .iter()
        .map(|r| (r.region_id.as_str(), r))
        .collect();

    for (idx, item) in note_items.iter().enumerate() {
        if item.note_kind != NoteKind::Endnote {
            continue;
        }
        let region = match region_by_id.get(item.region_id.as_str()) {
            Some(r) => r,
            None => continue,
        };
        let allow_projection = matches!(region.scope, RegionScope::Book)
            || (book_type == "endnote_only"
                && matches!(
                    region.source,
                    RegionSource::ManualRebind
                        | RegionSource::HeadingScan
                        | RegionSource::ContinuationMerge
                ));
        if !allow_projection {
            continue;
        }

        let marker = fnm_core::note_marker::normalize_note_marker(&item.marker);
        if marker.is_empty() {
            continue;
        }
        let candidates = match marker_to_chapters.get(&marker) {
            Some(c) => c,
            None => continue,
        };

        let current = if !item.chapter_id.is_empty() {
            &item.chapter_id
        } else {
            continue;
        };

        if !current.is_empty() && !candidates.contains(&current.to_string()) {
            continue;
        }

        let chosen = if candidates.len() == 1 {
            candidates[0].clone()
        } else if !current.is_empty() && candidates.contains(&current.to_string()) {
            continue;
        } else if !current.is_empty() && chapter_rank.contains_key(current) {
            let current_rank = chapter_rank[current];
            candidates
                .iter()
                .min_by_key(|id| {
                    (*chapter_rank.get(*id).unwrap_or(&1000000) as i64 - current_rank as i64)
                        .unsigned_abs()
                })
                .cloned()
                .unwrap_or_else(|| candidates[0].clone())
        } else {
            candidates[0].clone()
        };

        if *current != chosen {
            result.insert(idx, chosen);
        }
    }

    result
}

/// 计算无主 endnote 的兜底归属。
pub fn compute_fallback_assignments(
    chapters: &[ChapterRecord],
    note_items: &[NoteItemRecord],
) -> std::collections::HashMap<usize, String> {
    let mut result = std::collections::HashMap::new();

    let ordered: Vec<&ChapterRecord> = chapters
        .iter()
        .filter(|ch| !ch.chapter_id.is_empty())
        .collect();
    if ordered.is_empty() {
        return result;
    }

    for (idx, item) in note_items.iter().enumerate() {
        if item.note_kind != NoteKind::Endnote {
            continue;
        }
        if !item.chapter_id.is_empty() {
            continue;
        }
        let page_no = item.page_no;
        let owner = ordered
            .iter()
            .rev()
            .find(|ch| ch.start_page <= page_no)
            .map(|ch| ch.chapter_id.clone())
            .unwrap_or_else(|| ordered[0].chapter_id.clone());
        result.insert(idx, owner);
    }

    result
}

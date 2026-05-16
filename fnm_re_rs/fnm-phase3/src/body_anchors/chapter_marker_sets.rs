//! ←→ FNM_RE/stages/body_anchors.py:
//!   _build_chapter_marker_range / _build_chapter_note_items_set /
//!   _build_chapter_endnote_marker_set / _build_chapter_endnote_text_by_marker /
//!   _footnote_band_page_keys

use fnm_core::records::{NoteItemRecord, NoteRegionRecord};
use std::collections::{HashMap, HashSet};

/// 构建每章的 marker 数值范围 (min, max)。
pub fn build_chapter_marker_range(note_items: &[NoteItemRecord]) -> HashMap<String, (i64, i64)> {
    let mut chapter_markers: HashMap<String, Vec<i64>> = HashMap::new();
    for item in note_items {
        let chapter_id = item.chapter_id.trim();
        if chapter_id.is_empty() {
            continue;
        }
        let Ok(marker) = item.marker.parse::<i64>() else {
            continue;
        };
        if marker <= 0 {
            continue;
        }
        chapter_markers
            .entry(chapter_id.to_string())
            .or_default()
            .push(marker);
    }
    chapter_markers
        .into_iter()
        .filter_map(|(ch_id, markers)| {
            if markers.is_empty() {
                None
            } else {
                Some((
                    ch_id,
                    (
                        *markers.iter().min().unwrap(),
                        *markers.iter().max().unwrap(),
                    ),
                ))
            }
        })
        .collect()
}

/// 构建每章的 note item marker 数值集合。
pub fn build_chapter_note_items_set(
    note_items: &[NoteItemRecord],
) -> HashMap<String, HashSet<i64>> {
    let mut sets: HashMap<String, HashSet<i64>> = HashMap::new();
    for item in note_items {
        let chapter_id = item.chapter_id.trim();
        if chapter_id.is_empty() {
            continue;
        }
        let Ok(marker) = item.marker.parse::<i64>() else {
            continue;
        };
        if marker <= 0 {
            continue;
        }
        sets.entry(chapter_id.to_string())
            .or_default()
            .insert(marker);
    }
    sets
}

/// 构建每章的 endnote marker 数值集合。
pub fn build_chapter_endnote_marker_set(
    note_regions: &[NoteRegionRecord],
    note_items: &[NoteItemRecord],
) -> HashMap<String, HashSet<i64>> {
    let endnote_region_ids: HashSet<String> = note_regions
        .iter()
        .filter(|r| r.note_kind.as_str() == "endnote")
        .map(|r| r.region_id.trim().to_string())
        .filter(|id| !id.is_empty())
        .collect();

    let mut sets: HashMap<String, HashSet<i64>> = HashMap::new();
    for item in note_items {
        if !endnote_region_ids.contains(item.region_id.trim()) {
            continue;
        }
        let chapter_id = item.chapter_id.trim();
        if chapter_id.is_empty() {
            continue;
        }
        let Ok(marker) = item.marker.parse::<i64>() else {
            continue;
        };
        if marker <= 0 {
            continue;
        }
        sets.entry(chapter_id.to_string())
            .or_default()
            .insert(marker);
    }
    sets
}

/// 构建每章 endnote 文本 by marker。
pub fn build_chapter_endnote_text_by_marker(
    note_regions: &[NoteRegionRecord],
    note_items: &[NoteItemRecord],
) -> HashMap<String, HashMap<i64, String>> {
    let endnote_region_ids: HashSet<String> = note_regions
        .iter()
        .filter(|r| r.note_kind.as_str() == "endnote")
        .map(|r| r.region_id.trim().to_string())
        .filter(|id| !id.is_empty())
        .collect();

    let mut rows: HashMap<String, HashMap<i64, String>> = HashMap::new();
    for item in note_items {
        if !endnote_region_ids.contains(item.region_id.trim()) {
            continue;
        }
        let chapter_id = item.chapter_id.trim();
        let Ok(marker) = item.marker.parse::<i64>() else {
            continue;
        };
        if chapter_id.is_empty() {
            continue;
        }
        rows.entry(chapter_id.to_string())
            .or_default()
            .insert(marker, item.text.clone());
    }
    rows
}

/// 构建 footnote band 页键集合 (chapter_id, page_no)。
pub fn footnote_band_page_keys(note_regions: &[NoteRegionRecord]) -> HashSet<(String, i64)> {
    let mut keys: HashSet<(String, i64)> = HashSet::new();
    for region in note_regions {
        if region.note_kind.as_str() != "footnote" {
            continue;
        }
        let chapter_id = region.chapter_id.trim();
        if chapter_id.is_empty() {
            continue;
        }
        for &page_no in &region.pages {
            if page_no > 0 {
                keys.insert((chapter_id.to_string(), page_no));
            }
        }
    }
    keys
}

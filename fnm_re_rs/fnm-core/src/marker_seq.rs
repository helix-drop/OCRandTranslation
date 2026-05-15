//! ←→ FNM_RE/shared/marker_sequences.py
//! 原始 marker → note_id 序列构建工具。

use crate::records::{BodyAnchorRecord, NoteItemRecord, NoteLinkRecord};
use std::collections::HashMap;

/// 按 body anchor 的 page_no/paragraph_index/char_start 排序 link 并构建
/// marker → note_id 序列。与 Python `_build_raw_marker_note_sequences` 一致。
///
/// 注：此为简化版，完整版在 fnm-phase4 实现。
pub fn build_raw_marker_note_sequences(
    chapter_id: &str,
    matched_links: &[NoteLinkRecord],
    note_items_by_id: &HashMap<String, NoteItemRecord>,
    _body_anchors_by_id: &HashMap<String, BodyAnchorRecord>,
    _note_text_by_id: &HashMap<String, String>,
) -> HashMap<String, Vec<String>> {
    let chapter_links: Vec<&NoteLinkRecord> = matched_links
        .iter()
        .filter(|link| {
            link.status == crate::types::LinkStatus::Matched
                && link.chapter_id == chapter_id
                && !link.note_item_id.trim().is_empty()
                && !link.anchor_id.trim().is_empty()
        })
        .collect();

    let mut sequences: HashMap<String, Vec<String>> = HashMap::new();
    for link in &chapter_links {
        let note_item_id = link.note_item_id.trim();
        if note_item_id.is_empty() {
            continue;
        }
        // 简化版：直接用 marker 作 key
        if !link.marker.trim().is_empty() {
            sequences
                .entry(link.marker.clone())
                .or_default()
                .push(note_item_id.to_string());
        }
    }

    // 追加 chapter 内 note_items 的 marker
    for item in note_items_by_id.values() {
        if item.chapter_id != chapter_id {
            continue;
        }
        if !item.marker.trim().is_empty() {
            let entry = sequences.entry(item.marker.clone()).or_default();
            if !entry.contains(&item.note_item_id) {
                entry.push(item.note_item_id.clone());
            }
        }
    }

    sequences
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_input() {
        let result = build_raw_marker_note_sequences(
            "ch-1",
            &[],
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
        );
        assert!(result.is_empty());
    }
}

//! ←→ FNM_RE/shared/marker_sequences.py
//! 原始 marker → note_id 序列构建工具。

use crate::records::{BodyAnchorRecord, NoteItemRecord, NoteLinkRecord};
use crate::ref_rewriter::{marker_aliases, resolve_note_id};
use std::collections::HashMap;

/// 锚点排序键，对齐 Python `_anchor_sort_key`。
fn anchor_sort_key(
    anchor_id: &str,
    body_anchors_by_id: &HashMap<String, BodyAnchorRecord>,
) -> (i64, i64, i64) {
    body_anchors_by_id
        .get(anchor_id)
        .map(|a| (a.page_no, a.paragraph_index, a.char_start))
        .unwrap_or((0, 0, 0))
}

/// 收集 marker 的所有 alias 候选。←→ Python L54-62 的 6 源合成。
fn collect_marker_candidates(
    link: &NoteLinkRecord,
    note_item: Option<&NoteItemRecord>,
    anchor: Option<&BodyAnchorRecord>,
    note_id: &str,
) -> Vec<String> {
    let mut candidates: std::collections::HashSet<String> = std::collections::HashSet::new();
    candidates.extend(marker_aliases(note_id));
    candidates.extend(marker_aliases(&link.marker));
    if let Some(item) = note_item {
        candidates.extend(marker_aliases(&item.marker));
    }
    if let Some(a) = anchor {
        candidates.extend(marker_aliases(&a.normalized_marker));
        candidates.extend(marker_aliases(&a.source_marker));
        if !a.ocr_repaired_from_marker.is_empty() {
            candidates.extend(marker_aliases(&a.ocr_repaired_from_marker));
        }
    }
    candidates.into_iter().filter(|s| !s.is_empty()).collect()
}

pub fn build_raw_marker_note_sequences(
    chapter_id: &str,
    matched_links: &[NoteLinkRecord],
    note_items_by_id: &HashMap<String, NoteItemRecord>,
    body_anchors_by_id: &HashMap<String, BodyAnchorRecord>,
    note_text_by_id: &HashMap<String, String>,
) -> HashMap<String, Vec<String>> {
    // 收集 chapter links 并按锚点排序
    let mut chapter_links: Vec<&NoteLinkRecord> = matched_links
        .iter()
        .filter(|link| {
            link.status == crate::types::LinkStatus::Matched
                && link.chapter_id == chapter_id
                && !link.note_item_id.trim().is_empty()
                && !link.anchor_id.trim().is_empty()
        })
        .collect();
    chapter_links.sort_by(|a, b| {
        let ka = anchor_sort_key(&a.anchor_id, body_anchors_by_id);
        let kb = anchor_sort_key(&b.anchor_id, body_anchors_by_id);
        ka.cmp(&kb).then(a.link_id.cmp(&b.link_id))
    });

    let mut sequences: HashMap<String, Vec<String>> = HashMap::new();

    for link in &chapter_links {
        let note_item_id = link.note_item_id.trim();
        let note_id = resolve_note_id(note_item_id, note_text_by_id);
        if note_id.is_empty() {
            continue;
        }
        let anchor = body_anchors_by_id.get(&link.anchor_id);
        if anchor.is_some_and(|a| a.synthetic) {
            continue;
        }
        // 跳过 ocr_repaired_from_marker 锚点
        if anchor.is_some_and(|a| !a.ocr_repaired_from_marker.is_empty()) {
            continue;
        }
        let note_item = note_items_by_id.get(note_item_id);
        let candidates = collect_marker_candidates(link, note_item, anchor, &note_id);
        for marker in &candidates {
            sequences
                .entry(marker.clone())
                .or_default()
                .push(note_id.clone());
        }
    }

    // 追加 chapter 内 note_items（排序后）
    let mut chapter_items: Vec<&NoteItemRecord> = note_items_by_id
        .values()
        .filter(|item| item.chapter_id == chapter_id)
        .collect();
    chapter_items.sort_by_key(|item| (item.page_no, &item.note_item_id));

    for item in &chapter_items {
        let note_item_id = item.note_item_id.trim();
        let note_id = resolve_note_id(note_item_id, note_text_by_id);
        if note_id.is_empty() {
            continue;
        }
        let candidates: Vec<String> = {
            let mut s: std::collections::HashSet<String> = std::collections::HashSet::new();
            s.extend(marker_aliases(&note_id));
            s.extend(marker_aliases(&item.marker));
            s.into_iter().filter(|v| !v.is_empty()).collect()
        };
        for marker in &candidates {
            let entry = sequences.entry(marker.clone()).or_default();
            if !entry.contains(&note_id) {
                entry.push(note_id.clone());
            }
        }
    }

    // 单 note_id 章节 fallback（←→ Python L89-105）
    if !sequences.is_empty() {
        return sequences;
    }
    let fallback_note_ids: std::collections::HashSet<String> = note_items_by_id
        .values()
        .filter(|item| item.chapter_id == chapter_id)
        .filter_map(|item| {
            let id = resolve_note_id(item.note_item_id.trim(), note_text_by_id);
            if id.is_empty() {
                None
            } else {
                Some(id)
            }
        })
        .collect();
    if fallback_note_ids.len() != 1 {
        return sequences;
    }
    let fallback_id = fallback_note_ids.iter().next().unwrap();
    for item in note_items_by_id.values() {
        if item.chapter_id != chapter_id {
            continue;
        }
        for marker in marker_aliases(&item.marker)
            .into_iter()
            .filter(|s| !s.is_empty())
        {
            let entry = sequences.entry(marker).or_default();
            if !entry.contains(fallback_id) {
                entry.push(fallback_id.clone());
            }
        }
    }

    sequences
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::records::{BodyAnchorRecord, NoteLinkRecord};
    use crate::types::LinkStatus;

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

    #[test]
    fn skips_synthetic_anchor() {
        let link = NoteLinkRecord {
            link_id: "l1".into(),
            chapter_id: "ch-1".into(),
            note_item_id: "ni-1".into(),
            anchor_id: "a-1".into(),
            marker: "1".into(),
            status: LinkStatus::Matched,
            confidence: 0.9,
            ..Default::default()
        };
        let anchor = BodyAnchorRecord {
            anchor_id: "a-1".into(),
            synthetic: true,
            ..Default::default()
        };
        let mut anchors = HashMap::new();
        anchors.insert("a-1".into(), anchor);
        let result = build_raw_marker_note_sequences(
            "ch-1",
            &[link],
            &HashMap::new(),
            &anchors,
            &HashMap::new(),
        );
        assert!(result.is_empty());
    }

    #[test]
    fn alias_expansion() {
        let link = NoteLinkRecord {
            link_id: "l1".into(),
            chapter_id: "ch-1".into(),
            note_item_id: "ni-1".into(),
            anchor_id: "a-1".into(),
            marker: "01".into(),
            status: LinkStatus::Matched,
            confidence: 0.9,
            ..Default::default()
        };
        let anchor = BodyAnchorRecord {
            anchor_id: "a-1".into(),
            synthetic: false,
            ..Default::default()
        };
        let mut anchors = HashMap::new();
        anchors.insert("a-1".into(), anchor);
        let mut texts = HashMap::new();
        texts.insert("ni-1".into(), "note text".into());
        let result =
            build_raw_marker_note_sequences("ch-1", &[link], &HashMap::new(), &anchors, &texts);
        assert!(result.contains_key("01"));
        assert!(result.contains_key("1"));
    }

    #[test]
    fn anchor_sort_produces_stable_order() {
        let a1 = BodyAnchorRecord {
            anchor_id: "a-1".into(),
            page_no: 1,
            paragraph_index: 0,
            char_start: 0,
            synthetic: false,
            ..Default::default()
        };
        let a2 = BodyAnchorRecord {
            anchor_id: "a-2".into(),
            page_no: 2,
            paragraph_index: 0,
            char_start: 0,
            synthetic: false,
            ..Default::default()
        };
        let l1 = NoteLinkRecord {
            link_id: "l1".into(),
            chapter_id: "ch-1".into(),
            note_item_id: "ni-1".into(),
            anchor_id: "a-1".into(),
            marker: "1".into(),
            status: LinkStatus::Matched,
            confidence: 0.9,
            ..Default::default()
        };
        let l2 = NoteLinkRecord {
            link_id: "l2".into(),
            chapter_id: "ch-1".into(),
            note_item_id: "ni-2".into(),
            anchor_id: "a-2".into(),
            marker: "2".into(),
            status: LinkStatus::Matched,
            confidence: 0.9,
            ..Default::default()
        };
        let mut anchors = HashMap::new();
        anchors.insert("a-1".into(), a1);
        anchors.insert("a-2".into(), a2);
        let mut texts = HashMap::new();
        texts.insert("ni-1".into(), "t1".into());
        texts.insert("ni-2".into(), "t2".into());
        let result =
            build_raw_marker_note_sequences("ch-1", &[l2, l1], &HashMap::new(), &anchors, &texts);
        // 即使传入顺序为 l2, l1，排序后 l1(page_no=1) 应在 l2(page_no=2) 之前
        let seq1 = result.get("1").unwrap();
        assert_eq!(seq1[0], "ni-1");
    }
}

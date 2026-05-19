//! ←→ Python `note_linking.py:_repair_explicit_footnote_anchor_ocr_variants`
//!
//! # 子模块划分
//!
//! - [`loop1_orphan_rebind`]: Loop 1（orphan_anchor → 已匹配 synthetic 锚点重绑定）
//! - [`loop2_ambiguous_followup`]: Loop 2（ambiguous 跟进消歧）
//! - [`loop3_cross_chapter`]: Loop 3（跨章同页重绑定）
//!
//! 三 Loop 互相独立（计数器分离、状态变更不交叉），适合拆 3 文件。
//! 公共 helper `looks_like_single_digit_ocr_variant` + setup 留在 mod.rs。
//!
//! 翻译的函数：Loop 1 (行 782-843), Loop 2 (行 845-929), Loop 3 (行 931-967)

mod loop1_orphan_rebind;
mod loop2_ambiguous_followup;
mod loop3_cross_chapter;

use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{BodyAnchorRecord, NoteItemRecord, NoteLinkRecord};
use std::collections::HashMap;

/// 判断两个 marker 是否为单数字 OCR 变体。
///
/// ←→ Python `_looks_like_single_digit_ocr_variant`（行 192-202）
pub(super) fn looks_like_single_digit_ocr_variant(left_marker: &str, right_marker: &str) -> bool {
    let left = normalize_note_marker(left_marker);
    let right = normalize_note_marker(right_marker);
    if left.is_empty() || right.is_empty() || left == right {
        return false;
    }
    if left.len() == right.len() {
        return left
            .chars()
            .zip(right.chars())
            .filter(|(l, r)| l != r)
            .count()
            == 1;
    }
    let (shorter, longer) = if left.len() < right.len() {
        (left, right)
    } else {
        (right, left)
    };
    if longer.len() != shorter.len() + 1 {
        return false;
    }
    longer[1..] == shorter
}

/// 修复显式脚注锚点的 OCR 变体。
///
/// ←→ Python `_repair_explicit_footnote_anchor_ocr_variants`（行 758-975）
///
/// 返回 (repaired_anchors, repaired_links, summary)
/// summary 包含 Loop 1/2/3 各自的计数器。
pub fn repair_explicit_footnote_anchor_ocr_variants(
    anchors: &[BodyAnchorRecord],
    links: &[NoteLinkRecord],
    note_items: &[NoteItemRecord],
) -> (
    Vec<BodyAnchorRecord>,
    Vec<NoteLinkRecord>,
    HashMap<String, i64>,
) {
    let mut repaired_anchors: Vec<BodyAnchorRecord> = anchors.to_vec();
    let mut repaired_links: Vec<NoteLinkRecord> = links.to_vec();
    let anchor_index_by_id: HashMap<String, usize> = repaired_anchors
        .iter()
        .enumerate()
        .filter_map(|(idx, row)| {
            let id = row.anchor_id.trim();
            if id.is_empty() {
                None
            } else {
                Some((id.to_string(), idx))
            }
        })
        .collect();

    let note_item_by_id: HashMap<String, &NoteItemRecord> = note_items
        .iter()
        .filter_map(|row| {
            let id = row.note_item_id.trim();
            if id.is_empty() {
                None
            } else {
                Some((id.to_string(), row))
            }
        })
        .collect();

    let (rebound_match_count, ignored_orphan_count) = loop1_orphan_rebind::run(
        &mut repaired_anchors,
        &mut repaired_links,
        &anchor_index_by_id,
        &note_item_by_id,
    );

    let (ambiguous_followup_match_count, ambiguous_followup_rebind_count) =
        loop2_ambiguous_followup::run(&mut repaired_anchors, &mut repaired_links);

    let cross_chapter_same_page_rebind_count = loop3_cross_chapter::run(
        &mut repaired_anchors,
        &mut repaired_links,
        &anchor_index_by_id,
    );

    let summary = {
        let mut m = HashMap::new();
        // 对齐 Python key 命名：explicit_anchor_rebind_count
        m.insert(
            "explicit_anchor_rebind_count".to_string(),
            rebound_match_count,
        );
        m.insert(
            "ignored_orphan_anchor_count".to_string(),
            ignored_orphan_count,
        );
        m.insert(
            "ambiguous_followup_match_count".to_string(),
            ambiguous_followup_match_count,
        );
        m.insert(
            "ambiguous_followup_rebind_count".to_string(),
            ambiguous_followup_rebind_count,
        );
        m.insert(
            "cross_chapter_same_page_rebind_count".to_string(),
            cross_chapter_same_page_rebind_count,
        );
        m
    };

    (repaired_anchors, repaired_links, summary)
}

#[cfg(test)]
mod tests;

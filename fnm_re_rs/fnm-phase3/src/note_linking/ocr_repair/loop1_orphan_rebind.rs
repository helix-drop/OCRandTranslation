//! Loop 1: orphan_anchor → 已匹配 synthetic 锚点重绑定。
//!
//! ←→ Python `_repair_explicit_footnote_anchor_ocr_variants` 行 782-843

use super::looks_like_single_digit_ocr_variant;
use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{BodyAnchorRecord, NoteItemRecord, NoteLinkRecord};
use fnm_core::types::LinkResolver;
use std::collections::HashMap;

/// 返回 `(rebound_match_count, ignored_orphan_count)`。
pub(super) fn run(
    repaired_anchors: &mut [BodyAnchorRecord],
    repaired_links: &mut [NoteLinkRecord],
    anchor_index_by_id: &HashMap<String, usize>,
    note_item_by_id: &HashMap<String, &NoteItemRecord>,
) -> (i64, i64) {
    let mut rebound_match_count = 0i64;
    let mut ignored_orphan_count = 0i64;

    for orphan_index in 0..repaired_links.len() {
        let row_note_kind = repaired_links[orphan_index].note_kind;
        let row_status = repaired_links[orphan_index].status;
        if row_note_kind.as_str() != "footnote" || row_status.as_str() != "orphan_anchor" {
            continue;
        }
        // mem::take 替代 clone：row 用于下方 functional update（line 87 `..row`）
        // 必须 owned；末尾保证回写 repaired_links[orphan_index]——若中途 continue
        // 也需还原（见 continue 分支前的 restore）。
        let row = std::mem::take(&mut repaired_links[orphan_index]);
        let anchor_id = row.anchor_id.trim().to_string();
        let explicit_index = match anchor_index_by_id.get(&anchor_id) {
            Some(&idx) => idx,
            None => {
                repaired_links[orphan_index] = row;
                continue;
            }
        };
        let explicit_anchor = repaired_anchors[explicit_index].clone();
        if explicit_anchor.synthetic {
            repaired_links[orphan_index] = row;
            continue;
        }

        let mut candidates: Vec<(i64, usize, usize)> = Vec::new();
        for (match_index, match_row) in repaired_links.iter().enumerate() {
            if match_row.note_kind.as_str() != "footnote" || match_row.status.as_str() != "matched"
            {
                continue;
            }
            if match_row.chapter_id != row.chapter_id {
                continue;
            }
            let synthetic_index = match anchor_index_by_id.get(&match_row.anchor_id) {
                Some(&idx) => idx,
                None => continue,
            };
            let synthetic_anchor = &repaired_anchors[synthetic_index];
            if !synthetic_anchor.synthetic {
                continue;
            }
            if !looks_like_single_digit_ocr_variant(&row.marker, &match_row.marker) {
                continue;
            }
            let note_item = match note_item_by_id.get(&match_row.note_item_id) {
                Some(item) => *item,
                None => continue,
            };
            let page_distance = (note_item.page_no - explicit_anchor.page_no).abs();
            if page_distance > 2 {
                continue;
            }
            candidates.push((page_distance, match_row.marker.len(), match_index));
        }

        if candidates.len() != 1 {
            repaired_links[orphan_index] = row;
            continue;
        }

        let (_, _, match_index) = candidates[0];
        // 提前提取后续需要的字段，避免下方 functional update 内 self-clone
        let matched_marker_normalized = normalize_note_marker(&repaired_links[match_index].marker);
        let matched_row = std::mem::take(&mut repaired_links[match_index]);
        repaired_links[match_index] = NoteLinkRecord {
            anchor_id: explicit_anchor.anchor_id.clone(),
            resolver: LinkResolver::Repair,
            confidence: 1.0,
            ..matched_row
        };
        repaired_links[orphan_index] = NoteLinkRecord {
            status: fnm_core::types::LinkStatus::Ignored,
            resolver: LinkResolver::Repair,
            confidence: 1.0,
            ..row
        };

        let repaired_marker = matched_marker_normalized;
        let original_marker = normalize_note_marker(&explicit_anchor.normalized_marker);
        if !repaired_marker.is_empty() && repaired_marker != original_marker {
            repaired_anchors[explicit_index] = BodyAnchorRecord {
                normalized_marker: repaired_marker.clone(),
                certainty: 1.0,
                ocr_repaired_from_marker: original_marker,
                ..explicit_anchor
            };
        }
        rebound_match_count += 1;
        ignored_orphan_count += 1;
    }

    (rebound_match_count, ignored_orphan_count)
}

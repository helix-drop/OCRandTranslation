//! Loop 3: 跨章同页重绑定。
//!
//! ←→ Python `_repair_explicit_footnote_anchor_ocr_variants` 行 931-967
//!
//! 对每个已匹配但锚点仍为 synthetic 的脚注 link，寻找同页同 marker 的
//! orphan_anchor link，其背后有一个非 synthetic 显式锚点。精确匹配时
//! （1 个候选），将 synthetic link 重绑定到该显式锚点，并将孤儿 link
//! 标记为 ignored。注意：此循环不限同 chapter——即允许跨章。

use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{BodyAnchorRecord, NoteLinkRecord};
use fnm_core::types::LinkResolver;
use std::collections::HashMap;

/// 返回 `cross_chapter_same_page_rebind_count`。
pub(super) fn run(
    repaired_anchors: &mut [BodyAnchorRecord],
    repaired_links: &mut [NoteLinkRecord],
    anchor_index_by_id: &HashMap<String, usize>,
) -> i64 {
    let mut cross_chapter_same_page_rebind_count = 0i64;

    for match_index in 0..repaired_links.len() {
        let row_note_kind = repaired_links[match_index].note_kind;
        let row_status = repaired_links[match_index].status;
        if row_note_kind.as_str() != "footnote" || row_status.as_str() != "matched" {
            continue;
        }
        if !repaired_links[match_index]
            .anchor_id
            .trim()
            .starts_with("synthetic-footnote-")
        {
            continue;
        }
        let row = std::mem::take(&mut repaired_links[match_index]);

        // 只收集 index 对——避免 push 时整 record clone（NoteLinkRecord + BodyAnchorRecord）。
        let mut candidates: Vec<(usize, usize)> = Vec::new(); // (orphan_link_index, explicit_anchor_index)
        let row_marker = normalize_note_marker(&row.marker);
        for (orphan_index, orphan_link) in repaired_links.iter().enumerate() {
            if orphan_link.status.as_str() != "orphan_anchor" {
                continue;
            }
            if normalize_note_marker(&orphan_link.marker) != row_marker {
                continue;
            }
            if orphan_link.page_no_start != row.page_no_start {
                continue;
            }
            let explicit_index = match anchor_index_by_id.get(orphan_link.anchor_id.trim()) {
                Some(&idx) => idx,
                None => continue,
            };
            let explicit_anchor = &repaired_anchors[explicit_index];
            if explicit_anchor.synthetic {
                continue;
            }
            candidates.push((orphan_index, explicit_index));
        }

        if candidates.len() != 1 {
            // 还原 row 到原位（前面 mem::take 留了 default）
            repaired_links[match_index] = row;
            continue;
        }

        let (orphan_index, explicit_index) = candidates[0];
        let new_anchor_id = repaired_anchors[explicit_index].anchor_id.clone();
        let new_confidence = repaired_anchors[explicit_index].certainty.clamp(0.0, 1.0);
        let orphan_row = std::mem::take(&mut repaired_links[orphan_index]);
        repaired_links[match_index] = NoteLinkRecord {
            anchor_id: new_anchor_id,
            resolver: LinkResolver::Repair,
            confidence: new_confidence,
            ..row
        };
        repaired_links[orphan_index] = NoteLinkRecord {
            status: fnm_core::types::LinkStatus::Ignored,
            resolver: LinkResolver::Repair,
            confidence: 1.0,
            ..orphan_row
        };
        cross_chapter_same_page_rebind_count += 1;
    }

    cross_chapter_same_page_rebind_count
}

//! Loop 2: ambiguous 跟进消歧。
//!
//! ←→ Python `_repair_explicit_footnote_anchor_ocr_variants` 行 845-929
//!
//! 对每个 status=ambiguous 的脚注 link，寻找同页同章的两个未匹配显式锚点
//! 和一个已匹配但绑在 synthetic 锚点上的 link（marker 像 OCR 变体）。
//! 精确匹配时（2 显式候选 + 1 跟进候选），将歧义 link 绑定第一个显式锚点，
//! 跟进 link 绑定第二个显式锚点，并修复锚点的 normalized_marker。

use super::looks_like_single_digit_ocr_variant;
use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{BodyAnchorRecord, NoteLinkRecord};
use fnm_core::types::LinkResolver;

/// 返回 `(ambiguous_followup_match_count, ambiguous_followup_rebind_count)`。
pub(super) fn run(
    repaired_anchors: &mut [BodyAnchorRecord],
    repaired_links: &mut [NoteLinkRecord],
) -> (i64, i64) {
    let mut ambiguous_followup_match_count = 0i64;
    let mut ambiguous_followup_rebind_count = 0i64;

    // 先收集所有已匹配的显式锚点 ID（排除 synthetic-footnote- 前缀）
    let matched_explicit_anchor_ids: std::collections::HashSet<String> = repaired_links
        .iter()
        .filter(|l| {
            l.status.as_str() == "matched"
                && l.note_kind.as_str() == "footnote"
                && !l.anchor_id.trim().is_empty()
                && !l.anchor_id.trim().starts_with("synthetic-footnote-")
        })
        .map(|l| l.anchor_id.trim().to_string())
        .collect();

    for ambiguous_index in 0..repaired_links.len() {
        let row_note_kind = repaired_links[ambiguous_index].note_kind;
        let row_status = repaired_links[ambiguous_index].status;
        if row_note_kind.as_str() != "footnote" || row_status.as_str() != "ambiguous" {
            continue;
        }
        let row = repaired_links[ambiguous_index].clone();
        let marker = normalize_note_marker(&row.marker);
        if marker.is_empty() {
            continue;
        }

        // ←→ Python 行 854-861: 搜索同页同章的未匹配显式锚点
        let mut explicit_candidates: Vec<(usize, BodyAnchorRecord)> = Vec::new();
        for (explicit_index, explicit_anchor) in repaired_anchors.iter().enumerate() {
            if explicit_anchor.synthetic {
                continue;
            }
            if explicit_anchor.chapter_id != row.chapter_id {
                continue;
            }
            if explicit_anchor.page_no != row.page_no_start {
                continue;
            }
            if matched_explicit_anchor_ids.contains(explicit_anchor.anchor_id.trim()) {
                continue;
            }
            if normalize_note_marker(&explicit_anchor.normalized_marker) != marker {
                continue;
            }
            if explicit_anchor.anchor_kind.as_str() != "footnote"
                && explicit_anchor.anchor_kind.as_str() != "unknown"
            {
                continue;
            }
            explicit_candidates.push((explicit_index, explicit_anchor.clone()));
        }

        // ←→ Python 行 863-866: 排序: page_no, paragraph_index, char_start, anchor_id
        explicit_candidates.sort_by(|a, b| {
            let a = &a.1;
            let b = &b.1;
            let cmp = a.page_no.cmp(&b.page_no);
            if cmp != std::cmp::Ordering::Equal {
                return cmp;
            }
            let cmp = a.paragraph_index.cmp(&b.paragraph_index);
            if cmp != std::cmp::Ordering::Equal {
                return cmp;
            }
            let cmp = a.char_start.cmp(&b.char_start);
            if cmp != std::cmp::Ordering::Equal {
                return cmp;
            }
            a.anchor_id.cmp(&b.anchor_id)
        });

        if explicit_candidates.len() != 2 {
            continue;
        }

        // ←→ Python 行 870-881: 搜索跟进候选 (synthetic 锚点已匹配 link，同页同章，OCR 变体)
        let mut followup_candidates: Vec<(usize, NoteLinkRecord)> = Vec::new();
        for (match_index, match_row) in repaired_links.iter().enumerate() {
            if match_row.note_kind.as_str() != "footnote" || match_row.status.as_str() != "matched"
            {
                continue;
            }
            if match_row.chapter_id != row.chapter_id {
                continue;
            }
            if match_row.page_no_start != row.page_no_start {
                continue;
            }
            if !match_row
                .anchor_id
                .trim()
                .starts_with("synthetic-footnote-")
            {
                continue;
            }
            if !looks_like_single_digit_ocr_variant(&marker, &match_row.marker) {
                continue;
            }
            followup_candidates.push((match_index, match_row.clone()));
        }

        if followup_candidates.len() != 1 {
            continue;
        }

        // ←→ Python 行 887-905: 执行消歧绑定
        // 只 clone 真正需要的字段；BodyAnchorRecord 整体 clone 移除。
        let first_anchor_id = explicit_candidates[0].1.anchor_id.clone();
        let first_certainty = explicit_candidates[0].1.certainty;
        let second_explicit_index = explicit_candidates[1].0;
        let second_anchor_id = explicit_candidates[1].1.anchor_id.clone();
        let second_normalized_marker = explicit_candidates[1].1.normalized_marker.clone();
        // followup_candidates 后续不再使用——直接 remove 消费 owned
        let (followup_index, followup_row) = followup_candidates.remove(0);
        let followup_marker_normalized = normalize_note_marker(&followup_row.marker);

        repaired_links[ambiguous_index] = NoteLinkRecord {
            anchor_id: first_anchor_id,
            status: fnm_core::types::LinkStatus::Matched,
            resolver: LinkResolver::Repair,
            confidence: first_certainty.clamp(0.0, 1.0),
            ..row
        };
        repaired_links[followup_index] = NoteLinkRecord {
            anchor_id: second_anchor_id,
            resolver: LinkResolver::Repair,
            confidence: 1.0,
            ..followup_row
        };

        // ←→ Python 行 900-905: 修复锚点的 normalized_marker
        let repaired_marker = followup_marker_normalized;
        let original_marker = normalize_note_marker(&second_normalized_marker);
        if !repaired_marker.is_empty() && repaired_marker != original_marker {
            let old = std::mem::take(&mut repaired_anchors[second_explicit_index]);
            repaired_anchors[second_explicit_index] = BodyAnchorRecord {
                normalized_marker: repaired_marker,
                certainty: 1.0,
                ocr_repaired_from_marker: original_marker,
                ..old
            };
        }
        ambiguous_followup_match_count += 1;
        ambiguous_followup_rebind_count += 1;
    }

    (
        ambiguous_followup_match_count,
        ambiguous_followup_rebind_count,
    )
}

//! 尾注 link 的合同修复主体——4 段顺序流程。
//!
//! ←→ Python `repair_endnote_links_for_contract`（modules/endnote_repair.py）
//!
//! # 4 段流程
//! 1. **精确 + 排序去歧 + OCR 修复**（Python 行 45-113）
//! 2. **orphan_note ↔ orphan_anchor fallback 配对**（Python 行 115-152）
//! 3. **按 (chapter_id, marker) 分组 dedup**（Python 行 154-222）
//! 4. **endnote-only 残存孤儿配对**（Python 行 224-284）
//!
//! 4 段共享 mutable state（`repaired_links` / `anchors` / `used_anchor_ids`），
//! 强行拆 4 文件会让 `&mut` 借用模式变复杂——保持单文件实现，每段用注释明确边界。

use super::project_priority;
use crate::note_linking::chapter_meta::NoteItemMeta;
use fnm_core::note_marker::{marker_digits_are_ordered_subsequence, normalize_note_marker};
use fnm_core::records::{BodyAnchorRecord, NoteLinkRecord};
use fnm_core::types::{AnchorKind, LinkResolver, LinkStatus, NoteKind};
use std::collections::HashMap;

/// 修复尾注 link（contract 修复）。
///
/// ←→ Python `repair_endnote_links_for_contract`
///
/// 按照数据驱动规则修复 orphan_note / ambiguous endnote link：
/// 1. 精确 marker 匹配（single candidate）
/// 2. 多 candidate 排序去歧（distance-based）
/// 3. OCR 修复（marker 数字为有序子序列）
/// 4. endnote-only 配对（orphan_note ↔ orphan_anchor）
/// 5. 按 (chapter_id, marker) 分组 dedup
/// 6. endnote-only 书的残存孤儿配对（同章 marker 匹配）
///
/// 注：Python 端接 `book_type` 参数，但实际只用 `has_footnote_links` 判断
/// 是否启用 endnote-only 残孤配对（行 226）。Rust 端改为直接从 links 数据
/// 驱动判断，已对齐 Python 1:1 语义；book_type 删除避免死参。
pub fn repair_endnote_links_for_contract(
    links: &[NoteLinkRecord],
    anchors: &mut [BodyAnchorRecord],
    note_item_meta_by_id: &HashMap<String, NoteItemMeta>,
) -> (Vec<NoteLinkRecord>, HashMap<String, i64>) {
    let mut repaired_links: Vec<NoteLinkRecord> = links.to_vec();
    // Clone anchors at the start for by-id lookups, so anchors_by_id borrows
    // from the local clone rather than the &mut parameter. This allows
    // the OCR repair section (Python lines 102-105) to mutate anchors directly.
    let anchors_lookup = anchors.to_owned();
    let anchors_by_id: HashMap<String, &BodyAnchorRecord> = anchors_lookup
        .iter()
        .filter(|a| !a.anchor_id.trim().is_empty())
        .map(|a| (a.anchor_id.clone(), a))
        .collect();
    let mut used_anchor_ids: std::collections::HashSet<String> = links
        .iter()
        .filter(|row| row.status == LinkStatus::Matched && !row.anchor_id.trim().is_empty())
        .map(|row| row.anchor_id.clone())
        .collect();
    let mut ocr_repair_count: i64 = 0;
    let mut fallback_match_count: i64 = 0;

    // ── 第 1 段：精确 + 排序去歧 + OCR 修复 ──────────────────────────
    // ←→ Python 行 45-113
    // index-based 循环是必要的：Python 也在 enumerate 后修改 repaired_links[index]
    #[allow(clippy::needless_range_loop)]
    for index in 0..repaired_links.len() {
        let link = &repaired_links[index];
        if link.note_kind != NoteKind::Endnote {
            continue;
        }
        if link.status != LinkStatus::OrphanNote && link.status != LinkStatus::Ambiguous {
            continue;
        }
        let marker = normalize_note_marker(&link.marker);

        // 1a：精确 marker 匹配
        let mut candidates: Vec<&BodyAnchorRecord> = anchors
            .iter()
            .filter(|row| {
                row.chapter_id == link.chapter_id
                    && !row.synthetic
                    && (row.anchor_kind == AnchorKind::Endnote
                        || row.anchor_kind == AnchorKind::Unknown)
                    && !used_anchor_ids.contains(&row.anchor_id)
                    && normalize_note_marker(&row.normalized_marker) == marker
            })
            .collect();
        if candidates.len() == 1 {
            let selected = candidates[0];
            repaired_links[index] = NoteLinkRecord {
                anchor_id: selected.anchor_id.clone(),
                status: LinkStatus::Matched,
                resolver: LinkResolver::Repair,
                confidence: selected.certainty.clamp(0.0, 1.0),
                ..link.clone()
            };
            used_anchor_ids.insert(selected.anchor_id.clone());
            continue;
        }
        if candidates.len() > 1 {
            let page_no = link.page_no_start;
            candidates.sort_by_key(|row| {
                (
                    (row.page_no - page_no).abs(),
                    row.page_no,
                    row.paragraph_index,
                    row.char_start,
                )
            });
            if candidates.len() >= 2
                && (candidates[0].page_no - page_no).abs()
                    == (candidates[1].page_no - page_no).abs()
            {
                // 距离相同 → 歧义，跳过
                candidates.clear();
            } else {
                let selected = candidates[0];
                repaired_links[index] = NoteLinkRecord {
                    anchor_id: selected.anchor_id.clone(),
                    status: LinkStatus::Matched,
                    resolver: LinkResolver::Repair,
                    confidence: selected.certainty.clamp(0.0, 1.0),
                    ..link.clone()
                };
                used_anchor_ids.insert(selected.anchor_id.clone());
                continue;
            }
        }

        // 1b：OCR 修复（marker 数字为有序子序列）
        let mut repair_candidates: Vec<&BodyAnchorRecord> = anchors
            .iter()
            .filter(|row| {
                row.chapter_id == link.chapter_id
                    && !row.synthetic
                    && (row.anchor_kind == AnchorKind::Endnote
                        || row.anchor_kind == AnchorKind::Unknown)
                    && !used_anchor_ids.contains(&row.anchor_id)
                    && marker_digits_are_ordered_subsequence(&row.normalized_marker, &marker)
            })
            .collect();
        repair_candidates.sort_by_key(|row| {
            (
                (row.page_no - link.page_no_start).abs(),
                row.page_no,
                row.paragraph_index,
                row.char_start,
            )
        });
        if repair_candidates.len() == 1 {
            // 先 clone 需要的字段，再 drop repair_candidates（它持有对 anchors 的引用）
            let sel_anchor_id = repair_candidates[0].anchor_id.clone();
            let marker_for_anchor = marker.clone();
            let original_marker = normalize_note_marker(&repair_candidates[0].normalized_marker);

            // drop repair_candidates 后再 mutable 访问 anchors
            drop(repair_candidates);

            // ←→ Python 行 102-105: 修改 anchor 的 4 个字段
            if let Some(sel_idx) = anchors.iter().position(|a| a.anchor_id == sel_anchor_id) {
                anchors[sel_idx].normalized_marker = marker_for_anchor;
                anchors[sel_idx].anchor_kind = AnchorKind::Endnote;
                anchors[sel_idx].certainty = 1.0;
                anchors[sel_idx].ocr_repaired_from_marker = original_marker;
            }
            ocr_repair_count += 1;
            repaired_links[index] = NoteLinkRecord {
                anchor_id: sel_anchor_id.clone(),
                status: LinkStatus::Matched,
                resolver: LinkResolver::Repair,
                confidence: 1.0,
                marker: marker.clone(),
                ..link.clone()
            };
            used_anchor_ids.insert(sel_anchor_id);
            continue;
        }
    }

    // ── 第 2 段：orphan_note ↔ orphan_anchor fallback 配对 ────────────
    // ←→ Python 行 115-152
    // 先收集所有配对决策，再一次性应用，避免同时不可变/可变借用 repaired_links
    let mut fallback_pairings: Vec<(usize, String, LinkResolver, f64)> = Vec::new(); // (link_index, anchor_id, resolver, confidence)
    let mut orphan_ignore_indices: Vec<usize> = Vec::new();
    #[allow(clippy::needless_range_loop)]
    for index in 0..repaired_links.len() {
        let link = &repaired_links[index];
        if link.note_kind != NoteKind::Endnote {
            continue;
        }
        if link.status != LinkStatus::OrphanNote && link.status != LinkStatus::Ambiguous {
            continue;
        }
        let mut fallback_candidates: Vec<(i64, usize, String, f64)> = Vec::new(); // (distance, orphan_anchor_link_index, anchor_id, confidence)
        for ci in 0..repaired_links.len() {
            let candidate_link = &repaired_links[ci];
            if candidate_link.chapter_id != link.chapter_id {
                continue;
            }
            if candidate_link.note_kind != NoteKind::Endnote
                || candidate_link.status != LinkStatus::OrphanAnchor
            {
                continue;
            }
            if let Some(anchor) = anchors_by_id.get(&candidate_link.anchor_id) {
                if used_anchor_ids.contains(&anchor.anchor_id) {
                    continue;
                }
                fallback_candidates.push((
                    (anchor.page_no - link.page_no_start).abs(),
                    ci,
                    anchor.anchor_id.clone(),
                    anchor.certainty,
                ));
            }
        }
        if fallback_candidates.is_empty() {
            continue;
        }
        fallback_candidates.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.2.len().cmp(&b.2.len())));
        let (_, orphan_ci, anchor_id, confidence) = fallback_candidates.into_iter().next().unwrap();
        fallback_pairings.push((index, anchor_id.clone(), LinkResolver::Fallback, confidence));
        orphan_ignore_indices.push(orphan_ci);
        used_anchor_ids.insert(anchor_id);
        fallback_match_count += 1;
    }
    // 应用配对
    for (index, anchor_id, resolver, confidence) in &fallback_pairings {
        let existing = std::mem::take(&mut repaired_links[*index]);
        repaired_links[*index] = NoteLinkRecord {
            anchor_id: anchor_id.clone(),
            status: LinkStatus::Matched,
            resolver: *resolver,
            confidence: confidence.clamp(0.0, 1.0),
            ..existing
        };
    }
    for orphan_ci in orphan_ignore_indices {
        if repaired_links[orphan_ci].status != LinkStatus::Ignored {
            let existing = std::mem::take(&mut repaired_links[orphan_ci]);
            repaired_links[orphan_ci] = NoteLinkRecord {
                status: LinkStatus::Ignored,
                resolver: LinkResolver::Fallback,
                confidence: 1.0,
                ..existing
            };
        }
    }

    // ── 第 3 段：按 (chapter_id, marker) 分组 dedup ──────────────────
    // ←→ Python 行 154-222
    let mut groups: HashMap<(String, String), Vec<usize>> = HashMap::new();
    for (index, row) in repaired_links.iter().enumerate() {
        if row.note_kind != NoteKind::Endnote {
            continue;
        }
        let marker = normalize_note_marker(&row.marker);
        if marker.is_empty() {
            continue;
        }
        let cid = row.chapter_id.trim().to_string();
        groups.entry((cid, marker)).or_default().push(index);
    }

    for ((chapter_id_val, _marker_val), indexes) in &groups {
        if indexes.is_empty() {
            continue;
        }
        let mut real_anchor_ids: Vec<String> = Vec::new();
        let mut synthetic_anchor_ids_by_position: HashMap<(String, String, i64, i64, i64), String> =
            HashMap::new();
        for &index in indexes {
            let row = &repaired_links[index];
            let anchor_id = row.anchor_id.trim().to_string();
            if row.status != LinkStatus::Matched || anchor_id.is_empty() {
                continue;
            }
            if let Some(anchor) = anchors_by_id.get(&anchor_id) {
                if !anchor.synthetic {
                    if !real_anchor_ids.contains(&anchor_id) {
                        real_anchor_ids.push(anchor_id.clone());
                    }
                } else {
                    let synthetic_key = (
                        anchor.chapter_id.clone(),
                        normalize_note_marker(&anchor.normalized_marker),
                        anchor.page_no,
                        anchor.char_start,
                        anchor.char_end,
                    );
                    synthetic_anchor_ids_by_position
                        .entry(synthetic_key)
                        .or_insert_with(|| anchor_id.clone());
                }
            }
        }
        let anchor_ids: Vec<String> = if !real_anchor_ids.is_empty() {
            real_anchor_ids
        } else {
            synthetic_anchor_ids_by_position.values().cloned().collect()
        };
        if anchor_ids.is_empty() {
            continue;
        }
        let candidate_indexes: Vec<usize> = indexes
            .iter()
            .filter(|&&index| {
                let st = repaired_links[index].status;
                st == LinkStatus::Matched
                    || st == LinkStatus::OrphanNote
                    || st == LinkStatus::Ambiguous
            })
            .copied()
            .collect();
        if candidate_indexes.len() <= 1 {
            continue;
        }
        let mut ranked_indexes = candidate_indexes;
        ranked_indexes.sort_by_key(|&index| {
            let row = &repaired_links[index];
            let nid = row.note_item_id.trim();
            let pm = note_item_meta_by_id
                .get(nid)
                .map(|m| m.projection_mode.as_str())
                .unwrap_or("");
            (
                -project_priority(pm),
                row.page_no_start,
                row.note_item_id.clone(),
                row.link_id.clone(),
            )
        });
        let winner_count = anchor_ids.len().min(ranked_indexes.len());
        for winner_order in 0..winner_count {
            let winner_index = ranked_indexes[winner_order];
            let anchor_id = anchor_ids[winner_order].clone();
            let existing = std::mem::take(&mut repaired_links[winner_index]);
            repaired_links[winner_index] = NoteLinkRecord {
                chapter_id: chapter_id_val.clone(),
                anchor_id,
                status: LinkStatus::Matched,
                resolver: LinkResolver::Repair,
                confidence: existing.confidence.clamp(0.0, 1.0).max(1.0),
                ..existing
            };
        }
        for &loser_index in &ranked_indexes[winner_count..] {
            let existing = std::mem::take(&mut repaired_links[loser_index]);
            repaired_links[loser_index] = NoteLinkRecord {
                chapter_id: chapter_id_val.clone(),
                anchor_id: String::new(),
                status: LinkStatus::Ignored,
                resolver: LinkResolver::Repair,
                confidence: 1.0,
                ..existing
            };
        }
    }

    // ── 第 4 段：endnote-only 孤儿配对 ──────────────────────────────
    // ←→ Python 行 224-284
    // 数据驱动：仅当全书无 footnote link 时做 endnote-only 配对。
    let has_footnote_links = repaired_links
        .iter()
        .any(|row| row.note_kind == NoteKind::Footnote);
    if !has_footnote_links {
        let mut orphan_note_by_chapter_marker: HashMap<(String, String), Vec<usize>> =
            HashMap::new();
        let mut orphan_anchor_by_chapter_marker: HashMap<(String, String), Vec<usize>> =
            HashMap::new();
        for (index, row) in repaired_links.iter().enumerate() {
            if row.note_kind != NoteKind::Endnote {
                continue;
            }
            let marker = normalize_note_marker(&row.marker);
            if marker.is_empty() {
                continue;
            }
            let cid = row.chapter_id.trim().to_string();
            let key = (cid, marker);
            if row.status == LinkStatus::OrphanNote {
                orphan_note_by_chapter_marker
                    .entry(key)
                    .or_default()
                    .push(index);
            } else if row.status == LinkStatus::OrphanAnchor {
                orphan_anchor_by_chapter_marker
                    .entry(key)
                    .or_default()
                    .push(index);
            }
        }
        let common_keys: std::collections::BTreeSet<_> = orphan_note_by_chapter_marker
            .keys()
            .filter(|k| orphan_anchor_by_chapter_marker.contains_key(k))
            .collect();
        for key in common_keys {
            let mut note_indexes = orphan_note_by_chapter_marker
                .get(key)
                .cloned()
                .unwrap_or_default();
            let mut anchor_indexes = orphan_anchor_by_chapter_marker
                .get(key)
                .cloned()
                .unwrap_or_default();
            note_indexes.sort_by_key(|&index| {
                let row = &repaired_links[index];
                let nid = row.note_item_id.trim();
                let pm = note_item_meta_by_id
                    .get(nid)
                    .map(|m| m.projection_mode.as_str())
                    .unwrap_or("");
                (
                    -project_priority(pm),
                    row.page_no_start,
                    row.note_item_id.clone(),
                )
            });
            anchor_indexes.sort_by_key(|&index| {
                let row = &repaired_links[index];
                (row.page_no_start, row.link_id.clone())
            });
            let cid = key.0.clone();
            let pair_count = note_indexes.len().min(anchor_indexes.len());
            for offset in 0..pair_count {
                let note_index = note_indexes[offset];
                let anchor_index = anchor_indexes[offset];
                let anchor_anchor_id = repaired_links[anchor_index].anchor_id.clone();
                let anchor_confidence = repaired_links[anchor_index].confidence;
                let note_row = std::mem::take(&mut repaired_links[note_index]);
                repaired_links[note_index] = NoteLinkRecord {
                    chapter_id: cid.clone(),
                    anchor_id: anchor_anchor_id,
                    status: LinkStatus::Matched,
                    resolver: LinkResolver::Fallback,
                    confidence: anchor_confidence.clamp(0.0, 1.0).max(1.0),
                    ..note_row
                };
                let anchor_row = std::mem::take(&mut repaired_links[anchor_index]);
                repaired_links[anchor_index] = NoteLinkRecord {
                    status: LinkStatus::Ignored,
                    resolver: LinkResolver::Fallback,
                    confidence: 1.0,
                    ..anchor_row
                };
                fallback_match_count += 1;
            }
        }
    }

    let contract_repair_matched_count = repaired_links
        .iter()
        .filter(|row| row.note_kind == NoteKind::Endnote && row.status == LinkStatus::Matched)
        .count() as i64;

    let mut summary = HashMap::new();
    summary.insert(
        "contract_repair_matched_count".to_string(),
        contract_repair_matched_count,
    );
    summary.insert("contract_repair_ocr_count".to_string(), ocr_repair_count);
    summary.insert(
        "contract_repair_fallback_count".to_string(),
        fallback_match_count,
    );

    (repaired_links, summary)
}

//! ←→ FNM_RE/stages/footnote_links.py
//!
//! 脚注 link 匹配：anchor → note_item 配对、synthetic anchor 降级。

use fnm_core::records::{BodyAnchorRecord, NoteItemRecord};
use fnm_core::types::{AnchorKind, LinkResolver, LinkStatus, NoteKind};
use std::collections::HashSet;

/// 构建脚注 link。
///
/// ←→ Python `build_footnote_links`
///
/// 返回：(links, link_serial_end, synthetic_serial_end, ocr_repaired_count)
pub fn build_footnote_links(
    anchors: &mut Vec<BodyAnchorRecord>,
    note_items: &[NoteItemRecord],
    used_anchor_ids: &mut HashSet<String>,
    link_serial_start: usize,
    synthetic_serial_start: usize,
) -> (Vec<fnm_core::records::NoteLinkRecord>, usize, usize, usize) {
    let mut links: Vec<fnm_core::records::NoteLinkRecord> = Vec::new();
    let mut link_serial = link_serial_start;
    let synthetic_serial = synthetic_serial_start;
    let mut ocr_repaired_count = 0usize;

    for note_item in note_items {
        if note_item.note_kind.as_str() != "footnote" {
            continue;
        }
        let marker = note_item.marker.trim();
        let chapter_id = note_item.chapter_id.trim();
        if marker.is_empty() {
            links.push(crate::link_utils::link_new_link(
                &crate::link_utils::NewLinkParams {
                    serial: link_serial,
                    chapter_id,
                    region_id: &note_item.region_id,
                    note_item_id: &note_item.note_item_id,
                    anchor_id: "",
                    status: LinkStatus::Ignored,
                    resolver: LinkResolver::Rule,
                    confidence: 0.0,
                    note_kind: NoteKind::Footnote,
                    marker: "",
                    page_no_start: note_item.page_no,
                    page_no_end: note_item.page_no,
                },
            ));
            link_serial += 1;
            continue;
        }

        // 星号脚注按页内顺序匹配
        if marker.chars().all(|c| c == '*') && !marker.is_empty() {
            let mut same_page: Vec<&BodyAnchorRecord> = anchors
                .iter()
                .filter(|a| {
                    a.chapter_id == chapter_id
                        && !a.synthetic
                        && !used_anchor_ids.contains(&a.anchor_id)
                        && a.anchor_kind == AnchorKind::Footnote
                        && a.normalized_marker.trim() == marker
                        && a.page_no == note_item.page_no
                })
                .collect();
            same_page.sort_by_key(|a| (a.paragraph_index, a.char_start));
            if let Some(selected) = same_page.first() {
                used_anchor_ids.insert(selected.anchor_id.clone());
                links.push(crate::link_utils::link_new_link(
                    &crate::link_utils::NewLinkParams {
                        serial: link_serial,
                        chapter_id,
                        region_id: &note_item.region_id,
                        note_item_id: &note_item.note_item_id,
                        anchor_id: &selected.anchor_id,
                        status: LinkStatus::Matched,
                        resolver: LinkResolver::Rule,
                        confidence: selected.certainty.clamp(0.0, 1.0),
                        note_kind: NoteKind::Footnote,
                        marker,
                        page_no_start: note_item.page_no,
                        page_no_end: note_item.page_no,
                    },
                ));
                link_serial += 1;
                continue;
            }
        }

        // 正常 footnote 匹配
        let candidates = crate::link_utils::link_candidate_anchors(
            anchors,
            &crate::link_utils::CandidateFilter {
                chapter_id,
                marker,
                expected_kinds: &[AnchorKind::Footnote],
                used_anchor_ids,
                page_no: Some(note_item.page_no),
                footnote_window: true,
                include_synthetic: false,
                allow_cross_chapter: false,
            },
        );
        if candidates.len() == 1 {
            let selected = candidates[0];
            used_anchor_ids.insert(selected.anchor_id.clone());
            links.push(crate::link_utils::link_new_link(
                &crate::link_utils::NewLinkParams {
                    serial: link_serial,
                    chapter_id,
                    region_id: &note_item.region_id,
                    note_item_id: &note_item.note_item_id,
                    anchor_id: &selected.anchor_id,
                    status: LinkStatus::Matched,
                    resolver: LinkResolver::Rule,
                    confidence: selected.certainty.clamp(0.0, 1.0),
                    note_kind: NoteKind::Footnote,
                    marker,
                    page_no_start: note_item.page_no,
                    page_no_end: note_item.page_no,
                },
            ));
            link_serial += 1;
            continue;
        }
        if candidates.len() > 1 {
            let collapsed = crate::link_utils::collapse_redundant_candidates(candidates);
            if collapsed.len() == 1 {
                let selected = collapsed[0];
                used_anchor_ids.insert(selected.anchor_id.clone());
                links.push(crate::link_utils::link_new_link(
                    &crate::link_utils::NewLinkParams {
                        serial: link_serial,
                        chapter_id,
                        region_id: &note_item.region_id,
                        note_item_id: &note_item.note_item_id,
                        anchor_id: &selected.anchor_id,
                        status: LinkStatus::Matched,
                        resolver: LinkResolver::Repair,
                        confidence: selected.certainty.clamp(0.0, 1.0),
                        note_kind: NoteKind::Footnote,
                        marker,
                        page_no_start: note_item.page_no,
                        page_no_end: note_item.page_no,
                    },
                ));
                link_serial += 1;
                continue;
            }
            if let Some(selected) =
                crate::link_utils::nearest_unique_candidate(&collapsed, note_item.page_no)
            {
                used_anchor_ids.insert(selected.anchor_id.clone());
                links.push(crate::link_utils::link_new_link(
                    &crate::link_utils::NewLinkParams {
                        serial: link_serial,
                        chapter_id,
                        region_id: &note_item.region_id,
                        note_item_id: &note_item.note_item_id,
                        anchor_id: &selected.anchor_id,
                        status: LinkStatus::Matched,
                        resolver: LinkResolver::Repair,
                        confidence: selected.certainty.clamp(0.0, 1.0),
                        note_kind: NoteKind::Footnote,
                        marker,
                        page_no_start: note_item.page_no,
                        page_no_end: note_item.page_no,
                    },
                ));
                link_serial += 1;
                continue;
            }
            links.push(crate::link_utils::link_new_link(
                &crate::link_utils::NewLinkParams {
                    serial: link_serial,
                    chapter_id,
                    region_id: &note_item.region_id,
                    note_item_id: &note_item.note_item_id,
                    anchor_id: "",
                    status: LinkStatus::Ambiguous,
                    resolver: LinkResolver::Rule,
                    confidence: 0.0,
                    note_kind: NoteKind::Footnote,
                    marker,
                    page_no_start: note_item.page_no,
                    page_no_end: note_item.page_no,
                },
            ));
            link_serial += 1;
            continue;
        }

        // OCR repair: ordered subsequence match
        let mut repair_candidates: Vec<(String, String)> = Vec::new();
        for a in anchors.iter() {
            if a.chapter_id != chapter_id || a.synthetic || used_anchor_ids.contains(&a.anchor_id) {
                continue;
            }
            if !crate::link_utils::within_footnote_window(a.page_no, note_item.page_no, 1) {
                continue;
            }
            if a.anchor_kind != AnchorKind::Footnote {
                continue;
            }
            let norm_a = a.normalized_marker.trim();
            if norm_a.len() >= marker.len() {
                continue;
            }
            if marker_digits_are_ordered_subsequence(norm_a, marker) {
                repair_candidates.push((a.anchor_id.clone(), a.normalized_marker.clone()));
            }
        }
        // 按 page_no/paragraph_index/char_start 排序需要原始数据，这里简化为只取第一个
        if repair_candidates.len() == 1 {
            let (ref anchor_id, ref original_marker) = repair_candidates[0];
            if let Some(a) = anchors.iter_mut().find(|a| a.anchor_id == *anchor_id) {
                a.normalized_marker = marker.to_string();
                a.certainty = 1.0;
                a.ocr_repaired_from_marker = original_marker.clone();
            }
            used_anchor_ids.insert(anchor_id.clone());
            ocr_repaired_count += 1;
            links.push(crate::link_utils::link_new_link(
                &crate::link_utils::NewLinkParams {
                    serial: link_serial,
                    chapter_id,
                    region_id: &note_item.region_id,
                    note_item_id: &note_item.note_item_id,
                    anchor_id,
                    status: LinkStatus::Matched,
                    resolver: LinkResolver::Repair,
                    confidence: 1.0,
                    note_kind: NoteKind::Footnote,
                    marker,
                    page_no_start: note_item.page_no,
                    page_no_end: note_item.page_no,
                },
            ));
            link_serial += 1;
            continue;
        }

        // 无法匹配 → orphan_note，留待 LLM repair（Phase 3.5）。
        // 不创建 synthetic anchor：无坐标的 synthetic 锚点会被 Phase 4 跳过，
        // 不应在 Phase 3 伪装为 Matched（铁律 §3：禁止上游伪装）。
        links.push(crate::link_utils::link_new_link(
            &crate::link_utils::NewLinkParams {
                serial: link_serial,
                chapter_id,
                region_id: &note_item.region_id,
                note_item_id: &note_item.note_item_id,
                anchor_id: "",
                status: LinkStatus::OrphanNote,
                resolver: LinkResolver::Rule,
                confidence: 0.0,
                note_kind: NoteKind::Footnote,
                marker,
                page_no_start: note_item.page_no,
                page_no_end: note_item.page_no,
            },
        ));
        link_serial += 1;
    }

    (links, link_serial, synthetic_serial, ocr_repaired_count)
}

// ── 内部辅助 ────────────────────────────────────────────────────

/// 判断 a 的数字是否是 b 的数字的有序子序列。
/// ←→ Python `marker_digits_are_ordered_subsequence`
fn marker_digits_are_ordered_subsequence(a: &str, b: &str) -> bool {
    let digits_a: Vec<char> = a.chars().filter(|c| c.is_ascii_digit()).collect();
    let digits_b: Vec<char> = b.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits_a.is_empty() || digits_b.is_empty() {
        return false;
    }
    if digits_a.len() > digits_b.len() {
        return false;
    }
    let mut j = 0usize;
    for &da in &digits_a {
        while j < digits_b.len() && digits_b[j] != da {
            j += 1;
        }
        if j >= digits_b.len() {
            return false;
        }
        j += 1;
    }
    true
}

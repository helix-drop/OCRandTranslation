//! ←→ Python `note_linking.py:_chapter_contracts`

use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{BodyAnchorRecord, ChapterLinkContract, NoteLinkRecord};
use fnm_phase2::chapter_split::ChapterLayers;
use serde_json::Value;
use std::collections::{HashMap, HashSet};

/// 安全地将字符串转为 i64。
fn safe_int(text: &str) -> i64 {
    text.trim().parse::<i64>().unwrap_or(0)
}

/// 计算 projection_mode 优先级。
fn projection_priority(mode: &str) -> i64 {
    match mode {
        "native" => 3,
        "projection" => 2,
        "fallback" => 1,
        _ => 0,
    }
}

/// 构建章节契约。
///
/// ←→ Python `_chapter_contracts`
pub fn chapter_contracts(
    chapter_layers: &ChapterLayers,
    effective_links: &[NoteLinkRecord],
    body_anchors: &[BodyAnchorRecord],
) -> (Vec<ChapterLinkContract>, HashMap<String, Value>) {
    let mut contracts: Vec<ChapterLinkContract> = Vec::new();
    let mut contract_evidence: HashMap<String, Value> = HashMap::new();
    let anchor_by_id: HashMap<String, &BodyAnchorRecord> = body_anchors
        .iter()
        .filter_map(|a| {
            let id = a.anchor_id.trim();
            if id.is_empty() {
                None
            } else {
                Some((id.to_string(), a))
            }
        })
        .collect();

    // anchor_total_by_chapter：按章统计 endnote anchor 的不同 marker 数
    let mut anchor_markers_by_chapter: HashMap<String, HashSet<String>> = HashMap::new();
    for anchor in body_anchors {
        if anchor.anchor_kind.as_str() != "endnote" {
            continue;
        }
        let cid = anchor.chapter_id.trim();
        let marker = normalize_note_marker(&anchor.normalized_marker);
        if cid.is_empty() || marker.is_empty() || !marker.chars().all(|c| c.is_ascii_digit()) {
            continue;
        }
        anchor_markers_by_chapter
            .entry(cid.to_string())
            .or_default()
            .insert(marker);
    }
    let chapter_marker_counts: HashMap<String, usize> = anchor_markers_by_chapter
        .iter()
        .map(|(k, v)| (k.clone(), v.len()))
        .collect();

    for chapter in &chapter_layers.chapter_layers {
        let chapter_id = chapter.chapter_id.trim().to_string();
        let raw_has_endnote_signal =
            !chapter.endnote_items.is_empty() || !chapter.endnote_regions.is_empty();
        let note_mode = chapter
            .policy_applied
            .get("note_mode")
            .and_then(|v| v.as_str())
            .unwrap_or("no_notes");
        let requires_endnote_contract = raw_has_endnote_signal;

        let chapter_links: Vec<&NoteLinkRecord> = effective_links
            .iter()
            .filter(|row| {
                row.chapter_id.trim() == chapter_id && row.note_kind.as_str() == "endnote"
            })
            .collect();

        let mut endnote_items: Vec<_> = chapter.endnote_items.iter().collect();
        endnote_items.sort_by(|a, b| {
            let cmp = a.page_no.cmp(&b.page_no);
            if cmp == std::cmp::Ordering::Equal {
                a.note_item_id.cmp(&b.note_item_id)
            } else {
                cmp
            }
        });
        let mut endnote_items_by_marker: HashMap<String, Vec<_>> = HashMap::new();
        for item in &endnote_items {
            let marker = normalize_note_marker(&item.marker);
            if marker.is_empty() {
                continue;
            }
            endnote_items_by_marker
                .entry(marker)
                .or_default()
                .push(*item);
        }

        let matched_item_ids: HashSet<String> = chapter_links
            .iter()
            .filter(|row| row.status.as_str() == "matched" && !row.note_item_id.trim().is_empty())
            .map(|row| row.note_item_id.trim().to_string())
            .collect();
        let all_endnote_item_ids: HashSet<String> = endnote_items
            .iter()
            .filter(|row| !row.note_item_id.trim().is_empty())
            .map(|row| row.note_item_id.trim().to_string())
            .collect();

        let mut chapter_anchor_demand_by_marker: HashMap<String, i64> = HashMap::new();
        for row in &chapter_links {
            if row.status.as_str() != "matched" && row.status.as_str() != "orphan_anchor" {
                continue;
            }
            let marker = normalize_note_marker(&row.marker);
            if marker.is_empty() {
                continue;
            }
            *chapter_anchor_demand_by_marker.entry(marker).or_insert(0) += 1;
        }

        let mut expected_item_ids: HashSet<String> = HashSet::new();
        let mut expected_markers: HashSet<String> = HashSet::new();
        for (marker, demand) in &chapter_anchor_demand_by_marker {
            if *demand <= 0 {
                continue;
            }
            let mut candidates = endnote_items_by_marker
                .get(marker)
                .cloned()
                .unwrap_or_default();
            if candidates.is_empty() {
                continue;
            }
            candidates.sort_by(|a, b| {
                let pa = projection_priority(a.projection_mode.as_deref().unwrap_or(""));
                let pb = projection_priority(b.projection_mode.as_deref().unwrap_or(""));
                let cmp = pb.cmp(&pa); // 降序
                if cmp == std::cmp::Ordering::Equal {
                    let cmp2 = a.page_no.cmp(&b.page_no);
                    if cmp2 == std::cmp::Ordering::Equal {
                        a.note_item_id.cmp(&b.note_item_id)
                    } else {
                        cmp2
                    }
                } else {
                    cmp
                }
            });
            for candidate in candidates.iter().take(*demand as usize) {
                let candidate_id = candidate.note_item_id.trim();
                if candidate_id.is_empty() {
                    continue;
                }
                expected_item_ids.insert(candidate_id.to_string());
                expected_markers.insert(marker.clone());
            }
        }

        let target_item_ids = if expected_item_ids.is_empty() {
            all_endnote_item_ids.clone()
        } else {
            expected_item_ids.clone()
        };

        let ambiguous_link_ids: Vec<String> = chapter_links
            .iter()
            .filter(|row| {
                row.status.as_str() == "ambiguous"
                    && (target_item_ids.is_empty()
                        || target_item_ids.contains(row.note_item_id.trim()))
            })
            .map(|row| row.link_id.clone())
            .collect();
        let orphan_note_link_ids: Vec<String> = chapter_links
            .iter()
            .filter(|row| {
                row.status.as_str() == "orphan_note"
                    && (target_item_ids.is_empty()
                        || target_item_ids.contains(row.note_item_id.trim()))
            })
            .map(|row| row.link_id.clone())
            .collect();
        let orphan_anchor_link_ids: Vec<String> = chapter_links
            .iter()
            .filter(|row| {
                row.status.as_str() == "orphan_anchor"
                    && (expected_markers.is_empty()
                        || expected_markers.contains(&normalize_note_marker(&row.marker)))
            })
            .map(|row| row.link_id.clone())
            .collect();

        type MarkerKey = (i64, i64, i64, i64, String);
        let mut ordered_numeric_markers: Vec<(MarkerKey, i64)> = Vec::new();
        for row in &chapter_links {
            if row.status.as_str() != "matched" {
                continue;
            }
            if !target_item_ids.is_empty() && !target_item_ids.contains(row.note_item_id.trim()) {
                continue;
            }
            let marker_value = safe_int(&row.marker);
            if marker_value > 0 {
                let anchor = anchor_by_id.get(row.anchor_id.trim());
                let (sort_key, _) = if let Some(anchor) = anchor {
                    if anchor.page_no > 0 && anchor.chapter_id.trim() == chapter_id {
                        (
                            (
                                0,
                                anchor.page_no,
                                anchor.paragraph_index,
                                anchor.char_start,
                                row.link_id.clone(),
                            ),
                            marker_value,
                        )
                    } else {
                        (
                            (
                                1,
                                row.page_no_start,
                                row.page_no_end,
                                0,
                                row.link_id.clone(),
                            ),
                            marker_value,
                        )
                    }
                } else {
                    (
                        (
                            1,
                            row.page_no_start,
                            row.page_no_end,
                            0,
                            row.link_id.clone(),
                        ),
                        marker_value,
                    )
                };
                ordered_numeric_markers.push((sort_key, marker_value));
            }
        }
        ordered_numeric_markers.sort_by(|a, b| a.0.cmp(&b.0));
        let non_ignored_numeric_markers: Vec<i64> =
            ordered_numeric_markers.iter().map(|(_, m)| *m).collect();
        let mut first_marker_is_one = non_ignored_numeric_markers
            .first()
            .map(|&m| m == 1)
            .unwrap_or(true);

        let mut endnotes_all_matched = target_item_ids.is_subset(&matched_item_ids);
        let mut no_ambiguous_left = ambiguous_link_ids.is_empty();
        let mut no_orphan_note = orphan_note_link_ids.is_empty();
        let book_type = chapter
            .policy_applied
            .get("book_type")
            .and_then(|v| v.as_str())
            .unwrap_or("no_notes");
        if book_type == "endnote_only"
            && note_mode == "book_endnote_bound"
            && !target_item_ids.is_empty()
        {
            first_marker_is_one = true;
        }
        let mut endnote_only_no_orphan_anchor = if book_type == "endnote_only" {
            orphan_anchor_link_ids.is_empty()
        } else {
            true
        };

        if !requires_endnote_contract {
            endnotes_all_matched = true;
            no_ambiguous_left = true;
            no_orphan_note = true;
            endnote_only_no_orphan_anchor = true;
        }

        // def_anchor_mismatch 与 marker gap 计算
        // 分离 footnote / endnote def_count，使 def_anchor_mismatch 只对比 endnote 侧。
        // 铁律 §3：禁止广播——脚注的定义数不混入尾注的 def count。
        let count_numeric_defs = |items: &[fnm_core::records::NoteItemRecord]| -> i64 {
            let mut seen: HashSet<i64> = HashSet::new();
            for item in items {
                let v = safe_int(&normalize_note_marker(&item.marker));
                if v > 0 {
                    seen.insert(v);
                }
            }
            seen.len() as i64
        };
        let endnote_def_count = count_numeric_defs(&chapter.endnote_items);
        let footnote_def_count = count_numeric_defs(&chapter.footnote_items);

        // def_count：总定义数（footnote + endnote），保持 fnm-core/records.rs 兼容语义。
        let all_def_items: Vec<_> = chapter
            .footnote_items
            .iter()
            .chain(chapter.endnote_items.iter())
            .collect();
        let mut def_numeric_markers: Vec<i64> = Vec::new();
        let mut seen_markers: HashSet<i64> = HashSet::new();
        for item in &all_def_items {
            let marker_value = safe_int(&normalize_note_marker(&item.marker));
            if marker_value > 0 && !seen_markers.contains(&marker_value) {
                def_numeric_markers.push(marker_value);
                seen_markers.insert(marker_value);
            }
        }
        def_numeric_markers.sort_unstable();
        let def_count = def_numeric_markers.len();

        // endnote 专属数字 marker 序列——用于 endnote contract 的 gap/first-marker/sequence，
        // 不混入 footnote marker（铁律 §1：分类源头唯一；§3：禁止广播）。
        let mut endnote_numeric_markers: Vec<i64> = Vec::new();
        let mut endnote_seen: HashSet<i64> = HashSet::new();
        for item in &chapter.endnote_items {
            let marker_value = safe_int(&normalize_note_marker(&item.marker));
            if marker_value > 0 && !endnote_seen.contains(&marker_value) {
                endnote_numeric_markers.push(marker_value);
                endnote_seen.insert(marker_value);
            }
        }
        endnote_numeric_markers.sort_unstable();

        let anchor_total = *chapter_marker_counts.get(&chapter_id).unwrap_or(&0) as i64;

        let endnote_first_marker_is_one = endnote_numeric_markers
            .first()
            .map(|&m| m == 1)
            .unwrap_or(true);
        if !endnote_numeric_markers.is_empty() {
            first_marker_is_one = endnote_first_marker_is_one;
        } else if !requires_endnote_contract {
            first_marker_is_one = true;
        }

        let mut endnote_unique_markers: Vec<i64> = endnote_numeric_markers.clone();
        endnote_unique_markers.dedup();
        let has_marker_gap = if note_mode == "book_endnote_bound" {
            false
        } else if !endnote_unique_markers.is_empty() {
            let mut truncated = endnote_unique_markers.clone();
            if truncated.len() >= 2 {
                for i in (1..truncated.len()).rev() {
                    let gap_ratio = (truncated[i] - truncated[i - 1]) as f64
                        / std::cmp::max(1, truncated[i - 1]) as f64;
                    if gap_ratio > 0.5 && truncated[i] > truncated[i - 1] + 20 {
                        truncated = truncated[..i].to_vec();
                        break;
                    }
                }
            }
            let expected: Vec<i64> = (1..=truncated.last().copied().unwrap_or(0)).collect();
            truncated != expected
        } else {
            false
        };

        let def_anchor_mismatch = if !requires_endnote_contract || note_mode == "book_endnote_bound"
        {
            false
        } else if anchor_total > 0 {
            endnote_def_count != anchor_total
        } else {
            false
        };

        let mut failure_link_ids_set: HashSet<String> = HashSet::new();
        for id in &ambiguous_link_ids {
            failure_link_ids_set.insert(id.clone());
        }
        for id in &orphan_note_link_ids {
            failure_link_ids_set.insert(id.clone());
        }
        for id in &orphan_anchor_link_ids {
            failure_link_ids_set.insert(id.clone());
        }
        let mut failure_link_ids: Vec<String> = failure_link_ids_set.into_iter().collect();
        failure_link_ids.sort();

        contracts.push(ChapterLinkContract {
            chapter_id: chapter_id.clone(),
            requires_endnote_contract,
            book_type: book_type.to_string(),
            note_mode: note_mode.to_string(),
            first_marker_is_one,
            endnotes_all_matched,
            no_ambiguous_left,
            no_orphan_note,
            endnote_only_no_orphan_anchor,
            failure_link_ids,
            has_marker_gap,
            def_anchor_mismatch,
            endnote_def_count,
            footnote_def_count,
            def_count: def_count as i64,
            anchor_total,
            marker_sequence: endnote_unique_markers,
        });

        contract_evidence.insert(
            chapter_id.clone(),
            serde_json::json!({
                "raw_has_endnote_signal": raw_has_endnote_signal,
                "requires_endnote_contract": requires_endnote_contract,
                "endnote_item_count": endnote_items.len(),
                "endnote_link_count": chapter_links.len(),
                "target_item_count": target_item_ids.len(),
                "target_marker_count": expected_markers.len(),
                "non_ignored_numeric_markers": non_ignored_numeric_markers,
                "ambiguous_link_ids": ambiguous_link_ids,
                "orphan_note_link_ids": orphan_note_link_ids,
                "orphan_anchor_link_ids": orphan_anchor_link_ids,
            }),
        );
    }

    contracts.sort_by(|a, b| a.chapter_id.cmp(&b.chapter_id));
    (contracts, contract_evidence)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_input() {
        let layers = ChapterLayers {
            chapters: Vec::new(),
            regions: Vec::new(),
            note_items: Vec::new(),
            ..Default::default()
        };
        let links: Vec<NoteLinkRecord> = Vec::new();
        let anchors: Vec<BodyAnchorRecord> = Vec::new();
        let (contracts, evidence) = chapter_contracts(&layers, &links, &anchors);
        assert!(contracts.is_empty());
        assert!(evidence.is_empty());
    }
}

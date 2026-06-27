//! ←→ Python `note_linking.py:_apply_link_overrides`

use fnm_core::records::{BodyAnchorRecord, NoteItemRecord, NoteLinkRecord, NoteRegionRecord};
use fnm_core::types::{LinkResolver, LinkStatus, NoteKind};
use serde_json::Value;
use std::collections::{HashMap, HashSet};

/// 从 note_item 推断 anchor（用于 link override 中 anchor_id 以 llm-anchor- 开头的情况）。
fn find_existing_explicit_anchor<'a>(
    note_item: &NoteItemRecord,
    body_anchors: &'a [BodyAnchorRecord],
    expected_note_kind: &str,
) -> Option<&'a BodyAnchorRecord> {
    let marker = fnm_core::note_marker::normalize_note_marker(&note_item.marker);
    let chapter_id = note_item.chapter_id.trim();
    let note_kind = expected_note_kind.trim();
    if marker.is_empty() || chapter_id.is_empty() || !matches!(note_kind, "footnote" | "endnote") {
        return None;
    }
    let mut candidates: Vec<&'a BodyAnchorRecord> = Vec::new();
    for anchor in body_anchors {
        if anchor.synthetic {
            continue;
        }
        if anchor.chapter_id.trim() != chapter_id {
            continue;
        }
        if fnm_core::note_marker::normalize_note_marker(&anchor.normalized_marker) != marker {
            continue;
        }
        let anchor_kind = anchor.anchor_kind.as_str();
        // 严格匹配 expected_note_kind：Unknown 不能用于自动匹配
        //（铁律 §4：Phase3 不能重新分类；Unknown 只有 review/orphan 路径）。
        if anchor_kind != note_kind {
            continue;
        }
        if note_kind == "footnote" {
            let note_page = note_item.page_no;
            let anchor_page = anchor.page_no;
            if note_page > 0
                && anchor_page > 0
                && (anchor_page - note_page).abs()
                    > super::anchor_overrides::FOOTNOTE_OVERRIDE_PAGE_PADDING
            {
                continue;
            }
        }
        candidates.push(anchor);
    }
    if candidates.len() == 1 {
        Some(candidates[0])
    } else {
        None
    }
}

/// 应用 link override。
///
/// ←→ Python `_apply_link_overrides`
pub fn apply_link_overrides(
    note_links: &[NoteLinkRecord],
    link_overrides: Option<&HashMap<String, Value>>,
    note_items: &[NoteItemRecord],
    body_anchors: &[BodyAnchorRecord],
    note_regions: &[NoteRegionRecord],
) -> (Vec<NoteLinkRecord>, Value, Vec<Value>) {
    let overrides = link_overrides.unwrap_or(&HashMap::new()).clone();
    let mut effective_links: Vec<NoteLinkRecord> = note_links.to_vec();
    let note_items_by_id: HashMap<String, &NoteItemRecord> = note_items
        .iter()
        .filter_map(|item| {
            let id = item.note_item_id.trim();
            if id.is_empty() {
                None
            } else {
                Some((id.to_string(), item))
            }
        })
        .collect();
    let anchors_by_id: HashMap<String, &BodyAnchorRecord> = body_anchors
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
    let regions_by_id: HashMap<String, &NoteRegionRecord> = note_regions
        .iter()
        .filter_map(|r| {
            let id = r.region_id.trim();
            if id.is_empty() {
                None
            } else {
                Some((id.to_string(), r))
            }
        })
        .collect();

    let mut ignored_count = 0i64;
    let mut invalid_count = 0i64;
    let mut match_count = 0i64;
    let mut invalid_flags: Vec<String> = Vec::new();
    let mut matched_pairs: HashSet<(String, String)> = HashSet::new();
    let mut winner_link_ids: HashSet<String> = HashSet::new();
    let mut logs: Vec<Value> = Vec::new();

    for (target_id, payload) in overrides {
        let data = match payload.as_object() {
            Some(o) => o.clone(),
            None => continue,
        };
        let action = data
            .get("action")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_lowercase();
        let note_item_id = data
            .get("note_item_id")
            .or_else(|| data.get("definition_id"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let anchor_id = data
            .get("anchor_id")
            .or_else(|| data.get("ref_id"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();

        let mut resolved_index: Option<usize> = None;
        let exact_index = effective_links
            .iter()
            .position(|link| link.link_id == target_id);
        if let Some(idx) = exact_index {
            let exact_link = &effective_links[idx];
            let exact_note_item_id = exact_link.note_item_id.trim();
            let exact_anchor_id = exact_link.anchor_id.trim();
            if (note_item_id.is_empty() || note_item_id == exact_note_item_id)
                && (anchor_id.is_empty() || anchor_id == exact_anchor_id)
            {
                resolved_index = Some(idx);
            }
        }
        if resolved_index.is_none() && !note_item_id.is_empty() {
            resolved_index = effective_links
                .iter()
                .position(|link| link.note_item_id.trim() == note_item_id);
        }
        if resolved_index.is_none() && !anchor_id.is_empty() {
            resolved_index = effective_links
                .iter()
                .position(|link| link.anchor_id.trim() == anchor_id);
        }
        if resolved_index.is_none() {
            resolved_index = exact_index;
        }
        let resolved_index = match resolved_index {
            Some(idx) => idx,
            None => {
                invalid_count += 1;
                invalid_flags.push(format!("invalid_link_override:{}:target_link", target_id));
                continue;
            }
        };

        let link = effective_links[resolved_index].clone();

        if action == "ignore" {
            ignored_count += 1;
            let link_id = link.link_id.clone();
            effective_links[resolved_index] = NoteLinkRecord {
                status: LinkStatus::Ignored,
                resolver: LinkResolver::Repair,
                confidence: 1.0,
                ..link
            };
            logs.push(serde_json::json!({
                "kind": "link_override",
                "target_id": target_id,
                "link_id": link_id,
                "action": "ignore",
            }));
            continue;
        }
        if action != "match" {
            invalid_count += 1;
            invalid_flags.push(format!("invalid_link_override:{}:action", target_id));
            continue;
        }

        let note_item = match note_items_by_id.get(&note_item_id) {
            Some(item) => *item,
            None => {
                invalid_count += 1;
                invalid_flags.push(format!("invalid_link_override:{}:target", target_id));
                continue;
            }
        };

        let region = regions_by_id.get(&note_item.region_id);
        let expected_note_kind = region.map(|r| r.note_kind.as_str()).unwrap_or("");
        let mut anchor = anchors_by_id.get(&anchor_id).copied();
        if anchor.is_none() && anchor_id.starts_with("llm-anchor-") {
            anchor = find_existing_explicit_anchor(note_item, body_anchors, expected_note_kind);
        }
        let anchor = match anchor {
            Some(a) => a,
            None => {
                invalid_count += 1;
                invalid_flags.push(format!("invalid_link_override:{}:target", target_id));
                continue;
            }
        };

        let inferred_note_kind = if anchor.anchor_kind.as_str() == "footnote" {
            "footnote"
        } else if anchor.anchor_kind.as_str() == "endnote" {
            "endnote"
        } else {
            "unknown"
        };
        let same_chapter = note_item.chapter_id == anchor.chapter_id;
        let same_kind = (expected_note_kind == "footnote" || expected_note_kind == "endnote")
            && expected_note_kind == inferred_note_kind;
        if !same_chapter || !same_kind {
            invalid_count += 1;
            invalid_flags.push(format!("invalid_link_override:{}:consistency", target_id));
            continue;
        }
        if expected_note_kind == "footnote" {
            let note_page = note_item.page_no;
            let anchor_page = anchor.page_no;
            if note_page > 0
                && anchor_page > 0
                && (anchor_page - note_page).abs()
                    > super::anchor_overrides::FOOTNOTE_OVERRIDE_PAGE_PADDING
            {
                invalid_count += 1;
                invalid_flags.push(format!("invalid_link_override:{}:page_window", target_id));
                continue;
            }
        }

        let marker = if !note_item.marker.is_empty() {
            note_item.marker.clone()
        } else if !anchor.normalized_marker.is_empty() {
            anchor.normalized_marker.clone()
        } else {
            link.marker.clone()
        };
        let page_no = if anchor.page_no > 0 {
            anchor.page_no
        } else if note_item.page_no > 0 {
            note_item.page_no
        } else {
            link.page_no_start
        };
        let chapter_id = if !note_item.chapter_id.is_empty() {
            note_item.chapter_id.clone()
        } else if !anchor.chapter_id.is_empty() {
            anchor.chapter_id.clone()
        } else {
            link.chapter_id.clone()
        };
        match_count += 1;
        matched_pairs.insert((note_item.note_item_id.clone(), anchor.anchor_id.clone()));
        let link_id = link.link_id.clone();
        winner_link_ids.insert(link_id.clone());
        effective_links[resolved_index] = NoteLinkRecord {
            chapter_id,
            region_id: note_item.region_id.clone(),
            note_item_id: note_item.note_item_id.clone(),
            anchor_id: anchor.anchor_id.clone(),
            status: LinkStatus::Matched,
            resolver: LinkResolver::Repair,
            confidence: 1.0,
            note_kind: if expected_note_kind == "footnote" {
                NoteKind::Footnote
            } else {
                NoteKind::Endnote
            },
            marker,
            page_no_start: page_no,
            page_no_end: page_no,
            ..link
        };
        logs.push(serde_json::json!({
            "kind": "link_override",
            "target_id": target_id,
            "link_id": link_id,
            "action": "match",
            "note_item_id": note_item_id,
            "anchor_id": anchor_id,
        }));
    }

    if !matched_pairs.is_empty() {
        for link in effective_links.iter_mut() {
            if winner_link_ids.contains(&link.link_id) {
                continue;
            }
            let note_item_id = link.note_item_id.trim();
            let anchor_id = link.anchor_id.trim();
            let should_ignore =
                matched_pairs
                    .iter()
                    .any(|(matched_note_item_id, matched_anchor_id)| {
                        (!note_item_id.is_empty() && note_item_id == matched_note_item_id)
                            || (!anchor_id.is_empty() && anchor_id == matched_anchor_id)
                    });
            if should_ignore {
                ignored_count += 1;
                *link = NoteLinkRecord {
                    status: LinkStatus::Ignored,
                    resolver: LinkResolver::Repair,
                    confidence: 1.0,
                    ..link.clone()
                };
            }
        }
    }

    let override_summary = serde_json::json!({
        "ignored_link_override_count": ignored_count,
        "invalid_override_count": invalid_count,
        "matched_link_override_count": match_count,
        "invalid_override_flags": invalid_flags,
    });

    (effective_links, override_summary, logs)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_overrides() {
        let links: Vec<NoteLinkRecord> = Vec::new();
        let items: Vec<NoteItemRecord> = Vec::new();
        let anchors: Vec<BodyAnchorRecord> = Vec::new();
        let regions: Vec<NoteRegionRecord> = Vec::new();
        let (result, summary, logs) =
            apply_link_overrides(&links, None, &items, &anchors, &regions);
        assert!(result.is_empty());
        assert_eq!(summary["matched_link_override_count"], 0);
        assert!(logs.is_empty());
    }
}

//! ←→ Python `note_linking.py:_materialize_note_item_overrides`

use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{NoteItemRecord, NoteRegionRecord};
use fnm_core::types::NoteKind;
use serde_json::Value;
use std::collections::HashMap;

/// 物化 note_item override。
///
/// ←→ Python `_materialize_note_item_overrides`
pub fn materialize_note_item_overrides(
    note_items: &[NoteItemRecord],
    note_regions: &[NoteRegionRecord],
    note_item_overrides: Option<&HashMap<String, Value>>,
) -> (
    Vec<NoteItemRecord>,
    Vec<NoteRegionRecord>,
    Value,
    Vec<Value>,
) {
    let overrides = note_item_overrides.unwrap_or(&HashMap::new()).clone();
    let mut logs: Vec<Value> = Vec::new();
    let mut summary = serde_json::json!({
        "created_note_item_count": 0,
        "created_region_count": 0,
        "rejected_count": 0,
        "rejected_reasons": Vec::<String>::new(),
    });

    if overrides.is_empty() {
        return (note_items.to_vec(), note_regions.to_vec(), summary, logs);
    }

    let mut new_note_items = note_items.to_vec();
    let mut new_note_regions = note_regions.to_vec();
    let mut existing_note_item_ids: std::collections::HashSet<String> = new_note_items
        .iter()
        .filter_map(|ni| {
            let id = ni.note_item_id.trim();
            if id.is_empty() {
                None
            } else {
                Some(id.to_string())
            }
        })
        .collect();
    let mut existing_region_ids: std::collections::HashSet<String> = new_note_regions
        .iter()
        .filter_map(|nr| {
            let id = nr.region_id.trim();
            if id.is_empty() {
                None
            } else {
                Some(id.to_string())
            }
        })
        .collect();

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
            .and_then(|v| v.as_str())
            .unwrap_or(&target_id)
            .trim()
            .to_string();

        if action != "create" {
            summary["rejected_count"] =
                (summary["rejected_count"].as_i64().unwrap_or(0) + 1).into();
            let reasons = summary["rejected_reasons"].as_array_mut().unwrap();
            reasons.push(Value::String(format!(
                "{}:action={}",
                target_id,
                if action.is_empty() {
                    "missing"
                } else {
                    &action
                }
            )));
            continue;
        }
        if note_item_id.is_empty() || existing_note_item_ids.contains(&note_item_id) {
            summary["rejected_count"] =
                (summary["rejected_count"].as_i64().unwrap_or(0) + 1).into();
            let reasons = summary["rejected_reasons"].as_array_mut().unwrap();
            reasons.push(Value::String(format!(
                "{}:note_item_id_conflict",
                target_id
            )));
            continue;
        }

        let chapter_id = data
            .get("chapter_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let marker =
            normalize_note_marker(data.get("marker").and_then(|v| v.as_str()).unwrap_or(""));
        let text = data
            .get("text")
            .or_else(|| data.get("note_text"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let note_kind_str = data
            .get("note_kind")
            .and_then(|v| v.as_str())
            .unwrap_or("endnote")
            .trim();
        let note_kind = if note_kind_str == "footnote" {
            NoteKind::Footnote
        } else if note_kind_str == "endnote" {
            NoteKind::Endnote
        } else {
            NoteKind::Footnote
        };
        let page_no = data.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);

        if chapter_id.is_empty() || page_no <= 0 || marker.is_empty() || text.is_empty() {
            summary["rejected_count"] =
                (summary["rejected_count"].as_i64().unwrap_or(0) + 1).into();
            let reasons = summary["rejected_reasons"].as_array_mut().unwrap();
            reasons.push(Value::String(format!("{}:invalid_note_item", target_id)));
            continue;
        }

        let mut region_id = data
            .get("region_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if region_id.is_empty() || !existing_region_ids.contains(&region_id) {
            region_id = format!(
                "llm-note-region-{}-{}-{}",
                chapter_id, page_no, note_kind_str
            );
            if !existing_region_ids.contains(&region_id) {
                new_note_regions.push(NoteRegionRecord {
                    region_id: region_id.clone(),
                    chapter_id: chapter_id.clone(),
                    page_start: page_no,
                    page_end: page_no,
                    pages: vec![page_no],
                    note_kind,
                    scope: fnm_core::types::RegionScope::Chapter,
                    source: fnm_core::types::RegionSource::Llm,
                    heading_text: String::new(),
                    start_reason: "llm_note_item_override".to_string(),
                    end_reason: "llm_note_item_override".to_string(),
                    region_marker_alignment_ok: true,
                    region_start_first_source_marker: marker.clone(),
                    region_first_note_item_marker: marker.clone(),
                    review_required: data
                        .get("review_required")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false),
                });
                existing_region_ids.insert(region_id.clone());
                summary["created_region_count"] =
                    (summary["created_region_count"].as_i64().unwrap_or(0) + 1).into();
                logs.push(serde_json::json!({
                    "kind": "note_region_override",
                    "region_id": region_id,
                    "chapter_id": chapter_id,
                    "page_no": page_no,
                    "note_kind": note_kind_str,
                }));
            }
        }

        let marker_type = if note_kind_str == "footnote" {
            "footnote_marker"
        } else {
            "numeric"
        };
        new_note_items.push(NoteItemRecord {
            note_item_id: note_item_id.clone(),
            region_id: region_id.clone(),
            chapter_id: chapter_id.clone(),
            page_no,
            marker: marker.clone(),
            marker_type: marker_type.to_string(),
            text: text.clone(),
            source: data
                .get("source")
                .and_then(|v| v.as_str())
                .unwrap_or("llm")
                .to_string(),
            source_page_label: data
                .get("source_page_label")
                .and_then(|v| v.as_str())
                .unwrap_or(&page_no.to_string())
                .to_string(),
            is_reconstructed: data
                .get("is_reconstructed")
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
            review_required: data
                .get("review_required")
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
            note_kind,
            projection_mode: None,
            owner_chapter_id: None,
            source_marker: None,
            normalized_marker: None,
        });
        existing_note_item_ids.insert(note_item_id.clone());
        summary["created_note_item_count"] =
            (summary["created_note_item_count"].as_i64().unwrap_or(0) + 1).into();
        logs.push(serde_json::json!({
            "kind": "note_item_override",
            "note_item_id": note_item_id,
            "chapter_id": chapter_id,
            "page_no": page_no,
            "marker": marker,
            "note_kind": note_kind_str,
        }));
    }

    (new_note_items, new_note_regions, summary, logs)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_overrides() {
        let items: Vec<NoteItemRecord> = Vec::new();
        let regions: Vec<NoteRegionRecord> = Vec::new();
        let (new_items, new_regions, summary, logs) =
            materialize_note_item_overrides(&items, &regions, None);
        assert!(new_items.is_empty());
        assert!(new_regions.is_empty());
        assert_eq!(summary["created_note_item_count"], 0);
        assert!(logs.is_empty());
    }
}

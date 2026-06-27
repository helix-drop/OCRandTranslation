//! ←→ chapter_split.py:_apply_note_item_overrides_to_chapter_layers
//! 消费 review_overrides_v2 表中 scope=note_item 的行。
//! 支持 create / match / delete / update 四种 action。

use fnm_core::records::{NoteItemRecord, NoteRegionRecord};
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct NoteItemOverride {
    pub action: String,
    pub note_item_id: Option<String>,
    pub region_id: Option<String>,
    pub marker: Option<String>,
    pub text: Option<String>,
    pub note_kind_override: Option<String>,
}

/// 应用 overrides 到 note_items 列表。
pub fn apply_note_item_overrides(
    note_items: &mut Vec<NoteItemRecord>,
    note_regions: &[NoteRegionRecord],
    overrides: &[NoteItemOverride],
) {
    let region_lookup: HashMap<&str, &NoteRegionRecord> = note_regions
        .iter()
        .map(|r| (r.region_id.as_str(), r))
        .collect();

    for ov in overrides {
        match ov.action.as_str() {
            "delete" => {
                if let Some(ref id) = ov.note_item_id {
                    note_items.retain(|item| item.note_item_id != *id);
                }
            }
            "update" => {
                if let Some(ref id) = ov.note_item_id {
                    for item in note_items.iter_mut() {
                        if item.note_item_id == *id {
                            if let Some(ref text) = ov.text {
                                item.text = text.clone();
                            }
                            if let Some(ref marker) = ov.marker {
                                item.marker = marker.clone();
                            }
                            item.review_required = false;
                            break;
                        }
                    }
                }
            }
            "create" => {
                if let (Some(ref rid), Some(ref marker), Some(ref text)) =
                    (&ov.region_id, &ov.marker, &ov.text)
                {
                    if let Some(region) = region_lookup.get(rid.as_str()) {
                        let new_id = format!("{}-override-{}", rid, marker);
                        if !note_items.iter().any(|i| i.note_item_id == new_id) {
                            note_items.push(NoteItemRecord {
                                note_item_id: new_id,
                                region_id: rid.clone(),
                                chapter_id: region.chapter_id.clone(),
                                page_no: region.page_start,
                                marker: marker.clone(),
                                marker_type: "num".into(),
                                text: text.clone(),
                                source: "manual_override".into(),
                                source_page_label: String::new(),
                                is_reconstructed: false,
                                review_required: false,
                                note_kind: region.note_kind,
                                projection_mode: None,
                                owner_chapter_id: None,
                                source_marker: None,
                                normalized_marker: None,
                            });
                        }
                    }
                }
            }
            _ => {}
        }
    }
}

//! ←→ Python `note_linking.py:_materialize_anchor_overrides`

use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::BodyAnchorRecord;
use fnm_core::types::AnchorKind;
use serde_json::Value;
use std::collections::HashMap;

/// footnote anchor 与 note item 之间允许的最大页距（对齐 Python `FOOTNOTE_OVERRIDE_PAGE_PADDING`）。
pub(crate) const FOOTNOTE_OVERRIDE_PAGE_PADDING: i64 = 1;

/// 判断 anchor 是否为显式正文锚点（非合成、非 LLM）。
fn is_explicit_body_anchor(anchor: &BodyAnchorRecord) -> bool {
    if anchor.synthetic {
        return false;
    }
    let source = anchor.source.to_lowercase();
    if source == "llm"
        || anchor.anchor_id.starts_with("llm-anchor-")
        || anchor.anchor_id.starts_with("synthetic-")
    {
        return false;
    }
    true
}

/// anchor_kind 兼容性判断。
fn anchor_kind_compatible(left: &str, right: &str) -> bool {
    let left_kind = if left.is_empty() { "unknown" } else { left };
    let right_kind = if right.is_empty() { "unknown" } else { right };
    left_kind == right_kind || left_kind == "unknown" || right_kind == "unknown"
}

/// 检查是否已存在同章同页同 marker 的显式锚点。
fn has_existing_explicit_anchor(
    anchors: &[BodyAnchorRecord],
    chapter_id: &str,
    page_no: i64,
    normalized_marker: &str,
    anchor_kind: &str,
) -> bool {
    let marker = normalize_note_marker(normalized_marker);
    if marker.is_empty() {
        return false;
    }
    anchors.iter().any(|anchor| {
        is_explicit_body_anchor(anchor)
            && anchor.chapter_id == chapter_id
            && anchor.page_no == page_no
            && normalize_note_marker(&anchor.normalized_marker) == marker
            && anchor_kind_compatible(anchor.anchor_kind.as_str(), anchor_kind)
    })
}

/// 物化 anchor override。
///
/// ←→ Python `_materialize_anchor_overrides`
pub fn materialize_anchor_overrides(
    body_anchors: &[BodyAnchorRecord],
    anchor_overrides: Option<&HashMap<String, Value>>,
    chapter_body_text_by_page: Option<&HashMap<(String, i64), String>>,
) -> (Vec<BodyAnchorRecord>, Value, Vec<Value>) {
    let overrides = anchor_overrides.unwrap_or(&HashMap::new()).clone();
    let mut logs: Vec<Value> = Vec::new();
    let mut summary = serde_json::json!({
        "created_count": 0,
        "rejected_count": 0,
        "rejected_reasons": Vec::<String>::new(),
    });

    if overrides.is_empty() {
        return (body_anchors.to_vec(), summary, logs);
    }

    let mut existing_ids: std::collections::HashSet<String> = body_anchors
        .iter()
        .filter_map(|a| {
            let id = a.anchor_id.trim();
            if id.is_empty() {
                None
            } else {
                Some(id.to_string())
            }
        })
        .collect();
    let mut new_anchors = body_anchors.to_vec();

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
        let anchor_id = data
            .get("anchor_id")
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
        if anchor_id.is_empty() || existing_ids.contains(&anchor_id) {
            summary["rejected_count"] =
                (summary["rejected_count"].as_i64().unwrap_or(0) + 1).into();
            let reasons = summary["rejected_reasons"].as_array_mut().unwrap();
            reasons.push(Value::String(format!("{}:anchor_id_conflict", target_id)));
            continue;
        }

        let chapter_id = data
            .get("chapter_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let page_no = data.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
        let paragraph_index = data
            .get("paragraph_index")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let char_start = data
            .get("char_start")
            .and_then(|v| v.as_i64())
            .unwrap_or(-1);
        let char_end = data.get("char_end").and_then(|v| v.as_i64()).unwrap_or(-1);
        let certainty = data
            .get("certainty")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);

        if chapter_id.is_empty() || page_no <= 0 || char_start < 0 || char_end <= char_start {
            summary["rejected_count"] =
                (summary["rejected_count"].as_i64().unwrap_or(0) + 1).into();
            let reasons = summary["rejected_reasons"].as_array_mut().unwrap();
            reasons.push(Value::String(format!("{}:invalid_coords", target_id)));
            continue;
        }

        if let Some(text_map) = chapter_body_text_by_page {
            let body_text = text_map.get(&(chapter_id.clone(), page_no));
            if body_text.is_none() {
                summary["rejected_count"] =
                    (summary["rejected_count"].as_i64().unwrap_or(0) + 1).into();
                let reasons = summary["rejected_reasons"].as_array_mut().unwrap();
                reasons.push(Value::String(format!("{}:non_body_page", target_id)));
                continue;
            }
            let text_len = body_text.unwrap().len() as i64;
            if char_end > text_len {
                summary["rejected_count"] =
                    (summary["rejected_count"].as_i64().unwrap_or(0) + 1).into();
                let reasons = summary["rejected_reasons"].as_array_mut().unwrap();
                reasons.push(Value::String(format!("{}:coords_out_of_page", target_id)));
                continue;
            }
        }

        let anchor_kind_str = data
            .get("anchor_kind")
            .and_then(|v| v.as_str())
            .unwrap_or("endnote")
            .trim();
        let anchor_kind = if anchor_kind_str == "footnote" {
            AnchorKind::Footnote
        } else if anchor_kind_str == "endnote" {
            AnchorKind::Endnote
        } else {
            AnchorKind::Unknown
        };
        let normalized_marker = normalize_note_marker(
            data.get("normalized_marker")
                .and_then(|v| v.as_str())
                .unwrap_or(""),
        );
        if normalized_marker.is_empty() {
            summary["rejected_count"] =
                (summary["rejected_count"].as_i64().unwrap_or(0) + 1).into();
            let reasons = summary["rejected_reasons"].as_array_mut().unwrap();
            reasons.push(Value::String(format!("{}:missing_marker", target_id)));
            continue;
        }
        if has_existing_explicit_anchor(
            &new_anchors,
            &chapter_id,
            page_no,
            &normalized_marker,
            anchor_kind_str,
        ) {
            summary["rejected_count"] =
                (summary["rejected_count"].as_i64().unwrap_or(0) + 1).into();
            let reasons = summary["rejected_reasons"].as_array_mut().unwrap();
            reasons.push(Value::String(format!(
                "{}:existing_explicit_anchor",
                target_id
            )));
            continue;
        }

        let record = BodyAnchorRecord {
            anchor_id: anchor_id.clone(),
            chapter_id,
            page_no,
            paragraph_index,
            char_start,
            char_end,
            source_marker: normalized_marker.clone(),
            normalized_marker: normalized_marker.clone(),
            anchor_kind,
            certainty,
            source_text: data
                .get("source_text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            source: data
                .get("source")
                .and_then(|v| v.as_str())
                .unwrap_or("llm")
                .to_string(),
            synthetic: data
                .get("synthetic")
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
            ocr_repaired_from_marker: String::new(),
        };
        new_anchors.push(record);
        existing_ids.insert(anchor_id.clone());
        summary["created_count"] = (summary["created_count"].as_i64().unwrap_or(0) + 1).into();
        logs.push(serde_json::json!({
            "kind": "anchor_override",
            "anchor_id": anchor_id,
            "page_no": page_no,
            "char_start": char_start,
            "char_end": char_end,
            "source": "llm",
        }));
    }

    (new_anchors, summary, logs)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_overrides() {
        let anchors = vec![BodyAnchorRecord::default()];
        let (result, summary, logs) = materialize_anchor_overrides(&anchors, None, None);
        assert_eq!(result.len(), 1);
        assert_eq!(summary["created_count"], 0);
        assert!(logs.is_empty());
    }

    #[test]
    fn test_create_override() {
        let anchors: Vec<BodyAnchorRecord> = Vec::new();
        let mut overrides = HashMap::new();
        overrides.insert(
            "ov-1".to_string(),
            serde_json::json!({
                "action": "create",
                "anchor_id": "anc-1",
                "chapter_id": "ch-1",
                "page_no": 1,
                "char_start": 0,
                "char_end": 5,
                "normalized_marker": "1",
            }),
        );
        let (result, summary, logs) =
            materialize_anchor_overrides(&anchors, Some(&overrides), None);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].anchor_id, "anc-1");
        assert_eq!(summary["created_count"], 1);
        assert_eq!(logs.len(), 1);
    }
}

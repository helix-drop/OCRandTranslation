//! ←→ FNM_RE/shared/review.py
//! 复核覆盖层工具。

use serde_json::Value;
use std::collections::HashMap;

/// 给 note_links 附加 review_override 字段。
/// 与 Python `annotate_review_note_links` 一致。
pub fn annotate_review_note_links(
    note_links: &[Value],
    overrides: Option<&HashMap<String, HashMap<String, Value>>>,
) -> Vec<Value> {
    let link_overrides = overrides
        .and_then(|o| o.get("link"))
        .cloned()
        .unwrap_or_default();

    note_links
        .iter()
        .map(|link| {
            let mut payload = link.clone();
            let link_id = payload
                .get("link_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if let Some(ov) = link_overrides.get(link_id) {
                if let Some(obj) = payload.as_object_mut() {
                    obj.insert("review_override".into(), ov.clone());
                    obj.insert(
                        "review_action".into(),
                        Value::String(
                            ov.get("action")
                                .and_then(|v| v.as_str())
                                .unwrap_or("")
                                .trim()
                                .to_lowercase(),
                        ),
                    );
                }
            }
            payload
        })
        .collect()
}

/// 从 overrides 提取 LLM suggestions。
/// 与 Python `collect_llm_suggestions` 一致。
pub fn collect_llm_suggestions(
    overrides: Option<&HashMap<String, HashMap<String, Value>>>,
) -> Vec<Value> {
    let suggestions = overrides
        .and_then(|o| o.get("llm_suggestion"))
        .cloned()
        .unwrap_or_default();

    let mut result: Vec<Value> = suggestions
        .into_iter()
        .map(|(suggestion_id, mut payload)| {
            if let Some(obj) = payload.as_object_mut() {
                obj.insert("suggestion_id".into(), Value::String(suggestion_id));
            }
            payload
        })
        .collect();

    result.sort_by(|a, b| {
        let id_a = a
            .get("suggestion_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let id_b = b
            .get("suggestion_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        id_a.cmp(id_b)
    });

    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn annotate_empty_links() {
        let result = annotate_review_note_links(&[], None);
        assert!(result.is_empty());
    }

    #[test]
    fn annotate_with_override() {
        let links = vec![json!({"link_id": "nl-1", "status": "matched"})];
        let mut overrides: HashMap<String, HashMap<String, Value>> = HashMap::new();
        let mut link_ov = HashMap::new();
        link_ov.insert("nl-1".into(), json!({"action": "accept"}));
        overrides.insert("link".into(), link_ov);

        let result = annotate_review_note_links(&links, Some(&overrides));
        assert_eq!(result[0]["review_action"], "accept");
    }
}

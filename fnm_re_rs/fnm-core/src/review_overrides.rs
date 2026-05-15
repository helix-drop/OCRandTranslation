//! ←→ FNM_RE/shared/review_overrides.py
//! 结构化 review overrides 分组共享工具。

use serde_json::Value;
use std::collections::HashMap;

const KNOWN_SCOPES: &[&str] = &[
    "page",
    "chapter",
    "region",
    "link",
    "llm_suggestion",
    "anchor",
    "note_item",
];

/// 生成空的分组覆盖层结构。
pub fn empty_grouped_overrides() -> HashMap<String, HashMap<String, Value>> {
    KNOWN_SCOPES
        .iter()
        .map(|s| (s.to_string(), HashMap::new()))
        .collect()
}

/// 把 review_overrides（list 或 dict）按 scope → target_id → payload 分组。
/// 与 Python `group_review_overrides` 一致。
pub fn group_review_overrides(review_overrides: &Value) -> HashMap<String, HashMap<String, Value>> {
    let mut grouped = empty_grouped_overrides();

    if review_overrides.is_null() {
        return grouped;
    }

    if let Some(rows) = review_overrides.as_array() {
        for row in rows {
            let scope = row
                .get("scope")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_lowercase();
            let target_id = row
                .get("target_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string();
            let data = row
                .get("payload")
                .cloned()
                .unwrap_or(Value::Object(Default::default()));
            if scope.is_empty() || target_id.is_empty() {
                continue;
            }
            grouped.entry(scope).or_default().insert(target_id, data);
        }
        return grouped;
    }

    if let Some(obj) = review_overrides.as_object() {
        let has_known_scope = obj.keys().any(|k| KNOWN_SCOPES.contains(&k.as_str()));
        if has_known_scope {
            for (scope, rows) in obj {
                if !KNOWN_SCOPES.contains(&scope.as_str()) {
                    continue;
                }
                if let Some(rows_obj) = rows.as_object() {
                    let mut scope_group: HashMap<String, Value> = HashMap::new();
                    for (target_id, payload) in rows_obj {
                        let tid = target_id.trim().to_string();
                        if tid.is_empty() {
                            continue;
                        }
                        scope_group.insert(tid, payload.clone());
                    }
                    grouped.insert(scope.clone(), scope_group);
                }
            }
        }
    }

    grouped
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn empty_overrides() {
        let result = group_review_overrides(&json!(null));
        assert_eq!(result.len(), KNOWN_SCOPES.len());
        assert!(result.get("page").unwrap().is_empty());
    }

    #[test]
    fn group_list_format() {
        let input = json!([
            {"scope": "page", "target_id": "p1", "payload": {"role": "body"}},
            {"scope": "chapter", "target_id": "ch1", "payload": {"mode": "footnote_primary"}}
        ]);
        let result = group_review_overrides(&input);
        assert_eq!(result.get("page").unwrap().len(), 1);
        assert_eq!(result.get("chapter").unwrap().len(), 1);
    }

    #[test]
    fn group_dict_format() {
        let input = json!({
            "page": {"p1": {"role": "body"}},
            "link": {"nl1": {"action": "accept"}}
        });
        let result = group_review_overrides(&input);
        assert_eq!(result.get("page").unwrap().len(), 1);
        assert_eq!(result.get("link").unwrap().len(), 1);
    }
}

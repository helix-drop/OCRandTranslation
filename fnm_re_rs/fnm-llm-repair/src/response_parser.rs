//! ←→ Python `FNM_RE/modules/llm_repair.py` LLM JSON 响应解析（行 823-966）。
//!
//! 2 个函数：
//! - `parse_llm_repair_actions` ←→ `parse_llm_repair_actions`
//! - `select_auto_applicable_actions` ←→ `select_auto_applicable_actions`

use fnm_core::note_marker::normalize_note_marker;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{HashMap, HashSet};

use crate::constants::{
    FUZZY_SCORE_THRESHOLD, JSON_BLOCK_RE, LLM_REPAIR_FOOTNOTE_PAGE_PADDING,
    MIN_CHAPTER_UNMATCHED_FOR_AUTO,
};
use crate::usage::safe_float;

/// ←→ Python action dict 的结构化版本
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct RepairAction {
    pub action: String,
    pub note_item_id: String,
    pub anchor_id: String,
    pub anchor_phrase: String,
    pub marker: String,
    pub note_text: String,
    pub confidence: f64,
    pub reason: String,

    // Tier 1 fuzzy synthesize_anchor 由调用方在 enrich 阶段注入：
    #[serde(default, skip_serializing_if = "is_zero")]
    pub fuzzy_score: f64,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub ambiguous: bool,
    #[serde(default, skip_serializing_if = "is_zero_i64")]
    pub page_no: i64,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub link_id: String,
    /// 字节偏移（与 BodySpan 单位一致，非字符偏移）
    #[serde(default, skip_serializing_if = "is_zero_i64")]
    pub char_start: i64,
    /// 字节偏移（与 BodySpan 单位一致，非字符偏移）
    #[serde(default, skip_serializing_if = "is_zero_i64")]
    pub char_end: i64,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub matched_text: String,
    /// 置信度值是否来自 JSON number（而非文字映射）。auto-apply 路径要求 numeric。
    #[serde(default)]
    pub confidence_numeric: bool,
}

fn is_zero(v: &f64) -> bool {
    *v == 0.0
}

fn is_zero_i64(v: &i64) -> bool {
    *v == 0
}

/// 允许的 action 类型（与 Python set 对齐）
/// synthesize_note_item 已被移除——Phase3.5 无权创建 note item（P0-2）。
const ALLOWED_ACTIONS: &[&str] = &["match", "ignore_ref", "needs_review", "synthesize_anchor"];

/// ←→ Python `parse_llm_repair_actions` (llm_repair.py:823-871)
///
/// 解析 LLM 响应文本（JSON 数组或 `{actions: [...]}`），过滤合法 action。
pub fn parse_llm_repair_actions(text: &str) -> Vec<RepairAction> {
    let raw = text.trim();
    if raw.is_empty() {
        return Vec::new();
    }

    // 1. 优先匹配 ```json ... ``` 包裹
    let unwrapped: String = if let Some(captures) = JSON_BLOCK_RE.captures(raw) {
        captures
            .get(1)
            .map_or("", |m| m.as_str())
            .trim()
            .to_string()
    } else {
        raw.to_string()
    };

    // 2. 尝试 strict JSON 解析；失败时回退到首个 [...] 子串
    let payload: Value = match serde_json::from_str::<Value>(&unwrapped) {
        Ok(v) => v,
        Err(_) => {
            let start = unwrapped.find('[');
            let end = unwrapped.rfind(']');
            match (start, end) {
                (Some(s), Some(e)) if e > s => {
                    match serde_json::from_str::<Value>(&unwrapped[s..=e]) {
                        Ok(v) => v,
                        Err(_) => return Vec::new(),
                    }
                }
                _ => return Vec::new(),
            }
        }
    };

    // 3. `{actions: [...]}` 或 `[...]`
    let array: Vec<Value> = match payload {
        Value::Array(arr) => arr,
        Value::Object(map) => match map.get("actions") {
            Some(Value::Array(arr)) => arr.clone(),
            _ => return Vec::new(),
        },
        _ => return Vec::new(),
    };

    // 4. 逐项校验 + 规整
    let mut actions = Vec::with_capacity(array.len());
    for item in array {
        let Some(obj) = item.as_object() else {
            continue;
        };
        let action = obj
            .get("action")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_lowercase();
        if !ALLOWED_ACTIONS.contains(&action.as_str()) {
            continue;
        }
        let anchor_phrase = obj
            .get("anchor_phrase")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if action == "synthesize_anchor" && anchor_phrase.is_empty() {
            continue;
        }
        let marker_raw = obj.get("marker").and_then(|v| v.as_str()).unwrap_or("");
        let marker = normalize_note_marker(marker_raw);
        let note_text = obj
            .get("note_text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let anchor_id_raw = obj
            .get("anchor_id")
            .or_else(|| obj.get("ref_id"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let note_item_id = obj
            .get("note_item_id")
            .or_else(|| obj.get("definition_id"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let confidence_value = obj.get("confidence").unwrap_or(&Value::Null);
        let confidence = safe_float(confidence_value, 0.8);
        let confidence_numeric = confidence_value.is_number();
        let reason = obj
            .get("reason")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        actions.push(RepairAction {
            action,
            note_item_id,
            anchor_id: anchor_id_raw,
            anchor_phrase,
            marker,
            note_text,
            confidence,
            confidence_numeric,
            reason,
            ..Default::default()
        });
    }
    actions
}

/// `select_auto_applicable_actions` 参数包
///
/// ←→ Python `select_auto_applicable_actions` 的关键字参数（llm_repair.py:874-882）
pub struct SelectParams<'a> {
    pub confidence_threshold: f64,
    pub chapter_unmatched_count: usize,
    pub note_system: &'a str,
    pub note_page_by_id: Option<&'a HashMap<String, i64>>,
    pub allowed_synthesize_pages: Option<&'a HashSet<i64>>,
    /// 当前 cluster 中允许 auto-apply 的 note_item_id 白名单。
    /// 空集合视为"无限制"（保留向后兼容）。
    pub allowed_note_ids: Option<HashSet<String>>,
    /// 当前 cluster 中允许 auto-apply 的 anchor_id 白名单。
    pub allowed_anchor_ids: Option<HashSet<String>>,
}

impl<'a> Default for SelectParams<'a> {
    fn default() -> Self {
        SelectParams {
            confidence_threshold: 0.9,
            chapter_unmatched_count: 0,
            note_system: "",
            note_page_by_id: None,
            allowed_synthesize_pages: None,
            allowed_note_ids: None,
            allowed_anchor_ids: None,
        }
    }
}

/// ←→ Python `select_auto_applicable_actions` (llm_repair.py:874-966)
///
/// 筛选可自动应用的 LLM 动作。
///
/// - match / ignore_ref: 沿用原门槛 confidence >= threshold + 互斥使用集合。
/// - synthesize_anchor: 追加两道门槛：
///   - fuzzy_score >= FUZZY_SCORE_THRESHOLD 且非 ambiguous
///   - 本章未匹配 note 数量 >= MIN_CHAPTER_UNMATCHED_FOR_AUTO
/// - synthesize_anchor 在 fuzzy_score >= 95 时降阈值到 0.80
pub fn select_auto_applicable_actions(
    actions: &[RepairAction],
    params: SelectParams<'_>,
) -> Vec<RepairAction> {
    let mut selected = Vec::new();
    let mut used_definitions: HashSet<String> = HashSet::new();
    let mut used_refs: HashSet<String> = HashSet::new();

    for action in actions {
        let kind = action.action.trim().to_lowercase();
        let confidence = action.confidence;
        // synthesize_anchor 在 fuzzy_score 极高时降阈值
        let effective_threshold = if kind == "synthesize_anchor" && action.fuzzy_score >= 95.0 {
            0.80
        } else {
            params.confidence_threshold
        };
        if confidence < effective_threshold {
            continue;
        }
        // 文字派生的置信度（"high"/"medium"/"low"）不进入 auto-apply（P2-5）。
        if !action.confidence_numeric {
            continue;
        }

        match kind.as_str() {
            "match" => {
                let note_item_id = action.note_item_id.trim();
                let anchor_id = action.anchor_id.trim();
                if note_item_id.is_empty() || anchor_id.is_empty() {
                    continue;
                }
                if used_definitions.contains(note_item_id) || used_refs.contains(anchor_id) {
                    continue;
                }
                // 校验 note_item_id 在 cluster 白名单内（P1-1）
                if let Some(ref allowed) = params.allowed_note_ids {
                    if !allowed.contains(note_item_id) {
                        continue;
                    }
                }
                if let Some(ref allowed) = params.allowed_anchor_ids {
                    if !allowed.contains(anchor_id) {
                        continue;
                    }
                }
                used_definitions.insert(note_item_id.to_string());
                used_refs.insert(anchor_id.to_string());
                selected.push(action.clone());
            }
            "ignore_ref" => {
                let anchor_id = action.anchor_id.trim();
                if anchor_id.is_empty() || used_refs.contains(anchor_id) {
                    continue;
                }
                if let Some(ref allowed) = params.allowed_anchor_ids {
                    if !allowed.contains(anchor_id) {
                        continue;
                    }
                }
                used_refs.insert(anchor_id.to_string());
                selected.push(action.clone());
            }
            "synthesize_anchor" => {
                let note_item_id = action.note_item_id.trim();
                if note_item_id.is_empty() || used_definitions.contains(note_item_id) {
                    continue;
                }
                if action.anchor_phrase.trim().is_empty() {
                    continue;
                }
                if action.fuzzy_score < FUZZY_SCORE_THRESHOLD {
                    continue;
                }
                if action.ambiguous {
                    continue;
                }
                if params.chapter_unmatched_count < MIN_CHAPTER_UNMATCHED_FOR_AUTO {
                    continue;
                }
                let page_no = action.page_no;
                if let Some(allowed) = params.allowed_synthesize_pages {
                    if !allowed.contains(&page_no) {
                        continue;
                    }
                }
                if params.note_system.trim().eq_ignore_ascii_case("footnote") {
                    if let Some(note_page_map) = params.note_page_by_id {
                        let note_page = note_page_map.get(note_item_id).copied().unwrap_or(0);
                        if note_page > 0
                            && page_no > 0
                            && (page_no - note_page).abs() > LLM_REPAIR_FOOTNOTE_PAGE_PADDING
                        {
                            continue;
                        }
                    }
                }
                if let Some(ref allowed) = params.allowed_note_ids {
                    if !allowed.contains(note_item_id) {
                        continue;
                    }
                }
                used_definitions.insert(note_item_id.to_string());
                selected.push(action.clone());
            }
            _ => {}
        }
    }
    selected
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_plain_array() {
        let text = r#"[{"action":"match","note_item_id":"n1","anchor_id":"a1","confidence":0.95,"reason":"ok"}]"#;
        let actions = parse_llm_repair_actions(text);
        assert_eq!(actions.len(), 1);
        assert_eq!(actions[0].action, "match");
        assert_eq!(actions[0].confidence, 0.95);
    }

    #[test]
    fn test_parse_json_block() {
        let text = "Some explanation\n```json\n[{\"action\":\"ignore_ref\",\"anchor_id\":\"a1\",\"confidence\":0.9,\"reason\":\"dup\"}]\n```\nend";
        let actions = parse_llm_repair_actions(text);
        assert_eq!(actions.len(), 1);
        assert_eq!(actions[0].action, "ignore_ref");
    }

    #[test]
    fn test_parse_actions_wrapped() {
        let text = r#"{"actions":[{"action":"needs_review","reason":"ambiguous"}]}"#;
        let actions = parse_llm_repair_actions(text);
        assert_eq!(actions.len(), 1);
        assert_eq!(actions[0].action, "needs_review");
    }

    #[test]
    fn test_parse_invalid_action_rejected() {
        let text = r#"[{"action":"delete_everything","confidence":1.0}]"#;
        let actions = parse_llm_repair_actions(text);
        assert!(actions.is_empty());
    }

    #[test]
    fn test_parse_synth_anchor_empty_phrase_rejected() {
        let text = r#"[{"action":"synthesize_anchor","note_item_id":"n1","anchor_phrase":"","confidence":0.9}]"#;
        let actions = parse_llm_repair_actions(text);
        assert!(actions.is_empty());
    }

    #[test]
    fn test_parse_confidence_label() {
        let text =
            r#"[{"action":"match","note_item_id":"n1","anchor_id":"a1","confidence":"high"}]"#;
        let actions = parse_llm_repair_actions(text);
        assert_eq!(actions.len(), 1);
        assert!((actions[0].confidence - 0.9).abs() < 1e-9);
        // 文字置信度 marked as non-numeric → 不进入 auto-apply（P2-5）
        assert!(!actions[0].confidence_numeric);
    }

    #[test]
    fn test_parse_fallback_to_bracket_extraction() {
        let text = "preface text [{\"action\":\"match\",\"note_item_id\":\"n1\",\"anchor_id\":\"a1\",\"confidence\":0.95}] trailing";
        let actions = parse_llm_repair_actions(text);
        assert_eq!(actions.len(), 1);
    }

    fn make_action(kind: &str, note_id: &str, anchor_id: &str, conf: f64) -> RepairAction {
        RepairAction {
            action: kind.to_string(),
            note_item_id: note_id.to_string(),
            anchor_id: anchor_id.to_string(),
            confidence: conf,
            confidence_numeric: true,
            ..Default::default()
        }
    }

    #[test]
    fn test_select_match_above_threshold() {
        let actions = vec![make_action("match", "n1", "a1", 0.95)];
        let selected = select_auto_applicable_actions(&actions, SelectParams::default());
        assert_eq!(selected.len(), 1);
    }

    #[test]
    fn test_select_match_below_threshold_rejected() {
        let actions = vec![make_action("match", "n1", "a1", 0.5)];
        let selected = select_auto_applicable_actions(&actions, SelectParams::default());
        assert!(selected.is_empty());
    }

    #[test]
    fn test_select_match_mutual_exclusion() {
        let actions = vec![
            make_action("match", "n1", "a1", 0.95),
            make_action("match", "n1", "a2", 0.95), // same note_id, should skip
            make_action("match", "n2", "a1", 0.95), // same anchor_id, should skip
        ];
        let selected = select_auto_applicable_actions(&actions, SelectParams::default());
        assert_eq!(selected.len(), 1);
    }

    #[test]
    fn test_select_synth_anchor_needs_fuzzy() {
        let mut action = make_action("synthesize_anchor", "n1", "", 0.95);
        action.anchor_phrase = "some phrase".into();
        action.fuzzy_score = 70.0; // below threshold
        let selected = select_auto_applicable_actions(
            &[action.clone()],
            SelectParams {
                chapter_unmatched_count: 2,
                ..Default::default()
            },
        );
        assert!(selected.is_empty(), "fuzzy < 88 must be rejected");

        let mut action = action;
        action.fuzzy_score = 92.0;
        let selected = select_auto_applicable_actions(
            &[action],
            SelectParams {
                chapter_unmatched_count: 2,
                ..Default::default()
            },
        );
        assert_eq!(selected.len(), 1);
    }

    #[test]
    fn test_select_synth_anchor_high_fuzzy_lowers_threshold() {
        let mut action = make_action("synthesize_anchor", "n1", "", 0.82);
        action.anchor_phrase = "p".into();
        action.fuzzy_score = 96.0; // >= 95 → effective threshold 0.80
        action.confidence_numeric = true;
        let selected = select_auto_applicable_actions(
            &[action],
            SelectParams {
                chapter_unmatched_count: 2,
                ..Default::default()
            },
        );
        assert_eq!(selected.len(), 1);
    }

    #[test]
    fn test_select_synth_anchor_ambiguous_rejected() {
        let mut action = make_action("synthesize_anchor", "n1", "", 0.95);
        action.anchor_phrase = "p".into();
        action.fuzzy_score = 92.0;
        action.ambiguous = true;
        let selected = select_auto_applicable_actions(
            &[action],
            SelectParams {
                chapter_unmatched_count: 2,
                ..Default::default()
            },
        );
        assert!(selected.is_empty());
    }

    #[test]
    fn test_confidence_numeric_blocks_text_based() {
        // 文字置信度一定不被 auto-apply（即使值≥threshold）。
        let mut action = make_action("match", "n1", "a1", 0.95);
        action.confidence_numeric = false;
        let selected = select_auto_applicable_actions(&[action], SelectParams::default());
        assert!(
            selected.is_empty(),
            "text-derived confidence must not auto-apply"
        );
    }

    #[test]
    fn test_match_id_whitelist_rejects_out_of_cluster() {
        let mut action = make_action("match", "n1", "a1", 0.95);
        action.confidence_numeric = true;
        let mut allowed_anchors = HashSet::new();
        allowed_anchors.insert("a2".to_string()); // a1 NOT in whitelist
        let mut allowed_notes = HashSet::new();
        allowed_notes.insert("n1".to_string());
        let selected = select_auto_applicable_actions(
            &[action],
            SelectParams {
                allowed_note_ids: Some(allowed_notes),
                allowed_anchor_ids: Some(allowed_anchors),
                ..Default::default()
            },
        );
        assert!(
            selected.is_empty(),
            "anchor_id outside whitelist must be rejected"
        );
    }

    #[test]
    fn test_match_id_whitelist_passes_in_cluster() {
        let mut action = make_action("match", "n1", "a1", 0.95);
        action.confidence_numeric = true;
        let mut allowed_anchors = HashSet::new();
        allowed_anchors.insert("a1".to_string());
        let mut allowed_notes = HashSet::new();
        allowed_notes.insert("n1".to_string());
        let selected = select_auto_applicable_actions(
            &[action],
            SelectParams {
                allowed_note_ids: Some(allowed_notes),
                allowed_anchor_ids: Some(allowed_anchors),
                ..Default::default()
            },
        );
        assert_eq!(selected.len(), 1, "IDs in whitelist must be auto-applied");
    }

    #[test]
    fn test_ignore_ref_id_whitelist_rejects_outside() {
        let mut action = make_action("ignore_ref", "", "a1", 0.95);
        action.confidence_numeric = true;
        let mut allowed = HashSet::new();
        allowed.insert("a2".into()); // a1 NOT in whitelist
        let selected = select_auto_applicable_actions(
            &[action],
            SelectParams {
                allowed_anchor_ids: Some(allowed),
                ..Default::default()
            },
        );
        assert!(
            selected.is_empty(),
            "anchor outside whitelist must be rejected"
        );
    }

    #[test]
    fn test_ignore_ref_id_whitelist_passes_in_cluster() {
        let mut action = make_action("ignore_ref", "", "a1", 0.95);
        action.confidence_numeric = true;
        let mut allowed = HashSet::new();
        allowed.insert("a1".into());
        let selected = select_auto_applicable_actions(
            &[action],
            SelectParams {
                allowed_anchor_ids: Some(allowed),
                ..Default::default()
            },
        );
        assert_eq!(
            selected.len(),
            1,
            "anchor in whitelist must be auto-applied"
        );
    }

    #[test]
    fn test_select_synth_anchor_footnote_page_padding() {
        // footnote synthesize_anchor 要求 anchor page 接近 note page
        let mut action = make_action("synthesize_anchor", "n1", "", 0.95);
        action.anchor_phrase = "p".into();
        action.fuzzy_score = 92.0;
        action.page_no = 10;
        let mut note_pages = HashMap::new();
        note_pages.insert("n1".to_string(), 20_i64); // distance 10 > padding 1
        let selected = select_auto_applicable_actions(
            &[action.clone()],
            SelectParams {
                chapter_unmatched_count: 2,
                note_system: "footnote",
                note_page_by_id: Some(&note_pages),
                ..Default::default()
            },
        );
        assert!(
            selected.is_empty(),
            "footnote with distant note page must be rejected"
        );

        // 在 padding 内的允许
        let mut note_pages = HashMap::new();
        note_pages.insert("n1".to_string(), 10_i64);
        let selected = select_auto_applicable_actions(
            &[action],
            SelectParams {
                chapter_unmatched_count: 2,
                note_system: "footnote",
                note_page_by_id: Some(&note_pages),
                ..Default::default()
            },
        );
        assert_eq!(selected.len(), 1);
    }
}

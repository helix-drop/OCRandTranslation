//! ←→ Python `FNM_RE/modules/llm_repair.py::run_llm_repair`（行 1812-2087）。
//!
//! 顶层编排：从 DB 拉取 chapters/note_items/body_anchors/note_links → build_unresolved_clusters →
//! 逐 cluster 构建 page_contexts + chapter_body_text → 调 LLM → 解析 actions →
//! 物化 review_overrides（auto_apply=true 时）→ 汇总指标。

use anyhow::Result;
use fnm_core::db::Repository;
use fnm_core::note_marker::normalize_note_marker;
use fnm_phase1::input::RawPage;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

use crate::cluster::{build_unresolved_clusters, index_by_key};
use crate::constants::LLM_REPAIR_USAGE_STAGE;
use crate::llm_client::{request_llm_repair_actions, RepairRequestParams, TraceCallback};
use crate::override_materializer::{
    chapter_for_cluster, enrich_synthesize_anchor_actions, find_link_id_for_ignore,
    find_link_id_for_match, prefilter_duplicate_anchors, resolve_chapter_id_for_page, slug_token,
};
use crate::page_context::{
    build_chapter_body_text, build_cluster_page_contexts, fnm_page_role_by_no, RepairImageRenderer,
};
use crate::response_parser::{select_auto_applicable_actions, RepairAction, SelectParams};
use crate::usage::{safe_float, summarize_usage_events};

/// `run_llm_repair` 参数（与 Python kwargs 对齐）。
///
/// ←→ Python `run_llm_repair` (llm_repair.py:1812-1825)
pub struct RunLlmRepairParams<'a> {
    pub doc_id: &'a str,
    pub repo: &'a dyn Repository,
    pub raw_pages: &'a [RawPage],
    pub pdf_path: &'a str,
    pub renderer: &'a dyn RepairImageRenderer,
    pub slug: &'a str,
    pub cluster_limit: Option<usize>,
    pub auto_apply: bool,
    pub confidence_threshold: f64,
    pub model_args: Option<Value>,
    pub max_matched_examples: Option<usize>,
    pub max_unmatched_note_items: Option<usize>,
    pub max_unmatched_anchors: Option<usize>,
    pub clear_materialized_overrides: bool,
    pub trace_callback: Option<TraceCallback<'a>>,
}

impl<'a> RunLlmRepairParams<'a> {
    /// 构造默认参数。默认值对齐 Python `run_llm_repair` kwargs 默认值
    /// （llm_repair.py:1812-1825）：`slug=""`、`cluster_limit=None`、
    /// `auto_apply=True`、`confidence_threshold=0.9`、
    /// `clear_materialized_overrides=True`，其余可选。
    ///
    /// ←→ Python `run_llm_repair` kwargs 默认值（llm_repair.py:1812-1825）
    pub fn new(
        doc_id: &'a str,
        repo: &'a dyn Repository,
        raw_pages: &'a [RawPage],
        pdf_path: &'a str,
        renderer: &'a dyn RepairImageRenderer,
    ) -> Self {
        Self {
            doc_id,
            repo,
            raw_pages,
            pdf_path,
            renderer,
            slug: "",
            cluster_limit: None,
            auto_apply: true,
            confidence_threshold: 0.9,
            model_args: None,
            max_matched_examples: None,
            max_unmatched_note_items: None,
            max_unmatched_anchors: None,
            clear_materialized_overrides: true,
            trace_callback: None,
        }
    }
}

/// `run_llm_repair` 返回结果
///
/// ←→ Python `run_llm_repair` 返回 dict (llm_repair.py:2077-2087)
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
pub struct LlmRepairReport {
    pub cluster_count: usize,
    pub suggestion_count: usize,
    pub auto_applied_count: usize,
    pub suggestions: Vec<Value>,
    pub auto_applied: Vec<Value>,
    pub request_metrics: Vec<Value>,
    pub token_accounting: Vec<Value>,
    pub llm_traces: Vec<Value>,
    pub usage_summary: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    pub clusters_completed: usize,
}

fn record_to_value<T: serde::Serialize>(record: &T) -> Value {
    serde_json::to_value(record).unwrap_or(Value::Null)
}

fn str_field(value: &Value, key: &str) -> String {
    value
        .get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string()
}

fn i64_field(value: &Value, key: &str) -> i64 {
    value.get(key).and_then(|v| v.as_i64()).unwrap_or(0)
}

/// ←→ Python `run_llm_repair` (llm_repair.py:1812-2087)
///
/// Async 编排顶层；同步调用方可用 `tokio::runtime::Runtime::block_on`。
pub async fn run_llm_repair(params: RunLlmRepairParams<'_>) -> Result<LlmRepairReport> {
    let doc_id = params.doc_id;
    let repo = params.repo;
    let raw_pages = params.raw_pages;
    let pdf_path = params.pdf_path;
    let renderer = params.renderer;

    // 1. 拉取上游数据 + 索引
    let chapters_raw = repo.list_fnm_chapters(doc_id)?;
    let note_items_raw = repo.list_fnm_note_items(doc_id)?;
    let body_anchors_raw = repo.list_fnm_body_anchors(doc_id)?;
    let links_raw = repo.list_fnm_note_links(doc_id)?;

    let chapters_plain: Vec<Value> = chapters_raw.iter().map(record_to_value).collect();
    let note_items_plain: Vec<Value> = note_items_raw.iter().map(record_to_value).collect();
    let body_anchors_plain: Vec<Value> = body_anchors_raw.iter().map(record_to_value).collect();
    let links_plain: Vec<Value> = links_raw.iter().map(record_to_value).collect();

    let note_items_by_id = index_by_key(&note_items_plain, "note_item_id");

    // 2. 构建未解析簇
    let mut clusters = build_unresolved_clusters(
        &chapters_plain,
        &note_items_plain,
        &body_anchors_plain,
        &links_plain,
    );
    if let Some(limit) = params.cluster_limit {
        if limit > 0 {
            clusters.truncate(limit);
        }
    }

    if params.clear_materialized_overrides {
        repo.clear_fnm_review_overrides_v2(doc_id, Some("llm_suggestion"))?;
    }

    let mut suggestions: Vec<Value> = Vec::new();
    let mut auto_applied: Vec<Value> = Vec::new();
    let mut request_metrics_log: Vec<Value> = Vec::new();
    let mut llm_traces: Vec<Value> = Vec::new();
    let mut usage_events: Vec<Value> = Vec::new();
    let mut token_accounting_log: Vec<Value> = Vec::new();

    // 3. 预缓存页面角色（跨 cluster 不变）
    let cached_page_roles = fnm_page_role_by_no(doc_id, repo);

    let cluster_count = clusters.len();
    let mut clusters_completed: usize = 0;
    let mut fatal_error: Option<String> = None;
    // 4. 逐 cluster 处理
    for (cluster_index, mut cluster) in clusters.into_iter().enumerate() {
        let cluster_index = cluster_index + 1;
        // 4a. 构建 page_contexts + chapter_body_text
        let page_contexts = build_cluster_page_contexts(&cluster, raw_pages, pdf_path);
        let chapter_for_body = chapter_for_cluster(&cluster, &chapters_plain);
        let (chapter_body_text, body_spans) = build_chapter_body_text(
            &chapter_for_body,
            raw_pages,
            Some(&cached_page_roles),
            Some(&page_contexts),
        );
        cluster["page_contexts"] = Value::Array(page_contexts);
        cluster["chapter_body_text"] = Value::String(chapter_body_text);

        // 4b. 启发式预过滤同页同 marker 重复 anchor
        prefilter_duplicate_anchors(&mut cluster);
        let has_anchors = cluster
            .get("unmatched_anchors")
            .and_then(|v| v.as_array())
            .map(|a| !a.is_empty())
            .unwrap_or(false);
        let has_notes = cluster
            .get("unmatched_note_items")
            .and_then(|v| v.as_array())
            .map(|a| !a.is_empty())
            .unwrap_or(false);
        if !has_anchors && !has_notes {
            clusters_completed += 1;
            continue;
        }

        // 4c. 调 LLM
        let llm_request = RepairRequestParams {
            cluster: &cluster,
            model_args: params.model_args.clone(),
            max_matched_examples: params.max_matched_examples,
            max_unmatched_note_items: params.max_unmatched_note_items,
            max_unmatched_anchors: params.max_unmatched_anchors,
            doc_id,
            slug: params.slug,
            trace_callback: params.trace_callback,
            renderer,
        };
        let llm_result = match request_llm_repair_actions(llm_request).await {
            Ok(r) => r,
            Err(e) => {
                fatal_error = Some(format!("cluster {cluster_index}/{cluster_count} 失败: {e}"));
                break;
            }
        };

        // 4d. 富化 synthesize_anchor 动作（fuzzy_score + page_no + char_offsets）
        let enriched_actions =
            enrich_synthesize_anchor_actions(llm_result.actions, &cluster, &body_spans);

        // 解构 owned llm_result，避免多次 clone
        let crate::llm_client::RepairCallResult {
            request_metrics,
            token_accounting,
            usage_event,
            llm_trace,
            ..
        } = llm_result;
        request_metrics_log.push(request_metrics);
        if !matches!(&token_accounting, Value::Null) {
            token_accounting_log.push(token_accounting);
        }
        if usage_event
            .as_object()
            .map(|o| !o.is_empty())
            .unwrap_or(false)
        {
            usage_events.push(usage_event);
        }
        if !matches!(&llm_trace, Value::Null) {
            llm_traces.push(llm_trace);
        }

        // 4e. 准备 select_auto_applicable_actions 参数
        let note_page_by_id: HashMap<String, i64> = cluster
            .get("unmatched_note_items")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|item| {
                        let id = str_field(item, "note_item_id");
                        if id.is_empty() {
                            None
                        } else {
                            Some((id, i64_field(item, "page_no")))
                        }
                    })
                    .collect()
            })
            .unwrap_or_default();
        let note_system = {
            let s = str_field(&cluster, "note_system");
            if s.is_empty() {
                "endnote".to_string()
            } else {
                s
            }
        };
        let allowed_synthesize_pages: HashSet<i64> = cluster
            .get("page_contexts")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .map(|item| i64_field(item, "page_no"))
                    .filter(|p| *p > 0)
                    .collect()
            })
            .unwrap_or_default();
        let chapter_unmatched_count = cluster
            .get("unmatched_note_items")
            .and_then(|v| v.as_array())
            .map(|a| a.len())
            .unwrap_or(0);
        // 收集当前 cluster 允许的 note_item_id 和 anchor_id 白名单（P1-1）
        let allowed_note_ids: Option<HashSet<String>> = cluster
            .get("unmatched_note_items")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|item| {
                        let id = str_field(item, "note_item_id");
                        if id.is_empty() {
                            None
                        } else {
                            Some(id)
                        }
                    })
                    .collect()
            });
        let allowed_anchor_ids: Option<HashSet<String>> = cluster
            .get("unmatched_anchors")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|item| {
                        let id = str_field(item, "anchor_id");
                        if id.is_empty() {
                            None
                        } else {
                            Some(id)
                        }
                    })
                    .collect()
            });
        let select_params = SelectParams {
            confidence_threshold: params.confidence_threshold,
            chapter_unmatched_count,
            note_system: &note_system,
            note_page_by_id: Some(&note_page_by_id),
            allowed_synthesize_pages: if note_system == "endnote"
                && !allowed_synthesize_pages.is_empty()
            {
                Some(&allowed_synthesize_pages)
            } else {
                None
            },
            allowed_note_ids,
            allowed_anchor_ids,
        };
        // select_auto_applicable_actions 借用 enriched_actions
        let auto_actions = select_auto_applicable_actions(&enriched_actions, select_params);
        let auto_set: HashSet<usize> = enriched_actions
            .iter()
            .enumerate()
            .filter_map(|(i, a)| {
                if auto_actions.iter().any(|aa| action_eq(aa, a)) {
                    Some(i)
                } else {
                    None
                }
            })
            .collect();

        // 4f. 逐 action 生成 suggestion + 收集 overrides
        let mut cluster_overrides: Vec<(String, String, Value)> = Vec::new();
        for (action_index, action) in enriched_actions.iter().enumerate() {
            let suggestion_id = format!("llm-{cluster_index:02}-{:03}", action_index + 1);
            let auto_selected = auto_set.contains(&action_index);
            let payload = build_suggestion_payload(&cluster, action, auto_selected);
            // 一次构造，分别 push 到 overrides 和 suggestions
            let mut entry = payload.clone();
            entry.as_object_mut().unwrap().insert(
                "suggestion_id".to_string(),
                Value::String(suggestion_id.clone()),
            );
            suggestions.push(entry);
            cluster_overrides.push(("llm_suggestion".to_string(), suggestion_id, payload));
        }

        // ←→ Python `run_llm_repair` (llm_repair.py:1953-1954)：auto_apply=false 时
        // 仅累积 suggestions，**不持久化任何 override**（保持 review queue 不被污染）。
        // 早期 Rust 实现错误地仍 batch_save 了 suggestion 行，已修正为与 Python `continue` 一致。
        if !params.auto_apply {
            continue;
        }

        // 4g. 物化为 review_overrides
        let mut used_synth_positions: HashSet<(String, i64, i64, i64)> = HashSet::new();
        for action in &auto_actions {
            apply_action(
                action,
                &cluster,
                &chapters_plain,
                &note_items_by_id,
                &links_plain,
                &note_system,
                &mut used_synth_positions,
                &mut cluster_overrides,
                &mut auto_applied,
            );
        }

        // ←→ 为预过滤的重复 anchor 生成 ignore_ref override（P1-2）
        if let Some(prefiltered) = cluster
            .get("_prefiltered_anchors")
            .and_then(|v| v.as_array())
        {
            for anchor in prefiltered {
                let anchor_id = str_field(anchor, "anchor_id");
                if anchor_id.is_empty() {
                    continue;
                }
                let link_id = find_link_id_for_ignore(&links_plain, &anchor_id);
                if !link_id.is_empty() {
                    cluster_overrides.push((
                        "link".to_string(),
                        link_id.clone(),
                        json!({
                            "action": "ignore_ref",
                            "anchor_id": anchor_id,
                            "source": "llm",
                        }),
                    ));
                }
            }
        }

        // 4h. 批量提交本 cluster overrides
        if !cluster_overrides.is_empty() {
            repo.batch_save_fnm_review_overrides_v2(doc_id, &cluster_overrides)?;
        }
        clusters_completed += 1;
    }

    let usage_summary = serde_json::to_value(summarize_usage_events(
        Some(&usage_events),
        &[LLM_REPAIR_USAGE_STAGE],
    ))?;

    Ok(LlmRepairReport {
        cluster_count,
        suggestion_count: suggestions.len(),
        auto_applied_count: auto_applied.len(),
        suggestions,
        auto_applied,
        request_metrics: request_metrics_log,
        token_accounting: token_accounting_log,
        llm_traces,
        usage_summary,
        error: fatal_error,
        clusters_completed,
    })
}

/// suggestion / override 共用的 payload 构造。
fn build_suggestion_payload(cluster: &Value, action: &RepairAction, auto_selected: bool) -> Value {
    json!({
        "cluster_id": cluster.get("cluster_id").cloned().unwrap_or(Value::Null),
        "chapter_id": cluster.get("chapter_id").cloned().unwrap_or(Value::Null),
        "chapter_title": cluster.get("chapter_title").cloned().unwrap_or(Value::Null),
        "action": action.action,
        "note_item_id": action.note_item_id,
        "anchor_id": action.anchor_id,
        "anchor_phrase": action.anchor_phrase,
        "marker": action.marker,
        "note_text": action.note_text,
        "fuzzy_score": action.fuzzy_score,
        "ambiguous": action.ambiguous,
        "confidence": action.confidence,
        "reason": action.reason,
        "auto_selected": auto_selected,
    })
}

/// 物化单个 auto action 为 override（match / ignore_ref / synthesize_anchor）。
///
/// ←→ Python `run_llm_repair` 行 1959-2071 的 match 主体
#[allow(clippy::too_many_arguments)]
fn apply_action(
    action: &RepairAction,
    cluster: &Value,
    chapters_plain: &[Value],
    note_items_by_id: &HashMap<String, Value>,
    links_plain: &[Value],
    note_system: &str,
    used_synth_positions: &mut HashSet<(String, i64, i64, i64)>,
    cluster_overrides: &mut Vec<(String, String, Value)>,
    auto_applied: &mut Vec<Value>,
) {
    match action.action.as_str() {
        "match" => {
            let note_item_id = action.note_item_id.trim();
            let anchor_id = action.anchor_id.trim();
            let link_id = find_link_id_for_match(links_plain, note_item_id, anchor_id);
            if link_id.is_empty() {
                return;
            }
            cluster_overrides.push((
                "link".to_string(),
                link_id.clone(),
                json!({
                    "action": "match",
                    "note_item_id": note_item_id,
                    "anchor_id": anchor_id,
                }),
            ));
            auto_applied.push(merge_action_with(action, json!({"link_id": link_id})));
        }
        "ignore_ref" => {
            let anchor_id = action.anchor_id.trim();
            let link_id = find_link_id_for_ignore(links_plain, anchor_id);
            if link_id.is_empty() {
                return;
            }
            cluster_overrides.push((
                "link".to_string(),
                link_id.clone(),
                json!({"action": "ignore"}),
            ));
            auto_applied.push(merge_action_with(action, json!({"link_id": link_id})));
        }
        "synthesize_anchor" => apply_synthesize_anchor(
            action,
            cluster,
            chapters_plain,
            note_items_by_id,
            links_plain,
            note_system,
            used_synth_positions,
            cluster_overrides,
            auto_applied,
        ),
        // synthesize_note_item 已被移除（P0-2）——Phase3.5 无权创建 note item。
        // 即使 LLM 返回了此 action，也不物化 override，仅记录 warning。
        "synthesize_note_item" => {
            eprintln!(
                "  [WARNING] synthesize_note_item action ignored: \
                 note_item_id={}, anchor_id={}, reason={}",
                action.note_item_id, action.anchor_id, action.reason,
            );
        }
        _ => {}
    }
}

#[allow(clippy::too_many_arguments)]
fn apply_synthesize_anchor(
    action: &RepairAction,
    cluster: &Value,
    chapters_plain: &[Value],
    note_items_by_id: &HashMap<String, Value>,
    links_plain: &[Value],
    note_system: &str,
    used_synth_positions: &mut HashSet<(String, i64, i64, i64)>,
    cluster_overrides: &mut Vec<(String, String, Value)>,
    auto_applied: &mut Vec<Value>,
) {
    let note_item_id = action.note_item_id.trim().to_string();
    let Some(note_item) = note_items_by_id.get(&note_item_id) else {
        return;
    };
    let page_no_value = if action.page_no > 0 {
        action.page_no
    } else {
        i64_field(note_item, "page_no")
    };
    let chapter_id = {
        let from_cluster = str_field(cluster, "chapter_id");
        if !from_cluster.is_empty() {
            from_cluster
        } else {
            let from_note = str_field(note_item, "chapter_id");
            if !from_note.is_empty() {
                from_note
            } else {
                resolve_chapter_id_for_page(chapters_plain, page_no_value)
            }
        }
    };
    if chapter_id.is_empty() || page_no_value <= 0 {
        return;
    }
    let marker = normalize_note_marker(&{
        let m = str_field(note_item, "marker");
        if m.is_empty() {
            action.marker.clone()
        } else {
            m
        }
    });
    if marker.is_empty() {
        return;
    }
    let anchor_id = format!("llm-anchor-{}", slug_token(&note_item_id));
    let char_start = action.char_start;
    if char_start < 0 {
        return;
    }
    let char_end = if action.char_end > char_start {
        action.char_end
    } else {
        char_start + 1
    };
    let pos_key = (
        chapter_id.clone(),
        page_no_value,
        char_start.max(0),
        char_end.max(char_start + 1),
    );
    if used_synth_positions.contains(&pos_key) {
        return;
    }
    used_synth_positions.insert(pos_key);
    let matched_text = if !action.matched_text.trim().is_empty() {
        action.matched_text.trim().to_string()
    } else {
        action.anchor_phrase.trim().to_string()
    };
    if matched_text.is_empty() {
        return;
    }
    cluster_overrides.push((
        "anchor".to_string(),
        anchor_id.clone(),
        json!({
            "action": "create",
            "anchor_id": anchor_id,
            "chapter_id": chapter_id,
            "page_no": page_no_value,
            "paragraph_index": 0,
            "char_start": char_start.max(0),
            "char_end": char_end.max(char_start + 1),
            "source_text": matched_text,
            "source_marker": marker,
            "normalized_marker": marker,
            "anchor_kind": note_system,
            "certainty": safe_float(&json!(action.confidence), 0.8),
            "source": "llm",
            "synthetic": false,
        }),
    ));
    let link_id = find_link_id_for_match(links_plain, &note_item_id, "");
    if !link_id.is_empty() {
        cluster_overrides.push((
            "link".to_string(),
            link_id.clone(),
            json!({
                "action": "match",
                "note_item_id": note_item_id,
                "anchor_id": anchor_id,
            }),
        ));
    }
    auto_applied.push(merge_action_with(
        action,
        json!({"link_id": link_id, "anchor_id": anchor_id}),
    ));
}

/// 两个 action 是否等价（不含富化后的运行时字段）。仅用于 auto_set 索引。
pub(crate) fn action_eq(a: &RepairAction, b: &RepairAction) -> bool {
    a.action == b.action
        && a.note_item_id == b.note_item_id
        && a.anchor_id == b.anchor_id
        && a.anchor_phrase == b.anchor_phrase
        && a.marker == b.marker
        && (a.confidence - b.confidence).abs() < 1e-9
}

/// 把 extra 字段 merge 到 action 的 JSON 表示上（auto_applied 用）。
pub(crate) fn merge_action_with(action: &RepairAction, extra: Value) -> Value {
    let mut value = serde_json::to_value(action).unwrap_or(Value::Null);
    if let (Value::Object(target), Value::Object(src)) = (&mut value, extra) {
        for (k, v) in src {
            target.insert(k, v);
        }
    }
    value
}

// ── 单元测试：纯函数 ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_action_eq_distinguishes_action_type() {
        let a = RepairAction {
            action: "match".into(),
            note_item_id: "n1".into(),
            anchor_id: "a1".into(),
            confidence: 0.95,
            ..Default::default()
        };
        let mut b = a.clone();
        assert!(action_eq(&a, &b));
        b.action = "ignore_ref".into();
        assert!(!action_eq(&a, &b));
    }

    #[test]
    fn test_merge_action_with_extra_overrides() {
        let action = RepairAction {
            action: "match".into(),
            ..Default::default()
        };
        let merged = merge_action_with(&action, json!({"link_id": "L42"}));
        assert_eq!(merged["link_id"], "L42");
        assert_eq!(merged["action"], "match");
    }
}

//! ←→ Python `FNM_RE/modules/llm_repair.py` LLM 客户端层（行 59-1641）。
//!
//! 拆分为：
//! - `mod.rs`（本文件）—— 类型契约 + trace/metrics 辅助函数 + model spec 解析
//! - `request.rs` —— `request_llm_repair_actions` 顶层 + provider HTTP 调用 + 内容审核回退

use fnm_core::vision::{resolve_fnm_repair_model_specs, ResolvedModelSpec};
use serde_json::{json, Value};

use crate::constants::{
    LLM_REPAIR_SOFT_INPUT_TOKEN_BUDGET, QWEN35_PLUS_MAX_INPUT_TOKENS_NO_THINK,
    QWEN35_PLUS_MAX_INPUT_TOKENS_THINKING,
};
use crate::page_context::RepairImageRenderer;
use crate::prompt_builder::estimate_prompt_tokens;
use crate::response_parser::RepairAction;
use crate::usage::coerce_usage_int;

pub mod error;
pub mod request;

pub use error::{
    classify_provider_error, extract_provider_error_detail, parse_retry_after_seconds,
    ProviderError,
};
pub use request::request_llm_repair_actions;

/// Trace 回调（用户可注入观测点）
///
/// ←→ Python `trace_callback` 参数（llm_repair.py:1347-1353）
pub type TraceCallback<'a> = &'a dyn Fn(Value) -> Result<(), String>;

/// ←→ Python `_emit_llm_trace` (llm_repair.py:1347-1353)
pub fn emit_llm_trace(trace_callback: Option<TraceCallback<'_>>, trace: &Value) {
    let Some(cb) = trace_callback else { return };
    if let Err(e) = cb(trace.clone()) {
        // trace callback 失败时记录日志，不阻断主流程
        tracing::warn!("trace callback error: {}", e);
    }
}

/// `request_llm_repair_actions` 返回的结果
///
/// ←→ Python `request_llm_repair_actions` 返回 dict（llm_repair.py:1633-1641）
#[derive(Debug, Clone, Default)]
pub struct RepairCallResult {
    pub raw_text: String,
    pub usage: Value,
    pub usage_event: Value,
    pub actions: Vec<RepairAction>,
    pub request_metrics: Value,
    pub token_accounting: Value,
    pub llm_trace: Value,
    pub skipped: bool,
}

/// `request_llm_repair_actions` 参数包
///
/// ←→ Python `request_llm_repair_actions` 函数签名（llm_repair.py:1356-1366）
pub struct RepairRequestParams<'a> {
    pub cluster: &'a Value,
    pub model_args: Option<Value>,
    pub max_matched_examples: Option<usize>,
    pub max_unmatched_note_items: Option<usize>,
    pub max_unmatched_anchors: Option<usize>,
    pub doc_id: &'a str,
    pub slug: &'a str,
    pub trace_callback: Option<TraceCallback<'a>>,
    pub renderer: &'a dyn RepairImageRenderer,
}

// ── model spec 解析 ────────────────────────────────────────────

/// ←→ Python `_resolved_spec_to_model_args` (llm_repair.py:969-977)
///
/// 把 `ResolvedModelSpec` 摊平成 JSON dict（与 Python kwargs 一致）。
pub fn resolved_spec_to_model_args(spec: &ResolvedModelSpec) -> Value {
    json!({
        "provider": spec.provider.trim(),
        "model_id": spec.model_id.trim(),
        "api_key": spec.api_key.trim(),
        "base_url": spec.base_url.trim(),
        "supports_vision": spec.supports_vision,
        "request_overrides": spec.request_overrides.clone(),
        "display_label": if spec.display_label.trim().is_empty() {
            spec.model_id.trim()
        } else {
            spec.display_label.trim()
        },
    })
}

/// ←→ Python `_resolve_repair_model_args` (llm_repair.py:980-988)
///
/// 返回主模型参数（向后兼容；其它路径用 `resolve_all_repair_model_args`）。
pub fn resolve_repair_model_args() -> anyhow::Result<Value> {
    let specs = resolve_fnm_repair_model_specs(false);
    let Some(first) = specs.first() else {
        anyhow::bail!("未配置可用的 FNM 视觉与修补模型");
    };
    if first.api_key.trim().is_empty() {
        anyhow::bail!("当前 FNM 视觉与修补模型缺少 API Key");
    }
    Ok(resolved_spec_to_model_args(first))
}

/// ←→ Python `_resolve_all_repair_model_args` (llm_repair.py:991-1001)
pub fn resolve_all_repair_model_args() -> anyhow::Result<Vec<Value>> {
    let specs = resolve_fnm_repair_model_specs(false);
    let mut result: Vec<Value> = Vec::new();
    for spec in &specs {
        if spec.api_key.trim().is_empty() {
            continue;
        }
        result.push(resolved_spec_to_model_args(spec));
    }
    if result.is_empty() {
        anyhow::bail!("未配置可用的 FNM 视觉与修补模型（所有槽位均无 API Key）");
    }
    Ok(result)
}

// ── trace / metrics 辅助 ───────────────────────────────────────

/// ←→ Python `_request_metrics_for_cluster` (llm_repair.py:1266-1297)
pub fn request_metrics_for_cluster(
    cluster: &Value,
    request_cluster: &Value,
    system_prompt: &str,
    user_prompt: &str,
    image_refused: bool,
    skipped: bool,
    skip_reason: &str,
) -> Value {
    let me = array_len(request_cluster, "matched_examples");
    let uni = array_len(request_cluster, "unmatched_note_items");
    let ua = array_len(request_cluster, "unmatched_anchors");
    let pc = array_len(request_cluster, "page_contexts");
    let cme = array_len(cluster, "matched_examples");
    let cuni = array_len(cluster, "unmatched_note_items");
    let cua = array_len(cluster, "unmatched_anchors");
    let truncated = me < cme || uni < cuni || ua < cua;
    json!({
        "cluster_id": cluster.get("cluster_id").and_then(|v| v.as_str()).unwrap_or(""),
        "request_mode": request_cluster.get("request_mode").and_then(|v| v.as_str()).unwrap_or(""),
        "allowed_actions": request_cluster.get("allowed_actions").cloned().unwrap_or(Value::Array(vec![])),
        "chars": system_prompt.len() + user_prompt.len(),
        "estimated_prompt_tokens": estimate_prompt_tokens(system_prompt) + estimate_prompt_tokens(user_prompt),
        "soft_input_token_budget": LLM_REPAIR_SOFT_INPUT_TOKEN_BUDGET,
        "model_max_input_tokens_thinking": QWEN35_PLUS_MAX_INPUT_TOKENS_THINKING,
        "model_max_input_tokens_no_think": QWEN35_PLUS_MAX_INPUT_TOKENS_NO_THINK,
        "matched_examples": me,
        "unmatched_note_items": uni,
        "unmatched_anchors": ua,
        "page_context_count": pc,
        "image_refused": image_refused,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "truncated": truncated,
    })
}

fn array_len(value: &Value, key: &str) -> usize {
    value
        .get(key)
        .and_then(|v| v.as_array())
        .map(|a| a.len())
        .unwrap_or(0)
}

/// ←→ Python `_token_accounting_for_request` (llm_repair.py:1300-1329)
pub fn token_accounting_for_request(
    usage: Option<&Value>,
    request_metrics: Option<&Value>,
    skipped: bool,
    skip_reason: &str,
) -> Value {
    let input_tokens = field_int(usage, "prompt_tokens");
    let output_tokens = field_int(usage, "completion_tokens");
    let mut total_tokens = field_int(usage, "total_tokens");
    if total_tokens <= 0 && (input_tokens > 0 || output_tokens > 0) {
        total_tokens = input_tokens + output_tokens;
    }
    let request_count = field_int(usage, "request_count").max(0);
    let (input, output, total, request_count) = if skipped {
        (0, 0, 0, 0)
    } else {
        (input_tokens, output_tokens, total_tokens, request_count)
    };
    let estimated_input = field_int(request_metrics, "estimated_prompt_tokens");
    let source = if skipped {
        "skipped"
    } else if usage.is_some() && !matches!(usage, Some(Value::Null)) {
        "provider_usage"
    } else {
        "local_estimate"
    };
    json!({
        "request_count": request_count,
        "input_tokens": input,
        "output_tokens": output,
        "total_tokens": total,
        "estimated_input_tokens": estimated_input,
        "source": source,
        "skipped": skipped,
        "skip_reason": skip_reason,
    })
}

fn field_int(value: Option<&Value>, key: &str) -> i64 {
    value
        .and_then(|u| u.get(key))
        .map(coerce_usage_int)
        .unwrap_or(0)
}

/// ←→ Python `_compact_cluster_for_trace` (llm_repair.py:1332-1344)
pub fn compact_cluster_for_trace(request_cluster: &Value) -> Value {
    json!({
        "cluster_id": request_cluster.get("cluster_id").and_then(|v| v.as_str()).unwrap_or(""),
        "chapter_title": request_cluster.get("chapter_title").and_then(|v| v.as_str()).unwrap_or(""),
        "request_mode": request_cluster.get("request_mode").and_then(|v| v.as_str()).unwrap_or(""),
        "allowed_actions": request_cluster.get("allowed_actions").cloned().unwrap_or(Value::Array(vec![])),
        "note_system": request_cluster.get("note_system").and_then(|v| v.as_str()).unwrap_or(""),
        "page_range": [
            request_cluster.get("page_start").cloned().unwrap_or(Value::Null),
            request_cluster.get("page_end").cloned().unwrap_or(Value::Null),
        ],
        "matched_examples": request_cluster.get("matched_examples").cloned().unwrap_or(Value::Array(vec![])),
        "unmatched_note_items": request_cluster.get("unmatched_note_items").cloned().unwrap_or(Value::Array(vec![])),
        "unmatched_anchors": request_cluster.get("unmatched_anchors").cloned().unwrap_or(Value::Array(vec![])),
        "rebind_candidates": request_cluster.get("rebind_candidates").cloned().unwrap_or(Value::Array(vec![])),
    })
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_resolved_spec_to_model_args() {
        let spec = ResolvedModelSpec {
            provider: "qwen".to_string(),
            model_id: "qwen3.5-vl-plus".to_string(),
            base_url: "https://api.qwen".to_string(),
            api_key: "key123".to_string(),
            display_label: "Qwen VL".to_string(),
            supports_vision: true,
            request_overrides: json!({"extra_body": {"enable_thinking": false}}),
            ..Default::default()
        };
        let args = resolved_spec_to_model_args(&spec);
        assert_eq!(args["provider"], "qwen");
        assert_eq!(args["model_id"], "qwen3.5-vl-plus");
        assert_eq!(args["api_key"], "key123");
        assert_eq!(args["supports_vision"], true);
        assert_eq!(
            args["request_overrides"]["extra_body"]["enable_thinking"],
            false
        );
    }

    #[test]
    fn test_request_metrics_basic() {
        let cluster = json!({"cluster_id": "C1", "matched_examples": [{}, {}, {}]});
        let request = json!({
            "request_mode": "paired",
            "allowed_actions": ["match"],
            "matched_examples": [{}, {}],
            "unmatched_note_items": [{}],
            "unmatched_anchors": [{}],
            "page_contexts": [],
        });
        let m = request_metrics_for_cluster(&cluster, &request, "sys", "usr", false, false, "");
        assert_eq!(m["cluster_id"], "C1");
        assert_eq!(m["matched_examples"], 2);
        // truncated: cluster has 3 matched_examples, request only 2 → truncated true
        assert_eq!(m["truncated"], true);
    }

    #[test]
    fn test_token_accounting_skipped() {
        let acc = token_accounting_for_request(None, None, true, "no_actionable_auto_repair");
        assert_eq!(acc["input_tokens"], 0);
        assert_eq!(acc["skipped"], true);
        assert_eq!(acc["source"], "skipped");
    }

    #[test]
    fn test_token_accounting_provider_usage() {
        let usage = json!({
            "request_count": 1,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        });
        let acc = token_accounting_for_request(Some(&usage), None, false, "");
        assert_eq!(acc["input_tokens"], 100);
        assert_eq!(acc["output_tokens"], 50);
        assert_eq!(acc["total_tokens"], 150);
        assert_eq!(acc["source"], "provider_usage");
    }

    #[test]
    fn test_token_accounting_total_derived_when_missing() {
        let usage = json!({
            "request_count": 1,
            "prompt_tokens": 30,
            "completion_tokens": 12,
        });
        let acc = token_accounting_for_request(Some(&usage), None, false, "");
        assert_eq!(acc["total_tokens"], 42);
    }

    #[test]
    fn test_compact_cluster_for_trace() {
        let request = json!({
            "cluster_id": "C1",
            "chapter_title": "Title",
            "request_mode": "paired",
            "note_system": "endnote",
            "page_start": 5,
            "page_end": 10,
        });
        let c = compact_cluster_for_trace(&request);
        assert_eq!(c["cluster_id"], "C1");
        assert_eq!(c["page_range"][0], 5);
        assert_eq!(c["page_range"][1], 10);
    }

    #[test]
    fn test_emit_llm_trace_invokes_callback() {
        use std::cell::RefCell;
        let captured: RefCell<Option<Value>> = RefCell::new(None);
        let cb = |t: Value| -> Result<(), String> {
            *captured.borrow_mut() = Some(t);
            Ok(())
        };
        emit_llm_trace(Some(&cb), &json!({"stage": "test"}));
        assert_eq!(captured.borrow().as_ref().unwrap()["stage"], "test");
    }

    #[test]
    fn test_emit_llm_trace_no_callback_is_noop() {
        emit_llm_trace(None, &json!({"stage": "test"}));
    }
}

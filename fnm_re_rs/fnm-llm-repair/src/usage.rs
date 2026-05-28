//! ←→ Python `FNM_RE/modules/llm_repair.py` 用量统计（行 93-173）。
//!
//! 4 个函数：
//! - `safe_float` ←→ `_safe_float`
//! - `coerce_usage_int` ←→ `_coerce_usage_int`
//! - `compact_usage_context` ←→ `_compact_usage_context`
//! - `summarize_usage_events` ←→ `_summarize_usage_events`
//!
//! # 不 port 的 Python helper
//!
//! Python `_time_limit`（行 177-194，contextmanager）通过 `signal.SIGALRM` 在主线程
//! 强制中断 LLM 请求。Rust 端用 `reqwest::RequestBuilder::timeout(Duration::from_secs(60))`
//! 在 IO 层实现等价的 60s 超时保护（见 `llm_client/request.rs::call_provider`）。
//! 用 `std::thread::spawn + mpsc::recv_timeout` 模拟 SIGALRM 会泄漏阻塞线程，
//! 故选择不复现 `_time_limit`。

use serde_json::{Map, Value};
use std::collections::BTreeMap;

/// ←→ Python `_safe_float` (llm_repair.py:93-107)
///
/// 安全转换 float，只接受数值类型和可解析为数值的字符串。
/// 文字标签（如 "high", "medium"）不再转换为数值，直接返回 default。
pub fn safe_float(value: &Value, default: f64) -> f64 {
    if let Some(f) = value.as_f64() {
        return f;
    }
    if let Some(i) = value.as_i64() {
        return i as f64;
    }
    if let Some(u) = value.as_u64() {
        return u as f64;
    }
    if let Some(b) = value.as_bool() {
        return if b { 1.0 } else { 0.0 };
    }
    if let Some(text) = value.as_str() {
        if let Ok(f) = text.trim().parse::<f64>() {
            return f;
        }
    }
    default
}

/// ←→ Python `_coerce_usage_int` (llm_repair.py:110-114)
pub fn coerce_usage_int(value: &Value) -> i64 {
    let raw = match value {
        Value::Null => 0,
        Value::Bool(b) => i64::from(*b),
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_f64().map(|f| f as i64))
            .unwrap_or(0),
        Value::String(s) => s.trim().parse::<i64>().unwrap_or(0),
        _ => 0,
    };
    raw.max(0)
}

/// ←→ Python `_compact_usage_context` (llm_repair.py:117-131)
///
/// 压缩 context 字典：drop 空值，长字符串截断到 96 字符 + "..."。
pub fn compact_usage_context(context: Option<&Value>) -> Map<String, Value> {
    let mut compact = Map::new();
    let Some(Value::Object(obj)) = context else {
        return compact;
    };
    for (key, value) in obj.iter() {
        if value.is_null() {
            continue;
        }
        match value {
            Value::Number(_) | Value::Bool(_) => {
                compact.insert(key.to_string(), value.clone());
            }
            _ => {
                let text = match value {
                    Value::String(s) => s.clone(),
                    other => other.to_string(),
                };
                let trimmed = text.trim();
                if trimmed.is_empty() {
                    continue;
                }
                let truncated = if trimmed.chars().count() > 96 {
                    let mut buf: String = trimmed.chars().take(96).collect();
                    buf.push_str("...");
                    buf
                } else {
                    trimmed.to_string()
                };
                compact.insert(key.to_string(), Value::String(truncated));
            }
        }
    }
    compact
}

/// ←→ Python `_summarize_usage_events` 返回值的 4 项
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
pub struct UsageRow {
    pub request_count: i64,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub total_tokens: i64,
}

impl UsageRow {
    fn add_assign(&mut self, key: &str, value: i64) {
        match key {
            "request_count" => self.request_count += value,
            "prompt_tokens" => self.prompt_tokens += value,
            "completion_tokens" => self.completion_tokens += value,
            "total_tokens" => self.total_tokens += value,
            _ => {}
        }
    }
}

/// ←→ Python `_summarize_usage_events` 返回值
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
pub struct UsageSummary {
    pub by_stage: BTreeMap<String, UsageRow>,
    pub by_model: BTreeMap<String, UsageRow>,
    pub total: UsageRow,
}

/// ←→ Python `_summarize_usage_events` (llm_repair.py:134-173)
pub fn summarize_usage_events(events: Option<&[Value]>, required_stages: &[&str]) -> UsageSummary {
    let mut summary = UsageSummary::default();
    for event in events.unwrap_or(&[]) {
        let stage = event
            .get("stage")
            .and_then(|v| v.as_str())
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
            .unwrap_or("unknown")
            .to_string();
        let model_id = event
            .get("model_id")
            .and_then(|v| v.as_str())
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
            .unwrap_or("unknown")
            .to_string();
        let usage = [
            ("request_count", coerce_usage_int(&event["request_count"])),
            ("prompt_tokens", coerce_usage_int(&event["prompt_tokens"])),
            (
                "completion_tokens",
                coerce_usage_int(&event["completion_tokens"]),
            ),
            ("total_tokens", coerce_usage_int(&event["total_tokens"])),
        ];
        let stage_row = summary.by_stage.entry(stage).or_default();
        for (key, value) in usage.iter() {
            stage_row.add_assign(key, *value);
        }
        let model_row = summary.by_model.entry(model_id).or_default();
        for (key, value) in usage.iter() {
            model_row.add_assign(key, *value);
        }
        for (key, value) in usage.iter() {
            summary.total.add_assign(key, *value);
        }
    }
    for stage in required_stages {
        summary.by_stage.entry(stage.to_string()).or_default();
    }
    summary
}

// `with_time_limit` 已删除：见 module doc，超时由 `reqwest::RequestBuilder::timeout` 实现。

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_safe_float_number() {
        assert_eq!(safe_float(&json!(0.9), 0.0), 0.9);
        assert_eq!(safe_float(&json!(1), 0.0), 1.0);
    }

    #[test]
    fn test_safe_float_string_label_returns_default() {
        // 文字标签不再转换为数值，直接返回 default
        assert_eq!(safe_float(&json!("high"), 0.42), 0.42);
        assert_eq!(safe_float(&json!("Medium"), 0.42), 0.42);
        assert_eq!(safe_float(&json!("low"), 0.42), 0.42);
    }

    #[test]
    fn test_safe_float_string_numeric() {
        assert_eq!(safe_float(&json!("0.75"), 0.0), 0.75);
    }

    #[test]
    fn test_safe_float_default() {
        assert_eq!(safe_float(&json!("garbage"), 0.42), 0.42);
        assert_eq!(safe_float(&json!(null), 0.5), 0.5);
    }

    #[test]
    fn test_coerce_usage_int_normal() {
        assert_eq!(coerce_usage_int(&json!(42)), 42);
        assert_eq!(coerce_usage_int(&json!(null)), 0);
        assert_eq!(coerce_usage_int(&json!(-5)), 0);
    }

    #[test]
    fn test_coerce_usage_int_string() {
        assert_eq!(coerce_usage_int(&json!("17")), 17);
        assert_eq!(coerce_usage_int(&json!("garbage")), 0);
    }

    #[test]
    fn test_compact_usage_context() {
        let ctx = json!({"a": 1, "b": "  short  ", "c": null, "d": ""});
        let out = compact_usage_context(Some(&ctx));
        assert_eq!(out.get("a"), Some(&json!(1)));
        assert_eq!(out.get("b"), Some(&json!("short")));
        assert_eq!(out.get("c"), None);
        assert_eq!(out.get("d"), None);
    }

    #[test]
    fn test_compact_usage_context_truncate() {
        let long = "x".repeat(120);
        let ctx = json!({"k": long});
        let out = compact_usage_context(Some(&ctx));
        let v = out.get("k").unwrap().as_str().unwrap();
        assert!(v.ends_with("..."));
        assert_eq!(v.chars().count(), 96 + 3);
    }

    #[test]
    fn test_summarize_usage_events() {
        let events = vec![
            json!({"stage": "A", "model_id": "m1", "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "request_count": 1}),
            json!({"stage": "A", "model_id": "m1", "prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27, "request_count": 1}),
            json!({"stage": "B", "model_id": "m2", "prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4, "request_count": 1}),
        ];
        let summary = summarize_usage_events(Some(&events), &["A", "B", "C"]);
        assert_eq!(summary.total.prompt_tokens, 33);
        assert_eq!(summary.total.completion_tokens, 13);
        assert_eq!(summary.total.total_tokens, 46);
        assert_eq!(summary.by_stage["A"].prompt_tokens, 30);
        assert_eq!(summary.by_stage["B"].prompt_tokens, 3);
        assert!(summary.by_stage.contains_key("C"));
        assert_eq!(summary.by_model["m1"].total_tokens, 42);
    }
}

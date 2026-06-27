//! ←→ FNM_RE/modules/llm_book_type_verify.py
//! Vision LLM 调用 + content_filter retry + 多 model fallback + response parsing。
//!
//! 使用 fnm-core 的 `ResolvedModelSpec` + `resolve_fnm_model_pool_specs`，
//! 对齐 Python 端 `resolve_visual_model_spec` 的契约。

use anyhow::{Context, Result};
use fnm_core::vision::{ResolvedModelSpec, HTTP_CLIENT};
use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::{json, Value};

// ── 响应解析正则 ───────────────────────────────────────────────

static JSON_FENCED_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?s)```(?:json)?\s*(.*?)\s*```").unwrap());

static JSON_OBJECT_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?s)\{.*\}").unwrap());

// ── 响应解析 ────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct ParsedVerifyResponse {
    pub book_type: Option<String>,
    pub confidence: String,
    pub agrees_with_pipeline: bool,
    pub reasoning: String,
    pub toc_notes_page_verified: bool,
    pub toc_notes_actual_pdf_page: Option<i64>,
    pub suspected_false_positive_pages: Vec<i64>,
    pub raw_response: String,
    pub error: Option<String>,
}

/// ←→ Python `_parse_llm_response`
pub fn parse_llm_response(raw_text: &str) -> ParsedVerifyResponse {
    if raw_text.is_empty() {
        return ParsedVerifyResponse {
            error: Some("empty_response".into()),
            ..Default::default()
        };
    }
    let text = JSON_FENCED_RE
        .captures(raw_text)
        .and_then(|c| c.get(1))
        .map(|m| m.as_str().to_string())
        .unwrap_or_else(|| raw_text.to_string());
    let json_str = match JSON_OBJECT_RE.find(&text) {
        Some(m) => m.as_str().to_string(),
        None => {
            return ParsedVerifyResponse {
                error: Some("no_json_found".into()),
                raw_response: raw_text.chars().take(200).collect(),
                ..Default::default()
            }
        }
    };
    let parsed: Value = match serde_json::from_str(&json_str) {
        Ok(v) => v,
        Err(_) => {
            return ParsedVerifyResponse {
                error: Some("json_parse_error".into()),
                raw_response: raw_text.chars().take(200).collect(),
                ..Default::default()
            }
        }
    };
    if !parsed.is_object() {
        return ParsedVerifyResponse {
            error: Some("not_a_dict".into()),
            raw_response: raw_text.chars().take(200).collect(),
            ..Default::default()
        };
    }
    let valid_types: &[&str] = &["endnote_only", "footnote_only", "mixed"];
    let book_type = parsed
        .get("book_type")
        .and_then(|v| v.as_str())
        .filter(|s| valid_types.contains(s))
        .map(|s| s.to_string());

    ParsedVerifyResponse {
        book_type,
        confidence: parsed
            .get("confidence")
            .and_then(|v| v.as_str())
            .unwrap_or("low")
            .to_string(),
        agrees_with_pipeline: parsed
            .get("agrees_with_pipeline")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
        reasoning: parsed
            .get("reasoning")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        toc_notes_page_verified: parsed
            .get("toc_notes_page_verified")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
        toc_notes_actual_pdf_page: parsed
            .get("toc_notes_actual_pdf_page")
            .and_then(|v| v.as_i64()),
        suspected_false_positive_pages: parsed
            .get("suspected_false_positive_pages")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_i64()).collect())
            .unwrap_or_default(),
        raw_response: raw_text.chars().take(500).collect(),
        error: None,
    }
}

// ── Vision API 调用 ────────────────────────────────────────────

/// ←→ Python `_call_vision_llm`
pub async fn call_vision_llm(
    rendered: &[(i64, String)], // (page_no, base64_jpeg/png)
    system_prompt: &str,
    user_prompt: &str,
    spec: &ResolvedModelSpec,
) -> Result<ParsedVerifyResponse> {
    let mut user_content: Vec<Value> = vec![json!({"type": "text", "text": user_prompt})];
    for (_pn, b64) in rendered {
        user_content.push(json!({
            "type": "image_url",
            "image_url": { "url": format!("data:image/png;base64,{}", b64) }
        }));
    }
    let mut payload = json!({
        "model": spec.model_id,
        "max_tokens": super::selection::VERIFY_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    });
    // 应用 request_overrides（extra_body）
    if let Value::Object(overrides) = &spec.request_overrides {
        for (k, v) in overrides {
            if let Some(existing) = payload.get_mut(k) {
                if let (Value::Object(e), Value::Object(n)) = (existing, v) {
                    for (k2, v2) in n {
                        e.insert(k2.clone(), v2.clone());
                    }
                    continue;
                }
            }
            payload[k] = v.clone();
        }
    }
    // qwen / mimo_token_plan 默认 extra_body
    if !payload.as_object().unwrap().contains_key("extra_body")
        && matches!(spec.provider.as_str(), "qwen" | "mimo_token_plan")
    {
        payload["extra_body"] = json!({"enable_thinking": false});
    }

    let response = HTTP_CLIENT
        .post(format!("{}/chat/completions", spec.base_url))
        .bearer_auth(&spec.api_key)
        .json(&payload)
        .send()
        .await
        .context("Vision LLM 请求失败")?;
    let body: Value = response.json().await?;
    let raw_text = body["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .to_string();
    Ok(parse_llm_response(&raw_text))
}

// ── 多 model fallback 入口 ──────────────────────────────────────

/// ←→ Python `_call_vision_llm` + `_handle_content_filter_retry` 的合并入口。
/// 按 fnm pool 顺序遍历 specs，遇到 content_filter / 空响应时尝试下一 spec。
pub async fn call_with_fallback(
    rendered: &[(i64, String)],
    system_prompt: &str,
    user_prompt: &str,
    specs: &[ResolvedModelSpec],
) -> Result<ParsedVerifyResponse> {
    if specs.is_empty() {
        anyhow::bail!("no vision model spec resolved");
    }
    let mut last_err: Option<anyhow::Error> = None;
    for (idx, spec) in specs.iter().enumerate() {
        if !spec.supports_vision || spec.api_key.is_empty() {
            continue;
        }
        match call_vision_llm(rendered, system_prompt, user_prompt, spec).await {
            Ok(resp) => {
                // content_filter / 解析错误 → 尝试下一 spec
                if resp.book_type.is_none() && resp.error.is_some() && idx + 1 < specs.len() {
                    continue;
                }
                return Ok(resp);
            }
            Err(e) => {
                last_err = Some(e);
                if idx + 1 < specs.len() {
                    continue;
                }
            }
        }
    }
    Err(last_err.unwrap_or_else(|| anyhow::anyhow!("all vision specs failed")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_empty_response() {
        let r = parse_llm_response("");
        assert_eq!(r.error.as_deref(), Some("empty_response"));
    }

    #[test]
    fn parse_no_json() {
        let r = parse_llm_response("hello world");
        assert_eq!(r.error.as_deref(), Some("no_json_found"));
    }

    #[test]
    fn parse_valid_book_type() {
        let raw = r#"```json
        {"book_type": "endnote_only", "confidence": "high", "agrees_with_pipeline": true, "reasoning": "all chapters end with endnotes"}
        ```"#;
        let r = parse_llm_response(raw);
        assert_eq!(r.book_type.as_deref(), Some("endnote_only"));
        assert_eq!(r.confidence, "high");
        assert!(r.agrees_with_pipeline);
    }

    #[test]
    fn parse_invalid_book_type_strips() {
        let raw = r#"{"book_type": "weird_type"}"#;
        let r = parse_llm_response(raw);
        assert!(r.book_type.is_none());
    }

    #[test]
    fn parse_false_positive_pages_list() {
        let raw = r#"{"book_type": "mixed", "suspected_false_positive_pages": [10, 20, 30]}"#;
        let r = parse_llm_response(raw);
        assert_eq!(r.suspected_false_positive_pages, vec![10, 20, 30]);
    }
}

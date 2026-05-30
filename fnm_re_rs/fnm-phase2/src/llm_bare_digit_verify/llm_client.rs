//! bare digit vision API 调用。
//! ←→ FNM_RE/modules/llm_bare_digit_verify.py 中的 API 调用部分

use crate::llm_json::extract_json_block;
use crate::llm_bare_digit_verify::prompt_builder::build_bare_digit_prompt;
use crate::sup_recovery::layer3::VisionConfig;
use crate::sup_recovery::pdf_render::render_page_to_base64_png;
use anyhow::{Context, Result};
use serde_json::json;

/// 单一 bare digit 候选的验证结果。
#[derive(Debug, Clone)]
pub struct BareDigitVerifyResult {
    pub anchor_id: String,
    pub page_no: i64,
    pub marker: String,
    pub is_superscript: bool,
    pub confidence: f64,
}

/// 调 Vision API 验证一个 bare digit 候选。
pub async fn verify_bare_digit_candidate(
    pdf_path: &str,
    anchor_id: &str,
    page_no: i64,
    marker: &str,
    context_snippet: &str,
    config: &VisionConfig,
) -> Result<BareDigitVerifyResult> {
    // 1. 渲染 PDF 页
    let pdf_path_owned = pdf_path.to_string();
    let page_index = page_no - 1;
    let marker_owned = marker.to_string();
    let context_owned = context_snippet.to_string();
    let image_b64 = tokio::task::spawn_blocking(move || {
        render_page_to_base64_png(&pdf_path_owned, page_index, 150)
    })
    .await??;

    // 2. 构建 prompt
    let prompt = build_bare_digit_prompt(&marker_owned, &context_owned);

    // 3. 调 Vision API
    let client = &*crate::sup_recovery::layer3::HTTP_CLIENT;
    let response = client
        .post(format!("{}/chat/completions", config.base_url))
        .bearer_auth(&config.api_key)
        .json(&json!({
            "model": config.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": format!("data:image/png;base64,{}", image_b64)
                    }}
                ]
            }],
            "max_tokens": 100,
            "temperature": 0.0,
        }))
        .send()
        .await
        .context("Vision API 请求失败")?;

    // 4. 解析响应
    let body: serde_json::Value = response.json().await?;
    let content = body["choices"][0]["message"]["content"]
        .as_str()
        .context("Vision API 响应格式错误")?;

    Ok(parse_llm_response(content, anchor_id, page_no, marker))
}

fn parse_llm_response(
    content: &str,
    anchor_id: &str,
    page_no: i64,
    marker: &str,
) -> BareDigitVerifyResult {
    let json_str = extract_json_block(content);
    let parsed: serde_json::Value = serde_json::from_str(&json_str)
        .unwrap_or(json!({"is_superscript": false, "confidence": 0.0}));

    BareDigitVerifyResult {
        anchor_id: anchor_id.into(),
        page_no,
        marker: marker.into(),
        is_superscript: parsed["is_superscript"].as_bool().unwrap_or(false),
        confidence: parsed["confidence"].as_f64().unwrap_or(0.0),
    }
}

// JSON 块提取已收敛至 crate::llm_json。

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_accepted_response() {
        let resp = r#"{"is_superscript": true, "confidence": 0.9}"#;
        let result = parse_llm_response(resp, "a1", 5, "30");
        assert!(result.is_superscript);
        assert!((result.confidence - 0.9).abs() < 0.01);
    }

    #[test]
    fn parse_rejected_response() {
        let resp = r#"{"is_superscript": false, "confidence": 0.9}"#;
        let result = parse_llm_response(resp, "a2", 5, "30");
        assert!(!result.is_superscript);
    }

    #[test]
    fn parse_markdown_wrapped() {
        let resp = "```json\n{\"is_superscript\": true, \"confidence\": 0.8}\n```";
        let result = parse_llm_response(resp, "a3", 5, "30");
        assert!(result.is_superscript);
    }

    #[test]
    fn parse_garbage_defaults_false() {
        let resp = "not json at all";
        let result = parse_llm_response(resp, "a4", 5, "30");
        assert!(!result.is_superscript);
    }
}

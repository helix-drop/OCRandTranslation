//! Layer 3：Vision LLM 验证（PDF 截图 → vision API → marker 校验）。
//! ←→ FNM_RE/modules/sup_recovery.py 中的 Layer 3 部分（~250 行）

use crate::llm_json::extract_json_block;
use crate::sup_recovery::pdf_render::render_page_to_base64_png;
use anyhow::{Context, Result};
use fnm_core::vision::ResolvedModelSpec;
pub use fnm_core::vision::VisionConfig;
pub(crate) use fnm_core::vision::HTTP_CLIENT;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Layer3Candidate {
    pub page_no: i64,
    pub target_marker: String,
    pub context_region: String, // 周围文本
}

#[derive(Debug, Clone)]
pub struct Layer3Result {
    pub page_no: i64,
    pub marker: String,
    pub accepted: bool,
    pub confidence: f64,
    pub reason: String,
}

/// Vision LLM 验证候选 marker（异步）。
///
/// ←→ Python `sup_recovery._layer3_vision_verify()`
pub async fn layer3_verify_with_vision(
    pdf_path: &str,
    candidates: &[Layer3Candidate],
    config: &VisionConfig,
) -> Result<Vec<Layer3Result>> {
    if config.api_key.is_empty() {
        anyhow::bail!("OPENAI_API_KEY 未设置，无法调用 Vision API");
    }

    // 并发处理所有候选
    let futures = candidates
        .iter()
        .map(|c| verify_single_candidate(pdf_path, c, config));
    let results: Vec<Result<Layer3Result>> = futures::future::join_all(futures).await;

    results.into_iter().collect()
}

async fn verify_single_candidate(
    pdf_path: &str,
    candidate: &Layer3Candidate,
    config: &VisionConfig,
) -> Result<Layer3Result> {
    // 1. 渲染 PDF 页（spawn_blocking 因为 pdfium-render 是同步的）
    let pdf_path_owned = pdf_path.to_string();
    let page_index = candidate.page_no - 1; // PDF 0-indexed
    let image_b64 = tokio::task::spawn_blocking(move || {
        render_page_to_base64_png(&pdf_path_owned, page_index, 150)
    })
    .await??;

    // 2. 构建 prompt
    let prompt = build_layer3_prompt(&candidate.target_marker, &candidate.context_region);

    // 3. 调 Vision API
    let response = HTTP_CLIENT
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
            "max_tokens": 200,
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

    parse_layer3_response(content, &candidate.target_marker, candidate.page_no)
}

fn build_layer3_prompt(target_marker: &str, context: &str) -> String {
    // 严格对齐 Python 端的 prompt 模板
    format!(
        "查看页面图像。在以下上下文中是否存在上标 \"{}\"？\n\
        \n\
        上下文：{}\n\
        \n\
        如果存在且只有一个位置，回复 JSON: {{\"accepted\": true, \"confidence\": 0.9, \"reason\": \"unique location found\"}}\n\
        如果不存在，回复 JSON: {{\"accepted\": false, \"confidence\": 0.0, \"reason\": \"not found\"}}\n\
        如果有多个相同位置，回复 JSON: {{\"accepted\": false, \"confidence\": 0.0, \"reason\": \"ambiguous, multiple matches\"}}\n",
        target_marker, context
    )
}

pub fn parse_layer3_response(content: &str, marker: &str, page_no: i64) -> Result<Layer3Result> {
    // 提取 JSON（容忍 LLM 可能加 markdown ```json ... ``` 包装）
    let json_str = extract_json_block(content);
    let parsed: serde_json::Value = serde_json::from_str(&json_str)
        .with_context(|| format!("无法解析 LLM 响应为 JSON: {}", content))?;

    Ok(Layer3Result {
        page_no,
        marker: marker.into(),
        accepted: parsed["accepted"].as_bool().unwrap_or(false),
        confidence: parsed["confidence"].as_f64().unwrap_or(0.0),
        reason: parsed["reason"].as_str().unwrap_or("").into(),
    })
}

// ── ResolvedModelSpec 路径 ─────────────────────────────────────

/// 用 ResolvedModelSpec 路径（5 家 provider 通过 fnm_model_pool 配置）。
/// ←→ Python `_get_or_create_vision_client(spec)`
pub async fn layer3_verify_with_spec(
    pdf_path: &str,
    candidates: &[Layer3Candidate],
    specs: &[ResolvedModelSpec],
) -> Result<Vec<Layer3Result>> {
    if specs.is_empty() {
        anyhow::bail!("no vision spec resolved");
    }
    let vision_specs: Vec<&ResolvedModelSpec> = specs
        .iter()
        .filter(|s| s.supports_vision && !s.api_key.is_empty())
        .collect();
    if vision_specs.is_empty() {
        anyhow::bail!("no vision-capable spec available");
    }
    let futures = candidates
        .iter()
        .map(|c| verify_single_with_spec(pdf_path, c, &vision_specs));
    let results: Vec<Result<Layer3Result>> = futures::future::join_all(futures).await;
    results.into_iter().collect()
}

async fn verify_single_with_spec(
    pdf_path: &str,
    candidate: &Layer3Candidate,
    specs: &[&ResolvedModelSpec],
) -> Result<Layer3Result> {
    let pdf_path_owned = pdf_path.to_string();
    let page_index = candidate.page_no - 1;
    let image_b64 = tokio::task::spawn_blocking(move || {
        render_page_to_base64_png(&pdf_path_owned, page_index, 150)
    })
    .await??;
    let prompt = build_layer3_prompt(&candidate.target_marker, &candidate.context_region);
    let mut last_err: Option<anyhow::Error> = None;
    for spec in specs {
        match call_with_spec(spec, &prompt, &image_b64).await {
            Ok(content) => {
                return parse_layer3_response(&content, &candidate.target_marker, candidate.page_no)
            }
            Err(e) => {
                last_err = Some(e);
                continue;
            }
        }
    }
    Err(last_err.unwrap_or_else(|| anyhow::anyhow!("all specs failed")))
}

async fn call_with_spec(spec: &ResolvedModelSpec, prompt: &str, image_b64: &str) -> Result<String> {
    let mut payload = json!({
        "model": spec.model_id,
        "max_tokens": 400,
        "temperature": 0.0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": format!("data:image/png;base64,{}", image_b64)
                }}
            ]
        }]
    });
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
    let response = HTTP_CLIENT
        .post(format!("{}/chat/completions", spec.base_url))
        .bearer_auth(&spec.api_key)
        .json(&payload)
        .send()
        .await
        .context("Vision API 请求失败")?;
    let body: Value = response.json().await?;
    Ok(body["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_json_from_markdown() {
        let resp = "```json\n{\"accepted\": true, \"confidence\": 0.9, \"reason\": \"found\"}\n```";
        let extracted = extract_json_block(resp);
        assert!(extracted.contains("\"accepted\": true"));
    }

    #[test]
    fn parse_accepted_response() {
        let resp = r#"{"accepted": true, "confidence": 0.9, "reason": "unique"}"#;
        let result = parse_layer3_response(resp, "30", 5).unwrap();
        assert!(result.accepted);
        assert_eq!(result.confidence, 0.9);
    }

    #[test]
    fn parse_rejected_response() {
        let resp = r#"{"accepted": false, "confidence": 0.0, "reason": "not found"}"#;
        let result = parse_layer3_response(resp, "30", 5).unwrap();
        assert!(!result.accepted);
    }

    #[tokio::test]
    #[ignore = "需要真实 OPENAI_API_KEY"]
    async fn real_vision_call() {
        let candidate = Layer3Candidate {
            page_no: 1,
            target_marker: "1".into(),
            context_region: "...test...".into(),
        };
        let config = VisionConfig::default();
        let pdf = "/Users/hao/OCRandTranslation/test_example/Biopolitics/Biopolitics.pdf";
        let results = layer3_verify_with_vision(pdf, &[candidate], &config)
            .await
            .unwrap();
        assert_eq!(results.len(), 1);
    }
}

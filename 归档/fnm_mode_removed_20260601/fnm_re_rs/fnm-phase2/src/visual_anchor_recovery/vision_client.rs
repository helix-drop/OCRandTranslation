//! Vision LLM 客户端（复用 G2 的 HTTP_CLIENT 和 VisionConfig）。
//! ←→ Python `visual_anchor_recovery._vision_verify_candidate()`

use crate::llm_json::extract_json_block;
use crate::sup_recovery::layer3::VisionConfig;
use crate::sup_recovery::pdf_render::render_page_to_base64_png;
use anyhow::{Context, Result};
use serde_json::json;

/// Vision 验证结果。
#[derive(Debug, Clone)]
pub struct VisionVerifyResult {
    pub page_no: i64,
    pub marker: String,
    pub accepted: bool,
    pub confidence: f64,
    pub reason: String,
}

/// 调用 Vision API 验证指定页面上是否存在目标 marker。
pub async fn verify_candidate_page(
    pdf_path: &str,
    page_no: i64,
    target_marker: &str,
    config: &VisionConfig,
) -> Result<VisionVerifyResult> {
    // 1. 渲染 PDF 页
    let pdf_path_owned = pdf_path.to_string();
    let page_index = page_no - 1; // PDF 0-indexed
    let marker_owned = target_marker.to_string();
    let image_b64 = tokio::task::spawn_blocking(move || {
        render_page_to_base64_png(&pdf_path_owned, page_index, 150)
    })
    .await??;

    // 2. 构建 prompt
    let prompt = format!(
        "查看页面图像。数字 \"{}\" 作为上标或角标出现在正文中吗？\n\
        如果存在且只有一个位置，回复 JSON: {{\"accepted\": true, \"confidence\": 0.9}}\n\
        如果不存在，回复 JSON: {{\"accepted\": false, \"confidence\": 0.0}}",
        marker_owned
    );

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
            "max_tokens": 150,
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

    let json_str = extract_json_block(content);
    let parsed: serde_json::Value = serde_json::from_str(&json_str)
        .unwrap_or_else(|_| json!({"accepted": false, "confidence": 0.0}));

    Ok(VisionVerifyResult {
        page_no,
        marker: target_marker.into(),
        accepted: parsed["accepted"].as_bool().unwrap_or(false),
        confidence: parsed["confidence"].as_f64().unwrap_or(0.0),
        reason: "vision_llm_verified".into(),
    })
}

// JSON 块提取已收敛至 crate::llm_json（含其测试）。

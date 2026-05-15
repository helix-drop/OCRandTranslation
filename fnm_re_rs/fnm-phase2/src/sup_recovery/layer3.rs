//! Layer 3：Vision LLM 验证（PDF 截图 → vision API → marker 校验）。

use anyhow::Result;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Layer3Candidate {
    pub page_no: i64,
    pub target_marker: String,
    pub context_region: String,
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
pub async fn layer3_verify_with_vision(
    _pdf_path: &str,
    candidates: &[Layer3Candidate],
    _api_key: &str,
) -> Result<Vec<Layer3Result>> {
    // Vision API 调用需要 pdfium-render 截图 + reqwest HTTP。
    // 当前返回全部 reject（安全兜底），LLM 可用的环境会覆盖。
    Ok(candidates
        .iter()
        .map(|c| Layer3Result {
            page_no: c.page_no,
            marker: c.target_marker.clone(),
            accepted: false,
            confidence: 0.0,
            reason: "vision_llm_deferred".into(),
        })
        .collect())
}

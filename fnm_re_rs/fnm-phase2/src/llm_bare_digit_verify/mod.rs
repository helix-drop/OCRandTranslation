//! ←→ FNM_RE/modules/llm_bare_digit_verify.py (221 行)
//! LLM 验证 bare digit marker：对 body_anchors 中 source = "bare_digit" 的候选，
//! 用 vision LLM 二次确认，输出接受/拒绝。

pub mod llm_client;
pub mod prompt_builder;
pub mod response_parser;

use crate::llm_bare_digit_verify::llm_client::{
    verify_bare_digit_candidate, BareDigitVerifyResult,
};
use crate::llm_bare_digit_verify::response_parser::split_results;
use crate::sup_recovery::layer3::VisionConfig;
use fnm_core::records::BodyAnchorRecord;
use std::sync::Arc;
use tokio::sync::Semaphore;

/// 主入口：验证 bare digit anchors。
pub async fn verify_bare_digit_candidates(
    anchors: &[BodyAnchorRecord],
    pdf_path: &str,
    config: &VisionConfig,
    max_concurrent: usize,
    min_confidence: f64,
) -> anyhow::Result<(Vec<BareDigitVerifyResult>, Vec<BareDigitVerifyResult>)> {
    if config.api_key.is_empty() {
        return Ok((Vec::new(), Vec::new()));
    }

    // 只处理 source = "bare_digit" 的锚点
    let candidates: Vec<&BodyAnchorRecord> = anchors
        .iter()
        .filter(|a| a.source == "bare_digit")
        .collect();

    if candidates.is_empty() {
        return Ok((Vec::new(), Vec::new()));
    }

    // 并发验证
    let semaphore = Arc::new(Semaphore::new(max_concurrent));
    let mut handles = Vec::new();

    for candidate in candidates {
        let sem = Arc::clone(&semaphore);
        let pdf_path = pdf_path.to_string();
        let config = config.clone();
        let anchor_id = candidate.anchor_id.clone();
        let page_no = candidate.page_no;
        let marker = candidate.normalized_marker.clone();
        let context = candidate.source_text.clone();

        handles.push(tokio::spawn(async move {
            let _permit = sem.acquire().await;
            verify_bare_digit_candidate(&pdf_path, &anchor_id, page_no, &marker, &context, &config)
                .await
        }));
    }

    let mut all_results = Vec::new();
    for handle in handles {
        if let Ok(Ok(result)) = handle.await {
            all_results.push(result);
        }
    }

    let split = split_results(all_results, min_confidence);
    Ok((split.accepted, split.rejected))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_no_candidates() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let result = rt.block_on(verify_bare_digit_candidates(
            &[],
            "/dev/null",
            &VisionConfig::default(),
            4,
            0.5,
        ));
        let (accepted, rejected) = result.unwrap();
        assert!(accepted.is_empty());
        assert!(rejected.is_empty());
    }

    #[test]
    fn non_bare_digit_anchors_filtered() {
        let anchors = vec![BodyAnchorRecord {
            anchor_id: "a1".into(),
            chapter_id: "ch-1".into(),
            page_no: 1,
            paragraph_index: 1,
            char_start: 0,
            char_end: 1,
            source_marker: "1".into(),
            normalized_marker: "1".into(),
            anchor_kind: fnm_core::types::AnchorKind::Footnote,
            certainty: 1.0,
            source_text: String::new(),
            source: "footnote_ref".into(),
            synthetic: false,
            ocr_repaired_from_marker: String::new(),
        }];
        let rt = tokio::runtime::Runtime::new().unwrap();
        let result = rt.block_on(verify_bare_digit_candidates(
            &anchors,
            "/dev/null",
            &VisionConfig::default(),
            4,
            0.5,
        ));
        let (accepted, rejected) = result.unwrap();
        assert!(accepted.is_empty());
        assert!(rejected.is_empty());
    }
}

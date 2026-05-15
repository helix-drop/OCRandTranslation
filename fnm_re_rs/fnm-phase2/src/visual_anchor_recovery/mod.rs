//! ←→ FNM_RE/modules/visual_anchor_recovery.py (1017 行)
//! 视觉锚点恢复：检测正文中缺失的 marker → 调 vision LLM 验证 → 写 review_override。

pub mod gap_detection;
pub mod override_builder;
pub mod vision_client;

use crate::sup_recovery::layer3::VisionConfig;
use crate::visual_anchor_recovery::gap_detection::GapCandidate;
use crate::visual_anchor_recovery::override_builder::build_overrides_from_results;
use crate::visual_anchor_recovery::vision_client::verify_candidate_page;
use fnm_core::records::BodyAnchorRecord;
use fnm_phase1::input::RawPage;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tokio::sync::Semaphore;

/// 主入口：视觉锚点恢复。
///
/// 1. 对每章构建 expected_markers（来自 note_items）
/// 2. 对比 found_anchors，找缺口
/// 3. 对每个缺口，用 vision LLM 验证
/// 4. 接受的 marker 构建 override
pub async fn build_visual_recovery_overrides(
    pages: &[RawPage],
    chapter_markers: &HashMap<String, HashSet<String>>,
    chapter_page_ranges: &HashMap<String, (i64, i64)>,
    pdf_path: &str,
    config: &VisionConfig,
    max_concurrent: usize,
) -> anyhow::Result<Vec<serde_json::Value>> {
    if config.api_key.is_empty() {
        return Ok(Vec::new());
    }

    // 1. 构建锚点索引（按 chapter_id 分组）
    let anchors_by_chapter: HashMap<String, Vec<BodyAnchorRecord>> =
        group_anchors_by_chapter(pages);

    // 2. 检测所有缺口
    let mut gaps: Vec<GapCandidate> = Vec::new();
    for (chapter_id, expected_markers) in chapter_markers {
        if let Some(&(start, end)) = chapter_page_ranges.get(chapter_id) {
            let chapter_gaps = gap_detection::detect_chapter_marker_gaps(
                chapter_id,
                expected_markers,
                anchors_by_chapter
                    .get(chapter_id)
                    .map(|v| v.as_slice())
                    .unwrap_or(&[]),
                start,
                end,
            );
            gaps.extend(chapter_gaps);
        }
    }

    if gaps.is_empty() {
        return Ok(Vec::new());
    }

    // 3. 并发 vision 验证（受 semaphore 限制）
    let semaphore = Arc::new(Semaphore::new(max_concurrent));
    let mut handles = Vec::new();

    for gap in gaps {
        let sem = Arc::clone(&semaphore);
        let pdf_path = pdf_path.to_string();
        let config = config.clone();

        handles.push(tokio::spawn(async move {
            let _permit = sem.acquire().await;
            verify_candidate_page(&pdf_path, gap.expected_page_range.0, &gap.marker, &config).await
        }));
    }

    // 4. 收集结果
    let mut all_results = Vec::new();
    for handle in handles {
        if let Ok(Ok(result)) = handle.await {
            all_results.push(result);
        }
    }

    // 5. 构建 overrides（按 chapter_id 分组后构建）
    let mut all_overrides: Vec<serde_json::Value> = Vec::new();
    let mut by_chapter: HashMap<String, Vec<_>> = HashMap::new();
    for result in &all_results {
        by_chapter
            .entry(result.marker.clone())
            .or_default()
            .push(result.clone());
    }
    for (marker, results) in &by_chapter {
        // 查找 gap 对应的 chapter_id
        let chapter_id = results
            .first()
            .map(|_r| {
                // 用 marker 反查 chapter
                for (cid, expected) in chapter_markers {
                    if expected.contains(marker) {
                        return cid.clone();
                    }
                }
                "unknown".to_string()
            })
            .unwrap_or_default();
        all_overrides.extend(build_overrides_from_results(results, &chapter_id));
    }

    Ok(all_overrides)
}

fn group_anchors_by_chapter(pages: &[RawPage]) -> HashMap<String, Vec<BodyAnchorRecord>> {
    // 当前 Phase 2 还没有 body anchors（Phase 3 产物），返回空
    // TODO: 等 Phase 3 gateway 接入后从 phase3_structure 读取 anchors
    let _ = pages;
    HashMap::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_input_no_overrides() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let result = rt.block_on(build_visual_recovery_overrides(
            &[],
            &HashMap::new(),
            &HashMap::new(),
            "/dev/null",
            &VisionConfig::default(),
            4,
        ));
        assert!(result.unwrap().is_empty());
    }
}

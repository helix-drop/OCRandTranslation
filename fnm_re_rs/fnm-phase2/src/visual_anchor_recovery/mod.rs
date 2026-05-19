//! ←→ FNM_RE/modules/visual_anchor_recovery.py (1017 行)
//! 视觉锚点恢复：检测正文中缺失的 marker → 调 vision LLM 验证 → 物化为
//! BodyAnchorRecord + 构建 review override。
//!
//! 完整 port：
//! - `gap_detection`：缺口检测
//! - `parsing`：roman/superscript/sanitize/best_window/sample_pages/parse_findings
//! - `materialize`：findings → BodyAnchorRecord + fuzzy_find_phrase_in_page
//! - `vision_client`：Vision API（旧 VisionConfig 路径）
//! - 顶层 build_visual_recovery_overrides：用 ResolvedModelSpec 多 spec fallback
//!   调用 vision LLM，串起 parsing + materialize 全套工具

pub mod gap_detection;
pub mod materialize;
pub mod override_builder;
pub mod parsing;
pub mod vision_client;

use crate::sup_recovery::layer3::VisionConfig;
use crate::visual_anchor_recovery::gap_detection::GapCandidate;
use crate::visual_anchor_recovery::materialize::ChapterAnchorGap;
use crate::visual_anchor_recovery::override_builder::build_overrides_from_results;
use crate::visual_anchor_recovery::parsing::{
    build_visual_recovery_user_prompt, parse_visual_findings, sample_page_range,
    VISUAL_RECOVERY_SYSTEM_PROMPT,
};
use crate::visual_anchor_recovery::vision_client::verify_candidate_page;
use fnm_core::records::BodyAnchorRecord;
use fnm_core::vision::{
    render_page_to_base64_png, resolve_fnm_model_pool_specs, ResolvedModelSpec, HTTP_CLIENT,
};
use fnm_phase1::input::RawPage;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tokio::sync::Semaphore;

const VISUAL_RECOVERY_MAX_IMAGES: usize = 5;
const VISUAL_RECOVERY_MAX_OUTPUT_TOKENS: i64 = 2048;

// ── 顶层入口（旧 VisionConfig 路径，保留向后兼容）─────────────

/// 主入口：视觉锚点恢复（旧 OPENAI_API_KEY/VisionConfig 路径）。
pub async fn build_visual_recovery_overrides(
    _pages: &[RawPage],
    body_anchors: &[BodyAnchorRecord],
    chapter_markers: &HashMap<String, HashSet<String>>,
    chapter_page_ranges: &HashMap<String, (i64, i64)>,
    pdf_path: &str,
    config: &VisionConfig,
    max_concurrent: usize,
) -> anyhow::Result<Vec<Value>> {
    if config.api_key.is_empty() {
        return Ok(Vec::new());
    }
    let mut anchors_by_chapter: HashMap<String, Vec<&BodyAnchorRecord>> = HashMap::new();
    for anchor in body_anchors {
        anchors_by_chapter
            .entry(anchor.chapter_id.clone())
            .or_default()
            .push(anchor);
    }
    let mut gaps: Vec<GapCandidate> = Vec::new();
    for (chapter_id, expected_markers) in chapter_markers {
        if let Some(&(start, end)) = chapter_page_ranges.get(chapter_id) {
            let anchors_owned: Vec<BodyAnchorRecord> = anchors_by_chapter
                .get(chapter_id)
                .map(|v| v.iter().map(|a| (*a).clone()).collect())
                .unwrap_or_default();
            let chapter_gaps = gap_detection::detect_chapter_marker_gaps(
                chapter_id,
                expected_markers,
                &anchors_owned,
                start,
                end,
            );
            gaps.extend(chapter_gaps);
        }
    }
    if gaps.is_empty() {
        return Ok(Vec::new());
    }
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
    let mut all_results = Vec::new();
    for handle in handles {
        if let Ok(Ok(result)) = handle.await {
            all_results.push(result);
        }
    }
    let mut all_overrides: Vec<Value> = Vec::new();
    let mut by_chapter: HashMap<String, Vec<_>> = HashMap::new();
    for result in &all_results {
        by_chapter
            .entry(result.marker.clone())
            .or_default()
            .push(result.clone());
    }
    for (marker, results) in &by_chapter {
        let chapter_id = results
            .first()
            .map(|_r| {
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

// ── 新顶层：完整 Python `run_visual_anchor_recovery` + ResolvedModelSpec ──

/// ←→ Python `run_visual_anchor_recovery` 完整流程：
/// 1. 解析 gap 页范围 → 采样图像页
/// 2. 渲染 PDF 页 base64
/// 3. 调 VLM（multi-spec fallback）请求 findings
/// 4. parse findings → materialize 为 BodyAnchorRecord
///
/// 输出：直接产出 BodyAnchorRecord（不是 override），供下游 Phase 3 接入。
pub async fn run_visual_anchor_recovery(
    gap: &ChapterAnchorGap,
    page_by_no: &HashMap<i64, &RawPage>,
    pdf_path: &str,
) -> anyhow::Result<(Vec<BodyAnchorRecord>, Value)> {
    if pdf_path.is_empty() || gap.missing_markers.is_empty() {
        return Ok((
            Vec::new(),
            json!({"status": "skipped", "reason": "no input"}),
        ));
    }

    let specs = resolve_fnm_model_pool_specs();
    let vision_specs: Vec<ResolvedModelSpec> = specs
        .into_iter()
        .filter(|s| s.supports_vision && !s.api_key.is_empty())
        .collect();
    if vision_specs.is_empty() {
        return Ok((
            Vec::new(),
            json!({"status": "skipped", "reason": "no vision-capable spec"}),
        ));
    }

    let (min_page, max_page) = gap.body_page_range;
    if min_page <= 0 || max_page <= 0 {
        return Ok((
            Vec::new(),
            json!({"status": "skipped", "reason": "invalid page range"}),
        ));
    }

    let sample_pages = sample_page_range(min_page, max_page, VISUAL_RECOVERY_MAX_IMAGES);

    // 渲染
    let mut rendered: Vec<(i64, String)> = Vec::new();
    for &pn in &sample_pages {
        let pdf_path_owned = pdf_path.to_string();
        let page_index = (pn - 1).max(0);
        let result = tokio::task::spawn_blocking(move || {
            render_page_to_base64_png(&pdf_path_owned, page_index, 150)
        })
        .await;
        match result {
            Ok(Ok(b64)) => rendered.push((pn, b64)),
            Ok(Err(e)) => tracing::warn!("page {} render failed: {:?}", pn, e),
            Err(e) => tracing::warn!("page {} render join error: {:?}", pn, e),
        }
    }
    if rendered.is_empty() {
        return Ok((
            Vec::new(),
            json!({"status": "skipped", "reason": "no pages rendered"}),
        ));
    }

    // 调 VLM
    let missing: Vec<i64> = gap.missing_markers.iter().copied().collect();
    let user_prompt = build_visual_recovery_user_prompt(&missing, min_page, max_page);
    let findings = call_vlm_with_fallback(
        &vision_specs,
        VISUAL_RECOVERY_SYSTEM_PROMPT,
        &user_prompt,
        &rendered,
    )
    .await?;

    // Materialize
    let (anchors, summary) =
        materialize::materialize_visual_findings(&findings, gap, page_by_no, &sample_pages);
    Ok((
        anchors,
        json!({
            "chapter_id": gap.chapter_id,
            "missing_markers": missing,
            "rendered_pages": rendered.len(),
            "findings_count": findings.len(),
            "materialization": summary.to_json(),
        }),
    ))
}

// ── VLM 调用（multi-spec fallback） ─────────────────────────────

async fn call_vlm_with_fallback(
    specs: &[ResolvedModelSpec],
    system_prompt: &str,
    user_prompt: &str,
    rendered: &[(i64, String)],
) -> anyhow::Result<Vec<Value>> {
    let mut last_err: Option<anyhow::Error> = None;
    for (idx, spec) in specs.iter().enumerate() {
        match call_vlm_single(spec, system_prompt, user_prompt, rendered).await {
            Ok(text) => {
                let parsed = parse_visual_findings(&text);
                if !parsed.is_empty() || idx + 1 == specs.len() {
                    return Ok(parsed);
                }
                continue;
            }
            Err(e) => {
                last_err = Some(e);
                if idx + 1 < specs.len() {
                    continue;
                }
            }
        }
    }
    Err(last_err.unwrap_or_else(|| anyhow::anyhow!("all visual recovery specs failed")))
}

async fn call_vlm_single(
    spec: &ResolvedModelSpec,
    system_prompt: &str,
    user_prompt: &str,
    rendered: &[(i64, String)],
) -> anyhow::Result<String> {
    let mut user_content: Vec<Value> = vec![json!({"type": "text", "text": user_prompt})];
    for (_pn, b64) in rendered {
        user_content.push(json!({
            "type": "image_url",
            "image_url": { "url": format!("data:image/png;base64,{}", b64) }
        }));
    }
    let mut payload = json!({
        "model": spec.model_id,
        "max_tokens": VISUAL_RECOVERY_MAX_OUTPUT_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
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
        .await?;
    let body: Value = response.json().await?;
    Ok(body["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::visual_anchor_recovery::materialize::ChapterAnchorGap;

    #[test]
    fn old_path_empty_input_no_overrides() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let result = rt.block_on(build_visual_recovery_overrides(
            &[],
            &[],
            &HashMap::new(),
            &HashMap::new(),
            "/dev/null",
            &VisionConfig::default(),
            4,
        ));
        assert!(result.unwrap().is_empty());
    }

    #[test]
    fn run_recovery_skips_without_pdf() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let mut missing = HashSet::new();
        missing.insert(8i64);
        let gap = ChapterAnchorGap {
            chapter_id: "ch-1".into(),
            missing_markers: missing,
            body_page_range: (10, 20),
        };
        let pages: HashMap<i64, &RawPage> = HashMap::new();
        let (anchors, diag) = rt
            .block_on(run_visual_anchor_recovery(&gap, &pages, ""))
            .unwrap();
        assert!(anchors.is_empty());
        assert_eq!(diag["status"], "skipped");
    }

    #[test]
    fn run_recovery_skips_without_missing_markers() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let gap = ChapterAnchorGap {
            chapter_id: "ch-1".into(),
            missing_markers: HashSet::new(),
            body_page_range: (10, 20),
        };
        let pages: HashMap<i64, &RawPage> = HashMap::new();
        let (anchors, _) = rt
            .block_on(run_visual_anchor_recovery(&gap, &pages, "/tmp/fake.pdf"))
            .unwrap();
        assert!(anchors.is_empty());
    }
}

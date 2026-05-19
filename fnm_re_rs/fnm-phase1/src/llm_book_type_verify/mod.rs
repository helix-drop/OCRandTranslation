//! ←→ FNM_RE/modules/llm_book_type_verify.py (1039 行)
//! Phase 1→2 之间：LLM 交叉验证书型分类。
//!
//! 完整子模块：
//! - selection: 5 维分层选页（R1-R6）+ BookStructureProfile 提取
//! - prompt: system + user prompt 构建（带分章 chapter_label 分组）
//! - client: vision API 调用 + content_filter retry + multi-model fallback
//!
//! 使用 `fnm_core::vision::resolve_fnm_model_pool_specs()` 取代旧 OPENAI_API_KEY 硬编码。

pub mod client;
pub mod prompt;
pub mod selection;

use crate::book_note_type::BookNoteProfile;
use anyhow::Result;
use fnm_core::records::{ChapterNoteModeRecord, Phase1Structure};
use fnm_core::vision::{
    render_page_to_base64_png, resolve_fnm_model_pool_specs, ResolvedModelSpec,
};
use serde_json::json;
use std::collections::HashMap;

// ── Public API ──────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct LlmVerifyResult {
    pub llm_book_type: Option<String>,
    pub agreement_with_rules: bool,
    pub evidence: serde_json::Value,
}

/// Phase 1 LLM 验证入口（异步）。
///
/// ←→ Python `verify_book_type_with_llm`
/// 1. 提取 BookStructureProfile
/// 2. 5 维选页（R1-R6）
/// 3. 渲染 PDF 页为 base64 PNG
/// 4. 通过 fnm pool 解析的 Vision LLM specs 调用（支持多 model fallback）
/// 5. 解析响应、对比 rule-based book_type
pub async fn verify_book_type_with_llm(
    structure: &Phase1Structure,
    book_note_profile: &BookNoteProfile,
    chapter_note_modes: &[ChapterNoteModeRecord],
    pdf_path: &str,
) -> Result<LlmVerifyResult> {
    let specs = resolve_fnm_model_pool_specs();
    let vision_specs: Vec<ResolvedModelSpec> = specs
        .into_iter()
        .filter(|s| s.supports_vision && !s.api_key.is_empty())
        .collect();

    if vision_specs.is_empty() {
        return Ok(LlmVerifyResult {
            llm_book_type: None,
            agreement_with_rules: true,
            evidence: json!({
                "status": "skipped",
                "reason": "no vision-capable model spec resolved (check fnm_model_pool config + API key)",
            }),
        });
    }

    // 1. 提取 profile
    let profile =
        selection::extract_book_structure_profile(structure, book_note_profile, chapter_note_modes);

    // 2. 5 维选页
    let pages = selection::select_verification_pages(&profile);
    if pages.is_empty() {
        return Ok(LlmVerifyResult {
            llm_book_type: None,
            agreement_with_rules: true,
            evidence: json!({"status": "skipped", "reason": "no pages selected"}),
        });
    }

    // 3. 渲染
    let mut rendered: Vec<(i64, String)> = Vec::new();
    for &page_no in &pages {
        let pdf_path_owned = pdf_path.to_string();
        let page_index = (page_no - 1).max(0);
        let result = tokio::task::spawn_blocking(move || {
            render_page_to_base64_png(&pdf_path_owned, page_index, 150)
        })
        .await;
        match result {
            Ok(Ok(b64)) => rendered.push((page_no, b64)),
            Ok(Err(e)) => tracing::warn!("page {} render failed: {:?}", page_no, e),
            Err(e) => tracing::warn!("page {} render join error: {:?}", page_no, e),
        }
    }
    if rendered.is_empty() {
        anyhow::bail!("所有页面渲染失败: {}", pdf_path);
    }

    // 4. 构 prompt（按 chapter 分组）
    let chapter_by_page = selection::chapter_by_page(structure);
    let chapter_modes_by_page: HashMap<i64, String> = pages
        .iter()
        .filter_map(|&p| {
            chapter_by_page.get(&p).map(|cid| {
                let mode = profile
                    .chapter_modes
                    .get(cid)
                    .cloned()
                    .unwrap_or_else(|| "?".into());
                (p, mode)
            })
        })
        .collect();
    let page_infos: Vec<prompt::PageInfo> = pages
        .iter()
        .map(|&p| prompt::PageInfo {
            pdf_page: p,
            printed_page: None,
            chapter_label: chapter_by_page.get(&p).cloned().unwrap_or_default(),
        })
        .collect();
    let mode_types: Vec<String> = profile.mode_types.iter().cloned().collect();
    let user_prompt = prompt::build_user_prompt(
        &book_note_profile.book_type,
        &page_infos,
        profile.toc_has_notes_entry,
        profile.toc_notes_printed_page,
        profile.chapter_count,
        &mode_types,
        profile.endnote_regions.len(),
        profile.endnote_item_count,
        &chapter_modes_by_page,
    );

    // 5. 调 Vision LLM（multi-model fallback）
    let parsed = client::call_with_fallback(
        &rendered,
        prompt::LLM_VERIFY_SYSTEM_PROMPT,
        &user_prompt,
        &vision_specs,
    )
    .await?;

    let agreement = parsed
        .book_type
        .as_deref()
        .map(|t| t == book_note_profile.book_type)
        .unwrap_or(false);
    Ok(LlmVerifyResult {
        llm_book_type: parsed.book_type.clone(),
        agreement_with_rules: agreement,
        evidence: json!({
            "representative_pages": pages,
            "rendered_count": rendered.len(),
            "llm_book_type": parsed.book_type,
            "rule_based_type": book_note_profile.book_type,
            "agreement": agreement,
            "confidence": parsed.confidence,
            "reasoning": parsed.reasoning,
            "suspected_false_positive_pages": parsed.suspected_false_positive_pages,
            "raw_response_preview": parsed.raw_response,
        }),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::*;
    use fnm_core::types::PageRole;

    #[test]
    fn test_re_export_subpaths() {
        // Smoke：确认子模块可用
        assert!(prompt::LLM_VERIFY_SYSTEM_PROMPT.contains("book_type"));
        assert_eq!(selection::VERIFY_TOTAL_CAP_ABSOLUTE, 40);
        let r = client::parse_llm_response("");
        assert!(r.error.is_some());
    }

    #[tokio::test]
    #[ignore = "需要真实 OPENAI_API_KEY + PDFium 二进制"]
    async fn real_book_type_verify() {
        let structure = Phase1Structure {
            pages: vec![PagePartitionRecord {
                page_no: 1,
                target_pdf_page: 1,
                page_role: PageRole::FrontMatter,
                confidence: 1.0,
                reason: "test".into(),
                section_hint: String::new(),
                has_note_heading: false,
                note_scan_summary: serde_json::Value::Null,
            }],
            ..Default::default()
        };
        let profile = BookNoteProfile {
            book_type: "endnote_only".into(),
            chapter_modes: vec![],
            evidence: json!({}),
        };
        let pdf = "/Users/hao/OCRandTranslation/test_example/Biopolitics/Biopolitics.pdf";
        let result = verify_book_type_with_llm(&structure, &profile, &[], pdf)
            .await
            .unwrap();
        assert!(result.llm_book_type.is_some() || result.evidence["status"] == "skipped");
    }
}

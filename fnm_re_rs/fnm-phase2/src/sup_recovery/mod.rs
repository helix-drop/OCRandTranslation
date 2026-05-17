//! ←→ FNM_RE/modules/sup_recovery.py
//! OCR 上标修复：Layer 1 (markdown) + Layer 2 (block align) + Layer 3 (vision LLM)。
//!
//! Rust 实现：Layer 1 真实实现，Layer 2 数字匹配，Layer 3 vision LLM（需 pdf_path + API key）。

pub(crate) mod layer1;
pub(crate) mod layer2;
pub mod layer3;
pub mod pdf_render;

use fnm_core::vision::VisionConfig;
use fnm_phase1::input::RawPage;
use std::collections::HashMap;

/// 恢复入口：按章级 chapter_markers 修复缺失的上标标注。
/// 当 pdf_path + VisionConfig 有效时启用 Layer 2/3。
pub fn recover_book_chapter_scoped(
    pages: &[RawPage],
    chapter_markers: &HashMap<String, Vec<String>>,
    pdf_path: Option<&str>,
    vision_config: Option<&VisionConfig>,
) -> HashMap<String, Vec<(i64, String)>> {
    let mut results: HashMap<String, Vec<(i64, String)>> = HashMap::new();
    let mut layer3_candidates: HashMap<String, Vec<layer3::Layer3Candidate>> = HashMap::new();

    for (chapter_id, markers) in chapter_markers {
        let mut chapter_results: Vec<(i64, String)> = Vec::new();
        let mut unsolved: Vec<String> = markers.clone();

        for page in pages {
            if page.markdown.is_empty() {
                continue;
            }
            // Layer 1: markdown 内直接匹配 marker
            let hits = layer1::find_markers_in_markdown(&page.markdown, &unsolved);
            for marker in &hits {
                chapter_results.push((page.book_page, marker.clone()));
            }
            unsolved.retain(|m| !hits.contains(m));
            if unsolved.is_empty() {
                break;
            }
        }

        // Layer 2: OCR block 文本中搜索 missing markers（5 种 OCR surrogate 模式）
        if !unsolved.is_empty() {
            let block_texts: Vec<String> = pages
                .iter()
                .filter(|p| !p.markdown.is_empty())
                .map(|p| p.markdown.clone())
                .collect();
            let layer2_recoveries = layer2::find_markers_in_blocks(&block_texts, &unsolved);
            for rec in &layer2_recoveries {
                for page in pages {
                    if page.markdown.contains(&rec.marker) {
                        chapter_results.push((page.book_page, rec.marker.clone()));
                        break;
                    }
                }
                unsolved.retain(|m| m != &rec.marker);
            }
        }

        if !chapter_results.is_empty() {
            results.insert(chapter_id.clone(), chapter_results);
        }

        // Layer 3 vision 候选（剩余未解决标记）
        if !unsolved.is_empty() && pdf_path.is_some() && vision_config.is_some() {
            for marker in &unsolved {
                // 找 marker 可能出现的页
                for page in pages {
                    if page.markdown.contains(marker) {
                        layer3_candidates
                            .entry(chapter_id.clone())
                            .or_default()
                            .push(layer3::Layer3Candidate {
                                page_no: page.book_page,
                                target_marker: marker.clone(),
                                context_region: "sup_recovery_unsolved".into(),
                            });
                        break;
                    }
                }
            }
        }
    }

    // Layer 3: 异步 Vision LLM 验证
    if let (Some(pdf), Some(config)) = (pdf_path, vision_config) {
        if !config.api_key.is_empty() && !layer3_candidates.is_empty() {
            for (chapter_id, candidates) in &layer3_candidates {
                let rt = tokio::runtime::Runtime::new();
                if let Ok(runtime) = rt {
                    if let Ok(layer3_results) =
                        runtime.block_on(layer3::layer3_verify_with_vision(pdf, candidates, config))
                    {
                        for r in &layer3_results {
                            if r.accepted {
                                results
                                    .entry(chapter_id.clone())
                                    .or_default()
                                    .push((r.page_no, r.marker.clone()));
                            }
                        }
                    }
                }
            }
        }
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_input() {
        let result = recover_book_chapter_scoped(&[], &HashMap::new(), None, None);
        assert!(result.is_empty());
    }
}

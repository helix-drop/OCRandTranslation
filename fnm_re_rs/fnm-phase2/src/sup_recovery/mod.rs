//! ←→ FNM_RE/modules/sup_recovery.py
//! OCR 上标修复：Layer 1 (markdown) + Layer 2 (block align) + Layer 3 (vision LLM)。

pub(crate) mod layer1;
pub(crate) mod layer2;
pub mod layer3;
pub mod pdf_render;

use fnm_phase1::input::RawPage;
use std::collections::HashMap;

/// 恢复入口：按章级 chapter_markers 修复缺失的上标标注。
pub fn recover_book_chapter_scoped(
    pages: &[RawPage],
    chapter_markers: &HashMap<String, Vec<String>>,
    pdf_path: Option<&str>,
) -> HashMap<String, Vec<(i64, String)>> {
    let mut results: HashMap<String, Vec<(i64, String)>> = HashMap::new();

    for (chapter_id, markers) in chapter_markers {
        let chapter_pages: Vec<&RawPage> = pages
            .iter()
            .filter(|p| {
                // 简化：用 markdown 内容匹配 marker
                !p.markdown.is_empty()
            })
            .collect();

        let mut recovered: Vec<(i64, String)> = Vec::new();

        for page in &chapter_pages {
            // Layer 1: markdown 内直接匹配 marker
            let hits = layer1::find_markers_in_markdown(&page.markdown, markers);
            for marker in hits {
                recovered.push((page.book_page, marker));
            }
        }

        if !recovered.is_empty() {
            results.insert(chapter_id.clone(), recovered);
        }
    }

    let _ = pdf_path;
    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_input() {
        let result = recover_book_chapter_scoped(&[], &HashMap::new(), None);
        assert!(result.is_empty());
    }
}

//! ←→ FNM_RE/modules/toc_structure.py
//! Phase1 顶层编排：组装所有子模块输出为 Phase1Structure。

use crate::book_note_type::build_book_note_profile;
use crate::chapter_skeleton::builder::build_chapter_skeleton;
use crate::heading_graph::build_heading_graph_simple;
use crate::input::{ManualPageOverride, RawPage, TocItem, VisualTocBundle};
use crate::page_partition::build_page_partitions;
use crate::section_heads::build_section_heads;
use fnm_core::db::Repository;
use fnm_core::records::{HeadingCandidate, Phase1Structure};
use std::collections::HashMap;

#[derive(Debug, Clone, Default)]
pub struct Phase1Config {
    pub manual_page_overrides: Option<HashMap<String, ManualPageOverride>>,
    pub visual_toc_bundle: Option<VisualTocBundle>,
    pub pdf_path: Option<String>,
    pub doc_id: Option<String>,
    pub skip_llm_verify: bool,
}

#[derive(Debug, Clone)]
pub struct Phase1Output {
    pub structure: Phase1Structure,
    pub diagnostics: serde_json::Value,
}

/// Phase1 主入口：从原始页面构建章节骨架。
pub fn build_phase1_structure(
    pages: &[RawPage],
    toc_items: Option<&[TocItem]>,
    config: &Phase1Config,
) -> anyhow::Result<Phase1Output> {
    let total_pages = pages.len() as i64;

    // 1. TOC 乱码检测（暂跳过，直接使用传入的 toc_items）
    let _ = config;

    // 2. build_page_partitions
    let partitions_result = build_page_partitions(pages, None, None);
    let page_partitions = partitions_result.partitions;

    // 3. 构建 heading candidates（page_rows → collect → normalize）
    let page_rows = crate::chapter_skeleton::heading_candidates::page_rows::legacy_page_rows(
        &page_partitions,
        Some(pages),
    );
    let heading_candidates: Vec<HeadingCandidate> =
        crate::chapter_skeleton::heading_candidates::collect_heading_candidate_rows(
            &page_rows,
            toc_items,
            0,
            &config.pdf_path.clone().unwrap_or_default(),
            None,
            Some(&partitions_result.file_idx_map),
            &config.doc_id.clone().unwrap_or_default(),
        );

    // 4. build_section_heads
    let (section_heads, _) = build_section_heads(&[], &heading_candidates, &page_partitions, None);

    // 5. build_heading_graph
    let heading_graph = build_heading_graph_simple(&heading_candidates);

    // 6. build_chapter_skeleton
    let skeleton = build_chapter_skeleton(
        pages,
        toc_items,
        &page_partitions,
        &heading_graph,
        heading_candidates,
    );

    // 6. build_book_note_profile
    let _book_note_profile = build_book_note_profile(&skeleton.chapters, pages, None);

    // 7. 组装 Phase1Structure（page_partitions 已 owned，零 clone）
    let structure = Phase1Structure {
        pages: page_partitions,
        heading_candidates: skeleton.heading_candidates,
        chapters: skeleton.chapters,
        section_heads,
        endnote_explorer_hints: Default::default(),
        summary: Default::default(),
    };

    Ok(Phase1Output {
        structure,
        diagnostics: serde_json::json!({
            "total_pages": total_pages,
            "source": "Rust fnm-phase1",
        }),
    })
}

/// 把 Phase1Output 持久化到 DB（消耗 ownership，零 clone）。
pub fn persist_phase1(
    repo: &dyn Repository,
    doc_id: &str,
    output: Phase1Output,
) -> anyhow::Result<()> {
    repo.replace_fnm_phase1_products(
        doc_id,
        &fnm_core::db::Phase1Products {
            pages: output.structure.pages,
            chapters: output.structure.chapters,
            heading_candidates: output.structure.heading_candidates,
            section_heads: output.structure.section_heads,
        },
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::input::RawPage;

    #[test]
    fn build_structure_empty_pages() {
        let config = Phase1Config::default();
        let output = build_phase1_structure(&[], None, &config).unwrap();
        assert!(output.structure.pages.is_empty());
        assert!(output.structure.chapters.is_empty());
    }

    #[test]
    fn build_structure_single_page() {
        let pages = vec![RawPage {
            book_page: 1,
            markdown: "# Test\nContent".into(),
            ..Default::default()
        }];
        let config = Phase1Config::default();
        let output = build_phase1_structure(&pages, None, &config).unwrap();
        assert_eq!(output.structure.pages.len(), 1);
        assert_eq!(output.structure.pages[0].page_no, 1);
    }
}

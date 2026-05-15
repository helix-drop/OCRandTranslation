//! `fnm-phase2` — FNM_RE Phase 2: 识别注释结构 + 确定 note_kind（全书唯一来源）。

pub mod book_structure;
pub mod chapter_split;
pub mod endnote_chapter_explorer;
pub mod endnote_repair;
pub mod input;
pub mod llm_bare_digit_verify;
pub mod note_items;
pub mod note_kind_resolver;
pub mod note_regions;
pub mod output;
pub mod sup_recovery;
pub mod visual_anchor_recovery;

use crate::chapter_split::build_chapter_layers;
use crate::input::Phase2Input;
use crate::note_items::build_note_items;
use crate::note_regions::build_note_regions;
use crate::output::Phase2Output;
use fnm_core::db::Repository;

/// 同步入口（不含 LLM）。
pub fn build_phase2_structure_sync(input: Phase2Input) -> anyhow::Result<Phase2Output> {
    let _ = &input.config;

    // 1. sup_recovery Layer 1/2（如果 pdf_path 且 !skip_sup_recovery）
    // 2. build_note_regions
    let note_regions =
        build_note_regions(input.phase1_chapters, input.raw_pages, input.phase1_pages);

    // 3. build_note_items
    let note_items = build_note_items(input.raw_pages, &note_regions);

    // 4. endnote_chapter_explorer
    // 5. endnote_repair
    // 6. chapter_split
    let layers = build_chapter_layers(
        input.phase1_chapters,
        &note_regions,
        &note_items,
        input.phase1_pages,
        input.raw_pages,
    );

    // 7. book_structure 聚合
    let book_type = crate::book_structure::infer_book_type(&layers.chapter_note_modes);

    Ok(Phase2Output {
        chapters: input.phase1_chapters.to_vec(),
        note_regions,
        note_items,
        chapter_note_modes: layers.chapter_note_modes,
        book_type,
        diagnostics: serde_json::json!({}),
    })
}

/// 把 Phase2Output 持久化到 DB（只写 Phase 2 表，不触碰 Phase 1 表）。
pub fn persist_phase2(
    repo: &dyn Repository,
    doc_id: &str,
    output: Phase2Output,
) -> anyhow::Result<()> {
    repo.replace_fnm_phase2_products(
        doc_id,
        &fnm_core::db::Phase2Products {
            pages: vec![],
            chapters: vec![],
            heading_candidates: vec![],
            section_heads: vec![],
            note_regions: output.note_regions,
            chapter_note_modes: output.chapter_note_modes,
            note_items: output.note_items,
        },
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::ChapterRecord;
    use fnm_core::types::{BoundaryState, ChapterSource};
    use fnm_phase1::input::RawPage;

    #[test]
    fn build_structure_empty_input() {
        let input = Phase2Input {
            phase1_chapters: &[],
            phase1_pages: &[],
            phase1_section_heads: &[],
            raw_pages: &[],
            pdf_path: None,
            config: crate::input::Phase2Config::default(),
        };
        let output = build_phase2_structure_sync(input).unwrap();
        assert!(output.note_regions.is_empty());
        assert!(output.note_items.is_empty());
        assert_eq!(output.book_type, "no_notes");
    }

    #[test]
    fn build_structure_single_chapter() {
        let chapters = vec![ChapterRecord {
            chapter_id: "ch-1".into(),
            title: "Chapter 1".into(),
            start_page: 1,
            end_page: 3,
            pages: vec![1, 2, 3],
            source: ChapterSource::VisualToc,
            boundary_state: BoundaryState::Ready,
        }];
        let pages = vec![RawPage {
            book_page: 2,
            markdown: "1. First note about politics.\n2. Second note.".into(),
            note_scan: Some(serde_json::json!({"page_kind": "endnote_collection"})),
            ..Default::default()
        }];
        let input = Phase2Input {
            phase1_chapters: &chapters,
            phase1_pages: &[],
            phase1_section_heads: &[],
            raw_pages: &pages,
            pdf_path: None,
            config: crate::input::Phase2Config::default(),
        };
        let output = build_phase2_structure_sync(input).unwrap();
        assert_eq!(output.note_regions.len(), 1);
        assert!(!output.note_items.is_empty());
    }
}

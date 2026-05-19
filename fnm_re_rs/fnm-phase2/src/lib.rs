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
use fnm_core::vision::VisionConfig;
use std::collections::{HashMap, HashSet};
use std::time::Instant;

/// 同步入口（含 LLM sup_recovery Layer 3 vision 路径）。
pub fn build_phase2_structure_sync(input: Phase2Input) -> anyhow::Result<Phase2Output> {
    let start = Instant::now();

    // 1. build_note_regions
    let mut note_regions = build_note_regions(
        input.phase1_chapters,
        input.raw_pages,
        input.phase1_pages,
        &input.post_body_titles,
        input.phase1_heading_candidates,
    );

    // 1a. endnote_chapter_explorer 全量版：修正 book-scope endnote regions 的 chapter_id
    // ←→ Python `explore_endnote_chapter_regions`
    let page_by_no: HashMap<i64, &fnm_phase1::input::RawPage> =
        input.raw_pages.iter().map(|p| (p.book_page, p)).collect();
    let (explored_regions, _explorer_summary) =
        crate::endnote_chapter_explorer::explore_endnote_chapter_regions_full(
            note_regions,
            input.phase1_chapters,
            input.phase1_heading_candidates,
            &page_by_no,
            None,
        );
    let mut note_regions = explored_regions;

    // 2. build_note_items
    let note_items = build_note_items(input.raw_pages, &note_regions);

    // 3. sup_recovery Layer 1/2/3（基于 note_items 提取的 chapter_markers，pdf_path 启用 vision）
    let chapter_markers: HashMap<String, Vec<String>> = if !input.config.skip_sup_recovery {
        let mut markers: HashMap<String, HashSet<String>> = HashMap::new();
        for item in &note_items {
            markers
                .entry(item.chapter_id.clone())
                .or_default()
                .insert(item.marker.clone());
        }
        markers
            .into_iter()
            .map(|(k, v)| {
                let mut sorted: Vec<String> = v.into_iter().collect();
                sorted.sort();
                (k, sorted)
            })
            .collect()
    } else {
        HashMap::new()
    };

    let vision_config = if !input.config.skip_llm_verify {
        let cfg = VisionConfig::default();
        if cfg.api_key.is_empty() {
            None
        } else {
            Some(cfg)
        }
    } else {
        None
    };

    let recovered_sup = if !input.config.skip_sup_recovery {
        crate::sup_recovery::recover_book_chapter_scoped(
            input.raw_pages,
            &chapter_markers,
            input.pdf_path,
            vision_config.as_ref(),
        )
    } else {
        HashMap::new()
    };

    // 4. endnote_repair：引文缩写截断合并 + marker 连续性修复 + OCR split 合并
    let (repaired_note_items, endnote_repair_summary) =
        crate::endnote_repair::repair_endnote_items(&note_items);

    // 5. chapter_split（使用修复后的 note_items）
    let layers = build_chapter_layers(
        input.phase1_chapters,
        &note_regions,
        &repaired_note_items,
        input.phase1_pages,
        input.raw_pages,
    );

    // 6. book_structure 聚合
    let book_type = crate::book_structure::infer_book_type(&layers.chapter_note_modes)
        .as_str()
        .to_string();

    let total_recovered: usize = recovered_sup.values().map(|v| v.len()).sum();

    // 7. LLM 路径诊断（llm_bare_digit_verify + visual_anchor_recovery 需 Phase 3 body_anchors）
    let llm_ready = vision_config.is_some() && input.pdf_path.is_some();
    let elapsed = start.elapsed();
    let note_region_count = note_regions.len();
    let note_item_count = repaired_note_items.len();

    Ok(Phase2Output {
        chapters: input.phase1_chapters.to_vec(),
        note_regions,
        note_items: repaired_note_items,
        chapter_note_modes: layers.chapter_note_modes,
        book_type,
        diagnostics: serde_json::json!({
            "sup_recovery_recovered": total_recovered,
            "sup_recovery_num_chapters": recovered_sup.len(),
            "llm_vision_configured": llm_ready,
            "llm_bare_digit_verify_ready": llm_ready,
            "visual_anchor_recovery_ready": llm_ready,
            "note_item_count": note_item_count,
            "note_region_count": note_region_count,
            "elapsed_ms": elapsed.as_millis(),
            "endnote_repair": endnote_repair_summary,
        }),
    })
}

/// 把 Phase2Output 持久化到 DB。
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
            phase1_heading_candidates: &[],
            raw_pages: &[],
            pdf_path: None,
            config: crate::input::Phase2Config::default(),
            post_body_titles: HashSet::new(),
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
            phase1_heading_candidates: &[],
            raw_pages: &pages,
            pdf_path: None,
            config: crate::input::Phase2Config::default(),
            post_body_titles: HashSet::new(),
        };
        let output = build_phase2_structure_sync(input).unwrap();
        assert_eq!(output.note_regions.len(), 1);
        assert!(!output.note_items.is_empty());
    }
}

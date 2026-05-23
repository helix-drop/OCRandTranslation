//! `fnm-phase4` — FNM_RE Phase 4: 引用冻结 + 翻译单元 + 结构复核。
//!
//! ←→ Python:
//! - `FNM_RE/modules/ref_freeze.py` (~678 行) → `ref_freeze/`
//! - `FNM_RE/stages/units.py` (~868 行) → `units/`
//! - `FNM_RE/stages/reviews.py` (~210 行) → `reviews.rs`
//! - `document/text_processing.py` (~350 行) → `text/`
//!
//! # 上游依赖
//!
//! - Phase 3 已完成（14/14 任务）
//! - 已知 Phase 2 cascade 影响 5 个 Phase 3 parity 测试 `#[ignore]`——
//!   不阻塞 Phase 4 启动

#![deny(unused_must_use)]

pub mod input;
pub mod output;
pub mod ref_freeze;
pub mod reviews;
pub mod segments;
pub mod text;
pub mod units;

use anyhow::Result;
#[cfg(test)]
use fnm_core::records::Phase3Summary;
use input::Phase4Input;
use output::Phase4Output;

/// ←→ Python `build_phase4_structure`
///
/// Phase 4 顶层编排：调用 ref_freeze → units → reviews，组装 Phase4Output。
pub fn build_phase4_structure(input: Phase4Input<'_>) -> Result<Phase4Output> {
    // 1. ref_freeze: 构建 frozen_units
    let frozen_units = ref_freeze::build_frozen_units(
        input.chapter_layers,
        input.note_link_table,
        None, // book_structure_model
        input.max_body_chars,
        &input.pipeline_run_id,
    )?;
    let frozen_refs = frozen_units.ref_map.clone();
    let freeze_summary = frozen_units.freeze_summary.clone();

    // 2. units: 翻译单元由 frozen units 一对一映射生成
    let (translation_units, units_summary) =
        units::build_translation_units(&frozen_units);

    // 3. reviews: 构建 structure_reviews
    //     freeze_error_rows = ref_map 中注入失败的条目（policy_skip 除外）
    let freeze_error_rows: Vec<fnm_core::records::FrozenRefEntry> = frozen_refs
        .iter()
        .filter(|r| {
            r.skip_category == "ceiling_skip" || r.skip_category == "error_skip"
        })
        .cloned()
        .collect();
    let (structure_reviews, reviews_summary) = reviews::build_structure_reviews(
        input.chapters,
        input.body_anchors,
        input.effective_note_links,
        input.summary,
        input.ignored_link_override_count,
        input.invalid_override_count,
        &freeze_error_rows,
    );

    // 4. 组装 summary
    let summary = serde_json::json!({
        "freeze_summary": freeze_summary,
        "units_summary": units_summary,
        "reviews_summary": reviews_summary,
    });

    // 5. 组装 diagnostics
    let diagnostics = serde_json::json!({
        "frozen_units_count": frozen_units.body_units.len() + frozen_units.note_units.len(),
        "frozen_ref_count": frozen_refs.len(),
        "translation_unit_count": translation_units.len(),
        "structure_review_count": structure_reviews.len(),
        "freeze_error_count": freeze_error_rows.len(),
    });

    Ok(Phase4Output {
        frozen_units,
        frozen_refs,
        translation_units,
        structure_reviews,
        summary,
        diagnostics,
    })
}


/// ←→ Python `persist_phase4`
///
/// Phase 4 DB 持久化：写入 fnm_translation_units + fnm_structure_reviews。
pub fn persist_phase4(
    repo: &dyn fnm_core::db::Repository,
    doc_id: &str,
    output: &Phase4Output,
) -> Result<()> {
    let products = output.to_products();
    repo.replace_fnm_phase4_products(doc_id, &products)?;
    Ok(())
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_phase4_structure_empty() {
        let chapter_layers = fnm_phase2::chapter_split::ChapterLayers::default();
        let note_link_table = fnm_phase3::note_linking::NoteLinkTable::default();
        let summary = Phase3Summary::default();

        let input = Phase4Input {
            chapter_layers: &chapter_layers,
            note_link_table: &note_link_table,
            raw_pages: &[],
            page_partitions: &[],
            chapters: &[],
            body_anchors: &[],
            effective_note_links: &[],
            note_regions: &[],
            summary: &summary,
            max_body_chars: 6000,
            pipeline_run_id: "test".to_string(),
            ignored_link_override_count: 0,
            invalid_override_count: 0,
        };

        let result = build_phase4_structure(input);
        assert!(result.is_ok());
        let output = result.unwrap();
        assert!(output.translation_units.is_empty());
        // structure_reviews 可能不为空（取决于 summary 默认值）
        assert!(output.frozen_refs.is_empty());
    }
}

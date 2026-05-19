//! DB-driven pipeline 入口（每个 phase 完成后持久化到 SQLite）。
//!
//! ←→ Python `FNM_RE/app/mainline.py::run_phase6_pipeline_for_doc()`
//!
//! 本模块和纯内存 [`crate::pipeline::run_pipeline`] 的区别：
//! - 每个 phase 完成后立即调 `repo.replace_fnm_phaseN_products()` 持久化
//! - 在 phase 3 后可选触发 LLM repair（基于 DB 中 phase3 产物 + 写 review_overrides）
//! - 失败时已持久化的前置 phase 数据保留，下次可从 start_phase 续跑

use crate::error::{OrchestratorError, Result};
use crate::pipeline;
use crate::types::{
    ModulePipelineSnapshot, PipelineConfig, SerPhase1, SerPhase2, SerPhase3, SerPhase4, SerPhase5,
    SerPhase6,
};

use fnm_core::db::{
    Phase1Products, Phase2Products, Phase3Products, Phase4Products, Phase5Products, Phase6Products,
    Repository,
};
use fnm_phase1::input::{RawPage, TocItem};
use fnm_phase2::chapter_split::build_chapter_layers;

/// DB-driven 入口：跑 phase1→6 并持久化到 SQLite。
///
/// ←→ Python `FNM_RE/app/mainline.py::run_phase6_pipeline_for_doc()`
///
/// 与纯内存 [`pipeline::run_pipeline`] 的关系：
/// 本函数内联了 phase 调用，每个 phase 完成后立即 persist；
/// caller 无需再单独持久化 snapshot。
pub fn run_pipeline_for_doc<R: Repository>(
    repo: &R,
    doc_id: &str,
    raw_pages: Vec<RawPage>,
    toc_items: Vec<TocItem>,
    config: PipelineConfig,
) -> Result<ModulePipelineSnapshot> {
    let pipeline_run_id = pipeline::generate_run_id(doc_id);

    let mut snapshot = ModulePipelineSnapshot {
        doc_id: doc_id.to_string(),
        slug: config.slug.clone(),
        pipeline_run_id: pipeline_run_id.clone(),
        ..Default::default()
    };

    // ── Phase 1 ──
    let phase1 = pipeline::run_phase1(&raw_pages, &toc_items, &config)?;
    let phase1_products = Phase1Products {
        pages: phase1.structure.pages.clone(),
        chapters: phase1.structure.chapters.clone(),
        heading_candidates: phase1.structure.heading_candidates.clone(),
        section_heads: phase1.structure.section_heads.clone(),
    };
    repo.replace_fnm_phase1_products(doc_id, &phase1_products)
        .map_err(|e| OrchestratorError::Phase1(anyhow::anyhow!("persist phase1: {}", e)))?;
    snapshot.phase1 = Some(SerPhase1 {
        pages: phase1_products.pages,
        chapters: phase1_products.chapters,
        heading_candidates: phase1_products.heading_candidates,
        section_heads: phase1_products.section_heads,
    });

    // ── Phase 2 ──
    let phase2 = pipeline::run_phase2(&phase1, &raw_pages, &config)?;
    let phase2_products = Phase2Products {
        pages: phase1.structure.pages.clone(),
        chapters: phase1.structure.chapters.clone(),
        heading_candidates: phase1.structure.heading_candidates.clone(),
        section_heads: phase1.structure.section_heads.clone(),
        note_regions: phase2.note_regions.clone(),
        chapter_note_modes: phase2.chapter_note_modes.clone(),
        note_items: phase2.note_items.clone(),
    };
    repo.replace_fnm_phase2_products(doc_id, &phase2_products)
        .map_err(|e| OrchestratorError::Phase2(anyhow::anyhow!("persist phase2: {}", e)))?;
    snapshot.phase2 = Some(SerPhase2 {
        note_regions: phase2.note_regions.clone(),
        note_items: phase2.note_items.clone(),
        chapter_note_modes: phase2.chapter_note_modes.clone(),
    });

    // ── Phase 3 ──
    let phase3 = pipeline::run_phase3(&phase1, &phase2, &raw_pages, &config)?;
    let phase3_products = Phase3Products {
        body_anchors: phase3.body_anchors.clone(),
        note_links: phase3.note_links.clone(),
    };
    repo.replace_fnm_phase3_products(doc_id, &phase3_products)
        .map_err(|e| OrchestratorError::Phase3(anyhow::anyhow!("persist phase3: {}", e)))?;
    snapshot.phase3 = Some(SerPhase3 {
        body_anchors: phase3_products.body_anchors,
        note_links: phase3_products.note_links,
    });

    // ── Phase 3.5: LLM repair（暂未集成）──
    // 后续 commit 接入：调 fnm_llm_repair::run_llm_repair(...) 写 review_overrides，
    // phase4 读取应用 override 后的 phase3 产物。

    // ── Phase 4 ──
    let chapter_layers = build_chapter_layers(
        &phase1.structure.chapters,
        &phase2.note_regions,
        &phase2.note_items,
        &phase1.structure.pages,
        &raw_pages,
    );
    let phase4 = pipeline::run_phase4(
        &phase1,
        &phase2,
        &phase3,
        &chapter_layers,
        &raw_pages,
        &pipeline_run_id,
        &config,
    )?;
    let phase4_products = Phase4Products {
        translation_units: phase4.translation_units.clone(),
        structure_reviews: phase4.structure_reviews.clone(),
    };
    repo.replace_fnm_phase4_products(doc_id, &phase4_products)
        .map_err(|e| OrchestratorError::Phase4(anyhow::anyhow!("persist phase4: {}", e)))?;
    snapshot.phase4 = Some(SerPhase4 {
        translation_units: phase4_products.translation_units,
        structure_reviews: phase4_products.structure_reviews,
    });

    // ── Phase 5 ──
    let phase5 = pipeline::run_phase5(&phase4, &phase3, &chapter_layers, &phase1, &config)?;
    let phase5_products = Phase5Products {
        chapter_markdowns: phase5.chapter_markdowns.chapters.clone(),
        diagnostic_pages: Vec::new(),
        diagnostic_notes: Vec::new(),
    };
    repo.replace_fnm_phase5_products(doc_id, &phase5_products)
        .map_err(|e| OrchestratorError::Phase5(anyhow::anyhow!("persist phase5: {}", e)))?;
    snapshot.phase5 = Some(SerPhase5 {
        chapter_count: phase5.chapter_markdowns.chapters.len() as i64,
        merge_summary: phase5.chapter_markdowns.merge_summary.clone(),
    });

    // ── Phase 6 ──
    let phase6 = pipeline::run_phase6(&phase5, &phase1, &config)?;
    let phase6_products = Phase6Products {
        export_chapters: phase6.export_bundle.chapters.clone(),
        export_bundle: phase6.export_bundle.clone(),
        export_audit: phase6.export_audit.clone(),
    };
    repo.replace_fnm_phase6_products(doc_id, &phase6_products)
        .map_err(|e| OrchestratorError::Phase6(anyhow::anyhow!("persist phase6: {}", e)))?;
    snapshot.phase6 = Some(SerPhase6 {
        export_bundle: phase6_products.export_bundle,
        export_audit: phase6_products.export_audit,
    });

    snapshot.run_meta = serde_json::json!({
        "pipeline_run_id": pipeline_run_id,
        "start_phase": format!("{:?}", config.start_phase),
        "phase_state": "done",
        "persisted": true,
    });

    Ok(snapshot)
}

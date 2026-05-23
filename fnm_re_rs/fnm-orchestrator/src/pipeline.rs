//! Pipeline 顺序串联 phase1 → phase2 → phase3 → phase4 → phase5 → phase6。
//!
//! ←→ Python `FNM_RE/app/pipeline.py::build_module_pipeline_snapshot()`
//!
//! 当前 MVP 范围：
//! - 不含 LLM repair 回环（Step 3.5 由 caller 显式调用 `fnm_llm_repair::run_llm_repair`
//!   后重新触发 phase3+ 的执行）
//! - 不含 shadow mode（FNM_SHADOW_RUST_PHASES）
//! - 不含 DB 持久化（caller 拿到 ModulePipelineSnapshot 后自行 persist；
//!   或调用 `mainline::run_phase6_pipeline_for_doc` DB-driven 版本）

use crate::error::{OrchestratorError, Result};
use crate::types::{
    ModulePipelineSnapshot, Phase1Snapshot, Phase2Snapshot, Phase3Snapshot, Phase4Snapshot,
    Phase5Snapshot, Phase6Snapshot, PipelineConfig, SerPhase1, SerPhase2, SerPhase3, SerPhase4,
    SerPhase5, SerPhase6,
};

use fnm_phase1::input::{RawPage, TocItem};
use fnm_phase2::chapter_split::{build_chapter_layers, ChapterLayers};

/// Pipeline 完整运行：phase1 → phase6（不含 LLM repair 回环）。
///
/// ←→ Python `build_module_pipeline_snapshot()` 的 start_phase="toc" 分支。
pub fn run_pipeline(
    pages: Vec<RawPage>,
    toc_items: Vec<TocItem>,
    config: PipelineConfig,
) -> Result<ModulePipelineSnapshot> {
    let pipeline_run_id = generate_run_id(&config.doc_id);

    let mut snapshot = ModulePipelineSnapshot {
        doc_id: config.doc_id.clone(),
        slug: config.slug.clone(),
        pipeline_run_id: pipeline_run_id.clone(),
        ..Default::default()
    };

    // ── Phase 1 ──
    let phase1 = run_phase1(&pages, &toc_items, &config)?;
    snapshot.phase1 = Some(SerPhase1 {
        pages: phase1.structure.pages.clone(),
        chapters: phase1.structure.chapters.clone(),
        heading_candidates: phase1.structure.heading_candidates.clone(),
        section_heads: phase1.structure.section_heads.clone(),
    });

    // ── Phase 2 ──
    let phase2 = run_phase2(&phase1, &pages, &config)?;
    snapshot.phase2 = Some(SerPhase2 {
        note_regions: phase2.note_regions.clone(),
        note_items: phase2.note_items.clone(),
        chapter_note_modes: phase2.chapter_note_modes.clone(),
    });

    // ── Phase 3 ──
    let phase3 = run_phase3(&phase1, &phase2, &pages, &config)?;
    snapshot.phase3 = Some(SerPhase3 {
        body_anchors: phase3.body_anchors.clone(),
        note_links: phase3.note_links.clone(),
    });

    // ── Phase 4 ──
    let chapter_layers = build_chapter_layers(
        &phase1.structure.chapters,
        &phase2.note_regions,
        &phase2.note_items,
        &phase1.structure.pages,
        &pages,
    );
    let phase4 = run_phase4(
        &phase1,
        &phase2,
        &phase3,
        &chapter_layers,
        &pages,
        &pipeline_run_id,
        &config,
    )?;
    snapshot.phase4 = Some(SerPhase4 {
        translation_units: phase4.translation_units.clone(),
        structure_reviews: phase4.structure_reviews.clone(),
    });

    // ── Phase 5 ──
    let phase5 = run_phase5(&phase4, &phase3, &chapter_layers, &phase1, &config)?;
    snapshot.phase5 = Some(SerPhase5 {
        chapter_count: phase5.chapter_markdowns.chapters.len() as i64,
        merge_summary: phase5.chapter_markdowns.merge_summary.clone(),
    });

    // ── Phase 6 ──
    let phase6 = run_phase6(&phase5, &phase4, &phase1, &config)?;
    snapshot.phase6 = Some(SerPhase6 {
        export_bundle: phase6.export_bundle.clone(),
        export_audit: phase6.export_audit.clone(),
    });

    snapshot.run_meta = serde_json::json!({
        "pipeline_run_id": pipeline_run_id,
        "start_phase": format!("{:?}", config.start_phase),
        "phase_state": "done",
    });

    Ok(snapshot)
}

pub(crate) fn generate_run_id(doc_id: &str) -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    use std::hash::{Hash, Hasher};
    doc_id.hash(&mut hasher);
    now.hash(&mut hasher);
    format!("{:016x}", hasher.finish())
}

pub(crate) fn run_phase1(
    pages: &[RawPage],
    toc_items: &[TocItem],
    config: &PipelineConfig,
) -> Result<Phase1Snapshot> {
    let phase1_config = fnm_phase1::toc_structure::Phase1Config {
        manual_page_overrides: None,
        endnotes_start_page: config
            .visual_toc_bundle
            .as_ref()
            .and_then(|b| b.get("endnotes_start_page"))
            .and_then(|v| v.as_i64()),
        pdf_path: if config.pdf_path.is_empty() {
            None
        } else {
            Some(config.pdf_path.clone())
        },
        doc_id: if config.doc_id.is_empty() {
            None
        } else {
            Some(config.doc_id.clone())
        },
        skip_llm_verify: config.skip_llm_verify,
    };

    let toc_items_opt = if toc_items.is_empty() {
        None
    } else {
        Some(toc_items)
    };

    let output =
        fnm_phase1::toc_structure::build_phase1_structure(pages, toc_items_opt, &phase1_config)
            .map_err(OrchestratorError::Phase1)?;

    Ok(Phase1Snapshot {
        structure: output.structure,
        diagnostics: output.diagnostics,
    })
}

pub(crate) fn run_phase2(
    phase1: &Phase1Snapshot,
    pages: &[RawPage],
    config: &PipelineConfig,
) -> Result<Phase2Snapshot> {
    let post_body_titles: std::collections::HashSet<String> = phase1
        .structure
        .summary
        .post_body_titles
        .iter()
        .cloned()
        .collect();

    let phase2_config = fnm_phase2::input::Phase2Config {
        skip_sup_recovery: config.skip_sup_recovery,
        skip_llm_verify: config.skip_llm_verify,
    };

    let input = fnm_phase2::input::Phase2Input {
        phase1_chapters: &phase1.structure.chapters,
        phase1_pages: &phase1.structure.pages,
        phase1_section_heads: &phase1.structure.section_heads,
        phase1_heading_candidates: &phase1.structure.heading_candidates,
        raw_pages: pages,
        pdf_path: if config.pdf_path.is_empty() {
            None
        } else {
            Some(config.pdf_path.as_str())
        },
        config: phase2_config,
        post_body_titles,
    };

    let output =
        fnm_phase2::build_phase2_structure_sync(input).map_err(OrchestratorError::Phase2)?;

    // Phase2 上游 phase1 数据原样透传，phase2 自身产物覆盖 chapters/notes
    let structure = fnm_core::records::Phase2Structure {
        pages: phase1.structure.pages.clone(),
        heading_candidates: phase1.structure.heading_candidates.clone(),
        chapters: output.chapters.clone(),
        section_heads: phase1.structure.section_heads.clone(),
        note_regions: output.note_regions.clone(),
        note_items: output.note_items.clone(),
        chapter_note_modes: output.chapter_note_modes.clone(),
        summary: fnm_core::records::Phase2Summary {
            chapter_endnote_region_alignment_ok: output
                .note_regions
                .iter()
                .filter(|r| r.note_kind == fnm_core::types::NoteKind::Endnote)
                .all(|r| r.region_marker_alignment_ok),
            ..Default::default()
        },
    };

    Ok(Phase2Snapshot {
        structure,
        chapter_note_modes: output.chapter_note_modes,
        note_regions: output.note_regions,
        note_items: output.note_items,
        diagnostics: output.diagnostics,
    })
}

pub(crate) fn run_phase3(
    phase1: &Phase1Snapshot,
    phase2: &Phase2Snapshot,
    pages: &[RawPage],
    config: &PipelineConfig,
) -> Result<Phase3Snapshot> {
    let phase3_config = fnm_phase3::input::Phase3Config {
        skip_llm_verify: true,
    };

    let overrides_ref = config.review_overrides.as_ref();

    let input = fnm_phase3::input::Phase3Input {
        phase1_chapters: &phase1.structure.chapters,
        phase1_pages: &phase1.structure.pages,
        phase1_heading_candidates: &phase1.structure.heading_candidates,
        phase1_section_heads: &phase1.structure.section_heads,
        phase2_note_regions: &phase2.note_regions,
        phase2_note_items: &phase2.note_items,
        phase2_chapter_note_modes: &phase2.chapter_note_modes,
        raw_pages: pages,
        pdf_path: if config.pdf_path.is_empty() {
            None
        } else {
            Some(config.pdf_path.as_str())
        },
        config: phase3_config,
        overrides: overrides_ref,
    };

    let output = fnm_phase3::build_phase3_structure(input).map_err(OrchestratorError::Phase3)?;

    Ok(Phase3Snapshot {
        body_anchors: output.structure.body_anchors.clone(),
        note_links: output.structure.note_links.clone(),
        structure: output.structure,
        note_link_table: output.note_link_table,
        diagnostics: serde_json::to_value(&output.diagnostics).unwrap_or_default(),
    })
}

pub(crate) fn run_phase4(
    phase1: &Phase1Snapshot,
    phase2: &Phase2Snapshot,
    phase3: &Phase3Snapshot,
    chapter_layers: &ChapterLayers,
    pages: &[RawPage],
    pipeline_run_id: &str,
    config: &PipelineConfig,
) -> Result<Phase4Snapshot> {
    let max_body_chars = if config.max_body_chars > 0 {
        config.max_body_chars
    } else {
        6000
    };

    let input = fnm_phase4::input::Phase4Input {
        chapter_layers,
        note_link_table: &phase3.note_link_table,
        raw_pages: pages,
        page_partitions: &phase1.structure.pages,
        chapters: &phase1.structure.chapters,
        body_anchors: &phase3.structure.body_anchors,
        effective_note_links: &phase3.structure.note_links,
        note_regions: &phase2.note_regions,
        summary: &phase3.structure.summary,
        max_body_chars,
        pipeline_run_id: pipeline_run_id.to_string(),
        ignored_link_override_count: 0,
        invalid_override_count: 0,
    };

    let output = fnm_phase4::build_phase4_structure(input).map_err(OrchestratorError::Phase4)?;

    Ok(Phase4Snapshot {
        frozen_units: output.frozen_units,
        frozen_refs: output.frozen_refs,
        translation_units: output.translation_units,
        structure_reviews: output.structure_reviews,
        summary: output.summary,
        diagnostics: output.diagnostics,
    })
}

pub(crate) fn run_phase5(
    phase4: &Phase4Snapshot,
    phase3: &Phase3Snapshot,
    chapter_layers: &ChapterLayers,
    phase1: &Phase1Snapshot,
    config: &PipelineConfig,
) -> Result<Phase5Snapshot> {
    let chapter_markdowns = fnm_phase5::build_chapter_markdown_set(
        &phase4.frozen_units,
        &phase3.note_link_table,
        chapter_layers,
        None,
        config.include_diagnostic_entries,
        Some(&phase1.structure.section_heads),
    )
    .map_err(OrchestratorError::Phase5)?;

    Ok(Phase5Snapshot { chapter_markdowns })
}

pub(crate) fn run_phase6(
    phase5: &Phase5Snapshot,
    phase4: &Phase4Snapshot,
    phase1: &Phase1Snapshot,
    config: &PipelineConfig,
) -> Result<Phase6Snapshot> {
    let (export_bundle, export_zip, export_audit, diagnostics) =
        fnm_phase6::build_module_export_bundle(
            &phase5.chapter_markdowns,
            &phase1.structure,
            None,
            &config.slug,
            &config.doc_id,
            &phase4.structure_reviews,
        )
        .map_err(OrchestratorError::Phase6)?;

    Ok(Phase6Snapshot {
        export_bundle,
        export_zip,
        export_audit,
        diagnostics,
    })
}

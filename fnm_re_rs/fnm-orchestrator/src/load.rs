//! 从 DB 加载 phase1-6 全部数据 → Phase6Structure。
//!
//! ←→ Python `FNM_RE/app/mainline.py::load_phase6_for_doc()`

use crate::error::{OrchestratorError, Result};
use fnm_core::db::Repository;
use fnm_core::records::*;
use fnm_core::types::NoteKind;

/// 从 DB 读 phase1-6 全部表 → 组装 Phase6Structure。
///
/// `include_diag=false` 时 diagnostic_pages/notes 不读，提速。
///
/// ←→ Python `FNM_RE/app/mainline.py::load_phase6_for_doc()`
pub fn load_phase6_structure(
    repo: &dyn Repository,
    doc_id: &str,
    include_diag: bool,
) -> Result<Phase6Structure> {
    let pages = repo
        .list_fnm_pages(doc_id)
        .map_err(OrchestratorError::Phase1)?;
    if pages.is_empty() {
        return Err(OrchestratorError::Phase1(anyhow::anyhow!(
            "doc_id '{}' not found or has no pages",
            doc_id
        )));
    }
    let chapters = repo
        .list_fnm_chapters(doc_id)
        .map_err(OrchestratorError::Phase1)?;
    let heading_candidates = repo
        .list_fnm_heading_candidates(doc_id)
        .map_err(OrchestratorError::Phase1)?;
    let section_heads = repo
        .list_fnm_section_heads(doc_id)
        .map_err(OrchestratorError::Phase1)?;

    let note_regions = repo
        .list_fnm_note_regions(doc_id)
        .map_err(OrchestratorError::Phase2)?;
    let note_items = repo
        .list_fnm_note_items(doc_id)
        .map_err(OrchestratorError::Phase2)?;
    let chapter_note_modes = repo
        .list_fnm_chapter_note_modes(doc_id)
        .map_err(OrchestratorError::Phase2)?;

    let body_anchors = repo
        .list_fnm_body_anchors(doc_id)
        .map_err(OrchestratorError::Phase3)?;
    let note_links = repo
        .list_fnm_note_links(doc_id)
        .map_err(OrchestratorError::Phase3)?;

    let translation_units = repo
        .list_fnm_translation_units(doc_id)
        .map_err(OrchestratorError::Phase4)?;
    let structure_reviews = repo
        .list_fnm_structure_reviews(doc_id)
        .map_err(OrchestratorError::Phase4)?;

    let export_chapters = repo
        .list_fnm_export_chapters(doc_id)
        .map_err(OrchestratorError::Phase6)?;
    let export_bundle = repo
        .list_fnm_export_bundle(doc_id)
        .map_err(OrchestratorError::Phase6)?;
    let has_export_bundle = export_bundle.is_some();
    let export_bundle = export_bundle.unwrap_or_default();
    let export_audit = repo
        .list_fnm_export_audit(doc_id)
        .map_err(OrchestratorError::Phase6)?;
    let has_export_audit = export_audit.is_some();
    let export_audit = export_audit.unwrap_or_default();

    let has_export_audit_content = has_export_audit
        && (!export_audit.structure_state.is_empty()
            || !export_audit.blocking_reasons.is_empty()
            || export_audit.can_ship);

    let (diagnostic_pages, diagnostic_notes) = if include_diag {
        let diag_pages = repo
            .list_fnm_diagnostic_pages(doc_id)
            .map_err(OrchestratorError::Phase5)?;
        let diag_notes = repo
            .list_fnm_diagnostic_notes(doc_id)
            .map_err(OrchestratorError::Phase5)?;
        (diag_pages, diag_notes)
    } else {
        (vec![], vec![])
    };

    let chapter_endnote_region_alignment_ok = note_regions
        .iter()
        .filter(|r| r.note_kind == NoteKind::Endnote)
        .all(|r| r.region_marker_alignment_ok);

    // 旧 blocking_reasons 不再携带到 status.blocking_reasons（审计每次独立计算）
    let structure_state: String = if has_export_audit_content {
        export_audit.structure_state.clone()
    } else {
        "phase6_not_available".into()
    };
    let mut blocking_reasons: Vec<String> = if has_export_audit_content {
        vec![]
    } else {
        vec!["export_audit_missing".into()]
    };
    if !has_export_bundle {
        blocking_reasons.push("export_bundle_missing".into());
    }

    let export_ready = has_export_bundle && has_export_audit_content;

    Ok(Phase6Structure {
        pages,
        heading_candidates,
        chapters,
        section_heads,
        note_regions,
        note_items,
        chapter_note_modes,
        body_anchors,
        // Phase 3 persist 时已将 review_overrides 物化到 note_links，
        // DB 只存一份物化后的链接。load 阶段 note_links == effective_note_links。
        note_links: note_links.clone(),
        effective_note_links: note_links,
        structure_reviews,
        translation_units,
        diagnostic_pages,
        diagnostic_notes,
        export_chapters,
        export_bundle,
        export_audit,
        status: StructureStatusRecord {
            structure_state,
            blocking_reasons,
            chapter_endnote_region_alignment_ok,
            toc_semantic_contract_ok: true,
            export_ready_test: export_ready,
            export_ready_real: export_ready,
            ..Default::default()
        },
        summary: Phase6Summary::default(),
    })
}

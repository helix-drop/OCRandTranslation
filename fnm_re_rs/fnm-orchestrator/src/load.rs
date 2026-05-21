//! 从 DB 加载 phase1-6 全部数据 → Phase6Structure。
//!
//! ←→ Python `FNM_RE/app/mainline.py::load_phase6_for_doc()`

use crate::error::{OrchestratorError, Result};
use fnm_core::db::Repository;
use fnm_core::records::*;

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
        .map_err(|e| OrchestratorError::Phase1(e.into()))?;
    if pages.is_empty() {
        return Err(OrchestratorError::Phase1(anyhow::anyhow!(
            "doc_id '{}' not found or has no pages",
            doc_id
        )));
    }
    let chapters = repo
        .list_fnm_chapters(doc_id)
        .map_err(|e| OrchestratorError::Phase1(e.into()))?;
    let heading_candidates = repo
        .list_fnm_heading_candidates(doc_id)
        .map_err(|e| OrchestratorError::Phase1(e.into()))?;
    let section_heads = repo
        .list_fnm_section_heads(doc_id)
        .map_err(|e| OrchestratorError::Phase1(e.into()))?;

    let note_regions = repo
        .list_fnm_note_regions(doc_id)
        .map_err(|e| OrchestratorError::Phase2(e.into()))?;
    let note_items = repo
        .list_fnm_note_items(doc_id)
        .map_err(|e| OrchestratorError::Phase2(e.into()))?;
    let chapter_note_modes = repo
        .list_fnm_chapter_note_modes(doc_id)
        .map_err(|e| OrchestratorError::Phase2(e.into()))?;

    let body_anchors = repo
        .list_fnm_body_anchors(doc_id)
        .map_err(|e| OrchestratorError::Phase3(e.into()))?;
    let note_links = repo
        .list_fnm_note_links(doc_id)
        .map_err(|e| OrchestratorError::Phase3(e.into()))?;

    let translation_units = repo
        .list_fnm_translation_units(doc_id)
        .map_err(|e| OrchestratorError::Phase4(e.into()))?;
    let structure_reviews = repo
        .list_fnm_structure_reviews(doc_id)
        .map_err(|e| OrchestratorError::Phase4(e.into()))?;

    let export_chapters = repo
        .list_fnm_export_chapters(doc_id)
        .map_err(|e| OrchestratorError::Phase6(e.into()))?;
    let export_bundle = repo
        .list_fnm_export_bundle(doc_id)
        .map_err(|e| OrchestratorError::Phase6(e.into()))?
        .unwrap_or_default();
    let export_audit = repo
        .list_fnm_export_audit(doc_id)
        .map_err(|e| OrchestratorError::Phase6(e.into()))?
        .unwrap_or_default();

    let (diagnostic_pages, diagnostic_notes) = if include_diag {
        let diag_pages = repo
            .list_fnm_diagnostic_pages(doc_id)
            .map_err(|e| OrchestratorError::Phase5(e.into()))?;
        let diag_notes = repo
            .list_fnm_diagnostic_notes(doc_id)
            .map_err(|e| OrchestratorError::Phase5(e.into()))?;
        (diag_pages, diag_notes)
    } else {
        (vec![], vec![])
    };

    Ok(Phase6Structure {
        pages,
        heading_candidates,
        chapters,
        section_heads,
        note_regions,
        note_items,
        chapter_note_modes,
        body_anchors,
        note_links: note_links.clone(),
        effective_note_links: note_links,
        structure_reviews,
        translation_units,
        diagnostic_pages,
        diagnostic_notes,
        export_chapters,
        export_bundle,
        export_audit,
        status: StructureStatusRecord::default(),
        summary: Phase6Summary::default(),
    })
}

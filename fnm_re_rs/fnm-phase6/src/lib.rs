//! `fnm-phase6` — FNM_RE Phase 6: 导出 + 审计 + diagnostics。
//!
//! ←→ Python:
//! - `FNM_RE/stages/export.py` (~751 行) → `export/`
//! - `FNM_RE/stages/export_contract.py` (~224 行)
//! - `FNM_RE/stages/export_footnote.py` (~407 行)
//! - `FNM_RE/stages/export_audit.py` (~688 行)
//! - `FNM_RE/stages/diagnostics.py` (~336 行)
//! - `FNM_RE/modules/book_assemble.py` (~543 行)

#![deny(unused_must_use)]

pub mod book_assemble;
pub mod diagnostics;
mod export;
pub mod export_audit;

use anyhow::Result;
use fnm_core::records::{
    ExportAuditReportRecord, ExportBundleRecord, Phase1Structure, StructureReviewRecord,
};
use fnm_phase2::chapter_split::structure_model::BookStructureModel;

pub use export::zip::build_export_zip;

/// 导出 bundle 构建。
///
/// ←→ Python `build_export_bundle()` (book_assemble.py:398)
pub fn build_module_export_bundle(
    chapter_markdown_set: &fnm_core::records::ChapterMarkdownSet,
    phase1: &Phase1Structure,
    book_structure_model: Option<&BookStructureModel>,
    slug: &str,
    doc_id: &str,
    structure_reviews: &[StructureReviewRecord],
) -> Result<(
    ExportBundleRecord,
    Vec<u8>,
    ExportAuditReportRecord,
    serde_json::Value,
)> {
    book_assemble::build_module_export_bundle(
        chapter_markdown_set,
        phase1,
        book_structure_model,
        slug,
        doc_id,
        structure_reviews,
    )
}

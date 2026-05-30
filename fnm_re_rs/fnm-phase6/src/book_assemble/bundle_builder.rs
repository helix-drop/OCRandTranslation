//! Export bundle 构建逻辑。
//!
//! ←→ Python `book_assemble.py` 中的子步骤

use std::collections::HashMap;

use fnm_core::records::{
    ExportAuditReportRecord, ExportBundleRecord, ExportChapterRecord, Phase6Structure,
    Phase6Summary, StructureStatusRecord, SummaryTocBase,
};

/// 构建 Phase6Structure 用于审计。
pub(super) fn build_phase6_for_audit(
    bundle_record: &ExportBundleRecord,
    structure_reviews: &[fnm_core::records::StructureReviewRecord],
    note_items: Vec<fnm_core::records::NoteItemRecord>,
    container_titles: Vec<String>,
    post_body_titles: Vec<String>,
    back_matter_titles: Vec<String>,
    toc_role_summary: serde_json::Value,
) -> Phase6Structure {
    Phase6Structure {
        export_bundle: bundle_record.clone(),
        structure_reviews: structure_reviews.to_vec(),
        note_items,
        status: StructureStatusRecord {
            structure_state: "done".to_string(),
            ..Default::default()
        },
        summary: Phase6Summary {
            toc: SummaryTocBase {
                container_titles,
                post_body_titles,
                back_matter_titles,
                toc_role_summary,
                ..Default::default()
            },
            ..Default::default()
        },
        ..Default::default()
    }
}

/// 计算 book_assemble 级别的 gates（order_follows_toc、contamination、semantic_contract）。
pub(super) fn compute_book_assemble_gates(
    report_record: &ExportAuditReportRecord,
    order_follows_toc: bool,
    no_cross_chapter_contamination: bool,
    export_semantic_contract_ok: bool,
    missing_chapter_ids: &[String],
    extra_chapter_ids: &[String],
) -> (ExportAuditReportRecord, bool) {
    let gates_ok =
        order_follows_toc && no_cross_chapter_contamination && export_semantic_contract_ok;

    let mut gate_blockers: i64 = 0;
    let mut gate_reasons: Vec<String> = Vec::new();

    if !order_follows_toc {
        gate_blockers += 1;
        gate_reasons.push(format!(
            "gate_order_follows_toc: missing={:?}, extra={:?}",
            missing_chapter_ids, extra_chapter_ids
        ));
    }
    if !no_cross_chapter_contamination {
        gate_blockers += 1;
        gate_reasons.push("gate_no_cross_chapter_contamination".to_string());
    }
    if !export_semantic_contract_ok {
        gate_blockers += 1;
        gate_reasons.push("gate_export_semantic_contract_ok".to_string());
    }

    let mut final_blocking_reasons = report_record.blocking_reasons.clone();
    final_blocking_reasons.extend(gate_reasons);

    let updated_report = ExportAuditReportRecord {
        can_ship: report_record.can_ship && gates_ok,
        blocking_issue_count: report_record.blocking_issue_count + gate_blockers,
        blocking_reasons: final_blocking_reasons,
        ..report_record.clone()
    };

    (updated_report, gates_ok)
}

/// 构建语义摘要的输入参数。
pub(super) struct SemanticSummaryInput<'a> {
    pub export_chapters: &'a [ExportChapterRecord],
    pub chapter_files: &'a HashMap<String, String>,
    pub files: &'a HashMap<String, String>,
    pub missing_chapter_ids: &'a [String],
    pub extra_chapter_ids: &'a [String],
    pub order_follows_toc: bool,
    pub no_cross_chapter_contamination: bool,
    pub report_record: &'a ExportAuditReportRecord,
    pub audit_issue_file_summary: &'a [serde_json::Value],
    pub semantic: &'a HashMap<String, bool>,
    pub export_semantic_contract_ok: bool,
}

/// 构建语义摘要。
pub(super) fn build_semantic_summary(input: &SemanticSummaryInput) -> serde_json::Value {
    let base_summary = serde_json::json!({
        "chapter_count": input.export_chapters.len(),
        "chapter_file_count": input.chapter_files.len(),
        "file_count": input.files.len(),
        "missing_chapter_ids": input.missing_chapter_ids,
        "extra_chapter_ids": input.extra_chapter_ids,
        "gate_order_follows_toc": input.order_follows_toc,
        "gate_no_cross_chapter_contamination": input.no_cross_chapter_contamination,
        "audit_blocking_issue_count": input.report_record.blocking_issue_count,
        "audit_issue_file_count": input.audit_issue_file_summary.len(),
        "audit_issue_file_preview": input.audit_issue_file_summary,
    });

    let mut map = serde_json::Map::new();
    if let Some(obj) = base_summary.as_object() {
        for (k, v) in obj {
            map.insert(k.clone(), v.clone());
        }
    }
    for (k, v) in input.semantic {
        map.insert(k.clone(), serde_json::Value::Bool(*v));
    }
    map.insert(
        "export_semantic_contract_ok".to_string(),
        serde_json::Value::Bool(input.export_semantic_contract_ok),
    );

    serde_json::Value::Object(map)
}

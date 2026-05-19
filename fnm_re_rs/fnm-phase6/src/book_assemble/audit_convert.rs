//! ←→ FNM_RE/modules/book_assemble.py
//! 翻译的函数：
//!   to_export_audit_report  ←→ _to_export_audit_report (book_assemble.py:141)

use serde_json::Value;

use fnm_core::records::ExportAuditReportRecord;

/// 将 ExportAuditReportRecord 转换为审计报告 JSON 值。
///
/// ←→ Python `_to_export_audit_report()` (book_assemble.py:141)
pub fn to_export_audit_report(report: &ExportAuditReportRecord) -> Value {
    let files: Vec<Value> = report
        .files
        .iter()
        .map(|item| {
            serde_json::json!({
                "path": item.path,
                "title": item.title,
                "page_span": item.page_span.iter().filter(|&&p| p > 0).collect::<Vec<_>>(),
                "issue_codes": item.issue_codes.iter().map(|s| s.trim()).collect::<Vec<_>>(),
                "issue_summary": item.issue_summary.iter().map(|s| s.trim()).collect::<Vec<_>>(),
                "severity": if item.severity.is_empty() { "minor" } else { &item.severity },
                "sample_opening": item.sample_opening.as_str(),
                "sample_mid": item.sample_mid.as_str(),
                "sample_tail": item.sample_tail.as_str(),
                "footnote_endnote_summary": item.footnote_endnote_summary,
            })
        })
        .collect();

    let must_fix = report.must_fix_before_next_book.clone();
    let followups = report.recommended_followups.clone();

    serde_json::json!({
        "slug": report.slug,
        "doc_id": report.doc_id,
        "zip_path": report.zip_path,
        "structure_state": report.structure_state,
        "blocking_reasons": report.blocking_reasons.iter().map(|s| s.trim()).collect::<Vec<_>>(),
        "manual_toc_summary": report.manual_toc_summary,
        "toc_role_summary": report.toc_role_summary,
        "chapter_titles": report.chapter_titles.iter().map(|s| s.trim()).collect::<Vec<_>>(),
        "files": files,
        "blocking_issue_count": report.blocking_issue_count,
        "major_issue_count": report.major_issue_count,
        "can_ship": report.can_ship,
        "must_fix_before_next_book": must_fix,
        "recommended_followups": followups,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::ExportAuditFileRecord;

    #[test]
    fn convert_empty_report() {
        let report = ExportAuditReportRecord::default();
        let value = to_export_audit_report(&report);
        assert_eq!(value["slug"], "");
        assert!(!value["can_ship"].as_bool().unwrap()); // default false
        assert!(value["files"].as_array().unwrap().is_empty());
    }

    #[test]
    fn convert_with_one_file() {
        let report = ExportAuditReportRecord {
            slug: "test".into(),
            doc_id: "test-doc".into(),
            zip_path: "test.zip".into(),
            files: vec![ExportAuditFileRecord {
                path: "ch001.md".into(),
                title: "Chapter 1".into(),
                issue_codes: vec!["orphan_note_definition".into()],
                issue_summary: vec!["orphan_note_definition: [^5]".into()],
                severity: "blocking".into(),
                ..Default::default()
            }],
            can_ship: false,
            blocking_issue_count: 1,
            ..Default::default()
        };
        let value = to_export_audit_report(&report);
        assert_eq!(value["slug"], "test");
        assert!(!value["can_ship"].as_bool().unwrap());
        let files = value["files"].as_array().unwrap();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0]["path"], "ch001.md");
        assert_eq!(files[0]["severity"], "blocking");
    }
}

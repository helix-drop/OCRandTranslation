//! Export audit 模块。
//!
//! ←→ Python `FNM_RE/stages/export_audit.py` (688 行 / 25 函数)

mod audit_logic;
mod file_audit;
pub mod helpers;
mod zip_read;

/// 在 export audit 中检查 structure_reviews 里哪些 review_type 应视为 blocker。
/// 不属于此列表的类型即使 severity="error" 也不阻塞导出。
const BLOCKING_STRUCTURE_REVIEW_TYPES: &[&str] = &[
    "freeze_matched_ref_not_injected",
    "merge_local_refs_unclosed",
    "merge_frozen_ref_leak",
    "merge_raw_marker_leak",
    "merge_chapter_file_missing",
];

use std::collections::{HashMap, HashSet};

use fnm_core::records::{
    ExportAuditFileRecord, ExportAuditReportRecord, ExportChapterRecord, Phase6Structure,
};

#[cfg(test)]
use fnm_core::records::StructureReviewRecord;

pub use file_audit::{audit_markdown_file, AuditFileParams};
pub use zip_read::read_zip_markdown_files;

/// 按章节收集注释标记。
///
/// ←→ Python `_chapter_note_markers_by_section()` (export_audit.py:489)
pub fn chapter_note_markers_by_section(
    phase6: &Phase6Structure,
) -> HashMap<String, HashSet<String>> {
    let mut payload: HashMap<String, HashSet<String>> = HashMap::new();
    for item in &phase6.note_items {
        let chapter_id = item.chapter_id.trim().to_string();
        if chapter_id.is_empty() {
            continue;
        }
        let marker_set = payload.entry(chapter_id).or_default();
        let marker = helpers::alphanumeric_key(&item.marker);
        if !marker.is_empty() {
            marker_set.insert(marker);
        }
    }
    payload
}

/// 按路径索引章节。
///
/// ←→ Python `_chapter_by_path()` (export_audit.py:502)
pub fn chapter_by_path(chapters: &[ExportChapterRecord]) -> HashMap<String, &ExportChapterRecord> {
    chapters
        .iter()
        .filter(|ch| !ch.path.trim().is_empty())
        .map(|ch| (ch.path.trim().to_string(), ch))
        .collect()
}

/// 审计 Phase 6 导出。
///
/// ←→ Python `audit_phase6_export()` (export_audit.py:510)
pub fn audit_phase6_export(
    phase6: &Phase6Structure,
    slug: &str,
    doc_id: &str,
    zip_bytes: Option<&[u8]>,
) -> (ExportAuditReportRecord, serde_json::Value) {
    let summary = &phase6.summary;
    let bundle = &phase6.export_bundle;
    let chapter_rows: Vec<&ExportChapterRecord> = bundle.chapters.iter().collect();
    let chapter_titles: Vec<String> = chapter_rows
        .iter()
        .filter(|ch| !ch.title.trim().is_empty())
        .map(|ch| ch.title.trim().to_string())
        .collect();

    let mut manual_toc_titles: Vec<String> = Vec::new();
    manual_toc_titles.extend(summary.container_titles.iter().cloned());
    manual_toc_titles.extend(chapter_titles.iter().cloned());
    manual_toc_titles.extend(summary.post_body_titles.iter().cloned());
    manual_toc_titles.extend(summary.back_matter_titles.iter().cloned());

    let mut role_by_title_key: HashMap<String, String> = HashMap::new();
    for title in &summary.container_titles {
        role_by_title_key.insert(helpers::alphanumeric_key(title), "container".to_string());
    }
    for title in &summary.post_body_titles {
        role_by_title_key.insert(helpers::alphanumeric_key(title), "post_body".to_string());
    }
    for title in &summary.back_matter_titles {
        role_by_title_key.insert(helpers::alphanumeric_key(title), "back_matter".to_string());
    }

    // 读取 Markdown 文件
    let (markdown_files, zip_read_error) = audit_logic::read_markdown_files(phase6, zip_bytes);

    let chapter_rows_owned: Vec<ExportChapterRecord> =
        chapter_rows.iter().map(|&ch| ch.clone()).collect();
    let path_to_chapter = chapter_by_path(&chapter_rows_owned);
    let chapter_note_markers = chapter_note_markers_by_section(phase6);

    let mut file_reports: Vec<ExportAuditFileRecord> = Vec::new();
    if let Some(err_msg) = zip_read_error {
        file_reports.push(ExportAuditFileRecord {
            path: "__book__/zip".to_string(),
            title: "ZIP read error".to_string(),
            issue_codes: vec!["zip_read_failed".to_string()],
            issue_summary: vec![format!("zip_read_failed: {err_msg}")],
            severity: "blocking".to_string(),
            ..Default::default()
        });
    }

    // 比对 bundle 应有路径 vs ZIP 实际路径
    file_reports.extend(audit_logic::audit_file_paths(
        phase6,
        &markdown_files,
        zip_bytes.is_some(),
    ));

    for path in markdown_files.keys().collect::<Vec<_>>() {
        let chapter = path_to_chapter.get(path.as_str());
        let default_content = String::new();
        let content = markdown_files
            .get(path.as_str())
            .unwrap_or(&default_content);
        let inferred_title = helpers::file_title_from_content(content);
        let title = chapter
            .map(|ch| ch.title.trim().to_string())
            .unwrap_or_else(|| inferred_title.clone());
        let section_id = chapter
            .map(|ch| ch.section_id.trim().to_string())
            .unwrap_or_default();

        let mut page_span: Vec<i64> = Vec::new();
        if let Some(ch) = chapter {
            page_span.push(ch.start_page);
            page_span.push(ch.end_page.max(ch.start_page));
        }

        let expected_role = role_by_title_key
            .get(&helpers::alphanumeric_key(&title))
            .cloned()
            .unwrap_or_else(|| "chapter".to_string());
        let expected_role = if path == bundle.index_path.trim() || path == "index.md" {
            "index_file"
        } else {
            &expected_role
        };

        let expected_title = chapter
            .map(|ch| ch.title.trim().to_string())
            .unwrap_or_default();

        file_reports.push(audit_markdown_file(&AuditFileParams {
            path,
            title: &title,
            content,
            chapter_titles: &chapter_titles,
            expected_role,
            expected_title: &expected_title,
            page_span: &page_span,
            manual_toc_titles: Some(&manual_toc_titles),
            chapter_note_markers: chapter_note_markers.get(&section_id).map(|s| s as &_),
        }));
    }

    // 检查章节组织
    let exported_title_keys: HashSet<String> = chapter_rows
        .iter()
        .map(|ch| helpers::alphanumeric_key(&ch.title))
        .filter(|k| !k.is_empty())
        .collect();
    file_reports.extend(audit_logic::audit_chapter_organization(
        phase6,
        &chapter_rows,
        &exported_title_keys,
        slug,
    ));

    // 收集 structure_review blockers
    let structure_review_blockers =
        audit_logic::collect_structure_review_blockers(phase6, BLOCKING_STRUCTURE_REVIEW_TYPES);

    // 统计
    let mut blocking_issue_count = file_reports
        .iter()
        .filter(|r| r.severity == "blocking")
        .count() as i64;
    blocking_issue_count += structure_review_blockers.len() as i64;
    let major_issue_count = file_reports
        .iter()
        .filter(|r| r.severity == "major")
        .count() as i64;

    // Semantic gates
    let semantic_gate_reasons = audit_logic::compute_semantic_gates(phase6, &file_reports);
    let semantic_gate_blockers = semantic_gate_reasons.len() as i64;

    // 合并 blocking_reasons
    let final_blocking_reasons = audit_logic::build_blocking_reasons(
        phase6,
        &file_reports,
        &structure_review_blockers,
        &semantic_gate_reasons,
    );
    let total_blocking_issue_count = blocking_issue_count + semantic_gate_blockers;

    // 构建 followups 和 must_fix
    let (recommended_followups, must_fix) =
        audit_logic::build_followups_and_must_fix(&file_reports);

    let report = ExportAuditReportRecord {
        slug: slug.to_string(),
        doc_id: doc_id.to_string(),
        zip_path: format!(
            "{}.zip",
            if slug.is_empty() {
                "phase6_export"
            } else {
                slug
            }
        ),
        applicable: true,
        structure_state: phase6.status.structure_state.clone(),
        blocking_reasons: final_blocking_reasons,
        manual_toc_summary: serde_json::to_value(&phase6.status.manual_toc_summary)
            .unwrap_or_default(),
        toc_role_summary: serde_json::to_value(&summary.toc_role_summary).unwrap_or_default(),
        chapter_titles,
        files: file_reports,
        blocking_issue_count: total_blocking_issue_count,
        major_issue_count,
        can_ship: total_blocking_issue_count == 0,
        must_fix_before_next_book: must_fix,
        recommended_followups,
    };

    let audit_summary = serde_json::json!({
        "export_audit_summary": {
            "file_count": report.files.len(),
            "blocking_issue_count": report.blocking_issue_count,
            "major_issue_count": report.major_issue_count,
            "can_ship": report.can_ship,
        }
    });

    (report, audit_summary)
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::ExportChapterRecord;

    #[test]
    fn test_chapter_by_path() {
        let chapters = vec![
            ExportChapterRecord {
                path: "ch001.md".to_string(),
                title: "Chapter 1".to_string(),
                ..Default::default()
            },
            ExportChapterRecord {
                path: "ch002.md".to_string(),
                title: "Chapter 2".to_string(),
                ..Default::default()
            },
        ];
        let result = chapter_by_path(&chapters);
        assert_eq!(result.len(), 2);
        assert!(result.contains_key("ch001.md"));
    }

    #[test]
    fn test_audit_phase6_export_empty() {
        let phase6 = Phase6Structure::default();
        let (report, _summary) = audit_phase6_export(&phase6, "test", "test", None);
        assert_eq!(report.slug, "test");
        assert!(report.can_ship);
        assert!(report.files.is_empty());
    }

    #[test]
    fn test_audit_phase6_export_blocks_on_freeze_error() {
        let phase6 = Phase6Structure {
            structure_reviews: vec![StructureReviewRecord {
                review_id: "review-freeze_matched_ref_not_injected-ch001-1-5-abc".into(),
                review_type: "freeze_matched_ref_not_injected".into(),
                chapter_id: "ch001".into(),
                page_start: 1,
                page_end: 5,
                severity: "error".into(),
                payload: serde_json::json!({
                    "message": "anchor coord out of bounds for page 3",
                }),
            }],
            ..Default::default()
        };
        let (report, _summary) = audit_phase6_export(&phase6, "test", "test", None);
        assert!(!report.can_ship, "freeze error should block export");
        assert_eq!(report.blocking_issue_count, 1);
        assert!(report
            .blocking_reasons
            .iter()
            .any(|r| r.contains("freeze_matched_ref_not_injected")));
    }

    #[test]
    fn test_audit_phase6_export_ignores_non_blocking_review() {
        let phase6 = Phase6Structure {
            structure_reviews: vec![StructureReviewRecord {
                review_id: "review-boundary_review_required-ch001-1-5-xyz".into(),
                review_type: "boundary_review_required".into(),
                chapter_id: "ch001".into(),
                page_start: 1,
                page_end: 5,
                severity: "error".into(),
                payload: serde_json::json!({}),
            }],
            ..Default::default()
        };
        let (report, _summary) = audit_phase6_export(&phase6, "test", "test", None);
        assert!(report.can_ship, "non-freeze error should not block export");
        assert_eq!(report.blocking_issue_count, 0);
    }

    /// ZIP 缺文件 → blocking
    #[test]
    fn test_audit_zip_missing_file_blocks() {
        use crate::export::zip::build_export_zip;
        use fnm_core::records::ExportBundleRecord;
        use std::collections::HashMap;

        // 创建一个正常 ZIP（含 expected.md）
        let bundle = ExportBundleRecord {
            chapters_dir: "chapters".to_string(),
            files: {
                let mut f = HashMap::new();
                f.insert("chapters/expected.md".into(), "Content.".into());
                f.insert("index.md".into(), "# Index".into());
                f
            },
            ..Default::default()
        };
        let zip_bytes = build_export_zip(&bundle).expect("build_zip");

        // 构造 Phase6Structure，它的 bundle 声称应有更多文件
        let mut files_claim = HashMap::new();
        files_claim.insert("chapters/expected.md".into(), "Content.".into());
        files_claim.insert("chapters/missing.md".into(), "Should be missing.".into());
        files_claim.insert("index.md".into(), "# Index".into());
        let phase6 = Phase6Structure {
            export_bundle: ExportBundleRecord {
                chapters_dir: "chapters".to_string(),
                files: files_claim,
                ..Default::default()
            },
            ..Default::default()
        };
        let (report, _summary) = audit_phase6_export(&phase6, "test", "test", Some(&zip_bytes));
        assert!(!report.can_ship, "missing ZIP file should block export");
        assert!(
            report
                .blocking_reasons
                .iter()
                .any(|r| r.starts_with("zip_missing_file")),
            "blocking_reasons must include zip_missing_file"
        );
    }

    /// ZIP 多文件 → blocking
    #[test]
    fn test_audit_zip_extra_file_blocks() {
        use crate::export::zip::build_export_zip;
        use fnm_core::records::ExportBundleRecord;
        use std::collections::HashMap;

        // 创建一个 ZIP，含一个不应出现的文件
        let bundle = ExportBundleRecord {
            chapters_dir: "chapters".to_string(),
            files: {
                let mut f = HashMap::new();
                f.insert("chapters/expected.md".into(), "Content.".into());
                f.insert(
                    "chapters/extra.md".into(),
                    "Extra content not in bundle.".into(),
                );
                f.insert("index.md".into(), "# Index".into());
                f
            },
            ..Default::default()
        };
        let zip_bytes = build_export_zip(&bundle).expect("build_zip");

        // 构造 Phase6Structure，它的 bundle 声称应有更少的文件
        let mut files_claim = HashMap::new();
        files_claim.insert("chapters/expected.md".into(), "Content.".into());
        files_claim.insert("index.md".into(), "# Index".into());
        let phase6 = Phase6Structure {
            export_bundle: ExportBundleRecord {
                chapters_dir: "chapters".to_string(),
                files: files_claim,
                ..Default::default()
            },
            ..Default::default()
        };
        let (report, _summary) = audit_phase6_export(&phase6, "test", "test", Some(&zip_bytes));
        assert!(!report.can_ship, "extra ZIP file should block export");
        assert!(
            report
                .blocking_reasons
                .iter()
                .any(|r| r.starts_with("zip_extra_file")),
            "blocking_reasons must include zip_extra_file"
        );
    }
}

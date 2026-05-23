//! Export audit 模块。
//!
//! ←→ Python `FNM_RE/stages/export_audit.py` (688 行 / 25 函数)

mod file_audit;
pub mod helpers;

/// 在 export audit 中检查 structure_reviews 里哪些 review_type 应视为 blocker。
/// 不属于此列表的类型即使 severity="error" 也不阻塞导出。
const BLOCKING_STRUCTURE_REVIEW_TYPES: &[&str] = &["freeze_matched_ref_not_injected"];

use std::collections::{HashMap, HashSet};

use anyhow::Result;
use fnm_core::records::{
    ExportAuditFileRecord, ExportAuditReportRecord, ExportChapterRecord, Phase6Structure,
};

#[cfg(test)]
use fnm_core::records::StructureReviewRecord;

pub use file_audit::audit_markdown_file;

/// 从 ZIP 字节中读取 Markdown 文件。
///
/// ←→ Python `_read_zip_markdown_files()` (export_audit.py:479)
pub fn read_zip_markdown_files(zip_bytes: &[u8]) -> Result<HashMap<String, String>> {
    let reader = std::io::Cursor::new(zip_bytes);
    let mut archive = zip::ZipArchive::new(reader)?;
    let mut payload = HashMap::new();

    for i in 0..archive.len() {
        let mut file = archive.by_index(i)?;
        let name = file.name().to_string();
        if name.ends_with(".md") {
            let mut content = String::new();
            std::io::Read::read_to_string(&mut file, &mut content)?;
            payload.insert(name, content);
        }
    }

    Ok(payload)
}

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
    let markdown_files = if let Some(bytes) = zip_bytes {
        read_zip_markdown_files(bytes).unwrap_or_default()
    } else {
        bundle
            .files
            .iter()
            .filter(|(path, _)| path.ends_with(".md"))
            .map(|(path, content)| (path.clone(), content.clone()))
            .collect::<HashMap<String, String>>()
    };

    let chapter_rows_owned: Vec<ExportChapterRecord> =
        chapter_rows.iter().map(|&ch| ch.clone()).collect();
    let path_to_chapter = chapter_by_path(&chapter_rows_owned);
    let chapter_note_markers = chapter_note_markers_by_section(phase6);

    let mut file_reports: Vec<ExportAuditFileRecord> = Vec::new();

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

        file_reports.push(audit_markdown_file(
            path,
            &title,
            content,
            &chapter_titles,
            expected_role,
            &expected_title,
            &page_span,
            Some(&manual_toc_titles),
            chapter_note_markers.get(&section_id).map(|s| s as &_),
        ));
    }

    // 检查缺失的 post_body 标题
    let exported_title_keys: HashSet<String> = chapter_rows
        .iter()
        .map(|ch| helpers::alphanumeric_key(&ch.title))
        .filter(|k| !k.is_empty())
        .collect();

    let missing_post_body_titles: Vec<String> = summary
        .post_body_titles
        .iter()
        .filter(|t| {
            let key = helpers::alphanumeric_key(t);
            !key.is_empty() && !exported_title_keys.contains(&key)
        })
        .cloned()
        .collect();

    if !missing_post_body_titles.is_empty() {
        file_reports.push(ExportAuditFileRecord {
            path: "__book__/post_body".to_string(),
            title: missing_post_body_titles.join(", "),
            issue_codes: vec![
                "missing_post_body_export".to_string(),
                "toc_organization_mismatch".to_string(),
            ],
            issue_summary: vec![
                format!(
                    "missing_post_body_export: {}",
                    missing_post_body_titles.join(", ")
                ),
                "toc_organization_mismatch: post_body_titles_missing_from_export".to_string(),
            ],
            severity: "blocking".to_string(),
            ..Default::default()
        });
    }

    // 检查导出的 container 标题
    let exported_container_titles: Vec<String> = summary
        .container_titles
        .iter()
        .filter(|t| {
            let key = helpers::alphanumeric_key(t);
            !key.is_empty() && exported_title_keys.contains(&key)
        })
        .cloned()
        .collect();

    if !exported_container_titles.is_empty() {
        file_reports.push(ExportAuditFileRecord {
            path: "__book__/container".to_string(),
            title: exported_container_titles.join(", "),
            issue_codes: vec![
                "container_exported_as_chapter".to_string(),
                "toc_organization_mismatch".to_string(),
            ],
            issue_summary: vec![
                format!(
                    "container_exported_as_chapter: {}",
                    exported_container_titles.join(", ")
                ),
                "toc_organization_mismatch: container_titles_present_in_export".to_string(),
            ],
            severity: "blocking".to_string(),
            ..Default::default()
        });
    }

    // 检查导出深度
    let expected_export_count = summary
        .toc_role_summary
        .get("chapter")
        .and_then(|v| v.as_i64())
        .unwrap_or(0)
        + summary
            .toc_role_summary
            .get("post_body")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
    let actual_export_count = chapter_rows.len() as i64;

    if expected_export_count > 0
        && actual_export_count > 0
        && actual_export_count < expected_export_count
    {
        file_reports.push(ExportAuditFileRecord {
            path: "__book__/organization_depth".to_string(),
            title: if slug.is_empty() {
                "phase6".to_string()
            } else {
                slug.to_string()
            },
            issue_codes: vec![
                "export_depth_too_shallow".to_string(),
                "toc_organization_mismatch".to_string(),
            ],
            issue_summary: vec![
                format!(
                    "export_depth_too_shallow: expected>={}, actual={}",
                    expected_export_count, actual_export_count
                ),
                "toc_organization_mismatch: export_chapter_count_below_toc_depth".to_string(),
            ],
            severity: "blocking".to_string(),
            ..Default::default()
        });
    }

    // 检查 structure_reviews 中的 blocker 类型（如 freeze_matched_ref_not_injected）
    let mut freeze_blocking_reasons: Vec<String> = Vec::new();
    for review in &phase6.structure_reviews {
        if BLOCKING_STRUCTURE_REVIEW_TYPES.contains(&review.review_type.as_str()) {
            freeze_blocking_reasons.push(format!(
                "{}: {}",
                review.review_type,
                review
                    .payload
                    .get("message")
                    .and_then(|v| v.as_str())
                    .unwrap_or(&review.review_type)
            ));
        }
    }

    // 统计
    let mut blocking_issue_count = file_reports
        .iter()
        .filter(|r| r.severity == "blocking")
        .count() as i64;
    blocking_issue_count += freeze_blocking_reasons.len() as i64;
    let major_issue_count = file_reports
        .iter()
        .filter(|r| r.severity == "major")
        .count() as i64;

    // 合并 blocking_reasons
    let mut combined_blocking_reasons: Vec<String> =
        phase6.status.blocking_reasons.clone();
    combined_blocking_reasons.extend(freeze_blocking_reasons);

    let mut issue_counts: HashMap<String, i64> = HashMap::new();
    for row in &file_reports {
        for code in &row.issue_codes {
            *issue_counts.entry(code.clone()).or_insert(0) += 1;
        }
    }

    let mut recommended_followups: Vec<serde_json::Value> = issue_counts
        .iter()
        .map(|(code, count)| {
            serde_json::json!({
                "issue_code": code,
                "count": count,
            })
        })
        .collect();
    recommended_followups.sort_by(|a, b| {
        let count_a = a.get("count").and_then(|v| v.as_i64()).unwrap_or(0);
        let count_b = b.get("count").and_then(|v| v.as_i64()).unwrap_or(0);
        count_b.cmp(&count_a)
    });
    recommended_followups.truncate(8);

    let must_fix: Vec<serde_json::Value> = file_reports
        .iter()
        .filter(|r| r.severity == "blocking")
        .map(|row| {
            serde_json::json!({
                "path": row.path,
                "issue_codes": row.issue_codes,
            })
        })
        .collect();

    let report = ExportAuditReportRecord {
        slug: slug.to_string(),
        doc_id: slug.to_string(),
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
        blocking_reasons: combined_blocking_reasons,
        manual_toc_summary: serde_json::to_value(&phase6.status.manual_toc_summary)
            .unwrap_or_default(),
        toc_role_summary: serde_json::to_value(&summary.toc_role_summary).unwrap_or_default(),
        chapter_titles,
        files: file_reports,
        blocking_issue_count,
        major_issue_count,
        can_ship: blocking_issue_count == 0,
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
        let (report, _summary) = audit_phase6_export(&phase6, "test", None);
        assert_eq!(report.slug, "test");
        assert!(report.can_ship);
        assert!(report.files.is_empty());
    }

    #[test]
    fn test_audit_phase6_export_blocks_on_freeze_error() {
        let mut phase6 = Phase6Structure::default();
        phase6.structure_reviews = vec![StructureReviewRecord {
            review_id: "review-freeze_matched_ref_not_injected-ch001-1-5-abc".into(),
            review_type: "freeze_matched_ref_not_injected".into(),
            chapter_id: "ch001".into(),
            page_start: 1,
            page_end: 5,
            severity: "error".into(),
            payload: serde_json::json!({
                "message": "anchor coord out of bounds for page 3",
            }),
        }];
        let (report, _summary) = audit_phase6_export(&phase6, "test", None);
        assert!(!report.can_ship, "freeze error should block export");
        assert_eq!(report.blocking_issue_count, 1);
        assert!(report.blocking_reasons.iter().any(|r| r.contains("freeze_matched_ref_not_injected")));
    }

    #[test]
    fn test_audit_phase6_export_ignores_non_blocking_review() {
        let mut phase6 = Phase6Structure::default();
        phase6.structure_reviews = vec![StructureReviewRecord {
            review_id: "review-boundary_review_required-ch001-1-5-xyz".into(),
            review_type: "boundary_review_required".into(),
            chapter_id: "ch001".into(),
            page_start: 1,
            page_end: 5,
            severity: "error".into(),
            payload: serde_json::json!({}),
        }];
        let (report, _summary) = audit_phase6_export(&phase6, "test", None);
        assert!(report.can_ship, "non-freeze error should not block export");
        assert_eq!(report.blocking_issue_count, 0);
    }
}

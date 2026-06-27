//! Export audit 核心逻辑：路径比对、章节组织检查、semantic gates。
//!
//! ←→ Python `audit_phase6_export()` 中的子步骤

use std::collections::{HashMap, HashSet};

use fnm_core::records::{ExportAuditFileRecord, ExportChapterRecord, Phase6Structure};

use super::helpers;

/// 读取 Markdown 文件：优先从 ZIP 读取，否则从 bundle.files 读取。
pub(super) fn read_markdown_files(
    phase6: &Phase6Structure,
    zip_bytes: Option<&[u8]>,
) -> (HashMap<String, String>, Option<String>) {
    if let Some(bytes) = zip_bytes {
        match super::zip_read::read_zip_markdown_files(bytes) {
            Ok(files) => (files, None),
            Err(e) => (HashMap::new(), Some(e.to_string())),
        }
    } else {
        let files = phase6
            .export_bundle
            .files
            .iter()
            .filter(|(path, _)| path.ends_with(".md"))
            .map(|(path, content)| (path.clone(), content.clone()))
            .collect();
        (files, None)
    }
}

/// 比对 bundle 应有路径 vs ZIP 实际路径，生成缺失/多余文件报告。
pub(super) fn audit_file_paths(
    phase6: &Phase6Structure,
    markdown_files: &HashMap<String, String>,
    has_zip: bool,
) -> Vec<ExportAuditFileRecord> {
    let mut reports = Vec::new();
    if !has_zip {
        return reports;
    }

    let expected_paths: HashSet<&str> = phase6
        .export_bundle
        .files
        .keys()
        .map(|s| s.as_str())
        .collect();
    let actual_paths: HashSet<&str> = markdown_files.keys().map(|s| s.as_str()).collect();

    for missing in expected_paths.difference(&actual_paths) {
        reports.push(ExportAuditFileRecord {
            path: (*missing).to_string(),
            title: String::new(),
            issue_codes: vec!["zip_missing_file".to_string()],
            issue_summary: vec![format!("zip_missing_file: {missing} not found in ZIP")],
            severity: "blocking".to_string(),
            ..Default::default()
        });
    }
    for extra in actual_paths.difference(&expected_paths) {
        reports.push(ExportAuditFileRecord {
            path: (*extra).to_string(),
            title: String::new(),
            issue_codes: vec!["zip_extra_file".to_string()],
            issue_summary: vec![format!("zip_extra_file: {extra} not in bundle")],
            severity: "blocking".to_string(),
            ..Default::default()
        });
    }

    reports
}

/// 检查章节组织：post_body 缺失、container 导出、深度不足。
pub(super) fn audit_chapter_organization(
    phase6: &Phase6Structure,
    chapter_rows: &[&ExportChapterRecord],
    exported_title_keys: &HashSet<String>,
    slug: &str,
) -> Vec<ExportAuditFileRecord> {
    let mut reports = Vec::new();
    let summary = &phase6.summary;

    // 检查缺失的 post_body 标题
    let missing_post_body_titles: Vec<String> = summary
        .toc
        .post_body_titles
        .iter()
        .filter(|t| {
            let key = helpers::alphanumeric_key(t);
            !key.is_empty() && !exported_title_keys.contains(&key)
        })
        .cloned()
        .collect();

    if !missing_post_body_titles.is_empty() {
        reports.push(ExportAuditFileRecord {
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
        .toc
        .container_titles
        .iter()
        .filter(|t| {
            let key = helpers::alphanumeric_key(t);
            !key.is_empty() && exported_title_keys.contains(&key)
        })
        .cloned()
        .collect();

    if !exported_container_titles.is_empty() {
        reports.push(ExportAuditFileRecord {
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
        .toc
        .toc_role_summary
        .get("chapter")
        .and_then(|v| v.as_i64())
        .unwrap_or(0)
        + summary
            .toc
            .toc_role_summary
            .get("post_body")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
    let actual_export_count = chapter_rows.len() as i64;

    if expected_export_count > 0
        && actual_export_count > 0
        && actual_export_count < expected_export_count
    {
        reports.push(ExportAuditFileRecord {
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

    reports
}

/// 收集 structure_reviews 中的 blocker 类型。
pub(super) fn collect_structure_review_blockers(
    phase6: &Phase6Structure,
    blocking_types: &[&str],
) -> Vec<String> {
    let mut reasons = Vec::new();
    for review in &phase6.structure_reviews {
        if blocking_types.contains(&review.review_type.as_str()) {
            let ch_id = review
                .payload
                .get("chapter_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let msg = review
                .payload
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or(&review.review_type);
            let formatted = if ch_id.is_empty() {
                format!("{}: {}", review.review_type, msg)
            } else {
                format!("{} @ {}: {}", review.review_type, ch_id, msg)
            };
            reasons.push(formatted);
        }
    }
    reasons
}

/// 计算 semantic gates（book-level）。
pub(super) fn compute_semantic_gates(
    phase6: &Phase6Structure,
    file_reports: &[ExportAuditFileRecord],
) -> Vec<String> {
    let mut reasons = Vec::new();

    let has_merge_raw_marker_leak = phase6
        .structure_reviews
        .iter()
        .any(|r| r.review_type == "merge_raw_marker_leak");
    let has_file_raw_marker_leak = file_reports.iter().any(|r| {
        r.issue_codes
            .iter()
            .any(|code| code == "raw_note_marker_leak" || code == "legacy_note_token_leak")
    });

    if has_merge_raw_marker_leak || has_file_raw_marker_leak {
        reasons.push("gate_no_raw_marker_leak_book_level".to_string());
    }

    reasons
}

/// 构建 blocking_reasons 列表。
pub(super) fn build_blocking_reasons(
    phase6: &Phase6Structure,
    file_reports: &[ExportAuditFileRecord],
    structure_review_blockers: &[String],
    semantic_gate_reasons: &[String],
) -> Vec<String> {
    let mut reasons = phase6.status.blocking_reasons.clone();
    reasons.extend(structure_review_blockers.iter().cloned());

    for report in file_reports {
        if report.severity == "blocking" {
            for code in &report.issue_codes {
                reasons.push(format!("{code} @ {}", report.path));
            }
        }
    }

    reasons.extend(semantic_gate_reasons.iter().cloned());
    reasons
}

/// 构建 recommended_followups 和 must_fix 列表。
pub(super) fn build_followups_and_must_fix(
    file_reports: &[ExportAuditFileRecord],
) -> (Vec<serde_json::Value>, Vec<serde_json::Value>) {
    let mut issue_counts: HashMap<String, i64> = HashMap::new();
    for row in file_reports {
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

    (recommended_followups, must_fix)
}

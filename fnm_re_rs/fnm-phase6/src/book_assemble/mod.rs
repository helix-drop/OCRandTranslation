//! ←→ FNM_RE/modules/book_assemble.py
//! 翻译的函数：
//!   build_module_export_bundle  ←→ build_export_bundle (book_assemble.py:398)
//!
//! 子模块：
//!   garbled_repair   → _split_markdown_prefix / _looks_like_garbled_export_block / _repair_garbled_markdown_blocks
//!   canonicalize     → _is_adjacent_duplicate_candidate / _canonicalize_adjacent_duplicate_paragraphs / _apply_semantic_canonicalization
//!   chapter_order    → _reorder_chapters / _to_export_chapter_records
//!   toc_titles       → _toc_titles_and_summary
//!   marker_leak      → _has_book_level_raw_marker_leak

mod canonicalize;
mod chapter_order;
mod garbled_repair;
mod marker_leak;
mod toc_titles;

use std::collections::HashMap;

use anyhow::Result;
use fnm_core::records::Phase1Structure;
use fnm_core::records::{ChapterMarkdownSet, ExportBundleRecord};
use fnm_phase2::chapter_split::structure_model::BookStructureModel;

use self::canonicalize::apply_semantic_canonicalization;
use self::chapter_order::{reorder_chapters, to_export_chapter_records};
use self::marker_leak::{has_book_level_raw_marker_leak, has_leak_issues_in_report};
use self::toc_titles::toc_titles_and_summary;
use crate::export::contract::compute_export_semantic_contract;
use crate::export::index_render::build_index_markdown;
use crate::export::markdown_clean::normalize_markdown_content;
use crate::export::zip::build_export_zip;
use crate::export_audit::audit_phase6_export;
use fnm_core::records::{
    ExportAuditReportRecord, Phase6Structure, Phase6Summary, StructureReviewRecord,
    StructureStatusRecord,
};

/// 整书导出组装：将 Phase 5 的 ChapterMarkdownSet 组装为导出包。
///
/// ←→ Python `build_export_bundle()` (book_assemble.py:398)
pub fn build_module_export_bundle(
    chapter_markdown_set: &ChapterMarkdownSet,
    phase1: &Phase1Structure,
    book_structure_model: Option<&BookStructureModel>,
    slug: &str,
    _doc_id: &str,
    structure_reviews: &[StructureReviewRecord],
) -> Result<(
    ExportBundleRecord,
    Vec<u8>,
    ExportAuditReportRecord,
    serde_json::Value,
)> {
    // 1. 按 TOC 顺序重排章节
    let (ordered_chapters, missing_chapter_ids, extra_chapter_ids) =
        reorder_chapters(&chapter_markdown_set.chapters, &phase1.chapters);

    // 2. 乱码修复 + 去重
    let (canonicalized_chapters, canonicalization_summary) =
        apply_semantic_canonicalization(&ordered_chapters);

    // 3. 转换为 ExportChapterRecord
    let export_chapters = to_export_chapter_records(&canonicalized_chapters);

    // 4. 构建 chapter_files
    let mut chapter_files: HashMap<String, String> = HashMap::new();
    for row in &export_chapters {
        if !row.path.trim().is_empty() {
            chapter_files.insert(row.path.clone(), normalize_markdown_content(&row.content));
        }
    }

    // 5. 构建 files（含 index.md）
    let mut files: HashMap<String, String> = chapter_files.clone();
    if !export_chapters.is_empty() {
        files.insert(
            "index.md".to_string(),
            build_index_markdown(&export_chapters),
        );
    }

    // 6. 语义契约检查
    let semantic = compute_export_semantic_contract(&export_chapters, &chapter_files);

    // 7. 构建 ExportBundleRecord
    let bundle_record = ExportBundleRecord {
        index_path: "index.md".to_string(),
        chapters_dir: "chapters".to_string(),
        chapters: export_chapters.clone(),
        chapter_files: chapter_files.clone(),
        files: files.clone(),
        export_semantic_contract_ok: semantic
            .get("export_semantic_contract_ok")
            .copied()
            .unwrap_or(true),
        front_matter_leak_detected: semantic
            .get("front_matter_leak_detected")
            .copied()
            .unwrap_or(false),
        toc_residue_detected: semantic
            .get("toc_residue_detected")
            .copied()
            .unwrap_or(false),
        mid_paragraph_heading_detected: semantic
            .get("mid_paragraph_heading_detected")
            .copied()
            .unwrap_or(false),
        duplicate_paragraph_detected: semantic
            .get("duplicate_paragraph_detected")
            .copied()
            .unwrap_or(false),
    };

    // 8. 生成 ZIP 字节
    let zip_bytes = build_export_zip(&bundle_record)?;

    // 9. TOC 标题与摘要
    let (container_titles, post_body_titles, back_matter_titles, toc_role_summary) =
        toc_titles_and_summary(
            &phase1.toc_tree,
            &phase1.chapters,
            &phase1.summary.container_titles,
            &phase1.summary.post_body_titles,
            &phase1.summary.back_matter_titles,
        );

    // 10. 构建 Phase6Structure 用于审计
    let phase6 = Phase6Structure {
        export_bundle: bundle_record.clone(),
        structure_reviews: structure_reviews.to_vec(),
        status: StructureStatusRecord {
            structure_state: "done".to_string(),
            ..Default::default()
        },
        summary: Phase6Summary {
            container_titles: container_titles.clone(),
            post_body_titles: post_body_titles.clone(),
            back_matter_titles: back_matter_titles.clone(),
            toc_role_summary: toc_role_summary.clone(),
            ..Default::default()
        },
        ..Default::default()
    };

    // 11. 审计
    let (report_record, _audit_summary) = audit_phase6_export(&phase6, slug, None);

    // 12. 检查 raw marker leak（全书级）
    let no_raw_marker_leak_book_level =
        !has_book_level_raw_marker_leak(&chapter_files, book_structure_model)
            && !has_leak_issues_in_report(&report_record.files);

    // 13. 审计文件摘要
    let audit_issue_file_summary: Vec<serde_json::Value> = report_record
        .files
        .iter()
        .filter(|row| !row.issue_codes.is_empty())
        .take(24)
        .map(|row| {
            serde_json::json!({
                "path": row.path,
                "issue_codes": row.issue_codes.iter().map(|s| s.trim()).collect::<Vec<_>>(),
            })
        })
        .collect();

    // 14. 排序与 contamination 检查
    let toc_chapter_ids: Vec<String> = phase1
        .chapters
        .iter()
        .filter(|row| !row.chapter_id.trim().is_empty())
        .map(|row| row.chapter_id.clone())
        .collect();
    let exported_ids: Vec<String> = canonicalized_chapters
        .iter()
        .filter(|row| !row.chapter_id.trim().is_empty())
        .map(|row| row.chapter_id.clone())
        .collect();
    let toc_id_set: std::collections::HashSet<&str> =
        toc_chapter_ids.iter().map(|s| s.as_str()).collect();
    let exported_toc_ids: Vec<&str> = exported_ids
        .iter()
        .filter(|id| toc_id_set.contains(id.as_str()))
        .map(|s| s.as_str())
        .collect();
    let order_follows_toc = missing_chapter_ids.is_empty()
        && extra_chapter_ids.is_empty()
        && exported_toc_ids
            == toc_chapter_ids
                .iter()
                .map(|s| s.as_str())
                .collect::<Vec<_>>();

    let no_cross_chapter_contamination = !report_record.files.iter().any(|file_row| {
        file_row
            .issue_codes
            .contains(&"chapter_boundary_swallow_next".to_string())
    });

    // 15. 语义摘要
    let semantic_summary = serde_json::json!({
        "chapter_count": export_chapters.len(),
        "chapter_file_count": chapter_files.len(),
        "file_count": files.len(),
        "missing_chapter_ids": missing_chapter_ids,
        "extra_chapter_ids": extra_chapter_ids,
        "gate_order_follows_toc": order_follows_toc,
        "gate_no_cross_chapter_contamination": no_cross_chapter_contamination,
        "gate_no_raw_marker_leak_book_level": no_raw_marker_leak_book_level,
        "audit_blocking_issue_count": report_record.blocking_issue_count,
        "audit_issue_file_count": audit_issue_file_summary.len(),
        "audit_issue_file_preview": audit_issue_file_summary,
    });
    // 合并 semantic 与 canonicalization 字段
    let semantic_summary = {
        let mut map = serde_json::Map::new();
        if let Some(obj) = semantic_summary.as_object() {
            for (k, v) in obj {
                map.insert(k.clone(), v.clone());
            }
        }
        if let Some(obj) = canonicalization_summary.as_object() {
            for (k, v) in obj {
                map.insert(k.clone(), v.clone());
            }
        }
        for (k, v) in &semantic {
            map.insert(k.clone(), serde_json::Value::Bool(*v));
        }
        map.insert(
            "export_semantic_contract_ok".to_string(),
            serde_json::Value::Bool(bundle_record.export_semantic_contract_ok),
        );
        serde_json::Value::Object(map)
    };

    Ok((bundle_record, zip_bytes, report_record, semantic_summary))
}

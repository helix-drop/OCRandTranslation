//! ←→ FNM_RE/modules/book_assemble.py
//! 翻译的函数：
//!   build_module_export_bundle  ←→ build_export_bundle (book_assemble.py:398)
//!
//! 子模块：
//!   chapter_order    → _reorder_chapters / _to_export_chapter_records
//!   toc_titles       → _toc_titles_and_summary
//!   marker_leak      → _has_book_level_raw_marker_leak
//!   bundle_builder   → 构建 Phase6Structure 和语义摘要
//!
//! Phase6 为只读组装器：不修改 ChapterMarkdownEntry.markdown_text。

mod bundle_builder;
mod chapter_order;
mod marker_leak;
mod toc_titles;

use std::collections::HashMap;

use anyhow::Result;
use fnm_core::records::Phase1Structure;
use fnm_core::records::{ChapterMarkdownSet, ExportBundleRecord};
use fnm_phase2::chapter_split::structure_model::BookStructureModel;

use self::chapter_order::{reorder_chapters, to_export_chapter_records};
use self::toc_titles::toc_titles_and_summary;
use crate::export::contract::compute_export_semantic_contract;
use crate::export::index_render::build_index_markdown;
use crate::export::markdown_clean::normalize_markdown_content;
use crate::export::zip::build_export_zip;
use crate::export_audit::audit_phase6_export;
use fnm_core::records::{ExportAuditReportRecord, StructureReviewRecord};

/// 整书导出组装：将 Phase 5 的 ChapterMarkdownSet 组装为导出包。
///
/// ←→ Python `build_export_bundle()` (book_assemble.py:398)
pub fn build_module_export_bundle(
    chapter_markdown_set: &ChapterMarkdownSet,
    phase1: &Phase1Structure,
    _book_structure_model: Option<&BookStructureModel>,
    slug: &str,
    doc_id: &str,
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

    // 2. 转换为 ExportChapterRecord（Phase6 不修改正文内容）
    let export_chapters = to_export_chapter_records(&ordered_chapters);

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
            &phase1.summary.toc.container_titles,
            &phase1.summary.toc.post_body_titles,
            &phase1.summary.toc.back_matter_titles,
        );

    // 10. 构建 Phase6Structure 用于审计
    let phase6 = bundle_builder::build_phase6_for_audit(
        &bundle_record,
        structure_reviews,
        chapter_markdown_set.note_items.clone(),
        container_titles.clone(),
        post_body_titles.clone(),
        back_matter_titles.clone(),
        toc_role_summary.clone(),
    );

    // 11. 审计（已包含 gate_no_raw_marker_leak_book_level）
    let (report_record, _audit_summary) =
        audit_phase6_export(&phase6, slug, doc_id, Some(&zip_bytes));

    // 12. 审计文件摘要
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

    // 13. 排序与 contamination 检查
    let toc_chapter_ids: Vec<String> = phase1
        .chapters
        .iter()
        .filter(|row| !row.chapter_id.trim().is_empty())
        .map(|row| row.chapter_id.clone())
        .collect();
    let exported_ids: Vec<String> = ordered_chapters
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

    // 14. 补充 gates（audit_phase6_export 已计算 gate_no_raw_marker_leak_book_level）
    let (report_record, _gates_ok) = bundle_builder::compute_book_assemble_gates(
        &report_record,
        order_follows_toc,
        no_cross_chapter_contamination,
        bundle_record.export_semantic_contract_ok,
        &missing_chapter_ids,
        &extra_chapter_ids,
    );

    // 15. 语义摘要
    let semantic_summary =
        bundle_builder::build_semantic_summary(&bundle_builder::SemanticSummaryInput {
            export_chapters: &export_chapters,
            chapter_files: &chapter_files,
            files: &files,
            missing_chapter_ids: &missing_chapter_ids,
            extra_chapter_ids: &extra_chapter_ids,
            order_follows_toc,
            no_cross_chapter_contamination,
            report_record: &report_record,
            audit_issue_file_summary: &audit_issue_file_summary,
            semantic: &semantic,
            export_semantic_contract_ok: bundle_record.export_semantic_contract_ok,
        });

    Ok((bundle_record, zip_bytes, report_record, semantic_summary))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::export_audit::read_zip_markdown_files;
    use fnm_core::records::{ChapterMarkdownEntry, ChapterRecord};
    use fnm_core::types::{BoundaryState, ChapterSource};

    /// Phase6 不应修改正文内容：控制字符乱码须原样保留
    #[test]
    fn contract_phase6_does_not_modify_garbled_content() {
        let garbled_text =
            "## Chapitre\n\nTexte avec \x00\x01 caractères de contrôle.\n\n[^1]: Note.";
        let cm_set = ChapterMarkdownSet {
            chapters: vec![ChapterMarkdownEntry {
                order: 1,
                chapter_id: "ch1".to_string(),
                title: "Chapter 1".to_string(),
                path: "chapters/001-ch1.md".to_string(),
                markdown_text: garbled_text.to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let phase1 = Phase1Structure {
            chapters: vec![ChapterRecord {
                chapter_id: "ch1".to_string(),
                title: "Chapter 1".to_string(),
                start_page: 1,
                end_page: 5,
                pages: vec![1, 2, 3, 4, 5],
                source: ChapterSource::Fallback,
                boundary_state: BoundaryState::Ready,
            }],
            ..Default::default()
        };
        let (_bundle, zip_bytes, _report, _semantic) =
            build_module_export_bundle(&cm_set, &phase1, None, "test", "doc-test", &[])
                .expect("build_module_export_bundle");
        let files = read_zip_markdown_files(&zip_bytes).expect("read ZIP");
        let content = files.get("chapters/001-ch1.md").expect("chapter in ZIP");
        // 原始 garbled_text 含有 \x00 和 \x01
        assert!(
            content.contains('\x00'),
            "Phase6 must not remove control chars: \\x00 missing"
        );
        assert!(
            content.contains('\x01'),
            "Phase6 must not remove control chars: \\x01 missing"
        );
    }

    /// Phase6 不应折叠相邻重复段落
    #[test]
    fn contract_phase6_does_not_collapse_duplicate_paragraphs() {
        let p = "Cette phrase est suffisamment longue pour être candidate à la détection de doublon. Elle contient plus de douze mots et se termine par un point.";
        let dup_text = format!("## Chapitre 2\n\n{p}\n\n{p}\n\n[^1]: Note.\n");
        let cm_set = ChapterMarkdownSet {
            chapters: vec![ChapterMarkdownEntry {
                order: 1,
                chapter_id: "ch2".to_string(),
                title: "Chapter 2".to_string(),
                path: "chapters/001-ch2.md".to_string(),
                markdown_text: dup_text.clone(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let phase1 = Phase1Structure {
            chapters: vec![ChapterRecord {
                chapter_id: "ch2".to_string(),
                title: "Chapter 2".to_string(),
                start_page: 6,
                end_page: 10,
                pages: vec![6, 7, 8, 9, 10],
                source: ChapterSource::Fallback,
                boundary_state: BoundaryState::Ready,
            }],
            ..Default::default()
        };
        let (_bundle, zip_bytes, _report, _semantic) =
            build_module_export_bundle(&cm_set, &phase1, None, "test", "doc-test", &[])
                .expect("build_module_export_bundle");
        let files = read_zip_markdown_files(&zip_bytes).expect("read ZIP");
        let content = files.get("chapters/001-ch2.md").expect("chapter in ZIP");
        // 原始文本含两次相同的段落，Phase6 不应折叠为一次
        let count = content.matches(&p).count();
        assert_eq!(
            count, 2,
            "Phase6 must not collapse duplicate paragraphs: expected 2, got {count}"
        );
    }

    /// Phase6 保持 Biopolitics 真实页面内容不变
    #[test]
    fn contract_phase6_preserves_biopolitics_content() {
        let raw_fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../../fnm-phase5/tests/fixtures/biopolitics_ch1.json"
        ))
        .expect("fixture JSON");
        let pages = raw_fixture["pages"].as_array().expect("pages array");
        // 取第 1 页的 markdown 作为真实测试数据
        let first_page = &pages[0];
        let first_md = first_page["markdown"].as_str().unwrap_or("");
        assert!(
            !first_md.is_empty(),
            "real page markdown should not be empty"
        );

        let cm_set = ChapterMarkdownSet {
            chapters: vec![ChapterMarkdownEntry {
                order: 1,
                chapter_id: "ch1".to_string(),
                title: "Leçon du 10 janvier 1979".to_string(),
                path: "chapters/001-lecon.md".to_string(),
                markdown_text: first_md.to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let phase1 = Phase1Structure {
            chapters: vec![ChapterRecord {
                chapter_id: "ch1".to_string(),
                title: "Leçon du 10 janvier 1979".to_string(),
                start_page: 21,
                end_page: 40,
                pages: (21..=40).collect(),
                source: fnm_core::types::ChapterSource::Fallback,
                boundary_state: fnm_core::types::BoundaryState::Ready,
            }],
            ..Default::default()
        };
        let (_bundle, zip_bytes, _report, _semantic) =
            build_module_export_bundle(&cm_set, &phase1, None, "test", "doc-test", &[])
                .expect("build_module_export_bundle");
        let files = read_zip_markdown_files(&zip_bytes).expect("read ZIP");
        let content = files.get("chapters/001-lecon.md").expect("chapter in ZIP");
        assert_eq!(
            content.trim(),
            first_md.trim(),
            "Phase6 must preserve real Biopolitics page content unchanged"
        );
    }

    /// Phase6 保持 Goldstein 真实页面内容不变
    #[test]
    fn contract_phase6_preserves_goldstein_content() {
        let raw_fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../../fnm-phase5/tests/fixtures/goldstein_intro.json"
        ))
        .expect("fixture JSON");
        let pages = raw_fixture["pages"].as_array().expect("pages array");
        let first_page = &pages[0];
        let first_md = first_page["markdown"].as_str().unwrap_or("");
        assert!(
            !first_md.is_empty(),
            "Goldstein real page markdown should not be empty"
        );

        let cm_set = ChapterMarkdownSet {
            chapters: vec![ChapterMarkdownEntry {
                order: 1,
                chapter_id: "introduction".to_string(),
                title: "Introduction".to_string(),
                path: "chapters/001-introduction.md".to_string(),
                markdown_text: first_md.to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let phase1 = Phase1Structure {
            chapters: vec![ChapterRecord {
                chapter_id: "introduction".to_string(),
                title: "Introduction".to_string(),
                start_page: 18,
                end_page: 24,
                pages: (18..=24).collect(),
                source: fnm_core::types::ChapterSource::Fallback,
                boundary_state: fnm_core::types::BoundaryState::Ready,
            }],
            ..Default::default()
        };
        let (_bundle, zip_bytes, _report, _semantic) =
            build_module_export_bundle(&cm_set, &phase1, None, "test", "doc-test", &[])
                .expect("build_module_export_bundle");
        let files = read_zip_markdown_files(&zip_bytes).expect("read ZIP");
        let content = files
            .get("chapters/001-introduction.md")
            .expect("chapter in ZIP");
        assert_eq!(
            content.trim(),
            first_md.trim(),
            "Phase6 must preserve real Goldstein page content unchanged"
        );
    }

    /// 语义 gate false → can_ship=false
    #[test]
    fn contract_phase6_semantic_gate_blocks_can_ship() {
        // front_matter 标题会触发 FRONT_MATTER_TITLE_RE → export_semantic_contract_ok=false
        let cm_set = ChapterMarkdownSet {
            chapters: vec![ChapterMarkdownEntry {
                order: 1,
                chapter_id: "ch1".to_string(),
                title: "Preface".to_string(),
                path: "chapters/001-preface.md".to_string(),
                markdown_text: "# Preface\n\nSome text here.".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let phase1 = Phase1Structure {
            chapters: vec![ChapterRecord {
                chapter_id: "ch1".to_string(),
                title: "Preface".to_string(),
                start_page: 1,
                end_page: 5,
                pages: (1..=5).collect(),
                source: fnm_core::types::ChapterSource::Fallback,
                boundary_state: fnm_core::types::BoundaryState::Ready,
            }],
            ..Default::default()
        };
        let (_bundle, _zip, report, _semantic) =
            build_module_export_bundle(&cm_set, &phase1, None, "test", "doc-test", &[])
                .expect("build_module_export_bundle");
        assert!(!report.can_ship, "semantic gate false must block can_ship");
        assert!(
            report
                .blocking_reasons
                .iter()
                .any(|r| r.contains("gate_export_semantic_contract_ok")),
            "blocking_reasons must include semantic gate failure"
        );
    }

    /// 章节顺序 gate false → can_ship=false
    #[test]
    fn contract_phase6_order_gate_blocks_can_ship() {
        let cm_set = ChapterMarkdownSet {
            chapters: vec![ChapterMarkdownEntry {
                order: 1,
                chapter_id: "ch1".to_string(),
                title: "Chapter 1".to_string(),
                path: "chapters/001-ch1.md".to_string(),
                markdown_text: "# Chapter 1\n\nBody text.".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let phase1 = Phase1Structure {
            chapters: vec![
                ChapterRecord {
                    chapter_id: "ch1".to_string(),
                    title: "Chapter 1".to_string(),
                    start_page: 1,
                    end_page: 5,
                    pages: (1..=5).collect(),
                    source: fnm_core::types::ChapterSource::Fallback,
                    boundary_state: fnm_core::types::BoundaryState::Ready,
                },
                ChapterRecord {
                    chapter_id: "ch2".to_string(),
                    title: "Chapter 2".to_string(),
                    start_page: 6,
                    end_page: 10,
                    pages: (6..=10).collect(),
                    source: fnm_core::types::ChapterSource::Fallback,
                    boundary_state: fnm_core::types::BoundaryState::Ready,
                },
            ],
            ..Default::default()
        };
        let (_bundle, _zip, report, _semantic) =
            build_module_export_bundle(&cm_set, &phase1, None, "test", "doc-test", &[])
                .expect("build_module_export_bundle");
        assert!(
            !report.can_ship,
            "missing chapter must block can_ship via order gate"
        );
        assert!(
            report
                .blocking_reasons
                .iter()
                .any(|r| r.contains("gate_order_follows_toc")),
            "blocking_reasons must include order gate failure"
        );
    }

    /// 定义闭合：正文引用与定义匹配时不产生 blocker
    #[test]
    fn contract_phase6_local_refs_closed() {
        let cm_set = ChapterMarkdownSet {
            chapters: vec![ChapterMarkdownEntry {
                order: 1,
                chapter_id: "ch1".to_string(),
                title: "Chapter 1".to_string(),
                path: "chapters/001-ch1.md".to_string(),
                markdown_text: "Text with ref [^1] here.\n\n[^1]: Definition.".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let phase1 = Phase1Structure {
            chapters: vec![ChapterRecord {
                chapter_id: "ch1".to_string(),
                title: "Chapter 1".to_string(),
                start_page: 1,
                end_page: 5,
                pages: (1..=5).collect(),
                source: fnm_core::types::ChapterSource::Fallback,
                boundary_state: fnm_core::types::BoundaryState::Ready,
            }],
            ..Default::default()
        };
        let (_bundle, _zip, report, _semantic) =
            build_module_export_bundle(&cm_set, &phase1, None, "test", "doc-test", &[])
                .expect("build_module_export_bundle");
        assert!(
            !report
                .blocking_reasons
                .iter()
                .any(|r| r.contains("merge_local_refs_unclosed")),
            "closed local refs must not produce merge_local_refs_unclosed blocker"
        );
    }

    /// 定义闭合：孤立定义产生 blocker
    #[test]
    fn contract_phase6_orphan_definition_detected() {
        let cm_set = ChapterMarkdownSet {
            chapters: vec![ChapterMarkdownEntry {
                order: 1,
                chapter_id: "ch1".to_string(),
                title: "Chapter 1".to_string(),
                path: "chapters/001-ch1.md".to_string(),
                markdown_text: "Text without ref.\n\n[^1]: Orphan definition.".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let phase1 = Phase1Structure {
            chapters: vec![ChapterRecord {
                chapter_id: "ch1".to_string(),
                title: "Chapter 1".to_string(),
                start_page: 1,
                end_page: 5,
                pages: (1..=5).collect(),
                source: fnm_core::types::ChapterSource::Fallback,
                boundary_state: fnm_core::types::BoundaryState::Ready,
            }],
            ..Default::default()
        };
        let (_bundle, _zip, report, _semantic) =
            build_module_export_bundle(&cm_set, &phase1, None, "test", "doc-test", &[])
                .expect("build_module_export_bundle");
        // 孤立定义应该被检测到（通过 file audit 的 orphan_note_definition）
        assert!(
            report.files.iter().any(|f| f
                .issue_codes
                .contains(&"orphan_note_definition".to_string())),
            "orphan definition must be detected"
        );
    }
}

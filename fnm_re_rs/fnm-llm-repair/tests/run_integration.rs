//! 顶层 `run_llm_repair` 集成测试（StubRepo 注入 + 边界情况）。
//!
//! 原 `src/lib.rs::tests` 模块拆出，使 lib.rs 满足 AGENTS.md 铁律 §4（mod.rs/lib.rs <400 行）。

use anyhow::Result;
use fnm_core::db::{
    Phase1Products, Phase2Products, Phase3Products, Phase4Products, Phase5Products, Phase6Products,
    Repository,
};
use fnm_core::records::*;
use fnm_core::types::*;
use fnm_llm_repair::page_context::NoopRenderer;
use fnm_llm_repair::{run_llm_repair, LlmRepairReport, RunLlmRepairParams};
use serde_json::{json, Value};
use std::sync::Mutex;

fn make_chapter(chapter_id: &str, title: &str, start: i64, end: i64) -> ChapterRecord {
    ChapterRecord {
        chapter_id: chapter_id.to_string(),
        title: title.to_string(),
        start_page: start,
        end_page: end,
        pages: (start..=end).collect(),
        source: ChapterSource::Fallback,
        boundary_state: BoundaryState::Ready,
    }
}

/// 内存 Repository stub 用于 `run_llm_repair` 集成测试。
///
/// 只实现 `run_llm_repair` 实际用到的方法，其它方法 `bail!`（遵循 AGENTS.md §9）。
struct StubRepo {
    chapters: Vec<ChapterRecord>,
    note_items: Vec<NoteItemRecord>,
    body_anchors: Vec<BodyAnchorRecord>,
    note_links: Vec<NoteLinkRecord>,
    pages: Vec<PagePartitionRecord>,
    cleared_scopes: Mutex<Vec<(String, Option<String>)>>,
    saved: Mutex<Vec<(String, String, String, Value)>>,
}

impl StubRepo {
    fn new() -> Self {
        Self {
            chapters: vec![],
            note_items: vec![],
            body_anchors: vec![],
            note_links: vec![],
            pages: vec![],
            cleared_scopes: Mutex::new(vec![]),
            saved: Mutex::new(vec![]),
        }
    }
}

impl Repository for StubRepo {
    fn list_fnm_pages(&self, _doc_id: &str) -> Result<Vec<PagePartitionRecord>> {
        Ok(self.pages.clone())
    }
    fn list_fnm_chapters(&self, _doc_id: &str) -> Result<Vec<ChapterRecord>> {
        Ok(self.chapters.clone())
    }
    fn list_fnm_section_heads(&self, _doc_id: &str) -> Result<Vec<SectionHeadRecord>> {
        Ok(vec![])
    }
    fn list_fnm_heading_candidates(&self, _doc_id: &str) -> Result<Vec<HeadingCandidate>> {
        Ok(vec![])
    }
    fn replace_fnm_phase1_products(&self, _doc_id: &str, _payload: &Phase1Products) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn list_fnm_note_regions(&self, _doc_id: &str) -> Result<Vec<NoteRegionRecord>> {
        Ok(vec![])
    }
    fn list_fnm_note_items(&self, _doc_id: &str) -> Result<Vec<NoteItemRecord>> {
        Ok(self.note_items.clone())
    }
    fn list_fnm_chapter_note_modes(&self, _doc_id: &str) -> Result<Vec<ChapterNoteModeRecord>> {
        Ok(vec![])
    }
    fn replace_fnm_phase2_products(&self, _doc_id: &str, _payload: &Phase2Products) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn list_fnm_body_anchors(&self, _doc_id: &str) -> Result<Vec<BodyAnchorRecord>> {
        Ok(self.body_anchors.clone())
    }
    fn list_fnm_note_links(&self, _doc_id: &str) -> Result<Vec<NoteLinkRecord>> {
        Ok(self.note_links.clone())
    }
    fn list_fnm_chapter_anchor_alignments(
        &self,
        _doc_id: &str,
    ) -> Result<Vec<ChapterAnchorAlignmentRecord>> {
        Ok(vec![])
    }
    fn list_fnm_chapter_endnotes(&self, _doc_id: &str) -> Result<Vec<ChapterEndnoteRecord>> {
        Ok(vec![])
    }
    fn list_fnm_paragraph_footnotes(&self, _doc_id: &str) -> Result<Vec<ParagraphFootnoteRecord>> {
        Ok(vec![])
    }
    fn list_fnm_review_overrides_v2(&self, _doc_id: &str) -> Result<Vec<Value>> {
        Ok(vec![])
    }
    fn clear_fnm_review_overrides_v2(&self, doc_id: &str, scope: Option<&str>) -> Result<()> {
        self.cleared_scopes
            .lock()
            .unwrap()
            .push((doc_id.to_string(), scope.map(|s| s.to_string())));
        Ok(())
    }
    fn batch_save_fnm_review_overrides_v2(
        &self,
        doc_id: &str,
        rows: &[(String, String, Value)],
    ) -> Result<()> {
        let mut saved = self.saved.lock().unwrap();
        for (scope, target_id, payload) in rows {
            saved.push((
                doc_id.to_string(),
                scope.clone(),
                target_id.clone(),
                payload.clone(),
            ));
        }
        Ok(())
    }
    fn replace_fnm_phase3_products(&self, _doc_id: &str, _payload: &Phase3Products) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn upsert_fnm_chapter_anchor_alignment(
        &self,
        _doc_id: &str,
        _chapter_id: &str,
        _alignment_status: &str,
        _body_anchor_count: i64,
        _endnote_count: i64,
        _mismatch: Option<Value>,
    ) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn replace_fnm_paragraph_footnotes(
        &self,
        _doc_id: &str,
        _chapter_id: &str,
        _footnotes: &[ParagraphFootnoteRecord],
    ) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn replace_fnm_chapter_endnotes(
        &self,
        _doc_id: &str,
        _chapter_id: &str,
        _endnotes: &[ChapterEndnoteRecord],
    ) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn list_fnm_translation_units(&self, _doc_id: &str) -> Result<Vec<TranslationUnitRecord>> {
        Ok(vec![])
    }
    fn replace_fnm_translation_units(
        &self,
        _doc_id: &str,
        _units: &[TranslationUnitRecord],
    ) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn list_fnm_structure_reviews(&self, _doc_id: &str) -> Result<Vec<StructureReviewRecord>> {
        Ok(vec![])
    }
    fn replace_fnm_structure_reviews(
        &self,
        _doc_id: &str,
        _reviews: &[StructureReviewRecord],
    ) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn replace_fnm_phase4_products(&self, _doc_id: &str, _payload: &Phase4Products) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn list_fnm_chapter_markdowns(&self, _doc_id: &str) -> Result<Vec<ChapterMarkdownEntry>> {
        Ok(vec![])
    }
    fn list_fnm_diagnostic_pages(&self, _doc_id: &str) -> Result<Vec<DiagnosticPageRecord>> {
        Ok(vec![])
    }
    fn list_fnm_diagnostic_notes(&self, _doc_id: &str) -> Result<Vec<DiagnosticNoteRecord>> {
        Ok(vec![])
    }
    fn replace_fnm_phase5_products(&self, _doc_id: &str, _payload: &Phase5Products) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn list_fnm_export_chapters(&self, _doc_id: &str) -> Result<Vec<ExportChapterRecord>> {
        Ok(vec![])
    }
    fn list_fnm_export_audit(&self, _doc_id: &str) -> Result<Option<ExportAuditReportRecord>> {
        Ok(None)
    }
    fn list_fnm_export_bundle(&self, _doc_id: &str) -> Result<Option<ExportBundleRecord>> {
        Ok(None)
    }
    fn replace_fnm_phase6_products(&self, _doc_id: &str, _payload: &Phase6Products) -> Result<()> {
        anyhow::bail!("not implemented")
    }
    fn upsert_document(&self, _doc_id: &str, _slug: &str) -> Result<()> {
        Ok(())
    }
}

// ── 集成测试 ────────────────────────────────────────────────────

#[tokio::test]
async fn test_run_llm_repair_no_clusters() {
    let repo = StubRepo::new();
    let renderer = NoopRenderer;
    let params = RunLlmRepairParams::new("doc-1", &repo, &[], "/tmp/x.pdf", &renderer);
    let report: LlmRepairReport = run_llm_repair(params).await.unwrap();
    assert_eq!(report.cluster_count, 0);
    assert_eq!(report.suggestion_count, 0);
    assert_eq!(report.auto_applied_count, 0);
    // 即使没有 cluster 也应清理一次旧 override
    assert_eq!(repo.cleared_scopes.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn test_run_llm_repair_skips_review_only_cluster() {
    // 仅含 ambiguous link 但 note_item / anchor 都缺 → cluster 被丢弃
    let mut repo = StubRepo::new();
    repo.chapters.push(make_chapter("c1", "Ch1", 1, 10));
    repo.note_links.push(NoteLinkRecord {
        link_id: "L1".to_string(),
        chapter_id: "c1".to_string(),
        region_id: "r1".to_string(),
        note_kind: NoteKind::Endnote,
        status: LinkStatus::Ambiguous,
        note_item_id: "".to_string(),
        anchor_id: "".to_string(),
        ..Default::default()
    });
    let renderer = NoopRenderer;
    let params = RunLlmRepairParams::new("doc-1", &repo, &[], "/tmp/x.pdf", &renderer);
    let report = run_llm_repair(params).await.unwrap();
    assert_eq!(report.cluster_count, 0);
}

#[tokio::test]
async fn test_run_llm_repair_orphan_cluster_skipped_without_real_llm() {
    // 真实 orphan_note 簇但没有 model_args → resolve_repair_model_args 必失败
    // 测试 cluster 计数与 skip 路径汇合
    let mut repo = StubRepo::new();
    repo.chapters.push(make_chapter("c1", "Ch1", 1, 10));
    repo.note_items.push(NoteItemRecord {
        note_item_id: "n1".to_string(),
        chapter_id: "c1".to_string(),
        page_no: 5,
        marker: "1".to_string(),
        text: "note text".to_string(),
        ..Default::default()
    });
    repo.body_anchors.push(BodyAnchorRecord {
        anchor_id: "a1".to_string(),
        chapter_id: "c1".to_string(),
        page_no: 5,
        normalized_marker: "1".to_string(),
        ..Default::default()
    });
    // ambiguous link 触发同时收集 note 和 anchor
    repo.note_links.push(NoteLinkRecord {
        link_id: "L1".to_string(),
        chapter_id: "c1".to_string(),
        region_id: "r1".to_string(),
        note_kind: NoteKind::Endnote,
        status: LinkStatus::Ambiguous,
        note_item_id: "n1".to_string(),
        anchor_id: "a1".to_string(),
        ..Default::default()
    });

    // 提供假 model_args，但 base_url 指向本地无服务端口 → 请求必失败
    let renderer = NoopRenderer;
    let model_args = json!({
        "provider": "qwen",
        "model_id": "qwen-test",
        "api_key": "sk-test",
        "base_url": "http://127.0.0.1:1",
        "request_overrides": {},
        "display_label": "test",
    });
    let mut params = RunLlmRepairParams::new("doc-1", &repo, &[], "/tmp/x.pdf", &renderer);
    params.model_args = Some(model_args);
    // ambiguous + 双方都在 → cluster 含 1 unmatched_note + 1 unmatched_anchor
    // request_mode = paired，需要请求 LLM → 走 HTTP 失败
    let result = run_llm_repair(params).await;
    assert!(
        result.is_err(),
        "期望 network unreachable / connection refused"
    );
}

#[test]
fn test_run_llm_repair_params_defaults() {
    let repo = StubRepo::new();
    let renderer = NoopRenderer;
    let params = RunLlmRepairParams::new("doc-1", &repo, &[], "/tmp/x.pdf", &renderer);
    assert!(params.auto_apply);
    assert_eq!(params.confidence_threshold, 0.9);
    assert!(params.clear_materialized_overrides);
    assert!(params.cluster_limit.is_none());
    assert!(params.trace_callback.is_none());
}

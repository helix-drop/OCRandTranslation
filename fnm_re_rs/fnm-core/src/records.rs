//! ←→ FNM_RE/models.py
//! 所有 dataclass 翻译为 Rust struct。
//!
//! 共 37 个 struct，按 phase 顺序排列。
//! 每个 struct 必须能 JSON round-trip 与 Python `asdict()` 输出对齐。
//!
//! # 目录（按行号导航）
//!
//! - **共享类型** (行 ~16-104): `PipelineIdentity`, `PagePartitionRecord`,
//!   `HeadingCandidate`, `ChapterRecord`, `SectionHeadRecord`
//! - **Phase 1** (行 ~108-158): `Phase1Summary`, `Phase1Structure`
//! - **Phase 2** (行 ~163-335): `NoteRegionRecord`, `NoteItemRecord`,
//!   `ChapterNoteModeRecord`, `ChapterLinkContract`, `Phase2Summary`, `Phase2Structure`
//! - **Phase 3** (行 ~339-555): `BodyAnchorRecord`, `ChapterEndnoteRecord`,
//!   `ParagraphFootnoteRecord`, `ChapterAnchorAlignmentRecord`, `NoteLinkRecord`,
//!   `Phase3Summary`, `Phase3Structure`
//! - **Phase 4** (行 ~559-757): `StructureReviewRecord`, `StructureStatusRecord`,
//!   `Phase4Summary`, `Phase4Structure`
//! - **Phase 5** (行 ~761-1049): `UnitParagraphRecord`, `UnitPageSegmentRecord`,
//!   `TranslationUnitRecord`, `DiagnosticEntryRecord`, `DiagnosticPageRecord`,
//!   `DiagnosticNoteRecord`, `Phase5Summary`, `Phase5Structure`
//! - **Phase 6 / Export** (行 ~1053-1361): `ExportChapterRecord`, `ExportBundleRecord`,
//!   `ExportAuditFileRecord`, `ExportAuditReportRecord`, `Phase6Summary`, `Phase6Structure`
//!
//! 注：本文件长（1361 行）但全是数据声明，无业务逻辑。物理拆 7 个子模块
//! 会让"按 phase 找 struct"需要在 8 个 tab 之间跳转，反而损害可维护性。
//! 当前保持单文件 + 显式目录索引——按 § 4 精神实质更优。

use crate::types::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

// ── 跨 phase 基础类型 ──────────────────────────────────────────

/// 每次 pipeline run 的统一身份标识。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PipelineIdentity {
    #[serde(default)]
    pub run_id: String,
    #[serde(default)]
    pub pipeline_version: String,
    #[serde(default)]
    pub raw_pages_hash: String,
    #[serde(default)]
    pub toc_hash: String,
    #[serde(default)]
    pub override_hash: String,
    #[serde(default)]
    pub parser_version: String,
    #[serde(default)]
    pub freeze_version: String,
    #[serde(default)]
    pub chunk_plan_hash: String,
    #[serde(default)]
    pub max_body_chars: i64,
    #[serde(default)]
    pub created_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PagePartitionRecord {
    pub page_no: i64,
    pub target_pdf_page: i64,
    pub page_role: PageRole,
    pub confidence: f64,
    pub reason: String,
    pub section_hint: String,
    pub has_note_heading: bool,
    #[serde(default)]
    pub note_scan_summary: Value,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct HeadingCandidate {
    pub heading_id: String,
    pub page_no: i64,
    pub text: String,
    pub normalized_text: String,
    pub source: String,
    pub block_label: String,
    pub top_band: bool,
    pub confidence: f64,
    pub heading_family_guess: String,
    pub suppressed_as_chapter: bool,
    pub reject_reason: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub font_height: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub x: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub y: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub width_estimate: Option<f64>,
    #[serde(default)]
    pub font_name: String,
    #[serde(default)]
    pub font_weight_hint: String,
    #[serde(default)]
    pub align_hint: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub width_ratio: Option<f64>,
    #[serde(default)]
    pub heading_level_hint: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterRecord {
    pub chapter_id: String,
    pub title: String,
    pub start_page: i64,
    pub end_page: i64,
    pub pages: Vec<i64>,
    pub source: ChapterSource,
    pub boundary_state: BoundaryState,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SectionHeadRecord {
    pub section_head_id: String,
    pub chapter_id: String,
    pub title: String,
    pub page_no: i64,
    pub level: i64,
    pub source: String,
}

// ── Phase 1 ────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase1Summary {
    #[serde(default)]
    pub page_partition_summary: Value,
    #[serde(default)]
    pub heading_review_summary: Value,
    #[serde(default)]
    pub heading_graph_summary: Value,
    #[serde(default)]
    pub chapter_source_summary: Value,
    #[serde(default)]
    pub visual_toc_conflict_count: i64,
    #[serde(default)]
    pub toc_alignment_summary: Value,
    #[serde(default)]
    pub toc_semantic_summary: Value,
    #[serde(default)]
    pub toc_role_summary: Value,
    #[serde(default)]
    pub container_titles: Vec<String>,
    #[serde(default)]
    pub post_body_titles: Vec<String>,
    #[serde(default)]
    pub back_matter_titles: Vec<String>,
    #[serde(default = "default_true")]
    pub chapter_title_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub chapter_section_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub toc_semantic_contract_ok: bool,
    #[serde(default)]
    pub toc_semantic_blocking_reasons: Vec<String>,
    #[serde(default)]
    pub visual_toc_endnotes_summary: Value,
}

/// 页面角色记录（含 chapter 归属信息）。←→ Python `TocPageRole`
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TocPageRole {
    #[serde(default)]
    pub page_no: i64,
    #[serde(default)]
    pub role: String,
    #[serde(default)]
    pub source_role: String,
    #[serde(default)]
    pub reason: String,
    #[serde(default)]
    pub chapter_id: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TocNode {
    #[serde(default)]
    pub node_id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub role: String,
    #[serde(default)]
    pub level: i64,
    #[serde(default)]
    pub target_pdf_page: i64,
    #[serde(default)]
    pub parent_id: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase1Structure {
    #[serde(default)]
    pub pages: Vec<PagePartitionRecord>,
    #[serde(default)]
    pub heading_candidates: Vec<HeadingCandidate>,
    #[serde(default)]
    pub chapters: Vec<ChapterRecord>,
    #[serde(default)]
    pub section_heads: Vec<SectionHeadRecord>,
    #[serde(default)]
    pub endnote_explorer_hints: Value,
    #[serde(default)]
    pub summary: Phase1Summary,
    /// TOC 树节点列表。←→ Python `TocStructure.toc_tree: list[TocNode]`
    #[serde(default)]
    pub toc_tree: Vec<TocNode>,
    /// 每页的角色分配（含 chapter_id）。←→ Python `TocStructure.pages: list[TocPageRole]`
    #[serde(default)]
    pub page_roles: Vec<TocPageRole>,
}

// ── Phase 2 ────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NoteRegionRecord {
    pub region_id: String,
    pub chapter_id: String,
    pub page_start: i64,
    pub page_end: i64,
    pub pages: Vec<i64>,
    pub note_kind: NoteKind,
    pub scope: RegionScope,
    pub source: RegionSource,
    pub heading_text: String,
    pub start_reason: String,
    pub end_reason: String,
    pub region_marker_alignment_ok: bool,
    pub region_start_first_source_marker: String,
    pub region_first_note_item_marker: String,
    pub review_required: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NoteItemRecord {
    pub note_item_id: String,
    pub region_id: String,
    pub chapter_id: String,
    pub page_no: i64,
    pub marker: String,
    pub marker_type: String,
    pub text: String,
    pub source: String,
    pub source_page_label: String,
    pub is_reconstructed: bool,
    pub review_required: bool,
    pub note_kind: NoteKind,
    /// Phase 2 Layer 专有字段：projection_mode
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub projection_mode: Option<String>,
    /// Phase 2 Layer 专有字段：owner_chapter_id
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub owner_chapter_id: Option<String>,
    /// Phase 2 Layer 专有字段：source_marker
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_marker: Option<String>,
    /// Phase 2 Layer 专有字段：normalized_marker
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub normalized_marker: Option<String>,
}

impl Default for NoteItemRecord {
    fn default() -> Self {
        NoteItemRecord {
            note_item_id: String::new(),
            region_id: String::new(),
            chapter_id: String::new(),
            page_no: 0,
            marker: String::new(),
            marker_type: String::new(),
            text: String::new(),
            source: String::new(),
            source_page_label: String::new(),
            is_reconstructed: false,
            review_required: false,
            note_kind: NoteKind::Footnote,
            projection_mode: None,
            owner_chapter_id: None,
            source_marker: None,
            normalized_marker: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterNoteModeRecord {
    pub chapter_id: String,
    pub note_mode: NoteMode,
    #[serde(default)]
    pub region_ids: Vec<String>,
    #[serde(default)]
    pub primary_region_scope: String,
    #[serde(default)]
    pub has_footnote_band: bool,
    #[serde(default)]
    pub has_endnote_region: bool,
}

/// 章节链接契约（对应 Python `ChapterLinkContract`）。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ChapterLinkContract {
    pub chapter_id: String,
    pub requires_endnote_contract: bool,
    pub book_type: String,
    pub note_mode: String,
    pub first_marker_is_one: bool,
    pub endnotes_all_matched: bool,
    pub no_ambiguous_left: bool,
    pub no_orphan_note: bool,
    pub endnote_only_no_orphan_anchor: bool,
    #[serde(default)]
    pub failure_link_ids: Vec<String>,
    pub has_marker_gap: bool,
    pub def_anchor_mismatch: bool,
    pub def_count: i64,
    pub anchor_total: i64,
    #[serde(default)]
    pub marker_sequence: Vec<i64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase2Summary {
    #[serde(default)]
    pub page_partition_summary: Value,
    #[serde(default)]
    pub heading_review_summary: Value,
    #[serde(default)]
    pub heading_graph_summary: Value,
    #[serde(default)]
    pub chapter_source_summary: Value,
    #[serde(default)]
    pub visual_toc_conflict_count: i64,
    #[serde(default)]
    pub toc_alignment_summary: Value,
    #[serde(default)]
    pub toc_semantic_summary: Value,
    #[serde(default)]
    pub toc_role_summary: Value,
    #[serde(default)]
    pub container_titles: Vec<String>,
    #[serde(default)]
    pub post_body_titles: Vec<String>,
    #[serde(default)]
    pub back_matter_titles: Vec<String>,
    #[serde(default = "default_true")]
    pub chapter_title_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub chapter_section_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub toc_semantic_contract_ok: bool,
    #[serde(default)]
    pub toc_semantic_blocking_reasons: Vec<String>,
    #[serde(default)]
    pub note_region_summary: Value,
    #[serde(default)]
    pub note_item_summary: Value,
    #[serde(default)]
    pub chapter_note_mode_summary: Value,
    #[serde(default = "default_true")]
    pub chapter_endnote_region_alignment_ok: bool,
    #[serde(default)]
    pub chapter_endnote_start_page_map: HashMap<String, i64>,
    #[serde(default)]
    pub review_flags: Vec<String>,
    #[serde(default)]
    pub visual_toc_endnotes_summary: Value,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase2Structure {
    #[serde(default)]
    pub pages: Vec<PagePartitionRecord>,
    #[serde(default)]
    pub heading_candidates: Vec<HeadingCandidate>,
    #[serde(default)]
    pub chapters: Vec<ChapterRecord>,
    #[serde(default)]
    pub section_heads: Vec<SectionHeadRecord>,
    #[serde(default)]
    pub note_regions: Vec<NoteRegionRecord>,
    #[serde(default)]
    pub note_items: Vec<NoteItemRecord>,
    #[serde(default)]
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    #[serde(default)]
    pub summary: Phase2Summary,
}

// ── Phase 3 ────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BodyAnchorRecord {
    pub anchor_id: String,
    pub chapter_id: String,
    pub page_no: i64,
    pub paragraph_index: i64,
    pub char_start: i64,
    pub char_end: i64,
    pub source_marker: String,
    pub normalized_marker: String,
    pub anchor_kind: AnchorKind,
    pub certainty: f64,
    pub source_text: String,
    pub source: String,
    pub synthetic: bool,
    pub ocr_repaired_from_marker: String,
}

impl Default for BodyAnchorRecord {
    fn default() -> Self {
        BodyAnchorRecord {
            anchor_id: String::new(),
            chapter_id: String::new(),
            page_no: 0,
            paragraph_index: 0,
            char_start: 0,
            char_end: 0,
            source_marker: String::new(),
            normalized_marker: String::new(),
            anchor_kind: AnchorKind::Unknown,
            certainty: 0.0,
            source_text: String::new(),
            source: String::new(),
            synthetic: false,
            ocr_repaired_from_marker: String::new(),
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ChapterEndnoteRecord {
    #[serde(default)]
    pub doc_id: String,
    #[serde(default)]
    pub chapter_id: String,
    #[serde(default)]
    pub ordinal: i64,
    #[serde(default)]
    pub marker: String,
    #[serde(default)]
    pub numbering_scheme: String,
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub source_page_no: i64,
    #[serde(default)]
    pub is_reconstructed: bool,
    #[serde(default = "default_true")]
    pub review_required: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ParagraphFootnoteRecord {
    #[serde(default)]
    pub doc_id: String,
    #[serde(default)]
    pub chapter_id: String,
    #[serde(default)]
    pub page_no: i64,
    #[serde(default)]
    pub paragraph_index: i64,
    #[serde(default)]
    pub attachment_kind: String,
    #[serde(default)]
    pub source_marker: String,
    #[serde(default)]
    pub text: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ChapterAnchorAlignmentRecord {
    #[serde(default)]
    pub doc_id: String,
    #[serde(default)]
    pub chapter_id: String,
    #[serde(default)]
    pub alignment_status: String,
    #[serde(default)]
    pub body_anchor_count: i64,
    #[serde(default)]
    pub endnote_count: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mismatch: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NoteLinkRecord {
    pub link_id: String,
    pub chapter_id: String,
    pub region_id: String,
    pub note_item_id: String,
    pub anchor_id: String,
    pub status: LinkStatus,
    pub resolver: LinkResolver,
    pub confidence: f64,
    pub note_kind: NoteKind,
    pub marker: String,
    pub page_no_start: i64,
    pub page_no_end: i64,
}

impl Default for NoteLinkRecord {
    fn default() -> Self {
        NoteLinkRecord {
            link_id: String::new(),
            chapter_id: String::new(),
            region_id: String::new(),
            note_item_id: String::new(),
            anchor_id: String::new(),
            status: LinkStatus::Matched,
            resolver: LinkResolver::Rule,
            confidence: 0.0,
            note_kind: NoteKind::Footnote,
            marker: String::new(),
            page_no_start: 0,
            page_no_end: 0,
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase3Summary {
    #[serde(default)]
    pub page_partition_summary: Value,
    #[serde(default)]
    pub heading_review_summary: Value,
    #[serde(default)]
    pub heading_graph_summary: Value,
    #[serde(default)]
    pub chapter_source_summary: Value,
    #[serde(default)]
    pub visual_toc_conflict_count: i64,
    #[serde(default)]
    pub toc_alignment_summary: Value,
    #[serde(default)]
    pub toc_semantic_summary: Value,
    #[serde(default)]
    pub toc_role_summary: Value,
    #[serde(default)]
    pub container_titles: Vec<String>,
    #[serde(default)]
    pub post_body_titles: Vec<String>,
    #[serde(default)]
    pub back_matter_titles: Vec<String>,
    #[serde(default = "default_true")]
    pub chapter_title_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub chapter_section_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub toc_semantic_contract_ok: bool,
    #[serde(default)]
    pub toc_semantic_blocking_reasons: Vec<String>,
    #[serde(default)]
    pub note_region_summary: Value,
    #[serde(default)]
    pub note_item_summary: Value,
    #[serde(default)]
    pub chapter_note_mode_summary: Value,
    #[serde(default = "default_true")]
    pub chapter_endnote_region_alignment_ok: bool,
    #[serde(default)]
    pub chapter_endnote_start_page_map: HashMap<String, i64>,
    #[serde(default)]
    pub body_anchor_summary: Value,
    #[serde(default)]
    pub note_link_summary: Value,
    #[serde(default)]
    pub review_seed_summary: Value,
    #[serde(default)]
    pub review_flags: Vec<String>,
    #[serde(default)]
    pub paragraph_footnote_summary: Value,
    #[serde(default)]
    pub paragraph_endnote_summary: Value,
    #[serde(default)]
    pub chapter_anchor_alignment_summary: Value,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase3Structure {
    #[serde(default)]
    pub pages: Vec<PagePartitionRecord>,
    #[serde(default)]
    pub heading_candidates: Vec<HeadingCandidate>,
    #[serde(default)]
    pub chapters: Vec<ChapterRecord>,
    #[serde(default)]
    pub section_heads: Vec<SectionHeadRecord>,
    #[serde(default)]
    pub note_regions: Vec<NoteRegionRecord>,
    #[serde(default)]
    pub note_items: Vec<NoteItemRecord>,
    #[serde(default)]
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    #[serde(default)]
    pub body_anchors: Vec<BodyAnchorRecord>,
    #[serde(default)]
    pub note_links: Vec<NoteLinkRecord>,
    #[serde(default)]
    pub paragraph_footnotes: Vec<ParagraphFootnoteRecord>,
    #[serde(default)]
    pub paragraph_endnotes: Vec<ChapterEndnoteRecord>,
    #[serde(default)]
    pub chapter_anchor_alignments: Vec<ChapterAnchorAlignmentRecord>,
    #[serde(default)]
    pub summary: Phase3Summary,
}

// ── Phase 4 ────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StructureReviewRecord {
    pub review_id: String,
    pub review_type: String,
    pub chapter_id: String,
    pub page_start: i64,
    pub page_end: i64,
    pub severity: String,
    #[serde(default)]
    pub payload: Value,
}

/// fnm_runs 表行记录。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FnmRunRecord {
    #[serde(default)]
    pub id: i64,
    #[serde(default)]
    pub doc_id: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub error_msg: Option<String>,
    #[serde(default)]
    pub page_count: i64,
    #[serde(default)]
    pub section_count: i64,
    #[serde(default)]
    pub note_count: i64,
    #[serde(default)]
    pub unit_count: i64,
    #[serde(default)]
    pub validation_json: Option<String>,
    #[serde(default)]
    pub structure_state: Option<String>,
    #[serde(default)]
    pub review_counts_json: Option<String>,
    #[serde(default)]
    pub blocking_reasons_json: Option<String>,
    #[serde(default)]
    pub link_summary_json: Option<String>,
    #[serde(default)]
    pub page_partition_summary_json: Option<String>,
    #[serde(default)]
    pub chapter_mode_summary_json: Option<String>,
    #[serde(default)]
    pub created_at: i64,
    #[serde(default)]
    pub updated_at: i64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct StructureStatusRecord {
    #[serde(default)]
    pub structure_state: String,
    #[serde(default)]
    pub review_counts: HashMap<String, i64>,
    #[serde(default)]
    pub blocking_reasons: Vec<String>,
    #[serde(default)]
    pub link_summary: HashMap<String, i64>,
    #[serde(default)]
    pub page_partition_summary: Value,
    #[serde(default)]
    pub chapter_mode_summary: HashMap<String, i64>,
    #[serde(default)]
    pub heading_review_summary: Value,
    #[serde(default)]
    pub heading_graph_summary: Value,
    #[serde(default)]
    pub chapter_source_summary: Value,
    #[serde(default)]
    pub visual_toc_conflict_count: i64,
    #[serde(default)]
    pub toc_alignment_summary: Value,
    #[serde(default)]
    pub toc_semantic_summary: Value,
    #[serde(default)]
    pub toc_role_summary: Value,
    #[serde(default)]
    pub container_titles: Vec<String>,
    #[serde(default)]
    pub post_body_titles: Vec<String>,
    #[serde(default)]
    pub back_matter_titles: Vec<String>,
    #[serde(default)]
    pub visual_toc_endnotes_summary: Value,
    #[serde(default = "default_true")]
    pub toc_semantic_contract_ok: bool,
    #[serde(default)]
    pub toc_semantic_blocking_reasons: Vec<String>,
    #[serde(default = "default_true")]
    pub chapter_title_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub chapter_section_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub chapter_endnote_region_alignment_ok: bool,
    #[serde(default)]
    pub chapter_endnote_region_alignment_summary: Value,
    #[serde(default = "default_true")]
    pub manual_toc_ready: bool,
    #[serde(default)]
    pub manual_toc_required: bool,
    #[serde(default)]
    pub manual_toc_summary: Value,
    #[serde(default)]
    pub page_count: i64,
    #[serde(default)]
    pub chapter_count: i64,
    #[serde(default)]
    pub section_head_count: i64,
    #[serde(default)]
    pub review_count: i64,
    #[serde(default)]
    pub chapter_progress_summary: Value,
    #[serde(default)]
    pub note_region_progress_summary: Value,
    #[serde(default)]
    pub chapter_binding_summary: Value,
    #[serde(default)]
    pub note_capture_summary: Value,
    #[serde(default)]
    pub footnote_synthesis_summary: Value,
    #[serde(default)]
    pub chapter_link_contract_summary: Value,
    #[serde(default)]
    pub book_endnote_stream_summary: Value,
    #[serde(default)]
    pub freeze_note_unit_summary: Value,
    #[serde(default)]
    pub chapter_issue_counts: Value,
    #[serde(default)]
    pub chapter_issue_summary: Vec<Value>,
    #[serde(default)]
    pub export_drift_summary: Value,
    #[serde(default)]
    pub chapter_local_endnote_contract_ok: bool,
    #[serde(default = "default_true")]
    pub export_semantic_contract_ok: bool,
    #[serde(default)]
    pub front_matter_leak_detected: bool,
    #[serde(default)]
    pub toc_residue_detected: bool,
    #[serde(default)]
    pub mid_paragraph_heading_detected: bool,
    #[serde(default)]
    pub duplicate_paragraph_detected: bool,
    #[serde(default)]
    pub export_ready_test: bool,
    #[serde(default)]
    pub export_ready_real: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase4Summary {
    #[serde(default)]
    pub page_partition_summary: Value,
    #[serde(default)]
    pub heading_review_summary: Value,
    #[serde(default)]
    pub heading_graph_summary: Value,
    #[serde(default)]
    pub chapter_source_summary: Value,
    #[serde(default)]
    pub visual_toc_conflict_count: i64,
    #[serde(default)]
    pub toc_alignment_summary: Value,
    #[serde(default)]
    pub toc_semantic_summary: Value,
    #[serde(default)]
    pub toc_role_summary: Value,
    #[serde(default)]
    pub container_titles: Vec<String>,
    #[serde(default)]
    pub post_body_titles: Vec<String>,
    #[serde(default)]
    pub back_matter_titles: Vec<String>,
    #[serde(default = "default_true")]
    pub chapter_title_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub chapter_section_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub toc_semantic_contract_ok: bool,
    #[serde(default)]
    pub toc_semantic_blocking_reasons: Vec<String>,
    #[serde(default)]
    pub note_region_summary: Value,
    #[serde(default)]
    pub note_item_summary: Value,
    #[serde(default)]
    pub chapter_note_mode_summary: Value,
    #[serde(default = "default_true")]
    pub chapter_endnote_region_alignment_ok: bool,
    #[serde(default)]
    pub chapter_endnote_start_page_map: HashMap<String, i64>,
    #[serde(default)]
    pub body_anchor_summary: Value,
    #[serde(default)]
    pub note_link_summary: Value,
    #[serde(default)]
    pub review_seed_summary: Value,
    #[serde(default)]
    pub review_type_counts: HashMap<String, i64>,
    #[serde(default)]
    pub override_summary: Value,
    #[serde(default)]
    pub review_flags: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase4Structure {
    #[serde(default)]
    pub pages: Vec<PagePartitionRecord>,
    #[serde(default)]
    pub heading_candidates: Vec<HeadingCandidate>,
    #[serde(default)]
    pub chapters: Vec<ChapterRecord>,
    #[serde(default)]
    pub section_heads: Vec<SectionHeadRecord>,
    #[serde(default)]
    pub note_regions: Vec<NoteRegionRecord>,
    #[serde(default)]
    pub note_items: Vec<NoteItemRecord>,
    #[serde(default)]
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    #[serde(default)]
    pub body_anchors: Vec<BodyAnchorRecord>,
    #[serde(default)]
    pub note_links: Vec<NoteLinkRecord>,
    #[serde(default)]
    pub effective_note_links: Vec<NoteLinkRecord>,
    #[serde(default)]
    pub structure_reviews: Vec<StructureReviewRecord>,
    #[serde(default)]
    pub status: StructureStatusRecord,
    #[serde(default)]
    pub summary: Phase4Summary,
}

// ── Phase 4 Frozen 类型 ────────────────────────────────────────

/// ←→ Python `FNM_RE/modules/types.py:FrozenRefEntry` (L290)
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FrozenRefEntry {
    #[serde(default)]
    pub link_id: String,
    #[serde(default)]
    pub chapter_id: String,
    #[serde(default)]
    pub anchor_id: String,
    #[serde(default)]
    pub note_item_id: String,
    #[serde(default)]
    pub target_ref: String,
    #[serde(default)]
    pub decision: String,
    #[serde(default)]
    pub reason: String,
    #[serde(default)]
    pub skip_category: String,
    #[serde(default)]
    pub page_no: i64,
}

/// ←→ Python `FNM_RE/modules/types.py:FrozenUnit` (L303)
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FrozenUnit {
    #[serde(default)]
    pub unit_id: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub owner_kind: String,
    #[serde(default)]
    pub owner_id: String,
    #[serde(default)]
    pub section_id: String,
    #[serde(default)]
    pub section_title: String,
    #[serde(default)]
    pub section_start_page: i64,
    #[serde(default)]
    pub section_end_page: i64,
    #[serde(default)]
    pub note_id: String,
    #[serde(default)]
    pub page_start: i64,
    #[serde(default)]
    pub page_end: i64,
    #[serde(default)]
    pub char_count: i64,
    #[serde(default)]
    pub source_text: String,
    #[serde(default)]
    pub translated_text: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub error_msg: String,
    #[serde(default)]
    pub target_ref: String,
    #[serde(default)]
    pub page_segments: Vec<UnitPageSegmentRecord>,
    #[serde(default)]
    pub source_hash: String,
    #[serde(default)]
    pub segment_plan_hash: String,
    #[serde(default)]
    pub pipeline_run_id: String,
}

/// ←→ Python `FNM_RE/modules/types.py:FrozenUnits` (L328)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FrozenUnits {
    #[serde(default)]
    pub body_units: Vec<FrozenUnit>,
    #[serde(default)]
    pub note_units: Vec<FrozenUnit>,
    #[serde(default)]
    pub ref_map: Vec<FrozenRefEntry>,
    #[serde(default)]
    pub freeze_summary: serde_json::Value,
}

impl Default for FrozenUnits {
    fn default() -> Self {
        FrozenUnits {
            body_units: Vec::new(),
            note_units: Vec::new(),
            ref_map: Vec::new(),
            freeze_summary: serde_json::Value::Object(serde_json::Map::new()),
        }
    }
}

// ── Phase 5 ────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct UnitParagraphRecord {
    #[serde(default)]
    pub order: i64,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub heading_level: i64,
    #[serde(default)]
    pub source_text: String,
    #[serde(default)]
    pub display_text: String,
    #[serde(default)]
    pub cross_page: Value,
    #[serde(default)]
    pub consumed_by_prev: bool,
    #[serde(default)]
    pub section_path: Vec<String>,
    #[serde(default)]
    pub print_page_label: String,
    #[serde(default)]
    pub translated_text: String,
    #[serde(default)]
    pub translation_status: String,
    #[serde(default)]
    pub attempt_count: i64,
    #[serde(default)]
    pub last_error: String,
    #[serde(default)]
    pub manual_resolved: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct UnitPageSegmentRecord {
    #[serde(default)]
    pub page_no: i64,
    #[serde(default)]
    pub paragraph_count: i64,
    #[serde(default)]
    pub source_text: String,
    #[serde(default)]
    pub display_text: String,
    #[serde(default)]
    pub paragraphs: Vec<UnitParagraphRecord>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TranslationUnitRecord {
    #[serde(default)]
    pub unit_id: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub owner_kind: String,
    #[serde(default)]
    pub owner_id: String,
    #[serde(default)]
    pub section_id: String,
    #[serde(default)]
    pub section_title: String,
    #[serde(default)]
    pub section_start_page: i64,
    #[serde(default)]
    pub section_end_page: i64,
    #[serde(default)]
    pub note_id: String,
    #[serde(default)]
    pub page_start: i64,
    #[serde(default)]
    pub page_end: i64,
    #[serde(default)]
    pub char_count: i64,
    #[serde(default)]
    pub source_text: String,
    #[serde(default)]
    pub translated_text: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub error_msg: String,
    #[serde(default)]
    pub target_ref: String,
    #[serde(default)]
    pub page_segments: Vec<UnitPageSegmentRecord>,
    #[serde(default)]
    pub source_hash: String,
    #[serde(default)]
    pub segment_plan_hash: String,
    #[serde(default)]
    pub pipeline_run_id: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DiagnosticEntryRecord {
    #[serde(default)]
    pub original: String,
    #[serde(default)]
    pub translation: String,
    #[serde(default)]
    pub footnotes: String,
    #[serde(default)]
    pub footnotes_translation: String,
    #[serde(default)]
    pub heading_level: i64,
    #[serde(default)]
    pub pages: String,
    #[serde(default, rename = "_startBP")]
    pub _start_bp: i64,
    #[serde(default, rename = "_endBP")]
    pub _end_bp: i64,
    #[serde(default, rename = "_printPageLabel")]
    pub _print_page_label: String,
    #[serde(default, rename = "_status")]
    pub _status: String,
    #[serde(default, rename = "_error")]
    pub _error: String,
    #[serde(default, rename = "_translation_source")]
    pub _translation_source: String,
    #[serde(default, rename = "_machine_translation")]
    pub _machine_translation: String,
    #[serde(default, rename = "_manual_translation")]
    pub _manual_translation: String,
    #[serde(default)]
    pub _cross_page: Value,
    #[serde(default)]
    pub _section_path: Vec<String>,
    #[serde(default)]
    pub _fnm_refs: Vec<Value>,
    #[serde(default)]
    pub _note_kind: String,
    #[serde(default)]
    pub _note_marker: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub _note_number: Option<i64>,
    #[serde(default)]
    pub _note_section_title: String,
    #[serde(default)]
    pub _note_confidence: f64,
    #[serde(default)]
    pub _translation_status: String,
    #[serde(default)]
    pub _attempt_count: i64,
    #[serde(default)]
    pub _manual_resolved: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DiagnosticPageRecord {
    #[serde(default, rename = "_pageBP")]
    pub _page_bp: i64,
    #[serde(default, rename = "_status")]
    pub _status: String,
    #[serde(default)]
    pub pages: String,
    #[serde(default)]
    pub _page_entries: Vec<DiagnosticEntryRecord>,
    #[serde(default)]
    pub _fnm_source: Value,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DiagnosticNoteRecord {
    #[serde(default)]
    pub note_id: String,
    #[serde(default)]
    pub section_id: String,
    #[serde(default)]
    pub section_title: String,
    #[serde(default)]
    pub section_start_page: i64,
    #[serde(default)]
    pub section_end_page: i64,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub original_marker: String,
    #[serde(default)]
    pub start_page: i64,
    #[serde(default)]
    pub pages: Vec<i64>,
    #[serde(default)]
    pub source_text: String,
    #[serde(default)]
    pub translated_text: String,
    #[serde(default)]
    pub translate_status: String,
    #[serde(default)]
    pub region_id: String,
}

// ── Phase 5 / Chapter Markdown ───────────────────────────────────

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ChapterMarkdownEntry {
    #[serde(default)]
    pub order: i64,
    #[serde(default)]
    pub chapter_id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub markdown_text: String,
    #[serde(default)]
    pub start_page: i64,
    #[serde(default)]
    pub end_page: i64,
    #[serde(default)]
    pub pages: Vec<i64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ChapterMarkdownSet {
    #[serde(default)]
    pub chapters: Vec<ChapterMarkdownEntry>,
    #[serde(default)]
    pub chapter_contract_summary: serde_json::Value,
    #[serde(default)]
    pub merge_summary: serde_json::Value,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase5Summary {
    #[serde(default)]
    pub page_partition_summary: Value,
    #[serde(default)]
    pub heading_review_summary: Value,
    #[serde(default)]
    pub heading_graph_summary: Value,
    #[serde(default)]
    pub chapter_source_summary: Value,
    #[serde(default)]
    pub visual_toc_conflict_count: i64,
    #[serde(default)]
    pub toc_alignment_summary: Value,
    #[serde(default)]
    pub toc_semantic_summary: Value,
    #[serde(default)]
    pub toc_role_summary: Value,
    #[serde(default)]
    pub container_titles: Vec<String>,
    #[serde(default)]
    pub post_body_titles: Vec<String>,
    #[serde(default)]
    pub back_matter_titles: Vec<String>,
    #[serde(default = "default_true")]
    pub chapter_title_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub chapter_section_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub toc_semantic_contract_ok: bool,
    #[serde(default)]
    pub toc_semantic_blocking_reasons: Vec<String>,
    #[serde(default)]
    pub note_region_summary: Value,
    #[serde(default)]
    pub note_item_summary: Value,
    #[serde(default)]
    pub chapter_note_mode_summary: Value,
    #[serde(default = "default_true")]
    pub chapter_endnote_region_alignment_ok: bool,
    #[serde(default)]
    pub chapter_endnote_start_page_map: HashMap<String, i64>,
    #[serde(default)]
    pub body_anchor_summary: Value,
    #[serde(default)]
    pub note_link_summary: Value,
    #[serde(default)]
    pub review_seed_summary: Value,
    #[serde(default)]
    pub review_type_counts: HashMap<String, i64>,
    #[serde(default)]
    pub override_summary: Value,
    #[serde(default)]
    pub review_flags: Vec<String>,
    #[serde(default)]
    pub unit_planning_summary: Value,
    #[serde(default)]
    pub ref_materialization_summary: Value,
    #[serde(default)]
    pub diagnostic_page_summary: Value,
    #[serde(default)]
    pub diagnostic_note_summary: Value,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase5Structure {
    #[serde(default)]
    pub pages: Vec<PagePartitionRecord>,
    #[serde(default)]
    pub heading_candidates: Vec<HeadingCandidate>,
    #[serde(default)]
    pub chapters: Vec<ChapterRecord>,
    #[serde(default)]
    pub section_heads: Vec<SectionHeadRecord>,
    #[serde(default)]
    pub note_regions: Vec<NoteRegionRecord>,
    #[serde(default)]
    pub note_items: Vec<NoteItemRecord>,
    #[serde(default)]
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    #[serde(default)]
    pub body_anchors: Vec<BodyAnchorRecord>,
    #[serde(default)]
    pub note_links: Vec<NoteLinkRecord>,
    #[serde(default)]
    pub effective_note_links: Vec<NoteLinkRecord>,
    #[serde(default)]
    pub structure_reviews: Vec<StructureReviewRecord>,
    #[serde(default)]
    pub translation_units: Vec<TranslationUnitRecord>,
    #[serde(default)]
    pub diagnostic_pages: Vec<DiagnosticPageRecord>,
    #[serde(default)]
    pub diagnostic_notes: Vec<DiagnosticNoteRecord>,
    #[serde(default)]
    pub status: StructureStatusRecord,
    #[serde(default)]
    pub summary: Phase5Summary,
}

// ── Phase 6 / Export ────────────────────────────────────────────

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ExportChapterRecord {
    #[serde(default)]
    pub order: i64,
    #[serde(default)]
    pub section_id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub content: String,
    #[serde(default)]
    pub start_page: i64,
    #[serde(default)]
    pub end_page: i64,
    #[serde(default)]
    pub pages: Vec<i64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ExportBundleRecord {
    #[serde(default)]
    pub index_path: String,
    #[serde(default)]
    pub chapters_dir: String,
    #[serde(default)]
    pub chapters: Vec<ExportChapterRecord>,
    #[serde(default)]
    pub chapter_files: HashMap<String, String>,
    #[serde(default)]
    pub files: HashMap<String, String>,
    #[serde(default = "default_true")]
    pub export_semantic_contract_ok: bool,
    #[serde(default)]
    pub front_matter_leak_detected: bool,
    #[serde(default)]
    pub toc_residue_detected: bool,
    #[serde(default)]
    pub mid_paragraph_heading_detected: bool,
    #[serde(default)]
    pub duplicate_paragraph_detected: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ExportAuditFileRecord {
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub page_span: Vec<i64>,
    #[serde(default)]
    pub issue_codes: Vec<String>,
    #[serde(default)]
    pub issue_summary: Vec<String>,
    #[serde(default)]
    pub issue_details: Vec<Value>,
    #[serde(default)]
    pub severity: String,
    #[serde(default)]
    pub sample_opening: String,
    #[serde(default)]
    pub sample_mid: String,
    #[serde(default)]
    pub sample_tail: String,
    #[serde(default)]
    pub footnote_endnote_summary: Value,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ExportAuditReportRecord {
    #[serde(default)]
    pub slug: String,
    #[serde(default)]
    pub doc_id: String,
    #[serde(default)]
    pub zip_path: String,
    #[serde(default = "default_true")]
    pub applicable: bool,
    #[serde(default)]
    pub structure_state: String,
    #[serde(default)]
    pub blocking_reasons: Vec<String>,
    #[serde(default)]
    pub manual_toc_summary: Value,
    #[serde(default)]
    pub toc_role_summary: Value,
    #[serde(default)]
    pub chapter_titles: Vec<String>,
    #[serde(default)]
    pub files: Vec<ExportAuditFileRecord>,
    #[serde(default)]
    pub blocking_issue_count: i64,
    #[serde(default)]
    pub major_issue_count: i64,
    #[serde(default)]
    pub can_ship: bool,
    #[serde(default)]
    pub must_fix_before_next_book: Vec<Value>,
    #[serde(default)]
    pub recommended_followups: Vec<Value>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase6Summary {
    #[serde(default)]
    pub page_partition_summary: Value,
    #[serde(default)]
    pub heading_review_summary: Value,
    #[serde(default)]
    pub heading_graph_summary: Value,
    #[serde(default)]
    pub chapter_source_summary: Value,
    #[serde(default)]
    pub visual_toc_conflict_count: i64,
    #[serde(default)]
    pub toc_alignment_summary: Value,
    #[serde(default)]
    pub toc_semantic_summary: Value,
    #[serde(default)]
    pub toc_role_summary: Value,
    #[serde(default)]
    pub container_titles: Vec<String>,
    #[serde(default)]
    pub post_body_titles: Vec<String>,
    #[serde(default)]
    pub back_matter_titles: Vec<String>,
    #[serde(default = "default_true")]
    pub chapter_title_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub chapter_section_alignment_ok: bool,
    #[serde(default = "default_true")]
    pub toc_semantic_contract_ok: bool,
    #[serde(default)]
    pub toc_semantic_blocking_reasons: Vec<String>,
    #[serde(default)]
    pub note_region_summary: Value,
    #[serde(default)]
    pub note_item_summary: Value,
    #[serde(default)]
    pub chapter_note_mode_summary: Value,
    #[serde(default = "default_true")]
    pub chapter_endnote_region_alignment_ok: bool,
    #[serde(default)]
    pub chapter_endnote_start_page_map: HashMap<String, i64>,
    #[serde(default)]
    pub body_anchor_summary: Value,
    #[serde(default)]
    pub note_link_summary: Value,
    #[serde(default)]
    pub review_seed_summary: Value,
    #[serde(default)]
    pub review_type_counts: HashMap<String, i64>,
    #[serde(default)]
    pub override_summary: Value,
    #[serde(default)]
    pub review_flags: Vec<String>,
    #[serde(default)]
    pub unit_planning_summary: Value,
    #[serde(default)]
    pub ref_materialization_summary: Value,
    #[serde(default)]
    pub diagnostic_page_summary: Value,
    #[serde(default)]
    pub diagnostic_note_summary: Value,
    #[serde(default)]
    pub export_bundle_summary: Value,
    #[serde(default)]
    pub export_audit_summary: Value,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Phase6Structure {
    #[serde(default)]
    pub pages: Vec<PagePartitionRecord>,
    #[serde(default)]
    pub heading_candidates: Vec<HeadingCandidate>,
    #[serde(default)]
    pub chapters: Vec<ChapterRecord>,
    #[serde(default)]
    pub section_heads: Vec<SectionHeadRecord>,
    #[serde(default)]
    pub note_regions: Vec<NoteRegionRecord>,
    #[serde(default)]
    pub note_items: Vec<NoteItemRecord>,
    #[serde(default)]
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    #[serde(default)]
    pub body_anchors: Vec<BodyAnchorRecord>,
    #[serde(default)]
    pub note_links: Vec<NoteLinkRecord>,
    #[serde(default)]
    pub effective_note_links: Vec<NoteLinkRecord>,
    #[serde(default)]
    pub structure_reviews: Vec<StructureReviewRecord>,
    #[serde(default)]
    pub translation_units: Vec<TranslationUnitRecord>,
    #[serde(default)]
    pub diagnostic_pages: Vec<DiagnosticPageRecord>,
    #[serde(default)]
    pub diagnostic_notes: Vec<DiagnosticNoteRecord>,
    #[serde(default)]
    pub export_chapters: Vec<ExportChapterRecord>,
    #[serde(default)]
    pub export_bundle: ExportBundleRecord,
    #[serde(default)]
    pub export_audit: ExportAuditReportRecord,
    #[serde(default)]
    pub status: StructureStatusRecord,
    #[serde(default)]
    pub summary: Phase6Summary,
}

// ── 辅助函数 ────────────────────────────────────────────────────

fn default_true() -> bool {
    true
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chapter_record_roundtrip() {
        let ch = ChapterRecord {
            chapter_id: "toc-ch-1".into(),
            title: "Chapter One".into(),
            start_page: 10,
            end_page: 20,
            pages: (10..=20).collect(),
            source: ChapterSource::VisualToc,
            boundary_state: BoundaryState::Ready,
        };
        let json = serde_json::to_string(&ch).unwrap();
        let back: ChapterRecord = serde_json::from_str(&json).unwrap();
        assert_eq!(back.chapter_id, ch.chapter_id);
        assert_eq!(back.title, ch.title);
        assert_eq!(back.source, ch.source);
        assert_eq!(back.pages.len(), 11);
    }

    #[test]
    fn note_item_record_uses_note_kind_enum() {
        let item = NoteItemRecord {
            note_item_id: "ni-1".into(),
            region_id: "r-1".into(),
            chapter_id: "ch-1".into(),
            page_no: 5,
            marker: "1".into(),
            marker_type: "num".into(),
            text: "Some note".into(),
            source: "note_scan".into(),
            source_page_label: "5".into(),
            is_reconstructed: false,
            review_required: false,
            note_kind: NoteKind::Footnote,
            projection_mode: None,
            owner_chapter_id: None,
            source_marker: None,
            normalized_marker: None,
        };
        let json = serde_json::to_string(&item).unwrap();
        assert!(json.contains("\"footnote\""));
        let back: NoteItemRecord = serde_json::from_str(&json).unwrap();
        assert_eq!(back.note_kind, NoteKind::Footnote);
    }

    #[test]
    fn pipeline_identity_default() {
        let id = PipelineIdentity::default();
        assert!(id.run_id.is_empty());
        assert_eq!(id.max_body_chars, 0);
    }

    #[test]
    fn phase2_structure_default() {
        let s = Phase2Structure::default();
        assert!(s.pages.is_empty());
        assert!(s.chapters.is_empty());
        assert!(s.note_items.is_empty());
    }

    #[test]
    fn diagnostic_entry_underscore_fields_serialize_correctly() {
        let entry = DiagnosticEntryRecord {
            _start_bp: 42,
            _end_bp: 99,
            ..Default::default()
        };
        let json = serde_json::to_string(&entry).unwrap();
        assert!(json.contains("\"_startBP\""));
        assert!(json.contains("\"_endBP\""));
        let back: DiagnosticEntryRecord = serde_json::from_str(&json).unwrap();
        assert_eq!(back._start_bp, 42);
        assert_eq!(back._end_bp, 99);
    }

    #[test]
    fn export_audit_report_serde_default() {
        // serde default (from JSON {}) matches Python constructor
        let report: ExportAuditReportRecord = serde_json::from_str("{}").unwrap();
        assert!(report.applicable);
        assert_eq!(report.structure_state, "");
        assert!(!report.can_ship);
    }
}

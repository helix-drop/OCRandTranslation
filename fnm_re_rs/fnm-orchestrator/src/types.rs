//! Orchestrator 配置 + 快照类型。
//!
//! ←→ Python `FNM_RE/app/pipeline.py::ModulePipelineSnapshot`

use fnm_core::records::{
    BodyAnchorRecord, ChapterMarkdownSet, ChapterNoteModeRecord, ChapterRecord,
    ExportAuditReportRecord, ExportBundleRecord, FrozenRefEntry, FrozenUnits, HeadingCandidate,
    NoteItemRecord, NoteLinkRecord, NoteRegionRecord, PagePartitionRecord, Phase1Structure,
    Phase2Structure, Phase3Structure, SectionHeadRecord, StructureReviewRecord,
    TranslationUnitRecord,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Pipeline 启动阶段。
///
/// 当前仅支持 `Toc`（完整运行）。未来可扩展续跑能力。
///
/// ←→ Python `build_module_pipeline_snapshot(start_phase=...)`
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum StartPhase {
    /// 完整运行（默认）
    #[default]
    Toc,
}

impl std::str::FromStr for StartPhase {
    type Err = crate::error::OrchestratorError;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "toc" | "" => Ok(Self::Toc),
            other => Err(crate::error::OrchestratorError::InvalidStartPhase(
                other.into(),
            )),
        }
    }
}

/// Pipeline 全局配置。
///
/// ←→ Python `build_module_pipeline_snapshot(**kwargs)`
#[derive(Debug, Clone, Default)]
pub struct PipelineConfig {
    pub doc_id: String,
    pub slug: String,
    pub pdf_path: String,
    pub toc_offset: i64,
    pub max_body_chars: i64,
    pub include_diagnostic_entries: bool,
    pub manual_toc_ready: bool,
    pub pipeline_state: String,
    /// 启动阶段
    pub start_phase: StartPhase,
    /// review_overrides 原始 JSON（由 caller 分组后透传给各 phase）。
    /// ←→ Python `_group_review_overrides(review_overrides)`
    pub review_overrides: Option<Value>,
    /// visual_toc_bundle（含 items + endnotes_summary 等）。
    /// ←→ Python `pipeline.py:visual_toc_bundle`
    pub visual_toc_bundle: Option<Value>,
    /// 跳过 superscript recovery（默认 true）。
    pub skip_sup_recovery: bool,
    /// 跳过 LLM verify（默认 true）。
    pub skip_llm_verify: bool,
}

/// Phase 1 输出快照（DB 持久化前的内存形态）。
#[derive(Debug, Clone)]
pub struct Phase1Snapshot {
    pub structure: Phase1Structure,
    pub diagnostics: Value,
}

/// Phase 2 输出快照。
#[derive(Debug, Clone)]
pub struct Phase2Snapshot {
    pub structure: Phase2Structure,
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    pub note_regions: Vec<NoteRegionRecord>,
    pub note_items: Vec<NoteItemRecord>,
    pub diagnostics: Value,
}

/// Phase 3 输出快照。
#[derive(Debug, Clone)]
pub struct Phase3Snapshot {
    pub structure: Phase3Structure,
    pub note_link_table: fnm_phase3::note_linking::NoteLinkTable,
    pub body_anchors: Vec<BodyAnchorRecord>,
    pub note_links: Vec<NoteLinkRecord>,
    pub diagnostics: Value,
}

/// Phase 4 输出快照。
#[derive(Debug, Clone)]
pub struct Phase4Snapshot {
    pub frozen_units: FrozenUnits,
    pub frozen_refs: Vec<FrozenRefEntry>,
    pub translation_units: Vec<TranslationUnitRecord>,
    pub structure_reviews: Vec<StructureReviewRecord>,
    pub summary: Value,
    pub diagnostics: Value,
}

/// Phase 5 输出快照。
#[derive(Debug, Clone)]
pub struct Phase5Snapshot {
    pub chapter_markdowns: ChapterMarkdownSet,
}

/// Phase 6 输出快照。
#[derive(Debug, Clone)]
pub struct Phase6Snapshot {
    pub export_bundle: ExportBundleRecord,
    pub export_zip: Vec<u8>,
    pub export_audit: ExportAuditReportRecord,
    pub diagnostics: Value,
}

/// 模块管道完整快照（全 phase 产物聚合）。
///
/// ←→ Python `ModulePipelineSnapshot`
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ModulePipelineSnapshot {
    pub doc_id: String,
    pub slug: String,
    pub pipeline_run_id: String,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub phase1: Option<SerPhase1>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phase2: Option<SerPhase2>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phase3: Option<SerPhase3>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phase4: Option<SerPhase4>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phase5: Option<SerPhase5>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phase6: Option<SerPhase6>,

    /// 整本书的元数据：phase 完成状态、计时、运行日志。
    #[serde(default)]
    pub run_meta: Value,
}

/// Phase 1 序列化体（DB 持久化用）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerPhase1 {
    pub pages: Vec<PagePartitionRecord>,
    pub chapters: Vec<ChapterRecord>,
    pub heading_candidates: Vec<HeadingCandidate>,
    pub section_heads: Vec<SectionHeadRecord>,
}

/// Phase 2 序列化体。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerPhase2 {
    pub note_regions: Vec<NoteRegionRecord>,
    pub note_items: Vec<NoteItemRecord>,
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
}

/// Phase 3 序列化体。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerPhase3 {
    pub body_anchors: Vec<BodyAnchorRecord>,
    pub note_links: Vec<NoteLinkRecord>,
}

/// Phase 4 序列化体。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerPhase4 {
    pub translation_units: Vec<TranslationUnitRecord>,
    pub structure_reviews: Vec<StructureReviewRecord>,
}

/// Phase 5 序列化体。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerPhase5 {
    pub chapter_count: i64,
    pub merge_summary: Value,
}

/// Phase 6 序列化体。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerPhase6 {
    pub export_bundle: ExportBundleRecord,
    pub export_audit: ExportAuditReportRecord,
}

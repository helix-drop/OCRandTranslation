//! Phase 4 输入类型契约。
//!
//! 消费 Phase 1/2/3 的输出产物。

use fnm_core::records::{
    BodyAnchorRecord, ChapterRecord, NoteLinkRecord, NoteRegionRecord, PagePartitionRecord,
    Phase3Summary,
};
use fnm_phase1::input::RawPage;
use fnm_phase2::chapter_split::ChapterLayers;
use fnm_phase3::note_linking::NoteLinkTable;

/// Phase 4 完整输入。
pub struct Phase4Input<'a> {
    // ── ref_freeze 依赖 ──
    pub chapter_layers: &'a ChapterLayers,
    pub note_link_table: &'a NoteLinkTable,

    // ── units 依赖 ──
    pub raw_pages: &'a [RawPage],
    pub page_partitions: &'a [PagePartitionRecord],

    // ── reviews 依赖 ──
    pub chapters: &'a [ChapterRecord],
    pub body_anchors: &'a [BodyAnchorRecord],
    pub effective_note_links: &'a [NoteLinkRecord],
    pub note_regions: &'a [NoteRegionRecord],
    pub summary: &'a Phase3Summary,

    // ── 配置 ──
    pub max_body_chars: i64,
    pub pipeline_run_id: String,
    pub ignored_link_override_count: usize,
    pub invalid_override_count: usize,
}

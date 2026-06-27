//! Phase 3 输入类型契约。
//!
//! ←→ Python: FNM_RE/models.py Phase3 相关 dataclass（输入侧）

use fnm_core::records::{
    ChapterNoteModeRecord, ChapterRecord, HeadingCandidate, NoteItemRecord, NoteRegionRecord,
    PagePartitionRecord, SectionHeadRecord,
};
use fnm_phase1::input::RawPage;
use serde_json::Value;

/// Phase 3 的完整输入。
///
/// 所有上游数据均从 DB 读取（Phase 1 + Phase 2 产物），不直接在内存接收 Phase2Structure。
/// Phase1/2 facts（heading_candidates / section_heads）透传至输出以保持 byte-equal。
pub struct Phase3Input<'a> {
    pub phase1_chapters: &'a [ChapterRecord],
    pub phase1_pages: &'a [PagePartitionRecord],
    pub phase1_heading_candidates: &'a [HeadingCandidate],
    pub phase1_section_heads: &'a [SectionHeadRecord],
    pub phase2_note_regions: &'a [NoteRegionRecord],
    pub phase2_note_items: &'a [NoteItemRecord],
    /// Phase2 权威的 chapter_note_modes。Phase3 必须透传此字段（铁律 §1：Phase N 只能消费
    /// Phase N-1 的事实，不能重建或覆盖上游事实）。
    pub phase2_chapter_note_modes: &'a [ChapterNoteModeRecord],
    pub raw_pages: &'a [RawPage],
    pub pdf_path: Option<&'a str>,
    pub config: Phase3Config,
    /// ←→ Python `build_note_link_table(overrides=...)`（行 1434）
    /// review overrides，用于覆盖 note_item / anchor / link 的默认行为。
    /// 借用形式：避免 caller-side clone（AGENTS.md §11）。
    pub overrides: Option<&'a Value>,
}

pub struct Phase3Config {
    pub skip_llm_verify: bool,
}

impl Default for Phase3Config {
    fn default() -> Self {
        Self {
            skip_llm_verify: true,
        }
    }
}

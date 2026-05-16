//! Phase 3 输入类型契约。
//!
//! ←→ Python: FNM_RE/models.py Phase3 相关 dataclass（输入侧）

use fnm_core::records::{NoteItemRecord, NoteRegionRecord, PagePartitionRecord};
use fnm_phase1::input::RawPage;
use serde_json::Value;

/// Phase 3 的完整输入。
///
/// 所有上游数据均从 DB 读取（Phase 1 + Phase 2 产物），不直接在内存接收 Phase2Structure。
///
/// 注：原有 `phase2_chapter_note_modes` 字段已删除——`build_phase3_structure`
/// 内部 `phase2_rebuild::phase2_from_chapter_layers` 会从 chapter_layers 重新
/// 生成 chapter_note_modes（包含 mode_override_reason 等审计字段），caller 传
/// chapter_note_modes 是冗余且会被丢弃的死参（AGENTS.md §8）。
pub struct Phase3Input<'a> {
    pub phase1_chapters: &'a [fnm_core::records::ChapterRecord],
    pub phase1_pages: &'a [PagePartitionRecord],
    pub phase2_note_regions: &'a [NoteRegionRecord],
    pub phase2_note_items: &'a [NoteItemRecord],
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

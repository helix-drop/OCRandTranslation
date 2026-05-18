//! Phase 4 输入类型契约。
//!
//! 消费 Phase 1/2/3 的输出产物。
//!
//! 待实现：M1.1 任务

use fnm_phase2::chapter_split::ChapterLayers;
use fnm_phase3::note_linking::NoteLinkTable;

/// ←→ Python `ref_freeze.build_frozen_units` 的参数集合
pub struct Phase4Input<'a> {
    pub chapter_layers: &'a ChapterLayers,
    pub note_link_table: &'a NoteLinkTable,
    pub max_body_chars: i64,
    pub pipeline_run_id: String,
}

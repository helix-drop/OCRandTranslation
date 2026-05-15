//! Phase 2 输出类型。

use fnm_core::records::{ChapterNoteModeRecord, ChapterRecord, NoteItemRecord, NoteRegionRecord};

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Phase2Output {
    pub chapters: Vec<ChapterRecord>,
    pub note_regions: Vec<NoteRegionRecord>,
    pub note_items: Vec<NoteItemRecord>,
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    pub book_type: String,
    pub diagnostics: serde_json::Value,
}

//! Gate 校验。←→ Python `_note_capture_summary()` / `_chapter_binding_summary()`。

use super::ChapterLayer;
use fnm_core::records::ChapterNoteModeRecord;

/// 构建 gate report。
pub fn build_gate_report(
    chapter_layers: &[ChapterLayer],
    _chapter_note_modes: &[ChapterNoteModeRecord],
) -> serde_json::Value {
    let total_chapters = chapter_layers.len();
    let chapters_with_notes = chapter_layers
        .iter()
        .filter(|cl| cl.note_mode != fnm_core::types::NoteMode::NoNotes)
        .count();
    let chapters_with_footnote = chapter_layers
        .iter()
        .filter(|cl| cl.note_mode == fnm_core::types::NoteMode::FootnotePrimary)
        .count();
    let chapters_with_endnote = chapter_layers
        .iter()
        .filter(|cl| cl.note_mode == fnm_core::types::NoteMode::ChapterEndnotePrimary)
        .count();
    let chapters_review_required = chapter_layers
        .iter()
        .filter(|cl| cl.note_mode == fnm_core::types::NoteMode::ReviewRequired)
        .count();

    let total_footnote_items: usize = chapter_layers
        .iter()
        .map(|cl| cl.footnote_items.len())
        .sum();
    let total_endnote_items: usize = chapter_layers.iter().map(|cl| cl.endnote_items.len()).sum();
    let total_endnote_regions: usize = chapter_layers
        .iter()
        .map(|cl| cl.endnote_regions.len())
        .sum();

    let chapters_without_body: Vec<String> = chapter_layers
        .iter()
        .filter(|cl| cl.body_pages.is_empty())
        .map(|cl| cl.chapter_id.clone())
        .collect();

    let empty_endnote_regions: Vec<String> = chapter_layers
        .iter()
        .filter(|cl| {
            cl.note_mode == fnm_core::types::NoteMode::ChapterEndnotePrimary
                && cl.endnote_items.is_empty()
        })
        .map(|cl| cl.chapter_id.clone())
        .collect();

    serde_json::json!({
        "total_chapters": total_chapters,
        "chapters_with_notes": chapters_with_notes,
        "chapters_with_footnote": chapters_with_footnote,
        "chapters_with_endnote": chapters_with_endnote,
        "chapters_review_required": chapters_review_required,
        "total_footnote_items": total_footnote_items,
        "total_endnote_items": total_endnote_items,
        "total_endnote_regions": total_endnote_regions,
        "chapters_without_body": chapters_without_body,
        "empty_endnote_regions": empty_endnote_regions,
        "chapters_without_body_count": chapters_without_body.len(),
        "empty_endnote_regions_count": empty_endnote_regions.len(),
    })
}

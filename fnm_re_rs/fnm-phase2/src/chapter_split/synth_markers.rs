//! footnote_only 书的 marker 合成。←→ Python `_synthesize_footnote_only_markers()`。

use fnm_core::records::NoteItemRecord;

/// 给每章的 footnote items 生成顺序 synth_marker（1,2,3...）。
/// 用于 footnote_only 书型，确保 footnote 有连续编号。
/// 注意：此函数不修改 NoteItemRecord（无 normalized_marker 字段），
/// 而是返回 (item_index, synth_marker) 映射。
pub fn compute_synthetic_markers(chapter_layers: &[super::ChapterLayer]) -> Vec<(usize, String)> {
    let mut result = Vec::new();
    let mut offset = 0usize;
    for chapter in chapter_layers {
        if chapter.note_mode != fnm_core::types::NoteMode::FootnotePrimary {
            offset += chapter.footnote_items.len();
            continue;
        }
        let mut items: Vec<(usize, &NoteItemRecord)> =
            chapter.footnote_items.iter().enumerate().collect();
        items.sort_by_key(|(_, i)| (i.page_no, i.marker.clone()));

        for (local_idx, (_, item)) in items.iter().enumerate() {
            let synth_marker = format!("{}", local_idx + 1);
            if item.marker.is_empty() || item.marker == "*" || item.marker == "**" {
                result.push((offset + local_idx, synth_marker));
            }
        }
        offset += chapter.footnote_items.len();
    }
    result
}

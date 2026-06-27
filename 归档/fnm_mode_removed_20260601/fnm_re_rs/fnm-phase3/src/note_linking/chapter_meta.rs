//! ←→ Python `note_linking.py:_build_note_item_meta_by_id / _build_book_endnote_stream_summary`

use fnm_core::records::NoteItemRecord;
use fnm_phase2::chapter_split::ChapterLayer;
use std::collections::HashMap;

/// 单条 note_item 的元数据。
#[derive(Debug, Clone, Default)]
pub struct NoteItemMeta {
    pub projection_mode: String,
    pub owner_chapter_id: String,
    pub source_marker: String,
    pub normalized_marker: String,
}

/// 构建 note_item_id -> 元数据映射。
///
/// ←→ Python `_build_note_item_meta_by_id`
pub fn build_note_item_meta_by_id(note_items: &[NoteItemRecord]) -> HashMap<String, NoteItemMeta> {
    let mut meta: HashMap<String, NoteItemMeta> = HashMap::new();
    for row in note_items {
        let note_item_id = row.note_item_id.trim();
        if note_item_id.is_empty() {
            continue;
        }
        meta.insert(
            note_item_id.to_string(),
            NoteItemMeta {
                projection_mode: row
                    .projection_mode
                    .as_ref()
                    .map_or("unknown", |s| s.trim())
                    .to_string(),
                owner_chapter_id: row
                    .owner_chapter_id
                    .as_ref()
                    .map_or("", |s| s.trim())
                    .to_string(),
                source_marker: row
                    .source_marker
                    .as_ref()
                    .map_or("", |s| s.trim())
                    .to_string(),
                normalized_marker: row
                    .normalized_marker
                    .as_ref()
                    .map_or("", |s| s.trim())
                    .to_string(),
            },
        );
    }
    meta
}

/// 单章尾注流统计。
#[derive(Debug, Clone, Default)]
pub struct EndnoteStreamChapter {
    pub chapter_id: String,
    pub item_count: usize,
    pub projection_mode_counts: HashMap<String, usize>,
}

/// 全书尾注流汇总。
#[derive(Debug, Clone, Default)]
pub struct BookEndnoteStreamSummary {
    pub chapter_count: usize,
    pub chapters_with_endnote_stream: Vec<String>,
    pub high_concentration_chapter_ids: Vec<String>,
    pub chapters: Vec<EndnoteStreamChapter>,
}

/// 汇总全书中所有存在尾注条目的章节。
///
/// ←→ Python `_build_book_endnote_stream_summary`
pub fn build_book_endnote_stream_summary(
    chapter_layers: &[ChapterLayer],
) -> BookEndnoteStreamSummary {
    let mut chapters: Vec<EndnoteStreamChapter> = Vec::new();
    let mut chapter_ids: Vec<String> = Vec::new();
    let mut concentrated: Vec<String> = Vec::new();

    for chapter in chapter_layers {
        let chapter_id = chapter.chapter_id.trim();
        if chapter_id.is_empty() {
            continue;
        }
        let endnote_items = &chapter.endnote_items;
        if endnote_items.is_empty() {
            continue;
        }

        chapter_ids.push(chapter_id.to_string());

        let mut mode_counts: HashMap<String, usize> = HashMap::new();
        for item in endnote_items {
            let mode = item
                .projection_mode
                .as_ref()
                .map_or("unknown", |s| s.trim());
            *mode_counts.entry(mode.to_string()).or_insert(0) += 1;
        }

        if endnote_items.len() >= 100 {
            concentrated.push(chapter_id.to_string());
        }

        chapters.push(EndnoteStreamChapter {
            chapter_id: chapter_id.to_string(),
            item_count: endnote_items.len(),
            projection_mode_counts: mode_counts,
        });
    }

    // 只保留前 32 章
    chapters.truncate(32);

    BookEndnoteStreamSummary {
        chapter_count: chapter_ids.len(),
        chapters_with_endnote_stream: chapter_ids,
        high_concentration_chapter_ids: concentrated,
        chapters,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::NoteKind;

    #[test]
    fn test_build_note_item_meta_by_id() {
        let items = vec![
            NoteItemRecord {
                note_item_id: "fn-1".to_string(),
                projection_mode: Some("page_tail".to_string()),
                owner_chapter_id: Some("ch-1".to_string()),
                source_marker: Some("1".to_string()),
                normalized_marker: Some("1".to_string()),
                ..Default::default()
            },
            NoteItemRecord {
                note_item_id: "en-1".to_string(),
                projection_mode: None,
                ..Default::default()
            },
        ];

        let meta = build_note_item_meta_by_id(&items);
        let m1 = meta.get("fn-1").unwrap();
        assert_eq!(m1.projection_mode, "page_tail");
        assert_eq!(m1.owner_chapter_id, "ch-1");

        let m2 = meta.get("en-1").unwrap();
        assert_eq!(m2.projection_mode, "unknown");
    }

    #[test]
    fn test_build_book_endnote_stream_summary() {
        let layers = vec![
            ChapterLayer {
                chapter_id: "ch-1".to_string(),
                endnote_items: vec![NoteItemRecord {
                    note_item_id: "en-1".to_string(),
                    projection_mode: Some("chapter".to_string()),
                    note_kind: NoteKind::Endnote,
                    ..Default::default()
                }],
                ..Default::default()
            },
            ChapterLayer {
                chapter_id: "ch-2".to_string(),
                endnote_items: vec![],
                ..Default::default()
            },
        ];

        let summary = build_book_endnote_stream_summary(&layers);
        assert_eq!(summary.chapter_count, 1);
        assert_eq!(summary.chapters_with_endnote_stream, vec!["ch-1"]);
        assert!(summary.high_concentration_chapter_ids.is_empty());
    }
}

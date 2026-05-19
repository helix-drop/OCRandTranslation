//! ←→ Python `FNM_RE/stages/units.py`（L386-398）
//!
//! endnote 区起始页映射。

use fnm_core::records::NoteRegionRecord;
use fnm_core::types::NoteKind;
use std::collections::HashMap;

/// ←→ Python `_chapter_endnote_start_page_map` (units.py:386-398)
///
/// 构建 chapter_id → endnote 区起始页 的映射。
/// 只考虑 note_kind == "endnote" 的 region，取每个 chapter 的最小 page_start。
pub fn chapter_endnote_start_page_map(note_regions: &[NoteRegionRecord]) -> HashMap<String, i64> {
    let mut start_page_by_chapter: HashMap<String, i64> = HashMap::new();
    for region in note_regions {
        if region.note_kind != NoteKind::Endnote {
            continue;
        }
        let chapter_id = region.chapter_id.trim().to_string();
        let start_page = region.page_start;
        if chapter_id.is_empty() || start_page <= 0 {
            continue;
        }
        let existing = start_page_by_chapter.get(&chapter_id).copied().unwrap_or(0);
        if existing <= 0 || start_page < existing {
            start_page_by_chapter.insert(chapter_id, start_page);
        }
    }
    start_page_by_chapter
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{RegionScope, RegionSource};

    fn make_region(chapter_id: &str, note_kind: NoteKind, page_start: i64) -> NoteRegionRecord {
        NoteRegionRecord {
            region_id: format!("{}-region-{}", chapter_id, page_start),
            chapter_id: chapter_id.to_string(),
            page_start,
            page_end: page_start + 1,
            pages: vec![page_start],
            note_kind,
            scope: RegionScope::Chapter,
            source: RegionSource::HeadingScan,
            heading_text: String::new(),
            start_reason: String::new(),
            end_reason: String::new(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: String::new(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        }
    }

    #[test]
    fn test_chapter_endnote_start_page_map_basic() {
        let regions = vec![
            make_region("ch1", NoteKind::Endnote, 100),
            make_region("ch1", NoteKind::Endnote, 105),
            make_region("ch2", NoteKind::Endnote, 200),
            make_region("ch1", NoteKind::Footnote, 50), // 应被忽略
        ];
        let result = chapter_endnote_start_page_map(&regions);
        assert_eq!(result.len(), 2);
        assert_eq!(result.get("ch1"), Some(&100));
        assert_eq!(result.get("ch2"), Some(&200));
    }

    #[test]
    fn test_chapter_endnote_start_page_map_empty() {
        let regions = vec![];
        let result = chapter_endnote_start_page_map(&regions);
        assert!(result.is_empty());
    }

    #[test]
    fn test_chapter_endnote_start_page_map_no_endnotes() {
        let regions = vec![make_region("ch1", NoteKind::Footnote, 50)];
        let result = chapter_endnote_start_page_map(&regions);
        assert!(result.is_empty());
    }
}

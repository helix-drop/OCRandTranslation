//! ←→ FNM_RE/modules/chapter_merge.py
//! 翻译的 11 个转换函数：
//!   chapter_pages_from_layer   ←→ _chapter_pages_from_layer (chapter_merge.py:53)
//!   to_chapter_records          ←→ _to_chapter_records (chapter_merge.py:56)
//!   to_note_item_records        ←→ _to_note_item_records (chapter_merge.py:78)
//!   to_body_anchor_records      ←→ _to_body_anchor_records (chapter_merge.py:98)
//!   to_note_link_records        ←→ _to_note_link_records (chapter_merge.py:120)
//!   to_page_segments            ←→ _to_page_segments (chapter_merge.py:140)
//!   to_translation_unit_records ←→ _to_translation_unit_records (chapter_merge.py:180)
//!   effective_note_mode_from_layer ←→ _effective_note_mode_from_layer (chapter_merge.py:210)
//!   phase5_book_type            ←→ _phase5_book_type (chapter_merge.py:241)
//!   to_diagnostic_pages         ←→ _to_diagnostic_pages (chapter_merge.py:253)

use fnm_core::records::{
    BodyAnchorRecord, ChapterRecord, DiagnosticEntryRecord, DiagnosticPageRecord, NoteItemRecord,
    NoteLinkRecord, TranslationUnitRecord, UnitPageSegmentRecord, UnitParagraphRecord,
};
use fnm_core::types::ChapterSource;
use fnm_phase2::chapter_split::{ChapterLayer, ChapterLayers};
use fnm_phase3::note_linking::NoteLinkTable;
use serde_json::Value;
use std::collections::HashSet;

/// 从 ChapterLayer 收集章节边界页码（仅正文页）。
///
/// 不包含 note/endnote items 或 region 页 — 章节边界由 Phase1 权威决定，
/// Phase5 不应从注释区域扩写边界。
///
/// ←→ Python `_chapter_pages_from_layer()` (chapter_merge.py:53)
pub fn chapter_pages_from_layer(chapter: &ChapterLayer) -> Vec<i64> {
    let mut pages: HashSet<i64> = HashSet::new();
    for row in &chapter.body_pages {
        if row.page_no > 0 {
            pages.insert(row.page_no);
        }
    }
    let mut result: Vec<i64> = pages.into_iter().collect();
    result.sort();
    result
}

/// 从 ChapterLayers 转换为 ChapterRecord 列表。
///
/// ←→ Python `_to_chapter_records()` (chapter_merge.py:56)
pub fn to_chapter_records(chapter_layers: &ChapterLayers) -> Vec<ChapterRecord> {
    chapter_layers
        .chapter_layers
        .iter()
        .filter(|layer| !layer.chapter_id.trim().is_empty())
        .map(|layer| {
            let pages = chapter_pages_from_layer(layer);
            let start_page = pages.first().copied().unwrap_or(0);
            let end_page = pages.last().copied().unwrap_or(start_page);
            ChapterRecord {
                chapter_id: layer.chapter_id.clone(),
                title: if layer.title.trim().is_empty() {
                    layer.chapter_id.clone()
                } else {
                    layer.title.clone()
                },
                start_page,
                end_page,
                pages,
                source: ChapterSource::Fallback,
                boundary_state: fnm_core::types::BoundaryState::Ready,
            }
        })
        .collect()
}

/// 从 ChapterLayers 转换为 NoteItemRecord 列表。
///
/// ←→ Python `_to_note_item_records()` (chapter_merge.py:78)
pub fn to_note_item_records(chapter_layers: &ChapterLayers) -> Vec<NoteItemRecord> {
    chapter_layers
        .note_items
        .iter()
        .filter(|row| !row.note_item_id.trim().is_empty())
        .cloned()
        .collect()
}

/// 从 NoteLinkTable 转换为 BodyAnchorRecord 列表。
///
/// ←→ Python `_to_body_anchor_records()` (chapter_merge.py:98)
pub fn to_body_anchor_records(note_link_table: &NoteLinkTable) -> Vec<BodyAnchorRecord> {
    note_link_table
        .anchors
        .iter()
        .filter(|row| !row.anchor_id.trim().is_empty())
        .cloned()
        .collect()
}

/// 从 NoteLinkTable 转换为 NoteLinkRecord 列表（仅 effective_links）。
///
/// ←→ Python `_to_note_link_records()` (chapter_merge.py:120)
pub fn to_note_link_records(note_link_table: &NoteLinkTable) -> Vec<NoteLinkRecord> {
    note_link_table
        .effective_links
        .iter()
        .filter(|row| !row.link_id.trim().is_empty())
        .cloned()
        .collect()
}

/// 从 FrozenUnit 转换为 UnitPageSegmentRecord 列表。
///
/// ←→ Python `_to_page_segments()` (chapter_merge.py:140)
pub fn to_page_segments(unit: &fnm_core::records::FrozenUnit) -> Vec<UnitPageSegmentRecord> {
    let mut rows: Vec<UnitPageSegmentRecord> = Vec::new();
    for segment in &unit.page_segments {
        let mut paragraphs: Vec<UnitParagraphRecord> = Vec::new();
        for p in &segment.paragraphs {
            paragraphs.push(UnitParagraphRecord {
                order: p.order,
                kind: p.kind.clone(),
                heading_level: p.heading_level,
                source_text: p.source_text.clone(),
                display_text: p.display_text.clone(),
                cross_page: p.cross_page.clone(),
                consumed_by_prev: p.consumed_by_prev,
                section_path: p.section_path.clone(),
                print_page_label: p.print_page_label.clone(),
                translated_text: p.translated_text.clone(),
                translation_status: p.translation_status.clone(),
                attempt_count: p.attempt_count,
                last_error: p.last_error.clone(),
                manual_resolved: p.manual_resolved,
            });
        }
        rows.push(UnitPageSegmentRecord {
            page_no: segment.page_no,
            paragraph_count: segment.paragraph_count,
            source_text: segment.source_text.clone(),
            display_text: segment.display_text.clone(),
            paragraphs,
        });
    }
    rows
}

/// 从 FrozenUnits 转换为 TranslationUnitRecord 列表。
///
/// ←→ Python `_to_translation_unit_records()` (chapter_merge.py:180)
pub fn to_translation_unit_records(
    frozen_units: &fnm_core::records::FrozenUnits,
) -> Vec<TranslationUnitRecord> {
    let mut rows: Vec<TranslationUnitRecord> = Vec::new();
    for unit in frozen_units
        .body_units
        .iter()
        .chain(frozen_units.note_units.iter())
    {
        let page_end = if unit.page_end > 0 {
            unit.page_end
        } else {
            unit.page_start
        };
        rows.push(TranslationUnitRecord {
            unit_id: unit.unit_id.clone(),
            kind: unit.kind.clone(),
            owner_kind: unit.owner_kind.clone(),
            owner_id: unit.owner_id.clone(),
            section_id: unit.section_id.clone(),
            section_title: unit.section_title.clone(),
            section_start_page: unit.section_start_page,
            section_end_page: unit.section_end_page,
            note_id: unit.note_id.clone(),
            page_start: unit.page_start,
            page_end,
            char_count: unit.char_count,
            source_text: unit.source_text.clone(),
            translated_text: unit.translated_text.clone(),
            status: unit.status.clone(),
            error_msg: unit.error_msg.clone(),
            target_ref: unit.target_ref.clone(),
            page_segments: to_page_segments(unit),
            source_hash: unit.source_hash.clone(),
            segment_plan_hash: unit.segment_plan_hash.clone(),
            pipeline_run_id: unit.pipeline_run_id.clone(),
        });
    }
    rows
}

fn safe_int(value: &str) -> i64 {
    value.parse::<i64>().unwrap_or(0)
}

/// 从诊断页面映射转换为 DiagnosticPageRecord 列表。
///
/// ←→ Python `_to_diagnostic_pages()` (chapter_merge.py:253)
pub fn to_diagnostic_pages(
    diagnostic_machine_by_page: &std::collections::HashMap<String, String>,
) -> Vec<DiagnosticPageRecord> {
    let mut pairs: Vec<(i64, &String)> = diagnostic_machine_by_page
        .iter()
        .map(|(k, v)| (safe_int(k), v))
        .filter(|(page_no, content)| *page_no > 0 && !content.trim().is_empty())
        .collect();
    pairs.sort_by_key(|(page_no, _)| *page_no);
    pairs
        .into_iter()
        .map(|(page_no, content)| {
            let content = content.trim().to_string();
            DiagnosticPageRecord {
                _page_bp: page_no,
                _status: "done".to_string(),
                pages: page_no.to_string(),
                _page_entries: vec![DiagnosticEntryRecord {
                    original: String::new(),
                    translation: content.clone(),
                    footnotes: String::new(),
                    footnotes_translation: String::new(),
                    heading_level: 0,
                    pages: page_no.to_string(),
                    _start_bp: page_no,
                    _end_bp: page_no,
                    _print_page_label: page_no.to_string(),
                    _status: "done".to_string(),
                    _error: String::new(),
                    _translation_source: "model".to_string(),
                    _machine_translation: content,
                    _manual_translation: String::new(),
                    _cross_page: Value::Null,
                    ..Default::default()
                }],
                _fnm_source: serde_json::json!({}),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::NoteItemRecord;
    use fnm_core::types::{NoteKind, RegionScope};
    use fnm_phase2::chapter_split::BodyPageLayer;

    fn make_body_layer(page_no: i64) -> BodyPageLayer {
        BodyPageLayer {
            page_no,
            text: format!("Page {}", page_no),
            ..Default::default()
        }
    }

    fn make_note_item(page_no: i64, kind: NoteKind) -> NoteItemRecord {
        NoteItemRecord {
            note_item_id: format!("n{}", page_no),
            page_no,
            note_kind: kind,
            ..Default::default()
        }
    }

    #[test]
    fn test_chapter_pages_from_layer_body_only() {
        let layer = ChapterLayer {
            chapter_id: "ch1".to_string(),
            body_pages: vec![make_body_layer(1), make_body_layer(2), make_body_layer(3)],
            ..Default::default()
        };
        let pages = chapter_pages_from_layer(&layer);
        assert_eq!(pages, vec![1, 2, 3]);
    }

    #[test]
    fn test_chapter_pages_from_layer_excludes_note_pages() {
        let layer = ChapterLayer {
            chapter_id: "ch1".to_string(),
            body_pages: vec![make_body_layer(1), make_body_layer(2)],
            footnote_items: vec![make_note_item(1, NoteKind::Footnote)],
            endnote_items: vec![make_note_item(5, NoteKind::Endnote)],
            endnote_regions: vec![fnm_core::records::NoteRegionRecord {
                region_id: "r1".to_string(),
                chapter_id: String::new(),
                page_start: 100,
                page_end: 150,
                pages: vec![100, 101, 102],
                note_kind: NoteKind::Endnote,
                scope: RegionScope::Book,
                source: fnm_core::types::RegionSource::HeadingScan,
                heading_text: String::new(),
                start_reason: String::new(),
                end_reason: String::new(),
                region_marker_alignment_ok: false,
                region_start_first_source_marker: String::new(),
                region_first_note_item_marker: String::new(),
                review_required: false,
            }],
            ..Default::default()
        };
        let pages = chapter_pages_from_layer(&layer);
        assert_eq!(pages, vec![1, 2]);
    }

    #[test]
    fn test_chapter_pages_from_layer_empty() {
        let layer = ChapterLayer::default();
        assert!(chapter_pages_from_layer(&layer).is_empty());
    }

    #[test]
    fn test_safe_int_valid() {
        assert_eq!(safe_int("42"), 42);
        assert_eq!(safe_int("0"), 0);
        assert_eq!(safe_int("-1"), -1);
    }

    #[test]
    fn test_safe_int_invalid() {
        assert_eq!(safe_int("abc"), 0);
        assert_eq!(safe_int(""), 0);
    }

    #[test]
    fn test_to_diagnostic_pages_empty() {
        let map = std::collections::HashMap::new();
        let result = to_diagnostic_pages(&map);
        assert!(result.is_empty());
    }

    #[test]
    fn test_to_diagnostic_pages_sorted() {
        let mut map = std::collections::HashMap::new();
        map.insert("3".to_string(), "Page 3".to_string());
        map.insert("1".to_string(), "Page 1".to_string());
        map.insert("2".to_string(), "Page 2".to_string());
        let result = to_diagnostic_pages(&map);
        assert_eq!(result.len(), 3);
        assert_eq!(result[0]._page_bp, 1);
        assert_eq!(result[1]._page_bp, 2);
        assert_eq!(result[2]._page_bp, 3);
    }

    #[test]
    fn test_to_diagnostic_pages_skips_invalid() {
        let mut map = std::collections::HashMap::new();
        map.insert("0".to_string(), "Page 0".to_string());
        map.insert("abc".to_string(), "".to_string());
        map.insert("5".to_string(), "".to_string());
        let result = to_diagnostic_pages(&map);
        assert!(result.is_empty());
    }

    #[test]
    fn test_to_chapter_records_empty() {
        let layers = ChapterLayers::default();
        let result = to_chapter_records(&layers);
        assert!(result.is_empty());
    }

    #[test]
    fn test_to_chapter_records_basic() {
        let mut layers = ChapterLayers::default();
        layers.chapter_layers.push(ChapterLayer {
            chapter_id: "ch1".to_string(),
            title: "Chapter 1".to_string(),
            body_pages: vec![make_body_layer(5), make_body_layer(10)],
            ..Default::default()
        });
        let result = to_chapter_records(&layers);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].chapter_id, "ch1");
        assert_eq!(result[0].title, "Chapter 1");
        assert_eq!(result[0].start_page, 5);
        assert_eq!(result[0].end_page, 10);
    }
}

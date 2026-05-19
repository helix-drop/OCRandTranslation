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
//!   to_chapter_note_mode_records ←→ _to_chapter_note_mode_records (chapter_merge.py:222)
//!   phase5_book_type            ←→ _phase5_book_type (chapter_merge.py:241)
//!   to_diagnostic_pages         ←→ _to_diagnostic_pages (chapter_merge.py:253)

use std::str::FromStr;

use fnm_core::records::{
    BodyAnchorRecord, ChapterNoteModeRecord, ChapterRecord, DiagnosticEntryRecord,
    DiagnosticPageRecord, NoteItemRecord, NoteLinkRecord, TranslationUnitRecord,
    UnitPageSegmentRecord, UnitParagraphRecord,
};
use fnm_core::types::{ChapterSource, NoteMode, RegionScope};
use fnm_phase2::chapter_split::{ChapterLayer, ChapterLayers};
use fnm_phase3::note_linking::NoteLinkTable;
use serde_json::Value;
use std::collections::HashSet;

/// 从 ChapterLayer 收集所有页码。
///
/// ←→ Python `_chapter_pages_from_layer()` (chapter_merge.py:53)
pub fn chapter_pages_from_layer(chapter: &ChapterLayer) -> Vec<i64> {
    let mut pages: HashSet<i64> = HashSet::new();
    for row in &chapter.body_pages {
        if row.page_no > 0 {
            pages.insert(row.page_no);
        }
    }
    for row in &chapter.footnote_items {
        if row.page_no > 0 {
            pages.insert(row.page_no);
        }
    }
    for row in &chapter.endnote_items {
        if row.page_no > 0 {
            pages.insert(row.page_no);
        }
    }
    for region in &chapter.endnote_regions {
        for &page_no in &region.pages {
            if page_no > 0 {
                pages.insert(page_no);
            }
        }
        if region.page_start > 0 {
            pages.insert(region.page_start);
        }
        if region.page_end > 0 {
            pages.insert(region.page_end);
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

/// 从 ChapterLayer 推导注释模式。
///
/// ←→ Python `_effective_note_mode_from_layer()` (chapter_merge.py:210)
pub fn effective_note_mode_from_layer(chapter: &ChapterLayer) -> String {
    if !chapter.endnote_items.is_empty() {
        let has_book_scope = chapter
            .endnote_regions
            .iter()
            .any(|r| r.scope == RegionScope::Book);
        if has_book_scope {
            return "book_endnote_bound".to_string();
        }
        return "chapter_endnote_primary".to_string();
    }
    if !chapter.footnote_items.is_empty() {
        return "footnote_primary".to_string();
    }
    "no_notes".to_string()
}

/// 从 ChapterLayers 转换为 ChapterNoteModeRecord 列表。
///
/// ←→ Python `_to_chapter_note_mode_records()` (chapter_merge.py:222)
pub fn to_chapter_note_mode_records(chapter_layers: &ChapterLayers) -> Vec<ChapterNoteModeRecord> {
    chapter_layers
        .chapter_layers
        .iter()
        .map(|layer| {
            let note_mode = effective_note_mode_from_layer(layer);
            let region_ids: Vec<String> = layer
                .endnote_regions
                .iter()
                .filter(|r| !r.region_id.trim().is_empty())
                .map(|r| r.region_id.clone())
                .collect();
            ChapterNoteModeRecord {
                chapter_id: layer.chapter_id.clone(),
                note_mode: NoteMode::from_str(&note_mode).unwrap_or(NoteMode::NoNotes),
                primary_region_scope: String::new(),
                region_ids,
                has_footnote_band: !layer.footnote_items.is_empty(),
                has_endnote_region: !layer.endnote_regions.is_empty(),
            }
        })
        .collect()
}

/// 推断全书注释类型。
///
/// ←→ Python `_phase5_book_type()` (chapter_merge.py:241)
pub fn phase5_book_type(chapter_layers: &ChapterLayers) -> String {
    let modes: HashSet<String> = chapter_layers
        .chapter_layers
        .iter()
        .map(effective_note_mode_from_layer)
        .collect();
    let has_footnote = modes.contains("footnote_primary");
    let has_endnote =
        modes.contains("chapter_endnote_primary") || modes.contains("book_endnote_bound");
    if has_footnote && has_endnote {
        return "mixed".to_string();
    }
    if has_endnote {
        return "endnote_only".to_string();
    }
    if has_footnote {
        return "footnote_only".to_string();
    }
    "no_notes".to_string()
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
    use fnm_core::types::{NoteKind, RegionScope, RegionSource};
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
        let mut layer = ChapterLayer::default();
        layer.chapter_id = "ch1".to_string();
        layer.body_pages = vec![make_body_layer(1), make_body_layer(2), make_body_layer(3)];
        let pages = chapter_pages_from_layer(&layer);
        assert_eq!(pages, vec![1, 2, 3]);
    }

    #[test]
    fn test_chapter_pages_from_layer_with_notes() {
        let mut layer = ChapterLayer::default();
        layer.chapter_id = "ch1".to_string();
        layer.body_pages = vec![make_body_layer(1), make_body_layer(2)];
        layer.footnote_items = vec![make_note_item(1, NoteKind::Footnote)];
        layer.endnote_items = vec![make_note_item(5, NoteKind::Endnote)];
        let pages = chapter_pages_from_layer(&layer);
        assert_eq!(pages, vec![1, 2, 5]);
    }

    #[test]
    fn test_chapter_pages_from_layer_empty() {
        let layer = ChapterLayer::default();
        assert!(chapter_pages_from_layer(&layer).is_empty());
    }

    #[test]
    fn test_effective_note_mode_footnote() {
        let mut layer = ChapterLayer::default();
        layer.footnote_items = vec![make_note_item(1, NoteKind::Footnote)];
        assert_eq!(effective_note_mode_from_layer(&layer), "footnote_primary");
    }

    #[test]
    fn test_effective_note_mode_endnote_chapter() {
        let mut layer = ChapterLayer::default();
        layer.endnote_items = vec![make_note_item(10, NoteKind::Endnote)];
        assert_eq!(
            effective_note_mode_from_layer(&layer),
            "chapter_endnote_primary"
        );
    }

    #[test]
    fn test_effective_note_mode_book_endnote() {
        let mut layer = ChapterLayer::default();
        layer.endnote_items = vec![make_note_item(10, NoteKind::Endnote)];
        layer.endnote_regions = vec![fnm_core::records::NoteRegionRecord {
            region_id: "r1".to_string(),
            chapter_id: String::new(),
            page_start: 0,
            page_end: 0,
            pages: vec![],
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
        }];
        assert_eq!(effective_note_mode_from_layer(&layer), "book_endnote_bound");
    }

    #[test]
    fn test_effective_note_mode_no_notes() {
        let layer = ChapterLayer::default();
        assert_eq!(effective_note_mode_from_layer(&layer), "no_notes");
    }

    #[test]
    fn test_phase5_book_type_footnote_only() {
        let mut layers = ChapterLayers::default();
        let mut layer = ChapterLayer::default();
        layer.chapter_id = "ch1".to_string();
        layer.footnote_items = vec![make_note_item(1, NoteKind::Footnote)];
        layers.chapter_layers.push(layer);
        assert_eq!(phase5_book_type(&layers), "footnote_only");
    }

    #[test]
    fn test_phase5_book_type_mixed() {
        let mut layers = ChapterLayers::default();
        let mut ch1 = ChapterLayer::default();
        ch1.chapter_id = "ch1".to_string();
        ch1.footnote_items = vec![make_note_item(1, NoteKind::Footnote)];
        layers.chapter_layers.push(ch1);
        let mut ch2 = ChapterLayer::default();
        ch2.chapter_id = "ch2".to_string();
        ch2.endnote_items = vec![make_note_item(10, NoteKind::Endnote)];
        layers.chapter_layers.push(ch2);
        assert_eq!(phase5_book_type(&layers), "mixed");
    }

    #[test]
    fn test_phase5_book_type_no_notes() {
        let layers = ChapterLayers::default();
        assert_eq!(phase5_book_type(&layers), "no_notes");
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
        let mut layer = ChapterLayer::default();
        layer.chapter_id = "ch1".to_string();
        layer.title = "Chapter 1".to_string();
        layer.body_pages = vec![make_body_layer(5), make_body_layer(10)];
        layers.chapter_layers.push(layer);
        let result = to_chapter_records(&layers);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].chapter_id, "ch1");
        assert_eq!(result[0].title, "Chapter 1");
        assert_eq!(result[0].start_page, 5);
        assert_eq!(result[0].end_page, 10);
    }
}

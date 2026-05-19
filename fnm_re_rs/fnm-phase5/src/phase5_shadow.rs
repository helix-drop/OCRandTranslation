//! ←→ FNM_RE/modules/chapter_merge.py
//! 翻译的函数：
//!   build_phase5_shadow ←→ _build_phase5_shadow (chapter_merge.py:289)

use std::collections::HashMap;

use fnm_core::records::{
    ChapterNoteModeRecord, DiagnosticPageRecord, Phase5Structure, Phase5Summary, SectionHeadRecord,
};
use fnm_phase2::chapter_split::ChapterLayers;
use fnm_phase3::note_linking::NoteLinkTable;

use crate::convert;

/// 构建 Phase 5 影子结构。
///
/// ←→ Python `_build_phase5_shadow()` (chapter_merge.py:289)
pub fn build_phase5_shadow(
    frozen_units: &fnm_core::records::FrozenUnits,
    note_link_table: &NoteLinkTable,
    chapter_layers: &ChapterLayers,
    diagnostic_machine_by_page: Option<&HashMap<String, String>>,
    include_diagnostic_entries: bool,
    section_heads: Option<&[SectionHeadRecord]>,
) -> Phase5Structure {
    let chapter_note_modes: Vec<ChapterNoteModeRecord> =
        convert::to_chapter_note_mode_records(chapter_layers);
    let mode_counts: HashMap<String, i64> = {
        let mut counts: HashMap<String, i64> = HashMap::new();
        for row in &chapter_note_modes {
            *counts
                .entry(row.note_mode.as_str().to_string())
                .or_insert(0) += 1;
        }
        counts
    };
    let chapter_note_mode_summary = serde_json::json!({
        "book_type": convert::phase5_book_type(chapter_layers),
        "mode_counts": mode_counts,
    });

    let diagnostic_pages: Vec<DiagnosticPageRecord> = if include_diagnostic_entries {
        if let Some(mapping) = diagnostic_machine_by_page {
            convert::to_diagnostic_pages(mapping)
        } else {
            Vec::new()
        }
    } else {
        Vec::new()
    };

    Phase5Structure {
        chapters: convert::to_chapter_records(chapter_layers),
        section_heads: section_heads.map(|s| s.to_vec()).unwrap_or_default(),
        note_items: convert::to_note_item_records(chapter_layers),
        chapter_note_modes,
        body_anchors: convert::to_body_anchor_records(note_link_table),
        effective_note_links: convert::to_note_link_records(note_link_table),
        translation_units: convert::to_translation_unit_records(frozen_units),
        diagnostic_pages,
        summary: Phase5Summary {
            chapter_note_mode_summary,
            ..Default::default()
        },
        ..Default::default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::SectionHeadRecord;
    use fnm_core::types::NoteMode;
    use fnm_phase2::chapter_split::ChapterLayer;

    #[test]
    fn test_build_phase5_shadow_empty() {
        let frozen = fnm_core::records::FrozenUnits::default();
        let link_table = NoteLinkTable::default();
        let layers = ChapterLayers::default();
        let result = build_phase5_shadow(&frozen, &link_table, &layers, None, false, None);
        assert!(result.chapters.is_empty());
        assert!(result.note_items.is_empty());
        assert!(result.body_anchors.is_empty());
        assert!(result.effective_note_links.is_empty());
        assert!(result.translation_units.is_empty());
        assert!(result.diagnostic_pages.is_empty());
    }

    #[test]
    fn test_build_phase5_shadow_with_chapter() {
        let frozen = fnm_core::records::FrozenUnits::default();
        let link_table = NoteLinkTable::default();
        let mut layers = ChapterLayers::default();
        let mut layer = ChapterLayer::default();
        layer.chapter_id = "ch1".to_string();
        layer.title = "Chapter 1".to_string();
        layer.footnote_items = vec![fnm_core::records::NoteItemRecord {
            note_item_id: "n1".to_string(),
            chapter_id: "ch1".to_string(),
            page_no: 5,
            marker: "1".to_string(),
            note_kind: fnm_core::types::NoteKind::Footnote,
            ..Default::default()
        }];
        layers.chapter_layers.push(layer);
        layers.note_items.push(fnm_core::records::NoteItemRecord {
            note_item_id: "n1".to_string(),
            chapter_id: "ch1".to_string(),
            page_no: 5,
            marker: "1".to_string(),
            note_kind: fnm_core::types::NoteKind::Footnote,
            ..Default::default()
        });
        let heads = vec![SectionHeadRecord {
            section_head_id: "sh1".to_string(),
            chapter_id: String::new(),
            title: "1.1".to_string(),
            page_no: 0,
            level: 1,
            source: String::new(),
        }];
        let result = build_phase5_shadow(&frozen, &link_table, &layers, None, false, Some(&heads));
        assert_eq!(result.chapters.len(), 1);
        assert_eq!(result.section_heads.len(), 1);
        assert_eq!(result.note_items.len(), 1);
        assert_eq!(result.chapter_note_modes.len(), 1);
        assert_eq!(
            result.chapter_note_modes[0].note_mode,
            NoteMode::FootnotePrimary
        );
        assert_eq!(
            result
                .summary
                .chapter_note_mode_summary
                .get("book_type")
                .and_then(|v| v.as_str()),
            Some("footnote_only")
        );
    }

    #[test]
    fn test_build_phase5_shadow_diagnostic_pages_included() {
        let frozen = fnm_core::records::FrozenUnits::default();
        let link_table = NoteLinkTable::default();
        let layers = ChapterLayers::default();
        let mut diag = HashMap::new();
        diag.insert("1".to_string(), "Page 1 text.".to_string());
        diag.insert("3".to_string(), "Page 3 text.".to_string());
        let result = build_phase5_shadow(&frozen, &link_table, &layers, Some(&diag), true, None);
        assert_eq!(result.diagnostic_pages.len(), 2);
        assert_eq!(result.diagnostic_pages[0]._page_bp, 1);
        assert_eq!(result.diagnostic_pages[1]._page_bp, 3);
    }
}

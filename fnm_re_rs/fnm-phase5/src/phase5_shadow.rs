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
    // 使用 Phase2 权威的 chapter_note_modes，不重新推导
    let chapter_note_modes: Vec<ChapterNoteModeRecord> = chapter_layers.chapter_note_modes.clone();
    let mode_counts: HashMap<String, i64> = {
        let mut counts: HashMap<String, i64> = HashMap::new();
        for row in &chapter_note_modes {
            *counts
                .entry(row.note_mode.as_str().to_string())
                .or_insert(0) += 1;
        }
        counts
    };
    let book_type = if chapter_note_modes.is_empty() {
        "no_notes".to_string()
    } else {
        let modes_set: std::collections::HashSet<String> = chapter_note_modes
            .iter()
            .map(|m| m.note_mode.as_str().to_string())
            .filter(|m| m != "no_notes")
            .collect();
        let has_footnote = modes_set.contains("footnote_primary");
        let has_endnote = modes_set.contains("chapter_endnote_primary")
            || modes_set.contains("book_endnote_bound");
        if has_footnote && has_endnote {
            "mixed".to_string()
        } else if has_endnote {
            "endnote_only".to_string()
        } else if has_footnote {
            "footnote_only".to_string()
        } else {
            "no_notes".to_string()
        }
    };
    let chapter_note_mode_summary = serde_json::json!({
        "book_type": book_type,
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
        chapters: if chapter_layers.chapters.is_empty() {
            convert::to_chapter_records(chapter_layers)
        } else {
            chapter_layers.chapters.clone()
        },
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
        layers.chapter_layers.push(ChapterLayer {
            chapter_id: "ch1".to_string(),
            title: "Chapter 1".to_string(),
            footnote_items: vec![fnm_core::records::NoteItemRecord {
                note_item_id: "n1".to_string(),
                chapter_id: "ch1".to_string(),
                page_no: 5,
                marker: "1".to_string(),
                note_kind: fnm_core::types::NoteKind::Footnote,
                ..Default::default()
            }],
            ..Default::default()
        });
        layers.note_items.push(fnm_core::records::NoteItemRecord {
            note_item_id: "n1".to_string(),
            chapter_id: "ch1".to_string(),
            page_no: 5,
            marker: "1".to_string(),
            note_kind: fnm_core::types::NoteKind::Footnote,
            ..Default::default()
        });
        // Phase2 权威分类
        layers.chapter_note_modes.push(ChapterNoteModeRecord {
            chapter_id: "ch1".to_string(),
            note_mode: NoteMode::FootnotePrimary,
            region_ids: vec![],
            primary_region_scope: String::new(),
            has_footnote_band: true,
            has_endnote_region: false,
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

    /// Phase5 不得将 endnote region 页码纳入章节边界。
    /// 当前 convert::to_chapter_records 会把 endnote_items/endnote_regions 页码
    /// 合入 chapter.pages，导致章节边界膨胀。
    #[test]
    fn test_chapter_boundary_not_expanded_by_endnote_region() {
        let frozen = fnm_core::records::FrozenUnits::default();
        let link_table = NoteLinkTable::default();
        let mut layers = ChapterLayers::default();
        layers.chapter_layers.push(ChapterLayer {
            chapter_id: "ch1".to_string(),
            title: "Chapter 1".to_string(),
            body_pages: vec![
                fnm_phase2::chapter_split::BodyPageLayer {
                    page_no: 1,
                    text: "Page 1".into(),
                    ..Default::default()
                },
                fnm_phase2::chapter_split::BodyPageLayer {
                    page_no: 2,
                    text: "Page 2".into(),
                    ..Default::default()
                },
                fnm_phase2::chapter_split::BodyPageLayer {
                    page_no: 3,
                    text: "Page 3".into(),
                    ..Default::default()
                },
            ],
            endnote_regions: vec![fnm_core::records::NoteRegionRecord {
                region_id: "en_region".to_string(),
                chapter_id: "ch1".to_string(),
                page_start: 100,
                page_end: 150,
                pages: vec![100, 101, 102],
                note_kind: fnm_core::types::NoteKind::Endnote,
                scope: fnm_core::types::RegionScope::Book,
                source: fnm_core::types::RegionSource::HeadingScan,
                heading_text: String::new(),
                start_reason: String::new(),
                end_reason: String::new(),
                region_marker_alignment_ok: false,
                region_start_first_source_marker: String::new(),
                region_first_note_item_marker: String::new(),
                review_required: false,
            }],
            endnote_items: vec![fnm_core::records::NoteItemRecord {
                note_item_id: "en1".to_string(),
                chapter_id: "ch1".to_string(),
                page_no: 100,
                marker: "1".to_string(),
                note_kind: fnm_core::types::NoteKind::Endnote,
                ..Default::default()
            }],
            ..Default::default()
        });
        layers.note_items.push(fnm_core::records::NoteItemRecord {
            note_item_id: "en1".to_string(),
            chapter_id: "ch1".to_string(),
            page_no: 100,
            marker: "1".to_string(),
            note_kind: fnm_core::types::NoteKind::Endnote,
            ..Default::default()
        });

        let result = build_phase5_shadow(&frozen, &link_table, &layers, None, false, None);
        assert_eq!(result.chapters.len(), 1);
        // 章节页面列表应仅含正文页，不应包括 endnote region 的页
        let ch = &result.chapters[0];
        for p in &ch.pages {
            assert!(
                *p <= 3,
                "chapter boundary should not include endnote region pages, got page {p}"
            );
        }
        assert_eq!(ch.start_page, 1, "chapter should start at first body page");
        assert_eq!(
            ch.end_page, 3,
            "chapter should end at last body page, not at endnote region"
        );
    }

    /// Phase5 透传 Phase2 note mode，不从 layer 重新推断。
    #[test]
    fn test_note_mode_not_reinferred_from_items() {
        let frozen = fnm_core::records::FrozenUnits::default();
        let link_table = NoteLinkTable::default();
        let mut layers = ChapterLayers::default();
        layers.chapter_layers.push(ChapterLayer {
            chapter_id: "ch1".to_string(),
            title: "Chapter 1".to_string(),
            footnote_items: vec![fnm_core::records::NoteItemRecord {
                note_item_id: "fn1".to_string(),
                chapter_id: "ch1".to_string(),
                page_no: 1,
                marker: "1".to_string(),
                note_kind: fnm_core::types::NoteKind::Footnote,
                ..Default::default()
            }],
            endnote_items: vec![fnm_core::records::NoteItemRecord {
                note_item_id: "en1".to_string(),
                chapter_id: "ch1".to_string(),
                page_no: 2,
                marker: "1".to_string(),
                note_kind: fnm_core::types::NoteKind::Endnote,
                ..Default::default()
            }],
            ..Default::default()
        });
        layers.note_items.push(fnm_core::records::NoteItemRecord {
            note_item_id: "fn1".to_string(),
            chapter_id: "ch1".to_string(),
            page_no: 1,
            marker: "1".to_string(),
            note_kind: fnm_core::types::NoteKind::Footnote,
            ..Default::default()
        });
        layers.note_items.push(fnm_core::records::NoteItemRecord {
            note_item_id: "en1".to_string(),
            chapter_id: "ch1".to_string(),
            page_no: 2,
            marker: "1".to_string(),
            note_kind: fnm_core::types::NoteKind::Endnote,
            ..Default::default()
        });
        // Phase2 说这是 footnote_primary，尽管章内有 endnote items
        layers.chapter_note_modes.push(ChapterNoteModeRecord {
            chapter_id: "ch1".to_string(),
            note_mode: NoteMode::FootnotePrimary,
            region_ids: vec![],
            primary_region_scope: String::new(),
            has_footnote_band: true,
            has_endnote_region: true,
        });

        let result = build_phase5_shadow(&frozen, &link_table, &layers, None, false, None);
        assert_eq!(result.chapter_note_modes.len(), 1);
        let mode = &result.chapter_note_modes[0];
        // Phase5 应透传 Phase2 的分类，不改为 chapter_endnote_primary
        assert_eq!(
            mode.note_mode.as_str(),
            "footnote_primary",
            "Phase5 should pass through Phase2 note mode, not re-derive from items"
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

    /// 使用 Goldstein 真实页面数据验证章节边界计算。
    #[test]
    fn goldstein_intro_boundary_from_real_fixture() {
        let raw_fixture: serde_json::Value =
            serde_json::from_str(include_str!("../tests/fixtures/goldstein_intro.json"))
                .expect("fixture JSON");

        let pages = raw_fixture["pages"].as_array().expect("pages array");
        let body_pages: Vec<fnm_phase2::chapter_split::BodyPageLayer> = pages
            .iter()
            .filter_map(|p| {
                let bp = p["bookPage"].as_i64().unwrap_or(0);
                if bp > 0 {
                    Some(fnm_phase2::chapter_split::BodyPageLayer {
                        page_no: bp,
                        text: String::new(),
                        ..Default::default()
                    })
                } else {
                    None
                }
            })
            .collect();

        assert!(!body_pages.is_empty(), "should have real body pages");

        let layer = ChapterLayer {
            chapter_id: "introduction".to_string(),
            title: "Introduction: Psychological Interiority versus Self-Talk".to_string(),
            body_pages,
            ..Default::default()
        };

        let pages = crate::convert::chapter_pages_from_layer(&layer);
        assert_eq!(pages.first().copied(), Some(18));
        assert_eq!(pages.last().copied(), Some(24));
        assert_eq!(pages.len(), 7);
    }

    /// 使用 Biopolitics 真实页面数据验证章节边界计算。
    #[test]
    fn biopolitics_ch1_boundary_from_real_fixture() {
        let raw_fixture: serde_json::Value =
            serde_json::from_str(include_str!("../tests/fixtures/biopolitics_ch1.json"))
                .expect("fixture JSON");

        let pages = raw_fixture["pages"].as_array().expect("pages array");
        let body_pages: Vec<fnm_phase2::chapter_split::BodyPageLayer> = pages
            .iter()
            .filter_map(|p| {
                let bp = p["bookPage"].as_i64().unwrap_or(0);
                if bp > 0 {
                    Some(fnm_phase2::chapter_split::BodyPageLayer {
                        page_no: bp,
                        text: String::new(),
                        ..Default::default()
                    })
                } else {
                    None
                }
            })
            .collect();

        assert!(!body_pages.is_empty(), "should have real body pages");
        assert_eq!(body_pages.len(), 20, "chapter 1 should span 20 pages");

        let layer = ChapterLayer {
            chapter_id: "ch1".to_string(),
            title: "Leçon du 10 janvier 1979".to_string(),
            body_pages,
            ..Default::default()
        };

        let pages = crate::convert::chapter_pages_from_layer(&layer);
        assert_eq!(pages.first().copied(), Some(21));
        assert_eq!(pages.last().copied(), Some(40));
        assert_eq!(pages.len(), 20);
    }
}

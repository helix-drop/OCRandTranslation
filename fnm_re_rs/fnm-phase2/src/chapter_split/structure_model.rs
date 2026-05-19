//! ←→ FNM_RE/modules/chapter_split.py
//! `_note_capture_summary` + `_chapter_binding_summary`
//! + `_infer_numbering_topology` + `_build_book_structure_model`.

use super::ChapterLayer;
use fnm_core::records::{ChapterNoteModeRecord, ChapterRecord, NoteItemRecord, NoteRegionRecord};
use fnm_core::types::{BookType, NoteMode};
use std::collections::{HashMap, HashSet};

// ── BookStructureModel ──────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct ChapterStructureModel {
    pub chapter_id: String,
    pub note_mode: NoteMode,
    pub primary_note_kind: Option<String>, // "footnote" / "endnote" / None
    pub page_start: i64,
    pub page_end: i64,
    pub expected_anchor_count: i64,
    pub captured_note_count: i64,
    pub has_explicit_notes_heading: bool,
}

#[derive(Debug, Clone)]
pub struct OCRProfile {
    pub placeholder: bool, // 占位字段（与 Python OCRProfile() 默认对齐）
    pub unrecovered_marker_ids: Vec<String>, // ←→ Python `ocr_profile.unrecovered_marker_ids`
}

impl Default for OCRProfile {
    fn default() -> Self {
        Self {
            placeholder: false,
            unrecovered_marker_ids: Vec::new(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct BookStructureModel {
    pub book_type: BookType,
    pub numbering_topology: String, // "book_continuous" / "per_chapter_reset"
    pub chapters: Vec<ChapterStructureModel>,
    pub ocr_profile: OCRProfile,
}

// ── _infer_numbering_topology ──────────────────────────────────

/// ←→ Python `_infer_numbering_topology`
pub fn infer_numbering_topology(chapter_note_modes: &[ChapterNoteModeRecord]) -> String {
    let has_book_endnote = chapter_note_modes
        .iter()
        .any(|m| m.note_mode == NoteMode::BookEndnoteBound);
    if has_book_endnote {
        "book_continuous".into()
    } else {
        "per_chapter_reset".into()
    }
}

// ── _note_capture_summary ──────────────────────────────────────

/// ←→ Python `_note_capture_summary`
///
/// 输入：chapter_layers + chapter_marker_counts (chapter_id → expected anchor count)
///        + page_marker_counts_by_chapter (chapter_id → page_no_str → marker_count)
///        + mode_by_chapter + book_type
/// 输出：(is_ok, summary_value)
pub fn note_capture_summary(
    chapter_layers: &[ChapterLayer],
    chapter_marker_counts: &HashMap<String, i64>,
    page_marker_counts_by_chapter: &HashMap<String, HashMap<String, i64>>,
    mode_by_chapter: &HashMap<String, NoteMode>,
    book_type: BookType,
) -> (bool, serde_json::Value) {
    let mut chapter_rows: Vec<serde_json::Value> = Vec::new();
    let mut sparse_chapter_ids: Vec<String> = Vec::new();
    let mut sparse_pages: Vec<serde_json::Value> = Vec::new();
    let mut expected_total: i64 = 0;
    let mut captured_total: i64 = 0;

    for chapter in chapter_layers {
        let chapter_id = chapter.chapter_id.clone();
        let note_mode = mode_by_chapter
            .get(&chapter_id)
            .copied()
            .unwrap_or(NoteMode::NoNotes);
        let expected_count = chapter_marker_counts.get(&chapter_id).copied().unwrap_or(0);
        let captured_count: i64 = match note_mode {
            NoteMode::FootnotePrimary => chapter.footnote_items.len() as i64,
            NoteMode::ChapterEndnotePrimary | NoteMode::BookEndnoteBound => {
                chapter.endnote_items.len() as i64
            }
            _ => (chapter.footnote_items.len() + chapter.endnote_items.len()) as i64,
        };
        expected_total += expected_count;
        captured_total += captured_count;
        let ratio = if expected_count > 0 {
            captured_count as f64 / expected_count as f64
        } else {
            1.0
        };
        let mut row = serde_json::json!({
            "chapter_id": chapter_id,
            "note_mode": note_mode.as_str(),
            "expected_anchor_count": expected_count,
            "captured_note_count": captured_count,
            "capture_ratio": (ratio * 10_000.0).round() / 10_000.0,
        });

        // footnote_only 书的 expected_count 来自 body anchor digit markers
        let should_block_sparse = matches!(book_type, BookType::EndnoteOnly)
            || (matches!(book_type, BookType::NoNotes) && note_mode == NoteMode::NoNotes);
        if should_block_sparse && captured_count > 0 && expected_count >= 10 && ratio < 0.6 {
            sparse_chapter_ids.push(chapter_id.clone());
            row["sparse_capture"] = serde_json::Value::Bool(true);
        }
        chapter_rows.push(row);

        // page-level sparse pages
        let page_counts = page_marker_counts_by_chapter.get(&chapter_id);
        if let Some(pc) = page_counts {
            // captured_pages = footnote pages ∪ endnote pages
            let mut captured_pages: HashSet<i64> = HashSet::new();
            for item in &chapter.footnote_items {
                if item.page_no > 0 {
                    captured_pages.insert(item.page_no);
                }
            }
            for item in &chapter.endnote_items {
                if item.page_no > 0 {
                    captured_pages.insert(item.page_no);
                }
            }
            let skip_page_check = matches!(
                note_mode,
                NoteMode::BookEndnoteBound | NoteMode::ChapterEndnotePrimary
            );
            for (page_no_str, &expected_page_count) in pc {
                let page_no = match page_no_str.parse::<i64>() {
                    Ok(v) => v,
                    Err(_) => continue,
                };
                if !skip_page_check
                    && should_block_sparse
                    && expected_page_count >= 8
                    && !captured_pages.contains(&page_no)
                {
                    sparse_pages.push(serde_json::json!({
                        "chapter_id": chapter_id,
                        "page_no": page_no,
                        "expected_anchor_count": expected_page_count,
                        "captured_note_count": 0,
                    }));
                }
            }
        }
    }

    let overall_ratio = if expected_total > 0 {
        ((captured_total as f64 / expected_total as f64) * 10_000.0).round() / 10_000.0
    } else {
        1.0
    };
    let summary = serde_json::json!({
        "expected_anchor_count": expected_total,
        "captured_note_count": captured_total,
        "capture_ratio": overall_ratio,
        "sparse_capture_chapter_ids": sparse_chapter_ids.clone(),
        "dense_anchor_zero_capture_pages": sparse_pages.iter().take(24).cloned().collect::<Vec<_>>(),
        "chapters": chapter_rows.iter().take(32).cloned().collect::<Vec<_>>(),
    });
    let ok = sparse_chapter_ids.is_empty() && sparse_pages.is_empty();
    (ok, summary)
}

// ── _chapter_binding_summary ───────────────────────────────────

/// ←→ Python `_chapter_binding_summary`
pub fn chapter_binding_summary(
    layer_regions: &[NoteRegionRecord],
    layer_items: &[NoteItemRecord],
    chapter_ids: &HashSet<String>,
) -> serde_json::Value {
    let unbound_region_ids: Vec<String> = layer_regions
        .iter()
        .filter(|r| !chapter_ids.contains(&r.chapter_id))
        .map(|r| r.region_id.clone())
        .collect();
    let book_scope_region_ids: Vec<String> = layer_regions
        .iter()
        .filter(|r| r.scope == fnm_core::types::RegionScope::Book)
        .map(|r| r.region_id.clone())
        .collect();
    let unassigned_item_ids: Vec<String> = layer_items
        .iter()
        .filter(|i| !chapter_ids.contains(&i.chapter_id))
        .map(|i| i.note_item_id.clone())
        .collect();

    serde_json::json!({
        "region_count": layer_regions.len(),
        "book_scope_region_count": book_scope_region_ids.len(),
        "unbound_region_count": unbound_region_ids.len(),
        "unbound_region_ids_preview": unbound_region_ids.iter().take(16).cloned().collect::<Vec<_>>(),
        "unassigned_item_count": unassigned_item_ids.len(),
        "unassigned_item_ids_preview": unassigned_item_ids.iter().take(16).cloned().collect::<Vec<_>>(),
    })
}

// ── _build_book_structure_model ────────────────────────────────

/// ←→ Python `_build_book_structure_model`
pub fn build_book_structure_model(
    book_type: BookType,
    chapter_layers: &[ChapterLayer],
    phase1_chapters: &[ChapterRecord],
    chapter_marker_counts: &HashMap<String, i64>,
    chapter_note_modes: &[ChapterNoteModeRecord],
) -> BookStructureModel {
    let phase1_by_id: HashMap<&str, &ChapterRecord> = phase1_chapters
        .iter()
        .map(|ch| (ch.chapter_id.as_str(), ch))
        .collect();

    let mut chapter_models: Vec<ChapterStructureModel> = Vec::new();
    for layer in chapter_layers {
        let ch_id = layer.chapter_id.clone();
        let note_mode = layer.note_mode;
        let primary_kind = match note_mode {
            NoteMode::FootnotePrimary => Some("footnote".to_string()),
            NoteMode::ChapterEndnotePrimary | NoteMode::BookEndnoteBound => {
                Some("endnote".to_string())
            }
            _ => None,
        };
        let phase1_ch = phase1_by_id.get(ch_id.as_str()).copied();
        let captured = (layer.footnote_items.len() + layer.endnote_items.len()) as i64;
        let expected = chapter_marker_counts.get(&ch_id).copied().unwrap_or(0);
        // 检测 body_pages 中是否有显式 Notes/Endnotes heading
        let has_heading = layer
            .body_pages
            .iter()
            .any(|p| p.text.contains("### NOTES") || p.text.contains("### Endnotes"));

        chapter_models.push(ChapterStructureModel {
            chapter_id: ch_id,
            note_mode,
            primary_note_kind: primary_kind,
            page_start: phase1_ch.map(|c| c.start_page).unwrap_or(0),
            page_end: phase1_ch.map(|c| c.end_page).unwrap_or(0),
            expected_anchor_count: expected,
            captured_note_count: captured,
            has_explicit_notes_heading: has_heading,
        });
    }

    BookStructureModel {
        book_type,
        numbering_topology: infer_numbering_topology(chapter_note_modes),
        chapters: chapter_models,
        ocr_profile: OCRProfile::default(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{NoteMode, RegionScope, RegionSource};

    #[test]
    fn topology_book_continuous_when_any_book_endnote_bound() {
        let modes = vec![ChapterNoteModeRecord {
            chapter_id: "ch-1".into(),
            note_mode: NoteMode::BookEndnoteBound,
            region_ids: vec![],
            primary_region_scope: "book".into(),
            has_footnote_band: false,
            has_endnote_region: false,
        }];
        assert_eq!(infer_numbering_topology(&modes), "book_continuous");
    }

    #[test]
    fn topology_per_chapter_otherwise() {
        let modes = vec![ChapterNoteModeRecord {
            chapter_id: "ch-1".into(),
            note_mode: NoteMode::FootnotePrimary,
            region_ids: vec![],
            primary_region_scope: "chapter".into(),
            has_footnote_band: true,
            has_endnote_region: false,
        }];
        assert_eq!(infer_numbering_topology(&modes), "per_chapter_reset");
    }

    #[test]
    fn note_capture_summary_empty() {
        let (ok, summary) = note_capture_summary(
            &[],
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
            BookType::NoNotes,
        );
        assert!(ok);
        assert_eq!(summary["expected_anchor_count"], 0);
        assert_eq!(summary["captured_note_count"], 0);
    }

    #[test]
    fn chapter_binding_summary_unbound() {
        let region = NoteRegionRecord {
            region_id: "r-1".into(),
            chapter_id: "ch-ghost".into(),
            page_start: 1,
            page_end: 2,
            pages: vec![1, 2],
            note_kind: fnm_core::types::NoteKind::Endnote,
            scope: RegionScope::Book,
            source: RegionSource::HeadingScan,
            heading_text: String::new(),
            start_reason: String::new(),
            end_reason: String::new(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: String::new(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        };
        let mut ids = HashSet::new();
        ids.insert("ch-real".to_string());
        let summary = chapter_binding_summary(&[region], &[], &ids);
        assert_eq!(summary["unbound_region_count"], 1);
        assert_eq!(summary["book_scope_region_count"], 1);
    }

    #[test]
    fn build_book_structure_model_basic() {
        let chapter = ChapterRecord {
            chapter_id: "ch-1".into(),
            title: "Chapter 1".into(),
            start_page: 1,
            end_page: 10,
            pages: (1..=10).collect(),
            source: fnm_core::types::ChapterSource::VisualToc,
            boundary_state: fnm_core::types::BoundaryState::Ready,
        };
        let layer = ChapterLayer {
            chapter_id: "ch-1".into(),
            title: "Chapter 1".into(),
            start_page: 1,
            end_page: 10,
            note_mode: NoteMode::FootnotePrimary,
            ..Default::default()
        };
        let modes = vec![ChapterNoteModeRecord {
            chapter_id: "ch-1".into(),
            note_mode: NoteMode::FootnotePrimary,
            region_ids: vec![],
            primary_region_scope: "chapter".into(),
            has_footnote_band: true,
            has_endnote_region: false,
        }];
        let model = build_book_structure_model(
            BookType::FootnoteOnly,
            &[layer],
            &[chapter],
            &HashMap::new(),
            &modes,
        );
        assert_eq!(model.chapters.len(), 1);
        assert_eq!(model.chapters[0].primary_note_kind, Some("footnote".into()));
        assert_eq!(model.numbering_topology, "per_chapter_reset");
    }
}

//! ←→ Python `note_linking.py:_phase2_from_chapter_layers`

use fnm_core::records::{
    ChapterNoteModeRecord, ChapterRecord, NoteItemRecord, NoteRegionRecord, PagePartitionRecord,
    Phase2Structure, Phase2Summary,
};
use fnm_core::types::{BoundaryState, ChapterSource, NoteKind, NoteMode, RegionScope};
use fnm_phase2::chapter_split::ChapterLayers;
use std::collections::{HashMap, HashSet};

/// 将 ChapterLayers 重建为 Phase2Structure。
///
/// ←→ Python `_phase2_from_chapter_layers`
///
/// 注意:Python 的 ChapterLayers.chapters 等价于 Rust 的 `chapter_layers.chapter_layers`
/// (Vec<ChapterLayer>),里面才有 policy_applied / body_pages / footnote_items / endnote_items /
/// endnote_regions。`chapter_layers.chapters` 在 Rust 端只保存薄 ChapterRecord (7 字段)。
pub fn phase2_from_chapter_layers(
    chapter_layers: &ChapterLayers,
) -> (Phase2Structure, HashMap<String, String>, String) {
    let chapter_policy_by_id: HashMap<String, HashMap<String, serde_json::Value>> = chapter_layers
        .chapter_layers
        .iter()
        .map(|cl| {
            let policy: HashMap<String, serde_json::Value> = cl
                .policy_applied
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect();
            (cl.chapter_id.clone(), policy)
        })
        .collect();

    let mut region_note_kind_by_id: HashMap<String, String> = HashMap::new();
    let mut region_records: Vec<NoteRegionRecord> = Vec::new();
    for row in &chapter_layers.regions {
        let chapter_id = row.chapter_id.clone();
        // CLAUDE.md §12：不可用章级 mode 重分类个体 entity（对齐 Python `_ = chapter_mode`）。
        // 故意计算后丢弃以保留意图。注意：用 &str 不 to_string，避免 hot loop 内 alloc。
        let _chapter_mode = chapter_policy_by_id
            .get(&chapter_id)
            .and_then(|p| p.get("note_mode"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let note_kind_str = row.note_kind.as_str();
        let note_kind = if note_kind_str == "footnote" || note_kind_str == "endnote" {
            note_kind_str.to_string()
        } else {
            // note_kind 为空时保持空——不可用章级 chapter_mode 推断个体类型
            String::new()
        };
        region_note_kind_by_id.insert(row.region_id.clone(), note_kind.clone());
        region_records.push(NoteRegionRecord {
            region_id: row.region_id.clone(),
            chapter_id: chapter_id.clone(),
            page_start: row.page_start,
            page_end: row.page_end,
            pages: row.pages.clone(),
            note_kind: if note_kind == "footnote" {
                NoteKind::Footnote
            } else if note_kind == "endnote" {
                NoteKind::Endnote
            } else {
                NoteKind::Footnote
            },
            scope: row.scope,
            source: row.source,
            heading_text: row.heading_text.clone(),
            start_reason: "module_projection".to_string(),
            end_reason: "module_projection".to_string(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: String::new(),
            region_first_note_item_marker: String::new(),
            review_required: row.review_required,
        });
    }

    let mut note_items: Vec<NoteItemRecord> = Vec::new();
    for row in &chapter_layers.note_items {
        let chapter_id = row
            .owner_chapter_id
            .as_ref()
            .unwrap_or(&row.chapter_id)
            .clone();
        // CLAUDE.md §12：不可用章级 mode 重分类个体 entity（对齐 Python `_ = chapter_mode`）。
        let _chapter_mode = chapter_policy_by_id
            .get(&chapter_id)
            .and_then(|p| p.get("note_mode"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let region_id = row.region_id.clone();
        let region_note_kind = region_note_kind_by_id
            .get(&region_id)
            .cloned()
            .unwrap_or_default();
        let raw_note_kind = row.note_kind.as_str();
        let note_kind_str = if raw_note_kind == "footnote" || raw_note_kind == "endnote" {
            raw_note_kind.to_string()
        } else if !region_note_kind.is_empty() {
            region_note_kind
        } else {
            String::new()
        };
        let marker_type = if row.marker_type.is_empty() && note_kind_str == "footnote" {
            "footnote_marker".to_string()
        } else if row.marker_type.is_empty() && note_kind_str == "endnote" {
            "numeric".to_string()
        } else {
            row.marker_type.clone()
        };
        note_items.push(NoteItemRecord {
            note_item_id: row.note_item_id.clone(),
            region_id,
            chapter_id,
            page_no: row.page_no,
            marker: row.marker.clone(),
            marker_type,
            text: row.text.clone(),
            source: row.source.clone(),
            source_page_label: row.page_no.to_string(),
            is_reconstructed: row.is_reconstructed,
            review_required: row.review_required,
            note_kind: if note_kind_str == "footnote" {
                NoteKind::Footnote
            } else if note_kind_str == "endnote" {
                NoteKind::Endnote
            } else {
                NoteKind::Footnote
            },
            projection_mode: row.projection_mode.clone(),
            owner_chapter_id: row.owner_chapter_id.clone(),
            source_marker: row.source_marker.clone(),
            normalized_marker: row.normalized_marker.clone(),
        });
    }

    let mut region_ids_by_chapter: HashMap<String, HashSet<String>> = HashMap::new();
    for region in &region_records {
        region_ids_by_chapter
            .entry(region.chapter_id.clone())
            .or_default()
            .insert(region.region_id.clone());
    }

    let mut note_mode_by_chapter: HashMap<String, String> = HashMap::new();
    let mut chapter_records: Vec<ChapterRecord> = Vec::new();
    let mut chapter_note_modes: Vec<ChapterNoteModeRecord> = Vec::new();
    let mut body_page_records: Vec<PagePartitionRecord> = Vec::new();
    let mut body_seen_pages: HashSet<i64> = HashSet::new();
    let mut book_type = "no_notes".to_string();

    for cl in &chapter_layers.chapter_layers {
        let chapter_id = cl.chapter_id.clone();
        let mut page_nos: HashSet<i64> = HashSet::new();
        for row in &cl.body_pages {
            if row.page_no > 0 {
                page_nos.insert(row.page_no);
            }
        }
        for row in &cl.footnote_items {
            if row.page_no > 0 {
                page_nos.insert(row.page_no);
            }
        }
        for row in &cl.endnote_items {
            if row.page_no > 0 {
                page_nos.insert(row.page_no);
            }
        }
        for region in &cl.endnote_regions {
            for page_no in &region.pages {
                if *page_no > 0 {
                    page_nos.insert(*page_no);
                }
            }
            if region.page_start > 0 {
                page_nos.insert(region.page_start);
            }
            if region.page_end > 0 {
                page_nos.insert(region.page_end);
            }
        }
        let mut sorted_pages: Vec<i64> = page_nos.iter().copied().collect();
        sorted_pages.sort_unstable();
        let start_page = sorted_pages.first().copied().unwrap_or(0);
        let end_page = sorted_pages.last().copied().unwrap_or(0);
        chapter_records.push(ChapterRecord {
            chapter_id: chapter_id.clone(),
            title: cl.title.clone(),
            start_page,
            end_page,
            pages: sorted_pages,
            source: ChapterSource::Fallback,
            boundary_state: BoundaryState::Ready,
        });

        let chapter_regions: Vec<&NoteRegionRecord> = region_records
            .iter()
            .filter(|r| r.chapter_id == chapter_id)
            .collect();
        let has_footnote_band = chapter_regions
            .iter()
            .any(|r| r.note_kind.as_str() == "footnote");
        let has_endnote_region = chapter_regions
            .iter()
            .any(|r| r.note_kind.as_str() == "endnote");
        let primary_scope = if chapter_regions.iter().any(|r| r.scope == RegionScope::Book) {
            "book".to_string()
        } else {
            "chapter".to_string()
        };
        let note_mode_str = cl
            .policy_applied
            .get("note_mode")
            .and_then(|v| v.as_str())
            .unwrap_or("no_notes");
        let note_mode = match note_mode_str {
            "footnote_primary" => NoteMode::FootnotePrimary,
            "chapter_endnote_primary" => NoteMode::ChapterEndnotePrimary,
            "book_endnote_bound" => NoteMode::BookEndnoteBound,
            "no_notes" => NoteMode::NoNotes,
            "review_required" => NoteMode::ReviewRequired,
            _ => {
                eprintln!("  [WARNING] 未知 note_mode={note_mode_str:?}，强制回退为 no_notes");
                NoteMode::NoNotes
            }
        };
        note_mode_by_chapter.insert(chapter_id.clone(), note_mode.as_str().to_string());
        chapter_note_modes.push(ChapterNoteModeRecord {
            chapter_id: chapter_id.clone(),
            note_mode,
            region_ids: region_ids_by_chapter
                .get(&chapter_id)
                .map(|s| s.iter().cloned().collect())
                .unwrap_or_default(),
            primary_region_scope: if chapter_regions.is_empty() {
                String::new()
            } else {
                primary_scope
            },
            has_footnote_band,
            has_endnote_region,
        });

        let chapter_book_type = cl
            .policy_applied
            .get("book_type")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        if !chapter_book_type.is_empty() {
            book_type = chapter_book_type.to_string();
        }

        for page in &cl.body_pages {
            let page_no = page.page_no;
            if page_no <= 0 || body_seen_pages.contains(&page_no) {
                continue;
            }
            body_seen_pages.insert(page_no);
            body_page_records.push(PagePartitionRecord {
                page_no,
                target_pdf_page: page_no,
                page_role: fnm_core::types::PageRole::Body,
                confidence: 1.0,
                reason: if page.split_reason.is_empty() {
                    "module_projection".to_string()
                } else {
                    page.split_reason.clone()
                },
                section_hint: String::new(),
                has_note_heading: false,
                note_scan_summary: serde_json::Value::Null,
            });
        }
    }

    body_page_records.sort_by_key(|r| r.page_no);
    chapter_records.sort_by(|a, b| {
        let cmp = a.start_page.cmp(&b.start_page);
        if cmp == std::cmp::Ordering::Equal {
            a.chapter_id.cmp(&b.chapter_id)
        } else {
            cmp
        }
    });
    chapter_note_modes.sort_by(|a, b| a.chapter_id.cmp(&b.chapter_id));
    note_items.sort_by(|a, b| {
        let cmp = a.page_no.cmp(&b.page_no);
        if cmp == std::cmp::Ordering::Equal {
            a.note_item_id.cmp(&b.note_item_id)
        } else {
            cmp
        }
    });
    region_records.sort_by(|a, b| {
        let cmp = a.page_start.cmp(&b.page_start);
        if cmp == std::cmp::Ordering::Equal {
            a.region_id.cmp(&b.region_id)
        } else {
            cmp
        }
    });

    // chapter_layers 当前没暴露 region_summary / item_summary 聚合字段——
    // 这些在 Python 端由 build_chapter_layers 顶层产出,Rust 端目前留空。
    let summary = Phase2Summary::default();

    let phase2 = Phase2Structure {
        pages: body_page_records,
        heading_candidates: Vec::new(),
        chapters: chapter_records,
        section_heads: Vec::new(),
        note_regions: region_records,
        note_items,
        chapter_note_modes,
        summary,
    };

    (phase2, note_mode_by_chapter, book_type)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_layers() {
        let layers = ChapterLayers::default();
        let (phase2, note_mode_by_id, book_type) = phase2_from_chapter_layers(&layers);
        assert!(phase2.chapters.is_empty());
        assert!(note_mode_by_id.is_empty());
        assert_eq!(book_type, "no_notes");
    }
}

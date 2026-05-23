//! ←→ Python `note_linking.py:_phase2_from_chapter_layers`
//!
//! internal materialization helper：只返回 link matching 所需的最小数据，
//! 不输出退化的 Phase1/2 facts（pages / chapters / heading_candidates / section_heads）。

use fnm_core::records::{ChapterNoteModeRecord, NoteItemRecord, NoteRegionRecord};
use fnm_core::types::{NoteKind, NoteMode, RegionScope};
use fnm_phase2::chapter_split::ChapterLayers;
use std::collections::{HashMap, HashSet};

/// phase2_rebuild 的最小输出——仅包含 link matching 所需数据。
#[derive(Debug, Clone, Default)]
pub struct Phase2BuildOutput {
    pub note_regions: Vec<NoteRegionRecord>,
    pub note_items: Vec<NoteItemRecord>,
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    pub note_mode_by_chapter: HashMap<String, String>,
    pub book_type: String,
}

/// 将 ChapterLayers 重建为 Phase2 的 note 数据。
///
/// ←→ Python `_phase2_from_chapter_layers`
///
/// 注意：Python 的 ChapterLayers.chapters 等价于 Rust 的 `chapter_layers.chapter_layers`
/// (Vec<ChapterLayer>)，里面才有 policy_applied / body_pages / footnote_items / endnote_items /
/// endnote_regions。`chapter_layers.chapters` 在 Rust 端只保存薄 ChapterRecord (7 字段)。
///
/// 本函数只返回 note_regions / note_items / chapter_note_modes。Phase1/2 的 pages /
/// chapters / heading_candidates / section_heads 必须由 caller 透传原始版本，不使用本函数输出。
pub fn phase2_from_chapter_layers(chapter_layers: &ChapterLayers) -> Phase2BuildOutput {
    // 注：原 `chapter_policy_by_id` 索引已删——仅供 hot loop 内 `let _chapter_mode`
    // 读取后丢弃用，是 hot loop 内每 region/item ×2 次无意义 HashMap 查询。
    // 章级 note_mode 直接来自 chapter_layers.chapter_layers[].policy_applied，
    // 在下方装配 ChapterNoteModeRecord 时直接读，不需要预索引。

    // CLAUDE.md §12 第 3、4 条：
    //   - 禁止广播：章级 note_mode 不参与个体 entity 的 note_kind 决定。
    //   - 上下游隔离：直接消费上游已枚举化的 row.note_kind（Footnote/Endnote），不再走
    //     String 中转 + if/else 重新解释——后者会把未来新增变体静默降级为 Footnote。
    let mut region_records: Vec<NoteRegionRecord> = Vec::new();
    for row in &chapter_layers.regions {
        region_records.push(NoteRegionRecord {
            region_id: row.region_id.clone(),
            chapter_id: row.chapter_id.clone(),
            page_start: row.page_start,
            page_end: row.page_end,
            pages: row.pages.clone(),
            note_kind: row.note_kind,
            scope: row.scope,
            source: row.source,
            heading_text: row.heading_text.clone(),
            start_reason: row.start_reason.clone(),
            end_reason: row.end_reason.clone(),
            region_marker_alignment_ok: row.region_marker_alignment_ok,
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
        let marker_type = if row.marker_type.is_empty() {
            match row.note_kind {
                NoteKind::Footnote => "footnote_marker".to_string(),
                NoteKind::Endnote => "numeric".to_string(),
                NoteKind::Unknown => "unknown".to_string(),
            }
        } else {
            row.marker_type.clone()
        };
        note_items.push(NoteItemRecord {
            note_item_id: row.note_item_id.clone(),
            region_id: row.region_id.clone(),
            chapter_id,
            page_no: row.page_no,
            marker: row.marker.clone(),
            marker_type,
            text: row.text.clone(),
            source: row.source.clone(),
            source_page_label: row.source_page_label.clone(),
            is_reconstructed: row.is_reconstructed,
            review_required: row.review_required,
            note_kind: row.note_kind,
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
    let mut chapter_note_modes: Vec<ChapterNoteModeRecord> = Vec::new();
    let mut book_type = "no_notes".to_string();

    for cl in &chapter_layers.chapter_layers {
        let chapter_id = cl.chapter_id.clone();

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
    }

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

    Phase2BuildOutput {
        note_regions: region_records,
        note_items,
        chapter_note_modes,
        note_mode_by_chapter,
        book_type,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_layers() {
        let layers = ChapterLayers::default();
        let output = phase2_from_chapter_layers(&layers);
        assert!(output.note_regions.is_empty());
        assert!(output.note_items.is_empty());
        assert!(output.chapter_note_modes.is_empty());
        assert!(output.note_mode_by_chapter.is_empty());
        assert_eq!(output.book_type, "no_notes");
    }
}

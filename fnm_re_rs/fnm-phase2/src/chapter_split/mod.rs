//! ←→ FNM_RE/modules/chapter_split.py
//! 章节层聚合：消费 regions + items，按 chapter 聚合 ChapterLayer。

pub mod endnote_project;
pub mod gate;
pub mod overrides_apply;
pub mod synth_markers;

use fnm_core::records::{
    ChapterNoteModeRecord, ChapterRecord, NoteItemRecord, NoteRegionRecord, PagePartitionRecord,
};
use fnm_core::types::NoteMode;
use std::collections::HashMap;

/// ChapterLayer：单章的完整聚合数据。
#[derive(Debug, Clone)]
pub struct ChapterLayer {
    pub chapter_id: String,
    pub title: String,
    pub start_page: i64,
    pub end_page: i64,
    pub body_pages: Vec<BodyPageLayer>,
    pub footnote_items: Vec<NoteItemRecord>,
    pub endnote_items: Vec<NoteItemRecord>,
    pub endnote_regions: Vec<NoteRegionRecord>,
    pub note_mode: NoteMode,
    pub marker_count: i64,
}

/// Body page 层。
#[derive(Debug, Clone, Default)]
pub struct BodyPageLayer {
    pub page_no: i64,
    pub text: String,
    pub split_reason: String,
    pub source_role: String,
}

/// ChapterLayers 输出。
#[derive(Debug, Clone, Default)]
pub struct ChapterLayers {
    pub chapters: Vec<ChapterRecord>,
    pub regions: Vec<NoteRegionRecord>,
    pub note_items: Vec<NoteItemRecord>,
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    pub chapter_layers: Vec<ChapterLayer>,
    pub gate_report: serde_json::Value,
}

/// 构建 chapter layers。对齐 Python `build_chapter_layers()`。
pub fn build_chapter_layers(
    chapters: &[ChapterRecord],
    note_regions: &[NoteRegionRecord],
    note_items: &[NoteItemRecord],
    page_partitions: &[PagePartitionRecord],
    raw_pages: &[fnm_phase1::input::RawPage],
) -> ChapterLayers {
    let page_role_by_no: HashMap<i64, &str> = page_partitions
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str()))
        .collect();
    let raw_page_by_no: HashMap<i64, &fnm_phase1::input::RawPage> =
        raw_pages.iter().map(|p| (p.book_page, p)).collect();

    let mut region_by_chapter: HashMap<&str, Vec<&NoteRegionRecord>> = HashMap::new();
    for r in note_regions {
        region_by_chapter.entry(&r.chapter_id).or_default().push(r);
    }
    let mut item_by_chapter: HashMap<&str, Vec<&NoteItemRecord>> = HashMap::new();
    for item in note_items {
        item_by_chapter
            .entry(&item.chapter_id)
            .or_default()
            .push(item);
    }

    // 推导 note_mode
    let mut mode_by_chapter: HashMap<String, NoteMode> = HashMap::new();
    for ch in chapters {
        let has_footnote = item_by_chapter
            .get(ch.chapter_id.as_str())
            .map(|items| {
                items
                    .iter()
                    .any(|i| i.note_kind == fnm_core::types::NoteKind::Footnote)
            })
            .unwrap_or(false);
        let has_endnote = item_by_chapter
            .get(ch.chapter_id.as_str())
            .map(|items| {
                items
                    .iter()
                    .any(|i| i.note_kind == fnm_core::types::NoteKind::Endnote)
            })
            .unwrap_or(false);
        let mode = match (has_footnote, has_endnote) {
            (true, false) => NoteMode::FootnotePrimary,
            (false, true) => NoteMode::ChapterEndnotePrimary,
            (true, true) => NoteMode::ReviewRequired,
            (false, false) => NoteMode::NoNotes,
        };
        mode_by_chapter.insert(ch.chapter_id.clone(), mode);
    }

    // endnote region 优先覆盖 footnote_primary → chapter_endnote_primary
    for region in note_regions {
        if region.note_kind != fnm_core::types::NoteKind::Endnote {
            continue;
        }
        let cid = &region.chapter_id;
        if let Some(mode) = mode_by_chapter.get(cid) {
            if *mode == NoteMode::FootnotePrimary {
                let fn_count = item_by_chapter
                    .get(cid.as_str())
                    .map(|items| {
                        items
                            .iter()
                            .filter(|i| i.note_kind == fnm_core::types::NoteKind::Footnote)
                            .count()
                    })
                    .unwrap_or(0);
                let en_count = item_by_chapter
                    .get(cid.as_str())
                    .map(|items| {
                        items
                            .iter()
                            .filter(|i| i.note_kind == fnm_core::types::NoteKind::Endnote)
                            .count()
                    })
                    .unwrap_or(0);
                if fn_count > en_count && region.heading_text.is_empty() {
                    continue;
                }
                mode_by_chapter.insert(cid.clone(), NoteMode::ChapterEndnotePrimary);
            }
        }
    }

    // 构建 ChapterLayer
    let mut chapter_layers = Vec::new();
    let mut chapter_note_modes = Vec::new();

    for ch in chapters {
        let chapter_id = &ch.chapter_id;
        let mode = mode_by_chapter
            .get(chapter_id)
            .copied()
            .unwrap_or(NoteMode::NoNotes);

        let body_pages: Vec<BodyPageLayer> = ch
            .pages
            .iter()
            .filter(|&&page_no| {
                page_role_by_no
                    .get(&page_no)
                    .is_some_and(|r| *r == "body" || *r == "front_matter")
            })
            .map(|&page_no| {
                let text = raw_page_by_no
                    .get(&page_no)
                    .map(|p| {
                        fnm_core::text::page_markdown_text(
                            &serde_json::to_value(p).unwrap_or_default(),
                        )
                    })
                    .unwrap_or_default();
                BodyPageLayer {
                    page_no,
                    text,
                    split_reason: "body_page".into(),
                    source_role: page_role_by_no.get(&page_no).unwrap_or(&"").to_string(),
                }
            })
            .collect();

        let items = item_by_chapter.get(chapter_id.as_str());
        let footnote_items: Vec<NoteItemRecord> = items
            .map(|is| {
                is.iter()
                    .filter(|i| i.note_kind == fnm_core::types::NoteKind::Footnote)
                    .map(|i| (*i).clone())
                    .collect()
            })
            .unwrap_or_default();
        let endnote_items: Vec<NoteItemRecord> = items
            .map(|is| {
                is.iter()
                    .filter(|i| i.note_kind == fnm_core::types::NoteKind::Endnote)
                    .map(|i| (*i).clone())
                    .collect()
            })
            .unwrap_or_default();
        let endnote_regions: Vec<NoteRegionRecord> = region_by_chapter
            .get(chapter_id.as_str())
            .map(|rs| {
                rs.iter()
                    .filter(|r| r.note_kind == fnm_core::types::NoteKind::Endnote)
                    .map(|r| (*r).clone())
                    .collect()
            })
            .unwrap_or_default();

        let region_ids: Vec<String> = region_by_chapter
            .get(chapter_id.as_str())
            .map(|rs| rs.iter().map(|r| r.region_id.clone()).collect())
            .unwrap_or_default();

        let marker_count = endnote_items.len() as i64;

        chapter_layers.push(ChapterLayer {
            chapter_id: chapter_id.clone(),
            title: ch.title.clone(),
            start_page: ch.start_page,
            end_page: ch.end_page,
            body_pages,
            footnote_items,
            endnote_items,
            endnote_regions,
            note_mode: mode,
            marker_count,
        });

        chapter_note_modes.push(ChapterNoteModeRecord {
            chapter_id: chapter_id.clone(),
            note_mode: mode,
            region_ids,
            primary_region_scope: "chapter".into(),
            has_footnote_band: mode == NoteMode::FootnotePrimary,
            has_endnote_region: mode == NoteMode::ChapterEndnotePrimary,
        });
    }

    let gate_report = gate::build_gate_report(&chapter_layers, &chapter_note_modes);

    ChapterLayers {
        chapters: chapters.to_vec(),
        regions: note_regions.to_vec(),
        note_items: note_items.to_vec(),
        chapter_note_modes,
        chapter_layers,
        gate_report,
    }
}

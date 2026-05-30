//! ←→ FNM_RE/modules/chapter_split.py
//! 章节层聚合：消费 regions + items，按 chapter 聚合 ChapterLayer。

pub mod endnote_project;
pub mod gate;
pub mod overrides_apply;
pub mod structure_model;
pub mod synth_markers;

use fnm_core::records::{
    ChapterNoteModeRecord, ChapterRecord, NoteItemRecord, NoteRegionRecord, PagePartitionRecord,
};
use fnm_core::types::{NoteMode, RegionScope};
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
    /// 策略应用记录（如 note_mode、book_type 推导过程）。
    pub policy_applied: HashMap<String, serde_json::Value>,
}

impl Default for ChapterLayer {
    fn default() -> Self {
        ChapterLayer {
            chapter_id: String::new(),
            title: String::new(),
            start_page: 0,
            end_page: 0,
            body_pages: Vec::new(),
            footnote_items: Vec::new(),
            endnote_items: Vec::new(),
            endnote_regions: Vec::new(),
            note_mode: NoteMode::NoNotes,
            marker_count: 0,
            policy_applied: HashMap::new(),
        }
    }
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
    //
    // CLAUDE.md §12 第 2 条「分支条件穷尽且互斥」：4 分支显式列出，
    // 每个分支写 reason，不让 else 静默吞掉边界情况。每个升级动作的 reason
    // 都记到 `mode_override_reason`，最终写入 ChapterLayer.policy_applied 供审计。
    let mut mode_override_reason: HashMap<String, &'static str> = HashMap::new();
    for region in note_regions {
        if region.note_kind != fnm_core::types::NoteKind::Endnote {
            continue;
        }
        let cid = &region.chapter_id;
        let current_mode = match mode_by_chapter.get(cid) {
            Some(m) => *m,
            None => continue,
        };
        if current_mode != NoteMode::FootnotePrimary {
            continue;
        }
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
        let fn_dominant = fn_count > en_count;
        let has_heading = !region.heading_text.is_empty();
        let (next_mode, reason) = match (fn_dominant, has_heading) {
            // (1) footnote 占多 + 无 endnote heading → 弱信号，不升级
            (true, false) => (
                NoteMode::FootnotePrimary,
                "kept_fn_primary_weak_endnote_signal",
            ),
            // (2) footnote 占多 + 有 endnote heading → 强信号，升级
            (true, true) => (
                NoteMode::ChapterEndnotePrimary,
                "promoted_by_endnote_heading_despite_fn_dominant",
            ),
            // (3) endnote >= footnote + 无 heading → 数量证据升级
            (false, false) => (
                NoteMode::ChapterEndnotePrimary,
                "promoted_by_endnote_count_no_heading",
            ),
            // (4) endnote >= footnote + 有 heading → 强信号 + 数量都支持，升级
            (false, true) => (
                NoteMode::ChapterEndnotePrimary,
                "promoted_by_endnote_heading_and_count",
            ),
        };
        if next_mode != current_mode {
            mode_by_chapter.insert(cid.clone(), next_mode);
        }
        mode_override_reason.insert(cid.clone(), reason);
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
                        let page_value = match serde_json::to_value(p) {
                            Ok(v) => v,
                            Err(e) => {
                                tracing::warn!("RawPage 序列化失败 (page_no={}): {}", page_no, e);
                                serde_json::Value::Null
                            }
                        };
                        fnm_core::text::page_markdown_text(&page_value)
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
        let primary_region_scope = region_by_chapter
            .get(chapter_id.as_str())
            .map(|rs| {
                if rs.iter().any(|region| region.scope == RegionScope::Book) {
                    "book"
                } else {
                    "chapter"
                }
            })
            .unwrap_or("chapter");

        // 在 items/regions 被 move 之前计算事实字段
        let actual_has_footnote = !footnote_items.is_empty()
            || region_by_chapter
                .get(chapter_id.as_str())
                .map(|rs| {
                    rs.iter()
                        .any(|r| r.note_kind == fnm_core::types::NoteKind::Footnote)
                })
                .unwrap_or(false);
        let actual_has_endnote = !endnote_items.is_empty()
            || region_by_chapter
                .get(chapter_id.as_str())
                .map(|rs| {
                    rs.iter()
                        .any(|r| r.note_kind == fnm_core::types::NoteKind::Endnote)
                })
                .unwrap_or(false);

        let marker_count = endnote_items.len() as i64;

        let mut policy_applied = HashMap::new();
        policy_applied.insert(
            "note_mode".to_string(),
            serde_json::Value::String(mode.as_str().to_string()),
        );
        if let Some(reason) = mode_override_reason.get(chapter_id.as_str()) {
            policy_applied.insert(
                "mode_override_reason".to_string(),
                serde_json::Value::String((*reason).to_string()),
            );
        }

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
            policy_applied,
        });

        chapter_note_modes.push(ChapterNoteModeRecord {
            chapter_id: chapter_id.clone(),
            note_mode: mode,
            region_ids,
            primary_region_scope: primary_region_scope.into(),
            has_footnote_band: actual_has_footnote,
            has_endnote_region: actual_has_endnote,
        });
    }

    let gate_report = gate::build_gate_report(&chapter_layers, &chapter_note_modes);

    // 推算 book_type 并广播到每个 ChapterLayer.policy_applied——
    // 下游 phase3 chapter_contracts 依赖该字段判断 endnote_only 分支。
    // 此前 phase3 读 `policy_applied["book_type"]` 永远拿到 None
    // （phantom key），导致 `if book_type == "endnote_only"` 永远 false（silently-wrong）。
    let book_type = crate::book_structure::infer_book_type(&chapter_note_modes);
    let book_type_value = serde_json::Value::String(book_type.as_str().to_string());
    for layer in &mut chapter_layers {
        layer
            .policy_applied
            .insert("book_type".to_string(), book_type_value.clone());
    }

    ChapterLayers {
        chapters: chapters.to_vec(),
        regions: note_regions.to_vec(),
        note_items: note_items.to_vec(),
        chapter_note_modes,
        chapter_layers,
        gate_report,
    }
}

/// 下游阶段重建 chapter layer 的展示结构，但保留 Phase 2 已决定的 mode 事实。
///
/// ←→ Python `build_chapter_layers()` 输出被后续 module 直接消费的路径。
pub fn build_chapter_layers_from_authoritative_phase2(
    chapters: &[ChapterRecord],
    note_regions: &[NoteRegionRecord],
    note_items: &[NoteItemRecord],
    page_partitions: &[PagePartitionRecord],
    raw_pages: &[fnm_phase1::input::RawPage],
    authoritative_modes: &[ChapterNoteModeRecord],
) -> ChapterLayers {
    let mut layers = build_chapter_layers(
        chapters,
        note_regions,
        note_items,
        page_partitions,
        raw_pages,
    );
    if authoritative_modes.is_empty() {
        return layers;
    }

    let mode_by_chapter: HashMap<&str, &ChapterNoteModeRecord> = authoritative_modes
        .iter()
        .map(|mode| (mode.chapter_id.as_str(), mode))
        .collect();
    for layer in &mut layers.chapter_layers {
        if let Some(mode) = mode_by_chapter.get(layer.chapter_id.as_str()) {
            layer.note_mode = mode.note_mode;
            layer.policy_applied.insert(
                "note_mode".to_string(),
                serde_json::Value::String(mode.note_mode.as_str().to_string()),
            );
        }
    }

    layers.chapter_note_modes = authoritative_modes.to_vec();
    layers.gate_report = gate::build_gate_report(&layers.chapter_layers, authoritative_modes);

    let book_type = crate::book_structure::infer_book_type(authoritative_modes);
    let book_type_value = serde_json::Value::String(book_type.as_str().to_string());
    for layer in &mut layers.chapter_layers {
        layer
            .policy_applied
            .insert("book_type".to_string(), book_type_value.clone());
    }

    layers
}

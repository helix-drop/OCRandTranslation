//! ←→ Python `FNM_RE/stages/units.py`（~868 行）
//!
//! 翻译单元构建：body pages → 段落分段 → 切块 → 注入 ref → 翻译单元。
//!
//! # 子模块
//!
//! - `page_split` — 7 个文本切分 helper（P4.6）
//! - `endnote_lookup` — endnote 区起始页映射（P4.7）
//! - `body_pages` — 章级 body pages 结构化（P4.7）
//! - `ref_inject` — ref 物化 + 注入（P4.8）

pub mod body_pages;
pub mod endnote_lookup;
pub mod page_split;
pub mod ref_inject;

use fnm_core::records::{
    ChapterRecord, NoteItemRecord, NoteRegionRecord, Phase4Structure, TranslationUnitRecord,
};
use fnm_core::refs::frozen_note_ref;
use fnm_phase1::input::RawPage;
use std::collections::HashMap;

use self::body_pages::build_structured_body_pages_for_chapter;
use self::endnote_lookup::chapter_endnote_start_page_map;
use self::ref_inject::{materialize_refs_for_chapter, ref_materialization_context};
use crate::segments::chunking::chunk_body_page_segments;
use crate::segments::segment_paragraphs_from_body_pages;

/// ←→ Python `build_translation_units` (units.py:690-868)
///
/// 构建翻译单元列表：body chunks + footnote/endnote items。
///
/// # 参数
///
/// - `phase4` — Phase 4 结构数据
/// - `raw_pages` — 原始页面数据
/// - `max_body_chars` — body chunk 最大字符数（默认 6000）
///
/// # 返回
///
/// `(Vec<TranslationUnitRecord>, serde_json::Value)` — 翻译单元列表 + summary
pub fn build_translation_units(
    phase4: &Phase4Structure,
    raw_pages: &[RawPage],
    max_body_chars: i64,
) -> (Vec<TranslationUnitRecord>, serde_json::Value) {
    let max_body_chars = if max_body_chars > 0 {
        max_body_chars
    } else {
        6000
    };

    // 构建索引
    let raw_page_by_no: HashMap<i64, &RawPage> = raw_pages
        .iter()
        .filter(|p| p.book_page > 0)
        .map(|p| (p.book_page, p))
        .collect();

    let page_role_by_no: HashMap<i64, String> = phase4
        .pages
        .iter()
        .filter(|p| p.page_no > 0)
        .map(|p| (p.page_no, p.page_role.as_str().to_string()))
        .collect();

    let chapter_order: HashMap<String, usize> = phase4
        .chapters
        .iter()
        .enumerate()
        .filter(|(_, c)| !c.chapter_id.trim().is_empty())
        .map(|(idx, c)| (c.chapter_id.trim().to_string(), idx + 1))
        .collect();

    let chapter_by_id: HashMap<String, &ChapterRecord> = phase4
        .chapters
        .iter()
        .filter(|c| !c.chapter_id.trim().is_empty())
        .map(|c| (c.chapter_id.trim().to_string(), c))
        .collect();

    let note_region_by_id: HashMap<String, &NoteRegionRecord> = phase4
        .note_regions
        .iter()
        .filter(|r| !r.region_id.trim().is_empty())
        .map(|r| (r.region_id.trim().to_string(), r))
        .collect();

    let chapter_endnote_start_map = chapter_endnote_start_page_map(&phase4.note_regions);
    let ref_ctx = ref_materialization_context(&phase4.body_anchors, &phase4.effective_note_links);

    let mut units: Vec<TranslationUnitRecord> = Vec::new();
    let mut body_unit_counts: HashMap<String, usize> = HashMap::new();
    let mut empty_body_chapter_count = 0;
    let mut ref_injected_count = 0;
    let mut ref_synthetic_skipped = 0;

    // 遍历 chapters，生成 body units
    for (chapter_index, chapter) in phase4.chapters.iter().enumerate() {
        let chapter_id = chapter.chapter_id.trim().to_string();
        if chapter_id.is_empty() {
            continue;
        }

        let next_chapter = phase4.chapters.get(chapter_index + 1);
        let note_start_page = chapter_endnote_start_map
            .get(&chapter_id)
            .copied()
            .unwrap_or(0);

        let body_pages = build_structured_body_pages_for_chapter(
            chapter,
            &raw_page_by_no,
            &page_role_by_no,
            note_start_page,
            next_chapter,
        );

        if body_pages.is_empty() {
            empty_body_chapter_count += 1;
            body_unit_counts.insert(chapter_id, 0);
            continue;
        }

        // 注入 ref
        let (injected_pages, inject_summary) = materialize_refs_for_chapter(
            &chapter_id,
            &body_pages,
            &phase4.effective_note_links,
            &ref_ctx,
        );
        ref_injected_count += inject_summary.injected_link_count;
        ref_synthetic_skipped += inject_summary.synthetic_skipped_count;

        // 构建 body pages JSON
        let frozen_body_pages: Vec<serde_json::Value> = injected_pages
            .iter()
            .map(|p| serde_json::json!({"page_no": p.page_no, "text": p.text}))
            .collect();
        let obsidian_body_pages = frozen_body_pages.clone();
        let section_title = chapter.title.clone();

        // 分段
        let page_segments = segment_paragraphs_from_body_pages(
            &frozen_body_pages,
            &obsidian_body_pages,
            &section_title,
        );

        // 切块
        let chunks = chunk_body_page_segments(&page_segments, max_body_chars);
        body_unit_counts.insert(chapter_id.clone(), chunks.len());

        // 生成 body units
        for (chunk_idx, chunk) in chunks.iter().enumerate() {
            let page_start = chunk
                .get("page_start")
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            let page_end = chunk
                .get("page_end")
                .and_then(|v| v.as_i64())
                .unwrap_or(page_start);
            let char_count = chunk
                .get("char_count")
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            let source_text = chunk
                .get("source_text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let page_segments_value = chunk
                .get("page_segments")
                .cloned()
                .unwrap_or(serde_json::Value::Array(vec![]));

            units.push(TranslationUnitRecord {
                unit_id: format!("body-{}-{:04}", chapter_id, chunk_idx + 1),
                kind: "body".to_string(),
                owner_kind: "chapter".to_string(),
                owner_id: chapter_id.clone(),
                section_id: chapter_id.clone(),
                section_title: chapter.title.clone(),
                section_start_page: chapter.start_page,
                section_end_page: chapter.end_page,
                note_id: String::new(),
                page_start,
                page_end,
                char_count,
                source_text,
                translated_text: String::new(),
                status: "pending".to_string(),
                error_msg: String::new(),
                target_ref: String::new(),
                page_segments: serde_json::from_value(page_segments_value).unwrap_or_default(),
                ..Default::default()
            });
        }
    }

    // 生成 note units (footnote + endnote)
    let ordered_note_items =
        sort_note_items(&phase4.note_items, &chapter_order, &note_region_by_id);

    for item in ordered_note_items {
        let chapter_id = item.chapter_id.trim().to_string();
        let note_item_id = item.note_item_id.trim().to_string();
        if chapter_id.is_empty() || note_item_id.is_empty() {
            continue;
        }

        let chapter = match chapter_by_id.get(&chapter_id) {
            Some(c) => (*c).clone(),
            None => ChapterRecord {
                chapter_id: chapter_id.clone(),
                title: chapter_id.clone(),
                start_page: 0,
                end_page: 0,
                pages: vec![],
                boundary_state: fnm_core::types::BoundaryState::Ready,
                source: fnm_core::types::ChapterSource::Fallback,
            },
        };

        let region = note_region_by_id.get(item.region_id.trim()).cloned();

        let note_kind = region.map(|r| r.note_kind.as_str()).unwrap_or("");
        if note_kind != "footnote" && note_kind != "endnote" {
            continue;
        }

        let source_text = item.text.clone();
        let start_page = item.page_no;

        let owner_id = if !item.region_id.trim().is_empty() {
            item.region_id.trim().to_string()
        } else {
            format!("{}-note-region", chapter_id)
        };

        units.push(TranslationUnitRecord {
            unit_id: format!("{}-{}-{}", note_kind, chapter_id, note_item_id),
            kind: note_kind.to_string(),
            owner_kind: "note_region".to_string(),
            owner_id,
            section_id: chapter_id.clone(),
            section_title: if !chapter.title.is_empty() {
                chapter.title.clone()
            } else {
                chapter_id.clone()
            },
            section_start_page: chapter.start_page,
            section_end_page: if chapter.end_page > 0 {
                chapter.end_page
            } else {
                chapter.start_page
            },
            note_id: note_item_id.clone(),
            page_start: start_page,
            page_end: start_page,
            char_count: source_text.len() as i64,
            source_text,
            translated_text: String::new(),
            status: "pending".to_string(),
            error_msg: String::new(),
            target_ref: frozen_note_ref(&note_item_id),
            page_segments: vec![],
            ..Default::default()
        });
    }

    // 全 units 排序：(chapter_order, body_first, page_start, unit_id)
    units.sort_by(|a, b| {
        let order_a = chapter_order
            .get(a.section_id.trim())
            .copied()
            .unwrap_or(1_000_000);
        let order_b = chapter_order
            .get(b.section_id.trim())
            .copied()
            .unwrap_or(1_000_000);
        let kind_a = if a.kind == "body" { 0 } else { 1 };
        let kind_b = if b.kind == "body" { 0 } else { 1 };
        order_a
            .cmp(&order_b)
            .then(kind_a.cmp(&kind_b))
            .then(a.page_start.cmp(&b.page_start))
            .then(a.unit_id.cmp(&b.unit_id))
    });

    // 构建 summary
    let body_unit_count = units.iter().filter(|u| u.kind == "body").count();
    let note_unit_count = units.len() - body_unit_count;

    let summary = serde_json::json!({
        "unit_planning_summary": {
            "body_unit_count": body_unit_count,
            "note_unit_count": note_unit_count,
            "chapter_unit_counts": body_unit_counts,
            "empty_body_chapter_count": empty_body_chapter_count,
            "max_body_chars": max_body_chars,
        },
        "ref_materialization_summary": {
            "matched_link_count": ref_ctx.matched_link_count,
            "injected_link_count": ref_injected_count,
            "synthetic_skipped_count": ref_synthetic_skipped,
            "ignored_skipped_count": ref_ctx.ignored_skipped_count,
            "ambiguous_skipped_count": ref_ctx.ambiguous_skipped_count,
            "conflict_anchor_count": ref_ctx.conflict_anchor_ids.len(),
        },
    });

    (units, summary)
}

/// 排序 note items：(chapter_order, region.page_start, page_no, note_kind, note_item_id)。
fn sort_note_items<'a>(
    note_items: &'a [NoteItemRecord],
    chapter_order: &HashMap<String, usize>,
    note_region_by_id: &HashMap<String, &NoteRegionRecord>,
) -> Vec<&'a NoteItemRecord> {
    let mut items: Vec<&NoteItemRecord> = note_items.iter().collect();
    items.sort_by(|a, b| {
        let order_a = chapter_order
            .get(a.chapter_id.trim())
            .copied()
            .unwrap_or(1_000_000);
        let order_b = chapter_order
            .get(b.chapter_id.trim())
            .copied()
            .unwrap_or(1_000_000);
        let region_a = note_region_by_id.get(a.region_id.trim());
        let region_b = note_region_by_id.get(b.region_id.trim());
        let region_page_a = region_a.map(|r| r.page_start).unwrap_or(1_000_000);
        let region_page_b = region_b.map(|r| r.page_start).unwrap_or(1_000_000);
        let kind_a = region_a.map(|r| r.note_kind.as_str()).unwrap_or("");
        let kind_b = region_b.map(|r| r.note_kind.as_str()).unwrap_or("");
        order_a
            .cmp(&order_b)
            .then(region_page_a.cmp(&region_page_b))
            .then(a.page_no.cmp(&b.page_no))
            .then(kind_a.cmp(kind_b))
            .then(a.note_item_id.cmp(&b.note_item_id))
    });
    items
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::PagePartitionRecord;
    use fnm_core::types::{BoundaryState, ChapterSource, PageRole};
    use body_pages::StructuredBodyPage;

    fn make_chapter(chapter_id: &str, title: &str, start: i64, end: i64) -> ChapterRecord {
        ChapterRecord {
            chapter_id: chapter_id.to_string(),
            title: title.to_string(),
            start_page: start,
            end_page: end,
            pages: (start..=end).collect(),
            boundary_state: BoundaryState::Ready,
            source: ChapterSource::Fallback,
        }
    }

    fn make_raw_page(book_page: i64, markdown: &str) -> RawPage {
        RawPage {
            book_page,
            markdown: markdown.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn test_build_translation_units_empty() {
        let phase4 = Phase4Structure::default();
        let raw_pages = vec![];
        let (units, summary) = build_translation_units(&phase4, &raw_pages, 6000);
        assert!(units.is_empty());
        assert_eq!(summary["unit_planning_summary"]["body_unit_count"], 0);
    }

    #[test]
    fn test_build_translation_units_basic() {
        let phase4 = Phase4Structure {
            chapters: vec![make_chapter("ch1", "Chapter 1", 1, 2)],
            pages: vec![
                PagePartitionRecord {
                    page_no: 1,
                    target_pdf_page: 1,
                    page_role: PageRole::Body,
                    confidence: 1.0,
                    reason: String::new(),
                    section_hint: String::new(),
                    has_note_heading: false,
                    note_scan_summary: serde_json::Value::Null,
                },
                PagePartitionRecord {
                    page_no: 2,
                    target_pdf_page: 2,
                    page_role: PageRole::Body,
                    confidence: 1.0,
                    reason: String::new(),
                    section_hint: String::new(),
                    has_note_heading: false,
                    note_scan_summary: serde_json::Value::Null,
                },
            ],
            ..Default::default()
        };
        let raw_pages = vec![
            make_raw_page(1, "# Chapter 1\n\nBody text page 1."),
            make_raw_page(2, "Body text page 2."),
        ];
        let (units, summary) = build_translation_units(&phase4, &raw_pages, 6000);
        assert!(!units.is_empty());
        assert!(units.iter().any(|u| u.kind == "body"));
    }
}

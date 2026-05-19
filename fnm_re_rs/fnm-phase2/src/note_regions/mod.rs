//! ←→ FNM_RE/stages/note_regions.py (825 行)
//! 注释区识别：footnote band + endnote region 构建 + post-body promotion + merge + rebind。
//!
//! 10 子模块编排：
//! - chapter_lookup: 章节归属查找
//! - footnote_band: 脚注 band 区域
//! - illustration_list: 插图列表页识别
//! - endnote_candidate: endnote 候选页判定
//! - endnote_regions_raw: 原始 endnote region 构建
//! - post_body_promote: post-body promotion + fnBlock 重分类
//! - merge_adjacent: 相邻 region 合并
//! - book_regions: book-scope 重绑定
//! - normalize: region_id 规范化

pub mod book_regions;
pub mod chapter_lookup;
pub mod endnote_candidate;
pub mod endnote_regions_raw;
pub mod footnote_band;
pub mod illustration_list;
pub mod merge_adjacent;
pub mod normalize;
pub mod post_body_promote;

use fnm_core::records::{ChapterRecord, HeadingCandidate, NoteRegionRecord, PagePartitionRecord};
use fnm_phase1::input::RawPage;
use std::collections::{HashMap, HashSet};

use crate::note_regions::post_body_promote::reclassify_post_body_fnblocks;

/// 注释区识别入口。
/// ←→ Python `build_note_regions`
pub fn build_note_regions(
    phase1_chapters: &[ChapterRecord],
    pages: &[RawPage],
    page_partitions: &[PagePartitionRecord],
    post_body_titles: &HashSet<String>,
    heading_candidates: &[HeadingCandidate],
) -> Vec<NoteRegionRecord> {
    // 构建 page_by_no 和 page_role_by_no
    let page_by_no: HashMap<i64, &RawPage> = pages.iter().map(|p| (p.book_page, p)).collect();

    let mut page_role_by_no: HashMap<i64, String> = page_partitions
        .iter()
        .map(|pp| (pp.page_no, pp.page_role.as_str().to_string()))
        .collect();
    // 补全 pages 中存在的、但 page_partitions 缺失的 page_no（用 "unknown" 兜底）
    for &pn in page_by_no.keys() {
        page_role_by_no
            .entry(pn)
            .or_insert_with(|| "unknown".into());
    }

    // 重分类 post_body fnBlocks（返回被重分类的页号集合）
    // ←→ Python `_reclassify_post_body_fnblocks_as_endnote`
    let reclassified_pages = reclassify_post_body_fnblocks(
        phase1_chapters,
        &mut page_role_by_no,
        &page_by_no,
        post_body_titles,
    );
    // Python 端用 `note_scan["has_reclassified_endnotes"]=True` 标记页面，下游
    // `_is_endnote_candidate_page` 通过读取此标记把这些页认作 endnote candidate。
    // Rust 端通过 reclassified_pages set 等价传递：把这些页面的 page_role 从
    // "body" 提升到 "note"（满足 is_endnote_candidate_page 的 page_role=="note" 分支）。
    for &pn in &reclassified_pages {
        page_role_by_no.insert(pn, "note".into());
    }

    // 1. Footnote band regions
    let (footnote_regions, chapters_with_footnote_band) =
        footnote_band::build_footnote_band_regions_excluding(
            phase1_chapters,
            pages,
            &reclassified_pages,
        );

    // 2. Endnote regions raw
    let sorted_page_nos: Vec<i64> = {
        let mut pns: Vec<i64> = pages.iter().map(|p| p.book_page).collect();
        pns.sort_unstable();
        pns
    };
    let endnote_regions = endnote_regions_raw::build_endnote_regions_raw(
        phase1_chapters,
        &page_role_by_no,
        &page_by_no,
        &chapters_with_footnote_band,
        &sorted_page_nos,
    );

    // 3. Merge adjacent endnote regions
    let (endnote_regions, _merge_count) =
        merge_adjacent::merge_adjacent_endnote_regions(endnote_regions);

    // 4. Promote post-body regions
    let (endnote_regions, _promoted_count) =
        post_body_promote::promote_post_body_regions(endnote_regions, phase1_chapters);

    // 4b. Endnote chapter explorer（←→ Python `explore_endnote_chapter_regions`）
    // 当前 stub（20% 完成度），接入但不期望实际修改 regions。
    // 待完整实现后，此处结果应参与后序 rebind/章节重绑定。
    let _explorations =
        crate::endnote_chapter_explorer::explore_endnote_chapter_regions(pages, phase1_chapters);

    // 5. Rebind book regions
    let (endnote_regions, _rebind_count) =
        book_regions::rebind_book_regions(endnote_regions, phase1_chapters, heading_candidates);

    // 6. Normalize region IDs and combine
    let mut all_regions = Vec::new();
    all_regions.extend(footnote_regions);
    all_regions.extend(endnote_regions);
    normalize::normalize_region_ids(all_regions)
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::note_marker::{first_notes_heading, is_notes_heading_line};
    use fnm_core::types::{
        BoundaryState, ChapterSource, NoteKind, PageRole, RegionScope, RegionSource,
    };

    fn make_chapter(id: &str, start: i64, end: i64) -> ChapterRecord {
        ChapterRecord {
            chapter_id: id.into(),
            title: id.into(),
            start_page: start,
            end_page: end,
            pages: (start..=end).collect(),
            source: ChapterSource::VisualToc,
            boundary_state: BoundaryState::Ready,
        }
    }

    #[test]
    fn heading_detection() {
        assert!(is_notes_heading_line("## Notes"));
    }

    #[test]
    fn heading_detection_endnotes() {
        let page = RawPage {
            book_page: 1,
            markdown: "## Endnotes\n\n1. First endnote.".into(),
            ..Default::default()
        };
        assert!(!first_notes_heading(&page.markdown).is_empty());
    }

    #[test]
    fn no_heading() {
        let page = RawPage {
            book_page: 1,
            markdown: "## Chapter 1\nBody text.".into(),
            ..Default::default()
        };
        assert!(first_notes_heading(&page.markdown).is_empty());
    }

    #[test]
    fn endnote_candidate_from_note_scan() {
        let chapters = vec![make_chapter("ch-1", 1, 3)];
        let pages = vec![RawPage {
            book_page: 2,
            markdown: "1. Endnote text".into(),
            note_scan: Some(serde_json::json!({"page_kind": "endnote_collection"})),
            ..Default::default()
        }];
        let pp = vec![PagePartitionRecord {
            page_no: 1,
            target_pdf_page: 1,
            page_role: PageRole::Body,
            confidence: 1.0,
            reason: "body".into(),
            section_hint: "".into(),
            has_note_heading: false,
            note_scan_summary: serde_json::json!({}),
        }];
        let regions = build_note_regions(&chapters, &pages, &pp, &HashSet::new(), &[]);
        assert!(!regions.is_empty());
        assert_eq!(regions[0].note_kind, NoteKind::Endnote);
    }

    #[test]
    fn explicit_notes_heading_region() {
        let chapters = vec![make_chapter("ch-1", 1, 2)];
        let pages = vec![RawPage {
            book_page: 2,
            markdown: "## Notes\n1. Note text.".into(),
            ..Default::default()
        }];
        let pp = vec![PagePartitionRecord {
            page_no: 2,
            target_pdf_page: 2,
            page_role: PageRole::Body,
            confidence: 1.0,
            reason: "body".into(),
            section_hint: "".into(),
            has_note_heading: false,
            note_scan_summary: serde_json::json!({}),
        }];
        let regions = build_note_regions(&chapters, &pages, &pp, &HashSet::new(), &[]);
        assert!(!regions.is_empty());
        assert_eq!(regions[0].note_kind, NoteKind::Endnote);
        assert!(!regions[0].heading_text.is_empty());
    }

    #[test]
    fn empty_input() {
        let regions = build_note_regions(&[], &[], &[], &HashSet::new(), &[]);
        assert!(regions.is_empty());
    }

    #[test]
    fn footnote_band_empty_no_footnotes() {
        let chapters = vec![make_chapter("ch-1", 1, 3)];
        let pages = vec![RawPage {
            book_page: 1,
            markdown: "body text".into(),
            ..Default::default()
        }];
        let (regions, _) = footnote_band::build_footnote_band_regions(&chapters, &pages);
        assert!(regions.is_empty());
    }

    #[test]
    fn merge_adjacent_same_scope() {
        let r1 = NoteRegionRecord {
            region_id: "r1".into(),
            chapter_id: "ch-1".into(),
            page_start: 1,
            page_end: 3,
            pages: vec![1, 2, 3],
            note_kind: NoteKind::Endnote,
            scope: RegionScope::Chapter,
            source: RegionSource::HeadingScan,
            heading_text: "Notes".into(),
            start_reason: "notes_heading".into(),
            end_reason: "contiguous_break".into(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: "1".into(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        };
        let r2 = NoteRegionRecord {
            region_id: "r2".into(),
            chapter_id: "ch-1".into(),
            page_start: 4,
            page_end: 6,
            pages: vec![4, 5, 6],
            note_kind: NoteKind::Endnote,
            scope: RegionScope::Chapter,
            source: RegionSource::HeadingScan,
            heading_text: String::new(),
            start_reason: "candidate_page".into(),
            end_reason: "document_end".into(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: "4".into(),
            region_first_note_item_marker: String::new(),
            review_required: true,
        };
        let (merged, count) = merge_adjacent::merge_adjacent_endnote_regions(vec![r1, r2]);
        assert_eq!(count, 1);
        assert_eq!(merged.len(), 1);
        assert_eq!(merged[0].page_start, 1);
        assert_eq!(merged[0].page_end, 6);
        assert_eq!(merged[0].pages.len(), 6);
    }

    #[test]
    fn merge_adjacent_different_scope_no_merge() {
        let r1 = NoteRegionRecord {
            region_id: "r1".into(),
            chapter_id: "ch-1".into(),
            page_start: 1,
            page_end: 3,
            pages: vec![1, 2, 3],
            note_kind: NoteKind::Endnote,
            scope: RegionScope::Chapter,
            source: RegionSource::HeadingScan,
            heading_text: String::new(),
            start_reason: "candidate_page".into(),
            end_reason: "contiguous_break".into(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: String::new(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        };
        let r2 = NoteRegionRecord {
            region_id: "r2".into(),
            chapter_id: String::new(),
            page_start: 4,
            page_end: 6,
            pages: vec![4, 5, 6],
            note_kind: NoteKind::Endnote,
            scope: RegionScope::Book,
            source: RegionSource::HeadingScan,
            heading_text: String::new(),
            start_reason: "candidate_page".into(),
            end_reason: "document_end".into(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: String::new(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        };
        let (merged, count) = merge_adjacent::merge_adjacent_endnote_regions(vec![r1, r2]);
        assert_eq!(count, 0);
        assert_eq!(merged.len(), 2);
    }

    #[test]
    fn rebind_missing_chapter_id() {
        let chapters = vec![make_chapter("ch-1", 1, 3)];
        let region = NoteRegionRecord {
            region_id: "r1".into(),
            chapter_id: String::new(),
            page_start: 2,
            page_end: 4,
            pages: vec![2, 3, 4],
            note_kind: NoteKind::Endnote,
            scope: RegionScope::Book,
            source: RegionSource::HeadingScan,
            heading_text: String::new(),
            start_reason: "candidate_page".into(),
            end_reason: "document_end".into(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: String::new(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        };
        let (rebound, count) = book_regions::rebind_book_regions(vec![region], &chapters, &[]);
        assert_eq!(count, 1);
        assert_eq!(rebound[0].chapter_id, "ch-1");
    }

    #[test]
    fn normalize_ids_format() {
        let region = NoteRegionRecord {
            region_id: "old".into(),
            chapter_id: "ch-1".into(),
            page_start: 1,
            page_end: 2,
            pages: vec![1, 2],
            note_kind: NoteKind::Endnote,
            scope: RegionScope::Chapter,
            source: RegionSource::HeadingScan,
            heading_text: String::new(),
            start_reason: "notes_heading".into(),
            end_reason: "document_end".into(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: String::new(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        };
        let normalized = normalize::normalize_region_ids(vec![region]);
        assert_eq!(normalized.len(), 1);
        assert!(normalized[0].region_id.starts_with("nr-en-ch-"));
    }

    #[test]
    fn promote_post_body_region() {
        let chapters = vec![make_chapter("ch-1", 1, 5)];
        let region = NoteRegionRecord {
            region_id: "r1".into(),
            chapter_id: "ch-1".into(),
            page_start: 10,
            page_end: 12,
            pages: vec![10, 11, 12],
            note_kind: NoteKind::Endnote,
            scope: RegionScope::Chapter,
            source: RegionSource::HeadingScan,
            heading_text: String::new(),
            start_reason: "candidate_page".into(),
            end_reason: "document_end".into(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: String::new(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        };
        let (promoted, count) =
            post_body_promote::promote_post_body_regions(vec![region], &chapters);
        assert_eq!(count, 1);
        assert_eq!(promoted[0].scope, RegionScope::Book);
    }

    #[test]
    fn chapter_endnote_start_page_map_basic() {
        let region = NoteRegionRecord {
            region_id: "r1".into(),
            chapter_id: "ch-1".into(),
            page_start: 100,
            page_end: 105,
            pages: vec![100, 101, 102, 103, 104, 105],
            note_kind: NoteKind::Endnote,
            scope: RegionScope::Chapter,
            source: RegionSource::HeadingScan,
            heading_text: String::new(),
            start_reason: "notes_heading".into(),
            end_reason: "document_end".into(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: String::new(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        };
        let map = book_regions::chapter_endnote_start_page_map(&[region]);
        assert_eq!(map.get("ch-1"), Some(&100));
    }
}

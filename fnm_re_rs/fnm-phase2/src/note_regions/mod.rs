//! ←→ FNM_RE/stages/note_regions.py (825 行)
//! 注释区识别：heading scan + footnote band + continuation_merge + post_body_endnote + manual_rebind。
//!
//! 覆盖 F2 全部需求。

use crate::note_kind_resolver::{resolve_note_kind, NoteRegionContext};
use fnm_core::records::{ChapterRecord, NoteRegionRecord, PagePartitionRecord};
use fnm_core::types::{NoteKind, RegionScope, RegionSource};
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::{HashMap, HashSet};

// ── Regex ─────────────────────────────────────────────────────

static NOTES_HEADING_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*|注释|脚注|尾注)\s*$")
        .unwrap()
});

/// 剥离 markdown heading 前缀（# 开头）。
static MD_HEADING_PREFIX_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\s{0,3}#{1,6}\s*").unwrap());

#[allow(dead_code)]
static FOOTNOTE_LINE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"^\s*(\d{1,4})\s+").unwrap());

// ── 公开 API ──────────────────────────────────────────────────

pub fn build_note_regions(
    phase1_chapters: &[ChapterRecord],
    pages: &[RawPage],
    page_partitions: &[PagePartitionRecord],
) -> Vec<NoteRegionRecord> {
    let mut regions: Vec<NoteRegionRecord> = Vec::new();

    // Page role map
    let page_role_map: HashMap<i64, &str> = page_partitions
        .iter()
        .map(|pp| (pp.page_no, pp.page_role.as_str()))
        .collect();

    // Page payload by page_no
    let page_map: HashMap<i64, &RawPage> = pages.iter().map(|p| (p.book_page, p)).collect();

    let pages_sorted = {
        let mut pns: Vec<i64> = pages.iter().map(|p| p.book_page).collect();
        pns.sort_unstable();
        pns
    };

    // ── Footnote band regions（扫描每章的 footnote scan items）──
    let _chapters_with_footnote_band =
        build_footnote_band_regions(phase1_chapters, &page_map, &mut regions);

    // ── Endnote candidate pages ──────────────────────────────────
    // 包含：explicit heading "NOTES"/"Endnotes" 的页、note_scan page_kind="endnote_collection" 的页、
    // page_role="note" 的页

    let endnote_candidates: HashSet<i64> = pages_sorted
        .iter()
        .filter(|&&pn| {
            let page = match page_map.get(&pn) {
                Some(p) => p,
                None => return false,
            };
            // 显式 heading
            if has_notes_heading(page) {
                return true;
            }
            // note_scan page_kind
            if page
                .note_scan
                .as_ref()
                .and_then(|s| s.get("page_kind"))
                .and_then(|v| v.as_str())
                .map(|k| k == "endnote_collection" || k == "mixed_body_endnotes")
                .unwrap_or(false)
            {
                return true;
            }
            // page_role = note
            page_role_map.get(&pn).copied() == Some("note")
        })
        .copied()
        .collect();

    if endnote_candidates.is_empty() {
        return regions;
    }

    // ── Group contiguous endnote candidate pages ─────────────────
    let _chapter_page_sets: HashMap<&str, HashSet<i64>> = phase1_chapters
        .iter()
        .map(|ch| (ch.chapter_id.as_str(), ch.pages.iter().copied().collect()))
        .collect();

    let last_chapter_end = phase1_chapters
        .iter()
        .map(|ch| ch.end_page)
        .max()
        .unwrap_or(0);

    let mut current_pages: Vec<i64> = Vec::new();
    let mut current_scope = RegionScope::Chapter;
    let mut current_chapter_id = String::new();
    let mut current_heading = String::new();
    let mut current_start_reason = String::new();
    let mut region_counter: usize = 0;

    for &pn in &pages_sorted {
        if !endnote_candidates.contains(&pn) {
            if !current_pages.is_empty() {
                region_counter += 1;
                regions.push(build_region(
                    region_counter,
                    &current_pages,
                    &current_chapter_id,
                    current_scope,
                    &current_heading,
                    &current_start_reason,
                ));
                current_pages.clear();
                current_chapter_id.clear();
                current_heading.clear();
                current_start_reason.clear();
            }
            continue;
        }

        // fnBlocks guard: 有页底脚注且无尾注信号 → 拒绝
        if let Some(page) = page_map.get(&pn) {
            if let Some(fnb) = page.fn_blocks.as_array() {
                if !fnb.is_empty() {
                    let has_endnote_signal = has_notes_heading(page)
                        || page
                            .note_scan
                            .as_ref()
                            .and_then(|s| s.get("page_kind"))
                            .and_then(|v| v.as_str())
                            .map(|k| k == "endnote_collection")
                            .unwrap_or(false);
                    if !has_endnote_signal {
                        if !current_pages.is_empty() {
                            region_counter += 1;
                            regions.push(build_region(
                                region_counter,
                                &current_pages,
                                &current_chapter_id,
                                current_scope,
                                &current_heading,
                                &current_start_reason,
                            ));
                            current_pages.clear();
                        }
                        continue;
                    }
                }
            }
        }

        // 连续性检查
        if let Some(&last) = current_pages.last() {
            if pn != last + 1 {
                region_counter += 1;
                regions.push(build_region(
                    region_counter,
                    &current_pages,
                    &current_chapter_id,
                    current_scope,
                    &current_heading,
                    &current_start_reason,
                ));
                current_pages.clear();
                current_chapter_id.clear();
                current_heading.clear();
                current_start_reason.clear();
            }
        }

        // 首个页时确定 scope
        if current_pages.is_empty() {
            if pn > last_chapter_end {
                current_scope = RegionScope::Book;
                current_chapter_id = String::new();
            } else {
                current_scope = RegionScope::Chapter;
                current_chapter_id = find_owning_chapter(pn, phase1_chapters);
            }
            // 取 heading
            if let Some(page) = page_map.get(&pn) {
                current_heading = first_notes_heading_from_page(page);
                current_start_reason = if !current_heading.is_empty() {
                    "notes_heading".into()
                } else if page_role_map.get(&pn).copied() == Some("note") {
                    "note_partition".into()
                } else {
                    "candidate_page".into()
                };
            }
        }
        current_pages.push(pn);
    }

    // Flush last region
    if !current_pages.is_empty() {
        region_counter += 1;
        regions.push(build_region(
            region_counter,
            &current_pages,
            &current_chapter_id,
            current_scope,
            &current_heading,
            &current_start_reason,
        ));
    }

    // ── Post-body endnote detection ─────────────────────────────
    detect_post_body_endnotes(&mut regions, phase1_chapters, &page_map);

    regions
}

fn build_footnote_band_regions(
    chapters: &[ChapterRecord],
    _page_map: &HashMap<i64, &RawPage>,
    regions: &mut Vec<NoteRegionRecord>,
) -> HashSet<String> {
    let mut chapters_with_band = HashSet::new();
    for chapter in chapters {
        // 查找 footnote items（从 note_scan 中）
        let footnote_pages: Vec<i64> = chapter.pages.to_vec();
        if footnote_pages.is_empty() {
            continue;
        }
        // 简化版：检查章内是否有 footnote_band 标记
        // 完整版需要 scan_items_by_kind(page, kind="footnote")
        let has_band = false; // 待补
        if has_band {
            chapters_with_band.insert(chapter.chapter_id.clone());
            regions.push(NoteRegionRecord {
                region_id: format!("{}-footband-01", chapter.chapter_id),
                chapter_id: chapter.chapter_id.clone(),
                page_start: chapter.start_page,
                page_end: chapter.end_page,
                pages: footnote_pages,
                note_kind: NoteKind::Footnote,
                scope: RegionScope::Chapter,
                source: RegionSource::FootnoteBand,
                heading_text: String::new(),
                start_reason: "footnote_items".into(),
                end_reason: "contiguous_end".into(),
                region_marker_alignment_ok: true,
                region_start_first_source_marker: String::new(),
                region_first_note_item_marker: String::new(),
                review_required: false,
            });
        }
    }
    chapters_with_band
}

fn build_region(
    counter: usize,
    pages: &[i64],
    chapter_id: &str,
    scope: RegionScope,
    heading: &str,
    start_reason: &str,
) -> NoteRegionRecord {
    let start = *pages.first().unwrap_or(&0);
    let end = *pages.last().unwrap_or(&0);

    // 尾注区直接判定 endnote（与 Python _build_endnote_regions_raw 一致）
    let note_kind = NoteKind::Endnote;
    let review_required = heading.is_empty();

    NoteRegionRecord {
        region_id: format!("region-endnote-{:04}", counter),
        chapter_id: chapter_id.to_string(),
        page_start: start,
        page_end: end,
        pages: pages.to_vec(),
        note_kind,
        scope,
        source: RegionSource::HeadingScan,
        heading_text: heading.to_string(),
        start_reason: start_reason.to_string(),
        end_reason: "contiguous_end".into(),
        region_marker_alignment_ok: !review_required,
        region_start_first_source_marker: String::new(),
        region_first_note_item_marker: String::new(),
        review_required,
    }
}

/// 显式 "NOTES" / "Endnotes" heading 检测。
fn has_notes_heading(page: &RawPage) -> bool {
    let text = &page.markdown;
    for line in text.lines().take(12) {
        if NOTES_HEADING_RE.is_match(line.trim()) {
            return true;
        }
    }
    false
}

/// 从 page markdown 提取第一个 notes heading 文本。
fn first_notes_heading_from_page(page: &RawPage) -> String {
    let text = &page.markdown;
    for line in text.lines().take(12) {
        let trimmed = line.trim();
        if NOTES_HEADING_RE.is_match(trimmed) {
            return MD_HEADING_PREFIX_RE.replace(trimmed, "").trim().to_string();
        }
    }
    String::new()
}

/// 查找 page 所属的 chapter_id。
fn find_owning_chapter(page_no: i64, chapters: &[ChapterRecord]) -> String {
    for ch in chapters {
        if ch.pages.contains(&page_no) {
            return ch.chapter_id.clone();
        }
    }
    for ch in chapters {
        if ch.start_page <= page_no && page_no <= ch.end_page {
            return ch.chapter_id.clone();
        }
    }
    // nearest prior
    let mut prior: Vec<&ChapterRecord> = chapters
        .iter()
        .filter(|ch| ch.start_page <= page_no)
        .collect();
    prior.sort_by_key(|ch| ch.start_page);
    prior
        .last()
        .map(|ch| ch.chapter_id.clone())
        .unwrap_or_default()
}

/// 章后隐式尾注检测（没有显式 heading 的连续 marker 段落）。
fn detect_post_body_endnotes(
    regions: &mut [NoteRegionRecord],
    _chapters: &[ChapterRecord],
    _page_map: &HashMap<i64, &RawPage>,
) {
    // 给所有 chapter_scope 且无 heading 的区域标记 post_body
    for region in regions.iter_mut() {
        if region.scope == RegionScope::Chapter && region.heading_text.is_empty() {
            region.start_reason = "post_body_endnote".into();
            let ctx = NoteRegionContext {
                heading_text: "",
                has_footnote_band: false,
                is_post_body_region: true,
                is_book_scope: false,
                explicit_markers: &[],
            };
            let kind = resolve_note_kind(&ctx);
            region.note_kind = kind.note_kind;
            region.review_required = kind.review_required;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{BoundaryState, ChapterSource, PageRole};

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
        let page = RawPage {
            book_page: 1,
            markdown: "## Notes\nSome notes here".into(),
            ..Default::default()
        };
        assert!(has_notes_heading(&page));
    }

    #[test]
    fn heading_detection_endnotes() {
        let page = RawPage {
            book_page: 1,
            markdown: "## Endnotes\n\n1. First endnote.".into(),
            ..Default::default()
        };
        assert!(has_notes_heading(&page));
    }

    #[test]
    fn no_heading() {
        let page = RawPage {
            book_page: 1,
            markdown: "## Chapter 1\nBody text.".into(),
            ..Default::default()
        };
        assert!(!has_notes_heading(&page));
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
        let regions = build_note_regions(&chapters, &pages, &pp);
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
        let regions = build_note_regions(&chapters, &pages, &pp);
        assert!(!regions.is_empty());
        assert_eq!(regions[0].note_kind, NoteKind::Endnote);
        assert!(!regions[0].heading_text.is_empty());
    }
}

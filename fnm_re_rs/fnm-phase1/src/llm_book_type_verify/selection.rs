//! ←→ FNM_RE/modules/llm_book_type_verify.py
//! 5 维分层选页（R1-R6）+ BookStructureProfile 提取。

use crate::book_note_type::BookNoteProfile;
use fnm_core::records::{ChapterNoteModeRecord, ChapterRecord, Phase1Structure};
use std::collections::{HashMap, HashSet};

// ── 常量 ────────────────────────────────────────────────────────

pub const VERIFY_MAX_TOKENS: i64 = 4096;
pub const VERIFY_TOTAL_CAP_RATIO: f64 = 0.10;
pub const VERIFY_TOTAL_CAP_ABSOLUTE: usize = 40;
pub const CHAPTER_END_SAMPLE_RATE: f64 = 0.30;
pub const CHAPTER_END_MIN_REGIONS: usize = 3;
pub const CHAPTER_END_MAX_REGIONS: usize = 15;
pub const FALSE_POSITIVE_ITEM_THRESHOLD: i64 = 50;
pub const FALSE_POSITIVE_MAX_PAGES: usize = 5;
pub const BODY_BASELINE_MIN: usize = 2;
pub const LLM_TIMEOUT_SECS: u64 = 180;

// ── 数据结构 ────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct EndnoteRegionInfo {
    pub chapter_id: String,
    pub scope: String,
    pub start_page: i64,
    pub end_page: i64,
}

impl EndnoteRegionInfo {
    pub fn page_count(&self) -> i64 {
        std::cmp::max(1, self.end_page - self.start_page + 1)
    }
}

#[derive(Debug, Clone, Default)]
pub struct BookStructureProfile {
    pub total_pages: i64,
    pub chapter_count: usize,
    pub chapter_modes: HashMap<String, String>,
    pub endnote_regions: Vec<EndnoteRegionInfo>,
    pub chapter_endnote_count: usize,
    pub book_endnote_count: usize,
    pub endnote_item_count: i64,
    pub footnote_item_count: i64,
    pub toc_has_notes_entry: bool,
    pub toc_notes_printed_page: Option<i64>,
    pub mode_types: HashSet<String>,
    pub chapters: Vec<ChapterRecord>,
}

// ── 章节查找 ───────────────────────────────────────────────────

/// ←→ Python `_chapter_by_page`
pub fn chapter_by_page(structure: &Phase1Structure) -> HashMap<i64, String> {
    let mut mapped: HashMap<i64, String> = HashMap::new();
    for chapter in &structure.chapters {
        if chapter.chapter_id.is_empty() {
            continue;
        }
        for &page_no in &chapter.pages {
            if page_no > 0 {
                mapped.insert(page_no, chapter.chapter_id.clone());
            }
        }
        if chapter.start_page > 0 && chapter.end_page >= chapter.start_page {
            for page_no in chapter.start_page..=chapter.end_page {
                mapped.entry(page_no).or_insert(chapter.chapter_id.clone());
            }
        }
    }
    mapped
}

/// ←→ Python `_nearest_prior_chapter_id`
pub fn nearest_prior_chapter_id(structure: &Phase1Structure, page_no: i64) -> String {
    let mut candidates: Vec<&ChapterRecord> = structure
        .chapters
        .iter()
        .filter(|ch| !ch.chapter_id.is_empty() && ch.start_page <= page_no)
        .collect();
    if candidates.is_empty() {
        return String::new();
    }
    candidates.sort_by_key(|ch| (ch.start_page, ch.end_page));
    candidates.last().unwrap().chapter_id.clone()
}

// ── Profile 提取 ───────────────────────────────────────────────

/// ←→ Python `_extract_book_structure_profile`
pub fn extract_book_structure_profile(
    structure: &Phase1Structure,
    book_note_profile: &BookNoteProfile,
    chapter_note_modes: &[ChapterNoteModeRecord],
) -> BookStructureProfile {
    let total_pages = structure.pages.len() as i64;

    // chapter_modes
    let mut chapter_modes: HashMap<String, String> = HashMap::new();
    let mut mode_types: HashSet<String> = HashSet::new();
    for m in chapter_note_modes {
        let mode_str = m.note_mode.as_str().to_string();
        if !mode_str.is_empty() {
            chapter_modes.insert(m.chapter_id.clone(), mode_str.clone());
            mode_types.insert(mode_str);
        }
    }

    // 简化：直接从 chapter_note_modes 推断 endnote regions
    // Python 端从 toc_structure.endnote_regions 读，但 Rust 当前未在 Phase1Structure
    // 里保存独立 endnote_regions 列表——用 chapter_endnote_primary 章的边界近似。
    let mut endnote_regions: Vec<EndnoteRegionInfo> = Vec::new();
    let mut chapter_endnote_count = 0usize;
    let mut book_endnote_count = 0usize;
    for ch in &structure.chapters {
        let mode = chapter_modes
            .get(&ch.chapter_id)
            .cloned()
            .unwrap_or_default();
        if mode == "chapter_endnote_primary" {
            // chapter scope endnote region：章尾几页
            let end_band_start = std::cmp::max(ch.start_page, ch.end_page - 2);
            endnote_regions.push(EndnoteRegionInfo {
                chapter_id: ch.chapter_id.clone(),
                scope: "chapter".into(),
                start_page: end_band_start,
                end_page: ch.end_page,
            });
            chapter_endnote_count += 1;
        } else if mode == "book_endnote_bound" {
            // book scope endnote region：把 chapter 的 endnote 计为 book scope
            endnote_regions.push(EndnoteRegionInfo {
                chapter_id: ch.chapter_id.clone(),
                scope: "book".into(),
                start_page: ch.end_page,
                end_page: ch.end_page,
            });
            book_endnote_count += 1;
        }
    }

    BookStructureProfile {
        total_pages,
        chapter_count: structure.chapters.len(),
        chapter_modes,
        endnote_regions,
        chapter_endnote_count,
        book_endnote_count,
        endnote_item_count: book_note_profile
            .evidence
            .get("endnote_item_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        footnote_item_count: book_note_profile
            .evidence
            .get("footnote_item_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        toc_has_notes_entry: book_note_profile
            .evidence
            .get("toc_has_notes_entry")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
        toc_notes_printed_page: book_note_profile
            .evidence
            .get("toc_notes_printed_page")
            .and_then(|v| v.as_i64()),
        mode_types,
        chapters: structure.chapters.clone(),
    }
}

// ── R1: TOC 页 ────────────────────────────────────────────────

/// ←→ Python `_resolve_toc_notes_page` + `_toc_page`
pub fn toc_page(profile: &BookStructureProfile, _toc_pages: &[i64]) -> i64 {
    if let Some(toc_page) = profile.toc_notes_printed_page {
        if toc_page > 0 {
            return toc_page;
        }
    }
    if let Some(first) = profile
        .chapters
        .iter()
        .filter(|ch| ch.start_page > 0)
        .map(|ch| ch.start_page)
        .min()
    {
        return std::cmp::max(1, first - 1);
    }
    1
}

// ── R2: body baseline pages ─────────────────────────────────────

/// ←→ Python `_body_baseline_pages`
pub fn body_baseline_pages(profile: &BookStructureProfile) -> Vec<i64> {
    let mut pages: Vec<i64> = Vec::new();
    let mut sorted_modes: Vec<&String> = profile.mode_types.iter().collect();
    sorted_modes.sort();
    for mode in sorted_modes {
        let candidates: Vec<&ChapterRecord> = profile
            .chapters
            .iter()
            .filter(|ch| {
                profile
                    .chapter_modes
                    .get(&ch.chapter_id)
                    .map(|m| m == mode)
                    .unwrap_or(false)
            })
            .collect();
        if candidates.is_empty() {
            continue;
        }
        let ch = candidates[candidates.len() / 2];
        let mid = ch.start_page + (ch.end_page - ch.start_page) / 2;
        pages.push(std::cmp::max(1, mid));
    }
    while pages.len() < BODY_BASELINE_MIN && !profile.chapters.is_empty() {
        let idx = pages.len() % profile.chapters.len();
        let ch = &profile.chapters[idx];
        let mid = ch.start_page + (ch.end_page - ch.start_page) / 2;
        let safe_mid = std::cmp::max(1, mid);
        if !pages.contains(&safe_mid) {
            pages.push(safe_mid);
        } else {
            break;
        }
    }
    pages.into_iter().take(BODY_BASELINE_MIN).collect()
}

// ── R3: chapter_end_boundary_pages ──────────────────────────────

/// ←→ Python `_chapter_end_boundary_pages`
pub fn chapter_end_boundary_pages(profile: &BookStructureProfile) -> Vec<i64> {
    let chapter_regions: Vec<&EndnoteRegionInfo> = profile
        .endnote_regions
        .iter()
        .filter(|r| r.scope == "chapter")
        .collect();
    if chapter_regions.is_empty() {
        return Vec::new();
    }
    let n = chapter_regions.len();
    let sample_n = std::cmp::max(
        CHAPTER_END_MIN_REGIONS,
        std::cmp::min(
            CHAPTER_END_MAX_REGIONS,
            ((n as f64 * CHAPTER_END_SAMPLE_RATE).ceil()) as usize,
        ),
    );
    let sampled: Vec<&EndnoteRegionInfo> = if n <= sample_n {
        chapter_regions.clone()
    } else {
        let step = (n - 1) as f64 / std::cmp::max(1, sample_n - 1) as f64;
        (0..sample_n)
            .map(|i| {
                let idx = (step * i as f64) as usize;
                chapter_regions[idx.min(n - 1)]
            })
            .collect()
    };
    let mut pages: Vec<i64> = Vec::new();
    for region in sampled {
        let last_body = region.start_page - 1;
        if last_body >= 1 {
            pages.push(last_body);
        }
        pages.push(region.start_page);
        if region.page_count() >= 3 {
            pages.push(region.start_page + region.page_count() / 2);
        }
    }
    pages
}

// ── R4: book_notes_region_pages ─────────────────────────────────

/// ←→ Python `_book_notes_region_pages`
pub fn book_notes_region_pages(profile: &BookStructureProfile) -> Vec<i64> {
    let book_regions: Vec<&EndnoteRegionInfo> = profile
        .endnote_regions
        .iter()
        .filter(|r| r.scope == "book")
        .collect();
    if book_regions.is_empty() {
        return Vec::new();
    }
    let mut all_pages: HashSet<i64> = HashSet::new();
    for r in &book_regions {
        for pn in r.start_page..=r.end_page {
            all_pages.insert(pn);
        }
    }
    if all_pages.is_empty() {
        return Vec::new();
    }
    let mut sorted: Vec<i64> = all_pages.into_iter().collect();
    sorted.sort_unstable();
    let first = sorted[0];
    let last = *sorted.last().unwrap();
    let mut pages = vec![std::cmp::max(1, first - 1), first];
    if last - first >= 5 {
        pages.push(first + (last - first) / 2);
    }
    pages
}

// ── R5: toc_offset_verification_pages ───────────────────────────

/// ←→ Python `_toc_offset_verification_pages`
pub fn toc_offset_verification_pages(profile: &BookStructureProfile) -> Vec<i64> {
    if !profile.toc_has_notes_entry || profile.toc_notes_printed_page.is_none() {
        return Vec::new();
    }
    let toc_claimed = profile.toc_notes_printed_page.unwrap();
    let pipeline_first = profile.endnote_regions.iter().map(|r| r.start_page).min();
    let Some(pf) = pipeline_first else {
        return if toc_claimed > 0 {
            vec![toc_claimed]
        } else {
            Vec::new()
        };
    };
    vec![toc_claimed, pf - 2, pf, pf + 5]
        .into_iter()
        .filter(|&p| p > 0)
        .collect()
}

// ── R6: false_positive_check_pages ──────────────────────────────

/// ←→ Python `_false_positive_check_pages`
pub fn false_positive_check_pages(profile: &BookStructureProfile) -> Vec<i64> {
    if profile.endnote_item_count <= 0
        || profile.endnote_item_count >= FALSE_POSITIVE_ITEM_THRESHOLD
    {
        return Vec::new();
    }
    let mut pages: HashSet<i64> = HashSet::new();
    for r in &profile.endnote_regions {
        pages.insert(r.start_page);
        pages.insert(r.end_page);
    }
    let mut sorted: Vec<i64> = pages.into_iter().collect();
    sorted.sort_unstable();
    sorted.into_iter().take(FALSE_POSITIVE_MAX_PAGES).collect()
}

// ── 主选页入口（R1-R6 合并 + 上限） ─────────────────────────────

/// ←→ Python `select_verification_pages`
pub fn select_verification_pages(profile: &BookStructureProfile) -> Vec<i64> {
    let mut selected: HashSet<i64> = HashSet::new();
    selected.insert(toc_page(profile, &[]));
    for p in body_baseline_pages(profile) {
        selected.insert(p);
    }
    for p in chapter_end_boundary_pages(profile) {
        selected.insert(p);
    }
    for p in book_notes_region_pages(profile) {
        selected.insert(p);
    }
    for p in toc_offset_verification_pages(profile) {
        selected.insert(p);
    }
    for p in false_positive_check_pages(profile) {
        selected.insert(p);
    }
    let mut valid: Vec<i64> = selected
        .into_iter()
        .filter(|&p| p >= 1 && p <= profile.total_pages)
        .collect();
    valid.sort_unstable();
    let cap_ratio = (profile.total_pages as f64 * VERIFY_TOTAL_CAP_RATIO) as usize;
    let cap = std::cmp::min(cap_ratio, VERIFY_TOTAL_CAP_ABSOLUTE);
    valid.into_iter().take(std::cmp::max(cap, 5)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::PagePartitionRecord;
    use fnm_core::types::{BoundaryState, ChapterSource, NoteMode, PageRole};
    use serde_json::json;

    fn mk_chapter(id: &str, start: i64, end: i64) -> ChapterRecord {
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

    fn mk_profile() -> BookStructureProfile {
        let chapters = vec![
            mk_chapter("ch-1", 1, 20),
            mk_chapter("ch-2", 21, 40),
            mk_chapter("ch-3", 41, 60),
        ];
        let mut chapter_modes = HashMap::new();
        chapter_modes.insert("ch-1".into(), "chapter_endnote_primary".into());
        chapter_modes.insert("ch-2".into(), "footnote_primary".into());
        chapter_modes.insert("ch-3".into(), "chapter_endnote_primary".into());
        let mut mode_types = HashSet::new();
        mode_types.insert("chapter_endnote_primary".into());
        mode_types.insert("footnote_primary".into());
        BookStructureProfile {
            total_pages: 60,
            chapter_count: 3,
            chapter_modes,
            endnote_regions: vec![
                EndnoteRegionInfo {
                    chapter_id: "ch-1".into(),
                    scope: "chapter".into(),
                    start_page: 18,
                    end_page: 20,
                },
                EndnoteRegionInfo {
                    chapter_id: "ch-3".into(),
                    scope: "chapter".into(),
                    start_page: 58,
                    end_page: 60,
                },
            ],
            chapter_endnote_count: 2,
            book_endnote_count: 0,
            endnote_item_count: 25,
            footnote_item_count: 5,
            toc_has_notes_entry: false,
            toc_notes_printed_page: None,
            mode_types,
            chapters,
        }
    }

    #[test]
    fn r2_body_baseline() {
        let profile = mk_profile();
        let pages = body_baseline_pages(&profile);
        assert!(pages.len() >= BODY_BASELINE_MIN);
    }

    #[test]
    fn r3_chapter_end_boundary() {
        let profile = mk_profile();
        let pages = chapter_end_boundary_pages(&profile);
        assert!(!pages.is_empty());
    }

    #[test]
    fn r4_book_notes_empty_when_no_book_scope() {
        let profile = mk_profile();
        let pages = book_notes_region_pages(&profile);
        assert!(pages.is_empty());
    }

    #[test]
    fn r5_toc_offset_empty_when_no_toc_notes() {
        let profile = mk_profile();
        assert!(toc_offset_verification_pages(&profile).is_empty());
    }

    #[test]
    fn r6_false_positive_check_below_threshold() {
        let profile = mk_profile();
        let pages = false_positive_check_pages(&profile);
        assert!(!pages.is_empty()); // 25 < 50
    }

    #[test]
    fn select_pages_caps() {
        let profile = mk_profile();
        let pages = select_verification_pages(&profile);
        assert!(!pages.is_empty());
        assert!(pages.len() <= 40);
    }

    #[test]
    fn extract_profile_basic() {
        let structure = Phase1Structure {
            chapters: vec![mk_chapter("ch-1", 1, 10)],
            pages: vec![PagePartitionRecord {
                page_no: 1,
                target_pdf_page: 1,
                page_role: PageRole::Body,
                confidence: 1.0,
                reason: String::new(),
                section_hint: String::new(),
                has_note_heading: false,
                note_scan_summary: serde_json::Value::Null,
            }],
            ..Default::default()
        };
        let book_profile = BookNoteProfile {
            book_type: "endnote_only".into(),
            chapter_modes: vec![],
            evidence: json!({}),
        };
        let modes = vec![ChapterNoteModeRecord {
            chapter_id: "ch-1".into(),
            note_mode: NoteMode::ChapterEndnotePrimary,
            region_ids: vec![],
            primary_region_scope: "chapter".into(),
            has_footnote_band: false,
            has_endnote_region: true,
        }];
        let profile = extract_book_structure_profile(&structure, &book_profile, &modes);
        assert_eq!(profile.chapter_count, 1);
        assert_eq!(profile.chapter_endnote_count, 1);
    }
}

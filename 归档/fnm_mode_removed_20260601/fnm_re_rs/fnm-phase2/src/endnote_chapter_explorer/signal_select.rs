//! 最佳信号选择 + region 边界切分。
//!
//! ←→ Python `endnote_chapter_explorer.py` 中的 `_best_page_signal` / `_split_book_region_by_chapter_boundaries`

use fnm_core::records::{HeadingCandidate, NoteRegionRecord, Phase1Structure};
use fnm_core::text::extract_page_headings;
use fnm_core::title::{chapter_title_match_key, normalize_title};
use fnm_phase1::input::RawPage;
use serde_json::Value;
use std::collections::HashMap;

use super::matching::{match_signal_to_chapter, ChapterRow, PageChapterSignal};
use super::page_signals::{toc_page_signal_candidates, yield_page_signal_candidates};

/// ←→ Python `_best_page_signal`
pub(super) fn best_page_signal(
    page_no: i64,
    page: Option<&RawPage>,
    chapters: &[ChapterRow],
    hcbp: &HashMap<i64, Vec<HeadingCandidate>>,
    endnote_explorer_hints: Option<&Value>,
) -> (Option<PageChapterSignal>, bool) {
    let toc_ranked = toc_page_signal_candidates(page_no, chapters, endnote_explorer_hints);
    let mut ranked: Vec<PageChapterSignal> = toc_ranked.clone();

    let mut page_ranked: Vec<PageChapterSignal> = Vec::new();
    for (signal_title, source, bonus) in yield_page_signal_candidates(page_no, page, hcbp) {
        if let Some(matched) = match_signal_to_chapter(&signal_title, chapters) {
            page_ranked.push(PageChapterSignal {
                chapter_id: matched.0,
                signal_title,
                source,
                score: matched.2 + bonus,
            });
        }
    }
    ranked.extend(page_ranked.clone());
    ranked.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.chapter_id.cmp(&b.chapter_id))
            .then_with(|| a.signal_title.cmp(&b.signal_title))
    });
    if ranked.is_empty() || ranked[0].score < 0.98 {
        return (None, false);
    }
    // toc_best vs page_best 冲突检查
    let toc_best = if !toc_ranked.is_empty() {
        let mut tr = toc_ranked.clone();
        tr.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| a.chapter_id.cmp(&b.chapter_id))
                .then_with(|| a.signal_title.cmp(&b.signal_title))
        });
        Some(tr.into_iter().next().unwrap())
    } else {
        None
    };
    let page_best = if !page_ranked.is_empty() {
        let mut pr = page_ranked.clone();
        pr.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| a.chapter_id.cmp(&b.chapter_id))
                .then_with(|| a.signal_title.cmp(&b.signal_title))
        });
        Some(pr.into_iter().next().unwrap())
    } else {
        None
    };
    if let (Some(tb), Some(pb)) = (&toc_best, &page_best) {
        if tb.chapter_id != pb.chapter_id && tb.score >= 1.0 && pb.score >= 1.0 {
            return (None, true);
        }
    }
    if ranked.len() >= 2
        && ranked[1].chapter_id != ranked[0].chapter_id
        && ranked[1].score >= ranked[0].score - 0.08
    {
        return (None, true);
    }
    let best = ranked.into_iter().next().unwrap();
    (Some(best), false)
}

pub(super) fn signal_region_source(
    signal: Option<&PageChapterSignal>,
    default_source: &str,
) -> String {
    match signal {
        None => default_source.to_string(),
        Some(s) if s.source == "toc_subentry" => "explorer_toc_match".into(),
        Some(_) => "explorer_signal_match".into(),
    }
}

pub(super) fn supports_shared_boundary(signal: Option<&PageChapterSignal>) -> bool {
    matches!(signal, Some(s) if s.source != "toc_subentry")
}

// ── Region split by chapter boundaries (fallback) ───────────────

/// ←→ Python `_split_book_region_by_chapter_boundaries`
pub(super) fn split_book_region_by_chapter_boundaries(
    region: &NoteRegionRecord,
    phase1: &Phase1Structure,
    page_by_no: &HashMap<i64, &RawPage>,
) -> Vec<(String, Vec<i64>)> {
    if region.pages.is_empty() {
        return Vec::new();
    }
    let mut sorted_pages: Vec<i64> = region.pages.clone();
    sorted_pages.sort_unstable();

    let mut chapter_by_title_key: HashMap<String, String> = HashMap::new();
    for ch in &phase1.chapters {
        let title = normalize_title(&ch.title);
        let key = chapter_title_match_key(&title);
        if !key.is_empty() {
            chapter_by_title_key.insert(key, ch.chapter_id.clone());
        }
    }

    let mut page_chapter: HashMap<i64, String> = HashMap::new();
    for &pn in &sorted_pages {
        let page = match page_by_no.get(&pn) {
            Some(p) => *p,
            None => continue,
        };
        let headings = extract_page_headings(&page.pruned_result);
        for heading in headings {
            let normalized = normalize_title(&heading);
            let key = chapter_title_match_key(&normalized);
            if !key.is_empty() {
                if let Some(ch_id) = chapter_by_title_key.get(&key) {
                    page_chapter.insert(pn, ch_id.clone());
                    break;
                }
            }
        }
    }

    if page_chapter.is_empty() {
        return vec![(region.chapter_id.clone(), sorted_pages)];
    }

    let mut segments: Vec<(String, Vec<i64>)> = Vec::new();
    let mut current_chapter_id = region.chapter_id.clone();
    let mut current_pages: Vec<i64> = Vec::new();

    for pn in &sorted_pages {
        let ch_id = page_chapter.get(pn).cloned();
        if let Some(new_id) = &ch_id {
            if *new_id != current_chapter_id {
                if !current_pages.is_empty() {
                    segments.push((
                        current_chapter_id.clone(),
                        std::mem::take(&mut current_pages),
                    ));
                }
                current_chapter_id = new_id.clone();
            }
        }
        if current_chapter_id.is_empty() {
            if let Some(new_id) = ch_id {
                current_chapter_id = new_id;
            }
        }
        current_pages.push(*pn);
    }

    if !current_pages.is_empty() {
        segments.push((current_chapter_id, current_pages));
    }

    if segments.len() <= 1 {
        return vec![(region.chapter_id.clone(), sorted_pages)];
    }
    segments
}

// ── Heading candidates helper (re-export for boundary_fallback) ──

pub(super) use super::page_signals::heading_candidates_by_page as build_heading_candidates_by_page;

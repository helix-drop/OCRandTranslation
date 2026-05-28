//! 主入口 + 旧 API：3 路径分配（TOC subentry / page signal / chapter boundary fallback）。
//!
//! ←→ Python `endnote_chapter_explorer.py::explore_endnote_chapter_regions`

use fnm_core::records::{ChapterRecord, HeadingCandidate, NoteRegionRecord, Phase1Structure};
use fnm_core::types::{NoteKind, RegionScope, RegionSource};
use fnm_phase1::input::RawPage;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::str::FromStr;

use super::matching::{build_chapter_rows, match_signal_to_chapter, ChapterRow};
use super::signal_select::{
    best_page_signal, build_heading_candidates_by_page, signal_region_source,
    split_book_region_by_chapter_boundaries, supports_shared_boundary,
};

fn parse_region_source(s: &str) -> RegionSource {
    RegionSource::from_str(s).unwrap_or(RegionSource::HeadingScan)
}

#[derive(Debug, Clone, Default)]
pub struct ExplorerSummary {
    pub split_count: usize,
    pub rebind_count: usize,
    pub page_signal_count: usize,
    pub toc_match_count: usize,
    pub ambiguous_page_count: usize,
    pub signal_titles_preview: Vec<String>,
    pub toc_titles_preview: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct EndnoteRegionExploration {
    pub chapter_id: String,
    pub page_start: i64,
    pub page_end: i64,
    pub source: String,
    pub confidence: f64,
}

/// 完整 Python `explore_endnote_chapter_regions`：3 路径分配 + 子条目匹配 + heading 切分。
pub fn explore_endnote_chapter_regions_full(
    regions: Vec<NoteRegionRecord>,
    phase1_chapters: &[ChapterRecord],
    phase1_heading_candidates: &[HeadingCandidate],
    page_by_no: &HashMap<i64, &RawPage>,
    endnote_explorer_hints: Option<&Value>,
) -> (Vec<NoteRegionRecord>, ExplorerSummary) {
    let phase1 = Phase1Structure {
        chapters: phase1_chapters.to_vec(),
        heading_candidates: phase1_heading_candidates.to_vec(),
        ..Default::default()
    };
    let chapters = build_chapter_rows(phase1_chapters);
    let candidates_by_page = build_heading_candidates_by_page(&phase1);

    let mut rebuilt: Vec<NoteRegionRecord> = Vec::with_capacity(regions.len());
    let mut summary = ExplorerSummary::default();

    for region in regions {
        if region.note_kind != NoteKind::Endnote
            || region.scope != RegionScope::Book
            || region.pages.is_empty()
        {
            rebuilt.push(region);
            continue;
        }

        let mut page_signals: HashMap<i64, super::matching::PageChapterSignal> = HashMap::new();
        let mut ambiguous_pages: HashSet<i64> = HashSet::new();

        for &page_no in &region.pages {
            let (signal, ambiguous) = best_page_signal(
                page_no,
                page_by_no.get(&page_no).copied(),
                &chapters,
                &candidates_by_page,
                endnote_explorer_hints,
            );
            if ambiguous {
                ambiguous_pages.insert(page_no);
                summary.ambiguous_page_count += 1;
            }
            if let Some(sig) = signal {
                if sig.source == "toc_subentry" {
                    summary.toc_match_count += 1;
                    if !summary.toc_titles_preview.contains(&sig.signal_title) {
                        summary.toc_titles_preview.push(sig.signal_title.clone());
                    }
                } else {
                    summary.page_signal_count += 1;
                    if !summary.signal_titles_preview.contains(&sig.signal_title) {
                        summary.signal_titles_preview.push(sig.signal_title.clone());
                    }
                }
                page_signals.insert(page_no, sig);
            }
        }

        if !ambiguous_pages.is_empty() {
            let distinct_chapters: HashSet<String> = page_signals
                .values()
                .map(|s| s.chapter_id.clone())
                .filter(|c| !c.is_empty())
                .collect();
            if distinct_chapters.len() == 1 {
                let mut signals: Vec<&super::matching::PageChapterSignal> =
                    page_signals.values().collect();
                signals.sort_by(|a, b| {
                    b.score
                        .partial_cmp(&a.score)
                        .unwrap_or(std::cmp::Ordering::Equal)
                        .then_with(|| a.chapter_id.cmp(&b.chapter_id))
                });
                let best_signal = signals[0].clone();
                let rebound_source =
                    signal_region_source(Some(&best_signal), region.source.as_str());
                if !best_signal.chapter_id.is_empty() && best_signal.chapter_id != region.chapter_id
                {
                    summary.rebind_count += 1;
                }
                let mut r = region.clone();
                r.chapter_id = best_signal.chapter_id;
                r.heading_text = if !best_signal.signal_title.is_empty() {
                    best_signal.signal_title
                } else {
                    region.heading_text.clone()
                };
                r.source = parse_region_source(&rebound_source);
                r.review_required = true;
                rebuilt.push(r);
            } else {
                let mut r = region.clone();
                r.review_required = true;
                rebuilt.push(r);
            }
            continue;
        }

        if page_signals.is_empty() {
            let split_segments =
                split_book_region_by_chapter_boundaries(&region, &phase1, page_by_no);
            if split_segments.len() > 1 {
                summary.split_count += split_segments.len() - 1;
                for (idx, (ch_id, pages)) in split_segments.into_iter().enumerate() {
                    summary.rebind_count += 1;
                    let mut r = region.clone();
                    r.region_id = format!("{}-chbound-{:02}", region.region_id, idx + 1);
                    r.chapter_id = ch_id;
                    r.page_start = *pages.first().unwrap();
                    r.page_end = *pages.last().unwrap();
                    r.pages = pages;
                    r.source = parse_region_source("chapter_boundary_fallback");
                    rebuilt.push(r);
                }
            } else {
                rebuilt.push(region);
            }
            continue;
        }

        // 段落构建
        let mut segments: Vec<(String, String, String, Vec<i64>)> = Vec::new();
        let mut segment_pages: Vec<i64> = Vec::new();
        let mut segment_chapter_id = region.chapter_id.clone();
        let mut segment_heading_text = region.heading_text.clone();
        let mut segment_source = region.source.as_str().to_string();

        for &page_no in &region.pages {
            let signal = page_signals.get(&page_no);
            let signal_source = signal_region_source(signal, &segment_source);
            if let Some(sig) = signal {
                if !segment_pages.is_empty() && sig.chapter_id != segment_chapter_id {
                    let mut previous_pages = segment_pages.clone();
                    if supports_shared_boundary(Some(sig)) && !previous_pages.contains(&page_no) {
                        previous_pages.push(page_no);
                    }
                    segments.push((
                        segment_chapter_id.clone(),
                        segment_heading_text.clone(),
                        segment_source.clone(),
                        previous_pages,
                    ));
                    segment_pages = Vec::new();
                    segment_chapter_id = sig.chapter_id.clone();
                    segment_heading_text = sig.signal_title.clone();
                    segment_source = signal_source.clone();
                } else if segment_pages.is_empty() {
                    segment_chapter_id = sig.chapter_id.clone();
                    segment_heading_text = sig.signal_title.clone();
                    segment_source = signal_source.clone();
                } else if sig.chapter_id == segment_chapter_id {
                    if signal_source == "explorer_toc_match" {
                        segment_source = signal_source.clone();
                    }
                    if segment_heading_text.is_empty() {
                        segment_heading_text = sig.signal_title.clone();
                    }
                }
            }
            segment_pages.push(page_no);
        }
        if !segment_pages.is_empty() {
            segments.push((
                segment_chapter_id,
                segment_heading_text,
                segment_source,
                segment_pages,
            ));
        }

        if segments.len() < phase1.chapters.len() && segments.len() < 3 {
            let split_segments =
                split_book_region_by_chapter_boundaries(&region, &phase1, page_by_no);
            if split_segments.len() > segments.len() {
                summary.split_count += split_segments.len() - 1;
                for (idx, (ch_id, pages)) in split_segments.into_iter().enumerate() {
                    summary.rebind_count += 1;
                    let mut r = region.clone();
                    r.region_id = format!("{}-chbound-{:02}", region.region_id, idx + 1);
                    r.chapter_id = ch_id;
                    r.page_start = *pages.first().unwrap();
                    r.page_end = *pages.last().unwrap();
                    r.pages = pages;
                    r.source = parse_region_source("chapter_boundary_fallback");
                    rebuilt.push(r);
                }
                continue;
            }
        }

        if segments.len() == 1 {
            let (chapter_id, heading_text, source, _pages) = segments.into_iter().next().unwrap();
            if chapter_id != region.chapter_id {
                if !chapter_id.is_empty() {
                    summary.rebind_count += 1;
                }
                let mut r = region.clone();
                r.chapter_id = chapter_id;
                r.heading_text = if !heading_text.is_empty() {
                    heading_text
                } else {
                    region.heading_text.clone()
                };
                r.source = parse_region_source(&source);
                rebuilt.push(r);
                continue;
            }
            if source != region.source.as_str()
                || (!heading_text.is_empty() && heading_text != region.heading_text)
            {
                let mut r = region.clone();
                r.heading_text = if !heading_text.is_empty() {
                    heading_text
                } else {
                    region.heading_text.clone()
                };
                r.source = parse_region_source(&source);
                rebuilt.push(r);
                continue;
            }
            rebuilt.push(region);
            continue;
        }

        summary.split_count += segments.len() - 1;
        for (idx, (chapter_id, heading_text, source, pages)) in segments.into_iter().enumerate() {
            if !chapter_id.is_empty() && chapter_id != region.chapter_id {
                summary.rebind_count += 1;
            }
            let mut r = region.clone();
            r.region_id = format!("{}-explore-{:02}", region.region_id, idx + 1);
            r.chapter_id = chapter_id;
            r.page_start = *pages.first().unwrap();
            r.page_end = *pages.last().unwrap();
            r.pages = pages;
            r.heading_text = if !heading_text.is_empty() {
                heading_text
            } else {
                region.heading_text.clone()
            };
            r.source = parse_region_source(&source);
            rebuilt.push(r);
        }
    }

    (rebuilt, summary)
}

// ── 旧 API 兼容（仅 page→chapter exploration, 不修改 regions） ─

/// 旧 API（兼容现有调用方）：返回 chapter→pages exploration 列表。
/// 实际使用建议改用 `explore_endnote_chapter_regions_full`。
pub fn explore_endnote_chapter_regions(
    pages: &[RawPage],
    chapters: &[ChapterRecord],
) -> Vec<EndnoteRegionExploration> {
    let mut explorations = Vec::new();
    let endnote_pages: Vec<&RawPage> = pages
        .iter()
        .filter(|p| {
            p.note_scan
                .as_ref()
                .and_then(|s| s.get("page_kind"))
                .and_then(|v| v.as_str())
                .map(|k| k == "endnote_collection")
                .unwrap_or(false)
        })
        .collect();
    if endnote_pages.is_empty() || chapters.is_empty() {
        return explorations;
    }
    let chapter_rows = build_chapter_rows(chapters);
    let mut current_pages: Vec<i64> = Vec::new();
    for page in &endnote_pages {
        let pn = page.book_page;
        if let Some(&last) = current_pages.last() {
            if pn == last + 1 {
                current_pages.push(pn);
                continue;
            }
        }
        if let Some(&start) = current_pages.first() {
            let end = *current_pages.last().unwrap_or(&start);
            explorations.push(assign_to_chapter(
                start,
                end,
                &chapter_rows,
                chapters,
                pages,
            ));
        }
        current_pages = vec![pn];
    }
    if let Some(&start) = current_pages.first() {
        let end = *current_pages.last().unwrap_or(&start);
        explorations.push(assign_to_chapter(
            start,
            end,
            &chapter_rows,
            chapters,
            pages,
        ));
    }
    explorations
}

fn assign_to_chapter(
    start: i64,
    end: i64,
    chapter_rows: &[ChapterRow],
    chapters: &[ChapterRecord],
    pages: &[RawPage],
) -> EndnoteRegionExploration {
    let chapter_by_page: HashMap<i64, &ChapterRecord> = chapters
        .iter()
        .flat_map(|ch| ch.pages.iter().map(move |&p| (p, ch)))
        .collect();
    if let Some(ch) = chapter_by_page.get(&start) {
        return EndnoteRegionExploration {
            chapter_id: ch.chapter_id.clone(),
            page_start: start,
            page_end: end,
            source: "explorer_toc_match".into(),
            confidence: 0.95,
        };
    }
    let heading_text = pages
        .iter()
        .find(|p| p.book_page == start)
        .and_then(|p| {
            p.markdown.lines().find(|l| {
                let t = l.trim();
                t.starts_with('#')
                    && (t.to_lowercase().contains("notes") || t.to_lowercase().contains("endnote"))
            })
        })
        .map(|l| l.trim().to_string())
        .unwrap_or_default();
    if !heading_text.is_empty() {
        if let Some((ch_id, _ct, score)) = match_signal_to_chapter(&heading_text, chapter_rows) {
            return EndnoteRegionExploration {
                chapter_id: ch_id,
                page_start: start,
                page_end: end,
                source: "explorer_signal_match".into(),
                confidence: score,
            };
        }
    }
    let mut prior: Vec<&ChapterRecord> = chapters
        .iter()
        .filter(|ch| ch.start_page <= start)
        .collect();
    prior.sort_by_key(|ch| ch.start_page);
    if let Some(ch) = prior.last() {
        return EndnoteRegionExploration {
            chapter_id: ch.chapter_id.clone(),
            page_start: start,
            page_end: end,
            source: "fallback_nearest_prior".into(),
            confidence: 0.70,
        };
    }
    EndnoteRegionExploration {
        chapter_id: chapters[0].chapter_id.clone(),
        page_start: start,
        page_end: end,
        source: "fallback_nearest_prior".into(),
        confidence: 0.50,
    }
}

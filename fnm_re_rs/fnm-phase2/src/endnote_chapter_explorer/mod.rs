//! ←→ FNM_RE/stages/endnote_chapter_explorer.py
//! 探索 endnote chapter 归属（无 TOC 时，三路径：TOC match / signal match / fallback）。
//!
//! # 状态：**STUB（未接入 phase2 主入口）**
//!
//! 当前实现 147 行 vs Python 722 行（约 20% 完成度）。`lib.rs::build_phase2_structure_sync`
//! 跳过本模块——除 self-test 外**无生产 caller**。
//! 接入前需补完所有 3 路径（详见 FNM_PHASE12_AUDIT.md F8）。
#![allow(dead_code)]

use fnm_core::records::ChapterRecord;
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashMap;

static NAMED_NOTES_TARGET_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*notes?\s+to\s+(.+?)\s*$").unwrap());

static CHAPTER_NUMBER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:chapter|chapitre)\s+(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[ivxlcdm]+|\d+)\b"
    ).unwrap()
});

#[derive(Debug, Clone)]
pub struct EndnoteRegionExploration {
    pub chapter_id: String,
    pub page_start: i64,
    pub page_end: i64,
    pub source: String,
    pub confidence: f64,
}

/// 三路径探索：TOC match → signal match → nearest chapter fallback。
pub fn explore_endnote_chapter_regions(
    pages: &[RawPage],
    chapters: &[ChapterRecord],
) -> Vec<EndnoteRegionExploration> {
    let mut explorations = Vec::new();

    // 找所有包含 endnote 信号的页
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

    // 构建 chapter page lookup
    let chapter_by_page: HashMap<i64, &ChapterRecord> = chapters
        .iter()
        .flat_map(|ch| ch.pages.iter().map(move |&p| (p, ch)))
        .collect();

    let mut current_start: Option<i64> = None;
    let mut current_pages: Vec<i64> = Vec::new();

    for page in &endnote_pages {
        let pn = page.book_page;
        if let Some(last) = current_pages.last() {
            if pn == *last + 1 {
                current_pages.push(pn);
                continue;
            }
        }
        // Flush previous group
        if let Some(start) = current_start {
            explorations.push(assign_to_chapter(
                start,
                *current_pages.last().unwrap_or(&start),
                chapters,
                &chapter_by_page,
            ));
        }
        current_start = Some(pn);
        current_pages = vec![pn];
    }
    // Flush last group
    if let Some(start) = current_start {
        explorations.push(assign_to_chapter(
            start,
            *current_pages.last().unwrap_or(&start),
            chapters,
            &chapter_by_page,
        ));
    }

    explorations
}

fn assign_to_chapter(
    start: i64,
    end: i64,
    chapters: &[ChapterRecord],
    chapter_by_page: &HashMap<i64, &ChapterRecord>,
) -> EndnoteRegionExploration {
    // Path 1: exact page match
    if let Some(ch) = chapter_by_page.get(&start) {
        return EndnoteRegionExploration {
            chapter_id: ch.chapter_id.clone(),
            page_start: start,
            page_end: end,
            source: "explorer_toc_match".into(),
            confidence: 0.95,
        };
    }

    // Path 2: nearest prior chapter
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

    // Path 3: first chapter fallback
    EndnoteRegionExploration {
        chapter_id: chapters[0].chapter_id.clone(),
        page_start: start,
        page_end: end,
        source: "fallback_nearest_prior".into(),
        confidence: 0.50,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_pages_no_explorations() {
        let result = explore_endnote_chapter_regions(&[], &[]);
        assert!(result.is_empty());
    }
}

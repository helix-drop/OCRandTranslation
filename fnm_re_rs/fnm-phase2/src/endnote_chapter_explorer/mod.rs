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
use fnm_core::title::{chapter_title_match_key, normalize_title};
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

/// 罗马数字映射。
fn roman_to_int(s: &str) -> Option<i64> {
    let s = s.trim().to_lowercase();
    let vals: HashMap<char, i64> = [
        ('i', 1),
        ('v', 5),
        ('x', 10),
        ('l', 50),
        ('c', 100),
        ('d', 500),
        ('m', 1000),
    ]
    .iter()
    .copied()
    .collect();
    let mut total: i64 = 0;
    let mut prev: i64 = 0;
    for ch in s.chars().rev() {
        let val = *vals.get(&ch)?;
        if val < prev {
            total -= val;
        } else {
            total += val;
            prev = val;
        }
    }
    Some(total)
}

#[derive(Debug, Clone)]
pub struct EndnoteRegionExploration {
    pub chapter_id: String,
    pub page_start: i64,
    pub page_end: i64,
    pub source: String,
    pub confidence: f64,
}

/// 从 endnote 页面提取章节号引用（如 "Notes to Chapter 3" → 3）。
fn extract_chapter_number_from_heading(heading: &str) -> Option<i64> {
    if let Some(caps) = NAMED_NOTES_TARGET_RE.captures(heading) {
        let target = caps.get(1).map(|m| m.as_str().trim()).unwrap_or("");
        // 去除 "Chapter / Chapitre" 前缀
        let target = CHAPTER_NUMBER_RE
            .captures(target)
            .and_then(|c| c.get(1).map(|m| m.as_str()))
            .unwrap_or(target);
        if let Ok(n) = target.parse::<i64>() {
            return Some(n);
        }
        // 尝试罗马数字
        if let Some(r) = roman_to_int(target) {
            return Some(r);
        }
        // 尝试英文数字词
        let words: HashMap<&str, i64> = [
            ("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5),
            ("six", 6), ("seven", 7), ("eight", 8), ("nine", 9), ("ten", 10),
            ("eleven", 11), ("twelve", 12),
        ].iter().copied().collect();
        if let Some(&n) = words.get(target.to_lowercase().as_str()) {
            return Some(n);
        }
    }
    None
}

/// 从 chapter title 中提取章节号。
fn chapter_number_from_title(title: &str) -> Option<i64> {
    let normalized = normalize_title(title);
    if let Some(caps) = CHAPTER_NUMBER_RE.captures(&normalized) {
        let num_str = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        if let Ok(n) = num_str.parse::<i64>() {
            return Some(n);
        }
        if let Some(r) = roman_to_int(num_str) {
            return Some(r);
        }
        let words: HashMap<&str, i64> = [
            ("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5),
            ("six", 6), ("seven", 7), ("eight", 8), ("nine", 9), ("ten", 10),
            ("eleven", 11), ("twelve", 12),
        ].iter().copied().collect();
        if let Some(&n) = words.get(num_str.to_lowercase().as_str()) {
            return Some(n);
        }
    }
    // 尝试匹配罗马数字独立标题
    let trimmed = normalized.trim();
    if let Some(r) = roman_to_int(trimmed) {
        return Some(r);
    }
    None
}

/// 模糊匹配：通过章节号引用将 endnote 页面绑定到对应 chapter。
/// ←→ Python `_match_signal_to_chapter`
fn fuzzy_match_chapter(
    heading_text: &str,
    chapters: &[ChapterRecord],
) -> Option<(String, f64)> {
    // 路径 A：从 heading 提取章节号，匹配 chapter title
    if let Some(target_num) = extract_chapter_number_from_heading(heading_text) {
        for ch in chapters {
            if let Some(ch_num) = chapter_number_from_title(&ch.title) {
                if ch_num == target_num {
                    return Some((ch.chapter_id.clone(), 0.90));
                }
            }
        }
        // 没找到精确数字匹配 → 用位置推断
        // 按 start_page 排序，target_num 对应索引
        let mut sorted: Vec<&ChapterRecord> = chapters.iter().collect();
        sorted.sort_by_key(|ch| ch.start_page);
        if target_num > 0 && (target_num as usize) <= sorted.len() {
            let ch = sorted[(target_num - 1) as usize];
            return Some((ch.chapter_id.clone(), 0.75));
        }
    }

    // 路径 B：尝试 title_key 匹配（heading 文本直接匹配 chapter 标题）
    let heading_key = chapter_title_match_key(heading_text);
    if !heading_key.is_empty() {
        for ch in chapters {
            let ch_key = chapter_title_match_key(&ch.title);
            if ch_key == heading_key {
                return Some((ch.chapter_id.clone(), 0.85));
            }
            // 部分匹配
            if ch_key.contains(&heading_key) || heading_key.contains(&ch_key) {
                return Some((ch.chapter_id.clone(), 0.70));
            }
        }
    }

    None
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
                pages,
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
            pages,
        ));
    }

    explorations
}

fn assign_to_chapter(
    start: i64,
    end: i64,
    chapters: &[ChapterRecord],
    chapter_by_page: &HashMap<i64, &ChapterRecord>,
    pages: &[RawPage],
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

    // Path 2: fuzzy match via chapter number signal
    // ←→ Python `_match_signal_to_chapter`
    let heading_text = endnote_heading_for_page(start, pages);
    if !heading_text.is_empty() {
        if let Some((ch_id, confidence)) = fuzzy_match_chapter(&heading_text, chapters) {
            return EndnoteRegionExploration {
                chapter_id: ch_id,
                page_start: start,
                page_end: end,
                source: "explorer_signal_match".into(),
                confidence,
            };
        }
    }

    // Path 3: nearest prior chapter
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

    // Path 4: first chapter fallback
    EndnoteRegionExploration {
        chapter_id: chapters[0].chapter_id.clone(),
        page_start: start,
        page_end: end,
        source: "fallback_nearest_prior".into(),
        confidence: 0.50,
    }
}

/// 获取 endnote 页的 heading text。
fn endnote_heading_for_page(page_no: i64, pages: &[RawPage]) -> String {
    pages
        .iter()
        .find(|p| p.book_page == page_no)
        .and_then(|p| {
            p.markdown
                .lines()
                .find(|l| {
                    let t = l.trim();
                    t.starts_with('#') && (
                        t.to_lowercase().contains("notes")
                        || t.to_lowercase().contains("endnote")
                    )
                })
        })
        .map(|l| l.trim().to_string())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{BoundaryState, ChapterSource};

    fn make_chapter(id: &str, title: &str, start: i64, end: i64) -> ChapterRecord {
        ChapterRecord {
            chapter_id: id.into(),
            title: title.into(),
            start_page: start,
            end_page: end,
            pages: (start..=end).collect(),
            source: ChapterSource::VisualToc,
            boundary_state: BoundaryState::Ready,
        }
    }

    #[test]
    fn empty_pages_no_explorations() {
        let result = explore_endnote_chapter_regions(&[], &[]);
        assert!(result.is_empty());
    }

    #[test]
    fn chapter_number_extraction() {
        assert_eq!(extract_chapter_number_from_heading("Notes to Chapter 3"), Some(3));
        assert_eq!(extract_chapter_number_from_heading("Notes to Chapter IV"), Some(4));
        assert_eq!(extract_chapter_number_from_heading("Notes to Chapter two"), Some(2));
        assert!(extract_chapter_number_from_heading("General Notes").is_none());
    }

    #[test]
    fn fuzzy_match_by_number() {
        let chapters = vec![
            make_chapter("ch-1", "Chapter 1", 1, 10),
            make_chapter("ch-2", "Chapter II", 20, 30),
            make_chapter("ch-3", "Chapter 3", 40, 50),
        ];
        let result = fuzzy_match_chapter("Notes to Chapter 2", &chapters);
        assert!(result.is_some());
        assert_eq!(result.unwrap().0, "ch-2");
    }

    #[test]
    fn roman_numeral_conversion() {
        assert_eq!(roman_to_int("I"), Some(1));
        assert_eq!(roman_to_int("IV"), Some(4));
        assert_eq!(roman_to_int("IX"), Some(9));
        assert_eq!(roman_to_int("XII"), Some(12));
        assert_eq!(roman_to_int("XIV"), Some(14));
    }
}

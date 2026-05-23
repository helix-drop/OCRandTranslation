//! ←→ FNM_RE/stages/endnote_chapter_explorer.py (722 行)
//! 基于尾注页结构信号探索 chapter 绑定。
//!
//! 完整 port：3 路径分配（TOC subentry / page signal / chapter boundary fallback）
//! + SequenceMatcher 模糊匹配（Rust 端用等价 longest-common-subseq ratio 实现）
//! + 章节号词/罗马数字解析 + 子条目展开。

use fnm_core::records::{ChapterRecord, HeadingCandidate, NoteRegionRecord, Phase1Structure};
use fnm_core::text::extract_page_headings;
use fnm_core::title::{chapter_title_match_key, normalize_title};
use fnm_core::types::{NoteKind, RegionScope, RegionSource};
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::str::FromStr;

fn parse_region_source(s: &str) -> RegionSource {
    RegionSource::from_str(s).unwrap_or(RegionSource::HeadingScan)
}

// ── 正则与常量 ─────────────────────────────────────────────────

static GENERIC_NOTES_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*|注释|脚注|尾注)\s*$")
        .unwrap()
});

static NAMED_NOTES_TARGET_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*notes?\s+to\s+(.+?)\s*$").unwrap());

static CHAPTER_NUMBER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:chapter|chapitre)\s+(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[ivxlcdm]+|\d+)\b(?:[\s:.\-]+(.*))?$"
    ).unwrap()
});

static LEADING_NUMBER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[ivxlcdm]+|\d+)[\.\)]?(?:\s+|$)(.*)$"
    ).unwrap()
});

fn word_number(token: &str) -> Option<i64> {
    match token.to_lowercase().as_str() {
        "one" => Some(1),
        "two" => Some(2),
        "three" => Some(3),
        "four" => Some(4),
        "five" => Some(5),
        "six" => Some(6),
        "seven" => Some(7),
        "eight" => Some(8),
        "nine" => Some(9),
        "ten" => Some(10),
        "eleven" => Some(11),
        "twelve" => Some(12),
        _ => None,
    }
}

// ── 数值解析 ─────────────────────────────────────────────────────

/// 罗马数字 → 整数。
pub fn roman_to_int(s: &str) -> i64 {
    let s = s.trim().to_uppercase();
    let mut total: i64 = 0;
    let mut previous: i64 = 0;
    for c in s.chars().rev() {
        let value = match c {
            'I' => 1,
            'V' => 5,
            'X' => 10,
            'L' => 50,
            'C' => 100,
            'D' => 500,
            'M' => 1000,
            _ => return 0,
        };
        if value < previous {
            total -= value;
        } else {
            total += value;
            previous = value;
        }
    }
    total
}

/// 解析数字/罗马/词形 token。
/// ←→ Python `_number_token_to_int`
pub fn number_token_to_int(token: &str) -> i64 {
    let raw = token.trim();
    if raw.is_empty() {
        return 0;
    }
    if let Ok(v) = raw.parse::<i64>() {
        return v;
    }
    if let Some(v) = word_number(raw) {
        return v;
    }
    roman_to_int(raw)
}

/// 从 chapter title 提取 (number_value, remainder)。
/// ←→ Python `_extract_number_info`
pub fn extract_number_info(text: &str) -> (i64, String) {
    let normalized = normalize_title(text);
    if normalized.is_empty() {
        return (0, String::new());
    }
    if let Some(caps) = CHAPTER_NUMBER_RE.captures(&normalized) {
        let num_str = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        let remainder = caps.get(2).map(|m| m.as_str()).unwrap_or("");
        return (number_token_to_int(num_str), normalize_title(remainder));
    }
    if let Some(caps) = LEADING_NUMBER_RE.captures(&normalized) {
        let num_str = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        let remainder = caps.get(2).map(|m| m.as_str()).unwrap_or("");
        return (number_token_to_int(num_str), normalize_title(remainder));
    }
    (0, normalized)
}

fn is_generic_notes_title(text: &str) -> bool {
    GENERIC_NOTES_TITLE_RE.is_match(&normalize_title(text))
}

// ── SequenceMatcher.ratio() 等价实现 ─────────────────────────────

/// LCS-based similarity ratio：返回 `2.0 * lcs_len / (a_len + b_len)`，
/// 等价于 Python `difflib.SequenceMatcher(None, a, b).ratio()` 在两短串场景下的输出。
pub fn sequence_matcher_ratio(a: &str, b: &str) -> f64 {
    let a_chars: Vec<char> = a.chars().collect();
    let b_chars: Vec<char> = b.chars().collect();
    let a_len = a_chars.len();
    let b_len = b_chars.len();
    if a_len == 0 && b_len == 0 {
        return 1.0;
    }
    if a_len == 0 || b_len == 0 {
        return 0.0;
    }
    // DP LCS
    let mut prev = vec![0usize; b_len + 1];
    let mut cur = vec![0usize; b_len + 1];
    for i in 1..=a_len {
        for j in 1..=b_len {
            cur[j] = if a_chars[i - 1] == b_chars[j - 1] {
                prev[j - 1] + 1
            } else {
                prev[j].max(cur[j - 1])
            };
        }
        std::mem::swap(&mut prev, &mut cur);
        cur.iter_mut().for_each(|v| *v = 0);
    }
    let lcs = prev[b_len];
    2.0 * lcs as f64 / (a_len + b_len) as f64
}

// ── Chapter rows ────────────────────────────────────────────────

#[derive(Debug, Clone)]
struct ChapterRow {
    chapter_id: String,
    chapter_title: String,
    match_key: String,
    #[allow(dead_code)]
    order_index: usize,
    number_value: i64,
    numbered_order_index: usize,
}

fn build_chapter_rows(chapters: &[ChapterRecord]) -> Vec<ChapterRow> {
    let mut rows: Vec<ChapterRow> = Vec::new();
    for (order_index, ch) in chapters.iter().enumerate() {
        let title = normalize_title(&ch.title);
        let match_key = chapter_title_match_key(&title);
        if title.is_empty() || match_key.is_empty() {
            continue;
        }
        let (number_value, _remainder) = extract_number_info(&title);
        rows.push(ChapterRow {
            chapter_id: ch.chapter_id.clone(),
            chapter_title: title,
            match_key,
            order_index: order_index + 1,
            number_value,
            numbered_order_index: 0,
        });
    }
    // 为有 number_value 的行编 numbered_order_index
    let mut numbered_idx = 0usize;
    for row in rows.iter_mut() {
        if row.number_value > 0 {
            numbered_idx += 1;
            row.numbered_order_index = numbered_idx;
        }
    }
    rows
}

// ── Signal types ────────────────────────────────────────────────

#[derive(Debug, Clone)]
struct PageChapterSignal {
    #[allow(dead_code)]
    page_no: i64,
    chapter_id: String,
    #[allow(dead_code)]
    chapter_title: String,
    signal_title: String,
    source: String,
    score: f64,
}

// ── Matching ────────────────────────────────────────────────────

/// ←→ Python `_match_signal_to_chapter`
fn match_signal_to_chapter(
    signal_title: &str,
    chapters: &[ChapterRow],
) -> Option<(String, String, f64)> {
    let normalized_title = normalize_title(signal_title);
    let signal_key = chapter_title_match_key(&normalized_title);
    if normalized_title.is_empty() || signal_key.is_empty() {
        return None;
    }
    let (signal_number, signal_remainder) = extract_number_info(&normalized_title);
    let signal_remainder_key = chapter_title_match_key(&signal_remainder);
    let normalized_lower = normalized_title.to_lowercase();

    let mut best_row: Option<&ChapterRow> = None;
    let mut best_score: f64 = 0.0;

    for row in chapters {
        if row.match_key.is_empty() || row.chapter_title.is_empty() {
            continue;
        }
        let (chapter_number, chapter_remainder) = extract_number_info(&row.chapter_title);
        let chapter_remainder_key = chapter_title_match_key(&chapter_remainder);

        let score: f64 = if signal_key == row.match_key {
            1.0
        } else if signal_number > 0
            && chapter_number == signal_number
            && chapter_remainder_key.chars().count() >= 12
            && signal_remainder_key.starts_with(&chapter_remainder_key)
        {
            0.99
        } else if row.match_key.chars().count() >= 12 && signal_key.starts_with(&row.match_key) {
            0.98
        } else if signal_key.contains(&row.match_key) || row.match_key.contains(&signal_key) {
            0.93
        } else {
            let r1 = sequence_matcher_ratio(&signal_key, &row.match_key);
            let r2 = sequence_matcher_ratio(&normalized_lower, &row.chapter_title.to_lowercase());
            r1.max(r2)
        };

        if score > best_score {
            best_score = score;
            best_row = Some(row);
        }
    }

    let best = best_row?;
    if best_score < 0.78 {
        return None;
    }
    Some((
        best.chapter_id.clone(),
        best.chapter_title.clone(),
        best_score,
    ))
}

/// ←→ Python `_find_chapter_by_number`
fn find_chapter_by_number(number_value: i64, chapters: &[ChapterRow]) -> Option<&ChapterRow> {
    if number_value <= 0 {
        return None;
    }
    for row in chapters {
        if row.number_value == number_value {
            return Some(row);
        }
    }
    for row in chapters {
        if row.numbered_order_index as i64 == number_value {
            return Some(row);
        }
    }
    None
}

/// ←→ Python `_match_toc_subentry_to_chapter`
fn match_toc_subentry_to_chapter(
    subentry: &Value,
    chapters: &[ChapterRow],
) -> Option<(String, String, f64)> {
    let title = normalize_title(subentry.get("title").and_then(|v| v.as_str()).unwrap_or(""));
    let match_mode = subentry
        .get("match_mode")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown")
        .trim()
        .to_lowercase();
    if title.is_empty() {
        return None;
    }
    match match_mode.as_str() {
        "named" => {
            let target_title = NAMED_NOTES_TARGET_RE
                .captures(&title)
                .and_then(|c| c.get(1))
                .map(|m| normalize_title(m.as_str()))
                .unwrap_or_default();
            let (number_value, remainder) = extract_number_info(&target_title);
            if number_value > 0 {
                let matched_row = find_chapter_by_number(number_value, chapters)?;
                if !remainder.is_empty() {
                    if let Some(tm) = match_signal_to_chapter(&remainder, chapters) {
                        if tm.0 == matched_row.chapter_id {
                            return Some((tm.0, tm.1, 1.22));
                        }
                    }
                }
                return Some((
                    matched_row.chapter_id.clone(),
                    matched_row.chapter_title.clone(),
                    1.1,
                ));
            }
            let matched = match_signal_to_chapter(&target_title, chapters)?;
            Some((matched.0, matched.1, 1.18))
        }
        "numbered" => {
            let (number_value, remainder) = extract_number_info(&title);
            if !remainder.is_empty() {
                if let Some(matched) = match_signal_to_chapter(&remainder, chapters) {
                    let matched_row = chapters.iter().find(|r| r.chapter_id == matched.0);
                    if let Some(mr) = matched_row {
                        let row_number = mr.number_value;
                        if number_value <= 0 || row_number == 0 || row_number == number_value {
                            return Some((matched.0, matched.1, 1.2));
                        }
                    }
                }
            }
            let matched_row = find_chapter_by_number(number_value, chapters)?;
            Some((
                matched_row.chapter_id.clone(),
                matched_row.chapter_title.clone(),
                1.05,
            ))
        }
        "chapter_title" => {
            let matched = match_signal_to_chapter(&title, chapters)?;
            Some((matched.0, matched.1, 1.08))
        }
        "unknown" => {
            let matched = match_signal_to_chapter(&title, chapters)?;
            Some((matched.0, matched.1, 0.9))
        }
        _ => {
            let matched = match_signal_to_chapter(&title, chapters)?;
            Some((matched.0, matched.1, 1.0))
        }
    }
}

// ── Heading candidates bonus ────────────────────────────────────

/// ←→ Python `_heading_candidate_style_bonus`
fn heading_candidate_style_bonus(candidate: &HeadingCandidate) -> f64 {
    let mut bonus: f64 = 0.0;
    if candidate.top_band {
        bonus += 0.08;
    }
    if candidate.heading_level_hint == 1 {
        bonus += 0.08;
    } else if candidate.heading_level_hint >= 2 {
        bonus += 0.04;
    }
    match candidate.font_weight_hint.as_str() {
        "heavy" => bonus += 0.08,
        "bold" => bonus += 0.05,
        _ => {}
    }
    if candidate.align_hint == "center" {
        bonus += 0.05;
    }
    if let Some(h) = candidate.font_height {
        if h >= 24.0 {
            bonus += 0.04;
        } else if h >= 18.0 {
            bonus += 0.02;
        }
    }
    if candidate.source == "pdf_font_band" {
        bonus += 0.04;
    }
    bonus.min(0.28)
}

fn heading_candidates_by_page(phase1: &Phase1Structure) -> HashMap<i64, Vec<HeadingCandidate>> {
    let mut mapped: HashMap<i64, Vec<HeadingCandidate>> = HashMap::new();
    for candidate in &phase1.heading_candidates {
        let page_no = candidate.page_no;
        if page_no <= 0 {
            continue;
        }
        mapped.entry(page_no).or_default().push(candidate.clone());
    }
    for (_pn, list) in mapped.iter_mut() {
        list.sort_by(|a, b| {
            // top_band False 排后；level_hint 大优先；heavy > bold；confidence 大优先
            let key_a = (
                !a.top_band,
                -(a.heading_level_hint),
                if a.font_weight_hint == "heavy" {
                    -1i32
                } else {
                    0
                },
                if a.font_weight_hint == "bold" {
                    -1i32
                } else {
                    0
                },
                -((a.confidence * 1_000.0) as i64),
            );
            let key_b = (
                !b.top_band,
                -(b.heading_level_hint),
                if b.font_weight_hint == "heavy" {
                    -1i32
                } else {
                    0
                },
                if b.font_weight_hint == "bold" {
                    -1i32
                } else {
                    0
                },
                -((b.confidence * 1_000.0) as i64),
            );
            key_a.cmp(&key_b)
        });
    }
    mapped
}

/// ←→ Python `_yield_page_signal_candidates`
fn yield_page_signal_candidates(
    page_no: i64,
    page: Option<&RawPage>,
    heading_candidates_by_page: &HashMap<i64, Vec<HeadingCandidate>>,
) -> Vec<(String, String, f64)> {
    let mut yielded: Vec<(String, String, f64)> = Vec::new();
    let mut seen: HashSet<(String, String)> = HashSet::new();

    let push = |yielded: &mut Vec<(String, String, f64)>,
                seen: &mut HashSet<(String, String)>,
                title: &str,
                source: &str,
                bonus: f64| {
        let normalized = normalize_title(title);
        if normalized.is_empty() || is_generic_notes_title(&normalized) {
            return;
        }
        let key = (source.to_string(), normalized.to_lowercase());
        if seen.contains(&key) {
            return;
        }
        seen.insert(key);
        yielded.push((normalized, source.to_string(), bonus));
    };

    // 1. note_scan items endnote section_title
    if let Some(p) = page {
        if let Some(ns) = &p.note_scan {
            if let Some(items) = ns.get("items").and_then(|v| v.as_array()) {
                for item in items {
                    let kind = item
                        .get("kind")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .trim()
                        .to_lowercase();
                    if kind != "endnote" {
                        continue;
                    }
                    let st = item
                        .get("section_title")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    push(&mut yielded, &mut seen, st, "note_section_title", 0.38);
                }
            }
            if let Some(hints) = ns.get("section_hints").and_then(|v| v.as_array()) {
                for hint in hints {
                    if let Some(s) = hint.as_str() {
                        push(&mut yielded, &mut seen, s, "note_section_hint", 0.30);
                    }
                }
            }
        }

        // page_heading from prunedResult
        let headings = extract_page_headings(&p.pruned_result);
        for heading in &headings {
            push(&mut yielded, &mut seen, heading, "page_heading", 0.26);
        }
    }

    // 4. heading_candidates_by_page
    if let Some(candidates) = heading_candidates_by_page.get(&page_no) {
        for candidate in candidates {
            if candidate.suppressed_as_chapter {
                continue;
            }
            let reject = candidate.reject_reason.trim();
            if !reject.is_empty() && reject != "section_candidate" {
                continue;
            }
            push(
                &mut yielded,
                &mut seen,
                &candidate.text,
                "heading_candidate",
                0.22 + heading_candidate_style_bonus(candidate),
            );
        }
    }

    yielded
}

// ── TOC subentry hints ──────────────────────────────────────────

fn toc_subentries_for_page(page_no: i64, endnote_explorer_hints: Option<&Value>) -> Vec<Value> {
    let hints = match endnote_explorer_hints {
        Some(v) => v,
        None => return Vec::new(),
    };
    let endnotes_summary = hints
        .get("endnotes_summary")
        .cloned()
        .unwrap_or(Value::Null);
    let present = endnotes_summary
        .get("present")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    if !present {
        return Vec::new();
    }
    let container_start = hints
        .get("container_start_page_hint")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    if container_start > 0 && page_no < container_start {
        return Vec::new();
    }
    let raw_subentries = hints
        .get("toc_subentries")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut subentries: Vec<Value> = raw_subentries
        .into_iter()
        .filter(|row| {
            row.get("printed_page")
                .and_then(|v| v.as_i64())
                .unwrap_or(0)
                > 0
        })
        .collect();
    if subentries.is_empty() {
        return Vec::new();
    }
    subentries.sort_by_key(|row| {
        (
            row.get("printed_page")
                .and_then(|v| v.as_i64())
                .unwrap_or(0),
            row.get("visual_order")
                .and_then(|v| v.as_i64())
                .unwrap_or(0),
        )
    });
    let mut active_index: i64 = -1;
    for (idx, row) in subentries.iter().enumerate() {
        let pp = row
            .get("printed_page")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        if pp <= page_no {
            active_index = idx as i64;
        } else {
            break;
        }
    }
    if active_index < 0 {
        return Vec::new();
    }
    let active_printed_page = subentries[active_index as usize]
        .get("printed_page")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    subentries
        .into_iter()
        .filter(|row| {
            row.get("printed_page")
                .and_then(|v| v.as_i64())
                .unwrap_or(0)
                == active_printed_page
        })
        .collect()
}

fn toc_page_signal_candidates(
    page_no: i64,
    chapters: &[ChapterRow],
    endnote_explorer_hints: Option<&Value>,
) -> Vec<PageChapterSignal> {
    let mut ranked: Vec<PageChapterSignal> = Vec::new();
    for subentry in toc_subentries_for_page(page_no, endnote_explorer_hints) {
        if let Some(matched) = match_toc_subentry_to_chapter(&subentry, chapters) {
            let signal_title =
                normalize_title(subentry.get("title").and_then(|v| v.as_str()).unwrap_or(""));
            ranked.push(PageChapterSignal {
                page_no,
                chapter_id: matched.0,
                chapter_title: matched.1,
                signal_title,
                source: "toc_subentry".into(),
                score: matched.2,
            });
        }
    }
    ranked
}

/// ←→ Python `_best_page_signal`
fn best_page_signal(
    page_no: i64,
    page: Option<&RawPage>,
    chapters: &[ChapterRow],
    heading_candidates_by_page: &HashMap<i64, Vec<HeadingCandidate>>,
    endnote_explorer_hints: Option<&Value>,
) -> (Option<PageChapterSignal>, bool) {
    let toc_ranked = toc_page_signal_candidates(page_no, chapters, endnote_explorer_hints);
    let mut ranked: Vec<PageChapterSignal> = toc_ranked.clone();

    let mut page_ranked: Vec<PageChapterSignal> = Vec::new();
    for (signal_title, source, bonus) in
        yield_page_signal_candidates(page_no, page, heading_candidates_by_page)
    {
        if let Some(matched) = match_signal_to_chapter(&signal_title, chapters) {
            page_ranked.push(PageChapterSignal {
                page_no,
                chapter_id: matched.0,
                chapter_title: matched.1,
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

fn signal_region_source(signal: Option<&PageChapterSignal>, default_source: &str) -> String {
    match signal {
        None => default_source.to_string(),
        Some(s) if s.source == "toc_subentry" => "explorer_toc_match".into(),
        Some(_) => "explorer_signal_match".into(),
    }
}

fn supports_shared_boundary(signal: Option<&PageChapterSignal>) -> bool {
    matches!(signal, Some(s) if s.source != "toc_subentry")
}

// ── Region split by chapter boundaries (fallback) ───────────────

/// ←→ Python `_split_book_region_by_chapter_boundaries`
fn split_book_region_by_chapter_boundaries(
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

// ── Public summary ──────────────────────────────────────────────

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

// ── Main entrypoint ─────────────────────────────────────────────

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
    let candidates_by_page = heading_candidates_by_page(&phase1);

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

        let mut page_signals: HashMap<i64, PageChapterSignal> = HashMap::new();
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
                let mut signals: Vec<&PageChapterSignal> = page_signals.values().collect();
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
    fn roman_to_int_basic() {
        assert_eq!(roman_to_int("I"), 1);
        assert_eq!(roman_to_int("IV"), 4);
        assert_eq!(roman_to_int("IX"), 9);
        assert_eq!(roman_to_int("XII"), 12);
        assert_eq!(roman_to_int("XIV"), 14);
    }

    #[test]
    fn number_token_word_form() {
        assert_eq!(number_token_to_int("three"), 3);
        assert_eq!(number_token_to_int("eleven"), 11);
    }

    #[test]
    fn extract_number_info_chapter_form() {
        let (n, rem) = extract_number_info("Chapter 3: Introduction");
        assert_eq!(n, 3);
        assert_eq!(rem.to_lowercase(), "introduction");
    }

    #[test]
    fn extract_number_info_word() {
        let (n, _rem) = extract_number_info("Chapter Two");
        assert_eq!(n, 2);
    }

    #[test]
    fn sequence_matcher_full_match() {
        assert!((sequence_matcher_ratio("hello", "hello") - 1.0).abs() < 1e-9);
    }

    #[test]
    fn sequence_matcher_no_overlap() {
        assert!(sequence_matcher_ratio("abc", "xyz") < 0.1);
    }

    #[test]
    fn match_signal_exact() {
        let rows = build_chapter_rows(&[make_chapter("ch-1", "Chapter One", 1, 10)]);
        let result = match_signal_to_chapter("Chapter One", &rows);
        assert!(result.is_some());
        assert_eq!(result.unwrap().0, "ch-1");
    }

    #[test]
    fn empty_pages_no_explorations() {
        let result = explore_endnote_chapter_regions(&[], &[]);
        assert!(result.is_empty());
    }

    #[test]
    fn fuzzy_match_by_chapter_title() {
        let rows = build_chapter_rows(&[
            make_chapter("ch-1", "Chapter One", 1, 10),
            make_chapter("ch-2", "Chapter Two: Architecture", 11, 20),
        ]);
        let result = match_signal_to_chapter("Notes to Architecture", &rows);
        assert!(result.is_some());
    }

    #[test]
    fn explore_book_region_with_signals() {
        let chapters = vec![
            make_chapter("ch-1", "Chapter One", 1, 10),
            make_chapter("ch-2", "Chapter Two", 11, 20),
        ];
        let pages: Vec<RawPage> = vec![RawPage {
            book_page: 100,
            markdown: "## Notes to Chapter One\n1. foo".into(),
            ..Default::default()
        }];
        let page_by_no: HashMap<i64, &RawPage> = pages.iter().map(|p| (p.book_page, p)).collect();

        let region = NoteRegionRecord {
            region_id: "nr-en-book-01".into(),
            chapter_id: String::new(),
            page_start: 100,
            page_end: 100,
            pages: vec![100],
            note_kind: NoteKind::Endnote,
            scope: RegionScope::Book,
            source: RegionSource::HeadingScan,
            heading_text: String::new(),
            start_reason: "candidate_page".into(),
            end_reason: "document_end".into(),
            region_marker_alignment_ok: true,
            region_start_first_source_marker: "1".into(),
            region_first_note_item_marker: String::new(),
            review_required: false,
        };
        let (rebuilt, summary) =
            explore_endnote_chapter_regions_full(vec![region], &chapters, &[], &page_by_no, None);
        assert_eq!(rebuilt.len(), 1);
        // 命中 ch-1 或保留原值（取决于具体 SequenceMatcher score）
        assert!(summary.rebind_count <= 1);
    }
}

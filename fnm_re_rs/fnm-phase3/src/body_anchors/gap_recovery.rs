//! ←→ FNM_RE/stages/body_anchors.py:_recover_expected_gap_* +
//!       _scan_expected_gap_bare_digits + _scan_expected_gap_symbols +
//!       _within_sequence_page_window + _known_endnote_marker_pages
//!
//! 已知章级 marker 序列有缺口时，从 page text 中启发式恢复缺失的 anchor。

use fnm_core::records::{BodyAnchorRecord, NoteItemRecord};
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::{HashMap, HashSet};

// ── 弱信号正则（仅用于 gap recovery）──────────────────────────
// 注：Rust regex 不支持 lookaround，需手动验证上下文。

static WEAK_EXPECTED_DIGIT_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s(\d{1,3})").unwrap());

static WEAK_DIGIT_LEFT_WORD_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"([A-Za-zàâäéèêëïîôöùûüÿçœÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇŒ]+)\s*$").unwrap());

// ←→ Python `_WEAK_EXPECTED_SYMBOL_RE`: 要求字母在前，标点/空格在后。
// 由于 Rust regex 不支持 lookaround，此处只捕获 * 本身，由消费方验证上下文。
static WEAK_EXPECTED_SYMBOL_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\*{1,3}").unwrap());

// ── 已知 endnote marker 页码映射 ────────────────────────────────

/// 构建每章每个 endnote marker 的已知 anchor 页码集合。
///
/// ←→ Python `_known_endnote_marker_pages`
pub fn known_endnote_marker_pages(
    anchors: &[BodyAnchorRecord],
    chapter_endnote_markers: &HashMap<String, HashSet<i64>>,
) -> HashMap<String, HashMap<i64, Vec<i64>>> {
    let mut by_chapter: HashMap<String, HashMap<i64, HashSet<i64>>> = HashMap::new();
    for anchor in anchors {
        if anchor.anchor_kind.as_str() != "endnote" {
            continue;
        }
        let cid = anchor.chapter_id.trim();
        if cid.is_empty() {
            continue;
        }
        let Ok(marker) = anchor.normalized_marker.parse::<i64>() else {
            continue;
        };
        if let Some(set) = chapter_endnote_markers.get(cid) {
            if !set.contains(&marker) {
                continue;
            }
        }
        by_chapter
            .entry(cid.to_string())
            .or_default()
            .entry(marker)
            .or_default()
            .insert(anchor.page_no);
    }
    by_chapter
        .into_iter()
        .map(|(cid, rows)| {
            let sorted: HashMap<i64, Vec<i64>> = rows
                .into_iter()
                .map(|(marker, pages)| {
                    let mut v: Vec<i64> = pages.into_iter().collect();
                    v.sort();
                    (marker, v)
                })
                .collect();
            (cid, sorted)
        })
        .collect()
}

/// 判断 page_no 是否在已知 marker 序列的合理窗口内。
///
/// ←→ Python `_within_sequence_page_window`
pub fn within_sequence_page_window(
    page_no: i64,
    marker: i64,
    known_pages_by_marker: &HashMap<i64, Vec<i64>>,
) -> bool {
    if page_no <= 0 || known_pages_by_marker.is_empty() {
        return false;
    }
    let lower_markers: Vec<i64> = known_pages_by_marker
        .keys()
        .copied()
        .filter(|&v| v < marker)
        .collect();
    let upper_markers: Vec<i64> = known_pages_by_marker
        .keys()
        .copied()
        .filter(|&v| v > marker)
        .collect();

    let lower_pages: Vec<i64> = lower_markers
        .iter()
        .max()
        .and_then(|&m| known_pages_by_marker.get(&m))
        .cloned()
        .unwrap_or_default();
    let upper_pages: Vec<i64> = upper_markers
        .iter()
        .min()
        .and_then(|&m| known_pages_by_marker.get(&m))
        .cloned()
        .unwrap_or_default();

    let all_pages: Vec<i64> = lower_pages
        .iter()
        .chain(upper_pages.iter())
        .copied()
        .collect();
    let min_page = if all_pages.is_empty() {
        page_no
    } else {
        all_pages.iter().copied().min().unwrap_or(page_no)
    };
    let max_page = if all_pages.is_empty() {
        page_no
    } else {
        all_pages.iter().copied().max().unwrap_or(page_no)
    };

    let padding = if max_page - min_page >= 5 { 2 } else { 1 };
    let lower = (min_page - padding).max(1);
    let upper = max_page + padding;
    lower <= page_no && page_no <= upper
}

// ── 扫描预期 gap ───────────────────────────────────────────────

/// 在文本中扫描 expected bare digit markers。
///
/// ←→ Python `_scan_expected_gap_bare_digits`
pub fn scan_expected_gap_bare_digits(text: &str, expected_markers: &HashSet<i64>) -> Vec<GapHit> {
    if expected_markers.is_empty() {
        return Vec::new();
    }
    let mut matches: Vec<GapHit> = Vec::new();
    for caps in WEAK_EXPECTED_DIGIT_RE.captures_iter(text) {
        let digit_match = caps.get(1).unwrap();
        let marker: i64 = match digit_match.as_str().parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        if !expected_markers.contains(&marker) {
            continue;
        }
        let digit_start = digit_match.start();
        let digit_end = digit_match.end();

        // 手动验证左侧词（替代 WEAK_DIGIT_LEFT_WORD_RE）
        let left = &text[..digit_start];
        let left_trimmed = left.trim_end();
        if let Some(word_caps) = WEAK_DIGIT_LEFT_WORD_RE.captures(left_trimmed) {
            let word = word_caps.get(1).unwrap().as_str().to_lowercase();
            if word.len() < 2 {
                continue;
            }
            // ←→ Python `_WEAK_EXPECTED_DIGIT_RE` lookahead: 右侧需标点或空格+字母，拒绝紧跟数字
            let right = &text[digit_end..];
            let right_stripped = right.trim_start();
            let valid_after = match right_stripped.chars().next() {
                None => true,
                Some(c) if c.is_ascii_digit() => false,
                Some(c) if "],.;:)}»\"'".contains(c) => true,
                Some(c) if c.is_whitespace() => right_stripped
                    .trim_start()
                    .chars()
                    .next()
                    .map(|n| n.is_alphabetic())
                    .unwrap_or(false),
                Some(_) => false,
            };
            if !valid_after {
                continue;
            }
            matches.push(GapHit {
                marker: marker.to_string(),
                start: digit_start,
                end: digit_end,
                source_text: extract_context(text, digit_start, digit_end),
            });
        }
    }
    matches
}

/// 判断符号是否在合理的 note 上下文中。
/// ←→ Python `_WEAK_EXPECTED_SYMBOL_RE` 的 lookbehind + lookahead。
fn symbol_in_note_context(text: &str, start: usize, end: usize) -> bool {
    // 左侧需要有一个字母字符（替代 `(?<=[A-Za-z...])`  lookbehind）
    let before = &text[..start];
    let left_char = before.chars().last();
    let has_letter_before = left_char.is_some_and(|c| c.is_alphabetic());

    // 右侧需要空白或标点（替代 `(?=(?:\s|[.,;:)\]}»'"])`  lookahead）
    let after = &text[end..];
    let right_trimmed = after.trim_start();
    let has_valid_after = if let Some(next) = right_trimmed.chars().next() {
        next.is_whitespace() || "],.;:)}»'\"".contains(next)
    } else {
        true // end of text
    };

    has_letter_before && has_valid_after
}

/// 在文本中扫描 expected symbol markers。
///
/// ←→ Python `_scan_expected_gap_symbols`
pub fn scan_expected_gap_symbols(text: &str, expected_markers: &HashSet<String>) -> Vec<GapHit> {
    if expected_markers.is_empty() {
        return Vec::new();
    }
    let mut matches: Vec<GapHit> = Vec::new();
    for m in WEAK_EXPECTED_SYMBOL_RE.find_iter(text) {
        let symbol = m.as_str();
        if !expected_markers.contains(symbol) {
            continue;
        }
        // ←→ Python `_WEAK_EXPECTED_SYMBOL_RE` 上下文检查（替代 lookaround）
        if !symbol_in_note_context(text, m.start(), m.end()) {
            continue;
        }
        matches.push(GapHit {
            marker: symbol.to_string(),
            start: m.start(),
            end: m.end(),
            source_text: extract_context(text, m.start(), m.end()),
        });
    }
    matches
}

// ── GapHit 结构 ─────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct GapHit {
    pub marker: String,
    pub start: usize,
    pub end: usize,
    pub source_text: String,
}

// ── 恢复函数 ────────────────────────────────────────────────────

/// 恢复缺失的 bare digit endnote anchors。
///
/// ←→ Python `_recover_expected_gap_bare_digit_anchors`
pub fn recover_expected_gap_bare_digit_anchors(
    anchors: &mut Vec<BodyAnchorRecord>,
    note_items: &[NoteItemRecord],
    page_text_by_no: &HashMap<i64, String>,
    chapter_endnote_markers: &HashMap<String, HashSet<i64>>,
    seen: &mut HashSet<(String, String, i64)>,
    anchor_counter: &mut usize,
) {
    let mut confirmed_markers: HashMap<String, HashSet<i64>> = HashMap::new();
    for anchor in anchors.iter() {
        if anchor.anchor_kind.as_str() != "endnote" {
            continue;
        }
        if let Ok(marker) = anchor.normalized_marker.parse::<i64>() {
            confirmed_markers
                .entry(anchor.chapter_id.clone())
                .or_default()
                .insert(marker);
        }
    }

    let known_pages = known_endnote_marker_pages(anchors, chapter_endnote_markers);

    for item in note_items {
        if item.note_kind.as_str() != "endnote" {
            continue;
        }
        let chapter_id = item.chapter_id.trim();
        if chapter_id.is_empty() {
            continue;
        }
        let Ok(marker) = item.marker.parse::<i64>() else {
            continue;
        };
        if confirmed_markers
            .get(chapter_id)
            .map(|s| s.contains(&marker))
            .unwrap_or(false)
        {
            continue;
        }

        let known = known_pages.get(chapter_id);
        let mut found_any = false;

        for (page_no, text) in page_text_by_no {
            if !within_sequence_page_window(*page_no, marker, known.unwrap_or(&HashMap::new())) {
                continue;
            }
            if text.trim().is_empty() {
                continue;
            }
            let hits = scan_expected_gap_bare_digits(text, &HashSet::from([marker]));
            let mut count_by_marker: HashMap<String, usize> = HashMap::new();
            for hit in &hits {
                *count_by_marker.entry(hit.marker.clone()).or_insert(0) += 1;
            }
            for hit in hits {
                if count_by_marker.get(&hit.marker).copied().unwrap_or(0) != 1 {
                    continue;
                }
                *anchor_counter += 1;
                let anchor_id = format!("gap-bare-{anchor_counter:05}");
                let key = ("bare_digit".to_string(), hit.marker.clone(), *page_no);
                if seen.contains(&key) {
                    continue;
                }
                seen.insert(key);
                anchors.push(BodyAnchorRecord {
                    anchor_id,
                    chapter_id: chapter_id.to_string(),
                    page_no: *page_no,
                    paragraph_index: 0,
                    char_start: hit.start as i64,
                    char_end: hit.end as i64,
                    source_marker: hit.marker.clone(),
                    normalized_marker: hit.marker.clone(),
                    anchor_kind: fnm_core::types::AnchorKind::Endnote,
                    certainty: 0.72,
                    source_text: hit.source_text,
                    source: "markdown:bare_digit".to_string(),
                    synthetic: true,
                    ocr_repaired_from_marker: String::new(),
                });
                found_any = true;
                break;
            }
            if found_any {
                break;
            }
        }
    }
}

/// 恢复缺失的 symbol endnote anchors。
///
/// ←→ Python `_recover_expected_gap_symbol_anchors`
pub fn recover_expected_gap_symbol_anchors(
    anchors: &mut Vec<BodyAnchorRecord>,
    note_items: &[NoteItemRecord],
    page_text_by_no: &HashMap<i64, String>,
    seen: &mut HashSet<(String, String, i64)>,
    anchor_counter: &mut usize,
) {
    let mut confirmed_markers: HashMap<String, HashSet<String>> = HashMap::new();
    for anchor in anchors.iter() {
        if anchor.anchor_kind.as_str() != "endnote" {
            continue;
        }
        if anchor.normalized_marker.parse::<i64>().is_ok() {
            continue; // 数字型 marker 不走 symbol recovery
        }
        confirmed_markers
            .entry(anchor.chapter_id.clone())
            .or_default()
            .insert(anchor.normalized_marker.clone());
    }

    for item in note_items {
        if item.note_kind.as_str() != "endnote" {
            continue;
        }
        let chapter_id = item.chapter_id.trim();
        if chapter_id.is_empty() {
            continue;
        }
        let marker_str = item.marker.trim();
        if marker_str.is_empty() || marker_str.parse::<i64>().is_ok() {
            continue;
        }
        if confirmed_markers
            .get(chapter_id)
            .map(|s| s.contains(marker_str))
            .unwrap_or(false)
        {
            continue;
        }

        for (page_no, text) in page_text_by_no {
            if text.trim().is_empty() {
                continue;
            }
            let expected = HashSet::from([marker_str.to_string()]);
            let hits = scan_expected_gap_symbols(text, &expected);
            for hit in hits {
                *anchor_counter += 1;
                let anchor_id = format!("gap-sym-{anchor_counter:05}");
                let key = ("symbol".to_string(), hit.marker.clone(), *page_no);
                if seen.contains(&key) {
                    continue;
                }
                seen.insert(key);
                anchors.push(BodyAnchorRecord {
                    anchor_id,
                    chapter_id: chapter_id.to_string(),
                    page_no: *page_no,
                    paragraph_index: 0,
                    char_start: hit.start as i64,
                    char_end: hit.end as i64,
                    source_marker: hit.marker.clone(),
                    normalized_marker: hit.marker.clone(),
                    anchor_kind: fnm_core::types::AnchorKind::Endnote,
                    certainty: 0.72,
                    source_text: hit.source_text,
                    source: "markdown:symbol_gap".to_string(),
                    synthetic: true,
                    ocr_repaired_from_marker: String::new(),
                });
                break;
            }
        }
    }
}

// ── 内部辅助 ────────────────────────────────────────────────────

fn extract_context(text: &str, start: usize, end: usize) -> String {
    // 使用 char_indices 避免 byte slice 截断多字节 UTF-8 字符
    let ctx_start = start.saturating_sub(30);
    let ctx_end = (end + 30).min(text.len());
    text.char_indices()
        .skip_while(|(i, _)| *i < ctx_start)
        .take_while(|(i, _)| *i < ctx_end)
        .map(|(_, ch)| ch)
        .collect()
}

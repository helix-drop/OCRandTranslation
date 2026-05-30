//! 章节匹配：ChapterRow 构建 + 信号标题 → 章节匹配。
//!
//! ←→ Python `endnote_chapter_explorer.py` 中的 `_match_signal_to_chapter` / `_match_toc_subentry_to_chapter`

use fnm_core::records::ChapterRecord;
use fnm_core::title::{chapter_title_match_key, normalize_title};
use serde_json::Value;

use super::numbering::{extract_number_info, sequence_matcher_ratio, NAMED_NOTES_TARGET_RE};

#[derive(Debug, Clone)]
pub(super) struct ChapterRow {
    pub(super) chapter_id: String,
    pub(super) chapter_title: String,
    pub(super) match_key: String,
    pub(super) number_value: i64,
    pub(super) numbered_order_index: usize,
}

pub(super) fn build_chapter_rows(chapters: &[ChapterRecord]) -> Vec<ChapterRow> {
    let mut rows: Vec<ChapterRow> = Vec::new();
    for ch in chapters.iter() {
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

#[derive(Debug, Clone)]
pub(super) struct PageChapterSignal {
    pub(super) chapter_id: String,
    pub(super) signal_title: String,
    pub(super) source: String,
    pub(super) score: f64,
}

/// ←→ Python `_match_signal_to_chapter`
pub(super) fn match_signal_to_chapter(
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
pub(super) fn find_chapter_by_number(
    number_value: i64,
    chapters: &[ChapterRow],
) -> Option<&ChapterRow> {
    if number_value <= 0 {
        return None;
    }
    if let Some(row) = chapters.iter().find(|r| r.number_value == number_value) {
        return Some(row);
    }
    chapters
        .iter()
        .find(|r| r.numbered_order_index as i64 == number_value)
}

/// ←→ Python `_match_toc_subentry_to_chapter`
pub(super) fn match_toc_subentry_to_chapter(
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

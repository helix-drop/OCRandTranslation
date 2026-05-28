//! ←→ page_partition.py: 注释页判定启发式。

use fnm_core::title::normalize_title;

use super::patterns::*;

pub(crate) fn note_def_match(line: &str) -> bool {
    let candidate = line.trim();
    if candidate.is_empty() {
        return false;
    }
    let candidate = if MARKDOWN_HEADING_RE.is_match(candidate) {
        normalize_title(
            MARKDOWN_HEADING_RE
                .captures(candidate)
                .and_then(|c| c.get(2))
                .map(|m| m.as_str())
                .unwrap_or(""),
        )
    } else {
        candidate.to_string()
    };
    let candidate = LEADING_OCR_NOTE_PUNCT_RE.replace_all(&candidate, "");
    NOTE_DEF_RE.is_match(&candidate) || NOTE_DEF_OCR_SPLIT_RE.is_match(&candidate)
}

pub(crate) fn looks_like_note_continuation_page(
    text: &str,
    page_no: i64,
    total_pages: i64,
) -> bool {
    let normalized = text.trim();
    if normalized.is_empty() {
        return false;
    }
    if page_no <= (8).max((total_pages as f64 * 0.03) as i64) {
        return false;
    }
    let lines = super::plain_text_lines(normalized);
    if lines.is_empty() {
        return false;
    }
    if super::is_notes_heading_match(&lines[0]) {
        return true;
    }
    let note_def_count = lines.iter().filter(|l| note_def_match(l)).count();
    if note_def_count < 2 {
        return false;
    }
    if lines.len() < 5 {
        return false;
    }
    let first_note_index = lines.iter().position(|l| note_def_match(l));
    match first_note_index {
        None => return false,
        Some(idx) if idx > 3 => return false,
        Some(idx) => {
            let prelude_lines: Vec<&String> = lines.iter().take(idx).collect();
            if note_def_count >= 2
                && !prelude_lines.is_empty()
                && prelude_lines
                    .iter()
                    .all(|l| MARKDOWN_HEADING_RE.is_match(l.trim()) || l.len() <= 80)
            {
                return true;
            }
        }
    }
    let non_note_line_count = lines.len().saturating_sub(note_def_count);
    if non_note_line_count <= 1 && note_def_count >= 2 {
        return true;
    }
    let first_content = lines
        .iter()
        .find(|l| !super::is_notes_heading_match(l))
        .cloned()
        .unwrap_or_default();
    if !first_content.is_empty() && note_def_match(&first_content) {
        return note_def_count >= 2;
    }
    note_def_count >= (4).max(lines.len() / 2)
}

/// 判断紧邻已确认 note 区之前的页面是否也是尾注开头页。
///
/// 与 `looks_like_note_continuation_page` 不同，首张尾注页允许在编号定义前包含
/// 缩略语或章节标题；相邻 note 页由 caller 作为必要的正向证据。
/// ←→ Python `_looks_like_note_continuation_page` 的首张页缺口修复。
pub(crate) fn looks_like_note_leading_page(text: &str, page_no: i64, total_pages: i64) -> bool {
    if page_no <= (8).max((total_pages as f64 * 0.03) as i64) {
        return false;
    }
    let lines = super::plain_text_lines(text);
    if lines.iter().any(|line| super::is_notes_heading_match(line)) {
        return false;
    }
    lines.len() >= 4 && lines.iter().filter(|line| note_def_match(line)).count() >= 2
}

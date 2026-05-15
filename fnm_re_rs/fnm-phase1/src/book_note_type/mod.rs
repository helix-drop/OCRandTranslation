//! ←→ FNM_RE/modules/book_note_type.py
//! Phase1b 书型粗判：footnote_band / endnote_region 检测 + book_type 推断。

use crate::input::RawPage;
use fnm_core::records::{ChapterNoteModeRecord, ChapterRecord};
use fnm_core::text::page_markdown_text;
use fnm_core::types::NoteMode;
use once_cell::sync::Lazy;
use regex::Regex;

/// 注释定义行正则。
static NOTE_DEF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*(?:\[(\d{1,4})\]|(\d{1,4})[\.;:,\)\]])\s*(.+)$").unwrap());

/// NOTES heading 正则。
static NOTES_HEADING_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:#+\s*)?(notes?|endnotes?|notes to pages?.*)\s*$").unwrap()
});

#[derive(Debug, Clone)]
pub struct BookNoteProfile {
    pub book_type: String,
    pub chapter_modes: Vec<ChapterNoteModeRecord>,
    pub evidence: serde_json::Value,
}

/// 检查页面是否有 NOTES heading（强 endnote 信号）。
fn has_notes_heading(markdown: &str) -> bool {
    markdown
        .lines()
        .find(|l| !l.trim().is_empty())
        .is_some_and(|first| NOTES_HEADING_RE.is_match(first.trim()))
}

/// 检查页面是否为 endnote 页面（三重检查）。
fn is_endnote_page(markdown: &str) -> bool {
    if has_notes_heading(markdown) {
        return true;
    }
    let markers = extract_note_markers(markdown);
    if markers.len() >= 4 {
        return true;
    }
    has_consecutive_note_sequence(markdown)
}

/// 提取页面中的注释 marker。
fn extract_note_markers(markdown: &str) -> Vec<i64> {
    let mut markers = Vec::new();
    for line in markdown.lines().take(16) {
        if let Some(caps) = NOTE_DEF_RE.captures(line.trim()) {
            let num = caps
                .get(1)
                .or_else(|| caps.get(2))
                .and_then(|m| m.as_str().parse::<i64>().ok());
            if let Some(n) = num {
                markers.push(n);
            }
        }
    }
    markers
}

/// 检查是否有连续注释序列（从 1 或 2 开始，≤1 gap）。
fn has_consecutive_note_sequence(markdown: &str) -> bool {
    let markers = extract_note_markers(markdown);
    if markers.len() < 3 {
        return false;
    }
    let mut sorted = markers.clone();
    sorted.sort();
    sorted.dedup();
    if sorted.is_empty() {
        return false;
    }
    let start = sorted[0];
    if start != 1 && start != 2 {
        return false;
    }
    let mut gaps = 0;
    for w in sorted.windows(2) {
        if w[1] - w[0] > 1 {
            gaps += 1;
        }
    }
    gaps <= 1
}

/// 多页变体：检查章末尾是否有连续 endnote 序列。
fn chapter_has_consecutive_endnote_sequence(pages: &[&str]) -> bool {
    let mut all_markers = Vec::new();
    for page in pages.iter().rev().take(8) {
        all_markers.extend(extract_note_markers(page));
    }
    if all_markers.is_empty() {
        return false;
    }
    all_markers.sort();
    all_markers.dedup();
    let start = all_markers[0];
    if start != 1 && start != 2 {
        return false;
    }
    let mut gaps = 0i64;
    for w in all_markers.windows(2) {
        if w[1] - w[0] > 1 {
            gaps += 1;
        }
    }
    let max_gaps = (all_markers.len() as f64 * 0.1).max(1.0) as i64;
    gaps <= max_gaps
}

/// 从 has_footnote/has_endnote 二元组推断 book_type。
fn resolve_book_type(has_footnote: bool, has_endnote: bool) -> &'static str {
    match (has_footnote, has_endnote) {
        (true, true) => "mixed",
        (false, true) => "endnote_only",
        (true, false) => "footnote_only",
        (false, false) => "no_notes",
    }
}

/// 构建 book note profile。对齐 Python `build_book_note_profile()`。
pub fn build_book_note_profile(
    chapters: &[ChapterRecord],
    pages: &[RawPage],
    _overrides: Option<&serde_json::Value>,
) -> BookNoteProfile {
    let page_by_no: std::collections::HashMap<i64, &RawPage> =
        pages.iter().map(|p| (p.book_page, p)).collect();

    // 逐章检测 endnote 页面
    let mut chapter_has_endnote = std::collections::HashSet::new();
    let mut chapter_has_footnote = std::collections::HashSet::new();

    for ch in chapters {
        let mut endnote_page_texts: Vec<String> = Vec::new();
        for &page_no in &ch.pages {
            if let Some(page) = page_by_no.get(&page_no) {
                let text = page_markdown_text(&serde_json::to_value(page).unwrap_or_default());
                if is_endnote_page(&text) {
                    endnote_page_texts.push(text);
                }
                // 检查 fnBlocks 中的 footnote
                if !page.fn_blocks.is_null() {
                    if let Some(arr) = page.fn_blocks.as_array() {
                        if !arr.is_empty() {
                            chapter_has_footnote.insert(ch.chapter_id.clone());
                        }
                    }
                }
            }
        }
        if !endnote_page_texts.is_empty() {
            let refs: Vec<&str> = endnote_page_texts.iter().map(|s| s.as_str()).collect();
            if chapter_has_consecutive_endnote_sequence(&refs) {
                chapter_has_endnote.insert(ch.chapter_id.clone());
            }
        }
    }

    // 推断每章 note_mode
    let chapter_modes: Vec<ChapterNoteModeRecord> = chapters
        .iter()
        .map(|ch| {
            let has_fn = chapter_has_footnote.contains(&ch.chapter_id);
            let has_en = chapter_has_endnote.contains(&ch.chapter_id);
            let mode = match (has_fn, has_en) {
                (true, false) => NoteMode::FootnotePrimary,
                (false, true) => NoteMode::ChapterEndnotePrimary,
                (true, true) => NoteMode::ReviewRequired,
                (false, false) => NoteMode::NoNotes,
            };
            ChapterNoteModeRecord {
                chapter_id: ch.chapter_id.clone(),
                note_mode: mode,
                region_ids: vec![],
                primary_region_scope: "chapter".into(),
                has_footnote_band: has_fn,
                has_endnote_region: has_en,
            }
        })
        .collect();

    let has_footnote = chapter_modes.iter().any(|m| {
        m.note_mode == NoteMode::FootnotePrimary || m.note_mode == NoteMode::ReviewRequired
    });
    let has_endnote = chapter_modes.iter().any(|m| {
        m.note_mode == NoteMode::ChapterEndnotePrimary || m.note_mode == NoteMode::ReviewRequired
    });
    let book_type = resolve_book_type(has_footnote, has_endnote).to_string();

    let evidence = serde_json::json!({
        "chapters_with_footnote": chapter_has_footnote.len(),
        "chapters_with_endnote": chapter_has_endnote.len(),
        "total_chapters": chapters.len(),
    });

    BookNoteProfile {
        book_type,
        chapter_modes,
        evidence,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn profile_for_empty() {
        let profile = build_book_note_profile(&[], &[], None);
        assert_eq!(profile.book_type, "no_notes");
        assert!(profile.chapter_modes.is_empty());
    }

    #[test]
    fn endnote_page_detection() {
        assert!(is_endnote_page(
            "## NOTES\n1. First note.\n2. Second note.\n3. Third note."
        ));
        assert!(is_endnote_page("1. Citation de Virgile...\n2. Robert Walpole...\n3. Helmut Schmidt...\n4. Another note."));
        assert!(!is_endnote_page("Some regular text.\nMore text."));
    }

    #[test]
    fn notes_heading_detection() {
        assert!(has_notes_heading("## NOTES\nContent"));
        assert!(has_notes_heading("## Endnotes\nContent"));
        assert!(!has_notes_heading("## Chapter 1\nContent"));
    }

    #[test]
    fn resolve_book_type_cases() {
        assert_eq!(resolve_book_type(true, false), "footnote_only");
        assert_eq!(resolve_book_type(false, true), "endnote_only");
        assert_eq!(resolve_book_type(true, true), "mixed");
        assert_eq!(resolve_book_type(false, false), "no_notes");
    }
}

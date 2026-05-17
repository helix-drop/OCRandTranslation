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

/// ←→ Python `_nearest_prior_chapter_id`:
/// 返回不晚于 page_no 的最近 chapter 的 chapter_id；不存在则空串。
fn nearest_prior_chapter_id(chapters: &[ChapterRecord], page_no: i64) -> String {
    chapters
        .iter()
        .filter(|ch| !ch.chapter_id.is_empty() && ch.start_page <= page_no)
        .max_by_key(|ch| ch.start_page)
        .map(|ch| ch.chapter_id.clone())
        .unwrap_or_default()
}

/// 构建 pages → chapter_id 映射。
/// ←→ Python `_chapter_by_page`
fn build_chapter_by_page(chapters: &[ChapterRecord]) -> std::collections::HashMap<i64, String> {
    let mut mapped = std::collections::HashMap::new();
    for ch in chapters {
        if ch.chapter_id.is_empty() {
            continue;
        }
        for &page_no in &ch.pages {
            if page_no > 0 {
                mapped.insert(page_no, ch.chapter_id.clone());
            }
        }
        if ch.start_page > 0 && ch.end_page >= ch.start_page {
            for page_no in ch.start_page..=ch.end_page {
                mapped.entry(page_no).or_insert_with(|| ch.chapter_id.clone());
            }
        }
    }
    mapped
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
/// ←→ Python `_chapter_has_consecutive_endnote_sequence`（简化版，不依赖 annotated_pages）
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

/// 构建 book note profile。
/// ←→ Python `build_book_note_profile()` — 增加 4 个守卫：
///   - `_nearest_prior_chapter_id` — 章间隙页绑定到前一章
///   - `chapters_with_heading` — 弱信号尾注的强信号锚点守卫
///   - `book_endnote_pages` — 全书级尾注（末章之后）
///   - endnote-priority mode — 章尾注优先于脚注
pub fn build_book_note_profile(
    chapters: &[ChapterRecord],
    pages: &[RawPage],
    _overrides: Option<&serde_json::Value>,
) -> BookNoteProfile {
    let page_by_no: std::collections::HashMap<i64, &RawPage> =
        pages.iter().map(|p| (p.book_page, p)).collect();

    let chapter_by_page = build_chapter_by_page(chapters);

    let last_chapter_end = chapters
        .iter()
        .map(|ch| ch.end_page)
        .max()
        .unwrap_or(0);

    // 第一遍：找出有强信号（## NOTES 标题）的章，作为弱信号守卫
    let mut chapters_with_heading: std::collections::HashSet<String> = std::collections::HashSet::new();
    for page in pages {
        let page_no = page.book_page;
        if page_no <= 0 {
            continue;
        }
        let chapter_id = chapter_by_page
            .get(&page_no)
            .cloned()
            .unwrap_or_else(|| nearest_prior_chapter_id(chapters, page_no));
        if chapter_id.is_empty() {
            continue;
        }
        if has_notes_heading(&page.markdown) {
            chapters_with_heading.insert(chapter_id.clone());
        }
        // 检查 fn_blocks 中是否有 endnote_collection 等效信号：
        // 连续编号的 fnBlocks 且数量≥3
        if !chapters_with_heading.contains(&chapter_id) {
            if let Some(arr) = page.fn_blocks.as_array() {
                let mut nums: Vec<i64> = Vec::new();
                for block in arr {
                    if let Some(label) = block.get("label").and_then(|v| v.as_str()) {
                        if let Ok(n) = label.trim().parse::<i64>() {
                            nums.push(n);
                        }
                    }
                }
                if nums.len() >= 3 {
                    nums.sort();
                    nums.dedup();
                    if nums[0] == 1 || nums[0] == 2 {
                        let gap_count = nums.windows(2).filter(|w| w[1] - w[0] > 1).count();
                        if gap_count as f64 <= (nums.len() as f64 * 0.1).max(1.0) {
                            chapters_with_heading.insert(chapter_id);
                        }
                    }
                }
            }
        }
    }

    // 第二遍：逐页检测 fn/en
    let mut footnote_pages: std::collections::HashSet<i64> = std::collections::HashSet::new();
    let mut endnote_pages: std::collections::HashSet<i64> = std::collections::HashSet::new();
    let mut chapter_has_footnote: std::collections::HashMap<String, std::collections::HashSet<i64>> =
        std::collections::HashMap::new();
    let mut chapter_has_endnote: std::collections::HashMap<String, std::collections::HashSet<i64>> =
        std::collections::HashMap::new();
    let mut book_endnote_pages: std::collections::HashSet<i64> = std::collections::HashSet::new();

    for page in pages {
        let page_no = page.book_page;
        if page_no <= 0 {
            continue;
        }

        let has_footnote = !page.footnotes.trim().is_empty()
            || page.fn_blocks.as_array().map_or(false, |a| !a.is_empty());

        let is_heading_endnote = has_notes_heading(&page.markdown);
        let is_weak_endnote = !is_heading_endnote && is_endnote_page(&page.markdown);
        let mut has_endnote = is_heading_endnote || is_weak_endnote;

        // 弱信号守卫：无强信号锚点的章内的弱信号不可靠
        if is_weak_endnote {
            let chapter_id = chapter_by_page
                .get(&page_no)
                .cloned()
                .unwrap_or_else(|| nearest_prior_chapter_id(chapters, page_no));
            if !chapter_id.is_empty() && !chapters_with_heading.contains(&chapter_id) {
                has_endnote = false;
            }
        }

        // 同一页上 fn + en 冲突时，默认 fn 优先（对齐 Python）。
        // Python 有 _reclassified_endnote 标记（fnBlock 重分类为 endnote）
        // 可保留 en 信号；Rust 暂无此标记，按 Python 默认行为：fe 冲突 → 降级 en。
        if has_endnote && has_footnote && !is_heading_endnote {
            has_endnote = false;
        }

        // 确定所属章
        let mut chapter_id = chapter_by_page.get(&page_no).cloned().unwrap_or_default();
        // 间隙页（章边界之间）用 nearest_prior 兜底，但不包括末章之后的页
        if chapter_id.is_empty() && page_no <= last_chapter_end {
            chapter_id = nearest_prior_chapter_id(chapters, page_no);
        }

        if has_footnote {
            footnote_pages.insert(page_no);
            if !chapter_id.is_empty() {
                chapter_has_footnote
                    .entry(chapter_id.clone())
                    .or_default()
                    .insert(page_no);
            }
        }
        if has_endnote {
            endnote_pages.insert(page_no);
            if chapter_id.is_empty() && page_no > last_chapter_end {
                book_endnote_pages.insert(page_no);
            } else if !chapter_id.is_empty() {
                chapter_has_endnote
                    .entry(chapter_id)
                    .or_default()
                    .insert(page_no);
            } else {
                // 间隙页且≤last_chapter_end 已经用 nearest_prior 处理了
                book_endnote_pages.insert(page_no);
            }
        }
    }

    // 推断每章 note_mode（endnote 优先）
    let chapter_modes: Vec<ChapterNoteModeRecord> = chapters
        .iter()
        .map(|ch| {
            let has_fn = chapter_has_footnote.contains_key(&ch.chapter_id);
            let mut has_en = chapter_has_endnote.contains_key(&ch.chapter_id);

            // 补检：章末连续编号序列是最强的尾注物理信号
            if !has_en {
                let ch_tail_texts: Vec<String> = ch
                    .pages
                    .iter()
                    .rev()
                    .take(8)
                    .filter_map(|p| page_by_no.get(p))
                    .map(|p| page_markdown_text(&serde_json::to_value(p).unwrap_or_default()))
                    .collect();
                if !ch_tail_texts.is_empty() {
                    let refs: Vec<&str> = ch_tail_texts.iter().map(|s| s.as_str()).collect();
                    if chapter_has_consecutive_endnote_sequence(&refs) {
                        has_en = true;
                        // 将页内标记加入 endnote_pages
                        for p in &ch.pages {
                            if let Some(rp) = page_by_no.get(p) {
                                let md = page_markdown_text(&serde_json::to_value(rp).unwrap_or_default());
                                if !extract_note_markers(&md).is_empty() {
                                    endnote_pages.insert(*p);
                                    chapter_has_endnote
                                        .entry(ch.chapter_id.clone())
                                        .or_default()
                                        .insert(*p);
                                }
                            }
                        }
                    }
                }
            }

            let mode = if has_en {
                NoteMode::ChapterEndnotePrimary
            } else if has_fn {
                NoteMode::FootnotePrimary
            } else if book_endnote_pages.iter().any(|p| ch.start_page <= *p && *p <= ch.end_page)
                || (!book_endnote_pages.is_empty()
                    && ch.end_page >= last_chapter_end)
            {
                NoteMode::BookEndnoteBound
            } else {
                NoteMode::NoNotes
            };

            ChapterNoteModeRecord {
                chapter_id: ch.chapter_id.clone(),
                note_mode: mode,
                region_ids: vec![],
                primary_region_scope: "chapter".into(),
                has_footnote_band: has_fn,
                has_endnote_region: has_en
                    || book_endnote_pages.iter().any(|p| ch.start_page <= *p && *p <= ch.end_page),
            }
        })
        .collect();

    let has_footnote = chapter_modes.iter().any(|m| {
        m.note_mode == NoteMode::FootnotePrimary || m.note_mode == NoteMode::ChapterEndnotePrimary
    });
    let has_endnote = chapter_modes.iter().any(|m| {
        m.note_mode == NoteMode::ChapterEndnotePrimary || m.note_mode == NoteMode::BookEndnoteBound
    });
    let book_type = resolve_book_type(has_footnote, has_endnote).to_string();

    let evidence = serde_json::json!({
        "chapters_with_footnote": chapter_has_footnote.len(),
        "chapters_with_endnote": chapter_has_endnote.len(),
        "total_chapters": chapters.len(),
        "book_endnote_pages": book_endnote_pages.len(),
        "chapters_with_heading": chapters_with_heading.len(),
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

    #[test]
    fn nearest_prior_finds_closest() {
        use fnm_core::types::{BoundaryState, ChapterSource};
        let chs = vec![
            ChapterRecord {
                chapter_id: "ch1".into(),
                title: "".into(),
                start_page: 1,
                end_page: 10,
                pages: vec![],
                source: ChapterSource::VisualToc,
                boundary_state: BoundaryState::Ready,
            },
            ChapterRecord {
                chapter_id: "ch2".into(),
                title: "".into(),
                start_page: 20,
                end_page: 30,
                pages: vec![],
                source: ChapterSource::VisualToc,
                boundary_state: BoundaryState::Ready,
            },
        ];
        assert_eq!(nearest_prior_chapter_id(&chs, 15), "ch1");
        assert_eq!(nearest_prior_chapter_id(&chs, 25), "ch2");
        assert_eq!(nearest_prior_chapter_id(&chs, 0), "");
    }

    #[test]
    fn chapter_by_page_fills_gaps() {
        use fnm_core::types::{BoundaryState, ChapterSource};
        let chs = vec![ChapterRecord {
            chapter_id: "ch1".into(),
            title: "".into(),
            start_page: 1,
            end_page: 5,
            pages: vec![1, 2, 3],
            source: ChapterSource::VisualToc,
            boundary_state: BoundaryState::Ready,
        }];
        let map = build_chapter_by_page(&chs);
        assert_eq!(map.get(&1).map(|s| s.as_str()), Some("ch1"));
        assert_eq!(map.get(&4).map(|s| s.as_str()), Some("ch1"));
        assert_eq!(map.get(&5).map(|s| s.as_str()), Some("ch1"));
    }
}

//! ←→ Python `FNM_RE/stages/units.py`（L401-506）
//!
//! 章级 body pages 结构化：从 raw pages 提取正文内容。

use fnm_core::records::ChapterRecord;
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::{HashMap, HashSet};

use super::page_split::{
    extract_note_heading_split, sanitize_gap_page_prefix, split_page_text_at_first_heading,
    split_page_text_by_chapter_heading, trim_trailing_markdown_note_block,
};

// ── 正则常量 ──────────────────────────────────────────────────────

/// ←→ Python `_NOTE_DEFINITION_LINE_RE` (anchors.py:12-23)
static NOTE_DEFINITION_LINE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)^\s*(?:\[(?:\d{1,4})\]|(?:\d{1,4})[\.\)\]]|(?:\d{1,4})\s{1,3}|<sup>\s*\d{1,4}\s*</sup>|\$\s*\^\{\d{1,4}\}\s*\$|\^\{\d{1,4}\}|[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,4})\s*\S+",
    )
    .unwrap()
});

/// ←→ Python `_HTML_SUP_RE` (anchors.py:24)
static HTML_SUP_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)<sup>\s*(\d{1,4})\s*</sup>").unwrap());

/// ←→ Python `_LATEX_SUP_RE` (anchors.py:25)
static LATEX_SUP_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\$\s*\^\{(\d{1,4})\}\s*\$").unwrap());

/// ←→ Python `_UNICODE_SUP_RE` (anchors.py:23)
static UNICODE_SUP_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,4}").unwrap());

// ── 类型 ──────────────────────────────────────────────────────

/// 结构化的 body page。
#[derive(Debug, Clone, Default)]
pub struct StructuredBodyPage {
    pub page_no: i64,
    pub text: String,
}

// ── 公开函数 ──────────────────────────────────────────────────────

/// ←→ Python `_build_structured_body_pages_for_chapter` (units.py:401-506)
///
/// 从 raw pages 提取章级 body pages。
///
/// # 参数
///
/// - `chapter` — 章记录
/// - `raw_page_by_no` — page_no → RawPage 映射
/// - `page_role_by_no` — page_no → page_role 映射
/// - `note_start_page` — endnote 区起始页（0 表示无 endnote）
/// - `next_chapter` — 下一章（用于 gap page 处理）
pub fn build_structured_body_pages_for_chapter(
    chapter: &ChapterRecord,
    raw_page_by_no: &HashMap<i64, &RawPage>,
    page_role_by_no: &HashMap<i64, String>,
    note_start_page: i64,
    next_chapter: Option<&ChapterRecord>,
) -> Vec<StructuredBodyPage> {
    let mut body_pages: Vec<StructuredBodyPage> = Vec::new();
    let mut appended_pages: HashSet<i64> = HashSet::new();

    let chapter_pages: Vec<i64> = chapter.pages.iter().filter(|&&p| p > 0).copied().collect();

    let chapter_start_page = if chapter.start_page > 0 {
        chapter.start_page
    } else {
        chapter_pages.first().copied().unwrap_or(0)
    };
    let chapter_end_page = if chapter.end_page > 0 {
        chapter.end_page
    } else {
        chapter_pages.last().copied().unwrap_or(0)
    };
    let next_start_page = next_chapter.map(|c| c.start_page).unwrap_or(0);
    let next_title = next_chapter
        .map(|c| c.title.trim().to_string())
        .unwrap_or_default();

    // 辅助闭包：添加页面
    let append_page = |page_no: i64,
                       text: &str,
                       body_pages: &mut Vec<StructuredBodyPage>,
                       appended: &mut HashSet<i64>| {
        let normalized = text.trim().to_string();
        if normalized.is_empty() || appended.contains(&page_no) {
            return;
        }
        body_pages.push(StructuredBodyPage {
            page_no,
            text: normalized,
        });
        appended.insert(page_no);
    };

    // 主循环：遍历 chapter pages
    for &page_no in &chapter_pages {
        let raw_page = raw_page_by_no.get(&page_no);
        let mut raw_text = raw_page.map(|p| p.markdown.clone()).unwrap_or_default();

        // 在 note_start_page 处切分
        let mut note_split: Option<(String, String)> = None;
        if page_no == note_start_page && !raw_text.is_empty() {
            note_split = extract_note_heading_split(&raw_text);
            if let Some((ref body, _)) = note_split {
                raw_text = body.clone();
            }
        }

        // 在 chapter_start_page 处按章标题切分
        if page_no == chapter_start_page && !raw_text.is_empty() {
            let (_, chapter_text) = split_page_text_by_chapter_heading(&raw_text, &chapter.title);
            if !chapter_text.is_empty() {
                raw_text = chapter_text;
            }
        }

        // trim 尾部 note 定义块
        raw_text = trim_trailing_markdown_note_block(&raw_text);

        // 按 page_role 过滤
        let page_role = page_role_by_no
            .get(&page_no)
            .map(|s| s.as_str())
            .unwrap_or("");
        let allow_mixed_note_start_body =
            page_no == note_start_page && note_split.is_some() && !raw_text.trim().is_empty();

        // 检查 post-note-start 页面是否有 body 内容
        let mut has_post_note_body = false;
        if !allow_mixed_note_start_body
            && note_start_page > 0
            && page_no > note_start_page
            && !raw_text.is_empty()
        {
            let mut body_lines = 0;
            let mut has_sup_signal = false;
            for line in raw_text.lines() {
                let stripped = line.trim();
                if stripped.is_empty() {
                    continue;
                }
                // 跳过 note definition 行
                if NOTE_DEFINITION_LINE_RE.is_match(stripped) {
                    continue;
                }
                body_lines += 1;
                if !has_sup_signal {
                    if LATEX_SUP_RE.is_match(stripped)
                        || HTML_SUP_RE.is_match(stripped)
                        || UNICODE_SUP_RE.is_match(stripped)
                    {
                        has_sup_signal = true;
                    }
                }
            }
            has_post_note_body = body_lines >= 2 || (body_lines >= 1 && has_sup_signal);
        }

        if !["body", "front_matter"].contains(&page_role)
            && !allow_mixed_note_start_body
            && !has_post_note_body
        {
            continue;
        }
        if note_start_page > 0 && page_no > note_start_page && !has_post_note_body {
            continue;
        }

        append_page(page_no, &raw_text, &mut body_pages, &mut appended_pages);
    }

    // 确保 note_start_page 被包含
    if note_start_page > 0 && !appended_pages.contains(&note_start_page) {
        if let Some(raw_page) = raw_page_by_no.get(&note_start_page) {
            let raw_text = raw_page.markdown.clone();
            if !raw_text.is_empty() {
                if let Some((body, _)) = extract_note_heading_split(&raw_text) {
                    let trimmed = trim_trailing_markdown_note_block(&body);
                    append_page(
                        note_start_page,
                        &trimmed,
                        &mut body_pages,
                        &mut appended_pages,
                    );
                }
            }
        }
    }

    // 处理 gap pages（章末到下章开始之间的页面）
    if chapter_end_page > 0 && next_start_page - chapter_end_page > 1 {
        for page_no in (chapter_end_page + 1)..next_start_page {
            if appended_pages.contains(&page_no) {
                continue;
            }
            let page_role = page_role_by_no
                .get(&page_no)
                .map(|s| s.as_str())
                .unwrap_or("");
            if !["body", "front_matter"].contains(&page_role) {
                continue;
            }
            if let Some(raw_page) = raw_page_by_no.get(&page_no) {
                let raw_text = raw_page.markdown.clone();
                if raw_text.is_empty() {
                    continue;
                }
                let (leading_text, _) = split_page_text_at_first_heading(&raw_text);
                let sanitized =
                    sanitize_gap_page_prefix(&trim_trailing_markdown_note_block(&leading_text));
                if !sanitized.is_empty() {
                    append_page(page_no, &sanitized, &mut body_pages, &mut appended_pages);
                }
            }
        }
    }

    // 处理 next_start_page 的前缀
    if next_start_page > 0 && !appended_pages.contains(&next_start_page) {
        let next_page_role = page_role_by_no
            .get(&next_start_page)
            .map(|s| s.as_str())
            .unwrap_or("");
        if ["body", "front_matter"].contains(&next_page_role) {
            if let Some(next_page) = raw_page_by_no.get(&next_start_page) {
                let next_page_text = next_page.markdown.clone();
                let (leading_text, _) =
                    split_page_text_by_chapter_heading(&next_page_text, &next_title);
                if !leading_text.is_empty() {
                    let sanitized =
                        sanitize_gap_page_prefix(&trim_trailing_markdown_note_block(&leading_text));
                    if !sanitized.is_empty() {
                        append_page(
                            next_start_page,
                            &sanitized,
                            &mut body_pages,
                            &mut appended_pages,
                        );
                    }
                }
            }
        }
    }

    body_pages
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{BoundaryState, ChapterSource};

    fn make_chapter(chapter_id: &str, title: &str, start: i64, end: i64) -> ChapterRecord {
        ChapterRecord {
            chapter_id: chapter_id.to_string(),
            title: title.to_string(),
            start_page: start,
            end_page: end,
            pages: (start..=end).collect(),
            boundary_state: BoundaryState::Ready,
            source: ChapterSource::Fallback,
        }
    }

    fn make_raw_page(book_page: i64, markdown: &str) -> RawPage {
        RawPage {
            book_page,
            markdown: markdown.to_string(),
            footnotes: String::new(),
            fn_blocks: serde_json::Value::Array(vec![]),
            ..Default::default()
        }
    }

    #[test]
    fn test_build_structured_body_pages_basic() {
        let chapter = make_chapter("ch1", "Chapter 1", 1, 3);
        let p1 = make_raw_page(1, "# Chapter 1\n\nBody text page 1.");
        let p2 = make_raw_page(2, "Body text page 2.");
        let p3 = make_raw_page(3, "Body text page 3.");
        let raw_pages = vec![p1, p2, p3];
        let raw_page_by_no: HashMap<i64, &RawPage> =
            raw_pages.iter().map(|p| (p.book_page, p)).collect();
        let mut page_role_by_no = HashMap::new();
        page_role_by_no.insert(1, "body".to_string());
        page_role_by_no.insert(2, "body".to_string());
        page_role_by_no.insert(3, "body".to_string());

        let result = build_structured_body_pages_for_chapter(
            &chapter,
            &raw_page_by_no,
            &page_role_by_no,
            0,
            None,
        );
        assert_eq!(result.len(), 3);
        assert_eq!(result[0].page_no, 1);
        assert!(result[0].text.contains("Body text page 1"));
    }

    #[test]
    fn test_build_structured_body_pages_filters_other_role() {
        let chapter = make_chapter("ch1", "Chapter 1", 1, 3);
        let p1 = make_raw_page(1, "Body text page 1.");
        let p2 = make_raw_page(2, "Body text page 2.");
        let p3 = make_raw_page(3, "Body text page 3.");
        let raw_pages = vec![p1, p2, p3];
        let raw_page_by_no: HashMap<i64, &RawPage> =
            raw_pages.iter().map(|p| (p.book_page, p)).collect();
        let mut page_role_by_no = HashMap::new();
        page_role_by_no.insert(1, "body".to_string());
        page_role_by_no.insert(2, "note".to_string()); // 应被过滤
        page_role_by_no.insert(3, "body".to_string());

        let result = build_structured_body_pages_for_chapter(
            &chapter,
            &raw_page_by_no,
            &page_role_by_no,
            0,
            None,
        );
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].page_no, 1);
        assert_eq!(result[1].page_no, 3);
    }

    #[test]
    fn test_build_structured_body_pages_empty() {
        let chapter = make_chapter("ch1", "Chapter 1", 1, 1);
        let raw_page_by_no: HashMap<i64, &RawPage> = HashMap::new();
        let page_role_by_no: HashMap<i64, String> = HashMap::new();

        let result = build_structured_body_pages_for_chapter(
            &chapter,
            &raw_page_by_no,
            &page_role_by_no,
            0,
            None,
        );
        assert!(result.is_empty());
    }
}

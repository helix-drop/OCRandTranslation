//! ←→ FNM_RE/shared/chapters.py
//! 章节归属（page_no → chapter_id）共享工具。

use crate::records::ChapterRecord;

/// 判断 chapter_id 是否是 fallback 章（"ch-fallback-*" 前缀）。
pub fn is_fallback_chapter_id(s: &str) -> bool {
    s.starts_with("ch-fallback-")
}

/// 判断 chapter_id 是否是 TOC 章（"toc-ch-*" 前缀）。
pub fn is_toc_chapter_id(s: &str) -> bool {
    s.starts_with("toc-ch-")
}

/// 给定 page_no，返回它所属的 chapter_id。
/// 优先精确匹配 `chapter.pages`，其次区间匹配 `start_page..end_page`，最后最近前置章。
pub fn chapter_id_for_page(chapters: &[ChapterRecord], page_no: i64) -> String {
    if chapters.is_empty() || page_no <= 0 {
        return String::new();
    }
    // 1) 精确匹配 pages 列表
    for ch in chapters {
        if ch.pages.contains(&page_no) {
            return ch.chapter_id.clone();
        }
    }
    // 2) 区间匹配
    for ch in chapters {
        if ch.start_page <= page_no && page_no <= ch.end_page {
            return ch.chapter_id.clone();
        }
    }
    // 3) 最近前置章节兜底
    let mut prior: Vec<&ChapterRecord> = chapters
        .iter()
        .filter(|ch| ch.start_page <= page_no)
        .collect();
    if prior.is_empty() {
        return String::new();
    }
    prior.sort_by_key(|ch| (ch.start_page, ch.end_page));
    prior
        .last()
        .map(|ch| ch.chapter_id.clone())
        .unwrap_or_default()
}

/// 仅用最近前置章节兜底（不检查 pages 精确匹配）。
pub fn nearest_prior_chapter(chapters: &[ChapterRecord], page_no: i64) -> String {
    if chapters.is_empty() || page_no <= 0 {
        return String::new();
    }
    let mut prior: Vec<&ChapterRecord> = chapters
        .iter()
        .filter(|ch| ch.start_page <= page_no)
        .collect();
    if prior.is_empty() {
        return String::new();
    }
    prior.sort_by_key(|ch| (ch.start_page, ch.end_page));
    prior
        .last()
        .map(|ch| ch.chapter_id.clone())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{BoundaryState, ChapterSource};

    fn make_chapter(id: &str, start: i64, end: i64, pages: Vec<i64>) -> ChapterRecord {
        ChapterRecord {
            chapter_id: id.into(),
            title: id.into(),
            start_page: start,
            end_page: end,
            pages,
            source: ChapterSource::VisualToc,
            boundary_state: BoundaryState::Ready,
        }
    }

    #[test]
    fn is_fallback() {
        assert!(is_fallback_chapter_id("ch-fallback-1"));
        assert!(!is_fallback_chapter_id("toc-ch-1"));
        assert!(!is_fallback_chapter_id("ch-1"));
    }

    #[test]
    fn is_toc() {
        assert!(is_toc_chapter_id("toc-ch-1"));
        assert!(!is_toc_chapter_id("ch-1"));
    }

    #[test]
    fn find_chapter_exact_pages() {
        let chapters = vec![
            make_chapter("ch-1", 1, 10, vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
            make_chapter("ch-2", 11, 20, vec![11, 12, 13, 14, 15, 16, 17, 18, 19, 20]),
        ];
        assert_eq!(chapter_id_for_page(&chapters, 5), "ch-1");
        assert_eq!(chapter_id_for_page(&chapters, 15), "ch-2");
    }

    #[test]
    fn find_chapter_range_fallback() {
        let chapters = vec![
            make_chapter("ch-1", 1, 10, vec![]),
            make_chapter("ch-2", 11, 20, vec![]),
        ];
        assert_eq!(chapter_id_for_page(&chapters, 5), "ch-1");
    }

    #[test]
    fn find_chapter_empty() {
        assert_eq!(chapter_id_for_page(&[], 5), "");
    }
}

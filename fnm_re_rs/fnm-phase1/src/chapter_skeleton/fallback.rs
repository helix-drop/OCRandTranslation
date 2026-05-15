//! ←→ FNM_RE/stages/chapter_skeleton/fallback.py
//! 无 TOC 时的 fallback 章节切分。

use crate::heading_graph::HeadingGraph;
use fnm_core::records::{ChapterRecord, HeadingCandidate, PagePartitionRecord};
use fnm_core::types::{BoundaryState, ChapterSource};

/// 无 TOC 时，从 page_partitions 的 body 页构造 fallback 章节。
pub fn build_chapter_skeleton_fallback(
    page_partitions: &[PagePartitionRecord],
    _heading_candidates: &[HeadingCandidate],
    _heading_graph: &HeadingGraph,
    total_pages: i64,
) -> Vec<ChapterRecord> {
    if page_partitions.is_empty() {
        return vec![];
    }

    // 简单策略：把连续的 body 页打包为一个 fallback 章
    let mut chapters = Vec::new();
    let mut chapter_start: Option<i64> = None;
    let mut chapter_pages: Vec<i64> = Vec::new();
    let mut chapter_count = 0i64;

    for pp in page_partitions {
        if pp.page_role.as_str() == "body" {
            if chapter_start.is_none() {
                chapter_start = Some(pp.page_no);
                chapter_count += 1;
            }
            chapter_pages.push(pp.page_no);
        } else if chapter_start.is_some() {
            let start = chapter_start.take().unwrap();
            let end = chapter_pages.last().copied().unwrap_or(start);
            chapters.push(ChapterRecord {
                chapter_id: format!("ch-fallback-{:03}", chapter_count),
                title: format!("Chapter {}", chapter_count),
                start_page: start,
                end_page: end,
                pages: std::mem::take(&mut chapter_pages),
                source: ChapterSource::Fallback,
                boundary_state: BoundaryState::ReviewRequired,
            });
        }
    }

    // 尾章
    if let Some(start) = chapter_start {
        let end = chapter_pages.last().copied().unwrap_or(start);
        chapters.push(ChapterRecord {
            chapter_id: format!("ch-fallback-{:03}", chapter_count),
            title: format!("Chapter {}", chapter_count),
            start_page: start,
            end_page: end,
            pages: std::mem::take(&mut chapter_pages),
            source: ChapterSource::Fallback,
            boundary_state: BoundaryState::ReviewRequired,
        });
    }

    let _ = total_pages;
    chapters
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::PageRole;

    fn pp(page_no: i64, role: PageRole) -> PagePartitionRecord {
        PagePartitionRecord {
            page_no,
            target_pdf_page: page_no,
            page_role: role,
            confidence: 0.0,
            reason: String::new(),
            section_hint: String::new(),
            has_note_heading: false,
            note_scan_summary: serde_json::Value::Null,
        }
    }

    #[test]
    fn fallback_single_chapter() {
        let parts = vec![
            pp(1, PageRole::Body),
            pp(2, PageRole::Body),
            pp(3, PageRole::Body),
        ];
        let chapters = build_chapter_skeleton_fallback(&parts, &[], &HeadingGraph::default(), 3);
        assert_eq!(chapters.len(), 1);
        assert!(chapters[0].chapter_id.starts_with("ch-fallback-"));
        assert_eq!(chapters[0].start_page, 1);
        assert_eq!(chapters[0].end_page, 3);
    }

    #[test]
    fn fallback_empty() {
        let chapters = build_chapter_skeleton_fallback(&[], &[], &HeadingGraph::default(), 0);
        assert!(chapters.is_empty());
    }
}

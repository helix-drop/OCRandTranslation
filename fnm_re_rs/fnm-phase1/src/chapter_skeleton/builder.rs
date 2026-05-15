//! ←→ FNM_RE/stages/chapter_skeleton/builder.py
//! 章节边界构建器。

use crate::input::TocItem;
use fnm_core::records::{ChapterRecord, HeadingCandidate, PagePartitionRecord};
use fnm_core::types::{BoundaryState, ChapterSource};

#[derive(Debug, Clone)]
pub struct ChapterSkeleton {
    pub chapters: Vec<ChapterRecord>,
    pub heading_candidates: Vec<HeadingCandidate>,
    pub diagnostics: serde_json::Value,
}

/// 从 TOC items + page_partitions 构建章节骨架。
pub fn build_chapter_skeleton(
    pages: &[crate::input::RawPage],
    toc_items: Option<&[TocItem]>,
    page_partitions: &[PagePartitionRecord],
    heading_graph: &crate::heading_graph::HeadingGraph,
) -> ChapterSkeleton {
    let total_pages = pages.len() as i64;

    let (chapters, source) = if let Some(items) = toc_items {
        if items.is_empty() {
            (vec![], "fallback")
        } else {
            let mut chs: Vec<ChapterRecord> = items
                .iter()
                .filter(|item| item.export_candidate.unwrap_or(true))
                .enumerate()
                .map(|(i, item)| ChapterRecord {
                    chapter_id: format!("toc-ch-{}", i + 1),
                    title: item.title.clone(),
                    start_page: item.target_pdf_page.unwrap_or(1),
                    end_page: 0,
                    pages: vec![],
                    source: ChapterSource::VisualToc,
                    boundary_state: BoundaryState::Ready,
                })
                .collect();
            // fill end_page
            for i in 0..chs.len() {
                let next_start = if i + 1 < chs.len() {
                    chs[i + 1].start_page
                } else {
                    total_pages + 1
                };
                chs[i].end_page = next_start - 1;
                chs[i].pages = (chs[i].start_page..=chs[i].end_page).collect();
            }
            (chs, "visual_toc")
        }
    } else {
        (vec![], "fallback")
    };

    let chapters = if chapters.is_empty() {
        crate::chapter_skeleton::fallback::build_chapter_skeleton_fallback(
            page_partitions,
            &[],
            heading_graph,
            total_pages,
        )
    } else {
        chapters
    };

    ChapterSkeleton {
        chapters,
        heading_candidates: vec![],
        diagnostics: serde_json::json!({
            "source": source,
            "total_pages": total_pages,
        }),
    }
}

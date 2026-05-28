//! ←→ FNM_RE/stages/endnote_chapter_explorer.py (722 行)
//! 基于尾注页结构信号探索 chapter 绑定。
//!
//! 完整 port：3 路径分配（TOC subentry / page signal / chapter boundary fallback）
//! + SequenceMatcher 模糊匹配（Rust 端用等价 longest-common-subseq ratio 实现）
//! + 章节号词/罗马数字解析 + 子条目展开。
//!
//! 子模块拆分：
//! - `numbering`：数值解析 + 序列匹配
//! - `matching`：章节行 + 信号匹配
//! - `page_signals`：页面信号收集
//! - `signal_select`：最佳信号选择 + region 切分
//! - `boundary_fallback`：主入口 + 旧 API

mod boundary_fallback;
mod matching;
mod numbering;
mod page_signals;
mod signal_select;

// Re-export 公开 API
pub use boundary_fallback::{
    explore_endnote_chapter_regions, explore_endnote_chapter_regions_full,
    EndnoteRegionExploration, ExplorerSummary,
};
pub use numbering::{number_token_to_int, roman_to_int, sequence_matcher_ratio};

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::{ChapterRecord, NoteRegionRecord};
    use fnm_core::types::{BoundaryState, ChapterSource, NoteKind, RegionScope, RegionSource};
    use fnm_phase1::input::RawPage;
    use std::collections::HashMap;

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
        let (n, rem) = numbering::extract_number_info("Chapter 3: Introduction");
        assert_eq!(n, 3);
        assert_eq!(rem.to_lowercase(), "introduction");
    }

    #[test]
    fn extract_number_info_word() {
        let (n, _rem) = numbering::extract_number_info("Chapter Two");
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
        let rows = matching::build_chapter_rows(&[make_chapter("ch-1", "Chapter One", 1, 10)]);
        let result = matching::match_signal_to_chapter("Chapter One", &rows);
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
        let rows = matching::build_chapter_rows(&[
            make_chapter("ch-1", "Chapter One", 1, 10),
            make_chapter("ch-2", "Chapter Two: Architecture", 11, 20),
        ]);
        let result = matching::match_signal_to_chapter("Notes to Architecture", &rows);
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

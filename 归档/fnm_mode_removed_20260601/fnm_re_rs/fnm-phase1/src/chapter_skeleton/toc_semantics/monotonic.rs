//! 章节顺序单调性校验。

use fnm_core::records::ChapterRecord;

/// 检查章节列表的 start_page 是否单调不减（允许相等）。
pub fn check_chapter_order_monotonic(chapters: &[ChapterRecord]) -> bool {
    chapters
        .windows(2)
        .all(|w| w[0].start_page <= w[1].start_page)
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{BoundaryState, ChapterSource};

    fn ch(id: &str, start: i64) -> ChapterRecord {
        ChapterRecord {
            chapter_id: id.into(),
            title: id.into(),
            start_page: start,
            end_page: start + 5,
            pages: vec![],
            source: ChapterSource::VisualToc,
            boundary_state: BoundaryState::Ready,
        }
    }

    #[test]
    fn monotonic_true() {
        assert!(check_chapter_order_monotonic(&[
            ch("a", 1),
            ch("b", 10),
            ch("c", 20),
        ]));
    }

    #[test]
    fn monotonic_false() {
        assert!(!check_chapter_order_monotonic(&[
            ch("a", 20),
            ch("b", 10),
            ch("c", 30),
        ]));
    }
}

//! 章节顺序单调性校验 + 自动重排。

use fnm_core::records::ChapterRecord;

/// 检查章节列表的 start_page 是否严格递增。
pub fn check_chapter_order_monotonic(chapters: &[ChapterRecord]) -> bool {
    chapters
        .windows(2)
        .all(|w| w[0].start_page <= w[1].start_page)
}

/// 如果章节乱序，按 start_page 重新排序（保持 chapter_id 不变）。
pub fn reorder_chapters_monotonic(chapters: &mut [ChapterRecord]) -> bool {
    let was_monotonic = check_chapter_order_monotonic(chapters);
    if !was_monotonic {
        chapters.sort_by_key(|ch| ch.start_page);
    }
    was_monotonic
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

    #[test]
    fn reorder_fixes() {
        let mut chapters = vec![ch("c", 30), ch("a", 1), ch("b", 10)];
        assert!(!reorder_chapters_monotonic(&mut chapters));
        assert_eq!(chapters[0].chapter_id, "a");
        assert_eq!(chapters[1].chapter_id, "b");
        assert_eq!(chapters[2].chapter_id, "c");
    }
}

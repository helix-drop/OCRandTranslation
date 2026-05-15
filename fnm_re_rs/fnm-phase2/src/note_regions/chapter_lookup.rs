//! ←→ note_regions.py: _chapter_id_for_page / _nearest_prior_chapter
//! 薄封装层，将 fnm-core 的 chapter_lookup 适配到当前签名。

use fnm_core::chapters::{chapter_id_for_page, nearest_prior_chapter};
use fnm_core::records::ChapterRecord;

/// 返回 page_no 所属的 chapter_id。
pub fn find_chapter_id(page_no: i64, chapters: &[ChapterRecord]) -> String {
    chapter_id_for_page(chapters, page_no)
}

/// 返回 page_no 之前的最近章节的 chapter_id。
pub fn find_nearest_prior(page_no: i64, chapters: &[ChapterRecord]) -> String {
    nearest_prior_chapter(chapters, page_no)
}

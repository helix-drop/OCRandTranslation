//! book_type 聚合（footnote_only / endnote_only / mixed / no_notes）。

use fnm_core::records::ChapterNoteModeRecord;
use fnm_core::types::{BookType, NoteMode};

/// 从 chapter_note_modes 推断整本书的类型。
///
/// 返回 [`BookType`] enum 而非字符串字面量——下游 phase3 用 enum 比对
/// 避免拼写错误的 silent fallthrough（CLAUDE.md §12 分类源头唯一）。
pub fn infer_book_type(modes: &[ChapterNoteModeRecord]) -> BookType {
    let mut has_footnote = false;
    let mut has_endnote = false;
    for m in modes {
        match m.note_mode {
            NoteMode::FootnotePrimary => has_footnote = true,
            NoteMode::ChapterEndnotePrimary | NoteMode::BookEndnoteBound => has_endnote = true,
            NoteMode::NoNotes | NoteMode::ReviewRequired => {}
        }
    }
    match (has_footnote, has_endnote) {
        (true, true) => BookType::Mixed,
        (true, false) => BookType::FootnoteOnly,
        (false, true) => BookType::EndnoteOnly,
        (false, false) => BookType::NoNotes,
    }
}

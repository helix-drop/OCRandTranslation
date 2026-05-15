//! book_type 聚合（footnote_only / endnote_only / mixed / no_notes）。

use fnm_core::records::ChapterNoteModeRecord;
use fnm_core::types::NoteMode;

/// 从 chapter_note_modes 推断整本书的类型。
pub fn infer_book_type(modes: &[ChapterNoteModeRecord]) -> String {
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
        (true, true) => "mixed",
        (true, false) => "footnote_only",
        (false, true) => "endnote_only",
        (false, false) => "no_notes",
    }
    .into()
}

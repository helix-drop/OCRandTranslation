use std::collections::HashSet;

use fnm_core::records::ChapterNoteModeRecord;
use fnm_core::types::NoteMode;

pub fn infer_book_note_type_from_modes(
    chapter_note_modes: &[ChapterNoteModeRecord],
) -> &'static str {
    let modes: HashSet<&'static str> = chapter_note_modes
        .iter()
        .map(|r| match r.note_mode {
            NoteMode::FootnotePrimary => "footnote_primary",
            NoteMode::ChapterEndnotePrimary => "chapter_endnote_primary",
            NoteMode::BookEndnoteBound => "book_endnote_bound",
            NoteMode::NoNotes => "no_notes",
            NoteMode::ReviewRequired => "review_required",
        })
        .filter(|m| !m.is_empty() && *m != "no_notes")
        .collect();

    let has_footnote = modes.contains("footnote_primary");
    let has_endnote =
        modes.contains("chapter_endnote_primary") || modes.contains("book_endnote_bound");

    if has_footnote && has_endnote {
        "mixed"
    } else if has_endnote {
        "endnote_only"
    } else if has_footnote {
        "footnote_only"
    } else {
        "no_notes"
    }
}

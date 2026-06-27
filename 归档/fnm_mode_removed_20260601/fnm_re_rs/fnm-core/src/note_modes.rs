//! ←→ FNM_RE/shared/note_modes.py
//! note_mode 的 canonical ↔ DB alias 双向映射。

use crate::types::NoteMode;
use std::collections::HashMap;

/// Canonical → DB alias
pub fn to_db_alias(canonical: &str) -> &'static str {
    match canonical.trim() {
        "footnote_primary" => "footnote_primary",
        "chapter_endnote_primary" => "chapter_endnotes",
        "book_endnote_bound" => "book_endnotes",
        "no_notes" => "body_only",
        _ => "mixed_or_unclear",
    }
}

/// DB alias → Canonical NoteMode。未知 alias 返回 None。
pub fn from_db_alias(alias: &str) -> Option<NoteMode> {
    match alias.trim() {
        "footnote_primary" => Some(NoteMode::FootnotePrimary),
        "chapter_endnotes" => Some(NoteMode::ChapterEndnotePrimary),
        "book_endnotes" => Some(NoteMode::BookEndnoteBound),
        "body_only" => Some(NoteMode::NoNotes),
        _ => None,
    }
}

/// 生成空的 chapter mode summary（5 个 bucket 全 0）。
pub fn new_chapter_mode_summary() -> HashMap<String, i64> {
    [
        "footnote_primary",
        "chapter_endnotes",
        "book_endnotes",
        "body_only",
        "mixed_or_unclear",
    ]
    .iter()
    .map(|k| (k.to_string(), 0))
    .collect()
}

/// 按 canonical mode 把 summary 对应 bucket +1。
pub fn increment_chapter_mode_summary(summary: &mut HashMap<String, i64>, canonical: &str) {
    let bucket = to_db_alias(canonical).to_string();
    *summary.entry(bucket).or_insert(0) += 1;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn to_alias_known() {
        assert_eq!(to_db_alias("footnote_primary"), "footnote_primary");
        assert_eq!(to_db_alias("chapter_endnote_primary"), "chapter_endnotes");
        assert_eq!(to_db_alias("book_endnote_bound"), "book_endnotes");
        assert_eq!(to_db_alias("no_notes"), "body_only");
    }

    #[test]
    fn to_alias_unknown() {
        assert_eq!(to_db_alias("review_required"), "mixed_or_unclear");
        assert_eq!(to_db_alias(""), "mixed_or_unclear");
    }

    #[test]
    fn from_alias_roundtrip() {
        assert_eq!(
            from_db_alias("footnote_primary"),
            Some(NoteMode::FootnotePrimary)
        );
        assert_eq!(
            from_db_alias("chapter_endnotes"),
            Some(NoteMode::ChapterEndnotePrimary)
        );
        assert_eq!(
            from_db_alias("book_endnotes"),
            Some(NoteMode::BookEndnoteBound)
        );
        assert_eq!(from_db_alias("body_only"), Some(NoteMode::NoNotes));
    }

    #[test]
    fn from_alias_unknown() {
        assert_eq!(from_db_alias("garbage"), None);
    }

    #[test]
    fn summary_new_all_zero() {
        let s = new_chapter_mode_summary();
        assert_eq!(s.len(), 5);
        for v in s.values() {
            assert_eq!(*v, 0);
        }
    }

    #[test]
    fn summary_increment() {
        use std::collections::HashMap;
        let mut s: HashMap<String, i64> = new_chapter_mode_summary();
        increment_chapter_mode_summary(&mut s, "no_notes");
        increment_chapter_mode_summary(&mut s, "no_notes");
        increment_chapter_mode_summary(&mut s, "footnote_primary");
        assert_eq!(s.get("body_only"), Some(&2));
        assert_eq!(s.get("footnote_primary"), Some(&1));
        assert_eq!(s.get("mixed_or_unclear"), Some(&0));
    }
}

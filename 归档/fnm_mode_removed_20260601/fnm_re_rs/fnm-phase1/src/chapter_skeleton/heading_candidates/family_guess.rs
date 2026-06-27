//! ←→ heading_candidates.py: _heading_family_guess / _chapter_keyword_strength
//!
//! family 推断 + 章关键词强度。

use fnm_core::title::{guess_title_family, normalize_title};
use once_cell::sync::Lazy;
use regex::Regex;

static NOTES_HEADER_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?im)^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*)\s*$").unwrap()
});

static CHAPTER_KEYWORD_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?i)\b(?:chapter|chapitre|lecture|leçon|prologue|epilogue|postambule|appendix|appendices|part)\b",
    )
    .unwrap()
});

/// 非 body family 集合（Python `_FAMILY_NONBODY`）。
const FAMILY_NONBODY: &[&str] = &[
    "note",
    "other",
    "contents",
    "illustrations",
    "bibliography",
    "index",
    "appendix",
];

fn is_nonbody_family(family: &str) -> bool {
    FAMILY_NONBODY.contains(&family)
}

/// 推断 heading 的 family。完整 7 参数版。
/// ←→ Python `_heading_family_guess`
pub fn heading_family_guess(
    text: &str,
    page_no: i64,
    total_pages: i64,
    page_role: &str,
    source: &str,
    block_label: &str,
    top_band: bool,
) -> String {
    let title = normalize_title(text);
    if title.is_empty() {
        return "other".into();
    }

    if NOTES_HEADER_RE.is_match(&title) {
        return "note".into();
    }

    let family = guess_title_family(&title, page_no.max(1), total_pages.max(1));
    let family_str = if family.is_empty() { "body" } else { family };

    if source == "visual_toc" {
        return "chapter".into();
    }
    if source == "note_heading" {
        return "note".into();
    }
    if is_nonbody_family(family_str) {
        return family_str.to_string();
    }
    if page_role == "front_matter" && family_str == "front_matter" {
        return "front_matter".into();
    }
    if block_label == "doc_title" && top_band {
        return "chapter".into();
    }
    if CHAPTER_KEYWORD_RE.is_match(&title) {
        return "chapter".into();
    }

    let section_sources = ["markdown_heading", "ocr_block", "pdf_font_band"];
    if section_sources.contains(&source) {
        "section".into()
    } else {
        "chapter".into()
    }
}

/// 计算章关键词强度。
/// ←→ Python `_chapter_keyword_strength`
pub fn chapter_keyword_strength(title: &str) -> f64 {
    let text = normalize_title(title);
    if text.is_empty() {
        return 0.0;
    }
    let hits = CHAPTER_KEYWORD_RE.find_iter(&text).count();
    if hits >= 2 {
        2.0
    } else if hits == 1 {
        1.0
    } else {
        0.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn family_empty_text() {
        assert_eq!(
            heading_family_guess("", 1, 100, "body", "ocr_block", "doc_title", false),
            "other"
        );
    }

    #[test]
    fn family_notes_header() {
        assert_eq!(
            heading_family_guess("Notes", 50, 100, "body", "ocr_block", "", false),
            "note"
        );
    }

    #[test]
    fn family_visual_toc() {
        assert_eq!(
            heading_family_guess("Introduction", 5, 100, "body", "visual_toc", "", true),
            "chapter"
        );
    }

    #[test]
    fn family_note_heading_source() {
        assert_eq!(
            heading_family_guess("Some Note", 50, 100, "body", "note_heading", "", false),
            "note"
        );
    }

    #[test]
    fn family_nonbody_contents() {
        assert_eq!(
            heading_family_guess(
                "Bibliography",
                50,
                100,
                "body",
                "ocr_block",
                "doc_title",
                false
            ),
            "bibliography"
        );
    }

    #[test]
    fn family_front_matter_role_and_guess() {
        assert_eq!(
            heading_family_guess(
                "Acknowledgments",
                5,
                100,
                "front_matter",
                "ocr_block",
                "doc_title",
                false
            ),
            "front_matter"
        );
    }

    #[test]
    fn family_doc_title_top_band() {
        assert_eq!(
            heading_family_guess(
                "Chapter One",
                5,
                100,
                "body",
                "ocr_block",
                "doc_title",
                true
            ),
            "chapter"
        );
    }

    #[test]
    fn family_chapter_keyword() {
        assert_eq!(
            heading_family_guess(
                "Chapter 1: Introduction",
                5,
                100,
                "body",
                "ocr_block",
                "doc_title",
                false
            ),
            "chapter"
        );
    }

    #[test]
    fn family_section_fallback() {
        assert_eq!(
            heading_family_guess(
                "Some Random Text",
                5,
                100,
                "body",
                "ocr_block",
                "paragraph_title",
                false
            ),
            "section"
        );
    }

    #[test]
    fn keyword_strength_none() {
        assert_eq!(chapter_keyword_strength("Introduction"), 0.0);
    }

    #[test]
    fn keyword_strength_one() {
        assert_eq!(chapter_keyword_strength("Chapter 1"), 1.0);
    }

    #[test]
    fn keyword_strength_two() {
        assert_eq!(chapter_keyword_strength("Chapter and Part"), 2.0);
    }

    #[test]
    fn keyword_strength_empty() {
        assert_eq!(chapter_keyword_strength(""), 0.0);
    }
}

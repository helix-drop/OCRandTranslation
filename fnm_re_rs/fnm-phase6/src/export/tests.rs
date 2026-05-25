//! M1 导出辅助函数单元测试。

use std::collections::{HashMap, HashSet};

use fnm_core::records::{
    BodyAnchorRecord, ChapterNoteModeRecord, DiagnosticEntryRecord, DiagnosticPageRecord,
    ExportChapterRecord, NoteItemRecord, NoteLinkRecord, Phase5Structure, SectionHeadRecord,
    TranslationUnitRecord, UnitPageSegmentRecord, UnitParagraphRecord,
};
use fnm_core::types::NoteMode;

use super::body_render::{resolve_body_unit_text, rewrite_body_text_with_local_refs};
use super::book_type::infer_book_note_type_from_modes;
use super::chapter_pages::chapter_page_numbers;
use super::contract::{
    build_export_chapters, compute_export_semantic_contract, is_semantic_duplicate_candidate,
};
use super::diagnostic_text::diagnostic_machine_text_by_page;
use super::filename::{build_chapter_filename, sanitize_obsidian_chapter_title};
use super::footnote::{
    build_inline_footnote_targets, emit_local_note_definitions, emit_symbol_footnotes,
    is_numeric_note, note_marker, paragraph_render_text, split_numeric_note_ids,
    visible_segment_paragraphs,
};
use super::index_render::build_index_markdown;
use super::markdown_clean::{
    clean_export_html, escape_leading_asterisks, normalize_markdown_content,
    strip_trailing_image_only_block,
};
use super::note_lookup::{
    build_marker_by_note_id_for_chapter, build_note_kind_by_id_for_chapter,
    build_note_text_by_id_for_chapter,
};
use super::paragraph_key::normalized_paragraph_key;
use super::section_head::{
    build_section_heads_by_page, is_exportable_section_head, looks_like_sentence_section_heading,
};
use super::section_render::{build_section_markdown, ChapterExportInput, SectionMarkdownInput};
use super::title::format_chapter_title;

// ── paragraph_key ───────────────────────────────────────────────

#[test]
fn test_normalized_paragraph_key_strips_footnote_refs() {
    let result = normalized_paragraph_key("Some text [^1] with ref [^42].");
    assert_eq!(result, "some text with ref .");
}

#[test]
fn test_normalized_paragraph_key_compresses_whitespace() {
    let result = normalized_paragraph_key("  Hello   World  ");
    assert_eq!(result, "hello world");
}

#[test]
fn test_normalized_paragraph_key_empty() {
    assert_eq!(normalized_paragraph_key(""), "");
    assert_eq!(normalized_paragraph_key("  "), "");
}

// ── filename ────────────────────────────────────────────────────

#[test]
fn test_sanitize_obsidian_chapter_title_removes_invalid_chars() {
    let result = sanitize_obsidian_chapter_title("Chapter: 1 <Intro>");
    assert!(!result.contains('<'));
    assert!(!result.contains('>'));
    // `:` is also removed by the regex
    assert!(!result.contains(':'));
}

#[test]
fn test_sanitize_obsidian_chapter_title_replaces_dots() {
    let result = sanitize_obsidian_chapter_title("Ch.1.Introduction");
    assert!(!result.contains('.'));
}

#[test]
fn test_sanitize_obsidian_chapter_title_empty_fallback() {
    let result = sanitize_obsidian_chapter_title("");
    assert_eq!(result, "chapter");
}

#[test]
fn test_build_chapter_filename_basic() {
    let mut used = HashSet::new();
    let result = build_chapter_filename(1, "Introduction", &mut used);
    assert_eq!(result, "001-Introduction.md");
    assert!(used.contains("001-Introduction.md"));
}

#[test]
fn test_build_chapter_filename_dedup() {
    let mut used = HashSet::new();
    used.insert("001-Chapter.md".to_string());
    let result = build_chapter_filename(1, "Chapter", &mut used);
    // Since "001-Chapter.md" is taken, it should use suffix
    assert_eq!(result, "001-Chapter-2.md");
    assert!(used.contains("001-Chapter-2.md"));
}

#[test]
fn test_build_chapter_filename_zero_order() {
    let mut used = HashSet::new();
    let result = build_chapter_filename(-1, "Preface", &mut used);
    assert!(result.starts_with("000-"));
}

// ── markdown_clean ──────────────────────────────────────────────

#[test]
fn test_escape_leading_asterisks_single() {
    let result = escape_leading_asterisks("* hello");
    assert_eq!(result, "\\* hello");
}

#[test]
fn test_escape_leading_asterisks_double() {
    let result = escape_leading_asterisks("** bold");
    assert_eq!(result, "\\*\\* bold");
}

#[test]
fn test_escape_leading_asterisks_no_asterisk_at_start() {
    let result = escape_leading_asterisks("not * an asterisk");
    assert_eq!(result, "not * an asterisk");
}

#[test]
fn test_escape_leading_asterisks_multi_line() {
    let result = escape_leading_asterisks("normal\n* bullet");
    assert_eq!(result, "normal\n\\* bullet");
}

#[test]
fn test_normalize_markdown_content_empty() {
    assert_eq!(normalize_markdown_content(""), "");
    assert_eq!(normalize_markdown_content("  "), "");
}

#[test]
fn test_normalize_markdown_content_adds_newline() {
    assert_eq!(normalize_markdown_content("hello"), "hello\n");
    assert_eq!(normalize_markdown_content("  hello  "), "hello\n");
}

#[test]
fn test_clean_export_html_ordinal_sup() {
    let result = clean_export_html("Le<sup>e</sup> siècle");
    assert_eq!(result, "Lee siècle");
}

#[test]
fn test_clean_export_html_ordinal_sup_er() {
    let result = clean_export_html("1<sup>er</sup> janvier");
    assert_eq!(result, "1er janvier");
}

#[test]
fn test_clean_export_html_div_tags() {
    let result = clean_export_html("<div>content</div>");
    assert_eq!(result, "content");
}

#[test]
fn test_clean_export_html_any_sup() {
    let result = clean_export_html("text<sup>note</sup>end");
    assert_eq!(result, "textnoteend");
}

#[test]
fn test_strip_trailing_image_only_block_empty() {
    assert_eq!(strip_trailing_image_only_block(""), "");
    assert_eq!(strip_trailing_image_only_block("  "), "");
}

#[test]
fn test_strip_trailing_image_only_block_no_image() {
    let text = "Some text content.";
    assert_eq!(strip_trailing_image_only_block(text), text);
}

// ── title ───────────────────────────────────────────────────────
//
// 审计 #2 修复（2026-05-21）：原 `leçon du` 强制全大写规则已移除（违反逐书修补）。
// 当前 `format_chapter_title` 透传原标题；这 3 个测试验证透传语义。

#[test]
fn test_format_chapter_title_lecon_du_passthrough() {
    // 不再全大写——透传原始大小写
    let result = format_chapter_title("Leçon du 1", "");
    assert_eq!(result, "Leçon du 1");
}

#[test]
fn test_format_chapter_title_other_passthrough() {
    let result = format_chapter_title("Introduction", "");
    assert_eq!(result, "Introduction");
}

#[test]
fn test_format_chapter_title_empty() {
    let result = format_chapter_title("", "");
    assert_eq!(result, "");
}

#[test]
fn test_format_chapter_title_uppercase_input_preserved() {
    // 调用方若已传入全大写，则原样保留——本函数不再涉及大小写决策
    let result = format_chapter_title("LEÇON DU 10 JANVIER 1979", "");
    assert_eq!(result, "LEÇON DU 10 JANVIER 1979");
}

// ── book_type ───────────────────────────────────────────────────

fn make_mode_row(mode: NoteMode) -> ChapterNoteModeRecord {
    ChapterNoteModeRecord {
        chapter_id: "ch1".into(),
        note_mode: mode,
        region_ids: vec![],
        primary_region_scope: String::new(),
        has_footnote_band: false,
        has_endnote_region: false,
    }
}

#[test]
fn test_infer_book_note_type_footnote_only() {
    let modes = vec![make_mode_row(NoteMode::FootnotePrimary)];
    assert_eq!(infer_book_note_type_from_modes(&modes), "footnote_only");
}

#[test]
fn test_infer_book_note_type_endnote_only() {
    let modes = vec![make_mode_row(NoteMode::ChapterEndnotePrimary)];
    assert_eq!(infer_book_note_type_from_modes(&modes), "endnote_only");
}

#[test]
fn test_infer_book_note_type_mixed() {
    let modes = vec![
        make_mode_row(NoteMode::FootnotePrimary),
        make_mode_row(NoteMode::ChapterEndnotePrimary),
    ];
    assert_eq!(infer_book_note_type_from_modes(&modes), "mixed");
}

#[test]
fn test_infer_book_note_type_no_notes() {
    let modes = vec![make_mode_row(NoteMode::NoNotes)];
    assert_eq!(infer_book_note_type_from_modes(&modes), "no_notes");
}

#[test]
fn test_infer_book_note_type_book_endnote_bound() {
    let modes = vec![make_mode_row(NoteMode::BookEndnoteBound)];
    assert_eq!(infer_book_note_type_from_modes(&modes), "endnote_only");
}

#[test]
fn test_infer_book_note_type_empty() {
    assert_eq!(infer_book_note_type_from_modes(&[]), "no_notes");
}

// ── chapter_pages ───────────────────────────────────────────────

#[test]
fn test_chapter_page_numbers_explicit() {
    let result = chapter_page_numbers(&[1, 3, 5, 3], 0, 0);
    assert_eq!(result, vec![1, 3, 5]);
}

#[test]
fn test_chapter_page_numbers_from_range() {
    let result = chapter_page_numbers(&[], 10, 12);
    assert_eq!(result, vec![10, 11, 12]);
}

#[test]
fn test_chapter_page_numbers_empty() {
    let result = chapter_page_numbers(&[], 0, 0);
    assert!(result.is_empty());
}

#[test]
fn test_chapter_page_numbers_filters_negative() {
    let result = chapter_page_numbers(&[-1, 0, 2, 3], 0, 0);
    assert_eq!(result, vec![2, 3]);
}

// ── note_lookup ─────────────────────────────────────────────────

#[test]
fn test_build_note_kind_by_id_for_chapter_simple() {
    use fnm_core::records::TranslationUnitRecord;
    let units = vec![TranslationUnitRecord {
        section_id: "ch1".into(),
        kind: "footnote".into(),
        note_id: "n1".into(),
        ..Default::default()
    }];
    let result = build_note_kind_by_id_for_chapter(Some("ch1"), &units);
    let mut expected = HashMap::new();
    expected.insert("n1".into(), "footnote".into());
    assert_eq!(result, expected);
}

#[test]
fn test_build_marker_by_note_id_for_chapter_simple() {
    use fnm_core::records::NoteLinkRecord;
    let links = vec![NoteLinkRecord {
        chapter_id: "ch1".into(),
        note_item_id: "n1".into(),
        marker: "42".into(),
        ..Default::default()
    }];
    let result = build_marker_by_note_id_for_chapter("ch1", &links);
    let mut expected = HashMap::new();
    expected.insert("n1".into(), "42".into());
    assert_eq!(result, expected);
}

// ── diagnostic_text ─────────────────────────────────────────────

#[test]
fn test_diagnostic_machine_text_by_page_empty() {
    assert!(diagnostic_machine_text_by_page(&[]).is_empty());
}

#[test]
fn test_diagnostic_machine_text_by_page_with_entries() {
    let pages = vec![DiagnosticPageRecord {
        _page_bp: 42,
        _page_entries: vec![DiagnosticEntryRecord {
            _translation_source: "machine".into(),
            translation: "Hello world".into(),
            ..Default::default()
        }],
        ..Default::default()
    }];
    let result = diagnostic_machine_text_by_page(&pages);
    let mut expected = HashMap::new();
    expected.insert(42i64, "Hello world".into());
    assert_eq!(result, expected);
}

#[test]
fn test_diagnostic_machine_text_by_page_skips_source() {
    let pages = vec![DiagnosticPageRecord {
        _page_bp: 1,
        _page_entries: vec![DiagnosticEntryRecord {
            _translation_source: "source".into(),
            translation: "skip me".into(),
            ..Default::default()
        }],
        ..Default::default()
    }];
    let result = diagnostic_machine_text_by_page(&pages);
    assert!(result.is_empty());
}

// ── section_head ────────────────────────────────────────────────

#[test]
fn test_looks_like_sentence_section_heading_empty() {
    assert!(looks_like_sentence_section_heading(""));
}

#[test]
fn test_looks_like_sentence_section_heading_long_text() {
    let long = "A".repeat(120);
    assert!(looks_like_sentence_section_heading(&long));
}

#[test]
fn test_looks_like_sentence_section_heading_ends_with_exclamation() {
    assert!(looks_like_sentence_section_heading("Hello!"));
}

#[test]
fn test_looks_like_sentence_section_heading_short_phrase() {
    assert!(!looks_like_sentence_section_heading("The Early Modern Era"));
}

fn make_section_head(chapter_id: &str, title: &str, page_no: i64) -> SectionHeadRecord {
    SectionHeadRecord {
        section_head_id: String::new(),
        chapter_id: chapter_id.into(),
        title: title.into(),
        page_no,
        level: 0,
        source: String::new(),
    }
}

#[test]
fn test_is_exportable_section_head_empty() {
    let head = make_section_head("ch1", "", 0);
    assert!(!is_exportable_section_head(&head));
}

#[test]
fn test_is_exportable_section_head_asterisk() {
    let head = make_section_head("ch1", "*", 1);
    assert!(!is_exportable_section_head(&head));
}

#[test]
fn test_is_exportable_section_head_valid() {
    let head = make_section_head("ch1", "The Origins of Modern Thought", 10);
    assert!(is_exportable_section_head(&head));
}

#[test]
fn test_build_section_heads_by_page_filters_wrong_chapter() {
    let heads = vec![make_section_head("ch2", "Wrong Chapter", 5)];
    let pages: HashSet<i64> = [1, 2, 5].iter().copied().collect();
    let result = build_section_heads_by_page("ch1", &heads, &pages);
    assert!(result.is_empty());
}

// ── body_render ─────────────────────────────────────────────────

#[test]
fn test_resolve_body_unit_text_uses_translated() {
    use fnm_core::records::TranslationUnitRecord;
    let unit = TranslationUnitRecord {
        translated_text: "Translated text.".into(),
        source_text: "Source text.".into(),
        ..Default::default()
    };
    let result = resolve_body_unit_text(&unit, false, &HashMap::new());
    assert_eq!(result, "Translated text.");
}

#[test]
fn test_resolve_body_unit_text_falls_back_to_source() {
    use fnm_core::records::TranslationUnitRecord;
    let unit = TranslationUnitRecord {
        translated_text: "".into(),
        source_text: "Source text.".into(),
        ..Default::default()
    };
    let result = resolve_body_unit_text(&unit, false, &HashMap::new());
    assert_eq!(result, "Source text.");
}

// ── index_render ────────────────────────────────────────────────

#[test]
fn test_build_index_markdown_basic() {
    let chapters = vec![ExportChapterRecord {
        path: "chapters/001-Intro.md".into(),
        title: "Introduction".into(),
        ..Default::default()
    }];
    let result = build_index_markdown(&chapters);
    assert!(result.contains("# 目录"));
    assert!(result.contains("Introduction"));
    assert!(result.contains("chapters/001-Intro.md"));
}

#[test]
fn test_build_index_markdown_empty_path_skipped() {
    let chapters = vec![
        ExportChapterRecord {
            path: "".into(),
            title: "Skipped".into(),
            ..Default::default()
        },
        ExportChapterRecord {
            path: "chapters/001-Real.md".into(),
            title: "Real".into(),
            ..Default::default()
        },
    ];
    let result = build_index_markdown(&chapters);
    assert!(!result.contains("Skipped"));
    assert!(result.contains("Real"));
}

#[test]
fn test_build_index_markdown_escapes_brackets() {
    let chapters = vec![ExportChapterRecord {
        path: "chapters/001-Test.md".into(),
        title: "Title [with] brackets".into(),
        ..Default::default()
    }];
    let result = build_index_markdown(&chapters);
    assert!(result.contains("\\[with\\]"));
}

// ── note_lookup: build_note_text_by_id_for_chapter ──────────────

#[test]
fn test_build_note_text_by_id_prefers_translated() {
    let units = vec![TranslationUnitRecord {
        section_id: "ch1".into(),
        kind: "footnote".into(),
        note_id: "n1".into(),
        translated_text: "Translated footnote.".into(),
        source_text: "Source footnote.".into(),
        ..Default::default()
    }];
    let result = build_note_text_by_id_for_chapter(Some("ch1"), &units);
    assert!(result.contains_key("n1"));
    // sanitize_note_text strips leading markers; translated is preferred
    let text = result.get("n1").unwrap();
    assert!(text.contains("Translated footnote"));
}

#[test]
fn test_build_note_text_by_id_skips_wrong_chapter() {
    let units = vec![TranslationUnitRecord {
        section_id: "ch2".into(),
        kind: "footnote".into(),
        note_id: "n1".into(),
        translated_text: "Wrong chapter.".into(),
        ..Default::default()
    }];
    let result = build_note_text_by_id_for_chapter(Some("ch1"), &units);
    assert!(result.is_empty());
}

#[test]
fn test_build_note_text_by_id_none_chapter_returns_all() {
    let units = vec![TranslationUnitRecord {
        section_id: "ch1".into(),
        kind: "endnote".into(),
        note_id: "n1".into(),
        translated_text: "Endnote text.".into(),
        ..Default::default()
    }];
    let result = build_note_text_by_id_for_chapter(None, &units);
    assert_eq!(result.len(), 1);
}

// ── note_lookup: build_note_kind_by_id extra ────────────────────

#[test]
fn test_build_note_kind_by_id_skips_non_footnote_endnote() {
    let units = vec![TranslationUnitRecord {
        section_id: "ch1".into(),
        kind: "body".into(),
        note_id: "n1".into(),
        ..Default::default()
    }];
    let result = build_note_kind_by_id_for_chapter(Some("ch1"), &units);
    assert!(result.is_empty());
}

// ── note_lookup: build_marker_by_note_id extra ──────────────────

#[test]
fn test_build_marker_by_note_id_skips_empty_marker() {
    let links = vec![NoteLinkRecord {
        chapter_id: "ch1".into(),
        note_item_id: "n1".into(),
        marker: "".into(),
        ..Default::default()
    }];
    let result = build_marker_by_note_id_for_chapter("ch1", &links);
    assert!(result.is_empty());
}

// ── section_head: build_section_heads_by_page extra ─────────────

#[test]
fn test_build_section_heads_by_page_deduplicates() {
    let heads = vec![
        make_section_head("ch1", "Heading A", 5),
        make_section_head("ch1", "heading a", 5), // same page, same lowercase title
    ];
    let pages: HashSet<i64> = [5].iter().copied().collect();
    let result = build_section_heads_by_page("ch1", &heads, &pages);
    // Only one entry because "Heading A" and "heading a" dedup on lowercase
    assert_eq!(result.get(&5).unwrap().len(), 1);
}

// ── body_render: rewrite_body_text_with_local_refs ──────────────

#[test]
fn test_rewrite_body_text_replaces_frozen_note_ref() {
    let mut note_text_by_id = HashMap::new();
    note_text_by_id.insert("n1".into(), "footnote text".into());
    let mut note_kind_by_id = HashMap::new();
    note_kind_by_id.insert("n1".into(), "endnote".into());
    let marker_note_sequences: HashMap<String, Vec<String>> = HashMap::new();
    let mut local_ref_numbers: HashMap<String, i64> = HashMap::new();
    local_ref_numbers.insert("n1".into(), 42);
    let mut ordered_note_ids: Vec<String> = vec!["n1".into()];

    let result = rewrite_body_text_with_local_refs(
        "Body {{NOTE_REF:n1}} text.",
        &note_text_by_id,
        &note_kind_by_id,
        &marker_note_sequences,
        &mut local_ref_numbers,
        &mut ordered_note_ids,
        None,
        None,
    );
    // The frozen ref should be replaced with [^42]
    assert!(result.contains("[^42]"), "Expected [^42] in: {result}");
    assert!(!result.contains("{{NOTE_REF:n1}}"));
}

#[test]
fn test_rewrite_body_text_no_refs_unchanged() {
    let note_text_by_id: HashMap<String, String> = HashMap::new();
    let note_kind_by_id: HashMap<String, String> = HashMap::new();
    let marker_note_sequences: HashMap<String, Vec<String>> = HashMap::new();
    let mut local_ref_numbers: HashMap<String, i64> = HashMap::new();
    let mut ordered_note_ids: Vec<String> = Vec::new();

    let result = rewrite_body_text_with_local_refs(
        "Plain text without refs.",
        &note_text_by_id,
        &note_kind_by_id,
        &marker_note_sequences,
        &mut local_ref_numbers,
        &mut ordered_note_ids,
        None,
        None,
    );
    assert_eq!(result, "Plain text without refs.");
}

// ── section_render: build_section_markdown ───────────────────────

fn make_chapter_export_input(chapter_id: &str, title: &str) -> ChapterExportInput {
    ChapterExportInput {
        chapter_id: chapter_id.into(),
        title: title.into(),
        pages: vec![],
        start_page: 1,
        end_page: 1,
    }
}

fn make_body_unit(chapter_id: &str, text: &str) -> TranslationUnitRecord {
    TranslationUnitRecord {
        unit_id: "u1".into(),
        section_id: chapter_id.into(),
        kind: "body".into(),
        translated_text: text.into(),
        page_start: 1,
        page_end: 1,
        ..Default::default()
    }
}

#[test]
fn test_build_section_markdown_footnote_primary_produces_pending() {
    let chapter = make_chapter_export_input("ch1", "Test");
    let input = SectionMarkdownInput {
        chapter: &chapter,
        section_heads: &[],
        body_units: &[],
        note_units: &[],
        matched_links: &[],
        note_items_by_id: &HashMap::new(),
        body_anchors_by_id: &HashMap::new(),
        include_diagnostic_entries: false,
        diagnostic_machine_by_page: &HashMap::new(),
        book_type: "mixed",
        chapter_note_mode: "footnote_primary",
        skipped_note_ids: None,
    };
    let result = build_section_markdown(&input).unwrap();
    assert!(result.content.contains("## Test"));
    assert!(result.content.contains("[待翻译]"));
    assert_eq!(result.contract_summary.get("local_ref_count"), Some(&0));
}

#[test]
fn test_build_section_markdown_basic_produces_content() {
    let chapter = make_chapter_export_input("ch1", "Introduction");
    let body_units = vec![make_body_unit("ch1", "Hello world.")];
    let note_units: Vec<TranslationUnitRecord> = vec![];
    let input = SectionMarkdownInput {
        chapter: &chapter,
        section_heads: &[],
        body_units: &body_units,
        note_units: &note_units,
        matched_links: &[],
        note_items_by_id: &HashMap::new(),
        body_anchors_by_id: &HashMap::new(),
        include_diagnostic_entries: false,
        diagnostic_machine_by_page: &HashMap::new(),
        book_type: "footnote_only",
        chapter_note_mode: "footnote_primary",
        skipped_note_ids: None,
    };
    let result = build_section_markdown(&input).unwrap();
    assert!(result.content.contains("## Introduction"));
    assert!(result.content.contains("Hello world."));
    // contract_summary should have local_ref_count = 0
    assert_eq!(result.contract_summary.get("local_ref_count"), Some(&0));
}

#[test]
fn test_build_section_markdown_no_body_produces_pending() {
    let chapter = make_chapter_export_input("ch1", "Empty Chapter");
    let body_units: Vec<TranslationUnitRecord> = vec![];
    let note_units: Vec<TranslationUnitRecord> = vec![];
    let input = SectionMarkdownInput {
        chapter: &chapter,
        section_heads: &[],
        body_units: &body_units,
        note_units: &note_units,
        matched_links: &[],
        note_items_by_id: &HashMap::new(),
        body_anchors_by_id: &HashMap::new(),
        include_diagnostic_entries: false,
        diagnostic_machine_by_page: &HashMap::new(),
        book_type: "footnote_only",
        chapter_note_mode: "footnote_primary",
        skipped_note_ids: None,
    };
    let result = build_section_markdown(&input).unwrap();
    assert!(result.content.contains("## Empty Chapter"));
    // No body → PENDING_TRANSLATION_TEXT inserted
    assert!(result.content.contains("[待翻译]"));
}

// ── contract: is_semantic_duplicate_candidate ────────────────────

#[test]
fn test_is_semantic_duplicate_candidate_empty_false() {
    assert!(!is_semantic_duplicate_candidate(""));
}

#[test]
fn test_is_semantic_duplicate_candidate_heading_false() {
    assert!(!is_semantic_duplicate_candidate("### Introduction"));
}

#[test]
fn test_is_semantic_duplicate_candidate_short_text_false() {
    assert!(!is_semantic_duplicate_candidate("Short text."));
}

#[test]
fn test_is_semantic_duplicate_candidate_long_with_punct_true() {
    let text = "This is a sufficiently long paragraph that exceeds the minimum word and character thresholds. It contains multiple sentences that should trigger the punctuation check. The quick brown fox jumps over the lazy dog near the riverbank.";
    assert!(is_semantic_duplicate_candidate(text));
}

#[test]
fn test_is_semantic_duplicate_candidate_long_no_punct_false() {
    let text = "this is a sufficiently long paragraph without any punctuation marks exceeding thresholds for duplicate detection";
    assert!(!is_semantic_duplicate_candidate(text));
}

// ── contract: build_export_chapters ──────────────────────────────

#[test]
fn test_build_export_chapters_empty_phase5() {
    let phase5 = Phase5Structure::default();
    let (chapters, _summary) = build_export_chapters(&phase5, false, None).unwrap();
    assert!(chapters.is_empty());
}

#[test]
fn test_build_export_chapters_single_chapter_no_body() {
    use fnm_core::records::ChapterRecord;
    use fnm_core::types::ChapterSource;

    let chapter = ChapterRecord {
        chapter_id: "ch1".into(),
        title: "Test Chapter".into(),
        start_page: 1,
        end_page: 1,
        pages: vec![],
        source: ChapterSource::Fallback,
        boundary_state: fnm_core::types::BoundaryState::Ready,
    };
    let mut phase5 = Phase5Structure::default();
    phase5.chapters.push(chapter);
    let (records, _summary) = build_export_chapters(&phase5, false, None).unwrap();
    assert_eq!(records.len(), 1);
    let rec = &records[0];
    assert_eq!(rec.order, 1);
    assert_eq!(rec.section_id, "ch1");
    assert!(rec.path.starts_with("chapters/"));
}

// ── contract: compute_export_semantic_contract ───────────────────

#[test]
fn test_compute_export_semantic_contract_clean() {
    let chapter = ExportChapterRecord {
        section_id: "ch1".into(),
        title: "Chapter 1".into(),
        ..Default::default()
    };
    let mut files = HashMap::new();
    files.insert("001-test.md".into(), "Some body text.".into());
    let result = compute_export_semantic_contract(&[chapter], &files);
    assert!(result.get("export_semantic_contract_ok") == Some(&true));
    assert!(result.get("front_matter_leak_detected") == Some(&false));
    assert!(result.get("toc_residue_detected") == Some(&false));
}

// ── footnote: visible_segment_paragraphs ─────────────────────────

#[test]
fn test_visible_segment_paragraphs_filters_consumed() {
    let p1 = UnitParagraphRecord {
        consumed_by_prev: true,
        ..Default::default()
    };
    let p2 = UnitParagraphRecord {
        consumed_by_prev: false,
        ..Default::default()
    };
    let segment = UnitPageSegmentRecord {
        paragraphs: vec![p1.clone(), p2.clone()],
        ..Default::default()
    };
    let visible = visible_segment_paragraphs(&segment);
    assert_eq!(visible.len(), 1);
    assert!(!visible[0].consumed_by_prev);
}

#[test]
fn test_visible_segment_paragraphs_all_visible() {
    let segment = UnitPageSegmentRecord {
        paragraphs: vec![UnitParagraphRecord::default()],
        ..Default::default()
    };
    let visible = visible_segment_paragraphs(&segment);
    assert_eq!(visible.len(), 1);
}

// ── footnote: paragraph_render_text ──────────────────────────────

#[test]
fn test_paragraph_render_text_prefers_translated() {
    let p = UnitParagraphRecord {
        translated_text: "translated".into(),
        display_text: "display".into(),
        source_text: "source".into(),
        ..Default::default()
    };
    assert_eq!(paragraph_render_text(&p), "translated");
}

#[test]
fn test_paragraph_render_text_falls_back_to_display() {
    let p = UnitParagraphRecord {
        translated_text: "".into(),
        display_text: "display".into(),
        source_text: "source".into(),
        ..Default::default()
    };
    assert_eq!(paragraph_render_text(&p), "display");
}

#[test]
fn test_paragraph_render_text_falls_back_to_source() {
    let p = UnitParagraphRecord {
        translated_text: "".into(),
        display_text: "".into(),
        source_text: "source".into(),
        ..Default::default()
    };
    assert_eq!(paragraph_render_text(&p), "source");
}

// ── footnote: note_marker / is_numeric_note / split_numeric_note_ids ─

#[test]
fn test_note_marker_found() {
    let mut items = HashMap::new();
    items.insert(
        "n1".into(),
        NoteItemRecord {
            note_item_id: "n1".into(),
            marker: "42".into(),
            ..Default::default()
        },
    );
    assert_eq!(note_marker("n1", &items), "42");
}

#[test]
fn test_note_marker_not_found() {
    let items: HashMap<String, NoteItemRecord> = HashMap::new();
    assert_eq!(note_marker("n1", &items), "");
}

#[test]
fn test_is_numeric_note_true() {
    let mut items = HashMap::new();
    items.insert(
        "n1".into(),
        NoteItemRecord {
            note_item_id: "n1".into(),
            marker: "123".into(),
            ..Default::default()
        },
    );
    assert!(is_numeric_note("n1", &items));
}

#[test]
fn test_is_numeric_note_symbol_false() {
    let mut items = HashMap::new();
    items.insert(
        "n1".into(),
        NoteItemRecord {
            note_item_id: "n1".into(),
            marker: "*".into(),
            ..Default::default()
        },
    );
    assert!(!is_numeric_note("n1", &items));
}

#[test]
fn test_split_numeric_note_ids_mixed() {
    let mut items = HashMap::new();
    items.insert(
        "n1".into(),
        NoteItemRecord {
            note_item_id: "n1".into(),
            marker: "1".into(),
            ..Default::default()
        },
    );
    items.insert(
        "n2".into(),
        NoteItemRecord {
            note_item_id: "n2".into(),
            marker: "*".into(),
            ..Default::default()
        },
    );
    let (nums, syms) = split_numeric_note_ids(&["n1".into(), "n2".into()], &items);
    assert_eq!(nums, vec!["n1"]);
    assert_eq!(syms, vec!["n2"]);
}

#[test]
fn test_split_numeric_note_ids_empty() {
    let items = HashMap::new();
    let (nums, syms) = split_numeric_note_ids(&[], &items);
    assert!(nums.is_empty());
    assert!(syms.is_empty());
}

// ── footnote: emit_symbol_footnotes ──────────────────────────────

#[test]
fn test_emit_symbol_footnotes_basic() {
    let mut items = HashMap::new();
    items.insert(
        "n1".into(),
        NoteItemRecord {
            note_item_id: "n1".into(),
            marker: "*".into(),
            chapter_id: "ch1".into(),
            ..Default::default()
        },
    );
    let mut texts = HashMap::new();
    texts.insert("n1".into(), "Footnote text.".into());
    let mut lines: Vec<String> = Vec::new();
    let mut emitted: HashSet<String> = HashSet::new();
    let count = emit_symbol_footnotes(&["n1".into()], &mut lines, &mut emitted, &texts, &items);
    assert_eq!(count, 1);
    assert!(lines.iter().any(|l| l.contains("[footnote]")));
    assert!(lines.iter().any(|l| l.contains("Footnote text.")));
}

#[test]
fn test_emit_symbol_footnotes_already_emitted() {
    let items: HashMap<String, NoteItemRecord> = HashMap::new();
    let texts = HashMap::new();
    let mut lines: Vec<String> = Vec::new();
    let mut emitted: HashSet<String> = HashSet::new();
    emitted.insert("n1".into());
    let count = emit_symbol_footnotes(&["n1".into()], &mut lines, &mut emitted, &texts, &items);
    assert_eq!(count, 0);
}

// ── footnote: emit_local_note_definitions ────────────────────────

#[test]
fn test_emit_local_note_definitions_basic() {
    let mut items = HashMap::new();
    items.insert(
        "n1".into(),
        NoteItemRecord {
            note_item_id: "n1".into(),
            marker: "1".into(),
            ..Default::default()
        },
    );
    let mut texts: HashMap<String, String> = HashMap::new();
    texts.insert("n1".into(), "Note text.".into());
    let mut ref_nums: HashMap<String, i64> = HashMap::new();
    ref_nums.insert("n1".into(), 1);
    let mut lines: Vec<String> = Vec::new();
    let mut emitted: HashSet<String> = HashSet::new();
    let count = emit_local_note_definitions(
        &["n1".into()],
        &mut lines,
        &mut emitted,
        &ref_nums,
        &texts,
        None,
        &items,
    );
    assert_eq!(count, 1);
    assert!(lines.iter().any(|l| l.contains("[^1]:")));
}

#[test]
fn test_emit_local_note_definitions_skip_unreferenced() {
    let items = HashMap::new();
    let mut texts: HashMap<String, String> = HashMap::new();
    texts.insert("n1".into(), "text".into());
    let ref_nums: HashMap<String, i64> = HashMap::new(); // no ref number → skip
    let mut lines: Vec<String> = Vec::new();
    let mut emitted: HashSet<String> = HashSet::new();
    let count = emit_local_note_definitions(
        &["n1".into()],
        &mut lines,
        &mut emitted,
        &ref_nums,
        &texts,
        None,
        &items,
    );
    assert_eq!(count, 0);
}

// ── footnote: build_inline_footnote_targets ──────────────────────

#[test]
fn test_build_inline_footnote_targets_empty_chapter() {
    let (attached, fallback) = build_inline_footnote_targets(
        "ch1",
        &[],
        &HashMap::new(),
        &HashMap::new(),
        &HashMap::new(),
    );
    assert!(attached.is_empty());
    assert!(fallback.is_empty());
}

#[test]
fn test_build_inline_footnote_targets_attached_non_synthetic() {
    use fnm_core::types::{LinkStatus, NoteKind};
    let mut anchors = HashMap::new();
    anchors.insert(
        "a1".into(),
        BodyAnchorRecord {
            anchor_id: "a1".into(),
            page_no: 5,
            paragraph_index: 2,
            synthetic: false,
            ..Default::default()
        },
    );
    let link = NoteLinkRecord {
        link_id: "l1".into(),
        chapter_id: "ch1".into(),
        note_item_id: "n1".into(),
        anchor_id: "a1".into(),
        note_kind: NoteKind::Footnote,
        status: LinkStatus::Matched,
        ..Default::default()
    };
    let mut items = HashMap::new();
    items.insert(
        "n1".into(),
        NoteItemRecord {
            note_item_id: "n1".into(),
            ..Default::default()
        },
    );
    let mut texts = HashMap::new();
    texts.insert("n1".into(), "Note text.".into());
    let (attached, fallback) =
        build_inline_footnote_targets("ch1", &[link], &items, &anchors, &texts);
    assert!(attached.contains_key(&(5, 2)));
    assert!(fallback.is_empty());
}

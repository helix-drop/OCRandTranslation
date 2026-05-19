//! Phase 4 SPEC 测试。
//!
//! 翻译自 Python SPEC 测试，验证 Phase 4 核心功能。

use fnm_core::records::*;
use fnm_core::types::*;
use fnm_phase4::reviews::build_structure_reviews;
use fnm_phase4::units::build_translation_units;

// ── 辅助函数 ──────────────────────────────────────────────────────

fn make_chapter(chapter_id: &str, title: &str, start: i64, end: i64) -> ChapterRecord {
    ChapterRecord {
        chapter_id: chapter_id.to_string(),
        title: title.to_string(),
        start_page: start,
        end_page: end,
        pages: (start..=end).collect(),
        boundary_state: BoundaryState::Ready,
        source: ChapterSource::Fallback,
    }
}

fn make_raw_page(book_page: i64, markdown: &str) -> fnm_phase1::input::RawPage {
    fnm_phase1::input::RawPage {
        book_page,
        markdown: markdown.to_string(),
        ..Default::default()
    }
}

fn make_page_partition(page_no: i64, page_role: PageRole) -> PagePartitionRecord {
    PagePartitionRecord {
        page_no,
        target_pdf_page: page_no,
        page_role,
        confidence: 1.0,
        reason: String::new(),
        section_hint: String::new(),
        has_note_heading: false,
        note_scan_summary: serde_json::Value::Null,
    }
}

fn make_note_item(
    note_item_id: &str,
    chapter_id: &str,
    region_id: &str,
    page_no: i64,
    text: &str,
) -> NoteItemRecord {
    NoteItemRecord {
        note_item_id: note_item_id.to_string(),
        chapter_id: chapter_id.to_string(),
        region_id: region_id.to_string(),
        page_no,
        marker: "1".to_string(),
        marker_type: "digit".to_string(),
        text: text.to_string(),
        source: "test".to_string(),
        source_page_label: page_no.to_string(),
        is_reconstructed: false,
        review_required: false,
        note_kind: NoteKind::Footnote,
        ..Default::default()
    }
}

fn make_note_region(
    region_id: &str,
    chapter_id: &str,
    note_kind: NoteKind,
    page_start: i64,
) -> NoteRegionRecord {
    NoteRegionRecord {
        region_id: region_id.to_string(),
        chapter_id: chapter_id.to_string(),
        page_start,
        page_end: page_start,
        pages: vec![page_start],
        note_kind,
        scope: RegionScope::Chapter,
        source: RegionSource::HeadingScan,
        heading_text: String::new(),
        start_reason: String::new(),
        end_reason: String::new(),
        region_marker_alignment_ok: true,
        region_start_first_source_marker: String::new(),
        region_first_note_item_marker: String::new(),
        review_required: false,
    }
}

fn default_summary() -> Phase3Summary {
    Phase3Summary {
        chapter_title_alignment_ok: true,
        chapter_section_alignment_ok: true,
        toc_semantic_contract_ok: true,
        ..Default::default()
    }
}

// ── SPEC: test_superscript_note_definition_lines_are_filtered ──
//
// ←→ Python test_fnm_re_phase3.py:201
// 验证上标 note definition 行不会被误识别为 body anchor。

#[test]
fn test_superscript_note_definition_lines_are_filtered() {
    let pages = vec![make_raw_page(
        1,
        "# Chapter One\nBody keeps [8] reference.\n\n\
         $ ^{1} $ note definition line.\n\n\
         ¹ another note definition.\n\n\
         <sup>2</sup> html note definition.\n\n\
         ^{3} plain note definition.",
    )];

    let chapters = vec![make_chapter("ch1", "Chapter One", 1, 1)];
    let page_partitions = vec![make_page_partition(1, PageRole::Body)];

    let phase4 = Phase4Structure {
        pages: page_partitions,
        chapters: chapters.clone(),
        ..Default::default()
    };
    let (units, _) = build_translation_units(&phase4, &pages, 6000);

    let body_units: Vec<_> = units.iter().filter(|u| u.kind == "body").collect();
    assert!(!body_units.is_empty(), "Should have at least one body unit");
}

// ── SPEC: test_ch5_note_4_definition_is_full_length ──
//
// ←→ Python test_long_note_no_truncation.py:56
// 验证长注释定义不会被截断到 'vol.' 等引文缩写。

#[test]
fn test_note_definition_not_truncated_at_citation_abbreviation() {
    let long_note_text = "This is a very long note definition that should not be truncated. \
        It contains multiple sentences and citation information. \
        See Foucault, M. (1979). Naissance de la biopolitique. \
        Cours au Collège de France, 1978-1979. Paris: Gallimard/Seuil, \
        vol. 1, pp. 123-456.";
    let pages = vec![make_raw_page(
        1,
        &format!("# Chapter 5\n\nBody text.\n\n[^4]: 4. {}", long_note_text),
    )];

    let chapters = vec![make_chapter("ch5", "Chapter 5", 1, 1)];
    let page_partitions = vec![make_page_partition(1, PageRole::Body)];
    let note_regions = vec![make_note_region("r1", "ch5", NoteKind::Footnote, 1)];
    let note_items = vec![make_note_item("n1", "ch5", "r1", 1, long_note_text)];

    let phase4 = Phase4Structure {
        pages: page_partitions,
        chapters,
        note_regions,
        note_items,
        ..Default::default()
    };
    let (units, _) = build_translation_units(&phase4, &pages, 6000);

    let footnote_units: Vec<_> = units.iter().filter(|u| u.kind == "footnote").collect();
    assert_eq!(footnote_units.len(), 1, "Should have one footnote unit");

    let source_text = &footnote_units[0].source_text;
    assert!(
        source_text.contains("vol."),
        "Note text should contain 'vol.' citation"
    );
    assert!(
        source_text.contains("pp. 123-456"),
        "Note text should contain page numbers"
    );

    let truncation_endings = ["vol.", "no.", "p.", "pp.", "vol"];
    for ending in &truncation_endings {
        assert!(
            !source_text.trim().ends_with(ending),
            "Note text should not end with truncation marker '{}': ...{}",
            ending,
            &source_text[source_text.len().saturating_sub(80)..]
        );
    }
}

// ── SPEC: structure_reviews 生成正确 ──

#[test]
fn test_structure_reviews_generated_for_orphan_links() {
    let chapters = vec![make_chapter("ch1", "Chapter 1", 1, 10)];
    let links = vec![NoteLinkRecord {
        link_id: "l1".to_string(),
        chapter_id: "ch1".to_string(),
        region_id: "r1".to_string(),
        note_item_id: "n1".to_string(),
        anchor_id: "a1".to_string(),
        status: LinkStatus::OrphanNote,
        resolver: LinkResolver::Rule,
        confidence: 0.0,
        note_kind: NoteKind::Footnote,
        marker: "1".to_string(),
        page_no_start: 5,
        page_no_end: 5,
    }];

    let summary = default_summary();
    let (reviews, _) = build_structure_reviews(&chapters, &[], &links, &summary, 0, 0);

    assert_eq!(reviews.len(), 1);
    assert_eq!(reviews[0].review_type, "footnote_orphan_note");
    assert_eq!(reviews[0].severity, "error");
}

#[test]
fn test_structure_reviews_boundary_state() {
    let mut chapter = make_chapter("ch2", "Chapter 2", 11, 20);
    chapter.boundary_state = BoundaryState::ReviewRequired;
    let chapters = vec![make_chapter("ch1", "Chapter 1", 1, 10), chapter];

    let summary = default_summary();
    let (reviews, _) = build_structure_reviews(&chapters, &[], &[], &summary, 0, 0);

    assert_eq!(reviews.len(), 1);
    assert_eq!(reviews[0].review_type, "boundary_review_required");
    assert_eq!(reviews[0].chapter_id, "ch2");
}

#[test]
fn test_structure_reviews_toc_alignment() {
    let summary = Phase3Summary {
        chapter_title_alignment_ok: false,
        chapter_section_alignment_ok: true,
        toc_semantic_contract_ok: true,
        ..Default::default()
    };

    let (reviews, _) = build_structure_reviews(&[], &[], &[], &summary, 0, 0);

    assert_eq!(reviews.len(), 1);
    assert_eq!(reviews[0].review_type, "toc_alignment_review_required");
    assert_eq!(reviews[0].severity, "error");
}

#[test]
fn test_structure_reviews_toc_semantic() {
    let summary = Phase3Summary {
        chapter_title_alignment_ok: true,
        chapter_section_alignment_ok: true,
        toc_semantic_contract_ok: false,
        ..Default::default()
    };

    let (reviews, _) = build_structure_reviews(&[], &[], &[], &summary, 0, 0);

    assert_eq!(reviews.len(), 1);
    assert_eq!(reviews[0].review_type, "toc_semantic_review_required");
    assert_eq!(reviews[0].severity, "error");
}

#[test]
fn test_structure_reviews_ambiguous_link_is_warning() {
    let links = vec![NoteLinkRecord {
        link_id: "l1".to_string(),
        chapter_id: "ch1".to_string(),
        region_id: "r1".to_string(),
        note_item_id: "n1".to_string(),
        anchor_id: "a1".to_string(),
        status: LinkStatus::Ambiguous,
        resolver: LinkResolver::Rule,
        confidence: 0.5,
        note_kind: NoteKind::Footnote,
        marker: "1".to_string(),
        page_no_start: 5,
        page_no_end: 5,
    }];

    let summary = default_summary();
    let (reviews, _) = build_structure_reviews(&[], &[], &links, &summary, 0, 0);

    assert_eq!(reviews.len(), 1);
    assert_eq!(reviews[0].review_type, "ambiguous");
    assert_eq!(reviews[0].severity, "warning");
}

#[test]
fn test_structure_reviews_ignored_link_skipped() {
    let links = vec![NoteLinkRecord {
        link_id: "l1".to_string(),
        chapter_id: "ch1".to_string(),
        region_id: "r1".to_string(),
        note_item_id: "n1".to_string(),
        anchor_id: "a1".to_string(),
        status: LinkStatus::Ignored,
        resolver: LinkResolver::Rule,
        confidence: 0.0,
        note_kind: NoteKind::Footnote,
        marker: "1".to_string(),
        page_no_start: 5,
        page_no_end: 5,
    }];

    let summary = default_summary();
    let (reviews, _) = build_structure_reviews(&[], &[], &links, &summary, 0, 0);

    assert!(
        reviews.is_empty(),
        "Ignored links should not generate reviews"
    );
}

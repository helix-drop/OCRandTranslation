//! Phase 4 SPEC 测试。
//!
//! 验证 Phase 4 核心功能合同。

use fnm_core::records::*;
use fnm_core::types::*;
use fnm_phase4::reviews::build_structure_reviews;
use fnm_phase4::units::build_translation_units;

fn empty_freeze_errors() -> Vec<FrozenRefEntry> {
    Vec::new()
}

fn default_summary() -> Phase3Summary {
    Phase3Summary {
        chapter_title_alignment_ok: true,
        chapter_section_alignment_ok: true,
        toc_semantic_contract_ok: true,
        ..Default::default()
    }
}

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

// ── Phase 5 新增合同测试 ─────────────────────────────────────────
//
// 验证 build_translation_units 是 FrozenUnits 的纯映射层。
// 注入失败保留原 marker（P1-3）
// book-scope note owner 透传（P1-2）

#[test]
fn spec_translation_units_body_from_frozen_one_to_one() {
    let frozen_body = vec![
        FrozenUnit {
            unit_id: "body-ch1-0001".into(),
            kind: "body".into(),
            owner_kind: "chapter".into(),
            owner_id: "ch1".into(),
            section_id: "ch1".into(),
            section_title: "Chapter 1".into(),
            section_start_page: 1,
            section_end_page: 3,
            page_start: 1,
            page_end: 3,
            char_count: 30,
            source_text: "Chapter 1 text with {{NOTE_REF:n1}} ref.".into(),
            ..Default::default()
        },
        FrozenUnit {
            unit_id: "body-ch2-0001".into(),
            kind: "body".into(),
            owner_kind: "chapter".into(),
            owner_id: "ch2".into(),
            section_id: "ch2".into(),
            section_title: "Chapter 2".into(),
            section_start_page: 4,
            section_end_page: 6,
            page_start: 4,
            page_end: 6,
            char_count: 25,
            source_text: "Chapter 2 text.".into(),
            ..Default::default()
        },
    ];
    let frozen_units = FrozenUnits {
        body_units: frozen_body,
        ..Default::default()
    };
    let (units, _) = build_translation_units(&frozen_units);
    assert_eq!(units.len(), 2);
    assert_eq!(units[0].unit_id, "body-ch1-0001");
    assert_eq!(units[1].unit_id, "body-ch2-0001");
    assert_eq!(
        units[0].source_text,
        "Chapter 1 text with {{NOTE_REF:n1}} ref."
    );
    assert_eq!(units[1].source_text, "Chapter 2 text.");
    assert_eq!(units[0].page_start, 1);
    assert_eq!(units[0].page_end, 3);
    assert_eq!(units[1].section_title, "Chapter 2");
    // 验证 frozen ref token 未被修改
    assert!(units[0].source_text.contains("{{NOTE_REF:n1}}"));
}

#[test]
fn spec_translation_units_footnote_and_endnote_preserved() {
    let frozen_notes = vec![
        FrozenUnit {
            unit_id: "footnote-ch1-n1".into(),
            kind: "footnote".into(),
            note_id: "n1".into(),
            owner_id: "r1".into(),
            owner_kind: "note_region".into(),
            section_id: "ch1".into(),
            source_text: "A footnote definition.".into(),
            page_start: 2,
            page_end: 2,
            target_ref: "{{NOTE_REF:n1}}".into(),
            ..Default::default()
        },
        FrozenUnit {
            unit_id: "endnote-ch1-n2".into(),
            kind: "endnote".into(),
            note_id: "n2".into(),
            owner_id: "r2".into(),
            owner_kind: "note_region".into(),
            section_id: "ch1".into(),
            source_text: "An endnote definition.".into(),
            page_start: 10,
            page_end: 10,
            target_ref: "{{NOTE_REF:n2}}".into(),
            ..Default::default()
        },
    ];
    let frozen_units = FrozenUnits {
        note_units: frozen_notes,
        ..Default::default()
    };
    let (units, _) = build_translation_units(&frozen_units);
    assert_eq!(units.len(), 2);
    // footnote 和 endnote 类型保持
    let fn_units: Vec<_> = units.iter().filter(|u| u.kind == "footnote").collect();
    let en_units: Vec<_> = units.iter().filter(|u| u.kind == "endnote").collect();
    assert_eq!(fn_units.len(), 1);
    assert_eq!(en_units.len(), 1);
    // note_id 透传
    assert_eq!(fn_units[0].note_id, "n1");
    assert_eq!(en_units[0].note_id, "n2");
    // owner_id 透传
    assert_eq!(fn_units[0].owner_id, "r1");
    assert_eq!(en_units[0].owner_id, "r2");
    // target_ref 透传
    assert_eq!(fn_units[0].target_ref, "{{NOTE_REF:n1}}");
    assert_eq!(en_units[0].target_ref, "{{NOTE_REF:n2}}");
}

// ── 结构复核测试 ──────────────────────────────────────────────────

#[test]
fn spec_structure_reviews_generated_for_orphan_links() {
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
    let (reviews, _) = build_structure_reviews(
        &chapters,
        &[],
        &links,
        &summary,
        0,
        0,
        &empty_freeze_errors(),
    );

    assert_eq!(reviews.len(), 1);
    assert_eq!(reviews[0].review_type, "footnote_orphan_note");
    assert_eq!(reviews[0].severity, "error");
}

#[test]
fn spec_injection_failure_preserves_raw_marker() {
    let frozen_body = vec![FrozenUnit {
        unit_id: "body-ch1-0001".into(),
        kind: "body".into(),
        owner_kind: "chapter".into(),
        owner_id: "ch1".into(),
        section_id: "ch1".into(),
        section_title: "Chapter 1".into(),
        section_start_page: 1,
        section_end_page: 3,
        page_start: 1,
        page_end: 3,
        char_count: 40,
        source_text: "This text has a raw marker [^47] that was not injected.".into(),
        ..Default::default()
    }];
    let frozen_units = FrozenUnits {
        body_units: frozen_body,
        ..Default::default()
    };
    let (units, _) = build_translation_units(&frozen_units);
    assert_eq!(units.len(), 1);
    assert!(
        units[0].source_text.contains("[^47]"),
        "raw marker should survive when injection failed"
    );
    assert!(
        !units[0].source_text.contains("{{NOTE_REF:"),
        "no frozen ref token when injection failed"
    );
}

#[test]
fn spec_book_scope_note_owner_is_preserved() {
    let frozen_notes = vec![FrozenUnit {
        unit_id: "endnote-book-en001".into(),
        kind: "endnote".into(),
        note_id: "en001".into(),
        owner_id: "book-endnote-region".into(),
        owner_kind: "note_region".into(),
        section_id: "ch5".into(),
        source_text: "Book-level endnote definition.".into(),
        page_start: 120,
        page_end: 120,
        target_ref: "{{NOTE_REF:en001}}".into(),
        ..Default::default()
    }];
    let frozen_units = FrozenUnits {
        note_units: frozen_notes,
        ..Default::default()
    };
    let (units, _) = build_translation_units(&frozen_units);
    assert_eq!(units.len(), 1);
    // owner_id 与 section_id 不同 → book-scope
    assert_eq!(units[0].owner_id, "book-endnote-region");
    assert_eq!(units[0].section_id, "ch5");
    assert_ne!(
        units[0].owner_id, units[0].section_id,
        "book-scope note has owner_id different from section_id"
    );
    assert_eq!(units[0].note_id, "en001");
    assert_eq!(units[0].kind, "endnote");
}

#[test]
fn spec_freeze_error_generates_blocker_review() {
    let freeze_errors = vec![FrozenRefEntry {
        link_id: "l1".to_string(),
        chapter_id: "ch1".to_string(),
        anchor_id: "a1".to_string(),
        note_item_id: "n1".to_string(),
        target_ref: "{{NOTE_REF:n1}}".to_string(),
        decision: "skipped".to_string(),
        reason: "token_not_found".to_string(),
        skip_category: "ceiling_skip".to_string(),
        page_no: 10,
    }];
    let summary = default_summary();
    let (reviews, _) = build_structure_reviews(&[], &[], &[], &summary, 0, 0, &freeze_errors);
    assert_eq!(reviews.len(), 1);
    assert_eq!(reviews[0].review_type, "freeze_matched_ref_not_injected");
    assert_eq!(reviews[0].severity, "error");
    // 验证 payload 携带定位证据
    let payload = &reviews[0].payload;
    assert_eq!(payload["link_id"].as_str(), Some("l1"));
    assert_eq!(payload["reason"].as_str(), Some("token_not_found"));
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
    let (reviews, _) = build_structure_reviews(
        &chapters,
        &[],
        &links,
        &summary,
        0,
        0,
        &empty_freeze_errors(),
    );

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
    let (reviews, _) =
        build_structure_reviews(&chapters, &[], &[], &summary, 0, 0, &empty_freeze_errors());

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

    let (reviews, _) =
        build_structure_reviews(&[], &[], &[], &summary, 0, 0, &empty_freeze_errors());

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

    let (reviews, _) =
        build_structure_reviews(&[], &[], &[], &summary, 0, 0, &empty_freeze_errors());

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
    let (reviews, _) =
        build_structure_reviews(&[], &[], &links, &summary, 0, 0, &empty_freeze_errors());

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
    let (reviews, _) =
        build_structure_reviews(&[], &[], &links, &summary, 0, 0, &empty_freeze_errors());

    assert!(
        reviews.is_empty(),
        "Ignored links should not generate reviews"
    );
}

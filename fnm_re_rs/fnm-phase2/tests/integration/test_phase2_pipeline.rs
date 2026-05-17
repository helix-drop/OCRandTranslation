//! Phase 2 集成测试：endnote_repair + chapter_explorer + pipeline。

use fnm_core::records::{ChapterRecord, NoteItemRecord, NoteRegionRecord, PagePartitionRecord};
use fnm_core::types::*;
use fnm_phase1::input::RawPage;
use fnm_phase2::input::{Phase2Config, Phase2Input};

#[test]
fn full_pipeline_endnote_book() {
    let chapters = vec![ChapterRecord {
        chapter_id: "ch-1".into(),
        title: "Lecture 1".into(),
        start_page: 1,
        end_page: 5,
        pages: vec![1, 2, 3, 4, 5],
        source: ChapterSource::VisualToc,
        boundary_state: BoundaryState::Ready,
    }];

    let raw_pages: Vec<RawPage> = vec![
        RawPage {
            book_page: 1,
            markdown: "Body text with a point.<sup>1</sup>".into(),
            ..Default::default()
        },
        RawPage {
            book_page: 2,
            markdown: "More body.<sup>2</sup>".into(),
            ..Default::default()
        },
        RawPage {
            book_page: 4,
            markdown: "## Endnotes\n1. First note.\n2. Second note, vol.".into(),
            note_scan: Some(serde_json::json!({"page_kind": "endnote_collection"})),
            ..Default::default()
        },
        RawPage {
            book_page: 5,
            markdown: "III, p. 45.\n3. Third note.".into(),
            note_scan: Some(serde_json::json!({"page_kind": "endnote_collection"})),
            ..Default::default()
        },
    ];

    let input = Phase2Input {
        phase1_chapters: &chapters,
        phase1_pages: &[],
        phase1_section_heads: &[],
        phase1_heading_candidates: &[],
        raw_pages: &raw_pages,
        pdf_path: None,
        config: Phase2Config::default(),
        post_body_titles: std::collections::HashSet::new(),
    };

    let output = fnm_phase2::build_phase2_structure_sync(input).unwrap();

    // 验证 note regions 被检测到
    assert!(output.note_regions.len() >= 1);

    // 验证 note items 数量
    assert!(output.note_items.len() >= 2);

    // 验证所有 note items 的 note_kind 是 endnote（来自显式 heading）
    for item in &output.note_items {
        assert_eq!(item.note_kind, NoteKind::Endnote);
    }

    // 验证 book_type 判定
    assert_eq!(output.book_type, "endnote_only");
}

#[test]
fn endnote_repair_merges_truncated() {
    let items = vec![
        NoteItemRecord {
            note_item_id: "ni-1".into(),
            region_id: "r-1".into(),
            chapter_id: "ch-1".into(),
            page_no: 1,
            marker: "1".into(),
            marker_type: "num".into(),
            text: "See vol.".into(),
            source: "scan".into(),
            source_page_label: "1".into(),
            is_reconstructed: false,
            review_required: false,
            note_kind: NoteKind::Endnote,
        projection_mode: None,
        owner_chapter_id: None,
        source_marker: None,
        normalized_marker: None,
        },
        NoteItemRecord {
            note_item_id: "ni-2".into(),
            region_id: "r-1".into(),
            chapter_id: "ch-1".into(),
            page_no: 1,
            marker: "".into(),
            marker_type: "".into(),
            text: "III, p. 45.".into(),
            source: "scan".into(),
            source_page_label: "1".into(),
            is_reconstructed: false,
            review_required: false,
            note_kind: NoteKind::Endnote,
        projection_mode: None,
        owner_chapter_id: None,
        source_marker: None,
        normalized_marker: None,
        },
    ];

    let (repaired, _) = fnm_phase2::endnote_repair::repair_endnote_items(&items);
    assert_eq!(repaired.len(), 1);
    assert!(repaired[0].is_reconstructed);
    assert!(repaired[0].text.contains("III"));
}

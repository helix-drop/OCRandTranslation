//! DB 层 Phase2/3 round-trip 集成测试。
use fnm_core::db::{
    open_pool, Phase1Products, Phase2Products, Phase3Products, Repository, SqliteRepository,
};
use fnm_core::records::*;
use fnm_core::types::*;
use tempfile::NamedTempFile;

fn setup_db(doc_id: &str) -> (SqliteRepository, NamedTempFile) {
    let tmp = NamedTempFile::new().expect("temp file");
    let pool = open_pool(tmp.path()).expect("open pool");
    pool.get()
        .unwrap()
        .execute(
            "INSERT OR IGNORE INTO documents(id, slug) VALUES (?1, ?2)",
            rusqlite::params![doc_id, "test"],
        )
        .unwrap();
    (SqliteRepository::new(pool), tmp)
}

fn make_page(page_no: i64) -> PagePartitionRecord {
    PagePartitionRecord {
        page_no,
        target_pdf_page: 0,
        page_role: PageRole::Body,
        confidence: 1.0,
        reason: "test".into(),
        section_hint: "".into(),
        has_note_heading: false,
        note_scan_summary: serde_json::json!({}),
    }
}

fn make_chapter(chapter_id: &str, start: i64, end: i64) -> ChapterRecord {
    ChapterRecord {
        chapter_id: chapter_id.into(),
        title: format!("Chapter {chapter_id}"),
        start_page: start,
        end_page: end,
        pages: (start..=end).collect(),
        source: ChapterSource::VisualToc,
        boundary_state: BoundaryState::Ready,
    }
}

// ── Phase 2 round-trip ───────────────────────────────────────

#[test]
fn roundtrip_phase2_products() {
    let doc_id = "test-doc-phase2";
    let (repo, _tmp) = setup_db(doc_id);

    let pages = vec![make_page(1), make_page(2)];
    let chapters = vec![make_chapter("ch-1", 1, 2)];

    let note_regions = vec![NoteRegionRecord {
        region_id: "r-1".into(),
        chapter_id: "ch-1".into(),
        page_start: 1,
        page_end: 2,
        pages: vec![1, 2],
        note_kind: NoteKind::Footnote,
        scope: RegionScope::Chapter,
        source: RegionSource::FootnoteBand,
        heading_text: "Notes".into(),
        start_reason: "band found".into(),
        end_reason: "end of band".into(),
        region_marker_alignment_ok: true,
        region_start_first_source_marker: "1".into(),
        region_first_note_item_marker: "1".into(),
        review_required: false,
    }];

    let note_items = vec![NoteItemRecord {
        note_item_id: "ni-1".into(),
        region_id: "r-1".into(),
        chapter_id: "ch-1".into(),
        page_no: 2,
        marker: "1".into(),
        marker_type: "num".into(),
        text: "This is note 1.".into(),
        source: "note_scan".into(),
        source_page_label: "2".into(),
        is_reconstructed: false,
        review_required: false,
        note_kind: NoteKind::Footnote,
        projection_mode: None,
        owner_chapter_id: None,
        source_marker: None,
        normalized_marker: None,
    }];

    let chapter_note_modes = vec![ChapterNoteModeRecord {
        chapter_id: "ch-1".into(),
        note_mode: NoteMode::FootnotePrimary,
        region_ids: vec!["r-1".into()],
        primary_region_scope: "chapter".into(),
        has_footnote_band: true,
        has_endnote_region: false,
    }];

    // Phase 1 先写基础数据
    let phase1 = Phase1Products {
        pages: pages.clone(),
        chapters: chapters.clone(),
        heading_candidates: vec![],
        section_heads: vec![],
    };
    repo.replace_fnm_phase1_products(doc_id, &phase1)
        .expect("write phase1");

    // Phase 2 只写 Phase 2 表
    let products = Phase2Products {
        pages: vec![],    // Phase 2 不写 Phase 1 表
        chapters: vec![], // Phase 2 不写 Phase 1 表
        heading_candidates: vec![],
        section_heads: vec![],
        note_regions,
        chapter_note_modes,
        note_items,
    };
    repo.replace_fnm_phase2_products(doc_id, &products)
        .expect("write phase2");

    // 验证 pages（Phase 1 写入的不应被 Phase 2 清空）
    let read_pages = repo.list_fnm_pages(doc_id).expect("read pages");
    assert_eq!(
        read_pages.len(),
        2,
        "Phase 1 pages should survive Phase 2 write"
    );

    // 验证 chapters（Phase 1 写入的不应被 Phase 2 清空）
    let read_chapters = repo.list_fnm_chapters(doc_id).expect("read chapters");
    assert_eq!(read_chapters.len(), 1);
    assert_eq!(read_chapters[0].source, ChapterSource::VisualToc);

    // 验证 note_regions
    let read_regions = repo.list_fnm_note_regions(doc_id).expect("read regions");
    assert_eq!(read_regions.len(), 1);
    assert_eq!(read_regions[0].region_id, "r-1");
    assert_eq!(read_regions[0].note_kind, NoteKind::Footnote);

    // 验证 note_items
    let read_items = repo.list_fnm_note_items(doc_id).expect("read items");
    assert_eq!(read_items.len(), 1);
    assert_eq!(read_items[0].note_item_id, "ni-1");
    assert_eq!(read_items[0].note_kind, NoteKind::Footnote);
    assert!(read_items[0].text.contains("note 1"));

    // 验证 chapter_note_modes
    let read_modes = repo
        .list_fnm_chapter_note_modes(doc_id)
        .expect("read modes");
    assert_eq!(read_modes.len(), 1);
    assert_eq!(read_modes[0].chapter_id, "ch-1");
    assert_eq!(read_modes[0].note_mode, NoteMode::FootnotePrimary);
}

// ── Phase 3 round-trip ───────────────────────────────────────

#[test]
fn roundtrip_phase3_products() {
    let doc_id = "test-doc-phase3";
    let (repo, _tmp) = setup_db(doc_id);

    // 先写入 phase1 基础数据（Phase3 复用以保证外键不报错）
    let phase1 = Phase1Products {
        pages: vec![make_page(1)],
        chapters: vec![make_chapter("ch-1", 1, 1)],
        heading_candidates: vec![],
        section_heads: vec![],
    };
    repo.replace_fnm_phase1_products(doc_id, &phase1)
        .expect("write phase1");

    let body_anchors = vec![BodyAnchorRecord {
        anchor_id: "ba-1".into(),
        chapter_id: "ch-1".into(),
        page_no: 1,
        paragraph_index: 0,
        char_start: 10,
        char_end: 11,
        source_marker: "1".into(),
        normalized_marker: "1".into(),
        anchor_kind: AnchorKind::Footnote,
        certainty: 1.0,
        source_text: "ref".into(),
        source: "html".into(),
        synthetic: false,
        ocr_repaired_from_marker: "".into(),
    }];

    let note_links = vec![NoteLinkRecord {
        link_id: "nl-1".into(),
        chapter_id: "ch-1".into(),
        region_id: "r-1".into(),
        note_item_id: "ni-1".into(),
        anchor_id: "ba-1".into(),
        status: LinkStatus::Matched,
        resolver: LinkResolver::Rule,
        confidence: 1.0,
        note_kind: NoteKind::Footnote,
        marker: "1".into(),
        page_no_start: 1,
        page_no_end: 1,
    }];

    let products = Phase3Products {
        body_anchors,
        note_links,
    };
    repo.replace_fnm_phase3_products(doc_id, &products)
        .expect("write phase3");

    // 验证 body_anchors
    let read_anchors = repo.list_fnm_body_anchors(doc_id).expect("read anchors");
    assert_eq!(read_anchors.len(), 1);
    assert_eq!(read_anchors[0].anchor_id, "ba-1");
    assert_eq!(read_anchors[0].anchor_kind, AnchorKind::Footnote);
    assert_eq!(read_anchors[0].normalized_marker, "1");

    // 验证 note_links
    let read_links = repo.list_fnm_note_links(doc_id).expect("read links");
    assert_eq!(read_links.len(), 1);
    assert_eq!(read_links[0].link_id, "nl-1");
    assert_eq!(read_links[0].status, LinkStatus::Matched);
    assert_eq!(read_links[0].resolver, LinkResolver::Rule);
    assert_eq!(read_links[0].note_kind, NoteKind::Footnote);
}

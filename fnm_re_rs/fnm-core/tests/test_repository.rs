//! DB 层集成测试：SqliteRepository 端到端读写。
use fnm_core::db::{open_pool, Phase1Products, Repository, SqliteRepository};
use fnm_core::records::*;
use fnm_core::types::*;
use tempfile::NamedTempFile;

#[test]
fn roundtrip_phase1_products() {
    let tmp = NamedTempFile::new().expect("temp file");
    let pool = open_pool(tmp.path()).expect("open pool");
    let doc_id = "test-doc-1";

    // 插入测试 document（满足外键约束）
    pool.get()
        .unwrap()
        .execute(
            "INSERT OR IGNORE INTO documents(id, slug) VALUES (?1, ?2)",
            rusqlite::params![doc_id, "test"],
        )
        .unwrap();

    let repo = SqliteRepository::new(pool.clone());

    let pages = vec![PagePartitionRecord {
        page_no: 1,
        target_pdf_page: 0,
        page_role: PageRole::Body,
        confidence: 0.9,
        reason: "test".into(),
        section_hint: "Intro".into(),
        has_note_heading: false,
        note_scan_summary: serde_json::json!({}),
    }];

    let chapters = vec![ChapterRecord {
        chapter_id: "ch-1".into(),
        title: "Chapter 1".into(),
        start_page: 1,
        end_page: 10,
        pages: (1..=10).collect(),
        source: ChapterSource::VisualToc,
        boundary_state: BoundaryState::Ready,
    }];

    let heading_candidates = vec![HeadingCandidate {
        heading_id: "heading-1".into(),
        page_no: 1,
        text: "Chapter 1".into(),
        normalized_text: "chapter 1".into(),
        source: "pdf_font_band".into(),
        block_label: "title".into(),
        top_band: true,
        font_height: Some(21.5),
        x: Some(42.0),
        y: Some(18.0),
        width_estimate: Some(280.0),
        confidence: 0.94,
        heading_family_guess: "chapter".into(),
        suppressed_as_chapter: false,
        reject_reason: String::new(),
        font_name: "Times-Bold".into(),
        font_weight_hint: "bold".into(),
        align_hint: "center".into(),
        width_ratio: Some(0.55),
        heading_level_hint: 2,
    }];
    let section_heads = vec![SectionHeadRecord {
        section_head_id: "section-1".into(),
        chapter_id: "ch-1".into(),
        title: "Opening".into(),
        page_no: 2,
        level: 3,
        source: "markdown_heading".into(),
    }];

    let products = Phase1Products {
        pages,
        chapters,
        heading_candidates,
        section_heads,
    };
    repo.replace_fnm_phase1_products(doc_id, &products)
        .expect("write phase1");

    let read_pages = repo.list_fnm_pages(doc_id).expect("read pages");
    assert_eq!(read_pages.len(), 1);
    assert_eq!(read_pages[0].page_no, 1);
    assert_eq!(read_pages[0].page_role, PageRole::Body);

    let read_chapters = repo.list_fnm_chapters(doc_id).expect("read chapters");
    assert_eq!(read_chapters.len(), 1);
    assert_eq!(read_chapters[0].chapter_id, "ch-1");
    assert_eq!(read_chapters[0].source, ChapterSource::VisualToc);

    let read_headings = repo
        .list_fnm_heading_candidates(doc_id)
        .expect("read heading candidates");
    assert_eq!(read_headings.len(), 1);
    assert_eq!(read_headings[0].font_height, Some(21.5));
    assert_eq!(read_headings[0].x, Some(42.0));
    assert_eq!(read_headings[0].font_name, "Times-Bold");
    assert_eq!(read_headings[0].font_weight_hint, "bold");
    assert_eq!(read_headings[0].align_hint, "center");
    assert_eq!(read_headings[0].width_ratio, Some(0.55));
    assert_eq!(read_headings[0].heading_level_hint, 2);

    let read_sections = repo
        .list_fnm_section_heads(doc_id)
        .expect("read section heads");
    assert_eq!(read_sections.len(), 1);
    assert_eq!(read_sections[0].level, 3);
}

#[test]
fn malformed_persisted_chapter_pages_are_rejected() {
    let tmp = NamedTempFile::new().expect("temp file");
    let pool = open_pool(tmp.path()).expect("open pool");
    let doc_id = "invalid-chapter-pages";
    pool.get()
        .unwrap()
        .execute(
            "INSERT OR IGNORE INTO documents(id, slug) VALUES (?1, ?2)",
            rusqlite::params![doc_id, "invalid"],
        )
        .unwrap();
    let repo = SqliteRepository::new(pool.clone());

    repo.replace_fnm_phase1_products(
        doc_id,
        &Phase1Products {
            pages: vec![],
            chapters: vec![ChapterRecord {
                chapter_id: "ch-1".into(),
                title: "Chapter 1".into(),
                start_page: 1,
                end_page: 1,
                pages: vec![1],
                source: ChapterSource::VisualToc,
                boundary_state: BoundaryState::Ready,
            }],
            heading_candidates: vec![],
            section_heads: vec![],
        },
    )
    .expect("write chapter");
    pool.get()
        .unwrap()
        .execute(
            "UPDATE fnm_chapters SET pages_json = 'not-json' WHERE doc_id = ?1",
            [doc_id],
        )
        .expect("corrupt fixture");

    assert!(repo.list_fnm_chapters(doc_id).is_err());
}

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

    let products = Phase1Products {
        pages,
        chapters,
        heading_candidates: vec![],
        section_heads: vec![],
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
}

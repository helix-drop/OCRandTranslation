//! Phase 3 扩展 DB 方法集成测试：
//! - upsert_fnm_chapter_anchor_alignment
//! - replace_fnm_paragraph_footnotes (按章 scope)
//! - replace_fnm_chapter_endnotes (按章 scope)
//! - list_fnm_chapter_anchor_alignments / list_fnm_chapter_endnotes / list_fnm_paragraph_footnotes
//! - list_fnm_review_overrides_v2
use fnm_core::db::{open_pool, Phase3Products, Repository, SqliteRepository};
use fnm_core::records::*;
use fnm_core::types::*;
use tempfile::NamedTempFile;

fn setup_repo() -> (SqliteRepository, NamedTempFile, &'static str) {
    let tmp = NamedTempFile::new().expect("temp file");
    let pool = open_pool(tmp.path()).expect("open pool");
    let doc_id = "test-phase3-ext";
    pool.get()
        .unwrap()
        .execute(
            "INSERT OR IGNORE INTO documents(id, slug) VALUES (?1, ?2)",
            rusqlite::params![doc_id, "test"],
        )
        .unwrap();
    let repo = SqliteRepository::new(pool);
    (repo, tmp, doc_id)
}

#[test]
fn roundtrip_chapter_anchor_alignment_upsert() {
    let (repo, _tmp, doc_id) = setup_repo();

    repo.upsert_fnm_chapter_anchor_alignment(
        doc_id,
        "ch-1",
        "aligned",
        10,
        10,
        Some(serde_json::json!({"diff": 0})),
    )
    .expect("upsert alignment");

    let alignments = repo
        .list_fnm_chapter_anchor_alignments(doc_id)
        .expect("read alignments");
    assert_eq!(alignments.len(), 1);
    assert_eq!(alignments[0].chapter_id, "ch-1");
    assert_eq!(alignments[0].alignment_status, "aligned");
    assert_eq!(alignments[0].body_anchor_count, 10);
    assert_eq!(alignments[0].endnote_count, 10);

    // Upsert 同一章应更新
    repo.upsert_fnm_chapter_anchor_alignment(
        doc_id,
        "ch-1",
        "misaligned",
        12,
        10,
        Some(serde_json::json!({"diff": 2})),
    )
    .expect("upsert update");

    let alignments = repo
        .list_fnm_chapter_anchor_alignments(doc_id)
        .expect("read after update");
    assert_eq!(alignments.len(), 1);
    assert_eq!(alignments[0].alignment_status, "misaligned");
    assert_eq!(alignments[0].body_anchor_count, 12);
}

#[test]
fn roundtrip_paragraph_footnotes_by_chapter() {
    let (repo, _tmp, doc_id) = setup_repo();

    let footnotes = vec![
        ParagraphFootnoteRecord {
            doc_id: doc_id.to_string(),
            chapter_id: "ch-1".to_string(),
            page_no: 10,
            paragraph_index: 0,
            attachment_kind: "page_tail".to_string(),
            source_marker: "1".to_string(),
            text: "footnote 1 text".to_string(),
        },
        ParagraphFootnoteRecord {
            doc_id: doc_id.to_string(),
            chapter_id: "ch-1".to_string(),
            page_no: 12,
            paragraph_index: 1,
            attachment_kind: "page_tail".to_string(),
            source_marker: "2".to_string(),
            text: "footnote 2 text".to_string(),
        },
    ];

    repo.replace_fnm_paragraph_footnotes(doc_id, "ch-1", &footnotes)
        .expect("write footnotes");

    let read = repo
        .list_fnm_paragraph_footnotes(doc_id)
        .expect("read footnotes");
    assert_eq!(read.len(), 2);
    assert_eq!(read[0].chapter_id, "ch-1");
    assert_eq!(read[0].source_marker, "1");

    // 写入另一章不应影响 ch-1
    let ch2_footnotes = vec![ParagraphFootnoteRecord {
        doc_id: doc_id.to_string(),
        chapter_id: "ch-2".to_string(),
        page_no: 20,
        paragraph_index: 0,
        attachment_kind: "inline".to_string(),
        source_marker: "3".to_string(),
        text: "ch2 footnote".to_string(),
    }];
    repo.replace_fnm_paragraph_footnotes(doc_id, "ch-2", &ch2_footnotes)
        .expect("write ch-2 footnotes");

    let all = repo
        .list_fnm_paragraph_footnotes(doc_id)
        .expect("read all footnotes");
    assert_eq!(all.len(), 3);

    // 替换 ch-1 应清空旧数据并写入新数据
    let new_ch1 = vec![ParagraphFootnoteRecord {
        doc_id: doc_id.to_string(),
        chapter_id: "ch-1".to_string(),
        page_no: 15,
        paragraph_index: 0,
        attachment_kind: "page_tail".to_string(),
        source_marker: "5".to_string(),
        text: "replaced footnote".to_string(),
    }];
    repo.replace_fnm_paragraph_footnotes(doc_id, "ch-1", &new_ch1)
        .expect("replace ch-1 footnotes");

    let all = repo
        .list_fnm_paragraph_footnotes(doc_id)
        .expect("read after replace");
    assert_eq!(all.len(), 2); // 1 from ch-2 + 1 from replaced ch-1
}

#[test]
fn roundtrip_chapter_endnotes_by_chapter() {
    let (repo, _tmp, doc_id) = setup_repo();

    let endnotes = vec![
        ChapterEndnoteRecord {
            doc_id: doc_id.to_string(),
            chapter_id: "ch-1".to_string(),
            ordinal: 1,
            marker: "1".to_string(),
            numbering_scheme: "per_chapter".to_string(),
            text: "endnote 1".to_string(),
            source_page_no: 100,
            is_reconstructed: false,
            review_required: true,
        },
        ChapterEndnoteRecord {
            doc_id: doc_id.to_string(),
            chapter_id: "ch-1".to_string(),
            ordinal: 2,
            marker: "2".to_string(),
            numbering_scheme: "per_chapter".to_string(),
            text: "endnote 2".to_string(),
            source_page_no: 101,
            is_reconstructed: false,
            review_required: false,
        },
    ];

    repo.replace_fnm_chapter_endnotes(doc_id, "ch-1", &endnotes)
        .expect("write endnotes");

    let read = repo
        .list_fnm_chapter_endnotes(doc_id)
        .expect("read endnotes");
    assert_eq!(read.len(), 2);
    assert_eq!(read[0].chapter_id, "ch-1");
    assert_eq!(read[0].ordinal, 1);
    assert_eq!(read[0].marker, "1");
    assert!(!read[0].is_reconstructed);
    assert!(read[0].review_required);
    assert_eq!(read[1].ordinal, 2);
    assert!(!read[1].review_required);
}

#[test]
fn roundtrip_phase3_products_plus_per_chapter_tables() {
    let (repo, _tmp, doc_id) = setup_repo();

    // 1. 先写 Phase 3 products（body_anchors + note_links）
    let anchors = vec![BodyAnchorRecord {
        anchor_id: "a-1".to_string(),
        chapter_id: "ch-1".to_string(),
        page_no: 10,
        paragraph_index: 0,
        char_start: 5,
        char_end: 7,
        source_marker: "$^{1}$".to_string(),
        normalized_marker: "1".to_string(),
        anchor_kind: AnchorKind::Footnote,
        certainty: 1.0,
        source_text: "text [1]".to_string(),
        source: "markdown:latex".to_string(),
        synthetic: false,
        ocr_repaired_from_marker: String::new(),
    }];
    let links = vec![NoteLinkRecord {
        link_id: "l-1".to_string(),
        chapter_id: "ch-1".to_string(),
        region_id: "rg-1".to_string(),
        note_item_id: "ni-1".to_string(),
        anchor_id: "a-1".to_string(),
        status: LinkStatus::Matched,
        resolver: LinkResolver::Rule,
        confidence: 1.0,
        note_kind: NoteKind::Footnote,
        marker: "1".to_string(),
        page_no_start: 10,
        page_no_end: 10,
    }];
    let payload = Phase3Products {
        body_anchors: anchors,
        note_links: links,
    };
    repo.replace_fnm_phase3_products(doc_id, &payload)
        .expect("write phase3 products");

    // 2. 写 chapter_anchor_alignment（upsert）
    repo.upsert_fnm_chapter_anchor_alignment(doc_id, "ch-1", "aligned", 1, 0, None)
        .expect("upsert alignment");

    // 3. 写 paragraph_footnotes（按章 scope）
    let footnotes = vec![ParagraphFootnoteRecord {
        doc_id: doc_id.to_string(),
        chapter_id: "ch-1".to_string(),
        page_no: 10,
        paragraph_index: 0,
        attachment_kind: "page_tail".to_string(),
        source_marker: "1".to_string(),
        text: "footnote text".to_string(),
    }];
    repo.replace_fnm_paragraph_footnotes(doc_id, "ch-1", &footnotes)
        .expect("write footnotes");

    // 4. 写 chapter_endnotes（按章 scope）
    let endnotes = vec![ChapterEndnoteRecord {
        doc_id: doc_id.to_string(),
        chapter_id: "ch-1".to_string(),
        ordinal: 1,
        marker: "1".to_string(),
        numbering_scheme: "per_chapter".to_string(),
        text: "endnote text".to_string(),
        source_page_no: 100,
        is_reconstructed: false,
        review_required: true,
    }];
    repo.replace_fnm_chapter_endnotes(doc_id, "ch-1", &endnotes)
        .expect("write endnotes");

    // 5. 读回所有 5 张表，确认行数
    let read_anchors = repo.list_fnm_body_anchors(doc_id).expect("read anchors");
    let read_links = repo.list_fnm_note_links(doc_id).expect("read links");
    let read_alignments = repo
        .list_fnm_chapter_anchor_alignments(doc_id)
        .expect("read alignments");
    let read_footnotes = repo
        .list_fnm_paragraph_footnotes(doc_id)
        .expect("read footnotes");
    let read_endnotes = repo
        .list_fnm_chapter_endnotes(doc_id)
        .expect("read endnotes");

    assert_eq!(read_anchors.len(), 1, "should have 1 body anchor");
    assert_eq!(read_links.len(), 1, "should have 1 note link");
    assert_eq!(read_alignments.len(), 1, "should have 1 alignment");
    assert_eq!(read_footnotes.len(), 1, "should have 1 footnote");
    assert_eq!(read_endnotes.len(), 1, "should have 1 endnote");

    // 6. review_overrides_v2 应为空（Phase 3.5 写入）
    let read_overrides = repo
        .list_fnm_review_overrides_v2(doc_id)
        .expect("read overrides");
    assert!(read_overrides.is_empty(), "should have no overrides yet");
}

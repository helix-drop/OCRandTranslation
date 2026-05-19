//! DB 层 Phase5/6 round-trip 集成测试。
//!
//! 覆盖 fnm_chapter_markdowns / fnm_diagnostic_pages / fnm_diagnostic_notes /
//! fnm_export_chapters / fnm_export_audit / fnm_export_bundle 表的 CRUD。

use fnm_core::db::{open_pool, Phase5Products, Phase6Products, Repository, SqliteRepository};
use fnm_core::records::*;
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

fn make_chapter_markdown(chapter_id: &str, order: i64) -> ChapterMarkdownEntry {
    ChapterMarkdownEntry {
        order,
        chapter_id: chapter_id.into(),
        title: format!("Chapter {chapter_id}"),
        path: format!("chapters/{chapter_id}.md"),
        markdown_text: format!("# Chapter {chapter_id}\n\nBody text here."),
        start_page: order * 10,
        end_page: order * 10 + 9,
        pages: (order * 10..=order * 10 + 9).collect(),
    }
}

fn make_diagnostic_page(page_bp: i64) -> DiagnosticPageRecord {
    DiagnosticPageRecord {
        _page_bp: page_bp,
        _status: "ok".into(),
        pages: format!("{page_bp}"),
        _page_entries: vec![DiagnosticEntryRecord {
            _start_bp: page_bp * 100,
            _end_bp: page_bp * 100 + 50,
            ..Default::default()
        }],
        _fnm_source: serde_json::json!({"source": "test"}),
    }
}

fn make_diagnostic_note(note_id: &str, section_id: &str) -> DiagnosticNoteRecord {
    DiagnosticNoteRecord {
        note_id: note_id.into(),
        section_id: section_id.into(),
        section_title: format!("Section {section_id}"),
        section_start_page: 1,
        section_end_page: 10,
        kind: "footnote".into(),
        original_marker: "1".into(),
        start_page: 5,
        pages: vec![5],
        source_text: "Note text".into(),
        translated_text: "".into(),
        translate_status: "pending".into(),
        region_id: "r1".into(),
    }
}

fn make_export_chapter(section_id: &str, order: i64) -> ExportChapterRecord {
    ExportChapterRecord {
        order,
        section_id: section_id.into(),
        title: format!("Section {section_id}"),
        path: format!("chapters/{section_id}.md"),
        content: format!("# Section {section_id}\n\nContent here."),
        start_page: order * 10,
        end_page: order * 10 + 9,
        pages: (order * 10..=order * 10 + 9).collect(),
    }
}

fn make_export_audit(slug: &str) -> ExportAuditReportRecord {
    ExportAuditReportRecord {
        slug: slug.into(),
        doc_id: "doc-1".into(),
        zip_path: "/tmp/test.zip".into(),
        applicable: true,
        structure_state: "idle".into(),
        blocking_reasons: vec![],
        chapter_titles: vec!["Ch1".into()],
        can_ship: true,
        ..Default::default()
    }
}

fn make_export_bundle() -> ExportBundleRecord {
    ExportBundleRecord {
        index_path: "index.md".into(),
        chapters_dir: "chapters".into(),
        chapters: vec![make_export_chapter("s1", 0)],
        chapter_files: [("s1".into(), "chapters/s1.md".into())]
            .into_iter()
            .collect(),
        files: [("index.md".into(), "# Index".into())]
            .into_iter()
            .collect(),
        export_semantic_contract_ok: true,
        ..Default::default()
    }
}

// ── Phase 5 round-trip ───────────────────────────────────────

#[test]
fn roundtrip_chapter_markdowns() {
    let (repo, _tmp) = setup_db("doc-cm");
    let items = vec![
        make_chapter_markdown("ch1", 0),
        make_chapter_markdown("ch2", 1),
    ];
    let payload = Phase5Products {
        chapter_markdowns: items.clone(),
        diagnostic_pages: vec![],
        diagnostic_notes: vec![],
    };
    repo.replace_fnm_phase5_products("doc-cm", &payload)
        .expect("write");

    let loaded = repo.list_fnm_chapter_markdowns("doc-cm").expect("read");
    assert_eq!(loaded.len(), 2);
    assert_eq!(loaded[0].chapter_id, "ch1");
    assert_eq!(loaded[0].order, 0);
    assert_eq!(loaded[0].title, "Chapter ch1");
    assert_eq!(loaded[0].markdown_text, "# Chapter ch1\n\nBody text here.");
    assert_eq!(loaded[0].start_page, 0);
    assert_eq!(loaded[0].end_page, 9);
    assert_eq!(loaded[0].pages.len(), 10);
    assert_eq!(loaded[1].chapter_id, "ch2");
    assert_eq!(loaded[1].order, 1);
}

#[test]
fn roundtrip_diagnostic_pages() {
    let (repo, _tmp) = setup_db("doc-dp");
    let items = vec![make_diagnostic_page(1), make_diagnostic_page(2)];
    let payload = Phase5Products {
        chapter_markdowns: vec![],
        diagnostic_pages: items.clone(),
        diagnostic_notes: vec![],
    };
    repo.replace_fnm_phase5_products("doc-dp", &payload)
        .expect("write");

    let loaded = repo.list_fnm_diagnostic_pages("doc-dp").expect("read");
    assert_eq!(loaded.len(), 2);
    assert_eq!(loaded[0]._page_bp, 1);
    assert_eq!(loaded[0]._status, "ok");
    assert_eq!(loaded[0]._page_entries.len(), 1);
    assert_eq!(loaded[1]._page_bp, 2);
}

#[test]
fn roundtrip_diagnostic_notes() {
    let (repo, _tmp) = setup_db("doc-dn");
    let items = vec![
        make_diagnostic_note("n1", "s1"),
        make_diagnostic_note("n2", "s1"),
    ];
    let payload = Phase5Products {
        chapter_markdowns: vec![],
        diagnostic_pages: vec![],
        diagnostic_notes: items.clone(),
    };
    repo.replace_fnm_phase5_products("doc-dn", &payload)
        .expect("write");

    let loaded = repo.list_fnm_diagnostic_notes("doc-dn").expect("read");
    assert_eq!(loaded.len(), 2);
    assert_eq!(loaded[0].note_id, "n1");
    assert_eq!(loaded[0].section_id, "s1");
    assert_eq!(loaded[0].kind, "footnote");
    assert_eq!(loaded[0].source_text, "Note text");
    assert_eq!(loaded[1].note_id, "n2");
}

#[test]
fn roundtrip_phase5_products_combined() {
    let (repo, _tmp) = setup_db("doc-p5");
    let payload = Phase5Products {
        chapter_markdowns: vec![make_chapter_markdown("ch1", 0)],
        diagnostic_pages: vec![make_diagnostic_page(1)],
        diagnostic_notes: vec![make_diagnostic_note("n1", "s1")],
    };
    repo.replace_fnm_phase5_products("doc-p5", &payload)
        .expect("write");

    let cms = repo.list_fnm_chapter_markdowns("doc-p5").expect("read");
    let dps = repo.list_fnm_diagnostic_pages("doc-p5").expect("read");
    let dns = repo.list_fnm_diagnostic_notes("doc-p5").expect("read");
    assert_eq!(cms.len(), 1);
    assert_eq!(dps.len(), 1);
    assert_eq!(dns.len(), 1);
}

#[test]
fn phase5_replace_is_idempotent() {
    let (repo, _tmp) = setup_db("doc-p5-idem");
    let p1 = Phase5Products {
        chapter_markdowns: vec![make_chapter_markdown("ch1", 0)],
        diagnostic_pages: vec![],
        diagnostic_notes: vec![],
    };
    repo.replace_fnm_phase5_products("doc-p5-idem", &p1)
        .expect("write 1");

    let p2 = Phase5Products {
        chapter_markdowns: vec![
            make_chapter_markdown("ch1", 0),
            make_chapter_markdown("ch2", 1),
        ],
        diagnostic_pages: vec![],
        diagnostic_notes: vec![],
    };
    repo.replace_fnm_phase5_products("doc-p5-idem", &p2)
        .expect("write 2");

    let loaded = repo
        .list_fnm_chapter_markdowns("doc-p5-idem")
        .expect("read");
    assert_eq!(loaded.len(), 2, "replace 应清空再写入");
}

// ── Phase 6 round-trip ───────────────────────────────────────

#[test]
fn roundtrip_export_chapters() {
    let (repo, _tmp) = setup_db("doc-ec");
    let items = vec![make_export_chapter("s1", 0), make_export_chapter("s2", 1)];
    let payload = Phase6Products {
        export_chapters: items.clone(),
        export_bundle: ExportBundleRecord::default(),
        export_audit: ExportAuditReportRecord::default(),
    };
    repo.replace_fnm_phase6_products("doc-ec", &payload)
        .expect("write");

    let loaded = repo.list_fnm_export_chapters("doc-ec").expect("read");
    assert_eq!(loaded.len(), 2);
    assert_eq!(loaded[0].section_id, "s1");
    assert_eq!(loaded[0].order, 0);
    assert_eq!(loaded[0].title, "Section s1");
    assert_eq!(loaded[1].section_id, "s2");
    assert_eq!(loaded[1].order, 1);
}

#[test]
fn roundtrip_export_audit() {
    let (repo, _tmp) = setup_db("doc-ea");
    let audit = make_export_audit("TestBook");
    let payload = Phase6Products {
        export_chapters: vec![],
        export_bundle: ExportBundleRecord::default(),
        export_audit: audit.clone(),
    };
    repo.replace_fnm_phase6_products("doc-ea", &payload)
        .expect("write");

    let loaded = repo.list_fnm_export_audit("doc-ea").expect("read");
    assert!(loaded.is_some());
    let loaded = loaded.unwrap();
    assert_eq!(loaded.slug, "TestBook");
    assert!(loaded.can_ship);
    assert_eq!(loaded.doc_id, "doc-1");
}

#[test]
fn roundtrip_export_bundle() {
    let (repo, _tmp) = setup_db("doc-eb");
    let bundle = make_export_bundle();
    let payload = Phase6Products {
        export_chapters: vec![],
        export_bundle: bundle.clone(),
        export_audit: ExportAuditReportRecord::default(),
    };
    repo.replace_fnm_phase6_products("doc-eb", &payload)
        .expect("write");

    let loaded = repo.list_fnm_export_bundle("doc-eb").expect("read");
    assert!(loaded.is_some());
    let loaded = loaded.unwrap();
    assert_eq!(loaded.index_path, "index.md");
    assert_eq!(loaded.chapters_dir, "chapters");
    assert_eq!(loaded.chapters.len(), 1);
    assert_eq!(loaded.chapters[0].section_id, "s1");
    assert_eq!(loaded.chapter_files.len(), 1);
    assert_eq!(loaded.files.len(), 1);
    assert!(loaded.export_semantic_contract_ok);
}

#[test]
fn roundtrip_phase6_products_combined() {
    let (repo, _tmp) = setup_db("doc-p6");
    let payload = Phase6Products {
        export_chapters: vec![make_export_chapter("s1", 0)],
        export_bundle: make_export_bundle(),
        export_audit: make_export_audit("TestBook"),
    };
    repo.replace_fnm_phase6_products("doc-p6", &payload)
        .expect("write");

    let ecs = repo.list_fnm_export_chapters("doc-p6").expect("read");
    let ea = repo.list_fnm_export_audit("doc-p6").expect("read");
    let eb = repo.list_fnm_export_bundle("doc-p6").expect("read");
    assert_eq!(ecs.len(), 1);
    assert!(ea.is_some());
    assert!(eb.is_some());
    assert_eq!(eb.unwrap().index_path, "index.md");
}

#[test]
fn phase6_replace_is_idempotent() {
    let (repo, _tmp) = setup_db("doc-p6-idem");
    let p1 = Phase6Products {
        export_chapters: vec![make_export_chapter("s1", 0)],
        export_bundle: ExportBundleRecord::default(),
        export_audit: ExportAuditReportRecord::default(),
    };
    repo.replace_fnm_phase6_products("doc-p6-idem", &p1)
        .expect("write 1");

    let p2 = Phase6Products {
        export_chapters: vec![make_export_chapter("s1", 0), make_export_chapter("s2", 1)],
        export_bundle: make_export_bundle(),
        export_audit: make_export_audit("TestBook"),
    };
    repo.replace_fnm_phase6_products("doc-p6-idem", &p2)
        .expect("write 2");

    let ecs = repo.list_fnm_export_chapters("doc-p6-idem").expect("read");
    assert_eq!(ecs.len(), 2, "replace 应清空再写入");

    let eb = repo.list_fnm_export_bundle("doc-p6-idem").expect("read");
    assert!(eb.is_some(), "第二次写入应包含 export_bundle");
}

#[test]
fn export_audit_empty_returns_none() {
    let (repo, _tmp) = setup_db("doc-empty");
    let loaded = repo.list_fnm_export_audit("doc-empty").expect("read");
    assert!(loaded.is_none());
}

#[test]
fn export_bundle_empty_returns_none() {
    let (repo, _tmp) = setup_db("doc-empty-eb");
    let loaded = repo.list_fnm_export_bundle("doc-empty-eb").expect("read");
    assert!(loaded.is_none());
}

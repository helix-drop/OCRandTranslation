import json
import sqlite3
from pathlib import Path

import pytest

import fnm_re_rs

FIXTURE_PATH = "test_example/Biopolitics/raw_pages.json"


@pytest.fixture
def biopolitics_db(tmp_path: Path) -> str:
    """Create a temp SQLite DB with Biopolitics pages + documents + visual TOC,
    run pipeline, return DB path.
    """
    db_path = str(tmp_path / "biopolitics.db")
    with open(FIXTURE_PATH) as fh:
        raw = json.load(fh)
    pages = raw["pages"]

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, slug TEXT, state TEXT NOT NULL DEFAULT 'idle',
            toc_user_json TEXT DEFAULT '[]',
            toc_auto_visual_json TEXT DEFAULT '[]',
            toc_auto_pdf_json TEXT DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS pages (
            doc_id TEXT NOT NULL, book_page INTEGER NOT NULL,
            file_idx INTEGER NOT NULL DEFAULT 0, markdown TEXT, footnotes TEXT,
            text_source TEXT NOT NULL DEFAULT 'ocr', payload_json TEXT,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, book_page)
        );
    """)
    now = 1700000000
    for p in pages:
        conn.execute(
            "INSERT OR IGNORE INTO pages "
            "(doc_id, book_page, file_idx, markdown, footnotes, text_source, "
            "payload_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'ocr', ?, ?, ?)",
            ("biopolitics-seed", p.get("bookPage", 0), p.get("fileIdx", 0) or 0,
             p.get("markdown", ""), p.get("footnotes", ""),
             json.dumps(p, ensure_ascii=False), now, now),
        )

    toc_items = [
        {"item_id": f"toc-{i}", "title": title, "target_pdf_page": page,
         "role_hint": "chapter"}
        for i, (title, page) in enumerate([
            ("Leçon du 10 janvier 1979", 17),
            ("Leçon du 17 janvier 1979", 43),
            ("Leçon du 24 janvier 1979", 67),
            ("Leçon du 31 janvier 1979", 90),
            ("Leçon du 7 février 1979", 107),
            ("Leçon du 14 février 1979", 130),
            ("Leçon du 21 février 1979", 149),
            ("Leçon du 28 février 1979", 165),
            ("Leçon du 7 mars 1979", 192),
            ("Leçon du 14 mars 1979", 219),
            ("Leçon du 21 mars 1979", 252),
            ("Leçon du 4 avril 1979", 290),
        ], start=1)
    ]
    conn.execute(
        "INSERT OR IGNORE INTO documents (id, slug) VALUES (?, ?)",
        ("biopolitics-seed", "biopolitics"),
    )
    conn.execute(
        "UPDATE documents SET toc_user_json = ? WHERE id = ?",
        (json.dumps(toc_items, ensure_ascii=False), "biopolitics-seed"),
    )
    conn.commit()
    conn.close()

    fnm_re_rs.run_doc_pipeline_json(db_path, "biopolitics-seed", 6000, "toc")
    return db_path

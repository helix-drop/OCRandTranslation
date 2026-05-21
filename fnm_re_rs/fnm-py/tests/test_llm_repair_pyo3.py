import json

import fnm_re_rs

from conftest import FIXTURE_PATH


def _seed_small_db(db_path: str) -> None:
    """Seed with minimal pages + TOC for fast LLM repair test."""
    with open(FIXTURE_PATH) as fh:
        raw = json.load(fh)
    pages = raw["pages"][:5]

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, slug TEXT, state TEXT NOT NULL DEFAULT 'idle',
            toc_user_json TEXT DEFAULT '[]', toc_auto_visual_json TEXT DEFAULT '[]',
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
            ("llm-test", p.get("bookPage", 0), p.get("fileIdx", 0) or 0,
             p.get("markdown", ""), p.get("footnotes", ""),
             json.dumps(p, ensure_ascii=False), now, now),
        )
    toc = [{"item_id": "toc-1", "title": "Leçon du 10 janvier 1979",
            "target_pdf_page": 17, "role_hint": "chapter"}]
    conn.execute("INSERT OR IGNORE INTO documents (id, slug) VALUES (?, ?)",
                 ("llm-test", "llm-test"))
    conn.execute("UPDATE documents SET toc_user_json = ? WHERE id = ?",
                 (json.dumps(toc, ensure_ascii=False), "llm-test"))
    conn.commit()
    conn.close()

    fnm_re_rs.run_doc_pipeline_json(db_path, "llm-test", 6000, "toc")


def test_llm_repair_returns_report(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed_small_db(db_path)

    result = json.loads(fnm_re_rs.run_llm_repair_json(
        db_path, "llm-test", "", None, "llm-test", False, 0.9, None,
    ))
    assert isinstance(result, dict)
    assert "cluster_count" in result
    assert result["cluster_count"] >= 0


def test_llm_repair_with_auto_apply(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed_small_db(db_path)

    result = json.loads(fnm_re_rs.run_llm_repair_json(
        db_path, "llm-test", "", None, "llm-test", True, 0.9, None,
    ))
    assert isinstance(result, dict)
    assert result["cluster_count"] >= 0

"""M1.8: 验证 run_doc_pipeline 完整 pipeline（从 DB 读 pages + TOC → 跑 → 写 fnm_run）。"""

import json
import sqlite3
import tempfile
from pathlib import Path

import fnm_re_rs


FIXTURE = "test_example/Biopolitics/raw_pages.json"


def test_run_doc_pipeline_via_python_seeded_db():
    """用 Python SQLite 建 pages/documents 表 seed 数据后，
    调 run_doc_pipeline_json 从 Rust 读 pages + 跑完整 pipeline。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        with open(FIXTURE) as fh:
            raw = json.load(fh)
        pages = raw["pages"]

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                slug TEXT,
                state TEXT NOT NULL DEFAULT 'idle'
            );
        """)
        for col in ("toc_user_json", "toc_auto_visual_json", "toc_auto_pdf_json"):
            try:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT DEFAULT '[]'")
            except Exception:
                pass
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pages (
                doc_id TEXT NOT NULL,
                book_page INTEGER NOT NULL,
                file_idx INTEGER NOT NULL DEFAULT 0,
                markdown TEXT,
                footnotes TEXT,
                text_source TEXT NOT NULL DEFAULT 'ocr',
                payload_json TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(doc_id, book_page)
            );
        """)
        now = 1700000000
        for p in pages[:5]:
            conn.execute(
                "INSERT OR IGNORE INTO pages (doc_id, book_page, file_idx, markdown, footnotes, text_source, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'ocr', ?, ?, ?)",
                ("bp-m18", p.get("bookPage", 0), p.get("fileIdx", 0) or 0,
                 p.get("markdown", ""), p.get("footnotes", ""),
                 json.dumps(p, ensure_ascii=False), now, now),
            )
        conn.execute("INSERT OR IGNORE INTO documents (id, slug) VALUES (?, ?)", ("bp-m18", "biopolitics"))
        conn.commit()
        conn.close()

        result_json = fnm_re_rs.run_doc_pipeline_json(str(db_path), "bp-m18", 6000, "toc")
        result = json.loads(result_json)

        assert result.get("ok") is True, f"pipeline failed: {result}"
        assert result.get("section_count", 0) > 0, f"no sections: {result}"
        assert result.get("page_count", 0) >= 5, f"expected >=5 pages: {result}"
        assert result.get("run_id", 0) > 0, f"no run_id: {result}"
        print(f"PASSED: run_doc_pipeline_json → ok, sections={result['section_count']}, "
              f"pages={result['page_count']}, run_id={result['run_id']}")

    finally:
        Path(db_path).unlink(missing_ok=True)

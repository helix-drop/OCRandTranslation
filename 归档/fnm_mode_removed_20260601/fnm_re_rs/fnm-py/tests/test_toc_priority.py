"""M3.4: 验证 TOC 优先级列顺序（用户 > 视觉 > PDF）。"""

import json
import sqlite3
import tempfile
from pathlib import Path

import fnm_re_rs


def _make_db(user_json, visual_json, pdf_json):
    """创建带 toc_*_json 列的内存 DB，返回路径。"""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = f.name
    f.close()

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            slug TEXT,
            state TEXT NOT NULL DEFAULT 'idle'
        );
        CREATE TABLE IF NOT EXISTS pages (
            doc_id TEXT NOT NULL,
            book_page INTEGER NOT NULL,
            payload_json TEXT
        );
    """)
    # 加 TOC 列
    for col in ("toc_user_json", "toc_auto_visual_json", "toc_auto_pdf_json"):
        conn.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT DEFAULT '[]'")

    conn.execute(
        "INSERT INTO documents (id, slug, toc_user_json, toc_auto_visual_json, toc_auto_pdf_json) VALUES (?, ?, ?, ?, ?)",
        ("test-doc", "test", user_json, visual_json, pdf_json),
    )
    conn.execute(
        "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?, 1, '{}')",
        ("test-doc",),
    )
    conn.commit()
    conn.close()
    return db_path


def test_toc_priority_user_over_visual():
    """toc_user_json 非空时，忽略视觉和 PDF。"""
    user = '[{"item_id":"user-1","title":"User Chapter","level":1,"depth":0}]'
    visual = '[{"item_id":"vis-1","title":"Visual Chapter","level":1,"depth":0}]'
    pdf = '[{"item_id":"pdf-1","title":"PDF Chapter","level":1,"depth":0}]'
    db_path = _make_db(user, visual, pdf)

    try:
        result_json = fnm_re_rs.load_toc_items_for_doc_json(str(db_path), "test-doc")
        items = json.loads(result_json)
        assert len(items) == 1, f"expected 1 item, got {len(items)}: {items}"
        assert items[0]["item_id"] == "user-1"
        assert items[0]["title"] == "User Chapter"
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_toc_priority_falls_back_to_visual_when_user_empty():
    """toc_user_json 为空数组时，fallback 到视觉。"""
    visual = '[{"item_id":"vis-2","title":"Visual Chapter","level":1,"depth":0}]'
    pdf = '[{"item_id":"pdf-2","title":"PDF Chapter","level":1,"depth":0}]'
    db_path = _make_db("[]", visual, pdf)

    try:
        result_json = fnm_re_rs.load_toc_items_for_doc_json(str(db_path), "test-doc")
        items = json.loads(result_json)
        assert len(items) == 1, f"expected 1 item, got {len(items)}: {items}"
        assert items[0]["item_id"] == "vis-2"
    finally:
        Path(db_path).unlink(missing_ok=True)

"""M1.10: 验证 build_doc_status 从 phase6 + fnm_runs 构建 status dict。"""

import json
import sqlite3
import tempfile
from pathlib import Path

import fnm_re_rs


def test_build_doc_status_returns_valid_json():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, slug TEXT, state TEXT)")
        for col in ("toc_user_json", "toc_auto_visual_json", "toc_auto_pdf_json"):
            try:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT DEFAULT '[]'")
            except Exception:
                pass
        conn.execute("INSERT OR IGNORE INTO documents (id, slug, state) VALUES ('test-doc', 'test-doc', 'idle')")
        conn.execute("CREATE TABLE IF NOT EXISTS pages (doc_id TEXT, book_page INTEGER, payload_json TEXT)")
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?, 1, ?)",
            ("test-doc", json.dumps({"bookPage": 1, "markdown": "# Ch1\n\nContent", "footnotes": "", "fnBlocks": [], "prunedResult": {}})),
        )
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?, 2, ?)",
            ("test-doc", json.dumps({"bookPage": 2, "markdown": "More.", "footnotes": "", "fnBlocks": [], "prunedResult": {}})),
        )
        conn.commit()
        conn.close()

        # Pipeline 应成功运行
        pipeline_result = json.loads(fnm_re_rs.run_doc_pipeline_json(db_path, "test-doc"))
        assert pipeline_result.get("structure_state") == "done", f"Pipeline failed: {pipeline_result}"

        result_json = fnm_re_rs.build_doc_status_json(db_path, "test-doc", "toc")
        result = json.loads(result_json)

        assert isinstance(result, dict)
        assert "structure_state" in result
        assert "page_count" in result
        assert "chapter_count" in result
        assert "summary" in result
    finally:
        Path(db_path).unlink(missing_ok=True)

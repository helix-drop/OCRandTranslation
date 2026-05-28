"""M1.9: 验证 run_llm_repair 可调用且正确返回 repair report。"""

import json
import sqlite3
import tempfile
from pathlib import Path

import fnm_re_rs


def test_run_llm_repair_empty_db_does_not_panic():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, slug TEXT, state TEXT)")
        conn.execute("INSERT OR IGNORE INTO documents (id, slug, state) VALUES ('test-bk', 'test-bk', 'idle')")
        for col in ("toc_user_json", "toc_auto_visual_json", "toc_auto_pdf_json"):
            try:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT DEFAULT '[]'")
            except Exception:
                pass
        conn.execute("CREATE TABLE IF NOT EXISTS pages (doc_id TEXT, book_page INTEGER, payload_json TEXT)")
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?, 1, ?)",
            ("test-bk", json.dumps({"bookPage": 1, "markdown": "# Test\n\nContent", "footnotes": "", "fnBlocks": [], "prunedResult": {}})),
        )
        conn.commit()
        conn.close()

        # Pipeline 应成功运行
        pipeline_result = json.loads(fnm_re_rs.run_doc_pipeline_json(db_path, "test-bk"))
        assert pipeline_result.get("structure_state") == "done"

        result_json = fnm_re_rs.run_llm_repair_json(
            db_path,
            "test-bk",
            "",
            None,
            json.dumps({"slug": "test-bk", "auto_apply": False}),
        )
        result = json.loads(result_json)
        assert isinstance(result, dict)
        assert "cluster_count" in result
    finally:
        Path(db_path).unlink(missing_ok=True)

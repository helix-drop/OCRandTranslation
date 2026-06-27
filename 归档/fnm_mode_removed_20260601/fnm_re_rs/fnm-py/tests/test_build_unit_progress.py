"""M1.11a: 验证 build_unit_progress 从 fnm_translation_units 统计进度。"""

import json
import tempfile
from pathlib import Path

import fnm_re_rs


def _seed_schema(db_path: str, doc_id: str):
    try:
        fnm_re_rs.run_doc_pipeline_json(db_path, doc_id)
    except RuntimeError:
        pass


def test_build_unit_progress_empty_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        _seed_schema(db_path, "test-doc")
        result_json = fnm_re_rs.build_unit_progress_json(db_path, "test-doc", None, False)
        result = json.loads(result_json)

        assert result["total_units"] == 0
        assert result["done_units"] == 0
        assert result["error_units"] == 0
        assert result["pending_units"] == 0
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_build_unit_progress_with_units():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        import sqlite3
        _seed_schema(db_path, "test-doc")
        conn = sqlite3.connect(db_path)
        for i, (uid, status) in enumerate([
            ("u1", "done"), ("u2", "done"), ("u3", "error"), ("u4", "pending"),
        ]):
            conn.execute(
                "INSERT INTO fnm_translation_units (unit_id, doc_id, kind, owner_kind, owner_id, section_id, section_title, section_start_page, section_end_page, note_id, page_start, page_end, char_count, source_text, translated_text, status, error_msg, target_ref, page_segments_json, source_hash, created_at, updated_at) VALUES (?, ?, 'body', '', '', ?, ?, 1, 10, '', 1, 10, 0, '', '', ?, '', '', '[]', '', 1000000, 1000001)",
                (uid, "test-doc", f"s{i+1}", f"Section {i+1}", status),
            )
        conn.commit()
        conn.close()

        result_json = fnm_re_rs.build_unit_progress_json(db_path, "test-doc", None, False)
        result = json.loads(result_json)

        assert result["total_units"] == 4
        assert result["done_units"] == 2
        assert result["error_units"] == 1
        assert result["pending_units"] == 1
        assert len(result["unit_items"]) == 4
    finally:
        Path(db_path).unlink(missing_ok=True)

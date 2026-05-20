"""M1.11b: 验证 build_retry_summary 从 translation unit 段落失败推导。"""

import json
import tempfile
from pathlib import Path

import fnm_re_rs


def _seed_schema(db_path: str, doc_id: str):
    try:
        fnm_re_rs.run_doc_pipeline_json(db_path, doc_id)
    except RuntimeError:
        pass


def _unit_with_failed_paragraph(para_status: str, manual_resolved: bool = False) -> str:
    return json.dumps([{
        "page_no": 1,
        "paragraph_count": 1,
        "source_text": "test text",
        "display_text": "test text",
        "paragraphs": [{
            "order": 1,
            "kind": "body",
            "heading_level": 0,
            "source_text": "test text",
            "display_text": "test text",
            "cross_page": None,
            "consumed_by_prev": False,
            "section_path": [],
            "print_page_label": "",
            "translated_text": "",
            "translation_status": para_status,
            "attempt_count": 1,
            "last_error": "test error",
            "manual_resolved": manual_resolved,
        }],
    }])


def test_build_retry_summary_no_failures():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        _seed_schema(db_path, "test-doc")
        result_json = fnm_re_rs.build_retry_summary_json(db_path, "test-doc")
        result = json.loads(result_json)

        assert result["retry_progress"]["unresolved_count"] == 0
        assert result["retry_progress"]["manual_required_count"] == 0
        assert result["blocking_reason"] == ""
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_build_retry_summary_with_error():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        import sqlite3
        _seed_schema(db_path, "test-doc")
        conn = sqlite3.connect(db_path)
        seg = _unit_with_failed_paragraph("error")
        conn.execute(
            "INSERT INTO fnm_translation_units (unit_id, doc_id, kind, owner_kind, owner_id, section_id, section_title, section_start_page, section_end_page, note_id, page_start, page_end, char_count, source_text, translated_text, status, error_msg, target_ref, page_segments_json, source_hash, created_at, updated_at) VALUES (?, ?, 'body', '', '', 's1', 'Section 1', 1, 10, '', 1, 10, 0, '', '', 'pending', '', '', ?, '', 1000000, 1000001)",
            ("u1", "test-doc", seg),
        )
        conn.commit()
        conn.close()

        result_json = fnm_re_rs.build_retry_summary_json(db_path, "test-doc")
        result = json.loads(result_json)

        assert result["retry_progress"]["unresolved_count"] == 1
        assert result["blocking_reason"] == "unresolved"
    finally:
        Path(db_path).unlink(missing_ok=True)

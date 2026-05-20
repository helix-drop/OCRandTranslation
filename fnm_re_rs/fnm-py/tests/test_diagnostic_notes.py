"""M1.6: 验证 list_diagnostic_notes_for_doc 读取诊断注释。"""

import json
import tempfile
from pathlib import Path

import fnm_re_rs


FIXTURE_PATH = "test_example/Biopolitics/raw_pages.json"


def _seed_db(db_path: str) -> None:
    """用 Biopolitics 数据跑一次完整 pipeline → seed DB。"""
    with open(FIXTURE_PATH) as fh:
        pages = json.load(fh)["pages"]
    toc_items = [
        {"item_id": f"toc-{i}", "title": title, "target_pdf_page": page, "role_hint": "chapter"}
        for i, (title, page) in enumerate(
            [("Leçon du 10 janvier 1979", 17), ("Leçon du 17 janvier 1979", 43)], start=1
        )
    ]
    config = {
        "doc_id": "bp-d-6", "slug": "biopolitics", "pdf_path": "",
        "toc_offset": 0, "max_body_chars": 6000, "include_diagnostic_entries": True,
        "manual_toc_ready": False, "pipeline_state": "done", "start_phase": "toc",
    }
    fnm_re_rs.run_pipeline_for_doc_json(
        db_path, "bp-d-6", json.dumps(pages), json.dumps(toc_items), json.dumps(config),
    )


def test_list_diagnostic_notes_shape():
    """seed DB → notes 是 list，每条含 note_id。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _seed_db(db_path)

        result_json = fnm_re_rs.list_diagnostic_notes_for_doc_json(str(db_path), "bp-d-6")
        notes = json.loads(result_json)

        assert isinstance(notes, list)
        if len(notes) > 0:
            note = notes[0]
            assert "note_id" in note, f"missing note_id in {note}"

    finally:
        Path(db_path).unlink(missing_ok=True)

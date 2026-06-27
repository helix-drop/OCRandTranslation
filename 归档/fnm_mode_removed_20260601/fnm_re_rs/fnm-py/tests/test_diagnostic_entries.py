"""M1.5: 验证 list_diagnostic_entries_for_doc 读取诊断页面。"""

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
        "doc_id": "bp-d-5", "slug": "biopolitics", "pdf_path": "",
        "toc_offset": 0, "max_body_chars": 6000, "include_diagnostic_entries": True,
        "manual_toc_ready": False, "pipeline_state": "done", "start_phase": "toc",
    }
    fnm_re_rs.run_pipeline_for_doc_json(
        db_path, "bp-d-5", json.dumps(pages), json.dumps(toc_items), json.dumps(config),
    )


def test_list_diagnostic_entries_shape():
    """seed DB → entries 是 list，每条含 key 字段。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _seed_db(db_path)

        result_json = fnm_re_rs.list_diagnostic_entries_for_doc_json(str(db_path), "bp-d-5", None)
        entries = json.loads(result_json)

        assert isinstance(entries, list)
        if len(entries) > 0:
            entry = entries[0]
            assert "_pageBP" in entry or "_page_bp" in entry
            assert "_status" in entry
            assert "pages" in entry

    finally:
        Path(db_path).unlink(missing_ok=True)


def test_list_diagnostic_entries_with_filter():
    """visible_bps 过滤后只返回匹配条目。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _seed_db(db_path)

        all_json = fnm_re_rs.list_diagnostic_entries_for_doc_json(str(db_path), "bp-d-5", None)
        all_entries = json.loads(all_json)

        if len(all_entries) >= 2:
            bp = all_entries[0]["_pageBP"] if "_pageBP" in all_entries[0] else all_entries[0]["_page_bp"]
            filtered_json = fnm_re_rs.list_diagnostic_entries_for_doc_json(
                str(db_path), "bp-d-5", [bp],
            )
            filtered = json.loads(filtered_json)
            assert len(filtered) == 1, f"expected 1 entry, got {len(filtered)}"

    finally:
        Path(db_path).unlink(missing_ok=True)

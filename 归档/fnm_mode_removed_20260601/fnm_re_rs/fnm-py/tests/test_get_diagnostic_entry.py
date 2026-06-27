"""M1.7: 验证 get_diagnostic_entry_for_page 读取单页诊断条目。"""

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
        "doc_id": "bp-d-7", "slug": "biopolitics", "pdf_path": "",
        "toc_offset": 0, "max_body_chars": 6000, "include_diagnostic_entries": True,
        "manual_toc_ready": False, "pipeline_state": "done", "start_phase": "toc",
    }
    fnm_re_rs.run_pipeline_for_doc_json(
        db_path, "bp-d-7", json.dumps(pages), json.dumps(toc_items), json.dumps(config),
    )


def test_get_diagnostic_entry_found():
    """seed DB → 请求有效 bp → 返回 entry dict。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _seed_db(db_path)

        # 先 list 拿一条 bp
        all_json = fnm_re_rs.list_diagnostic_entries_for_doc_json(str(db_path), "bp-d-7", None)
        all_entries = json.loads(all_json)

        if len(all_entries) > 0:
            bp = all_entries[0]["_pageBP"] if "_pageBP" in all_entries[0] else all_entries[0]["_page_bp"]
            result_json = fnm_re_rs.get_diagnostic_entry_for_page_json(str(db_path), "bp-d-7", bp, True)
            assert result_json != "null", f"expected entry for bp {bp}, got null"
            entry = json.loads(result_json)
            assert isinstance(entry, dict)
            assert "_status" in entry

    finally:
        Path(db_path).unlink(missing_ok=True)


def test_get_diagnostic_entry_not_found_returns_null():
    """不存在的 bp → allow_fallback=True → 返回 None。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _seed_db(db_path)

        result_json = fnm_re_rs.get_diagnostic_entry_for_page_json(str(db_path), "bp-d-7", 99999, True)
        assert result_json == "null", f"expected 'null', got {result_json}"
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_get_diagnostic_entry_not_found_raises():
    """不存在的 bp → allow_fallback=False → 报错。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _seed_db(db_path)

        try:
            fnm_re_rs.get_diagnostic_entry_for_page_json(str(db_path), "bp-d-7", 99999, False)
            assert False, "expected exception"
        except Exception as exc:
            err_str = str(exc)
            assert "not found" in err_str, f"unexpected: {err_str}"
    finally:
        Path(db_path).unlink(missing_ok=True)

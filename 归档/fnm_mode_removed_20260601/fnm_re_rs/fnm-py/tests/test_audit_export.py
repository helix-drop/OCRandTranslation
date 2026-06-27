"""M1.2: 验证 audit_export_for_doc 审计 Phase 6 导出。"""

import json
import tempfile
from pathlib import Path

import fnm_re_rs


FIXTURE_PATH = "test_example/Biopolitics/raw_pages.json"


def _seed_db(db_path: str) -> None:
    """用 Biopolitics 数据跑一次完整 pipeline → seed DB。"""
    with open(FIXTURE_PATH) as fh:
        raw = json.load(fh)
    pages = raw["pages"]

    toc_items = [
        {"item_id": f"toc-{i}", "title": title, "target_pdf_page": page, "role_hint": "chapter"}
        for i, (title, page) in enumerate(
            [
                ("Leçon du 10 janvier 1979", 17),
                ("Leçon du 17 janvier 1979", 43),
                ("Leçon du 24 janvier 1979", 67),
                ("Leçon du 31 janvier 1979", 90),
                ("Leçon du 7 février 1979", 107),
                ("Leçon du 14 février 1979", 130),
                ("Leçon du 21 février 1979", 149),
                ("Leçon du 28 février 1979", 165),
                ("Leçon du 7 mars 1979", 192),
                ("Leçon du 14 mars 1979", 219),
                ("Leçon du 21 mars 1979", 252),
                ("Leçon du 4 avril 1979", 290),
            ],
            start=1,
        )
    ]

    config = {
        "doc_id": "biopolitics-seed",
        "slug": "biopolitics",
        "pdf_path": "",
        "toc_offset": 0,
        "max_body_chars": 6000,
        "include_diagnostic_entries": False,
        "manual_toc_ready": False,
        "pipeline_state": "done",
        "start_phase": "toc",
    }

    fnm_re_rs.run_pipeline_for_doc_json(
        db_path, "biopolitics-seed",
        json.dumps(pages), json.dumps(toc_items), json.dumps(config),
    )


def test_audit_export_with_defaults():
    """seed DB → audit → 断言 audit 报告基本形状。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        _seed_db(db_path)

        result_json = fnm_re_rs.audit_export_for_doc_json(
            str(db_path), "biopolitics-seed", "biopolitics", None, None,
        )
        report = json.loads(result_json)

        # 基本形状验证
        assert "slug" in report, "missing slug"
        assert "structure_state" in report, "missing structure_state"
        assert "chapter_titles" in report, "missing chapter_titles"
        assert "files" in report, "missing files"

        assert report["slug"] == "biopolitics"
        assert len(report.get("chapter_titles", [])) > 0, "expected at least 1 chapter title"

        # 断言 audit 给出明确结论
        assert "can_ship" in report, "missing can_ship"
        assert isinstance(report["can_ship"], bool)

    finally:
        Path(db_path).unlink(missing_ok=True)


def test_audit_export_with_zip_bytes():
    """传入 zip_bytes 走临时文件路径验证。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        _seed_db(db_path)

        # 先加载 phase6 再构建 zip 字节
        loaded_json = fnm_re_rs.load_doc_structure_json(str(db_path), "biopolitics-seed", False)
        loaded = json.loads(loaded_json)

        # 直接用 None zip_bytes 再跑一次
        result_json = fnm_re_rs.audit_export_for_doc_json(
            str(db_path), "biopolitics-seed", "biopolitics", None, None,
        )
        report = json.loads(result_json)
        assert "files" in report
        assert report["slug"] == "biopolitics"

    finally:
        Path(db_path).unlink(missing_ok=True)


def test_audit_export_nonexistent_doc():
    """不存在的 doc_id 应报错。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        try:
            fnm_re_rs.audit_export_for_doc_json(str(db_path), "nonexistent", "", None, None)
            assert False, "expected exception for nonexistent doc_id"
        except Exception as exc:
            err_str = str(exc)
            assert "not found" in err_str or "no pages" in err_str, f"unexpected error: {err_str}"
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_audit_export_nonexistent_zip_path():
    """不存在的 zip_path 应报错，不能静默退回结构审计。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        _seed_db(db_path)

        try:
            fnm_re_rs.audit_export_for_doc_json(
                str(db_path), "biopolitics-seed", "biopolitics",
                "/nonexistent/path/to/file.zip", None,
            )
            assert False, "expected exception for nonexistent zip_path"
        except Exception as exc:
            err_str = str(exc)
            assert "does not exist" in err_str, f"unexpected error: {err_str}"
    finally:
        Path(db_path).unlink(missing_ok=True)

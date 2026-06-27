"""M1.1: 验证 load_doc_structure 从 DB 加载 phase1-6 数据。"""

import json
import tempfile
from pathlib import Path

import fnm_re_rs


FIXTURE_PATH = "test_example/Biopolitics/raw_pages.json"


def test_load_doc_structure_returns_12_chapters():
    """用 smoke_test 方式 seed DB → 加载 → 断言 chapters=12。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # 1. seed DB: 跑 pipeline 写入 phase1-6 表
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

        result_json = fnm_re_rs.run_pipeline_for_doc_json(
            db_path, "biopolitics-seed",
            json.dumps(pages), json.dumps(toc_items), json.dumps(config),
        )
        snapshot = json.loads(result_json)
        assert "phase6" in snapshot, f"pipeline snapshot missing phase6, keys: {list(snapshot.keys())}"

        # 2. 调 load_doc_structure_json
        loaded_json = fnm_re_rs.load_doc_structure_json(str(db_path), "biopolitics-seed", False)
        loaded = json.loads(loaded_json)

        # 3. 断言
        chapters = loaded.get("chapters", [])
        assert len(chapters) == 12, f"expected 12 chapters, got {len(chapters)}"

        # 4. 基本形状验证
        for ch in chapters:
            assert "chapter_id" in ch, f"chapter missing chapter_id: {ch}"
            assert "title" in ch, f"chapter missing title: {ch}"
            assert "start_page" in ch, f"chapter missing start_page: {ch}"
            assert "end_page" in ch, f"chapter missing end_page: {ch}"

        # 5. 其它字段存在性检查
        assert "pages" in loaded
        assert "note_regions" in loaded
        assert "note_items" in loaded
        assert "body_anchors" in loaded
        assert "note_links" in loaded
        assert len(loaded.get("pages", [])) > 0, "expected at least 1 page"

        # 6. include_diagnostic_entries=False 时不出 diagnostic 数据
        assert loaded.get("diagnostic_pages", None) in (None, [])
        assert loaded.get("diagnostic_notes", None) in (None, [])

    finally:
        Path(db_path).unlink(missing_ok=True)


def test_load_doc_structure_nonexistent_doc_raises():
    """不存在的 doc_id 应返回错误而非空结构。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        import fnm_re_rs
        try:
            fnm_re_rs.load_doc_structure_json(str(db_path), "nonexistent", False)
            assert False, "expected exception for nonexistent doc_id"
        except Exception as exc:
            err_str = str(exc)
            assert "not found" in err_str or "no pages" in err_str, f"unexpected error: {err_str}"
    finally:
        Path(db_path).unlink(missing_ok=True)

"""M1.4: 验证 build_export_zip_for_doc 构建 ZIP 字节。"""

import json
import zipfile
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


def test_export_zip_is_valid_zip():
    """seed DB → ZIP bytes 解压成功 + 含 README.md + 含章节文件。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        _seed_db(db_path)

        zip_bytes = fnm_re_rs.build_export_zip_for_doc_json(str(db_path), "biopolitics-seed")
        assert isinstance(zip_bytes, bytes), f"expected bytes, got {type(zip_bytes)}"
        assert len(zip_bytes) > 100, f"zip too small: {len(zip_bytes)} bytes"

        # 解压验证
        import io
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = zf.namelist()
        zf.close()

        assert len(names) >= 3, f"expected >=3 files in zip, got {len(names)}: {names}"

        # 确保有 index.md + 12 个章节文件
        has_index = any("index" in n.lower() for n in names)
        chapter_count = sum(1 for n in names if n.startswith("chapters/") and n.endswith(".md"))
        assert has_index, f"expected index.md, got: {names}"
        assert chapter_count >= 12, f"expected >=12 chapter files, got {chapter_count}: {names}"

    finally:
        Path(db_path).unlink(missing_ok=True)


def test_export_zip_nonexistent_doc_raises():
    """不存在的 doc_id 应报错。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        try:
            fnm_re_rs.build_export_zip_for_doc_json(str(db_path), "nonexistent")
            assert False, "expected exception"
        except Exception as exc:
            err_str = str(exc)
            assert "not found" in err_str or "export bundle not found" in err_str, f"unexpected: {err_str}"
    finally:
        Path(db_path).unlink(missing_ok=True)

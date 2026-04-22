#!/usr/bin/env python3
"""后端 backlog 收口测试：状态口径、PDF TOC、术语 CRUD。"""

import io
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import config
import app as app_module
import persistence.storage as storage
import translation.service as tasks
from config import create_doc, ensure_dirs, set_current_doc, update_doc_meta
from document.pdf_extract import extract_pdf_toc
from pypdf import PdfWriter
from pypdf.constants import PageLabelStyle
from persistence.sqlite_store import SQLiteRepository, get_connection
from persistence.storage import (
    get_app_state,
    has_toc_visual_draft,
    load_auto_visual_toc_from_disk,
    load_effective_toc,
    load_entries_from_disk,
    load_pages_from_disk,
    load_user_toc_from_disk,
    get_toc_file_info,
    get_toc_file_path,
    save_auto_pdf_toc_to_disk,
    save_auto_visual_toc_to_disk,
    save_entries_to_disk,
    save_pages_to_disk,
    save_toc_file,
    save_user_toc_to_disk,
)
from testsupport import ClientCSRFMixin
from werkzeug.datastructures import FileStorage


def _build_simple_xlsx(rows: list[list[object]]) -> bytes:
    def _col_name(index: int) -> str:
        result = ""
        value = index + 1
        while value:
            value, rem = divmod(value - 1, 26)
            result = chr(65 + rem) + result
        return result

    def _xml_escape(value: object) -> str:
        text = str(value)
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    sheet_rows = []
    for row_idx, row in enumerate(rows, start=1):
        cells = []
        for col_idx, value in enumerate(row):
            ref = f"{_col_name(col_idx)}{row_idx}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{_xml_escape(value)}</t></is></c>'
                )
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        + "".join(sheet_rows)
        + "</sheetData></worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def _build_labeled_pdf(total_pages: int, label_start_page: int, start_label: int) -> bytes:
    writer = PdfWriter()
    for _ in range(total_pages):
        writer.add_blank_page(width=200, height=200)
    if 1 <= label_start_page <= total_pages:
        writer.set_page_label(
            label_start_page - 1,
            total_pages - 1,
            style=PageLabelStyle.DECIMAL,
            start=start_label,
        )
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class BackendBacklogTest(ClientCSRFMixin, unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="backend-backlog-")
        self._patch_config_dirs(self.temp_root)
        ensure_dirs()
        self.client = app_module.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def test_sqlite_schema_contains_toc_column(self):
        repo = SQLiteRepository()
        repo.upsert_document("doc-toc", "toc.pdf")
        with get_connection(config.get_sqlite_db_path()) as conn:
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(documents)").fetchall()
            }
        self.assertIn("toc_json", cols)
        self.assertIn("toc_file_name", cols)
        self.assertIn("toc_file_uploaded_at", cols)
        self.assertIn("toc_user_json", cols)
        self.assertIn("toc_auto_pdf_json", cols)
        self.assertIn("toc_auto_visual_json", cols)
        self.assertIn("auto_visual_toc_enabled", cols)
        self.assertIn("toc_visual_status", cols)
        self.assertIn("toc_visual_message", cols)
        self.assertIn("toc_visual_phase", cols)
        self.assertIn("toc_visual_progress_pct", cols)
        self.assertIn("toc_visual_progress_label", cols)
        self.assertIn("toc_visual_progress_detail", cols)

    def test_test_files_do_not_hardcode_unix_temp_dir(self):
        repo_root = os.path.dirname(__file__)
        unix_temp_fragment = "/" + "tmp"
        offenders = []
        for name in sorted(os.listdir(repo_root)):
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            path = os.path.join(repo_root, name)
            with open(path, "r", encoding="utf-8") as f:
                if unix_temp_fragment in f.read():
                    offenders.append(name)

        self.assertFalse(
            offenders,
            f"测试文件仍硬编码了 Unix 临时目录: {', '.join(offenders)}",
        )

    def test_get_app_state_exposes_has_translation_history(self):
        doc_id = create_doc("state.pdf")
        state = get_app_state(doc_id)
        self.assertIn("has_translation_history", state)
        self.assertFalse(state["has_translation_history"])

        save_entries_to_disk(
            [
                {
                    "_pageBP": 7,
                    "_model": "qwen-plus",
                    "_page_entries": [{"original": "a", "translation": "b"}],
                    "pages": "7",
                }
            ],
            "State Doc",
            0,
            doc_id,
        )
        state_after = get_app_state(doc_id)
        self.assertTrue(state_after["has_translation_history"])

    def test_pdf_toc_route_returns_saved_toc(self):
        doc_id = create_doc("toc-route.pdf")
        toc = [{"title": "Chapter 1", "depth": 0, "file_idx": 0}]
        save_user_toc_to_disk(doc_id, toc)
        save_toc_file(
            doc_id,
            FileStorage(stream=io.BytesIO(b"title,depth,page\nChapter 1,0,1\n"), filename="book-index.csv"),
        )
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 3)

        resp = self.client.get(f"/pdf_toc?doc_id={doc_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["doc_id"], doc_id)
        self.assertEqual(data["toc"], toc)
        self.assertEqual(data["source"], "user")
        self.assertEqual(data["offset"], 3)
        self.assertEqual(data["toc_file"]["display_name"], "book-index.csv")
        self.assertFalse(data["toc_file"]["is_legacy_name"])

    def test_save_toc_file_persists_original_name_and_replaces_old_extension(self):
        doc_id = create_doc("toc-save.pdf")

        save_toc_file(
            doc_id,
            FileStorage(stream=io.BytesIO(b"title,depth,page\nChapter 1,0,1\n"), filename="目录-v1.csv"),
        )
        first_path = get_toc_file_path(doc_id)
        self.assertTrue(first_path.endswith("toc_source.csv"))
        self.assertTrue(os.path.exists(first_path))
        first_info = get_toc_file_info(doc_id)
        self.assertEqual(first_info["display_name"], "目录-v1.csv")
        self.assertEqual(first_info["original_name"], "目录-v1.csv")
        self.assertFalse(first_info["is_legacy_name"])
        self.assertGreater(first_info["uploaded_at"], 0)

        save_toc_file(
            doc_id,
            FileStorage(stream=io.BytesIO(b"fake-xlsx"), filename="目录-v2.xlsx"),
        )
        second_path = get_toc_file_path(doc_id)
        self.assertTrue(second_path.endswith("toc_source.xlsx"))
        self.assertTrue(os.path.exists(second_path))
        self.assertFalse(os.path.exists(first_path))
        second_info = get_toc_file_info(doc_id)
        self.assertEqual(second_info["display_name"], "目录-v2.xlsx")
        self.assertEqual(second_info["original_name"], "目录-v2.xlsx")
        self.assertFalse(second_info["is_legacy_name"])

    def test_get_toc_file_info_returns_legacy_name_when_original_name_missing(self):
        doc_id = create_doc("legacy-toc.pdf")
        doc_dir = config.get_doc_dir(doc_id)
        legacy_path = os.path.join(doc_dir, "toc_source.csv")
        with open(legacy_path, "wb") as f:
            f.write(b"title,depth,page\nChapter 1,0,1\n")

        info = get_toc_file_info(doc_id)

        self.assertTrue(info["exists"])
        self.assertEqual(info["display_name"], "toc_source.csv")
        self.assertEqual(info["original_name"], "")
        self.assertTrue(info["is_legacy_name"])
        self.assertGreater(info["uploaded_at"], 0)

    def test_load_user_toc_recovers_from_saved_toc_file_when_sqlite_rows_missing(self):
        doc_id = create_doc("toc-recover.pdf")

        save_toc_file(
            doc_id,
            FileStorage(
                stream=io.BytesIO("title,depth,page\nChapter 1,0,3\n".encode("utf-8")),
                filename="toc-recover.csv",
            ),
        )

        recovered = load_user_toc_from_disk(doc_id)

        self.assertEqual(recovered, [{"title": "Chapter 1", "depth": 0, "book_page": 3}])
        self.assertEqual(load_user_toc_from_disk(doc_id), recovered)

    def test_toc_import_returns_toc_file_metadata(self):
        doc_id = create_doc("toc-import.pdf")
        set_current_doc(doc_id)

        resp = self.client.post(
            "/api/toc/import",
            query_string={"doc_id": doc_id},
            data={"file": (io.BytesIO("title,depth,page\n第一章,0,1\n".encode("utf-8")), "目录总表.csv")},
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
            content_type="multipart/form-data",
        )

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["toc_file"]["display_name"], "目录总表.csv")
        self.assertEqual(payload["toc_file"]["original_name"], "目录总表.csv")
        self.assertFalse(payload["toc_file"]["is_legacy_name"])
        self.assertTrue(os.path.exists(get_toc_file_path(doc_id)))

    def test_settings_page_shows_current_toc_file_and_replace_upload(self):
        doc_id = create_doc("toc-settings.pdf")
        SQLiteRepository().set_document_toc(doc_id, [{"title": "第一章", "depth": 0, "file_idx": 0}])
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 2)
        save_toc_file(
            doc_id,
            FileStorage(stream=io.BytesIO(b"title,depth,page\nChapter 1,0,1\n"), filename="目录设置版.csv"),
        )

        resp = self.client.get("/settings", query_string={"doc_id": doc_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("当前目录索引文件", html)
        self.assertIn("目录设置版.csv", html)
        self.assertIn("重新上传替换目录文件", html)
        self.assertIn("原始文件名", html)

    def test_settings_page_shows_empty_toc_file_state(self):
        doc_id = create_doc("toc-empty.pdf")

        resp = self.client.get("/settings", query_string={"doc_id": doc_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("当前未选择目录索引文件", html)
        self.assertIn("重新上传替换目录文件", html)

    def test_update_doc_meta_does_not_clear_existing_toc(self):
        doc_id = create_doc("toc-meta.pdf")
        toc = [{"title": "第一章", "depth": 0, "book_page": 1}]
        save_user_toc_to_disk(doc_id, toc)
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 2)

        update_doc_meta(doc_id, last_entry_idx=3)

        self.assertEqual(load_effective_toc(doc_id)[2], toc)

    def test_auto_pdf_toc_does_not_overwrite_user_toc(self):
        doc_id = create_doc("toc-auto-protect.pdf")
        user_toc = [{"title": "用户目录", "depth": 0, "book_page": 3}]
        save_user_toc_to_disk(doc_id, user_toc)
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 5)
        save_toc_file(
            doc_id,
            FileStorage(stream=io.BytesIO(b"title,depth,page\nUser,0,3\n"), filename="user-toc.csv"),
        )

        save_auto_pdf_toc_to_disk(doc_id, [{"title": "PDF 书签", "depth": 0, "file_idx": 0}])

        self.assertEqual(load_effective_toc(doc_id)[2], user_toc)

    def test_effective_toc_prefers_user_then_auto_visual_then_auto_pdf(self):
        doc_id = create_doc("toc-priority.pdf")
        auto_pdf = [{"title": "PDF 书签", "depth": 0, "file_idx": 0}]
        auto_visual = [{"title": "视觉目录", "depth": 0, "file_idx": 4}]
        user_toc = [{"title": "用户目录", "depth": 0, "book_page": 7}]

        save_auto_pdf_toc_to_disk(doc_id, auto_pdf)
        self.assertEqual(load_effective_toc(doc_id), ("auto", 0, auto_pdf))

        save_auto_visual_toc_to_disk(doc_id, auto_visual)
        self.assertEqual(load_effective_toc(doc_id), ("auto_visual", 0, auto_visual))

        save_user_toc_to_disk(doc_id, user_toc)
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 3)
        self.assertEqual(load_effective_toc(doc_id), ("user", 3, user_toc))

    def test_effective_toc_accepts_auto_visual_needs_offset_and_keeps_source_offset(self):
        doc_id = create_doc("toc-needs-offset.pdf")
        auto_pdf = [{"title": "PDF 书签", "depth": 0, "file_idx": 0}]
        auto_visual = [{"title": "视觉目录", "depth": 0, "book_page": 17, "item_id": "visual-1"}]

        save_auto_pdf_toc_to_disk(doc_id, auto_pdf)
        save_auto_visual_toc_to_disk(doc_id, auto_visual)
        update_doc_meta(doc_id, toc_visual_status="needs_offset")
        SQLiteRepository().set_document_toc_source_offset(doc_id, "auto_visual", 5)

        self.assertEqual(load_effective_toc(doc_id), ("auto_visual", 5, auto_visual))

    def test_toc_set_offset_updates_current_effective_toc_source(self):
        doc_id = create_doc("toc-offset-effective.pdf")
        save_auto_visual_toc_to_disk(
            doc_id,
            [{"title": "视觉目录", "depth": 0, "book_page": 3, "item_id": "visual-1"}],
        )
        update_doc_meta(doc_id, toc_visual_status="needs_offset")
        SQLiteRepository().set_document_toc_source_offset(doc_id, "auto_visual", 0)

        resp = self.client.post(
            "/api/toc/set_offset",
            query_string={"doc_id": doc_id},
            json={"offset": 7},
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["offset"], 7)
        self.assertEqual(
            SQLiteRepository().get_document_toc_source_offset(doc_id),
            ("auto_visual", 7),
        )

    def test_doc_processing_status_returns_visual_toc_progress_payload(self):
        doc_id = create_doc("visual-progress.pdf")
        update_doc_meta(
            doc_id,
            toc_visual_status="running",
            toc_visual_message="正在抽取目录项…",
            toc_visual_phase="extracting_items",
            toc_visual_progress_pct=68,
            toc_visual_progress_label="目录项抽取",
            toc_visual_progress_detail="视觉复核目录页 3/5",
        )

        resp = self.client.get("/api/doc_processing_status", query_string={"doc_id": doc_id})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["doc_id"], doc_id)
        self.assertEqual(data["toc_visual_status"], "running")
        self.assertEqual(data["toc_visual_phase"], "extracting_items")
        self.assertEqual(data["toc_visual_progress_pct"], 68)
        self.assertEqual(data["toc_visual_progress_label"], "目录项抽取")
        self.assertEqual(data["toc_visual_progress_detail"], "视觉复核目录页 3/5")

    def test_resolve_visual_item_persists_pdf_page_target(self):
        doc_id = create_doc("visual-resolve.pdf")
        save_pages_to_disk(
            [
                {"bookPage": 1, "fileIdx": 5, "markdown": "第 1 页", "footnotes": ""},
                {"bookPage": 2, "fileIdx": 6, "markdown": "第 2 页", "footnotes": ""},
            ],
            "视觉目录补录",
            doc_id,
        )
        save_auto_visual_toc_to_disk(
            doc_id,
            [
                {
                    "item_id": "visual-1",
                    "title": "第一章",
                    "depth": 0,
                    "book_page": 11,
                    "visual_order": 1,
                }
            ],
        )
        update_doc_meta(doc_id, toc_visual_status="needs_offset")

        resp = self.client.post(
            "/api/toc/resolve_visual_item",
            query_string={"doc_id": doc_id},
            json={"item_id": "visual-1", "pdf_page": 2},
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        saved = load_auto_visual_toc_from_disk(doc_id)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["item_id"], "visual-1")
        self.assertEqual(saved[0]["title"], "第一章")
        self.assertEqual(saved[0]["depth"], 0)
        self.assertEqual(saved[0]["book_page"], 11)
        self.assertEqual(saved[0]["file_idx"], 6)
        self.assertEqual(saved[0]["visual_order"], 1)
        self.assertTrue(saved[0]["resolved_by_user"])
        self.assertEqual(saved[0]["resolution_source"], "manual_pdf_page")

    def test_pdf_toc_route_includes_auto_visual_editor_payload(self):
        doc_id = create_doc("visual-editor-payload.pdf")
        save_pages_to_disk(
            [
                {"bookPage": 2, "fileIdx": 5, "markdown": "第 2 页", "footnotes": ""},
                {"bookPage": 3, "fileIdx": 6, "markdown": "第 3 页", "footnotes": ""},
            ],
            "视觉目录编辑",
            doc_id,
        )
        save_auto_visual_toc_to_disk(
            doc_id,
            [
                {
                    "item_id": "visual-1",
                    "title": "第一章",
                    "depth": 0,
                    "file_idx": 5,
                    "visual_order": 1,
                },
                {
                    "item_id": "visual-2",
                    "title": "第二章",
                    "depth": 1,
                    "book_page": 18,
                    "visual_order": 2,
                },
            ],
        )
        update_doc_meta(doc_id, toc_visual_status="needs_offset")

        resp = self.client.get("/pdf_toc", query_string={"doc_id": doc_id})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["source"], "auto_visual")
        self.assertEqual(
            data["auto_visual_toc"],
            [
                {
                    "item_id": "visual-1",
                    "title": "第一章",
                    "depth": 0,
                    "file_idx": 5,
                    "book_page": None,
                    "pdf_page": 2,
                    "visual_order": 1,
                },
                {
                    "item_id": "visual-2",
                    "title": "第二章",
                    "depth": 1,
                    "file_idx": None,
                    "book_page": 18,
                    "pdf_page": None,
                    "visual_order": 2,
                },
            ],
        )

    def test_pdf_toc_route_keeps_auto_visual_editor_order_by_visual_order(self):
        doc_id = create_doc("visual-editor-order-by-visual.pdf")
        save_pages_to_disk(
            [
                {"bookPage": 2, "fileIdx": 5, "markdown": "第 2 页", "footnotes": ""},
                {"bookPage": 5, "fileIdx": 8, "markdown": "第 5 页", "footnotes": ""},
                {"bookPage": 7, "fileIdx": 10, "markdown": "第 7 页", "footnotes": ""},
            ],
            "视觉目录排序",
            doc_id,
        )
        save_auto_visual_toc_to_disk(
            doc_id,
            [
                {
                    "item_id": "visual-1",
                    "title": "第三章",
                    "depth": 0,
                    "file_idx": 10,
                    "visual_order": 1,
                },
                {
                    "item_id": "visual-2",
                    "title": "第一章",
                    "depth": 0,
                    "file_idx": 5,
                    "visual_order": 2,
                },
                {
                    "item_id": "visual-3",
                    "title": "第二章",
                    "depth": 0,
                    "file_idx": 8,
                    "visual_order": 3,
                },
            ],
        )

        resp = self.client.get("/pdf_toc", query_string={"doc_id": doc_id})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data.get("has_toc_draft"))
        self.assertEqual(
            [item["title"] for item in data["auto_visual_toc"]],
            ["第三章", "第一章", "第二章"],
        )
        self.assertEqual(
            [item["pdf_page"] for item in data["auto_visual_toc"]],
            [7, 2, 5],
        )

    def test_save_visual_draft_leaves_sqlite_auto_visual_unchanged(self):
        doc_id = create_doc("visual-draft-save.pdf")
        save_pages_to_disk(
            [
                {"bookPage": 4, "fileIdx": 12, "markdown": "x", "footnotes": ""},
                {"bookPage": 5, "fileIdx": 13, "markdown": "y", "footnotes": ""},
            ],
            "draft.pdf",
            doc_id,
        )
        save_auto_visual_toc_to_disk(
            doc_id,
            [
                {
                    "item_id": "visual-1",
                    "title": "原标题一",
                    "depth": 0,
                    "file_idx": 12,
                    "visual_order": 1,
                },
                {
                    "item_id": "visual-2",
                    "title": "原标题二",
                    "depth": 0,
                    "file_idx": 13,
                    "visual_order": 2,
                },
            ],
        )
        sqlite_snapshot = load_auto_visual_toc_from_disk(doc_id)
        resp = self.client.post(
            "/api/toc/save_visual_draft",
            query_string={"doc_id": doc_id},
            json={
                "items": [
                    {"item_id": "visual-1", "title": "草稿标题一", "depth": 0, "pdf_page": 4},
                    {"item_id": "visual-2", "title": "原标题二", "depth": 0, "pdf_page": 5},
                ],
                "pending_offset": 3,
            },
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        self.assertEqual(load_auto_visual_toc_from_disk(doc_id), sqlite_snapshot)
        self.assertTrue(has_toc_visual_draft(doc_id))
        toc_resp = self.client.get("/pdf_toc", query_string={"doc_id": doc_id})
        data = toc_resp.get_json()
        self.assertTrue(data["has_toc_draft"])
        self.assertEqual(data["draft_pending_offset"], 3)
        self.assertEqual([x["title"] for x in data["auto_visual_toc"]], ["草稿标题一", "原标题二"])

    def test_commit_visual_draft_writes_user_toc_and_clears_draft(self):
        doc_id = create_doc("visual-draft-commit.pdf")
        save_pages_to_disk(
            [
                {"bookPage": 4, "fileIdx": 12, "markdown": "x", "footnotes": ""},
                {"bookPage": 5, "fileIdx": 13, "markdown": "y", "footnotes": ""},
            ],
            "draft-commit.pdf",
            doc_id,
        )
        save_auto_visual_toc_to_disk(
            doc_id,
            [
                {
                    "item_id": "visual-1",
                    "title": "条目一",
                    "depth": 0,
                    "file_idx": 12,
                    "visual_order": 1,
                },
                {
                    "item_id": "visual-2",
                    "title": "条目二",
                    "depth": 1,
                    "file_idx": 13,
                    "visual_order": 2,
                },
            ],
        )
        save_resp = self.client.post(
            "/api/toc/save_visual_draft",
            query_string={"doc_id": doc_id},
            json={
                "items": [
                    {"item_id": "visual-1", "title": "条目一", "depth": 0, "pdf_page": 4},
                    {"item_id": "visual-2", "title": "条目二", "depth": 1, "pdf_page": 5},
                ],
                "pending_offset": 2,
            },
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )
        self.assertEqual(save_resp.status_code, 200)
        self.assertTrue(save_resp.get_json()["ok"])
        self.assertTrue(has_toc_visual_draft(doc_id))

        resp = self.client.post(
            "/api/toc/commit_visual_draft",
            query_string={"doc_id": doc_id},
            json={"pending_offset": 2},
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        self.assertFalse(has_toc_visual_draft(doc_id))
        source, offset, toc_rows = load_effective_toc(doc_id)
        self.assertEqual(source, "user")
        self.assertEqual(offset, 2)
        self.assertEqual(len(toc_rows), 2)
        self.assertEqual(toc_rows[0]["title"], "条目一")
        self.assertEqual(toc_rows[1]["title"], "条目二")

    def test_commit_visual_draft_without_draft_returns_400(self):
        doc_id = create_doc("visual-no-draft.pdf")
        resp = self.client.post(
            "/api/toc/commit_visual_draft",
            query_string={"doc_id": doc_id},
            json={"pending_offset": 0},
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

    def test_api_toc_update_user_persists_and_returns_toc(self):
        doc_id = create_doc("toc-update-user-api.pdf")
        save_user_toc_to_disk(doc_id, [{"title": "第一章", "depth": 0, "book_page": 1}])
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 2)

        resp = self.client.post(
            "/api/toc/update_user",
            query_string={"doc_id": doc_id},
            json={
                "items": [
                    {"title": "第一章改", "depth": 1, "pdf_page": 8},
                    {"title": "第二章", "depth": 0, "pdf_page": 15},
                ],
                "offset": 5,
            },
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["updated"], 2)
        self.assertEqual(payload["offset"], 5)
        self.assertEqual(len(payload["toc"]), 2)
        self.assertEqual(payload["toc"][0]["title"], "第一章改")
        src, off, rows = load_effective_toc(doc_id)
        self.assertEqual(src, "user")
        self.assertEqual(off, 5)
        self.assertEqual(rows[1]["title"], "第二章")

    def test_api_toc_update_user_rejects_pdf_page_too_small_for_offset(self):
        doc_id = create_doc("toc-update-user-pdf-bound.pdf")
        save_user_toc_to_disk(doc_id, [{"title": "A", "depth": 0, "book_page": 1}])
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 10)

        resp = self.client.post(
            "/api/toc/update_user",
            query_string={"doc_id": doc_id},
            json={"items": [{"title": "A", "depth": 0, "pdf_page": 5}], "offset": 10},
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

    def test_api_toc_update_user_rejects_when_effective_not_user(self):
        doc_id = create_doc("toc-update-user-not-user.pdf")
        save_auto_visual_toc_to_disk(
            doc_id,
            [{"title": "视觉", "depth": 0, "book_page": 1, "item_id": "v1"}],
        )
        update_doc_meta(doc_id, toc_visual_status="ready")

        resp = self.client.post(
            "/api/toc/update_user",
            query_string={"doc_id": doc_id},
            json={"items": [{"title": "x", "depth": 0, "pdf_page": 1}], "offset": 0},
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

    def test_pdf_toc_auto_visual_editor_empty_when_effective_toc_is_user(self):
        """生效目录为用户时，auto_visual_toc 不应再塞入 SQLite 自动视觉备份（避免与 data.toc 冲突）。"""
        doc_id = create_doc("pdf-toc-user-hides-av-editor.pdf")
        save_pages_to_disk(
            [{"bookPage": 4, "fileIdx": 12, "markdown": "x", "footnotes": ""}],
            "user-eff.pdf",
            doc_id,
        )
        save_auto_visual_toc_to_disk(
            doc_id,
            [{"item_id": "visual-1", "title": "仅作备份的自动视觉", "depth": 0, "file_idx": 12, "visual_order": 1}],
        )
        update_doc_meta(doc_id, toc_visual_status="ready")
        save_user_toc_to_disk(doc_id, [{"title": "用户生效行", "depth": 0, "book_page": 1}])
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 0)

        resp = self.client.get("/pdf_toc", query_string={"doc_id": doc_id})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["source"], "user")
        self.assertEqual(data["auto_visual_toc"], [])
        self.assertEqual(len(data["toc"]), 1)
        self.assertEqual(data["toc"][0]["title"], "用户生效行")

    def test_update_auto_visual_toc_persists_title_depth_order_and_pdf_mapping(self):
        doc_id = create_doc("visual-edit-save.pdf")
        save_pages_to_disk(
            [
                {"bookPage": 4, "fileIdx": 12, "markdown": "第 4 页", "footnotes": ""},
                {"bookPage": 5, "fileIdx": 13, "markdown": "第 5 页", "footnotes": ""},
            ],
            "视觉目录编辑",
            doc_id,
        )
        save_auto_visual_toc_to_disk(
            doc_id,
            [
                {
                    "item_id": "visual-1",
                    "title": "旧标题一",
                    "depth": 0,
                    "file_idx": 12,
                    "visual_order": 1,
                },
                {
                    "item_id": "visual-2",
                    "title": "旧标题二",
                    "depth": 1,
                    "book_page": 17,
                    "visual_order": 2,
                },
            ],
        )
        update_doc_meta(doc_id, toc_visual_status="needs_offset")

        resp = self.client.post(
            "/api/toc/update_auto_visual",
            query_string={"doc_id": doc_id},
            json={
                "items": [
                    {
                        "item_id": "visual-2",
                        "title": "新标题二",
                        "depth": 0,
                        "pdf_page": 5,
                    },
                    {
                        "item_id": "visual-1",
                        "title": "新标题一",
                        "depth": 2,
                        "pdf_page": 4,
                    },
                ]
            },
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        saved = load_auto_visual_toc_from_disk(doc_id)
        self.assertEqual([row["item_id"] for row in saved], ["visual-2", "visual-1"])
        self.assertEqual([row["title"] for row in saved], ["新标题二", "新标题一"])
        self.assertEqual([row["depth"] for row in saved], [0, 2])
        self.assertEqual([row["file_idx"] for row in saved], [13, 12])
        self.assertEqual([row["visual_order"] for row in saved], [1, 2])
        self.assertTrue(all(row.get("resolved_by_user") for row in saved))
        self.assertTrue(all(row.get("resolution_source") == "manual_edit" for row in saved))
        self.assertEqual(load_effective_toc(doc_id)[2][0]["title"], "新标题二")

    def test_update_auto_visual_toc_allows_deleting_single_item(self):
        doc_id = create_doc("visual-edit-delete-one.pdf")
        save_pages_to_disk(
            [
                {"bookPage": 4, "fileIdx": 12, "markdown": "第 4 页", "footnotes": ""},
                {"bookPage": 5, "fileIdx": 13, "markdown": "第 5 页", "footnotes": ""},
            ],
            "视觉目录删除",
            doc_id,
        )
        save_auto_visual_toc_to_disk(
            doc_id,
            [
                {
                    "item_id": "visual-1",
                    "title": "旧标题一",
                    "depth": 0,
                    "file_idx": 12,
                    "visual_order": 1,
                },
                {
                    "item_id": "visual-2",
                    "title": "旧标题二",
                    "depth": 1,
                    "file_idx": 13,
                    "visual_order": 2,
                },
            ],
        )
        update_doc_meta(doc_id, toc_visual_status="ready")

        resp = self.client.post(
            "/api/toc/update_auto_visual",
            query_string={"doc_id": doc_id},
            json={
                "items": [
                    {
                        "item_id": "visual-2",
                        "title": "保留标题二",
                        "depth": 1,
                        "pdf_page": 5,
                    }
                ]
            },
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        saved = load_auto_visual_toc_from_disk(doc_id)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["item_id"], "visual-2")
        self.assertEqual(saved[0]["title"], "保留标题二")
        self.assertEqual(saved[0]["depth"], 1)
        self.assertEqual(saved[0]["file_idx"], 13)
        self.assertEqual(saved[0]["visual_order"], 1)
        self.assertTrue(saved[0]["resolved_by_user"])
        self.assertEqual(saved[0]["resolution_source"], "manual_edit")

    def test_manual_toc_import_keeps_existing_auto_visual_toc(self):
        doc_id = create_doc("toc-keep-visual.pdf")
        set_current_doc(doc_id)
        visual_toc = [{"title": "视觉目录", "depth": 0, "file_idx": 12}]
        save_auto_visual_toc_to_disk(doc_id, visual_toc)

        resp = self.client.post(
            "/api/toc/import",
            query_string={"doc_id": doc_id},
            data={"file": (io.BytesIO("title,depth,page\n第一章,0,1\n".encode("utf-8")), "目录总表.csv")},
            headers={"X-CSRF-Token": self._ensure_csrf_token()},
            content_type="multipart/form-data",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(load_auto_visual_toc_from_disk(doc_id), visual_toc)
        self.assertEqual(load_effective_toc(doc_id)[0], "user")

    def test_reading_keeps_toc_button_after_navigation_state_updates(self):
        doc_id = create_doc("toc-reading.pdf")
        set_current_doc(doc_id)
        save_pages_to_disk(
            [
                {"bookPage": 1, "fileIdx": 5, "markdown": "第一页正文", "footnotes": ""},
                {"bookPage": 2, "fileIdx": 6, "markdown": "第二页正文", "footnotes": ""},
            ],
            "toc-reading.pdf",
            doc_id,
        )
        save_entries_to_disk(
            [
                {
                    "_pageBP": 1,
                    "_model": "qwen-plus",
                    "_page_entries": [{"original": "A", "translation": "甲"}],
                    "pages": "1",
                },
                {
                    "_pageBP": 2,
                    "_model": "qwen-plus",
                    "_page_entries": [{"original": "B", "translation": "乙"}],
                    "pages": "2",
                },
            ],
            "阅读页目录测试",
            0,
            doc_id,
        )
        SQLiteRepository().set_document_toc(
            doc_id,
            [
                {"title": "第一章", "depth": 0, "book_page": 1},
                {"title": "第二章", "depth": 0, "book_page": 2},
            ],
        )
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 4)
        save_toc_file(
            doc_id,
            FileStorage(stream=io.BytesIO(b"title,depth,page\nChapter 1,0,1\nChapter 2,0,2\n"), filename="阅读目录.csv"),
        )

        first_resp = self.client.get("/reading", query_string={"doc_id": doc_id, "bp": 1})
        first_html = first_resp.get_data(as_text=True)
        self.assertEqual(first_resp.status_code, 200)
        self.assertIn('id="tocBtn"', first_html)

        second_resp = self.client.get("/reading", query_string={"doc_id": doc_id, "bp": 2})
        second_html = second_resp.get_data(as_text=True)
        self.assertEqual(second_resp.status_code, 200)
        self.assertIn('id="tocBtn"', second_html)
        self.assertEqual(len(SQLiteRepository().get_document_toc(doc_id)), 2)

    def test_load_pages_repairs_pdf_navigation_pages_and_migrates_entries(self):
        doc_id = create_doc("repair-pages.pdf")
        pdf_path = os.path.join(config.get_doc_dir(doc_id), "source.pdf")
        with open(pdf_path, "wb") as f:
            f.write(_build_labeled_pdf(total_pages=4, label_start_page=3, start_label=1))

        save_pages_to_disk(
            [
                {"bookPage": 1, "fileIdx": 2, "markdown": "第三页正文", "footnotes": ""},
                {"bookPage": 2, "fileIdx": 3, "markdown": "第四页正文", "footnotes": ""},
            ],
            "repair-pages.pdf",
            doc_id,
        )
        save_entries_to_disk(
            [
                {
                    "_pageBP": 1,
                    "_model": "qwen-plus",
                    "_page_entries": [
                        {
                            "original": "段落 A",
                            "translation": "译文 A",
                            "heading_level": 0,
                            "pages": "原书 p.1",
                            "_startBP": 1,
                            "_endBP": 1,
                            "_printPageLabel": "1",
                        }
                    ],
                    "pages": "原书 p.1",
                }
            ],
            "Repair Doc",
            0,
            doc_id,
        )

        pages, _ = load_pages_from_disk(doc_id)
        self.assertEqual([page["bookPage"] for page in pages], [1, 2, 3, 4])
        self.assertEqual(pages[2].get("pdfPage"), 3)
        self.assertEqual(pages[2].get("printPageLabel"), "1")
        self.assertEqual(pages[3].get("printPageLabel"), "2")

        entries, _, _ = load_entries_from_disk(doc_id)
        self.assertEqual(entries[0]["_pageBP"], 3)
        self.assertEqual(entries[0]["pages"], "原书 p.1")
        self.assertEqual(entries[0]["_page_entries"][0]["pages"], "原书 p.1")

        state = get_app_state(doc_id)
        self.assertEqual(state["first_page"], 3)
        self.assertEqual(state["last_page"], 4)
        self.assertEqual(state["page_count"], 2)
        self.assertEqual(state["hidden_placeholder_bps"], [1, 2])

    def test_start_reading_rejects_missing_page_even_if_within_numeric_range(self):
        doc_id = create_doc("gap-input.pdf")
        set_current_doc(doc_id)
        save_pages_to_disk(
            [
                {"bookPage": 1, "fileIdx": 0, "markdown": "第一页", "footnotes": ""},
                {"bookPage": 2, "fileIdx": 1, "markdown": "第二页", "footnotes": ""},
                {"bookPage": 4, "fileIdx": 3, "markdown": "第四页", "footnotes": ""},
            ],
            "gap-input.pdf",
            doc_id,
        )

        with patch.object(storage, "get_translate_args", return_value={"api_key": "fake-key", "provider": "deepseek"}):
            resp = self._post(
                "/start_reading",
                data={"doc_id": doc_id, "doc_title": "Gap Doc", "start_page": 3},
                follow_redirects=True,
            )

        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("请输入有效页码", html)
        self.assertIn("输入起始页码", html)
        self.assertNotIn("/reading?bp=3", html)

    def test_reading_renders_resolved_toc_target_pages(self):
        doc_id = create_doc("toc-target.pdf")
        set_current_doc(doc_id)
        save_pages_to_disk(
            [
                {"bookPage": 1, "fileIdx": 0, "markdown": "PDF 1", "footnotes": "", "pdfPage": 1, "printPageLabel": ""},
                {"bookPage": 2, "fileIdx": 1, "markdown": "PDF 2", "footnotes": "", "pdfPage": 2, "printPageLabel": ""},
                {"bookPage": 3, "fileIdx": 2, "markdown": "PDF 3", "footnotes": "", "pdfPage": 3, "printPageLabel": "1"},
                {"bookPage": 4, "fileIdx": 3, "markdown": "PDF 4", "footnotes": "", "pdfPage": 4, "printPageLabel": "2"},
            ],
            "toc-target.pdf",
            doc_id,
        )
        SQLiteRepository().set_document_toc(
            doc_id,
            [
                {"title": "第一章", "depth": 0, "book_page": 1},
                {"title": "第二章", "depth": 0, "book_page": 2},
            ],
        )
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 2)
        save_toc_file(
            doc_id,
            FileStorage(stream=io.BytesIO(b"title,depth,page\nA,0,1\nB,0,2\n"), filename="toc.csv"),
        )

        resp = self.client.get("/reading", query_string={"doc_id": doc_id, "bp": 3})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-target-page="3"', html)
        self.assertIn('data-target-page="4"', html)
        self.assertIn("原书 p.1", html)

    def test_save_entries_preserves_segment_page_metadata(self):
        doc_id = create_doc("segment-pages.pdf")
        save_entries_to_disk(
            [
                {
                    "_pageBP": 3,
                    "_model": "qwen-plus",
                    "_page_entries": [
                        {
                            "original": "段落 A",
                            "translation": "译文 A",
                            "heading_level": 0,
                            "pages": "原书 p.1-2",
                            "_startBP": 3,
                            "_endBP": 4,
                            "_printPageLabel": "1-2",
                        }
                    ],
                    "pages": "原书 p.1",
                }
            ],
            "Segment Doc",
            0,
            doc_id,
        )

        entries, _, _ = load_entries_from_disk(doc_id)
        seg = entries[0]["_page_entries"][0]
        self.assertEqual(seg["pages"], "原书 p.1-2")
        self.assertEqual(seg["_startBP"], 3)
        self.assertEqual(seg["_endBP"], 4)
        self.assertEqual(seg["_printPageLabel"], "1-2")

    def test_pdf_toc_recovers_user_toc_from_saved_file_when_json_missing(self):
        doc_id = create_doc("toc-recover.pdf")
        set_current_doc(doc_id)
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 6)
        save_toc_file(
            doc_id,
            FileStorage(
                stream=io.BytesIO("title,depth,page\n导论,0,1\n第一章,0,7\n".encode("utf-8")),
                filename="recover-toc.csv",
            ),
        )

        resp = self.client.get("/pdf_toc", query_string={"doc_id": doc_id})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["toc"]), 2)
        self.assertEqual(data["toc"][0]["title"], "导论")
        self.assertEqual(SQLiteRepository().get_document_toc(doc_id)[1]["book_page"], 7)

    def test_pdf_toc_recovers_user_toc_from_saved_xlsx_file_without_openpyxl(self):
        doc_id = create_doc("toc-recover-xlsx.pdf")
        set_current_doc(doc_id)
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 4)
        save_toc_file(
            doc_id,
            FileStorage(
                stream=io.BytesIO(
                    _build_simple_xlsx(
                        [
                            ["title", "depth", "page"],
                            ["前言", 0, 1],
                            ["第一章", 1, 9],
                        ]
                    )
                ),
                filename="recover-toc.xlsx",
            ),
        )

        resp = self.client.get("/pdf_toc", query_string={"doc_id": doc_id})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["toc"]), 2)
        self.assertEqual(data["toc"][0]["title"], "前言")
        self.assertEqual(data["toc"][1]["book_page"], 9)

    def test_glossary_crud_api(self):
        doc_id = create_doc("glossary-api.pdf")
        set_current_doc(doc_id)

        # create
        resp = self._post_json(
            "/api/glossary",
            query_string={"doc_id": doc_id},
            json={"term": "State", "defn": "状态"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["updated"])

        # list
        list_resp = self.client.get("/api/glossary", query_string={"doc_id": doc_id})
        self.assertEqual(list_resp.status_code, 200)
        items = list_resp.get_json()["items"]
        self.assertIn(["State", "状态"], items)

        # update
        upd_resp = self._put_json(
            "/api/glossary/State",
            query_string={"doc_id": doc_id},
            json={"defn": "状态(更新)"},
        )
        self.assertEqual(upd_resp.status_code, 200)
        upd_items = upd_resp.get_json()["items"]
        self.assertIn(["State", "状态(更新)"], upd_items)

        # delete
        del_resp = self._delete("/api/glossary/State", query_string={"doc_id": doc_id})
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.get_json()["ok"])

        missing_resp = self._delete("/api/glossary/State", query_string={"doc_id": doc_id})
        self.assertEqual(missing_resp.status_code, 404)

    def test_glossary_retranslate_preview_uses_last_entry_idx_and_reports_problem_segments(self):
        doc_id = create_doc("glossary-preview.pdf")
        set_current_doc(doc_id)
        config.set_glossary(
            [["Alpha", "阿尔法"], ["Gamma", "伽马"], ["Delta", "德尔塔"]],
            doc_id=doc_id,
        )
        save_pages_to_disk(
            [
                {"bookPage": 1, "fileIdx": 0, "imgW": 100, "imgH": 100, "markdown": "Alpha\n\nBeta", "footnotes": ""},
                {"bookPage": 2, "fileIdx": 1, "imgW": 100, "imgH": 100, "markdown": "Gamma\n\nDelta", "footnotes": ""},
                {"bookPage": 3, "fileIdx": 2, "imgW": 100, "imgH": 100, "markdown": "Epsilon", "footnotes": ""},
            ],
            "Glossary Preview",
            doc_id,
        )
        save_entries_to_disk(
            [
                {
                    "_pageBP": 1,
                    "_page_entries": [
                        {
                            "original": "Alpha",
                            "translation": "阿尔法",
                            "_machine_translation": "阿尔法",
                            "_translation_source": "model",
                            "footnotes": "",
                            "footnotes_translation": "",
                            "heading_level": 0,
                            "pages": "1",
                            "_startBP": 1,
                            "_endBP": 1,
                        },
                        {
                            "original": "Beta",
                            "translation": "贝塔",
                            "_machine_translation": "贝塔",
                            "_translation_source": "model",
                            "footnotes": "",
                            "footnotes_translation": "",
                            "heading_level": 0,
                            "pages": "1",
                            "_startBP": 1,
                            "_endBP": 1,
                        },
                    ],
                    "pages": "1",
                },
                {
                    "_pageBP": 2,
                    "_page_entries": [
                        {
                            "original": "Gamma",
                            "translation": "旧译 Gamma",
                            "_machine_translation": "旧译 Gamma",
                            "_translation_source": "model",
                            "footnotes": "",
                            "footnotes_translation": "",
                            "heading_level": 0,
                            "pages": "2",
                            "_startBP": 2,
                            "_endBP": 2,
                        },
                        {
                            "original": "Delta",
                            "translation": "人工译名",
                            "_machine_translation": "机翻德尔塔",
                            "_manual_translation": "人工译名",
                            "_translation_source": "manual",
                            "_manual_updated_at": 123,
                            "_manual_updated_by": "tester",
                            "footnotes": "",
                            "footnotes_translation": "",
                            "heading_level": 0,
                            "pages": "2",
                            "_startBP": 2,
                            "_endBP": 2,
                        },
                    ],
                    "pages": "2",
                },
            ],
            "Glossary Preview",
            1,
            doc_id,
        )

        resp = self.client.get("/api/glossary_retranslate_preview", query_string={"doc_id": doc_id})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["start_bp"], 2)
        self.assertEqual(data["start_segment_index"], 0)
        self.assertEqual(data["end_bp"], 2)
        self.assertEqual(data["affected_pages"], 1)
        self.assertEqual(data["affected_segments"], 1)
        self.assertEqual(data["skipped_manual_segments"], 1)
        self.assertTrue(data["can_start"])
        self.assertEqual(data["target_bps"], [2])
        self.assertEqual(data["target_segments_by_bp"], {"2": [0]})
        self.assertFalse(data["problem_list_truncated"])
        self.assertEqual(len(data["problem_segments"]), 1)
        self.assertEqual(data["problem_segments"][0]["bp"], 2)
        self.assertEqual(data["problem_segments"][0]["segment_index"], 0)
        self.assertEqual(data["problem_segments"][0]["missing_terms"], [{"term": "Gamma", "defn": "伽马"}])

    def test_glossary_retranslate_preview_stays_non_startable_when_only_manual_segments_have_glossary_issues(self):
        doc_id = create_doc("glossary-manual-only.pdf")
        set_current_doc(doc_id)
        config.set_glossary([["Delta", "德尔塔"]], doc_id=doc_id)
        save_pages_to_disk(
            [
                {"bookPage": 2, "fileIdx": 0, "imgW": 100, "imgH": 100, "markdown": "Delta", "footnotes": ""},
            ],
            "Glossary Manual Only",
            doc_id,
        )
        save_entries_to_disk(
            [
                {
                    "_pageBP": 2,
                    "_page_entries": [
                        {
                            "original": "Delta",
                            "translation": "人工译名",
                            "_machine_translation": "旧译 Delta",
                            "_manual_translation": "人工译名",
                            "_translation_source": "manual",
                            "_manual_updated_at": 123,
                            "_manual_updated_by": "tester",
                            "footnotes": "",
                            "footnotes_translation": "",
                            "heading_level": 0,
                            "pages": "2",
                            "_startBP": 2,
                            "_endBP": 2,
                        },
                    ],
                    "pages": "2",
                }
            ],
            "Glossary Manual Only",
            0,
            doc_id,
        )

        resp = self.client.get("/api/glossary_retranslate_preview", query_string={"doc_id": doc_id})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["can_start"])
        self.assertEqual(data["affected_segments"], 0)
        self.assertEqual(data["skipped_manual_segments"], 1)
        self.assertEqual(data["problem_segments"], [])
        self.assertIn("没有可自动补重译的机器段落", data["reason"])

    def test_retranslate_page_with_current_glossary_preserves_manual_and_prior_segments(self):
        pages = [
            {
                "bookPage": 2,
                "fileIdx": 0,
                "imgW": 100,
                "imgH": 100,
                "markdown": "Alpha\n\nBeta\n\nGamma",
                "footnotes": "",
            }
        ]
        para_jobs = [
            {
                "text": "Alpha",
                "footnotes": "",
                "heading_level": 0,
                "print_page_display": "2",
                "print_page_label": "2",
                "start_bp": 2,
                "end_bp": 2,
                "cross_page": False,
                "bboxes": [],
                "note_kind": "",
                "note_marker": "",
                "note_number": None,
                "note_section_title": "",
                "note_confidence": 0.0,
                "prev_context": "",
                "next_context": "",
                "section_path": [],
                "para_idx": 0,
                "para_total": 3,
                "content_role": "body",
            },
            {
                "text": "Beta",
                "footnotes": "",
                "heading_level": 0,
                "print_page_display": "2",
                "print_page_label": "2",
                "start_bp": 2,
                "end_bp": 2,
                "cross_page": False,
                "bboxes": [],
                "note_kind": "",
                "note_marker": "",
                "note_number": None,
                "note_section_title": "",
                "note_confidence": 0.0,
                "prev_context": "",
                "next_context": "",
                "section_path": [],
                "para_idx": 1,
                "para_total": 3,
                "content_role": "body",
            },
            {
                "text": "Gamma",
                "footnotes": "",
                "heading_level": 0,
                "print_page_display": "2",
                "print_page_label": "2",
                "start_bp": 2,
                "end_bp": 2,
                "cross_page": False,
                "bboxes": [],
                "note_kind": "",
                "note_marker": "",
                "note_number": None,
                "note_section_title": "",
                "note_confidence": 0.0,
                "prev_context": "",
                "next_context": "",
                "section_path": [],
                "para_idx": 2,
                "para_total": 3,
                "content_role": "body",
            },
        ]
        existing_entry = {
            "_pageBP": 2,
            "_page_entries": [
                {
                    "original": "Alpha",
                    "translation": "旧译 Alpha",
                    "_machine_translation": "旧译 Alpha",
                    "_translation_source": "model",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "2",
                    "_startBP": 2,
                    "_endBP": 2,
                },
                {
                    "original": "Beta",
                    "translation": "人工 Beta",
                    "_machine_translation": "机翻 Beta",
                    "_manual_translation": "人工 Beta",
                    "_translation_source": "manual",
                    "_manual_updated_at": 456,
                    "_manual_updated_by": "tester",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "2",
                    "_startBP": 2,
                    "_endBP": 2,
                },
                {
                    "original": "Gamma",
                    "translation": "旧译 Gamma",
                    "_machine_translation": "旧译 Gamma",
                    "_translation_source": "model",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "2",
                    "_startBP": 2,
                    "_endBP": 2,
                },
            ],
        }
        translated_texts = []

        def _fake_translate_paragraph(*, para_text, **kwargs):
            translated_texts.append(para_text)
            return {
                "original": para_text,
                "translation": "新译 " + para_text,
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "_usage": {"request_count": 1},
            }

        with (
            patch.object(tasks, "_prepare_page_translate_jobs", return_value=({"footnotes": ""}, para_jobs, {"request_count": 0})),
            patch.object(tasks, "translate_paragraph", side_effect=_fake_translate_paragraph),
        ):
            entry, page_stats = tasks.retranslate_page_with_current_glossary(
                pages,
                2,
                existing_entry,
                "qwen-plus",
                {"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"},
                [["Gamma", "伽马"]],
                target_segment_indices=[2],
            )

        self.assertEqual(translated_texts, ["Gamma"])
        segments = entry["_page_entries"]
        self.assertEqual(segments[0]["translation"], "旧译 Alpha")
        self.assertEqual(segments[0]["_translation_source"], "model")
        self.assertEqual(segments[1]["translation"], "人工 Beta")
        self.assertEqual(segments[1]["_translation_source"], "manual")
        self.assertEqual(segments[1]["_machine_translation"], "机翻 Beta")
        self.assertEqual(segments[1]["_manual_updated_at"], 456)
        self.assertEqual(segments[1]["_manual_updated_by"], "tester")
        self.assertEqual(segments[2]["translation"], "新译 Gamma")
        self.assertEqual(segments[2]["_machine_translation"], "新译 Gamma")
        self.assertEqual(page_stats["targeted_segments"], 1)
        self.assertEqual(page_stats["targeted_segment_indices"], [2])
        self.assertEqual(page_stats["skipped_manual_segments"], 0)

    def test_retranslate_page_with_current_glossary_rejects_structure_drift(self):
        pages = [
            {
                "bookPage": 3,
                "fileIdx": 0,
                "imgW": 100,
                "imgH": 100,
                "markdown": "One\n\nTwo",
                "footnotes": "",
            }
        ]
        para_jobs = [
            {
                "text": "One",
                "footnotes": "",
                "heading_level": 0,
                "print_page_display": "3",
                "print_page_label": "3",
                "start_bp": 3,
                "end_bp": 3,
                "cross_page": False,
                "bboxes": [],
                "note_kind": "",
                "note_marker": "",
                "note_number": None,
                "note_section_title": "",
                "note_confidence": 0.0,
                "prev_context": "",
                "next_context": "",
                "section_path": [],
                "para_idx": 0,
                "para_total": 2,
                "content_role": "body",
            },
            {
                "text": "Two",
                "footnotes": "",
                "heading_level": 0,
                "print_page_display": "3",
                "print_page_label": "3",
                "start_bp": 3,
                "end_bp": 3,
                "cross_page": False,
                "bboxes": [],
                "note_kind": "",
                "note_marker": "",
                "note_number": None,
                "note_section_title": "",
                "note_confidence": 0.0,
                "prev_context": "",
                "next_context": "",
                "section_path": [],
                "para_idx": 1,
                "para_total": 2,
                "content_role": "body",
            },
        ]
        existing_entry = {
            "_pageBP": 3,
            "_page_entries": [
                {
                    "original": "One",
                    "translation": "旧译 One",
                    "_machine_translation": "旧译 One",
                    "_translation_source": "model",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "3",
                    "_startBP": 3,
                    "_endBP": 3,
                }
            ],
        }

        with (
            patch.object(tasks, "_prepare_page_translate_jobs", return_value=({"footnotes": ""}, para_jobs, {"request_count": 0})),
            self.assertRaisesRegex(RuntimeError, "第3页段落结构已变化，请改用整页重译。"),
        ):
            tasks.retranslate_page_with_current_glossary(
                pages,
                3,
                existing_entry,
                "qwen-plus",
                {"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"},
                [],
                target_segment_indices=[0],
            )

    def test_translate_status_includes_task_meta(self):
        doc_id = create_doc("translate-task-meta.pdf")
        save_pages_to_disk(
            [{"bookPage": 5, "fileIdx": 0, "imgW": 100, "imgH": 100, "markdown": "Alpha", "footnotes": ""}],
            "Translate Task Meta",
            doc_id,
        )
        tasks._save_translate_state(
            doc_id,
            running=True,
            stop_requested=False,
            phase="running",
            start_bp=5,
            total_pages=2,
            done_pages=0,
            processed_pages=0,
            pending_pages=2,
            current_bp=5,
            current_page_idx=1,
            task={
                "kind": tasks.TASK_KIND_GLOSSARY_RETRANSLATE,
                "label": "词典补重译",
                "start_bp": 5,
                "start_segment_index": 1,
                "end_bp": 6,
                "target_bps": [5, 6],
                "target_segments_by_bp": {"5": [1, 3], "6": [0, 2]},
                "affected_pages": 2,
                "affected_segments": 4,
                "skipped_manual_segments": 1,
            },
        )

        resp = self.client.get("/translate_status", query_string={"doc_id": doc_id})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["task"]["kind"], "glossary_retranslate")
        self.assertEqual(data["task"]["label"], "词典补重译")
        self.assertEqual(data["task"]["start_bp"], 5)
        self.assertEqual(data["task"]["start_segment_index"], 1)
        self.assertEqual(data["task"]["end_bp"], 6)
        self.assertEqual(data["task"]["target_bps"], [5, 6])
        self.assertEqual(data["task"]["target_segments_by_bp"], {"5": [1, 3], "6": [0, 2]})

    def test_glossary_api_rejects_missing_csrf_token(self):
        doc_id = create_doc("glossary-csrf.pdf")
        set_current_doc(doc_id)

        resp = self.client.post(
            "/api/glossary",
            query_string={"doc_id": doc_id},
            json={"term": "State", "defn": "状态"},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["error"], "csrf_failed")

    def test_extract_pdf_toc_handles_empty_and_bookmarked_pdf(self):
        self.assertEqual(extract_pdf_toc(b"not-a-pdf"), [])

        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.add_blank_page(width=300, height=400)
        if hasattr(writer, "add_outline_item"):
            writer.add_outline_item("Chapter 1", 0)
            writer.add_outline_item("Chapter 2", 1)
        else:  # pragma: no cover - 兼容旧版本 pypdf
            writer.addBookmark("Chapter 1", 0)
            writer.addBookmark("Chapter 2", 1)
        buf = io.BytesIO()
        writer.write(buf)
        toc = extract_pdf_toc(buf.getvalue())
        self.assertGreaterEqual(len(toc), 2)
        self.assertEqual(toc[0]["title"], "Chapter 1")
        self.assertEqual(toc[0]["file_idx"], 0)


if __name__ == "__main__":
    unittest.main()

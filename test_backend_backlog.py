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
from config import create_doc, ensure_dirs, set_current_doc, update_doc_meta
from pdf_extract import extract_pdf_toc
from pypdf import PdfWriter
from pypdf.constants import PageLabelStyle
from sqlite_store import SQLiteRepository, get_connection
from storage import (
    get_app_state,
    load_entries_from_disk,
    load_pages_from_disk,
    get_toc_file_info,
    get_toc_file_path,
    save_auto_pdf_toc_to_disk,
    save_entries_to_disk,
    save_pages_to_disk,
    save_toc_file,
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
        SQLiteRepository().set_document_toc(doc_id, toc)
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
        SQLiteRepository().set_document_toc(doc_id, toc)
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 2)

        update_doc_meta(doc_id, last_entry_idx=3)

        self.assertEqual(SQLiteRepository().get_document_toc(doc_id), toc)

    def test_auto_pdf_toc_does_not_overwrite_user_toc(self):
        doc_id = create_doc("toc-auto-protect.pdf")
        user_toc = [{"title": "用户目录", "depth": 0, "book_page": 3}]
        SQLiteRepository().set_document_toc(doc_id, user_toc)
        SQLiteRepository().set_document_toc_source_offset(doc_id, "user", 5)
        save_toc_file(
            doc_id,
            FileStorage(stream=io.BytesIO(b"title,depth,page\nUser,0,3\n"), filename="user-toc.csv"),
        )

        save_auto_pdf_toc_to_disk(doc_id, [{"title": "PDF 书签", "depth": 0, "file_idx": 0}])

        self.assertEqual(SQLiteRepository().get_document_toc(doc_id), user_toc)

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
        self.assertEqual(state["first_page"], 1)
        self.assertEqual(state["last_page"], 4)
        self.assertEqual(state["page_count"], 4)

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

        with patch.object(app_module, "get_translate_args", return_value={"api_key": "fake-key", "provider": "deepseek"}):
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

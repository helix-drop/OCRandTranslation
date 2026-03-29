#!/usr/bin/env python3
"""后端 backlog 收口测试：状态口径、PDF TOC、术语 CRUD。"""

import io
import os
import shutil
import tempfile
import unittest

import config
import app as app_module
from config import create_doc, ensure_dirs, set_current_doc
from pdf_extract import extract_pdf_toc
from pypdf import PdfWriter
from sqlite_store import SQLiteRepository, get_connection
from storage import get_app_state, get_toc_file_info, get_toc_file_path, save_entries_to_disk, save_toc_file
from testsupport import ClientCSRFMixin
from werkzeug.datastructures import FileStorage


class BackendBacklogTest(ClientCSRFMixin, unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="backend-backlog-", dir="/tmp")
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

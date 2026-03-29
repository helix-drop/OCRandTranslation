#!/usr/bin/env python3
"""基于 example 文档的停止翻译回归测试。"""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app as app_module
import config
import pdf_extract
import tasks
from config import create_doc, ensure_dirs, get_doc_dir, set_current_doc
from ocr_parser import parse_ocr, clean_header_footer
from storage import load_entries_from_disk, save_entries_to_disk, save_pages_to_disk
from testsupport import ClientCSRFMixin
from text_processing import get_page_range


ROOT = Path(__file__).resolve().parent
EXAMPLE_DIR = ROOT / "example"
DOC_A_PDF = EXAMPLE_DIR / "10.1177@0957154X19859204.pdf"
DOC_A_OCR = EXAMPLE_DIR / "10.1177@0957154X19859204.pdf_by_PaddleOCR-VL-1.5.json"
DOC_B_PDF = EXAMPLE_DIR / "第三章.pdf"
DOC_B_OCR = EXAMPLE_DIR / "第三章.pdf_by_PaddleOCR-VL-1.5.json"


def _build_fake_translate(started: threading.Event, release: threading.Event):
    def _fake_translate(pages, target_bp, model_key, t_args, glossary, **kwargs):
        started.set()
        release.wait(timeout=2.0)
        return {
            "_pageBP": target_bp,
            "_model": model_key,
            "_page_entries": [{
                "original": f"Page {target_bp}",
                "translation": f"翻译 {target_bp}",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(target_bp),
            }],
            "pages": str(target_bp),
        }

    return _fake_translate


def _build_fake_translate_with_usage(started: threading.Event, release: threading.Event, usage: dict):
    def _fake_translate(pages, target_bp, model_key, t_args, glossary, **kwargs):
        started.set()
        release.wait(timeout=2.0)
        return {
            "_pageBP": target_bp,
            "_model": model_key,
            "_usage": dict(usage),
            "_page_entries": [{
                "original": f"Page {target_bp}",
                "translation": f"翻译 {target_bp}",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(target_bp),
            }],
            "pages": str(target_bp),
        }

    return _fake_translate


def _build_fake_translate_with_first_page_error(started: threading.Event, release: threading.Event, failed_bp: int):
    def _fake_translate(pages, target_bp, model_key, t_args, glossary, **kwargs):
        started.set()
        release.wait(timeout=2.0)
        if target_bp == failed_bp:
            raise RuntimeError(f"boom on {target_bp}")
        return {
            "_pageBP": target_bp,
            "_model": model_key,
            "_page_entries": [{
                "original": f"Page {target_bp}",
                "translation": f"翻译 {target_bp}",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(target_bp),
            }],
            "pages": str(target_bp),
        }

    return _fake_translate


def _build_fallback_pages(start_bp: int, count: int):
    return [{
        "bookPage": start_bp + idx,
        "fileIdx": idx,
        "imgW": 1000,
        "imgH": 1600,
        "markdown": f"Fallback page {start_bp + idx}",
        "footnotes": "",
    } for idx in range(count)]


class TranslateStopFlowRealDocsTest(ClientCSRFMixin, unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="translate-stop-", dir="/tmp")
        self._patch_config_dirs(self.temp_root)
        ensure_dirs()
        self._reset_translate_task()
        self.client = app_module.app.test_client()
        self.doc_a_id, self.doc_a_pages = self._create_doc_fixture(DOC_A_PDF, DOC_A_OCR)
        self.doc_b_id, self.doc_b_pages = self._create_doc_fixture(DOC_B_PDF, DOC_B_OCR)
        tasks._clear_translate_state(self.doc_a_id)
        tasks._clear_translate_state(self.doc_b_id)

    def tearDown(self):
        self._wait_for_worker_stop(timeout=3.0)
        self._reset_translate_task()
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def _reset_translate_task(self):
        with tasks._translate_lock:
            tasks._translate_task["running"] = False
            tasks._translate_task["stop"] = False
            tasks._translate_task["events"] = []
            if "doc_id" in tasks._translate_task:
                tasks._translate_task["doc_id"] = ""

    def _wait_for_worker_stop(self, timeout: float):
        end = time.time() + timeout
        while time.time() < end:
            with tasks._translate_lock:
                if not tasks._translate_task["running"]:
                    return
            time.sleep(0.05)
        self.fail("后台翻译线程未在预期时间内停止")

    def _create_doc_fixture(self, pdf_path: Path, ocr_path: Path):
        has_source_files = pdf_path.exists() and ocr_path.exists()
        if has_source_files:
            with open(ocr_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            parsed = parse_ocr(raw)
            cleaned = clean_header_footer(parsed["pages"])
            pages = cleaned["pages"]
            doc_name = pdf_path.name
        else:
            # 回归测试在无 example 数据时使用最小可用页面夹具，避免环境依赖导致失败。
            if "第三章" in str(pdf_path):
                pages = _build_fallback_pages(start_bp=101, count=6)
                doc_name = "第三章.pdf"
            else:
                pages = _build_fallback_pages(start_bp=1, count=12)
                doc_name = "10.1177@0957154X19859204.pdf"

        doc_id = create_doc(doc_name)
        save_pages_to_disk(pages, doc_name, doc_id)
        save_entries_to_disk([], pdf_path.stem, 0, doc_id)
        source_pdf = Path(get_doc_dir(doc_id)) / "source.pdf"
        if pdf_path.exists():
            shutil.copy2(pdf_path, source_pdf)
        else:
            with open(source_pdf, "wb") as f:
                f.write(b"%PDF-1.4\n%fallback\n")
        return doc_id, pages

    def test_status_and_stop_follow_started_doc_not_current_doc(self):
        started = threading.Event()
        release = threading.Event()
        first_bp, _ = get_page_range(self.doc_a_pages)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate(started, release)),
        ):
            try:
                set_current_doc(self.doc_a_id)
                resp = self._post("/start_translate_all", data={
                    "doc_id": self.doc_a_id,
                    "start_bp": first_bp,
                    "doc_title": "Doc A",
                })
                self.assertEqual(resp.get_json()["status"], "started")
                self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")

                set_current_doc(self.doc_b_id)
                stop_resp = self._post("/stop_translate", data={"doc_id": self.doc_a_id})
                self.assertEqual(stop_resp.get_json()["status"], "stopping")

                status_a = self.client.get("/translate_status", query_string={"doc_id": self.doc_a_id}).get_json()
                status_b = self.client.get("/translate_status", query_string={"doc_id": self.doc_b_id}).get_json()

                self.assertEqual(status_a["doc_id"], self.doc_a_id)
                self.assertEqual(status_a["phase"], "stopping")
                self.assertTrue(status_a["running"])
                self.assertTrue(status_a["stop_requested"])

                self.assertEqual(status_b["doc_id"], self.doc_b_id)
                self.assertEqual(status_b["phase"], "idle")
                self.assertFalse(status_b["running"])
                self.assertFalse(status_b["stop_requested"])
            finally:
                release.set()
                self._wait_for_worker_stop(timeout=3.0)

    def test_worker_saves_entries_back_to_started_doc_after_switch(self):
        started = threading.Event()
        release = threading.Event()
        first_bp, _ = get_page_range(self.doc_a_pages)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate(started, release)),
        ):
            try:
                set_current_doc(self.doc_a_id)
                resp = self._post("/start_translate_all", data={
                    "doc_id": self.doc_a_id,
                    "start_bp": first_bp,
                    "doc_title": "Doc A",
                })
                self.assertEqual(resp.get_json()["status"], "started")
                self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")

                set_current_doc(self.doc_b_id)
            finally:
                release.set()
                self._wait_for_worker_stop(timeout=3.0)

        entries_a, _, _ = load_entries_from_disk(self.doc_a_id)
        entries_b, _, _ = load_entries_from_disk(self.doc_b_id)

        self.assertGreater(len(entries_a), 0)
        self.assertEqual(entries_b, [])

    def test_worker_persists_entries_to_sqlite(self):
        started = threading.Event()
        release = threading.Event()
        first_bp, _ = get_page_range(self.doc_a_pages)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate(started, release)),
        ):
            set_current_doc(self.doc_a_id)
            resp = self._post("/start_translate_all", data={
                "doc_id": self.doc_a_id,
                "start_bp": first_bp,
                "doc_title": "Doc A",
            })
            self.assertEqual(resp.get_json()["status"], "started")
            self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")
            release.set()
            self._wait_for_worker_stop(timeout=3.0)

        doc_dir = Path(get_doc_dir(self.doc_a_id))
        entries, title, idx = load_entries_from_disk(self.doc_a_id)
        self.assertEqual(title, "Doc A")
        self.assertEqual(idx, max(0, len(entries) - 1))
        self.assertEqual(entries[0]["_pageBP"], first_bp)
        self.assertFalse((doc_dir / "entries.json").exists())

    def test_fetch_next_persists_single_page_without_rewriting_all_entries(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "翻译 1",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_a_id)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(app_module, "translate_page", return_value={
                "_pageBP": first_bp + 1,
                "_model": "sonnet",
                "_page_entries": [{
                    "original": "Page 2",
                    "translation": "翻译 2",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": str(first_bp + 1),
                }],
                "pages": str(first_bp + 1),
            }),
            patch.object(app_module, "save_entries_to_disk", side_effect=AssertionError("fetch_next 不应重写整份 entries")),
        ):
            resp = self._post("/fetch_next")

        self.assertEqual(resp.status_code, 302)
        entries, _, _ = load_entries_from_disk(self.doc_a_id)
        self.assertEqual([entry.get("_pageBP") for entry in entries[:2]], [first_bp, first_bp + 1])

    def test_fetch_next_uses_explicit_doc_id_instead_of_current_doc(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "翻译 1",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_b_id)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(app_module, "translate_page", return_value={
                "_pageBP": first_bp + 1,
                "_model": "sonnet",
                "_page_entries": [{
                    "original": "Page 2",
                    "translation": "翻译 2",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": str(first_bp + 1),
                }],
                "pages": str(first_bp + 1),
            }),
        ):
            resp = self._post("/fetch_next", data={"doc_id": self.doc_a_id})

        self.assertEqual(resp.status_code, 302)
        entries_a, _, _ = load_entries_from_disk(self.doc_a_id)
        entries_b, _, _ = load_entries_from_disk(self.doc_b_id)
        self.assertEqual([entry.get("_pageBP") for entry in entries_a[:2]], [first_bp, first_bp + 1])
        self.assertEqual(entries_b, [])

    def test_retranslate_persists_single_page_without_rewriting_all_entries(self):
        save_entries_to_disk([
            {
                "_pageBP": 1,
                "_model": "sonnet",
                "_page_entries": [{
                    "original": "Page 1",
                    "translation": "翻译 1",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "1",
                }],
                "pages": "1",
            },
            {
                "_pageBP": 2,
                "_model": "sonnet",
                "_page_entries": [{
                    "original": "Page 2",
                    "translation": "翻译 2",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "2",
                }],
                "pages": "2",
            },
        ], "Doc A", 1, self.doc_a_id)
        set_current_doc(self.doc_a_id)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(app_module, "translate_page", return_value={
                "_pageBP": 2,
                "_model": "qwen-plus",
                "_page_entries": [{
                    "original": "Page 2",
                    "translation": "新的翻译 2",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "2",
                }],
                "pages": "2",
            }),
            patch.object(app_module, "save_entries_to_disk", side_effect=AssertionError("retranslate 不应重写整份 entries")),
        ):
            resp = self._post("/retranslate/2", data={"target": "builtin:qwen-plus"})

        self.assertEqual(resp.status_code, 302)
        entries, _, _ = load_entries_from_disk(self.doc_a_id)
        self.assertEqual(entries[1]["_page_entries"][0]["translation"], "新的翻译 2")

    def test_retranslate_uses_explicit_doc_id_instead_of_current_doc(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "旧翻译",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_b_id)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(app_module, "translate_page", return_value={
                "_pageBP": first_bp,
                "_model": "qwen-plus",
                "_page_entries": [{
                    "original": "Page 1",
                    "translation": "新的翻译",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": str(first_bp),
                }],
                "pages": str(first_bp),
            }),
        ):
            resp = self._post(f"/retranslate/{first_bp}", data={"doc_id": self.doc_a_id, "target": "builtin:qwen-plus"})

        self.assertEqual(resp.status_code, 302)
        entries_a, _, _ = load_entries_from_disk(self.doc_a_id)
        entries_b, _, _ = load_entries_from_disk(self.doc_b_id)
        self.assertEqual(entries_a[0]["_page_entries"][0]["translation"], "新的翻译")
        self.assertEqual(entries_b, [])

    def test_pdf_file_uses_explicit_doc_id_instead_of_current_doc(self):
        doc_a_pdf = Path(get_doc_dir(self.doc_a_id)) / "source.pdf"
        doc_b_pdf = Path(get_doc_dir(self.doc_b_id)) / "source.pdf"
        doc_a_pdf.write_bytes(b"%PDF-1.4\n%doc-a\n")
        doc_b_pdf.write_bytes(b"%PDF-1.4\n%doc-b\n")
        set_current_doc(self.doc_b_id)

        resp = self.client.get("/pdf_file", query_string={"doc_id": self.doc_a_id})
        try:
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.mimetype, "application/pdf")
            self.assertEqual(resp.get_data(), b"%PDF-1.4\n%doc-a\n")
        finally:
            resp.close()

    def test_pdf_page_uses_explicit_doc_id_instead_of_current_doc(self):
        doc_a_pdf = str(Path(get_doc_dir(self.doc_a_id)) / "source.pdf")
        set_current_doc(self.doc_b_id)

        with patch.object(app_module, "render_pdf_page", return_value=b"png-bytes") as render_mock:
            resp = self.client.get("/pdf_page/0", query_string={"doc_id": self.doc_a_id, "scale": "1.25"})

        self.assertEqual(resp.status_code, 200)
        render_mock.assert_called_once_with(doc_a_pdf, 0, scale=1.25)

    def test_reparse_page_uses_explicit_doc_id_instead_of_current_doc(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        captured = {}

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                captured["target"] = target
                captured["args"] = args
                captured["daemon"] = daemon

            def start(self):
                return None

        with (
            patch.object(app_module, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(app_module.threading, "Thread", FakeThread),
        ):
            set_current_doc(self.doc_b_id)
            resp = self._post(f"/reparse_page/{first_bp}", data={"doc_id": self.doc_a_id})

        self.assertEqual(resp.status_code, 200)
        self.assertIn("task_id", resp.get_json())
        self.assertEqual(captured["args"][1], self.doc_a_id)
        self.assertEqual(captured["args"][2], first_bp)

    def test_reparse_uses_explicit_doc_id_instead_of_current_doc(self):
        captured = {}

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                captured["target"] = target
                captured["args"] = args
                captured["daemon"] = daemon

            def start(self):
                return None

        with (
            patch.object(app_module, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(app_module.threading, "Thread", FakeThread),
        ):
            set_current_doc(self.doc_b_id)
            resp = self._post("/reparse", data={"doc_id": self.doc_a_id})

        self.assertEqual(resp.status_code, 200)
        self.assertIn("task_id", resp.get_json())
        self.assertEqual(captured["args"][1], self.doc_a_id)

    def test_delete_doc_is_blocked_while_translation_is_running(self):
        started = threading.Event()
        release = threading.Event()
        first_bp, _ = get_page_range(self.doc_a_pages)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate(started, release)),
            patch.object(app_module, "delete_doc") as delete_mock,
        ):
            try:
                set_current_doc(self.doc_a_id)
                resp = self._post("/start_translate_all", data={
                    "doc_id": self.doc_a_id,
                    "start_bp": first_bp,
                    "doc_title": "Doc A",
                })
                self.assertEqual(resp.get_json()["status"], "started")
                self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")

                delete_resp = self._post(f"/delete_doc/{self.doc_a_id}", follow_redirects=True)
                html = delete_resp.get_data(as_text=True)

                self.assertEqual(delete_resp.status_code, 200)
                self.assertIn("该文档正在翻译中，请先停止翻译后再删除。", html)
                delete_mock.assert_not_called()
                self.assertTrue(Path(get_doc_dir(self.doc_a_id)).exists())
            finally:
                release.set()
                self._wait_for_worker_stop(timeout=3.0)

        entries_a, _, _ = load_entries_from_disk(self.doc_a_id)
        self.assertGreater(len(entries_a), 0)

    def test_translate_status_exposes_rich_progress_snapshot(self):
        started = threading.Event()
        release = threading.Event()
        first_bp, _ = get_page_range(self.doc_a_pages)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate(started, release)),
        ):
            try:
                set_current_doc(self.doc_a_id)
                resp = self._post("/start_translate_all", data={
                    "doc_id": self.doc_a_id,
                    "start_bp": first_bp,
                    "doc_title": "Doc A",
                })
                self.assertEqual(resp.get_json()["status"], "started")
                self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")

                status = self.client.get("/translate_status", query_string={"doc_id": self.doc_a_id}).get_json()
                self.assertEqual(status["phase"], "running")
                self.assertEqual(status["doc_id"], self.doc_a_id)
                self.assertGreaterEqual(status["total_pages"], 1)
                self.assertEqual(status["done_pages"], 0)
                self.assertEqual(status["prompt_tokens"], 0)
                self.assertEqual(status["completion_tokens"], 0)
            finally:
                release.set()
                self._wait_for_worker_stop(timeout=3.0)

    def test_translate_status_uses_full_document_page_total_when_starting_midway(self):
        started = threading.Event()
        release = threading.Event()
        all_pages = [pg["bookPage"] for pg in self.doc_a_pages]
        start_bp = all_pages[5]
        translated_entries = [{
            "_pageBP": bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": f"Page {bp}",
                "translation": f"翻译 {bp}",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(bp),
            }],
            "pages": str(bp),
        } for bp in all_pages[:5]]
        save_entries_to_disk(translated_entries, "Doc A", 4, self.doc_a_id)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate(started, release)),
        ):
            try:
                set_current_doc(self.doc_a_id)
                resp = self._post("/start_translate_all", data={
                    "doc_id": self.doc_a_id,
                    "start_bp": start_bp,
                    "doc_title": "Doc A",
                })
                self.assertEqual(resp.get_json()["status"], "started")
                self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")

                status = self.client.get("/translate_status", query_string={"doc_id": self.doc_a_id}).get_json()
                self.assertEqual(status["total_pages"], len(all_pages))
                self.assertEqual(status["done_pages"], 5)
                self.assertEqual(status["current_page_idx"], 6)
            finally:
                release.set()
                self._wait_for_worker_stop(timeout=3.0)

    def test_terminal_snapshot_persists_after_stop(self):
        started = threading.Event()
        release = threading.Event()
        first_bp, _ = get_page_range(self.doc_a_pages)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate(started, release)),
        ):
            set_current_doc(self.doc_a_id)
            resp = self._post("/start_translate_all", data={
                "doc_id": self.doc_a_id,
                "start_bp": first_bp,
                "doc_title": "Doc A",
            })
            self.assertEqual(resp.get_json()["status"], "started")
            self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")

            stop_resp = self._post("/stop_translate", data={"doc_id": self.doc_a_id})
            self.assertEqual(stop_resp.get_json()["status"], "stopping")

            release.set()
            self._wait_for_worker_stop(timeout=3.0)

        status = self.client.get("/translate_status", query_string={"doc_id": self.doc_a_id}).get_json()
        self.assertEqual(status["phase"], "stopped")
        self.assertEqual(status["doc_id"], self.doc_a_id)
        self.assertGreaterEqual(status["done_pages"], 1)
        self.assertFalse(status["running"])
        self.assertFalse(status["stop_requested"])

    def test_reading_page_embeds_bound_doc_id_for_translate_requests(self):
        set_current_doc(self.doc_a_id)
        resp = self.client.get("/reading?bp=1&auto=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"var currentDocId = '{self.doc_a_id}';", html)
        self.assertIn("currentBp: Number(1)", html)
        self.assertIn("goReadingPage", html)
        self.assertIn("translate_status", html)
        self.assertIn("start_translate_all", html)
        self.assertIn("stop_translate", html)
        self.assertIn("autoStart: '1'", html)

    def test_reading_uses_explicit_doc_id_for_nav_pdf_and_retranslate_links(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_b_id)

        resp = self.client.get(
            "/reading",
            query_string={
                "bp": first_bp,
                "doc_id": self.doc_a_id,
                "usage": "0",
                "orig": "0",
                "layout": "stack",
                "pdf": "0",
            },
        )
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"var currentDocId = '{self.doc_a_id}';", html)
        self.assertIn("翻译 A", html)
        self.assertIn(f'/reading?bp={first_bp}&amp;doc_id={self.doc_a_id}&amp;usage=0&amp;orig=0&amp;layout=stack&amp;pdf=0', html)
        self.assertIn(f'data-pdf-src="/pdf_page/0?doc_id={self.doc_a_id}"', html)
        self.assertIn("submitPostAction(retryUrl, {doc_id: retryDocId});", html)
        self.assertIn('action="/reset_text"', html)
        self.assertIn(f'name="doc_id" value="{self.doc_a_id}"', html)
        self.assertIn("reparseUrl += '?doc_id=' + encodeURIComponent(reparseDocId);", html)

    def test_home_page_preserves_current_doc_id_in_navigation_links(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_b_id)

        resp = self.client.get("/", query_string={"doc_id": self.doc_a_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(f'/input?doc_id={self.doc_a_id}', html)
        self.assertIn(f'/reading?doc_id={self.doc_a_id}', html)
        self.assertIn(f'/reading?bp={first_bp}&amp;auto=1&amp;start_bp={first_bp}&amp;doc_id={self.doc_a_id}', html)
        self.assertIn(f'/settings?doc_id={self.doc_a_id}', html)
        self.assertIn(f"reparseUrl += '?doc_id={self.doc_a_id}';", html)

    def test_home_page_renders_clear_translation_action_between_switch_and_delete(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        save_entries_to_disk([{
            "_pageBP": 101,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page B",
                "translation": "翻译 B",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "101",
            }],
            "pages": "101",
        }], "Doc B", 0, self.doc_b_id)
        set_current_doc(self.doc_a_id)

        resp = self.client.get("/", query_string={"doc_id": self.doc_a_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("OCR-JSON解析成功文档", html)
        switch_idx = html.index(f'action="/switch_doc/{self.doc_b_id}"')
        clear_idx = html.index('action="/reset_text"', switch_idx)
        delete_idx = html.index(f'action="/delete_doc/{self.doc_b_id}"', clear_idx)
        self.assertLess(switch_idx, clear_idx)
        self.assertLess(clear_idx, delete_idx)
        self.assertIn(f'name="doc_id" value="{self.doc_b_id}"', html)
        self.assertIn("当前阅读文档", html)
        self.assertIn("doc-current-banner", html)

    def test_home_page_marks_reading_entrances_for_temporary_disable(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_a_id)

        resp = self.client.get("/", query_string={"doc_id": self.doc_a_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-reading-entry="1"', html)
        self.assertIn('onclick="return guardReadingEntrance(event, this);"', html)
        self.assertIn("var readingEntrancesDisabled = false;", html)
        self.assertIn("setReadingEntrancesDisabled(true);", html)
        self.assertIn("setReadingEntrancesDisabled(false);", html)
        self.assertIn("if (readingEntrancesDisabled) {", html)
        self.assertIn("return false;", html)
        self.assertIn("el.innerHTML = '<span class=spinner></span> 加载中…';", html)
        self.assertIn("startUpload(file)", html)
        self.assertIn("startReparse()", html)
        self.assertIn("resetUploadArea()", html)

    def test_input_page_binds_current_doc_id_for_start_and_model_switch(self):
        set_current_doc(self.doc_b_id)

        resp = self.client.get("/input", query_string={"doc_id": self.doc_a_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(f'<input type="hidden" name="doc_id" value="{self.doc_a_id}">', html)
        self.assertIn('action="/set_model/deepseek-chat"', html)
        self.assertIn('name="next" value="input"', html)
        self.assertIn(f'name="doc_id" value="{self.doc_a_id}"', html)
        self.assertIn(f'/?doc_id={self.doc_a_id}', html)
        self.assertIn('id="paddleQuotaStatusCard"', html)
        self.assertIn("fetch('/paddle_quota_status')", html)
        self.assertIn("官方站内可查看 OCR 配额状态", html)

    def test_paddle_quota_status_route_returns_graceful_fallback(self):
        resp = self.client.get("/paddle_quota_status")
        data = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["supported"], False)
        self.assertEqual(data["status"], "unavailable")
        self.assertIn("官方站内可查看", data["message"])
        self.assertIn("429", data["message"])
        self.assertIn("aistudio.baidu.com/paddleocr", data["official_url"])

    def test_settings_page_exposes_official_quota_query_link(self):
        resp = self.client.get("/settings", query_string={"doc_id": self.doc_a_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("https://aistudio.baidu.com/paddleocr", html)
        self.assertIn("自己查询今日解析页数", html)
        self.assertNotIn("每日可解析 3000 页", html)

    def test_settings_page_hides_custom_model_panel_until_expanded(self):
        resp = self.client.get("/settings", query_string={"doc_id": self.doc_a_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="customModelPanel"', html)
        self.assertIn("toggleCustomModelPanel", html)
        self.assertIn("custom-model-panel", html)
        self.assertIn("hidden", html)

    def test_settings_page_expands_custom_model_panel_when_requested(self):
        resp = self.client.get("/settings", query_string={"doc_id": self.doc_a_id, "open_custom_model": "1"})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('name="provider_type"', html)
        self.assertIn('name="model_id"', html)
        self.assertIn('name="section" value="custom_model_save"', html)
        self.assertIn("保存自定义模型配置", html)

    def test_model_switch_uis_all_expose_custom_model_button(self):
        config.save_config({
            "active_model_mode": "custom",
            "active_builtin_model_key": "qwen-plus",
            "custom_model": {
                "enabled": True,
                "display_name": "Qwen 3.5 Plus",
                "provider_type": "qwen",
                "model_id": "qwen3.5-plus",
                "base_url": "",
                "qwen_region": "cn",
                "api_key_mode": "builtin_dashscope",
                "custom_api_key": "",
                "extra_body": {"enable_thinking": False},
            },
        })
        set_current_doc(self.doc_a_id)
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "qwen3.5-plus",
            "_model_source": "custom",
            "_model_key": "",
            "_model_id": "qwen3.5-plus",
            "_provider": "qwen",
            "_display_label": "Qwen 3.5 Plus",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)

        home_html = self.client.get("/", query_string={"doc_id": self.doc_a_id}).get_data(as_text=True)
        input_html = self.client.get("/input", query_string={"doc_id": self.doc_a_id}).get_data(as_text=True)
        reading_html = self.client.get("/reading", query_string={"bp": first_bp, "doc_id": self.doc_a_id}).get_data(as_text=True)
        settings_html = self.client.get("/settings", query_string={"doc_id": self.doc_a_id}).get_data(as_text=True)

        self.assertIn("自定义: Qwen 3.5 Plus", home_html)
        self.assertIn("自定义: Qwen 3.5 Plus", input_html)
        self.assertIn("自定义模型", reading_html)
        self.assertIn("重译本页", reading_html)
        self.assertIn("自定义: Qwen 3.5 Plus", settings_html)
        self.assertIn('action="/set_model/deepseek-chat"', home_html)
        self.assertIn('action="/set_model/deepseek-chat"', input_html)
        self.assertIn('action="/set_model/deepseek-chat"', reading_html)
        self.assertIn('action="/set_model/deepseek-chat"', settings_html)
        self.assertIn('/settings?doc_id=' + self.doc_a_id + '&amp;open_custom_model=1#customModelPanel', home_html)
        self.assertIn('/settings?doc_id=' + self.doc_a_id + '&amp;open_custom_model=1#customModelPanel', input_html)
        self.assertIn('/settings?doc_id=' + self.doc_a_id + '&amp;open_custom_model=1#customModelPanel', reading_html)
        self.assertNotIn('class="btn active">DeepSeek-Chat</a>', home_html)
        self.assertNotIn('class="btn active">DeepSeek-Chat</a>', input_html)
        self.assertNotIn('class="toolbar-dropdown-item active">DeepSeek-Chat</a>', reading_html)
        self.assertNotIn('class="btn active">DeepSeek-Chat</a>', settings_html)

    def test_switching_to_preset_model_disables_custom_mode_but_keeps_saved_name(self):
        config.save_config({
            "active_model_mode": "custom",
            "active_builtin_model_key": "qwen-plus",
            "custom_model": {
                "enabled": True,
                "display_name": "Qwen 3.5 Plus",
                "provider_type": "qwen",
                "model_id": "qwen3.5-plus",
                "base_url": "",
                "qwen_region": "cn",
                "api_key_mode": "builtin_dashscope",
                "custom_api_key": "",
                "extra_body": {"enable_thinking": False},
            },
        })
        set_current_doc(self.doc_a_id)

        resp = self._post("/set_model/qwen-max", data={"next": "settings", "doc_id": self.doc_a_id})
        self.assertEqual(resp.status_code, 302)

        settings_html = self.client.get("/settings", query_string={"doc_id": self.doc_a_id}).get_data(as_text=True)
        saved = config.load_config()
        self.assertEqual(saved.get("active_model_mode"), "builtin")
        self.assertEqual(saved.get("custom_model", {}).get("model_id"), "qwen3.5-plus")
        self.assertIn('action="/set_model/qwen-max"', settings_html)
        self.assertIn('自定义: Qwen 3.5 Plus', settings_html)

        t_args = app_module.get_translate_args()
        self.assertEqual(t_args["model_id"], "qwen-max")

    def test_form_route_rejects_missing_csrf_token(self):
        config.set_model_key("deepseek-chat")

        resp = self.client.post("/set_model/qwen-max", data={
            "next": "settings",
            "doc_id": self.doc_a_id,
        })

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(config.get_model_key(), "deepseek-chat")

    def test_retranslate_rejects_invalid_target_instead_of_silent_fallback(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "qwen-max",
            "_model_source": "builtin",
            "_model_key": "qwen-max",
            "_model_id": "qwen-max",
            "_provider": "qwen",
            "_display_label": "Qwen-Max",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)

        resp = self._post(f"/retranslate/{first_bp}", data={
            "doc_id": self.doc_a_id,
            "target": "builtin:not-exists",
        }, follow_redirects=True)
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("重译目标无效", html)

    def test_reading_model_switch_preserves_current_reading_context(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        html = self.client.get("/reading", query_string={
            "bp": first_bp,
            "doc_id": self.doc_a_id,
            "orig": 1,
            "layout": "side",
            "pdf": 1,
            "usage": 1,
        }).get_data(as_text=True)

        self.assertIn(f'name="bp" value="{first_bp}"', html)
        self.assertIn('name="usage" value="1"', html)
        self.assertIn('name="orig" value="1"', html)
        self.assertIn('name="layout" value="side"', html)
        self.assertIn('name="pdf" value="1"', html)

        resp = self._post("/set_model/qwen-max", data={
            "next": "reading",
            "doc_id": self.doc_a_id,
            "bp": first_bp,
            "usage": "1",
            "orig": "1",
            "layout": "side",
            "pdf": "1",
        })

        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"/reading?doc_id={self.doc_a_id}", resp.location)
        self.assertIn(f"bp={first_bp}", resp.location)
        self.assertIn("usage=1", resp.location)
        self.assertIn("orig=1", resp.location)
        self.assertIn("layout=side", resp.location)
        self.assertIn("pdf=1", resp.location)

    def test_reading_page_does_not_expose_removed_focus_mode(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        html = self.client.get("/reading", query_string={
            "bp": first_bp,
            "doc_id": self.doc_a_id,
            "orig": 1,
            "layout": "side",
            "pdf": 1,
            "usage": 1,
            "focus": 1,
        }).get_data(as_text=True)

        self.assertNotIn('id="focusBtn"', html)
        self.assertNotIn('id="distractionFreeExitBtn"', html)
        self.assertNotIn("toggleDistractionFree(", html)
        self.assertNotIn("distraction-free", html)
        self.assertNotIn('name="focus"', html)
        self.assertNotIn("focus=1", html)
        self.assertIn('name="usage" value="1"', html)
        self.assertIn('name="orig" value="1"', html)
        self.assertIn('name="layout" value="side"', html)
        self.assertIn('name="pdf" value="1"', html)
        self.assertIn('class="reading-main-layout with-pdf"', html)

    def test_save_settings_accepts_valid_custom_model_config_without_auto_activate(self):
        config.save_config({
            "active_model_mode": "builtin",
            "active_builtin_model_key": "qwen-max",
        })
        resp = self._post("/save_settings", data={
            "section": "custom_model_save",
            "display_name": "Qwen 3.5 Plus",
            "provider_type": "qwen",
            "model_id": "qwen3.5-plus",
            "qwen_region": "sg",
        }, follow_redirects=True)
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("已保存自定义模型配置", html)
        saved = config.load_config()
        self.assertEqual(saved.get("active_model_mode"), "builtin")
        self.assertEqual(saved.get("custom_model", {}).get("display_name"), "Qwen 3.5 Plus")
        self.assertEqual(saved.get("custom_model", {}).get("model_id"), "qwen3.5-plus")
        self.assertEqual(saved.get("custom_model", {}).get("qwen_region"), "sg")
        self.assertIn('name="model_id"', html)
        self.assertIn('value="qwen3.5-plus"', html)
        self.assertIn("启用此自定义模型", html)

    def test_activate_saved_custom_model_switches_to_custom_mode(self):
        config.save_config({
            "active_model_mode": "builtin",
            "active_builtin_model_key": "deepseek-chat",
            "deepseek_key": "deepseek-test-key",
            "dashscope_key": "dashscope-test-key",
            "custom_model": {
                "enabled": True,
                "display_name": "Qwen 3.5 Plus",
                "provider_type": "qwen",
                "model_id": "qwen3.5-plus",
                "base_url": "",
                "qwen_region": "cn",
                "api_key_mode": "builtin_dashscope",
                "custom_api_key": "",
                "extra_body": {"enable_thinking": False},
            },
        })

        resp = self._post("/save_settings", data={
            "section": "custom_model_enable",
        }, follow_redirects=True)
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        saved = config.load_config()
        self.assertEqual(saved.get("active_model_mode"), "custom")
        t_args = app_module.get_translate_args()
        self.assertEqual(t_args["provider"], "qwen")
        self.assertEqual(t_args["model_id"], "qwen3.5-plus")
        self.assertEqual(t_args["api_key"], "dashscope-test-key")
        self.assertIn("已启用自定义模型", html)

    def test_save_settings_rejects_openai_compatible_config_without_base_url(self):
        config.save_config({
            "active_model_mode": "builtin",
            "active_builtin_model_key": "qwen-plus",
            "custom_model": {
                "enabled": True,
                "display_name": "Old Name",
                "provider_type": "qwen",
                "model_id": "qwen-plus",
                "base_url": "",
                "qwen_region": "cn",
                "api_key_mode": "builtin_dashscope",
                "custom_api_key": "",
                "extra_body": {"enable_thinking": False},
            },
        })
        resp = self._post("/save_settings", data={
            "section": "custom_model_save",
            "display_name": "My OpenAI Compat",
            "provider_type": "openai_compatible",
            "model_id": "gpt-compat-1",
            "base_url": "",
            "custom_api_key": "sk-test",
        }, follow_redirects=True)
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("OpenAI 兼容模型必须填写 Base URL", html)
        self.assertEqual(config.load_config()["custom_model"]["display_name"], "Old Name")

    def test_reading_retranslate_button_uses_builtin_copy_when_custom_is_saved_but_inactive(self):
        config.save_config({
            "active_model_mode": "builtin",
            "active_builtin_model_key": "qwen-max",
            "custom_model": {
                "enabled": True,
                "display_name": "Qwen 3.5 Plus",
                "provider_type": "qwen",
                "model_id": "qwen3.5-plus",
                "base_url": "",
                "qwen_region": "cn",
                "api_key_mode": "builtin_dashscope",
                "custom_api_key": "",
                "extra_body": {"enable_thinking": False},
            },
        })
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "qwen-max",
            "_model_source": "builtin",
            "_model_key": "qwen-max",
            "_model_id": "qwen-max",
            "_provider": "qwen",
            "_display_label": "Qwen-Max",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)

        html = self.client.get("/reading", query_string={"bp": first_bp, "doc_id": self.doc_a_id}).get_data(as_text=True)

        self.assertIn("用Qwen-Max重译本页", html)
        self.assertNotIn("用自定义模型（Qwen 3.5 Plus）重译本页", html)

    def test_mutating_get_routes_are_rejected(self):
        routes = [
            ("/set_model/qwen-max", {"doc_id": self.doc_a_id, "next": "settings"}),
            ("/switch_doc/" + self.doc_b_id, {}),
            ("/delete_doc/" + self.doc_b_id, {}),
            ("/start_from_beginning", {"doc_id": self.doc_a_id}),
            ("/fetch_next", {"doc_id": self.doc_a_id}),
            ("/retranslate/1", {"doc_id": self.doc_a_id, "target": "builtin:deepseek-chat"}),
            ("/stop_translate", {"doc_id": self.doc_a_id}),
            ("/reset_text", {"doc_id": self.doc_a_id}),
            ("/reset_text_action", {"doc_id": self.doc_a_id}),
            ("/reset_all", {"doc_id": self.doc_a_id}),
        ]

        for path, query in routes:
            with self.subTest(path=path):
                resp = self.client.get(path, query_string=query)
                self.assertEqual(resp.status_code, 405)

    def test_settings_page_defaults_parallel_translation_to_disabled(self):
        resp = self.client.get("/settings", query_string={"doc_id": self.doc_a_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('name="translate_parallel_enabled"', html)
        self.assertIn('name="translate_parallel_limit"', html)
        self.assertIn('value="10"', html)
        self.assertIn("开启段内并发翻译", html)
        self.assertNotIn('name="translate_parallel_enabled" checked', html)

    def test_save_settings_persists_parallel_translation_preferences(self):
        resp = self._post("/save_settings", data={
            "section": "translate_parallel",
            "translate_parallel_enabled": "on",
            "translate_parallel_limit": "9",
        }, follow_redirects=True)
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("已开启段内并发翻译", html)
        self.assertIn('name="translate_parallel_enabled" value="on" checked', html)
        self.assertIn('name="translate_parallel_limit"', html)
        self.assertIn('value="9"', html)

    def test_save_settings_coerces_invalid_parallel_limit_back_to_ten(self):
        resp = self._post("/save_settings", data={
            "section": "translate_parallel",
            "translate_parallel_enabled": "on",
            "translate_parallel_limit": "99",
        }, follow_redirects=True)
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('name="translate_parallel_enabled" value="on" checked', html)
        self.assertIn('value="10"', html)

    def test_save_parallel_settings_while_translation_running_persists_and_warns_next_page(self):
        started = threading.Event()
        release = threading.Event()
        first_bp, _ = get_page_range(self.doc_a_pages)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate(started, release)),
        ):
            try:
                set_current_doc(self.doc_a_id)
                start_resp = self._post("/start_translate_all", data={
                    "doc_id": self.doc_a_id,
                    "start_bp": first_bp,
                    "doc_title": "Doc A",
                })
                self.assertEqual(start_resp.get_json()["status"], "started")
                self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")

                resp = self._post("/save_settings", data={
                    "section": "translate_parallel",
                    "translate_parallel_enabled": "on",
                    "translate_parallel_limit": "8",
                }, follow_redirects=True)
                html = resp.get_data(as_text=True)

                self.assertEqual(resp.status_code, 200)
                self.assertIn("已开启段内并发翻译", html)
                self.assertIn("新的并发设置会从下一页开始生效", html)
                self.assertIn('name="translate_parallel_enabled" value="on" checked', html)
                self.assertIn('value="8"', html)
                self.assertTrue(config.get_translate_parallel_enabled())
                self.assertEqual(config.get_translate_parallel_limit(), 8)
            finally:
                release.set()
                self._wait_for_worker_stop(timeout=3.0)

    def test_existing_config_file_wont_be_overwritten_by_legacy_migration(self):
        original_old_config_dir = config.OLD_CONFIG_DIR
        original_config_dir = config.CONFIG_DIR
        original_config_file = config.CONFIG_FILE
        original_data_dir = config.DATA_DIR
        original_docs_dir = config.DOCS_DIR
        original_current_file = config.CURRENT_FILE

        legacy_root = tempfile.mkdtemp(prefix="legacy-config-", dir="/tmp")
        new_root = tempfile.mkdtemp(prefix="new-config-", dir="/tmp")
        try:
            legacy_cfg = {"translate_parallel_enabled": False, "translate_parallel_limit": 2}
            os.makedirs(legacy_root, exist_ok=True)
            with open(os.path.join(legacy_root, "config.json"), "w", encoding="utf-8") as f:
                json.dump(legacy_cfg, f, ensure_ascii=False)

            config.CONFIG_DIR = new_root
            config.CONFIG_FILE = os.path.join(new_root, "config.json")
            config.DATA_DIR = os.path.join(new_root, "data")
            config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
            config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")
            config.OLD_CONFIG_DIR = legacy_root

            # 第一次会触发旧配置迁移
            enabled, limit = config.set_translate_parallel_settings(True, "9")
            self.assertTrue(enabled)
            self.assertEqual(limit, 9)

            # 第二次读取不应再次被旧配置覆盖
            loaded = config.load_config()
            self.assertTrue(bool(loaded.get("translate_parallel_enabled")))
            self.assertEqual(int(loaded.get("translate_parallel_limit")), 9)
        finally:
            config.OLD_CONFIG_DIR = original_old_config_dir
            config.CONFIG_DIR = original_config_dir
            config.CONFIG_FILE = original_config_file
            config.DATA_DIR = original_data_dir
            config.DOCS_DIR = original_docs_dir
            config.CURRENT_FILE = original_current_file
            shutil.rmtree(legacy_root, ignore_errors=True)
            shutil.rmtree(new_root, ignore_errors=True)

    def test_start_reading_uses_form_doc_id_when_redirecting_to_reading(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        set_current_doc(self.doc_b_id)

        with patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}):
            resp = self._post("/start_reading", data={
                "doc_id": self.doc_a_id,
                "start_page": first_bp,
                "doc_title": "Doc A",
            })

        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"/reading?bp={first_bp}&auto=1&start_bp={first_bp}&doc_id={self.doc_a_id}", resp.location)

    def test_start_from_beginning_keeps_existing_translations(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_b_id)

        with patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}):
            resp = self._post("/start_from_beginning", data={"doc_id": self.doc_a_id})

        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"/reading?bp={first_bp}&auto=1&start_bp={first_bp}&doc_id={self.doc_a_id}", resp.location)
        entries_a, _, _ = load_entries_from_disk(self.doc_a_id)
        self.assertEqual(entries_a[0]["_page_entries"][0]["translation"], "翻译 A")

    def test_start_from_beginning_missing_deepseek_key_uses_correct_provider_name(self):
        config.set_model_key("deepseek-chat")
        config.set_deepseek_key("")

        resp = self._post("/start_from_beginning", data={"doc_id": self.doc_a_id}, follow_redirects=True)
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("DeepSeek API Key", html)
        self.assertNotIn("Anthropic API Key", html)

    def test_reading_export_links_bind_current_doc_id(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_a_id)

        resp = self.client.get(f"/reading?bp={first_bp}&doc_id={self.doc_a_id}&layout=stack&pdf=0&usage=0&orig=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(f'href="/download_md?doc_id={self.doc_a_id}"', html)
        self.assertIn("fetch('/export_md?doc_id=' + encodeURIComponent(currentDocId))", html)

    def test_reading_page_shows_page_footnote_preview_from_real_page_data(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        page_footnotes = "1. 脚注原文甲\n2. 脚注原文乙"
        save_pages_to_disk([
            {
                "bookPage": first_bp,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文甲",
                "footnotes": page_footnotes,
            },
            {
                "bookPage": first_bp + 1,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文乙",
                "footnotes": "",
            },
        ], "Doc A", self.doc_a_id)
        set_current_doc(self.doc_a_id)

        resp = self.client.get(f"/reading?bp={first_bp}&doc_id={self.doc_a_id}&layout=stack&pdf=0&usage=0&orig=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("本页脚注预览", html)
        self.assertIn("page-preview-footnotes", html)
        self.assertIn(page_footnotes, html)
        self.assertIn("page-placeholder", html)
        self.assertIn("本页含脚注", html)

    def test_reading_page_splits_ocr_preview_into_multiple_paragraphs(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        preview_text = (
            "First paragraph opens the page with enough text to read naturally.\n\n"
            "Second paragraph continues the argument with a separate idea.\n"
            "Third paragraph should stay distinct instead of being merged into one block."
        )
        save_pages_to_disk([{
            "bookPage": first_bp,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": preview_text,
            "footnotes": "",
        }], "Doc A", self.doc_a_id)
        set_current_doc(self.doc_a_id)

        resp = self.client.get(f"/reading?bp={first_bp}&doc_id={self.doc_a_id}&layout=stack&pdf=0&usage=0&orig=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('class="page-preview-text preview-paragraphs"', html)
        self.assertGreaterEqual(html.count('class="page-preview-paragraph'), 2)
        self.assertIn("First paragraph opens the page with enough text to read naturally.", html)
        self.assertIn("Second paragraph continues the argument with a separate idea.", html)
        self.assertIn("Third paragraph should stay distinct instead of being merged into one block.", html)

    def test_reading_page_renders_page_level_footnotes_from_entry_data(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        page_footnotes = "1. 脚注原文甲\n2. 脚注原文乙"
        page_footnotes_translation = "1. 脚注译文甲\n2. 脚注译文乙"
        save_pages_to_disk([
            {
                "bookPage": first_bp,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文甲",
                "footnotes": page_footnotes,
            },
            {
                "bookPage": first_bp + 1,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文乙",
                "footnotes": "",
            },
        ], "Doc A", self.doc_a_id)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "正文原文甲",
                "translation": "正文译文甲",
                "footnotes": page_footnotes,
                "footnotes_translation": page_footnotes_translation,
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_a_id)

        resp = self.client.get(f"/reading?bp={first_bp}&doc_id={self.doc_a_id}&layout=stack&pdf=0&usage=0&orig=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("本页脚注", html)
        self.assertIn("脚注原文", html)
        self.assertIn("脚注翻译", html)
        self.assertIn(page_footnotes, html)
        self.assertIn(page_footnotes_translation, html)
        self.assertLess(html.index("正文译文甲"), html.index("本页脚注"))
        self.assertIn("读完脚注后可直接继续", html)

    def test_reading_page_defaults_to_orig_zero_and_keeps_original_footnotes_visible(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        page_footnotes = "1. 脚注原文甲\n2. 脚注原文乙"
        save_pages_to_disk([{
            "bookPage": first_bp,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "正文原文甲",
            "footnotes": page_footnotes,
        }], "Doc A", self.doc_a_id)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "正文原文甲",
                "translation": "正文译文甲",
                "footnotes": page_footnotes,
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_a_id)

        resp = self.client.get(f"/reading?bp={first_bp}&doc_id={self.doc_a_id}&layout=stack&pdf=0&usage=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("本页脚注", html)
        self.assertIn("脚注原文", html)
        self.assertIn(page_footnotes, html)
        self.assertNotIn("脚注翻译", html)
        self.assertNotIn("本页脚注预览", html)
        self.assertNotIn("你正在查看 p.", html)
        self.assertNotIn("OCR 原文已就绪", html)

    def test_reading_page_keeps_original_footnotes_visible_with_pdf_panel_open(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        page_footnotes = "1. 脚注原文甲\n2. 脚注原文乙"
        save_pages_to_disk([{
            "bookPage": first_bp,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "正文原文甲",
            "footnotes": page_footnotes,
        }], "Doc A", self.doc_a_id)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "正文原文甲",
                "translation": "正文译文甲",
                "footnotes": page_footnotes,
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_a_id)

        resp = self.client.get(f"/reading?bp={first_bp}&doc_id={self.doc_a_id}&layout=side&pdf=1&usage=0&orig=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('class="reading-main-layout with-pdf"', html)
        self.assertIn('class="pdf-panel" id="pdfPanel"', html)
        self.assertIn('PDF 原文', html)
        self.assertIn(f'data-pdf-src="/pdf_page/0?doc_id={self.doc_a_id}"', html)
        self.assertIn("本页脚注", html)
        self.assertIn("脚注原文", html)
        self.assertIn(page_footnotes, html)
        self.assertNotIn("脚注翻译", html)
        self.assertNotIn("本页脚注预览", html)
        self.assertNotIn("你正在查看 p.", html)

    def test_reading_page_exposes_pdf_zoom_controls(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "正文原文甲",
                "translation": "正文译文甲",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_a_id)

        resp = self.client.get(f"/reading?bp={first_bp}&doc_id={self.doc_a_id}&layout=stack&pdf=1&usage=0&orig=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("pdfZoomOutBtn", html)
        self.assertIn("pdfZoomInfo", html)
        self.assertIn("pdfZoomInBtn", html)
        self.assertIn("pdfZoomResetBtn", html)
        self.assertIn("pdfPanelModeBtn", html)
        self.assertIn("var targetWidth = getPdfItemWidth(container, pageImgW, pageImgH);", html)
        self.assertIn("el.style.width = targetWidth + 'px';", html)
        self.assertIn("el.style.minWidth = targetWidth + 'px';", html)
        self.assertIn("overflow-x: auto;", html)
        self.assertIn("dispatch('cycle_pdf_panel_mode');", html)
        self.assertIn("panel.setAttribute('data-panel-mode', store.ui.pdfPanelMode);", html)
        self.assertIn("container.addEventListener('dblclick', function(event) {", html)
        self.assertIn("togglePdfZoomFromGesture(pageItem, anchor);", html)
        self.assertIn("container.addEventListener('wheel', function(event) {", html)
        self.assertIn("if (!event.ctrlKey && !event.metaKey) return;", html)
        self.assertIn("stepPdfZoom(delta, anchor);", html)
        self.assertIn("var anchor = buildPdfZoomAnchor(container, event);", html)
        self.assertIn("restorePdfZoomAnchor(container, anchor);", html)
        self.assertIn("container.scrollLeft = Math.max(0, targetLeft);", html)
        self.assertIn("container.scrollTop = Math.max(0, targetTop);", html)

    def test_reading_route_supports_physical_page_without_translated_entry(self):
        set_current_doc(self.doc_a_id)
        resp = self.client.get("/reading?bp=5&auto=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("p.5 可直接开始阅读", html)
        self.assertIn("currentBp: Number(5)", html)
        self.assertIn("pageNavBtn", html)
        self.assertIn("pageNavList", html)
        self.assertNotIn("navSelect", html)

    def test_reset_text_uses_explicit_doc_id_instead_of_current_doc(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        save_entries_to_disk([{
            "_pageBP": 101,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page B",
                "translation": "翻译 B",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "101",
            }],
            "pages": "101",
        }], "Doc B", 0, self.doc_b_id)
        set_current_doc(self.doc_b_id)

        resp = self._post("/reset_text", data={"doc_id": self.doc_a_id})

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/input", resp.location)
        entries_a, _, _ = load_entries_from_disk(self.doc_a_id)
        entries_b, _, _ = load_entries_from_disk(self.doc_b_id)
        self.assertEqual(entries_a, [])
        self.assertEqual(entries_b[0]["_page_entries"][0]["translation"], "翻译 B")

    def test_reset_text_action_uses_explicit_doc_id_instead_of_current_doc(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_b_id)

        resp = self._post("/reset_text_action", data={"doc_id": self.doc_a_id})

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/settings", resp.location)
        entries_a, _, _ = load_entries_from_disk(self.doc_a_id)
        self.assertEqual(entries_a, [])

    def test_reset_all_uses_explicit_doc_id_and_blocks_while_translation_running(self):
        started = threading.Event()
        release = threading.Event()
        first_bp, _ = get_page_range(self.doc_a_pages)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate(started, release)),
        ):
            try:
                set_current_doc(self.doc_b_id)
                resp = self._post("/start_translate_all", data={
                    "doc_id": self.doc_a_id,
                    "start_bp": first_bp,
                    "doc_title": "Doc A",
                })
                self.assertEqual(resp.get_json()["status"], "started")
                self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")

                delete_resp = self._post("/reset_all", data={"doc_id": self.doc_a_id}, follow_redirects=True)
                html = delete_resp.get_data(as_text=True)
                self.assertIn("该文档正在翻译中，请先停止翻译后再删除。", html)
                self.assertTrue(Path(get_doc_dir(self.doc_a_id)).exists())
                self.assertTrue(Path(get_doc_dir(self.doc_b_id)).exists())
            finally:
                release.set()
                self._wait_for_worker_stop(timeout=3.0)

    def test_reset_all_stale_settings_tab_uses_page_doc_id_not_current_doc(self):
        resp = self.client.get("/settings", query_string={"doc_id": self.doc_a_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('action="/reset_all"', html)
        self.assertIn(f'name="doc_id" value="{self.doc_a_id}"', html)

        set_current_doc(self.doc_b_id)
        delete_resp = self._post("/reset_all", data={"doc_id": self.doc_a_id}, follow_redirects=True)

        self.assertEqual(delete_resp.status_code, 200)
        self.assertFalse(Path(get_doc_dir(self.doc_a_id)).exists())
        self.assertTrue(Path(get_doc_dir(self.doc_b_id)).exists())

    def test_reset_all_reports_failure_when_delete_does_not_remove_directory(self):
        first_bp, _ = get_page_range(self.doc_a_pages)
        save_entries_to_disk([{
            "_pageBP": first_bp,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page A",
                "translation": "翻译 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": str(first_bp),
            }],
            "pages": str(first_bp),
        }], "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_b_id)

        with patch.object(app_module, "delete_doc", side_effect=lambda doc_id: None):
            resp = self._post("/reset_all", data={"doc_id": self.doc_a_id}, follow_redirects=True)

        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("删除失败，请稍后重试", html)
        self.assertTrue(Path(get_doc_dir(self.doc_a_id)).exists())
        self.assertTrue(Path(get_doc_dir(self.doc_b_id)).exists())

    def test_settings_page_renders_reset_link_with_current_doc_id(self):
        save_entries_to_disk([{
            "_pageBP": 101,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page B",
                "translation": "翻译 B",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "101",
            }],
            "pages": "101",
        }], "Doc B", 0, self.doc_b_id)
        set_current_doc(self.doc_a_id)

        resp = self.client.get("/settings", query_string={"doc_id": self.doc_b_id})
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('action="/reset_text_action"', html)
        self.assertIn('action="/reset_all"', html)
        self.assertIn(f'name="doc_id" value="{self.doc_b_id}"', html)

    def test_extract_pdf_text_returns_empty_when_pdf_reader_raises(self):
        with patch.object(pdf_extract, "PdfReader", side_effect=RuntimeError("broken pdf")):
            pages = pdf_extract.extract_pdf_text(b"broken-pdf")

        self.assertEqual(pages, [])

    def test_extract_pdf_text_falls_back_to_ocr_when_page_extract_raises(self):
        class FakePage:
            def __init__(self, text: str, raise_on_extract: bool = False):
                self._text = text
                self._raise_on_extract = raise_on_extract
                self.mediabox = SimpleNamespace(width=100.0, height=200.0)

            def extract_text(self, visitor_text=None):
                if self._raise_on_extract:
                    raise RuntimeError("extract failed")
                if visitor_text is not None:
                    visitor_text(self._text, None, [0, 0, 0, 0, 10, 20], None, 12)
                return self._text

        class FakeReader:
            def __init__(self, pages):
                self.pages = pages

        pages = [
            FakePage("This is a readable page with normal words and punctuation."),
            FakePage("This page should fall back to OCR.", raise_on_extract=True),
        ]

        with patch.object(pdf_extract, "PdfReader", return_value=FakeReader(pages)):
            pdf_pages = pdf_extract.extract_pdf_text(b"mixed-pdf")

        self.assertEqual(len(pdf_pages), 2)
        self.assertTrue(pdf_pages[0]["items"])
        self.assertTrue(pdf_pages[0]["fullText"])
        self.assertEqual(pdf_pages[1]["items"], [])
        self.assertEqual(pdf_pages[1]["fullText"], "")

    def test_extract_pdf_text_falls_back_for_unreadable_later_page(self):
        class FakePage:
            def __init__(self, text: str):
                self._text = text
                self.mediabox = SimpleNamespace(width=100.0, height=200.0)

            def extract_text(self, visitor_text=None):
                if visitor_text is not None:
                    visitor_text(self._text, None, [0, 0, 0, 0, 10, 20], None, 12)
                return self._text

        class FakeReader:
            def __init__(self, pages):
                self.pages = pages

        mixed_pages = [
            FakePage("This is a readable page with normal words and punctuation."),
            FakePage("Another readable page with enough words to pass the check."),
            FakePage("\uf8ff\uf0aa\uf0ab\uf0ac\u0001\u0002\u0003"),
        ]

        with patch.object(pdf_extract, "PdfReader", return_value=FakeReader(mixed_pages)):
            pdf_pages = pdf_extract.extract_pdf_text(b"mixed-pdf")

        self.assertEqual(len(pdf_pages), 3)
        self.assertTrue(pdf_pages[0]["items"])
        self.assertTrue(pdf_pages[1]["items"])
        self.assertEqual(pdf_pages[2]["items"], [])
        self.assertEqual(pdf_pages[2]["fullText"], "")

    def test_reading_route_embeds_failed_pages_and_persisted_draft(self):
        set_current_doc(self.doc_a_id)
        tasks._save_translate_state(
            self.doc_a_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            failed_bps=[5],
            failed_pages=[{"bp": 5, "error": "boom on 5", "updated_at": time.time()}],
            draft={
                "active": False,
                "bp": 5,
                "para_idx": 1,
                "para_total": 3,
                "para_done": 1,
                "paragraphs": ["第一段", "第二段草稿", ""],
                "status": "error",
                "note": "p.5 翻译失败，等待重试。",
                "last_error": "boom on 5",
                "updated_at": time.time(),
            },
        )

        resp = self.client.get("/reading?bp=5&auto=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("p.5 需要重试", html)
        self.assertIn("失败页", html)
        self.assertIn("最近一次失败原因：boom on 5", html)
        self.assertIn("failedBps: [5].map(function(bp) { return Number(bp); })", html)
        self.assertIn('"status": "error"', html)
        self.assertIn("usageDraftMini", html)
        self.assertIn("失败1页", html)

    def test_reading_route_does_not_rewrite_entries_file(self):
        sample_entries = [{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Sample",
                "translation": "示例",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
            }],
            "pages": "1",
        }]
        save_entries_to_disk(sample_entries, "Doc A", 0, self.doc_a_id)
        set_current_doc(self.doc_a_id)

        with patch.object(app_module, "save_entries_to_disk", side_effect=AssertionError("reading route should not rewrite entries")):
            resp = self.client.get("/reading?bp=1")

        self.assertEqual(resp.status_code, 200)

    def test_translate_snapshot_accumulates_usage(self):
        started = threading.Event()
        release = threading.Event()
        _, last_bp = get_page_range(self.doc_a_pages)
        usage = {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
            "request_count": 1,
        }

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate_with_usage(started, release, usage)),
        ):
            set_current_doc(self.doc_a_id)
            resp = self._post("/start_translate_all", data={
                "doc_id": self.doc_a_id,
                "start_bp": last_bp,
                "doc_title": "Doc A",
            })
            self.assertEqual(resp.get_json()["status"], "started")
            self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入翻译逻辑")
            release.set()
            self._wait_for_worker_stop(timeout=3.0)

        status = self.client.get("/translate_status", query_string={"doc_id": self.doc_a_id}).get_json()
        self.assertEqual(status["phase"], "done")
        self.assertEqual(status["prompt_tokens"], 11)
        self.assertEqual(status["completion_tokens"], 7)
        self.assertEqual(status["total_tokens"], 18)
        self.assertEqual(status["request_count"], 1)

    def test_translate_snapshot_persists_failed_pages(self):
        started = threading.Event()
        release = threading.Event()
        first_bp, _ = get_page_range(self.doc_a_pages)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate_with_first_page_error(started, release, first_bp)),
        ):
            set_current_doc(self.doc_a_id)
            resp = self._post("/start_translate_all", data={
                "doc_id": self.doc_a_id,
                "start_bp": first_bp,
                "doc_title": "Doc A",
            })
            self.assertEqual(resp.get_json()["status"], "started")
            self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入翻译逻辑")
            release.set()
            self._wait_for_worker_stop(timeout=3.0)

        status = self.client.get("/translate_status", query_string={"doc_id": self.doc_a_id}).get_json()
        self.assertIn(first_bp, status["failed_bps"])
        self.assertEqual(status["failed_pages"][0]["bp"], first_bp)
        self.assertIn("boom", status["failed_pages"][0]["error"])

    def test_usage_route_redirects_back_to_reading_with_dashboard_open(self):
        set_current_doc(self.doc_a_id)
        resp = self.client.get("/translate_api_usage?doc_id=" + self.doc_a_id)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/reading", resp.headers["Location"])
        self.assertIn("usage=1", resp.headers["Location"])

    def test_reading_page_embeds_usage_dashboard_instead_of_external_link(self):
        set_current_doc(self.doc_a_id)
        resp = self.client.get("/reading?bp=1&auto=1&usage=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("toggleUsageDashboard", html)
        self.assertIn("translateUsagePanel", html)
        self.assertIn("translate_api_usage_data", html)
        self.assertIn("usageDraftMini", html)
        self.assertIn("usageDraftProgress", html)
        self.assertIn("usageDraftPreview", html)
        self.assertIn("applyStreamDelta", html)
        self.assertIn("renderStreamDraftState", html)
        self.assertNotIn("href=\"/translate_api_usage", html)

    def test_reading_page_progress_logic_keeps_bar_visible_for_idle_history(self):
        set_current_doc(self.doc_a_id)
        resp = self.client.get("/reading?bp=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("function hasPageProgressInStore()", html)
        self.assertIn("function hasPageProgressInSnapshot(state)", html)
        self.assertIn("if (state.phase === 'idle') {", html)
        self.assertIn("return hasPageProgressInSnapshot(state) || hasPageProgressInStore();", html)
        self.assertIn("} else if (state.phase === 'idle') {", html)

    def test_reading_page_embeds_rate_limit_wait_rendering_hooks(self):
        set_current_doc(self.doc_a_id)
        resp = self.client.get("/reading?bp=1&auto=1&usage=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("if (action === 'rate_limit_wait') {", html)
        self.assertIn("store.streamDraft.status === 'throttled'", html)
        self.assertIn("translateES.addEventListener('rate_limit_wait'", html)

    def test_reading_page_retranslate_flow_submits_post_action(self):
        set_current_doc(self.doc_a_id)
        resp = self.client.get("/reading?bp=1&auto=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("submitPostAction(retranslateUrl, {doc_id: docId});", html)
        self.assertNotIn("window.location.href = retranslateUrl;", html)

    def test_reading_page_exposes_resume_translate_action_after_stop(self):
        set_current_doc(self.doc_a_id)
        resp = self.client.get("/reading?bp=1&auto=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("resumeTranslateFromSnapshot", html)
        self.assertIn("继续翻译", html)

    def test_resume_logic_tolerates_dirty_snapshot_counts(self):
        set_current_doc(self.doc_a_id)
        tasks._save_translate_state(
            self.doc_a_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            total_pages=8,
            done_pages=10,
            pending_pages=0,
            current_bp=5,
            current_page_idx=5,
        )

        resp = self.client.get("/reading?bp=5")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("resumeTranslateFromSnapshot", html)
        self.assertIn("继续翻译", html)


if __name__ == "__main__":
    unittest.main()

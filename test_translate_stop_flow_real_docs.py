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
from unittest.mock import patch

import app as app_module
import config
import tasks
from config import create_doc, ensure_dirs, get_doc_dir, set_current_doc
from ocr_parser import parse_ocr, clean_header_footer
from storage import load_entries_from_disk, save_entries_to_disk, save_pages_to_disk
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


class TranslateStopFlowRealDocsTest(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="translate-stop-", dir="/tmp")
        self._patch_config_dirs(self.temp_root)
        ensure_dirs()
        self._reset_translate_task()
        self.client = app_module.app.test_client()
        self.doc_a_id, self.doc_a_pages = self._create_doc_fixture(DOC_A_PDF, DOC_A_OCR)
        self.doc_b_id, self.doc_b_pages = self._create_doc_fixture(DOC_B_PDF, DOC_B_OCR)

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
        with open(ocr_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        parsed = parse_ocr(raw)
        cleaned = clean_header_footer(parsed["pages"])
        pages = cleaned["pages"]

        doc_id = create_doc(pdf_path.name)
        save_pages_to_disk(pages, pdf_path.name, doc_id)
        save_entries_to_disk([], pdf_path.stem, 0, doc_id)
        shutil.copy2(pdf_path, Path(get_doc_dir(doc_id)) / "source.pdf")
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
                resp = self.client.post("/start_translate_all", data={
                    "doc_id": self.doc_a_id,
                    "start_bp": first_bp,
                    "doc_title": "Doc A",
                })
                self.assertEqual(resp.get_json()["status"], "started")
                self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")

                set_current_doc(self.doc_b_id)
                stop_resp = self.client.get("/stop_translate", query_string={"doc_id": self.doc_a_id})
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
                resp = self.client.post("/start_translate_all", data={
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

    def test_worker_persists_entries_as_page_files(self):
        started = threading.Event()
        release = threading.Event()
        first_bp, _ = get_page_range(self.doc_a_pages)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model", "api_key": "fake-key", "provider": "fake"}),
            patch.object(tasks, "translate_page_stream", side_effect=_build_fake_translate(started, release)),
        ):
            set_current_doc(self.doc_a_id)
            resp = self.client.post("/start_translate_all", data={
                "doc_id": self.doc_a_id,
                "start_bp": first_bp,
                "doc_title": "Doc A",
            })
            self.assertEqual(resp.get_json()["status"], "started")
            self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")
            release.set()
            self._wait_for_worker_stop(timeout=3.0)

        doc_dir = Path(get_doc_dir(self.doc_a_id))
        self.assertTrue((doc_dir / "entries" / "meta.json").exists())
        self.assertTrue(any((doc_dir / "entries" / "pages").glob("*.json")))
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
            resp = self.client.get("/fetch_next")

        self.assertEqual(resp.status_code, 302)
        entries, _, _ = load_entries_from_disk(self.doc_a_id)
        self.assertEqual([entry.get("_pageBP") for entry in entries[:2]], [first_bp, first_bp + 1])

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
            resp = self.client.get("/retranslate/2/sonnet")

        self.assertEqual(resp.status_code, 302)
        entries, _, _ = load_entries_from_disk(self.doc_a_id)
        self.assertEqual(entries[1]["_page_entries"][0]["translation"], "新的翻译 2")

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
                resp = self.client.post("/start_translate_all", data={
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
                resp = self.client.post("/start_translate_all", data={
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
            resp = self.client.post("/start_translate_all", data={
                "doc_id": self.doc_a_id,
                "start_bp": first_bp,
                "doc_title": "Doc A",
            })
            self.assertEqual(resp.get_json()["status"], "started")
            self.assertTrue(started.wait(timeout=1.0), "翻译线程没有进入首段翻译")

            stop_resp = self.client.get("/stop_translate", query_string={"doc_id": self.doc_a_id})
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
        self.assertIn("var currentPageBp = 1;", html)
        self.assertIn("goReadingPage", html)
        self.assertIn("translate_status", html)
        self.assertIn("start_translate_all", html)
        self.assertIn("stop_translate", html)
        self.assertIn("readingAutoStart === '1' && currentPageBp === d.bp", html)

    def test_reading_route_supports_physical_page_without_translated_entry(self):
        set_current_doc(self.doc_a_id)
        resp = self.client.get("/reading?bp=5&auto=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("本页尚未提交翻译", html)
        self.assertIn("var currentPageBp = 5;", html)
        self.assertIn("pageNavBtn", html)
        self.assertIn("pageNavList", html)
        self.assertNotIn("navSelect", html)

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
        self.assertIn("本页翻译失败", html)
        self.assertIn('var failedPageBps = [5];', html)
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
            resp = self.client.post("/start_translate_all", data={
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
            resp = self.client.post("/start_translate_all", data={
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

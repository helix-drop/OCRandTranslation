#!/usr/bin/env python3
"""SQLite 主链路切换准备测试。"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import config
import app as app_module
import tasks
from config import create_doc, ensure_dirs, get_current_doc_id, get_doc_meta, list_docs, set_current_doc
from sqlite_store import SQLiteRepository
from storage import load_entries_from_disk, load_pages_from_disk, save_entries_to_disk, save_pages_to_disk


class SQLiteMainlineTest(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="sqlite-mainline-", dir="/tmp")
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

    def test_documents_and_pages_write_to_sqlite_mainline(self):
        doc_id = create_doc("mainline.pdf")
        save_pages_to_disk([
            {
                "bookPage": 7,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 7",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 8,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 8",
                "footnotes": "fn-8",
                "textSource": "pdf",
            },
        ], "mainline.pdf", doc_id)

        pages, src_name = load_pages_from_disk(doc_id)
        meta = get_doc_meta(doc_id)
        docs = list_docs()

        self.assertEqual(get_current_doc_id(), doc_id)
        self.assertEqual(src_name, "mainline.pdf")
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[1]["textSource"], "pdf")
        self.assertEqual(meta["name"], "mainline.pdf")
        self.assertEqual(meta["page_count"], 2)
        self.assertEqual(docs[0]["id"], doc_id)

    def test_translate_state_mainline_reads_active_run_from_sqlite(self):
        doc_id = create_doc("state.pdf")
        draft = {
            "active": True,
            "bp": 7,
            "para_idx": 1,
            "para_total": 3,
            "para_done": 1,
            "parallel_limit": 2,
            "active_para_indices": [1],
            "paragraph_states": ["done", "streaming", "pending"],
            "paragraph_errors": ["", "", ""],
            "paragraphs": ["第一段", "", ""],
            "status": "streaming",
            "note": "正在翻译",
            "last_error": "",
            "updated_at": 0,
        }
        tasks._save_translate_state(
            doc_id,
            running=True,
            stop_requested=False,
            phase="running",
            start_bp=7,
            current_bp=7,
            resume_bp=7,
            total_pages=10,
            done_pages=2,
            processed_pages=3,
            pending_pages=7,
            current_page_idx=3,
            translated_chars=123,
            translated_paras=5,
            request_count=2,
            prompt_tokens=11,
            completion_tokens=7,
            model="qwen-plus",
            failed_bps=[9],
            partial_failed_bps=[8],
            failed_pages=[{"bp": 9, "error": "boom"}],
            draft=draft,
        )

        repo = SQLiteRepository()
        active = repo.get_active_translate_run(doc_id)
        snapshot = tasks._load_translate_state(doc_id)

        self.assertIsNotNone(active)
        self.assertEqual(active["phase"], "running")
        self.assertTrue(active["running"])
        self.assertEqual(active["current_bp"], 7)
        self.assertEqual(snapshot["phase"], "running")
        self.assertEqual(snapshot["prompt_tokens"], 11)
        self.assertEqual(snapshot["completion_tokens"], 7)
        self.assertEqual(snapshot["failed_bps"], [9])
        self.assertEqual(snapshot["partial_failed_bps"], [8])
        self.assertEqual(snapshot["draft"]["status"], "streaming")
        self.assertFalse(os.path.exists(os.path.join(config.DOCS_DIR, doc_id, "translate_state.json")))

        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            start_bp=7,
            current_bp=8,
            resume_bp=8,
            total_pages=10,
            done_pages=3,
            processed_pages=4,
            pending_pages=6,
            current_page_idx=4,
            translated_chars=222,
            translated_paras=8,
            request_count=3,
            prompt_tokens=20,
            completion_tokens=12,
            model="qwen-plus",
            failed_bps=[],
            partial_failed_bps=[],
            failed_pages=[],
            draft={"active": False, "paragraphs": [], "paragraph_states": [], "paragraph_errors": []},
        )

        self.assertIsNone(repo.get_active_translate_run(doc_id))
        effective = repo.get_effective_translate_run(doc_id)
        self.assertEqual(effective["phase"], "stopped")
        self.assertFalse(effective["running"])
        self.assertEqual(effective["resume_bp"], 8)
        self.assertEqual(repo.list_translate_failures(doc_id), [])

    def test_effective_translation_page_returns_current_page_result(self):
        doc_id = create_doc("entry.pdf")
        repo = SQLiteRepository()
        translation_page_id = repo.save_translation_page(
            doc_id,
            16,
            {
                "_model": "qwen-plus",
                "_status": "done",
                "pages": "16",
                "_usage": {"total_tokens": 10},
                "_page_entries": [
                    {
                        "original": "Paragraph A",
                        "translation": "段落 A",
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                    }
                ],
            },
        )

        self.assertGreater(translation_page_id, 0)
        page = repo.get_effective_translation_page(doc_id, 16)
        self.assertIsNotNone(page)
        self.assertEqual(page["_model"], "qwen-plus")
        self.assertEqual(page["_usage"]["total_tokens"], 10)
        self.assertEqual(page["_page_entries"][0]["translation"], "段落 A")

    def test_reading_route_reads_current_effective_entry_from_sqlite(self):
        doc_id = create_doc("reading.pdf")
        save_pages_to_disk([
            {
                "bookPage": 16,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Original paragraph",
                "footnotes": "",
                "textSource": "ocr",
            }
        ], "reading.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 16,
            "_model": "qwen-plus",
            "_page_entries": [{
                "original": "Original paragraph",
                "translation": "当前页译文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "16",
            }],
            "pages": "16",
        }], "Reading Doc", 0, doc_id)

        entries, title, idx = load_entries_from_disk(doc_id)
        self.assertEqual(title, "Reading Doc")
        self.assertEqual(idx, 0)
        self.assertEqual(entries[0]["_page_entries"][0]["translation"], "当前页译文")

        resp = self.client.get(f"/reading?bp=16&doc_id={doc_id}&orig=0&pdf=0&usage=0&layout=stack")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("当前页译文", html)

    def test_export_md_reads_current_effective_entries_from_sqlite(self):
        doc_id = create_doc("export.pdf")
        save_entries_to_disk([{
            "_pageBP": 8,
            "_model": "qwen-plus",
            "_page_entries": [{
                "original": "Original paragraph",
                "translation": "导出译文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "8",
            }],
            "pages": "8",
        }], "Export Doc", 0, doc_id)

        resp = self.client.get(f"/export_md?doc_id={doc_id}")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertIn("导出译文", payload["markdown"])

    def test_translate_snapshot_loads_failures_from_translate_failures_table(self):
        doc_id = create_doc("failure.pdf")
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=5,
            total_pages=2,
            done_pages=1,
            processed_pages=2,
            pending_pages=0,
            current_bp=6,
            current_page_idx=2,
            failed_bps=[6],
            failed_pages=[{"bp": 6, "error": "失败页"}],
        )

        repo = SQLiteRepository()
        failures = repo.list_translate_failures(doc_id)
        snapshot = tasks.get_translate_snapshot(doc_id)

        self.assertEqual(failures[0]["bp"], 6)
        self.assertEqual(snapshot["failed_pages"][0]["bp"], 6)
        self.assertEqual(snapshot["failed_bps"], [6])

    def test_resume_bp_and_phase_for_partial_failed_and_stopped(self):
        """验证 resume_bp 规则与 phase 切换行为。"""
        doc_id = create_doc("resume.pdf")
        # 准备两页，起始从 p.5
        save_pages_to_disk([
            {
                "bookPage": 5,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 5",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 6,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 6",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "resume.pdf", doc_id)

        # 场景 1：partial_failed，优先从失败页/部分失败页恢复
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=5,
            current_bp=6,
            total_pages=2,
            done_pages=1,
            processed_pages=2,
            pending_pages=0,
            failed_bps=[6],
            partial_failed_bps=[],
            failed_pages=[{"bp": 6, "error": "boom"}],
        )
        snapshot = tasks.get_translate_snapshot(doc_id)
        self.assertEqual(snapshot["phase"], "partial_failed")
        self.assertEqual(snapshot["resume_bp"], 6)

        # 场景 2：stopped，当前页尚未处理，应从 current_bp 恢复
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            start_bp=5,
            current_bp=6,
            total_pages=2,
            done_pages=1,
            processed_pages=1,
            pending_pages=1,
            failed_bps=[],
            partial_failed_bps=[],
            failed_pages=[],
        )
        snapshot2 = tasks.get_translate_snapshot(doc_id)
        self.assertEqual(snapshot2["phase"], "stopped")
        self.assertEqual(snapshot2["resume_bp"], 6)

        # 场景 3：全部完成但存在部分失败页，phase 应为 partial_failed，resume_bp 指向首个需要关注的页
        save_entries_to_disk([{
            "_pageBP": 5,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 5",
                "translation": "[翻译失败: timeout]",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "5",
                "_status": "error",
                "_error": "timeout",
            }],
            "pages": "5",
        }], "resume.pdf", 0, doc_id)
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=5,
            current_bp=None,
            total_pages=2,
            done_pages=2,
            processed_pages=2,
            pending_pages=0,
            failed_bps=[],
            partial_failed_bps=[5],
            failed_pages=[],
        )
        snapshot3 = tasks.get_translate_snapshot(doc_id)
        self.assertEqual(snapshot3["phase"], "partial_failed")
        self.assertEqual(snapshot3["resume_bp"], 5)

    def test_fetch_next_success_reconciles_failed_state_in_translate_snapshot(self):
        doc_id = create_doc("fetch-next-success.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 1",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 2,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 2",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "fetch-next-success.pdf", doc_id)
        save_entries_to_disk([{
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
        }], "Fetch Next", 0, doc_id)
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=1,
            current_bp=2,
            total_pages=2,
            done_pages=1,
            processed_pages=1,
            pending_pages=1,
            failed_bps=[2],
            failed_pages=[{"bp": 2, "error": "旧失败"}],
        )

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(app_module, "translate_page", return_value={
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
            }),
        ):
            resp = self.client.get(f"/fetch_next?doc_id={doc_id}")

        self.assertEqual(resp.status_code, 302)
        status = self.client.get(f"/translate_status?doc_id={doc_id}").get_json()
        self.assertEqual(status["failed_bps"], [])
        self.assertEqual(status["partial_failed_bps"], [])
        self.assertIn(status["phase"], ("done", "stopped", "idle"))

    def test_fetch_next_failure_marks_failed_page_in_translate_snapshot(self):
        doc_id = create_doc("fetch-next-fail.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 1",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 2,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 2",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "fetch-next-fail.pdf", doc_id)
        save_entries_to_disk([{
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
        }], "Fetch Next", 0, doc_id)
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            start_bp=1,
            current_bp=2,
            total_pages=2,
            done_pages=1,
            processed_pages=1,
            pending_pages=1,
            failed_bps=[],
            failed_pages=[],
        )

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(app_module, "translate_page", side_effect=RuntimeError("fetch_next boom")),
        ):
            resp = self.client.get(f"/fetch_next?doc_id={doc_id}")

        self.assertEqual(resp.status_code, 302)
        status = self.client.get(f"/translate_status?doc_id={doc_id}").get_json()
        self.assertEqual(status["failed_bps"], [2])
        self.assertEqual(status["failed_pages"][0]["bp"], 2)
        self.assertIn("fetch_next boom", status["last_error"])
        self.assertEqual(status["resume_bp"], 2)

    def test_retranslate_failure_always_marks_failed_page(self):
        doc_id = create_doc("retranslate-fail.pdf")
        save_pages_to_disk([{
            "bookPage": 7,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 7",
            "footnotes": "",
            "textSource": "ocr",
        }], "retranslate-fail.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 7,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 7",
                "translation": "旧翻译",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "7",
                "_status": "done",
                "_error": "",
            }],
            "pages": "7",
        }], "Retran", 0, doc_id)
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="done",
            start_bp=7,
            current_bp=7,
            total_pages=1,
            done_pages=1,
            processed_pages=1,
            pending_pages=0,
            failed_bps=[],
            failed_pages=[],
        )

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(app_module, "translate_page", side_effect=RuntimeError("retranslate boom")),
        ):
            resp = self.client.get(f"/retranslate/7/sonnet?doc_id={doc_id}")

        self.assertEqual(resp.status_code, 302)
        status = self.client.get(f"/translate_status?doc_id={doc_id}").get_json()
        self.assertEqual(status["failed_bps"], [7])
        self.assertEqual(status["failed_pages"][0]["bp"], 7)
        self.assertIn("retranslate boom", status["last_error"])
        self.assertEqual(status["resume_bp"], 7)

    def test_save_manual_revision_updates_reading_and_export(self):
        doc_id = create_doc("manual-revision.pdf")
        save_pages_to_disk([{
            "bookPage": 16,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 16",
            "footnotes": "",
            "textSource": "ocr",
        }], "manual-revision.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 16,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Paragraph A",
                "translation": "机器译文 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "16",
                "_status": "done",
                "_error": "",
            }],
            "pages": "16",
        }], "Manual Revision", 0, doc_id)

        read_before = self.client.get(f"/reading?bp=16&doc_id={doc_id}").get_data(as_text=True)
        resp = self.client.post(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={
                "bp": 16,
                "segment_index": 0,
                "translation": "人工修订 A",
            },
        )
        payload = resp.get_json()
        read_html = self.client.get(f"/reading?bp=16&doc_id={doc_id}").get_data(as_text=True)
        export_payload = self.client.get(f"/export_md?doc_id={doc_id}").get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["segment"]["translation"], "人工修订 A")
        self.assertEqual(payload["segment"]["_translation_source"], "manual")
        self.assertIn("编辑译文", read_before)
        self.assertIn("机器译文", read_before)
        self.assertIn("人工修订 A", read_html)
        self.assertIn("人工修订", read_html)
        self.assertIn("人工修订 A", export_payload["markdown"])
        self.assertNotIn("机器译文 A", export_payload["markdown"])

    def test_reading_page_has_history_button_and_usage_manual_metrics(self):
        doc_id = create_doc("history-btn.pdf")
        save_pages_to_disk([{
            "bookPage": 16,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 16",
            "footnotes": "",
            "textSource": "ocr",
        }], "history-btn.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 16,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Paragraph A",
                "translation": "机器译文 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "16",
                "_status": "done",
                "_error": "",
            }],
            "pages": "16",
        }], "History Btn", 0, doc_id)

        read_html = self.client.get(f"/reading?bp=16&doc_id={doc_id}").get_data(as_text=True)
        self.assertIn("查看历史", read_html)
        self.assertIn('id="usageManualRevisions"', read_html)
        self.assertIn('id="usagePagesWithRevisions"', read_html)

    def test_save_manual_revision_conflict_returns_409(self):
        doc_id = create_doc("manual-revision-conflict.pdf")
        save_pages_to_disk([{
            "bookPage": 8,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 8",
            "footnotes": "",
            "textSource": "ocr",
        }], "manual-revision-conflict.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 8,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Paragraph B",
                "translation": "机器译文 B",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "8",
                "_status": "done",
                "_error": "",
            }],
            "pages": "8",
        }], "Manual Revision Conflict", 0, doc_id)

        first = self.client.post(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={
                "bp": 8,
                "segment_index": 0,
                "translation": "人工修订 B1",
            },
        ).get_json()
        stale_base = int(first["segment"]["updated_at"]) - 1
        second = self.client.post(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={
                "bp": 8,
                "segment_index": 0,
                "translation": "人工修订 B2",
                "base_updated_at": stale_base,
            },
        )

        self.assertEqual(second.status_code, 409)
        self.assertIn("冲突", second.get_json()["error"])

    def test_doc_scoped_glossary_isolated_between_documents(self):
        doc_a = create_doc("glossary-a.pdf")
        doc_b = create_doc("glossary-b.pdf")

        config.set_glossary([["raison", "理性"]], doc_id=doc_a)
        config.set_glossary([["pouvoir", "权力"]], doc_id=doc_b)

        self.assertEqual(config.get_glossary(doc_a), [["raison", "理性"]])
        self.assertEqual(config.get_glossary(doc_b), [["pouvoir", "权力"]])

    def test_fetch_next_uses_doc_scoped_glossary(self):
        doc_a = create_doc("glossary-fetch-a.pdf")
        doc_b = create_doc("glossary-fetch-b.pdf")
        set_current_doc(doc_b)
        config.set_glossary([["raison", "理性"]], doc_id=doc_a)
        config.set_glossary([["pouvoir", "权力"]], doc_id=doc_b)

        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 1",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 2,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 2",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "glossary-fetch-a.pdf", doc_a)
        save_entries_to_disk([{
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
        }], "Glossary Fetch A", 0, doc_a)

        with (
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(app_module, "translate_page", return_value={
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
            }) as mock_translate,
        ):
            resp = self.client.get(f"/fetch_next?doc_id={doc_a}")

        self.assertEqual(resp.status_code, 302)
        used_glossary = mock_translate.call_args[0][4]
        self.assertEqual(used_glossary, [["raison", "理性"]])

    def test_translate_api_usage_data_includes_manual_revision_count(self):
        doc_id = create_doc("usage-manual-revision.pdf")
        save_pages_to_disk([{
            "bookPage": 3,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 3",
            "footnotes": "",
            "textSource": "ocr",
        }], "usage-manual-revision.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 3,
            "_model": "sonnet",
            "_usage": {"request_count": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "_page_entries": [{
                "original": "Paragraph C",
                "translation": "机器译文 C",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "3",
                "_status": "done",
                "_error": "",
            }],
            "pages": "3",
        }], "Usage Manual Revision", 0, doc_id)

        self.client.post(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={
                "bp": 3,
                "segment_index": 0,
                "translation": "人工修订 C",
            },
        )
        usage = self.client.get(f"/translate_api_usage_data?doc_id={doc_id}").get_json()

        self.assertEqual(usage["total_manual_revisions"], 1)
        self.assertEqual(usage["pages"][0]["manual_revision_count"], 1)

    def _setup_doc_with_manual_revision(self, doc_id_name):
        """Helper: create doc, page, entry, and one manual revision. Returns (doc_id, bp=10)."""
        doc_id = create_doc(f"{doc_id_name}.pdf")
        save_pages_to_disk([{
            "bookPage": 10,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 10",
            "footnotes": "",
            "textSource": "ocr",
        }], f"{doc_id_name}.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 10,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Original",
                "translation": "机器译文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "10",
                "_status": "done",
                "_error": "",
            }],
            "pages": "10",
        }], doc_id_name, 0, doc_id)
        resp = self.client.post(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={"bp": 10, "segment_index": 0, "translation": "人工修订文本"},
        )
        self.assertEqual(resp.status_code, 200)
        return doc_id

    def test_segment_history_api_returns_previous_state(self):
        doc_id = self._setup_doc_with_manual_revision("history-api-test")
        resp = self.client.get(
            f"/segment_history?doc_id={doc_id}&bp=10&segment_index=0"
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["revisions"]), 1)
        # The history entry should hold the model translation before manual revision
        self.assertEqual(payload["revisions"][0]["translation_text"], "机器译文")
        self.assertEqual(payload["revisions"][0]["revision_source"], "model")

    def test_check_retranslate_warnings_returns_manual_count(self):
        doc_id = self._setup_doc_with_manual_revision("retranslate-warn-test")
        resp = self.client.get(
            f"/check_retranslate_warnings?doc_id={doc_id}&bp=10"
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["manual_count"], 1)

    def test_conflict_409_returns_server_segment(self):
        doc_id = create_doc("conflict-server-seg.pdf")
        save_pages_to_disk([{
            "bookPage": 5,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 5",
            "footnotes": "",
            "textSource": "ocr",
        }], "conflict-server-seg.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 5,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Para",
                "translation": "机器译文 C",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "5",
                "_status": "done",
                "_error": "",
            }],
            "pages": "5",
        }], "Conflict Server Seg", 0, doc_id)

        first = self.client.post(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={"bp": 5, "segment_index": 0, "translation": "人工修订 C1"},
        ).get_json()

        stale_base = int(first["segment"]["updated_at"]) - 1
        second = self.client.post(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={
                "bp": 5,
                "segment_index": 0,
                "translation": "人工修订 C2",
                "base_updated_at": stale_base,
            },
        )
        payload = second.get_json()

        self.assertEqual(second.status_code, 409)
        self.assertIn("冲突", payload["error"])
        self.assertIsNotNone(payload.get("server_segment"))
        self.assertEqual(payload["server_segment"]["translation"], "人工修订 C1")

    def test_retranslate_after_manual_revision_logs_history(self):
        doc_id = self._setup_doc_with_manual_revision("retranslate-history-test")

        # Single-page retranslate mirrors the /retranslate route: uses save_entry_to_disk
        from storage import save_entry_to_disk
        save_entry_to_disk({
            "_pageBP": 10,
            "_model": "qwen",
            "_page_entries": [{
                "original": "Original",
                "translation": "新机器译文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "10",
                "_status": "done",
                "_error": "",
            }],
            "pages": "10",
        }, "retranslate-history-test", doc_id)

        # Current effective translation should be the new model text
        repo = SQLiteRepository()
        page = repo.get_effective_translation_page(doc_id, 10)
        self.assertEqual(page["_page_entries"][0]["translation"], "新机器译文")

        # History should contain the old manual revision snapshotted before retranslate
        revisions = repo.list_segment_revisions(doc_id, 10, 0)
        manual_texts = [r.get("manual_translation_text") for r in revisions]
        self.assertIn("人工修订文本", manual_texts)


if __name__ == "__main__":
    unittest.main()

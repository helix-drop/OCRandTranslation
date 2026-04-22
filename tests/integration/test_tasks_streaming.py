#!/usr/bin/env python3
"""后台流式翻译任务单元测试。"""

import os
import re
import shutil
import tempfile
import time
import unittest
import json
from io import BytesIO
from unittest.mock import Mock, patch

import app as app_module
import config
import ocr_client
import document.ocr_parser as ocr_parser
import persistence.storage as storage
import persistence.task_logs as task_logs
import pipeline.document_tasks as document_tasks
import pipeline.task_registry as task_registry
import translation.service as tasks
import translation.translate_launch as translate_launch
import translation.translate_runtime as translate_runtime
import web.document_routes as document_routes
from config import (
    create_doc, ensure_dirs, get_current_doc_id, get_doc_meta,
    get_upload_auto_visual_toc_enabled, get_upload_cleanup_headers_footers_enabled,
    set_current_doc, update_doc_meta,
)
from persistence.storage import (
    load_entries_from_disk,
    load_pages_from_disk,
    save_entries_to_disk,
    save_pages_to_disk,
    get_translate_args,
    resolve_model_spec,
)
from persistence.sqlite_store import SQLiteRepository
from testsupport import ClientCSRFMixin
from translation.translator import (
    TranslateStreamAborted,
    RateLimitedError,
    QuotaExceededError,
    NonRetryableProviderError,
)


class TasksStreamingTest(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="tasks-stream-")
        self._patch_config_dirs(self.temp_root)
        ensure_dirs()
        self.doc_id = create_doc("streaming-test.pdf")
        save_entries_to_disk([], "Streaming Test", 0, self.doc_id)
        self._reset_translate_task()
        self.pages = [{
            "bookPage": 1,
            "markdown": "Para one\n\nPara two",
        }]
        self.context = {
            "paragraphs": [
                {"heading_level": 0, "text": "Para one"},
                {"heading_level": 0, "text": "Para two"},
            ],
            "footnotes": "",
        }

    def tearDown(self):
        self._reset_translate_task()
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def _reset_translate_task(self):
        with translate_runtime._translate_lock:
            translate_runtime._translate_task["running"] = False
            translate_runtime._translate_task["stop"] = False
            translate_runtime._translate_task["events"] = []
            translate_runtime._translate_task["doc_id"] = ""
            translate_runtime._translate_task["owner_token"] = 0
            translate_runtime._translate_task["log_relpath"] = ""

    def _task_events(self, task_id: str):
        events, _exists = task_registry.get_task_events(task_id, 0)
        return events

    def test_translate_page_stream_pushes_delta_events(self):
        def _fake_stream(*args, **kwargs):
            yield {"type": "delta", "text": "甲"}
            yield {"type": "delta", "text": "乙"}
            yield {"type": "usage", "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "request_count": 1}}
            yield {"type": "done", "text": "", "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "request_count": 1}, "result": {
                "pages": "1",
                "original": "Para one",
                "translation": "甲乙",
                "footnotes": "",
                "footnotes_translation": "",
                "_usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "request_count": 1},
            }}

        pushed = []
        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=self.context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[], []]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
            patch.object(tasks, "translate_push", side_effect=lambda event_type, data: pushed.append((event_type, data))),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="fake-model",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual(entry["_page_entries"][0]["translation"], "甲乙")
        self.assertIn("stream_para_delta", [event_type for event_type, _ in pushed])
        self.assertEqual(entry["_usage"]["total_tokens"], 10)
        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["draft"]["status"], "done")
        self.assertEqual(snapshot["draft"]["para_total"], 2)
        self.assertEqual(snapshot["draft"]["para_done"], 2)
        self.assertEqual(snapshot["draft"]["paragraphs"], ["甲乙", "甲乙"])

    def test_process_file_persists_cleanup_mode_and_skips_cleaning_when_disabled(self):
        fd, file_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4\n%upload\n")
        task_id = "uploadskip01"
        task_registry.create_task(
            task_id,
            file_path,
            "upload-skip.pdf",
            0,
            options={"clean_header_footer": False},
        )
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [{
                "text": "OCR 正文",
                "x": 12,
                "bbox": [0, 0, 50, 20],
                "label": "text",
                "is_meta": False,
                "heading_level": 0,
            }],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "OCR 正文",
        }

        with (
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "extract_pdf_text", return_value=[]),
            patch.object(document_tasks, "_annotate_note_scans", side_effect=lambda pages, **kwargs: pages),
            patch.object(document_tasks.text_processing, "clean_header_footer") as clean_mock,
            patch.object(document_tasks, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_tasks, "extract_pdf_toc", return_value=[]),
            patch.object(document_tasks, "extract_pdf_toc_from_links", return_value=[]),
        ):
            document_tasks.process_file(task_id)

        clean_mock.assert_not_called()
        doc_id = get_current_doc_id()
        meta = get_doc_meta(doc_id)
        pages, _ = load_pages_from_disk(doc_id)
        self.assertFalse(meta["cleanup_headers_footers"])
        self.assertFalse(pages[0]["_cleanup_applied"])

    def test_process_file_rechecks_saved_upload_preferences_after_pdf_extraction(self):
        fd, file_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4\n%upload-refresh\n")
        task_id = "uploadrefresh01"
        task_registry.create_task(
            task_id,
            file_path,
            "upload-refresh.pdf",
            0,
            options={"clean_header_footer": False, "auto_visual_toc": False},
        )
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [{
                "text": "OCR 正文",
                "x": 12,
                "bbox": [0, 0, 50, 20],
                "label": "text",
                "is_meta": False,
                "heading_level": 0,
            }],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "OCR 正文",
        }

        def _flip_upload_preferences(_file_bytes):
            config.set_upload_processing_preferences(
                cleanup_headers_footers=True,
                auto_visual_toc=True,
            )
            return []

        with (
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "extract_pdf_text", side_effect=_flip_upload_preferences),
            patch.object(document_tasks, "_annotate_note_scans", side_effect=lambda pages, **kwargs: pages),
            patch.object(document_tasks.text_processing, "clean_header_footer", return_value={"pages": [ocr_page], "log": []}) as clean_mock,
            patch.object(document_tasks, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_tasks, "extract_pdf_toc", return_value=[]),
            patch.object(document_tasks, "extract_pdf_toc_from_links", return_value=[]),
            patch.object(document_tasks, "run_auto_visual_toc_for_doc", return_value={"status": "ready", "count": 2}) as visual_toc_mock,
            patch.object(document_tasks, "run_fnm_pipeline", return_value={"ok": True, "section_count": 1, "note_count": 1, "unit_count": 1}),
            patch.object(document_tasks, "start_fnm_translate_task", return_value=False),
        ):
            document_tasks.process_file(task_id)

        doc_id = get_current_doc_id()
        meta = get_doc_meta(doc_id)
        pages, _ = load_pages_from_disk(doc_id)
        self.assertTrue(get_upload_cleanup_headers_footers_enabled())
        self.assertTrue(get_upload_auto_visual_toc_enabled())
        self.assertTrue(task_registry.get_task(task_id)["options"]["clean_header_footer"])
        self.assertTrue(task_registry.get_task(task_id)["options"]["auto_visual_toc"])
        clean_mock.assert_called_once()
        visual_toc_mock.assert_called_once()
        self.assertTrue(meta["cleanup_headers_footers"])
        self.assertTrue(meta["auto_visual_toc_enabled"])
        self.assertTrue(pages[0]["_cleanup_applied"])

    def test_process_file_runs_fnm_pipeline_after_visual_toc_is_ready(self):
        fd, file_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4\n%fnm\n")
        task_id = "uploadfnm01"
        task_registry.create_task(
            task_id,
            file_path,
            "upload-fnm.pdf",
            0,
            options={"clean_header_footer": True, "auto_visual_toc": True},
        )
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "OCR 正文",
            "prunedResult": {"parsing_res_list": []},
        }

        with (
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "extract_pdf_text", return_value=[]),
            patch.object(document_tasks, "_annotate_note_scans", side_effect=lambda pages, **kwargs: pages),
            patch.object(document_tasks.text_processing, "clean_header_footer", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_tasks, "extract_pdf_toc", return_value=[]),
            patch.object(document_tasks, "extract_pdf_toc_from_links", return_value=[]),
            patch.object(document_tasks, "run_auto_visual_toc_for_doc", return_value={"status": "ready", "count": 2}) as visual_toc_mock,
            patch.object(document_tasks, "run_fnm_pipeline", return_value={"ok": True}) as fnm_mock,
            patch.object(document_tasks, "start_fnm_translate_task", return_value=False),
        ):
            document_tasks.process_file(task_id)

        visual_toc_mock.assert_called_once()
        fnm_mock.assert_called_once()

    def test_process_file_done_event_routes_standard_and_writes_doc_log(self):
        fd, file_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4\n%standard-route\n")
        task_id = "uploadroute01"
        task_registry.create_task(
            task_id,
            file_path,
            "upload-route.pdf",
            0,
            options={"clean_header_footer": False, "auto_visual_toc": False},
        )
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "OCR 正文",
            "prunedResult": {"parsing_res_list": []},
        }

        with (
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "extract_pdf_text", return_value=[]),
            patch.object(document_tasks, "_annotate_note_scans", side_effect=lambda pages, **kwargs: pages),
            patch.object(document_tasks, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_tasks, "extract_pdf_toc", return_value=[]),
            patch.object(document_tasks, "extract_pdf_toc_from_links", return_value=[]),
            patch.object(document_tasks, "run_fnm_pipeline", return_value={"ok": True, "section_count": 1, "note_count": 1, "unit_count": 1}) as fnm_mock,
            patch.object(document_tasks, "start_fnm_translate_task", return_value=True) as start_fnm_mock,
        ):
            document_tasks.process_file(task_id)

        done_events = [payload for event_type, payload in self._task_events(task_id) if event_type == "done"]
        self.assertEqual(len(done_events), 1)
        done_payload = done_events[0]
        doc_id = done_payload["doc_id"]
        log_relpath = done_payload["log_relpath"]
        log_path = task_logs.resolve_doc_task_log_path(doc_id, log_relpath)

        self.assertEqual(done_payload["route_mode"], "standard")
        self.assertTrue(done_payload["redirect_allowed"])
        self.assertEqual(done_payload["start_bp"], 1)
        self.assertFalse(start_fnm_mock.called)
        self.assertFalse(fnm_mock.called)
        self.assertTrue(os.path.exists(log_path))
        with open(log_path, "r", encoding="utf-8") as fh:
            log_text = fh.read()
        self.assertIn("快速模式解析完成后将直接进入标准阅读视图", log_text)
        self.assertIn("解析完成！1页", log_text)

    def test_process_file_done_event_routes_fnm_when_cleanup_enabled(self):
        fd, file_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4\n%fnm-route\n")
        task_id = "uploadroute02"
        task_registry.create_task(
            task_id,
            file_path,
            "upload-fnm-route.pdf",
            0,
            options={"clean_header_footer": True, "auto_visual_toc": True},
        )
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "OCR 正文",
            "prunedResult": {"parsing_res_list": []},
        }

        with (
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "extract_pdf_text", return_value=[]),
            patch.object(document_tasks, "_annotate_note_scans", side_effect=lambda pages, **kwargs: pages),
            patch.object(document_tasks.text_processing, "clean_header_footer", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_tasks, "extract_pdf_toc", return_value=[]),
            patch.object(document_tasks, "extract_pdf_toc_from_links", return_value=[]),
            patch.object(document_tasks, "run_auto_visual_toc_for_doc", return_value={"status": "ready", "count": 3}),
            patch.object(document_tasks, "run_fnm_pipeline", return_value={
                "ok": True,
                "run_id": 12,
                "section_count": 1,
                "note_count": 2,
                "unit_count": 3,
                "structure_state": "review_required",
                "manual_toc_required": False,
                "export_ready_real": False,
                "blocking_reasons": ["toc_no_exportable_chapter"],
            }),
            patch.object(document_tasks, "start_fnm_translate_task", return_value=True) as start_fnm_mock,
        ):
            document_tasks.process_file(task_id)

        done_events = [payload for event_type, payload in self._task_events(task_id) if event_type == "done"]
        self.assertEqual(len(done_events), 1)
        done_payload = done_events[0]
        log_path = task_logs.resolve_doc_task_log_path(done_payload["doc_id"], done_payload["log_relpath"])

        self.assertEqual(done_payload["route_mode"], "fnm_progress")
        self.assertFalse(done_payload["redirect_allowed"])
        self.assertIn("FNM 分类完成", done_payload["redirect_message"])
        self.assertIn("请留在首页点击“开始翻译”", done_payload["redirect_message"])
        self.assertFalse(start_fnm_mock.called)
        with open(log_path, "r", encoding="utf-8") as fh:
            log_text = fh.read()
        self.assertIn("请留在首页点击“开始翻译”", log_text)
        self.assertIn("首页保留在 FNM 进度模式", log_text)
        self.assertIn("FNM 解析状态：run_id=12", log_text)
        self.assertIn("FNM 阻塞项：toc_no_exportable_chapter", log_text)

    def test_process_file_fnm_failure_blocks_auto_redirect_without_downgrading(self):
        fd, file_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4\n%fnm-fail\n")
        task_id = "uploadroute03"
        task_registry.create_task(
            task_id,
            file_path,
            "upload-fnm-fail.pdf",
            0,
            options={"clean_header_footer": True, "auto_visual_toc": True},
        )
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "OCR 正文",
            "prunedResult": {"parsing_res_list": []},
        }

        with (
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "extract_pdf_text", return_value=[]),
            patch.object(document_tasks, "_annotate_note_scans", side_effect=lambda pages, **kwargs: pages),
            patch.object(document_tasks.text_processing, "clean_header_footer", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_tasks, "extract_pdf_toc", return_value=[]),
            patch.object(document_tasks, "extract_pdf_toc_from_links", return_value=[]),
            patch.object(document_tasks, "run_auto_visual_toc_for_doc", return_value={"status": "ready", "count": 3}),
            patch.object(document_tasks, "run_fnm_pipeline", return_value={"ok": False, "error": "bad_notes"}),
            patch.object(document_tasks, "start_fnm_translate_task", return_value=True) as start_fnm_mock,
        ):
            document_tasks.process_file(task_id)

        done_events = [payload for event_type, payload in self._task_events(task_id) if event_type == "done"]
        self.assertEqual(len(done_events), 1)
        done_payload = done_events[0]

        self.assertEqual(done_payload["route_mode"], "fnm_progress")
        self.assertFalse(done_payload["redirect_allowed"])
        self.assertIn("FootNoteMachine 分类失败", done_payload["redirect_message"])
        self.assertFalse(start_fnm_mock.called)

    def test_process_file_visual_toc_failure_blocks_fnm_and_returns_error(self):
        fd, file_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4\n%fnm-visual-fail\n")
        task_id = "uploadroute04"
        task_registry.create_task(
            task_id,
            file_path,
            "upload-fnm-visual-fail.pdf",
            0,
            options={"clean_header_footer": True, "auto_visual_toc": True},
        )
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "OCR 正文",
            "prunedResult": {"parsing_res_list": []},
        }

        with (
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "extract_pdf_text", return_value=[]),
            patch.object(document_tasks, "_annotate_note_scans", side_effect=lambda pages, **kwargs: pages),
            patch.object(document_tasks.text_processing, "clean_header_footer", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_tasks, "extract_pdf_toc", return_value=[]),
            patch.object(document_tasks, "extract_pdf_toc_from_links", return_value=[]),
            patch.object(document_tasks, "run_auto_visual_toc_for_doc", return_value={"status": "failed", "count": 0, "message": "视觉目录失败"}) as visual_toc_mock,
            patch.object(document_tasks, "run_fnm_pipeline", return_value={"ok": True}) as fnm_mock,
        ):
            document_tasks.process_file(task_id)

        visual_toc_mock.assert_called_once()
        self.assertFalse(fnm_mock.called)
        error_events = [payload for event_type, payload in self._task_events(task_id) if event_type == "error_msg"]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0]["error"], "视觉目录失败")

    def test_process_file_visual_toc_exception_blocks_fnm_and_surfaces_error(self):
        fd, file_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4\n%fnm-visual-exception\n")
        task_id = "uploadroute04_exception"
        task_registry.create_task(
            task_id,
            file_path,
            "upload-fnm-visual-exception.pdf",
            0,
            options={"clean_header_footer": True, "auto_visual_toc": True},
        )
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "OCR 正文",
            "prunedResult": {"parsing_res_list": []},
        }

        with (
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "extract_pdf_text", return_value=[]),
            patch.object(document_tasks, "_annotate_note_scans", side_effect=lambda pages, **kwargs: pages),
            patch.object(document_tasks.text_processing, "clean_header_footer", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_tasks, "extract_pdf_toc", return_value=[]),
            patch.object(document_tasks, "extract_pdf_toc_from_links", return_value=[]),
            patch.object(document_tasks, "run_auto_visual_toc_for_doc", side_effect=RuntimeError("dashscope 400 invalid_request")) as visual_toc_mock,
            patch.object(document_tasks, "run_fnm_pipeline", return_value={"ok": True}) as fnm_mock,
        ):
            document_tasks.process_file(task_id)

        visual_toc_mock.assert_called_once()
        self.assertFalse(fnm_mock.called)
        error_events = [payload for event_type, payload in self._task_events(task_id) if event_type == "error_msg"]
        self.assertEqual(len(error_events), 1)
        self.assertIn("自动视觉目录请求失败", error_events[0]["error"])
        self.assertIn("dashscope 400 invalid_request", error_events[0]["error"])

    def test_clean_header_footer_reports_detailed_progress_stages(self):
        pages = []
        for index in range(4):
            pages.append(
                {
                    "bookPage": index + 1,
                    "imgH": 1000,
                    "blocks": [
                        {"text": "Repeated Header", "bbox": [0, 10, 300, 30]},
                        {"text": f"Body {index + 1}", "bbox": [40, 200, 400, 600]},
                        {"text": str(index + 1), "bbox": [260, 950, 320, 980]},
                    ],
                    "fnBlocks": [],
                }
            )
        events = []

        result = ocr_parser.clean_header_footer(
            pages,
            on_progress=lambda phase, pct, detail: events.append((phase, pct, detail)),
        )

        self.assertGreaterEqual(len(events), 4)
        phase_order = []
        for phase, _, _ in events:
            if phase not in phase_order:
                phase_order.append(phase)
        self.assertEqual(
            phase_order[:4],
            ["collect_candidates", "detect_patterns", "apply_cleanup", "note_scan_ready"],
        )
        self.assertIn("重复模式", events[1][2])
        self.assertIn("页", events[2][2])
        self.assertTrue(result["log"])

    def test_translate_worker_marks_error_when_pages_missing_after_initial_start(self):
        doc_id = create_doc("worker-empty.pdf")

        started = translate_launch.start_translate_task(doc_id, 1, "Worker Empty")

        self.assertTrue(started)
        self.assertTrue(translate_runtime.wait_for_translate_idle(timeout_s=2.0, poll_interval_s=0.05))

        snapshot = translate_runtime.get_translate_snapshot(doc_id)
        self.assertEqual(snapshot["phase"], "error")
        self.assertFalse(snapshot["running"])
        self.assertEqual(snapshot["total_pages"], 0)
        self.assertEqual(snapshot["pending_pages"], 0)
        self.assertIn("未找到可翻译页面", snapshot["last_error"])

    def test_start_translate_task_creates_per_doc_log_and_exposes_log_relpath(self):
        save_pages_to_disk(
            [{"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""}],
            "Streaming Test",
            self.doc_id,
        )

        def _release_worker(_doc_id, _start_bp, _doc_title, owner_token):
            translate_runtime.release_translate_runtime(owner_token)

        with patch.object(translate_launch, "get_translate_args", return_value={
            "model_id": "fake-model",
            "model_key": "fake-model",
            "api_key": "fake-key",
            "provider": "fake",
            "display_label": "Fake Model",
        }):
            started = translate_launch.start_translate_task(
                self.doc_id,
                1,
                "Streaming Test",
                worker_target=_release_worker,
            )

        self.assertTrue(started)
        self.assertTrue(translate_runtime.wait_for_translate_idle(timeout_s=2.0, poll_interval_s=0.05))
        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        log_relpath = snapshot["task"]["log_relpath"]
        log_path = task_logs.resolve_doc_task_log_path(self.doc_id, log_relpath)

        self.assertTrue(log_relpath.startswith("logs/translate_continuous_"))
        self.assertTrue(os.path.exists(log_path))
        with open(log_path, "r", encoding="utf-8") as fh:
            log_text = fh.read()
        self.assertIn("连续翻译任务已启动", log_text)

        client = app_module.app.test_client()
        reading_resp = client.get(f"/reading?bp=1&doc_id={self.doc_id}")
        self.assertIn(log_relpath, reading_resp.get_data(as_text=True))

    def test_start_fnm_translate_task_creates_per_doc_log(self):
        def _release_worker(_doc_id, _doc_title, owner_token):
            translate_runtime.release_translate_runtime(owner_token)

        with patch.object(translate_launch, "get_translate_args", return_value={
            "model_id": "fake-model",
            "model_key": "fake-model",
            "api_key": "fake-key",
            "provider": "fake",
            "display_label": "Fake Model",
        }):
            started = translate_launch.start_fnm_translate_task(
                self.doc_id,
                "Streaming Test",
                worker_target=_release_worker,
            )

        self.assertTrue(started)
        self.assertTrue(translate_runtime.wait_for_translate_idle(timeout_s=2.0, poll_interval_s=0.05))
        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        log_relpath = snapshot["task"]["log_relpath"]
        log_path = task_logs.resolve_doc_task_log_path(self.doc_id, log_relpath)

        self.assertTrue(log_relpath.startswith("logs/translate_fnm_"))
        self.assertTrue(os.path.exists(log_path))
        with open(log_path, "r", encoding="utf-8") as fh:
            log_text = fh.read()
        self.assertIn("FNM 翻译任务已启动", log_text)

    def test_translate_worker_stops_before_next_page_start_without_regressing_progress(self):
        save_pages_to_disk([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
            {"bookPage": 2, "fileIdx": 1, "markdown": "Page 2", "footnotes": ""},
        ], "Streaming Test", self.doc_id)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "fake-model",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "译文 1",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
            }],
            "pages": "1",
        }], "Streaming Test", 0, self.doc_id)
        pushed = []

        with translate_runtime._translate_lock:
            translate_runtime._translate_task["running"] = True
            translate_runtime._translate_task["stop"] = True
            translate_runtime._translate_task["events"] = []
            translate_runtime._translate_task["doc_id"] = self.doc_id

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake-model-id", "model_key": "fake-model", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "translate_push", side_effect=lambda event_type, data: pushed.append((event_type, data))),
        ):
            tasks._translate_all_worker(self.doc_id, 1, "Streaming Test")

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["phase"], "stopped")
        self.assertEqual(snapshot["done_pages"], 1)
        self.assertEqual(snapshot["processed_pages"], 1)
        self.assertEqual(snapshot["pending_pages"], 1)
        self.assertNotIn("page_start", [event_type for event_type, _ in pushed])
        self.assertEqual(pushed[-1][0], "stopped")

    def test_translate_worker_marks_quota_error_and_pushes_quota_event(self):
        save_pages_to_disk([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
        ], "Streaming Test", self.doc_id)
        pushed = []

        with translate_runtime._translate_lock:
            translate_runtime._translate_task["running"] = True
            translate_runtime._translate_task["stop"] = False
            translate_runtime._translate_task["events"] = []
            translate_runtime._translate_task["doc_id"] = self.doc_id

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake-model-id", "model_key": "fake-model", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "get_glossary", return_value=[]),
            patch.object(tasks, "translate_page_stream", side_effect=QuotaExceededError("模型额度已耗尽")),
            patch.object(tasks, "translate_push", side_effect=lambda event_type, data: pushed.append((event_type, data))),
        ):
            tasks._translate_all_worker(self.doc_id, 1, "Streaming Test")

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["phase"], "error")
        self.assertFalse(snapshot["running"])
        self.assertEqual(snapshot["done_pages"], 0)
        self.assertEqual(snapshot["processed_pages"], 0)
        self.assertEqual(snapshot["pending_pages"], 1)
        self.assertIn("模型额度已耗尽", snapshot["last_error"])
        quota_events = [data for event_type, data in pushed if event_type == "error"]
        self.assertEqual(len(quota_events), 1)
        self.assertEqual(quota_events[0]["kind"], "quota")
        self.assertEqual(quota_events[0]["bp"], 1)

    def test_translate_worker_stops_on_non_retryable_provider_error(self):
        save_pages_to_disk([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
        ], "Streaming Test", self.doc_id)
        pushed = []

        with translate_runtime._translate_lock:
            translate_runtime._translate_task["running"] = True
            translate_runtime._translate_task["stop"] = False
            translate_runtime._translate_task["events"] = []
            translate_runtime._translate_task["doc_id"] = self.doc_id

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake-model-id", "model_key": "fake-model", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "get_glossary", return_value=[]),
            patch.object(
                tasks,
                "translate_page_stream",
                side_effect=NonRetryableProviderError("模型请求失败（HTTP 400）：invalid_request", status_code=400),
            ),
            patch.object(tasks, "translate_push", side_effect=lambda event_type, data: pushed.append((event_type, data))),
        ):
            tasks._translate_all_worker(self.doc_id, 1, "Streaming Test")

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["phase"], "error")
        self.assertFalse(snapshot["running"])
        self.assertEqual(snapshot["done_pages"], 0)
        self.assertIn("HTTP 400", snapshot["last_error"])
        fatal_events = [data for event_type, data in pushed if event_type == "error"]
        self.assertEqual(len(fatal_events), 1)
        self.assertEqual(fatal_events[0]["kind"], "fatal_provider")
        self.assertEqual(fatal_events[0]["bp"], 1)

    def test_glossary_retranslate_counts_only_targeted_segments(self):
        save_pages_to_disk([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
        ], "Streaming Test", self.doc_id)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "fake-model",
            "_page_entries": [
                {"original": "Para 0", "translation": "保留一", "pages": "1"},
                {"original": "Para 1", "translation": "旧译文", "pages": "1"},
                {"original": "Para 2", "translation": "保留二", "pages": "1"},
            ],
            "pages": "1",
        }], "Streaming Test", 0, self.doc_id)
        task_meta = tasks._build_translate_task_meta(
            kind=tasks.TASK_KIND_GLOSSARY_RETRANSLATE,
            label="词典补重译",
            start_bp=1,
            start_segment_index=0,
            target_bps=[1],
            affected_segments=1,
            target_segments_by_bp={"1": [1]},
        )
        pushed = []
        updated_entry = {
            "_pageBP": 1,
            "_model": "fake-model",
            "_page_entries": [
                {"original": "Para 0", "translation": "保留一", "pages": "1"},
                {"original": "Para 1", "translation": "只重译这里", "pages": "1"},
                {"original": "Para 2", "translation": "保留二", "pages": "1"},
            ],
            "_usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5, "request_count": 1},
            "pages": "1",
        }
        captured_target_indices = []

        def _fake_retranslate(_pages, _bp, _existing_entry, _model_key, _t_args, _glossary, *, target_segment_indices):
            captured_target_indices.append(list(target_segment_indices))
            return updated_entry, {
                "targeted_segments": 1,
                "targeted_segment_indices": [1],
                "skipped_manual_segments": 2,
            }

        with translate_runtime._translate_lock:
            translate_runtime._translate_task["running"] = True
            translate_runtime._translate_task["stop"] = False
            translate_runtime._translate_task["events"] = []
            translate_runtime._translate_task["doc_id"] = self.doc_id

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake-model-id", "model_key": "fake-model", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "get_glossary", return_value=[]),
            patch.object(tasks, "retranslate_page_with_current_glossary", side_effect=_fake_retranslate),
            patch.object(tasks, "translate_push", side_effect=lambda event_type, data: pushed.append((event_type, data))),
        ):
            tasks._glossary_retranslate_worker(self.doc_id, task_meta, "Streaming Test")

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["phase"], "done")
        self.assertEqual(snapshot["translated_paras"], 1)
        self.assertEqual(snapshot["translated_chars"], len("只重译这里"))
        self.assertEqual(captured_target_indices, [[1]])
        page_done = [data for event_type, data in pushed if event_type == "page_done"]
        self.assertEqual(len(page_done), 1)
        self.assertEqual(page_done[0]["para_count"], 1)
        self.assertEqual(page_done[0]["char_count"], len("只重译这里"))

    def test_glossary_retranslate_records_failed_pages_and_reaches_terminal_reconcile(self):
        save_pages_to_disk([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
            {"bookPage": 2, "fileIdx": 1, "markdown": "Page 2", "footnotes": ""},
        ], "Streaming Test", self.doc_id)
        save_entries_to_disk([
            {
                "_pageBP": 1,
                "_model": "fake-model",
                "_page_entries": [{"original": "Para 1", "translation": "旧译文 1", "pages": "1"}],
                "pages": "1",
            },
            {
                "_pageBP": 2,
                "_model": "fake-model",
                "_page_entries": [{"original": "Para 2", "translation": "旧译文 2", "pages": "2"}],
                "pages": "2",
            },
        ], "Streaming Test", 0, self.doc_id)
        task_meta = tasks._build_translate_task_meta(
            kind=tasks.TASK_KIND_GLOSSARY_RETRANSLATE,
            label="词典补重译",
            start_bp=1,
            start_segment_index=0,
            target_bps=[1, 2],
            affected_segments=2,
            target_segments_by_bp={"1": [0], "2": [0]},
        )
        pushed = []

        def _fake_retranslate(_pages, bp, existing_entry, *_args, **_kwargs):
            if int(bp) == 1:
                raise RuntimeError("第一页失败")
            return (
                {
                    **existing_entry,
                    "_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1},
                    "_page_entries": [{"original": "Para 2", "translation": "新译文 2", "pages": "2"}],
                },
                {
                    "targeted_segments": 1,
                    "targeted_segment_indices": [0],
                    "skipped_manual_segments": 0,
                },
            )

        with translate_runtime._translate_lock:
            translate_runtime._translate_task["running"] = True
            translate_runtime._translate_task["stop"] = False
            translate_runtime._translate_task["events"] = []
            translate_runtime._translate_task["doc_id"] = self.doc_id

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake-model-id", "model_key": "fake-model", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "get_glossary", return_value=[]),
            patch.object(tasks, "retranslate_page_with_current_glossary", side_effect=_fake_retranslate),
            patch.object(tasks, "translate_push", side_effect=lambda event_type, data: pushed.append((event_type, data))),
        ):
            tasks._glossary_retranslate_worker(self.doc_id, task_meta, "Streaming Test")

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["phase"], "partial_failed")
        self.assertEqual(snapshot["done_pages"], 2)
        self.assertEqual(snapshot["processed_pages"], 2)
        self.assertEqual(snapshot["pending_pages"], 0)
        self.assertEqual(snapshot["failed_bps"], [1])
        self.assertEqual(snapshot["failed_pages"][0]["bp"], 1)
        event_types = [event_type for event_type, _ in pushed]
        self.assertIn("page_error", event_types)
        self.assertIn("page_done", event_types)
        self.assertEqual(pushed[-1][0], "all_done")

    def test_get_translate_args_prefers_custom_model_name_when_enabled(self):
        config.save_config({
            "active_model_mode": "custom",
            "active_builtin_model_key": "qwen-plus",
            "dashscope_key": "dashscope-test-key",
            "custom_model": {
                "enabled": True,
                "display_name": "Qwen 3.5 Plus",
                "provider_type": "qwen",
                "model_id": "qwen3.5-plus",
                "base_url": "",
                "qwen_region": "sg",
                "api_key_mode": "builtin_dashscope",
                "custom_api_key": "",
                "extra_body": {"enable_thinking": False},
            },
        })

        spec = resolve_model_spec()
        t_args = get_translate_args()

        self.assertEqual(spec.source, "custom")
        self.assertEqual(spec.model_key, "")
        self.assertEqual(spec.model_id, "qwen3.5-plus")
        self.assertEqual(spec.provider, "qwen")
        self.assertEqual(spec.base_url, "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(spec.display_label, "Qwen 3.5 Plus")
        self.assertEqual(spec.request_overrides, {"extra_body": {"enable_thinking": False}})
        self.assertEqual(t_args["api_key"], "dashscope-test-key")

    def test_get_translate_args_uses_builtin_target_when_explicitly_requested(self):
        config.save_config({
            "active_model_mode": "custom",
            "active_builtin_model_key": "qwen-max",
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

        spec = resolve_model_spec("builtin:qwen-max")
        t_args = get_translate_args("builtin:qwen-max")

        self.assertEqual(spec.source, "builtin")
        self.assertEqual(spec.model_key, "qwen-max")
        self.assertEqual(t_args["provider"], "qwen")
        self.assertEqual(t_args["model_id"], "qwen-max")

    def test_translate_page_stream_accepts_full_translate_args_payload(self):
        config.save_config({
            "active_model_mode": "custom",
            "active_builtin_model_key": "qwen-plus",
            "dashscope_key": "dashscope-test-key",
            "custom_model": {
                "enabled": True,
                "display_name": "qwen3.5-plus",
                "provider_type": "qwen",
                "model_id": "qwen3.5-plus",
                "base_url": "",
                "qwen_region": "cn",
                "api_key_mode": "builtin_dashscope",
                "custom_api_key": "",
                "extra_body": {"enable_thinking": False},
            },
        })
        t_args = get_translate_args()
        self.assertIn("model_key", t_args)
        self.assertIn("display_label", t_args)
        captured = {}

        def _strict_stream(
            para_text,
            para_pages,
            footnotes,
            glossary,
            model_id,
            api_key,
            provider="deepseek",
            stop_checker=None,
            base_url=None,
            request_overrides=None,
            heading_level=0,
            para_idx=None,
            para_total=None,
            prev_context="",
            next_context="",
            section_path=None,
            cross_page=None,
            content_role="body",
            is_fnm=False,
        ):
            captured.update({
                "model_id": model_id,
                "api_key": api_key,
                "provider": provider,
                "base_url": base_url,
                "request_overrides": request_overrides,
                "para_idx": para_idx,
                "content_role": content_role,
            })
            yield {"type": "usage", "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3, "request_count": 1}}
            yield {"type": "done", "text": "", "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3, "request_count": 1}, "result": {
                "pages": para_pages,
                "original": para_text,
                "translation": f"流式译文{para_idx + 1}",
                "footnotes": footnotes,
                "footnotes_translation": "",
                "_usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3, "request_count": 1},
            }}

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=self.context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[], []]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", new=_strict_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="qwen-plus",
                t_args=t_args,
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual(entry["_page_entries"][0]["translation"], "流式译文1")
        self.assertEqual(captured["model_id"], "qwen3.5-plus")
        self.assertEqual(captured["provider"], "qwen")
        self.assertEqual(captured["request_overrides"], {"extra_body": {"enable_thinking": False}})
        self.assertEqual(captured["content_role"], "body")

    def test_translate_page_accepts_full_translate_args_payload(self):
        config.save_config({
            "active_model_mode": "custom",
            "active_builtin_model_key": "qwen-plus",
            "dashscope_key": "dashscope-test-key",
            "custom_model": {
                "enabled": True,
                "display_name": "qwen3.5-plus",
                "provider_type": "qwen",
                "model_id": "qwen3.5-plus",
                "base_url": "",
                "qwen_region": "sg",
                "api_key_mode": "builtin_dashscope",
                "custom_api_key": "",
                "extra_body": {"enable_thinking": False},
            },
        })
        t_args = get_translate_args()
        captured = {}

        def _strict_translate(
            para_text,
            para_pages,
            footnotes,
            glossary,
            model_id,
            api_key,
            provider="deepseek",
            base_url=None,
            request_overrides=None,
            heading_level=0,
            para_idx=None,
            para_total=None,
            prev_context="",
            next_context="",
            section_path=None,
            cross_page=None,
            content_role="body",
        ):
            captured.update({
                "model_id": model_id,
                "api_key": api_key,
                "provider": provider,
                "base_url": base_url,
                "request_overrides": request_overrides,
                "content_role": content_role,
            })
            return {
                "pages": para_pages,
                "original": para_text,
                "translation": f"普通译文{para_idx + 1}",
                "footnotes": footnotes,
                "footnotes_translation": "",
                "_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1},
            }

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=self.context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[], []]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "translate_paragraph", new=_strict_translate),
        ):
            entry = tasks.translate_page(
                pages=self.pages,
                target_bp=1,
                model_key="qwen-plus",
                t_args=t_args,
                glossary=[],
            )

        self.assertEqual(entry["_page_entries"][0]["translation"], "普通译文1")
        self.assertEqual(captured["model_id"], "qwen3.5-plus")
        self.assertEqual(captured["base_url"], "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(captured["request_overrides"], {"extra_body": {"enable_thinking": False}})
        self.assertEqual(captured["content_role"], "body")

    def test_translate_page_mt_body_uses_companion_chat_for_page_footnotes(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph [1].",
            "footnotes": "1. Page note",
            "fnBlocks": [],
        }]
        context = {
            "paragraphs": [{"heading_level": 0, "text": "Body paragraph [1]."}],
            "footnotes": "1. Page note",
            "page_num": 1,
            "print_page_label": "1",
            "print_page_display": "原书 p.1",
            "prev_tail": "",
            "next_head": "",
        }
        captured = []

        def _fake_translate(
            para_text,
            para_pages,
            footnotes,
            glossary,
            model_id,
            api_key,
            provider="deepseek",
            base_url=None,
            request_overrides=None,
            heading_level=0,
            para_idx=None,
            para_total=None,
            prev_context="",
            next_context="",
            section_path=None,
            cross_page=None,
            content_role="body",
            is_fnm=False,
        ):
            captured.append({
                "model_id": model_id,
                "provider": provider,
                "content_role": content_role,
                "footnotes": footnotes,
            })
            if content_role == "body":
                return {
                    "pages": para_pages,
                    "original": para_text,
                    "translation": "正文译文",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1},
                }
            return {
                "pages": para_pages,
                "original": footnotes,
                "translation": "脚注译文",
                "footnotes": "",
                "footnotes_translation": "",
                "_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1},
            }

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[]]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "translate_paragraph", new=_fake_translate),
        ):
            entry = tasks.translate_page(
                pages=pages,
                target_bp=1,
                model_key="qwen-mt-plus",
                t_args={
                    "model_id": "qwen-mt-plus",
                    "api_key": "fake-key",
                    "provider": "qwen_mt",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "request_overrides": {"extra_body": {"translation_options": {"source_lang": "auto", "target_lang": "Chinese"}}},
                    "companion_chat_model": {
                        "model_id": "qwen-plus",
                        "provider": "qwen",
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "request_overrides": {"extra_body": {"enable_thinking": False}},
                    },
                },
                glossary=[],
            )

        self.assertEqual(entry["_page_entries"][0]["translation"], "正文译文")
        self.assertEqual(entry["_page_entries"][0]["footnotes_translation"], "脚注译文")
        self.assertEqual(captured[0]["model_id"], "qwen-mt-plus")
        self.assertEqual(captured[0]["provider"], "qwen_mt")
        self.assertEqual(captured[1]["model_id"], "qwen-plus")
        self.assertEqual(captured[1]["provider"], "qwen")

    def test_translate_page_uses_note_scan_page_footnotes_for_body_jobs(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph [1].",
            "footnotes": "",
            "fnBlocks": [],
            "_note_scan": {
                "page_kind": "body_with_page_footnotes",
                "items": [
                    {
                        "kind": "footnote",
                        "marker": "1.",
                        "number": 1,
                        "text": "1. Page note from scan.",
                        "order": 1,
                        "source": "note_scan",
                        "confidence": 1.0,
                    }
                ],
                "section_hints": [],
                "ambiguity_flags": [],
                "reviewed_by_model": False,
            },
        }]
        context = {
            "paragraphs": [{"heading_level": 0, "text": "Body paragraph [1]."}],
            "footnotes": "",
            "page_num": 1,
            "print_page_label": "1",
            "print_page_display": "原书 p.1",
            "prev_tail": "",
            "next_head": "",
        }
        captured = {}

        def _strict_translate(
            para_text,
            para_pages,
            footnotes,
            glossary,
            model_id,
            api_key,
            provider="deepseek",
            base_url=None,
            request_overrides=None,
            heading_level=0,
            para_idx=None,
            para_total=None,
            prev_context="",
            next_context="",
            section_path=None,
            cross_page=None,
            content_role="body",
        ):
            captured["footnotes"] = footnotes
            captured["content_role"] = content_role
            return {
                "pages": para_pages,
                "original": para_text,
                "translation": "正文译文",
                "footnotes": footnotes,
                "footnotes_translation": "",
                "_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1},
            }

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[]]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "translate_paragraph", new=_strict_translate),
        ):
            entry = tasks.translate_page(
                pages=pages,
                target_bp=1,
                model_key="qwen-plus",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
            )

        self.assertEqual(captured["content_role"], "body")
        self.assertEqual(captured["footnotes"], "1. Page note from scan.")
        self.assertEqual(entry["footnotes"], "1. Page note from scan.")

    def test_translate_page_stream_mt_fnm_note_job_uses_companion_chat(self):
        prepared_ctx = {
            "footnotes": "",
            "print_page_display": "原书 p.1",
        }
        prepared_jobs = [
            {
                "para_idx": 0,
                "para_total": 1,
                "source_idx": 0,
                "bp": 1,
                "heading_level": 0,
                "text": "脚注原文",
                "cross_page": None,
                "start_bp": 1,
                "end_bp": 1,
                "print_page_label": "1",
                "print_page_display": "原书 p.1",
                "bboxes": [],
                "footnotes": "",
                "prev_context": "",
                "next_context": "",
                "section_path": ["Demo"],
                "content_role": "footnote",
                "note_kind": "footnote",
                "note_marker": "1",
                "note_number": 1,
                "note_section_title": "Demo",
                "note_confidence": 1.0,
                "fnm_note_id": "fn-01-0001",
            }
        ]
        captured = []

        def _fake_stream_translate(
            para_text,
            para_pages,
            footnotes,
            glossary,
            model_id,
            api_key,
            provider="deepseek",
            stop_checker=None,
            base_url=None,
            request_overrides=None,
            heading_level=0,
            para_idx=None,
            para_total=None,
            prev_context="",
            next_context="",
            section_path=None,
            cross_page=None,
            content_role="body",
            is_fnm=False,
        ):
            captured.append({
                "model_id": model_id,
                "provider": provider,
                "content_role": content_role,
                "is_fnm": is_fnm,
            })
            yield {"type": "delta", "text": "脚注译文"}
            yield {"type": "usage", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1}}
            yield {
                "type": "done",
                "text": "脚注译文",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1},
                "result": {
                    "pages": para_pages,
                    "original": para_text,
                    "translation": "脚注译文",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1},
                },
            }

        with (
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream_translate),
            patch.object(tasks, "translate_push", side_effect=lambda *a, **k: None),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="qwen-mt-plus",
                t_args={
                    "model_id": "qwen-mt-plus",
                    "api_key": "fake-key",
                    "provider": "qwen_mt",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "request_overrides": {"extra_body": {"translation_options": {"source_lang": "auto", "target_lang": "Chinese"}}},
                    "companion_chat_model": {
                        "model_id": "qwen-plus",
                        "provider": "qwen",
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "request_overrides": {"extra_body": {"enable_thinking": False}},
                    },
                },
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
                prepared_ctx=prepared_ctx,
                prepared_para_jobs=prepared_jobs,
                prepared_total_usage={},
                prepared_is_fnm=True,
            )

        self.assertEqual(entry["_page_entries"][0]["translation"], "脚注译文")
        self.assertEqual(captured[0]["model_id"], "qwen-plus")
        self.assertEqual(captured[0]["provider"], "qwen")
        self.assertEqual(captured[0]["content_role"], "footnote")

    def test_translate_page_turns_endnotes_into_individual_jobs(self):
        pages = [{
            "bookPage": 10,
            "markdown": "Closing paragraph.\nNOTES\n1. First endnote.\n2. Second endnote.",
            "footnotes": "",
            "fnBlocks": [],
            "_note_scan": {
                "page_kind": "endnote_collection",
                "items": [
                    {
                        "kind": "endnote",
                        "marker": "1.",
                        "number": 1,
                        "text": "1. First endnote.",
                        "order": 1,
                        "source": "note_scan",
                        "confidence": 1.0,
                        "section_title": "Introduction",
                    },
                    {
                        "kind": "endnote",
                        "marker": "2.",
                        "number": 2,
                        "text": "2. Second endnote.",
                        "order": 2,
                        "source": "note_scan",
                        "confidence": 1.0,
                        "section_title": "Introduction",
                    },
                ],
                "section_hints": ["NOTES", "Introduction"],
                "ambiguity_flags": [],
                "reviewed_by_model": False,
            },
        }]
        context = {
            "paragraphs": [{"heading_level": 0, "text": "This body paragraph should not be translated."}],
            "footnotes": "",
            "page_num": 10,
            "print_page_label": "172",
            "print_page_display": "原书 p.172",
            "prev_tail": "",
            "next_head": "",
        }
        calls = []

        def _strict_translate(
            para_text,
            para_pages,
            footnotes,
            glossary,
            model_id,
            api_key,
            provider="deepseek",
            base_url=None,
            request_overrides=None,
            heading_level=0,
            para_idx=None,
            para_total=None,
            prev_context="",
            next_context="",
            section_path=None,
            cross_page=None,
            content_role="body",
        ):
            calls.append({
                "para_text": para_text,
                "content_role": content_role,
                "para_idx": para_idx,
                "section_path": list(section_path or []),
            })
            return {
                "pages": para_pages,
                "original": para_text,
                "translation": f"尾注译文{para_idx + 1}",
                "footnotes": "",
                "footnotes_translation": "",
                "_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1},
            }

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[]]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "translate_paragraph", new=_strict_translate),
        ):
            entry = tasks.translate_page(
                pages=pages,
                target_bp=10,
                model_key="qwen-plus",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
            )

        self.assertEqual([call["content_role"] for call in calls], ["endnote", "endnote"])
        self.assertEqual([call["para_text"] for call in calls], ["1. First endnote.", "2. Second endnote."])
        self.assertEqual([pe["_note_kind"] for pe in entry["_page_entries"]], ["endnote", "endnote"])
        self.assertEqual([pe["_note_number"] for pe in entry["_page_entries"]], [1, 2])
        self.assertEqual([pe["_note_section_title"] for pe in entry["_page_entries"]], ["Introduction", "Introduction"])

    def test_llm_fix_paragraphs_accepts_full_translate_args_payload(self):
        config.save_config({
            "active_model_mode": "custom",
            "active_builtin_model_key": "qwen-plus",
            "dashscope_key": "dashscope-test-key",
            "custom_model": {
                "enabled": True,
                "display_name": "qwen3.5-plus",
                "provider_type": "qwen",
                "model_id": "qwen3.5-plus",
                "base_url": "",
                "qwen_region": "cn",
                "api_key_mode": "builtin_dashscope",
                "custom_api_key": "",
                "extra_body": {"enable_thinking": False},
            },
        })
        t_args = get_translate_args()
        captured = {}

        def _strict_structure(
            blocks,
            markdown,
            model_id,
            api_key,
            provider="deepseek",
            base_url=None,
            request_overrides=None,
            page_num=0,
        ):
            captured.update({
                "model_id": model_id,
                "api_key": api_key,
                "provider": provider,
                "base_url": base_url,
                "request_overrides": request_overrides,
                "page_num": page_num,
            })
            return {
                "paragraphs": [{"heading_level": 0, "text": "修正后段落"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6, "request_count": 1},
            }

        with patch.object(tasks, "structure_page", new=_strict_structure):
            paragraphs, usage = tasks._llm_fix_paragraphs(
                paragraphs=[{"heading_level": 0, "text": "原始段落"}],
                page_md="原始 markdown",
                t_args=t_args,
                page_num=7,
            )

        self.assertEqual(paragraphs[0]["text"], "修正后段落")
        self.assertEqual(usage["total_tokens"], 6)
        self.assertEqual(captured["model_id"], "qwen3.5-plus")
        self.assertEqual(captured["request_overrides"], {"extra_body": {"enable_thinking": False}})

    def test_load_config_migrates_legacy_custom_model_shape(self):
        config.save_config({
            "model_key": "deepseek-chat",
            "deepseek_key": "deepseek-test-key",
            "dashscope_key": "dashscope-test-key",
            "custom_model_name": "qwen3.5-plus",
            "custom_model_enabled": True,
            "custom_model_base_key": "qwen-max",
        })

        migrated = config.load_config()
        spec = resolve_model_spec()

        self.assertEqual(migrated["active_model_mode"], "custom")
        self.assertEqual(migrated["active_builtin_model_key"], "deepseek-chat")
        self.assertEqual(migrated["custom_model"]["provider_type"], "qwen")
        self.assertEqual(migrated["custom_model"]["model_id"], "qwen3.5-plus")
        self.assertEqual(migrated["custom_model"]["api_key_mode"], "builtin_dashscope")
        self.assertEqual(spec.provider, "qwen")
        self.assertEqual(spec.model_key, "")
        self.assertEqual(spec.model_id, "qwen3.5-plus")
        self.assertEqual(spec.api_key, "dashscope-test-key")

    def test_translate_page_stream_aborts_without_entry_when_stopped(self):
        def _fake_stream(*args, **kwargs):
            yield {"type": "delta", "text": "甲"}
            raise TranslateStreamAborted("用户停止流式翻译")

        pushed = []
        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=self.context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[], []]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
            patch.object(tasks, "translate_push", side_effect=lambda event_type, data: pushed.append((event_type, data))),
        ):
            with self.assertRaises(TranslateStreamAborted):
                tasks.translate_page_stream(
                    pages=self.pages,
                    target_bp=1,
                    model_key="fake-model",
                    t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                    glossary=[],
                    doc_id=self.doc_id,
                    stop_checker=lambda: False,
                )

        event_types = [event_type for event_type, _ in pushed]
        self.assertIn("stream_para_delta", event_types)
        self.assertIn("stream_page_aborted", event_types)
        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["draft"]["status"], "aborted")
        self.assertEqual(snapshot["draft"]["bp"], 1)
        self.assertEqual(snapshot["draft"]["paragraphs"][0], "甲")

    def test_translate_page_stream_keeps_result_order_under_parallelism(self):
        config.save_config({
            "translate_parallel_enabled": True,
            "translate_parallel_limit": 2,
        })

        def _fake_stream(*args, **kwargs):
            para_idx = kwargs["para_idx"]
            if para_idx == 0:
                time.sleep(0.05)
            else:
                time.sleep(0.01)
            text = f"译文{para_idx + 1}"
            yield {"type": "delta", "text": text[:1]}
            yield {"type": "usage", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1}}
            yield {"type": "done", "text": "", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1}, "result": {
                "pages": "1",
                "original": f"Para {para_idx + 1}",
                "translation": text,
                "footnotes": "",
                "footnotes_translation": "",
            }}

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=self.context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[], []]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="fake-model",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual([item["translation"] for item in entry["_page_entries"]], ["译文1", "译文2"])
        self.assertEqual([item["_status"] for item in entry["_page_entries"]], ["done", "done"])

    def test_translate_page_stream_retries_after_rate_limit_wait(self):
        attempts = {"count": 0}
        pushed = []

        def _fake_stream(*args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RateLimitedError("触发限流", retry_after_s=0.1)
            yield {"type": "done", "text": "", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1}, "result": {
                "pages": "1",
                "original": kwargs["para_text"],
                "translation": "重试后成功",
                "footnotes": "",
                "footnotes_translation": "",
            }}

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value={"paragraphs": [{"heading_level": 0, "text": "Para one"}], "footnotes": ""}),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[]]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
            patch.object(tasks, "translate_push", side_effect=lambda event_type, data: pushed.append((event_type, data))),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="qwen-plus",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertGreaterEqual(attempts["count"], 2)
        self.assertEqual(entry["_page_entries"][0]["translation"], "重试后成功")
        self.assertIn("rate_limit_wait", [event_type for event_type, _ in pushed])
        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertIn(snapshot["draft"]["status"], ("done", "throttled"))

    def test_translate_page_stream_raises_quota_error_without_retry(self):
        def _fake_stream(*args, **kwargs):
            raise QuotaExceededError("模型额度已耗尽")

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value={"paragraphs": [{"heading_level": 0, "text": "Para one"}], "footnotes": ""}),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[]]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            with self.assertRaises(QuotaExceededError):
                tasks.translate_page_stream(
                    pages=self.pages,
                    target_bp=1,
                    model_key="qwen-plus",
                    t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                    glossary=[],
                    doc_id=self.doc_id,
                    stop_checker=lambda: False,
                )

    def test_translate_page_stream_respects_configured_parallelism(self):
        config.save_config({
            "translate_parallel_enabled": True,
            "translate_parallel_limit": 3,
        })
        context = {
            "paragraphs": [
                {"heading_level": 0, "text": "Para one"},
                {"heading_level": 0, "text": "Para two"},
                {"heading_level": 0, "text": "Para three"},
                {"heading_level": 0, "text": "Para four"},
            ],
            "footnotes": "",
        }
        active = 0
        peak = 0
        seen = []

        def _fake_stream(*args, **kwargs):
            nonlocal active, peak, seen
            seen.append(kwargs["para_idx"])
            active += 1
            peak = max(peak, active)
            try:
                time.sleep(0.03)
                yield {"type": "done", "text": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 1}, "result": {
                    "pages": "1",
                    "original": kwargs["para_text"],
                    "translation": f"完成-{kwargs['para_idx']}",
                    "footnotes": "",
                    "footnotes_translation": "",
                }}
            finally:
                active -= 1

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[], [], [], []]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="fake-model",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual(peak, 3)
        self.assertEqual(sorted(seen), [0, 1, 2, 3])
        self.assertEqual(len(seen), 4)
        self.assertEqual([item["translation"] for item in entry["_page_entries"]], ["完成-0", "完成-1", "完成-2", "完成-3"])

    def test_translate_page_stream_defaults_to_serial_when_parallel_disabled(self):
        config.save_config({
            "translate_parallel_enabled": False,
            "translate_parallel_limit": 10,
        })
        context = {
            "paragraphs": [
                {"heading_level": 0, "text": "Para one"},
                {"heading_level": 0, "text": "Para two"},
                {"heading_level": 0, "text": "Para three"},
            ],
            "footnotes": "",
        }
        active = 0
        peak = 0

        def _fake_stream(*args, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                time.sleep(0.02)
                yield {"type": "done", "text": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 1}, "result": {
                    "pages": "1",
                    "original": kwargs["para_text"],
                    "translation": f"完成-{kwargs['para_idx']}",
                    "footnotes": "",
                    "footnotes_translation": "",
                }}
            finally:
                active -= 1

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[], [], []]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="qwen-plus",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual(peak, 1)
        self.assertEqual(entry["_page_entries"][0]["translation"], "完成-0")

    def test_translate_page_stream_allows_ten_parallel_for_qwen_plus(self):
        config.save_config({
            "translate_parallel_enabled": True,
            "translate_parallel_limit": 10,
        })
        context = {
            "paragraphs": [
                {"heading_level": 0, "text": f"Para {idx}"}
                for idx in range(12)
            ],
            "footnotes": "",
        }
        active = 0
        peak = 0

        def _fake_stream(*args, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                time.sleep(0.03)
                yield {"type": "done", "text": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 1}, "result": {
                    "pages": "1",
                    "original": kwargs["para_text"],
                    "translation": f"完成-{kwargs['para_idx']}",
                    "footnotes": "",
                    "footnotes_translation": "",
                }}
            finally:
                active -= 1

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[] for _ in range(12)]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="qwen-plus",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual(peak, 10)
        self.assertEqual(len(entry["_page_entries"]), 12)

    def test_translate_page_stream_allows_ten_parallel_for_qwen_turbo(self):
        config.save_config({
            "translate_parallel_enabled": True,
            "translate_parallel_limit": 10,
        })
        context = {
            "paragraphs": [
                {"heading_level": 0, "text": f"Para {idx}"}
                for idx in range(12)
            ],
            "footnotes": "",
        }
        active = 0
        peak = 0

        def _fake_stream(*args, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                time.sleep(0.03)
                yield {"type": "done", "text": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 1}, "result": {
                    "pages": "1",
                    "original": kwargs["para_text"],
                    "translation": f"完成-{kwargs['para_idx']}",
                    "footnotes": "",
                    "footnotes_translation": "",
                }}
            finally:
                active -= 1

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[] for _ in range(12)]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="qwen-turbo",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual(peak, 10)
        self.assertEqual(len(entry["_page_entries"]), 12)

    def test_translate_page_stream_allows_ten_parallel_for_reasoner_when_user_requests_it(self):
        config.save_config({
            "translate_parallel_enabled": True,
            "translate_parallel_limit": 10,
        })
        context = {
            "paragraphs": [
                {"heading_level": 0, "text": f"Para {idx}"}
                for idx in range(12)
            ],
            "footnotes": "",
        }
        active = 0
        peak = 0

        def _fake_stream(*args, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                time.sleep(0.03)
                yield {"type": "done", "text": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 1}, "result": {
                    "pages": "1",
                    "original": kwargs["para_text"],
                    "translation": f"完成-{kwargs['para_idx']}",
                    "footnotes": "",
                    "footnotes_translation": "",
                }}
            finally:
                active -= 1

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[] for _ in range(12)]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="deepseek-reasoner",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "deepseek"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual(peak, 10)
        self.assertEqual(len(entry["_page_entries"]), 12)

    def test_translate_page_stream_finishes_current_page_even_if_stop_requested_midway(self):
        config.save_config({
            "translate_parallel_enabled": True,
            "translate_parallel_limit": 1,
        })
        context = {
            "paragraphs": [
                {"heading_level": 0, "text": "Para one"},
                {"heading_level": 0, "text": "Para two"},
                {"heading_level": 0, "text": "Para three"},
            ],
            "footnotes": "",
        }
        stop_requested = {"value": False}
        seen = []

        def _fake_stream(*args, **kwargs):
            para_idx = kwargs["para_idx"]
            seen.append(para_idx)
            if para_idx == 0:
                stop_requested["value"] = True
            text = f"完成-{para_idx}"
            yield {"type": "done", "text": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 1}, "result": {
                "pages": "1",
                "original": kwargs["para_text"],
                "translation": text,
                "footnotes": "",
                "footnotes_translation": "",
            }}

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[], [], []]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="fake-model",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: stop_requested["value"],
            )

        self.assertEqual(seen, [0, 1, 2])
        self.assertEqual(
            [item["translation"] for item in entry["_page_entries"]],
            ["完成-0", "完成-1", "完成-2"],
        )

    def test_translate_page_stream_writes_page_level_footnotes_summary(self):
        context = {
            "paragraphs": [
                {"heading_level": 2, "text": "Chapter", "footnotes": ""},
                {"heading_level": 0, "text": "Body paragraph", "footnotes": "7. Original footnote"},
            ],
            "footnotes": "7. Original footnote",
        }

        def _fake_stream(*args, **kwargs):
            para_idx = kwargs["para_idx"]
            yield {"type": "done", "text": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 1}, "result": {
                "pages": "1",
                "original": kwargs["para_text"],
                "translation": f"译文-{para_idx}",
                "footnotes": kwargs["footnotes"],
                "footnotes_translation": "7. 脚注译文" if kwargs["footnotes"] else "",
            }}

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[], []]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="fake-model",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual(entry["footnotes"], "7. Original footnote")
        self.assertEqual(entry["footnotes_translation"], "7. 脚注译文")
        self.assertEqual(entry["_page_entries"][1]["footnotes"], "7. Original footnote")

    def test_translate_page_stream_assigns_marker_matched_footnotes_to_each_paragraph(self):
        pages = [{
            "bookPage": 1,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "First paragraph[1].\n\nSecond paragraph[2].",
            "footnotes": "[1] First footnote\n[2] Second footnote",
            "fnBlocks": [
                {"text": "[1] First footnote", "bbox": [80, 1280, 920, 1330], "label": "footnote"},
                {"text": "[2] Second footnote", "bbox": [80, 1340, 920, 1390], "label": "footnote"},
            ],
            "blocks": [
                {"text": "First paragraph[1].", "bbox": [80, 160, 920, 260], "label": "text", "is_meta": False},
                {"text": "Second paragraph[2].", "bbox": [80, 320, 920, 420], "label": "text", "is_meta": False},
            ],
        }]

        def _fake_stream(*args, **kwargs):
            footnotes = kwargs["footnotes"]
            footnotes_translation = ""
            if footnotes:
                if "[1]" in footnotes:
                    footnotes_translation = "[1] 第一条脚注译文"
                elif "[2]" in footnotes:
                    footnotes_translation = "[2] 第二条脚注译文"
            yield {"type": "done", "text": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 1}, "result": {
                "pages": "1",
                "original": kwargs["para_text"],
                "translation": f"译文-{kwargs['para_idx']}",
                "footnotes": footnotes,
                "footnotes_translation": footnotes_translation,
            }}

        with (
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=pages,
                target_bp=1,
                model_key="fake-model",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual(entry["_page_entries"][0]["footnotes"], "[1] First footnote")
        self.assertEqual(entry["_page_entries"][1]["footnotes"], "[2] Second footnote")
        self.assertEqual(entry["footnotes"], "[1] First footnote\n[2] Second footnote")
        self.assertEqual(entry["footnotes_translation"], "[1] 第一条脚注译文\n[2] 第二条脚注译文")

    def test_translate_page_stream_places_unmatched_footnote_on_last_body_paragraph(self):
        pages = [{
            "bookPage": 1,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Opening paragraph.\n\nClosing paragraph.",
            "footnotes": "1. Page-level footnote",
            "fnBlocks": [
                {"text": "1. Page-level footnote", "bbox": [80, 1340, 920, 1390], "label": "footnote"},
            ],
            "blocks": [
                {"text": "Opening paragraph.", "bbox": [80, 160, 920, 260], "label": "text", "is_meta": False},
                {"text": "Closing paragraph.", "bbox": [80, 340, 920, 440], "label": "text", "is_meta": False},
            ],
        }]

        def _fake_stream(*args, **kwargs):
            yield {"type": "done", "text": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 1}, "result": {
                "pages": "1",
                "original": kwargs["para_text"],
                "translation": f"译文-{kwargs['para_idx']}",
                "footnotes": kwargs["footnotes"],
                "footnotes_translation": "1. 页面脚注译文" if kwargs["footnotes"] else "",
            }}

        with (
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=pages,
                target_bp=1,
                model_key="fake-model",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual(entry["_page_entries"][0]["footnotes"], "")
        self.assertEqual(entry["_page_entries"][1]["footnotes"], "1. Page-level footnote")
        self.assertEqual(entry["footnotes"], "1. Page-level footnote")
        self.assertEqual(entry["footnotes_translation"], "1. 页面脚注译文")

    def test_translate_page_stream_keeps_heading_and_body_in_separate_slots(self):
        config.save_config({
            "translate_parallel_enabled": True,
            "translate_parallel_limit": 2,
        })
        context = {
            "paragraphs": [
                {"heading_level": 2, "text": "Funding"},
                {"heading_level": 0, "text": "This research received funding."},
            ],
            "footnotes": "",
        }

        def _fake_stream(*args, **kwargs):
            text = "资助" if kwargs["para_idx"] == 0 else "本研究获得资助。"
            yield {"type": "delta", "text": text}
            yield {"type": "done", "text": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "request_count": 1}, "result": {
                "pages": "1",
                "original": kwargs["para_text"],
                "translation": text,
                "footnotes": "",
                "footnotes_translation": "",
            }}

        with (
            patch.object(tasks, "get_page_context_for_translate", return_value=context),
            patch.object(tasks, "get_paragraph_bboxes", return_value=[[], []]),
            patch.object(tasks, "_needs_llm_fix", return_value=False),
            patch.object(tasks, "stream_translate_paragraph", side_effect=_fake_stream),
        ):
            entry = tasks.translate_page_stream(
                pages=self.pages,
                target_bp=1,
                model_key="fake-model",
                t_args={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"},
                glossary=[],
                doc_id=self.doc_id,
                stop_checker=lambda: False,
            )

        self.assertEqual([item["translation"] for item in entry["_page_entries"]], ["资助", "本研究获得资助。"])
        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["draft"]["paragraphs"], ["资助", "本研究获得资助。"])


class OCRClientTest(unittest.TestCase):
    def test_call_paddle_ocr_bytes_sends_official_layout_options(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "errorCode": 0,
            "errorMsg": "Success",
            "result": {"layoutParsingResults": []},
        }

        with patch.object(ocr_client.requests, "post", return_value=response) as post_mock:
            result = ocr_client.call_paddle_ocr_bytes(
                file_bytes=b"fake-image",
                token="fake-token",
                file_type=1,
            )

        self.assertEqual(result, {"layoutParsingResults": []})
        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["useDocOrientationClassify"], True)
        self.assertEqual(payload["useDocUnwarping"], True)
        self.assertEqual(payload["useTextlineOrientation"], False)
        self.assertEqual(payload["useSealRecognition"], False)
        self.assertEqual(payload["useTableRecognition"], True)
        self.assertEqual(payload["useFormulaRecognition"], True)
        self.assertEqual(payload["useChartRecognition"], False)
        self.assertEqual(payload["useRegionDetection"], True)
        self.assertEqual(payload["formatBlockContent"], False)

    def test_call_paddle_ocr_bytes_checks_official_error_code(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "errorCode": 4001,
            "errorMsg": "bad request",
            "result": None,
        }

        with patch.object(ocr_client.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "bad request"):
                ocr_client.call_paddle_ocr_bytes(
                    file_bytes=b"fake-image",
                    token="fake-token",
                    file_type=1,
                )


class ReadingRefreshContractTest(ClientCSRFMixin, unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="reading-refresh-")
        self._patch_config_dirs(self.temp_root)
        ensure_dirs()
        self.doc_id = create_doc("reading-refresh.pdf")
        set_current_doc(self.doc_id)
        save_pages_to_disk([{
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Para one",
            "footnotes": "",
        }], "Reading Refresh", self.doc_id)
        save_entries_to_disk([], "Reading Refresh", 0, self.doc_id)
        pdf_path = os.path.join(config.DOCS_DIR, self.doc_id, "source.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4\n%test\n")
        self.client = app_module.app.test_client()
        self._reset_translate_task()

    def tearDown(self):
        self._reset_translate_task()
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def _get_reading_script(self):
        chunks = []
        for filename in (
            "reading/core.js",
            "reading/navigation.js",
            "reading/page_editor.js",
            "reading/task_session.js",
            "reading/index.js",
        ):
            resp = self.client.get(f"/static/{filename}")
            self.assertEqual(resp.status_code, 200)
            chunks.append(resp.get_data(as_text=True))
            resp.close()
        return "\n".join(chunks)

    def _get_reading_css(self):
        resp = self.client.get("/static/reading/reading.css")
        self.assertEqual(resp.status_code, 200)
        try:
            return resp.get_data(as_text=True)
        finally:
            resp.close()

    def _reset_translate_task(self):
        with translate_runtime._translate_lock:
            translate_runtime._translate_task["running"] = False
            translate_runtime._translate_task["stop"] = False
            translate_runtime._translate_task["events"] = []
            translate_runtime._translate_task["doc_id"] = ""
            translate_runtime._translate_task["owner_token"] = 0
            translate_runtime._translate_task["log_relpath"] = ""

    def _save_range_pages(self, first_bp: int, last_bp: int):
        save_pages_to_disk([{
            "bookPage": bp,
            "fileIdx": bp - first_bp,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": f"Page {bp}",
            "footnotes": "",
        } for bp in range(first_bp, last_bp + 1)], "Reading Refresh", self.doc_id)

    def _save_pages(self, pages: list[dict]):
        payload = []
        for page in pages:
            item = {
                "bookPage": page["bookPage"],
                "fileIdx": page.get("fileIdx", max(int(page["bookPage"]) - 1, 0)),
                "imgW": page.get("imgW", 1000),
                "imgH": page.get("imgH", 1600),
                "markdown": page.get("markdown", ""),
                "footnotes": page.get("footnotes", ""),
            }
            for key in (
                "isPlaceholder",
                "textSource",
                "pdfPage",
                "printPage",
                "printPageLabel",
                "blocks",
                "fnBlocks",
            ):
                if key in page:
                    item[key] = page[key]
            payload.append(item)
        save_pages_to_disk(payload, "Reading Refresh", self.doc_id)

    def _save_page_entries_with_heading_and_footnotes(self, bp: int = 1):
        save_entries_to_disk([{
            "_pageBP": bp,
            "_model": "sonnet",
            "_page_entries": [
                {
                    "original": "Heading Original",
                    "translation": "标题译文",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 1,
                    "pages": str(bp),
                },
                {
                    "original": "Body Original",
                    "translation": "正文译文",
                    "footnotes": "1. 脚注原文甲",
                    "footnotes_translation": "1. 脚注译文甲",
                    "heading_level": 0,
                    "pages": str(bp),
                },
            ],
            "pages": str(bp),
        }], "Reading Refresh", 0, self.doc_id)

    def test_reading_route_reuses_page_and_entry_queries_within_single_request(self):
        self._save_range_pages(1, 3)
        page_queries = 0
        entry_queries = 0
        original_load_pages = storage.SQLiteRepository.load_pages
        original_list_entries = storage.SQLiteRepository.list_effective_translation_pages

        def counted_load_pages(repo, doc_id):
            nonlocal page_queries
            page_queries += 1
            return original_load_pages(repo, doc_id)

        def counted_list_entries(repo, doc_id):
            nonlocal entry_queries
            entry_queries += 1
            return original_list_entries(repo, doc_id)

        with (
            patch.object(storage.SQLiteRepository, "load_pages", new=counted_load_pages),
            patch.object(storage.SQLiteRepository, "list_effective_translation_pages", new=counted_list_entries),
        ):
            resp = self.client.get("/reading", query_string={"doc_id": self.doc_id, "bp": 1})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(page_queries, 1)
        self.assertEqual(entry_queries, 1)

    def test_load_pages_from_disk_does_not_write_back_repair_results(self):
        save_pages_to_disk([{
            "bookPage": 3,
            "fileIdx": 7,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Needs normalization",
            "footnotes": "",
        }], "Reading Refresh", self.doc_id)

        with (
            patch("persistence.sqlite_store.SingleDBRepository.replace_pages", side_effect=AssertionError("read path should stay read-only")),
            patch("persistence.sqlite_store.SingleDBRepository.remap_book_pages", side_effect=AssertionError("read path should stay read-only")),
            patch.object(storage, "update_doc_meta", side_effect=AssertionError("read path should stay read-only")),
        ):
            pages, _ = storage.load_pages_from_disk(self.doc_id)

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["markdown"], "Needs normalization")

    def test_reading_get_does_not_persist_cursor_or_switch_current_doc(self):
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Para one",
                "translation": "段落一",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
            }],
            "pages": "1",
        }], "Reading Refresh", 0, self.doc_id)

        with (
            patch.object(storage, "save_entry_cursor", side_effect=AssertionError("GET /reading should not write cursor")),
            patch.object(config, "set_current_doc", side_effect=AssertionError("GET routes should not switch current doc")),
        ):
            home_resp = self.client.get("/", query_string={"doc_id": self.doc_id})
            input_resp = self.client.get("/input", query_string={"doc_id": self.doc_id})
            reading_resp = self.client.get("/reading", query_string={"doc_id": self.doc_id, "bp": 1})

        self.assertEqual(home_resp.status_code, 200)
        self.assertEqual(input_resp.status_code, 200)
        self.assertEqual(reading_resp.status_code, 200)

    def test_request_cache_invalidates_after_page_write(self):
        self._save_range_pages(1, 2)
        page_queries = 0
        original_load_pages = storage.SQLiteRepository.load_pages

        def counted_load_pages(repo, doc_id):
            nonlocal page_queries
            page_queries += 1
            return original_load_pages(repo, doc_id)

        with patch.object(storage.SQLiteRepository, "load_pages", new=counted_load_pages):
            with app_module.app.test_request_context("/"):
                storage.load_pages_from_disk(self.doc_id)
                storage.load_pages_from_disk(self.doc_id)
                self.assertEqual(page_queries, 1)

                save_pages_to_disk([{
                    "bookPage": 1,
                    "fileIdx": 0,
                    "imgW": 1000,
                    "imgH": 1600,
                    "markdown": "Updated page",
                    "footnotes": "",
                }], "Reading Refresh", self.doc_id)
                pages, _ = storage.load_pages_from_disk(self.doc_id)

        self.assertEqual(page_queries, 2)
        self.assertEqual(pages[0]["markdown"], "Updated page")

    def test_request_cache_invalidates_after_entry_write(self):
        self._save_range_pages(1, 2)
        entry_queries = 0
        original_list_entries = storage.SQLiteRepository.list_effective_translation_pages

        def counted_list_entries(repo, doc_id):
            nonlocal entry_queries
            entry_queries += 1
            return original_list_entries(repo, doc_id)

        with patch.object(storage.SQLiteRepository, "list_effective_translation_pages", new=counted_list_entries):
            with app_module.app.test_request_context("/"):
                storage.load_entries_from_disk(self.doc_id)
                storage.load_entries_from_disk(self.doc_id)
                self.assertEqual(entry_queries, 1)

                save_entries_to_disk([{
                    "_pageBP": 1,
                    "_model": "sonnet",
                    "_page_entries": [],
                }], "Reading Refresh", 0, self.doc_id)
                entries, _, _ = storage.load_entries_from_disk(self.doc_id)

        self.assertEqual(entry_queries, 2)
        self.assertEqual([entry["_pageBP"] for entry in entries], [1])

    def test_translate_status_exposes_translated_bps_for_polling_recovery(self):
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
        }], "Reading Refresh", 0, self.doc_id)

        status = self.client.get("/translate_status", query_string={"doc_id": self.doc_id}).get_json()
        self.assertEqual(status["translated_bps"], [1])

    def test_start_translate_all_returns_doc_not_found_for_missing_doc(self):
        resp = self._post("/start_translate_all", data={
            "doc_id": "missing-doc-id",
            "doc_title": "Missing",
            "start_bp": 1,
        })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["error"], "doc_not_found")

    def test_translate_status_treats_literal_undefined_doc_id_as_missing_param(self):
        resp = self.client.get("/translate_status", query_string={"doc_id": "undefined"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["doc_id"], self.doc_id)

    def test_home_page_starts_from_first_visible_page_when_leading_placeholder_exists(self):
        self._save_pages([
            {"bookPage": 1, "fileIdx": 0, "markdown": "", "footnotes": "", "isPlaceholder": True, "textSource": "placeholder"},
            {"bookPage": 2, "fileIdx": 1, "markdown": "Page 2", "footnotes": ""},
            {"bookPage": 3, "fileIdx": 2, "markdown": "Page 3", "footnotes": ""},
        ])

        resp = self.client.get("/")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("从 PDF 第2页开始读", html)
        self.assertIn(f"/reading?bp=2&amp;auto=1&amp;start_bp=2&amp;doc_id={self.doc_id}", html)

    def test_home_page_renders_upload_toggles_off_by_default_and_current_mode_hint(self):
        resp = self.client.get("/")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="cleanupHeaderFooterToggle"', html)
        self.assertRegex(html, re.compile(r'id="cleanupHeaderFooterToggle"(?![^>]*checked)'))
        self.assertNotIn('id="autoVisualTocToggle"', html)
        self.assertIn("开启 FNM 模式", html)
        self.assertIn("FNM 模式（清理 + 视觉目录）", html)
        self.assertIn("当前为快速模式：解析完成后会直接进入标准阅读视图，并自动开始普通翻译。", html)

    def test_upload_preferences_endpoint_updates_homepage_defaults(self):
        resp = self._post_json(
            "/api/upload_preferences",
            json={"fnm_mode": True},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(get_upload_cleanup_headers_footers_enabled())
        self.assertTrue(get_upload_auto_visual_toc_enabled())

        home_resp = self.client.get("/")
        html = home_resp.get_data(as_text=True)

        self.assertIn('id="cleanupHeaderFooterToggle" checked', html)
        self.assertNotIn('id="autoVisualTocToggle"', html)

    def test_home_page_keeps_standard_entry_when_fnm_view_ready(self):
        update_doc_meta(self.doc_id, cleanup_headers_footers=True)
        SQLiteRepository().create_fnm_run(
            self.doc_id,
            status="done",
            page_count=1,
            section_count=1,
            note_count=1,
            unit_count=1,
        )

        resp = self.client.get("/")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("从 PDF 第1页开始读", html)
        self.assertNotIn(f"/reading?bp=1&amp;auto=1&amp;start_bp=1&amp;doc_id={self.doc_id}", html)
        self.assertNotIn(f"/reading?bp=1&amp;doc_id={self.doc_id}&amp;view=fnm", html)
        self.assertIn("FNM 模式不再提供预览视图", html)
        self.assertIn('id="fnmWorkflowCard"', html)
        self.assertIn("开始翻译", html)
        self.assertIn("继续 FNM 处理", html)
        self.assertIn("/fnm/full-flow", html)
        self.assertIn("导出章节包", html)

    def test_home_page_falls_back_to_existing_doc_when_current_doc_missing(self):
        save_pages_to_disk(
            [
                {
                    "bookPage": 1,
                    "fileIdx": 0,
                    "imgW": 100,
                    "imgH": 100,
                    "markdown": "Body one",
                    "footnotes": "",
                }
            ],
            "streaming-test.pdf",
            self.doc_id,
        )
        update_doc_meta(self.doc_id, cleanup_headers_footers=True)
        repo = SQLiteRepository()
        repo.set_app_state("current_doc_id", "missing-doc")

        resp = self.client.get("/")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"startDocStatusPolling('{self.doc_id}')", html)
        self.assertIn(f"startFnmWorkflowPolling('{self.doc_id}')", html)

    def test_home_page_renders_single_upload_card_and_glossary_actions(self):
        storage.save_auto_visual_toc_to_disk(
            self.doc_id,
            [
                {
                    "item_id": "visual-1",
                    "title": "第一章",
                    "depth": 0,
                    "file_idx": 0,
                    "visual_order": 1,
                }
            ],
        )
        resp = self.client.get("/")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="uploadCard"', html)
        self.assertIn("增强解析并重跑", html)
        self.assertIn("生成/重新生成自动视觉目录", html)
        self.assertIn("这里填写的是 PDF 页码，不是书籍原页码", html)
        self.assertIn("自动视觉目录调整", html)
        self.assertIn("保存自动视觉目录调整", html)
        self.assertIn("一键应用当前 offset", html)
        self.assertIn("用本条反推 offset", html)
        self.assertIn("删除此条", html)
        self.assertIn("拖拽调整顺序", html)
        self.assertIn("handleAutoVisualTocDrop", html)
        self.assertIn('class="modal-box modal-box-wide"', html)
        self.assertIn('class="auto-visual-toc-table"', html)

    def test_home_upload_area_click_guard_excludes_manual_toc_inputs(self):
        resp = self.client.get("/")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("function shouldOpenMainFilePickerFromUploadArea(target)", html)
        self.assertIn("target === tocPdfInput", html)
        self.assertIn("target === tocScreenshotInput", html)
        self.assertIn("target === glossaryInput", html)

    def test_upload_file_passes_fnm_mode_into_task_options(self):
        captured = {}

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                captured["target"] = target
                captured["args"] = args
                captured["daemon"] = daemon

            def start(self):
                return None

        with (
            patch.object(config, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_routes.threading, "Thread", FakeThread),
        ):
            default_resp = self.client.post(
                "/upload_file",
                data={
                    "_csrf_token": self._ensure_csrf_token(),
                    "file": (BytesIO(b"%PDF-1.4\n%default\n"), "default.pdf"),
                },
                content_type="multipart/form-data",
            )
            enabled_resp = self.client.post(
                "/upload_file",
                data={
                    "_csrf_token": self._ensure_csrf_token(),
                    "fnm_mode": "1",
                    "file": (BytesIO(b"%PDF-1.4\n%enabled\n"), "enabled.pdf"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(default_resp.status_code, 200)
        self.assertEqual(enabled_resp.status_code, 200)
        default_task_id = default_resp.get_json()["task_id"]
        enabled_task_id = enabled_resp.get_json()["task_id"]
        self.addCleanup(task_registry.remove_task, default_task_id)
        self.addCleanup(task_registry.remove_task, enabled_task_id)
        default_task = task_registry.get_task(default_task_id)
        enabled_task = task_registry.get_task(enabled_task_id)
        self.addCleanup(lambda: os.path.exists(default_task["file_path"]) and os.unlink(default_task["file_path"]))
        self.addCleanup(lambda: os.path.exists(enabled_task["file_path"]) and os.unlink(enabled_task["file_path"]))

        self.assertFalse(default_task["options"]["clean_header_footer"])
        self.assertTrue(enabled_task["options"]["clean_header_footer"])
        self.assertFalse(default_task["options"]["auto_visual_toc"])
        self.assertTrue(enabled_task["options"]["auto_visual_toc"])
        self.assertTrue(callable(captured["target"]))
        self.assertEqual(captured["args"], (enabled_task_id,))
        self.assertTrue(captured["daemon"])

    def test_upload_file_passes_manual_toc_pdf_into_task_options(self):
        captured = {}

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                captured["target"] = target
                captured["args"] = args
                captured["daemon"] = daemon

            def start(self):
                return None

        with (
            patch.object(config, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_routes.threading, "Thread", FakeThread),
        ):
            resp = self.client.post(
                "/upload_file",
                data={
                    "_csrf_token": self._ensure_csrf_token(),
                    "file": (BytesIO(b"%PDF-1.4\n%book\n"), "book.pdf"),
                    "toc_pdf": (BytesIO(b"%PDF-1.4\n%toc\n"), "目录.pdf"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 200)
        task_id = resp.get_json()["task_id"]
        self.addCleanup(task_registry.remove_task, task_id)
        task = task_registry.get_task(task_id)
        self.addCleanup(lambda: os.path.exists(task["file_path"]) and os.unlink(task["file_path"]))
        toc_pdf = task["options"].get("toc_visual_pdf_upload") or {}
        if toc_pdf.get("path"):
            self.addCleanup(lambda: os.path.exists(toc_pdf["path"]) and os.unlink(toc_pdf["path"]))

        self.assertTrue(task["options"]["auto_visual_toc"])
        self.assertEqual(toc_pdf.get("filename"), "目录.pdf")
        self.assertTrue(os.path.exists(toc_pdf.get("path", "")))
        self.assertTrue(callable(captured["target"]))
        self.assertEqual(captured["args"], (task_id,))
        self.assertTrue(captured["daemon"])

    def test_upload_file_passes_glossary_upload_into_task_options(self):
        captured = {}

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                captured["target"] = target
                captured["args"] = args
                captured["daemon"] = daemon

            def start(self):
                return None

        csv_bytes = "term,defn\nhello,你好\nworld,世界\n".encode("utf-8")

        with (
            patch.object(config, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_routes.threading, "Thread", FakeThread),
        ):
            resp = self.client.post(
                "/upload_file",
                data={
                    "_csrf_token": self._ensure_csrf_token(),
                    "file": (BytesIO(b"%PDF-1.4\n%book\n"), "book.pdf"),
                    "glossary_file": (BytesIO(csv_bytes), "词典.csv"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn("task_id", payload, msg=payload)
        task_id = payload["task_id"]
        self.addCleanup(task_registry.remove_task, task_id)
        task = task_registry.get_task(task_id)
        self.addCleanup(lambda: os.path.exists(task["file_path"]) and os.unlink(task["file_path"]))
        glossary_upload = task["options"].get("glossary_upload") or {}
        if glossary_upload.get("path"):
            self.addCleanup(lambda: os.path.exists(glossary_upload["path"]) and os.unlink(glossary_upload["path"]))

        self.assertEqual(glossary_upload.get("filename"), "词典.csv")
        self.assertTrue(os.path.exists(glossary_upload.get("path", "")))
        self.assertTrue(callable(captured["target"]))
        self.assertEqual(captured["args"], (task_id,))
        self.assertTrue(captured["daemon"])

    def test_upload_file_rejects_unsupported_glossary_extension(self):
        with patch.object(config, "get_paddle_token", return_value="fake-paddle-token"):
            resp = self.client.post(
                "/upload_file",
                data={
                    "_csrf_token": self._ensure_csrf_token(),
                    "file": (BytesIO(b"%PDF-1.4\n%book\n"), "book.pdf"),
                    "glossary_file": (BytesIO(b"not a glossary"), "glossary.txt"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn("error", payload, msg=payload)
        self.assertIn("词典", payload["error"])

    def test_upload_manual_toc_pdf_for_existing_doc_saves_file_and_starts_visual_toc(self):
        captured = {}

        def _start_auto_visual_toc(doc_id, pdf_path, model_spec=None):
            captured["doc_id"] = doc_id
            captured["pdf_path"] = pdf_path
            captured["model_id"] = getattr(model_spec, "model_id", "")
            return object()

        with (
            patch.object(document_tasks, "start_auto_visual_toc_for_doc", side_effect=_start_auto_visual_toc),
        ):
            resp = self._post(
                "/api/doc/upload_toc_visual_source",
                data={
                    "doc_id": self.doc_id,
                    "toc_pdf": (BytesIO(b"%PDF-1.4\n%toc-only\n"), "目录.pdf"),
                },
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["doc_id"], self.doc_id)
        self.assertEqual(payload["input_mode"], "manual_pdf")
        self.assertEqual(payload["page_count"], 1)
        self.assertEqual(captured["doc_id"], self.doc_id)
        saved_path = os.path.join(config.get_doc_dir(self.doc_id), "toc_visual_source.pdf")
        self.assertTrue(os.path.exists(saved_path))

    def test_reparse_enhanced_clears_translations_and_uses_cleanup_mode(self):
        save_entries_to_disk(
            [
                {
                    "_pageBP": 1,
                    "_model": "qwen-plus",
                    "_page_entries": [{"original": "A", "translation": "甲"}],
                    "pages": "1",
                }
            ],
            "Reading Refresh",
            0,
            self.doc_id,
        )
        captured = {}

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                captured["target"] = target
                captured["args"] = args
                captured["daemon"] = daemon

            def start(self):
                return None

        with (
            patch.object(config, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_routes.threading, "Thread", FakeThread),
        ):
            resp = self._post("/api/doc/reparse_enhanced", data={"doc_id": self.doc_id})

        self.assertEqual(resp.status_code, 200)
        task_id = resp.get_json()["task_id"]
        self.addCleanup(task_registry.remove_task, task_id)
        self.assertEqual(load_entries_from_disk(self.doc_id)[0], [])
        self.assertTrue(task_registry.get_task(task_id)["options"]["clean_header_footer"])
        self.assertTrue(task_registry.get_task(task_id)["options"]["auto_visual_toc"])
        self.assertEqual(get_doc_meta(self.doc_id).get("cleanup_headers_footers"), 1)
        self.assertEqual(get_doc_meta(self.doc_id).get("auto_visual_toc_enabled"), 1)
        self.assertEqual(captured["args"][1], self.doc_id)

    def test_run_visual_toc_keeps_translations_and_enables_doc_flag(self):
        save_entries_to_disk(
            [
                {
                    "_pageBP": 1,
                    "_model": "qwen-plus",
                    "_page_entries": [{"original": "A", "translation": "甲"}],
                    "pages": "1",
                }
            ],
            "Reading Refresh",
            0,
            self.doc_id,
        )

        with patch.object(document_tasks, "start_auto_visual_toc_for_doc") as visual_mock:
            resp = self._post("/api/doc/run_visual_toc", data={"doc_id": self.doc_id})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        self.assertEqual(len(load_entries_from_disk(self.doc_id)[0]), 1)
        self.assertTrue(get_doc_meta(self.doc_id).get("auto_visual_toc_enabled"))
        visual_mock.assert_called_once()

    def test_reparse_routes_only_inherit_document_fnm_mode(self):
        update_doc_meta(self.doc_id, cleanup_headers_footers=False, auto_visual_toc_enabled=True)
        captured = []

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                captured.append({"target": target, "args": args, "daemon": daemon})

            def start(self):
                return None

        with (
            patch.object(config, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_routes.threading, "Thread", FakeThread),
        ):
            reparse_resp = self._post("/reparse", data={"doc_id": self.doc_id})
            page_resp = self._post("/reparse_page/1", data={"doc_id": self.doc_id})

        self.assertEqual(reparse_resp.status_code, 200)
        self.assertEqual(page_resp.status_code, 200)
        reparse_task_id = reparse_resp.get_json()["task_id"]
        page_task_id = page_resp.get_json()["task_id"]
        self.addCleanup(task_registry.remove_task, reparse_task_id)
        self.addCleanup(task_registry.remove_task, page_task_id)
        self.assertFalse(task_registry.get_task(reparse_task_id)["options"]["clean_header_footer"])
        self.assertFalse(task_registry.get_task(page_task_id)["options"]["clean_header_footer"])
        self.assertFalse(task_registry.get_task(reparse_task_id)["options"]["auto_visual_toc"])
        self.assertFalse(task_registry.get_task(page_task_id)["options"]["auto_visual_toc"])

    def test_process_file_runs_visual_toc_sync_before_fnm_when_fnm_enabled(self):
        fd, file_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4\n%visual-toc\n")
        task_id = "uploadvisual01"
        task_registry.create_task(
            task_id,
            file_path,
            "upload-visual.pdf",
            0,
            options={"clean_header_footer": True, "auto_visual_toc": True},
        )
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [{
                "text": "OCR 正文",
                "x": 12,
                "bbox": [0, 0, 50, 20],
                "label": "text",
                "is_meta": False,
                "heading_level": 0,
            }],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "OCR 正文",
        }

        with (
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "extract_pdf_text", return_value=[]),
            patch.object(document_tasks, "_annotate_note_scans", side_effect=lambda pages, **kwargs: pages),
            patch.object(document_tasks.text_processing, "clean_header_footer", return_value={"pages": [ocr_page], "log": []}) as clean_mock,
            patch.object(document_tasks, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_tasks, "extract_pdf_toc", return_value=[]),
            patch.object(document_tasks, "extract_pdf_toc_from_links", return_value=[]),
            patch.object(document_tasks, "run_auto_visual_toc_for_doc", return_value={"status": "ready", "count": 2}) as visual_toc_mock,
            patch.object(document_tasks, "run_fnm_pipeline", return_value={"ok": True, "section_count": 1, "note_count": 1, "unit_count": 1}) as fnm_mock,
            patch.object(document_tasks, "start_fnm_translate_task", return_value=False),
        ):
            document_tasks.process_file(task_id)

        visual_toc_mock.assert_called_once()
        fnm_mock.assert_called_once()
        clean_mock.assert_called_once()

    def test_process_file_manual_toc_pdf_upload_does_not_break_doc_meta_update(self):
        fd, file_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(b"%PDF-1.4\n%upload\n")
        manual_fd, manual_toc_path = tempfile.mkstemp(suffix=".pdf")
        os.close(manual_fd)
        with open(manual_toc_path, "wb") as f:
            f.write(b"%PDF-1.4\n%manual-toc\n")
        task_id = "uploadmanual01"
        task_registry.create_task(
            task_id,
            file_path,
            "upload-manual.pdf",
            0,
            options={
                "clean_header_footer": False,
                "auto_visual_toc": False,
                "toc_visual_pdf_upload": {
                    "path": manual_toc_path,
                    "filename": "manual-toc.pdf",
                },
            },
        )
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [{
                "text": "OCR 正文",
                "x": 10,
                "bbox": [0, 0, 100, 30],
                "label": "text",
                "is_meta": False,
                "heading_level": 0,
            }],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "OCR 正文",
        }

        with (
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "extract_pdf_text", return_value=[]),
            patch.object(document_tasks, "_annotate_note_scans", side_effect=lambda pages, **kwargs: pages),
            patch.object(document_tasks, "get_paddle_token", return_value="fake-paddle-token"),
            patch.object(document_tasks, "extract_pdf_toc", return_value=[]),
            patch.object(document_tasks, "extract_pdf_toc_from_links", return_value=[]),
            patch.object(document_tasks, "run_auto_visual_toc_for_doc", return_value={"status": "ready", "count": 1}),
        ):
            document_tasks.process_file(task_id)

        events, _exists = task_registry.get_task_events(task_id, 0)
        done_events = [payload for event_type, payload in events if event_type == "done"]
        self.assertTrue(done_events, msg=events)
        self.assertFalse([payload for event_type, payload in events if event_type == "error_msg"], msg=events)
        uploaded_doc_id = str(done_events[-1].get("doc_id") or "")
        self.assertTrue(uploaded_doc_id)
        self.assertTrue(get_doc_meta(uploaded_doc_id).get("auto_visual_toc_enabled"))

    def test_reading_page_normalizes_body_markers_to_superscript_and_footnote_items_to_brackets(self):
        save_pages_to_disk([{
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "OCR [4] preview and [^5] preview and ⁶ preview",
            "footnotes": "",
        }], "Reading Refresh", self.doc_id)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Body [1] marker and [^2] marker and ³ marker",
                "translation": "译文 [1] 标记和 [^2] 标记以及 ³ 标记",
                "footnotes": "1. Note one\n[^2] Note two\n3) Note three",
                "footnotes_translation": "1. 注释一\n[^2] 注释二\n3) 注释三",
                "heading_level": 0,
                "pages": "1",
            }],
            "pages": "1",
        }], "Reading Refresh", 0, self.doc_id)

        resp = self.client.get("/reading?bp=1&orig=1&pdf=0&usage=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Body ¹ marker and ² marker and ³ marker", html)
        self.assertIn("译文 ¹ 标记和 ² 标记以及 ³ 标记", html)
        self.assertIn("[1] Note one", html)
        self.assertIn("[2] Note two", html)
        self.assertIn("[3] Note three", html)
        self.assertNotIn("[^2] Note two", html)
        self.assertNotIn("1. Note one", html)

    def test_reading_page_shows_unresolved_visual_toc_items_with_pdf_page_editor(self):
        self._save_pages([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
            {"bookPage": 2, "fileIdx": 1, "markdown": "Page 2", "footnotes": ""},
            {"bookPage": 3, "fileIdx": 2, "markdown": "Page 3", "footnotes": ""},
        ])
        storage.save_auto_visual_toc_to_disk(
            self.doc_id,
            [
                {
                    "item_id": "visual-1",
                    "title": "可跳转章节",
                    "depth": 0,
                    "file_idx": 1,
                    "visual_order": 1,
                },
                {
                    "item_id": "visual-2",
                    "title": "待补录章节",
                    "depth": 0,
                    "book_page": 12,
                    "visual_order": 2,
                },
            ],
        )
        update_doc_meta(self.doc_id, toc_visual_status="needs_offset")

        resp = self.client.get(f"/reading?bp=1&doc_id={self.doc_id}&orig=0&pdf=0&usage=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="tocBtn"', html)
        self.assertIn("可跳转章节", html)
        self.assertIn("待补录章节", html)
        self.assertIn("未定位目录项", html)
        self.assertIn("这里填写的是 PDF 页码，不是书籍原页码", html)
        self.assertIn('data-toc-item-id="visual-2"', html)
        self.assertIn("/api/toc/resolve_visual_item", html)

    def test_reading_placeholder_preview_normalizes_markers_for_body_and_page_footnotes(self):
        save_pages_to_disk([{
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Preview [7] marker and [^8] marker and ⁹ marker",
            "footnotes": "7. Preview note\n[^8] Preview second note\n9) Preview third note",
        }], "Reading Refresh", self.doc_id)
        save_entries_to_disk([], "Reading Refresh", 0, self.doc_id)

        resp = self.client.get("/reading?bp=1&orig=0&pdf=0&usage=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Preview ⁷ marker and ⁸ marker and ⁹ marker", html)
        self.assertIn("[7] Preview note", html)
        self.assertIn("[8] Preview second note", html)
        self.assertIn("[9] Preview third note", html)
        self.assertNotIn("7. Preview note", html)
        self.assertNotIn("[^8] Preview second note", html)

    def test_home_page_requests_stop_for_active_translate_task(self):
        tasks._save_translate_state(
            self.doc_id,
            running=True,
            stop_requested=False,
            phase="running",
            total_pages=3,
            done_pages=1,
            processed_pages=1,
            pending_pages=2,
            current_bp=2,
            current_page_idx=2,
        )
        with translate_runtime._translate_lock:
            translate_runtime._translate_task["running"] = True
            translate_runtime._translate_task["stop"] = False
            translate_runtime._translate_task["events"] = []
            translate_runtime._translate_task["doc_id"] = self.doc_id

        resp = self.client.get("/")
        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(snapshot["running"])
        self.assertTrue(snapshot["stop_requested"])
        self.assertEqual(snapshot["phase"], "stopping")

    def test_reading_route_redirects_placeholder_page_to_next_visible_page(self):
        self._save_pages([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
            {"bookPage": 2, "fileIdx": 1, "markdown": "", "footnotes": "", "isPlaceholder": True, "textSource": "placeholder"},
            {"bookPage": 3, "fileIdx": 2, "markdown": "Page 3", "footnotes": ""},
            {"bookPage": 4, "fileIdx": 3, "markdown": "Page 4", "footnotes": ""},
        ])

        resp = self.client.get(f"/reading?bp=2&doc_id={self.doc_id}", follow_redirects=True)
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("PDF 第2页为空白页，已跳转到 PDF 第3页。", html)
        self.assertIn("PDF 第3页 / 第4页", html)

    def test_reading_route_redirects_trailing_placeholder_page_to_previous_visible_page(self):
        self._save_pages([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
            {"bookPage": 2, "fileIdx": 1, "markdown": "Page 2", "footnotes": ""},
            {"bookPage": 3, "fileIdx": 2, "markdown": "", "footnotes": "", "isPlaceholder": True, "textSource": "placeholder"},
        ])

        resp = self.client.get(f"/reading?bp=3&doc_id={self.doc_id}", follow_redirects=True)
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("PDF 第3页为空白页，已跳转到 PDF 第2页。", html)
        self.assertIn("PDF 第2页 / 第2页", html)

    def test_reading_page_hides_placeholder_pages_from_progress_and_pdf_panel(self):
        self._save_pages([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
            {"bookPage": 2, "fileIdx": 1, "markdown": "", "footnotes": "", "isPlaceholder": True, "textSource": "placeholder"},
            {"bookPage": 3, "fileIdx": 2, "markdown": "Page 3", "footnotes": ""},
            {"bookPage": 4, "fileIdx": 3, "markdown": "", "footnotes": "", "isPlaceholder": True, "textSource": "placeholder"},
            {"bookPage": 5, "fileIdx": 4, "markdown": "Page 5", "footnotes": ""},
        ])

        resp = self.client.get(f"/reading?bp=1&doc_id={self.doc_id}")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-page-bp="1"', html)
        self.assertIn('data-page-bp="3"', html)
        self.assertIn('data-page-bp="5"', html)
        self.assertNotIn('data-page-bp="2"', html)
        self.assertNotIn('data-page-bp="4"', html)
        self.assertIn('data-pdf-bp="1"', html)
        self.assertIn('data-pdf-bp="3"', html)
        self.assertIn('data-pdf-bp="5"', html)
        self.assertNotIn('data-pdf-bp="2"', html)
        self.assertNotIn('data-pdf-bp="4"', html)
        self.assertIn(f'/reading?bp=3&amp;doc_id={self.doc_id}&amp;usage=0&amp;orig=0&amp;pdf=0', html)

    def test_start_translate_all_normalizes_placeholder_start_page_to_next_visible_page(self):
        self._save_pages([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
            {"bookPage": 2, "fileIdx": 1, "markdown": "", "footnotes": "", "isPlaceholder": True, "textSource": "placeholder"},
            {"bookPage": 3, "fileIdx": 2, "markdown": "Page 3", "footnotes": ""},
        ])

        with (
            patch.object(storage, "get_translate_args", return_value={"api_key": "fake-key", "provider": "qwen"}),
            patch.object(translate_launch, "start_translate_task", return_value=True) as start_mock,
        ):
            resp = self._post("/start_translate_all", data={
                "doc_id": self.doc_id,
                "doc_title": "Reading Refresh",
                "start_bp": 2,
            })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["start_bp"], 3)
        start_mock.assert_called_once_with(self.doc_id, 3, "Reading Refresh")

    def test_translate_status_filters_placeholder_failures_and_uses_visible_page_totals(self):
        self._save_pages([
            {"bookPage": 1, "fileIdx": 0, "markdown": "Page 1", "footnotes": ""},
            {"bookPage": 2, "fileIdx": 1, "markdown": "", "footnotes": "", "isPlaceholder": True, "textSource": "placeholder"},
            {"bookPage": 3, "fileIdx": 2, "markdown": "Page 3", "footnotes": ""},
            {"bookPage": 4, "fileIdx": 3, "markdown": "", "footnotes": "", "isPlaceholder": True, "textSource": "placeholder"},
            {"bookPage": 5, "fileIdx": 4, "markdown": "Page 5", "footnotes": ""},
        ])
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
        }], "Reading Refresh", 0, self.doc_id)
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            start_bp=1,
            total_pages=5,
            done_pages=1,
            processed_pages=3,
            pending_pages=2,
            current_bp=2,
            current_page_idx=2,
            failed_bps=[2, 4],
            failed_pages=[
                {"bp": 2, "error": "第2页未找到内容"},
                {"bp": 4, "error": "第4页未找到内容"},
            ],
        )

        status = self.client.get("/translate_status", query_string={"doc_id": self.doc_id}).get_json()

        self.assertEqual(status["translated_bps"], [1])
        self.assertEqual(status["failed_bps"], [])
        self.assertEqual(status["total_pages"], 3)
        self.assertEqual(status["done_pages"], 1)
        self.assertEqual(status["processed_pages"], 1)
        self.assertEqual(status["pending_pages"], 2)

    def test_set_model_treats_literal_undefined_doc_id_as_missing_param(self):
        resp = self._post(
            "/set_model/deepseek-chat",
            data={"doc_id": "undefined", "next": "reading"},
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(get_current_doc_id(), self.doc_id)
        self.assertIn(f"/reading?doc_id={self.doc_id}", resp.location)

    def test_pdf_preview_routes_treat_literal_undefined_doc_id_as_missing_param(self):
        with patch("document.pdf_extract.render_pdf_page", return_value=b"fake-png-bytes"):
            file_resp = self.client.get("/pdf_file", query_string={"doc_id": "undefined"})
            page_resp = self.client.get("/pdf_page/0", query_string={"doc_id": "undefined"})

        try:
            self.assertEqual(file_resp.status_code, 200)
            self.assertEqual(file_resp.mimetype, "application/pdf")
            self.assertTrue(file_resp.get_data().startswith(b"%PDF-1.4"))
            self.assertEqual(page_resp.status_code, 200)
            self.assertEqual(page_resp.mimetype, "image/png")
            self.assertEqual(page_resp.get_data(), b"fake-png-bytes")
        finally:
            file_resp.close()
            page_resp.close()

    def test_reading_page_degrades_orphan_ocr_images_in_preview(self):
        save_pages_to_disk([{
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": '<div style="text-align: center;"><img src="imgs/img_in_image_box_3_107_784_1005.jpg" alt="Image" width="99%" /></div>\n\nHOW CULTURE MATTERS',
            "footnotes": "",
        }], "Reading Refresh", self.doc_id)
        save_entries_to_disk([], "Reading Refresh", 0, self.doc_id)

        resp = self.client.get("/reading?bp=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('src="imgs/', html)
        self.assertNotIn("img_in_image_box", html)
        self.assertNotIn("&lt;img", html)
        self.assertIn("HOW CULTURE MATTERS", html)

    def test_reading_page_degrades_orphan_ocr_images_in_original_html(self):
        save_pages_to_disk([{
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Body Original",
            "footnotes": "",
        }], "Reading Refresh", self.doc_id)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": '<div style="text-align: center;"><img src="imgs/img_in_image_box_9_9_99_99.jpg" alt="Plate 1" width="45%" /></div>\n\nBody Original',
                "translation": "正文译文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
            }],
            "pages": "1",
        }], "Reading Refresh", 0, self.doc_id)

        resp = self.client.get("/reading?bp=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('src="imgs/', html)
        self.assertNotIn("img_in_image_box", html)
        self.assertIn("插图：Plate 1", html)

    def test_reading_page_embeds_controlled_commit_refresh_guards(self):
        self._save_range_pages(1, 2)
        resp = self.client.get("/reading?bp=1&auto=1")
        html = resp.get_data(as_text=True)
        script = self._get_reading_script()
        css = self._get_reading_css()

        self.assertEqual(resp.status_code, 200)
        self.assertIn('/static/reading/index.js', html)
        self.assertIn('id="translationSessionCard"', html)
        self.assertIn('id="translationSessionToggleBtn"', html)
        self.assertIn('id="translationSessionDetails"', html)
        self.assertIn('id="pdfScrollContainer"', html)
        self.assertIn('class="pdf-page-item"', html)
        self.assertIn("data-pdf-src=", html)
        self.assertIn("var store = {", script)
        self.assertIn("pendingCommittedRefreshBp: null", script)
        self.assertIn("function scheduleCommittedPageRefresh(bp)", script)
        self.assertIn("function maybeRefreshCommittedCurrentPage(state)", script)
        self.assertIn("manualNavigationInFlight: false", script)
        self.assertIn("function dispatch(action, payload)", script)
        self.assertIn("function handleReadingNavClick(event, bp)", script)
        self.assertIn("function setCurrentReadingBp(bp)", script)
        self.assertIn("function setCurrentPdfBp(bp)", script)
        self.assertIn("function getVisiblePdfBp()", script)
        self.assertIn("function setVisiblePdfBp(bp, source)", script)
        self.assertIn("function syncReadingBpFromPdf(source)", script)
        self.assertIn("function syncPdfBpFromReading(source)", script)
        self.assertIn("function getPdfRenderScale(bp)", script)
        self.assertIn("function buildPdfPageSrc(pageEl)", script)
        self.assertIn("function syncPdfImageSrc(pageEl, img)", script)
        self.assertIn("Math.max(2, window.devicePixelRatio || 1)", script)
        self.assertIn("function initPdfVirtualScroll()", script)
        self.assertIn("function updatePdfVirtualWindow(centerBp)", script)
        self.assertIn("function mountPdfImage(pageEl)", script)
        self.assertIn("function unmountPdfImage(pageEl)", script)
        self.assertIn("function setupPdfScrollObserver()", script)
        self.assertIn("new IntersectionObserver(", script)
        self.assertIn("function maybeRestoreHighlight()", script)
        self.assertIn("function suppressObserverNavigation(ms)", script)
        self.assertIn("function isObserverNavigationSuppressed()", script)
        self.assertIn("function alignPdfToReading(options)", script)
        self.assertIn("alignPdfToReading({", script)
        self.assertIn("var translateSessionActivated = !!BOOTSTRAP.showInitialTaskSnapshot;", script)
        self.assertIn("function shouldHydrateTranslateDraft(state)", script)
        self.assertIn("function hasRestorableDraft(state)", script)
        self.assertIn("var VIRTUAL_WINDOW_RADIUS = Number(BOOTSTRAP.pdfVirtualWindowRadius || 0);", script)
        self.assertIn("var VIRTUAL_SCROLL_MIN_PAGES = Number(BOOTSTRAP.pdfVirtualScrollMinPages || 0);", script)
        self.assertIn("state.processed_pages", script)
        self.assertIn("partial_failed: '部分完成'", script)
        self.assertIn("state.phase === 'partial_failed'", script)
        self.assertIn("state.resume_bp", script)
        self.assertIn("function getResumeActionLabel(state)", script)
        self.assertIn("translateES.addEventListener('stream_usage'", script)
        self.assertIn("function applyStreamUsage(eventData)", script)
        self.assertIn("function getUsageSampleStats()", script)
        self.assertNotIn("function retryDraftPage()", script)
        self.assertNotIn("function retryDraftParagraph(paraIdx)", script)
        self.assertIn('id="floatingPageNav"', html)
        self.assertIn('class="floating-page-nav-btn next"', html)
        self.assertIn('floating-page-nav-btn prev', html)
        self.assertIn('/static/reading/reading.css', html)
        self.assertIn("background: rgba(44, 36, 22, 0.5);", css)
        self.assertIn("position: fixed;", css)
        self.assertIn("function getReadingUiStateParams()", script)
        self.assertIn("url.searchParams.set('orig'", script)
        self.assertIn("url.searchParams.set('pdf'", script)
        self.assertIn("function applyOriginalVisibilityState()", script)
        self.assertIn("function applyPdfPanelVisibilityState()", script)

    def test_reading_page_preserves_ui_state_in_initial_store_and_nav_links(self):
        self._save_range_pages(1, 2)

        resp = self.client.get("/reading?bp=1&usage=0&orig=0&pdf=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("showOriginal: false,", html)
        self.assertIn("pdfVisible: false,", html)
        self.assertIn("currentBp: 1,", html)
        self.assertIn(f'currentDocId: "{self.doc_id}"', html)
        self.assertNotIn("sideBySide", html)
        self.assertIn(f'/reading?bp=2&amp;doc_id={self.doc_id}&amp;usage=0&amp;orig=0&amp;pdf=0', html)
        self.assertIn('class="pdf-panel" id="pdfPanel" style="display:none;"', html)
        self.assertIn('class="pdf-toggle-btn" id="pdfToggleBtn"', html)

    def test_reading_page_guards_request_doc_id_before_fetching(self):
        self._save_range_pages(1, 2)

        resp = self.client.get(f"/reading?bp=1&doc_id={self.doc_id}")
        html = resp.get_data(as_text=True)
        script = self._get_reading_script()

        self.assertEqual(resp.status_code, 200)
        self.assertIn('/static/reading/index.js', html)
        self.assertIn("function requireReadingDocId(actionLabel, onMissing)", script)
        self.assertIn("raw === 'undefined' || raw === 'null' || raw === 'None'", script)
        self.assertNotIn("form.append('doc_id', currentDocId);", script)
        self.assertIn("var docId = requireReadingDocId('刷新翻译状态');", script)
        self.assertIn("var docId = requireReadingDocId('刷新阅读视图状态');", script)
        self.assertIn("var docId = requireReadingDocId('启动翻译'", script)
        self.assertIn("var docId = requireReadingDocId('打开页编辑器');", script)
        self.assertIn("var docId = requireReadingDocId('订阅翻译进度');", script)
        self.assertIn("var docId = requireReadingDocId('停止翻译'", script)

    def test_reading_page_does_not_render_layout_controls(self):
        self._save_range_pages(1, 1)
        self._save_page_entries_with_heading_and_footnotes()

        resp = self.client.get("/reading?bp=1&usage=0&orig=0&pdf=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("原译排列", html)
        self.assertNotIn("上下排列", html)
        self.assertNotIn("左右排列", html)
        self.assertNotIn("layoutModeControl", html)
        self.assertNotIn("layoutStackBtn", html)
        self.assertNotIn("layoutSideBtn", html)
        self.assertNotIn("setLayoutMode", html)
        self.assertNotIn("applyLayoutState", html)

    def test_reading_page_renders_single_stacked_layout_for_heading_body_and_footnotes(self):
        self._save_range_pages(1, 1)
        self._save_page_entries_with_heading_and_footnotes()

        resp = self.client.get("/reading?bp=1&usage=0&orig=1&pdf=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('class="reading-layout-stack heading-layout-stack"', html)
        self.assertIn('class="reading-layout-stack"', html)
        self.assertIn('class="reading-layout-stack page-footnotes-stack"', html)
        self.assertNotIn('data-reading-layout="side"', html)
        self.assertNotIn('class="sbs-view', html)
        self.assertNotIn('class="stk-view', html)

    def test_reading_page_keeps_pdf_panel_without_layout_controls(self):
        self._save_range_pages(1, 1)
        self._save_page_entries_with_heading_and_footnotes()

        resp = self.client.get("/reading?bp=1&usage=0&orig=1&pdf=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('class="reading-main-layout with-pdf"', html)
        self.assertIn("PDF 原文", html)
        self.assertNotIn("原译排列", html)
        self.assertNotIn("上下排列", html)
        self.assertNotIn("左右排列", html)

    def test_reading_page_syncs_pdf_resizer_visibility_with_panel_state(self):
        self._save_range_pages(1, 2)

        resp = self.client.get("/reading?bp=1&usage=0&orig=0&pdf=0")
        html = resp.get_data(as_text=True)
        script = self._get_reading_script()

        self.assertEqual(resp.status_code, 200)
        self.assertIn("id=\"pdfResizer\"", html)
        self.assertIn("var resizer = document.getElementById('pdfResizer');", script)
        self.assertIn("resizer.style.display = store.ui.pdfVisible ? '' : 'none';", script)

    def test_reading_page_refreshes_pdf_layout_during_resizer_drag(self):
        self._save_range_pages(1, 2)

        resp = self.client.get("/reading?bp=1&pdf=1")
        html = resp.get_data(as_text=True)
        script = self._get_reading_script()

        self.assertEqual(resp.status_code, 200)
        self.assertIn('/static/reading/index.js', html)
        self.assertIn("function applyPdfPagePlaceholders(options)", script)
        self.assertRegex(
            script,
            re.compile(
                r"window\.addEventListener\('mousemove', function\(e\) \{[\s\S]*?"
                r"applyPdfPagePlaceholders\(\{ syncImageSrc: false \}\);",
                re.S,
            ),
        )
        self.assertRegex(
            script,
            re.compile(
                r"window\.addEventListener\('mouseup', function\(e\) \{[\s\S]*?"
                r"applyPdfPagePlaceholders\(\);",
                re.S,
            ),
        )

    def test_static_css_keeps_pdf_resizer_pinned_to_viewport(self):
        resp = self.client.get("/static/style.css")
        try:
            css = resp.get_data(as_text=True)

            self.assertEqual(resp.status_code, 200)
            self.assertRegex(
                css,
                re.compile(
                    r"\.resizer\s*\{[^}]*position:\s*sticky;[^}]*top:\s*0;[^}]*height:\s*100vh;",
                    re.S,
                ),
            )
        finally:
            resp.close()

    def test_static_css_contains_pdf_horizontal_overscroll(self):
        resp = self.client.get("/static/style.css")
        try:
            css = resp.get_data(as_text=True)

            self.assertEqual(resp.status_code, 200)
            self.assertRegex(
                css,
                re.compile(
                    r"\.pdf-img-container\s*\{[^}]*overflow-x:\s*auto;[^}]*overscroll-behavior-x:\s*none;",
                    re.S,
                ),
            )
        finally:
            resp.close()

    def test_reading_page_exposes_force_ocr_reparse_action_in_placeholder_and_content(self):
        self._save_range_pages(1, 1)

        resp = self.client.get("/reading?bp=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("强制 OCR 重解析本页", html)
        self.assertIn("不走 PDF 文字层", html)
        self.assertIn("会自动重译本页", html)

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
        }], "Reading Refresh", 0, self.doc_id)

        resp = self.client.get("/reading?bp=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("强制 OCR 重解析本页", html)
        self.assertIn("覆盖当前页译文", html)
        self.assertNotIn("不走 PDF 文字层", html)

    def test_reparse_single_page_forces_ocr_text_without_pdf_merge_and_retranslates(self):
        task_id = "reparseocr01"
        pdf_path = os.path.join(config.DOCS_DIR, self.doc_id, "source.pdf")
        task_registry.create_task(task_id, pdf_path, "Reading Refresh", 0)
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [{
                "text": "OCR 正文",
                "x": 12,
                "bbox": [0, 0, 50, 20],
                "label": "text",
                "is_meta": False,
                "heading_level": 0,
            }],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "",
        }
        translated_entry = {
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "OCR 正文",
                "translation": "重译后的正文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
                "_status": "done",
                "_error": "",
            }],
            "_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1},
            "pages": "1",
        }

        with (
            patch("document.pdf_extract.extract_single_page_pdf", return_value=b"%PDF-1.4\n%page\n"),
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "clean_header_footer", side_effect=lambda pages, on_progress=None: {"pages": pages, "log": []}),
            patch.object(document_tasks, "get_model_key", return_value="sonnet"),
            patch.object(document_tasks.storage, "get_translate_args", return_value={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(document_tasks, "get_glossary", return_value=[]),
            patch.object(tasks, "translate_page", return_value=translated_entry) as translate_page_mock,
            patch.object(document_tasks, "reconcile_translate_state_after_page_success") as reconcile_success_mock,
            patch("document.pdf_extract.extract_pdf_text") as extract_pdf_mock,
            patch("document.pdf_extract.combine_sources") as combine_sources_mock,
        ):
            document_tasks.reparse_single_page(task_id, self.doc_id, 1, 0)

        self.assertFalse(extract_pdf_mock.called)
        self.assertFalse(combine_sources_mock.called)
        translate_page_mock.assert_called_once()
        reconcile_success_mock.assert_called_once_with(self.doc_id, 1)

        pages, _ = load_pages_from_disk(self.doc_id)
        self.assertEqual(pages[0]["blocks"][0]["text"], "OCR 正文")
        self.assertEqual(pages[0]["textSource"], "ocr")
        entries, _, _ = tasks.load_entries_from_disk(self.doc_id)
        self.assertEqual(entries[0]["_page_entries"][0]["translation"], "重译后的正文")

        events, exists = task_registry.get_task_events(task_id, 0)
        self.assertTrue(exists)
        event_dump = json.dumps(events, ensure_ascii=False)
        self.assertIn("强制使用 OCR 文字", event_dump)
        self.assertIn("自动重译本页", event_dump)

    def test_reparse_single_page_skips_cleanup_when_document_mode_disabled(self):
        update_doc_meta(self.doc_id, cleanup_headers_footers=False)
        task_id = "reparseskip01"
        pdf_path = os.path.join(config.DOCS_DIR, self.doc_id, "source.pdf")
        task_registry.create_task(task_id, pdf_path, "Reading Refresh", 0, options={"clean_header_footer": False})
        self.addCleanup(task_registry.remove_task, task_id)

        ocr_page = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "blocks": [{
                "text": "OCR 正文",
                "x": 12,
                "bbox": [0, 0, 50, 20],
                "label": "text",
                "is_meta": False,
                "heading_level": 0,
            }],
            "fnBlocks": [],
            "footnotes": "",
            "indent": None,
            "textSource": "ocr",
            "markdown": "",
        }
        translated_entry = {
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "OCR 正文",
                "translation": "快速模式重译正文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
                "_status": "done",
                "_error": "",
            }],
            "_usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "request_count": 1},
            "pages": "1",
        }

        with (
            patch("document.pdf_extract.extract_single_page_pdf", return_value=b"%PDF-1.4\n%page\n"),
            patch.object(document_tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(document_tasks.text_processing, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(document_tasks.text_processing, "clean_header_footer") as clean_mock,
            patch.object(document_tasks, "get_model_key", return_value="sonnet"),
            patch.object(document_tasks.storage, "get_translate_args", return_value={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(document_tasks, "get_glossary", return_value=[]),
            patch.object(tasks, "translate_page", return_value=translated_entry),
            patch.object(document_tasks, "reconcile_translate_state_after_page_success"),
        ):
            document_tasks.reparse_single_page(task_id, self.doc_id, 1, 0)

        clean_mock.assert_not_called()
        pages, _ = load_pages_from_disk(self.doc_id)
        self.assertFalse(pages[0]["_cleanup_applied"])
        events, exists = task_registry.get_task_events(task_id, 0)
        self.assertTrue(exists)
        event_dump = json.dumps(events, ensure_ascii=False)
        self.assertIn("跳过页眉页脚清理", event_dump)

    def test_pdf_page_passes_scale_query_to_renderer(self):
        pdf_path = os.path.join(config.DOCS_DIR, self.doc_id, "source.pdf")
        with patch("document.pdf_extract.render_pdf_page", return_value=b"png-bytes") as render_mock:
            resp = self.client.get("/pdf_page/0?scale=1.25")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "image/png")
        render_mock.assert_called_once_with(pdf_path, 0, scale=1.25)

    def test_pdf_page_rejects_non_positive_scale(self):
        resp = self.client.get("/pdf_page/0?scale=0")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("scale 参数无效", resp.get_data(as_text=True))

    def test_large_pdf_reading_page_only_mounts_initial_virtual_window_images(self):
        self._save_range_pages(1, 100)

        resp = self.client.get("/reading?bp=40")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        initial_img_indices = [
            int(match)
            for match in re.findall(r'<div class="pdf-page-item" data-pdf-bp="(\d+)"[^>]*>\s*<img class="pdf-img" loading="lazy" alt="PDF p\.\d+">', html)
        ]
        self.assertEqual(initial_img_indices, list(range(35, 46)))

    def test_partial_failed_current_page_uses_consistent_initial_nav_label(self):
        self._save_range_pages(1, 3)
        save_entries_to_disk([{
            "_pageBP": 2,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 2",
                "translation": "翻译 2",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "2",
                "_status": "error",
            }],
            "pages": "2",
        }], "Reading Refresh", 0, self.doc_id)

        resp = self.client.get("/reading?bp=2")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('PDF 第2页 · 部分完成', html)

    def test_get_translate_snapshot_preserves_paragraph_errors_in_draft(self):
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="error",
            draft={
                "active": False,
                "bp": 1,
                "para_idx": 1,
                "para_total": 3,
                "para_done": 1,
                "parallel_limit": 2,
                "active_para_indices": [],
                "paragraph_states": ["done", "error", "pending"],
                "paragraph_errors": ["", "第二段失败", ""],
                "paragraphs": ["第一段", "第二段草稿", ""],
                "status": "error",
                "note": "p.1 翻译失败，等待重试。",
                "last_error": "第二段失败",
            },
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["draft"]["paragraph_errors"], ["", "第二段失败", ""])

    def test_restorable_draft_page_embeds_retry_actions_and_error_details(self):
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="error",
            draft={
                "active": False,
                "bp": 1,
                "para_idx": 1,
                "para_total": 3,
                "para_done": 1,
                "parallel_limit": 2,
                "active_para_indices": [],
                "paragraph_states": ["done", "error", "pending"],
                "paragraph_errors": ["", "第二段失败", ""],
                "paragraphs": ["第一段", "第二段草稿", ""],
                "status": "error",
                "note": "p.1 翻译失败，等待重试。",
                "last_error": "第二段失败",
            },
        )

        resp = self.client.get("/reading?bp=1")
        html = resp.get_data(as_text=True)
        script = self._get_reading_script()
        css = self._get_reading_css()

        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="translationSessionToggleBtn"', html)
        self.assertIn('"paragraph_errors"', html)
        self.assertIn("Array.isArray(draft.paragraph_errors) ? draft.paragraph_errors.slice() : []", script)
        self.assertIn("translation-detail-item-meta", css)
        self.assertIn("state.draft.status === 'throttled'", script)
        self.assertIn("onclick=\"toggleTaskSessionDetails();\"", html)
        self.assertNotIn("syncUsagePanel();", script)
        self.assertNotIn("retryDraftPage()", script)
        self.assertNotIn("retryDraftParagraph(paraIdx)", script)

    def test_reading_route_tolerates_empty_doc_meta_file(self):
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
        }], "Reading Refresh", 0, self.doc_id)

        meta_path = os.path.join(config.DOCS_DIR, self.doc_id, "meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write("")

        resp = self.client.get("/reading?bp=1")
        html = resp.get_data(as_text=True)
        script = self._get_reading_script()

        self.assertEqual(resp.status_code, 200)
        self.assertIn("hasCurrentEntry: true,", html)
        self.assertIn("var currentPageHasEntry = !!BOOTSTRAP.hasCurrentEntry;", script)
        self.assertEqual(get_doc_meta(self.doc_id).get("last_entry_idx"), 0)

    def test_reading_page_hides_stale_terminal_snapshot_on_initial_load(self):
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="done",
            total_pages=5,
            done_pages=1,
            processed_pages=1,
            pending_pages=0,
            current_bp=1,
            current_page_idx=1,
            translated_paras=1,
            translated_chars=60,
            prompt_tokens=400,
            completion_tokens=198,
            draft={
                "active": False,
                "bp": 1,
                "para_idx": 0,
                "para_total": 1,
                "para_done": 1,
                "parallel_limit": 1,
                "active_para_indices": [],
                "paragraph_states": ["done"],
                "paragraphs": ["旧草稿"],
                "status": "done",
                "note": "当前页已完整提交到硬盘。",
                "last_error": "",
            },
        )

        resp = self.client.get("/reading?bp=1")
        html = resp.get_data(as_text=True)
        script = self._get_reading_script()

        self.assertEqual(resp.status_code, 200)
        self.assertIn('/static/reading/index.js', html)
        self.assertIn("var translateSessionActivated = !!BOOTSTRAP.showInitialTaskSnapshot;", script)
        self.assertIn("function shouldHydrateTranslateDraft(state)", script)
        self.assertIn("function hasRestorableDraft(state)", script)
        self.assertIn("state.draft.status === 'throttled'", script)

    def test_get_translate_snapshot_closes_stale_running_state_without_active_worker(self):
        tasks._save_translate_state(
            self.doc_id,
            running=True,
            stop_requested=True,
            phase="stopping",
            total_pages=5,
            done_pages=2,
            pending_pages=3,
            current_bp=3,
            current_page_idx=3,
            draft={
                "active": True,
                "bp": 3,
                "para_idx": 1,
                "para_total": 4,
                "para_done": 1,
                "parallel_limit": 3,
                "active_para_indices": [1, 2],
                "paragraph_states": ["done", "running", "pending", "pending"],
                "paragraphs": ["第一段", "第二段草稿", "", ""],
                "status": "streaming",
                "note": "正在流式翻译",
                "last_error": "",
            },
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertFalse(snapshot["running"])
        self.assertFalse(snapshot["stop_requested"])
        self.assertEqual(snapshot["phase"], "stopped")
        self.assertFalse(snapshot["draft"]["active"])
        self.assertEqual(snapshot["draft"]["status"], "aborted")
        self.assertEqual(snapshot["draft"]["active_para_indices"], [])

    def test_release_runtime_does_not_clear_newer_owner_state(self):
        with translate_runtime._translate_lock:
            translate_runtime._translate_task["running"] = True
            translate_runtime._translate_task["stop"] = True
            translate_runtime._translate_task["events"] = [("stopped", {"msg": "old"})]
            translate_runtime._translate_task["doc_id"] = self.doc_id
            translate_runtime._translate_task["owner_token"] = 1
        old_deps = tasks._translate_worker_deps()

        with translate_runtime._translate_lock:
            translate_runtime._translate_task["running"] = True
            translate_runtime._translate_task["stop"] = False
            translate_runtime._translate_task["events"] = [("init", {"msg": "new"})]
            translate_runtime._translate_task["doc_id"] = self.doc_id
            translate_runtime._translate_task["owner_token"] = 2
        new_deps = tasks._translate_worker_deps()

        old_deps["release_runtime"]()
        with translate_runtime._translate_lock:
            self.assertTrue(translate_runtime._translate_task["running"])
            self.assertFalse(translate_runtime._translate_task["stop"])
            self.assertEqual(translate_runtime._translate_task["doc_id"], self.doc_id)
            self.assertEqual(translate_runtime._translate_task["owner_token"], 2)
            self.assertEqual(translate_runtime._translate_task["events"], [("init", {"msg": "new"})])

        new_deps["release_runtime"]()
        with translate_runtime._translate_lock:
            self.assertFalse(translate_runtime._translate_task["running"])
            self.assertFalse(translate_runtime._translate_task["stop"])
            self.assertEqual(translate_runtime._translate_task["doc_id"], "")
            self.assertEqual(translate_runtime._translate_task["owner_token"], 2)

    def test_get_translate_snapshot_normalizes_done_phase_to_zero_pending_pages(self):
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="done",
            total_pages=14,
            done_pages=11,
            pending_pages=3,
            current_bp=14,
            current_page_idx=14,
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["phase"], "done")
        self.assertEqual(snapshot["done_pages"], 11)
        self.assertEqual(snapshot["pending_pages"], 0)

    def test_get_translate_snapshot_keeps_processed_pages_distinct_from_done_pages(self):
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="done",
            total_pages=14,
            done_pages=11,
            processed_pages=14,
            pending_pages=0,
            current_bp=14,
            current_page_idx=14,
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["done_pages"], 11)
        self.assertEqual(snapshot["processed_pages"], 14)

    def test_get_translate_snapshot_preserves_remaining_pages_when_stopped(self):
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            total_pages=14,
            done_pages=11,
            processed_pages=12,
            pending_pages=2,
            current_bp=12,
            current_page_idx=12,
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["phase"], "stopped")
        self.assertEqual(snapshot["done_pages"], 11)
        self.assertEqual(snapshot["processed_pages"], 12)
        self.assertEqual(snapshot["pending_pages"], 2)

    def test_get_translate_snapshot_preserves_remaining_pages_when_error(self):
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="error",
            total_pages=14,
            done_pages=11,
            processed_pages=12,
            pending_pages=2,
            current_bp=12,
            current_page_idx=12,
            last_error="p.12 翻译失败",
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["phase"], "error")
        self.assertEqual(snapshot["done_pages"], 11)
        self.assertEqual(snapshot["processed_pages"], 12)
        self.assertEqual(snapshot["pending_pages"], 2)
        self.assertEqual(snapshot["last_error"], "p.12 翻译失败")

    def test_get_translate_snapshot_marks_terminal_partial_failed_when_all_pages_processed(self):
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            total_pages=14,
            done_pages=11,
            processed_pages=14,
            pending_pages=3,
            current_bp=14,
            current_page_idx=14,
            failed_bps=[4, 9, 12],
            failed_pages=[
                {"bp": 4, "error": "p.4 翻译失败"},
                {"bp": 9, "error": "p.9 翻译失败"},
                {"bp": 12, "error": "p.12 翻译失败"},
            ],
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["phase"], "partial_failed")
        self.assertEqual(snapshot["done_pages"], 11)
        self.assertEqual(snapshot["processed_pages"], 14)
        self.assertEqual(snapshot["pending_pages"], 0)
        self.assertEqual(snapshot["failed_bps"], [4, 9, 12])

    def test_get_translate_snapshot_uses_current_unprocessed_page_as_resume_bp_when_stopped(self):
        self._save_range_pages(1, 5)
        save_entries_to_disk([
            {"_pageBP": 2, "_model": "sonnet", "_page_entries": [], "pages": "2"},
            {"_pageBP": 3, "_model": "sonnet", "_page_entries": [], "pages": "3"},
        ], "Reading Refresh", 0, self.doc_id)
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            start_bp=2,
            total_pages=4,
            done_pages=2,
            processed_pages=2,
            pending_pages=2,
            current_bp=4,
            current_page_idx=3,
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["resume_bp"], 4)

    def test_get_translate_snapshot_reconciles_continuous_counts_from_disk_when_sqlite_stale(self):
        """连续翻译：SQLite 计数可能落后，快照应与磁盘条目及 resume_bp 一致。"""
        from translation.translate_state import TASK_KIND_CONTINUOUS, _build_translate_task_meta

        self._save_range_pages(1, 10)
        save_entries_to_disk(
            [{"_pageBP": i, "_model": "sonnet", "_page_entries": [], "pages": str(i)} for i in range(1, 6)],
            "Reading Refresh",
            0,
            self.doc_id,
        )
        task_meta = _build_translate_task_meta(
            kind=TASK_KIND_CONTINUOUS,
            label="连续翻译",
            start_bp=6,
            target_bps=list(range(1, 11)),
        )
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            start_bp=6,
            total_pages=10,
            done_pages=0,
            processed_pages=0,
            pending_pages=10,
            current_bp=6,
            current_page_idx=6,
            task=task_meta,
        )
        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["total_pages"], 10)
        self.assertEqual(snapshot["done_pages"], 5)
        self.assertEqual(snapshot["processed_pages"], 5)
        self.assertEqual(snapshot["resume_bp"], 6)

    def test_get_translate_snapshot_uses_failed_page_as_resume_bp_when_error(self):
        self._save_range_pages(1, 5)
        save_entries_to_disk([
            {"_pageBP": 2, "_model": "sonnet", "_page_entries": [], "pages": "2"},
            {"_pageBP": 3, "_model": "sonnet", "_page_entries": [], "pages": "3"},
        ], "Reading Refresh", 0, self.doc_id)
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="error",
            start_bp=2,
            total_pages=4,
            done_pages=2,
            processed_pages=2,
            pending_pages=2,
            current_bp=4,
            current_page_idx=3,
            failed_bps=[4],
            failed_pages=[{"bp": 4, "error": "p.4 翻译失败"}],
            last_error="p.4 翻译失败",
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["resume_bp"], 4)

    def test_get_translate_snapshot_uses_first_failed_page_as_resume_bp_when_partial_failed(self):
        self._save_range_pages(1, 5)
        save_entries_to_disk([
            {"_pageBP": 2, "_model": "sonnet", "_page_entries": [], "pages": "2"},
            {"_pageBP": 3, "_model": "sonnet", "_page_entries": [], "pages": "3"},
            {"_pageBP": 5, "_model": "sonnet", "_page_entries": [], "pages": "5"},
        ], "Reading Refresh", 0, self.doc_id)
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=2,
            total_pages=4,
            done_pages=3,
            processed_pages=4,
            pending_pages=0,
            current_bp=5,
            current_page_idx=4,
            failed_bps=[4],
            failed_pages=[{"bp": 4, "error": "p.4 翻译失败"}],
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["resume_bp"], 4)

    def test_get_translate_snapshot_marks_done_state_with_paragraph_errors_as_partial_failed(self):
        self._save_range_pages(1, 1)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "[翻译失败: 超时]",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
                "_status": "error",
                "_error": "超时",
            }],
            "pages": "1",
        }], "Reading Refresh", 0, self.doc_id)
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="done",
            start_bp=1,
            total_pages=1,
            done_pages=1,
            processed_pages=1,
            pending_pages=0,
            current_bp=1,
            current_page_idx=1,
        )

        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["phase"], "partial_failed")
        self.assertEqual(snapshot["partial_failed_bps"], [1])
        self.assertEqual(snapshot["resume_bp"], 1)

    def test_retranslate_success_clears_failed_state_and_done_recovers(self):
        self._save_range_pages(1, 1)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "[翻译失败: 超时]",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
                "_status": "error",
                "_error": "超时",
            }],
            "pages": "1",
        }], "Reading Refresh", 0, self.doc_id)
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=1,
            total_pages=1,
            done_pages=0,
            processed_pages=1,
            pending_pages=0,
            current_bp=1,
            current_page_idx=1,
            failed_bps=[1],
            failed_pages=[{"bp": 1, "error": "超时"}],
        )

        fixed_entry = {
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "修复后的翻译",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
                "_status": "done",
                "_error": "",
            }],
            "pages": "1",
        }

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "translate_page", return_value=fixed_entry),
        ):
            resp = self._post("/retranslate/1", data={"doc_id": self.doc_id, "target": "builtin:qwen-plus"})

        self.assertEqual(resp.status_code, 302)
        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["phase"], "done")
        self.assertEqual(snapshot["failed_bps"], [])
        self.assertIsNone(snapshot["resume_bp"])

        status = self.client.get("/translate_status", query_string={"doc_id": self.doc_id}).get_json()
        self.assertEqual(status["failed_bps"], [])
        self.assertEqual(status["partial_failed_bps"], [])

    def test_retranslate_failure_keeps_failed_state_and_updates_last_error(self):
        self._save_range_pages(1, 1)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "[翻译失败: 超时]",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
                "_status": "error",
                "_error": "超时",
            }],
            "pages": "1",
        }], "Reading Refresh", 0, self.doc_id)
        tasks._save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=1,
            total_pages=1,
            done_pages=0,
            processed_pages=1,
            pending_pages=0,
            current_bp=1,
            current_page_idx=1,
            failed_bps=[1],
            failed_pages=[{"bp": 1, "error": "超时"}],
            last_error="超时",
        )

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "translate_page", side_effect=RuntimeError("新的失败原因")),
        ):
            resp = self._post("/retranslate/1", data={"doc_id": self.doc_id, "target": "builtin:qwen-plus"})

        self.assertEqual(resp.status_code, 302)
        snapshot = translate_runtime.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["phase"], "partial_failed")
        self.assertEqual(snapshot["failed_bps"], [1])
        self.assertEqual(snapshot["last_error"], "新的失败原因")
        self.assertEqual(snapshot["resume_bp"], 1)

        status = self.client.get("/translate_status", query_string={"doc_id": self.doc_id}).get_json()
        self.assertEqual(status["failed_bps"], [1])
        self.assertEqual(status["partial_failed_bps"], [1])


if __name__ == "__main__":
    unittest.main()

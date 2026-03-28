#!/usr/bin/env python3
"""后台流式翻译任务单元测试。"""

import os
import re
import shutil
import tempfile
import time
import unittest
import json
from unittest.mock import Mock, patch

import app as app_module
import config
import ocr_client
import tasks
from config import create_doc, ensure_dirs, get_doc_meta, set_current_doc
from storage import load_pages_from_disk, save_entries_to_disk, save_pages_to_disk, get_translate_args
from testsupport import ClientCSRFMixin
from translator import TranslateStreamAborted, RateLimitedError, QuotaExceededError


class TasksStreamingTest(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="tasks-stream-", dir="/tmp")
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
        with tasks._translate_lock:
            tasks._translate_task["running"] = False
            tasks._translate_task["stop"] = False
            tasks._translate_task["events"] = []
            tasks._translate_task["doc_id"] = ""

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
        snapshot = tasks.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["draft"]["status"], "done")
        self.assertEqual(snapshot["draft"]["para_total"], 2)
        self.assertEqual(snapshot["draft"]["para_done"], 2)
        self.assertEqual(snapshot["draft"]["paragraphs"], ["甲乙", "甲乙"])

    def test_get_translate_args_prefers_custom_model_name_when_enabled(self):
        config.save_config({
            "model_key": "qwen-plus",
            "dashscope_key": "dashscope-test-key",
            "custom_model_name": "qwen-plus-custom-202503",
            "custom_model_enabled": True,
            "custom_model_base_key": "qwen-plus",
        })

        t_args = get_translate_args("qwen-plus")

        self.assertEqual(t_args["provider"], "qwen")
        self.assertEqual(t_args["model_id"], "qwen-plus-custom-202503")
        self.assertEqual(t_args["api_key"], "dashscope-test-key")

    def test_get_translate_args_uses_preset_model_id_when_custom_name_saved_but_disabled(self):
        config.save_config({
            "model_key": "qwen-max",
            "dashscope_key": "dashscope-test-key",
            "custom_model_name": "qwen3.5-plus-longcontext",
            "custom_model_enabled": False,
            "custom_model_base_key": "qwen-max",
        })

        t_args = get_translate_args("qwen-max")

        self.assertEqual(t_args["provider"], "qwen")
        self.assertEqual(t_args["model_id"], "qwen-max")

    def test_get_translate_args_uses_bound_provider_from_custom_model_base_key(self):
        config.save_config({
            "model_key": "deepseek-chat",
            "deepseek_key": "deepseek-test-key",
            "dashscope_key": "dashscope-test-key",
            "custom_model_name": "qwen3.5-plus-longcontext",
            "custom_model_enabled": True,
            "custom_model_base_key": "qwen-max",
        })

        t_args = get_translate_args("deepseek-chat")

        self.assertEqual(t_args["provider"], "qwen")
        self.assertEqual(t_args["model_id"], "qwen3.5-plus-longcontext")
        self.assertEqual(t_args["api_key"], "dashscope-test-key")

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
        snapshot = tasks.get_translate_snapshot(self.doc_id)
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
        snapshot = tasks.get_translate_snapshot(self.doc_id)
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

    def test_translate_page_stream_allows_qwen_plus_up_to_ten_parallel(self):
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

    def test_translate_page_stream_allows_qwen_turbo_up_to_ten_parallel(self):
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

    def test_translate_page_stream_keeps_reasoner_at_three_parallel_when_enabled(self):
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

        self.assertEqual(peak, 3)
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
        snapshot = tasks.get_translate_snapshot(self.doc_id)
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
        self.temp_root = tempfile.mkdtemp(prefix="reading-refresh-", dir="/tmp")
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

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def _save_range_pages(self, first_bp: int, last_bp: int):
        save_pages_to_disk([{
            "bookPage": bp,
            "fileIdx": bp - first_bp,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": f"Page {bp}",
            "footnotes": "",
        } for bp in range(first_bp, last_bp + 1)], "Reading Refresh", self.doc_id)

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

    def test_reading_page_embeds_controlled_commit_refresh_guards(self):
        self._save_range_pages(1, 2)
        resp = self.client.get("/reading?bp=1&auto=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("var store = {", html)
        self.assertIn("pendingCommittedRefreshBp: null", html)
        self.assertIn("function scheduleCommittedPageRefresh(bp)", html)
        self.assertIn("function maybeRefreshCommittedCurrentPage(state)", html)
        self.assertIn("manualNavigationInFlight: false", html)
        self.assertIn("function dispatch(action, payload)", html)
        self.assertIn("function handleReadingNavClick(event, bp)", html)
        self.assertIn("function setCurrentReadingBp(bp)", html)
        self.assertIn("function setCurrentPdfBp(bp)", html)
        self.assertIn("function getVisiblePdfBp()", html)
        self.assertIn("function setVisiblePdfBp(bp, source)", html)
        self.assertIn("function syncReadingBpFromPdf(source)", html)
        self.assertIn("function syncPdfBpFromReading(source)", html)
        self.assertIn('id="pdfScrollContainer"', html)
        self.assertIn('class="pdf-page-item"', html)
        self.assertIn("data-pdf-src=", html)
        self.assertIn("function getPdfRenderScale(bp)", html)
        self.assertIn("function buildPdfPageSrc(pageEl)", html)
        self.assertIn("function syncPdfImageSrc(pageEl, img)", html)
        self.assertIn("Math.max(2, window.devicePixelRatio || 1)", html)
        self.assertIn("function initPdfVirtualScroll()", html)
        self.assertIn("function updatePdfVirtualWindow(centerBp)", html)
        self.assertIn("function mountPdfImage(pageEl)", html)
        self.assertIn("function unmountPdfImage(pageEl)", html)
        self.assertIn("function setupPdfScrollObserver()", html)
        self.assertIn("new IntersectionObserver(", html)
        self.assertIn("function maybeRestoreHighlight()", html)
        self.assertIn("function suppressObserverNavigation(ms)", html)
        self.assertIn("function isObserverNavigationSuppressed()", html)
        self.assertIn("function alignPdfToReading(options)", html)
        self.assertIn("alignPdfToReading({", html)
        self.assertIn("var translateSessionActivated = false;", html)
        self.assertIn("function shouldHydrateTranslateDraft(state)", html)
        self.assertIn("function hasRestorableDraft(state)", html)
        self.assertIn("var VIRTUAL_WINDOW_RADIUS = 5;", html)
        self.assertIn("var VIRTUAL_SCROLL_MIN_PAGES = 80;", html)
        self.assertIn("state.processed_pages", html)
        self.assertIn("partial_failed: '部分完成'", html)
        self.assertIn("state.phase === 'partial_failed'", html)
        self.assertIn("state.resume_bp", html)
        self.assertIn("function getResumeActionLabel(state)", html)
        self.assertIn('id="usageRecentTokens"', html)
        self.assertIn('id="usageTokenRate"', html)
        self.assertIn('id="usageDraftActions"', html)
        self.assertIn("translateES.addEventListener('stream_usage'", html)
        self.assertIn("function applyStreamUsage(eventData)", html)
        self.assertIn("function getUsageSampleStats()", html)
        self.assertIn("function retryDraftPage()", html)
        self.assertIn("function retryDraftParagraph(paraIdx)", html)
        self.assertIn('id="floatingPageNav"', html)
        self.assertIn('class="floating-page-nav-btn next"', html)
        self.assertIn('floating-page-nav-btn prev', html)
        self.assertIn("background: rgba(44, 36, 22, 0.5);", html)
        self.assertIn("position: fixed;", html)
        self.assertIn("function getReadingUiStateParams()", html)
        self.assertIn("url.searchParams.set('orig'", html)
        self.assertIn("url.searchParams.set('layout'", html)
        self.assertIn("url.searchParams.set('pdf'", html)
        self.assertIn("function applyOriginalVisibilityState()", html)
        self.assertIn("function applyLayoutState()", html)
        self.assertIn("function applyPdfPanelVisibilityState()", html)

    def test_reading_page_preserves_ui_state_in_initial_store_and_nav_links(self):
        self._save_range_pages(1, 2)

        resp = self.client.get("/reading?bp=1&usage=0&orig=0&layout=stack&pdf=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("showOriginal: false,", html)
        self.assertIn("pdfVisible: false,", html)
        self.assertIn("sideBySide: false,", html)
        self.assertIn(f"var currentDocId = '{self.doc_id}';", html)
        self.assertIn(f'/reading?bp=2&amp;doc_id={self.doc_id}&amp;usage=0&amp;orig=0&amp;layout=stack&amp;pdf=0', html)
        self.assertIn('class="pdf-panel" id="pdfPanel" style="display:none;"', html)
        self.assertIn('class="pdf-toggle-btn" id="pdfToggleBtn"', html)

    def test_reading_page_syncs_pdf_resizer_visibility_with_panel_state(self):
        self._save_range_pages(1, 2)

        resp = self.client.get("/reading?bp=1&usage=0&orig=0&layout=stack&pdf=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("var resizer = document.getElementById('pdfResizer');", html)
        self.assertIn("resizer.style.display = store.ui.pdfVisible ? '' : 'none';", html)

    def test_reading_page_refreshes_pdf_layout_during_resizer_drag(self):
        self._save_range_pages(1, 2)

        resp = self.client.get("/reading?bp=1&pdf=1")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("function applyPdfPagePlaceholders(options)", html)
        self.assertRegex(
            html,
            re.compile(
                r"window\.addEventListener\('mousemove', function\(e\) \{[\s\S]*?"
                r"applyPdfPagePlaceholders\(\{ syncImageSrc: false \}\);",
                re.S,
            ),
        )
        self.assertRegex(
            html,
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
        self.assertIn("不走 PDF 文字层", html)
        self.assertIn("会自动重译本页", html)

    def test_reparse_single_page_forces_ocr_text_without_pdf_merge_and_retranslates(self):
        task_id = "reparseocr01"
        pdf_path = os.path.join(config.DOCS_DIR, self.doc_id, "source.pdf")
        tasks.create_task(task_id, pdf_path, "Reading Refresh", 0)
        self.addCleanup(tasks.remove_task, task_id)

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
            patch("pdf_extract.extract_single_page_pdf", return_value=b"%PDF-1.4\n%page\n"),
            patch.object(tasks, "call_paddle_ocr_bytes", return_value={"layoutParsingResults": []}),
            patch.object(tasks, "parse_ocr", return_value={"pages": [ocr_page], "log": []}),
            patch.object(tasks, "clean_header_footer", side_effect=lambda pages: {"pages": pages, "log": []}),
            patch.object(tasks, "get_model_key", return_value="sonnet"),
            patch.object(tasks, "get_translate_args", return_value={"model_id": "fake-model-id", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "get_glossary", return_value=[]),
            patch.object(tasks, "translate_page", return_value=translated_entry) as translate_page_mock,
            patch.object(tasks, "reconcile_translate_state_after_page_success") as reconcile_success_mock,
            patch("pdf_extract.extract_pdf_text") as extract_pdf_mock,
            patch("pdf_extract.combine_sources") as combine_sources_mock,
        ):
            tasks.reparse_single_page(task_id, self.doc_id, 1, 0)

        self.assertFalse(extract_pdf_mock.called)
        self.assertFalse(combine_sources_mock.called)
        translate_page_mock.assert_called_once()
        reconcile_success_mock.assert_called_once_with(self.doc_id, 1)

        pages, _ = load_pages_from_disk(self.doc_id)
        self.assertEqual(pages[0]["blocks"][0]["text"], "OCR 正文")
        self.assertEqual(pages[0]["textSource"], "ocr")
        entries, _, _ = tasks.load_entries_from_disk(self.doc_id)
        self.assertEqual(entries[0]["_page_entries"][0]["translation"], "重译后的正文")

        events, exists = tasks.get_task_events(task_id, 0)
        self.assertTrue(exists)
        event_dump = json.dumps(events, ensure_ascii=False)
        self.assertIn("强制使用 OCR 文字", event_dump)
        self.assertIn("自动重译本页", event_dump)

    def test_pdf_page_passes_scale_query_to_renderer(self):
        pdf_path = os.path.join(config.DOCS_DIR, self.doc_id, "source.pdf")
        with patch.object(app_module, "render_pdf_page", return_value=b"png-bytes") as render_mock:
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
        self.assertIn('p.2 · 部分完成', html)

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

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

        self.assertEqual(resp.status_code, 200)
        self.assertIn('"paragraph_errors"', html)
        self.assertIn("Array.isArray(draft.paragraph_errors) ? draft.paragraph_errors.slice() : []", html)
        self.assertIn("usage-draft-card-error", html)
        self.assertIn("state.draft.status === 'throttled'", html)
        self.assertIn("onclick=\"toggleUsageDashboard();\"", html)
        self.assertNotIn("syncUsagePanel();", html)
        self.assertIn("retryDraftPage()", html)
        self.assertIn("retryDraftParagraph(paraIdx)", html)

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

        self.assertEqual(resp.status_code, 200)
        self.assertIn("var currentPageHasEntry = true;", html)
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

        self.assertEqual(resp.status_code, 200)
        self.assertIn("var translateSessionActivated = false;", html)
        self.assertIn("function shouldHydrateTranslateDraft(state)", html)
        self.assertIn("function hasRestorableDraft(state)", html)
        self.assertIn("state.draft.status === 'throttled'", html)

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

        self.assertFalse(snapshot["running"])
        self.assertFalse(snapshot["stop_requested"])
        self.assertEqual(snapshot["phase"], "stopped")
        self.assertFalse(snapshot["draft"]["active"])
        self.assertEqual(snapshot["draft"]["status"], "aborted")
        self.assertEqual(snapshot["draft"]["active_para_indices"], [])

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

        self.assertEqual(snapshot["resume_bp"], 4)

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

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

        snapshot = tasks.get_translate_snapshot(self.doc_id)

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
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(app_module, "translate_page", return_value=fixed_entry),
        ):
            resp = self._post("/retranslate/1/sonnet", data={"doc_id": self.doc_id})

        self.assertEqual(resp.status_code, 302)
        snapshot = tasks.get_translate_snapshot(self.doc_id)
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
            patch.object(app_module, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(app_module, "translate_page", side_effect=RuntimeError("新的失败原因")),
        ):
            resp = self._post("/retranslate/1/sonnet", data={"doc_id": self.doc_id})

        self.assertEqual(resp.status_code, 302)
        snapshot = tasks.get_translate_snapshot(self.doc_id)
        self.assertEqual(snapshot["phase"], "partial_failed")
        self.assertEqual(snapshot["failed_bps"], [1])
        self.assertEqual(snapshot["last_error"], "新的失败原因")
        self.assertEqual(snapshot["resume_bp"], 1)

        status = self.client.get("/translate_status", query_string={"doc_id": self.doc_id}).get_json()
        self.assertEqual(status["failed_bps"], [1])
        self.assertEqual(status["partial_failed_bps"], [1])


if __name__ == "__main__":
    unittest.main()

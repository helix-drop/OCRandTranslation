#!/usr/bin/env python3
"""后台流式翻译任务单元测试。"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import config
import tasks
from config import create_doc, ensure_dirs
from storage import save_entries_to_disk
from translator import TranslateStreamAborted


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


if __name__ == "__main__":
    unittest.main()

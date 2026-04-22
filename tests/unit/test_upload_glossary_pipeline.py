"""覆盖 FNM/标准上传流程里"附带词典"任务选项的 pipeline 行为。"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import config
from persistence.sqlite_store import SQLiteRepository
from pipeline.task_document_pipeline import (
    _cleanup_glossary_upload_temp,
    _persist_glossary_upload,
)


class PersistGlossaryUploadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = tempfile.mkdtemp(prefix="upload-glossary-")
        self._patch_config_dirs(self.temp_root)
        config.ensure_dirs()
        self.doc_id = config.create_doc("glossary-test.pdf")
        self.events: list[tuple[str, dict]] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str) -> None:
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def _deps(self) -> dict:
        def _task_push(task_id, event_type, data):
            self.events.append((event_type, dict(data)))

        return {
            "task_push": _task_push,
            "parse_glossary_file": config.parse_glossary_file,
            "set_glossary": config.set_glossary,
        }

    def _write_temp_csv(self, body: str) -> str:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        try:
            tmp.write(body.encode("utf-8"))
        finally:
            tmp.close()
        return tmp.name

    def test_persist_glossary_upload_applies_items_to_target_doc(self) -> None:
        path = self._write_temp_csv("term,defn\nhello,你好\nworld,世界\n")
        task = {"options": {"glossary_upload": {"path": path, "filename": "词典.csv"}}}
        try:
            _persist_glossary_upload(
                task_id="t1",
                doc_id=self.doc_id,
                task=task,
                deps=self._deps(),
            )

            items = config.list_glossary_items(doc_id=self.doc_id)
            self.assertEqual(items, [["hello", "你好"], ["world", "世界"]])

            log_events = [data for evt, data in self.events if evt == "log"]
            self.assertTrue(
                any("已导入词典 2 条" in str(data.get("msg", "")) for data in log_events),
                msg=log_events,
            )
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_persist_glossary_upload_skips_missing_path(self) -> None:
        task = {"options": {"glossary_upload": {"path": "", "filename": ""}}}

        _persist_glossary_upload(
            task_id="t1",
            doc_id=self.doc_id,
            task=task,
            deps=self._deps(),
        )

        self.assertEqual(config.list_glossary_items(doc_id=self.doc_id), [])
        self.assertEqual(self.events, [])

    def test_persist_glossary_upload_logs_warning_on_empty_file(self) -> None:
        path = self._write_temp_csv("term,defn\n")  # 只有表头，无有效行
        task = {"options": {"glossary_upload": {"path": path, "filename": "空.csv"}}}
        try:
            _persist_glossary_upload(
                task_id="t1",
                doc_id=self.doc_id,
                task=task,
                deps=self._deps(),
            )

            self.assertEqual(config.list_glossary_items(doc_id=self.doc_id), [])
            log_events = [data for evt, data in self.events if evt == "log"]
            self.assertTrue(
                any("未解析到有效词条" in str(data.get("msg", "")) for data in log_events),
                msg=log_events,
            )
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_cleanup_glossary_upload_temp_removes_file(self) -> None:
        path = self._write_temp_csv("term,defn\nhello,你好\n")
        task = {"options": {"glossary_upload": {"path": path, "filename": "词典.csv"}}}

        self.assertTrue(os.path.exists(path))
        _cleanup_glossary_upload_temp(task)
        self.assertFalse(os.path.exists(path))
        # 再调用一次不应抛异常
        _cleanup_glossary_upload_temp(task)


if __name__ == "__main__":
    unittest.main()

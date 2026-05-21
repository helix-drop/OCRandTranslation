"""FNM_RE/dev/importer.py 的单元测试。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from FNM_RE.dev.importer import import_doc_for_dev
from persistence.sqlite_store import SingleDBRepository


class _FakeFS:
    """内存化的 doc 目录与 raw_pages.json。"""

    def __init__(self, tmp_root: str) -> None:
        self.tmp_root = tmp_root

    def get_doc_dir(self, doc_id: str) -> str:
        return os.path.join(self.tmp_root, doc_id)

    def make_doc(self, doc_id: str, *, pages: list | None = None, empty_raw: bool = False):
        doc_dir = self.get_doc_dir(doc_id)
        os.makedirs(doc_dir, exist_ok=True)
        raw_path = os.path.join(doc_dir, "raw_pages.json")
        if empty_raw:
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write("")
        else:
            final_pages = pages if pages is not None else [{"bookPage": 1, "markdown": "hello"}]
            payload = {"pages": final_pages}
            with open(raw_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
        return doc_dir

    def load_pages_from_disk(self, doc_id: str):
        raw_path = os.path.join(self.get_doc_dir(doc_id), "raw_pages.json")
        with open(raw_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return list(payload.get("pages") or []), f"{doc_id}.pdf"


class ImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self._tmp_db.close()
        self.db_path = self._tmp_db.name
        self.repo = SingleDBRepository(self.db_path)
        # 预创建 documents 行以满足外键
        self.repo.upsert_document("doc1", "book.pdf")
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.fs = _FakeFS(self._tmp_dir.name)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _import(self, doc_id: str):
        return import_doc_for_dev(
            doc_id,
            repo=self.repo,
            get_doc_dir=self.fs.get_doc_dir,
            load_pages_from_disk=self.fs.load_pages_from_disk,
        )

    def test_empty_doc_id_returns_error(self):
        result = self._import("")
        self.assertFalse(result.ok)
        self.assertIn("doc_id", result.error)

    def test_missing_doc_dir_returns_error(self):
        result = self._import("no_such_doc")
        self.assertFalse(result.ok)
        self.assertIn("文档目录", result.error)

    def test_missing_raw_pages_returns_error(self):
        doc_dir = self.fs.get_doc_dir("doc1")
        os.makedirs(doc_dir, exist_ok=True)
        result = self._import("doc1")
        self.assertFalse(result.ok)
        self.assertIn("raw_pages.json", result.error)

    def test_empty_raw_pages_returns_error(self):
        self.fs.make_doc("doc1", empty_raw=True)
        result = self._import("doc1")
        self.assertFalse(result.ok)

    def test_zero_pages_returns_error(self):
        self.fs.make_doc("doc1", pages=[])
        result = self._import("doc1")
        self.assertFalse(result.ok)
        self.assertIn("页数", result.error)

    def test_happy_path_initializes_six_idle_phases(self):
        self.fs.make_doc("doc1", pages=[{"bookPage": 1}, {"bookPage": 2}])
        result = self._import("doc1")
        self.assertTrue(result.ok, msg=result.error)
        self.assertEqual(result.page_count, 2)
        self.assertEqual(len(result.phase_runs), 6)
        for phase_num, row in zip(range(1, 7), result.phase_runs):
            self.assertEqual(row["phase"], phase_num)
            self.assertEqual(row["status"], "idle")
            self.assertFalse(row["gate_pass"])

    def test_reimport_is_idempotent(self):
        self.fs.make_doc("doc1", pages=[{"bookPage": 1}])
        first = self._import("doc1")
        self.assertTrue(first.ok)
        # 手动推进 phase 1 到 ready
        self.repo.upsert_phase_run("doc1", 1, status="ready", gate_pass=True)
        # 再次导入不应清零
        second = self._import("doc1")
        self.assertTrue(second.ok)
        phase1 = next(r for r in second.phase_runs if r["phase"] == 1)
        self.assertEqual(phase1["status"], "ready")
        self.assertTrue(phase1["gate_pass"])


if __name__ == "__main__":
    unittest.main()

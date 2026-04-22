"""DevRepoMixin（fnm_phase_runs / fnm_dev_snapshots）单元测试。"""
from __future__ import annotations

import os
import tempfile
import unittest

from persistence.sqlite_repo_dev import (
    PHASE_STATUS_FAILED,
    PHASE_STATUS_IDLE,
    PHASE_STATUS_READY,
    PHASE_STATUS_RUNNING,
    PHASES,
)
from persistence.sqlite_store import SingleDBRepository


class DevRepoPhaseRunsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self._tmp.close()
        self.db_path = self._tmp.name
        self.repo = SingleDBRepository(self.db_path)
        # 预创建 documents 行以满足外键约束
        self.repo.upsert_document("doc1", "Book 1.pdf")
        self.repo.upsert_document("doc2", "Book 2.pdf")

    def tearDown(self) -> None:
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    # ---------- init / list ----------

    def test_list_phase_runs_empty_returns_idle_placeholders(self):
        rows = self.repo.list_phase_runs("doc1")
        self.assertEqual(len(rows), 6)
        for phase, row in zip(PHASES, rows):
            self.assertEqual(row["phase"], phase)
            self.assertEqual(row["status"], PHASE_STATUS_IDLE)
            self.assertFalse(row["gate_pass"])
            self.assertFalse(row["forced_skip"])
            self.assertIsNone(row["created_at"])  # 未落库

    def test_init_phase_runs_is_idempotent(self):
        first = self.repo.init_phase_runs("doc1")
        self.assertEqual(len(first), 6)
        self.assertTrue(all(r["created_at"] is not None for r in first))

        # 修改第 3 阶段为 ready，再次 init 不应覆盖
        self.repo.upsert_phase_run(
            "doc1", 3, status=PHASE_STATUS_READY, gate_pass=True
        )
        second = self.repo.init_phase_runs("doc1")
        self.assertEqual(len(second), 6)
        phase3 = next(r for r in second if r["phase"] == 3)
        self.assertEqual(phase3["status"], PHASE_STATUS_READY)
        self.assertTrue(phase3["gate_pass"])

    def test_list_phase_runs_isolates_docs(self):
        self.repo.init_phase_runs("doc1")
        self.repo.upsert_phase_run("doc1", 1, status=PHASE_STATUS_READY, gate_pass=True)
        self.repo.init_phase_runs("doc2")
        doc2_rows = self.repo.list_phase_runs("doc2")
        phase1 = next(r for r in doc2_rows if r["phase"] == 1)
        self.assertEqual(phase1["status"], PHASE_STATUS_IDLE)
        self.assertFalse(phase1["gate_pass"])

    # ---------- upsert ----------

    def test_upsert_persists_gate_report_and_errors(self):
        row = self.repo.upsert_phase_run(
            "doc1",
            3,
            status=PHASE_STATUS_FAILED,
            gate_pass=False,
            gate_report={"pass": False, "failures": [{"code": "x"}]},
            errors=[{"code": "y", "message": "oops"}],
        )
        self.assertEqual(row["status"], PHASE_STATUS_FAILED)
        self.assertFalse(row["gate_pass"])
        self.assertEqual(row["gate_report"]["failures"][0]["code"], "x")
        self.assertEqual(row["errors"][0]["code"], "y")

        # 再次 upsert 只改 status，gate_report 应保留
        row2 = self.repo.upsert_phase_run("doc1", 3, status=PHASE_STATUS_RUNNING)
        self.assertEqual(row2["status"], PHASE_STATUS_RUNNING)
        self.assertEqual(row2["gate_report"]["failures"][0]["code"], "x")

    def test_upsert_invalid_phase_raises(self):
        with self.assertRaises(ValueError):
            self.repo.upsert_phase_run("doc1", 7)
        with self.assertRaises(ValueError):
            self.repo.upsert_phase_run("doc1", 0)

    def test_upsert_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            self.repo.upsert_phase_run("doc1", 1, status="bogus")

    def test_upsert_empty_doc_id_raises(self):
        with self.assertRaises(ValueError):
            self.repo.upsert_phase_run("", 1)

    def test_execution_mode_and_forced_skip_round_trip(self):
        row = self.repo.upsert_phase_run(
            "doc1", 5, execution_mode="real", forced_skip=True
        )
        self.assertEqual(row["execution_mode"], "real")
        self.assertTrue(row["forced_skip"])

    # ---------- delete / cascade ----------

    def test_delete_phase_runs_from_cascades(self):
        self.repo.init_phase_runs("doc1")
        for phase in PHASES:
            self.repo.upsert_phase_run("doc1", phase, status=PHASE_STATUS_READY, gate_pass=True)

        deleted = self.repo.delete_phase_runs_from("doc1", 3)
        self.assertEqual(deleted, 4)  # phase 3, 4, 5, 6

        rows = self.repo.list_phase_runs("doc1")
        for row in rows:
            if row["phase"] < 3:
                self.assertEqual(row["status"], PHASE_STATUS_READY)
                self.assertIsNotNone(row["created_at"])
            else:
                self.assertEqual(row["status"], PHASE_STATUS_IDLE)
                self.assertIsNone(row["created_at"])

    def test_get_phase_run_returns_none_when_missing(self):
        self.assertIsNone(self.repo.get_phase_run("doc1", 1))
        self.repo.init_phase_runs("doc1")
        row = self.repo.get_phase_run("doc1", 1)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], PHASE_STATUS_IDLE)


class DevRepoSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self._tmp.close()
        self.db_path = self._tmp.name
        self.repo = SingleDBRepository(self.db_path)
        self.repo.upsert_document("doc1", "Book 1.pdf")
        self.repo.upsert_document("doc2", "Book 2.pdf")

    def tearDown(self) -> None:
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_save_and_list_snapshots(self):
        sid1 = self.repo.save_dev_snapshot("doc1", 3, "dev_snapshots/p3_a.json", size_bytes=1024)
        sid2 = self.repo.save_dev_snapshot("doc1", 3, "dev_snapshots/p3_b.json", size_bytes=2048, note="after fix")
        self.repo.save_dev_snapshot("doc1", 4, "dev_snapshots/p4.json", size_bytes=500)

        self.assertGreater(sid2, sid1)

        all_rows = self.repo.list_dev_snapshots("doc1")
        self.assertEqual(len(all_rows), 3)

        phase3 = self.repo.list_dev_snapshots("doc1", phase=3)
        self.assertEqual(len(phase3), 2)
        self.assertEqual(phase3[0]["size_bytes"], 2048)  # newest first

    def test_delete_snapshots_cascades(self):
        self.repo.save_dev_snapshot("doc1", 2, "a.json")
        self.repo.save_dev_snapshot("doc1", 3, "b.json")
        self.repo.save_dev_snapshot("doc1", 5, "c.json")
        self.repo.save_dev_snapshot("doc2", 3, "d.json")

        deleted = self.repo.delete_dev_snapshots_from("doc1", 3)
        self.assertEqual(deleted, 2)

        self.assertEqual(len(self.repo.list_dev_snapshots("doc1")), 1)
        self.assertEqual(len(self.repo.list_dev_snapshots("doc2")), 1)  # 他 doc 不受影响


if __name__ == "__main__":
    unittest.main()

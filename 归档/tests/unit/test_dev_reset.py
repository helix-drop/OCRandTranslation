"""FNM_RE/dev/reset.py 的单元测试。"""
from __future__ import annotations

import os
import tempfile
import unittest

from FNM_RE.dev.reset import reset_from_phase
from persistence.sqlite_repo_dev import (
    PHASE_STATUS_IDLE,
    PHASE_STATUS_READY,
)
from persistence.sqlite_store import SingleDBRepository


class ResetFromPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self._tmp_db.close()
        self.db_path = self._tmp_db.name
        self.repo = SingleDBRepository(self.db_path)
        self.repo.upsert_document("doc1", "book.pdf")
        self._tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _doc_dir(self, doc_id: str) -> str:
        return os.path.join(self._tmp_dir.name, doc_id)

    def _seed_phase1(self) -> None:
        """写入 Phase 1 产物 + 把 phase_runs 1 推到 ready。"""
        self.repo.replace_fnm_phase1_products(
            "doc1",
            pages=[{"page_no": 1, "target_pdf_page": 1, "page_role": "body"}],
            chapters=[],
            heading_candidates=[],
            section_heads=[],
        )
        self.repo.init_phase_runs("doc1")
        self.repo.upsert_phase_run(
            "doc1", 1, status=PHASE_STATUS_READY, gate_pass=True
        )

    def _seed_phase2(self) -> None:
        """写入 Phase 1+2 产物 + phase_runs 1/2 都到 ready。"""
        self.repo.replace_fnm_phase2_products(
            "doc1",
            pages=[{"page_no": 1, "target_pdf_page": 1, "page_role": "body"}],
            chapters=[],
            heading_candidates=[],
            section_heads=[],
            note_regions=[
                {
                    "region_id": "r1",
                    "region_kind": "footnote",
                    "start_page": 1,
                    "end_page": 1,
                    "pages": [1],
                    "title_hint": "",
                    "bound_chapter_id": "",
                }
            ],
            chapter_note_modes=[],
            note_items=[],
        )
        self.repo.init_phase_runs("doc1")
        self.repo.upsert_phase_run("doc1", 1, status=PHASE_STATUS_READY, gate_pass=True)
        self.repo.upsert_phase_run("doc1", 2, status=PHASE_STATUS_READY, gate_pass=True)

    # ------- 基本入参 --------

    def test_empty_doc_id_returns_error(self):
        result = reset_from_phase("", 1, repo=self.repo)
        self.assertFalse(result.ok)
        self.assertIn("doc_id", result.error)

    def test_invalid_phase_returns_error(self):
        result = reset_from_phase("doc1", 0, repo=self.repo)
        self.assertFalse(result.ok)
        result7 = reset_from_phase("doc1", 7, repo=self.repo)
        self.assertFalse(result7.ok)

    # ------- 级联清理 --------

    def test_reset_from_phase_2_clears_phase2_products_only(self):
        self._seed_phase2()
        pre_pages = self.repo.list_fnm_pages("doc1")
        pre_regions = self.repo.list_fnm_note_regions("doc1")
        self.assertEqual(len(pre_pages), 1)
        self.assertEqual(len(pre_regions), 1)

        result = reset_from_phase("doc1", 2, repo=self.repo)
        self.assertTrue(result.ok, msg=result.error)
        self.assertEqual(result.deleted_phase_runs, 5)  # phase 2..6

        # Phase 2 产物应被清空
        self.assertEqual(len(self.repo.list_fnm_note_regions("doc1")), 0)
        self.assertEqual(len(self.repo.list_fnm_note_items("doc1")), 0)
        # Phase 1 产物应被保留
        self.assertEqual(len(self.repo.list_fnm_pages("doc1")), 1)

        # phase_runs：1 仍 ready，2..6 回到 idle
        runs = self.repo.list_phase_runs("doc1")
        self.assertEqual(next(r for r in runs if r["phase"] == 1)["status"], PHASE_STATUS_READY)
        for phase in (2, 3, 4, 5, 6):
            row = next(r for r in runs if r["phase"] == phase)
            self.assertEqual(row["status"], PHASE_STATUS_IDLE)

    def test_reset_from_phase_1_clears_everything(self):
        self._seed_phase2()
        result = reset_from_phase("doc1", 1, repo=self.repo)
        self.assertTrue(result.ok)
        self.assertEqual(len(self.repo.list_fnm_pages("doc1")), 0)
        self.assertEqual(len(self.repo.list_fnm_note_regions("doc1")), 0)
        runs = self.repo.list_phase_runs("doc1")
        for row in runs:
            self.assertEqual(row["status"], PHASE_STATUS_IDLE)

    def test_reset_clears_dev_snapshots(self):
        self._seed_phase2()
        self.repo.save_dev_snapshot("doc1", 1, "a.json")
        self.repo.save_dev_snapshot("doc1", 2, "b.json")
        self.repo.save_dev_snapshot("doc1", 3, "c.json")

        result = reset_from_phase("doc1", 2, repo=self.repo)
        self.assertTrue(result.ok)
        self.assertEqual(result.deleted_snapshots, 2)  # phase 2 + 3
        self.assertEqual(len(self.repo.list_dev_snapshots("doc1")), 1)

    def test_reset_isolates_other_docs(self):
        self.repo.upsert_document("doc2", "other.pdf")
        self.repo.replace_fnm_phase1_products(
            "doc2",
            pages=[{"page_no": 1, "target_pdf_page": 1, "page_role": "body"}],
            chapters=[],
            heading_candidates=[],
            section_heads=[],
        )
        self.repo.init_phase_runs("doc2")
        self.repo.upsert_phase_run("doc2", 1, status=PHASE_STATUS_READY, gate_pass=True)

        self._seed_phase2()
        reset_from_phase("doc1", 1, repo=self.repo)

        # doc2 不受影响
        self.assertEqual(len(self.repo.list_fnm_pages("doc2")), 1)
        runs2 = self.repo.list_phase_runs("doc2")
        self.assertEqual(
            next(r for r in runs2 if r["phase"] == 1)["status"], PHASE_STATUS_READY
        )

    def test_reset_clears_dev_exports_dir(self):
        self._seed_phase2()
        exports_dir = os.path.join(self._doc_dir("doc1"), "dev_exports")
        os.makedirs(exports_dir, exist_ok=True)
        with open(os.path.join(exports_dir, "result.json"), "w") as fh:
            fh.write("{}")
        with open(os.path.join(exports_dir, "summary.md"), "w") as fh:
            fh.write("# x")

        result = reset_from_phase(
            "doc1", 6, repo=self.repo, get_doc_dir=self._doc_dir
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.deleted_export_files, 2)
        self.assertFalse(os.path.isdir(exports_dir))

    def test_reset_without_get_doc_dir_skips_exports(self):
        self._seed_phase2()
        result = reset_from_phase("doc1", 6, repo=self.repo)
        self.assertTrue(result.ok)
        self.assertEqual(result.deleted_export_files, 0)

    def test_reset_is_idempotent(self):
        self._seed_phase2()
        r1 = reset_from_phase("doc1", 2, repo=self.repo)
        r2 = reset_from_phase("doc1", 2, repo=self.repo)
        self.assertTrue(r1.ok)
        self.assertTrue(r2.ok)
        # 第二次没什么可删
        self.assertEqual(r2.deleted_snapshots, 0)
        # phase_runs 第二次仍会被 delete_phase_runs_from 删掉（init 后又回填）
        self.assertEqual(len(self.repo.list_fnm_note_regions("doc1")), 0)


if __name__ == "__main__":
    unittest.main()

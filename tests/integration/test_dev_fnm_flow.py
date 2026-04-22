"""FNM 开发模式端到端流程测试：P1 → P2 → reset(2) → P2。

使用 `test_example/Neuropsychoanalysis_Introduction`（实例里最小的一本）。
"""
from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path

import config
from config import create_doc, ensure_dirs
from FNM_RE.dev.phase_runner import execute_phase
from FNM_RE.dev.reset import reset_from_phase
from persistence.sqlite_repo_dev import (
    PHASE_STATUS_IDLE,
    PHASE_STATUS_READY,
)
from persistence.sqlite_store import SQLiteRepository, TOC_SOURCE_AUTO_VISUAL
from persistence.storage import save_pages_to_disk
from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc, load_pages


EXAMPLE_NAME = "Neuropsychoanalysis_Introduction"


class DevFnmFlowIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._original_config = {
            "CONFIG_DIR": config.CONFIG_DIR,
            "CONFIG_FILE": config.CONFIG_FILE,
            "DATA_DIR": config.DATA_DIR,
            "DOCS_DIR": config.DOCS_DIR,
            "CURRENT_FILE": config.CURRENT_FILE,
        }
        self.temp_root = (
            Path(__file__).resolve().parents[2]
            / "local_data"
            / "_test_runtime"
            / f"dev-fnm-flow-{uuid.uuid4().hex}"
        )
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self._patch_config_dirs(str(self.temp_root))
        ensure_dirs()

        self.doc_id = create_doc(f"{EXAMPLE_NAME}.pdf")
        self.repo = SQLiteRepository()
        pages = load_pages(EXAMPLE_NAME)
        toc_items = load_auto_visual_toc(EXAMPLE_NAME)
        save_pages_to_disk(pages, f"{EXAMPLE_NAME}.pdf", self.doc_id)
        self.repo.set_document_toc_for_source(self.doc_id, TOC_SOURCE_AUTO_VISUAL, toc_items)
        self.repo.set_document_toc_source_offset(self.doc_id, TOC_SOURCE_AUTO_VISUAL, 0)

        self.repo.init_phase_runs(self.doc_id)
        self.page_count = len(pages)

    def tearDown(self) -> None:
        for key, value in self._original_config.items():
            setattr(config, key, value)
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str) -> None:
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(config.CONFIG_DIR, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    # ---------- 主流程 ----------

    def test_phase1_then_phase2_then_reset_then_phase2(self):
        # Phase 1
        r1 = execute_phase(self.doc_id, 1, repo=self.repo, force_skip=True)
        self.assertTrue(r1.ok, msg=r1.error)
        self.assertEqual(r1.status, PHASE_STATUS_READY)
        pages_after_p1 = self.repo.list_fnm_pages(self.doc_id)
        self.assertGreater(len(pages_after_p1), 0)
        self.assertEqual(len(self.repo.list_fnm_note_regions(self.doc_id)), 0)

        runs = self.repo.list_phase_runs(self.doc_id)
        phase1 = next(r for r in runs if r["phase"] == 1)
        self.assertEqual(phase1["status"], PHASE_STATUS_READY)

        # Phase 2
        r2 = execute_phase(self.doc_id, 2, repo=self.repo, force_skip=True)
        self.assertTrue(r2.ok, msg=r2.error)
        self.assertEqual(r2.status, PHASE_STATUS_READY)
        # Phase 2 重算 Phase 1，pages 数量应保持一致
        pages_after_p2 = self.repo.list_fnm_pages(self.doc_id)
        self.assertEqual(len(pages_after_p2), len(pages_after_p1))

        # 记录 Phase 2 产物的基线
        p2_regions_before = self.repo.list_fnm_note_regions(self.doc_id)
        p2_note_items_before = self.repo.list_fnm_note_items(self.doc_id)

        # Reset from phase 2 → Phase 2 产物清空，Phase 1 保留
        reset_result = reset_from_phase(self.doc_id, 2, repo=self.repo)
        self.assertTrue(reset_result.ok, msg=reset_result.error)
        self.assertEqual(len(self.repo.list_fnm_note_regions(self.doc_id)), 0)
        self.assertEqual(len(self.repo.list_fnm_note_items(self.doc_id)), 0)
        self.assertEqual(len(self.repo.list_fnm_pages(self.doc_id)), len(pages_after_p1))

        runs_after_reset = self.repo.list_phase_runs(self.doc_id)
        self.assertEqual(
            next(r for r in runs_after_reset if r["phase"] == 1)["status"],
            PHASE_STATUS_READY,
        )
        self.assertEqual(
            next(r for r in runs_after_reset if r["phase"] == 2)["status"],
            PHASE_STATUS_IDLE,
        )

        # 再跑 Phase 2 —— 应恢复到重置前的相同产物规模
        r2b = execute_phase(self.doc_id, 2, repo=self.repo, force_skip=True)
        self.assertTrue(r2b.ok, msg=r2b.error)
        p2_regions_after = self.repo.list_fnm_note_regions(self.doc_id)
        p2_note_items_after = self.repo.list_fnm_note_items(self.doc_id)
        self.assertEqual(len(p2_regions_before), len(p2_regions_after))
        self.assertEqual(len(p2_note_items_before), len(p2_note_items_after))

    def test_unsupported_phase_returns_error(self):
        result = execute_phase(self.doc_id, 7, repo=self.repo)
        self.assertFalse(result.ok)
        self.assertIn("暂未接入", result.error)


if __name__ == "__main__":
    unittest.main()

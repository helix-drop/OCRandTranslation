from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path

import config
from config import create_doc, ensure_dirs
from FNM_RE import build_doc_status, build_export_bundle_for_doc, run_doc_pipeline
from persistence.sqlite_store import TOC_SOURCE_AUTO_VISUAL, SQLiteRepository
from persistence.storage import save_pages_to_disk
from persistence.storage_toc import save_toc_visual_manual_screenshots
from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc, load_pages


class FnmReMainlineBiopoliticsIntegrationTest(unittest.TestCase):
    def setUp(self):
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
            / f"fnm-re-mainline-biopolitics-{uuid.uuid4().hex}"
        )
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self._patch_config_dirs(str(self.temp_root))
        ensure_dirs()

        self.doc_id = create_doc("biopolitics-mainline.pdf")
        self.repo = SQLiteRepository()
        self.pages = load_pages("Biopolitics")
        self.toc_items = load_auto_visual_toc("Biopolitics")
        save_pages_to_disk(self.pages, "biopolitics-mainline.pdf", self.doc_id)
        self.repo.set_document_toc_for_source(self.doc_id, TOC_SOURCE_AUTO_VISUAL, self.toc_items)
        self.repo.set_document_toc_source_offset(self.doc_id, TOC_SOURCE_AUTO_VISUAL, 0)

        screenshot_source = self.temp_root / "toc-shot-1.png"
        screenshot_source.write_bytes(b"placeholder")
        save_toc_visual_manual_screenshots(
            self.doc_id,
            [{"path": str(screenshot_source), "filename": screenshot_source.name}],
        )

    def tearDown(self):
        for key, value in self._original_config.items():
            setattr(config, key, value)
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(config.CONFIG_DIR, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def test_mainline_common_entry_chain_produces_ready_status_and_export_bundle(self):
        pipeline_result = run_doc_pipeline(self.doc_id, repo=self.repo)
        status = build_doc_status(self.doc_id, repo=self.repo)
        bundle = build_export_bundle_for_doc(self.doc_id, repo=self.repo)

        self.assertTrue(pipeline_result.get("ok"))
        self.assertIn("structure_state", status)
        self.assertIsInstance(status.get("blocking_reasons"), list)
        self.assertEqual(status.get("structure_state"), "ready")
        self.assertEqual(status.get("blocking_reasons"), [])
        self.assertTrue(bool(status.get("export_ready_test")))
        self.assertTrue(bool(status.get("chapter_local_endnote_contract_ok")))

        self.assertIn("index_path", bundle)
        self.assertIn("chapters", bundle)
        self.assertIn("chapter_files", bundle)
        self.assertIn("files", bundle)
        self.assertIsInstance(bundle.get("chapters"), list)
        self.assertIsInstance(bundle.get("chapter_files"), dict)
        self.assertIsInstance(bundle.get("files"), dict)
        self.assertTrue(bundle["chapters"])
        self.assertIn(str(bundle.get("index_path") or ""), bundle["files"])
        self.assertTrue(all(str(row.get("path") or "") in bundle["chapter_files"] for row in bundle["chapters"]))
        self.assertTrue(bool(bundle.get("export_semantic_contract_ok")))


if __name__ == "__main__":
    unittest.main()

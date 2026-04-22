#!/usr/bin/env python3
"""拆库迁移测试。"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import config
from persistence.sqlite_catalog_store import CatalogRepository
from persistence.sqlite_db_paths import get_catalog_db_path, get_document_db_path
from persistence.sqlite_document_store import DocumentRepository
from persistence.sqlite_split_migration import migrate_legacy_app_db
from persistence.sqlite_store import SQLiteRepository


class SQLiteSplitMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="sqlite-split-migration-")
        self._patch_config_dirs(self.temp_root)
        config.ensure_dirs()
        self.legacy_db_path = config.get_sqlite_db_path()

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(config.CONFIG_DIR, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def test_migrate_legacy_app_db_moves_document_payload_into_doc_db(self):
        legacy_repo = SQLiteRepository(self.legacy_db_path)
        doc_id = "doc-migrate"
        legacy_repo.upsert_document(doc_id, "迁移测试", page_count=1, entry_count=1)
        legacy_repo.replace_pages(
            doc_id,
            [
                {
                    "bookPage": 1,
                    "fileIdx": 1,
                    "imgW": 1000,
                    "imgH": 1400,
                    "markdown": "legacy page",
                    "footnotes": "[1] note",
                    "textSource": "ocr",
                }
            ],
        )
        legacy_repo.save_translate_run(doc_id, phase="idle", running=0, done_pages=1, total_pages=1)
        legacy_repo.create_fnm_run(doc_id, status="done", page_count=1, section_count=1, note_count=1, unit_count=1)
        legacy_repo.set_app_state("current_doc_id", doc_id)
        legacy_repo.set_translation_title(doc_id, "迁移标题")

        report = migrate_legacy_app_db(
            legacy_db_path=self.legacy_db_path,
            catalog_db_path=get_catalog_db_path(),
            backup_legacy=False,
            overwrite_doc_dbs=True,
        )
        self.assertEqual(report["migrated_documents"], 1)
        self.assertEqual(report["migrated_doc_dbs"], 1)
        self.assertGreater(report["migrated_rows"], 0)

        catalog_repo = CatalogRepository(get_catalog_db_path())
        self.assertEqual(catalog_repo.get_document(doc_id)["name"], "迁移测试")
        self.assertEqual(catalog_repo.get_app_state("current_doc_id"), doc_id)

        doc_db_path = get_document_db_path(doc_id)
        self.assertTrue(os.path.exists(doc_db_path))
        doc_repo = DocumentRepository(doc_id)
        pages = doc_repo.load_pages(doc_id)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["markdown"], "legacy page")
        fnm_run = doc_repo.get_latest_fnm_run(doc_id)
        self.assertIsNotNone(fnm_run)
        self.assertEqual(fnm_run["status"], "done")
        self.assertEqual(doc_repo.get_translation_title(doc_id), "迁移标题")


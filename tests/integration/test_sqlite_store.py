#!/usr/bin/env python3
"""SQLite 基础存储层测试。"""

import os
import shutil
import sqlite3
import tempfile
import unittest
import json
from unittest.mock import patch

import config
import persistence.sqlite_schema as sqlite_schema
from persistence.sqlite_catalog_store import CatalogRepository
from persistence.sqlite_bootstrap import initialize_runtime_databases
from persistence.sqlite_db_paths import get_catalog_db_path, get_document_db_path
from persistence.sqlite_document_store import DocumentRepository
from persistence.sqlite_schema import _ensure_column
from persistence.sqlite_store import (
    SQLiteRepository,
    get_connection,
    initialize_database,
)


class SQLiteStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="sqlite-store-")
        self._patch_config_dirs(self.temp_root)
        config.ensure_dirs()
        self.db_path = config.get_sqlite_db_path()

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def test_initialize_database_enables_wal_and_creates_core_tables(self):
        journal_mode = initialize_database(self.db_path)

        self.assertEqual(journal_mode.lower(), "wal")
        with get_connection(self.db_path) as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

        self.assertIn("documents", tables)
        self.assertIn("pages", tables)
        self.assertIn("translation_pages", tables)
        self.assertIn("translation_segments", tables)
        self.assertIn("translate_runs", tables)
        self.assertIn("translate_failures", tables)
        self.assertIn("app_state", tables)
        self.assertIn("fnm_runs", tables)
        self.assertIn("fnm_translation_units", tables)
        retired_v2_tables = {
            name
            for name in tables
            if name.startswith("fnm_")
            and name.endswith("_v2")
            and name != "fnm_review_overrides_v2"
        }
        self.assertFalse(retired_v2_tables)
        self.assertIn("fnm_chapters", tables)
        self.assertIn("fnm_note_items", tables)
        self.assertNotIn("fnm_notes", tables)
        self.assertNotIn("fnm_page_entries", tables)
        self.assertNotIn("fnm_page_revisions", tables)
        self.assertIn("fnm_chapter_endnotes", tables)
        self.assertIn("fnm_paragraph_footnotes", tables)
        self.assertIn("fnm_chapter_anchor_alignment", tables)

        with get_connection(self.db_path) as conn:
            body_anchor_cols = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(fnm_body_anchors)"
                ).fetchall()
            }
        self.assertIn("attached_paragraph_key", body_anchor_cols)
        self.assertIn("resolved_ordinal", body_anchor_cols)
        self.assertIn("alignment_status", body_anchor_cols)

        with get_connection(self.db_path) as conn:
            translation_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(translation_pages)"
                ).fetchall()
            }
            run_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(translate_runs)").fetchall()
            }

        self.assertIn("model_source", translation_columns)
        self.assertIn("model_id", translation_columns)
        self.assertIn("provider", translation_columns)
        self.assertIn("model_source", run_columns)
        self.assertIn("model_id", run_columns)
        self.assertIn("provider", run_columns)

    def test_initialize_database_skips_schema_rewrite_after_current_version_is_ready(
        self,
    ):
        initialize_database(self.db_path)

        with patch.object(
            sqlite_schema,
            "_create_schema",
            side_effect=AssertionError("schema should not rewrite"),
        ):
            journal_mode = initialize_database(self.db_path)

        self.assertEqual(journal_mode.lower(), "wal")

    def test_initialize_database_repairs_current_version_missing_translate_tail_columns(
        self,
    ):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO schema_meta(key, value) VALUES ('schema_version', '23');
                CREATE TABLE translate_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    running INTEGER NOT NULL DEFAULT 0,
                    stop_requested INTEGER NOT NULL DEFAULT 0,
                    failed_bps_json TEXT,
                    partial_failed_bps_json TEXT,
                    failed_pages_json TEXT,
                    retry_round INTEGER NOT NULL DEFAULT 0,
                    unresolved_count INTEGER NOT NULL DEFAULT 0,
                    manual_required_count INTEGER NOT NULL DEFAULT 0,
                    next_failed_location_json TEXT,
                    failed_locations_json TEXT,
                    manual_required_locations_json TEXT,
                    task_json TEXT,
                    draft_json TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )

        initialize_database(self.db_path)

        with get_connection(self.db_path) as conn:
            run_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(translate_runs)").fetchall()
            }

        self.assertIn("fnm_tail_state", run_columns)
        self.assertIn("export_bundle_available", run_columns)
        self.assertIn("export_has_blockers", run_columns)
        self.assertIn("tail_blocking_summary_json", run_columns)
        self.assertIn("translation_attempt_history_json", run_columns)

    def test_latest_translate_run_handles_legacy_row_missing_tail_columns(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO schema_meta(key, value) VALUES ('schema_version', '23');
                CREATE TABLE documents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE translate_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    model_key TEXT,
                    running INTEGER NOT NULL DEFAULT 0,
                    stop_requested INTEGER NOT NULL DEFAULT 0,
                    failed_bps_json TEXT,
                    partial_failed_bps_json TEXT,
                    failed_pages_json TEXT,
                    retry_round INTEGER NOT NULL DEFAULT 0,
                    unresolved_count INTEGER NOT NULL DEFAULT 0,
                    manual_required_count INTEGER NOT NULL DEFAULT 0,
                    next_failed_location_json TEXT,
                    failed_locations_json TEXT,
                    manual_required_locations_json TEXT,
                    task_json TEXT,
                    draft_json TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                INSERT INTO documents(id, name, created_at, updated_at)
                VALUES ('doc-legacy-tail', 'Legacy Tail', 1, 1);
                INSERT INTO translate_runs(
                    doc_id, phase, model_key, running, stop_requested,
                    failed_bps_json, partial_failed_bps_json, failed_pages_json,
                    next_failed_location_json, failed_locations_json, manual_required_locations_json,
                    task_json, draft_json, created_at, updated_at
                )
                VALUES (
                    'doc-legacy-tail', 'done', 'deepseek-chat', 0, 0,
                    '[]', '[]', '[]',
                    'null', '[]', '[]',
                    '{}', '{}', 1, 1
                );
                """
            )

        run = SQLiteRepository(self.db_path).get_latest_translate_run("doc-legacy-tail")

        self.assertIsNotNone(run)
        self.assertEqual(run["phase"], "done")
        self.assertEqual(run["fnm_tail_state"], "idle")
        self.assertEqual(run["tail_blocking_summary"], [])
        self.assertEqual(run["translation_attempt_history"], [])

    def test_catalog_repository_uses_catalog_db_path(self):
        expected = get_catalog_db_path()
        repo = CatalogRepository()
        repo.upsert_document("doc-cat", "Catalog Doc", page_count=1)

        self.assertEqual(repo.db_path, expected)
        self.assertTrue(os.path.exists(expected))
        self.assertEqual(repo.get_document("doc-cat")["name"], "Catalog Doc")

    def test_document_repository_uses_document_db_path(self):
        expected = get_document_db_path("doc-abc")
        repo = DocumentRepository("doc-abc")
        repo.upsert_document("doc-abc", "Doc Repo", page_count=2)

        self.assertEqual(repo.db_path, expected)
        self.assertTrue(os.path.exists(expected))
        self.assertEqual(repo.get_document("doc-abc")["name"], "Doc Repo")

    def test_initialize_runtime_databases_supports_catalog_and_document_dbs(self):
        catalog_path = get_catalog_db_path()
        doc_path = get_document_db_path("doc-init")

        modes = initialize_runtime_databases(
            include_legacy_app_db=True,
            include_catalog_db=True,
            document_ids=["doc-init"],
        )

        self.assertIn(self.db_path, modes)
        self.assertIn(catalog_path, modes)
        self.assertIn(doc_path, modes)
        self.assertEqual(modes[self.db_path].lower(), "wal")
        self.assertEqual(modes[catalog_path].lower(), "wal")
        self.assertEqual(modes[doc_path].lower(), "wal")
        with get_connection(catalog_path) as conn:
            catalog_tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("documents", catalog_tables)
        self.assertIn("app_state", catalog_tables)
        self.assertNotIn("pages", catalog_tables)

    def test_initialize_runtime_databases_defaults_to_catalog_without_legacy_app_db(
        self,
    ):
        modes = initialize_runtime_databases()
        catalog_path = get_catalog_db_path()

        self.assertIn(catalog_path, modes)
        self.assertNotIn(self.db_path, modes)
        self.assertFalse(os.path.exists(self.db_path))

    def test_glossary_state_is_written_to_doc_db_in_split_mode(self):
        doc_id = "doc-glossary"
        repo = SQLiteRepository()
        repo.upsert_document(doc_id, "Glossary Doc")

        config.set_glossary([["term-a", "定义-a"]], doc_id=doc_id)

        with get_connection(get_catalog_db_path()) as catalog_conn:
            catalog_row = catalog_conn.execute(
                "SELECT state_value FROM app_state WHERE state_key = ?",
                (f"glossary:{doc_id}",),
            ).fetchone()
        with get_connection(get_document_db_path(doc_id)) as doc_conn:
            doc_row = doc_conn.execute(
                "SELECT state_value FROM app_state WHERE state_key = ?",
                (f"glossary:{doc_id}",),
            ).fetchone()

        self.assertIsNone(catalog_row)
        self.assertIsNotNone(doc_row)
        self.assertEqual(json.loads(doc_row["state_value"]), [["term-a", "定义-a"]])

    def test_delete_document_cleans_catalog_doc_scoped_state_keys(self):
        doc_id = "doc-delete-state"
        repo = SQLiteRepository()
        repo.upsert_document(doc_id, "Delete State Doc")
        doc_dir = os.path.join(config.DOCS_DIR, doc_id)
        os.makedirs(doc_dir, exist_ok=True)

        catalog_repo = CatalogRepository()
        catalog_repo.set_app_state(
            f"glossary:{doc_id}", json.dumps([["term", "定义"]], ensure_ascii=False)
        )

        config.delete_doc(doc_id)

        with get_connection(get_catalog_db_path()) as conn:
            state_row = conn.execute(
                "SELECT state_value FROM app_state WHERE state_key = ?",
                (f"glossary:{doc_id}",),
            ).fetchone()
            doc_row = conn.execute(
                "SELECT id FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()

        self.assertIsNone(state_row)
        self.assertIsNone(doc_row)
        self.assertFalse(os.path.isdir(doc_dir))

    def test_delete_doc_renames_directory_and_cleans_in_background(self):
        doc_id = "doc-delete-async"
        repo = SQLiteRepository()
        repo.upsert_document(doc_id, "Delete Async Doc")
        doc_dir = os.path.join(config.DOCS_DIR, doc_id)
        os.makedirs(doc_dir, exist_ok=True)
        with open(os.path.join(doc_dir, "temp.bin"), "wb") as f:
            f.write(b"123")

        started = []

        class ImmediateThread:
            def __init__(
                self, target=None, args=(), kwargs=None, daemon=None, name=None
            ):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}
                started.append({"daemon": daemon, "name": name})

            def start(self):
                if self._target is not None:
                    self._target(*self._args, **self._kwargs)

        with patch.object(config.threading, "Thread", ImmediateThread):
            config.delete_doc(doc_id)

        with get_connection(get_catalog_db_path()) as conn:
            row = conn.execute(
                "SELECT id FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()

        self.assertIsNone(row)
        self.assertFalse(os.path.isdir(doc_dir))
        self.assertTrue(started)
        self.assertTrue(all(item["daemon"] for item in started))
        leftovers = [
            name
            for name in os.listdir(config.DOCS_DIR)
            if name.startswith(f".deleting-{doc_id}-")
        ]
        self.assertEqual(leftovers, [])

    def test_repository_persists_fnm_data_without_touching_standard_translation_pages(
        self,
    ):
        repo = SQLiteRepository(self.db_path)
        repo.upsert_document("doc-fnm", "FNM Doc", page_count=3)

        run_id = repo.create_fnm_run(
            "doc-fnm",
            status="running",
            page_count=3,
            section_count=1,
            note_count=2,
            unit_count=3,
        )
        self.assertGreater(run_id, 0)

        repo.replace_fnm_structure(
            "doc-fnm",
            pages=[
                {
                    "page_no": 1,
                    "target_pdf_page": 1,
                    "page_role": "body",
                    "role_confidence": 1.0,
                    "role_reason": "test",
                    "section_hint": "Demo",
                    "has_note_heading": False,
                    "note_scan_summary": {},
                },
                {
                    "page_no": 2,
                    "target_pdf_page": 2,
                    "page_role": "body",
                    "role_confidence": 1.0,
                    "role_reason": "test",
                    "section_hint": "Demo",
                    "has_note_heading": False,
                    "note_scan_summary": {},
                },
                {
                    "page_no": 3,
                    "target_pdf_page": 3,
                    "page_role": "note",
                    "role_confidence": 1.0,
                    "role_reason": "test",
                    "section_hint": "Demo",
                    "has_note_heading": True,
                    "note_scan_summary": {"page_kind": "chapter_endnotes"},
                },
            ],
            chapters=[
                {
                    "chapter_id": "sec-01-demo",
                    "title": "Demo",
                    "start_page": 1,
                    "end_page": 2,
                    "pages": [1, 2],
                    "source": "test",
                    "boundary_state": "ready",
                }
            ],
            heading_candidates=[],
            note_regions=[
                {
                    "region_id": "reg-01-demo",
                    "region_kind": "chapter_endnotes",
                    "start_page": 3,
                    "end_page": 3,
                    "pages": [3],
                    "title_hint": "Demo notes",
                    "bound_chapter_id": "sec-01-demo",
                    "region_start_first_source_marker": "1",
                    "region_first_note_item_marker": "1",
                    "region_marker_alignment_ok": True,
                }
            ],
            chapter_note_modes=[
                {
                    "chapter_id": "sec-01-demo",
                    "chapter_title": "Demo",
                    "note_mode": "mixed_or_unclear",
                    "sampled_pages": [1, 2, 3],
                    "detection_confidence": 1.0,
                }
            ],
            section_heads=[],
            note_items=[
                {
                    "note_item_id": "fn-01-0001",
                    "note_kind": "footnote",
                    "chapter_id": "sec-01-demo",
                    "region_id": "",
                    "marker": "1",
                    "normalized_marker": "1",
                    "occurrence": 1,
                    "source_text": "脚注原文",
                    "page_no": 1,
                    "display_marker": "1",
                    "source_marker": "1",
                    "title_hint": "",
                },
                {
                    "note_item_id": "en-01-0001",
                    "note_kind": "endnote",
                    "chapter_id": "sec-01-demo",
                    "region_id": "reg-01-demo",
                    "marker": "1",
                    "normalized_marker": "1",
                    "occurrence": 1,
                    "source_text": "尾注原文",
                    "page_no": 3,
                    "display_marker": "1",
                    "source_marker": "1",
                    "title_hint": "",
                },
            ],
            body_anchors=[],
            note_links=[],
            structure_reviews=[],
        )
        repo.replace_fnm_data(
            "doc-fnm",
            preserve_structure=True,
            notes=[],
            units=[
                {
                    "unit_id": "body-sec-01-demo-0001",
                    "kind": "body",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 3,
                    "page_start": 1,
                    "page_end": 2,
                    "char_count": 12,
                    "source_text": "body source",
                    "translated_text": "body translated",
                    "status": "done",
                    "error_msg": "",
                    "note_id": None,
                    "target_ref": "",
                    "page_segments": [
                        {
                            "page_no": 1,
                            "source_text": "page 1",
                            "display_text": "page 1",
                            "translated_text": "第一页译文",
                            "paragraphs": [
                                {
                                    "order": 1,
                                    "kind": "body",
                                    "heading_level": 0,
                                    "source_text": "page 1",
                                    "display_text": "page 1",
                                    "cross_page": None,
                                    "consumed_by_prev": False,
                                    "section_path": ["Demo"],
                                    "print_page_label": "1",
                                    "translated_text": "第一页译文",
                                }
                            ],
                        },
                        {
                            "page_no": 2,
                            "source_text": "page 2",
                            "display_text": "page 2",
                            "translated_text": "第二页译文",
                            "paragraphs": [
                                {
                                    "order": 1,
                                    "kind": "body",
                                    "heading_level": 0,
                                    "source_text": "page 2",
                                    "display_text": "page 2",
                                    "cross_page": None,
                                    "consumed_by_prev": False,
                                    "section_path": ["Demo"],
                                    "print_page_label": "2",
                                    "translated_text": "第二页译文",
                                }
                            ],
                        },
                    ],
                },
                {
                    "unit_id": "footnote-fn-01-0001",
                    "kind": "footnote",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 3,
                    "page_start": 1,
                    "page_end": 1,
                    "char_count": 4,
                    "source_text": "脚注原文",
                    "translated_text": "脚注译文",
                    "status": "done",
                    "error_msg": "",
                    "note_id": "fn-01-0001",
                    "target_ref": "{{FN_REF:fn-01-0001}}",
                    "page_segments": [],
                },
                {
                    "unit_id": "endnote-en-01-0001",
                    "kind": "endnote",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 3,
                    "page_start": 3,
                    "page_end": 3,
                    "char_count": 4,
                    "source_text": "尾注原文",
                    "translated_text": "尾注译文",
                    "status": "done",
                    "error_msg": "",
                    "note_id": "en-01-0001",
                    "target_ref": "{{EN_REF:en-01-0001}}",
                    "page_segments": [],
                },
            ],
        )
        repo.update_fnm_run(
            "doc-fnm",
            run_id,
            status="done",
            error_msg="",
            page_count=3,
            section_count=1,
            note_count=2,
            unit_count=3,
        )

        fnm_run = repo.get_latest_fnm_run("doc-fnm")
        notes = repo.list_fnm_diagnostic_notes("doc-fnm")
        units = repo.list_fnm_translation_units("doc-fnm")
        page_entry = repo.get_fnm_diagnostic_page("doc-fnm", 1)
        standard_page = repo.get_effective_translation_page("doc-fnm", 1)

        self.assertIsNotNone(fnm_run)
        self.assertEqual(fnm_run["status"], "done")
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]["section_title"], "Demo")
        self.assertEqual(len(units), 3)
        self.assertEqual(units[0]["section_title"], "Demo")
        self.assertEqual(units[0]["page_segments"][0]["page_no"], 1)
        self.assertIsNotNone(page_entry)
        self.assertEqual(page_entry["_page_entries"][0]["translation"], "第一页译文")
        self.assertEqual(page_entry["_fnm_source"]["section_id"], "sec-01-demo")
        self.assertIsNone(standard_page)

    def test_repository_persists_document_pages_run_and_segments(self):
        repo = SQLiteRepository(self.db_path)
        source_pdf_path = os.path.join(self.temp_root, "doc-1.pdf")
        repo.upsert_document(
            "doc-1",
            "Doc One",
            page_count=2,
            entry_count=1,
            has_pdf=1,
            last_entry_idx=0,
            status="ready",
            source_pdf_path=source_pdf_path,
        )
        repo.replace_pages(
            "doc-1",
            [
                {
                    "bookPage": 7,
                    "fileIdx": 0,
                    "imgW": 1000,
                    "imgH": 1600,
                    "markdown": "Page 7 markdown",
                    "footnotes": "fn-7",
                    "textSource": "ocr",
                },
                {
                    "bookPage": 8,
                    "fileIdx": 1,
                    "imgW": 1000,
                    "imgH": 1600,
                    "markdown": "Page 8 markdown",
                    "footnotes": "",
                    "textSource": "pdf",
                },
            ],
        )
        run_id = repo.save_translate_run(
            "doc-1",
            phase="running",
            model_source="custom",
            model_key="qwen-plus",
            model_id="qwen3.5-plus",
            provider="qwen",
            start_bp=7,
            current_bp=8,
            resume_bp=8,
            running=1,
            total_pages=2,
            done_pages=1,
            translated_paras=4,
            translated_chars=120,
            total_tokens=320,
            request_count=2,
            draft={"bp": 8, "status": "running"},
        )
        translation_page_id = repo.save_translation_page(
            "doc-1",
            7,
            {
                "_model": "qwen3.5-plus",
                "_model_source": "custom",
                "_model_key": "qwen-plus",
                "_model_id": "qwen3.5-plus",
                "_provider": "qwen",
                "_status": "done",
                "pages": "7",
                "_usage": {"total_tokens": 20},
                "_page_entries": [
                    {
                        "original": "Paragraph A",
                        "translation": "段落 A",
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                        "_status": "done",
                    },
                    {
                        "original": "Paragraph B",
                        "translation": "段落 B",
                        "footnotes": "fn",
                        "footnotes_translation": "脚注",
                        "heading_level": 1,
                        "_status": "done",
                    },
                ],
            },
        )
        repo.set_app_state("current_doc_id", "doc-1")

        self.assertGreater(run_id, 0)
        self.assertGreater(translation_page_id, 0)
        self.assertEqual(repo.get_app_state("current_doc_id"), "doc-1")

        latest_run = repo.get_latest_translate_run("doc-1")
        self.assertEqual(latest_run["phase"], "running")
        self.assertEqual(latest_run["resume_bp"], 8)
        self.assertEqual(latest_run["total_tokens"], 320)
        self.assertEqual(latest_run["model_source"], "custom")
        self.assertEqual(latest_run["model_id"], "qwen3.5-plus")
        self.assertEqual(latest_run["provider"], "qwen")

        segments = repo.list_translation_segments(translation_page_id)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["original_text"], "Paragraph A")
        self.assertEqual(segments[1]["translation_text"], "段落 B")
        self.assertEqual(segments[1]["heading_level"], 1)

        with get_connection(self.db_path) as conn:
            doc_row = conn.execute(
                "SELECT * FROM documents WHERE id = ?",
                ("doc-1",),
            ).fetchone()
            page_rows = conn.execute(
                "SELECT * FROM pages WHERE doc_id = ? ORDER BY book_page ASC",
                ("doc-1",),
            ).fetchall()

        self.assertEqual(doc_row["name"], "Doc One")
        self.assertEqual(doc_row["has_pdf"], 1)
        self.assertEqual(len(page_rows), 2)
        self.assertEqual(page_rows[1]["text_source"], "pdf")

        page = repo.get_effective_translation_page("doc-1", 7)
        self.assertEqual(page["_model"], "qwen3.5-plus")
        self.assertEqual(page["_model_source"], "custom")
        self.assertEqual(page["_model_key"], "qwen-plus")
        self.assertEqual(page["_model_id"], "qwen3.5-plus")
        self.assertEqual(page["_provider"], "qwen")

    def test_translation_segments_follow_translation_page_cascade_delete(self):
        repo = SQLiteRepository(self.db_path)
        repo.upsert_document("doc-2", "Doc Two")
        translation_page_id = repo.save_translation_page(
            "doc-2",
            16,
            {
                "_model": "qwen-plus",
                "_page_entries": [
                    {
                        "original": "Paragraph A",
                        "translation": "段落 A",
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                    }
                ],
            },
        )

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                "DELETE FROM translation_pages WHERE id = ?", (translation_page_id,)
            )
            rows = conn.execute(
                "SELECT COUNT(*) FROM translation_segments WHERE translation_page_id = ?",
                (translation_page_id,),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(rows[0], 0)

    def test_effective_run_prefers_active_then_latest_terminal(self):
        repo = SQLiteRepository(self.db_path)
        repo.upsert_document("doc-3", "Doc Three")

        # 先写入一个 terminal run
        first_run_id = repo.save_translate_run(
            "doc-3",
            phase="stopped",
            running=0,
            stop_requested=0,
            start_bp=7,
            current_bp=8,
            resume_bp=8,
            total_pages=20,
            done_pages=5,
            processed_pages=6,
            pending_pages=14,
            failed_pages=[{"bp": 9, "error": "boom"}],
        )
        self.assertGreater(first_run_id, 0)

        # 再写入 active run，effective 应优先 active
        second_run_id = repo.save_translate_run(
            "doc-3",
            phase="running",
            running=1,
            stop_requested=0,
            start_bp=7,
            current_bp=10,
            resume_bp=10,
            total_pages=20,
            done_pages=6,
            processed_pages=7,
            pending_pages=13,
            failed_pages=[],
        )
        self.assertEqual(second_run_id, first_run_id)

        effective = repo.get_effective_translate_run("doc-3")
        self.assertEqual(effective["phase"], "running")
        self.assertTrue(effective["running"])
        self.assertEqual(effective["current_bp"], 10)

        # 写回 terminal 后，effective 应回落到最新 terminal
        repo.save_translate_run(
            "doc-3",
            phase="stopped",
            running=0,
            stop_requested=0,
            start_bp=7,
            current_bp=11,
            resume_bp=11,
            total_pages=20,
            done_pages=7,
            processed_pages=8,
            pending_pages=12,
            failed_pages=[],
        )
        effective2 = repo.get_effective_translate_run("doc-3")
        self.assertEqual(effective2["phase"], "stopped")
        self.assertFalse(effective2["running"])
        self.assertEqual(effective2["resume_bp"], 11)

    def test_manual_revision_overrides_effective_segment_translation(self):
        repo = SQLiteRepository(self.db_path)
        repo.upsert_document("doc-4", "Doc Four")
        repo.save_translation_page(
            "doc-4",
            16,
            {
                "_model": "qwen-plus",
                "_status": "done",
                "pages": "16",
                "_usage": {"total_tokens": 8},
                "_page_entries": [
                    {
                        "original": "Paragraph A",
                        "translation": "机器译文 A",
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                        "_status": "done",
                    }
                ],
            },
        )

        updated = repo.save_manual_translation_segment(
            "doc-4",
            16,
            0,
            "人工修订 A",
            updated_by="local_user",
        )
        page = repo.get_effective_translation_page("doc-4", 16)

        self.assertEqual(updated["translation"], "人工修订 A")
        self.assertEqual(updated["_machine_translation"], "机器译文 A")
        self.assertEqual(updated["_translation_source"], "manual")
        self.assertEqual(page["_page_entries"][0]["translation"], "人工修订 A")
        self.assertEqual(page["_page_entries"][0]["_machine_translation"], "机器译文 A")
        self.assertEqual(page["_page_entries"][0]["_translation_source"], "manual")

    def _make_page_with_segment(self, repo, doc_id, book_page, translation_text):
        """Helper: upsert doc + page + 1 segment, return translation_page_id."""
        repo.upsert_document(doc_id, f"Doc {doc_id}")
        return repo.save_translation_page(
            doc_id,
            book_page,
            {
                "_model": "qwen-plus",
                "_status": "done",
                "pages": str(book_page),
                "_usage": {"total_tokens": 5},
                "_page_entries": [
                    {
                        "original": "Original text",
                        "translation": translation_text,
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                        "_status": "done",
                    }
                ],
            },
        )

    def test_schema_has_segment_revisions_table(self):
        initialize_database(self.db_path)
        with get_connection(self.db_path) as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("segment_revisions", tables)

    def test_ensure_column_ignores_duplicate_column_race(self):
        with get_connection(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS race_demo (id INTEGER PRIMARY KEY)"
            )
            conn.execute("ALTER TABLE race_demo ADD COLUMN late_col TEXT")
            _ensure_column(conn, "race_demo", "late_col", "late_col TEXT")

    def test_get_connection_closes_connection_when_pragmas_fail(self):
        class FakeConnection:
            def __init__(self):
                self.row_factory = None
                self.closed = False

            def close(self):
                self.closed = True

        conn = FakeConnection()
        with (
            patch("persistence.sqlite_schema.sqlite3.connect", return_value=conn),
            patch(
                "persistence.sqlite_schema._apply_pragmas",
                side_effect=RuntimeError("pragma boom"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "pragma boom"):
                get_connection(self.db_path)

        self.assertTrue(conn.closed)

    def test_get_connection_context_manager_closes_connection_on_exit(self):
        with get_connection(self.db_path) as conn:
            conn.execute("SELECT 1").fetchone()

        with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
            conn.execute("SELECT 1").fetchone()

    def test_manual_revision_creates_history_entry(self):
        repo = SQLiteRepository(self.db_path)
        self._make_page_with_segment(repo, "hist-1", 7, "机器译文 X")

        repo.save_manual_translation_segment("hist-1", 7, 0, "人工修订 X")
        revisions = repo.list_segment_revisions("hist-1", 7, 0)

        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0]["translation_text"], "机器译文 X")
        self.assertEqual(revisions[0]["revision_source"], "model")

    def test_retranslate_preserves_history(self):
        repo = SQLiteRepository(self.db_path)
        self._make_page_with_segment(repo, "hist-2", 10, "机器译文 Y")
        repo.save_manual_translation_segment("hist-2", 10, 0, "人工修订 Y")

        # Retranslate: save_translation_page again for same page
        repo.save_translation_page(
            "hist-2",
            10,
            {
                "_model": "qwen-plus",
                "_status": "done",
                "pages": "10",
                "_usage": {"total_tokens": 5},
                "_page_entries": [
                    {
                        "original": "Original text",
                        "translation": "新机器译文 Y",
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                        "_status": "done",
                    }
                ],
            },
        )

        revisions = repo.list_segment_revisions("hist-2", 10, 0)
        # Should have 2 entries: the model snapshot (from manual save) and the manual snapshot (from retranslate)
        self.assertGreaterEqual(len(revisions), 1)
        translation_texts = [r["translation_text"] for r in revisions]
        # The manual text must be captured before retranslate deleted it
        manual_texts = [r.get("manual_translation_text") for r in revisions]
        self.assertTrue(
            "人工修订 Y" in manual_texts or "人工修订 Y" in translation_texts,
            f"Expected '人工修订 Y' in history. revisions={revisions}",
        )

    def test_history_does_not_affect_effective_translation(self):
        repo = SQLiteRepository(self.db_path)
        tp_id = self._make_page_with_segment(repo, "hist-3", 5, "机器译文 Z")
        repo.save_manual_translation_segment("hist-3", 5, 0, "人工修订 Z")

        # Multiple revision entries should not pollute current segments
        revisions = repo.list_segment_revisions("hist-3", 5, 0)
        self.assertGreater(len(revisions), 0)

        segments = repo.list_translation_segments(tp_id)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["translation"], "人工修订 Z")

    def test_count_manual_segments_returns_correct_count(self):
        repo = SQLiteRepository(self.db_path)
        repo.upsert_document("hist-4", "Doc hist-4")
        repo.save_translation_page(
            "hist-4",
            3,
            {
                "_model": "qwen-plus",
                "_status": "done",
                "pages": "3",
                "_usage": {},
                "_page_entries": [
                    {
                        "original": "Para A",
                        "translation": "译 A",
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                        "_status": "done",
                    },
                    {
                        "original": "Para B",
                        "translation": "译 B",
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                        "_status": "done",
                    },
                ],
            },
        )

        self.assertEqual(repo.count_manual_segments("hist-4", 3), 0)
        repo.save_manual_translation_segment("hist-4", 3, 0, "人工修订 A")
        self.assertEqual(repo.count_manual_segments("hist-4", 3), 1)
        repo.save_manual_translation_segment("hist-4", 3, 1, "人工修订 B")
        self.assertEqual(repo.count_manual_segments("hist-4", 3), 2)

    def test_document_toc_roundtrip(self):
        repo = SQLiteRepository(self.db_path)
        repo.upsert_document("doc-toc", "Doc Toc")
        toc = [
            {"title": "Chapter 1", "depth": 0, "file_idx": 0},
            {"title": "Section 1.1", "depth": 1, "file_idx": 3},
        ]

        repo.set_document_toc("doc-toc", toc)

        loaded = repo.get_document_toc("doc-toc")
        self.assertEqual(loaded, toc)


class FnmNewTablesTest(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="fnm-new-tables-")
        self._patch_config_dirs(self.temp_root)
        config.ensure_dirs()
        self.db_path = config.get_sqlite_db_path()
        initialize_database(self.db_path)
        self.repo = SQLiteRepository(self.db_path)
        self.repo.upsert_document("doc1", "Doc One")

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def test_chapter_endnotes_crud(self):
        self.repo.replace_fnm_chapter_endnotes(
            "doc1",
            "ch-1",
            endnotes=[
                {
                    "ordinal": 1,
                    "marker": "1",
                    "text": "First endnote",
                    "source_page_no": 10,
                },
                {
                    "ordinal": 2,
                    "marker": "2",
                    "text": "Second endnote",
                    "source_page_no": 11,
                },
            ],
        )
        items = self.repo.list_fnm_chapter_endnotes("doc1", chapter_id="ch-1")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["ordinal"], 1)
        self.assertEqual(items[0]["marker"], "1")
        self.assertEqual(items[0]["text"], "First endnote")
        self.assertEqual(items[1]["ordinal"], 2)
        self.assertEqual(items[1]["review_required"], 1)

        self.repo.replace_fnm_chapter_endnotes(
            "doc1",
            "ch-1",
            endnotes=[{"ordinal": 1, "marker": "A", "text": "Replaced"}],
        )
        items = self.repo.list_fnm_chapter_endnotes("doc1", chapter_id="ch-1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "Replaced")

    def test_chapter_endnotes_ordinal_sequence(self):
        self.repo.replace_fnm_chapter_endnotes(
            "doc1",
            "ch-1",
            endnotes=[
                {"ordinal": 1, "marker": "1", "text": "Note 1"},
                {"ordinal": 3, "marker": "3", "text": "Note 3"},
            ],
        )
        items = self.repo.list_fnm_chapter_endnotes("doc1", chapter_id="ch-1")
        ordinals = [item["ordinal"] for item in items]
        self.assertNotEqual(ordinals, [1, 2])

    def test_paragraph_footnotes_crud(self):
        self.repo.replace_fnm_paragraph_footnotes(
            "doc1",
            "ch-1",
            footnotes=[
                {
                    "page_no": 5,
                    "paragraph_index": 0,
                    "source_marker": "1",
                    "text": "Fn 1",
                },
                {
                    "page_no": 5,
                    "paragraph_index": 1,
                    "source_marker": "2",
                    "text": "Fn 2",
                },
            ],
        )
        items = self.repo.list_fnm_paragraph_footnotes("doc1", chapter_id="ch-1")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["page_no"], 5)
        self.assertEqual(items[0]["attachment_kind"], "page_tail")

        items_p5 = self.repo.list_fnm_paragraph_footnotes(
            "doc1", chapter_id="ch-1", page_no=5
        )
        self.assertEqual(len(items_p5), 2)

    def test_chapter_anchor_alignment_upsert(self):
        self.repo.upsert_fnm_chapter_anchor_alignment(
            "doc1",
            "ch-1",
            alignment_status="clean",
            body_anchor_count=10,
            endnote_count=10,
        )
        records = self.repo.list_fnm_chapter_anchor_alignment("doc1", chapter_id="ch-1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["alignment_status"], "clean")
        self.assertEqual(records[0]["body_anchor_count"], 10)

        self.repo.upsert_fnm_chapter_anchor_alignment(
            "doc1",
            "ch-1",
            alignment_status="aligned_with_mismatches",
            body_anchor_count=10,
            endnote_count=10,
            mismatch={"issues": ["marker 3 differs"]},
        )
        records = self.repo.list_fnm_chapter_anchor_alignment("doc1", chapter_id="ch-1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["alignment_status"], "aligned_with_mismatches")
        self.assertIsNotNone(records[0].get("mismatch"))

    def test_clear_fnm_data_cascades_to_new_tables(self):
        self.repo.replace_fnm_chapter_endnotes(
            "doc1",
            "ch-1",
            endnotes=[{"ordinal": 1, "marker": "1", "text": "Note"}],
        )
        self.repo.replace_fnm_paragraph_footnotes(
            "doc1",
            "ch-1",
            footnotes=[{"page_no": 1, "text": "Fn"}],
        )
        self.repo.upsert_fnm_chapter_anchor_alignment(
            "doc1",
            "ch-1",
            alignment_status="clean",
        )

        self.assertEqual(len(self.repo.list_fnm_chapter_endnotes("doc1")), 1)
        self.assertEqual(len(self.repo.list_fnm_paragraph_footnotes("doc1")), 1)
        self.assertEqual(len(self.repo.list_fnm_chapter_anchor_alignment("doc1")), 1)

        self.repo.clear_fnm_data("doc1")

        self.assertEqual(len(self.repo.list_fnm_chapter_endnotes("doc1")), 0)
        self.assertEqual(len(self.repo.list_fnm_paragraph_footnotes("doc1")), 0)
        self.assertEqual(len(self.repo.list_fnm_chapter_anchor_alignment("doc1")), 0)

    def test_numbering_scheme_defaults_per_chapter(self):
        self.repo.replace_fnm_chapter_endnotes(
            "doc1",
            "ch-1",
            endnotes=[{"ordinal": 1, "marker": "1", "text": "Note"}],
        )
        items = self.repo.list_fnm_chapter_endnotes("doc1", chapter_id="ch-1")
        self.assertEqual(items[0]["numbering_scheme"], "per_chapter")


if __name__ == "__main__":
    unittest.main()

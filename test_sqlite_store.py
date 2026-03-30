#!/usr/bin/env python3
"""SQLite 基础存储层测试。"""

import os
import shutil
import sqlite3
import tempfile
import unittest

import config
from sqlite_store import SQLiteRepository, get_connection, initialize_database


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

        with get_connection(self.db_path) as conn:
            translation_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(translation_pages)").fetchall()
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

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM translation_pages WHERE id = ?", (translation_page_id,))
            rows = conn.execute(
                "SELECT COUNT(*) FROM translation_segments WHERE translation_page_id = ?",
                (translation_page_id,),
            ).fetchone()

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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""reingest_fnm_from_snapshots 脚本测试。"""

from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "reingest_fnm_from_snapshots.py"
SCRIPT_NS = runpy.run_path(str(SCRIPT_PATH))

ExampleBook = SCRIPT_NS["ExampleBook"]
reingest_book = SCRIPT_NS["reingest_book"]
maybe_bind_manual_toc = SCRIPT_NS["_maybe_bind_manual_toc"]


class ReingestFnmFromSnapshotsScriptTest(unittest.TestCase):
    def test_maybe_bind_manual_toc_accepts_alternate_filename(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            toc_path = folder / "Biopolitics目录.pdf"
            toc_path.write_text("toc", encoding="utf-8")
            book = ExampleBook(
                slug="demo",
                folder="Demo",
                group="baseline",
                doc_name="demo.pdf",
                source_pdf_path="",
                doc_id="doc-demo",
                include_in_default_batch=True,
                expected_page_count=1,
            )

            save_mock = unittest.mock.Mock(return_value="/tmp/manual.pdf")
            with (
                patch.dict(maybe_bind_manual_toc.__globals__, {"_book_folder": lambda _book: folder}),
                patch.dict(maybe_bind_manual_toc.__globals__, {"save_toc_visual_manual_pdf": save_mock}),
            ):
                saved = maybe_bind_manual_toc(book)

            self.assertEqual(saved, "/tmp/manual.pdf")
            self.assertEqual(save_mock.call_args.args[1], str(toc_path))

    def test_reingest_book_restores_visual_toc_bundle_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "auto_visual_toc.json").write_text(
                json.dumps(
                    {
                        "items": [{"title": "Chapter One", "level": 1}],
                        "endnotes_summary": {
                            "present": True,
                            "container_title": "Notes",
                            "container_printed_page": 259,
                            "container_visual_order": 21,
                            "has_chapter_keyed_subentries_in_toc": False,
                            "subentry_pattern": None,
                        },
                        "organization_summary": {"has_containers": True},
                        "run_summaries": [{"selected_as": "primary_run"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            book = ExampleBook(
                slug="demo",
                folder="Demo",
                group="baseline",
                doc_name="demo.pdf",
                source_pdf_path="",
                doc_id="doc-demo",
                include_in_default_batch=True,
                expected_page_count=1,
            )

            class _RepoStub:
                def upsert_document(self, *_args, **_kwargs):
                    return None

                def replace_pages(self, *_args, **_kwargs):
                    return None

                def clear_fnm_data(self, *_args, **_kwargs):
                    return None

            save_items_mock = unittest.mock.Mock()
            save_bundle_mock = unittest.mock.Mock()

            with (
                patch.dict(reingest_book.__globals__, {"SQLiteRepository": lambda: _RepoStub()}),
                patch.dict(reingest_book.__globals__, {"_book_folder": lambda _book: folder}),
                patch.dict(reingest_book.__globals__, {"_ensure_doc_pdf": lambda _book: folder / "source.pdf"}),
                patch.dict(reingest_book.__globals__, {"_load_raw_pages": lambda _book: [{"page_no": 1}]}),
                patch.dict(reingest_book.__globals__, {"_maybe_bind_manual_toc": lambda _book: None}),
                patch.dict(reingest_book.__globals__, {"run_fnm_pipeline": lambda _doc_id: {"ok": True, "structure_state": "ready", "note_count": 0, "blocking_reasons": []}}),
                patch.dict(reingest_book.__globals__, {"_log": lambda _msg: None}),
                patch.dict(reingest_book.__globals__, {"save_auto_visual_toc_to_disk": save_items_mock}),
                patch.dict(reingest_book.__globals__, {"save_auto_visual_toc_bundle_to_disk": save_bundle_mock}),
            ):
                result = reingest_book(book, rerun_auto_toc=False)

            save_items_mock.assert_called_once()
            save_bundle_mock.assert_called_once()
            saved_bundle = save_bundle_mock.call_args.args[1]
            self.assertEqual(saved_bundle["items"][0]["title"], "Chapter One")
            self.assertEqual(saved_bundle["endnotes_summary"]["container_title"], "Notes")
            self.assertEqual(result["visual_toc_count"], 1)

    def test_reingest_book_can_skip_visual_toc_restore_and_pipeline_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "auto_visual_toc.json").write_text(
                json.dumps({"items": [{"title": "Chapter One", "level": 1}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            book = ExampleBook(
                slug="demo",
                folder="Demo",
                group="baseline",
                doc_name="demo.pdf",
                source_pdf_path="",
                doc_id="doc-demo",
                include_in_default_batch=True,
                expected_page_count=1,
            )

            class _RepoStub:
                def upsert_document(self, *_args, **_kwargs):
                    return None

                def replace_pages(self, *_args, **_kwargs):
                    return None

                def clear_fnm_data(self, *_args, **_kwargs):
                    return None

            save_items_mock = unittest.mock.Mock()
            save_bundle_mock = unittest.mock.Mock()
            run_pipeline_mock = unittest.mock.Mock()

            with (
                patch.dict(reingest_book.__globals__, {"SQLiteRepository": lambda: _RepoStub()}),
                patch.dict(reingest_book.__globals__, {"_book_folder": lambda _book: folder}),
                patch.dict(reingest_book.__globals__, {"_ensure_doc_pdf": lambda _book: folder / "source.pdf"}),
                patch.dict(reingest_book.__globals__, {"_load_raw_pages": lambda _book: [{"page_no": 1}]}),
                patch.dict(reingest_book.__globals__, {"_maybe_bind_manual_toc": lambda _book: None}),
                patch.dict(reingest_book.__globals__, {"run_fnm_pipeline": run_pipeline_mock}),
                patch.dict(reingest_book.__globals__, {"_log": lambda _msg: None}),
                patch.dict(reingest_book.__globals__, {"save_auto_visual_toc_to_disk": save_items_mock}),
                patch.dict(reingest_book.__globals__, {"save_auto_visual_toc_bundle_to_disk": save_bundle_mock}),
            ):
                result = reingest_book(
                    book,
                    rerun_auto_toc=False,
                    restore_auto_visual_toc=False,
                    rebuild_fnm=False,
                )

            save_items_mock.assert_not_called()
            save_bundle_mock.assert_not_called()
            run_pipeline_mock.assert_not_called()
            self.assertEqual(result["visual_toc_count"], 0)

    def test_reingest_book_does_not_rerun_auto_toc_when_restore_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            book = ExampleBook(
                slug="demo",
                folder="Demo",
                group="baseline",
                doc_name="demo.pdf",
                source_pdf_path="",
                doc_id="doc-demo",
                include_in_default_batch=True,
                expected_page_count=1,
            )

            class _RepoStub:
                def upsert_document(self, *_args, **_kwargs):
                    return None

                def replace_pages(self, *_args, **_kwargs):
                    return None

                def clear_fnm_data(self, *_args, **_kwargs):
                    return None

            auto_toc_mock = unittest.mock.Mock()

            with (
                patch.dict(reingest_book.__globals__, {"SQLiteRepository": lambda: _RepoStub()}),
                patch.dict(reingest_book.__globals__, {"_book_folder": lambda _book: folder}),
                patch.dict(reingest_book.__globals__, {"_ensure_doc_pdf": lambda _book: folder / "source.pdf"}),
                patch.dict(reingest_book.__globals__, {"_load_raw_pages": lambda _book: [{"page_no": 1}]}),
                patch.dict(reingest_book.__globals__, {"_maybe_bind_manual_toc": lambda _book: None}),
                patch.dict(reingest_book.__globals__, {"run_fnm_pipeline": lambda _doc_id: {"ok": True, "structure_state": "ready", "note_count": 0, "blocking_reasons": []}}),
                patch.dict(reingest_book.__globals__, {"run_auto_visual_toc_for_doc": auto_toc_mock}),
                patch.dict(reingest_book.__globals__, {"_log": lambda _msg: None}),
            ):
                reingest_book(
                    book,
                    rerun_auto_toc=False,
                    restore_auto_visual_toc=False,
                    rebuild_fnm=False,
                )

            auto_toc_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

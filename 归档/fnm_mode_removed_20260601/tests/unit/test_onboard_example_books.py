#!/usr/bin/env python3
"""扩展样本 onboarding 脚本测试。"""

from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "onboard_example_books.py"
SCRIPT_NS = runpy.run_path(str(SCRIPT_PATH))

ExampleBook = SCRIPT_NS["ExampleBook"]
build_raw_pages_payload = SCRIPT_NS["build_raw_pages_payload"]
build_raw_source_markdown = SCRIPT_NS["build_raw_source_markdown"]
write_book_snapshots = SCRIPT_NS["write_book_snapshots"]
restore_missing_pages = SCRIPT_NS["restore_missing_pages"]


class OnboardExampleBooksScriptTest(unittest.TestCase):
    def test_build_raw_pages_payload_keeps_existing_shape(self):
        book = ExampleBook(
            slug="Demo",
            folder="Demo",
            group="extension",
            doc_name="demo.pdf",
            source_pdf_path="/tmp/demo.pdf",
            doc_id="doc-demo",
            include_in_default_batch=True,
            expected_page_count=2,
        )
        payload = build_raw_pages_payload(
            book=book,
            pages=[{"bookPage": 1, "markdown": "page-1"}, {"bookPage": 2, "markdown": "page-2"}],
        )
        self.assertEqual(payload["doc_id"], "doc-demo")
        self.assertEqual(payload["name"], "demo.pdf")
        self.assertEqual(payload["page_count"], 2)
        self.assertEqual(payload["pages"][1]["bookPage"], 2)

    def test_build_raw_source_markdown_uses_pdf_page_sections(self):
        book = ExampleBook(
            slug="Demo",
            folder="Demo",
            group="extension",
            doc_name="demo.pdf",
            source_pdf_path="/tmp/demo.pdf",
            doc_id="doc-demo",
            include_in_default_batch=True,
            expected_page_count=2,
        )
        markdown = build_raw_source_markdown(
            book=book,
            pages=[{"markdown": "Alpha"}, {"markdown": {"text": "Beta"}}],
        )
        self.assertIn("# demo.pdf", markdown)
        self.assertIn("## PDF第1页", markdown)
        self.assertIn("Alpha", markdown)
        self.assertIn("## PDF第2页", markdown)
        self.assertIn("Beta", markdown)

    def test_write_book_snapshots_creates_expected_files(self):
        book = ExampleBook(
            slug="Demo",
            folder="Demo",
            group="extension",
            doc_name="demo.pdf",
            source_pdf_path="/tmp/demo.pdf",
            doc_id="doc-demo",
            include_in_default_batch=True,
            expected_page_count=1,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            script_globals = write_book_snapshots.__globals__
            original_root = script_globals["TEST_EXAMPLE_ROOT"]
            try:
                script_globals["TEST_EXAMPLE_ROOT"] = root
                result = write_book_snapshots(
                    book=book,
                    pages=[{"bookPage": 1, "markdown": "Alpha"}],
                    fnm_result={"ok": True},
                    structure_status={"structure_state": "ready"},
                )
            finally:
                script_globals["TEST_EXAMPLE_ROOT"] = original_root

            self.assertTrue(Path(result["raw_pages_path"]).exists())
            self.assertTrue(Path(result["raw_source_markdown_path"]).exists())
            self.assertTrue(Path(result["fnm_cleanup_status_path"]).exists())

    def test_restore_missing_pages_reinserts_gaps_by_file_idx(self):
        restored = restore_missing_pages(
            pages=[
                {"fileIdx": 0, "bookPage": 1, "pdfPage": 1, "imgW": 700, "imgH": 1000, "indent": 20, "blocks": [], "fnBlocks": [], "markdown": "A"},
                {"fileIdx": 2, "bookPage": 3, "pdfPage": 3, "imgW": 700, "imgH": 1000, "indent": 20, "blocks": [], "fnBlocks": [], "markdown": "C"},
            ],
            pdf_pages=[
                {"pageIdx": 0, "fullText": "A"},
                {"pageIdx": 1, "fullText": ""},
                {"pageIdx": 2, "fullText": "C"},
            ],
        )
        self.assertEqual([page["fileIdx"] for page in restored], [0, 1, 2])
        self.assertEqual(len(restored), 3)
        self.assertTrue(restored[1]["_restored_missing_page"])
        self.assertEqual(restored[1]["bookPage"], 2)
        self.assertEqual(restored[1]["pdfPage"], 2)
        self.assertEqual(restored[1]["markdown"], "")
        self.assertEqual(restored[1]["imgW"], 700)
        self.assertEqual(restored[1]["imgH"], 1000)


if __name__ == "__main__":
    unittest.main()

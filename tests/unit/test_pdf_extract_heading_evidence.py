#!/usr/bin/env python3
"""PDF 文字层字体证据测试。"""

from __future__ import annotations

import unittest
from pathlib import Path

import document.pdf_extract as pdf_extract


REPO_ROOT = Path("/Users/hao/OCRandTranslation")
TEST_EXAMPLE_DIR = REPO_ROOT / "test_example"


class PdfExtractHeadingEvidenceTest(unittest.TestCase):
    def test_extract_pdf_text_keeps_font_name_and_weight_hint(self):
        pdf_path = next((TEST_EXAMPLE_DIR / "Neuropsychoanalysis_Introduction").glob("*.pdf"))

        pages = pdf_extract.extract_pdf_text(pdf_path.read_bytes())
        chapter_page = next(page for page in pages if int(page.get("pageIdx") or -1) == 19)
        chapter_items = list(chapter_page.get("items") or [])

        title_item = next(item for item in chapter_items if "Self and narcissism" in str(item.get("str") or ""))
        body_item = next(
            item
            for item in chapter_items
            if "One of the key discoveries of Freud" in str(item.get("str") or "")
        )

        self.assertEqual(title_item.get("font_name"), "GillSansStd-Bold")
        self.assertEqual(title_item.get("font_weight_hint"), "bold")
        self.assertEqual(body_item.get("font_name"), "TimesNewRomanPSMT")
        self.assertEqual(body_item.get("font_weight_hint"), "regular")

    def test_extract_pdf_text_without_font_dict_falls_back_to_unknown_weight(self):
        original_reader = pdf_extract.PdfReader

        class _FakeBox:
            width = 600
            height = 800

        class _FakePage:
            mediabox = _FakeBox()

            def extract_text(self, visitor_text=None):
                text = "Synthetic heading with enough readable text layer for fallback"
                if callable(visitor_text):
                    visitor_text(text, [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 32, 760], None, 18)
                return text

        class _FakeReader:
            pages = [_FakePage()]

        try:
            pdf_extract.PdfReader = lambda _stream: _FakeReader()
            pages = pdf_extract.extract_pdf_text(b"%PDF-1.4 fake")
        finally:
            pdf_extract.PdfReader = original_reader

        self.assertEqual(len(pages), 1)
        item = pages[0]["items"][0]
        self.assertEqual(item.get("font_name"), "")
        self.assertEqual(item.get("font_weight_hint"), "unknown")


if __name__ == "__main__":
    unittest.main()

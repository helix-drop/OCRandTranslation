#!/usr/bin/env python3
"""PDF 文字层字体证据测试。"""

from __future__ import annotations

import unittest

import document.pdf_extract as pdf_extract


class PdfExtractHeadingEvidenceTest(unittest.TestCase):
    def test_extract_pdf_text_keeps_font_name_and_weight_hint(self):
        try:
            import fitz
        except ModuleNotFoundError:
            self.skipTest("PyMuPDF 未安装，无法生成字体证据 PDF")

        doc = fitz.open()
        page = doc.new_page(width=360, height=240)
        page.insert_text(
            (36, 72),
            "Synthetic bold heading",
            fontsize=18,
            fontname="hebo",
        )
        page.insert_text(
            (36, 120),
            "Regular body paragraph with enough readable text layer.",
            fontsize=12,
            fontname="tiro",
        )
        pdf_bytes = doc.tobytes()
        doc.close()

        pages = pdf_extract.extract_pdf_text(pdf_bytes)
        chapter_items = list(pages[0].get("items") or [])

        title_item = next(item for item in chapter_items if "Synthetic bold heading" in str(item.get("str") or ""))
        body_item = next(
            item
            for item in chapter_items
            if "Regular body paragraph" in str(item.get("str") or "")
        )

        self.assertEqual(title_item.get("font_name"), "Helvetica-Bold")
        self.assertEqual(title_item.get("font_weight_hint"), "bold")
        self.assertEqual(body_item.get("font_name"), "Times-Roman")
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

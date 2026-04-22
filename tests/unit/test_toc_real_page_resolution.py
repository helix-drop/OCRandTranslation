#!/usr/bin/env python3
"""TOC 真实页码定位测试。"""

import unittest

from web.reading_view import _build_toc_reading_items
from web.toc_support import guess_toc_offset


class TocRealPageResolutionTest(unittest.TestCase):
    def test_build_toc_reading_items_prefers_resolved_target_pdf_page(self):
        page_lookup = {
            11: {"bookPage": 11, "fileIdx": 10, "printPageLabel": "1"},
            25: {"bookPage": 25, "fileIdx": 24, "printPageLabel": "15"},
        }
        toc_items = [
            {
                "title": "Chapter 1",
                "depth": 0,
                "book_page": 1,
                "target_pdf_page": 25,
            }
        ]

        resolved = _build_toc_reading_items(toc_items, 10, page_lookup)

        self.assertEqual(resolved[0]["target_page"], 25)
        self.assertFalse(resolved[0]["unresolved"])

    def test_guess_toc_offset_prefers_resolved_pdf_page_signal_over_title_guess(self):
        new_items = [{"title": "Introduction", "depth": 0, "book_page": 1}]
        auto_toc = [{
            "title": "Introduction",
            "depth": 0,
            "file_idx": 24,
            "target_pdf_page": 25,
        }]
        pages = [
            {"bookPage": 25, "fileIdx": 24, "printPageLabel": "1"},
            {"bookPage": 26, "fileIdx": 25, "printPageLabel": "2"},
        ]

        offset, matched_title = guess_toc_offset(new_items, auto_toc, pages=pages)

        self.assertEqual(offset, 24)
        self.assertEqual(matched_title, "Introduction")


if __name__ == "__main__":
    unittest.main()

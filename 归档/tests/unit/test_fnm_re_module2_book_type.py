from __future__ import annotations

import unittest

from FNM_RE.modules.book_note_type import build_book_note_profile
from FNM_RE.modules.toc_structure import build_toc_structure
from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc, load_pages


def _make_page(page_no: int, *, markdown: str, footnotes: str = "") -> dict:
    return {
        "bookPage": page_no,
        "fileIdx": page_no - 1,
        "target_pdf_page": page_no,
        "markdown": markdown,
        "footnotes": footnotes,
        "prunedResult": {
            "height": 1200,
            "width": 900,
            "parsing_res_list": [],
        },
    }


class FnmReModule2BookTypeTest(unittest.TestCase):
    def test_biopolitics_book_type_is_mixed_and_gate_pass(self):
        pages = load_pages("Biopolitics")
        toc = load_auto_visual_toc("Biopolitics")
        toc_result = build_toc_structure(pages, toc)
        result = build_book_note_profile(toc_result.data, pages)
        self.assertEqual(result.data.book_type, "mixed")
        self.assertTrue(all(result.gate_report.hard.values()))

    def test_conflicting_chapter_mode_breaks_consistency_gate(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody [1].", footnotes="1. note"),
            _make_page(2, markdown="# Chapter Two\nBody [1].", footnotes="1. note"),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]
        toc_result = build_toc_structure(pages, toc_items)
        target_chapter = toc_result.data.chapters[0].chapter_id
        result = build_book_note_profile(
            toc_result.data,
            pages,
            overrides={"chapter_modes": {target_chapter: {"note_mode": "chapter_endnote_primary", "reason": "test-conflict"}}},
        )
        self.assertFalse(result.gate_report.hard["book_type.chapter_modes_consistent"])
        self.assertIn("book_type_chapter_modes_inconsistent", result.gate_report.reasons)

    def test_unapproved_review_required_blocks_gate(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody [1].", footnotes="1. note"),
            _make_page(2, markdown="# Notes\n1. endnote one\n2. endnote two\n3. endnote three\n4. endnote four"),
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        toc_result = build_toc_structure(pages, toc_items)
        chapter_id = toc_result.data.chapters[0].chapter_id
        result = build_book_note_profile(
            toc_result.data,
            pages,
            overrides={"chapter_modes": {chapter_id: {"note_mode": "review_required", "reason": "force-review"}}},
        )
        self.assertFalse(result.gate_report.hard["book_type.no_unapproved_review_required"])
        self.assertIn("book_type_review_required_unapproved", result.gate_report.reasons)
        self.assertTrue(result.overrides_used)


if __name__ == "__main__":
    unittest.main()


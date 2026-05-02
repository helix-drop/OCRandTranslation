from __future__ import annotations

import unittest

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


class FnmReModule1TocTest(unittest.TestCase):
    def test_biopolitics_toc_gate_and_exportable_chapters(self):
        result = build_toc_structure(
            load_pages("Biopolitics"),
            load_auto_visual_toc("Biopolitics"),
        )
        self.assertTrue(all(result.gate_report.hard.values()))
        self.assertEqual(sum(1 for row in result.data.chapters if row.role == "chapter"), 13)
        self.assertEqual([row.title for row in result.data.chapters if row.role == "post_body"], [])

    def test_external_page_roles_do_not_expose_noise(self):
        pages = [
            _make_page(1, markdown=""),
            _make_page(2, markdown="# Chapter One\nBody."),
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 2}]
        result = build_toc_structure(pages, toc_items)
        self.assertNotIn("noise", {row.role for row in result.data.pages})
        self.assertTrue(result.gate_report.hard["toc.pages_classified"])

    def test_disordered_raw_toc_can_be_normalized_to_monotonic(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody."),
            _make_page(2, markdown="# Chapter Two\nBody."),
        ]
        toc_items = [
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 20},
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 10},
        ]
        result = build_toc_structure(pages, toc_items)
        self.assertTrue(result.gate_report.hard["toc.chapter_order_monotonic"])
        self.assertNotIn("toc_chapter_order_non_monotonic", result.gate_report.reasons)

    def test_section_role_hint_does_not_break_chapter_order_gate(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody."),
            _make_page(2, markdown="## Section 1.1\nBody."),
            _make_page(3, markdown="# Chapter Two\nBody."),
        ]
        toc_items = [
            {"item_id": "toc-ch-1", "title": "Chapter One", "level": 1, "target_pdf_page": 10},
            {
                "item_id": "toc-sec-1",
                "title": "Section 1.1",
                "level": 2,
                "target_pdf_page": 5,
                "role_hint": "section",
                "parent_title": "Chapter One",
            },
            {"item_id": "toc-ch-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 20},
        ]
        result = build_toc_structure(pages, toc_items)
        self.assertTrue(result.gate_report.hard["toc.chapter_order_monotonic"])

    def test_mid_book_other_page_does_not_force_back_matter_start(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody."),
            _make_page(2, markdown="Acknowledgments"),
            _make_page(3, markdown="# Chapter Two\nBody."),
        ]
        toc_items = [
            {"item_id": "toc-ch-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {
                "item_id": "toc-fm-1",
                "title": "Acknowledgments",
                "level": 1,
                "target_pdf_page": 2,
                "role_hint": "front_matter",
            },
            {"item_id": "toc-ch-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 3},
        ]
        result = build_toc_structure(pages, toc_items)
        self.assertTrue(result.gate_report.hard["toc.role_semantics_valid"])

    def test_manual_override_is_recorded(self):
        pages = [
            _make_page(1, markdown="Copyright page."),
            _make_page(2, markdown="# Chapter One\nBody."),
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 2}]
        result = build_toc_structure(
            pages,
            toc_items,
            manual_page_overrides={"1": {"page_role": "front_matter"}},
        )
        self.assertTrue(result.overrides_used)
        self.assertTrue(any(row.get("kind") == "page_override" for row in result.overrides_used))

    def test_toc_tree_preserves_endnotes_role_and_semantic_levels(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody."),
            _make_page(2, markdown="## Notes\n1. Note text."),
        ]
        toc_items = [
            {"item_id": "toc-part", "title": "Part I", "depth": 1, "role_hint": "container"},
            {
                "item_id": "toc-ch-1",
                "title": "Chapter One",
                "depth": 0,
                "role_hint": "chapter",
                "parent_title": "Part I",
                "target_pdf_page": 1,
            },
            {
                "item_id": "toc-notes",
                "title": "Notes",
                "depth": 1,
                "role_hint": "endnotes",
                "target_pdf_page": 2,
            },
            {
                "item_id": "toc-notes-1",
                "title": "Notes to Chapter One",
                "depth": 2,
                "role_hint": "section",
                "parent_title": "Notes",
                "target_pdf_page": 2,
            },
        ]

        result = build_toc_structure(pages, toc_items)
        roles_by_title = {row.title: (row.role, row.level, row.parent_id) for row in result.data.toc_tree}

        self.assertEqual(roles_by_title["Part I"], ("container", 1, ""))
        self.assertEqual(roles_by_title["Chapter One"], ("chapter", 2, "Part I"))
        self.assertEqual(roles_by_title["Notes"], ("endnotes", 1, ""))
        self.assertEqual(roles_by_title["Notes to Chapter One"], ("section", 3, "Notes"))
        self.assertTrue(result.gate_report.hard["toc.chapter_order_monotonic"])


if __name__ == "__main__":
    unittest.main()

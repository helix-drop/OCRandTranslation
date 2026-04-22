"""Regression: visual TOC items without an `export_candidate` field must not be
silently dropped by the exportable-chapter filter.

The filter inside `_build_visual_toc_chapters_and_section_heads` was written as
`bool(row.get("export_candidate")) is not False`, which mis-classifies rows that
omit the key (`bool(None) is False` → row excluded). Real auto_visual_toc.json
payloads often omit `export_candidate`, which collapses the visual TOC path to
fallback chapters and cascades into overlapping note regions.
"""

from __future__ import annotations

import unittest

from FNM_RE.modules.toc_structure import build_toc_structure
from tests.unit.fnm_re_module_fixtures import (
    load_auto_visual_toc,
    load_pages,
)


class VisualTocExportCandidateDefaultTest(unittest.TestCase):
    def test_germany_madness_snapshot_selects_visual_toc_source(self):
        pages = load_pages("Germany_Madness")
        toc_items = load_auto_visual_toc("Germany_Madness")
        self.assertTrue(toc_items, "fixture should contain TOC items")
        # Precondition for this regression: the snapshot TOC items do not
        # carry an explicit `export_candidate` field.
        self.assertFalse(
            any("export_candidate" in item for item in toc_items),
            "Germany_Madness fixture is expected to lack export_candidate fields",
        )

        result = build_toc_structure(pages, toc_items)
        summary = result.diagnostics["chapter_source_summary"]
        self.assertEqual(
            summary.get("source"),
            "visual_toc",
            f"visual TOC should drive chapters; got {summary}",
        )
        self.assertGreaterEqual(
            int(summary.get("visual_toc_chapter_count") or 0),
            3,
            "expected at least 3 visual-TOC chapters to survive the filter",
        )

    def test_synthetic_toc_without_export_candidate_preserves_chapters(self):
        # Minimal synthetic fixture: 30 body pages + 3 level-1 TOC items,
        # none of which declare `export_candidate`. Chapters must still be
        # built from the visual TOC path rather than falling through to
        # fallback.
        pages = [
            {
                "bookPage": page_no,
                "fileIdx": page_no - 1,
                "target_pdf_page": page_no,
                "markdown": f"Body text on page {page_no}.",
                "footnotes": "",
                "prunedResult": {"height": 1200, "width": 900, "parsing_res_list": []},
            }
            for page_no in range(1, 31)
        ]
        # Place heading text on the designated chapter-start pages so visual
        # TOC can anchor against body heading candidates.
        pages[4]["markdown"] = "# Chapter One\nBody text."
        pages[14]["markdown"] = "# Chapter Two\nBody text."
        pages[24]["markdown"] = "# Chapter Three\nBody text."

        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 5},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 15},
            {"item_id": "toc-3", "title": "Chapter Three", "level": 1, "target_pdf_page": 25},
        ]
        for item in toc_items:
            self.assertNotIn("export_candidate", item)

        result = build_toc_structure(pages, toc_items)
        summary = result.diagnostics["chapter_source_summary"]
        self.assertEqual(summary.get("source"), "visual_toc", f"got {summary}")
        self.assertGreaterEqual(int(summary.get("visual_toc_chapter_count") or 0), 3)


if __name__ == "__main__":
    unittest.main()

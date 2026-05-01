#!/usr/bin/env python3
"""Golden export comparison rules."""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_NS = runpy.run_path(str(REPO_ROOT / "scripts" / "compare_golden.py"))

compare_chapter = SCRIPT_NS["compare_chapter"]
count_endnote_refs = SCRIPT_NS["count_endnote_refs"]


class CompareGoldenTest(unittest.TestCase):
    def test_note_section_cross_refs_are_not_counted_as_body_refs(self):
        refs, defs = count_endnote_refs(
            "Body ref.[^1]\n\n### NOTES\n\n[^1]: See also [^2].\n[^2]: Note two.\n"
        )

        self.assertEqual(refs, [1])
        self.assertEqual(defs, [1, 2])

    def test_body_ref_counts_use_occurrences_not_only_unique_sets(self):
        result = compare_chapter(
            "example",
            "## Ch\n\nRepeated.[^1]\nRepeated again.[^1]\n\n### NOTES\n\n[^1]: Note.",
            "## Ch\n\nRepeated.[^1]\n\n### NOTES\n\n[^1]: Note.",
        )

        self.assertFalse(result["refs_ok"])
        self.assertIn("正文引用计数不一致", " ".join(result["issues"]))

    def test_section_headings_are_not_a_golden_metric(self):
        result = compare_chapter(
            "example",
            "## Ch\n\n### Extra Body Heading\n\nBody.[^1]\n\n### NOTES\n\n[^1]: Note.",
            "## Ch\n\nBody.[^1]\n\n### NOTES\n\n[^1]: Note.",
        )

        self.assertNotIn("标题数量", " ".join(result["issues"]))


if __name__ == "__main__":
    unittest.main()

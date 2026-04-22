"""FNM_RE/dev/artifact_lookup.py 单测。"""
from __future__ import annotations

import unittest

from FNM_RE.dev.artifact_lookup import LookupError, allowed_tables, lookup_artifact


class FakeRepo:
    def __init__(self):
        self._regions = [
            {"region_id": "r_1", "chapter_id": "ch01", "note_kind": "footnote"},
            {"region_id": "r_2", "chapter_id": "ch02", "note_kind": "endnote"},
        ]
        self._chapters = [
            {"chapter_id": "ch01", "title": "C1"},
            {"chapter_id": "ch02", "title": "C2"},
        ]

    def list_fnm_note_regions(self, doc_id):
        return list(self._regions)

    def list_fnm_chapters(self, doc_id):
        return list(self._chapters)


class LookupArtifactTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepo()

    def test_filter_by_region_id(self):
        res = lookup_artifact(self.repo, "doc", "fnm_note_regions", "region_id", "r_2")
        self.assertEqual(len(res["rows"]), 1)
        self.assertEqual(res["rows"][0]["chapter_id"], "ch02")

    def test_wildcard_returns_all(self):
        res = lookup_artifact(self.repo, "doc", "fnm_note_regions", "doc_id", "*")
        self.assertEqual(res["total"], 2)
        self.assertFalse(res["truncated"])

    def test_non_whitelisted_table_raises(self):
        with self.assertRaises(LookupError):
            lookup_artifact(self.repo, "doc", "sqlite_master", "name", "x")

    def test_disallowed_filter_field_raises(self):
        with self.assertRaises(LookupError):
            lookup_artifact(self.repo, "doc", "fnm_note_regions", "title", "abc")

    def test_no_match_returns_empty_ok(self):
        res = lookup_artifact(self.repo, "doc", "fnm_note_regions", "region_id", "none")
        self.assertEqual(res["rows"], [])
        self.assertTrue(res["ok"])

    def test_allowed_tables_snapshot(self):
        tables = allowed_tables()
        self.assertIn("fnm_pages", tables)
        self.assertIn("fnm_note_links", tables)


if __name__ == "__main__":
    unittest.main()

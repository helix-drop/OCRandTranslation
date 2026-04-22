from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from persistence.storage_toc import (
    clear_auto_visual_toc_bundle_from_disk,
    load_auto_visual_toc_bundle_from_disk,
    save_auto_visual_toc_bundle_to_disk,
)


class StorageTocBundleTest(unittest.TestCase):
    def test_bundle_round_trip_and_clear(self):
        bundle = {
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
            "usage_summary": {"total": {"total_tokens": 10}},
            "run_summaries": [{"selected_as": "primary_run"}],
            "manual_page_items_debug": [[{"title": "Notes"}]],
            "organization_bundle_debug": {"items": [{"title": "Notes"}]},
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("persistence.storage_toc.get_doc_dir", return_value=tmp_dir):
                save_auto_visual_toc_bundle_to_disk("doc-1", bundle)
                loaded = load_auto_visual_toc_bundle_from_disk("doc-1")
                self.assertEqual(loaded["endnotes_summary"]["container_title"], "Notes")
                self.assertEqual(loaded["items"][0]["title"], "Chapter One")

                clear_auto_visual_toc_bundle_from_disk("doc-1")
                self.assertEqual(load_auto_visual_toc_bundle_from_disk("doc-1"), {})

    def test_load_bundle_gracefully_handles_missing_or_invalid_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle_path = Path(tmp_dir) / "auto_visual_toc_bundle.json"
            with patch("persistence.storage_toc.get_doc_dir", return_value=tmp_dir):
                self.assertEqual(load_auto_visual_toc_bundle_from_disk("doc-1"), {})

                bundle_path.write_text("{invalid", encoding="utf-8")
                self.assertEqual(load_auto_visual_toc_bundle_from_disk("doc-1"), {})


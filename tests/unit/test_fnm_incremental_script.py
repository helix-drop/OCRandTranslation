#!/usr/bin/env python3
"""FNM 增量脚本输出口径测试。"""

from __future__ import annotations

import io
import runpy
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "test_fnm_incremental.py"
SCRIPT_NS = runpy.run_path(str(SCRIPT_PATH))
print_report = SCRIPT_NS["_print_report"]


class FnmIncrementalScriptTest(unittest.TestCase):
    def _render_report(self, report: dict) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            print_report(report)
        return output.getvalue()

    def test_check_only_reports_persisted_links_not_db_phase3(self):
        rendered = self._render_report(
            {
                "check_only": True,
                "phase2_detail": {
                    "total_items": 1153,
                    "total_anchors": 1355,
                    "item_kind_counts": {"footnote": 1124, "endnote": 29},
                    "anchor_kind_counts": {"footnote": 1336, "endnote": 19},
                    "sparse_chapters": [],
                },
                "persisted_links_detail": {
                    "matched": 357,
                    "orphan_note": 234,
                    "orphan_anchor": 76,
                    "footnote_orphan_note": 53,
                    "endnote_orphan_note": 181,
                    "footnote_orphan_anchor": 74,
                    "endnote_orphan_anchor": 2,
                    "fallback_match_ratio": 0.0712,
                },
            }
        )

        self.assertIn("Persisted note_links only", rendered)
        self.assertIn("Persisted Phase 2 rows: items/anchors=1153/1355", rendered)
        self.assertIn("Persisted note_links: matched=357", rendered)
        self.assertNotIn("DB Phase 2", rendered)
        self.assertNotIn("DB Phase 3", rendered)

    def test_module_mismatch_warning_names_persisted_links(self):
        rendered = self._render_report(
            {
                "structure_state": "review_required",
                "module_phase3_detail": {
                    "matched": 520,
                    "footnote_orphan_note": 53,
                    "endnote_orphan_note": 18,
                    "footnote_orphan_anchor": 74,
                    "endnote_orphan_anchor": 2,
                    "fallback_match_ratio": 0.0712,
                },
                "module_phase3_reasons": [],
                "by_phase": {},
                "persisted_links_detail": {
                    "matched": 357,
                    "orphan_note": 234,
                    "orphan_anchor": 76,
                    "footnote_orphan_note": 53,
                    "endnote_orphan_note": 181,
                    "footnote_orphan_anchor": 74,
                    "endnote_orphan_anchor": 2,
                    "fallback_match_ratio": 0.0712,
                },
                "persisted_readback": {
                    "note_count_matches_run": True,
                    "persisted_matched_matches_module": False,
                    "module_phase3_matched": 520,
                    "persisted_matched": 357,
                },
            }
        )

        self.assertIn("WARNING: Persisted note_links matched != Module Phase 3 matched", rendered)
        self.assertIn("treat Module Phase 3 as the Phase 3 gate source", rendered)
        self.assertNotIn("DB Phase 3", rendered)


if __name__ == "__main__":
    unittest.main()

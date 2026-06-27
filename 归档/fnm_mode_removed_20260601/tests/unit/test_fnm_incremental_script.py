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
run_pipeline_and_report = SCRIPT_NS["_run_pipeline_and_report"]


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

    def test_pipeline_and_repair_receive_document_database_path(self):
        calls: list[tuple[str, str | None]] = []

        def fake_pipeline(doc_id: str, **kwargs):
            calls.append(("pipeline", kwargs.get("db_path")))
            return {"blocking_reasons": ["toc_fixture_blocker"]}

        def fake_repair(doc_id: str, **kwargs):
            calls.append(("repair", kwargs.get("db_path")))
            return {}

        globals_dict = run_pipeline_and_report.__globals__
        original = {
            "run_doc_pipeline": globals_dict["run_doc_pipeline"],
            "run_llm_repair": globals_dict["run_llm_repair"],
        }
        globals_dict["run_doc_pipeline"] = fake_pipeline
        globals_dict["run_llm_repair"] = fake_repair
        globals_dict["get_document_db_path"] = (
            lambda doc_id: f"/docs/{doc_id}/doc.db"
        )
        try:
            run_pipeline_and_report("doc-1", "Fixture", with_repair=True)
        finally:
            globals_dict["run_doc_pipeline"] = original["run_doc_pipeline"]
            globals_dict["run_llm_repair"] = original["run_llm_repair"]

        self.assertEqual(
            calls,
            [
                ("pipeline", "/docs/doc-1/doc.db"),
                ("repair", "/docs/doc-1/doc.db"),
                ("pipeline", "/docs/doc-1/doc.db"),
            ],
        )

    def test_missing_module_phase3_snapshot_does_not_report_divergence(self):
        globals_dict = run_pipeline_and_report.__globals__
        originals = {
            key: globals_dict[key]
            for key in (
                "run_doc_pipeline",
                "_check_phase2",
                "_check_persisted_note_links",
            )
        }
        globals_dict["run_doc_pipeline"] = lambda doc_id, **kwargs: {
            "blocking_reasons": [],
            "note_count": 1,
        }
        globals_dict["_check_phase2"] = lambda doc_id: {
            "total_items": 1,
            "total_anchors": 1,
            "item_kind_counts": {"endnote": 1},
            "anchor_kind_counts": {"endnote": 1},
            "sparse_chapters": [],
        }
        globals_dict["_check_persisted_note_links"] = lambda doc_id: {
            "matched": 1,
            "orphan_note": 0,
            "orphan_anchor": 0,
        }
        globals_dict["get_document_db_path"] = (
            lambda doc_id: f"/docs/{doc_id}/doc.db"
        )
        try:
            report = run_pipeline_and_report("doc-1", "Fixture")
        finally:
            for key, value in originals.items():
                globals_dict[key] = value

        self.assertFalse(report["persisted_readback"]["module_phase3_snapshot_available"])
        self.assertEqual(report["persisted_readback"]["divergence"], "none")
        self.assertNotIn("persisted_matched_matches_module", report["persisted_readback"])
        self.assertNotIn(
            "Persisted note_links matched != Module Phase 3 matched",
            self._render_report(report),
        )


if __name__ == "__main__":
    unittest.main()

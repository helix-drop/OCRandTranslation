"""FNM_RE/dev/diagnostics.py 单测。"""
from __future__ import annotations

import unittest

from FNM_RE.dev.diagnostics import build_evidence_refs, build_phase_diagnostics


class BuildEvidenceRefsTests(unittest.TestCase):
    def test_phase1_chapter_missing_pages_emits_chapter_and_page_refs(self):
        failure = {
            "code": "phase1.chapter_missing_pages",
            "evidence": {
                "chapters": [
                    {"chapter_id": "ch01", "page_start": 5, "page_end": 10},
                    {"chapter_id": "ch02", "page_start": 0, "page_end": 0},
                ]
            },
        }
        refs = build_evidence_refs(failure)
        kinds = [r["kind"] for r in refs]
        self.assertIn("artifact", kinds)
        self.assertIn("page", kinds)
        page_nos = [r["page_no"] for r in refs if r["kind"] == "page"]
        self.assertEqual(page_nos, [5])
        chapter_ids = [
            r["artifact"]["row_value"] for r in refs if r["kind"] == "artifact"
        ]
        self.assertEqual(chapter_ids, ["ch01", "ch02"])

    def test_phase2_region_ids_expand_to_artifact_refs(self):
        failure = {
            "code": "phase2.region_marker_misaligned",
            "evidence": {"region_ids": ["r_1", "r_2"]},
        }
        refs = build_evidence_refs(failure)
        self.assertEqual(len(refs), 2)
        for ref in refs:
            self.assertEqual(ref["kind"], "artifact")
            self.assertEqual(ref["artifact"]["table"], "fnm_note_regions")
            self.assertEqual(ref["artifact"]["row_key"], "region_id")

    def test_phase3_orphan_anchor_points_to_note_links_summary(self):
        refs = build_evidence_refs(
            {"code": "phase3.footnote_orphan_anchor", "evidence": {"footnote_orphan_anchor": 3}}
        )
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["artifact"]["table"], "fnm_note_links")

    def test_unknown_code_returns_empty_refs(self):
        self.assertEqual(build_evidence_refs({"code": "unknown.x", "evidence": {}}), [])

    def test_evidence_refs_are_json_safe(self):
        import json

        refs = build_evidence_refs(
            {
                "code": "phase1.chapter_without_section_heads",
                "evidence": {"chapter_ids": ["a", "b"]},
            }
        )
        json.dumps(refs)  # 不抛


class BuildPhaseDiagnosticsTests(unittest.TestCase):
    def test_none_phase_run_returns_empty_payload(self):
        payload = build_phase_diagnostics(None)
        self.assertEqual(payload["failures"], [])
        self.assertFalse(payload["gate_pass"])

    def test_enriches_failures_with_evidence_refs(self):
        phase_run = {
            "phase": 2,
            "status": "failed",
            "gate_pass": False,
            "forced_skip": False,
            "gate_report": {
                "phase": 2,
                "pass": False,
                "failures": [
                    {
                        "code": "phase2.region_marker_misaligned",
                        "message": "1 个 region 未对齐",
                        "evidence": {"region_ids": ["r_1"]},
                    }
                ],
                "warnings": [],
            },
            "errors": [],
        }
        payload = build_phase_diagnostics(phase_run)
        self.assertEqual(payload["phase"], 2)
        self.assertEqual(len(payload["failures"]), 1)
        refs = payload["failures"][0]["evidence_refs"]
        self.assertEqual(refs[0]["artifact"]["row_value"], "r_1")


if __name__ == "__main__":
    unittest.main()

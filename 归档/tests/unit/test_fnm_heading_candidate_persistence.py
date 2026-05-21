#!/usr/bin/env python3
"""HeadingCandidate 持久化字段回归。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from FNM_RE.app.persist_helpers import serialize_heading_candidates_for_repo, serialize_pages_for_repo
from FNM_RE.models import HeadingCandidate
from persistence.sqlite_store import SQLiteRepository


class FnmHeadingCandidatePersistenceTest(unittest.TestCase):
    def test_heading_candidate_round_trip_keeps_geometry_and_style_fields(self):
        candidate = HeadingCandidate(
            heading_id="hd-00001",
            page_no=12,
            text="Chapter Twelve",
            normalized_text="Chapter Twelve",
            source="pdf_font_band",
            block_label="doc_title",
            top_band=True,
            confidence=0.91,
            heading_family_guess="chapter",
            suppressed_as_chapter=False,
            reject_reason="",
            font_height=28.0,
            x=144.0,
            y=96.0,
            width_estimate=240.0,
            font_name="GillSansStd-Bold",
            font_weight_hint="bold",
            align_hint="center",
            width_ratio=0.42,
            heading_level_hint=1,
        )
        payload = serialize_heading_candidates_for_repo([candidate])

        self.assertEqual(payload[0]["font_height"], 28.0)
        self.assertEqual(payload[0]["x"], 144.0)
        self.assertEqual(payload[0]["y"], 96.0)
        self.assertEqual(payload[0]["width_estimate"], 240.0)
        self.assertEqual(payload[0]["font_name"], "GillSansStd-Bold")
        self.assertEqual(payload[0]["font_weight_hint"], "bold")
        self.assertEqual(payload[0]["align_hint"], "center")
        self.assertEqual(payload[0]["width_ratio"], 0.42)
        self.assertEqual(payload[0]["heading_level_hint"], 1)

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = SQLiteRepository(str(Path(tmpdir) / "fnm-test.db"))
            repo.upsert_document("doc-heading-roundtrip", "doc-heading-roundtrip", page_count=12)
            repo.replace_fnm_phase1_products(
                "doc-heading-roundtrip",
                pages=serialize_pages_for_repo(
                    [
                        {
                            "page_no": 12,
                            "target_pdf_page": 12,
                            "page_role": "body",
                            "confidence": 1.0,
                            "reason": "body_text",
                            "section_hint": "",
                            "has_note_heading": False,
                            "note_scan_summary": {},
                        }
                    ]
                ),
                chapters=[
                    {
                        "chapter_id": "ch-001",
                        "title": "Chapter Twelve",
                        "start_page": 12,
                        "end_page": 12,
                        "pages": [12],
                        "source": "visual_toc",
                        "boundary_state": "ready",
                    }
                ],
                heading_candidates=payload,
                section_heads=[],
            )
            rows = repo.list_fnm_heading_candidates("doc-heading-roundtrip")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("font_height"), 28.0)
        self.assertEqual(rows[0].get("x"), 144.0)
        self.assertEqual(rows[0].get("y"), 96.0)
        self.assertEqual(rows[0].get("width_estimate"), 240.0)
        self.assertEqual(rows[0].get("font_name"), "GillSansStd-Bold")
        self.assertEqual(rows[0].get("font_weight_hint"), "bold")
        self.assertEqual(rows[0].get("align_hint"), "center")
        self.assertEqual(rows[0].get("width_ratio"), 0.42)
        self.assertEqual(rows[0].get("heading_level_hint"), 1)


if __name__ == "__main__":
    unittest.main()

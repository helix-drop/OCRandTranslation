from __future__ import annotations

import unittest

from FNM_RE.models import HeadingCandidate
from FNM_RE.modules.book_note_type import build_book_note_profile
from FNM_RE.modules.chapter_split import build_chapter_layers
from FNM_RE.modules.toc_structure import build_toc_structure
from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc, load_pages


def _make_page(page_no: int, *, markdown: str, footnotes: str = "", block_text: str = "") -> dict:
    blocks = []
    if block_text:
        blocks.append(
            {
                "block_label": "doc_title",
                "block_content": block_text,
                "block_order": 1,
                "block_bbox": [100.0, 120.0, 860.0, 180.0],
            }
        )
    return {
        "bookPage": page_no,
        "fileIdx": page_no - 1,
        "target_pdf_page": page_no,
        "markdown": markdown,
        "footnotes": footnotes,
        "prunedResult": {"height": 1200, "width": 900, "parsing_res_list": blocks},
    }


class FnmReModule3SplitTest(unittest.TestCase):
    def _build_biopolitics_layers(self):
        pages = load_pages("Biopolitics")
        toc = build_toc_structure(pages, load_auto_visual_toc("Biopolitics")).data
        profile = build_book_note_profile(toc, pages).data
        return build_chapter_layers(toc, profile, pages)

    def test_biopolitics_main_path_hard_gates_true(self):
        result = self._build_biopolitics_layers()
        self.assertTrue(all(result.gate_report.hard.values()))
        self.assertTrue(result.data.regions)
        self.assertTrue(result.data.note_items)
        self.assertTrue(result.data.chapters)
        self.assertTrue(all(bool(row.policy_applied) for row in result.data.chapters))

    def test_same_page_notes_heading_keeps_body_note_disjoint(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody paragraph before notes.\n\n## Notes\n1. Note one.\n2. Note two.",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody paragraph.",
                block_text="Chapter Two",
            ),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]
        toc = build_toc_structure(pages, toc_items).data
        profile = build_book_note_profile(toc, pages).data
        result = build_chapter_layers(toc, profile, pages)
        chapter_one = next(row for row in result.data.chapters if row.title == "Chapter One")
        self.assertTrue(result.gate_report.hard["split.body_note_disjoint"])
        self.assertTrue(chapter_one.endnote_items)
        self.assertFalse(any("Notes" in row.text for row in chapter_one.body_pages))

    def test_empty_region_blocks_items_extracted(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody paragraph.", block_text="Chapter One"),
            _make_page(2, markdown="## Notes\n"),
            _make_page(3, markdown="# Chapter Two\nBody paragraph.", block_text="Chapter Two"),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 3},
        ]
        toc = build_toc_structure(pages, toc_items).data
        profile = build_book_note_profile(toc, pages).data
        result = build_chapter_layers(toc, profile, pages)
        self.assertFalse(result.gate_report.hard["split.items_extracted"])
        self.assertIn("split_items_empty_regions", result.gate_report.reasons)
        self.assertTrue(result.evidence.get("unresolved_empty_region_ids"))

    def test_empty_region_override_allows_gate_and_records_override(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody paragraph.", block_text="Chapter One"),
            _make_page(2, markdown="## Notes\n"),
            _make_page(3, markdown="# Chapter Two\nBody paragraph.", block_text="Chapter Two"),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 3},
        ]
        toc = build_toc_structure(pages, toc_items).data
        profile = build_book_note_profile(toc, pages).data
        first_result = build_chapter_layers(toc, profile, pages)
        empty_ids = list(first_result.evidence.get("unresolved_empty_region_ids") or [])
        second_result = build_chapter_layers(
            toc,
            profile,
            pages,
            overrides={"allow_empty_region_ids": empty_ids, "reason": "manual-confirmed-empty"},
        )
        self.assertTrue(second_result.gate_report.hard["split.items_extracted"])
        self.assertTrue(second_result.overrides_used)

    def test_mixed_policy_evidence_is_recorded(self):
        result = self._build_biopolitics_layers()
        self.assertEqual(result.evidence.get("book_type"), "mixed")
        self.assertEqual(
            dict(result.evidence.get("mixed_marker_materialized") or {}).get("status"),
            "not_required",
        )
        self.assertTrue(result.gate_report.hard["split.footnote_only_synthesized"])
        self.assertEqual(
            dict(result.evidence.get("footnote_only_synthesized") or {}).get("status"),
            "not_applicable",
        )

    def test_footnote_only_synthesizes_per_chapter_not_global(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1] [2].",
                footnotes="1. Note one.\n2. Note two.",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody [1] [2].",
                footnotes="1. Note one again.\n2. Note two again.",
                block_text="Chapter Two",
            ),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]
        toc = build_toc_structure(pages, toc_items).data
        profile = build_book_note_profile(toc, pages).data
        self.assertEqual(profile.book_type, "footnote_only")
        result = build_chapter_layers(toc, profile, pages)
        self.assertTrue(result.gate_report.hard["split.footnote_only_synthesized"])
        evidence = dict(result.evidence.get("footnote_only_synthesized") or {})
        self.assertEqual(evidence.get("status"), "passed")
        chapter_markers = dict(evidence.get("chapter_markers") or {})
        self.assertEqual(chapter_markers.get("toc-toc-1"), ["1", "2"])
        self.assertEqual(chapter_markers.get("toc-toc-2"), ["1", "2"])

    def test_sparse_note_capture_fails_items_extracted_gate(self):
        pages = [
            _make_page(
                1,
                markdown=(
                    "# Chapter One\n"
                    "Body [1] [2] [3] [4] [5] [6] [7] [8] [9] [10] [11] [12]."
                ),
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody paragraph.",
                block_text="Chapter Two",
            ),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]
        toc = build_toc_structure(pages, toc_items).data
        profile = build_book_note_profile(toc, pages).data
        result = build_chapter_layers(toc, profile, pages)
        self.assertFalse(result.gate_report.hard["split.items_extracted"])
        self.assertIn("split_items_sparse_note_capture", result.gate_report.reasons)
        summary = dict(result.data.item_summary.get("note_capture_summary") or {})
        self.assertGreaterEqual(int(summary.get("expected_anchor_count") or 0), 10)
        self.assertEqual(int(summary.get("captured_note_count") or 0), 0)

    def test_book_scope_endnotes_are_projected_by_marker_to_chapters(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1] [2].",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody [3] [4].",
                block_text="Chapter Two",
            ),
            _make_page(
                3,
                markdown="## Notes\n1. Note one.\n2. Note two.\n3. Note three.\n4. Note four.",
            ),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]
        toc = build_toc_structure(pages, toc_items).data
        profile = build_book_note_profile(toc, pages).data
        self.assertEqual(profile.book_type, "endnote_only")
        result = build_chapter_layers(toc, profile, pages)
        chapter_one = next(row for row in result.data.chapters if row.title == "Chapter One")
        chapter_two = next(row for row in result.data.chapters if row.title == "Chapter Two")
        self.assertEqual([row.marker for row in chapter_one.endnote_items], ["1", "2"])
        self.assertEqual([row.marker for row in chapter_two.endnote_items], ["3", "4"])
        binding = dict(result.data.region_summary.get("chapter_binding_summary") or {})
        self.assertEqual(int(binding.get("unassigned_item_count") or 0), 0)

    def test_toc_structure_diagnostics_include_endnote_hints_and_heading_candidates(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody paragraph.", block_text="Chapter One"),
            _make_page(2, markdown="# Chapter Two\nBody paragraph.", block_text="Chapter Two"),
            _make_page(3, markdown="# Notes\n1. Note one.", block_text="Chapter Two"),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]
        visual_toc_bundle = {
            "endnotes_summary": {
                "present": True,
                "container_title": "Notes",
                "container_printed_page": 3,
                "container_visual_order": 10,
                "has_chapter_keyed_subentries_in_toc": True,
                "subentry_pattern": "numbered",
            },
            "items": [
                {"title": "Notes", "printed_page": 3, "visual_order": 10, "role_hint": "endnotes", "parent_title": ""},
                {"title": "1. Chapter Two", "printed_page": 3, "visual_order": 11, "role_hint": "section", "parent_title": "Notes"},
            ],
        }

        result = build_toc_structure(pages, toc_items, visual_toc_bundle=visual_toc_bundle)

        hints = dict(result.diagnostics.get("endnote_explorer_hints") or {})
        self.assertTrue(hints.get("has_toc_subentries"))
        self.assertEqual(int(hints.get("container_start_page_hint") or 0), 3)
        self.assertTrue(result.diagnostics.get("heading_candidates"))

    def test_build_chapter_layers_uses_passed_heading_candidates_for_signal_rebind(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody paragraph.", block_text="Chapter One"),
            _make_page(2, markdown="# Chapter Two\nBody paragraph.", block_text="Chapter Two"),
            _make_page(3, markdown="# Notes\n1. Note one."),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]
        toc_result = build_toc_structure(pages, toc_items)
        profile = build_book_note_profile(toc_result.data, pages).data
        heading_candidates = [
            HeadingCandidate(
                heading_id="hc-3",
                page_no=3,
                text="Chapter Two",
                normalized_text="chapter two",
                source="pdf_font_band",
                block_label="paragraph_title",
                top_band=True,
                confidence=0.94,
                heading_family_guess="body",
                suppressed_as_chapter=False,
                reject_reason="",
                font_height=28.0,
                x=120.0,
                y=160.0,
                width_estimate=440.0,
                font_name="Times-Bold",
                font_weight_hint="heavy",
                align_hint="center",
                width_ratio=0.48,
                heading_level_hint=1,
            )
        ]

        result = build_chapter_layers(
            toc_result.data,
            profile,
            pages,
            heading_candidates=heading_candidates,
        )

        regions = [row for row in result.data.regions if row.note_kind == "endnote"]
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].chapter_id, "toc-toc-2")
        self.assertEqual(regions[0].source, "explorer_signal_match")

    def test_stage3_summaries_exist_in_split_data(self):
        result = self._build_biopolitics_layers()
        self.assertIn("chapter_binding_summary", result.data.region_summary)
        self.assertIn("note_capture_summary", result.data.item_summary)
        self.assertIn("footnote_synthesis_summary", result.data.item_summary)


if __name__ == "__main__":
    unittest.main()

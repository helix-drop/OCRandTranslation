from __future__ import annotations

import unittest

from FNM_RE.app.pipeline import build_phase3_structure, build_phase4_structure
from FNM_RE.models import ChapterNoteModeRecord
from FNM_RE.status import build_phase4_status
from FNM_RE.stages.reviews import build_structure_reviews


def _make_page(
    page_no: int,
    *,
    markdown: str = "",
    block_label: str = "",
    block_text: str = "",
    footnotes: str = "",
) -> dict:
    blocks: list[dict] = []
    if block_text:
        blocks.append(
            {
                "block_label": block_label or "doc_title",
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
        "prunedResult": {
            "height": 1200,
            "width": 900,
            "parsing_res_list": blocks,
        },
    }


def _endnote_pages() -> list[dict]:
    return [
        _make_page(
            1,
            markdown="# Chapter One\nBody [2].",
            block_label="doc_title",
            block_text="Chapter One",
        ),
        _make_page(2, markdown="# Notes\n1. Endnote one."),
    ]


def _endnote_overrides() -> dict[str, dict]:
    return {"2": {"page_role": "note"}}


def _ambiguous_pages() -> list[dict]:
    return [
        _make_page(
            1,
            markdown="# Chapter One\nBody [2] and again [2].",
            block_label="doc_title",
            block_text="Chapter One",
        ),
        _make_page(2, markdown="# Notes\n2. Endnote two."),
    ]


def _unknown_anchor_pages() -> list[dict]:
    return [
        _make_page(
            1,
            markdown="# Chapter One\nBody [9].",
            block_label="doc_title",
            block_text="Chapter One",
        )
    ]


def _phase3_signature(phase3) -> tuple:
    return (
        tuple((row.page_no, row.page_role) for row in phase3.pages),
        tuple((row.chapter_id, row.title, row.start_page, row.end_page, row.boundary_state) for row in phase3.chapters),
        tuple((row.chapter_id, row.title, row.page_no) for row in phase3.section_heads),
        tuple(
            (row.region_id, row.chapter_id, row.page_start, row.page_end, row.note_kind, row.scope)
            for row in phase3.note_regions
        ),
        tuple((row.note_item_id, row.region_id, row.chapter_id, row.page_no, row.marker) for row in phase3.note_items),
        tuple((row.chapter_id, row.note_mode) for row in phase3.chapter_note_modes),
        tuple((row.anchor_id, row.chapter_id, row.page_no, row.normalized_marker, row.synthetic) for row in phase3.body_anchors),
        tuple((row.link_id, row.status, row.note_item_id, row.anchor_id, row.note_kind) for row in phase3.note_links),
    )


class FnmRePhase4Test(unittest.TestCase):
    def test_boundary_review_required_from_chapter_state(self):
        phase3 = build_phase3_structure(_endnote_pages(), page_overrides=_endnote_overrides())
        phase3.chapters[0].boundary_state = "review_required"
        reviews, _summary = build_structure_reviews(phase3, effective_note_links=phase3.note_links)
        self.assertTrue(any(row.review_type == "boundary_review_required" for row in reviews))

    def test_uncertain_anchor_review_from_unknown_anchor(self):
        phase4 = build_phase4_structure(_unknown_anchor_pages())
        self.assertTrue(any(row.review_type == "uncertain_anchor" for row in phase4.structure_reviews))
        self.assertGreaterEqual(int(phase4.status.review_counts.get("uncertain_anchor", 0) or 0), 1)

    def test_orphan_and_ambiguous_links_generate_expected_review_types(self):
        orphan_phase4 = build_phase4_structure(_endnote_pages(), review_overrides={"page": _endnote_overrides()})
        ambiguous_phase4 = build_phase4_structure(_ambiguous_pages(), review_overrides={"page": _endnote_overrides()})
        review_types = {row.review_type for row in orphan_phase4.structure_reviews}
        review_types.update(row.review_type for row in ambiguous_phase4.structure_reviews)
        self.assertIn("endnote_orphan_note", review_types)
        self.assertIn("endnote_orphan_anchor", review_types)
        self.assertIn("ambiguous", review_types)

    def test_ignored_link_not_in_review_counts_or_blocking(self):
        base = build_phase4_structure(_endnote_pages(), review_overrides={"page": _endnote_overrides()})
        orphan_note_link = next(row for row in base.note_links if row.status == "orphan_note")
        phase4 = build_phase4_structure(
            _endnote_pages(),
            review_overrides={
                "page": _endnote_overrides(),
                "link": {orphan_note_link.link_id: {"action": "ignore"}},
            },
        )
        self.assertEqual(int(phase4.status.review_counts.get("endnote_orphan_note", 0) or 0), 0)
        self.assertNotIn("endnote_orphan_note", set(phase4.status.blocking_reasons))
        self.assertTrue(any(row.status == "ignored" for row in phase4.effective_note_links))

    def test_link_ignore_clears_orphan_blocker_and_keeps_raw_links(self):
        base = build_phase4_structure(_endnote_pages(), review_overrides={"page": _endnote_overrides()})
        orphan_note_link = next(row for row in base.note_links if row.status == "orphan_note")
        phase4 = build_phase4_structure(
            _endnote_pages(),
            review_overrides={
                "page": _endnote_overrides(),
                "link": {orphan_note_link.link_id: {"action": "ignore"}},
            },
        )
        raw_status_by_id = {row.link_id: row.status for row in phase4.note_links}
        effective_status_by_id = {row.link_id: row.status for row in phase4.effective_note_links}
        self.assertEqual(raw_status_by_id.get(orphan_note_link.link_id), "orphan_note")
        self.assertEqual(effective_status_by_id.get(orphan_note_link.link_id), "ignored")

    def test_link_match_updates_effective_link_and_clears_orphan_blockers(self):
        base = build_phase4_structure(_endnote_pages(), review_overrides={"page": _endnote_overrides()})
        orphan_note = next(row for row in base.note_links if row.status == "orphan_note")
        orphan_anchor = next(row for row in base.note_links if row.status == "orphan_anchor")
        phase4 = build_phase4_structure(
            _endnote_pages(),
            review_overrides={
                "page": _endnote_overrides(),
                "link": {
                    orphan_note.link_id: {
                        "action": "match",
                        "note_item_id": orphan_note.note_item_id,
                        "anchor_id": orphan_anchor.anchor_id,
                    }
                },
            },
        )
        matched = next(row for row in phase4.effective_note_links if row.link_id == orphan_note.link_id)
        self.assertEqual(matched.status, "matched")
        self.assertEqual(matched.resolver, "repair")
        self.assertEqual(float(matched.confidence), 1.0)
        self.assertEqual(int(phase4.status.review_counts.get("endnote_orphan_note", 0) or 0), 0)
        self.assertEqual(int(phase4.status.review_counts.get("endnote_orphan_anchor", 0) or 0), 0)
        self.assertNotIn("endnote_orphan_note", set(phase4.status.blocking_reasons))
        self.assertNotIn("endnote_orphan_anchor", set(phase4.status.blocking_reasons))

    def test_invalid_link_match_enters_invalid_override_count(self):
        base = build_phase4_structure(_endnote_pages(), review_overrides={"page": _endnote_overrides()})
        orphan_note = next(row for row in base.note_links if row.status == "orphan_note")
        phase4 = build_phase4_structure(
            _endnote_pages(),
            review_overrides={
                "page": _endnote_overrides(),
                "link": {
                    orphan_note.link_id: {
                        "action": "match",
                        "note_item_id": orphan_note.note_item_id,
                        "anchor_id": "anchor-not-found",
                    }
                },
            },
        )
        self.assertEqual(int(phase4.summary.override_summary.get("invalid_override_count", 0) or 0), 1)
        self.assertTrue(
            any(str(flag).startswith("invalid_link_override:") for flag in (phase4.summary.review_flags or []))
        )

    def test_chapter_mode_summary_maps_to_legacy_keys(self):
        phase4 = build_phase4_structure(_endnote_pages(), review_overrides={"page": _endnote_overrides()})
        phase4.chapter_note_modes = [
            ChapterNoteModeRecord("ch-1", "footnote_primary", [], "", False, False),
            ChapterNoteModeRecord("ch-2", "chapter_endnote_primary", [], "", False, True),
            ChapterNoteModeRecord("ch-3", "book_endnote_bound", [], "", False, True),
            ChapterNoteModeRecord("ch-4", "no_notes", [], "", False, False),
            ChapterNoteModeRecord("ch-5", "review_required", [], "", False, False),
        ]
        status = build_phase4_status(phase4)
        self.assertEqual(status.chapter_mode_summary["footnote_primary"], 1)
        self.assertEqual(status.chapter_mode_summary["chapter_endnotes"], 1)
        self.assertEqual(status.chapter_mode_summary["book_endnotes"], 1)
        self.assertEqual(status.chapter_mode_summary["body_only"], 1)
        self.assertEqual(status.chapter_mode_summary["mixed_or_unclear"], 1)

    def test_manual_toc_not_ready_adds_manual_blocker(self):
        phase4 = build_phase4_structure(
            _endnote_pages(),
            review_overrides={"page": _endnote_overrides()},
            manual_toc_ready=False,
            manual_toc_summary={"source": "missing"},
        )
        self.assertEqual(phase4.status.structure_state, "review_required")
        self.assertIn("manual_toc_required", set(phase4.status.blocking_reasons))
        self.assertTrue(phase4.status.manual_toc_required)

    def test_toc_alignment_and_semantic_reviews_from_phase3_summary(self):
        phase3 = build_phase3_structure(_endnote_pages(), page_overrides=_endnote_overrides())
        phase3.summary.chapter_title_alignment_ok = False
        phase3.summary.chapter_section_alignment_ok = False
        phase3.summary.toc_semantic_contract_ok = False
        reviews, _summary = build_structure_reviews(phase3, effective_note_links=phase3.note_links)
        review_types = {row.review_type for row in reviews}
        self.assertIn("toc_alignment_review_required", review_types)
        self.assertIn("toc_semantic_review_required", review_types)

    def test_pipeline_state_idle_running_error_override_blocking(self):
        for pipeline_state in ("idle", "running", "error"):
            phase4 = build_phase4_structure(
                _endnote_pages(),
                review_overrides={"page": _endnote_overrides()},
                pipeline_state=pipeline_state,
            )
            self.assertEqual(phase4.status.structure_state, pipeline_state)

    def test_page_override_takes_effect_by_rerunning_phase3(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                block_label="doc_title",
                block_text="Chapter One",
            ),
            _make_page(2, markdown="1. Endnote one."),
            _make_page(
                3,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]
        base = build_phase4_structure(pages)
        with_override = build_phase4_structure(pages, review_overrides={"page": {"2": {"page_role": "note"}}})
        base_roles = {row.page_no: row.page_role for row in base.pages}
        override_roles = {row.page_no: row.page_role for row in with_override.pages}
        self.assertNotEqual(base_roles.get(2), override_roles.get(2))
        self.assertEqual(override_roles.get(2), "note")
        self.assertGreater(len(with_override.note_items), len(base.note_items))

    def test_phase4_keeps_phase3_truth_and_does_not_mutate_phase3(self):
        pages = _endnote_pages()
        phase3 = build_phase3_structure(pages, page_overrides=_endnote_overrides())
        before = _phase3_signature(phase3)
        orphan_note = next(row for row in phase3.note_links if row.status == "orphan_note")
        phase4 = build_phase4_structure(
            pages,
            review_overrides={
                "page": _endnote_overrides(),
                "link": {orphan_note.link_id: {"action": "ignore"}},
            },
        )
        after = _phase3_signature(phase3)
        self.assertEqual(before, after)
        self.assertEqual(_phase3_signature(phase4), before)
        self.assertNotEqual(
            tuple((row.link_id, row.status) for row in phase4.note_links),
            tuple((row.link_id, row.status) for row in phase4.effective_note_links),
        )


if __name__ == "__main__":
    unittest.main()

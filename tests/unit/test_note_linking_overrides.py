from __future__ import annotations

import unittest

from FNM_RE.models import (
    BodyAnchorRecord,
    NoteItemRecord,
    NoteLinkRecord,
    NoteRegionRecord,
)
from FNM_RE.modules.note_linking import _apply_link_overrides


def _region(region_id: str, note_kind: str) -> NoteRegionRecord:
    return NoteRegionRecord(
        region_id=region_id,
        chapter_id="ch-1",
        page_start=37,
        page_end=37,
        pages=[37],
        note_kind=note_kind,  # type: ignore[arg-type]
        scope="chapter",  # type: ignore[arg-type]
        source="fnBlock",  # type: ignore[arg-type]
        heading_text="",
        start_reason="test",
        end_reason="test",
        region_marker_alignment_ok=True,
        region_start_first_source_marker="",
        region_first_note_item_marker="",
        review_required=False,
    )


def _item(note_item_id: str, region_id: str, page_no: int, marker: str) -> NoteItemRecord:
    return NoteItemRecord(
        note_item_id=note_item_id,
        region_id=region_id,
        chapter_id="ch-1",
        page_no=page_no,
        marker=marker,
        marker_type="numeric",
        text="note text",
        source="test",
        source_page_label="",
        is_reconstructed=False,
        review_required=False,
        note_kind="endnote" if note_item_id.lower().startswith("en-") else "footnote",
    )


def _anchor(anchor_id: str, page_no: int, marker: str, kind: str) -> BodyAnchorRecord:
    return BodyAnchorRecord(
        anchor_id=anchor_id,
        chapter_id="ch-1",
        page_no=page_no,
        paragraph_index=0,
        char_start=10,
        char_end=11,
        source_marker=marker,
        normalized_marker=marker,
        anchor_kind=kind,  # type: ignore[arg-type]
        certainty=0.95,
        source_text="body phrase",
        source="llm",
        synthetic=False,
        ocr_repaired_from_marker="",
    )


def _link(link_id: str, note_item_id: str, marker: str) -> NoteLinkRecord:
    return NoteLinkRecord(
        link_id=link_id,
        chapter_id="ch-1",
        region_id="r-fn",
        note_item_id=note_item_id,
        anchor_id="",
        status="orphan_note",  # type: ignore[arg-type]
        resolver="rule",  # type: ignore[arg-type]
        confidence=0.0,
        note_kind="footnote",  # type: ignore[arg-type]
        marker=marker,
        page_no_start=37,
        page_no_end=37,
    )


class LinkOverrideValidationTest(unittest.TestCase):
    def test_footnote_override_must_stay_near_note_page(self):
        links, summary, _logs = _apply_link_overrides(
            [_link("link-1", "fn-1", "2")],
            link_overrides={
                "link-1": {
                    "action": "match",
                    "note_item_id": "fn-1",
                    "anchor_id": "a-far",
                }
            },
            note_items=[_item("fn-1", "r-fn", 37, "2")],
            body_anchors=[_anchor("a-far", 17, "2", "footnote")],
            note_regions=[_region("r-fn", "footnote")],
        )

        self.assertEqual(links[0].status, "orphan_note")
        self.assertEqual(summary["matched_link_override_count"], 0)
        self.assertIn("invalid_link_override:link-1:page_window", summary["invalid_override_flags"])

    def test_footnote_override_accepts_same_page_anchor(self):
        links, summary, _logs = _apply_link_overrides(
            [_link("link-1", "fn-1", "2")],
            link_overrides={
                "link-1": {
                    "action": "match",
                    "note_item_id": "fn-1",
                    "anchor_id": "a-near",
                }
            },
            note_items=[_item("fn-1", "r-fn", 37, "2")],
            body_anchors=[_anchor("a-near", 37, "2", "footnote")],
            note_regions=[_region("r-fn", "footnote")],
        )

        self.assertEqual(links[0].status, "matched")
        self.assertEqual(summary["matched_link_override_count"], 1)


if __name__ == "__main__":
    unittest.main()

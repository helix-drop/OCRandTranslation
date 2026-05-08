from __future__ import annotations

import unittest

from FNM_RE.modules.chapter_merge import _phase5_book_type, _to_chapter_note_mode_records
from FNM_RE.modules.types import (
    ChapterLayer,
    ChapterLayers,
    LayerNoteItem,
    LayerNoteRegion,
)


def _item(note_id: str, chapter_id: str, marker: str, note_kind: str) -> LayerNoteItem:
    return LayerNoteItem(
        note_item_id=note_id,
        region_id=f"region-{chapter_id}",
        chapter_id=chapter_id,
        page_no=1,
        marker=marker,
        marker_type="numeric",
        text=f"Note {marker}",
        source="test",
        is_reconstructed=False,
        review_required=False,
        note_kind=note_kind,  # type: ignore[arg-type]
    )


def _endnote_region(chapter_id: str) -> LayerNoteRegion:
    return LayerNoteRegion(
        region_id=f"region-{chapter_id}",
        chapter_id=chapter_id,
        page_start=2,
        page_end=2,
        pages=[2],
        note_kind="endnote",  # type: ignore[arg-type]
        scope="chapter",  # type: ignore[arg-type]
        source="chapter_endnotes",  # type: ignore[arg-type]
        heading_text="NOTES",
        review_required=False,
    )


class Phase5ChapterModeSourceTest(unittest.TestCase):
    def test_phase5_modes_use_actual_layer_items_not_stale_policy(self):
        endnote = _item("en-1", "ch-endnote", "1", "endnote")
        footnote = _item("fn-1", "ch-footnote", "1", "footnote")
        endnote_region = _endnote_region("ch-endnote")
        layers = ChapterLayers(
            chapters=[
                ChapterLayer(
                    chapter_id="ch-endnote",
                    title="Endnote Chapter",
                    endnote_items=[endnote],
                    endnote_regions=[endnote_region],
                    policy_applied={"note_mode": "chapter_endnote_primary", "book_type": "endnote_only"},
                ),
                ChapterLayer(
                    chapter_id="ch-footnote",
                    title="Footnote Chapter",
                    footnote_items=[footnote],
                    policy_applied={"note_mode": "no_notes", "book_type": "endnote_only"},
                ),
            ],
            regions=[endnote_region],
            note_items=[endnote, footnote],
        )

        mode_by_chapter = {
            row.chapter_id: row.note_mode
            for row in _to_chapter_note_mode_records(layers)
        }

        self.assertEqual(mode_by_chapter["ch-endnote"], "chapter_endnote_primary")
        self.assertEqual(mode_by_chapter["ch-footnote"], "footnote_primary")
        self.assertEqual(_phase5_book_type(layers), "mixed")


if __name__ == "__main__":
    unittest.main()

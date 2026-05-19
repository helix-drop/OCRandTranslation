from __future__ import annotations

import re
import unittest

from FNM_RE.models import (
    BodyAnchorRecord,
    ChapterRecord,
    NoteItemRecord,
    NoteLinkRecord,
    TranslationUnitRecord,
    UnitPageSegmentRecord,
    UnitParagraphRecord,
)
from FNM_RE.stages import export as _export_stage  # noqa: F401  (loads shared export helpers first)
from FNM_RE.stages.export_footnote import _build_inline_footnote_section_markdown


def _paragraph(order: int, text: str) -> UnitParagraphRecord:
    return UnitParagraphRecord(
        order=order,
        kind="body",
        heading_level=0,
        source_text=text,
        display_text=text,
        cross_page=None,
        consumed_by_prev=False,
    )


def _body_unit(texts: list[str] | None = None) -> TranslationUnitRecord:
    paragraphs = texts or [
        "Alpha {{NOTE_REF:fn-1}}.",
        "Beta {{NOTE_REF:fn-2}}.",
    ]
    return TranslationUnitRecord(
        unit_id="body-1",
        kind="body",
        owner_kind="chapter",
        owner_id="ch1",
        section_id="ch1",
        section_title="Chapter",
        section_start_page=1,
        section_end_page=1,
        note_id="",
        page_start=1,
        page_end=1,
        char_count=1,
        source_text="\n\n".join(paragraphs),
        translated_text="",
        status="pending",
        error_msg="",
        target_ref="",
        page_segments=[
            UnitPageSegmentRecord(
                page_no=1,
                paragraph_count=len(paragraphs),
                source_text="",
                display_text="",
                paragraphs=[
                    _paragraph(index, text)
                    for index, text in enumerate(paragraphs, start=1)
                ],
            )
        ],
    )


def _note_unit(note_id: str, marker: str, text: str) -> TranslationUnitRecord:
    return TranslationUnitRecord(
        unit_id=f"unit-{note_id}",
        kind="footnote",
        owner_kind="note",
        owner_id=note_id,
        section_id="ch1",
        section_title="Chapter",
        section_start_page=1,
        section_end_page=1,
        note_id=note_id,
        page_start=1,
        page_end=1,
        char_count=len(text),
        source_text=text,
        translated_text="",
        status="pending",
        error_msg="",
        target_ref=marker,
    )


def _note_item(note_id: str, marker: str) -> NoteItemRecord:
    return NoteItemRecord(
        note_item_id=note_id,
        region_id="r1",
        chapter_id="ch1",
        page_no=1,
        marker=marker,
        marker_type="numeric",
        text=f"Note {marker}",
        source="test",
        source_page_label="1",
        is_reconstructed=False,
        review_required=False,
        note_kind="endnote" if note_id.lower().startswith("en-") else "footnote",
    )


def _anchor(anchor_id: str, marker: str, paragraph_index: int) -> BodyAnchorRecord:
    return BodyAnchorRecord(
        anchor_id=anchor_id,
        chapter_id="ch1",
        page_no=1,
        paragraph_index=paragraph_index,
        char_start=6,
        char_end=7,
        source_marker=marker,
        normalized_marker=marker,
        anchor_kind="footnote",  # type: ignore[arg-type]
        certainty=1.0,
        source_text="",
        source="test",
        synthetic=False,
        ocr_repaired_from_marker="",
    )


def _link(link_id: str, note_id: str, anchor_id: str, marker: str) -> NoteLinkRecord:
    return NoteLinkRecord(
        link_id=link_id,
        chapter_id="ch1",
        region_id="r1",
        note_item_id=note_id,
        anchor_id=anchor_id,
        status="matched",  # type: ignore[arg-type]
        resolver="rule",  # type: ignore[arg-type]
        confidence=1.0,
        note_kind="footnote",  # type: ignore[arg-type]
        marker=marker,
        page_no_start=1,
        page_no_end=1,
    )


class NumberedFootnoteExportTest(unittest.TestCase):
    def test_numbered_footnotes_emit_body_refs_before_chapter_end_definitions(self):
        chapter = ChapterRecord(
            chapter_id="ch1",
            title="Chapter",
            start_page=1,
            end_page=1,
            pages=[1],
            source="visual_toc",  # type: ignore[arg-type]
            boundary_state="ready",  # type: ignore[arg-type]
        )
        note_items = {"fn-1": _note_item("fn-1", "1"), "fn-2": _note_item("fn-2", "2")}

        content, _summary = _build_inline_footnote_section_markdown(
            chapter,
            section_heads=[],
            body_units=[_body_unit()],
            note_units=[
                _note_unit("fn-1", "1", "First footnote."),
                _note_unit("fn-2", "2", "Second footnote."),
            ],
            matched_links=[
                _link("link-1", "fn-1", "a1", "1"),
                _link("link-2", "fn-2", "a2", "2"),
            ],
            note_items_by_id=note_items,
            body_anchors_by_id={"a1": _anchor("a1", "1", 0), "a2": _anchor("a2", "2", 1)},
            include_diagnostic_entries=False,
            diagnostic_machine_by_page={},
        )

        first_def = content.find("[^1]:")
        self.assertGreater(first_def, 0)
        body_before_defs = content[:first_def]
        self.assertIn("Alpha[^1].", body_before_defs)
        self.assertIn("Beta[^2].", body_before_defs)
        self.assertEqual(re.findall(r"^\[\^(\d+)\]:", content, re.MULTILINE), ["1", "2"])

    def test_symbol_footnotes_remain_inline_and_do_not_consume_numeric_labels(self):
        chapter = ChapterRecord(
            chapter_id="ch1",
            title="Chapter",
            start_page=1,
            end_page=1,
            pages=[1],
            source="visual_toc",  # type: ignore[arg-type]
            boundary_state="ready",  # type: ignore[arg-type]
        )
        note_items = {
            "fn-star": _note_item("fn-star", "*"),
            "fn-1": _note_item("fn-1", "1"),
        }

        content, _summary = _build_inline_footnote_section_markdown(
            chapter,
            section_heads=[],
            body_units=[_body_unit(["Author {{NOTE_REF:fn-star}}.", "Alpha {{NOTE_REF:fn-1}}."])],
            note_units=[
                _note_unit("fn-star", "*", "Author footnote."),
                _note_unit("fn-1", "1", "First footnote."),
            ],
            matched_links=[
                _link("link-star", "fn-star", "a-star", "*"),
                _link("link-1", "fn-1", "a1", "1"),
            ],
            note_items_by_id=note_items,
            body_anchors_by_id={
                "a-star": _anchor("a-star", "*", 0),
                "a1": _anchor("a1", "1", 1),
            },
            include_diagnostic_entries=False,
            diagnostic_machine_by_page={},
        )

        self.assertIn("Author *.", content)
        self.assertIn("[footnote] \\* Author footnote.", content)
        self.assertIn("Alpha[^1].", content)
        self.assertEqual(re.findall(r"^\[\^(\d+)\]:", content, re.MULTILINE), ["1"])


if __name__ == "__main__":
    unittest.main()

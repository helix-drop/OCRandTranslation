from __future__ import annotations

import unittest

from FNM_RE.app.pipeline import build_phase2_structure, build_phase3_structure
from FNM_RE.models import (
    BodyAnchorRecord,
    ChapterNoteModeRecord,
    ChapterRecord,
    NoteItemRecord,
    NoteRegionRecord,
    PagePartitionRecord,
    Phase2Structure,
)
from FNM_RE.shared.anchors import resolve_anchor_kind, scan_anchor_markers
from FNM_RE.shared.notes import normalize_note_marker
from FNM_RE.stages.note_links import build_note_links


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


def _partition(page_no: int, role: str = "body") -> PagePartitionRecord:
    return PagePartitionRecord(
        page_no=page_no,
        target_pdf_page=page_no,
        page_role=role,  # type: ignore[arg-type]
        confidence=1.0,
        reason="test",
        section_hint="",
        has_note_heading=False,
        note_scan_summary={},
    )


def _chapter(chapter_id: str, title: str, pages: list[int]) -> ChapterRecord:
    return ChapterRecord(
        chapter_id=chapter_id,
        title=title,
        start_page=min(pages),
        end_page=max(pages),
        pages=pages,
        source="fallback",
        boundary_state="ready",
    )


def _region(
    region_id: str,
    chapter_id: str,
    *,
    page_start: int,
    page_end: int | None = None,
    note_kind: str = "footnote",
    scope: str = "chapter",
) -> NoteRegionRecord:
    pages = list(range(page_start, int(page_end or page_start) + 1))
    return NoteRegionRecord(
        region_id=region_id,
        chapter_id=chapter_id,
        page_start=page_start,
        page_end=int(page_end or page_start),
        pages=pages,
        note_kind=note_kind,  # type: ignore[arg-type]
        scope=scope,  # type: ignore[arg-type]
        source="heading_scan",
        heading_text="",
        start_reason="test",
        end_reason="test",
        region_marker_alignment_ok=True,
        region_start_first_source_marker="",
        region_first_note_item_marker="",
        review_required=False,
    )


def _item(
    note_item_id: str, region_id: str, chapter_id: str, *, page_no: int, marker: str
) -> NoteItemRecord:
    return NoteItemRecord(
        note_item_id=note_item_id,
        region_id=region_id,
        chapter_id=chapter_id,
        page_no=page_no,
        marker=marker,
        marker_type="numeric",
        text=f"Note {marker}",
        source="test",
        source_page_label=f"p{page_no}",
        is_reconstructed=False,
        review_required=False,
    )


def _mode(chapter_id: str, note_mode: str) -> ChapterNoteModeRecord:
    return ChapterNoteModeRecord(
        chapter_id=chapter_id,
        note_mode=note_mode,  # type: ignore[arg-type]
        region_ids=[],
        primary_region_scope="",
        has_footnote_band=False,
        has_endnote_region=False,
    )


def _phase2_fixture(
    *,
    pages: list[PagePartitionRecord],
    chapters: list[ChapterRecord],
    note_regions: list[NoteRegionRecord],
    note_items: list[NoteItemRecord],
    chapter_modes: list[ChapterNoteModeRecord],
) -> Phase2Structure:
    return Phase2Structure(
        pages=pages,
        chapters=chapters,
        note_regions=note_regions,
        note_items=note_items,
        chapter_note_modes=chapter_modes,
    )


def _phase_signature(phase) -> tuple:
    return (
        tuple((row.page_no, row.page_role) for row in phase.pages),
        tuple(
            (row.chapter_id, row.title, row.start_page, row.end_page)
            for row in phase.chapters
        ),
        tuple((row.chapter_id, row.note_mode) for row in phase.chapter_note_modes),
        tuple(
            (
                row.region_id,
                row.chapter_id,
                row.scope,
                row.note_kind,
                row.page_start,
                row.page_end,
            )
            for row in phase.note_regions
        ),
        tuple(
            (row.note_item_id, row.region_id, row.chapter_id, row.page_no, row.marker)
            for row in phase.note_items
        ),
    )


class FnmRePhase3Test(unittest.TestCase):
    def test_year_like_marker_is_filtered(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [2020] and normal [12].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="12. Footnote text.",
            ),
            _make_page(2, markdown="Continuation body."),
        ]
        structure = build_phase3_structure(pages)
        markers = [row.normalized_marker for row in structure.body_anchors]
        self.assertIn("12", markers)
        self.assertNotIn("2020", markers)
        self.assertGreaterEqual(
            structure.summary.body_anchor_summary.get("year_like_filtered_count", 0), 1
        )

    def test_superscript_note_definition_lines_are_filtered(self):
        pages = [
            _make_page(
                1,
                markdown=(
                    "# Chapter One\n"
                    "Body keeps [8] reference.\n\n"
                    "$ ^{1} $ note definition line.\n\n"
                    "¹ another note definition.\n\n"
                    "<sup>2</sup> html note definition.\n\n"
                    "^{3} plain note definition."
                ),
                block_label="doc_title",
                block_text="Chapter One",
            ),
        ]
        structure = build_phase3_structure(pages)
        markers = [row.normalized_marker for row in structure.body_anchors]
        self.assertIn("8", markers)
        self.assertNotIn("1", markers)
        self.assertNotIn("2", markers)
        self.assertNotIn("3", markers)

    def test_anchor_kind_resolution_for_five_note_modes(self):
        self.assertEqual(resolve_anchor_kind("footnote_primary"), "footnote")
        self.assertEqual(resolve_anchor_kind("chapter_endnote_primary"), "endnote")
        self.assertEqual(resolve_anchor_kind("book_endnote_bound"), "endnote")
        self.assertEqual(resolve_anchor_kind("no_notes"), "unknown")
        self.assertEqual(
            resolve_anchor_kind("no_notes", has_page_footnote_band=True), "footnote"
        )
        self.assertEqual(resolve_anchor_kind("review_required"), "unknown")
        self.assertEqual(
            resolve_anchor_kind("review_required", has_page_footnote_band=True),
            "footnote",
        )

    def test_note_and_other_pages_do_not_generate_body_anchors(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                block_label="doc_title",
                block_text="Chapter One",
            ),
            _make_page(2, markdown="# Notes\n1. note page [2]."),
            _make_page(3, markdown="Advertisement page [3]."),
        ]
        structure = build_phase3_structure(
            pages,
            page_overrides={"2": {"page_role": "note"}, "3": {"page_role": "other"}},
        )
        anchor_pages = {row.page_no for row in structure.body_anchors}
        self.assertIn(1, anchor_pages)
        self.assertNotIn(2, anchor_pages)
        self.assertNotIn(3, anchor_pages)

    def test_synthetic_footnote_anchor_is_created_and_not_orphaned(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body")],
            chapters=[_chapter("ch-1", "Chapter 1", [1])],
            note_regions=[
                _region(
                    "rg-fn", "ch-1", page_start=1, note_kind="footnote", scope="chapter"
                )
            ],
            note_items=[_item("fn-1", "rg-fn", "ch-1", page_no=1, marker="1")],
            chapter_modes=[_mode("ch-1", "footnote_primary")],
        )
        anchors, links, _summary = build_note_links([], phase2, pages=[])
        self.assertTrue(any(row.synthetic for row in anchors))
        matched = [
            row
            for row in links
            if row.status == "matched" and row.note_kind == "footnote"
        ]
        self.assertTrue(matched)
        self.assertEqual(matched[0].resolver, "fallback")
        synthetic_ids = {row.anchor_id for row in anchors if row.synthetic}
        synthetic_orphan = [
            row
            for row in links
            if row.status == "orphan_anchor" and row.anchor_id in synthetic_ids
        ]
        self.assertFalse(synthetic_orphan)

    def test_explicit_anchor_can_replace_synthetic_match(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body")],
            chapters=[_chapter("ch-1", "Chapter 1", [1])],
            note_regions=[
                _region(
                    "rg-fn", "ch-1", page_start=1, note_kind="footnote", scope="chapter"
                )
            ],
            note_items=[_item("fn-1", "rg-fn", "ch-1", page_no=1, marker="1")],
            chapter_modes=[_mode("ch-1", "review_required")],
        )
        explicit_anchor = BodyAnchorRecord(
            anchor_id="anchor-explicit-1",
            chapter_id="ch-1",
            page_no=1,
            paragraph_index=0,
            char_start=5,
            char_end=8,
            source_marker="[1]",
            normalized_marker="1",
            anchor_kind="unknown",
            certainty=0.6,
            source_text="Body [1]",
            source="markdown:bracket",
            synthetic=False,
            ocr_repaired_from_marker="",
        )
        anchors, links, _summary = build_note_links([explicit_anchor], phase2, pages=[])
        matched = [
            row
            for row in links
            if row.note_item_id == "fn-1" and row.status == "matched"
        ]
        self.assertTrue(matched)
        self.assertEqual(matched[0].anchor_id, "anchor-explicit-1")
        self.assertEqual(matched[0].resolver, "repair")
        self.assertTrue(any(row.synthetic for row in anchors))

    def test_ocr_shortened_marker_is_repaired(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body")],
            chapters=[_chapter("ch-1", "Chapter 1", [1])],
            note_regions=[
                _region(
                    "rg-fn", "ch-1", page_start=1, note_kind="footnote", scope="chapter"
                )
            ],
            note_items=[_item("fn-1", "rg-fn", "ch-1", page_no=1, marker="123")],
            chapter_modes=[_mode("ch-1", "footnote_primary")],
        )
        explicit_anchor = BodyAnchorRecord(
            anchor_id="anchor-short-1",
            chapter_id="ch-1",
            page_no=1,
            paragraph_index=0,
            char_start=4,
            char_end=7,
            source_marker="[12]",
            normalized_marker="12",
            anchor_kind="footnote",
            certainty=1.0,
            source_text="Body [12]",
            source="markdown:bracket",
            synthetic=False,
            ocr_repaired_from_marker="",
        )
        anchors, links, _summary = build_note_links([explicit_anchor], phase2, pages=[])
        repaired_link = [
            row
            for row in links
            if row.note_item_id == "fn-1" and row.status == "matched"
        ]
        self.assertTrue(repaired_link)
        self.assertEqual(repaired_link[0].resolver, "repair")
        repaired_anchor = next(
            row for row in anchors if row.anchor_id == "anchor-short-1"
        )
        self.assertEqual(repaired_anchor.normalized_marker, "123")
        self.assertEqual(repaired_anchor.ocr_repaired_from_marker, "12")

    def test_chapter_scope_endnote_wont_cross_chapter_match(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body"), _partition(2, "body")],
            chapters=[
                _chapter("ch-1", "Chapter 1", [1]),
                _chapter("ch-2", "Chapter 2", [2]),
            ],
            note_regions=[
                _region(
                    "rg-en", "ch-1", page_start=1, note_kind="endnote", scope="chapter"
                )
            ],
            note_items=[_item("en-1", "rg-en", "ch-1", page_no=1, marker="5")],
            chapter_modes=[
                _mode("ch-1", "chapter_endnote_primary"),
                _mode("ch-2", "chapter_endnote_primary"),
            ],
        )
        anchor = BodyAnchorRecord(
            anchor_id="anchor-end-2",
            chapter_id="ch-2",
            page_no=2,
            paragraph_index=0,
            char_start=1,
            char_end=4,
            source_marker="[5]",
            normalized_marker="5",
            anchor_kind="endnote",
            certainty=1.0,
            source_text="Body [5]",
            source="markdown:bracket",
            synthetic=False,
            ocr_repaired_from_marker="",
        )
        _anchors, links, _summary = build_note_links([anchor], phase2, pages=[])
        target = next(row for row in links if row.note_item_id == "en-1")
        self.assertEqual(target.status, "orphan_note")

    def test_book_scope_endnote_can_use_fallback_resolver(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body")],
            chapters=[_chapter("ch-1", "Chapter 1", [1])],
            note_regions=[
                _region(
                    "rg-book", "ch-1", page_start=1, note_kind="endnote", scope="book"
                )
            ],
            note_items=[_item("en-1", "rg-book", "ch-1", page_no=1, marker="7")],
            chapter_modes=[_mode("ch-1", "book_endnote_bound")],
        )
        anchor = BodyAnchorRecord(
            anchor_id="anchor-end-1",
            chapter_id="ch-1",
            page_no=1,
            paragraph_index=0,
            char_start=0,
            char_end=3,
            source_marker="[7]",
            normalized_marker="7",
            anchor_kind="endnote",
            certainty=1.0,
            source_text="Body [7]",
            source="markdown:bracket",
            synthetic=False,
            ocr_repaired_from_marker="",
        )
        _anchors, links, _summary = build_note_links([anchor], phase2, pages=[])
        target = next(row for row in links if row.note_item_id == "en-1")
        self.assertEqual(target.status, "matched")
        self.assertEqual(target.resolver, "fallback")

    def test_ambiguous_candidates_return_ambiguous_status(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body")],
            chapters=[_chapter("ch-1", "Chapter 1", [1])],
            note_regions=[
                _region(
                    "rg-fn", "ch-1", page_start=1, note_kind="footnote", scope="chapter"
                )
            ],
            note_items=[_item("fn-1", "rg-fn", "ch-1", page_no=1, marker="1")],
            chapter_modes=[_mode("ch-1", "footnote_primary")],
        )
        anchors = [
            BodyAnchorRecord(
                "a-1",
                "ch-1",
                1,
                0,
                1,
                3,
                "[1]",
                "1",
                "footnote",
                1.0,
                "A[1]",
                "markdown:bracket",
                False,
                "",
            ),
            BodyAnchorRecord(
                "a-2",
                "ch-1",
                1,
                1,
                5,
                7,
                "[1]",
                "1",
                "footnote",
                1.0,
                "B[1]",
                "markdown:bracket",
                False,
                "",
            ),
        ]
        _anchors, links, _summary = build_note_links(anchors, phase2, pages=[])
        target = next(row for row in links if row.note_item_id == "fn-1")
        self.assertEqual(target.status, "ambiguous")
        orphan_same_marker = [
            row for row in links if row.status == "orphan_anchor" and row.marker == "1"
        ]
        self.assertFalse(orphan_same_marker)

    def test_nested_duplicate_candidates_prefer_more_local_anchor(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body")],
            chapters=[_chapter("ch-1", "Chapter 1", [1])],
            note_regions=[
                _region(
                    "rg-fn", "ch-1", page_start=1, note_kind="footnote", scope="chapter"
                )
            ],
            note_items=[_item("fn-1", "rg-fn", "ch-1", page_no=1, marker="1")],
            chapter_modes=[_mode("ch-1", "footnote_primary")],
        )
        anchors = [
            BodyAnchorRecord(
                "a-local",
                "ch-1",
                1,
                0,
                10,
                12,
                "[1]",
                "1",
                "footnote",
                1.0,
                "Short local sentence with [1].",
                "markdown:bracket",
                False,
                "",
            ),
            BodyAnchorRecord(
                "a-merged",
                "ch-1",
                1,
                1,
                10,
                12,
                "[1]",
                "1",
                "footnote",
                1.0,
                "Prelude. Short local sentence with [1]. Extra merged paragraph context.",
                "markdown:bracket",
                False,
                "",
            ),
        ]
        _anchors, links, _summary = build_note_links(anchors, phase2, pages=[])
        target = next(row for row in links if row.note_item_id == "fn-1")
        self.assertEqual(target.status, "matched")
        self.assertEqual(target.anchor_id, "a-local")

    def test_html_and_plain_duplicate_candidates_collapse_to_local_anchor(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body")],
            chapters=[_chapter("ch-1", "Chapter 1", [1])],
            note_regions=[
                _region(
                    "rg-fn", "ch-1", page_start=1, note_kind="footnote", scope="chapter"
                )
            ],
            note_items=[_item("fn-1", "rg-fn", "ch-1", page_no=1, marker="52")],
            chapter_modes=[_mode("ch-1", "footnote_primary")],
        )
        anchors = [
            BodyAnchorRecord(
                "a-html",
                "ch-1",
                1,
                0,
                10,
                19,
                "$ ^{52} $",
                "52",
                "footnote",
                1.0,
                "<table><tr><td>Événements de la Révolution :</td><td>30 [soit 27 %] $ ^{52} $</td></tr></table>",
                "markdown:latex",
                False,
                "",
            ),
            BodyAnchorRecord(
                "a-plain",
                "ch-1",
                1,
                1,
                10,
                19,
                "$ ^{52} $",
                "52",
                "footnote",
                1.0,
                "Événements de la Révolution : 30 [soit 27 %] $ ^{52} $",
                "ocr_block:latex",
                False,
                "",
            ),
        ]
        _anchors, links, _summary = build_note_links(anchors, phase2, pages=[])
        target = next(row for row in links if row.note_item_id == "fn-1")
        self.assertEqual(target.status, "matched")
        self.assertEqual(target.anchor_id, "a-plain")
        orphan_same_marker = [
            row for row in links if row.status == "orphan_anchor" and row.marker == "52"
        ]
        self.assertFalse(orphan_same_marker)

    def test_footnote_multiple_candidates_choose_unique_nearest(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body"), _partition(2, "body")],
            chapters=[_chapter("ch-1", "Chapter 1", [1, 2])],
            note_regions=[
                _region(
                    "rg-fn", "ch-1", page_start=2, note_kind="footnote", scope="chapter"
                )
            ],
            note_items=[_item("fn-1", "rg-fn", "ch-1", page_no=2, marker="1")],
            chapter_modes=[_mode("ch-1", "footnote_primary")],
        )
        anchors = [
            BodyAnchorRecord(
                "a-near",
                "ch-1",
                2,
                0,
                1,
                3,
                "[1]",
                "1",
                "footnote",
                1.0,
                "A[1]",
                "markdown:bracket",
                False,
                "",
            ),
            BodyAnchorRecord(
                "a-far",
                "ch-1",
                1,
                1,
                5,
                7,
                "[1]",
                "1",
                "footnote",
                1.0,
                "B[1]",
                "markdown:bracket",
                False,
                "",
            ),
        ]
        _anchors, links, _summary = build_note_links(anchors, phase2, pages=[])
        target = next(row for row in links if row.note_item_id == "fn-1")
        self.assertEqual(target.status, "matched")
        self.assertEqual(target.anchor_id, "a-near")
        orphan_same_marker = [
            row for row in links if row.status == "orphan_anchor" and row.marker == "1"
        ]
        self.assertFalse(orphan_same_marker)

    def test_fallback_chapter_endnote_can_repair_with_cross_chapter_anchor(self):
        phase2 = _phase2_fixture(
            pages=[_partition(9, "body"), _partition(10, "note")],
            chapters=[
                _chapter("ch-fallback-0001", "Chapter A", [10]),
                _chapter("ch-fallback-0002", "Chapter B", [9]),
            ],
            note_regions=[
                _region(
                    "rg-en",
                    "ch-fallback-0001",
                    page_start=10,
                    note_kind="endnote",
                    scope="chapter",
                )
            ],
            note_items=[
                _item("en-1", "rg-en", "ch-fallback-0001", page_no=10, marker="5")
            ],
            chapter_modes=[
                _mode("ch-fallback-0001", "no_notes"),
                _mode("ch-fallback-0002", "no_notes"),
            ],
        )
        anchor = BodyAnchorRecord(
            anchor_id="anchor-end-2",
            chapter_id="ch-fallback-0002",
            page_no=9,
            paragraph_index=0,
            char_start=1,
            char_end=4,
            source_marker="[5]",
            normalized_marker="5",
            anchor_kind="unknown",
            certainty=0.6,
            source_text="Body [5]",
            source="markdown:bracket",
            synthetic=False,
            ocr_repaired_from_marker="",
        )
        _anchors, links, _summary = build_note_links([anchor], phase2, pages=[])
        target = next(row for row in links if row.note_item_id == "en-1")
        self.assertEqual(target.status, "matched")
        self.assertEqual(target.anchor_id, "anchor-end-2")

    def test_toc_chapter_endnote_can_repair_with_cross_chapter_anchor(self):
        phase2 = _phase2_fixture(
            pages=[_partition(61, "body"), _partition(64, "note")],
            chapters=[
                _chapter("toc-ch-002", "Chapter A", [64]),
                _chapter("toc-ch-003", "Chapter B", [61]),
            ],
            note_regions=[
                _region(
                    "rg-en",
                    "toc-ch-002",
                    page_start=64,
                    note_kind="endnote",
                    scope="chapter",
                )
            ],
            note_items=[_item("en-1", "rg-en", "toc-ch-002", page_no=64, marker="7")],
            chapter_modes=[
                _mode("toc-ch-002", "chapter_endnote_primary"),
                _mode("toc-ch-003", "chapter_endnote_primary"),
            ],
        )
        anchor = BodyAnchorRecord(
            anchor_id="anchor-end-3",
            chapter_id="toc-ch-003",
            page_no=61,
            paragraph_index=0,
            char_start=1,
            char_end=4,
            source_marker="[7]",
            normalized_marker="7",
            anchor_kind="endnote",
            certainty=1.0,
            source_text="Body [7]",
            source="markdown:bracket",
            synthetic=False,
            ocr_repaired_from_marker="",
        )
        _anchors, links, _summary = build_note_links([anchor], phase2, pages=[])
        target = next(row for row in links if row.note_item_id == "en-1")
        self.assertEqual(target.status, "matched")
        self.assertEqual(target.anchor_id, "anchor-end-3")

    def test_fallback_chapter_without_note_markers_skips_orphan_anchor(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body")],
            chapters=[_chapter("ch-fallback-0001", "Chapter A", [1])],
            note_regions=[],
            note_items=[],
            chapter_modes=[_mode("ch-fallback-0001", "no_notes")],
        )
        anchor = BodyAnchorRecord(
            anchor_id="anchor-1",
            chapter_id="ch-fallback-0001",
            page_no=1,
            paragraph_index=0,
            char_start=0,
            char_end=2,
            source_marker="[1]",
            normalized_marker="1",
            anchor_kind="unknown",
            certainty=0.6,
            source_text="Body [1]",
            source="markdown:bracket",
            synthetic=False,
            ocr_repaired_from_marker="",
        )
        _anchors, links, _summary = build_note_links([anchor], phase2, pages=[])
        orphan_anchor_links = [row for row in links if row.status == "orphan_anchor"]
        self.assertFalse(orphan_anchor_links)

    def test_toc_chapter_out_of_note_range_skips_orphan_anchor(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body"), _partition(2, "note")],
            chapters=[_chapter("toc-ch-001", "Chapter A", [1, 2])],
            note_regions=[
                _region(
                    "rg-fn",
                    "toc-ch-001",
                    page_start=2,
                    note_kind="footnote",
                    scope="chapter",
                )
            ],
            note_items=[
                _item("fn-10", "rg-fn", "toc-ch-001", page_no=2, marker="10"),
                _item("fn-12", "rg-fn", "toc-ch-001", page_no=2, marker="12"),
            ],
            chapter_modes=[_mode("toc-ch-001", "footnote_primary")],
        )
        anchor = BodyAnchorRecord(
            anchor_id="anchor-30",
            chapter_id="toc-ch-001",
            page_no=1,
            paragraph_index=0,
            char_start=0,
            char_end=3,
            source_marker="[30]",
            normalized_marker="30",
            anchor_kind="footnote",
            certainty=1.0,
            source_text="Body [30]",
            source="markdown:bracket",
            synthetic=False,
            ocr_repaired_from_marker="",
        )
        _anchors, links, _summary = build_note_links([anchor], phase2, pages=[])
        orphan_anchor_links = [row for row in links if row.status == "orphan_anchor"]
        self.assertFalse(orphan_anchor_links)

    def test_unused_explicit_anchor_generates_orphan_anchor(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body")],
            chapters=[_chapter("ch-1", "Chapter 1", [1])],
            note_regions=[],
            note_items=[],
            chapter_modes=[_mode("ch-1", "footnote_primary")],
        )
        anchor = BodyAnchorRecord(
            anchor_id="anchor-1",
            chapter_id="ch-1",
            page_no=1,
            paragraph_index=0,
            char_start=0,
            char_end=2,
            source_marker="[1]",
            normalized_marker="1",
            anchor_kind="footnote",
            certainty=1.0,
            source_text="Body [1]",
            source="markdown:bracket",
            synthetic=False,
            ocr_repaired_from_marker="",
        )
        _anchors, links, _summary = build_note_links([anchor], phase2, pages=[])
        orphan_anchor_links = [row for row in links if row.status == "orphan_anchor"]
        self.assertTrue(orphan_anchor_links)

    def test_review_seed_summary_collects_expected_ids(self):
        phase2 = _phase2_fixture(
            pages=[_partition(1, "body")],
            chapters=[_chapter("ch-1", "Chapter 1", [1])],
            note_regions=[
                _region(
                    "rg-fn", "ch-1", page_start=1, note_kind="footnote", scope="chapter"
                ),
                _region(
                    "rg-en-a",
                    "ch-1",
                    page_start=1,
                    note_kind="endnote",
                    scope="chapter",
                ),
                _region(
                    "rg-en-b",
                    "ch-1",
                    page_start=1,
                    note_kind="endnote",
                    scope="chapter",
                ),
            ],
            note_items=[
                _item("fn-1", "rg-fn", "ch-1", page_no=1, marker="1"),
                _item("en-1", "rg-en-a", "ch-1", page_no=1, marker="2"),
                _item("en-2", "rg-en-b", "ch-1", page_no=1, marker="3"),
            ],
            chapter_modes=[_mode("ch-1", "review_required")],
        )
        anchors = [
            BodyAnchorRecord(
                "end-1",
                "ch-1",
                1,
                0,
                0,
                2,
                "[3]",
                "3",
                "endnote",
                1.0,
                "Body [3]",
                "markdown:bracket",
                False,
                "",
            ),
            BodyAnchorRecord(
                "end-2",
                "ch-1",
                1,
                1,
                5,
                7,
                "[3]",
                "3",
                "endnote",
                1.0,
                "Body [3]",
                "markdown:bracket",
                False,
                "",
            ),
            BodyAnchorRecord(
                "unk-1",
                "ch-1",
                1,
                2,
                8,
                10,
                "[9]",
                "9",
                "unknown",
                0.6,
                "Body [9]",
                "markdown:bracket",
                False,
                "",
            ),
        ]
        _anchors, _links, summary = build_note_links(anchors, phase2, pages=[])
        review = summary.get("review_seed_summary") or {}
        self.assertEqual(review.get("boundary_review_required_count"), 1)
        self.assertTrue(review.get("synthetic_anchor_ids"))
        self.assertTrue(review.get("orphan_link_ids"))
        self.assertFalse(review.get("ambiguous_link_ids"))
        self.assertIn("unk-1", set(review.get("uncertain_anchor_ids") or []))

    def test_phase3_contains_phase2_fields_without_mutating_phase2(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="1. footnote",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
            _make_page(3, markdown="# Notes\n1. endnote"),
        ]
        phase2 = build_phase2_structure(
            pages, page_overrides={"3": {"page_role": "note"}}
        )
        before = _phase_signature(phase2)
        phase3 = build_phase3_structure(
            pages, page_overrides={"3": {"page_role": "note"}}
        )
        after = _phase_signature(phase2)
        self.assertEqual(before, after)
        self.assertEqual(_phase_signature(phase3), before)
        self.assertIsNotNone(phase3.summary.body_anchor_summary)
        self.assertIsNotNone(phase3.summary.note_link_summary)

    def test_normalize_note_marker_preserves_all_digits(self):
        self.assertEqual(normalize_note_marker("$^{13}$"), "13")
        self.assertEqual(normalize_note_marker("<sup>14</sup>"), "14")
        self.assertEqual(normalize_note_marker("[47]"), "47")
        self.assertEqual(normalize_note_marker("¹²³"), "123")
        self.assertEqual(normalize_note_marker("⁴⁷"), "47")
        self.assertEqual(normalize_note_marker("^{52}"), "52")
        self.assertEqual(normalize_note_marker("13."), "13")
        self.assertEqual(normalize_note_marker("09"), "9")
        self.assertEqual(normalize_note_marker("0"), "0")
        self.assertEqual(normalize_note_marker(""), "")
        self.assertEqual(normalize_note_marker(None), "")

    def test_scan_anchor_markers_certainty_per_pattern(self):
        matches, _ = scan_anchor_markers("$^{13}$ <sup>14</sup> [47] ¹²³ ^{52}")
        markers = sorted(matches, key=lambda m: int(m["normalized_marker"]))
        by_marker = {m["normalized_marker"]: m["certainty"] for m in markers}
        self.assertEqual(by_marker.get("13"), 1.0)
        self.assertEqual(by_marker.get("14"), 1.0)
        self.assertEqual(by_marker.get("47"), 1.0)
        self.assertEqual(by_marker.get("52"), 0.4)
        self.assertEqual(by_marker.get("123"), 1.0)

    def test_build_body_anchors_certainty_per_anchor(self):
        pages = [
            _make_page(
                1,
                markdown=(
                    "# Chapter One\n"
                    "Body $^{13}$ and <sup>14</sup> and [47] and ¹²³ and ^{52}."
                ),
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="13. footnote 13\n14. footnote 14",
            ),
        ]
        structure = build_phase3_structure(pages)
        by_marker = {
            row.normalized_marker: row.certainty for row in structure.body_anchors
        }
        self.assertAlmostEqual(by_marker.get("13"), 1.0)
        self.assertAlmostEqual(by_marker.get("14"), 1.0)
        self.assertAlmostEqual(by_marker.get("47"), 1.0)
        self.assertAlmostEqual(by_marker.get("52"), 0.4)
        self.assertAlmostEqual(by_marker.get("123"), 1.0)


if __name__ == "__main__":
    unittest.main()

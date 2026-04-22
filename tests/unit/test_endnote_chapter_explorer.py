from __future__ import annotations

import unittest

from FNM_RE.models import ChapterRecord, HeadingCandidate, NoteRegionRecord, Phase1Structure
from FNM_RE.stages.endnote_chapter_explorer import explore_endnote_chapter_regions


def _chapter(chapter_id: str, title: str, start_page: int, end_page: int) -> ChapterRecord:
    return ChapterRecord(
        chapter_id=chapter_id,
        title=title,
        start_page=start_page,
        end_page=end_page,
        pages=list(range(start_page, end_page + 1)),
        source="visual_toc",
        boundary_state="ready",
    )


def _region(*, region_id: str = "nr-en-bk-0001-none", chapter_id: str = "", pages: list[int]) -> NoteRegionRecord:
    return NoteRegionRecord(
        region_id=region_id,
        chapter_id=chapter_id,
        page_start=pages[0],
        page_end=pages[-1],
        pages=list(pages),
        note_kind="endnote",
        scope="book",
        source="heading_scan",
        heading_text="",
        start_reason="notes_heading",
        end_reason="document_end",
        region_marker_alignment_ok=True,
        region_start_first_source_marker="1",
        region_first_note_item_marker="",
        review_required=False,
    )


def _page(page_no: int, *, markdown: str = "", section_title: str = "") -> dict:
    items = []
    if section_title:
        items.append(
            {
                "kind": "endnote",
                "marker": "1",
                "number": 1,
                "text": "1. note text",
                "order": 1,
                "source": "markdown",
                "confidence": 0.9,
                "section_title": section_title,
            }
        )
    return {
        "bookPage": page_no,
        "markdown": markdown,
        "_note_scan": {
            "page_kind": "endnote_collection",
            "items": items,
            "section_hints": [section_title] if section_title else ["Notes"],
            "ambiguity_flags": [],
            "note_start_line_index": 0,
        },
    }


def _hints(
    *,
    start_page: int = 0,
    title: str = "Notes",
    toc_subentries: list[dict] | None = None,
) -> dict:
    return {
        "endnotes_summary": {
            "present": True,
            "container_title": title,
            "container_printed_page": start_page or None,
            "container_visual_order": 10,
            "has_chapter_keyed_subentries_in_toc": bool(toc_subentries),
            "subentry_pattern": None,
        },
        "container_start_page_hint": int(start_page or 0),
        "container_title": title,
        "has_toc_subentries": bool(toc_subentries),
        "toc_subentries": list(toc_subentries or []),
    }


class EndnoteChapterExplorerTest(unittest.TestCase):
    def test_rebinds_book_region_from_endnote_section_title(self):
        phase1 = Phase1Structure(
            chapters=[
                _chapter("ch-1", "Chapter One", 1, 10),
                _chapter("ch-2", "Chapter Two", 11, 20),
            ]
        )
        regions = [_region(pages=[30, 31])]
        page_by_no = {
            30: _page(30, markdown="# Notes\nChapter Two\n1. note", section_title="Chapter Two"),
            31: _page(31, markdown="2. note"),
        }

        rebuilt, summary = explore_endnote_chapter_regions(
            regions,
            phase1=phase1,
            page_by_no=page_by_no,
        )

        self.assertEqual(len(rebuilt), 1)
        self.assertEqual(rebuilt[0].chapter_id, "ch-2")
        self.assertEqual(summary.get("rebind_count"), 1)
        self.assertEqual(summary.get("page_signal_count"), 1)

    def test_uses_heading_candidate_visual_signal(self):
        phase1 = Phase1Structure(
            chapters=[
                _chapter("ch-1", "Chapter One", 1, 10),
                _chapter("ch-2", "Chapter Two", 11, 20),
            ],
            heading_candidates=[
                HeadingCandidate(
                    heading_id="hc-30",
                    page_no=30,
                    text="Chapter Two",
                    normalized_text="chapter two",
                    source="pdf_font_band",
                    block_label="paragraph_title",
                    top_band=True,
                    confidence=0.92,
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
            ],
        )
        regions = [_region(pages=[30])]
        page_by_no = {
            30: _page(30, markdown="# Notes\n1. note"),
        }

        rebuilt, summary = explore_endnote_chapter_regions(
            regions,
            phase1=phase1,
            page_by_no=page_by_no,
        )

        self.assertEqual(len(rebuilt), 1)
        self.assertEqual(rebuilt[0].chapter_id, "ch-2")
        self.assertGreaterEqual(summary.get("page_signal_count", 0), 1)

    def test_splits_book_region_from_toc_numbered_subentries(self):
        phase1 = Phase1Structure(
            chapters=[
                _chapter("ch-1", "Chapter One", 1, 10),
                _chapter("ch-2", "Chapter Two", 11, 20),
            ]
        )
        regions = [_region(pages=[30, 31])]
        page_by_no = {
            30: _page(30, markdown="# Notes\n1. Note for chapter one."),
            31: _page(31, markdown="2. Note for chapter two."),
        }
        hints = _hints(
            start_page=30,
            toc_subentries=[
                {"title": "1. Chapter One", "printed_page": 30, "visual_order": 11, "match_mode": "numbered"},
                {"title": "2. Chapter Two", "printed_page": 31, "visual_order": 12, "match_mode": "numbered"},
            ],
        )

        rebuilt, summary = explore_endnote_chapter_regions(
            regions,
            phase1=phase1,
            page_by_no=page_by_no,
            endnote_explorer_hints=hints,
        )

        self.assertEqual(len(rebuilt), 2)
        self.assertEqual([row.chapter_id for row in rebuilt], ["ch-1", "ch-2"])
        self.assertTrue(all(row.source == "explorer_toc_match" for row in rebuilt))
        self.assertGreaterEqual(int(summary.get("toc_match_count") or 0), 2)
        self.assertGreaterEqual(int(summary.get("split_count") or 0), 1)

    def test_named_toc_subentries_bind_introduction_and_numbered_chapter(self):
        phase1 = Phase1Structure(
            chapters=[
                _chapter("intro", "Introduction", 1, 5),
                _chapter("ch-1", "Chapter One", 6, 15),
            ]
        )
        regions = [_region(pages=[30, 31])]
        page_by_no = {
            30: _page(30, markdown="# Notes\n1. Intro note."),
            31: _page(31, markdown="2. Chapter note."),
        }
        hints = _hints(
            start_page=30,
            toc_subentries=[
                {"title": "Notes to Introduction", "printed_page": 30, "visual_order": 11, "match_mode": "named"},
                {"title": "Notes to Chapter 1", "printed_page": 31, "visual_order": 12, "match_mode": "named"},
            ],
        )

        rebuilt, summary = explore_endnote_chapter_regions(
            regions,
            phase1=phase1,
            page_by_no=page_by_no,
            endnote_explorer_hints=hints,
        )

        self.assertEqual(len(rebuilt), 2)
        self.assertEqual([row.chapter_id for row in rebuilt], ["intro", "ch-1"])
        self.assertEqual(int(summary.get("toc_match_count") or 0), 2)

    def test_conflicting_toc_and_page_signal_keeps_region_unsplit_and_marks_review(self):
        phase1 = Phase1Structure(
            chapters=[
                _chapter("ch-1", "Chapter One", 1, 10),
                _chapter("ch-2", "Chapter Two", 11, 20),
            ]
        )
        regions = [_region(pages=[30])]
        page_by_no = {
            30: _page(30, markdown="# Notes\nChapter Two\n1. Note", section_title="Chapter Two"),
        }
        hints = _hints(
            start_page=30,
            toc_subentries=[
                {"title": "1. Chapter One", "printed_page": 30, "visual_order": 11, "match_mode": "numbered"},
            ],
        )

        rebuilt, summary = explore_endnote_chapter_regions(
            regions,
            phase1=phase1,
            page_by_no=page_by_no,
            endnote_explorer_hints=hints,
        )

        self.assertEqual(len(rebuilt), 1)
        self.assertEqual(rebuilt[0].chapter_id, "")
        self.assertTrue(rebuilt[0].review_required)
        self.assertGreaterEqual(int(summary.get("ambiguous_page_count") or 0), 1)


if __name__ == "__main__":
    unittest.main()

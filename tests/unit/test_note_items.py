from __future__ import annotations

import unittest

from FNM_RE.models import ChapterRecord, NoteRegionRecord, Phase1Structure
from FNM_RE.stages.note_items import build_note_items


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


def _region(region_id: str, chapter_id: str, pages: list[int], heading_text: str) -> NoteRegionRecord:
    return NoteRegionRecord(
        region_id=region_id,
        chapter_id=chapter_id,
        page_start=pages[0],
        page_end=pages[-1],
        pages=list(pages),
        note_kind="endnote",
        scope="book",
        source="explorer_signal_match",
        heading_text=heading_text,
        start_reason="notes_heading",
        end_reason="document_end",
        region_marker_alignment_ok=True,
        region_start_first_source_marker="",
        region_first_note_item_marker="",
        review_required=False,
    )


def _page(page_no: int, markdown: str) -> dict:
    return {
        "bookPage": page_no,
        "fileIdx": page_no - 1,
        "target_pdf_page": page_no,
        "markdown": markdown,
        "footnotes": "",
        "prunedResult": {"height": 1200, "width": 900, "parsing_res_list": []},
    }


class NoteItemsTest(unittest.TestCase):
    def test_shared_boundary_page_splits_items_by_endnote_section_title(self):
        phase1 = Phase1Structure(
            chapters=[
                _chapter("intro", "Introduction", 1, 10),
                _chapter("ch-1", "1. First Chapter", 11, 20),
            ]
        )
        regions = [
            _region("r-intro", "intro", [30, 31], "Introduction"),
            _region("r-ch-1", "ch-1", [31, 32], "1. First Chapter"),
        ]
        pages = [
            _page(30, "# Notes\n24. Prior intro note.\n25. More intro note."),
            _page(
                31,
                "26. Final intro note.\n"
                "### 1. First Chapter\n"
                "1. First chapter note.\n"
                "2. Second chapter note.",
            ),
            _page(32, "3. Third chapter note.\n4. Fourth chapter note."),
        ]

        items, summary = build_note_items(regions, phase1, pages=pages)

        markers_by_chapter: dict[str, list[str]] = {}
        for item in items:
            markers_by_chapter.setdefault(item.chapter_id, []).append(item.marker)
        self.assertEqual(markers_by_chapter.get("intro"), ["24", "25", "26"])
        self.assertEqual(markers_by_chapter.get("ch-1"), ["1", "2", "3", "4"])
        self.assertEqual(summary.get("shared_page_split_count"), 1)

    def test_shared_boundary_page_splits_items_by_heading_line_without_scan_section_title(self):
        phase1 = Phase1Structure(
            chapters=[
                _chapter("intro", "Introduction", 1, 10),
                _chapter("ch-1", "1. First Chapter", 11, 20),
            ]
        )
        regions = [
            _region("r-intro", "intro", [30, 31], "Introduction"),
            _region("r-ch-1", "ch-1", [31, 32], "1. First Chapter"),
        ]
        pages = [
            _page(30, "# Notes\n24. Prior intro note.\n25. More intro note."),
            _page(
                31,
                "26. Final intro note.\n"
                "### 1. First Chapter For the source of the epigraph, see note 38.\n"
                "1. First chapter note.\n"
                "2. Second chapter note.",
            ),
            _page(32, "3. Third chapter note.\n4. Fourth chapter note."),
        ]

        items, summary = build_note_items(regions, phase1, pages=pages)

        markers_by_chapter: dict[str, list[str]] = {}
        for item in items:
            markers_by_chapter.setdefault(item.chapter_id, []).append(item.marker)
        self.assertEqual(markers_by_chapter.get("intro"), ["24", "25", "26"])
        self.assertEqual(markers_by_chapter.get("ch-1"), ["1", "2", "3", "4"])
        self.assertEqual(summary.get("shared_page_text_split_count"), 1)


if __name__ == "__main__":
    unittest.main()

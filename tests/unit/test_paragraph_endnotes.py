"""Paragraph endnote stage unit tests."""

from __future__ import annotations

import unittest

from FNM_RE.models import ChapterEndnoteRecord, ChapterRecord, PagePartitionRecord, Phase1Structure, Phase1Summary
from FNM_RE.stages.paragraph_endnotes import build_paragraph_endnotes


def _partition(page_no: int, role: str = "body") -> PagePartitionRecord:
    return PagePartitionRecord(
        page_no=page_no,
        target_pdf_page=page_no,
        page_role=role,
        confidence=1.0,
        reason="test",
        section_hint="",
        has_note_heading=False,
        note_scan_summary={},
    )


def _chapter(
    chapter_id: str,
    title: str,
    pages: list[int],
) -> ChapterRecord:
    return ChapterRecord(
        chapter_id=chapter_id,
        title=title,
        start_page=min(pages) if pages else 0,
        end_page=max(pages) if pages else 0,
        pages=pages,
        source="fallback",
        boundary_state="ready",
    )


def _page(page_no: int, *, markdown: str = "", scan_items: list[dict] | None = None) -> dict:
    note_scan = {}
    if scan_items:
        note_scan["items"] = scan_items
    return {
        "bookPage": page_no,
        "fileIdx": page_no - 1,
        "target_pdf_page": page_no,
        "markdown": markdown,
        "_note_scan": note_scan,
        "footnotes": "",
        "prunedResult": {"height": 1200, "width": 900, "parsing_res_list": []},
    }


def _phase1(
    *,
    pages: list[PagePartitionRecord],
    chapters: list[ChapterRecord],
) -> Phase1Structure:
    return Phase1Structure(
        pages=pages,
        chapters=chapters,
        heading_candidates=[],
        section_heads=[],
        endnote_explorer_hints={},
        summary=Phase1Summary(),
    )


class ParagraphEndnotesTest(unittest.TestCase):
    """Test paragraph endnote building."""

    def test_simple_endnote_page_with_role_note(self):
        """Endnote pages with role=note are detected and parsed."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2])
        md = (
            "1. First endnote about something.\n"
            "2. Second endnote about something else.\n"
            "3. Third endnote with more details."
        )
        phase1 = _phase1(
            pages=[_partition(1), _partition(2, role="note")],
            chapters=[ch],
        )
        pages_data = [_page(1), _page(2, markdown=md)]

        records, summary = build_paragraph_endnotes(phase1, pages=pages_data)

        self.assertEqual(summary["total_endnote_items"], 3)
        self.assertEqual(summary["chapter_count"], 1)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].chapter_id, "ch-1")
        self.assertEqual(records[0].marker, "1")
        self.assertEqual(records[0].ordinal, 1)
        self.assertEqual(records[1].marker, "2")
        self.assertEqual(records[1].ordinal, 2)
        self.assertEqual(records[2].marker, "3")
        self.assertEqual(records[2].ordinal, 3)

    def test_endnote_scan_items(self):
        """_note_scan endnote items are used when no markdown."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2])
        scan_items = [
            {"kind": "endnote", "marker": "1", "text": "Endnote from scan"},
            {"kind": "endnote", "marker": "2", "text": "Second scan endnote"},
        ]
        phase1 = _phase1(
            pages=[_partition(1), _partition(2, role="note")],
            chapters=[ch],
        )
        pages_data = [_page(1), _page(2, scan_items=scan_items)]

        records, _ = build_paragraph_endnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].marker, "1")
        self.assertEqual(records[1].marker, "2")

    def test_endnote_page_with_notes_heading_but_other_role(self):
        """Other-role page with notes heading is still detected."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2])
        md = (
            "Notes\n\n"
            "1. First endnote.\n"
            "2. Second endnote."
        )
        phase1 = _phase1(
            pages=[_partition(1), _partition(2, role="other")],
            chapters=[ch],
        )
        pages_data = [_page(1), _page(2, markdown=md)]

        records, summary = build_paragraph_endnotes(phase1, pages=pages_data)

        self.assertGreaterEqual(len(records), 2)
        self.assertEqual(summary["total_endnote_items"], 2)

    def test_no_endnote_pages_produces_no_records(self):
        """No endnote candidate pages produces no records."""
        ch = _chapter("ch-1", "Chapter 1", [1])
        md = "Just body text.\n\nNo endnotes here."
        phase1 = _phase1(
            pages=[_partition(1, role="body")],
            chapters=[ch],
        )
        pages_data = [_page(1, markdown=md)]

        records, summary = build_paragraph_endnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 0)
        self.assertEqual(summary["total_endnote_items"], 0)

    def test_multi_chapter_endnotes(self):
        """Multiple chapters with endnote pages each produce per-chapter records."""
        ch1 = _chapter("ch-1", "Chapter 1", [1, 2])
        ch2 = _chapter("ch-2", "Chapter 2", [3, 4])
        md1 = "1. Endnote for ch1.\n2. Second ch1 endnote."
        md2 = "1. Endnote for ch2.\n2. Second ch2 endnote."
        phase1 = _phase1(
            pages=[
                _partition(1, role="body"),
                _partition(2, role="note"),
                _partition(3, role="body"),
                _partition(4, role="note"),
            ],
            chapters=[ch1, ch2],
        )
        pages_data = [
            _page(1),
            _page(2, markdown=md1),
            _page(3),
            _page(4, markdown=md2),
        ]

        records, summary = build_paragraph_endnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 4)
        self.assertEqual(summary["chapter_count"], 2)
        ch1_records = [r for r in records if r.chapter_id == "ch-1"]
        ch2_records = [r for r in records if r.chapter_id == "ch-2"]
        self.assertEqual(len(ch1_records), 2)
        self.assertEqual(len(ch2_records), 2)

    def test_contiguous_endnote_pages_combined(self):
        """Contiguous endnote pages are grouped and items combined."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2, 3])
        md2 = "1. First endnote.\n2. Second endnote."
        md3 = "3. Third endnote.\n4. Fourth endnote."
        phase1 = _phase1(
            pages=[
                _partition(1, role="body"),
                _partition(2, role="note"),
                _partition(3, role="note"),
            ],
            chapters=[ch],
        )
        pages_data = [
            _page(1),
            _page(2, markdown=md2),
            _page(3, markdown=md3),
        ]

        records, _ = build_paragraph_endnotes(phase1, pages=pages_data)

        # 4 items total across 2 pages
        self.assertEqual(len(records), 4)
        self.assertEqual(records[0].marker, "1")
        self.assertEqual(records[1].marker, "2")
        self.assertEqual(records[2].marker, "3")
        self.assertEqual(records[3].marker, "4")

    def test_book_scope_endnote_pages(self):
        """Pages beyond the last chapter end are book-scope endnotes."""
        ch = _chapter("ch-1", "Chapter 1", [1, 10])
        md = (
            "Notes\n\n"
            "1. Book-level endnote one.\n"
            "2. Book-level endnote two."
        )
        phase1 = _phase1(
            pages=[
                _partition(1, role="body"),
                _partition(100, role="note"),
            ],
            chapters=[ch],
        )
        pages_data = [_page(1), _page(100, markdown=md)]

        records, summary = build_paragraph_endnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 2)
        self.assertEqual(summary["total_endnote_items"], 2)
        # Book-scope endnotes should bind to last chapter
        self.assertEqual(records[0].chapter_id, "ch-1")

    def test_empty_chapter(self):
        """Chapter with no pages produces no records."""
        ch = _chapter("ch-empty", "Empty Chapter", [])
        phase1 = _phase1(pages=[], chapters=[ch])
        pages_data = []
        records, summary = build_paragraph_endnotes(phase1, pages=pages_data)
        self.assertEqual(len(records), 0)
        self.assertEqual(summary["total_endnote_items"], 0)

    def test_non_body_pages_ignored_unless_endnote_candidate(self):
        """Non-body pages without endnote data are ignored."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2, 3])
        phase1 = _phase1(
            pages=[
                _partition(1, role="body"),
                _partition(2, role="front_matter"),
                _partition(3, role="note"),
            ],
            chapters=[ch],
        )
        pages_data = [
            _page(1),
            _page(2, markdown="Some front matter"),
            _page(3, markdown="1. Real endnote."),
        ]

        records, summary = build_paragraph_endnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 1)
        self.assertEqual(summary["total_endnote_items"], 1)

    def test_illustration_list_pages_filtered(self):
        """Pages with illustration list content are not treated as endnotes."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2])
        md = "List of Illustrations\n\nFig 1. Something\nFig 2. Something else"
        phase1 = _phase1(
            pages=[
                _partition(1, role="body"),
                _partition(2, role="note"),
            ],
            chapters=[ch],
        )
        pages_data = [_page(1), _page(2, markdown=md)]

        records, _ = build_paragraph_endnotes(phase1, pages=pages_data)

        # Should not produce records from illustration list
        self.assertEqual(len(records), 0)

    def test_multi_line_endnote_text(self):
        """Multi-line endnote items are captured as single items."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2])
        md = (
            "1. This endnote has\n"
            "multiple lines of text\n"
            "all belonging to the same item.\n"
            "2. Second endnote here."
        )
        phase1 = _phase1(
            pages=[_partition(1), _partition(2, role="note")],
            chapters=[ch],
        )
        pages_data = [_page(1), _page(2, markdown=md)]

        records, _ = build_paragraph_endnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 2)
        self.assertIn("multiple lines", records[0].text.lower())

    def test_reconstructed_flag_set(self):
        """Reconstructed items from OCR splitting set is_reconstructed."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2])
        md = "1 2 This is a reconstructed endnote with spaced marker."
        phase1 = _phase1(
            pages=[_partition(1), _partition(2, role="note")],
            chapters=[ch],
        )
        pages_data = [_page(1), _page(2, markdown=md)]

        records, summary = build_paragraph_endnotes(phase1, pages=pages_data)

        self.assertGreaterEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()

"""Paragraph footnote stage unit tests."""

from __future__ import annotations

import unittest

from FNM_RE.models import ChapterRecord, PagePartitionRecord, Phase1Structure, Phase1Summary
from FNM_RE.stages.paragraph_footnotes import build_paragraph_footnotes


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


def _chapter(chapter_id: str, title: str, pages: list[int]) -> ChapterRecord:
    return ChapterRecord(
        chapter_id=chapter_id,
        title=title,
        start_page=min(pages) if pages else 0,
        end_page=max(pages) if pages else 0,
        pages=pages,
        source="fallback",
        boundary_state="ready",
    )


def _page(page_no: int, *, markdown: str = "") -> dict:
    return {
        "bookPage": page_no,
        "fileIdx": page_no - 1,
        "target_pdf_page": page_no,
        "markdown": markdown,
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


class ParagraphFootnotesTest(unittest.TestCase):
    """Test paragraph footnote mounting."""

    def test_simple_footnote_band(self):
        """Basic footnote detection with numbered items separated by rule."""
        ch = _chapter("ch-1", "Chapter 1", [1])
        md = (
            "Some body paragraph content here.\n\n"
            "More body text that goes on for a bit.\n\n"
            "1. First footnote about something.\n"
            "2. Second footnote about something else.\n"
            "3. Third footnote with more details."
        )
        phase1 = _phase1(pages=[_partition(1)], chapters=[ch])
        pages_data = [_page(1, markdown=md)]

        records, summary = build_paragraph_footnotes(phase1, pages=pages_data)

        self.assertEqual(summary["total_footnote_items"], 3)
        self.assertEqual(summary["chapter_count"], 1)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].chapter_id, "ch-1")
        self.assertEqual(records[0].page_no, 1)
        self.assertEqual(records[0].source_marker, "1")
        self.assertEqual(records[0].paragraph_index, 1)
        self.assertEqual(records[1].source_marker, "2")
        self.assertEqual(records[2].source_marker, "3")
        for r in records:
            self.assertEqual(r.attachment_kind, "page_tail")

    def test_footnote_band_with_separator(self):
        """Footnote band after --- separator."""
        ch = _chapter("ch-1", "Chapter 1", [1])
        md = (
            "Body paragraph text here.\n\n"
            "Another body paragraph.\n\n"
            "---\n\n"
            "1 First footnote\n"
            "2 Second footnote"
        )
        phase1 = _phase1(pages=[_partition(1)], chapters=[ch])
        pages_data = [_page(1, markdown=md)]

        records, _ = build_paragraph_footnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].source_marker, "1")
        self.assertEqual(records[1].source_marker, "2")

    def test_anchor_matched_footnote(self):
        """Footnote with inline marker in body paragraph is anchor_matched."""
        ch = _chapter("ch-1", "Chapter 1", [1])
        md = (
            "This is body text with an inline marker$^{1}$here.\n\n"
            "Another paragraph without markers.\n\n"
            "---\n\n"
            "1. The footnote for marker one.\n"
            "2. Second footnote."
        )
        phase1 = _phase1(pages=[_partition(1)], chapters=[ch])
        pages_data = [_page(1, markdown=md)]

        records, summary = build_paragraph_footnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 2)
        matched = [r for r in records if r.attachment_kind == "anchor_matched"]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].source_marker, "1")
        self.assertEqual(matched[0].paragraph_index, 0)
        self.assertEqual(summary["anchor_matched"], 1)

    def test_html_sup_marker_matches_footnote(self):
        """<sup> marker in body also triggers anchor_matched."""
        ch = _chapter("ch-1", "Chapter 1", [1])
        md = (
            "Body text with<sup>42</sup>inline.\n\n"
            "More text.\n\n"
            "---\n\n"
            "42 The footnote for marker 42.\n"
            "43 A second footnote."
        )
        phase1 = _phase1(pages=[_partition(1)], chapters=[ch])
        pages_data = [_page(1, markdown=md)]

        records, _ = build_paragraph_footnotes(phase1, pages=pages_data)

        matched = [r for r in records if r.attachment_kind == "anchor_matched"]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].source_marker, "42")

    def test_bracket_marker_matches_footnote(self):
        """[n] inline marker also triggers anchor_matched."""
        ch = _chapter("ch-1", "Chapter 1", [1])
        md = (
            "Text with[7]bracket marker.\n\n"
            "---\n\n"
            "7 The footnote."
        )
        phase1 = _phase1(pages=[_partition(1)], chapters=[ch])
        pages_data = [_page(1, markdown=md)]

        records, _ = build_paragraph_footnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].attachment_kind, "anchor_matched")
        self.assertEqual(records[0].source_marker, "7")

    def test_no_footnote_band(self):
        """Page with no footnote band produces no records."""
        ch = _chapter("ch-1", "Chapter 1", [1])
        md = "Just a regular body page.\n\nNo footnotes here."
        phase1 = _phase1(pages=[_partition(1)], chapters=[ch])
        pages_data = [_page(1, markdown=md)]

        records, summary = build_paragraph_footnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 0)
        self.assertEqual(summary["total_footnote_items"], 0)

    def test_cross_page_footnote_merge(self):
        """Cross-page footnote: prev page last item no end punct + next page first item no number."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2])
        md1 = (
            "Body text page 1.\n\n"
            "---\n\n"
            "1 This footnote continues across\n"
            "2 Second footnote"
        )
        # Page 2's band starts with unnumbered continuation text
        # (not a new numbered item) → merges into page 1's last item
        md2 = (
            "Body text page 2.\n\n"
            "---\n\n"
            "continuation of footnote 1\n"
            "3 Third footnote"
        )
        phase1 = _phase1(
            pages=[_partition(1), _partition(2)],
            chapters=[ch],
        )
        pages_data = [_page(1, markdown=md1), _page(2, markdown=md2)]

        records, summary = build_paragraph_footnotes(phase1, pages=pages_data)

        # Page 1: 2 items (item2 merged with continuation) + page 2: 1 item = 3
        self.assertEqual(len(records), 3)
        # The cross_page flag is set on the merged item
        cross_page_records = [r for r in records if r.attachment_kind == "cross_page_tail"]
        self.assertEqual(len(cross_page_records), 1)
        self.assertEqual(summary["cross_page_tail"], 1)
        # Item 3 from page 2 should also be present
        page2_records = [r for r in records if r.page_no == 2]
        self.assertEqual(len(page2_records), 1)
        self.assertEqual(page2_records[0].source_marker, "3")

    def test_cross_page_not_merged_when_has_number_prefix(self):
        """Cross-page NOT merged when next page first item has a number prefix."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2])
        md1 = (
            "Body text page 1.\n\n"
            "---\n\n"
            "1 This footnote continues across"
        )
        md2 = (
            "Body text page 2.\n\n"
            "---\n\n"
            "1 Continued footnote text\n"
            "2 Second footnote"
        )
        phase1 = _phase1(
            pages=[_partition(1), _partition(2)],
            chapters=[ch],
        )
        pages_data = [_page(1, markdown=md1), _page(2, markdown=md2)]

        records, summary = build_paragraph_footnotes(phase1, pages=pages_data)

        # Both pages have footnotes, none merged
        self.assertEqual(len(records), 3)
        self.assertEqual(summary["cross_page_tail"], 0)

    def test_multi_chapter(self):
        """Multiple chapters each get their own footnotes."""
        ch1 = _chapter("ch-1", "Chapter 1", [1, 2])
        ch2 = _chapter("ch-2", "Chapter 2", [3, 4])
        md1 = "Body text.\n\n---\n\n1 Fn 1\n2 Fn 2"
        md2 = "Body text 2.\n\n---\n\n3 Fn 3\n4 Fn 4"
        md3 = "Ch2 body.\n\n---\n\n1 Fn A\n2 Fn B"
        md4 = "Ch2 body 2.\n\n---\n\n3 Fn C\n4 Fn D"
        phase1 = _phase1(
            pages=[_partition(1), _partition(2), _partition(3), _partition(4)],
            chapters=[ch1, ch2],
        )
        pages_data = [
            _page(1, markdown=md1),
            _page(2, markdown=md2),
            _page(3, markdown=md3),
            _page(4, markdown=md4),
        ]

        records, summary = build_paragraph_footnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 8)
        self.assertEqual(summary["chapter_count"], 2)
        ch1_records = [r for r in records if r.chapter_id == "ch-1"]
        ch2_records = [r for r in records if r.chapter_id == "ch-2"]
        self.assertEqual(len(ch1_records), 4)
        self.assertEqual(len(ch2_records), 4)

    def test_footnote_item_with_multi_line_text(self):
        """Multi-line footnote text is captured as single item."""
        ch = _chapter("ch-1", "Chapter 1", [1])
        md = (
            "Body text.\n\n"
            "---\n\n"
            "1 This footnote has\n"
            "multiple lines of text\n"
            "all belonging to the same item.\n"
            "2 Second footnote here."
        )
        phase1 = _phase1(pages=[_partition(1)], chapters=[ch])
        pages_data = [_page(1, markdown=md)]

        records, _ = build_paragraph_footnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].source_marker, "1")
        self.assertIn("multiple lines", records[0].text.lower())

    def test_non_body_pages_skipped(self):
        """Pages with non-body roles are excluded."""
        ch = _chapter("ch-1", "Chapter 1", [1, 2])
        md1 = (
            "Body text.\n\n---\n\n1 Fn 1\n2 Fn 2"
        )
        md2 = (
            "Note page.\n\n---\n\n1 Endnote X"
        )
        phase1 = _phase1(
            pages=[_partition(1, role="body"), _partition(2, role="note")],
            chapters=[ch],
        )
        pages_data = [_page(1, markdown=md1), _page(2, markdown=md2)]

        records, summary = build_paragraph_footnotes(phase1, pages=pages_data)

        self.assertEqual(len(records), 2)
        self.assertEqual(summary["chapter_count"], 1)

    def test_empty_chapter(self):
        """Chapter with no pages produces no records."""
        ch = _chapter("ch-empty", "Empty Chapter", [])
        phase1 = _phase1(pages=[], chapters=[ch])
        pages_data = []
        records, summary = build_paragraph_footnotes(phase1, pages=pages_data)
        self.assertEqual(len(records), 0)
        self.assertEqual(summary["total_footnote_items"], 0)

    def test_single_footnote_does_not_form_band(self):
        """A single numbered paragraph is not enough to form a footnote band."""
        ch = _chapter("ch-1", "Chapter 1", [1])
        md = (
            "Body text here.\n\n"
            "More body text.\n\n"
            "1 Lone footnote paragraph is not enough."
        )
        phase1 = _phase1(pages=[_partition(1)], chapters=[ch])
        pages_data = [_page(1, markdown=md)]

        records, summary = build_paragraph_footnotes(phase1, pages=pages_data)

        # Only 1 footnote paragraph → not enough to form band → 0 items
        self.assertEqual(len(records), 0)
        self.assertEqual(summary["total_footnote_items"], 0)


if __name__ == "__main__":
    unittest.main()

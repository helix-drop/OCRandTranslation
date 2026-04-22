from __future__ import annotations

import unittest

from FNM_RE.app.pipeline import build_phase1_structure, build_phase2_structure


def _make_page(
    page_no: int,
    *,
    markdown: str = "",
    block_label: str = "",
    block_text: str = "",
    footnotes: str = "",
) -> dict:
    parsing_blocks: list[dict] = []
    if block_text:
        parsing_blocks.append(
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
            "parsing_res_list": parsing_blocks,
        },
    }


def _note_overrides(*page_nos: int) -> dict[str, dict]:
    return {str(page_no): {"page_role": "note"} for page_no in page_nos}


def _page_signature(phase1) -> tuple:
    return tuple((row.page_no, row.page_role, row.reason) for row in phase1.pages)


def _chapter_signature(phase1) -> tuple:
    return tuple((row.chapter_id, row.title, row.start_page, row.end_page) for row in phase1.chapters)


def _heading_signature(phase1) -> tuple:
    return tuple(
        (row.page_no, row.text, row.source, row.suppressed_as_chapter, row.reject_reason)
        for row in phase1.heading_candidates
    )


def _section_signature(phase1) -> tuple:
    return tuple((row.chapter_id, row.title, row.page_no) for row in phase1.section_heads)


class FnmRePhase2Test(unittest.TestCase):
    def test_footnote_band_chapter_wont_build_chapter_endnote_region(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody paragraph.",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="1. Page footnote one.",
            ),
            _make_page(2, markdown="# Notes\n1. Endnote candidate."),
            _make_page(
                3,
                markdown="# Chapter Two\nBody paragraph.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]
        structure = build_phase2_structure(pages, page_overrides=_note_overrides(2))
        foot_regions = [
            region
            for region in structure.note_regions
            if region.note_kind == "footnote" and region.chapter_id == structure.chapters[0].chapter_id
        ]
        chapter_end_regions = [
            region
            for region in structure.note_regions
            if region.note_kind == "endnote"
            and region.scope == "chapter"
            and region.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertTrue(foot_regions)
        self.assertFalse(chapter_end_regions)

    def test_notes_heading_and_continuation_merge_into_single_endnote_region(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody page.",
                block_label="doc_title",
                block_text="Chapter One",
            ),
            _make_page(2, markdown="# Notes\n1. First endnote."),
            _make_page(3, markdown="2. Continued endnote list."),
            _make_page(
                4,
                markdown="# Chapter Two\nBody page.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]
        structure = build_phase2_structure(pages, page_overrides=_note_overrides(2, 3))
        end_regions = [region for region in structure.note_regions if region.note_kind == "endnote" and region.scope == "chapter"]
        self.assertEqual(len(end_regions), 1)
        self.assertEqual(end_regions[0].pages, [2, 3])

    def test_adjacent_book_regions_merge_and_chapter_regions_do_not_cross_boundary(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Notes\n1. Chapter one note."),
            _make_page(3, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
            _make_page(4, markdown="# Notes\n1. Chapter two note."),
            _make_page(5, markdown="# Chapter Three\nBody.", block_label="doc_title", block_text="Chapter Three"),
            _make_page(6, markdown="# Notes\n1. Book note page one."),
            _make_page(7, markdown="2. Book note page two."),
        ]
        structure = build_phase2_structure(pages, page_overrides=_note_overrides(2, 4, 6, 7))
        chapter_regions = [region for region in structure.note_regions if region.note_kind == "endnote" and region.scope == "chapter"]
        book_regions = [region for region in structure.note_regions if region.note_kind == "endnote" and region.scope == "book"]
        self.assertEqual(len(chapter_regions), 2)
        self.assertEqual({region.chapter_id for region in chapter_regions}, {structure.chapters[0].chapter_id, structure.chapters[1].chapter_id})
        self.assertEqual(len(book_regions), 1)
        self.assertEqual(book_regions[0].pages, [6, 7])

    def test_post_body_note_page_promoted_to_book_scope(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
            _make_page(3, markdown="# Notes\n1. Post-body note."),
        ]
        structure = build_phase2_structure(pages, page_overrides=_note_overrides(3))
        book_regions = [region for region in structure.note_regions if region.note_kind == "endnote" and region.scope == "book"]
        self.assertEqual(len(book_regions), 1)
        self.assertEqual(book_regions[0].page_start, 3)

    def test_book_scope_region_split_by_heading_and_rebind(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
            _make_page(3, markdown="# Chapter One\n1. Note for chapter one."),
            _make_page(4, markdown="# Chapter Two\n2. Note for chapter two."),
        ]
        structure = build_phase2_structure(pages, page_overrides=_note_overrides(3, 4))
        split_regions = [region for region in structure.note_regions if region.note_kind == "endnote" and region.scope == "book"]
        self.assertEqual(len(split_regions), 2)
        self.assertEqual({region.chapter_id for region in split_regions}, {structure.chapters[0].chapter_id, structure.chapters[1].chapter_id})
        self.assertGreaterEqual(structure.summary.note_region_summary.get("split_region_count", 0), 1)

    def test_book_scope_region_split_by_endnote_section_titles(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
            _make_page(3, markdown="Notes\nChapter One\n1. Note for chapter one."),
            _make_page(4, markdown="Notes\nChapter Two\n1. Note for chapter two."),
        ]
        structure = build_phase2_structure(pages, page_overrides=_note_overrides(3, 4))
        split_regions = [region for region in structure.note_regions if region.note_kind == "endnote" and region.scope == "book"]
        self.assertEqual(len(split_regions), 2)
        self.assertEqual(
            {region.chapter_id for region in split_regions},
            {structure.chapters[0].chapter_id, structure.chapters[1].chapter_id},
        )
        self.assertGreaterEqual(structure.summary.note_region_summary.get("endnote_explorer_split_count", 0), 1)

    def test_visual_toc_hints_split_book_scope_region_by_numbered_subentries(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
            _make_page(3, markdown="# Notes\n1. First note."),
            _make_page(4, markdown="2. Second note."),
        ]
        structure = build_phase2_structure(
            pages,
            page_overrides=_note_overrides(3, 4),
            toc_items=[
                {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
                {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
            ],
            visual_toc_bundle={
                "endnotes_summary": {
                    "present": True,
                    "container_title": "Notes",
                    "container_printed_page": 3,
                    "container_visual_order": 5,
                    "has_chapter_keyed_subentries_in_toc": True,
                    "subentry_pattern": "numbered",
                },
                "items": [
                    {"title": "Notes", "printed_page": 3, "visual_order": 5, "role_hint": "endnotes", "parent_title": ""},
                    {
                        "title": "1. Chapter One",
                        "printed_page": 3,
                        "visual_order": 6,
                        "role_hint": "section",
                        "parent_title": "Notes",
                    },
                    {
                        "title": "2. Chapter Two",
                        "printed_page": 4,
                        "visual_order": 7,
                        "role_hint": "section",
                        "parent_title": "Notes",
                    },
                ],
            },
        )
        split_regions = [region for region in structure.note_regions if region.note_kind == "endnote" and region.scope == "book"]
        self.assertEqual(len(split_regions), 2)
        self.assertEqual(
            {region.chapter_id for region in split_regions},
            {structure.chapters[0].chapter_id, structure.chapters[1].chapter_id},
        )
        self.assertTrue(structure.summary.note_region_summary.get("endnote_explorer_toc_hint_present"))
        self.assertEqual(int(structure.summary.note_region_summary.get("endnote_explorer_toc_subentry_count") or 0), 2)

    def test_visual_toc_hints_support_named_subentries(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
            _make_page(3, markdown="# Notes\n1. First note."),
            _make_page(4, markdown="2. Second note."),
        ]
        structure = build_phase2_structure(
            pages,
            page_overrides=_note_overrides(3, 4),
            toc_items=[
                {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
                {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
            ],
            visual_toc_bundle={
                "endnotes_summary": {
                    "present": True,
                    "container_title": "Notes",
                    "container_printed_page": 3,
                    "container_visual_order": 5,
                    "has_chapter_keyed_subentries_in_toc": True,
                    "subentry_pattern": "named",
                },
                "items": [
                    {"title": "Notes", "printed_page": 3, "visual_order": 5, "role_hint": "endnotes", "parent_title": ""},
                    {
                        "title": "Notes to Chapter 1",
                        "printed_page": 3,
                        "visual_order": 6,
                        "role_hint": "section",
                        "parent_title": "Notes",
                    },
                    {
                        "title": "Notes to Chapter 2",
                        "printed_page": 4,
                        "visual_order": 7,
                        "role_hint": "section",
                        "parent_title": "Notes",
                    },
                ],
            },
        )
        split_regions = [region for region in structure.note_regions if region.note_kind == "endnote" and region.scope == "book"]
        self.assertEqual(len(split_regions), 2)
        chapter_ids = {row.title: row.chapter_id for row in structure.chapters}
        self.assertEqual(
            {region.chapter_id for region in split_regions},
            {chapter_ids["Chapter One"], chapter_ids["Chapter Two"]},
        )

    def test_ocr_split_marker_can_be_reconstructed(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Notes\n1 2 Split OCR marker note text."),
            _make_page(3, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
        ]
        structure = build_phase2_structure(pages, page_overrides=_note_overrides(2))
        reconstructed_items = [item for item in structure.note_items if item.is_reconstructed]
        self.assertTrue(reconstructed_items)
        self.assertEqual(reconstructed_items[0].marker, "12")

    def test_page_text_fallback_recovers_items_and_missing_region_enters_review(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Notes"),
            _make_page(3, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
            _make_page(4, markdown="# Notes"),
            _make_page(5, markdown="# Chapter Three\nBody.", block_label="doc_title", block_text="Chapter Three"),
        ]
        structure = build_phase2_structure(
            pages,
            page_overrides=_note_overrides(2, 4),
            page_text_map={2: "1. Fallback recovered item."},
        )
        self.assertGreaterEqual(structure.summary.note_item_summary.get("pdf_text_fallback_count", 0), 1)
        self.assertTrue(structure.summary.note_item_summary.get("empty_region_ids"))
        review_regions = [region for region in structure.note_regions if region.review_required]
        self.assertTrue(review_regions)

    def test_region_source_marker_alignment_is_written_to_summary(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="Intro\n# Notes\n2. Source marker two."),
            _make_page(3, markdown="3. Continuation line."),
            _make_page(4, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
        ]
        structure = build_phase2_structure(
            pages,
            page_overrides=_note_overrides(2, 3),
            page_text_map={2: "# Notes\n1. Override marker one."},
        )
        failures = list(structure.summary.note_item_summary.get("marker_alignment_failures") or [])
        self.assertTrue(failures)

    def test_embedded_page_footnote_text_builds_region_and_item(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [5].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes=(
                    "spill spill spill spill spill spill spill spill spill spill "
                    "5 What I here call brain-self differentiation remains recoverable."
                ),
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages)

        foot_regions = [
            region
            for region in structure.note_regions
            if region.note_kind == "footnote" and region.chapter_id == structure.chapters[0].chapter_id
        ]
        chapter_one_items = [
            item
            for item in structure.note_items
            if item.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertTrue(foot_regions)
        self.assertEqual([item.marker for item in chapter_one_items], ["5"])

    def test_trailing_marker_in_page_footnotes_creates_intermediate_item(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [25] [26] [27].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="25. Prior note ends here. 26.\nIbid., p. 414.\n27. Next note.",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages)

        chapter_one_items = [
            item
            for item in structure.note_items
            if item.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertEqual([item.marker for item in chapter_one_items], ["25", "26", "27"])

    def test_followup_marker_inside_same_footnotes_text_creates_next_item(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [46] [47].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes=(
                    "46. Ibid., p. 197. , 47. Jean WAHL, Vers le concret. "
                    "Études d'histoire de la philosophie contemporaine, Paris, Vrin, 1932."
                ),
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages)

        chapter_one_items = [
            item
            for item in structure.note_items
            if item.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertEqual([item.marker for item in chapter_one_items], ["46", "47"])

    def test_multiple_followup_markers_inside_same_footnotes_line_are_split(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [106] [107] [108].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes=(
                    "106. Sauf dans le cas de Kant und das Problem der Metaphysik, "
                    "107. Martin HEIDEGGER, De l'essence de la vérité, trad. citée. "
                    "Verbergung 108. Qui n'évite pas toujours le contresens."
                ),
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages)

        chapter_one_items = [
            item
            for item in structure.note_items
            if item.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertEqual([item.marker for item in chapter_one_items], ["106", "107", "108"])

    def test_leading_noise_before_footnote_marker_is_recovered(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [104].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="i 104. Voir ibid., pp. 94-95.",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages)

        chapter_one_items = [
            item
            for item in structure.note_items
            if item.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertEqual([item.marker for item in chapter_one_items], ["104"])

    def test_semicolon_and_leading_punctuation_markers_are_recovered(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [38] [39] [16] [17].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes=(
                    ".38. First recovered note.\n"
                    "39. Second recovered note.\n"
                    "16; Ibid., p. 42.\n"
                    "'17. Next recovered note."
                ),
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages)

        chapter_one_items = [
            item
            for item in structure.note_items
            if item.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertEqual([item.marker for item in chapter_one_items], ["38", "39", "16", "17"])

    def test_gap_lines_between_explicit_markers_are_synthesized_as_missing_notes(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [13] [14] [15].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes=(
                    "13. Ibid., p. 134.\n"
                    "ad^ ybid^\\  ^ ace]acf^\n"
                    "15. J. Goldstein, Consoler et classifier, op. cit., p. 220."
                ),
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages)

        chapter_one_items = [
            item
            for item in structure.note_items
            if item.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertEqual([item.marker for item in chapter_one_items], ["13", "14", "15"])
        self.assertTrue(chapter_one_items[1].is_reconstructed)
        self.assertIn("ybid", chapter_one_items[1].text)

    def test_trailing_garbled_line_after_last_marker_is_synthesized(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [57] [58].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes=(
                    "57. Ibid., p. 299.\n"
                    "eh^ ybid^\\  ^ bic]bid^"
                ),
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages)

        chapter_one_items = [
            item
            for item in structure.note_items
            if item.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertEqual([item.marker for item in chapter_one_items], ["57", "58"])
        self.assertTrue(chapter_one_items[1].is_reconstructed)

    def test_leading_garbled_line_before_next_marker_uses_last_page_marker_gap(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [91].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="91. Prior note.",
            ),
            _make_page(
                2,
                markdown="Continuation body [92] [93].",
                footnotes=(
                    "ib^ ybid^\\  ^ eba]ebb^\n"
                    "93. Ibid., p. 523."
                ),
            ),
            _make_page(
                3,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages)

        chapter_one_items = [
            item
            for item in structure.note_items
            if item.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertEqual([item.marker for item in chapter_one_items], ["91", "92", "93"])
        self.assertTrue(chapter_one_items[1].is_reconstructed)

    def test_footnotes_text_is_preferred_over_partial_fn_blocks(self):
        page_one = _make_page(
            1,
            markdown="# Chapter One\nBody [25] [26] [27].",
            block_label="doc_title",
            block_text="Chapter One",
            footnotes="25. Prior note ends here. 26.\nIbid., p. 414.\n27. Next note.",
        )
        page_one["fnBlocks"] = [
            {
                "text": "25. Prior note ends here.\n27. Next note.",
                "bbox": [10, 900, 100, 970],
            }
        ]
        pages = [
            page_one,
            _make_page(
                2,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages)

        chapter_one_items = [
            item
            for item in structure.note_items
            if item.chapter_id == structure.chapters[0].chapter_id
        ]
        self.assertEqual([item.marker for item in chapter_one_items], ["25", "26", "27"])

    def test_illustration_list_pages_do_not_form_endnote_regions(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody.",
                block_label="doc_title",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown=(
                    "# Liste des illustrations\n"
                    "1. Gravure. Musée Carnavalet. © Musée Carnavalet\n"
                    "2. Eau-forte. Bibliothèque nationale."
                ),
            ),
            _make_page(
                3,
                markdown=(
                    "10. Huile sur toile. Musée du Louvre. © RMN\n"
                    "11. Lithographie. Bibliothèque nationale de France."
                ),
            ),
            _make_page(
                4,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(pages, page_overrides=_note_overrides(2, 3))

        illustration_pages = {2, 3}
        endnote_regions = [
            region
            for region in structure.note_regions
            if region.note_kind == "endnote" and any(page in illustration_pages for page in region.pages)
        ]
        illustration_items = [
            item
            for item in structure.note_items
            if int(item.page_no) in illustration_pages
        ]
        self.assertFalse(endnote_regions)
        self.assertFalse(illustration_items)

    def test_bibliography_remarks_pages_do_not_form_endnote_regions(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody.",
                block_label="doc_title",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown=(
                    "# Bibliography\n\n"
                    "Des précisions préalables s'imposent quant à l'organisation de cette bibliographie."
                ),
            ),
            _make_page(
                3,
                markdown=(
                    "2. Signalons une traduction sans date, par Gérard Granel, texte bilingue, Paris, Belin, 2001.\n"
                    "3. La traduction du cours sur le Sophiste doit paraître en 2001 chez Gallimard.\n"
                    "4. « Le travail de recherche de Wilhelm Dilthey », trad. J.-C. Gens, Paris, Vrin, 2003."
                ),
            ),
            _make_page(
                4,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase2_structure(
            pages,
            toc_items=[
                {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
                {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 4},
            ],
        )

        bibliography_pages = {2, 3}
        endnote_regions = [
            region
            for region in structure.note_regions
            if region.note_kind == "endnote" and any(page in bibliography_pages for page in region.pages)
        ]
        bibliography_items = [
            item
            for item in structure.note_items
            if int(item.page_no) in bibliography_pages
        ]
        self.assertFalse(endnote_regions)
        self.assertFalse(bibliography_items)

    def test_chapter_note_modes_cover_three_primary_states(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody.",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="1. Footnote content.",
            ),
            _make_page(2, markdown="Body continuation."),
            _make_page(3, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
            _make_page(4, markdown="# Notes\n1. Chapter two endnote."),
            _make_page(5, markdown="# Chapter Three\nBody.", block_label="doc_title", block_text="Chapter Three"),
            _make_page(6, markdown="# Notes\n1. Book note for tail."),
        ]
        structure = build_phase2_structure(pages, page_overrides=_note_overrides(4, 6))
        mode_by_chapter = {row.chapter_id: row.note_mode for row in structure.chapter_note_modes}
        self.assertEqual(mode_by_chapter.get(structure.chapters[0].chapter_id), "footnote_primary")
        self.assertEqual(mode_by_chapter.get(structure.chapters[1].chapter_id), "chapter_endnote_primary")
        self.assertEqual(mode_by_chapter.get(structure.chapters[2].chapter_id), "book_endnote_bound")

    def test_phase2_keeps_phase1_fields_unchanged(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Notes\n1. Endnote."),
            _make_page(3, markdown="# Chapter Two\nBody.", block_label="doc_title", block_text="Chapter Two"),
        ]
        overrides = _note_overrides(2)
        phase1 = build_phase1_structure(pages, page_overrides=overrides)
        phase2 = build_phase2_structure(pages, page_overrides=overrides)
        self.assertEqual(_page_signature(phase1), _page_signature(phase2))
        self.assertEqual(_chapter_signature(phase1), _chapter_signature(phase2))
        self.assertEqual(_heading_signature(phase1), _heading_signature(phase2))
        self.assertEqual(_section_signature(phase1), _section_signature(phase2))
        self.assertTrue(phase2.note_regions)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from FNM_RE.models import BodyAnchorRecord, NoteItemRecord, NoteLinkRecord, NoteRegionRecord
from FNM_RE.modules.book_note_type import build_book_note_profile
from FNM_RE.modules.chapter_split import build_chapter_layers
from FNM_RE.modules.note_linking import (
    _apply_link_overrides,
    _chapter_contracts,
    _repair_explicit_footnote_anchor_ocr_variants,
    build_note_link_table,
)
from FNM_RE.modules.toc_structure import build_toc_structure
from FNM_RE.modules.types import (
    BodyPageLayer,
    ChapterLayer,
    ChapterLayers,
    LayerNoteItem,
    LayerNoteRegion,
)
from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc, load_pages


def _make_page(page_no: int, *, markdown: str, footnotes: str = "", block_text: str = "") -> dict:
    blocks = []
    if block_text:
        blocks.append(
            {
                "block_label": "doc_title",
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
        "prunedResult": {"height": 1200, "width": 900, "parsing_res_list": blocks},
    }


class FnmReModule4LinkingTest(unittest.TestCase):
    def _build_biopolitics_inputs(self):
        pages = load_pages("Biopolitics")
        toc = build_toc_structure(pages, load_auto_visual_toc("Biopolitics")).data
        profile = build_book_note_profile(toc, pages).data
        layers = build_chapter_layers(toc, profile, pages).data
        return pages, layers

    def _build_note_link_table(self, pages: list[dict], toc_items: list[dict]):
        toc = build_toc_structure(pages, toc_items).data
        profile = build_book_note_profile(toc, pages).data
        layers = build_chapter_layers(toc, profile, pages).data
        return build_note_link_table(layers, pages)

    def _single_chapter_layers(
        self,
        *,
        note_items: list[LayerNoteItem],
        note_regions: list[LayerNoteRegion],
        note_mode: str = "book_endnote_bound",
        book_type: str = "endnote_only",
    ) -> ChapterLayers:
        chapter = ChapterLayer(
            chapter_id="ch-1",
            title="Chapter One",
            body_pages=[
                BodyPageLayer(
                    page_no=1,
                    text="# Chapter One\nBody [1].",
                    split_reason="body_page",
                    source_role="body",
                )
            ],
            endnote_items=list(note_items),
            endnote_regions=list(note_regions),
            policy_applied={"note_mode": note_mode, "book_type": book_type},
        )
        return ChapterLayers(
            chapters=[chapter],
            regions=list(note_regions),
            note_items=list(note_items),
            region_summary={},
            item_summary={},
        )

    def test_biopolitics_main_path_hard_gates_true(self):
        pages, layers = self._build_biopolitics_inputs()
        result = build_note_link_table(layers, pages)
        self.assertTrue(all(result.gate_report.hard.values()))
        self.assertEqual(dict(result.evidence.get("endnote_only_no_orphan_anchor") or {}).get("status"), "not_applicable")
        self.assertFalse(result.gate_report.soft["link.footnote_orphan_anchor_warn"])

    def test_year_like_marker_is_filtered_from_anchors(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nPolicy year [2020] should not link. Real marker [1] should link.",
                block_text="Chapter One",
            ),
            _make_page(2, markdown="## Notes\n1. Endnote one."),
            _make_page(3, markdown="# Chapter Two\nBody paragraph.", block_text="Chapter Two"),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 3},
        ]
        result = self._build_note_link_table(pages, toc_items)
        markers = {row.normalized_marker for row in result.data.anchors}
        self.assertIn("1", markers)
        self.assertNotIn("2020", markers)

    def test_note_pages_do_not_emit_body_anchors(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody marker [1].",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown="## Notes\n1. Note with inline marker [99] only in notes page.",
            ),
            _make_page(
                3,
                markdown="# Chapter Two\nBody paragraph.",
                block_text="Chapter Two",
            ),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 3},
        ]
        toc = build_toc_structure(pages, toc_items).data
        profile = build_book_note_profile(toc, pages).data
        layers = build_chapter_layers(toc, profile, pages).data
        result = build_note_link_table(layers, pages)
        body_pages = {row.page_no for chapter in layers.chapters for row in chapter.body_pages}
        self.assertTrue(all(anchor.page_no in body_pages for anchor in result.data.anchors))

    def test_ignore_override_only_changes_effective_links(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody paragraph.", block_text="Chapter One"),
            _make_page(2, markdown="## Notes\n1. Endnote one."),
            _make_page(3, markdown="# Chapter Two\nBody paragraph.", block_text="Chapter Two"),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 3},
        ]
        toc = build_toc_structure(pages, toc_items).data
        profile = build_book_note_profile(toc, pages).data
        layers = build_chapter_layers(toc, profile, pages).data
        first_result = build_note_link_table(layers, pages)
        target = next(
            row for row in first_result.data.effective_links if row.status in {"orphan_note", "ambiguous"}
        )
        second_result = build_note_link_table(
            layers,
            pages,
            overrides={"link": {target.link_id: {"action": "ignore"}}},
        )
        raw_status = next(row.status for row in second_result.data.links if row.link_id == target.link_id)
        effective_status = next(
            row.status for row in second_result.data.effective_links if row.link_id == target.link_id
        )
        self.assertEqual(raw_status, target.status)
        self.assertEqual(effective_status, "ignored")

    def test_invalid_match_override_is_counted(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody paragraph.", block_text="Chapter One"),
            _make_page(2, markdown="## Notes\n1. Endnote one."),
            _make_page(3, markdown="# Chapter Two\nBody paragraph.", block_text="Chapter Two"),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 3},
        ]
        toc = build_toc_structure(pages, toc_items).data
        profile = build_book_note_profile(toc, pages).data
        layers = build_chapter_layers(toc, profile, pages).data
        first_result = build_note_link_table(layers, pages)
        target = first_result.data.effective_links[0]
        second_result = build_note_link_table(
            layers,
            pages,
            overrides={
                "link": {
                    target.link_id: {
                        "action": "match",
                        "note_item_id": "missing-note-item",
                        "anchor_id": "missing-anchor",
                    }
                }
            },
        )
        self.assertGreater(
            int(dict(second_result.diagnostics.get("override_summary") or {}).get("invalid_override_count") or 0),
            0,
        )

    def test_missing_footnote_anchor_creates_synthetic_warn(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody without marker but has footnote definition below.",
                footnotes="1. Footnote one.",
                block_text="Chapter One",
            ),
            _make_page(2, markdown="# Chapter Two\nBody paragraph.", block_text="Chapter Two"),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]
        result = self._build_note_link_table(pages, toc_items)
        self.assertFalse(result.gate_report.soft["link.synthetic_anchor_warn"])
        self.assertTrue(any(anchor.synthetic for anchor in result.data.anchors))

    def test_owner_chapter_id_routes_endnote_into_correct_chapter_stream(self):
        pages = [_make_page(1, markdown="# Chapter One\nBody [1].", block_text="Chapter One")]
        region = LayerNoteRegion(
            region_id="r-1",
            chapter_id="wrong-chapter",
            owner_chapter_id="ch-1",
            page_start=1,
            page_end=1,
            pages=[1],
            note_kind="endnote",
            scope="book",
            source_scope="book",
            source="manual_rebind",
            bind_method="marker_projection",
            bind_confidence=1.0,
            heading_text="Notes",
            review_required=False,
        )
        item = LayerNoteItem(
            note_item_id="n-1",
            region_id="r-1",
            chapter_id="wrong-chapter",
            owner_chapter_id="ch-1",
            page_no=1,
            marker="1",
            source_marker="1",
            normalized_marker="1",
            synth_marker="",
            projection_mode="book_marker_projected",
            marker_type="numeric",
            text="Note one.",
            source="unit-test",
            is_reconstructed=False,
            review_required=False,
            note_kind="endnote",
        )
        layers = self._single_chapter_layers(note_items=[item], note_regions=[region])
        result = build_note_link_table(layers, pages)
        self.assertTrue(result.gate_report.hard["link.no_orphan_note"])
        matched = [row for row in result.data.effective_links if row.status == "matched" and row.note_kind == "endnote"]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].chapter_id, "ch-1")

    def test_chapter_endnote_first_marker_follows_anchor_order_not_note_page_order(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nOpening argument [1].\n\nLater argument [2].",
                block_text="Chapter One",
            ),
            _make_page(2, markdown="## Notes\n2. Second note."),
            _make_page(3, markdown="1. First note."),
        ]
        region = LayerNoteRegion(
            region_id="r-1",
            chapter_id="ch-1",
            page_start=2,
            page_end=3,
            pages=[2, 3],
            note_kind="endnote",
            scope="chapter",
            source_scope="chapter",
            source="unit-test",
            bind_method="manual",
            bind_confidence=1.0,
            heading_text="Notes",
            review_required=False,
        )
        note_items = [
            LayerNoteItem(
                note_item_id="n-2",
                region_id="r-1",
                chapter_id="ch-1",
                page_no=2,
                marker="2",
                source_marker="2",
                normalized_marker="2",
                synth_marker="",
                projection_mode="native",
                marker_type="numeric",
                text="Second note.",
                source="unit-test",
                is_reconstructed=False,
                review_required=False,
                note_kind="endnote",
            ),
            LayerNoteItem(
                note_item_id="n-1",
                region_id="r-1",
                chapter_id="ch-1",
                page_no=3,
                marker="1",
                source_marker="1",
                normalized_marker="1",
                synth_marker="",
                projection_mode="native",
                marker_type="numeric",
                text="First note.",
                source="unit-test",
                is_reconstructed=False,
                review_required=False,
                note_kind="endnote",
            ),
        ]
        layers = self._single_chapter_layers(
            note_items=note_items,
            note_regions=[region],
            note_mode="chapter_endnote_primary",
            book_type="endnote_only",
        )

        result = build_note_link_table(layers, pages)
        contract_evidence = dict(result.evidence.get("chapter_contracts") or {}).get("ch-1") or {}

        self.assertEqual(
            [row.status for row in result.data.effective_links if row.note_kind == "endnote"],
            ["matched", "matched"],
        )
        self.assertTrue(result.gate_report.hard["link.first_marker_is_one"])
        self.assertEqual(contract_evidence.get("non_ignored_numeric_markers"), [1, 2])

    def test_chapter_endnote_first_marker_ignores_cross_chapter_stale_anchor_order(self):
        region = LayerNoteRegion(
            region_id="r-1",
            chapter_id="ch-1",
            page_start=20,
            page_end=21,
            pages=[20, 21],
            note_kind="endnote",
            scope="chapter",
            source_scope="chapter",
            source="unit-test",
            bind_method="manual",
            bind_confidence=1.0,
            heading_text="Notes",
            review_required=False,
        )
        note_items = [
            LayerNoteItem(
                note_item_id="n-36",
                region_id="r-1",
                chapter_id="ch-1",
                page_no=20,
                marker="36",
                source_marker="36",
                normalized_marker="36",
                synth_marker="",
                projection_mode="native",
                marker_type="numeric",
                text="Stale note.",
                source="unit-test",
                is_reconstructed=False,
                review_required=False,
                note_kind="endnote",
            ),
            LayerNoteItem(
                note_item_id="n-1",
                region_id="r-1",
                chapter_id="ch-1",
                page_no=21,
                marker="1",
                source_marker="1",
                normalized_marker="1",
                synth_marker="",
                projection_mode="native",
                marker_type="numeric",
                text="First real note.",
                source="unit-test",
                is_reconstructed=False,
                review_required=False,
                note_kind="endnote",
            ),
        ]
        layers = self._single_chapter_layers(
            note_items=note_items,
            note_regions=[region],
            note_mode="chapter_endnote_primary",
            book_type="endnote_only",
        )
        anchors = [
            BodyAnchorRecord(
                anchor_id="anchor-stale",
                chapter_id="ch-prev",
                page_no=1,
                paragraph_index=0,
                char_start=10,
                char_end=12,
                source_marker="36",
                normalized_marker="36",
                anchor_kind="endnote",
                certainty=1.0,
                source_text="Old chapter marker 36.",
                source="markdown",
                synthetic=False,
                ocr_repaired_from_marker="",
            ),
            BodyAnchorRecord(
                anchor_id="anchor-real",
                chapter_id="ch-1",
                page_no=10,
                paragraph_index=0,
                char_start=20,
                char_end=22,
                source_marker="1",
                normalized_marker="1",
                anchor_kind="endnote",
                certainty=1.0,
                source_text="Current chapter marker 1.",
                source="markdown",
                synthetic=False,
                ocr_repaired_from_marker="",
            ),
        ]
        links = [
            NoteLinkRecord(
                link_id="link-stale",
                chapter_id="ch-1",
                region_id="r-1",
                note_item_id="n-36",
                anchor_id="anchor-stale",
                status="matched",
                resolver="repair",
                confidence=1.0,
                note_kind="endnote",
                marker="36",
                page_no_start=20,
                page_no_end=20,
            ),
            NoteLinkRecord(
                link_id="link-real",
                chapter_id="ch-1",
                region_id="r-1",
                note_item_id="n-1",
                anchor_id="anchor-real",
                status="matched",
                resolver="repair",
                confidence=1.0,
                note_kind="endnote",
                marker="1",
                page_no_start=21,
                page_no_end=21,
            ),
        ]

        contracts, contract_evidence = _chapter_contracts(
            chapter_layers=layers,
            effective_links=links,
            body_anchors=anchors,
        )

        self.assertTrue(contracts[0].first_marker_is_one)
        self.assertEqual(
            contract_evidence["ch-1"].get("non_ignored_numeric_markers"),
            [1, 36],
        )

    def test_endnote_candidate_priority_prefers_book_projected(self):
        pages = [_make_page(1, markdown="# Chapter One\nBody [1].", block_text="Chapter One")]
        region = LayerNoteRegion(
            region_id="r-1",
            chapter_id="ch-1",
            owner_chapter_id="ch-1",
            page_start=1,
            page_end=1,
            pages=[1],
            note_kind="endnote",
            scope="book",
            source_scope="book",
            source="manual_rebind",
            bind_method="marker_projection",
            bind_confidence=1.0,
            heading_text="Notes",
            review_required=False,
        )
        low = LayerNoteItem(
            note_item_id="a-low",
            region_id="r-1",
            chapter_id="ch-1",
            owner_chapter_id="ch-1",
            page_no=1,
            marker="1",
            source_marker="1",
            normalized_marker="1",
            synth_marker="",
            projection_mode="book_fallback_projected",
            marker_type="numeric",
            text="Low priority",
            source="unit-test",
            is_reconstructed=False,
            review_required=False,
            note_kind="endnote",
        )
        mid = LayerNoteItem(
            note_item_id="b-mid",
            region_id="r-1",
            chapter_id="ch-1",
            owner_chapter_id="ch-1",
            page_no=1,
            marker="1",
            source_marker="1",
            normalized_marker="1",
            synth_marker="",
            projection_mode="book_marker_projected",
            marker_type="numeric",
            text="Mid priority",
            source="unit-test",
            is_reconstructed=False,
            review_required=False,
            note_kind="endnote",
        )
        high = LayerNoteItem(
            note_item_id="c-high",
            region_id="r-1",
            chapter_id="ch-1",
            owner_chapter_id="ch-1",
            page_no=1,
            marker="1",
            source_marker="1",
            normalized_marker="1",
            synth_marker="",
            projection_mode="book_projected",
            marker_type="numeric",
            text="High priority",
            source="unit-test",
            is_reconstructed=False,
            review_required=False,
            note_kind="endnote",
        )
        layers = self._single_chapter_layers(note_items=[low, mid, high], note_regions=[region])
        result = build_note_link_table(layers, pages)
        matched = [row for row in result.data.effective_links if row.status == "matched" and row.note_kind == "endnote"]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].note_item_id, "c-high")

    def test_note_item_override_can_create_missing_note_and_match_existing_anchor(self):
        pages = [_make_page(1, markdown="# Chapter One\nBody text with missing note¹.", block_text="Chapter One")]
        layers = self._single_chapter_layers(note_items=[], note_regions=[])
        result = build_note_link_table(
            layers,
            pages,
            overrides={
                "note_item": {
                    "llm-note-a-1": {
                        "action": "create",
                        "note_item_id": "llm-note-a-1",
                        "chapter_id": "ch-1",
                        "page_no": 1,
                        "marker": "1",
                        "note_kind": "endnote",
                        "text": "Visible note text from screenshot.",
                        "source": "llm",
                    }
                }
            },
        )
        matched = [
            row
            for row in result.data.effective_links
            if row.status == "matched" and row.note_kind == "endnote"
        ]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].note_item_id, "llm-note-a-1")
        self.assertTrue(result.gate_report.hard["link.no_orphan_note"])
        self.assertEqual(
            int(dict(result.diagnostics.get("note_item_override_summary") or {}).get("created_note_item_count") or 0),
            1,
        )

    def test_stage4_summaries_exist_in_link_evidence(self):
        pages, layers = self._build_biopolitics_inputs()
        result = build_note_link_table(layers, pages)
        self.assertIn("chapter_link_contract_summary", result.evidence)
        self.assertIn("book_endnote_stream_summary", result.evidence)

    def test_explicit_anchor_ocr_variant_replaces_synthetic_footnote_match(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody paragraph with OCR-broken anchor [122].",
                footnotes="102. Real footnote content.",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody paragraph.",
                block_text="Chapter Two",
            ),
            _make_page(
                3,
                markdown="# Notes\n1. Chapter two endnote.",
            ),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]

        result = self._build_note_link_table(pages, toc_items)

        matched = [
            row
            for row in result.data.effective_links
            if row.status == "matched" and row.note_kind == "footnote"
        ]
        orphan_anchors = [
            row
            for row in result.data.effective_links
            if row.status == "orphan_anchor" and row.note_kind == "footnote"
        ]

        self.assertEqual(len(matched), 1)
        self.assertFalse(matched[0].anchor_id.startswith("synthetic-footnote-"))
        self.assertFalse(orphan_anchors)

    def test_ambiguous_explicit_anchor_can_absorb_synthetic_followup_match(self):
        pages = [
            _make_page(
                1,
                markdown=(
                    "# Chapter One\n"
                    "Opening claim with anchor [23].\n\n"
                    "Later quotation still carries OCR-broken anchor [23]."
                ),
                footnotes="23. Ibid.\n25. Expression cited later.",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody paragraph.",
                block_text="Chapter Two",
            ),
            _make_page(
                3,
                markdown="# Notes\n1. Chapter two endnote.",
            ),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]

        result = self._build_note_link_table(pages, toc_items)

        ambiguous = [row for row in result.data.effective_links if row.status == "ambiguous"]
        matched = [
            row
            for row in result.data.effective_links
            if row.status == "matched" and row.note_kind == "footnote"
        ]

        self.assertFalse(ambiguous)
        self.assertEqual(len(matched), 2)
        self.assertTrue(all(not row.anchor_id.startswith("synthetic-footnote-") for row in matched))

    def test_same_page_orphan_anchor_from_previous_chapter_replaces_synthetic_footnote(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody paragraph with anchor [1].",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nOpening paragraph still contains anchor [2].",
                block_text="Chapter Two",
                footnotes="2. Real chapter-two footnote.",
            ),
            _make_page(
                3,
                markdown="# Notes\n1. Chapter three endnote.",
            ),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]

        result = self._build_note_link_table(pages, toc_items)

        matched = [
            row
            for row in result.data.effective_links
            if row.status == "matched" and row.note_kind == "footnote" and row.marker == "2"
        ]
        orphan_anchors = [
            row
            for row in result.data.effective_links
            if row.status == "orphan_anchor" and row.marker == "2"
        ]

        self.assertEqual(len(matched), 1)
        self.assertFalse(matched[0].anchor_id.startswith("synthetic-footnote-"))
        self.assertFalse(orphan_anchors)

    def test_cross_chapter_same_page_orphan_anchor_replaces_synthetic_footnote(self):
        anchors = [
            BodyAnchorRecord(
                anchor_id="anchor-prev",
                chapter_id="ch-1",
                page_no=2,
                paragraph_index=0,
                char_start=40,
                char_end=41,
                source_marker="²",
                normalized_marker="2",
                anchor_kind="endnote",
                certainty=1.0,
                source_text="Opening paragraph still contains anchor ².",
                source="markdown:unicode",
                synthetic=False,
                ocr_repaired_from_marker="",
            ),
            BodyAnchorRecord(
                anchor_id="synthetic-footnote-00001",
                chapter_id="ch-2",
                page_no=2,
                paragraph_index=999,
                char_start=0,
                char_end=0,
                source_marker="2",
                normalized_marker="2",
                anchor_kind="footnote",
                certainty=0.4,
                source_text="Real chapter-two footnote.",
                source="synthetic",
                synthetic=True,
                ocr_repaired_from_marker="",
            ),
        ]
        links = [
            NoteLinkRecord(
                link_id="link-match",
                chapter_id="ch-2",
                region_id="rg-2",
                note_item_id="fn-2",
                anchor_id="synthetic-footnote-00001",
                status="matched",
                resolver="fallback",
                confidence=0.4,
                note_kind="footnote",
                marker="2",
                page_no_start=2,
                page_no_end=2,
            ),
            NoteLinkRecord(
                link_id="link-orphan",
                chapter_id="ch-1",
                region_id="",
                note_item_id="",
                anchor_id="anchor-prev",
                status="orphan_anchor",
                resolver="rule",
                confidence=0.0,
                note_kind="endnote",
                marker="2",
                page_no_start=2,
                page_no_end=2,
            ),
        ]
        note_items = [
            NoteItemRecord(
                note_item_id="fn-2",
                region_id="rg-2",
                chapter_id="ch-2",
                page_no=2,
                marker="2",
                marker_type="numeric",
                text="Real chapter-two footnote.",
                source="footnotes",
                source_page_label="p2",
                is_reconstructed=False,
                review_required=False,
            )
        ]

        _repaired_anchors, repaired_links, summary = _repair_explicit_footnote_anchor_ocr_variants(
            anchors=anchors,
            links=links,
            note_items=note_items,
            chapter_mode_by_id={"ch-1": "chapter_endnote_primary", "ch-2": "footnote_primary"},
        )

        matched = next(row for row in repaired_links if row.link_id == "link-match")
        orphan = next(row for row in repaired_links if row.link_id == "link-orphan")
        self.assertEqual(matched.anchor_id, "anchor-prev")
        self.assertEqual(matched.resolver, "repair")
        self.assertEqual(orphan.status, "ignored")
        self.assertEqual(int(summary.get("cross_chapter_same_page_rebind_count") or 0), 1)

    def test_match_override_prefers_payload_identity_over_stale_link_id(self):
        links = [
            NoteLinkRecord(
                link_id="link-stale",
                chapter_id="ch-1",
                region_id="rg-1",
                note_item_id="n-old",
                anchor_id="synthetic-old",
                status="matched",
                resolver="fallback",
                confidence=0.4,
                note_kind="footnote",
                marker="10",
                page_no_start=1,
                page_no_end=1,
            ),
            NoteLinkRecord(
                link_id="link-current",
                chapter_id="ch-1",
                region_id="rg-1",
                note_item_id="n-1",
                anchor_id="anchor-old",
                status="matched",
                resolver="repair",
                confidence=1.0,
                note_kind="footnote",
                marker="70",
                page_no_start=2,
                page_no_end=2,
            ),
            NoteLinkRecord(
                link_id="link-orphan",
                chapter_id="ch-1",
                region_id="",
                note_item_id="",
                anchor_id="anchor-new",
                status="orphan_anchor",
                resolver="rule",
                confidence=0.0,
                note_kind="footnote",
                marker="76",
                page_no_start=2,
                page_no_end=2,
            ),
        ]
        note_items = [
            NoteItemRecord(
                note_item_id="n-old",
                region_id="rg-1",
                chapter_id="ch-1",
                page_no=1,
                marker="10",
                marker_type="footnote_marker",
                text="old note",
                source="unit-test",
                source_page_label="p1",
                is_reconstructed=False,
                review_required=False,
            ),
            NoteItemRecord(
                note_item_id="n-1",
                region_id="rg-1",
                chapter_id="ch-1",
                page_no=2,
                marker="70",
                marker_type="footnote_marker",
                text="target note",
                source="unit-test",
                source_page_label="p2",
                is_reconstructed=False,
                review_required=False,
            ),
        ]
        anchors = [
            BodyAnchorRecord(
                anchor_id="synthetic-old",
                chapter_id="ch-1",
                page_no=1,
                paragraph_index=999,
                char_start=0,
                char_end=0,
                source_marker="10",
                normalized_marker="10",
                anchor_kind="footnote",
                certainty=0.4,
                source_text="old synthetic anchor",
                source="synthetic",
                synthetic=True,
                ocr_repaired_from_marker="",
            ),
            BodyAnchorRecord(
                anchor_id="anchor-old",
                chapter_id="ch-1",
                page_no=1,
                paragraph_index=0,
                char_start=10,
                char_end=11,
                source_marker="70",
                normalized_marker="70",
                anchor_kind="footnote",
                certainty=1.0,
                source_text="old wrong anchor",
                source="markdown",
                synthetic=False,
                ocr_repaired_from_marker="",
            ),
            BodyAnchorRecord(
                anchor_id="anchor-new",
                chapter_id="ch-1",
                page_no=2,
                paragraph_index=0,
                char_start=20,
                char_end=21,
                source_marker="76",
                normalized_marker="76",
                anchor_kind="footnote",
                certainty=1.0,
                source_text="new explicit anchor",
                source="markdown",
                synthetic=False,
                ocr_repaired_from_marker="",
            ),
        ]
        regions = [
            NoteRegionRecord(
                region_id="rg-1",
                chapter_id="ch-1",
                page_start=2,
                page_end=2,
                pages=[2],
                note_kind="footnote",
                scope="chapter",
                source="llm",
                heading_text="",
                start_reason="unit-test",
                end_reason="unit-test",
                region_marker_alignment_ok=True,
                region_start_first_source_marker="70",
                region_first_note_item_marker="70",
                review_required=False,
            )
        ]

        effective_links, summary, _logs = _apply_link_overrides(
            links,
            link_overrides={
                "link-stale": {
                    "action": "match",
                    "note_item_id": "n-1",
                    "anchor_id": "anchor-new",
                }
            },
            note_items=note_items,
            body_anchors=anchors,
            note_regions=regions,
            chapter_mode_by_id={"ch-1": "footnote_primary"},
        )

        current = next(row for row in effective_links if row.link_id == "link-current")
        stale = next(row for row in effective_links if row.link_id == "link-stale")
        orphan = next(row for row in effective_links if row.link_id == "link-orphan")
        self.assertEqual(current.anchor_id, "anchor-new")
        self.assertEqual(current.status, "matched")
        self.assertEqual(stale.note_item_id, "n-old")
        self.assertEqual(orphan.status, "ignored")
        self.assertEqual(int(summary.get("matched_link_override_count") or 0), 1)


if __name__ == "__main__":
    unittest.main()

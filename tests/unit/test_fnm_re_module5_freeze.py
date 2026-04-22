from __future__ import annotations

from dataclasses import asdict
import unittest

from FNM_RE.modules.book_note_type import build_book_note_profile
from FNM_RE.modules.chapter_split import build_chapter_layers
from FNM_RE.modules.note_linking import build_note_link_table
from FNM_RE.modules.ref_freeze import build_frozen_units
from FNM_RE.modules.toc_structure import build_toc_structure
from FNM_RE.modules.types import (
    BodyPageLayer,
    ChapterLayer,
    ChapterLayers,
    LayerNoteItem,
    LayerNoteRegion,
    NoteLinkTable,
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


def _build_layers_and_links(
    pages: list[dict],
    toc_items: list[dict],
    *,
    link_overrides: dict | None = None,
):
    toc = build_toc_structure(pages, toc_items).data
    profile = build_book_note_profile(toc, pages).data
    layers = build_chapter_layers(toc, profile, pages).data
    note_link_result = build_note_link_table(layers, pages, overrides=link_overrides)
    return layers, note_link_result


class FnmReModule5FreezeTest(unittest.TestCase):
    def _build_biopolitics_inputs(self):
        pages = load_pages("Biopolitics")
        toc = build_toc_structure(pages, load_auto_visual_toc("Biopolitics")).data
        profile = build_book_note_profile(toc, pages).data
        layers = build_chapter_layers(toc, profile, pages).data
        link_table = build_note_link_table(layers, pages).data
        return pages, layers, link_table

    def _minimal_chapter_layers(
        self,
        *,
        chapters: list[ChapterLayer],
        regions: list[LayerNoteRegion],
        note_items: list[LayerNoteItem],
    ) -> ChapterLayers:
        return ChapterLayers(
            chapters=list(chapters),
            regions=list(regions),
            note_items=list(note_items),
            region_summary={},
            item_summary={},
        )

    def test_biopolitics_main_path_hard_gates_true(self):
        pages, layers, link_table = self._build_biopolitics_inputs()
        result = build_frozen_units(layers, link_table)
        self.assertTrue(all(result.gate_report.hard.values()))
        self.assertTrue(result.data.body_units)
        self.assertEqual(len(result.data.note_units), len(layers.note_items))
        self.assertEqual(
            int(result.data.freeze_summary.get("matched_link_count") or 0),
            len([row for row in link_table.effective_links if row.status == "matched"]),
        )
        self.assertEqual(result.data.freeze_summary.get("max_body_chars"), 6000)
        del pages

    def test_matched_explicit_link_injects_note_ref_token(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                footnotes="1. Footnote one.",
                block_text="Chapter One",
            ),
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_result = _build_layers_and_links(pages, toc_items)
        freeze_result = build_frozen_units(layers, note_link_result.data)
        body_text = "\n".join(row.source_text for row in freeze_result.data.body_units)
        self.assertIn("{{NOTE_REF:", body_text)
        self.assertGreater(int(freeze_result.data.freeze_summary.get("injected_count") or 0), 0)

    def test_only_matched_links_are_frozen(self):
        pages = load_pages("Biopolitics")
        toc_items = load_auto_visual_toc("Biopolitics")
        layers, first_link_result = _build_layers_and_links(pages, toc_items)
        matched_link = next(row for row in first_link_result.data.effective_links if row.status == "matched")
        layers, second_link_result = _build_layers_and_links(
            pages,
            toc_items,
            link_overrides={"link": {matched_link.link_id: {"action": "ignore"}}},
        )
        freeze_result = build_frozen_units(layers, second_link_result.data)
        frozen_link_ids = {row.link_id for row in freeze_result.data.ref_map}
        self.assertNotIn(matched_link.link_id, frozen_link_ids)
        self.assertTrue(freeze_result.gate_report.hard["freeze.only_matched_frozen"])

    def test_synthetic_anchor_is_skipped_and_warned(self):
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
        layers, note_link_result = _build_layers_and_links(pages, toc_items)
        freeze_result = build_frozen_units(layers, note_link_result.data)
        self.assertFalse(freeze_result.gate_report.soft["freeze.synthetic_skip_warn"])
        self.assertTrue(any(row.reason == "synthetic_anchor" for row in freeze_result.data.ref_map))

    def test_note_units_keep_worker_target_ref_contract(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                footnotes="1. Footnote one.",
                block_text="Chapter One",
            ),
            _make_page(2, markdown="# Chapter Two\nBody paragraph.", block_text="Chapter Two"),
        ]
        toc_items = [
            {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
            {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
        ]
        layers, note_link_result = _build_layers_and_links(pages, toc_items)
        freeze_result = build_frozen_units(layers, note_link_result.data)
        self.assertTrue(freeze_result.gate_report.hard["freeze.unit_contract_valid"])
        for unit in freeze_result.data.note_units:
            self.assertTrue(unit.target_ref.startswith("{{NOTE_REF:"))
            self.assertTrue(unit.note_id)
        for unit in freeze_result.data.body_units:
            self.assertEqual(unit.target_ref, "")

    def test_freeze_does_not_mutate_input_truth_objects(self):
        pages = load_pages("Biopolitics")
        toc_items = load_auto_visual_toc("Biopolitics")
        layers, note_link_result = _build_layers_and_links(pages, toc_items)
        before_layers = asdict(layers)
        before_link_table = asdict(note_link_result.data)
        _ = build_frozen_units(layers, note_link_result.data)
        self.assertEqual(asdict(layers), before_layers)
        self.assertEqual(asdict(note_link_result.data), before_link_table)

    def test_projected_endnote_without_item_chapter_still_materializes_note_unit(self):
        chapter = ChapterLayer(
            chapter_id="ch-1",
            title="Chapter One",
            body_pages=[BodyPageLayer(page_no=1, text="Body.", split_reason="body_page", source_role="body")],
            endnote_items=[
                LayerNoteItem(
                    note_item_id="en-00001",
                    region_id="r-1",
                    chapter_id="",
                    owner_chapter_id="ch-1",
                    page_no=1,
                    marker="1",
                    source_marker="1",
                    normalized_marker="1",
                    synth_marker="",
                    projection_mode="book_marker_projected",
                    marker_type="numeric",
                    text="Projected endnote.",
                    source="unit-test",
                    is_reconstructed=False,
                    review_required=False,
                    note_kind="endnote",
                )
            ],
            policy_applied={"book_type": "mixed", "note_mode": "book_endnote_bound"},
        )
        region = LayerNoteRegion(
            region_id="r-1",
            chapter_id="",
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
        item = chapter.endnote_items[0]
        layers = self._minimal_chapter_layers(chapters=[chapter], regions=[region], note_items=[item])
        result = build_frozen_units(layers, NoteLinkTable())
        self.assertTrue(result.gate_report.hard["freeze.unit_contract_valid"])
        note_unit = next(unit for unit in result.data.note_units if unit.note_id == "en-00001")
        self.assertEqual(note_unit.section_id, "ch-1")

    def test_owner_resolution_follows_item_then_region_priority(self):
        chapter_one = ChapterLayer(
            chapter_id="ch-1",
            title="Chapter One",
            body_pages=[BodyPageLayer(page_no=1, text="Body.", split_reason="body_page", source_role="body")],
            endnote_items=[],
            policy_applied={"book_type": "mixed", "note_mode": "book_endnote_bound"},
        )
        chapter_two = ChapterLayer(
            chapter_id="ch-2",
            title="Chapter Two",
            body_pages=[BodyPageLayer(page_no=2, text="Body.", split_reason="body_page", source_role="body")],
            endnote_items=[],
            policy_applied={"book_type": "mixed", "note_mode": "book_endnote_bound"},
        )
        regions = [
            LayerNoteRegion(
                region_id="r-item-owner",
                chapter_id="ch-2",
                owner_chapter_id="ch-1",
                page_start=1,
                page_end=1,
                pages=[1],
                note_kind="endnote",
                scope="book",
                source_scope="book",
                source="unit-test",
                bind_method="marker_projection",
                bind_confidence=1.0,
                heading_text="",
                review_required=False,
            ),
            LayerNoteRegion(
                region_id="r-item-chapter",
                chapter_id="ch-2",
                owner_chapter_id="",
                page_start=2,
                page_end=2,
                pages=[2],
                note_kind="endnote",
                scope="chapter",
                source_scope="chapter",
                source="unit-test",
                bind_method="rule",
                bind_confidence=1.0,
                heading_text="",
                review_required=False,
            ),
            LayerNoteRegion(
                region_id="r-region-owner",
                chapter_id="",
                owner_chapter_id="ch-1",
                page_start=1,
                page_end=1,
                pages=[1],
                note_kind="endnote",
                scope="book",
                source_scope="book",
                source="unit-test",
                bind_method="fallback_projection",
                bind_confidence=1.0,
                heading_text="",
                review_required=False,
            ),
            LayerNoteRegion(
                region_id="r-region-chapter",
                chapter_id="ch-2",
                owner_chapter_id="",
                page_start=2,
                page_end=2,
                pages=[2],
                note_kind="endnote",
                scope="chapter",
                source_scope="chapter",
                source="unit-test",
                bind_method="rule",
                bind_confidence=1.0,
                heading_text="",
                review_required=False,
            ),
        ]
        note_items = [
            LayerNoteItem(
                note_item_id="en-item-owner",
                region_id="r-item-owner",
                chapter_id="ch-2",
                owner_chapter_id="ch-1",
                page_no=1,
                marker="1",
                source_marker="1",
                normalized_marker="1",
                synth_marker="",
                projection_mode="book_projected",
                marker_type="numeric",
                text="Item owner wins",
                source="unit-test",
                is_reconstructed=False,
                review_required=False,
                note_kind="endnote",
            ),
            LayerNoteItem(
                note_item_id="en-item-chapter",
                region_id="r-item-chapter",
                chapter_id="ch-2",
                owner_chapter_id="",
                page_no=2,
                marker="2",
                source_marker="2",
                normalized_marker="2",
                synth_marker="",
                projection_mode="native",
                marker_type="numeric",
                text="Item chapter wins",
                source="unit-test",
                is_reconstructed=False,
                review_required=False,
                note_kind="endnote",
            ),
            LayerNoteItem(
                note_item_id="en-region-owner",
                region_id="r-region-owner",
                chapter_id="",
                owner_chapter_id="",
                page_no=1,
                marker="3",
                source_marker="3",
                normalized_marker="3",
                synth_marker="",
                projection_mode="book_fallback_projected",
                marker_type="numeric",
                text="Region owner wins",
                source="unit-test",
                is_reconstructed=False,
                review_required=False,
                note_kind="endnote",
            ),
            LayerNoteItem(
                note_item_id="en-region-chapter",
                region_id="r-region-chapter",
                chapter_id="",
                owner_chapter_id="",
                page_no=2,
                marker="4",
                source_marker="4",
                normalized_marker="4",
                synth_marker="",
                projection_mode="native",
                marker_type="numeric",
                text="Region chapter fallback",
                source="unit-test",
                is_reconstructed=False,
                review_required=False,
                note_kind="endnote",
            ),
        ]
        layers = self._minimal_chapter_layers(
            chapters=[chapter_one, chapter_two],
            regions=regions,
            note_items=note_items,
        )
        result = build_frozen_units(layers, NoteLinkTable())
        unit_by_note = {unit.note_id: unit for unit in result.data.note_units}
        self.assertEqual(unit_by_note["en-item-owner"].section_id, "ch-1")
        self.assertEqual(unit_by_note["en-item-chapter"].section_id, "ch-2")
        self.assertEqual(unit_by_note["en-region-owner"].section_id, "ch-1")
        self.assertEqual(unit_by_note["en-region-chapter"].section_id, "ch-2")

    def test_note_unit_materialization_deduplicates_same_resolved_owner_and_note_id(self):
        chapter = ChapterLayer(
            chapter_id="ch-1",
            title="Chapter One",
            body_pages=[BodyPageLayer(page_no=1, text="Body.", split_reason="body_page", source_role="body")],
            endnote_items=[],
            policy_applied={"book_type": "mixed", "note_mode": "book_endnote_bound"},
        )
        region = LayerNoteRegion(
            region_id="r-dup",
            chapter_id="",
            owner_chapter_id="ch-1",
            page_start=1,
            page_end=1,
            pages=[1],
            note_kind="endnote",
            scope="book",
            source_scope="book",
            source="unit-test",
            bind_method="marker_projection",
            bind_confidence=1.0,
            heading_text="",
            review_required=False,
        )
        first = LayerNoteItem(
            note_item_id="en-dup",
            region_id="r-dup",
            chapter_id="",
            owner_chapter_id="ch-1",
            page_no=1,
            marker="1",
            source_marker="1",
            normalized_marker="1",
            synth_marker="",
            projection_mode="book_projected",
            marker_type="numeric",
            text="dup-one",
            source="unit-test",
            is_reconstructed=False,
            review_required=False,
            note_kind="endnote",
        )
        second = LayerNoteItem(
            note_item_id="en-dup",
            region_id="r-dup",
            chapter_id="",
            owner_chapter_id="ch-1",
            page_no=1,
            marker="1",
            source_marker="1",
            normalized_marker="1",
            synth_marker="",
            projection_mode="book_fallback_projected",
            marker_type="numeric",
            text="dup-two",
            source="unit-test",
            is_reconstructed=False,
            review_required=False,
            note_kind="endnote",
        )
        layers = self._minimal_chapter_layers(chapters=[chapter], regions=[region], note_items=[first, second])
        result = build_frozen_units(layers, NoteLinkTable())
        dup_units = [unit for unit in result.data.note_units if unit.note_id == "en-dup" and unit.section_id == "ch-1"]
        self.assertEqual(len(dup_units), 1)

    def test_unresolved_owner_items_are_reported_and_block_contract(self):
        chapter = ChapterLayer(
            chapter_id="ch-1",
            title="Chapter One",
            body_pages=[BodyPageLayer(page_no=1, text="Body.", split_reason="body_page", source_role="body")],
            policy_applied={"book_type": "mixed", "note_mode": "book_endnote_bound"},
        )
        region = LayerNoteRegion(
            region_id="r-unresolved",
            chapter_id="",
            owner_chapter_id="",
            page_start=1,
            page_end=1,
            pages=[1],
            note_kind="endnote",
            scope="book",
            source_scope="book",
            source="unit-test",
            bind_method="fallback_projection",
            bind_confidence=0.0,
            heading_text="",
            review_required=True,
        )
        item = LayerNoteItem(
            note_item_id="en-unresolved",
            region_id="r-unresolved",
            chapter_id="",
            owner_chapter_id="",
            page_no=1,
            marker="1",
            source_marker="1",
            normalized_marker="1",
            synth_marker="",
            projection_mode="book_fallback_projected",
            marker_type="numeric",
            text="unresolved",
            source="unit-test",
            is_reconstructed=False,
            review_required=True,
            note_kind="endnote",
        )
        layers = self._minimal_chapter_layers(chapters=[chapter], regions=[region], note_items=[item])
        result = build_frozen_units(layers, NoteLinkTable())
        self.assertFalse(result.gate_report.hard["freeze.unit_contract_valid"])
        freeze_summary = dict(result.data.freeze_summary or {})
        self.assertEqual(int(freeze_summary.get("unresolved_note_item_count") or 0), 1)
        self.assertIn("en-unresolved", list(freeze_summary.get("unresolved_note_item_ids_preview") or []))


if __name__ == "__main__":
    unittest.main()

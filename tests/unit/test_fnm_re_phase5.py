from __future__ import annotations

import unittest

from FNM_RE.app.pipeline import build_phase4_structure, build_phase5_structure
from FNM_RE.models import UnitPageSegmentRecord, UnitParagraphRecord
from FNM_RE.stages.diagnostics import build_diagnostic_projection
from FNM_RE.stages.units import _chunk_body_page_segments, build_translation_units


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


def _body_units(phase5, chapter_id: str | None = None):
    rows = [row for row in phase5.translation_units if row.kind == "body"]
    if chapter_id:
        rows = [row for row in rows if row.section_id == chapter_id]
    return rows


def _body_source_text(phase5, chapter_id: str | None = None) -> str:
    return "\n\n".join(row.source_text for row in _body_units(phase5, chapter_id=chapter_id))


def _phase4_signature(phase4) -> tuple:
    return (
        tuple((row.page_no, row.page_role) for row in phase4.pages),
        tuple((row.chapter_id, row.title, row.start_page, row.end_page) for row in phase4.chapters),
        tuple((row.section_head_id, row.chapter_id, row.title, row.page_no) for row in phase4.section_heads),
        tuple((row.region_id, row.chapter_id, row.note_kind, row.scope, row.page_start, row.page_end) for row in phase4.note_regions),
        tuple((row.note_item_id, row.region_id, row.chapter_id, row.page_no, row.marker) for row in phase4.note_items),
        tuple((row.anchor_id, row.chapter_id, row.page_no, row.normalized_marker, row.synthetic) for row in phase4.body_anchors),
        tuple((row.link_id, row.status, row.note_item_id, row.anchor_id, row.note_kind) for row in phase4.note_links),
        tuple((row.link_id, row.status, row.note_item_id, row.anchor_id, row.note_kind) for row in phase4.effective_note_links),
        tuple((row.review_id, row.review_type, row.chapter_id, row.page_start, row.page_end) for row in phase4.structure_reviews),
    )


class FnmRePhase5Test(unittest.TestCase):
    def test_note_start_page_keeps_body_prefix_and_excludes_notes_block(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody one.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="Body prefix before notes.\n## NOTES\n1. Endnote text."),
        ]
        phase5 = build_phase5_structure(pages, review_overrides={"page": {"2": {"page_role": "note"}}})
        source = _body_source_text(phase5)
        self.assertIn("Body prefix before notes.", source)
        self.assertNotIn("1. Endnote text.", source)

    def test_chapter_start_page_is_trimmed_to_heading(self):
        pages = [
            _make_page(
                1,
                markdown="Preface line before chapter.\n# Chapter One\nBody content.",
                block_label="doc_title",
                block_text="Chapter One",
            ),
        ]
        phase5 = build_phase5_structure(pages)
        source = _body_source_text(phase5)
        self.assertIn("Body content.", source)
        self.assertNotIn("Preface line before chapter.", source)

    def test_next_chapter_heading_prefix_is_assigned_to_previous_chapter(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody one.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="Tail before next chapter.\n# Chapter Two\nBody two.", block_label="doc_title", block_text="Chapter Two"),
        ]
        phase5 = build_phase5_structure(pages)
        self.assertGreaterEqual(len(phase5.chapters), 2)
        first_chapter_id = phase5.chapters[0].chapter_id
        second_chapter_id = phase5.chapters[1].chapter_id
        first_source = _body_source_text(phase5, chapter_id=first_chapter_id)
        second_source = _body_source_text(phase5, chapter_id=second_chapter_id)
        self.assertIn("Tail before next chapter.", first_source)
        self.assertIn("Body two.", second_source)
        self.assertNotIn("Tail before next chapter.", second_source)

    def test_trailing_markdown_note_definitions_are_removed_from_body_units(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody paragraph.\n\n1. Note definition should be removed.",
                block_label="doc_title",
                block_text="Chapter One",
            ),
        ]
        phase5 = build_phase5_structure(pages)
        source = _body_source_text(phase5)
        self.assertIn("Body paragraph.", source)
        self.assertNotIn("Note definition should be removed.", source)

    def test_chunking_skips_consumed_text_but_keeps_paragraph_metadata(self):
        segment = UnitPageSegmentRecord(
            page_no=1,
            paragraph_count=1,
            source_text="Visible paragraph",
            display_text="Visible paragraph",
            paragraphs=[
                UnitParagraphRecord(
                    order=1,
                    kind="body",
                    heading_level=0,
                    source_text="Consumed by prev page",
                    display_text="Consumed by prev page",
                    cross_page="prev",
                    consumed_by_prev=True,
                    section_path=["Chapter One"],
                    print_page_label="1",
                    translated_text="",
                    translation_status="pending",
                    attempt_count=0,
                    last_error="",
                    manual_resolved=False,
                ),
                UnitParagraphRecord(
                    order=2,
                    kind="body",
                    heading_level=0,
                    source_text="Visible paragraph",
                    display_text="Visible paragraph",
                    cross_page=None,
                    consumed_by_prev=False,
                    section_path=["Chapter One"],
                    print_page_label="1",
                    translated_text="",
                    translation_status="pending",
                    attempt_count=0,
                    last_error="",
                    manual_resolved=False,
                ),
            ],
        )
        chunks = _chunk_body_page_segments([segment], max_body_chars=6000)
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertNotIn("Consumed by prev page", chunk["source_text"])
        self.assertIn("Visible paragraph", chunk["source_text"])
        self.assertTrue(any(paragraph.consumed_by_prev for paragraph in chunk["page_segments"][0].paragraphs))

    def test_matched_explicit_link_materializes_note_ref_token(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody [1].", block_label="doc_title", block_text="Chapter One", footnotes="1. Footnote one."),
        ]
        phase5 = build_phase5_structure(pages)
        matched = [
            row for row in phase5.effective_note_links
            if row.status == "matched" and row.note_item_id and row.anchor_id
        ]
        self.assertTrue(matched)
        token = "{{NOTE_REF:" + matched[0].note_item_id + "}}"
        self.assertIn(token, _body_source_text(phase5))

    def test_ignored_ambiguous_orphan_links_do_not_materialize_tokens(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody [1].", block_label="doc_title", block_text="Chapter One", footnotes="1. Footnote one."),
        ]
        base = build_phase5_structure(pages)
        matched = next(row for row in base.effective_note_links if row.status == "matched")
        ignored = build_phase5_structure(
            pages,
            review_overrides={"link": {matched.link_id: {"action": "ignore"}}},
        )
        self.assertNotIn("{{NOTE_REF:", _body_source_text(ignored))

        ambiguous_pages = [
            _make_page(1, markdown="# Chapter One\nBody [2] and again [2].", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Notes\n2. Endnote two."),
        ]
        ambiguous = build_phase5_structure(
            ambiguous_pages,
            review_overrides={"page": {"2": {"page_role": "note"}}},
        )
        self.assertNotIn("{{NOTE_REF:", _body_source_text(ambiguous))

    def test_synthetic_anchor_wont_inject_note_ref_token(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody without marker.", block_label="doc_title", block_text="Chapter One", footnotes="1. Footnote one."),
        ]
        phase5 = build_phase5_structure(pages)
        source = _body_source_text(phase5)
        self.assertNotIn("{{NOTE_REF:", source)
        self.assertGreaterEqual(
            int(phase5.summary.ref_materialization_summary.get("synthetic_skipped_count", 0) or 0),
            1,
        )

    def test_every_note_item_generates_note_unit_with_target_ref(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody [1].", block_label="doc_title", block_text="Chapter One", footnotes="1. Footnote one."),
            _make_page(2, markdown="# Notes\n2. Endnote two."),
        ]
        phase5 = build_phase5_structure(
            pages,
            review_overrides={"page": {"2": {"page_role": "note"}}},
        )
        note_units = [row for row in phase5.translation_units if row.kind in {"footnote", "endnote"}]
        self.assertEqual(len(note_units), len(phase5.note_items))
        for unit in note_units:
            self.assertEqual(unit.target_ref, "{{NOTE_REF:" + unit.note_id + "}}")

    def test_diagnostic_pages_render_visible_refs_and_keep_fnm_refs(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody [1].", block_label="doc_title", block_text="Chapter One", footnotes="1. Footnote one."),
        ]
        phase5 = build_phase5_structure(pages)
        self.assertTrue(phase5.diagnostic_pages)
        all_entries = [entry for page in phase5.diagnostic_pages for entry in page._page_entries]
        self.assertTrue(all_entries)
        self.assertTrue(any(entry._fnm_refs for entry in all_entries))
        self.assertTrue(any("[^" in entry.original for entry in all_entries))

    def test_diagnostic_notes_are_derived_from_note_items_and_note_units(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody [1].", block_label="doc_title", block_text="Chapter One", footnotes="1. Footnote one."),
        ]
        phase4 = build_phase4_structure(pages)
        units, _summary = build_translation_units(phase4, pages=pages)
        diagnostic_pages, diagnostic_notes, _diag_summary = build_diagnostic_projection(phase4, units, pages=pages)
        del diagnostic_pages
        self.assertEqual(len(diagnostic_notes), len(phase4.note_items))
        self.assertEqual(
            {row.note_id for row in diagnostic_notes},
            {row.note_item_id for row in phase4.note_items},
        )

    def test_phase5_keeps_phase4_fields_and_does_not_mutate_phase4_truth(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody [1].", block_label="doc_title", block_text="Chapter One", footnotes="1. Footnote one."),
            _make_page(2, markdown="# Chapter Two\nBody [2].", block_label="doc_title", block_text="Chapter Two", footnotes="2. Footnote two."),
        ]
        phase4 = build_phase4_structure(pages)
        before = _phase4_signature(phase4)
        units, _summary = build_translation_units(phase4, pages=pages)
        _diag_pages, _diag_notes, _diag_summary = build_diagnostic_projection(phase4, units, pages=pages)
        after = _phase4_signature(phase4)
        self.assertEqual(before, after)

        phase5 = build_phase5_structure(pages)
        self.assertEqual(
            tuple((row.page_no, row.page_role) for row in phase5.pages),
            tuple((row.page_no, row.page_role) for row in phase4.pages),
        )
        self.assertEqual(
            tuple((row.link_id, row.status, row.note_item_id, row.anchor_id) for row in phase5.effective_note_links),
            tuple((row.link_id, row.status, row.note_item_id, row.anchor_id) for row in phase4.effective_note_links),
        )


if __name__ == "__main__":
    unittest.main()

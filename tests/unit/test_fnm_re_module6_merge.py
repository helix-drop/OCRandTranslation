from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

import FNM_RE.modules.chapter_merge as chapter_merge_module
from FNM_RE.modules.book_note_type import build_book_note_profile
from FNM_RE.modules.chapter_merge import (
    _rewrite_residual_raw_markers_for_chapter,
    build_chapter_markdown_set,
)
from FNM_RE.modules.chapter_split import build_chapter_layers
from FNM_RE.modules.note_linking import build_note_link_table
from FNM_RE.modules.ref_freeze import build_frozen_units
from FNM_RE.modules.toc_structure import build_toc_structure
from FNM_RE.modules.types import ChapterMarkdownEntry
from FNM_RE.stages.export_audit import (
    _iter_raw_note_marker_hits,
    _iter_raw_superscript_note_marker_hits,
    split_body_and_definitions,
)


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


def _build_stage5_inputs(pages: list[dict], toc_items: list[dict]):
    toc = build_toc_structure(pages, toc_items).data
    profile = build_book_note_profile(toc, pages).data
    layers = build_chapter_layers(toc, profile, pages).data
    note_link_table = build_note_link_table(layers, pages).data
    frozen_units = build_frozen_units(layers, note_link_table).data
    return layers, note_link_table, frozen_units


class FnmReModule6MergeTest(unittest.TestCase):
    def test_rewrite_raw_markers_uses_existing_local_defs_when_sequences_missing(self):
        chapter = ChapterMarkdownEntry(
            order=1,
            chapter_id="ch-1",
            title="Chapter One",
            path="chapters/001-Chapter-One.md",
            markdown_text="Body [1] and $^{1}$ and <sup>1</sup> and ¹.\n\n[^1]: Note one.",
            start_page=1,
            end_page=1,
            pages=[1],
        )

        rewritten = _rewrite_residual_raw_markers_for_chapter(
            chapter,
            note_text_by_id={},
            marker_note_sequences={},
        )

        self.assertIn("Body [^1] and [^1] and [^1] and [^1].", rewritten)
        self.assertIn("[^1]: Note one.", rewritten)

    def test_rewrite_legacy_en_token_uses_book_level_fallback_note_text(self):
        chapter = ChapterMarkdownEntry(
            order=1,
            chapter_id="ch-1",
            title="Chapter One",
            path="chapters/001-Chapter-One.md",
            markdown_text="Body [EN-en-00096].\n\n[^1]: Existing note.",
            start_page=1,
            end_page=1,
            pages=[1],
        )

        rewritten = _rewrite_residual_raw_markers_for_chapter(
            chapter,
            note_text_by_id={},
            marker_note_sequences={},
            fallback_note_text_by_id={"en-00096": "Global fallback note."},
        )

        self.assertNotIn("[EN-en-00096]", rewritten)
        self.assertIn("[^2]", rewritten)
        self.assertIn("[^2]: Global fallback note.", rewritten)

    def test_rewrite_legacy_en_token_normalizes_fallback_definition_placeholders(self):
        chapter = ChapterMarkdownEntry(
            order=1,
            chapter_id="ch-1",
            title="Chapter One",
            path="chapters/001-Chapter-One.md",
            markdown_text="Body [EN-en-00096] and [^1].\n\n[^1]: Existing note.",
            start_page=1,
            end_page=1,
            pages=[1],
        )

        rewritten = _rewrite_residual_raw_markers_for_chapter(
            chapter,
            note_text_by_id={},
            marker_note_sequences={},
            fallback_note_text_by_id={"en-00096": "Global fallback {{NOTE_REF:1}} and {{NOTE_REF:ibid}}."},
        )

        self.assertNotIn("{{NOTE_REF:", rewritten)
        self.assertIn("[^2]:", rewritten)
        self.assertRegex(rewritten, r"\[\^2\]: .*?\[\^1\]")

    def test_translation_priority_manual_machine_source_pending(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                footnotes="1. Used note.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)
        body_unit = frozen_units.body_units[0]

        body_unit.translated_text = "Manual translation."
        result_manual = build_chapter_markdown_set(
            frozen_units,
            note_link_table,
            layers,
            include_diagnostic_entries=True,
            diagnostic_machine_by_page={1: "Machine translation."},
        )
        self.assertIn("Manual translation.", result_manual.data.chapters[0].markdown_text)

        body_unit.translated_text = ""
        body_unit.source_text = "Source fallback text."
        result_machine = build_chapter_markdown_set(
            frozen_units,
            note_link_table,
            layers,
            include_diagnostic_entries=True,
            diagnostic_machine_by_page={1: "Machine translation."},
        )
        self.assertIn("Machine translation.", result_machine.data.chapters[0].markdown_text)

        result_source = build_chapter_markdown_set(
            frozen_units,
            note_link_table,
            layers,
            include_diagnostic_entries=False,
            diagnostic_machine_by_page={1: "Machine translation."},
        )
        self.assertIn("Source fallback text.", result_source.data.chapters[0].markdown_text)

        body_unit.source_text = ""
        result_pending = build_chapter_markdown_set(
            frozen_units,
            note_link_table,
            layers,
            include_diagnostic_entries=False,
        )
        self.assertIn("[待翻译]", result_pending.data.chapters[0].markdown_text)

    def test_rewrites_note_refs_and_raw_markers_and_contract_closed(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1] and $^{1}$ and ¹.",
                footnotes="1. Used note.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)
        result = build_chapter_markdown_set(frozen_units, note_link_table, layers)
        content = result.data.chapters[0].markdown_text
        body_text, _ = split_body_and_definitions(content)

        self.assertIn("[^1]", content)
        self.assertIn("[^1]: Used note.", content)
        self.assertFalse(any(True for _ in _iter_raw_note_marker_hits(body_text, allowed_markers=None)))
        self.assertFalse(any(True for _ in _iter_raw_superscript_note_marker_hits(body_text, allowed_markers=None)))
        self.assertTrue(result.gate_report.hard["merge.local_refs_closed"])
        self.assertTrue(result.gate_report.hard["merge.no_frozen_ref_leak"])
        self.assertTrue(result.gate_report.hard["merge.no_raw_marker_leak_in_body"])

    def test_only_referenced_notes_emitted(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                footnotes="1. Used note.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)

        note_unit = frozen_units.note_units[0]
        frozen_units.note_units.append(
            replace(
                note_unit,
                unit_id=f"{note_unit.unit_id}-extra",
                note_id=f"{note_unit.note_id}-extra",
                source_text="Unreferenced note text.",
                target_ref=f"{{{{NOTE_REF:{note_unit.note_id}-extra}}}}",
            )
        )
        result = build_chapter_markdown_set(frozen_units, note_link_table, layers)
        content = result.data.chapters[0].markdown_text

        self.assertIn("[^1]: Used note.", content)
        self.assertNotIn("Unreferenced note text.", content)
        self.assertNotIn("{{NOTE_REF:", content)

    def test_trailing_image_only_block_removed(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody paragraph.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)
        frozen_units.body_units[0].source_text = "Body paragraph.\n\n![](tail.png)"
        result = build_chapter_markdown_set(frozen_units, note_link_table, layers)
        content = result.data.chapters[0].markdown_text
        self.assertIn("Body paragraph.", content)
        self.assertNotIn("![](tail.png)", content)
        self.assertTrue(result.gate_report.soft["merge.image_tail_warn"])

    def test_diagnostics_include_chapter_issue_summary(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                footnotes="1. Used note.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)
        result = build_chapter_markdown_set(frozen_units, note_link_table, layers)

        chapter_issue_summary = list(result.diagnostics.get("chapter_issue_summary") or [])
        chapter_issue_counts = dict(result.diagnostics.get("chapter_issue_counts") or {})
        self.assertEqual(len(chapter_issue_summary), 1)
        row = dict(chapter_issue_summary[0] or {})
        self.assertEqual(row.get("chapter_id"), "toc-toc-1")
        self.assertFalse(bool(row.get("frozen_ref_leak")))
        self.assertFalse(bool(row.get("raw_marker_leak")))
        self.assertEqual(int(row.get("missing_definition_count") or 0), 0)
        self.assertEqual(int(row.get("orphan_definition_count") or 0), 0)
        self.assertEqual(int(chapter_issue_counts.get("chapter_issue_count") or 0), 0)

    def test_gate_reasons_include_merge_frozen_ref_leak(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                footnotes="1. Used note.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)
        leaked_chapter = ChapterMarkdownEntry(
            order=1,
            chapter_id=str(layers.chapters[0].chapter_id or "ch-1"),
            title="Chapter One",
            path="chapters/001-Chapter-One.md",
            markdown_text="# Chapter One\nBody [EN-en-00096].",
            start_page=1,
            end_page=1,
            pages=[1],
        )
        with patch.object(chapter_merge_module, "_rewrite_chapters_for_merge", return_value=[leaked_chapter]):
            result = build_chapter_markdown_set(frozen_units, note_link_table, layers)

        self.assertFalse(result.gate_report.hard["merge.no_frozen_ref_leak"])
        self.assertIn("merge_frozen_ref_leak", result.gate_report.reasons)

    def test_gate_reasons_include_merge_raw_marker_leak(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                footnotes="1. Used note.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)
        leaked_chapter = ChapterMarkdownEntry(
            order=1,
            chapter_id=str(layers.chapters[0].chapter_id or "ch-1"),
            title="Chapter One",
            path="chapters/001-Chapter-One.md",
            markdown_text="# Chapter One\nBody [^1] and [1].\n\n[^1]: Used note.",
            start_page=1,
            end_page=1,
            pages=[1],
        )
        with patch.object(chapter_merge_module, "_rewrite_chapters_for_merge", return_value=[leaked_chapter]):
            result = build_chapter_markdown_set(frozen_units, note_link_table, layers)

        self.assertFalse(result.gate_report.hard["merge.no_raw_marker_leak_in_body"])
        self.assertIn("merge_raw_marker_leak", result.gate_report.reasons)

    def test_gate_reasons_include_merge_chapter_files_emitted_failed(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                footnotes="1. Used note.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)
        with patch.object(chapter_merge_module, "_rewrite_chapters_for_merge", return_value=[]):
            result = build_chapter_markdown_set(frozen_units, note_link_table, layers)

        self.assertFalse(result.gate_report.hard["merge.chapter_files_emitted"])
        self.assertIn("merge_chapter_files_emitted_failed", result.gate_report.reasons)

    def test_mixed_footnote_primary_attaches_definition_after_owning_paragraph(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\n\nFirst paragraph [1].\n\nSecond paragraph.",
                footnotes="1. Used note.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)
        layers.chapters[0].policy_applied["book_type"] = "mixed"
        layers.chapters[0].policy_applied["note_mode"] = "footnote_primary"

        result = build_chapter_markdown_set(frozen_units, note_link_table, layers)
        content = result.data.chapters[0].markdown_text

        self.assertIn("First paragraph[^1].", content)
        self.assertIn("[^1]: Used note.", content)
        self.assertLess(content.index("First paragraph[^1]."), content.index("[^1]: Used note."))
        self.assertLess(content.index("[^1]: Used note."), content.index("Second paragraph."))
        self.assertEqual(int(result.data.merge_summary.get("inline_footnote_paragraph_attach_count") or 0), 1)
        self.assertEqual(int(result.data.merge_summary.get("chapter_end_footnote_definition_count") or 0), 0)

    def test_mixed_footnote_primary_falls_back_to_page_tail_when_paragraph_is_ambiguous(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\n\nFirst paragraph [1].\n\nSecond paragraph.",
                footnotes="1. Used note.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)
        layers.chapters[0].policy_applied["book_type"] = "mixed"
        layers.chapters[0].policy_applied["note_mode"] = "footnote_primary"
        note_link_table.anchors[0].paragraph_index = 99

        result = build_chapter_markdown_set(frozen_units, note_link_table, layers)
        content = result.data.chapters[0].markdown_text

        self.assertLess(content.index("Second paragraph."), content.index("[^1]: Used note."))
        self.assertEqual(int(result.data.merge_summary.get("inline_footnote_page_fallback_count") or 0), 1)
        self.assertEqual(int(result.data.merge_summary.get("chapter_end_footnote_definition_count") or 0), 0)

    def test_footnote_only_book_keeps_definitions_at_chapter_end(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\n\nFirst paragraph [1].\n\nSecond paragraph.",
                footnotes="1. Used note.",
                block_text="Chapter One",
            )
        ]
        toc_items = [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]
        layers, note_link_table, frozen_units = _build_stage5_inputs(pages, toc_items)
        layers.chapters[0].policy_applied["book_type"] = "footnote_only"
        layers.chapters[0].policy_applied["note_mode"] = "footnote_primary"

        result = build_chapter_markdown_set(frozen_units, note_link_table, layers)
        content = result.data.chapters[0].markdown_text

        self.assertLess(content.index("Second paragraph."), content.index("[^1]: Used note."))
        self.assertEqual(int(result.data.merge_summary.get("inline_footnote_paragraph_attach_count") or 0), 0)
        self.assertEqual(int(result.data.merge_summary.get("inline_footnote_page_fallback_count") or 0), 0)
        self.assertEqual(int(result.data.merge_summary.get("chapter_end_footnote_definition_count") or 0), 1)


if __name__ == "__main__":
    unittest.main()

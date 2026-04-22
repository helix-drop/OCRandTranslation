from __future__ import annotations

import unittest
from unittest.mock import patch

import FNM_RE.app.pipeline as pipeline_app
from FNM_RE.app.pipeline import build_module_pipeline_snapshot


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


def _sample_pages() -> list[dict]:
    return [
        _make_page(
            1,
            markdown="# Chapter One\nBody [1].",
            block_label="doc_title",
            block_text="Chapter One",
            footnotes="1. Used note text.",
        )
    ]


def _sample_toc() -> list[dict]:
    return [{"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1}]


def _endnote_sample_pages() -> list[dict]:
    return [
        _make_page(
            1,
            markdown="# Chapter One\nBody paragraph.",
            block_label="doc_title",
            block_text="Chapter One",
        ),
        _make_page(
            2,
            markdown="# Chapter Two\nBody paragraph.",
            block_label="doc_title",
            block_text="Chapter Two",
        ),
        _make_page(3, markdown="# Notes\n1. First note."),
        _make_page(4, markdown="2. Second note."),
    ]


def _endnote_sample_toc() -> list[dict]:
    return [
        {"item_id": "toc-1", "title": "Chapter One", "level": 1, "target_pdf_page": 1},
        {"item_id": "toc-2", "title": "Chapter Two", "level": 1, "target_pdf_page": 2},
    ]


def _find_note_unit(units, unit_id: str):
    return next(row for row in units if str(row.unit_id or "") == str(unit_id or ""))


class FnmRePipelineSnapshotTest(unittest.TestCase):
    def test_module_execution_order_matches_stage6(self):
        pages = _sample_pages()
        toc_items = _sample_toc()
        call_order: list[str] = []

        def _spy(name: str, fn):
            def _runner(*args, **kwargs):
                call_order.append(name)
                return fn(*args, **kwargs)

            return _runner

        toc_fn = pipeline_app.build_toc_structure
        book_type_fn = pipeline_app.build_book_note_profile
        split_fn = pipeline_app.build_chapter_layers
        link_fn = pipeline_app.build_note_link_table
        freeze_fn = pipeline_app.build_frozen_units
        merge_fn = pipeline_app.build_chapter_markdown_set
        export_fn = pipeline_app.build_module_export_bundle

        with (
            patch.object(pipeline_app, "build_toc_structure", side_effect=_spy("toc", toc_fn)),
            patch.object(pipeline_app, "build_book_note_profile", side_effect=_spy("book_type", book_type_fn)),
            patch.object(pipeline_app, "build_chapter_layers", side_effect=_spy("split", split_fn)),
            patch.object(pipeline_app, "build_note_link_table", side_effect=_spy("link", link_fn)),
            patch.object(pipeline_app, "build_frozen_units", side_effect=_spy("freeze", freeze_fn)),
            patch.object(pipeline_app, "build_chapter_markdown_set", side_effect=_spy("merge", merge_fn)),
            patch.object(pipeline_app, "build_module_export_bundle", side_effect=_spy("export", export_fn)),
        ):
            snapshot = build_module_pipeline_snapshot(pages, toc_items=toc_items, slug="demo")

        self.assertTrue(snapshot.export_result.data.chapters)
        self.assertEqual(call_order, ["toc", "book_type", "split", "link", "freeze", "merge", "export"])

    def test_repo_overlay_only_updates_translation_state_fields(self):
        pages = _sample_pages()
        toc_items = _sample_toc()
        doc_id = "demo-doc"
        baseline = build_module_pipeline_snapshot(pages, toc_items=toc_items, doc_id=doc_id, slug="demo")
        baseline_note = baseline.freeze_result.data.note_units[0]

        overlay_segments = [
            {
                "page_no": 1,
                "paragraph_count": 1,
                "source_text": "Used note text.",
                "display_text": "Used note text.",
                "paragraphs": [
                    {
                        "order": 1,
                        "kind": "body",
                        "heading_level": 0,
                        "source_text": "Used note text.",
                        "display_text": "Used note text.",
                        "translated_text": "覆盖译文",
                        "translation_status": "done",
                    }
                ],
            }
        ]
        repo_units = [
            {
                "unit_id": f"{doc_id}-{baseline_note.unit_id}",
                "translated_text": "覆盖译文",
                "status": "done",
                "error_msg": "none",
                "target_ref": "should-not-apply",
                "page_segments": overlay_segments,
            }
        ]
        snapshot = build_module_pipeline_snapshot(
            pages,
            toc_items=toc_items,
            doc_id=doc_id,
            slug="demo",
            repo_units=repo_units,
        )

        truth_note = _find_note_unit(snapshot.freeze_result.data.note_units, baseline_note.unit_id)
        effective_note = _find_note_unit(snapshot.frozen_units_effective.note_units, baseline_note.unit_id)
        phase6_note = next(row for row in snapshot.phase6.translation_units if row.unit_id == baseline_note.unit_id)

        self.assertIsNot(snapshot.freeze_result.data, snapshot.frozen_units_effective)
        self.assertEqual(truth_note.translated_text, baseline_note.translated_text)
        self.assertEqual(truth_note.status, baseline_note.status)
        self.assertEqual(truth_note.error_msg, baseline_note.error_msg)
        self.assertEqual(truth_note.page_segments, baseline_note.page_segments)
        self.assertEqual(truth_note.target_ref, baseline_note.target_ref)

        self.assertEqual(effective_note.translated_text, "覆盖译文")
        self.assertEqual(effective_note.status, "done")
        self.assertEqual(effective_note.error_msg, "none")
        self.assertEqual(effective_note.page_segments, overlay_segments)
        self.assertEqual(effective_note.target_ref, baseline_note.target_ref)

        self.assertEqual(phase6_note.translated_text, "覆盖译文")
        self.assertEqual(phase6_note.status, "done")
        self.assertEqual(phase6_note.error_msg, "none")

    def test_snapshot_contains_diagnostics_and_phase6_shadow_projection(self):
        snapshot = build_module_pipeline_snapshot(_sample_pages(), toc_items=_sample_toc(), slug="demo")

        self.assertTrue(snapshot.diagnostic_pages)
        self.assertTrue(snapshot.diagnostic_notes)
        self.assertIs(snapshot.phase6_shadow, snapshot.phase6)
        self.assertEqual(len(snapshot.phase6.diagnostic_pages), len(snapshot.diagnostic_pages))
        self.assertEqual(len(snapshot.phase6.diagnostic_notes), len(snapshot.diagnostic_notes))
        self.assertTrue(snapshot.phase6.export_bundle.chapters)
        self.assertIn(snapshot.phase6.status.structure_state, {"ready", "review_required"})

    def test_snapshot_passes_visual_toc_bundle_hints_into_split_stage(self):
        snapshot = build_module_pipeline_snapshot(
            _endnote_sample_pages(),
            toc_items=_endnote_sample_toc(),
            slug="demo-endnotes",
            review_overrides=[
                {"scope": "page", "target_id": "3", "payload": {"page_role": "note"}},
                {"scope": "page", "target_id": "4", "payload": {"page_role": "note"}},
            ],
            visual_toc_bundle={
                "endnotes_summary": {
                    "present": True,
                    "container_title": "Notes",
                    "container_printed_page": 3,
                    "container_visual_order": 10,
                    "has_chapter_keyed_subentries_in_toc": True,
                    "subentry_pattern": "numbered",
                },
                "items": [
                    {"title": "Notes", "printed_page": 3, "visual_order": 10, "role_hint": "endnotes", "parent_title": ""},
                    {
                        "title": "1. Chapter One",
                        "printed_page": 3,
                        "visual_order": 11,
                        "role_hint": "section",
                        "parent_title": "Notes",
                    },
                    {
                        "title": "2. Chapter Two",
                        "printed_page": 4,
                        "visual_order": 12,
                        "role_hint": "section",
                        "parent_title": "Notes",
                    },
                ],
            },
        )

        region_summary = dict(snapshot.split_result.data.region_summary or {})
        self.assertTrue(region_summary.get("endnote_explorer_toc_hint_present"))
        self.assertEqual(int(region_summary.get("endnote_explorer_toc_subentry_count") or 0), 2)
        self.assertIn("1. Chapter One", list(region_summary.get("endnote_explorer_toc_titles_preview") or []))


if __name__ == "__main__":
    unittest.main()

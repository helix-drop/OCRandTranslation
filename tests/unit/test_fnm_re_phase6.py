from __future__ import annotations

import inspect
import unittest
from dataclasses import replace

import FNM_RE.stages.export as export_stage
import FNM_RE.stages.export_audit as export_audit_stage
from FNM_RE.app.pipeline import build_phase5_structure, build_phase6_structure
from FNM_RE.models import Phase6Structure, SectionHeadRecord
from FNM_RE.stages.export import build_export_bundle
from FNM_RE.stages.export_audit import audit_phase6_export
from FNM_RE.status import build_phase6_status


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


def _first_chapter_path(phase6: Phase6Structure) -> str:
    return str(phase6.export_bundle.chapters[0].path or "")


def _first_chapter_content(phase6: Phase6Structure) -> str:
    path = _first_chapter_path(phase6)
    return str(phase6.export_bundle.chapter_files.get(path) or "")


def _phase5_signature(phase5) -> tuple:
    return (
        tuple((row.page_no, row.page_role) for row in phase5.pages),
        tuple((row.chapter_id, row.title, row.start_page, row.end_page) for row in phase5.chapters),
        tuple((row.section_head_id, row.chapter_id, row.title, row.page_no) for row in phase5.section_heads),
        tuple((row.region_id, row.chapter_id, row.note_kind, row.scope, row.page_start, row.page_end) for row in phase5.note_regions),
        tuple((row.note_item_id, row.region_id, row.chapter_id, row.page_no, row.marker) for row in phase5.note_items),
        tuple((row.anchor_id, row.chapter_id, row.page_no, row.normalized_marker, row.synthetic) for row in phase5.body_anchors),
        tuple((row.link_id, row.status, row.note_item_id, row.anchor_id, row.note_kind) for row in phase5.note_links),
        tuple((row.link_id, row.status, row.note_item_id, row.anchor_id, row.note_kind) for row in phase5.effective_note_links),
        tuple((row.unit_id, row.kind, row.owner_kind, row.owner_id, row.note_id, row.status) for row in phase5.translation_units),
    )


class FnmRePhase6Test(unittest.TestCase):
    def test_phase6_modules_do_not_depend_on_legacy_export_wrappers(self):
        export_source = inspect.getsource(export_stage)
        audit_source = inspect.getsource(export_audit_stage)
        for forbidden in (
            "fnm.fnm_export",
            "fnm.fnm_export_audit",
            "build_fnm_structure_status",
            "SQLiteRepository",
            "list_fnm_diagnostic_entries",
        ):
            self.assertNotIn(forbidden, export_source + audit_source)

    def test_build_phase6_outputs_bundle_index_and_chapter_files(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody one.", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="# Chapter Two\nBody two.", block_label="doc_title", block_text="Chapter Two"),
        ]
        phase6 = build_phase6_structure(pages)
        self.assertTrue(phase6.export_bundle.chapters)
        self.assertIn("index.md", phase6.export_bundle.files)
        chapter_paths = [row.path for row in phase6.export_bundle.chapters]
        self.assertTrue(all(str(path).startswith("chapters/") for path in chapter_paths))
        for path in chapter_paths:
            self.assertIn(path, phase6.export_bundle.chapter_files)

    def test_body_text_priority_manual_then_diagnostic_machine_then_pending(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody one.", block_label="doc_title", block_text="Chapter One"),
        ]
        phase5 = build_phase5_structure(pages)
        body_unit = next(row for row in phase5.translation_units if row.kind == "body")

        body_unit.translated_text = "Manual translation."
        _chapters, bundle_manual, _summary = build_export_bundle(
            phase5,
            pages=pages,
            include_diagnostic_entries=True,
        )
        chapter_path = bundle_manual.chapters[0].path
        self.assertIn("Manual translation.", bundle_manual.chapter_files.get(chapter_path, ""))

        body_unit.translated_text = ""
        diag_entry = phase5.diagnostic_pages[0]._page_entries[0]
        diag_entry.translation = "Machine translation."
        diag_entry._translation_source = "model"
        _chapters, bundle_machine, _summary = build_export_bundle(
            phase5,
            pages=pages,
            include_diagnostic_entries=True,
        )
        self.assertIn("Machine translation.", bundle_machine.chapter_files.get(chapter_path, ""))

        body_unit.source_text = ""
        for page in phase5.diagnostic_pages:
            for entry in page._page_entries:
                entry.translation = ""
                entry._machine_translation = ""
                entry._manual_translation = ""
                entry._translation_source = "source"
        _chapters, bundle_pending, _summary = build_export_bundle(
            phase5,
            pages=pages,
            include_diagnostic_entries=True,
        )
        self.assertIn("[待翻译]", bundle_pending.chapter_files.get(chapter_path, ""))

    def test_only_referenced_notes_are_exported_as_definitions(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="1. Used note text.",
            ),
        ]
        phase5 = build_phase5_structure(pages)
        note_unit = next(row for row in phase5.translation_units if row.kind == "footnote")
        phase5.translation_units.append(
            replace(
                note_unit,
                unit_id=f"{note_unit.unit_id}-extra",
                note_id=f"{note_unit.note_id}-extra",
                source_text="Unreferenced note text.",
                target_ref="{{NOTE_REF:" + note_unit.note_id + "-extra}}",
            )
        )
        _chapters, bundle, _summary = build_export_bundle(phase5, pages=pages)
        chapter_path = bundle.chapters[0].path
        content = str(bundle.chapter_files.get(chapter_path) or "")
        # 阶段1：footnote 不生成 [^N] 或 [footnote]: 区段，正文中为 *
        self.assertNotIn("[^1]", content)
        self.assertNotIn("Unreferenced note text.", content)

    def test_raw_bracket_and_superscript_markers_are_rewritten_to_local_refs(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1] and $^{1}$ and ¹.",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="1. Note one.",
            ),
        ]
        phase6 = build_phase6_structure(pages)
        content = _first_chapter_content(phase6)
        # 阶段1：footnote 标记转为 *，不占 [^N]
        self.assertNotIn("[^1]", content)
        self.assertNotIn("[1]", content)
        self.assertNotIn("$^{1}$", content)
        self.assertNotIn("¹", content)

    def test_non_exportable_section_heads_are_filtered_out(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody one.", block_label="doc_title", block_text="Chapter One"),
        ]
        phase5 = build_phase5_structure(pages)
        chapter_id = phase5.chapters[0].chapter_id
        phase5.section_heads.extend(
            [
                SectionHeadRecord(
                    section_head_id="section-head-bad-note-like",
                    chapter_id=chapter_id,
                    title="1. ibid, this should be filtered",
                    page_no=1,
                    level=2,
                    source="manual",
                ),
                SectionHeadRecord(
                    section_head_id="section-head-bad-sentence-like",
                    chapter_id=chapter_id,
                    title="This heading is intentionally very long and looks like a sentence because it has many words in a row",
                    page_no=1,
                    level=2,
                    source="manual",
                ),
            ]
        )
        _chapters, bundle, _summary = build_export_bundle(phase5, pages=pages)
        chapter_path = bundle.chapters[0].path
        content = str(bundle.chapter_files.get(chapter_path) or "")
        self.assertNotIn("### 1. ibid", content)
        self.assertNotIn("### This heading is intentionally very long", content)

    def test_trailing_image_only_block_removed(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody one.", block_label="doc_title", block_text="Chapter One"),
        ]
        phase5 = build_phase5_structure(pages)
        body_unit = next(row for row in phase5.translation_units if row.kind == "body")
        body_unit.source_text = "Body paragraph.\n\n![](tail.png)"
        _chapters, bundle, _summary = build_export_bundle(phase5, pages=pages)
        chapter_path = bundle.chapters[0].path
        content = str(bundle.chapter_files.get(chapter_path) or "")
        self.assertIn("Body paragraph.", content)
        self.assertNotIn("![](tail.png)", content)

    def test_audit_missing_post_body_export_is_blocking(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody one.", block_label="doc_title", block_text="Chapter One"),
        ]
        phase6 = build_phase6_structure(pages)
        phase6.summary.post_body_titles = ["Appendix"]
        report, _summary = audit_phase6_export(phase6, slug="demo")
        self.assertTrue(any("missing_post_body_export" in row.issue_codes for row in report.files))
        self.assertFalse(report.can_ship)

    def test_audit_container_exported_as_chapter_is_blocking(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody one.", block_label="doc_title", block_text="Chapter One"),
        ]
        phase6 = build_phase6_structure(pages)
        phase6.summary.container_titles = [phase6.export_bundle.chapters[0].title]
        report, _summary = audit_phase6_export(phase6, slug="demo")
        self.assertTrue(any("container_exported_as_chapter" in row.issue_codes for row in report.files))
        self.assertFalse(report.can_ship)

    def test_audit_export_depth_too_shallow_is_blocking(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody one.", block_label="doc_title", block_text="Chapter One"),
        ]
        phase6 = build_phase6_structure(pages)
        phase6.summary.toc_role_summary["chapter"] = 3
        report, _summary = audit_phase6_export(phase6, slug="demo")
        self.assertTrue(any("export_depth_too_shallow" in row.issue_codes for row in report.files))
        self.assertFalse(report.can_ship)

    def test_audit_does_not_treat_prose_about_publishers_as_front_matter_leak(self):
        title = "9 La lettre et l'esprit"
        content = (
            f"# {title}\n\n"
            "La traduction du cours sur le Sophiste doit paraître en 2001 chez Gallimard, "
            "et cette mention s'inscrit ici dans une analyse suivie de la réception française de Heidegger, "
            "avec un paragraphe continu, argumenté et pleinement rédigé.\n\n"
            "Le second paragraphe prolonge cette lecture en comparant plusieurs médiations éditoriales sans "
            "reprendre la forme brève, fragmentaire ou métadonnée d'une page de faux titre."
        )

        file_report = export_audit_stage.audit_markdown_file(
            path="chapters/012-9 La lettre et l'esprit.md",
            title=title,
            content=content,
            chapter_titles=[title],
            expected_role="chapter",
            expected_title=title,
        )

        self.assertNotIn("front_matter_leak", set(file_report.issue_codes or []))

    def test_audit_still_flags_obvious_front_matter_metadata_leak(self):
        title = "Chapter One"
        content = (
            f"# {title}\n\n"
            "Copyright 2024 Example Press\n"
            "All rights reserved.\n"
            "Printed in France.\n"
            "ISBN 978-0-00-000000-0"
        )

        file_report = export_audit_stage.audit_markdown_file(
            path="chapters/001-Chapter One.md",
            title=title,
            content=content,
            chapter_titles=[title],
            expected_role="chapter",
            expected_title=title,
        )

        self.assertIn("front_matter_leak", set(file_report.issue_codes or []))

    def test_phase6_status_projects_chapter_and_note_region_progress(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="1. Footnote one.",
            ),
        ]
        phase6 = build_phase6_structure(pages)
        for unit in phase6.translation_units:
            if unit.kind == "body":
                unit.status = "done"
            elif unit.kind in {"footnote", "endnote"}:
                unit.status = "error"
        status = build_phase6_status(phase6)
        self.assertGreaterEqual(int(status.chapter_progress_summary.get("total_chapters", 0) or 0), 1)
        self.assertGreaterEqual(int(status.chapter_progress_summary.get("done_chapters", 0) or 0), 1)
        self.assertGreaterEqual(int(status.note_region_progress_summary.get("total_regions", 0) or 0), 1)
        self.assertGreaterEqual(int(status.note_region_progress_summary.get("blocked_regions", 0) or 0), 1)

    def test_phase6_status_export_drift_summary_counts_legacy_and_orphans(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody one.", block_label="doc_title", block_text="Chapter One"),
        ]
        phase6 = build_phase6_structure(pages)
        chapter_path = _first_chapter_path(phase6)
        drift_text = """## Chapter One

Legacy [FN-1] [EN-2] {{NOTE_REF:x}} and local ref [^1].

[^2]: orphan definition
"""
        phase6.export_bundle.chapter_files[chapter_path] = drift_text
        phase6.export_bundle.files[chapter_path] = drift_text
        status = build_phase6_status(phase6)
        drift = dict(status.export_drift_summary or {})
        self.assertGreater(int(drift.get("legacy_footnote_ref_count", 0) or 0), 0)
        self.assertGreater(int(drift.get("legacy_en_bracket_ref_count", 0) or 0), 0)
        self.assertGreater(int(drift.get("legacy_note_token_count", 0) or 0), 0)
        self.assertGreater(int(drift.get("orphan_local_definition_count", 0) or 0), 0)
        self.assertGreater(int(drift.get("orphan_local_ref_count", 0) or 0), 0)

    def test_export_ready_flags_follow_audit_and_contract(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nThis body sentence is complete.",
                block_label="doc_title",
                block_text="Chapter One",
            ),
        ]
        phase6 = build_phase6_structure(pages)
        status = build_phase6_status(phase6)
        self.assertTrue(bool(status.export_ready_test))
        self.assertTrue(bool(status.export_ready_real))

        phase6.export_audit.can_ship = False
        blocked_status = build_phase6_status(phase6)
        self.assertFalse(bool(blocked_status.export_ready_test))
        self.assertFalse(bool(blocked_status.export_ready_real))

    def test_phase6_keeps_phase5_fields_and_does_not_mutate_phase5_truth(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody [1].",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="1. Footnote one.",
            ),
            _make_page(
                2,
                markdown="# Chapter Two\nBody [2].",
                block_label="doc_title",
                block_text="Chapter Two",
                footnotes="2. Footnote two.",
            ),
        ]
        phase5 = build_phase5_structure(pages)
        before = _phase5_signature(phase5)
        _chapters, _bundle, _summary = build_export_bundle(phase5, pages=pages)
        after = _phase5_signature(phase5)
        self.assertEqual(before, after)

        phase6 = build_phase6_structure(pages)
        self.assertEqual(
            tuple((row.page_no, row.page_role) for row in phase6.pages),
            tuple((row.page_no, row.page_role) for row in phase5.pages),
        )
        self.assertEqual(
            tuple((row.link_id, row.status, row.note_item_id, row.anchor_id) for row in phase6.effective_note_links),
            tuple((row.link_id, row.status, row.note_item_id, row.anchor_id) for row in phase5.effective_note_links),
        )
        self.assertEqual(
            tuple((row.unit_id, row.kind, row.owner_kind, row.owner_id, row.note_id) for row in phase6.translation_units),
            tuple((row.unit_id, row.kind, row.owner_kind, row.owner_id, row.note_id) for row in phase5.translation_units),
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""FNM 批测报告输出测试。"""

from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "test_fnm_batch.py"
SCRIPT_NS = runpy.run_path(str(SCRIPT_PATH))
build_markdown_report = SCRIPT_NS["build_markdown_report"]
verify_export = SCRIPT_NS["verify_export"]
analyze_export_text = SCRIPT_NS["_analyze_export_text"]
select_documents = SCRIPT_NS["select_documents"]
select_documents_from_manifest = SCRIPT_NS["select_documents_from_manifest"]
verify_fnm_structure = SCRIPT_NS["verify_fnm_structure"]


class FnmBatchReportTest(unittest.TestCase):
    def test_verify_fnm_structure_keeps_module_gate_blocking_reasons(self):
        globals_dict = verify_fnm_structure.__globals__
        original_repo_cls = globals_dict["SQLiteRepository"]
        original_status_builder = globals_dict["build_fnm_structure_status"]

        class _FakeRepo:
            def get_latest_fnm_run(self, _doc_id):
                return {"status": "done", "validation_json": "{}"}

            def list_fnm_pages(self, _doc_id):
                return [{"page_no": 1, "page_role": "body"}]

            def list_fnm_chapters(self, _doc_id):
                return [{"chapter_id": "ch-1", "title": "Chapter One", "start_page": 1}]

            def list_fnm_section_heads(self, _doc_id):
                return []

            def list_fnm_heading_candidates(self, _doc_id):
                return []

            def list_fnm_note_regions(self, _doc_id):
                return []

            def list_fnm_note_items(self, _doc_id):
                return []

            def list_fnm_body_anchors(self, _doc_id):
                return []

            def list_fnm_note_links(self, _doc_id):
                return []

            def list_fnm_structure_reviews(self, _doc_id):
                return []

        try:
            globals_dict["SQLiteRepository"] = lambda: _FakeRepo()
            globals_dict["build_fnm_structure_status"] = lambda _doc_id, repo=None, snapshot=None: {
                "structure_state": "review_required",
                "review_counts": {"toc_chapter_order_non_monotonic": 1},
                "blocking_reasons": ["toc_chapter_order_non_monotonic"],
                "heading_graph_summary": {
                    "toc_body_item_count": 9,
                    "resolved_anchor_count": 2,
                    "boundary_conflict_titles_preview": ["Introduction"],
                },
                "toc_export_coverage_summary": {"missing_body_items_preview": ["One Missing Item"]},
                "toc_alignment_summary": {},
                "toc_semantic_summary": {"nonbody_contamination_count": 2},
                "visual_toc_endnotes_summary": {"present": True, "container_title": "Notes", "container_printed_page": 331},
                "toc_semantic_contract_ok": False,
                "toc_semantic_blocking_reasons": ["toc_nonbody_as_chapter"],
                "chapter_title_alignment_ok": False,
                "chapter_section_alignment_ok": False,
                "chapter_endnote_region_alignment_ok": True,
                "chapter_endnote_region_alignment_summary": {},
                "manual_toc_required": False,
                "manual_toc_ready": True,
                "manual_toc_summary": {},
                "chapter_binding_summary": {"region_count": 2, "unassigned_item_count": 1},
                "note_capture_summary": {"expected_anchor_count": 12, "captured_note_count": 4},
                "footnote_synthesis_summary": {"status": "failed", "reason": "chapter_no_footnote_items"},
                "chapter_link_contract_summary": {"chapter_count": 3, "failed_chapter_ids": ["ch-1"]},
                "book_endnote_stream_summary": {"chapter_count": 2, "high_concentration_chapter_ids": ["ch-2"]},
                "freeze_note_unit_summary": {
                    "chapter_view_note_unit_count": 20,
                    "owner_fallback_note_unit_count": 2,
                    "unresolved_note_item_count": 1,
                    "unresolved_note_item_ids_preview": ["en-00001"],
                },
                "chapter_issue_counts": {
                    "chapter_issue_count": 1,
                    "frozen_ref_leak_chapter_count": 0,
                    "raw_marker_leak_chapter_count": 1,
                    "local_ref_contract_broken_chapter_count": 0,
                },
                "chapter_issue_summary": [
                    {
                        "chapter_id": "ch-1",
                        "path": "chapters/001-Chapter-One.md",
                        "raw_marker_leak": True,
                    }
                ],
            }
            result = verify_fnm_structure("doc-stage1")
        finally:
            globals_dict["SQLiteRepository"] = original_repo_cls
            globals_dict["build_fnm_structure_status"] = original_status_builder

        self.assertEqual(result["blocking_reasons"], ["toc_chapter_order_non_monotonic"])
        self.assertEqual(
            result["heading_graph_summary"],
            {
                "toc_body_item_count": 9,
                "resolved_anchor_count": 2,
                "boundary_conflict_titles_preview": ["Introduction"],
            },
        )
        self.assertEqual(result["chapter_binding_summary"], {"region_count": 2, "unassigned_item_count": 1})
        self.assertEqual(result["note_capture_summary"], {"expected_anchor_count": 12, "captured_note_count": 4})
        self.assertEqual(
            result["footnote_synthesis_summary"],
            {"status": "failed", "reason": "chapter_no_footnote_items"},
        )
        self.assertEqual(
            result["chapter_link_contract_summary"],
            {"chapter_count": 3, "failed_chapter_ids": ["ch-1"]},
        )
        self.assertEqual(
            result["book_endnote_stream_summary"],
            {"chapter_count": 2, "high_concentration_chapter_ids": ["ch-2"]},
        )
        self.assertEqual(
            result["freeze_note_unit_summary"],
            {
                "chapter_view_note_unit_count": 20,
                "owner_fallback_note_unit_count": 2,
                "unresolved_note_item_count": 1,
                "unresolved_note_item_ids_preview": ["en-00001"],
            },
        )
        self.assertEqual(
            result["chapter_issue_counts"],
            {
                "chapter_issue_count": 1,
                "frozen_ref_leak_chapter_count": 0,
                "raw_marker_leak_chapter_count": 1,
                "local_ref_contract_broken_chapter_count": 0,
            },
        )
        self.assertEqual(
            result["chapter_issue_summary"],
            [
                {
                    "chapter_id": "ch-1",
                    "path": "chapters/001-Chapter-One.md",
                    "raw_marker_leak": True,
                }
            ],
        )
        self.assertEqual(
            result["visual_toc_endnotes_summary"],
            {"present": True, "container_title": "Notes", "container_printed_page": 331},
        )

    def test_verify_fnm_structure_forwards_snapshot_to_status_builder(self):
        globals_dict = verify_fnm_structure.__globals__
        original_repo_cls = globals_dict["SQLiteRepository"]
        original_status_builder = globals_dict["build_fnm_structure_status"]
        captured: dict[str, object] = {}

        class _FakeRepo:
            def get_latest_fnm_run(self, _doc_id):
                return {"status": "done", "validation_json": "{}"}

            def list_fnm_pages(self, _doc_id):
                return [{"page_no": 1, "page_role": "body"}]

            def list_fnm_chapters(self, _doc_id):
                return [{"chapter_id": "ch-1", "title": "Chapter One", "start_page": 1}]

            def list_fnm_section_heads(self, _doc_id):
                return []

            def list_fnm_heading_candidates(self, _doc_id):
                return []

            def list_fnm_note_regions(self, _doc_id):
                return []

            def list_fnm_note_items(self, _doc_id):
                return []

            def list_fnm_body_anchors(self, _doc_id):
                return []

            def list_fnm_note_links(self, _doc_id):
                return []

            def list_fnm_structure_reviews(self, _doc_id):
                return []

        def _fake_status_builder(_doc_id, repo=None, snapshot=None):
            captured["snapshot"] = snapshot
            return {
                "structure_state": "ready",
                "review_counts": {},
                "blocking_reasons": [],
                "toc_export_coverage_summary": {"missing_body_items_preview": []},
                "toc_alignment_summary": {},
                "toc_semantic_summary": {},
                "toc_semantic_contract_ok": True,
                "toc_semantic_blocking_reasons": [],
                "chapter_title_alignment_ok": True,
                "chapter_section_alignment_ok": True,
                "chapter_endnote_region_alignment_ok": True,
                "chapter_endnote_region_alignment_summary": {},
                "manual_toc_required": False,
                "manual_toc_ready": True,
                "manual_toc_summary": {},
            }

        marker = object()
        try:
            globals_dict["SQLiteRepository"] = lambda: _FakeRepo()
            globals_dict["build_fnm_structure_status"] = _fake_status_builder
            result = verify_fnm_structure("doc-stage1", snapshot=marker)
        finally:
            globals_dict["SQLiteRepository"] = original_repo_cls
            globals_dict["build_fnm_structure_status"] = original_status_builder

        self.assertTrue(result["ok"])
        self.assertIs(captured.get("snapshot"), marker)

    def test_verify_fnm_structure_normalizes_summary_rows_to_dicts(self):
        globals_dict = verify_fnm_structure.__globals__
        original_repo_cls = globals_dict["SQLiteRepository"]
        original_status_builder = globals_dict["build_fnm_structure_status"]
        original_audit_builder = globals_dict["_build_chapter_endnote_region_audit"]

        class _FakeRepo:
            def get_latest_fnm_run(self, _doc_id):
                return {"status": "done", "validation_json": "{}"}

            def list_fnm_pages(self, _doc_id):
                return [{"page_no": 1, "page_role": "body"}]

            def list_fnm_chapters(self, _doc_id):
                return [{"chapter_id": "ch-1", "title": "Chapter One", "start_page": 1}]

            def list_fnm_section_heads(self, _doc_id):
                return []

            def list_fnm_heading_candidates(self, _doc_id):
                return []

            def list_fnm_note_regions(self, _doc_id):
                return []

            def list_fnm_note_items(self, _doc_id):
                return []

            def list_fnm_body_anchors(self, _doc_id):
                return []

            def list_fnm_note_links(self, _doc_id):
                return []

            def list_fnm_structure_reviews(self, _doc_id):
                return []

        try:
            globals_dict["SQLiteRepository"] = lambda: _FakeRepo()
            globals_dict["build_fnm_structure_status"] = lambda _doc_id, repo=None, snapshot=None: {
                "structure_state": "ready",
                "review_counts": {},
                "blocking_reasons": [],
                "toc_export_coverage_summary": {"missing_body_items_preview": []},
                "toc_alignment_summary": {},
                "toc_semantic_summary": {},
                "toc_semantic_contract_ok": True,
                "toc_semantic_blocking_reasons": [],
                "chapter_title_alignment_ok": True,
                "chapter_section_alignment_ok": True,
                "chapter_endnote_region_alignment_ok": True,
                "chapter_endnote_region_alignment_summary": {},
                "manual_toc_required": False,
                "manual_toc_ready": True,
                "manual_toc_summary": {},
                "chapter_issue_summary": [{"chapter_id": "ch-1"}, "invalid-row", 123],
            }
            globals_dict["_build_chapter_endnote_region_audit"] = lambda _chapters, _regions: {
                "rows": [{"chapter_id": "ch-1"}, "bad-row", 123],
                "boundary_ok": True,
                "cross_next_chapter_count": 1,
                "cross_next_chapter_preview": [{"chapter_id": "ch-1"}, "bad-row"],
            }
            result = verify_fnm_structure("doc-stage1")
        finally:
            globals_dict["SQLiteRepository"] = original_repo_cls
            globals_dict["build_fnm_structure_status"] = original_status_builder
            globals_dict["_build_chapter_endnote_region_audit"] = original_audit_builder

        self.assertEqual(
            result["chapter_issue_summary"],
            [{"chapter_id": "ch-1"}, {}, {}],
        )
        self.assertEqual(
            result["chapter_endnote_region_audit_rows"],
            [{"chapter_id": "ch-1"}, {}, {}],
        )
        self.assertEqual(
            result["chapter_endnote_region_cross_next_chapter_preview"],
            [{"chapter_id": "ch-1"}, {}],
        )

    def test_select_documents_all_docs_still_enriches_manifest_slug_and_folder(self):
        globals_dict = select_documents.__globals__
        original_list_docs = globals_dict["list_docs"]
        original_select_example_books = globals_dict["select_example_books"]

        class _Book:
            def __init__(self, *, slug: str, folder: str, group: str, doc_id: str, doc_name: str, expected_page_count: int):
                self.slug = slug
                self.folder = folder
                self.group = group
                self.doc_id = doc_id
                self.doc_name = doc_name
                self.expected_page_count = expected_page_count

        try:
            globals_dict["list_docs"] = lambda: [
                {"id": "doc-1", "name": "sample-one.pdf", "page_count": 111},
                {"id": "doc-2", "name": "sample-two.pdf", "page_count": 222},
            ]
            globals_dict["select_example_books"] = lambda **_kwargs: [
                _Book(
                    slug="BookOne",
                    folder="FolderOne",
                    group="baseline",
                    doc_id="doc-1",
                    doc_name="sample-one.pdf",
                    expected_page_count=111,
                ),
                _Book(
                    slug="BookTwo",
                    folder="FolderTwo",
                    group="extension",
                    doc_id="doc-2",
                    doc_name="sample-two.pdf",
                    expected_page_count=222,
                ),
            ]

            docs = select_documents(all_docs=True, limit=0)
        finally:
            globals_dict["list_docs"] = original_list_docs
            globals_dict["select_example_books"] = original_select_example_books

        self.assertEqual([doc["id"] for doc in docs], ["doc-1", "doc-2"])
        self.assertEqual(docs[0]["slug"], "BookOne")
        self.assertEqual(docs[0]["folder"], "FolderOne")
        self.assertEqual(docs[1]["slug"], "BookTwo")
        self.assertEqual(docs[1]["folder"], "FolderTwo")

    def test_markdown_report_prefers_new_structure_summary(self):
        report = build_markdown_report(
            [
                {
                    "doc_id": "doc-1",
                    "doc_name": "demo.pdf",
                    "all_ok": False,
                    "steps": {
                        "pipeline": {"ok": True},
                        "structure": {
                            "ok": False,
                            "structure_state": "review_required",
                            "review_counts": {
                                "link_orphan_note": 5,
                                "link_orphan_anchor": 3,
                                "toc_manual_toc_required": 2,
                                "link_ambiguous_candidate": 1,
                            },
                            "link_summary": {
                                "matched": 40,
                            },
                            "blocking_reasons": ["link_orphan_note", "toc_manual_toc_required"],
                            "export_ready_test": False,
                            "export_ready_real": False,
                            "page_partition_summary": {
                                "noise": 1,
                                "front_matter": 2,
                                "body": 10,
                                "note": 3,
                                "other": 4,
                            },
                            "chapter_mode_summary": {
                                "footnote_primary": 2,
                                "chapter_endnotes": 1,
                                "book_endnotes": 0,
                                "body_only": 3,
                                "mixed_or_unclear": 0,
                            },
                            "toc_alignment_summary": {
                                "chapter_level_body_items": 3,
                                "exported_chapter_count": 2,
                                "missing_chapter_titles_preview": ["Introduction"],
                                "misleveled_titles_preview": ["1.1 Scope"],
                                "reanchored_titles_preview": [],
                                "missing_section_titles_preview": ["1.1 Scope"],
                            },
                            "chapter_title_alignment_ok": False,
                            "chapter_section_alignment_ok": False,
                        },
                        "export": {
                            "ok": False,
                            "blocked": True,
                            "reason": "structure_review_required",
                        },
                    },
                }
            ]
        )

        self.assertIn("结构状态：review_required", report)
        self.assertIn(
            "matched / review_reason_counts：40 / "
            "link_orphan_note=5, link_orphan_anchor=3, toc_manual_toc_required=2, link_ambiguous_candidate=1",
            report,
        )
        self.assertIn("阻塞原因：`['link_orphan_note', 'toc_manual_toc_required']`", report)
        self.assertIn("页面分区：noise=1, front_matter=2, body=10, note=3, other=4", report)
        self.assertIn("章节模式：footnote_primary=2, chapter_endnotes=1, book_endnotes=0, body_only=3, mixed_or_unclear=0", report)
        self.assertIn("chapter_title_alignment_ok / chapter_section_alignment_ok：False / False", report)
        self.assertIn("导出状态：blocked (structure_review_required)", report)

    def test_verify_export_blocks_when_full_audit_has_blocking_findings(self):
        globals_dict = verify_export.__globals__
        original_bundle_builder = globals_dict["build_fnm_obsidian_export_bundle"]
        original_zip_builder = globals_dict["build_fnm_obsidian_export_zip"]
        original_audit_bundle = globals_dict["audit_export_bundle"]
        try:
            globals_dict["build_fnm_obsidian_export_bundle"] = lambda _doc_id, **_kwargs: {
                "files": {"index.md": "# Index"},
                "chapters": [{"title": "Chapter One", "path": "chapters/001-Chapter-One.md"}],
                "chapter_files": {"chapters/001-Chapter-One.md": "Body [^1].\n\n[^1]: Note text.\n"},
                "export_semantic_contract_ok": True,
                "front_matter_leak_detected": False,
                "toc_residue_detected": False,
                "mid_paragraph_heading_detected": False,
                "duplicate_paragraph_detected": False,
            }
            globals_dict["build_fnm_obsidian_export_zip"] = lambda _doc_id, **_kwargs: b"zip"
            globals_dict["audit_export_bundle"] = lambda **_kwargs: {
                "can_ship": False,
                "must_fix_before_next_book": [{"path": "chapters/001-Chapter-One.md", "issue_codes": ["raw_note_marker_leak"]}],
                "blocking_issue_count": 1,
                "files": [],
            }
            result = verify_export(
                "doc-audit-blocked",
                structure={
                    "export_ready_test": True,
                    "linked_endnote_count": 1,
                    "endnote_count": 1,
                    "footnote_count": 0,
                    "chapter_endnote_region_boundary_ok": True,
                    "manual_toc_required": False,
                    "toc_semantic_contract_ok": True,
                    "chapter_endnote_region_alignment_ok": True,
                },
            )
        finally:
            globals_dict["build_fnm_obsidian_export_bundle"] = original_bundle_builder
            globals_dict["build_fnm_obsidian_export_zip"] = original_zip_builder
            globals_dict["audit_export_bundle"] = original_audit_bundle

        self.assertFalse(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertEqual(result["full_audit_blocking_issue_count"], 1)
        self.assertFalse(result["full_audit_can_ship"])

    def test_verify_export_prefers_linked_endnote_count_when_present(self):
        globals_dict = verify_export.__globals__
        original_bundle_builder = globals_dict["build_fnm_obsidian_export_bundle"]
        original_zip_builder = globals_dict["build_fnm_obsidian_export_zip"]
        original_audit_bundle = globals_dict["audit_export_bundle"]
        try:
            globals_dict["build_fnm_obsidian_export_bundle"] = lambda _doc_id, **_kwargs: {
                "files": {"index.md": "# Index"},
                "chapters": [{"title": "Chapter One", "path": "chapters/001-Chapter-One.md"}],
                "chapter_files": {
                    "chapters/001-Chapter-One.md": (
                        "Body with note ref [^1].\n\n"
                        "[^1]: Note text."
                    ),
                },
                "export_semantic_contract_ok": True,
                "front_matter_leak_detected": False,
                "toc_residue_detected": False,
                "mid_paragraph_heading_detected": False,
                "duplicate_paragraph_detected": False,
            }
            globals_dict["build_fnm_obsidian_export_zip"] = lambda _doc_id, **_kwargs: b"zip"
            globals_dict["audit_export_bundle"] = lambda **_kwargs: {
                "can_ship": True,
                "must_fix_before_next_book": [],
                "blocking_issue_count": 0,
                "files": [],
            }
            result = verify_export(
                "doc-1",
                structure={
                    "export_ready_test": True,
                    "endnote_count": 2,
                    "linked_endnote_count": 1,
                    "footnote_count": 0,
                },
            )
        finally:
            globals_dict["build_fnm_obsidian_export_bundle"] = original_bundle_builder
            globals_dict["build_fnm_obsidian_export_zip"] = original_zip_builder
            globals_dict["audit_export_bundle"] = original_audit_bundle

        self.assertEqual(result["expected_note_count"], 1)
        self.assertEqual(result["unique_local_ref_count"], 1)
        self.assertEqual(result["unique_local_def_count"], 1)
        self.assertTrue(result["chapter_local_endnote_contract_ok"])
        self.assertTrue(result["ok"])

    def test_verify_export_uses_full_audit_as_final_semantic_gate(self):
        globals_dict = verify_export.__globals__
        original_bundle_builder = globals_dict["build_fnm_obsidian_export_bundle"]
        original_zip_builder = globals_dict["build_fnm_obsidian_export_zip"]
        original_audit_bundle = globals_dict["audit_export_bundle"]
        try:
            globals_dict["build_fnm_obsidian_export_bundle"] = lambda _doc_id, **_kwargs: {
                "files": {"index.md": "# Index"},
                "chapters": [{"title": "Chapter One", "path": "chapters/001-Chapter-One.md"}],
                "chapter_files": {
                    "chapters/001-Chapter-One.md": (
                        "Paragraph A with note [^1].\n\n"
                        "Paragraph A with note [^1].\n\n"
                        "[^1]: Note text."
                    ),
                },
                "export_semantic_contract_ok": False,
                "front_matter_leak_detected": False,
                "toc_residue_detected": False,
                "mid_paragraph_heading_detected": False,
                "duplicate_paragraph_detected": True,
            }
            globals_dict["build_fnm_obsidian_export_zip"] = lambda _doc_id, **_kwargs: b"zip"
            globals_dict["audit_export_bundle"] = lambda **_kwargs: {
                "can_ship": True,
                "must_fix_before_next_book": [],
                "blocking_issue_count": 0,
                "files": [],
            }
            result = verify_export(
                "doc-semantic-aligned",
                structure={
                    "export_ready_test": True,
                    "linked_endnote_count": 1,
                    "endnote_count": 1,
                    "footnote_count": 0,
                    "chapter_endnote_region_boundary_ok": True,
                    "manual_toc_required": False,
                    "toc_semantic_contract_ok": True,
                    "chapter_endnote_region_alignment_ok": True,
                },
            )
        finally:
            globals_dict["build_fnm_obsidian_export_bundle"] = original_bundle_builder
            globals_dict["build_fnm_obsidian_export_zip"] = original_zip_builder
            globals_dict["audit_export_bundle"] = original_audit_bundle

        self.assertFalse(result["export_semantic_contract_ok"])
        self.assertTrue(result["duplicate_paragraph_detected"])
        self.assertTrue(result["preliminary_export_ok"])
        self.assertTrue(result["full_audit_can_ship"])
        self.assertTrue(result["ok"])

    def test_verify_export_forwards_snapshot_to_bundle_and_zip(self):
        globals_dict = verify_export.__globals__
        original_bundle_builder = globals_dict["build_fnm_obsidian_export_bundle"]
        original_zip_builder = globals_dict["build_fnm_obsidian_export_zip"]
        original_audit_bundle = globals_dict["audit_export_bundle"]
        captured: dict[str, object] = {}
        marker = object()

        def _fake_bundle(_doc_id, **kwargs):
            captured["bundle_snapshot"] = kwargs.get("snapshot")
            return {
                "files": {"index.md": "# Index"},
                "chapters": [{"title": "Chapter One", "path": "chapters/001-Chapter-One.md"}],
                "chapter_files": {"chapters/001-Chapter-One.md": "Body [^1].\n\n[^1]: Note text.\n"},
                "export_semantic_contract_ok": True,
                "front_matter_leak_detected": False,
                "toc_residue_detected": False,
                "mid_paragraph_heading_detected": False,
                "duplicate_paragraph_detected": False,
            }

        def _fake_zip(_doc_id, **kwargs):
            captured["zip_snapshot"] = kwargs.get("snapshot")
            return b"zip"

        try:
            globals_dict["build_fnm_obsidian_export_bundle"] = _fake_bundle
            globals_dict["build_fnm_obsidian_export_zip"] = _fake_zip
            globals_dict["audit_export_bundle"] = lambda **_kwargs: {
                "can_ship": True,
                "must_fix_before_next_book": [],
                "blocking_issue_count": 0,
                "files": [],
            }
            result = verify_export(
                "doc-snapshot-forwarding",
                structure={
                    "export_ready_test": True,
                    "linked_endnote_count": 1,
                    "endnote_count": 1,
                    "footnote_count": 0,
                    "chapter_endnote_region_boundary_ok": True,
                    "manual_toc_required": False,
                    "toc_semantic_contract_ok": True,
                    "chapter_endnote_region_alignment_ok": True,
                },
                snapshot=marker,
            )
        finally:
            globals_dict["build_fnm_obsidian_export_bundle"] = original_bundle_builder
            globals_dict["build_fnm_obsidian_export_zip"] = original_zip_builder
            globals_dict["audit_export_bundle"] = original_audit_bundle

        self.assertTrue(result["ok"])
        self.assertIs(captured.get("bundle_snapshot"), marker)
        self.assertIs(captured.get("zip_snapshot"), marker)

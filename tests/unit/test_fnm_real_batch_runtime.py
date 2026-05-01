#!/usr/bin/env python3
"""真实批跑脚本的运行时落盘测试。"""

from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "test_fnm_real_batch.py"
SCRIPT_NS = runpy.run_path(str(SCRIPT_PATH))

ExampleBook = SCRIPT_NS["ExampleBook"]
asset_paths = SCRIPT_NS["_asset_paths"]
process_book = SCRIPT_NS["_process_book"]
build_blocking_details = SCRIPT_NS["_build_blocking_details"]
build_module_process_report = SCRIPT_NS["_build_module_process_report"]
cleanup_example_results = SCRIPT_NS["_cleanup_example_results"]
main = SCRIPT_NS["main"]


class FnmRealBatchRuntimeTest(unittest.TestCase):
    def test_asset_paths_accepts_alternate_manual_toc_pdf_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            folder = root / "Biopolitics"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "Biopolitics目录.pdf").write_text("toc", encoding="utf-8")
            book = ExampleBook(
                slug="Biopolitics",
                folder="Biopolitics",
                group="baseline",
                doc_name="demo.pdf",
                source_pdf_path="",
                doc_id="doc-demo",
                include_in_default_batch=True,
                expected_page_count=1,
            )

            with patch.dict(asset_paths.__globals__, {"TEST_EXAMPLE_ROOT": root}):
                paths = asset_paths(book)

            self.assertEqual(paths["manual_toc_pdf"], folder / "Biopolitics目录.pdf")

    def test_cleanup_example_results_removes_old_outputs_but_keeps_inputs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            example_dir = Path(tmp_dir) / "Demo"
            example_dir.mkdir(parents=True, exist_ok=True)

            preserved = [
                example_dir / "demo.pdf",
                example_dir / "raw_pages.json",
                example_dir / "raw_source_markdown.md",
                example_dir / "目录.pdf",
            ]
            for path in preserved:
                path.write_text("input", encoding="utf-8")

            llm_trace_dir = example_dir / "llm_traces"
            llm_trace_dir.mkdir(parents=True, exist_ok=True)
            removed = [
                example_dir / "fnm_real_test_progress.json",
                example_dir / "fnm_real_test_result.json",
                example_dir / "FNM_REAL_TEST_REPORT.md",
                example_dir / "auto_visual_toc.json",
                example_dir / "auto_visual_toc.md",
                example_dir / "latest.fnm.obsidian.test.zip",
                example_dir / "latest.fnm.obsidian.blocked.test.zip",
                llm_trace_dir / "stale.json",
            ]
            for path in removed:
                path.write_text("stale", encoding="utf-8")

            result = cleanup_example_results(example_dir)

            self.assertGreaterEqual(len(result["removed"]), 6)
            self.assertTrue((example_dir / "fnm_cleanup_status.json").is_file())
            for path in preserved:
                self.assertTrue(path.exists(), str(path))
            self.assertFalse(llm_trace_dir.exists())
            for path in removed[:-1]:
                self.assertFalse(path.exists(), str(path))

    def test_cleanup_example_results_removes_stale_export_directories(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            example_dir = Path(tmp_dir) / "Demo"
            example_dir.mkdir(parents=True, exist_ok=True)

            preserved = [
                example_dir / "demo.pdf",
                example_dir / "raw_pages.json",
                example_dir / "raw_source_markdown.md",
                example_dir / "目录.pdf",
            ]
            for path in preserved:
                path.write_text("input", encoding="utf-8")

            stale_dirs = [
                example_dir / "latest.fnm.obsidian",
                example_dir / "latest.fnm.obsidian.blocked.test",
                example_dir / "forced_export_demo_20260421-010203",
            ]
            for path in stale_dirs:
                path.mkdir(parents=True, exist_ok=True)
                (path / "index.md").write_text("stale", encoding="utf-8")

            stale_files = [
                example_dir / "forced_export_demo_20260421-010203.zip",
            ]
            for path in stale_files:
                path.write_text("stale", encoding="utf-8")

            result = cleanup_example_results(example_dir)

            removed_paths = set(result["removed"])
            for path in stale_dirs + stale_files:
                self.assertIn(str(path), removed_paths)
                self.assertFalse(path.exists(), str(path))
            for path in preserved:
                self.assertTrue(path.exists(), str(path))

    def test_build_blocking_details_returns_empty_for_non_blocked_book(self):
        details = build_blocking_details(
            "doc-demo",
            structure={"heading_graph_summary": {}},
            export_result={"blocked": False},
            visual_result={},
            trace_index=[],
            stage_errors=[],
            blocking_reasons=[],
        )
        self.assertEqual(details, [])

    def test_build_blocking_details_uses_repo_section_head_when_visual_item_missing(self):
        class _RepoStub:
            def list_fnm_section_heads(self, _doc_id):
                return [{"text": "Chapter One", "page_no": 12}]

            def list_fnm_note_items(self, _doc_id):
                return []

            def list_fnm_body_anchors(self, _doc_id):
                return []

            def list_fnm_note_links(self, _doc_id):
                return []

            def list_fnm_translation_units(self, _doc_id):
                return []

        with patch.dict(build_blocking_details.__globals__, {"SQLiteRepository": lambda: _RepoStub()}):
            details = build_blocking_details(
                "doc-demo",
                structure={
                    "heading_graph_summary": {
                        "boundary_conflict_titles_preview": ["Chapter One"],
                        "unresolved_titles_preview": [],
                    }
                },
                export_result={"blocked": True, "reason": "structure_review_required"},
                visual_result={},
                trace_index=[],
                stage_errors=[],
                blocking_reasons=["heading_graph_boundary_conflict"],
            )

        self.assertEqual(details[0]["reason_code"], "heading_graph_boundary_conflict")
        self.assertIn("原书 p.12", details[0]["paragraph_locator"])
        self.assertIn("Chapter One", details[0]["paragraph_locator"])

    def test_build_module_process_report_collects_boundary_regions_and_anchor_evidence(self):
        class _RepoStub:
            def list_fnm_pages(self, _doc_id):
                return [
                    {"page_no": 1, "target_pdf_page": 1, "page_role": "front_matter", "role_reason": "default_body", "role_confidence": 1.0, "has_note_heading": False, "section_hint": ""},
                    {"page_no": 2, "target_pdf_page": 2, "page_role": "body", "role_reason": "chapter_title", "role_confidence": 1.0, "has_note_heading": False, "section_hint": "Chapter One"},
                    {"page_no": 9, "target_pdf_page": 9, "page_role": "note", "role_reason": "note_band", "role_confidence": 1.0, "has_note_heading": True, "section_hint": "Notes"},
                ]

            def list_fnm_note_regions(self, _doc_id):
                return [
                    {
                        "region_id": "nr-en-1",
                        "region_kind": "endnote",
                        "start_page": 9,
                        "end_page": 10,
                        "pages": [9, 10],
                        "bound_chapter_id": "ch-1",
                        "region_start_first_source_marker": "1",
                        "region_first_note_item_marker": "1",
                        "region_marker_alignment_ok": True,
                    }
                ]

            def list_fnm_note_items(self, _doc_id):
                return [
                    {"note_item_id": "en-1", "region_id": "nr-en-1", "chapter_id": "ch-1", "page_no": 9, "marker": "1", "normalized_marker": "1", "source_text": "note one"},
                    {"note_item_id": "en-2", "region_id": "nr-en-1", "chapter_id": "ch-1", "page_no": 9, "marker": "2", "normalized_marker": "2", "source_text": "note two"},
                ]

            def list_fnm_body_anchors(self, _doc_id):
                return [
                    {"anchor_id": "anchor-1", "chapter_id": "ch-1", "page_no": 3, "paragraph_index": 2, "source_marker": "1", "normalized_marker": "1", "anchor_kind": "endnote", "certainty": 1.0, "source_text": "body marker one"},
                ]

            def list_fnm_note_links(self, _doc_id):
                return [
                    {"link_id": "link-1", "chapter_id": "ch-1", "note_item_id": "en-1", "anchor_id": "anchor-1", "status": "matched", "resolver": "repair", "marker": "1", "page_no_start": 3, "page_no_end": 3},
                ]

            def list_fnm_translation_units(self, _doc_id):
                return [
                    {"unit_id": "u-body", "kind": "body", "section_id": "ch-1", "section_title": "Chapter One", "page_start": 2, "page_end": 8, "target_ref": ""},
                    {"unit_id": "u-note", "kind": "endnote", "section_id": "ch-1", "section_title": "Chapter One", "page_start": 9, "page_end": 10, "target_ref": "{{NOTE_REF:en-1}}"},
                ]

        with patch.dict(build_module_process_report.__globals__, {"SQLiteRepository": lambda: _RepoStub()}):
            payload = build_module_process_report(
                "doc-demo",
                structure={
                    "page_partition_summary": {"body": 1, "note": 1},
                    "visual_toc_endnotes_summary": {"present": True, "container_title": "Notes"},
                    "chapter_binding_summary": {"chapter_bound_region_count": 1},
                    "chapter_endnote_region_alignment_summary": {"chapter_endnotes_total": 1},
                    "note_capture_summary": {"captured_note_item_count": 2},
                    "book_endnote_stream_summary": {"bound_note_item_count": 2},
                    "freeze_note_unit_summary": {"chapter_view_note_unit_count": 1},
                    "link_summary": {"matched": 1},
                    "chapter_link_contract_summary": {"chapter_contract_ok_count": 1},
                },
                export_result={
                    "chapter_stats": [
                        {
                            "title": "Chapter One",
                            "path": "chapters/001-chapter-one.md",
                            "local_ref_total": 2,
                            "local_def_total": 2,
                            "first_local_def_marker": "1",
                            "chapter_local_contract_ok": True,
                            "orphan_local_definitions": [],
                            "orphan_local_refs": [],
                        }
                    ]
                },
                trace_index=[
                    {"stage": "llm_repair.cluster_request", "file": "/tmp/llm.json"},
                    {"stage": "visual_toc.manual_input_extract", "file": "/tmp/toc.json"},
                ],
            )

        self.assertEqual(payload["boundary_detection"]["first_body_page"], 2)
        self.assertEqual(payload["note_region_detection"]["endnote_region_rows"][0]["region_id"], "nr-en-1")
        self.assertTrue(payload["endnote_array_building"]["endnote_array_rows"][0]["numeric_marker_contiguous"])
        self.assertEqual(payload["endnote_merging"]["export_merge_rows"][0]["local_def_total"], 2)
        self.assertEqual(payload["anchor_resolution"]["link_resolver_counts"]["repair"], 1)

    def test_process_book_writes_progress_and_continues_after_llm_repair_exception(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            example_dir = Path(tmp_dir) / "Demo"
            example_dir.mkdir(parents=True, exist_ok=True)
            (example_dir / "llm_traces").mkdir(parents=True, exist_ok=True)
            book = ExampleBook(
                slug="demo",
                folder="Demo",
                group="baseline",
                doc_name="demo.pdf",
                source_pdf_path="",
                doc_id="doc-demo",
                include_in_default_batch=True,
                expected_page_count=1,
            )

            materialize_mock = Mock(return_value={"ok": True, "translated_paras": 3})
            export_mock = Mock(
                return_value={
                    "ok": False,
                    "blocked": True,
                    "reason": "structure_review_required",
                    "blocking_reasons": ["heading_graph_boundary_conflict"],
                    "latest_export_zip_path": "",
                }
            )

            def _repair_with_incremental_trace(*_args, **kwargs):
                trace_callback = kwargs.get("trace_callback")
                if callable(trace_callback):
                    trace_callback(
                        {
                            "stage": "llm_repair.cluster_request.started",
                            "reason_for_request": "准备请求 LLM 修补 cluster",
                            "model": {"model_id": "qwen3.5-plus"},
                            "request_context_summary": {"cluster_id": "c-1"},
                            "usage": {},
                        }
                    )
                raise RuntimeError("repair boom")

            repair_mock = Mock(side_effect=_repair_with_incremental_trace)

            with (
                patch.dict(process_book.__globals__, {"_check_required_assets": lambda _book: {
                    "ok": True,
                    "paths": {
                        "folder": str(example_dir),
                        "pdf": str(example_dir / "demo.pdf"),
                        "raw_pages": str(example_dir / "raw_pages.json"),
                        "raw_source_markdown": str(example_dir / "raw_source_markdown.md"),
                        "manual_toc_pdf": str(example_dir / "目录.pdf"),
                    },
                    "manual_toc_exists": True,
                }}),
                patch.dict(process_book.__globals__, {"_resolve_example_dir": lambda _book: example_dir}),
                patch.dict(process_book.__globals__, {"reingest_book": lambda _book, rerun_auto_toc=False, restore_auto_visual_toc=False, rebuild_fnm=False: {"ok": True}}),
                patch.dict(process_book.__globals__, {"get_pdf_path": lambda _doc_id: str(example_dir / "source.pdf")}),
                patch.dict(process_book.__globals__, {"run_auto_visual_toc_for_doc": lambda *_args, **_kwargs: {
                    "status": "ready",
                    "usage_summary": {"by_stage": {}, "by_model": {}, "total": {}},
                    "llm_traces": [
                        {
                            "stage": "visual_toc.manual_input_extract",
                            "reason_for_request": "目录单页抽取",
                            "model": {"model_id": "qwen3.5-plus"},
                            "request_prompt": "prompt",
                            "request_content": {"images": [{"file_idx": 1, "sha256": "abc"}]},
                            "response_raw_text": "[]",
                            "response_parsed": [],
                            "derived_truth": {"items": []},
                            "usage": {"total_tokens": 10},
                            "timing": {"duration_ms": 12},
                        }
                    ],
                    "endnotes_summary": {},
                }}),
                patch.dict(process_book.__globals__, {"run_fnm_pipeline": Mock(side_effect=[{"ok": True, "structure_state": "ready"}, {"ok": True, "structure_state": "ready"}])}),
                patch.dict(process_book.__globals__, {"run_llm_repair": repair_mock}),
                patch.dict(process_book.__globals__, {"load_fnm_doc_structure": lambda *_args, **_kwargs: object()}),
                patch.dict(process_book.__globals__, {"verify_fnm_structure": lambda *_args, **_kwargs: {
                    "blocking_reasons": ["heading_graph_boundary_conflict"],
                    "structure_state": "review_required",
                    "heading_graph_summary": {
                        "boundary_conflict_titles_preview": ["Chapter One"],
                        "unresolved_titles_preview": [],
                    },
                    "visual_toc_endnotes_summary": {},
                    "chapter_issue_summary": [],
                }}),
                patch.dict(process_book.__globals__, {"materialize_test_placeholders": materialize_mock}),
                patch.dict(process_book.__globals__, {"verify_export": export_mock}),
                patch.dict(process_book.__globals__, {"_resolve_source_zip_path": lambda *_args, **_kwargs: None}),
                patch.dict(process_book.__globals__, {"build_fnm_obsidian_export_zip": lambda *_args, **_kwargs: b"zip-bytes"}),
                patch.dict(process_book.__globals__, {"_write_zip_aliases": lambda **_kwargs: {
                    "written": True,
                    "slug_zip_path": str(example_dir / "demo.blocked.zip"),
                    "alias_zip_path": str(example_dir / "latest.blocked.zip"),
                    "reason": "",
                }}),
                patch.dict(process_book.__globals__, {"_build_module_process_report": lambda *_args, **_kwargs: {
                    "boundary_detection": {"page_role_counts": {"body": 1}},
                    "note_region_detection": {"endnote_region_rows": []},
                    "endnote_array_building": {"endnote_array_rows": []},
                    "endnote_merging": {"export_merge_rows": []},
                    "anchor_resolution": {"link_resolver_counts": {}},
                }}),
                patch.dict(process_book.__globals__, {"_build_blocking_details": lambda *_args, **_kwargs: [
                    {
                        "stage": "llm_repair",
                        "reason_code": "runtime_exception",
                        "page_no": 12,
                        "chapter_title": "Chapter One",
                        "paragraph_locator": "原书 p.12 ¶3 — 示例文本",
                        "evidence_text_preview": "示例文本",
                        "upstream_trace_refs": [],
                    }
                ]}),
            ):
                result = process_book(book)

            progress = json.loads((example_dir / "fnm_real_test_progress.json").read_text(encoding="utf-8"))
            self.assertEqual(progress["current_stage"], "report_write")
            self.assertTrue(any(row["stage"] == "export_verify" for row in progress["stage_history"]))
            self.assertTrue((example_dir / "fnm_real_test_result.json").is_file())
            self.assertTrue((example_dir / "fnm_real_test_modules.json").is_file())
            self.assertTrue((example_dir / "FNM_REAL_TEST_REPORT.md").is_file())
            trace_files = sorted((example_dir / "llm_traces").glob("*.json"))
            self.assertTrue(trace_files)
            self.assertIn("trace_callback", repair_mock.call_args.kwargs)
            self.assertTrue(any("llm_repair.cluster_request.started" in path.name for path in trace_files))
            started_trace = json.loads(
                next(path for path in trace_files if "llm_repair.cluster_request.started" in path.name).read_text(encoding="utf-8")
            )
            self.assertEqual(started_trace["request_context_summary"]["cluster_id"], "c-1")
            self.assertTrue(materialize_mock.called)
            self.assertTrue(export_mock.called)
            self.assertTrue(result["zip_written"])
            self.assertTrue(result["blocked"])
            self.assertIn("llm_repair_exception", result["blocking_reasons"])
            self.assertTrue(result["blocking_details"])
            self.assertFalse(result["translation_api_called"])
            self.assertIn("input_assets", result)
            self.assertIn("cleanup", result)

    def test_main_flushes_batch_outputs_after_each_book(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "out"
            books = [
                SimpleNamespace(slug="a", folder="A", doc_id="doc-a"),
                SimpleNamespace(slug="b", folder="B", doc_id="doc-b"),
            ]
            write_calls: list[int] = []

            def _write_batch_outputs(_output_dir, results):
                write_calls.append(len(results))

            with (
                patch.dict(main.__globals__, {"parse_args": lambda: Namespace(slug="", folder="", doc_id="", group="all", include_all=False, limit=0, batch_tag="batch")}),
                patch.dict(main.__globals__, {"select_example_books": lambda **_kwargs: books}),
                patch.dict(main.__globals__, {"OUTPUT_ROOT": output_dir}),
                patch.dict(main.__globals__, {"_process_book": Mock(side_effect=[
                    {"slug": "a", "blocked": False, "all_ok": True, "usage_summary": {"by_stage": {}, "by_model": {}, "total": {"total_tokens": 1}}},
                    {"slug": "b", "blocked": True, "all_ok": False, "usage_summary": {"by_stage": {}, "by_model": {}, "total": {"total_tokens": 2}}},
                ])}),
                patch.dict(main.__globals__, {"_write_batch_outputs": _write_batch_outputs}),
            ):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(write_calls, [1, 2])

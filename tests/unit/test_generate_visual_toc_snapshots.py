#!/usr/bin/env python3
"""自动视觉目录快照脚本测试。"""

from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_visual_toc_snapshots.py"
SCRIPT_NS = runpy.run_path(str(SCRIPT_PATH))

SnapshotTarget = SCRIPT_NS["SnapshotTarget"]
build_markdown = SCRIPT_NS["build_markdown"]
normalize_toc_items = SCRIPT_NS["normalize_toc_items"]
process_target = SCRIPT_NS["process_target"]
resolve_book_paths = SCRIPT_NS["resolve_book_paths"]


class GenerateVisualTocSnapshotsScriptTest(unittest.TestCase):
    def test_resolve_book_paths_prefers_test_example_pdf(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            test_example_root = root / "test_example"
            docs_root = root / "documents"
            folder_dir = test_example_root / "Biopolitics"
            folder_dir.mkdir(parents=True, exist_ok=True)
            example_pdf = folder_dir / "book.pdf"
            example_pdf.write_bytes(b"%PDF-1.4\n")

            fallback_pdf = docs_root / "0d285c0800db" / "source.pdf"
            fallback_pdf.parent.mkdir(parents=True, exist_ok=True)
            fallback_pdf.write_bytes(b"%PDF-1.4\n")

            target = SnapshotTarget(doc_id="0d285c0800db", folder="Biopolitics")
            resolved_folder, resolved_pdf = resolve_book_paths(
                target,
                test_example_root=test_example_root,
                docs_root=docs_root,
            )

            self.assertEqual(resolved_folder, folder_dir)
            self.assertEqual(resolved_pdf, example_pdf)

    def test_resolve_book_paths_ignores_manual_toc_pdf(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            test_example_root = root / "test_example"
            docs_root = root / "documents"
            folder_dir = test_example_root / "Biopolitics"
            folder_dir.mkdir(parents=True, exist_ok=True)
            (folder_dir / "目录.pdf").write_bytes(b"%PDF-1.4\n")

            fallback_pdf = docs_root / "0d285c0800db" / "source.pdf"
            fallback_pdf.parent.mkdir(parents=True, exist_ok=True)
            fallback_pdf.write_bytes(b"%PDF-1.4\n")

            target = SnapshotTarget(doc_id="0d285c0800db", folder="Biopolitics")
            resolved_folder, resolved_pdf = resolve_book_paths(
                target,
                test_example_root=test_example_root,
                docs_root=docs_root,
            )

            self.assertEqual(resolved_folder, folder_dir)
            self.assertEqual(resolved_pdf, fallback_pdf)

    def test_process_target_writes_json_and_markdown_when_ready(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            folder_dir = root / "test_example" / "Biopolitics"
            folder_dir.mkdir(parents=True, exist_ok=True)
            source_pdf = folder_dir / "demo.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\n")

            def _run_auto(_doc_id: str, _pdf_path: str, model_spec=None):
                _ = model_spec
                return {
                    "status": "ready",
                    "count": 1,
                    "scan_mode": "normal",
                    "candidate_source": "local_multi_run",
                    "candidate_indices": [2, 3, 4],
                    "candidate_pdf_pages": [3, 4, 5],
                    "retry_indices": [1],
                    "retry_pdf_pages": [2],
                    "run_summaries": [
                        {
                            "start_file_idx": 2,
                            "end_file_idx": 4,
                            "page_count": 3,
                            "score": 8.2,
                            "selected_as": "primary_run",
                        }
                    ],
                    "resolved_item_count": 1,
                    "unresolved_item_count": 0,
                    "selected_page_count": 3,
                    "selected_run_count": 1,
                    "suspected_partial_capture": False,
                    "coverage_quality": "good",
                    "manual_input_mode": "manual_pdf",
                    "manual_input_page_count": 5,
                    "manual_input_source_name": "目录.pdf",
                    "organization_summary": {
                        "max_body_depth": 2,
                        "has_containers": True,
                        "has_post_body": True,
                        "has_back_matter": False,
                        "body_root_titles": ["COURS, ANNÉE 1978-1979"],
                        "container_titles": ["COURS, ANNÉE 1978-1979"],
                        "post_body_titles": ["RÉSUMÉ DU COURS"],
                        "back_matter_titles": [],
                    },
                    "endnotes_summary": {
                        "present": True,
                        "container_title": "Notes",
                        "container_printed_page": 259,
                        "container_visual_order": 21,
                        "has_chapter_keyed_subentries_in_toc": False,
                        "subentry_pattern": None,
                    },
                }

            def _load_toc(_doc_id: str):
                return [{
                    "item_id": "v-1",
                    "title": "Chapter One",
                    "file_idx": 2,
                    "role_hint": "chapter",
                    "parent_title": "COURS, ANNÉE 1978-1979",
                    "body_candidate": True,
                    "export_candidate": True,
                }]

            def _load_bundle(_doc_id: str):
                return {
                    "endnotes_summary": {
                        "present": True,
                        "container_title": "Notes",
                        "container_printed_page": 301,
                        "container_visual_order": 9,
                        "has_chapter_keyed_subentries_in_toc": False,
                        "subentry_pattern": None,
                    }
                }

            def _read_meta(_doc_id: str):
                return {
                    "name": "demo.pdf",
                    "toc_visual_status": "ready",
                    "toc_visual_message": "已生成 1 条自动视觉目录。",
                    "toc_visual_phase": "completed",
                }

            target = SnapshotTarget(doc_id="0d285c0800db", folder="Biopolitics")
            result = process_target(
                target,
                test_example_root=root / "test_example",
                docs_root=root / "documents",
                run_auto=_run_auto,
                load_toc=_load_toc,
                load_bundle=_load_bundle,
                read_meta=_read_meta,
                generated_at="2026-04-08T00:00:00+00:00",
            )

            json_path = Path(result["json_path"])
            md_path = Path(result["md_path"])
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["doc_id"], "0d285c0800db")
            self.assertEqual(payload["doc_name"], "demo.pdf")
            self.assertEqual(payload["toc_visual_status"], "ready")
            self.assertEqual(payload["item_count"], 1)
            self.assertEqual(payload["items"][0]["target_pdf_page"], 3)
            self.assertTrue(payload["items"][0]["resolved"])
            self.assertEqual(payload["scan_mode"], "normal")
            self.assertEqual(payload["candidate_source"], "local_multi_run")
            self.assertEqual(payload["candidate_pdf_pages"], [3, 4, 5])
            self.assertEqual(payload["retry_pdf_pages"], [2])
            self.assertEqual(payload["selected_page_count"], 3)
            self.assertEqual(payload["selected_run_count"], 1)
            self.assertEqual(payload["coverage_quality"], "good")
            self.assertFalse(payload["suspected_partial_capture"])
            self.assertEqual(payload["run_summaries"][0]["selected_as"], "primary_run")
            self.assertEqual(payload["manual_input_mode"], "manual_pdf")
            self.assertEqual(payload["manual_input_page_count"], 5)
            self.assertEqual(payload["manual_input_source_name"], "目录.pdf")
            self.assertEqual(payload["organization_summary"]["has_containers"], True)
            self.assertTrue(payload["endnotes_summary"]["present"])
            self.assertEqual(payload["endnotes_summary"]["container_title"], "Notes")
            self.assertEqual(payload["items"][0]["role_hint"], "chapter")
            self.assertEqual(payload["items"][0]["parent_title"], "COURS, ANNÉE 1978-1979")

            md_text = md_path.read_text(encoding="utf-8")
            self.assertIn("# Auto Visual TOC", md_text)
            self.assertIn("## 扫描诊断", md_text)
            self.assertIn("## Run 摘要", md_text)
            self.assertIn("Manual Input Mode: manual_pdf", md_text)
            self.assertIn("## 组织方式", md_text)
            self.assertIn("## 尾注容器", md_text)
            self.assertIn("| # | Level | Title | Book Page | PDF Page | Resolved |", md_text)

    def test_process_target_keeps_status_when_visual_toc_empty(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            folder_dir = root / "test_example" / "Biopolitics"
            folder_dir.mkdir(parents=True, exist_ok=True)
            source_pdf = folder_dir / "demo.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\n")

            def _run_auto(_doc_id: str, _pdf_path: str, model_spec=None):
                _ = model_spec
                return {"status": "failed", "count": 0}

            def _load_toc(_doc_id: str):
                return []

            def _load_bundle(_doc_id: str):
                return {}

            def _read_meta(_doc_id: str):
                return {
                    "name": "demo.pdf",
                    "toc_visual_status": "failed",
                    "toc_visual_message": "未找到稳定目录项。",
                    "toc_visual_phase": "failed",
                }

            target = SnapshotTarget(doc_id="0d285c0800db", folder="Biopolitics")
            result = process_target(
                target,
                test_example_root=root / "test_example",
                docs_root=root / "documents",
                run_auto=_run_auto,
                load_toc=_load_toc,
                load_bundle=_load_bundle,
                read_meta=_read_meta,
                generated_at="2026-04-08T00:00:00+00:00",
            )

            payload = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["toc_visual_status"], "failed")
            self.assertEqual(payload["items"], [])
            self.assertEqual(payload["item_count"], 0)
            self.assertEqual(payload["scan_mode"], "")
            self.assertEqual(payload["run_summaries"], [])
            self.assertEqual(payload["selected_page_count"], 0)

    def test_build_markdown_lists_unresolved_items(self):
        payload = {
            "doc_name": "demo.pdf",
            "doc_id": "doc-demo",
            "source_pdf": "/tmp/demo.pdf",
            "generated_at": "2026-04-08T00:00:00+00:00",
            "toc_visual_status": "ready",
            "toc_visual_message": "",
            "scan_mode": "normal",
            "candidate_source": "local_multi_run",
            "candidate_pdf_pages": [10, 11],
            "retry_pdf_pages": [12],
            "selected_page_count": 2,
            "selected_run_count": 1,
            "coverage_quality": "mixed",
            "suspected_partial_capture": False,
            "organization_summary": {
                "max_body_depth": 2,
                "has_containers": True,
                "has_post_body": True,
                "has_back_matter": True,
                "body_root_titles": ["COURS, ANNÉE 1978-1979"],
                "container_titles": ["COURS, ANNÉE 1978-1979"],
                "post_body_titles": ["RÉSUMÉ DU COURS"],
                "back_matter_titles": ["Index des notions"],
            },
            "run_summaries": [
                {
                    "start_file_idx": 9,
                    "end_file_idx": 10,
                    "page_count": 2,
                    "score": 7.5,
                    "selected_as": "primary_run",
                }
            ],
            "item_count": 2,
            "items": [
                {
                    "item_id": "a",
                    "title": "Chapter A",
                    "level": 1,
                    "book_page": 10,
                    "target_pdf_page": 12,
                    "resolved": True,
                },
                {
                    "item_id": "b",
                    "title": "Chapter B",
                    "level": 2,
                    "book_page": 34,
                    "resolved": False,
                },
            ],
        }

        md = build_markdown(payload)
        self.assertIn("Candidate PDF Pages: 10, 11", md)
        self.assertIn("Coverage Quality: mixed", md)
        self.assertIn("## 组织方式", md)
        self.assertIn("Container Titles", md)
        self.assertIn("| # | File Idx Range | Page Count | Selected As | Score |", md)
        self.assertIn("## 未定位条目", md)
        self.assertIn("L2 Chapter B", md)
        self.assertIn("Book Page: 34", md)

    def test_normalize_toc_items_fills_required_fields(self):
        normalized = normalize_toc_items([{"title": "Only Title", "file_idx": 0}])
        self.assertEqual(len(normalized), 1)
        item = normalized[0]
        for key in (
            "item_id",
            "title",
            "level",
            "book_page",
            "target_pdf_page",
            "print_page_label",
            "file_idx",
            "resolved",
            "source",
        ):
            self.assertIn(key, item)
        self.assertIsNone(item["book_page"])
        self.assertEqual(item["target_pdf_page"], 1)
        self.assertEqual(item["print_page_label"], "")
        self.assertEqual(item["file_idx"], 0)
        self.assertTrue(item["resolved"])
        self.assertEqual(item["source"], "auto_visual")


if __name__ == "__main__":
    unittest.main()

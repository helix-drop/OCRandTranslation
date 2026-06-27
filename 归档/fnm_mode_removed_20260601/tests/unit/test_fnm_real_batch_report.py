#!/usr/bin/env python3
"""真实批跑报告输出测试。"""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "test_fnm_real_batch.py"
SCRIPT_NS = runpy.run_path(str(SCRIPT_PATH))
build_book_report_markdown = SCRIPT_NS["_build_book_report_markdown"]
build_batch_report_markdown = SCRIPT_NS["_build_batch_report_markdown"]


def _usage_summary() -> dict:
    return {
        "by_stage": {
            "visual_toc.preflight": {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "visual_toc.classify_candidates": {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "visual_toc.extract_page_items": {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "visual_toc.manual_input_extract": {"request_count": 1, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "llm_repair.cluster_request": {"request_count": 2, "prompt_tokens": 200, "completion_tokens": 80, "total_tokens": 280},
            "translation_test": {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
        "by_model": {},
        "total": {"request_count": 3, "prompt_tokens": 300, "completion_tokens": 130, "total_tokens": 430},
    }


class FnmRealBatchReportTest(unittest.TestCase):
    def test_book_report_includes_heading_graph_summary(self):
        markdown = build_book_report_markdown(
            {
                "slug": "npi",
                "doc_id": "doc-npi",
                "blocked": True,
                "all_ok": False,
                "blocking_reasons": ["heading_graph_boundary_conflict"],
                "translation_mode": "placeholder",
                "translation_api_called": False,
                "cleanup": {"removed": ["auto_visual_toc.json"]},
                "input_assets": {
                    "pdf": {"path": "/tmp/npi.pdf", "exists": True},
                    "raw_pages": {"path": "/tmp/raw_pages.json", "exists": True},
                    "raw_source_markdown": {"path": "/tmp/raw_source_markdown.md", "exists": True},
                    "manual_toc_pdf": {"path": "/tmp/目录.pdf", "exists": True},
                },
                "usage_summary": _usage_summary(),
                "slug_zip_path": "/tmp/npi.blocked.zip",
                "alias_zip_path": "/tmp/latest.blocked.zip",
                "module_process": {
                    "boundary_detection": {
                        "decision_basis": ["fnm_pages.page_role"],
                        "page_role_counts": {"body": 10, "note": 2},
                        "first_body_page": 3,
                        "first_note_page": 259,
                        "page_role_samples": [{"page_no": 3, "page_role": "body"}],
                    },
                    "note_region_detection": {
                        "decision_basis": ["fnm_note_regions"],
                        "visual_toc_endnotes_summary": {"present": True},
                        "chapter_binding_summary": {"chapter_bound_region_count": 2},
                        "endnote_region_rows": [{"region_id": "nr-en-1"}],
                    },
                    "endnote_array_building": {
                        "decision_basis": ["fnm_note_items.region_id"],
                        "note_capture_summary": {"captured_note_item_count": 9},
                        "book_endnote_stream_summary": {"bound_note_item_count": 9},
                        "endnote_array_rows": [{"region_id": "nr-en-1", "item_count": 9}],
                    },
                    "endnote_merging": {
                        "decision_basis": ["fnm_translation_units.target_ref"],
                        "freeze_note_unit_summary": {"chapter_view_note_unit_count": 9},
                        "note_unit_rows": [{"section_title": "Chapter One"}],
                        "export_merge_rows": [{"title": "Chapter One", "local_def_total": 9}],
                    },
                    "anchor_resolution": {
                        "decision_basis": ["fnm_body_anchors"],
                        "link_summary": {"matched": 9},
                        "link_resolver_counts": {"repair": 2, "rule": 7},
                        "anchor_samples": [{"anchor_id": "anchor-1"}],
                        "link_samples": [{"link_id": "link-1"}],
                    },
                },
                "visual_toc": {
                    "endnotes_summary": {
                        "present": True,
                        "container_title": "Notes",
                        "container_printed_page": 259,
                        "container_visual_order": 21,
                        "has_chapter_keyed_subentries_in_toc": False,
                        "subentry_pattern": None,
                    }
                },
                "structure": {
                    "heading_graph_summary": {
                        "toc_body_item_count": 9,
                        "resolved_anchor_count": 2,
                        "provisional_anchor_count": 0,
                        "optimized_anchor_count": 1,
                        "residual_provisional_count": 0,
                        "residual_provisional_titles_preview": [],
                        "expanded_window_hit_count": 1,
                        "composite_heading_count": 3,
                        "section_node_count": 5,
                        "unresolved_titles_preview": [],
                        "boundary_conflict_titles_preview": ["Introduction"],
                        "promoted_section_titles_preview": [],
                        "demoted_chapter_titles_preview": [],
                    }
                },
            }
        )

        self.assertIn("## Heading Graph", markdown)
        self.assertIn("Introduction", markdown)
        self.assertIn("resolved_anchor_count", markdown)
        self.assertIn("optimized_anchor_count", markdown)
        self.assertIn("residual_provisional_titles_preview", markdown)
        self.assertIn("## Endnotes Summary", markdown)
        self.assertIn("container_printed_page", markdown)
        self.assertIn("## 输入资产", markdown)
        self.assertIn("raw_source_markdown", markdown)
        self.assertIn("translation_api_called", markdown)
        self.assertIn("## 清理结果", markdown)
        self.assertIn("## 模块过程取证", markdown)
        self.assertIn("### 边界区分", markdown)
        self.assertIn("### 尾注区确定", markdown)
        self.assertIn("### 锚点寻找与链接", markdown)

    def test_batch_report_includes_heading_graph_preview_for_blocked_books(self):
        markdown = build_batch_report_markdown(
            [
                {
                    "slug": "npi",
                    "blocked": True,
                    "blocking_reasons": ["heading_graph_boundary_conflict"],
                    "usage_summary": _usage_summary(),
                    "visual_toc": {
                        "endnotes_summary": {
                            "present": True,
                            "container_title": "Notes",
                            "container_printed_page": 259,
                        }
                    },
                    "structure": {
                        "heading_graph_summary": {
                            "unresolved_titles_preview": [],
                            "boundary_conflict_titles_preview": ["Introduction", "Self and narcissism"],
                            "optimized_anchor_count": 2,
                            "residual_provisional_titles_preview": ["Appendices"],
                        }
                    },
                }
            ],
            {"by_stage": {}, "by_model": {}, "total": {}},
        )

        self.assertIn("## Heading Graph", markdown)
        self.assertIn("Introduction", markdown)
        self.assertIn("Self and narcissism", markdown)
        self.assertIn("Appendices", markdown)
        self.assertIn("| npi | blocked | 430 | 2 | yes | 259 |", markdown)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""heading_graph 两阶段锚点优化测试。"""

from __future__ import annotations

import unittest

from FNM_RE.stages.heading_graph import build_heading_graph, default_heading_graph_summary


def _page_rows(total: int = 40) -> list[dict]:
    return [{"page_no": page_no, "page_role": "body"} for page_no in range(1, total + 1)]


def _candidate(
    *,
    page_no: int,
    text: str,
    source: str = "ocr_block",
    block_label: str = "doc_title",
    top_band: bool = True,
    confidence: float = 0.9,
    heading_family_guess: str = "chapter",
    suppressed_as_chapter: bool = False,
    reject_reason: str = "",
    heading_level_hint: int = 1,
    font_weight_hint: str = "bold",
    align_hint: str = "center",
    font_name: str = "GillSansStd-Bold",
    x: float = 120.0,
    y: float = 80.0,
    width_estimate: float = 300.0,
) -> dict:
    return {
        "heading_id": f"hd-{page_no}-{text[:8]}",
        "page_no": page_no,
        "text": text,
        "normalized_text": text,
        "source": source,
        "block_label": block_label,
        "top_band": top_band,
        "confidence": confidence,
        "heading_family_guess": heading_family_guess,
        "suppressed_as_chapter": suppressed_as_chapter,
        "reject_reason": reject_reason,
        "font_height": 24.0,
        "x": x,
        "y": y,
        "width_estimate": width_estimate,
        "font_name": font_name,
        "font_weight_hint": font_weight_hint,
        "align_hint": align_hint,
        "width_ratio": 0.4,
        "heading_level_hint": heading_level_hint,
    }


class HeadingGraphOptimizerTest(unittest.TestCase):
    def test_default_summary_contains_new_optimizer_fields(self):
        summary = default_heading_graph_summary()

        self.assertEqual(summary["optimized_anchor_count"], 0)
        self.assertEqual(summary["residual_provisional_count"], 0)
        self.assertEqual(summary["expanded_window_hit_count"], 0)
        self.assertEqual(summary["composite_heading_count"], 0)
        self.assertEqual(summary["residual_provisional_titles_preview"], [])

    def test_local_exact_resolution_prefers_strong_doc_title(self):
        graph, summary = build_heading_graph(
            exportable_rows=[{"title": "Chapter One", "page_no": 10, "semantic_role": "chapter"}],
            heading_candidates=[
                _candidate(page_no=10, text="Chapter One"),
                _candidate(
                    page_no=10,
                    text="Chapter One",
                    source="markdown_heading",
                    block_label="",
                    confidence=0.6,
                    heading_level_hint=2,
                    top_band=False,
                ),
            ],
            page_rows=_page_rows(),
        )

        self.assertEqual(graph[0]["anchor_state"], "resolved")
        self.assertEqual(graph[0]["anchor_page"], 10)
        self.assertEqual(summary["resolved_anchor_count"], 1)
        self.assertEqual(summary["optimized_anchor_count"], 0)
        self.assertEqual(summary["residual_provisional_count"], 0)

    def test_residual_provisional_is_highlighted_without_unresolved(self):
        graph, summary = build_heading_graph(
            exportable_rows=[{"title": "Chapter One", "page_no": 10, "semantic_role": "chapter"}],
            heading_candidates=[],
            page_rows=_page_rows(),
        )

        self.assertEqual(graph[0]["anchor_state"], "provisional")
        self.assertEqual(graph[0]["anchor_page"], 10)
        self.assertEqual(summary["provisional_anchor_count"], 1)
        self.assertEqual(summary["residual_provisional_count"], 1)
        self.assertEqual(summary["residual_provisional_titles_preview"], ["Chapter One"])
        self.assertEqual(summary["unresolved_titles_preview"], [])
        self.assertEqual(summary["boundary_conflict_titles_preview"], [])

    def test_expanded_window_upgrades_provisional_anchor_to_resolved(self):
        graph, summary = build_heading_graph(
            exportable_rows=[
                {"title": "Errors and projections", "page_no": 10, "semantic_role": "chapter"},
                {"title": "Second Chapter", "page_no": 30, "semantic_role": "chapter"},
            ],
            heading_candidates=[
                _candidate(page_no=16, text="11 Errors and projections"),
                _candidate(page_no=30, text="Second Chapter"),
            ],
            page_rows=_page_rows(),
        )

        self.assertEqual(graph[0]["anchor_state"], "resolved")
        self.assertEqual(graph[0]["anchor_page"], 16)
        self.assertEqual(summary["optimized_anchor_count"], 1)
        self.assertEqual(summary["expanded_window_hit_count"], 1)
        self.assertEqual(summary["residual_provisional_count"], 0)

    def test_monotonic_body_target_pages_upgrade_provisional_rows_without_exact_headings(self):
        graph, summary = build_heading_graph(
            exportable_rows=[
                {"title": "Chapter One", "page_no": 10, "semantic_role": "chapter"},
                {"title": "Chapter Two", "page_no": 20, "semantic_role": "chapter"},
                {"title": "Chapter Three", "page_no": 30, "semantic_role": "chapter"},
            ],
            heading_candidates=[],
            page_rows=_page_rows(),
        )

        self.assertEqual([row["anchor_state"] for row in graph], ["resolved", "resolved", "resolved"])
        self.assertEqual([row["anchor_page"] for row in graph], [10, 20, 30])
        self.assertEqual([row["anchor_strategy"] for row in graph], ["monotonic_target"] * 3)
        self.assertEqual(summary["resolved_anchor_count"], 3)
        self.assertEqual(summary["provisional_anchor_count"], 0)
        self.assertEqual(summary["residual_provisional_count"], 0)

    def test_composite_pdf_candidates_can_match_split_title(self):
        graph, summary = build_heading_graph(
            exportable_rows=[{"title": "1 The Perils of Imagination", "page_no": 14, "semantic_role": "chapter"}],
            heading_candidates=[
                _candidate(
                    page_no=14,
                    text="1",
                    source="pdf_font_band",
                    block_label="",
                    font_weight_hint="regular",
                    font_name="GillSansStd",
                    align_hint="left",
                    width_estimate=24.0,
                ),
                _candidate(
                    page_no=14,
                    text="The Perils of",
                    source="pdf_font_band",
                    block_label="",
                    y=96.0,
                    x=160.0,
                    width_estimate=180.0,
                ),
                _candidate(
                    page_no=14,
                    text="Imagination",
                    source="pdf_font_band",
                    block_label="",
                    y=116.0,
                    x=160.0,
                    width_estimate=160.0,
                ),
            ],
            page_rows=_page_rows(),
        )

        self.assertEqual(graph[0]["anchor_state"], "resolved")
        self.assertEqual(graph[0]["anchor_page"], 14)
        self.assertGreater(summary["composite_heading_count"], 0)

    def test_same_page_conflict_still_reports_boundary_conflict(self):
        graph, summary = build_heading_graph(
            exportable_rows=[
                {"title": "Chapter One", "page_no": 10, "semantic_role": "chapter"},
                {"title": "Chapter Two", "page_no": 10, "semantic_role": "chapter"},
            ],
            heading_candidates=[
                _candidate(page_no=10, text="Chapter One"),
                _candidate(page_no=10, text="Chapter Two"),
            ],
            page_rows=_page_rows(),
        )

        self.assertEqual(len(graph), 2)
        self.assertGreater(len(summary["boundary_conflict_titles_preview"]), 0)


if __name__ == "__main__":
    unittest.main()

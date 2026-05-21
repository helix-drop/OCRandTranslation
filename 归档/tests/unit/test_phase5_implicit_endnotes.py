"""阶段5：当 LLM 漏检隐式尾注容器时，根据 page_partition 的 note 页自动合成。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from FNM_RE.models import (
    ChapterRecord,
    PagePartitionRecord,
    Phase1Structure,
    Phase1Summary,
)


def _synthesize_endnotes_summary_if_missing(
    summary: Phase1Summary,
    endnote_explorer_hints: dict,
) -> tuple[Phase1Summary, dict]:
    """当 visual_toc 未检测到尾注容器但 page_partition 有 ≥3 页 note 时，
    自动合成 endnotes_summary = {present: true}。"""
    existing = dict(summary.visual_toc_endnotes_summary or {})
    if existing.get("present"):
        return summary, endnote_explorer_hints

    note_count = int(dict(summary.page_partition_summary or {}).get("note") or 0)
    if note_count < 3:
        return summary, endnote_explorer_hints

    synthesized = {
        "present": True,
        "container_title": None,
        "container_printed_page": None,
        "container_visual_order": None,
        "has_chapter_keyed_subentries_in_toc": False,
        "subentry_pattern": "implicit_chapter_appended",
        "note_page_count": note_count,
        "synthesized": True,
    }
    new_summary = replace(summary, visual_toc_endnotes_summary=synthesized)
    new_hints = {**endnote_explorer_hints, "implicit_endnotes_detected": True, "note_page_count": note_count}
    return new_summary, new_hints


class Phase5ImplicitEndnotesTest(unittest.TestCase):
    """隐式尾注容器合成逻辑。"""

    def test_synthesize_when_present_false_and_note_pages_ge_3(self):
        summary = Phase1Summary(
            page_partition_summary={"note": 65, "body": 268},
            visual_toc_endnotes_summary={"present": False},
            heading_review_summary={}, heading_graph_summary={},
            chapter_source_summary={}, visual_toc_conflict_count=0,
            toc_alignment_summary={}, toc_semantic_summary={},
            toc_role_summary={}, container_titles=[], post_body_titles=[],
            back_matter_titles=[], chapter_title_alignment_ok=True,
            chapter_section_alignment_ok=True, toc_semantic_contract_ok=True,
            toc_semantic_blocking_reasons=[],
        )
        new_summary, hints = _synthesize_endnotes_summary_if_missing(summary, {})
        self.assertTrue(new_summary.visual_toc_endnotes_summary.get("present"))
        self.assertEqual(
            new_summary.visual_toc_endnotes_summary.get("subentry_pattern"),
            "implicit_chapter_appended",
        )
        self.assertTrue(hints.get("implicit_endnotes_detected"))

    def test_no_synthesize_when_already_present(self):
        summary = Phase1Summary(
            page_partition_summary={"note": 65},
            visual_toc_endnotes_summary={"present": True},
            heading_review_summary={}, heading_graph_summary={},
            chapter_source_summary={}, visual_toc_conflict_count=0,
            toc_alignment_summary={}, toc_semantic_summary={},
            toc_role_summary={}, container_titles=[], post_body_titles=[],
            back_matter_titles=[], chapter_title_alignment_ok=True,
            chapter_section_alignment_ok=True, toc_semantic_contract_ok=True,
            toc_semantic_blocking_reasons=[],
        )
        new_summary, _ = _synthesize_endnotes_summary_if_missing(summary, {})
        self.assertTrue(new_summary.visual_toc_endnotes_summary.get("present"))

    def test_no_synthesize_when_too_few_note_pages(self):
        summary = Phase1Summary(
            page_partition_summary={"note": 1},
            visual_toc_endnotes_summary={"present": False},
            heading_review_summary={}, heading_graph_summary={},
            chapter_source_summary={}, visual_toc_conflict_count=0,
            toc_alignment_summary={}, toc_semantic_summary={},
            toc_role_summary={}, container_titles=[], post_body_titles=[],
            back_matter_titles=[], chapter_title_alignment_ok=True,
            chapter_section_alignment_ok=True, toc_semantic_contract_ok=True,
            toc_semantic_blocking_reasons=[],
        )
        new_summary, _ = _synthesize_endnotes_summary_if_missing(summary, {})
        self.assertFalse(new_summary.visual_toc_endnotes_summary.get("present"))


if __name__ == "__main__":
    unittest.main()

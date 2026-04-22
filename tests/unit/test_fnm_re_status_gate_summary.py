from __future__ import annotations

import unittest

from FNM_RE.app.pipeline import build_module_pipeline_snapshot
from FNM_RE.status import build_module_gate_status


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


class FnmReStatusGateSummaryTest(unittest.TestCase):
    def _snapshot(self):
        return build_module_pipeline_snapshot(_sample_pages(), toc_items=_sample_toc(), slug="demo")

    def test_blocking_reasons_and_review_counts_from_module_reasons_and_manual_toc(self):
        snapshot = self._snapshot()
        snapshot.toc_result.gate_report.hard["toc.pages_classified"] = False
        snapshot.toc_result.gate_report.reasons = ["toc_pages_unclassified", "toc_pages_unclassified"]

        status = build_module_gate_status(
            snapshot,
            pipeline_state="done",
            manual_toc_ready=False,
            manual_toc_summary={"source": "missing"},
        )

        self.assertEqual(status.structure_state, "review_required")
        self.assertEqual(status.blocking_reasons, ["toc_pages_unclassified", "toc_manual_toc_required"])
        self.assertEqual(int(status.review_counts.get("toc_pages_unclassified", 0) or 0), 2)
        self.assertEqual(int(status.review_counts.get("toc_manual_toc_required", 0) or 0), 1)
        self.assertFalse(bool(status.export_ready_test))
        self.assertFalse(bool(status.export_ready_real))

    def test_hard_failure_without_reasons_does_not_create_fallback_reason(self):
        snapshot = self._snapshot()
        snapshot.link_result.gate_report.hard["link.no_orphan_note"] = False
        snapshot.link_result.gate_report.reasons = []

        status = build_module_gate_status(
            snapshot,
            pipeline_state="done",
            manual_toc_ready=True,
            manual_toc_summary={},
        )

        self.assertEqual(status.structure_state, "review_required")
        self.assertEqual(status.blocking_reasons, [])
        self.assertEqual(status.review_counts, {})
        self.assertNotIn("link_no_orphan_note", set(status.blocking_reasons))
        self.assertFalse(bool(status.export_ready_test))
        self.assertFalse(bool(status.export_ready_real))

    def test_projection_and_contract_flags_from_snapshot_gate(self):
        snapshot = self._snapshot()
        snapshot.merge_result.gate_report.hard["merge.local_refs_closed"] = False
        snapshot.merge_result.gate_report.reasons = ["merge_local_refs_unclosed"]
        snapshot.export_result.gate_report.hard["export.semantic_contract_ok"] = False
        snapshot.export_result.gate_report.reasons = ["export_semantic_contract_broken"]

        status = build_module_gate_status(
            snapshot,
            pipeline_state="done",
            manual_toc_ready=True,
            manual_toc_summary={"source": "auto"},
        )

        self.assertEqual(status.link_summary, dict(snapshot.link_result.data.link_summary or {}))
        self.assertEqual(
            status.page_partition_summary,
            dict(snapshot.toc_result.evidence.get("page_partition_summary") or {}),
        )
        self.assertEqual(
            status.chapter_mode_summary,
            {
                "footnote_primary": 1,
                "chapter_endnotes": 0,
                "book_endnotes": 0,
                "body_only": 0,
                "mixed_or_unclear": 0,
            },
        )
        self.assertFalse(bool(status.chapter_local_endnote_contract_ok))
        self.assertFalse(bool(status.export_semantic_contract_ok))
        self.assertIn("merge_local_refs_unclosed", set(status.blocking_reasons))
        self.assertIn("export_semantic_contract_broken", set(status.blocking_reasons))
        self.assertFalse(bool(status.export_ready_test))
        self.assertFalse(bool(status.export_ready_real))

    def test_pipeline_state_branches_follow_idle_running_error_done(self):
        snapshot = self._snapshot()
        for pipeline_state in ("idle", "running", "error"):
            status = build_module_gate_status(
                snapshot,
                pipeline_state=pipeline_state,
                manual_toc_ready=True,
                manual_toc_summary={},
            )
            self.assertEqual(status.structure_state, pipeline_state)
            self.assertFalse(bool(status.export_ready_test))
            self.assertFalse(bool(status.export_ready_real))

        done_status = build_module_gate_status(
            snapshot,
            pipeline_state="done",
            manual_toc_ready=True,
            manual_toc_summary={},
        )
        self.assertEqual(done_status.structure_state, "ready")
        self.assertTrue(bool(done_status.export_ready_test))
        self.assertTrue(bool(done_status.export_ready_real))

    def test_stage1_summaries_are_carried_into_status(self):
        snapshot = self._snapshot()
        status = build_module_gate_status(
            snapshot,
            pipeline_state="done",
            manual_toc_ready=True,
            manual_toc_summary={},
        )
        self.assertEqual(
            status.toc_role_summary,
            dict(snapshot.toc_result.evidence.get("toc_role_summary") or {}),
        )
        self.assertEqual(
            status.heading_review_summary,
            dict(snapshot.toc_result.diagnostics.get("heading_review_summary") or {}),
        )
        self.assertEqual(
            status.chapter_source_summary,
            dict(snapshot.toc_result.diagnostics.get("chapter_source_summary") or {}),
        )
        self.assertEqual(
            status.visual_toc_conflict_count,
            int((snapshot.toc_result.diagnostics.get("chapter_meta") or {}).get("visual_toc_conflict_count") or 0),
        )
        self.assertEqual(
            status.toc_alignment_summary,
            dict((snapshot.toc_result.diagnostics.get("chapter_meta") or {}).get("toc_alignment_summary") or {}),
        )
        self.assertEqual(
            status.toc_semantic_summary,
            dict((snapshot.toc_result.diagnostics.get("chapter_meta") or {}).get("toc_semantic_summary") or {}),
        )
        self.assertEqual(
            status.container_titles,
            list(snapshot.toc_result.diagnostics.get("container_titles") or []),
        )
        self.assertEqual(
            status.post_body_titles,
            list(snapshot.toc_result.diagnostics.get("post_body_titles") or []),
        )
        self.assertEqual(
            status.back_matter_titles,
            list(snapshot.toc_result.diagnostics.get("back_matter_titles") or []),
        )

    def test_stage3_summaries_are_carried_into_status(self):
        snapshot = self._snapshot()
        status = build_module_gate_status(
            snapshot,
            pipeline_state="done",
            manual_toc_ready=True,
            manual_toc_summary={},
        )
        split_evidence = dict(snapshot.split_result.evidence or {})
        split_region_summary = dict(split_evidence.get("region_summary") or {})
        split_item_summary = dict(split_evidence.get("item_summary") or {})
        self.assertEqual(
            status.chapter_binding_summary,
            dict(split_region_summary.get("chapter_binding_summary") or {}),
        )
        self.assertEqual(
            status.note_capture_summary,
            dict(split_item_summary.get("note_capture_summary") or {}),
        )
        self.assertEqual(
            status.footnote_synthesis_summary,
            dict(split_item_summary.get("footnote_synthesis_summary") or {}),
        )

    def test_stage4_summaries_are_carried_into_status(self):
        snapshot = self._snapshot()
        status = build_module_gate_status(
            snapshot,
            pipeline_state="done",
            manual_toc_ready=True,
            manual_toc_summary={},
        )
        link_evidence = dict(snapshot.link_result.evidence or {})
        self.assertEqual(
            status.chapter_link_contract_summary,
            dict(link_evidence.get("chapter_link_contract_summary") or {}),
        )
        self.assertEqual(
            status.book_endnote_stream_summary,
            dict(link_evidence.get("book_endnote_stream_summary") or {}),
        )

    def test_stage5_freeze_note_summary_is_carried_into_status(self):
        snapshot = self._snapshot()
        status = build_module_gate_status(
            snapshot,
            pipeline_state="done",
            manual_toc_ready=True,
            manual_toc_summary={},
        )
        freeze_summary = dict(snapshot.freeze_result.evidence.get("freeze_summary") or {})
        self.assertEqual(
            status.freeze_note_unit_summary,
            {
                "chapter_view_note_unit_count": int(freeze_summary.get("chapter_view_note_unit_count") or 0),
                "owner_fallback_note_unit_count": int(freeze_summary.get("owner_fallback_note_unit_count") or 0),
                "unresolved_note_item_count": int(freeze_summary.get("unresolved_note_item_count") or 0),
                "unresolved_note_item_ids_preview": list(freeze_summary.get("unresolved_note_item_ids_preview") or [])[:24],
            },
        )

    def test_stage6_merge_issue_diagnostics_are_carried_into_status(self):
        snapshot = self._snapshot()
        status = build_module_gate_status(
            snapshot,
            pipeline_state="done",
            manual_toc_ready=True,
            manual_toc_summary={},
        )
        merge_diagnostics = dict(snapshot.merge_result.diagnostics or {})
        raw_counts = dict(merge_diagnostics.get("chapter_issue_counts") or {})
        self.assertEqual(
            status.chapter_issue_counts,
            {
                "chapter_issue_count": int(raw_counts.get("chapter_issue_count") or 0),
                "frozen_ref_leak_chapter_count": int(raw_counts.get("frozen_ref_leak_chapter_count") or 0),
                "raw_marker_leak_chapter_count": int(raw_counts.get("raw_marker_leak_chapter_count") or 0),
                "local_ref_contract_broken_chapter_count": int(
                    raw_counts.get("local_ref_contract_broken_chapter_count") or 0
                ),
            },
        )
        self.assertEqual(
            status.chapter_issue_summary,
            [dict(row or {}) for row in list(merge_diagnostics.get("chapter_issue_summary") or []) if isinstance(row, dict)][
                :24
            ],
        )


if __name__ == "__main__":
    unittest.main()

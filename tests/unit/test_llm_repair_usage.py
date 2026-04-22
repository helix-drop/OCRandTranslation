from __future__ import annotations

import unittest
from unittest.mock import patch

from FNM_RE.llm_repair import _build_cluster_page_contexts, request_llm_repair_actions, run_llm_repair


class _RepoStub:
    def __init__(self):
        self.saved_overrides = []

    def list_fnm_chapters(self, _doc_id):
        return [{"chapter_id": "ch-1", "title": "Chapter 1", "start_page": 1, "end_page": 10}]

    def list_fnm_note_items(self, _doc_id):
        return [
            {
                "note_item_id": "n-1",
                "chapter_id": "ch-1",
                "region_id": "r-1",
                "marker": "1",
                "normalized_marker": "1",
                "page_no": 2,
                "source_text": "note one",
            }
        ]

    def list_fnm_body_anchors(self, _doc_id):
        return []

    def list_fnm_note_links(self, _doc_id):
        return [
            {
                "link_id": "L-1",
                "chapter_id": "ch-1",
                "region_id": "r-1",
                "note_kind": "endnote",
                "status": "orphan_note",
                "note_item_id": "n-1",
                "anchor_id": "",
                "marker": "1",
            }
        ]

    def clear_fnm_review_overrides(self, _doc_id, scope=""):
        return None

    def save_fnm_review_override(self, _doc_id, _scope, _record_id, _payload):
        self.saved_overrides.append((_scope, _record_id, dict(_payload or {})))
        return None


class LlmRepairUsageSummaryTest(unittest.TestCase):
    def test_build_cluster_page_contexts_includes_file_idx_and_pdf_path(self):
        class _PageRepo:
            def load_pages(self, _doc_id):
                return [
                    {
                        "bookPage": 2,
                        "fileIdx": 7,
                        "markdown": "page excerpt",
                    }
                ]

        cluster = {
            "page_start": 2,
            "page_end": 2,
            "unmatched_note_items": [{"page_no": 2}],
            "unmatched_anchors": [],
        }
        with (
            patch("FNM_RE.llm_repair.get_pdf_path", return_value="/tmp/book.pdf"),
            patch("FNM_RE.llm_repair.render_pdf_page", return_value=b"fake-image"),
        ):
            contexts = _build_cluster_page_contexts("doc-1", cluster, repo=_PageRepo())

        self.assertEqual(contexts[0]["page_no"], 2)
        self.assertEqual(contexts[0]["file_idx"], 7)
        self.assertEqual(contexts[0]["source_pdf_path"], "/tmp/book.pdf")
        self.assertIn("data:image/png;base64,", contexts[0]["image_url"])

    def test_build_cluster_page_contexts_expands_cross_page_footnote_window(self):
        class _PageRepo:
            def load_pages(self, _doc_id):
                return [
                    {"bookPage": 11, "fileIdx": 10, "markdown": {"text": "page 11 excerpt"}},
                    {"bookPage": 12, "fileIdx": 11, "markdown": {"text": "page 12 excerpt"}},
                    {"bookPage": 13, "fileIdx": 12, "markdown": {"text": "page 13 excerpt"}},
                    {"bookPage": 14, "fileIdx": 13, "markdown": {"text": "page 14 excerpt"}},
                    {"bookPage": 15, "fileIdx": 14, "markdown": {"text": "page 15 excerpt"}},
                ]

        cluster = {
            "note_system": "footnote",
            "page_start": 12,
            "page_end": 14,
            "unmatched_note_items": [{"page_no": 14}],
            "unmatched_anchors": [{"page_no": 12}],
            "rebind_candidates": [
                {
                    "note_item_id": "n-1",
                    "note_page_no": 14,
                    "anchor_page_no": 12,
                    "current_anchor_synthetic": True,
                }
            ],
        }
        with (
            patch("FNM_RE.llm_repair.get_pdf_path", return_value="/tmp/book.pdf"),
            patch("FNM_RE.llm_repair.render_pdf_page", return_value=b""),
        ):
            contexts = _build_cluster_page_contexts("doc-1", cluster, repo=_PageRepo())

        self.assertEqual([row["page_no"] for row in contexts], [11, 12, 13, 14, 15])
        self.assertEqual([row["file_idx"] for row in contexts], [10, 11, 12, 13, 14])

    def test_request_llm_repair_actions_returns_trace_payload(self):
        response = type(
            "_Resp",
            (),
            {
                "usage": type("_Usage", (), {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52})(),
                "choices": [type("_Choice", (), {"message": type("_Msg", (), {"content": "[]"})()})()],
            },
        )()

        fake_client = type(
            "_Client",
            (),
            {
                "chat": type(
                    "_Chat",
                    (),
                    {
                        "completions": type("_Completions", (), {"create": staticmethod(lambda **_kwargs: response)})()
                    },
                )()
            },
        )()

        cluster = {
            "cluster_id": "ch-1:r-1:endnote",
            "chapter_title": "Chapter 1",
            "note_system": "endnote",
            "page_start": 2,
            "page_end": 3,
            "matched_examples": [],
            "unmatched_note_items": [
                {"note_item_id": "n-1", "marker": "1", "page_no": 2, "source_text": "note one"}
            ],
            "unmatched_anchors": [],
            "page_contexts": [
                {
                    "page_no": 2,
                    "file_idx": 1,
                    "source_pdf_path": "/tmp/book.pdf",
                    "ocr_excerpt": "page excerpt",
                    "image_url": "data:image/png;base64,ZmFrZQ==",
                }
            ],
            "chapter_body_text": "body excerpt",
        }
        with (
            patch("FNM_RE.llm_repair._resolve_qwen_repair_model_args", return_value={"api_key": "k", "base_url": "https://example.invalid/v1", "model_id": "qwen3.5-plus", "provider": "qwen"}),
            patch("FNM_RE.llm_repair.OpenAI", return_value=fake_client),
        ):
            result = request_llm_repair_actions(cluster, doc_id="doc-1", slug="book-1")

        trace = result["llm_trace"]
        self.assertEqual(trace["stage"], "llm_repair.cluster_request")
        self.assertIn("你是 FNM 注释修补助手", trace["request_prompt"]["system"])
        self.assertIn("/no_think", trace["request_prompt"]["user"])
        self.assertEqual(trace["response_raw_text"], "[]")
        self.assertEqual(trace["request_content"]["page_contexts"][0]["page_no"], 2)
        self.assertEqual(trace["request_content"]["page_contexts"][0]["file_idx"], 1)
        self.assertEqual(trace["request_content"]["page_contexts"][0]["source_pdf_path"], "/tmp/book.pdf")
        self.assertNotIn("base64", str(trace["request_content"]))
        self.assertEqual(trace["derived_truth"]["parsed_actions"], [])

    def test_run_llm_repair_returns_usage_summary(self):
        repo = _RepoStub()
        with (
            patch("FNM_RE.llm_repair._build_cluster_page_contexts", return_value=[]),
            patch("FNM_RE.llm_repair._build_chapter_body_text", return_value=("", [])),
            patch(
                "FNM_RE.llm_repair.request_llm_repair_actions",
                return_value={
                    "actions": [],
                    "request_metrics": {"cluster_id": "ch-1:r-1:endnote"},
                    "usage_event": {
                        "stage": "llm_repair.cluster_request",
                        "provider": "qwen",
                        "model_id": "qwen-plus",
                        "request_count": 1,
                        "prompt_tokens": 30,
                        "completion_tokens": 12,
                        "total_tokens": 42,
                        "doc_id": "doc-1",
                        "slug": "book-1",
                        "context": {"cluster_id": "ch-1:r-1:endnote"},
                    },
                    "llm_trace": {
                        "stage": "llm_repair.cluster_request",
                        "reason_for_request": "cluster unresolved repair",
                        "request_prompt": {"system": "sys", "user": "user"},
                        "request_content": {"page_contexts": []},
                        "response_raw_text": "[]",
                        "response_parsed": [],
                        "derived_truth": {"parsed_actions": []},
                    },
                },
            ),
        ):
            result = run_llm_repair("doc-1", repo=repo, slug="book-1", auto_apply=False)

        self.assertEqual(result["cluster_count"], 1)
        self.assertEqual(len(result["usage_events"]), 1)
        summary = result["usage_summary"]
        self.assertEqual(summary["total"]["request_count"], 1)
        self.assertEqual(summary["total"]["prompt_tokens"], 30)
        self.assertEqual(summary["total"]["completion_tokens"], 12)
        self.assertEqual(summary["total"]["total_tokens"], 42)
        self.assertEqual(
            summary["by_stage"]["llm_repair.cluster_request"]["total_tokens"],
            42,
        )
        self.assertEqual(len(result["llm_traces"]), 1)
        self.assertEqual(result["llm_traces"][0]["stage"], "llm_repair.cluster_request")
        self.assertEqual(result["llm_traces"][0]["derived_truth"]["auto_selected_actions"], [])
        self.assertEqual(result["llm_traces"][0]["derived_truth"]["auto_applied_actions"], [])

    def test_run_llm_repair_can_rebind_currently_matched_link(self):
        class _RebindRepo(_RepoStub):
            def list_fnm_note_items(self, _doc_id):
                return [
                    {
                        "note_item_id": "n-1",
                        "chapter_id": "ch-1",
                        "region_id": "r-1",
                        "marker": "65",
                        "normalized_marker": "65",
                        "page_no": 10,
                        "source_text": "note 65",
                    }
                ]

            def list_fnm_body_anchors(self, _doc_id):
                return [
                    {
                        "anchor_id": "a-explicit",
                        "chapter_id": "ch-1",
                        "page_no": 10,
                        "normalized_marker": "4",
                        "source_marker": "4",
                        "source_text": "broken explicit anchor",
                        "synthetic": False,
                    },
                    {
                        "anchor_id": "synthetic-footnote-1",
                        "chapter_id": "ch-1",
                        "page_no": 10,
                        "normalized_marker": "65",
                        "source_marker": "65",
                        "source_text": "synthetic anchor",
                        "synthetic": True,
                    },
                ]

            def list_fnm_note_links(self, _doc_id):
                return [
                    {
                        "link_id": "L-orphan",
                        "chapter_id": "ch-1",
                        "region_id": "",
                        "note_kind": "footnote",
                        "status": "orphan_anchor",
                        "note_item_id": "",
                        "anchor_id": "a-explicit",
                        "marker": "4",
                    },
                    {
                        "link_id": "L-match",
                        "chapter_id": "ch-1",
                        "region_id": "r-1",
                        "note_kind": "footnote",
                        "status": "matched",
                        "note_item_id": "n-1",
                        "anchor_id": "synthetic-footnote-1",
                        "marker": "65",
                    },
                ]

        repo = _RebindRepo()
        with (
            patch("FNM_RE.llm_repair._build_cluster_page_contexts", return_value=[]),
            patch("FNM_RE.llm_repair._build_chapter_body_text", return_value=("", [])),
            patch(
                "FNM_RE.llm_repair.request_llm_repair_actions",
                return_value={
                    "actions": [
                        {
                            "action": "match",
                            "note_item_id": "n-1",
                            "anchor_id": "a-explicit",
                            "confidence": 0.95,
                            "reason": "visual rebind",
                        }
                    ],
                    "request_metrics": {"cluster_id": "ch-1:r-1:footnote"},
                    "usage_event": {},
                    "llm_trace": {
                        "stage": "llm_repair.cluster_request",
                        "reason_for_request": "cluster unresolved repair",
                        "request_prompt": {"system": "sys", "user": "user"},
                        "request_content": {"page_contexts": []},
                        "response_raw_text": "[]",
                        "response_parsed": [],
                        "derived_truth": {"parsed_actions": []},
                    },
                },
            ),
        ):
            run_llm_repair("doc-1", repo=repo, slug="book-1", auto_apply=True)

        self.assertIn(
            ("link", "L-match", {"action": "match", "note_item_id": "n-1", "anchor_id": "a-explicit"}),
            repo.saved_overrides,
        )

    def test_run_llm_repair_can_auto_apply_synthesize_note_item(self):
        class _NoteItemRepo(_RepoStub):
            def list_fnm_note_items(self, _doc_id):
                return []

            def list_fnm_body_anchors(self, _doc_id):
                return [
                    {
                        "anchor_id": "a-1",
                        "chapter_id": "ch-1",
                        "page_no": 10,
                        "normalized_marker": "1",
                        "source_marker": "1",
                        "source_text": "body marker",
                        "synthetic": False,
                    }
                ]

            def list_fnm_note_links(self, _doc_id):
                return [
                    {
                        "link_id": "L-1",
                        "chapter_id": "ch-1",
                        "region_id": "",
                        "note_kind": "endnote",
                        "status": "orphan_anchor",
                        "note_item_id": "",
                        "anchor_id": "a-1",
                        "marker": "1",
                    }
                ]

        repo = _NoteItemRepo()
        with (
            patch("FNM_RE.llm_repair._build_cluster_page_contexts", return_value=[{"page_no": 10, "ocr_excerpt": "page excerpt"}]),
            patch("FNM_RE.llm_repair._build_chapter_body_text", return_value=("", [])),
            patch(
                "FNM_RE.llm_repair.request_llm_repair_actions",
                return_value={
                    "actions": [
                        {
                            "action": "synthesize_note_item",
                            "anchor_id": "a-1",
                            "marker": "1",
                            "note_text": "Visible note text from screenshot.",
                            "confidence": 0.97,
                            "reason": "same-page note visible",
                        }
                    ],
                    "request_metrics": {"cluster_id": "ch-1:ch-1:endnote"},
                    "usage_event": {},
                    "llm_trace": {
                        "stage": "llm_repair.cluster_request",
                        "reason_for_request": "cluster unresolved repair",
                        "request_prompt": {"system": "sys", "user": "user"},
                        "request_content": {"page_contexts": []},
                        "response_raw_text": "[]",
                        "response_parsed": [],
                        "derived_truth": {"parsed_actions": []},
                    },
                },
            ),
        ):
            run_llm_repair("doc-1", repo=repo, slug="book-1", auto_apply=True)

        note_item_rows = [row for row in repo.saved_overrides if row[0] == "note_item"]
        self.assertEqual(len(note_item_rows), 1)
        scope, record_id, payload = note_item_rows[0]
        self.assertEqual(scope, "note_item")
        self.assertEqual(record_id, "llm-note-a-1")
        self.assertEqual(payload["marker"], "1")
        self.assertEqual(payload["note_kind"], "endnote")
        self.assertEqual(payload["chapter_id"], "ch-1")


if __name__ == "__main__":
    unittest.main()

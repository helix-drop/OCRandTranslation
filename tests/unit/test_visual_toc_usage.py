from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.visual_toc.shared import _attach_usage_payload
from pipeline.visual_toc.vision import _call_vision_json, _classify_toc_candidates


class VisualTocUsageTest(unittest.TestCase):
    def test_call_vision_json_returns_parsed_and_usage_event(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3, total_tokens=15),
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_kwargs: response),
            ),
        )
        spec = SimpleNamespace(
            api_key="k",
            base_url="https://example.com",
            provider="qwen",
            model_id="qwen-vl-plus",
        )
        with patch("pipeline.visual_toc.vision.OpenAI", return_value=fake_client):
            result = _call_vision_json(
                spec,
                prompt="ping",
                images=[],
                stage="visual_toc.preflight",
                usage_doc_id="doc-1",
                usage_slug="book-1",
                usage_context={"file_idx": 7, "note": "x" * 140},
            )

        self.assertEqual(result["parsed"]["ok"], True)
        event = result["usage_event"]
        self.assertEqual(event["stage"], "visual_toc.preflight")
        self.assertEqual(event["provider"], "qwen")
        self.assertEqual(event["model_id"], "qwen-vl-plus")
        self.assertEqual(event["request_count"], 1)
        self.assertEqual(event["prompt_tokens"], 12)
        self.assertEqual(event["completion_tokens"], 3)
        self.assertEqual(event["total_tokens"], 15)
        self.assertEqual(event["doc_id"], "doc-1")
        self.assertEqual(event["slug"], "book-1")
        self.assertEqual(event["context"]["file_idx"], 7)
        self.assertTrue(str(event["context"]["note"]).endswith("..."))

    def test_classify_toc_candidates_collects_usage_events(self):
        usage_events: list[dict] = []
        classify_payload = [
            {"file_idx": 1, "label": "toc_start", "score": 0.91, "header_hint": "Table"},
            {"file_idx": 2, "label": "toc_continue", "score": 0.88, "header_hint": ""},
        ]
        with (
            patch("pipeline.visual_toc.vision.render_pdf_page", return_value=b"fake"),
            patch("pipeline.visual_toc.vision._bytes_to_data_url", return_value="data:image/png;base64,ZmFrZQ=="),
            patch(
                "pipeline.visual_toc.vision._call_vision_json",
                return_value={
                    "parsed": classify_payload,
                    "usage_event": {
                        "stage": "visual_toc.classify_candidates",
                        "provider": "qwen",
                        "model_id": "qwen-vl-plus",
                        "request_count": 1,
                        "prompt_tokens": 20,
                        "completion_tokens": 6,
                        "total_tokens": 26,
                        "doc_id": "doc-2",
                        "slug": "",
                        "context": {"batch_start_file_idx": 1, "batch_end_file_idx": 2},
                    },
                },
            ),
        ):
            rows = _classify_toc_candidates(
                SimpleNamespace(provider="qwen", model_id="qwen-vl-plus"),
                "/tmp/fake.pdf",
                [1, 2],
                usage_events=usage_events,
                doc_id="doc-2",
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["label"], "toc_start")
        self.assertEqual(len(usage_events), 1)
        self.assertEqual(usage_events[0]["total_tokens"], 26)

    def test_attach_usage_payload_fills_missing_stage_with_zero(self):
        payload = _attach_usage_payload(
            {"status": "ready"},
            [
                {
                    "stage": "visual_toc.preflight",
                    "provider": "qwen",
                    "model_id": "qwen-vl-plus",
                    "request_count": 1,
                    "prompt_tokens": 11,
                    "completion_tokens": 4,
                    "total_tokens": 15,
                }
            ],
        )
        by_stage = payload["usage_summary"]["by_stage"]
        self.assertEqual(by_stage["visual_toc.preflight"]["total_tokens"], 15)
        self.assertEqual(by_stage["visual_toc.classify_candidates"]["total_tokens"], 0)
        self.assertEqual(by_stage["visual_toc.extract_page_items"]["total_tokens"], 0)
        self.assertEqual(by_stage["visual_toc.manual_input_extract"]["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()

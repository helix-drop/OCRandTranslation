#!/usr/bin/env python3
"""自动视觉目录纯逻辑测试。"""

import json
import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.visual_toc import VisionModelRequestError, generate_auto_visual_toc_for_doc
from pipeline.visual_toc.manual_inputs import (
    _augment_manual_toc_organization_with_ocr_containers,
    _extract_manual_toc_outline_nodes_from_pdf_text,
    _merge_manual_toc_organization_nodes,
)
from pipeline.visual_toc.organization import (
    _apply_printed_page_lookup,
    _annotate_visual_toc_organization,
    _default_endnotes_summary,
    _filter_resolved_visual_toc_anomalies,
    _normalize_visual_toc_role_hint,
    _should_prefer_manual_outline_nodes,
    filter_visual_toc_items,
    map_visual_items_to_link_targets,
)
from pipeline.visual_toc.scan_plan import (
    _assess_text_layer_quality,
    _build_coverage_quality_summary,
    _build_local_scan_plan,
    _build_visual_scan_plan,
    _choose_local_toc_scan_indices,
    _classify_header_hint,
    _expand_candidate_indices_for_retry,
    _score_local_toc_page,
    _vision_probe_passed,
    choose_toc_candidate_indices,
    pick_best_toc_cluster,
)
from pipeline.visual_toc.vision import (
    _call_vision_json,
    _extract_visual_toc_organization_bundle_from_images,
)


class VisualTocLogicTest(unittest.TestCase):
    def test_choose_toc_candidate_indices_scans_front_and_back(self):
        front, back = choose_toc_candidate_indices(120)

        self.assertGreaterEqual(len(front), 8)
        self.assertGreaterEqual(len(back), 8)
        self.assertEqual(front[0], 0)
        self.assertEqual(back[-1], 119)
        self.assertLess(front[-1], back[0])

    def test_pick_best_toc_cluster_prefers_higher_scoring_back_cluster(self):
        best = pick_best_toc_cluster(
            [
                {"file_idx": 2, "label": "toc_start", "score": 0.61},
                {"file_idx": 3, "label": "toc_continue", "score": 0.67},
            ],
            [
                {"file_idx": 180, "label": "toc_start", "score": 0.89},
                {"file_idx": 181, "label": "toc_continue", "score": 0.92},
                {"file_idx": 182, "label": "toc_continue", "score": 0.88},
            ],
        )

        self.assertEqual([item["file_idx"] for item in best], [180, 181, 182])

    def test_pick_best_toc_cluster_prefers_explicit_table_header_over_longer_index_cluster(self):
        best = pick_best_toc_cluster(
            [],
            [
                {"file_idx": 348, "label": "toc_start", "score": 0.95, "header_hint": "Indices"},
                {"file_idx": 349, "label": "toc_continue", "score": 0.90, "header_hint": "Index des notions"},
                {"file_idx": 350, "label": "toc_continue", "score": 0.98, "header_hint": ""},
                {"file_idx": 351, "label": "toc_continue", "score": 0.92, "header_hint": ""},
                {"file_idx": 352, "label": "toc_continue", "score": 0.91, "header_hint": ""},
                {"file_idx": 353, "label": "toc_continue", "score": 0.89, "header_hint": ""},
                {"file_idx": 363, "label": "toc_start", "score": 0.90, "header_hint": "Table"},
                {"file_idx": 364, "label": "toc_continue", "score": 0.90, "header_hint": ""},
                {"file_idx": 365, "label": "toc_continue", "score": 0.90, "header_hint": ""},
                {"file_idx": 366, "label": "toc_continue", "score": 0.95, "header_hint": ""},
            ],
        )

        self.assertEqual([item["file_idx"] for item in best], [363, 364, 365, 366])

    def test_classify_header_hint_supports_multilingual_toc_titles(self):
        self.assertEqual(_classify_header_hint("Table"), "toc")
        self.assertEqual(_classify_header_hint("Table des matières"), "toc")
        self.assertEqual(_classify_header_hint("Sommaire"), "toc")
        self.assertEqual(_classify_header_hint("Contents"), "toc")
        self.assertEqual(_classify_header_hint("目录"), "toc")
        self.assertEqual(_classify_header_hint("目次"), "toc")
        self.assertEqual(_classify_header_hint("Índice"), "toc")
        self.assertEqual(_classify_header_hint("Indice"), "toc")
        self.assertEqual(_classify_header_hint("Sumário"), "toc")
        self.assertEqual(_classify_header_hint("Содержание"), "toc")

    def test_classify_header_hint_keeps_index_trap_and_notebook_sections_out(self):
        self.assertEqual(_classify_header_hint("Index"), "index")
        self.assertEqual(_classify_header_hint("Indices"), "index")
        self.assertEqual(_classify_header_hint("Index des notions"), "index")
        self.assertEqual(_classify_header_hint("Notes"), "other")
        self.assertEqual(_classify_header_hint("Bibliography"), "other")

    def test_score_local_toc_page_distinguishes_indice_from_index(self):
        toc_score = _score_local_toc_page(
            {
                "file_idx": 12,
                "header_hint": "Índice",
                "text_excerpt": "Índice\nCapítulo 1 .... 7\nCapítulo 2 .... 19",
                "link_count": 0,
                "dot_leader_lines": 2,
                "numbered_lines": 2,
            }
        )
        index_score = _score_local_toc_page(
            {
                "file_idx": 340,
                "header_hint": "Index",
                "text_excerpt": "Index of names\nFoucault .... 399",
                "link_count": 0,
                "dot_leader_lines": 1,
                "numbered_lines": 1,
            }
        )

        self.assertGreater(toc_score, 0)
        self.assertLess(index_score, 0)

    def test_choose_local_toc_scan_indices_prefers_table_cluster_and_caps_pages(self):
        features = [
            {
                "file_idx": 348,
                "header_hint": "Indices",
                "text_excerpt": "Indices\nIndex des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 349,
                "header_hint": "Index des notions",
                "text_excerpt": "Index des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 350,
                "header_hint": "",
                "text_excerpt": "Index des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 351,
                "header_hint": "",
                "text_excerpt": "Index des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 352,
                "header_hint": "",
                "text_excerpt": "Index des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 353,
                "header_hint": "",
                "text_excerpt": "Index des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 362,
                "header_hint": "Table",
                "text_excerpt": "Table\nCours, année 1978-1979 .... 1",
                "link_count": 0,
                "dot_leader_lines": 5,
                "numbered_lines": 5,
            },
            {
                "file_idx": 363,
                "header_hint": "",
                "text_excerpt": "Leçon du 10 janvier 1979 .... 3",
                "link_count": 0,
                "dot_leader_lines": 5,
                "numbered_lines": 5,
            },
            {
                "file_idx": 364,
                "header_hint": "Table",
                "text_excerpt": "Table\nLeçon du 24 janvier 1979 .... 67",
                "link_count": 0,
                "dot_leader_lines": 5,
                "numbered_lines": 5,
            },
            {
                "file_idx": 365,
                "header_hint": "",
                "text_excerpt": "Leçon du 7 février 1979 .... 119",
                "link_count": 0,
                "dot_leader_lines": 5,
                "numbered_lines": 5,
            },
            {
                "file_idx": 366,
                "header_hint": "Table",
                "text_excerpt": "Table\nRésumé du cours .... 323",
                "link_count": 0,
                "dot_leader_lines": 5,
                "numbered_lines": 5,
            },
        ]

        self.assertEqual(_choose_local_toc_scan_indices(features, max_pages=6), [361, 362, 363, 364, 365, 366])

    def test_choose_local_toc_scan_indices_bridges_low_signal_pages_between_table_headers(self):
        features = [
            {
                "file_idx": 362,
                "header_hint": "Table",
                "text_excerpt": "Table",
                "link_count": 0,
                "dot_leader_lines": 0,
                "numbered_lines": 0,
            },
            {
                "file_idx": 363,
                "header_hint": "352",
                "text_excerpt": "352\nNaissance de la biopolitique",
                "link_count": 0,
                "dot_leader_lines": 0,
                "numbered_lines": 0,
            },
            {
                "file_idx": 364,
                "header_hint": "Table",
                "text_excerpt": "Table",
                "link_count": 0,
                "dot_leader_lines": 0,
                "numbered_lines": 0,
            },
            {
                "file_idx": 365,
                "header_hint": "354",
                "text_excerpt": "354\nNaissance de la biopolitique",
                "link_count": 0,
                "dot_leader_lines": 0,
                "numbered_lines": 0,
            },
            {
                "file_idx": 366,
                "header_hint": "Table",
                "text_excerpt": "Table",
                "link_count": 0,
                "dot_leader_lines": 0,
                "numbered_lines": 0,
            },
        ]

        self.assertEqual(_choose_local_toc_scan_indices(features, max_pages=6), [361, 362, 363, 364, 365, 366])

    def test_assess_text_layer_quality_switches_to_degraded_when_control_chars_high(self):
        features = [
            {"file_idx": file_idx, "text_excerpt": ("\x01\x02\x03目录..." * 30)}
            for file_idx in range(64)
        ]

        quality = _assess_text_layer_quality(features, total_pages=620)
        self.assertEqual(quality["mode"], "degraded")
        self.assertEqual(quality["reason_code"], "degraded_text_layer")
        self.assertGreaterEqual(quality["control_char_ratio"], 0.12)

    def test_build_visual_scan_plan_uses_front6_back12_for_degraded_mode(self):
        features = [
            {"file_idx": file_idx, "text_excerpt": ("\x01\x02\x03目录..." * 30)}
            for file_idx in range(80)
        ]

        plan = _build_visual_scan_plan(features, total_pages=620, max_pages=24)
        self.assertEqual(plan["mode"], "degraded")
        self.assertEqual(plan["candidate_source"], "degraded_window_expand")
        self.assertEqual(plan["candidate_indices"], [0, 1, 2, 3, 4, 5, 608, 609, 610, 611, 612, 613, 614, 615, 616, 617, 618, 619])
        self.assertEqual(plan["primary_run_pages"], plan["candidate_indices"])
        self.assertEqual(plan["context_pages"], [])
        self.assertEqual(plan["retry_indices"], [6, 607])
        self.assertEqual([row["selected_as"] for row in plan["run_summaries"]], ["primary_run", "secondary_run"])

    def test_expand_candidate_indices_for_retry_adds_neighbor_pages(self):
        retry_indices = _expand_candidate_indices_for_retry(
            [0, 1, 2, 3, 36, 37, 38, 39],
            total_pages=40,
            radius=1,
            max_extra_pages=8,
        )
        self.assertEqual(retry_indices, [4, 35])

    def test_build_local_scan_plan_exposes_multi_run_summaries(self):
        features = [
            {
                "file_idx": 10,
                "header_hint": "Table",
                "text_excerpt": "Table\nPart I .... 1",
                "link_count": 0,
                "dot_leader_lines": 3,
                "numbered_lines": 2,
            },
            {
                "file_idx": 11,
                "header_hint": "",
                "text_excerpt": "Chapter One .... 9",
                "link_count": 0,
                "dot_leader_lines": 3,
                "numbered_lines": 2,
            },
            {
                "file_idx": 30,
                "header_hint": "Table",
                "text_excerpt": "Table\nPart II .... 101",
                "link_count": 0,
                "dot_leader_lines": 3,
                "numbered_lines": 2,
            },
            {
                "file_idx": 31,
                "header_hint": "",
                "text_excerpt": "Chapter Two .... 109",
                "link_count": 0,
                "dot_leader_lines": 3,
                "numbered_lines": 2,
            },
        ]

        plan = _build_local_scan_plan(page_features=features, total_pages=80, max_pages=24)
        self.assertEqual(plan["candidate_source"], "local_multi_run")
        self.assertTrue(set([10, 11, 30, 31]).issubset(set(plan["primary_run_pages"])))
        selected_as = [row["selected_as"] for row in plan["run_summaries"]]
        self.assertIn("primary_run", selected_as)
        self.assertIn("secondary_run", selected_as)
        self.assertGreaterEqual(len(plan["candidate_indices"]), len(plan["primary_run_pages"]))

    def test_build_coverage_quality_summary_marks_partial_capture(self):
        summary = _build_coverage_quality_summary(
            resolved_items=[{"file_idx": 320}, {"file_idx": 321}],
            unresolved_item_count=0,
            selected_page_count=1,
            selected_run_count=1,
            total_pages=500,
        )
        self.assertEqual(summary["coverage_quality"], "partial")
        self.assertTrue(summary["suspected_partial_capture"])

    def test_generate_visual_toc_retry_failure_writes_structured_reason_code(self):
        class _RepoStub:
            def set_document_toc_for_source(self, *_args, **_kwargs):
                return None

            def set_document_toc_source_offset(self, *_args, **_kwargs):
                return None

        local_features = [
            {"file_idx": file_idx, "text_excerpt": ("\x01\x02\x03目录..." * 30)}
            for file_idx in range(64)
        ]
        classify_calls: list[list[int]] = []

        def _classify_stub(_spec, _pdf_path, page_indices, **_kwargs):
            classify_calls.append(list(page_indices))
            return [
                {"file_idx": file_idx, "label": "not_toc", "score": 0.01, "header_hint": ""}
                for file_idx in page_indices
            ]

        with patch("pipeline.visual_toc.runtime.os.path.exists", return_value=True), patch(
            "pipeline.visual_toc.runtime.SQLiteRepository",
            return_value=_RepoStub(),
        ), patch(
            "pipeline.visual_toc.vision.confirm_model_supports_vision",
            return_value=(True, "ok"),
        ), patch(
            "pipeline.visual_toc.runtime.load_toc_visual_manual_inputs",
            return_value={"mode": "", "pdf_path": "", "image_paths": [], "page_count": 0, "source_name": "", "files": []},
        ), patch(
            "pipeline.visual_toc.scan_plan._resolve_total_pages",
            return_value=40,
        ), patch(
            "pipeline.visual_toc.scan_plan._extract_local_toc_page_features",
            return_value=local_features,
        ), patch(
            "pipeline.visual_toc.vision._classify_toc_candidates",
            side_effect=_classify_stub,
        ), patch(
            "pipeline.visual_toc.runtime.update_doc_meta",
        ) as update_meta_mock:
            result = generate_auto_visual_toc_for_doc(
                "doc-test",
                pdf_path="/mock/path.pdf",
                model_spec=SimpleNamespace(model_id="mock-vision"),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(classify_calls), 2)
        self.assertEqual(classify_calls[0], [0, 1, 2, 3, 4, 5, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39])
        self.assertEqual(classify_calls[1], [6, 27])
        self.assertEqual(result["scan_mode"], "degraded")
        self.assertEqual(result["candidate_pdf_pages"], [1, 2, 3, 4, 5, 6, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40])
        self.assertEqual(result["retry_pdf_pages"], [7, 28])
        self.assertEqual(result["coverage_quality"], "none")

        final_kwargs = update_meta_mock.call_args.kwargs
        self.assertEqual(final_kwargs["toc_visual_status"], "failed")
        self.assertIn(
            "degraded_text_layer/no_toc_cluster_after_retry",
            final_kwargs["toc_visual_message"],
        )
        self.assertIn(
            "degraded_text_layer/no_toc_cluster_after_retry",
            final_kwargs["toc_visual_progress_detail"],
        )

    def test_generate_visual_toc_prefers_manual_toc_pdf_over_pdf_page_scan(self):
        class _RepoStub:
            def set_document_toc_for_source(self, *_args, **_kwargs):
                return None

            def set_document_toc_source_offset(self, *_args, **_kwargs):
                return None

        extracted_calls = []

        def _resolve_total_pages(path: str) -> int:
            return 2 if path.endswith("toc_visual_source.pdf") else 400

        def _extract_manual_items(_spec, toc_pdf_path: str, file_idx: int, **_kwargs):
            extracted_calls.append((toc_pdf_path, file_idx))
            if file_idx == 0:
                return [{"title": "Introduction", "depth": 0, "printed_page": 1, "visual_order": 1}]
            return [{"title": "Chapter 1", "depth": 0, "printed_page": 21, "visual_order": 1}]

        with (
            patch("pipeline.visual_toc.runtime.os.path.exists", return_value=True),
            patch("pipeline.visual_toc.runtime.SQLiteRepository", return_value=_RepoStub()),
            patch("pipeline.visual_toc.vision.confirm_model_supports_vision", return_value=(True, "ok")),
            patch("pipeline.visual_toc.runtime.load_toc_visual_manual_inputs", return_value={
                "mode": "manual_pdf",
                "pdf_path": "/mock/doc/toc_visual_source.pdf",
                "image_paths": [],
                "page_count": 2,
                "source_name": "目录.pdf",
            }),
            patch("pipeline.visual_toc.scan_plan._resolve_total_pages", side_effect=_resolve_total_pages),
            patch("pipeline.visual_toc.scan_plan._extract_local_toc_page_features") as feature_mock,
            patch("pipeline.visual_toc.vision._classify_toc_candidates") as classify_mock,
            patch("pipeline.visual_toc.vision._extract_visual_toc_page_items_from_pdf", side_effect=_extract_manual_items),
            patch("pipeline.visual_toc.vision.render_pdf_page", return_value=b"fake-image"),
            patch("pipeline.visual_toc.vision._bytes_to_data_url", return_value="data:image/png;base64,ZmFrZQ=="),
            patch(
                "pipeline.visual_toc.vision._extract_visual_toc_organization_bundle_from_images",
                return_value={"items": [], "endnotes_summary": _default_endnotes_summary()},
            ),
            patch("pipeline.visual_toc.organization._build_printed_page_lookup", return_value={1: 0, 21: 20}),
            patch("pipeline.visual_toc.runtime.extract_pdf_page_link_targets", return_value=[]),
            patch("pipeline.visual_toc.runtime.update_doc_meta"),
            patch("pipeline.visual_toc.runtime.save_auto_visual_toc_bundle_to_disk"),
            patch("pipeline.visual_toc.runtime.clear_auto_visual_toc_bundle_from_disk"),
        ):
            result = generate_auto_visual_toc_for_doc(
                "doc-test",
                pdf_path="/mock/source.pdf",
                model_spec=SimpleNamespace(model_id="mock-vision"),
            )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["scan_mode"], "manual_pdf")
        self.assertEqual(result["candidate_source"], "manual_toc_upload")
        self.assertEqual(result["manual_input_page_count"], 2)
        self.assertEqual(result["manual_input_source_name"], "目录.pdf")
        self.assertEqual(result["endnotes_summary"]["present"], False)
        self.assertEqual(extracted_calls, [
            ("/mock/doc/toc_visual_source.pdf", 0),
            ("/mock/doc/toc_visual_source.pdf", 1),
        ])
        feature_mock.assert_not_called()
        classify_mock.assert_not_called()

    def test_generate_visual_toc_manual_pdf_marks_ready_when_only_container_lacks_page_target(self):
        class _RepoStub:
            def set_document_toc_for_source(self, *_args, **_kwargs):
                return None

            def set_document_toc_source_offset(self, *_args, **_kwargs):
                return None

        manual_page_items = [
            {"title": "Part I", "depth": 0, "printed_page": None, "visual_order": 1, "role_hint": "container"},
            {"title": "Chapter 1", "depth": 1, "printed_page": 5, "visual_order": 2, "role_hint": "chapter", "parent_title": "Part I"},
        ]

        with (
            patch("pipeline.visual_toc.runtime.os.path.exists", return_value=True),
            patch("pipeline.visual_toc.runtime.SQLiteRepository", return_value=_RepoStub()),
            patch("pipeline.visual_toc.vision.confirm_model_supports_vision", return_value=(True, "ok")),
            patch("pipeline.visual_toc.runtime.load_toc_visual_manual_inputs", return_value={
                "mode": "manual_pdf",
                "pdf_path": "/mock/doc/toc_visual_source.pdf",
                "image_paths": [],
                "page_count": 1,
                "source_name": "目录.pdf",
            }),
            patch("pipeline.visual_toc.scan_plan._resolve_total_pages", side_effect=lambda path: 1 if path.endswith("toc_visual_source.pdf") else 300),
            patch("pipeline.visual_toc.vision._extract_visual_toc_page_items_from_pdf", return_value=manual_page_items),
            patch(
                "pipeline.visual_toc.vision._extract_visual_toc_organization_bundle_from_images",
                return_value={
                    "items": [],
                    "endnotes_summary": {
                        "present": True,
                        "container_title": "Notes",
                        "container_printed_page": 301,
                        "container_visual_order": 9,
                        "has_chapter_keyed_subentries_in_toc": False,
                        "subentry_pattern": None,
                    },
                },
            ),
            patch("pipeline.visual_toc.manual_inputs._extract_manual_toc_outline_nodes_from_pdf_text", return_value=[]),
            patch("pipeline.visual_toc.organization._build_printed_page_lookup", return_value={5: 4}),
            patch("pipeline.visual_toc.vision.render_pdf_page", return_value=b"fake-image"),
            patch("pipeline.visual_toc.vision._bytes_to_data_url", return_value="data:image/png;base64,ZmFrZQ=="),
            patch("pipeline.visual_toc.runtime.extract_pdf_page_link_targets", return_value=[]),
            patch("pipeline.visual_toc.runtime.update_doc_meta"),
            patch("pipeline.visual_toc.runtime.save_auto_visual_toc_bundle_to_disk") as save_bundle_mock,
            patch("pipeline.visual_toc.runtime.clear_auto_visual_toc_bundle_from_disk"),
        ):
            result = generate_auto_visual_toc_for_doc(
                "doc-test",
                pdf_path="/mock/source.pdf",
                model_spec=SimpleNamespace(model_id="mock-vision"),
            )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["unresolved_navigable_count"], 0)
        self.assertEqual(result["navigable_item_count"], 1)
        self.assertEqual(result["navigable_ready_count"], 1)
        self.assertEqual(result["endnotes_summary"]["container_title"], "Notes")
        saved_bundle = save_bundle_mock.call_args.args[1]
        self.assertEqual(saved_bundle["endnotes_summary"]["container_printed_page"], 301)

    def test_extract_visual_toc_organization_bundle_defaults_missing_endnotes_summary(self):
        with patch(
            "pipeline.visual_toc.vision._call_vision_json",
            return_value={
                "parsed": {"items": [{"title": "Chapter One", "depth": 0}]},
                "usage_event": {},
                "trace": {
                    "stage": "visual_toc.manual_input_extract",
                    "request_prompt": "prompt",
                    "request_content": {},
                    "response_raw_text": "{\"items\": [{\"title\": \"Chapter One\", \"depth\": 0}]}",
                },
            },
        ):
            bundle = _extract_visual_toc_organization_bundle_from_images(
                SimpleNamespace(model_id="mock-vision"),
                images=["data:image/png;base64,ZmFrZQ=="],
            )

        self.assertEqual(bundle["items"][0]["title"], "Chapter One")
        self.assertEqual(bundle["endnotes_summary"], _default_endnotes_summary())

    def test_call_vision_json_returns_trace_without_inline_base64(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5, total_tokens=17),
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"row_counts":[1,3,0,2],"supports_vision":true}'))],
        )

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: response,
                )
            )
        )

        with patch("pipeline.visual_toc.vision.OpenAI", return_value=fake_client):
            result = _call_vision_json(
                SimpleNamespace(api_key="k", base_url="https://example.invalid/v1", model_id="qwen3.5-plus", provider="qwen"),
                prompt="测试 prompt",
                images=[(3, "data:image/png;base64,ZmFrZQ==")],
                stage="visual_toc.preflight",
                usage_doc_id="doc-1",
                usage_slug="book-1",
                usage_context={"probe": "vision_preflight"},
                reason_for_request="视觉能力预检",
            )

        trace = result["trace"]
        self.assertEqual(trace["reason_for_request"], "视觉能力预检")
        self.assertEqual(trace["request_prompt"], "测试 prompt")
        self.assertEqual(trace["response_raw_text"], '{"row_counts":[1,3,0,2],"supports_vision":true}')
        self.assertEqual(trace["response_parsed"]["supports_vision"], True)
        self.assertEqual(trace["request_content"]["images"][0]["file_idx"], 3)
        self.assertEqual(
            trace["request_content"]["images"][0]["sha256"],
            hashlib.sha256(b"fake").hexdigest(),
        )
        self.assertNotIn("base64", json.dumps(trace["request_content"], ensure_ascii=False))

    def test_extract_visual_toc_organization_bundle_appends_trace_with_derived_truth(self):
        traces: list[dict] = []
        with patch(
            "pipeline.visual_toc.vision._call_vision_json",
            return_value={
                "parsed": {
                    "items": [
                        {"title": "Notes", "depth": 1, "visual_order": 1, "printed_page": 259, "role_hint": "endnotes"}
                    ],
                    "endnotes_summary": {
                        "present": True,
                        "container_title": "Notes",
                        "container_printed_page": 259,
                        "container_visual_order": 1,
                        "has_chapter_keyed_subentries_in_toc": False,
                        "subentry_pattern": None,
                    },
                },
                "usage_event": {},
                "trace": {
                    "stage": "visual_toc.manual_input_extract",
                    "request_prompt": "prompt",
                    "request_content": {},
                    "response_raw_text": "{}",
                },
            },
        ):
            bundle = _extract_visual_toc_organization_bundle_from_images(
                SimpleNamespace(model_id="mock-vision"),
                images=["data:image/png;base64,ZmFrZQ=="],
                usage_events=[],
                trace_events=traces,
            )

        self.assertTrue(bundle["endnotes_summary"]["present"])
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["derived_truth"]["items"][0]["title"], "Notes")
        self.assertEqual(traces[0]["derived_truth"]["endnotes_summary"]["container_printed_page"], 259)

    def test_generate_auto_visual_toc_infers_endnotes_summary_from_final_items_when_prompt_misses_it(self):
        manual_page_items = [
            {"title": "Epilogue", "depth": 0, "printed_page": 251, "visual_order": 1, "role_hint": "content"},
            {"title": "Notes", "depth": 0, "printed_page": 259, "visual_order": 2, "role_hint": "content"},
            {"title": "Note on Sources", "depth": 0, "printed_page": 287, "visual_order": 3, "role_hint": "back_matter"},
        ]

        class _RepoStub:
            def set_document_toc_for_source(self, *_args, **_kwargs):
                return None

            def set_document_toc_source_offset(self, *_args, **_kwargs):
                return None

        with (
            patch("pipeline.visual_toc.runtime.os.path.exists", return_value=True),
            patch("pipeline.visual_toc.runtime.SQLiteRepository", return_value=_RepoStub()),
            patch("pipeline.visual_toc.vision.confirm_model_supports_vision", return_value=(True, "ok")),
            patch("pipeline.visual_toc.runtime.load_toc_visual_manual_inputs", return_value={
                "mode": "manual_pdf",
                "pdf_path": "/mock/doc/toc_visual_source.pdf",
                "image_paths": [],
                "page_count": 1,
                "source_name": "目录.pdf",
            }),
            patch("pipeline.visual_toc.scan_plan._resolve_total_pages", side_effect=lambda path: 1 if path.endswith("toc_visual_source.pdf") else 400),
            patch("pipeline.visual_toc.vision._extract_visual_toc_page_items_from_pdf", return_value=manual_page_items),
            patch(
                "pipeline.visual_toc.vision._extract_visual_toc_organization_bundle_from_images",
                return_value={
                    "items": [
                        {"title": "Epilogue", "depth": 0, "visual_order": 1, "printed_page": 251, "role_hint": "post_body"},
                        {"title": "Notes", "depth": 1, "visual_order": 2, "printed_page": 259, "role_hint": "endnotes"},
                        {
                            "title": "Note on Sources",
                            "depth": 0,
                            "visual_order": 3,
                            "printed_page": 287,
                            "role_hint": "back_matter",
                        },
                    ]
                },
            ),
            patch("pipeline.visual_toc.manual_inputs._extract_manual_toc_outline_nodes_from_pdf_text", return_value=[]),
            patch("pipeline.visual_toc.organization._build_printed_page_lookup", return_value={251: 250, 259: 258, 287: 286}),
            patch("pipeline.visual_toc.vision.render_pdf_page", return_value=b"fake-image"),
            patch("pipeline.visual_toc.vision._bytes_to_data_url", return_value="data:image/png;base64,ZmFrZQ=="),
            patch("pipeline.visual_toc.runtime.extract_pdf_page_link_targets", return_value=[]),
            patch("pipeline.visual_toc.runtime.update_doc_meta"),
            patch("pipeline.visual_toc.runtime.save_auto_visual_toc_bundle_to_disk") as save_bundle_mock,
            patch("pipeline.visual_toc.runtime.clear_auto_visual_toc_bundle_from_disk"),
        ):
            result = generate_auto_visual_toc_for_doc(
                "doc-test",
                pdf_path="/mock/source.pdf",
                model_spec=SimpleNamespace(model_id="mock-vision"),
            )

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["endnotes_summary"]["present"])
        self.assertEqual(result["endnotes_summary"]["container_title"], "Notes")
        self.assertEqual(result["endnotes_summary"]["container_printed_page"], 259)
        saved_bundle = save_bundle_mock.call_args.args[1]
        self.assertEqual(saved_bundle["endnotes_summary"]["container_title"], "Notes")

    def test_generate_visual_toc_fails_fast_when_visual_call_returns_non_retryable_400(self):
        class _RepoStub:
            def set_document_toc_for_source(self, *_args, **_kwargs):
                return None

            def set_document_toc_source_offset(self, *_args, **_kwargs):
                return None

        with (
            patch("pipeline.visual_toc.runtime.os.path.exists", return_value=True),
            patch("pipeline.visual_toc.runtime.SQLiteRepository", return_value=_RepoStub()),
            patch("pipeline.visual_toc.vision.confirm_model_supports_vision", return_value=(True, "ok")),
            patch("pipeline.visual_toc.runtime.load_toc_visual_manual_inputs", return_value={"mode": ""}),
            patch("pipeline.visual_toc.scan_plan._resolve_total_pages", return_value=100),
            patch("pipeline.visual_toc.scan_plan._extract_local_toc_page_features", return_value=[{"file_idx": 0, "text_excerpt": "目录"}]),
            patch("pipeline.visual_toc.scan_plan._build_visual_scan_plan", return_value={
                "mode": "normal",
                "quality": {},
                "candidate_source": "test",
                "run_summaries": [],
                "candidate_indices": [0],
                "primary_run_pages": [0],
                "context_pages": [],
                "retry_indices": [],
            }),
            patch("pipeline.visual_toc.vision._classify_toc_candidates", side_effect=VisionModelRequestError(
                "classify_toc_candidates[0-0] 视觉请求失败（HTTP 400）：invalid_request",
                stage="classify_toc_candidates[0-0]",
                status_code=400,
                retryable=False,
                detail="invalid_request",
            )),
            patch("pipeline.visual_toc.runtime.update_doc_meta"),
            patch("pipeline.visual_toc.runtime.clear_auto_visual_toc_bundle_from_disk"),
        ):
            result = generate_auto_visual_toc_for_doc(
                "doc-test",
                pdf_path="/mock/source.pdf",
                model_spec=SimpleNamespace(model_id="mock-vision"),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason_code"], "vision_request_failed")
        self.assertEqual(result["http_status"], 400)
        self.assertIn("HTTP 400", result["message"])

    def test_filter_visual_toc_items_ignores_container_titles_and_summary_blocks(self):
        items = filter_visual_toc_items(
            [
                {"title": "Table des matieres", "depth": 0, "printed_page": None, "visual_order": 1},
                {
                    "title": "Lecon du 10 janvier 1979",
                    "depth": 0,
                    "printed_page": 51,
                    "visual_order": 2,
                },
                {
                    "title": "Dans cette lecon Foucault resume longuement les problemes generaux de la raison d'Etat et de la gouvernementalite liberale.",
                    "depth": 1,
                    "printed_page": None,
                    "visual_order": 3,
                },
                {
                    "title": "1. Liberalism",
                    "depth": 1,
                    "printed_page": 61,
                    "visual_order": 4,
                },
            ]
        )

        self.assertEqual(
            [item["title"] for item in items],
            ["Lecon du 10 janvier 1979", "1. Liberalism"],
        )

    def test_filter_visual_toc_items_keeps_role_hinted_container_and_post_body_without_pages(self):
        items = filter_visual_toc_items(
            [
                {
                    "title": "COURS, ANNÉE 1978-1979",
                    "depth": 0,
                    "printed_page": None,
                    "visual_order": 1,
                    "role_hint": "container",
                },
                {
                    "title": "RÉSUMÉ DU COURS",
                    "depth": 0,
                    "printed_page": None,
                    "visual_order": 2,
                    "role_hint": "post_body",
                },
            ]
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["role_hint"], "container")
        self.assertEqual(items[1]["role_hint"], "post_body")

    def test_filter_visual_toc_items_keeps_part_one_container_without_page(self):
        items = filter_visual_toc_items(
            [
                {
                    "title": "Part One",
                    "depth": 0,
                    "printed_page": None,
                    "visual_order": 1,
                },
                {
                    "title": "Part Two",
                    "depth": 0,
                    "printed_page": None,
                    "visual_order": 2,
                },
            ]
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["role_hint"], "container")
        self.assertEqual(items[1]["role_hint"], "container")

    def test_normalize_visual_toc_role_hint_accepts_container_aliases_and_book_matter_aliases(self):
        self.assertEqual(_normalize_visual_toc_role_hint("part"), "container")
        self.assertEqual(_normalize_visual_toc_role_hint("book"), "container")
        self.assertEqual(_normalize_visual_toc_role_hint("appendices"), "container")
        self.assertEqual(_normalize_visual_toc_role_hint("indices"), "container")
        self.assertEqual(_normalize_visual_toc_role_hint("frontmatter"), "front_matter")
        self.assertEqual(_normalize_visual_toc_role_hint("backmatter"), "back_matter")
        self.assertEqual(_normalize_visual_toc_role_hint("postbody"), "post_body")

    def test_merge_manual_toc_organization_nodes_skips_garbled_outline_rows(self):
        clean_nodes = [
            {
                "title": "Mad acts, mad speech, and mad people in Chinese medicine and law",
                "depth": 0,
                "printed_page": 1,
                "visual_order": 1,
                "role_hint": "chapter",
            },
            {
                "title": "Part One MEDICAL OBJECTS AND PRACTICES (Warring States to Qing)",
                "depth": 0,
                "printed_page": None,
                "visual_order": 2,
                "role_hint": "container",
            },
            {
                "title": "Prologue",
                "depth": 1,
                "printed_page": 20,
                "visual_order": 3,
                "role_hint": "chapter",
                "parent_title": "Part One MEDICAL OBJECTS AND PRACTICES (Warring States to Qing)",
            },
        ]
        garbled_outline = [
            {
                "title": "(4 \u0014438*387 \u0010!120 \"2 ((( \u0012.-2$-21 (4 \u0012.-2$-21\u0001\u0002#$2 (+$#\u0003 4( \u0015(&30$1\u0001 -#\u00012 !+$1 6( \u0012.-4$-2(.-1 6(( \u0010\"*-.5+$#&,$-21",
                "depth": 0,
                "printed_page": 64,
                "visual_order": 1,
                "role_hint": "chapter",
            },
            {
                "title": "\u0012.-2$-21",
                "depth": 0,
                "printed_page": 4,
                "visual_order": 2,
                "role_hint": "chapter",
                "parent_title": "Part Two = LEGAL AND POPULAR PRACTICES (Qing)",
            },
            {
                "title": "Mad acts, mad speech, and mad people in Chinese medicine and law",
                "depth": 0,
                "printed_page": 1,
                "visual_order": 3,
                "role_hint": "chapter",
            },
            {
                "title": "Part One MEDICAL OBJECTS AND PRACTICES (Warring States to Qing)",
                "depth": 0,
                "printed_page": None,
                "visual_order": 4,
                "role_hint": "container",
            },
            {
                "title": "Prologue",
                "depth": 1,
                "printed_page": 20,
                "visual_order": 5,
                "role_hint": "chapter",
                "parent_title": "Part One MEDICAL OBJECTS AND PRACTICES (Warring States to Qing)",
            },
        ]

        merged = _merge_manual_toc_organization_nodes(clean_nodes, garbled_outline)

        self.assertEqual(
            [item["title"] for item in merged],
            [
                "Mad acts, mad speech, and mad people in Chinese medicine and law",
                "Part One MEDICAL OBJECTS AND PRACTICES (Warring States to Qing)",
                "Prologue",
            ],
        )

    def test_merge_manual_toc_organization_nodes_skips_goldstein_like_container_chapter_composite_row(self):
        merged = _merge_manual_toc_organization_nodes(
            [
                {
                    "title": "Introduction",
                    "depth": 0,
                    "visual_order": 1,
                    "printed_page": 1,
                },
                {
                    "title": "II THE POLITICS OF SELFHOOD 3I Is There a Self in This Mental Apparatus?",
                    "depth": 0,
                    "visual_order": 2,
                    "printed_page": 31,
                },
                {
                    "title": "3 Is There a Self in This Mental Apparatus?",
                    "depth": 0,
                    "visual_order": 3,
                    "printed_page": 31,
                },
            ],
            [
                {
                    "title": "Introduction",
                    "depth": 0,
                    "visual_order": 1,
                    "printed_page": 1,
                    "role_hint": "chapter",
                },
                {
                    "title": "II THE POLITICS OF SELFHOOD",
                    "depth": 0,
                    "visual_order": 2,
                    "role_hint": "container",
                },
                {
                    "title": "3 Is There a Self in This Mental Apparatus?",
                    "depth": 1,
                    "visual_order": 3,
                    "printed_page": 31,
                    "role_hint": "chapter",
                    "parent_title": "II THE POLITICS OF SELFHOOD",
                },
            ],
        )

        self.assertEqual(
            [row["title"] for row in merged],
            [
                "Introduction",
                "II THE POLITICS OF SELFHOOD",
                "3 Is There a Self in This Mental Apparatus?",
            ],
        )
        self.assertEqual(merged[1]["role_hint"], "container")
        self.assertEqual(merged[2]["parent_title"], "II THE POLITICS OF SELFHOOD")

    def test_merge_manual_toc_organization_nodes_prefers_clean_page_matched_title_over_garbled_outline(self):
        merged = _merge_manual_toc_organization_nodes(
            [
                {
                    "title": "5. L'embellie des années 1950",
                    "depth": 0,
                    "printed_page": 187,
                    "visual_order": 5,
                    "role_hint": "chapter",
                },
                {
                    "title": "6. Polémiques renouvelées, déplacements inédits",
                    "depth": 0,
                    "printed_page": 203,
                    "visual_order": 6,
                    "role_hint": "chapter",
                },
            ],
            [
                {
                    "title": "5. L'=bellie des années 1950 ....................................................",
                    "depth": 0,
                    "printed_page": 187,
                    "visual_order": 1,
                    "role_hint": "chapter",
                },
                {
                    "title": "6. Polémiques renouvelées, déplac=ents inédits ......................",
                    "depth": 0,
                    "printed_page": 203,
                    "visual_order": 2,
                    "role_hint": "chapter",
                },
            ],
        )

        self.assertEqual(
            [row["title"] for row in merged],
            [
                "5. L'embellie des années 1950",
                "6. Polémiques renouvelées, déplacements inédits",
            ],
        )

    def test_annotate_visual_toc_organization_marks_container_post_body_and_export_candidates(self):
        items, summary = _annotate_visual_toc_organization(
            [
                {
                    "title": "COURS, ANNÉE 1978-1979",
                    "depth": 0,
                    "visual_order": 1,
                    "role_hint": "container",
                },
                {
                    "title": "Leçon du 10 janvier 1979",
                    "depth": 1,
                    "visual_order": 2,
                    "role_hint": "chapter",
                },
                {
                    "title": "RÉSUMÉ DU COURS",
                    "depth": 0,
                    "visual_order": 3,
                    "role_hint": "post_body",
                },
                {
                    "title": "Index des notions",
                    "depth": 0,
                    "visual_order": 4,
                    "role_hint": "back_matter",
                },
            ]
        )

        self.assertEqual(summary["has_containers"], True)
        self.assertEqual(summary["has_post_body"], True)
        self.assertEqual(summary["has_back_matter"], True)
        self.assertEqual(summary["container_titles"], ["COURS, ANNÉE 1978-1979"])
        self.assertEqual(summary["post_body_titles"], ["RÉSUMÉ DU COURS"])
        self.assertEqual(summary["back_matter_titles"], ["Index des notions"])
        self.assertEqual(items[0]["role_hint"], "container")
        self.assertFalse(items[0]["export_candidate"])
        self.assertEqual(items[1]["parent_title"], "COURS, ANNÉE 1978-1979")
        self.assertTrue(items[1]["body_candidate"])
        self.assertTrue(items[1]["export_candidate"])
        self.assertEqual(items[2]["role_hint"], "post_body")
        self.assertTrue(items[2]["export_candidate"])

    def test_annotate_visual_toc_organization_promotes_container_children_and_roman_root(self):
        items, summary = _annotate_visual_toc_organization(
            [
                {
                    "title": "Préambule",
                    "depth": 0,
                    "visual_order": 1,
                },
                {
                    "title": "III. L’homme qui se prenait pour Napoléon",
                    "depth": 0,
                    "visual_order": 2,
                },
                {
                    "title": "La monomanie orgueilleuse ou le mal du siècle",
                    "depth": 1,
                    "visual_order": 3,
                    "printed_page": 166,
                },
                {
                    "title": "L’Usurpateur",
                    "depth": 1,
                    "visual_order": 4,
                    "printed_page": 201,
                },
                {
                    "title": "Bibliographies",
                    "depth": 0,
                    "visual_order": 5,
                },
            ]
        )

        self.assertEqual(items[0]["role_hint"], "chapter")
        self.assertEqual(items[1]["role_hint"], "container")
        self.assertFalse(items[1]["export_candidate"])
        self.assertEqual(items[2]["role_hint"], "chapter")
        self.assertEqual(items[2]["parent_title"], "III. L’homme qui se prenait pour Napoléon")
        self.assertTrue(items[2]["export_candidate"])
        self.assertEqual(items[3]["role_hint"], "chapter")
        self.assertEqual(items[4]["role_hint"], "back_matter")
        self.assertEqual(summary["container_titles"], ["III. L’homme qui se prenait pour Napoléon"])
        self.assertEqual(summary["back_matter_titles"], ["Bibliographies"])

    def test_annotate_visual_toc_organization_overrides_explicit_part_root_to_container(self):
        items, summary = _annotate_visual_toc_organization(
            [
                {
                    "title": "Part I Conceptual Equipment",
                    "depth": 0,
                    "visual_order": 1,
                    "role_hint": "chapter",
                },
                {
                    "title": "1 Transcendental Approach to the Brain",
                    "depth": 1,
                    "visual_order": 2,
                    "printed_page": 19,
                    "role_hint": "chapter",
                },
                {
                    "title": "Part II Neural Equipment",
                    "depth": 0,
                    "visual_order": 3,
                    "role_hint": "chapter",
                },
                {
                    "title": "4 Cathexis and the Energy of the Brain",
                    "depth": 1,
                    "visual_order": 4,
                    "printed_page": 87,
                    "role_hint": "chapter",
                },
            ]
        )

        self.assertEqual(items[0]["role_hint"], "container")
        self.assertFalse(items[0]["export_candidate"])
        self.assertEqual(items[1]["role_hint"], "chapter")
        self.assertEqual(items[1]["parent_title"], "Part I Conceptual Equipment")
        self.assertEqual(items[2]["role_hint"], "container")
        self.assertEqual(summary["container_titles"], ["Part I Conceptual Equipment", "Part II Neural Equipment"])

    def test_annotate_visual_toc_organization_overrides_explicit_roman_roots_with_children(self):
        items, summary = _annotate_visual_toc_organization(
            [
                {
                    "title": "I. 1793 ou comment perdre la tête",
                    "depth": 0,
                    "visual_order": 1,
                    "role_hint": "chapter",
                },
                {
                    "title": "« Une invention utile dans le genre funeste »",
                    "depth": 1,
                    "visual_order": 2,
                    "printed_page": 47,
                    "role_hint": "section",
                },
                {
                    "title": "II. L’asile, prison politique ?",
                    "depth": 0,
                    "visual_order": 3,
                    "role_hint": "chapter",
                },
                {
                    "title": "Maisons de santé, maisons d’arrêt",
                    "depth": 1,
                    "visual_order": 4,
                    "printed_page": 112,
                    "role_hint": "section",
                },
            ]
        )

        self.assertEqual(items[0]["role_hint"], "container")
        self.assertEqual(items[1]["role_hint"], "chapter")
        self.assertEqual(items[1]["parent_title"], "I. 1793 ou comment perdre la tête")
        self.assertEqual(items[2]["role_hint"], "container")
        self.assertEqual(items[3]["role_hint"], "chapter")
        self.assertEqual(
            summary["container_titles"],
            ["I. 1793 ou comment perdre la tête", "II. L’asile, prison politique ?"],
        )

    def test_annotate_visual_toc_organization_normalizes_semantic_depth_for_endnotes_and_container_children(self):
        items, summary = _annotate_visual_toc_organization(
            [
                {
                    "title": "COURS, ANNÉE 1978-1979",
                    "depth": 0,
                    "visual_order": 1,
                    "role_hint": "container",
                },
                {
                    "title": "Leçon du 10 janvier 1979",
                    "depth": 1,
                    "visual_order": 2,
                    "printed_page": 3,
                    "role_hint": "chapter",
                },
                {
                    "title": "Notes",
                    "depth": 0,
                    "visual_order": 3,
                    "printed_page": 259,
                    "role_hint": "endnotes",
                },
                {
                    "title": "Notes to Introduction",
                    "depth": 1,
                    "visual_order": 4,
                    "printed_page": 261,
                    "role_hint": "section",
                    "parent_title": "Notes",
                },
            ]
        )

        self.assertEqual(items[0]["depth"], 1)
        self.assertEqual(items[1]["depth"], 0)
        self.assertEqual(items[1]["parent_title"], "COURS, ANNÉE 1978-1979")
        self.assertEqual(items[2]["depth"], 1)
        self.assertEqual(items[2]["role_hint"], "endnotes")
        self.assertEqual(items[3]["depth"], 2)
        self.assertEqual(items[3]["parent_title"], "Notes")
        self.assertFalse(items[3]["body_candidate"])
        self.assertFalse(items[3]["export_candidate"])
        self.assertEqual(summary["max_body_depth"], 2)

    def test_annotate_visual_toc_organization_promotes_semantic_container_titles_even_if_prompt_marks_back_matter(self):
        items, summary = _annotate_visual_toc_organization(
            [
                {
                    "title": "INDICES",
                    "depth": 0,
                    "visual_order": 1,
                    "role_hint": "back_matter",
                },
                {
                    "title": "Index des notions",
                    "depth": 1,
                    "visual_order": 2,
                    "printed_page": 361,
                    "role_hint": "section",
                },
                {
                    "title": "Notes",
                    "depth": 0,
                    "visual_order": 3,
                    "role_hint": "back_matter",
                },
                {
                    "title": "Notes to Introduction",
                    "depth": 1,
                    "visual_order": 4,
                    "printed_page": 259,
                    "role_hint": "section",
                },
            ]
        )

        self.assertEqual(items[0]["role_hint"], "container")
        self.assertEqual(items[0]["depth"], 1)
        self.assertEqual(items[1]["role_hint"], "back_matter")
        self.assertEqual(items[1]["depth"], 0)
        self.assertEqual(items[1]["parent_title"], "INDICES")
        self.assertEqual(items[2]["role_hint"], "endnotes")
        self.assertEqual(items[2]["depth"], 1)
        self.assertEqual(items[2]["parent_title"], "")
        self.assertEqual(items[3]["depth"], 2)
        self.assertEqual(items[3]["parent_title"], "Notes")
        self.assertIn("INDICES", summary["container_titles"])

    def test_merge_manual_toc_organization_nodes_preserves_missing_containers_and_page_matches(self):
        merged = _merge_manual_toc_organization_nodes(
            [
                {
                    "title": "Mad acts, mad speech, and mad people in Chinese medicine and law",
                    "depth": 0,
                    "visual_order": 1,
                    "file_idx": 18,
                },
                {
                    "title": "Prologue",
                    "depth": 1,
                    "visual_order": 2,
                    "file_idx": 37,
                },
                {
                    "title": "Errors and projections",
                    "depth": 0,
                    "visual_order": 3,
                    "file_idx": 438,
                },
                {
                    "title": "Bibliographies",
                    "depth": 0,
                    "visual_order": 4,
                    "file_idx": 638,
                },
                {
                    "title": "Appendices",
                    "depth": 0,
                    "visual_order": 5,
                    "file_idx": 723,
                },
            ],
            [
                {
                    "title": "Mad acts, mad speech, and mad people in Chinese medicine and law",
                    "depth": 0,
                    "visual_order": 1,
                    "role_hint": "chapter",
                },
                {
                    "title": "Part One",
                    "depth": 0,
                    "visual_order": 2,
                    "role_hint": "container",
                },
                {
                    "title": "Prologue",
                    "depth": 1,
                    "visual_order": 3,
                    "role_hint": "chapter",
                    "parent_title": "Part One",
                },
                {
                    "title": "Part Two",
                    "depth": 0,
                    "visual_order": 4,
                    "role_hint": "container",
                },
                {
                    "title": "Errors and projections",
                    "depth": 1,
                    "visual_order": 5,
                    "role_hint": "chapter",
                    "parent_title": "Part Two",
                },
                {
                    "title": "Bibliographies",
                    "depth": 0,
                    "visual_order": 6,
                    "role_hint": "back_matter",
                },
                {
                    "title": "Appendices",
                    "depth": 0,
                    "visual_order": 7,
                    "role_hint": "post_body",
                },
            ],
        )

        self.assertEqual([row["title"] for row in merged[:4]], [
            "Mad acts, mad speech, and mad people in Chinese medicine and law",
            "Part One",
            "Prologue",
            "Part Two",
        ])
        self.assertIsNone(merged[1].get("file_idx"))
        self.assertEqual(merged[2]["file_idx"], 37)
        self.assertEqual(merged[4]["file_idx"], 438)
        self.assertEqual(merged[5]["role_hint"], "back_matter")
        self.assertEqual(merged[6]["role_hint"], "post_body")

    def test_merge_manual_toc_organization_nodes_reinserts_missing_middle_body_rows_in_order(self):
        merged = _merge_manual_toc_organization_nodes(
            [
                {"title": "Introduction", "depth": 0, "visual_order": 1, "book_page": 1},
                {"title": "1 Transcendental Approach to the Brain", "depth": 0, "visual_order": 2, "book_page": 19},
                {"title": "2 Unknowability and the Concept of the Brain", "depth": 0, "visual_order": 3, "book_page": 36},
                {"title": "3 Transdisciplinary Methodology and Neuropsychodynamic Concept–Fact Iterativity", "depth": 0, "visual_order": 4, "book_page": 57},
                {"title": "4 Cathexis and the Energy of the Brain", "depth": 0, "visual_order": 5, "book_page": 87},
                {"title": "5 Cathexis, Neural Coding, and Mental States", "depth": 0, "visual_order": 6, "book_page": 108},
                {"title": "6 Defense Mechanisms and Brain–Object and Brain–Self Differentiation", "depth": 0, "visual_order": 7, "book_page": 134},
                {"title": "8 Unconsciousness and the Brain", "depth": 0, "visual_order": 8, "book_page": 186},
            ],
            [
                {"title": "Introduction", "depth": 0, "visual_order": 1, "role_hint": "chapter"},
                {"title": "Part I Conceptual Equipment", "depth": 0, "visual_order": 2, "role_hint": "container"},
                {"title": "1 Transcendental Approach to the Brain", "depth": 1, "visual_order": 3, "role_hint": "chapter", "parent_title": "Part I Conceptual Equipment"},
                {"title": "2 Unknowability and the Concept of the Brain", "depth": 1, "visual_order": 4, "role_hint": "chapter", "parent_title": "Part I Conceptual Equipment"},
                {"title": "3 Transdisciplinary Methodology and Neuropsychodynamic Concept–Fact Iterativity", "depth": 1, "visual_order": 5, "role_hint": "chapter", "parent_title": "Part I Conceptual Equipment"},
                {"title": "Part III Mental Equipment", "depth": 0, "visual_order": 6, "role_hint": "container"},
                {"title": "8 Unconsciousness and the Brain", "depth": 1, "visual_order": 7, "role_hint": "chapter", "parent_title": "Part III Mental Equipment"},
            ],
        )

        titles = [row["title"] for row in merged]
        self.assertEqual(
            titles,
            [
                "Introduction",
                "Part I Conceptual Equipment",
                "1 Transcendental Approach to the Brain",
                "2 Unknowability and the Concept of the Brain",
                "3 Transdisciplinary Methodology and Neuropsychodynamic Concept–Fact Iterativity",
                "4 Cathexis and the Energy of the Brain",
                "5 Cathexis, Neural Coding, and Mental States",
                "6 Defense Mechanisms and Brain–Object and Brain–Self Differentiation",
                "Part III Mental Equipment",
                "8 Unconsciousness and the Brain",
            ],
        )
        self.assertEqual(merged[5]["book_page"], 87)
        self.assertEqual(merged[6]["book_page"], 108)
        self.assertEqual(merged[7]["book_page"], 134)

    def test_augment_manual_toc_organization_with_ocr_containers_injects_missing_parts(self):
        augmented = _augment_manual_toc_organization_with_ocr_containers(
            [
                {
                    "title": "Introduction",
                    "depth": 0,
                    "visual_order": 1,
                    "printed_page": 1,
                    "role_hint": "chapter",
                },
                {
                    "title": "1 Transcendental Approach to the Brain",
                    "depth": 0,
                    "visual_order": 2,
                    "printed_page": 19,
                    "role_hint": "chapter",
                },
                {
                    "title": "Philosophical concepts",
                    "depth": 1,
                    "visual_order": 3,
                    "printed_page": 19,
                    "role_hint": "section",
                },
                {
                    "title": "2 Unknowability and the Concept of the Brain",
                    "depth": 0,
                    "visual_order": 4,
                    "printed_page": 36,
                    "role_hint": "chapter",
                },
                {
                    "title": "4 Cathexis and the Energy of the Brain",
                    "depth": 0,
                    "visual_order": 5,
                    "printed_page": 87,
                    "role_hint": "chapter",
                },
                {
                    "title": "Appendix: What Can We Learn From Depression and Psychosis?",
                    "depth": 0,
                    "visual_order": 6,
                    "printed_page": 333,
                    "role_hint": "post_body",
                },
            ],
            [
                "Introduction",
                "Part I Conceptual Equipment",
                "1 Transcendental Approach to the Brain",
                "2 Unknowability and the Concept of the Brain",
                "Part II Neural Equipment",
                "4 Cathexis and the Energy of the Brain",
                "Appendix: What Can We Learn From Depression and Psychosis?",
            ],
        )

        titles = [item["title"] for item in augmented]
        self.assertIn("Part I Conceptual Equipment", titles)
        self.assertIn("Part II Neural Equipment", titles)
        part_one = next(item for item in augmented if item["title"] == "Part I Conceptual Equipment")
        chapter_one = next(item for item in augmented if item["title"] == "1 Transcendental Approach to the Brain")
        chapter_two = next(item for item in augmented if item["title"] == "2 Unknowability and the Concept of the Brain")
        part_two = next(item for item in augmented if item["title"] == "Part II Neural Equipment")
        chapter_four = next(item for item in augmented if item["title"] == "4 Cathexis and the Energy of the Brain")
        appendix = next(item for item in augmented if item["title"].startswith("Appendix:"))

        self.assertEqual(part_one["role_hint"], "container")
        self.assertEqual(part_one["depth"], 0)
        self.assertEqual(chapter_one["depth"], 1)
        self.assertEqual(chapter_two["depth"], 1)
        self.assertEqual(part_two["role_hint"], "container")
        self.assertEqual(chapter_four["depth"], 1)
        self.assertEqual(appendix["role_hint"], "post_body")

    def test_augment_manual_toc_organization_with_ocr_containers_normalizes_roman_noise(self):
        augmented = _augment_manual_toc_organization_with_ocr_containers(
            [
                {
                    "title": "I. 1793 ou comment perdre la tête",
                    "depth": 0,
                    "visual_order": 1,
                    "printed_page": 45,
                    "role_hint": "chapter",
                },
                {
                    "title": "« Une invention utile dans le genre funeste »",
                    "depth": 1,
                    "visual_order": 2,
                    "printed_page": 47,
                    "role_hint": "section",
                },
                {
                    "title": "II. L’asile, prison politique ?",
                    "depth": 0,
                    "visual_order": 3,
                    "printed_page": 111,
                    "role_hint": "chapter",
                },
                {
                    "title": "Maisons de santé, maisons d’arrêt",
                    "depth": 1,
                    "visual_order": 4,
                    "printed_page": 112,
                    "role_hint": "section",
                },
            ],
            [
                "I. 1793 ou comment perdre la tête 45",
                "« Une invention utile dans le genre funeste »",
                "Il. L’asile, prison politique ? 111",
                "Maisons de santé, maisons d’arrêt",
            ],
        )

        titles = [item["title"] for item in augmented]
        self.assertEqual(titles.count("I. 1793 ou comment perdre la tête"), 1)
        self.assertEqual(titles.count("II. L’asile, prison politique ?"), 1)

    def test_augment_manual_toc_organization_with_ocr_containers_normalizes_part_ocr_noise(self):
        augmented = _augment_manual_toc_organization_with_ocr_containers(
            [
                {
                    "title": "Introduction",
                    "depth": 0,
                    "visual_order": 1,
                    "printed_page": 1,
                    "role_hint": "chapter",
                },
                {
                    "title": "1 Transcendental Approach to the Brain",
                    "depth": 0,
                    "visual_order": 2,
                    "printed_page": 19,
                    "role_hint": "chapter",
                },
                {
                    "title": "4 Cathexis and the Energy of the Brain",
                    "depth": 0,
                    "visual_order": 3,
                    "printed_page": 87,
                    "role_hint": "chapter",
                },
            ],
            [
                "Introduction 1",
                "Part | Conceptual Equipment",
                "1 Transcendental Approach to the Brain 19",
                "Part Il Neural Equipment",
                "4 Cathexis and the Energy of the Brain 87",
            ],
        )

        titles = [item["title"] for item in augmented]
        self.assertIn("Part I Conceptual Equipment", titles)
        self.assertIn("Part II Neural Equipment", titles)
        self.assertEqual(titles.count("Part I Conceptual Equipment"), 1)
        self.assertEqual(titles.count("Part II Neural Equipment"), 1)

    def test_extract_manual_toc_outline_nodes_from_pdf_text_recovers_missing_container_and_chapters(self):
        fake_pages = [
            SimpleNamespace(
                extract_text=lambda: (
                    "Contents\n"
                    "Introduction 1\n"
                    "Part I Conceptual Equipment\n"
                    "1 Transcendental Approach to the Brain 19\n"
                    "2 Unknowability and the Concept of the Brain 36\n"
                )
            ),
            SimpleNamespace(
                extract_text=lambda: (
                    "CONTENTSxii\n"
                    "Part II Neural Equipment\n"
                    "4 Cathexis and the Energy of the Brain 87\n"
                    "5 Cathexis, Neural Coding, and Mental States 108\n"
                    "6 Defense Mechanisms and Brain-Object and Brain-Self Differentiation 134\n"
                    "Appendix: What Can We Learn From Depression and Psychosis?\n"
                    "A Transdisciplinary and Neuroexistential Account 319\n"
                    "xiiiCONTENTS 8 Unconsciousness and the Brain 186\n"
                    "References 337\n"
                )
            ),
        ]

        class _Reader:
            def __init__(self, _path):
                self.pages = fake_pages

        with patch("pipeline.visual_toc.manual_inputs.os.path.exists", return_value=True), patch("pypdf.PdfReader", _Reader):
            nodes = _extract_manual_toc_outline_nodes_from_pdf_text("/tmp/fake-toc.pdf")

        titles = [row["title"] for row in nodes]
        self.assertIn("Part II Neural Equipment", titles)
        self.assertIn("4 Cathexis and the Energy of the Brain", titles)
        self.assertIn("5 Cathexis, Neural Coding, and Mental States", titles)
        self.assertIn("6 Defense Mechanisms and Brain-Object and Brain-Self Differentiation", titles)
        self.assertIn("Appendix: What Can We Learn From Depression and Psychosis? A Transdisciplinary and Neuroexistential Account", titles)
        self.assertIn("8 Unconsciousness and the Brain", titles)
        part_two = next(row for row in nodes if row["title"] == "Part II Neural Equipment")
        chapter_four = next(row for row in nodes if row["title"] == "4 Cathexis and the Energy of the Brain")
        chapter_five = next(row for row in nodes if row["title"] == "5 Cathexis, Neural Coding, and Mental States")
        chapter_six = next(row for row in nodes if row["title"] == "6 Defense Mechanisms and Brain-Object and Brain-Self Differentiation")
        appendix = next(row for row in nodes if row["title"].startswith("Appendix:"))
        references = next(row for row in nodes if row["title"] == "References")
        self.assertEqual(part_two["role_hint"], "container")
        self.assertEqual(part_two["depth"], 1)
        self.assertEqual(chapter_four["role_hint"], "chapter")
        self.assertEqual(chapter_four["depth"], 0)
        self.assertEqual(chapter_four["parent_title"], "Part II Neural Equipment")
        self.assertEqual(chapter_five["role_hint"], "chapter")
        self.assertEqual(chapter_five["depth"], 0)
        self.assertEqual(chapter_five["parent_title"], "Part II Neural Equipment")
        self.assertEqual(chapter_six["role_hint"], "chapter")
        self.assertEqual(chapter_six["depth"], 0)
        self.assertEqual(chapter_six["parent_title"], "Part II Neural Equipment")
        self.assertEqual(appendix["role_hint"], "post_body")
        self.assertEqual(appendix["depth"], 0)
        self.assertEqual(references["role_hint"], "back_matter")
        self.assertEqual(references["depth"], 0)

    def test_extract_manual_toc_outline_nodes_keeps_part_container_after_acknowledgments(self):
        fake_pages = [
            SimpleNamespace(
                extract_text=lambda: (
                    "CONTENTSxii\n"
                    "Part III Mental Equipment\n"
                    "7 Narcissism, Self-Objects, and the Brain 163\n"
                    "Acknowledgments 185\n"
                )
            ),
            SimpleNamespace(
                extract_text=lambda: (
                    "xiiiCONTENTS\n"
                    "8 Unconsciousness and the Brain 186\n"
                    "9 The Self and its Brain 212\n"
                    "Part IV Disordered Equipment\n"
                    "10 Depression and the Brain 239\n"
                    "Acknowledgments 263\n"
                    "11 Psychosis I: Psychodynamics and Phenomenology 264\n"
                    "12 Psychosis II: Neuropsychodynamic Hypotheses 283\n"
                )
            ),
        ]

        class _Reader:
            def __init__(self, _path):
                self.pages = fake_pages

        with patch("pipeline.visual_toc.manual_inputs.os.path.exists", return_value=True), patch("pypdf.PdfReader", _Reader):
            nodes = _extract_manual_toc_outline_nodes_from_pdf_text("/tmp/fake-toc.pdf")

        chapter_eight = next(row for row in nodes if row["title"] == "8 Unconsciousness and the Brain")
        chapter_nine = next(row for row in nodes if row["title"] == "9 The Self and its Brain")
        chapter_eleven = next(row for row in nodes if row["title"] == "11 Psychosis I: Psychodynamics and Phenomenology")
        chapter_twelve = next(row for row in nodes if row["title"] == "12 Psychosis II: Neuropsychodynamic Hypotheses")

        self.assertEqual(chapter_eight["parent_title"], "Part III Mental Equipment")
        self.assertEqual(chapter_eight["depth"], 0)
        self.assertEqual(chapter_nine["parent_title"], "Part III Mental Equipment")
        self.assertEqual(chapter_eleven["parent_title"], "Part IV Disordered Equipment")
        self.assertEqual(chapter_twelve["parent_title"], "Part IV Disordered Equipment")

    def test_extract_manual_toc_outline_nodes_keeps_appendix_children_under_post_body(self):
        fake_pages = [
            SimpleNamespace(
                extract_text=lambda: (
                    "CONTENTSxiv\n"
                    "Appendix: What Can We Learn From Depression and Psychosis?\n"
                    "A Transdisciplinary and Neuroexistential Account 319\n"
                    "  Background 319\n"
                    "  Depression 319\n"
                    "  Psychosis 321\n"
                    "  Neuroexistential account 323\n"
                    "Epilogue: The Beauty of Transdisciplinary Failure —A Trialogue 325\n"
                )
            ),
        ]

        class _Reader:
            def __init__(self, _path):
                self.pages = fake_pages

        with patch("pipeline.visual_toc.manual_inputs.os.path.exists", return_value=True), patch("pypdf.PdfReader", _Reader):
            nodes = _extract_manual_toc_outline_nodes_from_pdf_text("/tmp/fake-toc.pdf")

        appendix = next(row for row in nodes if row["title"].startswith("Appendix:"))
        background = next(row for row in nodes if row["title"] == "Background")
        depression = next(row for row in nodes if row["title"] == "Depression")
        epilogue = next(row for row in nodes if row["title"].startswith("Epilogue:"))

        self.assertEqual(appendix["role_hint"], "post_body")
        self.assertEqual(background["role_hint"], "section")
        self.assertEqual(background["parent_title"], appendix["title"])
        self.assertEqual(background["depth"], 2)
        self.assertEqual(depression["parent_title"], appendix["title"])
        self.assertEqual(epilogue["role_hint"], "chapter")
        self.assertEqual(epilogue["parent_title"], "")
        self.assertEqual(epilogue["depth"], 0)

    def test_extract_manual_toc_outline_nodes_keeps_endnotes_as_container_not_epilogue_section(self):
        fake_pages = [
            SimpleNamespace(
                extract_text=lambda: (
                    "Contents\n"
                    "Epilogue 316\n"
                    "Notes 331\n"
                    "Note on Sources 399\n"
                    "Index 403\n"
                )
            ),
        ]

        class _Reader:
            def __init__(self, _path):
                self.pages = fake_pages

        with patch("pipeline.visual_toc.manual_inputs.os.path.exists", return_value=True), patch("pypdf.PdfReader", _Reader):
            nodes = _extract_manual_toc_outline_nodes_from_pdf_text("/tmp/fake-toc.pdf")

        epilogue = next(row for row in nodes if row["title"] == "Epilogue")
        notes = next(row for row in nodes if row["title"] == "Notes")
        note_on_sources = next(row for row in nodes if row["title"] == "Note on Sources")

        self.assertEqual(epilogue["role_hint"], "chapter")
        self.assertEqual(epilogue["depth"], 0)
        self.assertEqual(notes["role_hint"], "endnotes")
        self.assertEqual(notes["depth"], 1)
        self.assertEqual(notes["parent_title"], "")
        self.assertEqual(note_on_sources["role_hint"], "back_matter")
        self.assertEqual(note_on_sources["parent_title"], "")

    def test_should_prefer_manual_outline_nodes_when_outline_recovers_missing_containers(self):
        existing = [
            {"title": "Introduction", "role_hint": "chapter"},
            {"title": "Part I Conceptual Equipment", "role_hint": "container"},
            {"title": "1 Transcendental Approach to the Brain", "role_hint": "chapter", "parent_title": "Part I Conceptual Equipment"},
            {"title": "Part III Mental Equipment", "role_hint": "container"},
            {"title": "8 Unconsciousness and the Brain", "role_hint": "chapter", "parent_title": "Part III Mental Equipment"},
            {"title": "Part IV Disordered Equipment", "role_hint": "container"},
            {"title": "10 Depression and the Brain", "role_hint": "chapter", "parent_title": "Part IV Disordered Equipment"},
            {"title": "Appendix", "role_hint": "post_body"},
            {"title": "References", "role_hint": "back_matter"},
        ]
        outline = [
            {"title": "Introduction", "role_hint": "chapter"},
            {"title": "Part I Conceptual Equipment", "role_hint": "container"},
            {"title": "1 Transcendental Approach to the Brain", "role_hint": "chapter", "parent_title": "Part I Conceptual Equipment"},
            {"title": "Part II Neural Equipment", "role_hint": "container"},
            {"title": "4 Cathexis and the Energy of the Brain", "role_hint": "chapter", "parent_title": "Part II Neural Equipment"},
            {"title": "5 Cathexis, Neural Coding, and Mental States", "role_hint": "chapter", "parent_title": "Part II Neural Equipment"},
            {"title": "6 Defense Mechanisms and Brain-Object and Brain-Self Differentiation", "role_hint": "chapter", "parent_title": "Part II Neural Equipment"},
            {"title": "Part III Mental Equipment", "role_hint": "container"},
            {"title": "8 Unconsciousness and the Brain", "role_hint": "chapter", "parent_title": "Part III Mental Equipment"},
            {"title": "Part IV Disordered Equipment", "role_hint": "container"},
            {"title": "10 Depression and the Brain", "role_hint": "chapter", "parent_title": "Part IV Disordered Equipment"},
            {"title": "Appendix", "role_hint": "post_body"},
            {"title": "References", "role_hint": "back_matter"},
        ]

        self.assertTrue(_should_prefer_manual_outline_nodes(existing, outline))

    def test_generate_visual_toc_manual_pdf_uses_outline_as_primary_items_when_outline_is_more_complete(self):
        class _RepoStub:
            def set_document_toc_for_source(self, *_args, **_kwargs):
                return None

            def set_document_toc_source_offset(self, *_args, **_kwargs):
                return None

        manual_page_items = [
            {"title": "Introduction", "depth": 0, "printed_page": 1, "visual_order": 1},
            {"title": "Part III Mental Equipment", "depth": 0, "printed_page": None, "visual_order": 2},
            {"title": "8 Unconsciousness and the Brain", "depth": 0, "printed_page": 186, "visual_order": 3},
            {"title": "Appendix", "depth": 0, "printed_page": 319, "visual_order": 4},
            {"title": "Background", "depth": 0, "printed_page": 319, "visual_order": 5},
        ]
        partial_org_nodes = [
            {"title": "Part III Mental Equipment", "depth": 0, "visual_order": 1, "role_hint": "container"},
            {"title": "8 Unconsciousness and the Brain", "depth": 1, "visual_order": 2, "role_hint": "chapter", "parent_title": "Part III Mental Equipment"},
        ]
        outline_nodes = [
            {"title": "Introduction", "depth": 0, "visual_order": 1, "role_hint": "chapter", "printed_page": 1},
            {"title": "Part II Neural Equipment", "depth": 0, "visual_order": 2, "role_hint": "container"},
            {"title": "4 Cathexis and the Energy of the Brain", "depth": 1, "visual_order": 3, "role_hint": "chapter", "parent_title": "Part II Neural Equipment", "printed_page": 87},
            {"title": "Part III Mental Equipment", "depth": 0, "visual_order": 4, "role_hint": "container"},
            {"title": "8 Unconsciousness and the Brain", "depth": 1, "visual_order": 5, "role_hint": "chapter", "parent_title": "Part III Mental Equipment", "printed_page": 186},
            {"title": "Appendix: What Can We Learn From Depression and Psychosis? A Transdisciplinary and Neuroexistential Account", "depth": 0, "visual_order": 6, "role_hint": "post_body", "printed_page": 319},
            {"title": "Background", "depth": 1, "visual_order": 7, "role_hint": "section", "parent_title": "Appendix: What Can We Learn From Depression and Psychosis? A Transdisciplinary and Neuroexistential Account", "printed_page": 319},
            {"title": "References", "depth": 0, "visual_order": 8, "role_hint": "back_matter", "printed_page": 337},
        ]

        with (
            patch("pipeline.visual_toc.runtime.os.path.exists", return_value=True),
            patch("pipeline.visual_toc.runtime.SQLiteRepository", return_value=_RepoStub()),
            patch("pipeline.visual_toc.vision.confirm_model_supports_vision", return_value=(True, "ok")),
            patch("pipeline.visual_toc.runtime.load_toc_visual_manual_inputs", return_value={
                "mode": "manual_pdf",
                "pdf_path": "/mock/doc/toc_visual_source.pdf",
                "image_paths": [],
                "page_count": 1,
                "source_name": "目录.pdf",
            }),
            patch("pipeline.visual_toc.scan_plan._resolve_total_pages", side_effect=lambda path: 1 if path.endswith("toc_visual_source.pdf") else 400),
            patch("pipeline.visual_toc.vision._extract_visual_toc_page_items_from_pdf", return_value=manual_page_items),
            patch("pipeline.visual_toc.vision._extract_visual_toc_organization_nodes_from_images", return_value=partial_org_nodes),
            patch("pipeline.visual_toc.manual_inputs._extract_manual_toc_outline_nodes_from_pdf_text", return_value=outline_nodes),
            patch("pipeline.visual_toc.organization._should_prefer_manual_outline_nodes", return_value=True),
            patch("pipeline.visual_toc.vision.render_pdf_page", return_value=b"fake-image"),
            patch("pipeline.visual_toc.vision._bytes_to_data_url", return_value="data:image/png;base64,ZmFrZQ=="),
            patch("pipeline.visual_toc.organization._build_printed_page_lookup", return_value={1: 0, 87: 86, 186: 185, 319: 318, 337: 336}),
            patch("pipeline.visual_toc.runtime.extract_pdf_page_link_targets", return_value=[]),
            patch("pipeline.visual_toc.runtime.update_doc_meta"),
        ):
            result = generate_auto_visual_toc_for_doc(
                "doc-test",
                pdf_path="/mock/source.pdf",
                model_spec=SimpleNamespace(model_id="mock-vision"),
            )

        titles = [str(row.get("title") or "") for row in result.get("organization_nodes") or []]
        self.assertEqual(
            titles,
            [
                "Introduction",
                "Part II Neural Equipment",
                "4 Cathexis and the Energy of the Brain",
                "Part III Mental Equipment",
                "8 Unconsciousness and the Brain",
                "Appendix: What Can We Learn From Depression and Psychosis? A Transdisciplinary and Neuroexistential Account",
                "Background",
                "References",
            ],
        )
        self.assertEqual(
            result["organization_summary"]["container_titles"],
            ["Part II Neural Equipment", "Part III Mental Equipment"],
        )

    def test_annotate_visual_toc_organization_demotes_long_root_book_title_before_containers(self):
        items, summary = _annotate_visual_toc_organization(
            [
                {
                    "title": "Mad acts, mad speech, and mad people in Chinese medicine and law",
                    "depth": 0,
                    "visual_order": 1,
                },
                {
                    "title": "Part One MEDICAL OBJECTS AND PRACTICES (Warring States to Qing)",
                    "depth": 0,
                    "visual_order": 2,
                    "role_hint": "container",
                },
                {
                    "title": "Prologue",
                    "depth": 1,
                    "visual_order": 3,
                    "printed_page": 20,
                    "role_hint": "chapter",
                },
            ]
        )

        self.assertEqual(items[0]["role_hint"], "front_matter")
        self.assertFalse(items[0]["export_candidate"])
        self.assertEqual(items[1]["role_hint"], "container")
        self.assertEqual(items[2]["parent_title"], "Part One MEDICAL OBJECTS AND PRACTICES (Warring States to Qing)")
        self.assertEqual(summary["container_titles"], ["Part One MEDICAL OBJECTS AND PRACTICES (Warring States to Qing)"])

    def test_filter_visual_toc_items_keeps_real_index_entry_when_it_has_a_page(self):
        items = filter_visual_toc_items(
            [
                {"title": "Index", "depth": 0, "printed_page": 411, "visual_order": 1},
            ]
        )

        self.assertEqual(items[0]["title"], "Index")
        self.assertEqual(items[0]["printed_page"], 411)

    def test_map_visual_items_to_link_targets_uses_visual_order_for_link_only_toc(self):
        mapped = map_visual_items_to_link_targets(
            [
                {"title": "Introduction", "depth": 0, "printed_page": None, "visual_order": 1},
                {"title": "Chapter 1", "depth": 0, "printed_page": None, "visual_order": 2},
            ],
            [
                {"visual_order": 1, "target_file_idx": 7},
                {"visual_order": 2, "target_file_idx": 19},
            ],
        )

        self.assertEqual(mapped[0]["file_idx"], 7)
        self.assertEqual(mapped[1]["file_idx"], 19)

    def test_filter_resolved_visual_toc_anomalies_drops_tail_introduction_outlier(self):
        filtered = _filter_resolved_visual_toc_anomalies(
            [
                {"title": "Acknowledgments", "visual_order": 1, "file_idx": 5},
                {"title": "Chapter 1", "visual_order": 2, "file_idx": 19},
                {"title": "Chapter 2", "visual_order": 3, "file_idx": 41},
                {"title": "Introduction", "visual_order": 4, "file_idx": 461},
            ],
            total_pages=462,
        )

        self.assertEqual([item["title"] for item in filtered], ["Acknowledgments", "Chapter 1", "Chapter 2"])

    def test_filter_resolved_visual_toc_anomalies_drops_large_reverse_jump_between_neighbors(self):
        filtered = _filter_resolved_visual_toc_anomalies(
            [
                {"title": "Chapter 1", "visual_order": 1, "file_idx": 10},
                {"title": "Chapter 2", "visual_order": 2, "file_idx": 40},
                {"title": "Introduction", "visual_order": 3, "file_idx": 461},
                {"title": "Chapter 3", "visual_order": 4, "file_idx": 70},
            ],
            total_pages=462,
        )

        self.assertEqual([item["title"] for item in filtered], ["Chapter 1", "Chapter 2", "Chapter 3"])

    def test_filter_resolved_visual_toc_anomalies_drops_notes_range_reverse_jump(self):
        filtered = _filter_resolved_visual_toc_anomalies(
            [
                {"title": "Chapter 6", "visual_order": 1, "file_idx": 210},
                {"title": "Notes to Pages 302-344", "visual_order": 2, "file_idx": 460},
                {"title": "Chapter 7", "visual_order": 3, "file_idx": 230},
            ],
            total_pages=462,
        )

        self.assertEqual([item["title"] for item in filtered], ["Chapter 6", "Chapter 7"])

    def test_filter_resolved_visual_toc_anomalies_drops_note_on_sources_reverse_jump(self):
        filtered = _filter_resolved_visual_toc_anomalies(
            [
                {"title": "Chapter 7", "visual_order": 1, "file_idx": 230},
                {"title": "Note on Sources", "visual_order": 2, "file_idx": 460},
                {"title": "Index", "visual_order": 3, "file_idx": 420},
            ],
            total_pages=462,
        )

        self.assertEqual([item["title"] for item in filtered], ["Chapter 7", "Index"])

    def test_vision_probe_accepts_relation_match_instead_of_exact_pixel_count(self):
        self.assertTrue(_vision_probe_passed([2, 4, 0, 2], True))
        self.assertFalse(_vision_probe_passed([2, 2, 1, 2], True))


if __name__ == "__main__":
    unittest.main()

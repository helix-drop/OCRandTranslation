#!/usr/bin/env python3
"""FNM real 模式失败处理与导出门槛测试。"""

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import app as app_module
import config
from config import create_doc, ensure_dirs
from persistence.fnm_export_bundle import save_fnm_export_bundle
from persistence.sqlite_store import SQLiteRepository
from persistence.storage import save_pages_to_disk
from testsupport import ClientCSRFMixin
from web.translation_routes import _resolve_fnm_workflow_state
from translation.translate_state import (
    TASK_KIND_FNM,
    _build_translate_task_meta,
    _default_stream_draft_state,
)
from translation.translate_store import _save_translate_state


class FnmRealModeIntegrationTest(ClientCSRFMixin, unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="fnm-real-mode-")
        self._patch_config_dirs(self.temp_root)
        ensure_dirs()
        self.client = app_module.app.test_client()
        self.doc_id = create_doc("fnm-real-mode.pdf")
        self.repo = SQLiteRepository()
        self.repo.upsert_document(self.doc_id, "fnm-real-mode.pdf", page_count=2)
        save_pages_to_disk(
            [
                {
                    "bookPage": 1,
                    "fileIdx": 0,
                    "imgW": 100,
                    "imgH": 100,
                    "markdown": "Body one",
                    "footnotes": "",
                    "textSource": "ocr",
                },
                {
                    "bookPage": 2,
                    "fileIdx": 1,
                    "imgW": 100,
                    "imgH": 100,
                    "markdown": "Body two",
                    "footnotes": "",
                    "textSource": "ocr",
                },
            ],
            "fnm-real-mode.pdf",
            self.doc_id,
        )
        run_id = self.repo.create_fnm_run(
            self.doc_id,
            status="done",
            page_count=2,
            section_count=1,
            note_count=0,
            unit_count=1,
        )
        self.repo.replace_fnm_data(
            self.doc_id,
            notes=[],
            units=[
                {
                    "unit_id": "body-sec-01-demo-0001",
                    "kind": "body",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 2,
                    "note_id": None,
                    "page_start": 1,
                    "page_end": 2,
                    "char_count": 16,
                    "source_text": "Body one\n\nBody two",
                    "translated_text": None,
                    "status": "error",
                    "error_msg": "第 1 段翻译失败：HTTP 400",
                    "target_ref": "",
                    "page_segments": [
                        {
                            "page_no": 1,
                            "paragraph_count": 1,
                            "source_text": "Body one",
                            "display_text": "Body one",
                            "paragraphs": [
                                {
                                    "order": 1,
                                    "kind": "body",
                                    "heading_level": 0,
                                    "source_text": "Body one",
                                    "display_text": "Body one",
                                    "cross_page": None,
                                    "consumed_by_prev": False,
                                    "section_path": ["Demo"],
                                    "print_page_label": "1",
                                    "translated_text": "",
                                    "translation_status": "manual_required",
                                    "attempt_count": 4,
                                    "last_error": "HTTP 400",
                                    "manual_resolved": False,
                                }
                            ],
                        },
                        {
                            "page_no": 2,
                            "paragraph_count": 1,
                            "source_text": "Body two",
                            "display_text": "Body two",
                            "paragraphs": [
                                {
                                    "order": 1,
                                    "kind": "body",
                                    "heading_level": 0,
                                    "source_text": "Body two",
                                    "display_text": "Body two",
                                    "cross_page": None,
                                    "consumed_by_prev": False,
                                    "section_path": ["Demo"],
                                    "print_page_label": "2",
                                    "translated_text": "正文译文二",
                                    "translation_status": "done",
                                    "attempt_count": 1,
                                    "last_error": "",
                                    "manual_resolved": False,
                                }
                            ],
                        },
                    ],
                }
            ],
        )
        self.repo.update_fnm_run(self.doc_id, run_id, status="done", error_msg="")
        _save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=1,
            total_pages=1,
            done_pages=0,
            processed_pages=1,
            pending_pages=0,
            current_bp=1,
            current_page_idx=1,
            translated_chars=0,
            translated_paras=0,
            request_count=0,
            prompt_tokens=0,
            completion_tokens=0,
            model="qwen-plus",
            last_error="HTTP 400",
            failed_bps=[],
            partial_failed_bps=[],
            failed_pages=[],
            draft=_default_stream_draft_state(),
            execution_mode="real",
            retry_round=3,
            unresolved_count=1,
            manual_required_count=1,
            next_failed_location={
                "unit_id": "body-sec-01-demo-0001",
                "page_no": 1,
                "para_idx": 0,
                "error": "HTTP 400",
                "status": "manual_required",
            },
            failed_locations=[
                {
                    "unit_id": "body-sec-01-demo-0001",
                    "section_title": "Demo",
                    "page_no": 1,
                    "para_idx": 0,
                    "error": "HTTP 400",
                    "status": "manual_required",
                }
            ],
            manual_required_locations=[
                {
                    "unit_id": "body-sec-01-demo-0001",
                    "section_title": "Demo",
                    "page_no": 1,
                    "para_idx": 0,
                    "error": "HTTP 400",
                    "status": "manual_required",
                }
            ],
        )

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def test_api_doc_fnm_status_reports_real_mode_blockers(self):
        resp = self.client.get(f"/api/doc/{self.doc_id}/fnm/status")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["blocking_export"])
        self.assertEqual(payload["retry_progress"]["retry_round"], 3)
        self.assertEqual(payload["retry_progress"]["manual_required_count"], 1)
        self.assertEqual(len(payload["failed_locations"]), 1)
        self.assertEqual(len(payload["manual_required_locations"]), 1)
        self.assertIn("chapter_progress_summary", payload)
        self.assertIn("note_region_progress_summary", payload)
        self.assertIn("run_phase_label", payload)
        self.assertIn("workflow_state", payload)
        self.assertIn("workflow_state_label", payload)
        self.assertIn("full_flow_available", payload)
        self.assertIn("gate_pass_count", payload)
        self.assertIn("gate_fail_count", payload)
        self.assertIn("gate_total_count", payload)
        self.assertIn("gate_failed_labels", payload)

    def test_api_doc_fnm_status_labels_translation_retrying_as_translating(self):
        _save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            execution_mode="real",
            fnm_tail_state="translation_retrying",
            draft={
                **_default_stream_draft_state(),
                "status": "streaming",
                "note": "当前 unit 已提交，准备继续后续 unit。",
            },
        )

        resp = self.client.get(f"/api/doc/{self.doc_id}/fnm/status")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(payload["fnm_tail_state"], "translation_retrying")
        self.assertFalse(payload["fnm_post_translate_running"])
        self.assertNotEqual(payload["workflow_state"], "post_translate_checking")
        self.assertNotEqual(payload["workflow_state"], "translating_retrying")
        self.assertFalse(payload["pause_translate_available"])

        _save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            execution_mode="real",
            fnm_tail_state="post_translate_checking",
            draft=_default_stream_draft_state(),
        )
        resp = self.client.get(f"/api/doc/{self.doc_id}/fnm/status")
        payload = resp.get_json()
        self.assertFalse(payload["fnm_post_translate_running"])
        self.assertNotEqual(payload["workflow_state"], "post_translate_checking")

        with patch("web.translation_routes._is_fnm_post_translate_running", return_value=True):
            resp = self.client.get(f"/api/doc/{self.doc_id}/fnm/status")
            payload = resp.get_json()
        self.assertTrue(payload["fnm_post_translate_running"])
        self.assertEqual(payload["workflow_state"], "post_translate_checking")
        self.assertEqual(payload["workflow_state_label"], "最终校验中")

        state, label = _resolve_fnm_workflow_state(
            run_status="done",
            full_flow_running=False,
            continue_running=False,
            post_translate_running=True,
            fnm_tail_state="translation_retrying",
            translate_running=True,
            can_translate=True,
            export_ready_real=False,
        )
        self.assertEqual(state, "translating_retrying")
        self.assertEqual(label, "翻译重试中")

        state, label = _resolve_fnm_workflow_state(
            run_status="done",
            full_flow_running=False,
            continue_running=False,
            post_translate_running=True,
            fnm_tail_state="translation_retrying",
            translate_running=False,
            can_translate=True,
            export_ready_real=False,
        )
        self.assertEqual(state, "post_translate_checking")
        self.assertEqual(label, "最终校验中")

    def test_api_doc_fnm_full_flow_starts_translate_when_ready(self):
        called = {"pipeline": 0, "translate": 0}

        def _fake_pipeline(doc_id: str):
            called["pipeline"] += 1
            return {"ok": True, "doc_id": doc_id}

        def _fake_start_translate(*_args, **_kwargs):
            called["translate"] += 1
            return True

        with (
            patch("web.translation_routes.run_fnm_pipeline", side_effect=_fake_pipeline),
            patch("translation.translate_launch.start_fnm_translate_task", side_effect=_fake_start_translate),
        ):
            resp = self._post(
                f"/api/doc/{self.doc_id}/fnm/full-flow",
                data={"execution_mode": "test"},
            )
            for _ in range(30):
                if called["translate"] > 0:
                    break
                time.sleep(0.01)

        payload = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "started")
        self.assertEqual(called["pipeline"], 0)
        self.assertEqual(called["translate"], 1)

    def test_api_doc_fnm_full_flow_runs_post_translate_checks_when_units_already_done(self):
        called = {"pipeline": 0, "translate": 0, "post_check": 0}
        self.repo.replace_fnm_data(
            self.doc_id,
            notes=[],
            units=[
                {
                    "unit_id": "body-sec-01-demo-0001",
                    "kind": "body",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 2,
                    "note_id": None,
                    "page_start": 1,
                    "page_end": 2,
                    "char_count": 16,
                    "source_text": "Body one\n\nBody two",
                    "translated_text": "正文一\n\n正文二",
                    "status": "done",
                    "error_msg": "",
                    "target_ref": "",
                    "page_segments": [
                        {
                            "page_no": 1,
                            "paragraph_count": 1,
                            "source_text": "Body one",
                            "display_text": "Body one",
                            "paragraphs": [
                                {
                                    "order": 1,
                                    "kind": "body",
                                    "heading_level": 0,
                                    "source_text": "Body one",
                                    "display_text": "Body one",
                                    "cross_page": None,
                                    "consumed_by_prev": False,
                                    "section_path": ["Demo"],
                                    "print_page_label": "1",
                                    "translated_text": "正文一",
                                    "translation_status": "done",
                                    "attempt_count": 1,
                                    "last_error": "",
                                    "manual_resolved": False,
                                }
                            ],
                        },
                        {
                            "page_no": 2,
                            "paragraph_count": 1,
                            "source_text": "Body two",
                            "display_text": "Body two",
                            "paragraphs": [
                                {
                                    "order": 1,
                                    "kind": "body",
                                    "heading_level": 0,
                                    "source_text": "Body two",
                                    "display_text": "Body two",
                                    "cross_page": None,
                                    "consumed_by_prev": False,
                                    "section_path": ["Demo"],
                                    "print_page_label": "2",
                                    "translated_text": "正文二",
                                    "translation_status": "done",
                                    "attempt_count": 1,
                                    "last_error": "",
                                    "manual_resolved": False,
                                }
                            ],
                        },
                    ],
                }
            ],
        )

        def _fake_pipeline(doc_id: str):
            called["pipeline"] += 1
            return {"ok": True, "doc_id": doc_id}

        def _fake_start_translate(*_args, **_kwargs):
            called["translate"] += 1
            return True

        def _fake_post_check(*_args, **_kwargs):
            called["post_check"] += 1
            return {"ok": True, "export_ready_real": True}

        with (
            patch("web.translation_routes.run_fnm_pipeline", side_effect=_fake_pipeline),
            patch("translation.translate_launch.start_fnm_translate_task", side_effect=_fake_start_translate),
            patch("web.translation_routes.run_post_translate_export_checks_for_doc", side_effect=_fake_post_check),
            patch(
                "web.translation_routes.build_fnm_structure_status",
                return_value={
                    "structure_state": "ready",
                    "manual_toc_required": False,
                    "blocking_reasons": [],
                },
            ),
            patch(
                "persistence.storage.get_translate_args",
                return_value={"api_key": "test-key", "display_label": "Qwen-MT-Plus"},
            ),
        ):
            resp = self._post(
                f"/api/doc/{self.doc_id}/fnm/full-flow",
                data={"execution_mode": "real"},
            )
            for _ in range(30):
                if called["post_check"] > 0:
                    break
                time.sleep(0.01)

        payload = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "started")
        self.assertEqual(called["pipeline"], 0)
        self.assertEqual(called["translate"], 0)
        self.assertEqual(called["post_check"], 1)

    def test_api_doc_fnm_continue_starts_background_rebuild(self):
        called = {"doc_id": ""}

        def _fake_run(doc_id: str):
            called["doc_id"] = doc_id
            return {"ok": True}

        with patch("web.translation_routes.run_fnm_pipeline", side_effect=_fake_run):
            resp = self._post(
                f"/api/doc/{self.doc_id}/fnm/continue",
            )
            for _ in range(30):
                if called["doc_id"]:
                    break
                time.sleep(0.01)

        payload = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "started")
        self.assertEqual(called["doc_id"], self.doc_id)

    def test_download_md_blocks_fnm_export_until_tail_done(self):
        save_fnm_export_bundle(
            self.doc_id,
            {
                "markdown": "# Demo",
                "chapter_files": {"Demo.md": "# Demo"},
                "chapter_order": ["Demo.md"],
                "files": {"index.md": "# Demo", "Demo.md": "# Demo"},
                "export_ready_real": False,
            },
        )
        _save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            execution_mode="real",
            fnm_tail_state="post_translate_checking",
            export_bundle_available=False,
            export_has_blockers=True,
            tail_blocking_summary=["manual_required"],
        )

        resp = self.client.get(
            "/download_md",
            query_string={"doc_id": self.doc_id, "format": "fnm_obsidian"},
        )

        payload = resp.get_json()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(payload["error"], "fnm_export_pending_tail")
        self.assertEqual(payload["reason"], "tail_state_post_translate_checking")

    def test_download_md_allows_tail_done_bundle_even_with_blockers(self):
        save_fnm_export_bundle(
            self.doc_id,
            {
                "markdown": "# Demo",
                "chapter_files": {"Demo.md": "# Demo"},
                "chapter_order": ["Demo.md"],
                "files": {"index.md": "# Demo", "Demo.md": "# Demo"},
                "export_ready_real": False,
            },
        )
        _save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            execution_mode="real",
            fnm_tail_state="done",
            export_bundle_available=True,
            export_has_blockers=True,
            tail_blocking_summary=["manual_required:p.1 ¶1"],
        )

        with patch("web.export_routes.build_doc_status", side_effect=AssertionError("tail done should bypass old blockers")):
            resp = self.client.get(
                "/download_md",
                query_string={"doc_id": self.doc_id, "format": "fnm_obsidian"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "application/zip")
        self.assertTrue(resp.data.startswith(b"PK"))

    def test_api_doc_fnm_status_reports_bundle_available_after_tail_done_with_blockers(self):
        save_fnm_export_bundle(
            self.doc_id,
            {
                "markdown": "# Demo",
                "chapter_files": {"Demo.md": "# Demo"},
                "chapter_order": ["Demo.md"],
                "export_ready_real": False,
            },
        )
        _save_translate_state(
            self.doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            execution_mode="real",
            fnm_tail_state="done",
            export_bundle_available=True,
            export_has_blockers=True,
            tail_blocking_summary=[
                "manual_required:p.1 ¶1",
                "repair_rounds_exhausted",
            ],
        )

        resp = self.client.get(f"/api/doc/{self.doc_id}/fnm/status")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(payload["fnm_tail_state"], "done")
        self.assertTrue(payload["export_bundle_available"])
        self.assertTrue(payload["export_has_blockers"])
        self.assertEqual(
            payload["tail_blocking_summary"],
            ["manual_required:p.1 ¶1", "repair_rounds_exhausted"],
        )
        self.assertFalse(payload["export_ready_real"])

    def test_api_doc_fnm_status_includes_live_translate_draft_fields(self):
        _save_translate_state(
            self.doc_id,
            running=True,
            stop_requested=False,
            phase="running",
            start_bp=1,
            total_pages=1,
            done_pages=0,
            processed_pages=0,
            pending_pages=1,
            current_bp=1,
            current_page_idx=1,
            translated_chars=0,
            translated_paras=0,
            request_count=1,
            prompt_tokens=12,
            completion_tokens=8,
            model="qwen-plus",
            last_error="模型请求失败（HTTP 400）：invalid_request",
            execution_mode="real",
            task=_build_translate_task_meta(
                kind=TASK_KIND_FNM,
                label="FNM 翻译",
                start_bp=1,
                progress_mode="unit",
                start_unit_idx=1,
                log_relpath="sessions/translate_fnm_test.log",
            ),
            draft={
                **_default_stream_draft_state(),
                "active": True,
                "mode": "fnm_unit",
                "status": "streaming",
                "note": "当前正在翻译第 2 段",
                "para_idx": 1,
                "para_done": 1,
                "para_total": 3,
            },
        )
        resp = self.client.get(f"/api/doc/{self.doc_id}/fnm/status")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertIn(payload["translate_phase"], {"running", "partial_failed"})
        self.assertIn("HTTP 400", payload["translate_last_error"])
        self.assertEqual(payload["translate_task_kind"], "fnm")
        self.assertEqual(payload["translate_log_relpath"], "sessions/translate_fnm_test.log")
        self.assertIn(payload["draft_status"], {"streaming", "aborted"})
        self.assertIn(payload["draft_note"], {"当前正在翻译第 2 段", "后台翻译未处于活动状态，当前页草稿已中断。"})
        self.assertEqual(payload["draft_para_done"], 1)
        self.assertEqual(payload["draft_para_total"], 3)

    def test_api_doc_fnm_status_returns_not_found_when_doc_dir_missing(self):
        shutil.rmtree(config.get_doc_dir(self.doc_id), ignore_errors=True)

        resp = self.client.get(f"/api/doc/{self.doc_id}/fnm/status")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(payload["error"], "doc_not_found")

    def test_export_md_allows_real_mode_when_manual_required_locations_remain(self):
        with (
            patch(
                "web.export_routes.build_doc_status",
                return_value={
                    "export_ready_test": True,
                    "structure_state": "ready",
                    "blocking_reasons": [],
                    "manual_toc_required": False,
                    "link_summary": {},
                },
            ),
            patch(
                "FNM_RE.app.mainline.build_phase6_export_bundle_for_doc",
                return_value={"chapter_files": {"chapters/demo.md": "demo markdown"}},
            ),
        ):
            resp = self.client.get(f"/export_md?doc_id={self.doc_id}&format=fnm_obsidian")
            payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertIn("markdown", payload)

    def test_export_md_does_not_block_on_export_stage_validation_reasons(self):
        with (
            patch(
                "web.export_routes.build_doc_status",
                return_value={
                    "export_ready_test": False,
                    "structure_state": "review_required",
                    "blocking_reasons": ["merge_frozen_ref_leak", "export_audit_blocking"],
                    "manual_toc_required": False,
                    "link_summary": {},
                },
            ),
            patch(
                "web.export_routes.build_retry_summary",
                return_value={"blocking_export": False},
            ),
            patch(
                "FNM_RE.app.mainline.build_phase6_export_bundle_for_doc",
                return_value={"chapter_files": {"chapters/demo.md": "demo markdown"}},
            ),
        ):
            resp = self.client.get(f"/export_md?doc_id={self.doc_id}&format=fnm_obsidian")
            payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertIn("markdown", payload)

    def test_export_md_still_blocks_on_pre_export_reasons(self):
        with (
            patch(
                "web.export_routes.build_doc_status",
                return_value={
                    "export_ready_test": False,
                    "structure_state": "review_required",
                    "blocking_reasons": ["toc_manual_toc_required"],
                    "manual_toc_required": True,
                    "link_summary": {},
                },
            ),
            patch(
                "web.export_routes.build_retry_summary",
                return_value={"blocking_export": False},
            ),
        ):
            resp = self.client.get(f"/export_md?doc_id={self.doc_id}&format=fnm_obsidian")
            payload = resp.get_json()

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(payload.get("error"), "fnm_export_blocked")
        self.assertEqual(payload.get("reason"), "manual_toc_required")


if __name__ == "__main__":
    unittest.main()

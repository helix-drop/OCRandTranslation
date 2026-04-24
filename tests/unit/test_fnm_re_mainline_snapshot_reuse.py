from __future__ import annotations

from io import BytesIO
import json
import zipfile
import unittest
from unittest.mock import patch

from FNM_RE.app import mainline
from FNM_RE.models import (
    ExportAuditFileRecord,
    ExportAuditReportRecord,
    ExportBundleRecord,
    ExportChapterRecord,
    NoteLinkRecord,
    Phase6Structure,
    Phase6Summary,
    StructureStatusRecord,
    TranslationUnitRecord,
    UnitPageSegmentRecord,
    UnitParagraphRecord,
)
import translation.translate_store as translate_store


class FnmReMainlineSnapshotReuseTest(unittest.TestCase):
    def test_persist_phase6_to_repo_writes_effective_note_links(self):
        raw_link = NoteLinkRecord(
            link_id="link-raw",
            chapter_id="ch-1",
            region_id="region-1",
            note_item_id="note-1",
            anchor_id="anchor-old",
            status="matched",
            resolver="rule",
            confidence=1.0,
            note_kind="footnote",
            marker="1",
            page_no_start=10,
            page_no_end=10,
        )
        effective_link = NoteLinkRecord(
            link_id="link-raw",
            chapter_id="ch-1",
            region_id="region-1",
            note_item_id="note-1",
            anchor_id="anchor-new",
            status="matched",
            resolver="repair",
            confidence=1.0,
            note_kind="footnote",
            marker="1",
            page_no_start=10,
            page_no_end=10,
        )
        phase6 = Phase6Structure(
            note_links=[raw_link],
            effective_note_links=[effective_link],
            status=StructureStatusRecord(structure_state="ready"),
            summary=Phase6Summary(),
        )

        class _FakeRepo:
            def __init__(self):
                self.structure_kwargs = {}
                self.data_kwargs = {}

            def replace_fnm_structure(self, _doc_id, **kwargs):
                self.structure_kwargs = dict(kwargs)

            def replace_fnm_data(self, _doc_id, **kwargs):
                self.data_kwargs = dict(kwargs)

        repo = _FakeRepo()
        original_clear = translate_store._clear_translate_state
        try:
            translate_store._clear_translate_state = lambda _doc_id: None
            mainline._persist_phase6_to_repo("doc-persist", phase6, repo=repo)
        finally:
            translate_store._clear_translate_state = original_clear

        persisted_links = list(repo.structure_kwargs.get("note_links") or [])
        self.assertEqual(len(persisted_links), 1)
        self.assertEqual(persisted_links[0].get("anchor_id"), "anchor-new")
        self.assertEqual(persisted_links[0].get("resolver"), "repair")

    def test_load_phase6_for_doc_keeps_synthesized_note_items_from_overrides(self):
        pages = [
            {
                "bookPage": 1,
                "fileIdx": 0,
                "target_pdf_page": 1,
                "markdown": "# Chapter One\nBody ¹.",
                "footnotes": "",
                "prunedResult": {
                    "height": 1200,
                    "width": 900,
                    "parsing_res_list": [
                        {
                            "block_label": "doc_title",
                            "block_content": "Chapter One",
                            "block_order": 1,
                            "block_bbox": [100.0, 120.0, 860.0, 180.0],
                        }
                    ],
                },
            }
        ]

        class _FakeRepo:
            def get_latest_fnm_run(self, _doc_id):
                return {"status": "done", "validation_json": "{}"}

            def load_pages(self, _doc_id):
                return list(pages)

            def list_fnm_review_overrides(self, _doc_id):
                return [
                    {
                        "scope": "note_item",
                        "target_id": "llm-note-anchor-1",
                        "payload": {
                            "action": "create",
                            "note_item_id": "llm-note-anchor-1",
                            "chapter_id": "toc-ch-001-chapterone",
                            "page_no": 1,
                            "marker": "1",
                            "note_kind": "footnote",
                            "text": "Synthesized note text.",
                            "source": "llm",
                            "source_page_label": "1",
                        },
                    },
                    {
                        "scope": "link",
                        "target_id": "link-00001",
                        "payload": {
                            "action": "match",
                            "note_item_id": "llm-note-anchor-1",
                            "anchor_id": "anchor-00001",
                        },
                    },
                ]

            def list_fnm_translation_units(self, _doc_id):
                return []

            def get_document_toc_for_source(self, *_args, **_kwargs):
                return []

            def get_document_toc(self, *_args, **_kwargs):
                return []

            def get_document_toc_source_offset(self, *_args, **_kwargs):
                return ("", 0)

        phase6 = mainline.load_phase6_for_doc("doc-synth-note", repo=_FakeRepo(), slug="doc-synth-note")
        note_item_ids = {row.note_item_id for row in phase6.note_items}
        self.assertIn("llm-note-anchor-1", note_item_ids)
        synthesized = next(row for row in phase6.note_items if row.note_item_id == "llm-note-anchor-1")
        self.assertEqual(synthesized.text, "Synthesized note text.")
        self.assertTrue(any(row.note_item_id == "llm-note-anchor-1" for row in phase6.effective_note_links))

    def test_build_phase6_status_for_doc_reuses_passed_phase6_snapshot(self):
        phase6 = Phase6Structure(
            status=StructureStatusRecord(structure_state="ready", export_ready_test=True, export_ready_real=True),
            summary=Phase6Summary(),
        )

        class _FakeRepo:
            def get_latest_fnm_run(self, _doc_id):
                return {"validation_json": "{}"}

        def _boom(*_args, **_kwargs):
            raise AssertionError("不应重复构建 phase6 snapshot")

        original_loader = mainline.load_phase6_for_doc
        try:
            mainline.load_phase6_for_doc = _boom
            payload = mainline.build_phase6_status_for_doc("doc-snapshot", repo=_FakeRepo(), snapshot=phase6)
        finally:
            mainline.load_phase6_for_doc = original_loader

        self.assertEqual(payload.get("structure_state"), "ready")
        self.assertTrue(bool(payload.get("export_ready_test")))

    def test_build_phase6_export_bundle_and_zip_reuse_passed_snapshot(self):
        phase6 = Phase6Structure(
            export_bundle=ExportBundleRecord(
                index_path="index.md",
                chapter_files={"chapters/001-demo.md": "Demo body\n"},
                files={"index.md": "# Demo\n", "chapters/001-demo.md": "Demo body\n"},
            ),
            status=StructureStatusRecord(structure_state="ready"),
            summary=Phase6Summary(),
        )

        def _boom(*_args, **_kwargs):
            raise AssertionError("不应重复构建 phase6 snapshot")

        original_loader = mainline.load_phase6_for_doc
        try:
            mainline.load_phase6_for_doc = _boom
            bundle = mainline.build_phase6_export_bundle_for_doc("doc-snapshot", snapshot=phase6)
            zip_bytes = mainline.build_phase6_export_zip_for_doc("doc-snapshot", snapshot=phase6)
        finally:
            mainline.load_phase6_for_doc = original_loader

        self.assertIn("index.md", bundle.get("files", {}))
        self.assertIsInstance(zip_bytes, bytes)
        self.assertGreater(len(zip_bytes), 0)

    def test_build_phase6_export_bundle_and_zip_load_persisted_bundle_without_rebuilding_snapshot(self):
        persisted_bundle = {
            "index_path": "index.md",
            "chapters": [
                {
                    "order": 1,
                    "section_id": "ch-1",
                    "title": "Demo",
                    "path": "chapters/001-demo.md",
                }
            ],
            "chapter_files": {"chapters/001-demo.md": "Demo body\n"},
            "files": {"index.md": "# Demo\n", "chapters/001-demo.md": "Demo body\n"},
            "export_semantic_contract_ok": False,
            "front_matter_leak_detected": False,
            "toc_residue_detected": False,
            "mid_paragraph_heading_detected": False,
            "duplicate_paragraph_detected": False,
        }

        class _FakeRepo:
            def get_latest_fnm_run(self, _doc_id):
                return {
                    "structure_state": "review_required",
                    "validation_json": json.dumps(
                        {
                            "blocking_reasons": ["export_audit_blocking"],
                            "post_translate_export_check": {
                                "final_blocking_files": [
                                    {
                                        "path": "chapters/001-demo.md",
                                        "title": "Demo",
                                        "page_span": [41, 41],
                                        "issue_codes": ["raw_note_marker_leak"],
                                        "issue_summary": ["raw_note_marker_leak: detected"],
                                        "issue_details": [
                                            {
                                                "code": "raw_note_marker_leak",
                                                "detail": "detected",
                                                "paragraph_index": 4,
                                                "excerpt": "A raw marker leaked here.",
                                            }
                                        ],
                                        "severity": "blocking",
                                    }
                                ],
                                "repair_rounds": [
                                    {
                                        "round": 1,
                                        "suggestion_count": 1,
                                        "auto_applied_count": 0,
                                        "post_round_can_ship": False,
                                        "post_round_blocking_reasons": ["export_audit_blocking"],
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                }

        def _boom(*_args, **_kwargs):
            raise AssertionError("不应回退重建 phase6 snapshot")

        with (
            patch("FNM_RE.app.mainline.load_phase6_for_doc", side_effect=_boom),
            patch("FNM_RE.app.mainline.load_fnm_export_bundle", return_value=persisted_bundle),
        ):
            bundle = mainline.build_phase6_export_bundle_for_doc("doc-persisted", repo=_FakeRepo())
            zip_bytes = mainline.build_phase6_export_zip_for_doc("doc-persisted", repo=_FakeRepo())

        self.assertIn("index.md", bundle.get("files", {}))
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as archive:
            log_text = archive.read("logs/fnm_export_validation_issues.log").decode("utf-8")

        self.assertIn("export_audit_blocking", log_text)
        self.assertIn("段落=4", log_text)
        self.assertIn("第 1 轮", log_text)

    def test_build_phase6_export_zip_includes_validation_log_when_export_checks_fail(self):
        phase6 = Phase6Structure(
            export_bundle=ExportBundleRecord(
                index_path="index.md",
                chapters=[
                    ExportChapterRecord(
                        order=1,
                        section_id="ch-1",
                        title="Demo",
                        path="chapters/001-demo.md",
                        content="Demo body\n",
                        start_page=36,
                        end_page=36,
                        pages=[36],
                    )
                ],
                chapter_files={"chapters/001-demo.md": "Demo body\n"},
                files={"index.md": "# Demo\n", "chapters/001-demo.md": "Demo body\n"},
            ),
            export_audit=ExportAuditReportRecord(
                can_ship=False,
                blocking_issue_count=1,
                files=[
                    ExportAuditFileRecord(
                        path="chapters/001-demo.md",
                        title="Demo",
                        page_span=[36, 36],
                        issue_codes=["raw_note_marker_leak"],
                        issue_summary=["raw_note_marker_leak: unresolved marker in body paragraph"],
                        issue_details=[
                            {
                                "code": "raw_note_marker_leak",
                                "detail": "detected",
                                "paragraph_index": 3,
                                "excerpt": "A leaked note marker remains in paragraph three.",
                            }
                        ],
                        severity="blocking",
                    )
                ],
            ),
            status=StructureStatusRecord(
                structure_state="review_required",
                blocking_reasons=["merge_frozen_ref_leak", "export_audit_blocking"],
            ),
            summary=Phase6Summary(),
        )

        zip_bytes = mainline.build_phase6_export_zip_for_doc("doc-snapshot", snapshot=phase6)
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as archive:
            names = set(archive.namelist())
            self.assertIn("logs/fnm_export_validation_issues.log", names)
            log_text = archive.read("logs/fnm_export_validation_issues.log").decode("utf-8")

        self.assertIn("merge_frozen_ref_leak", log_text)
        self.assertIn("export_audit_blocking", log_text)
        self.assertIn("raw_note_marker_leak", log_text)
        self.assertIn("p.36", log_text)
        self.assertIn("段落=3", log_text)
        self.assertIn("paragraph three", log_text)

    def test_build_phase6_export_zip_includes_post_translate_repair_history(self):
        phase6 = Phase6Structure(
            export_bundle=ExportBundleRecord(
                index_path="index.md",
                chapter_files={"chapters/001-demo.md": "Demo body\n"},
                files={"index.md": "# Demo\n", "chapters/001-demo.md": "Demo body\n"},
            ),
            export_audit=ExportAuditReportRecord(
                can_ship=False,
                blocking_issue_count=1,
                files=[
                    ExportAuditFileRecord(
                        path="chapters/001-demo.md",
                        title="Demo",
                        page_span=[40, 42],
                        issue_codes=["chapter_boundary_missing_tail"],
                        issue_summary=["chapter_boundary_missing_tail: tail is truncated"],
                        issue_details=[
                            {
                                "code": "chapter_boundary_missing_tail",
                                "detail": "tail is truncated",
                                "paragraph_index": 8,
                                "excerpt": "The chapter stops in the middle of a sentence",
                            }
                        ],
                        severity="blocking",
                    )
                ],
            ),
            status=StructureStatusRecord(
                structure_state="review_required",
                blocking_reasons=["export_audit_blocking"],
            ),
            summary=Phase6Summary(),
        )

        class _FakeRepo:
            def get_latest_fnm_run(self, _doc_id):
                return {
                    "validation_json": json.dumps(
                        {
                            "post_translate_export_check": {
                                "repair_rounds": [
                                    {
                                        "round": 1,
                                        "suggestion_count": 2,
                                        "auto_applied_count": 1,
                                        "auto_action_counts": {"match": 1},
                                        "post_round_can_ship": False,
                                        "post_round_blocking_reasons": ["export_audit_blocking"],
                                    },
                                    {
                                        "round": 2,
                                        "error": "LLM timeout",
                                    },
                                ]
                            }
                        },
                        ensure_ascii=False,
                    )
                }

        with patch("FNM_RE.app.mainline.SQLiteRepository", return_value=_FakeRepo()):
            zip_bytes = mainline.build_phase6_export_zip_for_doc("doc-snapshot", snapshot=phase6)
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as archive:
            log_text = archive.read("logs/fnm_export_validation_issues.log").decode("utf-8")

        self.assertIn("自动修补记录", log_text)
        self.assertIn("第 1 轮", log_text)
        self.assertIn("match=1", log_text)
        self.assertIn("第 2 轮", log_text)
        self.assertIn("LLM timeout", log_text)

    def test_run_post_translate_export_checks_retries_three_rounds_and_persists_history(self):
        blocked_phase6 = Phase6Structure(
            export_audit=ExportAuditReportRecord(
                can_ship=False,
                blocking_issue_count=1,
                files=[
                    ExportAuditFileRecord(
                        path="chapters/001-demo.md",
                        title="Demo",
                        page_span=[12, 12],
                        issue_codes=["raw_note_marker_leak"],
                        issue_summary=["raw_note_marker_leak: detected"],
                        issue_details=[
                            {
                                "code": "raw_note_marker_leak",
                                "detail": "detected",
                                "paragraph_index": 2,
                                "excerpt": "A raw marker leaked here.",
                            }
                        ],
                        severity="blocking",
                    )
                ],
            ),
            status=StructureStatusRecord(
                structure_state="review_required",
                blocking_reasons=["export_audit_blocking"],
                export_ready_real=False,
            ),
            summary=Phase6Summary(),
        )

        class _FakeRepo:
            def __init__(self):
                self.validation_json = "{}"

            def load_pages(self, _doc_id):
                return [{"bookPage": 1, "markdown": "demo"}]

            def replace_fnm_structure(self, _doc_id, **_kwargs):
                return None

            def replace_fnm_data(self, _doc_id, **_kwargs):
                return None

            def get_latest_fnm_run(self, _doc_id):
                return {
                    "id": 7,
                    "status": "done",
                    "validation_json": self.validation_json,
                }

            def update_fnm_run(self, _doc_id, _run_id, **fields):
                if fields.get("validation_json"):
                    self.validation_json = str(fields.get("validation_json") or "{}")

            def list_fnm_translation_units(self, _doc_id):
                return []

        repo = _FakeRepo()
        clear_calls: list[str] = []
        saved_export_bundle: dict[str, object] = {}
        repair_results = [
            {"suggestion_count": 2, "auto_applied_count": 1, "action_counts": {"match": 2}, "auto_action_counts": {"match": 1}, "usage_summary": {}},
            {"suggestion_count": 1, "auto_applied_count": 0, "action_counts": {"needs_review": 1}, "auto_action_counts": {}, "usage_summary": {}},
            {"suggestion_count": 1, "auto_applied_count": 0, "action_counts": {"needs_review": 1}, "auto_action_counts": {}, "usage_summary": {}},
        ]

        with (
            patch("FNM_RE.app.mainline.load_phase6_for_doc", side_effect=[blocked_phase6, blocked_phase6]),
            patch("FNM_RE.llm_repair.run_llm_repair", side_effect=repair_results) as run_repair,
            patch("translation.translate_store._clear_translate_state", side_effect=lambda doc_id: clear_calls.append(doc_id)),
            patch("FNM_RE.app.mainline.clear_fnm_export_bundle"),
            patch("translation.translate_store.SQLiteRepository"),
            patch(
                "FNM_RE.app.mainline.save_fnm_export_bundle",
                side_effect=lambda doc_id, payload: saved_export_bundle.update({"doc_id": doc_id, "payload": payload}),
            ),
        ):
            result = mainline.run_post_translate_export_checks_for_doc("doc-post-translate", repo=repo, max_repair_rounds=3)

        self.assertTrue(result["ok"])
        self.assertFalse(result["export_ready_real"])
        self.assertEqual(len(result["repair_rounds"]), 3)
        self.assertEqual(run_repair.call_count, 3)
        self.assertTrue(run_repair.call_args_list[0].kwargs["clear_materialized_overrides"])
        self.assertFalse(run_repair.call_args_list[1].kwargs["clear_materialized_overrides"])
        self.assertEqual(clear_calls, [])
        payload = json.loads(repo.validation_json)
        history = payload["post_translate_export_check"]
        self.assertEqual(history["attempted_rounds"], 3)
        self.assertFalse(history["final_can_ship"])
        self.assertEqual(len(history["repair_rounds"]), 3)
        self.assertEqual(saved_export_bundle.get("doc_id"), "doc-post-translate")
        self.assertIn("files", dict(saved_export_bundle.get("payload") or {}))

    def test_run_post_translate_export_checks_persists_final_export_bundle(self):
        phase6 = Phase6Structure(
            export_bundle=ExportBundleRecord(
                index_path="index.md",
                chapters=[
                    ExportChapterRecord(
                        order=1,
                        section_id="ch-1",
                        title="Demo",
                        path="chapters/001-demo.md",
                        content="Demo body\n",
                    )
                ],
                chapter_files={"chapters/001-demo.md": "Demo body\n"},
                files={"index.md": "# Demo\n", "chapters/001-demo.md": "Demo body\n"},
            ),
            export_audit=ExportAuditReportRecord(
                can_ship=True,
                blocking_issue_count=0,
            ),
            status=StructureStatusRecord(
                structure_state="ready",
                blocking_reasons=[],
                export_ready_real=True,
            ),
            summary=Phase6Summary(),
        )

        class _FakeRepo:
            def __init__(self):
                self.validation_json = "{}"

            def load_pages(self, _doc_id):
                return [{"bookPage": 1, "markdown": "demo"}]

            def replace_fnm_structure(self, _doc_id, **_kwargs):
                return None

            def replace_fnm_data(self, _doc_id, **_kwargs):
                return None

            def get_latest_fnm_run(self, _doc_id):
                return {
                    "id": 8,
                    "status": "done",
                    "validation_json": self.validation_json,
                }

            def update_fnm_run(self, _doc_id, _run_id, **fields):
                if fields.get("validation_json"):
                    self.validation_json = str(fields.get("validation_json") or "{}")

            def list_fnm_translation_units(self, _doc_id):
                return []

        repo = _FakeRepo()
        saved_export_bundle: dict[str, object] = {}

        with (
            patch("FNM_RE.app.mainline.load_phase6_for_doc", return_value=phase6),
            patch("FNM_RE.app.mainline.clear_fnm_export_bundle") as clear_bundle,
            patch(
                "FNM_RE.app.mainline.save_fnm_export_bundle",
                side_effect=lambda doc_id, payload: saved_export_bundle.update({"doc_id": doc_id, "payload": payload}),
            ),
            patch("translation.translate_store.SQLiteRepository"),
        ):
            result = mainline.run_post_translate_export_checks_for_doc("doc-final-bundle", repo=repo, max_repair_rounds=3)

        self.assertTrue(result["ok"])
        clear_bundle.assert_called_once_with("doc-final-bundle")
        self.assertEqual(saved_export_bundle.get("doc_id"), "doc-final-bundle")
        payload = dict(saved_export_bundle.get("payload") or {})
        self.assertIn("chapters/001-demo.md", payload.get("chapter_files", {}))
        self.assertIn("index.md", payload.get("files", {}))

    def test_run_post_translate_export_checks_preserves_existing_translations_when_rebuilding_snapshot(self):
        translated_phase6 = Phase6Structure(
            translation_units=[
                TranslationUnitRecord(
                    unit_id="body-ch-1-0001",
                    kind="body",
                    owner_kind="chapter",
                    owner_id="ch-1",
                    section_id="ch-1",
                    section_title="Demo",
                    section_start_page=1,
                    section_end_page=1,
                    note_id="",
                    page_start=1,
                    page_end=1,
                    char_count=4,
                    source_text="Body source",
                    translated_text="正文译文",
                    status="done",
                    error_msg="",
                    target_ref="",
                    page_segments=[
                        UnitPageSegmentRecord(
                            page_no=1,
                            paragraph_count=1,
                            source_text="Body source",
                            display_text="Body source",
                            paragraphs=[
                                UnitParagraphRecord(
                                    order=1,
                                    kind="body",
                                    heading_level=0,
                                    source_text="Body source",
                                    display_text="Body source",
                                    cross_page=None,
                                    consumed_by_prev=False,
                                    section_path=["Demo"],
                                    print_page_label="1",
                                    translated_text="正文译文",
                                    translation_status="done",
                                )
                            ],
                        )
                    ],
                )
            ],
            export_bundle=ExportBundleRecord(
                index_path="index.md",
                chapters=[
                    ExportChapterRecord(
                        order=1,
                        section_id="ch-1",
                        title="Demo",
                        path="chapters/001-demo.md",
                        content="正文译文\n",
                    )
                ],
                chapter_files={"chapters/001-demo.md": "正文译文\n"},
                files={"index.md": "# Demo\n", "chapters/001-demo.md": "正文译文\n"},
            ),
            export_audit=ExportAuditReportRecord(
                can_ship=True,
                blocking_issue_count=0,
            ),
            status=StructureStatusRecord(
                structure_state="ready",
                blocking_reasons=[],
                export_ready_real=True,
            ),
            summary=Phase6Summary(),
        )
        pending_phase6 = Phase6Structure(
            translation_units=[
                TranslationUnitRecord(
                    unit_id="body-ch-1-0001",
                    kind="body",
                    owner_kind="chapter",
                    owner_id="ch-1",
                    section_id="ch-1",
                    section_title="Demo",
                    section_start_page=1,
                    section_end_page=1,
                    note_id="",
                    page_start=1,
                    page_end=1,
                    char_count=11,
                    source_text="Body source",
                    translated_text="",
                    status="pending",
                    error_msg="",
                    target_ref="",
                    page_segments=[
                        UnitPageSegmentRecord(
                            page_no=1,
                            paragraph_count=1,
                            source_text="Body source",
                            display_text="Body source",
                            paragraphs=[
                                UnitParagraphRecord(
                                    order=1,
                                    kind="body",
                                    heading_level=0,
                                    source_text="Body source",
                                    display_text="Body source",
                                    cross_page=None,
                                    consumed_by_prev=False,
                                    section_path=["Demo"],
                                    print_page_label="1",
                                )
                            ],
                        )
                    ],
                )
            ],
            export_bundle=ExportBundleRecord(
                index_path="index.md",
                chapters=[
                    ExportChapterRecord(
                        order=1,
                        section_id="ch-1",
                        title="Demo",
                        path="chapters/001-demo.md",
                        content="Body source\n",
                    )
                ],
                chapter_files={"chapters/001-demo.md": "Body source\n"},
                files={"index.md": "# Demo\n", "chapters/001-demo.md": "Body source\n"},
            ),
            export_audit=ExportAuditReportRecord(
                can_ship=True,
                blocking_issue_count=0,
            ),
            status=StructureStatusRecord(
                structure_state="ready",
                blocking_reasons=[],
                export_ready_real=True,
            ),
            summary=Phase6Summary(),
        )

        class _FakeRepo:
            def __init__(self):
                self.validation_json = "{}"
                self.data_kwargs = {}

            def load_pages(self, _doc_id):
                return [{"bookPage": 1, "markdown": "demo"}]

            def replace_fnm_structure(self, _doc_id, **_kwargs):
                return None

            def replace_fnm_data(self, _doc_id, **kwargs):
                self.data_kwargs = dict(kwargs)

            def get_latest_fnm_run(self, _doc_id):
                return {
                    "id": 9,
                    "status": "done",
                    "validation_json": self.validation_json,
                }

            def update_fnm_run(self, _doc_id, _run_id, **fields):
                if fields.get("validation_json"):
                    self.validation_json = str(fields.get("validation_json") or "{}")

            def list_fnm_translation_units(self, _doc_id):
                return []

        repo = _FakeRepo()
        saved_export_bundle: dict[str, object] = {}

        def _fake_loader(*_args, **kwargs):
            if kwargs.get("overlay_repo_units"):
                return translated_phase6
            return pending_phase6

        with (
            patch("FNM_RE.app.mainline.load_phase6_for_doc", side_effect=_fake_loader),
            patch("FNM_RE.app.mainline.clear_fnm_export_bundle"),
            patch(
                "FNM_RE.app.mainline.save_fnm_export_bundle",
                side_effect=lambda doc_id, payload: saved_export_bundle.update({"doc_id": doc_id, "payload": payload}),
            ),
            patch("translation.translate_store.SQLiteRepository"),
        ):
            result = mainline.run_post_translate_export_checks_for_doc("doc-preserve-translations", repo=repo, max_repair_rounds=3)

        self.assertTrue(result["ok"])
        persisted_units = list(repo.data_kwargs.get("units") or [])
        self.assertEqual(len(persisted_units), 1)
        self.assertEqual(persisted_units[0].get("status"), "done")
        self.assertEqual(persisted_units[0].get("translated_text"), "正文译文")
        payload = dict(saved_export_bundle.get("payload") or {})
        self.assertIn("正文译文", str((payload.get("chapter_files") or {}).get("chapters/001-demo.md") or ""))

    def test_load_module_snapshot_for_doc_passes_visual_toc_bundle_into_snapshot_builder(self):
        captured: dict[str, object] = {}
        sentinel = object()

        class _FakeRepo:
            def get_latest_fnm_run(self, _doc_id):
                return {"status": "done"}

            def list_fnm_review_overrides(self, _doc_id):
                return []

            def list_fnm_translation_units(self, _doc_id):
                return []

        def _fake_builder(*_args, **kwargs):
            captured.update(kwargs)
            return sentinel

        original_toc_loader = mainline._load_fnm_toc_items
        original_bundle_loader = mainline._load_fnm_visual_toc_bundle
        original_builder = mainline.build_module_pipeline_snapshot
        try:
            mainline._load_fnm_toc_items = lambda _doc_id, _repo: ([], 0)
            mainline._load_fnm_visual_toc_bundle = lambda _doc_id: {
                "endnotes_summary": {"present": True, "container_title": "Notes", "container_printed_page": 12},
            }
            mainline.build_module_pipeline_snapshot = _fake_builder
            snapshot, pipeline_state = mainline._load_module_snapshot_for_doc(
                "doc-endnotes",
                repo=_FakeRepo(),
                pages=[{"bookPage": 1, "markdown": ""}],
            )
        finally:
            mainline._load_fnm_toc_items = original_toc_loader
            mainline._load_fnm_visual_toc_bundle = original_bundle_loader
            mainline.build_module_pipeline_snapshot = original_builder

        self.assertIs(snapshot, sentinel)
        self.assertEqual(pipeline_state, "done")
        self.assertEqual(
            dict(captured.get("visual_toc_bundle") or {}).get("endnotes_summary", {}).get("container_title"),
            "Notes",
        )


if __name__ == "__main__":
    unittest.main()

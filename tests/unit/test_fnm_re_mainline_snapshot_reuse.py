from __future__ import annotations

import unittest

from FNM_RE.app import mainline
from FNM_RE.models import (
    ExportBundleRecord,
    NoteLinkRecord,
    Phase6Structure,
    Phase6Summary,
    StructureStatusRecord,
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

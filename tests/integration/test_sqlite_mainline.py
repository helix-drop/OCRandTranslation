#!/usr/bin/env python3
"""SQLite 主链路切换准备测试。"""

import os
import shutil
import tempfile
import unittest
import json
import zipfile
from io import BytesIO
from unittest.mock import patch

import config
import app as app_module
import persistence.storage as storage
import translation.service as tasks
import translation.translate_launch as translate_launch
import translation.translate_runtime as translate_runtime
from pypdf import PdfWriter
from config import create_doc, ensure_dirs, get_current_doc_id, get_doc_meta, list_docs, set_current_doc
from scripts.rebuild_doc_derivatives import find_uppercase_continuation_candidates
from persistence.sqlite_store import SQLiteRepository
from document.text_processing import get_page_context_for_translate, parse_page_markdown
from persistence.storage import (
    _build_endnote_run_sections,
    compute_boilerplate_skip_bps,
    build_toc_title_map,
    detect_book_index_pages,
    detect_endnote_collection_pages,
    gen_markdown,
    load_entries_from_disk,
    load_pages_from_disk,
    save_pdf_toc_to_disk,
    save_toc_source_offset,
    save_entries_to_disk,
    save_entry_to_disk,
    save_pages_to_disk,
)
from persistence.storage_toc import save_toc_visual_manual_pdf
from testsupport import ClientCSRFMixin
from web.reading_view import _build_toc_reading_items


class SQLiteMainlineTest(ClientCSRFMixin, unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="sqlite-mainline-")
        self._patch_config_dirs(self.temp_root)
        ensure_dirs()
        self.client = app_module.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_config_dirs(self, root: str):
        config.CONFIG_DIR = root
        config.CONFIG_FILE = os.path.join(root, "config.json")
        config.DATA_DIR = os.path.join(root, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")

    def _replace_demo_fnm_structure(
        self,
        repo: SQLiteRepository,
        doc_id: str,
        *,
        chapter_id: str = "sec-01-demo",
        chapter_title: str = "Demo",
        chapter_pages: list[int] | None = None,
        note_items: list[dict] | None = None,
        note_regions: list[dict] | None = None,
    ) -> None:
        chapter_pages = list(chapter_pages or [1])
        note_items = list(note_items or [])
        note_regions = list(note_regions or [])
        region_kind_set = {
            str(item.get("note_kind") or "").strip()
            for item in note_items
        }
        if not note_regions and "endnote" in region_kind_set:
            endnote_pages = [
                int(item.get("page_no") or 0)
                for item in note_items
                if str(item.get("note_kind") or "").strip() == "endnote"
                and int(item.get("page_no") or 0) > 0
            ]
            if endnote_pages:
                first_marker = next(
                    (
                        str(item.get("source_marker") or item.get("display_marker") or item.get("marker") or "").strip()
                        for item in note_items
                        if str(item.get("note_kind") or "").strip() == "endnote"
                    ),
                    "",
                )
                note_regions.append(
                    {
                        "region_id": f"{chapter_id}-endnotes",
                        "region_kind": "chapter_endnotes",
                        "start_page": min(endnote_pages),
                        "end_page": max(endnote_pages),
                        "pages": sorted(set(endnote_pages)),
                        "title_hint": chapter_title,
                        "bound_chapter_id": chapter_id,
                        "region_start_first_source_marker": first_marker,
                        "region_first_note_item_marker": first_marker,
                        "region_marker_alignment_ok": True,
                    }
                )
        page_roles = []
        note_region_pages = {
            int(page_no)
            for region in note_regions
            for page_no in (region.get("pages") or [])
            if int(page_no or 0) > 0
        }
        for page_no in chapter_pages:
            page_roles.append(
                {
                    "page_no": int(page_no),
                    "target_pdf_page": int(page_no),
                    "page_role": "note" if int(page_no) in note_region_pages else "body",
                    "role_confidence": 1.0,
                    "role_reason": "test",
                    "section_hint": chapter_title,
                    "has_note_heading": bool(int(page_no) in note_region_pages),
                    "note_scan_summary": {"page_kind": "chapter_endnotes"} if int(page_no) in note_region_pages else {},
                }
            )
        note_mode = "none"
        if region_kind_set == {"footnote"}:
            note_mode = "footnote_primary"
        elif region_kind_set:
            note_mode = "mixed_or_unclear"
        repo.replace_fnm_structure(
            doc_id,
            pages=page_roles,
            chapters=[
                {
                    "chapter_id": chapter_id,
                    "title": chapter_title,
                    "start_page": min(chapter_pages),
                    "end_page": max(chapter_pages),
                    "pages": chapter_pages,
                    "source": "test",
                    "boundary_state": "ready",
                }
            ],
            heading_candidates=[],
            note_regions=note_regions,
            chapter_note_modes=[
                {
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "note_mode": note_mode,
                    "sampled_pages": chapter_pages,
                    "detection_confidence": 1.0,
                }
            ],
            section_heads=[],
            note_items=note_items,
            body_anchors=[],
            note_links=[],
            structure_reviews=[],
        )
        self._attach_manual_toc(doc_id)

    def _attach_manual_toc(self, doc_id: str) -> None:
        toc_path = os.path.join(self.temp_root, f"{doc_id}-toc.pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with open(toc_path, "wb") as f:
            writer.write(f)
        save_toc_visual_manual_pdf(doc_id, toc_path, original_name="目录.pdf")

    def test_documents_and_pages_write_to_sqlite_mainline(self):
        doc_id = create_doc("mainline.pdf")
        save_pages_to_disk([
            {
                "bookPage": 7,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 7",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 8,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 8",
                "footnotes": "fn-8",
                "textSource": "pdf",
            },
        ], "mainline.pdf", doc_id)

        pages, src_name = load_pages_from_disk(doc_id)
        meta = get_doc_meta(doc_id)
        docs = list_docs()

        self.assertEqual(get_current_doc_id(), doc_id)
        self.assertEqual(src_name, "mainline.pdf")
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[1]["textSource"], "pdf")
        self.assertEqual(meta["name"], "mainline.pdf")
        self.assertEqual(meta["page_count"], 2)
        self.assertEqual(docs[0]["id"], doc_id)

    def test_translate_state_mainline_reads_active_run_from_sqlite(self):
        doc_id = create_doc("state.pdf")
        draft = {
            "active": True,
            "bp": 7,
            "para_idx": 1,
            "para_total": 3,
            "para_done": 1,
            "parallel_limit": 2,
            "active_para_indices": [1],
            "paragraph_states": ["done", "streaming", "pending"],
            "paragraph_errors": ["", "", ""],
            "paragraphs": ["第一段", "", ""],
            "status": "streaming",
            "note": "正在翻译",
            "last_error": "",
            "updated_at": 0,
        }
        tasks._save_translate_state(
            doc_id,
            running=True,
            stop_requested=False,
            phase="running",
            start_bp=7,
            current_bp=7,
            resume_bp=7,
            total_pages=10,
            done_pages=2,
            processed_pages=3,
            pending_pages=7,
            current_page_idx=3,
            translated_chars=123,
            translated_paras=5,
            request_count=2,
            prompt_tokens=11,
            completion_tokens=7,
            model="qwen-plus",
            failed_bps=[9],
            partial_failed_bps=[8],
            failed_pages=[{"bp": 9, "error": "boom"}],
            draft=draft,
        )

        repo = SQLiteRepository()
        active = repo.get_active_translate_run(doc_id)
        snapshot = tasks._load_translate_state(doc_id)

        self.assertIsNotNone(active)
        self.assertEqual(active["phase"], "running")
        self.assertTrue(active["running"])
        self.assertEqual(active["current_bp"], 7)
        self.assertEqual(snapshot["phase"], "running")
        self.assertEqual(snapshot["prompt_tokens"], 11)
        self.assertEqual(snapshot["completion_tokens"], 7)
        self.assertEqual(snapshot["failed_bps"], [9])
        self.assertEqual(snapshot["partial_failed_bps"], [8])
        self.assertEqual(snapshot["draft"]["status"], "streaming")
        self.assertFalse(os.path.exists(os.path.join(config.DOCS_DIR, doc_id, "translate_state.json")))

        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            start_bp=7,
            current_bp=8,
            resume_bp=8,
            total_pages=10,
            done_pages=3,
            processed_pages=4,
            pending_pages=6,
            current_page_idx=4,
            translated_chars=222,
            translated_paras=8,
            request_count=3,
            prompt_tokens=20,
            completion_tokens=12,
            model="qwen-plus",
            failed_bps=[],
            partial_failed_bps=[],
            failed_pages=[],
            draft={"active": False, "paragraphs": [], "paragraph_states": [], "paragraph_errors": []},
        )

        self.assertIsNone(repo.get_active_translate_run(doc_id))
        effective = repo.get_effective_translate_run(doc_id)
        self.assertEqual(effective["phase"], "stopped")
        self.assertFalse(effective["running"])
        self.assertEqual(effective["resume_bp"], 8)
        self.assertEqual(repo.list_translate_failures(doc_id), [])

    def test_effective_translation_page_returns_current_page_result(self):
        doc_id = create_doc("entry.pdf")
        repo = SQLiteRepository()
        translation_page_id = repo.save_translation_page(
            doc_id,
            16,
            {
                "_model": "qwen-plus",
                "_status": "done",
                "pages": "16",
                "_usage": {"total_tokens": 10},
                "_page_entries": [
                    {
                        "original": "Paragraph A",
                        "translation": "段落 A",
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                    }
                ],
            },
        )

        self.assertGreater(translation_page_id, 0)
        page = repo.get_effective_translation_page(doc_id, 16)
        self.assertIsNotNone(page)
        self.assertEqual(page["_model"], "qwen-plus")
        self.assertEqual(page["_usage"]["total_tokens"], 10)
        self.assertEqual(page["_page_entries"][0]["translation"], "段落 A")

    def test_reading_route_reads_current_effective_entry_from_sqlite(self):
        doc_id = create_doc("reading.pdf")
        save_pages_to_disk([
            {
                "bookPage": 16,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Original paragraph",
                "footnotes": "",
                "textSource": "ocr",
            }
        ], "reading.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 16,
            "_model": "qwen-plus",
            "_page_entries": [{
                "original": "Original paragraph",
                "translation": "当前页译文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "16",
            }],
            "pages": "16",
        }], "Reading Doc", 0, doc_id)

        entries, title, idx = load_entries_from_disk(doc_id)
        self.assertEqual(title, "Reading Doc")
        self.assertEqual(idx, 0)
        self.assertEqual(entries[0]["_page_entries"][0]["translation"], "当前页译文")

        resp = self.client.get(f"/reading?bp=16&doc_id={doc_id}&orig=0&pdf=0&usage=0&layout=stack")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("当前页译文", html)
        self.assertIn("已译1页", html)
        self.assertIn('"reading_stats_done_pages": 1', html)

    def test_delete_docs_batch_removes_selected(self):
        from config import list_docs

        doc_a = create_doc("batch-a.pdf")
        doc_b = create_doc("batch-b.pdf")
        minimal = {
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 100,
            "imgH": 100,
            "markdown": "x",
            "footnotes": "",
            "textSource": "ocr",
        }
        save_pages_to_disk([dict(minimal)], "batch-a.pdf", doc_a)
        save_pages_to_disk([dict(minimal)], "batch-b.pdf", doc_b)
        ids = {d["id"] for d in list_docs()}
        self.assertIn(doc_a, ids)
        self.assertIn(doc_b, ids)

        resp = self._post("/delete_docs_batch", data={"doc_ids": [doc_a]})
        self.assertEqual(resp.status_code, 302)
        ids_after = {d["id"] for d in list_docs()}
        self.assertNotIn(doc_a, ids_after)
        self.assertIn(doc_b, ids_after)

        resp2 = self._post("/delete_docs_batch", data={"doc_ids": [doc_b]})
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(len(list_docs()), 0)

    def test_fnm_translate_returns_unavailable_when_pipeline_not_done(self):
        doc_id = create_doc("fnm-gate.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "x",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "fnm-gate.pdf", doc_id)
        resp = self._post(f"/api/doc/{doc_id}/fnm/translate", data={"doc_title": "T"})
        payload = resp.get_json()
        self.assertEqual(payload.get("error"), "fnm_unavailable")

    def test_export_md_reads_current_effective_entries_from_sqlite(self):
        doc_id = create_doc("export.pdf")
        save_entries_to_disk([{
            "_pageBP": 8,
            "_model": "qwen-plus",
            "_page_entries": [{
                "original": "Original paragraph",
                "translation": "导出译文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "8",
            }],
            "pages": "8",
        }], "Export Doc", 0, doc_id)

        resp = self.client.get(f"/export_md?doc_id={doc_id}")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertIn("导出译文", payload["markdown"])

    def test_export_pages_json_reads_current_pages_from_sqlite(self):
        doc_id = create_doc("export-pages.json.pdf")
        save_pages_to_disk([
            {
                "bookPage": 7,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 7",
                "footnotes": "fn-7",
                "textSource": "pdf",
                "blocks": [{"text": "Page 7"}],
            },
            {
                "bookPage": 8,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 8",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "export-pages.json.pdf", doc_id)

        resp = self.client.get(f"/export_pages_json?doc_id={doc_id}")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(payload["doc_id"], doc_id)
        self.assertEqual(payload["name"], "export-pages.json.pdf")
        self.assertEqual(payload["page_count"], 2)
        self.assertEqual(payload["pages"][0]["bookPage"], 7)
        self.assertEqual(payload["pages"][0]["textSource"], "pdf")
        self.assertEqual(payload["pages"][0]["blocks"][0]["text"], "Page 7")

    def test_export_source_markdown_reads_page_markdown_from_sqlite(self):
        doc_id = create_doc("export-source.pdf")
        save_pages_to_disk([
            {
                "bookPage": 3,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Alpha",
                "footnotes": "",
                "textSource": "pdf",
                "printPageLabel": "ix",
            },
            {
                "bookPage": 4,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Beta",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "export-source.pdf", doc_id)

        resp = self.client.get(f"/export_source_markdown?doc_id={doc_id}")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(payload["doc_id"], doc_id)
        self.assertEqual(payload["name"], "export-source.pdf")
        self.assertEqual(payload["page_count"], 2)
        self.assertIn("# export-source.pdf", payload["markdown"])
        self.assertIn("## PDF第3页 / 原书 p.ix", payload["markdown"])
        self.assertIn("Alpha", payload["markdown"])
        self.assertIn("## PDF第4页", payload["markdown"])
        self.assertIn("Beta", payload["markdown"])

    def test_reading_route_and_export_md_support_fnm_view(self):
        doc_id = create_doc("fnm-reading.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文一",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 2,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文二",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "fnm-reading.pdf", doc_id)
        repo = SQLiteRepository()
        run_id = repo.create_fnm_run(
            doc_id,
            status="done",
            page_count=2,
            section_count=1,
            note_count=2,
            unit_count=3,
        )
        self._replace_demo_fnm_structure(
            repo,
            doc_id,
            chapter_pages=[1, 2],
            note_items=[
                {
                    "note_item_id": "fn-01-0001",
                    "note_kind": "footnote",
                    "chapter_id": "sec-01-demo",
                    "region_id": "",
                    "marker": "1",
                    "normalized_marker": "1",
                    "occurrence": 1,
                    "source_text": "脚注原文",
                    "page_no": 1,
                    "display_marker": "1",
                    "source_marker": "1",
                    "title_hint": "",
                },
                {
                    "note_item_id": "en-01-0001",
                    "note_kind": "endnote",
                    "chapter_id": "sec-01-demo",
                    "region_id": "sec-01-demo-endnotes",
                    "marker": "1",
                    "normalized_marker": "1",
                    "occurrence": 1,
                    "source_text": "尾注原文",
                    "page_no": 2,
                    "display_marker": "1",
                    "source_marker": "1",
                    "title_hint": "",
                },
            ],
        )
        repo.replace_fnm_data(
            doc_id,
            preserve_structure=True,
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
                    "char_count": 8,
                    "source_text": "正文一\n\n正文二",
                    "translated_text": "正文译文一[^fn-01-0001]\n\n正文译文二[EN-en-01-0001]",
                    "status": "done",
                    "error_msg": "",
                    "target_ref": "",
                    "page_segments": [
                        {
                            "page_no": 1,
                            "source_text": "正文一 {{FN_REF:fn-01-0001}}",
                            "display_text": "正文一 [^fn-01-0001]",
                            "translated_text": "正文译文一[^fn-01-0001]",
                            "paragraphs": [
                                {
                                    "order": 1,
                                    "kind": "body",
                                    "heading_level": 0,
                                    "source_text": "正文一 {{FN_REF:fn-01-0001}}",
                                    "display_text": "正文一 [^fn-01-0001]",
                                    "cross_page": None,
                                    "consumed_by_prev": False,
                                    "section_path": ["Demo"],
                                    "print_page_label": "1",
                                    "translated_text": "正文译文一[^fn-01-0001]",
                                }
                            ],
                        },
                        {
                            "page_no": 2,
                            "source_text": "正文二 {{EN_REF:en-01-0001}}",
                            "display_text": "正文二 [EN-en-01-0001]",
                            "translated_text": "正文译文二[EN-en-01-0001]",
                            "paragraphs": [
                                {
                                    "order": 1,
                                    "kind": "body",
                                    "heading_level": 0,
                                    "source_text": "正文二 {{EN_REF:en-01-0001}}",
                                    "display_text": "正文二 [EN-en-01-0001]",
                                    "cross_page": None,
                                    "consumed_by_prev": False,
                                    "section_path": ["Demo"],
                                    "print_page_label": "2",
                                    "translated_text": "正文译文二[EN-en-01-0001]",
                                }
                            ],
                        },
                    ],
                },
                {
                    "unit_id": "footnote-fn-01-0001",
                    "kind": "footnote",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 2,
                    "note_id": "fn-01-0001",
                    "page_start": 1,
                    "page_end": 1,
                    "char_count": 4,
                    "source_text": "脚注原文",
                    "translated_text": "脚注译文",
                    "status": "done",
                    "error_msg": "",
                    "target_ref": "{{FN_REF:fn-01-0001}}",
                    "page_segments": [],
                },
                {
                    "unit_id": "endnote-en-01-0001",
                    "kind": "endnote",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 2,
                    "note_id": "en-01-0001",
                    "page_start": 2,
                    "page_end": 2,
                    "char_count": 4,
                    "source_text": "尾注原文",
                    "translated_text": "尾注译文",
                    "status": "done",
                    "error_msg": "",
                    "target_ref": "{{EN_REF:en-01-0001}}",
                    "page_segments": [],
                },
            ],
        )
        repo.update_fnm_run(doc_id, run_id, status="done", error_msg="")

        reading_resp = self.client.get(f"/reading?bp=1&doc_id={doc_id}&view=fnm&orig=0&pdf=0&usage=0")
        export_resp = self.client.get(f"/export_md?doc_id={doc_id}&format=fnm_obsidian")
        status_resp = self.client.get(f"/api/reading_view_state?doc_id={doc_id}&view=fnm")

        reading_html = reading_resp.get_data(as_text=True)
        export_payload = export_resp.get_json()
        status_payload = status_resp.get_json()

        self.assertEqual(reading_resp.status_code, 200)
        self.assertIn("正文译文一", reading_html)
        self.assertIn("脚注译文", reading_html)
        self.assertIn("页面注释", reading_html)
        self.assertIn("本页脚注", reading_html)
        self.assertIn("当前节尾注", reading_html)
        self.assertNotIn("FNM 注释", reading_html)
        self.assertEqual(reading_html.count('id="pageNotesPanel"'), 1)
        self.assertIn("/static/reading/core.js", reading_html)
        self.assertIn("/static/reading/navigation.js", reading_html)
        self.assertIn("/static/reading/page_editor.js", reading_html)
        self.assertIn("/static/reading/task_session.js", reading_html)
        self.assertIn("/static/reading/index.js", reading_html)
        self.assertEqual(export_resp.status_code, 200)
        self.assertIn("正文译文一[^1]", export_payload["markdown"])
        self.assertIn("正文译文二[^2]", export_payload["markdown"])
        self.assertIn("[^1]: 脚注译文", export_payload["markdown"])
        self.assertIn("[^2]: 尾注译文", export_payload["markdown"])
        self.assertNotIn("[EN-en-01-0001]", export_payload["markdown"])
        self.assertNotIn("[FN-1]", export_payload["markdown"])
        self.assertEqual(status_payload["translated_bps"], [1, 2])
        self.assertEqual(load_entries_from_disk(doc_id)[0], [])

        switch_fnm = self._post(
            "/switch_reading_mode",
            data={
                "doc_id": doc_id,
                "bp": 1,
                "usage": "0",
                "orig": "0",
                "pdf": "0",
                "layout": "stack",
                "target_mode": "fnm",
            },
        )
        self.assertEqual(switch_fnm.status_code, 302)
        self.assertIn("view=fnm", switch_fnm.headers.get("Location", ""))
        switch_std = self._post(
            "/switch_reading_mode",
            data={
                "doc_id": doc_id,
                "bp": 1,
                "usage": "0",
                "orig": "0",
                "pdf": "0",
                "layout": "stack",
                "target_mode": "standard",
            },
        )
        self.assertEqual(switch_std.status_code, 302)
        self.assertNotIn("view=fnm", switch_std.headers.get("Location", ""))

    def test_fnm_api_routes_report_status_notes_and_translate_entry(self):
        doc_id = create_doc("fnm-api.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文一",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 2,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文二",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "fnm-api.pdf", doc_id)
        repo = SQLiteRepository()
        run_id = repo.create_fnm_run(
            doc_id,
            status="done",
            page_count=2,
            section_count=1,
            note_count=2,
            unit_count=3,
        )
        self._replace_demo_fnm_structure(
            repo,
            doc_id,
            chapter_pages=[1, 2],
            note_items=[
                {
                    "note_item_id": "fn-01-0001",
                    "note_kind": "footnote",
                    "chapter_id": "sec-01-demo",
                    "region_id": "",
                    "marker": "1",
                    "normalized_marker": "1",
                    "occurrence": 1,
                    "source_text": "脚注原文",
                    "page_no": 1,
                    "display_marker": "1",
                    "source_marker": "1",
                    "title_hint": "",
                },
                {
                    "note_item_id": "en-01-0001",
                    "note_kind": "endnote",
                    "chapter_id": "sec-01-demo",
                    "region_id": "sec-01-demo-endnotes",
                    "marker": "1",
                    "normalized_marker": "1",
                    "occurrence": 1,
                    "source_text": "尾注原文",
                    "page_no": 2,
                    "display_marker": "1",
                    "source_marker": "1",
                    "title_hint": "",
                },
            ],
        )
        repo.replace_fnm_data(
            doc_id,
            preserve_structure=True,
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
                    "char_count": 8,
                    "source_text": "正文一 {{FN_REF:fn-01-0001}}\n\n正文二 {{EN_REF:en-01-0001}}",
                    "translated_text": None,
                    "status": "pending",
                    "error_msg": "",
                    "target_ref": "",
                    "page_segments": [
                        {"page_no": 1, "source_text": "正文一 {{FN_REF:fn-01-0001}}", "paragraph_count": 1},
                        {"page_no": 2, "source_text": "正文二 {{EN_REF:en-01-0001}}", "paragraph_count": 1},
                    ],
                },
                {
                    "unit_id": "footnote-fn-01-0001",
                    "kind": "footnote",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 2,
                    "note_id": "fn-01-0001",
                    "page_start": 1,
                    "page_end": 1,
                    "char_count": 4,
                    "source_text": "脚注原文",
                    "translated_text": None,
                    "status": "pending",
                    "error_msg": "",
                    "target_ref": "{{FN_REF:fn-01-0001}}",
                    "page_segments": [],
                },
                {
                    "unit_id": "endnote-en-01-0001",
                    "kind": "endnote",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 2,
                    "note_id": "en-01-0001",
                    "page_start": 2,
                    "page_end": 2,
                    "char_count": 4,
                    "source_text": "尾注原文",
                    "translated_text": None,
                    "status": "pending",
                    "error_msg": "",
                    "target_ref": "{{EN_REF:en-01-0001}}",
                    "page_segments": [],
                },
            ],
        )
        repo.update_fnm_run(doc_id, run_id, status="done", error_msg="")

        status_resp = self.client.get(f"/api/doc/{doc_id}/fnm/status")
        with (
            patch.object(storage, "get_translate_args", return_value={"api_key": "fake-key"}),
            patch.object(translate_launch, "start_fnm_translate_task", return_value=True) as start_mock,
        ):
            translate_resp = self._post(
                f"/api/doc/{doc_id}/fnm/translate",
                data={"doc_title": "FNM API", "start_unit_idx": "2"},
            )

        status_payload = status_resp.get_json()
        translate_payload = translate_resp.get_json()

        self.assertEqual(status_resp.status_code, 200)
        self.assertEqual(status_payload["run_status"], "done")
        self.assertFalse(status_payload["can_translate"])
        self.assertFalse(status_payload["view_available"])
        self.assertFalse(status_payload["has_diagnostic_entries"])
        self.assertEqual(status_payload["total_units"], 3)
        self.assertEqual(status_payload["done_units"], 0)
        self.assertEqual(status_payload["processed_units"], 0)
        self.assertEqual(status_payload["pending_units"], 3)
        self.assertIsNone(status_payload["current_unit_idx"])
        self.assertEqual(translate_resp.status_code, 409)
        self.assertEqual(translate_payload["error"], "fnm_structure_not_ready")
        self.assertEqual(translate_payload["structure_state"], "review_required")
        self.assertIn("toc_no_exportable_chapter", translate_payload["blocking_reasons"])
        self.assertFalse(start_mock.called)

    def test_translate_status_is_task_only_and_reading_view_state_is_separate(self):
        doc_id = create_doc("reading-view-state.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "标准正文一",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 2,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "标准正文二",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "reading-view-state.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "标准正文一",
                "translation": "标准译文一",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
            }],
            "pages": "1",
        }], "Reading View State", 0, doc_id)

        repo = SQLiteRepository()
        run_id = repo.create_fnm_run(
            doc_id,
            status="done",
            page_count=2,
            section_count=1,
            note_count=0,
            unit_count=1,
        )
        self._replace_demo_fnm_structure(
            repo,
            doc_id,
            chapter_pages=[1, 2],
            note_items=[],
        )
        repo.replace_fnm_data(
            doc_id,
            preserve_structure=True,
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
                    "char_count": 8,
                    "source_text": "FNM 正文一\n\nFNM 正文二",
                    "translated_text": None,
                    "status": "pending",
                    "error_msg": "",
                    "target_ref": "",
                    "page_segments": [
                        {"page_no": 1, "source_text": "FNM 正文一", "translated_text": "FNM 译文一", "paragraph_count": 1},
                        {"page_no": 2, "source_text": "FNM 正文二", "translated_text": "FNM 译文二", "paragraph_count": 1},
                    ],
                },
            ],
        )
        repo.update_fnm_run(doc_id, run_id, status="done", error_msg="")

        standard_status = self.client.get(f"/translate_status?doc_id={doc_id}&view=standard").get_json()
        fnm_status = self.client.get(f"/translate_status?doc_id={doc_id}&view=fnm").get_json()
        standard_view = self.client.get(f"/api/reading_view_state?doc_id={doc_id}&view=standard").get_json()
        fnm_view = self.client.get(f"/api/reading_view_state?doc_id={doc_id}&view=fnm").get_json()

        self.assertEqual(standard_status, fnm_status)
        self.assertEqual(standard_view["mode"], "standard")
        self.assertEqual(standard_view["translated_bps"], [1])
        self.assertEqual(fnm_view["mode"], "fnm")
        self.assertEqual(fnm_view["translated_bps"], [])
        self.assertEqual(fnm_view["source_only_bps"], [1, 2])

    def test_standard_reading_page_hides_fnm_view_switch_and_fnm_translate_button(self):
        doc_id = create_doc("reading-no-fnm-switch.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "标准正文一",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "reading-no-fnm-switch.pdf", doc_id)

        resp = self.client.get(f"/reading?bp=1&doc_id={doc_id}&orig=0&pdf=0&usage=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("FNM 视图", html)
        self.assertNotIn("启动 FNM 翻译", html)

    def test_switch_reading_mode_is_get_redirect_and_does_not_stop_task(self):
        doc_id = create_doc("switch-reading-mode.pdf")
        save_pages_to_disk([{
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 1",
            "footnotes": "",
            "textSource": "ocr",
        }], "switch-reading-mode.pdf", doc_id)
        repo = SQLiteRepository()
        run_id = repo.create_fnm_run(
            doc_id,
            status="done",
            page_count=1,
            section_count=1,
            note_count=0,
            unit_count=1,
        )
        repo.update_fnm_run(doc_id, run_id, status="done", error_msg="")
        resp = self.client.get(
            "/switch_reading_mode",
            query_string={
                "doc_id": doc_id,
                "bp": 1,
                "usage": "0",
                "orig": "0",
                "pdf": "0",
                "layout": "stack",
                "target_mode": "fnm",
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.assertIn("view=fnm", resp.headers.get("Location", ""))

    def test_fnm_reading_view_falls_back_to_unit_source_before_projection_exists(self):
        doc_id = create_doc("fnm-reading-fallback.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文一",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 2,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文二",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "fnm-reading-fallback.pdf", doc_id)
        repo = SQLiteRepository()
        run_id = repo.create_fnm_run(
            doc_id,
            status="done",
            page_count=2,
            section_count=1,
            note_count=1,
            unit_count=2,
        )
        self._replace_demo_fnm_structure(
            repo,
            doc_id,
            chapter_pages=[1, 2],
            note_items=[
                {
                    "note_item_id": "fn-01-0001",
                    "note_kind": "footnote",
                    "chapter_id": "sec-01-demo",
                    "region_id": "",
                    "marker": "1",
                    "normalized_marker": "1",
                    "occurrence": 1,
                    "source_text": "脚注原文",
                    "page_no": 1,
                    "display_marker": "1",
                    "source_marker": "1",
                    "title_hint": "",
                }
            ],
        )
        repo.replace_fnm_data(
            doc_id,
            preserve_structure=True,
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
                    "source_text": "正文原文一 {{FN_REF:fn-01-0001}}\n\n正文原文二",
                    "translated_text": None,
                    "status": "pending",
                    "error_msg": "",
                    "target_ref": "",
                    "page_segments": [
                        {"page_no": 1, "source_text": "正文原文一 {{FN_REF:fn-01-0001}}", "display_text": "正文原文一 [^fn-01-0001]", "paragraph_count": 1},
                        {"page_no": 2, "source_text": "正文原文二", "display_text": "正文原文二", "paragraph_count": 1},
                    ],
                },
                {
                    "unit_id": "footnote-fn-01-0001",
                    "kind": "footnote",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 2,
                    "note_id": "fn-01-0001",
                    "page_start": 1,
                    "page_end": 1,
                    "char_count": 4,
                    "source_text": "脚注原文",
                    "translated_text": None,
                    "status": "pending",
                    "error_msg": "",
                    "target_ref": "{{FN_REF:fn-01-0001}}",
                    "page_segments": [],
                },
            ],
        )
        repo.update_fnm_run(doc_id, run_id, status="done", error_msg="")

        resp = self.client.get(f"/reading?bp=1&doc_id={doc_id}&view=fnm&orig=0&pdf=0&usage=0")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("正文原文一", html)
        self.assertIn("脚注原文", html)

    def test_fnm_export_uses_pending_placeholder_when_units_untranslated(self):
        doc_id = create_doc("fnm-export-fallback.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "正文原文一",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "fnm-export-fallback.pdf", doc_id)
        repo = SQLiteRepository()
        run_id = repo.create_fnm_run(
            doc_id,
            status="done",
            page_count=1,
            section_count=1,
            note_count=2,
            unit_count=3,
        )
        self._replace_demo_fnm_structure(
            repo,
            doc_id,
            chapter_pages=[1],
            note_items=[
                {
                    "note_item_id": "fn-01-0001",
                    "note_kind": "footnote",
                    "chapter_id": "sec-01-demo",
                    "region_id": "",
                    "marker": "1",
                    "normalized_marker": "1",
                    "occurrence": 1,
                    "source_text": "脚注原文",
                    "page_no": 1,
                    "display_marker": "1",
                    "source_marker": "1",
                    "title_hint": "",
                },
                {
                    "note_item_id": "en-01-0001",
                    "note_kind": "endnote",
                    "chapter_id": "sec-01-demo",
                    "region_id": "sec-01-demo-endnotes",
                    "marker": "1",
                    "normalized_marker": "1",
                    "occurrence": 1,
                    "source_text": "尾注原文",
                    "page_no": 1,
                    "display_marker": "1",
                    "source_marker": "1",
                    "title_hint": "",
                },
            ],
        )
        repo.replace_fnm_data(
            doc_id,
            preserve_structure=True,
            notes=[],
            units=[
                {
                    "unit_id": "body-sec-01-demo-0001",
                    "kind": "body",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 1,
                    "note_id": None,
                    "page_start": 1,
                    "page_end": 1,
                    "char_count": 12,
                    "source_text": "正文原文 {{FN_REF:fn-01-0001}} {{EN_REF:en-01-0001}}",
                    "translated_text": None,
                    "status": "pending",
                    "error_msg": "",
                    "target_ref": "",
                    "page_segments": [
                        {"page_no": 1, "source_text": "正文原文 {{FN_REF:fn-01-0001}} {{EN_REF:en-01-0001}}", "paragraph_count": 1},
                    ],
                },
            ],
        )
        repo.update_fnm_run(doc_id, run_id, status="done", error_msg="")

        resp = self.client.get(f"/export_md?doc_id={doc_id}&format=fnm_obsidian")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertIn("[待翻译]", payload["markdown"])
        self.assertNotIn("[EN-en-01-0001]", payload["markdown"])
        self.assertNotIn("[^1]: 脚注原文", payload["markdown"])
        self.assertNotIn("[^2]: 尾注原文", payload["markdown"])
        self.assertNotIn("[FN-1]", payload["markdown"])

    def test_fnm_obsidian_export_omits_unreferenced_footnotes(self):
        doc_id = create_doc("fnm-footnote-fallback.pdf")
        save_pages_to_disk([{
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "正文原文",
            "footnotes": "",
            "textSource": "ocr",
        }], "fnm-footnote-fallback.pdf", doc_id)
        repo = SQLiteRepository()
        run_id = repo.create_fnm_run(
            doc_id,
            status="done",
            page_count=1,
            section_count=1,
            note_count=1,
            unit_count=1,
        )
        self._replace_demo_fnm_structure(
            repo,
            doc_id,
            chapter_pages=[1],
            note_items=[
                {
                    "note_item_id": "fn-01-0001",
                    "note_kind": "footnote",
                    "chapter_id": "sec-01-demo",
                    "region_id": "",
                    "marker": "1",
                    "normalized_marker": "1",
                    "occurrence": 1,
                    "source_text": "脚注原文",
                    "page_no": 1,
                    "display_marker": "1",
                    "source_marker": "1",
                    "title_hint": "",
                }
            ],
        )
        repo.replace_fnm_data(
            doc_id,
            preserve_structure=True,
            notes=[],
            units=[
                {
                    "unit_id": "body-sec-01-demo-0001",
                    "kind": "body",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 1,
                    "note_id": None,
                    "page_start": 1,
                    "page_end": 1,
                    "char_count": 4,
                    "source_text": "正文原文",
                    "translated_text": "正文译文",
                    "status": "done",
                    "error_msg": "",
                    "target_ref": "",
                    "page_segments": [],
                },
            ],
        )
        repo.update_fnm_run(doc_id, run_id, status="done", error_msg="")

        markdown = self.client.get(f"/export_md?doc_id={doc_id}&format=fnm_obsidian").get_json()["markdown"]
        self.assertIn("正文译文", markdown)
        self.assertNotIn("[^1]: 脚注译文", markdown)
        self.assertNotIn("[FN-1]", markdown)

    def test_download_md_matches_export_preview_markdown(self):
        doc_id = create_doc("download-export.pdf")
        save_entries_to_disk([{
            "_pageBP": 8,
            "_model": "qwen-plus",
            "_page_entries": [{
                "original": "Original paragraph",
                "translation": "下载导出一致性",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "8",
            }],
            "pages": "8",
        }], "Download Export", 0, doc_id)

        export_payload = self.client.get(f"/export_md?doc_id={doc_id}").get_json()
        download_resp = self.client.get(f"/download_md?doc_id={doc_id}")

        self.assertEqual(download_resp.status_code, 200)
        self.assertIn("text/markdown", download_resp.headers.get("Content-Type", ""))
        self.assertIn(".md", download_resp.headers.get("Content-Disposition", ""))
        self.assertEqual(download_resp.get_data(as_text=True), export_payload["markdown"])

    def test_download_md_returns_zip_bundle_for_fnm_obsidian_format(self):
        doc_id = create_doc("fnm-zip-export.pdf")
        save_pages_to_disk([{
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "正文原文",
            "footnotes": "",
            "textSource": "ocr",
        }], "fnm-zip-export.pdf", doc_id)
        repo = SQLiteRepository()
        run_id = repo.create_fnm_run(
            doc_id,
            status="done",
            page_count=1,
            section_count=1,
            note_count=0,
            unit_count=1,
        )
        self._replace_demo_fnm_structure(
            repo,
            doc_id,
            chapter_pages=[1],
            note_items=[],
        )
        repo.replace_fnm_data(
            doc_id,
            preserve_structure=True,
            notes=[],
            units=[
                {
                    "unit_id": "body-sec-01-demo-0001",
                    "kind": "body",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 1,
                    "note_id": None,
                    "page_start": 1,
                    "page_end": 1,
                    "char_count": 4,
                    "source_text": "正文原文",
                    "translated_text": "正文译文",
                    "status": "done",
                    "error_msg": "",
                    "target_ref": "",
                    "page_segments": [],
                }
            ],
        )
        repo.update_fnm_run(doc_id, run_id, status="done", error_msg="")

        download_resp = self.client.get(f"/download_md?doc_id={doc_id}&format=fnm_obsidian")

        self.assertEqual(download_resp.status_code, 200)
        self.assertIn("application/zip", download_resp.headers.get("Content-Type", ""))
        self.assertIn(".fnm.obsidian.zip", download_resp.headers.get("Content-Disposition", ""))

        with zipfile.ZipFile(BytesIO(download_resp.get_data()), "r") as archive:
            names = archive.namelist()
            self.assertIn("index.md", names)
            chapter_paths = [name for name in names if name.startswith("chapters/")]
            self.assertEqual(len(chapter_paths), 1)
            chapter_md = archive.read(chapter_paths[0]).decode("utf-8")
            self.assertIn("正文译文", chapter_md)
            index_md = archive.read("index.md").decode("utf-8")
            self.assertIn(chapter_paths[0], index_md)

    def test_export_md_formats_headings_body_and_paragraph_footnotes_like_reading_notes(self):
        doc_id = create_doc("export-format.pdf")
        save_entries_to_disk([{
            "_pageBP": 2,
            "_model": "qwen-plus",
            "_page_entries": [
                {
                    "original": "2_LECON DU 17 JANVIER 1979",
                    "translation": "1979年1月17日课程",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 1,
                    "pages": "2",
                },
                {
                    "original": "Le liberalisme et un nouvel art de gouverner.",
                    "translation": "自由主义与一种新的治理技艺。",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "2",
                },
                {
                    "original": "Je voudrais affiner ces hypotheses.",
                    "translation": "我想进一步细化这些假设。",
                    "footnotes": "1. Note originale",
                    "footnotes_translation": "1. 脚注译文",
                    "heading_level": 0,
                    "pages": "2",
                },
            ],
            "pages": "2",
        }], "Export Format", 0, doc_id)

        resp = self.client.get(f"/export_md?doc_id={doc_id}")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            payload["markdown"],
            "# 1979年1月17日课程\n"
            "*2_LECON DU 17 JANVIER 1979*\n\n"
            "> Le liberalisme et un nouvel art de gouverner.\n\n"
            "自由主义与一种新的治理技艺。\n\n"
            "> Je voudrais affiner ces hypotheses.\n\n"
            "我想进一步细化这些假设。 [^1]\n\n"
            "[^1]: Note originale\n"
            "    译：脚注译文\n",
        )
        self.assertNotIn("**Page 2**", payload["markdown"])
        self.assertNotIn("---", payload["markdown"])

    def test_export_md_moves_unresolved_page_footnotes_below_last_body_paragraph(self):
        doc_id = create_doc("export-page-footnote.pdf")
        save_entries_to_disk([{
            "_pageBP": 3,
            "_model": "qwen-plus",
            "_page_entries": [
                {
                    "original": "PREMIERE PARTIE",
                    "translation": "第一部分",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 1,
                    "pages": "3",
                },
                {
                    "original": "Premier paragraphe.",
                    "translation": "第一段。",
                    "footnotes": "1. Note de page",
                    "footnotes_translation": "1. 页面脚注译文",
                    "heading_level": 0,
                    "pages": "3",
                },
                {
                    "original": "Dernier paragraphe.",
                    "translation": "最后一段。",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "3",
                },
            ],
            "pages": "3",
        }], "Export Page Footnote", 0, doc_id)

        resp = self.client.get(f"/export_md?doc_id={doc_id}")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            payload["markdown"],
            "# 第一部分\n"
            "*PREMIERE PARTIE*\n\n"
            "> Premier paragraphe.\n\n"
            "第一段。\n\n"
            "> Dernier paragraphe.\n\n"
            "最后一段。 [^1]\n\n"
            "[^1]: Note de page\n"
            "    译：页面脚注译文\n",
        )
        self.assertLess(payload["markdown"].index("第一段。"), payload["markdown"].index("最后一段。"))
        self.assertLess(payload["markdown"].index("最后一段。"), payload["markdown"].index("[^1]:"))

    def test_export_md_normalizes_latex_and_superscript_markers_and_keeps_fallback_blocks(self):
        doc_id = create_doc("export-footnote-markers.pdf")
        save_entries_to_disk([{
            "_pageBP": 9,
            "_model": "qwen-plus",
            "_page_entries": [
                {
                    "original": "Original text with $ ^{93} $ marker.",
                    "translation": "译文含上标²²与LaTeX标记 ^{94}。",
                    "footnotes": "93. Original note",
                    "footnotes_translation": "93. 原注译文",
                    "heading_level": 0,
                    "pages": "9",
                },
                {
                    "original": "Second block.",
                    "translation": "第二段。",
                    "footnotes": "No numbered footnote line",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "9",
                },
            ],
            "pages": "9",
        }], "Export Footnote Markers", 0, doc_id)

        resp = self.client.get(f"/export_md?doc_id={doc_id}")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        md = payload["markdown"]
        self.assertIn("Original text with [^93] marker.", md)
        self.assertIn("译文含上标[^22]与LaTeX标记 [^94]。", md)
        self.assertIn("[^93]: Original note", md)
        self.assertIn("    译：原注译文", md)
        self.assertIn("[脚注] No numbered footnote line", md)

    def test_export_md_normalizes_bracket_inline_markers_to_obsidian_refs(self):
        doc_id = create_doc("export-inline-brackets.pdf")
        save_entries_to_disk([{
            "_pageBP": 10,
            "_model": "qwen-plus",
            "_page_entries": [
                {
                    "original": "Original text [1] and [2].",
                    "translation": "译文 [1] 和 [2]。",
                    "footnotes": "1. Original note one\n2. Original note two",
                    "footnotes_translation": "1. 原注一\n2. 原注二",
                    "heading_level": 0,
                    "pages": "10",
                },
            ],
            "pages": "10",
        }], "Export Inline Brackets", 0, doc_id)

        resp = self.client.get(f"/export_md?doc_id={doc_id}")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertIn("> Original text [^1] and [^2].", payload["markdown"])
        self.assertIn("译文 [^1] 和 [^2]。", payload["markdown"])
        self.assertIn("[^1]: Original note one", payload["markdown"])
        self.assertIn("[^2]: Original note two", payload["markdown"])

    def test_export_md_routes_high_confidence_endnotes_to_chapter_end(self):
        from persistence.storage import save_pdf_toc_to_disk, save_toc_source_offset

        doc_id = create_doc("chapter-endnote.pdf")
        save_pdf_toc_to_disk(doc_id, [
            {"title": "章一", "depth": 0, "book_page": 1},
            {"title": "章二", "depth": 0, "book_page": 6},
        ])
        save_toc_source_offset(doc_id, "user", 0)
        long_note = "12. " + ("这是章节尾注内容。" * 30)
        save_entries_to_disk([{
            "_pageBP": 5,
            "_model": "qwen-plus",
            "_page_entries": [{
                "original": "Body",
                "translation": "正文段落。",
                "footnotes": long_note,
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "5",
            }],
            "pages": "5",
        }], "Chapter Endnote", 0, doc_id)

        md = self.client.get(f"/export_md?doc_id={doc_id}").get_json()["markdown"]
        self.assertIn("正文段落。 [^12]", md)
        self.assertIn("## 本章尾注", md)
        self.assertIn("[^12]:", md)

    def test_export_md_routes_high_confidence_endnotes_to_book_end_without_chapters(self):
        doc_id = create_doc("book-endnote.pdf")
        long_note = "27. " + ("这是全书尾注内容。" * 30)
        save_entries_to_disk([{
            "_pageBP": 9,
            "_model": "qwen-plus",
            "_page_entries": [{
                "original": "Body",
                "translation": "最后页正文。",
                "footnotes": long_note,
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "9",
            }],
            "pages": "9",
        }], "Book Endnote", 0, doc_id)

        md = self.client.get(f"/export_md?doc_id={doc_id}").get_json()["markdown"]
        self.assertIn("最后页正文。 [^27]", md)
        self.assertIn("## 全书尾注", md)
        self.assertIn("[^27]:", md)

    def test_compute_boilerplate_skip_bps_respects_toc_window_and_keeps_long_preface(self):
        entries = [
            {"_pageBP": 1, "_page_entries": [{"original": "All rights reserved. ISBN 978-7-123-45678-9", "translation": ""}]},
            {"_pageBP": 2, "_page_entries": [{"original": "All rights reserved. ISBN 978-7-123-45678-9", "translation": ""}]},
            {"_pageBP": 3, "_page_entries": [{"original": "序言 " + ("关于研究问题的铺垫。" * 40), "translation": ""}]},
            {"_pageBP": 4, "_page_entries": [{"original": "图书在版编目 CIP 数据", "translation": ""}]},
            {"_pageBP": 5, "_page_entries": [{"original": "Chapter One starts here.", "translation": "第一章从这里开始。"}]},
        ]
        chapters = [{"index": 0, "title": "第一章", "start_bp": 5, "end_bp": 20}]
        skip = compute_boilerplate_skip_bps(entries, chapters)

        self.assertIn(1, skip)
        self.assertIn(2, skip)
        self.assertIn(4, skip)
        self.assertNotIn(3, skip)
        self.assertNotIn(5, skip)

    def test_export_md_exclude_boilerplate_flag_filters_pages(self):
        doc_id = create_doc("exclude-boilerplate.pdf")
        save_pdf_toc_to_disk(doc_id, [{"title": "第一章", "depth": 0, "book_page": 3}])
        save_toc_source_offset(doc_id, "user", 0)
        save_entries_to_disk([
            {"_pageBP": 1, "_page_entries": [{"original": "All rights reserved. ISBN 9787111000000", "translation": "版权所有。"}]},
            {"_pageBP": 2, "_page_entries": [{"original": "All rights reserved. ISBN 9787111000000", "translation": "版权所有。"}]},
            {"_pageBP": 3, "_page_entries": [{"original": "正文开场。", "translation": "这是正文第一段。"}]},
        ], "Exclude Boilerplate", 0, doc_id)

        default_md = self.client.get(f"/export_md?doc_id={doc_id}").get_json()["markdown"]
        filtered_md = self.client.get(f"/export_md?doc_id={doc_id}&exclude_boilerplate=1").get_json()["markdown"]

        self.assertIn("版权所有", default_md)
        self.assertIn("这是正文第一段。", default_md)
        self.assertNotIn("版权所有", filtered_md)
        self.assertIn("这是正文第一段。", filtered_md)

    def test_export_md_without_toc_uses_strong_signal_only(self):
        doc_id = create_doc("exclude-without-toc.pdf")
        save_entries_to_disk([
            {"_pageBP": 1, "_page_entries": [{"original": "图书在版编目 CIP 数据", "translation": ""}]},
            {"_pageBP": 2, "_page_entries": [{"original": "这是一段普通短文。", "translation": "短正文。"}]},
        ], "No TOC", 0, doc_id)

        filtered_md = self.client.get(f"/export_md?doc_id={doc_id}&exclude_boilerplate=1").get_json()["markdown"]
        self.assertNotIn("图书在版编目", filtered_md)
        self.assertIn("短正文。", filtered_md)

    def test_detect_book_index_pages_only_hits_tail_index_pages(self):
        entries = []
        for bp in range(1, 11):
            text = f"普通正文第{bp}页。"
            if bp == 9:
                text = "\n".join([
                    "Alpha, 1, 2, 3",
                    "Beta, 4, 5, 6",
                    "Gamma, 7, 8, 9",
                    "Delta, 10, 11, 12",
                    "Epsilon, 13, 14, 15",
                    "Zeta, 16, 17, 18",
                ])
            if bp == 9:
                text = "\n".join([
                    "Afary, Janet, 26, 37, 205",
                    "Althusser, Louis, 5, 9, 22-23",
                    "Balibar, Etienne, 45, 89, 104",
                    "Canguilhem, Georges, 41, 73, 95",
                    "Deleuze, Gilles, 12, 58, 143",
                    "Foucault, Michel, 1, 2, 3",
                ])
            entries.append(
                {
                    "_pageBP": bp,
                    "_page_entries": [{"original": text, "translation": ""}],
                }
            )

        detected = detect_book_index_pages(entries)
        self.assertIn(9, detected)
        self.assertNotIn(8, detected)
        self.assertNotIn(10, detected)

    def test_detect_book_index_pages_keeps_weak_continuation_near_strong_hits(self):
        entries = []
        for bp in range(1, 11):
            text = f"普通正文第{bp}页。"
            if bp == 9:
                text = "\n".join([
                    "Alpha, 1, 2, 3",
                    "Beta, 4, 5, 6",
                    "Gamma, 7, 8, 9",
                    "Delta, 10, 11, 12",
                    "Epsilon, 13, 14, 15",
                    "Zeta, 16, 17, 18",
                ])
            if bp == 10:
                text = "\n".join([
                    "Theta, 21, 22, 23",
                    "Iota, 24, 25, 26",
                    "Kappa, 27, 28, 29",
                    "Lambda, 30, 31, 32",
                    "M, N, O",  # 弱格式噪声行
                    "v. also references",
                ])
            entries.append(
                {
                    "_pageBP": bp,
                    "_page_entries": [{"original": text, "translation": ""}],
                }
            )

        detected = detect_book_index_pages(entries)
        self.assertIn(9, detected)
        self.assertIn(10, detected)

    def test_detect_endnote_collection_pages_accepts_boundary_notes_page_with_two_items(self):
        entries = [
            {
                "_pageBP": 9,
                "_page_entries": [
                    {
                        "original": "NOTES\n1. first note line\n2. second note line",
                        "translation": "",
                    }
                ],
            },
            {
                "_pageBP": 8,
                "_page_entries": [
                    {
                        "original": "正文段落，不应判为尾注集合。",
                        "translation": "",
                    }
                ],
            },
        ]
        chapter_ranges = [{"index": 0, "start_bp": 1, "end_bp": 9}]

        page_map = detect_endnote_collection_pages(entries, chapter_ranges)
        self.assertIn(0, page_map)
        self.assertIn(9, page_map[0])
        self.assertNotIn(8, page_map[0])

    def test_detect_endnote_collection_pages_keeps_mixed_start_page_before_dense_notes_run(self):
        entries = [
            {
                "_pageBP": 7,
                "_page_entries": [
                    {
                        "original": "正文收尾段落。\nNOTES\n1. first note line",
                        "translation": "",
                    }
                ],
            },
            {
                "_pageBP": 8,
                "_page_entries": [
                    {
                        "original": "2. second note line\n3. third note line\n4. fourth note line",
                        "translation": "",
                    }
                ],
            },
            {
                "_pageBP": 9,
                "_page_entries": [
                    {
                        "original": "5. fifth note line\n6. sixth note line\n7. seventh note line",
                        "translation": "",
                    }
                ],
            },
        ]
        chapter_ranges = [{"index": 0, "title": "章一", "start_bp": 1, "end_bp": 9}]

        page_map = detect_endnote_collection_pages(entries, chapter_ranges)
        self.assertIn(0, page_map)
        self.assertEqual(page_map[0], [7, 8, 9])

    def test_detect_endnote_collection_pages_skips_isolated_numbered_page_without_notes_signal(self):
        entries = [
            {
                "_pageBP": 10,
                "_page_entries": [
                    {
                        "original": "\n".join([
                            "14. note fourteen",
                            "15. note fifteen",
                            "16. note sixteen",
                            "17. note seventeen",
                            "18. note eighteen",
                        ]),
                        "translation": "",
                    }
                ],
            },
            {
                "_pageBP": 19,
                "_page_entries": [
                    {
                        "original": "正文收尾。",
                        "translation": "",
                    }
                ],
            },
        ]
        chapter_ranges = [{"index": 0, "title": "章一", "start_bp": 1, "end_bp": 20}]

        page_map = detect_endnote_collection_pages(entries, chapter_ranges)
        self.assertNotIn(0, page_map)

    def test_build_endnote_run_sections_recovers_missing_number_from_pdf_text_layer(self):
        chapter_ranges = [
            {"index": 0, "title": "2. Searching for a Left Governmentality", "start_bp": 33, "end_bp": 52},
            {"index": 1, "title": "3. Beyond the Sovereign Subject: Against Interpretation", "start_bp": 53, "end_bp": 70},
        ]
        run_pages = [
            {
                "bp": 172,
                "orig_lines": [
                    "2 Searching for a Left Governmentality",
                    "111 Rosanvallon, Notre histoire intellectuelle et politique, p. 100.",
                    "112 The SFIO was the historic French Socialist Party created in 1905.",
                    "$ 12/1. $",
                    "114 Interview de Michel Foucault, p. 1509.",
                    "3 Beyond the Sovereign Subject: Against Interpretation",
                ],
                "tr_lines": [],
                "pdf_orig_lines": [
                    "2 Searching for a Left Governmentality",
                    "111 Rosanvallon, Notre histoire intellectuelle et politique, p. 100.",
                    "112 The SFIO was the historic French Socialist Party created in 1905.",
                    "113 Michel Foucault, Structuralisme et poststructuralisme, p. 1271.",
                    "114 Interview de Michel Foucault, p. 1509.",
                    "3 Beyond the Sovereign Subject: Against Interpretation",
                ],
            }
        ]

        sections = _build_endnote_run_sections(run_pages, chapter_ranges)

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["chapter_index"], 0)
        self.assertIn(113, sections[0]["orig_map"])
        self.assertEqual(
            sections[0]["orig_map"][113],
            "Michel Foucault, Structuralisme et poststructuralisme, p. 1271.",
        )
        self.assertEqual(sections[0]["note_numbers"], [111, 112, 113, 114])

    def test_build_endnote_run_sections_recovers_gap_boundary_note_from_pdf_text_layer(self):
        chapter_ranges = [
            {"index": 0, "title": "5. The Revolution Beheaded", "start_bp": 101, "end_bp": 120},
        ]
        run_pages = [
            {
                "bp": 179,
                "orig_lines": [
                    "5 The Revolution Beheaded",
                    "23 Ibid., p. 223.",
                ],
                "tr_lines": [],
                "pdf_orig_lines": [
                    "5 The Revolution Beheaded",
                    "23 Ibid., p. 223.",
                    "24 Ibid.",
                ],
            },
            {
                "bp": 180,
                "orig_lines": [
                    "25 See, in particular, Mitchell Dean, Critical and Effective Histories, pp. 174-93.",
                ],
                "tr_lines": [],
                "pdf_orig_lines": [
                    "25 See, in particular, Mitchell Dean, Critical and Effective Histories, pp. 174-93.",
                ],
            },
        ]

        sections = _build_endnote_run_sections(run_pages, chapter_ranges)

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["chapter_index"], 0)
        self.assertIn(24, sections[0]["orig_map"])
        self.assertEqual(sections[0]["orig_map"][24], "Ibid.")
        self.assertEqual(sections[0]["note_numbers"], [23, 24, 25])

    def test_export_md_splits_contiguous_notes_by_chapter_and_sorts_each_section(self):
        doc_id = create_doc("split-notes-by-chapter.pdf")
        save_pdf_toc_to_disk(doc_id, [
            {"title": "Introduction: The Last Man Takes LSD", "depth": 0, "book_page": 1},
            {"title": "6. Foucault's Normativity", "depth": 0, "book_page": 5},
            {"title": "7. Rogue Neoliberalism and Liturgical Power", "depth": 0, "book_page": 8},
            {"title": "Notes", "depth": 0, "book_page": 10},
            {"title": "Index", "depth": 0, "book_page": 13},
        ])
        save_toc_source_offset(doc_id, "user", 0)
        save_entries_to_disk([
            {
                "_pageBP": 1,
                "_model": "qwen-plus",
                "_page_entries": [{
                    "_startBP": 1,
                    "original": "Introduction body [^3][^1][^2].",
                    "translation": "引言正文[^3][^1][^2]。",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "1",
                }],
                "pages": "1",
            },
            {
                "_pageBP": 5,
                "_model": "qwen-plus",
                "_page_entries": [{
                    "_startBP": 5,
                    "original": "Normativity body [^2][^1].",
                    "translation": "第六章正文[^2][^1]。",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "5",
                }],
                "pages": "5",
            },
            {
                "_pageBP": 8,
                "_model": "qwen-plus",
                "_page_entries": [{
                    "_startBP": 8,
                    "original": "Rogue body [^1].",
                    "translation": "第七章正文[^1]。",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "8",
                }],
                "pages": "8",
            },
            {
                "_pageBP": 10,
                "_model": "qwen-plus",
                "_page_entries": [{
                    "_startBP": 10,
                    "original": "Introduction: The Last Man Takes LSD\n1 Intro note one.\n2 Intro note two.\n3 Intro note three.",
                    "translation": "引言：最后的人服用迷幻药（LSD）\n1 引言注一。\n2 引言注二。\n3 引言注三。",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "10",
                }],
                "pages": "10",
            },
            {
                "_pageBP": 11,
                "_model": "qwen-plus",
                "_page_entries": [{
                    "_startBP": 11,
                    "original": "6 Foucault's Normativity\n1 Norm note one.\n2 Norm note two.",
                    "translation": "6 福柯的规范性\n1 规范性注一。\n2 规范性注二。",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "11",
                }],
                "pages": "11",
            },
            {
                "_pageBP": 12,
                "_model": "qwen-plus",
                "_page_entries": [{
                    "_startBP": 12,
                    "original": "7 Rogue Neoliberalism and Liturgical Power\n1 Rogue note one.",
                    "translation": "7 流氓新自由主义与礼仪权力\n1 流氓注一。",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "12",
                }],
                "pages": "12",
            },
        ], "Split Notes By Chapter", 0, doc_id)

        md = self.client.get(f"/export_md?doc_id={doc_id}").get_json()["markdown"]

        self.assertEqual(md.count("## 本章尾注"), 1)
        self.assertNotIn("## 全书尾注", md)
        self.assertIn("引言正文[^3][^ch00-1][^ch00-2]。", md)
        self.assertIn("第六章正文[^ch01-2][^ch01-1]。", md)
        self.assertIn("第七章正文[^ch02-1]。", md)
        self.assertIn("### Introduction: The Last Man Takes LSD", md)
        self.assertIn("### 6. Foucault's Normativity", md)
        self.assertIn("### 7. Rogue Neoliberalism and Liturgical Power", md)
        self.assertIn("[^ch00-1]: Intro note one.", md)
        self.assertIn("[^ch00-2]: Intro note two.", md)
        self.assertIn("[^3]: Intro note three.", md)
        self.assertIn("[^ch01-1]: Norm note one.", md)
        self.assertIn("[^ch01-2]: Norm note two.", md)
        self.assertIn("[^ch02-1]: Rogue note one.", md)

        intro_pos = md.index("### Introduction: The Last Man Takes LSD")
        chapter6_pos = md.index("### 6. Foucault's Normativity")
        chapter7_pos = md.index("### 7. Rogue Neoliberalism and Liturgical Power")
        self.assertLess(intro_pos, chapter6_pos)
        self.assertLess(chapter6_pos, chapter7_pos)
        self.assertLess(md.index("[^ch00-1]: Intro note one."), md.index("[^ch00-2]: Intro note two."))
        self.assertLess(md.index("[^ch00-2]: Intro note two."), md.index("[^3]: Intro note three."))
        self.assertLess(md.index("[^ch01-1]: Norm note one."), md.index("[^ch01-2]: Norm note two."))

    def test_export_md_prefers_structured_endnote_metadata_when_raw_text_unparseable(self):
        doc_id = create_doc("structured-endnotes.pdf")
        save_pdf_toc_to_disk(doc_id, [
            {"title": "Introduction", "depth": 0, "book_page": 1},
            {"title": "Notes", "depth": 0, "book_page": 5},
        ])
        save_toc_source_offset(doc_id, "user", 0)
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "markdown": "Introduction body [^1][^2].",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 5,
                "fileIdx": 4,
                "markdown": "NOISY OCR PAGE",
                "footnotes": "",
                "textSource": "ocr",
                "_note_scan_version": 1,
                "_note_scan": {
                    "page_kind": "endnote_collection",
                    "items": [
                        {
                            "kind": "endnote",
                            "marker": "1.",
                            "number": 1,
                            "text": "Structured note one.",
                            "order": 1,
                            "source": "note_scan",
                            "confidence": 1.0,
                            "section_title": "Introduction",
                        },
                        {
                            "kind": "endnote",
                            "marker": "2.",
                            "number": 2,
                            "text": "Structured note two.",
                            "order": 2,
                            "source": "note_scan",
                            "confidence": 1.0,
                            "section_title": "Introduction",
                        },
                    ],
                    "section_hints": ["Notes", "Introduction"],
                    "ambiguity_flags": [],
                    "reviewed_by_model": False,
                },
            },
        ], "Structured Endnotes", doc_id)
        save_entries_to_disk([
            {
                "_pageBP": 1,
                "_model": "qwen-plus",
                "_page_entries": [{
                    "_startBP": 1,
                    "original": "Introduction body [^1][^2].",
                    "translation": "引言正文[^1][^2]。",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "1",
                }],
                "pages": "1",
            },
            {
                "_pageBP": 5,
                "_model": "qwen-plus",
                "_page_entries": [
                    {
                        "_startBP": 5,
                        "original": "Structured note one.",
                        "translation": "结构化尾注一。",
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                        "pages": "5",
                        "_note_kind": "endnote",
                        "_note_marker": "1.",
                        "_note_number": 1,
                        "_note_section_title": "Introduction",
                        "_note_confidence": 1.0,
                    },
                    {
                        "_startBP": 5,
                        "original": "Structured note two.",
                        "translation": "结构化尾注二。",
                        "footnotes": "",
                        "footnotes_translation": "",
                        "heading_level": 0,
                        "pages": "5",
                        "_note_kind": "endnote",
                        "_note_marker": "2.",
                        "_note_number": 2,
                        "_note_section_title": "Introduction",
                        "_note_confidence": 1.0,
                    },
                ],
                "pages": "5",
            },
        ], "Structured Endnotes", 0, doc_id)

        md = self.client.get(f"/export_md?doc_id={doc_id}").get_json()["markdown"]

        self.assertIn("引言正文[^1][^2]。", md)
        self.assertIn("## 本章尾注", md)
        self.assertIn("### Introduction", md)
        self.assertIn("[^1]: Structured note one.", md)
        self.assertIn("[^2]: Structured note two.", md)

    def test_gen_markdown_prefixes_endnotes_when_chapter_numbers_overlap(self):
        entries = [
            {
                "_pageBP": 1,
                "_page_entries": [
                    {
                        "_startBP": 1,
                        "original": "Chap1 body [^3].",
                        "translation": "第一章正文[^3]。",
                        "heading_level": 0,
                        "footnotes": "",
                        "footnotes_translation": "",
                    }
                ],
            },
            {
                "_pageBP": 6,
                "_page_entries": [
                    {
                        "_startBP": 6,
                        "original": "Chap2 body [^3].",
                        "translation": "第二章正文[^3]。",
                        "heading_level": 0,
                        "footnotes": "",
                        "footnotes_translation": "",
                    }
                ],
            },
        ]
        toc_depth_map = {1: 0, 6: 0}
        endnote_index = {
            0: {3: {"orig": "Chapter 1 note", "tr": "第一章尾注"}},
            1: {3: {"orig": "Chapter 2 note", "tr": "第二章尾注"}},
        }

        md = gen_markdown(entries, toc_depth_map=toc_depth_map, endnote_index=endnote_index)
        self.assertIn("第一章正文[^ch00-3]。", md)
        self.assertIn("第二章正文[^ch01-3]。", md)
        self.assertIn("[^ch00-3]: Chapter 1 note", md)
        self.assertIn("[^ch01-3]: Chapter 2 note", md)
        self.assertNotIn("[^3]:", md)

    def test_gen_markdown_demotes_preface_headings_before_first_toc_chapter(self):
        entries = [
            {
                "_pageBP": 1,
                "_page_entries": [
                    {
                        "_startBP": 1,
                        "original": "COUVERTURE",
                        "translation": "封面",
                        "heading_level": 1,
                        "footnotes": "",
                        "footnotes_translation": "",
                    }
                ],
            },
            {
                "_pageBP": 5,
                "_page_entries": [
                    {
                        "_startBP": 5,
                        "original": "LECON DU 10 JANVIER 1979",
                        "translation": "1979年1月10日课程",
                        "heading_level": 1,
                        "footnotes": "",
                        "footnotes_translation": "",
                    }
                ],
            },
        ]
        toc_depth_map = {5: 0}
        md = gen_markdown(entries, toc_depth_map=toc_depth_map)

        self.assertIn("> COUVERTURE", md)
        self.assertIn("封面", md)
        self.assertIn("# 1979年1月10日课程", md)
        self.assertNotIn("# 封面", md)

    def test_gen_markdown_uses_nearby_toc_depth_when_heading_page_off_by_one(self):
        entries = [
            {
                "_pageBP": 17,
                "_page_entries": [
                    {
                        "_startBP": 17,
                        "original": "LECON DU 10 JANVIER 1979",
                        "translation": "1979年1月10日课程",
                        "heading_level": 1,
                        "footnotes": "",
                        "footnotes_translation": "",
                    }
                ],
            }
        ]
        # TOC 锚点可能在上一页（常见于目录页码与实际正文起始轻微错位）
        toc_depth_map = {16: 1}
        md = gen_markdown(entries, toc_depth_map=toc_depth_map)
        self.assertIn("## 1979年1月10日课程", md)

    def test_gen_markdown_demotes_heading_when_toc_title_mismatch_on_same_page(self):
        entries = [
            {
                "_pageBP": 20,
                "_page_entries": [
                    {
                        "_startBP": 20,
                        "original": "Abondance / rarete",
                        "translation": "丰裕/稀缺",
                        "heading_level": 1,
                        "footnotes": "",
                        "footnotes_translation": "",
                    }
                ],
            }
        ]
        toc_depth_map = {20: 0}
        toc_title_map = {20: "Indices"}
        md = gen_markdown(entries, toc_depth_map=toc_depth_map, toc_title_map=toc_title_map)
        self.assertNotIn("# 丰裕/稀缺", md)
        self.assertIn("丰裕/稀缺", md)

    def test_build_toc_title_map_maps_effective_book_page(self):
        title_map = build_toc_title_map(
            [{"title": "Indices", "depth": 0, "book_page": 337}],
            offset=13,
        )
        self.assertEqual(title_map[350], "Indices")

    def test_parse_page_markdown_does_not_cross_merge_unrelated_chinese_next_page(self):
        pages = [
            {"bookPage": 1, "markdown": "这是第一页末尾没有句号"},
            {"bookPage": 2, "markdown": "这是第二页的新段落。"},
        ]
        paras = parse_page_markdown(pages, 1)
        self.assertEqual(len(paras), 1)
        self.assertEqual(paras[0]["startBP"], 1)
        self.assertEqual(paras[0]["endBP"], 1)
        self.assertNotEqual(paras[0].get("cross_page"), "merged_next")

    def test_parse_page_markdown_keeps_hyphen_continuation_merge(self):
        pages = [
            {"bookPage": 1, "markdown": "The central argu-"},
            {"bookPage": 2, "markdown": "ment continues on next page."},
        ]
        paras = parse_page_markdown(pages, 1)
        self.assertEqual(len(paras), 1)
        self.assertEqual(paras[0]["endBP"], 2)
        self.assertEqual(paras[0].get("cross_page"), "merged_next")

    def test_parse_page_markdown_merges_uppercase_continuation_after_mid_sentence_page_break(self):
        pages = [
            {
                "bookPage": 3,
                "markdown": (
                    "Third, part of this anti-neurasthenia movement was associated with a brief "
                    "boom in psychology during this period. Ting Tsan was instrumental in "
                    "establishing the Chinese"
                ),
            },
            {
                "bookPage": 4,
                "markdown": (
                    "Academy of Sciences and its Institute of Psychology in the early 1950s "
                    "(Fan, 2017).\n\n## Culture of therapeutic experiment"
                ),
            },
        ]
        page3_paras = parse_page_markdown(pages, 3)
        self.assertEqual(page3_paras[-1]["endBP"], 4)
        self.assertEqual(page3_paras[-1].get("cross_page"), "merged_next")
        self.assertIn(
            "Academy of Sciences and its Institute of Psychology",
            page3_paras[-1]["text"],
        )

        page4_paras = parse_page_markdown(pages, 4)
        self.assertTrue(page4_paras[0].get("consumed_by_prev"))
        self.assertEqual(page4_paras[1]["text"], "Culture of therapeutic experiment")

    def test_parse_page_markdown_merges_uppercase_continuation_for_proper_name_split(self):
        pages = [
            {
                "bookPage": 7,
                "markdown": (
                    "The invention and popularization of SST helps us to get a better "
                    "understanding of the history of Maoist China. First, according to an "
                    "aetiological study conducted by the Beijing College of"
                ),
            },
            {
                "bookPage": 8,
                "markdown": (
                    "Medicine in 1960, the causes of neurasthenia included psychological "
                    "shocks, work-related mental stress, and lack of sleep."
                ),
            },
        ]
        paras = parse_page_markdown(pages, 7)
        self.assertEqual(paras[0]["endBP"], 8)
        self.assertEqual(paras[0].get("cross_page"), "merged_next")
        self.assertIn("Beijing College of Medicine in 1960", paras[0]["text"])

    def test_parse_page_markdown_footnote_superscript_stops_merged_next_chain(self):
        """句末 Unicode 上标脚注不应让 ends_mid 误判，避免跨多页链式合并（Goldstein 类书籍）。"""
        # 末字符剥离 ⁶⁹ 后应为引号，视为句终，不应对下一页做 merged_next
        pages = [
            {
                "bookPage": 52,
                "markdown": (
                    'Law replied to that charge. How could his System be "chimerical"? '
                    'Didn\'t the Dutch furnish proof?"⁶⁹'
                ),
            },
            {
                "bookPage": 53,
                "markdown": (
                    "Self-Contained Persons: The Odd Trio\n\n"
                    "The belief that a laissez-faire economy would overstimulate."
                ),
            },
            {"bookPage": 54, "markdown": "he presents his eroticism as having been bound up."},
        ]
        paras = parse_page_markdown(pages, 52)
        self.assertEqual(len(paras), 1)
        self.assertEqual(paras[0]["startBP"], 52)
        self.assertEqual(paras[0]["endBP"], 52)
        self.assertNotEqual(paras[0].get("cross_page"), "merged_next")
        self.assertNotIn("Self-Contained Persons", paras[0]["text"])
        self.assertNotIn("he presents his eroticism", paras[0]["text"])

    def test_parse_page_markdown_merged_next_stops_at_markdown_heading(self):
        """merged_next 链延续多页时，遇到 # 标题段应终止，不把该标题拼入上一页末段。"""
        pages = [
            {
                "bookPage": 1,
                "markdown": (
                    "A long opening paragraph that deliberately avoids ending with a period"
                ),
            },
            {
                "bookPage": 2,
                "markdown": (
                    "still continues here and also avoids any final sentence punctuation"
                ),
            },
            {"bookPage": 3, "markdown": "## Section Break\n\nSome body text."},
        ]
        paras = parse_page_markdown(pages, 1)
        self.assertEqual(len(paras), 1)
        self.assertNotIn("Section Break", paras[0]["text"])
        self.assertNotIn("Some body text", paras[0]["text"])

    def test_get_page_context_skips_consumed_paragraph_after_previous_page_merge(self):
        pages = [
            {"bookPage": 1, "markdown": "The central argu-"},
            {"bookPage": 2, "markdown": "ment continues on next page.\n\n## New Section\n\nFresh paragraph."},
        ]
        page1_paras = parse_page_markdown(pages, 1)
        self.assertEqual(page1_paras[0].get("cross_page"), "merged_next")

        page2_paras = parse_page_markdown(pages, 2)
        self.assertTrue(page2_paras[0].get("consumed_by_prev"))
        self.assertEqual(page2_paras[0]["text"], "ment continues on next page.")

        ctx = get_page_context_for_translate(pages, 2)
        self.assertEqual(
            [para["text"] for para in ctx["paragraphs"]],
            ["New Section", "Fresh paragraph."],
        )

    def test_parse_page_markdown_keeps_heading_on_mixed_body_endnotes_page(self):
        pages = [
            {
                "bookPage": 359,
                "markdown": (
                    "Tail body line.\n\n"
                    "82. First note.\n\n"
                    "### 2. The Revolutionary Schooling of Imagination\n\n"
                    "1. Restarted note."
                ),
                "_note_scan": {
                    "page_kind": "mixed_body_endnotes",
                    "note_start_line_index": 1,
                    "items": [
                        {"kind": "endnote", "marker": "82.", "text": "82. First note."},
                        {
                            "kind": "endnote",
                            "marker": "1.",
                            "text": "1. Restarted note.",
                            "section_title": "### 2. The Revolutionary Schooling of Imagination",
                        },
                    ],
                    "section_hints": ["### 2. The Revolutionary Schooling of Imagination"],
                },
            }
        ]
        paras = parse_page_markdown(pages, 359)
        self.assertEqual(
            [para["text"] for para in paras if para["heading_level"] > 0],
            ["2. The Revolutionary Schooling of Imagination"],
        )
        self.assertFalse(any("82. First note." in para["text"] for para in paras))
        self.assertFalse(any("1. Restarted note." in para["text"] for para in paras))

    def test_segmentation_audit_reports_uppercase_continuation_candidates(self):
        pages = [
            {
                "bookPage": 3,
                "markdown": (
                    "Third, part of this anti-neurasthenia movement was associated with a brief "
                    "boom in psychology during this period. Ting Tsan was instrumental in "
                    "establishing the Chinese"
                ),
            },
            {
                "bookPage": 4,
                "markdown": (
                    "Academy of Sciences and its Institute of Psychology in the early 1950s "
                    "(Fan, 2017).\n\n## Culture of therapeutic experiment"
                ),
            },
            {"bookPage": 5, "markdown": "## Next Section\n\nFresh paragraph."},
        ]
        candidates = find_uppercase_continuation_candidates(pages)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["book_page"], 3)
        self.assertEqual(candidates[0]["next_book_page"], 4)
        self.assertIn("establishing the Chinese", candidates[0]["tail_preview"])
        self.assertTrue(candidates[0]["next_starts_upper"])

    def test_parse_page_markdown_recovers_embedded_note_heading_from_note_scan_items(self):
        pages = [
            {
                "bookPage": 365,
                "markdown": "95. A long note body that swallowed the heading.",
                "_note_scan": {
                    "page_kind": "mixed_body_endnotes",
                    "note_start_line_index": 0,
                    "items": [
                        {
                            "kind": "endnote",
                            "marker": "95.",
                            "text": (
                                "95. A long note body.\n"
                                "### 3. Is There a Self in This Mental Apparatus?\n"
                                "1. Restarted note after heading."
                            ),
                        }
                    ],
                    "section_hints": [],
                },
            }
        ]
        paras = parse_page_markdown(pages, 365)
        self.assertEqual(
            [para["text"] for para in paras if para["heading_level"] > 0],
            ["3. Is There a Self in This Mental Apparatus?"],
        )

    def test_parse_page_markdown_promotes_plain_title_when_toc_starts_here(self):
        doc_id = create_doc("toc-promote.pdf")
        save_pdf_toc_to_disk(
            doc_id,
            [
                {
                    "title": "Religious and Secular Access to the Vie Intérieure",
                    "depth": 0,
                    "book_page": 2,
                }
            ],
        )
        set_current_doc(doc_id)
        pages = [
            {"bookPage": 1, "markdown": "Previous page text."},
            {
                "bookPage": 2,
                "markdown": (
                    "Religious and Secular Access to the Vie Intérieure\n\n"
                    "Body paragraph starts here."
                ),
            },
        ]
        paras = parse_page_markdown(pages, 2)
        self.assertGreater(paras[0]["heading_level"], 0)
        self.assertEqual(paras[0]["text"], "Religious and Secular Access to the Vie Intérieure")

    def test_parse_page_markdown_does_not_promote_garbled_long_paragraph_title_block(self):
        pages = [
            {
                "bookPage": 188,
                "markdown": (
                    "In sum, although Cousin was, in technical philosophical terms, a zealous champion of introspection.\n\n"
                    "The chief discovery that Cousin made by means of introspection was that the human personality could be identified with activity."
                ),
                "blocks": [
                    {
                        "heading_level": 0,
                        "label": "text",
                        "text": "In sum, although Cousin was, in technical philosophical terms, a zealous champion of introspection.",
                    },
                    {
                        "heading_level": 0,
                        "label": "paragraph_title",
                        "text": (
                            "to have utterly lacked the propensity to rummage around in his psyche or appreciate "
                            "his inner state, that such in-dwelling exceeded the bounds of A Discourse of Human "
                            "Difference: The Selved to find layers of hidden complexity in his motives and feelings."
                        ),
                    },
                    {
                        "heading_level": 0,
                        "label": "text",
                        "text": "The chief discovery that Cousin made by means of introspection was that the human personality could be identified with activity.",
                    },
                ],
            }
        ]
        paras = parse_page_markdown(pages, 188)
        self.assertFalse(any(para["heading_level"] > 0 for para in paras))

    def test_translate_snapshot_loads_failures_from_translate_failures_table(self):
        doc_id = create_doc("failure.pdf")
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=5,
            total_pages=2,
            done_pages=1,
            processed_pages=2,
            pending_pages=0,
            current_bp=6,
            current_page_idx=2,
            failed_bps=[6],
            failed_pages=[{"bp": 6, "error": "失败页"}],
        )

        repo = SQLiteRepository()
        failures = repo.list_translate_failures(doc_id)
        snapshot = translate_runtime.get_translate_snapshot(doc_id)

        self.assertEqual(failures[0]["bp"], 6)
        self.assertEqual(snapshot["failed_pages"][0]["bp"], 6)
        self.assertEqual(snapshot["failed_bps"], [6])

    def test_resume_bp_and_phase_for_partial_failed_and_stopped(self):
        """验证 resume_bp 规则与 phase 切换行为。"""
        doc_id = create_doc("resume.pdf")
        # 准备两页，起始从 p.5
        save_pages_to_disk([
            {
                "bookPage": 5,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 5",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 6,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 6",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "resume.pdf", doc_id)

        # 场景 1：partial_failed，优先从失败页/部分失败页恢复
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=5,
            current_bp=6,
            total_pages=2,
            done_pages=1,
            processed_pages=2,
            pending_pages=0,
            failed_bps=[6],
            partial_failed_bps=[],
            failed_pages=[{"bp": 6, "error": "boom"}],
        )
        snapshot = translate_runtime.get_translate_snapshot(doc_id)
        self.assertEqual(snapshot["phase"], "partial_failed")
        self.assertEqual(snapshot["resume_bp"], 6)

        # 场景 2：stopped，当前页尚未处理，应从 current_bp 恢复
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            start_bp=5,
            current_bp=6,
            total_pages=2,
            done_pages=1,
            processed_pages=1,
            pending_pages=1,
            failed_bps=[],
            partial_failed_bps=[],
            failed_pages=[],
        )
        snapshot2 = translate_runtime.get_translate_snapshot(doc_id)
        self.assertEqual(snapshot2["phase"], "stopped")
        self.assertEqual(snapshot2["resume_bp"], 6)

        # 场景 3：全部完成但存在部分失败页，phase 应为 partial_failed，resume_bp 指向首个需要关注的页
        save_entries_to_disk([{
            "_pageBP": 5,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 5",
                "translation": "[翻译失败: timeout]",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "5",
                "_status": "error",
                "_error": "timeout",
            }],
            "pages": "5",
        }], "resume.pdf", 0, doc_id)
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=5,
            current_bp=None,
            total_pages=2,
            done_pages=2,
            processed_pages=2,
            pending_pages=0,
            failed_bps=[],
            partial_failed_bps=[5],
            failed_pages=[],
        )
        snapshot3 = translate_runtime.get_translate_snapshot(doc_id)
        self.assertEqual(snapshot3["phase"], "partial_failed")
        self.assertEqual(snapshot3["resume_bp"], 5)

    def test_fetch_next_success_reconciles_failed_state_in_translate_snapshot(self):
        doc_id = create_doc("fetch-next-success.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 1",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 2,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 2",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "fetch-next-success.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "翻译 1",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
            }],
            "pages": "1",
        }], "Fetch Next", 0, doc_id)
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="partial_failed",
            start_bp=1,
            current_bp=2,
            total_pages=2,
            done_pages=1,
            processed_pages=1,
            pending_pages=1,
            failed_bps=[2],
            failed_pages=[{"bp": 2, "error": "旧失败"}],
        )

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "translate_page", return_value={
                "_pageBP": 2,
                "_model": "sonnet",
                "_page_entries": [{
                    "original": "Page 2",
                    "translation": "翻译 2",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "2",
                }],
                "pages": "2",
            }),
        ):
            resp = self._post("/fetch_next", data={"doc_id": doc_id})

        self.assertEqual(resp.status_code, 302)
        status = self.client.get(f"/translate_status?doc_id={doc_id}").get_json()
        self.assertEqual(status["failed_bps"], [])
        self.assertEqual(status["partial_failed_bps"], [])
        self.assertIn(status["phase"], ("done", "stopped", "idle"))

    def test_fetch_next_failure_marks_failed_page_in_translate_snapshot(self):
        doc_id = create_doc("fetch-next-fail.pdf")
        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 1",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 2,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 2",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "fetch-next-fail.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "翻译 1",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
            }],
            "pages": "1",
        }], "Fetch Next", 0, doc_id)
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="stopped",
            start_bp=1,
            current_bp=2,
            total_pages=2,
            done_pages=1,
            processed_pages=1,
            pending_pages=1,
            failed_bps=[],
            failed_pages=[],
        )

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "translate_page", side_effect=RuntimeError("fetch_next boom")),
        ):
            resp = self._post("/fetch_next", data={"doc_id": doc_id})

        self.assertEqual(resp.status_code, 302)
        status = self.client.get(f"/translate_status?doc_id={doc_id}").get_json()
        self.assertEqual(status["failed_bps"], [2])
        self.assertEqual(status["failed_pages"][0]["bp"], 2)
        self.assertIn("fetch_next boom", status["last_error"])
        self.assertEqual(status["resume_bp"], 2)

    def test_retranslate_failure_always_marks_failed_page(self):
        doc_id = create_doc("retranslate-fail.pdf")
        save_pages_to_disk([{
            "bookPage": 7,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 7",
            "footnotes": "",
            "textSource": "ocr",
        }], "retranslate-fail.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 7,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 7",
                "translation": "旧翻译",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "7",
                "_status": "done",
                "_error": "",
            }],
            "pages": "7",
        }], "Retran", 0, doc_id)
        tasks._save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="done",
            start_bp=7,
            current_bp=7,
            total_pages=1,
            done_pages=1,
            processed_pages=1,
            pending_pages=0,
            failed_bps=[],
            failed_pages=[],
        )

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "translate_page", side_effect=RuntimeError("retranslate boom")),
        ):
            resp = self._post(f"/retranslate/7", data={"doc_id": doc_id, "target": "builtin:qwen-plus"})

        self.assertEqual(resp.status_code, 302)
        status = self.client.get(f"/translate_status?doc_id={doc_id}").get_json()
        self.assertEqual(status["failed_bps"], [7])
        self.assertEqual(status["failed_pages"][0]["bp"], 7)
        self.assertIn("retranslate boom", status["last_error"])
        self.assertEqual(status["resume_bp"], 7)

    def test_save_manual_revision_updates_reading_and_export(self):
        doc_id = create_doc("manual-revision.pdf")
        save_pages_to_disk([{
            "bookPage": 16,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 16",
            "footnotes": "",
            "textSource": "ocr",
        }], "manual-revision.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 16,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Paragraph A",
                "translation": "机器译文 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "16",
                "_status": "done",
                "_error": "",
            }],
            "pages": "16",
        }], "Manual Revision", 0, doc_id)

        read_before = self.client.get(f"/reading?bp=16&doc_id={doc_id}").get_data(as_text=True)
        resp = self._post_json(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={
                "bp": 16,
                "segment_index": 0,
                "translation": "人工修订 A",
            },
        )
        payload = resp.get_json()
        read_html = self.client.get(f"/reading?bp=16&doc_id={doc_id}").get_data(as_text=True)
        export_payload = self.client.get(f"/export_md?doc_id={doc_id}").get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["segment"]["translation"], "人工修订 A")
        self.assertEqual(payload["segment"]["_translation_source"], "manual")
        self.assertIn("编辑本页段落", read_before)
        self.assertIn("机器译文", read_before)
        self.assertIn("人工修订 A", read_html)
        self.assertIn("人工修订", read_html)
        self.assertIn("人工修订 A", export_payload["markdown"])
        self.assertNotIn("机器译文 A", export_payload["markdown"])

    def test_page_editor_api_round_trip_updates_page_and_history(self):
        doc_id = create_doc("page-editor.pdf")
        save_pages_to_disk([{
            "bookPage": 16,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 16",
            "footnotes": "",
            "textSource": "ocr",
        }], "page-editor.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 16,
            "_model": "sonnet",
            "_page_entries": [
                {
                    "original": "第一段原文",
                    "translation": "第一段译文",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "16",
                    "_status": "done",
                    "_error": "",
                },
                {
                    "original": "第二段原文",
                    "translation": "第二段译文",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "16",
                    "_status": "done",
                    "_error": "",
                },
            ],
            "pages": "16",
        }], "Page Editor", 0, doc_id)

        get_payload = self.client.get(f"/api/page_editor?doc_id={doc_id}&bp=16").get_json()
        resp = self._post_json(
            "/api/page_editor",
            query_string={"doc_id": doc_id},
            json={
                "bp": 16,
                "base_updated_at": get_payload["page"]["updated_at"],
                "rows": [
                    {
                        "order": 0,
                        "kind": "heading",
                        "heading_level": 2,
                        "original": "新的小标题",
                        "translation": "新的小标题译文",
                    },
                    {
                        "order": 1,
                        "kind": "body",
                        "heading_level": 0,
                        "original": "第一段原文（修订）",
                        "translation": "第一段译文（修订）",
                    },
                ],
            },
        )
        payload = resp.get_json()
        read_html = self.client.get(f"/reading?bp=16&doc_id={doc_id}").get_data(as_text=True)
        export_payload = self.client.get(f"/export_md?doc_id={doc_id}").get_json()
        history_payload = self.client.get(f"/api/page_editor/history?doc_id={doc_id}&bp=16").get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        page = SQLiteRepository().get_effective_translation_page(doc_id, 16)
        self.assertEqual(len(page["_page_entries"]), 2)
        self.assertEqual(page["_page_entries"][0]["heading_level"], 2)
        self.assertEqual(page["_page_entries"][0]["translation"], "新的小标题译文")
        self.assertEqual(page["_page_entries"][1]["original"], "第一段原文（修订）")
        self.assertEqual(page["_page_entries"][1]["translation"], "第一段译文（修订）")
        self.assertIn("新的小标题译文", read_html)
        self.assertIn("第一段译文（修订）", export_payload["markdown"])
        self.assertTrue(history_payload["ok"])
        self.assertGreaterEqual(len(history_payload["revisions"]), 1)
        self.assertIn("第二段原文", history_payload["revisions"][0]["entry"]["_page_entries"][1]["original"])

    def test_page_editor_api_supports_fnm_view_and_history(self):
        doc_id = create_doc("page-editor-fnm.pdf")
        save_pages_to_disk([{
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 1",
            "footnotes": "",
            "textSource": "ocr",
        }], "page-editor-fnm.pdf", doc_id)
        repo = SQLiteRepository()
        run_id = repo.create_fnm_run(
            doc_id,
            status="done",
            page_count=1,
            section_count=1,
            note_count=0,
            unit_count=1,
        )
        self._replace_demo_fnm_structure(
            repo,
            doc_id,
            chapter_pages=[1],
            note_items=[],
        )
        repo.replace_fnm_data(
            doc_id,
            preserve_structure=True,
            notes=[],
            units=[
                {
                    "unit_id": f"{doc_id}-body-0001",
                    "kind": "body",
                    "section_id": "sec-01-demo",
                    "section_title": "Demo",
                    "section_start_page": 1,
                    "section_end_page": 1,
                    "note_id": None,
                    "page_start": 1,
                    "page_end": 1,
                    "char_count": 20,
                    "source_text": "旧标题\n\n旧正文",
                    "translated_text": "旧标题译文\n\n旧正文译文",
                    "status": "done",
                    "error_msg": "",
                    "target_ref": "",
                    "page_segments": [
                        {
                            "page_no": 1,
                            "source_text": "旧标题\n\n旧正文",
                            "display_text": "## 旧标题\n\n旧正文",
                            "paragraphs": [
                                {
                                    "order": 1,
                                    "kind": "heading",
                                    "heading_level": 2,
                                    "source_text": "旧标题",
                                    "display_text": "旧标题",
                                    "cross_page": None,
                                    "consumed_by_prev": False,
                                    "section_path": ["Demo"],
                                    "print_page_label": "1",
                                    "translated_text": "旧标题译文",
                                },
                                {
                                    "order": 2,
                                    "kind": "body",
                                    "heading_level": 0,
                                    "source_text": "旧正文",
                                    "display_text": "旧正文",
                                    "cross_page": None,
                                    "consumed_by_prev": False,
                                    "section_path": ["Demo"],
                                    "print_page_label": "1",
                                    "translated_text": "旧正文译文",
                                },
                            ],
                        },
                    ],
                },
            ],
        )
        repo.update_fnm_run(doc_id, run_id, status="done", error_msg="")
        get_resp = self.client.get(f"/api/page_editor?doc_id={doc_id}&bp=1&view=fnm")
        resp = self._post_json(
            "/api/page_editor",
            query_string={"doc_id": doc_id},
            json={
                "bp": 1,
                "view": "fnm",
                "base_updated_at": 0,
                "rows": [
                    {
                        "order": 0,
                        "kind": "heading",
                        "heading_level": 2,
                        "original": "新标题",
                        "translation": "新标题译文",
                    },
                    {
                        "order": 1,
                        "kind": "body",
                        "heading_level": 0,
                        "original": "新正文",
                        "translation": "新正文译文",
                        "cross_page": "cont_both",
                        "section_path": ["Edited", "Section"],
                        "fnm_refs": [
                            {"kind": "endnote", "note_id": "en-01-0009"},
                            {"kind": "footnote", "note_id": "fn-01-0002"},
                            {"kind": "", "note_id": ""},
                        ],
                    },
                ],
            },
        )
        history_resp = self.client.get(f"/api/page_editor/history?doc_id={doc_id}&bp=1&view=fnm")

        self.assertEqual(get_resp.status_code, 403)
        self.assertEqual(get_resp.get_json()["error"], "fnm_read_only")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["error"], "fnm_read_only")
        self.assertEqual(history_resp.status_code, 403)
        self.assertEqual(history_resp.get_json()["error"], "fnm_read_only")


    def test_translate_status_exposes_translation_and_companion_model_metadata(self):
        doc_id = create_doc("translate-status-models.pdf")
        save_pages_to_disk([{
            "bookPage": 1,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 1",
            "footnotes": "",
            "textSource": "ocr",
        }], "translate-status-models.pdf", doc_id)

        tasks._save_translate_state(
            doc_id,
            running=True,
            stop_requested=False,
            phase="running",
            start_bp=1,
            current_bp=1,
            total_pages=1,
            done_pages=0,
            processed_pages=0,
            pending_pages=1,
            model="Qwen-MT-Plus",
            model_key="qwen-mt-plus",
            model_id="qwen-mt-plus",
            provider="qwen_mt",
            translation_model_label="Qwen-MT-Plus",
            translation_model_id="qwen-mt-plus",
            companion_model_label="Qwen-Plus",
            companion_model_id="qwen-plus",
            task={"kind": "continuous", "label": "连续翻译"},
        )

        status = self.client.get(f"/translate_status?doc_id={doc_id}").get_json()
        html = self.client.get(f"/reading?bp=1&doc_id={doc_id}").get_data(as_text=True)

        self.assertEqual(status["translation_model_label"], "Qwen-MT-Plus")
        self.assertEqual(status["translation_model_id"], "qwen-mt-plus")
        self.assertEqual(status["companion_model_label"], "Qwen-Plus")
        self.assertEqual(status["companion_model_id"], "qwen-plus")
        self.assertIn('"translation_model_label": "Qwen-MT-Plus"', html)
        self.assertIn('"companion_model_label": "Qwen-Plus"', html)

    def test_settings_page_separates_translation_and_visual_model_options(self):
        doc_id = create_doc("settings-models.pdf")

        resp = self.client.get(f"/settings?doc_id={doc_id}")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Qwen-MT (DashScope)", html)
        self.assertIn("Qwen-VL-Plus", html)
        visual_provider_start = html.index('id="visualModelProvider"')
        visual_provider_end = html.index("</select>", visual_provider_start)
        visual_provider_html = html[visual_provider_start:visual_provider_end]
        self.assertNotIn('value="qwen_mt"', visual_provider_html)

    def test_save_manual_original_updates_reading(self):
        doc_id = create_doc("manual-original.pdf")
        save_pages_to_disk([{
            "bookPage": 22,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 22",
            "footnotes": "",
            "textSource": "ocr",
        }], "manual-original.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 22,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "OCR 段落",
                "translation": "译文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "22",
                "_status": "done",
                "_error": "",
            }],
            "pages": "22",
        }], "Manual Original", 0, doc_id)

        read_before = self.client.get(f"/reading?bp=22&doc_id={doc_id}").get_data(as_text=True)
        resp = self._post_json(
            "/save_manual_original",
            query_string={"doc_id": doc_id},
            json={
                "bp": 22,
                "segment_index": 0,
                "original": "人工修订 OCR 段落",
            },
        )
        payload = resp.get_json()
        read_html = self.client.get(f"/reading?bp=22&doc_id={doc_id}").get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["segment"]["original"], "人工修订 OCR 段落")
        self.assertEqual(payload["segment"].get("_original_source"), "manual")
        self.assertIn("编辑本页段落", read_before)
        self.assertIn("人工修订 OCR 段落", read_html)
        self.assertNotIn(">OCR 段落</div>", read_html)

    def test_reading_page_has_history_button_and_usage_manual_metrics(self):
        doc_id = create_doc("history-btn.pdf")
        save_pages_to_disk([{
            "bookPage": 16,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 16",
            "footnotes": "",
            "textSource": "ocr",
        }], "history-btn.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 16,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Paragraph A",
                "translation": "机器译文 A",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "16",
                "_status": "done",
                "_error": "",
            }],
            "pages": "16",
        }], "History Btn", 0, doc_id)

        read_html = self.client.get(f"/reading?bp=16&doc_id={doc_id}").get_data(as_text=True)
        self.assertIn('id="translationSessionCard"', read_html)
        self.assertIn('id="pageEditorModal"', read_html)
        self.assertIn("编辑本页段落", read_html)
        self.assertNotIn("查看历史", read_html)
        self.assertNotIn('id="translateUsagePanel"', read_html)
        self.assertNotIn('id="usageBtn"', read_html)

    def test_save_manual_revision_conflict_returns_409(self):
        doc_id = create_doc("manual-revision-conflict.pdf")
        save_pages_to_disk([{
            "bookPage": 8,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 8",
            "footnotes": "",
            "textSource": "ocr",
        }], "manual-revision-conflict.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 8,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Paragraph B",
                "translation": "机器译文 B",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "8",
                "_status": "done",
                "_error": "",
            }],
            "pages": "8",
        }], "Manual Revision Conflict", 0, doc_id)

        first = self._post_json(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={
                "bp": 8,
                "segment_index": 0,
                "translation": "人工修订 B1",
            },
        ).get_json()
        stale_base = int(first["segment"]["updated_at"]) - 1
        second = self._post_json(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={
                "bp": 8,
                "segment_index": 0,
                "translation": "人工修订 B2",
                "base_updated_at": stale_base,
            },
        )

        self.assertEqual(second.status_code, 409)
        self.assertIn("冲突", second.get_json()["error"])

    def test_doc_scoped_glossary_isolated_between_documents(self):
        doc_a = create_doc("glossary-a.pdf")
        doc_b = create_doc("glossary-b.pdf")

        config.set_glossary([["raison", "理性"]], doc_id=doc_a)
        config.set_glossary([["pouvoir", "权力"]], doc_id=doc_b)

        self.assertEqual(config.get_glossary(doc_a), [["raison", "理性"]])
        self.assertEqual(config.get_glossary(doc_b), [["pouvoir", "权力"]])

    def test_fetch_next_uses_doc_scoped_glossary(self):
        doc_a = create_doc("glossary-fetch-a.pdf")
        doc_b = create_doc("glossary-fetch-b.pdf")
        set_current_doc(doc_b)
        config.set_glossary([["raison", "理性"]], doc_id=doc_a)
        config.set_glossary([["pouvoir", "权力"]], doc_id=doc_b)

        save_pages_to_disk([
            {
                "bookPage": 1,
                "fileIdx": 0,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 1",
                "footnotes": "",
                "textSource": "ocr",
            },
            {
                "bookPage": 2,
                "fileIdx": 1,
                "imgW": 1000,
                "imgH": 1600,
                "markdown": "Page 2",
                "footnotes": "",
                "textSource": "ocr",
            },
        ], "glossary-fetch-a.pdf", doc_a)
        save_entries_to_disk([{
            "_pageBP": 1,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Page 1",
                "translation": "翻译 1",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "1",
            }],
            "pages": "1",
        }], "Glossary Fetch A", 0, doc_a)

        with (
            patch.object(storage, "get_translate_args", return_value={"model_id": "fake", "api_key": "fake-key", "provider": "qwen"}),
            patch.object(tasks, "translate_page", return_value={
                "_pageBP": 2,
                "_model": "sonnet",
                "_page_entries": [{
                    "original": "Page 2",
                    "translation": "翻译 2",
                    "footnotes": "",
                    "footnotes_translation": "",
                    "heading_level": 0,
                    "pages": "2",
                }],
                "pages": "2",
            }) as mock_translate,
        ):
            resp = self._post("/fetch_next", data={"doc_id": doc_a})

        self.assertEqual(resp.status_code, 302)
        used_glossary = mock_translate.call_args[0][4]
        self.assertEqual(used_glossary, [["raison", "理性"]])

    def test_translate_api_usage_data_includes_manual_revision_count(self):
        doc_id = create_doc("usage-manual-revision.pdf")
        save_pages_to_disk([{
            "bookPage": 3,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 3",
            "footnotes": "",
            "textSource": "ocr",
        }], "usage-manual-revision.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 3,
            "_model": "sonnet",
            "_usage": {"request_count": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "_page_entries": [{
                "original": "Paragraph C",
                "translation": "机器译文 C",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "3",
                "_status": "done",
                "_error": "",
            }],
            "pages": "3",
        }], "Usage Manual Revision", 0, doc_id)

        self._post_json(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={
                "bp": 3,
                "segment_index": 0,
                "translation": "人工修订 C",
            },
        )
        usage = self.client.get(f"/translate_api_usage_data?doc_id={doc_id}").get_json()

        self.assertEqual(usage["total_manual_revisions"], 1)
        self.assertEqual(usage["pages"][0]["manual_revision_count"], 1)

    def _setup_doc_with_manual_revision(self, doc_id_name):
        """Helper: create doc, page, entry, and one manual revision. Returns (doc_id, bp=10)."""
        doc_id = create_doc(f"{doc_id_name}.pdf")
        save_pages_to_disk([{
            "bookPage": 10,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 10",
            "footnotes": "",
            "textSource": "ocr",
        }], f"{doc_id_name}.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 10,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Original",
                "translation": "机器译文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "10",
                "_status": "done",
                "_error": "",
            }],
            "pages": "10",
        }], doc_id_name, 0, doc_id)
        resp = self._post_json(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={"bp": 10, "segment_index": 0, "translation": "人工修订文本"},
        )
        self.assertEqual(resp.status_code, 200)
        return doc_id

    def test_segment_history_api_returns_previous_state(self):
        doc_id = self._setup_doc_with_manual_revision("history-api-test")
        resp = self.client.get(
            f"/segment_history?doc_id={doc_id}&bp=10&segment_index=0"
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["revisions"]), 1)
        # The history entry should hold the model translation before manual revision
        self.assertEqual(payload["revisions"][0]["translation_text"], "机器译文")
        self.assertEqual(payload["revisions"][0]["revision_source"], "model")

    def test_check_retranslate_warnings_returns_manual_count(self):
        doc_id = self._setup_doc_with_manual_revision("retranslate-warn-test")
        resp = self.client.get(
            f"/check_retranslate_warnings?doc_id={doc_id}&bp=10"
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["manual_count"], 1)

    def test_conflict_409_returns_server_segment(self):
        doc_id = create_doc("conflict-server-seg.pdf")
        save_pages_to_disk([{
            "bookPage": 5,
            "fileIdx": 0,
            "imgW": 1000,
            "imgH": 1600,
            "markdown": "Page 5",
            "footnotes": "",
            "textSource": "ocr",
        }], "conflict-server-seg.pdf", doc_id)
        save_entries_to_disk([{
            "_pageBP": 5,
            "_model": "sonnet",
            "_page_entries": [{
                "original": "Para",
                "translation": "机器译文 C",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "5",
                "_status": "done",
                "_error": "",
            }],
            "pages": "5",
        }], "Conflict Server Seg", 0, doc_id)

        first = self._post_json(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={"bp": 5, "segment_index": 0, "translation": "人工修订 C1"},
        ).get_json()

        stale_base = int(first["segment"]["updated_at"]) - 1
        second = self._post_json(
            "/save_manual_revision",
            query_string={"doc_id": doc_id},
            json={
                "bp": 5,
                "segment_index": 0,
                "translation": "人工修订 C2",
                "base_updated_at": stale_base,
            },
        )
        payload = second.get_json()

        self.assertEqual(second.status_code, 409)
        self.assertIn("冲突", payload["error"])
        self.assertIsNotNone(payload.get("server_segment"))
        self.assertEqual(payload["server_segment"]["translation"], "人工修订 C1")

    def test_retranslate_after_manual_revision_logs_history(self):
        doc_id = self._setup_doc_with_manual_revision("retranslate-history-test")

        # Single-page retranslate mirrors the /retranslate route: uses save_entry_to_disk
        from persistence.storage import save_entry_to_disk
        save_entry_to_disk({
            "_pageBP": 10,
            "_model": "qwen",
            "_page_entries": [{
                "original": "Original",
                "translation": "新机器译文",
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": 0,
                "pages": "10",
                "_status": "done",
                "_error": "",
            }],
            "pages": "10",
        }, "retranslate-history-test", doc_id)

        # Current effective translation should be the new model text
        repo = SQLiteRepository()
        page = repo.get_effective_translation_page(doc_id, 10)
        self.assertEqual(page["_page_entries"][0]["translation"], "新机器译文")

        # History should contain the old manual revision snapshotted before retranslate
        revisions = repo.list_segment_revisions(doc_id, 10, 0)
        manual_texts = [r.get("manual_translation_text") for r in revisions]
        self.assertIn("人工修订文本", manual_texts)

    def test_build_toc_reading_items_supports_file_idx_and_book_page(self):
        page_lookup = {5: {"bookPage": 5}, 7: {"bookPage": 7}}

        items_with_file_idx = _build_toc_reading_items(
            [{"title": "自动目录", "depth": 0, "file_idx": 4}],
            0,
            page_lookup,
        )
        self.assertEqual(items_with_file_idx[0]["book_page"], 5)
        self.assertEqual(items_with_file_idx[0]["target_page"], 5)

        items_with_book_page = _build_toc_reading_items(
            [{"title": "用户目录", "depth": 0, "book_page": 6}],
            1,
            page_lookup,
        )
        self.assertEqual(items_with_book_page[0]["book_page"], 6)
        self.assertEqual(items_with_book_page[0]["target_page"], 7)

        item_missing_lookup = _build_toc_reading_items(
            [{"title": "缺失页", "depth": 0, "file_idx": 98}],
            0,
            page_lookup,
        )
        self.assertIsNone(item_missing_lookup[0]["target_page"])


if __name__ == "__main__":
    unittest.main()

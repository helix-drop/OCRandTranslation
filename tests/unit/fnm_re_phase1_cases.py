#!/usr/bin/env python3
"""FNM_RE 第一阶段回归测试。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from pipeline.visual_toc.organization import _annotate_visual_toc_organization, _apply_printed_page_lookup
from pipeline.visual_toc.manual_inputs import _extract_manual_toc_outline_nodes_from_pdf_text
from FNM_RE.app.pipeline import build_phase1_structure
from FNM_RE.stages.chapter_skeleton.heading_candidates import _collect_heading_candidate_rows, _legacy_page_rows
from FNM_RE.stages.chapter_skeleton.toc_semantics import (
    _collect_visual_toc_rows,
    _sanitize_visual_toc_semantic_rows,
    _visual_toc_level,
)
from FNM_RE.stages.page_partition import build_page_partitions


REPO_ROOT = Path("/Users/hao/OCRandTranslation")
TEST_EXAMPLE_DIR = REPO_ROOT / "test_example"
_SAMPLE_DOC_IDS = {
    "Biopolitics": "0d285c0800db",
    "Germany_Madness": "67356d1f7d9a",
    "post-revolutionary": "7ba9bca783fd",
    "Goldstein": "7ba9bca783fd",
    "Heidegger_en_France": "a5d9a08d6871",
    "Mad_Act": "bd05138cd773",
    "Napoleon": "5df1d3d7f9c1",
    "Neuropsychoanalysis_in_Practice": "e7f8a1b6c2d3",
    "Neuropsychoanalysis_Introduction": "a3c9e1f7b284",
}


def _load_pages(doc_dir: str) -> list[dict]:
    raw_path = TEST_EXAMPLE_DIR / doc_dir / "raw_pages.json"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    return list(payload.get("pages") or [])


def _load_auto_visual_toc(doc_dir: str) -> list[dict]:
    toc_path = TEST_EXAMPLE_DIR / doc_dir / "auto_visual_toc.json"
    if not toc_path.exists():
        doc_id = _SAMPLE_DOC_IDS.get(doc_dir)
        return _load_doc_auto_visual_toc_items(doc_id) if doc_id else []
    payload = json.loads(toc_path.read_text(encoding="utf-8"))
    return list(payload.get("items") or [])


def _load_auto_visual_toc_bundle(doc_dir: str) -> dict:
    toc_path = TEST_EXAMPLE_DIR / doc_dir / "auto_visual_toc.json"
    if not toc_path.exists():
        doc_id = _SAMPLE_DOC_IDS.get(doc_dir)
        return _load_doc_auto_visual_toc_bundle(doc_id) if doc_id else {}
    payload = json.loads(toc_path.read_text(encoding="utf-8"))
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _load_doc_auto_visual_toc_bundle(doc_id: str) -> dict:
    toc_path = REPO_ROOT / "local_data" / "user_data" / "data" / "documents" / doc_id / "auto_visual_toc_bundle.json"
    if not toc_path.exists():
        return {}
    payload = json.loads(toc_path.read_text(encoding="utf-8"))
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _load_doc_auto_visual_toc_items(doc_id: str) -> list[dict]:
    return list(_load_doc_auto_visual_toc_bundle(doc_id).get("items") or [])


def _load_pdf_path(doc_dir: str) -> str:
    matches = sorted((TEST_EXAMPLE_DIR / doc_dir).glob("*.pdf"))
    return str(matches[0]) if matches else ""


def _make_page(page_no: int, *, markdown: str, block_label: str = "", block_text: str = "") -> dict:
    blocks: list[dict] = []
    if block_label and block_text:
        blocks.append(
            {
                "block_label": block_label,
                "block_content": block_text,
                "block_bbox": [0, 10, 100, 80],
                "block_order": 1,
            }
        )
    return {
        "bookPage": page_no,
        "fileIdx": page_no - 1,
        "markdown": markdown,
        "footnotes": "",
        "textSource": "ocr",
        "prunedResult": {
            "height": 1200,
            "parsing_res_list": blocks,
        },
    }


def _load_nip_manual_outline_toc() -> list[dict]:
    pages = _load_pages("Neuropsychoanalysis_in_Practice")
    printed_page_lookup = {
        int(page.get("printPage") or 0): int(page.get("fileIdx") or 0)
        for page in pages
        if int(page.get("printPage") or 0) > 0
    }
    outline_items = _extract_manual_toc_outline_nodes_from_pdf_text(
        str(TEST_EXAMPLE_DIR / "Neuropsychoanalysis_in_Practice" / "目录.pdf")
    )
    outline_items = _apply_printed_page_lookup(outline_items, printed_page_lookup)
    outline_items, _ = _annotate_visual_toc_organization(outline_items)
    return outline_items


class FnmRePhase1Test(unittest.TestCase):
    def test_visual_toc_level_uses_role_hint_and_semantic_depth(self):
        self.assertEqual(_visual_toc_level({"role_hint": "container", "depth": 1}), 1)
        self.assertEqual(_visual_toc_level({"role_hint": "endnotes", "depth": 1}), 1)
        self.assertEqual(_visual_toc_level({"role_hint": "chapter", "depth": 0}), 2)
        self.assertEqual(_visual_toc_level({"role_hint": "section", "depth": 2}), 3)
        self.assertEqual(_visual_toc_level({"role_hint": "section", "depth": 3}), 4)
        self.assertEqual(_visual_toc_level({"role_hint": "back_matter", "depth": 0}), 0)

    def test_page_partition_marks_rear_toc_tail_and_author_blurb_as_other(self):
        pages = [_make_page(page_no, markdown=f"正文第 {page_no} 页。") for page_no in range(1, 101)]
        pages[97] = _make_page(
            98,
            markdown=(
                "## Préambule\n\n"
                "I. 1793 ou comment perdre la tête 45\n"
                "« Une invention utile dans le genre funeste » 47\n"
                "Un médecin au chevet du corps de l'État 56\n"
                "Les « événements de la Révolution » 81\n"
                "Spectres de la guillotine 93\n"
                "III. L'homme qui se prenait pour Napoléon 163\n"
                "1848 ou la peste démocratique 246\n"
                "V. La raison insurgée 298\n"
                "Postambule 333\n"
                "Bibliographie 363\n"
                "Index 375\n"
            ),
            block_label="paragraph_title",
            block_text="Préambule",
        )
        pages[99] = {
            "bookPage": 100,
            "fileIdx": 99,
            "markdown": (
                "# Laure Murat\n\n"
                "# L'HOMME QUI SE PRENAIT POUR NAPOLÉON\n\n"
                "Pour une histoire politique de la folie.\n\n"
                "Au lendemain du retour des cendres de Napoléon I er, l'auteur raconte...\n"
                "Encore un paragraphe long sur le livre.\n"
            ),
            "footnotes": "",
            "textSource": "ocr",
            "prunedResult": {
                "height": 1200,
                "parsing_res_list": [
                    {
                        "block_label": "doc_title",
                        "block_content": "Laure Murat",
                        "block_bbox": [0, 10, 100, 80],
                        "block_order": 1,
                    },
                    {
                        "block_label": "doc_title",
                        "block_content": "L'HOMME QUI SE PRENAIT POUR NAPOLÉON",
                        "block_bbox": [0, 90, 500, 160],
                        "block_order": 2,
                    },
                ],
            },
        }

        partitions = build_page_partitions(pages)
        by_no = {item.page_no: item for item in partitions}

        self.assertEqual(by_no[98].page_role, "other")
        self.assertEqual(by_no[100].page_role, "other")

    def test_page_partition_marks_note_continuation_as_note(self):
        pages = [
            _make_page(
                348,
                markdown=(
                    "Abbreviations\n\n"
                    "AN Archives Nationales, Paris\n\n"
                    "BN Bibliothèque nationale de France, Paris\n\n"
                    "## Introduction\n\n"
                    "1. First note starts on this page.\n\n"
                    "2. Second note also starts on this page.\n"
                ),
            )
        ]

        partitions = build_page_partitions(pages)
        self.assertEqual(len(partitions), 1)
        self.assertEqual(partitions[0].page_role, "note")
        self.assertEqual(partitions[0].reason, "note_continuation")

    def test_endnotes_start_hint_stops_before_rear_back_matter_tail(self):
        pages = [_make_page(page_no, markdown=f"Body page {page_no}.") for page_no in range(1, 101)]
        pages[87] = _make_page(88, markdown="1. First note.\n\n2. Second note.")
        pages[88] = _make_page(89, markdown="3. Third note.\n\n4. Fourth note.")
        pages[89] = _make_page(90, markdown="5. Fifth note.\n\n6. Sixth note.")
        pages[90] = _make_page(91, markdown="")
        pages[91] = _make_page(
            92,
            markdown=(
                "# Index\n\n"
                "Alpha, 1, 2\n"
                "Beta, 3, 4\n"
            ),
        )

        partitions = build_page_partitions(pages, endnotes_start_page=88)
        by_no = {item.page_no: item for item in partitions}

        self.assertEqual(by_no[88].page_role, "note")
        self.assertEqual(by_no[90].page_role, "note")
        self.assertNotEqual(by_no[91].page_role, "note")
        self.assertNotEqual(by_no[92].page_role, "note")

    def test_page_partition_keeps_illustration_list_continuation_as_other(self):
        pages = [_make_page(page_no, markdown=f"正文第 {page_no} 页。") for page_no in range(1, 41)]
        pages[35] = _make_page(
            36,
            markdown=(
                "# Liste des illustrations\n"
                "1. Gravure. Musée Carnavalet. © Musée Carnavalet\n"
                "2. Eau-forte. Bibliothèque nationale."
            ),
        )
        pages[36] = _make_page(
            37,
            markdown=(
                "10. Huile sur toile. Musée du Louvre. © RMN\n"
                "11. Lithographie. Bibliothèque nationale de France."
            ),
        )

        partitions = build_page_partitions(pages)
        by_no = {item.page_no: item for item in partitions}

        self.assertEqual(by_no[36].page_role, "other")
        self.assertEqual(by_no[37].page_role, "other")

    def test_page_partition_keeps_bibliography_remarks_tail_as_other(self):
        pages = [_make_page(page_no, markdown=f"正文第 {page_no} 页。") for page_no in range(1, 61)]
        pages[52] = _make_page(
            53,
            markdown=(
                "# Bibliography\n\n"
                "Des précisions préalables s'imposent quant à l'organisation de cette bibliographie."
            ),
        )
        pages[53] = _make_page(
            54,
            markdown=(
                "« Lettre sur l'humanisme », trad. Roger Munier, Cahiers du Sud, 1953, pp. 385-406.\n"
                "« Que signifie penser ? », trad. Annelise Botond, Mercure de France, 1953, pp. 393-407.\n"
                "« Principes de la pensée », trad. François Fédier, Arguments, 1960, pp. 27-33."
            ),
        )
        pages[54] = _make_page(
            55,
            markdown=(
                "2. Signalons une traduction sans date, par Gérard Granel, texte bilingue, Paris, Belin, 2001.\n"
                "3. La traduction du cours sur le Sophiste doit paraître en 2001 chez Gallimard.\n"
                "4. « Le travail de recherche de Wilhelm Dilthey », trad. J.-C. Gens, Paris, Vrin, 2003."
            ),
        )

        partitions = build_page_partitions(pages)
        by_no = {item.page_no: item for item in partitions}

        self.assertEqual(by_no[54].page_role, "other")
        self.assertEqual(by_no[55].page_role, "other")

    def test_page_partition_recovers_early_front_matter_continuation(self):
        pages = [
            _make_page(
                1,
                markdown=(
                    "Copyright 2024 Example Press\n"
                    "All rights reserved.\n"
                    "Printed in France.\n"
                    "ISBN 978-0-00-000000-0\n"
                ),
            ),
            _make_page(
                2,
                markdown=(
                    "Abbreviations\n\n"
                    "AN Archives Nationales, Paris\n"
                    "BN Bibliothèque nationale de France, Paris\n"
                    "CN Centre National des Archives\n"
                ),
            ),
            _make_page(
                3,
                markdown=(
                    "# Chapter One\n\n"
                    "This chapter starts with long prose content and should stay body.\n"
                ),
                block_label="doc_title",
                block_text="Chapter One",
            ),
        ]
        partitions = build_page_partitions(pages)
        by_no = {item.page_no: item for item in partitions}

        self.assertEqual(by_no[2].page_role, "front_matter")
        self.assertEqual(by_no[2].reason, "front_matter_continuation")
        self.assertEqual(by_no[3].page_role, "body")

    def test_visual_toc_chapter_boundary_stops_before_back_matter_start(self):
        pages = [_make_page(page_no, markdown=f"Page {page_no}") for page_no in range(1, 11)]
        pages[7] = _make_page(8, markdown="# Bibliography\n\nRef")
        pages[8] = _make_page(9, markdown="# Index\n\nEntry")
        toc_items = [
            {"item_id": "toc-ep", "title": "Epilogue", "level": 1, "target_pdf_page": 5},
            {"item_id": "toc-bib", "title": "Bibliography", "level": 1, "target_pdf_page": 8},
            {"item_id": "toc-index", "title": "Index", "level": 1, "target_pdf_page": 9},
        ]

        structure = build_phase1_structure(pages, toc_items=toc_items, toc_offset=0)

        self.assertEqual([chapter.title for chapter in structure.chapters], ["Epilogue"])
        self.assertEqual(structure.chapters[0].start_page, 5)
        self.assertEqual(structure.chapters[0].end_page, 7)
        self.assertEqual(structure.summary.toc_role_summary.get("back_matter"), 2)

    def test_biopolitics_exports_lectures_plus_post_body_titles_without_container_as_chapter(self):
        structure = build_phase1_structure(
            _load_pages("Biopolitics"),
            toc_items=_load_auto_visual_toc("Biopolitics"),
            toc_offset=0,
        )
        chapter_titles = [chapter.title for chapter in structure.chapters]

        self.assertEqual(len(chapter_titles), 14)
        self.assertNotIn("COURS, ANNÉE 1978-1979", chapter_titles)
        self.assertEqual(chapter_titles[12:], ["RÉSUMÉ DU COURS", "SITUATION DES COURS"])
        self.assertEqual(structure.summary.container_titles, ["COURS, ANNÉE 1978-1979", "INDICES"])
        self.assertEqual(structure.summary.post_body_titles, ["RÉSUMÉ DU COURS", "SITUATION DES COURS"])

    def test_phase1_summary_accepts_visual_toc_endnotes_summary(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody",
                block_label="doc_title",
                block_text="Chapter One",
            )
        ]
        structure = build_phase1_structure(
            pages,
            visual_toc_bundle={
                "endnotes_summary": {
                    "present": True,
                    "container_title": "Notes",
                    "container_printed_page": 259,
                    "container_visual_order": 21,
                    "has_chapter_keyed_subentries_in_toc": False,
                    "subentry_pattern": None,
                }
            },
        )

        self.assertTrue(structure.summary.visual_toc_endnotes_summary["present"])
        self.assertEqual(structure.summary.visual_toc_endnotes_summary["container_title"], "Notes")

    def test_phase1_summary_defaults_visual_toc_endnotes_summary_to_empty(self):
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody",
                block_label="doc_title",
                block_text="Chapter One",
            )
        ]
        structure = build_phase1_structure(pages)
        self.assertEqual(structure.summary.visual_toc_endnotes_summary, {})

    def test_phase1_semantic_depth_keeps_endnotes_out_of_chapter_tree(self):
        pages = [
            _make_page(1, markdown="# Chapter One\nBody", block_label="doc_title", block_text="Chapter One"),
            _make_page(2, markdown="## Section One\nBody", block_label="paragraph_title", block_text="Section One"),
            _make_page(3, markdown="## Notes\n1. Note text."),
        ]
        toc_items = [
            {"item_id": "toc-part", "title": "Part I", "depth": 1, "role_hint": "container"},
            {
                "item_id": "toc-ch-1",
                "title": "Chapter One",
                "depth": 0,
                "role_hint": "chapter",
                "parent_title": "Part I",
                "target_pdf_page": 1,
            },
            {
                "item_id": "toc-sec-1",
                "title": "Section One",
                "depth": 2,
                "role_hint": "section",
                "parent_title": "Chapter One",
                "target_pdf_page": 2,
            },
            {
                "item_id": "toc-notes",
                "title": "Notes",
                "depth": 1,
                "role_hint": "endnotes",
                "target_pdf_page": 3,
            },
            {
                "item_id": "toc-notes-1",
                "title": "Notes to Chapter One",
                "depth": 2,
                "role_hint": "section",
                "parent_title": "Notes",
                "target_pdf_page": 3,
            },
        ]

        structure = build_phase1_structure(pages, toc_items=toc_items, toc_offset=0)

        self.assertEqual([chapter.title for chapter in structure.chapters], ["Chapter One"])
        self.assertEqual(structure.chapters[0].pages, [1, 2])
        self.assertNotIn("Notes to Chapter One", [row.title for row in structure.section_heads])
        self.assertEqual(int(structure.summary.toc_role_summary.get("endnotes") or 0), 1)

    def test_fallback_does_not_promote_sentence_like_paragraph_title_to_chapter(self):
        long_sentence = "This is a very long sentence like a subsection heading that should not become a chapter"
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\n\nBody paragraph for chapter one.",
                block_label="doc_title",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown=f"# {long_sentence}\n\nBody line.",
                block_label="paragraph_title",
                block_text=long_sentence,
            ),
            _make_page(3, markdown="Continuation page."),
            _make_page(
                4,
                markdown="# Chapter Two\n\nBody paragraph for chapter two.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
            _make_page(5, markdown="Continuation page."),
        ]

        structure = build_phase1_structure(pages)
        chapter_titles = [chapter.title for chapter in structure.chapters]

        self.assertIn("Chapter One", chapter_titles)
        self.assertIn("Chapter Two", chapter_titles)
        self.assertNotIn(long_sentence, chapter_titles)
        suppressed = [
            candidate
            for candidate in structure.heading_candidates
            if long_sentence.lower() in candidate.text.lower()
        ]
        self.assertTrue(suppressed)
        self.assertTrue(suppressed[0].suppressed_as_chapter)
        self.assertTrue(bool(suppressed[0].reject_reason))

    def test_section_heads_keep_suppressed_candidates_with_reject_reason(self):
        long_sentence = "This is a very long sentence like a subsection heading that should not become a chapter"
        pages = [
            _make_page(
                1,
                markdown="# Chapter One\n\nBody paragraph for chapter one.",
                block_label="doc_title",
                block_text="Chapter One",
            ),
            _make_page(
                2,
                markdown=f"# {long_sentence}\n\nBody line.",
                block_label="paragraph_title",
                block_text=long_sentence,
            ),
            _make_page(3, markdown="Continuation page."),
            _make_page(
                4,
                markdown="# Chapter Two\n\nBody paragraph for chapter two.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]

        structure = build_phase1_structure(pages)
        section_titles = [item.title for item in structure.section_heads]
        self.assertIn(long_sentence, section_titles)
        self.assertGreaterEqual(structure.summary.heading_review_summary.get("suppressed_candidate_count", 0), 1)

    def test_heading_graph_residual_provisional_does_not_block_phase1(self):
        pages = [
            _make_page(1, markdown="Page one body."),
            _make_page(2, markdown="Page two body."),
            _make_page(3, markdown="Page three body."),
        ]
        toc_items = [
            {"item_id": "toc-ch1", "title": "Chapter One", "level": 1, "target_pdf_page": 2},
        ]

        structure = build_phase1_structure(pages, toc_items=toc_items, toc_offset=0)

        self.assertTrue(structure.chapters)
        self.assertEqual(structure.chapters[0].title, "Chapter One")
        self.assertEqual(structure.summary.heading_graph_summary.get("provisional_anchor_count"), 1)
        self.assertEqual(structure.summary.heading_graph_summary.get("residual_provisional_count"), 1)
        self.assertEqual(
            structure.summary.heading_graph_summary.get("residual_provisional_titles_preview"),
            ["Chapter One"],
        )
        self.assertNotIn("heading_graph_incomplete", structure.summary.toc_semantic_blocking_reasons)
        self.assertNotIn("heading_graph_boundary_conflict", structure.summary.toc_semantic_blocking_reasons)

    def test_mad_act_keeps_part_containers_and_exports_appendices(self):
        structure = build_phase1_structure(
            _load_pages("Mad_Act"),
            toc_items=_load_auto_visual_toc("Mad_Act"),
            toc_offset=0,
            pdf_path=_load_pdf_path("Mad_Act"),
            visual_toc_bundle=_load_auto_visual_toc_bundle("Mad_Act"),
        )
        chapter_titles = [chapter.title for chapter in structure.chapters]

        self.assertIn("Appendices", chapter_titles)
        self.assertTrue(any(title.startswith("Part One") for title in structure.summary.container_titles))
        self.assertIn("Appendices", structure.summary.post_body_titles)
        self.assertLess(chapter_titles.index("Punish, but how?"), chapter_titles.index("Life trials"))
        self.assertGreaterEqual(
            int(structure.summary.heading_graph_summary.get("resolved_anchor_count") or 0)
            + int(structure.summary.heading_graph_summary.get("provisional_anchor_count") or 0),
            len(chapter_titles),
        )
        self.assertGreater(int(structure.summary.heading_graph_summary.get("section_node_count") or 0), 0)
        self.assertGreaterEqual(int(structure.summary.heading_graph_summary.get("optimized_anchor_count") or 0), 1)
        self.assertLessEqual(int(structure.summary.heading_graph_summary.get("residual_provisional_count") or 0), 11)

    def test_napoleon_last_chapter_stops_before_rear_back_matter(self):
        structure = build_phase1_structure(
            _load_pages("Napoleon"),
            toc_items=_load_auto_visual_toc("Napoleon"),
            toc_offset=0,
        )
        last_exported_chapter = max(structure.chapters, key=lambda chapter: chapter.end_page)
        rear_back_matter_page = min(
            page.page_no
            for page in structure.pages
            if page.page_no >= last_exported_chapter.start_page
            and page.page_role == "other"
            and page.reason in {
                "appendix",
                "bibliography",
                "index",
                "illustrations",
                "rear_toc_tail",
                "rear_author_blurb",
                "rear_sparse_other",
            }
        )

        self.assertLess(last_exported_chapter.end_page, rear_back_matter_page)
        self.assertNotIn(rear_back_matter_page, last_exported_chapter.pages)

    def test_napoleon_exported_roman_root_is_not_left_in_container_titles(self):
        structure = build_phase1_structure(
            _load_pages("Napoleon"),
            toc_items=_load_auto_visual_toc("Napoleon"),
            toc_offset=0,
            pdf_path=_load_pdf_path("Napoleon"),
            visual_toc_bundle=_load_auto_visual_toc_bundle("Napoleon"),
        )

        exported_titles = [str(chapter.title or "") for chapter in structure.chapters]
        container_titles = [str(title or "") for title in structure.summary.container_titles]

        self.assertTrue(any(title.startswith("II. L’asile, prison politique") for title in exported_titles))
        self.assertFalse(any(title.startswith("II. L’asile, prison politique") for title in container_titles))

    def test_nip_manual_outline_keeps_part_i_to_iv_container_semantics(self):
        structure = build_phase1_structure(
            _load_pages("Neuropsychoanalysis_in_Practice"),
            toc_items=_load_nip_manual_outline_toc(),
            toc_offset=0,
        )
        self.assertCountEqual(
            structure.summary.container_titles,
            [
                "Part I Conceptual Equipment",
                "Part II Neural Equipment",
                "Part III Mental Equipment",
                "Part IV Disordered Equipment",
            ],
        )

    def test_phase1_smoke_for_remaining_sample_books_returns_non_empty_chapters(self):
        docs = [
            "Germany_Madness",
            "post-revolutionary",
            "Heidegger_en_France",
            "Neuropsychoanalysis_Introduction",
        ]
        for doc in docs:
            with self.subTest(doc=doc):
                structure = build_phase1_structure(
                    _load_pages(doc),
                    toc_items=_load_auto_visual_toc(doc),
                    toc_offset=0,
                )
                self.assertTrue(structure.chapters)

    def test_goldstein_phase1_preserves_endnotes_role_in_visual_toc(self):
        structure = build_phase1_structure(
            _load_pages("post-revolutionary"),
            toc_items=_load_auto_visual_toc("post-revolutionary"),
            toc_offset=0,
            pdf_path=_load_pdf_path("post-revolutionary"),
            visual_toc_bundle=_load_auto_visual_toc_bundle("post-revolutionary"),
        )

        self.assertEqual(int(structure.summary.toc_role_summary.get("endnotes") or 0), 1)
        self.assertEqual(
            dict(structure.summary.visual_toc_endnotes_summary or {}).get("container_title"),
            "Notes",
        )
        self.assertNotIn("Notes", [head.title for head in structure.section_heads])

    def test_phase1_treats_explicit_part_role_as_container_not_chapter(self):
        part_title = "I THE PROBLEM FOR WHICH PSYCHOLOGY FURNISHED A SOLUTION"
        chapter_title = "1 Is There a Self in This Mental Apparatus?"
        pages = [
            _make_page(
                1,
                markdown=f"# {part_title}\n",
                block_label="doc_title",
                block_text=part_title,
            ),
            _make_page(
                2,
                markdown=f"# {chapter_title}\n\nBody paragraph.",
                block_label="doc_title",
                block_text=chapter_title,
            ),
            _make_page(3, markdown="Continuation page."),
            _make_page(4, markdown="## Notes\n\n1. Note text."),
        ]
        toc_items = [
            {
                "item_id": "toc-part-1",
                "title": part_title,
                "depth": 0,
                "role_hint": "part",
                "target_pdf_page": 1,
            },
            {
                "item_id": "toc-ch-1",
                "title": chapter_title,
                "depth": 1,
                "role_hint": "chapter",
                "parent_title": part_title,
                "target_pdf_page": 2,
            },
            {
                "item_id": "toc-notes",
                "title": "Notes",
                "depth": 0,
                "role_hint": "endnotes",
                "target_pdf_page": 4,
            },
        ]

        structure = build_phase1_structure(
            pages,
            toc_items=toc_items,
            toc_offset=0,
            visual_toc_bundle={
                "endnotes_summary": {
                    "present": True,
                    "container_title": "Notes",
                    "container_printed_page": 331,
                    "container_visual_order": 3,
                    "has_chapter_keyed_subentries_in_toc": False,
                    "subentry_pattern": None,
                }
            },
        )

        self.assertEqual([chapter.title for chapter in structure.chapters], [chapter_title])
        self.assertIn(part_title, structure.summary.container_titles)
        self.assertEqual(int(structure.summary.toc_role_summary.get("container") or 0), 1)
        self.assertEqual(int(structure.summary.toc_role_summary.get("endnotes") or 0), 1)
        self.assertNotIn("toc_role_semantics_invalid", structure.summary.toc_semantic_blocking_reasons)

    def test_neuro_intro_heading_graph_flags_same_page_anchor_conflict(self):
        structure = build_phase1_structure(
            _load_pages("Neuropsychoanalysis_Introduction"),
            toc_items=_load_auto_visual_toc("Neuropsychoanalysis_Introduction"),
            toc_offset=0,
            pdf_path=_load_pdf_path("Neuropsychoanalysis_Introduction"),
        )

        self.assertNotIn("heading_graph_boundary_conflict", structure.summary.toc_semantic_blocking_reasons)
        self.assertEqual(
            int(structure.summary.heading_graph_summary.get("toc_body_item_count") or 0),
            9,
        )
        self.assertEqual(
            list(structure.summary.heading_graph_summary.get("boundary_conflict_titles_preview") or []),
            [],
        )

    def test_germany_madness_visual_toc_keeps_all_top_level_chapters(self):
        structure = build_phase1_structure(
            _load_pages("Germany_Madness"),
            toc_items=_load_auto_visual_toc("Germany_Madness"),
            toc_offset=0,
            visual_toc_bundle=_load_auto_visual_toc_bundle("Germany_Madness"),
        )

        self.assertEqual(
            [chapter.title for chapter in structure.chapters],
            [
                "Historical Problems: Sin, St. Vitus, and the Devil",
                "Two Reformers and a World Gone Mad: Luther and Paracelsus",
                "Academic “Psychiatry” and the Rise of Galenic Observation",
                "Witchcraft and the Melancholy Interpretation of the Insanity Defense",
                "Court Fools and Their Folly: Image and Social Reality",
                "Pilgrims in Search of Their Reason",
                "Madness as Helplessness: Two Hospitals in the Age of the Reformations",
                "Epilogue",
            ],
        )
        self.assertNotIn("heading_graph_boundary_conflict", structure.summary.toc_semantic_blocking_reasons)
        self.assertEqual(
            int(structure.summary.heading_graph_summary.get("residual_provisional_count") or 0),
            0,
        )
        self.assertEqual(
            int(structure.summary.toc_alignment_summary.get("exported_chapter_count") or 0),
            8,
        )

    def test_goldstein_visual_toc_filters_composite_root_duplicate(self):
        structure = build_phase1_structure(
            _load_pages("post-revolutionary"),
            toc_items=_load_doc_auto_visual_toc_items("7ba9bca783fd"),
            toc_offset=0,
            pdf_path=_load_pdf_path("post-revolutionary"),
        )

        titles = [chapter.title for chapter in structure.chapters]
        self.assertIn("3 Is There a Self in This Mental Apparatus?", titles)
        self.assertNotIn("II THE POLITICS OF SELFHOOD 3I s There a Self in This Mental Apparatus?", titles)
        self.assertEqual(
            len([chapter for chapter in structure.chapters if chapter.start_page == 120]),
            1,
        )
        self.assertNotIn("heading_graph_boundary_conflict", structure.summary.toc_semantic_blocking_reasons)

    def test_heidegger_visual_toc_demotes_back_matter_subsections(self):
        pages = _load_pages("Heidegger_en_France")
        toc_items = _load_doc_auto_visual_toc_items("a5d9a08d6871")
        partitions = build_page_partitions(pages)
        page_rows = _legacy_page_rows(partitions, pages)
        heading_candidates = _collect_heading_candidate_rows(
            page_rows,
            toc_items=toc_items,
            toc_offset=0,
            pdf_path="",
        )
        rows = _sanitize_visual_toc_semantic_rows(
            _collect_visual_toc_rows(
                page_rows,
                toc_items=toc_items,
                toc_offset=0,
                heading_candidates=heading_candidates,
            )
        )

        role_by_title = {
            str(row.get("title") or ""): str(row.get("role_hint") or "")
            for row in rows
        }
        export_by_title = {
            str(row.get("title") or ""): bool(row.get("export_candidate"))
            for row in rows
        }
        self.assertEqual(
            role_by_title.get(
                "Traductions françaises de Heidegger dans l'ordre chronologique de leur publication"
            ),
            "back_matter",
        )
        self.assertEqual(
            role_by_title.get("des mots clés heideggériens"),
            "back_matter",
        )
        self.assertFalse(
            export_by_title.get(
                "Traductions françaises de Heidegger dans l'ordre chronologique de leur publication",
                True,
            )
        )
        self.assertFalse(
            export_by_title.get(
                "des mots clés heideggériens",
                True,
            )
        )

    def test_neuro_intro_visual_toc_prefers_clean_titles_over_number_noise(self):
        structure = build_phase1_structure(
            _load_pages("Neuropsychoanalysis_Introduction"),
            toc_items=_load_doc_auto_visual_toc_items("a3c9e1f7b284"),
            toc_offset=0,
            pdf_path=_load_pdf_path("Neuropsychoanalysis_Introduction"),
        )

        titles = [chapter.title for chapter in structure.chapters]
        self.assertIn("Introduction", titles)
        self.assertIn("Conclusion", titles)
        self.assertNotIn("7 Introduction", titles)
        self.assertNotIn("1", titles)
        self.assertNotIn("heading_graph_boundary_conflict", structure.summary.toc_semantic_blocking_reasons)

    def test_neuro_intro_sample_clean_visual_toc_exports_all_chapters(self):
        structure = build_phase1_structure(
            _load_pages("Neuropsychoanalysis_Introduction"),
            toc_items=_load_auto_visual_toc("Neuropsychoanalysis_Introduction"),
            toc_offset=0,
            pdf_path=_load_pdf_path("Neuropsychoanalysis_Introduction"),
            visual_toc_bundle=_load_auto_visual_toc_bundle("Neuropsychoanalysis_Introduction"),
        )

        self.assertEqual(
            [chapter.title for chapter in structure.chapters],
            [
                "Introduction",
                "Self and narcissism",
                "Attachment and trauma",
                "Defense mechanisms and dissociation",
                "Cathexis and free energy",
                "Unconscious and conscious",
                "Dreams",
                "Schizophrenia and depression",
                "Conclusion",
            ],
        )
        self.assertNotIn("heading_graph_boundary_conflict", structure.summary.toc_semantic_blocking_reasons)
        self.assertEqual(
            int(structure.summary.toc_alignment_summary.get("exported_chapter_count") or 0),
            9,
        )

    def test_napoleon_heading_graph_resolves_long_french_titles_without_residual_provisional(self):
        structure = build_phase1_structure(
            _load_pages("Napoleon"),
            toc_items=_load_auto_visual_toc("Napoleon"),
            toc_offset=0,
            pdf_path=_load_pdf_path("Napoleon"),
            visual_toc_bundle=_load_auto_visual_toc_bundle("Napoleon"),
        )

        residual_preview = list(structure.summary.heading_graph_summary.get("residual_provisional_titles_preview") or [])
        self.assertEqual(int(structure.summary.heading_graph_summary.get("residual_provisional_count") or 0), 0)
        self.assertNotIn("Les « événements de la Révolution »", residual_preview)
        self.assertNotIn("Le maître de l’Univers", residual_preview)
        self.assertNotIn("1830 ou la maladie de la civilisation", residual_preview)
        self.assertNotIn("Les bégaiements de l’Histoire", residual_preview)

    def test_heidegger_manual_visual_toc_does_not_keep_obvious_garbled_titles(self):
        structure = build_phase1_structure(
            _load_pages("Heidegger_en_France"),
            toc_items=_load_auto_visual_toc("Heidegger_en_France"),
            toc_offset=0,
            visual_toc_bundle=_load_auto_visual_toc_bundle("Heidegger_en_France"),
        )

        residual_preview = list(structure.summary.heading_graph_summary.get("residual_provisional_titles_preview") or [])
        self.assertFalse(any("L'=bellie" in title for title in residual_preview))
        self.assertFalse(any("déplac=ents" in title for title in residual_preview))
        self.assertFalse(any("Epilogue II .................................... r" in title for title in residual_preview))


if __name__ == "__main__":
    unittest.main()

"""章节骨架主编排。"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from document.pdf_extract import extract_pdf_text
from web.toc_support import resolve_toc_item_target_pdf_page

from FNM_RE.constants import ChapterSource, is_valid_boundary_state, is_valid_chapter_source
from FNM_RE.models import ChapterRecord, HeadingCandidate, PagePartitionRecord
from FNM_RE.shared.refs import extract_note_refs
from FNM_RE.shared.text import extract_page_headings, page_blocks, page_markdown_text
from FNM_RE.shared.title import chapter_title_match_key, guess_title_family, normalize_title, normalized_title_key
from FNM_RE.stages.heading_graph import (
    build_heading_graph as _run_heading_graph,
    default_heading_graph_summary as _default_heading_graph_summary_impl,
)

_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")
_NOTES_HEADER_RE = re.compile(r"^\s*(?:#+\s*)?(notes?|endnotes?|notes to pages?.*)\s*$", re.IGNORECASE)
_NOTE_DEF_RE = re.compile(r"^\s*(?:\d{1,4}[A-Za-z]?\s*[\.\)\]]|\[[0-9]{1,4}\])\s+")

_FAMILY_NONBODY = {"note", "other", "contents", "illustrations", "bibliography", "index", "appendix"}
_CHAPTER_KEYWORD_RE = re.compile(
    r"\b(?:chapter|chapitre|lecture|leçon|prologue|epilogue|postambule|appendix|appendices|part)\b",
    re.IGNORECASE,
)


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_LECTURE_TITLE_RE = re.compile(r"\ble[cç]on du\b", re.IGNORECASE)
_YEAR_RANGE_RE = re.compile(r"(?:\(|\b)(\d{4})\s*-\s*(\d{4})(?:\)|\b)")
_MAIN_NUMBERED_TITLE_RE = re.compile(
    r"^(?:chapter\s+)?(?:\d+|[IVXLCMivxlcm]+)[\.\):\-]?\s+\S+",
    re.IGNORECASE,
)
_TOC_NON_BODY_TITLE_RE = re.compile(
    r"^\s*(?:"
    r"contents?|table(?:\s+of\s+contents)?|table des mati[eè]res|sommaire|"
    r"illustrations?|list of illustrations|liste des illustrations|tables and maps|figures and tables|"
    r"bibliograph(?:y|ie)?|references?|works cited|index|indices?|"
    r"appendix|appendices|annex(?:es)?|glossary|note on sources|sources?|"
    r"conventions|abbreviations?|list of abbreviations|liste des abr[eé]viations|"
    r"acknowledg(?:e)?ments?|remerciements?|"
    r"notes?(?:\s+to\b.*)?|endnotes?|back matter"
    r")\b",
    re.IGNORECASE,
)
_TOC_FORCE_EXPORT_TITLE_RE = re.compile(
    r"^\s*(?:introduction|avertissement|pr[eé]face|foreword|epilogue|conclusion)\b",
    re.IGNORECASE,
)
_TOC_PART_TITLE_RE = re.compile(
    r"^\s*(?:part|partie|livre|book|section)\s+(?:[ivxlcm]+|\d+)\b",
    re.IGNORECASE,
)
_TOC_EXPLICIT_CHAPTER_TITLE_RE = re.compile(
    r"^(?:chapter|chapitre)\b|^(?:\d+|[ivxlcm]+)[\.\):\-]\s+\S+|\ble[cç]on du\b|\bcours\b|\bprologue\b|\bepilogue\b|\bconclusion\b",
    re.IGNORECASE,
)
_TOC_BODY_ANCHOR_TITLE_RE = re.compile(
    r"\b(?:chapter|part|book|lecture|lesson|le[cç]on|cours|epilogue|conclusion)\b",
    re.IGNORECASE,
)
_TOC_EXCLUDED_FAMILIES = {"contents", "illustrations", "bibliography", "index", "appendix"}
_TOC_LEADING_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:(?:chapter|chapitre|part|partie|section|book|livre)\s+)?(?:\d+|[ivxlcm]+)[\.\):\-–—]?\s+",
    re.IGNORECASE,
)
_TOC_PURE_NUMBER_TITLE_RE = re.compile(r"^\s*(?:\d+|[ivxlcm]+)\s*$", re.IGNORECASE)
_LECTURE_COLLECTION_EXCLUDED_TITLE_RE = re.compile(
    r"^\s*(?:cours,\s*ann[eé]e\s*1978-1979|avertissement|situation du cours)\s*$",
    re.IGNORECASE,
)
_LECTURE_COLLECTION_BOUNDARY_TITLE_RE = re.compile(
    r"^\s*(?:situation du cours)\s*$",
    re.IGNORECASE,
)
_VISUAL_TOC_ROLE_ALIAS_MAP = {
    "part": "container",
    "book": "container",
    "course": "container",
    "cours": "container",
    "appendices": "container",
    "indices": "container",
    "notes": "endnotes",
    "endnote": "endnotes",
    "frontmatter": "front_matter",
    "backmatter": "back_matter",
    "postbody": "post_body",
    "book_title": "front_matter",
}
_LECTURE_TRAILING_PAGE_SUFFIX_RE = re.compile(
    r"^(?P<title>.*\ble[cç]on du\b.+?)\s*(?:[+\-–—]\s*)?(?P<page>\d{1,4})\s*$",
    re.IGNORECASE,
)
_FRONT_MATTER_LINE_PATTERNS = (
    r"^a dissertation$",
    r"^presented to the faculty$",
    r"^of .*university$",
    r"^in candidacy for the degree$",
    r"^doctor of philosophy$",
    r"^copyright\b",
    r"^all rights reserved$",
    r"^library of congress\b",
    r"^printed in\b",
    r"^isbn\b",
    r"^[©©]",
    r"^code de la propriété intellectuelle\b",
)
_VISUAL_TOC_CHAPTER_KEYWORD_RE = re.compile(
    r"\b(chapter|chapitre|lecture|lesson|le[cç]on|prologue|epilogue)\b"
    r"|^\s*(?:part|partie|livre|book)\s+(?:[ivxlcm]+|\d+)\b",
    re.IGNORECASE,
)

from FNM_RE.stages.heading_graph import default_heading_graph_summary as _default_heading_graph_summary
from .fallback import (
    _build_fallback_chapters_and_sections,
    _candidate_section_rows,
    _classify_fallback_sections,
    _default_toc_alignment_summary,
    _default_toc_role_summary,
    _default_toc_semantic_summary,
    _find_chapter_by_page,
    _infer_back_matter_start_page,
    _mark_suppressed_candidates,
    _merge_section_heads,
    _normalize_chapters,
    _normalize_section_fallback_rows,
    _trim_chapter_rows,
)
from .heading_candidates import _collect_heading_candidate_rows, _legacy_page_rows, _normalize_heading_candidates
from .toc_semantics import (
    _build_endnote_explorer_hints,
    _build_visual_toc_chapters_and_section_heads,
    _compact_unique_titles,
    _compute_toc_role_summary,
)

def build_chapter_skeleton(
    page_partitions: list[PagePartitionRecord],
    *,
    toc_items: list[dict] | None = None,
    toc_offset: int = 0,
    pdf_path: str = "",
    pages: list[dict] | None = None,
    visual_toc_bundle: Mapping[str, Any] | None = None,
) -> tuple[list[HeadingCandidate], list[ChapterRecord], dict[str, Any]]:
    page_rows = _legacy_page_rows(page_partitions, pages)
    page_roles = {int(row.get("page_no") or 0): str(row.get("page_role") or "") for row in page_rows}
    visual_toc_items = list((visual_toc_bundle or {}).get("items") or toc_items or [])
    heading_candidate_rows = _collect_heading_candidate_rows(
        page_rows,
        toc_items=toc_items,
        toc_offset=int(toc_offset or 0),
        pdf_path=str(pdf_path or ""),
    )

    section_rows = _candidate_section_rows(heading_candidate_rows, page_rows=page_rows, page_roles=page_roles)
    classified_sections = _classify_fallback_sections(
        section_rows,
        page_roles=page_roles,
        total_pages=max(1, len(page_rows)),
        heading_candidates=heading_candidate_rows,
    )
    _mark_suppressed_candidates(classified_sections, heading_candidate_rows)
    fallback_chapters_raw, fallback_section_heads_raw, _ = _build_fallback_chapters_and_sections(
        classified_sections,
        page_rows=page_rows,
        page_roles=page_roles,
    )

    visual_chapters_raw, visual_section_heads_raw, visual_meta = _build_visual_toc_chapters_and_section_heads(
        page_rows=page_rows,
        toc_items=visual_toc_items,
        visual_toc_bundle=visual_toc_bundle,
        toc_offset=int(toc_offset or 0),
        heading_candidates=heading_candidate_rows,
    )

    if visual_chapters_raw:
        chapters_raw = list(visual_chapters_raw)
        remapped_fallback_heads: list[dict] = []
        for row in fallback_section_heads_raw:
            remapped = dict(row)
            page_no = int(remapped.get("page_no") or 0)
            remapped["chapter_id"] = _find_chapter_by_page(chapters_raw, page_no)
            if str(remapped.get("chapter_id") or "").strip():
                remapped_fallback_heads.append(remapped)
        merged_section_fallbacks = _merge_section_heads(visual_section_heads_raw, remapped_fallback_heads)
        chapter_source_summary = dict(visual_meta.get("chapter_source_summary") or {})
        chapter_source_summary.setdefault("source", "visual_toc")
        chapter_source_summary.setdefault("chapter_level", None)
        chapter_source_summary.setdefault("visual_toc_chapter_count", len(visual_chapters_raw))
        chapter_source_summary.setdefault("legacy_chapter_count", len(fallback_chapters_raw))
        chapter_source_summary.setdefault("fallback_used", False)
        source_hint: ChapterSource = "visual_toc"
    else:
        chapters_raw = list(fallback_chapters_raw)
        merged_section_fallbacks = list(fallback_section_heads_raw)
        chapter_source_summary = {
            "source": "fallback",
            "chapter_level": None,
            "visual_toc_chapter_count": 0,
            "legacy_chapter_count": len(fallback_chapters_raw),
            "fallback_used": True,
        }
        source_hint = "fallback"

    preserved_post_body_title_keys = {
        chapter_title_match_key(title)
        for title in (visual_meta.get("post_body_titles") or [])
        if chapter_title_match_key(title)
    }
    back_matter_start_page = _infer_back_matter_start_page(
        page_rows,
        toc_items=visual_toc_items,
        toc_offset=int(toc_offset or 0),
    )
    chapters_raw = _trim_chapter_rows(
        chapters_raw,
        page_roles=page_roles,
        back_matter_start_page=back_matter_start_page,
        preserve_title_keys=preserved_post_body_title_keys,
    )
    if visual_chapters_raw:
        raw_titles_by_id = {
            str(row.get("chapter_id") or "").strip(): str(row.get("title") or "").strip()
            for row in visual_chapters_raw
            if str(row.get("chapter_id") or "").strip()
        }
        kept_ids = {
            str(row.get("chapter_id") or "").strip()
            for row in chapters_raw
            if str(row.get("chapter_id") or "").strip()
        }
        dropped_titles = [
            title
            for chapter_id, title in raw_titles_by_id.items()
            if chapter_id not in kept_ids and title
        ]
        if dropped_titles:
            heading_graph_summary = dict(visual_meta.get("heading_graph_summary") or _default_heading_graph_summary())
            boundary_conflicts = _compact_unique_titles(
                list(heading_graph_summary.get("boundary_conflict_titles_preview") or []) + dropped_titles
            )[:8]
            heading_graph_summary["boundary_conflict_titles_preview"] = boundary_conflicts
            visual_meta["heading_graph_summary"] = heading_graph_summary

            toc_alignment_summary = dict(
                visual_meta.get("toc_alignment_summary") or _default_toc_alignment_summary(len(chapters_raw))
            )
            toc_alignment_summary["exported_chapter_count"] = len(chapters_raw)
            toc_alignment_summary["missing_chapter_titles_preview"] = _compact_unique_titles(
                list(toc_alignment_summary.get("missing_chapter_titles_preview") or []) + dropped_titles
            )[:8]
            visual_meta["toc_alignment_summary"] = toc_alignment_summary

            toc_export_coverage_summary = dict(visual_meta.get("toc_export_coverage_summary") or {})
            toc_export_coverage_summary["exported_body_items"] = len(chapters_raw)
            toc_export_coverage_summary["missing_body_items_preview"] = _compact_unique_titles(
                list(toc_export_coverage_summary.get("missing_body_items_preview") or []) + dropped_titles
            )[:8]
            visual_meta["toc_export_coverage_summary"] = toc_export_coverage_summary

            blocking_reasons = list(visual_meta.get("toc_semantic_blocking_reasons") or [])
            if "heading_graph_boundary_conflict" not in blocking_reasons:
                blocking_reasons.append("heading_graph_boundary_conflict")
            visual_meta["toc_semantic_blocking_reasons"] = blocking_reasons
            visual_meta["toc_semantic_contract_ok"] = False

    chapters = _normalize_chapters(chapters_raw, source_hint=source_hint)
    heading_candidates = _normalize_heading_candidates(heading_candidate_rows)
    fallback_sections = _normalize_section_fallback_rows(merged_section_fallbacks)

    toc_alignment_summary = dict(visual_meta.get("toc_alignment_summary") or _default_toc_alignment_summary(len(chapters)))
    toc_semantic_summary = dict(visual_meta.get("toc_semantic_summary") or _default_toc_semantic_summary(len(chapters)))
    toc_role_summary = dict(
        visual_meta.get("toc_role_summary") or _default_toc_role_summary(len(chapters), len(fallback_sections))
    )
    computed_roles = _compute_toc_role_summary(
        visual_toc_items,
        page_rows=page_rows,
        toc_offset=int(toc_offset or 0),
    )
    for role, count in computed_roles.items():
        toc_role_summary[role] = max(int(toc_role_summary.get(role) or 0), int(count or 0))

    meta = {
        "chapter_source_summary": chapter_source_summary,
        "visual_toc_conflict_count": int(visual_meta.get("visual_toc_conflict_count") or 0),
        "back_matter_start_page": int(back_matter_start_page or 0),
        "toc_alignment_summary": toc_alignment_summary,
        "toc_semantic_summary": toc_semantic_summary,
        "heading_graph_summary": dict(visual_meta.get("heading_graph_summary") or _default_heading_graph_summary()),
        "toc_role_summary": toc_role_summary,
        "container_titles": list(visual_meta.get("container_titles") or []),
        "endnotes_titles": list(visual_meta.get("endnotes_titles") or []),
        "post_body_titles": list(visual_meta.get("post_body_titles") or []),
        "back_matter_titles": list(visual_meta.get("back_matter_titles") or []),
        "normalized_toc_rows": list(visual_meta.get("normalized_toc_rows") or []),
        "chapter_title_alignment_ok": bool(
            visual_meta.get("chapter_title_alignment_ok", True if not visual_toc_items else bool(visual_chapters_raw))
        ),
        "chapter_section_alignment_ok": bool(
            visual_meta.get("chapter_section_alignment_ok", True if not visual_toc_items else bool(visual_chapters_raw))
        ),
        "toc_semantic_contract_ok": bool(visual_meta.get("toc_semantic_contract_ok", True)),
        "toc_semantic_blocking_reasons": list(visual_meta.get("toc_semantic_blocking_reasons") or []),
        "visual_toc_endnotes_summary": dict((visual_toc_bundle or {}).get("endnotes_summary") or {}),
        "endnote_explorer_hints": _build_endnote_explorer_hints(
            visual_toc_bundle=visual_toc_bundle,
            normalized_toc_rows=list(visual_meta.get("normalized_toc_rows") or []),
        ),
        "fallback_sections": fallback_sections,
    }
    return heading_candidates, chapters, meta

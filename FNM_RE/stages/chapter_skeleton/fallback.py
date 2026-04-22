"""章节骨架：fallback chapter/section 构建。"""

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

from .heading_candidates import _build_pdf_page_by_file_idx, _chapter_keyword_strength, _is_sentence_like_heading


def _normalize_title(value: Any) -> str:
    return normalize_title(str(value or ""))

def _candidate_section_rows(
    heading_candidates: list[dict],
    *,
    page_rows: list[dict],
    page_roles: dict[int, str],
) -> list[dict]:
    all_pages = sorted({int(row.get("page_no") or 0) for row in page_rows if int(row.get("page_no") or 0) > 0})
    if not all_pages:
        return []
    selected: list[dict] = []
    dedupe: set[tuple[int, str]] = set()
    for candidate in heading_candidates:
        page_no = int(candidate.get("page_no") or 0)
        if page_no <= 0:
            continue
        if page_roles.get(page_no) not in {"body", "front_matter"}:
            continue
        source = str(candidate.get("source") or "").strip().lower()
        family = str(candidate.get("heading_family_guess") or "").strip().lower()
        if source == "note_heading":
            continue
        if family in _FAMILY_NONBODY:
            continue
        title = normalize_title(candidate.get("text") or "")
        key = chapter_title_match_key(title)
        if not title or not key:
            continue
        dedupe_key = (page_no, key)
        if dedupe_key in dedupe:
            continue
        dedupe.add(dedupe_key)
        selected.append({"page_no": page_no, "title": title, "source": source})
    selected.sort(key=lambda item: (int(item.get("page_no") or 0), str(item.get("title") or "")))
    rows: list[dict] = []
    for index, section in enumerate(selected, start=1):
        start_page = int(section.get("page_no") or 0)
        if start_page <= 0:
            continue
        next_page = int(selected[index].get("page_no") or 0) if index < len(selected) else 0
        end_page = next_page - 1 if next_page > start_page else all_pages[-1]
        raw_pages = [page_no for page_no in all_pages if start_page <= page_no <= end_page]
        filtered_pages = [page_no for page_no in raw_pages if page_roles.get(page_no) in {"body", "front_matter"}]
        if not filtered_pages:
            continue
        rows.append(
            {
                "section_id": f"sec-{index:04d}",
                "title": str(section.get("title") or ""),
                "start_page": filtered_pages[0],
                "end_page": filtered_pages[-1],
                "raw_pages": raw_pages,
                "filtered_pages": filtered_pages,
                "source": str(section.get("source") or "fallback"),
            }
        )
    return rows

def _classify_fallback_sections(
    section_rows: list[dict],
    *,
    page_roles: dict[int, str],
    total_pages: int,
    heading_candidates: list[dict],
) -> list[dict]:
    classified: list[dict] = []
    for section in section_rows:
        title = normalize_title(section.get("title") or "")
        start_page = int(section.get("start_page") or 0)
        filtered_pages = [int(page_no) for page_no in (section.get("filtered_pages") or []) if int(page_no) > 0]
        span_pages = len(filtered_pages)
        title_key = chapter_title_match_key(title)
        matched_candidates = [
            candidate
            for candidate in heading_candidates
            if abs(int(candidate.get("page_no") or 0) - start_page) <= 1
            and (not title_key or chapter_title_match_key(candidate.get("text") or "") == title_key)
        ]
        chapter_evidence = [
            candidate
            for candidate in matched_candidates
            if page_roles.get(int(candidate.get("page_no") or 0)) in {"body", "front_matter"}
        ]
        has_visual_toc = any(str(item.get("source") or "") == "visual_toc" for item in chapter_evidence)
        has_top_doc_title = any(
            str(item.get("source") or "") == "ocr_block"
            and str(item.get("block_label") or "") == "doc_title"
            and bool(item.get("top_band"))
            for item in chapter_evidence
        )
        has_pdf_font = any(str(item.get("source") or "") == "pdf_font_band" for item in chapter_evidence)
        keyword_strength = _chapter_keyword_strength(title)
        strong_evidence = bool(has_visual_toc or has_top_doc_title or has_pdf_font or keyword_strength >= 1.0)
        start_role = str(page_roles.get(start_page) or "")
        family = str(guess_title_family(title, page_no=max(1, start_page), total_pages=max(1, total_pages)) or "body")
        keep = True
        reject_reason = ""
        score = 0.0
        if not title:
            keep = False
            reject_reason = "invalid_title"
        elif start_role in {"noise", "other"}:
            keep = False
            reject_reason = "partition_conflict"
        elif start_role == "note":
            keep = False
            reject_reason = "note_partition"
        elif _NOTES_HEADER_RE.match(title):
            keep = False
            reject_reason = "note_heading"
        elif family in {"contents", "illustrations", "bibliography", "index", "appendix"}:
            keep = False
            reject_reason = "non_body_family"
        elif _is_sentence_like_heading(title) and not strong_evidence:
            keep = False
            reject_reason = "sentence_like"
        else:
            if has_visual_toc:
                score += 3.0
            if has_top_doc_title:
                score += 1.8
            if has_pdf_font:
                score += 1.2
            if has_top_doc_title and keyword_strength >= 1.0:
                score += 1.2
            if span_pages >= 4:
                score += 1.2
            elif span_pages == 3:
                score += 0.5
            elif span_pages <= 2:
                score -= 0.8 if has_top_doc_title or has_visual_toc else 1.8
            score += float(keyword_strength)
            all_paragraph_title = bool(chapter_evidence) and all(
                str(item.get("source") or "") == "ocr_block"
                and str(item.get("block_label") or "") == "paragraph_title"
                for item in chapter_evidence
            )
            if all_paragraph_title and not strong_evidence:
                score -= 1.2
            keep = score >= 2.0
            if keep and span_pages <= 2 and not strong_evidence:
                keep = False
                reject_reason = "short_span"
            if not keep and not reject_reason:
                reject_reason = "low_score"
        classified.append(
            {
                **section,
                "title": title,
                "start_page": start_page,
                "span_pages": span_pages,
                "start_role": start_role,
                "title_family": family,
                "matched_candidates": matched_candidates,
                "keep_as_chapter": bool(keep),
                "reject_reason": reject_reason,
                "classification_score": float(score),
                "classification_confidence": max(0.0, min(1.0, 0.5 + score / 6.0)),
            }
        )
    if classified and not any(bool(row.get("keep_as_chapter")) for row in classified):
        fallback_index: int | None = None
        for index, row in enumerate(classified):
            if str(row.get("start_role") or "") not in {"body", "front_matter"}:
                continue
            if _NOTES_HEADER_RE.match(str(row.get("title") or "").strip()):
                continue
            fallback_index = index
            break
        if fallback_index is not None:
            classified[fallback_index]["keep_as_chapter"] = True
            classified[fallback_index]["reject_reason"] = ""
            classified[fallback_index]["classification_score"] = max(
                2.1,
                float(classified[fallback_index].get("classification_score") or 0.0),
            )
    return classified

def _mark_suppressed_candidates(classified_sections: list[dict], heading_candidates: list[dict]) -> None:
    for section in classified_sections:
        if bool(section.get("keep_as_chapter")):
            for candidate in section.get("matched_candidates") or []:
                if str(candidate.get("heading_family_guess") or "") not in {"note", "other"}:
                    candidate["heading_family_guess"] = "chapter"
            continue
        reject_reason = str(section.get("reject_reason") or "demoted")
        title_key = chapter_title_match_key(section.get("title") or "")
        start_page = int(section.get("start_page") or 0)
        matched = False
        for candidate in heading_candidates:
            page_no = int(candidate.get("page_no") or 0)
            if abs(page_no - start_page) > 1:
                continue
            if title_key and chapter_title_match_key(candidate.get("text") or "") != title_key:
                continue
            candidate["suppressed_as_chapter"] = True
            candidate["reject_reason"] = reject_reason
            candidate["heading_family_guess"] = "section"
            matched = True
        if matched:
            continue
        heading_candidates.append(
            {
                "heading_id": "",
                "page_no": start_page,
                "text": str(section.get("title") or ""),
                "normalized_text": normalize_title(section.get("title") or ""),
                "source": "fallback",
                "block_label": "",
                "top_band": True,
                "font_height": None,
                "x": None,
                "y": None,
                "width_estimate": None,
                "font_name": "",
                "font_weight_hint": "unknown",
                "align_hint": "unknown",
                "width_ratio": None,
                "heading_level_hint": 2,
                "confidence": float(section.get("classification_confidence", 0.55) or 0.55),
                "heading_family_guess": "section",
                "suppressed_as_chapter": True,
                "reject_reason": reject_reason,
            }
        )

def _build_fallback_chapters_and_sections(
    classified_sections: list[dict],
    *,
    page_rows: list[dict],
    page_roles: dict[int, str],
) -> tuple[list[dict], list[dict], dict[str, str]]:
    if not classified_sections:
        return [], [], {}
    all_page_numbers = [int(row.get("page_no") or 0) for row in page_rows if int(row.get("page_no") or 0) > 0]
    all_page_numbers.sort()
    if not all_page_numbers:
        return [], [], {}
    kept_indexes = [index for index, row in enumerate(classified_sections) if bool(row.get("keep_as_chapter"))]
    if not kept_indexes:
        return [], [], {}
    chapters: list[dict] = []
    section_to_chapter_id: dict[str, str] = {}
    for keep_pos, section_index in enumerate(kept_indexes, start=1):
        section = classified_sections[section_index]
        chapter_id = f"ch-fallback-{keep_pos:04d}"
        next_keep_index = kept_indexes[keep_pos] if keep_pos < len(kept_indexes) else len(classified_sections)
        section_start = int(section.get("start_page") or 0)
        next_start = int(classified_sections[next_keep_index].get("start_page") or 0) if next_keep_index < len(classified_sections) else 0
        section_end_limit = next_start - 1 if next_start > section_start else max(all_page_numbers)
        raw_span = [page_no for page_no in all_page_numbers if section_start <= page_no <= section_end_limit]
        filtered = [page_no for page_no in raw_span if page_roles.get(page_no, "") in {"body", "front_matter"}]
        if not filtered:
            filtered = [int(page_no) for page_no in (section.get("filtered_pages") or []) if int(page_no) > 0]
        if not filtered:
            continue
        chapters.append(
            {
                "chapter_id": chapter_id,
                "title": str(section.get("title") or ""),
                "start_page": filtered[0],
                "end_page": filtered[-1],
                "pages": filtered,
                "source": "fallback",
                "boundary_state": "ready",
            }
        )
        for mapping_index in range(section_index, next_keep_index):
            section_id = str(classified_sections[mapping_index].get("section_id") or "").strip()
            if section_id:
                section_to_chapter_id[section_id] = chapter_id
        section_to_chapter_id[str(section.get("section_id") or "")] = chapter_id
    if not chapters:
        return [], [], {}
    first_chapter_id = str(chapters[0].get("chapter_id") or "")
    last_chapter_id = str(chapters[-1].get("chapter_id") or "")
    for index in range(0, kept_indexes[0]):
        section_id = str(classified_sections[index].get("section_id") or "").strip()
        if section_id:
            section_to_chapter_id.setdefault(section_id, first_chapter_id)
    for index in range(kept_indexes[-1] + 1, len(classified_sections)):
        section_id = str(classified_sections[index].get("section_id") or "").strip()
        if section_id:
            section_to_chapter_id.setdefault(section_id, last_chapter_id)

    section_heads: list[dict] = []
    serial = 1
    for section in classified_sections:
        if bool(section.get("keep_as_chapter")):
            continue
        section_id = str(section.get("section_id") or "").strip()
        chapter_id = str(section_to_chapter_id.get(section_id) or "").strip()
        title = str(section.get("title") or "").strip()
        if not title:
            continue
        section_heads.append(
            {
                "section_head_id": f"section-head-{serial:04d}",
                "chapter_id": chapter_id,
                "text": title,
                "title": title,
                "normalized_text": normalize_title(title),
                "page_no": int(section.get("start_page") or 0),
                "level": 2,
                "source": "fallback",
            }
        )
        serial += 1
    return chapters, section_heads, section_to_chapter_id

def _find_chapter_by_page(chapters: list[dict], page_no: int) -> str:
    ordered = sorted(chapters, key=lambda item: int(item.get("start_page") or 0))
    for chapter in ordered:
        if int(page_no) in {int(page) for page in (chapter.get("pages") or []) if int(page) > 0}:
            return str(chapter.get("chapter_id") or "")
    prior = [chapter for chapter in ordered if int(chapter.get("start_page") or 0) <= int(page_no)]
    return str(prior[-1].get("chapter_id") or "") if prior else ""

def _merge_section_heads(primary: list[dict], supplemental: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, int, str]] = set()
    serial = 1
    for row in list(primary or []) + list(supplemental or []):
        chapter_id = str(row.get("chapter_id") or "").strip()
        page_no = int(row.get("page_no") or 0)
        text = normalize_title(row.get("text") or row.get("title") or "")
        if not text:
            continue
        key = (chapter_id, page_no, chapter_title_match_key(text))
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                **dict(row),
                "section_head_id": f"section-head-{serial:04d}",
                "text": text,
                "title": text,
                "normalized_text": normalize_title(text),
            }
        )
        serial += 1
    return merged

def _normalize_chapters(chapter_rows: list[dict], *, source_hint: ChapterSource) -> list[ChapterRecord]:
    normalized: list[ChapterRecord] = []
    for row in chapter_rows:
        pages = [int(page_no) for page_no in (row.get("pages") or []) if int(page_no) > 0]
        if not pages:
            continue
        chapter_id = str(row.get("chapter_id") or "").strip()
        if not chapter_id:
            continue
        source_value = str(row.get("source") or source_hint).strip()
        if not is_valid_chapter_source(source_value):
            source_value = source_hint
        boundary_state = str(row.get("boundary_state") or "ready").strip()
        if not is_valid_boundary_state(boundary_state):
            boundary_state = "ready"
        normalized.append(
            ChapterRecord(
                chapter_id=chapter_id,
                title=str(row.get("title") or "").strip(),
                start_page=int(row.get("start_page") or pages[0]),
                end_page=int(row.get("end_page") or pages[-1]),
                pages=pages,
                source=source_value,  # type: ignore[arg-type]
                boundary_state=boundary_state,  # type: ignore[arg-type]
            )
        )
    normalized.sort(key=lambda item: (item.start_page, item.chapter_id))
    return normalized

def _normalize_section_fallback_rows(section_rows: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for row in section_rows:
        title = normalize_title(row.get("text") or row.get("title") or "")
        if not title:
            continue
        page_no = int(row.get("page_no") or row.get("start_page") or 0)
        if page_no <= 0:
            continue
        normalized.append(
            {
                "chapter_id": str(row.get("chapter_id") or "").strip(),
                "title": title,
                "page_no": page_no,
                "level": max(1, int(row.get("level") or 2)),
                "source": str(row.get("source") or "fallback"),
            }
        )
    normalized.sort(key=lambda item: (int(item.get("page_no") or 0), str(item.get("title") or "")))
    return normalized

def _default_toc_alignment_summary(chapter_count: int) -> dict[str, Any]:
    return {
        "chapter_level_body_items": 0,
        "exported_chapter_count": int(chapter_count),
        "missing_chapter_titles_preview": [],
        "misleveled_titles_preview": [],
        "reanchored_titles_preview": [],
        "missing_section_titles_preview": [],
    }

def _default_toc_semantic_summary(chapter_count: int) -> dict[str, Any]:
    return {
        "body_item_count": 0,
        "chapter_item_count": int(chapter_count),
        "part_item_count": 0,
        "endnotes_item_count": 0,
        "back_matter_item_count": 0,
        "first_body_pdf_page": 0,
        "last_body_pdf_page": 0,
        "body_span_ratio": 0.0,
        "nonbody_contamination_count": 0,
        "mixed_level_chapter_count": 0,
    }

def _default_toc_role_summary(chapter_count: int, section_count: int) -> dict[str, Any]:
    return {
        "container": 0,
        "endnotes": 0,
        "chapter": int(chapter_count),
        "section": int(section_count),
        "post_body": 0,
        "back_matter": 0,
        "front_matter": 0,
    }

def _infer_back_matter_start_page(
    page_rows: list[dict],
    *,
    toc_items: list[dict] | None,
    toc_offset: int,
) -> int:
    candidate_pages: list[int] = []
    total_pages = max(1, len(page_rows))
    rear_page_role_min_page = max(24, int(total_pages * 0.45))
    rear_page_role_force_page = max(rear_page_role_min_page, int(total_pages * 0.8))
    toc_back_matter_min_page = max(24, int(total_pages * 0.25))
    rear_reasons = {
        "appendix",
        "bibliography",
        "index",
        "illustrations",
        "rear_toc_tail",
        "rear_author_blurb",
        "rear_sparse_other",
    }
    rear_role_pages = sorted(
        int(row.get("page_no") or 0)
        for row in page_rows
        if int(row.get("page_no") or 0) >= rear_page_role_min_page
        and str(row.get("page_role") or "") == "other"
        and str(row.get("role_reason") or "") in rear_reasons
    )
    for row in page_rows:
        page_no = int(row.get("page_no") or 0)
        if page_no <= 0:
            continue
        if page_no < rear_page_role_min_page:
            continue
        if str(row.get("page_role") or "") != "other":
            continue
        if str(row.get("role_reason") or "") not in rear_reasons:
            continue
        has_neighboring_rear_page = any(
            other_page != page_no and abs(other_page - page_no) <= 6
            for other_page in rear_role_pages
        )
        if page_no >= rear_page_role_force_page or has_neighboring_rear_page:
            candidate_pages.append(page_no)
    raw_pages = [dict(row.get("_page") or {}) for row in page_rows]
    file_idx_map = _build_pdf_page_by_file_idx(raw_pages)
    for item in toc_items or []:
        page_no = resolve_toc_item_target_pdf_page(
            item,
            offset=int(toc_offset or 0),
            pages=raw_pages,
            pdf_page_by_file_idx=file_idx_map,
        )
        try:
            resolved_page = int(page_no)
        except (TypeError, ValueError):
            continue
        if resolved_page <= 0:
            continue
        if resolved_page < toc_back_matter_min_page:
            continue
        role_hint = str(item.get("role_hint") or "").strip().lower().replace("-", "_")
        family = guess_title_family(item.get("title") or "", page_no=resolved_page, total_pages=total_pages)
        if role_hint == "back_matter" or family in {"bibliography", "index", "illustrations"}:
            candidate_pages.append(resolved_page)
    return min(candidate_pages) if candidate_pages else 0

def _trim_chapter_rows(
    chapter_rows: list[dict],
    *,
    page_roles: dict[int, str],
    back_matter_start_page: int,
    preserve_title_keys: set[str],
) -> list[dict]:
    trimmed_rows: list[dict] = []
    for row in chapter_rows:
        pages = [int(page_no) for page_no in (row.get("pages") or []) if int(page_no) > 0]
        if not pages:
            continue
        filtered_pages = [page_no for page_no in pages if page_roles.get(page_no) in {"body", "front_matter"}]
        title_key = chapter_title_match_key(str(row.get("title") or ""))
        if (
            back_matter_start_page > 0
            and title_key not in preserve_title_keys
            and not _is_toc_force_export_title(str(row.get("title") or ""))
        ):
            filtered_pages = [page_no for page_no in filtered_pages if page_no < back_matter_start_page]
        if not filtered_pages:
            continue
        clone = dict(row)
        clone["pages"] = filtered_pages
        clone["start_page"] = filtered_pages[0]
        clone["end_page"] = filtered_pages[-1]
        trimmed_rows.append(clone)
    return trimmed_rows

def _is_toc_force_export_title(title: str) -> bool:
    return bool(_TOC_FORCE_EXPORT_TITLE_RE.match(_normalize_title(title)))

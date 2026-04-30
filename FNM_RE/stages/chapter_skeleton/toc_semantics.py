"""章节骨架：visual TOC 语义落章与 endnote 提示。"""

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
from FNM_RE.stages.page_partition import (
    _plain_text_lines,
    _uppercase_ratio,
    _markdown_body_after_first_heading,
    _looks_like_prose_after_heading,
    _looks_like_title_page,
    _looks_like_course_listing_page,
    _looks_like_copyright_front_matter_page,
    _is_toc_force_export_title,
    _is_visual_toc_explicit_chapter_title,
)
from FNM_RE.stages.heading_graph import build_heading_graph, default_heading_graph_summary
from FNM_RE.shared.notes import _safe_int

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
_ENDNOTE_NAMED_SUBENTRY_RE = re.compile(
    r"^\s*(?:chapter|chapitre|part|partie|book|livre|lecture|lesson|le[cç]on|section|introduction|conclusion|prologue|epilogue)\b",
    re.IGNORECASE,
)
_ENDNOTE_NUMBERED_SUBENTRY_RE = re.compile(
    r"^\s*(?:\d+|[ivxlcm]+)[\.\):\-]\s+\S+",
    re.IGNORECASE,
)
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

from .fallback import (
    _default_toc_alignment_summary,
    _default_toc_role_summary,
    _default_toc_semantic_summary,
    _find_chapter_by_page,
    _merge_section_heads,
)
from .heading_candidates import _build_pdf_page_by_file_idx

def _normalize_visual_toc_role_hint(raw_value: Any) -> str:
    role = str(raw_value or "").strip().lower().replace("-", "_")
    return _VISUAL_TOC_ROLE_ALIAS_MAP.get(role, role)

def _compute_toc_role_summary(
    toc_items: list[dict] | None,
    *,
    page_rows: list[dict],
    toc_offset: int,
) -> dict[str, int]:
    counts = {
        "container": 0,
        "endnotes": 0,
        "chapter": 0,
        "section": 0,
        "post_body": 0,
        "back_matter": 0,
        "front_matter": 0,
    }
    raw_pages = [dict(row.get("_page") or {}) for row in page_rows]
    file_idx_map = _build_pdf_page_by_file_idx(raw_pages)
    total_pages = max(1, len(page_rows))
    for item in toc_items or []:
        title = normalize_title(item.get("title") or "")
        if not title:
            continue
        role_hint = _normalize_visual_toc_role_hint(item.get("role_hint") or "")
        if role_hint not in counts:
            page_no = resolve_toc_item_target_pdf_page(
                item,
                offset=int(toc_offset or 0),
                pages=raw_pages,
                pdf_page_by_file_idx=file_idx_map,
            )
            try:
                resolved_page = int(page_no)
            except (TypeError, ValueError):
                resolved_page = 0
            family = guess_title_family(title, page_no=max(1, resolved_page), total_pages=total_pages)
            if family in {"bibliography", "index", "illustrations"}:
                role_hint = "back_matter"
            elif family == "contents":
                role_hint = "front_matter"
            else:
                role_hint = "chapter"
        counts[role_hint] += 1
    return counts

def _normalize_title(value: Any) -> str:
    return normalize_title(str(value or ""))

def _normalize_visual_toc_item_title(value: Any) -> str:
    normalized = normalize_title(str(value or ""))
    if not normalized:
        return ""
    normalized = re.sub(r"\s[.\u2026,:;•·]{4,}.*$", "", normalized).strip()
    normalized = re.sub(r"(?i)'=b", "'emb", normalized)
    normalized = re.sub(r"(?<=[A-Za-zÀ-ÿ])=(?=[A-Za-zÀ-ÿ]{2,})", "em", normalized)
    return normalize_title(normalized)

def _chapter_title_match_key(value: Any) -> str:
    return chapter_title_match_key(str(value or ""))

def _normalized_title_key(value: Any) -> str:
    return normalized_title_key(str(value or ""))

def _page_markdown_text(page: dict | None) -> str:
    return page_markdown_text(page)

def _extract_page_headings(page: dict | None) -> list[str]:
    return [
        heading
        for heading in (extract_page_headings(page) or [])
        if _normalize_title(heading)
    ]

def _visual_toc_chapter_keyword_strength(title: str) -> int:
    text = _normalize_title(title)
    if not text:
        return 0
    if _VISUAL_TOC_CHAPTER_KEYWORD_RE.search(text):
        return 2
    if _MAIN_NUMBERED_TITLE_RE.search(text):
        return 1
    return 0

def _title_family(title: str, *, page_no: int, total_pages: int) -> str:
    return str(
        guess_title_family(
            _normalize_title(title),
            page_no=max(1, int(page_no or 1)),
            total_pages=max(1, int(total_pages or 1)),
        )
        or "body"
    )

def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _trim_exportable_chapter_pages(
    page_numbers: list[int],
    *,
    page_by_no: dict[int, dict],
    total_pages: int,
) -> list[int]:
    trimmed = [int(page_no) for page_no in page_numbers if int(page_no) > 0]
    while trimmed:
        page_no = int(trimmed[0])
        row = dict(page_by_no.get(page_no) or {})
        role = str(row.get("page_role") or "")
        page = dict(row.get("_page") or {})
        text = _page_markdown_text(page)
        headings = _extract_page_headings(page)
        if role in {"noise", "other"}:
            trimmed.pop(0)
            continue
        if role != "front_matter":
            break
        first_heading = _normalize_title(headings[0] if headings else "")
        if first_heading and _is_toc_force_export_title(first_heading) and _looks_like_prose_after_heading(text):
            break
        if _looks_like_copyright_front_matter_page(text, page_no=page_no, total_pages=total_pages):
            trimmed.pop(0)
            continue
        if _looks_like_course_listing_page(text, page_no=page_no, total_pages=total_pages):
            trimmed.pop(0)
            continue
        if _looks_like_title_page(text, headings, page_no=page_no, total_pages=total_pages):
            trimmed.pop(0)
            continue
        if not _looks_like_prose_after_heading(text):
            trimmed.pop(0)
            continue
        break
    return trimmed or [int(page_no) for page_no in page_numbers if int(page_no) > 0]

def _visual_toc_level(item: dict) -> int:
    role_hint = _normalize_visual_toc_role_hint(
        item.get("role_hint") or item.get("explicit_role_hint") or ""
    )
    depth = _safe_int(item.get("depth"))
    if role_hint in {"container", "endnotes"}:
        return 1
    if role_hint == "chapter":
        return 2
    if role_hint == "section":
        semantic_depth = max(2, int(depth or 0))
        return semantic_depth + 1
    if role_hint in {"front_matter", "back_matter", "post_body"}:
        return 0
    level = _safe_int(item.get("level"))
    if level is not None and level > 0:
        return int(level)
    depth = _safe_int(item.get("depth"))
    if depth is not None and depth >= 0:
        return int(depth) + 1
    return 1

def _normalize_toc_chapter_id(raw_id: Any, *, order: int, title: str) -> str:
    raw = str(raw_id or "").strip()
    if raw:
        normalized = re.sub(r"[^0-9A-Za-z_\-]+", "-", raw).strip("-")
        if normalized:
            return f"toc-{normalized}"
    title_key = _chapter_title_match_key(title)
    if not title_key:
        title_key = f"{order:03d}"
    return f"toc-ch-{order:03d}-{title_key[:24]}"

def _is_toc_body_anchor_title(title: str) -> bool:
    return bool(_TOC_BODY_ANCHOR_TITLE_RE.search(_normalize_title(title)))

def _is_toc_part_title(title: str) -> bool:
    return bool(_TOC_PART_TITLE_RE.match(_normalize_title(title)))

def _is_visual_toc_body_candidate(row: dict) -> bool:
    if "body_candidate" in row:
        return bool(row.get("body_candidate"))
    if bool(row.get("non_body_title")):
        return False
    role_hint = _normalize_visual_toc_role_hint(row.get("role_hint") or "")
    if role_hint in {"container", "endnotes", "post_body", "back_matter", "front_matter"}:
        return False
    family = str(row.get("family") or "")
    if family in _TOC_EXCLUDED_FAMILIES:
        return False
    title = str(row.get("title") or "")
    page_role = str(row.get("page_role") or "")
    if page_role == "body":
        return True
    if page_role == "front_matter" and _is_toc_force_export_title(title):
        return True
    if _is_toc_body_anchor_title(title):
        return True
    return bool(row.get("resolved_via_heading"))

def _visual_toc_title_key(row: dict) -> str:
    return _chapter_title_match_key(str(row.get("title") or ""))

def _visual_toc_row_key(row: dict) -> tuple[int, str]:
    return (int(row.get("page_no") or 0), _visual_toc_title_key(row))

def _dedupe_visual_toc_rows(rows: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for row in rows or []:
        key = _visual_toc_row_key(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped

def _strip_trailing_toc_noise(title: str) -> str:
    normalized = _normalize_title(title)
    while normalized and normalized[-1] in {" ", ".", "·", "•", "…", ",", ":", ";", "'", "-"}:
        normalized = normalized[:-1].rstrip()
    return normalized

def _strip_leading_toc_number_prefix(title: str) -> str:
    normalized = _strip_trailing_toc_noise(title)
    previous = ""
    while normalized and normalized != previous:
        previous = normalized
        normalized = _TOC_LEADING_NUMBER_PREFIX_RE.sub("", normalized).strip()
    return normalized

def _semantic_visual_toc_title_key(title: str, *, strip_number_prefix: bool = False) -> str:
    normalized = _strip_leading_toc_number_prefix(title) if strip_number_prefix else _strip_trailing_toc_noise(title)
    return normalized_title_key(normalized)

def _has_leading_toc_number_prefix(title: str) -> bool:
    normalized = _strip_trailing_toc_noise(title)
    if not normalized:
        return False
    return normalized != _strip_leading_toc_number_prefix(normalized)

def _prefixed_visual_toc_row_should_yield_to_clean(row: dict) -> bool:
    clean_title = _normalize_title(_strip_leading_toc_number_prefix(str(row.get("title") or "")))
    if not clean_title:
        return True
    if _is_toc_force_export_title(clean_title):
        return True
    return False

def _apply_preferred_duplicate_parent_context(
    preferred_row: dict,
    fallback_rows: list[dict],
    *,
    rows: list[dict],
) -> None:
    container_title_keys = {
        _semantic_visual_toc_title_key(str(row.get("title") or ""))
        for row in rows
        if str(row.get("role_hint") or "") == "container"
        and _semantic_visual_toc_title_key(str(row.get("title") or ""))
    }
    current_parent_key = _semantic_visual_toc_title_key(str(preferred_row.get("parent_title") or ""))
    if current_parent_key in container_title_keys:
        return
    for fallback_row in fallback_rows:
        parent_title = _normalize_title(str(fallback_row.get("parent_title") or ""))
        parent_key = _semantic_visual_toc_title_key(parent_title)
        if not parent_title or parent_key not in container_title_keys:
            continue
        preferred_row["parent_title"] = parent_title
        return

def _is_pure_number_toc_title(title: str) -> bool:
    return bool(_TOC_PURE_NUMBER_TITLE_RE.match(_strip_trailing_toc_noise(title)))

def _visual_toc_rows_are_nearby(left: dict, right: dict, *, max_gap: int = 12) -> bool:
    left_page = int(left.get("page_no") or 0)
    right_page = int(right.get("page_no") or 0)
    if left_page <= 0 or right_page <= 0:
        return True
    return abs(left_page - right_page) <= max(0, int(max_gap))

def _suppress_visual_toc_semantic_row(row: dict, *, role_hint: str = "section") -> None:
    if role_hint:
        row["role_hint"] = role_hint
    row["body_candidate"] = False
    row["export_candidate"] = False
    row["semantic_suppressed"] = True

def _suppress_visual_toc_composite_root_duplicates(rows: list[dict]) -> None:
    chapter_rows = [
        row
        for row in rows
        if str(row.get("role_hint") or "") == "chapter"
        and bool(row.get("body_candidate", True))
        and bool(row.get("export_candidate", True))
        and str(row.get("parent_title") or "").strip()
        and int(row.get("page_no") or 0) > 0
    ]
    for row in chapter_rows:
        title_key = _semantic_visual_toc_title_key(str(row.get("title") or ""))
        parent_key = _semantic_visual_toc_title_key(str(row.get("parent_title") or ""))
        if not title_key or not parent_key or parent_key not in title_key:
            continue
        for sibling in chapter_rows:
            if sibling is row:
                continue
            if int(sibling.get("page_no") or 0) != int(row.get("page_no") or 0):
                continue
            if _semantic_visual_toc_title_key(str(sibling.get("parent_title") or "")) != parent_key:
                continue
            sibling_key = _semantic_visual_toc_title_key(str(sibling.get("title") or ""))
            if not sibling_key or sibling_key == title_key or parent_key in sibling_key:
                continue
            if sibling_key in title_key:
                _suppress_visual_toc_semantic_row(row)
                break

def _suppress_visual_toc_prefixed_duplicates(rows: list[dict]) -> None:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if str(row.get("role_hint") or "") != "chapter":
            continue
        if not bool(row.get("body_candidate", True)) or not bool(row.get("export_candidate", True)):
            continue
        canonical_key = _semantic_visual_toc_title_key(str(row.get("title") or ""), strip_number_prefix=True)
        if len(canonical_key) < 6:
            continue
        groups.setdefault(canonical_key, []).append(row)

    for group in groups.values():
        clean_rows = [row for row in group if not _has_leading_toc_number_prefix(str(row.get("title") or ""))]
        if not clean_rows:
            continue
        for row in group:
            if row in clean_rows:
                continue
            if not _has_leading_toc_number_prefix(str(row.get("title") or "")):
                continue
            nearby_clean_rows = [
                clean_row
                for clean_row in clean_rows
                if _visual_toc_rows_are_nearby(row, clean_row)
            ]
            if not nearby_clean_rows:
                continue
            if _prefixed_visual_toc_row_should_yield_to_clean(row):
                _suppress_visual_toc_semantic_row(row)
                continue
            _apply_preferred_duplicate_parent_context(row, nearby_clean_rows, rows=rows)
            for clean_row in nearby_clean_rows:
                _suppress_visual_toc_semantic_row(clean_row)

def _merge_visual_toc_split_heading_rows(rows: list[dict]) -> None:
    chapter_rows = [
        row
        for row in rows
        if str(row.get("role_hint") or "") == "chapter"
        and bool(row.get("body_candidate", True))
        and bool(row.get("export_candidate", True))
        and int(row.get("page_no") or 0) > 0
        and _has_leading_toc_number_prefix(str(row.get("title") or ""))
    ]
    for row in chapter_rows:
        short_title = _normalize_title(_strip_leading_toc_number_prefix(str(row.get("title") or "")))
        if not short_title:
            continue
        sibling_rows = [
            sibling
            for sibling in rows
            if sibling is not row
            and str(sibling.get("role_hint") or "") == "chapter"
            and bool(sibling.get("body_candidate", True))
            and bool(sibling.get("export_candidate", True))
            and int(sibling.get("page_no") or 0) == int(row.get("page_no") or 0)
            and _normalize_title(str(sibling.get("title") or "")) != short_title
        ]
        matching_long_rows = [
            sibling
            for sibling in sibling_rows
            if _normalize_title(str(sibling.get("title") or "")).startswith(f"{short_title} ")
        ]
        if not matching_long_rows:
            continue
        row["title"] = short_title
        _apply_preferred_duplicate_parent_context(row, matching_long_rows, rows=rows)
        for sibling in matching_long_rows:
            _suppress_visual_toc_semantic_row(sibling)

def _suppress_visual_toc_numeric_root_noise(rows: list[dict]) -> None:
    child_rows_by_parent: dict[str, list[dict]] = {}
    for row in rows:
        parent_title = _normalize_title(str(row.get("parent_title") or ""))
        if not parent_title:
            continue
        child_rows_by_parent.setdefault(parent_title, []).append(row)

    root_rows = [
        row
        for row in rows
        if str(row.get("role_hint") or "") == "chapter"
        and bool(row.get("body_candidate", True))
        and bool(row.get("export_candidate", True))
        and not str(row.get("parent_title") or "").strip()
    ]
    for row in root_rows:
        title = str(row.get("title") or "")
        if not _is_pure_number_toc_title(title):
            continue
        child_rows = child_rows_by_parent.get(_normalize_title(title), [])
        numeric_children = [
            child for child in child_rows
            if bool(child.get("body_candidate", True)) and _is_pure_number_toc_title(str(child.get("title") or ""))
        ]
        if len(numeric_children) < 2 or len(numeric_children) != len(child_rows):
            continue
        nearby_semantic_rows = [
            other
            for other in root_rows
            if other is not row
            and not _is_pure_number_toc_title(str(other.get("title") or ""))
            and _visual_toc_rows_are_nearby(row, other)
        ]
        if nearby_semantic_rows:
            _suppress_visual_toc_semantic_row(row)

def _demote_visual_toc_rows_after_back_matter_start(rows: list[dict]) -> None:
    back_matter_rows = [
        row
        for row in rows
        if str(row.get("role_hint") or "") == "back_matter"
        and int(row.get("page_no") or 0) > 0
    ]
    if not back_matter_rows:
        return
    first_back_matter_page = min(int(row.get("page_no") or 0) for row in back_matter_rows)
    back_matter_title_keys = {
        _semantic_visual_toc_title_key(str(row.get("title") or ""))
        for row in back_matter_rows
        if _semantic_visual_toc_title_key(str(row.get("title") or ""))
    }
    for row in rows:
        if int(row.get("page_no") or 0) < first_back_matter_page:
            continue
        if str(row.get("role_hint") or "") not in {"chapter", "section"}:
            continue
        parent_key = _semantic_visual_toc_title_key(str(row.get("parent_title") or ""))
        if parent_key and parent_key not in back_matter_title_keys:
            continue
        _suppress_visual_toc_semantic_row(row, role_hint="back_matter")

def _sanitize_visual_toc_semantic_rows(rows: list[dict]) -> list[dict]:
    sanitized = [dict(row) for row in rows or []]
    _suppress_visual_toc_composite_root_duplicates(sanitized)
    _merge_visual_toc_split_heading_rows(sanitized)
    _suppress_visual_toc_prefixed_duplicates(sanitized)
    _suppress_visual_toc_numeric_root_noise(sanitized)
    _demote_visual_toc_rows_after_back_matter_start(sanitized)
    return sanitized

def _compact_unique_titles(values: list[str]) -> list[str]:
    compact: list[str] = []
    seen: set[str] = set()
    for title in values:
        normalized = _normalize_title(title)
        if not normalized:
            continue
        key = _chapter_title_match_key(normalized) or normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        compact.append(normalized)
    return compact

def _resolve_visual_toc_page_by_heading_only(
    *,
    title: str,
    page_role_by_no: dict[int, str],
    heading_candidates: list[dict] | None,
) -> tuple[int, bool]:
    title_key = _chapter_title_match_key(title)
    if not title_key:
        return 0, False
    candidates: list[tuple[int, int, int]] = []
    for candidate in heading_candidates or []:
        page_no = int(candidate.get("page_no") or 0)
        if page_no <= 0:
            continue
        candidate_text = str(candidate.get("text") or "")
        if _chapter_title_match_key(candidate_text) != title_key:
            continue
        page_role = str(page_role_by_no.get(page_no) or "")
        if page_role in {"note", "other", "noise"}:
            continue
        score = 0
        if page_role == "body":
            score += 300
        elif page_role == "front_matter":
            score += 120
        source = str(candidate.get("source") or "")
        if source == "ocr_block" and str(candidate.get("block_label") or "") == "doc_title":
            score += 36
        elif source == "markdown_heading":
            score += 30
        elif source == "pdf_font_band":
            score += 24
        elif source == "visual_toc":
            score += 10
        family = str(candidate.get("heading_family_guess") or "")
        if family in {"chapter", "book"}:
            score += 18
        elif family == "section":
            score += 10
        if bool(candidate.get("top_band")):
            score += 8
        score += int(round(float(candidate.get("confidence") or 0.0) * 10))
        candidates.append((score, -page_no, page_no))
    if not candidates:
        return 0, False
    candidates.sort(reverse=True)
    return int(candidates[0][2]), True

def _visual_toc_chapter_level_style(chapter_level_rows: list[dict]) -> dict[str, bool]:
    has_lecture = any(
        bool(_LECTURE_TITLE_RE.search(str(row.get("title") or "")))
        for row in chapter_level_rows or []
    )
    numbered_count = sum(
        1
        for row in chapter_level_rows or []
        if bool(_MAIN_NUMBERED_TITLE_RE.search(_normalize_title(str(row.get("title") or ""))))
    )
    return {
        "lecture": has_lecture,
        "numbered": numbered_count >= max(2, len(chapter_level_rows or []) // 2),
    }

def _is_misleveled_chapter_row(row: dict, chapter_style: dict[str, bool]) -> bool:
    title = _normalize_title(str(row.get("title") or ""))
    if not title:
        return False
    if chapter_style.get("lecture") and _LECTURE_TITLE_RE.search(title):
        return True
    if chapter_style.get("numbered") and _MAIN_NUMBERED_TITLE_RE.search(title):
        return True
    return False

def _looks_like_lecture_collection(
    body_rows: list[dict],
    heading_candidates: list[dict] | None,
) -> bool:
    lecture_title_keys = {
        _chapter_title_match_key(str(row.get("title") or ""))
        for row in body_rows or []
        if _LECTURE_TITLE_RE.search(str(row.get("title") or ""))
    }
    lecture_title_keys.update(
        _chapter_title_match_key(str(candidate.get("text") or ""))
        for candidate in heading_candidates or []
        if _LECTURE_TITLE_RE.search(str(candidate.get("text") or ""))
        and int(candidate.get("page_no") or 0) > 0
    )
    has_course_cover = any(
        bool(_LECTURE_COLLECTION_EXCLUDED_TITLE_RE.match(_normalize_title(str(row.get("title") or ""))))
        for row in body_rows or []
    )
    return has_course_cover and len({key for key in lecture_title_keys if key}) >= 4

def _normalize_lecture_title_and_suffix(title: str) -> tuple[str, bool]:
    normalized = _normalize_title(title)
    if not normalized or not _LECTURE_TITLE_RE.search(normalized):
        return normalized, False
    match = _LECTURE_TRAILING_PAGE_SUFFIX_RE.match(normalized)
    if not match:
        return normalized, False
    candidate = _normalize_title(str(match.group("title") or ""))
    if not candidate:
        return normalized, False
    # 仅在标题里已包含年份时，才把末尾数字视作目录页码噪声并剥离。
    if not re.search(r"\b(?:19|20)\d{2}\b", candidate):
        return normalized, False
    return candidate, True

def _normalize_lecture_title(title: str) -> str:
    normalized, _ = _normalize_lecture_title_and_suffix(title)
    return normalized

def _preferred_lecture_heading_title(
    *,
    title: str,
    page_no: int,
    heading_candidates: list[dict] | None,
) -> str:
    normalized_title = _normalize_lecture_title(title)
    fallback_title = normalized_title.upper() if _LECTURE_TITLE_RE.search(normalized_title) else normalized_title
    title_key = _chapter_title_match_key(normalized_title)
    if page_no <= 0 or not title_key:
        return fallback_title

    candidates: list[tuple[int, str]] = []
    for candidate in heading_candidates or []:
        candidate_page = int(candidate.get("page_no") or 0)
        candidate_text = _normalize_lecture_title(str(candidate.get("text") or ""))
        if candidate_page != int(page_no) or not candidate_text:
            continue
        if _chapter_title_match_key(candidate_text) != title_key:
            continue
        if not _LECTURE_TITLE_RE.search(candidate_text):
            continue
        source = str(candidate.get("source") or "")
        score = 0
        if source == "ocr_block" and str(candidate.get("block_label") or "") == "doc_title":
            score += 40
        elif source == "markdown_heading":
            score += 30
        elif source == "pdf_font_band":
            score += 20
        else:
            continue
        if bool(candidate.get("top_band")):
            score += 10
        if str(candidate.get("heading_family_guess") or "") == "chapter":
            score += 8
        score += int(round(float(candidate.get("confidence") or 0.0) * 10))
        candidates.append((score, candidate_text))
    if not candidates:
        return fallback_title
    candidates.sort(reverse=True)
    return _normalize_lecture_title(candidates[0][1])

def _build_lecture_collection_chapter_rows(
    *,
    body_rows: list[dict],
    heading_candidates: list[dict] | None,
    page_role_by_no: dict[int, str],
    chapter_level: int,
) -> list[dict]:
    lecture_rows = []
    for row in body_rows or []:
        page_no = int(row.get("page_no") or 0)
        raw_title = str(row.get("title") or "")
        title, had_suffix = _normalize_lecture_title_and_suffix(raw_title)
        if page_no <= 0:
            continue
        if not _LECTURE_TITLE_RE.search(title):
            continue
        if _LECTURE_COLLECTION_EXCLUDED_TITLE_RE.match(_normalize_title(title)):
            continue
        normalized_row = dict(row)
        normalized_row["title"] = _preferred_lecture_heading_title(
            title=title,
            page_no=page_no,
            heading_candidates=heading_candidates,
        )
        normalized_row["_lecture_title_had_suffix"] = bool(had_suffix)
        lecture_rows.append(normalized_row)
    selected_by_title: dict[str, dict] = {}

    def _lecture_row_rank(row: dict) -> tuple[int, int, int]:
        title_penalty = 0 if bool(row.get("_lecture_title_had_suffix")) else 1
        resolved_score = 1 if bool(row.get("resolved_via_heading")) else 0
        page_role = str(row.get("page_role") or "")
        page_role_score = 2 if page_role == "body" else (1 if page_role == "front_matter" else 0)
        return (title_penalty, resolved_score, page_role_score)

    for row in lecture_rows:
        title_key = _chapter_title_match_key(str(row.get("title") or ""))
        if not title_key:
            continue
        existing = selected_by_title.get(title_key)
        if existing is None or _lecture_row_rank(row) > _lecture_row_rank(existing):
            selected_by_title[title_key] = row

    lecture_rows = sorted(
        selected_by_title.values(),
        key=lambda row: (
            int(row.get("page_no") or 0) if int(row.get("page_no") or 0) > 0 else 10**9,
            int(row.get("order") or 0),
        ),
    )
    seen_keys = {_visual_toc_row_key(row) for row in lecture_rows}
    seen_title_keys = {_chapter_title_match_key(str(row.get("title") or "")) for row in lecture_rows}
    supplemental_rows: list[dict] = []
    for candidate in heading_candidates or []:
        page_no = int(candidate.get("page_no") or 0)
        source = str(candidate.get("source") or "")
        family = str(candidate.get("heading_family_guess") or "")
        title = _normalize_lecture_title(str(candidate.get("text") or ""))
        if page_no <= 0 or not title or not _LECTURE_TITLE_RE.search(title):
            continue
        if source not in {"ocr_block", "markdown_heading", "pdf_font_band"}:
            continue
        if family not in {"chapter", "book"}:
            continue
        if _LECTURE_COLLECTION_EXCLUDED_TITLE_RE.match(title):
            continue
        if str(page_role_by_no.get(page_no) or "") not in {"body", "front_matter"}:
            continue
        title_key = _chapter_title_match_key(title)
        if not title_key or title_key in seen_title_keys:
            continue
        row = {
            "title": title,
            "page_no": page_no,
            "level": int(chapter_level),
            "order": 10**6 + page_no,
            "item_id": f"lecture-heading-{page_no:04d}-{_chapter_title_match_key(title)[:24]}",
            "family": "body",
            "page_role": str(page_role_by_no.get(page_no) or ""),
            "non_body_title": False,
            "resolved_via_heading": True,
            "semantic_role": "chapter",
        }
        key = _visual_toc_row_key(row)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        seen_title_keys.add(title_key)
        supplemental_rows.append(row)
    rows = _dedupe_visual_toc_rows(lecture_rows + supplemental_rows)
    for row in rows:
        row.pop("_lecture_title_had_suffix", None)
    return rows

def _lecture_collection_boundary_pages(
    *,
    body_rows: list[dict],
    heading_candidates: list[dict] | None,
    page_role_by_no: dict[int, str],
) -> set[int]:
    boundary_pages: set[int] = set()
    for row in body_rows or []:
        title = _normalize_title(str(row.get("title") or ""))
        page_no = int(row.get("page_no") or 0)
        if page_no > 0 and _LECTURE_COLLECTION_BOUNDARY_TITLE_RE.match(title):
            boundary_pages.add(page_no)
    for candidate in heading_candidates or []:
        title = _normalize_title(str(candidate.get("text") or ""))
        page_no = int(candidate.get("page_no") or 0)
        if page_no <= 0 or not _LECTURE_COLLECTION_BOUNDARY_TITLE_RE.match(title):
            continue
        if str(page_role_by_no.get(page_no) or "") not in {"body", "front_matter"}:
            continue
        boundary_pages.add(page_no)
    return boundary_pages

def _visual_toc_semantic_role(
    row: dict,
    *,
    chapter_level: int,
    total_pages: int,
) -> str:
    title = _normalize_title(str(row.get("title") or ""))
    if not title:
        return "unknown"
    lowered = title.lower()
    page_no = int(row.get("page_no") or 0)
    page_role = str(row.get("page_role") or "")
    explicit_role = _normalize_visual_toc_role_hint(row.get("role_hint") or "")
    if explicit_role == "container":
        return "part"
    if explicit_role == "endnotes":
        return "endnotes"
    if (
        explicit_role == "back_matter"
        and re.match(r"^(?:appendix|appendices|annex(?:es)?)\b", lowered, re.IGNORECASE)
        and page_no > 0
        and page_role not in {"note", "noise"}
    ):
        return "post_body"
    if explicit_role in {"chapter", "section", "post_body", "back_matter", "front_matter"}:
        return explicit_role
    level = int(row.get("level") or 0)
    family = str(row.get("family") or "")
    if bool(row.get("non_body_title")) or family in _TOC_EXCLUDED_FAMILIES:
        if _NOTES_HEADER_RE.match(title):
            return "endnotes"
        if re.search(
            r"^(?:acknowledg(?:e)?ments?|remerciements?|list of abbreviations|liste des abr[eé]viations|list of illustrations|liste des illustrations)\b",
            lowered,
            re.IGNORECASE,
        ):
            return "front_matter"
        return "back_matter"
    if _is_toc_part_title(title):
        return "part"
    if _NOTES_HEADER_RE.match(title):
        return "endnotes"
    if _is_visual_toc_explicit_chapter_title(title):
        return "chapter"
    if page_role == "front_matter" and level <= int(chapter_level):
        if _uppercase_ratio(title) >= 0.7 and len(title.split()) <= 8:
            return "book_title"
        return "front_matter"
    if level > int(chapter_level):
        return "section"
    if level == int(chapter_level):
        return "chapter"
    if _is_toc_body_anchor_title(title):
        return "chapter"
    if page_role in {"body", "front_matter"}:
        return "section"
    return "unknown"

def _resolve_visual_toc_target_page(
    *,
    title: str,
    resolved_page: int,
    page_role_by_no: dict[int, str],
    heading_candidates: list[dict] | None,
) -> tuple[int, bool]:
    target_page = int(resolved_page or 0)
    if target_page <= 0:
        return 0, False
    title_key = _chapter_title_match_key(title)
    if not title_key:
        return target_page, False

    candidates: list[tuple[int, int, int, int]] = []
    current_has_exact_heading = False
    for candidate in heading_candidates or []:
        page_no = int(candidate.get("page_no") or 0)
        if page_no <= 0:
            continue
        candidate_text = str(candidate.get("text") or "")
        if _chapter_title_match_key(candidate_text) != title_key:
            continue
        if page_no == target_page and str(candidate.get("source") or "") != "visual_toc":
            current_has_exact_heading = True
        page_role = str(page_role_by_no.get(page_no) or "")
        if page_role in {"note", "other", "noise"}:
            continue
        score = 0
        if page_role == "body":
            score += 300
        elif page_role == "front_matter":
            score += 120
        source = str(candidate.get("source") or "")
        if source == "ocr_block" and str(candidate.get("block_label") or "") == "doc_title":
            score += 36
        elif source == "markdown_heading":
            score += 30
        elif source == "pdf_font_band":
            score += 24
        elif source == "visual_toc":
            score += 10
        family = str(candidate.get("heading_family_guess") or "")
        if family in {"chapter", "book"}:
            score += 18
        elif family == "section":
            score += 10
        if bool(candidate.get("top_band")):
            score += 8
        score += int(round(float(candidate.get("confidence") or 0.0) * 10))
        distance = abs(page_no - target_page)
        candidates.append((score, -distance, -page_no, page_no))

    if not candidates:
        return target_page, False
    candidates.sort(reverse=True)
    best_page = int(candidates[0][3])
    current_role = str(page_role_by_no.get(target_page) or "")
    best_role = str(page_role_by_no.get(best_page) or "")
    should_replace = (
        current_role in {"noise", "other", "note"}
        or (not current_has_exact_heading and best_page != target_page)
        or (best_role == "body" and current_role != "body")
        or (
            current_role == "front_matter"
            and best_role == "body"
            and _is_toc_body_anchor_title(title)
        )
    )
    if should_replace and best_page != target_page:
        return best_page, True
    return target_page, False

def _collect_visual_toc_rows(
    page_rows: list[dict],
    *,
    toc_items: list[dict] | None,
    visual_toc_bundle: Mapping[str, Any] | None = None,
    toc_offset: int,
    heading_candidates: list[dict] | None = None,
) -> list[dict]:
    source_items = list((visual_toc_bundle or {}).get("items") or toc_items or [])
    if not source_items:
        return []
    raw_pages = [dict(row.get("_page") or {}) for row in page_rows or []]
    page_role_by_no = {
        int(row.get("page_no") or 0): str(row.get("page_role") or "")
        for row in page_rows or []
    }
    file_idx_map = _build_pdf_page_by_file_idx(raw_pages)
    total_pages = max(1, len(page_rows or []))
    rows: list[dict] = []
    for index, item in enumerate(source_items, start=1):
        title = _normalize_visual_toc_item_title(item.get("title") or "")
        if not title:
            continue
        page_no = resolve_toc_item_target_pdf_page(
            item,
            offset=int(toc_offset or 0),
            pages=raw_pages,
            pdf_page_by_file_idx=file_idx_map,
        )
        resolved_page = int(_safe_int(page_no) or 0)
        resolved_via_heading = False
        if resolved_page > 0:
            resolved_page, resolved_via_heading = _resolve_visual_toc_target_page(
                title=title,
                resolved_page=resolved_page,
                page_role_by_no=page_role_by_no,
                heading_candidates=heading_candidates,
            )
        if resolved_page <= 0:
            resolved_page, resolved_via_heading = _resolve_visual_toc_page_by_heading_only(
                title=title,
                page_role_by_no=page_role_by_no,
                heading_candidates=heading_candidates,
            )
        role = str(page_role_by_no.get(int(resolved_page)) or "") if resolved_page > 0 else ""
        family = _title_family(title, page_no=int(resolved_page), total_pages=total_pages)
        row = {
            "item_id": str(item.get("item_id") or ""),
            "title": title,
            "page_no": int(resolved_page),
            "level": _visual_toc_level(item),
            "page_role": role,
            "family": family,
            "non_body_title": bool(_TOC_NON_BODY_TITLE_RE.match(title)),
            "order": index,
            "resolved_via_heading": bool(resolved_via_heading),
            "unresolved_page": bool(resolved_page <= 0),
            "explicit_role_hint": _normalize_visual_toc_role_hint(item.get("role_hint") or ""),
            "role_hint": _normalize_visual_toc_role_hint(item.get("role_hint") or ""),
            "parent_title": _normalize_visual_toc_item_title(str(item.get("parent_title") or "")),
        }
        if "body_candidate" in item:
            row["body_candidate"] = bool(item.get("body_candidate"))
        if "export_candidate" in item:
            row["export_candidate"] = bool(item.get("export_candidate"))
        rows.append(row)

    child_page_by_parent: dict[str, int] = {}
    for row in rows:
        parent_title = _normalize_title(str(row.get("parent_title") or ""))
        page_no = int(row.get("page_no") or 0)
        if not parent_title or page_no <= 0:
            continue
        existing = int(child_page_by_parent.get(parent_title) or 0)
        if existing <= 0 or page_no < existing:
            child_page_by_parent[parent_title] = page_no

    for row in rows:
        role_hint = _normalize_visual_toc_role_hint(row.get("role_hint") or "")
        page_no = int(row.get("page_no") or 0)
        if page_no > 0 or role_hint not in {"container", "endnotes", "post_body", "back_matter", "front_matter"}:
            continue
        synthetic_page = int(child_page_by_parent.get(str(row.get("title") or "")) or 0)
        if synthetic_page <= 0:
            continue
        row["page_no"] = synthetic_page
        row["page_role"] = str(page_role_by_no.get(synthetic_page) or "")
        row["family"] = _title_family(
            str(row.get("title") or ""),
            page_no=synthetic_page,
            total_pages=total_pages,
        )
        row["unresolved_page"] = False
    rows.sort(
        key=lambda row: (
            int(row.get("page_no") or 0) if int(row.get("page_no") or 0) > 0 else 10**9,
            int(row.get("order") or 0),
        )
    )
    return rows

def _choose_visual_toc_chapter_level(rows: list[dict]) -> int | None:
    candidates = [row for row in rows if _is_visual_toc_body_candidate(row)]
    if not candidates:
        return None
    levels = sorted({int(row.get("level") or 0) for row in candidates if int(row.get("level") or 0) > 0})
    if not levels:
        return None
    chapter_level = levels[0]
    base_count = sum(1 for row in candidates if int(row.get("level") or 0) == chapter_level)
    if base_count <= 2:
        for level in levels[1:]:
            level_count = sum(1 for row in candidates if int(row.get("level") or 0) == level)
            if level_count >= 3:
                chapter_level = level
                break
    return chapter_level

def _build_visual_toc_chapters_and_section_heads(
    *,
    page_rows: list[dict],
    toc_items: list[dict] | None,
    visual_toc_bundle: Mapping[str, Any] | None = None,
    toc_offset: int,
    heading_candidates: list[dict],
) -> tuple[list[dict], list[dict], dict[str, Any]]:
    source_items = list((visual_toc_bundle or {}).get("items") or toc_items or [])
    rows = _sanitize_visual_toc_semantic_rows(
        _collect_visual_toc_rows(
            page_rows,
            toc_items=source_items,
            visual_toc_bundle=visual_toc_bundle,
            toc_offset=toc_offset,
            heading_candidates=heading_candidates,
        )
    )

    root_container_present = any(
        int(row.get("level") or 0) == 1
        and (
            str(row.get("role_hint") or "").strip().lower() == "container"
            or _is_toc_part_title(str(row.get("title") or ""))
        )
        for row in rows
    )
    if root_container_present:
        for index, row in enumerate(rows):
            if int(row.get("level") or 0) != 1:
                continue
            if str(row.get("parent_title") or "").strip():
                continue
            explicit_role_hint = str(row.get("explicit_role_hint") or "").strip().lower()
            if str(row.get("role_hint") or "").strip().lower() not in {"", "chapter"}:
                continue
            if explicit_role_hint:
                continue
            title = str(row.get("title") or "").strip()
            if len(title.split()) < 6:
                continue
            if _is_toc_part_title(title) or _is_visual_toc_explicit_chapter_title(title):
                continue
            has_later_root_container = any(
                int(later.get("level") or 0) == 1
                and (
                    str(later.get("role_hint") or "").strip().lower() == "container"
                    or _is_toc_part_title(str(later.get("title") or ""))
                )
                for later in rows[index + 1:]
            )
            if not has_later_root_container:
                continue
            row["role_hint"] = "front_matter"
            row["body_candidate"] = False
            row["export_candidate"] = False
    has_toc_items = bool(source_items)

    def _compact_unique_titles(values: list[str]) -> list[str]:
        compact: list[str] = []
        seen: set[str] = set()
        for title in values:
            normalized = _normalize_title(title)
            if not normalized:
                continue
            key = _chapter_title_match_key(normalized) or normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            compact.append(normalized)
        return compact

    def _empty_meta(
        *,
        chapter_level: int | None,
        missing_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        missing_preview = _compact_unique_titles(list(missing_titles or []))[:8]
        chapter_title_alignment_ok = not has_toc_items
        chapter_section_alignment_ok = not has_toc_items
        toc_semantic_contract_ok = True
        if missing_preview:
            chapter_title_alignment_ok = False
            chapter_section_alignment_ok = False
        return {
            "used": False,
            "chapter_level": chapter_level,
            "visual_toc_conflict_count": 0,
            "normalized_toc_rows": [],
            "toc_export_coverage_summary": {
                "resolved_body_items": 0,
                "exported_body_items": 0,
                "missing_body_items_preview": list(missing_preview),
            },
            "toc_alignment_summary": {
                "chapter_level_body_items": 0,
                "exported_chapter_count": 0,
                "missing_chapter_titles_preview": list(missing_preview),
                "misleveled_titles_preview": [],
                "reanchored_titles_preview": [],
                "missing_section_titles_preview": [],
            },
            "toc_semantic_summary": {
                "body_item_count": 0,
                "chapter_item_count": 0,
                "part_item_count": 0,
                "back_matter_item_count": 0,
                "first_body_pdf_page": 0,
                "last_body_pdf_page": 0,
                "body_span_ratio": 0.0,
                "nonbody_contamination_count": 0,
                "mixed_level_chapter_count": 0,
            },
            "toc_semantic_contract_ok": bool(toc_semantic_contract_ok),
            "toc_semantic_blocking_reasons": [],
            "heading_graph_summary": default_heading_graph_summary(),
            "toc_role_summary": {
                "container": 0,
                "endnotes": 0,
                "chapter": 0,
                "section": 0,
                "post_body": 0,
                "back_matter": 0,
                "front_matter": 0,
            },
            "container_titles": [],
            "endnotes_titles": [],
            "post_body_titles": [],
            "back_matter_titles": [],
            "chapter_title_alignment_ok": bool(chapter_title_alignment_ok),
            "chapter_section_alignment_ok": bool(chapter_section_alignment_ok),
            "chapter_source_summary": {
                "source": "legacy",
                "chapter_level": chapter_level,
                "visual_toc_chapter_count": 0,
                "legacy_chapter_count": 0,
                "fallback_used": True,
            },
        }

    if not rows:
        missing = [
            _normalize_title(item.get("title") or "")
            for item in source_items
            if _normalize_title(item.get("title") or "")
            and not _TOC_NON_BODY_TITLE_RE.match(_normalize_title(item.get("title") or ""))
        ]
        return [], [], _empty_meta(chapter_level=None, missing_titles=missing)

    chapter_level = _choose_visual_toc_chapter_level(rows)
    if chapter_level is None:
        missing = [
            str(row.get("title") or "")
            for row in rows
            if _is_visual_toc_body_candidate(row)
        ]
        return [], [], _empty_meta(chapter_level=None, missing_titles=missing)

    total_pages = max(1, len(page_rows or []))
    for row in rows:
        row["semantic_role"] = _visual_toc_semantic_role(
            row,
            chapter_level=int(chapter_level),
            total_pages=total_pages,
        )
        if str(row.get("semantic_role") or "") == "post_body" and row.get("export_candidate") is False:
            row["export_candidate"] = True
    toc_role_summary = {
        "container": 0,
        "endnotes": 0,
        "chapter": 0,
        "section": 0,
        "post_body": 0,
        "back_matter": 0,
        "front_matter": 0,
    }
    container_titles_raw: list[str] = []
    post_body_titles_raw: list[str] = []
    back_matter_titles_raw: list[str] = []

    def _toc_role_from_semantic_role(row: dict) -> str:
        semantic_role = str(row.get("semantic_role") or "")
        if semantic_role in {"part", "book_title"}:
            return "container"
        if semantic_role == "endnotes":
            return "endnotes"
        if semantic_role == "chapter":
            return "chapter"
        if semantic_role == "section":
            return "section"
        if semantic_role == "post_body":
            return "post_body"
        if semantic_role == "back_matter":
            return "back_matter"
        if semantic_role == "front_matter":
            return "front_matter"
        return ""

    for row in rows:
        mapped_role = _toc_role_from_semantic_role(row)
        if not mapped_role:
            continue
        toc_role_summary[mapped_role] += 1
        title = str(row.get("title") or "")
        if mapped_role == "container":
            container_titles_raw.append(title)
        elif mapped_role == "endnotes":
            pass
        elif mapped_role == "post_body":
            post_body_titles_raw.append(title)
        elif mapped_role == "back_matter":
            back_matter_titles_raw.append(title)
    container_titles = _compact_unique_titles(container_titles_raw)[:8]
    post_body_titles = _compact_unique_titles(post_body_titles_raw)[:8]
    back_matter_titles = _compact_unique_titles(back_matter_titles_raw)[:8]
    body_rows = [row for row in rows if _is_visual_toc_body_candidate(row)]
    has_explicit_organization = bool(
        container_titles
        or post_body_titles
        or back_matter_titles
        or any(str(row.get("parent_title") or "").strip() for row in rows)
        or any(
            str(row.get("role_hint") or "").strip().lower()
            in {"container", "endnotes", "chapter", "section", "post_body", "back_matter", "front_matter"}
            for row in rows
        )
    )
    chapter_level_rows = [
        row for row in body_rows
        if int(row.get("level") or 0) == int(chapter_level)
    ]
    part_rows_at_chapter_level = [
        row
        for row in chapter_level_rows
        if str(row.get("semantic_role") or "") == "part"
    ]
    numbered_rows_deeper = [
        row
        for row in body_rows
        if int(row.get("level") or 0) > int(chapter_level)
        and bool(_MAIN_NUMBERED_TITLE_RE.search(_normalize_title(str(row.get("title") or ""))))
    ]
    prefer_deeper_numbered = bool(part_rows_at_chapter_level and len(numbered_rows_deeper) >= 3)
    chapter_style = _visual_toc_chapter_level_style(
        [row for row in chapter_level_rows if int(row.get("page_no") or 0) > 0]
    )
    force_export_rows = [
        row for row in body_rows
        if int(row.get("level") or 0) != int(chapter_level)
        and _is_toc_force_export_title(str(row.get("title") or ""))
    ]
    misleveled_rows = [
        row for row in body_rows
        if int(row.get("level") or 0) > int(chapter_level)
        and not bool(row.get("non_body_title"))
        and not _is_toc_force_export_title(str(row.get("title") or ""))
    ]
    corrected_chapter_rows = [
        row for row in misleveled_rows
        if _is_misleveled_chapter_row(row, chapter_style)
    ]
    explicit_chapter_rows = [
        row
        for row in body_rows
        if _is_visual_toc_explicit_chapter_title(str(row.get("title") or ""))
    ]
    page_role_by_no = {
        int(row.get("page_no") or 0): str(row.get("page_role") or "")
        for row in page_rows or []
        if int(row.get("page_no") or 0) > 0
    }
    lecture_collection_override = _looks_like_lecture_collection(body_rows, heading_candidates)
    if prefer_deeper_numbered:
        baseline_chapter_rows = [
            row
            for row in chapter_level_rows
            if _is_toc_force_export_title(str(row.get("title") or ""))
        ]
    else:
        baseline_chapter_rows = list(chapter_level_rows)

    explicit_export_chapter_rows = _dedupe_visual_toc_rows(
        [
            row
            for row in rows
            if str(row.get("semantic_role") or "") == "chapter"
            and int(row.get("page_no") or 0) > 0
            and row.get("export_candidate") is not False
        ]
    )
    if has_explicit_organization:
        chapter_rows = list(explicit_export_chapter_rows)
    else:
        chapter_rows = _dedupe_visual_toc_rows(
            baseline_chapter_rows + force_export_rows + corrected_chapter_rows + explicit_chapter_rows
        )
        chapter_rows = [
            row for row in chapter_rows
            if str(row.get("semantic_role") or "") == "chapter"
        ]
        if lecture_collection_override:
            chapter_rows = _build_lecture_collection_chapter_rows(
                body_rows=body_rows,
                heading_candidates=heading_candidates,
                page_role_by_no=page_role_by_no,
                chapter_level=int(chapter_level),
            )
    chapter_rows.sort(
        key=lambda row: (
            int(row.get("page_no") or 0) if int(row.get("page_no") or 0) > 0 else 10**9,
            int(row.get("order") or 0),
        )
    )
    post_body_rows = _dedupe_visual_toc_rows(
        [
            row for row in rows
            if str(row.get("semantic_role") or "") == "post_body"
            and int(row.get("page_no") or 0) > 0
            and row.get("export_candidate") is not False
        ]
    )
    post_body_rows.sort(
        key=lambda row: (
            int(row.get("page_no") or 0) if int(row.get("page_no") or 0) > 0 else 10**9,
            int(row.get("order") or 0),
        )
    )

    first_body_chapter_page = min(
        (
            int(row.get("page_no") or 0)
            for row in chapter_rows
            if int(row.get("page_no") or 0) > 0
            and _title_family(
                str(row.get("title") or ""),
                page_no=int(row.get("page_no") or 0),
                total_pages=total_pages,
            ) == "body"
        ),
        default=0,
    )
    if first_body_chapter_page > 0:
        chapter_rows = [
            row for row in chapter_rows
            if _title_family(
                str(row.get("title") or ""),
                page_no=int(row.get("page_no") or 0),
                total_pages=total_pages,
            ) != "front_matter"
            or _is_toc_force_export_title(str(row.get("title") or ""))
            or int(row.get("page_no") or 0) < first_body_chapter_page
        ]
    exportable_chapter_rows = _dedupe_visual_toc_rows(
        chapter_rows + post_body_rows
    )
    exportable_chapter_rows = [
        row for row in exportable_chapter_rows
        if int(row.get("page_no") or 0) > 0
    ]
    exportable_chapter_rows.sort(
        key=lambda row: (
            int(row.get("page_no") or 0) if int(row.get("page_no") or 0) > 0 else 10**9,
            int(row.get("order") or 0),
        )
    )
    exported_title_keys = {
        _semantic_visual_toc_title_key(str(row.get("title") or ""))
        for row in exportable_chapter_rows
        if _semantic_visual_toc_title_key(str(row.get("title") or ""))
    }
    if exported_title_keys:
        container_titles = [
            title
            for title in container_titles
            if _semantic_visual_toc_title_key(title) not in exported_title_keys
        ]
    heading_graph_rows, heading_graph_summary = build_heading_graph(
        exportable_rows=exportable_chapter_rows,
        heading_candidates=heading_candidates,
        page_rows=page_rows,
    )
    heading_graph_incomplete = bool(heading_graph_summary.get("unresolved_titles_preview"))
    heading_graph_boundary_conflict = bool(heading_graph_summary.get("boundary_conflict_titles_preview"))
    if not heading_graph_incomplete and not heading_graph_boundary_conflict:
        anchored_rows: list[dict] = []
        for row, graph_row in zip(exportable_chapter_rows, heading_graph_rows):
            anchored = dict(row)
            anchor_page = int(graph_row.get("anchor_page") or anchored.get("page_no") or 0)
            if anchor_page > 0:
                anchored["page_no"] = anchor_page
                anchored["resolved_via_heading"] = bool(
                    anchored.get("resolved_via_heading") or str(graph_row.get("anchor_state") or "") == "resolved"
                )
            anchored_rows.append(anchored)
        exportable_chapter_rows = anchored_rows

    page_row_by_no = {
        int(row.get("page_no") or 0): row
        for row in page_rows or []
        if int(row.get("page_no") or 0) > 0
    }
    eligible_pages_all = [
        int(row.get("page_no") or 0)
        for row in page_rows or []
        if int(row.get("page_no") or 0) > 0
        and str(row.get("page_role") or "") in {"body", "front_matter"}
    ]
    if not eligible_pages_all:
        eligible_pages_all = [
            int(row.get("page_no") or 0)
            for row in page_rows or []
            if int(row.get("page_no") or 0) > 0
        ]
    if not eligible_pages_all or not exportable_chapter_rows:
        missing = [
            str(row.get("title") or "")
            for row in chapter_rows
            if str(row.get("title") or "").strip()
        ]
        return [], [], _empty_meta(chapter_level=int(chapter_level), missing_titles=missing)
    max_page_no = max(eligible_pages_all)
    extra_boundary_pages = (
        _lecture_collection_boundary_pages(
            body_rows=body_rows,
            heading_candidates=heading_candidates,
            page_role_by_no=page_role_by_no,
        )
        if lecture_collection_override
        else set()
    )
    nonchapter_stop_pages = {
        int(row.get("page_no") or 0)
        for row in rows
        if int(row.get("page_no") or 0) > 0
        and str(row.get("semantic_role") or "") in {"endnotes", "back_matter"}
    }
    exportable_chapter_start_pages = {
        int(row.get("page_no") or 0)
        for row in exportable_chapter_rows
        if int(row.get("page_no") or 0) > 0
    }
    rear_nonbody_stop_pages = {
        int(row.get("page_no") or 0)
        for row in page_rows or []
        if int(row.get("page_no") or 0) >= int(first_body_chapter_page or 0)
        and int(row.get("page_no") or 0) not in exportable_chapter_start_pages
        and str(row.get("page_role") or "") == "other"
        and str(row.get("role_reason") or "")
        in {
            "appendix",
            "bibliography",
            "index",
            "illustrations",
            "rear_toc_tail",
            "rear_author_blurb",
            "rear_sparse_other",
        }
    }
    chapter_boundary_pages = sorted(
        {
            int(row.get("page_no") or 0)
            for row in exportable_chapter_rows
            if int(row.get("page_no") or 0) > 0
        }
        | {int(page_no) for page_no in extra_boundary_pages if int(page_no) > 0}
        | nonchapter_stop_pages
        | rear_nonbody_stop_pages
    )

    chapters: list[dict] = []
    for index, row in enumerate(exportable_chapter_rows, start=1):
        start_page = int(row.get("page_no") or 0)
        next_start_page = next(
            (page_no for page_no in chapter_boundary_pages if int(page_no) > int(start_page)),
            max_page_no + 1,
        )
        raw_span_pages = [
            page_no for page_no in eligible_pages_all
            if int(start_page) <= int(page_no) < int(next_start_page)
        ]
        body_span_pages = [
            page_no
            for page_no in raw_span_pages
            if str(page_role_by_no.get(int(page_no)) or "") == "body"
        ]
        if (
            str(page_role_by_no.get(int(start_page)) or "") == "front_matter"
            and _is_toc_force_export_title(str(row.get("title") or ""))
            and raw_span_pages
        ):
            span_pages = raw_span_pages
        else:
            span_pages = body_span_pages or raw_span_pages
        span_pages = _trim_exportable_chapter_pages(
            span_pages,
            page_by_no=page_row_by_no,
            total_pages=total_pages,
        )
        if not span_pages:
            span_pages = [start_page]
        chapters.append(
            {
                "chapter_id": _normalize_toc_chapter_id(
                    row.get("item_id"),
                    order=index,
                    title=str(row.get("title") or ""),
                ),
                "title": str(row.get("title") or ""),
                "start_page": int(span_pages[0]),
                "end_page": int(span_pages[-1]),
                "pages": list(span_pages),
                "source": "visual_toc",
                "boundary_state": "ready",
            }
        )

    visual_toc_conflict_count = 0
    for chapter in chapters:
        chapter_page = int(chapter.get("start_page") or 0)
        if _visual_toc_chapter_keyword_strength(str(chapter.get("title") or "")) < 1:
            continue
        chapter_key = _chapter_title_match_key(chapter.get("title") or "")
        strong_candidates = [
            row for row in heading_candidates or []
            if str(row.get("source") or "") in {"ocr_block", "pdf_font_band"}
            and str(row.get("heading_family_guess") or "") == "chapter"
            and not bool(row.get("suppressed_as_chapter"))
            and bool(row.get("top_band"))
            and (
                str(row.get("source") or "") != "ocr_block"
                or str(row.get("block_label") or "") == "doc_title"
            )
            and _visual_toc_chapter_keyword_strength(str(row.get("text") or "")) >= 1
            and float(row.get("confidence") or 0.0) >= 0.68
            and int(row.get("page_no") or 0) == chapter_page
        ]
        if len(strong_candidates) != 1:
            continue
        candidate_key = _chapter_title_match_key(str(strong_candidates[0].get("text") or ""))
        if not chapter_key or not candidate_key:
            continue
        if candidate_key == chapter_key:
            continue
        if chapter_key in candidate_key or candidate_key in chapter_key:
            continue
        chapter["boundary_state"] = "review_required"
        visual_toc_conflict_count += 1

    section_heads: list[dict] = []
    chapter_row_keys = {
        _visual_toc_row_key(row)
        for row in exportable_chapter_rows
    }
    if has_explicit_organization:
        section_target_rows = _dedupe_visual_toc_rows(
            [
                row
                for row in rows
                if int(row.get("page_no") or 0) > 0
                and not bool(row.get("non_body_title"))
                and bool(row.get("body_candidate"))
                and _visual_toc_row_key(row) not in chapter_row_keys
                and str(row.get("semantic_role") or "") == "section"
            ]
        )
    else:
        section_target_rows = _dedupe_visual_toc_rows(
            [
                row for row in rows
                if _is_visual_toc_body_candidate(row)
                and int(row.get("page_no") or 0) > 0
                and not bool(row.get("non_body_title"))
                and _visual_toc_row_key(row) not in chapter_row_keys
                and (
                    str(row.get("semantic_role") or "") in {"section", "part"}
                    or int(row.get("level") or 0) > int(chapter_level)
                )
            ]
        )
    seen_head_keys: set[tuple[str, int, str]] = set()
    covered_section_row_keys: set[tuple[int, str]] = set()
    for row in section_target_rows:
        chapter_id = _find_chapter_by_page(chapters, int(row.get("page_no") or 0))
        if not chapter_id:
            continue
        text = _normalize_title(row.get("title") or "")
        if not text:
            continue
        key = (chapter_id, int(row.get("page_no") or 0), _chapter_title_match_key(text))
        if key in seen_head_keys:
            continue
        seen_head_keys.add(key)
        covered_section_row_keys.add(_visual_toc_row_key(row))
        section_heads.append(
            {
                "section_head_id": "",
                "chapter_id": chapter_id,
                "page_no": int(row.get("page_no") or 0),
                "text": text,
                "normalized_text": _normalize_title(text),
                "source": "visual_toc",
                "confidence": 0.98,
                "heading_family_guess": "section",
                "rejected_chapter_candidate": False,
                "reject_reason": "",
                "derived_from_heading_id": "",
            }
        )

    missing_chapter_titles_preview = _compact_unique_titles(
        [
            str(row.get("title") or "")
            for row in chapter_rows
            if int(row.get("page_no") or 0) <= 0
        ]
    )[:8]
    missing_section_titles_preview = _compact_unique_titles(
        [
            str(row.get("title") or "")
            for row in section_target_rows
            if _visual_toc_row_key(row) not in covered_section_row_keys
        ]
    )[:8]
    misleveled_titles_preview = _compact_unique_titles(
        [str(row.get("title") or "") for row in misleveled_rows]
    )[:8]
    reanchored_titles_preview = _compact_unique_titles(
        [
            str(row.get("title") or "")
            for row in rows
            if bool(row.get("resolved_via_heading"))
            and int(row.get("page_no") or 0) > 0
        ]
    )[:8]

    chapter_title_alignment_ok = bool(
        not missing_chapter_titles_preview
        and len(chapters) == len(exportable_chapter_rows)
        and [
            _chapter_title_match_key(str(chapter.get("title") or ""))
            for chapter in chapters
        ] == [
            _visual_toc_title_key(row)
            for row in exportable_chapter_rows
        ]
    )
    chapter_section_alignment_ok = bool(not missing_section_titles_preview)
    semantic_role_counts = Counter(
        str(row.get("semantic_role") or "unknown")
        for row in body_rows
    )
    semantic_body_pages = sorted(
        {
            int(row.get("page_no") or 0)
            for row in body_rows
            if int(row.get("page_no") or 0) > 0
            and str(row.get("semantic_role") or "") in {"chapter", "section", "part"}
        }
    )
    first_body_pdf_page = int(semantic_body_pages[0]) if semantic_body_pages else 0
    last_body_pdf_page = int(semantic_body_pages[-1]) if semantic_body_pages else 0
    body_span_ratio = (
        float(last_body_pdf_page - first_body_pdf_page + 1) / float(total_pages)
        if first_body_pdf_page > 0 and last_body_pdf_page >= first_body_pdf_page and total_pages > 0
        else 0.0
    )
    nonbody_contamination_count = sum(
        1
        for row in chapter_rows
        if str(row.get("semantic_role") or "") != "chapter"
    )
    chapter_row_keys = {
        _visual_toc_row_key(row)
        for row in chapter_rows
    }
    mixed_level_chapter_count = (
        1
        if (
            part_rows_at_chapter_level
            and numbered_rows_deeper
            and any(_visual_toc_row_key(row) in chapter_row_keys for row in part_rows_at_chapter_level)
        )
        else 0
    )
    partial_tail_capture = bool(
        first_body_pdf_page > max(24, int(total_pages * 0.45))
        and body_span_ratio < 0.55
        and len(chapter_rows) <= max(6, len(body_rows))
    )
    toc_semantic_blocking_reasons: list[str] = []
    if partial_tail_capture:
        toc_semantic_blocking_reasons.append("toc_partial_tail_capture")
    if nonbody_contamination_count > 0:
        toc_semantic_blocking_reasons.append("toc_nonbody_as_chapter")
    if mixed_level_chapter_count > 0:
        toc_semantic_blocking_reasons.append("toc_mixed_part_and_chapter_levels")
    if heading_graph_incomplete:
        toc_semantic_blocking_reasons.append("heading_graph_incomplete")
    if heading_graph_boundary_conflict:
        toc_semantic_blocking_reasons.append("heading_graph_boundary_conflict")
    toc_semantic_contract_ok = bool(not toc_semantic_blocking_reasons)
    normalized_toc_rows = [
        {
            "item_id": str(row.get("item_id") or ""),
            "title": str(row.get("title") or ""),
            "page_no": int(row.get("page_no") or 0),
            "level": int(row.get("level") or 1),
            "order": int(row.get("order") or 0),
            "semantic_role": str(row.get("semantic_role") or ""),
            "role_hint": str(row.get("role_hint") or ""),
            "parent_title": str(row.get("parent_title") or ""),
            "source": "visual_toc",
        }
        for row in rows
        if str(row.get("title") or "").strip()
    ]

    return chapters, section_heads, {
        "used": True,
        "chapter_level": int(chapter_level),
        "visual_toc_conflict_count": int(visual_toc_conflict_count),
        "normalized_toc_rows": normalized_toc_rows,
        "toc_export_coverage_summary": {
            "resolved_body_items": len(exportable_chapter_rows),
            "exported_body_items": len(chapters),
            "missing_body_items_preview": list(missing_chapter_titles_preview),
        },
        "toc_alignment_summary": {
            "chapter_level_body_items": len(chapter_level_rows),
            "exported_chapter_count": len(chapters),
            "missing_chapter_titles_preview": list(missing_chapter_titles_preview),
            "misleveled_titles_preview": list(misleveled_titles_preview),
            "reanchored_titles_preview": list(reanchored_titles_preview),
            "missing_section_titles_preview": list(missing_section_titles_preview),
        },
        "toc_semantic_summary": {
            "body_item_count": int(sum(semantic_role_counts.values())),
            "chapter_item_count": int(semantic_role_counts.get("chapter", 0)),
            "part_item_count": int(semantic_role_counts.get("part", 0)),
            "endnotes_item_count": int(semantic_role_counts.get("endnotes", 0)),
            "back_matter_item_count": int(semantic_role_counts.get("back_matter", 0)),
            "first_body_pdf_page": int(first_body_pdf_page),
            "last_body_pdf_page": int(last_body_pdf_page),
            "body_span_ratio": round(float(body_span_ratio), 4),
            "nonbody_contamination_count": int(nonbody_contamination_count),
            "mixed_level_chapter_count": int(mixed_level_chapter_count),
        },
        "toc_semantic_contract_ok": bool(toc_semantic_contract_ok),
        "toc_semantic_blocking_reasons": list(toc_semantic_blocking_reasons),
        "heading_graph_summary": dict(heading_graph_summary or {}),
        "toc_role_summary": toc_role_summary,
        "container_titles": container_titles,
        "endnotes_titles": _compact_unique_titles(
            [str(row.get("title") or "") for row in rows if str(row.get("semantic_role") or "") == "endnotes"]
        )[:8],
        "post_body_titles": post_body_titles,
        "back_matter_titles": back_matter_titles,
        "chapter_title_alignment_ok": bool(chapter_title_alignment_ok),
        "chapter_section_alignment_ok": bool(chapter_section_alignment_ok),
        "chapter_source_summary": {
            "source": "visual_toc",
            "chapter_level": int(chapter_level),
            "visual_toc_chapter_count": len(chapters),
            "legacy_chapter_count": 0,
            "fallback_used": False,
        },
    }

def _endnote_subentry_match_mode(title: str) -> str:
    normalized = normalize_title(title)
    if not normalized:
        return "unknown"
    lowered = normalized.lower()
    if re.match(r"^\s*notes?\s+to\s+\S+", lowered):
        return "named"
    if _ENDNOTE_NAMED_SUBENTRY_RE.match(lowered):
        return "named"
    if _ENDNOTE_NUMBERED_SUBENTRY_RE.match(lowered):
        return "numbered"
    if chapter_title_match_key(normalized):
        return "chapter_title"
    return "unknown"

def _resolve_endnotes_book_page(
    *,
    endnotes_summary: dict[str, Any],
    bundle_items: list[dict[str, Any]],
) -> int:
    """解析尾注容器的真实 bookPage，优先用 file_idx 映射，其次用 book_page 字段。

    不能直接用 container_printed_page，因为它是目录 PDF 上的印刷页码（如 331），
    与 doc.db 的 bookPage（如 348）存在 17-18 页的前言偏移。
    """
    container_title = normalize_title(str(endnotes_summary.get("container_title") or ""))
    if not container_title:
        return int(endnotes_summary.get("container_printed_page") or 0)
    for item in bundle_items:
        if str(item.get("role_hint") or "").strip().lower() != "endnotes":
            continue
        item_title = normalize_title(str(item.get("title") or ""))
        if item_title != container_title:
            continue
        book_page = item.get("book_page")
        if book_page is not None and int(book_page) > 0:
            return int(book_page)
        file_idx = item.get("file_idx")
        if file_idx is not None and int(file_idx) >= 0:
            return int(file_idx) + 1
        break
    return int(endnotes_summary.get("container_printed_page") or 0)


def _build_endnote_explorer_hints(
    *,
    visual_toc_bundle: Mapping[str, Any] | None,
    normalized_toc_rows: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    endnotes_summary = dict((visual_toc_bundle or {}).get("endnotes_summary") or {})
    present = bool(endnotes_summary.get("present"))
    container_title = normalize_title(str(endnotes_summary.get("container_title") or ""))
    bundle_items = list((visual_toc_bundle or {}).get("items") or [])
    container_start_page_hint = _resolve_endnotes_book_page(
        endnotes_summary=endnotes_summary,
        bundle_items=bundle_items,
    )
    source_rows = bundle_items if bundle_items else list(normalized_toc_rows or [])
    toc_subentries: list[dict[str, Any]] = []

    if present and container_title:
        for row in source_rows:
            title = normalize_title(str(row.get("title") or ""))
            parent_title = normalize_title(str(row.get("parent_title") or ""))
            if not title or parent_title != container_title:
                continue
            explicit_role = str(row.get("role_hint") or row.get("semantic_role") or "").strip().lower()
            if explicit_role in {"container", "endnotes", "front_matter", "back_matter"}:
                continue
            toc_subentries.append(
                {
                    "title": title,
                    "printed_page": int(row.get("printed_page") or row.get("page_no") or 0),
                    "visual_order": int(row.get("visual_order") or row.get("order") or 0),
                    "match_mode": _endnote_subentry_match_mode(title),
                }
            )
    toc_subentries.sort(key=lambda item: (int(item.get("printed_page") or 0) <= 0, int(item.get("printed_page") or 0), int(item.get("visual_order") or 0), str(item.get("title") or "")))
    return {
        "endnotes_summary": endnotes_summary,
        "container_start_page_hint": int(container_start_page_hint or 0),
        "container_title": container_title,
        "has_toc_subentries": bool(toc_subentries),
        "toc_subentries": toc_subentries,
    }

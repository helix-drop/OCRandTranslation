"""章节骨架：heading candidate 收集与归一。"""

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

def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _normalize_font_weight_hint(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"regular", "bold", "heavy", "unknown"}:
        return token
    return "unknown"

def _normalize_align_hint(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"left", "center", "right", "unknown"}:
        return token
    return "unknown"

def _width_ratio(width_estimate: Any, page_width: Any) -> float | None:
    width = _safe_float(width_estimate)
    total = _safe_float(page_width)
    if width is None or total is None or total <= 0:
        return None
    ratio = width / total
    return max(0.0, min(1.0, ratio))

def _align_hint(x: Any, width_estimate: Any, page_width: Any) -> str:
    left = _safe_float(x)
    width = _safe_float(width_estimate)
    total = _safe_float(page_width)
    if left is None or width is None or total is None or total <= 0:
        return "unknown"
    right = left + width
    center = left + (width / 2.0)
    page_center = total / 2.0
    if abs(center - page_center) <= max(40.0, total * 0.08):
        return "center"
    if left <= total * 0.18:
        return "left"
    if right >= total * 0.82:
        return "right"
    return "unknown"

def _heading_level_hint(
    *,
    source: str,
    block_label: str = "",
    top_band: bool = False,
    markdown_level: int = 0,
) -> int:
    normalized_source = str(source or "").strip().lower()
    normalized_label = str(block_label or "").strip().lower()
    if normalized_source == "visual_toc":
        return 1
    if normalized_source == "note_heading":
        return 0
    if normalized_source == "ocr_block":
        if normalized_label == "doc_title":
            return 1 if top_band else 2
        if normalized_label == "paragraph_title":
            return 2
    if normalized_source == "markdown_heading":
        return max(1, int(markdown_level or 1))
    if normalized_source == "pdf_font_band":
        return 1 if top_band else 2
    return 0

def _build_pdf_page_by_file_idx(pages: list[dict]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for page in pages:
        try:
            file_idx = int(page.get("fileIdx"))
            page_no = int(page.get("bookPage"))
        except (TypeError, ValueError):
            continue
        if file_idx >= 0 and page_no > 0:
            mapping[file_idx] = page_no
    return mapping

def _legacy_page_rows(page_partitions: list[PagePartitionRecord], pages: list[dict] | None) -> list[dict]:
    page_by_no: dict[int, dict] = {}
    for page in pages or []:
        try:
            page_no = int(page.get("bookPage") or 0)
        except (TypeError, ValueError):
            continue
        if page_no > 0:
            page_by_no[page_no] = dict(page)
    rows: list[dict] = []
    for row in sorted(page_partitions, key=lambda item: item.page_no):
        rows.append(
            {
                "page_no": int(row.page_no),
                "target_pdf_page": int(row.target_pdf_page),
                "page_role": str(row.page_role),
                "role_confidence": float(row.confidence),
                "role_reason": str(row.reason),
                "section_hint": str(row.section_hint),
                "has_note_heading": bool(row.has_note_heading),
                "note_scan_summary": dict(row.note_scan_summary),
                "_page": dict(page_by_no.get(int(row.page_no), {})),
            }
        )
    return rows

def _heading_family_guess(
    text: str,
    *,
    page_no: int,
    total_pages: int,
    page_role: str,
    source: str,
    block_label: str = "",
    top_band: bool = False,
) -> str:
    title = normalize_title(text)
    if not title:
        return "other"
    if _NOTES_HEADER_RE.match(title):
        return "note"
    family = str(guess_title_family(title, page_no=max(1, page_no), total_pages=max(1, total_pages)) or "body")
    if source == "visual_toc":
        return "chapter"
    if source == "note_heading":
        return "note"
    if family in _FAMILY_NONBODY:
        return family
    if page_role == "front_matter" and family == "front_matter":
        return "front_matter"
    if block_label == "doc_title" and top_band:
        return "chapter"
    if _CHAPTER_KEYWORD_RE.search(title):
        return "chapter"
    return "section" if source in {"markdown_heading", "ocr_block", "pdf_font_band"} else "chapter"

def _append_heading_candidate(
    target: list[dict],
    dedupe: dict[tuple[int, str, str, str], int],
    *,
    page_no: int,
    text: str,
    source: str,
    block_label: str = "",
    top_band: bool = False,
    confidence: float = 0.0,
    heading_family_guess: str = "",
    font_height: float | None = None,
    x: float | None = None,
    y: float | None = None,
    width_estimate: float | None = None,
    font_name: str = "",
    font_weight_hint: str = "unknown",
    align_hint: str = "unknown",
    width_ratio: float | None = None,
    heading_level_hint: int = 0,
) -> None:
    normalized_text = normalize_title(text)
    if not normalized_text:
        return
    key = (
        int(page_no),
        str(source).strip().lower(),
        chapter_title_match_key(normalized_text),
        str(block_label or "").strip().lower(),
    )
    payload = {
        "heading_id": "",
        "page_no": int(page_no),
        "text": normalized_text,
        "normalized_text": normalized_text,
        "source": str(source).strip().lower(),
        "block_label": str(block_label or "").strip().lower(),
        "top_band": bool(top_band),
        "font_height": _safe_float(font_height),
        "x": _safe_float(x),
        "y": _safe_float(y),
        "width_estimate": _safe_float(width_estimate),
        "font_name": str(font_name or ""),
        "font_weight_hint": _normalize_font_weight_hint(font_weight_hint),
        "align_hint": _normalize_align_hint(align_hint),
        "width_ratio": _safe_float(width_ratio),
        "heading_level_hint": max(0, int(heading_level_hint or 0)),
        "confidence": float(confidence or 0.0),
        "heading_family_guess": str(heading_family_guess or ""),
        "suppressed_as_chapter": False,
        "reject_reason": "",
    }
    if key not in dedupe:
        dedupe[key] = len(target)
        target.append(payload)
        return
    current = target[dedupe[key]]
    replace = False
    if float(payload.get("confidence") or 0.0) > float(current.get("confidence") or 0.0):
        replace = True
    if bool(payload.get("top_band")) and not bool(current.get("top_band")):
        replace = True
    if replace:
        payload["heading_id"] = str(current.get("heading_id") or "")
        target[dedupe[key]] = payload

def _collect_page_heading_candidates(page_rows: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    dedupe: dict[tuple[int, str, str, str], int] = {}
    total_pages = max(1, len(page_rows or []))
    for row in page_rows or []:
        page_no = int(row.get("page_no") or 0)
        if page_no <= 0:
            continue
        page_role = str(row.get("page_role") or "")
        page = dict(row.get("_page") or {})
        page_h = _safe_float((dict(page.get("prunedResult") or {})).get("height")) or 1200.0
        page_w = _safe_float((dict(page.get("prunedResult") or {})).get("width")) or 1000.0
        for block in page_blocks(page):
            label = str(block.get("block_label") or "").strip().lower()
            if label not in {"doc_title", "paragraph_title"}:
                continue
            text = normalize_title(block.get("block_content") or "")
            if not text:
                continue
            bbox = list(block.get("block_bbox") or [])
            left = _safe_float(bbox[0]) if len(bbox) >= 1 else None
            top = _safe_float(bbox[1]) if len(bbox) >= 2 else None
            right = _safe_float(bbox[2]) if len(bbox) >= 3 else None
            bottom = _safe_float(bbox[3]) if len(bbox) >= 4 else None
            width = max(0.0, (right or 0.0) - (left or 0.0)) if left is not None and right is not None else None
            font_h = max(0.0, (bottom or 0.0) - (top or 0.0)) if top is not None and bottom is not None else None
            top_band = bool(top is not None and top <= page_h * 0.30)
            confidence = 0.72 if label == "doc_title" else 0.58
            if top_band:
                confidence += 0.12
            family = _heading_family_guess(
                text,
                page_no=page_no,
                total_pages=total_pages,
                page_role=page_role,
                source="ocr_block",
                block_label=label,
                top_band=top_band,
            )
            _append_heading_candidate(
                candidates,
                dedupe,
                page_no=page_no,
                text=text,
                source="ocr_block",
                block_label=label,
                top_band=top_band,
                confidence=confidence,
                heading_family_guess=family,
                font_height=font_h,
                x=left,
                y=top,
                width_estimate=width,
                align_hint=_align_hint(left, width, page_w),
                width_ratio=_width_ratio(width, page_w),
                heading_level_hint=_heading_level_hint(
                    source="ocr_block",
                    block_label=label,
                    top_band=top_band,
                ),
            )
        markdown = page_markdown_text(page)
        for index, raw_line in enumerate(markdown.splitlines()[:12]):
            line = str(raw_line or "").strip()
            if not line:
                continue
            if _NOTES_HEADER_RE.match(line):
                family = _heading_family_guess(
                    line,
                    page_no=page_no,
                    total_pages=total_pages,
                    page_role=page_role,
                    source="note_heading",
                    top_band=index <= 3,
                )
                _append_heading_candidate(
                    candidates,
                    dedupe,
                    page_no=page_no,
                    text=line,
                    source="note_heading",
                    top_band=index <= 3,
                    confidence=0.96,
                    heading_family_guess=family,
                    heading_level_hint=0,
                )
                continue
            match = _MARKDOWN_HEADING_RE.match(raw_line)
            if not match:
                continue
            heading = normalize_title(match.group(1))
            if not heading:
                continue
            markdown_prefix = re.match(r"^\s{0,3}(#{1,6})", str(raw_line or ""))
            markdown_level = len(markdown_prefix.group(1)) if markdown_prefix else 1
            family = _heading_family_guess(
                heading,
                page_no=page_no,
                total_pages=total_pages,
                page_role=page_role,
                source="markdown_heading",
                top_band=index <= 2,
            )
            _append_heading_candidate(
                candidates,
                dedupe,
                page_no=page_no,
                text=heading,
                source="markdown_heading",
                top_band=index <= 2,
                confidence=0.62 if index <= 2 else 0.54,
                heading_family_guess=family,
                heading_level_hint=_heading_level_hint(
                    source="markdown_heading",
                    top_band=index <= 2,
                    markdown_level=markdown_level,
                ),
            )
    return candidates

def _collect_toc_heading_candidates(
    page_rows: list[dict],
    *,
    toc_items: list[dict] | None,
    toc_offset: int,
) -> list[dict]:
    if not toc_items:
        return []
    raw_pages = [dict(row.get("_page") or {}) for row in page_rows]
    file_idx_map = _build_pdf_page_by_file_idx(raw_pages)
    page_role_by_no = {int(row.get("page_no") or 0): str(row.get("page_role") or "") for row in page_rows}
    total_pages = max(1, len(page_rows or []))
    candidates: list[dict] = []
    dedupe: dict[tuple[int, str, str, str], int] = {}
    for item in toc_items or []:
        title = normalize_title(item.get("title") or "")
        if not title:
            continue
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
        family = _heading_family_guess(
            title,
            page_no=resolved_page,
            total_pages=total_pages,
            page_role=page_role_by_no.get(resolved_page, ""),
            source="visual_toc",
            top_band=True,
        )
        _append_heading_candidate(
            candidates,
            dedupe,
            page_no=resolved_page,
            text=title,
            source="visual_toc",
            top_band=True,
            confidence=1.0,
            heading_family_guess=family,
            heading_level_hint=1,
        )
    return candidates

def _collect_pdf_font_band_candidates(
    page_rows: list[dict],
    heading_candidates: list[dict],
    *,
    pdf_path: str,
    toc_items: list[dict] | None,
    toc_offset: int,
) -> list[dict]:
    path = Path(str(pdf_path or "").strip())
    if not path.exists() or not path.is_file():
        return []
    candidate_pages: set[int] = {
        int(row.get("page_no") or 0)
        for row in heading_candidates
        if int(row.get("page_no") or 0) > 0
    }
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
            resolved = int(page_no)
        except (TypeError, ValueError):
            continue
        if resolved > 0:
            candidate_pages.add(resolved)
    if not candidate_pages:
        return []
    try:
        file_bytes = path.read_bytes()
    except OSError:
        return []
    pdf_pages = extract_pdf_text(file_bytes)
    if not pdf_pages:
        return []
    page_role_by_no = {int(row.get("page_no") or 0): str(row.get("page_role") or "") for row in page_rows}
    total_pages = max(1, len(page_rows))
    file_idx_to_page_no = _build_pdf_page_by_file_idx(raw_pages)
    candidates: list[dict] = []
    dedupe: dict[tuple[int, str, str, str], int] = {}
    for page in pdf_pages:
        file_idx = int(page.get("pageIdx") or -1)
        page_no = int(file_idx_to_page_no.get(file_idx) or 0)
        if page_no <= 0 or page_no not in candidate_pages:
            continue
        pdf_w = _safe_float(page.get("pdfW")) or 0.0
        pdf_h = _safe_float(page.get("pdfH")) or 0.0
        items = sorted(
            list(page.get("items") or []),
            key=lambda item: (_safe_float(item.get("y")) or 10**9, -(_safe_float(item.get("h")) or 0.0)),
        )
        if not items:
            continue
        top_limit = (pdf_h * 0.28) if pdf_h > 0 else 240.0
        mid_limit = (pdf_h * 0.55) if pdf_h > 0 else 520.0

        def _rank_item(item: dict, *, top_band: bool) -> tuple[float, float, float]:
            text = normalize_title(item.get("str") or "")
            font_weight_hint = _normalize_font_weight_hint(item.get("font_weight_hint"))
            align_hint = _align_hint(item.get("x"), item.get("w"), pdf_w)
            weight_score = 0.0
            if font_weight_hint == "heavy":
                weight_score = 2.0
            elif font_weight_hint == "bold":
                weight_score = 1.2
            elif font_weight_hint == "regular":
                weight_score = 0.4
            length_penalty = min(2.4, max(0.0, (len(text) - 48) * 0.03))
            center_bonus = 0.8 if align_hint == "center" else 0.0
            top_bonus = 0.9 if top_band else 0.0
            return (
                weight_score + center_bonus + top_bonus - length_penalty,
                -(_safe_float(item.get("y")) or 0.0),
                -len(text),
            )

        top_items = [
            item for item in items[:80]
            if (_safe_float(item.get("y")) or 10**9) <= top_limit
            and normalize_title(item.get("str") or "")
            and len(normalize_title(item.get("str") or "")) <= 160
        ]
        mid_items = [
            item for item in items[:120]
            if top_limit < (_safe_float(item.get("y")) or 10**9) <= mid_limit
            and normalize_title(item.get("str") or "")
            and len(normalize_title(item.get("str") or "")) <= 160
            and _normalize_font_weight_hint(item.get("font_weight_hint")) in {"bold", "heavy"}
        ]
        selected_items = sorted(top_items, key=lambda item: _rank_item(item, top_band=True), reverse=True)[:3]
        selected_items.extend(
            sorted(mid_items, key=lambda item: _rank_item(item, top_band=False), reverse=True)[:2]
        )
        for item in selected_items:
            text = normalize_title(item.get("str") or "")
            if not text:
                continue
            top_band = bool((_safe_float(item.get("y")) or 10**9) <= top_limit)
            font_height = _safe_float(item.get("h")) or 0.0
            font_name = str(item.get("font_name") or "")
            font_weight_hint = _normalize_font_weight_hint(item.get("font_weight_hint"))
            align_hint = _align_hint(item.get("x"), item.get("w"), pdf_w)
            confidence = 0.52
            if top_band:
                confidence += 0.12
            if font_weight_hint in {"bold", "heavy"}:
                confidence += 0.12
            if align_hint == "center":
                confidence += 0.08
            family = _heading_family_guess(
                text,
                page_no=page_no,
                total_pages=total_pages,
                page_role=page_role_by_no.get(page_no, ""),
                source="pdf_font_band",
                top_band=top_band,
            )
            _append_heading_candidate(
                candidates,
                dedupe,
                page_no=page_no,
                text=text,
                source="pdf_font_band",
                top_band=top_band,
                confidence=confidence,
                heading_family_guess=family,
                font_height=font_height,
                x=_safe_float(item.get("x")),
                y=_safe_float(item.get("y")),
                width_estimate=_safe_float(item.get("w")),
                font_name=font_name,
                font_weight_hint=font_weight_hint,
                align_hint=align_hint,
                width_ratio=_width_ratio(item.get("w"), pdf_w),
                heading_level_hint=_heading_level_hint(source="pdf_font_band", top_band=top_band),
            )
    return candidates

def _collect_heading_candidate_rows(
    page_rows: list[dict],
    *,
    toc_items: list[dict] | None,
    toc_offset: int,
    pdf_path: str,
) -> list[dict]:
    candidates: list[dict] = []
    candidates.extend(_collect_page_heading_candidates(page_rows))
    candidates.extend(_collect_toc_heading_candidates(page_rows, toc_items=toc_items, toc_offset=toc_offset))
    candidates.extend(
        _collect_pdf_font_band_candidates(
            page_rows,
            candidates,
            pdf_path=pdf_path,
            toc_items=toc_items,
            toc_offset=toc_offset,
        )
    )
    candidates.sort(
        key=lambda item: (
            int(item.get("page_no") or 0),
            str(item.get("source") or ""),
            str(item.get("text") or ""),
        )
    )
    for index, item in enumerate(candidates, start=1):
        item["heading_id"] = f"hd-{index:05d}"
    return candidates

def _is_sentence_like_heading(title: str) -> bool:
    text = normalize_title(title)
    words = [part for part in text.split() if part]
    if len(words) < 8:
        return False
    if any(ch in text for ch in ".;:?!"):
        return True
    lower_words = sum(1 for word in words if word[:1].islower())
    return lower_words >= max(3, len(words) // 2)

def _chapter_keyword_strength(title: str) -> float:
    text = normalize_title(title)
    if not text:
        return 0.0
    hits = len(_CHAPTER_KEYWORD_RE.findall(text))
    if hits >= 2:
        return 2.0
    if hits == 1:
        return 1.0
    return 0.0

def _normalize_heading_candidates(candidate_rows: list[dict]) -> list[HeadingCandidate]:
    normalized: list[HeadingCandidate] = []
    candidate_rows.sort(
        key=lambda item: (
            int(item.get("page_no") or 0),
            str(item.get("source") or ""),
            str(item.get("text") or ""),
        )
    )
    for index, row in enumerate(candidate_rows, start=1):
        heading_id = str(row.get("heading_id") or f"hd-{index:05d}")
        normalized_text = normalize_title(row.get("normalized_text") or row.get("text") or "")
        text = normalize_title(row.get("text") or normalized_text)
        if not text:
            continue
        normalized.append(
            HeadingCandidate(
                heading_id=heading_id,
                page_no=int(row.get("page_no") or 0),
                text=text,
                normalized_text=normalized_text or text,
                source=str(row.get("source") or ""),
                block_label=str(row.get("block_label") or ""),
                top_band=bool(row.get("top_band")),
                confidence=float(row.get("confidence") or 0.0),
                heading_family_guess=str(row.get("heading_family_guess") or ""),
                suppressed_as_chapter=bool(row.get("suppressed_as_chapter")),
                reject_reason=str(row.get("reject_reason") or ""),
                font_height=_safe_float(row.get("font_height")),
                x=_safe_float(row.get("x")),
                y=_safe_float(row.get("y")),
                width_estimate=_safe_float(row.get("width_estimate")),
                font_name=str(row.get("font_name") or ""),
                font_weight_hint=_normalize_font_weight_hint(row.get("font_weight_hint")),
                align_hint=_normalize_align_hint(row.get("align_hint")),
                width_ratio=_safe_float(row.get("width_ratio")),
                heading_level_hint=max(0, int(row.get("heading_level_hint") or 0)),
            )
        )
    return normalized

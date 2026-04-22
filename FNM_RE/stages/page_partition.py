"""FNM_RE 第一阶段：页面分区。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from document.note_detection import annotate_pages_with_note_scans

from FNM_RE.constants import PageRole, is_valid_page_role
from FNM_RE.models import PagePartitionRecord
from FNM_RE.shared.text import (
    extract_page_headings,
    first_section_hint,
    has_note_heading,
    note_scan_summary,
    page_markdown_text,
)
from FNM_RE.shared.title import guess_title_family, normalize_title

_ARCHIVE_NOISE_RE = re.compile(
    r"(digitized by the internet archive|the quick brown fox)",
    re.IGNORECASE,
)
_NOTES_HEADER_RE = re.compile(r"^\s*(?:#+\s*)?(notes?|endnotes?|notes to pages?.*)\s*$", re.IGNORECASE)

_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s*(.+?)\s*$")
_NOTE_DEF_RE = re.compile(r"^\s*(\d{1,4}[A-Za-z]?)\s*[\.,\)\]]\s*(.*\S.*)?$")
_NOTE_DEF_OCR_SPLIT_RE = re.compile(r"^\s*(\d{1,4}[A-Za-z]?)\s+[Il1]\s*[\.,\)\]]\s*(.*\S.*)?$")
_LEADING_OCR_NOTE_PUNCT_RE = re.compile(r"^[\.,:;·•]+\s*(?=\d)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TOC_LINE_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*|[A-Za-z]?\d+(?:\.\d+)*)[\.\)]?\s+.+?\s+\d+\s*$")
_FIGURE_LIST_LINE_RE = re.compile(r"^\s*(?:fig(?:ure)?\.?|table|appendix)\s*[A-Za-z0-9\.\-]*\s+.+?\s+\d+\s*$", re.IGNORECASE)
_DOT_LEADER_RE = re.compile(r"\.{3,}\s*(?:\d{1,4})?\s*$")
_LECTURE_TITLE_RE = re.compile(r"\ble[cç]on du\b", re.IGNORECASE)
_TABLE_TOC_HEADING_RE = re.compile(r"^(?:table|table des mati[eè]res|sommaire)\b", re.IGNORECASE)
_YEAR_RANGE_RE = re.compile(r"(?:\(|\b)(\d{4})\s*-\s*(\d{4})(?:\)|\b)")
_YEAR_TOKEN_RE = re.compile(r"\b(?:1[6-9]\d{2}|20\d{2})\b")
_BIBLIO_AUTHOR_ENTRY_RE = re.compile(
    r"(?:^|[.;]\s+)(?:[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'’\-]+(?:,\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'’\-]+){0,2},)",
)
_BIBLIO_CITATION_HINT_RE = re.compile(
    r"\b(?:Paris|Gallimard|Vrin|Press|University Press|trad\.?|pp\.|vol\.|n°|coll\.|"
    r"Éditions?|Mercure de France|Cahiers du Sud|Rivages|Belin|Flammarion|Archimbaud)\b",
    re.IGNORECASE,
)
_INDEX_ENTRY_RE = re.compile(
    r"(?:^|[\n])\s*[A-ZÀ-ÖØ-Þ][^:\n]{1,120}:\s*\d{1,4}(?:[-–]\d{1,4})?(?:,\s*\d{1,4}(?:[-–]\d{1,4})?){0,12}\.?",
    re.MULTILINE,
)
_ILLUSTRATION_CONTENT_RE = re.compile(
    r"(?:©|cm\b|mus[ée]e|biblioth[eè]que|gravure|huile|lithograph|dessin|eau-forte|collection)",
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

_CHAPTER_KEYWORD_RE = re.compile(
    r"\b(chapter|chapitre|lecture|lesson|le[cç]on|prologue|epilogue)\b"
    r"|^\s*(?:part|partie|livre|book)\s+(?:[ivxlcm]+|\d+)\b",
    re.IGNORECASE,
)
_MAIN_NUMBERED_TITLE_RE = re.compile(
    r"^(?:chapter\s+)?(?:\d+|[IVXLCMivxlcm]+)[\.\):\-]?\s+\S+",
    re.IGNORECASE,
)
_TOC_FORCE_EXPORT_TITLE_RE = re.compile(
    r"^\s*(?:introduction|avertissement|pr[eé]face|foreword|epilogue|conclusion)\b",
    re.IGNORECASE,
)
_TOC_EXPLICIT_CHAPTER_TITLE_RE = re.compile(
    r"^(?:chapter|chapitre)\b|^(?:\d+|[ivxlcm]+)[\.\):\-]\s+\S+|\ble[cç]on du\b|\bcours\b|\bprologue\b|\bepilogue\b|\bconclusion\b",
    re.IGNORECASE,
)

_NOTE_REF_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("generic", re.compile(r"\{\{NOTE_REF:([^}]+)\}\}")),
    ("footnote", re.compile(r"\{\{FN_REF:([^}]+)\}\}")),
    ("endnote", re.compile(r"\{\{EN_REF:([^}]+)\}\}")),
    ("endnote", re.compile(r"\[\^(en-[^\]]+)\]", re.IGNORECASE)),
    ("endnote", re.compile(r"\[EN-([^\]]+)\]", re.IGNORECASE)),
    ("footnote", re.compile(r"\[FN-([^\]]+)\]", re.IGNORECASE)),
    ("footnote", re.compile(r"\[\^((?!en-)[^\]]+)\]", re.IGNORECASE)),
)


def _strip_markdown_heading(text: str) -> str:
    value = str(text or "")
    match = _MARKDOWN_HEADING_RE.match(value)
    if match:
        value = match.group(2)
    return normalize_title(value)


def _note_kind_from_id(note_id: str) -> str:
    label = str(note_id or "").strip().lower()
    if label.startswith("en-"):
        return "endnote"
    return "footnote"


def _extract_note_refs(text: str) -> list[dict[str, str]]:
    content = str(text or "")
    matches: list[tuple[int, str, str]] = []
    for kind, pattern in _NOTE_REF_PATTERNS:
        for match in pattern.finditer(content):
            note_id = str(match.group(1) or "").strip()
            if note_id:
                resolved_kind = _note_kind_from_id(note_id) if kind == "generic" else kind
                matches.append((match.start(), resolved_kind, note_id))
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _pos, kind, note_id in sorted(matches, key=lambda item: item[0]):
        key = (kind, note_id)
        if key in seen:
            continue
        seen.add(key)
        refs.append({"kind": kind, "note_id": note_id})
    return refs


def _plain_text_lines(text: str) -> list[str]:
    raw = _HTML_TAG_RE.sub(" ", str(text or ""))
    return [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines() if re.sub(r"\s+", " ", line).strip()]


def _uppercase_ratio(text: str) -> float:
    letters = [ch for ch in str(text or "") if ch.isalpha()]
    if not letters:
        return 0.0
    uppers = sum(1 for ch in letters if ch.isupper())
    return uppers / max(1, len(letters))


def _markdown_body_after_first_heading(text: str) -> str:
    raw_lines = str(text or "").splitlines()
    if not raw_lines:
        return ""
    if _MARKDOWN_HEADING_RE.match(str(raw_lines[0] or "").strip()):
        return "\n".join(raw_lines[1:]).strip()
    return str(text or "").strip()


def _looks_like_prose_after_heading(text: str) -> bool:
    body = _markdown_body_after_first_heading(text).strip()
    if not body:
        return False
    if _extract_note_refs(body):
        return True
    if re.search(r"\^\{\d+\}|\$\s*\^\{\d+\}\s*\$|<sup>\s*\d+\s*</sup>", body):
        return True
    lines = _plain_text_lines(body)[:10]
    if not lines:
        return False
    sentence_like = sum(1 for line in lines if len(line) >= 40 and re.search(r"[.!?。！？]", line))
    short_sentence_like = sum(1 for line in lines if len(line) >= 10 and re.search(r"[.!?。！？]", line))
    long_lines = sum(1 for line in lines if len(line) >= 60)
    medium_lines = sum(1 for line in lines if len(line) >= 30)
    mixed_case_lines = sum(1 for line in lines if re.search(r"[a-zà-ÿ]", line))
    total_chars = sum(len(line) for line in lines[:6])
    return bool(
        long_lines >= 2
        or (long_lines >= 1 and medium_lines >= 3)
        or sentence_like >= 2
        or (sentence_like >= 1 and total_chars >= 180)
        or short_sentence_like >= 1
        or (mixed_case_lines >= 2 and total_chars >= 70)
    )


def _looks_like_title_page(text: str, headings: list[str], *, page_no: int, total_pages: int) -> bool:
    if page_no > max(18, int(total_pages * 0.08)):
        return False
    lines = _plain_text_lines(text)[:12]
    if not lines:
        return False
    first_heading = normalize_title(headings[0] if headings else "")
    if first_heading and _chapter_keyword_strength(first_heading) >= 1 and _looks_like_prose_after_heading(text):
        return False
    if headings and _looks_like_prose_after_heading(text):
        return False
    lowered = [line.lower() for line in lines]
    if any(any(re.search(pattern, line, re.IGNORECASE) for pattern in _FRONT_MATTER_LINE_PATTERNS) for line in lowered):
        return True
    short_lines = sum(1 for line in lines if len(line) <= 40)
    heading_like = any(_uppercase_ratio(item) >= 0.55 for item in headings or [])
    if len(lines) <= 12 and short_lines >= max(2, len(lines) - 2):
        if heading_like or headings or _uppercase_ratio(" ".join(lines[:8])) >= 0.55:
            return True
    return False


def _looks_like_course_listing_page(text: str, *, page_no: int, total_pages: int) -> bool:
    if page_no > max(20, int(total_pages * 0.08)):
        return False
    lines = _plain_text_lines(text)[:24]
    if len(lines) < 4:
        return False
    year_range_count = sum(1 for line in lines if _YEAR_RANGE_RE.search(line))
    course_hint = any(
        re.search(r"cours (?:de|au).*(?:coll[eè]ge de france)", line, re.IGNORECASE)
        for line in lines[:4]
    )
    return year_range_count >= 3 and (course_hint or len(lines) >= 8)


def _looks_like_copyright_front_matter_page(text: str, *, page_no: int, total_pages: int) -> bool:
    if page_no > max(20, int(total_pages * 0.08)):
        return False
    lines = _plain_text_lines(text)[:20]
    if not lines:
        return False
    hits = sum(
        1
        for line in lines
        if re.search(
            r"\b(?:isbn|all rights reserved|printed in|copyright|code de la propriété intellectuelle)\b|^[©©]",
            line,
            re.IGNORECASE,
        )
    )
    if hits >= 2:
        return True
    return any("édition établie sous la direction" in line.lower() for line in lines) and hits >= 1


def _chapter_keyword_strength(title: str) -> int:
    text = normalize_title(title)
    if not text:
        return 0
    if _CHAPTER_KEYWORD_RE.search(text):
        return 2
    if _MAIN_NUMBERED_TITLE_RE.search(text):
        return 1
    return 0


def _is_toc_force_export_title(title: str) -> bool:
    return bool(_TOC_FORCE_EXPORT_TITLE_RE.match(normalize_title(title)))


def _is_visual_toc_explicit_chapter_title(title: str) -> bool:
    normalized = normalize_title(title)
    if not normalized:
        return False
    if _is_toc_force_export_title(normalized):
        return True
    if _MAIN_NUMBERED_TITLE_RE.search(normalized):
        return True
    return bool(_TOC_EXPLICIT_CHAPTER_TITLE_RE.search(normalized))


def _is_strong_body_boundary_page(page_row: Mapping[str, Any], *, total_pages: int) -> bool:
    page = dict(page_row.get("_page") or {})
    page_no = int(page_row.get("page_no") or 0)
    headings = extract_page_headings(page)
    first_heading = normalize_title(headings[0] if headings else "")
    if not first_heading:
        return False
    if _NOTES_HEADER_RE.match(first_heading):
        return False
    if _LECTURE_TITLE_RE.search(first_heading):
        return True
    if _is_visual_toc_explicit_chapter_title(first_heading):
        return True
    family = guess_title_family(first_heading, page_no=page_no, total_pages=total_pages)
    return family == "chapter"


def _is_body_entry_page(page_row: Mapping[str, Any], *, total_pages: int) -> bool:
    if _is_strong_body_boundary_page(page_row, total_pages=total_pages):
        return True
    page = dict(page_row.get("_page") or {})
    page_no = int(page_row.get("page_no") or 0)
    text = page_markdown_text(page)
    headings = extract_page_headings(page)
    first_heading = normalize_title(headings[0] if headings else "")
    if not first_heading:
        return False
    if _NOTES_HEADER_RE.match(first_heading):
        return False
    if _looks_like_course_listing_page(text, page_no=page_no, total_pages=total_pages):
        return False
    if _looks_like_copyright_front_matter_page(text, page_no=page_no, total_pages=total_pages):
        return False
    return _looks_like_prose_after_heading(text)


def _looks_like_early_other_page(text: str, headings: list[str], *, page_no: int, total_pages: int) -> bool:
    if page_no > max(25, int(total_pages * 0.08)):
        return False
    first_heading = normalize_title(headings[0] if headings else "")
    if first_heading and guess_title_family(first_heading, page_no=page_no, total_pages=total_pages) in {
        "contents",
        "illustrations",
        "bibliography",
        "index",
        "appendix",
    }:
        return True
    lines = _plain_text_lines(text)[:24]
    if not lines:
        return False
    numbered_like = sum(1 for line in lines if _TOC_LINE_RE.match(line) or _FIGURE_LIST_LINE_RE.match(line))
    return numbered_like >= 4


def _looks_like_rear_toc_tail_page(text: str, headings: list[str], *, page_no: int, total_pages: int) -> bool:
    if total_pages < 40:
        return False
    tail_window = max(12, int(total_pages * 0.04))
    if page_no < max(1, total_pages - tail_window):
        return False
    lines = _plain_text_lines(text)[:40]
    if len(lines) < 3:
        return False

    lecture_count = 0
    dotted_count = 0
    tocish_count = 0
    tail_listing_count = 0
    for line in lines:
        normalized = normalize_title(line)
        lowered = normalized.lower()
        has_dot_leader = bool(_DOT_LEADER_RE.search(normalized) or "....." in normalized)
        if has_dot_leader:
            dotted_count += 1
            if len(normalized.split()) <= 26:
                tocish_count += 1
        if _TOC_LINE_RE.match(normalized) or _FIGURE_LIST_LINE_RE.match(normalized):
            tocish_count += 1
        if _LECTURE_TITLE_RE.search(lowered):
            lecture_count += 1
            if has_dot_leader or re.search(r"\d{4}\s*$", lowered):
                tocish_count += 1
        if (
            re.search(r"\b\d{1,4}\s*$", normalized)
            and len(normalized.split()) >= 3
            and len(normalized.split()) <= 18
        ):
            tail_listing_count += 1

    normalized_headings = [normalize_title(item).lower() for item in headings if normalize_title(item)]
    has_table_heading = any(
        _TABLE_TOC_HEADING_RE.match(heading)
        for heading in normalized_headings[:2]
    )
    if has_table_heading and (tocish_count >= 2 or dotted_count >= 2):
        return True
    if lecture_count >= 2 and (tocish_count >= 3 or dotted_count >= 2):
        return True
    if tocish_count >= 5 and dotted_count >= 1:
        return True
    if tocish_count >= 6:
        return True
    if tail_listing_count >= 5:
        return True
    return False


def _looks_like_rear_author_blurb_page(text: str, headings: list[str], *, page_no: int, total_pages: int) -> bool:
    if total_pages < 40:
        return False
    tail_window = max(12, int(total_pages * 0.04))
    if page_no < max(1, total_pages - tail_window):
        return False
    lines = _plain_text_lines(text)[:24]
    if len(lines) < 4:
        return False
    normalized_headings = [normalize_title(item) for item in headings if normalize_title(item)]
    if len(normalized_headings) < 2:
        return False
    first_heading = normalized_headings[0]
    second_heading = normalized_headings[1]
    if _chapter_keyword_strength(first_heading) >= 1 or _chapter_keyword_strength(second_heading) >= 1:
        return False
    if _uppercase_ratio(second_heading) < 0.45:
        return False
    prose_lines = sum(1 for line in lines if len(line) >= 60 and re.search(r"[a-zà-ÿ]{4,}", line, re.IGNORECASE))
    total_chars = sum(len(line) for line in lines)
    return prose_lines >= 2 or (prose_lines >= 1 and total_chars >= 150)


def _looks_like_rear_sparse_other_page(text: str, *, page_no: int, total_pages: int) -> bool:
    if total_pages < 40:
        return False
    tail_window = max(12, int(total_pages * 0.04))
    if page_no < max(1, total_pages - tail_window):
        return False
    normalized = str(text or "").strip()
    if not normalized:
        return True
    if "<table" in normalized.lower():
        return True
    lines = _plain_text_lines(normalized)[:20]
    if not lines:
        return True
    alnum_chars = sum(1 for ch in normalized if ch.isalnum())
    digit_chars = sum(1 for ch in normalized if ch.isdigit())
    if alnum_chars > 0 and digit_chars / max(1, alnum_chars) >= 0.65:
        return True
    short_lines = sum(1 for line in lines if len(line) <= 24)
    return short_lines >= max(4, len(lines) - 1) and not _looks_like_prose_after_heading(normalized)


def _note_def_match(line: str) -> re.Match[str] | None:
    candidate = str(line or "").strip()
    if not candidate:
        return None
    if _MARKDOWN_HEADING_RE.match(candidate):
        candidate = _strip_markdown_heading(candidate)
    candidate = _LEADING_OCR_NOTE_PUNCT_RE.sub("", candidate)
    return _NOTE_DEF_RE.match(candidate) or _NOTE_DEF_OCR_SPLIT_RE.match(candidate)


def _looks_like_note_continuation_page(text: str, *, page_no: int, total_pages: int) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if page_no <= max(8, int(total_pages * 0.03)):
        return False
    lines = _plain_text_lines(normalized)
    if not lines:
        return False
    if _NOTES_HEADER_RE.match(lines[0]):
        return True
    note_def_count = sum(1 for line in lines if _note_def_match(line))
    if note_def_count < 2:
        return False
    first_note_index = next((idx for idx, line in enumerate(lines) if _note_def_match(line)), -1)
    if first_note_index >= 0:
        prelude_lines = lines[:first_note_index]
        if (
            note_def_count >= 2
            and first_note_index <= 4
            and prelude_lines
            and all(
                _MARKDOWN_HEADING_RE.match(line)
                or len(line) <= 80
                for line in prelude_lines
            )
        ):
            return True
    non_note_line_count = max(0, len(lines) - note_def_count)
    if non_note_line_count <= 1 and note_def_count >= 2:
        return True
    first_content_line = next((line for line in lines if not _NOTES_HEADER_RE.match(line)), "")
    if first_content_line and _note_def_match(first_content_line):
        return note_def_count >= 2
    return note_def_count >= max(4, len(lines) // 2)


def _looks_like_bibliography_continuation_page(text: str) -> bool:
    normalized = " ".join(_plain_text_lines(text))
    if not normalized:
        return False
    author_entry_count = len(_BIBLIO_AUTHOR_ENTRY_RE.findall(normalized))
    citation_hint_count = len(_BIBLIO_CITATION_HINT_RE.findall(normalized))
    year_count = len(_YEAR_TOKEN_RE.findall(normalized))
    quoted_title_count = normalized.count("«") + normalized.count('"')
    if author_entry_count >= 2 and year_count >= 2:
        return True
    if citation_hint_count >= 3 and year_count >= 3:
        return True
    return quoted_title_count >= 2 and citation_hint_count >= 2 and year_count >= 2


def _looks_like_index_continuation_page(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return len(_INDEX_ENTRY_RE.findall(normalized)) >= 2


def _looks_like_illustrations_continuation_page(text: str) -> bool:
    normalized = " ".join(_plain_text_lines(text))
    if not normalized:
        return False
    numbered_entry_count = len(re.findall(r"\b\d{1,3}\.\s+\S", normalized))
    hint_count = len(_ILLUSTRATION_CONTENT_RE.findall(normalized))
    return numbered_entry_count >= 2 and hint_count >= 2


def _looks_like_back_matter_continuation_page(
    text: str,
    *,
    family: str,
    page_no: int,
    total_pages: int,
) -> bool:
    normalized_family = str(family or "").strip().lower()
    if normalized_family == "bibliography":
        return _looks_like_bibliography_continuation_page(text)
    if normalized_family == "index":
        return _looks_like_index_continuation_page(text)
    if normalized_family == "illustrations":
        return _looks_like_illustrations_continuation_page(text)
    return False


def _seed_back_matter_family(
    record: PagePartitionRecord,
    *,
    page: Mapping[str, Any],
    total_pages: int,
) -> str:
    safe_total_pages = max(1, int(total_pages))
    safe_page_no = max(1, int(record.page_no))
    if safe_total_pages > 20 and safe_page_no < max(20, int(safe_total_pages * 0.6)):
        return ""
    if record.page_role == "other" and str(record.reason or "") in {"bibliography", "index", "illustrations"}:
        return str(record.reason or "")
    headings = extract_page_headings(page)
    first_heading = normalize_title(headings[0] if headings else "")
    if not first_heading:
        return ""
    family = guess_title_family(first_heading, page_no=record.page_no, total_pages=total_pages)
    if family in {"bibliography", "index", "illustrations"}:
        return str(family)
    return ""


@dataclass(slots=True)
class _RuleMatch:
    matched: bool
    role: PageRole
    confidence: float
    reason: str


@dataclass(slots=True)
class _PageScanContext:
    page: dict[str, Any]
    page_no: int
    total_pages: int
    text: str
    note_scan: dict[str, Any]
    headings: list[str]


def _match(role: PageRole, confidence: float, reason: str) -> _RuleMatch:
    return _RuleMatch(matched=True, role=role, confidence=float(confidence), reason=str(reason or ""))


def _no_match() -> _RuleMatch:
    return _RuleMatch(matched=False, role="body", confidence=0.0, reason="")


def _rule_archive_noise(ctx: _PageScanContext) -> _RuleMatch:
    if ctx.page_no <= max(6, int(ctx.total_pages * 0.03)) and _ARCHIVE_NOISE_RE.search(ctx.text):
        return _match("noise", 0.98, "archive_noise")
    return _no_match()


def _rule_early_course_listing(ctx: _PageScanContext) -> _RuleMatch:
    if _looks_like_course_listing_page(ctx.text, page_no=ctx.page_no, total_pages=ctx.total_pages):
        return _match("other", 0.97, "early_course_listing")
    return _no_match()


def _rule_copyright_front_matter(ctx: _PageScanContext) -> _RuleMatch:
    if _looks_like_copyright_front_matter_page(ctx.text, page_no=ctx.page_no, total_pages=ctx.total_pages):
        return _match("front_matter", 0.95, "copyright_front_matter")
    return _no_match()


def _rule_early_other_list(ctx: _PageScanContext) -> _RuleMatch:
    first_heading = ctx.headings[0] if ctx.headings else ""
    if not (_NOTES_HEADER_RE.match(first_heading)) and _looks_like_early_other_page(
        ctx.text,
        ctx.headings,
        page_no=ctx.page_no,
        total_pages=ctx.total_pages,
    ):
        return _match("other", 0.96, "early_other_list")
    return _no_match()


def _rule_rear_toc_tail(ctx: _PageScanContext) -> _RuleMatch:
    if _looks_like_rear_toc_tail_page(
        ctx.text,
        ctx.headings,
        page_no=ctx.page_no,
        total_pages=ctx.total_pages,
    ):
        return _match("other", 0.95, "rear_toc_tail")
    return _no_match()


def _rule_rear_author_blurb(ctx: _PageScanContext) -> _RuleMatch:
    if _looks_like_rear_author_blurb_page(
        ctx.text,
        ctx.headings,
        page_no=ctx.page_no,
        total_pages=ctx.total_pages,
    ):
        return _match("other", 0.95, "rear_author_blurb")
    return _no_match()


def _rule_rear_sparse_other(ctx: _PageScanContext) -> _RuleMatch:
    if _looks_like_rear_sparse_other_page(ctx.text, page_no=ctx.page_no, total_pages=ctx.total_pages):
        return _match("other", 0.90, "rear_sparse_other")
    return _no_match()


def _rule_note_scan(ctx: _PageScanContext) -> _RuleMatch:
    page_kind = str(ctx.note_scan.get("page_kind") or "").strip().lower()
    if page_kind == "endnote_collection":
        return _match("note", 0.95, "note_scan_collection")
    if page_kind == "mixed_body_endnotes":
        return _match("body", 0.85, "mixed_body_endnotes")
    return _no_match()


def _rule_notes_heading(ctx: _PageScanContext) -> _RuleMatch:
    first_heading = ctx.headings[0] if ctx.headings else ""
    note_start_line_index = ctx.note_scan.get("note_start_line_index")
    if note_start_line_index == 0 or (first_heading and _NOTES_HEADER_RE.match(first_heading)):
        return _match("note", 0.88, "notes_heading")
    return _no_match()


def _rule_title_page(ctx: _PageScanContext) -> _RuleMatch:
    if _looks_like_title_page(ctx.text, ctx.headings, page_no=ctx.page_no, total_pages=ctx.total_pages):
        return _match("front_matter", 0.92, "title_page")
    return _no_match()


def _rule_title_family(ctx: _PageScanContext) -> _RuleMatch:
    first_heading = ctx.headings[0] if ctx.headings else ""
    if not first_heading:
        return _no_match()
    family = guess_title_family(first_heading, page_no=ctx.page_no, total_pages=ctx.total_pages)
    if family == "front_matter":
        return _match("front_matter", 0.90, "title_family")
    if family in {"contents", "illustrations", "bibliography", "index", "appendix"}:
        return _match("other", 0.94, family)
    return _no_match()


def _rule_blank_front_page(ctx: _PageScanContext) -> _RuleMatch:
    if ctx.page_no <= 2 and not ctx.text.strip():
        return _match("noise", 0.60, "blank_front_page")
    return _no_match()


def _rule_default_body(ctx: _PageScanContext) -> _RuleMatch:
    return _match("body", 0.72 if ctx.headings else 0.62, "default_body")


def _resolve_page_role(ctx: _PageScanContext) -> _RuleMatch:
    rules = (
        _rule_archive_noise,
        _rule_early_course_listing,
        _rule_copyright_front_matter,
        _rule_early_other_list,
        _rule_rear_toc_tail,
        _rule_rear_author_blurb,
        _rule_rear_sparse_other,
        _rule_note_scan,
        _rule_notes_heading,
        _rule_title_page,
        _rule_title_family,
        _rule_blank_front_page,
        _rule_default_body,
    )
    for rule in rules:
        matched = rule(ctx)
        if matched.matched:
            return matched
    return _rule_default_body(ctx)


def _apply_front_matter_continuation_fix(
    records: list[PagePartitionRecord],
    *,
    page_by_no: Mapping[int, Mapping[str, Any]],
    total_pages: int,
) -> None:
    early_limit = max(20, int(total_pages * 0.08))
    in_front_matter_run = False
    for record in records:
        if record.page_no <= 0 or record.page_no > early_limit:
            continue
        if record.page_role == "front_matter":
            in_front_matter_run = True
            continue
        if record.page_role in {"noise", "other"}:
            continue
        page = dict(page_by_no.get(record.page_no) or {})
        row_stub = {
            "page_no": record.page_no,
            "page_role": record.page_role,
            "section_hint": record.section_hint,
            "has_note_heading": record.has_note_heading,
            "_page": page,
        }
        is_body_entry = _is_body_entry_page(row_stub, total_pages=max(1, total_pages))
        if record.page_role == "body" and in_front_matter_run and not is_body_entry:
            record.page_role = "front_matter"
            record.confidence = max(float(record.confidence), 0.78)
            record.reason = "front_matter_continuation"
            continue
        if record.page_role == "body" and is_body_entry:
            in_front_matter_run = False


def _apply_note_continuation_fix(
    records: list[PagePartitionRecord],
    *,
    page_by_no: Mapping[int, Mapping[str, Any]],
    total_pages: int,
) -> None:
    for record in records:
        if record.page_role not in {"body", "front_matter"}:
            continue
        page = dict(page_by_no.get(record.page_no) or {})
        text = page_markdown_text(page)
        if not _looks_like_note_continuation_page(text, page_no=record.page_no, total_pages=max(1, total_pages)):
            continue
        record.page_role = "note"
        record.confidence = max(float(record.confidence), 0.90)
        record.reason = "note_continuation"


def _apply_back_matter_continuation_fix(
    records: list[PagePartitionRecord],
    *,
    page_by_no: Mapping[int, Mapping[str, Any]],
    total_pages: int,
) -> None:
    active_family = ""
    for record in records:
        page = dict(page_by_no.get(record.page_no) or {})
        seeded_family = _seed_back_matter_family(
            record,
            page=page,
            total_pages=max(1, total_pages),
        )
        if seeded_family:
            active_family = seeded_family
            continue
        if not active_family:
            continue
        text = page_markdown_text(page)
        if _looks_like_back_matter_continuation_page(
            text,
            family=active_family,
            page_no=record.page_no,
            total_pages=max(1, total_pages),
        ):
            record.page_role = "other"
            record.confidence = max(float(record.confidence), 0.93)
            record.reason = f"{active_family}_continuation"
            continue
        active_family = ""


def _apply_manual_overrides(
    records: list[PagePartitionRecord],
    *,
    page_overrides: Mapping[str, Mapping[str, Any]] | None,
) -> None:
    override_map = dict(page_overrides or {})
    for record in records:
        override = dict(override_map.get(str(record.page_no), {}) or {})
        role = str(override.get("page_role") or "").strip()
        if not role or not is_valid_page_role(role):
            continue
        record.page_role = role  # type: ignore[assignment]
        record.confidence = 1.0
        record.reason = "manual_override"


def build_page_partitions(
    pages: list[dict],
    *,
    page_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[PagePartitionRecord]:
    annotated_pages = annotate_pages_with_note_scans(list(pages or []))
    total_pages = len(annotated_pages)
    records: list[PagePartitionRecord] = []
    page_by_no: dict[int, dict[str, Any]] = {}
    for page in annotated_pages:
        try:
            page_no = int(page.get("bookPage") or 0)
        except (TypeError, ValueError):
            continue
        if page_no <= 0:
            continue
        page_payload = dict(page)
        page_by_no[page_no] = page_payload
        note_scan = dict(page_payload.get("_note_scan") or {})
        headings = extract_page_headings(page_payload)
        matched = _resolve_page_role(
            _PageScanContext(
                page=page_payload,
                page_no=page_no,
                total_pages=max(1, total_pages),
                text=page_markdown_text(page_payload),
                note_scan=note_scan,
                headings=headings,
            )
        )
        records.append(
            PagePartitionRecord(
                page_no=page_no,
                target_pdf_page=page_no,
                page_role=matched.role,
                confidence=float(matched.confidence),
                reason=matched.reason,
                section_hint=first_section_hint(page_payload, note_scan),
                has_note_heading=has_note_heading(page_payload),
                note_scan_summary=note_scan_summary(note_scan),
            )
        )
    records.sort(key=lambda item: item.page_no)
    _apply_front_matter_continuation_fix(records, page_by_no=page_by_no, total_pages=max(1, total_pages))
    _apply_back_matter_continuation_fix(records, page_by_no=page_by_no, total_pages=max(1, total_pages))
    _apply_note_continuation_fix(records, page_by_no=page_by_no, total_pages=max(1, total_pages))
    _apply_manual_overrides(records, page_overrides=page_overrides)
    return records


def summarize_page_partitions(records: list[PagePartitionRecord]) -> dict[str, Any]:
    counts = {
        "noise": 0,
        "front_matter": 0,
        "body": 0,
        "note": 0,
        "other": 0,
    }
    for record in records:
        if record.page_role in counts:
            counts[record.page_role] += 1
    return {
        "total_pages": len(records),
        **counts,
    }

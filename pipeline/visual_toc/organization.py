"""visual TOC 条目归一、组织层和运行时 bundle。"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import struct
import tempfile
import time
import unicodedata
import zlib

from openai import OpenAI

from config import update_doc_meta
from document.pdf_extract import (
    extract_pdf_page_link_targets,
    read_pdf_page_labels,
    render_pdf_page,
)
from document.text_layer_fixer import detect_and_fix_text, detect_garbled_text
from persistence.sqlite_store import (
    SQLiteRepository,
    TOC_SOURCE_AUTO_VISUAL,
    TOC_SOURCE_USER,
)
from persistence.storage_toc import (
    clear_auto_visual_toc_bundle_from_disk,
    save_auto_visual_toc_bundle_to_disk,
)
from persistence.storage import (
    load_pages_from_disk,
    load_toc_visual_manual_inputs,
    load_user_toc_from_disk,
    resolve_page_print_label,
    resolve_visual_model_spec,
)

logger = logging.getLogger(__name__)


_VISION_PREFLIGHT_CACHE: dict[tuple[str, str, str], tuple[bool, str]] = {}
_TOC_CONTAINER_RE = re.compile(
    r"^(?:"
    r"table|table of contents|table des mati[eè]res|contents?|sommaire|toc|"
    r"目录|目錄|目次|목차|차례|"
    r"inhalt|inhaltsverzeichnis|"
    r"[ií]ndice|contenido|sum[aá]rio|sommario|"
    r"содержание|оглавление|"
    r"inhoud|inhoudsopgave|"
    r"المحتويات|الفهرس|"
    r"index"
    r")$",
    re.IGNORECASE,
)
_SENTENCE_PUNCT_RE = re.compile(r"[.:;!?]")
_TOC_HEADER_HINT_PATTERNS = (
    re.compile(r"^(?:table|table of contents|table des matieres?)$", re.IGNORECASE),
    re.compile(r"^(?:contents?|toc)$", re.IGNORECASE),
    re.compile(r"^(?:目录|目錄|目次)$"),
    re.compile(r"^(?:목차|차례)$"),
    re.compile(r"^(?:sommaire)$", re.IGNORECASE),
    re.compile(r"^(?:inhalt|inhaltsverzeichnis)$", re.IGNORECASE),
    re.compile(r"^(?:indice|indice\.|indice general|contenido|sumario|sommario)$", re.IGNORECASE),
    re.compile(r"^(?:содержание|оглавление)$", re.IGNORECASE),
    re.compile(r"^(?:inhoud|inhoudsopgave)$", re.IGNORECASE),
    re.compile(r"^(?:المحتويات|الفهرس)$"),
)
_INDEX_HEADER_HINT_PATTERNS = (
    re.compile(r"^(?:index|index of names|index of subjects|index nominum|index rerum)\b", re.IGNORECASE),
    re.compile(r"^(?:index des notions|index des noms|index des matieres)\b", re.IGNORECASE),
    re.compile(r"^(?:indices)$", re.IGNORECASE),
)
_BACKMATTER_HEADER_HINT_PATTERNS = (
    re.compile(r"^(?:notes?|bibliograph(?:y|ie)|references?|appendi(?:x|ces))$", re.IGNORECASE),
)
_FRONTMATTER_TITLE_PATTERNS = (
    re.compile(r"^(?:introduction|intro)\b", re.IGNORECASE),
    re.compile(r"^(?:acknowledg(?:e)?ments?)\b", re.IGNORECASE),
    re.compile(r"^(?:preface|foreword|prologue)\b", re.IGNORECASE),
    re.compile(r"^(?:avant-propos|avant propos|prelude)\b", re.IGNORECASE),
)
_NOTES_RANGE_TITLE_PATTERNS = (
    re.compile(r"^notes?\s+to\s+pages?\s+\d+\s*[-–]\s*\d+$", re.IGNORECASE),
    re.compile(r"^notes?\s+to\s+(?:pp?|pages?)\.?\s*\d+\s*[-–]\s*\d+$", re.IGNORECASE),
    re.compile(r"^notes?\s+on\s+sources?$", re.IGNORECASE),
    re.compile(r"^note\s+on\s+sources?$", re.IGNORECASE),
)
_TOC_TEXT_KEYWORD_PATTERNS = (
    re.compile(r"\btable of contents\b", re.IGNORECASE),
    re.compile(r"\bcontents?\b", re.IGNORECASE),
    re.compile(r"\btable des matieres?\b", re.IGNORECASE),
    re.compile(r"\bsommaire\b", re.IGNORECASE),
    re.compile(r"(?:目录|目錄|目次|목차|차례)"),
    re.compile(r"\b(?:inhalt|inhaltsverzeichnis)\b", re.IGNORECASE),
    re.compile(r"\b(?:indice|contenido|sumario|sommario)\b", re.IGNORECASE),
    re.compile(r"(?:содержание|оглавление)", re.IGNORECASE),
    re.compile(r"\b(?:inhoud|inhoudsopgave)\b", re.IGNORECASE),
    re.compile(r"(?:المحتويات|الفهرس)"),
)
_INDEX_TEXT_KEYWORD_PATTERNS = (
    re.compile(r"\bindex\b", re.IGNORECASE),
    re.compile(r"\bindices\b", re.IGNORECASE),
    re.compile(r"\bindex des notions\b", re.IGNORECASE),
    re.compile(r"\bindex des noms\b", re.IGNORECASE),
    re.compile(r"\bindex nominum\b", re.IGNORECASE),
)
_TOC_DOT_LEADER_RE = re.compile(r"\.{2,}\s*(?:\d+|[ivxlcdm]{1,10})\s*$", re.IGNORECASE)
_TOC_TRAILING_PAGE_RE = re.compile(r"(?:\s|\.{2,})(?:\d+|[ivxlcdm]{1,10})\s*$", re.IGNORECASE)
_LOCAL_VISUAL_SCAN_MAX_PAGES = 24
_TEXT_LAYER_MIN_SAMPLE_CHARS = 160
_TEXT_LAYER_DEGRADED_CONTROL_CHAR_RATIO = 0.12
_TEXT_LAYER_DEGRADED_REPLACEMENT_CHAR_RATIO = 0.02
_VISUAL_RETRY_NEIGHBOR_RADIUS = 1
_VISUAL_RETRY_MAX_EXTRA_PAGES = 8
_MAX_PRIMARY_RUNS = 3
_MAX_VISUAL_TOC_PAGES_TOTAL = 24
_MAX_VISUAL_TOC_PAGES_PER_RUN = 12
_CONTEXT_PAGES_PER_RUN_SIDE = 1
_DEGRADED_FRONT_WINDOW = 6
_DEGRADED_BACK_WINDOW = 12
_DEGRADED_EXPAND_STEP = 4
_DEGRADED_MAX_EXPAND_ROUNDS = 2
_VISUAL_TOC_ROLE_VALUES = {
    "container",
    "endnotes",
    "chapter",
    "section",
    "post_body",
    "back_matter",
    "front_matter",
}
_VISUAL_TOC_ROLE_ALIASES = {
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
_VISUAL_TOC_CONTAINER_TITLE_RE = re.compile(
    r"^\s*(?:part|partie|livre|book|section)\s+(?:[ivxlcm]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"premi[eè]re?|deuxi[eè]me|troisi[eè]me|quatri[eè]me|cinqui[eè]me|sixi[eè]me|septi[eè]me|huiti[eè]me|neuvi[eè]me|dixi[eè]me)\b|"
    r"^\s*cours,\s*ann[eé]e\b|"
    r"^\s*appendices\b|"
    r"^\s*indices\b",
    re.IGNORECASE,
)
_VISUAL_TOC_POST_BODY_TITLE_RE = re.compile(
    r"^\s*(?:r[eé]sum[eé](?:\s+du\s+cours)?|situation(?:\s+des?\s+cours?)?|appendix\b|annex(?:e|es)?\b)",
    re.IGNORECASE,
)
_VISUAL_TOC_ENDNOTES_TITLE_RE = re.compile(
    r"^\s*(?:notes?\b|endnotes?\b|notes?\s+on\s+the\s+text\b|notes?\s+to\s+the\s+chapters?\b|chapter\s+notes?\b)",
    re.IGNORECASE,
)
_VISUAL_TOC_BACK_MATTER_TITLE_RE = re.compile(
    r"^\s*(?:index\b|indices?\b|bibliograph(?:y|ie|ies)\b|references?\b|works cited\b|note on sources?\b)",
    re.IGNORECASE,
)
_VISUAL_TOC_FRONT_MATTER_TITLE_RE = re.compile(
    r"^\s*(?:list of abbreviations|liste des abr[eé]viations|list of illustrations|liste des illustrations|"
    r"acknowledg(?:e)?ments?|remerciements?|foreword|preface|avant-propos|avant propos|avertissement|abstract)\b",
    re.IGNORECASE,
)
_VISUAL_TOC_CHAPTER_TITLE_RE = re.compile(
    r"^\s*(?:chapter|chapitre)\b|^(?:\d+|[ivxlcm]+)(?:[\.\):\-]|\s)\s*\S+|\ble[cç]on du\b|\bepilogue\b|\bconclusion\b|\bintroduction\b",
    re.IGNORECASE,
)
_VISUAL_TOC_ROMAN_CONTAINER_RE = re.compile(r"^\s*[ivxlcm]+\.\s+\S+", re.IGNORECASE)
_MANUAL_TOC_HEADER_LINE_RE = re.compile(
    r"^\s*(?:(?:[ivxlcdm\d]+\s*)?(?:contents?|table(?:\s+of\s+contents)?|table des mati[eè]res|sommaire)(?:\s*[ivxlcdm\d]+)?|(?:contents?|table(?:\s+of\s+contents)?|table des mati[eè]res|sommaire)(?:\s*[ivxlcdm\d]+)?)\s*$",
    re.IGNORECASE,
)
_MANUAL_TOC_HEADER_PREFIX_RE = re.compile(
    r"^\s*(?:[ivxlcdm\d]+\s*)?(?:contents?|table(?:\s+of\s+contents)?|table des mati[eè]res|sommaire)\s*",
    re.IGNORECASE,
)
_MANUAL_TOC_TRAILING_PAGE_RE = re.compile(
    r"^(?P<title>.+?)\s+(?P<page>\d{1,4}|[ivxlcdm]{1,8})\s*$",
    re.IGNORECASE,
)
_VISUAL_USAGE_STAGES = (
    "visual_toc.preflight",
    "visual_toc.classify_candidates",
    "visual_toc.extract_page_items",
    "visual_toc.manual_input_extract",
)

_PAGE_ITEM_ROLE_HINT_VALUES = {"container", "content", "back_matter"}
from .scan_plan import _fold_header_hint, _normalize_header_hint
from .shared import _coerce_nonnegative_int, _coerce_positive_int


def _looks_like_summary_text(title: str) -> bool:
    text = str(title or "").strip()
    if not text:
        return False
    words = re.findall(r"\S+", text)
    if len(words) >= 18:
        return True
    if len(text) >= 120:
        return True
    if len(words) >= 12 and _SENTENCE_PUNCT_RE.search(text):
        return True
    return False

def _default_endnotes_summary() -> dict[str, bool | int | str | None]:
    return {
        "present": False,
        "container_title": None,
        "container_printed_page": None,
        "container_visual_order": None,
        "has_chapter_keyed_subentries_in_toc": False,
        "subentry_pattern": None,
    }

def _normalize_endnotes_summary(raw_value) -> dict[str, bool | int | str | None]:
    summary = _default_endnotes_summary()
    if not isinstance(raw_value, dict):
        return summary
    if not bool(raw_value.get("present")):
        return summary
    summary["present"] = True
    title = re.sub(r"\s+", " ", str(raw_value.get("container_title") or "")).strip()
    summary["container_title"] = title or None
    summary["container_printed_page"] = _coerce_positive_int(raw_value.get("container_printed_page"))
    visual_order = _coerce_positive_int(raw_value.get("container_visual_order"))
    summary["container_visual_order"] = visual_order
    summary["has_chapter_keyed_subentries_in_toc"] = bool(raw_value.get("has_chapter_keyed_subentries_in_toc"))
    subentry_pattern = str(raw_value.get("subentry_pattern") or "").strip()
    summary["subentry_pattern"] = subentry_pattern or None
    return summary

def _infer_endnotes_subentry_pattern(subentries: list[dict]) -> str | None:
    normalized_titles = [
        _normalize_header_hint(item.get("title") or "")
        for item in (subentries or [])
        if isinstance(item, dict) and _normalize_header_hint(item.get("title") or "")
    ]
    if not normalized_titles:
        return None
    if all(re.match(r"^(?:notes?|endnotes?)\s+to\b", title, re.IGNORECASE) for title in normalized_titles):
        return "named"
    if all(re.match(r"^(?:\d+|[ivxlcdm]+)[\.\)]?\s+\S", title, re.IGNORECASE) for title in normalized_titles):
        return "numbered"
    return "chapter_title"

def _finalize_endnotes_summary(
    raw_summary,
    items: list[dict],
) -> dict[str, bool | int | str | None]:
    summary = _normalize_endnotes_summary(raw_summary)
    normalized_items = [dict(item) for item in (items or []) if isinstance(item, dict)]
    endnotes_item = next(
        (
            item
            for item in normalized_items
            if _normalize_visual_toc_role_hint(
                item.get("role_hint"),
                title=_normalize_header_hint(item.get("title") or ""),
            )
            == "endnotes"
        ),
        None,
    )
    if endnotes_item is None:
        return summary

    title = _normalize_header_hint(endnotes_item.get("title") or "")
    printed_page = _coerce_positive_int(endnotes_item.get("printed_page")) or _coerce_positive_int(
        endnotes_item.get("book_page")
    )
    visual_order = _coerce_positive_int(endnotes_item.get("visual_order"))
    child_items = [
        item
        for item in normalized_items
        if _normalize_visual_toc_role_hint(
            item.get("role_hint"),
            title=_normalize_header_hint(item.get("title") or ""),
        )
        == "section"
        and _fold_header_hint(_normalize_header_hint(item.get("parent_title") or "")) == _fold_header_hint(title)
    ]

    summary["present"] = True
    summary["container_title"] = title or summary.get("container_title")
    summary["container_printed_page"] = printed_page or summary.get("container_printed_page")
    summary["container_visual_order"] = visual_order or summary.get("container_visual_order")
    summary["has_chapter_keyed_subentries_in_toc"] = bool(child_items) or bool(
        summary.get("has_chapter_keyed_subentries_in_toc")
    )
    if child_items:
        summary["subentry_pattern"] = _infer_endnotes_subentry_pattern(child_items) or summary.get("subentry_pattern")
    return summary

def _normalize_visual_toc_page_item_rows(values) -> list[dict]:
    rows: list[dict] = []
    for index, item in enumerate(values or [], start=1):
        if not isinstance(item, dict):
            continue
        title = re.sub(r"\s+", " ", str(item.get("title", "") or "")).strip()
        if not title:
            continue
        row = {
            "title": title,
            "depth": max(0, int(item.get("depth", 0) or 0)),
            "printed_page": _coerce_positive_int(item.get("printed_page")),
            "visual_order": max(1, int(item.get("visual_order", index) or index)),
        }
        role_hint = str(item.get("role_hint") or "").strip().lower().replace("-", "_")
        if role_hint in _PAGE_ITEM_ROLE_HINT_VALUES:
            row["role_hint"] = role_hint
        if "endnotes_candidate" in item:
            row["endnotes_candidate"] = bool(item.get("endnotes_candidate"))
        if "endnotes_subentry_candidate" in item:
            row["endnotes_subentry_candidate"] = bool(item.get("endnotes_subentry_candidate"))
        rows.append(row)
    return rows

def _slugify_visual_toc_title(text: str) -> str:
    normalized = _fold_header_hint(text)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or "item"

def _is_offset_required_item(item: dict) -> bool:
    role_hint = _normalize_visual_toc_role_hint(
        item.get("role_hint"),
        title=_normalize_header_hint(item.get("title") or ""),
    )
    return role_hint in {"chapter", "section", "post_body"}

def _build_offset_resolution_summary(items: list[dict]) -> dict[str, int]:
    navigable_total = 0
    navigable_ready = 0
    for item in items or []:
        if not _is_offset_required_item(item):
            continue
        navigable_total += 1
        if _coerce_nonnegative_int(item.get("file_idx")) is not None:
            navigable_ready += 1
    return {
        "navigable_item_count": int(navigable_total),
        "navigable_ready_count": int(navigable_ready),
        "unresolved_navigable_count": int(max(0, navigable_total - navigable_ready)),
    }

def filter_visual_toc_items(items: list[dict]) -> list[dict]:
    """过滤目录容器标题与 Biopolitique 一类的摘要说明块。"""
    filtered: list[dict] = []
    for index, item in enumerate(items or [], start=1):
        title = re.sub(r"\s+", " ", str(item.get("title", "") or "")).strip()
        if not title:
            continue
        printed_page = _coerce_positive_int(item.get("printed_page"))
        file_idx = _coerce_nonnegative_int(item.get("file_idx"))
        role_hint = _normalize_visual_toc_role_hint(item.get("role_hint"), title=title)
        preserve_without_page = role_hint in {
            "container",
            "endnotes",
            "post_body",
            "back_matter",
            "front_matter",
        }
        if _TOC_CONTAINER_RE.match(title) and printed_page is None and file_idx is None and not preserve_without_page:
            continue
        if file_idx is None and printed_page is None and _looks_like_summary_text(title) and not preserve_without_page:
            continue
        clone = {
            "title": title,
            "depth": max(0, int(item.get("depth", 0) or 0)),
            "printed_page": printed_page,
            "file_idx": file_idx,
            "visual_order": max(1, int(item.get("visual_order", index) or index)),
        }
        if role_hint:
            clone["role_hint"] = role_hint
        if item.get("parent_title"):
            clone["parent_title"] = re.sub(r"\s+", " ", str(item.get("parent_title") or "")).strip()
        if "body_candidate" in item:
            clone["body_candidate"] = bool(item.get("body_candidate"))
        if "export_candidate" in item:
            clone["export_candidate"] = bool(item.get("export_candidate"))
        filtered.append(clone)
    return filtered

def _normalize_visual_toc_role_hint(raw_value, *, title: str = "") -> str:
    role = str(raw_value or "").strip().lower().replace("-", "_")
    role = _VISUAL_TOC_ROLE_ALIASES.get(role, role)
    if role in _VISUAL_TOC_ROLE_VALUES:
        return role
    normalized_title = _normalize_header_hint(title)
    if not normalized_title:
        return ""
    if _VISUAL_TOC_CONTAINER_TITLE_RE.search(normalized_title):
        return "container"
    if _VISUAL_TOC_ENDNOTES_TITLE_RE.search(normalized_title):
        return "endnotes"
    if _VISUAL_TOC_POST_BODY_TITLE_RE.search(normalized_title):
        return "post_body"
    if _VISUAL_TOC_BACK_MATTER_TITLE_RE.search(normalized_title):
        return "back_matter"
    if _VISUAL_TOC_FRONT_MATTER_TITLE_RE.search(normalized_title):
        return "front_matter"
    if _VISUAL_TOC_CHAPTER_TITLE_RE.search(normalized_title):
        return "chapter"
    return ""

def _fold_visual_toc_composite_title(value: str) -> str:
    normalized = _normalize_header_hint(value)
    normalized = re.sub(r"\b(\d+)[il|](?=\s)", r"\1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b(\d+)[il|]\b", r"\1", normalized, flags=re.IGNORECASE)
    return _fold_header_hint(normalized)

def _is_visual_toc_composite_base_row(
    base_row: dict,
    organization_rows: list[dict],
) -> bool:
    base_title = _normalize_header_hint(base_row.get("title") or "")
    base_key = _fold_visual_toc_composite_title(base_title)
    if not base_key or len(base_key) < 18:
        return False

    matched: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in organization_rows or []:
        title = _normalize_header_hint(row.get("title") or "")
        title_key = _fold_visual_toc_composite_title(title)
        if not title_key or title_key == base_key or len(title_key) < 8 or title_key in seen:
            continue
        if title_key not in base_key:
            continue
        seen.add(title_key)
        matched.append(
            (
                title_key,
                _normalize_visual_toc_role_hint(
                    row.get("role_hint"),
                    title=title,
                ),
            )
        )
    if len(matched) < 2:
        return False

    roles = {role for _, role in matched if role}
    if not roles:
        return False
    if {"container", "endnotes"} & roles and roles & {
        "chapter",
        "section",
        "front_matter",
        "post_body",
        "back_matter",
    }:
        return True

    covered = sum(len(title_key) for title_key, _ in sorted(matched, key=lambda item: len(item[0]), reverse=True)[:2])
    return covered >= max(12, int(len(base_key) * 0.6))

def _compact_unique_visual_titles(values: list[str]) -> list[str]:
    compact: list[str] = []
    seen: set[str] = set()
    for raw_title in values or []:
        title = _normalize_header_hint(raw_title)
        if not title:
            continue
        key = _fold_header_hint(title)
        if key in seen:
            continue
        seen.add(key)
        compact.append(title)
    return compact

def _count_visual_toc_roles(items: list[dict]) -> dict[str, int]:
    counts = {role: 0 for role in _VISUAL_TOC_ROLE_VALUES}
    for item in items or []:
        role = _normalize_visual_toc_role_hint(item.get("role_hint"), title=_normalize_header_hint(item.get("title") or ""))
        if role in counts:
            counts[role] += 1
    return counts

def _should_prefer_manual_outline_nodes(existing_nodes: list[dict], outline_nodes: list[dict]) -> bool:
    existing_counts = _count_visual_toc_roles(existing_nodes)
    outline_counts = _count_visual_toc_roles(outline_nodes)
    if outline_counts.get("container", 0) <= 0:
        return False
    outline_body = int(outline_counts.get("chapter", 0)) + int(outline_counts.get("post_body", 0))
    existing_body = int(existing_counts.get("chapter", 0)) + int(existing_counts.get("post_body", 0))
    if outline_body < 8:
        return False
    return bool(
        outline_counts.get("container", 0) > existing_counts.get("container", 0)
        or outline_body >= existing_body
    )

def _collect_visual_toc_root_container_overrides(items: list[dict]) -> set[str]:
    ordered = sorted(
        [dict(item) for item in (items or []) if isinstance(item, dict)],
        key=lambda item: (
            max(1, int(item.get("visual_order", 0) or 0)),
            max(0, int(item.get("depth", 0) or 0)),
        ),
    )
    roman_root_candidates: list[str] = []
    overrides: set[str] = set()
    for index, item in enumerate(ordered):
        title = _normalize_header_hint(item.get("title") or "")
        depth = max(0, int(item.get("depth", 0) or 0))
        if not title or depth != 0:
            continue
        next_depth = None
        if index < len(ordered) - 1:
            try:
                next_depth = max(0, int(ordered[index + 1].get("depth", 0) or 0))
            except Exception:
                next_depth = None
        has_child_block = next_depth is not None and next_depth > depth
        if not has_child_block:
            continue
        if _VISUAL_TOC_CONTAINER_TITLE_RE.search(title):
            overrides.add(_fold_header_hint(title))
            continue
        if _VISUAL_TOC_ROMAN_CONTAINER_RE.match(title):
            roman_root_candidates.append(_fold_header_hint(title))
    if len(roman_root_candidates) >= 2:
        overrides.update(roman_root_candidates)
    return overrides

def _semantic_visual_toc_depth(role_hint: str, raw_depth: int) -> int:
    normalized_role = _normalize_visual_toc_role_hint(role_hint)
    if normalized_role in {"container", "endnotes"}:
        return 1
    if normalized_role == "section":
        return max(2, int(raw_depth or 0))
    return 0

def _semantic_visual_toc_level(role_hint: str, depth: int) -> int:
    normalized_role = _normalize_visual_toc_role_hint(role_hint)
    if normalized_role in {"container", "endnotes"}:
        return 1
    if normalized_role == "chapter":
        return 2
    if normalized_role == "section":
        return max(3, int(depth or 0) + 1)
    return 0

def _annotate_visual_toc_organization(items: list[dict]) -> tuple[list[dict], dict]:
    ordered = sorted(
        [dict(item) for item in (items or []) if isinstance(item, dict)],
        key=lambda item: (
            max(1, int(item.get("visual_order", 0) or 0)),
            max(0, int(item.get("depth", 0) or 0)),
        ),
    )
    root_container_overrides = _collect_visual_toc_root_container_overrides(ordered)
    explicit_root_container_keys = {
        _fold_header_hint(_normalize_header_hint(item.get("title") or ""))
        for item in ordered
        if max(0, int(item.get("depth", 0) or 0)) == 0
        and _normalize_visual_toc_role_hint(
            item.get("role_hint"),
            title=_normalize_header_hint(item.get("title") or ""),
        )
        == "container"
        and _fold_header_hint(_normalize_header_hint(item.get("title") or ""))
    }
    annotated: list[dict] = []
    ancestor_by_depth: dict[int, dict] = {}
    active_container_title = ""
    active_container_role = ""
    container_titles: list[str] = []
    post_body_titles: list[str] = []
    back_matter_titles: list[str] = []
    body_root_titles: list[str] = []
    max_body_depth = 0

    for index, item in enumerate(ordered, start=1):
        clone = dict(item)
        title = _normalize_header_hint(clone.get("title") or "")
        raw_depth = max(0, int(clone.get("depth", 0) or 0))
        explicit_role = str(clone.get("role_hint") or "").strip()
        role_hint = _normalize_visual_toc_role_hint(explicit_role, title=title)
        if not role_hint:
            role_hint = "section" if raw_depth > 0 else "chapter"

        next_depth = None
        if index < len(ordered):
            try:
                next_depth = max(0, int(ordered[index].get("depth", 0) or 0))
            except Exception:
                next_depth = None
        if raw_depth == 0 and next_depth is not None and next_depth > raw_depth:
            title_key = _fold_header_hint(title)
            looks_like_root_container = bool(
                title_key in root_container_overrides
                or (
                    role_hint in {"container", "back_matter", "front_matter", "post_body"}
                    and _VISUAL_TOC_CONTAINER_TITLE_RE.search(title)
                )
                or (explicit_role == "" and _VISUAL_TOC_ROMAN_CONTAINER_RE.match(title))
            )
            if role_hint in {"chapter", "section", "back_matter", "front_matter", "post_body"} and looks_like_root_container:
                role_hint = "container"
            elif role_hint == "back_matter" and _VISUAL_TOC_ENDNOTES_TITLE_RE.search(title):
                role_hint = "endnotes"

        if (
            raw_depth == 0
            and role_hint == "chapter"
            and not explicit_role
            and len(title.split()) >= 6
        ):
            has_later_root_container = any(
                max(0, int(later.get("depth", 0) or 0)) == 0
                and (
                    _fold_header_hint(_normalize_header_hint(later.get("title") or "")) in root_container_overrides
                    or _fold_header_hint(_normalize_header_hint(later.get("title") or "")) in explicit_root_container_keys
                    or _normalize_visual_toc_role_hint(
                        later.get("role_hint"),
                        title=_normalize_header_hint(later.get("title") or ""),
                    )
                    == "container"
                )
                for later in ordered[index:]
            )
            if has_later_root_container:
                role_hint = "front_matter"

        depth = _semantic_visual_toc_depth(role_hint, raw_depth)
        clone["title"] = title
        clone["depth"] = depth
        clone["visual_order"] = max(1, int(clone.get("visual_order", index) or index))
        clone["role_hint"] = role_hint

        for old_depth in [value for value in ancestor_by_depth.keys() if value >= raw_depth]:
            ancestor_by_depth.pop(old_depth, None)

        parent_title = _normalize_header_hint(clone.get("parent_title") or "")
        if not parent_title:
            parent_row = next(
                (
                    ancestor_by_depth[parent_depth]
                    for parent_depth in sorted(ancestor_by_depth.keys(), reverse=True)
                    if parent_depth < raw_depth
                ),
                None,
            )
            if isinstance(parent_row, dict):
                parent_title = _normalize_header_hint(parent_row.get("title") or "")
        if not parent_title and role_hint in {"chapter", "section"} and active_container_title and raw_depth > 0:
            parent_title = active_container_title
        if role_hint == "endnotes":
            parent_title = ""
        clone["parent_title"] = parent_title

        parent_role_hint = ""
        if parent_title:
            parent_row = next(
                (
                    row for row in reversed(annotated)
                    if _fold_header_hint(str(row.get("title") or "")) == _fold_header_hint(parent_title)
                ),
                None,
            )
            if isinstance(parent_row, dict):
                parent_role_hint = str(parent_row.get("role_hint") or "")
        elif active_container_title and parent_title == active_container_title:
            parent_role_hint = active_container_role

        if (
            role_hint == "section"
            and parent_title
            and (
                _coerce_positive_int(clone.get("printed_page")) is not None
                or _coerce_nonnegative_int(clone.get("file_idx")) is not None
            )
        ):
            parent_row = next(
                (
                    row for row in reversed(annotated)
                    if _fold_header_hint(str(row.get("title") or "")) == _fold_header_hint(parent_title)
                ),
                None,
            )
            if isinstance(parent_row, dict) and str(parent_row.get("role_hint") or "") == "container":
                title_role = _normalize_visual_toc_role_hint("", title=title)
                if title_role in {"front_matter", "back_matter", "post_body"}:
                    role_hint = title_role
                else:
                    role_hint = "chapter"
                clone["role_hint"] = role_hint
                depth = _semantic_visual_toc_depth(role_hint, raw_depth)
                clone["depth"] = depth

        if role_hint == "endnotes":
            body_candidate = False
            export_candidate = False
        elif role_hint == "section" and parent_role_hint == "endnotes":
            body_candidate = False
            export_candidate = False
        else:
            body_candidate = bool(clone.get("body_candidate")) if "body_candidate" in clone else role_hint in {"chapter", "section"}
            export_candidate = bool(clone.get("export_candidate")) if "export_candidate" in clone else role_hint in {"chapter", "post_body"}
        clone["body_candidate"] = body_candidate
        clone["export_candidate"] = export_candidate

        if role_hint in {"container", "endnotes"}:
            active_container_role = role_hint
        if role_hint == "container":
            container_titles.append(title)
            active_container_title = title
        elif role_hint == "endnotes":
            active_container_title = title
        elif role_hint == "post_body":
            post_body_titles.append(title)
            active_container_title = ""
            active_container_role = ""
        elif role_hint == "back_matter":
            back_matter_titles.append(title)
            active_container_title = ""
            active_container_role = ""

        if body_candidate:
            max_body_depth = max(max_body_depth, _semantic_visual_toc_level(role_hint, depth))
            root_title = title
            for parent_depth in sorted(ancestor_by_depth.keys(), reverse=True):
                parent_row = ancestor_by_depth[parent_depth]
                if str(parent_row.get("role_hint") or "") == "container":
                    root_title = _normalize_header_hint(parent_row.get("title") or "") or root_title
                    break
            body_root_titles.append(root_title)

        ancestor_by_depth[raw_depth] = clone
        annotated.append(clone)

    summary = {
        "max_body_depth": int(max_body_depth),
        "has_containers": bool(container_titles),
        "has_post_body": bool(post_body_titles),
        "has_back_matter": bool(back_matter_titles),
        "body_root_titles": _compact_unique_visual_titles(body_root_titles),
        "container_titles": _compact_unique_visual_titles(container_titles),
        "post_body_titles": _compact_unique_visual_titles(post_body_titles),
        "back_matter_titles": _compact_unique_visual_titles(back_matter_titles),
    }
    return annotated, summary

def map_visual_items_to_link_targets(items: list[dict], link_targets: list[dict]) -> list[dict]:
    """对没有页码的目录项，按视觉顺序对齐 PDF 内链目标页。"""
    order_map = {
        max(1, int(target.get("visual_order", 0) or 0)): int(target.get("target_file_idx"))
        for target in (link_targets or [])
        if target.get("target_file_idx") is not None
    }
    mapped: list[dict] = []
    for index, item in enumerate(items or [], start=1):
        clone = dict(item)
        visual_order = max(1, int(clone.get("visual_order", index) or index))
        if clone.get("file_idx") is None and visual_order in order_map:
            clone["file_idx"] = order_map[visual_order]
        mapped.append(clone)
    return mapped

def _build_visual_toc_runtime_bundle(
    *,
    items: list[dict],
    endnotes_summary: dict | None = None,
    organization_summary: dict | None = None,
    usage_summary: dict | None = None,
    run_summaries: list[dict] | None = None,
    manual_page_items_debug: list[list[dict]] | None = None,
    organization_bundle_debug: dict | None = None,
) -> dict:
    return {
        "items": list(items or []),
        "endnotes_summary": _normalize_endnotes_summary(endnotes_summary),
        "organization_summary": dict(organization_summary or {}),
        "usage_summary": dict(usage_summary or {}),
        "run_summaries": list(run_summaries or []),
        "manual_page_items_debug": list(manual_page_items_debug or []),
        "organization_bundle_debug": dict(organization_bundle_debug or {}),
    }

def _title_matches_any_pattern(title: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    normalized = _normalize_header_hint(title)
    folded = _fold_header_hint(normalized)
    return any(pattern.match(normalized) or pattern.match(folded) for pattern in patterns)

def _is_frontmatter_visual_title(title: str) -> bool:
    return _title_matches_any_pattern(title, _FRONTMATTER_TITLE_PATTERNS)

def _is_notes_range_title(title: str) -> bool:
    return _title_matches_any_pattern(title, _NOTES_RANGE_TITLE_PATTERNS)

def _filter_resolved_visual_toc_anomalies(items: list[dict], total_pages: int) -> list[dict]:
    ordered = sorted(
        items or [],
        key=lambda item: int(item.get("visual_order", 0) or 0),
    )
    if not ordered:
        return []

    threshold = max(18, int(max(0, total_pages or 0) * 0.12))
    tail_cutoff = int(max(0, total_pages or 0) * 0.7)
    indexed_file_targets = [
        _coerce_nonnegative_int(item.get("file_idx"))
        for item in ordered
    ]
    filtered: list[dict] = []

    for index, item in enumerate(ordered):
        clone = dict(item)
        file_idx = indexed_file_targets[index]
        title = str(clone.get("title", "") or "").strip()
        if file_idx is None:
            filtered.append(clone)
            continue

        prev_idx = next(
            (value for value in reversed(indexed_file_targets[:index]) if value is not None),
            None,
        )
        next_idx = next(
            (value for value in indexed_file_targets[index + 1:] if value is not None),
            None,
        )

        if _is_frontmatter_visual_title(title) and file_idx >= tail_cutoff:
            continue

        if prev_idx is not None and next_idx is not None and prev_idx <= next_idx:
            if file_idx > next_idx + threshold:
                continue
            if file_idx + threshold < prev_idx:
                continue

        notes_threshold = max(10, threshold // 2)
        if prev_idx is not None and file_idx + notes_threshold < prev_idx and _is_notes_range_title(title):
            continue
        if next_idx is not None and file_idx > next_idx + notes_threshold and _is_notes_range_title(title):
            continue

        filtered.append(clone)
    return filtered

def _build_printed_page_lookup(doc_id: str, pdf_path: str) -> dict[int, int]:
    lookup: dict[int, int] = {}
    pages, _ = load_pages_from_disk(doc_id)
    for page in pages or []:
        label = resolve_page_print_label(page)
        if label.isdigit():
            printed_page = int(label)
            if printed_page > 0 and printed_page not in lookup:
                lookup[printed_page] = int(page.get("fileIdx", max(int(page.get("bookPage", 1)) - 1, 0)) or 0)
    if lookup:
        return lookup
    for file_idx, label in enumerate(read_pdf_page_labels(pdf_path)):
        if label.isdigit():
            printed_page = int(label)
            if printed_page > 0 and printed_page not in lookup:
                lookup[printed_page] = file_idx
    return lookup

def _apply_printed_page_lookup(items: list[dict], printed_page_lookup: dict[int, int]) -> list[dict]:
    resolved: list[dict] = []
    for item in items or []:
        clone = dict(item)
        printed_page = _coerce_positive_int(clone.get("printed_page"))
        if clone.get("file_idx") is None and printed_page in printed_page_lookup:
            clone["file_idx"] = printed_page_lookup[printed_page]
        resolved.append(clone)
    return resolved

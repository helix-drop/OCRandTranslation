"""manual TOC 输入、outline 合并与 OCR 容器修补。"""

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
from .organization import _is_visual_toc_composite_base_row, _normalize_visual_toc_role_hint
from .scan_plan import _fold_header_hint, _normalize_header_hint

def _dedupe_toc_items(items: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for item in items or []:
        key = (
            re.sub(r"\s+", " ", str(item.get("title", "") or "")).strip().lower(),
            int(item.get("depth", 0) or 0),
            item.get("file_idx"),
            item.get("book_page"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped

def _looks_like_garbled_visual_toc_title(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return False
    if any(ord(char) < 32 and char not in "\t\n\r" for char in normalized):
        return True
    if re.search(r"[A-Za-zÀ-ÿ]'?=[A-Za-zÀ-ÿ]", normalized):
        return True
    if re.search(r"\.{6,}", normalized):
        return True
    if len(normalized) < 12:
        return False
    try:
        is_valid, stats = detect_garbled_text(normalized)
    except Exception:
        return False
    if is_valid:
        return False
    if stats.get("reason") in {"text_too_short", "no_content"}:
        return False
    length = int(stats.get("length", len(normalized)) or len(normalized))
    letter_ratio = float(stats.get("letter_ratio", 1.0) or 0.0)
    lower_ratio = float(stats.get("lower_ratio", 1.0) or 0.0)
    digit_ratio = float(stats.get("digit_ratio", 0.0) or 0.0)
    trash_ratio = float(stats.get("trash_ratio", 0.0) or 0.0)
    case_change_ratio = float(stats.get("case_change_ratio", 0.0) or 0.0)
    if length >= 40 and letter_ratio <= 0.01:
        return True
    if length >= 20 and lower_ratio <= 0.08 and (digit_ratio >= 0.15 or trash_ratio >= 0.08):
        return True
    if length >= 20 and letter_ratio <= 0.2 and case_change_ratio >= 0.12:
        return True
    return False

def _repair_or_drop_visual_toc_title(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return ""
    normalized = re.sub(r"\s[.\u2026,:;•·]{4,}.*$", "", normalized).strip()
    normalized = re.sub(r"(?i)'=b", "'emb", normalized)
    normalized = re.sub(r"(?<=[A-Za-zÀ-ÿ])=(?=[A-Za-zÀ-ÿ]{2,})", "em", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not _looks_like_garbled_visual_toc_title(normalized):
        return normalized
    try:
        fixed, method = detect_and_fix_text(normalized, raise_on_failure=False)
    except Exception:
        fixed, method = normalized, None
    fixed_normalized = re.sub(r"\s+", " ", str(fixed or "")).strip()
    fixed_normalized = re.sub(r"\s[.\u2026,:;•·]{4,}.*$", "", fixed_normalized).strip()
    fixed_normalized = re.sub(r"(?i)'=b", "'emb", fixed_normalized)
    fixed_normalized = re.sub(r"(?<=[A-Za-zÀ-ÿ])=(?=[A-Za-zÀ-ÿ]{2,})", "em", fixed_normalized)
    fixed_normalized = re.sub(r"\s+", " ", fixed_normalized).strip()
    if method and fixed_normalized and not _looks_like_garbled_visual_toc_title(fixed_normalized):
        return fixed_normalized
    return ""

def _sanitize_visual_toc_merge_rows(items: list[dict]) -> list[dict]:
    sanitized: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        clone = dict(item)
        title = _repair_or_drop_visual_toc_title(clone.get("title") or "")
        if not title:
            continue
        clone["title"] = title
        parent_title = clone.get("parent_title")
        if parent_title:
            repaired_parent = _repair_or_drop_visual_toc_title(parent_title)
            if repaired_parent:
                clone["parent_title"] = repaired_parent
            else:
                clone.pop("parent_title", None)
        sanitized.append(clone)
    return sanitized

def _merge_manual_toc_organization_nodes(base_items: list[dict], organization_nodes: list[dict]) -> list[dict]:
    if not organization_nodes:
        return list(base_items or [])

    normalized_base = _sanitize_visual_toc_merge_rows(base_items)
    normalized_org = _sanitize_visual_toc_merge_rows(organization_nodes)
    if not normalized_org:
        return normalized_base

    base_occurrence_map: dict[str, list[tuple[int, dict]]] = {}
    base_page_map: dict[int, list[tuple[int, dict]]] = {}
    for base_index, item in enumerate(normalized_base):
        title = _normalize_header_hint(item.get("title") or "")
        if not title:
            continue
        key = _fold_header_hint(title)
        base_occurrence_map.setdefault(key, []).append((base_index, item))
        printed_page = item.get("printed_page")
        if printed_page is not None:
            try:
                base_page_map.setdefault(int(printed_page), []).append((base_index, item))
            except (TypeError, ValueError):
                pass

    used_base_indices: set[int] = set()
    matched_base_index_by_org_pos: dict[int, int] = {}
    merged: list[dict] = []

    for org_pos, node in enumerate(normalized_org, start=1):
        original_title = str(node.get("title") or "")
        clone = dict(node)
        title = _normalize_header_hint(clone.get("title") or "")
        if not title:
            continue
        clone["title"] = title
        clone["visual_order"] = max(1, int(clone.get("visual_order", org_pos) or org_pos))
        key = _fold_header_hint(title)
        candidates = base_occurrence_map.get(key) or []
        matched = next(
            (
                (base_index, candidate)
                for base_index, candidate in candidates
                if base_index not in used_base_indices
            ),
            None,
        )
        matched_via_page = False
        if matched is None and _looks_like_garbled_visual_toc_title(original_title):
            printed_page = clone.get("printed_page")
            try:
                printed_page_no = int(printed_page)
            except (TypeError, ValueError):
                printed_page_no = 0
            if printed_page_no > 0:
                matched = next(
                    (
                        (base_index, candidate)
                        for base_index, candidate in (base_page_map.get(printed_page_no) or [])
                        if base_index not in used_base_indices
                    ),
                    None,
                )
                matched_via_page = matched is not None
        if matched is not None:
            matched_base_index, matched_item = matched
            used_base_indices.add(matched_base_index)
            matched_base_index_by_org_pos[len(merged)] = matched_base_index
            if matched_via_page:
                clone["title"] = _normalize_header_hint(matched_item.get("title") or clone.get("title") or "")
            for field in ("file_idx", "printed_page", "book_page"):
                if clone.get(field) is None and matched_item.get(field) is not None:
                    clone[field] = matched_item.get(field)
            matched_parent = _normalize_header_hint(matched_item.get("parent_title") or "")
            current_parent = _normalize_header_hint(clone.get("parent_title") or "")
            if matched_parent and (not current_parent or _looks_like_garbled_visual_toc_title(current_parent)):
                clone["parent_title"] = matched_parent
            if matched_via_page and not clone.get("role_hint") and matched_item.get("role_hint"):
                clone["role_hint"] = matched_item.get("role_hint")
        merged.append(clone)

    if normalized_base:
        trailing_order = max((int(item.get("visual_order", 0) or 0) for item in merged), default=0)
        with_inserted_base: list[dict] = []
        previous_matched_base_index = -1
        inserted_base_indices: set[int] = set()
        total_org_rows = len(merged)
        for org_index, row in enumerate(merged):
            next_matched_base_index = matched_base_index_by_org_pos.get(org_index)
            if next_matched_base_index is None:
                next_matched_base_index = next(
                    (
                        matched_base_index
                        for later_org_index, matched_base_index in matched_base_index_by_org_pos.items()
                        if later_org_index > org_index
                    ),
                    None,
                )
            if next_matched_base_index is not None:
                for gap_pos, gap_row in [
                    (base_pos, dict(base_row))
                    for base_pos, base_row in enumerate(normalized_base)
                    if previous_matched_base_index < base_pos < next_matched_base_index
                    and base_pos not in used_base_indices
                    and base_pos not in inserted_base_indices
                ]:
                    if _is_visual_toc_composite_base_row(gap_row, normalized_org):
                        inserted_base_indices.add(gap_pos)
                        continue
                    trailing_order += 1
                    gap_row["visual_order"] = trailing_order
                    with_inserted_base.append(gap_row)
                    inserted_base_indices.add(gap_pos)
            matched_base_index = matched_base_index_by_org_pos.get(org_index)
            if matched_base_index is not None:
                previous_matched_base_index = matched_base_index
            trailing_order += 1
            row["visual_order"] = trailing_order
            with_inserted_base.append(row)

            if org_index == total_org_rows - 1:
                trailing_rows = [
                    (base_pos, dict(base_row))
                    for base_pos, base_row in enumerate(normalized_base)
                    if base_pos > previous_matched_base_index
                    and base_pos not in used_base_indices
                    and base_pos not in inserted_base_indices
                ]
                for trailing_pos, trailing_row in trailing_rows:
                    if _is_visual_toc_composite_base_row(trailing_row, normalized_org):
                        inserted_base_indices.add(trailing_pos)
                        continue
                    trailing_order += 1
                    trailing_row["visual_order"] = trailing_order
                    with_inserted_base.append(trailing_row)
                    inserted_base_indices.add(trailing_pos)
        merged = with_inserted_base

    merged.sort(
        key=lambda item: (
            max(1, int(item.get("visual_order", 0) or 0)),
            max(0, int(item.get("depth", 0) or 0)),
        )
    )
    return merged

def _extract_manual_toc_ocr_lines_from_image_bytes_list(image_bytes_list: list[bytes]) -> list[str]:
    tesseract_bin = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"
    if not tesseract_bin or not os.path.exists(tesseract_bin):
        return []
    ocr_lines: list[str] = []
    seen: set[str] = set()
    for image_bytes in image_bytes_list or []:
        blob = bytes(image_bytes or b"")
        if not blob:
            continue
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(blob)
            temp_path = handle.name
        try:
            result = subprocess.run(
                [tesseract_bin, temp_path, "stdout", "--psm", "6"],
                capture_output=True,
                text=True,
                check=False,
            )
            text = str(result.stdout or "")
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        for raw_line in text.splitlines():
            line = _normalize_header_hint(raw_line)
            if not line or len(line) < 3:
                continue
            key = _fold_header_hint(line)
            if not key or key in seen:
                continue
            seen.add(key)
            ocr_lines.append(line)
    return ocr_lines

def _extract_manual_toc_outline_nodes_from_pdf_text(pdf_path: str) -> list[dict]:
    try:
        from pypdf import PdfReader
    except Exception:
        return []
    if not pdf_path or not os.path.exists(pdf_path):
        return []
    try:
        reader = PdfReader(pdf_path)
    except Exception:
        return []

    outline_entries: list[dict] = []
    visual_order = 0
    current_container_title = ""
    current_container_role = ""
    current_container_indent: int | None = None
    current_post_body_title = ""
    current_post_body_indent: int | None = None
    current_chapter_title = ""

    def _entry_role(title: str, has_page: bool) -> str:
        normalized_title = _normalize_header_hint(title)
        if re.search(r"(?i)\bnote\s+on\s+sources?\b", normalized_title):
            return "back_matter"
        explicit = _normalize_visual_toc_role_hint("", title=title)
        if explicit in {"container", "endnotes", "post_body", "back_matter", "front_matter"}:
            return explicit
        if has_page and _VISUAL_TOC_CHAPTER_TITLE_RE.search(normalized_title):
            return "chapter"
        return "section" if has_page else ""

    def _strip_header_prefix(text: str) -> str:
        candidate = _normalize_header_hint(text)
        if not candidate:
            return ""
        stripped = _MANUAL_TOC_HEADER_PREFIX_RE.sub("", candidate).strip()
        return _normalize_header_hint(stripped) or candidate

    for page in reader.pages:
        raw_text = str(page.extract_text() or "")
        if not raw_text.strip():
            continue
        lines = raw_text.splitlines()
        buffer = ""
        buffer_indent = 0
        for raw_line in lines:
            if not str(raw_line or "").strip():
                continue
            indent = len(str(raw_line)) - len(str(raw_line).lstrip(" "))
            stripped = _normalize_header_hint(raw_line)
            if not stripped:
                continue
            if _MANUAL_TOC_HEADER_LINE_RE.match(stripped):
                continue
            stripped = _strip_header_prefix(stripped)
            candidate = stripped if not buffer else _normalize_header_hint(f"{buffer} {stripped}")
            matched = _MANUAL_TOC_TRAILING_PAGE_RE.match(candidate)
            role_hint = _entry_role(candidate, has_page=bool(matched))
            if not matched and role_hint not in {"container", "back_matter", "front_matter"}:
                buffer = candidate
                buffer_indent = indent if buffer_indent == 0 else buffer_indent
                continue

            if matched:
                title = _normalize_header_hint(matched.group("title") or "")
                raw_page = str(matched.group("page") or "").strip()
                printed_page = int(raw_page) if raw_page.isdigit() else None
                role_hint = _entry_role(title, has_page=True)
                effective_indent = buffer_indent if buffer else indent
            else:
                title = candidate
                printed_page = None
                effective_indent = buffer_indent if buffer else indent

            buffer = ""
            buffer_indent = 0
            if not title:
                continue

            parent_title = ""
            depth = 0
            if role_hint == "container":
                current_container_title = title
                current_container_role = "container"
                current_container_indent = effective_indent
                current_post_body_title = ""
                current_post_body_indent = None
                current_chapter_title = ""
                depth = 1
            elif role_hint == "endnotes":
                current_container_title = title
                current_container_role = "endnotes"
                current_container_indent = effective_indent
                current_post_body_title = ""
                current_post_body_indent = None
                current_chapter_title = ""
                depth = 1
            elif role_hint == "post_body":
                current_container_title = ""
                current_container_role = ""
                current_container_indent = None
                current_post_body_title = title
                current_post_body_indent = effective_indent
                current_chapter_title = ""
            elif role_hint == "back_matter":
                current_post_body_title = ""
                current_post_body_indent = None
                current_chapter_title = ""
            elif role_hint == "front_matter":
                current_post_body_title = ""
                current_post_body_indent = None
                current_chapter_title = ""
            elif role_hint == "chapter":
                if (
                    current_container_title
                    and current_container_role == "endnotes"
                    and (
                        current_container_indent is None
                        or effective_indent >= current_container_indent
                    )
                ):
                    role_hint = "section"
                    depth = 2
                    parent_title = current_container_title
                    current_chapter_title = ""
                elif (
                    current_post_body_title
                    and current_post_body_indent is not None
                    and effective_indent > current_post_body_indent
                    and not bool(_VISUAL_TOC_CHAPTER_TITLE_RE.search(_normalize_header_hint(title)))
                ):
                    role_hint = "section"
                    depth = 2
                    parent_title = current_post_body_title
                    current_chapter_title = ""
                else:
                    current_post_body_title = ""
                    current_post_body_indent = None
                    if (
                        current_container_title
                        and current_container_role == "container"
                        and (
                            current_container_indent is None
                            or effective_indent >= current_container_indent
                            or bool(_VISUAL_TOC_CHAPTER_TITLE_RE.search(_normalize_header_hint(title)))
                        )
                    ):
                        parent_title = current_container_title
                    current_chapter_title = title
            elif role_hint == "section":
                if (
                    current_container_title
                    and current_container_role == "endnotes"
                    and (
                        current_container_indent is None
                        or effective_indent >= current_container_indent
                    )
                ):
                    depth = 2
                    parent_title = current_container_title
                    current_chapter_title = ""
                elif (
                    current_post_body_title
                    and current_post_body_indent is not None
                    and effective_indent > current_post_body_indent
                    and not current_chapter_title
                ):
                    depth = 2
                    parent_title = current_post_body_title
                elif current_chapter_title:
                    depth = 2
                    parent_title = current_chapter_title
                elif current_container_title and current_container_role == "container":
                    current_post_body_title = ""
                    current_post_body_indent = None
                    role_hint = "chapter"
                    depth = 0
                    parent_title = current_container_title
                    current_chapter_title = title
                else:
                    current_post_body_title = ""
                    current_post_body_indent = None
                    role_hint = "chapter"
                    depth = 0
                    current_chapter_title = title

            visual_order += 1
            entry = {
                "title": title,
                "depth": depth,
                "visual_order": visual_order,
                "role_hint": role_hint,
                "parent_title": parent_title,
            }
            if printed_page is not None:
                entry["printed_page"] = printed_page
            outline_entries.append(entry)
    return outline_entries

def _normalize_manual_toc_container_candidate_title(raw_title: str) -> str:
    title = _normalize_header_hint(raw_title)
    if not title:
        return ""
    title = re.sub(r"\s+(?:\d{1,4}|[ivxlcm]{1,8})\s*$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"(?i)^part\s+\|(?=\s)", "Part I", title)
    title = re.sub(r"(?i)^part\s+l(?=\s)", "Part I", title)
    title = re.sub(r"(?i)^part\s+il(?=\s)", "Part II", title)
    title = re.sub(r"(?i)^part\s+i1(?=\s)", "Part II", title)
    title = re.sub(r"(?i)^part\s+ill(?=\s)", "Part III", title)
    title = re.sub(r"(?i)^part\s+iv(?=\s)", "Part IV", title)
    title = re.sub(r"^\s*Il(?=\.)", "II", title)
    title = re.sub(r"^\s*lI(?=\.)", "II", title)
    title = re.sub(r"^\s*I1(?=\.)", "II", title)
    return _normalize_header_hint(title)

def _find_manual_toc_line_position(
    line_keys: list[str],
    title: str,
    *,
    start_at: int = 0,
) -> int | None:
    title_key = _fold_header_hint(title)
    if not title_key:
        return None
    for index in range(max(0, int(start_at)), len(line_keys)):
        line_key = line_keys[index]
        if not line_key:
            continue
        if line_key == title_key or title_key in line_key or line_key in title_key:
            return index
    return None

def _augment_manual_toc_organization_with_ocr_containers(
    organization_nodes: list[dict],
    ocr_lines: list[str],
) -> list[dict]:
    nodes = [dict(item) for item in (organization_nodes or []) if isinstance(item, dict)]
    if not nodes or not ocr_lines:
        return nodes
    line_titles = [_normalize_header_hint(line) for line in (ocr_lines or [])]
    line_keys = [_fold_header_hint(line) for line in line_titles]
    container_candidates: list[tuple[int, str]] = []
    for index, title in enumerate(line_titles):
        if not title:
            continue
        normalized_candidate = _normalize_manual_toc_container_candidate_title(title)
        if not normalized_candidate:
            continue
        if _VISUAL_TOC_CONTAINER_TITLE_RE.search(normalized_candidate) or _VISUAL_TOC_ROMAN_CONTAINER_RE.match(normalized_candidate):
            container_candidates.append((index, normalized_candidate))
    if not container_candidates:
        return nodes

    existing_title_keys = {
        _fold_header_hint(_normalize_header_hint(item.get("title") or ""))
        for item in nodes
        if _normalize_header_hint(item.get("title") or "")
    }
    node_line_positions: list[int] = []
    scan_cursor = 0
    last_matched_position = -1
    for item in nodes:
        matched = _find_manual_toc_line_position(
            line_keys,
            _normalize_header_hint(item.get("title") or ""),
            start_at=scan_cursor,
        )
        if matched is None:
            matched = last_matched_position if last_matched_position >= 0 else len(line_keys) + len(node_line_positions)
        else:
            scan_cursor = matched + 1
            last_matched_position = matched
        node_line_positions.append(matched)

    augmented = [dict(item) for item in nodes]
    offset = 0
    for candidate_index, title in container_candidates:
        title_key = _fold_header_hint(title)
        if not title_key or title_key in existing_title_keys:
            continue
        next_candidate_index = next(
            (
                later_index
                for later_index, _later_title in container_candidates
                if later_index > candidate_index
            ),
            None,
        )
        target_indices = [
            idx
            for idx, line_pos in enumerate(node_line_positions)
            if line_pos > candidate_index
            and (next_candidate_index is None or line_pos < next_candidate_index)
        ]
        if not target_indices:
            continue
        start_idx = target_indices[0]
        end_idx = target_indices[-1] + 1
        for idx in range(start_idx, end_idx):
            node = augmented[idx + offset]
            node_title = _normalize_header_hint(node.get("title") or "")
            role_hint = _normalize_visual_toc_role_hint(node.get("role_hint"), title=node_title)
            if role_hint in {"front_matter", "back_matter", "post_body"}:
                continue
            node["depth"] = max(1, int(node.get("depth", 0) or 0) + 1)
            node.pop("parent_title", None)
        augmented.insert(
            start_idx + offset,
            {
                "title": title,
                "depth": 0,
                "visual_order": 0,
                "printed_page": None,
                "file_idx": None,
                "role_hint": "container",
                "body_candidate": False,
                "export_candidate": False,
            },
        )
        existing_title_keys.add(title_key)
        offset += 1

    for index, item in enumerate(augmented, start=1):
        item["visual_order"] = index
    return augmented

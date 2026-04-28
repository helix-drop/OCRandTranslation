"""FNM_RE 第六阶段：导出构建。"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from typing import Any

from FNM_RE.models import (
    BodyAnchorRecord,
    ExportBundleRecord,
    ExportChapterRecord,
    NoteItemRecord,
    NoteLinkRecord,
    Phase5Structure,
    SectionHeadRecord,
    TranslationUnitRecord,
)
from FNM_RE.shared.refs import replace_frozen_refs

PENDING_TRANSLATION_TEXT = "[待翻译]"
OBSIDIAN_EXPORT_INDEX_MD = "index.md"
OBSIDIAN_EXPORT_CHAPTERS_DIR = "chapters"
OBSIDIAN_EXPORT_CHAPTERS_PREFIX = f"{OBSIDIAN_EXPORT_CHAPTERS_DIR}/"

_INVALID_CHAPTER_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_CHAPTER_FILENAME_SPACE_RE = re.compile(r"\s+")
_NOTE_TEXT_BODY_MARKUP_RE = re.compile(
    r"\$\s*\^\{\s*\[?\d{1,4}[A-Za-z]?\]?\s*\}\s*\$"
    r"|\$\s*\^\{\s*(\*{1,4})\s*\}\s*\$"
    r"|<sup>\s*\[?\d{1,4}[A-Za-z]?\]?\s*</sup>",
    re.IGNORECASE,
)
_LEADING_RAW_NOTE_MARKER_RE = re.compile(
    r"^\s*(?:\[\d{1,4}[A-Za-z]?\]|\d{1,4}[A-Za-z]?[.)]|\*{1,4}\s+|<sup>\s*\d{1,4}[A-Za-z]?\s*</sup>)\s*",
    re.IGNORECASE,
)
_ANY_NOTE_REF_RE = re.compile(
    r"\{\{NOTE_REF:([^}]+)\}\}"
    r"|\{\{FN_REF:([^}]+)\}\}"
    r"|\{\{EN_REF:([^}]+)\}\}"
    r"|\[EN-([^\]]+)\]"
    r"|\[FN-([^\]]+)\]"
    r"|\[\^([^\]]+)\]",
    re.IGNORECASE,
)
_RAW_BRACKET_NOTE_REF_RE = re.compile(r"(?<!\d)\[(\d{1,4}[A-Za-z]?)\](?!\d)")
_RAW_SUPERSCRIPT_NOTE_REF_RE = re.compile(
    r"\$\s*\^\{\s*\[?(\d{1,4}[A-Za-z]?)\]?\s*\}\s*\$"
    r"|\$\s*\^\{\s*(\*{1,4})\s*\}\s*\$"
    r"|<sup>\s*\[?(\d{1,4}[A-Za-z]?)\]?\s*</sup>",
    re.IGNORECASE,
)
_RAW_UNICODE_SUPERSCRIPT_NOTE_REF_RE = re.compile(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")
_TRAILING_IMAGE_ONLY_BLOCK_RE = re.compile(
    r"(?:\n\s*)*(?:<div[^>]*>\s*<img\b[^>]*>\s*</div>|!\[[^\]]*\]\([^)]+\))\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SECTION_HEAD_FORBIDDEN_PREFIX_RE = re.compile(
    r"^\d+\.\s*(?:ibid|cf\.?|see|supra|infra)\b",
    re.IGNORECASE,
)
_SECTION_HEAD_INLINE_NOTE_TRACE_RE = re.compile(
    r"(?:<sup>|\[\^[^\]]+\]|\$\s*\^\{[^}]+\}\s*\$)",
    re.IGNORECASE,
)
_SECTION_HEAD_QUOTE_RE = re.compile(r'^\s*["“”«»‹›「」『』].*["“”«»‹›」』]\s*$')
_FRONT_MATTER_TITLE_RE = re.compile(
    r"^(?:preface|foreword|acknowledg(?:e)?ments?|remerciements?|avant-propos|table of contents|contents|目录)\b",
    re.IGNORECASE,
)
_TOC_RESIDUE_RE = re.compile(r"(?im)^\s*(?:table of contents|contents|目录)\b")
_UNICODE_SUPERSCRIPT_TRANSLATION = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def _sanitize_obsidian_chapter_title(title: str) -> str:
    sanitized = _INVALID_CHAPTER_FILENAME_CHARS_RE.sub(" ", str(title or ""))
    sanitized = sanitized.replace(".", " ")
    sanitized = _CHAPTER_FILENAME_SPACE_RE.sub(" ", sanitized).strip()
    return sanitized or "chapter"


def _build_chapter_filename(
    order: int,
    title: str,
    *,
    used_filenames: set[str],
) -> str:
    base_name = f"{max(0, int(order or 0)):03d}-{_sanitize_obsidian_chapter_title(title)}"
    candidate = f"{base_name}.md"
    suffix = 2
    while candidate in used_filenames:
        candidate = f"{base_name}-{suffix}.md"
        suffix += 1
    used_filenames.add(candidate)
    return candidate


def _escape_leading_asterisks(text: str) -> str:
    """Escape leading * and ** at line start to prevent markdown italic/bold/list."""
    def _escape(m: re.Match) -> str:
        return "".join("\\*" for _ in m.group(1))
    return re.sub(r"^(\*{1,4})(?=\s)", _escape, text, flags=re.MULTILINE)


def _normalize_markdown_content(content: str) -> str:
    text = str(content or "").strip()
    return f"{text}\n" if text else ""


def _marker_key(raw: Any) -> str:
    normalized = str(raw or "").strip().translate(_UNICODE_SUPERSCRIPT_TRANSLATION).lower()
    # 符号型标记（*, ** 等）原样保留
    if re.match(r"^\*{1,4}$", normalized):
        return normalized
    normalized = re.sub(r"[^0-9a-z]+", "", normalized)
    if normalized.startswith("en") and normalized[2:].isdigit():
        return normalized[2:]
    return normalized


def _marker_aliases(raw: Any) -> set[str]:
    key = _marker_key(raw)
    if not key:
        return set()
    aliases = {key}
    trimmed = key.lstrip("0")
    if trimmed:
        aliases.add(trimmed)
    if key.startswith("en"):
        aliases.add(key[2:])
    return {token for token in aliases if token}


def _normalize_endnote_note_id(note_id: str) -> str:
    token = str(note_id or "").strip()
    if not token:
        return ""
    return token if token.lower().startswith("en-") else f"en-{token}"


def _resolve_note_id(note_id: str, note_text_by_id: dict[str, str]) -> str:
    token = str(note_id or "").strip()
    if not token:
        return ""
    if token in note_text_by_id:
        return token
    if token.lower().startswith("en-"):
        stripped = token[3:]
        if stripped in note_text_by_id:
            return stripped
    else:
        endnote = f"en-{token}"
        if endnote in note_text_by_id:
            return endnote
    return ""


def _resolve_note_kind(note_id: str, *, note_kind_by_id: dict[str, str]) -> str:
    """根据 note_id 查询 note_kind，返回 'endnote' | 'footnote' | ''。"""
    kind = str(note_kind_by_id.get(note_id, "") or "").strip().lower()
    if kind in ("endnote", "footnote"):
        return kind
    normalized = str(note_id or "").strip()
    if normalized.startswith("en-"):
        stripped = normalized[3:]
        kind = str(note_kind_by_id.get(stripped, "") or "").strip().lower()
    elif normalized:
        kind = str(note_kind_by_id.get(f"en-{normalized}", "") or "").strip().lower()
    return kind if kind in ("endnote", "footnote") else ""


def _local_endnote_ref_number(
    note_id: str,
    *,
    note_kind_by_id: dict[str, str],
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
) -> int | None:
    """为 endnote 分配 [^N] 编号。footnote 返回 None（不占编号）。note_kind_by_id 为空时兜底分配。"""
    kind = _resolve_note_kind(note_id, note_kind_by_id=note_kind_by_id)
    if kind == "footnote":
        return None
    if note_id not in local_ref_numbers:
        local_ref_numbers[note_id] = len(local_ref_numbers) + 1
        ordered_note_ids.append(note_id)
    return int(local_ref_numbers[note_id])


def _replace_note_refs_with_local_labels(
    text: str,
    *,
    note_text_by_id: dict[str, str],
    note_kind_by_id: dict[str, str],
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
    footnote_ids_seen: list[str] | None = None,
) -> str:
    def _replace(match: re.Match) -> str:
        captured = [str(match.group(idx) or "").strip() for idx in range(1, 7)]
        note_id = ""
        if captured[0]:
            note_id = captured[0]
        elif captured[1]:
            note_id = captured[1]
        elif captured[2]:
            note_id = _normalize_endnote_note_id(captured[2])
        elif captured[3]:
            note_id = _normalize_endnote_note_id(captured[3])
        elif captured[4]:
            note_id = captured[4]
        elif captured[5]:
            local_ref = captured[5]
            note_id = _normalize_endnote_note_id(local_ref) if local_ref.lower().startswith("en-") else local_ref
        resolved = _resolve_note_id(note_id, note_text_by_id)
        if not resolved:
            return match.group(0)
        ref_num = _local_endnote_ref_number(resolved, note_kind_by_id=note_kind_by_id,
                                            local_ref_numbers=local_ref_numbers,
                                            ordered_note_ids=ordered_note_ids)
        if ref_num is None:
            if footnote_ids_seen is not None and resolved not in footnote_ids_seen:
                footnote_ids_seen.append(resolved)
            return "*"
        return f"[^{ref_num}]"

    return _ANY_NOTE_REF_RE.sub(_replace, str(text or ""))


def _consume_marker_note_id(
    marker: str,
    *,
    marker_note_sequences: dict[str, list[str]],
    marker_usage_index: dict[str, int],
) -> str:
    normalized = _marker_key(marker)
    if not normalized:
        return ""
    candidates = list(marker_note_sequences.get(normalized) or [])
    if not candidates:
        return ""
    index = int(marker_usage_index.get(normalized) or 0)
    if index >= len(candidates):
        index = len(candidates) - 1
    marker_usage_index[normalized] = index + 1
    return str(candidates[index] or "")


def _replace_raw_bracket_refs_with_local_labels(
    text: str,
    *,
    marker_note_sequences: dict[str, list[str]],
    marker_usage_index: dict[str, int],
    note_kind_by_id: dict[str, str],
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
    footnote_ids_seen: list[str] | None = None,
) -> str:
    def _replace(match: re.Match) -> str:
        note_id = _consume_marker_note_id(
            str(match.group(1) or ""),
            marker_note_sequences=marker_note_sequences,
            marker_usage_index=marker_usage_index,
        )
        if not note_id:
            return match.group(0)
        ref_num = _local_endnote_ref_number(note_id, note_kind_by_id=note_kind_by_id,
                                            local_ref_numbers=local_ref_numbers,
                                            ordered_note_ids=ordered_note_ids)
        if ref_num is None:
            if footnote_ids_seen is not None and note_id not in footnote_ids_seen:
                footnote_ids_seen.append(note_id)
            return "*"
        return f"[^{ref_num}]"

    return _RAW_BRACKET_NOTE_REF_RE.sub(_replace, str(text or ""))


def _replace_raw_superscript_refs_with_local_labels(
    text: str,
    *,
    marker_note_sequences: dict[str, list[str]],
    marker_usage_index: dict[str, int],
    note_kind_by_id: dict[str, str],
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
    footnote_ids_seen: list[str] | None = None,
) -> str:
    def _replace(match: re.Match) -> str:
        marker = str(match.group(1) or match.group(2) or match.group(3) or "")
        note_id = _consume_marker_note_id(
            marker,
            marker_note_sequences=marker_note_sequences,
            marker_usage_index=marker_usage_index,
        )
        if not note_id:
            return match.group(0)
        ref_num = _local_endnote_ref_number(note_id, note_kind_by_id=note_kind_by_id,
                                            local_ref_numbers=local_ref_numbers,
                                            ordered_note_ids=ordered_note_ids)
        if ref_num is None:
            if footnote_ids_seen is not None and note_id not in footnote_ids_seen:
                footnote_ids_seen.append(note_id)
            return "*"
        return f"[^{ref_num}]"

    return _RAW_SUPERSCRIPT_NOTE_REF_RE.sub(_replace, str(text or ""))




def _replace_raw_unicode_superscript_refs_with_local_labels(
    text: str,
    *,
    marker_note_sequences: dict[str, list[str]],
    marker_usage_index: dict[str, int],
    note_kind_by_id: dict[str, str],
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
    footnote_ids_seen: list[str] | None = None,
) -> str:
    def _replace(match: re.Match) -> str:
        marker = str(match.group(1) or "").translate(_UNICODE_SUPERSCRIPT_TRANSLATION)
        note_id = _consume_marker_note_id(
            marker,
            marker_note_sequences=marker_note_sequences,
            marker_usage_index=marker_usage_index,
        )
        if not note_id:
            return match.group(0)
        ref_num = _local_endnote_ref_number(note_id, note_kind_by_id=note_kind_by_id,
                                            local_ref_numbers=local_ref_numbers,
                                            ordered_note_ids=ordered_note_ids)
        if ref_num is None:
            if footnote_ids_seen is not None and note_id not in footnote_ids_seen:
                footnote_ids_seen.append(note_id)
            return "*"
        return f"[^{ref_num}]"

    return _RAW_UNICODE_SUPERSCRIPT_NOTE_REF_RE.sub(_replace, str(text or ""))


def _strip_trailing_image_only_block(text: str) -> str:
    candidate = str(text or "").strip()
    if not candidate:
        return ""
    while True:
        updated = _TRAILING_IMAGE_ONLY_BLOCK_RE.sub("", candidate).rstrip()
        if updated == candidate:
            return candidate
        candidate = updated


def _looks_like_sentence_section_heading(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    if not normalized:
        return True
    words = [part for part in normalized.split(" ") if part]
    if len(words) >= 16 or len(normalized) >= 110:
        return True
    if normalized.endswith(("?", "!", ";")):
        return True
    if re.search(r"[.!;]\s+[A-Za-zÀ-ÖØ-öø-ÿ]", normalized):
        return True
    return False


def _is_exportable_section_head(head: SectionHeadRecord) -> bool:
    title = re.sub(r"\s+", " ", str(head.title or "").strip()).strip()
    if not title:
        return False
    if title == "*":
        return False
    if _SECTION_HEAD_FORBIDDEN_PREFIX_RE.match(title):
        return False
    if _SECTION_HEAD_INLINE_NOTE_TRACE_RE.search(title):
        return False
    if _SECTION_HEAD_QUOTE_RE.match(title):
        return False
    if _looks_like_sentence_section_heading(title):
        return False
    return True


def _should_replace_definition_text(existing: str, candidate: str) -> bool:
    current = str(existing or "").strip()
    payload = str(candidate or "").strip()
    if not payload:
        return False
    if not current:
        return True
    current_has_body_markup = bool(_NOTE_TEXT_BODY_MARKUP_RE.search(current))
    payload_has_body_markup = bool(_NOTE_TEXT_BODY_MARKUP_RE.search(payload))
    if current_has_body_markup and not payload_has_body_markup:
        return True
    if not current_has_body_markup and payload_has_body_markup:
        return False
    return len(payload) > len(current)


def _sanitize_note_text(text: str) -> str:
    payload = str(text or "").strip()
    payload = _NOTE_TEXT_BODY_MARKUP_RE.sub("", payload).strip()
    payload = _LEADING_RAW_NOTE_MARKER_RE.sub("", payload).strip()
    payload = re.sub(r"\s+", " ", payload).strip()
    return payload


def _build_note_text_by_id_for_chapter(
    chapter_id: str,
    *,
    note_units: list[TranslationUnitRecord],
) -> dict[str, str]:
    payload: dict[str, str] = {}
    for unit in note_units:
        if str(unit.section_id or "") != str(chapter_id or ""):
            continue
        if str(unit.kind or "") not in {"footnote", "endnote"}:
            continue
        note_id = str(unit.note_id or "").strip()
        if not note_id:
            continue
        note_text = _sanitize_note_text(str(unit.translated_text or unit.source_text or ""))
        if _should_replace_definition_text(payload.get(note_id, ""), note_text):
            payload[note_id] = note_text
    return payload


def _build_note_kind_by_id_for_chapter(
    chapter_id: str,
    *,
    note_units: list[TranslationUnitRecord],
) -> dict[str, str]:
    payload: dict[str, str] = {}
    for unit in note_units:
        if str(unit.section_id or "") != str(chapter_id or ""):
            continue
        kind = str(unit.kind or "").strip().lower()
        if kind not in {"footnote", "endnote"}:
            continue
        note_id = str(unit.note_id or "").strip()
        if note_id and note_id not in payload:
            payload[note_id] = kind
    return payload


def _diagnostic_machine_text_by_page(phase5: Phase5Structure) -> dict[int, str]:
    payload: dict[int, str] = {}
    for page in phase5.diagnostic_pages:
        page_no = int(page._pageBP or 0)
        if page_no <= 0:
            continue
        entries: list[str] = []
        for entry in page._page_entries:
            source = str(entry._translation_source or "").strip().lower()
            if source == "source":
                continue
            candidate = str(entry.translation or entry._machine_translation or entry._manual_translation or "").strip()
            if candidate:
                entries.append(candidate)
        if entries:
            payload[page_no] = "\n\n".join(entries)
    return payload


def _resolve_body_unit_text(
    unit: TranslationUnitRecord,
    *,
    include_diagnostic_entries: bool,
    diagnostic_machine_by_page: dict[int, str],
) -> str:
    translated = str(unit.translated_text or "").strip()
    if translated:
        return translated
    if include_diagnostic_entries:
        page_numbers = sorted(
            {
                int(segment.page_no or 0)
                for segment in unit.page_segments
                if int(segment.page_no or 0) > 0
            }
        )
        if not page_numbers and int(unit.page_start or 0) > 0:
            page_start = int(unit.page_start or 0)
            page_end = int(unit.page_end or page_start)
            page_numbers = list(range(page_start, page_end + 1))
        diagnostic_parts = [
            str(diagnostic_machine_by_page.get(page_no) or "").strip()
            for page_no in page_numbers
        ]
        diagnostic_parts = [item for item in diagnostic_parts if item]
        if diagnostic_parts:
            return "\n\n".join(diagnostic_parts)
    source = str(unit.source_text or "").strip()
    return source or PENDING_TRANSLATION_TEXT


def _rewrite_body_text_with_local_refs(
    text: str,
    *,
    note_text_by_id: dict[str, str],
    note_kind_by_id: dict[str, str],
    marker_note_sequences: dict[str, list[str]],
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
    footnote_ids_seen: list[str] | None = None,
) -> str:
    updated = _replace_note_refs_with_local_labels(
        text,
        note_text_by_id=note_text_by_id,
        note_kind_by_id=note_kind_by_id,
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
        footnote_ids_seen=footnote_ids_seen,
    )
    marker_usage_index: dict[str, int] = {}
    updated = _replace_raw_bracket_refs_with_local_labels(
        updated,
        marker_note_sequences=marker_note_sequences,
        marker_usage_index=marker_usage_index,
        note_kind_by_id=note_kind_by_id,
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
        footnote_ids_seen=footnote_ids_seen,
    )
    updated = _replace_raw_superscript_refs_with_local_labels(
        updated,
        marker_note_sequences=marker_note_sequences,
        marker_usage_index=marker_usage_index,
        note_kind_by_id=note_kind_by_id,
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
        footnote_ids_seen=footnote_ids_seen,
    )
    updated = _replace_raw_unicode_superscript_refs_with_local_labels(
        updated,
        marker_note_sequences=marker_note_sequences,
        marker_usage_index=marker_usage_index,
        note_kind_by_id=note_kind_by_id,
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
        footnote_ids_seen=footnote_ids_seen,
    )
    updated = replace_frozen_refs(updated)
    updated = re.sub(r"\s+(\[\^[^\]]+\])", r"\1", updated)
    return updated


def _chapter_page_numbers(chapter: Any) -> list[int]:
    pages = [int(page_no) for page_no in (getattr(chapter, "pages", []) or []) if int(page_no) > 0]
    if pages:
        return sorted(dict.fromkeys(pages))
    start_page = int(getattr(chapter, "start_page", 0) or 0)
    end_page = int(getattr(chapter, "end_page", start_page) or start_page)
    if start_page > 0 and end_page >= start_page:
        return list(range(start_page, end_page + 1))
    return []


def _build_section_heads_by_page(
    chapter_id: str,
    *,
    section_heads: list[SectionHeadRecord],
    chapter_pages: set[int],
) -> dict[int, list[str]]:
    payload: dict[int, list[str]] = {}
    for head in section_heads:
        if str(head.chapter_id or "") != str(chapter_id or ""):
            continue
        page_no = int(head.page_no or 0)
        if page_no <= 0 or (chapter_pages and page_no not in chapter_pages):
            continue
        if not _is_exportable_section_head(head):
            continue
        title = re.sub(r"\s+", " ", str(head.title or "").strip()).strip()
        if not title:
            continue
        payload.setdefault(page_no, []).append(title)
    return payload


def _build_raw_marker_note_sequences(
    chapter_id: str,
    *,
    matched_links: list[NoteLinkRecord],
    note_items_by_id: dict[str, NoteItemRecord],
    body_anchors_by_id: dict[str, BodyAnchorRecord],
    note_text_by_id: dict[str, str],
) -> dict[str, list[str]]:
    def _anchor_sort_key(anchor_id: str) -> tuple[int, int, int]:
        anchor = body_anchors_by_id.get(str(anchor_id or "").strip())
        if not anchor:
            return (0, 0, 0)
        return (
            int(anchor.page_no or 0),
            int(anchor.paragraph_index or 0),
            int(anchor.char_start or 0),
        )

    chapter_links = [
        link
        for link in matched_links
        if str(link.status or "") == "matched"
        and str(link.chapter_id or "") == str(chapter_id or "")
        and str(link.note_item_id or "").strip()
        and str(link.anchor_id or "").strip()
    ]
    chapter_links.sort(
        key=lambda link: (
            *_anchor_sort_key(str(link.anchor_id or "")),
            str(link.link_id or ""),
        )
    )
    sequences: dict[str, list[str]] = {}
    for link in chapter_links:
        note_item_id = str(link.note_item_id or "").strip()
        note_id = _resolve_note_id(note_item_id, note_text_by_id)
        if not note_id:
            continue
        anchor = body_anchors_by_id.get(str(link.anchor_id or "").strip())
        if anchor and bool(anchor.synthetic):
            continue
        note_item = note_items_by_id.get(note_item_id)
        marker_candidates: set[str] = set()
        marker_candidates.update(_marker_aliases(note_id))
        marker_candidates.update(_marker_aliases(str(link.marker or "")))
        if note_item:
            marker_candidates.update(_marker_aliases(str(note_item.marker or "")))
        if anchor:
            marker_candidates.update(_marker_aliases(str(anchor.normalized_marker or "")))
            marker_candidates.update(_marker_aliases(str(anchor.source_marker or "")))
            marker_candidates.update(_marker_aliases(str(anchor.ocr_repaired_from_marker or "")))
        for marker in marker_candidates:
            row = sequences.setdefault(marker, [])
            row.append(note_id)
    chapter_items = sorted(
        [
            item
            for item in note_items_by_id.values()
            if str(item.chapter_id or "") == str(chapter_id or "")
        ],
        key=lambda item: (
            int(item.page_no or 0),
            str(item.note_item_id or ""),
        ),
    )
    for item in chapter_items:
        note_item_id = str(item.note_item_id or "").strip()
        note_id = _resolve_note_id(note_item_id, note_text_by_id)
        if not note_id:
            continue
        marker_candidates: set[str] = set()
        marker_candidates.update(_marker_aliases(note_id))
        marker_candidates.update(_marker_aliases(str(item.marker or "")))
        for marker in marker_candidates:
            row = sequences.setdefault(marker, [])
            if note_id not in row:
                row.append(note_id)
    if sequences:
        return sequences

    fallback_note_ids = {
        _resolve_note_id(str(item.note_item_id or "").strip(), note_text_by_id)
        for item in note_items_by_id.values()
        if str(item.chapter_id or "") == str(chapter_id or "")
    }
    fallback_note_ids.discard("")
    if len(fallback_note_ids) != 1:
        return sequences
    fallback_note_id = next(iter(fallback_note_ids))
    for item in note_items_by_id.values():
        if str(item.chapter_id or "") != str(chapter_id or ""):
            continue
        for marker in _marker_aliases(str(item.marker or "")):
            row = sequences.setdefault(marker, [])
            if fallback_note_id not in row:
                row.append(fallback_note_id)
    return sequences


def _infer_book_note_type_from_modes(chapter_note_modes: list[Any]) -> str:
    modes = {
        str(row.note_mode or "").strip()
        for row in list(chapter_note_modes or [])
        if str(row.note_mode or "").strip() and str(row.note_mode or "").strip() != "no_notes"
    }
    has_footnote = "footnote_primary" in modes
    has_endnote = bool({"chapter_endnote_primary", "book_endnote_bound"} & modes)
    if has_footnote and has_endnote:
        return "mixed"
    if has_endnote:
        return "endnote_only"
    if has_footnote:
        return "footnote_only"
    return "no_notes"


def _format_chapter_title(title: str, _chapter_id: str = "") -> str:
    """对齐金标：Leçon du 章标题用全大写（原书印刷体例）。"""
    lower = str(title or "").lower().strip()
    if lower.startswith("leçon du "):
        return title.upper()
    return str(title or "")

def _build_section_markdown(
    chapter: Any,
    *,
    section_heads: list[SectionHeadRecord],
    body_units: list[TranslationUnitRecord],
    note_units: list[TranslationUnitRecord],
    matched_links: list[NoteLinkRecord],
    note_items_by_id: dict[str, NoteItemRecord],
    body_anchors_by_id: dict[str, BodyAnchorRecord],
    include_diagnostic_entries: bool,
    diagnostic_machine_by_page: dict[int, str],
    book_type: str,
    chapter_note_mode: str,
) -> tuple[str, dict[str, int]]:
    if str(book_type or "") == "mixed" and str(chapter_note_mode or "") == "footnote_primary":
        from FNM_RE.stages.export_footnote import _build_inline_footnote_section_markdown  # lazy to avoid circular import
        return _build_inline_footnote_section_markdown(
            chapter,
            section_heads=section_heads,
            body_units=body_units,
            note_units=note_units,
            matched_links=matched_links,
            note_items_by_id=note_items_by_id,
            body_anchors_by_id=body_anchors_by_id,
            include_diagnostic_entries=include_diagnostic_entries,
            diagnostic_machine_by_page=diagnostic_machine_by_page,
        )

    chapter_id = str(getattr(chapter, "chapter_id", "") or "")
    chapter_title = _format_chapter_title(getattr(chapter, "title", "") or chapter_id)
    chapter_pages = set(_chapter_page_numbers(chapter))
    note_text_by_id = _build_note_text_by_id_for_chapter(chapter_id, note_units=note_units)
    note_kind_by_id = _build_note_kind_by_id_for_chapter(chapter_id, note_units=note_units)
    marker_note_sequences = _build_raw_marker_note_sequences(
        chapter_id,
        matched_links=matched_links,
        note_items_by_id=note_items_by_id,
        body_anchors_by_id=body_anchors_by_id,
        note_text_by_id=note_text_by_id,
    )
    section_heads_by_page = _build_section_heads_by_page(
        chapter_id,
        section_heads=section_heads,
        chapter_pages=chapter_pages,
    )

    lines: list[str] = [f"## {chapter_title}", ""]
    seen_section_heads: set[tuple[int, str]] = set()
    local_ref_numbers: dict[str, int] = {}
    ordered_note_ids: list[str] = []
    footnote_ids_written: list[str] = []
    chapter_has_body = False

    sorted_units = sorted(
        [unit for unit in body_units if str(unit.section_id or "") == chapter_id],
        key=lambda row: (int(row.page_start or 0), int(row.page_end or int(row.page_start or 0)), str(row.unit_id or "")),
    )
    for unit in sorted_units:
        page_numbers = sorted(
            {
                int(segment.page_no or 0)
                for segment in unit.page_segments
                if int(segment.page_no or 0) > 0
            }
        )
        if not page_numbers and int(unit.page_start or 0) > 0:
            page_start = int(unit.page_start or 0)
            page_end = int(unit.page_end or page_start)
            page_numbers = list(range(page_start, page_end + 1))
        for page_no in page_numbers:
            for title in section_heads_by_page.get(page_no, []):
                dedupe_key = (int(page_no), title.lower())
                if dedupe_key in seen_section_heads:
                    continue
                seen_section_heads.add(dedupe_key)
                lines.append(f"### {title}")
                lines.append("")

        body_text = _resolve_body_unit_text(
            unit,
            include_diagnostic_entries=include_diagnostic_entries,
            diagnostic_machine_by_page=diagnostic_machine_by_page,
        )
        prev_footnote_count = len(footnote_ids_written)
        body_text = _rewrite_body_text_with_local_refs(
            body_text,
            note_text_by_id=note_text_by_id,
            note_kind_by_id=note_kind_by_id,
            marker_note_sequences=marker_note_sequences,
            local_ref_numbers=local_ref_numbers,
            ordered_note_ids=ordered_note_ids,
            footnote_ids_seen=footnote_ids_written,
        )
        if (
            not str(unit.translated_text or "").strip()
            and not include_diagnostic_entries
            and not note_text_by_id
            and _ANY_NOTE_REF_RE.search(body_text)
        ):
            body_text = PENDING_TRANSLATION_TEXT
        body_text = str(body_text or "").strip()
        if not body_text:
            continue
        chapter_has_body = True
        lines.append(body_text)
        # 阶段1.5：正文段落后紧跟新发现的 footnote 定义（[footnote] \* text）
        new_footnotes = footnote_ids_written[prev_footnote_count:]
        for fn_id in new_footnotes:
            fn_text = str(note_text_by_id.get(fn_id, "") or "").strip()
            if fn_text:
                lines.append(f"[footnote] \\* {fn_text}")
        lines.append("")

    if not chapter_has_body:
        lines.append(PENDING_TRANSLATION_TEXT)
        lines.append("")

    endnote_ids = [nid for nid in ordered_note_ids
                   if note_kind_by_id.get(nid, "") in ("endnote", "")]
    unknown_ids = [nid for nid in ordered_note_ids if nid not in note_kind_by_id]

    def _emit_definitions(ids: list[str]) -> None:
        rendered: list[str] = []
        for note_id in ids:
            number = int(local_ref_numbers.get(note_id) or 0)
            text = str(note_text_by_id.get(note_id) or "").strip()
            if number <= 0 or not text:
                continue
            rendered.append(f"[^{number}]: {text}")
        if not rendered:
            return
        lines.append("### NOTES")
        lines.append("")
        lines.extend(rendered)

    _emit_definitions(endnote_ids + unknown_ids)

    content = _strip_trailing_image_only_block("\n".join(lines).strip())
    refs = sorted(set(re.findall(r"\[\^([0-9]+)\]", content)))
    defs = sorted(set(re.findall(r"^\[\^([0-9]+)\]:", content, re.MULTILINE)))
    footnote_defs = re.findall(r"^\[footnote\]:", content, re.MULTILINE)
    missing = len(set(refs) - set(defs))
    effective_missing = max(0, missing - len(footnote_defs))
    contract_summary = {
        "local_ref_count": len(refs),
        "local_definition_count": len(defs) + len(footnote_defs),
        "missing_definition_count": effective_missing,
        "orphan_definition_count": len(set(defs) - set(refs)),
        "inline_footnote_paragraph_attach_count": 0,
        "inline_footnote_page_fallback_count": 0,
        "chapter_end_footnote_definition_count": len(defs) + len(footnote_defs),
    }
    return content, contract_summary


def _build_index_markdown(chapters: list[ExportChapterRecord]) -> str:
    lines = ["# 目录", ""]
    for chapter in chapters:
        if not str(chapter.path or "").strip():
            continue
        title = str(chapter.title or "Untitled").strip() or "Untitled"
        lines.append(f"- [{title}]({chapter.path})")
    return "\n".join(lines).rstrip() + "\n"


def _normalized_paragraph_key(text: str) -> str:
    normalized = str(text or "").strip().lower()
    normalized = re.sub(r"\[\^[^\]]+\]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def build_export_bundle(
    phase5: Phase5Structure,
    *,
    pages: list[dict],
    include_diagnostic_entries: bool = False,
) -> tuple[list[ExportChapterRecord], ExportBundleRecord, dict[str, Any]]:
    from FNM_RE.stages.export_contract import _build_export_chapters, _compute_export_semantic_contract
    del pages
    export_chapters, chapter_summary = _build_export_chapters(
        phase5,
        include_diagnostic_entries=bool(include_diagnostic_entries),
    )
    chapter_files = {
        chapter.path: _normalize_markdown_content(chapter.content)
        for chapter in export_chapters
    }
    files = dict(chapter_files)
    if export_chapters:
        files[OBSIDIAN_EXPORT_INDEX_MD] = _build_index_markdown(export_chapters)
    semantic = _compute_export_semantic_contract(
        chapters=export_chapters,
        chapter_files=chapter_files,
    )
    bundle = ExportBundleRecord(
        index_path=OBSIDIAN_EXPORT_INDEX_MD,
        chapters_dir=OBSIDIAN_EXPORT_CHAPTERS_DIR,
        chapters=list(export_chapters),
        chapter_files=chapter_files,
        files=files,
        export_semantic_contract_ok=bool(semantic.get("export_semantic_contract_ok", True)),
        front_matter_leak_detected=bool(semantic.get("front_matter_leak_detected", False)),
        toc_residue_detected=bool(semantic.get("toc_residue_detected", False)),
        mid_paragraph_heading_detected=bool(semantic.get("mid_paragraph_heading_detected", False)),
        duplicate_paragraph_detected=bool(semantic.get("duplicate_paragraph_detected", False)),
    )
    summary = {
        "export_bundle_summary": {
            "chapter_count": len(export_chapters),
            "chapter_file_count": len(chapter_files),
            "file_count": len(files),
            "index_path": OBSIDIAN_EXPORT_INDEX_MD,
            "include_diagnostic_entries": bool(include_diagnostic_entries),
            **dict(semantic or {}),
        },
        **dict(chapter_summary or {}),
    }
    return export_chapters, bundle, summary


def build_export_zip(bundle: ExportBundleRecord) -> bytes:
    files = dict(bundle.files or {})
    if str(bundle.index_path or OBSIDIAN_EXPORT_INDEX_MD) not in files and bundle.chapters:
        files[str(bundle.index_path or OBSIDIAN_EXPORT_INDEX_MD)] = _build_index_markdown(list(bundle.chapters or []))
    payload = BytesIO()
    with zipfile.ZipFile(payload, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files.keys()):
            raw_path = str(path or "").replace("\\", "/").strip().lstrip("/")
            segments = [segment for segment in raw_path.split("/") if segment]
            if not segments or any(segment in {".", ".."} for segment in segments):
                continue
            safe_path = "/".join(segments)
            archive.writestr(
                safe_path,
                _normalize_markdown_content(str(files.get(path) or "")),
            )
    return payload.getvalue()


# ── 向后兼容重导出 ──
from FNM_RE.stages.export_contract import (  # noqa: E402,F401
    _build_export_chapters,
    _compute_export_semantic_contract,
    _is_semantic_duplicate_candidate,
    _looks_like_bibliography_entry,
)
from FNM_RE.stages.export_footnote import (  # noqa: E402,F401
    _build_inline_footnote_section_markdown,
)

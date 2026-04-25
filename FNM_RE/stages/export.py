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


def _local_ref_number(
    note_id: str,
    *,
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
) -> int:
    if note_id not in local_ref_numbers:
        local_ref_numbers[note_id] = len(local_ref_numbers) + 1
        ordered_note_ids.append(note_id)
    return int(local_ref_numbers[note_id])


def _replace_note_refs_with_local_labels(
    text: str,
    *,
    note_text_by_id: dict[str, str],
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
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
        return f"[^{_local_ref_number(resolved, local_ref_numbers=local_ref_numbers, ordered_note_ids=ordered_note_ids)}]"

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
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
) -> str:
    def _replace(match: re.Match) -> str:
        note_id = _consume_marker_note_id(
            str(match.group(1) or ""),
            marker_note_sequences=marker_note_sequences,
            marker_usage_index=marker_usage_index,
        )
        if not note_id:
            return match.group(0)
        return f"[^{_local_ref_number(note_id, local_ref_numbers=local_ref_numbers, ordered_note_ids=ordered_note_ids)}]"

    return _RAW_BRACKET_NOTE_REF_RE.sub(_replace, str(text or ""))


def _replace_raw_superscript_refs_with_local_labels(
    text: str,
    *,
    marker_note_sequences: dict[str, list[str]],
    marker_usage_index: dict[str, int],
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
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
        return f"[^{_local_ref_number(note_id, local_ref_numbers=local_ref_numbers, ordered_note_ids=ordered_note_ids)}]"

    return _RAW_SUPERSCRIPT_NOTE_REF_RE.sub(_replace, str(text or ""))


def _replace_raw_unicode_superscript_refs_with_local_labels(
    text: str,
    *,
    marker_note_sequences: dict[str, list[str]],
    marker_usage_index: dict[str, int],
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
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
        return f"[^{_local_ref_number(note_id, local_ref_numbers=local_ref_numbers, ordered_note_ids=ordered_note_ids)}]"

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
    marker_note_sequences: dict[str, list[str]],
    local_ref_numbers: dict[str, int],
    ordered_note_ids: list[str],
) -> str:
    updated = _replace_note_refs_with_local_labels(
        text,
        note_text_by_id=note_text_by_id,
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
    )
    marker_usage_index: dict[str, int] = {}
    updated = _replace_raw_bracket_refs_with_local_labels(
        updated,
        marker_note_sequences=marker_note_sequences,
        marker_usage_index=marker_usage_index,
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
    )
    updated = _replace_raw_superscript_refs_with_local_labels(
        updated,
        marker_note_sequences=marker_note_sequences,
        marker_usage_index=marker_usage_index,
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
    )
    updated = _replace_raw_unicode_superscript_refs_with_local_labels(
        updated,
        marker_note_sequences=marker_note_sequences,
        marker_usage_index=marker_usage_index,
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
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


def _paragraph_attr(paragraph: Any, key: str, default: Any = "") -> Any:
    if isinstance(paragraph, dict):
        return paragraph.get(key, default)
    return getattr(paragraph, key, default)


def _visible_segment_paragraphs(segment: Any) -> list[Any]:
    paragraphs = []
    for paragraph in list(getattr(segment, "paragraphs", []) or []):
        if bool(_paragraph_attr(paragraph, "consumed_by_prev", False)):
            continue
        paragraphs.append(paragraph)
    return paragraphs


def _paragraph_render_text(paragraph: Any) -> str:
    translated = str(_paragraph_attr(paragraph, "translated_text", "") or "").strip()
    if translated:
        return translated
    display = str(_paragraph_attr(paragraph, "display_text", "") or "").strip()
    if display:
        return display
    return str(_paragraph_attr(paragraph, "source_text", "") or "").strip()


def _append_note_ids(target: dict[Any, list[str]], key: Any, note_id: str) -> None:
    if not note_id:
        return
    row = target.setdefault(key, [])
    if note_id not in row:
        row.append(note_id)


def _emit_local_note_definitions(
    note_ids: list[str],
    *,
    lines: list[str],
    emitted_note_ids: set[str],
    local_ref_numbers: dict[str, int],
    note_text_by_id: dict[str, str],
) -> int:
    emitted = 0
    for note_id in note_ids:
        if note_id in emitted_note_ids:
            continue
        number = int(local_ref_numbers.get(note_id) or 0)
        text = str(note_text_by_id.get(note_id) or "").strip()
        if number <= 0 or not text:
            continue
        lines.append(f"[^{number}]: {_escape_leading_asterisks(text)}")
        lines.append("")
        emitted_note_ids.add(note_id)
        emitted += 1
    return emitted


def _build_inline_footnote_targets(
    chapter_id: str,
    *,
    matched_links: list[NoteLinkRecord],
    note_items_by_id: dict[str, NoteItemRecord],
    body_anchors_by_id: dict[str, BodyAnchorRecord],
    note_text_by_id: dict[str, str],
) -> tuple[dict[tuple[int, int], list[str]], dict[int, list[str]]]:
    chapter_links = [
        link
        for link in matched_links
        if str(link.chapter_id or "") == str(chapter_id or "")
        and str(link.note_kind or "") == "footnote"
        and str(link.status or "") == "matched"
        and str(link.note_item_id or "").strip()
    ]
    chapter_links.sort(
        key=lambda link: (
            int(body_anchors_by_id.get(str(link.anchor_id or "").strip(), BodyAnchorRecord("", "", 0, 0, 0, 0, "", "", "unknown", 0.0, "", "", False, "")).page_no or 0),
            int(body_anchors_by_id.get(str(link.anchor_id or "").strip(), BodyAnchorRecord("", "", 0, 0, 0, 0, "", "", "unknown", 0.0, "", "", False, "")).paragraph_index or 0),
            int(body_anchors_by_id.get(str(link.anchor_id or "").strip(), BodyAnchorRecord("", "", 0, 0, 0, 0, "", "", "unknown", 0.0, "", "", False, "")).char_start or 0),
            str(link.link_id or ""),
        )
    )
    attached: dict[tuple[int, int], list[str]] = {}
    page_fallback: dict[int, list[str]] = {}
    for link in chapter_links:
        note_item_id = str(link.note_item_id or "").strip()
        note_id = _resolve_note_id(note_item_id, note_text_by_id)
        if not note_id or not str(note_text_by_id.get(note_id) or "").strip():
            continue
        note_item = note_items_by_id.get(note_item_id)
        anchor = body_anchors_by_id.get(str(link.anchor_id or "").strip())
        note_page = 0
        if anchor is not None and int(anchor.page_no or 0) > 0:
            note_page = int(anchor.page_no or 0)
        elif note_item is not None and int(note_item.page_no or 0) > 0:
            note_page = int(note_item.page_no or 0)
        else:
            note_page = int(link.page_no_start or 0)
        if anchor is not None and not bool(anchor.synthetic) and int(anchor.page_no or 0) > 0:
            _append_note_ids(attached, (int(anchor.page_no or 0), int(anchor.paragraph_index or 0)), note_id)
            continue
        if note_page > 0:
            _append_note_ids(page_fallback, note_page, note_id)
    return attached, page_fallback


def _build_inline_footnote_section_markdown(
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
) -> tuple[str, dict[str, int]]:
    chapter_id = str(getattr(chapter, "chapter_id", "") or "")
    chapter_title = str(getattr(chapter, "title", "") or chapter_id)
    chapter_pages = set(_chapter_page_numbers(chapter))
    note_text_by_id = _build_note_text_by_id_for_chapter(chapter_id, note_units=note_units)
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
    attached_note_ids, page_fallback_note_ids = _build_inline_footnote_targets(
        chapter_id,
        matched_links=matched_links,
        note_items_by_id=note_items_by_id,
        body_anchors_by_id=body_anchors_by_id,
        note_text_by_id=note_text_by_id,
    )

    page_paragraphs: dict[int, list[Any]] = {}
    sorted_units = sorted(
        [unit for unit in body_units if str(unit.section_id or "") == chapter_id],
        key=lambda row: (int(row.page_start or 0), int(row.page_end or int(row.page_start or 0)), str(row.unit_id or "")),
    )
    for unit in sorted_units:
        for segment in sorted(
            [segment for segment in list(unit.page_segments or []) if int(segment.page_no or 0) > 0],
            key=lambda row: int(row.page_no or 0),
        ):
            page_no = int(segment.page_no or 0)
            visible = _visible_segment_paragraphs(segment)
            if visible:
                page_paragraphs.setdefault(page_no, []).extend(visible)
                continue
            fallback_text = str(segment.display_text or segment.source_text or "").strip()
            if not fallback_text:
                continue
            page_paragraphs.setdefault(page_no, []).append(
                {
                    "kind": "body",
                    "display_text": fallback_text,
                    "source_text": str(segment.source_text or fallback_text),
                    "translated_text": "",
                    "consumed_by_prev": False,
                }
            )

    lines: list[str] = [f"## {chapter_title}", ""]
    seen_section_heads: set[tuple[int, str]] = set()
    local_ref_numbers: dict[str, int] = {}
    ordered_note_ids: list[str] = []
    emitted_note_ids: set[str] = set()
    chapter_has_body = False
    inline_attach_count = 0
    page_fallback_count = 0

    for page_no in sorted(page_paragraphs.keys()):
        for title in section_heads_by_page.get(page_no, []):
            dedupe_key = (int(page_no), title.lower())
            if dedupe_key in seen_section_heads:
                continue
            seen_section_heads.add(dedupe_key)
            lines.append(f"### {title}")
            lines.append("")

        body_paragraph_index = 0
        page_has_body = False
        for paragraph in page_paragraphs.get(page_no, []):
            kind = str(_paragraph_attr(paragraph, "kind", "body") or "body").strip().lower()
            text = _paragraph_render_text(paragraph)
            if not text:
                continue
            if _normalized_paragraph_key(text) == _normalized_paragraph_key(chapter_title):
                continue
            if kind == "heading":
                heading_title = re.sub(r"\s+", " ", text).strip()
                if not heading_title or _normalized_paragraph_key(heading_title) == _normalized_paragraph_key(chapter_title):
                    continue
                dedupe_key = (int(page_no), heading_title.lower())
                if dedupe_key in seen_section_heads:
                    continue
                seen_section_heads.add(dedupe_key)
                lines.append(f"### {heading_title}")
                lines.append("")
                continue

            body_text = _rewrite_body_text_with_local_refs(
                text,
                note_text_by_id=note_text_by_id,
                marker_note_sequences=marker_note_sequences,
                local_ref_numbers=local_ref_numbers,
                ordered_note_ids=ordered_note_ids,
            )
            if (
                not str(_paragraph_attr(paragraph, "translated_text", "") or "").strip()
                and not include_diagnostic_entries
                and not note_text_by_id
                and _ANY_NOTE_REF_RE.search(body_text)
            ):
                body_text = PENDING_TRANSLATION_TEXT
            body_text = str(body_text or "").strip()
            if not body_text:
                body_paragraph_index += 1
                continue
            lines.append(_escape_leading_asterisks(body_text))
            lines.append("")
            chapter_has_body = True
            page_has_body = True
            inline_attach_count += _emit_local_note_definitions(
                list(attached_note_ids.get((page_no, body_paragraph_index), []) or []),
                lines=lines,
                emitted_note_ids=emitted_note_ids,
                local_ref_numbers=local_ref_numbers,
                note_text_by_id=note_text_by_id,
            )
            body_paragraph_index += 1

        remaining_page_note_ids: list[str] = []
        for (target_page_no, target_paragraph_index), note_ids in sorted(attached_note_ids.items()):
            if int(target_page_no) != int(page_no):
                continue
            if int(target_paragraph_index) >= int(body_paragraph_index):
                remaining_page_note_ids.extend(note_ids)
        remaining_page_note_ids.extend(list(page_fallback_note_ids.get(page_no) or []))
        if page_has_body:
            page_fallback_count += _emit_local_note_definitions(
                remaining_page_note_ids,
                lines=lines,
                emitted_note_ids=emitted_note_ids,
                local_ref_numbers=local_ref_numbers,
                note_text_by_id=note_text_by_id,
            )

    if not chapter_has_body:
        lines.append(PENDING_TRANSLATION_TEXT)
        lines.append("")

    chapter_end_count = _emit_local_note_definitions(
        list(ordered_note_ids),
        lines=lines,
        emitted_note_ids=emitted_note_ids,
        local_ref_numbers=local_ref_numbers,
        note_text_by_id=note_text_by_id,
    )
    content = _strip_trailing_image_only_block("\n".join(lines).strip())
    refs = sorted(set(re.findall(r"\[\^([0-9]+)\]", content)))
    defs = sorted(set(re.findall(r"^\[\^([0-9]+)\]:", content, re.MULTILINE)))
    contract_summary = {
        "local_ref_count": len(refs),
        "local_definition_count": len(defs),
        "missing_definition_count": len(set(refs) - set(defs)),
        "orphan_definition_count": len(set(defs) - set(refs)),
        "inline_footnote_paragraph_attach_count": int(inline_attach_count),
        "inline_footnote_page_fallback_count": int(page_fallback_count),
        "chapter_end_footnote_definition_count": int(chapter_end_count),
    }
    return content, contract_summary


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
    chapter_title = str(getattr(chapter, "title", "") or chapter_id)
    chapter_pages = set(_chapter_page_numbers(chapter))
    note_text_by_id = _build_note_text_by_id_for_chapter(chapter_id, note_units=note_units)
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
        body_text = _rewrite_body_text_with_local_refs(
            body_text,
            note_text_by_id=note_text_by_id,
            marker_note_sequences=marker_note_sequences,
            local_ref_numbers=local_ref_numbers,
            ordered_note_ids=ordered_note_ids,
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
        lines.append("")

    if not chapter_has_body:
        lines.append(PENDING_TRANSLATION_TEXT)
        lines.append("")

    for note_id in ordered_note_ids:
        number = int(local_ref_numbers.get(note_id) or 0)
        text = str(note_text_by_id.get(note_id) or "").strip()
        if number <= 0 or not text:
            continue
        lines.append(f"[^{number}]: {text}")

    content = _strip_trailing_image_only_block("\n".join(lines).strip())
    refs = sorted(set(re.findall(r"\[\^([0-9]+)\]", content)))
    defs = sorted(set(re.findall(r"^\[\^([0-9]+)\]:", content, re.MULTILINE)))
    contract_summary = {
        "local_ref_count": len(refs),
        "local_definition_count": len(defs),
        "missing_definition_count": len(set(refs) - set(defs)),
        "orphan_definition_count": len(set(defs) - set(refs)),
        "inline_footnote_paragraph_attach_count": 0,
        "inline_footnote_page_fallback_count": 0,
        "chapter_end_footnote_definition_count": len(defs),
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


def _is_semantic_duplicate_candidate(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    if not normalized:
        return False
    if normalized.startswith("#"):
        return False
    if len(normalized) < 80:
        return False
    words = [token for token in normalized.split(" ") if token]
    if len(words) < 12:
        return False
    return bool(re.search(r"[.!?;:。！？；：]", normalized))


def _looks_like_bibliography_entry(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    if not normalized:
        return False
    if not re.search(r"\b\d{4}\.?\s*$", normalized):
        return False
    return bool(re.search(r":\s*[^:]{6,},\s*\d{4}\.?\s*$", normalized))


def _compute_export_semantic_contract(
    *,
    chapters: list[ExportChapterRecord],
    chapter_files: dict[str, str],
) -> dict[str, bool]:
    front_matter_leak_detected = any(
        bool(_FRONT_MATTER_TITLE_RE.match(str(chapter.title or "").strip()))
        for chapter in chapters
    )
    toc_residue_detected = any(
        bool(_TOC_RESIDUE_RE.search(str(content or "")))
        for content in chapter_files.values()
    )
    mid_paragraph_heading_detected = False
    duplicate_paragraph_detected = False

    for content in chapter_files.values():
        lines = str(content or "").splitlines()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("### "):
                continue
            prev = lines[idx - 1].strip() if idx > 0 else ""
            if prev and not prev.startswith("#"):
                mid_paragraph_heading_detected = True
                break
        if mid_paragraph_heading_detected:
            break

    for content in chapter_files.values():
        seen: set[str] = set()
        for paragraph in re.split(r"\n\s*\n+", str(content or "")):
            if not _is_semantic_duplicate_candidate(paragraph):
                continue
            if _looks_like_bibliography_entry(paragraph):
                continue
            key = _normalized_paragraph_key(paragraph)
            if len(key) < 60:
                continue
            if key in seen:
                duplicate_paragraph_detected = True
                break
            seen.add(key)
        if duplicate_paragraph_detected:
            break

    export_semantic_contract_ok = not any(
        (
            front_matter_leak_detected,
            toc_residue_detected,
            mid_paragraph_heading_detected,
            duplicate_paragraph_detected,
        )
    )
    return {
        "export_semantic_contract_ok": bool(export_semantic_contract_ok),
        "front_matter_leak_detected": bool(front_matter_leak_detected),
        "toc_residue_detected": bool(toc_residue_detected),
        "mid_paragraph_heading_detected": bool(mid_paragraph_heading_detected),
        "duplicate_paragraph_detected": bool(duplicate_paragraph_detected),
    }


def _build_export_chapters(
    phase5: Phase5Structure,
    *,
    include_diagnostic_entries: bool,
) -> tuple[list[ExportChapterRecord], dict[str, Any]]:
    chapters = sorted(
        list(phase5.chapters or []),
        key=lambda row: (int(row.start_page or 0), str(row.chapter_id or "")),
    )
    body_units = [unit for unit in phase5.translation_units if str(unit.kind or "") == "body"]
    note_units = [unit for unit in phase5.translation_units if str(unit.kind or "") in {"footnote", "endnote"}]
    matched_links = [
        link
        for link in phase5.effective_note_links
        if str(link.status or "") == "matched"
        and str(link.note_item_id or "").strip()
        and str(link.anchor_id or "").strip()
    ]
    note_items_by_id = {
        str(item.note_item_id or "").strip(): item
        for item in phase5.note_items
        if str(item.note_item_id or "").strip()
    }
    body_anchors_by_id = {
        str(anchor.anchor_id or "").strip(): anchor
        for anchor in phase5.body_anchors
        if str(anchor.anchor_id or "").strip()
    }
    diagnostic_machine_by_page = _diagnostic_machine_text_by_page(phase5)
    chapter_note_mode_by_id = {
        str(row.chapter_id or ""): str(row.note_mode or "no_notes")
        for row in list(phase5.chapter_note_modes or [])
        if str(row.chapter_id or "").strip()
    }
    summary_book_type = str(
        dict(getattr(getattr(phase5, "summary", None), "chapter_note_mode_summary", {}) or {}).get("book_type") or ""
    ).strip()
    book_type = (
        summary_book_type
        if summary_book_type in {"mixed", "endnote_only", "footnote_only", "no_notes"}
        else _infer_book_note_type_from_modes(list(phase5.chapter_note_modes or []))
    )
    used_filenames: set[str] = set()

    chapter_records: list[ExportChapterRecord] = []
    contract_items: list[dict[str, Any]] = []
    inline_footnote_paragraph_attach_count = 0
    inline_footnote_page_fallback_count = 0
    chapter_end_footnote_definition_count = 0
    for order, chapter in enumerate(chapters, start=1):
        chapter_id = str(chapter.chapter_id or "").strip()
        if not chapter_id:
            continue
        title = str(chapter.title or chapter_id)
        content, contract_summary = _build_section_markdown(
            chapter,
            section_heads=list(phase5.section_heads or []),
            body_units=body_units,
            note_units=note_units,
            matched_links=matched_links,
            note_items_by_id=note_items_by_id,
            body_anchors_by_id=body_anchors_by_id,
            include_diagnostic_entries=bool(include_diagnostic_entries),
            diagnostic_machine_by_page=diagnostic_machine_by_page,
            book_type=book_type,
            chapter_note_mode=str(chapter_note_mode_by_id.get(chapter_id) or "no_notes"),
        )
        inline_footnote_paragraph_attach_count += int(contract_summary.get("inline_footnote_paragraph_attach_count") or 0)
        inline_footnote_page_fallback_count += int(contract_summary.get("inline_footnote_page_fallback_count") or 0)
        chapter_end_footnote_definition_count += int(contract_summary.get("chapter_end_footnote_definition_count") or 0)
        filename = _build_chapter_filename(order, title, used_filenames=used_filenames)
        chapter_records.append(
            ExportChapterRecord(
                order=order,
                section_id=chapter_id,
                title=title,
                path=f"{OBSIDIAN_EXPORT_CHAPTERS_PREFIX}{filename}",
                content=content,
                start_page=int(chapter.start_page or 0),
                end_page=int(chapter.end_page or int(chapter.start_page or 0)),
                pages=_chapter_page_numbers(chapter),
            )
        )
        contract_items.append(
            {
                "section_id": chapter_id,
                "title": title,
                **dict(contract_summary or {}),
            }
        )
    summary = {
        "chapter_ref_contract_summary": {
            "chapter_count": len(contract_items),
            "chapter_local_contract_ok_count": sum(
                1
                for item in contract_items
                if int(item.get("missing_definition_count") or 0) == 0
                and int(item.get("orphan_definition_count") or 0) == 0
            ),
            "items": contract_items,
        },
        "inline_footnote_paragraph_attach_count": int(inline_footnote_paragraph_attach_count),
        "inline_footnote_page_fallback_count": int(inline_footnote_page_fallback_count),
        "chapter_end_footnote_definition_count": int(chapter_end_footnote_definition_count),
    }
    return chapter_records, summary


def build_export_bundle(
    phase5: Phase5Structure,
    *,
    pages: list[dict],
    include_diagnostic_entries: bool = False,
) -> tuple[list[ExportChapterRecord], ExportBundleRecord, dict[str, Any]]:
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

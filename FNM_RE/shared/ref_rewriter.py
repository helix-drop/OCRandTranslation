"""注释引用重写工具。

从 stages/export.py 提取，供 export.py 和 chapter_merge.py 共用，
消除 modules → stages 跨层私有函数引用。
"""

from __future__ import annotations

import re
from typing import Any

from FNM_RE.shared.export_constants import (
    _ANY_NOTE_REF_RE,
    _RAW_BRACKET_NOTE_REF_RE,
    _RAW_SUPERSCRIPT_NOTE_REF_RE,
    _RAW_UNICODE_SUPERSCRIPT_NOTE_REF_RE,
    _UNICODE_SUPERSCRIPT_TRANSLATION,
)


def _marker_key(raw: Any) -> str:
    normalized = str(raw or "").strip().translate(_UNICODE_SUPERSCRIPT_TRANSLATION).lower()
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
    kind = _resolve_note_kind(note_id, note_kind_by_id=note_kind_by_id)
    if kind == "footnote":
        return None
    if note_id not in local_ref_numbers:
        local_ref_numbers[note_id] = len(local_ref_numbers) + 1
        ordered_note_ids.append(note_id)
    return int(local_ref_numbers[note_id])


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


def replace_note_refs_with_local_labels(
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


def replace_raw_bracket_refs_with_local_labels(
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


def replace_raw_superscript_refs_with_local_labels(
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


def replace_raw_unicode_superscript_refs_with_local_labels(
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

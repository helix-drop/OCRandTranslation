"""Note text/kind 查找共享工具。

在 export.py 和 chapter_merge.py 中各有独立版本。
"""

from __future__ import annotations

from typing import Any

from FNM_RE.models import TranslationUnitRecord


def _sanitize_note_text(text: str) -> str:
    """Note text cleanup: strip body markup, leading markers, normalize whitespace."""
    import re
    from FNM_RE.stages.export import _NOTE_TEXT_BODY_MARKUP_RE, _LEADING_RAW_NOTE_MARKER_RE
    payload = str(text or "").strip()
    payload = _NOTE_TEXT_BODY_MARKUP_RE.sub("", payload).strip()
    payload = _LEADING_RAW_NOTE_MARKER_RE.sub("", payload).strip()
    payload = re.sub(r"\s+", " ", payload).strip()
    return payload


def build_note_text_by_id_for_chapter(
    chapter_id: str,
    *,
    note_units: list[TranslationUnitRecord],
) -> dict[str, str]:
    payload: dict[str, str] = {}
    from FNM_RE.stages.export import _should_replace_definition_text
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


def build_note_kind_by_id_for_chapter(
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

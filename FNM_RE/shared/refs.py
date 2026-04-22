"""FNM_RE 冻结引用 token 工具。"""

from __future__ import annotations

import re

_NOTE_REF_RE = re.compile(r"\{\{NOTE_REF:([^}]+)\}\}")
_FN_REF_RE = re.compile(r"\{\{FN_REF:([^}]+)\}\}")
_EN_REF_RE = re.compile(r"\{\{EN_REF:([^}]+)\}\}")
_VISIBLE_ENDNOTE_RE = re.compile(r"\[\^(en-[^\]]+)\]", re.IGNORECASE)
_VISIBLE_EN_BRACKET_RE = re.compile(r"\[EN-([^\]]+)\]", re.IGNORECASE)
_VISIBLE_FN_RE = re.compile(r"\[FN-([^\]]+)\]", re.IGNORECASE)
_VISIBLE_FOOTNOTE_RE = re.compile(r"\[\^((?!en-)[^\]]+)\]", re.IGNORECASE)


def frozen_note_ref(note_id: str) -> str:
    token = str(note_id or "").strip()
    return f"{{{{NOTE_REF:{token}}}}}" if token else ""


def note_kind_from_id(note_id: str) -> str:
    token = str(note_id or "").strip().lower()
    return "endnote" if token.startswith("en-") else "footnote"


def _normalize_endnote_label(note_id: str) -> str:
    token = str(note_id or "").strip()
    if not token:
        return ""
    return token if token.lower().startswith("en-") else f"en-{token}"


def replace_frozen_refs(text: str, *, endnote_mode: str = "legacy") -> str:
    mode = str(endnote_mode or "legacy").strip().lower()
    if mode not in {"legacy", "standard"}:
        raise ValueError(f"Unsupported endnote_mode: {endnote_mode}")
    payload = str(text or "")

    def _replace_note_ref(match: re.Match) -> str:
        note_id = str(match.group(1) or "").strip()
        if not note_id:
            return ""
        if note_kind_from_id(note_id) == "endnote":
            return f"[^{_normalize_endnote_label(note_id)}]" if mode == "standard" else f"[EN-{note_id}]"
        return f"[^{note_id}]"

    payload = _NOTE_REF_RE.sub(_replace_note_ref, payload)
    payload = _FN_REF_RE.sub(lambda m: f"[^{str(m.group(1) or '').strip()}]", payload)
    if mode == "standard":
        payload = _EN_REF_RE.sub(
            lambda m: f"[^{_normalize_endnote_label(str(m.group(1) or '').strip())}]",
            payload,
        )
        payload = _VISIBLE_EN_BRACKET_RE.sub(
            lambda m: f"[^{_normalize_endnote_label(str(m.group(1) or '').strip())}]",
            payload,
        )
        payload = re.sub(r"\s+(\[\^[^\]]+\])", r"\1", payload)
    else:
        payload = _EN_REF_RE.sub(lambda m: f"[EN-{str(m.group(1) or '').strip()}]", payload)
        payload = re.sub(r"\s+(\[\^[^\]]+\]|\[EN-[^\]]+\])", r"\1", payload)
    return payload


def extract_note_refs(text: str) -> list[dict]:
    content = str(text or "")
    matches: list[tuple[int, str, str]] = []
    patterns = [
        ("generic", _NOTE_REF_RE),
        ("footnote", _FN_REF_RE),
        ("endnote", _EN_REF_RE),
        ("endnote", _VISIBLE_ENDNOTE_RE),
        ("endnote", _VISIBLE_EN_BRACKET_RE),
        ("footnote", _VISIBLE_FN_RE),
        ("footnote", _VISIBLE_FOOTNOTE_RE),
    ]
    for kind, pattern in patterns:
        for matched in pattern.finditer(content):
            note_id = str(matched.group(1) or "").strip()
            if not note_id:
                continue
            resolved_kind = note_kind_from_id(note_id) if kind == "generic" else kind
            matches.append((matched.start(), resolved_kind, note_id))

    refs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for _pos, kind, note_id in sorted(matches, key=lambda row: row[0]):
        key = (kind, note_id)
        if key in seen:
            continue
        seen.add(key)
        refs.append({"kind": kind, "note_id": note_id})
    return refs

"""FNM_RE 冻结引用 token 工具。"""

from __future__ import annotations

import re

_NOTE_REF_RE = re.compile(r"\{\{NOTE_REF:([^}]+)\}\}")
_FN_REF_RE = re.compile(r"\{\{FN_REF:([^}]+)\}\}")
_EN_REF_RE = re.compile(r"\{\{EN_REF:([^}]+)\}\}")
_VISIBLE_ENDNOTE_RE = re.compile(r"\[\^(en-[^\]]+)\]", re.IGNORECASE)
_VISIBLE_FOOTNOTE_RE = re.compile(r"\[\^((?!en-)[^\]]+)\]", re.IGNORECASE)


_NESTED_NOTE_REF_RE = re.compile(
    r"\{\{NOTE_REF:([^}]*?)\{\{NOTE_REF:([^}]+)\}\}([^}]*?)\}\}", re.IGNORECASE
)
_NOTE_REF_TOKEN_RE = re.compile(r"\{\{NOTE_REF:[^}]+\}\}", re.IGNORECASE)
_SPLIT_NOTE_REF_RE = re.compile(
    r"\{\{NO(\{\{NOTE_REF:([^}]+)\}\})TE_REF:([^}]+)\}\}",
    re.IGNORECASE,
)


def cleanup_nested_note_refs(text: str) -> str:
    """修复嵌套的 {{NOTE_REF:...{{NOTE_REF:...}}...}} 结构。

    _inject_token_once 对同一区域多次替换时可能造出嵌套 NOTE_REF。
    此函数检测并拆分为两个独立的 NOTE_REF。
    """
    payload = str(text or "")
    changed = True
    while changed:
        changed = False
        split_match = _SPLIT_NOTE_REF_RE.search(payload)
        if split_match:
            inner_token = str(split_match.group(1) or "")
            outer_id = str(split_match.group(3) or "")
            outer_token = f"{{{{NOTE_REF:{outer_id}}}}}"
            replacement = _SPLIT_NOTE_REF_RE.sub(
                lambda _m: f"{outer_token} {inner_token}",
                payload,
                count=1,
            )
            if replacement != payload:
                payload = replacement
                changed = True
                continue
        match = _NESTED_NOTE_REF_RE.search(payload)
        if match:
            outer_prefix = str(match.group(1) or "")
            inner_id = str(match.group(2) or "")
            outer_suffix = str(match.group(3) or "")
            outer_full = outer_prefix + inner_id + outer_suffix
            outer_token = f"{{{{NOTE_REF:{outer_full}}}}}"
            inner_token = f"{{{{NOTE_REF:{inner_id}}}}}"
            replacement = _NESTED_NOTE_REF_RE.sub(
                lambda m: f"{inner_token} {outer_token}" if (m.group(1) or m.group(3)) else inner_token,
                payload,
                count=1,
            )
            if replacement != payload:
                payload = replacement
                changed = True
    return payload


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


def replace_frozen_refs(text: str, *, endnote_mode: str = "standard") -> str:
    mode = str(endnote_mode or "standard").strip().lower()
    if mode not in {"legacy", "standard"}:
        raise ValueError(f"Unsupported endnote_mode: {endnote_mode}")
    payload = str(text or "")

    def _replace_note_ref(match: re.Match) -> str:
        note_id = str(match.group(1) or "").strip()
        if not note_id:
            return ""
        if note_kind_from_id(note_id) == "endnote":
            return f"[^{_normalize_endnote_label(note_id)}]"
        return f"[^{note_id}]"

    payload = _NOTE_REF_RE.sub(_replace_note_ref, payload)
    payload = _FN_REF_RE.sub(lambda m: f"[^{str(m.group(1) or '').strip()}]", payload)
    payload = _EN_REF_RE.sub(
        lambda m: f"[^{_normalize_endnote_label(str(m.group(1) or '').strip())}]",
        payload,
    )
    payload = re.sub(r"\s+(\[\^[^\]]+\])", r"\1", payload)
    return payload


def extract_note_refs(text: str) -> list[dict]:
    content = str(text or "")
    matches: list[tuple[int, str, str]] = []
    patterns = [
        ("generic", _NOTE_REF_RE),
        ("footnote", _FN_REF_RE),
        ("endnote", _EN_REF_RE),
        ("endnote", _VISIBLE_ENDNOTE_RE),
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

"""Note text 清理共享工具。"""

from __future__ import annotations


def _sanitize_note_text(text: str) -> str:
    """Note text cleanup: strip body markup, leading markers, normalize whitespace."""
    import re
    from FNM_RE.shared.export_constants import _NOTE_TEXT_BODY_MARKUP_RE, _LEADING_RAW_NOTE_MARKER_RE
    payload = str(text or "").strip()
    payload = _NOTE_TEXT_BODY_MARKUP_RE.sub("", payload).strip()
    payload = _LEADING_RAW_NOTE_MARKER_RE.sub("", payload).strip()
    payload = re.sub(r"\s+", " ", payload).strip()
    return payload



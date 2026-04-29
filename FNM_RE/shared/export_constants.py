"""导出相关共享常量与辅助函数。

从 stages/export.py 提取，作为 shared/note_lookup.py、stages/export_contract.py、
stages/export_footnote.py 和 modules/chapter_merge.py 的单一依赖源，
打破 shared → stages 的循环导入。
"""

from __future__ import annotations

import re

PENDING_TRANSLATION_TEXT = "[待翻译]"
OBSIDIAN_EXPORT_CHAPTERS_PREFIX = "chapters/"

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
_TRAILING_IMAGE_ONLY_BLOCK_RE = re.compile(
    r"(?:\n\s*)*(?:<div[^>]*>\s*<img\b[^>]*>\s*</div>|!\[[^\]]*\]\([^)]+\))\s*$",
    re.IGNORECASE | re.DOTALL,
)
_FRONT_MATTER_TITLE_RE = re.compile(
    r"^(?:preface|foreword|acknowledg(?:e)?ments?|remerciements?|avant-propos|table of contents|contents|目录)\b",
    re.IGNORECASE,
)
_TOC_RESIDUE_RE = re.compile(r"(?im)^\s*(?:table of contents|contents|目录)\b")

# ── ref_rewriter 依赖的正则常量 ──

_RAW_BRACKET_NOTE_REF_RE = re.compile(r"(?<!\d)\[(\d{1,4}[A-Za-z]?)\](?!\d)")
_RAW_SUPERSCRIPT_NOTE_REF_RE = re.compile(
    r"\$\s*\^\{\s*\[?(\d{1,4}[A-Za-z]?)\]?\s*\}\s*\$"
    r"|\$\s*\^\{\s*(\*{1,4})\s*\}\s*\$"
    r"|<sup>\s*\[?(\d{1,4}[A-Za-z]?)\]?\s*</sup>",
    re.IGNORECASE,
)
_RAW_UNICODE_SUPERSCRIPT_NOTE_REF_RE = re.compile(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")
_UNICODE_SUPERSCRIPT_TRANSLATION = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


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

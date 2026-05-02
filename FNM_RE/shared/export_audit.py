"""导出文本审计工具（从 scripts/test_fnm_batch.py 提取）。"""

from __future__ import annotations

import re
from typing import Any

LOCAL_REF_RE = re.compile(r"\[\^([0-9]+)\]")
LOCAL_DEF_RE = re.compile(r"^\[\^([0-9]+)\]:", re.MULTILINE)
LEGACY_FOOTNOTE_RE = re.compile(r"\[FN-[^\]]+\]", re.IGNORECASE)
LEGACY_ENDNOTE_RE = re.compile(r"\[\^en-[^\]]+\]", re.IGNORECASE)
LEGACY_EN_BRACKET_RE = re.compile(r"\[EN-[^\]]+\]", re.IGNORECASE)
LEGACY_NOTE_TOKEN_RE = re.compile(
    r"\{\{(?:NOTE_REF|FN_REF|EN_REF):[^}]+\}\}", re.IGNORECASE
)
RAW_NOTE_HEADING_RE = re.compile(
    r"^(?!##\s*)(NOTES|ENDNOTES)\s*$", re.IGNORECASE | re.MULTILINE
)
SECTION_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
FORBIDDEN_SECTION_HEAD_PREFIX_RE = re.compile(
    r"^\d+\.\s*(?:ibid|cf\.?|see|supra|infra)\b",
    re.IGNORECASE,
)
SECTION_HEAD_INLINE_NOTE_TRACE_RE = re.compile(
    r"(?:<sup>|\[\^[^\]]+\]|\$\s*\^\{[^}]+\}\s*\$)",
    re.IGNORECASE,
)


def _numeric_first_sort_key(value: str) -> tuple[int, int | str]:
    text = str(value or "").strip()
    if text.isdigit():
        return (0, int(text))
    return (1, text)


def _split_body_and_definition_text(content: str) -> tuple[str, str]:
    body_lines: list[str] = []
    definition_lines: list[str] = []
    in_definition_block = False
    for raw_line in str(content or "").splitlines():
        if LOCAL_DEF_RE.match(raw_line):
            in_definition_block = True
            definition_lines.append(raw_line)
            continue
        if in_definition_block and (
            raw_line.startswith("    ") or raw_line.startswith("\t")
        ):
            definition_lines.append(raw_line)
            continue
        in_definition_block = False
        body_lines.append(raw_line)
    return "\n".join(body_lines), "\n".join(definition_lines)


def _looks_like_sentence_heading(title: str) -> bool:
    text = re.sub(r"\s+", " ", str(title or "").strip())
    if not text:
        return True
    words = [part for part in text.split(" ") if part]
    if len(words) >= 16 or len(text) >= 110:
        return True
    if text.endswith(("?", "!", ";")):
        return True
    if re.search(r"[.!;]\s+[A-Za-zÀ-ÖØ-öø-ÿ]", text):
        return True
    return False


def analyze_export_text(content: str) -> dict[str, Any]:
    text = content or ""
    body_text, _definition_text = _split_body_and_definition_text(text)
    def_matches = list(LOCAL_DEF_RE.finditer(text))
    defs = [str(match.group(1) or "").strip() for match in def_matches]
    refs = [
        str(match.group(1) or "").strip()
        for match in LOCAL_REF_RE.finditer(body_text)
    ]
    forbidden_section_headings: list[str] = []
    for match in SECTION_HEADING_RE.finditer(body_text):
        heading_text = re.sub(r"\s+", " ", str(match.group(1) or "").strip())
        if not heading_text:
            continue
        if heading_text == "*":
            forbidden_section_headings.append(heading_text)
            continue
        if FORBIDDEN_SECTION_HEAD_PREFIX_RE.match(heading_text):
            forbidden_section_headings.append(heading_text)
            continue
        if SECTION_HEAD_INLINE_NOTE_TRACE_RE.search(heading_text):
            forbidden_section_headings.append(heading_text)
            continue
        if _looks_like_sentence_heading(heading_text):
            forbidden_section_headings.append(heading_text)
    all_numbers = {
        int(value) for value in refs + defs if str(value).isdigit()
    }
    starts_at_one = True if not all_numbers else min(all_numbers) == 1
    def_numbers = sorted({int(v) for v in defs if str(v).isdigit()})
    if def_numbers:
        no_gap = def_numbers == list(range(1, def_numbers[-1] + 1))
    else:
        no_gap = True
    return {
        "local_ref_total": len(refs),
        "local_def_total": len(defs),
        "unique_local_refs": sorted(set(refs), key=_numeric_first_sort_key),
        "unique_local_defs": sorted(set(defs), key=_numeric_first_sort_key),
        "local_numbering_starts_at_one": starts_at_one,
        "local_numbering_no_gap": bool(no_gap),
        "legacy_footnote_ref_count": len(LEGACY_FOOTNOTE_RE.findall(text)),
        "legacy_endnote_ref_count": len(LEGACY_ENDNOTE_RE.findall(text)),
        "legacy_en_bracket_ref_count": len(LEGACY_EN_BRACKET_RE.findall(text)),
        "legacy_note_token_count": len(LEGACY_NOTE_TOKEN_RE.findall(text)),
        "pending_placeholder_count": str(content or "").count("[待翻译]"),
        "raw_note_heading_leak_count": len(
            RAW_NOTE_HEADING_RE.findall(content or "")
        ),
        "section_heading_total": len(SECTION_HEADING_RE.findall(body_text)),
        "forbidden_section_heading_count": len(forbidden_section_headings),
        "forbidden_section_heading_preview": forbidden_section_headings[:8],
    }

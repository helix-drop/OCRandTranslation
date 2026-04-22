"""FNM_RE 文本相关工具。"""

from __future__ import annotations

import re
from typing import Any, Mapping

from FNM_RE.shared.title import normalize_title, normalized_title_key

_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")
_NOTES_HEADER_RE = re.compile(r"^\s*(?:#+\s*)?(notes?|endnotes?|notes to pages?.*)\s*$", re.IGNORECASE)


def page_markdown_text(page: Mapping[str, Any] | None) -> str:
    if not isinstance(page, Mapping):
        return ""
    markdown = page.get("markdown")
    if isinstance(markdown, Mapping):
        return str(markdown.get("text") or "").strip()
    if markdown:
        return str(markdown).strip()
    nested_page = page.get("_page")
    if isinstance(nested_page, Mapping) and nested_page is not page:
        return page_markdown_text(nested_page)
    return ""


def page_blocks(page: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    payload = dict(page or {})
    pruned = dict(payload.get("prunedResult") or {})
    blocks = list(pruned.get("parsing_res_list") or [])
    return sorted(
        [dict(block) for block in blocks if isinstance(block, dict)],
        key=lambda block: (
            int(block.get("block_order", 10**9) or 10**9),
            float((block.get("block_bbox") or [0, 0, 0, 0])[1] or 0),
            float((block.get("block_bbox") or [0, 0, 0, 0])[0] or 0),
        ),
    )


def extract_page_headings(page: Mapping[str, Any] | None) -> list[str]:
    headings: list[str] = []
    seen: set[str] = set()
    for block in page_blocks(page):
        label = str(block.get("block_label") or "").strip().lower()
        if label not in {"doc_title", "paragraph_title"}:
            continue
        text = normalize_title(str(block.get("block_content") or ""))
        key = normalized_title_key(text)
        if text and key and key not in seen:
            seen.add(key)
            headings.append(text)
    if headings:
        return headings
    for raw_line in page_markdown_text(page).splitlines()[:8]:
        match = _MARKDOWN_HEADING_RE.match(raw_line)
        if not match:
            continue
        text = normalize_title(match.group(1))
        key = normalized_title_key(text)
        if text and key and key not in seen:
            seen.add(key)
            headings.append(text)
    return headings


def has_note_heading(page: Mapping[str, Any] | None) -> bool:
    return bool(_NOTES_HEADER_RE.search(page_markdown_text(page)))


def first_section_hint(page: Mapping[str, Any] | None, note_scan: Mapping[str, Any] | None) -> str:
    headings = extract_page_headings(page)
    if headings:
        return headings[0]
    hints = list((note_scan or {}).get("section_hints") or [])
    if hints:
        return str(hints[0] or "")
    return ""


def note_scan_summary(note_scan: Mapping[str, Any] | None) -> dict[str, Any]:
    scan = dict(note_scan or {})
    return {
        "page_kind": scan.get("page_kind"),
        "item_count": len(scan.get("items") or []),
        "ambiguity_flags": list(scan.get("ambiguity_flags") or []),
        "note_start_line_index": scan.get("note_start_line_index"),
    }


def plain_text_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if str(line or "").strip()]

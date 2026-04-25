"""页级脚注/尾注检测。"""

from __future__ import annotations

import re


NOTE_SCAN_VERSION = 1

_NOTES_HEADER_RE = re.compile(r"^\s*(?:notes?|endnotes?|注释|脚注|尾注)\s*$", re.IGNORECASE)
_ILLUSTRATION_LIST_RE = re.compile(
    r"^\s*(?:list(?:e)?\s+(?:of\s+)?(?:illustrations?|figures?|plates?)|liste\s+des\s+illustrations?)\b",
    re.IGNORECASE,
)
_ILLUSTRATION_CONTENT_RE = re.compile(
    r"(?:©|cm\b|mus[ée]e|biblioth[eè]que|gravure|huile|lithograph|dessin|eau-forte|collection)",
    re.IGNORECASE,
)
_TITLEISH_RE = re.compile(
    r"^(?:\d+[\.\s]|chapter\b|introduction\b|epilogue\b|afterword\b|appendix\b|preface\b|conclusion\b|le[cç]on\b|lesson\b)",
    re.IGNORECASE,
)
_LATEX_FOOTNOTE_MARK_RE = re.compile(r"\$\s*\^\{(\d+)\}\s*\$")
_PLAIN_FOOTNOTE_MARK_RE = re.compile(r"(?<![\w\[])\^\{(\d+)\}")
_NUMBERED_NOTE_RE = re.compile(
    r"^\s*(?:\[(?P<bracket>\d{1,4})\]|(?P<num>\d{1,4})[\.;:,)、\]]|(?P<loose>\d{1,4})\s{1,3})\s*(?P<rest>\S.+?)\s*$"
)
_MARKER_ONLY_RE = re.compile(
    r"^\s*(?:\[(?P<bracket>\d{1,4})\]|(?P<num>\d{1,4})[\.;:,)、\]])\s*$"
)
_OCR_SPLIT_NUMBERED_NOTE_RE = re.compile(
    r"^\s*(?P<token>(?:\d[\s,.\-]*){2,4})(?:[\.;:,)、\]:-]|\s{1,3})(?P<rest>\S.+?)\s*$"
)
_EMBEDDED_NUMBERED_NOTE_RE = re.compile(
    r"^(?P<prefix>.{20,}?)\s+(?P<token>\d{1,4})(?P<rest>\s+\S.+?)\s*$"
)
_INLINE_NOTE_BREAK_RE = re.compile(
    r"(?P<prefix>[\.\]\)»”])(?P<gap>\s+)(?=(?:\d[\s,.\-]*){1,4}[\.,)、\]])"
)
_PAGE_CITATION_PREFIX_RE = re.compile(r"(?:\bpp?|\bf(?:o|°)?)\.$", re.IGNORECASE)
_INLINE_FOLLOWUP_TOKEN_RE = re.compile(
    r"(?:\s*[,;:·•]+\s*|\s+)"
    r"(?P<token>\d(?:[ ,\.\-]{0,2}\d){0,3})"
    r"(?:[\.,)、\]]|\s{1,3})"
)
_LEADING_NOISE_NUMBERED_NOTE_RE = re.compile(
    r"^\s*(?P<noise>[IiLl\|'\.,‘’“”])\s*(?P<rest>(?:\[(?:\d{1,4})\]|(?:\d{1,4})[\.;:,)、\]])\s*\S.+?)\s*$"
)
_SYMBOL_NOTE_LINE_RE = re.compile(
    r"^\s*(\*{1,4}|†{1,2}|‡{1,2}|§|¶)\s+(.*)\s*$",
)


def _normalize_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    normalized = _LATEX_FOOTNOTE_MARK_RE.sub(r"[\1]", raw)
    normalized = _PLAIN_FOOTNOTE_MARK_RE.sub(r"[\1]", normalized)
    return normalized.strip()


def _expand_inline_marker_breaks(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return ""

    def _replace(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "")
        gap = str(match.group("gap") or "")
        head = raw[max(0, match.start("prefix") - 8):match.start("prefix") + len(prefix)]
        if _PAGE_CITATION_PREFIX_RE.search(head):
            return f"{prefix}{gap}"
        return f"{prefix}\n"

    return _INLINE_NOTE_BREAK_RE.sub(_replace, raw)


def _split_lines(text: str) -> list[str]:
    expanded = _expand_inline_marker_breaks(str(text or ""))
    return [_normalize_text(line) for line in expanded.split("\n") if _normalize_text(line)]


def _strip_markdown_heading_prefix(line: str) -> str:
    text = _normalize_text(line)
    if not text:
        return ""
    return re.sub(r"^\s{0,3}#{1,6}\s*", "", text).strip()


def _is_notes_header_line(line: str, *, allow_markdown_heading: bool) -> bool:
    text = _normalize_text(line)
    if not text:
        return False
    if _NOTES_HEADER_RE.match(text):
        return True
    if not allow_markdown_heading:
        return False
    stripped = _strip_markdown_heading_prefix(text)
    return bool(stripped and stripped != text and _NOTES_HEADER_RE.match(stripped))


def _normalize_number_token(token: str) -> int | None:
    digits = re.sub(r"\D+", "", str(token or ""))
    if not digits or len(digits) > 4:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_numbered_line(line: str) -> dict | None:
    candidate = _normalize_text(line)
    if not candidate:
        return None
    noise_match = _LEADING_NOISE_NUMBERED_NOTE_RE.match(candidate)
    if noise_match:
        candidate = str(noise_match.group("rest") or "").strip()
    split_match = _OCR_SPLIT_NUMBERED_NOTE_RE.match(candidate)
    if split_match:
        number = _normalize_number_token(split_match.group("token") or "")
        rest = str(split_match.group("rest") or "").strip()
        if number is not None and rest:
            return {
                "number": number,
                "marker": f"{number}.",
                "text": f"{number}. {rest}",
                "body": rest,
            }

    match = _NUMBERED_NOTE_RE.match(candidate)
    if not match:
        return None
    token = match.group("bracket") or match.group("num") or match.group("loose") or ""
    if not token:
        return None
    number = int(token)
    if match.group("loose") and 1900 <= number <= 2100:
        return None
    marker = f"[{number}]" if match.group("bracket") else f"{number}."
    return {
        "number": number,
        "marker": marker,
        "text": candidate,
        "body": str(match.group("rest") or "").strip(),
    }


def _parse_embedded_numbered_line(line: str) -> dict | None:
    candidate = _normalize_text(line)
    if not candidate:
        return None
    match = _EMBEDDED_NUMBERED_NOTE_RE.match(candidate)
    if not match:
        return None
    number = _normalize_number_token(match.group("token") or "")
    rest = str(match.group("rest") or "").strip()
    if number is None or number > 20 or not rest:
        return None
    return {
        "number": number,
        "marker": f"{number}.",
        "text": f"{number}. {rest}",
        "body": rest,
    }


def _parse_symbol_note_line(line: str) -> dict | None:
    """解析符号型脚注行，如 * text、** text 等。

    Returns:
        {marker, text, body}，非符号行返回 None
    """
    candidate = _normalize_text(line)
    if not candidate:
        return None
    match = _SYMBOL_NOTE_LINE_RE.match(candidate)
    if not match:
        return None
    marker = match.group(1)
    text = str(match.group(2) or "").strip()
    if not text:
        return None
    return {
        "number": 0,
        "marker": marker,
        "text": f"{marker} {text}",
        "body": text,
    }


def _parse_marker_only_line(line: str) -> int | None:
    candidate = _normalize_text(line)
    if not candidate:
        return None
    match = _MARKER_ONLY_RE.match(candidate)
    if not match:
        return None
    token = match.group("bracket") or match.group("num") or ""
    if not token:
        return None
    return _normalize_number_token(token)


def _split_trailing_marker(text: str, *, current_number: int) -> tuple[str, int | None]:
    candidate = _normalize_text(text)
    if not candidate:
        return "", None
    match = re.match(r"^(?P<body>.+?)\s+(?P<token>(?:\d[\s,.\-]*){1,4})[\.,)、\]]\s*$", candidate)
    if not match:
        return candidate, None
    next_number = _normalize_number_token(match.group("token") or "")
    if next_number is None or next_number <= int(current_number) or next_number > int(current_number) + 2:
        return candidate, None
    body = str(match.group("body") or "").rstrip()
    if len(body) < 8:
        return candidate, None
    return body, next_number


def _split_inline_followup_body(text: str, *, current_number: int) -> tuple[str, int | None, str | None]:
    candidate = _normalize_text(text)
    if not candidate:
        return "", None, None
    for match in _INLINE_FOLLOWUP_TOKEN_RE.finditer(candidate):
        body = candidate[:match.start()].rstrip()
        separator = candidate[match.start():match.start("token")]
        if len(body) < 8:
            continue
        body_tail = body[-1:] if body else ""
        separator_has_punct = any(ch in ",;:·•" for ch in str(separator or ""))
        if not separator_has_punct and body_tail not in ".;,:!?»”":
            if len(body) < 24 or body_tail.isdigit():
                continue
            if not re.search(r"[.!?;:]", body):
                continue
            if _PAGE_CITATION_PREFIX_RE.search(body[max(0, len(body) - 12):]):
                continue
        next_number = _normalize_number_token(match.group("token") or "")
        rest = candidate[match.end():].strip()
        if next_number is None or next_number <= int(current_number) or next_number > int(current_number) + 2:
            continue
        if len(rest) < 8:
            continue
        first_char = rest[:1]
        if first_char and not (first_char.isupper() or first_char in {'"', "'", "«", "(", "["}):
            continue
        return body, next_number, rest
    return candidate, None, None


def _looks_like_complete_note_text(text: str) -> bool:
    candidate = _normalize_text(text)
    if not candidate:
        return False
    return candidate[-1:] in {".", ";", ":", "!", "?", ")", "]", "»", "”", '"', "'"}


def _looks_like_ocr_missing_note_body_line(line: str) -> bool:
    candidate = _normalize_text(line)
    if not candidate:
        return False
    if _parse_numbered_line(candidate) or _parse_marker_only_line(candidate) is not None:
        return False
    compact = re.sub(r"[^a-z0-9]+", "", candidate.lower())
    if len(compact) < 4:
        return False
    noise_count = sum(1 for char in candidate if char in "^[]\\|/_")
    uppercase_runs = len(re.findall(r"[A-Z]{3,}", candidate))
    has_ibid_hint = any(token in compact for token in ("ibid", "ybid", "jbid", "lbid"))
    return bool(has_ibid_hint or noise_count >= 2 or uppercase_runs >= 2)


def _append_current_item(items: list[dict], current: dict | None) -> None:
    if current and _normalize_text(current.get("text", "")):
        items.append(current)


def _split_followup_items(current: dict, *, base_order: int, default_section_title: str) -> tuple[dict, int | None, list[dict]]:
    emitted: list[dict] = []
    last_number: int | None = None
    while True:
        current_body = re.sub(
            rf"^\s*{int(current.get('number') or 0)}[\.,)\]]?\s*",
            "",
            str(current.get("text") or ""),
        ).strip()
        body_text, followup_number, followup_body = _split_inline_followup_body(
            current_body,
            current_number=int(current.get("number") or 0),
        )
        current["text"] = f"{int(current.get('number') or 0)}. {body_text}".strip()
        if followup_number is None or not followup_body:
            break
        if _normalize_text(current.get("text", "")):
            emitted.append(current)
        current = {
            "kind": str(current.get("kind") or ""),
            "marker": f"{followup_number}.",
            "number": followup_number,
            "text": f"{followup_number}. {followup_body}",
            "order": base_order + len(emitted) + 1,
            "source": str(current.get("source") or ""),
            "confidence": float(current.get("confidence", 1.0) or 1.0),
            "section_title": default_section_title,
        }
        last_number = followup_number
    return current, last_number, emitted


def _append_line_to_current_item(
    current: dict,
    line: str,
    *,
    base_order: int,
    default_section_title: str,
) -> tuple[dict, int | None, list[dict]]:
    current["text"] = f"{current['text']}\n{_normalize_text(line)}".strip()
    return _split_followup_items(current, base_order=base_order, default_section_title=default_section_title)


def _synthesize_gap_items(
    *,
    kind: str,
    source: str,
    base_order: int,
    default_section_title: str,
    start_number: int,
    pending_lines: list[str],
) -> tuple[list[dict], int]:
    synthesized: list[dict] = []
    last_number = int(start_number)
    for offset, pending_line in enumerate(pending_lines, start=1):
        marker_number = int(start_number) + offset
        synthesized.append(
            {
                "kind": kind,
                "marker": f"{marker_number}.",
                "number": marker_number,
                "text": f"{marker_number}. {_normalize_text(pending_line)}".strip(),
                "order": base_order + len(synthesized) + 1,
                "source": source,
                "confidence": 1.0,
                "section_title": default_section_title,
            }
        )
        last_number = marker_number
    return synthesized, last_number


def _looks_like_title(line: str) -> bool:
    text = _normalize_text(line)
    if (
        not text
        or _is_notes_header_line(text, allow_markdown_heading=True)
    ):
        return False
    if _parse_numbered_line(text):
        return False
    if _TITLEISH_RE.match(text):
        return True
    if len(text) <= 120 and not re.search(r"[.!?。！？]\s*$", text):
        letters = sum(1 for ch in text if ch.isalpha())
        return letters >= max(4, len(text) // 3)
    return False


def _looks_like_illustration_list_page(page: dict | None, prev_page: dict | None) -> bool:
    if not isinstance(page, dict):
        return False
    lines = _split_lines(page.get("markdown", ""))
    if not lines:
        return False
    first_line = _strip_markdown_heading_prefix(lines[0])
    if _ILLUSTRATION_LIST_RE.match(first_line):
        return True
    if not isinstance(prev_page, dict):
        return False
    prev_lines = _split_lines(prev_page.get("markdown", ""))
    if not prev_lines:
        return False
    prev_first_line = _strip_markdown_heading_prefix(prev_lines[0])
    if not _ILLUSTRATION_LIST_RE.match(prev_first_line):
        return False
    numbered_prefix = 0
    illustration_hint_count = 0
    for line in lines[:8]:
        if _parse_numbered_line(line):
            numbered_prefix += 1
        if _ILLUSTRATION_CONTENT_RE.search(line):
            illustration_hint_count += 1
    return numbered_prefix >= 2 and illustration_hint_count >= 2


def _clone_item(item: dict, *, order: int | None = None, source: str | None = None, confidence: float | None = None) -> dict:
    return {
        "kind": str(item.get("kind") or "").strip(),
        "marker": str(item.get("marker") or "").strip(),
        "number": int(item["number"]) if item.get("number") is not None else None,
        "text": _normalize_text(item.get("text", "")),
        "order": int(order if order is not None else item.get("order", 0) or 0),
        "source": str(source if source is not None else item.get("source", "")).strip(),
        "confidence": float(confidence if confidence is not None else item.get("confidence", 0.0) or 0.0),
        "top": item.get("top"),
        "section_title": str(item.get("section_title", "") or "").strip(),
    }


def _split_items_from_text(
    text: str,
    *,
    kind: str,
    source: str,
    base_order: int = 0,
    default_section_title: str = "",
    last_number: int | None = None,
) -> list[dict]:
    lines = _split_lines(text)
    if not lines:
        return []
    items: list[dict] = []
    current: dict | None = None
    pending_gap_lines: list[str] = []
    last_seen_number = last_number
    for line in lines:
        parsed = _parse_numbered_line(line)
        if parsed is None and current is None:
            parsed = _parse_embedded_numbered_line(line)
        if parsed is None:
            parsed = _parse_symbol_note_line(line)
        if parsed:
            parsed_number = int(parsed["number"])
            if current:
                current_number = int(current.get("number") or 0)
                if (
                    pending_gap_lines
                    and parsed_number > current_number + 1
                    and parsed_number - current_number - 1 == len(pending_gap_lines)
                    and _looks_like_complete_note_text(str(current.get("text") or ""))
                    and all(_looks_like_ocr_missing_note_body_line(candidate) for candidate in pending_gap_lines)
                ):
                    _append_current_item(items, current)
                    synthesized, last_seen_number = _synthesize_gap_items(
                        kind=kind,
                        source=source,
                        base_order=base_order + len(items),
                        default_section_title=default_section_title,
                        start_number=current_number,
                        pending_lines=pending_gap_lines,
                    )
                    items.extend(synthesized)
                else:
                    for pending_line in pending_gap_lines:
                        current, split_number, emitted = _append_line_to_current_item(
                            current,
                            pending_line,
                            base_order=base_order + len(items),
                            default_section_title=default_section_title,
                        )
                        items.extend(emitted)
                        if split_number is not None:
                            last_seen_number = split_number
                    _append_current_item(items, current)
                    if current.get("number") is not None:
                        last_seen_number = int(current.get("number") or 0)
                current = None
                pending_gap_lines = []
            elif (
                pending_gap_lines
                and last_seen_number is not None
                and parsed_number > int(last_seen_number) + 1
                and parsed_number - int(last_seen_number) - 1 == len(pending_gap_lines)
                and all(_looks_like_ocr_missing_note_body_line(candidate) for candidate in pending_gap_lines)
            ):
                synthesized, last_seen_number = _synthesize_gap_items(
                    kind=kind,
                    source=source,
                    base_order=base_order + len(items),
                    default_section_title=default_section_title,
                    start_number=int(last_seen_number),
                    pending_lines=pending_gap_lines,
                )
                items.extend(synthesized)
                pending_gap_lines = []
            else:
                pending_gap_lines = []
            current = {
                "kind": kind,
                "marker": parsed["marker"],
                "number": parsed["number"],
                "text": parsed["text"],
                "order": base_order + len(items) + 1,
                "source": source,
                "confidence": 1.0,
                "section_title": default_section_title,
            }
            trimmed_text, pending_number = _split_trailing_marker(
                current["text"],
                current_number=int(parsed["number"]),
            )
            current["text"] = trimmed_text
            if pending_number is not None:
                _append_current_item(items, current)
                current = {
                    "kind": kind,
                    "marker": f"{pending_number}.",
                    "number": pending_number,
                    "text": "",
                    "order": base_order + len(items) + 1,
                    "source": source,
                    "confidence": 1.0,
                    "section_title": default_section_title,
                }
                last_seen_number = pending_number
            else:
                current["text"] = f"{int(parsed['number'])}. {str(parsed.get('body') or '').strip()}".strip()
                current, split_number, emitted = _split_followup_items(
                    current,
                    base_order=base_order + len(items),
                    default_section_title=default_section_title,
                )
                items.extend(emitted)
                last_seen_number = split_number if split_number is not None else parsed_number
            continue
        marker_only = _parse_marker_only_line(line)
        if current and marker_only is not None and int(current.get("number") or 0) < int(marker_only) <= int(current.get("number") or 0) + 2:
            for pending_line in pending_gap_lines:
                current, split_number, emitted = _append_line_to_current_item(
                    current,
                    pending_line,
                    base_order=base_order + len(items),
                    default_section_title=default_section_title,
                )
                items.extend(emitted)
                if split_number is not None:
                    last_seen_number = split_number
            pending_gap_lines = []
            _append_current_item(items, current)
            current = {
                "kind": kind,
                "marker": f"{marker_only}.",
                "number": marker_only,
                "text": "",
                "order": base_order + len(items) + 1,
                "source": source,
                "confidence": 1.0,
                "section_title": default_section_title,
            }
            last_seen_number = marker_only
            continue
        if current is None:
            if _looks_like_ocr_missing_note_body_line(line):
                pending_gap_lines.append(line)
            continue
        if _looks_like_ocr_missing_note_body_line(line):
            pending_gap_lines.append(line)
            continue
        for pending_line in pending_gap_lines:
            current, split_number, emitted = _append_line_to_current_item(
                current,
                pending_line,
                base_order=base_order + len(items),
                default_section_title=default_section_title,
            )
            items.extend(emitted)
            if split_number is not None:
                last_seen_number = split_number
        pending_gap_lines = []
        current, split_number, emitted = _append_line_to_current_item(
            current,
            line,
            base_order=base_order + len(items),
            default_section_title=default_section_title,
        )
        items.extend(emitted)
        if split_number is not None:
            last_seen_number = split_number
    if current:
        if (
            pending_gap_lines
            and len(pending_gap_lines) <= 2
            and _looks_like_complete_note_text(str(current.get("text") or ""))
            and all(_looks_like_ocr_missing_note_body_line(candidate) for candidate in pending_gap_lines)
        ):
            _append_current_item(items, current)
            synthesized, _last = _synthesize_gap_items(
                kind=kind,
                source=source,
                base_order=base_order + len(items),
                default_section_title=default_section_title,
                start_number=int(current.get("number") or 0),
                pending_lines=pending_gap_lines,
            )
            items.extend(synthesized)
        else:
            for pending_line in pending_gap_lines:
                current, split_number, emitted = _append_line_to_current_item(
                    current,
                    pending_line,
                    base_order=base_order + len(items),
                    default_section_title=default_section_title,
                )
                items.extend(emitted)
                if split_number is not None:
                    last_seen_number = split_number
            _append_current_item(items, current)
    return items


def _extract_page_footnote_items(page: dict, prev_page: dict | None = None) -> list[dict]:
    items: list[dict] = []
    previous_last_number: int | None = None
    previous_scan = dict((prev_page or {}).get("_note_scan") or {})
    previous_footnotes = [
        item
        for item in list(previous_scan.get("items") or [])
        if str(item.get("kind") or "").strip() == "footnote" and item.get("number") is not None
    ]
    if previous_footnotes:
        previous_last_number = max(int(item.get("number") or 0) for item in previous_footnotes)
    fn_blocks = page.get("fnBlocks") or []
    if fn_blocks:
        for block in fn_blocks:
            top = None
            bbox = block.get("bbox")
            if bbox and len(bbox) >= 4:
                top = float(bbox[1])
            for item in _split_items_from_text(
                block.get("text", ""),
                kind="footnote",
                source="fnBlocks",
                base_order=len(items),
                last_number=previous_last_number,
            ):
                item["top"] = top
                items.append(item)
                if item.get("number") is not None:
                    previous_last_number = int(item.get("number") or 0)
        if items:
            return items
    return _split_items_from_text(
        page.get("footnotes", ""),
        kind="footnote",
        source="footnotes",
        last_number=previous_last_number,
    )


def _looks_like_note_continuation(page: dict | None) -> bool:
    if not isinstance(page, dict):
        return False
    if _looks_like_illustration_list_page(page, None):
        return False
    lines = _split_lines(page.get("markdown", ""))
    if any(_is_notes_header_line(line, allow_markdown_heading=True) for line in lines[:3]):
        return True
    numbered_prefix = 0
    for line in lines[:8]:
        if _parse_numbered_line(line):
            numbered_prefix += 1
        else:
            break
    return numbered_prefix >= 2


def _collect_markdown_endnotes(page: dict, prev_page: dict | None, next_page: dict | None) -> dict:
    if _looks_like_illustration_list_page(page, prev_page):
        return {
            "page_kind": "body",
            "items": [],
            "section_hints": [],
            "ambiguity_flags": [],
            "note_start_line_index": None,
        }
    lines = _split_lines(page.get("markdown", ""))
    if not lines:
        return {
            "page_kind": "body",
            "items": [],
            "section_hints": [],
            "ambiguity_flags": [],
            "note_start_line_index": None,
        }

    notes_header_idx = None
    for idx, line in enumerate(lines):
        if _is_notes_header_line(line, allow_markdown_heading=False):
            notes_header_idx = idx
            break
        if idx > 0 and _is_notes_header_line(line, allow_markdown_heading=True):
            notes_header_idx = idx
            break
    numbered_positions = [(idx, _parse_numbered_line(line)) for idx, line in enumerate(lines)]
    numbered_positions = [(idx, parsed) for idx, parsed in numbered_positions if parsed]
    ambiguity_flags: list[str] = []
    section_hints: list[str] = []
    current_section_title = ""
    items: list[dict] = []
    note_start_line_index: int | None = None

    if notes_header_idx is not None:
        section_hints.append(lines[notes_header_idx])
        note_start_line_index = notes_header_idx
        after_header_positions = [(idx, parsed) for idx, parsed in numbered_positions if idx > notes_header_idx]
        if not after_header_positions:
            ambiguity_flags.append("notes_header_without_items")
            return {
                "page_kind": "body",
                "items": [],
                "section_hints": section_hints,
                "ambiguity_flags": ambiguity_flags,
                "note_start_line_index": note_start_line_index,
            }
        cursor = notes_header_idx + 1
    else:
        if not numbered_positions:
            return {
                "page_kind": "body",
                "items": [],
                "section_hints": [],
                "ambiguity_flags": [],
                "note_start_line_index": None,
            }
        first_number_idx = numbered_positions[0][0]
        number_count = len(numbered_positions)
        first_number = numbered_positions[0][1]["number"]
        neighbor_note_like = _looks_like_note_continuation(prev_page) or _looks_like_note_continuation(next_page)
        if number_count >= 2 and first_number_idx <= 1 and (neighbor_note_like or first_number <= 2):
            note_start_line_index = first_number_idx
        else:
            ambiguity_flags.append("isolated_numbered_page")
            return {
                "page_kind": "body",
                "items": [],
                "section_hints": [],
                "ambiguity_flags": ambiguity_flags,
                "note_start_line_index": None,
            }
        cursor = note_start_line_index

    pending_section_title = ""
    current_item: dict | None = None
    for idx in range(cursor, len(lines)):
        line = lines[idx]
        if _NOTES_HEADER_RE.match(line):
            continue
        parsed = _parse_numbered_line(line)
        if parsed:
            if current_item:
                items.append(current_item)
            if pending_section_title:
                current_section_title = pending_section_title
                pending_section_title = ""
            current_item = {
                "kind": "endnote",
                "marker": parsed["marker"],
                "number": parsed["number"],
                "text": parsed["text"],
                "order": len(items) + 1,
                "source": "markdown",
                "confidence": 0.88,
                "section_title": current_section_title,
            }
            continue
        next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
        if _looks_like_title(line) and _parse_numbered_line(next_line):
            pending_section_title = line
            if line not in section_hints:
                section_hints.append(line)
            if current_item:
                items.append(current_item)
                current_item = None
            continue
        if current_item:
            current_item["text"] = f"{current_item['text']}\n{line}".strip()
    if current_item:
        items.append(current_item)

    if not items:
        ambiguity_flags.append("notes_header_without_items")
        return {
            "page_kind": "body",
            "items": [],
            "section_hints": section_hints,
            "ambiguity_flags": ambiguity_flags,
            "note_start_line_index": note_start_line_index,
        }

    body_line_count = note_start_line_index if note_start_line_index is not None else 0
    page_kind = "mixed_body_endnotes" if body_line_count > 0 else "endnote_collection"
    numbers = [item["number"] for item in items if item.get("number") is not None]
    if len(numbers) >= 2 and len(set(numbers)) != len(numbers):
        ambiguity_flags.append("duplicate_numbers")
    if len(numbers) >= 2 and numbers != sorted(numbers):
        ambiguity_flags.append("non_monotonic_numbers")
    return {
        "page_kind": page_kind,
        "items": items,
        "section_hints": section_hints,
        "ambiguity_flags": ambiguity_flags,
        "note_start_line_index": note_start_line_index,
    }


def _build_rule_scan(page: dict, prev_page: dict | None, next_page: dict | None) -> dict:
    footnote_items = _extract_page_footnote_items(page, prev_page)
    endnote_scan = _collect_markdown_endnotes(page, prev_page, next_page)
    if endnote_scan["items"]:
        scan = dict(endnote_scan)
    elif footnote_items:
        scan = {
            "page_kind": "body_with_page_footnotes",
            "items": footnote_items,
            "section_hints": [],
            "ambiguity_flags": [],
            "note_start_line_index": None,
        }
    else:
        scan = {
            "page_kind": "body",
            "items": [],
            "section_hints": [],
            "ambiguity_flags": list(endnote_scan.get("ambiguity_flags") or []),
            "note_start_line_index": None,
        }
    scan["reviewed_by_model"] = False
    return scan


def _scan_score(scan: dict) -> float:
    items = list(scan.get("items") or [])
    score = len(items) * 10.0
    score += sum(float(item.get("confidence", 0.0) or 0.0) for item in items)
    if scan.get("page_kind") != "body":
        score += 3.0
    score -= len(scan.get("ambiguity_flags") or []) * 2.0
    return score


def _normalize_review_scan(review_scan: dict, rule_scan: dict) -> dict | None:
    if not isinstance(review_scan, dict):
        return None
    items = []
    for idx, item in enumerate(review_scan.get("items") or [], 1):
        cloned = _clone_item(
            item,
            order=idx,
            source=item.get("source") or "model_review",
            confidence=float(item.get("confidence", 0.75) or 0.75),
        )
        if not cloned["kind"] or not cloned["text"]:
            continue
        items.append(cloned)
    return {
        "page_kind": str(review_scan.get("page_kind") or rule_scan.get("page_kind") or "body").strip() or "body",
        "items": items,
        "section_hints": [str(v).strip() for v in (review_scan.get("section_hints") or []) if str(v).strip()],
        "ambiguity_flags": [str(v).strip() for v in (review_scan.get("ambiguity_flags") or []) if str(v).strip()],
        "note_start_line_index": rule_scan.get("note_start_line_index"),
        "reviewed_by_model": True,
    }


def annotate_pages_with_note_scans(
    pages: list[dict],
    reviewer=None,
    target_bps: set[int] | None = None,
) -> list[dict]:
    normalized_pages = [dict(page or {}) for page in (pages or [])]
    page_by_bp = {
        int(page.get("bookPage") or 0): page
        for page in normalized_pages
        if int(page.get("bookPage") or 0) > 0
    }

    for idx, page in enumerate(normalized_pages):
        bp = int(page.get("bookPage") or 0)
        if bp <= 0:
            continue
        if target_bps is not None and bp not in target_bps and page.get("_note_scan"):
            page["_note_scan_version"] = NOTE_SCAN_VERSION
            continue
        prev_page = page_by_bp.get(bp - 1)
        next_page = page_by_bp.get(bp + 1)
        rule_scan = _build_rule_scan(page, prev_page, next_page)
        selected_scan = rule_scan
        if reviewer and (rule_scan.get("ambiguity_flags") or []):
            try:
                reviewed = reviewer(page=page, prev_page=prev_page, next_page=next_page, rule_scan=rule_scan)
            except Exception:
                reviewed = None
            normalized_review = _normalize_review_scan(reviewed, rule_scan) if reviewed else None
            if normalized_review and _scan_score(normalized_review) >= _scan_score(rule_scan):
                selected_scan = normalized_review
        page["_note_scan_version"] = NOTE_SCAN_VERSION
        page["_note_scan"] = selected_scan
    return normalized_pages

"""页级脚注/尾注检测。"""

from __future__ import annotations

import re


NOTE_SCAN_VERSION = 1

_NOTES_HEADER_RE = re.compile(r"^\s*(?:notes?|注释|脚注|尾注)\s*$", re.IGNORECASE)
_TITLEISH_RE = re.compile(
    r"^(?:\d+[\.\s]|chapter\b|introduction\b|epilogue\b|afterword\b|appendix\b|preface\b|conclusion\b|le[cç]on\b|lesson\b)",
    re.IGNORECASE,
)
_LATEX_FOOTNOTE_MARK_RE = re.compile(r"\$\s*\^\{(\d+)\}\s*\$")
_PLAIN_FOOTNOTE_MARK_RE = re.compile(r"(?<![\w\[])\^\{(\d+)\}")
_NUMBERED_NOTE_RE = re.compile(
    r"^\s*(?:\[(?P<bracket>\d{1,4})\]|(?P<num>\d{1,4})[\.\)、\]]|(?P<loose>\d{1,4})\s{1,3})\s*(?P<rest>\S.+?)\s*$"
)


def _normalize_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    normalized = _LATEX_FOOTNOTE_MARK_RE.sub(r"[\1]", raw)
    normalized = _PLAIN_FOOTNOTE_MARK_RE.sub(r"[\1]", normalized)
    return normalized.strip()


def _split_lines(text: str) -> list[str]:
    return [_normalize_text(line) for line in str(text or "").split("\n") if _normalize_text(line)]


def _parse_numbered_line(line: str) -> dict | None:
    match = _NUMBERED_NOTE_RE.match(_normalize_text(line))
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
        "text": _normalize_text(line),
    }


def _looks_like_title(line: str) -> bool:
    text = _normalize_text(line)
    if not text or _NOTES_HEADER_RE.match(text):
        return False
    if _parse_numbered_line(text):
        return False
    if _TITLEISH_RE.match(text):
        return True
    if len(text) <= 120 and not re.search(r"[.!?。！？]\s*$", text):
        letters = sum(1 for ch in text if ch.isalpha())
        return letters >= max(4, len(text) // 3)
    return False


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


def _split_items_from_text(text: str, *, kind: str, source: str, base_order: int = 0, default_section_title: str = "") -> list[dict]:
    lines = _split_lines(text)
    if not lines:
        return []
    items: list[dict] = []
    current: dict | None = None
    for line in lines:
        parsed = _parse_numbered_line(line)
        if parsed:
            if current:
                items.append(current)
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
            continue
        if current:
            current["text"] = f"{current['text']}\n{_normalize_text(line)}".strip()
    if current:
        items.append(current)
    return items


def _extract_page_footnote_items(page: dict) -> list[dict]:
    items: list[dict] = []
    fn_blocks = page.get("fnBlocks") or []
    if fn_blocks:
        for block in fn_blocks:
            top = None
            bbox = block.get("bbox")
            if bbox and len(bbox) >= 4:
                top = float(bbox[1])
            for item in _split_items_from_text(block.get("text", ""), kind="footnote", source="fnBlocks", base_order=len(items)):
                item["top"] = top
                items.append(item)
        if items:
            return items
    return _split_items_from_text(page.get("footnotes", ""), kind="footnote", source="footnotes")


def _looks_like_note_continuation(page: dict | None) -> bool:
    if not isinstance(page, dict):
        return False
    lines = _split_lines(page.get("markdown", ""))
    if any(_NOTES_HEADER_RE.match(line) for line in lines[:3]):
        return True
    numbered_prefix = 0
    for line in lines[:8]:
        if _parse_numbered_line(line):
            numbered_prefix += 1
        else:
            break
    return numbered_prefix >= 2


def _collect_markdown_endnotes(page: dict, prev_page: dict | None, next_page: dict | None) -> dict:
    lines = _split_lines(page.get("markdown", ""))
    if not lines:
        return {
            "page_kind": "body",
            "items": [],
            "section_hints": [],
            "ambiguity_flags": [],
            "note_start_line_index": None,
        }

    notes_header_idx = next((idx for idx, line in enumerate(lines) if _NOTES_HEADER_RE.match(line)), None)
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
    footnote_items = _extract_page_footnote_items(page)
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

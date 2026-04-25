"""FNM_RE 注释解析共享工具。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from document.pdf_extract import extract_pdf_text

from FNM_RE.shared.text import page_markdown_text

_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")
_NOTES_HEADING_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*|注释|脚注|尾注)\s*$",
    re.IGNORECASE,
)
_NOTE_DEF_RE = re.compile(
    r"^\s*(?:\[(?P<bracket>\d{1,4})\]|(?P<num>\d{1,4})[\.;:,\)\]]|(?P<loose>\d{1,4})\s{1,3})\s*(?P<body>\S.*)$"
)
_MARKER_ONLY_RE = re.compile(
    r"^\s*(?:\[(?P<bracket>\d{1,4})\]|(?P<num>\d{1,4})[\.;:,\)\]])\s*$"
)
_OCR_SPLIT_NOTE_DEF_RE = re.compile(
    r"^\s*(?P<token>(?:\d[\s,\.\-]*){2,4})(?:[\.;:,\)\]:-]|\s{1,3})(?P<body>\S.*)$"
)
_EMBEDDED_NOTE_DEF_RE = re.compile(
    r"^(?P<prefix>.{20,}?)\s+(?P<token>\d{1,4})(?P<body>\s+\S.*)$"
)
_INLINE_NOTE_BREAK_RE = re.compile(
    r"(?P<prefix>[\.\]\)»”])(?P<gap>\s+)(?=(?:\d[\s,\.\-]*){1,4}[\.,\)\]])"
)
_PAGE_CITATION_PREFIX_RE = re.compile(r"(?:\bpp?|\bf(?:o|°)?)\.$", re.IGNORECASE)
_INLINE_FOLLOWUP_TOKEN_RE = re.compile(
    r"(?:\s*[,;:·•]+\s*|\s+)"
    r"(?P<token>\d(?:[ ,\.\-]{0,2}\d){0,3})"
    r"(?:[\.,\)\]]|\s{1,3})"
)
_LEADING_NOISE_NOTE_DEF_RE = re.compile(
    r"^\s*(?P<noise>[IiLl\|'\.,‘’“”])\s*(?P<rest>(?:\[(?:\d{1,4})\]|(?:\d{1,4})[\.;:,\)\]])\s*\S.*)$"
)
# 符号型脚注标记：*, **, ***, ****, †, ‡, §, ¶
_SYMBOL_NOTE_DEF_RE = re.compile(
    r"^\s*(\*{1,4}|†{1,2}|‡{1,2}|§|¶)\s+(?P<body>\S.*)$"
)
_SYMBOL_MARKER_ONLY_RE = re.compile(
    r"^\s*(\*{1,4}|†{1,2}|‡{1,2}|§|¶)\s*$"
)
# 符号型标记特征匹配（用于 normalize_note_marker 保留符号标记）
_SYMBOLIC_MARKER_RE = re.compile(r"^[\*†‡§¶]{1,4}$")


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _expand_inline_note_breaks(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return ""

    def _replace(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "")
        gap = str(match.group("gap") or "")
        head = raw[
            max(0, match.start("prefix") - 8) : match.start("prefix") + len(prefix)
        ]
        if _PAGE_CITATION_PREFIX_RE.search(head):
            return f"{prefix}{gap}"
        return f"{prefix}\n"

    return _INLINE_NOTE_BREAK_RE.sub(_replace, raw)


_UNICODE_SUPERSCRIPT_TO_DIGITS = str.maketrans(
    {
        "⁰": "0",
        "¹": "1",
        "²": "2",
        "³": "3",
        "⁴": "4",
        "⁵": "5",
        "⁶": "6",
        "⁷": "7",
        "⁸": "8",
        "⁹": "9",
    }
)


def normalize_note_marker(marker: Any) -> str:
    raw = str(marker or "").strip()
    if not raw:
        return ""
    # 符号型标记（*, ** 等）原样保留
    if _SYMBOLIC_MARKER_RE.match(raw):
        return raw
    translated = raw.translate(_UNICODE_SUPERSCRIPT_TO_DIGITS)
    digits = re.sub(r"\D+", "", translated)
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def strip_markdown_heading(line: str) -> str:
    text = str(line or "").strip()
    match = _MARKDOWN_HEADING_RE.match(text)
    if not match:
        return text
    return str(match.group(1) or "").strip()


def is_notes_heading_line(line: str) -> bool:
    text = strip_markdown_heading(line)
    return bool(text and _NOTES_HEADING_RE.match(text))


def first_notes_heading(page: Mapping[str, Any] | None) -> str:
    for raw_line in page_markdown_text(page).splitlines()[:12]:
        if is_notes_heading_line(raw_line):
            return strip_markdown_heading(raw_line)
    return ""


def scan_items_by_kind(page: Mapping[str, Any] | None, *, kind: str) -> list[dict]:
    scan = dict((dict(page or {})).get("_note_scan") or {})
    target_kind = str(kind or "").strip().lower()
    items: list[dict] = []
    for item in scan.get("items") or []:
        if str(item.get("kind") or "").strip().lower() != target_kind:
            continue
        marker = normalize_note_marker(item.get("marker") or item.get("number") or "")
        text = str(item.get("text") or "").strip()
        if not marker and not text:
            continue
        items.append(
            {
                "marker": marker,
                "text": re.sub(r"\s+", " ", text).strip(),
                "is_reconstructed": False,
                "source": "note_scan",
            }
        )
    return items


def first_source_marker(page: Mapping[str, Any] | None, *, kind: str) -> str:
    for item in scan_items_by_kind(page, kind=kind):
        marker = normalize_note_marker(item.get("marker") or "")
        if marker:
            return marker
    return ""


def _parse_note_definition_line(line: str) -> tuple[str, str, bool] | None:
    candidate = strip_markdown_heading(str(line or "").strip())
    if not candidate or is_notes_heading_line(candidate):
        return None
    noise_match = _LEADING_NOISE_NOTE_DEF_RE.match(candidate)
    if noise_match:
        candidate = str(noise_match.group("rest") or "").strip()
    split_match = _OCR_SPLIT_NOTE_DEF_RE.match(candidate)
    if split_match:
        token = str(split_match.group("token") or "").strip()
        body = str(split_match.group("body") or "").strip()
        collapsed = normalize_note_marker(token)
        if not collapsed or not body:
            return None
        reconstructed = bool(re.search(r"[\s\.\-]", token))
        return collapsed, body, reconstructed
    match = _NOTE_DEF_RE.match(candidate)
    if match:
        raw_marker = (
            match.group("bracket") or match.group("num") or match.group("loose") or ""
        )
        marker = normalize_note_marker(raw_marker)
        body = str(match.group("body") or "").strip()
        if not marker or not body:
            return None
        return marker, body, False
    # 尝试符号型标记：*， ** 等
    sym_match = _SYMBOL_NOTE_DEF_RE.match(candidate)
    if sym_match:
        marker = sym_match.group(1)
        body = str(sym_match.group("body") or "").strip()
        if not body:
            return None
        return marker, body, False
    return None


def _parse_embedded_note_definition_line(
    line: str,
    *,
    last_marker_value: int | None,
) -> tuple[str, str, bool] | None:
    candidate = strip_markdown_heading(str(line or "").strip())
    if not candidate or is_notes_heading_line(candidate):
        return None
    match = _EMBEDDED_NOTE_DEF_RE.match(candidate)
    if not match:
        return None
    raw_marker = str(match.group("token") or "").strip()
    marker = normalize_note_marker(raw_marker)
    body = str(match.group("body") or "").strip()
    if not marker or not body:
        return None
    try:
        marker_value = int(marker)
    except ValueError:
        return None
    if last_marker_value is None:
        if marker_value > 20:
            return None
    elif (
        marker_value < int(last_marker_value)
        or marker_value > int(last_marker_value) + 2
    ):
        return None
    return marker, body, True


def _parse_marker_only_line(line: str) -> str | None:
    candidate = strip_markdown_heading(str(line or "").strip())
    if not candidate or is_notes_heading_line(candidate):
        return None
    match = _MARKER_ONLY_RE.match(candidate)
    if match:
        raw_marker = match.group("bracket") or match.group("num") or ""
        marker = normalize_note_marker(raw_marker)
        return marker or None
    sym_match = _SYMBOL_MARKER_ONLY_RE.match(candidate)
    if sym_match:
        return sym_match.group(1)
    return None


def _split_trailing_marker(
    text: str,
    *,
    current_marker: str,
) -> tuple[str, str | None]:
    candidate = str(text or "").strip()
    if not candidate:
        return "", None
    try:
        current_value = int(normalize_note_marker(current_marker))
    except ValueError:
        return candidate, None
    match = re.match(
        r"^(?P<body>.+?)\s+(?P<token>(?:\d[\s,\.\-]*){1,4})[\.,\)\]]\s*$", candidate
    )
    if not match:
        return candidate, None
    next_marker = normalize_note_marker(match.group("token") or "")
    if not next_marker:
        return candidate, None
    try:
        next_value = int(next_marker)
    except ValueError:
        return candidate, None
    if next_value <= current_value or next_value > current_value + 2:
        return candidate, None
    body = str(match.group("body") or "").strip()
    if len(body) < 8:
        return candidate, None
    return body, next_marker


def _split_inline_followup_marker(
    text: str,
    *,
    current_marker: str,
) -> tuple[str, str | None, str | None]:
    candidate = str(text or "").strip()
    if not candidate:
        return "", None, None
    try:
        current_value = int(normalize_note_marker(current_marker))
    except ValueError:
        return candidate, None, None
    for match in _INLINE_FOLLOWUP_TOKEN_RE.finditer(candidate):
        body = candidate[: match.start()].rstrip()
        separator = candidate[match.start() : match.start("token")]
        if len(body) < 8:
            continue
        body_tail = body[-1:] if body else ""
        separator_has_punct = any(ch in ",;:·•" for ch in str(separator or ""))
        if not separator_has_punct and body_tail not in ".;,:!?»”":
            if len(body) < 24 or body_tail.isdigit():
                continue
            if not re.search(r"[.!?;:]", body):
                continue
            if _PAGE_CITATION_PREFIX_RE.search(body[max(0, len(body) - 12) :]):
                continue
        next_marker = normalize_note_marker(match.group("token") or "")
        if not next_marker:
            continue
        try:
            next_value = int(next_marker)
        except ValueError:
            continue
        if next_value <= current_value or next_value > current_value + 2:
            continue
        rest = candidate[match.end() :].strip()
        if len(rest) < 8:
            continue
        first_char = rest[:1]
        if first_char and not (
            first_char.isupper() or first_char in {'"', "'", "«", "(", "["}
        ):
            continue
        return body, next_marker, rest
    return candidate, None, None


def _looks_like_complete_note_text(text: str) -> bool:
    candidate = re.sub(r"\s+", " ", str(text or "")).strip()
    if not candidate:
        return False
    return candidate[-1:] in {".", ";", ":", "!", "?", ")", "]", "»", "”", '"', "'"}


def _looks_like_ocr_missing_note_body_line(line: str) -> bool:
    candidate = strip_markdown_heading(str(line or "").strip())
    if not candidate or is_notes_heading_line(candidate):
        return False
    if _parse_note_definition_line(candidate) or _parse_marker_only_line(candidate):
        return False
    compact = re.sub(r"[^a-z0-9]+", "", candidate.lower())
    if len(compact) < 4:
        return False
    noise_count = sum(1 for char in candidate if char in "^[]\\|/_")
    uppercase_runs = len(re.findall(r"[A-Z]{3,}", candidate))
    has_ibid_hint = any(token in compact for token in ("ibid", "ybid", "jbid", "lbid"))
    return bool(has_ibid_hint or noise_count >= 2 or uppercase_runs >= 2)


def _finalize_current_note(items: list[dict], current: dict | None) -> None:
    if not current:
        return
    merged_text = re.sub(r"\s+", " ", str(current.get("text") or "")).strip()
    if merged_text:
        items.append({**current, "text": merged_text})


def _split_followup_notes(items: list[dict], current: dict) -> tuple[dict, int | None]:
    marker_state: int | None = None
    while True:
        body, followup_marker, followup_body = _split_inline_followup_marker(
            str(current.get("text") or ""),
            current_marker=str(current.get("marker") or ""),
        )
        current["text"] = body
        if not (followup_marker and followup_body):
            break
        _finalize_current_note(items, current)
        current = {
            "marker": followup_marker,
            "text": followup_body,
            "is_reconstructed": True,
        }
        marker_state = int(followup_marker)
    return current, marker_state


def _append_line_to_current(
    items: list[dict], current: dict, line: str
) -> tuple[dict, int | None]:
    current["text"] = (
        f"{str(current.get('text') or '').strip()} {str(line or '').strip()}".strip()
    )
    return _split_followup_notes(items, current)


def _synthesize_pending_gap_notes(
    items: list[dict],
    *,
    start_marker_value: int,
    pending_lines: list[str],
) -> int:
    last_marker_value = int(start_marker_value)
    for offset, pending_line in enumerate(pending_lines, start=1):
        marker_value = int(start_marker_value) + offset
        _finalize_current_note(
            items,
            {
                "marker": str(marker_value),
                "text": str(pending_line or "").strip(),
                "is_reconstructed": True,
            },
        )
        last_marker_value = marker_value
    return last_marker_value


def parse_note_items_from_text(
    text: str,
    *,
    last_marker_value: int | None = None,
) -> tuple[list[dict], int | None]:
    items: list[dict] = []
    current: dict | None = None
    marker_state = last_marker_value
    pending_gap_lines: list[str] = []
    expanded_text = _expand_inline_note_breaks(str(text or ""))
    for raw_line in expanded_text.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        parsed = _parse_note_definition_line(line)
        if parsed is None and current is None:
            parsed = _parse_embedded_note_definition_line(
                line,
                last_marker_value=marker_state,
            )
        if parsed:
            marker, body, reconstructed = parsed
            parsed_value = int(marker) if marker.isdigit() else None
            if current:
                current_raw = normalize_note_marker(current.get("marker") or "") or ""
                current_value = int(current_raw) if current_raw.isdigit() else 0
                if (
                    pending_gap_lines
                    and parsed_value is not None
                    and parsed_value > current_value + 1
                    and parsed_value - current_value - 1 == len(pending_gap_lines)
                    and _looks_like_complete_note_text(str(current.get("text") or ""))
                    and all(
                        _looks_like_ocr_missing_note_body_line(candidate)
                        for candidate in pending_gap_lines
                    )
                ):
                    _finalize_current_note(items, current)
                    marker_state = _synthesize_pending_gap_notes(
                        items,
                        start_marker_value=current_value,
                        pending_lines=pending_gap_lines,
                    )
                else:
                    for pending_line in pending_gap_lines:
                        current, split_marker_state = _append_line_to_current(
                            items, current, pending_line
                        )
                        if split_marker_state is not None:
                            marker_state = split_marker_state
                    _finalize_current_note(items, current)
                current = None
                pending_gap_lines = []
            elif (
                pending_gap_lines
                and parsed_value is not None
                and marker_state is not None
                and parsed_value > int(marker_state) + 1
                and parsed_value - int(marker_state) - 1 == len(pending_gap_lines)
                and all(
                    _looks_like_ocr_missing_note_body_line(candidate)
                    for candidate in pending_gap_lines
                )
            ):
                marker_state = _synthesize_pending_gap_notes(
                    items,
                    start_marker_value=int(marker_state),
                    pending_lines=pending_gap_lines,
                )
                pending_gap_lines = []
            else:
                pending_gap_lines = []
            current = {
                "marker": marker,
                "text": body,
                "is_reconstructed": bool(reconstructed),
            }
            body, pending_marker = _split_trailing_marker(body, current_marker=marker)
            current["text"] = body
            if marker.isdigit():
                marker_state = int(marker)
            if pending_marker:
                merged_text = re.sub(
                    r"\s+", " ", str(current.get("text") or "")
                ).strip()
                if merged_text:
                    items.append({**current, "text": merged_text})
                current = {
                    "marker": pending_marker,
                    "text": "",
                    "is_reconstructed": True,
                }
                marker_state = int(pending_marker)
            else:
                current, split_marker_state = _split_followup_notes(items, current)
                if split_marker_state is not None:
                    marker_state = split_marker_state
            continue
        marker_only = _parse_marker_only_line(line)
        if current is not None and marker_only:
            current_marker = normalize_note_marker(current.get("marker") or "") or ""
            if current_marker.isdigit() and marker_only.isdigit():
                current_value = int(current_marker)
                marker_value = int(marker_only)
                if current_value < marker_value <= current_value + 2:
                    for pending_line in pending_gap_lines:
                        current, split_marker_state = _append_line_to_current(
                            items, current, pending_line
                        )
                        if split_marker_state is not None:
                            marker_state = split_marker_state
                    pending_gap_lines = []
                    _finalize_current_note(items, current)
                    current = {
                        "marker": marker_only,
                        "text": "",
                        "is_reconstructed": True,
                    }
                    marker_state = marker_value
                    continue
        if current is None:
            if _looks_like_ocr_missing_note_body_line(line):
                pending_gap_lines.append(line)
            continue
        if _looks_like_ocr_missing_note_body_line(line):
            pending_gap_lines.append(line)
            continue
        for pending_line in pending_gap_lines:
            current, split_marker_state = _append_line_to_current(
                items, current, pending_line
            )
            if split_marker_state is not None:
                marker_state = split_marker_state
        pending_gap_lines = []
        current, split_marker_state = _append_line_to_current(items, current, line)
        if split_marker_state is not None:
            marker_state = split_marker_state
    if current:
        current_raw = normalize_note_marker(current.get("marker") or "") or ""
        current_value = int(current_raw) if current_raw.isdigit() else 0
        if (
            pending_gap_lines
            and len(pending_gap_lines) <= 2
            and _looks_like_complete_note_text(str(current.get("text") or ""))
            and all(
                _looks_like_ocr_missing_note_body_line(candidate)
                for candidate in pending_gap_lines
            )
        ):
            _finalize_current_note(items, current)
            marker_state = _synthesize_pending_gap_notes(
                items,
                start_marker_value=current_value,
                pending_lines=pending_gap_lines,
            )
        else:
            for pending_line in pending_gap_lines:
                current, split_marker_state = _append_line_to_current(
                    items, current, pending_line
                )
                if split_marker_state is not None:
                    marker_state = split_marker_state
            _finalize_current_note(items, current)
    return items, marker_state


def _pdf_page_text(page: Mapping[str, Any]) -> str:
    items = sorted(
        list(page.get("items") or []),
        key=lambda item: (
            _safe_float(item.get("y")) or 10**9,
            _safe_float(item.get("x")) or 10**9,
        ),
    )
    lines: list[str] = []
    for item in items:
        token = str(item.get("str") or "").strip()
        if token:
            lines.append(token)
    return "\n".join(lines).strip()


def extract_pdf_text_by_page(
    pdf_path: str,
    *,
    pages: list[dict],
    target_pages: set[int],
) -> dict[int, str]:
    path = Path(str(pdf_path or "").strip())
    if not target_pages or not path.exists() or not path.is_file():
        return {}
    try:
        file_bytes = path.read_bytes()
    except OSError:
        return {}
    payloads = extract_pdf_text(file_bytes)
    if not payloads:
        return {}
    file_idx_to_page: dict[int, int] = {}
    for page in pages or []:
        try:
            file_idx = int(page.get("fileIdx"))
            page_no = int(page.get("bookPage"))
        except (TypeError, ValueError):
            continue
        if file_idx >= 0 and page_no > 0:
            file_idx_to_page[file_idx] = page_no
    resolved: dict[int, str] = {}
    for payload in payloads:
        file_idx = int(payload.get("pageIdx") or -1)
        page_no = int(file_idx_to_page.get(file_idx) or 0)
        if page_no <= 0 or page_no not in target_pages:
            continue
        text = _pdf_page_text(payload)
        if text:
            resolved[page_no] = text
    return resolved

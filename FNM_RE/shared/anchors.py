"""FNM_RE anchor 提取共享工具。"""

from __future__ import annotations

import re
from typing import Any, Mapping

from FNM_RE.shared.notes import is_notes_heading_line, normalize_note_marker
from FNM_RE.shared.text import page_blocks, page_markdown_text

_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")
_NOTE_DEFINITION_LINE_RE = re.compile(
    r"^\s*(?:"
    r"\[(?:\d{1,4})\]"
    r"|(?:\d{1,4})[\.\)\]]"
    r"|(?:\d{1,4})\s{1,3}"
    r"|<sup>\s*\d{1,4}\s*</sup>"
    r"|\$\s*\^\{\d{1,4}\}\s*\$"
    r"|\^\{\d{1,4}\}"
    r"|[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,4}"
    r")\s*\S+",
    re.IGNORECASE,
)
_HTML_SUP_RE = re.compile(r"<sup>\s*(\d{1,4})\s*</sup>", re.IGNORECASE)
_LATEX_SUP_RE = re.compile(r"\$\s*\^\{(\d{1,4})\}\s*\$")
_PLAIN_SUP_RE = re.compile(r"\^\{(\d{1,4})\}")
_FOOTNOTE_REF_RE = re.compile(r"\[\^(\d{1,4})\]")
_BRACKET_REF_RE = re.compile(r"(?<!\d)\[(\d{1,4})\](?!\d)")
_BROKEN_LEFT_BRACKET_REF_RE = re.compile(
    r"(?<=[A-Za-zàâäéèêëïîôöùûüÿçœÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇŒ»”’\)])"
    r"\[(\d{1,4})(?=[\.,;:!\?…»”’\)])"
)
_UNICODE_SUP_RE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
_BARE_DIGIT_RE = re.compile(r"\s(\d{1,3})(?=[\.\,\;\:\)\]\}»]|\s+[\-–—])")
_BARE_DIGIT_LEFT_WORD_RE = re.compile(
    r"([A-Za-zàâäéèêëïîôöùûüÿçœÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇŒ]+)\s*$"
)
# 段落级最小化预过滤：只排除必定不是 marker 的结构性前缀词。
# 真正的 gate 在 body_anchors 阶段通过正向证据（note_items 精确集合 +
# 非冗余 + 单次出现）完成，不依赖黑名单。
_BARE_DIGIT_STRUCTURAL_PREFIX = frozenset(
    {
        "p", "pp", "vol", "fig", "no", "n",
        "chap", "chapter", "section", "sect",
        "page", "pages", "line", "lines",
        "note", "notes", "part", "thesis",
        "problem", "table", "tableau",
        "article", "act", "scene",
    }
)
# OCR 常见上标乱码：'12、' 3、`45 等，数字前有一个孤立的撇号/反引号。
_APOSTROPHE_SUP_RE = re.compile(r"[\'`]\s*(\d{1,4})\b")
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
_LATEX_SYMBOL_SUP_RE = re.compile(r"\$\s*\^\{\s*(\*{1,4})\s*\}\s*\$")
# HTML 符号型脚注上标：<sup>*</sup>、<sup>**</sup>、<sup>***</sup>、<sup>****</sup>
_HTML_SYMBOL_SUP_RE = re.compile(r"<sup>\s*(\*{1,4})\s*</sup>", re.IGNORECASE)
_TRAILING_SYMBOL_AFTER_BRACKET_RE = re.compile(r"[\]](\*{1,4})")
_TRAILING_SYMBOL_AFTER_QUOTE_RE = re.compile(r"[»](\*{1,4})")
_REF_PATTERN_PRIORITY = {
    "footnote_ref": 0,
    "latex": 0,
    "latex_symbol_sup": 0,
    "html_symbol_sup": 0,
    "plain": 1,
    "html": 2,
    "unicode": 3,
    "apostrophe_sup": 3,
    "bracket": 4,
    "broken_left_bracket": 4,
    "trailing_symbol": 5,
    "bare_digit": 6,
}
_REF_PATTERN_CERTAINTY = {
    "footnote_ref": 1.0,
    "latex": 1.0,
    "html": 1.0,
    "html_symbol_sup": 1.0,
    "bracket": 1.0,
    "broken_left_bracket": 0.85,
    "unicode": 1.0,
    "plain": 0.4,
    "latex_symbol_sup": 1.0,
    "apostrophe_sup": 0.55,
    "trailing_symbol": 0.9,
    "bare_digit": 0.6,
}


def looks_like_year_marker(marker: str) -> bool:
    normalized = normalize_note_marker(marker)
    if len(normalized) != 4:
        return False
    try:
        value = int(normalized)
    except ValueError:
        return False
    return 1500 <= value <= 2100


def resolve_anchor_kind(
    *,
    has_page_footnote_band: bool = False,
    normalized_marker: str = "",
    chapter_endnote_markers: set[int] | None = None,
    pattern: str = "",
) -> str:
    source_pattern = str(pattern or "").strip()
    if source_pattern in {"bracket", "broken_left_bracket"}:
        return "footnote" if has_page_footnote_band else "unknown"

    # 优先级：格式分支 > endnote marker set 精匹配 > footnote band > unknown。
    # 对普通上标，即使页面有 footnote band，如果 marker 明确在本章 endnote
    # item set 中，仍应归为 endnote——单页可同时有脚注和尾注标记，不能整页广播。
    if normalized_marker.isdigit() and chapter_endnote_markers:
        if int(normalized_marker) in chapter_endnote_markers:
            return "endnote"
    if has_page_footnote_band:
        return "footnote"
    return "unknown"


def _paragraphs_from_markdown(page: Mapping[str, Any] | None) -> list[dict]:
    text = page_markdown_text(page)
    if not str(text or "").strip():
        return []
    paragraphs: list[dict] = []
    current_lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", str(raw_line or "")).strip()
        if not line:
            if current_lines:
                paragraphs.append(
                    {"text": " ".join(current_lines).strip(), "source": "markdown"}
                )
                current_lines = []
            continue
        if _MARKDOWN_HEADING_RE.match(raw_line) or is_notes_heading_line(line):
            if current_lines:
                paragraphs.append(
                    {"text": " ".join(current_lines).strip(), "source": "markdown"}
                )
                current_lines = []
            continue
        if _NOTE_DEFINITION_LINE_RE.match(line):
            if current_lines:
                paragraphs.append(
                    {"text": " ".join(current_lines).strip(), "source": "markdown"}
                )
                current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        paragraphs.append(
            {"text": " ".join(current_lines).strip(), "source": "markdown"}
        )
    return [row for row in paragraphs if str(row.get("text") or "").strip()]


def _paragraphs_from_ocr_blocks(page: Mapping[str, Any] | None) -> list[dict]:
    paragraphs: list[dict] = []
    for block in page_blocks(page):
        label = str(block.get("block_label") or "").strip().lower()
        if label in {"doc_title", "paragraph_title"}:
            continue
        text = re.sub(r"\s+", " ", str(block.get("block_content") or "")).strip()
        if len(text) < 20:
            continue
        if _NOTE_DEFINITION_LINE_RE.match(text) or is_notes_heading_line(text):
            continue
        paragraphs.append({"text": text, "source": "ocr_block"})
    return paragraphs


def _paragraph_dedupe_key(text: str) -> str:
    canonical = str(text or "")
    canonical = _FOOTNOTE_REF_RE.sub(lambda m: m.group(1), canonical)
    canonical = _LATEX_SUP_RE.sub(lambda m: m.group(1), canonical)
    canonical = _PLAIN_SUP_RE.sub(lambda m: m.group(1), canonical)
    canonical = _HTML_SUP_RE.sub(lambda m: m.group(1), canonical)
    canonical = _UNICODE_SUP_RE.sub(
        lambda m: m.group(0).translate(_UNICODE_SUPERSCRIPT_TO_DIGITS),
        canonical,
    )
    canonical = re.sub(r"<[^>]+>", "", canonical)
    return re.sub(r"\W+", "", canonical).lower()


def page_body_paragraphs(page: Mapping[str, Any] | None) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for row in [*_paragraphs_from_markdown(page), *_paragraphs_from_ocr_blocks(page)]:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        key = _paragraph_dedupe_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "text": text,
                "source": str(row.get("source") or ""),
                "paragraph_index": len(merged),
            }
        )
    return merged


def _is_bare_digit_marker_context(content: str, digit_start: int, digit_end: int) -> bool:
    """段落级廉价预过滤——只排除必定为噪声的候选。

    真正的正向验证在 body_anchors._positive_gate_bare_digit 完成。
    这里只做三件事：
      1. 左侧必须有 >=3 字符的词（排除 "p 5"、"de 68"）
      2. 左侧词是结构性前缀（"thesis"、"page"、"chapter"）-> 拒绝
      3. 右侧标点后紧跟数字 -> 列表/日期/千分位 -> 拒绝
    """
    left = content[:digit_start].rstrip()
    word_match = _BARE_DIGIT_LEFT_WORD_RE.search(left)
    if not word_match:
        return False
    word = word_match.group(1).lower()
    if len(word) < 3:
        return False
    if word in _BARE_DIGIT_STRUCTURAL_PREFIX:
        return False
    right = content[digit_end:].lstrip()
    punctuation = set(".,;:)]}»”’")
    while right and right[0] in punctuation:
        right = right[1:].lstrip()
    if right and right[0].isdigit():
        return False
    return True


def _scan_inline_refs(text: str) -> list[dict]:
    refs: list[dict] = []
    content = str(text or "")
    for pattern, kind in (
        (_FOOTNOTE_REF_RE, "footnote_ref"),
        (_LATEX_SUP_RE, "latex"),
        (_LATEX_SYMBOL_SUP_RE, "latex_symbol_sup"),
        (_HTML_SYMBOL_SUP_RE, "html_symbol_sup"),
        (_PLAIN_SUP_RE, "plain"),
        (_HTML_SUP_RE, "html"),
        (_BRACKET_REF_RE, "bracket"),
        (_BROKEN_LEFT_BRACKET_REF_RE, "broken_left_bracket"),
        (_APOSTROPHE_SUP_RE, "apostrophe_sup"),
        (_TRAILING_SYMBOL_AFTER_BRACKET_RE, "trailing_symbol"),
        (_TRAILING_SYMBOL_AFTER_QUOTE_RE, "trailing_symbol"),
    ):
        for match in pattern.finditer(content):
            marker = normalize_note_marker(match.group(1) or "")
            if not marker:
                continue
            refs.append(
                {
                    "source_marker": str(match.group(0) or "").strip(),
                    "normalized_marker": marker,
                    "char_start": int(match.start()),
                    "char_end": int(match.end()),
                    "pattern": kind,
                    "certainty": _REF_PATTERN_CERTAINTY.get(kind, 0.4),
                }
            )
    for match in _BARE_DIGIT_RE.finditer(content):
        digit_start = match.start(1)
        if not _is_bare_digit_marker_context(content, digit_start, match.end(1)):
            continue
        marker = normalize_note_marker(match.group(1) or "")
        if not marker:
            continue
        refs.append(
            {
                "source_marker": str(match.group(1) or "").strip(),
                "normalized_marker": marker,
                "char_start": int(digit_start),
                "char_end": int(match.end(1)),
                "pattern": "bare_digit",
                "certainty": _REF_PATTERN_CERTAINTY.get("bare_digit", 0.6),
            }
        )
    for match in _UNICODE_SUP_RE.finditer(content):
        marker = normalize_note_marker(
            match.group(0).translate(_UNICODE_SUPERSCRIPT_TO_DIGITS)
        )
        if not marker:
            continue
        refs.append(
            {
                "source_marker": str(match.group(0) or "").strip(),
                "normalized_marker": marker,
                "char_start": int(match.start()),
                "char_end": int(match.end()),
                "pattern": "unicode",
                "certainty": _REF_PATTERN_CERTAINTY.get("unicode", 1.0),
            }
        )
    refs.sort(key=lambda row: (int(row["char_start"]), int(row["char_end"])))
    return refs


def _overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return not (
        int(left.get("char_end") or 0) <= int(right.get("char_start") or 0)
        or int(right.get("char_end") or 0) <= int(left.get("char_start") or 0)
    )


def _preferred(left: dict, right: dict) -> dict:
    left_p = _REF_PATTERN_PRIORITY.get(str(left.get("pattern") or ""), 99)
    right_p = _REF_PATTERN_PRIORITY.get(str(right.get("pattern") or ""), 99)
    if right_p < left_p:
        return right
    if right_p > left_p:
        return left
    left_span = int(left.get("char_end") or 0) - int(left.get("char_start") or 0)
    right_span = int(right.get("char_end") or 0) - int(right.get("char_start") or 0)
    return right if right_span > left_span else left


def scan_anchor_markers(text: str) -> tuple[list[dict], int]:
    deduped: list[dict] = []
    year_like_filtered = 0
    for candidate in _scan_inline_refs(text):
        normalized = normalize_note_marker(candidate.get("normalized_marker") or "")
        if not normalized:
            continue
        if looks_like_year_marker(normalized):
            year_like_filtered += 1
            continue
        replaced = False
        for index, existing in enumerate(deduped):
            if str(existing.get("normalized_marker") or "") == normalized and _overlap(
                existing, candidate
            ):
                deduped[index] = _preferred(existing, candidate)
                replaced = True
                break
        if not replaced:
            deduped.append({**candidate, "normalized_marker": normalized})
    deduped.sort(
        key=lambda row: (int(row.get("char_start") or 0), int(row.get("char_end") or 0))
    )
    return deduped, year_like_filtered


def anchor_dedupe_key(
    *,
    chapter_id: str,
    page_no: int,
    paragraph_index: int,
    char_start: int,
    char_end: int,
    normalized_marker: str,
) -> str:
    return (
        f"{str(chapter_id).strip()}:"
        f"{int(page_no)}:{int(paragraph_index)}:{int(char_start)}:{int(char_end)}:"
        f"{normalize_note_marker(normalized_marker)}"
    )

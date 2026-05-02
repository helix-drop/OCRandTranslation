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
_BRACKET_REF_RE = re.compile(r"\[(\d{1,4})\]")
_UNICODE_SUP_RE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
_BARE_DIGIT_RE = re.compile(r"\s(\d{1,3})(?=[\.\,\;\:\)\]\}»]|\s+[\-–—])")
_BARE_DIGIT_LEFT_WORD_RE = re.compile(
    r"([A-Za-zàâäéèêëïîôöùûüÿçœÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇŒ]+)\s*$"
)
# 这些缩写/介词后的数字几乎肯定不是 note marker（页码/卷号/章号/引文锚）。
_BARE_DIGIT_LEFT_WORD_BLACKLIST = frozenset(
    {
        "p", "pp", "f", "ff", "vol", "t", "tome", "chap", "chapitre",
        "art", "article", "fig", "figure", "tableau", "tabl", "no",
        "sect", "section", "cf", "voir", "see", "infra", "supra",
        "loc", "op", "n",
        "et", "ou", "de", "du", "la", "le", "les", "un", "une",
        "il", "elle", "ils", "elles", "on", "y", "a", "as", "ai",
        "au", "aux", "ce", "ces", "ma", "ta", "sa", "mes", "tes", "ses",
        "in", "by", "to", "of", "at",
        "letter", "letters", "lettre", "lettres",
        "page", "pages", "para", "paragraph", "paragraphe",
        "number", "numbers", "numéro", "numéros",
        "ligne", "lignes", "line", "lines",
        "colonne", "col", "colonne",
        "note", "notes",
        "chapter", "chapters", "part", "partie",
        "book", "livre", "livres",
        "strophe", "stanza",
        "act", "scene", "scène",
        "épître", "epistle",
        # 学术书常见非 marker 上下文——月份/日期/文档编号/数量词
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
        "lesson", "leçon", "leçons",
        "mémoire", "memoir", "number", "numéro",
        "needs", "expect", "about", "some", "almost", "nearly",
        "volume", "volumes", "tome", "tomes",
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
_TRAILING_SYMBOL_AFTER_BRACKET_RE = re.compile(r"[\]](\*{1,4})")
_TRAILING_SYMBOL_AFTER_QUOTE_RE = re.compile(r"[»](\*{1,4})")
_REF_PATTERN_PRIORITY = {
    "footnote_ref": 0,
    "latex": 0,
    "latex_symbol_sup": 0,
    "plain": 1,
    "html": 2,
    "unicode": 3,
    "apostrophe_sup": 3,
    "bracket": 4,
    "trailing_symbol": 5,
    "bare_digit": 6,
}
_REF_PATTERN_CERTAINTY = {
    "footnote_ref": 1.0,
    "latex": 1.0,
    "html": 1.0,
    "bracket": 1.0,
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
) -> str:
    # 页上已经确认存在脚注带时，按脚注处理；
    # 这能兜住 post_body / 未显式建模章节中的真实页脚脚注。
    if has_page_footnote_band:
        return "footnote"
    # 无逐页 evidence 时返回 unknown——同一章内
    # 可以同时有 footnote 和 endnote marker，不能按章 mode 广播。
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


def page_body_paragraphs(page: Mapping[str, Any] | None) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for row in [*_paragraphs_from_markdown(page), *_paragraphs_from_ocr_blocks(page)]:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        key = re.sub(r"\W+", "", text).lower()
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
    """裸数字（"Encyclopédie 11"）守卫。

    左侧：紧邻词长度 ≥ 4 且不在引用前缀黑名单。
    右侧：跳过标点后紧跟数字（列表/日期/千分位）则拒绝。
    "needs 4, 5 or 6"、"August 4, 1789"、"2,000 copies" 都是非 marker。
    """
    left = content[:digit_start].rstrip()
    word_match = _BARE_DIGIT_LEFT_WORD_RE.search(left)
    if not word_match:
        return False
    word = word_match.group(1).lower()
    if len(word) < 4:
        return False
    if word in _BARE_DIGIT_LEFT_WORD_BLACKLIST:
        return False
    # 右侧守卫：跳过标点后如果紧跟数字，说明是列表/日期/千分位
    right = content[digit_end:].lstrip()
    # \u4f5c\u8005\u9996\u5b57\u6bcd+\u5e74\u4efd\u6a21\u5f0f\uff1a"Z (2017)"\u3001"X 1999)"\u2014\u2014\u4e0d\u662f note marker
    if len(word) == 1 and word.isalpha():
        return False
    punctuation = set(".,;:)]}\u00bb\u201d\u2019")
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
        (_PLAIN_SUP_RE, "plain"),
        (_HTML_SUP_RE, "html"),
        (_BRACKET_REF_RE, "bracket"),
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

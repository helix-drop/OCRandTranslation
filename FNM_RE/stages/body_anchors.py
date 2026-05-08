"""FNM_RE 第三阶段：body_anchors。"""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any

from FNM_RE.models import BodyAnchorRecord, Phase2Structure
from FNM_RE.shared.chapters import chapter_id_for_page, chapter_id_for_page as _chapter_id_for_page
from FNM_RE.shared.anchors import (
    anchor_dedupe_key,
    page_body_paragraphs,
    resolve_anchor_kind,
    scan_anchor_markers,
)

_WEAK_EXPECTED_DIGIT_RE = re.compile(
    r"\s(\d{1,3})(?=(?:\s*[.,;:)\]\}»”’\"]|\s+[A-Za-zÀ-ÖØ-öø-ÿ]))"
)
_WEAK_DIGIT_LEFT_WORD_RE = re.compile(
    r"([A-Za-zàâäéèêëïîôöùûüÿçœÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇŒ]+)\s*$"
)
_WEAK_DIGIT_STRUCTURAL_PREFIX = frozenset(
    {
        "p",
        "pp",
        "vol",
        "fig",
        "no",
        "n",
        "chap",
        "chapter",
        "section",
        "sect",
        "page",
        "pages",
        "line",
        "lines",
        "note",
        "notes",
        "part",
        "thesis",
        "table",
        "tableau",
        "article",
        "act",
        "scene",
    }
)
_WEAK_EXPECTED_SYMBOL_RE = re.compile(
    r"(?<=[A-Za-zÀ-ÖØ-öø-ÿ])(\*{1,3})(?=(?:\s|[.,;:)\]\}»”’\"]))"
)
_CONTEXT_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
_CONTEXT_STOPWORDS = frozenset(
    {
        "avec",
        "cette",
        "dans",
        "dont",
        "elle",
        "elles",
        "entre",
        "pour",
        "quand",
        "sans",
        "sont",
        "tout",
        "toute",
        "vous",
        "mais",
        "donc",
        "comme",
        "plus",
        "moins",
        "faire",
        "fait",
        "être",
        "etre",
        "cela",
        "ceci",
        "leur",
        "leurs",
        "dune",
        "dun",
        "dune",
    }
)


def _chapter_id_for_page(phase2: Phase2Structure, page_no: int) -> str:
    return chapter_id_for_page(phase2.chapters, page_no)


def _page_payload_by_no(pages: list[dict]) -> dict[int, dict]:
    mapping: dict[int, dict] = {}
    for page in pages or []:
        try:
            page_no = int(page.get("bookPage") or 0)
        except (TypeError, ValueError):
            continue
        if page_no > 0:
            mapping[page_no] = dict(page)
    return mapping


def _footnote_band_page_keys(phase2: Phase2Structure) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    for region in phase2.note_regions:
        if region.note_kind != "footnote":
            continue
        chapter_id = str(region.chapter_id or "").strip()
        if not chapter_id:
            continue
        for page_no in region.pages:
            if int(page_no) > 0:
                keys.add((chapter_id, int(page_no)))
    return keys


def _build_summary(
    anchors: list[BodyAnchorRecord], *, year_like_filtered_count: int
) -> dict[str, Any]:
    kind_counts = Counter(anchor.anchor_kind for anchor in anchors)
    explicit_count = sum(1 for anchor in anchors if not anchor.synthetic)
    synthetic_count = sum(1 for anchor in anchors if anchor.synthetic)
    uncertain_count = sum(
        1
        for anchor in anchors
        if anchor.anchor_kind == "unknown" or float(anchor.certainty) < 1.0
    )
    ocr_repaired_count = sum(
        1 for anchor in anchors if str(anchor.ocr_repaired_from_marker or "").strip()
    )
    return {
        "total_count": len(anchors),
        "explicit_count": int(explicit_count),
        "synthetic_count": int(synthetic_count),
        "kind_counts": dict(kind_counts),
        "uncertain_count": int(uncertain_count),
        "ocr_repaired_count": int(ocr_repaired_count),
        "year_like_filtered_count": int(year_like_filtered_count),
    }


def _build_chapter_marker_range(phase2: Phase2Structure) -> dict[str, tuple[int, int]]:
    """从 note_items 构建每章 marker 的预期范围。"""
    chapter_markers: dict[str, list[int]] = {}
    for item in phase2.note_items:
        chapter_id = str(item.chapter_id or "").strip()
        if not chapter_id:
            continue
        try:
            marker = int(item.marker)
        except (ValueError, TypeError):
            continue
        if marker <= 0:
            continue
        chapter_markers.setdefault(chapter_id, []).append(marker)
    return {
        ch_id: (min(markers), max(markers))
        for ch_id, markers in chapter_markers.items()
        if markers
    }


def _build_chapter_note_items_set(phase2: Phase2Structure) -> dict[str, set[int]]:
    """从 note_items 构建每章 marker 的精确集合（含 footnote + endnote）。"""
    sets: dict[str, set[int]] = {}
    for item in phase2.note_items:
        chapter_id = str(item.chapter_id or "").strip()
        if not chapter_id:
            continue
        try:
            marker = int(item.marker)
        except (ValueError, TypeError):
            continue
        if marker <= 0:
            continue
        sets.setdefault(chapter_id, set()).add(marker)
    return sets


def _build_chapter_endnote_marker_set(phase2: Phase2Structure) -> dict[str, set[int]]:
    """从 note_items 构建每章 endnote marker 的实际集合（仅 endnote kind）。"""
    endnote_region_ids: set[str] = {
        str(r.region_id or "").strip()
        for r in phase2.note_regions
        if str(r.note_kind or "") == "endnote" and str(r.region_id or "").strip()
    }
    sets: dict[str, set[int]] = {}
    for item in phase2.note_items:
        if str(item.region_id or "").strip() not in endnote_region_ids:
            continue
        chapter_id = str(item.chapter_id or "").strip()
        if not chapter_id:
            continue
        try:
            marker = int(item.marker)
        except (ValueError, TypeError):
            continue
        if marker <= 0:
            continue
        sets.setdefault(chapter_id, set()).add(marker)
    return sets


def _build_chapter_endnote_text_by_marker(phase2: Phase2Structure) -> dict[str, dict[int, str]]:
    endnote_region_ids: set[str] = {
        str(r.region_id or "").strip()
        for r in phase2.note_regions
        if str(r.note_kind or "") == "endnote" and str(r.region_id or "").strip()
    }
    rows: dict[str, dict[int, str]] = defaultdict(dict)
    for item in phase2.note_items:
        if str(item.region_id or "").strip() not in endnote_region_ids:
            continue
        chapter_id = str(item.chapter_id or "").strip()
        marker = _int_marker(getattr(item, "marker", ""))
        if not chapter_id or marker is None:
            continue
        rows[chapter_id][marker] = str(getattr(item, "text", "") or "")
    return {chapter_id: dict(items) for chapter_id, items in rows.items()}


def _marker_in_expected_range(
    normalized_marker: str,
    *,
    pattern: str,
    marker_min: int,
    marker_max: int,
    has_page_footnote_band: bool = False,
) -> bool:
    """范围预过滤（cheap）：marker 是否在章节的预期范围内。

    高置信度模式始终保留。
    bare_digit 只做范围卡，真正的正向验证在 _positive_gate_bare_digit 完成。
    """
    if has_page_footnote_band:
        return True
    if marker_max <= 0:
        return True
    try:
        marker_val = int(normalized_marker)
    except (ValueError, TypeError):
        return True
    if pattern in {"latex", "latex_symbol_sup", "plain", "html", "unicode", "footnote_ref", "apostrophe_sup"}:
        return True
    if pattern == "bare_digit":
        return marker_min <= marker_val <= marker_max
    tolerance = max(3, int(marker_max * 0.03))
    return marker_min <= marker_val <= marker_max + tolerance


_BARE_DIGIT_VALID_SENTENCE_END = frozenset({".", ";", ":", "!", "?", ",", "—", "–", "-"})


def _is_bare_digit_false_positive_context(anchor: BodyAnchorRecord) -> bool:
    """正向上下文守卫：bare_digit 仅当处于句末/段尾位置时才可能是尾注标记。

    白名单（满足任一 → 保留，不触发拒绝）：
      1. 数字是段落最后一个非空白字符（段尾）
      2. 数字后紧跟句末标点或破折号（.,;:!?—–-）

    不在白名单中的 bare_digit（如后跟字母、引号、括号等）将被拒绝。
    """
    source_text = str(anchor.source_text or "").strip()
    if not source_text:
        return False

    char_end = int(anchor.char_end or 0)
    remainder = source_text[char_end:]

    if not remainder.strip():
        return False  # 段尾 → 保留

    next_char = remainder.lstrip()[0] if remainder.lstrip() else ""
    if next_char in _BARE_DIGIT_VALID_SENTENCE_END:
        return False  # 句末标点 → 保留

    return True  # 不在白名单 → 拒绝


def _positive_gate_bare_digit(
    anchors: list[BodyAnchorRecord],
    *,
    chapter_note_items: dict[str, set[int]],
) -> list[BodyAnchorRecord]:
    """正向证据 gate：bare_digit 必须满足正向条件才能保留。

    正向条件（全部必须满足）：
      1. marker 在 note_items 精确集合中（不仅是范围内）
      2. 该 marker 尚未被更高置信度 pattern 覆盖（非冗余）
      3. 该 marker 的 bare_digit 出现次数 <= 2（单次性）

    设计原理：
      - 条件 1 排除 "范围内但不是真实 note" 的数字（如 thesis 编号）
      - 条件 2 排除已由 latex/html/unicode/plain 覆盖的 marker（冗余 = 噪声）
      - 条件 3 排除语义数字（如 "La Pensée 68" 在文中多次出现）
    """
    # 分离 bare_digit 和非 bare_digit
    non_bare: list[BodyAnchorRecord] = []
    bare_candidates: list[BodyAnchorRecord] = []
    for anchor in anchors:
        if anchor.source.endswith(":bare_digit"):
            bare_candidates.append(anchor)
        else:
            non_bare.append(anchor)

    if not bare_candidates:
        return anchors

    # 每章已被非 bare_digit 覆盖的 marker 集合
    covered_by_chapter: dict[str, set[int]] = defaultdict(set)
    for anchor in non_bare:
        try:
            val = int(anchor.normalized_marker)
        except (ValueError, TypeError):
            continue
        covered_by_chapter[anchor.chapter_id].add(val)

    # 每章 bare_digit 各 marker 出现次数
    bare_count_by_chapter: dict[str, Counter[int]] = defaultdict(Counter)
    for anchor in bare_candidates:
        try:
            val = int(anchor.normalized_marker)
        except (ValueError, TypeError):
            continue
        bare_count_by_chapter[anchor.chapter_id][val] += 1

    accepted_bare: list[BodyAnchorRecord] = []
    for anchor in bare_candidates:
        chapter_id = anchor.chapter_id
        try:
            marker_val = int(anchor.normalized_marker)
        except (ValueError, TypeError):
            continue

        note_items_set = chapter_note_items.get(chapter_id)

        # 条件 1：marker 必须在 note_items 精确集合中
        if not note_items_set or marker_val not in note_items_set:
            continue

        # 条件 2：marker 不能已被更高置信度 pattern 覆盖
        if marker_val in covered_by_chapter[chapter_id]:
            continue

        # 条件 3：同章内 bare_digit 对该 marker 的声明次数 <= 2
        if bare_count_by_chapter[chapter_id][marker_val] > 2:
            continue

        # 条件 4：语义上下文守卫 — 排除明显不是尾注标记的 bare_digit
        if _is_bare_digit_false_positive_context(anchor):
            continue

        accepted_bare.append(anchor)

    return non_bare + accepted_bare


def _int_marker(value: Any) -> int | None:
    try:
        marker = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return marker if marker > 0 else None


def _scan_expected_gap_bare_digits(text: str, expected_markers: set[int]) -> list[dict]:
    if not expected_markers:
        return []
    content = str(text or "")
    matches: list[dict] = []
    for match in _WEAK_EXPECTED_DIGIT_RE.finditer(content):
        marker = _int_marker(match.group(1))
        if marker is None or marker not in expected_markers:
            continue
        left = content[: match.start(1)].rstrip()
        word_match = _WEAK_DIGIT_LEFT_WORD_RE.search(left)
        if not word_match:
            continue
        left_word = word_match.group(1).lower()
        if len(left_word) < 2 or left_word in _WEAK_DIGIT_STRUCTURAL_PREFIX:
            continue
        matches.append(
            {
                "source_marker": str(match.group(1) or "").strip(),
                "normalized_marker": str(marker),
                "char_start": int(match.start(1)),
                "char_end": int(match.end(1)),
                "pattern": "expected_gap_bare_digit",
                "certainty": 0.72,
            }
        )
    return matches


def _distinct_context_words(words: list[str]) -> list[str]:
    out: list[str] = []
    for word in words:
        normalized = str(word or "").lower().strip("'’")
        if len(normalized) < 4 or normalized in _CONTEXT_STOPWORDS:
            continue
        out.append(normalized)
    return out


def _words_around_span(text: str, start: int, end: int, *, radius: int = 6) -> list[str]:
    left = _CONTEXT_WORD_RE.findall(str(text or "")[:start])[-radius:]
    right = _CONTEXT_WORD_RE.findall(str(text or "")[end:])[:radius]
    return left + right


def _symbol_context_alignment_score(context_words: list[str], note_text: str) -> int:
    words = _distinct_context_words(context_words)
    if not words:
        return 0
    note_words = _distinct_context_words(_CONTEXT_WORD_RE.findall(str(note_text or "")))
    if not note_words:
        return 0
    note_set = set(note_words)
    score = sum(1 for word in words if word in note_set)

    candidate_bigrams = set(zip(words, words[1:]))
    note_bigrams = set(zip(note_words, note_words[1:]))
    score += 2 * len(candidate_bigrams & note_bigrams)

    candidate_trigrams = set(zip(words, words[1:], words[2:]))
    note_trigrams = set(zip(note_words, note_words[1:], note_words[2:]))
    score += 3 * len(candidate_trigrams & note_trigrams)
    return int(score)


def _scan_expected_gap_symbols(
    text: str,
    *,
    expected_markers: set[int],
    note_text_by_marker: dict[int, str],
) -> list[dict]:
    if not expected_markers:
        return []
    content = str(text or "")
    matches: list[dict] = []
    for match in _WEAK_EXPECTED_SYMBOL_RE.finditer(content):
        context_words = _words_around_span(content, int(match.start(1)), int(match.end(1)))
        for marker in sorted(expected_markers):
            score = _symbol_context_alignment_score(
                context_words,
                note_text_by_marker.get(marker, ""),
            )
            if score < 2:
                continue
            matches.append(
                {
                    "source_marker": str(match.group(1) or "").strip(),
                    "normalized_marker": str(marker),
                    "char_start": int(match.start(1)),
                    "char_end": int(match.end(1)),
                    "pattern": "expected_gap_symbol",
                    "certainty": 0.76,
                    "context_score": int(score),
                }
            )
    return matches


def _known_endnote_marker_pages(
    anchors: list[BodyAnchorRecord],
) -> dict[str, dict[int, list[int]]]:
    by_chapter: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for anchor in anchors:
        if str(anchor.anchor_kind or "") != "endnote":
            continue
        marker = _int_marker(anchor.normalized_marker)
        if marker is None:
            continue
        page_no = int(anchor.page_no or 0)
        if page_no <= 0:
            continue
        by_chapter[str(anchor.chapter_id or "")][marker].append(page_no)
    return {cid: {marker: pages for marker, pages in rows.items()} for cid, rows in by_chapter.items()}


def _within_sequence_page_window(
    marker: int,
    page_no: int,
    known_pages_by_marker: dict[int, list[int]],
) -> bool:
    if page_no <= 0 or not known_pages_by_marker:
        return False
    lower_markers = [value for value in known_pages_by_marker if value < marker]
    upper_markers = [value for value in known_pages_by_marker if value > marker]
    lower = max(lower_markers) if lower_markers else None
    upper = min(upper_markers) if upper_markers else None
    if lower is None and upper is None:
        return False
    if lower is not None and upper is not None:
        low_page = min(known_pages_by_marker[lower])
        high_page = max(known_pages_by_marker[upper])
        start = min(low_page, high_page) - 1
        end = max(low_page, high_page) + 1
        return start <= page_no <= end
    if lower is not None:
        anchor_page = max(known_pages_by_marker[lower])
        return anchor_page - 1 <= page_no <= anchor_page + 2
    anchor_page = min(known_pages_by_marker[upper])  # type: ignore[index]
    return anchor_page - 2 <= page_no <= anchor_page + 1


def _recover_expected_gap_bare_digit_anchors(
    anchors: list[BodyAnchorRecord],
    *,
    phase2: Phase2Structure,
    page_by_no: dict[int, dict],
    page_role_by_no: dict[int, str],
    footnote_band_pages: set[tuple[str, int]],
    chapter_endnote_markers: dict[str, set[int]],
    seen: set[str],
    anchor_counter: int,
) -> tuple[list[BodyAnchorRecord], int]:
    known_pages = _known_endnote_marker_pages(anchors)
    existing_by_chapter = {
        chapter_id: set(marker_pages)
        for chapter_id, marker_pages in known_pages.items()
    }
    missing_by_chapter = {
        chapter_id: set(markers) - existing_by_chapter.get(chapter_id, set())
        for chapter_id, markers in chapter_endnote_markers.items()
        if set(markers) - existing_by_chapter.get(chapter_id, set())
    }
    if not missing_by_chapter:
        return anchors, anchor_counter

    candidates: list[tuple[int, int, dict, dict]] = []
    for page_no in sorted(page_role_by_no):
        if page_role_by_no.get(page_no) not in {"body", "front_matter"}:
            continue
        chapter_id = _chapter_id_for_page(phase2, page_no)
        expected_markers = missing_by_chapter.get(chapter_id)
        if not expected_markers:
            continue
        known_for_chapter = known_pages.get(chapter_id, {})
        if not known_for_chapter:
            continue
        page_payload = page_by_no.get(page_no) or {}
        for paragraph in page_body_paragraphs(page_payload):
            paragraph_text = str(paragraph.get("text") or "").strip()
            paragraph_index = int(paragraph.get("paragraph_index") or 0)
            if not paragraph_text:
                continue
            for match in _scan_expected_gap_bare_digits(paragraph_text, expected_markers):
                marker = _int_marker(match.get("normalized_marker"))
                if marker is None:
                    continue
                if not _within_sequence_page_window(marker, page_no, known_for_chapter):
                    continue
                key = anchor_dedupe_key(
                    chapter_id=chapter_id,
                    page_no=page_no,
                    paragraph_index=paragraph_index,
                    char_start=int(match.get("char_start") or 0),
                    char_end=int(match.get("char_end") or 0),
                    normalized_marker=str(marker),
                )
                if key in seen:
                    continue
                candidates.append((page_no, paragraph_index, paragraph, match))

    count_by_chapter_marker: Counter[tuple[str, int]] = Counter()
    for page_no, _paragraph_index, _paragraph, match in candidates:
        chapter_id = _chapter_id_for_page(phase2, page_no)
        marker = _int_marker(match.get("normalized_marker"))
        if marker is not None:
            count_by_chapter_marker[(chapter_id, marker)] += 1

    for page_no, paragraph_index, paragraph, match in candidates:
        chapter_id = _chapter_id_for_page(phase2, page_no)
        marker = _int_marker(match.get("normalized_marker"))
        if marker is None or count_by_chapter_marker[(chapter_id, marker)] != 1:
            continue
        key = anchor_dedupe_key(
            chapter_id=chapter_id,
            page_no=page_no,
            paragraph_index=paragraph_index,
            char_start=int(match.get("char_start") or 0),
            char_end=int(match.get("char_end") or 0),
            normalized_marker=str(marker),
        )
        if key in seen:
            continue
        seen.add(key)
        has_page_footnote_band = (chapter_id, page_no) in footnote_band_pages
        anchors.append(
            BodyAnchorRecord(
                anchor_id=f"anchor-{anchor_counter:05d}",
                chapter_id=chapter_id,
                page_no=page_no,
                paragraph_index=paragraph_index,
                char_start=int(match.get("char_start") or 0),
                char_end=int(match.get("char_end") or 0),
                source_marker=str(match.get("source_marker") or ""),
                normalized_marker=str(marker),
                        anchor_kind=resolve_anchor_kind(  # type: ignore[arg-type]
                            has_page_footnote_band=has_page_footnote_band,
                            normalized_marker=str(marker),
                            chapter_endnote_markers=chapter_endnote_markers.get(chapter_id, set()),
                            pattern=str(match.get("pattern") or ""),
                        ),
                certainty=float(match.get("certainty", 0.72)),
                source_text=str(paragraph.get("text") or ""),
                source=f"{str(paragraph.get('source') or 'markdown')}:expected_gap_bare_digit",
                synthetic=False,
                ocr_repaired_from_marker="",
            )
        )
        anchor_counter += 1
    return anchors, anchor_counter


def _recover_expected_gap_symbol_anchors(
    anchors: list[BodyAnchorRecord],
    *,
    phase2: Phase2Structure,
    page_by_no: dict[int, dict],
    page_role_by_no: dict[int, str],
    footnote_band_pages: set[tuple[str, int]],
    chapter_endnote_markers: dict[str, set[int]],
    chapter_endnote_text_by_marker: dict[str, dict[int, str]],
    seen: set[str],
    anchor_counter: int,
) -> tuple[list[BodyAnchorRecord], int]:
    known_pages = _known_endnote_marker_pages(anchors)
    existing_by_chapter = {
        chapter_id: set(marker_pages)
        for chapter_id, marker_pages in known_pages.items()
    }
    missing_by_chapter = {
        chapter_id: set(markers) - existing_by_chapter.get(chapter_id, set())
        for chapter_id, markers in chapter_endnote_markers.items()
        if set(markers) - existing_by_chapter.get(chapter_id, set())
    }
    if not missing_by_chapter:
        return anchors, anchor_counter

    candidates: list[tuple[int, int, dict, dict]] = []
    for page_no in sorted(page_role_by_no):
        if page_role_by_no.get(page_no) not in {"body", "front_matter"}:
            continue
        chapter_id = _chapter_id_for_page(phase2, page_no)
        expected_markers = missing_by_chapter.get(chapter_id)
        if not expected_markers:
            continue
        known_for_chapter = known_pages.get(chapter_id, {})
        if not known_for_chapter:
            continue
        note_text_by_marker = chapter_endnote_text_by_marker.get(chapter_id, {})
        if not note_text_by_marker:
            continue
        page_payload = page_by_no.get(page_no) or {}
        for paragraph in page_body_paragraphs(page_payload):
            paragraph_text = str(paragraph.get("text") or "").strip()
            paragraph_index = int(paragraph.get("paragraph_index") or 0)
            if not paragraph_text:
                continue
            for match in _scan_expected_gap_symbols(
                paragraph_text,
                expected_markers=expected_markers,
                note_text_by_marker=note_text_by_marker,
            ):
                marker = _int_marker(match.get("normalized_marker"))
                if marker is None:
                    continue
                if not _within_sequence_page_window(marker, page_no, known_for_chapter):
                    continue
                key = anchor_dedupe_key(
                    chapter_id=chapter_id,
                    page_no=page_no,
                    paragraph_index=paragraph_index,
                    char_start=int(match.get("char_start") or 0),
                    char_end=int(match.get("char_end") or 0),
                    normalized_marker=str(marker),
                )
                if key in seen:
                    continue
                candidates.append((page_no, paragraph_index, paragraph, match))

    grouped: dict[tuple[str, int], list[tuple[int, int, dict, dict]]] = defaultdict(list)
    for row in candidates:
        page_no, _paragraph_index, _paragraph, match = row
        chapter_id = _chapter_id_for_page(phase2, page_no)
        marker = _int_marker(match.get("normalized_marker"))
        if marker is not None:
            grouped[(chapter_id, marker)].append(row)

    selected: list[tuple[int, int, dict, dict]] = []
    for (_chapter_id, _marker), rows in grouped.items():
        ranked = sorted(
            rows,
            key=lambda row: int(row[3].get("context_score") or 0),
            reverse=True,
        )
        if not ranked:
            continue
        best_score = int(ranked[0][3].get("context_score") or 0)
        if best_score < 2:
            continue
        if len(ranked) > 1 and int(ranked[1][3].get("context_score") or 0) == best_score:
            continue
        selected.append(ranked[0])

    for page_no, paragraph_index, paragraph, match in selected:
        chapter_id = _chapter_id_for_page(phase2, page_no)
        marker = _int_marker(match.get("normalized_marker"))
        if marker is None:
            continue
        key = anchor_dedupe_key(
            chapter_id=chapter_id,
            page_no=page_no,
            paragraph_index=paragraph_index,
            char_start=int(match.get("char_start") or 0),
            char_end=int(match.get("char_end") or 0),
            normalized_marker=str(marker),
        )
        if key in seen:
            continue
        seen.add(key)
        has_page_footnote_band = (chapter_id, page_no) in footnote_band_pages
        anchors.append(
            BodyAnchorRecord(
                anchor_id=f"anchor-{anchor_counter:05d}",
                chapter_id=chapter_id,
                page_no=page_no,
                paragraph_index=paragraph_index,
                char_start=int(match.get("char_start") or 0),
                char_end=int(match.get("char_end") or 0),
                source_marker=str(match.get("source_marker") or ""),
                normalized_marker=str(marker),
                        anchor_kind=resolve_anchor_kind(  # type: ignore[arg-type]
                            has_page_footnote_band=has_page_footnote_band,
                            normalized_marker=str(marker),
                            chapter_endnote_markers=chapter_endnote_markers.get(chapter_id, set()),
                            pattern=str(match.get("pattern") or ""),
                        ),
                certainty=float(match.get("certainty", 0.76)),
                source_text=str(paragraph.get("text") or ""),
                source=f"{str(paragraph.get('source') or 'markdown')}:expected_gap_symbol",
                synthetic=False,
                ocr_repaired_from_marker=str(match.get("source_marker") or ""),
            )
        )
        anchor_counter += 1
    return anchors, anchor_counter


def build_body_anchors(
    phase2: Phase2Structure,
    *,
    pages: list[dict],
    pdf_path: str = "",
) -> tuple[list[BodyAnchorRecord], dict]:
    page_by_no = _page_payload_by_no(pages)
    page_role_by_no = {
        int(row.page_no): str(row.page_role)
        for row in phase2.pages
        if int(row.page_no) > 0
    }
    footnote_band_pages = _footnote_band_page_keys(phase2)
    chapter_marker_range = _build_chapter_marker_range(phase2)
    chapter_endnote_markers = _build_chapter_endnote_marker_set(phase2)
    chapter_note_items = _build_chapter_note_items_set(phase2)
    chapter_endnote_text_by_marker = _build_chapter_endnote_text_by_marker(phase2)

    anchors: list[BodyAnchorRecord] = []
    seen: set[str] = set()
    anchor_counter = 1
    year_like_filtered_total = 0
    for page_no in sorted(page_role_by_no):
        if page_role_by_no.get(page_no) not in {"body", "front_matter"}:
            continue
        chapter_id = _chapter_id_for_page(phase2, page_no)
        if not chapter_id:
            continue
        has_page_footnote_band = (chapter_id, page_no) in footnote_band_pages
        marker_min, marker_max = chapter_marker_range.get(chapter_id, (0, 0))
        page_payload = page_by_no.get(page_no) or {}
        for paragraph in page_body_paragraphs(page_payload):
            paragraph_text = str(paragraph.get("text") or "").strip()
            paragraph_index = int(paragraph.get("paragraph_index") or 0)
            if not paragraph_text:
                continue
            matches, year_like_filtered = scan_anchor_markers(paragraph_text)
            year_like_filtered_total += int(year_like_filtered)
            for match in matches:
                normalized_marker = str(match.get("normalized_marker") or "").strip()
                if not normalized_marker:
                    continue
                if not _marker_in_expected_range(
                    normalized_marker,
                    pattern=str(match.get("pattern") or ""),
                    marker_min=marker_min,
                    marker_max=marker_max,
                    has_page_footnote_band=has_page_footnote_band,
                ):
                    continue
                char_start = int(match.get("char_start") or 0)
                char_end = int(match.get("char_end") or 0)
                key = anchor_dedupe_key(
                    chapter_id=chapter_id,
                    page_no=page_no,
                    paragraph_index=paragraph_index,
                    char_start=char_start,
                    char_end=char_end,
                    normalized_marker=normalized_marker,
                )
                if key in seen:
                    continue
                seen.add(key)
                anchors.append(
                    BodyAnchorRecord(
                        anchor_id=f"anchor-{anchor_counter:05d}",
                        chapter_id=chapter_id,
                        page_no=page_no,
                        paragraph_index=paragraph_index,
                        char_start=char_start,
                        char_end=char_end,
                        source_marker=str(match.get("source_marker") or ""),
                        normalized_marker=normalized_marker,
                        anchor_kind=resolve_anchor_kind(  # type: ignore[arg-type]
                            has_page_footnote_band=has_page_footnote_band,
                            normalized_marker=normalized_marker,
                            chapter_endnote_markers=chapter_endnote_markers.get(chapter_id, set()),
                            pattern=str(match.get("pattern") or ""),
                        ),
                        certainty=float(match.get("certainty", 0.4)),
                        source_text=paragraph_text,
                        source=f"{str(paragraph.get('source') or 'markdown')}:{str(match.get('pattern') or 'ref')}",
                        synthetic=False,
                        ocr_repaired_from_marker="",
                    )
                )
                anchor_counter += 1

    # 正向证据 gate：过滤 bare_digit 假阳性
    anchors = _positive_gate_bare_digit(
        anchors, chapter_note_items=chapter_note_items
    )
    anchors, anchor_counter = _recover_expected_gap_bare_digit_anchors(
        anchors,
        phase2=phase2,
        page_by_no=page_by_no,
        page_role_by_no=page_role_by_no,
        footnote_band_pages=footnote_band_pages,
        chapter_endnote_markers=chapter_endnote_markers,
        seen=seen,
        anchor_counter=anchor_counter,
    )
    anchors, anchor_counter = _recover_expected_gap_symbol_anchors(
        anchors,
        phase2=phase2,
        page_by_no=page_by_no,
        page_role_by_no=page_role_by_no,
        footnote_band_pages=footnote_band_pages,
        chapter_endnote_markers=chapter_endnote_markers,
        chapter_endnote_text_by_marker=chapter_endnote_text_by_marker,
        seen=seen,
        anchor_counter=anchor_counter,
    )

    anchors.sort(
        key=lambda row: (
            int(row.page_no),
            int(row.paragraph_index),
            int(row.char_start),
            row.anchor_id,
        )
    )
    summary = _build_summary(anchors, year_like_filtered_count=year_like_filtered_total)
    return anchors, summary

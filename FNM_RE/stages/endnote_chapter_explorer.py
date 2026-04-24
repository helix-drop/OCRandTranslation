"""基于尾注页结构信号探索 chapter 绑定。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import re
from typing import Any, Mapping

from FNM_RE.models import HeadingCandidate, NoteRegionRecord, Phase1Structure
from FNM_RE.shared.text import extract_page_headings
from FNM_RE.shared.title import chapter_title_match_key, normalize_title

_GENERIC_NOTES_TITLE_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*|注释|脚注|尾注)\s*$",
    re.IGNORECASE,
)
_NAMED_NOTES_TARGET_RE = re.compile(r"^\s*notes?\s+to\s+(.+?)\s*$", re.IGNORECASE)
_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_NUMBER_TOKEN_PATTERN = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[ivxlcdm]+|\d+)"
_CHAPTER_NUMBER_RE = re.compile(
    rf"^\s*(?:chapter|chapitre)\s+({_NUMBER_TOKEN_PATTERN})\b(?:[\s:.\-]+(.*))?$",
    re.IGNORECASE,
)
_LEADING_NUMBER_RE = re.compile(rf"^\s*({_NUMBER_TOKEN_PATTERN})[\.\)]?(?:\s+|$)(.*)$", re.IGNORECASE)
_ROMAN_DIGITS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


@dataclass(slots=True)
class _PageChapterSignal:
    page_no: int
    chapter_id: str
    chapter_title: str
    signal_title: str
    source: str
    score: float


def _is_generic_notes_title(text: str) -> bool:
    return bool(_GENERIC_NOTES_TITLE_RE.match(normalize_title(text)))


def _roman_to_int(token: str) -> int:
    total = 0
    previous = 0
    for char in reversed(str(token or "").upper()):
        value = int(_ROMAN_DIGITS.get(char) or 0)
        if value <= 0:
            return 0
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return total


def _number_token_to_int(token: str) -> int:
    raw = str(token or "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)
    if raw.lower() in _WORD_NUMBERS:
        return int(_WORD_NUMBERS[raw.lower()])
    return _roman_to_int(raw)


def _extract_number_info(text: str) -> tuple[int, str]:
    normalized = normalize_title(text)
    if not normalized:
        return 0, ""
    match = _CHAPTER_NUMBER_RE.match(normalized)
    if match:
        number_value = _number_token_to_int(str(match.group(1) or ""))
        remainder = normalize_title(str(match.group(2) or ""))
        return number_value, remainder
    match = _LEADING_NUMBER_RE.match(normalized)
    if match:
        number_value = _number_token_to_int(str(match.group(1) or ""))
        remainder = normalize_title(str(match.group(2) or ""))
        return number_value, remainder
    return 0, normalized


def _chapter_rows(phase1: Phase1Structure) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order_index, chapter in enumerate(phase1.chapters, start=1):
        title = normalize_title(chapter.title)
        match_key = chapter_title_match_key(title)
        if not title or not match_key:
            continue
        number_value, _remainder = _extract_number_info(title)
        rows.append(
            {
                "chapter_id": str(chapter.chapter_id or ""),
                "chapter_title": title,
                "match_key": match_key,
                "order_index": int(order_index),
                "number_value": int(number_value or 0),
                "numbered_order_index": 0,
            }
        )
    numbered_rows = [row for row in rows if int(row.get("number_value") or 0) > 0]
    for index, row in enumerate(numbered_rows, start=1):
        row["numbered_order_index"] = int(index)
    return rows


def _match_signal_to_chapter(signal_title: str, chapters: list[dict[str, Any]]) -> tuple[str, str, float] | None:
    normalized_title = normalize_title(signal_title)
    signal_key = chapter_title_match_key(normalized_title)
    if not normalized_title or not signal_key:
        return None
    signal_number, signal_remainder = _extract_number_info(normalized_title)
    signal_remainder_key = chapter_title_match_key(signal_remainder)

    best_row: dict[str, Any] | None = None
    best_score = 0.0
    normalized_lower = normalized_title.lower()
    for row in chapters:
        chapter_key = str(row.get("match_key") or "").strip()
        chapter_title = str(row.get("chapter_title") or "").strip()
        if not chapter_key or not chapter_title:
            continue
        chapter_number, chapter_remainder = _extract_number_info(chapter_title)
        chapter_remainder_key = chapter_title_match_key(chapter_remainder)
        if signal_key == chapter_key:
            score = 1.0
        elif (
            int(signal_number or 0) > 0
            and int(chapter_number or 0) == int(signal_number)
            and len(chapter_remainder_key) >= 12
            and signal_remainder_key.startswith(chapter_remainder_key)
        ):
            score = 0.99
        elif len(chapter_key) >= 12 and signal_key.startswith(chapter_key):
            score = 0.98
        elif signal_key in chapter_key or chapter_key in signal_key:
            score = 0.93
        else:
            score = max(
                SequenceMatcher(None, signal_key, chapter_key).ratio(),
                SequenceMatcher(None, normalized_lower, chapter_title.lower()).ratio(),
            )
        if score > best_score:
            best_score = score
            best_row = row
    if best_row is None or best_score < 0.78:
        return None
    return (
        str(best_row["chapter_id"]),
        str(best_row["chapter_title"]),
        float(best_score),
    )


def _find_chapter_by_number(number_value: int, chapters: list[dict[str, Any]]) -> dict[str, Any] | None:
    if int(number_value or 0) <= 0:
        return None
    for row in chapters:
        if int(row.get("number_value") or 0) == int(number_value):
            return row
    for row in chapters:
        if int(row.get("numbered_order_index") or 0) == int(number_value):
            return row
    return None


def _match_toc_subentry_to_chapter(
    subentry: Mapping[str, Any],
    chapters: list[dict[str, Any]],
) -> tuple[str, str, float] | None:
    title = normalize_title(str(subentry.get("title") or ""))
    match_mode = str(subentry.get("match_mode") or "unknown").strip().lower()
    if not title:
        return None

    if match_mode == "named":
        named_match = _NAMED_NOTES_TARGET_RE.match(title)
        target_title = normalize_title(str(named_match.group(1) or "")) if named_match else ""
        number_value, remainder = _extract_number_info(target_title)
        if number_value > 0:
            matched_row = _find_chapter_by_number(number_value, chapters)
            if matched_row is None:
                return None
            if remainder:
                title_match = _match_signal_to_chapter(remainder, chapters)
                if title_match is not None and title_match[0] == str(matched_row.get("chapter_id") or ""):
                    return title_match[0], title_match[1], 1.22
            return str(matched_row["chapter_id"]), str(matched_row["chapter_title"]), 1.1
        matched = _match_signal_to_chapter(target_title, chapters)
        if matched is None:
            return None
        return matched[0], matched[1], 1.18

    if match_mode == "numbered":
        number_value, remainder = _extract_number_info(title)
        if remainder:
            matched = _match_signal_to_chapter(remainder, chapters)
            if matched is not None:
                matched_row = next(
                    (row for row in chapters if str(row.get("chapter_id") or "") == matched[0]),
                    None,
                )
                if matched_row is not None:
                    row_number = int(matched_row.get("number_value") or 0)
                    if number_value <= 0 or row_number in {0, number_value}:
                        return matched[0], matched[1], 1.2
        matched_row = _find_chapter_by_number(number_value, chapters)
        if matched_row is None:
            return None
        return str(matched_row["chapter_id"]), str(matched_row["chapter_title"]), 1.05

    if match_mode == "chapter_title":
        matched = _match_signal_to_chapter(title, chapters)
        if matched is None:
            return None
        return matched[0], matched[1], 1.08

    if match_mode == "unknown":
        matched = _match_signal_to_chapter(title, chapters)
        if matched is None:
            return None
        return matched[0], matched[1], 0.9

    matched = _match_signal_to_chapter(title, chapters)
    if matched is None:
        return None
    return matched[0], matched[1], 1.0


def _heading_candidate_style_bonus(candidate: HeadingCandidate) -> float:
    bonus = 0.0
    if candidate.top_band:
        bonus += 0.08
    if candidate.heading_level_hint == 1:
        bonus += 0.08
    elif candidate.heading_level_hint >= 2:
        bonus += 0.04
    if candidate.font_weight_hint == "heavy":
        bonus += 0.08
    elif candidate.font_weight_hint == "bold":
        bonus += 0.05
    if candidate.align_hint == "center":
        bonus += 0.05
    if candidate.font_height is not None:
        if float(candidate.font_height) >= 24.0:
            bonus += 0.04
        elif float(candidate.font_height) >= 18.0:
            bonus += 0.02
    if candidate.source == "pdf_font_band":
        bonus += 0.04
    return min(bonus, 0.28)


def _yield_page_signal_candidates(
    page_no: int,
    *,
    page: Mapping[str, Any] | None,
    heading_candidates_by_page: Mapping[int, list[HeadingCandidate]],
) -> list[tuple[str, str, float]]:
    page_payload = dict(page or {})
    note_scan = dict(page_payload.get("_note_scan") or {})
    yielded: list[tuple[str, str, float]] = []
    seen: set[tuple[str, str]] = set()

    def _push(title: str, source: str, bonus: float) -> None:
        normalized = normalize_title(title)
        if not normalized or _is_generic_notes_title(normalized):
            return
        dedupe_key = (source, normalized.lower())
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        yielded.append((normalized, source, bonus))

    for item in note_scan.get("items") or []:
        if str(item.get("kind") or "").strip().lower() != "endnote":
            continue
        _push(str(item.get("section_title") or ""), "note_section_title", 0.38)
    for hint in note_scan.get("section_hints") or []:
        _push(str(hint or ""), "note_section_hint", 0.30)
    for heading in extract_page_headings(page_payload):
        _push(str(heading or ""), "page_heading", 0.26)
    for candidate in heading_candidates_by_page.get(int(page_no), []):
        if candidate.suppressed_as_chapter:
            continue
        if candidate.reject_reason and candidate.reject_reason not in {"", "section_candidate"}:
            continue
        _push(
            candidate.text,
            "heading_candidate",
            0.22 + _heading_candidate_style_bonus(candidate),
        )
    return yielded


def _heading_candidates_by_page(phase1: Phase1Structure) -> dict[int, list[HeadingCandidate]]:
    mapped: dict[int, list[HeadingCandidate]] = {}
    for candidate in phase1.heading_candidates:
        page_no = int(candidate.page_no or 0)
        if page_no <= 0:
            continue
        mapped.setdefault(page_no, []).append(candidate)
    for page_no in list(mapped.keys()):
        mapped[page_no] = sorted(
            mapped[page_no],
            key=lambda item: (
                item.top_band is False,
                -(item.heading_level_hint or 0),
                -(1 if item.font_weight_hint == "heavy" else 0),
                -(1 if item.font_weight_hint == "bold" else 0),
                -(item.confidence or 0.0),
            ),
        )
    return mapped


def _toc_subentries_for_page(
    page_no: int,
    *,
    endnote_explorer_hints: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    hints = dict(endnote_explorer_hints or {})
    endnotes_summary = dict(hints.get("endnotes_summary") or {})
    if not bool(endnotes_summary.get("present")):
        return []
    container_start_page_hint = int(hints.get("container_start_page_hint") or 0)
    if container_start_page_hint > 0 and int(page_no) < container_start_page_hint:
        return []
    subentries = [
        dict(row)
        for row in list(hints.get("toc_subentries") or [])
        if int(row.get("printed_page") or 0) > 0
    ]
    if not subentries:
        return []
    subentries.sort(key=lambda row: (int(row.get("printed_page") or 0), int(row.get("visual_order") or 0)))
    active_index = -1
    for index, row in enumerate(subentries):
        if int(row.get("printed_page") or 0) <= int(page_no):
            active_index = index
        else:
            break
    if active_index < 0:
        return []
    active_printed_page = int(subentries[active_index].get("printed_page") or 0)
    return [row for row in subentries if int(row.get("printed_page") or 0) == active_printed_page]


def _toc_page_signal_candidates(
    page_no: int,
    *,
    chapters: list[dict[str, Any]],
    endnote_explorer_hints: Mapping[str, Any] | None,
) -> list[_PageChapterSignal]:
    ranked: list[_PageChapterSignal] = []
    for subentry in _toc_subentries_for_page(int(page_no), endnote_explorer_hints=endnote_explorer_hints):
        matched = _match_toc_subentry_to_chapter(subentry, chapters)
        if matched is None:
            continue
        chapter_id, chapter_title, match_score = matched
        ranked.append(
            _PageChapterSignal(
                page_no=int(page_no),
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                signal_title=normalize_title(str(subentry.get("title") or "")),
                source="toc_subentry",
                score=float(match_score),
            )
        )
    return ranked


def _best_page_signal(
    page_no: int,
    *,
    page: Mapping[str, Any] | None,
    chapters: list[dict[str, Any]],
    heading_candidates_by_page: Mapping[int, list[HeadingCandidate]],
    endnote_explorer_hints: Mapping[str, Any] | None,
) -> tuple[_PageChapterSignal | None, bool]:
    toc_ranked: list[_PageChapterSignal] = list(
        _toc_page_signal_candidates(
            int(page_no),
            chapters=chapters,
            endnote_explorer_hints=endnote_explorer_hints,
        )
    )
    ranked: list[_PageChapterSignal] = list(toc_ranked)
    page_ranked: list[_PageChapterSignal] = []
    for signal_title, source, bonus in _yield_page_signal_candidates(
        int(page_no),
        page=page,
        heading_candidates_by_page=heading_candidates_by_page,
    ):
        matched = _match_signal_to_chapter(signal_title, chapters)
        if matched is None:
            continue
        chapter_id, chapter_title, match_score = matched
        page_ranked.append(
            _PageChapterSignal(
                page_no=int(page_no),
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                signal_title=signal_title,
                source=source,
                score=float(match_score + bonus),
            )
        )
    ranked.extend(page_ranked)
    ranked.sort(key=lambda item: (-item.score, item.chapter_id, item.signal_title))
    if not ranked or ranked[0].score < 0.98:
        return None, False
    toc_best = sorted(toc_ranked, key=lambda item: (-item.score, item.chapter_id, item.signal_title))[0] if toc_ranked else None
    page_best = sorted(page_ranked, key=lambda item: (-item.score, item.chapter_id, item.signal_title))[0] if page_ranked else None
    if (
        toc_best is not None
        and page_best is not None
        and toc_best.chapter_id != page_best.chapter_id
        and toc_best.score >= 1.0
        and page_best.score >= 1.0
    ):
        return None, True
    if len(ranked) >= 2 and ranked[1].chapter_id != ranked[0].chapter_id and ranked[1].score >= ranked[0].score - 0.08:
        return None, True
    return ranked[0], False


def _signal_region_source(signal: _PageChapterSignal | None, default_source: str) -> str:
    if signal is None:
        return str(default_source or "heading_scan")
    if signal.source == "toc_subentry":
        return "explorer_toc_match"
    return "explorer_signal_match"


def explore_endnote_chapter_regions(
    regions: list[NoteRegionRecord],
    *,
    phase1: Phase1Structure,
    page_by_no: Mapping[int, Mapping[str, Any]],
    endnote_explorer_hints: Mapping[str, Any] | None = None,
) -> tuple[list[NoteRegionRecord], dict[str, Any]]:
    chapters = _chapter_rows(phase1)
    heading_candidates_by_page = _heading_candidates_by_page(phase1)
    rebuilt: list[NoteRegionRecord] = []
    split_count = 0
    rebind_count = 0
    page_signal_count = 0
    toc_match_count = 0
    ambiguous_page_count = 0
    signal_titles: list[str] = []
    toc_titles: list[str] = []

    for region in regions:
        if region.note_kind != "endnote" or region.scope != "book" or not region.pages:
            rebuilt.append(region)
            continue

        page_signals: dict[int, _PageChapterSignal] = {}
        ambiguous_pages: set[int] = set()
        for page_no in region.pages:
            signal, ambiguous = _best_page_signal(
                int(page_no),
                page=page_by_no.get(int(page_no)),
                chapters=chapters,
                heading_candidates_by_page=heading_candidates_by_page,
                endnote_explorer_hints=endnote_explorer_hints,
            )
            if ambiguous:
                ambiguous_pages.add(int(page_no))
                ambiguous_page_count += 1
            if signal is None:
                continue
            page_signals[int(page_no)] = signal
            if signal.source == "toc_subentry":
                toc_match_count += 1
                if signal.signal_title not in toc_titles:
                    toc_titles.append(signal.signal_title)
            else:
                page_signal_count += 1
                if signal.signal_title not in signal_titles:
                    signal_titles.append(signal.signal_title)

        if ambiguous_pages:
            distinct_chapters = {str(signal.chapter_id or "").strip() for signal in page_signals.values() if str(signal.chapter_id or "").strip()}
            if len(distinct_chapters) == 1 and distinct_chapters:
                best_signal = sorted(page_signals.values(), key=lambda item: (-item.score, item.chapter_id))[0]
                rebound_source = _signal_region_source(best_signal, region.source)
                if best_signal.chapter_id and best_signal.chapter_id != str(region.chapter_id or "").strip():
                    rebind_count += 1
                rebuilt.append(
                    replace(
                        region,
                        chapter_id=best_signal.chapter_id,
                        heading_text=best_signal.signal_title or region.heading_text,
                        source=rebound_source,
                        review_required=True,
                    )
                )
            else:
                rebuilt.append(replace(region, review_required=True))
            continue

        if not page_signals:
            rebuilt.append(region)
            continue

        segments: list[tuple[str, str, str, list[int]]] = []
        segment_pages: list[int] = []
        segment_chapter_id = str(region.chapter_id or "").strip()
        segment_heading_text = str(region.heading_text or "").strip()
        segment_source = str(region.source or "heading_scan")
        for page_no in region.pages:
            signal = page_signals.get(int(page_no))
            signal_source = _signal_region_source(signal, segment_source)
            if signal is not None and segment_pages and signal.chapter_id != segment_chapter_id:
                segments.append((segment_chapter_id, segment_heading_text, segment_source, list(segment_pages)))
                segment_pages = []
                segment_chapter_id = signal.chapter_id
                segment_heading_text = signal.signal_title
                segment_source = signal_source
            elif signal is not None and not segment_pages:
                segment_chapter_id = signal.chapter_id
                segment_heading_text = signal.signal_title
                segment_source = signal_source
            elif signal is not None and signal.chapter_id == segment_chapter_id:
                if signal_source == "explorer_toc_match":
                    segment_source = signal_source
                if not segment_heading_text:
                    segment_heading_text = signal.signal_title
            segment_pages.append(int(page_no))
        if segment_pages:
            segments.append((segment_chapter_id, segment_heading_text, segment_source, list(segment_pages)))

        if len(segments) == 1:
            chapter_id, heading_text, source, pages = segments[0]
            if chapter_id != str(region.chapter_id or "").strip():
                if chapter_id:
                    rebind_count += 1
                rebuilt.append(
                    replace(
                        region,
                        chapter_id=chapter_id,
                        heading_text=heading_text or region.heading_text,
                        source=source,
                    )
                )
                continue
            if source != str(region.source or "") or (heading_text and heading_text != str(region.heading_text or "")):
                rebuilt.append(
                    replace(
                        region,
                        heading_text=heading_text or region.heading_text,
                        source=source,
                    )
                )
                continue
            rebuilt.append(region)
            continue

        split_count += len(segments) - 1
        for index, (chapter_id, heading_text, source, pages) in enumerate(segments, start=1):
            if chapter_id and chapter_id != str(region.chapter_id or "").strip():
                rebind_count += 1
            rebuilt.append(
                replace(
                    region,
                    region_id=f"{region.region_id}-explore-{index:02d}",
                    chapter_id=chapter_id,
                    page_start=pages[0],
                    page_end=pages[-1],
                    pages=pages,
                    heading_text=heading_text or region.heading_text,
                    source=source,
                )
            )

    summary = {
        "split_count": int(split_count),
        "rebind_count": int(rebind_count),
        "page_signal_count": int(page_signal_count),
        "toc_match_count": int(toc_match_count),
        "ambiguous_page_count": int(ambiguous_page_count),
        "signal_titles_preview": signal_titles[:6],
        "toc_titles_preview": toc_titles[:6],
    }
    return rebuilt, summary

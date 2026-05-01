"""FNM_RE 第一阶段：章内标题。"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from FNM_RE.models import ChapterRecord, HeadingCandidate, PagePartitionRecord, SectionHeadRecord
from FNM_RE.shared.chapters import chapter_id_for_page, chapter_id_for_page as _chapter_id_for_page
from FNM_RE.shared.title import chapter_title_match_key, normalize_title


def _chapter_page_bounds(chapters: list[ChapterRecord]) -> list[ChapterRecord]:
    return sorted(chapters, key=lambda item: (item.start_page, item.chapter_id))


def _chapter_id_for_page(chapters: list[ChapterRecord], page_no: int) -> str:
    return chapter_id_for_page(chapters, page_no)


_SECTION_TITLE_MIN_WORDS = 3
_SECTION_TITLE_MIN_CHARS = 18
_CHAPTER_LEADING_NUMBER_RE = re.compile(r"^\s*(?:\d+|[ivxlcdm]+)[\.\):\-–—]?\s+", re.IGNORECASE)
_SECTION_TITLE_NOISE_RE = re.compile(
    r"^\s*(?:to the|and|or|the|a|an|in the|of the|for the|with the|by the|at the|on the|from the|"
    r"is a|are|was|were|has|have|had|been|being|"
    r"it is|that is|this is|there are|there is|"
    r"\.\s*\)|\]\s*$|"
    r"\b(?:tices|nomics|ology|ophy|istry|ments|ances|ities|tions|sions|ments)\s*$"
    r")\s*$",
    re.IGNORECASE,
)
_SECTION_TITLE_OPENING_QUOTES = "\"'“”‘’«»‹›「」『』"
_SUPPRESSED_SECTION_HARD_REJECT_REASONS = {
    "invalid_title",
    "partition_conflict",
    "note_partition",
    "note_heading",
    "non_body_family",
}


def _chapter_title_match_keys(value: str) -> set[str]:
    title = normalize_title(value)
    keys = {chapter_title_match_key(title)}
    stripped = _CHAPTER_LEADING_NUMBER_RE.sub("", title).strip()
    if stripped and stripped != title:
        keys.add(chapter_title_match_key(stripped))
    return {key for key in keys if key}


def _chapter_title_keys(chapters: list[ChapterRecord]) -> dict[str, set[str]]:
    return {chapter.chapter_id: _chapter_title_match_keys(chapter.title) for chapter in chapters}


def _section_title_starts_like_heading(title: str) -> bool:
    stripped = normalize_title(title).lstrip(_SECTION_TITLE_OPENING_QUOTES)
    first_alpha = next((char for char in stripped if char.isalpha()), "")
    return not first_alpha or first_alpha.isupper()


def _section_title_text_is_plausible(title: str) -> bool:
    normalized = normalize_title(title)
    if not normalized:
        return False
    words = [w for w in normalized.split() if w]
    if _SECTION_TITLE_NOISE_RE.match(normalized):
        return False
    if len(words) == 1 and len(normalized) < 12:
        return False
    if not _section_title_starts_like_heading(normalized):
        return False
    if len(words) < _SECTION_TITLE_MIN_WORDS and len(normalized) < _SECTION_TITLE_MIN_CHARS:
        return _section_title_starts_like_heading(normalized)
    return True


def _candidate_can_become_section(candidate: HeadingCandidate) -> bool:
    title = normalize_title(candidate.normalized_text or candidate.text)
    if not _section_title_text_is_plausible(title):
        return False
    if candidate.suppressed_as_chapter:
        if str(candidate.reject_reason or "") in _SUPPRESSED_SECTION_HARD_REJECT_REASONS:
            return False
        return True
    family = str(candidate.heading_family_guess or "").strip().lower()
    if family != "section":
        return False
    return _section_title_text_is_plausible(title)


def build_section_heads(
    chapters: list[ChapterRecord],
    heading_candidates: list[HeadingCandidate],
    page_partitions: list[PagePartitionRecord],
    *,
    fallback_sections: list[dict] | None = None,
) -> tuple[list[SectionHeadRecord], dict[str, Any]]:
    ordered_chapters = _chapter_page_bounds(chapters)
    chapter_title_key_map = _chapter_title_keys(ordered_chapters)
    page_role_map = {int(item.page_no): str(item.page_role) for item in page_partitions}

    merged_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    for row in fallback_sections or []:
        title = normalize_title(row.get("title") or row.get("text") or "")
        page_no = int(row.get("page_no") or row.get("start_page") or 0)
        chapter_id = str(row.get("chapter_id") or "").strip() or _chapter_id_for_page(ordered_chapters, page_no)
        if not title or page_no <= 0 or not chapter_id:
            continue
        if not _section_title_text_is_plausible(title):
            continue
        if chapter_title_match_key(title) in chapter_title_key_map.get(chapter_id, set()):
            continue
        key = (chapter_id, page_no, chapter_title_match_key(title))
        if key in seen:
            continue
        seen.add(key)
        merged_rows.append(
            {
                "chapter_id": chapter_id,
                "title": title,
                "page_no": page_no,
                "level": max(1, int(row.get("level") or 2)),
                "source": str(row.get("source") or "fallback"),
            }
        )

    if fallback_sections is None:
        for candidate in heading_candidates:
            if not _candidate_can_become_section(candidate):
                continue
            page_no = int(candidate.page_no)
            if page_no <= 0 or page_role_map.get(page_no) not in {"body", "front_matter"}:
                continue
            chapter_id = _chapter_id_for_page(ordered_chapters, page_no)
            if not chapter_id:
                continue
            title = normalize_title(candidate.normalized_text or candidate.text)
            if not title:
                continue
            if chapter_title_match_key(title) in chapter_title_key_map.get(chapter_id, set()):
                continue
            key = (chapter_id, page_no, chapter_title_match_key(title))
            if key in seen:
                continue
            seen.add(key)
            merged_rows.append(
                {
                    "chapter_id": chapter_id,
                    "title": title,
                    "page_no": page_no,
                    "level": 2,
                    "source": str(candidate.source or "candidate"),
                }
            )

    merged_rows.sort(
        key=lambda item: (
            next(
                (
                    chapter.start_page
                    for chapter in ordered_chapters
                    if chapter.chapter_id == str(item.get("chapter_id") or "")
                ),
                10**9,
            ),
            int(item.get("page_no") or 0),
            str(item.get("title") or ""),
        )
    )

    section_heads: list[SectionHeadRecord] = []
    for index, row in enumerate(merged_rows, start=1):
        section_heads.append(
            SectionHeadRecord(
                section_head_id=f"section-head-{index:04d}",
                chapter_id=str(row.get("chapter_id") or ""),
                title=str(row.get("title") or ""),
                page_no=int(row.get("page_no") or 0),
                level=max(1, int(row.get("level") or 2)),
                source=str(row.get("source") or ""),
            )
        )

    suppressed_reason_counts = Counter(
        str(candidate.reject_reason or "")
        for candidate in heading_candidates
        if candidate.suppressed_as_chapter and str(candidate.reject_reason or "")
    )
    heading_review_summary = {
        "chapter_candidate_count": sum(
            1
            for candidate in heading_candidates
            if str(candidate.heading_family_guess or "").strip().lower() in {"chapter", "front_matter", "section"}
        ),
        "suppressed_candidate_count": sum(1 for candidate in heading_candidates if candidate.suppressed_as_chapter),
        "suppressed_reason_counts": dict(suppressed_reason_counts),
        "partition_conflict_count": int(suppressed_reason_counts.get("partition_conflict", 0)),
    }
    return section_heads, heading_review_summary

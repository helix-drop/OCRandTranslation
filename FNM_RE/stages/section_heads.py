"""FNM_RE 第一阶段：章内标题。"""

from __future__ import annotations

from collections import Counter
from typing import Any

from FNM_RE.models import ChapterRecord, HeadingCandidate, PagePartitionRecord, SectionHeadRecord
from FNM_RE.shared.chapters import chapter_id_for_page, chapter_id_for_page as _chapter_id_for_page
from FNM_RE.shared.title import chapter_title_match_key, normalize_title


def _chapter_page_bounds(chapters: list[ChapterRecord]) -> list[ChapterRecord]:
    return sorted(chapters, key=lambda item: (item.start_page, item.chapter_id))


def _chapter_id_for_page(chapters: list[ChapterRecord], page_no: int) -> str:
    return chapter_id_for_page(chapters, page_no)


def _chapter_title_keys(chapters: list[ChapterRecord]) -> dict[str, str]:
    return {chapter.chapter_id: chapter_title_match_key(chapter.title) for chapter in chapters}


def _candidate_can_become_section(candidate: HeadingCandidate) -> bool:
    if candidate.suppressed_as_chapter:
        return True
    family = str(candidate.heading_family_guess or "").strip().lower()
    return family == "section"


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
        if chapter_title_match_key(title) == chapter_title_key_map.get(chapter_id, ""):
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
        if chapter_title_match_key(title) == chapter_title_key_map.get(chapter_id, ""):
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


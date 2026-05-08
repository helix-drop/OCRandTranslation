"""note_links 共享工具函数：anchor 搜索、候选合并、link 构造。"""

from __future__ import annotations

import re
from typing import Any

from FNM_RE.models import BodyAnchorRecord, NoteLinkRecord
from FNM_RE.shared.notes import normalize_note_marker


def _is_fallback_chapter_id(chapter_id: str) -> bool:
    return str(chapter_id or "").startswith("ch-fallback-")


def _is_toc_chapter_id(chapter_id: str) -> bool:
    return str(chapter_id or "").startswith("toc-ch-")


def _within_footnote_window(anchor_page: int, note_page: int, *, max_distance: int = 1) -> bool:
    return abs(int(anchor_page) - int(note_page)) <= max_distance


def _nearest_unique_candidate(candidates: list[BodyAnchorRecord], *, target_page: int) -> BodyAnchorRecord | None:
    if len(candidates) <= 1:
        return candidates[0] if candidates else None
    min_distance = min(abs(int(row.page_no) - int(target_page or 0)) for row in candidates)
    nearest = [row for row in candidates if abs(int(row.page_no) - int(target_page or 0)) == min_distance]
    if len(nearest) != 1:
        return None
    return nearest[0]


def _collapse_redundant_candidates(candidates: list[BodyAnchorRecord]) -> list[BodyAnchorRecord]:
    if len(candidates) <= 1:
        return candidates

    def _normalized_text(text: str) -> str:
        candidate = re.sub(r"<[^>]+>", " ", str(text or ""))
        candidate = candidate.replace("&nbsp;", " ")
        return " ".join(candidate.split()).strip()

    def _preference_key(row: BodyAnchorRecord) -> tuple[int, int, int, int, int]:
        normalized = _normalized_text(row.source_text)
        source = str(row.source or "")
        return (
            len(normalized), len(str(row.source_text or "")),
            0 if source.startswith("ocr_block") else 1,
            int(row.paragraph_index), int(row.char_start),
        )

    kept: list[BodyAnchorRecord] = []
    for candidate in candidates:
        candidate_text = _normalized_text(candidate.source_text)
        redundant = False
        for other in candidates:
            if other.anchor_id == candidate.anchor_id:
                continue
            if int(other.page_no) != int(candidate.page_no):
                continue
            other_text = _normalized_text(other.source_text)
            if not candidate_text or not other_text:
                continue
            if other_text == candidate_text and _preference_key(other) < _preference_key(candidate):
                redundant = True
                break
            if len(other_text) >= len(candidate_text):
                continue
            if other_text in candidate_text:
                redundant = True
                break
        if not redundant:
            kept.append(candidate)
    return kept or candidates


def link_candidate_anchors(
    anchors: list[BodyAnchorRecord],
    *,
    chapter_id: str,
    marker: str,
    expected_kinds: set[str],
    used_anchor_ids: set[str],
    page_no: int | None = None,
    footnote_window: bool = False,
    include_synthetic: bool = False,
    allow_cross_chapter: bool = False,
) -> list[BodyAnchorRecord]:
    candidates: list[BodyAnchorRecord] = []
    normalized_marker = normalize_note_marker(marker)
    for anchor in anchors:
        if not allow_cross_chapter and str(anchor.chapter_id or "") != str(chapter_id or ""):
            continue
        if not include_synthetic and bool(anchor.synthetic):
            continue
        if anchor.anchor_id in used_anchor_ids:
            continue
        if normalize_note_marker(anchor.normalized_marker) != normalized_marker:
            continue
        if str(anchor.anchor_kind or "") not in expected_kinds:
            continue
        if footnote_window and page_no is not None and not _within_footnote_window(anchor.page_no, page_no):
            continue
        candidates.append(anchor)
    candidates = _collapse_redundant_candidates(candidates)
    candidates.sort(key=lambda row: (
        abs(int(row.page_no) - int(page_no or row.page_no)),
        int(row.page_no), int(row.paragraph_index), int(row.char_start),
    ))
    return candidates


def link_new_link(
    *,
    serial: int,
    chapter_id: str,
    region_id: str,
    note_item_id: str,
    anchor_id: str,
    status: str,
    resolver: str,
    confidence: float,
    note_kind: str,
    marker: str,
    page_no_start: int,
    page_no_end: int,
) -> NoteLinkRecord:
    return NoteLinkRecord(
        link_id=f"link-{serial:05d}",
        chapter_id=str(chapter_id or ""),
        region_id=str(region_id or ""),
        note_item_id=str(note_item_id or ""),
        anchor_id=str(anchor_id or ""),
        status=status,  # type: ignore[arg-type]
        resolver=resolver,  # type: ignore[arg-type]
        confidence=float(confidence),
        note_kind=note_kind,  # type: ignore[arg-type]
        marker=normalize_note_marker(marker),
        page_no_start=int(page_no_start or 0),
        page_no_end=int(page_no_end or 0),
    )

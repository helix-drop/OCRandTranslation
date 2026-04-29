"""FNM_RE 第二阶段：note_regions。"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Mapping

from document.note_detection import annotate_pages_with_note_scans

from FNM_RE.models import NoteRegionRecord, Phase1Structure
from FNM_RE.shared.notes import _split_contiguous_ranges, first_notes_heading, first_source_marker, scan_items_by_kind
from FNM_RE.shared.chapters import chapter_id_for_page as _shared_chapter_id_for_page, nearest_prior_chapter as _shared_nearest_prior_chapter
from FNM_RE.stages.endnote_chapter_explorer import explore_endnote_chapter_regions
from FNM_RE.shared.text import extract_page_headings
from FNM_RE.shared.title import chapter_title_match_key, normalize_title

_ILLUSTRATION_LIST_RE = re.compile(
    r"^\s*(?:list(?:e)?\s+(?:of\s+)?(?:illustrations?|figures?|plates?)|liste\s+des\s+illustrations?)\b",
    re.IGNORECASE,
)
_ILLUSTRATION_CONTENT_RE = re.compile(
    r"(?:©|cm\b|mus[ée]e|biblioth[eè]que|gravure|huile|lithograph|dessin|eau-forte|collection)",
    re.IGNORECASE,
)


def _chapter_id_for_page(phase1: Phase1Structure, page_no: int) -> str:
    chapters = getattr(phase1, "chapters", phase1)
    return _shared_chapter_id_for_page(chapters, page_no)


def _nearest_prior_chapter(phase1: Phase1Structure, page_no: int) -> str:
    return _shared_nearest_prior_chapter(phase1.chapters, page_no)


def _page_payload_by_no(pages: list[dict]) -> dict[int, dict]:
    annotated = annotate_pages_with_note_scans(list(pages or []))
    payload: dict[int, dict] = {}
    for page in annotated:
        try:
            page_no = int(page.get("bookPage") or 0)
        except (TypeError, ValueError):
            continue
        if page_no > 0:
            payload[page_no] = dict(page)
    return payload


def _build_footnote_band_regions(
    phase1: Phase1Structure,
    page_by_no: Mapping[int, Mapping[str, Any]],
) -> tuple[list[NoteRegionRecord], set[str]]:
    regions: list[NoteRegionRecord] = []
    chapters_with_footnote_band: set[str] = set()
    for chapter in phase1.chapters:
        footnote_pages = [
            int(page_no)
            for page_no in chapter.pages
            if int(page_no) > 0 and scan_items_by_kind(page_by_no.get(int(page_no)), kind="footnote")
        ]
        for run_index, run_pages in enumerate(_split_contiguous_ranges(footnote_pages), start=1):
            start_page = run_pages[0]
            end_page = run_pages[-1]
            chapters_with_footnote_band.add(chapter.chapter_id)
            regions.append(
                NoteRegionRecord(
                    region_id=f"{chapter.chapter_id}-footband-{run_index:02d}",
                    chapter_id=chapter.chapter_id,
                    page_start=start_page,
                    page_end=end_page,
                    pages=run_pages,
                    note_kind="footnote",
                    scope="chapter",
                    source="footnote_band",
                    heading_text="",
                    start_reason="footnote_items",
                    end_reason="contiguous_end",
                    region_marker_alignment_ok=True,
                    region_start_first_source_marker=first_source_marker(
                        page_by_no.get(start_page),
                        kind="footnote",
                    ),
                    region_first_note_item_marker="",
                    review_required=False,
                )
            )
    return regions, chapters_with_footnote_band


def _looks_like_illustration_list_page(
    page_no: int,
    *,
    page_by_no: Mapping[int, Mapping[str, Any]],
) -> bool:
    page = page_by_no.get(page_no)
    if page is None:
        return False
    lines = [str(line or "").strip() for line in str(page.get("markdown") or "").splitlines() if str(line or "").strip()]
    if not lines:
        return False
    first_line = re.sub(r"^\s{0,3}#{1,6}\s*", "", lines[0]).strip()
    if _ILLUSTRATION_LIST_RE.match(first_line):
        return True

    prev_page = page_by_no.get(page_no - 1)
    if prev_page is None:
        return False
    prev_lines = [str(line or "").strip() for line in str(prev_page.get("markdown") or "").splitlines() if str(line or "").strip()]
    if not prev_lines:
        return False
    prev_first_line = re.sub(r"^\s{0,3}#{1,6}\s*", "", prev_lines[0]).strip()
    if not _ILLUSTRATION_LIST_RE.match(prev_first_line):
        return False
    numbered_prefix = 0
    illustration_hint_count = 0
    for line in lines[:8]:
        stripped = re.sub(r"^\s{0,3}#{1,6}\s*", "", line).strip()
        if re.match(r"^\d{1,3}[\.)]\s+", stripped):
            numbered_prefix += 1
        if _ILLUSTRATION_CONTENT_RE.search(stripped):
            illustration_hint_count += 1
    return numbered_prefix >= 2 and illustration_hint_count >= 2


def _is_endnote_candidate_page(
    page_no: int,
    *,
    page_role_by_no: Mapping[int, str],
    page_by_no: Mapping[int, Mapping[str, Any]],
) -> bool:
    page = page_by_no.get(page_no)
    if page is None:
        return False
    if _looks_like_illustration_list_page(page_no, page_by_no=page_by_no):
        return False
    page_role = str(page_role_by_no.get(page_no) or "")
    if page_role == "other":
        return bool(first_notes_heading(page))
    if page_role == "note":
        return True
    if scan_items_by_kind(page, kind="endnote"):
        return True
    return bool(first_notes_heading(page))


def _endnote_scope_for_page(
    page_no: int,
    *,
    phase1: Phase1Structure,
    last_chapter_end_page: int,
) -> tuple[str, str]:
    chapter_id = _chapter_id_for_page(phase1, page_no)
    if page_no > int(last_chapter_end_page):
        return "book", ""
    if chapter_id:
        return "chapter", chapter_id
    return "book", ""


def _start_reason_for_page(
    page_no: int,
    *,
    page_role_by_no: Mapping[int, str],
    page_by_no: Mapping[int, Mapping[str, Any]],
) -> str:
    page = page_by_no.get(page_no) or {}
    if first_notes_heading(page):
        return "notes_heading"
    if scan_items_by_kind(page, kind="endnote"):
        return "endnote_items"
    if str(page_role_by_no.get(page_no) or "") == "note":
        return "note_partition"
    return "candidate_page"


def _build_endnote_regions_raw(
    phase1: Phase1Structure,
    *,
    page_role_by_no: Mapping[int, str],
    page_by_no: Mapping[int, Mapping[str, Any]],
    chapters_with_footnote_band: set[str],
) -> list[NoteRegionRecord]:
    if not phase1.pages:
        return []
    sorted_page_nos = sorted(int(row.page_no) for row in phase1.pages if int(row.page_no) > 0)
    if not sorted_page_nos:
        return []
    last_chapter_end_page = max((int(chapter.end_page) for chapter in phase1.chapters), default=0)

    regions: list[NoteRegionRecord] = []
    current_pages: list[int] = []
    current_scope = ""
    current_chapter_id = ""
    current_heading_text = ""
    current_start_reason = ""
    for page_no in sorted_page_nos:
        if not _is_endnote_candidate_page(
            page_no,
            page_role_by_no=page_role_by_no,
            page_by_no=page_by_no,
        ):
            if current_pages:
                start_page = current_pages[0]
                end_page = current_pages[-1]
                regions.append(
                    NoteRegionRecord(
                        region_id=f"region-endnote-{len(regions) + 1:04d}",
                        chapter_id=current_chapter_id,
                        page_start=start_page,
                        page_end=end_page,
                        pages=list(current_pages),
                        note_kind="endnote",
                        scope=current_scope if current_scope in {"chapter", "book"} else "chapter",
                        source="heading_scan",
                        heading_text=current_heading_text,
                        start_reason=current_start_reason or "candidate_page",
                        end_reason="contiguous_break",
                        region_marker_alignment_ok=True,
                        region_start_first_source_marker=first_source_marker(
                            page_by_no.get(start_page),
                            kind="endnote",
                        ),
                        region_first_note_item_marker="",
                        review_required=False,
                    )
                )
                current_pages = []
                current_scope = ""
                current_chapter_id = ""
                current_heading_text = ""
                current_start_reason = ""
            continue

        scope, chapter_id = _endnote_scope_for_page(
            page_no,
            phase1=phase1,
            last_chapter_end_page=last_chapter_end_page,
        )
        if scope == "chapter" and chapter_id in chapters_with_footnote_band:
            continue
        heading_text = first_notes_heading(page_by_no.get(page_no))
        start_reason = _start_reason_for_page(
            page_no,
            page_role_by_no=page_role_by_no,
            page_by_no=page_by_no,
        )

        if not current_pages:
            current_pages = [page_no]
            current_scope = scope
            current_chapter_id = chapter_id
            current_heading_text = heading_text
            current_start_reason = start_reason
            continue

        expected_next_page = current_pages[-1] + 1
        same_group = (
            page_no == expected_next_page
            and scope == current_scope
            and (scope == "book" or chapter_id == current_chapter_id)
        )
        if same_group:
            current_pages.append(page_no)
            if not current_heading_text and heading_text:
                current_heading_text = heading_text
            continue

        start_page = current_pages[0]
        end_page = current_pages[-1]
        regions.append(
            NoteRegionRecord(
                region_id=f"region-endnote-{len(regions) + 1:04d}",
                chapter_id=current_chapter_id,
                page_start=start_page,
                page_end=end_page,
                pages=list(current_pages),
                note_kind="endnote",
                scope=current_scope if current_scope in {"chapter", "book"} else "chapter",
                source="heading_scan",
                heading_text=current_heading_text,
                start_reason=current_start_reason or "candidate_page",
                end_reason="contiguous_break",
                region_marker_alignment_ok=True,
                region_start_first_source_marker=first_source_marker(
                    page_by_no.get(start_page),
                    kind="endnote",
                ),
                region_first_note_item_marker="",
                review_required=False,
            )
        )
        current_pages = [page_no]
        current_scope = scope
        current_chapter_id = chapter_id
        current_heading_text = heading_text
        current_start_reason = start_reason

    if current_pages:
        start_page = current_pages[0]
        end_page = current_pages[-1]
        regions.append(
            NoteRegionRecord(
                region_id=f"region-endnote-{len(regions) + 1:04d}",
                chapter_id=current_chapter_id,
                page_start=start_page,
                page_end=end_page,
                pages=list(current_pages),
                note_kind="endnote",
                scope=current_scope if current_scope in {"chapter", "book"} else "chapter",
                source="heading_scan",
                heading_text=current_heading_text,
                start_reason=current_start_reason or "candidate_page",
                end_reason="document_end",
                region_marker_alignment_ok=True,
                region_start_first_source_marker=first_source_marker(
                    page_by_no.get(start_page),
                    kind="endnote",
                ),
                region_first_note_item_marker="",
                review_required=False,
            )
        )
    return regions


def _promote_post_body_regions(
    regions: list[NoteRegionRecord],
    *,
    phase1: Phase1Structure,
) -> tuple[list[NoteRegionRecord], int]:
    last_chapter_end_page = max((int(chapter.end_page) for chapter in phase1.chapters), default=0)
    promoted = 0
    normalized: list[NoteRegionRecord] = []
    for region in regions:
        if region.note_kind != "endnote":
            normalized.append(region)
            continue
        if region.page_start > last_chapter_end_page and region.scope != "book":
            promoted += 1
            normalized.append(
                replace(
                    region,
                    scope="book",
                    chapter_id="",
                    source="continuation_merge",
                )
            )
            continue
        normalized.append(region)
    return normalized, promoted


def _merge_adjacent_endnote_regions(regions: list[NoteRegionRecord]) -> tuple[list[NoteRegionRecord], int]:
    ordered = sorted(regions, key=lambda row: (int(row.page_start), int(row.page_end), row.region_id))
    merged: list[NoteRegionRecord] = []
    merge_count = 0
    for region in ordered:
        if region.note_kind != "endnote":
            merged.append(region)
            continue
        if not merged:
            merged.append(region)
            continue
        previous = merged[-1]
        can_merge = (
            previous.note_kind == "endnote"
            and previous.scope == region.scope
            and previous.page_end + 1 >= region.page_start
            and (
                previous.scope == "book"
                or previous.chapter_id == region.chapter_id
            )
        )
        if not can_merge:
            merged.append(region)
            continue
        merged_pages = sorted({*previous.pages, *region.pages})
        merged[-1] = replace(
            previous,
            page_start=merged_pages[0],
            page_end=merged_pages[-1],
            pages=merged_pages,
            source="continuation_merge",
            end_reason=region.end_reason,
            review_required=bool(previous.review_required or region.review_required),
        )
        merge_count += 1
    return merged, merge_count


def _split_book_regions_by_heading(
    regions: list[NoteRegionRecord],
    *,
    phase1: Phase1Structure,
    page_by_no: Mapping[int, Mapping[str, Any]],
) -> tuple[list[NoteRegionRecord], int]:
    chapter_key_to_id = {
        chapter_title_match_key(chapter.title): chapter.chapter_id
        for chapter in phase1.chapters
        if chapter_title_match_key(chapter.title)
    }
    rebuilt: list[NoteRegionRecord] = []
    split_count = 0
    for region in regions:
        if region.note_kind != "endnote" or region.scope != "book" or len(region.pages) <= 1:
            rebuilt.append(region)
            continue
        chapter_match_by_page: dict[int, str] = {}
        for page_no in region.pages:
            headings = [normalize_title(text) for text in extract_page_headings(page_by_no.get(page_no))]
            for heading in headings:
                key = chapter_title_match_key(heading)
                if key and key in chapter_key_to_id:
                    chapter_match_by_page[page_no] = chapter_key_to_id[key]
                    break
        if not chapter_match_by_page:
            rebuilt.append(region)
            continue
        boundaries = [0]
        for index, page_no in enumerate(region.pages):
            if index == 0:
                continue
            if page_no in chapter_match_by_page:
                boundaries.append(index)
        boundaries.append(len(region.pages))
        if len(boundaries) <= 2:
            first_page = region.pages[0]
            bound_chapter = chapter_match_by_page.get(first_page, region.chapter_id)
            if bound_chapter and bound_chapter != region.chapter_id:
                rebuilt.append(
                    replace(
                        region,
                        chapter_id=bound_chapter,
                        source="manual_rebind",
                    )
                )
            else:
                rebuilt.append(region)
            continue
        split_count += len(boundaries) - 2
        for segment_index in range(len(boundaries) - 1):
            segment_pages = region.pages[boundaries[segment_index] : boundaries[segment_index + 1]]
            if not segment_pages:
                continue
            segment_start = segment_pages[0]
            segment_chapter = chapter_match_by_page.get(segment_start, _nearest_prior_chapter(phase1, segment_start))
            rebuilt.append(
                replace(
                    region,
                    region_id=f"{region.region_id}-split-{segment_index + 1:02d}",
                    chapter_id=segment_chapter,
                    page_start=segment_pages[0],
                    page_end=segment_pages[-1],
                    pages=segment_pages,
                    source="manual_rebind",
                )
            )
    return rebuilt, split_count


def _rebind_book_regions(
    regions: list[NoteRegionRecord],
    *,
    phase1: Phase1Structure,
) -> tuple[list[NoteRegionRecord], int]:
    chapter_ids = {chapter.chapter_id for chapter in phase1.chapters}
    normalized: list[NoteRegionRecord] = []
    rebind_count = 0
    for region in regions:
        if region.note_kind != "endnote" or region.scope != "book":
            normalized.append(region)
            continue
        chapter_id = str(region.chapter_id or "").strip()
        if chapter_id and chapter_id in chapter_ids:
            normalized.append(region)
            continue
        rebound = _nearest_prior_chapter(phase1, region.page_start)
        if not rebound:
            normalized.append(replace(region, review_required=True))
            continue
        normalized.append(
            replace(
                region,
                chapter_id=rebound,
                source="fallback_nearest_prior",
            )
        )
        rebind_count += 1
    return normalized, rebind_count


def _chapter_endnote_start_page_map(regions: list[NoteRegionRecord]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for region in regions:
        if region.note_kind != "endnote" or region.scope != "chapter":
            continue
        chapter_id = str(region.chapter_id or "").strip()
        if not chapter_id:
            continue
        start_page = int(region.page_start)
        if chapter_id not in mapping or start_page < mapping[chapter_id]:
            mapping[chapter_id] = start_page
    return mapping


def _normalize_region_ids(regions: list[NoteRegionRecord]) -> list[NoteRegionRecord]:
    ordered = sorted(
        regions,
        key=lambda row: (
            int(row.page_start),
            int(row.page_end),
            str(row.note_kind),
            str(row.scope),
            str(row.chapter_id),
        ),
    )
    normalized: list[NoteRegionRecord] = []
    for index, region in enumerate(ordered, start=1):
        note_tag = "fn" if region.note_kind == "footnote" else "en"
        scope_tag = "ch" if region.scope == "chapter" else "bk"
        chapter_tag = str(region.chapter_id or "none").replace(" ", "-")
        normalized.append(
            replace(
                region,
                region_id=f"nr-{note_tag}-{scope_tag}-{index:04d}-{chapter_tag}",
            )
        )
    return normalized


def build_note_regions(
    phase1: Phase1Structure,
    *,
    pages: list[dict],
    pdf_path: str = "",
    page_text_map: Mapping[int | str, str] | None = None,
    endnote_explorer_hints: Mapping[str, Any] | None = None,
) -> tuple[list[NoteRegionRecord], dict]:
    # phase-2 第一版不依赖 pdf/page_text_map 进行 region 识别，参数仅保持接口稳定
    _ = str(pdf_path or "")
    _ = dict(page_text_map or {})

    page_by_no = _page_payload_by_no(pages)
    page_role_by_no = {
        int(row.page_no): str(row.page_role)
        for row in phase1.pages
        if int(row.page_no) > 0
    }

    footnote_regions, chapters_with_footnote_band = _build_footnote_band_regions(phase1, page_by_no)
    endnote_regions = _build_endnote_regions_raw(
        phase1,
        page_role_by_no=page_role_by_no,
        page_by_no=page_by_no,
        chapters_with_footnote_band=chapters_with_footnote_band,
    )
    endnote_regions, merge_count = _merge_adjacent_endnote_regions(endnote_regions)
    endnote_regions, post_body_promoted_count = _promote_post_body_regions(endnote_regions, phase1=phase1)
    endnote_regions, endnote_explorer_summary = explore_endnote_chapter_regions(
        endnote_regions,
        phase1=phase1,
        page_by_no=page_by_no,
        endnote_explorer_hints=endnote_explorer_hints,
    )
    endnote_regions, fallback_rebind_count = _rebind_book_regions(endnote_regions, phase1=phase1)

    regions = _normalize_region_ids([*footnote_regions, *endnote_regions])
    chapter_endnote_start_page_map = _chapter_endnote_start_page_map(regions)
    chapter_endnote_regions = [
        region
        for region in regions
        if region.note_kind == "endnote" and region.scope == "chapter"
    ]
    chapter_endnote_region_alignment_ok = all(region.region_marker_alignment_ok for region in chapter_endnote_regions)
    manual_rebind_count = sum(
        1 for region in regions if region.note_kind == "endnote" and region.source == "manual_rebind"
    )
    bind_method_counts: dict[str, int] = {}
    for region in regions:
        if region.note_kind != "endnote":
            continue
        source = str(region.source or "").strip()
        if source in {"explorer_toc_match", "explorer_signal_match", "fallback_nearest_prior"}:
            bind_method_counts[source] = int(bind_method_counts.get(source, 0) or 0) + 1
    explorer_hints = dict(endnote_explorer_hints or {})
    toc_subentries = list(explorer_hints.get("toc_subentries") or [])
    summary = {
        "chapter_endnote_start_page_map": chapter_endnote_start_page_map,
        "chapter_endnote_region_alignment_ok": bool(chapter_endnote_region_alignment_ok),
        "book_region_count": sum(
            1 for region in regions if region.note_kind == "endnote" and region.scope == "book"
        ),
        "chapter_region_count": sum(
            1 for region in regions if region.note_kind == "endnote" and region.scope == "chapter"
        ),
        "footnote_band_chapter_count": len(chapters_with_footnote_band),
        "manual_rebind_count": int(manual_rebind_count),
        "fallback_nearest_prior_count": int(fallback_rebind_count),
        "post_body_promoted_count": int(post_body_promoted_count),
        "split_region_count": int(endnote_explorer_summary.get("split_count", 0)),
        "merge_region_count": int(merge_count),
        "endnote_explorer_split_count": int(endnote_explorer_summary.get("split_count", 0)),
        "endnote_explorer_rebind_count": int(endnote_explorer_summary.get("rebind_count", 0)),
        "endnote_explorer_page_signal_count": int(endnote_explorer_summary.get("page_signal_count", 0)),
        "endnote_explorer_toc_hint_present": bool(
            dict(explorer_hints.get("endnotes_summary") or {}).get("present")
            or explorer_hints.get("has_toc_subentries")
        ),
        "endnote_explorer_container_start_page": int(explorer_hints.get("container_start_page_hint") or 0),
        "endnote_explorer_toc_subentry_count": len(toc_subentries),
        "endnote_explorer_toc_match_count": int(endnote_explorer_summary.get("toc_match_count", 0)),
        "endnote_explorer_ambiguous_page_count": int(endnote_explorer_summary.get("ambiguous_page_count", 0)),
        "endnote_explorer_signal_titles_preview": list(
            endnote_explorer_summary.get("signal_titles_preview") or []
        ),
        "endnote_explorer_toc_titles_preview": [
            str(row.get("title") or "").strip()
            for row in toc_subentries[:6]
            if str(row.get("title") or "").strip()
        ],
        "endnote_explorer_bind_method_counts": dict(bind_method_counts),
        "review_flags": [
            f"region:{region.region_id}"
            for region in regions
            if region.review_required
        ],
    }
    return regions, summary

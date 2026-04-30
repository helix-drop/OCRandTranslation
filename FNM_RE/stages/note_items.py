"""FNM_RE 第二阶段：note_items。"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import re
from typing import Any, Mapping

from document.note_detection import annotate_pages_with_note_scans

from FNM_RE.models import NoteItemRecord, NoteRegionRecord, Phase1Structure
from FNM_RE.shared.notes import (
    extract_pdf_text_by_page,
    normalize_note_marker,
    parse_note_items_from_text,
    scan_items_by_kind,
)
from FNM_RE.shared.text import page_markdown_text
from FNM_RE.shared.title import chapter_title_match_key


_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")


def _annotated_page_by_no(pages: list[dict]) -> dict[int, dict]:
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


def _region_pages(region: NoteRegionRecord) -> list[int]:
    pages = sorted({int(page_no) for page_no in region.pages if int(page_no) > 0})
    if pages:
        return pages
    if int(region.page_start) > 0 and int(region.page_end) >= int(region.page_start):
        return list(range(int(region.page_start), int(region.page_end) + 1))
    return []


def _parse_items_from_structured_scan(page: Mapping[str, Any], *, kind: str) -> list[dict]:
    return scan_items_by_kind(page, kind=kind)


def _raw_scan_items_by_kind(page: Mapping[str, Any], *, kind: str) -> list[dict]:
    scan = dict((dict(page or {})).get("_note_scan") or {})
    target_kind = str(kind or "").strip().lower()
    rows: list[dict] = []
    for item in scan.get("items") or []:
        if str(item.get("kind") or "").strip().lower() != target_kind:
            continue
        marker = normalize_note_marker(item.get("marker") or item.get("number") or "")
        text = str(item.get("text") or "").strip()
        if not marker and not text:
            continue
        rows.append(
            {
                "marker": marker,
                "text": re.sub(r"\s+", " ", text).strip(),
                "is_reconstructed": bool(item.get("is_reconstructed")),
                "source": str(item.get("source") or "note_scan"),
                "section_title": str(item.get("section_title") or "").strip(),
            }
        )
    return rows


def _section_title_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _MARKDOWN_HEADING_RE.match(text)
    if match:
        text = str(match.group(1) or "").strip()
    return chapter_title_match_key(text)


def _chapter_title_by_id(phase1: Phase1Structure) -> dict[str, str]:
    return {
        str(chapter.chapter_id or "").strip(): str(chapter.title or "").strip()
        for chapter in phase1.chapters
        if str(chapter.chapter_id or "").strip()
    }


def _region_title_keys(
    region: NoteRegionRecord,
    *,
    chapter_title_by_id: Mapping[str, str],
) -> set[str]:
    keys = {
        _section_title_key(region.heading_text),
        _section_title_key(chapter_title_by_id.get(str(region.chapter_id or "").strip()) or ""),
    }
    return {key for key in keys if key}


def _filter_shared_page_rows_for_region(
    rows: list[dict],
    region: NoteRegionRecord,
    *,
    chapter_title_by_id: Mapping[str, str],
) -> list[dict]:
    section_keys = {_section_title_key(row.get("section_title") or "") for row in rows}
    section_keys.discard("")
    if not section_keys:
        return rows
    target_keys = _region_title_keys(region, chapter_title_by_id=chapter_title_by_id)
    matched_keys = target_keys & section_keys
    if matched_keys:
        return [
            row
            for row in rows
            if _section_title_key(row.get("section_title") or "") in matched_keys
        ]
    return [row for row in rows if not _section_title_key(row.get("section_title") or "")]


def _title_key_matches(line_key: str, target_key: str) -> bool:
    if not line_key or not target_key:
        return False
    candidates = {
        target_key,
        re.sub(r"^\d+", "", target_key),
    }
    for candidate in candidates:
        if not candidate:
            continue
        if line_key == candidate:
            return True
        if len(candidate) >= 6 and line_key.startswith(candidate):
            return True
        if len(line_key) >= 12 and candidate.startswith(line_key):
            return True
    return False


def _all_chapter_title_keys(chapter_title_by_id: Mapping[str, str]) -> set[str]:
    return {
        key
        for key in (_section_title_key(title) for title in chapter_title_by_id.values())
        if key
    }


def _matching_markdown_heading_indices(
    text: str,
    *,
    target_keys: set[str],
    all_title_keys: set[str],
) -> tuple[list[int], list[int]]:
    current_region_indices: list[int] = []
    any_chapter_indices: list[int] = []
    for index, raw_line in enumerate(str(text or "").splitlines()):
        if not _MARKDOWN_HEADING_RE.match(str(raw_line or "")):
            continue
        line_key = _section_title_key(raw_line)
        if not line_key:
            continue
        if any(_title_key_matches(line_key, key) for key in target_keys):
            current_region_indices.append(index)
        if any(_title_key_matches(line_key, key) for key in all_title_keys):
            any_chapter_indices.append(index)
    return current_region_indices, any_chapter_indices


def _split_shared_page_text_for_region(
    text: str,
    region: NoteRegionRecord,
    *,
    chapter_title_by_id: Mapping[str, str],
) -> tuple[str, bool]:
    lines = str(text or "").splitlines()
    if not lines:
        return "", False
    target_keys = _region_title_keys(region, chapter_title_by_id=chapter_title_by_id)
    all_title_keys = _all_chapter_title_keys(chapter_title_by_id)
    if not target_keys or not all_title_keys:
        return str(text or ""), False
    current_indices, any_indices = _matching_markdown_heading_indices(
        str(text or ""),
        target_keys=target_keys,
        all_title_keys=all_title_keys,
    )
    if current_indices:
        return "\n".join(lines[current_indices[0] :]).strip(), True
    if any_indices:
        return "\n".join(lines[: any_indices[0]]).strip(), True
    return str(text or ""), False


def _last_numeric_marker_value(rows: list[dict], default: int | None) -> int | None:
    marker_value = default
    for row in rows:
        marker = normalize_note_marker(row.get("marker") or "")
        if not marker.isdigit():
            continue
        marker_value = int(marker)
    return marker_value


def _normalized_page_text(
    page_no: int,
    *,
    note_kind: str,
    page_by_no: Mapping[int, Mapping[str, Any]],
    page_text_map: Mapping[int, str],
    pdf_text_by_page: Mapping[int, str],
) -> tuple[str, str]:
    mapped = str(page_text_map.get(page_no) or "").strip()
    if mapped:
        return mapped, "page_text_map"
    page = page_by_no.get(page_no)
    if str(note_kind or "") == "footnote":
        footnotes = str((page or {}).get("footnotes") or "").strip()
        if footnotes:
            return footnotes, "footnotes"
    markdown = page_markdown_text(page)
    if str(markdown or "").strip():
        return str(markdown or ""), "markdown"
    pdf_text = str(pdf_text_by_page.get(page_no) or "").strip()
    if pdf_text:
        return pdf_text, "pdf_text"
    return "", ""


def _dedupe_region_items(items: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in items:
        marker = normalize_note_marker(item.get("marker") or "")
        if marker and marker in seen:
            continue
        if marker:
            seen.add(marker)
        deduped.append(item)
    return deduped


def _chapter_id_set(phase1: Phase1Structure) -> set[str]:
    return {chapter.chapter_id for chapter in phase1.chapters}


def _fix_year_markers_in_place(records: list[NoteItemRecord]) -> list[NoteItemRecord]:
    """修正 OCR 将出版年份误作尾注 marker 的情况。

    若一个 marker 是年份（1500-2100）且夹在连续数字之间（如 3, 1976, 4），
    删除该幽灵条目。
    若前后数字不连续但有跳跃（如 3, 1976, 5），将年份替换为插值数字。
    """
    if len(records) < 3:
        return records
    updated = list(records)
    to_remove: set[int] = set()
    for i in range(1, len(updated) - 1):
        prev_marker = _try_parse_int(updated[i - 1].marker)
        curr_marker = _try_parse_int(updated[i].marker)
        next_marker = _try_parse_int(updated[i + 1].marker)
        if prev_marker is None or curr_marker is None or next_marker is None:
            continue
        if not (1500 <= curr_marker <= 2100):
            continue
        if prev_marker + 1 == next_marker:
            # 年份夹在连续数字之间 → 幽灵条目，删除
            to_remove.add(i)
        elif prev_marker + 2 == next_marker:
            # 年份占据了一个数字位 → 插值替换
            corrected = prev_marker + 1
            updated[i] = replace(updated[i], marker=str(corrected))
    return [row for idx, row in enumerate(updated) if idx not in to_remove]


def _try_parse_int(value: Any) -> int | None:
    try:
        return int(str(value or "").strip())
    except (ValueError, TypeError):
        return None


def build_note_items(
    note_regions: list[NoteRegionRecord],
    phase1: Phase1Structure,
    *,
    pages: list[dict],
    pdf_path: str = "",
    page_text_map: Mapping[int | str, str] | None = None,
) -> tuple[list[NoteItemRecord], dict]:
    page_by_no = _annotated_page_by_no(pages)
    normalized_page_text_map: dict[int, str] = {}
    for raw_key, raw_value in dict(page_text_map or {}).items():
        try:
            page_no = int(raw_key)
        except (TypeError, ValueError):
            continue
        if page_no <= 0:
            continue
        text = str(raw_value or "").strip()
        if text:
            normalized_page_text_map[page_no] = text

    target_pages = {page_no for region in note_regions for page_no in _region_pages(region)}
    pdf_text_by_page = extract_pdf_text_by_page(
        str(pdf_path or ""),
        pages=pages,
        target_pages=target_pages,
    )

    records: list[NoteItemRecord] = []
    region_item_count_map: dict[str, int] = {}
    empty_region_ids: list[str] = []
    marker_alignment_failures: list[dict[str, Any]] = []
    reconstructed_item_count = 0
    pdf_text_fallback_count = 0
    footnote_serial = 1
    endnote_serial = 1
    chapter_ids = _chapter_id_set(phase1)
    chapter_title_by_id = _chapter_title_by_id(phase1)
    page_region_counts = Counter(
        page_no
        for region in note_regions
        for page_no in _region_pages(region)
        if int(page_no) > 0
    )
    shared_page_split_pages: set[int] = set()
    shared_page_text_split_pages: set[int] = set()

    for region in note_regions:
        region_id = str(region.region_id or "").strip()
        chapter_id = str(region.chapter_id or "").strip()
        if not region_id:
            continue
        region_kind = "footnote" if region.note_kind == "footnote" else "endnote"
        parsed_rows: list[dict] = []
        last_marker_value: int | None = None
        used_page_text_fallback = False

        for page_no in _region_pages(region):
            page_payload = page_by_no.get(page_no) or {}
            is_shared_endnote_page = (
                region_kind == "endnote"
                and int(page_region_counts.get(page_no, 0) or 0) > 1
            )
            if is_shared_endnote_page:
                parsed_from_scan = _raw_scan_items_by_kind(page_payload, kind=region_kind)
                if parsed_from_scan and any(_section_title_key(row.get("section_title") or "") for row in parsed_from_scan):
                    filtered_rows = _filter_shared_page_rows_for_region(
                        parsed_from_scan,
                        region,
                        chapter_title_by_id=chapter_title_by_id,
                    )
                    if filtered_rows != parsed_from_scan:
                        shared_page_split_pages.add(int(page_no))
                    parsed_rows.extend(
                        {
                            "page_no": page_no,
                            "marker": normalize_note_marker(row.get("marker") or ""),
                            "text": str(row.get("text") or "").strip(),
                            "is_reconstructed": bool(row.get("is_reconstructed")),
                            "source": str(row.get("source") or "note_scan"),
                        }
                        for row in filtered_rows
                    )
                    last_marker_value = _last_numeric_marker_value(filtered_rows, last_marker_value)
                    continue
                text, text_source = _normalized_page_text(
                    page_no,
                    note_kind=region_kind,
                    page_by_no=page_by_no,
                    page_text_map=normalized_page_text_map,
                    pdf_text_by_page=pdf_text_by_page,
                )
                split_text, did_split_text = _split_shared_page_text_for_region(
                    text,
                    region,
                    chapter_title_by_id=chapter_title_by_id,
                )
                if did_split_text:
                    shared_page_text_split_pages.add(int(page_no))
                    if not split_text:
                        continue
                    parsed_from_text, marker_state = parse_note_items_from_text(
                        split_text,
                        last_marker_value=last_marker_value,
                    )
                    if parsed_from_text:
                        parsed_rows.extend(
                            {
                                "page_no": page_no,
                                "marker": normalize_note_marker(row.get("marker") or ""),
                                "text": str(row.get("text") or "").strip(),
                                "is_reconstructed": bool(row.get("is_reconstructed")),
                                "source": text_source or "markdown",
                            }
                            for row in parsed_from_text
                        )
                        if text_source in {"page_text_map", "pdf_text"}:
                            used_page_text_fallback = True
                        last_marker_value = marker_state
                    continue
                if int(region.page_start or 0) != int(page_no):
                    continue
            text, text_source = _normalized_page_text(
                page_no,
                note_kind=region_kind,
                page_by_no=page_by_no,
                page_text_map=normalized_page_text_map,
                pdf_text_by_page=pdf_text_by_page,
            )
            parsed_from_text, marker_state = parse_note_items_from_text(
                text,
                last_marker_value=last_marker_value,
            )
            if parsed_from_text:
                parsed_rows.extend(
                    {
                        "page_no": page_no,
                        "marker": normalize_note_marker(row.get("marker") or ""),
                        "text": str(row.get("text") or "").strip(),
                        "is_reconstructed": bool(row.get("is_reconstructed")),
                        "source": text_source or "markdown",
                    }
                    for row in parsed_from_text
                )
                if text_source in {"page_text_map", "pdf_text"}:
                    used_page_text_fallback = True
                last_marker_value = marker_state
                continue

            parsed_from_scan = _parse_items_from_structured_scan(page_payload, kind=region_kind)
            if parsed_from_scan:
                parsed_rows.extend(
                    {
                        "page_no": page_no,
                        "marker": normalize_note_marker(row.get("marker") or ""),
                        "text": str(row.get("text") or "").strip(),
                        "is_reconstructed": bool(row.get("is_reconstructed")),
                        "source": "note_scan",
                    }
                    for row in parsed_from_scan
                )
                last_marker_value = _last_numeric_marker_value(parsed_from_scan, last_marker_value)
                continue

            if text_source in {"page_text_map", "pdf_text"} and text:
                used_page_text_fallback = True

        parsed_rows = [row for row in _dedupe_region_items(parsed_rows) if row.get("text")]
        region_item_count_map[region_id] = len(parsed_rows)
        if used_page_text_fallback:
            pdf_text_fallback_count += 1
        if not parsed_rows:
            empty_region_ids.append(region_id)
            region.review_required = True
            region.region_marker_alignment_ok = False
            region.region_first_note_item_marker = ""
            continue

        first_marker = normalize_note_marker(parsed_rows[0].get("marker") or "")
        region.region_first_note_item_marker = first_marker
        if region.note_kind == "endnote" and region.scope == "chapter":
            source_marker = normalize_note_marker(region.region_start_first_source_marker or "")
            aligned = True
            if source_marker and first_marker:
                aligned = source_marker == first_marker
            region.region_marker_alignment_ok = aligned
            if not aligned:
                region.review_required = True
                marker_alignment_failures.append(
                    {
                        "region_id": region_id,
                        "chapter_id": chapter_id,
                        "source_marker": source_marker,
                        "note_item_marker": first_marker,
                    }
                )
        else:
            region.region_marker_alignment_ok = True

        for row in parsed_rows:
            marker = normalize_note_marker(row.get("marker") or "")
            if not marker:
                continue
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            is_reconstructed = bool(row.get("is_reconstructed"))
            if is_reconstructed:
                reconstructed_item_count += 1
            if region.note_kind == "footnote":
                note_item_id = f"fn-{footnote_serial:05d}"
                footnote_serial += 1
            else:
                note_item_id = f"en-{endnote_serial:05d}"
                endnote_serial += 1
            records.append(
                NoteItemRecord(
                    note_item_id=note_item_id,
                    region_id=region_id,
                    chapter_id=chapter_id,
                    page_no=int(row.get("page_no") or 0),
                    marker=marker,
                    marker_type="numeric",
                    text=text,
                    source=str(row.get("source") or "markdown"),
                    source_page_label=f"p{int(row.get('page_no') or 0)}",
                    is_reconstructed=is_reconstructed,
                    review_required=bool(region.review_required),
                )
            )

    records.sort(key=lambda item: (int(item.page_no), item.note_item_id))
    # 阶段4.B：修正年份误标——尾注页上的出版年份被 OCR 误作 marker
    records = _fix_year_markers_in_place(records)
    orphan_item_count = sum(1 for item in records if item.chapter_id not in chapter_ids)
    summary = {
        "region_item_count_map": region_item_count_map,
        "empty_region_ids": empty_region_ids,
        "reconstructed_item_count": int(reconstructed_item_count),
        "pdf_text_fallback_count": int(pdf_text_fallback_count),
        "marker_alignment_failures": marker_alignment_failures,
        "orphan_item_count": int(orphan_item_count),
        "shared_page_split_count": int(len(shared_page_split_pages)),
        "shared_page_text_split_count": int(len(shared_page_text_split_pages)),
    }
    return records, summary

"""FNM_RE 第二阶段：note_items。"""

from __future__ import annotations

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
    orphan_item_count = sum(1 for item in records if item.chapter_id not in chapter_ids)
    summary = {
        "region_item_count_map": region_item_count_map,
        "empty_region_ids": empty_region_ids,
        "reconstructed_item_count": int(reconstructed_item_count),
        "pdf_text_fallback_count": int(pdf_text_fallback_count),
        "marker_alignment_failures": marker_alignment_failures,
        "orphan_item_count": int(orphan_item_count),
    }
    return records, summary

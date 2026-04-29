"""FNM_RE 第三阶段：body_anchors。"""

from __future__ import annotations

from collections import Counter
from typing import Any

from FNM_RE.models import BodyAnchorRecord, Phase2Structure
from FNM_RE.shared.chapters import chapter_id_for_page, chapter_id_for_page as _chapter_id_for_page
from FNM_RE.shared.anchors import (
    anchor_dedupe_key,
    page_body_paragraphs,
    resolve_anchor_kind,
    scan_anchor_markers,
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


def _chapter_mode_map(phase2: Phase2Structure) -> dict[str, str]:
    return {
        str(row.chapter_id): str(row.note_mode)
        for row in phase2.chapter_note_modes
        if str(row.chapter_id or "").strip()
    }


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


def build_body_anchors(
    phase2: Phase2Structure,
    *,
    pages: list[dict],
) -> tuple[list[BodyAnchorRecord], dict]:
    page_by_no = _page_payload_by_no(pages)
    page_role_by_no = {
        int(row.page_no): str(row.page_role)
        for row in phase2.pages
        if int(row.page_no) > 0
    }
    mode_by_chapter = _chapter_mode_map(phase2)
    footnote_band_pages = _footnote_band_page_keys(phase2)

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
        note_mode = str(mode_by_chapter.get(chapter_id) or "no_notes")
        has_page_footnote_band = (chapter_id, page_no) in footnote_band_pages
        anchor_kind = resolve_anchor_kind(
            note_mode, has_page_footnote_band=has_page_footnote_band
        )
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
                        anchor_kind=anchor_kind,  # type: ignore[arg-type]
                        certainty=float(match.get("certainty", 0.4)),
                        source_text=paragraph_text,
                        source=f"{str(paragraph.get('source') or 'markdown')}:{str(match.get('pattern') or 'ref')}",
                        synthetic=False,
                        ocr_repaired_from_marker="",
                    )
                )
                anchor_counter += 1

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

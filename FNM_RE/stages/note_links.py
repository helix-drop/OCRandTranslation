"""FNM_RE 第三阶段：note_links 编排入口。

尾注匹配 → endnote_links.build_endnote_links()
脚注匹配 → footnote_links.build_footnote_links()
共享工具  → _link_utils
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any

from FNM_RE.models import BodyAnchorRecord, NoteLinkRecord, Phase2Structure
from FNM_RE.shared.notes import normalize_note_marker
from FNM_RE.stages._link_utils import (
    _is_fallback_chapter_id,
    _is_toc_chapter_id,
    link_new_link,
)
from FNM_RE.stages.endnote_links import build_endnote_links
from FNM_RE.stages.footnote_links import build_footnote_links


def _region_map(phase2: Phase2Structure) -> dict[str, Any]:
    return {
        str(region.region_id or ""): region
        for region in phase2.note_regions
        if str(region.region_id or "").strip()
    }


# ── 编排入口 ──

def build_note_links(
    body_anchors: list[BodyAnchorRecord],
    phase2: Phase2Structure,
    *,
    pages: list[dict],
) -> tuple[list[BodyAnchorRecord], list[NoteLinkRecord], dict]:
    _ = list(pages or [])
    anchors: list[BodyAnchorRecord] = [replace(anchor) for anchor in body_anchors]
    regions_by_id = _region_map(phase2)
    used_anchor_ids: set[str] = set()
    anchor_count_by_chapter = Counter(
        str(row.chapter_id or "") for row in anchors if not bool(row.synthetic)
    )

    note_items_sorted = sorted(
        phase2.note_items, key=lambda row: (int(row.page_no), row.note_item_id)
    )

    # ── 尾注匹配 ──
    en_links, _orphan_indexes = build_endnote_links(
        anchors, note_items_sorted, regions_by_id, used_anchor_ids,
        anchor_count_by_chapter, pages=pages,
        link_serial_start=1,
    )

    # ── 脚注匹配 ──
    fn_links, _fn_serial, synthetic_serial, ocr_repaired_count = build_footnote_links(
        anchors, note_items_sorted, regions_by_id, used_anchor_ids,
        link_serial_start=len(en_links) + 1,
    )

    links: list[NoteLinkRecord] = en_links + fn_links
    synthetic_added_count = synthetic_serial - 1

    # ── orphan_anchor links（仅显式 anchors）──
    note_item_marker_keys: set[tuple[str, str, str]] = set()
    note_kind_marker_ranges: dict[tuple[str, str], tuple[int, int]] = {}
    note_kind_with_markers: set[tuple[str, str]] = set()
    for note_item in phase2.note_items:
        normalized_marker = normalize_note_marker(note_item.marker)
        if not normalized_marker:
            continue
        region = regions_by_id.get(str(note_item.region_id or "")) or {}
        note_kind = str(getattr(region, "note_kind", "") or "")
        if note_kind not in {"footnote", "endnote"}:
            continue
        chapter_id = str(note_item.chapter_id or getattr(region, "chapter_id", "") or "")
        if not chapter_id:
            continue
        note_item_marker_keys.add((chapter_id, note_kind, normalized_marker))
        marker_int: int | None = None
        try:
            marker_int = int(normalized_marker)
        except (TypeError, ValueError):
            marker_int = None
        if marker_int is None:
            continue
        range_key = (chapter_id, note_kind)
        note_kind_with_markers.add(range_key)
        existing_range = note_kind_marker_ranges.get(range_key)
        if existing_range is None:
            note_kind_marker_ranges[range_key] = (marker_int, marker_int)
        else:
            note_kind_marker_ranges[range_key] = (
                min(existing_range[0], marker_int),
                max(existing_range[1], marker_int),
            )

    matched_marker_keys = {
        (str(row.chapter_id or ""), str(row.note_kind or ""),
         normalize_note_marker(row.marker))
        for row in links
        if row.status == "matched" and normalize_note_marker(row.marker)
    }
    link_serial = len(links) + 1

    def _append_link(**kwargs: Any) -> None:
        nonlocal link_serial
        links.append(link_new_link(serial=link_serial, **kwargs))
        link_serial += 1

    for anchor in anchors:
        if anchor.synthetic or anchor.anchor_id in used_anchor_ids:
            continue
        normalized_marker = normalize_note_marker(anchor.normalized_marker)
        if not normalized_marker:
            continue
        ak = str(anchor.anchor_kind or "")
        inferred_kind = "footnote" if ak == "footnote" else ("endnote" if ak == "endnote" else "unknown")
        if (str(anchor.chapter_id or ""), inferred_kind, normalized_marker) in matched_marker_keys:
            continue
        if (str(anchor.chapter_id or ""), inferred_kind, normalized_marker) in note_item_marker_keys:
            continue
        chapter_key = (str(anchor.chapter_id or ""), inferred_kind)
        if _is_fallback_chapter_id(anchor.chapter_id) and chapter_key not in note_kind_with_markers:
            continue
        marker_range = note_kind_marker_ranges.get(chapter_key)
        if marker_range and _is_toc_chapter_id(anchor.chapter_id):
            marker_int: int | None = None
            try:
                marker_int = int(normalized_marker)
            except (TypeError, ValueError):
                marker_int = None
            if marker_int is not None and (marker_int < marker_range[0] or marker_int > marker_range[1]):
                continue
        _append_link(
            chapter_id=anchor.chapter_id, region_id="", note_item_id="",
            anchor_id=anchor.anchor_id, status="orphan_anchor",
            resolver="rule", confidence=0.0, note_kind=inferred_kind,
            marker=normalized_marker,
            page_no_start=anchor.page_no, page_no_end=anchor.page_no,
        )

    links.sort(key=lambda row: row.link_id)
    anchors.sort(key=lambda row: (
        int(row.page_no), int(row.paragraph_index), int(row.char_start), row.anchor_id
    ))

    note_link_summary = {
        "matched": sum(1 for row in links if row.status == "matched"),
        "footnote_orphan_note": sum(1 for row in links if row.note_kind == "footnote" and row.status == "orphan_note"),
        "footnote_orphan_anchor": sum(1 for row in links if row.note_kind == "footnote" and row.status == "orphan_anchor"),
        "endnote_orphan_note": sum(1 for row in links if row.note_kind == "endnote" and row.status == "orphan_note"),
        "endnote_orphan_anchor": sum(1 for row in links if row.note_kind == "endnote" and row.status == "orphan_anchor"),
        "unknown_orphan": sum(1 for row in links if row.note_kind not in {"footnote", "endnote"} and row.status in {"orphan_note", "orphan_anchor"}),
        "ambiguous": sum(1 for row in links if row.status == "ambiguous"),
        "ignored": sum(1 for row in links if row.status == "ignored"),
        "fallback_count": sum(1 for row in links if row.resolver == "fallback"),
        "repair_count": sum(1 for row in links if row.resolver == "repair"),
    }
    review_seed_summary = {
        "boundary_review_required_count": sum(
            1 for row in phase2.chapter_note_modes if row.note_mode == "review_required"
        ),
        "uncertain_anchor_ids": [
            row.anchor_id for row in anchors
            if row.anchor_kind == "unknown" or float(row.certainty) < 1.0
        ],
        "orphan_link_ids": [
            row.link_id for row in links
            if row.status in {"orphan_note", "orphan_anchor"}
        ],
        "ambiguous_link_ids": [row.link_id for row in links if row.status == "ambiguous"],
        "synthetic_anchor_ids": [row.anchor_id for row in anchors if row.synthetic],
    }
    summary = {
        "note_link_summary": note_link_summary,
        "review_seed_summary": review_seed_summary,
        "anchor_patch_summary": {
            "synthetic_added_count": int(synthetic_added_count),
            "ocr_repaired_count": int(ocr_repaired_count),
            "kind_counts": dict(Counter(row.anchor_kind for row in anchors)),
        },
    }
    return anchors, links, summary

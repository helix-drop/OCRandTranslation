"""脚注 link 匹配：anchor → note_item 配对、synthetic anchor 降级。"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from FNM_RE.models import BodyAnchorRecord, NoteLinkRecord
from FNM_RE.shared.notes import (
    marker_digits_are_ordered_subsequence,
    normalize_note_marker,
)
from FNM_RE.stages._link_utils import (
    _nearest_unique_candidate,
    _within_footnote_window,
    link_candidate_anchors,
    link_new_link,
)


def _make_synthetic_footnote_anchor(
    *,
    serial: int,
    chapter_id: str,
    page_no: int,
    marker: str,
    source_text: str,
) -> BodyAnchorRecord:
    return BodyAnchorRecord(
        anchor_id=f"synthetic-footnote-{serial:05d}",
        chapter_id=str(chapter_id or ""),
        page_no=int(page_no or 0),
        paragraph_index=999,
        char_start=0,
        char_end=0,
        source_marker=str(marker or ""),
        normalized_marker=normalize_note_marker(marker),
        anchor_kind="footnote",
        certainty=0.4,
        source_text=str(source_text or ""),
        source="synthetic",
        synthetic=True,
        ocr_repaired_from_marker="",
    )


def build_footnote_links(
    anchors: list[BodyAnchorRecord],
    phase2_note_items: list[Any],
    regions_by_id: dict[str, Any],
    used_anchor_ids: set[str],
    *,
    link_serial_start: int = 1,
    synthetic_serial_start: int = 1,
) -> tuple[list[NoteLinkRecord], int, int, int]:
    """构建脚注 link。

    Returns:
        (links, link_serial_end, synthetic_serial_end, ocr_repaired_count)
    """
    links: list[NoteLinkRecord] = []
    link_serial = link_serial_start
    synthetic_serial = synthetic_serial_start
    synthetic_added_count = 0
    ocr_repaired_count = 0

    def _append_link(**kwargs: Any) -> None:
        nonlocal link_serial
        links.append(link_new_link(serial=link_serial, **kwargs))
        link_serial += 1

    # --- footnote_resolver ---
    for note_item in phase2_note_items:
        region = regions_by_id.get(str(note_item.region_id or "")) or {}
        note_kind = str(getattr(region, "note_kind", "") or "")
        if note_kind != "footnote":
            continue
        marker = normalize_note_marker(note_item.marker)
        chapter_id = str(note_item.chapter_id or getattr(region, "chapter_id", "") or "")
        if not marker:
            _append_link(
                chapter_id=chapter_id, region_id=note_item.region_id,
                note_item_id=note_item.note_item_id, anchor_id="",
                status="ignored", resolver="rule", confidence=0.0,
                note_kind="footnote", marker="",
                page_no_start=note_item.page_no, page_no_end=note_item.page_no,
            )
            continue

        # 星号脚注按页内顺序匹配
        if marker and re.match(r"^\*{1,4}$", marker):
            same_page_candidates = [
                a for a in anchors
                if str(a.chapter_id or "") == chapter_id
                and not a.synthetic
                and a.anchor_id not in used_anchor_ids
                and a.anchor_kind in {"footnote", "unknown"}
                and normalize_note_marker(a.normalized_marker) == marker
                and int(a.page_no or 0) == int(note_item.page_no or 0)
            ]
            same_page_candidates.sort(key=lambda a: (int(a.paragraph_index), int(a.char_start)))
            if same_page_candidates:
                selected = same_page_candidates[0]
                used_anchor_ids.add(selected.anchor_id)
                _append_link(
                    chapter_id=chapter_id, region_id=note_item.region_id,
                    note_item_id=note_item.note_item_id, anchor_id=selected.anchor_id,
                    status="matched", resolver="rule",
                    confidence=max(0.0, min(1.0, float(selected.certainty))),
                    note_kind="footnote", marker=marker,
                    page_no_start=note_item.page_no, page_no_end=note_item.page_no,
                )
                continue

        candidates = link_candidate_anchors(
            anchors, chapter_id=chapter_id, marker=marker,
            expected_kinds={"footnote"}, used_anchor_ids=used_anchor_ids,
            page_no=note_item.page_no, footnote_window=True,
            include_synthetic=False,
        )
        if len(candidates) == 1:
            selected = candidates[0]
            used_anchor_ids.add(selected.anchor_id)
            _append_link(
                chapter_id=chapter_id, region_id=note_item.region_id,
                note_item_id=note_item.note_item_id, anchor_id=selected.anchor_id,
                status="matched", resolver="rule",
                confidence=max(0.0, min(1.0, float(selected.certainty))),
                note_kind="footnote", marker=marker,
                page_no_start=note_item.page_no, page_no_end=note_item.page_no,
            )
            continue
        if len(candidates) > 1:
            selected = _nearest_unique_candidate(candidates, target_page=note_item.page_no)
            if selected is not None:
                used_anchor_ids.add(selected.anchor_id)
                _append_link(
                    chapter_id=chapter_id, region_id=note_item.region_id,
                    note_item_id=note_item.note_item_id, anchor_id=selected.anchor_id,
                    status="matched", resolver="repair",
                    confidence=max(0.0, min(1.0, float(selected.certainty))),
                    note_kind="footnote", marker=marker,
                    page_no_start=note_item.page_no, page_no_end=note_item.page_no,
                )
                continue
            _append_link(
                chapter_id=chapter_id, region_id=note_item.region_id,
                note_item_id=note_item.note_item_id, anchor_id="",
                status="ambiguous", resolver="rule", confidence=0.0,
                note_kind="footnote", marker=marker,
                page_no_start=note_item.page_no, page_no_end=note_item.page_no,
            )
            continue

        # OCR repair: ordered subsequence match
        repair_candidates: list[BodyAnchorRecord] = []
        for a in anchors:
            if a.chapter_id != chapter_id or a.synthetic or a.anchor_id in used_anchor_ids:
                continue
            if not _within_footnote_window(a.page_no, note_item.page_no):
                continue
            if a.anchor_kind not in {"footnote", "unknown"}:
                continue
            if len(normalize_note_marker(a.normalized_marker)) >= len(marker):
                continue
            if marker_digits_are_ordered_subsequence(a.normalized_marker, marker):
                repair_candidates.append(a)
        repair_candidates.sort(key=lambda row: (
            abs(int(row.page_no) - int(note_item.page_no)),
            int(row.paragraph_index), int(row.char_start),
        ))
        if len(repair_candidates) == 1:
            selected = repair_candidates[0]
            original_marker = normalize_note_marker(selected.normalized_marker)
            selected.normalized_marker = marker
            selected.anchor_kind = "footnote"  # type: ignore[assignment]
            selected.certainty = 1.0
            selected.ocr_repaired_from_marker = original_marker
            used_anchor_ids.add(selected.anchor_id)
            ocr_repaired_count += 1
            _append_link(
                chapter_id=chapter_id, region_id=note_item.region_id,
                note_item_id=note_item.note_item_id, anchor_id=selected.anchor_id,
                status="matched", resolver="repair", confidence=1.0,
                note_kind="footnote", marker=marker,
                page_no_start=note_item.page_no, page_no_end=note_item.page_no,
            )
            continue

        # 最终降级：synthetic footnote anchor
        synthetic_anchor = _make_synthetic_footnote_anchor(
            serial=synthetic_serial, chapter_id=chapter_id,
            page_no=note_item.page_no, marker=marker,
            source_text=note_item.text,
        )
        synthetic_serial += 1
        synthetic_added_count += 1
        anchors.append(synthetic_anchor)
        used_anchor_ids.add(synthetic_anchor.anchor_id)
        _append_link(
            chapter_id=chapter_id, region_id=note_item.region_id,
            note_item_id=note_item.note_item_id, anchor_id=synthetic_anchor.anchor_id,
            status="matched", resolver="fallback", confidence=0.4,
            note_kind="footnote", marker=marker,
            page_no_start=note_item.page_no, page_no_end=note_item.page_no,
        )
        continue

        _append_link(
            chapter_id=chapter_id, region_id=note_item.region_id,
            note_item_id=note_item.note_item_id, anchor_id="",
            status="orphan_note", resolver="rule", confidence=0.0,
            note_kind="footnote", marker=marker,
            page_no_start=note_item.page_no, page_no_end=note_item.page_no,
        )

    # --- synthetic 替换为同页显式 anchor ---
    for index, link in enumerate(links):
        if link.note_kind != "footnote" or link.status != "matched":
            continue
        if not link.anchor_id.startswith("synthetic-footnote-"):
            continue
        explicit_candidates = link_candidate_anchors(
            anchors, chapter_id=link.chapter_id, marker=link.marker,
            expected_kinds={"footnote", "unknown"},
            used_anchor_ids=used_anchor_ids,
            page_no=link.page_no_start, footnote_window=True,
            include_synthetic=False,
        )
        if len(explicit_candidates) != 1:
            continue
        selected = explicit_candidates[0]
        used_anchor_ids.add(selected.anchor_id)
        links[index] = replace(link, anchor_id=selected.anchor_id,
                               resolver="repair",
                               confidence=max(0.0, min(1.0, float(selected.certainty))))

    return links, link_serial, synthetic_serial, ocr_repaired_count

"""FNM_RE 第三阶段：body_anchors。"""

from __future__ import annotations

from collections import Counter
from typing import Any

from FNM_RE.models import BodyAnchorRecord, Phase2Structure
from FNM_RE.shared.chapters import chapter_id_for_page, chapter_id_for_page as _chapter_id_for_page
from FNM_RE.shared.notes import _chapter_mode_map
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


def _build_chapter_marker_range(phase2: Phase2Structure) -> dict[str, tuple[int, int]]:
    """从 note_items 构建每章 endnote marker 的预期范围。"""
    chapter_markers: dict[str, list[int]] = {}
    for item in phase2.note_items:
        chapter_id = str(item.chapter_id or "").strip()
        if not chapter_id:
            continue
        try:
            marker = int(item.marker)
        except (ValueError, TypeError):
            continue
        if marker <= 0:
            continue
        chapter_markers.setdefault(chapter_id, []).append(marker)
    return {
        ch_id: (min(markers), max(markers))
        for ch_id, markers in chapter_markers.items()
        if markers
    }


def _marker_in_expected_range(
    normalized_marker: str,
    *,
    pattern: str,
    marker_min: int,
    marker_max: int,
) -> bool:
    """正向验证：marker 是否在章节的预期尾注范围内。

    高置信度模式（superscript/latex/html/unicode）始终保留。
    低置信度模式（bare_digit/bracket/trailing）只在预期范围内才保留。
    """
    if marker_max <= 0:
        return True
    try:
        marker_val = int(normalized_marker)
    except (ValueError, TypeError):
        return True
    if pattern in {"latex", "latex_symbol_sup", "plain", "html", "unicode", "footnote_ref"}:
        return True
    tolerance = max(5, int(marker_max * 0.05))
    return marker_min <= marker_val <= marker_max + tolerance


def _fill_marker_gaps(
    anchors: list[BodyAnchorRecord],
    *,
    chapter_marker_range: dict[str, tuple[int, int]],
    mode_by_chapter: dict[str, str],
    footnote_band_pages: set[tuple[str, int]],
    anchor_counter: int,
) -> list[BodyAnchorRecord]:
    """填补 marker 序列中的 OCR 丢失缺口。

    对每个章节，比对已检测 anchor 的 marker 集合和 note_items 的预期范围。
    缺失的 marker 在相邻已检测 marker 之间创建 synthetic anchor。
    """
    synthetic: list[BodyAnchorRecord] = []
    anchors_by_chapter: dict[str, list[BodyAnchorRecord]] = {}
    for anchor in anchors:
        anchors_by_chapter.setdefault(anchor.chapter_id, []).append(anchor)

    counter = anchor_counter
    for chapter_id, chapter_anchors in anchors_by_chapter.items():
        marker_range = chapter_marker_range.get(chapter_id)
        if not marker_range or marker_range[1] <= 0:
            continue
        marker_min, marker_max = marker_range
        detected = sorted(
            int(a.normalized_marker)
            for a in chapter_anchors
            if a.normalized_marker.isdigit() and marker_min <= int(a.normalized_marker) <= marker_max + 5
        )
        if not detected:
            continue
        detected_set = set(detected)
        expected = set(range(detected[0], detected[-1] + 1))
        missing = sorted(expected - detected_set)
        if not missing:
            continue

        # 建立已检测 marker → anchor 的快速查找（取每个 marker 最后出现的 anchor 作为位置参考）
        anchor_by_marker: dict[int, BodyAnchorRecord] = {}
        for a in sorted(chapter_anchors, key=lambda a: (a.page_no, a.paragraph_index, a.char_start)):
            m = int(a.normalized_marker) if a.normalized_marker.isdigit() else 0
            if m > 0:
                anchor_by_marker[m] = a

        note_mode = str(mode_by_chapter.get(chapter_id) or "no_notes")
        for missing_marker in missing:
            prev_anchor = anchor_by_marker.get(missing_marker - 1)
            if prev_anchor is None:
                continue
            has_footnote_band = (chapter_id, prev_anchor.page_no) in footnote_band_pages
            anchor_kind = resolve_anchor_kind(note_mode, has_page_footnote_band=has_footnote_band)
            counter += 1
            new_anchor = BodyAnchorRecord(
                anchor_id=f"anchor-{counter:05d}",
                chapter_id=chapter_id,
                page_no=prev_anchor.page_no,
                paragraph_index=prev_anchor.paragraph_index,
                char_start=prev_anchor.char_end + 1,
                char_end=prev_anchor.char_end + 2,
                source_marker="",
                normalized_marker=str(missing_marker),
                anchor_kind=anchor_kind,
                certainty=0.55,
                source_text=prev_anchor.source_text,
                source="gap_fill",
                synthetic=True,
                ocr_repaired_from_marker="",
            )
            synthetic.append(new_anchor)
            anchor_by_marker[missing_marker] = new_anchor
    return synthetic


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
    chapter_marker_range = _build_chapter_marker_range(phase2)

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
        marker_min, marker_max = chapter_marker_range.get(chapter_id, (0, 0))
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
                if not _marker_in_expected_range(
                    normalized_marker,
                    pattern=str(match.get("pattern") or ""),
                    marker_min=marker_min,
                    marker_max=marker_max,
                ):
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

    gap_filled = _fill_marker_gaps(
        anchors,
        chapter_marker_range=chapter_marker_range,
        mode_by_chapter=mode_by_chapter,
        footnote_band_pages=footnote_band_pages,
        anchor_counter=anchor_counter,
    )
    anchors.extend(gap_filled)
    anchor_counter += len(gap_filled)

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

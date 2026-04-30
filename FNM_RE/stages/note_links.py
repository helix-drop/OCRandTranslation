"""FNM_RE 第三阶段：note_links。"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import re
from typing import Any

from FNM_RE.models import BodyAnchorRecord, NoteLinkRecord, Phase2Structure
from FNM_RE.shared.notes import _chapter_mode_map, normalize_note_marker


def _region_map(phase2: Phase2Structure) -> dict[str, Any]:
    return {
        str(region.region_id or ""): region
        for region in phase2.note_regions
        if str(region.region_id or "").strip()
    }


def _infer_note_kind_from_anchor(anchor: BodyAnchorRecord, *, mode_by_chapter: dict[str, str]) -> str:
    if anchor.anchor_kind == "footnote":
        return "footnote"
    if anchor.anchor_kind == "endnote":
        return "endnote"
    mode = str(mode_by_chapter.get(anchor.chapter_id) or "")
    if mode in {"footnote_primary", "review_required"}:
        return "footnote"
    return "endnote"


from FNM_RE.shared.notes import marker_digits_are_ordered_subsequence as _marker_digits_are_ordered_subsequence  # noqa: F401


def _within_footnote_window(anchor_page: int, note_page: int, *, max_distance: int = 1) -> bool:
    return abs(int(anchor_page) - int(note_page)) <= max_distance


def _is_fallback_chapter_id(chapter_id: str) -> bool:
    return str(chapter_id or "").startswith("ch-fallback-")


def _is_toc_chapter_id(chapter_id: str) -> bool:
    return str(chapter_id or "").startswith("toc-ch-")


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
            len(normalized),
            len(str(row.source_text or "")),
            0 if source.startswith("ocr_block") else 1,
            int(row.paragraph_index),
            int(row.char_start),
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


def _candidate_anchors(
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
    candidates.sort(key=lambda row: (abs(int(row.page_no) - int(page_no or row.page_no)), int(row.page_no), int(row.paragraph_index), int(row.char_start)))
    return candidates


def _make_synthetic_anchor(
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


def _new_link(
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


# ── 阶段4：orphan endnote 直接正文搜索恢复 ──

def _unicode_superscript_pattern(num_str: str) -> str | None:
    superscript_map = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    }
    chars = [superscript_map.get(c) for c in num_str]
    if None in chars:
        return None
    return ''.join(chars)


def _find_marker_in_body(body_text: str, marker: str) -> dict | None:
    """用已知 marker 号在 body text 中做宽松搜索。返回匹配位置或 None。"""
    escaped = re.escape(marker)
    patterns = [
        rf'\[\s*{escaped}\s*\]',
        rf'\$\s*\^\s*\{{\s*{escaped}\s*\}}\s*\$',
        rf'<sup>\s*{escaped}\s*</sup>',
        rf'\^\s*\{{\s*{escaped}\s*\}}',
        rf'\$\^\{{\s*{escaped}\s*\}}\$',
        rf'\^\s*{escaped}\b',
        rf'»\s*{escaped}\b',
        _unicode_superscript_pattern(marker) or "",
    ]
    for pattern in patterns:
        if not pattern:
            continue
        m = re.search(pattern, body_text)
        if m:
            return {
                "start": m.start(),
                "end": m.end(),
                "source_text": body_text[max(0, m.start()-30):min(len(body_text), m.end()+30)],
            }
    return None


def _chapter_body_text(pages: list[dict], body_page_nos: set[int]) -> str:
    """拼接一章所有 body 页的 markdown 文字。"""
    parts: list[str] = []
    for p in pages:
        pno = int(p.get("bookPage") or p.get("pdfPage") or 0)
        if pno not in body_page_nos:
            continue
        md = str(p.get("markdown") or "").strip()
        if md:
            parts.append(md)
    return "\n".join(parts)


def _build_orphan_recovery_anchors(
    orphans: list[dict],
    pages: list[dict],
) -> list[BodyAnchorRecord]:
    """对残余 orphan endnote，用正文直接搜索恢复 anchor。"""
    recovered: list[BodyAnchorRecord] = []
    for orphan in orphans:
        marker = orphan["marker"]
        chapter_id = orphan["chapter_id"]
        note_item_id = orphan["note_item_id"]
        page_nos = set(orphan.get("page_nos") or [])
        body_text = _chapter_body_text(pages, page_nos)
        if not body_text or not marker:
            continue
        hit = _find_marker_in_body(body_text, marker)
        if not hit:
            continue
        recovered.append(
            BodyAnchorRecord(
                anchor_id=f"orphan-recovery-{note_item_id}",
                chapter_id=chapter_id,
                page_no=min(page_nos) if page_nos else 0,
                paragraph_index=0,
                char_start=hit["start"],
                char_end=hit["end"],
                source_marker=marker,
                normalized_marker=marker,
                anchor_kind="endnote",
                certainty=0.7,
                source_text=hit["source_text"],
                source="orphan_recovery",
                synthetic=True,
                ocr_repaired_from_marker="",
            )
        )
    return recovered


def build_note_links(
    body_anchors: list[BodyAnchorRecord],
    phase2: Phase2Structure,
    *,
    pages: list[dict],
) -> tuple[list[BodyAnchorRecord], list[NoteLinkRecord], dict]:
    _ = list(pages or [])
    anchors: list[BodyAnchorRecord] = [replace(anchor) for anchor in body_anchors]
    mode_by_chapter = _chapter_mode_map(phase2)
    regions_by_id = _region_map(phase2)
    used_anchor_ids: set[str] = set()
    links: list[NoteLinkRecord] = []
    link_serial = 1
    synthetic_serial = 1
    synthetic_added_count = 0
    ocr_repaired_count = 0
    anchor_count_by_chapter = Counter(str(row.chapter_id or "") for row in anchors if not bool(row.synthetic))

    def _append_link(**kwargs: Any) -> None:
        nonlocal link_serial
        links.append(_new_link(serial=link_serial, **kwargs))
        link_serial += 1

    note_items_sorted = sorted(phase2.note_items, key=lambda row: (int(row.page_no), row.note_item_id))
    orphan_endnote_link_indexes: list[int] = []

    # endnote_resolver
    for note_item in note_items_sorted:
        region = regions_by_id.get(str(note_item.region_id or "")) or {}
        note_kind = str(getattr(region, "note_kind", "") or "")
        if note_kind != "endnote":
            continue
        marker = normalize_note_marker(note_item.marker)
        chapter_id = str(note_item.chapter_id or getattr(region, "chapter_id", "") or "")
        scope = str(getattr(region, "scope", "") or "")
        if not marker:
            _append_link(
                chapter_id=chapter_id,
                region_id=note_item.region_id,
                note_item_id=note_item.note_item_id,
                anchor_id="",
                status="ignored",
                resolver="rule",
                confidence=0.0,
                note_kind="endnote",
                marker="",
                page_no_start=note_item.page_no,
                page_no_end=note_item.page_no,
            )
            continue
        candidates = _candidate_anchors(
            anchors,
            chapter_id=chapter_id,
            marker=marker,
            expected_kinds={"endnote", "unknown"},
            used_anchor_ids=used_anchor_ids,
            page_no=note_item.page_no,
            include_synthetic=False,
        )
        if not candidates and chapter_id and _is_fallback_chapter_id(chapter_id):
            chapter_anchor_count = int(anchor_count_by_chapter.get(chapter_id, 0) or 0)
            if chapter_anchor_count == 0:
                candidates = _candidate_anchors(
                    anchors,
                    chapter_id=chapter_id,
                    marker=marker,
                    expected_kinds={"endnote", "unknown"},
                    used_anchor_ids=used_anchor_ids,
                    page_no=note_item.page_no,
                    include_synthetic=False,
                    allow_cross_chapter=True,
                )
        if not candidates:
            candidates = _candidate_anchors(
                anchors,
                chapter_id=chapter_id,
                marker=marker,
                expected_kinds={"endnote"},
                used_anchor_ids=used_anchor_ids,
                page_no=note_item.page_no,
                include_synthetic=True,
                allow_cross_chapter=False,
            )
        if not candidates:
            candidates = _candidate_anchors(
                anchors,
                chapter_id=chapter_id,
                marker=marker,
                expected_kinds={"endnote"},
                used_anchor_ids=used_anchor_ids,
                page_no=note_item.page_no,
                include_synthetic=True,
                allow_cross_chapter=True,
            )
        if not candidates and chapter_id and _is_toc_chapter_id(chapter_id):
            candidates = _candidate_anchors(
                anchors,
                chapter_id=chapter_id,
                marker=marker,
                expected_kinds={"endnote", "unknown"},
                used_anchor_ids=used_anchor_ids,
                page_no=note_item.page_no,
                include_synthetic=False,
                allow_cross_chapter=True,
            )
        if not candidates and scope == "book" and chapter_id:
            candidates = _candidate_anchors(
                anchors,
                chapter_id=chapter_id,
                marker=marker,
                expected_kinds={"endnote", "unknown"},
                used_anchor_ids=used_anchor_ids,
                page_no=note_item.page_no,
                include_synthetic=False,
            )
        if len(candidates) == 1:
            selected = candidates[0]
            used_anchor_ids.add(selected.anchor_id)
            _append_link(
                chapter_id=chapter_id,
                region_id=note_item.region_id,
                note_item_id=note_item.note_item_id,
                anchor_id=selected.anchor_id,
                status="matched",
                resolver="fallback" if scope == "book" else "rule",
                confidence=max(0.0, min(1.0, float(selected.certainty))),
                note_kind="endnote",
                marker=marker,
                page_no_start=note_item.page_no,
                page_no_end=note_item.page_no,
            )
            continue
        if len(candidates) > 1:
            selected = _nearest_unique_candidate(candidates, target_page=note_item.page_no)
            if selected is not None:
                used_anchor_ids.add(selected.anchor_id)
                _append_link(
                    chapter_id=chapter_id,
                    region_id=note_item.region_id,
                    note_item_id=note_item.note_item_id,
                    anchor_id=selected.anchor_id,
                    status="matched",
                    resolver="repair",
                    confidence=max(0.0, min(1.0, float(selected.certainty))),
                    note_kind="endnote",
                    marker=marker,
                    page_no_start=note_item.page_no,
                    page_no_end=note_item.page_no,
                )
                continue
            _append_link(
                chapter_id=chapter_id,
                region_id=note_item.region_id,
                note_item_id=note_item.note_item_id,
                anchor_id="",
                status="ambiguous",
                resolver="rule",
                confidence=0.0,
                note_kind="endnote",
                marker=marker,
                page_no_start=note_item.page_no,
                page_no_end=note_item.page_no,
            )
            continue
        _append_link(
            chapter_id=chapter_id,
            region_id=note_item.region_id,
            note_item_id=note_item.note_item_id,
            anchor_id="",
            status="orphan_note",
            resolver="rule",
            confidence=0.0,
            note_kind="endnote",
            marker=marker,
            page_no_start=note_item.page_no,
            page_no_end=note_item.page_no,
        )
        orphan_endnote_link_indexes.append(len(links) - 1)

    # endnote orphan repair
    for index in orphan_endnote_link_indexes:
        link = links[index]
        if link.status != "orphan_note" or link.note_kind != "endnote":
            continue
        candidates = _candidate_anchors(
            anchors,
            chapter_id=link.chapter_id,
            marker=link.marker,
            expected_kinds={"endnote", "unknown"},
            used_anchor_ids=used_anchor_ids,
            include_synthetic=False,
        )
        if len(candidates) == 1:
            selected = candidates[0]
            used_anchor_ids.add(selected.anchor_id)
            links[index] = replace(
                link,
                anchor_id=selected.anchor_id,
                status="matched",
                resolver="repair",
                confidence=max(0.0, min(1.0, float(selected.certainty))),
            )
        elif len(candidates) > 1:
            links[index] = replace(
                link,
                status="ambiguous",
                resolver="repair",
            )

    # ── 阶段4：orphan endnote 直接正文搜索恢复 ──
    remaining_orphans = [
        {
            "index": idx,
            "link": links[idx],
            "marker": links[idx].marker,
            "chapter_id": links[idx].chapter_id,
            "note_item_id": links[idx].note_item_id,
        }
        for idx in orphan_endnote_link_indexes
        if links[idx].status == "orphan_note"
        and links[idx].note_kind == "endnote"
        and links[idx].marker
    ]
    if remaining_orphans:
        chapter_body_pages: dict[str, set[int]] = {}
        for anchor in anchors:
            cid = str(anchor.chapter_id or "")
            if cid and int(anchor.page_no or 0) > 0:
                chapter_body_pages.setdefault(cid, set()).add(int(anchor.page_no))
        for orphan in remaining_orphans:
            cid = orphan["chapter_id"]
            if cid not in chapter_body_pages:
                # fallback: get pages from existing anchors in same chapter
                chapter_body_pages[cid] = {
                    int(a.page_no or 0) for a in anchors
                    if str(a.chapter_id or "") == cid and int(a.page_no or 0) > 0
                }
        enriched = [
            {**orphan, "page_nos": sorted(chapter_body_pages.get(orphan["chapter_id"], set()))}
            for orphan in remaining_orphans
        ]
        recovered = _build_orphan_recovery_anchors(enriched, pages)
        for rec in recovered:
            anchors.append(rec)
            used_anchor_ids.add(rec.anchor_id)
            # Update matching orphan link
            for orphan in remaining_orphans:
                if orphan["note_item_id"] == rec.anchor_id.replace("orphan-recovery-", ""):
                    idx = orphan["index"]
                    links[idx] = replace(
                        links[idx],
                        anchor_id=rec.anchor_id,
                        status="matched",
                        resolver="orphan_recovery",
                        confidence=0.7,
                    )
                    break

    # footnote_resolver
    for note_item in note_items_sorted:
        region = regions_by_id.get(str(note_item.region_id or "")) or {}
        note_kind = str(getattr(region, "note_kind", "") or "")
        if note_kind != "footnote":
            continue
        marker = normalize_note_marker(note_item.marker)
        chapter_id = str(note_item.chapter_id or getattr(region, "chapter_id", "") or "")
        chapter_mode = str(mode_by_chapter.get(chapter_id) or "")
        if not marker:
            _append_link(
                chapter_id=chapter_id,
                region_id=note_item.region_id,
                note_item_id=note_item.note_item_id,
                anchor_id="",
                status="ignored",
                resolver="rule",
                confidence=0.0,
                note_kind="footnote",
                marker="",
                page_no_start=note_item.page_no,
                page_no_end=note_item.page_no,
            )
            continue
        candidates = _candidate_anchors(
            anchors,
            chapter_id=chapter_id,
            marker=marker,
            expected_kinds={"footnote"},
            used_anchor_ids=used_anchor_ids,
            page_no=note_item.page_no,
            footnote_window=True,
            include_synthetic=False,
        )
        if len(candidates) == 1:
            selected = candidates[0]
            used_anchor_ids.add(selected.anchor_id)
            _append_link(
                chapter_id=chapter_id,
                region_id=note_item.region_id,
                note_item_id=note_item.note_item_id,
                anchor_id=selected.anchor_id,
                status="matched",
                resolver="rule",
                confidence=max(0.0, min(1.0, float(selected.certainty))),
                note_kind="footnote",
                marker=marker,
                page_no_start=note_item.page_no,
                page_no_end=note_item.page_no,
            )
            continue
        if len(candidates) > 1:
            selected = _nearest_unique_candidate(candidates, target_page=note_item.page_no)
            if selected is not None:
                used_anchor_ids.add(selected.anchor_id)
                _append_link(
                    chapter_id=chapter_id,
                    region_id=note_item.region_id,
                    note_item_id=note_item.note_item_id,
                    anchor_id=selected.anchor_id,
                    status="matched",
                    resolver="repair",
                    confidence=max(0.0, min(1.0, float(selected.certainty))),
                    note_kind="footnote",
                    marker=marker,
                    page_no_start=note_item.page_no,
                    page_no_end=note_item.page_no,
                )
                continue
            _append_link(
                chapter_id=chapter_id,
                region_id=note_item.region_id,
                note_item_id=note_item.note_item_id,
                anchor_id="",
                status="ambiguous",
                resolver="rule",
                confidence=0.0,
                note_kind="footnote",
                marker=marker,
                page_no_start=note_item.page_no,
                page_no_end=note_item.page_no,
            )
            continue

        repair_candidates: list[BodyAnchorRecord] = []
        for anchor in anchors:
            if anchor.chapter_id != chapter_id or anchor.synthetic or anchor.anchor_id in used_anchor_ids:
                continue
            if not _within_footnote_window(anchor.page_no, note_item.page_no):
                continue
            if anchor.anchor_kind not in {"footnote", "unknown"}:
                continue
            if len(normalize_note_marker(anchor.normalized_marker)) >= len(marker):
                continue
            if _marker_digits_are_ordered_subsequence(anchor.normalized_marker, marker):
                repair_candidates.append(anchor)
        repair_candidates.sort(key=lambda row: (abs(int(row.page_no) - int(note_item.page_no)), int(row.paragraph_index), int(row.char_start)))
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
                chapter_id=chapter_id,
                region_id=note_item.region_id,
                note_item_id=note_item.note_item_id,
                anchor_id=selected.anchor_id,
                status="matched",
                resolver="repair",
                confidence=1.0,
                note_kind="footnote",
                marker=marker,
                page_no_start=note_item.page_no,
                page_no_end=note_item.page_no,
            )
            continue

        allow_synthetic = chapter_mode in {"footnote_primary", "review_required"}
        if allow_synthetic:
            synthetic_anchor = _make_synthetic_anchor(
                serial=synthetic_serial,
                chapter_id=chapter_id,
                page_no=note_item.page_no,
                marker=marker,
                source_text=note_item.text,
            )
            synthetic_serial += 1
            synthetic_added_count += 1
            anchors.append(synthetic_anchor)
            used_anchor_ids.add(synthetic_anchor.anchor_id)
            _append_link(
                chapter_id=chapter_id,
                region_id=note_item.region_id,
                note_item_id=note_item.note_item_id,
                anchor_id=synthetic_anchor.anchor_id,
                status="matched",
                resolver="fallback",
                confidence=0.4,
                note_kind="footnote",
                marker=marker,
                page_no_start=note_item.page_no,
                page_no_end=note_item.page_no,
            )
            continue

        _append_link(
            chapter_id=chapter_id,
            region_id=note_item.region_id,
            note_item_id=note_item.note_item_id,
            anchor_id="",
            status="orphan_note",
            resolver="rule",
            confidence=0.0,
            note_kind="footnote",
            marker=marker,
            page_no_start=note_item.page_no,
            page_no_end=note_item.page_no,
        )

    # synthetic 替换为同页显式 anchor
    for index, link in enumerate(links):
        if link.note_kind != "footnote" or link.status != "matched":
            continue
        if not link.anchor_id.startswith("synthetic-footnote-"):
            continue
        explicit_candidates = _candidate_anchors(
            anchors,
            chapter_id=link.chapter_id,
            marker=link.marker,
            expected_kinds={"footnote", "unknown"},
            used_anchor_ids=used_anchor_ids,
            page_no=link.page_no_start,
            footnote_window=True,
            include_synthetic=False,
        )
        if len(explicit_candidates) != 1:
            continue
        selected = explicit_candidates[0]
        used_anchor_ids.add(selected.anchor_id)
        links[index] = replace(
            link,
            anchor_id=selected.anchor_id,
            resolver="repair",
            confidence=max(0.0, min(1.0, float(selected.certainty))),
        )

    # orphan_anchor links（仅显式 anchors）
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
        (
            str(row.chapter_id or ""),
            str(row.note_kind or ""),
            normalize_note_marker(row.marker),
        )
        for row in links
        if row.status == "matched" and normalize_note_marker(row.marker)
    }
    for anchor in anchors:
        if anchor.synthetic:
            continue
        normalized_marker = normalize_note_marker(anchor.normalized_marker)
        if not normalized_marker:
            continue
        if anchor.anchor_id in used_anchor_ids:
            continue
        inferred_kind = _infer_note_kind_from_anchor(anchor, mode_by_chapter=mode_by_chapter)
        if (
            str(anchor.chapter_id or ""),
            inferred_kind,
            normalized_marker,
        ) in matched_marker_keys:
            continue
        if (
            str(anchor.chapter_id or ""),
            inferred_kind,
            normalized_marker,
        ) in note_item_marker_keys:
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
            chapter_id=anchor.chapter_id,
            region_id="",
            note_item_id="",
            anchor_id=anchor.anchor_id,
            status="orphan_anchor",
            resolver="rule",
            confidence=0.0,
            note_kind=inferred_kind,
            marker=normalized_marker,
            page_no_start=anchor.page_no,
            page_no_end=anchor.page_no,
        )

    links.sort(key=lambda row: row.link_id)
    anchors.sort(key=lambda row: (int(row.page_no), int(row.paragraph_index), int(row.char_start), row.anchor_id))

    note_link_summary = {
        "matched": sum(1 for row in links if row.status == "matched"),
        "footnote_orphan_note": sum(1 for row in links if row.note_kind == "footnote" and row.status == "orphan_note"),
        "footnote_orphan_anchor": sum(1 for row in links if row.note_kind == "footnote" and row.status == "orphan_anchor"),
        "endnote_orphan_note": sum(1 for row in links if row.note_kind == "endnote" and row.status == "orphan_note"),
        "endnote_orphan_anchor": sum(1 for row in links if row.note_kind == "endnote" and row.status == "orphan_anchor"),
        "ambiguous": sum(1 for row in links if row.status == "ambiguous"),
        "ignored": sum(1 for row in links if row.status == "ignored"),
        "fallback_count": sum(1 for row in links if row.resolver == "fallback"),
        "repair_count": sum(1 for row in links if row.resolver == "repair"),
    }
    review_seed_summary = {
        "boundary_review_required_count": sum(1 for row in phase2.chapter_note_modes if row.note_mode == "review_required"),
        "uncertain_anchor_ids": [
            row.anchor_id
            for row in anchors
            if row.anchor_kind == "unknown" or float(row.certainty) < 1.0
        ],
        "orphan_link_ids": [
            row.link_id
            for row in links
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

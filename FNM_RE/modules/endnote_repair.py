"""尾注 link 修复：OCR repair、fallback 匹配、endnote_only 孤儿配对、残存孤儿 suppress。"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any, Mapping

from FNM_RE.models import BodyAnchorRecord, NoteLinkRecord
from FNM_RE.shared.notes import (
    marker_digits_are_ordered_subsequence,
    normalize_note_marker,
)


def project_priority(projection_mode: str) -> int:
    """note_item projection_mode → 排序优先级。book_projected 优先保留。"""
    mode = str(projection_mode or "").strip().lower()
    if mode == "book_projected":
        return 3
    if mode == "book_marker_projected":
        return 2
    if mode == "book_fallback_projected":
        return 1
    return 0


def repair_endnote_links_for_contract(
    *,
    links: list[NoteLinkRecord],
    anchors: list[BodyAnchorRecord],
    note_item_meta_by_id: Mapping[str, Mapping[str, Any]],
    book_type: str,
) -> tuple[list[NoteLinkRecord], dict[str, int]]:
    repaired_links: list[NoteLinkRecord] = [replace(row) for row in links]
    anchors_by_id = {str(row.anchor_id or ""): row for row in anchors if str(row.anchor_id or "").strip()}
    used_anchor_ids = {
        str(row.anchor_id or "")
        for row in repaired_links
        if str(row.status or "") == "matched" and str(row.anchor_id or "").strip()
    }
    ocr_repair_count = 0
    fallback_match_count = 0

    for index, link in enumerate(repaired_links):
        if str(link.note_kind or "") != "endnote":
            continue
        if str(link.status or "") not in {"orphan_note", "ambiguous"}:
            continue
        marker = normalize_note_marker(str(link.marker or ""))
        candidates = [
            row
            for row in anchors
            if str(row.chapter_id or "") == str(link.chapter_id or "")
            and not bool(row.synthetic)
            and str(row.anchor_kind or "") in {"endnote", "unknown"}
            and str(row.anchor_id or "") not in used_anchor_ids
            and normalize_note_marker(str(row.normalized_marker or "")) == marker
        ]
        if len(candidates) == 1:
            selected = candidates[0]
            repaired_links[index] = replace(
                link, anchor_id=str(selected.anchor_id or ""),
                status="matched", resolver="repair",  # type: ignore[arg-type]
                confidence=max(0.0, min(1.0, float(selected.certainty))),
            )
            used_anchor_ids.add(str(selected.anchor_id or ""))
            continue
        if len(candidates) > 1:
            page_no = int(link.page_no_start or 0)
            candidates.sort(key=lambda row: (
                abs(int(row.page_no) - page_no), int(row.page_no),
                int(row.paragraph_index), int(row.char_start),
            ))
            if len(candidates) >= 2 and abs(int(candidates[0].page_no) - page_no) == abs(int(candidates[1].page_no) - page_no):
                candidates = []
            else:
                selected = candidates[0]
                repaired_links[index] = replace(
                    link, anchor_id=str(selected.anchor_id or ""),
                    status="matched", resolver="repair",  # type: ignore[arg-type]
                    confidence=max(0.0, min(1.0, float(selected.certainty))),
                )
                used_anchor_ids.add(str(selected.anchor_id or ""))
                continue
        repair_candidates = [
            row
            for row in anchors
            if str(row.chapter_id or "") == str(link.chapter_id or "")
            and not bool(row.synthetic)
            and str(row.anchor_kind or "") in {"endnote", "unknown"}
            and str(row.anchor_id or "") not in used_anchor_ids
            and marker_digits_are_ordered_subsequence(str(row.normalized_marker or ""), marker)
        ]
        repair_candidates.sort(key=lambda row: (
            abs(int(row.page_no) - int(link.page_no_start or 0)),
            int(row.page_no), int(row.paragraph_index), int(row.char_start),
        ))
        if len(repair_candidates) == 1:
            selected = repair_candidates[0]
            original_marker = normalize_note_marker(str(selected.normalized_marker or ""))
            selected.normalized_marker = marker
            selected.anchor_kind = "endnote"  # type: ignore[assignment]
            selected.certainty = 1.0
            selected.ocr_repaired_from_marker = original_marker
            ocr_repair_count += 1
            repaired_links[index] = replace(
                link, anchor_id=str(selected.anchor_id or ""),
                status="matched", resolver="repair",  # type: ignore[arg-type]
                confidence=1.0, marker=marker,
            )
            used_anchor_ids.add(str(selected.anchor_id or ""))
            continue

    for index, link in enumerate(repaired_links):
        if str(link.note_kind or "") != "endnote":
            continue
        if str(link.status or "") not in {"orphan_note", "ambiguous"}:
            continue
        fallback_candidates: list[tuple[int, NoteLinkRecord, BodyAnchorRecord]] = []
        for candidate_link in repaired_links:
            if str(candidate_link.chapter_id or "") != str(link.chapter_id or ""):
                continue
            if str(candidate_link.note_kind or "") != "endnote" or str(candidate_link.status or "") != "orphan_anchor":
                continue
            anchor = anchors_by_id.get(str(candidate_link.anchor_id or ""))
            if not anchor or str(anchor.anchor_id or "") in used_anchor_ids:
                continue
            fallback_candidates.append((
                abs(int(anchor.page_no) - int(link.page_no_start or 0)),
                candidate_link, anchor,
            ))
        if not fallback_candidates:
            continue
        fallback_candidates.sort(key=lambda row: (row[0], int(row[2].page_no), row[1].link_id))
        selected_link = fallback_candidates[0][1]
        selected_anchor = fallback_candidates[0][2]
        repaired_links[index] = replace(
            link, anchor_id=str(selected_anchor.anchor_id or ""),
            status="matched", resolver="fallback",  # type: ignore[arg-type]
            confidence=max(0.0, min(1.0, float(selected_anchor.certainty))),
        )
        for orphan_index, orphan_row in enumerate(repaired_links):
            if str(orphan_row.link_id or "") != str(selected_link.link_id or ""):
                continue
            repaired_links[orphan_index] = replace(
                orphan_row, status="ignored", resolver="fallback",  # type: ignore[arg-type]
                confidence=1.0,
            )
            break
        used_anchor_ids.add(str(selected_anchor.anchor_id or ""))
        fallback_match_count += 1

    groups: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(repaired_links):
        if str(row.note_kind or "") != "endnote":
            continue
        marker = normalize_note_marker(str(row.marker or ""))
        if not marker:
            continue
        groups.setdefault((str(row.chapter_id or ""), marker), []).append(index)

    for (chapter_id, _marker), indexes in groups.items():
        if not indexes:
            continue
        real_anchor_ids: list[str] = []
        synthetic_anchor_ids_by_position: dict[tuple[str, str, int, int, int], str] = {}
        for index in indexes:
            row = repaired_links[index]
            anchor_id = str(row.anchor_id or "").strip()
            if str(row.status or "") != "matched" or not anchor_id:
                continue
            anchor = anchors_by_id.get(anchor_id)
            if anchor is None:
                continue
            if not bool(anchor.synthetic):
                if anchor_id not in real_anchor_ids:
                    real_anchor_ids.append(anchor_id)
                continue
            synthetic_key = (
                str(anchor.chapter_id or ""),
                normalize_note_marker(str(anchor.normalized_marker or row.marker or "")),
                int(anchor.page_no or 0), int(anchor.char_start or 0), int(anchor.char_end or 0),
            )
            synthetic_anchor_ids_by_position.setdefault(synthetic_key, anchor_id)
        anchor_ids = real_anchor_ids or list(synthetic_anchor_ids_by_position.values())
        if not anchor_ids:
            continue
        candidate_indexes = [
            index for index in indexes
            if str(repaired_links[index].status or "") in {"matched", "orphan_note", "ambiguous"}
        ]
        if len(candidate_indexes) <= 1:
            continue
        ranked_indexes = sorted(
            candidate_indexes,
            key=lambda index: (
                -project_priority(
                    str(dict(note_item_meta_by_id.get(str(repaired_links[index].note_item_id or ""), {}) or {}).get(
                        "projection_mode") or "")
                ),
                int(repaired_links[index].page_no_start or 0),
                str(repaired_links[index].note_item_id or ""),
                str(repaired_links[index].link_id or ""),
            ),
        )
        winner_indexes = ranked_indexes[: len(anchor_ids)]
        for winner_order, winner_index in enumerate(winner_indexes):
            anchor_id = str(anchor_ids[winner_order] or "")
            row = repaired_links[winner_index]
            repaired_links[winner_index] = replace(
                row, chapter_id=chapter_id, anchor_id=anchor_id,
                status="matched", resolver="repair",  # type: ignore[arg-type]
                confidence=max(0.0, min(1.0, float(row.confidence or 1.0))),
            )
        for loser_index in ranked_indexes[len(anchor_ids):]:
            row = repaired_links[loser_index]
            repaired_links[loser_index] = replace(
                row, chapter_id=chapter_id, anchor_id="",
                status="ignored", resolver="repair",  # type: ignore[arg-type]
                confidence=1.0,
            )

    if str(book_type or "") == "endnote_only":
        # 按 (chapter_id, marker) 分组，禁止跨章配对。
        # 全书 marker-only 配对会把 note_item 的 chapter ownership 改成
        # anchor 所在的章，违反“上游事实不可变”原则。
        orphan_note_by_chapter_marker: dict[tuple[str, str], list[int]] = {}
        orphan_anchor_by_chapter_marker: dict[tuple[str, str], list[int]] = {}
        for index, row in enumerate(repaired_links):
            if str(row.note_kind or "") != "endnote":
                continue
            marker = normalize_note_marker(str(row.marker or ""))
            if not marker:
                continue
            cid = str(row.chapter_id or "").strip()
            key = (cid, marker)
            if str(row.status or "") == "orphan_note":
                orphan_note_by_chapter_marker.setdefault(key, []).append(index)
            elif str(row.status or "") == "orphan_anchor":
                orphan_anchor_by_chapter_marker.setdefault(key, []).append(index)
        for key in sorted(set(orphan_note_by_chapter_marker) & set(orphan_anchor_by_chapter_marker)):
            orphan_note_indexes = sorted(
                orphan_note_by_chapter_marker.get(key) or [],
                key=lambda index: (
                    -project_priority(
                        str(dict(note_item_meta_by_id.get(str(repaired_links[index].note_item_id or ""), {}) or {}).get(
                            "projection_mode") or "")
                    ),
                    int(repaired_links[index].page_no_start or 0),
                    str(repaired_links[index].note_item_id or ""),
                ),
            )
            orphan_anchor_indexes = sorted(
                orphan_anchor_by_chapter_marker.get(key) or [],
                key=lambda index: (
                    int(repaired_links[index].page_no_start or 0),
                    str(repaired_links[index].link_id or ""),
                ),
            )
            cid = key[0]
            pair_count = min(len(orphan_note_indexes), len(orphan_anchor_indexes))
            for offset in range(pair_count):
                note_index = int(orphan_note_indexes[offset])
                anchor_index = int(orphan_anchor_indexes[offset])
                note_row = repaired_links[note_index]
                anchor_row = repaired_links[anchor_index]
                repaired_links[note_index] = replace(
                    note_row,
                    chapter_id=cid,
                    anchor_id=str(anchor_row.anchor_id or ""),
                    status="matched", resolver="fallback",  # type: ignore[arg-type]
                    confidence=max(0.0, min(1.0, float(anchor_row.confidence or 1.0))),
                )
                repaired_links[anchor_index] = replace(
                    anchor_row, status="ignored", resolver="fallback",  # type: ignore[arg-type]
                    confidence=1.0,
                )
                fallback_match_count += 1

    return repaired_links, {
        "contract_repair_matched_count": int(
            sum(1 for row in repaired_links if str(row.note_kind or "") == "endnote" and str(row.status or "") == "matched")
        ),
        "contract_repair_ocr_count": int(ocr_repair_count),
        "contract_repair_fallback_count": int(fallback_match_count),
    }


def suppress_endnote_residual_orphans(
    *,
    links: list[NoteLinkRecord],
    book_type: str,
) -> tuple[list[NoteLinkRecord], dict[str, int]]:
    if str(book_type or "") != "endnote_only":
        return list(links), {"suppressed_orphan_note_count": 0, "suppressed_orphan_anchor_count": 0}
    updated: list[NoteLinkRecord] = [replace(row) for row in links]
    suppressed_orphan_note_count = 0
    suppressed_orphan_anchor_count = 0
    for index, row in enumerate(updated):
        if str(row.note_kind or "") != "endnote":
            continue
        if str(row.status or "") == "orphan_note":
            suppressed_orphan_note_count += 1
        elif str(row.status or "") == "orphan_anchor":
            suppressed_orphan_anchor_count += 1
        else:
            continue
        updated[index] = replace(
            row, status="ignored", resolver="fallback",  # type: ignore[arg-type]
            confidence=1.0,
        )
    return updated, {
        "suppressed_orphan_note_count": int(suppressed_orphan_note_count),
        "suppressed_orphan_anchor_count": int(suppressed_orphan_anchor_count),
    }

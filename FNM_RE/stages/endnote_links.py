"""尾注 link 匹配：anchor → note_item 配对、orphan repair、正文搜索恢复。"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from FNM_RE.models import BodyAnchorRecord, NoteLinkRecord
from FNM_RE.shared.notes import normalize_note_marker
from FNM_RE.stages._link_utils import (
    _is_fallback_chapter_id,
    link_candidate_anchors,
    link_new_link,
)


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
    escaped = re.escape(marker)
    patterns = [
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
                "matched_text": m.group(0),
                "source_text": body_text[max(0, m.start()-30):min(len(body_text), m.end()+30)],
            }
    return None


def _build_orphan_recovery_anchors(
    orphans: list[dict],
    pages: list[dict],
) -> list[BodyAnchorRecord]:
    page_text: dict[int, str] = {}
    body_page_nos: set[int] = set()
    for p in pages:
        pno = int(p.get("bookPage") or p.get("pdfPage") or 0)
        if pno <= 0:
            continue
        role = str(p.get("page_role") or "").strip()
        if role and role != "body":
            continue
        body_page_nos.add(pno)
        md = str(p.get("enriched_markdown") or p.get("markdown") or "").strip()
        if md:
            page_text[pno] = md

    recovered: list[BodyAnchorRecord] = []
    for orphan in orphans:
        marker = orphan["marker"]
        chapter_id = orphan["chapter_id"]
        note_item_id = orphan["note_item_id"]
        page_nos = sorted(orphan.get("page_nos") or [])
        if not marker:
            continue
        found = False
        for pno in page_nos:
            if pno not in body_page_nos:
                continue
            body_text = page_text.get(pno, "")
            if not body_text:
                continue
            hit = _find_marker_in_body(body_text, marker)
            if not hit:
                continue
            recovered.append(
                BodyAnchorRecord(
                    anchor_id=f"orphan-recovery-{note_item_id}",
                    chapter_id=chapter_id,
                    page_no=pno,
                    paragraph_index=0,
                    char_start=hit["start"],
                    char_end=hit["end"],
                    source_marker=hit.get("matched_text", marker),
                    normalized_marker=marker,
                    anchor_kind="endnote",
                    certainty=0.7,
                    source_text=hit["source_text"],
                    source="orphan_recovery",
                    synthetic=True,
                    ocr_repaired_from_marker="",
                )
            )
            found = True
            break
        if not found and page_nos:
            combined = "\n".join(
                page_text.get(pno, "") for pno in page_nos if page_text.get(pno, "")
            )
            if combined:
                hit = _find_marker_in_body(combined, marker)
                if hit:
                    recovered.append(
                        BodyAnchorRecord(
                            anchor_id=f"orphan-recovery-{note_item_id}",
                            chapter_id=chapter_id,
                            page_no=page_nos[0],
                            paragraph_index=0,
                            char_start=hit["start"],
                            char_end=hit["end"],
                            source_marker=hit.get("matched_text", marker),
                            normalized_marker=marker,
                            anchor_kind="endnote",
                            certainty=0.5,
                            source_text=hit["source_text"],
                            source="orphan_recovery",
                            synthetic=True,
                            ocr_repaired_from_marker="",
                        )
                    )
    return recovered


def build_endnote_links(
    anchors: list[BodyAnchorRecord],
    phase2_note_items: list[Any],
    regions_by_id: dict[str, Any],
    used_anchor_ids: set[str],
    anchor_count_by_chapter: dict[str, int],
    *,
    pages: list[dict],
    link_serial_start: int = 1,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[list[NoteLinkRecord], list[int]]:
    links: list[NoteLinkRecord] = []
    link_serial = link_serial_start
    orphan_endnote_link_indexes: list[int] = []

    def _append_link(**kwargs: Any) -> None:
        nonlocal link_serial
        links.append(link_new_link(serial=link_serial, **kwargs))
        link_serial += 1

    # --- endnote_resolver: 逐 item 匹配 anchor ---
    for note_item in phase2_note_items:
        region = regions_by_id.get(str(note_item.region_id or "")) or {}
        note_kind = str(getattr(region, "note_kind", "") or "")
        if note_kind != "endnote":
            continue
        marker = normalize_note_marker(note_item.marker)
        chapter_id = str(note_item.chapter_id or getattr(region, "chapter_id", "") or "")
        scope = str(getattr(region, "scope", "") or "")
        if not marker:
            _append_link(
                chapter_id=chapter_id, region_id=note_item.region_id,
                note_item_id=note_item.note_item_id, anchor_id="",
                status="ignored", resolver="rule", confidence=0.0,
                note_kind="endnote", marker="",
                page_no_start=note_item.page_no, page_no_end=note_item.page_no,
            )
            continue
        candidates = link_candidate_anchors(
            anchors, chapter_id=chapter_id, marker=marker,
            expected_kinds={"endnote"},
            used_anchor_ids=used_anchor_ids,
            page_no=note_item.page_no, include_synthetic=False,
        )
        is_direct_match = bool(candidates)
        if not candidates and chapter_id and _is_fallback_chapter_id(chapter_id):
            if int(anchor_count_by_chapter.get(chapter_id, 0) or 0) == 0:
                candidates = link_candidate_anchors(
                    anchors, chapter_id=chapter_id, marker=marker,
                    expected_kinds={"endnote"},
                    used_anchor_ids=used_anchor_ids,
                    page_no=note_item.page_no, include_synthetic=False,
                    allow_cross_chapter=True,
                )
        if not candidates:
            candidates = link_candidate_anchors(
                anchors, chapter_id=chapter_id, marker=marker,
                expected_kinds={"endnote"}, used_anchor_ids=used_anchor_ids,
                page_no=note_item.page_no, include_synthetic=True,
                allow_cross_chapter=False,
            )
        if not candidates and scope == "book" and chapter_id:
            candidates = link_candidate_anchors(
                anchors, chapter_id=chapter_id, marker=marker,
                expected_kinds={"endnote"},
                used_anchor_ids=used_anchor_ids,
                page_no=note_item.page_no, include_synthetic=False,
            )
        if len(candidates) == 1:
            selected = candidates[0]
            used_anchor_ids.add(selected.anchor_id)
            _append_link(
                chapter_id=chapter_id, region_id=note_item.region_id,
                note_item_id=note_item.note_item_id, anchor_id=selected.anchor_id,
                status="matched",
                resolver="rule" if is_direct_match else "fallback",
                confidence=max(0.0, min(1.0, float(selected.certainty))),
                note_kind="endnote", marker=marker,
                page_no_start=note_item.page_no, page_no_end=note_item.page_no,
            )
            continue
        if len(candidates) > 1:
            candidates.sort(key=lambda row: (int(row.page_no), int(row.paragraph_index), int(row.char_start)))
            selected = candidates[0]
            used_anchor_ids.add(selected.anchor_id)
            _append_link(
                chapter_id=chapter_id, region_id=note_item.region_id,
                note_item_id=note_item.note_item_id, anchor_id=selected.anchor_id,
                status="matched", resolver="repair",
                confidence=max(0.0, min(1.0, float(selected.certainty))),
                note_kind="endnote", marker=marker,
                page_no_start=note_item.page_no, page_no_end=note_item.page_no,
            )
            continue
        _append_link(
            chapter_id=chapter_id, region_id=note_item.region_id,
            note_item_id=note_item.note_item_id, anchor_id="",
            status="orphan_note", resolver="rule", confidence=0.0,
            note_kind="endnote", marker=marker,
            page_no_start=note_item.page_no, page_no_end=note_item.page_no,
        )
        orphan_endnote_link_indexes.append(len(links) - 1)

    # --- endnote orphan repair: 同章内搜索未用 anchor ---
    for index in orphan_endnote_link_indexes[:]:
        link = links[index]
        if link.status != "orphan_note" or link.note_kind != "endnote":
            continue
        candidates = link_candidate_anchors(
            anchors, chapter_id=link.chapter_id, marker=link.marker,
            expected_kinds={"endnote"},
            used_anchor_ids=used_anchor_ids, include_synthetic=False,
        )
        if len(candidates) == 1:
            selected = candidates[0]
            used_anchor_ids.add(selected.anchor_id)
            links[index] = replace(link, anchor_id=selected.anchor_id,
                                   status="matched", resolver="repair",
                                   confidence=max(0.0, min(1.0, float(selected.certainty))))
        elif len(candidates) > 1:
            candidates.sort(key=lambda row: (int(row.page_no), int(row.paragraph_index), int(row.char_start)))
            selected = candidates[0]
            used_anchor_ids.add(selected.anchor_id)
            links[index] = replace(link, anchor_id=selected.anchor_id,
                                   status="matched", resolver="repair",
                                   confidence=max(0.0, min(1.0, float(selected.certainty))))

    # --- orphan endnote 正文搜索恢复 ---
    remaining_orphans = [
        {"index": idx, "link": links[idx], "marker": links[idx].marker,
         "chapter_id": links[idx].chapter_id, "note_item_id": links[idx].note_item_id}
        for idx in orphan_endnote_link_indexes
        if links[idx].status == "orphan_note"
        and links[idx].note_kind == "endnote"
        and links[idx].marker
    ]
    if remaining_orphans:
        chapter_body_pages: dict[str, set[int]] = {}
        for a in anchors:
            cid = str(a.chapter_id or "")
            if cid and int(a.page_no or 0) > 0:
                chapter_body_pages.setdefault(cid, set()).add(int(a.page_no))
        for orphan in remaining_orphans:
            cid = orphan["chapter_id"]
            if cid not in chapter_body_pages:
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
            for orphan in remaining_orphans:
                if orphan["note_item_id"] == rec.anchor_id.replace("orphan-recovery-", ""):
                    idx = orphan["index"]
                    links[idx] = replace(links[idx], anchor_id=rec.anchor_id,
                                         status="matched", resolver="orphan_recovery",
                                         confidence=0.7)
                    break

    return links, orphan_endnote_link_indexes

"""原始 marker → note_id 序列构建工具。

从 stages/export.py 提取，供 export.py 和 export_footnote.py 共用。
"""

from __future__ import annotations

from FNM_RE.models import BodyAnchorRecord, NoteItemRecord, NoteLinkRecord
from FNM_RE.shared.ref_rewriter import _marker_aliases, _resolve_note_id


def _build_raw_marker_note_sequences(
    chapter_id: str,
    *,
    matched_links: list[NoteLinkRecord],
    note_items_by_id: dict[str, NoteItemRecord],
    body_anchors_by_id: dict[str, BodyAnchorRecord],
    note_text_by_id: dict[str, str],
) -> dict[str, list[str]]:
    def _anchor_sort_key(anchor_id: str) -> tuple[int, int, int]:
        anchor = body_anchors_by_id.get(str(anchor_id or "").strip())
        if not anchor:
            return (0, 0, 0)
        return (
            int(anchor.page_no or 0),
            int(anchor.paragraph_index or 0),
            int(anchor.char_start or 0),
        )

    chapter_links = [
        link
        for link in matched_links
        if str(link.status or "") == "matched"
        and str(link.chapter_id or "") == str(chapter_id or "")
        and str(link.note_item_id or "").strip()
        and str(link.anchor_id or "").strip()
    ]
    chapter_links.sort(
        key=lambda link: (
            *_anchor_sort_key(str(link.anchor_id or "")),
            str(link.link_id or ""),
        )
    )
    sequences: dict[str, list[str]] = {}
    for link in chapter_links:
        note_item_id = str(link.note_item_id or "").strip()
        note_id = _resolve_note_id(note_item_id, note_text_by_id)
        if not note_id:
            continue
        anchor = body_anchors_by_id.get(str(link.anchor_id or "").strip())
        if anchor and bool(anchor.synthetic):
            continue
        note_item = note_items_by_id.get(note_item_id)
        marker_candidates: set[str] = set()
        marker_candidates.update(_marker_aliases(note_id))
        marker_candidates.update(_marker_aliases(str(link.marker or "")))
        if note_item:
            marker_candidates.update(_marker_aliases(str(note_item.marker or "")))
        if anchor:
            marker_candidates.update(_marker_aliases(str(anchor.normalized_marker or "")))
            marker_candidates.update(_marker_aliases(str(anchor.source_marker or "")))
            marker_candidates.update(_marker_aliases(str(anchor.ocr_repaired_from_marker or "")))
        for marker in marker_candidates:
            row = sequences.setdefault(marker, [])
            row.append(note_id)
    chapter_items = sorted(
        [
            item
            for item in note_items_by_id.values()
            if str(item.chapter_id or "") == str(chapter_id or "")
        ],
        key=lambda item: (int(item.page_no or 0), str(item.note_item_id or "")),
    )
    for item in chapter_items:
        note_item_id = str(item.note_item_id or "").strip()
        note_id = _resolve_note_id(note_item_id, note_text_by_id)
        if not note_id:
            continue
        marker_candidates: set[str] = set()
        marker_candidates.update(_marker_aliases(note_id))
        marker_candidates.update(_marker_aliases(str(item.marker or "")))
        for marker in marker_candidates:
            row = sequences.setdefault(marker, [])
            if note_id not in row:
                row.append(note_id)
    if sequences:
        return sequences

    fallback_note_ids = {
        _resolve_note_id(str(item.note_item_id or "").strip(), note_text_by_id)
        for item in note_items_by_id.values()
        if str(item.chapter_id or "") == str(chapter_id or "")
    }
    fallback_note_ids.discard("")
    if len(fallback_note_ids) != 1:
        return sequences
    fallback_note_id = next(iter(fallback_note_ids))
    for item in note_items_by_id.values():
        if str(item.chapter_id or "") != str(chapter_id or ""):
            continue
        for marker in _marker_aliases(str(item.marker or "")):
            row = sequences.setdefault(marker, [])
            if fallback_note_id not in row:
                row.append(fallback_note_id)
    return sequences

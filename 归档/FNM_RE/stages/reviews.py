"""FNM_RE 第四阶段：结构复核生成。"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from FNM_RE.models import NoteLinkRecord, Phase3Structure, StructureReviewRecord

_REVIEW_TYPE_WHITELIST = {
    "boundary_review_required",
    "uncertain_anchor",
    "footnote_orphan_note",
    "footnote_orphan_anchor",
    "endnote_orphan_note",
    "endnote_orphan_anchor",
    "ambiguous",
    "toc_alignment_review_required",
    "toc_semantic_review_required",
}
_WARNING_REVIEW_TYPES = {"ambiguous", "uncertain_anchor"}
_REVIEW_ID_SANITIZE_RE = re.compile(r"[^0-9a-zA-Z]+")


def _sanitize_review_token(value: Any) -> str:
    token = _REVIEW_ID_SANITIZE_RE.sub("-", str(value or "").strip())
    token = token.strip("-")
    return token or "na"


def _make_review_id(
    *,
    review_type: str,
    chapter_id: str,
    page_start: int,
    page_end: int,
    target_id: str,
) -> str:
    return (
        f"review-"
        f"{_sanitize_review_token(review_type)}-"
        f"{_sanitize_review_token(chapter_id)}-"
        f"{int(page_start)}-{int(page_end)}-"
        f"{_sanitize_review_token(target_id)}"
    )


def _append_review(
    rows: list[StructureReviewRecord],
    *,
    review_type: str,
    chapter_id: str,
    page_start: int,
    page_end: int,
    payload: dict[str, Any],
) -> None:
    if review_type not in _REVIEW_TYPE_WHITELIST:
        return
    target_id = (
        str(payload.get("anchor_id") or payload.get("note_item_id") or payload.get("link_id") or "")
        or f"{page_start}-{page_end}"
    )
    severity = "warning" if review_type in _WARNING_REVIEW_TYPES else "error"
    rows.append(
        StructureReviewRecord(
            review_id=_make_review_id(
                review_type=review_type,
                chapter_id=chapter_id,
                page_start=page_start,
                page_end=page_end,
                target_id=target_id,
            ),
            review_type=review_type,
            chapter_id=chapter_id,
            page_start=int(page_start),
            page_end=int(page_end),
            severity=severity,
            payload=dict(payload or {}),
        )
    )


def build_structure_reviews(
    phase3: Phase3Structure,
    *,
    effective_note_links: list[NoteLinkRecord],
    ignored_link_override_count: int = 0,
    invalid_override_count: int = 0,
) -> tuple[list[StructureReviewRecord], dict]:
    reviews: list[StructureReviewRecord] = []

    for chapter in phase3.chapters:
        if str(chapter.boundary_state or "") != "review_required":
            continue
        _append_review(
            reviews,
            review_type="boundary_review_required",
            chapter_id=str(chapter.chapter_id or ""),
            page_start=int(chapter.start_page or 0),
            page_end=int(chapter.end_page or int(chapter.start_page or 0)),
            payload={"reason": "chapter_boundary_conflict"},
        )

    for anchor in phase3.body_anchors:
        if str(anchor.anchor_kind or "") != "unknown" and float(anchor.certainty or 1.0) >= 1.0:
            continue
        _append_review(
            reviews,
            review_type="uncertain_anchor",
            chapter_id=str(anchor.chapter_id or ""),
            page_start=int(anchor.page_no or 0),
            page_end=int(anchor.page_no or 0),
            payload={
                "anchor_id": str(anchor.anchor_id or ""),
                "marker": str(anchor.normalized_marker or ""),
                "certainty": float(anchor.certainty or 0.0),
                "synthetic": bool(anchor.synthetic),
            },
        )

    for link in effective_note_links or []:
        status = str(link.status or "")
        if status == "ignored":
            continue
        if status == "orphan_note":
            if str(link.note_kind or "") == "footnote":
                review_type = "footnote_orphan_note"
            elif str(link.note_kind or "") == "endnote":
                review_type = "endnote_orphan_note"
            else:
                continue
        elif status == "orphan_anchor":
            if str(link.note_kind or "") == "footnote":
                review_type = "footnote_orphan_anchor"
            elif str(link.note_kind or "") == "endnote":
                review_type = "endnote_orphan_anchor"
            else:
                continue
        elif status == "ambiguous":
            review_type = "ambiguous"
        else:
            continue
        _append_review(
            reviews,
            review_type=review_type,
            chapter_id=str(link.chapter_id or ""),
            page_start=int(link.page_no_start or 0),
            page_end=int(link.page_no_end or int(link.page_no_start or 0)),
            payload={
                "link_id": str(link.link_id or ""),
                "note_item_id": str(link.note_item_id or ""),
                "anchor_id": str(link.anchor_id or ""),
                "note_kind": str(link.note_kind or ""),
                "marker": str(link.marker or ""),
            },
        )

    chapter_title_alignment_ok = bool(getattr(phase3.summary, "chapter_title_alignment_ok", True))
    chapter_section_alignment_ok = bool(getattr(phase3.summary, "chapter_section_alignment_ok", True))
    if not chapter_title_alignment_ok or not chapter_section_alignment_ok:
        _append_review(
            reviews,
            review_type="toc_alignment_review_required",
            chapter_id="",
            page_start=0,
            page_end=0,
            payload={
                "chapter_title_alignment_ok": chapter_title_alignment_ok,
                "chapter_section_alignment_ok": chapter_section_alignment_ok,
                "toc_alignment_summary": dict(getattr(phase3.summary, "toc_alignment_summary", {}) or {}),
            },
        )

    toc_semantic_contract_ok = bool(getattr(phase3.summary, "toc_semantic_contract_ok", True))
    if not toc_semantic_contract_ok:
        _append_review(
            reviews,
            review_type="toc_semantic_review_required",
            chapter_id="",
            page_start=0,
            page_end=0,
            payload={
                "toc_semantic_contract_ok": toc_semantic_contract_ok,
                "toc_semantic_summary": dict(getattr(phase3.summary, "toc_semantic_summary", {}) or {}),
                "toc_semantic_blocking_reasons": list(
                    getattr(phase3.summary, "toc_semantic_blocking_reasons", []) or []
                ),
            },
        )

    deduped: list[StructureReviewRecord] = []
    seen_ids: set[str] = set()
    for review in reviews:
        if review.review_id in seen_ids:
            continue
        seen_ids.add(review.review_id)
        deduped.append(review)
    deduped.sort(key=lambda row: (row.review_type, row.chapter_id, int(row.page_start), int(row.page_end), row.review_id))

    review_type_counts = Counter(row.review_type for row in deduped)
    summary = {
        "review_type_counts": dict(review_type_counts),
        "error_count": sum(1 for row in deduped if row.severity == "error"),
        "warning_count": sum(1 for row in deduped if row.severity == "warning"),
        "ignored_link_override_count": int(ignored_link_override_count),
        "invalid_override_count": int(invalid_override_count),
    }
    return deduped, summary


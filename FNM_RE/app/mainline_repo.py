"""FNM_RE 仓库记录转换层。

从 mainline.py 提取的 DB 记录与 Record 类型互转函数。
"""

from __future__ import annotations

import json
from typing import Any

from FNM_RE.models import (
    BodyAnchorRecord,
    ChapterNoteModeRecord,
    ChapterRecord,
    NoteItemRecord,
    NoteLinkRecord,
    NoteRegionRecord,
    SectionHeadRecord,
    StructureReviewRecord,
    TranslationUnitRecord,
    UnitPageSegmentRecord,
    UnitParagraphRecord,
)

_EMPTY_ROLE_SUMMARY = {
    "container": 0,
    "chapter": 0,
    "section": 0,
    "post_body": 0,
    "back_matter": 0,
    "front_matter": 0,
}
_EXPORT_VALIDATION_LOG_PATH = "logs/fnm_export_validation_issues.log"
_EXPORT_STAGE_REASON_PREFIXES = ("merge_", "export_")
_EXPORT_STAGE_REASON_EXACT = {"local_note_contract_broken"}
_MISSING_PERSISTED_EXPORT_BUNDLE_MESSAGE = "FNM 导出包不存在，请先执行最终校验。"


def _normalize_unit_id(unit_id: str, doc_id: str) -> str:
    raw = str(unit_id or "").strip()
    prefix = f"{doc_id}-"
    return raw[len(prefix):] if raw.startswith(prefix) else raw


def _paragraph_record_from_payload(payload: dict[str, Any]) -> UnitParagraphRecord:
    return UnitParagraphRecord(
        order=int(payload.get("order") or 0),
        kind=str(payload.get("kind") or "body"),
        heading_level=int(payload.get("heading_level") or 0),
        source_text=str(payload.get("source_text") or ""),
        display_text=str(payload.get("display_text") or payload.get("source_text") or ""),
        cross_page=payload.get("cross_page"),
        consumed_by_prev=bool(payload.get("consumed_by_prev")),
        section_path=list(payload.get("section_path") or []),
        print_page_label=str(payload.get("print_page_label") or ""),
        translated_text=str(payload.get("translated_text") or ""),
        translation_status=str(payload.get("translation_status") or payload.get("status") or "pending"),
        attempt_count=int(payload.get("attempt_count") or 0),
        last_error=str(payload.get("last_error") or ""),
        manual_resolved=bool(payload.get("manual_resolved")),
    )


def _segment_record_from_payload(payload: dict[str, Any]) -> UnitPageSegmentRecord:
    paragraphs = [
        _paragraph_record_from_payload(dict(row))
        for row in list(payload.get("paragraphs") or [])
        if isinstance(row, dict)
    ]
    return UnitPageSegmentRecord(
        page_no=int(payload.get("page_no") or 0),
        paragraph_count=int(payload.get("paragraph_count") or len(paragraphs)),
        source_text=str(payload.get("source_text") or ""),
        display_text=str(payload.get("display_text") or payload.get("source_text") or ""),
        paragraphs=paragraphs,
    )


def _repo_chapter_record(row: dict[str, Any]) -> ChapterRecord | None:
    chapter_id = str(row.get("chapter_id") or "").strip()
    if not chapter_id:
        return None
    pages = []
    for page_no in list(row.get("pages") or []):
        try:
            parsed = int(page_no)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            pages.append(parsed)
    start_page = int(row.get("start_page") or 0)
    end_page = int(row.get("end_page") or 0)
    if not pages and start_page > 0 and end_page >= start_page:
        pages = list(range(start_page, end_page + 1))
    return ChapterRecord(
        chapter_id=chapter_id,
        title=str(row.get("title") or chapter_id),
        start_page=start_page,
        end_page=end_page,
        pages=pages,
        source=str(row.get("source") or "repo"),
        boundary_state=str(row.get("boundary_state") or "ready"),
    )


def _repo_section_head_record(row: dict[str, Any]) -> SectionHeadRecord | None:
    section_head_id = str(row.get("section_head_id") or "").strip()
    if not section_head_id:
        return None
    return SectionHeadRecord(
        section_head_id=section_head_id,
        chapter_id=str(row.get("chapter_id") or ""),
        title=str(row.get("text") or ""),
        page_no=int(row.get("page_no") or 0),
        level=1,
        source=str(row.get("source") or "repo"),
    )


def _repo_note_region_record(row: dict[str, Any]) -> NoteRegionRecord | None:
    region_id = str(row.get("region_id") or "").strip()
    if not region_id:
        return None
    pages = []
    for page_no in list(row.get("pages") or []):
        try:
            parsed = int(page_no)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            pages.append(parsed)
    region_kind = str(row.get("region_kind") or "").strip().lower()
    return NoteRegionRecord(
        region_id=region_id,
        chapter_id=str(row.get("bound_chapter_id") or ""),
        page_start=int(row.get("start_page") or 0),
        page_end=int(row.get("end_page") or 0),
        pages=pages,
        note_kind="endnote" if "endnote" in region_kind else "footnote",
        scope="book" if region_kind.startswith("book_") else "chapter",
        source=str(row.get("source") or "repo"),
        heading_text=str(row.get("title_hint") or ""),
        start_reason="repo_fallback",
        end_reason="repo_fallback",
        region_marker_alignment_ok=bool(row.get("region_marker_alignment_ok", True)),
        region_start_first_source_marker=str(row.get("region_start_first_source_marker") or ""),
        region_first_note_item_marker=str(row.get("region_first_note_item_marker") or ""),
        review_required=False,
    )


def _repo_note_item_record(row: dict[str, Any]) -> NoteItemRecord | None:
    note_item_id = str(row.get("note_item_id") or "").strip()
    if not note_item_id:
        return None
    return NoteItemRecord(
        note_item_id=note_item_id,
        region_id=str(row.get("region_id") or ""),
        chapter_id=str(row.get("chapter_id") or ""),
        page_no=int(row.get("page_no") or 0),
        marker=str(row.get("marker") or ""),
        marker_type="numeric",
        text=str(row.get("source_text") or ""),
        source="repo",
        source_page_label=str(row.get("display_marker") or row.get("source_marker") or ""),
        is_reconstructed=False,
        review_required=False,
    )


def _repo_chapter_note_mode_record(row: dict[str, Any]) -> ChapterNoteModeRecord | None:
    chapter_id = str(row.get("chapter_id") or "").strip()
    if not chapter_id:
        return None
    note_mode = str(row.get("note_mode") or "mixed_or_unclear")
    return ChapterNoteModeRecord(
        chapter_id=chapter_id,
        note_mode=note_mode,
        region_ids=[],
        primary_region_scope="",
        has_footnote_band=note_mode == "footnote_primary",
        has_endnote_region="endnote" in note_mode,
    )


def _repo_body_anchor_record(row: dict[str, Any]) -> BodyAnchorRecord | None:
    anchor_id = str(row.get("anchor_id") or "").strip()
    if not anchor_id:
        return None
    return BodyAnchorRecord(
        anchor_id=anchor_id,
        chapter_id=str(row.get("chapter_id") or ""),
        page_no=int(row.get("page_no") or 0),
        paragraph_index=int(row.get("paragraph_index") or 0),
        char_start=int(row.get("char_start") or 0),
        char_end=int(row.get("char_end") or 0),
        source_marker=str(row.get("source_marker") or ""),
        normalized_marker=str(row.get("normalized_marker") or ""),
        anchor_kind=str(row.get("anchor_kind") or "inline"),
        certainty=float(row.get("certainty") or 0.0),
        source_text=str(row.get("source_text") or ""),
        source=str(row.get("source") or "repo"),
        synthetic=bool(row.get("synthetic")),
        ocr_repaired_from_marker=str(row.get("ocr_repaired_from_marker") or ""),
    )


def _repo_note_link_record(row: dict[str, Any]) -> NoteLinkRecord | None:
    link_id = str(row.get("link_id") or "").strip()
    if not link_id:
        return None
    return NoteLinkRecord(
        link_id=link_id,
        chapter_id=str(row.get("chapter_id") or ""),
        region_id=str(row.get("region_id") or ""),
        note_item_id=str(row.get("note_item_id") or ""),
        anchor_id=str(row.get("anchor_id") or ""),
        status=str(row.get("status") or "pending"),
        resolver=str(row.get("resolver") or "repo"),
        confidence=float(row.get("confidence") or 0.0),
        note_kind=str(row.get("note_kind") or ""),
        marker=str(row.get("marker") or ""),
        page_no_start=int(row.get("page_no_start") or 0),
        page_no_end=int(row.get("page_no_end") or 0),
    )


def _repo_structure_review_record(index: int, row: dict[str, Any]) -> StructureReviewRecord:
    review_id = str(row.get("review_id") or row.get("id") or f"repo-review-{index}")
    page_range = row.get("page_range") or [0, 0]
    if not isinstance(page_range, (list, tuple)):
        page_range = [0, 0]
    page_start = int(page_range[0] or 0) if len(page_range) > 0 else 0
    page_end = int(page_range[1] or 0) if len(page_range) > 1 else 0
    return StructureReviewRecord(
        review_id=review_id,
        review_type=str(row.get("review_type") or ""),
        chapter_id=str(row.get("chapter_id") or ""),
        page_start=page_start,
        page_end=page_end,
        severity=str(row.get("severity") or "warning"),
        payload=dict(row.get("payload_json") or {}),
    )


def _serialize_structure_reviews(rows: list[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for review in rows:
        row = _to_plain(review)
        payload.append(
            {
                "review_type": str(row.get("review_type") or ""),
                "chapter_id": str(row.get("chapter_id") or ""),
                "page_range": [row.get("page_start"), row.get("page_end")],
                "payload_json": dict(row.get("payload") or {}),
                "severity": str(row.get("severity") or "warning"),
            }
        )
    return payload


def _serialize_units_for_repo(doc_id: str, rows: list[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for raw_row in rows:
        row = _to_plain(raw_row)
        unit_id = str(row.get("unit_id") or "").strip()
        if unit_id and not unit_id.startswith(f"{doc_id}-"):
            row["unit_id"] = f"{doc_id}-{unit_id}"
        owner_kind = str(row.get("owner_kind") or "").strip().lower()
        if not owner_kind:
            row["owner_kind"] = "chapter" if str(row.get("kind") or "") == "body" else "note_region"
        owner_id = str(row.get("owner_id") or "").strip()
        if not owner_id:
            row["owner_id"] = str(row.get("section_id") or "").strip()
        payload.append(row)
    return payload


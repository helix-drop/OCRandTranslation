"""FNM_RE 持久化辅助函数：产物对象 → repo row 序列化 + TOC 加载。

从 `FNM_RE/app/mainline.py` 抽出来，给 mainline 和 dev phase_runner 共用。
"""
from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any

from persistence.storage_toc import (
    load_auto_visual_toc_bundle_from_disk,
    load_auto_visual_toc_from_disk,
)


def to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: to_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    return value


def normalize_marker(text: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text or "").strip().lower())


def _safe_list(callable_obj: Any, *args) -> list[Any]:
    if not callable(callable_obj):
        return []
    value = callable_obj(*args)
    return list(value or [])


def load_fnm_toc_items(doc_id: str, repo: Any) -> tuple[list[dict], int]:
    """从 repo（按 source 优先级）或磁盘加载 TOC items 与 offset。

    顺序：
      1. `get_document_toc_for_source(doc_id, "auto_visual")`
      2. `get_document_toc_for_source(doc_id, "auto_pdf")`
      3. `get_document_toc(doc_id)`
      4. `load_auto_visual_toc_from_disk(doc_id)`
    """
    get_document_toc_for_source = getattr(repo, "get_document_toc_for_source", None)
    get_document_toc_source_offset = getattr(repo, "get_document_toc_source_offset", None)
    get_document_toc = getattr(repo, "get_document_toc", None)

    for source in ("auto_visual", "auto_pdf"):
        items = _safe_list(get_document_toc_for_source, doc_id, source)
        if not items:
            continue
        offset = 0
        if callable(get_document_toc_source_offset):
            current_source, current_offset = get_document_toc_source_offset(doc_id)
            if str(current_source or "").strip() == source:
                offset = int(current_offset or 0)
        return items, int(offset)

    items = _safe_list(get_document_toc, doc_id)
    if items:
        offset = 0
        if callable(get_document_toc_source_offset):
            _current_source, current_offset = get_document_toc_source_offset(doc_id)
            offset = int(current_offset or 0)
        return items, int(offset)

    visual_items = list(load_auto_visual_toc_from_disk(doc_id) or [])
    if visual_items:
        offset = 0
        if callable(get_document_toc_source_offset):
            _current_source, current_offset = get_document_toc_source_offset(doc_id)
            offset = int(current_offset or 0)
        return visual_items, int(offset)
    return [], 0


def load_fnm_visual_toc_bundle(doc_id: str) -> dict[str, Any]:
    payload = load_auto_visual_toc_bundle_from_disk(doc_id)
    return dict(payload) if isinstance(payload, dict) else {}


# ---------- 序列化 ----------

def serialize_pages_for_repo(rows: list[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for raw_row in rows:
        row = to_plain(raw_row)
        payload.append(
            {
                "page_no": int(row.get("page_no") or 0),
                "target_pdf_page": int(row.get("target_pdf_page") or 0),
                "page_role": str(row.get("page_role") or "other"),
                "role_confidence": float(row.get("confidence", 0.0) or 0.0),
                "role_reason": str(row.get("reason") or ""),
                "section_hint": str(row.get("section_hint") or ""),
                "has_note_heading": bool(row.get("has_note_heading")),
                "note_scan_summary": dict(row.get("note_scan_summary") or {}),
            }
        )
    return payload


def serialize_heading_candidates_for_repo(rows: list[Any]) -> list[dict[str, Any]]:
    allowed_family = {"book", "chapter", "section", "note", "other", "unknown"}
    allowed_font_weight = {"regular", "bold", "heavy", "unknown"}
    allowed_align = {"left", "center", "right", "unknown"}
    payload: list[dict[str, Any]] = []
    for raw_row in rows:
        row = to_plain(raw_row)
        family_guess = str(row.get("heading_family_guess") or "").strip().lower()
        family_alias = {
            "front_matter": "book",
            "back_matter": "other",
        }
        family_guess = family_alias.get(family_guess, family_guess)
        if family_guess not in allowed_family:
            family_guess = "unknown"
        font_weight_hint = str(row.get("font_weight_hint") or "").strip().lower() or "unknown"
        if font_weight_hint not in allowed_font_weight:
            font_weight_hint = "unknown"
        align_hint = str(row.get("align_hint") or "").strip().lower() or "unknown"
        if align_hint not in allowed_align:
            align_hint = "unknown"
        payload.append(
            {
                "heading_id": str(row.get("heading_id") or ""),
                "page_no": int(row.get("page_no") or 0),
                "text": str(row.get("text") or ""),
                "normalized_text": str(row.get("normalized_text") or ""),
                "source": str(row.get("source") or ""),
                "block_label": str(row.get("block_label") or ""),
                "top_band": bool(row.get("top_band")),
                "font_height": float(row.get("font_height")) if row.get("font_height") is not None else None,
                "x": float(row.get("x")) if row.get("x") is not None else None,
                "y": float(row.get("y")) if row.get("y") is not None else None,
                "width_estimate": float(row.get("width_estimate")) if row.get("width_estimate") is not None else None,
                "font_name": str(row.get("font_name") or ""),
                "font_weight_hint": font_weight_hint,
                "align_hint": align_hint,
                "width_ratio": float(row.get("width_ratio")) if row.get("width_ratio") is not None else None,
                "heading_level_hint": int(row.get("heading_level_hint") or 0),
                "confidence": float(row.get("confidence", 0.0) or 0.0),
                "heading_family_guess": family_guess,
                "suppressed_as_chapter": bool(row.get("suppressed_as_chapter")),
                "reject_reason": str(row.get("reject_reason") or ""),
            }
        )
    return payload


def region_kind_from_row(row: dict[str, Any]) -> str:
    note_kind = str(row.get("note_kind") or "").strip().lower()
    scope = str(row.get("scope") or "").strip().lower()
    if note_kind == "footnote":
        return "footnote"
    if note_kind == "endnote":
        if scope == "chapter":
            return "chapter_endnotes"
        if scope == "book":
            return "book_endnotes"
        return "endnote"
    return note_kind or "footnote"


def serialize_note_regions_for_repo(rows: list[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for raw_row in rows:
        row = to_plain(raw_row)
        payload.append(
            {
                "region_id": str(row.get("region_id") or ""),
                "region_kind": region_kind_from_row(row),
                "start_page": int(row.get("page_start") or 0),
                "end_page": int(row.get("page_end") or int(row.get("page_start") or 0)),
                "pages": list(row.get("pages") or []),
                "title_hint": str(row.get("heading_text") or ""),
                "bound_chapter_id": str(row.get("chapter_id") or ""),
                "region_start_first_source_marker": str(row.get("region_start_first_source_marker") or ""),
                "region_first_note_item_marker": str(row.get("region_first_note_item_marker") or ""),
                "region_marker_alignment_ok": bool(row.get("region_marker_alignment_ok")),
            }
        )
    return payload


def serialize_chapter_note_modes_for_repo(
    rows: list[Any],
    *,
    chapter_title_by_id: dict[str, str],
    region_pages_by_id: dict[str, list[int]],
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    mode_alias = {
        "chapter_endnote_primary": "chapter_endnotes",
        "book_endnote_bound": "book_endnotes",
        "no_notes": "body_only",
    }
    for raw_row in rows:
        row = to_plain(raw_row)
        chapter_id = str(row.get("chapter_id") or "")
        sampled_pages: list[int] = []
        for region_id in list(row.get("region_ids") or []):
            sampled_pages.extend(region_pages_by_id.get(str(region_id), []))
        sampled_pages = sorted({int(page_no) for page_no in sampled_pages if int(page_no) > 0})
        note_mode = str(row.get("note_mode") or "")
        payload.append(
            {
                "chapter_id": chapter_id,
                "chapter_title": str(chapter_title_by_id.get(chapter_id) or chapter_id),
                "note_mode": mode_alias.get(note_mode, note_mode),
                "sampled_pages": sampled_pages,
                "detection_confidence": 1.0,
            }
        )
    return payload


def serialize_section_heads_for_repo(rows: list[Any]) -> list[dict[str, Any]]:
    allowed_sources = {"visual_toc", "ocr_block", "pdf_font_band", "markdown_heading", "note_heading"}
    payload: list[dict[str, Any]] = []
    for raw_row in rows:
        row = to_plain(raw_row)
        text = str(row.get("title") or "").strip()
        source = str(row.get("source") or "").strip()
        if source not in allowed_sources:
            source = "markdown_heading"
        payload.append(
            {
                "section_head_id": str(row.get("section_head_id") or ""),
                "chapter_id": str(row.get("chapter_id") or ""),
                "page_no": int(row.get("page_no") or 0),
                "text": text,
                "normalized_text": re.sub(r"\s+", " ", text).strip().lower(),
                "source": source,
                "confidence": 1.0,
                "heading_family_guess": "section",
                "rejected_chapter_candidate": False,
                "reject_reason": "",
                "derived_from_heading_id": "",
            }
        )
    return payload


def serialize_note_items_for_repo(
    rows: list[Any],
    *,
    note_kind_by_region_id: dict[str, str],
    title_hint_by_region_id: dict[str, str],
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    marker_occurrence: dict[tuple[str, str, str], int] = {}
    for raw_row in rows:
        row = to_plain(raw_row)
        chapter_id = str(row.get("chapter_id") or "")
        region_id = str(row.get("region_id") or "")
        marker = str(row.get("marker") or "").strip()
        note_kind = str(note_kind_by_region_id.get(region_id) or row.get("marker_type") or "footnote")
        occurrence_key = (chapter_id, note_kind, normalize_marker(marker))
        marker_occurrence[occurrence_key] = int(marker_occurrence.get(occurrence_key, 0) or 0) + 1
        payload.append(
            {
                "note_item_id": str(row.get("note_item_id") or ""),
                "note_kind": note_kind,
                "chapter_id": chapter_id,
                "region_id": region_id,
                "marker": marker,
                "normalized_marker": normalize_marker(marker),
                "occurrence": int(marker_occurrence[occurrence_key]),
                "source_text": str(row.get("text") or ""),
                "page_no": int(row.get("page_no") or 0),
                "display_marker": marker,
                "source_marker": marker,
                "title_hint": str(title_hint_by_region_id.get(region_id) or ""),
            }
        )
    return payload

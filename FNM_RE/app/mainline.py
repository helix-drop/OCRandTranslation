"""FNM_RE 第七阶段：doc/repo-aware 主线接线层。"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from FNM_RE.app.pipeline import build_module_pipeline_snapshot
from FNM_RE.constants import is_valid_pipeline_state
from FNM_RE.models import (
    BodyAnchorRecord,
    ChapterNoteModeRecord,
    ChapterRecord,
    NoteItemRecord,
    NoteLinkRecord,
    NoteRegionRecord,
    Phase4Structure,
    Phase5Structure,
    Phase6Structure,
    Phase6Summary,
    SectionHeadRecord,
    StructureReviewRecord,
    StructureStatusRecord,
    TranslationUnitRecord,
    UnitPageSegmentRecord,
    UnitParagraphRecord,
)
from FNM_RE.app.persist_helpers import (
    load_fnm_visual_toc_bundle as _load_fnm_visual_toc_bundle,
    load_fnm_toc_items as _load_fnm_toc_items,
    normalize_marker as _normalize_marker,
    serialize_chapter_note_modes_for_repo as _serialize_chapter_note_modes_for_repo,
    serialize_heading_candidates_for_repo as _serialize_heading_candidates_for_repo,
    serialize_note_items_for_repo as _serialize_note_items_for_repo,
    serialize_note_regions_for_repo as _serialize_note_regions_for_repo,
    serialize_pages_for_repo as _serialize_pages_for_repo,
    serialize_section_heads_for_repo as _serialize_section_heads_for_repo,
    to_plain as _to_plain,
)
from FNM_RE.stages.diagnostics import build_diagnostic_projection
from FNM_RE.stages.export import build_export_zip
from FNM_RE.stages.export_audit import audit_phase6_export
from persistence.sqlite_store import SQLiteRepository
from persistence.storage import get_pdf_path, get_translate_args
from persistence.storage_toc import load_toc_visual_manual_inputs

_EMPTY_ROLE_SUMMARY = {
    "container": 0,
    "chapter": 0,
    "section": 0,
    "post_body": 0,
    "back_matter": 0,
    "front_matter": 0,
}


def _safe_list(callable_obj: Any, *args) -> list[Any]:
    if not callable(callable_obj):
        return []
    value = callable_obj(*args)
    return list(value or [])


def _safe_dict(callable_obj: Any, *args) -> dict[str, Any]:
    if not callable(callable_obj):
        return {}
    value = callable_obj(*args)
    if not isinstance(value, dict):
        return {}
    return dict(value)


def _safe_json_loads(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _group_review_overrides(rows: list[dict] | None) -> dict[str, dict[str, dict]]:
    grouped: dict[str, dict[str, dict]] = {
        "page": {},
        "chapter": {},
        "region": {},
        "link": {},
        "llm_suggestion": {},
        "anchor": {},
        "note_item": {},
    }
    for row in rows or []:
        scope = str((row or {}).get("scope") or "").strip().lower()
        target_id = str((row or {}).get("target_id") or "").strip()
        if not scope or not target_id:
            continue
        grouped.setdefault(scope, {})[target_id] = dict((row or {}).get("payload") or {})
    return grouped


def _resolve_manual_toc_state(doc_id: str) -> tuple[bool, dict[str, Any]]:
    inputs = load_toc_visual_manual_inputs(doc_id) if doc_id else {}
    mode = str((inputs or {}).get("mode") or "").strip().lower()
    pdf_path = str((inputs or {}).get("pdf_path") or "").strip()
    image_paths = [
        str(path or "").strip()
        for path in (inputs or {}).get("image_paths") or []
        if str(path or "").strip()
    ]
    page_count = int((inputs or {}).get("page_count") or 0)
    if page_count <= 0:
        if mode == "manual_pdf" and pdf_path:
            page_count = 1
        elif mode == "manual_images":
            page_count = len(image_paths)
    source_name = str((inputs or {}).get("source_name") or "").strip()
    manual_toc_ready = False
    if mode == "manual_pdf":
        manual_toc_ready = bool(pdf_path and page_count > 0)
    elif mode == "manual_images":
        manual_toc_ready = bool(image_paths)
    summary = {
        "mode": mode,
        "page_count": int(max(0, page_count)),
        "file_count": 1 if mode == "manual_pdf" and pdf_path else len(image_paths),
        "image_count": len(image_paths),
        "source_name": source_name,
    }
    return manual_toc_ready, summary


def _summarize_book_audit(
    *,
    slug: str,
    doc_id: str,
    zip_path: str,
    structure_state: str,
    blocking_reasons: list[str],
    manual_toc_summary: dict[str, Any],
    toc_role_summary: dict[str, Any],
    chapter_titles: list[str],
    file_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    now = int(time.time())
    blocking_files = [row for row in file_reports if str(row.get("severity") or "") == "blocking"]
    major_files = [row for row in file_reports if str(row.get("severity") or "") == "major"]
    issue_counts: dict[str, int] = {}
    for row in file_reports:
        for code in list(row.get("issue_codes") or []):
            token = str(code or "").strip()
            if not token:
                continue
            issue_counts[token] = issue_counts.get(token, 0) + 1
    recommended_followups = [
        {"issue_code": code, "count": count}
        for code, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]
    return {
        "slug": str(slug or "").strip(),
        "doc_id": str(doc_id or "").strip(),
        "zip_path": str(zip_path or "").strip(),
        "audit_started_at": now,
        "audit_finished_at": now,
        "structure_state": str(structure_state or "").strip(),
        "blocking_reasons": [str(item).strip() for item in (blocking_reasons or []) if str(item).strip()],
        "manual_toc_summary": dict(manual_toc_summary or {}),
        "toc_role_summary": dict(toc_role_summary or {}),
        "chapter_titles": list(chapter_titles or []),
        "files": file_reports,
        "blocking_issue_count": len(blocking_files),
        "major_issue_count": len(major_files),
        "can_ship": len(blocking_files) == 0,
        "must_fix_before_next_book": [
            {
                "path": str(row.get("path") or ""),
                "issue_codes": list(row.get("issue_codes") or []),
            }
            for row in blocking_files
        ],
        "recommended_followups": recommended_followups,
    }


def _infer_max_body_chars(model_key: str) -> int:
    lowered = str(model_key or "").strip().lower()
    if lowered.startswith("qwen-"):
        return 24000
    if lowered.startswith("deepseek-"):
        return 18000
    return 12000


def _effective_max_body_chars(explicit_value: int | None) -> int:
    if explicit_value is not None:
        return max(2000, int(explicit_value))
    model_key = str(get_translate_args().get("model_key") or "")
    return _infer_max_body_chars(model_key)


def _phase_state_from_run(run: dict[str, Any]) -> str:
    if not run:
        return "idle"
    status = str(run.get("status") or "").strip().lower()
    if status in {"pending", "running"}:
        return "running"
    if status == "error":
        return "error"
    return "done"


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


def _overlay_repo_structure_if_needed(phase5: Phase5Structure, *, doc_id: str, repo: SQLiteRepository) -> None:
    need_chapters = not bool(phase5.chapters)
    need_note_items = not bool(phase5.note_items)
    if not need_chapters and not need_note_items:
        return

    if need_chapters:
        repo_chapters = [
            record
            for record in (
                _repo_chapter_record(dict(row))
                for row in _safe_list(getattr(repo, "list_fnm_chapters", None), doc_id)
                if isinstance(row, dict)
            )
            if record is not None
        ]
        if repo_chapters:
            phase5.chapters = repo_chapters

    if not phase5.section_heads:
        repo_section_heads = [
            record
            for record in (
                _repo_section_head_record(dict(row))
                for row in _safe_list(getattr(repo, "list_fnm_section_heads", None), doc_id)
                if isinstance(row, dict)
            )
            if record is not None
        ]
        if repo_section_heads:
            phase5.section_heads = repo_section_heads

    if not phase5.note_regions:
        repo_note_regions = [
            record
            for record in (
                _repo_note_region_record(dict(row))
                for row in _safe_list(getattr(repo, "list_fnm_note_regions", None), doc_id)
                if isinstance(row, dict)
            )
            if record is not None
        ]
        if repo_note_regions:
            phase5.note_regions = repo_note_regions

    if need_note_items:
        repo_note_items = [
            record
            for record in (
                _repo_note_item_record(dict(row))
                for row in _safe_list(getattr(repo, "list_fnm_note_items", None), doc_id)
                if isinstance(row, dict)
            )
            if record is not None
        ]
        if repo_note_items:
            phase5.note_items = repo_note_items

    if not phase5.chapter_note_modes:
        repo_note_modes = [
            record
            for record in (
                _repo_chapter_note_mode_record(dict(row))
                for row in _safe_list(getattr(repo, "list_fnm_chapter_note_modes", None), doc_id)
                if isinstance(row, dict)
            )
            if record is not None
        ]
        if repo_note_modes:
            phase5.chapter_note_modes = repo_note_modes

    if not phase5.body_anchors:
        repo_body_anchors = [
            record
            for record in (
                _repo_body_anchor_record(dict(row))
                for row in _safe_list(getattr(repo, "list_fnm_body_anchors", None), doc_id)
                if isinstance(row, dict)
            )
            if record is not None
        ]
        if repo_body_anchors:
            phase5.body_anchors = repo_body_anchors

    if not phase5.note_links:
        repo_note_links = [
            record
            for record in (
                _repo_note_link_record(dict(row))
                for row in _safe_list(getattr(repo, "list_fnm_note_links", None), doc_id)
                if isinstance(row, dict)
            )
            if record is not None
        ]
        if repo_note_links:
            phase5.note_links = repo_note_links
    if not phase5.effective_note_links and phase5.note_links:
        phase5.effective_note_links = list(phase5.note_links)

    if not phase5.structure_reviews:
        repo_structure_reviews = [
            _repo_structure_review_record(index, dict(row))
            for index, row in enumerate(
                _safe_list(getattr(repo, "list_fnm_structure_reviews", None), doc_id),
                start=1,
            )
            if isinstance(row, dict)
        ]
        if repo_structure_reviews:
            phase5.structure_reviews = repo_structure_reviews


def _overlay_repo_translation_units(phase5: Phase5Structure, *, doc_id: str, repo: SQLiteRepository, pages: list[dict]) -> None:
    repo_units = _safe_list(getattr(repo, "list_fnm_translation_units", None), doc_id)
    if not repo_units:
        return

    by_unit_id = {
        _normalize_unit_id(str(row.get("unit_id") or ""), doc_id): dict(row)
        for row in repo_units
        if str(row.get("unit_id") or "").strip()
    }

    existing_unit_ids = {str(unit.unit_id or "").strip() for unit in phase5.translation_units}
    for normalized_unit_id, repo_unit in by_unit_id.items():
        if not normalized_unit_id or normalized_unit_id in existing_unit_ids:
            continue
        segment_payload = list(repo_unit.get("page_segments") or [])
        page_segments = [
            _segment_record_from_payload(dict(segment))
            for segment in segment_payload
            if isinstance(segment, dict)
        ]
        phase5.translation_units.append(
            TranslationUnitRecord(
                unit_id=normalized_unit_id,
                kind=str(repo_unit.get("kind") or ""),
                owner_kind=str(repo_unit.get("owner_kind") or ""),
                owner_id=str(repo_unit.get("owner_id") or ""),
                section_id=str(repo_unit.get("section_id") or ""),
                section_title=str(repo_unit.get("section_title") or ""),
                section_start_page=int(repo_unit.get("section_start_page") or 0),
                section_end_page=int(repo_unit.get("section_end_page") or 0),
                note_id=str(repo_unit.get("note_id") or ""),
                page_start=int(repo_unit.get("page_start") or 0),
                page_end=int(repo_unit.get("page_end") or 0),
                char_count=int(repo_unit.get("char_count") or 0),
                source_text=str(repo_unit.get("source_text") or ""),
                translated_text=str(repo_unit.get("translated_text") or ""),
                status=str(repo_unit.get("status") or "pending"),
                error_msg=str(repo_unit.get("error_msg") or ""),
                target_ref=str(repo_unit.get("target_ref") or ""),
                page_segments=page_segments,
            )
        )
        existing_unit_ids.add(normalized_unit_id)

    for unit in phase5.translation_units:
        repo_unit = by_unit_id.get(str(unit.unit_id or "").strip())
        if not repo_unit:
            continue
        unit.translated_text = str(repo_unit.get("translated_text") or "")
        unit.status = str(repo_unit.get("status") or unit.status or "pending")
        unit.error_msg = str(repo_unit.get("error_msg") or "")
        target_ref = str(repo_unit.get("target_ref") or "").strip()
        if target_ref:
            unit.target_ref = target_ref
        segment_payload = list(repo_unit.get("page_segments") or [])
        if segment_payload:
            unit.page_segments = [
                _segment_record_from_payload(dict(segment))
                for segment in segment_payload
                if isinstance(segment, dict)
            ]

    phase4_like = Phase4Structure(
        pages=phase5.pages,
        heading_candidates=phase5.heading_candidates,
        chapters=phase5.chapters,
        section_heads=phase5.section_heads,
        note_regions=phase5.note_regions,
        note_items=phase5.note_items,
        chapter_note_modes=phase5.chapter_note_modes,
        body_anchors=phase5.body_anchors,
        note_links=phase5.note_links,
        effective_note_links=phase5.effective_note_links,
        structure_reviews=phase5.structure_reviews,
        status=phase5.status,
    )
    diagnostic_pages, diagnostic_notes, diagnostic_summary = build_diagnostic_projection(
        phase4_like,
        phase5.translation_units,
        pages=pages,
        only_pages=None,
    )
    phase5.diagnostic_pages = diagnostic_pages
    phase5.diagnostic_notes = diagnostic_notes
    phase5.summary.diagnostic_page_summary = dict(diagnostic_summary.get("diagnostic_page_summary") or {})
    phase5.summary.diagnostic_note_summary = dict(diagnostic_summary.get("diagnostic_note_summary") or {})


def _apply_pipeline_state_override(status: StructureStatusRecord, *, pipeline_state: str) -> StructureStatusRecord:
    lowered = str(pipeline_state or "done").strip().lower()
    if not is_valid_pipeline_state(lowered):
        lowered = "done"
    if lowered == "done":
        return status
    if lowered == "idle":
        state = "idle"
    elif lowered == "running":
        state = "running"
    else:
        state = "error"
    return replace(
        status,
        structure_state=state,
        export_ready_test=False,
        export_ready_real=False,
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


def _export_bundle_payload(phase6: Phase6Structure) -> dict[str, Any]:
    bundle = phase6.export_bundle
    return {
        "index_path": str(bundle.index_path or "index.md"),
        "chapters_dir": str(bundle.chapters_dir or "chapters"),
        "chapters": [
            {
                "order": int(chapter.order or 0),
                "section_id": str(chapter.section_id or ""),
                "title": str(chapter.title or ""),
                "path": str(chapter.path or ""),
            }
            for chapter in bundle.chapters
        ],
        "chapter_files": dict(bundle.chapter_files or {}),
        "files": dict(bundle.files or {}),
        "export_semantic_contract_ok": bool(bundle.export_semantic_contract_ok),
        "front_matter_leak_detected": bool(bundle.front_matter_leak_detected),
        "toc_residue_detected": bool(bundle.toc_residue_detected),
        "mid_paragraph_heading_detected": bool(bundle.mid_paragraph_heading_detected),
        "duplicate_paragraph_detected": bool(bundle.duplicate_paragraph_detected),
    }


def _status_payload(
    *,
    status: StructureStatusRecord,
    summary: Phase6Summary,
    run_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_validation = dict(run_validation or {})
    summary_payload = dict(run_validation.get("summary") or {})
    toc_export_coverage_summary = dict(
        summary_payload.get("toc_export_coverage_summary")
        or run_validation.get("toc_export_coverage_summary")
        or {}
    )
    if toc_export_coverage_summary:
        toc_export_coverage_summary = {
            "resolved_body_items": int(toc_export_coverage_summary.get("resolved_body_items") or 0),
            "exported_body_items": int(toc_export_coverage_summary.get("exported_body_items") or 0),
            "missing_body_items_preview": list(toc_export_coverage_summary.get("missing_body_items_preview") or [])[:8],
        }

    return {
        "structure_state": str(status.structure_state or "idle"),
        "review_counts": dict(status.review_counts or {}),
        "blocking_reasons": list(status.blocking_reasons or []),
        "link_summary": dict(status.link_summary or {}),
        "page_partition_summary": dict(status.page_partition_summary or {}),
        "chapter_mode_summary": dict(status.chapter_mode_summary or {}),
        "heading_review_summary": dict(status.heading_review_summary or {}),
        "heading_graph_summary": dict(status.heading_graph_summary or {}),
        "chapter_source_summary": dict(status.chapter_source_summary or {}),
        "visual_toc_conflict_count": int(status.visual_toc_conflict_count or 0),
        "toc_export_coverage_summary": toc_export_coverage_summary,
        "toc_alignment_summary": dict(status.toc_alignment_summary or {}),
        "toc_semantic_summary": dict(status.toc_semantic_summary or {}),
        "toc_role_summary": dict(status.toc_role_summary or _EMPTY_ROLE_SUMMARY),
        "container_titles": list(status.container_titles or []),
        "post_body_titles": list(status.post_body_titles or []),
        "back_matter_titles": list(status.back_matter_titles or []),
        "toc_semantic_contract_ok": bool(status.toc_semantic_contract_ok),
        "toc_semantic_blocking_reasons": list(status.toc_semantic_blocking_reasons or []),
        "chapter_title_alignment_ok": bool(status.chapter_title_alignment_ok),
        "chapter_section_alignment_ok": bool(status.chapter_section_alignment_ok),
        "chapter_endnote_region_alignment_ok": bool(status.chapter_endnote_region_alignment_ok),
        "chapter_endnote_region_alignment_summary": dict(status.chapter_endnote_region_alignment_summary or {}),
        "export_drift_summary": dict(status.export_drift_summary or {}),
        "chapter_local_endnote_contract_ok": bool(status.chapter_local_endnote_contract_ok),
        "export_semantic_contract_ok": bool(status.export_semantic_contract_ok),
        "front_matter_leak_detected": bool(status.front_matter_leak_detected),
        "toc_residue_detected": bool(status.toc_residue_detected),
        "mid_paragraph_heading_detected": bool(status.mid_paragraph_heading_detected),
        "duplicate_paragraph_detected": bool(status.duplicate_paragraph_detected),
        "manual_toc_required": bool(status.manual_toc_required),
        "manual_toc_ready": bool(status.manual_toc_ready),
        "manual_toc_summary": dict(status.manual_toc_summary or {}),
        "chapter_progress_summary": dict(status.chapter_progress_summary or {}),
        "note_region_progress_summary": dict(status.note_region_progress_summary or {}),
        "chapter_binding_summary": dict(status.chapter_binding_summary or {}),
        "note_capture_summary": dict(status.note_capture_summary or {}),
        "footnote_synthesis_summary": dict(status.footnote_synthesis_summary or {}),
        "chapter_link_contract_summary": dict(status.chapter_link_contract_summary or {}),
        "book_endnote_stream_summary": dict(status.book_endnote_stream_summary or {}),
        "freeze_note_unit_summary": dict(status.freeze_note_unit_summary or {}),
        "chapter_issue_counts": dict(status.chapter_issue_counts or {}),
        "chapter_issue_summary": [dict(row or {}) for row in list(status.chapter_issue_summary or [])][:24],
        "page_count": int(status.page_count or 0),
        "chapter_count": int(status.chapter_count or 0),
        "section_head_count": int(status.section_head_count or 0),
        "review_count": int(status.review_count or 0),
        "export_ready_test": bool(status.export_ready_test),
        "export_ready_real": bool(status.export_ready_real),
        "summary": {
            "heading_review_summary": dict(summary.heading_review_summary or {}),
            "heading_graph_summary": dict(summary.heading_graph_summary or {}),
            "chapter_source_summary": dict(summary.chapter_source_summary or {}),
            "toc_alignment_summary": dict(summary.toc_alignment_summary or {}),
            "toc_semantic_summary": dict(summary.toc_semantic_summary or {}),
            "toc_role_summary": dict(summary.toc_role_summary or {}),
            "container_titles": list(summary.container_titles or []),
            "post_body_titles": list(summary.post_body_titles or []),
            "back_matter_titles": list(summary.back_matter_titles or []),
            "toc_semantic_contract_ok": bool(summary.toc_semantic_contract_ok),
            "toc_semantic_blocking_reasons": list(summary.toc_semantic_blocking_reasons or []),
            "chapter_title_alignment_ok": bool(summary.chapter_title_alignment_ok),
            "chapter_section_alignment_ok": bool(summary.chapter_section_alignment_ok),
            "export_bundle_summary": dict(summary.export_bundle_summary or {}),
            "export_audit_summary": dict(summary.export_audit_summary or {}),
            "chapter_progress_summary": dict(status.chapter_progress_summary or {}),
            "note_region_progress_summary": dict(status.note_region_progress_summary or {}),
            "chapter_binding_summary": dict(status.chapter_binding_summary or {}),
            "note_capture_summary": dict(status.note_capture_summary or {}),
            "footnote_synthesis_summary": dict(status.footnote_synthesis_summary or {}),
            "chapter_link_contract_summary": dict(status.chapter_link_contract_summary or {}),
            "book_endnote_stream_summary": dict(status.book_endnote_stream_summary or {}),
            "freeze_note_unit_summary": dict(status.freeze_note_unit_summary or {}),
            "chapter_issue_counts": dict(status.chapter_issue_counts or {}),
            "chapter_issue_summary": [dict(row or {}) for row in list(status.chapter_issue_summary or [])][:24],
            "export_drift_summary": dict(status.export_drift_summary or {}),
            "chapter_local_endnote_contract_ok": bool(status.chapter_local_endnote_contract_ok),
            "export_semantic_contract_ok": bool(status.export_semantic_contract_ok),
            "front_matter_leak_detected": bool(status.front_matter_leak_detected),
            "toc_residue_detected": bool(status.toc_residue_detected),
            "mid_paragraph_heading_detected": bool(status.mid_paragraph_heading_detected),
            "duplicate_paragraph_detected": bool(status.duplicate_paragraph_detected),
        },
    }


def _build_validation_payload(status_payload: dict[str, Any]) -> dict[str, Any]:
    summary = dict(status_payload.get("summary") or {})
    return {
        "needs_human_review": str(status_payload.get("structure_state") or "") != "ready",
        "review_counts": dict(status_payload.get("review_counts") or {}),
        "blocking_reasons": list(status_payload.get("blocking_reasons") or []),
        "link_summary": dict(status_payload.get("link_summary") or {}),
        "summary": summary,
        "manual_toc_required": bool(status_payload.get("manual_toc_required")),
        "manual_toc_ready": bool(status_payload.get("manual_toc_ready")),
        "manual_toc_summary": dict(status_payload.get("manual_toc_summary") or {}),
        "toc_export_coverage_summary": dict(status_payload.get("toc_export_coverage_summary") or {}),
    }


def _load_module_snapshot_for_doc(
    doc_id: str,
    *,
    repo: SQLiteRepository,
    pages: list[dict],
    max_body_chars: int | None = None,
    pipeline_state_override: str | None = None,
    overlay_repo_units: bool = True,
    include_diagnostic_entries: bool = False,
    slug: str = "",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Any, str]:
    run = _safe_dict(getattr(repo, "get_latest_fnm_run", None), doc_id)
    pipeline_state = str(pipeline_state_override or _phase_state_from_run(run)).strip().lower()
    if not is_valid_pipeline_state(pipeline_state):
        pipeline_state = "done"

    toc_items, toc_offset = _load_fnm_toc_items(doc_id, repo)
    visual_toc_bundle = _load_fnm_visual_toc_bundle(doc_id)
    overrides = _group_review_overrides(
        _safe_list(getattr(repo, "list_fnm_review_overrides", None), doc_id)
    )
    manual_toc_ready, manual_toc_summary = _resolve_manual_toc_state(doc_id)
    repo_units = (
        _safe_list(getattr(repo, "list_fnm_translation_units", None), doc_id)
        if overlay_repo_units
        else None
    )
    snapshot = build_module_pipeline_snapshot(
        pages,
        toc_items=toc_items or None,
        toc_offset=int(toc_offset or 0),
        review_overrides=overrides,
        pdf_path=get_pdf_path(doc_id),
        manual_toc_ready=bool(manual_toc_ready),
        manual_toc_summary=manual_toc_summary,
        pipeline_state=pipeline_state,
        max_body_chars=_effective_max_body_chars(max_body_chars),
        include_diagnostic_entries=bool(include_diagnostic_entries),
        slug=str(slug or doc_id),
        doc_id=doc_id,
        repo_units=repo_units,
        progress_callback=progress_callback,
        visual_toc_bundle=visual_toc_bundle,
    )
    return snapshot, pipeline_state


def load_phase6_for_doc(
    doc_id: str,
    *,
    include_diagnostic_entries: bool = False,
    slug: str = "",
    repo: SQLiteRepository | None = None,
    max_body_chars: int | None = None,
    pipeline_state_override: str | None = None,
    pages: list[dict] | None = None,
    overlay_repo_units: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Phase6Structure:
    repo = repo or SQLiteRepository()
    if pages is None:
        pages = _safe_list(getattr(repo, "load_pages", None), doc_id)
    else:
        pages = list(pages or [])

    snapshot, _pipeline_state = _load_module_snapshot_for_doc(
        doc_id,
        repo=repo,
        pages=pages,
        max_body_chars=max_body_chars,
        pipeline_state_override=pipeline_state_override,
        overlay_repo_units=overlay_repo_units,
        include_diagnostic_entries=bool(include_diagnostic_entries),
        slug=str(slug or doc_id),
        progress_callback=progress_callback,
    )
    return snapshot.phase6_shadow


def _resolve_phase6_from_snapshot(snapshot: Any) -> Phase6Structure | None:
    if isinstance(snapshot, Phase6Structure):
        return snapshot

    if isinstance(snapshot, dict):
        for key in ("phase6", "phase6_shadow", "_phase6"):
            maybe_phase6 = snapshot.get(key)
            if isinstance(maybe_phase6, Phase6Structure):
                return maybe_phase6
    else:
        for attr in ("phase6", "phase6_shadow"):
            maybe_phase6 = getattr(snapshot, attr, None)
            if isinstance(maybe_phase6, Phase6Structure):
                return maybe_phase6
    return None


def build_phase6_status_for_doc(
    doc_id: str,
    *,
    snapshot: Any | None = None,
    repo: SQLiteRepository | None = None,
) -> dict[str, Any]:
    repo = repo or SQLiteRepository()
    run = _safe_dict(getattr(repo, "get_latest_fnm_run", None), doc_id)
    run_validation = _safe_json_loads(run.get("validation_json"))
    phase6 = _resolve_phase6_from_snapshot(snapshot)
    if phase6 is None:
        phase6 = load_phase6_for_doc(
            doc_id,
            include_diagnostic_entries=False,
            slug=doc_id,
            repo=repo,
            pipeline_state_override=None,
        )
    return _status_payload(
        status=phase6.status,
        summary=phase6.summary,
        run_validation=run_validation,
    )


def build_phase6_export_bundle_for_doc(
    doc_id: str,
    *,
    include_diagnostic_entries: bool = False,
    repo: SQLiteRepository | None = None,
    snapshot: Any | None = None,
) -> dict[str, Any]:
    phase6 = _resolve_phase6_from_snapshot(snapshot)
    if phase6 is None:
        phase6 = load_phase6_for_doc(
            doc_id,
            include_diagnostic_entries=bool(include_diagnostic_entries),
            slug=doc_id,
            repo=repo,
        )
    return _export_bundle_payload(phase6)


def build_phase6_export_zip_for_doc(
    doc_id: str,
    *,
    include_diagnostic_entries: bool = False,
    repo: SQLiteRepository | None = None,
    snapshot: Any | None = None,
) -> bytes:
    phase6 = _resolve_phase6_from_snapshot(snapshot)
    if phase6 is None:
        phase6 = load_phase6_for_doc(
            doc_id,
            include_diagnostic_entries=bool(include_diagnostic_entries),
            slug=doc_id,
            repo=repo,
        )
    return build_export_zip(phase6.export_bundle)


def audit_phase6_export_for_doc(
    doc_id: str,
    *,
    slug: str = "",
    zip_path: str = "",
    zip_bytes: bytes | None = None,
    repo: SQLiteRepository | None = None,
    snapshot: Any | None = None,
) -> dict[str, Any]:
    repo = repo or SQLiteRepository()
    phase6 = _resolve_phase6_from_snapshot(snapshot)
    if phase6 is None:
        phase6 = load_phase6_for_doc(
            doc_id,
            include_diagnostic_entries=False,
            slug=slug or doc_id,
            repo=repo,
        )
    payload = zip_bytes
    if payload is None and str(zip_path or "").strip():
        path = Path(str(zip_path or "").strip())
        if path.exists():
            payload = path.read_bytes()
    report, _summary = audit_phase6_export(
        phase6,
        slug=str(slug or doc_id),
        zip_bytes=payload,
    )
    file_reports = [_to_plain(row) for row in report.files]
    return _summarize_book_audit(
        slug=str(slug or doc_id),
        doc_id=doc_id,
        zip_path=str(zip_path or report.zip_path or ""),
        structure_state=str(report.structure_state or ""),
        blocking_reasons=list(report.blocking_reasons or []),
        manual_toc_summary=dict(report.manual_toc_summary or {}),
        toc_role_summary=dict(report.toc_role_summary or {}),
        chapter_titles=list(report.chapter_titles or []),
        file_reports=file_reports,
    )


def _persist_phase6_to_repo(doc_id: str, phase6: Phase6Structure, *, repo: SQLiteRepository) -> None:
    chapter_title_by_id = {
        str(row.chapter_id or ""): str(row.title or "")
        for row in phase6.chapters
        if str(row.chapter_id or "")
    }
    region_rows = _serialize_note_regions_for_repo(list(phase6.note_regions or []))
    region_pages_by_id = {
        str(row.get("region_id") or ""): list(row.get("pages") or [])
        for row in region_rows
        if str(row.get("region_id") or "")
    }
    note_kind_by_region_id = {
        str(row.get("region_id") or ""): (
            "endnote" if str(row.get("region_kind") or "").startswith("book_endnote") or str(row.get("region_kind") or "").startswith("chapter_endnote") or str(row.get("region_kind") or "") == "endnote" else "footnote"
        )
        for row in region_rows
        if str(row.get("region_id") or "")
    }
    title_hint_by_region_id = {
        str(row.get("region_id") or ""): str(row.get("title_hint") or "")
        for row in region_rows
        if str(row.get("region_id") or "")
    }
    effective_note_links = list(phase6.effective_note_links or phase6.note_links or [])
    repo.replace_fnm_structure(
        doc_id,
        pages=_serialize_pages_for_repo(list(phase6.pages or [])),
        chapters=[_to_plain(row) for row in phase6.chapters],
        heading_candidates=_serialize_heading_candidates_for_repo(list(phase6.heading_candidates or [])),
        note_regions=region_rows,
        chapter_note_modes=_serialize_chapter_note_modes_for_repo(
            list(phase6.chapter_note_modes or []),
            chapter_title_by_id=chapter_title_by_id,
            region_pages_by_id=region_pages_by_id,
        ),
        section_heads=_serialize_section_heads_for_repo(list(phase6.section_heads or [])),
        note_items=_serialize_note_items_for_repo(
            list(phase6.note_items or []),
            note_kind_by_region_id=note_kind_by_region_id,
            title_hint_by_region_id=title_hint_by_region_id,
        ),
        body_anchors=[_to_plain(row) for row in phase6.body_anchors],
        note_links=[_to_plain(row) for row in effective_note_links],
        structure_reviews=_serialize_structure_reviews(list(phase6.structure_reviews or [])),
    )
    repo.replace_fnm_data(
        doc_id,
        notes=[_to_plain(row) for row in phase6.diagnostic_notes],
        units=_serialize_units_for_repo(doc_id, list(phase6.translation_units or [])),
        preserve_structure=True,
    )
    from translation.translate_store import _clear_translate_state

    _clear_translate_state(doc_id)


def run_phase6_pipeline_for_doc(
    doc_id: str,
    *,
    max_body_chars: int | None = None,
    repo: SQLiteRepository | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    repo = repo or SQLiteRepository()
    pages = _safe_list(getattr(repo, "load_pages", None), doc_id)
    run_id = int(getattr(repo, "create_fnm_run")(doc_id, status="running"))
    if not pages:
        repo.update_fnm_run(doc_id, run_id, status="error", error_msg="未找到 OCR 页面数据")
        return {"ok": False, "error": "no_pages", "run_id": run_id}

    try:
        phase6 = load_phase6_for_doc(
            doc_id,
            include_diagnostic_entries=False,
            slug=doc_id,
            repo=repo,
            max_body_chars=max_body_chars,
            pipeline_state_override="done",
            pages=pages,
            overlay_repo_units=False,
            progress_callback=progress_callback,
        )
        _persist_phase6_to_repo(doc_id, phase6, repo=repo)
        status_payload = _status_payload(
            status=phase6.status,
            summary=phase6.summary,
            run_validation=None,
        )
        validation_payload = _build_validation_payload(status_payload)
        note_count = len(phase6.note_items)
        unit_count = len(phase6.translation_units)
        section_count = len(phase6.chapters)
        page_count = len(pages)
        repo.update_fnm_run(
            doc_id,
            run_id,
            status="done",
            error_msg="",
            page_count=page_count,
            section_count=section_count,
            note_count=note_count,
            unit_count=unit_count,
            validation_json=json.dumps(validation_payload, ensure_ascii=False),
            structure_state=str(status_payload.get("structure_state") or "ready"),
            review_counts=dict(status_payload.get("review_counts") or {}),
            blocking_reasons=list(status_payload.get("blocking_reasons") or []),
            link_summary=dict(status_payload.get("link_summary") or {}),
            page_partition_summary=dict(status_payload.get("page_partition_summary") or {}),
            chapter_mode_summary=dict(status_payload.get("chapter_mode_summary") or {}),
        )
        return {
            "ok": True,
            "run_id": run_id,
            "page_count": page_count,
            "section_count": section_count,
            "note_count": note_count,
            "unit_count": unit_count,
            "structure_state": str(status_payload.get("structure_state") or "ready"),
            "manual_toc_required": bool(status_payload.get("manual_toc_required")),
            "blocking_reasons": list(status_payload.get("blocking_reasons") or []),
            "review_counts": dict(status_payload.get("review_counts") or {}),
            "export_ready_real": bool(status_payload.get("export_ready_real")),
        }
    except Exception as exc:
        repo.update_fnm_run(doc_id, run_id, status="error", error_msg=str(exc))
        return {"ok": False, "error": str(exc), "run_id": run_id}


def list_phase6_diagnostic_notes_for_doc(
    doc_id: str,
    *,
    repo: SQLiteRepository | None = None,
) -> list[dict]:
    phase6 = load_phase6_for_doc(
        doc_id,
        include_diagnostic_entries=False,
        slug=doc_id,
        repo=repo,
    )
    rows = [_to_plain(row) for row in phase6.diagnostic_notes]
    rows.sort(
        key=lambda row: (
            int(row.get("section_start_page") or 0),
            int(row.get("start_page") or 0),
            str(row.get("kind") or ""),
            str(row.get("note_id") or ""),
        )
    )
    return rows


def list_phase6_diagnostic_entries_for_doc(
    doc_id: str,
    *,
    pages: list[dict] | None = None,
    visible_bps: list[int] | None = None,
    repo: SQLiteRepository | None = None,
) -> list[dict]:
    phase6 = load_phase6_for_doc(
        doc_id,
        include_diagnostic_entries=False,
        slug=doc_id,
        repo=repo,
        pages=pages,
    )
    visible = {int(bp) for bp in (visible_bps or []) if int(bp) > 0}
    rows = []
    for row in phase6.diagnostic_pages:
        payload = _to_plain(row)
        bp = int(payload.get("_pageBP") or 0)
        if visible and bp not in visible:
            continue
        rows.append(payload)
    rows.sort(key=lambda row: int(row.get("_pageBP") or 0))
    return rows


def get_phase6_diagnostic_entry_for_doc(
    doc_id: str,
    bp: int,
    *,
    pages: list[dict] | None = None,
    allow_fallback: bool = True,
    repo: SQLiteRepository | None = None,
) -> dict | None:
    if not allow_fallback:
        return None
    target = int(bp)
    for row in list_phase6_diagnostic_entries_for_doc(
        doc_id,
        pages=pages,
        visible_bps=[target],
        repo=repo,
    ):
        if int(row.get("_pageBP") or 0) == target:
            return row
    return None

"""FNM_RE 第四阶段：结构状态投影。"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from typing import Any

from FNM_RE.constants import is_valid_pipeline_state
from FNM_RE.models import Phase4Structure, Phase6Structure, StructureStatusRecord

CANONICAL_REVIEW_KEYS = (
    "footnote_orphan_note",
    "footnote_orphan_anchor",
    "endnote_orphan_note",
    "endnote_orphan_anchor",
    "ambiguous",
    "uncertain_anchor",
    "boundary_review_required",
    "toc_alignment_review_required",
    "toc_semantic_review_required",
)

BLOCKING_REVIEW_KEYS = (
    "footnote_orphan_note",
    "footnote_orphan_anchor",
    "endnote_orphan_note",
    "endnote_orphan_anchor",
    "ambiguous",
    "boundary_review_required",
)

_DONE_UNIT_STATUSES = {"done", "done_manual"}
_ERROR_UNIT_STATUSES = {"error", "retry_pending", "retrying", "manual_required"}
_LOCAL_REF_RE = re.compile(r"\[\^([0-9]+)\]")
_LOCAL_DEF_RE = re.compile(r"^\[\^([0-9]+)\]:", re.MULTILINE)
_LEGACY_FOOTNOTE_RE = re.compile(r"\[FN-[^\]]+\]", re.IGNORECASE)
_LEGACY_ENDNOTE_RE = re.compile(r"\[\^en-[^\]]+\]", re.IGNORECASE)
_LEGACY_EN_BRACKET_RE = re.compile(r"\[EN-[^\]]+\]", re.IGNORECASE)
_LEGACY_NOTE_TOKEN_RE = re.compile(r"\{\{(?:NOTE_REF|FN_REF|EN_REF):[^}]+\}\}", re.IGNORECASE)


def _count_page_roles(phase4: Phase4Structure) -> dict[str, int]:
    counts = {"noise": 0, "front_matter": 0, "body": 0, "note": 0, "other": 0}
    for page in phase4.pages:
        role = str(page.page_role or "")
        if role in counts:
            counts[role] += 1
    return {"total_pages": len(phase4.pages), **counts}


def _heading_review_summary(phase4: Phase4Structure) -> dict[str, Any]:
    suppressed = [row for row in phase4.heading_candidates if bool(row.suppressed_as_chapter)]
    reason_counts = Counter(str(row.reject_reason or "unknown") for row in suppressed if str(row.reject_reason or "").strip())
    return {
        "chapter_candidate_count": sum(
            1
            for row in phase4.heading_candidates
            if str(row.heading_family_guess or "").strip().lower() in {"chapter", "front_matter", "section"}
        ),
        "suppressed_candidate_count": len(suppressed),
        "suppressed_reason_counts": dict(reason_counts),
        "partition_conflict_count": int(reason_counts.get("partition_conflict", 0)),
    }


def _chapter_source_summary(phase4: Phase4Structure) -> dict[str, Any]:
    visual_count = sum(1 for chapter in phase4.chapters if str(chapter.source or "") == "visual_toc")
    fallback_count = sum(1 for chapter in phase4.chapters if str(chapter.source or "") != "visual_toc")
    return {
        "source": "visual_toc" if visual_count > 0 else "fallback",
        "chapter_level": None,
        "visual_toc_chapter_count": int(visual_count),
        "legacy_chapter_count": int(fallback_count),
        "fallback_used": bool(visual_count == 0),
    }


def _chapter_mode_summary(phase4: Phase4Structure) -> dict[str, int]:
    mapped = {
        "footnote_primary": 0,
        "chapter_endnotes": 0,
        "book_endnotes": 0,
        "body_only": 0,
        "mixed_or_unclear": 0,
    }
    for row in phase4.chapter_note_modes:
        mode = str(row.note_mode or "")
        if mode == "footnote_primary":
            mapped["footnote_primary"] += 1
        elif mode == "chapter_endnote_primary":
            mapped["chapter_endnotes"] += 1
        elif mode == "book_endnote_bound":
            mapped["book_endnotes"] += 1
        elif mode == "no_notes":
            mapped["body_only"] += 1
        else:
            mapped["mixed_or_unclear"] += 1
    return mapped


def _link_summary(phase4: Phase4Structure) -> dict[str, int]:
    links = list(phase4.effective_note_links or [])
    return {
        "matched": sum(1 for row in links if str(row.status or "") == "matched"),
        "footnote_orphan_note": sum(
            1 for row in links if str(row.status or "") == "orphan_note" and str(row.note_kind or "") == "footnote"
        ),
        "footnote_orphan_anchor": sum(
            1 for row in links if str(row.status or "") == "orphan_anchor" and str(row.note_kind or "") == "footnote"
        ),
        "endnote_orphan_note": sum(
            1 for row in links if str(row.status or "") == "orphan_note" and str(row.note_kind or "") == "endnote"
        ),
        "endnote_orphan_anchor": sum(
            1 for row in links if str(row.status or "") == "orphan_anchor" and str(row.note_kind or "") == "endnote"
        ),
        "ambiguous": sum(1 for row in links if str(row.status or "") == "ambiguous"),
        "ignored": sum(1 for row in links if str(row.status or "") == "ignored"),
    }


def _review_counts(phase4: Phase4Structure) -> dict[str, int]:
    counts = {key: 0 for key in CANONICAL_REVIEW_KEYS}
    for review in phase4.structure_reviews:
        review_type = str(review.review_type or "")
        if review_type in counts:
            counts[review_type] += 1
    return counts


def _chapter_endnote_region_alignment_summary(phase4: Phase4Structure) -> dict[str, Any]:
    chapter_regions = [
        region
        for region in phase4.note_regions
        if str(region.note_kind or "") == "endnote" and str(region.scope or "") == "chapter"
    ]
    total = len(chapter_regions)
    aligned = sum(1 for region in chapter_regions if bool(region.region_marker_alignment_ok))
    missing = sum(
        1
        for region in chapter_regions
        if not str(region.region_start_first_source_marker or "").strip()
        or not str(region.region_first_note_item_marker or "").strip()
    )
    misaligned = sum(1 for region in chapter_regions if not bool(region.region_marker_alignment_ok))
    return {
        "chapter_endnotes_total": int(total),
        "aligned_count": int(aligned),
        "misaligned_count": int(misaligned),
        "missing_marker_count": int(missing),
    }


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        token = str(value or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _infer_toc_semantic_blocking_reasons(
    toc_semantic_summary: dict[str, Any],
    existing: list[str],
) -> list[str]:
    reasons = list(existing or [])
    if reasons:
        return reasons
    nonbody_contamination_count = int(toc_semantic_summary.get("nonbody_contamination_count") or 0)
    mixed_level_chapter_count = int(toc_semantic_summary.get("mixed_level_chapter_count") or 0)
    first_body_pdf_page = int(toc_semantic_summary.get("first_body_pdf_page") or 0)
    body_span_ratio = float(toc_semantic_summary.get("body_span_ratio") or 0.0)
    if nonbody_contamination_count > 0:
        reasons.append("toc_nonbody_as_chapter")
    if mixed_level_chapter_count > 0:
        reasons.append("toc_mixed_part_and_chapter_levels")
    if first_body_pdf_page > 0 and body_span_ratio < 0.55:
        reasons.append("toc_partial_tail_capture")
    return reasons


def build_phase4_status(phase4: Phase4Structure) -> StructureStatusRecord:
    override_summary = dict(getattr(phase4.summary, "override_summary", {}) or {})
    pipeline_state = str(override_summary.get("pipeline_state") or "done").strip()
    if not is_valid_pipeline_state(pipeline_state):
        pipeline_state = "done"
    manual_toc_ready = bool(override_summary.get("manual_toc_ready", True))
    manual_toc_summary = dict(override_summary.get("manual_toc_summary") or {})
    manual_toc_required = bool(not manual_toc_ready)

    review_counts = _review_counts(phase4)
    link_summary = _link_summary(phase4)
    blocking_reasons: list[str] = [
        key for key in BLOCKING_REVIEW_KEYS if int(review_counts.get(key, 0) or 0) > 0
    ]

    toc_alignment_summary = dict(getattr(phase4.summary, "toc_alignment_summary", {}) or {})
    toc_semantic_summary = dict(getattr(phase4.summary, "toc_semantic_summary", {}) or {})
    toc_role_summary = dict(getattr(phase4.summary, "toc_role_summary", {}) or {})
    container_titles = list(getattr(phase4.summary, "container_titles", []) or [])
    post_body_titles = list(getattr(phase4.summary, "post_body_titles", []) or [])
    back_matter_titles = list(getattr(phase4.summary, "back_matter_titles", []) or [])
    chapter_title_alignment_ok = bool(getattr(phase4.summary, "chapter_title_alignment_ok", True))
    chapter_section_alignment_ok = bool(getattr(phase4.summary, "chapter_section_alignment_ok", True))
    toc_semantic_contract_ok = bool(getattr(phase4.summary, "toc_semantic_contract_ok", True))
    toc_semantic_blocking_reasons = list(getattr(phase4.summary, "toc_semantic_blocking_reasons", []) or [])

    chapter_endnote_region_alignment_ok = bool(
        getattr(phase4.summary, "chapter_endnote_region_alignment_ok", True)
    )
    chapter_endnote_region_alignment_summary = _chapter_endnote_region_alignment_summary(phase4)

    if manual_toc_required:
        blocking_reasons.append("manual_toc_required")
    if not chapter_title_alignment_ok:
        blocking_reasons.append("toc_chapter_title_mismatch")
    if not chapter_endnote_region_alignment_ok:
        blocking_reasons.append("endnote_region_marker_misalignment")
    if not toc_semantic_contract_ok:
        inferred_toc_reasons = _infer_toc_semantic_blocking_reasons(
            toc_semantic_summary=toc_semantic_summary,
            existing=toc_semantic_blocking_reasons,
        )
        blocking_reasons.extend(inferred_toc_reasons)
        toc_semantic_blocking_reasons = inferred_toc_reasons
    blocking_reasons = _dedupe_preserve_order(blocking_reasons)

    if pipeline_state == "idle":
        structure_state = "idle"
    elif pipeline_state == "running":
        structure_state = "running"
    elif pipeline_state == "error":
        structure_state = "error"
    else:
        structure_state = "ready" if not blocking_reasons else "review_required"

    return StructureStatusRecord(
        structure_state=structure_state,
        review_counts=review_counts,
        blocking_reasons=blocking_reasons,
        link_summary=link_summary,
        page_partition_summary=_count_page_roles(phase4),
        chapter_mode_summary=_chapter_mode_summary(phase4),
        heading_review_summary=_heading_review_summary(phase4),
        heading_graph_summary=dict(getattr(phase4.summary, "heading_graph_summary", {}) or {}),
        chapter_source_summary=_chapter_source_summary(phase4),
        visual_toc_conflict_count=int(getattr(phase4.summary, "visual_toc_conflict_count", 0) or 0),
        toc_alignment_summary=toc_alignment_summary,
        toc_semantic_summary=toc_semantic_summary,
        toc_role_summary=toc_role_summary,
        container_titles=container_titles,
        post_body_titles=post_body_titles,
        back_matter_titles=back_matter_titles,
        toc_semantic_contract_ok=toc_semantic_contract_ok,
        toc_semantic_blocking_reasons=toc_semantic_blocking_reasons,
        chapter_title_alignment_ok=chapter_title_alignment_ok,
        chapter_section_alignment_ok=chapter_section_alignment_ok,
        chapter_endnote_region_alignment_ok=chapter_endnote_region_alignment_ok,
        chapter_endnote_region_alignment_summary=chapter_endnote_region_alignment_summary,
        manual_toc_ready=manual_toc_ready,
        manual_toc_required=manual_toc_required,
        manual_toc_summary=manual_toc_summary,
        page_count=len(phase4.pages),
        chapter_count=len(phase4.chapters),
        section_head_count=len(phase4.section_heads),
        review_count=len(phase4.structure_reviews),
    )


def _owner_progress_status(
    *,
    total_units: int,
    done_units: int,
    error_units: int,
    is_current: bool,
) -> str:
    if is_current:
        return "translating"
    if total_units <= 0:
        return "pending"
    if done_units >= total_units:
        return "done"
    if error_units > 0:
        return "blocked"
    if done_units > 0:
        return "partial"
    return "pending"


def _build_owner_progress_summaries(phase6: Phase6Structure) -> tuple[dict[str, Any], dict[str, Any]]:
    units_by_owner: dict[tuple[str, str], list[Any]] = {}
    for unit in phase6.translation_units:
        owner_kind = str(unit.owner_kind or "").strip().lower()
        if not owner_kind:
            owner_kind = "chapter" if str(unit.kind or "") == "body" else "note_region"
        owner_id = str(unit.owner_id or unit.section_id or "").strip()
        if not owner_id:
            continue
        units_by_owner.setdefault((owner_kind, owner_id), []).append(unit)

    chapter_items: list[dict[str, Any]] = []
    for chapter in phase6.chapters:
        chapter_id = str(chapter.chapter_id or "").strip()
        if not chapter_id:
            continue
        owner_units = list(units_by_owner.get(("chapter", chapter_id)) or [])
        total_units = len(owner_units)
        done_units = sum(1 for unit in owner_units if str(unit.status or "") in _DONE_UNIT_STATUSES)
        error_units = sum(1 for unit in owner_units if str(unit.status or "") in _ERROR_UNIT_STATUSES)
        status = _owner_progress_status(
            total_units=total_units,
            done_units=done_units,
            error_units=error_units,
            is_current=False,
        )
        chapter_items.append(
            {
                "chapter_id": chapter_id,
                "title": str(chapter.title or chapter_id),
                "start_page": int(chapter.start_page or 0),
                "end_page": int(chapter.end_page or int(chapter.start_page or 0)),
                "total_units": total_units,
                "done_units": done_units,
                "error_units": error_units,
                "pending_units": max(0, total_units - done_units - error_units),
                "status": status,
            }
        )

    chapter_by_id = {
        str(chapter.chapter_id or "").strip(): chapter
        for chapter in phase6.chapters
        if str(chapter.chapter_id or "").strip()
    }
    note_region_items: list[dict[str, Any]] = []
    for region in phase6.note_regions:
        region_id = str(region.region_id or "").strip()
        if not region_id:
            continue
        owner_units = list(units_by_owner.get(("note_region", region_id)) or [])
        total_units = len(owner_units)
        done_units = sum(1 for unit in owner_units if str(unit.status or "") in _DONE_UNIT_STATUSES)
        error_units = sum(1 for unit in owner_units if str(unit.status or "") in _ERROR_UNIT_STATUSES)
        status = _owner_progress_status(
            total_units=total_units,
            done_units=done_units,
            error_units=error_units,
            is_current=False,
        )
        chapter = chapter_by_id.get(str(region.chapter_id or "").strip())
        note_region_items.append(
            {
                "region_id": region_id,
                "chapter_id": str(region.chapter_id or "").strip(),
                "chapter_title": str((chapter.title if chapter else region.chapter_id) or ""),
                "region_kind": str(region.note_kind or ""),
                "start_page": int(region.page_start or 0),
                "end_page": int(region.page_end or int(region.page_start or 0)),
                "total_units": total_units,
                "done_units": done_units,
                "error_units": error_units,
                "pending_units": max(0, total_units - done_units - error_units),
                "status": status,
            }
        )

    chapter_progress_summary = {
        "total_chapters": len(chapter_items),
        "done_chapters": sum(1 for item in chapter_items if item.get("status") == "done"),
        "translating_chapters": sum(1 for item in chapter_items if item.get("status") == "translating"),
        "blocked_chapters": sum(1 for item in chapter_items if item.get("status") == "blocked"),
        "partial_chapters": sum(1 for item in chapter_items if item.get("status") == "partial"),
        "pending_chapters": sum(1 for item in chapter_items if item.get("status") == "pending"),
        "current_chapter_id": "",
        "current_chapter_title": "",
        "items": chapter_items,
    }
    note_region_progress_summary = {
        "total_regions": len(note_region_items),
        "done_regions": sum(1 for item in note_region_items if item.get("status") == "done"),
        "translating_regions": sum(1 for item in note_region_items if item.get("status") == "translating"),
        "blocked_regions": sum(1 for item in note_region_items if item.get("status") == "blocked"),
        "partial_regions": sum(1 for item in note_region_items if item.get("status") == "partial"),
        "pending_regions": sum(1 for item in note_region_items if item.get("status") == "pending"),
        "current_region_id": "",
        "items": note_region_items,
    }
    return chapter_progress_summary, note_region_progress_summary


def _chapter_local_ref_contract_summary(phase6: Phase6Structure) -> tuple[bool, list[dict[str, Any]]]:
    chapter_files = dict(phase6.export_bundle.chapter_files or {})
    items: list[dict[str, Any]] = []
    for chapter in phase6.export_bundle.chapters:
        content = str(chapter_files.get(chapter.path) or "")
        body_text, _definition_text = _split_body_and_definitions(content)
        refs = sorted(set(_LOCAL_REF_RE.findall(body_text)))
        defs = sorted(set(_LOCAL_DEF_RE.findall(content)))
        missing = sorted(set(refs) - set(defs))
        orphan = sorted(set(defs) - set(refs))
        items.append(
            {
                "section_id": str(chapter.section_id or ""),
                "title": str(chapter.title or ""),
                "path": str(chapter.path or ""),
                "missing_definition_markers": missing[:8],
                "orphan_definition_markers": orphan[:8],
                "contract_ok": not missing and not orphan,
            }
        )
    return all(bool(item.get("contract_ok")) for item in items), items


def _split_body_and_definitions(content: str) -> tuple[str, str]:
    body_lines: list[str] = []
    definition_lines: list[str] = []
    in_definition_block = False
    for raw_line in str(content or "").splitlines():
        if _LOCAL_DEF_RE.match(raw_line):
            in_definition_block = True
            definition_lines.append(raw_line)
            continue
        if in_definition_block and (raw_line.startswith("    ") or raw_line.startswith("\t")):
            definition_lines.append(raw_line)
            continue
        in_definition_block = False
        body_lines.append(raw_line)
    return "\n".join(body_lines), "\n".join(definition_lines)


def _build_export_drift_summary(phase6: Phase6Structure) -> dict[str, Any]:
    chapter_files = dict(phase6.export_bundle.chapter_files or {})
    orphan_local_definition_count = 0
    orphan_local_ref_count = 0
    for content in chapter_files.values():
        body_text, _definition_text = _split_body_and_definitions(content)
        refs = set(_LOCAL_REF_RE.findall(body_text))
        defs = set(_LOCAL_DEF_RE.findall(content))
        orphan_local_definition_count += max(0, len(defs - refs))
        orphan_local_ref_count += max(0, len(refs - defs))
    return {
        "legacy_footnote_ref_count": sum(len(_LEGACY_FOOTNOTE_RE.findall(content)) for content in chapter_files.values()),
        "legacy_endnote_ref_count": sum(len(_LEGACY_ENDNOTE_RE.findall(content)) for content in chapter_files.values()),
        "legacy_en_bracket_ref_count": sum(len(_LEGACY_EN_BRACKET_RE.findall(content)) for content in chapter_files.values()),
        "legacy_note_token_count": sum(len(_LEGACY_NOTE_TOKEN_RE.findall(content)) for content in chapter_files.values()),
        "orphan_local_definition_count": int(orphan_local_definition_count),
        "orphan_local_ref_count": int(orphan_local_ref_count),
    }


def _chapter_mode_summary_from_snapshot(snapshot: Any) -> dict[str, int]:
    mapped = {
        "footnote_primary": 0,
        "chapter_endnotes": 0,
        "book_endnotes": 0,
        "body_only": 0,
        "mixed_or_unclear": 0,
    }
    book_type_result = getattr(snapshot, "book_type_result", None)
    book_type_data = getattr(book_type_result, "data", None)
    rows = list(getattr(book_type_data, "chapter_modes", []) or [])
    for row in rows:
        mode = str(getattr(row, "note_mode", "") or "")
        if mode == "footnote_primary":
            mapped["footnote_primary"] += 1
        elif mode == "chapter_endnote_primary":
            mapped["chapter_endnotes"] += 1
        elif mode == "book_endnote_bound":
            mapped["book_endnotes"] += 1
        elif mode == "no_notes":
            mapped["body_only"] += 1
        else:
            mapped["mixed_or_unclear"] += 1
    return mapped


def build_module_gate_status(
    snapshot: Any,
    *,
    pipeline_state: str,
    manual_toc_ready: bool,
    manual_toc_summary: dict[str, Any] | None = None,
) -> StructureStatusRecord:
    normalized_pipeline_state = str(pipeline_state or "done").strip().lower()
    if not is_valid_pipeline_state(normalized_pipeline_state):
        normalized_pipeline_state = "done"

    module_results = [
        getattr(snapshot, "toc_result", None),
        getattr(snapshot, "book_type_result", None),
        getattr(snapshot, "split_result", None),
        getattr(snapshot, "link_result", None),
        getattr(snapshot, "freeze_result", None),
        getattr(snapshot, "merge_result", None),
        getattr(snapshot, "export_result", None),
    ]
    blocking_reasons: list[str] = []
    review_counts: dict[str, int] = {}
    hard_all_true = True
    for result in module_results:
        if result is None:
            hard_all_true = False
            continue
        gate = getattr(result, "gate_report", None)
        if gate is None:
            hard_all_true = False
            continue
        hard = dict(getattr(gate, "hard", {}) or {})
        reasons = [str(item).strip() for item in list(getattr(gate, "reasons", []) or []) if str(item).strip()]
        module_hard_failed = False
        if not hard:
            module_hard_failed = True
            hard_all_true = False
        for value in hard.values():
            if bool(value):
                continue
            module_hard_failed = True
            hard_all_true = False
        if module_hard_failed and reasons:
            blocking_reasons.extend(reasons)
            for reason in reasons:
                review_counts[reason] = int(review_counts.get(reason, 0) or 0) + 1
    if not bool(manual_toc_ready):
        blocking_reasons.append("toc_manual_toc_required")
        review_counts["toc_manual_toc_required"] = int(review_counts.get("toc_manual_toc_required", 0) or 0) + 1
        hard_all_true = False
    blocking_reasons = _dedupe_preserve_order(blocking_reasons)

    if normalized_pipeline_state == "idle":
        structure_state = "idle"
    elif normalized_pipeline_state == "running":
        structure_state = "running"
    elif normalized_pipeline_state == "error":
        structure_state = "error"
    else:
        structure_state = "ready" if hard_all_true and not blocking_reasons else "review_required"

    phase6 = getattr(snapshot, "phase6", None)
    chapter_progress_summary: dict[str, Any] = {}
    note_region_progress_summary: dict[str, Any] = {}
    export_drift_summary: dict[str, Any] = {}
    page_count = len(getattr(phase6, "pages", []) or [])
    chapter_count = len(getattr(phase6, "chapters", []) or [])
    section_head_count = len(getattr(phase6, "section_heads", []) or [])
    if phase6 is not None:
        chapter_progress_summary, note_region_progress_summary = _build_owner_progress_summaries(phase6)
        export_drift_summary = _build_export_drift_summary(phase6)

    toc_result = getattr(snapshot, "toc_result", None)
    toc_gate = getattr(toc_result, "gate_report", None)
    toc_evidence = dict(getattr(toc_result, "evidence", {}) or {})
    toc_diagnostics = dict(getattr(toc_result, "diagnostics", {}) or {})
    chapter_meta = dict(toc_diagnostics.get("chapter_meta") or {})
    heading_review_summary = dict(toc_diagnostics.get("heading_review_summary") or {})
    heading_graph_summary = dict(
        chapter_meta.get("heading_graph_summary")
        or toc_diagnostics.get("heading_graph_summary")
        or toc_evidence.get("heading_graph_summary")
        or {}
    )
    chapter_source_summary = dict(toc_diagnostics.get("chapter_source_summary") or {})
    visual_toc_conflict_count = int(chapter_meta.get("visual_toc_conflict_count") or 0)
    toc_alignment_summary = dict(chapter_meta.get("toc_alignment_summary") or {})
    toc_semantic_summary = dict(chapter_meta.get("toc_semantic_summary") or {})
    toc_role_summary = dict(toc_evidence.get("toc_role_summary") or {})
    container_titles = list(toc_diagnostics.get("container_titles") or [])
    post_body_titles = list(toc_diagnostics.get("post_body_titles") or [])
    back_matter_titles = list(toc_diagnostics.get("back_matter_titles") or [])
    visual_toc_endnotes_summary = dict(chapter_meta.get("visual_toc_endnotes_summary") or {})
    toc_hard = dict(getattr(toc_gate, "hard", {}) or {})
    toc_soft = dict(getattr(toc_gate, "soft", {}) or {})
    toc_semantic_contract_ok = bool(toc_hard.get("toc.role_semantics_valid", True))
    toc_semantic_blocking_reasons = list(chapter_meta.get("toc_semantic_blocking_reasons") or [])
    if not toc_semantic_contract_ok:
        toc_semantic_blocking_reasons = _infer_toc_semantic_blocking_reasons(
            toc_semantic_summary=toc_semantic_summary,
            existing=toc_semantic_blocking_reasons,
        )
    chapter_title_alignment_ok = bool(toc_hard.get("toc.chapter_titles_aligned", True))
    chapter_section_alignment_ok = bool(toc_soft.get("toc.section_alignment_warn", True))

    link_result = getattr(snapshot, "link_result", None)
    link_data = getattr(link_result, "data", None)
    link_summary = dict(getattr(link_data, "link_summary", {}) or {})
    link_evidence = dict(getattr(link_result, "evidence", {}) or {})
    chapter_link_contract_summary = dict(link_evidence.get("chapter_link_contract_summary") or {})
    book_endnote_stream_summary = dict(link_evidence.get("book_endnote_stream_summary") or {})
    split_result = getattr(snapshot, "split_result", None)
    split_evidence = dict(getattr(split_result, "evidence", {}) or {})
    split_region_summary = dict(split_evidence.get("region_summary") or {})
    split_item_summary = dict(split_evidence.get("item_summary") or {})
    chapter_binding_summary = dict(
        split_region_summary.get("chapter_binding_summary")
        or split_evidence.get("chapter_binding_summary")
        or {}
    )
    note_capture_summary = dict(
        split_item_summary.get("note_capture_summary")
        or split_evidence.get("note_capture_summary")
        or {}
    )
    footnote_synthesis_summary = dict(
        split_item_summary.get("footnote_synthesis_summary")
        or split_evidence.get("footnote_synthesis_summary")
        or {}
    )
    freeze_result = getattr(snapshot, "freeze_result", None)
    freeze_evidence = dict(getattr(freeze_result, "evidence", {}) or {})
    freeze_summary = dict(freeze_evidence.get("freeze_summary") or {})
    freeze_note_unit_summary = {
        "chapter_view_note_unit_count": int(freeze_summary.get("chapter_view_note_unit_count") or 0),
        "owner_fallback_note_unit_count": int(freeze_summary.get("owner_fallback_note_unit_count") or 0),
        "unresolved_note_item_count": int(freeze_summary.get("unresolved_note_item_count") or 0),
        "unresolved_note_item_ids_preview": list(freeze_summary.get("unresolved_note_item_ids_preview") or [])[:24],
    }
    merge_result = getattr(snapshot, "merge_result", None)
    merge_diagnostics = dict(getattr(merge_result, "diagnostics", {}) or {})
    chapter_issue_counts_raw = dict(merge_diagnostics.get("chapter_issue_counts") or {})
    chapter_issue_counts = {
        "chapter_issue_count": int(chapter_issue_counts_raw.get("chapter_issue_count") or 0),
        "frozen_ref_leak_chapter_count": int(chapter_issue_counts_raw.get("frozen_ref_leak_chapter_count") or 0),
        "raw_marker_leak_chapter_count": int(chapter_issue_counts_raw.get("raw_marker_leak_chapter_count") or 0),
        "local_ref_contract_broken_chapter_count": int(
            chapter_issue_counts_raw.get("local_ref_contract_broken_chapter_count") or 0
        ),
    }
    chapter_issue_summary = [
        dict(row or {})
        for row in list(merge_diagnostics.get("chapter_issue_summary") or [])
        if isinstance(row, dict)
    ][:24]
    page_partition_summary = dict(toc_evidence.get("page_partition_summary") or {})
    chapter_mode_summary = _chapter_mode_summary_from_snapshot(snapshot)
    merge_hard = dict(getattr(getattr(merge_result, "gate_report", None), "hard", {}) or {})
    export_hard = dict(getattr(getattr(getattr(snapshot, "export_result", None), "gate_report", None), "hard", {}) or {})
    export_result = getattr(snapshot, "export_result", None)
    export_data = getattr(export_result, "data", None)
    export_semantic_summary = dict(getattr(export_data, "semantic_summary", {}) or {})

    export_ready = bool(
        normalized_pipeline_state == "done"
        and hard_all_true
        and not blocking_reasons
    )
    return StructureStatusRecord(
        structure_state=structure_state,
        review_counts=review_counts,
        blocking_reasons=blocking_reasons,
        link_summary=link_summary,
        page_partition_summary=page_partition_summary,
        chapter_mode_summary=chapter_mode_summary,
        heading_review_summary=heading_review_summary,
        heading_graph_summary=heading_graph_summary,
        chapter_source_summary=chapter_source_summary,
        visual_toc_conflict_count=visual_toc_conflict_count,
        toc_alignment_summary=toc_alignment_summary,
        toc_semantic_summary=toc_semantic_summary,
        toc_role_summary=toc_role_summary,
        container_titles=container_titles,
        post_body_titles=post_body_titles,
        back_matter_titles=back_matter_titles,
        visual_toc_endnotes_summary=visual_toc_endnotes_summary,
        toc_semantic_contract_ok=toc_semantic_contract_ok,
        toc_semantic_blocking_reasons=toc_semantic_blocking_reasons,
        chapter_title_alignment_ok=chapter_title_alignment_ok,
        chapter_section_alignment_ok=chapter_section_alignment_ok,
        manual_toc_ready=bool(manual_toc_ready),
        manual_toc_required=not bool(manual_toc_ready),
        manual_toc_summary=dict(manual_toc_summary or {}),
        page_count=int(page_count),
        chapter_count=int(chapter_count),
        section_head_count=int(section_head_count),
        chapter_progress_summary=chapter_progress_summary,
        note_region_progress_summary=note_region_progress_summary,
        chapter_binding_summary=chapter_binding_summary,
        note_capture_summary=note_capture_summary,
        footnote_synthesis_summary=footnote_synthesis_summary,
        chapter_link_contract_summary=chapter_link_contract_summary,
        book_endnote_stream_summary=book_endnote_stream_summary,
        freeze_note_unit_summary=freeze_note_unit_summary,
        chapter_issue_counts=chapter_issue_counts,
        chapter_issue_summary=chapter_issue_summary,
        export_drift_summary=export_drift_summary,
        chapter_local_endnote_contract_ok=bool(merge_hard.get("merge.local_refs_closed", False)),
        export_semantic_contract_ok=bool(export_hard.get("export.semantic_contract_ok", False)),
        front_matter_leak_detected=bool(export_semantic_summary.get("front_matter_leak_detected", False)),
        toc_residue_detected=bool(export_semantic_summary.get("toc_residue_detected", False)),
        mid_paragraph_heading_detected=bool(export_semantic_summary.get("mid_paragraph_heading_detected", False)),
        duplicate_paragraph_detected=bool(export_semantic_summary.get("duplicate_paragraph_detected", False)),
        export_ready_test=export_ready,
        export_ready_real=export_ready,
    )


def build_phase6_status(phase6: Phase6Structure) -> StructureStatusRecord:
    base_status = phase6.status or StructureStatusRecord(structure_state="idle")
    override_summary = dict(getattr(phase6.summary, "override_summary", {}) or {})
    pipeline_state = str(override_summary.get("pipeline_state") or "done").strip().lower()
    if not is_valid_pipeline_state(pipeline_state):
        pipeline_state = "done"

    chapter_progress_summary, note_region_progress_summary = _build_owner_progress_summaries(phase6)
    chapter_local_endnote_contract_ok, chapter_contract_items = _chapter_local_ref_contract_summary(phase6)
    export_drift_summary = _build_export_drift_summary(phase6)
    export_drift_summary["chapter_contract_preview"] = chapter_contract_items[:8]
    export_semantic_contract_ok = bool(phase6.export_bundle.export_semantic_contract_ok)

    blocking_reasons = list(base_status.blocking_reasons or [])
    if pipeline_state not in {"idle", "running", "error"}:
        if not chapter_local_endnote_contract_ok:
            blocking_reasons.append("local_note_contract_broken")
        if not export_semantic_contract_ok:
            blocking_reasons.append("export_semantic_contract_broken")
        if not bool(phase6.export_audit.can_ship):
            blocking_reasons.append("export_audit_blocking")
    blocking_reasons = _dedupe_preserve_order(blocking_reasons)

    if pipeline_state == "idle":
        structure_state = "idle"
    elif pipeline_state == "running":
        structure_state = "running"
    elif pipeline_state == "error":
        structure_state = "error"
    else:
        structure_state = "ready" if not blocking_reasons else "review_required"

    export_ready = bool(
        pipeline_state == "done"
        and bool(phase6.export_bundle.chapters)
        and structure_state == "ready"
        and chapter_local_endnote_contract_ok
        and export_semantic_contract_ok
        and bool(phase6.export_audit.can_ship)
    )

    return replace(
        base_status,
        structure_state=structure_state,
        blocking_reasons=blocking_reasons,
        page_count=len(phase6.pages),
        chapter_count=len(phase6.chapters),
        section_head_count=len(phase6.section_heads),
        review_count=len(phase6.structure_reviews),
        chapter_progress_summary=chapter_progress_summary,
        note_region_progress_summary=note_region_progress_summary,
        export_drift_summary=export_drift_summary,
        chapter_local_endnote_contract_ok=bool(chapter_local_endnote_contract_ok),
        export_semantic_contract_ok=export_semantic_contract_ok,
        front_matter_leak_detected=bool(phase6.export_bundle.front_matter_leak_detected),
        toc_residue_detected=bool(phase6.export_bundle.toc_residue_detected),
        mid_paragraph_heading_detected=bool(phase6.export_bundle.mid_paragraph_heading_detected),
        duplicate_paragraph_detected=bool(phase6.export_bundle.duplicate_paragraph_detected),
        export_ready_test=export_ready,
        export_ready_real=export_ready,
    )

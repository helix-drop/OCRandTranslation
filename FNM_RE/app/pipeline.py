"""FNM_RE 分阶段总入口。"""

from __future__ import annotations

import copy
import re
import time
from dataclasses import dataclass, replace
from collections import Counter
from typing import Any, Callable, Mapping

from FNM_RE.constants import is_valid_pipeline_state
from FNM_RE.models import (
    ExportAuditFileRecord,
    ExportAuditReportRecord,
    ExportBundleRecord,
    ExportChapterRecord,
    BodyAnchorRecord,
    ChapterRecord,
    ChapterNoteModeRecord,
    NoteItemRecord,
    NoteLinkRecord,
    NoteRegionRecord,
    PagePartitionRecord,
    Phase1Structure,
    Phase1Summary,
    Phase2Structure,
    Phase2Summary,
    Phase3Structure,
    Phase3Summary,
    Phase4Structure,
    Phase4Summary,
    Phase6Structure,
    Phase6Summary,
    Phase5Structure,
    Phase5Summary,
    StructureReviewRecord,
    StructureStatusRecord,
    SectionHeadRecord,
    TranslationUnitRecord,
    UnitPageSegmentRecord,
    UnitParagraphRecord,
)
from FNM_RE.modules.book_assemble import build_export_bundle as build_module_export_bundle
from FNM_RE.modules.book_note_type import build_book_note_profile
from FNM_RE.modules.chapter_merge import build_chapter_markdown_set
from FNM_RE.modules.chapter_split import build_chapter_layers
from FNM_RE.modules.contracts import ModuleResult
from FNM_RE.modules.note_linking import build_note_link_table
from FNM_RE.modules.ref_freeze import build_frozen_units
from FNM_RE.modules.toc_structure import build_toc_structure
from FNM_RE.modules.types import (
    BookNoteProfile,
    ChapterLayers,
    ChapterMarkdownSet,
    ExportBundle,
    FrozenUnits,
    LayerNoteItem,
    LayerNoteRegion,
    NoteLinkTable,
    TocStructure,
)
from FNM_RE.shared.notes import normalize_note_marker
from FNM_RE.stages.export import build_export_bundle
from FNM_RE.stages.export_audit import audit_phase6_export
from FNM_RE.stages.body_anchors import build_body_anchors
from FNM_RE.stages.chapter_skeleton import build_chapter_skeleton
from FNM_RE.stages.diagnostics import build_diagnostic_projection
from FNM_RE.stages.note_items import build_note_items
from FNM_RE.stages.note_links import build_note_links
from FNM_RE.stages.note_regions import build_note_regions
from FNM_RE.stages.page_partition import build_page_partitions, summarize_page_partitions
from FNM_RE.stages.reviews import build_structure_reviews
from FNM_RE.stages.section_heads import build_section_heads
from FNM_RE.stages.units import build_translation_units
from FNM_RE.status import build_module_gate_status, build_phase4_status, build_phase6_status


def build_phase1_structure(
    pages: list[dict],
    *,
    toc_items: list[dict] | None = None,
    toc_offset: int = 0,
    page_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    pdf_path: str = "",
    visual_toc_bundle: Mapping[str, Any] | None = None,
) -> Phase1Structure:
    page_partitions = build_page_partitions(
        pages,
        page_overrides=page_overrides,
    )
    heading_candidates, chapters, chapter_meta = build_chapter_skeleton(
        page_partitions,
        toc_items=toc_items,
        toc_offset=int(toc_offset or 0),
        pdf_path=str(pdf_path or ""),
        pages=pages,
        visual_toc_bundle=visual_toc_bundle,
    )
    section_heads, heading_review_summary = build_section_heads(
        chapters,
        heading_candidates,
        page_partitions,
        fallback_sections=list(chapter_meta.get("fallback_sections") or []),
    )
    summary = Phase1Summary(
        page_partition_summary=summarize_page_partitions(page_partitions),
        heading_review_summary=heading_review_summary,
        heading_graph_summary=dict(chapter_meta.get("heading_graph_summary") or {}),
        chapter_source_summary=dict(chapter_meta.get("chapter_source_summary") or {}),
        visual_toc_conflict_count=int(chapter_meta.get("visual_toc_conflict_count") or 0),
        toc_alignment_summary=dict(chapter_meta.get("toc_alignment_summary") or {}),
        toc_semantic_summary=dict(chapter_meta.get("toc_semantic_summary") or {}),
        toc_role_summary=dict(chapter_meta.get("toc_role_summary") or {}),
        container_titles=list(chapter_meta.get("container_titles") or []),
        post_body_titles=list(chapter_meta.get("post_body_titles") or []),
        back_matter_titles=list(chapter_meta.get("back_matter_titles") or []),
        chapter_title_alignment_ok=bool(chapter_meta.get("chapter_title_alignment_ok", True)),
        chapter_section_alignment_ok=bool(chapter_meta.get("chapter_section_alignment_ok", True)),
        toc_semantic_contract_ok=bool(chapter_meta.get("toc_semantic_contract_ok", True)),
        toc_semantic_blocking_reasons=list(chapter_meta.get("toc_semantic_blocking_reasons") or []),
        visual_toc_endnotes_summary=dict(chapter_meta.get("visual_toc_endnotes_summary") or {}),
    )
    return Phase1Structure(
        pages=page_partitions,
        heading_candidates=heading_candidates,
        chapters=chapters,
        section_heads=section_heads,
        endnote_explorer_hints=dict(chapter_meta.get("endnote_explorer_hints") or {}),
        summary=summary,
    )


def _build_chapter_note_modes(
    phase1: Phase1Structure,
    *,
    note_regions: list[NoteRegionRecord],
    note_item_summary: Mapping[str, Any],
) -> tuple[list[ChapterNoteModeRecord], dict[str, Any]]:
    marker_alignment_failures = list(note_item_summary.get("marker_alignment_failures") or [])
    review_chapters = {
        str(failure.get("chapter_id") or "").strip()
        for failure in marker_alignment_failures
        if str(failure.get("chapter_id") or "").strip()
    }
    for region in note_regions:
        if region.review_required and str(region.chapter_id or "").strip():
            review_chapters.add(str(region.chapter_id or "").strip())

    rows: list[ChapterNoteModeRecord] = []
    for chapter in phase1.chapters:
        chapter_id = chapter.chapter_id
        footnote_regions = [
            region.region_id
            for region in note_regions
            if region.chapter_id == chapter_id and region.note_kind == "footnote"
        ]
        chapter_endnote_regions = [
            region.region_id
            for region in note_regions
            if region.chapter_id == chapter_id and region.note_kind == "endnote" and region.scope == "chapter"
        ]
        book_endnote_regions = [
            region.region_id
            for region in note_regions
            if region.chapter_id == chapter_id and region.note_kind == "endnote" and region.scope == "book"
        ]
        region_ids = sorted({*footnote_regions, *chapter_endnote_regions, *book_endnote_regions})
        if footnote_regions:
            note_mode = "footnote_primary"
            primary_scope = "chapter"
        elif chapter_endnote_regions:
            note_mode = "chapter_endnote_primary"
            primary_scope = "chapter"
        elif book_endnote_regions:
            note_mode = "book_endnote_bound"
            primary_scope = "book"
        else:
            note_mode = "no_notes"
            primary_scope = ""
        has_conflict = bool(footnote_regions and (chapter_endnote_regions or book_endnote_regions))
        if has_conflict or chapter_id in review_chapters:
            note_mode = "review_required"
        rows.append(
            ChapterNoteModeRecord(
                chapter_id=chapter_id,
                note_mode=note_mode,  # type: ignore[arg-type]
                region_ids=region_ids,
                primary_region_scope=primary_scope,
                has_footnote_band=bool(footnote_regions),
                has_endnote_region=bool(chapter_endnote_regions or book_endnote_regions),
            )
        )
    counts = Counter(row.note_mode for row in rows)
    summary = {
        "mode_counts": dict(counts),
        "review_required_chapters": [row.chapter_id for row in rows if row.note_mode == "review_required"],
    }
    return rows, summary


def _assemble_phase2_summary(
    *,
    phase1_summary: Phase1Summary,
    note_region_summary: Mapping[str, Any],
    note_item_summary: Mapping[str, Any],
    chapter_note_mode_summary: Mapping[str, Any],
) -> Phase2Summary:
    marker_alignment_failures = list(note_item_summary.get("marker_alignment_failures") or [])
    review_flags: list[str] = []
    review_flags.extend(str(flag) for flag in note_region_summary.get("review_flags") or [])
    review_flags.extend(f"empty_region:{region_id}" for region_id in note_item_summary.get("empty_region_ids") or [])
    review_flags.extend(
        f"marker_alignment:{failure.get('region_id')}"
        for failure in marker_alignment_failures
        if str(failure.get("region_id") or "").strip()
    )
    review_flags.extend(
        f"chapter_mode:{chapter_id}"
        for chapter_id in chapter_note_mode_summary.get("review_required_chapters") or []
        if str(chapter_id or "").strip()
    )
    review_flags = list(dict.fromkeys(review_flags))
    alignment_ok = bool(note_region_summary.get("chapter_endnote_region_alignment_ok", True))
    alignment_ok = alignment_ok and not marker_alignment_failures
    return Phase2Summary(
        page_partition_summary=dict(phase1_summary.page_partition_summary or {}),
        heading_review_summary=dict(phase1_summary.heading_review_summary or {}),
        heading_graph_summary=dict(phase1_summary.heading_graph_summary or {}),
        chapter_source_summary=dict(phase1_summary.chapter_source_summary or {}),
        visual_toc_conflict_count=int(phase1_summary.visual_toc_conflict_count or 0),
        toc_alignment_summary=dict(phase1_summary.toc_alignment_summary or {}),
        toc_semantic_summary=dict(phase1_summary.toc_semantic_summary or {}),
        toc_role_summary=dict(phase1_summary.toc_role_summary or {}),
        container_titles=list(phase1_summary.container_titles or []),
        post_body_titles=list(phase1_summary.post_body_titles or []),
        back_matter_titles=list(phase1_summary.back_matter_titles or []),
        chapter_title_alignment_ok=bool(phase1_summary.chapter_title_alignment_ok),
        chapter_section_alignment_ok=bool(phase1_summary.chapter_section_alignment_ok),
        toc_semantic_contract_ok=bool(phase1_summary.toc_semantic_contract_ok),
        toc_semantic_blocking_reasons=list(phase1_summary.toc_semantic_blocking_reasons or []),
        note_region_summary=dict(note_region_summary or {}),
        note_item_summary=dict(note_item_summary or {}),
        chapter_note_mode_summary=dict(chapter_note_mode_summary or {}),
        chapter_endnote_region_alignment_ok=bool(alignment_ok),
        chapter_endnote_start_page_map=dict(note_region_summary.get("chapter_endnote_start_page_map") or {}),
        review_flags=review_flags,
        visual_toc_endnotes_summary=dict(phase1_summary.visual_toc_endnotes_summary or {}),
    )


def build_phase2_structure(
    pages: list[dict],
    *,
    toc_items: list[dict] | None = None,
    toc_offset: int = 0,
    page_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    pdf_path: str = "",
    page_text_map: Mapping[int | str, str] | None = None,
    visual_toc_bundle: Mapping[str, Any] | None = None,
) -> Phase2Structure:
    phase1 = build_phase1_structure(
        pages,
        toc_items=toc_items,
        toc_offset=int(toc_offset or 0),
        page_overrides=page_overrides,
        pdf_path=str(pdf_path or ""),
        visual_toc_bundle=visual_toc_bundle,
    )
    note_regions, note_region_summary = build_note_regions(
        phase1,
        pages=pages,
        pdf_path=str(pdf_path or ""),
        page_text_map=page_text_map,
        endnote_explorer_hints=phase1.endnote_explorer_hints,
    )
    note_items, note_item_summary = build_note_items(
        note_regions,
        phase1,
        pages=pages,
        pdf_path=str(pdf_path or ""),
        page_text_map=page_text_map,
    )
    chapter_note_modes, chapter_note_mode_summary = _build_chapter_note_modes(
        phase1,
        note_regions=note_regions,
        note_item_summary=note_item_summary,
    )
    summary = _assemble_phase2_summary(
        phase1_summary=phase1.summary,
        note_region_summary=note_region_summary,
        note_item_summary=note_item_summary,
        chapter_note_mode_summary=chapter_note_mode_summary,
    )
    return Phase2Structure(
        pages=phase1.pages,
        heading_candidates=phase1.heading_candidates,
        chapters=phase1.chapters,
        section_heads=phase1.section_heads,
        note_regions=note_regions,
        note_items=note_items,
        chapter_note_modes=chapter_note_modes,
        summary=summary,
    )


def _refresh_body_anchor_summary(
    *,
    base_summary: Mapping[str, Any],
    body_anchors: list[Any],
) -> dict[str, Any]:
    kind_counts = Counter(str(row.anchor_kind) for row in body_anchors)
    total_count = len(body_anchors)
    synthetic_count = sum(1 for row in body_anchors if bool(row.synthetic))
    explicit_count = total_count - synthetic_count
    uncertain_count = sum(
        1
        for row in body_anchors
        if str(row.anchor_kind) == "unknown" or float(row.certainty) < 1.0
    )
    ocr_repaired_count = sum(
        1 for row in body_anchors if str(row.ocr_repaired_from_marker or "").strip()
    )
    return {
        **dict(base_summary or {}),
        "total_count": int(total_count),
        "explicit_count": int(explicit_count),
        "synthetic_count": int(synthetic_count),
        "kind_counts": dict(kind_counts),
        "uncertain_count": int(uncertain_count),
        "ocr_repaired_count": int(ocr_repaired_count),
    }


def _assemble_phase3_summary(
    *,
    phase2: Phase2Structure,
    body_anchor_summary: Mapping[str, Any],
    note_link_meta: Mapping[str, Any],
) -> Phase3Summary:
    note_link_summary = dict(note_link_meta.get("note_link_summary") or {})
    review_seed_summary = dict(note_link_meta.get("review_seed_summary") or {})
    review_flags: list[str] = []
    review_flags.extend(str(flag) for flag in (phase2.summary.review_flags or []))
    review_flags.extend(f"orphan_link:{link_id}" for link_id in review_seed_summary.get("orphan_link_ids") or [])
    review_flags.extend(f"ambiguous_link:{link_id}" for link_id in review_seed_summary.get("ambiguous_link_ids") or [])
    review_flags.extend(f"synthetic_anchor:{anchor_id}" for anchor_id in review_seed_summary.get("synthetic_anchor_ids") or [])
    review_flags = list(dict.fromkeys(review_flags))
    return Phase3Summary(
        page_partition_summary=dict(phase2.summary.page_partition_summary or {}),
        heading_review_summary=dict(phase2.summary.heading_review_summary or {}),
        heading_graph_summary=dict(phase2.summary.heading_graph_summary or {}),
        chapter_source_summary=dict(phase2.summary.chapter_source_summary or {}),
        visual_toc_conflict_count=int(phase2.summary.visual_toc_conflict_count or 0),
        toc_alignment_summary=dict(phase2.summary.toc_alignment_summary or {}),
        toc_semantic_summary=dict(phase2.summary.toc_semantic_summary or {}),
        toc_role_summary=dict(phase2.summary.toc_role_summary or {}),
        container_titles=list(phase2.summary.container_titles or []),
        post_body_titles=list(phase2.summary.post_body_titles or []),
        back_matter_titles=list(phase2.summary.back_matter_titles or []),
        chapter_title_alignment_ok=bool(phase2.summary.chapter_title_alignment_ok),
        chapter_section_alignment_ok=bool(phase2.summary.chapter_section_alignment_ok),
        toc_semantic_contract_ok=bool(phase2.summary.toc_semantic_contract_ok),
        toc_semantic_blocking_reasons=list(phase2.summary.toc_semantic_blocking_reasons or []),
        note_region_summary=dict(phase2.summary.note_region_summary or {}),
        note_item_summary=dict(phase2.summary.note_item_summary or {}),
        chapter_note_mode_summary=dict(phase2.summary.chapter_note_mode_summary or {}),
        chapter_endnote_region_alignment_ok=bool(phase2.summary.chapter_endnote_region_alignment_ok),
        chapter_endnote_start_page_map=dict(phase2.summary.chapter_endnote_start_page_map or {}),
        body_anchor_summary=dict(body_anchor_summary or {}),
        note_link_summary=note_link_summary,
        review_seed_summary=review_seed_summary,
        review_flags=review_flags,
    )


def build_phase3_structure(
    pages: list[dict],
    *,
    toc_items: list[dict] | None = None,
    toc_offset: int = 0,
    page_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    pdf_path: str = "",
    page_text_map: Mapping[int | str, str] | None = None,
    visual_toc_bundle: Mapping[str, Any] | None = None,
) -> Phase3Structure:
    phase2 = build_phase2_structure(
        pages,
        toc_items=toc_items,
        toc_offset=int(toc_offset or 0),
        page_overrides=page_overrides,
        pdf_path=str(pdf_path or ""),
        page_text_map=page_text_map,
        visual_toc_bundle=visual_toc_bundle,
    )
    body_anchors, body_anchor_summary = build_body_anchors(phase2, pages=pages)
    enhanced_anchors, note_links, note_link_meta = build_note_links(body_anchors, phase2, pages=pages)
    refreshed_body_anchor_summary = _refresh_body_anchor_summary(
        base_summary=body_anchor_summary,
        body_anchors=enhanced_anchors,
    )
    summary = _assemble_phase3_summary(
        phase2=phase2,
        body_anchor_summary=refreshed_body_anchor_summary,
        note_link_meta=note_link_meta,
    )
    return Phase3Structure(
        pages=phase2.pages,
        heading_candidates=phase2.heading_candidates,
        chapters=phase2.chapters,
        section_heads=phase2.section_heads,
        note_regions=phase2.note_regions,
        note_items=phase2.note_items,
        chapter_note_modes=phase2.chapter_note_modes,
        body_anchors=enhanced_anchors,
        note_links=note_links,
        summary=summary,
    )


def _empty_grouped_overrides() -> dict[str, dict[str, dict]]:
    return {
        "page": {},
        "chapter": {},
        "region": {},
        "link": {},
        "llm_suggestion": {},
        "anchor": {},
        "note_item": {},
    }


def _group_review_overrides(review_overrides: Any) -> dict[str, dict[str, dict]]:
    grouped = _empty_grouped_overrides()
    if not review_overrides:
        return grouped
    if isinstance(review_overrides, list):
        for row in review_overrides:
            payload = dict(row or {})
            scope = str(payload.get("scope") or "").strip().lower()
            target_id = str(payload.get("target_id") or "").strip()
            data = dict(payload.get("payload") or {})
            if not scope or not target_id:
                continue
            grouped.setdefault(scope, {})[target_id] = data
        return grouped
    if isinstance(review_overrides, Mapping):
        known_scopes = {"page", "chapter", "region", "link", "llm_suggestion", "anchor", "note_item"}
        if any(str(key) in known_scopes for key in review_overrides.keys()):
            for scope, rows in dict(review_overrides).items():
                scope_key = str(scope or "").strip().lower()
                if scope_key not in known_scopes:
                    continue
                if not isinstance(rows, Mapping):
                    continue
                grouped[scope_key] = {
                    str(target_id): dict(payload or {})
                    for target_id, payload in dict(rows).items()
                    if str(target_id or "").strip()
                }
            return grouped
    return grouped


def _extract_page_overrides(grouped_overrides: Mapping[str, dict[str, dict]]) -> dict[str, dict]:
    page_override_rows = dict(grouped_overrides.get("page") or {})
    extracted: dict[str, dict] = {}
    for target_id, payload in page_override_rows.items():
        data = dict(payload or {})
        page_no = str(data.get("page_no") or target_id or "").strip()
        role = str(data.get("page_role") or "").strip()
        if not page_no or not role:
            continue
        extracted[page_no] = {"page_role": role}
    return extracted


def _apply_anchor_overrides(
    body_anchors: list[BodyAnchorRecord],
    *,
    anchor_overrides: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[list[BodyAnchorRecord], dict[str, Any]]:
    """把 scope='anchor' 的 override（主要来自 LLM synthesize_anchor）合入 body_anchors。

    - action='create'：根据 payload 构造 BodyAnchorRecord 并追加；若 anchor_id 已存在则跳过。
    - 其它 action：忽略（当前只支持创建；删除/修改留给后续）。
    """
    effective_anchors: list[BodyAnchorRecord] = list(body_anchors or [])
    overrides = dict(anchor_overrides or {})
    existing_ids = {str(a.anchor_id) for a in effective_anchors if str(a.anchor_id or "").strip()}
    created_count = 0
    skipped_duplicate = 0
    invalid_count = 0
    invalid_flags: list[str] = []
    for target_id, payload in overrides.items():
        data = dict(payload or {})
        action = str(data.get("action") or "").strip().lower()
        if action != "create":
            continue
        anchor_id = str(data.get("anchor_id") or target_id or "").strip()
        if not anchor_id:
            invalid_count += 1
            invalid_flags.append(f"invalid_anchor_override:{target_id}:no_id")
            continue
        if anchor_id in existing_ids:
            skipped_duplicate += 1
            continue
        try:
            page_no = int(data.get("page_no") or 0)
        except (TypeError, ValueError):
            page_no = 0
        try:
            paragraph_index = int(data.get("paragraph_index") or 0)
        except (TypeError, ValueError):
            paragraph_index = 0
        try:
            char_start = int(data.get("char_start") or 0)
        except (TypeError, ValueError):
            char_start = 0
        try:
            char_end = int(data.get("char_end") or 0)
        except (TypeError, ValueError):
            char_end = 0
        try:
            certainty = float(data.get("certainty") or 0.0)
        except (TypeError, ValueError):
            certainty = 0.0
        record = BodyAnchorRecord(
            anchor_id=anchor_id,
            chapter_id=str(data.get("chapter_id") or ""),
            page_no=page_no,
            paragraph_index=paragraph_index,
            char_start=char_start,
            char_end=char_end,
            source_marker=str(data.get("source_marker") or data.get("normalized_marker") or ""),
            normalized_marker=str(data.get("normalized_marker") or ""),
            anchor_kind=str(data.get("anchor_kind") or "endnote"),  # type: ignore[arg-type]
            certainty=certainty,
            source_text=str(data.get("source_text") or ""),
            source=str(data.get("source") or "llm"),
            synthetic=bool(data.get("synthetic") or False),
            ocr_repaired_from_marker=str(data.get("ocr_repaired_from_marker") or ""),
        )
        effective_anchors.append(record)
        existing_ids.add(anchor_id)
        created_count += 1
    summary = {
        "created_anchor_count": created_count,
        "skipped_duplicate_count": skipped_duplicate,
        "invalid_anchor_override_count": invalid_count,
        "invalid_anchor_override_flags": invalid_flags,
    }
    return effective_anchors, summary


def _apply_link_overrides(
    note_links: list[NoteLinkRecord],
    *,
    link_overrides: Mapping[str, Mapping[str, Any]] | None,
    note_items: list[NoteItemRecord],
    body_anchors: list[BodyAnchorRecord],
    note_regions: list[NoteRegionRecord],
) -> tuple[list[NoteLinkRecord], dict[str, Any]]:
    effective_links: list[NoteLinkRecord] = [replace(link) for link in note_links]
    overrides = dict(link_overrides or {})
    note_items_by_id = {str(item.note_item_id): item for item in note_items if str(item.note_item_id or "").strip()}
    anchors_by_id = {str(item.anchor_id): item for item in body_anchors if str(item.anchor_id or "").strip()}
    regions_by_id = {str(item.region_id): item for item in note_regions if str(item.region_id or "").strip()}

    ignored_count = 0
    invalid_count = 0
    match_count = 0
    invalid_flags: list[str] = []
    matched_pairs: set[tuple[str, str]] = set()

    for index, link in enumerate(effective_links):
        override = dict(overrides.get(str(link.link_id or ""), {}) or {})
        if not override:
            continue
        action = str(override.get("action") or "").strip().lower()
        if action == "ignore":
            ignored_count += 1
            effective_links[index] = replace(
                link,
                status="ignored",  # type: ignore[arg-type]
                resolver="repair",  # type: ignore[arg-type]
                confidence=1.0,
            )
            continue
        if action != "match":
            invalid_count += 1
            invalid_flags.append(f"invalid_link_override:{link.link_id}:action")
            continue
        note_item_id = str(override.get("note_item_id") or override.get("definition_id") or "").strip()
        anchor_id = str(override.get("anchor_id") or override.get("ref_id") or "").strip()
        note_item = note_items_by_id.get(note_item_id)
        anchor = anchors_by_id.get(anchor_id)
        if not note_item or not anchor:
            invalid_count += 1
            invalid_flags.append(f"invalid_link_override:{link.link_id}:target")
            continue
        region = regions_by_id.get(str(note_item.region_id or ""))
        note_kind = str((region.note_kind if region else link.note_kind) or "")
        marker = str(note_item.marker or anchor.normalized_marker or link.marker or "")
        page_no = int(anchor.page_no or note_item.page_no or link.page_no_start or 0)
        chapter_id = str(note_item.chapter_id or anchor.chapter_id or link.chapter_id or "")
        match_count += 1
        matched_pairs.add((str(note_item.note_item_id or ""), str(anchor.anchor_id or "")))
        effective_links[index] = replace(
            link,
            chapter_id=chapter_id,
            region_id=str(note_item.region_id or ""),
            note_item_id=str(note_item.note_item_id or ""),
            anchor_id=str(anchor.anchor_id or ""),
            status="matched",  # type: ignore[arg-type]
            resolver="repair",  # type: ignore[arg-type]
            confidence=1.0,
            note_kind=note_kind,  # type: ignore[arg-type]
            marker=marker,
            page_no_start=page_no,
            page_no_end=page_no,
        )

    if matched_pairs:
        for index, link in enumerate(effective_links):
            if str(link.status or "") == "matched":
                continue
            note_item_id = str(link.note_item_id or "").strip()
            anchor_id = str(link.anchor_id or "").strip()
            if any(
                (note_item_id and note_item_id == matched_note_item_id)
                or (anchor_id and anchor_id == matched_anchor_id)
                for matched_note_item_id, matched_anchor_id in matched_pairs
            ):
                ignored_count += 1
                effective_links[index] = replace(
                    link,
                    status="ignored",  # type: ignore[arg-type]
                    resolver="repair",  # type: ignore[arg-type]
                    confidence=1.0,
                )
    override_summary = {
        "ignored_link_override_count": int(ignored_count),
        "invalid_override_count": int(invalid_count),
        "matched_link_override_count": int(match_count),
        "invalid_override_flags": invalid_flags,
    }
    return effective_links, override_summary


def _phase4_review_seed_summary(
    *,
    chapter_note_modes: list[ChapterNoteModeRecord],
    body_anchors: list[BodyAnchorRecord],
    effective_note_links: list[NoteLinkRecord],
) -> dict[str, Any]:
    return {
        "boundary_review_required_count": sum(
            1 for row in chapter_note_modes if str(row.note_mode or "") == "review_required"
        ),
        "uncertain_anchor_ids": [
            row.anchor_id
            for row in body_anchors
            if str(row.anchor_kind or "") == "unknown" or float(row.certainty or 1.0) < 1.0
        ],
        "orphan_link_ids": [
            row.link_id
            for row in effective_note_links
            if str(row.status or "") in {"orphan_note", "orphan_anchor"}
        ],
        "ambiguous_link_ids": [
            row.link_id
            for row in effective_note_links
            if str(row.status or "") == "ambiguous"
        ],
        "synthetic_anchor_ids": [row.anchor_id for row in body_anchors if bool(row.synthetic)],
    }


def _assemble_phase4_summary(
    *,
    phase3: Phase3Structure,
    effective_note_links: list[NoteLinkRecord],
    structure_reviews: list[StructureReviewRecord],
    review_summary: Mapping[str, Any],
    override_summary: Mapping[str, Any],
) -> Phase4Summary:
    review_seed_summary = _phase4_review_seed_summary(
        chapter_note_modes=phase3.chapter_note_modes,
        body_anchors=phase3.body_anchors,
        effective_note_links=effective_note_links,
    )
    review_flags: list[str] = []
    review_flags.extend(str(flag) for flag in (phase3.summary.review_flags or []))
    review_flags.extend(str(flag) for flag in (override_summary.get("invalid_override_flags") or []))
    review_flags.extend(f"review:{row.review_id}" for row in structure_reviews if row.severity == "error")
    review_flags = list(dict.fromkeys(review_flags))

    return Phase4Summary(
        page_partition_summary=dict(phase3.summary.page_partition_summary or {}),
        heading_review_summary=dict(phase3.summary.heading_review_summary or {}),
        heading_graph_summary=dict(phase3.summary.heading_graph_summary or {}),
        chapter_source_summary=dict(phase3.summary.chapter_source_summary or {}),
        visual_toc_conflict_count=int(phase3.summary.visual_toc_conflict_count or 0),
        toc_alignment_summary=dict(phase3.summary.toc_alignment_summary or {}),
        toc_semantic_summary=dict(phase3.summary.toc_semantic_summary or {}),
        toc_role_summary=dict(phase3.summary.toc_role_summary or {}),
        container_titles=list(phase3.summary.container_titles or []),
        post_body_titles=list(phase3.summary.post_body_titles or []),
        back_matter_titles=list(phase3.summary.back_matter_titles or []),
        chapter_title_alignment_ok=bool(phase3.summary.chapter_title_alignment_ok),
        chapter_section_alignment_ok=bool(phase3.summary.chapter_section_alignment_ok),
        toc_semantic_contract_ok=bool(phase3.summary.toc_semantic_contract_ok),
        toc_semantic_blocking_reasons=list(phase3.summary.toc_semantic_blocking_reasons or []),
        note_region_summary=dict(phase3.summary.note_region_summary or {}),
        note_item_summary=dict(phase3.summary.note_item_summary or {}),
        chapter_note_mode_summary=dict(phase3.summary.chapter_note_mode_summary or {}),
        chapter_endnote_region_alignment_ok=bool(phase3.summary.chapter_endnote_region_alignment_ok),
        chapter_endnote_start_page_map=dict(phase3.summary.chapter_endnote_start_page_map or {}),
        body_anchor_summary=dict(phase3.summary.body_anchor_summary or {}),
        note_link_summary={
            "matched": sum(1 for row in effective_note_links if str(row.status or "") == "matched"),
            "footnote_orphan_note": sum(
                1 for row in effective_note_links if str(row.status or "") == "orphan_note" and str(row.note_kind or "") == "footnote"
            ),
            "footnote_orphan_anchor": sum(
                1 for row in effective_note_links if str(row.status or "") == "orphan_anchor" and str(row.note_kind or "") == "footnote"
            ),
            "endnote_orphan_note": sum(
                1 for row in effective_note_links if str(row.status or "") == "orphan_note" and str(row.note_kind or "") == "endnote"
            ),
            "endnote_orphan_anchor": sum(
                1 for row in effective_note_links if str(row.status or "") == "orphan_anchor" and str(row.note_kind or "") == "endnote"
            ),
            "ambiguous": sum(1 for row in effective_note_links if str(row.status or "") == "ambiguous"),
            "ignored": sum(1 for row in effective_note_links if str(row.status or "") == "ignored"),
        },
        review_seed_summary=review_seed_summary,
        review_type_counts=dict(review_summary.get("review_type_counts") or {}),
        override_summary=dict(override_summary or {}),
        review_flags=review_flags,
    )


def build_phase4_structure(
    pages: list[dict],
    *,
    toc_items: list[dict] | None = None,
    toc_offset: int = 0,
    review_overrides: Any = None,
    pdf_path: str = "",
    page_text_map: Mapping[int | str, str] | None = None,
    manual_toc_ready: bool = True,
    manual_toc_summary: Mapping[str, Any] | None = None,
    pipeline_state: str = "done",
    visual_toc_bundle: Mapping[str, Any] | None = None,
) -> Phase4Structure:
    grouped_overrides = _group_review_overrides(review_overrides)
    page_overrides = _extract_page_overrides(grouped_overrides)
    phase3 = build_phase3_structure(
        pages,
        toc_items=toc_items,
        toc_offset=int(toc_offset or 0),
        page_overrides=page_overrides,
        pdf_path=str(pdf_path or ""),
        page_text_map=page_text_map,
        visual_toc_bundle=visual_toc_bundle,
    )

    effective_body_anchors, anchor_override_summary = _apply_anchor_overrides(
        phase3.body_anchors,
        anchor_overrides=grouped_overrides.get("anchor"),
    )
    if int(anchor_override_summary.get("created_anchor_count") or 0) > 0:
        # 让后续 phase / 最终 DB 持久化都能看见 LLM 合成的 anchor。
        phase3.body_anchors = effective_body_anchors
    effective_note_links, link_override_summary = _apply_link_overrides(
        phase3.note_links,
        link_overrides=grouped_overrides.get("link"),
        note_items=phase3.note_items,
        body_anchors=effective_body_anchors,
        note_regions=phase3.note_regions,
    )
    unsupported_scopes = [
        scope
        for scope in ("chapter", "region", "llm_suggestion")
        if dict(grouped_overrides.get(scope) or {})
    ]
    normalized_pipeline_state = str(pipeline_state or "").strip().lower()
    if not is_valid_pipeline_state(normalized_pipeline_state):
        normalized_pipeline_state = "done"
    override_summary = {
        **dict(link_override_summary or {}),
        **dict(anchor_override_summary or {}),
        "unsupported_scopes": unsupported_scopes,
        "manual_toc_ready": bool(manual_toc_ready),
        "manual_toc_summary": dict(manual_toc_summary or {}),
        "pipeline_state": normalized_pipeline_state,
    }

    structure_reviews, review_summary = build_structure_reviews(
        phase3,
        effective_note_links=effective_note_links,
        ignored_link_override_count=int(link_override_summary.get("ignored_link_override_count", 0) or 0),
        invalid_override_count=int(link_override_summary.get("invalid_override_count", 0) or 0),
    )
    summary = _assemble_phase4_summary(
        phase3=phase3,
        effective_note_links=effective_note_links,
        structure_reviews=structure_reviews,
        review_summary=review_summary,
        override_summary=override_summary,
    )
    phase4 = Phase4Structure(
        pages=phase3.pages,
        heading_candidates=phase3.heading_candidates,
        chapters=phase3.chapters,
        section_heads=phase3.section_heads,
        note_regions=phase3.note_regions,
        note_items=phase3.note_items,
        chapter_note_modes=phase3.chapter_note_modes,
        body_anchors=phase3.body_anchors,
        note_links=phase3.note_links,
        effective_note_links=effective_note_links,
        structure_reviews=structure_reviews,
        status=StructureStatusRecord(structure_state="idle"),
        summary=summary,
    )
    phase4.status = build_phase4_status(phase4)
    phase4.summary.note_link_summary = dict(phase4.status.link_summary or {})
    return phase4


def _assemble_phase5_summary(
    *,
    phase4: Phase4Structure,
    unit_summary: Mapping[str, Any],
    diagnostic_summary: Mapping[str, Any],
) -> Phase5Summary:
    return Phase5Summary(
        page_partition_summary=dict(phase4.summary.page_partition_summary or {}),
        heading_review_summary=dict(phase4.summary.heading_review_summary or {}),
        heading_graph_summary=dict(phase4.summary.heading_graph_summary or {}),
        chapter_source_summary=dict(phase4.summary.chapter_source_summary or {}),
        visual_toc_conflict_count=int(phase4.summary.visual_toc_conflict_count or 0),
        toc_alignment_summary=dict(phase4.summary.toc_alignment_summary or {}),
        toc_semantic_summary=dict(phase4.summary.toc_semantic_summary or {}),
        toc_role_summary=dict(phase4.summary.toc_role_summary or {}),
        container_titles=list(phase4.summary.container_titles or []),
        post_body_titles=list(phase4.summary.post_body_titles or []),
        back_matter_titles=list(phase4.summary.back_matter_titles or []),
        chapter_title_alignment_ok=bool(phase4.summary.chapter_title_alignment_ok),
        chapter_section_alignment_ok=bool(phase4.summary.chapter_section_alignment_ok),
        toc_semantic_contract_ok=bool(phase4.summary.toc_semantic_contract_ok),
        toc_semantic_blocking_reasons=list(phase4.summary.toc_semantic_blocking_reasons or []),
        note_region_summary=dict(phase4.summary.note_region_summary or {}),
        note_item_summary=dict(phase4.summary.note_item_summary or {}),
        chapter_note_mode_summary=dict(phase4.summary.chapter_note_mode_summary or {}),
        chapter_endnote_region_alignment_ok=bool(phase4.summary.chapter_endnote_region_alignment_ok),
        chapter_endnote_start_page_map=dict(phase4.summary.chapter_endnote_start_page_map or {}),
        body_anchor_summary=dict(phase4.summary.body_anchor_summary or {}),
        note_link_summary=dict(phase4.summary.note_link_summary or {}),
        review_seed_summary=dict(phase4.summary.review_seed_summary or {}),
        review_type_counts=dict(phase4.summary.review_type_counts or {}),
        override_summary=dict(phase4.summary.override_summary or {}),
        review_flags=list(phase4.summary.review_flags or []),
        unit_planning_summary=dict(unit_summary.get("unit_planning_summary") or {}),
        ref_materialization_summary=dict(unit_summary.get("ref_materialization_summary") or {}),
        diagnostic_page_summary=dict(diagnostic_summary.get("diagnostic_page_summary") or {}),
        diagnostic_note_summary=dict(diagnostic_summary.get("diagnostic_note_summary") or {}),
    )


def build_phase5_structure(
    pages: list[dict],
    *,
    toc_items: list[dict] | None = None,
    toc_offset: int = 0,
    review_overrides: Any = None,
    pdf_path: str = "",
    page_text_map: Mapping[int | str, str] | None = None,
    manual_toc_ready: bool = True,
    manual_toc_summary: Mapping[str, Any] | None = None,
    pipeline_state: str = "done",
    max_body_chars: int = 6000,
    visual_toc_bundle: Mapping[str, Any] | None = None,
) -> Phase5Structure:
    phase4 = build_phase4_structure(
        pages,
        toc_items=toc_items,
        toc_offset=int(toc_offset or 0),
        review_overrides=review_overrides,
        pdf_path=str(pdf_path or ""),
        page_text_map=page_text_map,
        manual_toc_ready=bool(manual_toc_ready),
        manual_toc_summary=manual_toc_summary,
        pipeline_state=str(pipeline_state or "done"),
        visual_toc_bundle=visual_toc_bundle,
    )
    translation_units, unit_summary = build_translation_units(
        phase4,
        pages=pages,
        max_body_chars=int(max_body_chars or 6000),
    )
    diagnostic_pages, diagnostic_notes, diagnostic_summary = build_diagnostic_projection(
        phase4,
        translation_units,
        pages=pages,
        only_pages=None,
    )
    summary = _assemble_phase5_summary(
        phase4=phase4,
        unit_summary=unit_summary,
        diagnostic_summary=diagnostic_summary,
    )
    return Phase5Structure(
        pages=phase4.pages,
        heading_candidates=phase4.heading_candidates,
        chapters=phase4.chapters,
        section_heads=phase4.section_heads,
        note_regions=phase4.note_regions,
        note_items=phase4.note_items,
        chapter_note_modes=phase4.chapter_note_modes,
        body_anchors=phase4.body_anchors,
        note_links=phase4.note_links,
        effective_note_links=phase4.effective_note_links,
        structure_reviews=phase4.structure_reviews,
        translation_units=list(translation_units or []),
        diagnostic_pages=list(diagnostic_pages or []),
        diagnostic_notes=list(diagnostic_notes or []),
        status=phase4.status,
        summary=summary,
    )


def _assemble_phase6_summary(
    *,
    phase5: Phase5Structure,
    export_summary: Mapping[str, Any],
    audit_summary: Mapping[str, Any],
) -> Phase6Summary:
    return Phase6Summary(
        page_partition_summary=dict(phase5.summary.page_partition_summary or {}),
        heading_review_summary=dict(phase5.summary.heading_review_summary or {}),
        heading_graph_summary=dict(phase5.summary.heading_graph_summary or {}),
        chapter_source_summary=dict(phase5.summary.chapter_source_summary or {}),
        visual_toc_conflict_count=int(phase5.summary.visual_toc_conflict_count or 0),
        toc_alignment_summary=dict(phase5.summary.toc_alignment_summary or {}),
        toc_semantic_summary=dict(phase5.summary.toc_semantic_summary or {}),
        toc_role_summary=dict(phase5.summary.toc_role_summary or {}),
        container_titles=list(phase5.summary.container_titles or []),
        post_body_titles=list(phase5.summary.post_body_titles or []),
        back_matter_titles=list(phase5.summary.back_matter_titles or []),
        chapter_title_alignment_ok=bool(phase5.summary.chapter_title_alignment_ok),
        chapter_section_alignment_ok=bool(phase5.summary.chapter_section_alignment_ok),
        toc_semantic_contract_ok=bool(phase5.summary.toc_semantic_contract_ok),
        toc_semantic_blocking_reasons=list(phase5.summary.toc_semantic_blocking_reasons or []),
        note_region_summary=dict(phase5.summary.note_region_summary or {}),
        note_item_summary=dict(phase5.summary.note_item_summary or {}),
        chapter_note_mode_summary=dict(phase5.summary.chapter_note_mode_summary or {}),
        chapter_endnote_region_alignment_ok=bool(phase5.summary.chapter_endnote_region_alignment_ok),
        chapter_endnote_start_page_map=dict(phase5.summary.chapter_endnote_start_page_map or {}),
        body_anchor_summary=dict(phase5.summary.body_anchor_summary or {}),
        note_link_summary=dict(phase5.summary.note_link_summary or {}),
        review_seed_summary=dict(phase5.summary.review_seed_summary or {}),
        review_type_counts=dict(phase5.summary.review_type_counts or {}),
        override_summary=dict(phase5.summary.override_summary or {}),
        review_flags=list(phase5.summary.review_flags or []),
        unit_planning_summary=dict(phase5.summary.unit_planning_summary or {}),
        ref_materialization_summary=dict(phase5.summary.ref_materialization_summary or {}),
        diagnostic_page_summary=dict(phase5.summary.diagnostic_page_summary or {}),
        diagnostic_note_summary=dict(phase5.summary.diagnostic_note_summary or {}),
        export_bundle_summary=dict(export_summary.get("export_bundle_summary") or {}),
        export_audit_summary=dict(audit_summary.get("export_audit_summary") or {}),
    )


def build_phase6_structure(
    pages: list[dict],
    *,
    toc_items: list[dict] | None = None,
    toc_offset: int = 0,
    review_overrides: Any = None,
    pdf_path: str = "",
    page_text_map: Mapping[int | str, str] | None = None,
    manual_toc_ready: bool = True,
    manual_toc_summary: Mapping[str, Any] | None = None,
    pipeline_state: str = "done",
    max_body_chars: int = 6000,
    include_diagnostic_entries: bool = False,
    slug: str = "",
    visual_toc_bundle: Mapping[str, Any] | None = None,
) -> Phase6Structure:
    phase5 = build_phase5_structure(
        pages,
        toc_items=toc_items,
        toc_offset=int(toc_offset or 0),
        review_overrides=review_overrides,
        pdf_path=str(pdf_path or ""),
        page_text_map=page_text_map,
        manual_toc_ready=bool(manual_toc_ready),
        manual_toc_summary=manual_toc_summary,
        pipeline_state=str(pipeline_state or "done"),
        max_body_chars=int(max_body_chars or 6000),
        visual_toc_bundle=visual_toc_bundle,
    )
    export_chapters, export_bundle, export_summary = build_export_bundle(
        phase5,
        pages=pages,
        include_diagnostic_entries=bool(include_diagnostic_entries),
    )
    phase6 = Phase6Structure(
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
        translation_units=phase5.translation_units,
        diagnostic_pages=phase5.diagnostic_pages,
        diagnostic_notes=phase5.diagnostic_notes,
        export_chapters=list(export_chapters or []),
        export_bundle=export_bundle,
        status=phase5.status,
        summary=Phase6Summary(),
    )
    export_audit, audit_summary = audit_phase6_export(
        phase6,
        slug=str(slug or ""),
        zip_bytes=None,
    )
    phase6.export_audit = export_audit
    phase6.status = build_phase6_status(phase6)
    phase6.summary = _assemble_phase6_summary(
        phase5=phase5,
        export_summary=export_summary,
        audit_summary=audit_summary,
    )
    return phase6


@dataclass(slots=True)
class ModulePipelineSnapshot:
    toc_result: ModuleResult[TocStructure]
    book_type_result: ModuleResult[BookNoteProfile]
    split_result: ModuleResult[ChapterLayers]
    link_result: ModuleResult[NoteLinkTable]
    freeze_result: ModuleResult[FrozenUnits]
    merge_result: ModuleResult[ChapterMarkdownSet]
    export_result: ModuleResult[ExportBundle]
    frozen_units_effective: FrozenUnits
    diagnostic_pages: list[Any]
    diagnostic_notes: list[Any]
    phase6: Phase6Structure

    @property
    def phase6_shadow(self) -> Phase6Structure:
        return self.phase6


def _normalize_toc_items_with_offset(toc_items: list[dict] | None, *, toc_offset: int) -> list[dict]:
    offset = int(toc_offset or 0)
    rows: list[dict] = []
    for raw in list(toc_items or []):
        row = dict(raw or {})
        target_pdf_page = int(row.get("target_pdf_page") or 0)
        if target_pdf_page > 0 and offset != 0:
            row["target_pdf_page"] = target_pdf_page + offset
        rows.append(row)
    return rows


def _legacy_page_role_from_toc_role(role: str) -> str:
    token = str(role or "").strip().lower()
    if token in {"chapter", "post_body"}:
        return "body"
    if token == "front_matter":
        return "front_matter"
    return "other"


def _phase_pages_from_toc(toc_structure: TocStructure) -> list[Any]:
    return [
        PagePartitionRecord(
            page_no=int(row.page_no or 0),
            target_pdf_page=int(row.page_no or 0),
            page_role=_legacy_page_role_from_toc_role(str(row.role or "")),  # type: ignore[arg-type]
            confidence=1.0,
            reason=str(row.reason or ""),
            section_hint="",
            has_note_heading=False,
            note_scan_summary={},
        )
        for row in sorted(toc_structure.pages, key=lambda item: int(item.page_no or 0))
        if int(row.page_no or 0) > 0
    ]


def _phase_chapters_from_toc(toc_structure: TocStructure) -> list[ChapterRecord]:
    return [
        ChapterRecord(
            chapter_id=str(row.chapter_id or ""),
            title=str(row.title or ""),
            start_page=int(row.start_page or 0),
            end_page=int(row.end_page or int(row.start_page or 0)),
            pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
            source=str(row.source or "fallback"),  # type: ignore[arg-type]
            boundary_state=str(row.boundary_state or "ready"),  # type: ignore[arg-type]
        )
        for row in toc_structure.chapters
        if str(row.chapter_id or "").strip()
    ]


def _phase_section_heads_from_toc(toc_structure: TocStructure) -> list[SectionHeadRecord]:
    return [
        SectionHeadRecord(
            section_head_id=str(row.section_head_id or ""),
            chapter_id=str(row.chapter_id or ""),
            title=str(row.title or ""),
            page_no=int(row.page_no or 0),
            level=int(row.level or 1),
            source=str(row.source or ""),
        )
        for row in toc_structure.section_heads
        if str(row.section_head_id or "").strip()
    ]


def _phase_note_regions_from_layers(chapter_layers: ChapterLayers) -> list[NoteRegionRecord]:
    return [
        NoteRegionRecord(
            region_id=str(row.region_id or ""),
            chapter_id=str(row.chapter_id or ""),
            page_start=int(row.page_start or 0),
            page_end=int(row.page_end or int(row.page_start or 0)),
            pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
            note_kind=str(row.note_kind),  # type: ignore[arg-type]
            scope=str(row.scope),  # type: ignore[arg-type]
            source=str(row.source),  # type: ignore[arg-type]
            heading_text=str(row.heading_text or ""),
            start_reason="module_projection",
            end_reason="module_projection",
            region_marker_alignment_ok=not bool(row.review_required),
            region_start_first_source_marker="",
            region_first_note_item_marker="",
            review_required=bool(row.review_required),
        )
        for row in chapter_layers.regions
        if str(row.region_id or "").strip()
    ]


def _phase_note_regions_from_split(split_result: ModuleResult[ChapterLayers]) -> list[NoteRegionRecord]:
    return _phase_note_regions_from_layers(split_result.data)


def _phase_note_items_from_layers(chapter_layers: ChapterLayers) -> list[NoteItemRecord]:
    return [
        NoteItemRecord(
            note_item_id=str(row.note_item_id or ""),
            region_id=str(row.region_id or ""),
            chapter_id=str(row.chapter_id or ""),
            page_no=int(row.page_no or 0),
            marker=str(row.marker or ""),
            marker_type=str(row.marker_type or ""),
            text=str(row.text or ""),
            source=str(row.source or ""),
            source_page_label=str(row.page_no or ""),
            is_reconstructed=bool(row.is_reconstructed),
            review_required=bool(row.review_required),
        )
        for row in chapter_layers.note_items
        if str(row.note_item_id or "").strip()
    ]


def _phase_note_items_from_split(split_result: ModuleResult[ChapterLayers]) -> list[NoteItemRecord]:
    return _phase_note_items_from_layers(split_result.data)


def _apply_note_item_overrides_to_chapter_layers(
    chapter_layers: ChapterLayers,
    *,
    note_item_overrides: Mapping[str, Mapping[str, Any]] | None,
) -> ChapterLayers:
    overrides = dict(note_item_overrides or {})
    if not overrides:
        return chapter_layers

    effective_layers: ChapterLayers = copy.deepcopy(chapter_layers)
    chapter_by_id = {
        str(chapter.chapter_id or ""): chapter
        for chapter in effective_layers.chapters
        if str(chapter.chapter_id or "").strip()
    }
    existing_note_item_ids = {
        str(row.note_item_id or "")
        for row in effective_layers.note_items
        if str(row.note_item_id or "").strip()
    }
    existing_region_ids = {
        str(row.region_id or "")
        for row in effective_layers.regions
        if str(row.region_id or "").strip()
    }

    for target_id, payload in overrides.items():
        data = dict(payload or {})
        action = str(data.get("action") or "").strip().lower()
        note_item_id = str(data.get("note_item_id") or target_id or "").strip()
        if action != "create" or not note_item_id or note_item_id in existing_note_item_ids:
            continue
        chapter_id = str(data.get("chapter_id") or "").strip()
        marker = normalize_note_marker(str(data.get("marker") or ""))
        text = str(data.get("text") or data.get("note_text") or "").strip()
        note_kind = str(data.get("note_kind") or "endnote").strip() or "endnote"
        try:
            page_no = int(data.get("page_no") or 0)
        except (TypeError, ValueError):
            page_no = 0
        if not chapter_id or page_no <= 0 or not marker or not text:
            continue

        region_id = str(data.get("region_id") or "").strip()
        if not region_id or region_id not in existing_region_ids:
            region_id = f"llm-note-region-{chapter_id}-{page_no}-{note_kind}"
            if region_id not in existing_region_ids:
                region = LayerNoteRegion(
                    region_id=region_id,
                    chapter_id=chapter_id,
                    page_start=page_no,
                    page_end=page_no,
                    pages=[page_no],
                    note_kind=note_kind,  # type: ignore[arg-type]
                    scope="chapter",  # type: ignore[arg-type]
                    source="llm",  # type: ignore[arg-type]
                    heading_text="",
                    review_required=bool(data.get("review_required") or False),
                    owner_chapter_id=chapter_id,
                    source_scope="chapter",
                    bind_method="llm_note_item_override",
                    bind_confidence=1.0,
                )
                effective_layers.regions.append(region)
                existing_region_ids.add(region_id)
                chapter = chapter_by_id.get(chapter_id)
                if chapter and note_kind == "endnote":
                    chapter.endnote_regions.append(region)

        item = LayerNoteItem(
            note_item_id=note_item_id,
            region_id=region_id,
            chapter_id=chapter_id,
            page_no=page_no,
            marker=marker,
            marker_type="footnote_marker" if note_kind == "footnote" else "numeric",
            text=text,
            source=str(data.get("source") or "llm"),
            is_reconstructed=bool(data.get("is_reconstructed") or False),
            review_required=bool(data.get("review_required") or False),
            note_kind=note_kind,  # type: ignore[arg-type]
            owner_chapter_id=chapter_id,
            source_marker=marker,
            normalized_marker=marker,
            synth_marker="",
            projection_mode="native",
        )
        effective_layers.note_items.append(item)
        existing_note_item_ids.add(note_item_id)
        chapter = chapter_by_id.get(chapter_id)
        if chapter:
            if note_kind == "footnote":
                chapter.footnote_items.append(item)
            else:
                chapter.endnote_items.append(item)

    effective_layers.regions.sort(
        key=lambda row: (
            int(row.page_start or 0),
            int(row.page_end or 0),
            str(row.chapter_id or ""),
            str(row.region_id or ""),
        )
    )
    effective_layers.note_items.sort(
        key=lambda row: (
            int(row.page_no or 0),
            str(row.chapter_id or ""),
            str(row.note_item_id or ""),
        )
    )
    for chapter in effective_layers.chapters:
        chapter.footnote_items.sort(
            key=lambda row: (int(row.page_no or 0), str(row.note_item_id or ""))
        )
        chapter.endnote_items.sort(
            key=lambda row: (int(row.page_no or 0), str(row.note_item_id or ""))
        )
        chapter.endnote_regions.sort(
            key=lambda row: (
                int(row.page_start or 0),
                int(row.page_end or 0),
                str(row.region_id or ""),
            )
        )
    return effective_layers


def _phase_note_modes_from_book_type(book_type_result: ModuleResult[BookNoteProfile]) -> list[ChapterNoteModeRecord]:
    return [
        ChapterNoteModeRecord(
            chapter_id=str(row.chapter_id or ""),
            note_mode=str(row.note_mode),  # type: ignore[arg-type]
            region_ids=[str(token) for token in list(row.region_ids or []) if str(token).strip()],
            primary_region_scope="",
            has_footnote_band=bool(row.has_footnote_band),
            has_endnote_region=bool(row.has_endnote_region),
        )
        for row in book_type_result.data.chapter_modes
        if str(row.chapter_id or "").strip()
    ]


def _phase_anchors_from_links(link_result: ModuleResult[NoteLinkTable]) -> list[BodyAnchorRecord]:
    return [
        BodyAnchorRecord(
            anchor_id=str(row.anchor_id or ""),
            chapter_id=str(row.chapter_id or ""),
            page_no=int(row.page_no or 0),
            paragraph_index=int(row.paragraph_index or 0),
            char_start=int(row.char_start or 0),
            char_end=int(row.char_end or 0),
            source_marker=str(row.source_marker or ""),
            normalized_marker=str(row.normalized_marker or ""),
            anchor_kind=str(row.anchor_kind),  # type: ignore[arg-type]
            certainty=float(row.certainty or 0.0),
            source_text=str(row.source_text or ""),
            source=str(row.source or ""),
            synthetic=bool(row.synthetic),
            ocr_repaired_from_marker=str(row.ocr_repaired_from_marker or ""),
        )
        for row in link_result.data.anchors
        if str(row.anchor_id or "").strip()
    ]


def _phase_links_from_layers(rows: list[Any]) -> list[NoteLinkRecord]:
    return [
        NoteLinkRecord(
            link_id=str(row.link_id or ""),
            chapter_id=str(row.chapter_id or ""),
            region_id=str(row.region_id or ""),
            note_item_id=str(row.note_item_id or ""),
            anchor_id=str(row.anchor_id or ""),
            status=str(row.status),  # type: ignore[arg-type]
            resolver=str(row.resolver),  # type: ignore[arg-type]
            confidence=float(row.confidence or 0.0),
            note_kind=str(row.note_kind),  # type: ignore[arg-type]
            marker=str(row.marker or ""),
            page_no_start=int(row.page_no_start or 0),
            page_no_end=int(row.page_no_end or int(row.page_no_start or 0)),
        )
        for row in rows
        if str(row.link_id or "").strip()
    ]


def _paragraph_record_from_dict(payload: dict[str, Any]) -> UnitParagraphRecord:
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


def _segment_record_from_dict(payload: dict[str, Any]) -> UnitPageSegmentRecord:
    paragraphs = [
        _paragraph_record_from_dict(dict(row))
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


def _phase_translation_units_from_frozen(frozen_units: FrozenUnits) -> list[TranslationUnitRecord]:
    rows: list[TranslationUnitRecord] = []
    for unit in list(frozen_units.body_units or []) + list(frozen_units.note_units or []):
        rows.append(
            TranslationUnitRecord(
                unit_id=str(unit.unit_id or ""),
                kind=str(unit.kind or ""),
                owner_kind=str(unit.owner_kind or ""),
                owner_id=str(unit.owner_id or ""),
                section_id=str(unit.section_id or ""),
                section_title=str(unit.section_title or ""),
                section_start_page=int(unit.section_start_page or 0),
                section_end_page=int(unit.section_end_page or 0),
                note_id=str(unit.note_id or ""),
                page_start=int(unit.page_start or 0),
                page_end=int(unit.page_end or int(unit.page_start or 0)),
                char_count=int(unit.char_count or 0),
                source_text=str(unit.source_text or ""),
                translated_text=str(unit.translated_text or ""),
                status=str(unit.status or "pending"),
                error_msg=str(unit.error_msg or ""),
                target_ref=str(unit.target_ref or ""),
                page_segments=[
                    _segment_record_from_dict(dict(segment))
                    for segment in list(unit.page_segments or [])
                    if isinstance(segment, dict)
                ],
            )
        )
    return rows


def _export_bundle_record_from_module(bundle: ExportBundle) -> ExportBundleRecord:
    chapters = [
        ExportChapterRecord(
            order=int(row.order or 0),
            section_id=str(row.chapter_id or ""),
            title=str(row.title or ""),
            path=str(row.path or ""),
            content=str(row.markdown_text or ""),
            start_page=int(row.start_page or 0),
            end_page=int(row.end_page or int(row.start_page or 0)),
            pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
        )
        for row in bundle.chapters
        if str(row.path or "").strip()
    ]
    return ExportBundleRecord(
        index_path="index.md",
        chapters_dir="chapters",
        chapters=chapters,
        chapter_files={str(key): str(value or "") for key, value in dict(bundle.chapter_files or {}).items()},
        files={str(key): str(value or "") for key, value in dict(bundle.files or {}).items()},
        export_semantic_contract_ok=bool(bundle.semantic_summary.get("export_semantic_contract_ok", True)),
        front_matter_leak_detected=bool(bundle.semantic_summary.get("front_matter_leak_detected", False)),
        toc_residue_detected=bool(bundle.semantic_summary.get("toc_residue_detected", False)),
        mid_paragraph_heading_detected=bool(bundle.semantic_summary.get("mid_paragraph_heading_detected", False)),
        duplicate_paragraph_detected=bool(bundle.semantic_summary.get("duplicate_paragraph_detected", False)),
    )


def _export_audit_record_from_module(report: Any) -> ExportAuditReportRecord:
    return ExportAuditReportRecord(
        slug=str(report.slug or ""),
        doc_id=str(report.doc_id or ""),
        zip_path=str(report.zip_path or ""),
        applicable=bool(getattr(report, "applicable", True)),
        structure_state=str(report.structure_state or ""),
        blocking_reasons=[str(item).strip() for item in list(report.blocking_reasons or []) if str(item).strip()],
        manual_toc_summary=dict(report.manual_toc_summary or {}),
        toc_role_summary=dict(report.toc_role_summary or {}),
        chapter_titles=[str(item).strip() for item in list(report.chapter_titles or []) if str(item).strip()],
        files=[
            ExportAuditFileRecord(
                path=str(item.path or ""),
                title=str(item.title or ""),
                page_span=[int(page_no) for page_no in list(item.page_span or []) if int(page_no) > 0],
                issue_codes=[str(code).strip() for code in list(item.issue_codes or []) if str(code).strip()],
                issue_summary=[str(code).strip() for code in list(item.issue_summary or []) if str(code).strip()],
                severity=str(item.severity or "minor"),
                sample_opening=str(item.sample_opening or ""),
                sample_mid=str(item.sample_mid or ""),
                sample_tail=str(item.sample_tail or ""),
                footnote_endnote_summary=dict(item.footnote_endnote_summary or {}),
            )
            for item in list(report.files or [])
        ],
        blocking_issue_count=int(report.blocking_issue_count or 0),
        major_issue_count=int(report.major_issue_count or 0),
        can_ship=bool(report.can_ship),
        must_fix_before_next_book=[dict(item or {}) for item in list(report.must_fix_before_next_book or [])],
        recommended_followups=[dict(item or {}) for item in list(report.recommended_followups or [])],
    )


def _phase6_summary_from_modules(
    *,
    toc_result: ModuleResult[TocStructure],
    book_type_result: ModuleResult[BookNoteProfile],
    split_result: ModuleResult[ChapterLayers],
    link_result: ModuleResult[NoteLinkTable],
    freeze_result: ModuleResult[FrozenUnits],
    export_result: ModuleResult[ExportBundle],
    diagnostic_summary: Mapping[str, Any],
    manual_toc_ready: bool,
    manual_toc_summary: Mapping[str, Any] | None,
    pipeline_state: str,
) -> Phase6Summary:
    def _summary_title_key(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        text = re.sub(r"\s+([?!:;,])", r"\1", text)
        return text.casefold()

    container_titles = [str(row.title or "") for row in toc_result.data.toc_tree if str(row.role or "") == "container"]
    post_body_titles = [str(row.title or "") for row in toc_result.data.chapters if str(row.role or "") == "post_body"]
    back_matter_titles = [
        str(row.title or "")
        for row in toc_result.data.toc_tree
        if str(row.role or "") == "back_matter"
    ]
    exported_title_keys = {
        _summary_title_key(str(row.title or ""))
        for row in export_result.data.chapters
        if _summary_title_key(str(row.title or ""))
    }
    if exported_title_keys:
        container_titles = [
            title
            for title in container_titles
            if _summary_title_key(title) not in exported_title_keys
        ]
    return Phase6Summary(
        page_partition_summary=dict(toc_result.evidence.get("page_partition_summary") or {}),
        heading_review_summary=dict(toc_result.evidence.get("heading_review_summary") or {}),
        heading_graph_summary=dict(toc_result.evidence.get("heading_graph_summary") or {}),
        chapter_source_summary=dict(toc_result.evidence.get("chapter_source_summary") or {}),
        visual_toc_conflict_count=int(toc_result.evidence.get("visual_toc_conflict_count") or 0),
        toc_alignment_summary=dict(toc_result.evidence.get("toc_alignment_summary") or {}),
        toc_semantic_summary=dict(toc_result.evidence.get("toc_semantic_summary") or {}),
        toc_role_summary=dict(toc_result.evidence.get("toc_role_summary") or {}),
        container_titles=[title for title in container_titles if str(title or "").strip()],
        post_body_titles=[title for title in post_body_titles if str(title or "").strip()],
        back_matter_titles=[title for title in back_matter_titles if str(title or "").strip()],
        chapter_title_alignment_ok=bool(toc_result.gate_report.hard.get("toc.chapter_titles_aligned", True)),
        chapter_section_alignment_ok=bool(toc_result.gate_report.soft.get("toc.section_alignment_warn", True)),
        toc_semantic_contract_ok=bool(toc_result.gate_report.hard.get("toc.role_semantics_valid", True)),
        toc_semantic_blocking_reasons=[],
        note_region_summary=dict(split_result.data.region_summary or {}),
        note_item_summary=dict(split_result.data.item_summary or {}),
        chapter_note_mode_summary={
            "mode_counts": dict(book_type_result.data.evidence.chapter_mode_counts or {}),
            "review_required_chapters": list(book_type_result.data.evidence.chapter_review_required or []),
        },
        chapter_endnote_region_alignment_ok=bool(split_result.gate_report.hard.get("split.regions_bound", True)),
        chapter_endnote_start_page_map={},
        body_anchor_summary=dict(link_result.data.anchor_summary or {}),
        note_link_summary=dict(link_result.data.link_summary or {}),
        review_seed_summary={},
        review_type_counts={},
        override_summary={
            "manual_toc_ready": bool(manual_toc_ready),
            "manual_toc_summary": dict(manual_toc_summary or {}),
            "pipeline_state": str(pipeline_state or "done"),
        },
        review_flags=[],
        unit_planning_summary=dict(freeze_result.data.freeze_summary or {}),
        ref_materialization_summary=dict(freeze_result.data.freeze_summary or {}),
        diagnostic_page_summary=dict(diagnostic_summary.get("diagnostic_page_summary") or {}),
        diagnostic_note_summary=dict(diagnostic_summary.get("diagnostic_note_summary") or {}),
        export_bundle_summary=dict(export_result.data.semantic_summary or {}),
        export_audit_summary={
            "file_count": int(len(export_result.data.audit_report.files)),
            "blocking_issue_count": int(export_result.data.audit_report.blocking_issue_count or 0),
            "major_issue_count": int(export_result.data.audit_report.major_issue_count or 0),
            "can_ship": bool(export_result.data.audit_report.can_ship),
        },
    )


def _diagnostic_machine_by_page(rows: list[Any]) -> dict[int, str]:
    payload: dict[int, str] = {}
    for page in rows:
        page_no = int(getattr(page, "_pageBP", 0) or 0)
        if page_no <= 0:
            continue
        entries = []
        for entry in list(getattr(page, "_page_entries", []) or []):
            source = str(getattr(entry, "_translation_source", "") or "").strip().lower()
            if source == "source":
                continue
            candidate = str(
                getattr(entry, "translation", "")
                or getattr(entry, "_machine_translation", "")
                or getattr(entry, "_manual_translation", "")
                or ""
            ).strip()
            if candidate:
                entries.append(candidate)
        if entries:
            payload[page_no] = "\n\n".join(entries)
    return payload


def _normalize_overlay_unit_id(unit_id: str, *, overlay_doc_id: str) -> str:
    raw = str(unit_id or "").strip()
    prefix = f"{str(overlay_doc_id or '').strip()}-"
    return raw[len(prefix):] if prefix and raw.startswith(prefix) else raw


def _overlay_repo_units_on_frozen(
    frozen_units: FrozenUnits,
    *,
    repo_units: list[dict] | None,
    overlay_doc_id: str,
) -> FrozenUnits:
    if not repo_units:
        return frozen_units
    payload = copy.deepcopy(frozen_units)
    by_id = {
        _normalize_overlay_unit_id(str(row.get("unit_id") or ""), overlay_doc_id=str(overlay_doc_id or "")): dict(row)
        for row in list(repo_units or [])
        if str(row.get("unit_id") or "").strip()
    }
    for unit in list(payload.body_units or []) + list(payload.note_units or []):
        repo_unit = by_id.get(str(unit.unit_id or "").strip())
        if not repo_unit:
            continue
        unit.translated_text = str(repo_unit.get("translated_text") or "")
        unit.status = str(repo_unit.get("status") or unit.status or "pending")
        unit.error_msg = str(repo_unit.get("error_msg") or "")
        segment_payload = list(repo_unit.get("page_segments") or [])
        unit.page_segments = [dict(segment) for segment in segment_payload if isinstance(segment, dict)]
    return payload


def build_module_pipeline_snapshot(
    pages: list[dict],
    *,
    toc_items: list[dict] | None = None,
    toc_offset: int = 0,
    review_overrides: Any = None,
    pdf_path: str = "",
    manual_toc_ready: bool = True,
    manual_toc_summary: Mapping[str, Any] | None = None,
    pipeline_state: str = "done",
    max_body_chars: int = 6000,
    include_diagnostic_entries: bool = False,
    slug: str = "",
    doc_id: str = "",
    repo_units: list[dict] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    visual_toc_bundle: Mapping[str, Any] | None = None,
) -> ModulePipelineSnapshot:
    def _emit_progress(
        *,
        stage: str,
        label: str,
        pct: float,
        event: str,
        elapsed_ms: int | None = None,
    ) -> None:
        if not callable(progress_callback):
            return
        payload: dict[str, Any] = {
            "stage": stage,
            "label": label,
            "pct": float(pct),
            "event": event,
        }
        if elapsed_ms is not None:
            payload["elapsed_ms"] = int(max(0, elapsed_ms))
        progress_callback(payload)

    def _run_stage(
        *,
        stage: str,
        label: str,
        start_pct: float,
        end_pct: float,
        runner: Callable[[], Any],
    ) -> Any:
        _emit_progress(stage=stage, label=label, pct=start_pct, event="start")
        start_ts = time.perf_counter()
        result = runner()
        elapsed_ms = int((time.perf_counter() - start_ts) * 1000)
        _emit_progress(stage=stage, label=label, pct=end_pct, event="done", elapsed_ms=elapsed_ms)
        return result

    grouped_overrides = _group_review_overrides(review_overrides)
    toc_result = _run_stage(
        stage="toc_structure",
        label="构建目录与章节结构",
        start_pct=97.0,
        end_pct=97.9,
        runner=lambda: build_toc_structure(
            pages,
            _normalize_toc_items_with_offset(toc_items, toc_offset=int(toc_offset or 0)),
            manual_page_overrides=grouped_overrides.get("page"),
            pdf_path=str(pdf_path or ""),
            visual_toc_bundle=visual_toc_bundle,
        ),
    )
    book_type_result = _run_stage(
        stage="book_note_profile",
        label="判定章节注释模式",
        start_pct=98.0,
        end_pct=98.6,
        runner=lambda: build_book_note_profile(
            toc_result.data,
            pages,
            overrides={"chapter_modes": grouped_overrides.get("chapter")},
        ),
    )
    split_result = _run_stage(
        stage="chapter_layers",
        label="识别注释区与注释项",
        start_pct=98.7,
        end_pct=99.2,
        runner=lambda: build_chapter_layers(
            toc_result.data,
            book_type_result.data,
            pages,
            endnote_explorer_hints=dict(toc_result.diagnostics.get("endnote_explorer_hints") or {}),
            heading_candidates=list(toc_result.diagnostics.get("heading_candidates") or []),
        ),
    )
    effective_split_layers = _apply_note_item_overrides_to_chapter_layers(
        split_result.data,
        note_item_overrides=grouped_overrides.get("note_item"),
    )
    grouped_overrides_for_link = {
        str(scope): dict(rows or {})
        for scope, rows in dict(grouped_overrides or {}).items()
    }
    grouped_overrides_for_link["note_item"] = {}
    link_result = _run_stage(
        stage="note_link_table",
        label="建立正文锚点与注释链接",
        start_pct=99.3,
        end_pct=99.55,
        runner=lambda: build_note_link_table(
            effective_split_layers,
            pages,
            overrides=grouped_overrides_for_link,
        ),
    )
    freeze_result = _run_stage(
        stage="frozen_units",
        label="生成翻译单元",
        start_pct=99.56,
        end_pct=99.72,
        runner=lambda: build_frozen_units(
            effective_split_layers,
            link_result.data,
            max_body_chars=int(max_body_chars or 6000),
        ),
    )
    frozen_units_effective = _overlay_repo_units_on_frozen(
        freeze_result.data,
        repo_units=repo_units,
        overlay_doc_id=str(doc_id or ""),
    )
    translation_units = _phase_translation_units_from_frozen(frozen_units_effective)
    phase4_shadow = Phase4Structure(
        pages=_phase_pages_from_toc(toc_result.data),
        heading_candidates=list(toc_result.diagnostics.get("heading_candidates") or []),
        chapters=_phase_chapters_from_toc(toc_result.data),
        section_heads=_phase_section_heads_from_toc(toc_result.data),
        note_regions=_phase_note_regions_from_layers(effective_split_layers),
        note_items=_phase_note_items_from_layers(effective_split_layers),
        chapter_note_modes=_phase_note_modes_from_book_type(book_type_result),
        body_anchors=_phase_anchors_from_links(link_result),
        note_links=_phase_links_from_layers(link_result.data.links),
        effective_note_links=_phase_links_from_layers(link_result.data.effective_links),
        structure_reviews=[],
        status=StructureStatusRecord(structure_state="idle"),
        summary=Phase4Summary(),
    )
    diagnostic_pages, diagnostic_notes, diagnostic_summary = _run_stage(
        stage="diagnostics",
        label="生成诊断投影",
        start_pct=99.73,
        end_pct=99.82,
        runner=lambda: build_diagnostic_projection(
            phase4_shadow,
            translation_units,
            pages=pages,
            only_pages=None,
        ),
    )
    merge_result = _run_stage(
        stage="chapter_markdown_set",
        label="组装章节 Markdown",
        start_pct=99.83,
        end_pct=99.9,
        runner=lambda: build_chapter_markdown_set(
            frozen_units_effective,
            link_result.data,
            split_result.data,
            diagnostic_machine_by_page=_diagnostic_machine_by_page(diagnostic_pages),
            include_diagnostic_entries=bool(include_diagnostic_entries),
        ),
    )
    export_result = _run_stage(
        stage="export_bundle",
        label="构建导出结构与审计",
        start_pct=99.91,
        end_pct=99.98,
        runner=lambda: build_module_export_bundle(
            merge_result.data,
            toc_result.data,
            slug=str(slug or ""),
            doc_id=str(doc_id or ""),
        ),
    )
    phase6 = Phase6Structure(
        pages=phase4_shadow.pages,
        heading_candidates=[],
        chapters=phase4_shadow.chapters,
        section_heads=phase4_shadow.section_heads,
        note_regions=phase4_shadow.note_regions,
        note_items=phase4_shadow.note_items,
        chapter_note_modes=phase4_shadow.chapter_note_modes,
        body_anchors=phase4_shadow.body_anchors,
        note_links=phase4_shadow.note_links,
        effective_note_links=phase4_shadow.effective_note_links,
        structure_reviews=[],
        translation_units=translation_units,
        diagnostic_pages=list(diagnostic_pages or []),
        diagnostic_notes=list(diagnostic_notes or []),
        export_chapters=_export_bundle_record_from_module(export_result.data).chapters,
        export_bundle=_export_bundle_record_from_module(export_result.data),
        export_audit=_export_audit_record_from_module(export_result.data.audit_report),
        status=StructureStatusRecord(structure_state="idle"),
        summary=Phase6Summary(),
    )
    snapshot = ModulePipelineSnapshot(
        toc_result=toc_result,
        book_type_result=book_type_result,
        split_result=split_result,
        link_result=link_result,
        freeze_result=freeze_result,
        merge_result=merge_result,
        export_result=export_result,
        frozen_units_effective=frozen_units_effective,
        diagnostic_pages=list(diagnostic_pages or []),
        diagnostic_notes=list(diagnostic_notes or []),
        phase6=phase6,
    )
    snapshot.phase6.status = build_module_gate_status(
        snapshot,
        pipeline_state=str(pipeline_state or "done"),
        manual_toc_ready=bool(manual_toc_ready),
        manual_toc_summary=manual_toc_summary,
    )
    snapshot.phase6.summary = _phase6_summary_from_modules(
        toc_result=toc_result,
        book_type_result=book_type_result,
        split_result=split_result,
        link_result=link_result,
        freeze_result=freeze_result,
        export_result=export_result,
        diagnostic_summary=diagnostic_summary,
        manual_toc_ready=bool(manual_toc_ready),
        manual_toc_summary=manual_toc_summary,
        pipeline_state=str(pipeline_state or "done"),
    )
    return snapshot

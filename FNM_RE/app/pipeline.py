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
    ChapterEndnoteRecord,
    ChapterNoteModeRecord,
    NoteItemRecord,
    NoteLinkRecord,
    NoteRegionRecord,
    PagePartitionRecord,
    ParagraphFootnoteRecord,
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
from FNM_RE.app.pipeline_converters import (
    ModulePipelineSnapshot,
    _apply_note_item_overrides_to_chapter_layers,
    _diagnostic_machine_by_page,
    _export_audit_record_from_module,
    _export_bundle_record_from_module,
    _legacy_page_role_from_toc_role,
    _normalize_overlay_unit_id,
    _normalize_toc_items_with_offset,
    _overlay_repo_units_on_frozen,
    _paragraph_record_from_dict,
    _phase_anchors_from_links,
    _phase_chapters_from_toc,
    _phase_links_from_layers,
    _phase_note_items_from_layers,
    _phase_note_items_from_split,
    _phase_note_modes_from_book_type,
    _phase_note_regions_from_layers,
    _phase_note_regions_from_split,
    _phase_pages_from_toc,
    _phase_section_heads_from_toc,
    _phase_translation_units_from_frozen,
    _phase6_summary_from_modules,
    _segment_record_from_dict,
)
from FNM_RE.shared.review_overrides import group_review_overrides as _group_review_overrides, empty_grouped_overrides as _empty_grouped_overrides
from FNM_RE.modules.chapter_split import build_chapter_layers
from FNM_RE.modules.contracts import ModuleResult
from FNM_RE.modules.note_linking import build_note_link_table
from FNM_RE.modules.ref_freeze import build_frozen_units
from FNM_RE.stages.paragraph_footnotes import build_paragraph_footnotes
from FNM_RE.stages.paragraph_endnotes import build_paragraph_endnotes
from FNM_RE.stages.chapter_anchor_alignment import build_chapter_anchor_alignment
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


def _note_link_summary_from_layers(links: list[Any]) -> dict[str, int]:
    return {
        "matched": sum(1 for row in links if str(getattr(row, "status", "") or "") == "matched"),
        "footnote_orphan_note": sum(
            1
            for row in links
            if str(getattr(row, "note_kind", "") or "") == "footnote"
            and str(getattr(row, "status", "") or "") == "orphan_note"
        ),
        "footnote_orphan_anchor": sum(
            1
            for row in links
            if str(getattr(row, "note_kind", "") or "") == "footnote"
            and str(getattr(row, "status", "") or "") == "orphan_anchor"
        ),
        "endnote_orphan_note": sum(
            1
            for row in links
            if str(getattr(row, "note_kind", "") or "") == "endnote"
            and str(getattr(row, "status", "") or "") == "orphan_note"
        ),
        "endnote_orphan_anchor": sum(
            1
            for row in links
            if str(getattr(row, "note_kind", "") or "") == "endnote"
            and str(getattr(row, "status", "") or "") == "orphan_anchor"
        ),
        "ambiguous": sum(1 for row in links if str(getattr(row, "status", "") or "") == "ambiguous"),
        "ignored": sum(1 for row in links if str(getattr(row, "status", "") or "") == "ignored"),
    }


def _link_table_with_uninjected_refs_reopened(
    note_link_table: NoteLinkTable,
    frozen_units: FrozenUnits,
) -> NoteLinkTable:
    skipped_link_ids = {
        str(row.link_id or "")
        for row in list(frozen_units.ref_map or [])
        if str(row.decision or "") == "skipped"
        and str(row.link_id or "").strip()
        and str(row.note_item_id or "").strip()
    }
    if not skipped_link_ids:
        return note_link_table
    adjusted_effective_links = []
    for row in note_link_table.effective_links:
        if str(row.link_id or "") in skipped_link_ids and str(row.status or "") == "matched":
            adjusted_effective_links.append(
                replace(
                    row,
                    anchor_id="",
                    status="orphan_note",  # type: ignore[arg-type]
                    resolver="repair",  # type: ignore[arg-type]
                    confidence=0.0,
                )
            )
        else:
            adjusted_effective_links.append(row)
    return replace(
        note_link_table,
        effective_links=adjusted_effective_links,
        link_summary=_note_link_summary_from_layers(adjusted_effective_links),
    )


def _resolve_endnotes_start_page(visual_toc_bundle: Mapping[str, Any] | None) -> int | None:
    if not visual_toc_bundle:
        return None
    endnotes_summary = visual_toc_bundle.get("endnotes_summary") or {}
    if not endnotes_summary.get("present"):
        return None
    items = visual_toc_bundle.get("items") or []
    endnotes_item = next(
        (item for item in items if item.get("role_hint") == "endnotes"),
        None,
    )
    if not endnotes_item:
        return None
    book_page = endnotes_item.get("book_page")
    if book_page is not None:
        return int(book_page)
    file_idx = endnotes_item.get("file_idx")
    if file_idx is not None:
        return int(file_idx) + 1
    return None


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
        endnotes_start_page=_resolve_endnotes_start_page(visual_toc_bundle),
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

    # 预建按 chapter_id 分组的 region 查找表，避免 O(C×R) 重复扫描
    regions_by_chapter: dict[str, dict[str, list[str]]] = {}
    for region in note_regions:
        chapter_id = str(region.chapter_id or "").strip()
        if not chapter_id:
            continue
        bucket = regions_by_chapter.setdefault(chapter_id, {
            "footnote": [],
            "chapter_endnote": [],
            "book_endnote": [],
        })
        if region.note_kind == "footnote":
            bucket["footnote"].append(region.region_id)
        elif region.note_kind == "endnote":
            key = "book_endnote" if region.scope == "book" else "chapter_endnote"
            bucket[key].append(region.region_id)

    rows: list[ChapterNoteModeRecord] = []
    for chapter in phase1.chapters:
        chapter_id = chapter.chapter_id
        bucket = regions_by_chapter.get(chapter_id, {})
        footnote_regions = bucket.get("footnote") or []
        chapter_endnote_regions = bucket.get("chapter_endnote") or []
        book_endnote_regions = bucket.get("book_endnote") or []
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
    paragraph_footnote_summary: Mapping[str, Any] | None = None,
    paragraph_endnote_summary: Mapping[str, Any] | None = None,
    chapter_anchor_alignment_summary: Mapping[str, Any] | None = None,
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
        paragraph_footnote_summary=dict(paragraph_footnote_summary or {}),
        paragraph_endnote_summary=dict(paragraph_endnote_summary or {}),
        chapter_anchor_alignment_summary=dict(chapter_anchor_alignment_summary or {}),
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

    # —— Paragraph footnotes (layout-based) ——
    phase1_for_footnotes = Phase1Structure(
        pages=phase2.pages,
        chapters=phase2.chapters,
    )
    paragraph_footnotes, paragraph_footnote_summary = build_paragraph_footnotes(
        phase1_for_footnotes, pages=pages,
    )

    # —— Paragraph endnotes (layout-based) ——
    paragraph_endnotes, paragraph_endnote_summary = build_paragraph_endnotes(
        phase1_for_footnotes, pages=pages,
    )

    # —— Chapter anchor alignment (DP sequence alignment) ——
    chapter_anchor_alignments, chapter_anchor_alignment_summary = build_chapter_anchor_alignment(
        enhanced_anchors, paragraph_endnotes,
    )

    refreshed_body_anchor_summary = _refresh_body_anchor_summary(
        base_summary=body_anchor_summary,
        body_anchors=enhanced_anchors,
    )
    summary = _assemble_phase3_summary(
        phase2=phase2,
        body_anchor_summary=refreshed_body_anchor_summary,
        note_link_meta=note_link_meta,
        paragraph_footnote_summary=paragraph_footnote_summary,
        paragraph_endnote_summary=paragraph_endnote_summary,
        chapter_anchor_alignment_summary=chapter_anchor_alignment_summary,
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
        paragraph_footnotes=paragraph_footnotes,
        paragraph_endnotes=paragraph_endnotes,
        chapter_anchor_alignments=chapter_anchor_alignments,
        summary=summary,
    )


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


def _emit_progress(
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None,
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
    progress_callback: Callable[[dict[str, Any]], None] | None,
    stage: str,
    label: str,
    start_pct: float,
    end_pct: float,
    runner: Callable[[], Any],
) -> Any:
    _emit_progress(progress_callback=progress_callback, stage=stage, label=label, pct=start_pct, event="start")
    start_ts = time.perf_counter()
    result = runner()
    elapsed_ms = int((time.perf_counter() - start_ts) * 1000)
    _emit_progress(progress_callback=progress_callback, stage=stage, label=label, pct=end_pct, event="done", elapsed_ms=elapsed_ms)
    return result


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
    grouped_overrides = _group_review_overrides(review_overrides)
    toc_result = _run_stage(
        progress_callback=progress_callback,
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
        progress_callback=progress_callback,
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
        progress_callback=progress_callback,
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
        progress_callback=progress_callback,
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
        progress_callback=progress_callback,
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
    export_link_table = _link_table_with_uninjected_refs_reopened(
        link_result.data,
        freeze_result.data,
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
        note_links=_phase_links_from_layers(export_link_table.links),
        effective_note_links=_phase_links_from_layers(export_link_table.effective_links),
        structure_reviews=[],
        status=StructureStatusRecord(structure_state="idle"),
        summary=Phase4Summary(),
    )
    diagnostic_pages, diagnostic_notes, diagnostic_summary = _run_stage(
        progress_callback=progress_callback,
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
        progress_callback=progress_callback,
        stage="chapter_markdown_set",
        label="组装章节 Markdown",
        start_pct=99.83,
        end_pct=99.9,
        runner=lambda: build_chapter_markdown_set(
            frozen_units_effective,
            export_link_table,
            split_result.data,
            diagnostic_machine_by_page=_diagnostic_machine_by_page(diagnostic_pages),
            include_diagnostic_entries=bool(include_diagnostic_entries),
            section_heads=_phase_section_heads_from_toc(toc_result.data),
        ),
    )
    export_result = _run_stage(
        progress_callback=progress_callback,
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

"""FNM_RE 分阶段总入口。"""

from __future__ import annotations

import copy
import gc
import os
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
    _toc_role_to_page_role,
    _normalize_overlay_unit_id,
    _normalize_toc_items_with_offset,
    _overlay_repo_units_on_frozen,
    _paragraph_record_from_dict,
    _phase_anchors_from_links,
    _phase_chapters_from_toc,
    _phase_links_from_layers,
    _phase_note_items_from_layers,
    _phase_note_items_from_split,
    _phase_chapter_note_modes_from_layers,
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
from FNM_RE.modules.note_linking import (
    FOOTNOTE_OVERRIDE_PAGE_PADDING,
    _apply_link_overrides as _apply_link_overrides_impl,
    _find_existing_explicit_anchor_for_link_override,
    _infer_note_kind_from_anchor,
    _materialize_anchor_overrides,
    build_note_link_table,
)
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
from FNM_RE.stages.diagnostics import build_diagnostic_projection, build_print_page_map
from FNM_RE.stages.note_items import build_note_items
from FNM_RE.stages.note_links import build_note_links
from FNM_RE.stages.note_regions import build_note_regions
from FNM_RE.stages.page_partition import build_page_partitions, summarize_page_partitions
from FNM_RE.stages.reviews import build_structure_reviews
from FNM_RE.stages.section_heads import build_section_heads
from FNM_RE.stages.units import build_translation_units
from FNM_RE.app.status import build_module_gate_status, build_phase4_status, build_phase6_status


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
    page_partitions, pre_extracted_page_candidates, file_idx_map = build_page_partitions(
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
        pre_extracted_page_candidates=pre_extracted_page_candidates,
        file_idx_map=file_idx_map,
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
    _bare_verifier = None
    if pdf_path:
        try:
            from FNM_RE.modules.llm_bare_digit_verify import verify_bare_digit_candidates
            _bare_verifier = verify_bare_digit_candidates
        except Exception:
            pass
    body_anchors, body_anchor_summary = build_body_anchors(phase2, pages=pages, pdf_path=str(pdf_path or ""), bare_digit_verifier=_bare_verifier)
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

    - action='create'：根据 payload 构造 BodyAnchorRecord 并追加；若 anchor_id 已存在或
      同章同页同 marker 已有显式锚点则跳过。
    - 其它 action：忽略（当前只支持创建；删除/修改留给后续）。
    """
    effective_anchors, materialize_summary, _logs = _materialize_anchor_overrides(
        list(body_anchors or []),
        anchor_overrides=anchor_overrides,
    )
    rejected_reasons = list(materialize_summary.get("rejected_reasons") or [])
    duplicate_reasons = [
        reason
        for reason in rejected_reasons
        if str(reason).endswith(":anchor_id_conflict")
        or str(reason).endswith(":existing_explicit_anchor")
    ]
    invalid_count = max(
        0,
        int(materialize_summary.get("rejected_count") or 0) - len(duplicate_reasons),
    )
    summary = {
        "created_anchor_count": int(materialize_summary.get("created_count") or 0),
        "skipped_duplicate_count": len(duplicate_reasons),
        "invalid_anchor_override_count": invalid_count,
        "invalid_anchor_override_flags": rejected_reasons,
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
    """Thin wrapper: 委托 modules/note_linking 的实现，丢弃 logs 返回值。"""
    effective_links, override_summary, _logs = _apply_link_overrides_impl(
        note_links,
        link_overrides=link_overrides,
        note_items=note_items,
        body_anchors=body_anchors,
        note_regions=note_regions,
    )
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
    # 使用覆盖后的 anchor（含 LLM 合成的），但不写回 phase3。
    # 下游通过本局部变量消费，保持树状原则：不修改上游对象。
    body_anchors_for_phase4 = (
        effective_body_anchors
        if int(anchor_override_summary.get("created_anchor_count") or 0) > 0
        else phase3.body_anchors
    )
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
        body_anchors=body_anchors_for_phase4,
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
        print_page_map=build_print_page_map(pages),
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


_LLM_IDLE_TIMEOUT = float(os.environ.get("SUP_RECOVERY_IDLE_TIMEOUT", "120"))


def _run_sup_recovery_subprocess(
    doc_id, chapter_note_markers, chapter_page_ranges,
    pdf_path, effective_split_layers, grouped_overrides_for_link,
) -> tuple[dict, dict, dict, list]:
    """子进程执行 sup_recovery + visual_anchor_recovery，返回 (enriched_map, vr_overrides, worker_usage)。

    采用活动心跳监测：子进程每次 LLM API 调用前后输出 [llm:req]/[llm:res]
    到 stderr，父进程跟踪最后活动时间戳。超过 _LLM_IDLE_TIMEOUT 秒无
    任何 LLM 活动则判定卡死并 kill，避免盲 timeout 无法区分正常等待与挂起。
    """
    import subprocess, json as _json, sys as _sys, threading
    import time as _time
    from dataclasses import asdict as _asdict

    # 只传 worker 真正需要的字段——避免整个 ChapterLayer 深度序列化
    def _slim_chapter(ch):
        return {
            "chapter_id": ch.chapter_id,
            "title": ch.title,
            "policy_applied": dict(ch.policy_applied or {}),
            "body_pages": [
                {"page_no": bp.page_no, "text": bp.text,
                 "split_reason": bp.split_reason, "source_role": bp.source_role}
                for bp in (ch.body_pages or [])
            ],
            "footnote_items": [_asdict(fi) for fi in (ch.footnote_items or [])],
            "endnote_items": [_asdict(ei) for ei in (ch.endnote_items or [])],
            "endnote_regions": [_asdict(er) for er in (ch.endnote_regions or [])],
        }

    import tempfile as _tempfile, os as _os
    _tmp_fd, _tmp_path = _tempfile.mkstemp(suffix=".json", prefix="fnm_worker_")
    params = {
        "doc_id": doc_id,
        "pdf_path": pdf_path,
        "chapter_note_markers": {k: list(v) for k, v in chapter_note_markers.items()},
        "chapter_page_ranges": {k: list(v) for k, v in chapter_page_ranges.items()},
        "has_chapter_layers": bool(effective_split_layers.chapters),
        "output_path": _tmp_path,  # worker 将大 JSON 写入此路径
    }
    input_data = _json.dumps(params).encode()

    proc = subprocess.Popen(
        [_sys.executable, "-m", "FNM_RE.modules._sup_recovery_worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**_os.environ, "FNM_WORKER_OUTPUT_PATH": _tmp_path},
    )
    proc.stdin.write(input_data)
    proc.stdin.close()

    # ── 活动心跳监测 ──
    last_activity = _time.monotonic()           # 最后一次 LLM 活动时间
    activity_lock = threading.Lock()
    llm_call_count = 0
    killed_by_idle = False
    stderr_lines: list[str] = []

    def _touch_activity():
        nonlocal last_activity, llm_call_count
        with activity_lock:
            last_activity = _time.monotonic()
            llm_call_count += 1

    def _read_stderr():
        """逐行读取 stderr，解析心跳标签并转发到父进程 stderr。"""
        for raw_line in proc.stderr:
            line = raw_line.decode(errors="replace").rstrip()
            stderr_lines.append(line)
            if "[llm:req]" in line or "[llm:res]" in line:
                _touch_activity()
            print(f"  [worker] {line}", file=_sys.stderr, flush=True)

    def _read_stdout() -> bytes:
        """读完整 stdout（JSON 结果）。"""
        return proc.stdout.read()

    def _watchdog():
        """定期检查 LLM 活动——仅在首次 LLM 调用后开始计时。"""
        nonlocal killed_by_idle
        while proc.poll() is None:
            _time.sleep(10)
            with activity_lock:
                idle_sec = _time.monotonic() - last_activity
                has_llm = llm_call_count > 0
            # 首次 LLM 调用前不计空闲（可能在做非 LLM 计算）
            if has_llm and idle_sec > _LLM_IDLE_TIMEOUT:
                print(
                    f"[sup_recovery subprocess] IDLE {idle_sec:.0f}s > {_LLM_IDLE_TIMEOUT}s "
                    f"after {llm_call_count} LLM calls, killing",
                    file=_sys.stderr, flush=True,
                )
                killed_by_idle = True
                proc.kill()
                return

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stdout_holder: list[bytes] = []

    def _stdout_wrapper():
        stdout_holder.append(_read_stdout())

    stdout_thread = threading.Thread(target=_stdout_wrapper, daemon=True)
    watchdog_thread = threading.Thread(target=_watchdog, daemon=True)

    stderr_thread.start()
    stdout_thread.start()
    watchdog_thread.start()

    proc.wait()
    stderr_thread.join(timeout=5)
    stdout_thread.join(timeout=5)

    stdout_data = stdout_holder[0] if stdout_holder else b""

    with activity_lock:
        total_calls = llm_call_count

    if proc.returncode != 0:
        reason = "idle_timeout" if killed_by_idle else f"exit={proc.returncode}"
        print(
            f"[sup_recovery subprocess] failed ({reason}), llm_calls={total_calls}",
            file=_sys.stderr, flush=True,
        )
        return {}, {}, {}, []

    print(
        f"[sup_recovery subprocess] done, llm_calls={total_calls}",
        file=_sys.stderr, flush=True,
    )
    # 优先从临时文件读取大 JSON（避免 stdout buffer 截断）
    result = {}
    if _os.path.isfile(_tmp_path):
        try:
            with open(_tmp_path, "r", encoding="utf-8") as f:
                result = _json.loads(f.read())
        except Exception:
            pass
    if not result:
        try:
            result = _json.loads(stdout_data) if stdout_data else {}
        except Exception:
            pass
    _os.unlink(_tmp_path)
    enriched_map = {int(k): v for k, v in result.get("enriched_map", {}).items()}
    vr_overrides = result.get("vr_overrides", {})
    worker_usage = result.get("usage_summary", {})
    worker_traces = result.get("_traces", [])
    return enriched_map, vr_overrides, worker_usage, worker_traces


def _convert_page_segments_to_dicts(segments):
    """将 dataclass page_segments 转为可序列化的 dict 列表。"""
    from dataclasses import asdict as _asdict
    result = []
    for seg in (segments or []):
        if isinstance(seg, dict):
            result.append(seg)
        else:
            result.append(_asdict(seg))
    return result


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


def _get_pipeline_repo():
    """Lazy singleton SQLiteRepository for in-pipeline DB access."""
    from persistence.sqlite_store import SQLiteRepository
    return SQLiteRepository()


def _make_stage_result(data):
    """Wrap a plain data object as a minimal stage result for downstream consumers."""
    from types import SimpleNamespace
    gate_report = SimpleNamespace(
        module="reconstructed", hard={}, soft={}, reasons=[], blockers=[], warnings=[],
        evidence={}, overrides_used=[],
    )
    return SimpleNamespace(data=data, gate_report=gate_report, diagnostics={}, evidence={})


def _reconstruct_toc_and_book_for_rebuild(doc_id: str, pages: list[dict]):
    """从 DB 重建 TocStructure + BookNoteProfile，用于 start_phase 跳过 Phase 1。"""
    from FNM_RE.app.db_reconstruct import reconstruct_toc_structure, reconstruct_book_note_profile
    repo = _get_pipeline_repo()
    toc_data = reconstruct_toc_structure(repo, doc_id)
    book_data = reconstruct_book_note_profile(repo, doc_id)
    toc_result = _make_stage_result(toc_data)
    book_type_result = _make_stage_result(book_data)
    return toc_result, book_type_result


def _reconstruct_chapter_layers_for_rebuild(doc_id: str, pdf_path: str, pages: list[dict]):
    """从 DB 重建 ChapterLayers，用于 start_phase='note_link_table' 跳过 Phase 1-2。"""
    from FNM_RE.modules.types import ChapterLayers
    from FNM_RE.modules._sup_recovery_worker import _reconstruct_chapter_layers_from_db
    repo = _get_pipeline_repo()
    chapters_raw = repo.list_fnm_chapters(doc_id) or []
    chapter_page_ranges = {}
    for ch in chapters_raw:
        cid = str(ch.get("chapter_id", ""))
        sp = int(ch.get("start_page", 0))
        ep = int(ch.get("end_page", 0))
        if cid and sp and ep:
            chapter_page_ranges[cid] = (sp, ep)
    return _reconstruct_chapter_layers_from_db(repo, doc_id, chapter_page_ranges)


def _merge_usage_dicts(*dicts: dict) -> dict:
    """合并多个 usage_summary dict，key 累加。"""
    result: dict = {"by_stage": {}, "by_model": {}, "total": {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
    for d in dicts:
        if not d:
            continue
        for section in ("by_stage", "by_model"):
            for key, row in dict(d.get(section) or {}).items():
                target = result[section].setdefault(key, {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
                for k in ("request_count", "prompt_tokens", "completion_tokens", "total_tokens"):
                    target[k] += int(row.get(k) or 0)
        total_row = dict(d.get("total") or {})
        for k in ("request_count", "prompt_tokens", "completion_tokens", "total_tokens"):
            result["total"][k] += int(total_row.get(k) or 0)
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
    start_phase: str = "toc",
) -> ModulePipelineSnapshot:
    """构建模块管道快照。

    start_phase 控制从哪个 Phase 开始执行：
      "toc"              — 完整运行（默认）
      "chapter_layers"   — 跳过 TOC + book_note_profile，从 chapter_layers 开始
      "note_link_table"  — 跳过 Phase 1-2，从 DB 重建 ChapterLayers 后从 Phase 3 开始
      "frozen_units"     — 跳过 Phase 1-3，从 DB 重建 ChapterLayers + NoteLinkTable 后从 Phase 4 开始
    """
    pages = list(pages or [])
    import hashlib, time, uuid
    _pipeline_run_id = hashlib.sha256(
        f"{str(doc_id or '')}-{int(time.time())}-{uuid.uuid4().hex[:8]}".encode()
    ).hexdigest()[:16]
    grouped_overrides = _group_review_overrides(review_overrides)
    _start = str(start_phase or "toc").strip().lower()
    _worker_usage: dict = {}
    _worker_traces: list = []
    _llm_repair_usage: dict = {}

    # ── Phase 1a: TOC Structure ──
    if _start == "toc":
        toc_result = _run_stage(
            progress_callback=progress_callback, stage="toc_structure", label="构建目录与章节结构",
            start_pct=97.0, end_pct=97.9,
            runner=lambda: build_toc_structure(
                pages,
                _normalize_toc_items_with_offset(toc_items, toc_offset=int(toc_offset or 0)),
                manual_page_overrides=grouped_overrides.get("page"),
                pdf_path=str(pdf_path or ""), visual_toc_bundle=visual_toc_bundle, doc_id=doc_id,
            ),
        )
        # Phase 1 持久化 → 释放轻量页 → 重载完整页
        if doc_id:
            try:
                from persistence.sqlite_store import SQLiteRepository as _SR
                from FNM_RE.app.persist_helpers import (
                    serialize_pages_for_repo, serialize_heading_candidates_for_repo,
                    serialize_section_heads_for_repo, to_plain,
                )
                _repo = _SR()
                _repo.replace_fnm_phase1_products(
                    doc_id,
                    pages=serialize_pages_for_repo(list(toc_result.data.pages or [])),
                    chapters=[to_plain(r) for r in (toc_result.data.chapters or [])],
                    heading_candidates=serialize_heading_candidates_for_repo(
                        list(toc_result.diagnostics.get("heading_candidates") or [])),
                    section_heads=serialize_section_heads_for_repo(list(toc_result.data.section_heads or [])),
                )
                pages.clear()
                gc.collect()
                pages.extend(_repo.load_pages(doc_id, exclude_pruned=True))
            except Exception:
                import sys as _sys, traceback as _tb
                print("[pipeline] Phase1 persist failed:", file=_sys.stderr)
                _tb.print_exc(file=_sys.stderr)

        _need_llm = bool(str(pdf_path or "").strip())
        _light_pages: list[dict] = []
        if _need_llm:
            _light_pages = [
                {"bookPage": p.get("bookPage"), "pdfPage": p.get("pdfPage", p.get("bookPage")),
                 "fileIdx": p.get("fileIdx"), "_note_scan": p.get("_note_scan"), "fnBlocks": p.get("fnBlocks")}
                for p in pages
            ]

        # Phase 1b: Book Note Profile
        book_type_result = _run_stage(
            progress_callback=progress_callback, stage="book_note_profile", label="判定章节注释模式",
            start_pct=98.0, end_pct=98.6,
            runner=lambda: build_book_note_profile(
                toc_result.data, pages=pages,
                overrides={"chapter_modes": grouped_overrides.get("chapter")},
            ),
        )
        # Phase 1c: LLM Book Type Verify
        if _need_llm:
            try:
                from FNM_RE.modules.llm_book_type_verify import verify_book_type_with_llm
                _emit_progress(progress_callback=progress_callback, stage="llm_book_type_verify",
                               label="LLM交叉验证书型", pct=98.63, event="start")
                llm_verify_result = verify_book_type_with_llm(
                    toc_structure=toc_result.data, book_type_profile=book_type_result.data,
                    pages=_light_pages or [], pdf_path=str(pdf_path or ""),
                )
                book_type_result.gate_report.evidence["llm_verification"] = llm_verify_result.data
                if llm_verify_result.gate_report.soft.get("llm.disagreement"):
                    book_type_result.gate_report.soft["llm_disagreement"] = True
                    book_type_result.gate_report.reasons.append("llm_verification_disagreement")
                _emit_progress(progress_callback=progress_callback, stage="llm_book_type_verify",
                               label="LLM交叉验证书型", pct=98.68, event="done")
            except Exception as _llm_err:
                _emit_progress(progress_callback=progress_callback, stage="llm_book_type_verify",
                               label="LLM书型验证失败（非阻断）", pct=98.65, event="warn")
                book_type_result.gate_report.evidence["llm_verification"] = {
                    "error": str(_llm_err), "fallback": "trust_rules",
                }
    else:
        # 从 DB 重建 TocStructure + BookNoteProfile（轻量）
        from FNM_RE.app.db_reconstruct import reconstruct_toc_structure, reconstruct_book_note_profile
        _repo = _get_pipeline_repo()
        toc_result = _make_stage_result(reconstruct_toc_structure(_repo, doc_id))
        book_type_result = _make_stage_result(reconstruct_book_note_profile(_repo, doc_id))
        _light_pages = []
        _need_llm = False

    # ── Phase 2: Chapter Layers + sup_recovery ──
    if _start in ("toc", "chapter_layers"):
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
                doc_id=str(doc_id or ""),
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

    # ── sup_recovery + visual_anchor_recovery：子进程隔离 ──
    # 必须在 Phase 2（note_items 已产出）之后、Phase 3（读 enriched_markdown）之前
    # SKIP_SUP_RECOVERY=1 跳过 L3 vision API 调用以加速非生产测试
    if _start in ("toc", "chapter_layers") and str(pdf_path or "").strip() and not os.environ.get("SKIP_SUP_RECOVERY"):
        try:
            chapter_note_markers: dict[str, set[str]] = {}
            chapter_page_ranges: dict[str, tuple[int, int]] = {}
            for chapter in toc_result.data.chapters:
                ch_id = str(chapter.chapter_id or "")
                if not ch_id:
                    continue
                start_p = int(chapter.start_page or 0)
                end_p = int(chapter.end_page or 0)
                if start_p > 0 and end_p >= start_p:
                    chapter_page_ranges[ch_id] = (start_p, end_p)
            for item in split_result.data.note_items:
                ch_id = str(item.chapter_id or "")
                marker = str(item.marker or "").strip()
                if ch_id and marker.isdigit():
                    chapter_note_markers.setdefault(ch_id, set()).add(marker)
            print(f"[sup_recovery] chapters={len(chapter_page_ranges)} "
                  f"ch_with_markers={len(chapter_note_markers)} "
                  f"pdf_path={'yes' if pdf_path else 'no'}")

            if chapter_note_markers and chapter_page_ranges:
                if doc_id:
                    # 子进程执行（L3 vision + PDF 解析在子进程，退出即释放全部内存）
                    enriched_map, vr_overrides, _worker_usage, _worker_traces = _run_sup_recovery_subprocess(
                        doc_id, chapter_note_markers, chapter_page_ranges,
                        str(pdf_path), effective_split_layers, grouped_overrides_for_link,
                    )
                    # 回写 enriched_markdown
                    for page in pages:
                        pn = int(page.get("pdfPage") or page.get("page_no") or 0)
                        if pn in enriched_map:
                            page["enriched_markdown"] = enriched_map[pn]
                    for chapter in effective_split_layers.chapters:
                        for bp in chapter.body_pages:
                            pn = int(bp.page_no or 0)
                            if pn in enriched_map:
                                bp.text = enriched_map[pn]
                    # 合并 vr_overrides
                    for scope, items in vr_overrides.items():
                        target = grouped_overrides_for_link.setdefault(str(scope), {})
                        for key, payload in items.items():
                            if key not in target:
                                target[key] = payload
                else:
                    # 旧路径原地执行
                    from FNM_RE.modules.sup_recovery import recover_book_chapter_scoped
                    stats = recover_book_chapter_scoped(
                        pages, chapter_note_markers, chapter_page_ranges,
                        pdf_path=str(pdf_path),
                    )
                    print(f"[sup_recovery] done: {stats}")
                    # 旧路径 visual_anchor_recovery
                    from FNM_RE.modules.visual_anchor_recovery import build_visual_recovery_overrides
                    from FNM_RE.modules.note_linking import _phase2_from_chapter_layers as _resolve_phase2
                    from FNM_RE.stages.body_anchors import build_body_anchors as _build_body_anchors_for_gap
                    phase2_for_gap, _, _ = _resolve_phase2(effective_split_layers)
                    gap_anchors, _ = _build_body_anchors_for_gap(phase2_for_gap, pages=pages, pdf_path=str(pdf_path))
                    vr_overrides = build_visual_recovery_overrides(
                        phase2=phase2_for_gap, body_anchors=gap_anchors,
                        pages=pages, pdf_path=str(pdf_path),
                    )
                    if vr_overrides:
                        for scope, items in vr_overrides.items():
                            target = grouped_overrides_for_link.setdefault(str(scope), {})
                            for key, payload in items.items():
                                if key not in target:
                                    target[key] = payload
        except Exception as _e:
            print(f"[sup_recovery] pipeline call failed: {_e}")
            import traceback
            traceback.print_exc()

    # ── sup_recovery 结果回写到 ChapterLayers.body_pages.text ──
    if _start in ("toc", "chapter_layers") and str(pdf_path or "").strip():
        for chapter in effective_split_layers.chapters:
            for bp in chapter.body_pages:
                pn = int(bp.page_no or 0)
                if pn <= 0:
                    continue
                page = next((p for p in pages if int(p.get("pdfPage") or p.get("page_no") or 0) == pn), None)
                if page and page.get("enriched_markdown"):
                    bp.text = page["enriched_markdown"]
    if _start not in ("toc", "chapter_layers"):
        # start_phase="note_link_table" 或 "frozen_units": 从 DB 重建 ChapterLayers
        effective_split_layers = _reconstruct_chapter_layers_for_rebuild(doc_id, str(pdf_path), pages)
        split_result = _make_stage_result(effective_split_layers)
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
            effective_split_layers, pages,
            pdf_path=str(pdf_path or ""),
            overrides=grouped_overrides_for_link,
        ),
    )
    # Phase 3 产物立即落盘（幂等覆盖写，后续 _persist_phase6_to_repo 可再次写入）
    if doc_id:
        try:
            from persistence.sqlite_store import SQLiteRepository as _R
            _R().replace_fnm_phase3_products(
                doc_id,
                body_anchors=[{
                    "anchor_id": str(getattr(a, "anchor_id", "") or ""),
                    "chapter_id": str(getattr(a, "chapter_id", "") or ""),
                    "page_no": int(getattr(a, "page_no", 0) or 0),
                    "paragraph_index": int(getattr(a, "paragraph_index", 0) or 0),
                    "char_start": int(getattr(a, "char_start", 0) or 0),
                    "char_end": int(getattr(a, "char_end", 0) or 0),
                    "source_marker": str(getattr(a, "source_marker", "") or ""),
                    "normalized_marker": str(getattr(a, "normalized_marker", "") or ""),
                    "anchor_kind": str(getattr(a, "anchor_kind", "") or ""),
                    "certainty": float(getattr(a, "certainty", 0.0) or 0.0),
                    "source_text": str(getattr(a, "source_text", "") or ""),
                } for a in link_result.data.anchors],
                note_links=[{
                    "link_id": str(getattr(l, "link_id", "") or ""),
                    "chapter_id": str(getattr(l, "chapter_id", "") or ""),
                    "region_id": str(getattr(l, "region_id", "") or ""),
                    "note_item_id": str(getattr(l, "note_item_id", "") or ""),
                    "anchor_id": str(getattr(l, "anchor_id", "") or ""),
                    "status": str(getattr(l, "status", "") or ""),
                    "resolver": str(getattr(l, "resolver", "") or ""),
                    "confidence": float(getattr(l, "confidence", 0.0) or 0.0),
                    "note_kind": str(getattr(l, "note_kind", "") or ""),
                    "marker": str(getattr(l, "marker", "") or ""),
                    "page_no_start": int(getattr(l, "page_no_start", 0) or 0),
                    "page_no_end": int(getattr(l, "page_no_end", 0) or 0),
                } for l in link_result.data.effective_links],
            )
        except Exception:
            import sys as _sys, traceback as _tb
            print("[pipeline] Phase3 DB persist failed:", file=_sys.stderr)
            _tb.print_exc(file=_sys.stderr)
    # pages 最后消费者（build_note_link_table）已完成 → 释放 pages
    from FNM_RE.stages.diagnostics import build_print_page_map
    _print_page_map = build_print_page_map(pages)
    pages.clear()
    gc.collect()

    # ── Phase 3.5: LLM Repair（嵌入管道，修补 Phase 3 未匹配的 anchors/links）──
    _llm_repair_applied = 0
    _llm_repair_usage = {}
    if doc_id:
        try:
            from FNM_RE.modules.llm_repair import run_llm_repair
            _repair_result = run_llm_repair(doc_id, slug=str(slug or doc_id), auto_apply=True) or {}
            _llm_repair_applied = int(_repair_result.get("auto_applied_count") or 0)
            _llm_repair_usage = dict(_repair_result.get("usage_summary") or {})
        except Exception as _llm_repair_err:
            import sys as _sys
            print(f"[pipeline] Phase 3.5 llm_repair failed (non-blocking): {_llm_repair_err}", file=_sys.stderr)

    freeze_result = _run_stage(
        progress_callback=progress_callback,
        stage="frozen_units",
        label="生成翻译单元",
        start_pct=99.56,
        end_pct=99.72,
        runner=lambda: build_frozen_units(
            effective_split_layers,
            link_result.data,
            book_structure_model=effective_split_layers.book_structure,
            max_body_chars=int(max_body_chars or 6000),
            pipeline_run_id=str(_pipeline_run_id or ""),
        ),
    )
    export_link_table = link_result.data
    frozen_units_effective = _overlay_repo_units_on_frozen(
        freeze_result.data,
        repo_units=repo_units,
        overlay_doc_id=str(doc_id or ""),
    )
    translation_units = _phase_translation_units_from_frozen(frozen_units_effective)

    # Phase 4 产物立即落盘（幂等覆盖写）
    if doc_id:
        try:
            from persistence.sqlite_store import SQLiteRepository as _R
            _R().replace_fnm_translation_units(
                doc_id,
                units=[{
                    "unit_id": str(getattr(u, "unit_id", "") or ""),
                    "kind": str(getattr(u, "kind", "") or ""),
                    "owner_kind": str(getattr(u, "owner_kind", "") or ""),
                    "owner_id": str(getattr(u, "owner_id", "") or ""),
                    "section_id": str(getattr(u, "section_id", "") or ""),
                    "section_title": str(getattr(u, "section_title", "") or ""),
                    "section_start_page": int(getattr(u, "section_start_page", 0) or 0),
                    "section_end_page": int(getattr(u, "section_end_page", 0) or 0),
                    "note_id": str(getattr(u, "note_id", "") or ""),
                    "page_start": int(getattr(u, "page_start", 0) or 0),
                    "page_end": int(getattr(u, "page_end", 0) or 0),
                    "char_count": int(getattr(u, "char_count", 0) or 0),
                    "source_text": str(getattr(u, "source_text", "") or ""),
                    "translated_text": str(getattr(u, "translated_text", "") or ""),
                    "status": str(getattr(u, "status", "pending") or "pending"),
                    "error_msg": str(getattr(u, "error_msg", "") or ""),
                    "target_ref": str(getattr(u, "target_ref", "") or ""),
                    "page_segments": _convert_page_segments_to_dicts(getattr(u, "page_segments", []) or []),
                    "source_hash": str(getattr(u, "source_hash", "") or ""),
                    "segment_plan_hash": str(getattr(u, "segment_plan_hash", "") or ""),
                    "pipeline_run_id": str(getattr(u, "pipeline_run_id", "") or ""),
                    "stale_reason": str(getattr(u, "stale_reason", "") or ""),
                } for u in translation_units],
            )
        except Exception:
            import sys as _sys, traceback as _tb
            print("[pipeline] Phase4 DB persist failed:", file=_sys.stderr)
            _tb.print_exc(file=_sys.stderr)

    phase4_shadow = Phase4Structure(
        pages=_phase_pages_from_toc(toc_result.data),
        heading_candidates=list(toc_result.diagnostics.get("heading_candidates") or []),
        chapters=_phase_chapters_from_toc(toc_result.data),
        section_heads=_phase_section_heads_from_toc(toc_result.data),
        note_regions=_phase_note_regions_from_layers(effective_split_layers),
        note_items=_phase_note_items_from_layers(effective_split_layers),
        chapter_note_modes=_phase_chapter_note_modes_from_layers(effective_split_layers),
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
            print_page_map=_print_page_map,
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
            book_structure_model=split_result.data.book_structure,
            diagnostic_machine_by_page=_diagnostic_machine_by_page(diagnostic_pages),
            include_diagnostic_entries=bool(include_diagnostic_entries),
            section_heads=_phase_section_heads_from_toc(toc_result.data),
        ),
    )
    # Phase 5 完成 → 释放 body page_segments（Phase 6 export 不读）
    for unit in frozen_units_effective.body_units:
        unit.page_segments = []
    gc.collect()
    export_result = _run_stage(
        progress_callback=progress_callback,
        stage="export_bundle",
        label="构建导出结构与审计",
        start_pct=99.91,
        end_pct=99.98,
        runner=lambda: build_module_export_bundle(
            merge_result.data,
            toc_result.data,
            book_structure_model=split_result.data.book_structure,
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
    # 聚合管道内 token 用量
    _pipeline_usage = _merge_usage_dicts(_worker_usage if '_worker_usage' in dir() else {},
                                          _llm_repair_usage if '_llm_repair_usage' in dir() else {})

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
    snapshot.pipeline_usage = _pipeline_usage  # 附加到 snapshot 上
    snapshot.pipeline_usage["_worker_traces"] = _worker_traces
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

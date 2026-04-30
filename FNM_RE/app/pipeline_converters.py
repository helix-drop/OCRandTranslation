"""FNM_RE 管道数据转换层。

从 pipeline.py 提取的 ModulePipelineSnapshot 类与数据转换辅助函数。
"""

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
from FNM_RE.shared.review_overrides import group_review_overrides as _group_review_overrides, empty_grouped_overrides as _empty_grouped_overrides
from FNM_RE.shared.text import _summary_title_key
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
    if token in {"note", "endnotes"}:
        return "note"
    if token == "noise":
        return "noise"
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


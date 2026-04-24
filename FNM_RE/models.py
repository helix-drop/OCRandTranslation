"""FNM_RE 分阶段领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from FNM_RE.constants import (
    AnchorKind,
    BoundaryState,
    ChapterSource,
    LinkResolver,
    LinkStatus,
    NoteKind,
    NoteMode,
    PageRole,
    RegionScope,
    RegionSource,
)


@dataclass(slots=True)
class PagePartitionRecord:
    page_no: int
    target_pdf_page: int
    page_role: PageRole
    confidence: float
    reason: str
    section_hint: str
    has_note_heading: bool
    note_scan_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HeadingCandidate:
    heading_id: str
    page_no: int
    text: str
    normalized_text: str
    source: str
    block_label: str
    top_band: bool
    confidence: float
    heading_family_guess: str
    suppressed_as_chapter: bool
    reject_reason: str
    font_height: float | None = None
    x: float | None = None
    y: float | None = None
    width_estimate: float | None = None
    font_name: str = ""
    font_weight_hint: str = "unknown"
    align_hint: str = "unknown"
    width_ratio: float | None = None
    heading_level_hint: int = 0


@dataclass(slots=True)
class ChapterRecord:
    chapter_id: str
    title: str
    start_page: int
    end_page: int
    pages: list[int]
    source: ChapterSource
    boundary_state: BoundaryState


@dataclass(slots=True)
class SectionHeadRecord:
    section_head_id: str
    chapter_id: str
    title: str
    page_no: int
    level: int
    source: str


@dataclass(slots=True)
class Phase1Summary:
    page_partition_summary: dict[str, Any] = field(default_factory=dict)
    heading_review_summary: dict[str, Any] = field(default_factory=dict)
    heading_graph_summary: dict[str, Any] = field(default_factory=dict)
    chapter_source_summary: dict[str, Any] = field(default_factory=dict)
    visual_toc_conflict_count: int = 0
    toc_alignment_summary: dict[str, Any] = field(default_factory=dict)
    toc_semantic_summary: dict[str, Any] = field(default_factory=dict)
    toc_role_summary: dict[str, Any] = field(default_factory=dict)
    container_titles: list[str] = field(default_factory=list)
    post_body_titles: list[str] = field(default_factory=list)
    back_matter_titles: list[str] = field(default_factory=list)
    chapter_title_alignment_ok: bool = True
    chapter_section_alignment_ok: bool = True
    toc_semantic_contract_ok: bool = True
    toc_semantic_blocking_reasons: list[str] = field(default_factory=list)
    visual_toc_endnotes_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Phase1Structure:
    pages: list[PagePartitionRecord] = field(default_factory=list)
    heading_candidates: list[HeadingCandidate] = field(default_factory=list)
    chapters: list[ChapterRecord] = field(default_factory=list)
    section_heads: list[SectionHeadRecord] = field(default_factory=list)
    endnote_explorer_hints: dict[str, Any] = field(default_factory=dict)
    summary: Phase1Summary = field(default_factory=Phase1Summary)


@dataclass(slots=True)
class NoteRegionRecord:
    region_id: str
    chapter_id: str
    page_start: int
    page_end: int
    pages: list[int]
    note_kind: NoteKind
    scope: RegionScope
    source: RegionSource
    heading_text: str
    start_reason: str
    end_reason: str
    region_marker_alignment_ok: bool
    region_start_first_source_marker: str
    region_first_note_item_marker: str
    review_required: bool


@dataclass(slots=True)
class NoteItemRecord:
    note_item_id: str
    region_id: str
    chapter_id: str
    page_no: int
    marker: str
    marker_type: str
    text: str
    source: str
    source_page_label: str
    is_reconstructed: bool
    review_required: bool


@dataclass(slots=True)
class ChapterNoteModeRecord:
    chapter_id: str
    note_mode: NoteMode
    region_ids: list[str] = field(default_factory=list)
    primary_region_scope: str = ""
    has_footnote_band: bool = False
    has_endnote_region: bool = False


@dataclass(slots=True)
class Phase2Summary:
    page_partition_summary: dict[str, Any] = field(default_factory=dict)
    heading_review_summary: dict[str, Any] = field(default_factory=dict)
    heading_graph_summary: dict[str, Any] = field(default_factory=dict)
    chapter_source_summary: dict[str, Any] = field(default_factory=dict)
    visual_toc_conflict_count: int = 0
    toc_alignment_summary: dict[str, Any] = field(default_factory=dict)
    toc_semantic_summary: dict[str, Any] = field(default_factory=dict)
    toc_role_summary: dict[str, Any] = field(default_factory=dict)
    container_titles: list[str] = field(default_factory=list)
    post_body_titles: list[str] = field(default_factory=list)
    back_matter_titles: list[str] = field(default_factory=list)
    chapter_title_alignment_ok: bool = True
    chapter_section_alignment_ok: bool = True
    toc_semantic_contract_ok: bool = True
    toc_semantic_blocking_reasons: list[str] = field(default_factory=list)
    note_region_summary: dict[str, Any] = field(default_factory=dict)
    note_item_summary: dict[str, Any] = field(default_factory=dict)
    chapter_note_mode_summary: dict[str, Any] = field(default_factory=dict)
    chapter_endnote_region_alignment_ok: bool = True
    chapter_endnote_start_page_map: dict[str, int] = field(default_factory=dict)
    review_flags: list[str] = field(default_factory=list)
    visual_toc_endnotes_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Phase2Structure:
    pages: list[PagePartitionRecord] = field(default_factory=list)
    heading_candidates: list[HeadingCandidate] = field(default_factory=list)
    chapters: list[ChapterRecord] = field(default_factory=list)
    section_heads: list[SectionHeadRecord] = field(default_factory=list)
    note_regions: list[NoteRegionRecord] = field(default_factory=list)
    note_items: list[NoteItemRecord] = field(default_factory=list)
    chapter_note_modes: list[ChapterNoteModeRecord] = field(default_factory=list)
    summary: Phase2Summary = field(default_factory=Phase2Summary)


@dataclass(slots=True)
class BodyAnchorRecord:
    anchor_id: str
    chapter_id: str
    page_no: int
    paragraph_index: int
    char_start: int
    char_end: int
    source_marker: str
    normalized_marker: str
    anchor_kind: AnchorKind
    certainty: float
    source_text: str
    source: str
    synthetic: bool
    ocr_repaired_from_marker: str


@dataclass(slots=True)
class ChapterEndnoteRecord:
    doc_id: str = ""
    chapter_id: str = ""
    ordinal: int = 0
    marker: str = ""
    numbering_scheme: str = "per_chapter"
    text: str = ""
    source_page_no: int = 0
    is_reconstructed: bool = False
    review_required: bool = True


@dataclass(slots=True)
class ParagraphFootnoteRecord:
    doc_id: str = ""
    chapter_id: str = ""
    page_no: int = 0
    paragraph_index: int = 0
    attachment_kind: str = "page_tail"
    source_marker: str = ""
    text: str = ""


@dataclass(slots=True)
class ChapterAnchorAlignmentRecord:
    doc_id: str = ""
    chapter_id: str = ""
    alignment_status: str = "misaligned"
    body_anchor_count: int = 0
    endnote_count: int = 0
    mismatch: dict | None = None


@dataclass(slots=True)
class NoteLinkRecord:
    link_id: str
    chapter_id: str
    region_id: str
    note_item_id: str
    anchor_id: str
    status: LinkStatus
    resolver: LinkResolver
    confidence: float
    note_kind: NoteKind
    marker: str
    page_no_start: int
    page_no_end: int


@dataclass(slots=True)
class Phase3Summary:
    page_partition_summary: dict[str, Any] = field(default_factory=dict)
    heading_review_summary: dict[str, Any] = field(default_factory=dict)
    heading_graph_summary: dict[str, Any] = field(default_factory=dict)
    chapter_source_summary: dict[str, Any] = field(default_factory=dict)
    visual_toc_conflict_count: int = 0
    toc_alignment_summary: dict[str, Any] = field(default_factory=dict)
    toc_semantic_summary: dict[str, Any] = field(default_factory=dict)
    toc_role_summary: dict[str, Any] = field(default_factory=dict)
    container_titles: list[str] = field(default_factory=list)
    post_body_titles: list[str] = field(default_factory=list)
    back_matter_titles: list[str] = field(default_factory=list)
    chapter_title_alignment_ok: bool = True
    chapter_section_alignment_ok: bool = True
    toc_semantic_contract_ok: bool = True
    toc_semantic_blocking_reasons: list[str] = field(default_factory=list)
    note_region_summary: dict[str, Any] = field(default_factory=dict)
    note_item_summary: dict[str, Any] = field(default_factory=dict)
    chapter_note_mode_summary: dict[str, Any] = field(default_factory=dict)
    chapter_endnote_region_alignment_ok: bool = True
    chapter_endnote_start_page_map: dict[str, int] = field(default_factory=dict)
    body_anchor_summary: dict[str, Any] = field(default_factory=dict)
    note_link_summary: dict[str, Any] = field(default_factory=dict)
    review_seed_summary: dict[str, Any] = field(default_factory=dict)
    review_flags: list[str] = field(default_factory=list)
    paragraph_footnote_summary: dict[str, Any] = field(default_factory=dict)
    paragraph_endnote_summary: dict[str, Any] = field(default_factory=dict)
    chapter_anchor_alignment_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Phase3Structure:
    pages: list[PagePartitionRecord] = field(default_factory=list)
    heading_candidates: list[HeadingCandidate] = field(default_factory=list)
    chapters: list[ChapterRecord] = field(default_factory=list)
    section_heads: list[SectionHeadRecord] = field(default_factory=list)
    note_regions: list[NoteRegionRecord] = field(default_factory=list)
    note_items: list[NoteItemRecord] = field(default_factory=list)
    chapter_note_modes: list[ChapterNoteModeRecord] = field(default_factory=list)
    body_anchors: list[BodyAnchorRecord] = field(default_factory=list)
    note_links: list[NoteLinkRecord] = field(default_factory=list)
    paragraph_footnotes: list[ParagraphFootnoteRecord] = field(default_factory=list)
    paragraph_endnotes: list[ChapterEndnoteRecord] = field(default_factory=list)
    chapter_anchor_alignments: list[ChapterAnchorAlignmentRecord] = field(default_factory=list)
    summary: Phase3Summary = field(default_factory=Phase3Summary)


@dataclass(slots=True)
class StructureReviewRecord:
    review_id: str
    review_type: str
    chapter_id: str
    page_start: int
    page_end: int
    severity: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StructureStatusRecord:
    structure_state: str
    review_counts: dict[str, int] = field(default_factory=dict)
    blocking_reasons: list[str] = field(default_factory=list)
    link_summary: dict[str, int] = field(default_factory=dict)
    page_partition_summary: dict[str, Any] = field(default_factory=dict)
    chapter_mode_summary: dict[str, int] = field(default_factory=dict)
    heading_review_summary: dict[str, Any] = field(default_factory=dict)
    heading_graph_summary: dict[str, Any] = field(default_factory=dict)
    chapter_source_summary: dict[str, Any] = field(default_factory=dict)
    visual_toc_conflict_count: int = 0
    toc_alignment_summary: dict[str, Any] = field(default_factory=dict)
    toc_semantic_summary: dict[str, Any] = field(default_factory=dict)
    toc_role_summary: dict[str, Any] = field(default_factory=dict)
    container_titles: list[str] = field(default_factory=list)
    post_body_titles: list[str] = field(default_factory=list)
    back_matter_titles: list[str] = field(default_factory=list)
    visual_toc_endnotes_summary: dict[str, Any] = field(default_factory=dict)
    toc_semantic_contract_ok: bool = True
    toc_semantic_blocking_reasons: list[str] = field(default_factory=list)
    chapter_title_alignment_ok: bool = True
    chapter_section_alignment_ok: bool = True
    chapter_endnote_region_alignment_ok: bool = True
    chapter_endnote_region_alignment_summary: dict[str, Any] = field(
        default_factory=dict
    )
    manual_toc_ready: bool = True
    manual_toc_required: bool = False
    manual_toc_summary: dict[str, Any] = field(default_factory=dict)
    page_count: int = 0
    chapter_count: int = 0
    section_head_count: int = 0
    review_count: int = 0
    chapter_progress_summary: dict[str, Any] = field(default_factory=dict)
    note_region_progress_summary: dict[str, Any] = field(default_factory=dict)
    chapter_binding_summary: dict[str, Any] = field(default_factory=dict)
    note_capture_summary: dict[str, Any] = field(default_factory=dict)
    footnote_synthesis_summary: dict[str, Any] = field(default_factory=dict)
    chapter_link_contract_summary: dict[str, Any] = field(default_factory=dict)
    book_endnote_stream_summary: dict[str, Any] = field(default_factory=dict)
    freeze_note_unit_summary: dict[str, Any] = field(default_factory=dict)
    chapter_issue_counts: dict[str, Any] = field(default_factory=dict)
    chapter_issue_summary: list[dict[str, Any]] = field(default_factory=list)
    export_drift_summary: dict[str, Any] = field(default_factory=dict)
    chapter_local_endnote_contract_ok: bool = False
    export_semantic_contract_ok: bool = True
    front_matter_leak_detected: bool = False
    toc_residue_detected: bool = False
    mid_paragraph_heading_detected: bool = False
    duplicate_paragraph_detected: bool = False
    export_ready_test: bool = False
    export_ready_real: bool = False


@dataclass(slots=True)
class Phase4Summary:
    page_partition_summary: dict[str, Any] = field(default_factory=dict)
    heading_review_summary: dict[str, Any] = field(default_factory=dict)
    heading_graph_summary: dict[str, Any] = field(default_factory=dict)
    chapter_source_summary: dict[str, Any] = field(default_factory=dict)
    visual_toc_conflict_count: int = 0
    toc_alignment_summary: dict[str, Any] = field(default_factory=dict)
    toc_semantic_summary: dict[str, Any] = field(default_factory=dict)
    toc_role_summary: dict[str, Any] = field(default_factory=dict)
    container_titles: list[str] = field(default_factory=list)
    post_body_titles: list[str] = field(default_factory=list)
    back_matter_titles: list[str] = field(default_factory=list)
    chapter_title_alignment_ok: bool = True
    chapter_section_alignment_ok: bool = True
    toc_semantic_contract_ok: bool = True
    toc_semantic_blocking_reasons: list[str] = field(default_factory=list)
    note_region_summary: dict[str, Any] = field(default_factory=dict)
    note_item_summary: dict[str, Any] = field(default_factory=dict)
    chapter_note_mode_summary: dict[str, Any] = field(default_factory=dict)
    chapter_endnote_region_alignment_ok: bool = True
    chapter_endnote_start_page_map: dict[str, int] = field(default_factory=dict)
    body_anchor_summary: dict[str, Any] = field(default_factory=dict)
    note_link_summary: dict[str, Any] = field(default_factory=dict)
    review_seed_summary: dict[str, Any] = field(default_factory=dict)
    review_type_counts: dict[str, int] = field(default_factory=dict)
    override_summary: dict[str, Any] = field(default_factory=dict)
    review_flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Phase4Structure:
    pages: list[PagePartitionRecord] = field(default_factory=list)
    heading_candidates: list[HeadingCandidate] = field(default_factory=list)
    chapters: list[ChapterRecord] = field(default_factory=list)
    section_heads: list[SectionHeadRecord] = field(default_factory=list)
    note_regions: list[NoteRegionRecord] = field(default_factory=list)
    note_items: list[NoteItemRecord] = field(default_factory=list)
    chapter_note_modes: list[ChapterNoteModeRecord] = field(default_factory=list)
    body_anchors: list[BodyAnchorRecord] = field(default_factory=list)
    note_links: list[NoteLinkRecord] = field(default_factory=list)
    effective_note_links: list[NoteLinkRecord] = field(default_factory=list)
    structure_reviews: list[StructureReviewRecord] = field(default_factory=list)
    status: StructureStatusRecord = field(
        default_factory=lambda: StructureStatusRecord(structure_state="idle")
    )
    summary: Phase4Summary = field(default_factory=Phase4Summary)


@dataclass(slots=True)
class UnitParagraphRecord:
    order: int
    kind: str
    heading_level: int
    source_text: str
    display_text: str
    cross_page: Any
    consumed_by_prev: bool
    section_path: list[str] = field(default_factory=list)
    print_page_label: str = ""
    translated_text: str = ""
    translation_status: str = "pending"
    attempt_count: int = 0
    last_error: str = ""
    manual_resolved: bool = False


@dataclass(slots=True)
class UnitPageSegmentRecord:
    page_no: int
    paragraph_count: int
    source_text: str
    display_text: str
    paragraphs: list[UnitParagraphRecord] = field(default_factory=list)


@dataclass(slots=True)
class TranslationUnitRecord:
    unit_id: str
    kind: str
    owner_kind: str
    owner_id: str
    section_id: str
    section_title: str
    section_start_page: int
    section_end_page: int
    note_id: str
    page_start: int
    page_end: int
    char_count: int
    source_text: str
    translated_text: str
    status: str
    error_msg: str
    target_ref: str
    page_segments: list[UnitPageSegmentRecord] = field(default_factory=list)


@dataclass(slots=True)
class DiagnosticEntryRecord:
    original: str
    translation: str
    footnotes: str
    footnotes_translation: str
    heading_level: int
    pages: str
    _startBP: int
    _endBP: int
    _printPageLabel: str
    _status: str
    _error: str
    _translation_source: str
    _machine_translation: str
    _manual_translation: str
    _cross_page: Any
    _section_path: list[str] = field(default_factory=list)
    _fnm_refs: list[dict[str, Any]] = field(default_factory=list)
    _note_kind: str = ""
    _note_marker: str = ""
    _note_number: int | None = None
    _note_section_title: str = ""
    _note_confidence: float = 0.0
    _translation_status: str = "pending"
    _attempt_count: int = 0
    _manual_resolved: bool = False


@dataclass(slots=True)
class DiagnosticPageRecord:
    _pageBP: int
    _status: str
    pages: str
    _page_entries: list[DiagnosticEntryRecord] = field(default_factory=list)
    _fnm_source: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DiagnosticNoteRecord:
    note_id: str
    section_id: str
    section_title: str
    section_start_page: int
    section_end_page: int
    kind: str
    original_marker: str
    start_page: int
    pages: list[int] = field(default_factory=list)
    source_text: str = ""
    translated_text: str = ""
    translate_status: str = "pending"
    region_id: str = ""


@dataclass(slots=True)
class Phase5Summary:
    page_partition_summary: dict[str, Any] = field(default_factory=dict)
    heading_review_summary: dict[str, Any] = field(default_factory=dict)
    heading_graph_summary: dict[str, Any] = field(default_factory=dict)
    chapter_source_summary: dict[str, Any] = field(default_factory=dict)
    visual_toc_conflict_count: int = 0
    toc_alignment_summary: dict[str, Any] = field(default_factory=dict)
    toc_semantic_summary: dict[str, Any] = field(default_factory=dict)
    toc_role_summary: dict[str, Any] = field(default_factory=dict)
    container_titles: list[str] = field(default_factory=list)
    post_body_titles: list[str] = field(default_factory=list)
    back_matter_titles: list[str] = field(default_factory=list)
    chapter_title_alignment_ok: bool = True
    chapter_section_alignment_ok: bool = True
    toc_semantic_contract_ok: bool = True
    toc_semantic_blocking_reasons: list[str] = field(default_factory=list)
    note_region_summary: dict[str, Any] = field(default_factory=dict)
    note_item_summary: dict[str, Any] = field(default_factory=dict)
    chapter_note_mode_summary: dict[str, Any] = field(default_factory=dict)
    chapter_endnote_region_alignment_ok: bool = True
    chapter_endnote_start_page_map: dict[str, int] = field(default_factory=dict)
    body_anchor_summary: dict[str, Any] = field(default_factory=dict)
    note_link_summary: dict[str, Any] = field(default_factory=dict)
    review_seed_summary: dict[str, Any] = field(default_factory=dict)
    review_type_counts: dict[str, int] = field(default_factory=dict)
    override_summary: dict[str, Any] = field(default_factory=dict)
    review_flags: list[str] = field(default_factory=list)
    unit_planning_summary: dict[str, Any] = field(default_factory=dict)
    ref_materialization_summary: dict[str, Any] = field(default_factory=dict)
    diagnostic_page_summary: dict[str, Any] = field(default_factory=dict)
    diagnostic_note_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Phase5Structure:
    pages: list[PagePartitionRecord] = field(default_factory=list)
    heading_candidates: list[HeadingCandidate] = field(default_factory=list)
    chapters: list[ChapterRecord] = field(default_factory=list)
    section_heads: list[SectionHeadRecord] = field(default_factory=list)
    note_regions: list[NoteRegionRecord] = field(default_factory=list)
    note_items: list[NoteItemRecord] = field(default_factory=list)
    chapter_note_modes: list[ChapterNoteModeRecord] = field(default_factory=list)
    body_anchors: list[BodyAnchorRecord] = field(default_factory=list)
    note_links: list[NoteLinkRecord] = field(default_factory=list)
    effective_note_links: list[NoteLinkRecord] = field(default_factory=list)
    structure_reviews: list[StructureReviewRecord] = field(default_factory=list)
    translation_units: list[TranslationUnitRecord] = field(default_factory=list)
    diagnostic_pages: list[DiagnosticPageRecord] = field(default_factory=list)
    diagnostic_notes: list[DiagnosticNoteRecord] = field(default_factory=list)
    status: StructureStatusRecord = field(
        default_factory=lambda: StructureStatusRecord(structure_state="idle")
    )
    summary: Phase5Summary = field(default_factory=Phase5Summary)


@dataclass(slots=True)
class ExportChapterRecord:
    order: int = 0
    section_id: str = ""
    title: str = ""
    path: str = ""
    content: str = ""
    start_page: int = 0
    end_page: int = 0
    pages: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ExportBundleRecord:
    index_path: str = "index.md"
    chapters_dir: str = "chapters"
    chapters: list[ExportChapterRecord] = field(default_factory=list)
    chapter_files: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    export_semantic_contract_ok: bool = True
    front_matter_leak_detected: bool = False
    toc_residue_detected: bool = False
    mid_paragraph_heading_detected: bool = False
    duplicate_paragraph_detected: bool = False


@dataclass(slots=True)
class ExportAuditFileRecord:
    path: str = ""
    title: str = ""
    page_span: list[int] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)
    issue_summary: list[str] = field(default_factory=list)
    issue_details: list[dict[str, Any]] = field(default_factory=list)
    severity: str = "minor"
    sample_opening: str = ""
    sample_mid: str = ""
    sample_tail: str = ""
    footnote_endnote_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExportAuditReportRecord:
    slug: str = ""
    doc_id: str = ""
    zip_path: str = ""
    applicable: bool = True
    structure_state: str = "idle"
    blocking_reasons: list[str] = field(default_factory=list)
    manual_toc_summary: dict[str, Any] = field(default_factory=dict)
    toc_role_summary: dict[str, Any] = field(default_factory=dict)
    chapter_titles: list[str] = field(default_factory=list)
    files: list[ExportAuditFileRecord] = field(default_factory=list)
    blocking_issue_count: int = 0
    major_issue_count: int = 0
    can_ship: bool = False
    must_fix_before_next_book: list[dict[str, Any]] = field(default_factory=list)
    recommended_followups: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Phase6Summary(Phase5Summary):
    export_bundle_summary: dict[str, Any] = field(default_factory=dict)
    export_audit_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Phase6Structure(Phase5Structure):
    export_chapters: list[ExportChapterRecord] = field(default_factory=list)
    export_bundle: ExportBundleRecord = field(default_factory=ExportBundleRecord)
    export_audit: ExportAuditReportRecord = field(
        default_factory=ExportAuditReportRecord
    )
    status: StructureStatusRecord = field(
        default_factory=lambda: StructureStatusRecord(structure_state="idle")
    )
    summary: Phase6Summary = field(default_factory=Phase6Summary)

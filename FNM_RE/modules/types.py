"""FNM_RE 模块化阶段对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from typing import Literal

from FNM_RE.constants import (
    AnchorKind,
    BoundaryState,
    ChapterSource,
    LinkResolver,
    LinkStatus,
    NoteKind,
    NoteMode,
    RegionScope,
    RegionSource,
)

TocExternalRole = Literal["front_matter", "chapter", "post_body", "back_matter", "note", "endnotes"]
TocNodeRole = Literal["container", "endnotes", "chapter", "section", "post_body", "back_matter", "front_matter"]
BookNoteType = Literal["mixed", "endnote_only", "footnote_only", "no_notes"]
FreezeDecision = Literal["injected", "skipped"]
FrozenSkipReason = Literal[
    "synthetic_anchor",
    "conflict_anchor",
    "duplicate_anchor",
    "missing_anchor",
    "missing_body_page",
    "token_not_found",
]


@dataclass(slots=True)
class TocPageRole:
    page_no: int
    role: TocExternalRole
    source_role: str
    reason: str
    chapter_id: str = ""


@dataclass(slots=True)
class TocNode:
    node_id: str
    title: str
    role: TocNodeRole
    level: int
    target_pdf_page: int
    parent_id: str = ""


@dataclass(slots=True)
class TocChapter:
    chapter_id: str
    title: str
    start_page: int
    end_page: int
    pages: list[int] = field(default_factory=list)
    role: Literal["chapter", "post_body"] = "chapter"
    source: ChapterSource = "fallback"
    boundary_state: BoundaryState = "ready"


@dataclass(slots=True)
class TocSectionHead:
    section_head_id: str
    chapter_id: str
    title: str
    page_no: int
    level: int
    source: str


@dataclass(slots=True)
class TocStructure:
    pages: list[TocPageRole] = field(default_factory=list)
    toc_tree: list[TocNode] = field(default_factory=list)
    chapters: list[TocChapter] = field(default_factory=list)
    section_heads: list[TocSectionHead] = field(default_factory=list)


@dataclass(slots=True)
class ChapterNoteMode:
    chapter_id: str
    note_mode: NoteMode
    region_ids: list[str] = field(default_factory=list)
    has_footnote_band: bool = False
    has_endnote_region: bool = False
    evidence_page_nos: list[int] = field(default_factory=list)


@dataclass(slots=True)
class BookNoteTypeEvidence:
    footnote_page_count: int = 0
    endnote_page_count: int = 0
    chapter_mode_counts: dict[str, int] = field(default_factory=dict)
    chapter_review_required: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BookNoteProfile:
    book_type: BookNoteType
    chapter_modes: list[ChapterNoteMode] = field(default_factory=list)
    evidence: BookNoteTypeEvidence = field(default_factory=BookNoteTypeEvidence)


@dataclass(slots=True)
class LayerNoteRegion:
    region_id: str
    chapter_id: str
    page_start: int
    page_end: int
    pages: list[int]
    note_kind: NoteKind
    scope: RegionScope
    source: RegionSource
    heading_text: str
    review_required: bool
    owner_chapter_id: str = ""
    source_scope: str = ""
    bind_method: str = ""
    bind_confidence: float = 0.0
    # 工单 #2：region 首条 note item 的 marker（来自 NoteRegionRecord 同名字段，
    # 在 build_chapter_layers 内 build_note_items 后回填）。供下游契约校验
    # 与取证报告使用，避免空字符串。
    region_first_note_item_marker: str = ""


@dataclass(slots=True)
class LayerNoteItem:
    note_item_id: str
    region_id: str
    chapter_id: str
    page_no: int
    marker: str
    marker_type: str
    text: str
    source: str
    is_reconstructed: bool
    review_required: bool
    note_kind: NoteKind
    owner_chapter_id: str = ""
    source_marker: str = ""
    normalized_marker: str = ""
    synth_marker: str = ""
    projection_mode: str = ""


@dataclass(slots=True)
class BodyPageLayer:
    page_no: int
    text: str
    split_reason: str
    source_role: str


@dataclass(slots=True)
class BodySegmentLayer:
    page_no: int
    paragraph_count: int
    source_text: str
    display_text: str
    paragraphs: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ChapterLayer:
    chapter_id: str
    title: str
    body_pages: list[BodyPageLayer] = field(default_factory=list)
    body_segments: list[BodySegmentLayer] = field(default_factory=list)
    footnote_items: list[LayerNoteItem] = field(default_factory=list)
    endnote_items: list[LayerNoteItem] = field(default_factory=list)
    endnote_regions: list[LayerNoteRegion] = field(default_factory=list)
    policy_applied: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChapterLayers:
    chapters: list[ChapterLayer] = field(default_factory=list)
    regions: list[LayerNoteRegion] = field(default_factory=list)
    note_items: list[LayerNoteItem] = field(default_factory=list)
    region_summary: dict[str, Any] = field(default_factory=dict)
    item_summary: dict[str, Any] = field(default_factory=dict)
    # 由 chapter_split._chapter_body_marker_sets 累积：每章正文中识别到的 anchor marker 唯一数。
    # 工单 #3 契约 v2 用作 def_anchor_mismatch 的"对地"基线。
    chapter_marker_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class BodyAnchorLayer:
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
class NoteLinkLayer:
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
class ChapterLinkContract:
    chapter_id: str
    requires_endnote_contract: bool
    book_type: BookNoteType
    note_mode: NoteMode
    first_marker_is_one: bool
    endnotes_all_matched: bool
    no_ambiguous_left: bool
    no_orphan_note: bool
    endnote_only_no_orphan_anchor: bool
    failure_link_ids: list[str] = field(default_factory=list)
    # 工单 #3 契约 v2：对地校验（不依赖 requires_endnote_contract 短路）
    has_marker_gap: bool = False
    def_anchor_mismatch: bool = False
    def_count: int = 0
    anchor_total: int = 0
    marker_sequence: list[int] = field(default_factory=list)


@dataclass(slots=True)
class NoteLinkTable:
    anchors: list[BodyAnchorLayer] = field(default_factory=list)
    links: list[NoteLinkLayer] = field(default_factory=list)
    effective_links: list[NoteLinkLayer] = field(default_factory=list)
    chapter_link_contracts: list[ChapterLinkContract] = field(default_factory=list)
    anchor_summary: dict[str, Any] = field(default_factory=dict)
    link_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FrozenRefEntry:
    link_id: str
    chapter_id: str
    anchor_id: str
    note_item_id: str
    target_ref: str
    decision: FreezeDecision
    reason: FrozenSkipReason | str = ""
    page_no: int = 0


@dataclass(slots=True)
class FrozenUnit:
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
    page_segments: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class FrozenUnits:
    body_units: list[FrozenUnit] = field(default_factory=list)
    note_units: list[FrozenUnit] = field(default_factory=list)
    ref_map: list[FrozenRefEntry] = field(default_factory=list)
    freeze_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChapterMarkdownEntry:
    order: int
    chapter_id: str
    title: str
    path: str
    markdown_text: str
    start_page: int
    end_page: int
    pages: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ChapterMarkdownSet:
    chapters: list[ChapterMarkdownEntry] = field(default_factory=list)
    chapter_contract_summary: dict[str, Any] = field(default_factory=dict)
    merge_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExportAuditFile:
    path: str = ""
    title: str = ""
    page_span: list[int] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)
    issue_summary: list[str] = field(default_factory=list)
    severity: str = "minor"
    sample_opening: str = ""
    sample_mid: str = ""
    sample_tail: str = ""
    footnote_endnote_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExportAuditReport:
    slug: str = ""
    doc_id: str = ""
    zip_path: str = ""
    structure_state: str = "idle"
    blocking_reasons: list[str] = field(default_factory=list)
    manual_toc_summary: dict[str, Any] = field(default_factory=dict)
    toc_role_summary: dict[str, Any] = field(default_factory=dict)
    chapter_titles: list[str] = field(default_factory=list)
    files: list[ExportAuditFile] = field(default_factory=list)
    blocking_issue_count: int = 0
    major_issue_count: int = 0
    can_ship: bool = False
    must_fix_before_next_book: list[dict[str, Any]] = field(default_factory=list)
    recommended_followups: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ExportBundle:
    index_markdown: str = ""
    chapters: list[ChapterMarkdownEntry] = field(default_factory=list)
    chapter_files: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    zip_bytes: bytes = b""
    audit_report: ExportAuditReport = field(default_factory=ExportAuditReport)
    semantic_summary: dict[str, Any] = field(default_factory=dict)

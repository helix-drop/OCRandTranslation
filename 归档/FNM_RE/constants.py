"""FNM_RE 分阶段常量定义。"""

from __future__ import annotations

from typing import Final, Literal, get_args

PageRole = Literal["noise", "front_matter", "body", "note", "other"]
ChapterSource = Literal["visual_toc", "fallback"]
BoundaryState = Literal["ready", "review_required"]
NoteKind = Literal["footnote", "endnote"]
RegionScope = Literal["chapter", "book"]
RegionSource = Literal[
    "heading_scan",
    "footnote_band",
    "continuation_merge",
    "manual_rebind",
    "explorer_toc_match",
    "explorer_signal_match",
    "fallback_nearest_prior",
]
NoteMode = Literal[
    "footnote_primary",
    "chapter_endnote_primary",
    "book_endnote_bound",
    "no_notes",
    "review_required",
]
AnchorKind = Literal["footnote", "endnote", "unknown"]
LinkStatus = Literal["matched", "orphan_note", "orphan_anchor", "ambiguous", "ignored"]
LinkResolver = Literal["rule", "fallback", "repair"]
PipelineState = Literal["idle", "running", "error", "done"]

PAGE_ROLES: Final[tuple[PageRole, ...]] = get_args(PageRole)
CHAPTER_SOURCES: Final[tuple[ChapterSource, ...]] = get_args(ChapterSource)
BOUNDARY_STATES: Final[tuple[BoundaryState, ...]] = get_args(BoundaryState)
NOTE_KINDS: Final[tuple[NoteKind, ...]] = get_args(NoteKind)
REGION_SCOPES: Final[tuple[RegionScope, ...]] = get_args(RegionScope)
REGION_SOURCES: Final[tuple[RegionSource, ...]] = get_args(RegionSource)
NOTE_MODES: Final[tuple[NoteMode, ...]] = get_args(NoteMode)
ANCHOR_KINDS: Final[tuple[AnchorKind, ...]] = get_args(AnchorKind)
LINK_STATUSES: Final[tuple[LinkStatus, ...]] = get_args(LinkStatus)
LINK_RESOLVERS: Final[tuple[LinkResolver, ...]] = get_args(LinkResolver)
PIPELINE_STATES: Final[tuple[PipelineState, ...]] = get_args(PipelineState)


def is_valid_page_role(value: str) -> bool:
    return str(value or "").strip() in PAGE_ROLES


def is_valid_chapter_source(value: str) -> bool:
    return str(value or "").strip() in CHAPTER_SOURCES


def is_valid_boundary_state(value: str) -> bool:
    return str(value or "").strip() in BOUNDARY_STATES


def is_valid_note_kind(value: str) -> bool:
    return str(value or "").strip() in NOTE_KINDS


def is_valid_region_scope(value: str) -> bool:
    return str(value or "").strip() in REGION_SCOPES


def is_valid_region_source(value: str) -> bool:
    return str(value or "").strip() in REGION_SOURCES


def is_valid_note_mode(value: str) -> bool:
    return str(value or "").strip() in NOTE_MODES


def is_valid_anchor_kind(value: str) -> bool:
    return str(value or "").strip() in ANCHOR_KINDS


def is_valid_link_status(value: str) -> bool:
    return str(value or "").strip() in LINK_STATUSES


def is_valid_link_resolver(value: str) -> bool:
    return str(value or "").strip() in LINK_RESOLVERS


def is_valid_pipeline_state(value: str) -> bool:
    return str(value or "").strip() in PIPELINE_STATES

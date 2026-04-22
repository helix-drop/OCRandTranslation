"""FNM_RE 模块化入口。"""

from FNM_RE.modules.book_note_type import build_book_note_profile
from FNM_RE.modules.book_assemble import build_export_bundle
from FNM_RE.modules.chapter_merge import build_chapter_markdown_set
from FNM_RE.modules.chapter_split import build_chapter_layers
from FNM_RE.modules.contracts import GateReport, ModuleResult
from FNM_RE.modules.note_linking import build_note_link_table
from FNM_RE.modules.ref_freeze import build_frozen_units
from FNM_RE.modules.toc_structure import build_toc_structure
from FNM_RE.modules.types import (
    BodyAnchorLayer,
    BodyPageLayer,
    BodySegmentLayer,
    BookNoteProfile,
    BookNoteTypeEvidence,
    ChapterLayer,
    ChapterLayers,
    ChapterMarkdownEntry,
    ChapterMarkdownSet,
    ChapterLinkContract,
    ChapterNoteMode,
    ExportAuditFile,
    ExportAuditReport,
    ExportBundle,
    FrozenRefEntry,
    FrozenUnit,
    FrozenUnits,
    LayerNoteItem,
    LayerNoteRegion,
    NoteLinkLayer,
    NoteLinkTable,
    TocChapter,
    TocNode,
    TocPageRole,
    TocSectionHead,
    TocStructure,
)

__all__ = [
    "GateReport",
    "ModuleResult",
    "TocPageRole",
    "TocNode",
    "TocChapter",
    "TocSectionHead",
    "TocStructure",
    "ChapterNoteMode",
    "BookNoteTypeEvidence",
    "BookNoteProfile",
    "LayerNoteRegion",
    "LayerNoteItem",
    "BodyPageLayer",
    "BodySegmentLayer",
    "ChapterLayer",
    "ChapterLayers",
    "ChapterMarkdownEntry",
    "ChapterMarkdownSet",
    "BodyAnchorLayer",
    "NoteLinkLayer",
    "ChapterLinkContract",
    "NoteLinkTable",
    "FrozenRefEntry",
    "FrozenUnit",
    "FrozenUnits",
    "ExportAuditFile",
    "ExportAuditReport",
    "ExportBundle",
    "build_toc_structure",
    "build_book_note_profile",
    "build_chapter_layers",
    "build_note_link_table",
    "build_frozen_units",
    "build_chapter_markdown_set",
    "build_export_bundle",
]

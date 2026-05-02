"""阶段 1 模块：全书书型与章级注释模式。"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping

from FNM_RE.modules.contracts import GateReport, ModuleResult
from FNM_RE.modules.types import BookNoteProfile, BookNoteTypeEvidence, ChapterNoteMode, TocStructure
from FNM_RE.shared.text import page_markdown_text
from FNM_RE.stages.page_partition import annotate_pages_with_note_scans
from FNM_RE.shared.notes import _safe_int

_NOTES_HEADING_RE = re.compile(r"^\s*(?:#+\s*)?(?:notes?|endnotes?|notes to pages?.*)\s*$", re.IGNORECASE)
_NOTE_DEF_RE = re.compile(r"^\s*(?:\d{1,4}[A-Za-z]?)\s*[\.\)\]]\s+")

def _chapter_by_page(toc_structure: TocStructure) -> dict[int, str]:
    mapped: dict[int, str] = {}
    for chapter in toc_structure.chapters:
        chapter_id = str(chapter.chapter_id or "")
        if not chapter_id:
            continue
        for page_no in chapter.pages:
            if int(page_no) > 0:
                mapped[int(page_no)] = chapter_id
        start_page = int(chapter.start_page or 0)
        end_page = int(chapter.end_page or 0)
        if start_page > 0 and end_page >= start_page:
            for page_no in range(start_page, end_page + 1):
                mapped.setdefault(page_no, chapter_id)
    return mapped

def _nearest_prior_chapter_id(toc_structure: TocStructure, page_no: int) -> str:
    """返回不晚于 page_no 的最近 chapter 的 chapter_id；不存在则空串。

    工单 #6：用于把章节边界之间的 endnote 容器页（如 LEÇON DU 21 FÉVRIER 章末
    NOTES 在 197-202，下一章 LEÇON DU 7 MARS 从 220 起，197-202 落在两章之间）
    绑定到前一章。与 [`note_regions._chapter_id_for_page`](../stages/note_regions.py)
    的兜底语义一致。
    """
    candidates = [
        ch
        for ch in toc_structure.chapters
        if str(ch.chapter_id or "").strip() and int(ch.start_page or 0) <= int(page_no)
    ]
    if not candidates:
        return ""
    candidates.sort(key=lambda ch: (int(ch.start_page or 0), int(ch.end_page or 0)))
    return str(candidates[-1].chapter_id or "")

def _has_notes_heading(markdown: str) -> bool:
    """页首有 ## NOTES / ## Endnotes 标题——尾注强信号。"""
    lines = [line.strip() for line in str(markdown or "").splitlines() if line.strip()]
    return bool(lines and _NOTES_HEADING_RE.match(lines[0]))


def _is_endnote_page(markdown: str) -> bool:
    """页首有 NOTES 标题或 ≥4 条编号定义——后者可能是脚注，不可靠。"""
    lines = [line.strip() for line in str(markdown or "").splitlines() if line.strip()]
    if not lines:
        return False
    if _NOTES_HEADING_RE.match(lines[0]):
        return True
    note_lines = sum(1 for line in lines[:16] if _NOTE_DEF_RE.match(line))
    return note_lines >= 4

def _resolve_book_type(*, has_footnote: bool, has_endnote: bool) -> str:
    if has_footnote and has_endnote:
        return "mixed"
    if has_endnote:
        return "endnote_only"
    if has_footnote:
        return "footnote_only"
    return "no_notes"

def _mode_compatible(book_type: str, mode: str) -> bool:
    if mode == "review_required":
        return True
    if book_type == "mixed":
        return mode in {"footnote_primary", "chapter_endnote_primary", "book_endnote_bound", "no_notes"}
    if book_type == "endnote_only":
        return mode in {"chapter_endnote_primary", "book_endnote_bound", "no_notes"}
    if book_type == "footnote_only":
        return mode in {"footnote_primary", "no_notes"}
    return mode == "no_notes"

def build_book_note_profile(
    toc_structure: TocStructure,
    pages: list[dict],
    *,
    pdf_path: str = "",
    page_text_map: Mapping[int | str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> ModuleResult[BookNoteProfile]:
    del pdf_path, page_text_map
    annotated_pages = annotate_pages_with_note_scans(list(pages or []))
    chapter_by_page = _chapter_by_page(toc_structure)
    chapters = [row for row in toc_structure.chapters if row.role == "chapter"]
    last_chapter_end = max((int(row.end_page or 0) for row in chapters), default=0)
    # 检查 TOC 中是否有 endnotes 条目：若无，则 endnote_collection 页更有
    # 可能是脚注页被 note_detection 误判（纯脚注书如 Germany_Madness）。
    toc_has_endnotes_entry = any(
        str(node.role or "").strip().lower() == "endnotes"
        for node in (toc_structure.toc_tree or [])
    )

    footnote_pages: set[int] = set()
    endnote_pages: set[int] = set()
    chapter_has_footnote: dict[str, set[int]] = {}
    chapter_has_endnote: dict[str, set[int]] = {}
    book_endnote_pages: set[int] = set()

    # 第一遍：确定哪些章有显式 ## NOTES 标题（强信号锚点）或 endnote_collection 页。
    # 同章后续的弱信号尾注页（延续页）应跟随锚点保留。
    # Biopolitics 类型：章末 note 页不一定有 ## NOTES 标题，且可能落在章节间隙中
    # （ch1 end=39, note 页=40-42, ch2 start=43），需 nearest_prior 兜底。
    chapters_with_heading: set[str] = set()
    if not toc_has_endnotes_entry:
        for page in annotated_pages:
            page_no = _safe_int(page.get("bookPage") or 0)
            if page_no <= 0:
                continue
            markdown = page_markdown_text(page)
            chapter_id = chapter_by_page.get(page_no, "") or _nearest_prior_chapter_id(toc_structure, page_no)
            if not chapter_id:
                continue
            if _has_notes_heading(markdown):
                chapters_with_heading.add(chapter_id)
                continue
            note_scan = dict(page.get("_note_scan") or {})
            if str(note_scan.get("page_kind") or "").strip().lower() == "endnote_collection":
                chapters_with_heading.add(chapter_id)

    for page in annotated_pages:
        page_no = _safe_int(page.get("bookPage") or 0)
        if page_no <= 0:
            continue
        markdown = page_markdown_text(page)
        note_scan = dict(page.get("_note_scan") or {})
        page_kind = str(note_scan.get("page_kind") or "").strip().lower()
        has_footnote = bool(str(page.get("footnotes") or "").strip())
        # 尾注信号分级：
        # 强信号：页首有 ## NOTES / ## Endnotes 标题
        # 弱信号：page_kind=endnote_collection 或 ≥4 条编号定义但无标题
        is_heading_endnote = _has_notes_heading(markdown)
        is_weak_endnote = (page_kind == "endnote_collection" or _is_endnote_page(markdown)) and not is_heading_endnote
        has_endnote = is_heading_endnote or is_weak_endnote
        if has_endnote and has_footnote:
            has_endnote = False
        elif is_weak_endnote and not toc_has_endnotes_entry:
            # TOC 无 endnotes 条目时，弱信号需额外守卫。若同章有显式标题页
            # 或 endnote_collection 页（Biopolitics：章末 note 页不一定有 ## NOTES），
            # 弱信号跟随保留。若同章无任何尾注证据（Germany_Madness：纯脚注书的
            # 编号条目被 note_detection 误判为 endnote），弱信号降级丢弃。
            chapter_id = chapter_by_page.get(page_no, "") or _nearest_prior_chapter_id(toc_structure, page_no)
            if chapter_id not in chapters_with_heading:
                has_endnote = False
        chapter_id = chapter_by_page.get(page_no, "")
        # 间隙页（章边界之间）和章内未分配页用 nearest_prior 兜底，
        # 但不包括全书末尾页（> last_chapter_end）——那些属于 book_endnote。
        if not chapter_id and page_no <= last_chapter_end:
            chapter_id = _nearest_prior_chapter_id(toc_structure, page_no)

        if has_footnote:
            footnote_pages.add(page_no)
            if chapter_id:
                chapter_has_footnote.setdefault(chapter_id, set()).add(page_no)
        if has_endnote:
            endnote_pages.add(page_no)
            if chapter_id:
                chapter_has_endnote.setdefault(chapter_id, set()).add(page_no)
            elif page_no > last_chapter_end:
                book_endnote_pages.add(page_no)
            else:
                # 工单 #6：章节边界之间的 endnote 容器页（前章 end < page_no <
                # 下一章 start）按 nearest-prior chapter 兜底绑定，与 phase2
                # `note_regions._chapter_id_for_page` 语义保持一致。
                prior_id = _nearest_prior_chapter_id(toc_structure, page_no)
                if prior_id:
                    chapter_has_endnote.setdefault(prior_id, set()).add(page_no)

    chapter_modes: list[ChapterNoteMode] = []
    for chapter in chapters:
        chapter_id = str(chapter.chapter_id or "")
        chapter_footnote_pages = chapter_has_footnote.get(chapter_id, set())
        chapter_endnote_pages = chapter_has_endnote.get(chapter_id, set())
        # 工单 #6：endnote 容器页（_is_endnote_page 命中 / page_kind=endnote_collection）
        # 是该章 endnote 主导的强信号（NOTES 容器 1 页可含 7-8 条 endnote）；
        # page footnote（手稿星号等）是辅助补充。endnote 优先，避免按"页数比较"
        # 把 endnote 主导章误判为 footnote_primary（旧算法 6 vs 8 误判 footnote）。
        if chapter_endnote_pages:
            note_mode = "chapter_endnote_primary"
        elif chapter_footnote_pages:
            note_mode = "footnote_primary"
        elif book_endnote_pages:
            note_mode = "book_endnote_bound"
        else:
            note_mode = "no_notes"
        chapter_modes.append(
            ChapterNoteMode(
                chapter_id=chapter_id,
                note_mode=note_mode,  # type: ignore[arg-type]
                region_ids=[],
                has_footnote_band=bool(chapter_footnote_pages),
                has_endnote_region=bool(chapter_endnote_pages or book_endnote_pages),
                evidence_page_nos=sorted(set(chapter_footnote_pages) | set(chapter_endnote_pages)),
            )
        )

    chapter_overrides = dict((overrides or {}).get("chapter_modes") or {})
    allow_review_required = {str(item) for item in list((overrides or {}).get("allow_review_required") or [])}
    overrides_used: list[dict[str, Any]] = []
    for row in chapter_modes:
        override = dict(chapter_overrides.get(row.chapter_id) or {})
        force_mode = str(override.get("note_mode") or "").strip()
        if force_mode in {"footnote_primary", "chapter_endnote_primary", "book_endnote_bound", "no_notes", "review_required"}:
            previous = row.note_mode
            row.note_mode = force_mode  # type: ignore[assignment]
            overrides_used.append(
                {
                    "kind": "gate_override",
                    "chapter_id": row.chapter_id,
                    "field": "note_mode",
                    "from": previous,
                    "to": force_mode,
                    "reason": str(override.get("reason") or ""),
                }
            )

    has_footnote = bool(footnote_pages)
    has_endnote = bool(endnote_pages)
    book_type = _resolve_book_type(has_footnote=has_footnote, has_endnote=has_endnote)
    mode_counts = dict(Counter(str(row.note_mode or "") for row in chapter_modes))
    review_required_chapters = [row.chapter_id for row in chapter_modes if row.note_mode == "review_required"]

    no_unapproved_review_required = all(chapter_id in allow_review_required for chapter_id in review_required_chapters)
    chapter_modes_consistent = all(_mode_compatible(book_type, str(row.note_mode or "")) for row in chapter_modes)
    resolved = book_type in {"mixed", "endnote_only", "footnote_only", "no_notes"}

    hard = {
        "book_type.resolved": resolved,
        "book_type.chapter_modes_consistent": chapter_modes_consistent,
        "book_type.no_unapproved_review_required": no_unapproved_review_required,
    }
    soft = {
        "book_type.low_confidence_warn": bool(review_required_chapters),
    }
    reasons: list[str] = []
    if not hard["book_type.resolved"]:
        reasons.append("book_type_unresolved")
    if not hard["book_type.chapter_modes_consistent"]:
        reasons.append("book_type_chapter_modes_inconsistent")
    if not hard["book_type.no_unapproved_review_required"]:
        reasons.append("book_type_review_required_unapproved")

    evidence_payload = {
        "footnote_page_count": len(footnote_pages),
        "endnote_page_count": len(endnote_pages),
        "book_endnote_page_count": len(book_endnote_pages),
        "chapter_mode_counts": mode_counts,
        "review_required_chapters": list(review_required_chapters),
    }
    gate_report = GateReport(
        module="book_type",
        hard=hard,
        soft=soft,
        reasons=reasons,
        evidence=evidence_payload,
        overrides_used=list(overrides_used),
    )
    data = BookNoteProfile(
        book_type=book_type,  # type: ignore[arg-type]
        chapter_modes=chapter_modes,
        evidence=BookNoteTypeEvidence(
            footnote_page_count=len(footnote_pages),
            endnote_page_count=len(endnote_pages),
            chapter_mode_counts=mode_counts,
            chapter_review_required=list(review_required_chapters),
        ),
    )
    diagnostics = {
        "chapter_by_page_count": len(chapter_by_page),
        "allow_review_required": sorted(allow_review_required),
    }
    return ModuleResult(
        data=data,
        gate_report=gate_report,
        evidence=evidence_payload,
        overrides_used=list(overrides_used),
        diagnostics=diagnostics,
    )

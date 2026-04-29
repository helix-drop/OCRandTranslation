"""导出语义合同检查与章节 Markdown 构建。

从 export.py 拆分出的独立模块。
"""

from __future__ import annotations

import re
from typing import Any

from FNM_RE.models import (
    BodyAnchorRecord,
    ExportBundleRecord,
    ExportChapterRecord,
    NoteItemRecord,
    NoteLinkRecord,
    SectionHeadRecord,
    TranslationUnitRecord,
)
from FNM_RE.shared.export_constants import (
    OBSIDIAN_EXPORT_CHAPTERS_PREFIX,
    PENDING_TRANSLATION_TEXT,
    _FRONT_MATTER_TITLE_RE,
    _TOC_RESIDUE_RE,
)
from FNM_RE.stages.export import (
    _build_chapter_filename,
    _build_section_markdown,
    _chapter_page_numbers,
    _diagnostic_machine_text_by_page,
    _infer_book_note_type_from_modes,
    _normalized_paragraph_key,
    _sanitize_obsidian_chapter_title,
    _strip_trailing_image_only_block,
)


def _is_semantic_duplicate_candidate(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    if not normalized:
        return False
    if normalized.startswith("#"):
        return False
    if len(normalized) < 80:
        return False
    words = [token for token in normalized.split(" ") if token]
    if len(words) < 12:
        return False
    return bool(re.search(r"[.!?;:。！？；：]", normalized))


def _looks_like_bibliography_entry(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    if not normalized:
        return False
    if not re.search(r"\b\d{4}\.?\s*$", normalized):
        return False
    return bool(re.search(r":\s*[^:]{6,},\s*\d{4}\.?\s*$", normalized))


def _compute_export_semantic_contract(
    *,
    chapters: list[ExportChapterRecord],
    chapter_files: dict[str, str],
) -> dict[str, bool]:
    front_matter_leak_detected = any(
        bool(_FRONT_MATTER_TITLE_RE.match(str(chapter.title or "").strip()))
        for chapter in chapters
    )
    toc_residue_detected = any(
        bool(_TOC_RESIDUE_RE.search(str(content or "")))
        for content in chapter_files.values()
    )
    mid_paragraph_heading_detected = False
    duplicate_paragraph_detected = False

    for content in chapter_files.values():
        lines = str(content or "").splitlines()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("### "):
                continue
            prev = lines[idx - 1].strip() if idx > 0 else ""
            if prev and not prev.startswith("#"):
                mid_paragraph_heading_detected = True
                break
        if mid_paragraph_heading_detected:
            break

    for content in chapter_files.values():
        seen: set[str] = set()
        for paragraph in re.split(r"\n\s*\n+", str(content or "")):
            if not _is_semantic_duplicate_candidate(paragraph):
                continue
            if _looks_like_bibliography_entry(paragraph):
                continue
            key = _normalized_paragraph_key(paragraph)
            if len(key) < 60:
                continue
            if key in seen:
                duplicate_paragraph_detected = True
                break
            seen.add(key)
        if duplicate_paragraph_detected:
            break

    export_semantic_contract_ok = not any(
        (
            front_matter_leak_detected,
            toc_residue_detected,
            mid_paragraph_heading_detected,
            duplicate_paragraph_detected,
        )
    )
    return {
        "export_semantic_contract_ok": bool(export_semantic_contract_ok),
        "front_matter_leak_detected": bool(front_matter_leak_detected),
        "toc_residue_detected": bool(toc_residue_detected),
        "mid_paragraph_heading_detected": bool(mid_paragraph_heading_detected),
        "duplicate_paragraph_detected": bool(duplicate_paragraph_detected),
    }


def _build_export_chapters(
    phase5: Phase5Structure,
    *,
    include_diagnostic_entries: bool,
) -> tuple[list[ExportChapterRecord], dict[str, Any]]:
    chapters = sorted(
        list(phase5.chapters or []),
        key=lambda row: (int(row.start_page or 0), str(row.chapter_id or "")),
    )
    body_units = [unit for unit in phase5.translation_units if str(unit.kind or "") == "body"]
    note_units = [unit for unit in phase5.translation_units if str(unit.kind or "") in {"footnote", "endnote"}]
    matched_links = [
        link
        for link in phase5.effective_note_links
        if str(link.status or "") == "matched"
        and str(link.note_item_id or "").strip()
        and str(link.anchor_id or "").strip()
    ]
    note_items_by_id = {
        str(item.note_item_id or "").strip(): item
        for item in phase5.note_items
        if str(item.note_item_id or "").strip()
    }
    body_anchors_by_id = {
        str(anchor.anchor_id or "").strip(): anchor
        for anchor in phase5.body_anchors
        if str(anchor.anchor_id or "").strip()
    }
    diagnostic_machine_by_page = _diagnostic_machine_text_by_page(phase5)
    chapter_note_mode_by_id = {
        str(row.chapter_id or ""): str(row.note_mode or "no_notes")
        for row in list(phase5.chapter_note_modes or [])
        if str(row.chapter_id or "").strip()
    }
    summary_book_type = str(
        dict(getattr(getattr(phase5, "summary", None), "chapter_note_mode_summary", {}) or {}).get("book_type") or ""
    ).strip()
    book_type = (
        summary_book_type
        if summary_book_type in {"mixed", "endnote_only", "footnote_only", "no_notes"}
        else _infer_book_note_type_from_modes(list(phase5.chapter_note_modes or []))
    )
    used_filenames: set[str] = set()

    chapter_records: list[ExportChapterRecord] = []
    contract_items: list[dict[str, Any]] = []
    inline_footnote_paragraph_attach_count = 0
    inline_footnote_page_fallback_count = 0
    chapter_end_footnote_definition_count = 0
    for order, chapter in enumerate(chapters, start=1):
        chapter_id = str(chapter.chapter_id or "").strip()
        if not chapter_id:
            continue
        title = str(chapter.title or chapter_id)
        content, contract_summary = _build_section_markdown(
            chapter,
            section_heads=list(phase5.section_heads or []),
            body_units=body_units,
            note_units=note_units,
            matched_links=matched_links,
            note_items_by_id=note_items_by_id,
            body_anchors_by_id=body_anchors_by_id,
            include_diagnostic_entries=bool(include_diagnostic_entries),
            diagnostic_machine_by_page=diagnostic_machine_by_page,
            book_type=book_type,
            chapter_note_mode=str(chapter_note_mode_by_id.get(chapter_id) or "no_notes"),
        )
        inline_footnote_paragraph_attach_count += int(contract_summary.get("inline_footnote_paragraph_attach_count") or 0)
        inline_footnote_page_fallback_count += int(contract_summary.get("inline_footnote_page_fallback_count") or 0)
        chapter_end_footnote_definition_count += int(contract_summary.get("chapter_end_footnote_definition_count") or 0)
        filename = _build_chapter_filename(order, title, used_filenames=used_filenames)
        chapter_records.append(
            ExportChapterRecord(
                order=order,
                section_id=chapter_id,
                title=title,
                path=f"{OBSIDIAN_EXPORT_CHAPTERS_PREFIX}{filename}",
                content=content,
                start_page=int(chapter.start_page or 0),
                end_page=int(chapter.end_page or int(chapter.start_page or 0)),
                pages=_chapter_page_numbers(chapter),
            )
        )
        contract_items.append(
            {
                "section_id": chapter_id,
                "title": title,
                **dict(contract_summary or {}),
            }
        )
    summary = {
        "chapter_ref_contract_summary": {
            "chapter_count": len(contract_items),
            "chapter_local_contract_ok_count": sum(
                1
                for item in contract_items
                if int(item.get("missing_definition_count") or 0) == 0
                and int(item.get("orphan_definition_count") or 0) == 0
            ),
            "items": contract_items,
        },
        "inline_footnote_paragraph_attach_count": int(inline_footnote_paragraph_attach_count),
        "inline_footnote_page_fallback_count": int(inline_footnote_page_fallback_count),
        "chapter_end_footnote_definition_count": int(chapter_end_footnote_definition_count),
    }
    return chapter_records, summary


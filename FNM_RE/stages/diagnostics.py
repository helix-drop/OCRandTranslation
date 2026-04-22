"""FNM_RE 第五阶段：diagnostic 投影。"""

from __future__ import annotations

from typing import Any

from FNM_RE.models import (
    ChapterRecord,
    DiagnosticEntryRecord,
    DiagnosticNoteRecord,
    DiagnosticPageRecord,
    NoteRegionRecord,
    Phase4Structure,
    TranslationUnitRecord,
    UnitPageSegmentRecord,
    UnitParagraphRecord,
)
from FNM_RE.shared.refs import extract_note_refs, replace_frozen_refs

_ERROR_TRANSLATION_STATUSES = {"error", "retry_pending", "retrying", "manual_required"}
_DONE_UNIT_STATUSES = {"done", "done_manual"}


def _raw_print_page_label(page_no: int, pages: list[dict]) -> str:
    for page in pages or []:
        if int(page.get("bookPage") or 0) != int(page_no):
            continue
        label = str(page.get("printPageLabel") or "").strip()
        if label:
            return label
        print_page = page.get("printPage")
        try:
            parsed = int(print_page)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return str(parsed)
        break
    return str(page_no)


def _display_pages_label(page_no: int, pages: list[dict]) -> str:
    raw = _raw_print_page_label(page_no, pages)
    if not raw:
        return ""
    return raw if raw.startswith("原书 p.") else f"原书 p.{raw}"


def _segment_from_any(payload: UnitPageSegmentRecord | dict[str, Any]) -> UnitPageSegmentRecord:
    if isinstance(payload, UnitPageSegmentRecord):
        return payload
    paragraphs: list[UnitParagraphRecord] = []
    for row in list((payload or {}).get("paragraphs") or []):
        if isinstance(row, UnitParagraphRecord):
            paragraphs.append(row)
            continue
        paragraphs.append(
            UnitParagraphRecord(
                order=int((row or {}).get("order", len(paragraphs) + 1) or len(paragraphs) + 1),
                kind=str((row or {}).get("kind") or ""),
                heading_level=int((row or {}).get("heading_level", 0) or 0),
                source_text=str((row or {}).get("source_text") or ""),
                display_text=str((row or {}).get("display_text") or (row or {}).get("source_text") or ""),
                cross_page=(row or {}).get("cross_page"),
                consumed_by_prev=bool((row or {}).get("consumed_by_prev")),
                section_path=list((row or {}).get("section_path") or []),
                print_page_label=str((row or {}).get("print_page_label") or ""),
                translated_text=str((row or {}).get("translated_text") or ""),
                translation_status=str((row or {}).get("translation_status") or "pending"),
                attempt_count=max(0, int((row or {}).get("attempt_count", 0) or 0)),
                last_error=str((row or {}).get("last_error") or ""),
                manual_resolved=bool((row or {}).get("manual_resolved")),
            )
        )
    return UnitPageSegmentRecord(
        page_no=int((payload or {}).get("page_no") or 0),
        paragraph_count=int((payload or {}).get("paragraph_count") or 0),
        source_text=str((payload or {}).get("source_text") or ""),
        display_text=str((payload or {}).get("display_text") or (payload or {}).get("source_text") or ""),
        paragraphs=paragraphs,
    )


def _entry_status(paragraph: UnitParagraphRecord) -> str:
    status = str(paragraph.translation_status or "").strip()
    if status in _ERROR_TRANSLATION_STATUSES:
        return "error"
    if str(paragraph.translated_text or "").strip():
        return "done"
    return "pending"


def _build_diagnostic_entry(
    *,
    page_no: int,
    paragraph: UnitParagraphRecord,
    pages: list[dict],
) -> DiagnosticEntryRecord:
    source_text = str(paragraph.display_text or paragraph.source_text or "").strip()
    translated_text = str(paragraph.translated_text or "").strip()
    translation_status = str(paragraph.translation_status or "").strip() or ("done" if translated_text else "pending")
    entry_text = replace_frozen_refs(translated_text or source_text)
    refs: list[dict[str, str]] = []
    seen_refs: set[tuple[str, str]] = set()
    for candidate in (
        paragraph.source_text,
        paragraph.display_text,
        paragraph.translated_text,
        source_text,
        translated_text,
    ):
        for ref in extract_note_refs(str(candidate or "").strip()):
            key = (str(ref.get("kind") or ""), str(ref.get("note_id") or ""))
            if key in seen_refs:
                continue
            seen_refs.add(key)
            refs.append({"kind": key[0], "note_id": key[1]})
    return DiagnosticEntryRecord(
        original=replace_frozen_refs(source_text),
        translation=entry_text,
        footnotes="",
        footnotes_translation="",
        heading_level=int(paragraph.heading_level or 0),
        pages=_display_pages_label(page_no, pages),
        _startBP=int(page_no),
        _endBP=int(page_no),
        _printPageLabel=_raw_print_page_label(page_no, pages),
        _status=_entry_status(paragraph),
        _error=str(paragraph.last_error or ""),
        _translation_source="manual"
        if bool(paragraph.manual_resolved)
        else ("model" if translated_text else "source"),
        _machine_translation=entry_text if translated_text else "",
        _manual_translation=entry_text if bool(paragraph.manual_resolved) else "",
        _cross_page=paragraph.cross_page,
        _section_path=list(paragraph.section_path or []),
        _fnm_refs=refs,
        _note_kind="",
        _note_marker="",
        _note_number=None,
        _note_section_title="",
        _note_confidence=0.0,
        _translation_status=translation_status,
        _attempt_count=max(0, int(paragraph.attempt_count or 0)),
        _manual_resolved=bool(paragraph.manual_resolved),
    )


def _note_unit_by_note_id(translation_units: list[TranslationUnitRecord]) -> dict[str, TranslationUnitRecord]:
    payload: dict[str, TranslationUnitRecord] = {}
    for unit in translation_units:
        if str(unit.kind or "") not in {"footnote", "endnote"}:
            continue
        note_id = str(unit.note_id or "").strip()
        if note_id:
            payload[note_id] = unit
    return payload


def _chapter_meta_by_id(phase4: Phase4Structure) -> dict[str, ChapterRecord]:
    return {
        str(chapter.chapter_id or "").strip(): chapter
        for chapter in phase4.chapters
        if str(chapter.chapter_id or "").strip()
    }


def _note_region_by_id(phase4: Phase4Structure) -> dict[str, NoteRegionRecord]:
    return {
        str(region.region_id or "").strip(): region
        for region in phase4.note_regions
        if str(region.region_id or "").strip()
    }


def build_diagnostic_projection(
    phase4: Phase4Structure,
    translation_units: list[TranslationUnitRecord],
    *,
    pages: list[dict],
    only_pages: list[int] | None = None,
) -> tuple[list[DiagnosticPageRecord], list[DiagnosticNoteRecord], dict[str, Any]]:
    visible_page_filter = {int(page_no) for page_no in (only_pages or []) if int(page_no) > 0}
    page_rows: dict[int, DiagnosticPageRecord] = {}

    for unit in translation_units:
        if str(unit.kind or "") != "body":
            continue
        source_meta = {
            "section_id": unit.section_id,
            "section_title": unit.section_title,
            "section_start_page": unit.section_start_page,
            "section_end_page": unit.section_end_page,
            "unit_id": unit.unit_id,
        }
        for raw_segment in unit.page_segments:
            segment = _segment_from_any(raw_segment)
            page_no = int(segment.page_no or 0)
            if page_no <= 0:
                continue
            if visible_page_filter and page_no not in visible_page_filter:
                continue
            page_row = page_rows.setdefault(
                page_no,
                DiagnosticPageRecord(
                    _pageBP=page_no,
                    _status="pending",
                    pages=_display_pages_label(page_no, pages),
                    _page_entries=[],
                    _fnm_source=dict(source_meta),
                ),
            )
            for paragraph in segment.paragraphs:
                if paragraph.consumed_by_prev:
                    continue
                page_row._page_entries.append(
                    _build_diagnostic_entry(
                        page_no=page_no,
                        paragraph=paragraph,
                        pages=pages,
                    )
                )
            if any(entry._status == "error" for entry in page_row._page_entries):
                page_row._status = "error"
            elif any(entry._status == "done" for entry in page_row._page_entries):
                page_row._status = "done"
            else:
                page_row._status = "pending"

    diagnostic_pages = [page_rows[page_no] for page_no in sorted(page_rows)]

    chapter_by_id = _chapter_meta_by_id(phase4)
    note_region_by_id = _note_region_by_id(phase4)
    note_units = _note_unit_by_note_id(translation_units)
    diagnostic_notes: list[DiagnosticNoteRecord] = []
    for item in phase4.note_items:
        note_id = str(item.note_item_id or "").strip()
        if not note_id:
            continue
        chapter_id = str(item.chapter_id or "").strip()
        chapter = chapter_by_id.get(chapter_id)
        region = note_region_by_id.get(str(item.region_id or "").strip())
        note_kind = str(region.note_kind if region else "")
        unit = note_units.get(note_id)
        if not note_kind:
            unit_kind = str(unit.kind if unit else "").strip().lower()
            if unit_kind in {"footnote", "endnote"}:
                note_kind = unit_kind
            else:
                note_kind = "endnote" if str(note_id).lower().startswith("en-") else "footnote"
        start_page = int(item.page_no or (unit.page_start if unit else 0) or 0)
        diagnostic_notes.append(
            DiagnosticNoteRecord(
                note_id=note_id,
                section_id=chapter_id,
                section_title=str((chapter.title if chapter else chapter_id) or chapter_id),
                section_start_page=int((chapter.start_page if chapter else 0) or 0),
                section_end_page=int((chapter.end_page if chapter else 0) or 0),
                kind=note_kind,
                original_marker=str(item.marker or ""),
                start_page=start_page,
                pages=[start_page] if start_page > 0 else [],
                source_text=str(item.text or (unit.source_text if unit else "") or ""),
                translated_text=str((unit.translated_text if unit else "") or ""),
                translate_status=str((unit.status if unit else "pending") or "pending"),
                region_id=str(item.region_id or ""),
            )
        )
    diagnostic_notes.sort(
        key=lambda row: (
            int(row.section_start_page or 0),
            int(row.start_page or 0),
            str(row.kind or ""),
            str(row.note_id or ""),
        )
    )

    page_entry_count = sum(len(page._page_entries) for page in diagnostic_pages)
    translated_page_count = sum(
        1
        for page in diagnostic_pages
        if any(entry._translation_source != "source" for entry in page._page_entries)
    )
    diagnostic_summary = {
        "diagnostic_page_summary": {
            "page_count": len(diagnostic_pages),
            "entry_count": page_entry_count,
            "error_page_count": sum(1 for page in diagnostic_pages if page._status == "error"),
            "translated_page_count": translated_page_count,
        },
        "diagnostic_note_summary": {
            "note_count": len(diagnostic_notes),
            "translated_count": sum(
                1
                for note in diagnostic_notes
                if str(note.translate_status or "") in _DONE_UNIT_STATUSES
                or bool(str(note.translated_text or "").strip())
            ),
            "pending_count": sum(
                1
                for note in diagnostic_notes
                if str(note.translate_status or "") not in _DONE_UNIT_STATUSES
                and str(note.translate_status or "") not in _ERROR_TRANSLATION_STATUSES
                and not bool(str(note.translated_text or "").strip())
            ),
            "error_count": sum(
                1
                for note in diagnostic_notes
                if str(note.translate_status or "") in _ERROR_TRANSLATION_STATUSES
            ),
        },
    }
    return diagnostic_pages, diagnostic_notes, diagnostic_summary

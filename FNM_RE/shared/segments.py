"""FNM_RE 段落与分页分段工具。"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from document.text_utils import ensure_str, extract_heading_level

from FNM_RE.models import UnitPageSegmentRecord, UnitParagraphRecord


def split_fnm_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", str(text or "")) if part.strip()]


def normalize_heading_text(text: str) -> tuple[int, str]:
    heading_level, clean = extract_heading_level(ensure_str(text).strip())
    return int(heading_level or 0), ensure_str(clean or text).strip()


def build_fallback_unit_paragraphs(
    *,
    source_text: str,
    display_text: str,
    translated_text: str = "",
    page_no: int = 0,
    section_title: str = "",
    print_page_label: str = "",
) -> list[UnitParagraphRecord]:
    source_parts = split_fnm_paragraphs(source_text)
    display_parts = split_fnm_paragraphs(display_text)
    translated_parts = split_fnm_paragraphs(translated_text)
    if display_parts and len(display_parts) != len(source_parts):
        display_parts = source_parts
    title_stack: list[str] = [section_title] if section_title else []
    resolved_label = ensure_str(print_page_label).strip() or (str(page_no) if int(page_no or 0) > 0 else "")
    paragraphs: list[UnitParagraphRecord] = []
    for idx, source_part in enumerate(source_parts, start=1):
        source_candidate = ensure_str(source_part).strip()
        display_candidate = ensure_str(display_parts[idx - 1] if idx - 1 < len(display_parts) else source_candidate).strip()
        heading_level, clean_display = normalize_heading_text(display_candidate)
        source_heading_level, clean_source = normalize_heading_text(source_candidate)
        if heading_level <= 0 and source_heading_level > 0:
            heading_level = source_heading_level
            clean_display = clean_source
        source_clean = clean_source if source_heading_level > 0 else source_candidate
        display_clean = clean_display if heading_level > 0 else display_candidate
        if heading_level > 0:
            active_titles = title_stack[1:] if title_stack and title_stack[0] == section_title else list(title_stack)
            while len(active_titles) >= heading_level:
                active_titles.pop()
            active_titles.append(display_clean)
            title_stack = ([section_title] if section_title else []) + active_titles
            section_path = list(title_stack)
            kind = "heading"
        else:
            section_path = list(title_stack)
            kind = "body"
        translated = ensure_str(translated_parts[idx - 1] if idx - 1 < len(translated_parts) else "").strip()
        paragraphs.append(
            UnitParagraphRecord(
                order=idx,
                kind=kind,
                heading_level=int(heading_level or 0),
                source_text=source_clean,
                display_text=display_clean or source_clean,
                cross_page=None,
                consumed_by_prev=False,
                section_path=section_path,
                print_page_label=resolved_label,
                translated_text=translated,
                translation_status="done" if translated else "pending",
                attempt_count=0,
                last_error="",
                manual_resolved=False,
            )
        )
    return paragraphs


def _normalize_unit_paragraph(
    paragraph: UnitParagraphRecord | dict[str, Any],
    *,
    order: int,
    section_title: str = "",
    print_page_label: str = "",
) -> UnitParagraphRecord:
    if isinstance(paragraph, UnitParagraphRecord):
        source = paragraph
    else:
        source = UnitParagraphRecord(
            order=int((paragraph or {}).get("order", order) or order),
            kind=ensure_str((paragraph or {}).get("kind", "")).strip()
            or ("heading" if int((paragraph or {}).get("heading_level", 0) or 0) > 0 else "body"),
            heading_level=int((paragraph or {}).get("heading_level", 0) or 0),
            source_text=ensure_str((paragraph or {}).get("source_text", "")).strip(),
            display_text=ensure_str((paragraph or {}).get("display_text", "")).strip()
            or ensure_str((paragraph or {}).get("source_text", "")).strip(),
            cross_page=(paragraph or {}).get("cross_page"),
            consumed_by_prev=bool((paragraph or {}).get("consumed_by_prev")),
            section_path=list((paragraph or {}).get("section_path") or ([section_title] if section_title else [])),
            print_page_label=ensure_str((paragraph or {}).get("print_page_label", "")).strip(),
            translated_text=ensure_str((paragraph or {}).get("translated_text", "")).strip(),
            translation_status=ensure_str((paragraph or {}).get("translation_status", "")).strip() or "pending",
            attempt_count=max(0, int((paragraph or {}).get("attempt_count", 0) or 0)),
            last_error=ensure_str((paragraph or {}).get("last_error", "")).strip(),
            manual_resolved=bool((paragraph or {}).get("manual_resolved")),
        )
    resolved_label = ensure_str(print_page_label).strip() or source.print_page_label
    if resolved_label != source.print_page_label:
        source = UnitParagraphRecord(
            order=source.order,
            kind=source.kind,
            heading_level=source.heading_level,
            source_text=source.source_text,
            display_text=source.display_text,
            cross_page=source.cross_page,
            consumed_by_prev=source.consumed_by_prev,
            section_path=list(source.section_path),
            print_page_label=resolved_label,
            translated_text=source.translated_text,
            translation_status=source.translation_status or "pending",
            attempt_count=max(0, int(source.attempt_count or 0)),
            last_error=source.last_error,
            manual_resolved=bool(source.manual_resolved),
        )
    return source


def normalize_unit_page_segment(
    segment: UnitPageSegmentRecord | dict[str, Any],
    *,
    section_title: str = "",
    print_page_label: str = "",
) -> tuple[UnitPageSegmentRecord, bool]:
    payload = asdict(segment) if isinstance(segment, UnitPageSegmentRecord) else dict(segment or {})
    page_no = int(payload.get("page_no") or 0)
    existing_paragraphs = payload.get("paragraphs")
    if isinstance(existing_paragraphs, list) and existing_paragraphs:
        paragraphs = [
            _normalize_unit_paragraph(
                paragraph,
                order=idx,
                section_title=section_title,
                print_page_label=print_page_label,
            )
            for idx, paragraph in enumerate(existing_paragraphs, start=1)
        ]
    else:
        paragraphs = build_fallback_unit_paragraphs(
            source_text=ensure_str(payload.get("source_text", "")).strip(),
            display_text=ensure_str(payload.get("display_text", "")).strip()
            or ensure_str(payload.get("source_text", "")).strip(),
            translated_text=ensure_str(payload.get("translated_text", "")).strip(),
            page_no=page_no,
            section_title=section_title,
            print_page_label=print_page_label,
        )

    visible_paragraphs = [paragraph for paragraph in paragraphs if not paragraph.consumed_by_prev]
    source_text = "\n\n".join(
        paragraph.source_text.strip()
        for paragraph in visible_paragraphs
        if paragraph.source_text.strip()
    ).strip()
    display_text = "\n\n".join(
        paragraph.display_text.strip()
        for paragraph in visible_paragraphs
        if paragraph.display_text.strip()
    ).strip()
    normalized = UnitPageSegmentRecord(
        page_no=page_no,
        paragraph_count=len(visible_paragraphs),
        source_text=source_text or ensure_str(payload.get("source_text", "")).strip(),
        display_text=display_text
        or ensure_str(payload.get("display_text", "")).strip()
        or source_text
        or ensure_str(payload.get("source_text", "")).strip(),
        paragraphs=paragraphs,
    )
    changed = (
        int(payload.get("paragraph_count", 0) or 0) != normalized.paragraph_count
        or ensure_str(payload.get("source_text", "")).strip() != normalized.source_text
        or ensure_str(payload.get("display_text", "")).strip() != normalized.display_text
        or [asdict(paragraph) for paragraph in paragraphs] != [
            asdict(paragraph) if isinstance(paragraph, UnitParagraphRecord) else dict(paragraph or {})
            for paragraph in (existing_paragraphs or [])
        ]
    )
    return normalized, changed


def segment_paragraphs(
    segment: dict,
    *,
    section_title: str = "",
    print_page_label: str = "",
) -> list[dict]:
    """兼容旧调用方：返回 dict 形态的 paragraph 列表。"""
    normalized, _changed = normalize_unit_page_segment(
        dict(segment or {}),
        section_title=section_title,
        print_page_label=print_page_label,
    )
    return [asdict(paragraph) for paragraph in list(normalized.paragraphs or [])]


def normalize_fnm_segment(
    segment: dict,
    *,
    section_title: str = "",
    print_page_label: str = "",
) -> tuple[dict, bool]:
    """兼容旧调用方：返回 dict 形态的 normalized segment。"""
    normalized, changed = normalize_unit_page_segment(
        dict(segment or {}),
        section_title=section_title,
        print_page_label=print_page_label,
    )
    return asdict(normalized), bool(changed)

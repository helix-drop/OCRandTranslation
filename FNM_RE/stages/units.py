"""FNM_RE 第五阶段：translation units 规划。"""

from __future__ import annotations

import re
from typing import Any

from document.text_processing import parse_page_markdown

from FNM_RE.models import (
    BodyAnchorRecord,
    ChapterRecord,
    NoteItemRecord,
    NoteRegionRecord,
    Phase4Structure,
    TranslationUnitRecord,
    UnitPageSegmentRecord,
    UnitParagraphRecord,
)
from FNM_RE.shared.refs import frozen_note_ref, replace_frozen_refs
from FNM_RE.shared.segments import build_fallback_unit_paragraphs
from FNM_RE.shared.text import page_markdown_text

_NOTE_HEADING_RE = re.compile(r"(?im)^\s{0,3}(?:##\s*)?(NOTES|ENDNOTES)\s*$")
_MARKDOWN_HEADING_LINE_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")
_MARKDOWN_NOTE_DEF_START_RE = re.compile(
    r"^\s*(?:"
    r"\$\s*\^\{\s*\d{1,4}[A-Za-z]?\s*\}\s*\$"
    r"|<sup>\s*\d{1,4}[A-Za-z]?\s*</sup>"
    r"|[⁰¹²³⁴⁵⁶⁷⁸⁹]+"
    r"|\d{1,4}[A-Za-z]?\s*[\.\)\]]"
    r")\s+",
    re.IGNORECASE,
)
_GAP_PAGE_NOISE_LINE_RE = re.compile(
    r"^\s*(?:<div\b.*|</div>\s*|<img\b.*|!\[.*\]\(.*\)\s*|fig\.\s*\d+.*)$",
    re.IGNORECASE,
)
_MARKDOWN_TAIL_LINE_LIMIT = 40


def _normalize_title_key(text: str) -> str:
    lowered = str(text or "").strip().lower()
    normalized = re.sub(r"^\s{0,3}#{1,6}\s*", "", lowered).strip()
    normalized = re.sub(r"^(?:\d+|[ivxlcm]+)[\.\)]\s*", "", normalized).strip()
    normalized = re.sub(r"[^0-9a-zà-ÿ]+", "", normalized)
    return normalized


def _extract_note_heading_split(text: str) -> tuple[str, str] | None:
    raw = str(text or "")
    if not raw:
        return None
    matched = _NOTE_HEADING_RE.search(raw)
    if not matched:
        return None
    body_text = raw[:matched.start()].strip()
    note_text = raw[matched.end():].strip()
    return body_text, note_text


def _split_page_text_by_chapter_heading(text: str, title: str) -> tuple[str, str]:
    raw = str(text or "")
    if not raw.strip():
        return "", ""
    title_key = _normalize_title_key(title)
    if not title_key:
        return "", raw.strip()
    lines = raw.splitlines()
    for index, raw_line in enumerate(lines):
        stripped = str(raw_line or "").strip()
        if not stripped:
            continue
        heading_text = stripped
        matched = _MARKDOWN_HEADING_LINE_RE.match(stripped)
        if matched:
            heading_text = str(matched.group(1) or "").strip()
        if _normalize_title_key(heading_text) != title_key:
            continue
        before = "\n".join(lines[:index]).strip()
        after = "\n".join(lines[index:]).strip()
        return before, after
    return "", raw.strip()


def _split_page_text_at_first_heading(text: str) -> tuple[str, str]:
    raw = str(text or "")
    if not raw.strip():
        return "", ""
    lines = raw.splitlines()
    for index, raw_line in enumerate(lines):
        if not _MARKDOWN_HEADING_LINE_RE.match(str(raw_line or "").strip()):
            continue
        before = "\n".join(lines[:index]).strip()
        after = "\n".join(lines[index:]).strip()
        return before, after
    return raw.strip(), ""


def _trim_trailing_markdown_note_block(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    lines = raw.splitlines()
    tail_lines = lines[-_MARKDOWN_TAIL_LINE_LIMIT:]
    first_note_idx: int | None = None
    for index, raw_line in enumerate(tail_lines):
        stripped = str(raw_line or "").strip()
        if not stripped:
            continue
        if _MARKDOWN_NOTE_DEF_START_RE.match(stripped):
            first_note_idx = index
            break
    if first_note_idx is None:
        return raw
    keep_count = len(lines) - len(tail_lines) + first_note_idx
    return "\n".join(lines[:keep_count]).strip()


def _sanitize_gap_page_prefix(text: str) -> str:
    kept_lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        stripped = str(raw_line or "").strip()
        if stripped and _GAP_PAGE_NOISE_LINE_RE.match(stripped):
            continue
        kept_lines.append(raw_line)
    return "\n".join(kept_lines).strip()


def _synthetic_markdown_pages(pages_by_no: dict[int, str]) -> list[dict]:
    synthetic_pages: list[dict] = []
    for page_no in sorted(int(page) for page in pages_by_no):
        synthetic_pages.append(
            {
                "bookPage": int(page_no),
                "fileIdx": max(int(page_no) - 1, 0),
                "markdown": str(pages_by_no.get(int(page_no), "") or "").strip(),
                "footnotes": "",
                "textSource": "fnm_re",
                "printPageLabel": str(page_no),
            }
        )
    return synthetic_pages


def _segment_paragraphs_from_body_pages(section: dict) -> list[UnitPageSegmentRecord]:
    source_by_page = {
        int(page["page_no"]): str(page.get("text", "") or "").strip()
        for page in section.get("frozen_body_pages") or []
        if page.get("page_no") is not None
    }
    display_by_page = {
        int(page["page_no"]): str(page.get("text", "") or "").strip()
        for page in section.get("obsidian_body_pages") or []
        if page.get("page_no") is not None
    }
    if not source_by_page:
        return []

    all_page_nos = sorted(source_by_page.keys())
    source_pages = _synthetic_markdown_pages(source_by_page)
    display_pages = _synthetic_markdown_pages({
        int(page_no): display_by_page.get(int(page_no), source_by_page.get(int(page_no), ""))
        for page_no in all_page_nos
    })

    section_title = str(section.get("title", "") or "").strip()
    title_stack: list[str] = [section_title] if section_title else []
    page_segments: list[UnitPageSegmentRecord] = []
    for page_no in all_page_nos:
        source_paras = parse_page_markdown(source_pages, int(page_no))
        display_paras = parse_page_markdown(display_pages, int(page_no))
        raw_source_parts = [part.strip() for part in str(source_by_page.get(int(page_no), "")).split("\n\n") if part.strip()]
        if not source_paras and not display_paras:
            fallback_paragraphs = build_fallback_unit_paragraphs(
                source_text=source_by_page.get(int(page_no), ""),
                display_text=display_by_page.get(int(page_no), source_by_page.get(int(page_no), "")),
                page_no=int(page_no),
                section_title=section_title,
                print_page_label=str(page_no),
            )
            visible_fallback = [paragraph for paragraph in fallback_paragraphs if not paragraph.consumed_by_prev]
            if visible_fallback:
                page_segments.append(
                    UnitPageSegmentRecord(
                        page_no=int(page_no),
                        paragraph_count=len(visible_fallback),
                        source_text="\n\n".join(
                            paragraph.source_text.strip()
                            for paragraph in visible_fallback
                            if paragraph.source_text.strip()
                        ).strip(),
                        display_text="\n\n".join(
                            paragraph.display_text.strip()
                            for paragraph in visible_fallback
                            if paragraph.display_text.strip()
                        ).strip(),
                        paragraphs=fallback_paragraphs,
                    )
                )
            continue

        paragraph_total = max(len(source_paras), len(display_paras))
        normalized_paragraphs: list[UnitParagraphRecord] = []
        for index in range(paragraph_total):
            source_para = source_paras[index] if index < len(source_paras) else {}
            display_para = display_paras[index] if index < len(display_paras) else source_para
            aligned_source_text = ""
            if paragraph_total == 1 and len(raw_source_parts) > 1:
                aligned_source_text = "\n\n".join(
                    str(part or "").strip()
                    for part in raw_source_parts
                    if str(part or "").strip()
                ).strip()
            elif (
                len(display_paras) == paragraph_total
                and len(source_paras) != paragraph_total
                and len(raw_source_parts) == paragraph_total
                and index < len(raw_source_parts)
            ):
                aligned_source_text = str(raw_source_parts[index] or "").strip()
            source_text = aligned_source_text or str(source_para.get("text") or display_para.get("text") or "").strip()
            display_text = str(display_para.get("text") or source_text).strip()
            if not source_text and not display_text:
                continue
            heading_level = int(display_para.get("heading_level", source_para.get("heading_level", 0)) or 0)
            kind = "heading" if heading_level > 0 else "body"
            if heading_level > 0:
                active_titles = title_stack[1:] if title_stack and title_stack[0] == section_title else list(title_stack)
                while len(active_titles) >= heading_level:
                    active_titles.pop()
                active_titles.append(display_text or source_text)
                title_stack = ([section_title] if section_title else []) + active_titles
                section_path = list(title_stack)
            else:
                section_path = list(title_stack)
            normalized_paragraphs.append(
                UnitParagraphRecord(
                    order=len(normalized_paragraphs) + 1,
                    kind=kind,
                    heading_level=heading_level,
                    source_text=source_text,
                    display_text=display_text or source_text,
                    cross_page=display_para.get("cross_page", source_para.get("cross_page")),
                    consumed_by_prev=bool(
                        display_para.get("consumed_by_prev") or source_para.get("consumed_by_prev")
                    ),
                    section_path=section_path,
                    print_page_label=str(page_no),
                    translated_text="",
                    translation_status="pending",
                    attempt_count=0,
                    last_error="",
                    manual_resolved=False,
                )
            )
        if not normalized_paragraphs:
            continue
        visible_paragraphs = [paragraph for paragraph in normalized_paragraphs if not paragraph.consumed_by_prev]
        page_segments.append(
            UnitPageSegmentRecord(
                page_no=int(page_no),
                paragraph_count=len(visible_paragraphs),
                source_text="\n\n".join(
                    paragraph.source_text.strip()
                    for paragraph in visible_paragraphs
                    if paragraph.source_text.strip()
                ).strip(),
                display_text="\n\n".join(
                    paragraph.display_text.strip()
                    for paragraph in visible_paragraphs
                    if paragraph.display_text.strip()
                ).strip(),
                paragraphs=normalized_paragraphs,
            )
        )
    return page_segments


def _chunk_body_page_segments(
    page_segments: list[UnitPageSegmentRecord],
    *,
    max_body_chars: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current_parts: list[str] = []
    current_start: int | None = None
    current_end: int | None = None
    current_chars = 0
    current_page_segments: list[UnitPageSegmentRecord] = []
    pending_page_meta: list[UnitPageSegmentRecord] = []

    def flush() -> None:
        nonlocal current_parts, current_start, current_end, current_chars, current_page_segments, pending_page_meta
        if not current_parts:
            return
        chunks.append(
            {
                "page_start": current_start,
                "page_end": current_end,
                "source_text": "\n\n".join(current_parts),
                "char_count": current_chars,
                "page_segments": list(current_page_segments),
            }
        )
        current_parts = []
        current_start = None
        current_end = None
        current_chars = 0
        current_page_segments = []
        pending_page_meta = []

    for segment in page_segments:
        page_no = int(segment.page_no or 0)
        visible_paragraphs = [paragraph for paragraph in segment.paragraphs if not paragraph.consumed_by_prev]
        segment_source = "\n\n".join(
            paragraph.source_text.strip()
            for paragraph in visible_paragraphs
            if paragraph.source_text.strip()
        ).strip()
        segment_display = "\n\n".join(
            paragraph.display_text.strip()
            for paragraph in visible_paragraphs
            if paragraph.display_text.strip()
        ).strip()
        normalized_segment = UnitPageSegmentRecord(
            page_no=page_no,
            paragraph_count=len(visible_paragraphs),
            source_text=segment_source,
            display_text=segment_display or segment.source_text,
            paragraphs=list(segment.paragraphs),
        )
        if page_no <= 0:
            continue
        if not segment_source:
            if current_start is None:
                pending_page_meta.append(normalized_segment)
            else:
                current_page_segments.append(normalized_segment)
            continue

        projected = current_chars + (2 if current_parts else 0) + len(segment_source)
        if current_parts and projected > int(max_body_chars):
            flush()
        if current_start is None:
            current_start = page_no
            if pending_page_meta:
                current_page_segments.extend(pending_page_meta)
                pending_page_meta = []
        current_end = page_no
        if current_parts:
            current_chars += 2
        current_parts.append(segment_source)
        current_chars += len(segment_source)
        current_page_segments.append(normalized_segment)
    flush()
    return chunks


def _chapter_endnote_start_page_map(note_regions: list[NoteRegionRecord]) -> dict[str, int]:
    start_page_by_chapter: dict[str, int] = {}
    for region in note_regions:
        if str(region.note_kind or "") != "endnote":
            continue
        chapter_id = str(region.chapter_id or "").strip()
        start_page = int(region.page_start or 0)
        if not chapter_id or start_page <= 0:
            continue
        existing = int(start_page_by_chapter.get(chapter_id) or 0)
        if existing <= 0 or start_page < existing:
            start_page_by_chapter[chapter_id] = start_page
    return start_page_by_chapter


def _build_structured_body_pages_for_chapter(
    chapter: ChapterRecord,
    *,
    raw_page_by_no: dict[int, dict[str, Any]],
    page_role_by_no: dict[int, str],
    note_start_page: int = 0,
    next_chapter: ChapterRecord | None = None,
) -> list[dict[str, Any]]:
    body_pages: list[dict[str, Any]] = []
    chapter_pages = [int(page_no) for page_no in (chapter.pages or []) if int(page_no) > 0]
    appended_pages: set[int] = set()
    chapter_start_page = int(chapter.start_page or (chapter_pages[0] if chapter_pages else 0))
    chapter_end_page = int(chapter.end_page or (chapter_pages[-1] if chapter_pages else 0))
    next_start_page = int((next_chapter.start_page if next_chapter else 0) or 0)
    next_title = str((next_chapter.title if next_chapter else "") or "").strip()

    def _append_page_text(page_no: int, raw_text: str) -> None:
        normalized = str(raw_text or "").strip()
        if not normalized or int(page_no) in appended_pages:
            return
        body_pages.append({"page_no": int(page_no), "text": normalized})
        appended_pages.add(int(page_no))

    for page_no in chapter_pages:
        raw_page = raw_page_by_no.get(page_no) or {}
        raw_text = page_markdown_text(raw_page)
        note_split = None
        if page_no == note_start_page and raw_text:
            note_split = _extract_note_heading_split(raw_text)
            if note_split is not None:
                raw_text = note_split[0]
        if page_no == chapter_start_page and raw_text:
            _ignored_prefix, chapter_text = _split_page_text_by_chapter_heading(raw_text, str(chapter.title or ""))
            raw_text = chapter_text or raw_text
        raw_text = _trim_trailing_markdown_note_block(raw_text)
        page_role = str(page_role_by_no.get(page_no) or "")
        allow_mixed_note_start_body = (
            page_no == note_start_page
            and note_split is not None
            and bool(str(raw_text or "").strip())
        )
        if page_role not in {"body", "front_matter"} and not allow_mixed_note_start_body:
            continue
        if note_start_page > 0 and page_no > note_start_page:
            continue
        _append_page_text(page_no, raw_text)

    if note_start_page > 0 and note_start_page not in appended_pages:
        raw_page = raw_page_by_no.get(note_start_page) or {}
        raw_text = page_markdown_text(raw_page)
        split = _extract_note_heading_split(raw_text) if raw_text else None
        if split is not None:
            _append_page_text(note_start_page, _trim_trailing_markdown_note_block(split[0]))
    if chapter_end_page > 0 and next_start_page - chapter_end_page > 1:
        for page_no in range(chapter_end_page + 1, next_start_page):
            if page_no in appended_pages:
                continue
            page_role = str(page_role_by_no.get(page_no) or "")
            if page_role not in {"body", "front_matter"}:
                continue
            raw_page = raw_page_by_no.get(page_no) or {}
            raw_text = page_markdown_text(raw_page)
            if not raw_text:
                continue
            leading_text, _ignored_tail = _split_page_text_at_first_heading(raw_text)
            sanitized = _sanitize_gap_page_prefix(_trim_trailing_markdown_note_block(leading_text))
            if sanitized:
                _append_page_text(page_no, sanitized)
    if next_start_page > 0 and next_start_page not in appended_pages:
        next_page_role = str(page_role_by_no.get(next_start_page) or "")
        if next_page_role in {"body", "front_matter"}:
            next_page = raw_page_by_no.get(next_start_page) or {}
            next_page_text = page_markdown_text(next_page)
            leading_text, _chapter_text = _split_page_text_by_chapter_heading(next_page_text, next_title)
            if leading_text:
                _append_page_text(
                    next_start_page,
                    _sanitize_gap_page_prefix(_trim_trailing_markdown_note_block(leading_text)),
                )
    return body_pages


def _ref_materialization_context(phase4: Phase4Structure) -> dict[str, Any]:
    anchors_by_id = {
        str(anchor.anchor_id or "").strip(): anchor
        for anchor in phase4.body_anchors
        if str(anchor.anchor_id or "").strip()
    }
    matched_links = [link for link in phase4.effective_note_links if str(link.status or "") == "matched"]
    anchor_to_note_ids: dict[str, set[str]] = {}
    for link in matched_links:
        anchor_id = str(link.anchor_id or "").strip()
        note_item_id = str(link.note_item_id or "").strip()
        if not anchor_id or not note_item_id:
            continue
        anchor_to_note_ids.setdefault(anchor_id, set()).add(note_item_id)
    conflict_anchor_ids = {
        anchor_id
        for anchor_id, note_ids in anchor_to_note_ids.items()
        if len(note_ids) > 1
    }
    return {
        "anchors_by_id": anchors_by_id,
        "conflict_anchor_ids": conflict_anchor_ids,
        "matched_link_count": len(matched_links),
        "ignored_skipped_count": sum(1 for link in phase4.effective_note_links if str(link.status or "") == "ignored"),
        "ambiguous_skipped_count": sum(1 for link in phase4.effective_note_links if str(link.status or "") == "ambiguous"),
    }


def _inject_token_once(
    text: str,
    *,
    anchor: BodyAnchorRecord,
    marker: str,
    note_id: str,
) -> tuple[str, bool]:
    payload = str(text or "")
    if not payload:
        return payload, False
    token = frozen_note_ref(note_id)
    if not token:
        return payload, False
    candidates = [
        str(anchor.source_marker or "").strip(),
        f"[{str(marker or '').strip()}]",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in payload:
            return payload.replace(candidate, token, 1), True
    normalized_marker = str(marker or "").strip()
    if normalized_marker:
        pattern = re.compile(r"\[\s*(?:\^)?\s*" + re.escape(normalized_marker) + r"\s*\]")
        replaced, count = pattern.subn(token, payload, count=1)
        if count > 0:
            return replaced, True
    return payload, False


def _materialize_refs_for_chapter(
    chapter: ChapterRecord,
    body_pages: list[dict[str, Any]],
    *,
    phase4: Phase4Structure,
    ref_ctx: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    anchors_by_id: dict[str, BodyAnchorRecord] = dict(ref_ctx.get("anchors_by_id") or {})
    conflict_anchor_ids: set[str] = set(ref_ctx.get("conflict_anchor_ids") or set())
    page_payload_by_no = {
        int(row.get("page_no") or 0): dict(row)
        for row in body_pages
        if int(row.get("page_no") or 0) > 0
    }
    synthetic_skipped = 0
    injected_count = 0
    chapter_links = [
        link
        for link in phase4.effective_note_links
        if str(link.status or "") == "matched"
        and str(link.chapter_id or "") == str(chapter.chapter_id or "")
    ]

    def _link_sort_key(link) -> tuple[int, int, str]:
        anchor = anchors_by_id.get(str(link.anchor_id or "").strip())
        return (
            int(anchor.page_no if anchor else 0),
            -int(anchor.char_start if anchor else 0),
            str(link.link_id or ""),
        )

    chapter_links.sort(key=_link_sort_key)
    injected_anchor_ids: set[str] = set()
    for link in chapter_links:
        anchor_id = str(link.anchor_id or "").strip()
        note_id = str(link.note_item_id or "").strip()
        if not anchor_id or not note_id:
            continue
        if anchor_id in injected_anchor_ids:
            continue
        if anchor_id in conflict_anchor_ids:
            continue
        anchor = anchors_by_id.get(anchor_id)
        if not anchor:
            continue
        if bool(anchor.synthetic):
            synthetic_skipped += 1
            continue
        page_no = int(anchor.page_no or 0)
        payload = page_payload_by_no.get(page_no)
        if not payload:
            continue
        updated_text, replaced = _inject_token_once(
            str(payload.get("text") or ""),
            anchor=anchor,
            marker=str(link.marker or ""),
            note_id=note_id,
        )
        if replaced:
            payload["text"] = updated_text
            page_payload_by_no[page_no] = payload
            injected_count += 1
            injected_anchor_ids.add(anchor_id)
    from FNM_RE.modules.ref_freeze import _cleanup_nested_note_refs
    for page_no, payload in page_payload_by_no.items():
        text = str(payload.get("text") or "")
        cleaned = _cleanup_nested_note_refs(text)
        if cleaned != text:
            payload["text"] = cleaned
            page_payload_by_no[page_no] = payload
    normalized_pages = [page_payload_by_no[int(row.get("page_no") or 0)] for row in body_pages if int(row.get("page_no") or 0) in page_payload_by_no]
    return normalized_pages, {
        "injected_link_count": injected_count,
        "synthetic_skipped_count": synthetic_skipped,
    }


def build_translation_units(
    phase4: Phase4Structure,
    *,
    pages: list[dict],
    max_body_chars: int = 6000,
) -> tuple[list[TranslationUnitRecord], dict]:
    raw_page_by_no = {
        int(page.get("bookPage") or 0): dict(page)
        for page in pages or []
        if int(page.get("bookPage") or 0) > 0
    }
    page_role_by_no = {
        int(row.page_no): str(row.page_role)
        for row in phase4.pages
        if int(row.page_no) > 0
    }
    chapter_order = {
        str(chapter.chapter_id or ""): index
        for index, chapter in enumerate(phase4.chapters, start=1)
        if str(chapter.chapter_id or "").strip()
    }
    chapter_by_id = {
        str(chapter.chapter_id or ""): chapter
        for chapter in phase4.chapters
        if str(chapter.chapter_id or "").strip()
    }
    note_region_by_id = {
        str(region.region_id or ""): region
        for region in phase4.note_regions
        if str(region.region_id or "").strip()
    }
    chapter_endnote_start_map = _chapter_endnote_start_page_map(phase4.note_regions)
    ref_ctx = _ref_materialization_context(phase4)

    units: list[TranslationUnitRecord] = []
    body_unit_counts: dict[str, int] = {}
    empty_body_chapter_count = 0
    ref_injected_count = 0
    ref_synthetic_skipped = 0

    for chapter_index, chapter in enumerate(phase4.chapters, start=1):
        chapter_id = str(chapter.chapter_id or "").strip()
        if not chapter_id:
            continue
        next_chapter = phase4.chapters[chapter_index] if chapter_index < len(phase4.chapters) else None
        body_pages = _build_structured_body_pages_for_chapter(
            chapter,
            raw_page_by_no=raw_page_by_no,
            page_role_by_no=page_role_by_no,
            note_start_page=int(chapter_endnote_start_map.get(chapter_id) or 0),
            next_chapter=next_chapter,
        )
        if not body_pages:
            empty_body_chapter_count += 1
            body_unit_counts[chapter_id] = 0
            continue

        injected_pages, inject_summary = _materialize_refs_for_chapter(
            chapter,
            body_pages,
            phase4=phase4,
            ref_ctx=ref_ctx,
        )
        ref_injected_count += int(inject_summary.get("injected_link_count") or 0)
        ref_synthetic_skipped += int(inject_summary.get("synthetic_skipped_count") or 0)
        section_payload = {
            "section_id": chapter_id,
            "title": str(chapter.title or ""),
            "start_page": int(chapter.start_page or 0),
            "end_page": int(chapter.end_page or 0),
            "frozen_body_pages": injected_pages,
            "obsidian_body_pages": [
                {
                    "page_no": int(row.get("page_no") or 0),
                    "text": replace_frozen_refs(str(row.get("text") or "")),
                }
                for row in injected_pages
            ],
        }
        page_segments = _segment_paragraphs_from_body_pages(section_payload)
        chunks = _chunk_body_page_segments(page_segments, max_body_chars=int(max_body_chars or 6000))
        body_unit_counts[chapter_id] = len(chunks)
        for chunk_index, chunk in enumerate(chunks, start=1):
            units.append(
                TranslationUnitRecord(
                    unit_id=f"body-{chapter_id}-{chunk_index:04d}",
                    kind="body",
                    owner_kind="chapter",
                    owner_id=chapter_id,
                    section_id=chapter_id,
                    section_title=str(chapter.title or ""),
                    section_start_page=int(chapter.start_page or 0),
                    section_end_page=int(chapter.end_page or 0),
                    note_id="",
                    page_start=int(chunk.get("page_start") or 0),
                    page_end=int(chunk.get("page_end") or int(chunk.get("page_start") or 0)),
                    char_count=int(chunk.get("char_count") or 0),
                    source_text=str(chunk.get("source_text") or ""),
                    translated_text="",
                    status="pending",
                    error_msg="",
                    target_ref="",
                    page_segments=list(chunk.get("page_segments") or []),
                )
            )

    ordered_note_items = sorted(
        phase4.note_items,
        key=lambda item: (
            int(chapter_order.get(str(item.chapter_id or "").strip()) or 10**6),
            int((note_region_by_id.get(str(item.region_id or "").strip()).page_start if note_region_by_id.get(str(item.region_id or "").strip()) else 10**6) or 10**6),
            int(item.page_no or 0),
            str((note_region_by_id.get(str(item.region_id or "").strip()).note_kind if note_region_by_id.get(str(item.region_id or "").strip()) else "") or ""),
            str(item.note_item_id or ""),
        ),
    )
    for item in ordered_note_items:
        chapter_id = str(item.chapter_id or "").strip()
        note_item_id = str(item.note_item_id or "").strip()
        if not chapter_id or not note_item_id:
            continue
        chapter = chapter_by_id.get(chapter_id) or ChapterRecord("", "", 0, 0, [], "fallback", "ready")
        region = note_region_by_id.get(str(item.region_id or "").strip())
        note_kind = str(region.note_kind if region else "")
        if note_kind not in {"footnote", "endnote"}:
            continue
        source_text = str(item.text or "").strip()
        start_page = int(item.page_no or 0)
        units.append(
            TranslationUnitRecord(
                unit_id=f"{note_kind}-{chapter_id}-{note_item_id}",
                kind=note_kind,
                owner_kind="note_region",
                owner_id=str(item.region_id or "").strip() or f"{chapter_id}-note-region",
                section_id=chapter_id,
                section_title=str(chapter.title or chapter_id),
                section_start_page=int(chapter.start_page or 0),
                section_end_page=int(chapter.end_page or int(chapter.start_page or 0)),
                note_id=note_item_id,
                page_start=start_page,
                page_end=start_page,
                char_count=len(source_text),
                source_text=source_text,
                translated_text="",
                status="pending",
                error_msg="",
                target_ref=frozen_note_ref(note_item_id),
                page_segments=[],
            )
        )

    units.sort(
        key=lambda row: (
            int(chapter_order.get(str(row.section_id or "").strip()) or 10**6),
            0 if str(row.kind or "") == "body" else 1,
            int(row.page_start or 0),
            str(row.unit_id or ""),
        )
    )
    body_unit_count = sum(1 for row in units if str(row.kind or "") == "body")
    note_unit_count = len(units) - body_unit_count
    summary = {
        "unit_planning_summary": {
            "body_unit_count": int(body_unit_count),
            "note_unit_count": int(note_unit_count),
            "chapter_unit_counts": dict(body_unit_counts),
            "empty_body_chapter_count": int(empty_body_chapter_count),
            "max_body_chars": int(max_body_chars or 6000),
        },
        "ref_materialization_summary": {
            "matched_link_count": int(ref_ctx.get("matched_link_count") or 0),
            "injected_link_count": int(ref_injected_count),
            "synthetic_skipped_count": int(ref_synthetic_skipped),
            "ignored_skipped_count": int(ref_ctx.get("ignored_skipped_count") or 0),
            "ambiguous_skipped_count": int(ref_ctx.get("ambiguous_skipped_count") or 0),
            "conflict_anchor_count": len(set(ref_ctx.get("conflict_anchor_ids") or set())),
        },
    }
    return units, summary

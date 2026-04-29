"""章节级内联脚注 Markdown 生成。

从 export.py 拆分出的独立模块，处理 footnote_primary 章节的
每段脚注内联渲染。
"""

from __future__ import annotations

import re
from typing import Any

from FNM_RE.models import (
    BodyAnchorRecord,
    NoteItemRecord,
    NoteLinkRecord,
    SectionHeadRecord,
    TranslationUnitRecord,
)
from FNM_RE.shared.export_constants import (
    _ANY_NOTE_REF_RE,
    PENDING_TRANSLATION_TEXT,
)
from FNM_RE.shared.marker_sequences import _build_raw_marker_note_sequences
from FNM_RE.shared.ref_rewriter import _resolve_note_id
from FNM_RE.stages.export import (
    _build_note_text_by_id_for_chapter,
    _build_section_heads_by_page,
    _chapter_page_numbers,
    _escape_leading_asterisks,
    _format_chapter_title,
    _normalized_paragraph_key,
    _rewrite_body_text_with_local_refs,
    _strip_trailing_image_only_block,
)


def _paragraph_attr(paragraph: Any, key: str, default: Any = "") -> Any:
    if isinstance(paragraph, dict):
        return paragraph.get(key, default)
    return getattr(paragraph, key, default)


def _visible_segment_paragraphs(segment: Any) -> list[Any]:
    paragraphs = []
    for paragraph in list(getattr(segment, "paragraphs", []) or []):
        if bool(_paragraph_attr(paragraph, "consumed_by_prev", False)):
            continue
        paragraphs.append(paragraph)
    return paragraphs


def _paragraph_render_text(paragraph: Any) -> str:
    translated = str(_paragraph_attr(paragraph, "translated_text", "") or "").strip()
    if translated:
        return translated
    display = str(_paragraph_attr(paragraph, "display_text", "") or "").strip()
    if display:
        return display
    return str(_paragraph_attr(paragraph, "source_text", "") or "").strip()


def _append_note_ids(target: dict[Any, list[str]], key: Any, note_id: str) -> None:
    if not note_id:
        return
    row = target.setdefault(key, [])
    if note_id not in row:
        row.append(note_id)


def _emit_local_note_definitions(
    note_ids: list[str],
    *,
    lines: list[str],
    emitted_note_ids: set[str],
    local_ref_numbers: dict[str, int],
    note_text_by_id: dict[str, str],
) -> int:
    emitted = 0
    for note_id in note_ids:
        if note_id in emitted_note_ids:
            continue
        number = int(local_ref_numbers.get(note_id) or 0)
        text = str(note_text_by_id.get(note_id) or "").strip()
        if number <= 0 or not text:
            continue
        lines.append(f"[^{number}]: {_escape_leading_asterisks(text)}")
        lines.append("")
        emitted_note_ids.add(note_id)
        emitted += 1
    return emitted


def _build_inline_footnote_targets(
    chapter_id: str,
    *,
    matched_links: list[NoteLinkRecord],
    note_items_by_id: dict[str, NoteItemRecord],
    body_anchors_by_id: dict[str, BodyAnchorRecord],
    note_text_by_id: dict[str, str],
) -> tuple[dict[tuple[int, int], list[str]], dict[int, list[str]]]:
    chapter_links = [
        link
        for link in matched_links
        if str(link.chapter_id or "") == str(chapter_id or "")
        and str(link.note_kind or "") == "footnote"
        and str(link.status or "") == "matched"
        and str(link.note_item_id or "").strip()
    ]
    chapter_links.sort(
        key=lambda link: (
            int(body_anchors_by_id.get(str(link.anchor_id or "").strip(), BodyAnchorRecord("", "", 0, 0, 0, 0, "", "", "unknown", 0.0, "", "", False, "")).page_no or 0),
            int(body_anchors_by_id.get(str(link.anchor_id or "").strip(), BodyAnchorRecord("", "", 0, 0, 0, 0, "", "", "unknown", 0.0, "", "", False, "")).paragraph_index or 0),
            int(body_anchors_by_id.get(str(link.anchor_id or "").strip(), BodyAnchorRecord("", "", 0, 0, 0, 0, "", "", "unknown", 0.0, "", "", False, "")).char_start or 0),
            str(link.link_id or ""),
        )
    )
    attached: dict[tuple[int, int], list[str]] = {}
    page_fallback: dict[int, list[str]] = {}
    for link in chapter_links:
        note_item_id = str(link.note_item_id or "").strip()
        note_id = _resolve_note_id(note_item_id, note_text_by_id)
        if not note_id or not str(note_text_by_id.get(note_id) or "").strip():
            continue
        note_item = note_items_by_id.get(note_item_id)
        anchor = body_anchors_by_id.get(str(link.anchor_id or "").strip())
        note_page = 0
        if anchor is not None and int(anchor.page_no or 0) > 0:
            note_page = int(anchor.page_no or 0)
        elif note_item is not None and int(note_item.page_no or 0) > 0:
            note_page = int(note_item.page_no or 0)
        else:
            note_page = int(link.page_no_start or 0)
        if anchor is not None and not bool(anchor.synthetic) and int(anchor.page_no or 0) > 0:
            _append_note_ids(attached, (int(anchor.page_no or 0), int(anchor.paragraph_index or 0)), note_id)
            continue
        if note_page > 0:
            _append_note_ids(page_fallback, note_page, note_id)
    return attached, page_fallback



def _build_inline_footnote_section_markdown(
    chapter: Any,
    *,
    section_heads: list[SectionHeadRecord],
    body_units: list[TranslationUnitRecord],
    note_units: list[TranslationUnitRecord],
    matched_links: list[NoteLinkRecord],
    note_items_by_id: dict[str, NoteItemRecord],
    body_anchors_by_id: dict[str, BodyAnchorRecord],
    include_diagnostic_entries: bool,
    diagnostic_machine_by_page: dict[int, str],
) -> tuple[str, dict[str, int]]:
    chapter_id = str(getattr(chapter, "chapter_id", "") or "")
    chapter_title = _format_chapter_title(getattr(chapter, "title", "") or chapter_id)
    chapter_pages = set(_chapter_page_numbers(chapter))
    note_text_by_id = _build_note_text_by_id_for_chapter(chapter_id, note_units=note_units)
    # 纯 footnote 章：无 endnote 冲突，保留 [^N] 编号（传空 note_kind_by_id = 全当 endnote 处理）
    _inline_note_kind_by_id: dict[str, str] = {}
    marker_note_sequences = _build_raw_marker_note_sequences(
        chapter_id,
        matched_links=matched_links,
        note_items_by_id=note_items_by_id,
        body_anchors_by_id=body_anchors_by_id,
        note_text_by_id=note_text_by_id,
    )
    section_heads_by_page = _build_section_heads_by_page(
        chapter_id,
        section_heads=section_heads,
        chapter_pages=chapter_pages,
    )
    attached_note_ids, page_fallback_note_ids = _build_inline_footnote_targets(
        chapter_id,
        matched_links=matched_links,
        note_items_by_id=note_items_by_id,
        body_anchors_by_id=body_anchors_by_id,
        note_text_by_id=note_text_by_id,
    )

    page_paragraphs: dict[int, list[Any]] = {}
    sorted_units = sorted(
        [unit for unit in body_units if str(unit.section_id or "") == chapter_id],
        key=lambda row: (int(row.page_start or 0), int(row.page_end or int(row.page_start or 0)), str(row.unit_id or "")),
    )
    for unit in sorted_units:
        for segment in sorted(
            [segment for segment in list(unit.page_segments or []) if int(segment.page_no or 0) > 0],
            key=lambda row: int(row.page_no or 0),
        ):
            page_no = int(segment.page_no or 0)
            visible = _visible_segment_paragraphs(segment)
            if visible:
                page_paragraphs.setdefault(page_no, []).extend(visible)
                continue
            fallback_text = str(segment.display_text or segment.source_text or "").strip()
            if not fallback_text:
                continue
            page_paragraphs.setdefault(page_no, []).append(
                {
                    "kind": "body",
                    "display_text": fallback_text,
                    "source_text": str(segment.source_text or fallback_text),
                    "translated_text": "",
                    "consumed_by_prev": False,
                }
            )

    lines: list[str] = [f"## {chapter_title}", ""]
    seen_section_heads: set[tuple[int, str]] = set()
    local_ref_numbers: dict[str, int] = {}
    ordered_note_ids: list[str] = []
    emitted_note_ids: set[str] = set()
    chapter_has_body = False
    inline_attach_count = 0
    page_fallback_count = 0

    for page_no in sorted(page_paragraphs.keys()):
        for title in section_heads_by_page.get(page_no, []):
            dedupe_key = (int(page_no), title.lower())
            if dedupe_key in seen_section_heads:
                continue
            seen_section_heads.add(dedupe_key)
            lines.append(f"### {title}")
            lines.append("")

        body_paragraph_index = 0
        page_has_body = False
        for paragraph in page_paragraphs.get(page_no, []):
            kind = str(_paragraph_attr(paragraph, "kind", "body") or "body").strip().lower()
            text = _paragraph_render_text(paragraph)
            if not text:
                continue
            if _normalized_paragraph_key(text) == _normalized_paragraph_key(chapter_title):
                continue
            if kind == "heading":
                heading_title = re.sub(r"\s+", " ", text).strip()
                if not heading_title or _normalized_paragraph_key(heading_title) == _normalized_paragraph_key(chapter_title):
                    continue
                dedupe_key = (int(page_no), heading_title.lower())
                if dedupe_key in seen_section_heads:
                    continue
                seen_section_heads.add(dedupe_key)
                lines.append(f"### {heading_title}")
                lines.append("")
                continue

            body_text = _rewrite_body_text_with_local_refs(
                text,
                note_text_by_id=note_text_by_id,
                note_kind_by_id=_inline_note_kind_by_id,
                marker_note_sequences=marker_note_sequences,
                local_ref_numbers=local_ref_numbers,
                ordered_note_ids=ordered_note_ids,
            )
            if (
                not str(_paragraph_attr(paragraph, "translated_text", "") or "").strip()
                and not include_diagnostic_entries
                and not note_text_by_id
                and _ANY_NOTE_REF_RE.search(body_text)
            ):
                body_text = PENDING_TRANSLATION_TEXT
            body_text = str(body_text or "").strip()
            if not body_text:
                body_paragraph_index += 1
                continue
            lines.append(_escape_leading_asterisks(body_text))
            lines.append("")
            chapter_has_body = True
            page_has_body = True
            inline_attach_count += _emit_local_note_definitions(
                list(attached_note_ids.get((page_no, body_paragraph_index), []) or []),
                lines=lines,
                emitted_note_ids=emitted_note_ids,
                local_ref_numbers=local_ref_numbers,
                note_text_by_id=note_text_by_id,
            )
            body_paragraph_index += 1

        remaining_page_note_ids: list[str] = []
        for (target_page_no, target_paragraph_index), note_ids in sorted(attached_note_ids.items()):
            if int(target_page_no) != int(page_no):
                continue
            if int(target_paragraph_index) >= int(body_paragraph_index):
                remaining_page_note_ids.extend(note_ids)
        remaining_page_note_ids.extend(list(page_fallback_note_ids.get(page_no) or []))
        if page_has_body:
            page_fallback_count += _emit_local_note_definitions(
                remaining_page_note_ids,
                lines=lines,
                emitted_note_ids=emitted_note_ids,
                local_ref_numbers=local_ref_numbers,
                note_text_by_id=note_text_by_id,
            )

    if not chapter_has_body:
        lines.append(PENDING_TRANSLATION_TEXT)
        lines.append("")

    chapter_end_count = _emit_local_note_definitions(
        list(ordered_note_ids),
        lines=lines,
        emitted_note_ids=emitted_note_ids,
        local_ref_numbers=local_ref_numbers,
        note_text_by_id=note_text_by_id,
    )
    content = _strip_trailing_image_only_block("\n".join(lines).strip())
    refs = sorted(set(re.findall(r"\[\^([0-9]+)\]", content)))
    defs = sorted(set(re.findall(r"^\[\^([0-9]+)\]:", content, re.MULTILINE)))
    contract_summary = {
        "local_ref_count": len(refs),
        "local_definition_count": len(defs),
        "missing_definition_count": len(set(refs) - set(defs)),
        "orphan_definition_count": len(set(defs) - set(refs)),
        "inline_footnote_paragraph_attach_count": int(inline_attach_count),
        "inline_footnote_page_fallback_count": int(page_fallback_count),
        "chapter_end_footnote_definition_count": int(chapter_end_count),
    }
    return content, contract_summary


"""阶段 5 模块：单章 markdown 合并。"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any, Mapping

from FNM_RE.models import (
    BodyAnchorRecord,
    ChapterNoteModeRecord,
    ChapterRecord,
    DiagnosticEntryRecord,
    DiagnosticPageRecord,
    NoteItemRecord,
    NoteLinkRecord,
    Phase5Structure,
    Phase5Summary,
    TranslationUnitRecord,
    UnitPageSegmentRecord,
    UnitParagraphRecord,
)
from FNM_RE.modules.contracts import GateReport, ModuleResult
from FNM_RE.modules.types import (
    ChapterLayers,
    ChapterMarkdownEntry,
    ChapterMarkdownSet,
    FrozenUnit,
    FrozenUnits,
    NoteLinkTable,
)
from FNM_RE.stages import export as export_stage
from FNM_RE.stages import export_audit as export_audit_stage


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _chapter_pages_from_layer(chapter: Any) -> list[int]:
    pages: set[int] = set()
    pages.update(int(row.page_no) for row in list(chapter.body_pages or []) if int(row.page_no) > 0)
    pages.update(int(row.page_no) for row in list(chapter.footnote_items or []) if int(row.page_no) > 0)
    pages.update(int(row.page_no) for row in list(chapter.endnote_items or []) if int(row.page_no) > 0)
    for row in list(chapter.endnote_regions or []):
        pages.update(int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0)
        if int(row.page_start) > 0:
            pages.add(int(row.page_start))
        if int(row.page_end) > 0:
            pages.add(int(row.page_end))
    return sorted(pages)


def _to_chapter_records(chapter_layers: ChapterLayers) -> list[ChapterRecord]:
    rows: list[ChapterRecord] = []
    for chapter in chapter_layers.chapters:
        chapter_id = str(chapter.chapter_id or "").strip()
        if not chapter_id:
            continue
        pages = _chapter_pages_from_layer(chapter)
        start_page = int(pages[0]) if pages else 0
        end_page = int(pages[-1]) if pages else start_page
        rows.append(
            ChapterRecord(
                chapter_id=chapter_id,
                title=str(chapter.title or chapter_id),
                start_page=start_page,
                end_page=end_page,
                pages=pages,
                source="fallback",
                boundary_state="ready",
            )
        )
    return rows


def _to_note_item_records(chapter_layers: ChapterLayers) -> list[NoteItemRecord]:
    return [
        NoteItemRecord(
            note_item_id=str(row.note_item_id or ""),
            region_id=str(row.region_id or ""),
            chapter_id=str(row.chapter_id or ""),
            page_no=int(row.page_no or 0),
            marker=str(row.marker or ""),
            marker_type=str(row.marker_type or ""),
            text=str(row.text or ""),
            source=str(row.source or ""),
            source_page_label=str(row.page_no or ""),
            is_reconstructed=bool(row.is_reconstructed),
            review_required=bool(row.review_required),
        )
        for row in chapter_layers.note_items
        if str(row.note_item_id or "").strip()
    ]


def _to_body_anchor_records(note_link_table: NoteLinkTable) -> list[BodyAnchorRecord]:
    return [
        BodyAnchorRecord(
            anchor_id=str(row.anchor_id or ""),
            chapter_id=str(row.chapter_id or ""),
            page_no=int(row.page_no or 0),
            paragraph_index=int(row.paragraph_index or 0),
            char_start=int(row.char_start or 0),
            char_end=int(row.char_end or 0),
            source_marker=str(row.source_marker or ""),
            normalized_marker=str(row.normalized_marker or ""),
            anchor_kind=str(row.anchor_kind),
            certainty=float(row.certainty or 0.0),
            source_text=str(row.source_text or ""),
            source=str(row.source or ""),
            synthetic=bool(row.synthetic),
            ocr_repaired_from_marker=str(row.ocr_repaired_from_marker or ""),
        )
        for row in note_link_table.anchors
        if str(row.anchor_id or "").strip()
    ]


def _to_note_link_records(note_link_table: NoteLinkTable) -> list[NoteLinkRecord]:
    return [
        NoteLinkRecord(
            link_id=str(row.link_id or ""),
            chapter_id=str(row.chapter_id or ""),
            region_id=str(row.region_id or ""),
            note_item_id=str(row.note_item_id or ""),
            anchor_id=str(row.anchor_id or ""),
            status=str(row.status),
            resolver=str(row.resolver),
            confidence=float(row.confidence or 0.0),
            note_kind=str(row.note_kind),
            marker=str(row.marker or ""),
            page_no_start=int(row.page_no_start or 0),
            page_no_end=int(row.page_no_end or 0),
        )
        for row in note_link_table.effective_links
        if str(row.link_id or "").strip()
    ]


def _to_page_segments(unit: FrozenUnit) -> list[UnitPageSegmentRecord]:
    rows: list[UnitPageSegmentRecord] = []
    for row in list(unit.page_segments or []):
        payload = dict(row or {})
        paragraphs: list[UnitParagraphRecord] = []
        for paragraph in list(payload.get("paragraphs") or []):
            paragraph_payload = dict(paragraph or {})
            paragraphs.append(
                UnitParagraphRecord(
                    order=int(paragraph_payload.get("order") or 0),
                    kind=str(paragraph_payload.get("kind") or ""),
                    heading_level=int(paragraph_payload.get("heading_level") or 0),
                    source_text=str(paragraph_payload.get("source_text") or ""),
                    display_text=str(paragraph_payload.get("display_text") or ""),
                    cross_page=paragraph_payload.get("cross_page"),
                    consumed_by_prev=bool(paragraph_payload.get("consumed_by_prev")),
                    section_path=[
                        str(item or "")
                        for item in list(paragraph_payload.get("section_path") or [])
                        if str(item or "").strip()
                    ],
                    print_page_label=str(paragraph_payload.get("print_page_label") or ""),
                    translated_text=str(paragraph_payload.get("translated_text") or ""),
                    translation_status=str(paragraph_payload.get("translation_status") or "pending"),
                    attempt_count=int(paragraph_payload.get("attempt_count") or 0),
                    last_error=str(paragraph_payload.get("last_error") or ""),
                    manual_resolved=bool(paragraph_payload.get("manual_resolved")),
                )
            )
        rows.append(
            UnitPageSegmentRecord(
                page_no=int(payload.get("page_no") or 0),
                paragraph_count=int(payload.get("paragraph_count") or 0),
                source_text=str(payload.get("source_text") or ""),
                display_text=str(payload.get("display_text") or ""),
                paragraphs=paragraphs,
            )
        )
    return rows


def _to_translation_unit_records(frozen_units: FrozenUnits) -> list[TranslationUnitRecord]:
    rows: list[TranslationUnitRecord] = []
    for unit in list(frozen_units.body_units or []) + list(frozen_units.note_units or []):
        rows.append(
            TranslationUnitRecord(
                unit_id=str(unit.unit_id or ""),
                kind=str(unit.kind or ""),
                owner_kind=str(unit.owner_kind or ""),
                owner_id=str(unit.owner_id or ""),
                section_id=str(unit.section_id or ""),
                section_title=str(unit.section_title or ""),
                section_start_page=int(unit.section_start_page or 0),
                section_end_page=int(unit.section_end_page or 0),
                note_id=str(unit.note_id or ""),
                page_start=int(unit.page_start or 0),
                page_end=int(unit.page_end or int(unit.page_start or 0)),
                char_count=int(unit.char_count or 0),
                source_text=str(unit.source_text or ""),
                translated_text=str(unit.translated_text or ""),
                status=str(unit.status or "pending"),
                error_msg=str(unit.error_msg or ""),
                target_ref=str(unit.target_ref or ""),
                page_segments=_to_page_segments(unit),
            )
        )
    return rows


def _to_chapter_note_mode_records(chapter_layers: ChapterLayers) -> list[ChapterNoteModeRecord]:
    rows: list[ChapterNoteModeRecord] = []
    for chapter in chapter_layers.chapters:
        policy = dict(chapter.policy_applied or {})
        rows.append(
            ChapterNoteModeRecord(
                chapter_id=str(chapter.chapter_id or ""),
                note_mode=str(policy.get("note_mode") or "no_notes"),  # type: ignore[arg-type]
                region_ids=[
                    str(region.region_id or "")
                    for region in list(chapter.endnote_regions or [])
                    if str(region.region_id or "").strip()
                ],
                has_footnote_band=bool(chapter.footnote_items),
                has_endnote_region=bool(chapter.endnote_regions),
            )
        )
    return rows


def _phase5_book_type(chapter_layers: ChapterLayers) -> str:
    for chapter in chapter_layers.chapters:
        policy = dict(chapter.policy_applied or {})
        book_type = str(policy.get("book_type") or "").strip()
        if book_type:
            return book_type
    return "no_notes"


def _to_diagnostic_pages(diagnostic_machine_by_page: Mapping[int | str, str] | None) -> list[DiagnosticPageRecord]:
    rows: list[DiagnosticPageRecord] = []
    for key, text in sorted(dict(diagnostic_machine_by_page or {}).items(), key=lambda item: _safe_int(item[0])):
        page_no = _safe_int(key)
        content = str(text or "").strip()
        if page_no <= 0 or not content:
            continue
        rows.append(
            DiagnosticPageRecord(
                _pageBP=page_no,
                _status="done",
                pages=str(page_no),
                _page_entries=[
                    DiagnosticEntryRecord(
                        original="",
                        translation=content,
                        footnotes="",
                        footnotes_translation="",
                        heading_level=0,
                        pages=str(page_no),
                        _startBP=page_no,
                        _endBP=page_no,
                        _printPageLabel=str(page_no),
                        _status="done",
                        _error="",
                        _translation_source="model",
                        _machine_translation=content,
                        _manual_translation="",
                        _cross_page=None,
                    )
                ],
                _fnm_source={},
            )
        )
    return rows


def _build_phase5_shadow(
    frozen_units: FrozenUnits,
    note_link_table: NoteLinkTable,
    chapter_layers: ChapterLayers,
    *,
    diagnostic_machine_by_page: Mapping[int | str, str] | None,
    include_diagnostic_entries: bool,
) -> Phase5Structure:
    chapter_note_modes = _to_chapter_note_mode_records(chapter_layers)
    chapter_note_mode_summary = {
        "book_type": _phase5_book_type(chapter_layers),
        "mode_counts": dict(Counter(str(row.note_mode or "") for row in chapter_note_modes)),
    }
    return Phase5Structure(
        chapters=_to_chapter_records(chapter_layers),
        section_heads=[],
        note_items=_to_note_item_records(chapter_layers),
        chapter_note_modes=chapter_note_modes,
        body_anchors=_to_body_anchor_records(note_link_table),
        effective_note_links=_to_note_link_records(note_link_table),
        translation_units=_to_translation_unit_records(frozen_units),
        diagnostic_pages=(
            _to_diagnostic_pages(diagnostic_machine_by_page)
            if include_diagnostic_entries
            else []
        ),
        summary=Phase5Summary(
            chapter_note_mode_summary=chapter_note_mode_summary,
        ),
    )


def _has_raw_marker_in_body(markdown_text: str) -> bool:
    body_text, _ = export_audit_stage.split_body_and_definitions(markdown_text)
    allowed_markers = set(export_audit_stage.LOCAL_REF_RE.findall(body_text))
    allowed_markers.update(export_audit_stage.LOCAL_DEF_RE.findall(str(markdown_text or "")))
    if not allowed_markers:
        return False
    if any(True for _ in export_audit_stage._iter_raw_note_marker_hits(body_text, allowed_markers=allowed_markers)):
        return True
    if any(
        True
        for _ in export_audit_stage._iter_raw_superscript_note_marker_hits(body_text, allowed_markers=allowed_markers)
    ):
        return True
    return False


_LOCAL_DEF_LINE_RE = re.compile(r"^\[\^([0-9]+)\]:\s*(.*)$")


def _chapter_note_text_by_id(
    frozen_units: FrozenUnits,
    *,
    chapter_id: str,
) -> dict[str, str]:
    payload: dict[str, str] = {}
    for unit in frozen_units.note_units:
        if str(unit.section_id or "") != str(chapter_id or ""):
            continue
        note_id = str(unit.note_id or "").strip()
        if not note_id:
            continue
        text = export_stage._sanitize_note_text(str(unit.translated_text or unit.source_text or ""))
        if export_stage._should_replace_definition_text(payload.get(note_id, ""), text):
            payload[note_id] = text
    return payload


def _book_note_text_by_id(frozen_units: FrozenUnits) -> dict[str, str]:
    payload: dict[str, str] = {}
    for unit in frozen_units.note_units:
        note_id = str(unit.note_id or "").strip()
        if not note_id:
            continue
        text = export_stage._sanitize_note_text(str(unit.translated_text or unit.source_text or ""))
        if export_stage._should_replace_definition_text(payload.get(note_id, ""), text):
            payload[note_id] = text
    return payload


def _chapter_marker_sequences(
    chapter_layers: ChapterLayers,
    *,
    chapter_id: str,
    note_text_by_id: dict[str, str],
) -> dict[str, list[str]]:
    sequences: dict[str, list[str]] = {}
    chapter_items = sorted(
        [
            item
            for item in chapter_layers.note_items
            if str(item.chapter_id or "") == str(chapter_id or "")
        ],
        key=lambda item: (int(item.page_no or 0), str(item.note_item_id or "")),
    )
    for item in chapter_items:
        note_id = export_stage._resolve_note_id(str(item.note_item_id or ""), note_text_by_id)
        if not note_id:
            continue
        marker_candidates: set[str] = set()
        marker_candidates.update(export_stage._marker_aliases(note_id))
        marker_candidates.update(export_stage._marker_aliases(str(item.marker or "")))
        for marker in marker_candidates:
            row = sequences.setdefault(marker, [])
            row.append(note_id)
    return sequences


def _rewrite_residual_raw_markers_for_chapter(
    chapter: ChapterMarkdownEntry,
    *,
    note_text_by_id: dict[str, str],
    marker_note_sequences: dict[str, list[str]],
    fallback_note_text_by_id: dict[str, str] | None = None,
) -> str:
    markdown_text = str(chapter.markdown_text or "")
    if not markdown_text:
        return markdown_text
    resolved_note_text_by_id = dict(fallback_note_text_by_id or {})
    resolved_note_text_by_id.update(dict(note_text_by_id or {}))
    marker_note_sequences = dict(marker_note_sequences or {})
    body_text, definition_text = export_audit_stage.split_body_and_definitions(markdown_text)
    existing_numbers = sorted(
        {
            int(token)
            for token in (
                list(export_audit_stage.LOCAL_REF_RE.findall(body_text))
                + list(export_audit_stage.LOCAL_DEF_RE.findall(markdown_text))
            )
            if str(token).isdigit()
        }
    )
    local_ref_numbers: dict[str, int] = {f"__reserved_{num}": int(num) for num in existing_numbers}
    ordered_note_ids: list[str] = [f"__reserved_{num}" for num in existing_numbers]
    marker_usage_index: dict[str, int] = {}

    updated_body = export_stage._replace_note_refs_with_local_labels(
        body_text,
        note_text_by_id=resolved_note_text_by_id,
        note_kind_by_id={},
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
    )
    updated_body = export_stage._replace_raw_bracket_refs_with_local_labels(
        updated_body,
        marker_note_sequences=marker_note_sequences,
        marker_usage_index=marker_usage_index,
        note_kind_by_id={},
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
    )
    updated_body = export_stage._replace_raw_superscript_refs_with_local_labels(
        updated_body,
        marker_note_sequences=marker_note_sequences,
        marker_usage_index=marker_usage_index,
        note_kind_by_id={},
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
    )
    updated_body = export_stage._replace_raw_unicode_superscript_refs_with_local_labels(
        updated_body,
        marker_note_sequences=marker_note_sequences,
        marker_usage_index=marker_usage_index,
        note_kind_by_id={},
        local_ref_numbers=local_ref_numbers,
        ordered_note_ids=ordered_note_ids,
    )
    local_number_tokens = {
        str(token)
        for token in (
            list(export_audit_stage.LOCAL_REF_RE.findall(updated_body))
            + list(export_audit_stage.LOCAL_DEF_RE.findall(markdown_text))
        )
        if str(token).strip().isdigit()
    }

    def _replace_raw_bracket_with_existing_local_ref(match: re.Match) -> str:
        marker = str(match.group(1) or "").strip()
        return f"[^{marker}]" if marker in local_number_tokens else match.group(0)

    def _replace_raw_sup_with_existing_local_ref(match: re.Match) -> str:
        marker = str(match.group(1) or match.group(2) or "").strip()
        if not marker:
            marker = str(match.group(3) or "").translate(export_audit_stage._UNICODE_SUPERSCRIPT_TRANSLATION).strip()
        return f"[^{marker}]" if marker in local_number_tokens else match.group(0)

    updated_body = export_audit_stage.RAW_BRACKET_NOTE_REF_RE.sub(
        _replace_raw_bracket_with_existing_local_ref,
        updated_body,
    )
    updated_body = export_audit_stage.RAW_SUPERSCRIPT_NOTE_REF_RE.sub(
        _replace_raw_sup_with_existing_local_ref,
        updated_body,
    )
    if updated_body == body_text:
        return markdown_text

    definitions: dict[int, str] = {}
    for line in str(definition_text or "").splitlines():
        match = _LOCAL_DEF_LINE_RE.match(str(line or "").rstrip())
        if not match:
            continue
        number = int(match.group(1))
        text = str(match.group(2) or "").strip()
        if number > 0 and text:
            definitions[number] = text
    def _replace_def_note_refs(def_text: str) -> str:
        """Replace {{NOTE_REF:<number>}} tokens in fallback definition text with [^N]."""
        ref_num_to_note_id: dict[int, str] = {v: k for k, v in local_ref_numbers.items()}
        last_ref_num = 0

        def _replacer(m: re.Match) -> str:
            nonlocal last_ref_num
            for idx in range(1, 7):
                captured = str(m.group(idx) or "").strip()
                if not captured:
                    continue
                if captured.lower() == "ibid":
                    if last_ref_num > 0:
                        return f"[^{last_ref_num}]"
                    return m.group(0)
                if captured.isdigit():
                    ref_num = int(captured)
                    if ref_num in ref_num_to_note_id:
                        note_id = ref_num_to_note_id[ref_num]
                        target_num = int(local_ref_numbers[note_id])
                        if target_num > 0:
                            last_ref_num = target_num
                            return f"[^{target_num}]"
                return m.group(0)
            return m.group(0)

        return export_stage._ANY_NOTE_REF_RE.sub(_replacer, def_text)

    for note_id in ordered_note_ids:
        if note_id.startswith("__reserved_"):
            continue
        number = int(local_ref_numbers.get(note_id) or 0)
        if number <= 0 or number in definitions:
            continue
        text = str(resolved_note_text_by_id.get(note_id) or "").strip()
        if text:
            definitions[number] = _replace_def_note_refs(text)

    lines: list[str] = [str(updated_body or "").strip()]
    if definitions:
        lines.append("")
        for number in sorted(definitions.keys()):
            lines.append(f"[^{number}]: {definitions[number]}")
    return "\n".join(lines).strip()


_DEF_LINE_PRINTED_PREFIX_RE = re.compile(r"^\[\^(\d+)\]:\s*(.*)$")


def _apply_notes_block_format(markdown_text: str) -> str:
    """工单 #7a + #7b：统一章节 NOTES 块格式。

    - 当章节末尾出现 `[^N]: <text>` 定义行但缺 `### NOTES` 标题时，自动追加
      标题（除章 1 外原 OCR 不会自带该标题，导致导出 zip 章 2-12 全部缺标题）。
    - 每条 `[^N]: <text>` 改为 `[^N]: N. <text>` 印刷编号前缀，幂等
      （text 已以 `N. ` 开头则不重复）。按金板 PROCESSING_NOTES 第 25 条落格。
    """
    text = str(markdown_text or "")
    if not text:
        return text
    output_lines: list[str] = []
    has_def_lines = False
    notes_heading_inserted = False
    saw_notes_heading_already = False
    raw_lines = text.splitlines()
    # 先扫描定位是否已有 ### NOTES
    for line in raw_lines:
        stripped = line.strip()
        if stripped.startswith("### NOTES") or stripped == "### NOTES":
            saw_notes_heading_already = True
            break

    for line in raw_lines:
        match = _DEF_LINE_PRINTED_PREFIX_RE.match(line.rstrip())
        if match:
            number = int(match.group(1))
            body = str(match.group(2) or "").strip()
            # 工单 #7a：第一条定义行出现前补 NOTES 标题（如尚无）
            if not has_def_lines and not saw_notes_heading_already and not notes_heading_inserted:
                # 在前面插入空行 + 标题
                while output_lines and output_lines[-1].strip() == "":
                    output_lines.pop()
                if output_lines:
                    output_lines.append("")
                output_lines.append("### NOTES")
                output_lines.append("")
                notes_heading_inserted = True
            has_def_lines = True
            # 工单 #7b：印刷编号前缀（幂等）
            prefix = f"{number}. "
            if not body.startswith(prefix):
                body = f"{prefix}{body}"
            output_lines.append(f"[^{number}]: {body}")
        else:
            output_lines.append(line)
    return "\n".join(output_lines).rstrip() + ("\n" if text.endswith("\n") else "")


def _rewrite_chapters_for_merge(
    chapters: list[ChapterMarkdownEntry],
    *,
    frozen_units: FrozenUnits,
    chapter_layers: ChapterLayers,
) -> list[ChapterMarkdownEntry]:
    rewritten: list[ChapterMarkdownEntry] = []
    book_note_text_by_id = _book_note_text_by_id(frozen_units)
    for row in chapters:
        note_text_by_id = _chapter_note_text_by_id(
            frozen_units,
            chapter_id=str(row.chapter_id or ""),
        )
        marker_note_sequences = _chapter_marker_sequences(
            chapter_layers,
            chapter_id=str(row.chapter_id or ""),
            note_text_by_id=note_text_by_id,
        )
        rewritten.append(
            ChapterMarkdownEntry(
                order=int(row.order or 0),
                chapter_id=str(row.chapter_id or ""),
                title=str(row.title or ""),
                path=str(row.path or ""),
                markdown_text=_rewrite_residual_raw_markers_for_chapter(
                    row,
                    note_text_by_id=note_text_by_id,
                    marker_note_sequences=marker_note_sequences,
                    fallback_note_text_by_id=book_note_text_by_id,
                ),
                start_page=int(row.start_page or 0),
                end_page=int(row.end_page or int(row.start_page or 0)),
                pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
            )
        )
    return rewritten


def _chapter_contract_items_by_section(chapter_contract_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for row in list(chapter_contract_summary.get("items") or []):
        item = dict(row or {})
        section_id = str(item.get("section_id") or "").strip()
        if section_id:
            payload[section_id] = item
    return payload


def _has_legacy_note_token(markdown_text: str) -> bool:
    text = str(markdown_text or "")
    return any(
        pattern.search(text)
        for pattern in (
            export_audit_stage.LEGACY_FOOTNOTE_RE,
            export_audit_stage.LEGACY_ENDNOTE_RE,
            export_audit_stage.LEGACY_EN_BRACKET_RE,
            export_audit_stage.LEGACY_NOTE_TOKEN_RE,
        )
    )


def _build_chapter_issue_diagnostics(
    chapters: list[ChapterMarkdownEntry],
    *,
    chapter_contract_summary: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    contract_by_section = _chapter_contract_items_by_section(chapter_contract_summary)
    chapter_issue_summary: list[dict[str, Any]] = []
    chapter_issue_count = 0
    frozen_ref_leak_chapter_count = 0
    raw_marker_leak_chapter_count = 0
    local_ref_contract_broken_chapter_count = 0

    for row in chapters:
        text = str(row.markdown_text or "")
        contract_item = dict(contract_by_section.get(str(row.chapter_id or ""), {}) or {})
        missing_definition_count = int(contract_item.get("missing_definition_count") or 0)
        orphan_definition_count = int(contract_item.get("orphan_definition_count") or 0)
        frozen_ref_leak = _has_legacy_note_token(text)
        raw_marker_leak = _has_raw_marker_in_body(text)
        local_refs_closed = missing_definition_count == 0 and orphan_definition_count == 0
        has_issue = frozen_ref_leak or raw_marker_leak or (not local_refs_closed)
        if has_issue:
            chapter_issue_count += 1
        if frozen_ref_leak:
            frozen_ref_leak_chapter_count += 1
        if raw_marker_leak:
            raw_marker_leak_chapter_count += 1
        if not local_refs_closed:
            local_ref_contract_broken_chapter_count += 1

        chapter_issue_summary.append(
            {
                "chapter_id": str(row.chapter_id or ""),
                "title": str(row.title or ""),
                "path": str(row.path or ""),
                "frozen_ref_leak": bool(frozen_ref_leak),
                "raw_marker_leak": bool(raw_marker_leak),
                "missing_definition_count": int(missing_definition_count),
                "orphan_definition_count": int(orphan_definition_count),
                "local_refs_closed": bool(local_refs_closed),
            }
        )

    chapter_issue_counts = {
        "chapter_issue_count": int(chapter_issue_count),
        "frozen_ref_leak_chapter_count": int(frozen_ref_leak_chapter_count),
        "raw_marker_leak_chapter_count": int(raw_marker_leak_chapter_count),
        "local_ref_contract_broken_chapter_count": int(local_ref_contract_broken_chapter_count),
    }
    return chapter_issue_summary, chapter_issue_counts


def build_chapter_markdown_set(
    frozen_units: FrozenUnits,
    note_link_table: NoteLinkTable,
    chapter_layers: ChapterLayers,
    *,
    diagnostic_machine_by_page: Mapping[int | str, str] | None = None,
    include_diagnostic_entries: bool = False,
) -> ModuleResult[ChapterMarkdownSet]:
    phase5 = _build_phase5_shadow(
        frozen_units,
        note_link_table,
        chapter_layers,
        diagnostic_machine_by_page=diagnostic_machine_by_page,
        include_diagnostic_entries=bool(include_diagnostic_entries),
    )
    from FNM_RE.stages.export_contract import _build_export_chapters
    export_chapters, export_summary = _build_export_chapters(
        phase5,
        include_diagnostic_entries=bool(include_diagnostic_entries),
    )
    chapters = [
        ChapterMarkdownEntry(
            order=int(row.order or 0),
            chapter_id=str(row.section_id or ""),
            title=str(row.title or ""),
            path=str(row.path or ""),
            markdown_text=str(row.content or ""),
            start_page=int(row.start_page or 0),
            end_page=int(row.end_page or int(row.start_page or 0)),
            pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
        )
        for row in export_chapters
        if str(row.section_id or "").strip()
    ]
    chapters = _rewrite_chapters_for_merge(
        chapters,
        frozen_units=frozen_units,
        chapter_layers=chapter_layers,
    )
    # 工单 #7：在最终 markdown 上应用 NOTES 块格式（标题统一 + 印刷编号前缀）。
    chapters = [
        ChapterMarkdownEntry(
            order=int(row.order or 0),
            chapter_id=str(row.chapter_id or ""),
            title=str(row.title or ""),
            path=str(row.path or ""),
            markdown_text=_apply_notes_block_format(str(row.markdown_text or "")),
            start_page=int(row.start_page or 0),
            end_page=int(row.end_page or int(row.start_page or 0)),
            pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
        )
        for row in chapters
    ]

    expected_chapters = [row for row in chapter_layers.chapters if str(row.chapter_id or "").strip()]
    chapter_contract_summary = dict(export_summary.get("chapter_ref_contract_summary") or {})
    chapter_issue_summary, chapter_issue_counts = _build_chapter_issue_diagnostics(
        chapters,
        chapter_contract_summary=chapter_contract_summary,
    )
    local_refs_closed = int(chapter_issue_counts.get("local_ref_contract_broken_chapter_count") or 0) == 0
    no_frozen_ref_leak = int(chapter_issue_counts.get("frozen_ref_leak_chapter_count") or 0) == 0
    no_raw_marker_leak_in_body = int(chapter_issue_counts.get("raw_marker_leak_chapter_count") or 0) == 0
    chapter_files_emitted = len(chapters) == len(expected_chapters) and all(
        str(row.path or "").endswith(".md") for row in chapters
    )
    image_tail_warn = all(
        not bool(export_stage._TRAILING_IMAGE_ONLY_BLOCK_RE.search(str(row.markdown_text or "")))
        for row in chapters
    )
    section_heading_warn = all(
        not export_audit_stage._detect_mid_paragraph_heading(
            export_audit_stage.split_body_and_definitions(str(row.markdown_text or ""))[0]
        )
        for row in chapters
    )

    hard = {
        "merge.chapter_files_emitted": bool(chapter_files_emitted),
        "merge.local_refs_closed": bool(local_refs_closed),
        "merge.no_frozen_ref_leak": bool(no_frozen_ref_leak),
        "merge.no_raw_marker_leak_in_body": bool(no_raw_marker_leak_in_body),
    }
    soft = {
        "merge.image_tail_warn": bool(image_tail_warn),
        "merge.section_heading_warn": bool(section_heading_warn),
    }
    reasons: list[str] = []
    if not hard["merge.chapter_files_emitted"]:
        reasons.append("merge_chapter_files_emitted_failed")
    if not hard["merge.local_refs_closed"]:
        reasons.append("merge_local_refs_unclosed")
    if not hard["merge.no_frozen_ref_leak"]:
        reasons.append("merge_frozen_ref_leak")
    if not hard["merge.no_raw_marker_leak_in_body"]:
        reasons.append("merge_raw_marker_leak")

    merge_summary = {
        "chapter_count": len(chapters),
        "expected_chapter_count": len(expected_chapters),
        "include_diagnostic_entries": bool(include_diagnostic_entries),
        "local_refs_closed": bool(local_refs_closed),
        "no_frozen_ref_leak": bool(no_frozen_ref_leak),
        "no_raw_marker_leak_in_body": bool(no_raw_marker_leak_in_body),
        "image_tail_warn": bool(image_tail_warn),
        "section_heading_warn": bool(section_heading_warn),
        "chapter_issue_count": int(chapter_issue_counts.get("chapter_issue_count") or 0),
        "frozen_ref_leak_chapter_count": int(chapter_issue_counts.get("frozen_ref_leak_chapter_count") or 0),
        "raw_marker_leak_chapter_count": int(chapter_issue_counts.get("raw_marker_leak_chapter_count") or 0),
        "local_ref_contract_broken_chapter_count": int(
            chapter_issue_counts.get("local_ref_contract_broken_chapter_count") or 0
        ),
        "inline_footnote_paragraph_attach_count": int(
            export_summary.get("inline_footnote_paragraph_attach_count") or 0
        ),
        "inline_footnote_page_fallback_count": int(
            export_summary.get("inline_footnote_page_fallback_count") or 0
        ),
        "chapter_end_footnote_definition_count": int(
            export_summary.get("chapter_end_footnote_definition_count") or 0
        ),
    }
    evidence = {
        "merge_summary": dict(merge_summary),
        "chapter_contract_summary": dict(chapter_contract_summary),
    }
    diagnostics = {
        "chapter_ids": [str(row.chapter_id or "") for row in chapters],
        "chapter_issue_summary": chapter_issue_summary,
        "chapter_issue_counts": chapter_issue_counts,
    }
    gate_report = GateReport(
        module="merge",
        hard=hard,
        soft=soft,
        reasons=reasons,
        evidence=evidence,
        overrides_used=[],
    )
    data = ChapterMarkdownSet(
        chapters=chapters,
        chapter_contract_summary=chapter_contract_summary,
        merge_summary=merge_summary,
    )
    return ModuleResult(
        data=data,
        gate_report=gate_report,
        evidence=evidence,
        overrides_used=[],
        diagnostics=diagnostics,
    )

"""阶段 4 模块：引用冻结与 unit 规划。"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict
from typing import Any

from FNM_RE.modules.contracts import GateReport, ModuleResult
from FNM_RE.modules.types import (
    BodyAnchorLayer,
    ChapterLayer,
    ChapterLayers,
    FrozenRefEntry,
    FrozenUnit,
    FrozenUnits,
    NoteLinkLayer,
    NoteLinkTable,
)
from FNM_RE.shared.refs import frozen_note_ref, replace_frozen_refs
from FNM_RE.stages.units import _chunk_body_page_segments, _segment_paragraphs_from_body_pages
from FNM_RE.shared.notes import _safe_int

_TOKEN_CANDIDATE_RE_TEMPLATE = r"\[\s*(?:\^)?\s*{marker}\s*\]"

def _chapter_order_map(chapter_layers: ChapterLayers) -> dict[str, int]:
    return {
        str(chapter.chapter_id or ""): index
        for index, chapter in enumerate(chapter_layers.chapters, start=1)
        if str(chapter.chapter_id or "").strip()
    }

def _chapter_page_bounds(chapter: ChapterLayer) -> tuple[int, int]:
    pages: set[int] = set()
    pages.update(int(row.page_no) for row in chapter.body_pages if int(row.page_no) > 0)
    pages.update(int(row.page_no) for row in chapter.footnote_items if int(row.page_no) > 0)
    pages.update(int(row.page_no) for row in chapter.endnote_items if int(row.page_no) > 0)
    for region in chapter.endnote_regions:
        pages.update(int(page_no) for page_no in list(region.pages or []) if int(page_no) > 0)
        if int(region.page_start) > 0:
            pages.add(int(region.page_start))
        if int(region.page_end) > 0:
            pages.add(int(region.page_end))
    if not pages:
        return 0, 0
    sorted_pages = sorted(pages)
    return int(sorted_pages[0]), int(sorted_pages[-1])

def _resolve_note_item_owner(
    item: Any,
    *,
    region_by_id: dict[str, Any],
    valid_chapter_ids: set[str],
) -> tuple[str, str]:
    region = region_by_id.get(str(getattr(item, "region_id", "") or ""))
    candidates = [
        ("item.owner_chapter_id", str(getattr(item, "owner_chapter_id", "") or "").strip()),
        ("item.chapter_id", str(getattr(item, "chapter_id", "") or "").strip()),
        ("region.owner_chapter_id", str(getattr(region, "owner_chapter_id", "") or "").strip()),
        ("region.chapter_id", str(getattr(region, "chapter_id", "") or "").strip()),
    ]
    for source, chapter_id in candidates:
        if chapter_id and chapter_id in valid_chapter_ids:
            return chapter_id, source
    return "", ""

def _inject_token_once(
    text: str,
    *,
    anchor: BodyAnchorLayer,
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
        pattern = re.compile(_TOKEN_CANDIDATE_RE_TEMPLATE.format(marker=re.escape(normalized_marker)))
        replaced, count = pattern.subn(token, payload, count=1)
        if count > 0:
            return replaced, True
    return payload, False

def _unit_contract_issues(*, body_units: list[FrozenUnit], note_units: list[FrozenUnit]) -> list[str]:
    issues: list[str] = []
    for row in list(body_units) + list(note_units):
        if not str(row.unit_id or "").strip():
            issues.append("missing_unit_id")
        if not str(row.kind or "").strip():
            issues.append(f"missing_kind:{row.unit_id}")
        if not str(row.owner_kind or "").strip() or not str(row.owner_id or "").strip():
            issues.append(f"missing_owner:{row.unit_id}")
        if not str(row.section_id or "").strip():
            issues.append(f"missing_section_id:{row.unit_id}")
        if not isinstance(row.page_segments, list):
            issues.append(f"invalid_page_segments_type:{row.unit_id}")
    for row in body_units:
        if str(row.target_ref or "").strip():
            issues.append(f"body_target_ref_not_empty:{row.unit_id}")
    for row in note_units:
        if str(row.kind or "") not in {"footnote", "endnote"}:
            issues.append(f"note_kind_invalid:{row.unit_id}")
        if not str(row.note_id or "").strip():
            issues.append(f"note_id_missing:{row.unit_id}")
        if not str(row.target_ref or "").startswith("{{NOTE_REF:"):
            issues.append(f"note_target_ref_invalid:{row.unit_id}")
    return issues

def build_frozen_units(
    chapter_layers: ChapterLayers,
    note_link_table: NoteLinkTable,
    *,
    max_body_chars: int = 6000,
) -> ModuleResult[FrozenUnits]:
    chapter_order = _chapter_order_map(chapter_layers)
    chapter_by_id = {
        str(chapter.chapter_id or ""): chapter
        for chapter in chapter_layers.chapters
        if str(chapter.chapter_id or "").strip()
    }
    valid_chapter_ids = set(chapter_by_id.keys())
    region_by_id = {
        str(region.region_id or ""): region
        for region in chapter_layers.regions
        if str(region.region_id or "").strip()
    }
    anchor_by_id = {
        str(anchor.anchor_id or ""): anchor
        for anchor in note_link_table.anchors
        if str(anchor.anchor_id or "").strip()
    }
    matched_links = [
        row
        for row in note_link_table.effective_links
        if str(row.status or "") == "matched"
    ]
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
    matched_links.sort(
        key=lambda row: (
            int(chapter_order.get(str(row.chapter_id or ""), 10**6)),
            _safe_int(anchor_by_id.get(str(row.anchor_id or ""), BodyAnchorLayer("", "", 0, 0, 0, 0, "", "", "unknown", 0.0, "", "", False, "")).page_no),
            -_safe_int(anchor_by_id.get(str(row.anchor_id or ""), BodyAnchorLayer("", "", 0, 0, 0, 0, "", "", "unknown", 0.0, "", "", False, "")).char_start),
            str(row.link_id or ""),
        )
    )

    chapter_body_pages: dict[str, dict[int, dict[str, Any]]] = {}
    chapter_body_page_order: dict[str, list[int]] = {}
    for chapter in chapter_layers.chapters:
        chapter_id = str(chapter.chapter_id or "")
        page_map: dict[int, dict[str, Any]] = {}
        page_order: list[int] = []
        for page in chapter.body_pages:
            page_no = int(page.page_no)
            if page_no <= 0:
                continue
            page_map[page_no] = {"page_no": page_no, "text": str(page.text or "")}
            page_order.append(page_no)
        chapter_body_pages[chapter_id] = page_map
        chapter_body_page_order[chapter_id] = page_order

    ref_map: list[FrozenRefEntry] = []
    injected_anchor_ids: set[str] = set()
    skipped_reason_counts: Counter[str] = Counter()
    for link in matched_links:
        chapter_id = str(link.chapter_id or "")
        anchor_id = str(link.anchor_id or "").strip()
        note_item_id = str(link.note_item_id or "").strip()
        marker = str(link.marker or "")
        anchor = anchor_by_id.get(anchor_id)
        target_ref = frozen_note_ref(note_item_id)

        def _append_skipped(reason: str, page_no: int = 0) -> None:
            skipped_reason_counts.update([reason])
            ref_map.append(
                FrozenRefEntry(
                    link_id=str(link.link_id or ""),
                    chapter_id=chapter_id,
                    anchor_id=anchor_id,
                    note_item_id=note_item_id,
                    target_ref=target_ref,
                    decision="skipped",
                    reason=reason,  # type: ignore[arg-type]
                    page_no=int(page_no or 0),
                )
            )

        if not anchor:
            _append_skipped("missing_anchor")
            continue
        if bool(anchor.synthetic):
            _append_skipped("synthetic_anchor", page_no=int(anchor.page_no))
            continue
        if anchor_id in conflict_anchor_ids:
            _append_skipped("conflict_anchor", page_no=int(anchor.page_no))
            continue
        if anchor_id in injected_anchor_ids:
            _append_skipped("duplicate_anchor", page_no=int(anchor.page_no))
            continue
        payload = dict(chapter_body_pages.get(chapter_id, {}).get(int(anchor.page_no), {}))
        if not payload:
            _append_skipped("missing_body_page", page_no=int(anchor.page_no))
            continue
        updated_text, injected = _inject_token_once(
            str(payload.get("text") or ""),
            anchor=anchor,
            marker=marker,
            note_id=note_item_id,
        )
        if not injected:
            _append_skipped("token_not_found", page_no=int(anchor.page_no))
            continue
        payload["text"] = updated_text
        chapter_body_pages.setdefault(chapter_id, {})[int(anchor.page_no)] = payload
        injected_anchor_ids.add(anchor_id)
        ref_map.append(
            FrozenRefEntry(
                link_id=str(link.link_id or ""),
                chapter_id=chapter_id,
                anchor_id=anchor_id,
                note_item_id=note_item_id,
                target_ref=target_ref,
                decision="injected",
                reason="",
                page_no=int(anchor.page_no),
            )
        )

    body_units: list[FrozenUnit] = []
    chapter_unit_counts: dict[str, int] = {}
    empty_body_chapter_count = 0
    chapter_bounds = {
        str(chapter.chapter_id or ""): _chapter_page_bounds(chapter)
        for chapter in chapter_layers.chapters
    }
    for chapter in chapter_layers.chapters:
        chapter_id = str(chapter.chapter_id or "")
        page_order = [page_no for page_no in chapter_body_page_order.get(chapter_id, []) if page_no in chapter_body_pages.get(chapter_id, {})]
        frozen_body_pages = [chapter_body_pages[chapter_id][page_no] for page_no in page_order]
        if not frozen_body_pages:
            empty_body_chapter_count += 1
            chapter_unit_counts[chapter_id] = 0
            continue
        section_payload = {
            "section_id": chapter_id,
            "title": str(chapter.title or ""),
            "frozen_body_pages": list(frozen_body_pages),
            "obsidian_body_pages": [
                {"page_no": int(row.get("page_no") or 0), "text": replace_frozen_refs(str(row.get("text") or ""))}
                for row in frozen_body_pages
            ],
        }
        page_segments = _segment_paragraphs_from_body_pages(section_payload)
        chunks = _chunk_body_page_segments(page_segments, max_body_chars=int(max_body_chars or 6000))
        chapter_unit_counts[chapter_id] = len(chunks)
        section_start_page, section_end_page = chapter_bounds.get(chapter_id, (0, 0))
        for chunk_index, chunk in enumerate(chunks, start=1):
            body_units.append(
                FrozenUnit(
                    unit_id=f"body-{chapter_id}-{chunk_index:04d}",
                    kind="body",
                    owner_kind="chapter",
                    owner_id=chapter_id,
                    section_id=chapter_id,
                    section_title=str(chapter.title or ""),
                    section_start_page=int(section_start_page),
                    section_end_page=int(section_end_page),
                    note_id="",
                    page_start=int(chunk.get("page_start") or 0),
                    page_end=int(chunk.get("page_end") or int(chunk.get("page_start") or 0)),
                    char_count=int(chunk.get("char_count") or 0),
                    source_text=str(chunk.get("source_text") or ""),
                    translated_text="",
                    status="pending",
                    error_msg="",
                    target_ref="",
                    page_segments=[asdict(row) for row in list(chunk.get("page_segments") or [])],
                )
            )

    note_units: list[FrozenUnit] = []
    seen_note_unit_keys: set[tuple[str, str]] = set()
    unresolved_note_item_ids: list[str] = []
    unresolved_note_item_id_set: set[str] = set()
    chapter_view_note_unit_count = 0
    owner_fallback_note_unit_count = 0

    def _append_note_unit(
        *,
        item: Any,
        resolved_chapter_id: str,
    ) -> bool:
        note_item_id = str(item.note_item_id or "")
        if not note_item_id:
            return False
        dedupe_key = (resolved_chapter_id, note_item_id)
        if dedupe_key in seen_note_unit_keys:
            return False
        chapter = chapter_by_id.get(resolved_chapter_id)
        section_start_page, section_end_page = chapter_bounds.get(
            resolved_chapter_id,
            (int(item.page_no or 0), int(item.page_no or 0)),
        )
        note_units.append(
            FrozenUnit(
                unit_id=f"{str(item.note_kind or 'note')}-{resolved_chapter_id}-{note_item_id}",
                kind=str(item.note_kind or "note"),
                owner_kind="note_region",
                owner_id=str(item.region_id or ""),
                section_id=resolved_chapter_id,
                section_title=str((chapter.title if chapter else resolved_chapter_id) or resolved_chapter_id),
                section_start_page=int(section_start_page),
                section_end_page=int(section_end_page),
                note_id=note_item_id,
                page_start=int(item.page_no or 0),
                page_end=int(item.page_no or 0),
                char_count=len(str(item.text or "")),
                source_text=str(item.text or ""),
                translated_text="",
                status="pending",
                error_msg="",
                target_ref=frozen_note_ref(note_item_id),
                page_segments=[],
            )
        )
        seen_note_unit_keys.add(dedupe_key)
        return True

    # 主路径：章节材料化视图
    for chapter in chapter_layers.chapters:
        chapter_note_items = [*list(chapter.footnote_items or []), *list(chapter.endnote_items or [])]
        for item in chapter_note_items:
            resolved_chapter_id, _source = _resolve_note_item_owner(
                item,
                region_by_id=region_by_id,
                valid_chapter_ids=valid_chapter_ids,
            )
            note_item_id = str(item.note_item_id or "")
            if not resolved_chapter_id:
                if note_item_id and note_item_id not in unresolved_note_item_id_set:
                    unresolved_note_item_ids.append(note_item_id)
                    unresolved_note_item_id_set.add(note_item_id)
                continue
            if _append_note_unit(item=item, resolved_chapter_id=resolved_chapter_id):
                chapter_view_note_unit_count += 1

    # 兜底路径：仅补录未被章节视图消费的 raw item
    ordered_note_items = sorted(
        chapter_layers.note_items,
        key=lambda row: (
            int(row.page_no or 0),
            str(row.note_item_id or ""),
        ),
    )
    for item in ordered_note_items:
        resolved_chapter_id, _source = _resolve_note_item_owner(
            item,
            region_by_id=region_by_id,
            valid_chapter_ids=valid_chapter_ids,
        )
        note_item_id = str(item.note_item_id or "")
        if not resolved_chapter_id:
            if note_item_id and note_item_id not in unresolved_note_item_id_set:
                unresolved_note_item_ids.append(note_item_id)
                unresolved_note_item_id_set.add(note_item_id)
            continue
        if _append_note_unit(item=item, resolved_chapter_id=resolved_chapter_id):
            owner_fallback_note_unit_count += 1

    body_units.sort(
        key=lambda row: (
            int(chapter_order.get(str(row.section_id or ""), 10**6)),
            int(row.page_start or 0),
            str(row.unit_id or ""),
        )
    )
    note_units.sort(
        key=lambda row: (
            int(chapter_order.get(str(row.section_id or ""), 10**6)),
            int(row.page_start or 0),
            str(row.unit_id or ""),
        )
    )

    matched_link_ids = {str(row.link_id or "") for row in matched_links}
    injected_rows = [row for row in ref_map if row.decision == "injected"]
    injected_count = len(injected_rows)
    skipped_count = len(ref_map) - injected_count
    synthetic_skipped_count = int(skipped_reason_counts.get("synthetic_anchor", 0))
    conflict_skipped_count = int(skipped_reason_counts.get("conflict_anchor", 0))
    unit_contract_issues = _unit_contract_issues(body_units=body_units, note_units=note_units)
    unit_contract_issues.extend(f"unresolved_note_item:{note_item_id}" for note_item_id in unresolved_note_item_ids)

    hard = {
        "freeze.only_matched_frozen": all(str(row.link_id or "") in matched_link_ids for row in injected_rows),
        "freeze.no_duplicate_injection": injected_count == len({str(row.anchor_id or "") for row in injected_rows}),
        "freeze.accounting_closed": len(ref_map) == len(matched_links)
        and all(row.decision in {"injected", "skipped"} for row in ref_map),
        "freeze.unit_contract_valid": len(unit_contract_issues) == 0,
    }
    soft = {
        "freeze.synthetic_skip_warn": synthetic_skipped_count == 0,
        "freeze.conflict_skip_warn": conflict_skipped_count == 0,
    }
    reasons: list[str] = []
    if not hard["freeze.only_matched_frozen"]:
        reasons.append("freeze_only_matched_violation")
    if not hard["freeze.no_duplicate_injection"]:
        reasons.append("freeze_duplicate_injection")
    if not hard["freeze.accounting_closed"]:
        reasons.append("freeze_accounting_unclosed")
    if not hard["freeze.unit_contract_valid"]:
        reasons.append("freeze_unit_contract_invalid")

    freeze_summary = {
        "matched_link_count": int(len(matched_links)),
        "injected_count": int(injected_count),
        "skipped_count": int(skipped_count),
        "skip_reason_counts": dict(skipped_reason_counts),
        "synthetic_skipped_count": int(synthetic_skipped_count),
        "conflict_anchor_count": int(len(conflict_anchor_ids)),
        "body_unit_count": int(len(body_units)),
        "note_unit_count": int(len(note_units)),
        "chapter_view_note_unit_count": int(chapter_view_note_unit_count),
        "owner_fallback_note_unit_count": int(owner_fallback_note_unit_count),
        "unresolved_note_item_count": int(len(unresolved_note_item_ids)),
        "unresolved_note_item_ids_preview": list(unresolved_note_item_ids[:24]),
        "chapter_unit_counts": {str(key): int(value) for key, value in chapter_unit_counts.items()},
        "empty_body_chapter_count": int(empty_body_chapter_count),
        "max_body_chars": int(max_body_chars or 6000),
    }
    evidence = {
        "freeze_summary": dict(freeze_summary),
        "link_summary": dict(note_link_table.link_summary or {}),
        "matched_link_count": int(len(matched_links)),
    }
    diagnostics = {
        "unit_contract_issues": list(unit_contract_issues),
        "matched_link_ids": sorted(matched_link_ids),
        "conflict_anchor_ids": sorted(conflict_anchor_ids),
    }
    gate_report = GateReport(
        module="freeze",
        hard=hard,
        soft=soft,
        reasons=reasons,
        evidence=evidence,
        overrides_used=[],
    )
    data = FrozenUnits(
        body_units=body_units,
        note_units=note_units,
        ref_map=ref_map,
        freeze_summary=freeze_summary,
    )
    return ModuleResult(
        data=data,
        gate_report=gate_report,
        evidence=evidence,
        overrides_used=[],
        diagnostics=diagnostics,
    )

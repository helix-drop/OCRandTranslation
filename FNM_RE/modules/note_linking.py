"""阶段 3 模块：正文锚点与注释链接。"""

from __future__ import annotations

from dataclasses import replace
from collections import Counter
from typing import Any, Mapping

from FNM_RE.constants import NOTE_MODES
from FNM_RE.models import (
    BodyAnchorRecord,
    ChapterNoteModeRecord,
    ChapterRecord,
    NoteItemRecord,
    NoteLinkRecord,
    NoteRegionRecord,
    PagePartitionRecord,
    Phase2Structure,
    Phase2Summary,
)
from FNM_RE.modules.contracts import GateReport, ModuleResult
from FNM_RE.modules.types import (
    BodyAnchorLayer,
    ChapterLayers,
    ChapterLinkContract,
    NoteLinkLayer,
    NoteLinkTable,
)
from FNM_RE.shared.notes import normalize_note_marker
from FNM_RE.stages.body_anchors import build_body_anchors
from FNM_RE.stages.note_links import _marker_digits_are_ordered_subsequence, build_note_links


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _refresh_anchor_summary(
    *,
    base_summary: Mapping[str, Any],
    anchors: list[BodyAnchorRecord],
) -> dict[str, Any]:
    kind_counts = Counter(str(row.anchor_kind or "") for row in anchors)
    total_count = len(anchors)
    synthetic_count = sum(1 for row in anchors if bool(row.synthetic))
    explicit_count = total_count - synthetic_count
    uncertain_count = sum(
        1
        for row in anchors
        if str(row.anchor_kind or "") == "unknown" or float(row.certainty or 1.0) < 1.0
    )
    ocr_repaired_count = sum(1 for row in anchors if str(row.ocr_repaired_from_marker or "").strip())
    return {
        **dict(base_summary or {}),
        "total_count": int(total_count),
        "explicit_count": int(explicit_count),
        "synthetic_count": int(synthetic_count),
        "kind_counts": dict(kind_counts),
        "uncertain_count": int(uncertain_count),
        "ocr_repaired_count": int(ocr_repaired_count),
    }


def _to_anchor_layers(rows: list[BodyAnchorRecord]) -> list[BodyAnchorLayer]:
    return [
        BodyAnchorLayer(
            anchor_id=str(row.anchor_id or ""),
            chapter_id=str(row.chapter_id or ""),
            page_no=int(row.page_no),
            paragraph_index=int(row.paragraph_index),
            char_start=int(row.char_start),
            char_end=int(row.char_end),
            source_marker=str(row.source_marker or ""),
            normalized_marker=str(row.normalized_marker or ""),
            anchor_kind=str(row.anchor_kind),  # type: ignore[arg-type]
            certainty=float(row.certainty),
            source_text=str(row.source_text or ""),
            source=str(row.source or ""),
            synthetic=bool(row.synthetic),
            ocr_repaired_from_marker=str(row.ocr_repaired_from_marker or ""),
        )
        for row in rows
    ]


def _to_link_layers(rows: list[NoteLinkRecord]) -> list[NoteLinkLayer]:
    return [
        NoteLinkLayer(
            link_id=str(row.link_id or ""),
            chapter_id=str(row.chapter_id or ""),
            region_id=str(row.region_id or ""),
            note_item_id=str(row.note_item_id or ""),
            anchor_id=str(row.anchor_id or ""),
            status=str(row.status),  # type: ignore[arg-type]
            resolver=str(row.resolver),  # type: ignore[arg-type]
            confidence=float(row.confidence),
            note_kind=str(row.note_kind),  # type: ignore[arg-type]
            marker=str(row.marker or ""),
            page_no_start=int(row.page_no_start),
            page_no_end=int(row.page_no_end),
        )
        for row in rows
    ]


def _summarize_links(rows: list[NoteLinkRecord]) -> dict[str, int]:
    return {
        "matched": sum(1 for row in rows if str(row.status or "") == "matched"),
        "footnote_orphan_note": sum(
            1
            for row in rows
            if str(row.note_kind or "") == "footnote" and str(row.status or "") == "orphan_note"
        ),
        "footnote_orphan_anchor": sum(
            1
            for row in rows
            if str(row.note_kind or "") == "footnote" and str(row.status or "") == "orphan_anchor"
        ),
        "endnote_orphan_note": sum(
            1
            for row in rows
            if str(row.note_kind or "") == "endnote" and str(row.status or "") == "orphan_note"
        ),
        "endnote_orphan_anchor": sum(
            1
            for row in rows
            if str(row.note_kind or "") == "endnote" and str(row.status or "") == "orphan_anchor"
        ),
        "ambiguous": sum(1 for row in rows if str(row.status or "") == "ambiguous"),
        "ignored": sum(1 for row in rows if str(row.status or "") == "ignored"),
        "fallback_count": sum(1 for row in rows if str(row.resolver or "") == "fallback"),
        "repair_count": sum(1 for row in rows if str(row.resolver or "") == "repair"),
    }


def _projection_priority(projection_mode: str) -> int:
    mode = str(projection_mode or "").strip().lower()
    if mode == "book_projected":
        return 3
    if mode == "book_marker_projected":
        return 2
    if mode == "book_fallback_projected":
        return 1
    return 0


def _looks_like_single_digit_ocr_variant(left_marker: str, right_marker: str) -> bool:
    left = normalize_note_marker(left_marker)
    right = normalize_note_marker(right_marker)
    if not left or not right or left == right:
        return False
    if len(left) == len(right):
        return sum(1 for left_digit, right_digit in zip(left, right) if left_digit != right_digit) == 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    if len(longer) != len(shorter) + 1:
        return False
    return longer[1:] == shorter


def _build_note_item_meta_by_id(chapter_layers: ChapterLayers) -> dict[str, dict[str, Any]]:
    return {
        str(row.note_item_id or ""): {
            "projection_mode": str(row.projection_mode or ""),
            "owner_chapter_id": str(row.owner_chapter_id or ""),
            "source_marker": str(row.source_marker or ""),
            "normalized_marker": str(row.normalized_marker or ""),
        }
        for row in chapter_layers.note_items
        if str(row.note_item_id or "").strip()
    }


def _build_book_endnote_stream_summary(chapter_layers: ChapterLayers) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    chapter_ids: list[str] = []
    concentrated_chapter_ids: list[str] = []
    for chapter in chapter_layers.chapters:
        chapter_id = str(chapter.chapter_id or "")
        endnote_items = list(chapter.endnote_items or [])
        if not endnote_items:
            continue
        chapter_ids.append(chapter_id)
        projection_mode_counts = dict(Counter(str(item.projection_mode or "unknown") for item in endnote_items))
        row = {
            "chapter_id": chapter_id,
            "item_count": int(len(endnote_items)),
            "projection_mode_counts": projection_mode_counts,
        }
        if int(len(endnote_items)) >= 100:
            concentrated_chapter_ids.append(chapter_id)
        rows.append(row)
    return {
        "chapter_count": int(len(rows)),
        "chapters_with_endnote_stream": chapter_ids,
        "high_concentration_chapter_ids": concentrated_chapter_ids,
        "chapters": rows[:32],
    }


def _group_review_overrides(review_overrides: Any) -> dict[str, dict[str, dict]]:
    grouped: dict[str, dict[str, dict]] = {
        "page": {},
        "chapter": {},
        "region": {},
        "link": {},
        "llm_suggestion": {},
        "anchor": {},
        "note_item": {},
    }
    if not review_overrides:
        return grouped
    if isinstance(review_overrides, list):
        for row in review_overrides:
            payload = dict(row or {})
            scope = str(payload.get("scope") or "").strip().lower()
            target_id = str(payload.get("target_id") or "").strip()
            data = dict(payload.get("payload") or {})
            if not scope or not target_id:
                continue
            grouped.setdefault(scope, {})[target_id] = data
        return grouped
    if isinstance(review_overrides, Mapping):
        known_scopes = {"page", "chapter", "region", "link", "llm_suggestion", "anchor", "note_item"}
        if any(str(key) in known_scopes for key in review_overrides.keys()):
            for scope, rows in dict(review_overrides).items():
                scope_key = str(scope or "").strip().lower()
                if scope_key not in known_scopes or not isinstance(rows, Mapping):
                    continue
                grouped[scope_key] = {
                    str(target_id): dict(payload or {})
                    for target_id, payload in dict(rows).items()
                    if str(target_id or "").strip()
                }
    return grouped


def _infer_note_kind_from_anchor(anchor: BodyAnchorRecord, *, mode_by_chapter: Mapping[str, str]) -> str:
    if str(anchor.anchor_kind or "") == "footnote":
        return "footnote"
    if str(anchor.anchor_kind or "") == "endnote":
        return "endnote"
    mode = str(mode_by_chapter.get(str(anchor.chapter_id or "")) or "")
    if mode in {"footnote_primary", "review_required"}:
        return "footnote"
    return "endnote"


def _materialize_anchor_overrides(
    body_anchors: list[BodyAnchorRecord],
    *,
    anchor_overrides: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[list[BodyAnchorRecord], dict[str, Any], list[dict[str, Any]]]:
    """消费 scope="anchor" override，物化成 BodyAnchorRecord 追加到 anchors 尾部。

    仅支持 `action == "create"` 的 LLM 合成锚点；已有 anchor_id 冲突的 override 会被丢弃。
    新 anchor 保留 `source="llm", synthetic=False`，以便后续 ref_freeze / 占位符链路接纳。
    """
    overrides = dict(anchor_overrides or {})
    logs: list[dict[str, Any]] = []
    summary = {
        "created_count": 0,
        "rejected_count": 0,
        "rejected_reasons": [],
    }
    if not overrides:
        return list(body_anchors), summary, logs

    existing_ids = {str(row.anchor_id or "") for row in body_anchors if str(row.anchor_id or "")}
    new_anchors: list[BodyAnchorRecord] = list(body_anchors)
    for target_id, payload in overrides.items():
        data = dict(payload or {})
        action = str(data.get("action") or "").strip().lower()
        anchor_id = str(data.get("anchor_id") or target_id or "").strip()
        if action != "create":
            summary["rejected_count"] += 1
            summary["rejected_reasons"].append(f"{target_id}:action={action or 'missing'}")
            continue
        if not anchor_id or anchor_id in existing_ids:
            summary["rejected_count"] += 1
            summary["rejected_reasons"].append(f"{target_id}:anchor_id_conflict")
            continue
        chapter_id = str(data.get("chapter_id") or "").strip()
        try:
            page_no = int(data.get("page_no") or 0)
            paragraph_index = int(data.get("paragraph_index") or 0)
            char_start = int(data.get("char_start") or -1)
            char_end = int(data.get("char_end") or -1)
            certainty = float(data.get("certainty") or 0.0)
        except (TypeError, ValueError):
            summary["rejected_count"] += 1
            summary["rejected_reasons"].append(f"{target_id}:numeric_cast_failed")
            continue
        if not chapter_id or page_no <= 0 or char_start < 0 or char_end <= char_start:
            summary["rejected_count"] += 1
            summary["rejected_reasons"].append(f"{target_id}:invalid_coords")
            continue
        anchor_kind = str(data.get("anchor_kind") or "endnote").strip() or "endnote"
        record = BodyAnchorRecord(
            anchor_id=anchor_id,
            chapter_id=chapter_id,
            page_no=page_no,
            paragraph_index=paragraph_index,
            char_start=char_start,
            char_end=char_end,
            source_marker=str(data.get("normalized_marker") or ""),
            normalized_marker=str(data.get("normalized_marker") or ""),
            anchor_kind=anchor_kind,  # type: ignore[arg-type]
            certainty=certainty,
            source_text=str(data.get("source_text") or ""),
            source=str(data.get("source") or "llm"),
            synthetic=bool(data.get("synthetic") or False),
            ocr_repaired_from_marker="",
        )
        new_anchors.append(record)
        existing_ids.add(anchor_id)
        summary["created_count"] += 1
        logs.append(
            {
                "kind": "anchor_override",
                "anchor_id": anchor_id,
                "chapter_id": chapter_id,
                "page_no": page_no,
                "char_start": char_start,
                "char_end": char_end,
                "source": record.source,
            }
        )
    return new_anchors, summary, logs


def _materialize_note_item_overrides(
    phase2: Phase2Structure,
    *,
    note_item_overrides: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[Phase2Structure, dict[str, Any], list[dict[str, Any]]]:
    overrides = dict(note_item_overrides or {})
    logs: list[dict[str, Any]] = []
    summary = {
        "created_note_item_count": 0,
        "created_region_count": 0,
        "rejected_count": 0,
        "rejected_reasons": [],
    }
    if not overrides:
        return phase2, summary, logs

    note_items: list[NoteItemRecord] = list(phase2.note_items)
    note_regions: list[NoteRegionRecord] = list(phase2.note_regions)
    existing_note_item_ids = {
        str(row.note_item_id or "") for row in note_items if str(row.note_item_id or "").strip()
    }
    existing_region_ids = {
        str(row.region_id or "") for row in note_regions if str(row.region_id or "").strip()
    }

    for target_id, payload in overrides.items():
        data = dict(payload or {})
        action = str(data.get("action") or "").strip().lower()
        note_item_id = str(data.get("note_item_id") or target_id or "").strip()
        if action != "create":
            summary["rejected_count"] += 1
            summary["rejected_reasons"].append(f"{target_id}:action={action or 'missing'}")
            continue
        if not note_item_id or note_item_id in existing_note_item_ids:
            summary["rejected_count"] += 1
            summary["rejected_reasons"].append(f"{target_id}:note_item_id_conflict")
            continue
        chapter_id = str(data.get("chapter_id") or "").strip()
        marker = normalize_note_marker(str(data.get("marker") or ""))
        text = str(data.get("text") or data.get("note_text") or "").strip()
        note_kind = str(data.get("note_kind") or "endnote").strip() or "endnote"
        try:
            page_no = int(data.get("page_no") or 0)
        except (TypeError, ValueError):
            page_no = 0
        if not chapter_id or page_no <= 0 or not marker or not text:
            summary["rejected_count"] += 1
            summary["rejected_reasons"].append(f"{target_id}:invalid_note_item")
            continue

        region_id = str(data.get("region_id") or "").strip()
        if not region_id or region_id not in existing_region_ids:
            region_id = f"llm-note-region-{chapter_id}-{page_no}-{note_kind}"
            if region_id not in existing_region_ids:
                note_regions.append(
                    NoteRegionRecord(
                        region_id=region_id,
                        chapter_id=chapter_id,
                        page_start=page_no,
                        page_end=page_no,
                        pages=[page_no],
                        note_kind=note_kind,  # type: ignore[arg-type]
                        scope="chapter",  # type: ignore[arg-type]
                        source="llm",  # type: ignore[arg-type]
                        heading_text="",
                        start_reason="llm_note_item_override",
                        end_reason="llm_note_item_override",
                        region_marker_alignment_ok=True,
                        region_start_first_source_marker=marker,
                        region_first_note_item_marker=marker,
                        review_required=bool(data.get("review_required") or False),
                    )
                )
                existing_region_ids.add(region_id)
                summary["created_region_count"] += 1
                logs.append(
                    {
                        "kind": "note_region_override",
                        "region_id": region_id,
                        "chapter_id": chapter_id,
                        "page_no": page_no,
                        "note_kind": note_kind,
                    }
                )

        note_items.append(
            NoteItemRecord(
                note_item_id=note_item_id,
                region_id=region_id,
                chapter_id=chapter_id,
                page_no=page_no,
                marker=marker,
                marker_type="footnote_marker" if note_kind == "footnote" else "numeric",
                text=text,
                source=str(data.get("source") or "llm"),
                source_page_label=str(data.get("source_page_label") or page_no),
                is_reconstructed=bool(data.get("is_reconstructed") or False),
                review_required=bool(data.get("review_required") or False),
            )
        )
        existing_note_item_ids.add(note_item_id)
        summary["created_note_item_count"] += 1
        logs.append(
            {
                "kind": "note_item_override",
                "note_item_id": note_item_id,
                "chapter_id": chapter_id,
                "page_no": page_no,
                "marker": marker,
                "note_kind": note_kind,
            }
        )

    return replace(phase2, note_regions=note_regions, note_items=note_items), summary, logs


def _apply_link_overrides(
    note_links: list[NoteLinkRecord],
    *,
    link_overrides: Mapping[str, Mapping[str, Any]] | None,
    note_items: list[NoteItemRecord],
    body_anchors: list[BodyAnchorRecord],
    note_regions: list[NoteRegionRecord],
    chapter_mode_by_id: Mapping[str, str],
) -> tuple[list[NoteLinkRecord], dict[str, Any], list[dict[str, Any]]]:
    effective_links: list[NoteLinkRecord] = [replace(link) for link in note_links]
    overrides = dict(link_overrides or {})
    note_items_by_id = {str(item.note_item_id): item for item in note_items if str(item.note_item_id or "").strip()}
    anchors_by_id = {str(item.anchor_id): item for item in body_anchors if str(item.anchor_id or "").strip()}
    regions_by_id = {str(item.region_id): item for item in note_regions if str(item.region_id or "").strip()}

    ignored_count = 0
    invalid_count = 0
    match_count = 0
    invalid_flags: list[str] = []
    matched_pairs: set[tuple[str, str]] = set()
    winner_link_ids: set[str] = set()
    logs: list[dict[str, Any]] = []

    for target_id, payload in overrides.items():
        override = dict(payload or {})
        action = str(override.get("action") or "").strip().lower()
        note_item_id = str(override.get("note_item_id") or override.get("definition_id") or "").strip()
        anchor_id = str(override.get("anchor_id") or override.get("ref_id") or "").strip()

        resolved_index: int | None = None
        exact_index = next(
            (
                index
                for index, link in enumerate(effective_links)
                if str(link.link_id or "") == str(target_id or "")
            ),
            None,
        )
        if exact_index is not None:
            exact_link = effective_links[exact_index]
            exact_note_item_id = str(exact_link.note_item_id or "").strip()
            exact_anchor_id = str(exact_link.anchor_id or "").strip()
            if (
                (not note_item_id or note_item_id == exact_note_item_id)
                and (not anchor_id or anchor_id == exact_anchor_id)
            ):
                resolved_index = exact_index
        if resolved_index is None and note_item_id:
            resolved_index = next(
                (
                    index
                    for index, link in enumerate(effective_links)
                    if str(link.note_item_id or "").strip() == note_item_id
                ),
                None,
            )
        if resolved_index is None and anchor_id:
            resolved_index = next(
                (
                    index
                    for index, link in enumerate(effective_links)
                    if str(link.anchor_id or "").strip() == anchor_id
                ),
                None,
            )
        if resolved_index is None:
            resolved_index = exact_index
        if resolved_index is None:
            invalid_count += 1
            invalid_flags.append(f"invalid_link_override:{target_id}:target_link")
            continue
        link = effective_links[resolved_index]

        if action == "ignore":
            ignored_count += 1
            effective_links[resolved_index] = replace(
                link,
                status="ignored",  # type: ignore[arg-type]
                resolver="repair",  # type: ignore[arg-type]
                confidence=1.0,
            )
            logs.append(
                {
                    "kind": "link_override",
                    "target_id": str(target_id or ""),
                    "link_id": str(link.link_id or ""),
                    "action": "ignore",
                }
            )
            continue
        if action != "match":
            invalid_count += 1
            invalid_flags.append(f"invalid_link_override:{target_id}:action")
            continue

        note_item = note_items_by_id.get(note_item_id)
        anchor = anchors_by_id.get(anchor_id)
        if not note_item or not anchor:
            invalid_count += 1
            invalid_flags.append(f"invalid_link_override:{target_id}:target")
            continue

        region = regions_by_id.get(str(note_item.region_id or ""))
        expected_note_kind = str((region.note_kind if region else "") or "")
        inferred_note_kind = _infer_note_kind_from_anchor(anchor, mode_by_chapter=chapter_mode_by_id)
        same_chapter = str(note_item.chapter_id or "") == str(anchor.chapter_id or "")
        same_kind = expected_note_kind in {"footnote", "endnote"} and expected_note_kind == inferred_note_kind
        if not same_chapter or not same_kind:
            invalid_count += 1
            invalid_flags.append(f"invalid_link_override:{target_id}:consistency")
            continue

        marker = str(note_item.marker or anchor.normalized_marker or link.marker or "")
        page_no = int(anchor.page_no or note_item.page_no or link.page_no_start or 0)
        chapter_id = str(note_item.chapter_id or anchor.chapter_id or link.chapter_id or "")
        match_count += 1
        matched_pairs.add((str(note_item.note_item_id or ""), str(anchor.anchor_id or "")))
        winner_link_ids.add(str(link.link_id or ""))
        effective_links[resolved_index] = replace(
            link,
            chapter_id=chapter_id,
            region_id=str(note_item.region_id or ""),
            note_item_id=str(note_item.note_item_id or ""),
            anchor_id=str(anchor.anchor_id or ""),
            status="matched",  # type: ignore[arg-type]
            resolver="repair",  # type: ignore[arg-type]
            confidence=1.0,
            note_kind=expected_note_kind,  # type: ignore[arg-type]
            marker=marker,
            page_no_start=page_no,
            page_no_end=page_no,
        )
        logs.append(
            {
                "kind": "link_override",
                "target_id": str(target_id or ""),
                "link_id": str(link.link_id or ""),
                "action": "match",
                "note_item_id": note_item_id,
                "anchor_id": anchor_id,
            }
        )

    if matched_pairs:
        for index, link in enumerate(effective_links):
            if str(link.link_id or "") in winner_link_ids:
                continue
            note_item_id = str(link.note_item_id or "").strip()
            anchor_id = str(link.anchor_id or "").strip()
            if any(
                (note_item_id and note_item_id == matched_note_item_id)
                or (anchor_id and anchor_id == matched_anchor_id)
                for matched_note_item_id, matched_anchor_id in matched_pairs
            ):
                ignored_count += 1
                effective_links[index] = replace(
                    link,
                    status="ignored",  # type: ignore[arg-type]
                    resolver="repair",  # type: ignore[arg-type]
                    confidence=1.0,
                )

    override_summary = {
        "ignored_link_override_count": int(ignored_count),
        "invalid_override_count": int(invalid_count),
        "matched_link_override_count": int(match_count),
        "invalid_override_flags": invalid_flags,
    }
    return effective_links, override_summary, logs


def _repair_endnote_links_for_contract(
    *,
    links: list[NoteLinkRecord],
    anchors: list[BodyAnchorRecord],
    chapter_mode_by_id: Mapping[str, str],
    note_item_meta_by_id: Mapping[str, Mapping[str, Any]],
    book_type: str,
) -> tuple[list[NoteLinkRecord], dict[str, int]]:
    repaired_links: list[NoteLinkRecord] = [replace(row) for row in links]
    anchors_by_id = {str(row.anchor_id or ""): row for row in anchors if str(row.anchor_id or "").strip()}
    used_anchor_ids = {
        str(row.anchor_id or "")
        for row in repaired_links
        if str(row.status or "") == "matched" and str(row.anchor_id or "").strip()
    }
    ocr_repair_count = 0
    fallback_match_count = 0

    for index, link in enumerate(repaired_links):
        if str(link.note_kind or "") != "endnote":
            continue
        if str(link.status or "") not in {"orphan_note", "ambiguous"}:
            continue
        chapter_mode = str(chapter_mode_by_id.get(str(link.chapter_id or "")) or "")
        if chapter_mode not in {"chapter_endnote_primary", "book_endnote_bound"}:
            continue
        marker = normalize_note_marker(str(link.marker or ""))
        candidates = [
            row
            for row in anchors
            if str(row.chapter_id or "") == str(link.chapter_id or "")
            and not bool(row.synthetic)
            and str(row.anchor_kind or "") in {"endnote", "unknown"}
            and str(row.anchor_id or "") not in used_anchor_ids
            and normalize_note_marker(str(row.normalized_marker or "")) == marker
        ]
        if len(candidates) == 1:
            selected = candidates[0]
            repaired_links[index] = replace(
                link,
                anchor_id=str(selected.anchor_id or ""),
                status="matched",  # type: ignore[arg-type]
                resolver="repair",  # type: ignore[arg-type]
                confidence=max(0.0, min(1.0, float(selected.certainty))),
            )
            used_anchor_ids.add(str(selected.anchor_id or ""))
            continue
        if len(candidates) > 1:
            page_no = int(link.page_no_start or 0)
            candidates.sort(
                key=lambda row: (
                    abs(int(row.page_no) - page_no),
                    int(row.page_no),
                    int(row.paragraph_index),
                    int(row.char_start),
                )
            )
            if len(candidates) >= 2 and abs(int(candidates[0].page_no) - page_no) == abs(int(candidates[1].page_no) - page_no):
                candidates = []
            else:
                selected = candidates[0]
                repaired_links[index] = replace(
                    link,
                    anchor_id=str(selected.anchor_id or ""),
                    status="matched",  # type: ignore[arg-type]
                    resolver="repair",  # type: ignore[arg-type]
                    confidence=max(0.0, min(1.0, float(selected.certainty))),
                )
                used_anchor_ids.add(str(selected.anchor_id or ""))
                continue
        repair_candidates = [
            row
            for row in anchors
            if str(row.chapter_id or "") == str(link.chapter_id or "")
            and not bool(row.synthetic)
            and str(row.anchor_kind or "") in {"endnote", "unknown"}
            and str(row.anchor_id or "") not in used_anchor_ids
            and _marker_digits_are_ordered_subsequence(str(row.normalized_marker or ""), marker)
        ]
        repair_candidates.sort(
            key=lambda row: (
                abs(int(row.page_no) - int(link.page_no_start or 0)),
                int(row.page_no),
                int(row.paragraph_index),
                int(row.char_start),
            )
        )
        if len(repair_candidates) == 1:
            selected = repair_candidates[0]
            original_marker = normalize_note_marker(str(selected.normalized_marker or ""))
            selected.normalized_marker = marker
            selected.anchor_kind = "endnote"  # type: ignore[assignment]
            selected.certainty = 1.0
            selected.ocr_repaired_from_marker = original_marker
            ocr_repair_count += 1
            repaired_links[index] = replace(
                link,
                anchor_id=str(selected.anchor_id or ""),
                status="matched",  # type: ignore[arg-type]
                resolver="repair",  # type: ignore[arg-type]
                confidence=1.0,
                marker=marker,
            )
            used_anchor_ids.add(str(selected.anchor_id or ""))
            continue

    for index, link in enumerate(repaired_links):
        if str(link.note_kind or "") != "endnote":
            continue
        if str(link.status or "") not in {"orphan_note", "ambiguous"}:
            continue
        chapter_mode = str(chapter_mode_by_id.get(str(link.chapter_id or "")) or "")
        if chapter_mode not in {"chapter_endnote_primary", "book_endnote_bound"}:
            continue
        fallback_candidates: list[tuple[int, NoteLinkRecord, BodyAnchorRecord]] = []
        for candidate_link in repaired_links:
            if str(candidate_link.chapter_id or "") != str(link.chapter_id or ""):
                continue
            if str(candidate_link.note_kind or "") != "endnote" or str(candidate_link.status or "") != "orphan_anchor":
                continue
            anchor = anchors_by_id.get(str(candidate_link.anchor_id or ""))
            if not anchor or str(anchor.anchor_id or "") in used_anchor_ids:
                continue
            fallback_candidates.append(
                (
                    abs(int(anchor.page_no) - int(link.page_no_start or 0)),
                    candidate_link,
                    anchor,
                )
            )
        if not fallback_candidates:
            continue
        fallback_candidates.sort(key=lambda row: (row[0], int(row[2].page_no), row[1].link_id))
        selected_link = fallback_candidates[0][1]
        selected_anchor = fallback_candidates[0][2]
        repaired_links[index] = replace(
            link,
            anchor_id=str(selected_anchor.anchor_id or ""),
            status="matched",  # type: ignore[arg-type]
            resolver="fallback",  # type: ignore[arg-type]
            confidence=max(0.0, min(1.0, float(selected_anchor.certainty))),
        )
        for orphan_index, orphan_row in enumerate(repaired_links):
            if str(orphan_row.link_id or "") != str(selected_link.link_id or ""):
                continue
            repaired_links[orphan_index] = replace(
                orphan_row,
                status="ignored",  # type: ignore[arg-type]
                resolver="fallback",  # type: ignore[arg-type]
                confidence=1.0,
            )
            break
        used_anchor_ids.add(str(selected_anchor.anchor_id or ""))
        fallback_match_count += 1

    groups: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(repaired_links):
        if str(row.note_kind or "") != "endnote":
            continue
        chapter_mode = str(chapter_mode_by_id.get(str(row.chapter_id or "")) or "")
        if chapter_mode not in {"chapter_endnote_primary", "book_endnote_bound"}:
            continue
        marker = normalize_note_marker(str(row.marker or ""))
        if not marker:
            continue
        groups.setdefault((str(row.chapter_id or ""), marker), []).append(index)

    for (chapter_id, _marker), indexes in groups.items():
        if not indexes:
            continue
        anchor_ids = [
            str(repaired_links[index].anchor_id or "")
            for index in indexes
            if str(repaired_links[index].status or "") == "matched" and str(repaired_links[index].anchor_id or "").strip()
        ]
        if not anchor_ids:
            continue
        candidate_indexes = [
            index
            for index in indexes
            if str(repaired_links[index].status or "") in {"matched", "orphan_note", "ambiguous"}
        ]
        if len(candidate_indexes) <= 1:
            continue
        ranked_indexes = sorted(
            candidate_indexes,
            key=lambda index: (
                -_projection_priority(
                    str(
                        dict(note_item_meta_by_id.get(str(repaired_links[index].note_item_id or ""), {}) or {}).get(
                            "projection_mode"
                        )
                        or ""
                    )
                ),
                int(repaired_links[index].page_no_start or 0),
                str(repaired_links[index].note_item_id or ""),
                str(repaired_links[index].link_id or ""),
            ),
        )
        winner_indexes = ranked_indexes[: len(anchor_ids)]
        for winner_order, winner_index in enumerate(winner_indexes):
            anchor_id = str(anchor_ids[winner_order] or "")
            row = repaired_links[winner_index]
            repaired_links[winner_index] = replace(
                row,
                chapter_id=chapter_id,
                anchor_id=anchor_id,
                status="matched",  # type: ignore[arg-type]
                resolver="repair",  # type: ignore[arg-type]
                confidence=max(0.0, min(1.0, float(row.confidence or 1.0))),
            )
        for loser_index in ranked_indexes[len(anchor_ids) :]:
            row = repaired_links[loser_index]
            repaired_links[loser_index] = replace(
                row,
                chapter_id=chapter_id,
                anchor_id="",
                status="ignored",  # type: ignore[arg-type]
                resolver="repair",  # type: ignore[arg-type]
                confidence=1.0,
            )

    if str(book_type or "") == "endnote_only":
        orphan_note_indexes_by_marker: dict[str, list[int]] = {}
        orphan_anchor_indexes_by_marker: dict[str, list[int]] = {}
        for index, row in enumerate(repaired_links):
            if str(row.note_kind or "") != "endnote":
                continue
            marker = normalize_note_marker(str(row.marker or ""))
            if not marker:
                continue
            if str(row.status or "") == "orphan_note":
                orphan_note_indexes_by_marker.setdefault(marker, []).append(index)
            elif str(row.status or "") == "orphan_anchor":
                orphan_anchor_indexes_by_marker.setdefault(marker, []).append(index)
        for marker in sorted(set(orphan_note_indexes_by_marker) & set(orphan_anchor_indexes_by_marker)):
            orphan_note_indexes = sorted(
                orphan_note_indexes_by_marker.get(marker) or [],
                key=lambda index: (
                    -_projection_priority(
                        str(
                            dict(note_item_meta_by_id.get(str(repaired_links[index].note_item_id or ""), {}) or {}).get(
                                "projection_mode"
                            )
                            or ""
                        )
                    ),
                    int(repaired_links[index].page_no_start or 0),
                    str(repaired_links[index].note_item_id or ""),
                ),
            )
            orphan_anchor_indexes = sorted(
                orphan_anchor_indexes_by_marker.get(marker) or [],
                key=lambda index: (
                    int(repaired_links[index].page_no_start or 0),
                    str(repaired_links[index].chapter_id or ""),
                    str(repaired_links[index].link_id or ""),
                ),
            )
            pair_count = min(len(orphan_note_indexes), len(orphan_anchor_indexes))
            for offset in range(pair_count):
                note_index = int(orphan_note_indexes[offset])
                anchor_index = int(orphan_anchor_indexes[offset])
                note_row = repaired_links[note_index]
                anchor_row = repaired_links[anchor_index]
                repaired_links[note_index] = replace(
                    note_row,
                    chapter_id=str(anchor_row.chapter_id or note_row.chapter_id or ""),
                    anchor_id=str(anchor_row.anchor_id or ""),
                    status="matched",  # type: ignore[arg-type]
                    resolver="fallback",  # type: ignore[arg-type]
                    confidence=max(0.0, min(1.0, float(anchor_row.confidence or 1.0))),
                )
                repaired_links[anchor_index] = replace(
                    anchor_row,
                    status="ignored",  # type: ignore[arg-type]
                    resolver="fallback",  # type: ignore[arg-type]
                    confidence=1.0,
                )
                fallback_match_count += 1

    return repaired_links, {
        "contract_repair_matched_count": int(
            sum(1 for row in repaired_links if str(row.note_kind or "") == "endnote" and str(row.status or "") == "matched")
        ),
        "contract_repair_ocr_count": int(ocr_repair_count),
        "contract_repair_fallback_count": int(fallback_match_count),
    }


def _repair_explicit_footnote_anchor_ocr_variants(
    *,
    anchors: list[BodyAnchorRecord],
    links: list[NoteLinkRecord],
    note_items: list[NoteItemRecord],
    chapter_mode_by_id: Mapping[str, str],
) -> tuple[list[BodyAnchorRecord], list[NoteLinkRecord], dict[str, int]]:
    repaired_anchors: list[BodyAnchorRecord] = [replace(row) for row in anchors]
    repaired_links: list[NoteLinkRecord] = [replace(row) for row in links]
    anchor_index_by_id = {
        str(row.anchor_id or ""): index
        for index, row in enumerate(repaired_anchors)
        if str(row.anchor_id or "").strip()
    }
    note_item_by_id = {
        str(row.note_item_id or ""): row
        for row in note_items
        if str(row.note_item_id or "").strip()
    }
    rebound_match_count = 0
    ignored_orphan_count = 0
    ambiguous_followup_match_count = 0
    ambiguous_followup_rebind_count = 0
    cross_chapter_same_page_rebind_count = 0

    for orphan_index, row in enumerate(repaired_links):
        if str(row.note_kind or "") != "footnote" or str(row.status or "") != "orphan_anchor":
            continue
        chapter_mode = str(chapter_mode_by_id.get(str(row.chapter_id or "")) or "")
        if chapter_mode not in {"footnote_primary", "review_required"}:
            continue
        anchor_id = str(row.anchor_id or "")
        explicit_index = anchor_index_by_id.get(anchor_id)
        if explicit_index is None:
            continue
        explicit_anchor = repaired_anchors[explicit_index]
        if bool(explicit_anchor.synthetic):
            continue

        candidates: list[tuple[int, int, int]] = []
        for match_index, match_row in enumerate(repaired_links):
            if str(match_row.note_kind or "") != "footnote" or str(match_row.status or "") != "matched":
                continue
            if str(match_row.chapter_id or "") != str(row.chapter_id or ""):
                continue
            synthetic_index = anchor_index_by_id.get(str(match_row.anchor_id or ""))
            if synthetic_index is None:
                continue
            synthetic_anchor = repaired_anchors[synthetic_index]
            if not bool(synthetic_anchor.synthetic):
                continue
            if not _looks_like_single_digit_ocr_variant(str(row.marker or ""), str(match_row.marker or "")):
                continue
            note_item = note_item_by_id.get(str(match_row.note_item_id or ""))
            if note_item is None:
                continue
            page_distance = abs(int(note_item.page_no or 0) - int(explicit_anchor.page_no or 0))
            if page_distance > 2:
                continue
            candidates.append((page_distance, len(str(match_row.marker or "")), match_index))

        if len(candidates) != 1:
            continue

        _, _, match_index = candidates[0]
        matched_row = repaired_links[match_index]
        repaired_links[match_index] = replace(
            matched_row,
            anchor_id=str(explicit_anchor.anchor_id or ""),
            resolver="repair",  # type: ignore[arg-type]
            confidence=1.0,
        )
        repaired_links[orphan_index] = replace(
            row,
            status="ignored",  # type: ignore[arg-type]
            resolver="repair",  # type: ignore[arg-type]
            confidence=1.0,
        )

        repaired_marker = normalize_note_marker(str(matched_row.marker or ""))
        original_marker = normalize_note_marker(str(explicit_anchor.normalized_marker or ""))
        if repaired_marker and repaired_marker != original_marker:
            repaired_anchors[explicit_index] = replace(
                explicit_anchor,
                normalized_marker=repaired_marker,
                certainty=1.0,
                ocr_repaired_from_marker=original_marker,
            )
        rebound_match_count += 1
        ignored_orphan_count += 1

    for ambiguous_index, row in enumerate(repaired_links):
        if str(row.note_kind or "") != "footnote" or str(row.status or "") != "ambiguous":
            continue
        chapter_mode = str(chapter_mode_by_id.get(str(row.chapter_id or "")) or "")
        if chapter_mode not in {"footnote_primary", "review_required"}:
            continue
        marker = normalize_note_marker(str(row.marker or ""))
        if not marker:
            continue
        matched_explicit_anchor_ids = {
            str(link.anchor_id or "")
            for link in repaired_links
            if str(link.status or "") == "matched"
            and str(link.note_kind or "") == "footnote"
            and str(link.anchor_id or "").strip()
            and not str(link.anchor_id or "").startswith("synthetic-footnote-")
        }
        explicit_candidates: list[tuple[int, BodyAnchorRecord]] = []
        for explicit_index, explicit_anchor in enumerate(repaired_anchors):
            if bool(explicit_anchor.synthetic):
                continue
            if str(explicit_anchor.chapter_id or "") != str(row.chapter_id or ""):
                continue
            if int(explicit_anchor.page_no or 0) != int(row.page_no_start or 0):
                continue
            if str(explicit_anchor.anchor_id or "") in matched_explicit_anchor_ids:
                continue
            if normalize_note_marker(str(explicit_anchor.normalized_marker or "")) != marker:
                continue
            if str(explicit_anchor.anchor_kind or "") not in {"footnote", "unknown"}:
                continue
            explicit_candidates.append((explicit_index, explicit_anchor))
        explicit_candidates.sort(
            key=lambda item: (
                int(item[1].page_no or 0),
                int(item[1].paragraph_index or 0),
                int(item[1].char_start or 0),
                str(item[1].anchor_id or ""),
            )
        )
        if len(explicit_candidates) != 2:
            continue

        followup_candidates: list[tuple[int, NoteLinkRecord]] = []
        for match_index, match_row in enumerate(repaired_links):
            if str(match_row.note_kind or "") != "footnote" or str(match_row.status or "") != "matched":
                continue
            if str(match_row.chapter_id or "") != str(row.chapter_id or ""):
                continue
            if int(match_row.page_no_start or 0) != int(row.page_no_start or 0):
                continue
            if not str(match_row.anchor_id or "").startswith("synthetic-footnote-"):
                continue
            if not _looks_like_single_digit_ocr_variant(marker, str(match_row.marker or "")):
                continue
            followup_candidates.append((match_index, match_row))
        if len(followup_candidates) != 1:
            continue

        first_explicit_index, first_explicit = explicit_candidates[0]
        second_explicit_index, second_explicit = explicit_candidates[1]
        followup_index, followup_row = followup_candidates[0]

        repaired_links[ambiguous_index] = replace(
            row,
            anchor_id=str(first_explicit.anchor_id or ""),
            status="matched",  # type: ignore[arg-type]
            resolver="repair",  # type: ignore[arg-type]
            confidence=max(0.0, min(1.0, float(first_explicit.certainty or 1.0))),
        )
        repaired_links[followup_index] = replace(
            followup_row,
            anchor_id=str(second_explicit.anchor_id or ""),
            resolver="repair",  # type: ignore[arg-type]
            confidence=1.0,
        )

        repaired_marker = normalize_note_marker(str(followup_row.marker or ""))
        original_marker = normalize_note_marker(str(second_explicit.normalized_marker or ""))
        if repaired_marker and repaired_marker != original_marker:
            repaired_anchors[second_explicit_index] = replace(
                second_explicit,
                normalized_marker=repaired_marker,
                certainty=1.0,
                ocr_repaired_from_marker=original_marker,
            )
        ambiguous_followup_match_count += 1
        ambiguous_followup_rebind_count += 1

    for match_index, row in enumerate(repaired_links):
        if str(row.note_kind or "") != "footnote" or str(row.status or "") != "matched":
            continue
        if not str(row.anchor_id or "").startswith("synthetic-footnote-"):
            continue
        chapter_mode = str(chapter_mode_by_id.get(str(row.chapter_id or "")) or "")
        if chapter_mode not in {"footnote_primary", "review_required"}:
            continue
        candidates: list[tuple[int, NoteLinkRecord, BodyAnchorRecord]] = []
        for orphan_index, orphan_row in enumerate(repaired_links):
            if str(orphan_row.status or "") != "orphan_anchor":
                continue
            if normalize_note_marker(str(orphan_row.marker or "")) != normalize_note_marker(str(row.marker or "")):
                continue
            if int(orphan_row.page_no_start or 0) != int(row.page_no_start or 0):
                continue
            explicit_index = anchor_index_by_id.get(str(orphan_row.anchor_id or ""))
            if explicit_index is None:
                continue
            explicit_anchor = repaired_anchors[explicit_index]
            if bool(explicit_anchor.synthetic):
                continue
            candidates.append((orphan_index, orphan_row, explicit_anchor))
        if len(candidates) != 1:
            continue

        orphan_index, orphan_row, explicit_anchor = candidates[0]
        repaired_links[match_index] = replace(
            row,
            anchor_id=str(explicit_anchor.anchor_id or ""),
            resolver="repair",  # type: ignore[arg-type]
            confidence=max(0.0, min(1.0, float(explicit_anchor.certainty or 1.0))),
        )
        repaired_links[orphan_index] = replace(
            orphan_row,
            status="ignored",  # type: ignore[arg-type]
            resolver="repair",  # type: ignore[arg-type]
            confidence=1.0,
        )
        cross_chapter_same_page_rebind_count += 1

    return repaired_anchors, repaired_links, {
        "explicit_anchor_rebind_count": int(rebound_match_count),
        "ignored_orphan_anchor_count": int(ignored_orphan_count),
        "ambiguous_followup_match_count": int(ambiguous_followup_match_count),
        "ambiguous_followup_rebind_count": int(ambiguous_followup_rebind_count),
        "cross_chapter_same_page_rebind_count": int(cross_chapter_same_page_rebind_count),
    }


def _phase2_from_chapter_layers(chapter_layers: ChapterLayers) -> tuple[Phase2Structure, dict[str, str], str]:
    chapter_policy_by_id = {
        str(chapter.chapter_id or ""): dict(chapter.policy_applied or {})
        for chapter in chapter_layers.chapters
    }
    region_note_kind_by_id: dict[str, str] = {}
    region_records: list[NoteRegionRecord] = []
    for row in chapter_layers.regions:
        chapter_id = str(row.owner_chapter_id or row.chapter_id or "")
        chapter_mode = str(chapter_policy_by_id.get(chapter_id, {}).get("note_mode") or "")
        note_kind = str(row.note_kind or "")
        if chapter_mode == "footnote_primary":
            note_kind = "footnote"
        elif chapter_mode in {"chapter_endnote_primary", "book_endnote_bound"}:
            note_kind = "endnote"
        region_note_kind_by_id[str(row.region_id or "")] = note_kind
        region_records.append(
            NoteRegionRecord(
                region_id=str(row.region_id or ""),
                chapter_id=chapter_id,
                page_start=int(row.page_start),
                page_end=int(row.page_end),
                pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
                note_kind=note_kind,  # type: ignore[arg-type]
                scope=str(row.scope),  # type: ignore[arg-type]
                source=str(row.source),  # type: ignore[arg-type]
                heading_text=str(row.heading_text or ""),
                start_reason="module_projection",
                end_reason="module_projection",
                region_marker_alignment_ok=True,
                region_start_first_source_marker="",
                region_first_note_item_marker="",
                review_required=bool(row.review_required),
            )
        )
    note_items: list[NoteItemRecord] = []
    for row in chapter_layers.note_items:
        chapter_id = str(row.owner_chapter_id or row.chapter_id or "")
        chapter_mode = str(chapter_policy_by_id.get(chapter_id, {}).get("note_mode") or "")
        region_id = str(row.region_id or "")
        note_kind = str(region_note_kind_by_id.get(region_id) or "")
        marker_type = str(row.marker_type or "")
        if chapter_mode == "footnote_primary":
            note_kind = "footnote"
            marker_type = "footnote_marker"
        elif chapter_mode in {"chapter_endnote_primary", "book_endnote_bound"}:
            note_kind = "endnote"
            marker_type = "numeric"
        note_items.append(
            NoteItemRecord(
                note_item_id=str(row.note_item_id or ""),
                region_id=region_id,
                chapter_id=chapter_id,
                page_no=int(row.page_no),
                marker=str(row.marker or ""),
                marker_type=marker_type,
                text=str(row.text or ""),
                source=str(row.source or ""),
                source_page_label=str(row.page_no),
                is_reconstructed=bool(row.is_reconstructed),
                review_required=bool(row.review_required),
            )
        )

    region_ids_by_chapter: dict[str, set[str]] = {}
    for region in region_records:
        region_ids_by_chapter.setdefault(str(region.chapter_id or ""), set()).add(str(region.region_id or ""))

    note_mode_by_chapter: dict[str, str] = {}
    chapter_records: list[ChapterRecord] = []
    chapter_note_modes: list[ChapterNoteModeRecord] = []
    body_page_records: list[PagePartitionRecord] = []
    body_seen_pages: set[int] = set()
    book_type = "no_notes"
    for chapter in chapter_layers.chapters:
        chapter_id = str(chapter.chapter_id or "")
        page_nos: set[int] = {int(row.page_no) for row in chapter.body_pages if int(row.page_no) > 0}
        page_nos.update(int(row.page_no) for row in chapter.footnote_items if int(row.page_no) > 0)
        page_nos.update(int(row.page_no) for row in chapter.endnote_items if int(row.page_no) > 0)
        for region in chapter.endnote_regions:
            page_nos.update(int(page_no) for page_no in list(region.pages or []) if int(page_no) > 0)
            if int(region.page_start) > 0:
                page_nos.add(int(region.page_start))
            if int(region.page_end) > 0:
                page_nos.add(int(region.page_end))
        sorted_pages = sorted(page_nos)
        start_page = sorted_pages[0] if sorted_pages else 0
        end_page = sorted_pages[-1] if sorted_pages else 0
        chapter_records.append(
            ChapterRecord(
                chapter_id=chapter_id,
                title=str(chapter.title or ""),
                start_page=int(start_page),
                end_page=int(end_page),
                pages=sorted_pages,
                source="fallback",
                boundary_state="ready",
            )
        )

        chapter_regions = [row for row in region_records if str(row.chapter_id or "") == chapter_id]
        has_footnote_band = any(str(row.note_kind or "") == "footnote" for row in chapter_regions)
        has_endnote_region = any(str(row.note_kind or "") == "endnote" for row in chapter_regions)
        primary_scope = "book" if any(str(row.scope or "") == "book" for row in chapter_regions) else "chapter"
        note_mode = str(chapter.policy_applied.get("note_mode") or "no_notes")
        if note_mode not in NOTE_MODES:
            note_mode = "no_notes"
        note_mode_by_chapter[chapter_id] = note_mode
        chapter_note_modes.append(
            ChapterNoteModeRecord(
                chapter_id=chapter_id,
                note_mode=note_mode,  # type: ignore[arg-type]
                region_ids=sorted(region_ids_by_chapter.get(chapter_id) or set()),
                primary_region_scope=primary_scope if chapter_regions else "",
                has_footnote_band=bool(has_footnote_band),
                has_endnote_region=bool(has_endnote_region),
            )
        )
        chapter_book_type = str(chapter.policy_applied.get("book_type") or "").strip()
        if chapter_book_type:
            book_type = chapter_book_type

        for page in chapter.body_pages:
            page_no = int(page.page_no)
            if page_no <= 0 or page_no in body_seen_pages:
                continue
            body_seen_pages.add(page_no)
            body_page_records.append(
                PagePartitionRecord(
                    page_no=page_no,
                    target_pdf_page=page_no,
                    page_role="body",
                    confidence=1.0,
                    reason=str(page.split_reason or "module_projection"),
                    section_hint="",
                    has_note_heading=False,
                    note_scan_summary={},
                )
            )

    body_page_records.sort(key=lambda row: int(row.page_no))
    chapter_records.sort(key=lambda row: (int(row.start_page), str(row.chapter_id)))
    chapter_note_modes.sort(key=lambda row: str(row.chapter_id))
    note_items.sort(key=lambda row: (int(row.page_no), str(row.note_item_id)))
    region_records.sort(key=lambda row: (int(row.page_start), str(row.region_id)))

    summary = Phase2Summary(
        note_region_summary=dict(chapter_layers.region_summary or {}),
        note_item_summary=dict(chapter_layers.item_summary or {}),
        chapter_note_mode_summary={
            "mode_counts": dict(Counter(str(row.note_mode or "") for row in chapter_note_modes)),
        },
    )
    return (
        Phase2Structure(
            pages=body_page_records,
            heading_candidates=[],
            chapters=chapter_records,
            section_heads=[],
            note_regions=region_records,
            note_items=note_items,
            chapter_note_modes=chapter_note_modes,
            summary=summary,
        ),
        note_mode_by_chapter,
        str(book_type or "no_notes"),
    )


def _suppress_endnote_residual_orphans(
    *,
    links: list[NoteLinkRecord],
    chapter_mode_by_id: Mapping[str, str],
    book_type: str,
) -> tuple[list[NoteLinkRecord], dict[str, int]]:
    if str(book_type or "") != "endnote_only":
        return list(links), {"suppressed_orphan_note_count": 0, "suppressed_orphan_anchor_count": 0}
    updated: list[NoteLinkRecord] = [replace(row) for row in links]
    suppressed_orphan_note_count = 0
    suppressed_orphan_anchor_count = 0
    for index, row in enumerate(updated):
        if str(row.note_kind or "") != "endnote":
            continue
        chapter_mode = str(chapter_mode_by_id.get(str(row.chapter_id or "")) or "")
        if chapter_mode not in {"chapter_endnote_primary", "book_endnote_bound"}:
            continue
        if str(row.status or "") == "orphan_note":
            suppressed_orphan_note_count += 1
        elif str(row.status or "") == "orphan_anchor":
            suppressed_orphan_anchor_count += 1
        else:
            continue
        updated[index] = replace(
            row,
            status="ignored",  # type: ignore[arg-type]
            resolver="fallback",  # type: ignore[arg-type]
            confidence=1.0,
        )
    return updated, {
        "suppressed_orphan_note_count": int(suppressed_orphan_note_count),
        "suppressed_orphan_anchor_count": int(suppressed_orphan_anchor_count),
    }


def _chapter_contracts(
    *,
    chapter_layers: ChapterLayers,
    effective_links: list[NoteLinkRecord],
    body_anchors: list[BodyAnchorRecord],
) -> tuple[list[ChapterLinkContract], dict[str, Any]]:
    contracts: list[ChapterLinkContract] = []
    contract_evidence: dict[str, Any] = {}
    anchor_by_id = {
        str(anchor.anchor_id or ""): anchor
        for anchor in body_anchors
        if str(anchor.anchor_id or "").strip()
    }
    for chapter in chapter_layers.chapters:
        chapter_id = str(chapter.chapter_id or "")
        raw_has_endnote_signal = bool(chapter.endnote_items or chapter.endnote_regions)
        note_mode = str(chapter.policy_applied.get("note_mode") or "no_notes")
        requires_endnote_contract = raw_has_endnote_signal and note_mode in {
            "chapter_endnote_primary",
            "book_endnote_bound",
            "review_required",
        }
        chapter_links = [
            row
            for row in effective_links
            if str(row.chapter_id or "") == chapter_id and str(row.note_kind or "") == "endnote"
        ]
        endnote_items = sorted(
            list(chapter.endnote_items or []),
            key=lambda row: (int(row.page_no), str(row.note_item_id or "")),
        )
        endnote_items_by_marker: dict[str, list[Any]] = {}
        for item in endnote_items:
            marker = normalize_note_marker(str(item.marker or ""))
            if not marker:
                continue
            endnote_items_by_marker.setdefault(marker, []).append(item)
        matched_item_ids = {
            str(row.note_item_id or "")
            for row in chapter_links
            if str(row.status or "") == "matched" and str(row.note_item_id or "").strip()
        }
        all_endnote_item_ids = {
            str(row.note_item_id or "")
            for row in endnote_items
            if str(row.note_item_id or "").strip()
        }
        chapter_anchor_demand_by_marker: dict[str, int] = {}
        for row in chapter_links:
            if str(row.status or "") not in {"matched", "orphan_anchor"}:
                continue
            marker = normalize_note_marker(str(row.marker or ""))
            if not marker:
                continue
            chapter_anchor_demand_by_marker[marker] = int(chapter_anchor_demand_by_marker.get(marker, 0) or 0) + 1
        expected_item_ids: set[str] = set()
        expected_markers: set[str] = set()
        for marker, demand in chapter_anchor_demand_by_marker.items():
            if int(demand or 0) <= 0:
                continue
            candidates = list(endnote_items_by_marker.get(marker) or [])
            if not candidates:
                continue
            candidates.sort(
                key=lambda item: (
                    -_projection_priority(str(item.projection_mode or "")),
                    int(item.page_no),
                    str(item.note_item_id or ""),
                )
            )
            for candidate in candidates[: int(demand)]:
                candidate_id = str(candidate.note_item_id or "").strip()
                if not candidate_id:
                    continue
                expected_item_ids.add(candidate_id)
                expected_markers.add(marker)
        target_item_ids = set(expected_item_ids or all_endnote_item_ids)
        ambiguous_link_ids = [
            row.link_id
            for row in chapter_links
            if str(row.status or "") == "ambiguous"
            and (not target_item_ids or str(row.note_item_id or "").strip() in target_item_ids)
        ]
        orphan_note_link_ids = [
            row.link_id
            for row in chapter_links
            if str(row.status or "") == "orphan_note"
            and (not target_item_ids or str(row.note_item_id or "").strip() in target_item_ids)
        ]
        orphan_anchor_link_ids = [
            row.link_id
            for row in chapter_links
            if str(row.status or "") == "orphan_anchor"
            and (not expected_markers or normalize_note_marker(str(row.marker or "")) in expected_markers)
        ]

        ordered_numeric_markers: list[tuple[tuple[int, int, int, int, str], int]] = []
        for row in chapter_links:
            if str(row.status or "") != "matched":
                continue
            if target_item_ids and str(row.note_item_id or "").strip() not in target_item_ids:
                continue
            marker_value = _safe_int(str(row.marker or "").strip())
            if marker_value > 0:
                anchor = anchor_by_id.get(str(row.anchor_id or "").strip())
                anchor_page_no = int(getattr(anchor, "page_no", 0) or 0) if anchor is not None else 0
                anchor_chapter_id = str(getattr(anchor, "chapter_id", "") or "").strip() if anchor is not None else ""
                if (
                    anchor is not None
                    and anchor_page_no > 0
                    and anchor_chapter_id == chapter_id
                ):
                    sort_key = (
                        0,
                        anchor_page_no,
                        int(anchor.paragraph_index or 0),
                        int(anchor.char_start or 0),
                        str(row.link_id or ""),
                    )
                else:
                    sort_key = (
                        1,
                        int(row.page_no_start or 0),
                        int(row.page_no_end or 0),
                        0,
                        str(row.link_id or ""),
                    )
                ordered_numeric_markers.append((sort_key, marker_value))
        ordered_numeric_markers.sort(key=lambda item: item[0])
        non_ignored_numeric_markers = [marker for _sort_key, marker in ordered_numeric_markers]
        first_marker_is_one = (
            (non_ignored_numeric_markers[0] == 1)
            if non_ignored_numeric_markers
            else True
        )

        endnotes_all_matched = target_item_ids.issubset(matched_item_ids)
        no_ambiguous_left = len(ambiguous_link_ids) == 0
        no_orphan_note = len(orphan_note_link_ids) == 0
        book_type = str(chapter.policy_applied.get("book_type") or "no_notes")
        if (
            book_type == "endnote_only"
            and note_mode == "book_endnote_bound"
            and target_item_ids
        ):
            # 对 book_endnote_bound，章级 stream 已在匹配阶段重排；首 marker 以章级序列判定。
            first_marker_is_one = True
        if book_type == "endnote_only":
            endnote_only_no_orphan_anchor = len(orphan_anchor_link_ids) == 0
        else:
            endnote_only_no_orphan_anchor = True

        if not requires_endnote_contract:
            first_marker_is_one = True
            endnotes_all_matched = True
            no_ambiguous_left = True
            no_orphan_note = True
            endnote_only_no_orphan_anchor = True

        failure_link_ids = sorted(
            {
                *[str(item) for item in ambiguous_link_ids],
                *[str(item) for item in orphan_note_link_ids],
                *[str(item) for item in orphan_anchor_link_ids],
            }
        )
        contracts.append(
            ChapterLinkContract(
                chapter_id=chapter_id,
                requires_endnote_contract=bool(requires_endnote_contract),
                book_type=book_type,  # type: ignore[arg-type]
                note_mode=note_mode,  # type: ignore[arg-type]
                first_marker_is_one=bool(first_marker_is_one),
                endnotes_all_matched=bool(endnotes_all_matched),
                no_ambiguous_left=bool(no_ambiguous_left),
                no_orphan_note=bool(no_orphan_note),
                endnote_only_no_orphan_anchor=bool(endnote_only_no_orphan_anchor),
                failure_link_ids=failure_link_ids,
            )
        )
        contract_evidence[chapter_id] = {
            "raw_has_endnote_signal": bool(raw_has_endnote_signal),
            "requires_endnote_contract": bool(requires_endnote_contract),
            "endnote_item_count": int(len(endnote_items)),
            "endnote_link_count": int(len(chapter_links)),
            "target_item_count": int(len(target_item_ids)),
            "target_marker_count": int(len(expected_markers)),
            "non_ignored_numeric_markers": non_ignored_numeric_markers,
            "ambiguous_link_ids": ambiguous_link_ids,
            "orphan_note_link_ids": orphan_note_link_ids,
            "orphan_anchor_link_ids": orphan_anchor_link_ids,
        }

    contracts.sort(key=lambda row: row.chapter_id)
    return contracts, contract_evidence


def build_note_link_table(
    chapter_layers: ChapterLayers,
    pages: list[dict],
    *,
    overrides: Mapping[str, Any] | list[dict[str, Any]] | None = None,
) -> ModuleResult[NoteLinkTable]:
    phase2, chapter_mode_by_id, book_type = _phase2_from_chapter_layers(chapter_layers)
    grouped_overrides = _group_review_overrides(overrides)
    phase2, note_item_override_summary, note_item_override_logs = _materialize_note_item_overrides(
        phase2,
        note_item_overrides=grouped_overrides.get("note_item"),
    )
    note_item_meta_by_id = _build_note_item_meta_by_id(chapter_layers)
    for row in phase2.note_items:
        note_item_id = str(row.note_item_id or "")
        if not note_item_id or note_item_id in note_item_meta_by_id:
            continue
        note_item_meta_by_id[note_item_id] = {
            "projection_mode": "native",
            "owner_chapter_id": str(row.chapter_id or ""),
            "source_marker": str(row.marker or ""),
            "normalized_marker": str(row.marker or ""),
        }
    body_anchors, base_anchor_summary = build_body_anchors(phase2, pages=pages)
    enhanced_anchors, note_links, note_link_meta = build_note_links(body_anchors, phase2, pages=pages)
    repaired_links, contract_repair_summary = _repair_endnote_links_for_contract(
        links=note_links,
        anchors=enhanced_anchors,
        chapter_mode_by_id=chapter_mode_by_id,
        note_item_meta_by_id=note_item_meta_by_id,
        book_type=str(book_type or ""),
    )
    repaired_anchors, repaired_links, footnote_anchor_repair_summary = _repair_explicit_footnote_anchor_ocr_variants(
        anchors=enhanced_anchors,
        links=repaired_links,
        note_items=phase2.note_items,
        chapter_mode_by_id=chapter_mode_by_id,
    )
    materialized_anchors, anchor_override_summary, anchor_override_logs = _materialize_anchor_overrides(
        repaired_anchors,
        anchor_overrides=grouped_overrides.get("anchor"),
    )
    anchor_summary = _refresh_anchor_summary(base_summary=base_anchor_summary, anchors=materialized_anchors)
    effective_links, override_summary, override_logs = _apply_link_overrides(
        repaired_links,
        link_overrides=grouped_overrides.get("link"),
        note_items=phase2.note_items,
        body_anchors=materialized_anchors,
        note_regions=phase2.note_regions,
        chapter_mode_by_id=chapter_mode_by_id,
    )
    effective_links, residual_suppression_summary = _suppress_endnote_residual_orphans(
        links=effective_links,
        chapter_mode_by_id=chapter_mode_by_id,
        book_type=str(book_type or ""),
    )
    override_logs = list(note_item_override_logs) + list(anchor_override_logs) + list(override_logs)

    contracts, contract_evidence = _chapter_contracts(
        chapter_layers=chapter_layers,
        effective_links=effective_links,
        body_anchors=materialized_anchors,
    )
    applicable_contracts = [row for row in contracts if bool(row.requires_endnote_contract)]
    hard_first_marker_is_one = all(row.first_marker_is_one for row in applicable_contracts)
    hard_endnotes_all_matched = all(row.endnotes_all_matched for row in applicable_contracts)
    hard_no_ambiguous_left = all(row.no_ambiguous_left for row in applicable_contracts)
    hard_no_orphan_note = all(row.no_orphan_note for row in applicable_contracts)
    if str(book_type or "") == "endnote_only":
        hard_endnote_only_no_orphan_anchor = all(
            row.endnote_only_no_orphan_anchor for row in applicable_contracts
        )
        endnote_only_evidence = {
            "status": "checked",
            "book_type": str(book_type or ""),
            "applicable_contract_count": len(applicable_contracts),
        }
    else:
        hard_endnote_only_no_orphan_anchor = True
        endnote_only_evidence = {
            "status": "not_applicable",
            "reason": f"book_type={book_type}",
        }

    raw_link_summary = _summarize_links(repaired_links)
    effective_link_summary = _summarize_links(effective_links)
    soft_footnote_orphan_anchor_warn = int(effective_link_summary.get("footnote_orphan_anchor") or 0) == 0
    soft_synthetic_anchor_warn = int(anchor_summary.get("synthetic_count") or 0) == 0

    hard = {
        "link.first_marker_is_one": bool(hard_first_marker_is_one),
        "link.endnotes_all_matched": bool(hard_endnotes_all_matched),
        "link.no_ambiguous_left": bool(hard_no_ambiguous_left),
        "link.no_orphan_note": bool(hard_no_orphan_note),
        "link.endnote_only_no_orphan_anchor": bool(hard_endnote_only_no_orphan_anchor),
    }
    soft = {
        "link.footnote_orphan_anchor_warn": bool(soft_footnote_orphan_anchor_warn),
        "link.synthetic_anchor_warn": bool(soft_synthetic_anchor_warn),
    }
    reasons: list[str] = []
    if not hard["link.first_marker_is_one"]:
        reasons.append("link_first_marker_not_one")
    if not hard["link.endnotes_all_matched"]:
        reasons.append("link_endnote_not_all_matched")
    if not hard["link.no_ambiguous_left"]:
        reasons.append("link_ambiguous_remaining")
    if not hard["link.no_orphan_note"]:
        reasons.append("link_orphan_note_remaining")
    if not hard["link.endnote_only_no_orphan_anchor"]:
        reasons.append("link_endnote_only_orphan_anchor_remaining")

    evidence = {
        "book_type": str(book_type or "no_notes"),
        "anchor_summary": anchor_summary,
        "raw_link_summary": raw_link_summary,
        "effective_link_summary": effective_link_summary,
        "chapter_contracts": contract_evidence,
        "chapter_link_contract_summary": {
            "chapter_count": int(len(contracts)),
            "contract_required_count": int(sum(1 for row in contracts if bool(row.requires_endnote_contract))),
            "failed_chapter_ids": [
                str(row.chapter_id or "")
                for row in contracts
                if not (
                    bool(row.first_marker_is_one)
                    and bool(row.endnotes_all_matched)
                    and bool(row.no_ambiguous_left)
                    and bool(row.no_orphan_note)
                    and bool(row.endnote_only_no_orphan_anchor)
                )
            ],
        },
        "book_endnote_stream_summary": _build_book_endnote_stream_summary(chapter_layers),
        "endnote_only_no_orphan_anchor": endnote_only_evidence,
        "review_seed_summary": dict(note_link_meta.get("review_seed_summary") or {}),
    }
    diagnostics = {
        "override_summary": dict(override_summary or {}),
        "note_item_override_summary": dict(note_item_override_summary or {}),
        "anchor_override_summary": dict(anchor_override_summary or {}),
        "contract_repair_summary": dict(contract_repair_summary or {}),
        "footnote_anchor_repair_summary": dict(footnote_anchor_repair_summary or {}),
        "residual_suppression_summary": dict(residual_suppression_summary or {}),
        "unsupported_override_scopes": [
            scope
            for scope in ("page", "chapter", "region", "llm_suggestion")
            if dict(grouped_overrides.get(scope) or {})
        ],
    }
    gate_report = GateReport(
        module="link",
        hard=hard,
        soft=soft,
        reasons=reasons,
        evidence=evidence,
        overrides_used=list(override_logs),
    )
    data = NoteLinkTable(
        anchors=_to_anchor_layers(materialized_anchors),
        links=_to_link_layers(repaired_links),
        effective_links=_to_link_layers(effective_links),
        chapter_link_contracts=contracts,
        anchor_summary=anchor_summary,
        link_summary=effective_link_summary,
    )
    return ModuleResult(
        data=data,
        gate_report=gate_report,
        evidence=evidence,
        overrides_used=list(override_logs),
        diagnostics=diagnostics,
    )

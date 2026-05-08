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
from FNM_RE.modules.endnote_repair import (
    project_priority as _projection_priority,
    repair_endnote_links_for_contract as _repair_endnote_links_for_contract,
    suppress_endnote_residual_orphans as _suppress_endnote_residual_orphans,
)
from FNM_RE.shared.notes import (
    _safe_int,
    normalize_note_marker,
)
from FNM_RE.shared.review_overrides import group_review_overrides as _group_review_overrides
from FNM_RE.stages.body_anchors import build_body_anchors
from FNM_RE.stages.note_links import build_note_links

FOOTNOTE_OVERRIDE_PAGE_PADDING = 1


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

def _summarize_links(rows: list[NoteLinkRecord]) -> dict[str, Any]:
    """对所有 link 按 status / note_kind / resolver 聚合统计。

    字段语义说明：
      - matched / orphan_* / ambiguous / ignored / fallback_count / repair_count
        都是按"link 数"独立统计，互不交集（按 status）或互不交集（按 resolver）。
      - **fallback_count / repair_count 不是错误数**：它们是按 resolver 维度的全量计数
        （含 matched 与 orphan），sum(rule + fallback + repair) 等于总 link 数，
        与 `matched` 不可直接比较（参见工单 #4）。
      - 工单 #4 引入 `fallback_match_ratio` 才是真正的链接质量信号：
        fallback resolver 命中的 matched 数 / matched 总数。
    """
    matched_count = sum(1 for row in rows if str(row.status or "") == "matched")
    fallback_matched_count = sum(
        1
        for row in rows
        if str(row.status or "") == "matched" and str(row.resolver or "") == "fallback"
    )
    fallback_match_ratio = (
        float(fallback_matched_count) / float(matched_count) if matched_count > 0 else 0.0
    )
    return {
        "matched": matched_count,
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
        "fallback_matched_count": fallback_matched_count,
        "fallback_match_ratio": fallback_match_ratio,
    }

def _link_quality_gate(rows: list[NoteLinkRecord]) -> dict[str, Any]:
    """工单 #4：链接质量阈值阻塞门。

    返回 `{quality_ok, fallback_match_ratio, orphan_anchor_total, ...}`。
    `quality_ok = False` 表示 fallback 占比或尾注孤儿 anchor 数任一超阈，
    应转化为 reasons `link_quality_low` 并阻塞。
    """
    import config

    summary = _summarize_links(rows)
    fallback_match_ratio = float(summary.get("fallback_match_ratio") or 0.0)
    footnote_orphan_anchor = int(summary.get("footnote_orphan_anchor") or 0)
    endnote_orphan_anchor = int(summary.get("endnote_orphan_anchor") or 0)
    orphan_anchor_total = footnote_orphan_anchor + endnote_orphan_anchor
    fallback_threshold = float(getattr(config, "LINK_FALLBACK_MATCH_RATIO_THRESHOLD_DEFAULT", 0.30))
    orphan_threshold = int(getattr(config, "LINK_ORPHAN_ANCHOR_THRESHOLD_DEFAULT", 10))
    # 脚注书 fallback 率高是正常的（synthetic-footnote），不应触发质量门。
    # fallback 率只在存在尾注孤儿 anchor 时才有质量含义。
    quality_ok = endnote_orphan_anchor <= orphan_threshold and (
        endnote_orphan_anchor == 0 or fallback_match_ratio <= fallback_threshold
    )
    return {
        "quality_ok": bool(quality_ok),
        "fallback_match_ratio": float(fallback_match_ratio),
        "fallback_match_ratio_threshold": float(fallback_threshold),
        "orphan_anchor_total": int(orphan_anchor_total),
        "footnote_orphan_anchor_total": int(footnote_orphan_anchor),
        "endnote_orphan_anchor_total": int(endnote_orphan_anchor),
        "orphan_anchor_threshold": int(orphan_threshold),
    }

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

def _infer_note_kind_from_anchor(anchor: BodyAnchorRecord) -> str:
    if str(anchor.anchor_kind or "") == "footnote":
        return "footnote"
    if str(anchor.anchor_kind or "") == "endnote":
        return "endnote"
    return "unknown"


def _chapter_body_text_by_page(chapter_layers: ChapterLayers) -> dict[tuple[str, int], str]:
    rows: dict[tuple[str, int], str] = {}
    for chapter in chapter_layers.chapters or []:
        chapter_id = str(chapter.chapter_id or "").strip()
        if not chapter_id:
            continue
        for page in chapter.body_pages or []:
            try:
                page_no = int(page.page_no or 0)
            except (TypeError, ValueError):
                page_no = 0
            if page_no <= 0:
                continue
            rows[(chapter_id, page_no)] = str(page.text or "")
    return rows


def _is_explicit_body_anchor(anchor: BodyAnchorRecord) -> bool:
    anchor_id = str(anchor.anchor_id or "")
    source = str(anchor.source or "").strip().lower()
    if bool(anchor.synthetic):
        return False
    if source == "llm" or anchor_id.startswith(("llm-anchor-", "synthetic-")):
        return False
    return True


def _anchor_kind_compatible(left: str, right: str) -> bool:
    left_kind = str(left or "").strip() or "unknown"
    right_kind = str(right or "").strip() or "unknown"
    return left_kind == right_kind or "unknown" in {left_kind, right_kind}


def _has_existing_explicit_anchor_for_override(
    anchors: list[BodyAnchorRecord],
    *,
    chapter_id: str,
    page_no: int,
    normalized_marker: str,
    anchor_kind: str,
) -> bool:
    marker = normalize_note_marker(normalized_marker)
    if not marker:
        return False
    return any(
        _is_explicit_body_anchor(anchor)
        and str(anchor.chapter_id or "") == chapter_id
        and int(anchor.page_no or 0) == page_no
        and normalize_note_marker(str(anchor.normalized_marker or "")) == marker
        and _anchor_kind_compatible(str(anchor.anchor_kind or ""), anchor_kind)
        for anchor in anchors
    )


def _find_existing_explicit_anchor_for_link_override(
    *,
    note_item: NoteItemRecord,
    body_anchors: list[BodyAnchorRecord],
    expected_note_kind: str,
) -> BodyAnchorRecord | None:
    marker = normalize_note_marker(str(note_item.marker or ""))
    chapter_id = str(note_item.chapter_id or "").strip()
    note_kind = str(expected_note_kind or "").strip()
    if not marker or not chapter_id or note_kind not in {"footnote", "endnote"}:
        return None

    candidates: list[BodyAnchorRecord] = []
    for anchor in body_anchors:
        if not _is_explicit_body_anchor(anchor):
            continue
        if str(anchor.chapter_id or "").strip() != chapter_id:
            continue
        if normalize_note_marker(str(anchor.normalized_marker or "")) != marker:
            continue
        if not _anchor_kind_compatible(str(anchor.anchor_kind or ""), note_kind):
            continue
        if note_kind == "footnote":
            note_page = int(note_item.page_no or 0)
            anchor_page = int(anchor.page_no or 0)
            if (
                note_page > 0
                and anchor_page > 0
                and abs(anchor_page - note_page) > FOOTNOTE_OVERRIDE_PAGE_PADDING
            ):
                continue
        candidates.append(anchor)

    if len(candidates) != 1:
        return None
    return candidates[0]


def _materialize_anchor_overrides(
    body_anchors: list[BodyAnchorRecord],
    *,
    anchor_overrides: Mapping[str, Mapping[str, Any]] | None,
    chapter_body_text_by_page: Mapping[tuple[str, int], str] | None = None,
) -> tuple[list[BodyAnchorRecord], dict[str, Any], list[dict[str, Any]]]:
    """消费 scope="anchor" override，物化成 BodyAnchorRecord 追加到 anchors 尾部。

    仅支持 `action == "create"` 的 LLM 合成锚点；已有 anchor_id 冲突的 override 会被丢弃。
    若 Phase 3 已在同章同页捕获同 marker/kind 的显式锚点，LLM 不再重复造锚点。
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
        if chapter_body_text_by_page is not None:
            body_text = chapter_body_text_by_page.get((chapter_id, page_no))
            if body_text is None:
                summary["rejected_count"] += 1
                summary["rejected_reasons"].append(f"{target_id}:non_body_page")
                continue
            if char_end > len(str(body_text or "")):
                summary["rejected_count"] += 1
                summary["rejected_reasons"].append(f"{target_id}:coords_out_of_page")
                continue
        anchor_kind = str(data.get("anchor_kind") or "endnote").strip() or "endnote"
        normalized_marker = normalize_note_marker(str(data.get("normalized_marker") or ""))
        if not normalized_marker:
            summary["rejected_count"] += 1
            summary["rejected_reasons"].append(f"{target_id}:missing_marker")
            continue
        if _has_existing_explicit_anchor_for_override(
            new_anchors,
            chapter_id=chapter_id,
            page_no=page_no,
            normalized_marker=normalized_marker,
            anchor_kind=anchor_kind,
        ):
            summary["rejected_count"] += 1
            summary["rejected_reasons"].append(f"{target_id}:existing_explicit_anchor")
            continue
        record = BodyAnchorRecord(
            anchor_id=anchor_id,
            chapter_id=chapter_id,
            page_no=page_no,
            paragraph_index=paragraph_index,
            char_start=char_start,
            char_end=char_end,
            source_marker=normalized_marker,
            normalized_marker=normalized_marker,
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
        if not note_item:
            invalid_count += 1
            invalid_flags.append(f"invalid_link_override:{target_id}:target")
            continue

        region = regions_by_id.get(str(note_item.region_id or ""))
        expected_note_kind = str((region.note_kind if region else "") or "")
        anchor = anchors_by_id.get(anchor_id)
        if anchor is None and str(anchor_id or "").startswith("llm-anchor-"):
            anchor = _find_existing_explicit_anchor_for_link_override(
                note_item=note_item,
                body_anchors=body_anchors,
                expected_note_kind=expected_note_kind,
            )
        if not anchor:
            invalid_count += 1
            invalid_flags.append(f"invalid_link_override:{target_id}:target")
            continue

        inferred_note_kind = _infer_note_kind_from_anchor(anchor)
        same_chapter = str(note_item.chapter_id or "") == str(anchor.chapter_id or "")
        same_kind = expected_note_kind in {"footnote", "endnote"} and expected_note_kind == inferred_note_kind
        if not same_chapter or not same_kind:
            invalid_count += 1
            invalid_flags.append(f"invalid_link_override:{target_id}:consistency")
            continue
        if expected_note_kind == "footnote":
            note_page = int(note_item.page_no or 0)
            anchor_page = int(anchor.page_no or 0)
            if (
                note_page > 0
                and anchor_page > 0
                and abs(anchor_page - note_page) > FOOTNOTE_OVERRIDE_PAGE_PADDING
            ):
                invalid_count += 1
                invalid_flags.append(f"invalid_link_override:{target_id}:page_window")
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

def _repair_explicit_footnote_anchor_ocr_variants(
    *,
    anchors: list[BodyAnchorRecord],
    links: list[NoteLinkRecord],
    note_items: list[NoteItemRecord],
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

    def _note_kind_from_layer(value: str, *, chapter_mode: str) -> str:
        note_kind = str(value or "").strip()
        if note_kind in {"footnote", "endnote"}:
            return note_kind
        # note_kind 为空时，保持空——不可用章级 chapter_mode 推断个体类型。
        # Phase 2 已确定每个 entity 的 note_kind，这里不应重新解释。
        # 如果到达此处，说明上游数据有问题，应在上游修复。
        _ = chapter_mode
        return ""

    region_note_kind_by_id: dict[str, str] = {}
    region_records: list[NoteRegionRecord] = []
    for row in chapter_layers.regions:
        chapter_id = str(row.owner_chapter_id or row.chapter_id or "")
        chapter_mode = str(chapter_policy_by_id.get(chapter_id, {}).get("note_mode") or "")
        note_kind = _note_kind_from_layer(str(row.note_kind or ""), chapter_mode=chapter_mode)
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
        note_kind = _note_kind_from_layer(
            str(row.note_kind or region_note_kind_by_id.get(region_id) or ""),
            chapter_mode=chapter_mode,
        )
        marker_type = str(row.marker_type or "")
        if not marker_type and note_kind == "footnote":
            marker_type = "footnote_marker"
        elif not marker_type and note_kind == "endnote":
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
            import sys
            print(f"  [WARNING] 未知 note_mode={note_mode!r}，强制回退为 no_notes", file=sys.stderr)
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
    # 工单 #3 契约 v2：anchor_total 直接取自 body_anchors（与落库数据同源），
    # 不再使用 chapter_layers.chapter_marker_counts（Phase 2 逐行扫描，与 Phase 3
    # 的分段扫描+OCR blocks 是两个不同路径，计数会有微小差异，导致假阳性 mismatch）。
    _anchor_total_by_chapter: dict[str, int] = {}
    for anchor in body_anchors:
        if str(anchor.anchor_kind or "") != "endnote":
            continue
        cid = str(anchor.chapter_id or "")
        marker = normalize_note_marker(str(anchor.normalized_marker or ""))
        if not cid or not marker or not marker.isdigit():
            continue
        _anchor_total_by_chapter.setdefault(cid, set()).add(marker)  # type: ignore[union-attr]
    chapter_marker_counts = {cid: len(s) for cid, s in _anchor_total_by_chapter.items()}
    for chapter in chapter_layers.chapters:
        chapter_id = str(chapter.chapter_id or "")
        raw_has_endnote_signal = bool(chapter.endnote_items or chapter.endnote_regions)
        note_mode = str(chapter.policy_applied.get("note_mode") or "no_notes")
        # 树状原则：合同触发条件必须是物理信号（章内是否有尾注内容），
        # 不能依赖 note_mode（章的聚合标签，不反映个体 entity 的种类）。
        requires_endnote_contract = bool(raw_has_endnote_signal)
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
            # endnote-link 视角的 4 类校验保留按 endnote 上下文（mode 不要求时不强求）
            endnotes_all_matched = True
            no_ambiguous_left = True
            no_orphan_note = True
            endnote_only_no_orphan_anchor = True

        # 工单 #3 契约 v2：对地校验（不依赖 requires_endnote_contract 短路）
        # def 集合 = chapter 的 footnote_items + endnote_items 中带数字 marker 的项。
        # 必须去重：_build_chapter_layers 中 endnote region 拆分/投影可能产生同 marker
        # 的重复条目（ChapterLayer 有 112 项但 DB 落库去重后只有 108 项）。
        all_def_items = list(chapter.footnote_items or []) + list(chapter.endnote_items or [])
        def_numeric_markers: list[int] = []
        seen_markers: set[int] = set()
        for item in all_def_items:
            marker_value = _safe_int(normalize_note_marker(str(item.marker or "")))
            if marker_value > 0 and marker_value not in seen_markers:
                def_numeric_markers.append(marker_value)
                seen_markers.add(marker_value)
        def_numeric_markers.sort()
        def_count = len(def_numeric_markers)
        anchor_total = int(chapter_marker_counts.get(chapter_id) or 0)

        # first_marker_is_one：所有 def 中数字最小的 == 1（无 def 时 True）
        contract_first_marker_is_one = (
            (def_numeric_markers[0] == 1) if def_numeric_markers else True
        )
        # 当 def_numeric_markers 为空但 endnote-link 路径已计算了 first_marker_is_one，
        # 取后者（保持 endnote-only 章节的现有语义）；当有 def_numeric_markers 时以"对地"为准。
        if def_numeric_markers:
            first_marker_is_one = bool(contract_first_marker_is_one)
        elif not requires_endnote_contract:
            first_marker_is_one = True

        # has_marker_gap：去重后的数字 marker 是否等于 [1, 2, ..., max]。
        # book_endnote_bound 书的 marker 序列跨章连续，跳过逐章校验。
        unique_markers = sorted(set(def_numeric_markers))
        if note_mode == "book_endnote_bound":
            has_marker_gap = False
        elif unique_markers:
            # 过滤 outlier：OCR 可能把页码/垃圾文本误读为超大 marker
            # （Biopolitics ch.4 marker=359, ch.6 marker=668），
            # 这类 outlier 会把 range 拉到 [1..668]，制造假 gap。
            # 策略：若最大 marker 与次大 marker 之间存在 > 50% 的跳跃，
            # 截断到跳跃点之前的主序列。
            truncated = list(unique_markers)
            if len(truncated) >= 2:
                for i in range(len(truncated) - 1, 0, -1):
                    gap_ratio = (truncated[i] - truncated[i - 1]) / max(1, truncated[i - 1])
                    if gap_ratio > 0.5 and truncated[i] > truncated[i - 1] + 20:
                        truncated = truncated[:i]
                        break
            expected = list(range(1, truncated[-1] + 1))
            has_marker_gap = truncated != expected
        else:
            has_marker_gap = False

        # def_anchor_mismatch：def_count vs anchor_total 偏差。
        # 仅对有 endnote 信号的章做校验——纯脚注章或无注释章的 anchor 计数
        # 差异来自 OCR 噪声（1-3 个 bare_digit），不是真正的 mismatch。
        # book_endnote_bound 的 items 从全书尾注池按 marker 投影到章，
        # 逐章校验同样无意义。
        if not requires_endnote_contract or note_mode == "book_endnote_bound":
            def_anchor_mismatch = False
        elif anchor_total > 0:
            def_anchor_mismatch = def_count != anchor_total
        else:
            def_anchor_mismatch = False

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
                has_marker_gap=bool(has_marker_gap),
                def_anchor_mismatch=bool(def_anchor_mismatch),
                def_count=int(def_count),
                anchor_total=int(anchor_total),
                marker_sequence=list(unique_markers),
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
    pdf_path: str = "",
) -> ModuleResult[NoteLinkTable]:
    phase2, _chapter_mode_by_id, book_type = _phase2_from_chapter_layers(chapter_layers)
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
    body_anchors, base_anchor_summary = build_body_anchors(phase2, pages=pages, pdf_path=str(pdf_path or ""))
    enhanced_anchors, note_links, note_link_meta = build_note_links(body_anchors, phase2, pages=pages)
    repaired_links, contract_repair_summary = _repair_endnote_links_for_contract(
        links=note_links,
        anchors=enhanced_anchors,
        note_item_meta_by_id=note_item_meta_by_id,
        book_type=str(book_type or ""),
    )
    repaired_anchors, repaired_links, footnote_anchor_repair_summary = _repair_explicit_footnote_anchor_ocr_variants(
        anchors=enhanced_anchors,
        links=repaired_links,
        note_items=phase2.note_items,
    )
    materialized_anchors, anchor_override_summary, anchor_override_logs = _materialize_anchor_overrides(
        repaired_anchors,
        anchor_overrides=grouped_overrides.get("anchor"),
        chapter_body_text_by_page=_chapter_body_text_by_page(chapter_layers),
    )
    anchor_summary = _refresh_anchor_summary(base_summary=base_anchor_summary, anchors=materialized_anchors)
    effective_links, override_summary, override_logs = _apply_link_overrides(
        repaired_links,
        link_overrides=grouped_overrides.get("link"),
        note_items=phase2.note_items,
        body_anchors=materialized_anchors,
        note_regions=phase2.note_regions,
    )
    effective_links, residual_suppression_summary = _suppress_endnote_residual_orphans(
        links=effective_links,
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

    # 工单 #3 契约 v2：沿用上面的 applicable_contracts（仅 requires_endnote_contract=True 的章）。
    contract_v2_first_marker_is_one = all(row.first_marker_is_one for row in applicable_contracts)
    contract_v2_no_marker_gap = all(not row.has_marker_gap for row in applicable_contracts)
    contract_v2_def_anchor_aligned = all(not row.def_anchor_mismatch for row in applicable_contracts)
    contract_v2_failed_chapters = [
        str(row.chapter_id or "")
        for row in applicable_contracts
        if not bool(row.first_marker_is_one)
        or bool(row.has_marker_gap)
        or bool(row.def_anchor_mismatch)
    ]

    raw_link_summary = _summarize_links(repaired_links)
    effective_link_summary = _summarize_links(effective_links)
    link_quality = _link_quality_gate(effective_links)
    soft_footnote_orphan_anchor_warn = int(effective_link_summary.get("footnote_orphan_anchor") or 0) == 0
    soft_synthetic_anchor_warn = int(anchor_summary.get("synthetic_count") or 0) == 0

    hard = {
        "link.first_marker_is_one": bool(hard_first_marker_is_one),
        "link.endnotes_all_matched": bool(hard_endnotes_all_matched),
        "link.no_ambiguous_left": bool(hard_no_ambiguous_left),
        "link.no_orphan_note": bool(hard_no_orphan_note),
        "link.endnote_only_no_orphan_anchor": bool(hard_endnote_only_no_orphan_anchor),
        # 工单 #3 契约 v2：对地校验
        "link.contract_first_marker_is_one": bool(contract_v2_first_marker_is_one),
        "link.no_marker_gap": bool(contract_v2_no_marker_gap),
        "link.def_anchor_aligned": bool(contract_v2_def_anchor_aligned),
        # 工单 #4 链接质量阈值：fallback_match_ratio + orphan_anchor 总数
        "link.quality_ok": bool(link_quality.get("quality_ok", True)),
    }
    soft = {
        "link.footnote_orphan_anchor_warn": bool(soft_footnote_orphan_anchor_warn),
        "link.synthetic_anchor_warn": bool(soft_synthetic_anchor_warn),
    }
    reasons: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []
    # book_endnotes 模式下，跨章编号序列检查不适用
    _is_book_endnotes = str(book_type or "") == "endnote_only"
    def _add(code: str, *, blocker: bool = True) -> None:
        reasons.append(code)
        if blocker:
            blockers.append(code)
        else:
            warnings.append(code)
    if not hard["link.first_marker_is_one"]:
        _add("link_first_marker_not_one", blocker=not _is_book_endnotes)
    if not hard["link.endnotes_all_matched"]:
        _add("link_endnote_not_all_matched")
    if not hard["link.no_ambiguous_left"]:
        _add("link_ambiguous_remaining")
    if not hard["link.no_orphan_note"]:
        _add("link_orphan_note_remaining")
    if not hard["link.endnote_only_no_orphan_anchor"]:
        _add("link_endnote_only_orphan_anchor_remaining")
    if not hard["link.contract_first_marker_is_one"]:
        _add("contract_first_marker_not_one", blocker=not _is_book_endnotes)
    if not hard["link.no_marker_gap"]:
        _add("contract_marker_gap", blocker=not _is_book_endnotes)
    if not hard["link.def_anchor_aligned"]:
        _add("contract_def_anchor_mismatch")
    if not hard["link.quality_ok"]:
        _add("link_quality_low")

    evidence = {
        "book_type": str(book_type or "no_notes"),
        "anchor_summary": anchor_summary,
        "raw_link_summary": raw_link_summary,
        "effective_link_summary": effective_link_summary,
        "link_quality": dict(link_quality),
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
            # 工单 #3 契约 v2：对地校验失败的章节及统计
            "contract_v2_failed_chapter_ids": list(contract_v2_failed_chapters),
            "contract_v2_first_marker_violation_count": int(
                sum(1 for row in contracts if not bool(row.first_marker_is_one))
            ),
            "contract_v2_marker_gap_violation_count": int(
                sum(1 for row in contracts if bool(row.has_marker_gap))
            ),
            "contract_v2_def_anchor_mismatch_count": int(
                sum(1 for row in contracts if bool(row.def_anchor_mismatch))
            ),
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
        blockers=blockers,
        warnings=warnings,
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

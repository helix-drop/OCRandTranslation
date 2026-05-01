"""阶段 2 模块：章节正文与注释切分。"""

from __future__ import annotations

import re
from dataclasses import asdict, replace
from typing import Any, Mapping

from FNM_RE.models import ChapterRecord, PagePartitionRecord, Phase1Structure, SectionHeadRecord
from FNM_RE.modules.contracts import GateReport, ModuleResult
from FNM_RE.modules.types import (
    BodyPageLayer,
    BodySegmentLayer,
    BookNoteProfile,
    ChapterLayer,
    ChapterLayers,
    LayerNoteItem,
    LayerNoteRegion,
    TocStructure,
)
from FNM_RE.shared.anchors import scan_anchor_markers
from FNM_RE.shared.notes import _safe_int, normalize_note_marker
from FNM_RE.shared.text import page_markdown_text
from FNM_RE.stages.note_items import build_note_items
from FNM_RE.stages.note_regions import build_note_regions
from FNM_RE.stages.units import (
    _build_structured_body_pages_for_chapter,
    _chapter_endnote_start_page_map,
    _segment_paragraphs_from_body_pages,
)

_NOTES_HEADING_RE = re.compile(r"(?im)^\s{0,3}(?:##\s*)?(?:notes?|endnotes?)\s*$")
_NOTE_DEF_LINE_PREFIX_RE = re.compile(r"^\s*\[\^?\d{1,4}\]:\s*")

def _scan_body_anchor_markers(text: str) -> list[str]:
    """对页 markdown 扫描正文 anchor marker；跳过 `[^N]: ...` 定义行。

    返回 normalized_marker 列表（可能含重复，按出现顺序）。
    """
    markers: list[str] = []
    for line in (text or "").split("\n"):
        if _NOTE_DEF_LINE_PREFIX_RE.match(line):
            continue
        refs, _ = scan_anchor_markers(line)
        for ref in refs:
            normalized = str(ref.get("normalized_marker") or "")
            if normalized:
                markers.append(normalized)
    return markers

def _legacy_page_role(toc_role: str) -> str:
    role = str(toc_role or "").strip().lower()
    if role in {"chapter", "post_body"}:
        return "body"
    if role == "front_matter":
        return "front_matter"
    # 工单 #5：note 角色直接透传，让下游 note_regions._is_endnote_candidate_page
    # 与 chapter_split._chapter_body_marker_sets 都能识别 NOTES 容器页。
    if role == "note":
        return "note"
    return "other"

def _phase1_from_toc_structure(toc_structure: TocStructure) -> Phase1Structure:
    return _phase1_from_toc_structure_with_evidence(toc_structure)

def _phase1_from_toc_structure_with_evidence(
    toc_structure: TocStructure,
    *,
    heading_candidates: list[Any] | None = None,
    endnote_explorer_hints: Mapping[str, Any] | None = None,
) -> Phase1Structure:
    pages = [
        PagePartitionRecord(
            page_no=int(row.page_no),
            target_pdf_page=int(row.page_no),
            page_role=_legacy_page_role(row.role),  # type: ignore[arg-type]
            confidence=1.0,
            reason=str(row.reason or "module_projection"),
            section_hint="",
            has_note_heading=bool(_NOTES_HEADING_RE.search(str(row.reason or ""))),
            note_scan_summary={},
        )
        for row in sorted(toc_structure.pages, key=lambda item: int(item.page_no))
    ]
    chapters = [
        ChapterRecord(
            chapter_id=str(row.chapter_id or ""),
            title=str(row.title or ""),
            start_page=int(row.start_page),
            end_page=int(row.end_page),
            pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
            source=str(row.source or "fallback"),  # type: ignore[arg-type]
            boundary_state=str(row.boundary_state or "ready"),  # type: ignore[arg-type]
        )
        for row in sorted(toc_structure.chapters, key=lambda item: (int(item.start_page), str(item.chapter_id)))
    ]
    section_heads = [
        SectionHeadRecord(
            section_head_id=str(row.section_head_id or ""),
            chapter_id=str(row.chapter_id or ""),
            title=str(row.title or ""),
            page_no=int(row.page_no),
            level=int(row.level),
            source=str(row.source or ""),
        )
        for row in toc_structure.section_heads
    ]
    return Phase1Structure(
        pages=pages,
        heading_candidates=list(heading_candidates or []),
        chapters=chapters,
        section_heads=section_heads,
        endnote_explorer_hints=dict(endnote_explorer_hints or {}),
    )

def _to_layer_regions(regions: list[Any]) -> list[LayerNoteRegion]:
    def _bind_meta(source: str, chapter_id: str) -> tuple[str, float]:
        normalized = str(source or "").strip().lower()
        if normalized == "explorer_toc_match":
            return "toc_subentry", 1.0
        if normalized == "explorer_signal_match":
            return "page_signal", 0.82
        if normalized == "fallback_nearest_prior":
            return "nearest_prior", 0.55
        if "llm" in normalized:
            return "llm", 1.0 if chapter_id else 0.0
        return "rule", 1.0 if chapter_id else 0.0

    return [
        LayerNoteRegion(
            region_id=str(row.region_id or ""),
            chapter_id=str(row.chapter_id or ""),
            owner_chapter_id=str(row.chapter_id or ""),
            page_start=int(row.page_start),
            page_end=int(row.page_end),
            pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
            note_kind=str(row.note_kind),  # type: ignore[arg-type]
            scope=str(row.scope),  # type: ignore[arg-type]
            source_scope=str(row.scope),  # type: ignore[arg-type]
            source=str(row.source),  # type: ignore[arg-type]
            bind_method=_bind_meta(str(row.source or ""), str(row.chapter_id or ""))[0],
            bind_confidence=_bind_meta(str(row.source or ""), str(row.chapter_id or ""))[1],
            heading_text=str(row.heading_text or ""),
            review_required=bool(row.review_required),
            # 工单 #2：透传上游回填的 region 首条 note item marker
            region_first_note_item_marker=str(row.region_first_note_item_marker or ""),
        )
        for row in regions
    ]

def _to_layer_items(
    items: list[Any],
    *,
    note_kind_by_region: Mapping[str, str],
    owner_chapter_by_region: Mapping[str, str],
    source_scope_by_region: Mapping[str, str],
) -> list[LayerNoteItem]:
    rows: list[LayerNoteItem] = []
    for row in items:
        region_id = str(row.region_id or "")
        owner_chapter_id = str(owner_chapter_by_region.get(region_id, str(row.chapter_id or "")) or "")
        source_scope = str(source_scope_by_region.get(region_id, "chapter") or "chapter")
        source_marker = str(row.marker or "")
        normalized_marker = normalize_note_marker(source_marker)
        note_kind = str(note_kind_by_region.get(str(row.region_id or ""), "footnote"))
        rows.append(
            LayerNoteItem(
                note_item_id=str(row.note_item_id or ""),
                region_id=region_id,
                chapter_id=str(row.chapter_id or ""),
                owner_chapter_id=owner_chapter_id,
                page_no=int(row.page_no),
                marker=normalized_marker or source_marker,
                source_marker=source_marker,
                normalized_marker=normalized_marker,
                synth_marker="",
                projection_mode="book_projected" if source_scope == "book" else "native",
                marker_type=str(row.marker_type or ""),
                text=str(row.text or ""),
                source=str(row.source or ""),
                is_reconstructed=bool(row.is_reconstructed),
                review_required=bool(row.review_required),
                note_kind=note_kind,  # type: ignore[arg-type]
            )
        )
    return rows

def _chapter_body_marker_sets(
    *,
    phase1: Phase1Structure,
    pages: list[dict],
) -> dict[str, set[str]]:
    raw_page_by_no = {
        int(page.get("bookPage") or 0): dict(page)
        for page in pages
        if int(page.get("bookPage") or 0) > 0
    }
    page_role_by_no = {int(row.page_no): str(row.page_role) for row in phase1.pages if int(row.page_no) > 0}
    markers_by_chapter: dict[str, set[str]] = {}
    for chapter in phase1.chapters:
        chapter_id = str(chapter.chapter_id or "")
        if not chapter_id:
            continue
        chapter_markers: set[str] = set()
        for page_no in sorted({int(page_no) for page_no in list(chapter.pages or []) if int(page_no) > 0}):
            if str(page_role_by_no.get(page_no) or "") == "note":
                continue
            text = page_markdown_text(raw_page_by_no.get(page_no) or {})
            for normalized in _scan_body_anchor_markers(text or ""):
                chapter_markers.add(normalized)
        markers_by_chapter[chapter_id] = chapter_markers
    return markers_by_chapter

def _project_endnotes_by_marker(
    *,
    layer_regions: list[LayerNoteRegion],
    layer_items: list[LayerNoteItem],
    chapter_marker_sets: Mapping[str, set[str]],
    chapter_order: list[str],
    book_type: str,
) -> None:
    marker_to_chapters: dict[str, list[str]] = {}
    for chapter_id in chapter_order:
        for marker in sorted(chapter_marker_sets.get(chapter_id) or set()):
            marker_to_chapters.setdefault(marker, []).append(chapter_id)
    chapter_rank = {chapter_id: index for index, chapter_id in enumerate(chapter_order)}
    region_by_id = {str(region.region_id or ""): region for region in layer_regions}
    item_counts_by_region: dict[str, dict[str, int]] = {}
    for item in layer_items:
        if str(item.note_kind or "") != "endnote":
            continue
        region = region_by_id.get(str(item.region_id or ""))
        if region is None:
            continue
        source_scope = str(region.source_scope or region.scope or "")
        region_source = str(region.source or "")
        allow_projection = (
            source_scope == "book"
            or (
                book_type == "endnote_only"
                and region_source in {"manual_rebind", "heading_scan", "continuation_merge"}
            )
        )
        if not allow_projection:
            continue
        marker = str(item.normalized_marker or normalize_note_marker(str(item.marker or "")) or "").strip()
        candidates = list(marker_to_chapters.get(marker) or [])
        if not candidates:
            continue
        current = str(item.owner_chapter_id or item.chapter_id or "")
        if len(candidates) == 1:
            chosen = str(candidates[0])
        else:
            if current and current in candidates:
                continue
            if current and current in chapter_rank:
                chosen = min(candidates, key=lambda chapter_id: abs(chapter_rank.get(chapter_id, 0) - chapter_rank.get(current, 0)))
            else:
                chosen = str(candidates[0])
        if current == chosen:
            continue
        item.owner_chapter_id = chosen
        item.projection_mode = "book_marker_projected" if source_scope == "book" else "chapter_marker_projected"
        region_id = str(item.region_id or "")
        item_counts_by_region.setdefault(region_id, {})
        item_counts_by_region[region_id][chosen] = int(item_counts_by_region[region_id].get(chosen, 0) or 0) + 1
    for region_id, chapter_counts in item_counts_by_region.items():
        region = region_by_id.get(region_id)
        if region is None or str(region.source_scope or region.scope or "") != "book":
            continue
        total = sum(int(count or 0) for count in chapter_counts.values())
        if total <= 0:
            continue
        ranked = sorted(chapter_counts.items(), key=lambda row: (-int(row[1]), chapter_rank.get(str(row[0]), 10**9)))
        chosen, count = ranked[0]
        region.owner_chapter_id = str(chosen)
        region.bind_method = "marker_projection"
        region.bind_confidence = round(float(count / total), 4)

def _fallback_assign_unowned_endnotes(
    *,
    phase1: Phase1Structure,
    layer_regions: list[LayerNoteRegion],
    layer_items: list[LayerNoteItem],
) -> None:
    ordered_chapters = [chapter for chapter in phase1.chapters if str(chapter.chapter_id or "").strip()]
    if not ordered_chapters:
        return

    def _owner_for_page(page_no: int) -> str:
        for chapter in ordered_chapters:
            pages = {int(page) for page in list(chapter.pages or []) if int(page) > 0}
            if pages and int(page_no) in pages:
                return str(chapter.chapter_id or "")
        prior = [chapter for chapter in ordered_chapters if int(chapter.start_page) <= int(page_no)]
        if prior:
            return str(prior[-1].chapter_id or "")
        return str(ordered_chapters[0].chapter_id or "")

    item_owner_counts_by_region: dict[str, dict[str, int]] = {}
    for item in layer_items:
        if str(item.note_kind or "") != "endnote":
            continue
        if str(item.owner_chapter_id or item.chapter_id or "").strip():
            continue
        fallback_owner = _owner_for_page(int(item.page_no))
        if not fallback_owner:
            continue
        item.owner_chapter_id = fallback_owner
        item.projection_mode = "book_fallback_projected"
        region_id = str(item.region_id or "")
        item_owner_counts_by_region.setdefault(region_id, {})
        item_owner_counts_by_region[region_id][fallback_owner] = int(
            item_owner_counts_by_region[region_id].get(fallback_owner, 0) or 0
        ) + 1

    if not item_owner_counts_by_region:
        return

    region_by_id = {str(region.region_id or ""): region for region in layer_regions}
    for region_id, owner_counts in item_owner_counts_by_region.items():
        region = region_by_id.get(region_id)
        if region is None:
            continue
        if str(region.owner_chapter_id or region.chapter_id or "").strip():
            continue
        total = sum(int(count or 0) for count in owner_counts.values())
        if total <= 0:
            continue
        chosen, count = sorted(owner_counts.items(), key=lambda row: -int(row[1]))[0]
        region.owner_chapter_id = str(chosen)
        region.bind_method = "fallback_projection"
        region.bind_confidence = round(float(count / total), 4)

def _normalize_empty_region_overrides(overrides: Mapping[str, Any] | None) -> tuple[set[str], list[dict[str, Any]]]:
    override_map = dict(overrides or {})
    allow_ids: set[str] = {str(item).strip() for item in list(override_map.get("allow_empty_region_ids") or []) if str(item).strip()}
    for row in list(override_map.get("allow_empty_regions") or []):
        if isinstance(row, dict) and str(row.get("region_id") or "").strip():
            allow_ids.add(str(row.get("region_id")).strip())
    reason = str(override_map.get("reason") or "manual_allow_empty_region").strip()
    used = [
        {
            "kind": "gate_override",
            "gate": "split.items_extracted",
            "region_id": region_id,
            "reason": reason,
        }
        for region_id in sorted(allow_ids)
    ]
    return allow_ids, used

def _build_chapter_layers(
    *,
    toc_structure: TocStructure,
    phase1: Phase1Structure,
    pages: list[dict],
    regions: list[Any],
    layer_regions: list[LayerNoteRegion],
    layer_items: list[LayerNoteItem],
    book_note_profile: BookNoteProfile,
) -> tuple[list[ChapterLayer], dict[str, int], dict[str, Any]]:
    raw_page_by_no = {
        int(page.get("bookPage") or 0): dict(page)
        for page in pages
        if int(page.get("bookPage") or 0) > 0
    }
    page_role_by_no = {int(row.page_no): str(row.page_role) for row in phase1.pages if int(row.page_no) > 0}
    chapter_endnote_start_map = _chapter_endnote_start_page_map(regions)
    mode_by_chapter = {str(row.chapter_id or ""): str(row.note_mode or "no_notes") for row in book_note_profile.chapter_modes}

    # 先按 item 归类，用于后续 mode override 的安全校验
    footnotes_by_chapter: dict[str, list[LayerNoteItem]] = {}
    endnotes_by_chapter: dict[str, list[LayerNoteItem]] = {}
    for item in layer_items:
        chapter_key = str(item.owner_chapter_id or item.chapter_id or "")
        if item.note_kind == "footnote":
            footnotes_by_chapter.setdefault(chapter_key, []).append(item)
        else:
            endnotes_by_chapter.setdefault(chapter_key, []).append(item)

    # 阶段3.A：endnote region 优先——若有 chapter_endnotes region，覆盖 footnote_primary → chapter_endnote_primary
    for region in layer_regions:
        if str(region.note_kind or "") != "endnote" or str(region.scope or "") != "chapter":
            continue
        cid = str(region.chapter_id or region.owner_chapter_id or "")
        if cid in mode_by_chapter and mode_by_chapter[cid] == "footnote_primary":
            # 安全检查：若章内脚注条目数 > 尾注条目数，且 region 没有 notes heading，
            # 则 endnote region 很可能是脚注页被 note_detection 误判，不回退会导致
            # note_capture 只看尾注而忽略大量脚注条目（Germany_Madness ch.1 captured=0 的根因）。
            fn_count = len(footnotes_by_chapter.get(cid, []))
            en_count = len(endnotes_by_chapter.get(cid, []))
            region_has_heading = bool(str(region.heading_text or "").strip())
            if fn_count > en_count and not region_has_heading:
                continue
            mode_by_chapter[cid] = "chapter_endnote_primary"
    endnote_regions_by_chapter: dict[str, list[LayerNoteRegion]] = {}
    for region in layer_regions:
        if region.note_kind == "endnote":
            chapter_key = str(region.owner_chapter_id or region.chapter_id or "")
            endnote_regions_by_chapter.setdefault(chapter_key, []).append(region)

    chapter_layers: list[ChapterLayer] = []
    chapter_disjoint_violations: list[str] = []
    chapters_without_body: list[str] = []
    cross_page_counts: dict[str, int] = {}
    char_drop_candidates: list[dict[str, Any]] = []
    page_marker_counts_by_chapter: dict[str, dict[int, int]] = {}
    chapter_marker_counts: dict[str, int] = {}
    _chapter_marker_unique_sets: dict[str, set[str]] = {}

    for index, chapter in enumerate(phase1.chapters):
        next_chapter = phase1.chapters[index + 1] if index + 1 < len(phase1.chapters) else None
        chapter_id = str(chapter.chapter_id or "")
        note_start_page = int(chapter_endnote_start_map.get(chapter_id) or 0)
        body_rows = _build_structured_body_pages_for_chapter(
            chapter,
            raw_page_by_no=raw_page_by_no,
            page_role_by_no=page_role_by_no,
            note_start_page=note_start_page,
            next_chapter=next_chapter,
        )
        body_pages: list[BodyPageLayer] = []
        for row in body_rows:
            page_no = int(row.get("page_no") or 0)
            source_text = str(row.get("text") or "")
            source_role = str(page_role_by_no.get(page_no) or "")
            marker_hits = [marker for marker in _scan_body_anchor_markers(source_text or "") if marker]
            if marker_hits and page_no > 0:
                page_marker_counts_by_chapter.setdefault(chapter_id, {})[page_no] = len(marker_hits)
                # 章级总数用去重 marker——同一尾注被正文多次引用时，
                # anchor_total 应与 def_count (唯一 note items) 语义一致。
                prev_set = _chapter_marker_unique_sets.get(chapter_id, set())
                prev_set.update(marker_hits)
                _chapter_marker_unique_sets[chapter_id] = prev_set
                chapter_marker_counts[chapter_id] = len(prev_set)
            if (
                page_no > 0
                and note_start_page > 0
                and page_no > note_start_page
                and (source_role in {"note", "other"} or bool(_NOTES_HEADING_RE.search(source_text)))
            ):
                chapter_disjoint_violations.append(chapter_id)
            if page_no == note_start_page and _NOTES_HEADING_RE.search(source_text):
                chapter_disjoint_violations.append(chapter_id)
            split_reason = "note_start_split" if page_no == note_start_page and note_start_page > 0 else "body_page"
            body_pages.append(
                BodyPageLayer(
                    page_no=page_no,
                    text=source_text,
                    split_reason=split_reason,
                    source_role=source_role,
                )
            )

        section_payload = {
            "section_id": chapter_id,
            "title": str(chapter.title or ""),
            "frozen_body_pages": [{"page_no": row.page_no, "text": row.text} for row in body_pages],
            "obsidian_body_pages": [{"page_no": row.page_no, "text": row.text} for row in body_pages],
        }
        unit_segments = _segment_paragraphs_from_body_pages(section_payload)
        body_segments: list[BodySegmentLayer] = []
        cross_page_count = 0
        for segment in unit_segments:
            paragraph_payloads = [asdict(paragraph) for paragraph in list(segment.paragraphs or [])]
            cross_page_count += sum(1 for row in paragraph_payloads if bool(row.get("cross_page")))
            body_segments.append(
                BodySegmentLayer(
                    page_no=int(segment.page_no),
                    paragraph_count=int(segment.paragraph_count),
                    source_text=str(segment.source_text or ""),
                    display_text=str(segment.display_text or ""),
                    paragraphs=paragraph_payloads,
                )
            )
        cross_page_counts[chapter_id] = int(cross_page_count)
        if not body_segments:
            chapters_without_body.append(chapter_id)

        chapter_before_chars = sum(
            len(page_markdown_text(raw_page_by_no.get(int(page_no), {})))
            for page_no in ([int(page_no) for page_no in chapter.pages] or range(int(chapter.start_page), int(chapter.end_page) + 1))
            if int(page_no) > 0
        )
        chapter_after_chars = sum(len(row.text) for row in body_pages)
        if chapter_before_chars > 0 and chapter_after_chars / chapter_before_chars < 0.35:
            char_drop_candidates.append(
                {
                    "chapter_id": chapter_id,
                    "before_chars": int(chapter_before_chars),
                    "after_chars": int(chapter_after_chars),
                    "ratio": float(chapter_after_chars / chapter_before_chars),
                }
            )

        chapter_mode = str(mode_by_chapter.get(chapter_id) or "no_notes")
        chapter_policy = {
            "book_type": str(book_note_profile.book_type or ""),
            "note_mode": chapter_mode,
            "materialization": "not_required" if str(book_note_profile.book_type) == "mixed" else "not_applicable",
            "footnote_only_synthesized": "required" if str(book_note_profile.book_type) == "footnote_only" else "not_applicable",
        }
        chapter_layers.append(
            ChapterLayer(
                chapter_id=chapter_id,
                title=str(chapter.title or ""),
                body_pages=body_pages,
                body_segments=body_segments,
                footnote_items=sorted(footnotes_by_chapter.get(chapter_id, []), key=lambda item: (item.page_no, item.note_item_id)),
                endnote_items=sorted(endnotes_by_chapter.get(chapter_id, []), key=lambda item: (item.page_no, item.note_item_id)),
                endnote_regions=sorted(
                    endnote_regions_by_chapter.get(chapter_id, []),
                    key=lambda row: (row.page_start, row.region_id),
                ),
                policy_applied=chapter_policy,
            )
        )

    return chapter_layers, cross_page_counts, {
        "chapter_endnote_start_map": {str(key): int(value) for key, value in dict(chapter_endnote_start_map).items()},
        "chapter_disjoint_violations": sorted(set(chapter_disjoint_violations)),
        "chapters_without_body": sorted(set(chapters_without_body)),
        "char_drop_candidates": char_drop_candidates,
        "chapter_marker_counts": {str(key): int(value) for key, value in chapter_marker_counts.items()},
        "page_marker_counts_by_chapter": {
            str(chapter_id): {str(page_no): int(count) for page_no, count in counts.items()}
            for chapter_id, counts in page_marker_counts_by_chapter.items()
        },
    }

def _synthesize_footnote_only_markers(
    *,
    chapter_layers: list[ChapterLayer],
    mode_by_chapter: Mapping[str, str],
) -> tuple[bool, dict[str, Any]]:
    chapter_markers: dict[str, list[str]] = {}
    synthesized_item_count = 0
    for chapter in chapter_layers:
        chapter_id = str(chapter.chapter_id or "")
        if str(mode_by_chapter.get(chapter_id) or "no_notes") != "footnote_primary":
            continue
        items = sorted(
            list(chapter.footnote_items or []),
            key=lambda row: (int(row.page_no), str(row.note_item_id or "")),
        )
        if not items:
            return False, {
                "status": "failed",
                "reason": "chapter_no_footnote_items",
                "chapter_id": chapter_id,
                "chapter_markers": chapter_markers,
            }
        synthesized: list[str] = []
        for index, item in enumerate(items, start=1):
            source_marker = str(item.source_marker or item.marker or "")
            normalized_marker = normalize_note_marker(source_marker)
            synth_marker = str(index)
            item.source_marker = source_marker
            item.normalized_marker = normalized_marker
            item.synth_marker = synth_marker
            item.marker = synth_marker
            item.projection_mode = "footnote_synthesized"
            synthesized.append(synth_marker)
            synthesized_item_count += 1
        chapter_markers[chapter_id] = synthesized
    if not chapter_markers:
        return False, {"status": "failed", "reason": "no_footnote_only_chapter"}
    return True, {
        "status": "passed",
        "chapter_markers": chapter_markers,
        "chapter_count": len(chapter_markers),
        "synthesized_item_count": int(synthesized_item_count),
    }

def _note_capture_summary(
    *,
    chapter_layers: list[ChapterLayer],
    chapter_marker_counts: Mapping[str, int],
    page_marker_counts_by_chapter: Mapping[str, Mapping[str, int]],
    mode_by_chapter: Mapping[str, str],
    book_type: str,
) -> tuple[bool, dict[str, Any]]:
    chapter_rows: list[dict[str, Any]] = []
    sparse_chapter_ids: list[str] = []
    sparse_pages: list[dict[str, Any]] = []
    expected_total = 0
    captured_total = 0
    for chapter in chapter_layers:
        chapter_id = str(chapter.chapter_id or "")
        note_mode = str(mode_by_chapter.get(chapter_id) or "no_notes")
        expected_count = int(chapter_marker_counts.get(chapter_id) or 0)
        if note_mode == "footnote_primary":
            captured_count = int(len(chapter.footnote_items or []))
        elif note_mode in {"chapter_endnote_primary", "book_endnote_bound"}:
            captured_count = int(len(chapter.endnote_items or []))
        else:
            captured_count = int(len(chapter.footnote_items or [])) + int(len(chapter.endnote_items or []))
        expected_total += expected_count
        captured_total += captured_count
        ratio = float(captured_count / expected_count) if expected_count > 0 else 1.0
        chapter_row = {
            "chapter_id": chapter_id,
            "note_mode": note_mode,
            "expected_anchor_count": expected_count,
            "captured_note_count": captured_count,
            "capture_ratio": round(ratio, 4),
        }
        should_block_sparse = (
            book_type in {"footnote_only", "endnote_only"}
            or (book_type == "no_notes" and note_mode == "no_notes")
        )
        if should_block_sparse and expected_count >= 10 and ratio < 0.6:
            sparse_chapter_ids.append(chapter_id)
            chapter_row["sparse_capture"] = True
        chapter_rows.append(chapter_row)
        page_counts = dict(page_marker_counts_by_chapter.get(chapter_id) or {})
        # 同时收集 footnote 和 endnote items 的页码——之前只取 footnote_items，
        # 导致 book_endnote_bound / chapter_endnote_primary 章的 captured_pages
        # 始终为空，dense_anchor_zero_capture_pages 全为假阳性。
        captured_pages: set[int] = set()
        for item in list(chapter.footnote_items or []):
            pn = int(item.page_no)
            if pn > 0:
                captured_pages.add(pn)
        for item in list(chapter.endnote_items or []):
            pn = int(item.page_no)
            if pn > 0:
                captured_pages.add(pn)
        # 对 book_endnote_bound 章，尾注条目在全书尾注区（不在正文页），逐页比对无意义，
        # 跳过 dense_anchor_zero_capture_pages 检查。
        skip_page_check = note_mode == "book_endnote_bound"
        for page_no_str, expected_page_count in page_counts.items():
            try:
                page_no = int(page_no_str)
            except (TypeError, ValueError):
                continue
            expected_page_count = int(expected_page_count or 0)
            if (
                not skip_page_check
                and should_block_sparse
                and expected_page_count >= 8
                and page_no not in captured_pages
            ):
                sparse_pages.append(
                    {
                        "chapter_id": chapter_id,
                        "page_no": page_no,
                        "expected_anchor_count": expected_page_count,
                        "captured_note_count": 0,
                    }
                )
    summary = {
        "expected_anchor_count": int(expected_total),
        "captured_note_count": int(captured_total),
        "capture_ratio": round(float(captured_total / expected_total), 4) if expected_total > 0 else 1.0,
        "sparse_capture_chapter_ids": sparse_chapter_ids,
        "dense_anchor_zero_capture_pages": sparse_pages[:24],
        "chapters": chapter_rows[:32],
    }
    return bool(not sparse_chapter_ids and not sparse_pages), summary

def _chapter_binding_summary(
    *,
    layer_regions: list[LayerNoteRegion],
    layer_items: list[LayerNoteItem],
    chapter_ids: set[str],
) -> dict[str, Any]:
    unbound_region_ids = [
        str(region.region_id or "")
        for region in layer_regions
        if str(region.owner_chapter_id or region.chapter_id or "").strip() not in chapter_ids
    ]
    book_scope_region_ids = [
        str(region.region_id or "")
        for region in layer_regions
        if str(region.source_scope or region.scope or "") == "book"
    ]
    unassigned_item_ids = [
        str(item.note_item_id or "")
        for item in layer_items
        if str(item.owner_chapter_id or item.chapter_id or "").strip() not in chapter_ids
    ]
    return {
        "region_count": len(layer_regions),
        "book_scope_region_count": len(book_scope_region_ids),
        "unbound_region_count": len(unbound_region_ids),
        "unbound_region_ids_preview": unbound_region_ids[:16],
        "unassigned_item_count": len(unassigned_item_ids),
        "unassigned_item_ids_preview": unassigned_item_ids[:16],
    }

def build_chapter_layers(
    toc_structure: TocStructure,
    book_note_profile: BookNoteProfile,
    pages: list[dict],
    *,
    pdf_path: str = "",
    page_text_map: Mapping[int | str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
    max_body_chars: int = 6000,
    endnote_explorer_hints: Mapping[str, Any] | None = None,
    heading_candidates: list[Any] | None = None,
) -> ModuleResult[ChapterLayers]:
    phase1 = _phase1_from_toc_structure_with_evidence(
        toc_structure,
        heading_candidates=heading_candidates,
        endnote_explorer_hints=endnote_explorer_hints,
    )
    note_regions, region_summary = build_note_regions(
        phase1,
        pages=pages,
        pdf_path=str(pdf_path or ""),
        page_text_map=page_text_map,
        endnote_explorer_hints=endnote_explorer_hints,
    )
    note_items, item_summary = build_note_items(
        note_regions,
        phase1,
        pages=pages,
        pdf_path=str(pdf_path or ""),
        page_text_map=page_text_map,
    )
    # 工单 #2：回填 NoteRegionRecord.region_first_note_item_marker（之前 4 处
    # 硬编码空字符串）。按 region_id 取该 region 内首条 note item 的归一化 marker，
    # 供契约校验和取证报告使用。
    _first_marker_by_region: dict[str, str] = {}
    for note_item in note_items:
        rid = str(note_item.region_id or "")
        if not rid or rid in _first_marker_by_region:
            continue
        marker = str(
            getattr(note_item, "normalized_marker", "")
            or getattr(note_item, "marker", "")
            or ""
        ).strip()
        if marker:
            _first_marker_by_region[rid] = marker
    for region in note_regions:
        rid = str(region.region_id or "")
        if not str(region.region_first_note_item_marker or "").strip():
            region.region_first_note_item_marker = _first_marker_by_region.get(rid, "")
    # 阶段3：扩展章节 end_page 以包含绑定的 endnote region
    for region in note_regions:
        if str(region.note_kind or "") != "endnote" or str(region.scope or "") != "chapter":
            continue
        cid = str(region.chapter_id or "").strip()
        if not cid:
            continue
        for idx, chapter in enumerate(phase1.chapters):
            if str(chapter.chapter_id or "") != cid:
                continue
            new_end = max(int(chapter.end_page), int(region.page_end))
            new_pages = list(chapter.pages or [])
            for p in (region.pages or []):
                if int(p) not in new_pages:
                    new_pages.append(int(p))
            new_pages.sort()
            phase1.chapters[idx] = replace(chapter, end_page=new_end, pages=new_pages)
            break
    note_kind_by_region = {str(row.region_id or ""): str(row.note_kind or "") for row in note_regions}
    owner_chapter_by_region = {str(row.region_id or ""): str(row.chapter_id or "") for row in note_regions}
    source_scope_by_region = {str(row.region_id or ""): str(row.scope or "") for row in note_regions}
    layer_regions = _to_layer_regions(note_regions)
    layer_items = _to_layer_items(
        note_items,
        note_kind_by_region=note_kind_by_region,
        owner_chapter_by_region=owner_chapter_by_region,
        source_scope_by_region=source_scope_by_region,
    )
    _project_endnotes_by_marker(
        layer_regions=layer_regions,
        layer_items=layer_items,
        chapter_marker_sets=_chapter_body_marker_sets(phase1=phase1, pages=pages),
        chapter_order=[str(chapter.chapter_id or "") for chapter in phase1.chapters if str(chapter.chapter_id or "").strip()],
        book_type=str(book_note_profile.book_type or ""),
    )
    _fallback_assign_unowned_endnotes(
        phase1=phase1,
        layer_regions=layer_regions,
        layer_items=layer_items,
    )
    chapter_layers, cross_page_counts, layer_diag = _build_chapter_layers(
        toc_structure=toc_structure,
        phase1=phase1,
        pages=pages,
        regions=note_regions,
        layer_regions=layer_regions,
        layer_items=layer_items,
        book_note_profile=book_note_profile,
    )

    allow_empty_region_ids, empty_region_override_logs = _normalize_empty_region_overrides(overrides)
    empty_region_ids = [str(row) for row in list(item_summary.get("empty_region_ids") or []) if str(row)]
    unresolved_empty_region_ids = [region_id for region_id in empty_region_ids if region_id not in allow_empty_region_ids]
    remaining_orphan_regions = [
        row.region_id
        for row in layer_regions
        if not (str(row.chapter_id or "").strip() or str(row.scope or "") == "book")
    ]
    chapter_ids = {str(row.chapter_id or "") for row in toc_structure.chapters if str(row.chapter_id or "").strip()}
    remaining_orphan_regions.extend(
        row.region_id
        for row in layer_regions
        if str(row.scope or "") == "chapter" and str(row.chapter_id or "") not in chapter_ids
    )
    remaining_orphan_regions = sorted(set(remaining_orphan_regions))

    policy_missing_chapters = [row.chapter_id for row in chapter_layers if not row.policy_applied]
    disjoint_violations = list(layer_diag.get("chapter_disjoint_violations") or [])
    chapters_without_body = list(layer_diag.get("chapters_without_body") or [])
    char_drop_candidates = list(layer_diag.get("char_drop_candidates") or [])

    book_type = str(book_note_profile.book_type or "")
    chapter_mode_by_id = {str(row.chapter_id or ""): str(row.note_mode or "no_notes") for row in book_note_profile.chapter_modes}
    if book_type == "footnote_only":
        footnote_only_ok, footnote_only_evidence = _synthesize_footnote_only_markers(
            chapter_layers=chapter_layers,
            mode_by_chapter=chapter_mode_by_id,
        )
    else:
        footnote_only_ok = True
        footnote_only_evidence = {"status": "not_applicable", "reason": f"book_type={book_type}"}

    if book_type == "mixed":
        mixed_materialized_ok = True
        mixed_materialized_evidence = {
            "status": "not_required",
            "reason": "mixed_book_does_not_require_marker_materialization_in_split_stage",
        }
    else:
        mixed_materialized_ok = True
        mixed_materialized_evidence = {"status": "not_applicable", "reason": f"book_type={book_type}"}

    chapter_ids = {str(row.chapter_id or "") for row in toc_structure.chapters if str(row.chapter_id or "").strip()}
    binding_summary = _chapter_binding_summary(
        layer_regions=layer_regions,
        layer_items=layer_items,
        chapter_ids=chapter_ids,
    )
    note_capture_ok, note_capture_summary = _note_capture_summary(
        chapter_layers=chapter_layers,
        chapter_marker_counts=dict(layer_diag.get("chapter_marker_counts") or {}),
        page_marker_counts_by_chapter=dict(layer_diag.get("page_marker_counts_by_chapter") or {}),
        mode_by_chapter=chapter_mode_by_id,
        book_type=book_type,
    )
    footnote_synthesis_summary = {
        "book_type": book_type,
        **dict(footnote_only_evidence or {}),
    }

    hard = {
        "split.regions_bound": len(remaining_orphan_regions) == 0 and int(binding_summary.get("unbound_region_count") or 0) == 0,
        "split.items_extracted": (
            len(unresolved_empty_region_ids) == 0
            and int(binding_summary.get("unassigned_item_count") or 0) == 0
            and bool(note_capture_ok)
        ),
        "split.body_note_disjoint": len(disjoint_violations) == 0,
        "split.cross_page_continuity_ok": len(chapters_without_body) == 0,
        "split.policy_applied": len(policy_missing_chapters) == 0,
        "split.footnote_only_synthesized": bool(footnote_only_ok),
        "split.mixed_marker_materialized": bool(mixed_materialized_ok),
    }
    soft = {
        "split.char_drop_warn": len(char_drop_candidates) == 0,
    }
    reasons: list[str] = []
    if not hard["split.regions_bound"]:
        reasons.append("split_regions_unbound")
    if not hard["split.items_extracted"]:
        if len(unresolved_empty_region_ids) > 0:
            reasons.append("split_items_empty_regions")
        if int(binding_summary.get("unassigned_item_count") or 0) > 0:
            reasons.append("split_items_unassigned_owner")
        if not note_capture_ok:
            reasons.append("split_items_sparse_note_capture")
    if not hard["split.body_note_disjoint"]:
        reasons.append("split_body_note_overlap")
    if not hard["split.cross_page_continuity_ok"]:
        reasons.append("split_cross_page_continuity_missing")
    if not hard["split.policy_applied"]:
        reasons.append("split_policy_missing")
    if not hard["split.footnote_only_synthesized"]:
        reasons.append("split_footnote_only_synthesis_failed")
    if not hard["split.mixed_marker_materialized"]:
        reasons.append("split_mixed_marker_materialization_failed")

    evidence = {
        "region_summary": {
            **dict(region_summary or {}),
            "chapter_binding_summary": dict(binding_summary),
        },
        "item_summary": {
            **dict(item_summary or {}),
            "note_capture_summary": dict(note_capture_summary),
            "footnote_synthesis_summary": dict(footnote_synthesis_summary),
        },
        "remaining_orphan_region_ids": remaining_orphan_regions,
        "unresolved_empty_region_ids": unresolved_empty_region_ids,
        "chapter_disjoint_violations": disjoint_violations,
        "chapters_without_body": chapters_without_body,
        "cross_page_counts": {str(key): int(value) for key, value in cross_page_counts.items()},
        "char_drop_candidates": char_drop_candidates,
        "footnote_only_synthesized": footnote_only_evidence,
        "mixed_marker_materialized": mixed_materialized_evidence,
        "book_type": book_type,
        "chapter_binding_summary": dict(binding_summary),
        "note_capture_summary": dict(note_capture_summary),
        "footnote_synthesis_summary": dict(footnote_synthesis_summary),
    }
    diagnostics = {
        **dict(layer_diag),
        "max_body_chars": int(max_body_chars or 6000),
        "empty_region_ids": empty_region_ids,
        "allow_empty_region_ids": sorted(allow_empty_region_ids),
    }
    gate_report = GateReport(
        module="split",
        hard=hard,
        soft=soft,
        reasons=reasons,
        evidence=evidence,
        overrides_used=list(empty_region_override_logs),
    )
    data = ChapterLayers(
        chapters=chapter_layers,
        regions=layer_regions,
        note_items=layer_items,
        region_summary={
            **dict(region_summary or {}),
            "chapter_binding_summary": dict(binding_summary),
        },
        item_summary={
            **dict(item_summary or {}),
            "note_capture_summary": dict(note_capture_summary),
            "footnote_synthesis_summary": dict(footnote_synthesis_summary),
        },
        chapter_marker_counts=dict(layer_diag.get("chapter_marker_counts") or {}),
    )
    return ModuleResult(
        data=data,
        gate_report=gate_report,
        evidence=evidence,
        overrides_used=list(empty_region_override_logs),
        diagnostics=diagnostics,
    )

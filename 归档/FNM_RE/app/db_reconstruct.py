"""从 DB 重建 Phase 1-2 数据结构，使下游 Phase 可独立子进程运行。"""
from __future__ import annotations
from typing import Any
import json


def reconstruct_toc_structure(repo, doc_id: str):
    """从 fnm_chapters + fnm_section_heads + fnm_pages 重建 TocStructure。"""
    from FNM_RE.modules.types import TocChapter, TocSectionHead, TocStructure, TocPageRole

    chapters_raw = repo.list_fnm_chapters(doc_id) or []
    sections_raw = repo.list_fnm_section_heads(doc_id) or []
    pages_raw = repo.list_fnm_pages(doc_id) or []

    chapters = [
        TocChapter(
            chapter_id=str(r.get("chapter_id") or ""),
            title=str(r.get("title") or ""),
            start_page=int(r.get("start_page") or 0),
            end_page=int(r.get("end_page") or 0),
            pages=json.loads(r.get("pages_json") or "[]"),
            source=str(r.get("source") or "fallback"),
            boundary_state=str(r.get("boundary_state") or "ready"),
        )
        for r in chapters_raw
    ]
    section_heads = [
        TocSectionHead(
            section_head_id=str(r.get("section_head_id") or ""),
            chapter_id=str(r.get("chapter_id") or ""),
            title=str(r.get("text") or ""),
            page_no=int(r.get("page_no") or 0),
            level=1,
            source=str(r.get("source") or "computed"),
        )
        for r in sections_raw
    ]
    pages = [
        TocPageRole(
            page_no=int(r.get("page_no") or 0),
            role=str(r.get("page_role") or "other"),
            source_role=str(r.get("section_hint") or ""),
            reason=str(r.get("role_reason") or ""),
            chapter_id="",
        )
        for r in pages_raw
    ]
    # 从章节区间回填 page → chapter_id 映射
    _page_to_chapter: dict[int, str] = {}
    for ch in chapters:
        for pn in range(ch.start_page, ch.end_page + 1):
            _page_to_chapter.setdefault(pn, ch.chapter_id)
    for p in pages:
        ch_id = _page_to_chapter.get(p.page_no, "")
        if ch_id:
            p.chapter_id = ch_id

    return TocStructure(
        chapters=chapters,
        section_heads=section_heads,
        pages=pages,
    )


def reconstruct_book_note_profile(repo, doc_id: str):
    """从 fnm_chapter_note_modes 重建 BookNoteProfile。"""
    from FNM_RE.modules.types import BookNoteProfile, ChapterNoteMode, BookNoteTypeEvidence

    modes_raw = repo.list_fnm_chapter_note_modes(doc_id) or []

    from FNM_RE.shared.note_modes import from_db_alias
    chapter_modes: list[ChapterNoteMode] = []
    note_mode_chapter_ids: list[str] = []
    for r in modes_raw:
        # DB 存的是 alias（如 body_only/chapter_endnotes），还原为 canonical NoteMode
        raw_mode = str(r.get("note_mode") or "no_notes")
        canonical_mode = from_db_alias(raw_mode)
        chapter_modes.append(ChapterNoteMode(
            chapter_id=str(r.get("chapter_id") or ""),
            note_mode=canonical_mode,  # type: ignore[arg-type]
            evidence_page_nos=json.loads(r.get("sampled_pages_json") or "[]"),
        ))
        if canonical_mode not in ("no_notes", ""):
            note_mode_chapter_ids.append(str(r.get("chapter_id") or ""))

    # 推导 book_type（精确判断 canonical mode，不再 substring 启发式）
    canonical_modes = {str(m.note_mode or "") for m in chapter_modes}
    if not note_mode_chapter_ids:
        book_type = "no_notes"
    elif "footnote_primary" in canonical_modes:
        book_type = "mixed"
    elif canonical_modes & {"chapter_endnote_primary", "book_endnote_bound"}:
        book_type = "endnote_only"
    else:
        book_type = "no_notes"

    return BookNoteProfile(
        book_type=book_type,
        chapter_modes=chapter_modes,
        evidence=BookNoteTypeEvidence(),
    )


def reconstruct_chapter_layers(repo, doc_id: str):
    """从 DB 重建 ChapterLayers（Phase 2 产物）。

    数据来源：
    - fnm_chapter_body_pages → 每章 body_pages/body_segments
    - fnm_note_regions → LayerNoteRegion 列表
    - fnm_note_items → LayerNoteItem 列表
    - fnm_chapter_note_modes → BookStructureModel（book_structure）
    """
    from FNM_RE.modules.types import (
        ChapterLayers, ChapterLayer, LayerNoteRegion, LayerNoteItem,
        BodyPageLayer, BodySegmentLayer, BookStructureModel,
    )

    body_pages_all = _list_chapter_body_pages_all(repo, doc_id)
    regions_raw = repo.list_fnm_note_regions(doc_id) or []
    note_items_raw = repo.list_fnm_note_items(doc_id) or []
    modes_raw = repo.list_fnm_chapter_note_modes(doc_id) or []

    # ── 章节层 ──
    # 按 chapter_id 聚合 body_pages / body_segments
    body_by_chapter: dict[str, list[BodyPageLayer]] = {}
    segments_by_chapter: dict[str, list[BodySegmentLayer]] = {}
    for row in body_pages_all:
        ch_id = str(row.get("chapter_id") or "")
        bp_raw = row.get("body_pages_json")
        # body_pages_json 可能是 JSON 字符串，也可能是已解析的 dict
        if isinstance(bp_raw, str):
            bp_raw = json.loads(bp_raw)
        if isinstance(bp_raw, dict):
            bp_list = bp_raw.get("body_pages") or []
            seg_list = bp_raw.get("body_segments") or []
        elif isinstance(bp_raw, list):
            bp_list = bp_raw
            seg_list = []
        else:
            bp_list = []
            seg_list = []
        body_pages = [BodyPageLayer(
            page_no=int(bp.get("page_no") or 0),
            text=str(bp.get("text") or ""),
            split_reason=str(bp.get("split_reason") or ""),
            source_role=str(bp.get("source_role") or ""),
        ) for bp in bp_list if isinstance(bp, dict)]
        body_segments = [BodySegmentLayer(
            page_no=int(seg.get("page_no") or 0),
            paragraph_count=int(seg.get("paragraph_count") or 1),
            source_text=str(seg.get("source_text") or seg.get("display_text") or ""),
            display_text=str(seg.get("display_text") or seg.get("source_text") or ""),
        ) for seg in seg_list if isinstance(seg, dict)]
        body_by_chapter[ch_id] = body_pages
        segments_by_chapter[ch_id] = body_segments

    # ── Region 层 ──
    regions: list[LayerNoteRegion] = []
    for r in regions_raw:
        pages = json.loads(r.get("pages_json") or "[]")
        region_kind = str(r.get("region_kind") or "footnote")
        note_kind = _region_kind_to_note_kind(region_kind)
        scope = _region_kind_to_scope(region_kind)
        regions.append(LayerNoteRegion(
            region_id=str(r.get("region_id") or ""),
            chapter_id=str(r.get("bound_chapter_id") or ""),
            page_start=int(r.get("start_page") or 0),
            page_end=int(r.get("end_page") or 0),
            pages=pages,
            note_kind=note_kind,
            scope=scope,
            source="db_reconstruct",
            heading_text=str(r.get("title_hint") or ""),
            review_required=False,
            region_first_note_item_marker=str(r.get("region_first_note_item_marker") or ""),
        ))

    # ── Note item 层 ──
    note_items: list[LayerNoteItem] = []
    region_kind_by_id: dict[str, str] = {
        str(r.get("region_id") or ""): str(r.get("region_kind") or "")
        for r in regions_raw
    }
    for ni in note_items_raw:
        region_id = str(ni.get("region_id") or "")
        note_kind = _region_kind_to_note_kind(region_kind_by_id.get(region_id, ""))
        note_items.append(LayerNoteItem(
            note_item_id=str(ni.get("note_item_id") or ""),
            region_id=region_id,
            chapter_id=str(ni.get("chapter_id") or ""),
            page_no=int(ni.get("page_no") or 0),
            marker=str(ni.get("marker") or ""),
            marker_type=str(ni.get("note_kind") or "footnote"),
            text=str(ni.get("source_text") or ""),
            source="db_reconstruct",
            is_reconstructed=False,
            review_required=False,
            note_kind=note_kind,
            source_marker=str(ni.get("source_marker") or ""),
            normalized_marker=str(ni.get("normalized_marker") or ""),
        ))

    # ── 聚合章节 footnotes/endnotes ──
    chapters: list[ChapterLayer] = []
    all_chapter_ids = set(body_by_chapter.keys()) | {ni.chapter_id for ni in note_items}
    for ch_id in sorted(all_chapter_ids):
        ch_footnotes = [ni for ni in note_items if ni.chapter_id == ch_id and ni.note_kind == "footnote"]
        ch_endnotes = [ni for ni in note_items if ni.chapter_id == ch_id and ni.note_kind == "endnote"]
        ch_regions = [r for r in regions if r.chapter_id == ch_id and r.scope == "chapter"]
        chapters.append(ChapterLayer(
            chapter_id=ch_id,
            title="",
            body_pages=body_by_chapter.get(ch_id, []),
            body_segments=segments_by_chapter.get(ch_id, []),
            footnote_items=ch_footnotes,
            endnote_items=ch_endnotes,
            endnote_regions=ch_regions,
        ))

    # ── BookStructureModel ──
    from FNM_RE.shared.note_modes import from_db_alias
    book_type: str = "no_notes"
    for m in modes_raw:
        canonical = from_db_alias(str(m.get("note_mode") or ""))
        if canonical not in ("no_notes", ""):
            book_type = canonical
            break

    from FNM_RE.modules.types import ChapterStructureModel
    chapter_models = []
    for m in modes_raw:
        chapter_models.append(ChapterStructureModel(
            chapter_id=str(m.get("chapter_id") or ""),
            note_mode=from_db_alias(str(m.get("note_mode") or "no_notes")),
            has_explicit_notes_heading=False,
        ))
    book_structure = BookStructureModel(
        book_type=book_type,
        chapters=chapter_models,
    )

    return ChapterLayers(
        chapters=chapters,
        regions=regions,
        note_items=note_items,
        book_structure=book_structure,
    )


# ── 内部辅助 ──

def _region_kind_to_note_kind(region_kind: str) -> str:
    kind = str(region_kind or "").lower()
    if kind == "footnote":
        return "footnote"
    if kind in ("chapter_endnotes", "book_endnotes", "endnote"):
        return "endnote"
    return "footnote"


def _region_kind_to_scope(region_kind: str) -> str:
    kind = str(region_kind or "").lower()
    if kind == "book_endnotes":
        return "book"
    return "chapter"


def _list_chapter_body_pages_all(repo, doc_id: str) -> list[dict]:
    """读取 fnm_chapter_body_pages 全部行。"""
    list_fn = getattr(repo, "list_fnm_chapter_body_pages_all", None)
    if callable(list_fn):
        try:
            return list_fn(doc_id) or []
        except Exception:
            pass
    return []

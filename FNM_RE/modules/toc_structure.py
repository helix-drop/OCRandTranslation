"""阶段 1 模块：目录结构与章节骨架。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from FNM_RE.modules.contracts import GateReport, ModuleResult
from FNM_RE.modules.types import TocChapter, TocNode, TocPageRole, TocSectionHead, TocStructure
from FNM_RE.shared.title import chapter_title_match_key, normalize_title
from FNM_RE.stages.chapter_skeleton import build_chapter_skeleton
from FNM_RE.stages.page_partition import build_page_partitions, summarize_page_partitions
from FNM_RE.stages.section_heads import build_section_heads
from FNM_RE.shared.notes import _safe_int

_BACK_MATTER_REASON_HINTS = {
    "appendix",
    "bibliography",
    "index",
    "illustrations",
    "rear_toc_tail",
    "rear_author_blurb",
    "rear_sparse_other",
}

def _normalize_toc_node_role(value: Any) -> str:
    role = str(value or "").strip().lower().replace("-", "_")
    if role in {"container", "endnotes", "chapter", "section", "post_body", "back_matter", "front_matter"}:
        return role
    if role == "part":
        return "container"
    if role in {"notes", "endnotes"}:
        return "endnotes"
    if role == "book_title":
        return "front_matter"
    return ""

def _map_toc_role(
    title: str,
    *,
    explicit_role: str,
    title_key: str,
    container_keys: set[str],
    endnotes_keys: set[str],
    post_body_keys: set[str],
    back_matter_keys: set[str],
    chapter_keys: set[str],
) -> str:
    normalized_explicit_role = _normalize_toc_node_role(explicit_role)
    if normalized_explicit_role:
        return normalized_explicit_role
    if title_key in container_keys:
        return "container"
    if title_key in endnotes_keys:
        return "endnotes"
    if title_key in post_body_keys:
        return "post_body"
    if title_key in back_matter_keys:
        return "back_matter"
    if title_key in chapter_keys:
        return "chapter"
    normalized = normalize_title(title).lower()
    if "endnote" in normalized or normalized == "notes" or normalized.startswith("notes "):
        return "endnotes"
    if any(token in normalized for token in ("bibliograph", "index", "appendix", "references")):
        return "back_matter"
    return "chapter"

def _build_toc_tree(
    toc_items: list[dict] | None,
    *,
    chapter_rows: list[TocChapter],
    meta: Mapping[str, Any],
) -> list[TocNode]:
    normalized_toc_rows = list(meta.get("normalized_toc_rows") or [])
    title_keys = {chapter_title_match_key(row.title) for row in chapter_rows}
    container_keys = {chapter_title_match_key(title) for title in list(meta.get("container_titles") or [])}
    endnotes_keys = {chapter_title_match_key(title) for title in list(meta.get("endnotes_titles") or [])}
    post_body_keys = {chapter_title_match_key(title) for title in list(meta.get("post_body_titles") or [])}
    back_matter_keys = {chapter_title_match_key(title) for title in list(meta.get("back_matter_titles") or [])}
    nodes: list[TocNode] = []
    source_rows = normalized_toc_rows if normalized_toc_rows else list(toc_items or [])
    for index, item in enumerate(source_rows, start=1):
        title = normalize_title(str(item.get("title") or ""))
        if not title:
            continue
        title_key = chapter_title_match_key(title)
        explicit_role = str(
            item.get("semantic_role")
            or item.get("role_hint")
            or item.get("explicit_role_hint")
            or ""
        )
        role = _map_toc_role(
            title,
            explicit_role=explicit_role,
            title_key=title_key,
            container_keys=container_keys,
            endnotes_keys=endnotes_keys,
            post_body_keys=post_body_keys,
            back_matter_keys=back_matter_keys,
            chapter_keys=title_keys,
        )
        target_pdf_page = _safe_int(item.get("target_pdf_page") or item.get("page_no") or 0)
        nodes.append(
            TocNode(
                node_id=str(item.get("item_id") or f"toc-node-{index:04d}"),
                title=title,
                role=role,  # type: ignore[arg-type]
                level=max(1, _safe_int(item.get("level") or 1)),
                target_pdf_page=target_pdf_page,
                parent_id=str(item.get("parent_id") or item.get("parent_title") or ""),
            )
        )
    return nodes

def _build_chapters(chapters: list[Any], *, meta: Mapping[str, Any]) -> list[TocChapter]:
    post_body_keys = {chapter_title_match_key(title) for title in list(meta.get("post_body_titles") or [])}
    rows: list[TocChapter] = []
    for row in chapters:
        title = normalize_title(str(getattr(row, "title", "") or ""))
        role = "post_body" if chapter_title_match_key(title) in post_body_keys else "chapter"
        rows.append(
            TocChapter(
                chapter_id=str(getattr(row, "chapter_id", "") or ""),
                title=title,
                start_page=_safe_int(getattr(row, "start_page", 0)),
                end_page=_safe_int(getattr(row, "end_page", 0)),
                pages=[_safe_int(page_no) for page_no in list(getattr(row, "pages", []) or []) if _safe_int(page_no) > 0],
                role=role,  # type: ignore[arg-type]
                source=str(getattr(row, "source", "fallback") or "fallback"),  # type: ignore[arg-type]
                boundary_state=str(getattr(row, "boundary_state", "ready") or "ready"),  # type: ignore[arg-type]
            )
        )
    rows.sort(key=lambda item: (item.start_page, item.chapter_id))
    return rows

def _build_page_roles(
    partitions: list[Any],
    *,
    chapters: list[TocChapter],
    back_matter_start_hint: int = 0,
) -> list[TocPageRole]:
    chapter_by_page: dict[int, TocChapter] = {}
    for chapter in chapters:
        for page_no in chapter.pages:
            chapter_by_page[int(page_no)] = chapter
        if chapter.start_page > 0 and chapter.end_page >= chapter.start_page:
            for page_no in range(chapter.start_page, chapter.end_page + 1):
                chapter_by_page.setdefault(page_no, chapter)

    first_chapter_start = min((int(ch.start_page) for ch in chapters if int(ch.start_page) > 0), default=0)
    total_pages = max(1, len(partitions))
    rear_page_role_min_page = max(24, int(total_pages * 0.45))
    
    if int(back_matter_start_hint or 0) > 0:
        back_matter_start = int(back_matter_start_hint)
    else:
        inferred_back_matter_start = min(
            (
                int(row.page_no)
                for row in partitions
                if str(row.reason or "") in _BACK_MATTER_REASON_HINTS 
                and int(row.page_no) > first_chapter_start
                and int(row.page_no) >= rear_page_role_min_page
            ),
            default=0,
        )
        back_matter_start = int(inferred_back_matter_start)

    rows: list[TocPageRole] = []
    for row in partitions:
        page_no = int(row.page_no)
        source_role = str(row.page_role or "").strip().lower()
        chapter = chapter_by_page.get(page_no)
        # 工单 #5：上游 note_scan（page_partition._rule_note_scan）已识别为
        # NOTES 容器页时，note 角色优先于 chapter，避免章末 NOTES 容器被
        # chapter mapping 覆盖。chapter_id 仍保留供下游 region 绑定。
        if source_role == "note":
            role = "note"
            chapter_id = chapter.chapter_id if chapter is not None else ""
        elif chapter is not None:
            role = chapter.role
            chapter_id = chapter.chapter_id
        elif page_no > 0 and back_matter_start > 0 and page_no >= back_matter_start:
            role = "back_matter"
            chapter_id = ""
        elif back_matter_start == 0 and str(row.reason or "") in _BACK_MATTER_REASON_HINTS and page_no >= rear_page_role_min_page:
            role = "back_matter"
            chapter_id = ""
        elif source_role in {"other"}:
            role = "front_matter"
            chapter_id = ""
        elif first_chapter_start > 0 and page_no < first_chapter_start:
            role = "front_matter"
            chapter_id = ""
        elif source_role == "front_matter":
            role = "front_matter"
            chapter_id = ""
        else:
            role = "front_matter"
            chapter_id = ""
        rows.append(
            TocPageRole(
                page_no=page_no,
                role=role,  # type: ignore[arg-type]
                source_role=str(row.page_role or ""),
                reason=str(row.reason or ""),
                chapter_id=chapter_id,
            )
        )
    rows.sort(key=lambda item: item.page_no)
    return rows

def _role_semantics_valid(pages: list[TocPageRole]) -> bool:
    first_back_matter_page = min((row.page_no for row in pages if row.role == "back_matter"), default=0)
    if first_back_matter_page <= 0:
        return True
    return not any(row.role == "chapter" and row.page_no > first_back_matter_page for row in pages)

def _chapter_order_monotonic(chapters: list[TocChapter], toc_tree: list[TocNode]) -> bool:
    chapter_targets = [
        int(node.target_pdf_page)
        for node in toc_tree
        if node.role in {"chapter", "post_body"} and int(node.target_pdf_page) > 0
    ]
    if len(chapter_targets) >= 2:
        return all(chapter_targets[index - 1] <= chapter_targets[index] for index in range(1, len(chapter_targets)))
    return all(chapters[index - 1].start_page <= chapters[index].start_page for index in range(1, len(chapters)))

def build_toc_structure(
    pages: list[dict],
    toc_items: list[dict] | None,
    *,
    manual_page_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    pdf_path: str = "",
    visual_toc_bundle: Mapping[str, Any] | None = None,
) -> ModuleResult[TocStructure]:
    page_partitions = build_page_partitions(pages, page_overrides=manual_page_overrides)
    heading_candidates, phase1_chapters, chapter_meta = build_chapter_skeleton(
        page_partitions,
        toc_items=toc_items,
        toc_offset=0,
        pdf_path=str(pdf_path or ""),
        pages=pages,
        visual_toc_bundle=visual_toc_bundle,
    )
    section_heads, heading_review_summary = build_section_heads(
        phase1_chapters,
        heading_candidates,
        page_partitions,
        fallback_sections=list(chapter_meta.get("fallback_sections") or []),
    )

    toc_chapters = _build_chapters(phase1_chapters, meta=chapter_meta)
    toc_tree = _build_toc_tree(toc_items, chapter_rows=toc_chapters, meta=chapter_meta)
    toc_pages = _build_page_roles(
        page_partitions,
        chapters=toc_chapters,
        back_matter_start_hint=int(chapter_meta.get("back_matter_start_page") or 0),
    )
    toc_section_heads = [
        TocSectionHead(
            section_head_id=str(row.section_head_id or ""),
            chapter_id=str(row.chapter_id or ""),
            title=str(row.title or ""),
            page_no=int(row.page_no),
            level=int(row.level),
            source=str(row.source or ""),
        )
        for row in section_heads
    ]

    hard = {
        "toc.pages_classified": bool(toc_pages) and all(
            row.role in {"front_matter", "chapter", "post_body", "back_matter", "endnotes", "container"} for row in toc_pages
        ),
        "toc.has_exportable_chapters": any(row.role == "chapter" for row in toc_chapters),
        "toc.chapter_titles_aligned": bool(chapter_meta.get("chapter_title_alignment_ok", True)),
        "toc.chapter_order_monotonic": _chapter_order_monotonic(toc_chapters, toc_tree),
        "toc.role_semantics_valid": bool(chapter_meta.get("toc_semantic_contract_ok", True))
        and _role_semantics_valid(toc_pages),
    }
    soft = {
        "toc.section_alignment_warn": bool(chapter_meta.get("chapter_section_alignment_ok", True)),
        "toc.visual_toc_conflict_warn": int(chapter_meta.get("visual_toc_conflict_count") or 0) == 0,
    }
    reasons: list[str] = []
    if not hard["toc.pages_classified"]:
        reasons.append("toc_pages_unclassified")
    if not hard["toc.has_exportable_chapters"]:
        reasons.append("toc_no_exportable_chapter")
    if not hard["toc.chapter_titles_aligned"]:
        reasons.append("toc_chapter_title_mismatch")
    if not hard["toc.chapter_order_monotonic"]:
        reasons.append("toc_chapter_order_non_monotonic")
    if not hard["toc.role_semantics_valid"]:
        reasons.append("toc_role_semantics_invalid")

    overrides_used = [
        {"kind": "page_override", "page_no": int(row.page_no), "reason": "manual_override"}
        for row in page_partitions
        if str(row.reason or "") == "manual_override"
    ]
    evidence = {
        "page_partition_summary": summarize_page_partitions(page_partitions),
        "chapter_count": len(toc_chapters),
        "exportable_chapter_count": sum(1 for row in toc_chapters if row.role == "chapter"),
        "heading_graph_summary": dict(chapter_meta.get("heading_graph_summary") or {}),
        "toc_role_summary": dict(chapter_meta.get("toc_role_summary") or {}),
    }
    diagnostics = {
        "heading_review_summary": heading_review_summary,
        "heading_graph_summary": dict(chapter_meta.get("heading_graph_summary") or {}),
        "chapter_source_summary": dict(chapter_meta.get("chapter_source_summary") or {}),
        "container_titles": list(chapter_meta.get("container_titles") or []),
        "endnotes_titles": list(chapter_meta.get("endnotes_titles") or []),
        "post_body_titles": list(chapter_meta.get("post_body_titles") or []),
        "back_matter_titles": list(chapter_meta.get("back_matter_titles") or []),
        "endnote_explorer_hints": dict(chapter_meta.get("endnote_explorer_hints") or {}),
        "heading_candidates": list(heading_candidates or []),
        "chapter_meta": dict(chapter_meta or {}),
    }

    gate_report = GateReport(
        module="toc",
        hard=hard,
        soft=soft,
        reasons=reasons,
        evidence=evidence,
        overrides_used=list(overrides_used),
    )
    data = TocStructure(
        pages=toc_pages,
        toc_tree=toc_tree,
        chapters=toc_chapters,
        section_heads=toc_section_heads,
    )
    return ModuleResult(
        data=data,
        gate_report=gate_report,
        evidence=evidence,
        overrides_used=list(overrides_used),
        diagnostics={
            **diagnostics,
            "chapter_meta": dict(chapter_meta),
            "first_three_chapters": [asdict(row) for row in toc_chapters[:3]],
        },
    )

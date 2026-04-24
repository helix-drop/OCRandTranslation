"""FNM_RE 3b 阶段：Endnote 路径（尾注页识别 + 条目解析 + 章节绑定）。

对每章：
1. 识别尾注页：page_role=note 或 _note_scan 含 endnote 条目，或页内有 notes heading
2. 连续页分组，区分 book-scope / chapter-scope
3. 条目切分：从页面 markdown 或 PDF 文本中解析编号条目
4. 章节绑定：按页面对应的 chapter_id 绑定
5. 写入 fnm_chapter_endnotes
"""

from __future__ import annotations

import re
from typing import Any

from FNM_RE.models import ChapterEndnoteRecord, Phase1Structure
from FNM_RE.shared.notes import (
    first_notes_heading,
    normalize_note_marker,
    parse_note_items_from_text,
    scan_items_by_kind,
)

_ILLUSTRATION_LIST_RE = re.compile(
    r"^\s*(?:list(?:e)?\s+(?:of\s+)?(?:illustrations?|figures?|plates?)"
    r"|liste\s+des\s+illustrations?)\b",
    re.IGNORECASE,
)


def _page_role_map(phase1: Phase1Structure) -> dict[int, str]:
    return {
        int(row.page_no): str(row.page_role)
        for row in phase1.pages
        if int(row.page_no) > 0
    }


def _chapter_id_for_page(phase1: Phase1Structure, page_no: int) -> str:
    for chapter in phase1.chapters:
        if int(page_no) in {int(p) for p in chapter.pages if int(p) > 0}:
            return chapter.chapter_id
    prior = [c for c in phase1.chapters if int(c.start_page) <= int(page_no)]
    return prior[-1].chapter_id if prior else ""


def _is_endnote_page(
    page_no: int,
    *,
    page_role_by_no: dict[int, str],
    page_by_no: dict[int, dict],
) -> bool:
    page = page_by_no.get(page_no)
    if page is None:
        return False
    role = str(page_role_by_no.get(page_no) or "")
    if role == "note":
        return True
    if role == "other":
        return bool(first_notes_heading(page))
    if scan_items_by_kind(page, kind="endnote"):
        return True
    return bool(first_notes_heading(page))


def _looks_like_illustration_list_page(
    page_no: int,
    *,
    page_by_no: dict[int, dict],
) -> bool:
    page = page_by_no.get(page_no)
    if page is None:
        return False
    md = str(page.get("markdown") or "")
    lines = [line.strip() for line in md.splitlines() if line.strip()]
    if not lines:
        return False
    stripped = lines[0].lstrip("#").strip()
    return bool(_ILLUSTRATION_LIST_RE.match(stripped))


def _split_contiguous_ranges(values: list[int]) -> list[list[int]]:
    if not values:
        return []
    ordered = sorted({int(v) for v in values if int(v) > 0})
    if not ordered:
        return []
    ranges: list[list[int]] = [[ordered[0]]]
    for value in ordered[1:]:
        current = ranges[-1]
        if value == current[-1] + 1:
            current.append(value)
        else:
            ranges.append([value])
    return ranges


def _last_chapter_end_page(phase1: Phase1Structure) -> int:
    return max((int(c.end_page) for c in phase1.chapters), default=0)


def _is_book_scope(
    page_no: int,
    last_chapter_end_page: int,
) -> bool:
    return page_no > last_chapter_end_page


def _page_markdown(page: dict | None) -> str:
    if not page:
        return ""
    return str(page.get("markdown") or "").strip()


def _parse_items_from_page(
    page: dict,
    *,
    note_kind: str,
) -> list[dict]:
    """解析单个页面的注释条目。

    优先从 markdown 文本解析；回退到 _note_scan 数据。
    """
    md = _page_markdown(page)
    if md:
        items, _ = parse_note_items_from_text(md)
        if items:
            return [
                {
                    "marker": normalize_note_marker(item.get("marker") or ""),
                    "text": str(item.get("text") or "").strip(),
                    "is_reconstructed": bool(item.get("is_reconstructed")),
                    "source": "markdown",
                }
                for item in items
                if normalize_note_marker(item.get("marker") or "")
            ]

    scan_items = scan_items_by_kind(page, kind=note_kind)
    if scan_items:
        return [
            {
                "marker": normalize_note_marker(item.get("marker") or ""),
                "text": re.sub(r"\s+", " ", str(item.get("text") or "")).strip(),
                "is_reconstructed": bool(item.get("is_reconstructed")),
                "source": "note_scan",
            }
            for item in scan_items
            if normalize_note_marker(item.get("marker") or "")
            and str(item.get("text") or "").strip()
        ]

    return []


def build_paragraph_endnotes(
    phase1: Phase1Structure,
    *,
    pages: list[dict],
    doc_id: str = "",
) -> tuple[list[ChapterEndnoteRecord], dict]:
    """构建段落级尾注条目。

    Args:
        phase1: 章节与页面角色信息
        pages: 原始页面数据（含 markdown 文本）
        doc_id: 文档 ID

    Returns:
        (ChapterEndnoteRecord 列表, 统计摘要 dict)
    """
    page_role_by_no = _page_role_map(phase1)
    page_by_no: dict[int, dict] = {}
    for p in pages:
        try:
            bp = int(p.get("bookPage") or 0)
        except (TypeError, ValueError):
            continue
        if bp > 0:
            page_by_no[bp] = dict(p)

    end_page = _last_chapter_end_page(phase1)
    sorted_page_nos = sorted(
        int(row.page_no) for row in phase1.pages if int(row.page_no) > 0
    )

    # Pass 1: 识别尾注候选页
    endnote_page_nos: list[int] = []
    for pn in sorted_page_nos:
        if not _is_endnote_page(
            pn,
            page_role_by_no=page_role_by_no,
            page_by_no=page_by_no,
        ):
            continue
        if _looks_like_illustration_list_page(pn, page_by_no=page_by_no):
            continue
        endnote_page_nos.append(pn)

    # Pass 2: 按连续页分组
    group_runs: list[list[int]] = _split_contiguous_ranges(endnote_page_nos)

    # Pass 3: 对每组分组合并解析
    all_records: list[ChapterEndnoteRecord] = []
    chapter_stats: dict[str, dict] = {}

    for run in group_runs:
        midpoint = run[len(run) // 2]
        is_book = _is_book_scope(midpoint, end_page)
        chapter_id = "" if is_book else _chapter_id_for_page(phase1, midpoint)
        if not chapter_id:
            chapter_id = _chapter_id_for_page(phase1, run[0])

        ordinal = 0
        last_marker_value: int | None = None
        used_items: list[dict] = []

        for pn in run:
            page = page_by_no.get(pn)
            if page is None:
                continue

            parsed = _parse_items_from_page(page, note_kind="endnote")
            for item in parsed:
                marker = item.get("marker", "")
                try:
                    mv = int(marker)
                except (TypeError, ValueError):
                    mv = 0
                if mv > 0 and last_marker_value is not None and mv < last_marker_value - 5:
                    # marker 大幅回退 → 可能跨越到新序列
                    continue
                ordinal += 1
                last_marker_value = mv
                used_items.append(item)

        if not used_items:
            continue

        source_page = run[0] if run else 0
        target_chapter = chapter_id if chapter_id else _chapter_id_for_page(phase1, source_page)
        if not target_chapter:
            continue

        for idx, item in enumerate(used_items):
            all_records.append(ChapterEndnoteRecord(
                doc_id=doc_id,
                chapter_id=target_chapter,
                ordinal=idx + 1,
                marker=item["marker"],
                numbering_scheme="per_chapter",
                text=item["text"],
                source_page_no=source_page,
                is_reconstructed=item.get("is_reconstructed", False),
                review_required=False,
            ))

        if target_chapter not in chapter_stats:
            chapter_stats[target_chapter] = {
                "endnote_page_count": 0,
                "endnote_item_count": 0,
            }
        chapter_stats[target_chapter]["endnote_page_count"] += len(run)
        chapter_stats[target_chapter]["endnote_item_count"] += len(used_items)

    total_items = len(all_records)
    total_chapters = len(chapter_stats)
    reconstructed_count = sum(1 for r in all_records if r.is_reconstructed)

    summary: dict[str, Any] = {
        "total_endnote_items": total_items,
        "chapter_count": total_chapters,
        "reconstructed_count": reconstructed_count,
        "chapter_stats": chapter_stats,
    }
    return all_records, summary

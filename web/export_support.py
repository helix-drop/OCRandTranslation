"""导出辅助函数。"""

from __future__ import annotations

from document.text_utils import ensure_str
from persistence.storage import (
    _build_chapter_ranges_from_depth_map,
    build_endnote_index,
    build_toc_chapters,
    build_toc_depth_map,
    build_toc_title_map,
    detect_book_index_pages,
    detect_endnote_collection_pages,
    load_effective_toc,
    load_pages_from_disk,
)
from config import get_doc_meta


def load_toc_depth_map(doc_id: str) -> dict:
    _, offset, toc_items = load_effective_toc(doc_id)
    return build_toc_depth_map(toc_items, offset)


def load_toc_title_map(doc_id: str) -> dict[int, str]:
    _, offset, toc_items = load_effective_toc(doc_id)
    return build_toc_title_map(toc_items, offset)


def load_toc_chapters_data(doc_id: str) -> list[dict]:
    _, offset, toc_items = load_effective_toc(doc_id)
    meta = get_doc_meta(doc_id) or {}
    total_pages = int(meta.get("page_count") or 0)
    return build_toc_chapters(toc_items, offset, total_pages)


def parse_bp_ranges(raw: str) -> list[tuple[int, int]]:
    result = []
    for part in (raw or "").split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                result.append((int(start), int(end)))
            except (ValueError, TypeError):
                pass
    return result


def build_endnote_data(
    doc_id: str,
    entries: list,
    toc_depth_map: dict,
    toc_title_map: dict | None = None,
    pages: list | None = None,
) -> tuple[dict, set]:
    if pages is None:
        pages, _ = load_pages_from_disk(doc_id)
    all_bps = sorted({
        int(entry.get("_pageBP") or entry.get("book_page") or 0)
        for entry in entries
        if int(entry.get("_pageBP") or entry.get("book_page") or 0) > 0
    } | {
        int(page.get("bookPage") or 0)
        for page in (pages or [])
        if int(page.get("bookPage") or 0) > 0
    })
    chapter_ranges = _build_chapter_ranges_from_depth_map(
        toc_depth_map,
        all_bps,
        toc_title_map=toc_title_map,
    )
    endnote_page_map = detect_endnote_collection_pages(entries, chapter_ranges)
    structured_bps = []
    for page in pages or []:
        scan = page.get("_note_scan") if isinstance(page, dict) else {}
        if not isinstance(scan, dict):
            continue
        if ensure_str(scan.get("page_kind", "")).strip() not in {"endnote_collection", "mixed_body_endnotes"}:
            continue
        bp = int(page.get("bookPage") or 0)
        if bp > 0:
            structured_bps.append(bp)
    if structured_bps:
        endnote_page_map = dict(endnote_page_map)
        endnote_page_map.setdefault(None, [])
        endnote_page_map[None] = sorted(set(endnote_page_map[None]) | set(structured_bps))
    endnote_index = build_endnote_index(entries, endnote_page_map, chapter_ranges=chapter_ranges, pages=pages)
    endnote_page_bps = {bp for bps in endnote_page_map.values() for bp in bps}
    index_page_bps = detect_book_index_pages(entries)
    return endnote_index, endnote_page_bps | index_page_bps

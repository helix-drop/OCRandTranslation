"""章节归属（page_no → chapter_id）共享工具。

在 5 个文件中各有一个独立副本，此处收敛为单一实现。
"""

from __future__ import annotations

from typing import Any


def chapter_id_for_page(chapters: list[Any], page_no: int) -> str:
    """给定 page_no，返回它所属的 chapter_id。

    优先精确匹配 chapter.pages 列表，其次用 start_page 找最近的前置章节。
    chapters 中的对象需要有以下属性：chapter_id, pages(list[int]), start_page(int), end_page(int)。
    """
    if not chapters or page_no <= 0:
        return ""
    page_int = int(page_no)
    # 1) 精确匹配 pages 列表
    for chapter in chapters:
        pages = getattr(chapter, "pages", None) or []
        if page_int in {int(p) for p in pages if int(p) > 0}:
            return str(getattr(chapter, "chapter_id", "") or "")
    # 2) 区间匹配 start_page..end_page
    for chapter in chapters:
        start = int(getattr(chapter, "start_page", 0) or 0)
        end = int(getattr(chapter, "end_page", 0) or 0)
        if start <= page_int <= end:
            return str(getattr(chapter, "chapter_id", "") or "")
    # 3) 最近前置章节兜底
    prior = [
        chapter
        for chapter in chapters
        if int(getattr(chapter, "start_page", 0) or 0) <= page_int
    ]
    if not prior:
        return ""
    prior.sort(key=lambda ch: (int(getattr(ch, "start_page", 0) or 0), int(getattr(ch, "end_page", 0) or 0)))
    return str(getattr(prior[-1], "chapter_id", "") or "")


def nearest_prior_chapter(chapters: list[Any], page_no: int) -> str:
    """仅用最近前置章节兜底（不检查 pages 精确匹配）。"""
    if not chapters or int(page_no or 0) <= 0:
        return ""
    page_int = int(page_no)
    prior = [
        chapter
        for chapter in chapters
        if int(getattr(chapter, "start_page", 0) or 0) <= page_int
    ]
    if not prior:
        return ""
    prior.sort(key=lambda ch: (int(getattr(ch, "start_page", 0) or 0), int(getattr(ch, "end_page", 0) or 0)))
    return str(getattr(prior[-1], "chapter_id", "") or "")

"""TOC 编辑辅助函数。"""

from __future__ import annotations

from persistence.storage import (
    load_auto_visual_toc_from_disk,
    load_pages_from_disk,
    load_toc_visual_draft,
    resolve_page_print_label,
)
from web.reading_view import _build_pdf_page_lookup


def _safe_positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _safe_nonnegative_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def resolve_toc_item_target_pdf_page(
    item: dict | None,
    *,
    offset: int | None = None,
    pages: list[dict] | None = None,
    pdf_page_by_file_idx: dict[int, int] | None = None,
) -> int | None:
    """解析目录项稳定落点：target_pdf_page > file_idx > printPageLabel > book_page+offset。"""
    if not isinstance(item, dict):
        return None

    target_pdf_page = _safe_positive_int(item.get("target_pdf_page"))
    if target_pdf_page is not None:
        return target_pdf_page

    raw_pdf_page = _safe_positive_int(item.get("pdf_page"))
    if raw_pdf_page is not None:
        return raw_pdf_page

    file_idx = _safe_nonnegative_int(item.get("file_idx"))
    if file_idx is not None:
        zero_based_idx = int(file_idx) - 1 if int(file_idx) > 0 and pdf_page_by_file_idx and int(file_idx) not in pdf_page_by_file_idx and (int(file_idx) - 1) in pdf_page_by_file_idx else int(file_idx)
        if pdf_page_by_file_idx and zero_based_idx in pdf_page_by_file_idx:
            return int(pdf_page_by_file_idx[zero_based_idx])

    book_page = _safe_positive_int(item.get("book_page"))
    if pages and book_page is not None:
        for page in pages:
            if _safe_positive_int(resolve_page_print_label(page)) == book_page:
                resolved_pdf_page = _safe_positive_int(page.get("bookPage"))
                if resolved_pdf_page is not None:
                    return resolved_pdf_page

    if book_page is not None and offset is not None:
        candidate = book_page + int(offset or 0)
        return candidate if candidate > 0 else None

    return None


def visual_toc_base_for_draft_merge(doc_id: str) -> list[dict]:
    """草稿存在则以草稿条目为合并基底，否则以 SQLite 自动视觉目录为基底。"""
    draft = load_toc_visual_draft(doc_id)
    if draft:
        items, _ = draft
        return list(items or [])
    return load_auto_visual_toc_from_disk(doc_id) or []


def merge_auto_visual_submission(
    doc_id: str,
    submitted_items: list,
    visual_toc: list[dict],
) -> tuple[list[dict] | None, int, str | None]:
    """将前端提交的目录行合并到 visual_toc 基底。"""
    if not visual_toc:
        return None, 0, "当前没有可调整的自动视觉目录"

    existing_by_id = {}
    for item in visual_toc:
        item_id = str(item.get("item_id", "") or "").strip()
        if not item_id:
            return None, 0, "自动视觉目录缺少稳定条目标识，暂时无法手动调整"
        existing_by_id[item_id] = item

    submitted_ids = [str((item or {}).get("item_id", "") or "").strip() for item in submitted_items]
    if len(set(submitted_ids)) != len(submitted_ids):
        return None, 0, "目录项 ID 重复，请刷新后重试"
    if not set(submitted_ids).issubset(set(existing_by_id.keys())):
        return None, 0, "目录项集合已变化，请刷新后重试"

    pages, _ = load_pages_from_disk(doc_id)
    page_by_pdf_page, _ = _build_pdf_page_lookup(pages)
    updated_items = []
    unresolved_count = 0

    for visual_order, raw_item in enumerate(submitted_items, start=1):
        item_id = str((raw_item or {}).get("item_id", "") or "").strip()
        current_item = dict(existing_by_id[item_id])
        title = str((raw_item or {}).get("title", "") or "").strip()
        if not title:
            return None, 0, "目录标题不能为空"
        try:
            depth = int((raw_item or {}).get("depth", 0))
        except (TypeError, ValueError):
            return None, 0, "目录深度必须为整数"
        if depth < 0:
            return None, 0, "目录深度不能小于 0"

        has_pdf_page = "pdf_page" in (raw_item or {})
        raw_pdf_page = (raw_item or {}).get("pdf_page")
        target_file_idx = current_item.get("file_idx")
        target_pdf_page = _safe_positive_int(current_item.get("target_pdf_page"))
        if has_pdf_page:
            if raw_pdf_page in ("", None):
                target_file_idx = None
                target_pdf_page = None
            else:
                try:
                    pdf_page = int(raw_pdf_page)
                except (TypeError, ValueError):
                    return None, 0, "PDF 页码必须为整数"
                if pdf_page < 1:
                    return None, 0, "PDF 页码必须大于等于 1"
                target_page = page_by_pdf_page.get(pdf_page)
                if not target_page:
                    return None, 0, f"未找到 PDF 第 {pdf_page} 页"
                try:
                    target_file_idx = int(target_page.get("fileIdx"))
                except (TypeError, ValueError):
                    return None, 0, f"PDF 第 {pdf_page} 页缺少可用页码映射"
                target_pdf_page = int(pdf_page)

        current_item["title"] = title
        current_item["depth"] = depth
        current_item["visual_order"] = visual_order
        current_item["resolved_by_user"] = True
        current_item["resolution_source"] = "manual_edit"
        if target_file_idx is None:
            current_item.pop("file_idx", None)
            current_item.pop("target_pdf_page", None)
            unresolved_count += 1
        else:
            current_item["file_idx"] = int(target_file_idx)
            if target_pdf_page is not None:
                current_item["target_pdf_page"] = int(target_pdf_page)
        updated_items.append(current_item)

    return updated_items, unresolved_count, None


def visual_items_to_user_rows(
    items: list[dict],
    toc_offset: int,
    pdf_page_by_file_idx: dict,
) -> list[dict]:
    rows = []
    off = int(toc_offset or 0)
    for item in items:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        try:
            depth = max(0, int(item.get("depth") or 0))
        except (TypeError, ValueError):
            depth = 0
        bp_raw = item.get("book_page")
        if bp_raw is not None:
            try:
                book_page = max(1, int(bp_raw))
            except (TypeError, ValueError):
                book_page = 1
        else:
            file_idx = item.get("file_idx")
            pdf_page = None
            if file_idx is not None:
                try:
                    pdf_page = pdf_page_by_file_idx.get(int(file_idx))
                except (TypeError, ValueError):
                    pdf_page = None
            if pdf_page is not None:
                book_page = max(1, int(pdf_page) - off)
            else:
                book_page = 1
        target_pdf_page = resolve_toc_item_target_pdf_page(
            item,
            offset=off,
            pdf_page_by_file_idx=pdf_page_by_file_idx,
        )
        row = {"title": title, "depth": depth, "book_page": book_page}
        if target_pdf_page is not None:
            row["target_pdf_page"] = int(target_pdf_page)
        rows.append(row)
    return rows


def guess_toc_offset(new_items: list[dict], auto_toc: list[dict], pages: list[dict] | None = None) -> tuple[int, str]:
    if not new_items or not auto_toc:
        return 0, ""
    _page_by_pdf, pdf_page_by_file_idx = _build_pdf_page_lookup(pages or [])
    for new_item in new_items[:5]:
        new_title = (new_item.get("title") or "").strip().lower()
        book_page = new_item.get("book_page")
        if not new_title or not book_page:
            continue
        for auto_item in auto_toc:
            auto_title = (auto_item.get("title") or "").strip().lower()
            if new_title in auto_title or auto_title in new_title:
                resolved_pdf_page = resolve_toc_item_target_pdf_page(
                    auto_item,
                    pages=pages,
                    pdf_page_by_file_idx=pdf_page_by_file_idx,
                )
                if resolved_pdf_page is None:
                    file_idx = auto_item.get("file_idx")
                    if file_idx is None:
                        continue
                    resolved_pdf_page = int(file_idx) + 1
                offset = int(resolved_pdf_page) - int(book_page)
                return max(0, offset), auto_item.get("title", "")
    return 0, ""

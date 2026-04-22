"""开发者模式：产物表单行查询。

只给诊断抽屉用，故：
  - 只允许白名单表。
  - `row_value == "*"` 时返回全表（裁到 `MAX_ROWS`）。
  - 其余情况按给定 `row_key` 过滤并返回匹配行。
"""
from __future__ import annotations

from typing import Any


MAX_ROWS = 500

# 表名 -> (repo 方法名, 允许的过滤字段集合)
_TABLE_SPEC: dict[str, tuple[str, set[str]]] = {
    "fnm_pages": ("list_fnm_pages", {"book_page", "page_no"}),
    "fnm_chapters": ("list_fnm_chapters", {"chapter_id"}),
    "fnm_section_heads": ("list_fnm_section_heads", {"chapter_id", "page_no"}),
    "fnm_heading_candidates": (
        "list_fnm_heading_candidates",
        {"chapter_id", "page_no"},
    ),
    "fnm_note_regions": ("list_fnm_note_regions", {"region_id", "chapter_id"}),
    "fnm_chapter_note_modes": (
        "list_fnm_chapter_note_modes",
        {"chapter_id"},
    ),
    "fnm_note_items": ("list_fnm_note_items", {"note_id", "region_id", "page_no"}),
    "fnm_body_anchors": (
        "list_fnm_body_anchors",
        {"anchor_id", "chapter_id", "page_no"},
    ),
    "fnm_note_links": ("list_fnm_note_links", {"link_id", "anchor_id", "note_id"}),
}


class LookupError(Exception):
    pass


def allowed_tables() -> list[str]:
    return sorted(_TABLE_SPEC.keys())


def lookup_artifact(
    repo,
    doc_id: str,
    table: str,
    row_key: str,
    row_value: str,
) -> dict[str, Any]:
    """按 (table, row_key, row_value) 查询产物行。

    返回 `{"ok": True, "table": ..., "rows": [...], "truncated": bool}`。
    找不到行（且非通配）时 `rows` 为空但仍 ok。
    非法 table / row_key 抛 `LookupError`。
    """
    if table not in _TABLE_SPEC:
        raise LookupError(f"表 {table!r} 不在白名单内")
    method_name, allowed_keys = _TABLE_SPEC[table]
    method = getattr(repo, method_name, None)
    if method is None:
        raise LookupError(f"repo 缺 {method_name}")

    rows = method(doc_id) or []

    if row_value == "*" or row_key in ("doc_id",):
        truncated = len(rows) > MAX_ROWS
        return {
            "ok": True,
            "table": table,
            "row_key": row_key,
            "row_value": row_value,
            "rows": rows[:MAX_ROWS],
            "truncated": truncated,
            "total": len(rows),
        }

    if row_key not in allowed_keys:
        raise LookupError(
            f"字段 {row_key!r} 不在表 {table} 的允许过滤字段内：{sorted(allowed_keys)}"
        )

    filtered: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        val = row.get(row_key)
        if val is None:
            continue
        if str(val) == str(row_value):
            filtered.append(row)

    return {
        "ok": True,
        "table": table,
        "row_key": row_key,
        "row_value": row_value,
        "rows": filtered,
        "truncated": False,
        "total": len(filtered),
    }


__all__ = ["allowed_tables", "lookup_artifact", "LookupError", "MAX_ROWS"]

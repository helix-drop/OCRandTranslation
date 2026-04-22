"""翻译路由辅助函数。"""

from __future__ import annotations

import persistence.storage as storage
import translation.translate_runtime as translate_runtime
from web.reading_view import _get_partial_failed_bps


def build_translate_usage_payload(
    doc_id: str,
    *,
    entries: list[dict] | None = None,
    snapshot: dict | None = None,
) -> dict:
    """构建翻译 API 使用情况页面/接口的数据。"""
    pages, _ = storage.load_pages_from_disk(doc_id)
    visible_page_view = storage.load_visible_page_view(doc_id, pages=pages)
    if entries is None:
        entries, doc_title, _ = storage.load_entries_from_disk(doc_id, pages=pages)
    else:
        _, doc_title, _ = storage.load_entries_from_disk(doc_id, pages=pages)
    if snapshot is None:
        snapshot = translate_runtime.get_translate_snapshot(
            doc_id,
            pages=pages,
            entries=entries,
            visible_page_view=visible_page_view,
        )
    if snapshot.get("partial_failed_bps") is None:
        snapshot["partial_failed_bps"] = _get_partial_failed_bps(doc_id, entries=entries)
    pages_payload = []
    total_manual_revisions = 0
    pages_with_manual_revisions = 0
    for entry in entries:
        usage = entry.get("_usage") or {}
        manual_revision_count = sum(
            1
            for seg in (entry.get("_page_entries") or [])
            if isinstance(seg, dict) and seg.get("_translation_source") == "manual"
        )
        total_manual_revisions += manual_revision_count
        if manual_revision_count > 0:
            pages_with_manual_revisions += 1
        pages_payload.append({
            "page_bp": entry.get("_pageBP"),
            "model": entry.get("_model", ""),
            "request_count": int(usage.get("request_count", 0) or 0),
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
            "manual_revision_count": manual_revision_count,
        })
    return {
        "doc_id": doc_id,
        "doc_title": doc_title,
        "snapshot": snapshot,
        "pages": pages_payload,
        "total_manual_revisions": total_manual_revisions,
        "pages_with_manual_revisions": pages_with_manual_revisions,
    }

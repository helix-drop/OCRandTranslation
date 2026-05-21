"""结构化 review overrides 分组共享工具。

3 个文件（pipeline.py, mainline.py, note_linking.py）中原各有一份副本。
"""

from __future__ import annotations

from typing import Any, Mapping


_KNOWN_SCOPES = {"page", "chapter", "region", "link", "llm_suggestion", "anchor", "note_item"}


def empty_grouped_overrides() -> dict[str, dict[str, dict]]:
    return {scope: {} for scope in _KNOWN_SCOPES}


def group_review_overrides(review_overrides: Any) -> dict[str, dict[str, dict]]:
    grouped = empty_grouped_overrides()
    if not review_overrides:
        return grouped
    if isinstance(review_overrides, list):
        for row in review_overrides:
            payload = dict(row or {})
            scope = str(payload.get("scope") or "").strip().lower()
            target_id = str(payload.get("target_id") or "").strip()
            data = dict(payload.get("payload") or {})
            if not scope or not target_id:
                continue
            grouped.setdefault(scope, {})[target_id] = data
        return grouped
    if isinstance(review_overrides, Mapping):
        if any(str(key) in _KNOWN_SCOPES for key in review_overrides.keys()):
            for scope, rows in dict(review_overrides).items():
                scope_key = str(scope or "").strip().lower()
                if scope_key not in _KNOWN_SCOPES:
                    continue
                if not isinstance(rows, Mapping):
                    continue
                grouped[scope_key] = {
                    str(target_id): dict(payload or {})
                    for target_id, payload in dict(rows).items()
                    if str(target_id or "").strip()
                }
            return grouped
    return grouped

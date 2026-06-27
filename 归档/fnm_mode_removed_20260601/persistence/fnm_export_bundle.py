"""FNM 章节包持久化。"""

from __future__ import annotations

import json
import os
from typing import Any

from config import get_doc_dir


FNM_EXPORT_BUNDLE_FILENAME = "fnm_export_bundle.json"


def resolve_fnm_export_bundle_path(doc_id: str) -> str:
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return ""
    return os.path.join(doc_dir, FNM_EXPORT_BUNDLE_FILENAME)


def load_fnm_export_bundle(doc_id: str) -> dict[str, Any] | None:
    path = resolve_fnm_export_bundle_path(doc_id)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        return None
    return dict(payload) if isinstance(payload, dict) else None


def save_fnm_export_bundle(doc_id: str, payload: dict[str, Any]) -> str:
    path = resolve_fnm_export_bundle_path(doc_id)
    if not path:
        return ""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dict(payload or {}), fh, ensure_ascii=False, indent=2)
    return path


def clear_fnm_export_bundle(doc_id: str) -> str:
    path = resolve_fnm_export_bundle_path(doc_id)
    if path and os.path.isfile(path):
        os.remove(path)
    return path


__all__ = [
    "FNM_EXPORT_BUNDLE_FILENAME",
    "clear_fnm_export_bundle",
    "load_fnm_export_bundle",
    "resolve_fnm_export_bundle_path",
    "save_fnm_export_bundle",
]

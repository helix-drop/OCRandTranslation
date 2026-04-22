"""Web 层通用 helper。"""

from __future__ import annotations

import re
import time

from flask import request


def request_doc_id(normalize_doc_id_fn, get_current_doc_id_fn) -> str:
    raw = normalize_doc_id_fn(request.values.get("doc_id", ""))
    return raw or get_current_doc_id_fn()


def normalize_reading_view(view: str | None) -> str:
    normalized = str(view or "standard").strip().lower()
    return normalized if normalized in {"standard", "fnm"} else "standard"


def parse_bool_flag(raw: str) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', " ", name).strip()


def format_unix_ts(ts: int | float | None) -> str:
    if not ts:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return ""

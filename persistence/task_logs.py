"""文档级任务日志 helper。"""

from __future__ import annotations

import os
import re
import time

from config import get_doc_dir


_TASK_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _slugify_task_kind(task_kind: str) -> str:
    raw = str(task_kind or "").strip().lower()
    if not raw:
        return "task"
    normalized = _TASK_SLUG_RE.sub("_", raw).strip("_")
    return normalized or "task"


def _timestamp_label(started_at: float | None = None) -> str:
    ts = float(started_at or time.time())
    whole = int(ts)
    ms = int(round((ts - whole) * 1000))
    if ms >= 1000:
        whole += 1
        ms = 0
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(whole)) + f"-{ms:03d}"


def resolve_doc_task_log_path(doc_id: str, log_relpath: str) -> str:
    doc_dir = get_doc_dir(doc_id)
    rel = str(log_relpath or "").strip()
    if not doc_dir or not rel:
        return ""
    return os.path.join(doc_dir, rel)


def create_doc_task_log(
    doc_id: str,
    task_kind: str,
    *,
    task_id: str | None = None,
    started_at: float | None = None,
) -> str:
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return ""
    logs_dir = os.path.join(doc_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    filename = f"{_slugify_task_kind(task_kind)}_{_timestamp_label(started_at)}"
    if task_id:
        filename += f"_{_slugify_task_kind(task_id)}"
    filename += ".log"
    abs_path = os.path.join(logs_dir, filename)
    with open(abs_path, "a", encoding="utf-8"):
        pass
    return os.path.join("logs", filename)


def append_doc_task_log(
    doc_id: str,
    log_relpath: str,
    message: str,
    *,
    level: str = "INFO",
) -> str:
    abs_path = resolve_doc_task_log_path(doc_id, log_relpath)
    if not abs_path:
        return ""
    normalized = str(message or "").strip()
    if not normalized:
        return abs_path
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{str(level or 'INFO').upper()}] {normalized}\n"
    with open(abs_path, "a", encoding="utf-8") as fh:
        fh.write(line)
    return abs_path


__all__ = [
    "append_doc_task_log",
    "create_doc_task_log",
    "resolve_doc_task_log_path",
]

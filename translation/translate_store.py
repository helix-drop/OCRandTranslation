"""翻译状态持久化 helper。"""

import time

from persistence.sqlite_store import SQLiteRepository
from translation.translate_state import (
    _default_translate_state,
    _default_stream_draft_state,
    _normalize_stream_draft,
    _normalize_translate_task_meta,
    _normalize_translate_state,
)


def _save_translate_state(doc_id: str, running: bool, stop_requested: bool, **extra):
    """保存翻译状态到 SQLite。"""
    if not doc_id:
        return
    state = _load_translate_state(doc_id)
    state.update(extra)
    state["doc_id"] = doc_id
    state["running"] = running
    state["stop_requested"] = stop_requested
    if "phase" not in extra:
        state["phase"] = "stopping" if stop_requested else ("running" if running else state.get("phase", "idle"))
    state["total_tokens"] = state.get("prompt_tokens", 0) + state.get("completion_tokens", 0)
    state["updated_at"] = time.time()
    payload = dict(state)
    payload.pop("doc_id", None)
    SQLiteRepository().save_translate_run(doc_id, **payload)


def _load_translate_state(doc_id: str) -> dict:
    """从 SQLite 加载翻译状态。"""
    default = _default_translate_state(doc_id)
    if not doc_id:
        return default
    repo = SQLiteRepository()
    data = repo.get_effective_translate_run(doc_id)
    if not isinstance(data, dict):
        return default
    default.update(data)
    failures = repo.list_translate_failures(doc_id)
    if failures:
        default["failed_pages"] = failures
        default["failed_bps"] = [int(item["bp"]) for item in failures if item.get("bp") is not None]
    default["doc_id"] = doc_id
    default["task"] = _normalize_translate_task_meta(default.get("task"))
    default["draft"] = _normalize_stream_draft(default.get("draft"))
    if not isinstance(default.get("failed_bps"), list):
        default["failed_bps"] = []
    if not isinstance(default.get("partial_failed_bps"), list):
        default["partial_failed_bps"] = []
    if not isinstance(default.get("failed_pages"), list):
        default["failed_pages"] = []
    return _normalize_translate_state(default)


def _clear_translate_state(doc_id: str):
    """清除 SQLite 中的翻译状态。"""
    if doc_id:
        SQLiteRepository().clear_translate_runs(doc_id)


def _save_stream_draft(doc_id: str, **fields):
    if not doc_id:
        return
    snapshot = _load_translate_state(doc_id)
    draft = _normalize_stream_draft(snapshot.get("draft"))
    draft.update(fields)
    draft = _normalize_stream_draft(draft)
    draft["updated_at"] = time.time()
    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        phase=snapshot.get("phase", "idle"),
        draft=draft,
    )


def _clear_failed_page_state(doc_id: str, bp: int):
    if not doc_id or bp is None:
        return
    snapshot = _load_translate_state(doc_id)
    failed_pages = [
        page for page in snapshot.get("failed_pages", [])
        if isinstance(page, dict) and page.get("bp") != bp
    ]
    failed_bps = [page.get("bp") for page in failed_pages if page.get("bp") is not None]
    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        phase=snapshot.get("phase", "idle"),
        failed_pages=failed_pages,
        failed_bps=sorted(failed_bps),
    )


def _mark_failed_page_state(doc_id: str, bp: int, error: str):
    if not doc_id or bp is None:
        return
    snapshot = _load_translate_state(doc_id)
    failed_pages = [
        page for page in snapshot.get("failed_pages", [])
        if isinstance(page, dict) and page.get("bp") != bp
    ]
    failed_pages.append({
        "bp": bp,
        "error": str(error),
        "updated_at": time.time(),
    })
    failed_pages.sort(key=lambda page: page.get("bp") or 0)
    failed_bps = [page.get("bp") for page in failed_pages if page.get("bp") is not None]
    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        phase=snapshot.get("phase", "idle"),
        failed_pages=failed_pages,
        failed_bps=failed_bps,
        last_error=str(error),
    )

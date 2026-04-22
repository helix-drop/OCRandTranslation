"""翻译运行态：模块级单例状态 + 快照读取 helper。"""

import threading
import time

from FNM_RE import build_unit_progress
from persistence.storage import load_entries_from_disk, load_pages_from_disk
from persistence.task_logs import append_doc_task_log
from document.text_processing import build_visible_page_view
from translation.translate_progress import (
    _collect_partial_failed_bps,
    _compute_resume_bp,
    _resolve_task_target_bps,
)
from translation.translate_state import (
    TASK_KIND_CONTINUOUS,
    TASK_KIND_FNM,
    TASK_KIND_GLOSSARY_RETRANSLATE,
    _default_translate_state,
    _normalize_translate_state,
    _normalize_translate_task_meta,
    _remaining_pages,
)
from translation.translate_store import _load_translate_state, _save_translate_state

# ============ 模块级翻译运行时状态（单例） ============

_translate_task = {
    "running": False,
    "events": [],
    "stop": False,
    "doc_id": "",
    "owner_token": 0,
    "log_relpath": "",
}
_translate_lock = threading.Lock()


def _translate_event_log_message(event_type: str, data: dict) -> tuple[str, str] | None:
    payload = data if isinstance(data, dict) else {}
    if event_type == "init":
        return "INFO", (
            f"翻译任务进入运行态：总量 {int(payload.get('total_pages', 0) or 0)}，"
            f"已完成 {int(payload.get('done_pages', 0) or 0)}。"
        )
    if event_type == "page_start":
        bp = payload.get("bp")
        return "INFO", f"开始处理 PDF 第{int(bp)}页。" if bp is not None else None
    if event_type == "page_done":
        bp = payload.get("bp")
        partial = bool(payload.get("partial_failed"))
        base = f"PDF 第{int(bp)}页处理完成。" if bp is not None else "页面处理完成。"
        if partial:
            base += " 本页存在部分失败段落。"
        return "INFO", base
    if event_type == "page_error":
        bp = payload.get("bp")
        msg = str(payload.get("error") or "").strip() or "未知错误"
        prefix = f"PDF 第{int(bp)}页处理失败" if bp is not None else "页面处理失败"
        return "ERROR", f"{prefix}：{msg}"
    if event_type == "all_done":
        total_units = int(payload.get("total_units", 0) or 0)
        total_pages = int(payload.get("total_pages", 0) or 0)
        if total_units:
            return "INFO", f"任务完成：共处理 {total_units} 个 unit。"
        return "INFO", f"任务完成：共处理 {total_pages} 页。"
    if event_type == "stopped":
        msg = str(payload.get("msg") or "翻译已停止").strip()
        bp = payload.get("bp")
        if bp is not None:
            msg += f" 停在 PDF 第{int(bp)}页。"
        return "WARNING", msg
    if event_type == "error":
        msg = str(payload.get("msg") or "翻译失败").strip()
        bp = payload.get("bp")
        if bp is not None:
            msg = f"PDF 第{int(bp)}页：{msg}"
        return "ERROR", msg
    if event_type == "rate_limit_wait":
        wait_s = int(payload.get("wait_seconds", 0) or 0)
        provider = str(payload.get("provider") or "").strip()
        label = f"{provider} 限流" if provider else "限流"
        return "WARNING", f"{label}，等待 {wait_s} 秒后继续。"
    if event_type == "stream_page_init":
        bp = payload.get("bp")
        para_total = int(payload.get("para_total", 0) or 0)
        return "INFO", (
            f"开始流式翻译 PDF 第{int(bp)}页，共 {para_total} 段。"
            if bp is not None else f"开始流式翻译，共 {para_total} 段。"
        )
    if event_type == "stream_page_aborted":
        bp = payload.get("bp")
        prefix = f"PDF 第{int(bp)}页流式翻译中断" if bp is not None else "流式翻译中断"
        return "WARNING", prefix
    if event_type == "stream_para_error":
        idx = payload.get("para_idx")
        msg = str(payload.get("error") or "").strip() or "未知错误"
        if idx is None:
            return "ERROR", f"段落翻译失败：{msg}"
        return "ERROR", f"第 {int(idx) + 1} 段翻译失败：{msg}"
    return None


def translate_push(event_type: str, data: dict):
    doc_id = ""
    log_relpath = ""
    with _translate_lock:
        _translate_task["events"].append((event_type, data))
        doc_id = str(_translate_task.get("doc_id") or "").strip()
        log_relpath = str(_translate_task.get("log_relpath") or "").strip()
    message = _translate_event_log_message(event_type, data)
    if doc_id and log_relpath and message:
        level, text = message
        append_doc_task_log(doc_id, log_relpath, text, level=level)


def get_translate_state() -> dict:
    """获取翻译任务状态（线程安全）。"""
    with _translate_lock:
        state = _load_translate_state(_translate_task["doc_id"]) if _translate_task["doc_id"] else _default_translate_state()
        return {
            "running": _translate_task["running"],
            "events": list(_translate_task["events"]),
            "doc_id": _translate_task["doc_id"],
            "state": state,
        }


def get_translate_events(cursor: int, doc_id: str) -> tuple[list, bool]:
    """获取从 cursor 开始的翻译事件，返回 (events, running)。"""
    with _translate_lock:
        if _translate_task["doc_id"] != doc_id:
            return [], False
        events = _translate_task["events"][cursor:]
        running = _translate_task["running"]
    return events, running


def has_active_translate_task() -> bool:
    """是否有任何后台翻译任务正在运行。"""
    with _translate_lock:
        return _translate_task["running"]


def get_translate_snapshot(
    doc_id: str,
    *,
    pages: list | None = None,
    entries: list[dict] | None = None,
    visible_page_view: dict | None = None,
) -> dict:
    """获取指定文档的翻译快照。"""
    if not doc_id:
        return _default_translate_state()
    state = _load_translate_state(doc_id)
    has_active_worker = False
    with _translate_lock:
        if _translate_task["doc_id"] == doc_id:
            has_active_worker = True
            state["running"] = _translate_task["running"]
            state["stop_requested"] = _translate_task["stop"]
            if state["running"] and state["phase"] not in ("running", "stopping"):
                state["phase"] = "stopping" if state["stop_requested"] else "running"
    state = _normalize_translate_state(state, assume_inactive=not has_active_worker)
    if pages is None:
        pages, _ = load_pages_from_disk(doc_id)
    if visible_page_view is None:
        visible_page_view = build_visible_page_view(pages)
    target_bps = _resolve_task_target_bps(pages, state, visible_page_view=visible_page_view)
    target_bp_set = set(target_bps)
    task_kind = _normalize_translate_task_meta(state.get("task")).get("kind")
    if task_kind == TASK_KIND_FNM:
        unit_progress = build_unit_progress(doc_id, snapshot=state)
        state.update(unit_progress)
        state["partial_failed_bps"] = []
        if (
            not state.get("running")
            and unit_progress.get("total_units", 0)
            and unit_progress.get("processed_units", 0) >= unit_progress.get("total_units", 0)
            and unit_progress.get("error_units", 0) > 0
        ):
            state["phase"] = "partial_failed"
        state["resume_bp"] = _compute_resume_bp(
            doc_id,
            state,
            pages=pages,
            entries=entries,
            target_bps=target_bps,
            partial_failed_bps=[],
            visible_page_view=visible_page_view,
        )
        return state
    should_reconcile_page_counts = bool(target_bps) and task_kind != TASK_KIND_FNM and (
        bool(visible_page_view.get("hidden_placeholder_bps"))
        or task_kind in (TASK_KIND_CONTINUOUS, TASK_KIND_GLOSSARY_RETRANSLATE)
    )
    if should_reconcile_page_counts:
        entries, _, _ = load_entries_from_disk(doc_id, pages=pages)
        state["failed_pages"] = [
            page for page in state.get("failed_pages", [])
            if isinstance(page, dict) and page.get("bp") is not None and int(page.get("bp")) in target_bp_set
        ]
        state["failed_bps"] = sorted(
            int(page.get("bp"))
            for page in state["failed_pages"]
            if page.get("bp") is not None
        )
        translated_bps = {
            int(entry.get("_pageBP"))
            for entry in entries
            if entry.get("_pageBP") is not None and int(entry.get("_pageBP")) in target_bp_set
        }
        total_pages = len(target_bps)
        partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps, entries=entries)
        done_bps = translated_bps - set(partial_failed_bps)
        processed_bps = translated_bps | set(state["failed_bps"])
        state["total_pages"] = total_pages
        state["done_pages"] = min(total_pages, len(done_bps))
        state["processed_pages"] = min(total_pages, len(processed_bps))
        state["pending_pages"] = _remaining_pages(total_pages, state["processed_pages"])
    partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps, entries=entries)
    state["partial_failed_bps"] = partial_failed_bps
    if (
        partial_failed_bps
        and not state.get("running")
        and state.get("phase") not in ("running", "stopping", "error")
        and state.get("pending_pages", 0) == 0
    ):
        state["phase"] = "partial_failed"
    state["resume_bp"] = _compute_resume_bp(
        doc_id,
        state,
        pages=pages,
        entries=entries,
        target_bps=target_bps,
        partial_failed_bps=partial_failed_bps,
        visible_page_view=visible_page_view,
    )
    return state


def is_translate_running(doc_id: str) -> bool:
    """检查指定文档的翻译是否正在运行。"""
    if not doc_id:
        return False
    return get_translate_snapshot(doc_id)["running"]


def is_stop_requested(doc_id: str) -> bool:
    """检查是否请求了停止翻译。"""
    if not doc_id:
        return False
    return get_translate_snapshot(doc_id).get("stop_requested", False)


def runtime_stop_requested(doc_id: str) -> bool:
    """读取运行时 stop 标记，避免并发下被旧快照覆盖。"""
    if not doc_id:
        return False
    with _translate_lock:
        return bool(
            _translate_task["running"]
            and _translate_task["doc_id"] == doc_id
            and _translate_task["stop"]
        )


def request_stop_translate(doc_id: str) -> bool:
    """请求停止指定文档的翻译。"""
    if not doc_id:
        return False
    with _translate_lock:
        if not _translate_task["running"] or _translate_task["doc_id"] != doc_id:
            return False
        _translate_task["stop"] = True
    snapshot = _load_translate_state(doc_id)
    _save_translate_state(
        doc_id,
        running=True,
        stop_requested=True,
        phase="stopping",
        total_pages=snapshot.get("total_pages", 0),
        done_pages=snapshot.get("done_pages", 0),
        processed_pages=snapshot.get("processed_pages", snapshot.get("done_pages", 0)),
        pending_pages=snapshot.get("pending_pages", 0),
        current_bp=snapshot.get("current_bp"),
        current_page_idx=snapshot.get("current_page_idx", 0),
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=snapshot.get("model", ""),
        last_error=snapshot.get("last_error", ""),
    )
    return True


def request_stop_active_translate() -> bool:
    """请求停止当前活动翻译任务（不关心 doc_id）。"""
    with _translate_lock:
        running = _translate_task.get("running", False)
        active_doc_id = _translate_task.get("doc_id", "")
    if not running or not active_doc_id:
        return False
    return request_stop_translate(active_doc_id)


def wait_for_translate_idle(timeout_s: float = 3.0, poll_interval_s: float = 0.05) -> bool:
    """等待后台翻译进入空闲状态。"""
    deadline = time.time() + max(0.0, float(timeout_s))
    interval = max(0.01, float(poll_interval_s))
    while time.time() <= deadline:
        with _translate_lock:
            if not _translate_task.get("running", False):
                return True
        time.sleep(interval)
    with _translate_lock:
        return not _translate_task.get("running", False)


# ============ 运行时 claim / release ============

def claim_translate_runtime(doc_id: str) -> int | None:
    """尝试获取翻译运行时所有权，返回 owner_token 或 None（已被占用）。"""
    with _translate_lock:
        if _translate_task["running"]:
            return None
        next_owner_token = int(_translate_task.get("owner_token", 0) or 0) + 1
        _translate_task["running"] = True
        _translate_task["stop"] = False
        _translate_task["events"] = []
        _translate_task["doc_id"] = doc_id
        _translate_task["owner_token"] = next_owner_token
        _translate_task["log_relpath"] = ""
    return next_owner_token


def set_translate_runtime_log_path(log_relpath: str) -> None:
    with _translate_lock:
        _translate_task["log_relpath"] = str(log_relpath or "").strip()


def release_translate_runtime(expected_owner_token: int | None = None):
    """释放翻译运行时（worker 完成后调用）。"""
    with _translate_lock:
        current_owner_token = int(_translate_task.get("owner_token", 0) or 0)
        if expected_owner_token is not None and current_owner_token != int(expected_owner_token):
            return
        _translate_task["running"] = False
        _translate_task["stop"] = False
        _translate_task["doc_id"] = ""
        _translate_task["log_relpath"] = ""


def get_current_owner_token() -> int:
    """获取当前 owner_token（供 worker deps 使用）。"""
    with _translate_lock:
        return int(_translate_task.get("owner_token", 0) or 0)

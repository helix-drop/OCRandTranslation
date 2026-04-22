"""翻译页进度与状态收口 helper。"""

from persistence.storage import load_entries_from_disk, load_pages_from_disk
from document.text_processing import build_visible_page_view, resolve_visible_page_bp
from translation.translate_state import _normalize_translate_task_meta, _remaining_pages
from translation.translate_store import (
    _clear_failed_page_state,
    _load_translate_state,
    _mark_failed_page_state,
    _save_translate_state,
)


def _entry_has_paragraph_error(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    return any((page_entry.get("_status") == "error") for page_entry in entry.get("_page_entries", []))


def _collect_partial_failed_bps(
    doc_id: str,
    target_bps: list[int] | None = None,
    entries: list[dict] | None = None,
) -> list[int]:
    if not doc_id:
        return []
    target_bp_set = set(target_bps) if target_bps else None
    if entries is None:
        entries, _, _ = load_entries_from_disk(doc_id)
    partial_failed = set()
    for entry in entries:
        bp = entry.get("_pageBP")
        if bp is None:
            continue
        bp = int(bp)
        if target_bp_set is not None and bp not in target_bp_set:
            continue
        if _entry_has_paragraph_error(entry):
            partial_failed.add(bp)
    return sorted(partial_failed)


def _collect_target_bps(
    pages: list,
    start_bp: int | None,
    visible_page_view: dict | None = None,
) -> list[int]:
    view = visible_page_view or build_visible_page_view(pages)
    visible_page_bps = view["visible_page_bps"]
    if not visible_page_bps:
        return []
    resolved_start_bp = resolve_visible_page_bp(pages, start_bp)
    if resolved_start_bp is None:
        resolved_start_bp = visible_page_bps[0]
    start_index = visible_page_bps.index(resolved_start_bp)
    return visible_page_bps[start_index:]


def _resolve_task_target_bps(
    pages: list[dict],
    state: dict,
    *,
    visible_page_view: dict | None = None,
) -> list[int]:
    task = _normalize_translate_task_meta((state or {}).get("task"))
    target_bps = list(task.get("target_bps") or [])
    if target_bps:
        visible_bps = set((visible_page_view or build_visible_page_view(pages)).get("visible_page_bps") or [])
        filtered = [bp for bp in target_bps if not visible_bps or bp in visible_bps]
        if filtered:
            return filtered
    return _collect_target_bps(pages, (state or {}).get("start_bp"), visible_page_view=visible_page_view)


def _compute_resume_bp(
    doc_id: str,
    state: dict,
    *,
    pages: list | None = None,
    entries: list[dict] | None = None,
    target_bps: list[int] | None = None,
    partial_failed_bps: list[int] | None = None,
    visible_page_view: dict | None = None,
) -> int | None:
    if not doc_id or not isinstance(state, dict):
        return None
    phase = state.get("phase", "idle")
    if phase in ("idle", "done"):
        return None
    task = _normalize_translate_task_meta(state.get("task"))
    if task.get("kind") == "fnm":
        from persistence.sqlite_store import SQLiteRepository
        repo = SQLiteRepository()
        units = repo.list_fnm_translation_units(doc_id)
        if not units:
            return None
        target_bps = list(range(1, len(units) + 1))
        done_set = set()
        failed_set = set()
        for idx, unit in enumerate(units, start=1):
            st = unit.get("status")
            if st == "done":
                done_set.add(idx)
            elif st == "error":
                failed_set.add(idx)
        processed_bps = done_set | failed_set
        current_bp = state.get("current_bp")
        current_bp = int(current_bp) if current_bp is not None else None
        if phase == "partial_failed":
            for bp in target_bps:
                if bp in failed_set:
                    return bp
            return None
        if phase == "error" and current_bp in target_bps and current_bp not in processed_bps:
            return current_bp
        if phase == "stopped" and current_bp in target_bps and current_bp not in processed_bps:
            return current_bp
        for bp in target_bps:
            if bp not in processed_bps:
                return bp
        return None
    if pages is None:
        pages, _ = load_pages_from_disk(doc_id)
    if target_bps is None:
        target_bps = _resolve_task_target_bps(pages, state, visible_page_view=visible_page_view)
    if not target_bps:
        return None
    if entries is None:
        entries, _, _ = load_entries_from_disk(doc_id, pages=pages)
    translated_bps = {
        int(entry.get("_pageBP"))
        for entry in entries
        if entry.get("_pageBP") is not None and int(entry.get("_pageBP")) in target_bps
    }
    failed_bps = {
        int(bp)
        for bp in state.get("failed_bps", [])
        if bp is not None and int(bp) in target_bps
    }
    partial_failed_bps = {
        int(bp)
        for bp in (
            partial_failed_bps
            if partial_failed_bps is not None
            else state.get("partial_failed_bps", [])
        )
        if bp is not None and int(bp) in target_bps
    }
    processed_bps = translated_bps | failed_bps
    current_bp = state.get("current_bp")
    current_bp = int(current_bp) if current_bp is not None else None

    if phase == "partial_failed":
        for bp in target_bps:
            if bp in failed_bps or bp in partial_failed_bps:
                return bp
        return None

    if phase == "error" and current_bp in target_bps:
        return current_bp

    if phase == "stopped" and current_bp in target_bps and current_bp not in processed_bps:
        return current_bp

    for bp in target_bps:
        if bp not in processed_bps:
            return bp
    return None


def _translated_bps_for_target(entries: list[dict], target_bps: list[int]) -> set[int]:
    return {
        int(entry.get("_pageBP"))
        for entry in entries
        if entry.get("_pageBP") is not None and (not target_bps or int(entry.get("_pageBP")) in target_bps)
    }


def _filtered_failed_pages(snapshot: dict, target_bps: list[int]) -> list[dict]:
    return [
        page for page in snapshot.get("failed_pages", [])
        if isinstance(page, dict) and page.get("bp") is not None and (not target_bps or int(page.get("bp")) in target_bps)
    ]


def _build_reconcile_payload(
    snapshot: dict,
    *,
    target_bps: list[int],
    translated_bps: set[int],
    partial_failed_bps: list[int],
    current_bp: int | None,
    failure_error: str | None = None,
) -> dict:
    total_pages = len(target_bps) if target_bps else int(snapshot.get("total_pages", 0) or 0)
    done_bps = translated_bps - set(partial_failed_bps)
    done_pages = min(total_pages, len(done_bps)) if total_pages else len(done_bps)
    failed_pages = _filtered_failed_pages(snapshot, target_bps)
    failed_bps = sorted(int(page.get("bp")) for page in failed_pages)
    processed_floor = len(set(failed_bps) | translated_bps)
    processed_pages = max(processed_floor, int(snapshot.get("processed_pages", done_pages) or 0))
    if total_pages:
        processed_pages = min(total_pages, processed_pages)
    pending_pages = _remaining_pages(total_pages, processed_pages)
    previous_phase = snapshot.get("phase", "idle")

    if snapshot.get("running", False):
        phase = "stopping" if snapshot.get("stop_requested", False) else "running"
    elif failure_error is None:
        if failed_bps or partial_failed_bps:
            phase = "partial_failed" if pending_pages == 0 else previous_phase
            if phase == "done":
                phase = "partial_failed"
        else:
            if pending_pages == 0 and total_pages:
                phase = "done"
            elif previous_phase in ("error", "partial_failed"):
                phase = "stopped"
            else:
                phase = previous_phase
    else:
        if pending_pages == 0 and (failed_bps or partial_failed_bps):
            phase = "partial_failed"
        elif previous_phase in ("error", "partial_failed", "stopped"):
            phase = previous_phase
        else:
            phase = "stopped"

    return {
        "phase": phase,
        "total_pages": total_pages,
        "done_pages": done_pages,
        "processed_pages": processed_pages,
        "pending_pages": pending_pages,
        "current_bp": current_bp,
        "current_page_idx": snapshot.get("current_page_idx", 0),
        "translated_chars": snapshot.get("translated_chars", 0),
        "translated_paras": snapshot.get("translated_paras", 0),
        "request_count": snapshot.get("request_count", 0),
        "prompt_tokens": snapshot.get("prompt_tokens", 0),
        "completion_tokens": snapshot.get("completion_tokens", 0),
        "model": snapshot.get("model", ""),
        "failed_pages": failed_pages,
        "failed_bps": failed_bps,
        "partial_failed_bps": partial_failed_bps,
        "last_error": str(failure_error) if failure_error is not None else (failed_pages[0].get("error", "") if failed_pages else ""),
    }


def reconcile_translate_state_after_page_success(doc_id: str, bp: int):
    if not doc_id or bp is None:
        return
    _clear_failed_page_state(doc_id, bp)
    snapshot = _load_translate_state(doc_id)
    task = _normalize_translate_task_meta(snapshot.get("task"))
    if task.get("kind") == "fnm":
        return
    pages, _ = load_pages_from_disk(doc_id)
    target_bps = _resolve_task_target_bps(pages, snapshot)
    entries, _, _ = load_entries_from_disk(doc_id, pages=pages)
    partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps, entries=entries)
    translated_bps = _translated_bps_for_target(entries, target_bps)
    payload = _build_reconcile_payload(
        snapshot,
        target_bps=target_bps,
        translated_bps=translated_bps,
        partial_failed_bps=partial_failed_bps,
        current_bp=snapshot.get("current_bp"),
    )
    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        **payload,
    )


def reconcile_translate_state_after_page_failure(doc_id: str, bp: int, error: str):
    if not doc_id or bp is None:
        return
    _mark_failed_page_state(doc_id, bp, error)
    snapshot = _load_translate_state(doc_id)
    task = _normalize_translate_task_meta(snapshot.get("task"))
    if task.get("kind") == "fnm":
        return
    pages, _ = load_pages_from_disk(doc_id)
    target_bps = _resolve_task_target_bps(pages, snapshot)
    entries, _, _ = load_entries_from_disk(doc_id, pages=pages)
    partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps, entries=entries)
    translated_bps = _translated_bps_for_target(entries, target_bps)
    payload = _build_reconcile_payload(
        snapshot,
        target_bps=target_bps,
        translated_bps=translated_bps,
        partial_failed_bps=partial_failed_bps,
        current_bp=bp,
        failure_error=str(error),
    )
    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        **payload,
    )

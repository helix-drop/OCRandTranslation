"""翻译 worker 共享运行骨架。"""
import logging

from translation.translator import (
    NonRetryableProviderError,
    QuotaExceededError,
    TranslateStreamAborted,
)

logger = logging.getLogger(__name__)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _page_idx_for(worker_plan: dict, bp: int, loop_index: int) -> int:
    page_idx_by_bp = worker_plan.get("page_idx_by_bp") or {}
    resolved = page_idx_by_bp.get(int(bp))
    if resolved is not None:
        return max(0, _safe_int(resolved))
    return loop_index + 1


def _save_stopped_state(
    deps: dict,
    doc_id: str,
    snapshot: dict,
    *,
    total_pages: int,
    done_pages: int,
    current_bp,
    current_page_idx: int,
    model: str,
    partial_failed_bps: list[int] | None = None,
):
    state_total, state_done = deps["clamp_page_progress"](
        snapshot.get("total_pages", total_pages),
        snapshot.get("done_pages", done_pages),
    )
    processed_pages = snapshot.get("processed_pages", state_done)
    deps["save_translate_state"](
        doc_id,
        running=False,
        stop_requested=False,
        phase="stopped",
        total_pages=state_total,
        done_pages=state_done,
        processed_pages=processed_pages,
        pending_pages=deps["remaining_pages"](state_total, processed_pages),
        current_bp=current_bp,
        current_page_idx=snapshot.get("current_page_idx", current_page_idx),
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=snapshot.get("model", model),
        partial_failed_bps=snapshot.get("partial_failed_bps", partial_failed_bps or []),
        last_error="",
    )


def _save_page_start_state(
    deps: dict,
    doc_id: str,
    snapshot: dict,
    *,
    total_pages: int,
    done_pages: int,
    bp: int,
    current_page_idx: int,
    model: str,
):
    state_total, state_done = deps["clamp_page_progress"](
        snapshot.get("total_pages", total_pages),
        snapshot.get("done_pages", done_pages),
    )
    processed_pages = snapshot.get("processed_pages", state_done)
    stop_requested = deps["runtime_stop_requested"](doc_id)
    deps["save_translate_state"](
        doc_id,
        running=True,
        stop_requested=stop_requested,
        phase="stopping" if stop_requested else "running",
        total_pages=state_total,
        done_pages=state_done,
        processed_pages=processed_pages,
        pending_pages=deps["remaining_pages"](state_total, processed_pages),
        current_bp=bp,
        current_page_idx=current_page_idx,
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=model,
        last_error="",
    )
    return state_total, state_done


def _save_page_success_state(
    deps: dict,
    doc_id: str,
    snapshot: dict,
    *,
    worker_plan: dict,
    bp: int,
    current_page_idx: int,
    page_result: dict,
):
    total_pages = _safe_int(worker_plan.get("total_pages", 0))
    state_total, snapshot_done = deps["clamp_page_progress"](
        snapshot.get("total_pages", total_pages),
        snapshot.get("done_pages", 0),
    )
    processed_pages = min(
        state_total,
        _safe_int(snapshot.get("processed_pages", snapshot_done), snapshot_done) + 1,
    )
    page_has_partial_failure = bool(page_result.get("partial_failed"))
    done_pages = min(state_total, snapshot_done + (0 if page_has_partial_failure else 1))
    translated_chars = _safe_int(snapshot.get("translated_chars", 0)) + _safe_int(page_result.get("char_count", 0))
    translated_paras = _safe_int(snapshot.get("translated_paras", 0)) + _safe_int(page_result.get("para_count", 0))
    usage = page_result.get("usage") or {}
    request_count = _safe_int(snapshot.get("request_count", 0)) + _safe_int(usage.get("request_count", 0))
    prompt_tokens = _safe_int(snapshot.get("prompt_tokens", 0)) + _safe_int(usage.get("prompt_tokens", 0))
    completion_tokens = _safe_int(snapshot.get("completion_tokens", 0)) + _safe_int(usage.get("completion_tokens", 0))
    partial_failed_bps = deps["collect_partial_failed_bps"](doc_id, worker_plan.get("target_bps") or [])
    stop_requested = deps["runtime_stop_requested"](doc_id)
    deps["save_translate_state"](
        doc_id,
        running=True,
        stop_requested=stop_requested,
        phase="stopping" if stop_requested else "running",
        total_pages=state_total,
        done_pages=done_pages,
        processed_pages=processed_pages,
        pending_pages=deps["remaining_pages"](state_total, processed_pages),
        current_bp=bp,
        current_page_idx=current_page_idx,
        translated_chars=translated_chars,
        translated_paras=translated_paras,
        request_count=request_count,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=page_result.get("model_key", worker_plan.get("model_key", "")),
        partial_failed_bps=partial_failed_bps,
        last_error="",
    )
    return {
        "state_total": state_total,
        "done_pages": done_pages,
        "processed_pages": processed_pages,
        "translated_chars": translated_chars,
        "translated_paras": translated_paras,
        "request_count": request_count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "partial_failed_bps": partial_failed_bps,
    }


def _save_page_error_state(
    deps: dict,
    doc_id: str,
    snapshot: dict,
    *,
    worker_plan: dict,
    bp: int,
    current_page_idx: int,
    model: str,
    error: Exception,
):
    total_pages = _safe_int(worker_plan.get("total_pages", 0))
    initial_done_pages = _safe_int(worker_plan.get("initial_done_pages", 0))
    state_total, state_done = deps["clamp_page_progress"](
        snapshot.get("total_pages", total_pages),
        snapshot.get("done_pages", initial_done_pages),
    )
    next_processed_pages = min(
        state_total,
        _safe_int(snapshot.get("processed_pages", state_done), state_done) + 1,
    )
    stop_requested = bool(snapshot.get("stop_requested", False))
    deps["save_translate_state"](
        doc_id,
        running=True,
        stop_requested=stop_requested,
        phase="stopping" if stop_requested else "running",
        total_pages=state_total,
        done_pages=state_done,
        processed_pages=next_processed_pages,
        pending_pages=deps["remaining_pages"](state_total, next_processed_pages),
        current_bp=bp,
        current_page_idx=current_page_idx,
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=model,
        partial_failed_bps=snapshot.get("partial_failed_bps", []),
        last_error=str(error),
    )


def _save_quota_error_state(
    deps: dict,
    doc_id: str,
    snapshot: dict,
    *,
    worker_plan: dict,
    bp: int,
    current_page_idx: int,
    model: str,
    error: Exception,
):
    total_pages = _safe_int(worker_plan.get("total_pages", 0))
    initial_done_pages = _safe_int(worker_plan.get("initial_done_pages", 0))
    state_total, state_done = deps["clamp_page_progress"](
        snapshot.get("total_pages", total_pages),
        snapshot.get("done_pages", initial_done_pages),
    )
    processed_pages = snapshot.get("processed_pages", state_done)
    deps["save_translate_state"](
        doc_id,
        running=False,
        stop_requested=False,
        phase="error",
        total_pages=state_total,
        done_pages=state_done,
        processed_pages=processed_pages,
        pending_pages=deps["remaining_pages"](state_total, processed_pages),
        current_bp=bp,
        current_page_idx=current_page_idx,
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=model,
        last_error=str(error),
    )


def _finalize_terminal_state(deps: dict, doc_id: str, worker_plan: dict):
    snapshot = deps["load_translate_state"](doc_id)
    task_meta = worker_plan.get("task_meta") or {}
    if str(task_meta.get("kind") or "") == "fnm":
        from FNM_RE import build_unit_progress, list_diagnostic_entries_for_doc
        from persistence.sqlite_store import SQLiteRepository

        repo = SQLiteRepository()
        unit_progress = build_unit_progress(doc_id, repo=repo, snapshot=snapshot)
        translated_bps = []
        for entry in list_diagnostic_entries_for_doc(doc_id, repo=repo):
            bp = entry.get("_pageBP")
            if bp is None:
                continue
            has_translated = any(
                str(item.get("translation") or "").strip()
                and str(item.get("_translation_source") or "") != "source"
                for item in (entry.get("_page_entries") or [])
                if isinstance(item, dict)
            )
            if has_translated:
                translated_bps.append(int(bp))
        final_phase = "partial_failed" if unit_progress.get("error_units", 0) else "done"
        deps["save_translate_state"](
            doc_id,
            running=False,
            stop_requested=False,
            phase=final_phase,
            total_pages=unit_progress.get("total_units", 0),
            done_pages=unit_progress.get("done_units", 0),
            processed_pages=unit_progress.get("processed_units", 0),
            pending_pages=unit_progress.get("pending_units", 0),
            current_bp=snapshot.get("current_bp"),
            current_page_idx=snapshot.get("current_page_idx", unit_progress.get("processed_units", 0)),
            translated_chars=snapshot.get("translated_chars", 0),
            translated_paras=snapshot.get("translated_paras", 0),
            request_count=snapshot.get("request_count", 0),
            prompt_tokens=snapshot.get("prompt_tokens", 0),
            completion_tokens=snapshot.get("completion_tokens", 0),
            model=snapshot.get("model", worker_plan.get("model_key", "")),
            partial_failed_bps=[],
            last_error=snapshot.get("last_error", ""),
        )
        deps["translate_push"]("all_done", {
            "total_pages": unit_progress.get("total_units", 0),
            "total_entries": len(translated_bps),
            "total_units": unit_progress.get("total_units", 0),
        })
        return
    total_pages = _safe_int(worker_plan.get("total_pages", 0))
    state_total, _state_done = deps["clamp_page_progress"](
        snapshot.get("total_pages", total_pages),
        snapshot.get("done_pages", total_pages),
    )
    target_bps = [int(bp) for bp in (worker_plan.get("target_bps") or []) if bp is not None]
    final_failed_bps = [bp for bp in snapshot.get("failed_bps", []) if bp is not None]
    final_partial_failed_bps = deps["collect_partial_failed_bps"](doc_id, target_bps)
    entries, _, _ = deps["load_entries_from_disk"](doc_id)
    target_bp_set = set(target_bps)
    translated_bps = {
        int(entry.get("_pageBP"))
        for entry in entries
        if entry.get("_pageBP") is not None and int(entry.get("_pageBP")) in target_bp_set
    }
    done_bps = translated_bps - set(final_partial_failed_bps)
    final_done_pages = min(state_total, len(done_bps)) if state_total else len(done_bps)
    final_phase = "partial_failed" if (final_failed_bps or final_partial_failed_bps) else "done"
    deps["save_translate_state"](
        doc_id,
        running=False,
        stop_requested=False,
        phase=final_phase,
        total_pages=state_total,
        done_pages=final_done_pages,
        processed_pages=state_total,
        pending_pages=0,
        current_bp=snapshot.get("current_bp"),
        current_page_idx=snapshot.get("current_page_idx", state_total),
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=snapshot.get("model", worker_plan.get("model_key", "")),
        partial_failed_bps=final_partial_failed_bps,
        last_error=snapshot.get("last_error", ""),
    )
    deps["translate_push"]("all_done", {
        "total_pages": total_pages,
        "total_entries": len(entries),
    })


def _save_top_level_error_state(deps: dict, doc_id: str, error: Exception):
    snapshot = deps["load_translate_state"](doc_id)
    state_total, state_done = deps["clamp_page_progress"](
        snapshot.get("total_pages", 0),
        snapshot.get("done_pages", 0),
    )
    processed_pages = snapshot.get("processed_pages", state_done)
    deps["save_translate_state"](
        doc_id,
        running=False,
        stop_requested=False,
        phase="error",
        total_pages=state_total,
        done_pages=state_done,
        processed_pages=processed_pages,
        pending_pages=deps["remaining_pages"](state_total, processed_pages),
        current_bp=snapshot.get("current_bp"),
        current_page_idx=snapshot.get("current_page_idx", 0),
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=snapshot.get("model", ""),
        last_error=str(error),
    )


def run_translate_worker(
    *,
    doc_id: str,
    build_plan,
    run_page,
    handle_page_exception,
    deps: dict,
    after_target_loop=None,
):
    worker_plan = {}
    context = {}
    try:
        plan = build_plan()
        start_error = plan.get("start_error")
        if start_error:
            deps["mark_translate_start_error"](
                doc_id,
                start_error.get("start_bp"),
                start_error.get("error_code", "start_error"),
                start_error.get("message", "启动失败"),
                total_pages=start_error.get("total_pages", 0),
                model_label=start_error.get("model_label", ""),
            )
            return

        worker_plan = plan["worker_plan"]
        context = plan.get("context") or {}
        target_bps = [int(bp) for bp in (worker_plan.get("target_bps") or []) if bp is not None]
        total_pages = _safe_int(worker_plan.get("total_pages", len(target_bps)))
        initial_done_pages = _safe_int(worker_plan.get("initial_done_pages", 0))
        initial_processed_pages = _safe_int(worker_plan.get("initial_processed_pages", initial_done_pages))
        initial_page_idx = _safe_int(worker_plan.get("initial_page_idx", initial_done_pages))

        deps["translate_push"]("init", {
            "total_pages": total_pages,
            "done_pages": initial_done_pages,
            "pending_pages": total_pages - initial_processed_pages,
        })
        deps["save_translate_state"](
            doc_id,
            running=True,
            stop_requested=False,
            phase="running",
            start_bp=worker_plan.get("start_bp"),
            total_pages=total_pages,
            done_pages=initial_done_pages,
            processed_pages=initial_processed_pages,
            pending_pages=deps["remaining_pages"](total_pages, initial_processed_pages),
            current_bp=None,
            current_page_idx=initial_page_idx,
            translated_chars=0,
            translated_paras=0,
            request_count=0,
            prompt_tokens=0,
            completion_tokens=0,
            model=worker_plan.get("model_label", ""),
            model_source=worker_plan.get("model_source", "builtin"),
            model_key=worker_plan.get("model_key", ""),
            model_id=worker_plan.get("model_id", ""),
            provider=worker_plan.get("provider", ""),
            last_error="",
            failed_bps=[],
            partial_failed_bps=worker_plan.get("initial_partial_failed_bps", []),
            failed_pages=[],
            task=worker_plan.get("task_meta") or {},
            draft=deps["default_stream_draft_state"](),
        )

        for loop_index, bp in enumerate(target_bps):
            current_page_idx = _page_idx_for(worker_plan, bp, loop_index)
            if deps["runtime_stop_requested"](doc_id):
                snapshot = deps["load_translate_state"](doc_id)
                _save_stopped_state(
                    deps,
                    doc_id,
                    snapshot,
                    total_pages=total_pages,
                    done_pages=initial_done_pages + loop_index,
                    current_bp=snapshot.get("current_bp"),
                    current_page_idx=current_page_idx,
                    model=worker_plan.get("model_key", ""),
                    partial_failed_bps=worker_plan.get("initial_partial_failed_bps", []),
                )
                deps["translate_push"]("stopped", {"msg": "翻译已停止"})
                return

            snapshot = deps["load_translate_state"](doc_id)
            if deps["runtime_stop_requested"](doc_id):
                _save_stopped_state(
                    deps,
                    doc_id,
                    snapshot,
                    total_pages=total_pages,
                    done_pages=initial_done_pages + loop_index,
                    current_bp=snapshot.get("current_bp"),
                    current_page_idx=current_page_idx,
                    model=worker_plan.get("model_key", ""),
                    partial_failed_bps=worker_plan.get("initial_partial_failed_bps", []),
                )
                deps["translate_push"]("stopped", {"msg": "翻译已停止"})
                return

            _save_page_start_state(
                deps,
                doc_id,
                snapshot,
                total_pages=total_pages,
                done_pages=initial_done_pages + loop_index,
                bp=bp,
                current_page_idx=current_page_idx,
                model=worker_plan.get("model_key", ""),
            )
            deps["translate_push"]("page_start", {
                "bp": bp,
                "page_idx": current_page_idx,
                "total": total_pages,
            })

            try:
                page_result = run_page(
                    doc_id=doc_id,
                    bp=bp,
                    loop_index=loop_index,
                    current_page_idx=current_page_idx,
                    worker_plan=worker_plan,
                    context=context,
                )
                if page_result.get("draft_error_patch"):
                    deps["save_stream_draft"](doc_id, **page_result["draft_error_patch"])
                deps["clear_failed_page_state"](doc_id, int(bp))
                entry_cache_update = page_result.get("entry_cache_update")
                if isinstance(entry_cache_update, dict):
                    context.setdefault("entry_by_bp", {}).update(entry_cache_update)
                snapshot = deps["load_translate_state"](doc_id)
                success_state = _save_page_success_state(
                    deps,
                    doc_id,
                    snapshot,
                    worker_plan=worker_plan,
                    bp=bp,
                    current_page_idx=current_page_idx,
                    page_result=page_result,
                )
                page_done_payload = {
                    "bp": bp,
                    "page_idx": current_page_idx,
                    "total": total_pages,
                    "entry_idx": page_result.get("entry_idx"),
                    "affected_bps": list(page_result.get("affected_bps") or []),
                    "para_count": page_result.get("para_count", 0),
                    "char_count": page_result.get("char_count", 0),
                    "usage": page_result.get("usage", {}),
                    "model": page_result.get("model_key", worker_plan.get("model_key", "")),
                    "partial_failed": bool(page_result.get("partial_failed")),
                }
                if deps["runtime_stop_requested"](doc_id):
                    stop_snapshot = deps["load_translate_state"](doc_id)
                    _save_stopped_state(
                        deps,
                        doc_id,
                        stop_snapshot,
                        total_pages=total_pages,
                        done_pages=success_state["done_pages"],
                        current_bp=bp,
                        current_page_idx=current_page_idx,
                        model=page_result.get("model_key", worker_plan.get("model_key", "")),
                        partial_failed_bps=success_state["partial_failed_bps"],
                    )
                    deps["translate_push"]("page_done", page_done_payload)
                    deps["translate_push"]("stopped", {"msg": "翻译已停止", "bp": bp})
                    return

                deps["translate_push"]("page_done", page_done_payload)
            except TranslateStreamAborted:
                snapshot = deps["load_translate_state"](doc_id)
                _save_stopped_state(
                    deps,
                    doc_id,
                    snapshot,
                    total_pages=total_pages,
                    done_pages=initial_done_pages + loop_index,
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    model=worker_plan.get("model_key", ""),
                    partial_failed_bps=worker_plan.get("initial_partial_failed_bps", []),
                )
                deps["translate_push"]("stopped", {"msg": "翻译已停止", "bp": bp})
                return
            except QuotaExceededError as exc:
                snapshot = deps["load_translate_state"](doc_id)
                _save_quota_error_state(
                    deps,
                    doc_id,
                    snapshot,
                    worker_plan=worker_plan,
                    bp=bp,
                    current_page_idx=current_page_idx,
                    model=getattr(exc, "_worker_model_key", worker_plan.get("model_key", "")),
                    error=exc,
                )
                deps["translate_push"]("error", {"msg": str(exc), "bp": bp, "kind": "quota"})
                return
            except NonRetryableProviderError as exc:
                snapshot = deps["load_translate_state"](doc_id)
                deps["mark_failed_page_state"](doc_id, bp, str(exc))
                _save_quota_error_state(
                    deps,
                    doc_id,
                    snapshot,
                    worker_plan=worker_plan,
                    bp=bp,
                    current_page_idx=current_page_idx,
                    model=getattr(exc, "_worker_model_key", worker_plan.get("model_key", "")),
                    error=exc,
                )
                deps["translate_push"]("error", {
                    "msg": str(exc),
                    "bp": bp,
                    "kind": "fatal_provider",
                    "status_code": getattr(exc, "status_code", None),
                })
                return
            except Exception as exc:
                logger.exception("翻译页面失败 doc_id=%s bp=%s", doc_id, bp)
                deps["mark_failed_page_state"](doc_id, bp, str(exc))
                error_patch = handle_page_exception(
                    exc,
                    doc_id=doc_id,
                    bp=bp,
                    loop_index=loop_index,
                    current_page_idx=current_page_idx,
                    worker_plan=worker_plan,
                    context=context,
                ) or {}
                draft_error_patch = error_patch.get("draft_error_patch")
                if draft_error_patch:
                    deps["save_stream_draft"](doc_id, **draft_error_patch)
                snapshot = deps["load_translate_state"](doc_id)
                _save_page_error_state(
                    deps,
                    doc_id,
                    snapshot,
                    worker_plan=worker_plan,
                    bp=bp,
                    current_page_idx=current_page_idx,
                    model=error_patch.get("model_key", getattr(exc, "_worker_model_key", worker_plan.get("model_key", ""))),
                    error=exc,
                )
                deps["translate_push"]("page_error", {
                    "bp": bp,
                    "error": str(exc),
                    "page_idx": current_page_idx,
                    "total": total_pages,
                })

        if after_target_loop is not None:
            after_target_loop(
                doc_id=doc_id,
                worker_plan=worker_plan,
                context=context,
                deps=deps,
            )
        _finalize_terminal_state(deps, doc_id, worker_plan)
    except Exception as exc:
        logger.exception("翻译 worker 顶层错误 doc_id=%s", doc_id)
        _save_top_level_error_state(deps, doc_id, exc)
        deps["translate_push"]("error", {"msg": str(exc)})
    finally:
        deps["release_runtime"]()

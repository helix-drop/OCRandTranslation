"""翻译任务启动与启动失败收口 helper。"""

import threading
import time

from config import get_model_key
from persistence.storage import get_translate_args
from persistence.task_logs import append_doc_task_log, create_doc_task_log
from translation.translate_runtime import (
    claim_translate_runtime,
    set_translate_runtime_log_path,
    translate_push,
)
from translation.translate_state import (
    TASK_KIND_CONTINUOUS,
    TASK_KIND_FNM,
    _build_translate_task_meta,
    _default_stream_draft_state,
    _normalize_translate_task_meta,
)
from translation.translate_store import _save_translate_state


def mark_translate_start_error(doc_id: str, start_bp: int, error_code: str, message: str, *, total_pages: int = 0, model_label: str = ""):
    safe_message = str(message or error_code or "启动失败")
    translate_push("error", {"code": error_code, "msg": safe_message})
    _save_translate_state(
        doc_id,
        running=False,
        stop_requested=False,
        phase="error",
        start_bp=start_bp,
        total_pages=max(0, int(total_pages or 0)),
        done_pages=0,
        processed_pages=0,
        pending_pages=0,
        current_bp=start_bp,
        current_page_idx=0,
        translated_chars=0,
        translated_paras=0,
        request_count=0,
        prompt_tokens=0,
        completion_tokens=0,
        model=model_label,
        last_error=safe_message,
        failed_bps=[],
        partial_failed_bps=[],
        failed_pages=[],
        draft=_default_stream_draft_state(),
    )


def _translate_model_state_fields(initial_args: dict) -> dict:
    companion = dict(initial_args.get("companion_chat_model") or {})
    return {
        "translation_model_label": initial_args.get("display_label", "") or initial_args.get("model_id", "") or initial_args.get("model_key", ""),
        "translation_model_id": initial_args.get("model_id", "") or initial_args.get("model_key", ""),
        "companion_model_label": companion.get("display_label", "") or companion.get("model_id", ""),
        "companion_model_id": companion.get("model_id", "") or companion.get("model_key", ""),
    }


def start_translate_task(
    doc_id: str,
    start_bp: int,
    doc_title: str,
    worker_target=None,
) -> bool:
    """启动后台连续翻译任务，返回是否成功启动。"""
    if not doc_id:
        return False
    if worker_target is None:
        from translation.service import _translate_all_worker as worker_target
    owner_token = claim_translate_runtime(doc_id)
    if owner_token is None:
        return False

    initial_args = get_translate_args()
    log_relpath = create_doc_task_log(
        doc_id,
        "translate_continuous",
        started_at=time.time(),
    )
    set_translate_runtime_log_path(log_relpath)
    _save_translate_state(
        doc_id,
        running=True,
        stop_requested=False,
        phase="running",
        start_bp=start_bp,
        total_pages=0,
        done_pages=0,
        processed_pages=0,
        pending_pages=0,
        current_bp=None,
        current_page_idx=0,
        translated_chars=0,
        translated_paras=0,
        request_count=0,
        prompt_tokens=0,
        completion_tokens=0,
        model=initial_args.get("display_label") or initial_args.get("model_id") or initial_args.get("model_key") or get_model_key(),
        model_source=initial_args.get("model_source", "builtin"),
        model_key=initial_args.get("model_key", ""),
        model_id=initial_args.get("model_id", ""),
        provider=initial_args.get("provider", ""),
        last_error="",
        failed_bps=[],
        partial_failed_bps=[],
        failed_pages=[],
        task=_build_translate_task_meta(
            kind=TASK_KIND_CONTINUOUS,
            label="连续翻译",
            start_bp=start_bp,
            start_segment_index=0,
            target_bps=[],
            log_relpath=log_relpath,
        ),
        draft=_default_stream_draft_state(),
        **_translate_model_state_fields(initial_args),
    )
    append_doc_task_log(
        doc_id,
        log_relpath,
        (
            f"连续翻译任务已启动：start_bp={int(start_bp or 0)}，"
            f"模型={initial_args.get('display_label') or initial_args.get('model_id') or initial_args.get('model_key') or get_model_key()}。"
        ),
    )

    thread = threading.Thread(target=worker_target, args=(doc_id, start_bp, doc_title, owner_token), daemon=True)
    thread.start()
    return True


def start_fnm_translate_task(
    doc_id: str,
    doc_title: str,
    start_unit_idx: int | None = None,
    execution_mode: str = "real",
    worker_target=None,
) -> bool:
    """启动后台 FNM 翻译任务。"""
    if not doc_id:
        return False
    if worker_target is None:
        from translation.service import _fnm_translate_worker as worker_target
    owner_token = claim_translate_runtime(doc_id)
    if owner_token is None:
        return False

    initial_args = get_translate_args()
    log_relpath = create_doc_task_log(
        doc_id,
        "translate_fnm",
        started_at=time.time(),
    )
    set_translate_runtime_log_path(log_relpath)
    _save_translate_state(
        doc_id,
        running=True,
        stop_requested=False,
        phase="running",
        execution_mode=str(execution_mode or "real").strip().lower() or "real",
        start_bp=start_unit_idx,
        total_pages=0,
        done_pages=0,
        processed_pages=0,
        pending_pages=0,
        current_bp=None,
        current_page_idx=0,
        translated_chars=0,
        translated_paras=0,
        request_count=0,
        prompt_tokens=0,
        completion_tokens=0,
        model=initial_args.get("display_label") or initial_args.get("model_id") or initial_args.get("model_key") or get_model_key(),
        model_source=initial_args.get("model_source", "builtin"),
        model_key=initial_args.get("model_key", ""),
        model_id=initial_args.get("model_id", ""),
        provider=initial_args.get("provider", ""),
        last_error="",
        failed_bps=[],
        partial_failed_bps=[],
        failed_pages=[],
        retry_round=0,
        unresolved_count=0,
        manual_required_count=0,
        next_failed_location=None,
        failed_locations=[],
        manual_required_locations=[],
        task=_build_translate_task_meta(
            kind=TASK_KIND_FNM,
            label="FNM 翻译",
            start_bp=start_unit_idx,
            progress_mode="unit",
            start_unit_idx=start_unit_idx,
            start_segment_index=0,
            target_bps=[],
            log_relpath=log_relpath,
        ),
        draft=_default_stream_draft_state(),
        **_translate_model_state_fields(initial_args),
    )
    append_doc_task_log(
        doc_id,
        log_relpath,
        (
            "FNM 翻译任务已启动："
            f"start_unit_idx={int(start_unit_idx) if start_unit_idx is not None else 1}，"
            f"模式={str(execution_mode or 'real').strip().lower() or 'real'}，"
            f"模型={initial_args.get('display_label') or initial_args.get('model_id') or initial_args.get('model_key') or get_model_key()}。"
        ),
    )

    thread = threading.Thread(target=worker_target, args=(doc_id, doc_title, owner_token), daemon=True)
    thread.start()
    return True


def start_glossary_retranslate_task(
    doc_id: str,
    preview: dict | None = None,
    *,
    start_bp: int | None = None,
    start_segment_index: int = 0,
    doc_title: str,
    worker_target=None,
) -> tuple[bool, dict]:
    if preview is None:
        from translation.service import build_glossary_retranslate_preview
        preview = build_glossary_retranslate_preview(
            doc_id,
            start_bp=start_bp,
            start_segment_index=start_segment_index,
        )
    if not doc_id:
        return False, preview
    if not preview.get("ok") or not preview.get("can_start"):
        return False, preview
    if worker_target is None:
        from translation.service import _glossary_retranslate_worker as worker_target
    owner_token = claim_translate_runtime(doc_id)
    if owner_token is None:
        return False, preview

    initial_args = get_translate_args()
    task_meta = _normalize_translate_task_meta(preview.get("task"))
    log_relpath = create_doc_task_log(
        doc_id,
        "translate_glossary",
        started_at=time.time(),
    )
    set_translate_runtime_log_path(log_relpath)
    task_meta["log_relpath"] = log_relpath
    _save_translate_state(
        doc_id,
        running=True,
        stop_requested=False,
        phase="running",
        start_bp=task_meta.get("start_bp"),
        total_pages=task_meta.get("affected_pages", 0),
        done_pages=0,
        processed_pages=0,
        pending_pages=task_meta.get("affected_pages", 0),
        current_bp=None,
        current_page_idx=0,
        translated_chars=0,
        translated_paras=0,
        request_count=0,
        prompt_tokens=0,
        completion_tokens=0,
        model=initial_args.get("display_label") or initial_args.get("model_id") or initial_args.get("model_key") or get_model_key(),
        model_source=initial_args.get("model_source", "builtin"),
        model_key=initial_args.get("model_key", ""),
        model_id=initial_args.get("model_id", ""),
        provider=initial_args.get("provider", ""),
        last_error="",
        failed_bps=[],
        partial_failed_bps=[],
        failed_pages=[],
        task=task_meta,
        draft=_default_stream_draft_state(),
        **_translate_model_state_fields(initial_args),
    )
    append_doc_task_log(
        doc_id,
        log_relpath,
        (
            "词典补重译任务已启动："
            f"start_bp={task_meta.get('start_bp')}, "
            f"affected_pages={task_meta.get('affected_pages', 0)}。"
        ),
    )

    thread = threading.Thread(
        target=worker_target,
        args=(doc_id, task_meta, doc_title, owner_token),
        daemon=True,
    )
    thread.start()
    return True, preview

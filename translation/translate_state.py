"""翻译任务状态与任务元数据 helper。"""


TASK_KIND_CONTINUOUS = "continuous"
TASK_KIND_FNM = "fnm"
TASK_KIND_GLOSSARY_RETRANSLATE = "glossary_retranslate"


def _default_translate_task_meta() -> dict:
    return {
        "kind": "",
        "label": "",
        "progress_mode": "page",
        "log_relpath": "",
        "start_bp": None,
        "start_unit_idx": None,
        "start_segment_index": 0,
        "end_bp": None,
        "target_bps": [],
        "target_segments_by_bp": {},
        "target_unit_ids": [],
        "affected_pages": 0,
        "affected_segments": 0,
        "skipped_manual_segments": 0,
    }


def _normalize_translate_task_meta(task: dict | None) -> dict:
    meta = _default_translate_task_meta()
    if isinstance(task, dict):
        meta.update(task)
    meta["kind"] = str(meta.get("kind", "") or "").strip()
    meta["label"] = str(meta.get("label", "") or "").strip()
    meta["progress_mode"] = str(meta.get("progress_mode", "page") or "page").strip() or "page"
    meta["log_relpath"] = str(meta.get("log_relpath", "") or "").strip()
    meta["start_bp"] = int(meta.get("start_bp")) if meta.get("start_bp") is not None else None
    meta["start_unit_idx"] = int(meta.get("start_unit_idx")) if meta.get("start_unit_idx") is not None else None
    meta["start_segment_index"] = max(0, int(meta.get("start_segment_index", 0) or 0))
    meta["end_bp"] = int(meta.get("end_bp")) if meta.get("end_bp") is not None else None
    raw_target_bps = meta.get("target_bps")
    target_bps = []
    if isinstance(raw_target_bps, list):
        for item in raw_target_bps:
            if item is None:
                continue
            try:
                target_bps.append(int(item))
            except (TypeError, ValueError):
                continue
    meta["target_bps"] = target_bps
    raw_target_segments_by_bp = meta.get("target_segments_by_bp")
    normalized_target_segments_by_bp = {}
    if isinstance(raw_target_segments_by_bp, dict):
        for raw_bp, raw_indices in raw_target_segments_by_bp.items():
            try:
                bp = str(int(raw_bp))
            except (TypeError, ValueError):
                continue
            indices = []
            if isinstance(raw_indices, list):
                for item in raw_indices:
                    try:
                        idx = int(item)
                    except (TypeError, ValueError):
                        continue
                    if idx >= 0:
                        indices.append(idx)
            normalized_target_segments_by_bp[bp] = sorted(set(indices))
    meta["target_segments_by_bp"] = normalized_target_segments_by_bp
    raw_target_unit_ids = meta.get("target_unit_ids")
    if isinstance(raw_target_unit_ids, list):
        meta["target_unit_ids"] = [
            str(item).strip()
            for item in raw_target_unit_ids
            if str(item).strip()
        ]
    else:
        meta["target_unit_ids"] = []
    meta["affected_pages"] = max(0, int(meta.get("affected_pages", len(target_bps)) or 0))
    meta["affected_segments"] = max(0, int(meta.get("affected_segments", 0) or 0))
    meta["skipped_manual_segments"] = max(0, int(meta.get("skipped_manual_segments", 0) or 0))
    return meta


def _build_translate_task_meta(
    *,
    kind: str,
    label: str,
    start_bp: int | None,
    progress_mode: str = "page",
    start_unit_idx: int | None = None,
    start_segment_index: int = 0,
    target_bps: list[int] | None = None,
    target_segments_by_bp: dict[str, list[int]] | None = None,
    target_unit_ids: list[str] | None = None,
    affected_segments: int = 0,
    skipped_manual_segments: int = 0,
    log_relpath: str = "",
) -> dict:
    ordered_target_bps = [int(bp) for bp in (target_bps or []) if bp is not None]
    return _normalize_translate_task_meta({
        "kind": kind,
        "label": label,
        "progress_mode": progress_mode,
        "log_relpath": log_relpath,
        "start_bp": start_bp,
        "start_unit_idx": start_unit_idx,
        "start_segment_index": start_segment_index,
        "end_bp": ordered_target_bps[-1] if ordered_target_bps else None,
        "target_bps": ordered_target_bps,
        "target_segments_by_bp": dict(target_segments_by_bp or {}),
        "target_unit_ids": list(target_unit_ids or []),
        "affected_pages": len(ordered_target_bps),
        "affected_segments": affected_segments,
        "skipped_manual_segments": skipped_manual_segments,
    })


def _default_stream_draft_state() -> dict:
    return {
        "active": False,
        "mode": "page",
        "bp": None,
        "unit_idx": None,
        "unit_id": "",
        "unit_kind": "",
        "unit_label": "",
        "unit_pages": "",
        "unit_error": "",
        "unit_items": [],
        "para_idx": None,
        "para_total": 0,
        "para_done": 0,
        "parallel_limit": 0,
        "active_para_indices": [],
        "paragraph_states": [],
        "paragraph_errors": [],
        "paragraphs": [],
        "status": "idle",
        "note": "",
        "last_error": "",
        "updated_at": 0,
    }


def _normalize_stream_draft(draft: dict | None) -> dict:
    normalized = _default_stream_draft_state()
    if isinstance(draft, dict):
        normalized.update(draft)
    for key in ("active_para_indices", "paragraph_states", "paragraph_errors", "paragraphs", "unit_items"):
        value = normalized.get(key)
        normalized[key] = list(value) if isinstance(value, list) else []
    return normalized


def _default_translate_state(doc_id: str = "") -> dict:
    return {
        "doc_id": doc_id,
        "phase": "idle",
        "execution_mode": "test",
        "running": False,
        "stop_requested": False,
        "start_bp": None,
        "resume_bp": None,
        "total_pages": 0,
        "done_pages": 0,
        "processed_pages": 0,
        "pending_pages": 0,
        "current_bp": None,
        "current_page_idx": 0,
        "translated_chars": 0,
        "translated_paras": 0,
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "model": "",
        "model_source": "",
        "model_key": "",
        "model_id": "",
        "provider": "",
        "translation_model_label": "",
        "translation_model_id": "",
        "companion_model_label": "",
        "companion_model_id": "",
        "last_error": "",
        "failed_bps": [],
        "partial_failed_bps": [],
        "failed_pages": [],
        "retry_round": 0,
        "unresolved_count": 0,
        "manual_required_count": 0,
        "fnm_tail_state": "idle",
        "export_bundle_available": False,
        "export_has_blockers": False,
        "tail_blocking_summary": [],
        "translation_attempt_history": [],
        "next_failed_location": None,
        "failed_locations": [],
        "manual_required_locations": [],
        "task": _default_translate_task_meta(),
        "draft": _default_stream_draft_state(),
        "updated_at": 0,
    }


def _clamp_page_progress(total_pages: int, done_pages: int) -> tuple[int, int]:
    total = max(0, int(total_pages or 0))
    done = max(0, int(done_pages or 0))
    if total and done > total:
        done = total
    return total, done


def _remaining_pages(total_pages: int, processed_pages: int) -> int:
    total = max(0, int(total_pages or 0))
    processed = max(0, int(processed_pages or 0))
    if total and processed > total:
        processed = total
    return max(0, total - processed)


def _normalize_translate_state(state: dict, assume_inactive: bool = False) -> dict:
    """统一收口快照字段，避免前端读取到自相矛盾的状态。"""
    if not isinstance(state, dict):
        return _default_translate_state()

    state["start_bp"] = int(state.get("start_bp")) if state.get("start_bp") is not None else None
    state["resume_bp"] = int(state.get("resume_bp")) if state.get("resume_bp") is not None else None
    total_pages, done_pages = _clamp_page_progress(
        state.get("total_pages", 0),
        state.get("done_pages", 0),
    )
    state["total_pages"] = total_pages
    state["done_pages"] = done_pages
    processed_pages = max(0, int(state.get("processed_pages", done_pages) or 0))
    if total_pages and processed_pages > total_pages:
        processed_pages = total_pages
    if processed_pages < done_pages:
        processed_pages = done_pages
    state["processed_pages"] = processed_pages
    state["pending_pages"] = max(0, int(state.get("pending_pages", max(0, total_pages - done_pages)) or 0))
    current_page_idx = max(0, int(state.get("current_page_idx", 0) or 0))
    if total_pages and current_page_idx > total_pages:
        current_page_idx = total_pages
    state["current_page_idx"] = current_page_idx

    phase = state.get("phase", "idle")
    state["task"] = _normalize_translate_task_meta(state.get("task"))
    state["draft"] = _normalize_stream_draft(state.get("draft"))
    state["execution_mode"] = str(state.get("execution_mode", "test") or "test").strip().lower() or "test"
    state["retry_round"] = max(0, int(state.get("retry_round", 0) or 0))
    state["unresolved_count"] = max(0, int(state.get("unresolved_count", 0) or 0))
    state["manual_required_count"] = max(0, int(state.get("manual_required_count", 0) or 0))
    tail_state = str(state.get("fnm_tail_state", "idle") or "idle").strip().lower() or "idle"
    if tail_state not in {"idle", "translation_retrying", "post_translate_checking", "repairing", "done"}:
        tail_state = "idle"
    state["fnm_tail_state"] = tail_state
    state["export_bundle_available"] = bool(state.get("export_bundle_available"))
    state["export_has_blockers"] = bool(state.get("export_has_blockers"))
    if not isinstance(state.get("tail_blocking_summary"), list):
        state["tail_blocking_summary"] = []
    if not isinstance(state.get("translation_attempt_history"), list):
        state["translation_attempt_history"] = []
    if not isinstance(state.get("failed_locations"), list):
        state["failed_locations"] = []
    if not isinstance(state.get("manual_required_locations"), list):
        state["manual_required_locations"] = []
    if state.get("next_failed_location") is not None and not isinstance(state.get("next_failed_location"), dict):
        state["next_failed_location"] = None
    if not isinstance(state.get("partial_failed_bps"), list):
        state["partial_failed_bps"] = []

    if phase in ("idle", "done", "partial_failed", "stopped", "error"):
        state["running"] = False
        state["stop_requested"] = False
    if phase in ("done", "partial_failed"):
        state["processed_pages"] = total_pages
        state["pending_pages"] = 0

    draft = state["draft"]
    if assume_inactive and phase in ("running", "stopping"):
        state["running"] = False
        state["stop_requested"] = False
        state["phase"] = "stopped"
        if draft.get("active"):
            draft["active"] = False
            draft["active_para_indices"] = []
            if draft.get("status") == "streaming":
                draft["status"] = "aborted"
                draft["note"] = "后台翻译未处于活动状态，当前页草稿已中断。"

    if state.get("phase") in ("done", "partial_failed", "stopped", "error"):
        draft["active"] = False
        draft["active_para_indices"] = []

    state["total_tokens"] = state.get("prompt_tokens", 0) + state.get("completion_tokens", 0)
    return state

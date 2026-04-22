"""visual TOC 共享异常与 usage helper。"""

from __future__ import annotations

from typing import Any

_VISUAL_USAGE_STAGES = (
    "visual_toc.preflight",
    "visual_toc.classify_candidates",
    "visual_toc.extract_page_items",
    "visual_toc.manual_input_extract",
)

class VisionModelRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str = "",
        status_code: int | None = None,
        retryable: bool = False,
        detail: str = "",
    ):
        super().__init__(message)
        self.stage = str(stage or "")
        self.status_code = int(status_code) if status_code is not None else None
        self.retryable = bool(retryable)
        self.detail = str(detail or "")

def _format_visual_failure_message(reason_code: str, detail: str) -> str:
    reason = str(reason_code or "").strip()
    text = str(detail or "").strip()
    if not reason:
        return text
    if not text:
        return f"[{reason}]"
    return f"[{reason}] {text}"

def _coerce_usage_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0

def _compact_usage_context(context: dict | None) -> dict:
    if not isinstance(context, dict):
        return {}
    compact: dict[str, object] = {}
    for key, value in context.items():
        if value is None:
            continue
        if isinstance(value, (int, float, bool)):
            compact[str(key)] = value
            continue
        text = str(value).strip()
        if not text:
            continue
        compact[str(key)] = text[:96] + ("..." if len(text) > 96 else "")
    return compact

def _summarize_usage_events(
    events: list[dict] | None,
    *,
    required_stages: tuple[str, ...] = (),
) -> dict:
    by_stage: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    total = {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    for event in events or []:
        stage = str(event.get("stage") or "").strip() or "unknown"
        model_id = str(event.get("model_id") or "").strip() or "unknown"
        usage = {
            "request_count": _coerce_usage_int(event.get("request_count")),
            "prompt_tokens": _coerce_usage_int(event.get("prompt_tokens")),
            "completion_tokens": _coerce_usage_int(event.get("completion_tokens")),
            "total_tokens": _coerce_usage_int(event.get("total_tokens")),
        }
        stage_row = by_stage.setdefault(
            stage,
            {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        model_row = by_model.setdefault(
            model_id,
            {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        for key, value in usage.items():
            stage_row[key] += int(value)
            model_row[key] += int(value)
            total[key] += int(value)
    for stage in required_stages:
        by_stage.setdefault(
            stage,
            {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
    return {"by_stage": by_stage, "by_model": by_model, "total": total}

def _attach_usage_payload(result: dict, usage_events: list[dict] | None) -> dict:
    payload = dict(result or {})
    events = [dict(item) for item in (usage_events or [])]
    payload["usage_events"] = events
    payload["usage_summary"] = _summarize_usage_events(events, required_stages=_VISUAL_USAGE_STAGES)
    return payload

def _attach_trace_payload(result: dict, trace_events: list[dict] | None) -> dict:
    payload = dict(result or {})
    payload["llm_traces"] = [dict(item) for item in (trace_events or [])]
    return payload

def _coerce_positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None

def _coerce_nonnegative_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None

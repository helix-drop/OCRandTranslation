"""FNM 统一 VLM token 计数器。所有 LLM 调用点通过此模块累加用量。"""
from __future__ import annotations
from typing import Any

_counts: list[dict[str, Any]] = []


def record_usage(
    *,
    stage: str,
    model_id: str = "",
    provider: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    request_count: int = 1,
    dur_ms: int = 0,
) -> None:
    _counts.append({
        "stage": stage,
        "model_id": str(model_id or ""),
        "provider": str(provider or ""),
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "request_count": int(request_count or 0),
        "dur_ms": int(dur_ms or 0),
    })


def get_usage_summary() -> dict[str, Any]:
    by_stage: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    total = {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for c in _counts:
        sk = c["stage"]
        mk = c["model_id"]
        if sk not in by_stage:
            by_stage[sk] = {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if mk not in by_model:
            by_model[mk] = {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for k in ("request_count", "prompt_tokens", "completion_tokens", "total_tokens"):
            v = int(c.get(k) or 0)
            by_stage[sk][k] += v
            by_model[mk][k] += v
            total[k] += v
    return {"by_stage": by_stage, "by_model": by_model, "total": total}


def clear_usage() -> None:
    _counts.clear()


def dump_traces(example_dir: str, doc_id: str = "") -> int:
    """将逐条记录写入 llm_traces/ 目录，返回写入文件数。"""
    import json, os
    trace_dir = os.path.join(example_dir, "llm_traces")
    os.makedirs(trace_dir, exist_ok=True)
    stage_counters: dict[str, int] = {}
    written = 0
    for c in _counts:
        stage = str(c.get("stage") or "unknown")
        stage_counters[stage] = stage_counters.get(stage, 0) + 1
        seq = stage_counters[stage]
        path = os.path.join(trace_dir, f"{stage}.{seq:03d}.json")
        trace = {
            "stage": stage,
            "model_id": str(c.get("model_id") or ""),
            "provider": str(c.get("provider") or ""),
            "usage": {
                "prompt_tokens": int(c.get("prompt_tokens") or 0),
                "completion_tokens": int(c.get("completion_tokens") or 0),
                "total_tokens": int(c.get("total_tokens") or 0),
            },
            "timing": {"duration_ms": int(c.get("dur_ms") or 0)},
            "doc_id": str(doc_id or ""),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)
        written += 1
    return written


def write_summary_traces(example_dir: str, usage_summary: dict, doc_id: str = "") -> int:
    """将汇总 usage_summary 写入 llm_traces/ 目录（每阶段一个文件）。"""
    import json, os
    trace_dir = os.path.join(example_dir, "llm_traces")
    os.makedirs(trace_dir, exist_ok=True)
    written = 0
    by_stage = usage_summary.get("by_stage") or {}
    for stage, info in by_stage.items():
        if not info.get("request_count"):
            continue
        path = os.path.join(trace_dir, f"{stage}.summary.json")
        trace = {
            "stage": stage,
            "usage": {
                "request_count": int(info.get("request_count") or 0),
                "prompt_tokens": int(info.get("prompt_tokens") or 0),
                "completion_tokens": int(info.get("completion_tokens") or 0),
                "total_tokens": int(info.get("total_tokens") or 0),
            },
            "doc_id": str(doc_id or ""),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)
        written += 1
    return written

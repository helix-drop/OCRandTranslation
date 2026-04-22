"""翻译领域服务：页面翻译、连续翻译 worker、词表补重译。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import queue
import re
import time

logger = logging.getLogger(__name__)

import config as app_config
import persistence.storage as storage
from config import (
    MODELS,
    get_glossary,
    get_model_key,
    get_doc_meta,
)
from persistence.sqlite_store import SQLiteRepository
from FNM_RE.shared.refs import replace_frozen_refs
from document.text_processing import (
    get_page_range, get_next_page_bp,
    build_visible_page_view, resolve_visible_page_bp,
    get_page_context_for_translate,
    get_paragraph_bboxes,
    assign_page_footnotes_to_paragraphs,
)
from translation.translator import (
    TranslateStreamAborted,
    RateLimitedError,
    TransientProviderError,
    QuotaExceededError,
    NonRetryableProviderError,
    stream_translate_paragraph,
    translate_paragraph,
    structure_page,
)
from document.text_utils import ensure_str
from persistence.storage import (
    load_pages_from_disk,
    save_entry_to_disk,
    load_entries_from_disk,
)
from translation.translate_state import (
    TASK_KIND_CONTINUOUS,
    TASK_KIND_GLOSSARY_RETRANSLATE,
    _build_translate_task_meta,
    _clamp_page_progress,
    _default_stream_draft_state,
    _default_translate_task_meta,
    _normalize_translate_task_meta,
    _remaining_pages,
)
from translation.translate_progress import (
    _collect_partial_failed_bps,
    _collect_target_bps,
    _compute_resume_bp,
    _entry_has_paragraph_error,
    _resolve_task_target_bps,
    reconcile_translate_state_after_page_failure,
    reconcile_translate_state_after_page_success,
)
from translation.glossary_tools import diagnose_segment_glossary
from translation.translate_launch import (
    mark_translate_start_error,
    start_fnm_translate_task as _launch_fnm_translate_task,
    start_glossary_retranslate_task as _launch_glossary_retranslate_task,
    start_translate_task as _launch_translate_task,
)
from translation.translate_runtime import (
    get_current_owner_token,
    get_translate_snapshot,
    release_translate_runtime,
    runtime_stop_requested as _runtime_stop_requested,
    translate_push,
    is_stop_requested,
)
from translation.translate_store import (
    _clear_failed_page_state,
    _clear_translate_state,
    _load_translate_state,
    _mark_failed_page_state,
    _save_stream_draft,
    _save_translate_state,
)
from translation.translate_worker_continuous import run_translate_all_worker as _run_translate_all_worker_impl
from translation.translate_worker_fnm import run_fnm_worker as _run_fnm_worker_impl
from translation.translate_worker_glossary import run_glossary_retranslate_worker as _run_glossary_retranslate_worker_impl
# ============ 翻译核心 ============

def _needs_llm_fix(paragraphs: list) -> bool:
    """判断程序化解析结果是否需要 LLM 修正。"""
    if not paragraphs:
        return True

    has_ref_heading = any(
        p["heading_level"] > 0 and re.search(r"^(References|Bibliography|Works Cited)", p["text"], re.I)
        for p in paragraphs
    )
    if has_ref_heading:
        return False

    body = [p for p in paragraphs if p["heading_level"] == 0]
    if body:
        ref_like = sum(1 for p in body if re.search(r"\(\d{4}[a-z]?\)", p["text"][:80]))
        if ref_like >= len(body) * 0.5:
            return False

    short_count = sum(1 for p in body if len(p["text"]) < 30)
    if short_count > 3:
        return True

    return False


def _llm_fix_paragraphs(paragraphs: list, page_md: str, t_args: dict, page_num: int) -> list:
    """用 LLM 修正有问题的段落结构。"""
    empty_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }
    request_args = _provider_request_args(t_args)
    translate_kwargs = _translate_call_kwargs(request_args)
    call_kwargs = _translate_call_kwargs(request_args)
    try:
        fixed = structure_page(
            blocks=[],
            markdown=page_md,
            page_num=page_num,
            **call_kwargs,
        )
        if fixed and fixed.get("paragraphs"):
            return fixed["paragraphs"], fixed.get("usage", empty_usage)
    except Exception:
        pass
    return paragraphs, empty_usage


def _merge_usage(base: dict, delta: dict | None) -> dict:
    usage = dict(base)
    if not delta:
        return usage
    usage["prompt_tokens"] = usage.get("prompt_tokens", 0) + int(delta.get("prompt_tokens", 0) or 0)
    usage["completion_tokens"] = usage.get("completion_tokens", 0) + int(delta.get("completion_tokens", 0) or 0)
    usage["total_tokens"] = usage.get("total_tokens", 0) + int(delta.get("total_tokens", 0) or 0)
    usage["request_count"] = usage.get("request_count", 0) + int(delta.get("request_count", 0) or 0)
    return usage


def _trim_para_context(text: str, limit: int = 200, from_end: bool = False) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[-limit:] if from_end else text[:limit]


def _get_para_context_window() -> int:
    try:
        return max(50, min(500, int(getattr(app_config, "PARA_CONTEXT_WINDOW", 200) or 200)))
    except Exception:
        return 200


def _get_active_translate_args(model_key: str | None = None) -> tuple[str, dict]:
    if model_key and model_key in MODELS:
        t_args = storage.get_translate_args(f"builtin:{model_key}")
        return model_key, t_args
    t_args = storage.get_translate_args()
    resolved_model_key = t_args.get("model_key") or get_model_key()
    return resolved_model_key, t_args


def _provider_request_args(t_args: dict) -> dict:
    """从翻译状态 payload 中筛出真正传给模型 SDK 的请求字段。"""
    if not isinstance(t_args, dict):
        return {}
    request_overrides = t_args.get("request_overrides")
    companion_chat_model = t_args.get("companion_chat_model")
    return {
        "model_id": str(t_args.get("model_id", "") or "").strip(),
        "api_key": str(t_args.get("api_key", "") or "").strip(),
        "provider": str(t_args.get("provider", "deepseek") or "deepseek").strip() or "deepseek",
        "base_url": t_args.get("base_url"),
        "api_family": str(t_args.get("api_family", "") or "").strip(),
        "stream_mode": str(t_args.get("stream_mode", "") or "").strip(),
        "companion_chat_model_key": str(t_args.get("companion_chat_model_key", "") or "").strip(),
        "request_overrides": dict(request_overrides) if isinstance(request_overrides, dict) else None,
        "companion_chat_model": dict(companion_chat_model) if isinstance(companion_chat_model, dict) else None,
    }


def _translate_call_kwargs(request_args: dict) -> dict:
    return {
        "model_id": str(request_args.get("model_id", "") or "").strip(),
        "api_key": str(request_args.get("api_key", "") or "").strip(),
        "provider": str(request_args.get("provider", "deepseek") or "deepseek").strip() or "deepseek",
        "base_url": request_args.get("base_url"),
        "request_overrides": dict(request_args.get("request_overrides") or {}) if isinstance(request_args.get("request_overrides"), dict) else None,
    }


def _job_request_args(request_args: dict, job: dict) -> dict:
    content_role = str((job or {}).get("content_role", "body") or "body").strip()
    if (
        str(request_args.get("provider", "") or "").strip() == "qwen_mt"
        and content_role in {"footnote", "endnote"}
        and isinstance(request_args.get("companion_chat_model"), dict)
    ):
        companion_args = _translate_call_kwargs(dict(request_args.get("companion_chat_model") or {}))
        if not companion_args.get("api_key"):
            companion_args["api_key"] = str(request_args.get("api_key", "") or "").strip()
        return companion_args
    return _translate_call_kwargs(request_args)


def _should_split_mt_page_footnotes(request_args: dict, ctx: dict) -> bool:
    if str(request_args.get("provider", "") or "").strip() != "qwen_mt":
        return False
    if not isinstance(request_args.get("companion_chat_model"), dict):
        return False
    if not ensure_str((ctx or {}).get("footnotes", "")).strip():
        return False
    return True


def _translate_page_footnotes_with_companion(
    *,
    target_bp: int,
    page_footnotes: str,
    glossary: list,
    request_args: dict,
) -> dict:
    companion = dict(request_args.get("companion_chat_model") or {})
    companion_args = _translate_call_kwargs(companion)
    if not companion_args.get("api_key"):
        companion_args["api_key"] = str(request_args.get("api_key", "") or "").strip()
    if not companion_args.get("model_id") or not companion_args.get("api_key"):
        raise RuntimeError("缺少 companion chat model 配置")
    return translate_paragraph(
        para_text=page_footnotes,
        para_pages=str(target_bp),
        footnotes="",
        glossary=glossary,
        heading_level=0,
        para_idx=0,
        para_total=1,
        prev_context="",
        next_context="",
        section_path=[],
        cross_page=None,
        content_role="footnote",
        **companion_args,
    )


def _apply_page_footnote_translation(
    *,
    page_entries: list[dict],
    target_bp: int,
    ctx: dict,
    glossary: list,
    request_args: dict,
    total_usage: dict,
) -> tuple[list[dict], dict]:
    if not _should_split_mt_page_footnotes(request_args, ctx):
        return page_entries, total_usage
    page_footnotes = ensure_str(ctx.get("footnotes", "")).strip()
    if not page_footnotes or not page_entries:
        return page_entries, total_usage
    try:
        translated = _translate_page_footnotes_with_companion(
            target_bp=target_bp,
            page_footnotes=page_footnotes,
            glossary=glossary,
            request_args=request_args,
        )
        total_usage = _merge_usage(total_usage, translated.get("_usage"))
        page_entries[0]["footnotes"] = page_footnotes
        page_entries[0]["footnotes_translation"] = ensure_str(translated.get("translation", "")).strip()
    except Exception as exc:
        page_entries[0]["footnotes"] = page_footnotes
        page_entries[0]["footnotes_translation"] = f"[翻译失败: {exc}]"
    return page_entries, total_usage


def _get_para_max_concurrency(model_key: str, para_total: int) -> int:
    if para_total <= 0:
        return 1
    if not app_config.get_translate_parallel_enabled():
        return 1
    try:
        configured_default = max(1, min(10, int(getattr(app_config, "PARA_MAX_CONCURRENCY", 10) or 10)))
    except Exception:
        configured_default = 10
    user_limit = app_config.get_translate_parallel_limit()
    return max(1, min(para_total, user_limit, configured_default))


def _entry_has_paragraph_error(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    return any((pe.get("_status") == "error") for pe in entry.get("_page_entries", []))


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


def _segment_is_manual(segment: dict | None) -> bool:
    if not isinstance(segment, dict):
        return False
    return str(segment.get("_translation_source", "") or "").strip() == "manual"


def _segment_machine_translation_text(segment: dict | None) -> str:
    if not isinstance(segment, dict):
        return ""
    machine = ensure_str(segment.get("_machine_translation", "")).strip()
    if machine:
        return machine
    if _segment_is_manual(segment):
        return ""
    return ensure_str(segment.get("translation", "")).strip()


def _segment_is_retranslatable_machine(segment: dict | None) -> bool:
    if not isinstance(segment, dict) or _segment_is_manual(segment):
        return False
    if str(segment.get("_status", "done") or "done").strip() == "error":
        return False
    translation = _segment_machine_translation_text(segment)
    if not translation:
        return False
    return not translation.startswith("[翻译失败:")


def _segment_glossary_source_text(segment: dict | None) -> str:
    if not isinstance(segment, dict):
        return ""
    return "\n".join(
        text
        for text in (
            ensure_str(segment.get("original", "")).strip(),
            ensure_str(segment.get("footnotes", "")).strip(),
        )
        if text
    ).strip()


def _segment_glossary_target_text(segment: dict | None) -> str:
    if not isinstance(segment, dict):
        return ""
    return "\n".join(
        text
        for text in (
            ensure_str(segment.get("translation", "")).strip(),
            ensure_str(segment.get("footnotes_translation", "")).strip(),
        )
        if text
    ).strip()


def _excerpt_text(text: str, limit: int = 120) -> str:
    normalized = re.sub(r"\s+", " ", ensure_str(text)).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "..."


def build_glossary_retranslate_preview(
    doc_id: str,
    *,
    start_bp: int | None = None,
    start_segment_index: int | None = None,
    pages: list[dict] | None = None,
    entries: list[dict] | None = None,
    entry_idx: int | None = None,
) -> dict:
    preview = {
        "ok": True,
        "doc_id": doc_id,
        "start_bp": None,
        "start_segment_index": 0,
        "end_bp": None,
        "affected_pages": 0,
        "affected_segments": 0,
        "skipped_manual_segments": 0,
        "can_start": False,
        "reason": "",
        "target_bps": [],
        "target_segments_by_bp": {},
        "problem_segments": [],
        "problem_list_truncated": False,
        "task": _default_translate_task_meta(),
    }
    if not doc_id:
        preview["ok"] = False
        preview["reason"] = "缺少文档 ID"
        return preview
    if pages is None:
        pages, _ = load_pages_from_disk(doc_id)
    if entries is None or entry_idx is None:
        loaded_entries, _, loaded_entry_idx = load_entries_from_disk(doc_id, pages=pages)
        if entries is None:
            entries = loaded_entries
        if entry_idx is None:
            entry_idx = loaded_entry_idx
    entries = [
        entry for entry in (entries or [])
        if entry.get("_pageBP") is not None
    ]
    if not entries:
        preview["reason"] = "当前文档还没有已译内容。"
        return preview
    ordered_entries = sorted(entries, key=lambda entry: int(entry.get("_pageBP") or 0))
    if start_bp is None:
        bounded_idx = max(0, min(len(ordered_entries) - 1, int(entry_idx or 0)))
        actual_start_bp = int(ordered_entries[bounded_idx].get("_pageBP") or 0)
        actual_start_segment_index = 0
    else:
        actual_start_bp = int(start_bp)
        actual_start_segment_index = max(0, int(start_segment_index or 0))

    candidate_entries = [
        entry for entry in ordered_entries
        if int(entry.get("_pageBP") or 0) >= actual_start_bp
    ]
    if not candidate_entries:
        preview["reason"] = "起始位置之后没有已译内容。"
        return preview
    first_entry_bp = int(candidate_entries[0].get("_pageBP") or 0)
    if first_entry_bp != actual_start_bp:
        actual_start_bp = first_entry_bp
        actual_start_segment_index = 0

    glossary = get_glossary(doc_id)
    affected_segments = 0
    skipped_manual_segments = 0
    target_bps = []
    target_segments_by_bp: dict[str, list[int]] = {}
    problem_segments: list[dict] = []
    problem_segment_limit = 20
    for entry in candidate_entries:
        bp = int(entry.get("_pageBP") or 0)
        has_target = False
        for seg_idx, segment in enumerate(entry.get("_page_entries") or []):
            if bp == actual_start_bp and seg_idx < actual_start_segment_index:
                continue
            diagnosis = diagnose_segment_glossary(
                _segment_glossary_source_text(segment),
                _segment_glossary_target_text(segment),
                glossary,
            )
            if not diagnosis.get("has_issue"):
                continue
            if _segment_is_manual(segment):
                skipped_manual_segments += 1
                continue
            if not _segment_is_retranslatable_machine(segment):
                continue
            affected_segments += 1
            has_target = True
            target_segments_by_bp.setdefault(str(bp), []).append(seg_idx)
            if len(problem_segments) < problem_segment_limit:
                problem_segments.append({
                    "bp": bp,
                    "segment_index": seg_idx,
                    "pages": ensure_str(segment.get("pages", "")).strip(),
                    "source_excerpt": _excerpt_text(_segment_glossary_source_text(segment)),
                    "translation_excerpt": _excerpt_text(_segment_glossary_target_text(segment)),
                    "missing_terms": [
                        {"term": term, "defn": defn}
                        for term, defn in (diagnosis.get("missing_terms") or [])
                    ],
                })
            elif not preview["problem_list_truncated"]:
                preview["problem_list_truncated"] = True
        if has_target:
            target_bps.append(bp)

    preview["start_bp"] = actual_start_bp
    preview["start_segment_index"] = actual_start_segment_index
    preview["end_bp"] = target_bps[-1] if target_bps else None
    preview["affected_pages"] = len(target_bps)
    preview["affected_segments"] = affected_segments
    preview["skipped_manual_segments"] = skipped_manual_segments
    preview["target_bps"] = target_bps
    preview["target_segments_by_bp"] = target_segments_by_bp
    preview["problem_segments"] = problem_segments
    preview["task"] = _build_translate_task_meta(
        kind=TASK_KIND_GLOSSARY_RETRANSLATE,
        label="词典补重译",
        start_bp=actual_start_bp,
        start_segment_index=actual_start_segment_index,
        target_bps=target_bps,
        target_segments_by_bp=target_segments_by_bp,
        affected_segments=affected_segments,
        skipped_manual_segments=skipped_manual_segments,
    )

    if not target_bps:
        if skipped_manual_segments > 0:
            preview["reason"] = "起始范围内命中词典问题的段落都已人工修订，没有可自动补重译的机器段落。"
        else:
            preview["reason"] = "起始范围内没有词典未生效的机器译文段落。"
        return preview

    snapshot = get_translate_snapshot(
        doc_id,
        pages=pages,
        entries=ordered_entries,
        visible_page_view=build_visible_page_view(pages),
    )
    if snapshot.get("running"):
        current_task = _normalize_translate_task_meta(snapshot.get("task"))
        if current_task.get("kind") == TASK_KIND_CONTINUOUS:
            preview["reason"] = "当前有连续翻译正在运行，新词典会从下一页起生效；补重译请在当前任务停止或完成后再发起。"
        else:
            preview["reason"] = "当前已有后台翻译任务正在运行，请等待完成或停止后再发起。"
        return preview

    preview["can_start"] = True
    return preview


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


def _extract_page_footnote_summary(page_entries: list[dict], fallback_footnotes: str = "") -> tuple[str, str]:
    footnote_parts = []
    footnote_translation_parts = []
    seen_footnotes = set()
    seen_translations = set()
    for entry in page_entries:
        if not isinstance(entry, dict):
            continue
        footnotes = ensure_str(entry.get("footnotes", "")).strip()
        footnotes_translation = ensure_str(entry.get("footnotes_translation", "")).strip()
        if footnotes and footnotes not in seen_footnotes:
            seen_footnotes.add(footnotes)
            footnote_parts.append(footnotes)
        if footnotes_translation and footnotes_translation not in seen_translations:
            seen_translations.add(footnotes_translation)
            footnote_translation_parts.append(footnotes_translation)
    page_footnotes = "\n".join(footnote_parts).strip() or ensure_str(fallback_footnotes).strip()
    page_footnotes_translation = "\n".join(footnote_translation_parts).strip()
    return page_footnotes, page_footnotes_translation


def _build_endnote_jobs(note_scan: dict, ctx: dict, target_bp: int) -> list[dict]:
    jobs = []
    for item in note_scan.get("items") or []:
        if str(item.get("kind", "")).strip() != "endnote":
            continue
        text = ensure_str(item.get("text", "")).strip()
        if not text:
            continue
        section_title = ensure_str(item.get("section_title", "")).strip()
        jobs.append({
            "para_idx": len(jobs),
            "source_idx": -1,
            "bp": target_bp,
            "heading_level": 0,
            "text": text,
            "cross_page": None,
            "start_bp": target_bp,
            "end_bp": target_bp,
            "print_page_label": str(ctx.get("print_page_label", "") or "").strip(),
            "print_page_display": str(ctx.get("print_page_display", "") or "").strip(),
            "bboxes": [],
            "footnotes": "",
            "prev_context": "",
            "next_context": "",
            "section_path": [section_title] if section_title else [],
            "content_role": "endnote",
            "note_kind": "endnote",
            "note_marker": ensure_str(item.get("marker", "")).strip(),
            "note_number": item.get("number"),
            "note_section_title": section_title,
            "note_confidence": float(item.get("confidence", 0.0) or 0.0),
        })
    return jobs


def _resolve_page_note_scan(pages: list[dict], target_bp: int, ctx: dict | None = None) -> dict:
    if isinstance(ctx, dict) and isinstance(ctx.get("note_scan"), dict):
        return ctx["note_scan"]
    for page in pages or []:
        if int(page.get("bookPage") or 0) != int(target_bp):
            continue
        scan = page.get("_note_scan")
        if isinstance(scan, dict):
            return scan
    return {}


def _build_para_jobs(paragraphs: list, ctx: dict, para_bboxes: list, target_bp: int, context_window: int = 200) -> list[dict]:
    jobs = []
    title_stack = []

    for idx, para in enumerate(paragraphs):
        hlevel = int(para.get("heading_level", 0) or 0)
        text = para.get("text", "").strip()
        if not text:
            continue

        if hlevel > 0:
            while len(title_stack) >= hlevel:
                title_stack.pop()
            title_stack.append(text)

        prev_text = ""
        next_text = ""
        for prev_idx in range(idx - 1, -1, -1):
            prev_candidate = paragraphs[prev_idx].get("text", "").strip()
            if prev_candidate:
                prev_text = prev_candidate
                break
        for next_idx in range(idx + 1, len(paragraphs)):
            next_candidate = paragraphs[next_idx].get("text", "").strip()
            if next_candidate:
                next_text = next_candidate
                break

        cross = para.get("cross_page")
        if not prev_text and cross in ("cont_prev", "cont_both"):
            prev_text = ctx.get("prev_tail", "") or ""
        if not next_text and cross in ("cont_next", "cont_both", "merged_next"):
            next_text = ctx.get("next_head", "") or ""

        jobs.append({
            "para_idx": len(jobs),
            "source_idx": idx,
            "bp": target_bp,
            "heading_level": hlevel,
            "text": text,
            "cross_page": cross,
            "start_bp": int(para.get("startBP", target_bp) or target_bp),
            "end_bp": int(para.get("endBP", target_bp) or target_bp),
            "print_page_label": str(para.get("printPageLabel", "") or "").strip(),
            "print_page_display": (
                f"原书 p.{str(para.get('printPageLabel', '') or '').strip()}"
                if str(para.get("printPageLabel", "") or "").strip()
                else ""
            ),
            "bboxes": para_bboxes[idx] if idx < len(para_bboxes) else [],
            "footnotes": ensure_str(para.get("footnotes", "")).strip(),
            "prev_context": "" if hlevel > 0 else _trim_para_context(prev_text, limit=context_window, from_end=True),
            "next_context": "" if hlevel > 0 else _trim_para_context(next_text, limit=context_window, from_end=False),
            "section_path": list(title_stack),
            "content_role": "body",
            "note_kind": "",
            "note_marker": "",
            "note_number": None,
            "note_section_title": "",
            "note_confidence": 0.0,
        })
    for job in jobs:
        job["para_total"] = len(jobs)
    return jobs


def _entry_model_meta(t_args: dict, fallback_model_key: str) -> dict:
    model_source = str(t_args.get("model_source", "builtin") or "builtin")
    model_key = str(t_args.get("model_key", "") or "").strip()
    model_id = str(t_args.get("model_id", "") or model_key or fallback_model_key).strip()
    provider = str(t_args.get("provider", "") or "").strip()
    display_label = str(t_args.get("display_label", "") or model_id or model_key or fallback_model_key).strip()
    return {
        "_model_source": model_source,
        "_model_key": model_key,
        "_model_id": model_id,
        "_provider": provider,
        "_display_label": display_label,
        "_model": model_id or model_key or fallback_model_key,
    }


def _make_page_entry(job: dict, target_bp: int, result: dict | None = None, error: str = "") -> dict:
    result = result or {}
    is_error = bool(error)
    translation = f"[翻译失败: {error}]" if is_error else ensure_str(result.get("translation", ""))
    source = str(result.get("_translation_source") or "").strip() or ("manual" if result.get("_manual_translation") else "model")
    machine_translation = ensure_str(result.get("_machine_translation", "")).strip()
    manual_translation = ensure_str(result.get("_manual_translation", "")).strip()
    if not is_error and source != "manual" and not machine_translation:
        machine_translation = translation
    if source == "manual" and not manual_translation and not is_error:
        manual_translation = translation
    result_footnotes = ensure_str(result.get("footnotes", "")).strip()
    job_footnotes = ensure_str(job.get("footnotes", "")).strip()
    footnotes = result_footnotes or job_footnotes
    footnotes_translation = ensure_str(result.get("footnotes_translation", "")).strip()
    pages_label = str(job.get("print_page_display", "") or "").strip()
    return {
        "original": ensure_str(result.get("original", job["text"])),
        "translation": translation,
        "footnotes": footnotes,
        "footnotes_translation": footnotes_translation,
        "heading_level": job["heading_level"],
        "pages": pages_label,
        "_rawText": job["text"],
        "_startBP": int(job.get("start_bp", target_bp) or target_bp),
        "_endBP": int(job.get("end_bp", target_bp) or target_bp),
        "_printPageLabel": str(job.get("print_page_label", "") or "").strip(),
        "_cross_page": job["cross_page"],
        "_bboxes": job["bboxes"],
        "_status": "error" if is_error else "done",
        "_error": str(error) if is_error else "",
        "_note_kind": ensure_str(job.get("note_kind", "")).strip(),
        "_note_marker": ensure_str(job.get("note_marker", "")).strip(),
        "_note_number": job.get("note_number"),
        "_note_section_title": ensure_str(job.get("note_section_title", "")).strip(),
        "_note_confidence": float(job.get("note_confidence", 0.0) or 0.0),
        "_machine_translation": machine_translation,
        "_manual_translation": manual_translation,
        "_translation_source": source,
        "_manual_updated_at": result.get("_manual_updated_at"),
        "_manual_updated_by": ensure_str(result.get("_manual_updated_by", "")).strip(),
        "updated_at": result.get("updated_at"),
    }


def _count_finished_paragraphs(states: list[str]) -> int:
    return sum(1 for state in states if state in ("done", "error"))


def _primary_para_idx(active_indices: set[int], states: list[str]) -> int | None:
    if active_indices:
        return min(active_indices)
    for idx in range(len(states) - 1, -1, -1):
        if states[idx] in ("done", "error", "aborted"):
            return idx
    return None


def _prepare_page_translate_jobs(pages, target_bp, t_args) -> tuple[dict, list[dict], dict]:
    total_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }

    ctx = get_page_context_for_translate(pages, target_bp)
    paragraphs = ctx["paragraphs"]
    note_scan = _resolve_page_note_scan(pages, target_bp, ctx)

    if paragraphs and _needs_llm_fix(paragraphs):
        cur = None
        for pg in pages:
            if pg["bookPage"] == target_bp:
                cur = pg
                break
        page_md = cur.get("markdown", "") if cur else ""
        if page_md:
            paragraphs, structure_usage = _llm_fix_paragraphs(paragraphs, page_md, t_args, target_bp)
            total_usage = _merge_usage(total_usage, structure_usage)

    para_bboxes = get_paragraph_bboxes(pages, target_bp, paragraphs) if paragraphs else []
    if paragraphs:
        paragraphs, resolved_page_footnotes = assign_page_footnotes_to_paragraphs(
            pages,
            target_bp,
            paragraphs,
            para_bboxes=para_bboxes,
        )
        ctx["footnotes"] = resolved_page_footnotes
    para_jobs = _build_para_jobs(paragraphs, ctx, para_bboxes, target_bp, context_window=_get_para_context_window())
    endnote_jobs = _build_endnote_jobs(note_scan, ctx, target_bp)
    page_kind = str(note_scan.get("page_kind", "") or "").strip()
    if page_kind == "endnote_collection":
        para_jobs = endnote_jobs
    elif page_kind == "mixed_body_endnotes":
        para_jobs.extend(endnote_jobs)
    for idx, job in enumerate(para_jobs):
        job["para_idx"] = idx
        job["para_total"] = len(para_jobs)

    if not para_jobs:
        raise RuntimeError(f"第{target_bp}页未找到有效内容")

    return ctx, para_jobs, total_usage


def translate_page(pages, target_bp, model_key, t_args, glossary):
    """翻译指定页面：基于 markdown 解析段落，处理跨页，逐段翻译。"""
    ctx, para_jobs, total_usage = _prepare_page_translate_jobs(pages, target_bp, t_args)

    # 段内并发翻译，和流式路径保持同一上限。
    results = [None] * len(para_jobs)
    max_parallel = _get_para_max_concurrency(model_key, len(para_jobs))
    request_args = _provider_request_args(t_args)
    split_page_footnotes = _should_split_mt_page_footnotes(request_args, ctx)

    def _do_translate(job: dict):
        footnotes = "" if split_page_footnotes and str(job.get("content_role", "body") or "body").strip() == "body" else job["footnotes"]
        translate_kwargs = _job_request_args(request_args, job)
        return job["para_idx"], translate_paragraph(
            para_text=job["text"],
            para_pages=job.get("print_page_label") or str(target_bp),
            footnotes=footnotes,
            glossary=glossary,
            heading_level=job["heading_level"],
            para_idx=job["para_idx"],
            para_total=job["para_total"],
            prev_context=job["prev_context"],
            next_context=job["next_context"],
            section_path=job["section_path"],
            cross_page=job["cross_page"],
            content_role=job.get("content_role", "body"),
            **translate_kwargs,
        )

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {
            pool.submit(_do_translate, job): job
            for job in para_jobs
        }
        for future in as_completed(futures):
            job = futures[future]
            try:
                _, p = future.result()
            except Exception as e:
                p = {"original": job["text"], "translation": f"[翻译失败: {e}]",
                     "footnotes": "", "footnotes_translation": ""}
            total_usage = _merge_usage(total_usage, p.get("_usage"))
            results[job["para_idx"]] = _make_page_entry(job, target_bp, result=p)

    page_entries = [r for r in results if r is not None]
    page_entries, total_usage = _apply_page_footnote_translation(
        page_entries=page_entries,
        target_bp=target_bp,
        ctx=ctx,
        glossary=glossary,
        request_args=request_args,
        total_usage=total_usage,
    )
    page_footnotes, page_footnotes_translation = _extract_page_footnote_summary(
        page_entries,
        fallback_footnotes=ctx.get("footnotes", ""),
    )

    return {
        "_pageBP": target_bp,
        **_entry_model_meta(t_args, model_key),
        "_usage": total_usage,
        "_page_entries": page_entries,
        "footnotes": page_footnotes,
        "footnotes_translation": page_footnotes_translation,
        "pages": ctx.get("print_page_display", ""),
    }


def translate_page_stream(
    pages,
    target_bp,
    model_key,
    t_args,
    glossary,
    doc_id: str,
    stop_checker=None,
    *,
    fnm_doc_id: str | None = None,
    prepared_ctx: dict | None = None,
    prepared_para_jobs: list[dict] | None = None,
    prepared_total_usage: dict | None = None,
    prepared_is_fnm: bool = False,
):
    """流式翻译指定页面：段内有界并发推送增量，但仅在整页完成后返回 entry。

    fnm_doc_id 若设置，则使用 FNM 章节/尾注区单元任务；结果回写 translation_pages 与 fnm_translation_units，
    FNM 注释与页投影均从结构真相层现算，不再依赖旧的 fnm_notes/fnm_page_entries 持久化表。
    prepared_* 若设置，则直接复用外部准备好的上下文/段落任务，仍走同一套流式并发内核。
    """
    total_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }
    if prepared_para_jobs is not None:
        ctx = dict(prepared_ctx or {})
        para_jobs = [dict(job) for job in (prepared_para_jobs or [])]
        total_usage = _merge_usage(total_usage, prepared_total_usage or {})
    elif fnm_doc_id:
        from FNM_RE import prepare_page_translate_jobs

        ctx, para_jobs, total_usage = prepare_page_translate_jobs(
            pages, target_bp, t_args, fnm_doc_id
        )
    else:
        ctx, para_jobs, total_usage = _prepare_page_translate_jobs(pages, target_bp, t_args)
    for idx, job in enumerate(para_jobs):
        job.setdefault("para_idx", idx)
        job["para_total"] = len(para_jobs)
    fnm_mode = bool(fnm_doc_id) or bool(prepared_is_fnm)

    max_parallel = _get_para_max_concurrency(model_key, len(para_jobs))
    dynamic_parallel_limit = max_parallel
    request_args = _provider_request_args(t_args)
    split_page_footnotes = _should_split_mt_page_footnotes(request_args, ctx)
    results = [None] * len(para_jobs)
    paragraph_texts = [""] * len(para_jobs)
    paragraph_states = ["pending"] * len(para_jobs)
    paragraph_errors = [""] * len(para_jobs)
    active_para_indices = set()
    event_queue: queue.Queue = queue.Queue()
    pending_jobs = list(para_jobs)
    running_count = 0
    aborted = False
    scheduled_para_indices = set()
    finished_para_indices = set()
    consecutive_rate_limits = 0
    successful_after_throttle = 0

    def _save_parallel_draft(status: str, note: str, last_error: str = ""):
        ordered_active = sorted(active_para_indices)
        _save_stream_draft(
            doc_id,
            active=bool(active_para_indices) and status == "streaming",
            bp=target_bp,
            para_idx=_primary_para_idx(active_para_indices, paragraph_states),
            para_total=len(para_jobs),
            para_done=_count_finished_paragraphs(paragraph_states),
            parallel_limit=max_parallel,
            active_para_indices=ordered_active,
            paragraph_states=list(paragraph_states),
            paragraph_errors=list(paragraph_errors),
            paragraphs=list(paragraph_texts),
            status=status,
            note=note,
            last_error=last_error,
        )

    def _worker_stream(job: dict):
        event_queue.put({"type": "start", "job": job})
        try:
            translate_kwargs = _job_request_args(request_args, job)
            for event in stream_translate_paragraph(
                para_text=job["text"],
                para_pages=job.get("print_page_label") or str(target_bp),
                footnotes="" if split_page_footnotes and str(job.get("content_role", "body") or "body").strip() == "body" else job["footnotes"],
                glossary=glossary,
                stop_checker=None,
                heading_level=job["heading_level"],
                para_idx=job["para_idx"],
                para_total=job["para_total"],
                prev_context=job["prev_context"],
                next_context=job["next_context"],
                section_path=job["section_path"],
                cross_page=job["cross_page"],
                content_role=job.get("content_role", "body"),
                is_fnm=fnm_mode,
                **translate_kwargs,
            ):
                payload = {"type": event["type"], "job": job}
                payload.update({k: v for k, v in event.items() if k != "type"})
                event_queue.put(payload)
        except TranslateStreamAborted:
            event_queue.put({"type": "aborted", "job": job})
        except QuotaExceededError as e:
            event_queue.put({"type": "error", "job": job, "error": str(e), "error_kind": "quota"})
        except NonRetryableProviderError as e:
            event_queue.put({
                "type": "error",
                "job": job,
                "error": str(e),
                "error_kind": "fatal_provider",
                "status_code": getattr(e, "status_code", None),
            })
        except RateLimitedError as e:
            event_queue.put({
                "type": "error",
                "job": job,
                "error": str(e),
                "error_kind": "rate_limit",
                "retry_after_s": float(e.retry_after_s) if e.retry_after_s is not None else None,
            })
        except TransientProviderError as e:
            event_queue.put({
                "type": "error",
                "job": job,
                "error": str(e),
                "error_kind": "transient",
                "retry_after_s": float(e.retry_after_s) if e.retry_after_s is not None else None,
            })
        except Exception as e:
            event_queue.put({"type": "error", "job": job, "error": str(e)})

    def _submit_next_job(pool: ThreadPoolExecutor) -> bool:
        nonlocal running_count
        if aborted or not pending_jobs:
            return False
        job = None
        while pending_jobs:
            candidate = pending_jobs.pop(0)
            para_idx = candidate["para_idx"]
            if para_idx in scheduled_para_indices or para_idx in finished_para_indices:
                continue
            job = candidate
            break
        if not job:
            return False
        scheduled_para_indices.add(job["para_idx"])
        pool.submit(_worker_stream, job)
        running_count += 1
        return True

    def _compute_backoff_seconds(error_kind: str, retry_after_s: float | None = None) -> float:
        nonlocal consecutive_rate_limits
        if retry_after_s is not None and retry_after_s >= 0:
            return min(90.0, float(retry_after_s))
        if error_kind == "rate_limit":
            consecutive_rate_limits += 1
            # 8/16/32/64/90 秒封顶 + 抖动，避免并发请求同时恢复。
            base = min(90.0, 8.0 * (2 ** max(0, consecutive_rate_limits - 1)))
            return min(90.0, base + (0.1 * (consecutive_rate_limits % 10)))
        return 3.0

    def _emit_throttle_wait(seconds: float, reason: str):
        wait_s = max(0.0, float(seconds))
        msg = f"触发{reason}，等待 {int(wait_s)} 秒后自动重试。"
        translate_push("rate_limit_wait", {
            "doc_id": doc_id,
            "bp": target_bp,
            "wait_seconds": int(wait_s),
            "reason": reason,
            "parallel_limit": dynamic_parallel_limit,
            "max_parallel": max_parallel,
            "message": msg,
        })
        _save_stream_draft(
            doc_id,
            active=False,
            bp=target_bp,
            para_idx=_primary_para_idx(active_para_indices, paragraph_states),
            para_total=len(para_jobs),
            para_done=_count_finished_paragraphs(paragraph_states),
            parallel_limit=dynamic_parallel_limit,
            active_para_indices=sorted(active_para_indices),
            paragraph_states=list(paragraph_states),
            paragraph_errors=list(paragraph_errors),
            paragraphs=list(paragraph_texts),
            status="throttled",
            note=msg,
            last_error="",
        )

    translate_push("stream_page_init", {
        "doc_id": doc_id,
        "bp": target_bp,
        "para_total": len(para_jobs),
        "parallel_limit": max_parallel,
    })
    _save_stream_draft(
        doc_id,
        active=True,
        bp=target_bp,
        para_idx=0 if para_jobs else None,
        para_total=len(para_jobs),
        para_done=0,
        parallel_limit=max_parallel,
        paragraphs=[""] * len(para_jobs),
        active_para_indices=[],
        paragraph_states=["pending"] * len(para_jobs),
        paragraph_errors=[""] * len(para_jobs),
        status="streaming",
        note="当前页正在流式翻译，完整结束后才会写入硬盘。",
        last_error="",
    )

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        for _ in range(dynamic_parallel_limit):
            if not _submit_next_job(pool):
                break

        while running_count > 0:
            event = event_queue.get()
            job = event["job"]
            para_idx = job["para_idx"]
            evt_type = event["type"]

            if evt_type == "start":
                active_para_indices.add(para_idx)
                paragraph_states[para_idx] = "running"
                paragraph_errors[para_idx] = ""
                translate_push("stream_para_start", {
                    "doc_id": doc_id,
                    "bp": target_bp,
                    "para_idx": para_idx,
                })
                _save_parallel_draft("streaming", "当前页尚未提交到硬盘；如请求停止，将在本页完成后停止。")
                continue

            if evt_type == "delta":
                delta_text = event.get("text", "")
                if delta_text:
                    paragraph_texts[para_idx] = event.get("translation_so_far", paragraph_texts[para_idx] + delta_text)
                    translate_push("stream_para_delta", {
                        "doc_id": doc_id,
                        "bp": target_bp,
                        "para_idx": para_idx,
                        "delta": delta_text,
                        "translation_so_far": paragraph_texts[para_idx],
                    })
                    _save_parallel_draft("streaming", "当前页尚未提交到硬盘；如请求停止，将在本页完成后停止。")
                continue

            if evt_type == "usage":
                total_usage = _merge_usage(total_usage, event.get("usage"))
                translate_push("stream_usage", {
                    "doc_id": doc_id,
                    "bp": target_bp,
                    "para_idx": para_idx,
                    "usage": event.get("usage", {}),
                })
                continue

            running_count = max(0, running_count - 1)
            active_para_indices.discard(para_idx)

            if evt_type == "done":
                finished_para_indices.add(para_idx)
                p = event["result"]
                results[para_idx] = _make_page_entry(job, target_bp, result=p)
                if fnm_mode and fnm_doc_id and job.get("fnm_note_id"):
                    SQLiteRepository().update_fnm_note_translation(
                        fnm_doc_id,
                        job["fnm_note_id"],
                        replace_frozen_refs(ensure_str(p.get("translation", ""))),
                        status="done",
                    )
                paragraph_texts[para_idx] = ensure_str(p.get("translation", ""))
                paragraph_states[para_idx] = "done"
                paragraph_errors[para_idx] = ""
                if consecutive_rate_limits > 0:
                    successful_after_throttle += 1
                    if successful_after_throttle >= 20 and dynamic_parallel_limit < max_parallel:
                        dynamic_parallel_limit += 1
                        successful_after_throttle = 0
                else:
                    successful_after_throttle = 0
                translate_push("stream_para_done", {
                    "doc_id": doc_id,
                    "bp": target_bp,
                    "para_idx": para_idx,
                    "translation": paragraph_texts[para_idx],
                })
                _save_parallel_draft("streaming", "该段已完成，正在继续翻译后续段落。")
            elif evt_type == "error":
                error_kind = event.get("error_kind", "")
                error_text = str(event.get("error", "未知错误"))
                if error_kind == "quota":
                    paragraph_states[para_idx] = "error"
                    paragraph_errors[para_idx] = error_text
                    _save_stream_draft(
                        doc_id,
                        active=False,
                        bp=target_bp,
                        para_idx=para_idx,
                        para_total=len(para_jobs),
                        para_done=_count_finished_paragraphs(paragraph_states),
                        parallel_limit=dynamic_parallel_limit,
                        active_para_indices=sorted(active_para_indices),
                        paragraph_states=list(paragraph_states),
                        paragraph_errors=list(paragraph_errors),
                        paragraphs=list(paragraph_texts),
                        status="error",
                        note="检测到额度耗尽，已停止自动重试。",
                        last_error=error_text,
                    )
                    raise QuotaExceededError(error_text)
                if error_kind == "fatal_provider":
                    paragraph_states[para_idx] = "error"
                    paragraph_errors[para_idx] = error_text
                    _save_stream_draft(
                        doc_id,
                        active=False,
                        bp=target_bp,
                        para_idx=para_idx,
                        para_total=len(para_jobs),
                        para_done=_count_finished_paragraphs(paragraph_states),
                        parallel_limit=dynamic_parallel_limit,
                        active_para_indices=sorted(active_para_indices),
                        paragraph_states=list(paragraph_states),
                        paragraph_errors=list(paragraph_errors),
                        paragraphs=list(paragraph_texts),
                        status="error",
                        note="检测到不可重试的上游请求错误，已停止当前任务。",
                        last_error=error_text,
                    )
                    raise NonRetryableProviderError(
                        error_text,
                        status_code=event.get("status_code"),
                    )
                if error_kind in ("rate_limit", "transient"):
                    paragraph_states[para_idx] = "pending"
                    paragraph_errors[para_idx] = ""
                    scheduled_para_indices.discard(para_idx)
                    finished_para_indices.discard(para_idx)
                    pending_jobs.insert(0, job)
                    wait_seconds = _compute_backoff_seconds(error_kind, event.get("retry_after_s"))
                    if error_kind == "rate_limit":
                        dynamic_parallel_limit = max(1, dynamic_parallel_limit // 2)
                        successful_after_throttle = 0
                    _emit_throttle_wait(wait_seconds, "限流" if error_kind == "rate_limit" else "临时故障")
                    deadline = time.time() + wait_seconds
                    while time.time() < deadline:
                        if stop_checker and stop_checker():
                            raise TranslateStreamAborted("用户停止流式翻译")
                        time.sleep(0.2)
                    while running_count < dynamic_parallel_limit and not aborted and pending_jobs:
                        if not _submit_next_job(pool):
                            break
                    continue
                finished_para_indices.add(para_idx)
                results[para_idx] = _make_page_entry(job, target_bp, error=error_text)
                paragraph_texts[para_idx] = results[para_idx]["translation"]
                paragraph_states[para_idx] = "error"
                paragraph_errors[para_idx] = error_text
                translate_push("stream_para_error", {
                    "doc_id": doc_id,
                    "bp": target_bp,
                    "para_idx": para_idx,
                    "error": error_text,
                    "translation": paragraph_texts[para_idx],
                })
                _save_parallel_draft("streaming", "该段翻译失败，已记录失败占位文本。", last_error=error_text)
            elif evt_type == "aborted":
                finished_para_indices.add(para_idx)
                paragraph_states[para_idx] = "aborted"
                aborted = True
            else:
                finished_para_indices.add(para_idx)
                paragraph_states[para_idx] = "error"
                paragraph_errors[para_idx] = f"未知事件: {evt_type}"
                results[para_idx] = _make_page_entry(job, target_bp, error=f"未知事件: {evt_type}")
                paragraph_texts[para_idx] = results[para_idx]["translation"]
                translate_push("stream_para_error", {
                    "doc_id": doc_id,
                    "bp": target_bp,
                    "para_idx": para_idx,
                    "error": f"未知事件: {evt_type}",
                    "translation": paragraph_texts[para_idx],
                })
                _save_parallel_draft("streaming", "该段翻译失败，已记录失败占位文本。", last_error=f"未知事件: {evt_type}")

            while running_count < dynamic_parallel_limit and not aborted and pending_jobs:
                if not _submit_next_job(pool):
                    break

        if aborted:
            translate_push("stream_page_aborted", {
                "doc_id": doc_id,
                "bp": target_bp,
                "para_idx": _primary_para_idx(active_para_indices, paragraph_states),
            })
            _save_parallel_draft("aborted", "当前页已停止，草稿未提交到硬盘。")
            raise TranslateStreamAborted("用户停止流式翻译")

    page_entries = [entry for entry in results if entry is not None]

    if not page_entries:
        raise RuntimeError(f"第{target_bp}页未找到有效内容")

    page_entries, total_usage = _apply_page_footnote_translation(
        page_entries=page_entries,
        target_bp=target_bp,
        ctx=ctx,
        glossary=glossary,
        request_args=request_args,
        total_usage=total_usage,
    )

    page_footnotes, page_footnotes_translation = _extract_page_footnote_summary(
        page_entries,
        fallback_footnotes=ctx.get("footnotes", ""),
    )

    paragraph_texts = [ensure_str(entry.get("translation", "")) if entry else "" for entry in results]
    paragraph_states = [
        ("error" if entry and entry.get("_status") == "error" else "done") if entry else state
        for entry, state in zip(results, paragraph_states)
    ]
    _save_parallel_draft("done", "当前页已完整提交到硬盘。")

    return {
        "_pageBP": target_bp,
        **_entry_model_meta(t_args, model_key),
        "_usage": total_usage,
        "_page_entries": page_entries,
        "footnotes": page_footnotes,
        "footnotes_translation": page_footnotes_translation,
        "pages": ctx.get("print_page_display", ""),
    }


def _job_structure_signature(job: dict) -> tuple:
    return (
        int(job.get("heading_level", 0) or 0),
        int(job.get("start_bp", 0) or 0),
        int(job.get("end_bp", 0) or 0),
        ensure_str(job.get("note_kind", "")).strip(),
        ensure_str(job.get("note_marker", "")).strip(),
    )


def _segment_structure_signature(segment: dict) -> tuple:
    return (
        int(segment.get("heading_level", 0) or 0),
        int(segment.get("_startBP", 0) or 0),
        int(segment.get("_endBP", 0) or 0),
        ensure_str(segment.get("_note_kind", "")).strip(),
        ensure_str(segment.get("_note_marker", "")).strip(),
    )


def _validate_glossary_retranslate_structure(existing_entry: dict, para_jobs: list[dict], target_bp: int) -> None:
    existing_segments = list((existing_entry or {}).get("_page_entries") or [])
    if len(existing_segments) != len(para_jobs):
        raise RuntimeError(
            f"第{target_bp}页段落结构已变化，请改用整页重译。"
        )
    for idx, (segment, job) in enumerate(zip(existing_segments, para_jobs)):
        if _segment_structure_signature(segment) != _job_structure_signature(job):
            raise RuntimeError(
                f"第{target_bp}页第{idx + 1}段结构已变化，请改用整页重译。"
            )


def _build_preserved_page_entry(job: dict, target_bp: int, segment: dict) -> dict:
    result = {
        "original": segment.get("original", job.get("text", "")),
        "translation": segment.get("translation", ""),
        "footnotes": segment.get("footnotes", ""),
        "footnotes_translation": segment.get("footnotes_translation", ""),
        "_machine_translation": _segment_machine_translation_text(segment),
        "_manual_translation": ensure_str(segment.get("_manual_translation", "")).strip(),
        "_translation_source": segment.get("_translation_source") or ("manual" if _segment_is_manual(segment) else "model"),
        "_manual_updated_at": segment.get("_manual_updated_at"),
        "_manual_updated_by": segment.get("_manual_updated_by"),
        "updated_at": segment.get("updated_at"),
    }
    preserved = _make_page_entry(job, target_bp, result=result)
    preserved["_status"] = segment.get("_status", "done")
    preserved["_error"] = ensure_str(segment.get("_error", "")).strip()
    return preserved


def retranslate_page_with_current_glossary(
    pages,
    target_bp: int,
    existing_entry: dict,
    model_key: str,
    t_args: dict,
    glossary: list,
    *,
    target_segment_indices: list[int] | None = None,
) -> tuple[dict, dict]:
    ctx, para_jobs, total_usage = _prepare_page_translate_jobs(pages, target_bp, t_args)
    _validate_glossary_retranslate_structure(existing_entry, para_jobs, target_bp)
    existing_segments = list((existing_entry or {}).get("_page_entries") or [])
    request_args = _provider_request_args(t_args)
    results: list[dict | None] = [None] * len(para_jobs)
    target_items: list[tuple[int, dict, dict]] = []
    skipped_manual_segments = 0
    targeted_segment_indices: list[int] = []
    requested_indices = {
        int(idx)
        for idx in (target_segment_indices or [])
        if idx is not None
    }
    if not requested_indices:
        raise RuntimeError("当前页没有命中的词典问题段落可补重译。")

    for idx, job in enumerate(para_jobs):
        segment = existing_segments[idx]
        if requested_indices and idx not in requested_indices:
            results[idx] = _build_preserved_page_entry(job, target_bp, segment)
            continue
        if _segment_is_manual(segment):
            skipped_manual_segments += 1
            results[idx] = _build_preserved_page_entry(job, target_bp, segment)
            continue
        if not _segment_is_retranslatable_machine(segment):
            results[idx] = _build_preserved_page_entry(job, target_bp, segment)
            continue
        target_items.append((idx, job, segment))
        targeted_segment_indices.append(idx)

    if not target_items:
        raise RuntimeError("起始范围内没有可按词典补重译的机器译文段落。")

    def _do_translate(item: tuple[int, dict, dict]):
        idx, job, _segment = item
        translated = translate_paragraph(
            para_text=job["text"],
            para_pages=job.get("print_page_label") or str(target_bp),
            footnotes=job["footnotes"],
            glossary=glossary,
            heading_level=job["heading_level"],
            para_idx=job["para_idx"],
            para_total=job["para_total"],
            prev_context=job["prev_context"],
            next_context=job["next_context"],
            section_path=job["section_path"],
            cross_page=job["cross_page"],
            content_role=job.get("content_role", "body"),
            **request_args,
        )
        return idx, job, translated

    max_parallel = _get_para_max_concurrency(model_key, len(target_items))
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {
            pool.submit(_do_translate, item): item
            for item in target_items
        }
        for future in as_completed(futures):
            idx, job, segment = futures[future]
            try:
                _, translated_job, translated = future.result()
                total_usage = _merge_usage(total_usage, translated.get("_usage"))
                results[idx] = _make_page_entry(translated_job, target_bp, result=translated)
            except Exception as exc:
                preserved = _build_preserved_page_entry(job, target_bp, segment)
                preserved["_status"] = "error"
                preserved["_error"] = str(exc)
                results[idx] = preserved

    page_entries = [entry for entry in results if entry is not None]
    page_footnotes, page_footnotes_translation = _extract_page_footnote_summary(
        page_entries,
        fallback_footnotes=ctx.get("footnotes", ""),
    )
    return (
        {
            "_pageBP": target_bp,
            **_entry_model_meta(t_args, model_key),
            "_usage": total_usage,
            "_page_entries": page_entries,
            "footnotes": page_footnotes,
            "footnotes_translation": page_footnotes_translation,
            "pages": ctx.get("print_page_display", ""),
        },
        {
            "targeted_segments": len(target_items),
            "targeted_segment_indices": targeted_segment_indices,
            "skipped_manual_segments": skipped_manual_segments,
        },
    )


# ============ 后台连续翻译 ============


def _translate_worker_deps(owner_token: int | None = None) -> dict:
    if owner_token is None:
        owner_token = get_current_owner_token()
    return {
        "mark_translate_start_error": mark_translate_start_error,
        "translate_push": translate_push,
        "load_translate_state": _load_translate_state,
        "save_translate_state": _save_translate_state,
        "default_stream_draft_state": _default_stream_draft_state,
        "save_stream_draft": _save_stream_draft,
        "runtime_stop_requested": _runtime_stop_requested,
        "is_stop_requested": is_stop_requested,
        "clamp_page_progress": _clamp_page_progress,
        "remaining_pages": _remaining_pages,
        "mark_failed_page_state": _mark_failed_page_state,
        "clear_failed_page_state": _clear_failed_page_state,
        "collect_partial_failed_bps": _collect_partial_failed_bps,
        "entry_has_paragraph_error": _entry_has_paragraph_error,
        "release_runtime": lambda: release_translate_runtime(owner_token),
        "get_doc_meta": get_doc_meta,
        "load_pages_from_disk": load_pages_from_disk,
        "load_entries_from_disk": load_entries_from_disk,
        "save_entry_to_disk": save_entry_to_disk,
        "get_active_translate_args": _get_active_translate_args,
        "build_visible_page_view": build_visible_page_view,
        "resolve_visible_page_bp": resolve_visible_page_bp,
        "collect_target_bps": _collect_target_bps,
        "get_glossary": get_glossary,
        "translate_page_stream": translate_page_stream,
        "retranslate_page_with_current_glossary": retranslate_page_with_current_glossary,
    }


def _translate_all_worker(doc_id: str, start_bp: int, doc_title: str, owner_token: int | None = None):
    """后台线程：从 start_bp 开始逐页翻译，每页完成后写入磁盘。"""
    return _run_translate_all_worker_impl(
        doc_id,
        start_bp,
        doc_title,
        _translate_worker_deps(owner_token),
    )


def _glossary_retranslate_worker(doc_id: str, task_meta: dict, doc_title: str, owner_token: int | None = None):
    return _run_glossary_retranslate_worker_impl(
        doc_id,
        task_meta,
        doc_title,
        _translate_worker_deps(owner_token),
    )


def _fnm_translate_worker(doc_id: str, doc_title: str, owner_token: int | None = None):
    return _run_fnm_worker_impl(
        doc_id,
        doc_title,
        _translate_worker_deps(owner_token),
    )

"""后台任务：OCR 文件处理、页面翻译、连续翻译 worker。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import queue
import re
import tempfile
import threading
import time

import config as app_config
from config import (
    MODELS,
    get_paddle_token, get_glossary, get_model_key,
    create_doc, get_doc_dir, get_doc_meta, get_doc_auto_visual_toc_enabled,
    get_upload_cleanup_headers_footers_enabled, get_upload_auto_visual_toc_enabled,
)
from sqlite_store import SQLiteRepository
from ocr_client import call_paddle_ocr_bytes
from text_processing import (
    parse_ocr, clean_header_footer,
    extract_pdf_text, combine_sources,
    get_page_range, get_next_page_bp,
    build_visible_page_view, resolve_visible_page_bp,
    get_page_context_for_translate,
    get_paragraph_bboxes,
    assign_page_footnotes_to_paragraphs,
)
from translator import (
    TranslateStreamAborted,
    RateLimitedError,
    TransientProviderError,
    QuotaExceededError,
    review_note_page,
    stream_translate_paragraph,
    translate_paragraph,
    structure_page,
)
from note_detection import annotate_pages_with_note_scans
from storage import (
    save_pages_to_disk, load_pages_from_disk,
    save_entries_to_disk, save_entry_to_disk, load_entries_from_disk,
    save_auto_pdf_toc_to_disk,
    get_translate_args, _ensure_str, resolve_model_spec,
)
from pdf_extract import extract_pdf_toc, extract_pdf_toc_from_links
from visual_toc import generate_auto_visual_toc_for_doc


# ============ OCR TASK MANAGEMENT ============

_tasks = {}  # task_id -> {"status", "events": [], "file_path", "file_name", "file_type"}
_tasks_lock = threading.Lock()


def task_push(task_id: str, event_type: str, data: dict):
    with _tasks_lock:
        if task_id in _tasks:
            _tasks[task_id]["events"].append((event_type, data))


def get_task(task_id: str) -> dict | None:
    with _tasks_lock:
        return _tasks.get(task_id)


def create_task(
    task_id: str,
    file_path: str,
    file_name: str,
    file_type: int,
    options: dict | None = None,
):
    normalized_options = {}
    if isinstance(options, dict) and "clean_header_footer" in options:
        normalized_options["clean_header_footer"] = bool(options.get("clean_header_footer"))
    if isinstance(options, dict) and "auto_visual_toc" in options:
        normalized_options["auto_visual_toc"] = bool(options.get("auto_visual_toc"))
    with _tasks_lock:
        _tasks[task_id] = {
            "status": "pending",
            "events": [],
            "file_path": file_path,
            "file_name": file_name,
            "file_type": file_type,
            "options": normalized_options,
        }


def _resolve_cleanup_headers_footers(task: dict | None, doc_id: str = "") -> bool:
    options = (task or {}).get("options") or {}
    if "clean_header_footer" in options:
        return bool(options.get("clean_header_footer"))
    if doc_id:
        return app_config.get_doc_cleanup_headers_footers(
            doc_id,
            default=app_config.DOC_CLEANUP_HEADERS_FOOTERS_DEFAULT,
        )
    return bool(app_config.UPLOAD_CLEANUP_HEADERS_FOOTERS_DEFAULT)


def _resolve_auto_visual_toc(task: dict | None, doc_id: str = "") -> bool:
    options = (task or {}).get("options") or {}
    if "auto_visual_toc" in options:
        return bool(options.get("auto_visual_toc"))
    if doc_id:
        return get_doc_auto_visual_toc_enabled(
            doc_id,
            default=app_config.DOC_AUTO_VISUAL_TOC_DEFAULT,
        )
    return bool(app_config.UPLOAD_AUTO_VISUAL_TOC_DEFAULT)


def _apply_cleanup_mode_to_pages(
    pages: list[dict],
    *,
    cleanup_enabled: bool,
) -> list[dict]:
    flagged_pages = []
    for page in pages or []:
        page_payload = dict(page)
        page_payload["_cleanup_applied"] = bool(cleanup_enabled)
        flagged_pages.append(page_payload)
    return flagged_pages


def _refresh_upload_task_runtime_options(
    task_id: str,
    *,
    cleanup_enabled: bool,
    auto_visual_toc_enabled: bool,
) -> tuple[bool, bool, list[str]]:
    refreshed_cleanup = get_upload_cleanup_headers_footers_enabled(default=cleanup_enabled)
    refreshed_auto_visual = get_upload_auto_visual_toc_enabled(default=auto_visual_toc_enabled)
    logs: list[str] = []
    if refreshed_cleanup != cleanup_enabled:
        logs.append(
            "检测到上传后的页眉页脚清理勾选已更新，后续将按最新选择继续处理。"
        )
    if refreshed_auto_visual != auto_visual_toc_enabled:
        logs.append(
            "检测到上传后的自动视觉目录勾选已更新，后续将按最新选择继续处理。"
        )
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task is not None:
            options = dict(task.get("options") or {})
            options["clean_header_footer"] = refreshed_cleanup
            options["auto_visual_toc"] = refreshed_auto_visual
            task["options"] = options
    return refreshed_cleanup, refreshed_auto_visual, logs


def start_auto_visual_toc_for_doc(doc_id: str, pdf_path: str, model_spec=None):
    """后台触发自动视觉目录生成，不阻塞 OCR 主任务。"""
    if not doc_id or not pdf_path or not os.path.exists(pdf_path):
        return None

    def _runner():
        generate_auto_visual_toc_for_doc(doc_id, pdf_path=pdf_path, model_spec=model_spec)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return thread


def _push_cleanup_progress(task_id: str, phase: str, pct: int, detail: str, *, start_pct: int = 85, end_pct: int = 90):
    local_pct = max(0, min(100, int(pct or 0)))
    total_pct = start_pct + ((end_pct - start_pct) * local_pct / 100.0)
    label_map = {
        "collect_candidates": "收集页眉/页脚候选…",
        "detect_patterns": "统计重复模式…",
        "apply_cleanup": "正在应用页眉页脚清理…",
        "note_scan_ready": "进入脚注/尾注检测…",
    }
    task_push(task_id, "progress", {
        "pct": total_pct,
        "label": label_map.get(phase, "清理页眉页脚…"),
        "detail": detail or "",
    })


def get_task_events(task_id: str, cursor: int) -> tuple[list, bool]:
    """获取从 cursor 开始的事件，返回 (events, task_exists)。"""
    with _tasks_lock:
        task = _tasks.get(task_id)
        if not task:
            return [], False
        events = task["events"][cursor:]
        return events, True


def set_task_final(task_id: str, logs: list, summary: str):
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task:
            task["final_logs"] = logs
            task["summary"] = summary


def remove_task(task_id: str):
    with _tasks_lock:
        _tasks.pop(task_id, None)


def process_file(task_id: str):
    """Background thread: run OCR pipeline and push SSE events."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return

    file_path = task["file_path"]
    file_name = task["file_name"]
    file_type = task["file_type"]
    paddle_token = get_paddle_token()
    cleanup_enabled = _resolve_cleanup_headers_footers(task)
    auto_visual_toc_enabled = _resolve_auto_visual_toc(task)

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        all_logs = []

        # Step 1: OCR
        task_push(task_id, "progress", {"pct": 5, "label": "调用 PaddleOCR 解析版面…", "detail": ""})

        def on_ocr_progress(chunk_i, total_chunks):
            pct = 5 + (chunk_i / total_chunks) * 60
            task_push(task_id, "progress", {
                "pct": pct,
                "label": f"OCR 解析中… ({chunk_i}/{total_chunks})",
                "detail": f"分片 {chunk_i}/{total_chunks}",
                "log": f"OCR 分片 {chunk_i}/{total_chunks} 完成",
            })

        result = call_paddle_ocr_bytes(
            file_bytes=file_bytes,
            token=paddle_token,
            file_type=file_type,
            on_progress=on_ocr_progress,
        )

        task_push(task_id, "progress", {"pct": 65, "label": "解析 OCR 结果…", "detail": ""})
        task_push(task_id, "log", {"msg": "OCR API 调用完成"})

        parsed = parse_ocr(result)
        if not parsed["pages"]:
            task_push(task_id, "error_msg", {"error": "解析失败：未获取到任何页面数据"})
            return
        all_logs.extend(parsed["log"])
        for lg in parsed["log"]:
            task_push(task_id, "log", {"msg": lg})

        # Step 2: PDF text extraction
        if file_type == 0:
            task_push(task_id, "progress", {"pct": 72, "label": "提取 PDF 文字层…", "detail": ""})
            pdf_pages = extract_pdf_text(file_bytes)
            if pdf_pages:
                task_push(task_id, "log", {"msg": f"检测到PDF文字层 ({len(pdf_pages)}页)", "cls": "success"})
                all_logs.append(f"检测到PDF文字层 ({len(pdf_pages)}页)")

                task_push(task_id, "progress", {"pct": 78, "label": "合并 PDF 文字与 OCR 布局…", "detail": ""})
                combined = combine_sources(parsed["pages"], pdf_pages)
                parsed["pages"] = combined["pages"]
                all_logs.extend(combined["log"])
                for lg in combined["log"]:
                    task_push(task_id, "log", {"msg": lg, "cls": "success"})
            else:
                task_push(task_id, "log", {"msg": "PDF无有效文字层，使用OCR文字"})
                all_logs.append("PDF无有效文字层，使用OCR文字")

        cleanup_enabled, auto_visual_toc_enabled, refreshed_option_logs = _refresh_upload_task_runtime_options(
            task_id,
            cleanup_enabled=cleanup_enabled,
            auto_visual_toc_enabled=auto_visual_toc_enabled,
        )
        for option_log in refreshed_option_logs:
            task_push(task_id, "log", {"msg": option_log, "cls": "success"})
            all_logs.append(option_log)

        # Step 3: Optional cleanup before note scan
        if cleanup_enabled:
            task_push(task_id, "progress", {"pct": 85, "label": "清理页眉页脚…", "detail": ""})
            hf = clean_header_footer(
                parsed["pages"],
                on_progress=lambda phase, pct, detail: _push_cleanup_progress(task_id, phase, pct, detail),
            )
            final_pages = _apply_cleanup_mode_to_pages(
                hf["pages"],
                cleanup_enabled=True,
            )
            all_logs.extend(hf["log"])
            for lg in hf["log"]:
                task_push(task_id, "log", {"msg": lg})
        else:
            task_push(task_id, "progress", {
                "pct": 85,
                "label": "跳过页眉页脚清理…",
                "detail": "快速模式：直接进入脚注/尾注检测",
            })
            skip_log = "已跳过页眉页脚清理（快速模式）"
            task_push(task_id, "log", {"msg": skip_log, "cls": "success"})
            all_logs.append(skip_log)
            final_pages = _apply_cleanup_mode_to_pages(
                parsed["pages"],
                cleanup_enabled=False,
            )
        final_pages = _annotate_note_scans(final_pages)

        # Step 4: 创建文档目录并保存
        task_push(task_id, "progress", {"pct": 90, "label": "保存数据…", "detail": ""})
        doc_id = create_doc(
            file_name,
            cleanup_headers_footers=cleanup_enabled,
            auto_visual_toc_enabled=auto_visual_toc_enabled,
        )

        # 保存 PDF 副本供预览
        if file_type == 0:
            pdf_dest = os.path.join(get_doc_dir(doc_id), "source.pdf")
            try:
                import shutil
                shutil.copy2(file_path, pdf_dest)
                task_push(task_id, "log", {"msg": "PDF 已保存供预览"})
            except Exception as e:
                task_push(task_id, "log", {"msg": f"PDF保存失败: {e}"})
            toc_items = extract_pdf_toc(file_bytes)
            if not toc_items:
                toc_items = extract_pdf_toc_from_links(file_bytes)
                if toc_items:
                    task_push(task_id, "log", {"msg": f"已从目录页超链接提取目录 ({len(toc_items)} 条)", "cls": "success"})
            save_auto_pdf_toc_to_disk(doc_id, toc_items)
            if toc_items:
                task_push(task_id, "log", {"msg": f"已提取 PDF 目录 ({len(toc_items)} 条)", "cls": "success"})
            else:
                task_push(task_id, "log", {"msg": "PDF 未检测到目录书签"})
            if auto_visual_toc_enabled:
                task_push(task_id, "log", {"msg": "已启动自动视觉目录后台任务", "cls": "success"})
                start_auto_visual_toc_for_doc(doc_id, pdf_dest, model_spec=resolve_model_spec())
        else:
            save_auto_pdf_toc_to_disk(doc_id, [])

        # Step 5: Save pages data
        task_push(task_id, "progress", {"pct": 95, "label": "保存数据…", "detail": ""})
        save_pages_to_disk(final_pages, file_name, doc_id)

        first, last = get_page_range(final_pages)
        summary = f"解析完成！{len(final_pages)}页 (p.{first}-{last})"
        task_push(task_id, "done", {"summary": summary, "logs": all_logs})

    except Exception as e:
        task_push(task_id, "error_msg", {"error": f"解析失败: {e}"})
    finally:
        try:
            os.unlink(file_path)
        except OSError:
            pass


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
    try:
        fixed = structure_page(
            blocks=[],
            markdown=page_md,
            page_num=page_num,
            **request_args,
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
        t_args = get_translate_args(f"builtin:{model_key}")
        return model_key, t_args
    t_args = get_translate_args()
    resolved_model_key = t_args.get("model_key") or get_model_key()
    return resolved_model_key, t_args


def _provider_request_args(t_args: dict) -> dict:
    """从翻译状态 payload 中筛出真正传给模型 SDK 的请求字段。"""
    if not isinstance(t_args, dict):
        return {}
    request_overrides = t_args.get("request_overrides")
    return {
        "model_id": str(t_args.get("model_id", "") or "").strip(),
        "api_key": str(t_args.get("api_key", "") or "").strip(),
        "provider": str(t_args.get("provider", "deepseek") or "deepseek").strip() or "deepseek",
        "base_url": t_args.get("base_url"),
        "request_overrides": dict(request_overrides) if isinstance(request_overrides, dict) else None,
    }


def _build_note_reviewer(t_args: dict | None = None):
    request_args = _provider_request_args(t_args or get_translate_args())
    if not request_args.get("api_key") or not request_args.get("model_id"):
        return None

    def _reviewer(*, page, prev_page, next_page, rule_scan):
        prev_tail = _ensure_str((prev_page or {}).get("markdown", "")).strip()[-300:]
        next_head = _ensure_str((next_page or {}).get("markdown", "")).strip()[:300]
        return review_note_page(
            markdown=_ensure_str((page or {}).get("markdown", "")),
            footnotes=_ensure_str((page or {}).get("footnotes", "")),
            page_num=int((page or {}).get("bookPage") or 0),
            prev_context=prev_tail,
            next_context=next_head,
            rule_scan=rule_scan,
            **request_args,
        )

    return _reviewer


def _annotate_note_scans(pages: list[dict], t_args: dict | None = None, target_bps: set[int] | None = None) -> list[dict]:
    return annotate_pages_with_note_scans(
        pages,
        reviewer=_build_note_reviewer(t_args),
        target_bps=target_bps,
    )


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


TASK_KIND_CONTINUOUS = "continuous"
TASK_KIND_GLOSSARY_RETRANSLATE = "glossary_retranslate"


def _default_translate_task_meta() -> dict:
    return {
        "kind": "",
        "label": "",
        "start_bp": None,
        "start_segment_index": 0,
        "end_bp": None,
        "target_bps": [],
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
    meta["start_bp"] = int(meta.get("start_bp")) if meta.get("start_bp") is not None else None
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
    meta["affected_pages"] = max(0, int(meta.get("affected_pages", len(target_bps)) or 0))
    meta["affected_segments"] = max(0, int(meta.get("affected_segments", 0) or 0))
    meta["skipped_manual_segments"] = max(0, int(meta.get("skipped_manual_segments", 0) or 0))
    return meta


def _build_translate_task_meta(
    *,
    kind: str,
    label: str,
    start_bp: int | None,
    start_segment_index: int = 0,
    target_bps: list[int] | None = None,
    affected_segments: int = 0,
    skipped_manual_segments: int = 0,
) -> dict:
    ordered_target_bps = [int(bp) for bp in (target_bps or []) if bp is not None]
    return _normalize_translate_task_meta({
        "kind": kind,
        "label": label,
        "start_bp": start_bp,
        "start_segment_index": start_segment_index,
        "end_bp": ordered_target_bps[-1] if ordered_target_bps else None,
        "target_bps": ordered_target_bps,
        "affected_pages": len(ordered_target_bps),
        "affected_segments": affected_segments,
        "skipped_manual_segments": skipped_manual_segments,
    })


def _segment_is_manual(segment: dict | None) -> bool:
    if not isinstance(segment, dict):
        return False
    return str(segment.get("_translation_source", "") or "").strip() == "manual"


def _segment_machine_translation_text(segment: dict | None) -> str:
    if not isinstance(segment, dict):
        return ""
    machine = _ensure_str(segment.get("_machine_translation", "")).strip()
    if machine:
        return machine
    if _segment_is_manual(segment):
        return ""
    return _ensure_str(segment.get("translation", "")).strip()


def _segment_is_retranslatable_machine(segment: dict | None) -> bool:
    if not isinstance(segment, dict) or _segment_is_manual(segment):
        return False
    if str(segment.get("_status", "done") or "done").strip() == "error":
        return False
    translation = _segment_machine_translation_text(segment)
    if not translation:
        return False
    return not translation.startswith("[翻译失败:")


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

    affected_segments = 0
    skipped_manual_segments = 0
    target_bps = []
    for entry in candidate_entries:
        bp = int(entry.get("_pageBP") or 0)
        has_target = False
        for seg_idx, segment in enumerate(entry.get("_page_entries") or []):
            if bp == actual_start_bp and seg_idx < actual_start_segment_index:
                continue
            if _segment_is_manual(segment):
                skipped_manual_segments += 1
                continue
            if _segment_is_retranslatable_machine(segment):
                affected_segments += 1
                has_target = True
        if has_target:
            target_bps.append(bp)

    preview["start_bp"] = actual_start_bp
    preview["start_segment_index"] = actual_start_segment_index
    preview["end_bp"] = target_bps[-1] if target_bps else None
    preview["affected_pages"] = len(target_bps)
    preview["affected_segments"] = affected_segments
    preview["skipped_manual_segments"] = skipped_manual_segments
    preview["target_bps"] = target_bps
    preview["task"] = _build_translate_task_meta(
        kind=TASK_KIND_GLOSSARY_RETRANSLATE,
        label="词典补重译",
        start_bp=actual_start_bp,
        start_segment_index=actual_start_segment_index,
        target_bps=target_bps,
        affected_segments=affected_segments,
        skipped_manual_segments=skipped_manual_segments,
    )

    if not target_bps:
        preview["reason"] = "起始范围内没有可按词典补重译的机器译文段落。"
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
        footnotes = _ensure_str(entry.get("footnotes", "")).strip()
        footnotes_translation = _ensure_str(entry.get("footnotes_translation", "")).strip()
        if footnotes and footnotes not in seen_footnotes:
            seen_footnotes.add(footnotes)
            footnote_parts.append(footnotes)
        if footnotes_translation and footnotes_translation not in seen_translations:
            seen_translations.add(footnotes_translation)
            footnote_translation_parts.append(footnotes_translation)
    page_footnotes = "\n".join(footnote_parts).strip() or _ensure_str(fallback_footnotes).strip()
    page_footnotes_translation = "\n".join(footnote_translation_parts).strip()
    return page_footnotes, page_footnotes_translation


def _build_endnote_jobs(note_scan: dict, ctx: dict, target_bp: int) -> list[dict]:
    jobs = []
    for item in note_scan.get("items") or []:
        if str(item.get("kind", "")).strip() != "endnote":
            continue
        text = _ensure_str(item.get("text", "")).strip()
        if not text:
            continue
        section_title = _ensure_str(item.get("section_title", "")).strip()
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
            "note_marker": _ensure_str(item.get("marker", "")).strip(),
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
            "footnotes": _ensure_str(para.get("footnotes", "")).strip(),
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
    translation = f"[翻译失败: {error}]" if is_error else _ensure_str(result.get("translation", ""))
    source = str(result.get("_translation_source") or "").strip() or ("manual" if result.get("_manual_translation") else "model")
    machine_translation = _ensure_str(result.get("_machine_translation", "")).strip()
    manual_translation = _ensure_str(result.get("_manual_translation", "")).strip()
    if not is_error and source != "manual" and not machine_translation:
        machine_translation = translation
    if source == "manual" and not manual_translation and not is_error:
        manual_translation = translation
    result_footnotes = _ensure_str(result.get("footnotes", "")).strip()
    job_footnotes = _ensure_str(job.get("footnotes", "")).strip()
    footnotes = result_footnotes or job_footnotes
    footnotes_translation = _ensure_str(result.get("footnotes_translation", "")).strip()
    pages_label = str(job.get("print_page_display", "") or "").strip()
    return {
        "original": _ensure_str(result.get("original", job["text"])),
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
        "_note_kind": _ensure_str(job.get("note_kind", "")).strip(),
        "_note_marker": _ensure_str(job.get("note_marker", "")).strip(),
        "_note_number": job.get("note_number"),
        "_note_section_title": _ensure_str(job.get("note_section_title", "")).strip(),
        "_note_confidence": float(job.get("note_confidence", 0.0) or 0.0),
        "_machine_translation": machine_translation,
        "_manual_translation": manual_translation,
        "_translation_source": source,
        "_manual_updated_at": result.get("_manual_updated_at"),
        "_manual_updated_by": _ensure_str(result.get("_manual_updated_by", "")).strip(),
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

    def _do_translate(job: dict):
        return job["para_idx"], translate_paragraph(
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


def translate_page_stream(pages, target_bp, model_key, t_args, glossary, doc_id: str, stop_checker=None):
    """流式翻译指定页面：段内有界并发推送增量，但仅在整页完成后返回 entry。"""
    ctx, para_jobs, total_usage = _prepare_page_translate_jobs(pages, target_bp, t_args)

    max_parallel = _get_para_max_concurrency(model_key, len(para_jobs))
    dynamic_parallel_limit = max_parallel
    request_args = _provider_request_args(t_args)
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
            for event in stream_translate_paragraph(
                para_text=job["text"],
                para_pages=job.get("print_page_label") or str(target_bp),
                footnotes=job["footnotes"],
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
                **request_args,
            ):
                payload = {"type": event["type"], "job": job}
                payload.update({k: v for k, v in event.items() if k != "type"})
                event_queue.put(payload)
        except TranslateStreamAborted:
            event_queue.put({"type": "aborted", "job": job})
        except QuotaExceededError as e:
            event_queue.put({"type": "error", "job": job, "error": str(e), "error_kind": "quota"})
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
                paragraph_texts[para_idx] = _ensure_str(p.get("translation", ""))
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

    page_footnotes, page_footnotes_translation = _extract_page_footnote_summary(
        page_entries,
        fallback_footnotes=ctx.get("footnotes", ""),
    )

    paragraph_texts = [_ensure_str(entry.get("translation", "")) if entry else "" for entry in results]
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
        _ensure_str(job.get("note_kind", "")).strip(),
        _ensure_str(job.get("note_marker", "")).strip(),
    )


def _segment_structure_signature(segment: dict) -> tuple:
    return (
        int(segment.get("heading_level", 0) or 0),
        int(segment.get("_startBP", 0) or 0),
        int(segment.get("_endBP", 0) or 0),
        _ensure_str(segment.get("_note_kind", "")).strip(),
        _ensure_str(segment.get("_note_marker", "")).strip(),
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
        "_manual_translation": _ensure_str(segment.get("_manual_translation", "")).strip(),
        "_translation_source": segment.get("_translation_source") or ("manual" if _segment_is_manual(segment) else "model"),
        "_manual_updated_at": segment.get("_manual_updated_at"),
        "_manual_updated_by": segment.get("_manual_updated_by"),
        "updated_at": segment.get("updated_at"),
    }
    preserved = _make_page_entry(job, target_bp, result=result)
    preserved["_status"] = segment.get("_status", "done")
    preserved["_error"] = _ensure_str(segment.get("_error", "")).strip()
    return preserved


def retranslate_page_with_current_glossary(
    pages,
    target_bp: int,
    existing_entry: dict,
    model_key: str,
    t_args: dict,
    glossary: list,
    *,
    start_segment_index: int = 0,
) -> tuple[dict, dict]:
    ctx, para_jobs, total_usage = _prepare_page_translate_jobs(pages, target_bp, t_args)
    _validate_glossary_retranslate_structure(existing_entry, para_jobs, target_bp)
    existing_segments = list((existing_entry or {}).get("_page_entries") or [])
    request_args = _provider_request_args(t_args)
    results: list[dict | None] = [None] * len(para_jobs)
    target_items: list[tuple[int, dict, dict]] = []
    skipped_manual_segments = 0
    targeted_segment_indices: list[int] = []

    for idx, job in enumerate(para_jobs):
        segment = existing_segments[idx]
        if idx < max(0, int(start_segment_index or 0)):
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

_translate_task = {
    "running": False,
    "events": [],
    "stop": False,
    "doc_id": "",
}
_translate_lock = threading.Lock()


def _default_stream_draft_state() -> dict:
    return {
        "active": False,
        "bp": None,
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


def _default_translate_state(doc_id: str = "") -> dict:
    return {
        "doc_id": doc_id,
        "phase": "idle",
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
        "last_error": "",
        "failed_bps": [],
        "partial_failed_bps": [],
        "failed_pages": [],
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


def _normalize_translate_state(state: dict, assume_inactive: bool = False) -> dict:
    """统一收口磁盘快照字段，避免前端读取到自相矛盾的状态。"""
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
    draft = state.get("draft")
    if not isinstance(draft, dict):
        draft = _default_stream_draft_state()
    state["task"] = _normalize_translate_task_meta(state.get("task"))
    if not isinstance(draft.get("active_para_indices"), list):
        draft["active_para_indices"] = []
    if not isinstance(draft.get("paragraph_states"), list):
        draft["paragraph_states"] = []
    if not isinstance(draft.get("paragraph_errors"), list):
        draft["paragraph_errors"] = []
    if not isinstance(draft.get("paragraphs"), list):
        draft["paragraphs"] = []
    if not isinstance(state.get("partial_failed_bps"), list):
        state["partial_failed_bps"] = []

    if phase in ("idle", "done", "partial_failed", "stopped", "error"):
        state["running"] = False
        state["stop_requested"] = False
    if phase == "done":
        state["processed_pages"] = total_pages
        state["pending_pages"] = 0
    elif phase == "partial_failed":
        state["processed_pages"] = total_pages
        state["pending_pages"] = 0

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

    state["draft"] = draft
    state["total_tokens"] = state.get("prompt_tokens", 0) + state.get("completion_tokens", 0)
    return state


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


def _mark_translate_start_error(
    doc_id: str,
    start_bp: int,
    error_code: str,
    message: str,
    *,
    total_pages: int = 0,
    model_label: str = "",
):
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
    draft = default.get("draft")
    if not isinstance(draft, dict):
        draft = {}
    merged_draft = _default_stream_draft_state()
    merged_draft.update(draft)
    if not isinstance(merged_draft.get("active_para_indices"), list):
        merged_draft["active_para_indices"] = []
    if not isinstance(merged_draft.get("paragraph_states"), list):
        merged_draft["paragraph_states"] = []
    if not isinstance(merged_draft.get("paragraph_errors"), list):
        merged_draft["paragraph_errors"] = []
    if not isinstance(merged_draft.get("paragraphs"), list):
        merged_draft["paragraphs"] = []
    default["draft"] = merged_draft
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
    draft = _default_stream_draft_state()
    draft.update(snapshot.get("draft") or {})
    draft.update(fields)
    paragraphs = draft.get("paragraphs")
    draft["paragraphs"] = list(paragraphs) if isinstance(paragraphs, list) else []
    active_para_indices = draft.get("active_para_indices")
    draft["active_para_indices"] = list(active_para_indices) if isinstance(active_para_indices, list) else []
    paragraph_states = draft.get("paragraph_states")
    draft["paragraph_states"] = list(paragraph_states) if isinstance(paragraph_states, list) else []
    paragraph_errors = draft.get("paragraph_errors")
    draft["paragraph_errors"] = list(paragraph_errors) if isinstance(paragraph_errors, list) else []
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


def reconcile_translate_state_after_page_success(doc_id: str, bp: int):
    if not doc_id or bp is None:
        return
    _clear_failed_page_state(doc_id, bp)
    snapshot = _load_translate_state(doc_id)
    pages, _ = load_pages_from_disk(doc_id)
    target_bps = _resolve_task_target_bps(pages, snapshot)
    total_pages = len(target_bps) if target_bps else int(snapshot.get("total_pages", 0) or 0)
    entries, _, _ = load_entries_from_disk(doc_id, pages=pages)
    translated_bps = {
        int(entry.get("_pageBP"))
        for entry in entries
        if entry.get("_pageBP") is not None and (not target_bps or int(entry.get("_pageBP")) in target_bps)
    }
    partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps, entries=entries)
    done_bps = translated_bps - set(partial_failed_bps)
    done_pages = min(total_pages, len(done_bps)) if total_pages else len(done_bps)
    failed_pages = [
        page for page in snapshot.get("failed_pages", [])
        if isinstance(page, dict) and page.get("bp") is not None and (not target_bps or int(page.get("bp")) in target_bps)
    ]
    failed_bps = sorted(int(page.get("bp")) for page in failed_pages)
    processed_floor = len(set(failed_bps) | translated_bps)
    processed_pages = max(processed_floor, int(snapshot.get("processed_pages", done_pages) or 0))
    if total_pages:
        processed_pages = min(total_pages, processed_pages)
    pending_pages = _remaining_pages(total_pages, processed_pages)
    previous_phase = snapshot.get("phase", "idle")

    if snapshot.get("running", False):
        phase = "stopping" if snapshot.get("stop_requested", False) else "running"
    elif failed_bps or partial_failed_bps:
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

    next_last_error = failed_pages[0].get("error", "") if failed_pages else ""
    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        phase=phase,
        total_pages=total_pages,
        done_pages=done_pages,
        processed_pages=processed_pages,
        pending_pages=pending_pages,
        current_bp=snapshot.get("current_bp"),
        current_page_idx=snapshot.get("current_page_idx", 0),
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=snapshot.get("model", ""),
        failed_pages=failed_pages,
        failed_bps=failed_bps,
        partial_failed_bps=partial_failed_bps,
        last_error=next_last_error,
    )


def reconcile_translate_state_after_page_failure(doc_id: str, bp: int, error: str):
    if not doc_id or bp is None:
        return
    _mark_failed_page_state(doc_id, bp, error)
    snapshot = _load_translate_state(doc_id)
    pages, _ = load_pages_from_disk(doc_id)
    target_bps = _resolve_task_target_bps(pages, snapshot)
    total_pages = len(target_bps) if target_bps else int(snapshot.get("total_pages", 0) or 0)
    entries, _, _ = load_entries_from_disk(doc_id, pages=pages)
    translated_bps = {
        int(entry.get("_pageBP"))
        for entry in entries
        if entry.get("_pageBP") is not None and (not target_bps or int(entry.get("_pageBP")) in target_bps)
    }
    partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps, entries=entries)
    done_bps = translated_bps - set(partial_failed_bps)
    done_pages = min(total_pages, len(done_bps)) if total_pages else len(done_bps)
    failed_pages = [
        page for page in snapshot.get("failed_pages", [])
        if isinstance(page, dict) and page.get("bp") is not None and (not target_bps or int(page.get("bp")) in target_bps)
    ]
    failed_bps = sorted(int(page.get("bp")) for page in failed_pages)
    processed_floor = len(set(failed_bps) | translated_bps)
    processed_pages = max(processed_floor, int(snapshot.get("processed_pages", done_pages) or 0))
    if total_pages:
        processed_pages = min(total_pages, processed_pages)
    pending_pages = _remaining_pages(total_pages, processed_pages)
    previous_phase = snapshot.get("phase", "idle")

    if snapshot.get("running", False):
        phase = "stopping" if snapshot.get("stop_requested", False) else "running"
    elif pending_pages == 0 and (failed_bps or partial_failed_bps):
        phase = "partial_failed"
    elif previous_phase in ("error", "partial_failed", "stopped"):
        phase = previous_phase
    else:
        phase = "stopped"

    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        phase=phase,
        total_pages=total_pages,
        done_pages=done_pages,
        processed_pages=processed_pages,
        pending_pages=pending_pages,
        current_bp=bp,
        current_page_idx=snapshot.get("current_page_idx", 0),
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=snapshot.get("model", ""),
        failed_pages=failed_pages,
        failed_bps=failed_bps,
        partial_failed_bps=partial_failed_bps,
        last_error=str(error),
    )


def translate_push(event_type: str, data: dict):
    with _translate_lock:
        _translate_task["events"].append((event_type, data))


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
    if visible_page_view["hidden_placeholder_bps"] and target_bps:
        if entries is None:
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


def _runtime_stop_requested(doc_id: str) -> bool:
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


def start_translate_task(doc_id: str, start_bp: int, doc_title: str) -> bool:
    """启动后台翻译任务，返回是否成功启动。"""
    if not doc_id:
        return False
    with _translate_lock:
        if _translate_task["running"]:
            return False
        _translate_task["running"] = True
        _translate_task["stop"] = False
        _translate_task["events"] = []
        _translate_task["doc_id"] = doc_id

    initial_args = get_translate_args()
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
        ),
        draft=_default_stream_draft_state(),
    )

    t = threading.Thread(target=_translate_all_worker, args=(doc_id, start_bp, doc_title), daemon=True)
    t.start()
    return True


def start_glossary_retranslate_task(
    doc_id: str,
    *,
    start_bp: int | None = None,
    start_segment_index: int = 0,
    doc_title: str = "",
) -> tuple[bool, dict]:
    if not doc_id:
        return False, build_glossary_retranslate_preview(doc_id)
    preview = build_glossary_retranslate_preview(
        doc_id,
        start_bp=start_bp,
        start_segment_index=start_segment_index,
    )
    if not preview.get("ok") or not preview.get("can_start"):
        return False, preview
    with _translate_lock:
        if _translate_task["running"]:
            return False, preview
        _translate_task["running"] = True
        _translate_task["stop"] = False
        _translate_task["events"] = []
        _translate_task["doc_id"] = doc_id

    initial_args = get_translate_args()
    task_meta = _normalize_translate_task_meta(preview.get("task"))
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
    )

    t = threading.Thread(
        target=_glossary_retranslate_worker,
        args=(doc_id, task_meta, doc_title),
        daemon=True,
    )
    t.start()
    return True, preview


def _translate_all_worker(doc_id: str, start_bp: int, doc_title: str):
    """后台线程：从 start_bp 开始逐页翻译，每页完成后写入磁盘。"""
    try:
        if not doc_id or not get_doc_meta(doc_id):
            _mark_translate_start_error(doc_id, start_bp, "doc_not_found", "文档不存在或已删除")
            return

        pages, _ = load_pages_from_disk(doc_id)
        entries, _, _ = load_entries_from_disk(doc_id, pages=pages)
        model_key, t_args = _get_active_translate_args()

        if not pages:
            _mark_translate_start_error(doc_id, start_bp, "no_pages", "未找到可翻译页面")
            return

        if not t_args["api_key"]:
            _mark_translate_start_error(
                doc_id,
                start_bp,
                "no_api_key",
                "缺少翻译 API Key",
                total_pages=len(_collect_target_bps(pages, start_bp, visible_page_view=build_visible_page_view(pages))),
                model_label=t_args.get("display_label") or t_args.get("model_id") or model_key,
            )
            return

        visible_page_view = build_visible_page_view(pages)
        doc_bps = list(visible_page_view["visible_page_bps"])
        if not doc_bps:
            _mark_translate_start_error(doc_id, start_bp, "no_pages", "未找到可翻译页面")
            return
        normalized_start_bp = resolve_visible_page_bp(pages, start_bp) or doc_bps[0]
        all_bps = _collect_target_bps(pages, normalized_start_bp, visible_page_view=visible_page_view)
        task_meta = _build_translate_task_meta(
            kind=TASK_KIND_CONTINUOUS,
            label="连续翻译",
            start_bp=normalized_start_bp,
            start_segment_index=0,
            target_bps=all_bps,
        )

        doc_bp_set = set(all_bps)
        partial_failed_doc_bps = set(_collect_partial_failed_bps(doc_id, all_bps, entries=entries))
        done_bps = set()
        for e in entries:
            pbp = e.get("_pageBP")
            if pbp is not None and pbp in doc_bp_set and pbp not in partial_failed_doc_bps:
                done_bps.add(pbp)

        pending_bps = [b for b in all_bps if b not in done_bps]
        total_pages = len(all_bps)
        done_pages = len(done_bps)

        translate_push("init", {
            "total_pages": total_pages,
            "done_pages": done_pages,
            "pending_pages": len(pending_bps),
        })
        _save_translate_state(
            doc_id,
            running=True,
            stop_requested=False,
            phase="running",
            start_bp=normalized_start_bp,
            total_pages=total_pages,
            done_pages=done_pages,
            processed_pages=done_pages,
            pending_pages=_remaining_pages(total_pages, done_pages),
            current_bp=None,
            current_page_idx=done_pages,
            translated_chars=0,
            translated_paras=0,
            request_count=0,
            prompt_tokens=0,
            completion_tokens=0,
            model=t_args.get("display_label") or t_args.get("model_id") or model_key,
            model_source=t_args.get("model_source", "builtin"),
            model_key=t_args.get("model_key", ""),
            model_id=t_args.get("model_id", ""),
            provider=t_args.get("provider", ""),
            last_error="",
            failed_bps=[],
            partial_failed_bps=sorted(partial_failed_doc_bps),
            failed_pages=[],
            task=task_meta,
            draft=_default_stream_draft_state(),
        )

        for i, bp in enumerate(pending_bps):
            should_stop = _runtime_stop_requested(doc_id)
            if should_stop:
                snapshot = _load_translate_state(doc_id)
                state_total, state_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", done_pages + i),
                )
                _save_translate_state(
                    doc_id,
                    running=False,
                    stop_requested=False,
                    phase="stopped",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=snapshot.get("processed_pages", state_done),
                    pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                    current_bp=snapshot.get("current_bp"),
                    current_page_idx=snapshot.get("current_page_idx", done_pages + i),
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=snapshot.get("model", model_key),
                    last_error="",
                )
                translate_push("stopped", {"msg": "翻译已停止"})
                return

            current_page_idx = doc_bps.index(bp) + 1 if bp in doc_bps else (done_pages + i + 1)
            snapshot = _load_translate_state(doc_id)
            state_total, state_done = _clamp_page_progress(
                snapshot.get("total_pages", total_pages),
                snapshot.get("done_pages", done_pages + i),
            )
            stop_requested_now = _runtime_stop_requested(doc_id)
            if stop_requested_now:
                _save_translate_state(
                    doc_id,
                    running=False,
                    stop_requested=False,
                    phase="stopped",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=snapshot.get("processed_pages", state_done),
                    pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                    current_bp=snapshot.get("current_bp"),
                    current_page_idx=snapshot.get("current_page_idx", done_pages + i),
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=snapshot.get("model", model_key),
                    last_error="",
                )
                translate_push("stopped", {"msg": "翻译已停止"})
                return
            _save_translate_state(
                doc_id,
                running=True,
                stop_requested=stop_requested_now,
                phase="stopping" if stop_requested_now else "running",
                total_pages=state_total,
                done_pages=state_done,
                processed_pages=snapshot.get("processed_pages", state_done),
                pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                current_bp=bp,
                current_page_idx=current_page_idx,
                translated_chars=snapshot.get("translated_chars", 0),
                translated_paras=snapshot.get("translated_paras", 0),
                request_count=snapshot.get("request_count", 0),
                prompt_tokens=snapshot.get("prompt_tokens", 0),
                completion_tokens=snapshot.get("completion_tokens", 0),
                model=model_key,
                last_error="",
            )
            translate_push("page_start", {
                "bp": bp,
                "page_idx": current_page_idx,
                "total": total_pages,
            })

            try:
                model_key, t_args = _get_active_translate_args()
                glossary = get_glossary(doc_id)
                entry = translate_page_stream(
                    pages,
                    bp,
                    model_key,
                    t_args,
                    glossary,
                    doc_id=doc_id,
                    stop_checker=lambda: is_stop_requested(doc_id),
                )

                entry_idx = save_entry_to_disk(entry, doc_title, doc_id)
                _clear_failed_page_state(doc_id, bp)

                para_count = len(entry.get("_page_entries", []))
                char_count = sum(len(pe.get("translation", "")) for pe in entry.get("_page_entries", []))
                entry_usage = entry.get("_usage", {})
                snapshot = _load_translate_state(doc_id)
                state_total, snapshot_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", 0),
                )
                page_has_partial_failure = _entry_has_paragraph_error(entry)
                next_processed_pages = min(
                    state_total,
                    int(snapshot.get("processed_pages", snapshot_done) or 0) + 1,
                )
                next_done_pages = min(state_total, snapshot_done + (0 if page_has_partial_failure else 1))
                translated_chars = snapshot.get("translated_chars", 0) + char_count
                translated_paras = snapshot.get("translated_paras", 0) + para_count
                request_count = snapshot.get("request_count", 0) + int(entry_usage.get("request_count", 0) or 0)
                prompt_tokens = snapshot.get("prompt_tokens", 0) + int(entry_usage.get("prompt_tokens", 0) or 0)
                completion_tokens = snapshot.get("completion_tokens", 0) + int(entry_usage.get("completion_tokens", 0) or 0)
                partial_failed_bps = _collect_partial_failed_bps(doc_id, all_bps)

                _save_translate_state(
                    doc_id,
                    running=True,
                    stop_requested=_runtime_stop_requested(doc_id),
                    phase="stopping" if _runtime_stop_requested(doc_id) else "running",
                    total_pages=state_total,
                    done_pages=next_done_pages,
                    processed_pages=next_processed_pages,
                    pending_pages=_remaining_pages(state_total, next_processed_pages),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=translated_chars,
                    translated_paras=translated_paras,
                    request_count=request_count,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    model=model_key,
                    partial_failed_bps=partial_failed_bps,
                    last_error="",
                )
                stop_requested_now = _runtime_stop_requested(doc_id)
                if stop_requested_now:
                    stop_snapshot = _load_translate_state(doc_id)
                    stop_total, stop_done = _clamp_page_progress(
                        stop_snapshot.get("total_pages", total_pages),
                        stop_snapshot.get("done_pages", next_done_pages),
                    )
                    _save_translate_state(
                        doc_id,
                        running=False,
                        stop_requested=False,
                        phase="stopped",
                        total_pages=stop_total,
                        done_pages=stop_done,
                        processed_pages=stop_snapshot.get("processed_pages", stop_done),
                        pending_pages=_remaining_pages(stop_total, stop_snapshot.get("processed_pages", stop_done)),
                        current_bp=bp,
                        current_page_idx=current_page_idx,
                        translated_chars=stop_snapshot.get("translated_chars", translated_chars),
                        translated_paras=stop_snapshot.get("translated_paras", translated_paras),
                        request_count=stop_snapshot.get("request_count", request_count),
                        prompt_tokens=stop_snapshot.get("prompt_tokens", prompt_tokens),
                        completion_tokens=stop_snapshot.get("completion_tokens", completion_tokens),
                        model=stop_snapshot.get("model", model_key),
                        partial_failed_bps=stop_snapshot.get("partial_failed_bps", partial_failed_bps),
                        last_error="",
                    )
                    translate_push("page_done", {
                        "bp": bp,
                        "page_idx": current_page_idx,
                        "total": total_pages,
                        "entry_idx": entry_idx,
                        "para_count": para_count,
                        "char_count": char_count,
                        "usage": entry_usage,
                        "model": model_key,
                        "partial_failed": any((pe.get("_status") == "error") for pe in entry.get("_page_entries", [])),
                    })
                    translate_push("stopped", {"msg": "翻译已停止", "bp": bp})
                    return
                translate_push("page_done", {
                    "bp": bp,
                    "page_idx": current_page_idx,
                    "total": total_pages,
                    "entry_idx": entry_idx,
                    "para_count": para_count,
                    "char_count": char_count,
                    "usage": entry_usage,
                    "model": model_key,
                    "partial_failed": any((pe.get("_status") == "error") for pe in entry.get("_page_entries", [])),
                })

            except TranslateStreamAborted:
                snapshot = _load_translate_state(doc_id)
                state_total, state_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", done_pages + i),
                )
                _save_translate_state(
                    doc_id,
                    running=False,
                    stop_requested=False,
                    phase="stopped",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=snapshot.get("processed_pages", state_done),
                    pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=model_key,
                    last_error="",
                )
                translate_push("stopped", {"msg": "翻译已停止", "bp": bp})
                return
            except QuotaExceededError as e:
                snapshot = _load_translate_state(doc_id)
                state_total, state_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", done_pages + i),
                )
                _save_translate_state(
                    doc_id,
                    running=False,
                    stop_requested=False,
                    phase="error",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=snapshot.get("processed_pages", state_done),
                    pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=model_key,
                    last_error=str(e),
                )
                translate_push("error", {"msg": str(e), "bp": bp, "kind": "quota"})
                return
            except Exception as e:
                _mark_failed_page_state(doc_id, bp, str(e))
                snapshot = _load_translate_state(doc_id)
                draft = _default_stream_draft_state()
                draft.update(snapshot.get("draft") or {})
                if draft.get("bp") != bp:
                    draft = _default_stream_draft_state()
                    draft.update({
                        "bp": bp,
                        "para_total": 0,
                        "para_done": 0,
                        "paragraphs": [],
                    })
                _save_stream_draft(
                    doc_id,
                    active=False,
                    bp=bp,
                    para_idx=draft.get("para_idx"),
                    para_total=draft.get("para_total", 0),
                    para_done=draft.get("para_done", 0),
                    paragraph_errors=draft.get("paragraph_errors", []),
                    paragraphs=draft.get("paragraphs", []),
                    status="error",
                    note=f"p.{bp} 翻译失败，等待重试。",
                    last_error=str(e),
                )
                snapshot = _load_translate_state(doc_id)
                state_total, state_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", done_pages + i),
                )
                next_processed_pages = min(
                    state_total,
                    int(snapshot.get("processed_pages", state_done) or 0) + 1,
                )
                _save_translate_state(
                    doc_id,
                    running=True,
                    stop_requested=snapshot.get("stop_requested", False),
                    phase="stopping" if snapshot.get("stop_requested", False) else "running",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=next_processed_pages,
                    pending_pages=_remaining_pages(state_total, next_processed_pages),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=model_key,
                    partial_failed_bps=snapshot.get("partial_failed_bps", []),
                    last_error=str(e),
                )
                translate_push("page_error", {
                    "bp": bp,
                    "error": str(e),
                    "page_idx": current_page_idx,
                    "total": total_pages,
                })

        snapshot = _load_translate_state(doc_id)
        state_total, state_done = _clamp_page_progress(
            snapshot.get("total_pages", total_pages),
            snapshot.get("done_pages", total_pages),
        )
        final_failed_bps = [
            bp for bp in snapshot.get("failed_bps", [])
            if bp is not None
        ]
        final_partial_failed_bps = _collect_partial_failed_bps(doc_id, all_bps)
        entries, _, _ = load_entries_from_disk(doc_id)
        translated_bps = {
            int(entry.get("_pageBP"))
            for entry in entries
            if entry.get("_pageBP") is not None and int(entry.get("_pageBP")) in doc_bp_set
        }
        final_done_pages = min(state_total, len(translated_bps - set(final_partial_failed_bps))) if state_total else len(translated_bps - set(final_partial_failed_bps))
        final_phase = "partial_failed" if (final_failed_bps or final_partial_failed_bps) else "done"
        _save_translate_state(
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
            model=snapshot.get("model", model_key),
            partial_failed_bps=final_partial_failed_bps,
            last_error=snapshot.get("last_error", ""),
        )
        translate_push("all_done", {
            "total_pages": total_pages,
            "total_entries": len(entries),
        })

    except Exception as e:
        snapshot = _load_translate_state(doc_id)
        state_total, state_done = _clamp_page_progress(
            snapshot.get("total_pages", 0),
            snapshot.get("done_pages", 0),
        )
        _save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="error",
            total_pages=state_total,
            done_pages=state_done,
            processed_pages=snapshot.get("processed_pages", state_done),
            pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
            current_bp=snapshot.get("current_bp"),
            current_page_idx=snapshot.get("current_page_idx", 0),
            translated_chars=snapshot.get("translated_chars", 0),
            translated_paras=snapshot.get("translated_paras", 0),
            request_count=snapshot.get("request_count", 0),
            prompt_tokens=snapshot.get("prompt_tokens", 0),
            completion_tokens=snapshot.get("completion_tokens", 0),
            model=snapshot.get("model", ""),
            last_error=str(e),
        )
        translate_push("error", {"msg": str(e)})
    finally:
        with _translate_lock:
            _translate_task["running"] = False
            _translate_task["stop"] = False
            _translate_task["doc_id"] = ""


def _glossary_retranslate_worker(doc_id: str, task_meta: dict, doc_title: str):
    task_meta = _normalize_translate_task_meta(task_meta)
    target_bps = list(task_meta.get("target_bps") or [])
    total_pages = len(target_bps)
    try:
        if not doc_id or not get_doc_meta(doc_id):
            _mark_translate_start_error(doc_id, task_meta.get("start_bp"), "doc_not_found", "文档不存在或已删除")
            return

        pages, _ = load_pages_from_disk(doc_id)
        entries, _, _ = load_entries_from_disk(doc_id, pages=pages)
        entry_by_bp = {
            int(entry.get("_pageBP")): entry
            for entry in entries
            if entry.get("_pageBP") is not None
        }
        model_key, t_args = _get_active_translate_args()

        if not pages:
            _mark_translate_start_error(doc_id, task_meta.get("start_bp"), "no_pages", "未找到可翻译页面")
            return
        if not t_args["api_key"]:
            _mark_translate_start_error(
                doc_id,
                task_meta.get("start_bp"),
                "no_api_key",
                "缺少翻译 API Key",
                total_pages=total_pages,
                model_label=t_args.get("display_label") or t_args.get("model_id") or model_key,
            )
            return
        if not target_bps:
            _mark_translate_start_error(
                doc_id,
                task_meta.get("start_bp"),
                "no_retranslate_range",
                "当前范围内没有可按词典补重译的机器译文段落。",
                total_pages=0,
                model_label=t_args.get("display_label") or t_args.get("model_id") or model_key,
            )
            return

        translate_push("init", {
            "total_pages": total_pages,
            "done_pages": 0,
            "pending_pages": total_pages,
        })
        _save_translate_state(
            doc_id,
            running=True,
            stop_requested=False,
            phase="running",
            start_bp=task_meta.get("start_bp"),
            total_pages=total_pages,
            done_pages=0,
            processed_pages=0,
            pending_pages=total_pages,
            current_bp=None,
            current_page_idx=0,
            translated_chars=0,
            translated_paras=0,
            request_count=0,
            prompt_tokens=0,
            completion_tokens=0,
            model=t_args.get("display_label") or t_args.get("model_id") or model_key,
            model_source=t_args.get("model_source", "builtin"),
            model_key=t_args.get("model_key", ""),
            model_id=t_args.get("model_id", ""),
            provider=t_args.get("provider", ""),
            last_error="",
            failed_bps=[],
            partial_failed_bps=[],
            failed_pages=[],
            task=task_meta,
            draft=_default_stream_draft_state(),
        )

        for i, bp in enumerate(target_bps):
            if _runtime_stop_requested(doc_id):
                snapshot = _load_translate_state(doc_id)
                state_total, state_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", i),
                )
                _save_translate_state(
                    doc_id,
                    running=False,
                    stop_requested=False,
                    phase="stopped",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=snapshot.get("processed_pages", state_done),
                    pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                    current_bp=snapshot.get("current_bp"),
                    current_page_idx=snapshot.get("current_page_idx", i),
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=snapshot.get("model", model_key),
                    task=task_meta,
                    last_error="",
                )
                translate_push("stopped", {"msg": "翻译已停止"})
                return

            current_page_idx = i + 1
            snapshot = _load_translate_state(doc_id)
            state_total, state_done = _clamp_page_progress(
                snapshot.get("total_pages", total_pages),
                snapshot.get("done_pages", i),
            )
            stop_requested_now = _runtime_stop_requested(doc_id)
            _save_translate_state(
                doc_id,
                running=True,
                stop_requested=stop_requested_now,
                phase="stopping" if stop_requested_now else "running",
                total_pages=state_total,
                done_pages=state_done,
                processed_pages=snapshot.get("processed_pages", state_done),
                pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                current_bp=bp,
                current_page_idx=current_page_idx,
                translated_chars=snapshot.get("translated_chars", 0),
                translated_paras=snapshot.get("translated_paras", 0),
                request_count=snapshot.get("request_count", 0),
                prompt_tokens=snapshot.get("prompt_tokens", 0),
                completion_tokens=snapshot.get("completion_tokens", 0),
                model=model_key,
                task=task_meta,
                last_error="",
            )
            translate_push("page_start", {
                "bp": bp,
                "page_idx": current_page_idx,
                "total": total_pages,
            })

            try:
                model_key, t_args = _get_active_translate_args()
                glossary = get_glossary(doc_id)
                existing_entry = entry_by_bp.get(int(bp))
                if not existing_entry:
                    raise RuntimeError(f"第{bp}页尚未有已译内容，无法按词典补重译。")
                page_start_segment_index = task_meta.get("start_segment_index", 0) if int(bp) == int(task_meta.get("start_bp") or 0) else 0
                entry, page_stats = retranslate_page_with_current_glossary(
                    pages,
                    int(bp),
                    existing_entry,
                    model_key,
                    t_args,
                    glossary,
                    start_segment_index=page_start_segment_index,
                )

                entry_idx = save_entry_to_disk(entry, doc_title, doc_id)
                entry_by_bp[int(bp)] = entry
                _clear_failed_page_state(doc_id, int(bp))

                targeted_indices = set(page_stats.get("targeted_segment_indices") or [])
                para_count = len(targeted_indices)
                char_count = sum(
                    len(_ensure_str(entry.get("_page_entries", [])[idx].get("translation", "")))
                    for idx in targeted_indices
                    if idx < len(entry.get("_page_entries", []))
                )
                entry_usage = entry.get("_usage", {})
                snapshot = _load_translate_state(doc_id)
                state_total, snapshot_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", 0),
                )
                page_has_partial_failure = _entry_has_paragraph_error(entry)
                next_processed_pages = min(
                    state_total,
                    int(snapshot.get("processed_pages", snapshot_done) or 0) + 1,
                )
                next_done_pages = min(state_total, snapshot_done + (0 if page_has_partial_failure else 1))
                translated_chars = snapshot.get("translated_chars", 0) + char_count
                translated_paras = snapshot.get("translated_paras", 0) + para_count
                request_count = snapshot.get("request_count", 0) + int(entry_usage.get("request_count", 0) or 0)
                prompt_tokens = snapshot.get("prompt_tokens", 0) + int(entry_usage.get("prompt_tokens", 0) or 0)
                completion_tokens = snapshot.get("completion_tokens", 0) + int(entry_usage.get("completion_tokens", 0) or 0)
                partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps)

                _save_translate_state(
                    doc_id,
                    running=True,
                    stop_requested=_runtime_stop_requested(doc_id),
                    phase="stopping" if _runtime_stop_requested(doc_id) else "running",
                    total_pages=state_total,
                    done_pages=next_done_pages,
                    processed_pages=next_processed_pages,
                    pending_pages=_remaining_pages(state_total, next_processed_pages),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=translated_chars,
                    translated_paras=translated_paras,
                    request_count=request_count,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    model=model_key,
                    partial_failed_bps=partial_failed_bps,
                    task=task_meta,
                    last_error="",
                )
                stop_requested_now = _runtime_stop_requested(doc_id)
                if stop_requested_now:
                    stop_snapshot = _load_translate_state(doc_id)
                    stop_total, stop_done = _clamp_page_progress(
                        stop_snapshot.get("total_pages", total_pages),
                        stop_snapshot.get("done_pages", next_done_pages),
                    )
                    _save_translate_state(
                        doc_id,
                        running=False,
                        stop_requested=False,
                        phase="stopped",
                        total_pages=stop_total,
                        done_pages=stop_done,
                        processed_pages=stop_snapshot.get("processed_pages", stop_done),
                        pending_pages=_remaining_pages(stop_total, stop_snapshot.get("processed_pages", stop_done)),
                        current_bp=bp,
                        current_page_idx=current_page_idx,
                        translated_chars=stop_snapshot.get("translated_chars", translated_chars),
                        translated_paras=stop_snapshot.get("translated_paras", translated_paras),
                        request_count=stop_snapshot.get("request_count", request_count),
                        prompt_tokens=stop_snapshot.get("prompt_tokens", prompt_tokens),
                        completion_tokens=stop_snapshot.get("completion_tokens", completion_tokens),
                        model=stop_snapshot.get("model", model_key),
                        partial_failed_bps=stop_snapshot.get("partial_failed_bps", partial_failed_bps),
                        task=task_meta,
                        last_error="",
                    )
                    translate_push("page_done", {
                        "bp": bp,
                        "page_idx": current_page_idx,
                        "total": total_pages,
                        "entry_idx": entry_idx,
                        "para_count": para_count,
                        "char_count": char_count,
                        "usage": entry_usage,
                        "model": model_key,
                        "partial_failed": page_has_partial_failure,
                    })
                    translate_push("stopped", {"msg": "翻译已停止", "bp": bp})
                    return
                translate_push("page_done", {
                    "bp": bp,
                    "page_idx": current_page_idx,
                    "total": total_pages,
                    "entry_idx": entry_idx,
                    "para_count": para_count,
                    "char_count": char_count,
                    "usage": entry_usage,
                    "model": model_key,
                    "partial_failed": page_has_partial_failure,
                })
            except QuotaExceededError as exc:
                snapshot = _load_translate_state(doc_id)
                state_total, state_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", i),
                )
                _save_translate_state(
                    doc_id,
                    running=False,
                    stop_requested=False,
                    phase="error",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=snapshot.get("processed_pages", state_done),
                    pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=model_key,
                    task=task_meta,
                    last_error=str(exc),
                )
                translate_push("error", {"msg": str(exc), "bp": bp, "kind": "quota"})
                return
            except Exception as exc:
                _mark_failed_page_state(doc_id, bp, str(exc))
                snapshot = _load_translate_state(doc_id)
                state_total, state_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", i),
                )
                next_processed_pages = min(
                    state_total,
                    int(snapshot.get("processed_pages", state_done) or 0) + 1,
                )
                _save_translate_state(
                    doc_id,
                    running=True,
                    stop_requested=snapshot.get("stop_requested", False),
                    phase="stopping" if snapshot.get("stop_requested", False) else "running",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=next_processed_pages,
                    pending_pages=_remaining_pages(state_total, next_processed_pages),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=model_key,
                    partial_failed_bps=snapshot.get("partial_failed_bps", []),
                    task=task_meta,
                    last_error=str(exc),
                )
                translate_push("page_error", {
                    "bp": bp,
                    "error": str(exc),
                    "page_idx": current_page_idx,
                    "total": total_pages,
                })

        snapshot = _load_translate_state(doc_id)
        state_total, _state_done = _clamp_page_progress(
            snapshot.get("total_pages", total_pages),
            snapshot.get("done_pages", total_pages),
        )
        final_failed_bps = [bp for bp in snapshot.get("failed_bps", []) if bp is not None]
        final_partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps)
        entries, _, _ = load_entries_from_disk(doc_id)
        target_bp_set = set(target_bps)
        translated_bps = {
            int(entry.get("_pageBP"))
            for entry in entries
            if entry.get("_pageBP") is not None and int(entry.get("_pageBP")) in target_bp_set
        }
        final_done_pages = min(state_total, len(translated_bps - set(final_partial_failed_bps))) if state_total else len(translated_bps - set(final_partial_failed_bps))
        final_phase = "partial_failed" if (final_failed_bps or final_partial_failed_bps) else "done"
        _save_translate_state(
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
            model=snapshot.get("model", model_key),
            partial_failed_bps=final_partial_failed_bps,
            task=task_meta,
            last_error=snapshot.get("last_error", ""),
        )
        translate_push("all_done", {
            "total_pages": total_pages,
            "total_entries": len(entries),
        })
    except Exception as exc:
        snapshot = _load_translate_state(doc_id)
        state_total, state_done = _clamp_page_progress(
            snapshot.get("total_pages", 0),
            snapshot.get("done_pages", 0),
        )
        _save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="error",
            total_pages=state_total,
            done_pages=state_done,
            processed_pages=snapshot.get("processed_pages", state_done),
            pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
            current_bp=snapshot.get("current_bp"),
            current_page_idx=snapshot.get("current_page_idx", 0),
            translated_chars=snapshot.get("translated_chars", 0),
            translated_paras=snapshot.get("translated_paras", 0),
            request_count=snapshot.get("request_count", 0),
            prompt_tokens=snapshot.get("prompt_tokens", 0),
            completion_tokens=snapshot.get("completion_tokens", 0),
            model=snapshot.get("model", ""),
            task=task_meta,
            last_error=str(exc),
        )
        translate_push("error", {"msg": str(exc)})
    finally:
        with _translate_lock:
            _translate_task["running"] = False
            _translate_task["stop"] = False
            _translate_task["doc_id"] = ""


# ============ 重新解析 ============

def reparse_file(task_id: str, doc_id: str):
    """后台线程：对已有文档重新执行 OCR 解析（保留翻译数据）。"""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return

    paddle_token = get_paddle_token()
    cleanup_enabled = _resolve_cleanup_headers_footers(task, doc_id=doc_id)
    auto_visual_toc_enabled = _resolve_auto_visual_toc(task, doc_id=doc_id)
    pdf_path = task["file_path"]
    file_name = task["file_name"]

    try:
        with open(pdf_path, "rb") as f:
            file_bytes = f.read()

        all_logs = []

        # Step 1: OCR
        task_push(task_id, "progress", {"pct": 5, "label": "重新调用 PaddleOCR…", "detail": ""})

        def on_ocr_progress(chunk_i, total_chunks):
            pct = 5 + (chunk_i / total_chunks) * 60
            task_push(task_id, "progress", {
                "pct": pct,
                "label": f"OCR 解析中… ({chunk_i}/{total_chunks})",
                "detail": f"分片 {chunk_i}/{total_chunks}",
            })

        result = call_paddle_ocr_bytes(
            file_bytes=file_bytes,
            token=paddle_token,
            file_type=0,
            on_progress=on_ocr_progress,
        )

        task_push(task_id, "progress", {"pct": 65, "label": "解析 OCR 结果…", "detail": ""})
        parsed = parse_ocr(result)
        if not parsed["pages"]:
            task_push(task_id, "error_msg", {"error": "重新解析失败：未获取到页面数据"})
            return
        all_logs.extend(parsed["log"])

        # Step 2: PDF text extraction（带污染检测）
        task_push(task_id, "progress", {"pct": 72, "label": "提取 PDF 文字层…", "detail": ""})
        pdf_pages = extract_pdf_text(file_bytes)
        if pdf_pages:
            task_push(task_id, "log", {"msg": f"检测到有效PDF文字层 ({len(pdf_pages)}页)", "cls": "success"})
            combined = combine_sources(parsed["pages"], pdf_pages)
            parsed["pages"] = combined["pages"]
            all_logs.extend(combined["log"])
        else:
            task_push(task_id, "log", {"msg": "PDF无有效文字层（或文字层已损坏），使用OCR文字"})
            all_logs.append("PDF无有效文字层，使用OCR文字")

        # Step 3: Optional cleanup before note scan
        if cleanup_enabled:
            task_push(task_id, "progress", {"pct": 85, "label": "清理页眉页脚…", "detail": ""})
            hf = clean_header_footer(
                parsed["pages"],
                on_progress=lambda phase, pct, detail: _push_cleanup_progress(task_id, phase, pct, detail),
            )
            final_pages = _apply_cleanup_mode_to_pages(
                hf["pages"],
                cleanup_enabled=True,
            )
            all_logs.extend(hf["log"])
        else:
            task_push(task_id, "progress", {
                "pct": 85,
                "label": "跳过页眉页脚清理…",
                "detail": "快速模式：直接进入脚注/尾注检测",
            })
            skip_log = "已跳过页眉页脚清理（快速模式）"
            task_push(task_id, "log", {"msg": skip_log, "cls": "success"})
            all_logs.append(skip_log)
            final_pages = _apply_cleanup_mode_to_pages(
                parsed["pages"],
                cleanup_enabled=False,
            )
        final_pages = _annotate_note_scans(final_pages)

        # Step 4: 保存页面数据（SQLite 主写入）
        task_push(task_id, "progress", {"pct": 95, "label": "保存数据…", "detail": ""})
        save_pages_to_disk(final_pages, file_name, doc_id)
        _toc = extract_pdf_toc(file_bytes) or extract_pdf_toc_from_links(file_bytes)
        save_auto_pdf_toc_to_disk(doc_id, _toc)
        if auto_visual_toc_enabled:
            pdf_path = os.path.join(get_doc_dir(doc_id), "source.pdf")
            start_auto_visual_toc_for_doc(doc_id, pdf_path, model_spec=resolve_model_spec())

        first, last = get_page_range(final_pages)
        summary = f"重新解析完成！{len(final_pages)}页 (p.{first}-{last})"
        task_push(task_id, "done", {"summary": summary, "logs": all_logs})

    except Exception as e:
        task_push(task_id, "error_msg", {"error": f"重新解析失败: {e}"})


def reparse_single_page(task_id: str, doc_id: str, target_bp: int, file_idx: int):
    """后台线程：对单页重新执行 OCR 解析（保留翻译数据）。"""
    from pdf_extract import extract_single_page_pdf

    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return

    paddle_token = get_paddle_token()
    pdf_path = task["file_path"]
    file_name = task["file_name"]
    cleanup_enabled = _resolve_cleanup_headers_footers(task, doc_id=doc_id)

    try:
        # 提取单页PDF
        task_push(task_id, "progress", {"pct": 5, "label": f"提取第 {target_bp} 页…", "detail": ""})
        single_page_bytes = extract_single_page_pdf(pdf_path, file_idx)
        if not single_page_bytes:
            task_push(task_id, "error_msg", {"error": f"无法提取第 {target_bp} 页"})
            return

        # 调用 PaddleOCR
        task_push(task_id, "progress", {"pct": 30, "label": "调用 PaddleOCR 解析…", "detail": ""})
        result = call_paddle_ocr_bytes(
            file_bytes=single_page_bytes,
            token=paddle_token,
            file_type=0,  # PDF
        )

        task_push(task_id, "progress", {"pct": 65, "label": "解析 OCR 结果…", "detail": ""})
        parsed = parse_ocr(result)
        if not parsed["pages"]:
            task_push(task_id, "error_msg", {"error": "OCR 未返回页面数据"})
            return

        # 单页结果
        new_page = parsed["pages"][0]
        new_page["bookPage"] = target_bp
        new_page["fileIdx"] = file_idx

        # 单页手动重解析固定走 OCR 文本，避免坏掉的 PDF 文字层再次覆盖版面文本。
        task_push(task_id, "progress", {
            "pct": 75,
            "label": "保留 OCR 文字…",
            "detail": "手动重解析会跳过 PDF 文字层",
        })
        task_push(task_id, "log", {
            "msg": "手动重解析模式：跳过 PDF 文字层，强制使用 OCR 文字",
            "cls": "success",
        })
        new_page["textSource"] = "ocr"

        # 清理页眉页脚（按文档模式决定是否跳过）
        if cleanup_enabled:
            task_push(task_id, "progress", {"pct": 85, "label": "清理页眉页脚…", "detail": ""})
            hf = clean_header_footer(
                [new_page],
                on_progress=lambda phase, pct, detail: _push_cleanup_progress(task_id, phase, pct, detail, start_pct=85, end_pct=92),
            )
            new_page = _apply_cleanup_mode_to_pages(
                hf["pages"],
                cleanup_enabled=True,
            )[0]
        else:
            task_push(task_id, "progress", {
                "pct": 85,
                "label": "跳过页眉页脚清理…",
                "detail": "快速模式：直接进入脚注/尾注检测",
            })
            task_push(task_id, "log", {"msg": "已跳过页眉页脚清理（快速模式）", "cls": "success"})
            new_page = _apply_cleanup_mode_to_pages(
                [new_page],
                cleanup_enabled=False,
            )[0]

        # 读取现有页面数据并更新
        task_push(task_id, "progress", {"pct": 95, "label": "保存数据…", "detail": ""})
        existing_pages, _ = load_pages_from_disk(doc_id)
        updated_pages = []
        for p in existing_pages:
            if p["bookPage"] == target_bp:
                updated_pages.append(new_page)
            else:
                updated_pages.append(p)
        updated_pages = _annotate_note_scans(
            updated_pages,
            target_bps={max(1, target_bp - 1), target_bp, target_bp + 1},
        )

        save_pages_to_disk(updated_pages, file_name, doc_id)
        entries, doc_title, _ = load_entries_from_disk(doc_id, pages=updated_pages)
        entry_title = doc_title or file_name

        try:
            model_key = ""
            for entry in entries:
                if entry.get("_pageBP") == target_bp and entry.get("_model") in MODELS:
                    model_key = entry.get("_model")
                    break
            model_key, t_args = _get_active_translate_args(model_key)
            if not t_args["api_key"]:
                raise RuntimeError("缺少翻译 API Key，请先在设置中配置。")

            model_label = MODELS.get(model_key, {}).get("label", model_key)
            task_push(task_id, "progress", {
                "pct": 97,
                "label": "自动重译本页…",
                "detail": f"使用 {model_label}",
            })
            task_push(task_id, "log", {
                "msg": f"开始自动重译第 {target_bp} 页（{model_label}）",
                "cls": "success",
            })
            new_entry = translate_page(updated_pages, target_bp, model_key, t_args, get_glossary(doc_id))
            save_entry_to_disk(new_entry, entry_title, doc_id)
            reconcile_translate_state_after_page_success(doc_id, target_bp)
        except Exception as e:
            reconcile_translate_state_after_page_failure(doc_id, target_bp, str(e))
            task_push(task_id, "error_msg", {"error": f"第 {target_bp} 页 OCR 重解析已完成，但自动重译失败: {e}"})
            return

        summary = f"第 {target_bp} 页 OCR 重解析并重译完成"
        task_push(task_id, "done", {"summary": summary, "bp": target_bp})

    except Exception as e:
        task_push(task_id, "error_msg", {"error": f"重新解析失败: {e}"})

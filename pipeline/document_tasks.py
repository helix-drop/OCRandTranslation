"""文档级 OCR/重解析后台入口。"""

from __future__ import annotations

import logging
import os
import threading
import time

import config as app_config
import document.text_processing as text_processing
import persistence.storage as storage
import persistence.task_logs as task_logs
import pipeline.task_registry as task_registry
import translation.service as translation_service
from config import (
    MODELS,
    create_doc,
    get_doc_auto_visual_toc_enabled,
    get_doc_cleanup_headers_footers,
    get_doc_dir,
    get_glossary,
    get_model_key,
    get_paddle_token,
    get_upload_auto_visual_toc_enabled,
    get_upload_cleanup_headers_footers_enabled,
)
from document.note_detection import annotate_pages_with_note_scans
from document.pdf_extract import extract_pdf_toc, extract_pdf_toc_from_links
from document.text_utils import ensure_str
from ocr_client import call_paddle_ocr_bytes
from pipeline.task_document_pipeline import (
    process_file as _process_file_impl,
    reparse_file as _reparse_file_impl,
    reparse_single_page as _reparse_single_page_impl,
)
from pipeline.visual_toc import generate_auto_visual_toc_for_doc
from translation.translate_progress import (
    reconcile_translate_state_after_page_failure,
    reconcile_translate_state_after_page_success,
)
from translation.translator import review_note_page


logger = logging.getLogger(__name__)


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
        logs.append("检测到上传后的页眉页脚清理选项已更新，后续将按最新选择继续处理。")
    if refreshed_auto_visual != auto_visual_toc_enabled:
        logs.append("检测到上传后的自动视觉目录前置要求已更新，后续将按最新选择继续处理。")
    task_registry.update_task_options(
        task_id,
        clean_header_footer=refreshed_cleanup,
        auto_visual_toc=refreshed_auto_visual,
    )
    return refreshed_cleanup, refreshed_auto_visual, logs


def start_auto_visual_toc_for_doc(doc_id: str, pdf_path: str, model_spec=None):
    if not doc_id or not pdf_path or not os.path.exists(pdf_path):
        return None

    def _runner():
        generate_auto_visual_toc_for_doc(doc_id, pdf_path=pdf_path, model_spec=model_spec)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return thread


def run_auto_visual_toc_for_doc(doc_id: str, pdf_path: str, model_spec=None) -> dict:
    if not doc_id or not pdf_path or not os.path.exists(pdf_path):
        return {"status": "failed", "count": 0, "message": "未找到源 PDF，无法生成自动视觉目录。"}
    return generate_auto_visual_toc_for_doc(doc_id, pdf_path=pdf_path, model_spec=model_spec)


def _push_cleanup_progress(task_id: str, phase: str, pct: int, detail: str, *, start_pct: int = 85, end_pct: int = 90):
    local_pct = max(0, min(100, int(pct or 0)))
    total_pct = start_pct + ((end_pct - start_pct) * local_pct / 100.0)
    label_map = {
        "collect_candidates": "收集页眉/页脚候选…",
        "detect_patterns": "统计重复模式…",
        "apply_cleanup": "正在应用页眉页脚清理…",
        "note_scan_ready": "进入脚注/尾注检测…",
    }
    task_registry.task_push(task_id, "progress", {
        "pct": total_pct,
        "label": label_map.get(phase, "清理页眉页脚…"),
        "detail": detail or "",
    })


def _get_active_translate_args(model_key: str | None = None) -> tuple[str, dict]:
    if model_key and model_key in MODELS:
        t_args = storage.get_translate_args(f"builtin:{model_key}")
        return model_key, t_args
    t_args = storage.get_translate_args()
    resolved_model_key = t_args.get("model_key") or get_model_key()
    return resolved_model_key, t_args


def _build_note_reviewer(t_args: dict | None = None):
    resolved_args = dict(t_args or storage.get_translate_args())
    call_kwargs = {
        "model_id": str(resolved_args.get("model_id", "") or "").strip(),
        "api_key": str(resolved_args.get("api_key", "") or "").strip(),
        "provider": str(resolved_args.get("provider", "deepseek") or "deepseek").strip() or "deepseek",
        "base_url": resolved_args.get("base_url"),
        "request_overrides": dict(resolved_args.get("request_overrides") or {}) if isinstance(resolved_args.get("request_overrides"), dict) else None,
    }
    if not call_kwargs.get("api_key") or not call_kwargs.get("model_id"):
        return None

    def _reviewer(*, page, prev_page, next_page, rule_scan):
        prev_tail = ensure_str((prev_page or {}).get("markdown", "")).strip()[-300:]
        next_head = ensure_str((next_page or {}).get("markdown", "")).strip()[:300]
        return review_note_page(
            markdown=ensure_str((page or {}).get("markdown", "")),
            footnotes=ensure_str((page or {}).get("footnotes", "")),
            page_num=int((page or {}).get("bookPage") or 0),
            prev_context=prev_tail,
            next_context=next_head,
            rule_scan=rule_scan,
            **call_kwargs,
        )

    return _reviewer


def _annotate_note_scans(
    pages: list[dict],
    t_args: dict | None = None,
    target_bps: set[int] | None = None,
) -> list[dict]:
    return annotate_pages_with_note_scans(
        pages,
        reviewer=_build_note_reviewer(t_args),
        target_bps=target_bps,
    )


def _create_doc_task_log(doc_id: str, task_kind: str, *, task_id: str) -> str:
    return task_logs.create_doc_task_log(
        doc_id,
        task_kind,
        task_id=task_id,
        started_at=time.time(),
    )


def _append_doc_task_log(doc_id: str, log_relpath: str, message: str, *, level: str = "INFO") -> str:
    return task_logs.append_doc_task_log(
        doc_id,
        log_relpath,
        message,
        level=level,
    )


def _document_pipeline_deps() -> dict:
    return {
        "MODELS": MODELS,
        "annotate_note_scans": _annotate_note_scans,
        "append_doc_task_log": _append_doc_task_log,
        "apply_cleanup_mode_to_pages": _apply_cleanup_mode_to_pages,
        "build_visible_page_view": text_processing.build_visible_page_view,
        "call_paddle_ocr_bytes": call_paddle_ocr_bytes,
        "clean_header_footer": text_processing.clean_header_footer,
        "combine_sources": text_processing.combine_sources,
        "create_doc": create_doc,
        "create_doc_task_log": _create_doc_task_log,
        "extract_pdf_text": text_processing.extract_pdf_text,
        "extract_pdf_toc": extract_pdf_toc,
        "extract_pdf_toc_from_links": extract_pdf_toc_from_links,
        "get_active_translate_args": _get_active_translate_args,
        "get_doc_dir": get_doc_dir,
        "get_glossary": get_glossary,
        "get_page_range": text_processing.get_page_range,
        "get_paddle_token": get_paddle_token,
        "get_task_record": task_registry.get_task,
        "load_entries_from_disk": storage.load_entries_from_disk,
        "load_pages_from_disk": storage.load_pages_from_disk,
        "parse_ocr": text_processing.parse_ocr,
        "parse_glossary_file": app_config.parse_glossary_file,
        "push_cleanup_progress": _push_cleanup_progress,
        "reconcile_translate_state_after_page_failure": reconcile_translate_state_after_page_failure,
        "reconcile_translate_state_after_page_success": reconcile_translate_state_after_page_success,
        "refresh_upload_task_runtime_options": _refresh_upload_task_runtime_options,
        "resolve_auto_visual_toc": _resolve_auto_visual_toc,
        "resolve_cleanup_headers_footers": _resolve_cleanup_headers_footers,
        "resolve_visual_model_spec": storage.resolve_visual_model_spec,
        "run_auto_visual_toc_for_doc": run_auto_visual_toc_for_doc,
        "save_auto_pdf_toc_to_disk": storage.save_auto_pdf_toc_to_disk,
        "save_entry_to_disk": storage.save_entry_to_disk,
        "save_pages_to_disk": storage.save_pages_to_disk,
        "set_glossary": app_config.set_glossary,
        "save_toc_visual_manual_pdf": storage.save_toc_visual_manual_pdf,
        "save_toc_visual_manual_screenshots": storage.save_toc_visual_manual_screenshots,
        "start_auto_visual_toc_for_doc": start_auto_visual_toc_for_doc,
        "task_push": task_registry.task_push,
        "translate_page": translation_service.translate_page,
        "update_doc_meta": app_config.update_doc_meta,
    }


def process_file(task_id: str):
    return _process_file_impl(task_id, _document_pipeline_deps())


def reparse_file(task_id: str, doc_id: str):
    return _reparse_file_impl(task_id, doc_id, _document_pipeline_deps())


def reparse_single_page(task_id: str, doc_id: str, target_bp: int, file_idx: int):
    return _reparse_single_page_impl(
        task_id,
        doc_id,
        target_bp,
        file_idx,
        _document_pipeline_deps(),
    )


__all__ = [
    "process_file",
    "reparse_file",
    "reparse_single_page",
    "run_auto_visual_toc_for_doc",
    "start_auto_visual_toc_for_doc",
]

"""连续翻译 worker 业务逻辑。"""
import logging

from translation.translate_state import TASK_KIND_CONTINUOUS, _build_translate_task_meta
from translation.translate_worker_common import run_translate_worker

logger = logging.getLogger(__name__)


def _model_label(model_key: str, t_args: dict) -> str:
    return t_args.get("display_label") or t_args.get("model_id") or model_key


def run_translate_all_worker(doc_id: str, start_bp: int, doc_title: str, deps: dict):
    def build_plan():
        if not doc_id or not deps["get_doc_meta"](doc_id):
            return {
                "start_error": {
                    "start_bp": start_bp,
                    "error_code": "doc_not_found",
                    "message": "文档不存在或已删除",
                }
            }

        pages, _ = deps["load_pages_from_disk"](doc_id)
        entries, _, _ = deps["load_entries_from_disk"](doc_id, pages=pages)
        model_key, t_args = deps["get_active_translate_args"]()

        if not pages:
            return {
                "start_error": {
                    "start_bp": start_bp,
                    "error_code": "no_pages",
                    "message": "未找到可翻译页面",
                }
            }

        visible_page_view = deps["build_visible_page_view"](pages)
        doc_bps = list(visible_page_view.get("visible_page_bps") or [])
        if not doc_bps:
            return {
                "start_error": {
                    "start_bp": start_bp,
                    "error_code": "no_pages",
                    "message": "未找到可翻译页面",
                }
            }

        normalized_start_bp = deps["resolve_visible_page_bp"](pages, start_bp) or doc_bps[0]
        target_bps = deps["collect_target_bps"](
            pages,
            normalized_start_bp,
            visible_page_view=visible_page_view,
        )
        if not t_args.get("api_key"):
            return {
                "start_error": {
                    "start_bp": start_bp,
                    "error_code": "no_api_key",
                    "message": "缺少翻译 API Key",
                    "total_pages": len(target_bps),
                    "model_label": _model_label(model_key, t_args),
                }
            }

        partial_failed_bps = deps["collect_partial_failed_bps"](doc_id, target_bps, entries=entries)
        target_bp_set = set(target_bps)
        partial_failed_set = set(partial_failed_bps)
        done_bps = {
            int(entry.get("_pageBP"))
            for entry in entries
            if entry.get("_pageBP") is not None
            and int(entry.get("_pageBP")) in target_bp_set
            and int(entry.get("_pageBP")) not in partial_failed_set
        }
        page_idx_by_bp = {int(bp): idx + 1 for idx, bp in enumerate(doc_bps)}
        task_meta = _build_translate_task_meta(
            kind=TASK_KIND_CONTINUOUS,
            label="连续翻译",
            start_bp=normalized_start_bp,
            start_segment_index=0,
            target_bps=target_bps,
        )
        return {
            "worker_plan": {
                "start_bp": normalized_start_bp,
                "target_bps": target_bps,
                "total_pages": len(target_bps),
                "initial_done_pages": len(done_bps),
                "initial_processed_pages": len(done_bps),
                "initial_partial_failed_bps": partial_failed_bps,
                "initial_page_idx": len(done_bps),
                "task_meta": task_meta,
                "model_label": _model_label(model_key, t_args),
                "model_source": t_args.get("model_source", "builtin"),
                "model_key": t_args.get("model_key", model_key),
                "model_id": t_args.get("model_id", ""),
                "provider": t_args.get("provider", ""),
                "page_idx_by_bp": page_idx_by_bp,
            },
            "context": {
                "pages": pages,
                "doc_title": doc_title,
            },
        }

    def run_page(*, doc_id: str, bp: int, **_kwargs):
        model_key, t_args = deps["get_active_translate_args"]()
        glossary = deps["get_glossary"](doc_id)
        try:
            entry = deps["translate_page_stream"](
                _kwargs["context"]["pages"],
                bp,
                model_key,
                t_args,
                glossary,
                doc_id=doc_id,
                stop_checker=lambda: deps["is_stop_requested"](doc_id),
            )
        except Exception as exc:
            exc._worker_model_key = model_key
            raise

        entry_idx = deps["save_entry_to_disk"](entry, _kwargs["context"]["doc_title"], doc_id)
        page_entries = entry.get("_page_entries", [])
        return {
            "entry": entry,
            "entry_idx": entry_idx,
            "para_count": len(page_entries),
            "char_count": sum(len(item.get("translation", "")) for item in page_entries),
            "usage": entry.get("_usage", {}),
            "partial_failed": deps["entry_has_paragraph_error"](entry),
            "model_key": model_key,
        }

    def handle_page_exception(exc: Exception, *, doc_id: str, bp: int, **_kwargs):
        draft = deps["default_stream_draft_state"]()
        snapshot = deps["load_translate_state"](doc_id)
        draft.update(snapshot.get("draft") or {})
        if draft.get("bp") != bp:
            draft = deps["default_stream_draft_state"]()
            draft.update({
                "bp": bp,
                "para_total": 0,
                "para_done": 0,
                "paragraphs": [],
            })
        return {
            "draft_error_patch": {
                "active": False,
                "bp": bp,
                "para_idx": draft.get("para_idx"),
                "para_total": draft.get("para_total", 0),
                "para_done": draft.get("para_done", 0),
                "paragraph_errors": draft.get("paragraph_errors", []),
                "paragraphs": draft.get("paragraphs", []),
                "status": "error",
                "note": f"p.{bp} 翻译失败，等待重试。",
                "last_error": str(exc),
            },
            "model_key": getattr(exc, "_worker_model_key", _kwargs["worker_plan"].get("model_key", "")),
        }

    return run_translate_worker(
        doc_id=doc_id,
        build_plan=build_plan,
        run_page=run_page,
        handle_page_exception=handle_page_exception,
        deps=deps,
    )

"""连续翻译 worker 业务逻辑。"""
import logging

from translation.translate_state import TASK_KIND_CONTINUOUS, _build_translate_task_meta
from translation.translate_worker_common import run_translate_worker

logger = logging.getLogger(__name__)


def _model_label(model_key: str, t_args: dict) -> str:
    return t_args.get("display_label") or t_args.get("model_id") or model_key


def run_translate_all_worker(doc_id: str, start_bp: int, doc_title: str, deps: dict):
    def _collect_retry_targets(*, doc_id: str, target_bps: list[int]) -> list[int]:
        target_bp_set = {int(bp) for bp in (target_bps or []) if bp is not None}
        if not target_bp_set:
            return []
        snapshot = deps["load_translate_state"](doc_id)
        failed_bps = {
            int(bp)
            for bp in (snapshot.get("failed_bps") or [])
            if bp is not None and int(bp) in target_bp_set
        }
        partial_failed_bps = {
            int(bp)
            for bp in deps["collect_partial_failed_bps"](doc_id, list(target_bp_set))
            if bp is not None and int(bp) in target_bp_set
        }
        return sorted(failed_bps | partial_failed_bps)

    def _retry_model_candidates() -> list[tuple[str, dict]]:
        getter = deps.get("get_translation_retry_model_args")
        if callable(getter):
            return list(getter() or [])
        return []

    def _retry_failed_pages(
        *,
        doc_id: str,
        context: dict,
        retry_bps: list[int],
        retry_round: int,
        model_key_override: str | None = None,
        t_args_override: dict | None = None,
    ) -> dict:
        if not retry_bps:
            return {"model_key": "", "provider": "", "attempted": []}
        if model_key_override and isinstance(t_args_override, dict):
            model_key, t_args = model_key_override, dict(t_args_override)
        else:
            model_key, t_args = deps["get_active_translate_args"]()
        provider = str(t_args.get("provider") or "").strip()
        api_key = str(t_args.get("api_key") or "").strip()
        if not api_key:
            deps["translate_push"]("retry_skip", {
                "retry_round": retry_round,
                "model": model_key,
                "provider": provider,
                "reason": "no_api_key",
            })
            return {"model_key": model_key, "provider": provider, "attempted": []}

        glossary = deps["get_glossary"](doc_id)
        attempted = []
        for bp in retry_bps:
            if deps["runtime_stop_requested"](doc_id):
                break
            try:
                entry = deps["translate_page_stream"](
                    context["pages"],
                    int(bp),
                    model_key,
                    t_args,
                    glossary,
                    doc_id=doc_id,
                    stop_checker=lambda: deps["is_stop_requested"](doc_id),
                )
                deps["save_entry_to_disk"](entry, context["doc_title"], doc_id)
                deps["clear_failed_page_state"](doc_id, int(bp))
                attempted.append(int(bp))
                deps["translate_push"]("page_done", {
                    "bp": int(bp),
                    "retry_round": retry_round,
                    "model": model_key,
                    "provider": provider,
                    "partial_failed": bool(deps["entry_has_paragraph_error"](entry)),
                })
            except Exception as exc:
                deps["mark_failed_page_state"](doc_id, int(bp), str(exc))
                deps["translate_push"]("page_error", {
                    "bp": int(bp),
                    "error": str(exc),
                    "retry_round": retry_round,
                    "model": model_key,
                    "provider": provider,
                })
        return {"model_key": model_key, "provider": provider, "attempted": attempted}

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

    def after_target_loop(*, doc_id: str, worker_plan: dict, context: dict, **_kwargs):
        target_bps = [int(bp) for bp in (worker_plan.get("target_bps") or []) if bp is not None]
        retry_bps = _collect_retry_targets(doc_id=doc_id, target_bps=target_bps)
        if not retry_bps:
            return

        deps["translate_push"]("retry_round_start", {
            "retry_round": 1,
            "targets": retry_bps,
            "provider": worker_plan.get("provider", ""),
            "model": worker_plan.get("model_key", ""),
        })
        retry_models = _retry_model_candidates()
        for retry_round, (retry_model_key, retry_t_args) in enumerate(retry_models, start=1):
            remaining = _collect_retry_targets(doc_id=doc_id, target_bps=target_bps)
            if not remaining:
                return
            deps["translate_push"]("retry_round_start", {
                "retry_round": retry_round,
                "targets": remaining,
                "model_target": retry_model_key,
            })
            _retry_failed_pages(
                doc_id=doc_id,
                context=context,
                retry_bps=remaining,
                retry_round=retry_round,
                model_key_override=retry_model_key,
                t_args_override=retry_t_args,
            )

    return run_translate_worker(
        doc_id=doc_id,
        build_plan=build_plan,
        run_page=run_page,
        handle_page_exception=handle_page_exception,
        deps=deps,
        after_target_loop=after_target_loop,
    )

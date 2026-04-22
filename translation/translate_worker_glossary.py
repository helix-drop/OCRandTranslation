"""词典补重译 worker 业务逻辑。"""

from translation.translate_state import _normalize_translate_task_meta
from translation.translate_worker_common import run_translate_worker


def _model_label(model_key: str, t_args: dict) -> str:
    return t_args.get("display_label") or t_args.get("model_id") or model_key


def run_glossary_retranslate_worker(doc_id: str, task_meta: dict, doc_title: str, deps: dict):
    normalized_task_meta = _normalize_translate_task_meta(task_meta)

    def build_plan():
        target_segments_by_bp = dict(normalized_task_meta.get("target_segments_by_bp") or {})
        target_bps = list(normalized_task_meta.get("target_bps") or [])
        if not target_bps and target_segments_by_bp:
            target_bps = sorted(int(bp) for bp in target_segments_by_bp.keys())
        total_pages = len(target_bps)
        if not doc_id or not deps["get_doc_meta"](doc_id):
            return {
                "start_error": {
                    "start_bp": normalized_task_meta.get("start_bp"),
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
                    "start_bp": normalized_task_meta.get("start_bp"),
                    "error_code": "no_pages",
                    "message": "未找到可翻译页面",
                }
            }
        if not t_args.get("api_key"):
            return {
                "start_error": {
                    "start_bp": normalized_task_meta.get("start_bp"),
                    "error_code": "no_api_key",
                    "message": "缺少翻译 API Key",
                    "total_pages": total_pages,
                    "model_label": _model_label(model_key, t_args),
                }
            }
        if not target_bps:
            return {
                "start_error": {
                    "start_bp": normalized_task_meta.get("start_bp"),
                    "error_code": "no_retranslate_range",
                    "message": "当前范围内没有可按词典补重译的机器译文段落。",
                    "total_pages": 0,
                    "model_label": _model_label(model_key, t_args),
                }
            }

        entry_by_bp = {
            int(entry.get("_pageBP")): entry
            for entry in entries
            if entry.get("_pageBP") is not None
        }
        page_idx_by_bp = {int(bp): idx + 1 for idx, bp in enumerate(target_bps)}
        return {
            "worker_plan": {
                "start_bp": normalized_task_meta.get("start_bp"),
                "target_bps": target_bps,
                "total_pages": total_pages,
                "initial_done_pages": 0,
                "initial_processed_pages": 0,
                "initial_partial_failed_bps": [],
                "initial_page_idx": 0,
                "task_meta": normalized_task_meta,
                "model_label": _model_label(model_key, t_args),
                "model_source": t_args.get("model_source", "builtin"),
                "model_key": t_args.get("model_key", model_key),
                "model_id": t_args.get("model_id", ""),
                "provider": t_args.get("provider", ""),
                "page_idx_by_bp": page_idx_by_bp,
                "target_segments_by_bp": target_segments_by_bp,
            },
            "context": {
                "pages": pages,
                "entry_by_bp": entry_by_bp,
                "doc_title": doc_title,
            },
        }

    def run_page(*, doc_id: str, bp: int, worker_plan: dict, context: dict, **_kwargs):
        model_key, t_args = deps["get_active_translate_args"]()
        glossary = deps["get_glossary"](doc_id)
        existing_entry = (context.get("entry_by_bp") or {}).get(int(bp))
        if not existing_entry:
            raise RuntimeError(f"第{bp}页尚未有已译内容，无法按词典补重译。")

        target_segment_indices = (
            worker_plan.get("target_segments_by_bp", {}).get(str(int(bp))) or []
        )
        try:
            entry, page_stats = deps["retranslate_page_with_current_glossary"](
                context["pages"],
                int(bp),
                existing_entry,
                model_key,
                t_args,
                glossary,
                target_segment_indices=target_segment_indices,
            )
        except Exception as exc:
            exc._worker_model_key = model_key
            raise

        entry_idx = deps["save_entry_to_disk"](entry, context["doc_title"], doc_id)
        targeted_indices = {
            int(idx)
            for idx in (page_stats.get("targeted_segment_indices") or [])
            if idx is not None
        }
        page_entries = entry.get("_page_entries", [])
        char_count = sum(
            len(str(page_entries[idx].get("translation", "") or ""))
            for idx in targeted_indices
            if 0 <= idx < len(page_entries)
        )
        return {
            "entry": entry,
            "entry_idx": entry_idx,
            "para_count": len(targeted_indices),
            "char_count": char_count,
            "usage": entry.get("_usage", {}),
            "partial_failed": deps["entry_has_paragraph_error"](entry),
            "model_key": model_key,
            "entry_cache_update": {int(bp): entry},
        }

    def handle_page_exception(exc: Exception, **_kwargs):
        return {
            "model_key": getattr(exc, "_worker_model_key", _kwargs["worker_plan"].get("model_key", "")),
        }

    return run_translate_worker(
        doc_id=doc_id,
        build_plan=build_plan,
        run_page=run_page,
        handle_page_exception=handle_page_exception,
        deps=deps,
    )

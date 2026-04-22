"""页面状态聚合 helper。"""

from config import (
    get_active_model_mode,
    get_active_builtin_model_key,
    get_custom_model_config,
    get_active_visual_model_mode,
    get_active_builtin_visual_model_key,
    get_visual_custom_model_config,
    get_glossary,
    get_paddle_token,
    get_deepseek_key,
    get_dashscope_key,
    get_translate_parallel_enabled,
    get_translate_parallel_limit,
    get_doc_cleanup_headers_footers,
    get_upload_cleanup_headers_footers_enabled,
    get_doc_auto_visual_toc_enabled,
    get_upload_auto_visual_toc_enabled,
    get_doc_meta,
)
from model_capabilities import get_selectable_models
from document.text_processing import get_page_range


def get_app_state(doc_id: str = "", *, deps: dict) -> dict:
    """获取阅读页、首页和设置页共用的聚合状态。"""
    load_pages_from_disk = deps["load_pages_from_disk"]
    load_visible_page_view = deps["load_visible_page_view"]
    load_entries_from_disk = deps["load_entries_from_disk"]
    load_toc_visual_manual_inputs = deps["load_toc_visual_manual_inputs"]
    resolve_model_spec = deps["resolve_model_spec"]
    resolve_visual_model_spec = deps["resolve_visual_model_spec"]
    sqlite_repository_factory = deps.get("SQLiteRepository")

    pages, src_name = load_pages_from_disk(doc_id)
    visible_page_view = load_visible_page_view(doc_id, pages=pages)
    entries, doc_title, entry_idx = load_entries_from_disk(doc_id, pages=pages)
    active_model_mode = get_active_model_mode()
    active_builtin_model_key = get_active_builtin_model_key()
    custom_model = get_custom_model_config()
    resolved_spec = resolve_model_spec()
    active_visual_model_mode = get_active_visual_model_mode()
    active_builtin_visual_model_key = get_active_builtin_visual_model_key()
    visual_custom_model = get_visual_custom_model_config()
    resolved_visual_spec = resolve_visual_model_spec()
    meta = get_doc_meta(doc_id)
    repo = sqlite_repository_factory() if callable(sqlite_repository_factory) else None
    fnm_run = repo.get_latest_fnm_run(doc_id) if repo and doc_id else {}
    entry_idx = meta.get("last_entry_idx", entry_idx)
    cleanup_headers_footers_enabled = get_doc_cleanup_headers_footers(doc_id) if doc_id else True
    auto_visual_toc_enabled = get_doc_auto_visual_toc_enabled(doc_id) if doc_id else False
    fnm_view_ready = bool(cleanup_headers_footers_enabled and fnm_run and fnm_run.get("status") == "done")
    visual_toc_status = str(meta.get("toc_visual_status", "idle") or "idle").strip() or "idle"
    visual_toc_message = str(meta.get("toc_visual_message", "") or "").strip()
    visual_toc_phase = str(meta.get("toc_visual_phase", "") or "").strip()
    visual_toc_progress_pct = int(meta.get("toc_visual_progress_pct", 0) or 0)
    visual_toc_progress_label = str(meta.get("toc_visual_progress_label", "") or "").strip()
    visual_toc_progress_detail = str(meta.get("toc_visual_progress_detail", "") or "").strip()
    visual_toc_status_label_map = {
        "idle": "未生成",
        "running": "生成中",
        "ready": "已生成",
        "unsupported": "当前模型不支持视觉目录",
        "failed": "生成失败",
        "needs_offset": "需要确认页码偏移",
    }
    visual_toc_status_label = visual_toc_status_label_map.get(visual_toc_status, visual_toc_status)
    manual_toc_inputs = load_toc_visual_manual_inputs(doc_id) if doc_id else {}
    manual_toc_mode = str((manual_toc_inputs or {}).get("mode") or "").strip().lower()
    manual_toc_page_count = int((manual_toc_inputs or {}).get("page_count") or 0)
    manual_toc_source_name = str((manual_toc_inputs or {}).get("source_name") or "").strip()
    manual_toc_enabled = manual_toc_mode in {"manual_pdf", "manual_images"}
    manual_toc_label_map = {
        "manual_pdf": "手动目录 PDF",
        "manual_images": "手动目录截图",
    }
    manual_toc_label = manual_toc_label_map.get(manual_toc_mode, "未提供")

    first_page = visible_page_view["first_visible_page"] or (get_page_range(pages)[0] if pages else 1)
    last_page = visible_page_view["last_visible_page"] or (get_page_range(pages)[1] if pages else 1)
    visible_page_count = int(visible_page_view["visible_page_count"] or 0)

    has_entries = len(entries) > 0
    translation_models = get_selectable_models("translation")
    visual_models = get_selectable_models("vision")
    return {
        "pages": pages,
        "src_name": src_name,
        "entries": entries,
        "doc_title": doc_title,
        "entry_idx": entry_idx,
        "model_key": active_builtin_model_key,
        "models": translation_models,
        "translation_models": translation_models,
        "visual_models": visual_models,
        "glossary": get_glossary(doc_id),
        "paddle_token": get_paddle_token(),
        "deepseek_key": get_deepseek_key(),
        "dashscope_key": get_dashscope_key(),
        "active_model_mode": active_model_mode,
        "active_builtin_model_key": active_builtin_model_key,
        "custom_model": custom_model,
        "custom_model_name": custom_model.get("display_name") or custom_model.get("model_id", ""),
        "custom_model_enabled": active_model_mode == "custom",
        "custom_model_base_key": "",
        "current_model_source": resolved_spec.source,
        "current_model_id": resolved_spec.model_id,
        "current_model_label": resolved_spec.display_label,
        "current_model_provider": resolved_spec.provider,
        "active_visual_model_mode": active_visual_model_mode,
        "visual_model_key": active_builtin_visual_model_key,
        "visual_custom_model": visual_custom_model,
        "visual_custom_model_name": visual_custom_model.get("display_name") or visual_custom_model.get("model_id", ""),
        "visual_custom_model_enabled": active_visual_model_mode == "custom",
        "current_visual_model_source": resolved_visual_spec.source,
        "current_visual_model_id": resolved_visual_spec.model_id,
        "current_visual_model_label": resolved_visual_spec.display_label,
        "current_visual_model_provider": resolved_visual_spec.provider,
        "translate_parallel_enabled": get_translate_parallel_enabled(),
        "translate_parallel_limit": get_translate_parallel_limit(),
        "has_pages": len(pages) > 0,
        "has_entries": has_entries,
        "has_translation_history": has_entries,
        "page_count": visible_page_count or len(pages),
        "first_page": first_page,
        "last_page": last_page,
        "visible_page_view": visible_page_view,
        "visible_page_bps": visible_page_view["visible_page_bps"],
        "hidden_placeholder_bps": visible_page_view["hidden_placeholder_bps"],
        "visible_page_count": visible_page_count or len(pages),
        "entry_count": len(entries),
        "cleanup_headers_footers_enabled": cleanup_headers_footers_enabled,
        "fnm_view_ready": fnm_view_ready,
        "cleanup_mode_label": "FNM 模式（清理 + 视觉目录）" if cleanup_headers_footers_enabled else "快速模式",
        "cleanup_mode_detail": "当前文档会先清理页眉页脚，再生成自动视觉目录，随后执行 FNM 注释分类。" if cleanup_headers_footers_enabled else "当前文档跳过 FNM 链路，优先更快开始阅读。",
        "upload_cleanup_default_enabled": get_upload_cleanup_headers_footers_enabled(),
        "auto_visual_toc_enabled": auto_visual_toc_enabled,
        "auto_visual_toc_mode_label": "自动视觉目录已纳入 FNM" if cleanup_headers_footers_enabled else ("自动视觉目录已手动开启" if auto_visual_toc_enabled else "自动视觉目录未开启"),
        "auto_visual_toc_mode_detail": (
            visual_toc_message
            or (
                "FNM 模式下会先生成自动视觉目录，再进入 FNM 分类。"
                if cleanup_headers_footers_enabled
                else ("当前文档保留手动触发的自动视觉目录结果。" if auto_visual_toc_enabled else "当前文档不会自动生成视觉目录。")
            )
        ),
        "visual_toc_status": visual_toc_status,
        "visual_toc_status_label": visual_toc_status_label,
        "visual_toc_status_message": visual_toc_message,
        "visual_toc_phase": visual_toc_phase,
        "visual_toc_progress_pct": visual_toc_progress_pct,
        "visual_toc_progress_label": visual_toc_progress_label,
        "visual_toc_progress_detail": visual_toc_progress_detail,
        "manual_toc_enabled": manual_toc_enabled,
        "manual_toc_mode": manual_toc_mode,
        "manual_toc_label": manual_toc_label,
        "manual_toc_page_count": manual_toc_page_count,
        "manual_toc_source_name": manual_toc_source_name,
        "upload_auto_visual_toc_default_enabled": get_upload_cleanup_headers_footers_enabled(),
    }

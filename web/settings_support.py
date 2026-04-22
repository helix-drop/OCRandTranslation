"""设置页辅助函数。"""

from __future__ import annotations

import re

from flask import flash, redirect, request, url_for

from config import (
    clear_custom_model_config,
    clear_visual_custom_model_config,
    enable_custom_model,
    enable_visual_custom_model,
    get_active_model_mode,
    get_current_doc_id,
    get_custom_model_config,
    get_model_key,
    get_visual_custom_model_config,
    save_custom_model_config,
    save_visual_custom_model_config,
    set_translate_parallel_settings,
)
from translation.translate_runtime import has_active_translate_task


CUSTOM_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]+$")


def serialize_glossary_retranslate_preview(preview: dict) -> dict:
    payload = dict(preview or {})
    payload["task"] = dict(payload.get("task") or {})
    payload["task"]["target_segments_by_bp"] = {
        str(bp): [
            int(idx)
            for idx in (indices or [])
            if idx is not None
        ]
        for bp, indices in dict(payload["task"].get("target_segments_by_bp") or {}).items()
    }
    payload["target_bps"] = [
        int(bp)
        for bp in (payload.get("target_bps") or [])
        if bp is not None
    ]
    payload["target_segments_by_bp"] = {
        str(bp): [
            int(idx)
            for idx in (indices or [])
            if idx is not None
        ]
        for bp, indices in dict(payload.get("target_segments_by_bp") or {}).items()
    }
    payload["problem_segments"] = [
        {
            "bp": int(item.get("bp") or 0),
            "segment_index": int(item.get("segment_index") or 0),
            "pages": str(item.get("pages", "") or ""),
            "source_excerpt": str(item.get("source_excerpt", "") or ""),
            "translation_excerpt": str(item.get("translation_excerpt", "") or ""),
            "missing_terms": [
                {
                    "term": str(term.get("term", "") or ""),
                    "defn": str(term.get("defn", "") or ""),
                }
                for term in (item.get("missing_terms") or [])
                if isinstance(term, dict)
            ],
        }
        for item in (payload.get("problem_segments") or [])
        if isinstance(item, dict)
    ]
    payload["problem_list_truncated"] = bool(payload.get("problem_list_truncated"))
    return payload


def redirect_settings(
    doc_id: str = "",
    open_custom_model: bool = False,
    open_visual_custom_model: bool = False,
):
    target_doc_id = (doc_id or get_current_doc_id() or "").strip()
    params = {}
    if target_doc_id:
        params["doc_id"] = target_doc_id
    if open_custom_model:
        params["open_custom_model"] = "1"
    if open_visual_custom_model:
        params["open_visual_custom_model"] = "1"
    target = url_for("settings", **params)
    if open_custom_model:
        target += "#customModelPanel"
    elif open_visual_custom_model:
        target += "#visualCustomModelPanel"
    return redirect(target)


def redirect_after_model_change(next_page: str, doc_id: str):
    if next_page == "reading":
        reading_params = {}
        if doc_id:
            reading_params["doc_id"] = doc_id
        bp = request.values.get("bp", type=int)
        if bp is not None:
            reading_params["bp"] = bp
        for key in ("usage", "orig", "pdf"):
            value = request.values.get(key, "").strip()
            if value in {"0", "1"}:
                reading_params[key] = value
        layout = request.values.get("layout", "").strip()
        if layout in {"stack", "side"}:
            reading_params["layout"] = layout
        view = request.values.get("view", "").strip().lower()
        if view == "fnm":
            reading_params["view"] = "fnm"
        return redirect(url_for("reading", **reading_params))
    if next_page == "input":
        return redirect(url_for("input_page", doc_id=doc_id))
    if next_page == "settings":
        return redirect_settings(doc_id)
    return redirect(url_for("home", doc_id=doc_id))


def save_text_setting(form_key: str, setter, success_message: str):
    setter(request.form.get(form_key, "").strip())
    flash(success_message, "success")


def save_translate_parallel_section():
    enabled_values = [
        str(v).strip().lower()
        for v in request.form.getlist("translate_parallel_enabled")
    ]
    enabled = any(v in {"1", "true", "yes", "on"} for v in enabled_values)
    limit = request.form.get("translate_parallel_limit", "").strip()
    normalized_enabled, normalized_limit = set_translate_parallel_settings(enabled, limit)
    if normalized_enabled:
        flash(f"已开启段内并发翻译（上限 {normalized_limit}）", "success")
    else:
        flash("已关闭段内并发翻译", "success")
    if has_active_translate_task():
        flash("当前页的翻译已经启动，新的并发设置会从下一页开始生效。", "info")


def current_model_target() -> str:
    return "custom" if get_active_model_mode() == "custom" else f"builtin:{get_model_key()}"


def provider_api_key_label(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized in {"qwen", "qwen_mt"}:
        return "DashScope API Key"
    if normalized == "deepseek":
        return "DeepSeek API Key"
    return "OpenAI 兼容 API Key"


def validate_and_build_custom_model(allowed_providers: set[str], label: str) -> dict | str:
    """从 request.form 校验并构建自定义模型 dict。成功返回 dict，失败返回错误消息字符串。"""
    provider_type = request.form.get("provider_type", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    model_id = request.form.get("model_id", "").strip()
    qwen_region = request.form.get("qwen_region", "cn").strip().lower()
    base_url = request.form.get("base_url", "").strip()
    custom_api_key = request.form.get("custom_api_key", "").strip()

    if provider_type not in allowed_providers:
        return f"{label} provider 无效。"
    if not model_id:
        return f"{label}必须填写模型 ID。"
    if not CUSTOM_MODEL_ID_PATTERN.fullmatch(model_id):
        return "模型 ID 格式无效：仅允许字母、数字、.、_、-、:、/"
    if provider_type == "openai_compatible":
        if not base_url:
            return "OpenAI 兼容模型必须填写 Base URL。"
        if not custom_api_key:
            return "OpenAI 兼容模型必须填写专用 API Key。"

    return {
        "enabled": True,
        "display_name": display_name or model_id,
        "provider_type": provider_type,
        "model_id": model_id,
        "base_url": base_url if provider_type == "openai_compatible" else "",
        "qwen_region": qwen_region if provider_type in {"qwen", "qwen_mt"} else "cn",
        "api_key_mode": "builtin_dashscope" if provider_type in {"qwen", "qwen_mt"} else ("builtin_deepseek" if provider_type == "deepseek" else "custom"),
        "custom_api_key": custom_api_key if provider_type == "openai_compatible" else "",
        "extra_body": {"enable_thinking": False} if provider_type == "qwen" else {},
    }


def save_custom_model_section(section: str, current_doc_id: str):
    redir_kw = {"open_custom_model": True}

    if section == "custom_model_save":
        result = validate_and_build_custom_model(
            {"qwen", "qwen_mt", "deepseek", "openai_compatible"},
            "自定义模型",
        )
        if isinstance(result, str):
            flash(result, "error")
            return redirect_settings(current_doc_id, **redir_kw)
        save_custom_model_config(result)
        flash(f"已保存自定义模型配置：{result['display_name']}", "success")
        return redirect_settings(current_doc_id, **redir_kw)

    if section in ("custom_model_enable", "custom_model_activate"):
        custom_model = get_custom_model_config()
        if not custom_model.get("model_id"):
            flash("还没有可启用的自定义模型，请先保存配置。", "error")
        else:
            enable_custom_model()
            flash(
                f"已启用自定义模型：{custom_model.get('display_name') or custom_model.get('model_id')}",
                "success",
            )
        return redirect_settings(current_doc_id, **redir_kw)

    if section == "custom_model":
        legacy_name = request.form.get("custom_model_name", "").strip()
        if legacy_name:
            save_custom_model_config({
                "enabled": True,
                "display_name": legacy_name,
                "provider_type": "qwen",
                "model_id": legacy_name,
                "base_url": "",
                "qwen_region": "cn",
                "api_key_mode": "builtin_dashscope",
                "custom_api_key": "",
                "extra_body": {"enable_thinking": False},
            })
            flash(f"已保存自定义模型配置：{legacy_name}", "success")
        else:
            clear_custom_model_config()
            flash("已清空自定义模型配置，恢复使用默认模型", "success")
        return redirect_settings(current_doc_id, **redir_kw)

    if section == "custom_model_clear":
        clear_custom_model_config()
        flash("已清空自定义模型配置，恢复使用默认模型", "success")
        return redirect_settings(current_doc_id, **redir_kw)

    return None


def save_visual_custom_model_section(section: str, current_doc_id: str):
    redir_kw = {"open_visual_custom_model": True}

    if section == "visual_custom_model_save":
        result = validate_and_build_custom_model(
            {"qwen", "deepseek", "openai_compatible"},
            "视觉目录自定义模型",
        )
        if isinstance(result, str):
            flash(result, "error")
            return redirect_settings(current_doc_id, **redir_kw)
        save_visual_custom_model_config(result)
        flash(f"已保存视觉目录模型配置：{result['display_name']}", "success")
        return redirect_settings(current_doc_id, **redir_kw)

    if section == "visual_custom_model_enable":
        visual_model = get_visual_custom_model_config()
        if not visual_model.get("enabled") or not visual_model.get("model_id"):
            flash("还没有可启用的视觉目录自定义模型，请先保存配置。", "error")
        else:
            enable_visual_custom_model()
            flash(
                f"已启用视觉目录自定义模型：{visual_model.get('display_name') or visual_model.get('model_id')}",
                "success",
            )
        return redirect_settings(current_doc_id, **redir_kw)

    if section == "visual_custom_model_clear":
        clear_visual_custom_model_config()
        flash("已清空视觉目录自定义模型配置，恢复使用内置视觉模型", "success")
        return redirect_settings(current_doc_id, **redir_kw)

    return None

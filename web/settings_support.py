"""设置页辅助函数。"""

from __future__ import annotations

import re

from flask import flash, redirect, request, url_for

from config import (
    get_current_doc_id,
    save_fnm_model_pool,
    save_translation_model_pool,
    set_translate_parallel_settings,
)
from model_capabilities import get_selectable_models
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


def redirect_settings(doc_id: str = ""):
    target_doc_id = (doc_id or get_current_doc_id() or "").strip()
    params = {}
    if target_doc_id:
        params["doc_id"] = target_doc_id
    return redirect(url_for("settings", **params))


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


def provider_api_key_label(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized in {"qwen", "qwen_mt"}:
        return "DashScope API Key"
    if normalized == "deepseek":
        return "DeepSeek API Key"
    if normalized == "glm":
        return "智谱 GLM API Key"
    if normalized == "kimi":
        return "Kimi API Key"
    if normalized == "mimo":
        return "MiMo 全局 API Key"
    if normalized == "mimo_token_plan":
        return "MiMo Token Plan 专用 API Key"
    return "OpenAI 兼容 API Key"


def _pool_slot_form_prefix(pool_name: str, slot_no: int) -> str:
    return f"{pool_name}_slot{slot_no}"


def _pool_custom_provider_options(capability: str) -> set[str]:
    if capability == "fnm":
        return {"qwen", "openai_compatible", "mimo", "mimo_token_plan", "glm", "kimi"}
    return {"deepseek", "qwen", "qwen_mt", "openai_compatible", "mimo", "mimo_token_plan", "glm", "kimi"}


def _validate_and_build_model_pool_slot(pool_name: str, slot_no: int, capability: str) -> dict | str:
    prefix = _pool_slot_form_prefix(pool_name, slot_no)
    mode = request.form.get(f"{prefix}_mode", "empty").strip().lower()
    thinking_values = [
        str(v).strip().lower()
        for v in request.form.getlist(f"{prefix}_thinking_enabled")
    ]
    thinking_enabled = any(v in {"1", "true", "yes", "on"} for v in thinking_values)
    if mode == "empty":
        return {"mode": "empty"}
    if mode == "builtin":
        builtin_key = request.form.get(f"{prefix}_builtin_key", "").strip()
        if builtin_key not in get_selectable_models(capability):
            return f"{pool_name} 第 {slot_no} 槽内置模型无效。"
        return {
            "mode": "builtin",
            "builtin_key": builtin_key,
            "thinking_enabled": thinking_enabled,
        }
    if mode != "custom":
        return f"{pool_name} 第 {slot_no} 槽模式无效。"

    provider_type = request.form.get(f"{prefix}_provider_type", "").strip().lower()
    model_id = request.form.get(f"{prefix}_model_id", "").strip()
    display_name = request.form.get(f"{prefix}_display_name", "").strip()
    qwen_region = request.form.get(f"{prefix}_qwen_region", "cn").strip().lower()
    base_url = request.form.get(f"{prefix}_base_url", "").strip()
    custom_api_key = request.form.get(f"{prefix}_custom_api_key", "").strip()

    if provider_type not in _pool_custom_provider_options(capability):
        return f"{pool_name} 第 {slot_no} 槽 provider 无效。"
    if not model_id:
        return f"{pool_name} 第 {slot_no} 槽必须填写模型 ID。"
    if not CUSTOM_MODEL_ID_PATTERN.fullmatch(model_id):
        return f"{pool_name} 第 {slot_no} 槽模型 ID 格式无效。"
    if provider_type in {"openai_compatible", "mimo_token_plan"} and not base_url:
        return f"{pool_name} 第 {slot_no} 槽必须填写 Base URL。"
    if provider_type in {"openai_compatible", "mimo_token_plan"} and not custom_api_key:
        return f"{pool_name} 第 {slot_no} 槽必须填写专用 API Key。"

    slot = {
        "mode": "custom",
        "display_name": display_name or model_id,
        "provider_type": provider_type,
        "model_id": model_id,
        "base_url": base_url,
        "qwen_region": qwen_region if provider_type in {"qwen", "qwen_mt"} else "cn",
        "custom_api_key": custom_api_key if provider_type in {"openai_compatible", "mimo_token_plan"} else "",
        "extra_body": {"enable_thinking": thinking_enabled} if provider_type == "qwen" else {},
        "thinking_enabled": thinking_enabled,
    }
    return slot


def save_model_pool_section(section: str, current_doc_id: str):
    if section not in {"translation_model_pool", "fnm_model_pool"}:
        return None
    capability = "translation" if section == "translation_model_pool" else "fnm"
    slots = []
    for slot_no in range(1, 4):
        result = _validate_and_build_model_pool_slot(section, slot_no, capability)
        if isinstance(result, str):
            flash(result, "error")
            return redirect_settings(current_doc_id)
        slots.append(result)
    if capability == "translation":
        save_translation_model_pool(slots)
        flash("翻译模型池已保存。", "success")
    else:
        save_fnm_model_pool(slots)
        flash("FNM 视觉与修补模型池已保存。", "success")
    return redirect_settings(current_doc_id)

"""内置模型目录与能力描述。"""

from __future__ import annotations

from copy import deepcopy


def _chat_model(
    model_id: str,
    label: str,
    provider: str,
    *,
    selectable: bool = True,
    thinking: bool = False,
    companion: str | None = None,
) -> dict:
    spec = {
        "id": model_id,
        "label": label,
        "provider": provider,
        "api_family": "chat",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": "chat_json",
        "companion_chat_model_key": companion or model_id,
        "translation_selectable": selectable,
        "fnm_selectable": False,
        "visual_selectable": False,
    }
    if thinking:
        spec["supports_thinking_toggle"] = True
        spec["thinking_request_format"] = (
            "qwen_enable_thinking" if provider == "qwen" else "thinking_type"
        )
    return spec


def _mt_model(
    model_id: str,
    label: str,
    *,
    stream_mode: str,
    companion: str,
    selectable: bool = True,
) -> dict:
    return {
        "id": model_id,
        "label": label,
        "provider": "qwen_mt",
        "api_family": "mt",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": stream_mode,
        "companion_chat_model_key": companion,
        "translation_selectable": selectable,
        "fnm_selectable": False,
        "visual_selectable": False,
    }


def _vision_model(
    model_id: str,
    label: str,
    provider: str,
    *,
    selectable: bool = True,
    translation_selectable: bool = False,
    thinking: bool = False,
    companion: str | None = None,
    supports_translation: bool = True,
) -> dict:
    spec = {
        "id": model_id,
        "label": label,
        "provider": provider,
        "api_family": "vision",
        "supports_translation": supports_translation,
        "supports_vision": True,
        "supports_stream": True,
        "stream_mode": "chat_json",
        "companion_chat_model_key": companion or model_id,
        "translation_selectable": translation_selectable,
        "fnm_selectable": selectable,
        "visual_selectable": selectable,
    }
    if thinking:
        spec["supports_thinking_toggle"] = True
        spec["thinking_request_format"] = (
            "qwen_enable_thinking" if provider == "qwen" else "thinking_type"
        )
    return spec


_MODEL_SPECS = {
    # DeepSeek 官方 API 当前以 alias 形式暴露文本模型；没有视觉输入能力。
    "deepseek-chat": _chat_model(
        "deepseek-chat",
        "DeepSeek-Chat",
        "deepseek",
        thinking=True,
    ),
    "deepseek-reasoner": _chat_model(
        "deepseek-reasoner",
        "DeepSeek-Reasoner",
        "deepseek",
    ),
    # Qwen3.6 是百炼当前文本与视觉理解文档都推荐的主线系列。
    "qwen3.6-max-preview": _chat_model(
        "qwen3.6-max-preview",
        "Qwen3.6 Max Preview",
        "qwen",
        thinking=True,
        companion="qwen3.6-plus",
    ),
    "qwen3.6-plus": _vision_model(
        "qwen3.6-plus",
        "Qwen3.6 Plus",
        "qwen",
        translation_selectable=True,
        thinking=True,
    ),
    "qwen3.6-flash": _vision_model(
        "qwen3.6-flash",
        "Qwen3.6 Flash",
        "qwen",
        translation_selectable=True,
        thinking=True,
    ),
    "qwen3.5-plus": _vision_model(
        "qwen3.5-plus",
        "Qwen3.5 Plus",
        "qwen",
        translation_selectable=True,
        thinking=True,
    ),
    "qwen3.5-flash": _vision_model(
        "qwen3.5-flash",
        "Qwen3.5 Flash",
        "qwen",
        translation_selectable=True,
        thinking=True,
    ),
    "qwen-plus": _chat_model(
        "qwen-plus",
        "Qwen-Plus",
        "qwen",
        selectable=False,
        thinking=True,
    ),
    "qwen-max": _chat_model(
        "qwen-max",
        "Qwen-Max",
        "qwen",
        selectable=False,
        thinking=True,
        companion="qwen-plus",
    ),
    "qwen-turbo": _chat_model(
        "qwen-turbo",
        "Qwen-Turbo",
        "qwen",
        selectable=False,
        thinking=True,
    ),
    "qwen-mt-plus": _mt_model(
        "qwen-mt-plus",
        "Qwen-MT-Plus",
        stream_mode="mt_cumulative",
        companion="qwen3.6-plus",
    ),
    "qwen-mt-turbo": _mt_model(
        "qwen-mt-turbo",
        "Qwen-MT-Turbo",
        stream_mode="mt_cumulative",
        companion="qwen3.6-flash",
    ),
    "qwen-mt-flash": _mt_model(
        "qwen-mt-flash",
        "Qwen-MT-Flash",
        stream_mode="mt_incremental",
        companion="qwen3.6-flash",
    ),
    "qwen-mt-lite": _mt_model(
        "qwen-mt-lite",
        "Qwen-MT-Lite",
        stream_mode="mt_incremental",
        companion="qwen3.6-flash",
        selectable=False,
    ),
    "qwen3-vl-plus": _vision_model(
        "qwen3-vl-plus",
        "Qwen3 VL Plus",
        "qwen",
        thinking=True,
        companion="qwen3.6-plus",
    ),
    "qwen3-vl-flash": _vision_model(
        "qwen3-vl-flash",
        "Qwen3 VL Flash",
        "qwen",
        thinking=True,
        companion="qwen3.6-flash",
    ),
    "qwen-vl-plus": _vision_model(
        "qwen-vl-plus",
        "Qwen-VL-Plus",
        "qwen",
        selectable=False,
        supports_translation=False,
        companion="qwen-plus",
    ),
    "qwen-vl-max": _vision_model(
        "qwen-vl-max",
        "Qwen-VL-Max",
        "qwen",
        selectable=False,
        supports_translation=False,
        companion="qwen-plus",
    ),
    "qwen-vl-ocr": _vision_model(
        "qwen-vl-ocr",
        "Qwen-VL-OCR",
        "qwen",
        selectable=False,
        supports_translation=False,
        companion="qwen-plus",
    ),
    # MiMo：Pro/Flash 是文本推理候选；V2.5/Omni 用于视觉与修补。
    "mimo-v2-flash": _chat_model(
        "mimo-v2-flash",
        "MiMo V2 Flash",
        "mimo",
    ),
    "mimo-v2-pro": _chat_model(
        "mimo-v2-pro",
        "MiMo V2 Pro",
        "mimo",
        thinking=True,
    ),
    "mimo-v2.5-pro": _chat_model(
        "mimo-v2.5-pro",
        "MiMo V2.5 Pro",
        "mimo",
        thinking=True,
    ),
    "mimo-v2.5": _vision_model(
        "mimo-v2.5",
        "MiMo V2.5",
        "mimo",
        thinking=True,
    ),
    "mimo-v2-omni": _vision_model(
        "mimo-v2-omni",
        "MiMo V2 Omni",
        "mimo",
        thinking=True,
        companion="mimo-v2.5",
    ),
    # 智谱：GLM-5.1 是最新文本旗舰；GLM-5V-Turbo 是视觉+文本主候选。
    "glm-5.1": _chat_model(
        "glm-5.1",
        "GLM-5.1",
        "glm",
        thinking=True,
    ),
    "glm-5": _chat_model(
        "glm-5",
        "GLM-5",
        "glm",
        thinking=True,
    ),
    "glm-5-turbo": _chat_model(
        "glm-5-turbo",
        "GLM-5-Turbo",
        "glm",
        thinking=True,
    ),
    "glm-4.7": _chat_model(
        "glm-4.7",
        "GLM-4.7",
        "glm",
        selectable=False,
        thinking=True,
    ),
    "glm-4.6": _chat_model(
        "glm-4.6",
        "GLM-4.6",
        "glm",
        selectable=False,
        thinking=True,
    ),
    "glm-4.7-flashx": _chat_model(
        "glm-4.7-flashx",
        "GLM-4.7-FlashX",
        "glm",
        selectable=False,
        thinking=True,
    ),
    "glm-4.5": _chat_model(
        "glm-4.5",
        "GLM-4.5",
        "glm",
        selectable=False,
        thinking=True,
    ),
    "glm-4.5-air": _chat_model(
        "glm-4.5-air",
        "GLM-4.5-Air",
        "glm",
        selectable=False,
        thinking=True,
    ),
    "glm-4.5-airx": _chat_model(
        "glm-4.5-airx",
        "GLM-4.5-AirX",
        "glm",
        selectable=False,
        thinking=True,
    ),
    "glm-4-long": _chat_model(
        "glm-4-long",
        "GLM-4-Long",
        "glm",
        selectable=False,
    ),
    "glm-5v-turbo": _vision_model(
        "glm-5v-turbo",
        "GLM-5V-Turbo",
        "glm",
        thinking=True,
        companion="glm-5.1",
    ),
    "glm-4.6v": _vision_model(
        "glm-4.6v",
        "GLM-4.6V",
        "glm",
        thinking=True,
        companion="glm-4.6",
    ),
    "glm-4.5v": _vision_model(
        "glm-4.5v",
        "GLM-4.5V",
        "glm",
        selectable=False,
        thinking=True,
        companion="glm-4.5",
    ),
    # Kimi：K2.6/K2.5 是当前主线；旧 K2 preview 不再作为候选。
    "kimi-k2.6": _vision_model(
        "kimi-k2.6",
        "Kimi K2.6",
        "kimi",
        translation_selectable=True,
        thinking=True,
    ),
    "kimi-k2.5": _vision_model(
        "kimi-k2.5",
        "Kimi K2.5",
        "kimi",
        translation_selectable=True,
        thinking=True,
    ),
    "kimi-k2-0905-preview": _chat_model(
        "kimi-k2-0905-preview",
        "Kimi K2 0905 Preview",
        "kimi",
        selectable=False,
    ),
    "kimi-k2-0711-preview": _chat_model(
        "kimi-k2-0711-preview",
        "Kimi K2 0711 Preview",
        "kimi",
        selectable=False,
    ),
    "kimi-k2-turbo-preview": _chat_model(
        "kimi-k2-turbo-preview",
        "Kimi K2 Turbo Preview",
        "kimi",
        selectable=False,
    ),
    "kimi-k2-thinking": _chat_model(
        "kimi-k2-thinking",
        "Kimi K2 Thinking",
        "kimi",
        selectable=False,
    ),
    "kimi-k2-thinking-turbo": _chat_model(
        "kimi-k2-thinking-turbo",
        "Kimi K2 Thinking Turbo",
        "kimi",
        selectable=False,
    ),
    "moonshot-v1-8k": _chat_model(
        "moonshot-v1-8k",
        "Moonshot V1 8K",
        "kimi",
        selectable=False,
    ),
    "moonshot-v1-32k": _chat_model(
        "moonshot-v1-32k",
        "Moonshot V1 32K",
        "kimi",
    ),
    "moonshot-v1-128k": _chat_model(
        "moonshot-v1-128k",
        "Moonshot V1 128K",
        "kimi",
    ),
    "moonshot-v1-8k-vision-preview": _vision_model(
        "moonshot-v1-8k-vision-preview",
        "Moonshot V1 8K Vision Preview",
        "kimi",
        selectable=False,
        supports_translation=False,
        companion="moonshot-v1-8k",
    ),
    "moonshot-v1-32k-vision-preview": _vision_model(
        "moonshot-v1-32k-vision-preview",
        "Moonshot V1 32K Vision Preview",
        "kimi",
        selectable=False,
        supports_translation=False,
        companion="moonshot-v1-32k",
    ),
    "moonshot-v1-128k-vision-preview": _vision_model(
        "moonshot-v1-128k-vision-preview",
        "Moonshot V1 128K Vision Preview",
        "kimi",
        selectable=False,
        supports_translation=False,
        companion="moonshot-v1-128k",
    ),
}


MODELS = {
    key: {
        "id": value["id"],
        "label": value["label"],
        "provider": value["provider"],
    }
    for key, value in _MODEL_SPECS.items()
}


DEFAULT_TRANSLATION_MODEL_KEY = "deepseek-chat"
DEFAULT_VISUAL_MODEL_KEY = "qwen3.6-plus"


def get_model_spec(key: str, *, capability: str | None = None) -> dict:
    normalized = normalize_builtin_model_key(key, capability=capability)
    return deepcopy(_MODEL_SPECS[normalized])


def normalize_builtin_model_key(key: str | None, *, capability: str | None = None) -> str:
    normalized = str(key or "").strip()
    if normalized not in _MODEL_SPECS:
        normalized = (
            DEFAULT_VISUAL_MODEL_KEY
            if capability in {"vision", "fnm"}
            else DEFAULT_TRANSLATION_MODEL_KEY
        )
    spec = _MODEL_SPECS.get(normalized, {})
    if capability == "translation" and not spec.get("supports_translation"):
        return DEFAULT_TRANSLATION_MODEL_KEY
    if capability == "vision" and not spec.get("supports_vision"):
        return DEFAULT_VISUAL_MODEL_KEY
    if capability == "fnm" and not spec.get("fnm_selectable"):
        return DEFAULT_VISUAL_MODEL_KEY
    return normalized


def get_selectable_models(capability: str) -> dict[str, dict]:
    flag = {
        "translation": "translation_selectable",
        "fnm": "fnm_selectable",
        "vision": "visual_selectable",
    }.get(capability, "translation_selectable")
    return {
        key: {
            "id": value["id"],
            "label": value["label"],
            "provider": value["provider"],
            "supports_thinking_toggle": bool(value.get("supports_thinking_toggle", False)),
            "thinking_request_format": str(value.get("thinking_request_format", "") or ""),
        }
        for key, value in _MODEL_SPECS.items()
        if value.get(flag)
    }


def infer_builtin_key_from_custom_model(provider: str, model_id: str, *, capability: str | None = None) -> str:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model_id = str(model_id or "").strip().lower()
    if normalized_provider == "qwen_mt":
        if "flash" in normalized_model_id:
            return "qwen-mt-flash"
        if "lite" in normalized_model_id:
            return "qwen-mt-lite"
        if "turbo" in normalized_model_id:
            return "qwen-mt-turbo"
        return "qwen-mt-plus"
    if normalized_provider == "qwen":
        if "3.6-max" in normalized_model_id or "3-max" in normalized_model_id:
            return "qwen3.6-max-preview"
        if "3.6-flash" in normalized_model_id:
            return "qwen3.6-flash"
        if "3.6-plus" in normalized_model_id:
            return "qwen3.6-plus"
        if "3.5-flash" in normalized_model_id:
            return "qwen3.5-flash"
        if "3.5-plus" in normalized_model_id:
            return "qwen3.5-plus"
        if "qwen3-vl-flash" in normalized_model_id:
            return "qwen3-vl-flash"
        if "qwen3-vl-plus" in normalized_model_id:
            return "qwen3-vl-plus"
        if "vl-ocr" in normalized_model_id:
            return "qwen-vl-ocr"
        if "vl-max" in normalized_model_id:
            return "qwen-vl-max"
        if "vl-plus" in normalized_model_id:
            return "qwen-vl-plus"
        if "max" in normalized_model_id:
            return "qwen-max"
        if "turbo" in normalized_model_id or "flash" in normalized_model_id:
            return "qwen-turbo"
        return "qwen3.6-plus"
    if normalized_provider == "deepseek":
        if "reasoner" in normalized_model_id or normalized_model_id.endswith("-r1"):
            return "deepseek-reasoner"
        return "deepseek-chat"
    if normalized_provider == "glm":
        if "5v" in normalized_model_id:
            return "glm-5v-turbo"
        if "4.6v" in normalized_model_id:
            return "glm-4.6v"
        if "4.5v" in normalized_model_id:
            return "glm-4.5v"
        if "5.1" in normalized_model_id:
            return "glm-5.1"
        if "5-turbo" in normalized_model_id or "5 turbo" in normalized_model_id:
            return "glm-5-turbo"
        if "4.7-flashx" in normalized_model_id or "4.7 flashx" in normalized_model_id:
            return "glm-4.7-flashx"
        if "4.7" in normalized_model_id:
            return "glm-4.7"
        if "4.6" in normalized_model_id:
            return "glm-4.6"
        if "4.5-airx" in normalized_model_id or "4.5 airx" in normalized_model_id:
            return "glm-4.5-airx"
        if "4.5-air" in normalized_model_id or "4.5 air" in normalized_model_id:
            return "glm-4.5-air"
        if "4.5" in normalized_model_id:
            return "glm-4.5"
        if "long" in normalized_model_id:
            return "glm-4-long"
        return "glm-5.1"
    if normalized_provider == "kimi":
        if "128k-vision" in normalized_model_id:
            return "moonshot-v1-128k-vision-preview"
        if "32k-vision" in normalized_model_id:
            return "moonshot-v1-32k-vision-preview"
        if "8k-vision" in normalized_model_id:
            return "moonshot-v1-8k-vision-preview"
        if "k2.6" in normalized_model_id:
            return "kimi-k2.6"
        if "k2.5" in normalized_model_id:
            return "kimi-k2.5"
        if "thinking-turbo" in normalized_model_id:
            return "kimi-k2-thinking-turbo"
        if "thinking" in normalized_model_id:
            return "kimi-k2-thinking"
        if "turbo" in normalized_model_id:
            return "kimi-k2-turbo-preview"
        if "0711" in normalized_model_id:
            return "kimi-k2-0711-preview"
        if "0905" in normalized_model_id or normalized_model_id.startswith("kimi-k2"):
            return "kimi-k2-0905-preview"
        if "128k" in normalized_model_id:
            return "moonshot-v1-128k"
        if "32k" in normalized_model_id:
            return "moonshot-v1-32k"
        return "kimi-k2.6"
    if normalized_provider in {"mimo", "mimo_token_plan"}:
        if "omni" in normalized_model_id:
            return "mimo-v2-omni"
        if "2.5-pro" in normalized_model_id:
            return "mimo-v2.5-pro"
        if "2.5" in normalized_model_id:
            return "mimo-v2.5"
        if "flash" in normalized_model_id:
            return "mimo-v2-flash"
        if "v2-pro" in normalized_model_id or normalized_model_id.endswith("-pro"):
            return "mimo-v2-pro"
        return "mimo-v2.5"
    return normalize_builtin_model_key("", capability=capability)

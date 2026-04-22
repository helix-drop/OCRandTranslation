"""内置模型目录与能力描述。"""

from __future__ import annotations

from copy import deepcopy


_MODEL_SPECS = {
    "deepseek-chat": {
        "id": "deepseek-chat",
        "label": "DeepSeek-Chat",
        "provider": "deepseek",
        "api_family": "chat",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": "chat_json",
        "companion_chat_model_key": "deepseek-chat",
        "translation_selectable": True,
        "visual_selectable": False,
    },
    "deepseek-reasoner": {
        "id": "deepseek-reasoner",
        "label": "DeepSeek-Reasoner",
        "provider": "deepseek",
        "api_family": "chat",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": "chat_json",
        "companion_chat_model_key": "deepseek-chat",
        "translation_selectable": True,
        "visual_selectable": False,
    },
    "qwen-plus": {
        "id": "qwen-plus",
        "label": "Qwen-Plus",
        "provider": "qwen",
        "api_family": "chat",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": "chat_json",
        "companion_chat_model_key": "qwen-plus",
        "translation_selectable": True,
        "visual_selectable": False,
    },
    "qwen-max": {
        "id": "qwen-max",
        "label": "Qwen-Max",
        "provider": "qwen",
        "api_family": "chat",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": "chat_json",
        "companion_chat_model_key": "qwen-plus",
        "translation_selectable": True,
        "visual_selectable": False,
    },
    "qwen-turbo": {
        "id": "qwen-turbo",
        "label": "Qwen-Turbo",
        "provider": "qwen",
        "api_family": "chat",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": "chat_json",
        "companion_chat_model_key": "qwen-turbo",
        "translation_selectable": True,
        "visual_selectable": False,
    },
    "qwen-mt-plus": {
        "id": "qwen-mt-plus",
        "label": "Qwen-MT-Plus",
        "provider": "qwen_mt",
        "api_family": "mt",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": "mt_cumulative",
        "companion_chat_model_key": "qwen-plus",
        "translation_selectable": True,
        "visual_selectable": False,
    },
    "qwen-mt-turbo": {
        "id": "qwen-mt-turbo",
        "label": "Qwen-MT-Turbo",
        "provider": "qwen_mt",
        "api_family": "mt",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": "mt_cumulative",
        "companion_chat_model_key": "qwen-turbo",
        "translation_selectable": True,
        "visual_selectable": False,
    },
    "qwen-mt-flash": {
        "id": "qwen-mt-flash",
        "label": "Qwen-MT-Flash",
        "provider": "qwen_mt",
        "api_family": "mt",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": "mt_incremental",
        "companion_chat_model_key": "qwen-turbo",
        "translation_selectable": True,
        "visual_selectable": False,
    },
    "qwen-mt-lite": {
        "id": "qwen-mt-lite",
        "label": "Qwen-MT-Lite",
        "provider": "qwen_mt",
        "api_family": "mt",
        "supports_translation": True,
        "supports_vision": False,
        "supports_stream": True,
        "stream_mode": "mt_incremental",
        "companion_chat_model_key": "qwen-turbo",
        "translation_selectable": True,
        "visual_selectable": False,
    },
    "qwen-vl-plus": {
        "id": "qwen-vl-plus",
        "label": "Qwen-VL-Plus",
        "provider": "qwen",
        "api_family": "vision",
        "supports_translation": False,
        "supports_vision": True,
        "supports_stream": True,
        "stream_mode": "chat_json",
        "companion_chat_model_key": "qwen-plus",
        "translation_selectable": False,
        "visual_selectable": True,
    },
    "qwen-vl-max": {
        "id": "qwen-vl-max",
        "label": "Qwen-VL-Max",
        "provider": "qwen",
        "api_family": "vision",
        "supports_translation": False,
        "supports_vision": True,
        "supports_stream": True,
        "stream_mode": "chat_json",
        "companion_chat_model_key": "qwen-plus",
        "translation_selectable": False,
        "visual_selectable": True,
    },
    "qwen-vl-ocr": {
        "id": "qwen-vl-ocr",
        "label": "Qwen-VL-OCR",
        "provider": "qwen",
        "api_family": "vision",
        "supports_translation": False,
        "supports_vision": True,
        "supports_stream": True,
        "stream_mode": "chat_json",
        "companion_chat_model_key": "qwen-plus",
        "translation_selectable": False,
        "visual_selectable": True,
    },
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
DEFAULT_VISUAL_MODEL_KEY = "qwen-vl-plus"


def get_model_spec(key: str, *, capability: str | None = None) -> dict:
    normalized = normalize_builtin_model_key(key, capability=capability)
    return deepcopy(_MODEL_SPECS[normalized])


def normalize_builtin_model_key(key: str | None, *, capability: str | None = None) -> str:
    normalized = str(key or "").strip()
    if normalized not in _MODEL_SPECS:
        normalized = (
            DEFAULT_VISUAL_MODEL_KEY
            if capability == "vision"
            else DEFAULT_TRANSLATION_MODEL_KEY
        )
    spec = _MODEL_SPECS.get(normalized, {})
    if capability == "translation" and not spec.get("supports_translation"):
        return DEFAULT_TRANSLATION_MODEL_KEY
    if capability == "vision" and not spec.get("supports_vision"):
        return DEFAULT_VISUAL_MODEL_KEY
    return normalized


def get_selectable_models(capability: str) -> dict[str, dict]:
    flag = "translation_selectable" if capability == "translation" else "visual_selectable"
    return {
        key: {
            "id": value["id"],
            "label": value["label"],
            "provider": value["provider"],
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
        return "qwen-plus"
    if normalized_provider == "deepseek":
        if "reasoner" in normalized_model_id or normalized_model_id.endswith("-r1"):
            return "deepseek-reasoner"
        return "deepseek-chat"
    return normalize_builtin_model_key("", capability=capability)

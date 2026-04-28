"""本地配置存储：API令牌、术语表、用户偏好、多文档管理。

数据存储路径：项目目录下的 local_data/user_data/
便于应用分发和便携使用。
"""
import copy
import json
import logging
import os
import tempfile
import threading
import time
import uuid as _uuid
from model_capabilities import MODELS, normalize_builtin_model_key

# 项目根目录（config.py 所在目录的父目录）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOCAL_DATA_DIR = os.path.join(PROJECT_ROOT, "local_data")
CONFIG_DIR = os.path.join(LOCAL_DATA_DIR, "user_data")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DATA_DIR = os.path.join(CONFIG_DIR, "data")
DOCS_DIR = os.path.join(DATA_DIR, "documents")
CURRENT_FILE = os.path.join(DATA_DIR, "current.txt")

# 旧数据路径（用于迁移）
OLD_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".foreign_lit_reader")

GLOSSARY_INIT = []
PARA_MAX_CONCURRENCY = 10
PARA_CONTEXT_WINDOW = 200

# 工单 #4：链接质量阈值（FNM_RE.modules.note_linking 用）。
# fallback resolver 命中的 matched 占 matched 总数的比例，超过即触发 link_quality_low。
LINK_FALLBACK_MATCH_RATIO_THRESHOLD_DEFAULT = 0.30
# footnote_orphan_anchor + endnote_orphan_anchor 总数，超过即触发 link_quality_low。
LINK_ORPHAN_ANCHOR_THRESHOLD_DEFAULT = 10
PDF_VIRTUAL_WINDOW_RADIUS_DEFAULT = 5
PDF_VIRTUAL_SCROLL_MIN_PAGES_DEFAULT = 80
TRANSLATE_PARALLEL_ENABLED_DEFAULT = False
TRANSLATE_PARALLEL_LIMIT_DEFAULT = 10
ACTIVE_MODEL_MODE_DEFAULT = "builtin"
ACTIVE_BUILTIN_MODEL_KEY_DEFAULT = "deepseek-chat"
ACTIVE_BUILTIN_FNM_MODEL_KEY_DEFAULT = "qwen3.6-plus"
CUSTOM_MODEL_NAME_DEFAULT = ""
CUSTOM_MODEL_ENABLED_DEFAULT = False
CUSTOM_MODEL_BASE_KEY_DEFAULT = ""
CUSTOM_MODEL_DEFAULT = {
    "enabled": False,
    "display_name": "",
    "provider_type": "qwen",
    "model_id": "",
    "base_url": "",
    "qwen_region": "cn",
    "api_key_mode": "builtin_dashscope",
    "custom_api_key": "",
    "extra_body": {},
    "thinking_enabled": False,
}
MODEL_POOL_SLOT_COUNT = 3
MODEL_POOL_MODE_VALUES = {"builtin", "custom", "empty"}
MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_TOKEN_PLAN_BASE_URL_DEFAULT = "https://token-plan-cn.xiaomimimo.com/v1"
GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
KIMI_BASE_URL = "https://api.moonshot.ai/v1"
MODEL_POOL_LEGACY_KEYS = {
    "model_key",
    "active_model_mode",
    "active_builtin_model_key",
    "custom_model_name",
    "custom_model_enabled",
    "custom_model_base_key",
    "custom_model",
    "active_visual_model_mode",
    "active_builtin_visual_model_key",
    "visual_custom_model",
}

INVALID_DOC_ID_LITERALS = {"undefined", "null", "None"}
DOC_CLEANUP_HEADERS_FOOTERS_DEFAULT = True
UPLOAD_CLEANUP_HEADERS_FOOTERS_DEFAULT = False
DOC_AUTO_VISUAL_TOC_DEFAULT = False
UPLOAD_AUTO_VISUAL_TOC_DEFAULT = False
UPLOAD_CLEANUP_HEADERS_FOOTERS_KEY = "upload_cleanup_headers_footers_enabled"
UPLOAD_AUTO_VISUAL_TOC_KEY = "upload_auto_visual_toc_enabled"


def normalize_doc_id(doc_id: str | None) -> str:
    raw = str(doc_id or "").strip()
    if not raw or raw in INVALID_DOC_ID_LITERALS:
        return ""
    return raw

QWEN_BASE_URLS = {
    "cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "sg": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "us": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
}
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
CUSTOM_MODEL_PROVIDER_TYPES = {
    "qwen",
    "qwen_mt",
    "deepseek",
    "glm",
    "kimi",
    "openai_compatible",
    "mimo",
    "mimo_token_plan",
}
CUSTOM_MODEL_API_KEY_MODES = {
    "builtin_dashscope",
    "builtin_deepseek",
    "builtin_glm",
    "builtin_kimi",
    "builtin_mimo",
    "custom",
}

logger = logging.getLogger(__name__)


def _default_custom_model_config() -> dict:
    return dict(CUSTOM_MODEL_DEFAULT)


def _normalize_builtin_model_key(key) -> str:
    return normalize_builtin_model_key(str(key or "").strip(), capability="translation")


def _normalize_active_model_mode(value) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"builtin", "custom"} else ACTIVE_MODEL_MODE_DEFAULT


def _thinking_extra_body(provider_type: str, enabled: bool) -> dict:
    normalized = str(provider_type or "").strip().lower()
    if normalized == "qwen":
        return {"enable_thinking": bool(enabled)}
    if normalized in {"deepseek", "glm", "kimi", "mimo", "mimo_token_plan"}:
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    return {}


def _normalize_custom_model_config(value) -> dict:
    source = value if isinstance(value, dict) else {}
    cfg = _default_custom_model_config()
    cfg["enabled"] = _coerce_bool(source.get("enabled"), False)
    cfg["display_name"] = str(source.get("display_name", "") or "").strip()
    provider_type = str(source.get("provider_type", "qwen") or "").strip().lower()
    cfg["provider_type"] = provider_type if provider_type in CUSTOM_MODEL_PROVIDER_TYPES else "qwen"
    cfg["model_id"] = str(source.get("model_id", "") or "").strip()
    cfg["base_url"] = str(source.get("base_url", "") or "").strip()
    qwen_region = str(source.get("qwen_region", "cn") or "").strip().lower()
    cfg["qwen_region"] = qwen_region if qwen_region in QWEN_BASE_URLS else "cn"
    api_key_mode = str(source.get("api_key_mode", "") or "").strip().lower()
    cfg["api_key_mode"] = api_key_mode if api_key_mode in CUSTOM_MODEL_API_KEY_MODES else ""
    cfg["custom_api_key"] = str(source.get("custom_api_key", "") or "").strip()
    extra_body = source.get("extra_body")
    cfg["extra_body"] = dict(extra_body) if isinstance(extra_body, dict) else {}
    cfg["thinking_enabled"] = _coerce_bool(
        source.get("thinking_enabled"),
        _coerce_bool(cfg["extra_body"].get("enable_thinking") if isinstance(cfg["extra_body"], dict) else None, False),
    )

    if cfg["provider_type"] == "qwen":
        cfg["api_key_mode"] = "builtin_dashscope"
        cfg["extra_body"] = _thinking_extra_body("qwen", cfg["thinking_enabled"])
        cfg["base_url"] = ""
        cfg["custom_api_key"] = ""
    elif cfg["provider_type"] == "qwen_mt":
        cfg["api_key_mode"] = "builtin_dashscope"
        cfg["base_url"] = ""
        cfg["custom_api_key"] = ""
        cfg["extra_body"] = {}
        cfg["thinking_enabled"] = False
    elif cfg["provider_type"] == "deepseek":
        cfg["api_key_mode"] = "builtin_deepseek"
        cfg["base_url"] = ""
        cfg["custom_api_key"] = ""
        cfg["qwen_region"] = "cn"
        cfg["extra_body"] = _thinking_extra_body("deepseek", True) if cfg["thinking_enabled"] else {}
    elif cfg["provider_type"] == "glm":
        cfg["api_key_mode"] = "builtin_glm"
        cfg["base_url"] = GLM_BASE_URL
        cfg["custom_api_key"] = ""
        cfg["qwen_region"] = "cn"
        cfg["extra_body"] = _thinking_extra_body("glm", cfg["thinking_enabled"])
    elif cfg["provider_type"] == "kimi":
        cfg["api_key_mode"] = "builtin_kimi"
        cfg["base_url"] = KIMI_BASE_URL
        cfg["custom_api_key"] = ""
        cfg["qwen_region"] = "cn"
        cfg["extra_body"] = _thinking_extra_body("kimi", cfg["thinking_enabled"])
    elif cfg["provider_type"] == "mimo":
        cfg["api_key_mode"] = "builtin_mimo"
        cfg["base_url"] = MIMO_BASE_URL
        cfg["custom_api_key"] = ""
        cfg["qwen_region"] = "cn"
        cfg["extra_body"] = _thinking_extra_body("mimo", cfg["thinking_enabled"]) if cfg["thinking_enabled"] else {}
    elif cfg["provider_type"] == "mimo_token_plan":
        cfg["api_key_mode"] = "custom"
        cfg["base_url"] = cfg["base_url"] or MIMO_TOKEN_PLAN_BASE_URL_DEFAULT
        cfg["qwen_region"] = "cn"
        cfg["extra_body"] = _thinking_extra_body("mimo_token_plan", cfg["thinking_enabled"]) if cfg["thinking_enabled"] else {}
    else:
        cfg["api_key_mode"] = "custom"
        cfg["qwen_region"] = "cn"
        cfg["extra_body"] = {}
        cfg["thinking_enabled"] = False
    if not cfg["display_name"] and cfg["model_id"]:
        cfg["display_name"] = cfg["model_id"]
    if not cfg["model_id"]:
        cfg["enabled"] = False
    return cfg


def _default_model_pool_slot(capability: str) -> dict:
    return {
        "mode": "empty",
        "builtin_key": normalize_builtin_model_key("", capability=capability),
        "display_name": "",
        "provider_type": "qwen",
        "model_id": "",
        "base_url": "",
        "qwen_region": "cn",
        "custom_api_key": "",
        "extra_body": {},
        "thinking_enabled": False,
    }


def _legacy_custom_model_to_slot(value, *, capability: str) -> dict:
    custom_model = _normalize_custom_model_config(value)
    slot = _default_model_pool_slot(capability)
    if custom_model.get("enabled") and custom_model.get("model_id"):
        slot.update(
            {
                "mode": "custom",
                "display_name": str(custom_model.get("display_name") or "").strip(),
                "provider_type": str(custom_model.get("provider_type") or "qwen").strip().lower(),
                "model_id": str(custom_model.get("model_id") or "").strip(),
                "base_url": str(custom_model.get("base_url") or "").strip(),
                "qwen_region": str(custom_model.get("qwen_region") or "cn").strip().lower(),
                "custom_api_key": str(custom_model.get("custom_api_key") or "").strip(),
                "extra_body": dict(custom_model.get("extra_body") or {}),
                "thinking_enabled": _coerce_bool(custom_model.get("thinking_enabled"), False),
            }
        )
    return _normalize_model_pool_slot(slot, capability=capability)


def _normalize_model_pool_slot(value, *, capability: str) -> dict:
    source = value if isinstance(value, dict) else {}
    slot = _default_model_pool_slot(capability)
    mode = str(source.get("mode", "empty") or "empty").strip().lower()
    slot["mode"] = mode if mode in MODEL_POOL_MODE_VALUES else "empty"
    slot["builtin_key"] = normalize_builtin_model_key(
        source.get("builtin_key") or source.get("model_key") or slot["builtin_key"],
        capability=capability,
    )
    slot["display_name"] = str(source.get("display_name", "") or "").strip()
    provider_type = str(source.get("provider_type", "qwen") or "qwen").strip().lower()
    slot["provider_type"] = provider_type if provider_type in CUSTOM_MODEL_PROVIDER_TYPES else "qwen"
    slot["model_id"] = str(source.get("model_id", "") or "").strip()
    slot["base_url"] = str(source.get("base_url", "") or "").strip()
    qwen_region = str(source.get("qwen_region", "cn") or "cn").strip().lower()
    slot["qwen_region"] = qwen_region if qwen_region in QWEN_BASE_URLS else "cn"
    slot["custom_api_key"] = str(source.get("custom_api_key", "") or "").strip()
    extra_body = source.get("extra_body")
    slot["extra_body"] = dict(extra_body) if isinstance(extra_body, dict) else {}
    slot["thinking_enabled"] = _coerce_bool(
        source.get("thinking_enabled"),
        _coerce_bool(slot["extra_body"].get("enable_thinking") if isinstance(slot["extra_body"], dict) else None, False),
    )

    if slot["mode"] == "builtin":
        slot["display_name"] = ""
        slot["provider_type"] = "qwen"
        slot["model_id"] = ""
        slot["base_url"] = ""
        slot["qwen_region"] = "cn"
        slot["custom_api_key"] = ""
        slot["extra_body"] = {}
        return slot

    if slot["mode"] == "custom":
        if slot["provider_type"] == "qwen":
            slot["base_url"] = ""
            slot["custom_api_key"] = ""
            slot["extra_body"] = _thinking_extra_body("qwen", slot["thinking_enabled"])
        elif slot["provider_type"] == "qwen_mt":
            slot["base_url"] = ""
            slot["custom_api_key"] = ""
            slot["extra_body"] = {}
            slot["thinking_enabled"] = False
        elif slot["provider_type"] == "deepseek":
            slot["base_url"] = ""
            slot["custom_api_key"] = ""
            slot["qwen_region"] = "cn"
            slot["extra_body"] = _thinking_extra_body("deepseek", True) if slot["thinking_enabled"] else {}
        elif slot["provider_type"] == "glm":
            slot["base_url"] = GLM_BASE_URL
            slot["custom_api_key"] = ""
            slot["qwen_region"] = "cn"
            slot["extra_body"] = _thinking_extra_body("glm", slot["thinking_enabled"])
        elif slot["provider_type"] == "kimi":
            slot["base_url"] = KIMI_BASE_URL
            slot["custom_api_key"] = ""
            slot["qwen_region"] = "cn"
            slot["extra_body"] = _thinking_extra_body("kimi", slot["thinking_enabled"])
        elif slot["provider_type"] == "mimo":
            slot["base_url"] = MIMO_BASE_URL
            slot["custom_api_key"] = ""
            slot["qwen_region"] = "cn"
            slot["extra_body"] = _thinking_extra_body("mimo", slot["thinking_enabled"]) if slot["thinking_enabled"] else {}
        elif slot["provider_type"] == "mimo_token_plan":
            slot["base_url"] = slot["base_url"] or MIMO_TOKEN_PLAN_BASE_URL_DEFAULT
            slot["qwen_region"] = "cn"
            slot["extra_body"] = _thinking_extra_body("mimo_token_plan", slot["thinking_enabled"]) if slot["thinking_enabled"] else {}
        else:
            slot["qwen_region"] = "cn"
            slot["extra_body"] = {}
            slot["thinking_enabled"] = False
        if not slot["display_name"] and slot["model_id"]:
            slot["display_name"] = slot["model_id"]
        if not slot["model_id"]:
            return _default_model_pool_slot(capability)
        return slot

    return _default_model_pool_slot(capability)


def _default_model_pool(capability: str) -> list[dict]:
    builtin_key = (
        ACTIVE_BUILTIN_FNM_MODEL_KEY_DEFAULT
        if capability == "fnm"
        else ACTIVE_BUILTIN_MODEL_KEY_DEFAULT
    )
    primary = _default_model_pool_slot(capability)
    primary["mode"] = "builtin"
    primary["builtin_key"] = normalize_builtin_model_key(builtin_key, capability=capability)
    return [
        primary,
        _default_model_pool_slot(capability),
        _default_model_pool_slot(capability),
    ]


def _normalize_model_pool(value, *, capability: str) -> list[dict]:
    items = list(value) if isinstance(value, list) else []
    normalized = []
    for index in range(MODEL_POOL_SLOT_COUNT):
        source = items[index] if index < len(items) else None
        normalized.append(_normalize_model_pool_slot(source, capability=capability))
    if not normalized:
        return _default_model_pool(capability)
    return normalized


def _migrate_model_pool_config(cfg: dict) -> tuple[dict, bool]:
    changed = False
    normalized = dict(cfg or {})
    if "translation_model_pool" not in normalized:
        if "custom_model" not in normalized and any(
            key in normalized
            for key in ("custom_model_name", "custom_model_enabled", "custom_model_base_key")
        ):
            migrated_legacy, legacy_changed = _migrate_legacy_model_config(normalized)
            for key in ("active_model_mode", "active_builtin_model_key", "custom_model"):
                normalized[key] = migrated_legacy.get(key)
            changed = changed or legacy_changed
        legacy_custom = _normalize_custom_model_config(normalized.get("custom_model"))
        legacy_mode = _normalize_active_model_mode(normalized.get("active_model_mode"))
        if "active_model_mode" not in normalized and legacy_custom.get("enabled"):
            legacy_mode = "custom"
        legacy_builtin = _normalize_builtin_model_key(
            normalized.get("active_builtin_model_key", normalized.get("model_key", ACTIVE_BUILTIN_MODEL_KEY_DEFAULT))
        )
        primary = _default_model_pool_slot("translation")
        if legacy_mode == "custom":
            primary = _legacy_custom_model_to_slot(legacy_custom, capability="translation")
        else:
            primary["mode"] = "builtin"
            primary["builtin_key"] = legacy_builtin
        normalized["translation_model_pool"] = [
            primary,
            _default_model_pool_slot("translation"),
            _default_model_pool_slot("translation"),
        ]
        changed = True
    normalized["translation_model_pool"] = _normalize_model_pool(
        normalized.get("translation_model_pool"),
        capability="translation",
    )

    if "fnm_model_pool" not in normalized:
        legacy_visual_custom = _normalize_custom_model_config(normalized.get("visual_custom_model"))
        legacy_mode = _normalize_active_model_mode(normalized.get("active_visual_model_mode"))
        if "active_visual_model_mode" not in normalized and legacy_visual_custom.get("enabled"):
            legacy_mode = "custom"
        legacy_builtin = normalize_builtin_model_key(
            normalized.get("active_builtin_visual_model_key", ACTIVE_BUILTIN_FNM_MODEL_KEY_DEFAULT),
            capability="fnm",
        )
        primary = _default_model_pool_slot("fnm")
        if legacy_mode == "custom":
            primary = _legacy_custom_model_to_slot(legacy_visual_custom, capability="fnm")
        else:
            primary["mode"] = "builtin"
            primary["builtin_key"] = legacy_builtin
        normalized["fnm_model_pool"] = [
            primary,
            _default_model_pool_slot("fnm"),
            _default_model_pool_slot("fnm"),
        ]
        changed = True
    normalized["fnm_model_pool"] = _normalize_model_pool(
        normalized.get("fnm_model_pool"),
        capability="fnm",
    )

    if "mimo_api_key" not in normalized:
        normalized["mimo_api_key"] = str(normalized.get("mimo_api_key", "") or "").strip()
        changed = True
    else:
        normalized["mimo_api_key"] = str(normalized.get("mimo_api_key", "") or "").strip()
    if "glm_api_key" not in normalized:
        normalized["glm_api_key"] = str(normalized.get("glm_api_key", "") or "").strip()
        changed = True
    else:
        normalized["glm_api_key"] = str(normalized.get("glm_api_key", "") or "").strip()
    if "kimi_api_key" not in normalized:
        normalized["kimi_api_key"] = str(normalized.get("kimi_api_key", "") or "").strip()
        changed = True
    else:
        normalized["kimi_api_key"] = str(normalized.get("kimi_api_key", "") or "").strip()

    for key in list(MODEL_POOL_LEGACY_KEYS):
        if key in normalized:
            normalized.pop(key, None)
            changed = True
    return normalized, changed


def _strip_legacy_model_keys(cfg: dict) -> dict:
    normalized = dict(cfg or {})
    for key in MODEL_POOL_LEGACY_KEYS:
        normalized.pop(key, None)
    return normalized


def _slot_to_legacy_custom_model(slot: dict, *, capability: str) -> dict:
    normalized_slot = _normalize_model_pool_slot(slot, capability=capability)
    if normalized_slot.get("mode") != "custom":
        return _default_custom_model_config()
    provider_type = str(normalized_slot.get("provider_type") or "qwen").strip().lower()
    api_key_mode = "custom"
    if provider_type in {"qwen", "qwen_mt"}:
        api_key_mode = "builtin_dashscope"
    elif provider_type == "deepseek":
        api_key_mode = "builtin_deepseek"
    elif provider_type == "glm":
        api_key_mode = "builtin_glm"
    elif provider_type == "kimi":
        api_key_mode = "builtin_kimi"
    elif provider_type == "mimo":
        api_key_mode = "builtin_mimo"
    return _normalize_custom_model_config(
        {
            "enabled": True,
            "display_name": normalized_slot.get("display_name", ""),
            "provider_type": provider_type,
            "model_id": normalized_slot.get("model_id", ""),
            "base_url": normalized_slot.get("base_url", ""),
            "qwen_region": normalized_slot.get("qwen_region", "cn"),
            "api_key_mode": api_key_mode,
            "custom_api_key": normalized_slot.get("custom_api_key", ""),
            "extra_body": dict(normalized_slot.get("extra_body") or {}),
            "thinking_enabled": _coerce_bool(normalized_slot.get("thinking_enabled"), False),
        }
    )


def _migrate_legacy_model_config(cfg: dict) -> tuple[dict, bool]:
    changed = False
    normalized = dict(cfg or {})
    if "active_builtin_model_key" not in normalized:
        normalized["active_builtin_model_key"] = _normalize_builtin_model_key(
            normalized.get("model_key", ACTIVE_BUILTIN_MODEL_KEY_DEFAULT)
        )
        changed = True
    else:
        normalized["active_builtin_model_key"] = _normalize_builtin_model_key(normalized.get("active_builtin_model_key"))

    if "custom_model" not in normalized:
        legacy_name = str(normalized.get("custom_model_name", CUSTOM_MODEL_NAME_DEFAULT) or "").strip()
        legacy_enabled = _coerce_bool(normalized.get("custom_model_enabled"), CUSTOM_MODEL_ENABLED_DEFAULT)
        legacy_base_key = str(normalized.get("custom_model_base_key", CUSTOM_MODEL_BASE_KEY_DEFAULT) or "").strip()
        provider_type = "qwen"
        if legacy_base_key in MODELS:
            provider_type = MODELS[legacy_base_key].get("provider", "qwen")
        custom_model = _default_custom_model_config()
        custom_model.update({
            "enabled": bool(legacy_name and legacy_enabled),
            "display_name": legacy_name,
            "provider_type": provider_type if provider_type in CUSTOM_MODEL_PROVIDER_TYPES else "qwen",
            "model_id": legacy_name,
            "qwen_region": "cn",
            "api_key_mode": (
                "builtin_dashscope"
                if provider_type in {"qwen", "qwen_mt"}
                else (
                    "builtin_glm"
                    if provider_type == "glm"
                    else (
                        "builtin_kimi"
                        if provider_type == "kimi"
                        else ("builtin_mimo" if provider_type == "mimo" else "builtin_deepseek")
                    )
                )
            ),
        })
        if provider_type == "qwen":
            custom_model["extra_body"] = {"enable_thinking": False}
        elif provider_type == "qwen_mt":
            custom_model["extra_body"] = {}
        normalized["custom_model"] = custom_model
        changed = True
    normalized["custom_model"] = _normalize_custom_model_config(normalized.get("custom_model"))

    if "active_model_mode" not in normalized:
        normalized["active_model_mode"] = "custom" if normalized["custom_model"]["enabled"] else "builtin"
        changed = True
    else:
        normalized["active_model_mode"] = _normalize_active_model_mode(normalized.get("active_model_mode"))

    if normalized["active_model_mode"] == "custom" and not normalized["custom_model"]["enabled"]:
        normalized["active_model_mode"] = "builtin"
        changed = True

    return normalized, changed


def _coerce_int(value, default: int, minimum: int) -> int:
    """将配置值转换为整数，并限制最小值。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _coerce_bool(value, default: bool = False) -> bool:
    """将配置值转换为布尔值。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


def get_pdf_virtual_window_radius() -> int:
    """获取 PDF 卷轴虚拟窗口半径。"""
    cfg = load_config()
    return _coerce_int(
        cfg.get("pdf_virtual_window_radius"),
        PDF_VIRTUAL_WINDOW_RADIUS_DEFAULT,
        1,
    )


def get_pdf_virtual_scroll_min_pages() -> int:
    """获取启用 PDF 虚拟滚动的最小页数阈值。"""
    cfg = load_config()
    return _coerce_int(
        cfg.get("pdf_virtual_scroll_min_pages"),
        PDF_VIRTUAL_SCROLL_MIN_PAGES_DEFAULT,
        1,
    )


def get_translate_parallel_enabled() -> bool:
    """获取段内并发翻译开关。"""
    cfg = load_config()
    return _coerce_bool(
        cfg.get("translate_parallel_enabled"),
        TRANSLATE_PARALLEL_ENABLED_DEFAULT,
    )


def get_translate_parallel_limit() -> int:
    """获取段内并发翻译上限。"""
    cfg = load_config()
    return max(1, min(10, _coerce_int(
        cfg.get("translate_parallel_limit"),
        TRANSLATE_PARALLEL_LIMIT_DEFAULT,
        1,
    )))


def set_translate_parallel_settings(enabled: bool, limit) -> tuple[bool, int]:
    """保存段内并发翻译设置，返回归一化后的值。"""
    normalized_enabled = _coerce_bool(enabled, TRANSLATE_PARALLEL_ENABLED_DEFAULT)
    normalized_limit = max(1, min(10, _coerce_int(
        limit,
        TRANSLATE_PARALLEL_LIMIT_DEFAULT,
        1,
    )))
    cfg = load_config()
    cfg["translate_parallel_enabled"] = normalized_enabled
    cfg["translate_parallel_limit"] = normalized_limit
    save_config(cfg)
    return normalized_enabled, normalized_limit


def check_write_permission() -> tuple[bool, str]:
    """检查是否有写入权限，返回 (是否可写, 错误信息)。"""
    try:
        # 尝试创建 local_data 目录
        os.makedirs(LOCAL_DATA_DIR, exist_ok=True)
        # 尝试写入测试文件
        test_file = os.path.join(LOCAL_DATA_DIR, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True, ""
    except PermissionError:
        return False, f"没有写入权限: {LOCAL_DATA_DIR}\n请将应用安装到用户有权限的目录（如文档文件夹、桌面），或使用管理员权限运行。"
    except Exception as e:
        return False, f"无法访问数据目录: {e}"


def ensure_dirs():
    """确保所有数据目录存在。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)


def get_sqlite_db_path() -> str:
    """返回 SQLite 主库路径。"""
    ensure_dirs()
    return os.path.join(DATA_DIR, "app.db")


def _atomic_write_json(path: str, payload):
    """原子写入 JSON，避免读到半写文件。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _safe_read_json(path: str, default):
    """安全读取 JSON；遇到空文件或损坏内容时返回默认值。"""
    if not os.path.isfile(path):
        if isinstance(default, dict):
            return dict(default)
        if isinstance(default, list):
            return list(default)
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        if isinstance(default, dict):
            return dict(default)
        if isinstance(default, list):
            return list(default)
        return default


def migrate_from_old_location():
    """从旧位置 (~/.foreign_lit_reader/) 迁移数据到新位置。"""
    # 新位置已有配置时，不再重复迁移，避免后续写入被旧配置覆盖。
    if os.path.isfile(CONFIG_FILE):
        return

    if not os.path.isdir(OLD_CONFIG_DIR):
        return  # 无旧数据

    # 检查新位置是否已有数据
    if os.path.isdir(DATA_DIR) and os.listdir(DATA_DIR):
        return  # 新位置已有数据，不迁移

    try:
        import shutil
        # 迁移配置文件
        old_config_file = os.path.join(OLD_CONFIG_DIR, "config.json")
        if os.path.isfile(old_config_file):
            ensure_dirs()
            shutil.copy2(old_config_file, CONFIG_FILE)

        # 迁移数据目录
        old_data_dir = os.path.join(OLD_CONFIG_DIR, "data")
        if os.path.isdir(old_data_dir):
            ensure_dirs()
            for item in os.listdir(old_data_dir):
                src = os.path.join(old_data_dir, item)
                dst = os.path.join(DATA_DIR, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
    except Exception:
        pass  # 迁移失败不影响使用



def _migrate_visual_model_config(cfg: dict) -> tuple[dict, bool]:
    """为自动视觉目录增加独立模型配置；首次迁移时与当前翻译模型对齐。"""
    changed = False
    normalized = dict(cfg or {})
    if "active_visual_model_mode" not in normalized:
        normalized["active_visual_model_mode"] = _normalize_active_model_mode(
            normalized.get("active_model_mode", ACTIVE_MODEL_MODE_DEFAULT)
        )
        changed = True
    else:
        normalized["active_visual_model_mode"] = _normalize_active_model_mode(
            normalized.get("active_visual_model_mode")
        )

    if "active_builtin_visual_model_key" not in normalized:
        normalized["active_builtin_visual_model_key"] = normalize_builtin_model_key(
            normalized.get("active_builtin_model_key"),
            capability="vision",
        )
        changed = True
    else:
        normalized["active_builtin_visual_model_key"] = normalize_builtin_model_key(
            normalized.get("active_builtin_visual_model_key"),
            capability="vision",
        )

    if "visual_custom_model" not in normalized:
        base = normalized.get("custom_model")
        if isinstance(base, dict):
            normalized["visual_custom_model"] = _normalize_custom_model_config(copy.deepcopy(base))
        else:
            normalized["visual_custom_model"] = _default_custom_model_config()
        changed = True
    else:
        normalized["visual_custom_model"] = _normalize_custom_model_config(normalized.get("visual_custom_model"))

    if (
        normalized["active_visual_model_mode"] == "custom"
        and not normalized["visual_custom_model"].get("enabled")
    ):
        normalized["active_visual_model_mode"] = "builtin"
        changed = True

    return normalized, changed



def load_config() -> dict:
    """加载配置，自动迁移旧数据。"""
    # 首次加载时尝试从旧位置迁移
    migrate_from_old_location()
    ensure_dirs()
    cfg = _safe_read_json(CONFIG_FILE, {})
    normalized, changed = _migrate_model_pool_config(cfg)
    if changed or normalized != cfg:
        save_config(normalized)
        return normalized
    return normalized


def save_config(cfg: dict):
    ensure_dirs()
    normalized, _changed = _migrate_model_pool_config(_strip_legacy_model_keys(cfg))
    _atomic_write_json(CONFIG_FILE, normalized)


def _get_config_value(key: str, default=""):
    return load_config().get(key, default)


def _set_config_value(key: str, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)


def get_paddle_token() -> str:
    return _get_config_value("paddle_token", "")


def set_paddle_token(token: str):
    _set_config_value("paddle_token", token)


def get_deepseek_key() -> str:
    return _get_config_value("deepseek_key", "")


def set_deepseek_key(key: str):
    _set_config_value("deepseek_key", key)


def get_dashscope_key() -> str:
    return _get_config_value("dashscope_key", "")


def set_dashscope_key(key: str):
    _set_config_value("dashscope_key", key)


def get_mimo_api_key() -> str:
    return _get_config_value("mimo_api_key", "")


def set_mimo_api_key(key: str):
    _set_config_value("mimo_api_key", key)


def get_glm_api_key() -> str:
    return _get_config_value("glm_api_key", "")


def set_glm_api_key(key: str):
    _set_config_value("glm_api_key", key)


def get_kimi_api_key() -> str:
    return _get_config_value("kimi_api_key", "")


def set_kimi_api_key(key: str):
    _set_config_value("kimi_api_key", key)


def get_translation_model_pool() -> list[dict]:
    cfg = load_config()
    return _normalize_model_pool(cfg.get("translation_model_pool"), capability="translation")


def save_translation_model_pool(pool: list[dict]) -> None:
    cfg = load_config()
    cfg["translation_model_pool"] = _normalize_model_pool(pool, capability="translation")
    save_config(cfg)


def get_fnm_model_pool() -> list[dict]:
    cfg = load_config()
    return _normalize_model_pool(cfg.get("fnm_model_pool"), capability="fnm")


def save_fnm_model_pool(pool: list[dict]) -> None:
    cfg = load_config()
    cfg["fnm_model_pool"] = _normalize_model_pool(pool, capability="fnm")
    save_config(cfg)


def _glossary_state_key(doc_id: str) -> str:
    return f"glossary:{doc_id}"


def get_glossary(doc_id: str = "") -> list:
    target_doc_id = (doc_id or get_current_doc_id() or "").strip()
    if not target_doc_id:
        return list(GLOSSARY_INIT)
    from persistence.sqlite_store import SQLiteRepository

    raw = SQLiteRepository().get_glossary_state(target_doc_id)
    if not raw:
        return list(GLOSSARY_INIT)
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return list(GLOSSARY_INIT)
    if not isinstance(data, list):
        return list(GLOSSARY_INIT)
    normalized = []
    for item in data:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        normalized.append([str(item[0] or ""), str(item[1] or "")])
    return normalized


def set_glossary(glossary: list, doc_id: str = ""):
    target_doc_id = (doc_id or get_current_doc_id() or "").strip()
    if not target_doc_id:
        return
    from persistence.sqlite_store import SQLiteRepository

    normalized = []
    for item in glossary or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        normalized.append([str(item[0] or ""), str(item[1] or "")])
    SQLiteRepository().set_glossary_state(
        target_doc_id,
        json.dumps(normalized, ensure_ascii=False),
    )


def _normalize_glossary_term(term: str) -> str:
    return str(term or "").strip().lower()


def list_glossary_items(doc_id: str = "") -> list[list[str]]:
    items = get_glossary(doc_id) or []
    normalized = []
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        term = str(item[0]).strip()
        defn = str(item[1]).strip()
        if term and defn:
            normalized.append([term, defn])
    return normalized


def upsert_glossary_item(term: str, defn: str, doc_id: str = "") -> tuple[list[list[str]], bool]:
    term = str(term or "").strip()
    defn = str(defn or "").strip()
    if not term or not defn:
        raise ValueError("term/defn 不能为空")

    key = _normalize_glossary_term(term)
    items = list_glossary_items(doc_id)
    updated = False
    for idx, item in enumerate(items):
        if _normalize_glossary_term(item[0]) == key:
            items[idx] = [term, defn]
            updated = True
            break
    if not updated:
        items.append([term, defn])
    set_glossary(items, doc_id=doc_id)
    return items, updated


def delete_glossary_item(term: str, doc_id: str = "") -> tuple[list[list[str]], bool]:
    key = _normalize_glossary_term(term)
    if not key:
        return list_glossary_items(doc_id), False
    items = list_glossary_items(doc_id)
    kept = [item for item in items if _normalize_glossary_term(item[0]) != key]
    deleted = len(kept) != len(items)
    if deleted:
        set_glossary(kept, doc_id=doc_id)
    return kept if deleted else items, deleted


def parse_glossary_file(file_storage) -> list[list[str]]:
    """解析上传的 csv 或 xlsx 文件，返回 [[term, defn], ...] 列表。

    规则：
    - 只取前两列，忽略多余列
    - 跳过空行
    - 如果第一行两列均为非数字纯文字且疑似表头（不含常规术语特征），自动跳过
    - term/defn 均 strip 处理
    """
    import io

    filename = (file_storage.filename or "").lower()
    raw = file_storage.read()

    if filename.endswith(".csv"):
        import csv
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    elif filename.endswith((".xlsx", ".xls")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append([str(c) if c is not None else "" for c in row])
        wb.close()
    else:
        raise ValueError("仅支持 .csv / .xlsx 格式")

    result: list[list[str]] = []
    for i, row in enumerate(rows):
        if len(row) < 2:
            continue
        term = str(row[0] or "").strip()
        defn = str(row[1] or "").strip()
        if not term or not defn:
            continue
        # 跳过首行表头：两列均为纯文字且内容像列名（含"术语""term""译文""translation"等）
        if i == 0:
            combined = (term + defn).lower()
            header_hints = ("term", "术语", "source", "原文", "defn", "译文", "translation", "target", "中文")
            if any(h in combined for h in header_hints):
                continue
        result.append([term, defn])
    return result


def get_active_model_mode() -> str:
    return str(get_translation_model_pool()[0].get("mode") or "empty").strip().lower() or "empty"


def set_active_model_mode(mode: str):
    normalized_mode = str(mode or "").strip().lower()
    pool = get_translation_model_pool()
    slot = dict(pool[0])
    if normalized_mode == "builtin":
        slot = _default_model_pool_slot("translation")
        slot["mode"] = "builtin"
        slot["builtin_key"] = _normalize_builtin_model_key(pool[0].get("builtin_key"))
    elif normalized_mode == "custom" and str(slot.get("model_id") or "").strip():
        slot["mode"] = "custom"
        slot = _normalize_model_pool_slot(slot, capability="translation")
    pool[0] = slot
    save_translation_model_pool(pool)


def get_active_builtin_model_key() -> str:
    slot = get_translation_model_pool()[0]
    return _normalize_builtin_model_key(slot.get("builtin_key"))


def set_active_builtin_model_key(key: str):
    pool = get_translation_model_pool()
    slot = _default_model_pool_slot("translation")
    slot["mode"] = "builtin"
    slot["builtin_key"] = _normalize_builtin_model_key(key)
    pool[0] = slot
    save_translation_model_pool(pool)


def get_custom_model_config() -> dict:
    return _slot_to_legacy_custom_model(get_translation_model_pool()[0], capability="translation")


def save_custom_model_config(custom_model: dict):
    normalized = _normalize_custom_model_config(custom_model)
    pool = get_translation_model_pool()
    if normalized.get("enabled") and normalized.get("model_id"):
        pool[0] = _normalize_model_pool_slot(
            {
                "mode": "custom",
                "display_name": normalized.get("display_name", ""),
                "provider_type": normalized.get("provider_type", "qwen"),
                "model_id": normalized.get("model_id", ""),
                "base_url": normalized.get("base_url", ""),
                "qwen_region": normalized.get("qwen_region", "cn"),
                "custom_api_key": normalized.get("custom_api_key", ""),
                "extra_body": dict(normalized.get("extra_body") or {}),
                "thinking_enabled": _coerce_bool(normalized.get("thinking_enabled"), False),
            },
            capability="translation",
        )
    else:
        pool[0] = _default_model_pool("translation")[0]
    save_translation_model_pool(pool)


def clear_custom_model_config():
    pool = get_translation_model_pool()
    pool[0] = _default_model_pool("translation")[0]
    save_translation_model_pool(pool)


def enable_custom_model():
    pool = get_translation_model_pool()
    slot = dict(pool[0])
    if str(slot.get("model_id") or "").strip():
        slot["mode"] = "custom"
        pool[0] = _normalize_model_pool_slot(slot, capability="translation")
        save_translation_model_pool(pool)


def disable_custom_model():
    pool = get_translation_model_pool()
    slot = _default_model_pool_slot("translation")
    slot["mode"] = "builtin"
    slot["builtin_key"] = _normalize_builtin_model_key(pool[0].get("builtin_key"))
    pool[0] = slot
    save_translation_model_pool(pool)


def get_active_visual_model_mode() -> str:
    return str(get_fnm_model_pool()[0].get("mode") or "empty").strip().lower() or "empty"


def set_active_visual_model_mode(mode: str):
    normalized_mode = str(mode or "").strip().lower()
    pool = get_fnm_model_pool()
    slot = dict(pool[0])
    if normalized_mode == "builtin":
        slot = _default_model_pool_slot("fnm")
        slot["mode"] = "builtin"
        slot["builtin_key"] = normalize_builtin_model_key(pool[0].get("builtin_key"), capability="fnm")
    elif normalized_mode == "custom" and str(slot.get("model_id") or "").strip():
        slot["mode"] = "custom"
        slot = _normalize_model_pool_slot(slot, capability="fnm")
    pool[0] = slot
    save_fnm_model_pool(pool)


def get_active_builtin_visual_model_key() -> str:
    slot = get_fnm_model_pool()[0]
    return normalize_builtin_model_key(slot.get("builtin_key"), capability="fnm")


def set_active_builtin_visual_model_key(key: str):
    pool = get_fnm_model_pool()
    slot = _default_model_pool_slot("fnm")
    slot["mode"] = "builtin"
    slot["builtin_key"] = normalize_builtin_model_key(key, capability="fnm")
    pool[0] = slot
    save_fnm_model_pool(pool)


def get_visual_custom_model_config() -> dict:
    return _slot_to_legacy_custom_model(get_fnm_model_pool()[0], capability="fnm")


def save_visual_custom_model_config(visual_custom_model: dict):
    normalized = _normalize_custom_model_config(visual_custom_model)
    pool = get_fnm_model_pool()
    if normalized.get("enabled") and normalized.get("model_id"):
        pool[0] = _normalize_model_pool_slot(
            {
                "mode": "custom",
                "display_name": normalized.get("display_name", ""),
                "provider_type": normalized.get("provider_type", "qwen"),
                "model_id": normalized.get("model_id", ""),
                "base_url": normalized.get("base_url", ""),
                "qwen_region": normalized.get("qwen_region", "cn"),
                "custom_api_key": normalized.get("custom_api_key", ""),
                "extra_body": dict(normalized.get("extra_body") or {}),
                "thinking_enabled": _coerce_bool(normalized.get("thinking_enabled"), False),
            },
            capability="fnm",
        )
    else:
        pool[0] = _default_model_pool("fnm")[0]
    save_fnm_model_pool(pool)


def clear_visual_custom_model_config():
    pool = get_fnm_model_pool()
    pool[0] = _default_model_pool("fnm")[0]
    save_fnm_model_pool(pool)


def enable_visual_custom_model():
    pool = get_fnm_model_pool()
    slot = dict(pool[0])
    if str(slot.get("model_id") or "").strip():
        slot["mode"] = "custom"
        pool[0] = _normalize_model_pool_slot(slot, capability="fnm")
        save_fnm_model_pool(pool)


def disable_visual_custom_model():
    pool = get_fnm_model_pool()
    slot = _default_model_pool_slot("fnm")
    slot["mode"] = "builtin"
    slot["builtin_key"] = normalize_builtin_model_key(pool[0].get("builtin_key"), capability="fnm")
    pool[0] = slot
    save_fnm_model_pool(pool)


def get_visual_model_key() -> str:
    return get_active_builtin_visual_model_key()


def set_visual_model_key(key: str):
    set_active_builtin_visual_model_key(key)


def get_visual_custom_model_name() -> str:
    cfg = get_visual_custom_model_config()
    return str(cfg.get("display_name") or cfg.get("model_id", "") or "").strip()


def get_visual_custom_model_enabled() -> bool:
    return get_active_visual_model_mode() == "custom"


def get_model_key() -> str:
    return get_active_builtin_model_key()


def set_model_key(key: str):
    set_active_builtin_model_key(key)


def get_custom_model_name() -> str:
    cfg = get_custom_model_config()
    return str(cfg.get("display_name") or cfg.get("model_id", "") or "").strip()


def get_custom_model_enabled() -> bool:
    return get_active_model_mode() == "custom"


def get_custom_model_base_key() -> str:
    return ""


def set_custom_model_name(name: str):
    cfg = get_custom_model_config()
    normalized_name = str(name or "").strip()
    cfg["model_id"] = normalized_name
    cfg["display_name"] = normalized_name
    save_custom_model_config(cfg)


def set_custom_model_enabled(enabled: bool):
    if _coerce_bool(enabled, False):
        enable_custom_model()
    else:
        disable_custom_model()


def set_custom_model_base_key(key: str):
    # 新结构不再依赖基础模型族；保留空实现以兼容旧测试/调用。
    _ = key


def save_custom_model_selection(name: str, enabled: bool, base_key: str):
    """兼容旧入口：按旧结构写入并自动迁移为新结构。"""
    provider_type = MODELS.get(base_key, {}).get("provider", "qwen")
    custom_model = {
        "enabled": bool(str(name or "").strip() and _coerce_bool(enabled, False)),
        "display_name": str(name or "").strip(),
        "provider_type": provider_type if provider_type in CUSTOM_MODEL_PROVIDER_TYPES else "qwen",
        "model_id": str(name or "").strip(),
        "base_url": "",
        "qwen_region": "cn",
        "api_key_mode": (
            "builtin_dashscope"
            if provider_type in {"qwen", "qwen_mt"}
            else (
                "builtin_glm"
                if provider_type == "glm"
                else (
                    "builtin_kimi"
                    if provider_type == "kimi"
                    else ("builtin_mimo" if provider_type == "mimo" else "builtin_deepseek")
                )
            )
        ),
        "custom_api_key": "",
        "extra_body": {"enable_thinking": False} if provider_type == "qwen" else {},
        "thinking_enabled": False,
    }
    save_custom_model_config(custom_model)


# ============ 多文档管理 ============

def create_doc(
    name: str,
    *,
    cleanup_headers_footers: bool = DOC_CLEANUP_HEADERS_FOOTERS_DEFAULT,
    auto_visual_toc_enabled: bool = DOC_AUTO_VISUAL_TOC_DEFAULT,
) -> str:
    """创建新文档目录，返回 doc_id。"""
    ensure_dirs()
    from persistence.sqlite_store import SQLiteRepository

    doc_id = _uuid.uuid4().hex[:12]
    doc_dir = os.path.join(DOCS_DIR, doc_id)
    os.makedirs(doc_dir, exist_ok=True)
    now = int(time.time())
    SQLiteRepository().upsert_document(
        doc_id,
        name,
        created_at=now,
        updated_at=now,
        page_count=0,
        entry_count=0,
        last_entry_idx=0,
        has_pdf=0,
        status="ready",
        cleanup_headers_footers=cleanup_headers_footers,
        auto_visual_toc_enabled=auto_visual_toc_enabled,
        toc_visual_status="idle",
        toc_visual_message="",
        toc_visual_model_id="",
    )
    set_current_doc(doc_id)
    return doc_id


def get_current_doc_id() -> str:
    """返回当前活跃文档 ID，无则返回空字符串。"""
    from persistence.sqlite_store import SQLiteRepository

    doc_id = normalize_doc_id(SQLiteRepository().get_app_state("current_doc_id"))
    if doc_id and os.path.isdir(os.path.join(DOCS_DIR, doc_id)):
        return doc_id
    return ""


def set_current_doc(doc_id: str):
    """设置当前活跃文档。"""
    ensure_dirs()
    from persistence.sqlite_store import SQLiteRepository

    normalized_doc_id = normalize_doc_id(doc_id)
    if not normalized_doc_id:
        return
    if not os.path.isdir(os.path.join(DOCS_DIR, normalized_doc_id)):
        return
    SQLiteRepository().set_app_state("current_doc_id", normalized_doc_id)


def get_doc_dir(doc_id: str = "") -> str:
    """获取文档目录路径。无 doc_id 时使用当前文档。"""
    if not doc_id:
        doc_id = get_current_doc_id()
    if not doc_id:
        return ""
    return os.path.join(DOCS_DIR, doc_id)


def list_docs() -> list[dict]:
    """列出所有文档的元数据，按创建时间倒序。"""
    ensure_dirs()
    from persistence.sqlite_store import SQLiteRepository

    docs = SQLiteRepository().list_documents()
    for meta in docs:
        doc_id = meta.get("id", "")
        meta["has_pdf"] = os.path.isfile(os.path.join(DOCS_DIR, doc_id, "source.pdf"))
    return docs


def update_doc_meta(doc_id: str, **kwargs):
    """更新文档元数据字段。"""
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return
    from persistence.sqlite_store import SQLiteRepository

    meta = get_doc_meta(doc_id)
    if not meta:
        meta = {"id": doc_id, "name": kwargs.get("name", "")}
    meta.update(kwargs)
    SQLiteRepository().upsert_document(
        doc_id,
        meta.get("name", ""),
        created_at=int(meta.get("created", time.time()) or time.time()),
        updated_at=int(time.time()),
        page_count=int(meta.get("page_count", 0) or 0),
        entry_count=int(meta.get("entry_count", 0) or 0),
        has_pdf=int(meta.get("has_pdf", 0) or 0),
        last_entry_idx=int(meta.get("last_entry_idx", 0) or 0),
        status=meta.get("status", "ready"),
        source_pdf_path=meta.get("source_pdf_path"),
        cleanup_headers_footers=_coerce_bool(
            meta.get("cleanup_headers_footers"),
            DOC_CLEANUP_HEADERS_FOOTERS_DEFAULT,
        ),
        auto_visual_toc_enabled=_coerce_bool(
            meta.get("auto_visual_toc_enabled"),
            DOC_AUTO_VISUAL_TOC_DEFAULT,
        ),
        toc_visual_status=str(meta.get("toc_visual_status", "idle") or "idle").strip() or "idle",
        toc_visual_message=str(meta.get("toc_visual_message", "") or ""),
        toc_visual_model_id=str(meta.get("toc_visual_model_id", "") or ""),
        toc_visual_phase=str(meta.get("toc_visual_phase", "") or ""),
        toc_visual_progress_pct=int(meta.get("toc_visual_progress_pct", 0) or 0),
        toc_visual_progress_label=str(meta.get("toc_visual_progress_label", "") or ""),
        toc_visual_progress_detail=str(meta.get("toc_visual_progress_detail", "") or ""),
    )


def get_doc_meta(doc_id: str = "") -> dict:
    """读取指定文档元数据。"""
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return {}
    from persistence.sqlite_store import SQLiteRepository

    meta = SQLiteRepository().get_document(doc_id)
    return meta if isinstance(meta, dict) else {}


def get_doc_cleanup_headers_footers(
    doc_id: str = "",
    default: bool = DOC_CLEANUP_HEADERS_FOOTERS_DEFAULT,
) -> bool:
    """返回文档的页眉页脚清理模式。"""
    meta = get_doc_meta(doc_id)
    if not meta:
        return bool(default)
    return _coerce_bool(meta.get("cleanup_headers_footers"), default)


def get_doc_auto_visual_toc_enabled(
    doc_id: str = "",
    default: bool = DOC_AUTO_VISUAL_TOC_DEFAULT,
) -> bool:
    """返回文档是否启用自动视觉目录。"""
    meta = get_doc_meta(doc_id)
    if not meta:
        return bool(default)
    return _coerce_bool(meta.get("auto_visual_toc_enabled"), default)


def get_upload_cleanup_headers_footers_enabled(
    default: bool = UPLOAD_CLEANUP_HEADERS_FOOTERS_DEFAULT,
) -> bool:
    """返回首页上传时的页眉页脚清理默认勾选。"""
    return _coerce_bool(_get_config_value(UPLOAD_CLEANUP_HEADERS_FOOTERS_KEY, default), default)


def get_upload_auto_visual_toc_enabled(
    default: bool = UPLOAD_AUTO_VISUAL_TOC_DEFAULT,
) -> bool:
    """返回首页上传时的自动视觉目录默认勾选。"""
    return _coerce_bool(_get_config_value(UPLOAD_AUTO_VISUAL_TOC_KEY, default), default)


def set_upload_processing_preferences(
    *,
    cleanup_headers_footers: bool,
    auto_visual_toc: bool,
) -> None:
    """持久化首页上传区的两个勾选项。"""
    cfg = load_config()
    cfg[UPLOAD_CLEANUP_HEADERS_FOOTERS_KEY] = bool(cleanup_headers_footers)
    cfg[UPLOAD_AUTO_VISUAL_TOC_KEY] = bool(auto_visual_toc)
    save_config(cfg)


def delete_doc(doc_id: str):
    """删除文档目录。"""
    import shutil
    from persistence.sqlite_store import SQLiteRepository

    is_current = get_current_doc_id() == doc_id
    doc_dir = os.path.join(DOCS_DIR, doc_id)

    # 先做数据库清理（此时 doc.db 仍在原路径，级联删除可正常执行）
    SQLiteRepository().delete_document(doc_id)

    # 如果删除的是当前文档，清除 current
    if is_current:
        SQLiteRepository().set_app_state("current_doc_id", "")

    # 再做文件系统清理：重命名后交给后台线程删除
    if os.path.isdir(doc_dir):
        cleanup_dir = os.path.join(DOCS_DIR, f".deleting-{doc_id}-{int(time.time() * 1000)}")
        renamed = False
        try:
            os.replace(doc_dir, cleanup_dir)
            renamed = True
        except OSError:
            cleanup_dir = doc_dir

        if renamed:
            def _cleanup_worker(path: str):
                try:
                    shutil.rmtree(path)
                except Exception:
                    logger.exception("后台清理文档目录失败 path=%s", path)

            thread = threading.Thread(
                target=_cleanup_worker,
                args=(cleanup_dir,),
                daemon=True,
                name=f"doc-delete-{doc_id}",
            )
            thread.start()
        elif os.path.isdir(cleanup_dir):
            shutil.rmtree(cleanup_dir)

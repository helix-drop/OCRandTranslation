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
PDF_VIRTUAL_WINDOW_RADIUS_DEFAULT = 5
PDF_VIRTUAL_SCROLL_MIN_PAGES_DEFAULT = 80
TRANSLATE_PARALLEL_ENABLED_DEFAULT = False
TRANSLATE_PARALLEL_LIMIT_DEFAULT = 10
ACTIVE_MODEL_MODE_DEFAULT = "builtin"
ACTIVE_BUILTIN_MODEL_KEY_DEFAULT = "deepseek-chat"
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
CUSTOM_MODEL_PROVIDER_TYPES = {"qwen", "qwen_mt", "deepseek", "openai_compatible"}
CUSTOM_MODEL_API_KEY_MODES = {"builtin_dashscope", "builtin_deepseek", "custom"}

logger = logging.getLogger(__name__)


def _default_custom_model_config() -> dict:
    return dict(CUSTOM_MODEL_DEFAULT)


def _normalize_builtin_model_key(key) -> str:
    return normalize_builtin_model_key(str(key or "").strip(), capability="translation")


def _normalize_active_model_mode(value) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"builtin", "custom"} else ACTIVE_MODEL_MODE_DEFAULT


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

    if cfg["provider_type"] == "qwen":
        cfg["api_key_mode"] = "builtin_dashscope"
        if "enable_thinking" not in cfg["extra_body"]:
            cfg["extra_body"]["enable_thinking"] = False
        cfg["base_url"] = ""
        cfg["custom_api_key"] = ""
    elif cfg["provider_type"] == "qwen_mt":
        cfg["api_key_mode"] = "builtin_dashscope"
        cfg["base_url"] = ""
        cfg["custom_api_key"] = ""
        cfg["extra_body"] = {}
    elif cfg["provider_type"] == "deepseek":
        cfg["api_key_mode"] = "builtin_deepseek"
        cfg["base_url"] = ""
        cfg["custom_api_key"] = ""
        cfg["qwen_region"] = "cn"
        cfg["extra_body"] = {}
    else:
        cfg["api_key_mode"] = "custom"
        cfg["qwen_region"] = "cn"
        cfg["extra_body"] = {}
    if not cfg["display_name"] and cfg["model_id"]:
        cfg["display_name"] = cfg["model_id"]
    if not cfg["model_id"]:
        cfg["enabled"] = False
    return cfg


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
            "provider_type": provider_type if provider_type in {"qwen", "qwen_mt", "deepseek"} else "qwen",
            "model_id": legacy_name,
            "qwen_region": "cn",
            "api_key_mode": "builtin_dashscope" if provider_type in {"qwen", "qwen_mt"} else "builtin_deepseek",
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
    normalized, changed = _migrate_legacy_model_config(cfg)
    normalized, v_changed = _migrate_visual_model_config(normalized)
    changed = changed or v_changed
    if changed or normalized != cfg:
        save_config(normalized)
        return normalized
    return normalized


def save_config(cfg: dict):
    ensure_dirs()
    normalized, _changed = _migrate_legacy_model_config(cfg)
    normalized, _v_changed = _migrate_visual_model_config(normalized)
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
    cfg = load_config()
    return _normalize_active_model_mode(cfg.get("active_model_mode"))


def set_active_model_mode(mode: str):
    cfg = load_config()
    cfg["active_model_mode"] = _normalize_active_model_mode(mode)
    save_config(cfg)


def get_active_builtin_model_key() -> str:
    cfg = load_config()
    return _normalize_builtin_model_key(cfg.get("active_builtin_model_key"))


def set_active_builtin_model_key(key: str):
    cfg = load_config()
    cfg["active_builtin_model_key"] = _normalize_builtin_model_key(key)
    save_config(cfg)


def get_custom_model_config() -> dict:
    cfg = load_config()
    return _normalize_custom_model_config(cfg.get("custom_model"))


def save_custom_model_config(custom_model: dict):
    cfg = load_config()
    cfg["custom_model"] = _normalize_custom_model_config(custom_model)
    save_config(cfg)


def clear_custom_model_config():
    cfg = load_config()
    cfg["custom_model"] = _default_custom_model_config()
    if _normalize_active_model_mode(cfg.get("active_model_mode")) == "custom":
        cfg["active_model_mode"] = "builtin"
    save_config(cfg)


def enable_custom_model():
    cfg = load_config()
    custom_model = _normalize_custom_model_config(cfg.get("custom_model"))
    if custom_model.get("enabled") and custom_model.get("model_id"):
        cfg["active_model_mode"] = "custom"
    save_config(cfg)


def disable_custom_model():
    cfg = load_config()
    cfg["active_model_mode"] = "builtin"
    save_config(cfg)


def get_active_visual_model_mode() -> str:
    cfg = load_config()
    return _normalize_active_model_mode(cfg.get("active_visual_model_mode"))


def set_active_visual_model_mode(mode: str):
    cfg = load_config()
    cfg["active_visual_model_mode"] = _normalize_active_model_mode(mode)
    save_config(cfg)


def get_active_builtin_visual_model_key() -> str:
    cfg = load_config()
    return normalize_builtin_model_key(cfg.get("active_builtin_visual_model_key"), capability="vision")


def set_active_builtin_visual_model_key(key: str):
    cfg = load_config()
    cfg["active_builtin_visual_model_key"] = normalize_builtin_model_key(key, capability="vision")
    save_config(cfg)


def get_visual_custom_model_config() -> dict:
    cfg = load_config()
    return _normalize_custom_model_config(cfg.get("visual_custom_model"))


def save_visual_custom_model_config(visual_custom_model: dict):
    cfg = load_config()
    cfg["visual_custom_model"] = _normalize_custom_model_config(visual_custom_model)
    save_config(cfg)


def clear_visual_custom_model_config():
    cfg = load_config()
    cfg["visual_custom_model"] = _default_custom_model_config()
    if _normalize_active_model_mode(cfg.get("active_visual_model_mode")) == "custom":
        cfg["active_visual_model_mode"] = "builtin"
    save_config(cfg)


def enable_visual_custom_model():
    cfg = load_config()
    vcm = _normalize_custom_model_config(cfg.get("visual_custom_model"))
    if vcm.get("enabled") and vcm.get("model_id"):
        cfg["active_visual_model_mode"] = "custom"
    save_config(cfg)


def disable_visual_custom_model():
    cfg = load_config()
    cfg["active_visual_model_mode"] = "builtin"
    save_config(cfg)


def get_visual_model_key() -> str:
    return get_active_builtin_visual_model_key()


def set_visual_model_key(key: str):
    set_active_builtin_visual_model_key(key)


def get_visual_custom_model_name() -> str:
    return str(get_visual_custom_model_config().get("model_id", "") or "").strip()


def get_visual_custom_model_enabled() -> bool:
    return get_active_visual_model_mode() == "custom"


def get_model_key() -> str:
    return get_active_builtin_model_key()


def set_model_key(key: str):
    set_active_builtin_model_key(key)


def get_custom_model_name() -> str:
    return str(get_custom_model_config().get("model_id", "") or "").strip()


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
        "provider_type": provider_type if provider_type in {"qwen", "qwen_mt", "deepseek"} else "qwen",
        "model_id": str(name or "").strip(),
        "base_url": "",
        "qwen_region": "cn",
        "api_key_mode": "builtin_dashscope" if provider_type in {"qwen", "qwen_mt"} else "builtin_deepseek",
        "custom_api_key": "",
        "extra_body": {"enable_thinking": False} if provider_type == "qwen" else {},
    }
    cfg = load_config()
    cfg["custom_model"] = custom_model
    cfg["active_model_mode"] = "custom" if custom_model["enabled"] else "builtin"
    save_config(cfg)


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


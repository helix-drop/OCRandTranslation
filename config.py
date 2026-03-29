"""本地配置存储：API令牌、术语表、用户偏好、多文档管理。

数据存储路径：项目目录下的 local_data/user_data/
便于应用分发和便携使用。
"""
import json
import os
import tempfile
import time
import uuid as _uuid

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
CUSTOM_MODEL_NAME_DEFAULT = ""
CUSTOM_MODEL_ENABLED_DEFAULT = False
CUSTOM_MODEL_BASE_KEY_DEFAULT = ""

MODELS = {
    "deepseek-chat": {"id": "deepseek-chat", "label": "DeepSeek-Chat", "provider": "deepseek"},
    "deepseek-reasoner": {"id": "deepseek-reasoner", "label": "DeepSeek-Reasoner", "provider": "deepseek"},
    "qwen-plus": {"id": "qwen-plus", "label": "Qwen-Plus", "provider": "qwen"},
    "qwen-max": {"id": "qwen-max", "label": "Qwen-Max", "provider": "qwen"},
    "qwen-turbo": {"id": "qwen-turbo", "label": "Qwen-Turbo", "provider": "qwen"},
}


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


def load_config() -> dict:
    """加载配置，自动迁移旧数据。"""
    # 首次加载时尝试从旧位置迁移
    migrate_from_old_location()
    ensure_dirs()
    return _safe_read_json(CONFIG_FILE, {})


def save_config(cfg: dict):
    ensure_dirs()
    _atomic_write_json(CONFIG_FILE, cfg)


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
    from sqlite_store import SQLiteRepository

    raw = SQLiteRepository().get_app_state(_glossary_state_key(target_doc_id))
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
    from sqlite_store import SQLiteRepository

    normalized = []
    for item in glossary or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        normalized.append([str(item[0] or ""), str(item[1] or "")])
    SQLiteRepository().set_app_state(
        _glossary_state_key(target_doc_id),
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


def get_model_key() -> str:
    key = _get_config_value("model_key", "deepseek-chat")
    return key if key in MODELS else "deepseek-chat"


def set_model_key(key: str):
    _set_config_value("model_key", key)


def get_custom_model_name() -> str:
    """获取用户自定义模型名。"""
    value = _get_config_value("custom_model_name", CUSTOM_MODEL_NAME_DEFAULT)
    return str(value or "").strip()


def get_custom_model_enabled() -> bool:
    """获取用户是否启用了自定义模型。"""
    cfg = load_config()
    return _coerce_bool(
        cfg.get("custom_model_enabled"),
        CUSTOM_MODEL_ENABLED_DEFAULT,
    )


def get_custom_model_base_key() -> str:
    """获取自定义模型绑定的预设模型 key。"""
    value = str(_get_config_value("custom_model_base_key", CUSTOM_MODEL_BASE_KEY_DEFAULT) or "").strip()
    return value if value in MODELS else ""


def set_custom_model_name(name: str):
    _set_config_value("custom_model_name", str(name or "").strip())


def set_custom_model_enabled(enabled: bool):
    _set_config_value("custom_model_enabled", _coerce_bool(enabled, CUSTOM_MODEL_ENABLED_DEFAULT))


def set_custom_model_base_key(key: str):
    _set_config_value("custom_model_base_key", key if key in MODELS else "")


def save_custom_model_selection(name: str, enabled: bool, base_key: str):
    """统一保存自定义模型的名称、启用状态和绑定模型族。"""
    normalized_name = str(name or "").strip()
    normalized_base_key = base_key if base_key in MODELS else ""
    normalized_enabled = bool(
        normalized_name
        and normalized_base_key
        and _coerce_bool(enabled, CUSTOM_MODEL_ENABLED_DEFAULT)
    )
    cfg = load_config()
    cfg["custom_model_name"] = normalized_name
    cfg["custom_model_enabled"] = normalized_enabled
    cfg["custom_model_base_key"] = normalized_base_key
    save_config(cfg)


# ============ 多文档管理 ============

def create_doc(name: str) -> str:
    """创建新文档目录，返回 doc_id。"""
    ensure_dirs()
    from sqlite_store import SQLiteRepository

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
    )
    set_current_doc(doc_id)
    return doc_id


def get_current_doc_id() -> str:
    """返回当前活跃文档 ID，无则返回空字符串。"""
    from sqlite_store import SQLiteRepository

    doc_id = (SQLiteRepository().get_app_state("current_doc_id") or "").strip()
    if doc_id and os.path.isdir(os.path.join(DOCS_DIR, doc_id)):
        return doc_id
    return ""


def set_current_doc(doc_id: str):
    """设置当前活跃文档。"""
    ensure_dirs()
    from sqlite_store import SQLiteRepository

    SQLiteRepository().set_app_state("current_doc_id", doc_id)


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
    from sqlite_store import SQLiteRepository

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
    from sqlite_store import SQLiteRepository

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
    )


def get_doc_meta(doc_id: str = "") -> dict:
    """读取指定文档元数据。"""
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return {}
    from sqlite_store import SQLiteRepository

    meta = SQLiteRepository().get_document(doc_id)
    return meta if isinstance(meta, dict) else {}


def delete_doc(doc_id: str):
    """删除文档目录。"""
    import shutil
    from sqlite_store import SQLiteRepository

    is_current = get_current_doc_id() == doc_id
    doc_dir = os.path.join(DOCS_DIR, doc_id)
    if os.path.isdir(doc_dir):
        shutil.rmtree(doc_dir)
    SQLiteRepository().delete_document(doc_id)
    # 如果删除的是当前文档，清除 current
    if is_current:
        SQLiteRepository().set_app_state("current_doc_id", "")

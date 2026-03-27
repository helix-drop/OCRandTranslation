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
PARA_MAX_CONCURRENCY = 3
PARA_CONTEXT_WINDOW = 200
PDF_VIRTUAL_WINDOW_RADIUS_DEFAULT = 5
PDF_VIRTUAL_SCROLL_MIN_PAGES_DEFAULT = 80

MODELS = {
    "sonnet": {"id": "claude-sonnet-4-6", "label": "Sonnet 4.6", "provider": "anthropic"},
    "opus": {"id": "claude-opus-4-6", "label": "Opus 4.6", "provider": "anthropic"},
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


def get_paddle_token() -> str:
    return load_config().get("paddle_token", "")


def set_paddle_token(token: str):
    cfg = load_config()
    cfg["paddle_token"] = token
    save_config(cfg)


def get_anthropic_key() -> str:
    return load_config().get("anthropic_key", "")


def set_anthropic_key(key: str):
    cfg = load_config()
    cfg["anthropic_key"] = key
    save_config(cfg)


def get_dashscope_key() -> str:
    return load_config().get("dashscope_key", "")


def set_dashscope_key(key: str):
    cfg = load_config()
    cfg["dashscope_key"] = key
    save_config(cfg)


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


def get_model_key() -> str:
    return load_config().get("model_key", "sonnet")


def set_model_key(key: str):
    cfg = load_config()
    cfg["model_key"] = key
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



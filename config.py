"""本地配置存储：API令牌、术语表、用户偏好、多文档管理。"""
import json
import os
import time
import uuid as _uuid

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".foreign_lit_reader")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DATA_DIR = os.path.join(CONFIG_DIR, "data")
DOCS_DIR = os.path.join(DATA_DIR, "documents")
CURRENT_FILE = os.path.join(DATA_DIR, "current.txt")

GLOSSARY_INIT = []

MODELS = {
    "sonnet": {"id": "claude-sonnet-4-6", "label": "Sonnet 4.6", "provider": "anthropic"},
    "opus": {"id": "claude-opus-4-6", "label": "Opus 4.6", "provider": "anthropic"},
    "qwen-plus": {"id": "qwen-plus", "label": "Qwen-Plus", "provider": "qwen"},
    "qwen-max": {"id": "qwen-max", "label": "Qwen-Max", "provider": "qwen"},
    "qwen-turbo": {"id": "qwen-turbo", "label": "Qwen-Turbo", "provider": "qwen"},
}


def ensure_dirs():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)


def load_config() -> dict:
    ensure_dirs()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg: dict):
    ensure_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


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


def get_glossary() -> list:
    cfg = load_config()
    return cfg.get("glossary", GLOSSARY_INIT)


def set_glossary(glossary: list):
    cfg = load_config()
    cfg["glossary"] = glossary
    save_config(cfg)


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
    doc_id = _uuid.uuid4().hex[:12]
    doc_dir = os.path.join(DOCS_DIR, doc_id)
    os.makedirs(doc_dir, exist_ok=True)
    meta = {
        "id": doc_id,
        "name": name,
        "created": time.time(),
        "page_count": 0,
        "entry_count": 0,
    }
    with open(os.path.join(doc_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    set_current_doc(doc_id)
    return doc_id


def get_current_doc_id() -> str:
    """返回当前活跃文档 ID，无则返回空字符串。"""
    if os.path.exists(CURRENT_FILE):
        with open(CURRENT_FILE, "r") as f:
            doc_id = f.read().strip()
        if doc_id and os.path.isdir(os.path.join(DOCS_DIR, doc_id)):
            return doc_id
    return ""


def set_current_doc(doc_id: str):
    """设置当前活跃文档。"""
    ensure_dirs()
    with open(CURRENT_FILE, "w") as f:
        f.write(doc_id)


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
    docs = []
    if not os.path.isdir(DOCS_DIR):
        return docs
    for name in os.listdir(DOCS_DIR):
        meta_path = os.path.join(DOCS_DIR, name, "meta.json")
        if os.path.isfile(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["id"] = name  # 确保 id 一致
            meta["has_pdf"] = os.path.isfile(os.path.join(DOCS_DIR, name, "source.pdf"))
            docs.append(meta)
    docs.sort(key=lambda d: d.get("created", 0), reverse=True)
    return docs


def update_doc_meta(doc_id: str, **kwargs):
    """更新文档元数据字段。"""
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return
    meta_path = os.path.join(doc_dir, "meta.json")
    if os.path.isfile(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    else:
        meta = {"id": doc_id}
    meta.update(kwargs)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def get_doc_meta(doc_id: str = "") -> dict:
    """读取指定文档元数据。"""
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return {}
    meta_path = os.path.join(doc_dir, "meta.json")
    if not os.path.isfile(meta_path):
        return {}
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_doc(doc_id: str):
    """删除文档目录。"""
    import shutil
    doc_dir = os.path.join(DOCS_DIR, doc_id)
    if os.path.isdir(doc_dir):
        shutil.rmtree(doc_dir)
    # 如果删除的是当前文档，清除 current
    if get_current_doc_id() == doc_id:
        if os.path.exists(CURRENT_FILE):
            os.remove(CURRENT_FILE)


def migrate_legacy_data():
    """将旧的单文件数据迁移到多文档结构。"""
    ensure_dirs()
    old_pages = os.path.join(DATA_DIR, "pages.json")
    if not os.path.isfile(old_pages):
        return  # 无旧数据

    # 读取旧数据获取名称
    with open(old_pages, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        name = "迁移数据"
        pages = data
    else:
        name = data.get("name", "迁移数据")
        pages = data.get("pages", [])

    if not pages:
        os.remove(old_pages)
        return

    # 创建新文档
    doc_id = create_doc(name)
    doc_dir = get_doc_dir(doc_id)

    # 移动文件
    import shutil
    shutil.move(old_pages, os.path.join(doc_dir, "pages.json"))

    old_entries = os.path.join(DATA_DIR, "entries.json")
    if os.path.isfile(old_entries):
        shutil.move(old_entries, os.path.join(doc_dir, "entries.json"))

    old_pdf = os.path.join(DATA_DIR, "source.pdf")
    if os.path.isfile(old_pdf):
        shutil.move(old_pdf, os.path.join(doc_dir, "source.pdf"))

    # 更新元数据
    update_doc_meta(doc_id, page_count=len(pages))

"""磁盘持久化与辅助函数：数据读写、模板变量、文本处理工具。"""
import json
import os
import re
import shutil

from config import (
    MODELS,
    get_paddle_token, get_anthropic_key, get_dashscope_key,
    get_glossary, get_model_key,
    get_current_doc_id, get_doc_dir, get_doc_meta, update_doc_meta,
)
from text_processing import get_page_range


# ============ DISK PERSISTENCE (多文档) ============

def _doc_path(filename: str, doc_id: str = "") -> str:
    """获取当前文档目录下的文件路径。"""
    d = get_doc_dir(doc_id)
    if not d:
        return ""
    return os.path.join(d, filename)


def _entries_root(doc_id: str = "") -> str:
    return _doc_path("entries", doc_id)


def _entries_meta_path(doc_id: str = "") -> str:
    root = _entries_root(doc_id)
    return os.path.join(root, "meta.json") if root else ""


def _entries_pages_dir(doc_id: str = "") -> str:
    root = _entries_root(doc_id)
    return os.path.join(root, "pages") if root else ""


def _entry_page_path(bp: int, doc_id: str = "") -> str:
    pages_dir = _entries_pages_dir(doc_id)
    if not pages_dir or bp is None:
        return ""
    return os.path.join(pages_dir, f"{int(bp):06d}.json")


def _write_json(path: str, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _load_entries_meta(doc_id: str = "") -> dict:
    meta_path = _entries_meta_path(doc_id)
    if meta_path and os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {
                    "title": data.get("title", ""),
                    "idx": int(data.get("idx", 0) or 0),
                }
    return {"title": "", "idx": 0}


def _list_entry_page_paths(doc_id: str = "") -> list[str]:
    pages_dir = _entries_pages_dir(doc_id)
    if not pages_dir or not os.path.isdir(pages_dir):
        return []
    return sorted(
        os.path.join(pages_dir, name)
        for name in os.listdir(pages_dir)
        if name.endswith(".json")
    )


def _remove_legacy_entries_file(doc_id: str = ""):
    legacy_path = _doc_path("entries.json", doc_id)
    if legacy_path and os.path.exists(legacy_path):
        os.remove(legacy_path)


def save_pages_to_disk(pages: list, name: str, doc_id: str = ""):
    path = _doc_path("pages.json", doc_id)
    if not path:
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"name": name, "pages": pages}, f, ensure_ascii=False)
    update_doc_meta(doc_id or get_current_doc_id(), page_count=len(pages), name=name)


def load_pages_from_disk(doc_id: str = "") -> tuple[list, str]:
    path = _doc_path("pages.json", doc_id)
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data, ""
            return data.get("pages", []), data.get("name", "")
    return [], ""


def save_entries_to_disk(entries: list, title: str, idx: int, doc_id: str = ""):
    root = _entries_root(doc_id)
    pages_dir = _entries_pages_dir(doc_id)
    meta_path = _entries_meta_path(doc_id)
    if not root or not pages_dir or not meta_path:
        return
    os.makedirs(pages_dir, exist_ok=True)
    for page_path in _list_entry_page_paths(doc_id):
        os.remove(page_path)
    for entry in entries:
        bp = entry.get("_pageBP")
        if bp is None:
            continue
        _write_json(_entry_page_path(bp, doc_id), entry)
    _write_json(meta_path, {"title": title, "idx": idx})
    _remove_legacy_entries_file(doc_id)
    update_doc_meta(doc_id or get_current_doc_id(), entry_count=len(entries), last_entry_idx=idx)


def save_entry_cursor(idx: int, doc_id: str = ""):
    """仅保存当前阅读位置，不重写整份翻译结果。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    meta = _load_entries_meta(target_doc_id)
    meta["idx"] = idx
    meta_path = _entries_meta_path(target_doc_id)
    root = _entries_root(target_doc_id)
    if meta_path and root:
        os.makedirs(root, exist_ok=True)
        _write_json(meta_path, meta)
    update_doc_meta(target_doc_id, last_entry_idx=idx)


def load_entries_from_disk(doc_id: str = "") -> tuple[list, str, int]:
    entries = []
    for page_path in _list_entry_page_paths(doc_id):
        with open(page_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
            if isinstance(payload, dict):
                entries.append(payload)
    entries.sort(key=lambda entry: entry.get("_pageBP") or 0)
    meta = _load_entries_meta(doc_id)
    return entries, meta.get("title", ""), meta.get("idx", 0)


def save_entry_to_disk(entry: dict, title: str, doc_id: str = "") -> int:
    target_doc_id = doc_id or get_current_doc_id()
    bp = entry.get("_pageBP")
    page_path = _entry_page_path(bp, target_doc_id)
    pages_dir = _entries_pages_dir(target_doc_id)
    root = _entries_root(target_doc_id)
    if not target_doc_id or not page_path or not pages_dir or not root:
        return 0

    os.makedirs(pages_dir, exist_ok=True)
    _write_json(page_path, entry)

    page_paths = _list_entry_page_paths(target_doc_id)
    page_bps = [int(os.path.splitext(os.path.basename(path))[0]) for path in page_paths]
    idx = page_bps.index(int(bp)) if bp is not None and int(bp) in page_bps else max(0, len(page_paths) - 1)
    meta = _load_entries_meta(target_doc_id)
    meta["title"] = meta.get("title") or title
    meta["idx"] = idx
    _write_json(_entries_meta_path(target_doc_id), meta)
    _remove_legacy_entries_file(target_doc_id)
    update_doc_meta(target_doc_id, entry_count=len(page_paths), last_entry_idx=idx)
    return idx


def clear_entries_from_disk(doc_id: str = ""):
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    root = _entries_root(target_doc_id)
    if root and os.path.isdir(root):
        shutil.rmtree(root)
    _remove_legacy_entries_file(target_doc_id)
    update_doc_meta(target_doc_id, entry_count=0, last_entry_idx=0)


def has_pdf(doc_id: str = "") -> bool:
    """检查当前文档是否有保存的 PDF 文件供预览。"""
    path = _doc_path("source.pdf", doc_id)
    return bool(path) and os.path.exists(path)


def get_pdf_path(doc_id: str = "") -> str:
    """获取 PDF 文件路径。"""
    return _doc_path("source.pdf", doc_id)


# ============ HELPERS ============

def get_translate_args(model_key: str) -> dict:
    """根据模型key返回 translate_paragraph 所需的 model_id, api_key, provider。"""
    model = MODELS[model_key]
    provider = model.get("provider", "anthropic")
    model_id = model["id"]
    if provider == "qwen":
        api_key = get_dashscope_key()
    else:
        api_key = get_anthropic_key()
    return {"model_id": model_id, "api_key": api_key, "provider": provider}


def highlight_terms(text: str, glossary: list) -> str:
    """在文本中高亮术语，返回 HTML。"""
    if not text or not glossary:
        return text or ""
    terms = sorted(glossary, key=lambda g: len(g[0]) if g[0] else 0, reverse=True)
    result = text
    for term, defn in terms:
        if not term:
            continue
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        result = pattern.sub(
            f'<span class="term" title="{defn}">{term}</span>',
            result,
        )
    return result


def _ensure_str(val) -> str:
    """确保值为字符串（API有时返回列表）。"""
    if val is None:
        return ""
    if isinstance(val, list):
        return "\n".join(str(v) for v in val)
    return str(val)


def gen_markdown(entries: list) -> str:
    md = ""
    for e in entries:
        page_entries = e.get("_page_entries")
        if page_entries:
            page_bp = e.get("_pageBP", "?")
            md += f"---\n**Page {page_bp}**\n\n"
            for pe in page_entries:
                hlevel = pe.get("heading_level", 0)
                orig = _ensure_str(pe.get("original")).strip()
                if hlevel > 0:
                    prefix = "#" * min(hlevel, 6)
                    md += f"{prefix} {orig}\n\n"
                    tr = _ensure_str(pe.get("translation")).strip()
                    if tr:
                        md += f"{prefix} {tr}\n\n"
                else:
                    for line in orig.split("\n"):
                        line = line.strip()
                        if line:
                            md += f"> {line}\n"
                    md += "\n"
                    md += _ensure_str(pe.get("translation")).strip() + "\n\n"
                    fn = _ensure_str(pe.get("footnotes")).strip()
                    fn_tr = _ensure_str(pe.get("footnotes_translation")).strip()
                    if fn:
                        md += fn + "\n"
                        if fn_tr:
                            md += fn_tr + "\n"
                        md += "\n"
        else:
            orig = _ensure_str(e.get("original")).strip()
            for line in orig.split("\n"):
                line = line.strip()
                if line:
                    md += f"> {line}\n"
            md += "\n"
            md += _ensure_str(e.get("translation")).strip() + "\n\n"
    return md.strip() + "\n"


def get_app_state() -> dict:
    """获取所有共享的模板变量。"""
    pages, src_name = load_pages_from_disk()
    entries, doc_title, entry_idx = load_entries_from_disk()
    model_key = get_model_key()
    meta = get_doc_meta()
    entry_idx = meta.get("last_entry_idx", entry_idx)

    first_page, last_page = get_page_range(pages) if pages else (1, 1)

    return {
        "pages": pages,
        "src_name": src_name,
        "entries": entries,
        "doc_title": doc_title,
        "entry_idx": entry_idx,
        "model_key": model_key,
        "models": MODELS,
        "glossary": get_glossary(),
        "paddle_token": get_paddle_token(),
        "anthropic_key": get_anthropic_key(),
        "dashscope_key": get_dashscope_key(),
        "has_pages": len(pages) > 0,
        "has_entries": len(entries) > 0,
        "page_count": len(pages),
        "first_page": first_page,
        "last_page": last_page,
        "entry_count": len(entries),
    }

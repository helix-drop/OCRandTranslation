"""磁盘持久化与辅助函数：数据读写、模板变量、文本处理工具。"""
import os
import re
import shutil

from config import (
    MODELS,
    get_paddle_token, get_deepseek_key, get_dashscope_key,
    get_glossary, get_model_key, get_custom_model_name,
    get_custom_model_enabled, get_custom_model_base_key,
    get_translate_parallel_enabled, get_translate_parallel_limit,
    get_current_doc_id, get_doc_dir, get_doc_meta, update_doc_meta,
)
from sqlite_store import SQLiteRepository
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


def _entries_pages_dir(doc_id: str = "") -> str:
    root = _entries_root(doc_id)
    return os.path.join(root, "pages") if root else ""


def _entry_page_path(bp: int, doc_id: str = "") -> str:
    pages_dir = _entries_pages_dir(doc_id)
    if not pages_dir or bp is None:
        return ""
    return os.path.join(pages_dir, f"{int(bp):06d}.json")


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
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    SQLiteRepository().replace_pages(target_doc_id, pages)
    update_doc_meta(target_doc_id, page_count=len(pages), name=name)


def load_pages_from_disk(doc_id: str = "") -> tuple[list, str]:
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return [], ""
    repo = SQLiteRepository()
    pages = repo.load_pages(target_doc_id)
    meta = repo.get_document(target_doc_id) or {}
    return pages, meta.get("name", "")


def save_entries_to_disk(entries: list, title: str, idx: int, doc_id: str = ""):
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    repo = SQLiteRepository()
    repo.clear_translation_pages(target_doc_id)
    for entry in entries:
        bp = entry.get("_pageBP")
        if bp is None:
            continue
        repo.save_translation_page(target_doc_id, int(bp), entry)
    repo.set_translation_title(target_doc_id, title)
    update_doc_meta(target_doc_id, entry_count=len(entries), last_entry_idx=idx)


def save_entry_cursor(idx: int, doc_id: str = ""):
    """仅保存当前阅读位置，不重写整份翻译结果。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    update_doc_meta(target_doc_id, last_entry_idx=idx)


def load_entries_from_disk(doc_id: str = "") -> tuple[list, str, int]:
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return [], "", 0
    repo = SQLiteRepository()
    entries = repo.list_effective_translation_pages(target_doc_id)
    title = repo.get_translation_title(target_doc_id)
    meta = get_doc_meta(target_doc_id)
    return entries, title, int(meta.get("last_entry_idx", 0) or 0)


def save_entry_to_disk(entry: dict, title: str, doc_id: str = "") -> int:
    target_doc_id = doc_id or get_current_doc_id()
    bp = entry.get("_pageBP")
    if not target_doc_id or bp is None:
        return 0
    repo = SQLiteRepository()
    repo.save_translation_page(target_doc_id, int(bp), entry)
    existing_entries = repo.list_effective_translation_pages(target_doc_id)
    page_bps = [int(item.get("_pageBP")) for item in existing_entries if item.get("_pageBP") is not None]
    idx = page_bps.index(int(bp)) if int(bp) in page_bps else max(0, len(page_bps) - 1)
    current_title = repo.get_translation_title(target_doc_id)
    repo.set_translation_title(target_doc_id, current_title or title)
    update_doc_meta(target_doc_id, entry_count=len(existing_entries), last_entry_idx=idx)
    return idx


def clear_entries_from_disk(doc_id: str = ""):
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    SQLiteRepository().clear_translation_pages(target_doc_id)
    SQLiteRepository().set_translation_title(target_doc_id, "")
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


def save_pdf_toc_to_disk(doc_id: str, toc_items: list[dict]) -> None:
    """保存 PDF 目录结构到 SQLite 文档记录。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    SQLiteRepository().set_document_toc(target_doc_id, toc_items or [])


def load_pdf_toc_from_disk(doc_id: str = "") -> list[dict]:
    """读取 PDF 目录结构。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return []
    return SQLiteRepository().get_document_toc(target_doc_id)


# ============ HELPERS ============

def _resolve_translate_model(model_key: str) -> tuple[dict, str]:
    active_model_key = model_key if model_key in MODELS else "deepseek-chat"
    custom_model_name = get_custom_model_name()
    custom_model_enabled = get_custom_model_enabled()
    if custom_model_enabled and custom_model_name:
        bound_model_key = get_custom_model_base_key()
        if bound_model_key:
            active_model_key = bound_model_key
    model = MODELS.get(active_model_key) or MODELS["deepseek-chat"]
    model_id = custom_model_name if custom_model_enabled and custom_model_name else model["id"]
    return model, model_id


def get_translate_args(model_key: str) -> dict:
    """根据模型key返回 translate_paragraph 所需的 model_id, api_key, provider。"""
    model, model_id = _resolve_translate_model(model_key)
    provider = model.get("provider", "deepseek")
    if provider == "qwen":
        api_key = get_dashscope_key()
    else:
        api_key = get_deepseek_key()
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


def _nonempty_markdown_lines(text) -> list[str]:
    return [line.strip() for line in _ensure_str(text).split("\n") if line.strip()]


def _append_blockquote(md_lines: list[str], text) -> None:
    lines = _nonempty_markdown_lines(text)
    if not lines:
        return
    for line in lines:
        md_lines.append(f"> {line}")
    md_lines.append("")


def _append_paragraph(md_lines: list[str], text) -> None:
    content = _ensure_str(text).strip()
    if not content:
        return
    md_lines.append(content)
    md_lines.append("")


def _append_labeled_block(md_lines: list[str], label: str, text) -> None:
    lines = _nonempty_markdown_lines(text)
    if not lines:
        return
    md_lines.append(f"[{label}] {lines[0]}")
    for line in lines[1:]:
        md_lines.append(line)
    md_lines.append("")


def _resolve_page_footnote_assignments(page_entries: list[dict]) -> dict[int, list[tuple[str, str]]]:
    assignments: dict[int, list[tuple[str, str]]] = {}
    body_indices = [
        idx for idx, pe in enumerate(page_entries)
        if int(pe.get("heading_level", 0) or 0) <= 0
        and (_ensure_str(pe.get("original")).strip() or _ensure_str(pe.get("translation")).strip())
    ]
    if not body_indices:
        body_indices = list(range(len(page_entries)))

    footnote_entries = []
    for idx, pe in enumerate(page_entries):
        footnotes = _ensure_str(pe.get("footnotes")).strip()
        footnotes_translation = _ensure_str(pe.get("footnotes_translation")).strip()
        if footnotes or footnotes_translation:
            footnote_entries.append((idx, footnotes, footnotes_translation))

    if not footnote_entries:
        return assignments

    # 当前翻译链路里，整页脚注在“无法挂到具体段落”时会默认落到首段。
    # 导出时把这类单点脚注移到该页最后一段后，避免截断正文阅读节奏。
    if len(footnote_entries) == 1 and body_indices:
        idx, footnotes, footnotes_translation = footnote_entries[0]
        first_body_idx = body_indices[0]
        last_body_idx = body_indices[-1]
        if last_body_idx != idx and (idx not in body_indices or idx == first_body_idx):
            return {last_body_idx: [(footnotes, footnotes_translation)]}

    for idx, footnotes, footnotes_translation in footnote_entries:
        assignments.setdefault(idx, []).append((footnotes, footnotes_translation))
    return assignments


def gen_markdown(entries: list) -> str:
    md_lines: list[str] = []
    for e in entries:
        page_entries = e.get("_page_entries")
        if page_entries:
            footnote_assignments = _resolve_page_footnote_assignments(page_entries)
            for idx, pe in enumerate(page_entries):
                hlevel = pe.get("heading_level", 0)
                orig = _ensure_str(pe.get("original")).strip()
                tr = _ensure_str(pe.get("translation")).strip()
                if hlevel > 0:
                    prefix = "#" * min(hlevel, 6)
                    heading = orig or tr
                    if heading:
                        md_lines.append(f"{prefix} {heading}")
                        md_lines.append("")
                else:
                    _append_blockquote(md_lines, orig)
                    _append_paragraph(md_lines, tr)

                for footnotes, footnotes_translation in footnote_assignments.get(idx, []):
                    _append_labeled_block(md_lines, "脚注", footnotes)
                    _append_labeled_block(md_lines, "脚注翻译", footnotes_translation)
        else:
            orig = _ensure_str(e.get("original")).strip()
            _append_blockquote(md_lines, orig)
            _append_paragraph(md_lines, e.get("translation"))
            _append_labeled_block(md_lines, "脚注", e.get("footnotes"))
            _append_labeled_block(md_lines, "脚注翻译", e.get("footnotes_translation"))

    while md_lines and not md_lines[-1].strip():
        md_lines.pop()
    if not md_lines:
        return ""
    return "\n".join(md_lines) + "\n"


def get_app_state(doc_id: str = "") -> dict:
    """获取所有共享的模板变量。"""
    pages, src_name = load_pages_from_disk(doc_id)
    entries, doc_title, entry_idx = load_entries_from_disk(doc_id)
    model_key = get_model_key()
    meta = get_doc_meta(doc_id)
    entry_idx = meta.get("last_entry_idx", entry_idx)

    first_page, last_page = get_page_range(pages) if pages else (1, 1)

    has_entries = len(entries) > 0
    return {
        "pages": pages,
        "src_name": src_name,
        "entries": entries,
        "doc_title": doc_title,
        "entry_idx": entry_idx,
        "model_key": model_key,
        "models": MODELS,
        "glossary": get_glossary(doc_id),
        "paddle_token": get_paddle_token(),
        "deepseek_key": get_deepseek_key(),
        "dashscope_key": get_dashscope_key(),
        "custom_model_name": get_custom_model_name(),
        "custom_model_enabled": get_custom_model_enabled(),
        "custom_model_base_key": get_custom_model_base_key(),
        "translate_parallel_enabled": get_translate_parallel_enabled(),
        "translate_parallel_limit": get_translate_parallel_limit(),
        "has_pages": len(pages) > 0,
        "has_entries": has_entries,
        "has_translation_history": has_entries,
        "page_count": len(pages),
        "first_page": first_page,
        "last_page": last_page,
        "entry_count": len(entries),
    }

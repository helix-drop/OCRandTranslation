"""磁盘持久化与辅助函数：数据读写、模板变量、文本处理工具。"""
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
import io
import json
import os
import re
import shutil
import time
import unicodedata

from flask import g, has_request_context
from pypdf import PdfReader

from config import (
    MODELS,
    QWEN_BASE_URLS,
    DEEPSEEK_BASE_URL,
    get_paddle_token, get_deepseek_key, get_dashscope_key,
    get_glossary,
    get_active_model_mode, get_active_builtin_model_key, get_custom_model_config,
    get_translate_parallel_enabled, get_translate_parallel_limit,
    get_current_doc_id, get_doc_dir, get_doc_meta, update_doc_meta,
    get_doc_cleanup_headers_footers,
    get_upload_cleanup_headers_footers_enabled,
    get_doc_auto_visual_toc_enabled,
    get_upload_auto_visual_toc_enabled,
)
from sqlite_store import (
    SQLiteRepository,
    TOC_SOURCE_AUTO,
    TOC_SOURCE_AUTO_VISUAL,
    TOC_SOURCE_USER,
)
from text_processing import (
    get_page_range,
    build_visible_page_view,
    normalize_footnote_markers_for_obsidian,
)
from text_utils import strip_html


# ============ DISK PERSISTENCE (多文档) ============

_PRINT_PAGE_INT_RE = re.compile(r"^\d+$")
_DOC_REQUEST_CACHE_KEY = "_doc_request_cache"
_FN_LINE_NUM_RE = re.compile(r"^\s*(\d{1,4})\s*[\.\)、\]]\s*(.+?)\s*$")
_FN_LINE_BRACKET_RE = re.compile(r"^\s*\[(\d{1,4})\]\s*(.+?)\s*$")
# 宽松格式：数字 + 1-3个空格 + 实质内容（用于无标点编号的尾注页，如 "43 Hervé Guibert..."）
_FN_LINE_LOOSE_RE = re.compile(r"^\s*(\d{1,4})\s{1,3}(\S.+?)\s*$")
_NOTES_HEADER_RE = re.compile(r"^\s*(?:notes?|注释|脚注|尾注)\s*$", re.IGNORECASE)
_BACKMATTER_TITLE_RE = re.compile(r"\b(?:notes?|index)\b|注释|尾注|索引|indices", re.IGNORECASE)
_CONTAINER_TITLE_RE = re.compile(r"^(?:cours|course|courses|lectures?|part|section|volume|book)\b", re.IGNORECASE)
_CONTENT_TITLE_RE = re.compile(
    r"^(?:\d+[\.\s]|chapter\b|introduction\b|epilogue\b|afterword\b|appendix\b|preface\b|conclusion\b|le[cç]on\b|lesson\b)",
    re.IGNORECASE,
)
_EXPORT_BOILERPLATE_STRONG_PATTERNS = [
    re.compile(r"\ball rights reserved\b", re.IGNORECASE),
    re.compile(r"\bcopyright\b", re.IGNORECASE),
    re.compile(r"\bisbn(?:-1[03])?\b", re.IGNORECASE),
    re.compile(r"\bcip\b", re.IGNORECASE),
    re.compile(r"版权所有"),
    re.compile(r"图书在版编目"),
]
_EXPORT_BOILERPLATE_WEAK_PATTERNS = [
    re.compile(r"\bpublisher\b", re.IGNORECASE),
    re.compile(r"\bprinted in\b", re.IGNORECASE),
    re.compile(r"\beditorial\b", re.IGNORECASE),
    re.compile(r"出版社"),
    re.compile(r"印刷"),
    re.compile(r"定价"),
]


def _get_request_cache_root() -> dict | None:
    if not has_request_context():
        return None
    cache = getattr(g, _DOC_REQUEST_CACHE_KEY, None)
    if cache is None:
        cache = {}
        setattr(g, _DOC_REQUEST_CACHE_KEY, cache)
    return cache


def _get_doc_request_cache(doc_id: str) -> dict | None:
    if not doc_id:
        return None
    cache = _get_request_cache_root()
    if cache is None:
        return None
    return cache.setdefault(doc_id, {})


def _get_cached_doc_value(doc_id: str, key: str):
    cache = _get_doc_request_cache(doc_id)
    if cache is None:
        return None
    return cache.get(key)


def _set_cached_doc_value(doc_id: str, key: str, value):
    cache = _get_doc_request_cache(doc_id)
    if cache is not None:
        cache[key] = value
    return value


def _invalidate_doc_request_cache(doc_id: str, *keys: str) -> None:
    if not has_request_context() or not doc_id:
        return
    cache = getattr(g, _DOC_REQUEST_CACHE_KEY, None)
    if not isinstance(cache, dict) or doc_id not in cache:
        return
    if not keys:
        cache.pop(doc_id, None)
        return
    for key in keys:
        cache[doc_id].pop(key, None)
    if not cache[doc_id]:
        cache.pop(doc_id, None)

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
    _invalidate_doc_request_cache(target_doc_id)


def _parse_print_page_number(label) -> int | None:
    raw = str(label or "").strip()
    if not raw or not _PRINT_PAGE_INT_RE.match(raw):
        return None
    value = int(raw)
    return value if value > 0 else None


def resolve_page_print_label(page: dict | None) -> str:
    if not isinstance(page, dict):
        return ""
    raw = str(page.get("printPageLabel") or "").strip()
    if raw:
        return raw
    value = page.get("printPage")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return ""
    return str(parsed) if parsed > 0 else ""


def format_print_page_display(label) -> str:
    raw = str(label or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("原书 p.") else f"原书 p.{raw}"


def _normalize_page_payload(page: dict, book_page: int | None = None, file_idx: int | None = None) -> dict:
    normalized = dict(page or {})
    resolved_book_page = int(book_page if book_page is not None else normalized.get("bookPage", 0) or 0)
    resolved_file_idx = int(file_idx if file_idx is not None else normalized.get("fileIdx", max(resolved_book_page - 1, 0)) or 0)
    normalized["bookPage"] = resolved_book_page
    normalized["pdfPage"] = int(normalized.get("pdfPage", resolved_book_page) or resolved_book_page)
    normalized["fileIdx"] = resolved_file_idx
    print_label = resolve_page_print_label(normalized)
    if print_label:
        normalized["printPageLabel"] = print_label
        if normalized.get("printPage") is None:
            parsed = _parse_print_page_number(print_label)
            if parsed is not None:
                normalized["printPage"] = parsed
    else:
        normalized["printPageLabel"] = ""
    normalized["printPageDisplay"] = format_print_page_display(normalized.get("printPageLabel"))
    return normalized


def _pages_need_pdf_navigation_repair(pages: list[dict]) -> bool:
    if not pages:
        return False
    ordered = sorted(pages, key=lambda item: int(item.get("fileIdx", 0) or 0))
    for expected_file_idx, page in enumerate(ordered):
        file_idx = int(page.get("fileIdx", -1) or -1)
        book_page = int(page.get("bookPage", 0) or 0)
        if file_idx != expected_file_idx or book_page != expected_file_idx + 1:
            return True
    return False


def _read_pdf_page_count(doc_id: str) -> int:
    pdf_path = get_pdf_path(doc_id)
    if not pdf_path or not os.path.exists(pdf_path):
        return 0
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            return len(reader.pages)
    except Exception:
        return 0


def _repair_pages_for_pdf_navigation(doc_id: str, pages: list[dict]) -> tuple[list[dict], dict[int, int]]:
    pdf_page_count = _read_pdf_page_count(doc_id)
    if pdf_page_count <= 0:
        return ([_normalize_page_payload(page) for page in pages], {})

    ordered = sorted((dict(page) for page in pages), key=lambda item: int(item.get("fileIdx", 0) or 0))
    existing_by_file_idx = {
        int(page.get("fileIdx", 0) or 0): page
        for page in ordered
        if page.get("fileIdx") is not None
    }
    legacy_bp_to_pdf_bp = {}
    known_print_numbers: dict[int, int] = {}
    for page in ordered:
        file_idx = int(page.get("fileIdx", 0) or 0)
        legacy_bp = page.get("bookPage")
        if legacy_bp is not None:
            legacy_bp_to_pdf_bp[int(legacy_bp)] = file_idx + 1
        print_label = resolve_page_print_label(page)
        if not print_label:
            legacy_book_page = page.get("bookPage")
            legacy_pdf_page = file_idx + 1
            try:
                legacy_book_page = int(legacy_book_page)
            except (TypeError, ValueError):
                legacy_book_page = None
            if legacy_book_page and legacy_book_page != legacy_pdf_page:
                print_label = str(legacy_book_page)
        print_num = _parse_print_page_number(print_label)
        if print_num is not None:
            known_print_numbers[file_idx] = print_num

    sorted_known = sorted(known_print_numbers.items())
    interpolated_print_numbers = dict(known_print_numbers)
    for idx in range(len(sorted_known) - 1):
        start_idx, start_num = sorted_known[idx]
        end_idx, end_num = sorted_known[idx + 1]
        gap = end_idx - start_idx
        if gap <= 1:
            continue
        step = end_num - start_num
        if step != gap:
            continue
        for file_idx in range(start_idx + 1, end_idx):
            candidate = start_num + (file_idx - start_idx)
            if candidate > 0:
                interpolated_print_numbers[file_idx] = candidate

    repaired_pages = []
    for file_idx in range(pdf_page_count):
        source_page = existing_by_file_idx.get(file_idx, {})
        page = _normalize_page_payload(source_page, book_page=file_idx + 1, file_idx=file_idx)
        if not page.get("printPageLabel"):
            inferred_print_num = interpolated_print_numbers.get(file_idx)
            if inferred_print_num is not None and inferred_print_num > 0:
                page["printPage"] = inferred_print_num
                page["printPageLabel"] = str(inferred_print_num)
                page["printPageDisplay"] = format_print_page_display(page["printPageLabel"])
        if file_idx not in existing_by_file_idx:
            page["isPlaceholder"] = True
            page["markdown"] = _ensure_str(page.get("markdown", ""))
            page["footnotes"] = _ensure_str(page.get("footnotes", ""))
            page["blocks"] = page.get("blocks") or []
            page["fnBlocks"] = page.get("fnBlocks") or []
            page["textSource"] = page.get("textSource") or "placeholder"
        repaired_pages.append(page)
    return repaired_pages, legacy_bp_to_pdf_bp


def _normalize_placeholder_print_labels(pages: list[dict]) -> tuple[list[dict], bool]:
    ordered = [_normalize_page_payload(page) for page in pages]
    explicit_numbers: dict[int, int] = {}
    for idx, page in enumerate(ordered):
        if page.get("isPlaceholder"):
            continue
        print_num = _parse_print_page_number(page.get("printPageLabel"))
        if print_num is not None:
            explicit_numbers[idx] = print_num

    changed = False
    for idx, page in enumerate(ordered):
        if not page.get("isPlaceholder"):
            continue
        prev_known = next(((i, explicit_numbers[i]) for i in range(idx - 1, -1, -1) if i in explicit_numbers), None)
        next_known = next(((i, explicit_numbers[i]) for i in range(idx + 1, len(ordered)) if i in explicit_numbers), None)
        confident_label = ""
        if prev_known and next_known:
            prev_idx, prev_num = prev_known
            next_idx, next_num = next_known
            if next_num - prev_num == next_idx - prev_idx:
                confident_label = str(prev_num + (idx - prev_idx))
        current_label = str(page.get("printPageLabel") or "").strip()
        if confident_label:
            if current_label != confident_label:
                page["printPage"] = int(confident_label)
                page["printPageLabel"] = confident_label
                page["printPageDisplay"] = format_print_page_display(confident_label)
                changed = True
        elif current_label or page.get("printPage") or page.get("printPageDisplay"):
            page["printPage"] = None
            page["printPageLabel"] = ""
            page["printPageDisplay"] = ""
            changed = True
    return ordered, changed


def _segment_print_label_for_range(pages_by_bp: dict[int, dict], start_bp: int | None, end_bp: int | None) -> str:
    if start_bp is None:
        return ""
    end_bp = end_bp if end_bp is not None else start_bp
    start_label = resolve_page_print_label(pages_by_bp.get(int(start_bp)))
    end_label = resolve_page_print_label(pages_by_bp.get(int(end_bp)))
    if not start_label:
        return ""
    if not end_label or end_label == start_label:
        return start_label
    return f"{start_label}-{end_label}"


def _normalize_entries_page_metadata(entries: list[dict], pages: list[dict]) -> tuple[list[dict], bool]:
    pages_by_bp = {
        int(page.get("bookPage")): page
        for page in pages
        if page.get("bookPage") is not None
    }
    changed = False
    normalized_entries = []
    for entry in entries:
        entry_copy = dict(entry or {})
        page_bp = entry_copy.get("_pageBP")
        page_label = resolve_page_print_label(pages_by_bp.get(int(page_bp))) if page_bp is not None else ""
        if not str(entry_copy.get("pages", "") or "").strip() and page_label:
            entry_copy["pages"] = format_print_page_display(page_label)
            changed = True

        normalized_segments = []
        for segment in entry_copy.get("_page_entries") or []:
            segment_copy = dict(segment or {})
            start_bp = segment_copy.get("_startBP")
            end_bp = segment_copy.get("_endBP")
            if start_bp is None and page_bp is not None:
                segment_copy["_startBP"] = int(page_bp)
                start_bp = int(page_bp)
                changed = True
            if end_bp is None and start_bp is not None:
                segment_copy["_endBP"] = int(start_bp)
                end_bp = int(start_bp)
                changed = True

            print_label = str(segment_copy.get("_printPageLabel") or "").strip()
            if not print_label:
                print_label = _segment_print_label_for_range(pages_by_bp, start_bp, end_bp)
                if print_label:
                    segment_copy["_printPageLabel"] = print_label
                    changed = True
            if not str(segment_copy.get("pages", "") or "").strip() and print_label:
                segment_copy["pages"] = format_print_page_display(print_label)
                changed = True
            normalized_segments.append(segment_copy)

        entry_copy["_page_entries"] = normalized_segments
        normalized_entries.append(entry_copy)
    return normalized_entries, changed


def load_pages_from_disk(doc_id: str = "") -> tuple[list, str]:
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return [], ""
    cached = _get_cached_doc_value(target_doc_id, "pages_payload")
    if cached is not None:
        return cached
    repo = SQLiteRepository()
    pages = repo.load_pages(target_doc_id)
    if _pages_need_pdf_navigation_repair(pages):
        repaired_pages, bp_map = _repair_pages_for_pdf_navigation(target_doc_id, pages)
        repaired_pages, _ = _normalize_placeholder_print_labels(repaired_pages)
        repo.replace_pages(target_doc_id, repaired_pages)
        repo.remap_book_pages(target_doc_id, bp_map)
        update_doc_meta(target_doc_id, page_count=len(repaired_pages))
        pages = repaired_pages
    else:
        pages = [_normalize_page_payload(page) for page in pages]
        pages, changed = _normalize_placeholder_print_labels(pages)
        if changed:
            repo.replace_pages(target_doc_id, pages)
    meta = repo.get_document(target_doc_id) or {}
    return _set_cached_doc_value(target_doc_id, "pages_payload", (pages, meta.get("name", "")))


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
    _invalidate_doc_request_cache(target_doc_id)


def save_entry_cursor(idx: int, doc_id: str = ""):
    """仅保存当前阅读位置，不重写整份翻译结果。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    update_doc_meta(target_doc_id, last_entry_idx=idx)


def load_entries_from_disk(doc_id: str = "", pages: list | None = None) -> tuple[list, str, int]:
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return [], "", 0
    cached = _get_cached_doc_value(target_doc_id, "entries_payload")
    if cached is not None:
        return cached
    repo = SQLiteRepository()
    entries = repo.list_effective_translation_pages(target_doc_id)
    if pages is None:
        pages, _ = load_pages_from_disk(target_doc_id)
    entries, changed = _normalize_entries_page_metadata(entries, pages)
    if changed:
        for entry in entries:
            bp = entry.get("_pageBP")
            if bp is None:
                continue
                repo.save_translation_page(target_doc_id, int(bp), entry)
    title = repo.get_translation_title(target_doc_id)
    meta = get_doc_meta(target_doc_id)
    return _set_cached_doc_value(
        target_doc_id,
        "entries_payload",
        (entries, title, int(meta.get("last_entry_idx", 0) or 0)),
    )


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
    _invalidate_doc_request_cache(target_doc_id)
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
    _invalidate_doc_request_cache(target_doc_id)


def load_visible_page_view(doc_id: str = "", pages: list | None = None) -> dict:
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return build_visible_page_view([])
    cached = _get_cached_doc_value(target_doc_id, "visible_page_view")
    if cached is not None:
        return cached
    if pages is None:
        pages, _ = load_pages_from_disk(target_doc_id)
    return _set_cached_doc_value(target_doc_id, "visible_page_view", build_visible_page_view(pages))


def has_pdf(doc_id: str = "") -> bool:
    """检查当前文档是否有保存的 PDF 文件供预览。"""
    path = _doc_path("source.pdf", doc_id)
    return bool(path) and os.path.exists(path)


def get_pdf_path(doc_id: str = "") -> str:
    """获取 PDF 文件路径。"""
    return _doc_path("source.pdf", doc_id)


def save_pdf_toc_to_disk(doc_id: str, toc_items: list[dict]) -> None:
    """兼容旧调用：保存用户目录结构到 SQLite 文档记录。"""
    save_user_toc_to_disk(doc_id, toc_items)


def save_user_toc_to_disk(doc_id: str, toc_items: list[dict]) -> None:
    """保存用户目录结构到 SQLite 文档记录。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    SQLiteRepository().set_document_toc_for_source(target_doc_id, TOC_SOURCE_USER, toc_items or [])
    _invalidate_doc_request_cache(target_doc_id)


def load_pdf_toc_from_disk(doc_id: str = "") -> list[dict]:
    """读取自动提取的 PDF 书签/超链接目录。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return []
    return SQLiteRepository().get_document_toc_for_source(target_doc_id, TOC_SOURCE_AUTO)


def _parse_saved_toc_file(path: str) -> list[dict]:
    from pdf_extract import parse_toc_file

    class _SavedTocFile(io.BytesIO):
        def __init__(self, raw: bytes, filename: str):
            super().__init__(raw)
            self.filename = filename

    with open(path, "rb") as f:
        raw = f.read()
    return parse_toc_file(_SavedTocFile(raw, os.path.basename(path)))


def load_user_toc_from_disk(doc_id: str = "") -> list[dict]:
    """读取用户导入目录；若 SQLite 内容意外丢失，则从已持久化文件恢复。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return []
    toc_items = SQLiteRepository().get_document_toc_for_source(target_doc_id, TOC_SOURCE_USER)
    if toc_items:
        return toc_items
    path = get_toc_file_path(target_doc_id)
    if not path or not os.path.exists(path):
        return []
    try:
        recovered = _parse_saved_toc_file(path)
    except Exception:
        return []
    if recovered:
        save_user_toc_to_disk(target_doc_id, recovered)
    return recovered


def save_auto_pdf_toc_to_disk(doc_id: str, toc_items: list[dict]) -> None:
    """保存自动提取的 PDF 书签/超链接目录。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    SQLiteRepository().set_document_toc_for_source(target_doc_id, TOC_SOURCE_AUTO, toc_items or [])
    current_source, _ = SQLiteRepository().get_document_toc_source_offset(target_doc_id)
    if current_source not in {TOC_SOURCE_USER, TOC_SOURCE_AUTO_VISUAL}:
        SQLiteRepository().set_document_toc_source_offset(target_doc_id, TOC_SOURCE_AUTO, 0)
    _invalidate_doc_request_cache(target_doc_id)


def save_auto_visual_toc_to_disk(doc_id: str, toc_items: list[dict]) -> None:
    """保存一份已就绪的自动视觉目录；若当前没有用户目录，则切换为视觉目录来源。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    SQLiteRepository().set_document_toc_for_source(target_doc_id, TOC_SOURCE_AUTO_VISUAL, toc_items or [])
    update_doc_meta(
        target_doc_id,
        toc_visual_status="ready",
        toc_visual_message=f"已生成 {len(toc_items or [])} 条自动视觉目录。",
    )
    current_source, _ = SQLiteRepository().get_document_toc_source_offset(target_doc_id)
    if current_source != TOC_SOURCE_USER:
        SQLiteRepository().set_document_toc_source_offset(target_doc_id, TOC_SOURCE_AUTO_VISUAL, 0)
    _invalidate_doc_request_cache(target_doc_id)


def load_auto_visual_toc_from_disk(doc_id: str = "") -> list[dict]:
    """读取自动视觉目录。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return []
    return SQLiteRepository().get_document_toc_for_source(target_doc_id, TOC_SOURCE_AUTO_VISUAL)


def load_effective_toc(doc_id: str = "") -> tuple[str, int, list[dict]]:
    """按优先级返回当前生效目录：用户 > 自动视觉 > 自动 PDF。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return (TOC_SOURCE_AUTO, 0, [])

    source, offset = SQLiteRepository().get_document_toc_source_offset(target_doc_id)
    user_toc = load_user_toc_from_disk(target_doc_id)
    if user_toc:
        return (TOC_SOURCE_USER, int(offset or 0), user_toc)

    meta = get_doc_meta(target_doc_id) or {}
    visual_toc = load_auto_visual_toc_from_disk(target_doc_id)
    visual_status = str(meta.get("toc_visual_status", "") or "").strip().lower()
    if visual_toc and visual_status in {"ready", "needs_offset"}:
        visual_offset = int(offset or 0) if source == TOC_SOURCE_AUTO_VISUAL else 0
        return (TOC_SOURCE_AUTO_VISUAL, visual_offset, visual_toc)

    return (TOC_SOURCE_AUTO, 0, load_pdf_toc_from_disk(target_doc_id))


def save_toc_file(doc_id: str, file_storage) -> None:
    """将用户上传的目录原始文件持久化到文档目录，文件名固定为 toc_source.{ext}。"""
    target_doc_id = doc_id or get_current_doc_id()
    doc_dir = get_doc_dir(target_doc_id)
    if not doc_dir:
        return
    original_name = os.path.basename(str(file_storage.filename or "").strip())
    filename = original_name.lower()
    ext = "xlsx" if filename.endswith(".xlsx") else "csv"
    dest = os.path.join(doc_dir, f"toc_source.{ext}")
    # 删除旧格式文件（xlsx/csv 互换时清理）
    for old_ext in ("xlsx", "csv"):
        old_path = os.path.join(doc_dir, f"toc_source.{old_ext}")
        if old_path != dest and os.path.exists(old_path):
            os.remove(old_path)
    file_storage.seek(0)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file_storage, f)
    SQLiteRepository().set_document_toc_file_meta(
        target_doc_id,
        original_name,
        uploaded_at=int(time.time()),
    )


def get_toc_file_path(doc_id: str = "") -> str:
    """返回已保存的目录原始文件路径，不存在时返回空字符串。"""
    target_doc_id = doc_id or get_current_doc_id()
    doc_dir = get_doc_dir(target_doc_id)
    if not doc_dir:
        return ""
    for ext in ("xlsx", "csv"):
        path = os.path.join(doc_dir, f"toc_source.{ext}")
        if os.path.exists(path):
            return path
    return ""


def get_toc_file_info(doc_id: str = "") -> dict:
    """返回当前文档已保存目录文件的展示信息。"""
    target_doc_id = doc_id or get_current_doc_id()
    path = get_toc_file_path(target_doc_id)
    info = {
        "exists": False,
        "display_name": "",
        "original_name": "",
        "uploaded_at": 0,
        "saved_path": "",
        "is_legacy_name": False,
    }
    if not path or not os.path.exists(path):
        return info

    meta = get_doc_meta(target_doc_id) if target_doc_id else {}
    original_name = os.path.basename(str(meta.get("toc_file_name", "") or "").strip())
    uploaded_at = int(meta.get("toc_file_uploaded_at", 0) or 0)
    if uploaded_at <= 0:
        try:
            uploaded_at = int(os.path.getmtime(path))
        except OSError:
            uploaded_at = 0
    return {
        "exists": True,
        "display_name": original_name or os.path.basename(path),
        "original_name": original_name,
        "uploaded_at": uploaded_at,
        "saved_path": path,
        "is_legacy_name": not bool(original_name),
    }


TOC_VISUAL_DRAFT_FILENAME = "toc_visual_draft.json"


def get_toc_visual_draft_path(doc_id: str) -> str:
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return ""
    return os.path.join(doc_dir, TOC_VISUAL_DRAFT_FILENAME)


def load_toc_visual_draft(doc_id: str) -> tuple[list[dict], int] | None:
    """读取自动视觉目录草稿；返回 (items, pending_offset) 或 None。"""
    path = get_toc_visual_draft_path(doc_id)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return None
    if isinstance(raw, list):
        return raw, 0
    if not isinstance(raw, dict):
        return None
    items = raw.get("items")
    if not isinstance(items, list):
        return None
    po = int(raw.get("pending_offset") or 0)
    return items, po


def save_toc_visual_draft(doc_id: str, items: list[dict], pending_offset: int) -> None:
    """写入草稿文件；不修改 SQLite 中的自动视觉目录。"""
    path = get_toc_visual_draft_path(doc_id)
    if not path:
        return
    payload = {"items": items, "pending_offset": int(pending_offset or 0)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _invalidate_doc_request_cache(doc_id)


def clear_toc_visual_draft(doc_id: str) -> None:
    path = get_toc_visual_draft_path(doc_id)
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    _invalidate_doc_request_cache(doc_id)


def has_toc_visual_draft(doc_id: str) -> bool:
    p = get_toc_visual_draft_path(doc_id)
    return bool(p and os.path.exists(p))


def save_user_toc_csv_generated(doc_id: str, user_rows: list[dict]) -> None:
    """根据用户目录行生成 toc_source.csv 并更新文件元数据。"""
    from pdf_extract import write_user_toc_csv_bytes

    target_doc_id = doc_id or get_current_doc_id()
    doc_dir = get_doc_dir(target_doc_id)
    if not doc_dir:
        return
    raw = write_user_toc_csv_bytes(user_rows)
    dest = os.path.join(doc_dir, "toc_source.csv")
    for old_ext in ("xlsx", "csv"):
        old_path = os.path.join(doc_dir, f"toc_source.{old_ext}")
        if old_path != dest and os.path.exists(old_path):
            os.remove(old_path)
    with open(dest, "wb") as f:
        f.write(raw)
    SQLiteRepository().set_document_toc_file_meta(
        target_doc_id,
        "toc_export.csv",
        uploaded_at=int(time.time()),
    )


def save_toc_source_offset(doc_id: str, source: str, offset: int) -> None:
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    SQLiteRepository().set_document_toc_source_offset(target_doc_id, source, offset)
    _invalidate_doc_request_cache(target_doc_id)


def load_toc_source_offset(doc_id: str = "") -> tuple[str, int]:
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return (TOC_SOURCE_AUTO, 0)
    source, offset, _ = load_effective_toc(target_doc_id)
    return (source, offset)


# ============ HELPERS ============

@dataclass(slots=True)
class ResolvedModelSpec:
    source: str
    model_key: str
    model_id: str
    provider: str
    base_url: str
    api_key: str
    display_label: str
    request_overrides: dict = field(default_factory=dict)


def _infer_builtin_key_from_custom_model(provider: str, model_id: str) -> str:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model_id = str(model_id or "").strip().lower()
    if normalized_provider == "qwen":
        if "max" in normalized_model_id:
            return "qwen-max"
        if "turbo" in normalized_model_id or "flash" in normalized_model_id:
            return "qwen-turbo"
        return "qwen-plus"
    if normalized_provider == "deepseek":
        if "reasoner" in normalized_model_id or normalized_model_id.endswith("-r1"):
            return "deepseek-reasoner"
        return "deepseek-chat"
    return ""


def resolve_model_spec(target: str | None = None) -> ResolvedModelSpec:
    active_mode = get_active_model_mode()
    active_builtin_key = get_active_builtin_model_key()
    custom_model = get_custom_model_config()

    normalized_target = str(target or "").strip()
    if normalized_target.startswith("builtin:"):
        builtin_key = normalized_target.split(":", 1)[1].strip()
        builtin_key = builtin_key if builtin_key in MODELS else active_builtin_key
        model = MODELS.get(builtin_key) or MODELS["deepseek-chat"]
        provider = model.get("provider", "deepseek")
        api_key = get_dashscope_key() if provider == "qwen" else get_deepseek_key()
        return ResolvedModelSpec(
            source="builtin",
            model_key=builtin_key,
            model_id=model["id"],
            provider=provider,
            base_url=QWEN_BASE_URLS["cn"] if provider == "qwen" else DEEPSEEK_BASE_URL,
            api_key=api_key,
            display_label=model.get("label", model["id"]),
            request_overrides={},
        )
    if normalized_target == "custom":
        active_mode = "custom"

    if active_mode == "custom" and custom_model.get("enabled") and custom_model.get("model_id"):
        provider = custom_model.get("provider_type", "qwen")
        if provider == "qwen":
            api_key = get_dashscope_key()
            base_url = QWEN_BASE_URLS.get(custom_model.get("qwen_region", "cn"), QWEN_BASE_URLS["cn"])
            request_overrides = {"extra_body": dict(custom_model.get("extra_body") or {"enable_thinking": False})}
        elif provider == "deepseek":
            api_key = get_deepseek_key()
            base_url = DEEPSEEK_BASE_URL
            request_overrides = {}
        else:
            api_key = str(custom_model.get("custom_api_key", "") or "").strip()
            base_url = str(custom_model.get("base_url", "") or "").strip()
            request_overrides = {}
        return ResolvedModelSpec(
            source="custom",
            model_key="",
            model_id=str(custom_model.get("model_id", "") or "").strip(),
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            display_label=str(custom_model.get("display_name", "") or custom_model.get("model_id", "")).strip(),
            request_overrides=request_overrides,
        )

    return resolve_model_spec(f"builtin:{active_builtin_key}")


def get_translate_args(target: str | None = None) -> dict:
    """返回统一解析后的翻译请求参数。"""
    spec = resolve_model_spec(target)
    payload = asdict(spec)
    payload["model_source"] = payload.pop("source")
    return payload


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


def _unwrap_translation_json(text: str) -> str:
    """若 text 是 LLM 返回的 JSON 整体（误存为 translation），提取其中真正的 translation 字段。

    先尝试 json.loads，失败则用正则定位 "translation": 后面的内容（兼容 JSON 中含未转义引号的情况）。
    """
    t = text.strip()
    if not t.startswith("{"):
        return text
    # 快速判断：必须像翻译 JSON（含多个已知键）
    if '"translation"' not in t or '"original"' not in t:
        return text

    # 尝试标准解析
    try:
        parsed = json.loads(t)
        if isinstance(parsed, dict) and "translation" in parsed:
            result = _ensure_str(parsed["translation"]).strip()
            return result or text
    except Exception:
        pass

    # 正则兜底：提取 "translation": "..." 的值
    # 向后定位到 "footnotes_translation" 或 JSON 结尾作为截止标志
    m = re.search(
        r'"translation"\s*:\s*"(.*?)"\s*(?:,\s*"footnotes_translation"|[}\]])',
        t,
        re.DOTALL,
    )
    if m:
        raw = m.group(1)
        # 还原转义序列
        result = raw.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').strip()
        return result or text

    return text


def build_toc_chapters(toc_items: list, offset: int = 0, total_pages: int = 0) -> list[dict]:
    """将 TOC 条目转换为带页码范围的顶级章节列表。

    只取 depth=0 的条目作为章节；若无 depth=0 条目则取全部。
    返回：[{index, title, depth, start_bp, end_bp}, ...]
    start_bp/end_bp 均为 1-based book_page（已加 offset）。
    """
    if not toc_items:
        return []

    def _bp(item: dict) -> int:
        bp = int(item.get("book_page") or 0)
        fi = item.get("file_idx")
        if not bp and fi is not None:
            bp = int(fi) + 1
        return bp + int(offset or 0) if bp > 0 else 0

    top_level = [item for item in toc_items if int(item.get("depth", 0) or 0) == 0]
    candidates = top_level if top_level else list(toc_items)

    chapters = []
    for item in candidates:
        bp = _bp(item)
        if bp > 0:
            chapters.append({
                "title": item.get("title", ""),
                "depth": int(item.get("depth", 0) or 0),
                "start_bp": bp,
                "end_bp": None,
            })

    if not chapters:
        return []

    chapters.sort(key=lambda c: c["start_bp"])

    for i, ch in enumerate(chapters):
        if i + 1 < len(chapters):
            ch["end_bp"] = chapters[i + 1]["start_bp"] - 1
        else:
            ch["end_bp"] = total_pages if total_pages > 0 else ch["start_bp"]

    for i, ch in enumerate(chapters):
        ch["index"] = i

    return chapters


def build_toc_depth_map(toc_items: list, offset: int = 0) -> dict:
    """从原始 TOC 条目 + 页码偏移构建 {book_page: depth} 查找表。

    auto-extracted TOC 使用 file_idx（0-based），user-uploaded 使用 book_page（1-based印刷页）。
    book_page（有效页）= file_idx+1（自动目录）或 book_page+offset（用户目录）。
    """
    depth_map: dict[int, int] = {}
    for item in toc_items or []:
        depth = int(item.get("depth", 0) or 0)
        bp = int(item.get("book_page") or 0)
        fi = item.get("file_idx")
        if not bp and fi is not None:
            bp = int(fi) + 1  # 0-based → 1-based
        if bp > 0:
            effective = bp + int(offset or 0)
            depth_map[effective] = depth
    return depth_map


def build_toc_title_map(toc_items: list, offset: int = 0) -> dict[int, str]:
    """从 TOC 条目 + 偏移构建 {book_page: title} 查找表。"""
    title_map: dict[int, str] = {}
    for item in toc_items or []:
        bp = int(item.get("book_page") or 0)
        fi = item.get("file_idx")
        if not bp and fi is not None:
            bp = int(fi) + 1
        if bp > 0:
            effective = bp + int(offset or 0)
            title_map[int(effective)] = _ensure_str(item.get("title")).strip()
    return title_map


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


def _normalize_heuristic_text(raw: str) -> str:
    return re.sub(r"\s+", " ", _ensure_str(raw)).strip().lower()


def _page_text_for_export_heuristic(entry: dict) -> str:
    chunks: list[str] = []
    page_entries = entry.get("_page_entries") or []
    if page_entries:
        for pe in page_entries:
            orig = strip_html(_normalize_footnote_markers(_ensure_str(pe.get("original")).strip())).strip()
            tr = strip_html(
                _normalize_footnote_markers(
                    _unwrap_translation_json(_ensure_str(pe.get("translation")).strip())
                )
            ).strip()
            if orig:
                chunks.append(orig)
            if tr:
                chunks.append(tr)
    else:
        orig = strip_html(_normalize_footnote_markers(_ensure_str(entry.get("original")).strip())).strip()
        tr = strip_html(
            _normalize_footnote_markers(_unwrap_translation_json(_ensure_str(entry.get("translation")).strip()))
        ).strip()
        if orig:
            chunks.append(orig)
        if tr:
            chunks.append(tr)
    return "\n".join(chunks).strip()


def compute_boilerplate_skip_bps(
    entries: list[dict],
    chapters: list[dict] | None,
    *,
    max_leading_scan: int = 12,
) -> set[int]:
    page_texts: dict[int, str] = {}
    for entry in entries or []:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp <= 0:
            continue
        text = _page_text_for_export_heuristic(entry)
        if text:
            page_texts[bp] = text
    if not page_texts:
        return set()

    sorted_bps = sorted(page_texts.keys())
    last_bp = sorted_bps[-1]
    leading_limit_bp = min(last_bp, int(max_leading_scan))
    chapter_start_bp = None
    if chapters:
        starts = [int(ch.get("start_bp") or 0) for ch in chapters if int(ch.get("start_bp") or 0) > 0]
        if starts:
            chapter_start_bp = min(starts)

    candidate_bps: set[int] = set()
    if chapter_start_bp and chapter_start_bp > 1:
        candidate_bps = {bp for bp in sorted_bps if bp < chapter_start_bp}
    else:
        candidate_bps = {bp for bp in sorted_bps if bp <= leading_limit_bp}

    skip_bps: set[int] = set()
    normalized_by_bp = {bp: _normalize_heuristic_text(page_texts[bp]) for bp in sorted_bps}
    length_by_bp = {bp: len(normalized_by_bp[bp]) for bp in sorted_bps}

    for bp in sorted_bps:
        text = normalized_by_bp[bp]
        text_len = length_by_bp[bp]
        if text_len == 0:
            continue
        in_candidate = bp in candidate_bps
        strong_hit = any(p.search(text) for p in _EXPORT_BOILERPLATE_STRONG_PATTERNS)
        weak_hit = any(p.search(text) for p in _EXPORT_BOILERPLATE_WEAK_PATTERNS)
        if (in_candidate or text_len <= 120) and strong_hit and text_len <= 1600:
            skip_bps.add(bp)
            continue
        if in_candidate and text_len <= 220 and weak_hit:
            skip_bps.add(bp)

    leading_bps = [bp for bp in sorted_bps if bp <= leading_limit_bp]
    for i in range(len(leading_bps)):
        a_bp = leading_bps[i]
        if a_bp in skip_bps:
            continue
        a_text = normalized_by_bp[a_bp]
        if len(a_text) < 24:
            continue
        for j in range(i + 1, len(leading_bps)):
            b_bp = leading_bps[j]
            if b_bp in skip_bps:
                continue
            b_text = normalized_by_bp[b_bp]
            if len(b_text) < 24:
                continue
            ratio = SequenceMatcher(None, a_text, b_text).ratio()
            if ratio >= 0.92 and len(b_text) <= 1600:
                skip_bps.add(b_bp)
    return skip_bps


def detect_book_index_pages(entries: list[dict]) -> set[int]:
    """检测书末索引页（人名/主题索引），返回应跳过的页码集合。"""
    page_texts: dict[int, str] = {}
    for entry in entries or []:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp <= 0:
            continue
        text = _page_text_for_export_heuristic(entry)
        if text:
            page_texts[bp] = text
    if not page_texts:
        return set()

    sorted_bps = sorted(page_texts.keys())
    start_idx = int(len(sorted_bps) * 0.8)
    scan_bps = sorted_bps[start_idx:] if start_idx < len(sorted_bps) else []
    if not scan_bps:
        return set()

    def _looks_like_index_line(line: str) -> bool:
        ln = line.strip()
        if not ln:
            return False
        if not re.match(r"^[A-Za-zÀ-ÿ\u4e00-\u9fff]", ln):
            return False
        if "," not in ln and "，" not in ln:
            return False
        nums = re.findall(r"\d+", ln)
        if len(nums) < 2:
            return False
        return True

    stats_by_bp: dict[int, tuple[int, int, float]] = {}
    for bp in scan_bps:
        raw = _ensure_str(page_texts.get(bp))
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            continue
        numeric_lines = [ln for ln in lines if re.search(r"\d", ln)]
        if not numeric_lines:
            continue
        index_hits = sum(1 for ln in numeric_lines if _looks_like_index_line(ln))
        ratio = index_hits / max(len(numeric_lines), 1)
        stats_by_bp[bp] = (index_hits, len(numeric_lines), ratio)

    strong_hits = {
        bp for bp, (hits, _num_count, ratio) in stats_by_bp.items() if hits >= 5 and ratio >= 0.4
    }
    hit_bps: set[int] = set(strong_hits)
    if strong_hits:
        # 双语索引页常出现“半页命中、半页译文”，将与强命中页相邻的中等命中页一并纳入。
        for bp, (hits, _num_count, ratio) in stats_by_bp.items():
            if bp in hit_bps:
                continue
            if hits >= 5 and ratio >= 0.22 and any(abs(bp - s) <= 2 for s in strong_hits):
                hit_bps.add(bp)
        # 索引续页可能是弱格式（词条压行、参照项较多），对强命中邻页再放宽一档。
        for bp, (hits, _num_count, ratio) in stats_by_bp.items():
            if bp in hit_bps:
                continue
            if hits >= 4 and ratio >= 0.18 and any(abs(bp - s) <= 1 for s in hit_bps):
                hit_bps.add(bp)
    return hit_bps


def _normalize_footnote_markers(text: str) -> str:
    return normalize_footnote_markers_for_obsidian(_ensure_str(text))


def _extract_marked_footnote_labels(text: str) -> list[str]:
    normalized = _normalize_footnote_markers(text)
    labels = []
    seen = set()
    for m in re.finditer(r"\[\^([A-Za-z0-9_-]+)\]", normalized):
        label = m.group(1)
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def _split_footnote_items(text: str, strict: bool = True) -> list[tuple[str | None, str]]:
    """将脚注/尾注文本拆分为 (label, content) 列表。

    strict=True（默认）：仅识别带明确标点的编号格式，如 "1. text"、"[1] text"。
    strict=False：额外识别无标点的宽松格式，如 "43 Hervé Guibert..."（用于尾注页）。
    """
    lines = [ln.strip() for ln in _ensure_str(text).split("\n") if ln.strip()]
    if not lines:
        return []
    items: list[tuple[str | None, str]] = []
    for line in lines:
        m_num = _FN_LINE_NUM_RE.match(line)
        if m_num:
            items.append((m_num.group(1), m_num.group(2).strip()))
            continue
        m_bracket = _FN_LINE_BRACKET_RE.match(line)
        if m_bracket:
            items.append((m_bracket.group(1), m_bracket.group(2).strip()))
            continue
        if not strict:
            m_loose = _FN_LINE_LOOSE_RE.match(line)
            if m_loose:
                items.append((m_loose.group(1), m_loose.group(2).strip()))
                continue
        items.append((None, line))
    return items


def _classify_note_scope(
    label: str,
    content: str,
    inline_labels: list[str],
    source_bp: int,
    chapter_end_bp: int | None,
    doc_last_bp: int,
    had_explicit_label: bool,
) -> tuple[str, str]:
    """返回 (note_type, note_scope)。

    note_type: footnote | endnote
    note_scope: paragraph_or_page | chapter_end | book_end
    """
    # 保守默认：脚注
    if label in set(inline_labels):
        return "footnote", "paragraph_or_page"
    if not had_explicit_label:
        return "footnote", "paragraph_or_page"

    # 高置信尾注：编号清晰 + 正文未命中 + 内容较长 + 位于章末/书末附近
    is_numeric_label = str(label).isdigit()
    looks_long_note = len(_ensure_str(content)) >= 220
    if is_numeric_label and looks_long_note:
        if chapter_end_bp is not None and source_bp >= max(1, int(chapter_end_bp) - 1):
            return "endnote", "chapter_end"
        if source_bp >= max(1, int(doc_last_bp) - 1):
            return "endnote", "book_end"
    return "footnote", "paragraph_or_page"


def _build_obsidian_footnote_defs(
    footnotes,
    footnotes_translation,
    existing_labels: list[str],
    preferred_labels: list[str] | None,
    source_bp: int,
    segment_idx: int,
    chapter_index: int | None,
    chapter_end_bp: int | None,
    doc_last_bp: int,
    fallback_prefix: str,
) -> tuple[list[dict], list[str], list[tuple[str, str]]]:
    items_fn = _split_footnote_items(footnotes)
    items_tr = _split_footnote_items(footnotes_translation)
    defs: list[dict] = []
    fallback_blocks: list[tuple[str, str]] = []
    labels_for_refs: list[str] = []

    count = max(len(items_fn), len(items_tr))
    if count == 0:
        return defs, labels_for_refs, fallback_blocks

    existing_set = set(existing_labels)
    preferred = [lab for lab in (preferred_labels or []) if lab and lab not in existing_set]
    preferred_idx = 0
    for idx in range(count):
        fn_label = items_fn[idx][0] if idx < len(items_fn) else None
        fn_content = items_fn[idx][1] if idx < len(items_fn) else ""
        tr_label = items_tr[idx][0] if idx < len(items_tr) else None
        tr_content = items_tr[idx][1] if idx < len(items_tr) else ""
        label = fn_label or tr_label
        if not label:
            if preferred_idx < len(preferred):
                label = preferred[preferred_idx]
                preferred_idx += 1
            else:
                # 无法解析编号时走保守回退，保持可读文本块而不是伪造编号。
                if fn_content:
                    fallback_blocks.append(("脚注", fn_content))
                if tr_content:
                    fallback_blocks.append(("脚注翻译", tr_content))
                continue
        label = re.sub(r"[^A-Za-z0-9_-]", "-", str(label)).strip("-") or f"{fallback_prefix}-{idx + 1}"
        if label in existing_set:
            label = f"{label}-{fallback_prefix}"
        existing_set.add(label)
        labels_for_refs.append(label)

        merged = []
        if fn_content:
            merged.append(fn_content)
        if tr_content:
            merged.append(f"译：{tr_content}")
        merged_text = "\n".join(merged).strip()
        if merged_text:
            note_type, note_scope = _classify_note_scope(
                label=label,
                content=merged_text,
                inline_labels=preferred_labels or [],
                source_bp=source_bp,
                chapter_end_bp=chapter_end_bp,
                doc_last_bp=doc_last_bp,
                had_explicit_label=bool(fn_label or tr_label),
            )
            defs.append({
                "label": label,
                "content": merged_text,
                "source_bp": int(source_bp),
                "segment_idx": int(segment_idx),
                "chapter_index": chapter_index,
                "note_type": note_type,
                "note_scope": note_scope,
            })
        else:
            if _ensure_str(footnotes).strip():
                fallback_blocks.append(("脚注", _ensure_str(footnotes)))
            if _ensure_str(footnotes_translation).strip():
                fallback_blocks.append(("脚注翻译", _ensure_str(footnotes_translation)))
    return defs, labels_for_refs, fallback_blocks


def _extract_heading_number(text: str) -> int | None:
    match = re.match(r"^\s*(\d{1,4})\b", _ensure_str(text))
    return int(match.group(1)) if match else None


def _looks_like_backmatter_title(title: str) -> bool:
    return bool(_BACKMATTER_TITLE_RE.search(_ensure_str(title).strip()))


def _looks_like_container_title(title: str) -> bool:
    return bool(_CONTAINER_TITLE_RE.search(_ensure_str(title).strip()))


def _looks_like_content_title(title: str) -> bool:
    return bool(_CONTENT_TITLE_RE.search(_ensure_str(title).strip()))


def _collect_entry_lines(entry: dict, field: str) -> list[str]:
    lines: list[str] = []
    page_entries = entry.get("_page_entries") or []
    if page_entries:
        for pe in page_entries:
            raw = _ensure_str(pe.get(field, "")).strip()
            if raw:
                lines.extend(ln.strip() for ln in raw.split("\n") if ln.strip())
    else:
        raw = _ensure_str(entry.get(field, "")).strip()
        if raw:
            lines.extend(ln.strip() for ln in raw.split("\n") if ln.strip())
    return lines


def _extract_note_candidate_lines(lines: list[str]) -> list[str]:
    for idx, line in enumerate(lines):
        if _NOTES_HEADER_RE.match(line):
            return [ln.strip() for ln in lines[idx + 1:] if ln.strip()]
    return [ln.strip() for ln in lines if ln.strip()]


def _split_consecutive_bps(bps: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    current: list[int] = []
    for bp in sorted(int(v) for v in bps):
        if current and bp != current[-1] + 1:
            runs.append(current)
            current = [bp]
        else:
            current.append(bp)
    if current:
        runs.append(current)
    return runs


def _build_chapter_ranges_from_depth_map(
    toc_depth_map: dict[int, int],
    all_bps: list[int],
    toc_title_map: dict[int, str] | None = None,
) -> list[dict]:
    bps = sorted(int(bp) for bp in all_bps if bp is not None)
    if not bps:
        return []
    toc_items = sorted(
        (
            {
                "start_bp": int(bp),
                "depth": int(depth),
                "title": _ensure_str((toc_title_map or {}).get(int(bp), "")).strip(),
            }
            for bp, depth in (toc_depth_map or {}).items()
            if int(bp) > 0
        ),
        key=lambda item: (int(item["start_bp"]), int(item["depth"])),
    )
    if not toc_items:
        return []
    min_depth = min(item["depth"] for item in toc_items)
    top_items = [item for item in toc_items if item["depth"] == min_depth]
    if not top_items:
        return []

    effective_items: list[dict] = []
    for idx, item in enumerate(top_items):
        section_start = int(item["start_bp"])
        section_end = int(top_items[idx + 1]["start_bp"]) - 1 if idx + 1 < len(top_items) else bps[-1]
        child_items = [
            candidate for candidate in toc_items
            if section_start < int(candidate["start_bp"]) <= section_end
            and int(candidate["depth"]) == min_depth + 1
        ]
        should_promote_children = (
            len(child_items) >= 3
            and (section_end - section_start + 1) >= 40
            and (_looks_like_container_title(item["title"]) or not _looks_like_content_title(item["title"]))
        )
        if should_promote_children:
            effective_items.extend(child_items)
        else:
            effective_items.append(item)

    effective_items = sorted(
        {int(item["start_bp"]): item for item in effective_items if int(item["start_bp"]) > 0}.values(),
        key=lambda item: int(item["start_bp"]),
    )
    ranges = []
    for i, item in enumerate(effective_items):
        start_bp = int(item["start_bp"])
        end_bp = int(effective_items[i + 1]["start_bp"]) - 1 if i + 1 < len(effective_items) else bps[-1]
        ranges.append({
            "index": i,
            "start_bp": start_bp,
            "end_bp": int(end_bp),
            "title": item["title"],
            "depth": int(item["depth"]),
        })
    return ranges


def _resolve_chapter_for_bp(chapter_ranges: list[dict], bp: int) -> dict | None:
    for chapter in chapter_ranges:
        if int(chapter["start_bp"]) <= int(bp) <= int(chapter["end_bp"]):
            return chapter
    return None


def _resolve_previous_content_chapter(chapter_ranges: list[dict], bp: int) -> dict | None:
    candidate = None
    for chapter in chapter_ranges:
        if int(chapter["start_bp"]) > int(bp):
            break
        if _looks_like_backmatter_title(chapter.get("title", "")):
            continue
        candidate = chapter
    return candidate


# 尾注集合页判定：编号行占比阈值和最少条目数
_ENDNOTE_PAGE_MIN_RATIO = 0.5
_ENDNOTE_PAGE_MIN_ENTRIES = 3


def detect_endnote_collection_pages(
    entries: list[dict],
    chapter_ranges: list[dict],
) -> dict[int | None, list[int]]:
    """检测正文中的尾注集合页，返回 {chapter_index: [bp, ...]}。

    chapter_index=None 表示不属于任何章节（全书尾注区）。
    """
    result: dict[int | None, list[int]] = {}
    stats_by_bp: dict[int, dict] = {}
    for entry in entries or []:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp <= 0:
            continue
        raw_lines = _collect_entry_lines(entry, "original")
        all_orig = "\n".join(raw_lines).strip()
        if not all_orig:
            continue
        lines = [ln.strip() for ln in all_orig.split("\n") if ln.strip()]
        # 用宽松模式统计编号行数（既含严格格式也含无标点格式）
        numbered = sum(
            1 for ln in lines
            if _FN_LINE_NUM_RE.match(ln)
            or _FN_LINE_BRACKET_RE.match(ln)
            or _FN_LINE_LOOSE_RE.match(ln)
        )
        chapter = _resolve_chapter_for_bp(chapter_ranges, bp)
        cidx: int | None = int(chapter["index"]) if chapter else None
        ratio = numbered / max(len(lines), 1)
        has_notes_signal = any(
            _NOTES_HEADER_RE.match(line)
            or re.match(r"^\s*(?:notes?|注释|脚注|尾注)\b", line, re.IGNORECASE)
            for line in lines
        )
        chapter_end_bp = int(chapter["end_bp"]) if chapter else None
        near_chapter_end = bool(chapter_end_bp is not None and bp >= max(1, chapter_end_bp - 1))
        stats_by_bp[bp] = {
            "chapter_index": cidx,
            "chapter_end_bp": chapter_end_bp,
            "numbered": numbered,
            "ratio": ratio,
            "has_notes_signal": has_notes_signal,
            "near_chapter_end": near_chapter_end,
        }

    # 第一轮：原有强规则
    for bp, st in stats_by_bp.items():
        if st["numbered"] >= _ENDNOTE_PAGE_MIN_ENTRIES and st["ratio"] >= _ENDNOTE_PAGE_MIN_RATIO:
            result.setdefault(st["chapter_index"], []).append(bp)

    # 第二轮：章节尾部边界页放宽（仅低风险补漏，不影响正文中段）
    for bp, st in stats_by_bp.items():
        cidx = st["chapter_index"]
        if cidx is None:
            continue
        cur = result.setdefault(cidx, [])
        if bp in cur:
            continue
        if st["near_chapter_end"] and st["numbered"] >= 2 and (
            st["ratio"] >= 0.34 or st["has_notes_signal"]
        ):
            cur.append(bp)

    # 第二点五轮：正文+尾注混合起始页补漏。
    # 这类页往往只有 1 条尾注，但会出现 NOTES/尾注 标记，并紧邻已识别的尾注页。
    for bp, st in stats_by_bp.items():
        cidx = st["chapter_index"]
        cur = result.setdefault(cidx, [])
        if bp in cur:
            continue
        if st["numbered"] < 1 or not st["has_notes_signal"]:
            continue
        if any(abs(bp - hit_bp) <= 1 for hit_bp in cur):
            cur.append(bp)

    # 第三轮：紧邻已识别尾注页的续页放宽（同章节）
    for bp, st in stats_by_bp.items():
        cidx = st["chapter_index"]
        if cidx is None:
            continue
        cur = result.setdefault(cidx, [])
        if bp in cur:
            continue
        if st["numbered"] < 2:
            continue
        if st["ratio"] < 0.28:
            continue
        if any(abs(bp - hit_bp) <= 1 for hit_bp in cur):
            cur.append(bp)

    # 统一排序
    for cidx in list(result.keys()):
        cleaned_bps = sorted(set(result[cidx]))
        filtered_runs: list[int] = []
        for run in _split_consecutive_bps(cleaned_bps):
            if len(run) == 1:
                st = stats_by_bp.get(int(run[0]), {})
                if not st.get("has_notes_signal") and not st.get("near_chapter_end"):
                    continue
            filtered_runs.extend(run)
        result[cidx] = filtered_runs
        if not result[cidx]:
            result.pop(cidx, None)
    return result


def _match_chapter_heading_line(line: str, chapter_ranges: list[dict]) -> dict | None:
    raw = _ensure_str(line).strip()
    if not raw or _NOTES_HEADER_RE.match(raw):
        return None
    normalized_line = _normalize_heading_text_for_match(raw)
    if not normalized_line:
        return None
    best_match = None
    best_score = 0.0
    for chapter in chapter_ranges or []:
        title = _ensure_str(chapter.get("title", "")).strip()
        if not title or _looks_like_backmatter_title(title):
            continue
        normalized_title = _normalize_heading_text_for_match(title)
        if not normalized_title:
            continue
        if normalized_line == normalized_title:
            score = 1.0
        elif normalized_line in normalized_title or normalized_title in normalized_line:
            score = min(len(normalized_line), len(normalized_title)) / max(len(normalized_line), len(normalized_title), 1)
        else:
            score = SequenceMatcher(None, normalized_line, normalized_title).ratio()
        if score > best_score:
            best_score = score
            best_match = chapter
    if best_score >= 0.84:
        return best_match
    return None


def _merge_numbered_note_items(raw_items: list[tuple[str | None, str]]) -> tuple[list[int], dict[int, str]]:
    ordered_numbers: list[int] = []
    merged: dict[int, str] = {}
    current_num: int | None = None
    current_parts: list[str] = []

    def _repair_number(parsed_num: int, expected_num: int, content: str) -> int | None:
        text = _ensure_str(content).strip()
        if parsed_num == expected_num:
            return parsed_num
        # 同一章节尾注通常单调递增；若 OCR 把高位数字吞掉，常会出现 31 -> 3、28 -> 22 这类回退。
        if parsed_num < expected_num and len(text) >= 8:
            return expected_num
        # PDF 文字层或 OCR 续行有时会把年份/页码拆到行首，避免把 2019 / 2024 之类误识别成新尾注。
        if parsed_num >= 1000:
            return None
        # OCR 也会把 131 识别成 151 这类“中间位飘移”，优先回正到期望序号。
        if (
            parsed_num > expected_num
            and len(text) >= 8
            and len(str(parsed_num)) == len(str(expected_num))
            and str(parsed_num)[0] == str(expected_num)[0]
            and str(parsed_num)[-1] == str(expected_num)[-1]
        ):
            return expected_num
        return parsed_num

    def _flush_current() -> None:
        nonlocal current_num, current_parts
        if current_num is None:
            return
        text = " ".join(part for part in current_parts if part).strip()
        if current_num not in ordered_numbers:
            ordered_numbers.append(current_num)
        if text:
            existing = merged.get(current_num, "").strip()
            merged[current_num] = f"{existing} {text}".strip() if existing else text
        else:
            merged.setdefault(current_num, "")

    for label, content in raw_items:
        if label is not None and str(label).isdigit():
            parsed_num = int(label)
            if current_num is not None:
                repaired_num = _repair_number(parsed_num, current_num + 1, content)
                if repaired_num is None:
                    if content:
                        current_parts.append(content)
                    continue
                parsed_num = repaired_num
            _flush_current()
            current_num = parsed_num
            current_parts = [content] if content else []
            continue
        if current_num is not None and content:
            current_parts.append(content)
    _flush_current()
    return ordered_numbers, merged


def _load_pdf_note_lines_by_bp(doc_id: str, bps: list[int]) -> dict[int, list[str]]:
    doc_key = _ensure_str(doc_id).strip()
    wanted_bps = sorted({int(bp) for bp in (bps or []) if int(bp) > 0})
    if not doc_key or not wanted_bps:
        return {}
    pdf_path = get_pdf_path(doc_key)
    if not pdf_path or not os.path.exists(pdf_path):
        return {}

    page_cache: dict[int, list[str]] | None = None
    request_cache = _get_doc_request_cache(doc_key)
    if request_cache is not None:
        page_cache = request_cache.setdefault("pdf_note_lines_by_bp", {})

    missing_bps = (
        [bp for bp in wanted_bps if bp not in page_cache]
        if page_cache is not None
        else wanted_bps
    )
    if missing_bps:
        try:
            reader = PdfReader(pdf_path)
        except Exception:
            return {}
        page_count = len(reader.pages)
        loaded_lines: dict[int, list[str]] = {}
        for bp in missing_bps:
            if bp <= 0 or bp > page_count:
                loaded_lines[bp] = []
                continue
            try:
                raw_text = _ensure_str(reader.pages[bp - 1].extract_text() or "")
            except Exception:
                raw_text = ""
            loaded_lines[bp] = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        if page_cache is not None:
            page_cache.update(loaded_lines)
        else:
            page_cache = loaded_lines
    return {
        bp: list((page_cache or {}).get(bp) or [])
        for bp in wanted_bps
        if (page_cache or {}).get(bp)
    }


def _resolve_endnote_run_default_chapter(run_pages: list[dict], chapter_ranges: list[dict]) -> dict | None:
    if not run_pages:
        return None
    default_chapter = _resolve_previous_content_chapter(chapter_ranges, int(run_pages[0]["bp"]))
    if default_chapter is None:
        default_chapter = _resolve_chapter_for_bp(chapter_ranges, int(run_pages[0]["bp"]))
        if default_chapter and _looks_like_backmatter_title(default_chapter.get("title", "")):
            default_chapter = _resolve_previous_content_chapter(chapter_ranges, int(run_pages[0]["bp"]))
    return default_chapter


def _new_endnote_section(chapter: dict | None) -> dict:
    return {
        "chapter_index": int(chapter["index"]) if chapter and chapter.get("index") is not None else None,
        "chapter_title": _ensure_str(chapter.get("title", "")).strip() if chapter else "",
        "chapter_start_bp": int(chapter["start_bp"]) if chapter and chapter.get("start_bp") is not None else None,
        "heading_number": _extract_heading_number(chapter.get("title", "")) if chapter else None,
        "orig_lines": [],
    }


def _split_endnote_run_pages_into_sections(
    run_pages: list[dict],
    chapter_ranges: list[dict],
    line_key: str,
    forced_chapter: dict | None = None,
) -> list[dict]:
    if not run_pages:
        return []
    default_chapter = forced_chapter or _resolve_endnote_run_default_chapter(run_pages, chapter_ranges)
    allow_heading_split = forced_chapter is None
    sections: list[dict] = [_new_endnote_section(default_chapter)]
    for page in run_pages:
        page_lines = _extract_note_candidate_lines(page.get(line_key) or [])
        for line in page_lines:
            matched_chapter = _match_chapter_heading_line(line, chapter_ranges) if allow_heading_split else None
            if matched_chapter is not None:
                current = sections[-1]
                matched_index = int(matched_chapter["index"])
                if current["orig_lines"] or current["chapter_index"] != matched_index:
                    sections.append(_new_endnote_section(matched_chapter))
                else:
                    current["chapter_index"] = matched_index
                    current["chapter_title"] = _ensure_str(matched_chapter.get("title", "")).strip()
                    current["chapter_start_bp"] = int(matched_chapter["start_bp"])
                    current["heading_number"] = _extract_heading_number(matched_chapter.get("title", ""))
                continue
            sections[-1]["orig_lines"].append(line)
    return sections


def _prepare_endnote_sections(raw_sections: list[dict]) -> list[dict]:
    prepared_sections: list[dict] = []
    for section in raw_sections:
        orig_order, orig_map = _merge_numbered_note_items(
            _split_footnote_items("\n".join(section["orig_lines"]), strict=False)
        )
        if not orig_order and not orig_map:
            continue
        prepared_sections.append({
            **section,
            "note_numbers": orig_order,
            "orig_map": orig_map,
        })
    return prepared_sections


def _merge_pdf_endnote_sections(prepared_sections: list[dict], pdf_sections: list[dict]) -> list[dict]:
    if not pdf_sections:
        return prepared_sections

    def _should_accept_pdf_number(number: int, existing_numbers: list[int]) -> bool:
        if not existing_numbers:
            return True
        if number in set(existing_numbers):
            return False
        first = existing_numbers[0]
        last = existing_numbers[-1]
        if number < first:
            return number >= max(1, first - 2)
        if number > last:
            return number <= last + 2
        for left, right in zip(existing_numbers, existing_numbers[1:]):
            if left < number < right:
                return (right - left) >= 2
        return False

    def _find_target(pdf_section: dict, section_idx: int) -> dict | None:
        chapter_index = pdf_section.get("chapter_index")
        if chapter_index is not None:
            same_chapter = [
                section for section in prepared_sections
                if section.get("chapter_index") == chapter_index
            ]
            if len(same_chapter) == 1:
                return same_chapter[0]
            if same_chapter:
                return same_chapter[0]
        if 0 <= section_idx < len(prepared_sections):
            return prepared_sections[section_idx]
        return None

    for section_idx, pdf_section in enumerate(pdf_sections):
        target = _find_target(pdf_section, section_idx)
        if target is None:
            target = {
                "chapter_index": pdf_section.get("chapter_index"),
                "chapter_title": pdf_section.get("chapter_title", ""),
                "chapter_start_bp": pdf_section.get("chapter_start_bp"),
                "heading_number": pdf_section.get("heading_number"),
                "orig_lines": [],
                "note_numbers": [],
                "orig_map": {},
                "tr_map": {},
            }
            prepared_sections.append(target)
        if not target.get("chapter_title") and pdf_section.get("chapter_title"):
            target["chapter_title"] = pdf_section["chapter_title"]
        if target.get("chapter_start_bp") is None and pdf_section.get("chapter_start_bp") is not None:
            target["chapter_start_bp"] = pdf_section["chapter_start_bp"]
        merged_numbers = {int(v) for v in target.get("note_numbers", [])}
        existing_numbers = sorted(merged_numbers)
        target_orig_map = target.setdefault("orig_map", {})
        for number, content in (pdf_section.get("orig_map") or {}).items():
            if not _ensure_str(content).strip():
                continue
            if not _should_accept_pdf_number(int(number), existing_numbers):
                continue
            if not _ensure_str(target_orig_map.get(number, "")).strip():
                target_orig_map[int(number)] = content
            merged_numbers.add(int(number))
            existing_numbers = sorted(merged_numbers)
        target["note_numbers"] = sorted(merged_numbers)
    prepared_sections.sort(
        key=lambda section: (
            section.get("chapter_index") is None,
            int(section.get("chapter_start_bp") or 10**9),
            _ensure_str(section.get("chapter_title", "")),
        )
    )
    return prepared_sections


def _clone_endnote_section(section: dict) -> dict:
    return {
        "chapter_index": section.get("chapter_index"),
        "chapter_title": section.get("chapter_title", ""),
        "chapter_start_bp": section.get("chapter_start_bp"),
        "heading_number": section.get("heading_number"),
        "orig_lines": list(section.get("orig_lines") or []),
        "note_numbers": list(section.get("note_numbers") or []),
        "orig_map": dict(section.get("orig_map") or {}),
        "tr_map": dict(section.get("tr_map") or {}),
    }


def _endnote_section_score(section: dict | None) -> float:
    if not section:
        return float("-inf")
    note_numbers = [int(v) for v in (section.get("note_numbers") or [])]
    if not note_numbers:
        return float("-inf")
    uniq = sorted(set(note_numbers))
    span = max(uniq[-1] - uniq[0] + 1, 1)
    density = len(uniq) / span
    start_penalty = min(max(uniq[0] - 1, 0), 8) * 0.08
    order_resets = sum(
        1 for prev, cur in zip(note_numbers, note_numbers[1:])
        if int(cur) < int(prev)
    )
    return density - start_penalty - (order_resets * 0.2)


def _should_prefer_pdf_section(ocr_section: dict | None, pdf_section: dict | None) -> bool:
    if not pdf_section:
        return False
    if not ocr_section:
        return True
    note_numbers = [int(v) for v in (ocr_section.get("note_numbers") or [])]
    if not note_numbers:
        return True
    uniq = sorted(set(note_numbers))
    span = max(uniq[-1] - uniq[0] + 1, 1)
    density = len(uniq) / span
    order_resets = sum(
        1 for prev, cur in zip(note_numbers, note_numbers[1:])
        if int(cur) < int(prev)
    )
    has_large_outlier = any(int(v) >= 1000 for v in note_numbers) or (uniq[-1] - len(uniq) >= 15)
    ocr_is_suspicious = (
        uniq[0] > 1
        or order_resets > 0
        or density < 0.9
        or has_large_outlier
    )
    if not ocr_is_suspicious:
        return False
    return _endnote_section_score(pdf_section) >= (_endnote_section_score(ocr_section) - 0.05)


def _select_base_endnote_sections(ocr_sections: list[dict], pdf_sections: list[dict]) -> list[dict]:
    if not pdf_sections:
        return ocr_sections
    if not ocr_sections:
        return pdf_sections

    selected_sections: list[dict] = []
    used_pdf_indices: set[int] = set()

    def _match_pdf_section(ocr_section: dict, ocr_idx: int) -> tuple[int | None, dict | None]:
        chapter_index = ocr_section.get("chapter_index")
        if chapter_index is not None:
            for pdf_idx, pdf_section in enumerate(pdf_sections):
                if pdf_idx in used_pdf_indices:
                    continue
                if pdf_section.get("chapter_index") == chapter_index:
                    return pdf_idx, pdf_section
        if ocr_idx < len(pdf_sections) and ocr_idx not in used_pdf_indices:
            return ocr_idx, pdf_sections[ocr_idx]
        return None, None

    for ocr_idx, ocr_section in enumerate(ocr_sections):
        pdf_idx, pdf_section = _match_pdf_section(ocr_section, ocr_idx)
        if pdf_idx is None or pdf_section is None:
            selected_sections.append(_clone_endnote_section(ocr_section))
            continue
        used_pdf_indices.add(pdf_idx)
        if _should_prefer_pdf_section(ocr_section, pdf_section):
            base_section = _clone_endnote_section(pdf_section)
            supplement_section = ocr_section
        else:
            base_section = _clone_endnote_section(ocr_section)
            supplement_section = pdf_section
        selected_sections.extend(_merge_pdf_endnote_sections([base_section], [supplement_section]))

    for pdf_idx, pdf_section in enumerate(pdf_sections):
        if pdf_idx in used_pdf_indices:
            continue
        selected_sections.append(_clone_endnote_section(pdf_section))
    return selected_sections


def _build_endnote_run_sections(
    run_pages: list[dict],
    chapter_ranges: list[dict],
    forced_chapter: dict | None = None,
) -> list[dict]:
    if not run_pages:
        return []
    all_tr_lines: list[str] = []
    for page in run_pages:
        all_tr_lines.extend(_extract_note_candidate_lines(page["tr_lines"]))

    ocr_sections = _prepare_endnote_sections(
        _split_endnote_run_pages_into_sections(
            run_pages,
            chapter_ranges,
            line_key="orig_lines",
            forced_chapter=forced_chapter,
        )
    )
    pdf_sections = _prepare_endnote_sections(
        _split_endnote_run_pages_into_sections(
            run_pages,
            chapter_ranges,
            line_key="pdf_orig_lines",
            forced_chapter=forced_chapter,
        )
    )
    prepared_sections = _select_base_endnote_sections(ocr_sections, pdf_sections)

    if not prepared_sections:
        return []

    tr_items = _split_footnote_items("\n".join(all_tr_lines), strict=False)
    assigned_tr_items: list[list[tuple[str | None, str]]] = [[] for _ in prepared_sections]
    section_idx = 0
    current_has_numeric = False
    last_numeric: int | None = None

    def _peek_next_numeric(from_idx: int) -> int | None:
        for future_label, _future_content in tr_items[from_idx:]:
            if future_label is not None and str(future_label).isdigit():
                return int(future_label)
        return None

    for item_idx, (label, content) in enumerate(tr_items):
        if section_idx >= len(prepared_sections):
            section_idx = len(prepared_sections) - 1
        if label is not None and str(label).isdigit():
            number = int(label)
            skipped_heading = False
            while section_idx + 1 < len(prepared_sections):
                next_section = prepared_sections[section_idx + 1]
                next_first = next_section["note_numbers"][0] if next_section["note_numbers"] else None
                next_heading = next_section.get("heading_number")
                next_numeric = _peek_next_numeric(item_idx + 1)
                if (
                    current_has_numeric
                    and next_heading is not None
                    and number == int(next_heading)
                    and next_first is not None
                    and next_numeric == int(next_first)
                ):
                    skipped_heading = True
                    break
                if (
                    current_has_numeric
                    and next_first is not None
                    and number == int(next_first)
                    and last_numeric is not None
                    and number < last_numeric
                ):
                    section_idx += 1
                    current_has_numeric = False
                    last_numeric = None
                    continue
                break
            if skipped_heading:
                continue
            assigned_tr_items[section_idx].append((label, content))
            current_has_numeric = True
            last_numeric = number
            continue
        if current_has_numeric or assigned_tr_items[section_idx]:
            assigned_tr_items[section_idx].append((label, content))

    for section, raw_tr_section_items in zip(prepared_sections, assigned_tr_items):
        _tr_order, tr_map = _merge_numbered_note_items(raw_tr_section_items)
        section["tr_map"] = tr_map

    return prepared_sections


def _normalize_note_title_hint(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", _ensure_str(text)).lower()
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", normalized).strip()


def _match_chapter_by_note_title(chapter_ranges: list[dict], title: str) -> dict | None:
    target = _normalize_note_title_hint(title)
    if not target:
        return None
    best = None
    best_score = 0.0
    for chapter in chapter_ranges or []:
        chapter_title = _ensure_str(chapter.get("title", "")).strip()
        if not chapter_title or _looks_like_backmatter_title(chapter_title):
            continue
        candidate = _normalize_note_title_hint(chapter_title)
        if not candidate:
            continue
        if target in candidate or candidate in target:
            return chapter
        score = SequenceMatcher(None, target, candidate).ratio()
        if score > best_score:
            best = chapter
            best_score = score
    return best if best_score >= 0.58 else None


def _build_structured_endnote_groups(
    entries: list[dict],
    chapter_ranges: list[dict] | None,
    pages: list[dict] | None,
) -> tuple[list[dict], set[int]]:
    if not pages:
        return [], set()
    page_by_bp = {
        int(page.get("bookPage") or 0): page
        for page in (pages or [])
        if int(page.get("bookPage") or 0) > 0
    }
    groups_by_key: dict[str, dict] = {}
    group_order: list[str] = []
    covered_bps: set[int] = set()

    for entry in entries or []:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp <= 0:
            continue
        page = page_by_bp.get(bp) or {}
        note_scan = page.get("_note_scan") if isinstance(page, dict) else {}
        segment_items = []
        for seg_idx, pe in enumerate(entry.get("_page_entries") or []):
            if _ensure_str(pe.get("_note_kind", "")).strip() != "endnote":
                continue
            number = pe.get("_note_number")
            try:
                number = int(number)
            except (TypeError, ValueError):
                continue
            orig = _ensure_str(pe.get("original", "")).strip()
            tr = _ensure_str(pe.get("translation", "")).strip()
            if not orig and not tr:
                continue
            segment_items.append({
                "order": seg_idx,
                "number": number,
                "orig": orig,
                "tr": tr,
                "marker": _ensure_str(pe.get("_note_marker", "")).strip(),
                "section_title": _ensure_str(pe.get("_note_section_title", "")).strip(),
                "confidence": float(pe.get("_note_confidence", 0.0) or 0.0),
            })
        if not segment_items:
            continue
        covered_bps.add(bp)
        page_kind = _ensure_str((note_scan or {}).get("page_kind", "")).strip()
        hint_title = ""
        for item in segment_items:
            if item["section_title"]:
                hint_title = item["section_title"]
                break
        if not hint_title:
            for hint in (note_scan or {}).get("section_hints") or []:
                hint = _ensure_str(hint).strip()
                if hint and not _looks_like_backmatter_title(hint):
                    hint_title = hint
                    break
        chapter = _match_chapter_by_note_title(chapter_ranges or [], hint_title) if hint_title else None
        if chapter is None and page_kind == "mixed_body_endnotes":
            chapter = _resolve_chapter_for_bp(chapter_ranges or [], bp)
            if chapter and _looks_like_backmatter_title(chapter.get("title", "")):
                chapter = None
        chapter_index = int(chapter["index"]) if chapter is not None else None
        chapter_title = _ensure_str(chapter.get("title", "")).strip() if chapter is not None else hint_title
        chapter_start_bp = chapter.get("start_bp") if chapter is not None else None
        if chapter_index is not None:
            group_key = f"chapter:{chapter_index}"
        elif hint_title:
            group_key = f"hint:{_normalize_note_title_hint(hint_title)}"
        else:
            group_key = f"book:{bp}"
        if group_key not in groups_by_key:
            groups_by_key[group_key] = {
                "group_key": group_key,
                "chapter_index": chapter_index,
                "chapter_title": chapter_title,
                "chapter_start_bp": chapter_start_bp,
                "note_scope": "chapter_end" if chapter_index is not None else "book_end",
                "notes": {},
            }
            group_order.append(group_key)
        group = groups_by_key[group_key]
        if not group.get("chapter_title") and chapter_title:
            group["chapter_title"] = chapter_title
        if group.get("chapter_start_bp") is None and chapter_start_bp is not None:
            group["chapter_start_bp"] = chapter_start_bp
        for item in sorted(segment_items, key=lambda data: (data["number"], data["order"])):
            note_entry = group["notes"].setdefault(
                int(item["number"]),
                {
                    "number": int(item["number"]),
                    "orig": "",
                    "tr": "",
                    "source_bps": [bp],
                },
            )
            if bp not in note_entry["source_bps"]:
                note_entry["source_bps"].append(bp)
            if item["orig"] and not note_entry.get("orig"):
                note_entry["orig"] = item["orig"]
            if item["tr"] and not note_entry.get("tr"):
                note_entry["tr"] = item["tr"]

    groups = [groups_by_key[key] for key in group_order]
    groups.sort(
        key=lambda group: (
            group.get("chapter_index") is None,
            int(group.get("chapter_start_bp") or 10**9),
            _ensure_str(group.get("chapter_title", "")),
            _ensure_str(group.get("group_key", "")),
        )
    )
    return groups, covered_bps


def build_endnote_index(
    entries: list[dict],
    endnote_page_map: dict[int | None, list[int]],
    chapter_ranges: list[dict] | None = None,
    pages: list[dict] | None = None,
) -> dict:
    """从尾注集合页解析章节尾注，返回分组后的尾注索引。"""
    structured_groups, structured_bps = _build_structured_endnote_groups(entries, chapter_ranges, pages)
    if not endnote_page_map and not structured_groups:
        return {"groups": []}

    entry_by_bp: dict[int, dict] = {}
    for entry in entries or []:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp > 0:
            entry_by_bp[bp] = entry
    doc_id = _ensure_str(next(
        (
            entry.get("doc_id")
            for entry in entries or []
            if _ensure_str(entry.get("doc_id")).strip()
        ),
        "",
    )).strip()
    pdf_note_lines_by_bp = _load_pdf_note_lines_by_bp(
        doc_id,
        [bp for bps in (endnote_page_map or {}).values() for bp in (bps or [])],
    )

    groups_by_key: dict[str, dict] = {
        _ensure_str(group.get("group_key", "")): dict(group)
        for group in structured_groups
        if _ensure_str(group.get("group_key", ""))
    }
    group_order: list[str] = [
        _ensure_str(group.get("group_key", ""))
        for group in structured_groups
        if _ensure_str(group.get("group_key", ""))
    ]

    for _cidx, bps in endnote_page_map.items():
        candidate_chapter = None
        if _cidx is not None:
            candidate_chapter = next(
                (
                    chapter for chapter in (chapter_ranges or [])
                    if chapter.get("index") == _cidx
                ),
                None,
            )
        for run_bps in _split_consecutive_bps(bps):
            if run_bps and all(int(bp) in structured_bps for bp in run_bps):
                continue
            forced_chapter = None
            if candidate_chapter and not _looks_like_backmatter_title(candidate_chapter.get("title", "")):
                chapter_end_bp = int(candidate_chapter.get("end_bp") or 0)
                if int(run_bps[0]) <= chapter_end_bp + 2:
                    forced_chapter = candidate_chapter
            run_pages = []
            for bp in run_bps:
                entry = entry_by_bp.get(bp)
                if not entry:
                    continue
                run_pages.append({
                    "bp": int(bp),
                    "orig_lines": _collect_entry_lines(entry, "original"),
                    "tr_lines": _collect_entry_lines(entry, "translation"),
                    "pdf_orig_lines": list(pdf_note_lines_by_bp.get(int(bp), [])),
                })
            for section in _build_endnote_run_sections(
                run_pages,
                chapter_ranges or [],
                forced_chapter=forced_chapter,
            ):
                all_numbers = sorted(set(section.get("orig_map", {})) | set(section.get("tr_map", {})))
                if not all_numbers:
                    continue
                chapter_index = section.get("chapter_index")
                if chapter_index is None:
                    group_key = f"book:{run_bps[0]}:{len(group_order)}"
                else:
                    group_key = f"chapter:{int(chapter_index)}"
                if group_key not in groups_by_key:
                    groups_by_key[group_key] = {
                        "group_key": group_key,
                        "chapter_index": chapter_index,
                        "chapter_title": section.get("chapter_title", ""),
                        "chapter_start_bp": section.get("chapter_start_bp"),
                        "note_scope": "chapter_end" if chapter_index is not None else "book_end",
                        "notes": {},
                    }
                    group_order.append(group_key)
                group = groups_by_key[group_key]
                if not group.get("chapter_title") and section.get("chapter_title"):
                    group["chapter_title"] = section["chapter_title"]
                if group.get("chapter_start_bp") is None and section.get("chapter_start_bp") is not None:
                    group["chapter_start_bp"] = section["chapter_start_bp"]
                for number in all_numbers:
                    note_entry = group["notes"].setdefault(
                        int(number),
                        {
                            "number": int(number),
                            "orig": "",
                            "tr": "",
                            "source_bps": list(run_bps),
                        },
                    )
                    if section.get("orig_map", {}).get(number) and not note_entry.get("orig"):
                        note_entry["orig"] = section["orig_map"][number]
                    if section.get("tr_map", {}).get(number) and not note_entry.get("tr"):
                        note_entry["tr"] = section["tr_map"][number]

    groups = [groups_by_key[key] for key in group_order]
    groups.sort(
        key=lambda group: (
            group.get("chapter_index") is None,
            int(group.get("chapter_start_bp") or 10**9),
            _ensure_str(group.get("chapter_title", "")),
        )
    )
    return {"groups": groups}


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


def _resolve_heading_toc_match(pe: dict, bp: int, toc_depth_map: dict) -> tuple[int, int] | None:
    if not toc_depth_map:
        return None
    probes: list[int] = []
    start_bp = pe.get("_startBP")
    if start_bp is not None:
        try:
            probes.append(int(start_bp))
        except (TypeError, ValueError):
            pass
    try:
        probes.append(int(bp))
    except (TypeError, ValueError):
        pass
    probes = [p for p in probes if p > 0]
    seen = set()
    probes = [p for p in probes if not (p in seen or seen.add(p))]
    for probe in probes:
        depth = toc_depth_map.get(probe)
        if depth is not None:
            return int(probe), int(depth)
    # 容错：目录锚点与段起始页可能有 1 页偏移，允许就近匹配。
    keys = sorted(int(k) for k in toc_depth_map.keys())
    best_depth = None
    best_dist = None
    for probe in probes:
        for k in keys:
            dist = abs(int(k) - int(probe))
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_depth = int(toc_depth_map[k])
    if best_dist is not None and best_dist <= 1 and best_depth is not None:
        # 这里返回近邻页码与对应 depth
        nearest_bp = None
        for probe in probes:
            for k in keys:
                if abs(int(k) - int(probe)) == best_dist:
                    nearest_bp = int(k)
                    break
            if nearest_bp is not None:
                break
        if nearest_bp is not None:
            return nearest_bp, best_depth
    return None


def _normalize_heading_text_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", _ensure_str(text)).lower()
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", normalized).strip()


def _heading_matches_toc_title(orig: str, tr: str, toc_title: str) -> bool:
    title = _normalize_heading_text_for_match(toc_title)
    if not title:
        return True
    orig_norm = _normalize_heading_text_for_match(orig)
    tr_norm = _normalize_heading_text_for_match(tr)
    haystack = f"{orig_norm} {tr_norm}".strip()
    if not haystack:
        return False
    if title in haystack:
        return True
    ratio = SequenceMatcher(None, haystack, title).ratio()
    if ratio >= 0.5:
        return True
    tokens = [tok for tok in title.split() if len(tok) >= 4]
    if tokens and any(tok in haystack for tok in tokens):
        return True
    return False


def _resolve_heading_level(pe: dict, toc_depth_map: dict, min_non_toc_level: int = 1, bp: int = 0) -> tuple[int, int | None]:
    """根据 TOC depth map 确定段落的 Markdown 标题层级。

    - TOC 命中：严格使用 depth+1，不受 OCR 检测值影响。
    - TOC 未命中但 OCR 判定为标题：层级不低于 min_non_toc_level，
      避免非目录标题与目录层级混淆。
    返回 0 表示普通正文，>0 表示标题。
    """
    hlevel = int(pe.get("heading_level", 0) or 0)
    if hlevel <= 0:
        return 0, None
    if not toc_depth_map:
        return hlevel, None
    match = _resolve_heading_toc_match(pe, bp=bp, toc_depth_map=toc_depth_map)
    if match is not None:
        matched_bp, depth = match
        return max(1, int(depth) + 1), matched_bp
    # 有目录时，标题以目录为准；未命中目录的 OCR 标题统一降级为正文。
    return 0, None


def _looks_like_heading_noise(text: str) -> bool:
    content = _ensure_str(text).strip()
    if not content:
        return True
    if content in {"*", "#", "-", "—", "_"}:
        return True
    if re.match(r"^\d{1,3}[\.\)、]\s+", content):
        return True
    return False


def _should_demote_heading(
    *,
    hlevel: int,
    toc_depth_map: dict,
    bp: int,
    start_bp: int | None,
    title_text: str,
) -> bool:
    if hlevel <= 0:
        return False
    if _looks_like_heading_noise(title_text):
        return True
    if not toc_depth_map:
        return False

    # 有目录时，目录首章之前的前置页标题统一降级为正文，避免封面/版权页被导成大量 ###。
    top_level_starts = sorted(int(k) for k, depth in toc_depth_map.items() if int(depth) == 0)
    if top_level_starts:
        first_chapter_bp = top_level_starts[0]
        if int(bp) < int(first_chapter_bp):
            return True

    if start_bp is not None and int(start_bp) in toc_depth_map:
        return False
    return False


def _normalize_endnote_registry(
    endnote_index: dict | None,
    chapter_ranges: list[dict],
    toc_title_map: dict[int, str] | None,
) -> dict:
    if not endnote_index:
        return {
            "groups": [],
            "groups_by_chapter": {},
            "book_groups": [],
            "duplicate_chapter_numbers": set(),
            "global_duplicate_numbers": set(),
        }

    if isinstance(endnote_index, dict) and "groups" in endnote_index:
        raw_groups = list(endnote_index.get("groups") or [])
    else:
        raw_groups = []
        for chapter_index, notes in (endnote_index or {}).items():
            chapter = next(
                (item for item in chapter_ranges if item.get("index") == chapter_index),
                None,
            )
            chapter_title = ""
            chapter_start_bp = None
            if chapter is not None:
                chapter_title = _ensure_str(chapter.get("title", "")).strip()
                chapter_start_bp = chapter.get("start_bp")
            if not chapter_title and chapter_start_bp is not None and toc_title_map:
                chapter_title = _ensure_str(toc_title_map.get(int(chapter_start_bp), "")).strip()
            raw_groups.append({
                "group_key": f"chapter:{chapter_index}" if chapter_index is not None else "book:legacy",
                "chapter_index": chapter_index,
                "chapter_title": chapter_title,
                "chapter_start_bp": chapter_start_bp,
                "note_scope": "chapter_end" if chapter_index is not None else "book_end",
                "notes": {
                    int(number): {
                        "number": int(number),
                        "orig": _ensure_str(value.get("orig", "")),
                        "tr": _ensure_str(value.get("tr", "")),
                    }
                    for number, value in (notes or {}).items()
                    if str(number).isdigit()
                },
            })

    groups: list[dict] = []
    chapter_number_counts: dict[int, int] = {}
    global_number_counts: dict[int, int] = {}
    for group in raw_groups:
        notes = {
            int(number): {
                "number": int(number),
                "orig": _ensure_str(value.get("orig", "")),
                "tr": _ensure_str(value.get("tr", "")),
            }
            for number, value in (group.get("notes") or {}).items()
            if str(number).isdigit()
        }
        if not notes:
            continue
        normalized_group = {
            "group_key": _ensure_str(group.get("group_key")).strip() or (
                f"chapter:{group.get('chapter_index')}"
                if group.get("chapter_index") is not None
                else f"book:{len(groups)}"
            ),
            "chapter_index": group.get("chapter_index"),
            "chapter_title": _ensure_str(group.get("chapter_title", "")).strip(),
            "chapter_start_bp": group.get("chapter_start_bp"),
            "note_scope": _ensure_str(group.get("note_scope", "")).strip() or (
                "chapter_end" if group.get("chapter_index") is not None else "book_end"
            ),
            "notes": notes,
        }
        if (
            not normalized_group["chapter_title"]
            and normalized_group["chapter_index"] is not None
        ):
            chapter = next(
                (
                    item for item in chapter_ranges
                    if item.get("index") == normalized_group["chapter_index"]
                ),
                None,
            )
            if chapter is not None:
                normalized_group["chapter_title"] = _ensure_str(chapter.get("title", "")).strip()
                normalized_group["chapter_start_bp"] = chapter.get("start_bp")
        groups.append(normalized_group)
        for number in notes:
            global_number_counts[number] = global_number_counts.get(number, 0) + 1
            if normalized_group["chapter_index"] is not None:
                chapter_number_counts[number] = chapter_number_counts.get(number, 0) + 1

    groups.sort(
        key=lambda group: (
            group.get("chapter_index") is None,
            int(group.get("chapter_start_bp") or 10**9),
            _ensure_str(group.get("chapter_title", "")),
        )
    )
    chapter_ordinal = 0
    for group in groups:
        if group.get("chapter_index") is None:
            group["chapter_label_prefix"] = ""
            continue
        group["chapter_label_prefix"] = f"ch{chapter_ordinal:02d}"
        chapter_ordinal += 1
    groups_by_chapter = {
        int(group["chapter_index"]): group
        for group in groups
        if group.get("chapter_index") is not None
    }
    book_groups = [group for group in groups if group.get("chapter_index") is None]
    return {
        "groups": groups,
        "groups_by_chapter": groups_by_chapter,
        "book_groups": book_groups,
        "duplicate_chapter_numbers": {
            number for number, count in chapter_number_counts.items() if count > 1
        },
        "global_duplicate_numbers": {
            number for number, count in global_number_counts.items() if count > 1
        },
    }


def _build_endnote_label(group: dict, number: int, registry: dict) -> str:
    num = int(number)
    chapter_index = group.get("chapter_index")
    if chapter_index is not None and num in set(registry.get("duplicate_chapter_numbers", set())):
        prefix = _ensure_str(group.get("chapter_label_prefix", "")).strip() or f"ch{int(chapter_index)}"
        return f"{prefix}-{num}"
    if chapter_index is None and num in set(registry.get("global_duplicate_numbers", set())):
        return f"book-{num}"
    return str(num)


def gen_markdown(
    entries: list,
    toc_depth_map: dict | None = None,
    page_ranges: list[tuple[int, int]] | None = None,
    skip_bps: set[int] | None = None,
    toc_title_map: dict[int, str] | None = None,
    endnote_index: dict | None = None,
    endnote_page_bps: set[int] | None = None,
) -> str:
    """生成 Markdown 导出内容。

    Args:
        entries: 翻译条目列表。
        toc_depth_map: {book_page: depth} 查找表，由 build_toc_depth_map() 生成。
                       传入后用于修正标题的 # 层级；不传则沿用 OCR 检测值。
        page_ranges: [(start_bp, end_bp), ...] 指定只导出哪些页码区间；
                     None 表示导出全部。
        endnote_index: {chapter_index: {number: {orig, tr}}} 尾注索引，
                       由 build_endnote_index() 生成。传入后正文 [^n] 引用
                       会与索引中的定义严格对应。
        endnote_page_bps: 检测到的尾注集合页页码集合，这些页不输出正文内容。
    """
    dm = toc_depth_map or {}
    # 非 TOC 标题的最低层级 = TOC 最深 depth 对应的 # 数 + 1
    # 例：TOC 有 depth=0,1 → max_toc_level=2 → 非 TOC 标题至少 ### (3)
    if dm:
        min_non_toc_level = max(depth + 1 for depth in dm.values()) + 1
    else:
        min_non_toc_level = 1

    def _in_ranges(bp: int) -> bool:
        if page_ranges is None:
            return True
        return any(s <= bp <= e for s, e in page_ranges)

    skip_set = {int(bp) for bp in (skip_bps or set()) if int(bp) > 0}
    # 尾注集合页完全隐藏——不输出正文，仅在尾注区块以 [^n]: 定义形式出现
    if endnote_page_bps:
        skip_set.update(int(bp) for bp in endnote_page_bps if int(bp) > 0)
    entries_for_export: list[dict] = []
    for e in entries:
        bp = int(e.get("_pageBP") or e.get("book_page") or 0)
        if bp > 0 and bp in skip_set:
            continue
        entries_for_export.append(e)

    md_lines: list[str] = []
    all_bps = [
        int(e.get("_pageBP") or e.get("book_page") or 0)
        for e in entries_for_export
        if int(e.get("_pageBP") or e.get("book_page") or 0) > 0
    ]
    if not all_bps:
        return ""
    doc_last_bp = max(all_bps) if all_bps else 1
    chapter_ranges = _build_chapter_ranges_from_depth_map(dm, all_bps, toc_title_map=toc_title_map)
    endnote_registry = _normalize_endnote_registry(endnote_index, chapter_ranges, toc_title_map)
    used_endnote_chapter_groups: set[int] = set()
    used_endnote_book_groups: set[str] = set()
    chapter_endnotes: dict[int, list[dict]] = {}
    book_endnotes: list[dict] = []
    seen_footnote_labels: set[str] = set()
    for e in entries_for_export:
        bp = int(e.get("_pageBP") or e.get("book_page") or 0)
        if not _in_ranges(bp):
            continue
        page_entries = e.get("_page_entries")
        if page_entries:
            footnote_assignments = _resolve_page_footnote_assignments(page_entries)
            current_chapter = _resolve_chapter_for_bp(chapter_ranges, bp)
            for idx, pe in enumerate(page_entries):
                hlevel, matched_toc_bp = _resolve_heading_level(pe, dm, min_non_toc_level, bp=bp)
                orig = strip_html(_normalize_footnote_markers(_ensure_str(pe.get("original")).strip())).strip()
                tr = strip_html(
                    _normalize_footnote_markers(
                        _unwrap_translation_json(_ensure_str(pe.get("translation")).strip())
                    )
                ).strip()
                if hlevel > 0 and matched_toc_bp is not None and toc_title_map:
                    toc_title = _ensure_str(toc_title_map.get(int(matched_toc_bp))).strip()
                    if toc_title and not _heading_matches_toc_title(orig, tr, toc_title):
                        hlevel = 0
                if _should_demote_heading(
                    hlevel=hlevel,
                    toc_depth_map=dm,
                    bp=bp,
                    start_bp=pe.get("_startBP"),
                    title_text=tr or orig,
                ):
                    hlevel = 0
                inline_labels = _extract_marked_footnote_labels(f"{orig}\n{tr}")
                label_rewrites: dict[str, str] = {}
                # 尾注索引匹配：正文中的数字型 [^n] 优先绑定到当前章节尾注组。
                if endnote_registry["groups"] and inline_labels:
                    cidx_cur = int(current_chapter["index"]) if current_chapter else None
                    current_group = (
                        endnote_registry["groups_by_chapter"].get(cidx_cur)
                        if cidx_cur is not None
                        else None
                    )
                    for lbl in inline_labels:
                        if not lbl.isdigit():
                            continue
                        num = int(lbl)
                        matched_group = None
                        if current_group and num in current_group.get("notes", {}):
                            matched_group = current_group
                            used_endnote_chapter_groups.add(int(current_group["chapter_index"]))
                        else:
                            candidate_book_groups = [
                                group for group in endnote_registry["book_groups"]
                                if num in group.get("notes", {})
                            ]
                            if len(candidate_book_groups) == 1:
                                matched_group = candidate_book_groups[0]
                                used_endnote_book_groups.add(_ensure_str(matched_group["group_key"]))
                            else:
                                candidate_chapter_groups = [
                                    group for group in endnote_registry["groups"]
                                    if group.get("chapter_index") is not None
                                    and num in group.get("notes", {})
                                ]
                                if len(candidate_chapter_groups) == 1:
                                    matched_group = candidate_chapter_groups[0]
                                    used_endnote_chapter_groups.add(int(candidate_chapter_groups[0]["chapter_index"]))
                        if matched_group is None:
                            continue
                        rewritten_label = _build_endnote_label(matched_group, num, endnote_registry)
                        seen_footnote_labels.add(rewritten_label)
                        if rewritten_label != lbl:
                            label_rewrites[lbl] = rewritten_label
                if label_rewrites:
                    for old_label, new_label in label_rewrites.items():
                        orig = orig.replace(f"[^{old_label}]", f"[^{new_label}]")
                        tr = tr.replace(f"[^{old_label}]", f"[^{new_label}]")
                    inline_labels = [label_rewrites.get(lbl, lbl) for lbl in inline_labels]
                if hlevel > 0:
                    prefix = "#" * min(hlevel, 6)
                    # 译文为主标题，原文以斜体注释跟随
                    if tr:
                        md_lines.append(f"{prefix} {tr}")
                        if orig and orig != tr:
                            md_lines.append(f"*{orig}*")
                        md_lines.append("")
                    elif orig:
                        md_lines.append(f"{prefix} {orig}")
                        md_lines.append("")
                else:
                    _append_blockquote(md_lines, orig)
                    pending_ref_labels: list[str] = []
                    fallback_blocks: list[tuple[str, str]] = []
                    pending_footnote_defs: list[dict] = []
                    for footnotes, footnotes_translation in footnote_assignments.get(idx, []):
                        defs, parsed_labels, fallback = _build_obsidian_footnote_defs(
                            footnotes=footnotes,
                            footnotes_translation=footnotes_translation,
                            existing_labels=list(seen_footnote_labels) + pending_ref_labels,
                            preferred_labels=inline_labels,
                            source_bp=bp,
                            segment_idx=idx,
                            chapter_index=current_chapter["index"] if current_chapter else None,
                            chapter_end_bp=current_chapter["end_bp"] if current_chapter else None,
                            doc_last_bp=doc_last_bp,
                            fallback_prefix=f"p{bp}-s{idx}",
                        )
                        for note_def in defs:
                            label = note_def["label"]
                            if label not in seen_footnote_labels:
                                seen_footnote_labels.add(label)
                                pending_ref_labels.append(label)
                                if note_def["note_type"] == "endnote":
                                    if note_def["note_scope"] == "chapter_end" and note_def.get("chapter_index") is not None:
                                        chapter_endnotes.setdefault(int(note_def["chapter_index"]), []).append(note_def)
                                    else:
                                        book_endnotes.append(note_def)
                                else:
                                    pending_footnote_defs.append(note_def)
                        fallback_blocks.extend(fallback)

                    tr_with_refs = tr
                    for label in pending_ref_labels:
                        marker = f"[^{label}]"
                        if marker not in tr_with_refs and marker not in orig:
                            tr_with_refs = (tr_with_refs + f" {marker}").strip() if tr_with_refs else marker
                    _append_paragraph(md_lines, tr_with_refs)
                    for note_def in pending_footnote_defs:
                        content_lines = _nonempty_markdown_lines(note_def.get("content"))
                        if not content_lines:
                            continue
                        md_lines.append(f"[^{note_def['label']}]: {content_lines[0]}")
                        for line in content_lines[1:]:
                            md_lines.append(f"    {line}")
                        md_lines.append("")
                    for fb_label, fb_text in fallback_blocks:
                        _append_labeled_block(md_lines, fb_label, fb_text)
        else:
            orig = strip_html(_normalize_footnote_markers(_ensure_str(e.get("original")).strip())).strip()
            tr_legacy = strip_html(
                _normalize_footnote_markers(_unwrap_translation_json(_ensure_str(e.get("translation")).strip()))
            ).strip()
            _append_blockquote(md_lines, orig)
            _append_paragraph(md_lines, tr_legacy)
            defs, _, fallback_blocks = _build_obsidian_footnote_defs(
                e.get("footnotes"),
                e.get("footnotes_translation"),
                existing_labels=list(seen_footnote_labels),
                preferred_labels=_extract_marked_footnote_labels(f"{orig}\n{tr_legacy}"),
                source_bp=bp,
                segment_idx=0,
                chapter_index=_resolve_chapter_for_bp(chapter_ranges, bp)["index"] if _resolve_chapter_for_bp(chapter_ranges, bp) else None,
                chapter_end_bp=_resolve_chapter_for_bp(chapter_ranges, bp)["end_bp"] if _resolve_chapter_for_bp(chapter_ranges, bp) else None,
                doc_last_bp=doc_last_bp,
                fallback_prefix=f"p{bp}-legacy",
            )
            for note_def in defs:
                label = note_def["label"]
                if label not in seen_footnote_labels:
                    seen_footnote_labels.add(label)
                    if note_def["note_type"] == "endnote":
                        if note_def["note_scope"] == "chapter_end" and note_def.get("chapter_index") is not None:
                            chapter_endnotes.setdefault(int(note_def["chapter_index"]), []).append(note_def)
                        else:
                            book_endnotes.append(note_def)
                    else:
                        content_lines = _nonempty_markdown_lines(note_def.get("content"))
                        if content_lines:
                            md_lines.append(f"[^{label}]: {content_lines[0]}")
                            for line in content_lines[1:]:
                                md_lines.append(f"    {line}")
                            md_lines.append("")
            for fb_label, fb_text in fallback_blocks:
                _append_labeled_block(md_lines, fb_label, fb_text)

    def _note_sort_key(note_def: dict) -> tuple[int, str]:
        explicit_number = note_def.get("number")
        if explicit_number is not None:
            return int(explicit_number), _ensure_str(note_def.get("label", ""))
        label = _ensure_str(note_def.get("label", ""))
        match = re.search(r"(\d+)$", label)
        return (int(match.group(1)) if match else 10**9, label)

    has_grouped_chapter_endnotes = bool(used_endnote_chapter_groups)
    has_extra_chapter_endnotes = any(chapter_endnotes.get(int(chapter["index"])) for chapter in chapter_ranges)
    if has_grouped_chapter_endnotes or has_extra_chapter_endnotes:
        if md_lines and md_lines[-1].strip():
            md_lines.append("")
        md_lines.append("## 本章尾注")
        md_lines.append("")
        for chapter in chapter_ranges:
            cidx = int(chapter["index"])
            group = (
                endnote_registry["groups_by_chapter"].get(cidx)
                if cidx in used_endnote_chapter_groups
                else None
            )
            notes = list(chapter_endnotes.get(cidx) or [])
            if not group and not notes:
                continue
            chapter_title = _ensure_str(chapter.get("title", "")).strip()
            if group and group.get("chapter_title"):
                chapter_title = _ensure_str(group.get("chapter_title", "")).strip()
            if not chapter_title and toc_title_map:
                chapter_title = _ensure_str(toc_title_map.get(int(chapter.get("start_bp", 0)), "")).strip()
            if not chapter_title:
                chapter_title = f"章节 {cidx + 1}"
            md_lines.append(f"### {chapter_title}")
            md_lines.append("")
            if group:
                for number in sorted(int(v) for v in group.get("notes", {}).keys()):
                    note = group["notes"][number]
                    merged_parts = []
                    if note.get("orig"):
                        merged_parts.append(note["orig"])
                    if note.get("tr"):
                        merged_parts.append(f"译：{note['tr']}")
                    content_lines = _nonempty_markdown_lines("\n".join(merged_parts).strip())
                    if not content_lines:
                        continue
                    label = _build_endnote_label(group, number, endnote_registry)
                    md_lines.append(f"[^{label}]: {content_lines[0]}")
                    for line in content_lines[1:]:
                        md_lines.append(f"    {line}")
                    md_lines.append("")
            for note_def in sorted(notes, key=_note_sort_key):
                content_lines = _nonempty_markdown_lines(note_def.get("content"))
                if not content_lines:
                    continue
                md_lines.append(f"[^{note_def['label']}]: {content_lines[0]}")
                for line in content_lines[1:]:
                    md_lines.append(f"    {line}")
                md_lines.append("")

    has_grouped_book_endnotes = bool(used_endnote_book_groups)
    if has_grouped_book_endnotes or book_endnotes:
        if md_lines and md_lines[-1].strip():
            md_lines.append("")
        md_lines.append("## 全书尾注")
        md_lines.append("")
        for group in endnote_registry["book_groups"]:
            if _ensure_str(group.get("group_key")) not in used_endnote_book_groups:
                continue
            for number in sorted(int(v) for v in group.get("notes", {}).keys()):
                note = group["notes"][number]
                merged_parts = []
                if note.get("orig"):
                    merged_parts.append(note["orig"])
                if note.get("tr"):
                    merged_parts.append(f"译：{note['tr']}")
                content_lines = _nonempty_markdown_lines("\n".join(merged_parts).strip())
                if not content_lines:
                    continue
                label = _build_endnote_label(group, number, endnote_registry)
                md_lines.append(f"[^{label}]: {content_lines[0]}")
                for line in content_lines[1:]:
                    md_lines.append(f"    {line}")
                md_lines.append("")
        for note_def in sorted(book_endnotes, key=_note_sort_key):
            content_lines = _nonempty_markdown_lines(note_def.get("content"))
            if not content_lines:
                continue
            md_lines.append(f"[^{note_def['label']}]: {content_lines[0]}")
            for line in content_lines[1:]:
                md_lines.append(f"    {line}")
            md_lines.append("")

    while md_lines and not md_lines[-1].strip():
        md_lines.pop()
    if not md_lines:
        return ""
    return "\n".join(md_lines) + "\n"


def get_app_state(doc_id: str = "") -> dict:
    """获取所有共享的模板变量。"""
    pages, src_name = load_pages_from_disk(doc_id)
    visible_page_view = load_visible_page_view(doc_id, pages=pages)
    entries, doc_title, entry_idx = load_entries_from_disk(doc_id, pages=pages)
    active_model_mode = get_active_model_mode()
    active_builtin_model_key = get_active_builtin_model_key()
    custom_model = get_custom_model_config()
    resolved_spec = resolve_model_spec()
    meta = get_doc_meta(doc_id)
    entry_idx = meta.get("last_entry_idx", entry_idx)
    cleanup_headers_footers_enabled = (
        get_doc_cleanup_headers_footers(doc_id)
        if doc_id
        else True
    )
    auto_visual_toc_enabled = (
        get_doc_auto_visual_toc_enabled(doc_id)
        if doc_id
        else False
    )
    visual_toc_status = str(meta.get("toc_visual_status", "idle") or "idle").strip() or "idle"
    visual_toc_message = str(meta.get("toc_visual_message", "") or "").strip()
    visual_toc_phase = str(meta.get("toc_visual_phase", "") or "").strip()
    visual_toc_progress_pct = int(meta.get("toc_visual_progress_pct", 0) or 0)
    visual_toc_progress_label = str(meta.get("toc_visual_progress_label", "") or "").strip()
    visual_toc_progress_detail = str(meta.get("toc_visual_progress_detail", "") or "").strip()
    visual_toc_status_label_map = {
        "idle": "未生成",
        "running": "生成中",
        "ready": "已生成",
        "unsupported": "当前模型不支持视觉目录",
        "failed": "生成失败",
        "needs_offset": "需要确认页码偏移",
    }
    visual_toc_status_label = visual_toc_status_label_map.get(visual_toc_status, visual_toc_status)

    first_page = visible_page_view["first_visible_page"] or (get_page_range(pages)[0] if pages else 1)
    last_page = visible_page_view["last_visible_page"] or (get_page_range(pages)[1] if pages else 1)
    visible_page_count = int(visible_page_view["visible_page_count"] or 0)

    has_entries = len(entries) > 0
    return {
        "pages": pages,
        "src_name": src_name,
        "entries": entries,
        "doc_title": doc_title,
        "entry_idx": entry_idx,
        "model_key": active_builtin_model_key,
        "models": MODELS,
        "glossary": get_glossary(doc_id),
        "paddle_token": get_paddle_token(),
        "deepseek_key": get_deepseek_key(),
        "dashscope_key": get_dashscope_key(),
        "active_model_mode": active_model_mode,
        "active_builtin_model_key": active_builtin_model_key,
        "custom_model": custom_model,
        "custom_model_name": custom_model.get("display_name") or custom_model.get("model_id", ""),
        "custom_model_enabled": active_model_mode == "custom",
        "custom_model_base_key": "",
        "current_model_source": resolved_spec.source,
        "current_model_id": resolved_spec.model_id,
        "current_model_label": resolved_spec.display_label,
        "current_model_provider": resolved_spec.provider,
        "translate_parallel_enabled": get_translate_parallel_enabled(),
        "translate_parallel_limit": get_translate_parallel_limit(),
        "has_pages": len(pages) > 0,
        "has_entries": has_entries,
        "has_translation_history": has_entries,
        "page_count": visible_page_count or len(pages),
        "first_page": first_page,
        "last_page": last_page,
        "visible_page_view": visible_page_view,
        "visible_page_bps": visible_page_view["visible_page_bps"],
        "hidden_placeholder_bps": visible_page_view["hidden_placeholder_bps"],
        "visible_page_count": visible_page_count or len(pages),
        "entry_count": len(entries),
        "cleanup_headers_footers_enabled": cleanup_headers_footers_enabled,
        "cleanup_mode_label": "增强脚注/尾注模式（已清理）" if cleanup_headers_footers_enabled else "快速模式（未清理）",
        "cleanup_mode_detail": "页眉页脚清理已开启，更利于脚注/尾注检测。" if cleanup_headers_footers_enabled else "已跳过页眉页脚清理，优先更快开始阅读。",
        "upload_cleanup_default_enabled": get_upload_cleanup_headers_footers_enabled(),
        "auto_visual_toc_enabled": auto_visual_toc_enabled,
        "auto_visual_toc_mode_label": "自动视觉目录已开启" if auto_visual_toc_enabled else "自动视觉目录未开启",
        "auto_visual_toc_mode_detail": (
            visual_toc_message
            or ("解析后会继续后台生成目录。" if auto_visual_toc_enabled else "当前文档不会自动生成视觉目录。")
        ),
        "visual_toc_status": visual_toc_status,
        "visual_toc_status_label": visual_toc_status_label,
        "visual_toc_status_message": visual_toc_message,
        "visual_toc_phase": visual_toc_phase,
        "visual_toc_progress_pct": visual_toc_progress_pct,
        "visual_toc_progress_label": visual_toc_progress_label,
        "visual_toc_progress_detail": visual_toc_progress_detail,
        "upload_auto_visual_toc_default_enabled": get_upload_auto_visual_toc_enabled(),
    }

"""磁盘持久化与辅助函数：数据读写、模板变量、文本处理工具。"""
from dataclasses import asdict, dataclass, field
import json
import os
import re
import shutil

from flask import g, has_request_context
from pypdf import PdfReader

from config import (
    MODELS,
    QWEN_BASE_URLS,
    DEEPSEEK_BASE_URL,
    get_paddle_token, get_deepseek_key, get_dashscope_key,
    get_glossary,
    get_active_model_mode, get_active_builtin_model_key, get_custom_model_config,
    get_active_visual_model_mode, get_active_builtin_visual_model_key, get_visual_custom_model_config,
    get_translate_parallel_enabled, get_translate_parallel_limit,
    get_current_doc_id, get_doc_dir, get_doc_meta, update_doc_meta,
    get_doc_cleanup_headers_footers,
    get_upload_cleanup_headers_footers_enabled,
    get_doc_auto_visual_toc_enabled,
    get_upload_auto_visual_toc_enabled,
)
from model_capabilities import (
    get_model_spec as get_builtin_model_spec,
    infer_builtin_key_from_custom_model,
    normalize_builtin_model_key,
    get_selectable_models,
)
from persistence.sqlite_store import (
    SQLiteRepository,
    TOC_SOURCE_AUTO,
    TOC_SOURCE_AUTO_VISUAL,
    TOC_SOURCE_USER,
)
from persistence.storage_toc import (
    clear_toc_visual_draft,
    clear_toc_visual_manual_inputs,
    get_toc_file_info,
    get_toc_file_path,
    get_toc_visual_manual_pdf_path,
    get_toc_visual_screenshot_dir,
    has_toc_visual_draft,
    load_auto_visual_toc_from_disk,
    load_effective_toc,
    load_pdf_toc_from_disk,
    load_toc_visual_manual_inputs,
    load_toc_source_offset,
    load_toc_visual_draft,
    load_user_toc_from_disk,
    save_auto_pdf_toc_to_disk,
    save_auto_visual_toc_to_disk,
    save_pdf_toc_to_disk,
    save_toc_file,
    save_toc_source_offset,
    save_toc_visual_draft,
    save_toc_visual_manual_pdf,
    save_toc_visual_manual_screenshots,
    save_user_toc_csv_generated,
    save_user_toc_to_disk,
)
from persistence.storage_export_plan import (
    build_toc_chapters as _build_toc_chapters_impl,
    build_toc_depth_map as _build_toc_depth_map_impl,
    build_toc_title_map as _build_toc_title_map_impl,
    compute_boilerplate_skip_bps as _compute_boilerplate_skip_bps_impl,
    detect_book_index_pages as _detect_book_index_pages_impl,
)
from persistence.storage_endnotes import (
    _append_blockquote,
    _append_labeled_block,
    _append_paragraph,
    _build_chapter_ranges_from_depth_map,
    _build_endnote_label,
    _build_endnote_run_sections,
    _build_obsidian_footnote_defs,
    _extract_marked_footnote_labels,
    _heading_matches_toc_title,
    _nonempty_markdown_lines,
    _normalize_endnote_registry,
    _normalize_footnote_markers,
    _resolve_chapter_for_bp,
    _resolve_heading_level,
    _resolve_page_footnote_assignments,
    _should_demote_heading,
    build_endnote_index as _build_endnote_index_impl,
    detect_endnote_collection_pages,
)
from persistence.storage_markdown import gen_markdown as _gen_markdown_impl
from persistence.storage_state import get_app_state as _get_app_state_impl
from document.text_processing import (
    get_page_range,
    build_visible_page_view,
)


# ============ DISK PERSISTENCE (多文档) ============

_PRINT_PAGE_INT_RE = re.compile(r"^\d+$")
_DOC_REQUEST_CACHE_KEY = "_doc_request_cache"
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
            page["markdown"] = ensure_str(page.get("markdown", ""))
            page["footnotes"] = ensure_str(page.get("footnotes", ""))
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
        pages = repaired_pages
    else:
        pages = [_normalize_page_payload(page) for page in pages]
        pages, _ = _normalize_placeholder_print_labels(pages)
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
    api_family: str = "chat"
    supports_translation: bool = True
    supports_vision: bool = False
    supports_stream: bool = True
    stream_mode: str = "chat_json"
    companion_chat_model_key: str = ""
    request_overrides: dict = field(default_factory=dict)

def _resolve_builtin_model_spec(key: str, *, capability: str | None = None) -> ResolvedModelSpec:
    builtin_key = normalize_builtin_model_key(key, capability=capability) if capability else str(key or "").strip()
    if builtin_key not in MODELS:
        builtin_key = normalize_builtin_model_key("", capability=capability)
    model = get_builtin_model_spec(builtin_key)
    provider = model.get("provider", "deepseek")
    api_key = get_dashscope_key() if provider in {"qwen", "qwen_mt"} else get_deepseek_key()
    base_url = QWEN_BASE_URLS["cn"] if provider in {"qwen", "qwen_mt"} else DEEPSEEK_BASE_URL
    request_overrides = {}
    if provider == "qwen" and model.get("api_family") == "chat":
        request_overrides = {"extra_body": {"enable_thinking": False}}
    return ResolvedModelSpec(
        source="builtin",
        model_key=builtin_key,
        model_id=model["id"],
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        display_label=model.get("label", model["id"]),
        api_family=str(model.get("api_family", "chat") or "chat"),
        supports_translation=bool(model.get("supports_translation")),
        supports_vision=bool(model.get("supports_vision")),
        supports_stream=bool(model.get("supports_stream", True)),
        stream_mode=str(model.get("stream_mode", "chat_json") or "chat_json"),
        companion_chat_model_key=str(model.get("companion_chat_model_key", "") or "").strip(),
        request_overrides=request_overrides,
    )


def _resolve_custom_model_spec(custom_model: dict, *, source: str, capability: str) -> ResolvedModelSpec:
    provider = str(custom_model.get("provider_type", "qwen") or "qwen").strip()
    model_id = str(custom_model.get("model_id", "") or "").strip()
    builtin_key = infer_builtin_key_from_custom_model(provider, model_id, capability=capability)
    builtin_spec = get_builtin_model_spec(builtin_key, capability=capability) if builtin_key in MODELS else {}
    if provider in {"qwen", "qwen_mt"}:
        api_key = get_dashscope_key()
        base_url = QWEN_BASE_URLS.get(custom_model.get("qwen_region", "cn"), QWEN_BASE_URLS["cn"])
    elif provider == "deepseek":
        api_key = get_deepseek_key()
        base_url = DEEPSEEK_BASE_URL
    else:
        api_key = str(custom_model.get("custom_api_key", "") or "").strip()
        base_url = str(custom_model.get("base_url", "") or "").strip()

    request_overrides = {}
    if provider == "qwen":
        request_overrides = {"extra_body": dict(custom_model.get("extra_body") or {"enable_thinking": False})}
    elif provider == "qwen_mt":
        request_overrides = {"extra_body": dict(custom_model.get("extra_body") or {})}

    default_api_family = "vision" if capability == "vision" else ("mt" if provider == "qwen_mt" else "chat")
    return ResolvedModelSpec(
        source=source,
        model_key="",
        model_id=model_id,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        display_label=str(custom_model.get("display_name", "") or model_id).strip(),
        api_family=str(builtin_spec.get("api_family", default_api_family) or default_api_family),
        supports_translation=bool(
            builtin_spec.get("supports_translation", capability == "translation")
        ),
        supports_vision=bool(
            builtin_spec.get("supports_vision", capability == "vision")
        ),
        supports_stream=bool(builtin_spec.get("supports_stream", True)),
        stream_mode=str(
            builtin_spec.get(
                "stream_mode",
                "mt_cumulative" if provider == "qwen_mt" else "chat_json",
            ) or "chat_json"
        ),
        companion_chat_model_key=str(builtin_spec.get("companion_chat_model_key", "") or "").strip(),
        request_overrides=request_overrides,
    )


def resolve_model_spec(target: str | None = None) -> ResolvedModelSpec:
    active_mode = get_active_model_mode()
    active_builtin_key = get_active_builtin_model_key()
    custom_model = get_custom_model_config()

    normalized_target = str(target or "").strip()
    if normalized_target.startswith("builtin:"):
        builtin_key = normalized_target.split(":", 1)[1].strip()
        fallback_key = active_builtin_key if active_builtin_key in MODELS else "deepseek-chat"
        builtin_key = normalize_builtin_model_key(
            builtin_key if builtin_key in MODELS else fallback_key,
            capability="translation",
        )
        return _resolve_builtin_model_spec(builtin_key, capability="translation")
    if normalized_target == "custom":
        active_mode = "custom"

    if active_mode == "custom" and custom_model.get("enabled") and custom_model.get("model_id"):
        return _resolve_custom_model_spec(custom_model, source="custom", capability="translation")

    return resolve_model_spec(f"builtin:{active_builtin_key}")


def resolve_visual_model_spec(target: str | None = None) -> ResolvedModelSpec:
    """自动视觉目录等「读图」能力使用的模型，与翻译模型独立配置。"""
    active_mode = get_active_visual_model_mode()
    active_builtin_key = get_active_builtin_visual_model_key()
    custom_model = get_visual_custom_model_config()

    normalized_target = str(target or "").strip()
    if normalized_target.startswith("builtin:"):
        builtin_key = normalized_target.split(":", 1)[1].strip()
        if builtin_key not in MODELS:
            builtin_key = normalize_builtin_model_key(active_builtin_key, capability="vision")
        return _resolve_builtin_model_spec(builtin_key)
    if normalized_target == "custom":
        active_mode = "custom"

    if active_mode == "custom" and custom_model.get("enabled") and custom_model.get("model_id"):
        return _resolve_custom_model_spec(custom_model, source="custom", capability="vision")

    return resolve_visual_model_spec(f"builtin:{active_builtin_key}")


def get_visual_model_args(target: str | None = None) -> dict:
    spec = resolve_visual_model_spec(target)
    payload = asdict(spec)
    payload["model_source"] = payload.pop("source")
    return payload


def get_translate_args(target: str | None = None) -> dict:
    """返回统一解析后的翻译请求参数。"""
    spec = resolve_model_spec(target)
    payload = asdict(spec)
    payload["model_source"] = payload.pop("source")
    companion_key = str(spec.companion_chat_model_key or "").strip()
    if companion_key:
        companion_spec = _resolve_builtin_model_spec(companion_key, capability="translation")
        companion_payload = asdict(companion_spec)
        companion_payload["model_source"] = companion_payload.pop("source")
        payload["companion_chat_model"] = companion_payload
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


from document.text_utils import ensure_str  # 统一定义在 text_utils.py


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
            result = ensure_str(parsed["translation"]).strip()
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
    return _build_toc_chapters_impl(toc_items, offset=offset, total_pages=total_pages)


def build_toc_depth_map(toc_items: list, offset: int = 0) -> dict:
    """从原始 TOC 条目 + 页码偏移构建 {book_page: depth} 查找表。"""
    return _build_toc_depth_map_impl(toc_items, offset)


def build_toc_title_map(toc_items: list, offset: int = 0) -> dict[int, str]:
    """从 TOC 条目 + 偏移构建 {book_page: title} 查找表。"""
    return _build_toc_title_map_impl(toc_items, offset, ensure_str=ensure_str)


def compute_boilerplate_skip_bps(
    entries: list[dict],
    chapters: list[dict] | None,
    *,
    max_leading_scan: int = 12,
) -> set[int]:
    return _compute_boilerplate_skip_bps_impl(
        entries,
        chapters,
        max_leading_scan=max_leading_scan,
        ensure_str=ensure_str,
        normalize_footnote_markers=_normalize_footnote_markers,
        unwrap_translation_json=_unwrap_translation_json,
    )


def detect_book_index_pages(entries: list[dict]) -> set[int]:
    """检测书末索引页（人名/主题索引），返回应跳过的页码集合。"""
    return _detect_book_index_pages_impl(
        entries,
        ensure_str=ensure_str,
        normalize_footnote_markers=_normalize_footnote_markers,
        unwrap_translation_json=_unwrap_translation_json,
    )


def _load_pdf_note_lines_by_bp(doc_id: str, bps: list[int]) -> dict[int, list[str]]:
    doc_key = ensure_str(doc_id).strip()
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
                raw_text = ensure_str(reader.pages[bp - 1].extract_text() or "")
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


def build_endnote_index(
    entries: list[dict],
    endnote_page_map: dict[int | None, list[int]],
    chapter_ranges: list[dict] | None = None,
    pages: list[dict] | None = None,
) -> dict:
    return _build_endnote_index_impl(
        entries,
        endnote_page_map,
        chapter_ranges=chapter_ranges,
        pages=pages,
        load_pdf_note_lines_by_bp=_load_pdf_note_lines_by_bp,
    )


def gen_markdown(
    entries: list,
    toc_depth_map: dict | None = None,
    page_ranges: list[tuple[int, int]] | None = None,
    skip_bps: set[int] | None = None,
    toc_title_map: dict[int, str] | None = None,
    endnote_index: dict | None = None,
    endnote_page_bps: set[int] | None = None,
) -> str:
    return _gen_markdown_impl(
        entries,
        toc_depth_map=toc_depth_map,
        page_ranges=page_ranges,
        skip_bps=skip_bps,
        toc_title_map=toc_title_map,
        endnote_index=endnote_index,
        endnote_page_bps=endnote_page_bps,
        helpers={
            "ensure_str": ensure_str,
            "build_chapter_ranges_from_depth_map": _build_chapter_ranges_from_depth_map,
            "normalize_endnote_registry": _normalize_endnote_registry,
            "resolve_chapter_for_bp": _resolve_chapter_for_bp,
            "resolve_heading_level": _resolve_heading_level,
            "heading_matches_toc_title": _heading_matches_toc_title,
            "should_demote_heading": _should_demote_heading,
            "extract_marked_footnote_labels": _extract_marked_footnote_labels,
            "build_obsidian_footnote_defs": _build_obsidian_footnote_defs,
            "append_blockquote": _append_blockquote,
            "append_paragraph": _append_paragraph,
            "append_labeled_block": _append_labeled_block,
            "nonempty_markdown_lines": _nonempty_markdown_lines,
            "normalize_footnote_markers": _normalize_footnote_markers,
            "unwrap_translation_json": _unwrap_translation_json,
            "build_endnote_label": _build_endnote_label,
            "resolve_page_footnote_assignments": _resolve_page_footnote_assignments,
        },
    )


def get_app_state(doc_id: str = "") -> dict:
    return _get_app_state_impl(
        doc_id,
        deps={
            "load_pages_from_disk": load_pages_from_disk,
            "load_visible_page_view": load_visible_page_view,
            "load_entries_from_disk": load_entries_from_disk,
            "load_toc_visual_manual_inputs": load_toc_visual_manual_inputs,
            "resolve_model_spec": resolve_model_spec,
            "resolve_visual_model_spec": resolve_visual_model_spec,
            "SQLiteRepository": SQLiteRepository,
        },
    )

"""磁盘持久化与辅助函数：数据读写、模板变量、文本处理工具。"""
from dataclasses import asdict, dataclass, field
import io
import os
import re
import shutil
import time

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
)
from sqlite_store import SQLiteRepository
from text_processing import get_page_range, build_visible_page_view


# ============ DISK PERSISTENCE (多文档) ============

_PRINT_PAGE_INT_RE = re.compile(r"^\d+$")

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
    toc_items = load_pdf_toc_from_disk(target_doc_id)
    if toc_items:
        return toc_items
    source, _ = load_toc_source_offset(target_doc_id)
    if source != "user":
        return []
    path = get_toc_file_path(target_doc_id)
    if not path or not os.path.exists(path):
        return []
    try:
        recovered = _parse_saved_toc_file(path)
    except Exception:
        return []
    if recovered:
        save_pdf_toc_to_disk(target_doc_id, recovered)
    return recovered


def save_auto_pdf_toc_to_disk(doc_id: str, toc_items: list[dict]) -> None:
    """保存自动提取的 PDF 书签，但不覆盖用户手动导入的目录。"""
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    source, _ = load_toc_source_offset(target_doc_id)
    if source == "user":
        if load_user_toc_from_disk(target_doc_id) or get_toc_file_path(target_doc_id):
            return
    save_pdf_toc_to_disk(target_doc_id, toc_items)


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


def save_toc_source_offset(doc_id: str, source: str, offset: int) -> None:
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return
    SQLiteRepository().set_document_toc_source_offset(target_doc_id, source, offset)


def load_toc_source_offset(doc_id: str = "") -> tuple[str, int]:
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return ("auto", 0)
    return SQLiteRepository().get_document_toc_source_offset(target_doc_id)


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
    active_model_mode = get_active_model_mode()
    active_builtin_model_key = get_active_builtin_model_key()
    custom_model = get_custom_model_config()
    resolved_spec = resolve_model_spec()
    meta = get_doc_meta(doc_id)
    entry_idx = meta.get("last_entry_idx", entry_idx)

    visible_page_view = build_visible_page_view(pages)
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
        "visible_page_bps": visible_page_view["visible_page_bps"],
        "hidden_placeholder_bps": visible_page_view["hidden_placeholder_bps"],
        "visible_page_count": visible_page_count or len(pages),
        "entry_count": len(entries),
    }

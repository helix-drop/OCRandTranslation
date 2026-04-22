"""目录（TOC）存储与恢复 helper。"""

import io
import json
import os
import re
import shutil
import time

from flask import g, has_request_context

from config import get_current_doc_id, get_doc_dir, get_doc_meta, update_doc_meta
from persistence.sqlite_store import (
    SQLiteRepository,
    TOC_SOURCE_AUTO,
    TOC_SOURCE_AUTO_VISUAL,
    TOC_SOURCE_USER,
)


_DOC_REQUEST_CACHE_KEY = "_doc_request_cache"
TOC_VISUAL_DRAFT_FILENAME = "toc_visual_draft.json"
TOC_VISUAL_SOURCE_PDF_FILENAME = "toc_visual_source.pdf"
TOC_VISUAL_SCREENSHOT_DIRNAME = "toc_visual_screenshots"
TOC_VISUAL_INPUT_MANIFEST_FILENAME = "toc_visual_input_manifest.json"
AUTO_VISUAL_TOC_BUNDLE_FILENAME = "auto_visual_toc_bundle.json"


def _invalidate_doc_request_cache(doc_id: str) -> None:
    if not has_request_context() or not doc_id:
        return
    cache = getattr(g, _DOC_REQUEST_CACHE_KEY, None)
    if not isinstance(cache, dict) or doc_id not in cache:
        return
    cache.pop(doc_id, None)


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
    from document.pdf_extract import parse_toc_file

    class _SavedTocFile(io.BytesIO):
        def __init__(self, raw: bytes, filename: str):
            super().__init__(raw)
            self.filename = filename

    with open(path, "rb") as f:
        raw = f.read()
    return parse_toc_file(_SavedTocFile(raw, os.path.basename(path)))


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


def get_auto_visual_toc_bundle_path(doc_id: str) -> str:
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return ""
    return os.path.join(doc_dir, AUTO_VISUAL_TOC_BUNDLE_FILENAME)


def save_auto_visual_toc_bundle_to_disk(doc_id: str, bundle: dict) -> None:
    """保存运行时视觉目录 bundle sidecar。"""
    target_doc_id = doc_id or get_current_doc_id()
    path = get_auto_visual_toc_bundle_path(target_doc_id)
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = dict(bundle or {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_auto_visual_toc_bundle_from_disk(doc_id: str = "") -> dict:
    """读取运行时视觉目录 bundle sidecar；不存在或损坏时返回空对象。"""
    target_doc_id = doc_id or get_current_doc_id()
    path = get_auto_visual_toc_bundle_path(target_doc_id)
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def clear_auto_visual_toc_bundle_from_disk(doc_id: str) -> None:
    """清理运行时视觉目录 bundle sidecar。"""
    target_doc_id = doc_id or get_current_doc_id()
    path = get_auto_visual_toc_bundle_path(target_doc_id)
    if not path or not os.path.exists(path):
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        return


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


def get_toc_visual_draft_path(doc_id: str) -> str:
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return ""
    return os.path.join(doc_dir, TOC_VISUAL_DRAFT_FILENAME)


def get_toc_visual_manual_pdf_path(doc_id: str) -> str:
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return ""
    return os.path.join(doc_dir, TOC_VISUAL_SOURCE_PDF_FILENAME)


def get_toc_visual_screenshot_dir(doc_id: str) -> str:
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return ""
    return os.path.join(doc_dir, TOC_VISUAL_SCREENSHOT_DIRNAME)


def get_toc_visual_input_manifest_path(doc_id: str) -> str:
    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return ""
    return os.path.join(doc_dir, TOC_VISUAL_INPUT_MANIFEST_FILENAME)


def _safe_visual_input_name(name: str, *, fallback_ext: str = "") -> str:
    original = os.path.basename(str(name or "").strip())
    stem, ext = os.path.splitext(original)
    ext = (ext or fallback_ext or "").lower()
    safe_stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", stem).strip("._-") or "input"
    return f"{safe_stem}{ext}"


def _write_toc_visual_input_manifest(doc_id: str, payload: dict) -> None:
    path = get_toc_visual_input_manifest_path(doc_id)
    if not path:
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _invalidate_doc_request_cache(doc_id)


def _count_pdf_pages(path: str) -> int:
    target = str(path or "").strip()
    if not target or not os.path.exists(target):
        return 0
    try:
        from pypdf import PdfReader

        return len(PdfReader(target).pages)
    except Exception:
        return 0


def _load_toc_visual_input_manifest(doc_id: str) -> dict | None:
    path = get_toc_visual_input_manifest_path(doc_id)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def clear_toc_visual_manual_inputs(doc_id: str) -> None:
    pdf_path = get_toc_visual_manual_pdf_path(doc_id)
    screenshot_dir = get_toc_visual_screenshot_dir(doc_id)
    manifest_path = get_toc_visual_input_manifest_path(doc_id)
    for path in (pdf_path, manifest_path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    if screenshot_dir and os.path.isdir(screenshot_dir):
        shutil.rmtree(screenshot_dir, ignore_errors=True)
    _invalidate_doc_request_cache(doc_id)


def save_toc_visual_manual_pdf(doc_id: str, source_path: str, *, original_name: str = "") -> str:
    if not doc_id or not source_path or not os.path.exists(source_path):
        return ""
    clear_toc_visual_manual_inputs(doc_id)
    dest = get_toc_visual_manual_pdf_path(doc_id)
    if not dest:
        return ""
    shutil.copy2(source_path, dest)
    _write_toc_visual_input_manifest(
        doc_id,
        {
            "mode": "manual_pdf",
            "source_name": os.path.basename(original_name or source_path),
            "files": [
                {
                    "index": 1,
                    "stored_name": os.path.basename(dest),
                    "original_name": os.path.basename(original_name or source_path),
                }
            ],
        },
    )
    return dest


def save_toc_visual_manual_screenshots(doc_id: str, screenshots: list[dict]) -> list[str]:
    if not doc_id:
        return []
    valid_rows = [
        row for row in (screenshots or [])
        if isinstance(row, dict) and row.get("path") and os.path.exists(str(row.get("path")))
    ]
    if not valid_rows:
        clear_toc_visual_manual_inputs(doc_id)
        return []
    clear_toc_visual_manual_inputs(doc_id)
    target_dir = get_toc_visual_screenshot_dir(doc_id)
    if not target_dir:
        return []
    os.makedirs(target_dir, exist_ok=True)
    saved_paths: list[str] = []
    manifest_files: list[dict] = []
    for index, row in enumerate(valid_rows, start=1):
        source_path = str(row.get("path") or "")
        original_name = os.path.basename(str(row.get("filename") or source_path))
        ext = os.path.splitext(original_name)[1].lower() or ".png"
        safe_name = _safe_visual_input_name(original_name, fallback_ext=ext)
        dest_name = f"{index:03d}-{safe_name}"
        dest_path = os.path.join(target_dir, dest_name)
        shutil.copy2(source_path, dest_path)
        saved_paths.append(dest_path)
        manifest_files.append(
            {
                "index": index,
                "stored_name": dest_name,
                "original_name": original_name,
            }
        )
    _write_toc_visual_input_manifest(
        doc_id,
        {
            "mode": "manual_images",
            "source_name": "",
            "files": manifest_files,
        },
    )
    return saved_paths


def load_toc_visual_manual_inputs(doc_id: str = "") -> dict:
    target_doc_id = doc_id or get_current_doc_id()
    if not target_doc_id:
        return {
            "mode": "",
            "pdf_path": "",
            "image_paths": [],
            "page_count": 0,
            "source_name": "",
            "files": [],
        }

    manifest = _load_toc_visual_input_manifest(target_doc_id) or {}
    mode = str(manifest.get("mode", "") or "").strip().lower()
    files = list(manifest.get("files") or []) if isinstance(manifest.get("files"), list) else []
    source_name = str(manifest.get("source_name", "") or "")
    pdf_path = get_toc_visual_manual_pdf_path(target_doc_id)
    screenshot_dir = get_toc_visual_screenshot_dir(target_doc_id)
    if mode == "manual_pdf" and os.path.exists(pdf_path):
        return {
            "mode": "manual_pdf",
            "pdf_path": pdf_path,
            "image_paths": [],
            "page_count": _count_pdf_pages(pdf_path),
            "source_name": source_name or os.path.basename(pdf_path),
            "files": files,
        }
    if mode == "manual_images" and os.path.isdir(screenshot_dir):
        ordered_paths: list[str] = []
        for row in files:
            stored_name = os.path.basename(str((row or {}).get("stored_name") or ""))
            if not stored_name:
                continue
            path = os.path.join(screenshot_dir, stored_name)
            if os.path.exists(path):
                ordered_paths.append(path)
        if not ordered_paths:
            ordered_paths = [
                entry.path
                for entry in sorted(os.scandir(screenshot_dir), key=lambda item: item.name)
                if entry.is_file()
            ]
        return {
            "mode": "manual_images",
            "pdf_path": "",
            "image_paths": ordered_paths,
            "page_count": len(ordered_paths),
            "source_name": source_name,
            "files": files,
        }
    if os.path.exists(pdf_path):
        return {
            "mode": "manual_pdf",
            "pdf_path": pdf_path,
            "image_paths": [],
            "page_count": _count_pdf_pages(pdf_path),
            "source_name": os.path.basename(pdf_path),
            "files": [],
        }
    if os.path.isdir(screenshot_dir):
        ordered_paths = [
            entry.path
            for entry in sorted(os.scandir(screenshot_dir), key=lambda item: item.name)
            if entry.is_file()
        ]
        return {
            "mode": "manual_images",
            "pdf_path": "",
            "image_paths": ordered_paths,
            "page_count": len(ordered_paths),
            "source_name": "",
            "files": [],
        }
    return {
        "mode": "",
        "pdf_path": "",
        "image_paths": [],
        "page_count": 0,
        "source_name": "",
        "files": [],
    }


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
    return items, int(raw.get("pending_offset") or 0)


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
    path = get_toc_visual_draft_path(doc_id)
    return bool(path and os.path.exists(path))


def save_user_toc_csv_generated(doc_id: str, user_rows: list[dict]) -> None:
    """根据用户目录行生成 toc_source.csv 并更新文件元数据。"""
    from document.pdf_extract import write_user_toc_csv_bytes

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
    return source, offset

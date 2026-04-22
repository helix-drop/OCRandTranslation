"""阅读页整页段落编辑相关的纯服务函数。"""

from __future__ import annotations

import time

from config import get_doc_meta
from persistence.sqlite_store import SQLiteRepository
from persistence.storage import save_entry_to_disk


def _normalize_page_editor_view(view: str | None) -> str:
    normalized = str(view or "standard").strip().lower()
    return normalized if normalized in {"standard", "fnm"} else "standard"


def normalize_page_editor_section_path(value) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text)
    return items


def normalize_page_editor_fnm_refs(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    refs = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        note_id = str(item.get("note_id") or "").strip()
        key = (kind, note_id)
        if kind not in {"footnote", "endnote"} or not note_id or key in seen:
            continue
        seen.add(key)
        refs.append({"kind": kind, "note_id": note_id})
    return refs


def page_editor_row_from_segment(segment: dict, order: int, fallback_bp: int) -> dict:
    heading_level = int(segment.get("heading_level", 0) or 0)
    start_bp = segment.get("_startBP")
    end_bp = segment.get("_endBP")
    return {
        "order": int(order),
        "kind": "heading" if heading_level > 0 else "body",
        "heading_level": heading_level,
        "original": str(segment.get("original") or ""),
        "translation": str(segment.get("translation") or ""),
        "pages": str(segment.get("pages") or fallback_bp),
        "start_bp": int(start_bp) if start_bp is not None else int(fallback_bp),
        "end_bp": int(end_bp) if end_bp is not None else int(fallback_bp),
        "print_page_label": str(segment.get("_printPageLabel") or ""),
        "footnotes": str(segment.get("footnotes") or ""),
        "footnotes_translation": str(segment.get("footnotes_translation") or ""),
        "note_kind": str(segment.get("_note_kind") or ""),
        "note_marker": str(segment.get("_note_marker") or ""),
        "note_number": segment.get("_note_number"),
        "note_section_title": str(segment.get("_note_section_title") or ""),
        "note_confidence": float(segment.get("_note_confidence", 0.0) or 0.0),
        "cross_page": segment.get("_cross_page"),
        "section_path": normalize_page_editor_section_path(segment.get("_section_path") or []),
        "fnm_refs": normalize_page_editor_fnm_refs(segment.get("_fnm_refs") or []),
        "translation_source": str(segment.get("_translation_source") or "model"),
    }


def build_page_editor_payload(
    doc_id: str,
    book_page: int,
    *,
    view: str = "standard",
    repo: SQLiteRepository | None = None,
) -> dict | None:
    repo = repo or SQLiteRepository()
    mode = _normalize_page_editor_view(view)
    if mode == "fnm":
        raise ValueError("FNM 诊断页为只读视图，不支持整页编辑")
    page = repo.get_effective_translation_page(doc_id, int(book_page))
    if not page:
        return None
    rows = [
        page_editor_row_from_segment(segment, idx, int(book_page))
        for idx, segment in enumerate(page.get("_page_entries") or [])
    ]
    history_count = len(repo.list_translation_page_revisions(doc_id, int(book_page), limit=1))
    updated_at = int(page.get("updated_at", 0) or 0)
    manual_segment_count = repo.count_manual_segments(doc_id, int(book_page))
    return {
        "doc_id": doc_id,
        "view": mode,
        "page": {
            "bp": int(book_page),
            "pages": str(page.get("pages") or book_page),
            "updated_at": updated_at,
            "manual_segment_count": manual_segment_count,
            "history_count": history_count,
        },
        "rows": rows,
    }


def _entry_from_page_editor_rows(current_page: dict, book_page: int, rows: list[dict], *, view: str = "standard") -> dict:
    now = int(time.time())
    existing_segments = list((current_page or {}).get("_page_entries") or [])
    page_entries = []
    for idx, row in enumerate(rows):
        existing_segment = existing_segments[idx] if idx < len(existing_segments) and isinstance(existing_segments[idx], dict) else {}
        heading_level = int(row.get("heading_level", 0) or 0)
        if str(row.get("kind") or "").strip() != "heading":
            heading_level = 0
        original = str(row.get("original") or "").strip()
        translation = str(row.get("translation") or "").strip()
        if not original:
            raise ValueError(f"第 {idx + 1} 段缺少原文")
        if not translation:
            raise ValueError(f"第 {idx + 1} 段缺少译文")
        start_bp = row.get("start_bp")
        end_bp = row.get("end_bp")
        note_number = row.get("note_number", existing_segment.get("_note_number"))
        cross_page = row.get("cross_page", existing_segment.get("_cross_page"))
        section_path = normalize_page_editor_section_path(
            row.get("section_path")
            if row.get("section_path") is not None
            else existing_segment.get("_section_path") or []
        )
        fnm_refs = normalize_page_editor_fnm_refs(
            row.get("fnm_refs")
            if row.get("fnm_refs") is not None
            else existing_segment.get("_fnm_refs") or []
        )
        page_entries.append({
            "original": original,
            "translation": translation,
            "footnotes": str(row.get("footnotes") or ""),
            "footnotes_translation": str(row.get("footnotes_translation") or ""),
            "heading_level": heading_level,
            "pages": str(row.get("pages") or book_page),
            "_startBP": int(start_bp) if start_bp is not None else int(book_page),
            "_endBP": int(end_bp) if end_bp is not None else int(book_page),
            "_printPageLabel": str(row.get("print_page_label") or ""),
            "_status": "done",
            "_error": "",
            "_translation_source": "manual",
            "_manual_translation": translation,
            "_manual_original": original,
            "_manual_updated_at": now,
            "_manual_updated_by": "local_user",
            "_cross_page": cross_page,
            "_section_path": section_path,
            "_fnm_refs": fnm_refs,
            "_note_kind": str(row.get("note_kind") or existing_segment.get("_note_kind") or ""),
            "_note_marker": str(row.get("note_marker") or existing_segment.get("_note_marker") or ""),
            "_note_number": note_number,
            "_note_section_title": str(row.get("note_section_title") or existing_segment.get("_note_section_title") or ""),
            "_note_confidence": float(row.get("note_confidence", existing_segment.get("_note_confidence", 0.0)) or 0.0),
        })
    if _normalize_page_editor_view(view) == "fnm":
        return {
            "_pageBP": int(book_page),
            "_status": "done",
            "_error": "",
            "pages": str(current_page.get("pages") or book_page),
            "_manual_locked": True,
            "_fnm_source": dict(current_page.get("_fnm_source") or {}),
            "_page_entries": page_entries,
        }
    return {
        "_pageBP": int(book_page),
        "_model_source": current_page.get("_model_source", "builtin"),
        "_model_key": current_page.get("_model_key", ""),
        "_model_id": current_page.get("_model_id") or current_page.get("_model") or "",
        "_provider": current_page.get("_provider", ""),
        "_model": current_page.get("_model") or current_page.get("_model_id") or "",
        "_status": "done",
        "_error": "",
        "_usage": current_page.get("_usage") or {},
        "pages": str(current_page.get("pages") or book_page),
        "_page_entries": page_entries,
    }


def save_page_editor_rows(
    doc_id: str,
    book_page: int,
    rows: list[dict],
    *,
    view: str = "standard",
    base_updated_at: int | None = None,
    repo: SQLiteRepository | None = None,
) -> dict:
    repo = repo or SQLiteRepository()
    mode = _normalize_page_editor_view(view)
    if mode == "fnm":
        raise ValueError("FNM 诊断页为只读视图，不支持整页编辑")
    current_page = repo.get_effective_translation_page(doc_id, int(book_page))
    if not current_page:
        raise ValueError("当前页还没有标准译文，无法编辑")
    current_updated_at = int(current_page.get("updated_at", 0) or 0)
    if base_updated_at is not None and current_updated_at > int(base_updated_at):
        raise RuntimeError("当前页已被更新，请刷新后再保存（冲突）")
    repo.save_translation_page_revision(
        doc_id,
        int(book_page),
        current_page,
        revision_source="page_editor",
        updated_by="local_user",
    )
    current_title = repo.get_translation_title(doc_id) or get_doc_meta(doc_id).get("name") or ""
    save_entry_to_disk(
        _entry_from_page_editor_rows(current_page, int(book_page), rows, view=mode),
        current_title,
        doc_id,
    )
    payload = build_page_editor_payload(doc_id, int(book_page), view=mode, repo=repo)
    return payload or {}


def list_page_editor_revisions(
    doc_id: str,
    book_page: int,
    *,
    view: str = "standard",
    repo: SQLiteRepository | None = None,
) -> list[dict]:
    repo = repo or SQLiteRepository()
    if _normalize_page_editor_view(view) == "fnm":
        raise ValueError("FNM 诊断页为只读视图，不支持编辑历史")
    return repo.list_translation_page_revisions(doc_id, book_page)

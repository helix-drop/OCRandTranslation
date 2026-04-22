"""阅读页与目录展示相关的纯 helper。"""

import html
import json
import re

from FNM_RE import (
    build_retry_summary as build_fnm_retry_summary,
    build_unit_progress as build_fnm_unit_progress,
    get_diagnostic_entry_for_page as get_fnm_diagnostic_entry_for_page,
    list_diagnostic_entries_for_doc as list_fnm_diagnostic_entries,
    list_diagnostic_notes_for_doc as list_fnm_diagnostic_notes,
)
from persistence.sqlite_store import SQLiteRepository
from persistence.storage import (
    format_print_page_display,
    highlight_terms,
    load_auto_visual_toc_from_disk,
    load_entries_from_disk,
    load_pages_from_disk,
    resolve_page_print_label,
)
from document.text_processing import (
    normalize_latex_footnote_markers,
    render_reading_footnote_text,
    render_superscript_footnote_references,
)
from document.text_utils import ensure_str, strip_html


def _default_reading_bp(page_bps: list[int], entries: list[dict], entry_idx: int, first_page: int) -> int:
    if entries:
        cursor_idx = max(0, min(int(entry_idx or 0), len(entries) - 1))
        candidate = entries[cursor_idx].get("_pageBP")
        if candidate in page_bps:
            return int(candidate)
    if first_page in page_bps:
        return int(first_page)
    return int(page_bps[0]) if page_bps else 1


def _nearest_existing_bp(page_bps: list[int], requested_bp: int) -> int | None:
    if not page_bps:
        return None
    return min(page_bps, key=lambda bp: (abs(int(bp) - int(requested_bp)), int(bp)))


def _build_toc_reading_items(toc_items: list[dict], toc_offset: int, page_lookup: dict[int, dict]) -> list[dict]:
    file_idx_lookup = {}
    for page_key, page in page_lookup.items():
        try:
            page_bp = int(page.get("bookPage"))
        except (TypeError, ValueError):
            continue
        try:
            page_file_idx = int(page.get("fileIdx"))
        except (TypeError, ValueError):
            try:
                page_file_idx = int(page_key) - 1
            except (TypeError, ValueError):
                continue
        file_idx_lookup[page_file_idx] = page_bp
    resolved_items = []
    for item in toc_items or []:
        resolved = dict(item)
        try:
            file_idx = item.get("file_idx")
            file_idx = int(file_idx) if file_idx is not None else None
        except (TypeError, ValueError):
            file_idx = None
        try:
            book_page = int(item.get("book_page") or 0)
        except (TypeError, ValueError):
            book_page = 0
        target_page = None
        try:
            target_pdf_page = int(item.get("target_pdf_page") or 0)
        except (TypeError, ValueError):
            target_pdf_page = 0
        if target_pdf_page > 0 and target_pdf_page in page_lookup:
            target_page = target_pdf_page
        elif file_idx is not None and file_idx in file_idx_lookup:
            target_page = file_idx_lookup[file_idx]
        elif book_page > 0:
            candidate_page = book_page + int(toc_offset or 0)
            if candidate_page in page_lookup:
                target_page = candidate_page
        if book_page <= 0 and file_idx is not None:
            book_page = int(file_idx) + 1
        resolved["book_page"] = book_page if book_page > 0 else item.get("book_page")
        resolved["book_page_display"] = format_print_page_display(book_page) if book_page > 0 else ""
        resolved["target_page"] = target_page if target_page in page_lookup else None
        resolved["target_pdf_page"] = target_page if target_page in page_lookup else (target_pdf_page if target_pdf_page > 0 else None)
        resolved["unresolved"] = resolved["target_page"] is None
        resolved_items.append(resolved)
    return resolved_items


def _build_pdf_page_lookup(pages: list[dict]) -> tuple[dict[int, dict], dict[int, int]]:
    page_by_pdf_page = {}
    pdf_page_by_file_idx = {}
    for page in pages or []:
        try:
            pdf_page = int(page.get("bookPage"))
            file_idx = int(page.get("fileIdx"))
        except (TypeError, ValueError):
            continue
        page_by_pdf_page[pdf_page] = page
        pdf_page_by_file_idx[file_idx] = pdf_page
    return page_by_pdf_page, pdf_page_by_file_idx


def _build_auto_visual_toc_editor_payload(doc_id: str) -> list[dict]:
    visual_toc = load_auto_visual_toc_from_disk(doc_id)
    if not visual_toc:
        return []
    return _build_auto_visual_toc_editor_payload_from_items(doc_id, visual_toc)


def _build_auto_visual_toc_editor_payload_from_items(doc_id: str, visual_toc: list[dict]) -> list[dict]:
    """按磁盘/JSON 数组顺序构建编辑器数据（与保存顺序一致，不按 PDF 页码重排）。"""
    pages, _ = load_pages_from_disk(doc_id)
    _, pdf_page_by_file_idx = _build_pdf_page_lookup(pages)

    payload = []
    for item in visual_toc:
        try:
            file_idx = int(item.get("file_idx")) if item.get("file_idx") is not None else None
        except (TypeError, ValueError):
            file_idx = None
        try:
            depth = int(item.get("depth") or 0)
        except (TypeError, ValueError):
            depth = 0
        try:
            visual_order = int(item.get("visual_order") or 0)
        except (TypeError, ValueError):
            visual_order = 0
        try:
            book_page = int(item.get("book_page")) if item.get("book_page") is not None else None
        except (TypeError, ValueError):
            book_page = None
        payload.append({
            "item_id": str(item.get("item_id", "") or "").strip(),
            "title": str(item.get("title", "") or ""),
            "depth": depth,
            "file_idx": file_idx,
            "book_page": book_page,
            "pdf_page": int(item.get("target_pdf_page")) if item.get("target_pdf_page") is not None else (pdf_page_by_file_idx.get(file_idx) if file_idx is not None else None),
            "visual_order": visual_order,
        })
    return payload


def _strip_html_table(text: str) -> str:
    """将 HTML <table> 转为制表符分隔的纯文本行。"""
    cleaned = re.sub(r"</?table[^>]*>", "", text)
    cleaned = re.sub(r"</?tbody[^>]*>", "", cleaned)
    cleaned = re.sub(r"</?thead[^>]*>", "", cleaned)
    cleaned = re.sub(r"</tr>", "\n", cleaned)
    cleaned = re.sub(r"<tr[^>]*>", "", cleaned)
    cleaned = re.sub(r"</t[dh]>", "\t", cleaned)
    cleaned = re.sub(r"<t[dh][^>]*>", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
    return "\n".join(lines)


def _extract_json_translation(text: str) -> str | None:
    """尝试从 LLM 返回的 JSON 结构中提取 translation 字段。"""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            for key in ("translation", "翻译", "text", "content"):
                if key in obj and isinstance(obj[key], str):
                    return obj[key].strip()
    except (json.JSONDecodeError, ValueError):
        pass
    for key in ("translation", "翻译"):
        match = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if match:
            return match.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
    for key in ("translation", "翻译"):
        marker = f'"{key}": "'
        idx = text.find(marker)
        if idx < 0:
            continue
        rest = text[idx + len(marker):]
        end = 0
        while end < len(rest):
            if rest[end] == '"' and (end == 0 or rest[end - 1] != "\\"):
                break
            end += 1
        if end > 0:
            return rest[:end].replace("\\n", "\n").replace('\\"', '"').strip()
    return None


def _clean_display_text(text: str) -> str:
    """清洗翻译/原文中的异常格式：JSON 泄漏提取翻译，HTML 表格转可读文本。"""
    if not text:
        return text
    cleaned = text.strip()
    if cleaned.startswith("{") and ('"translation"' in cleaned or '"翻译"' in cleaned):
        extracted = _extract_json_translation(cleaned)
        if extracted:
            cleaned = extracted
    if "<table" in cleaned.lower() and "<td" in cleaned.lower():
        cleaned = _strip_html_table(cleaned)
    return cleaned


_ORPHAN_OCR_IMG_RE = re.compile(
    r"<img\b(?=[^>]*\bsrc=(['\"])imgs/[^'\"]+\1)[^>]*>",
    re.IGNORECASE,
)
_IMG_ALT_RE = re.compile(r"""\balt=(['"])(.*?)\1""", re.IGNORECASE | re.DOTALL)
_EMPTY_DIV_RE = re.compile(r"<div\b[^>]*>\s*</div>", re.IGNORECASE)
_ONLY_PLACEHOLDER_DIV_RE = re.compile(r"<div\b[^>]*>\s*(\[(?:插图|图片)：[^\]]+\])\s*</div>", re.IGNORECASE)


def _replace_orphan_ocr_img(match: re.Match[str]) -> str:
    tag = match.group(0)
    alt_match = _IMG_ALT_RE.search(tag)
    alt_text = html.unescape(alt_match.group(2)).strip() if alt_match else ""
    if alt_text and alt_text.lower() not in {"image", "img"}:
        return f"[插图：{alt_text}]"
    return ""


def _degrade_orphan_ocr_images(text: str) -> str:
    raw = ensure_str(text)
    if not raw:
        return ""
    cleaned = _ORPHAN_OCR_IMG_RE.sub(_replace_orphan_ocr_img, raw)
    cleaned = _ONLY_PLACEHOLDER_DIV_RE.sub(r"\1", cleaned)
    while True:
        reduced = _EMPTY_DIV_RE.sub("", cleaned)
        if reduced == cleaned:
            break
        cleaned = reduced
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _get_partial_failed_bps(doc_id: str, entries: list[dict] | None = None) -> list[int]:
    if entries is None:
        entries, _, _ = load_entries_from_disk(doc_id)
    return sorted(
        entry.get("_pageBP")
        for entry in entries
        if entry.get("_pageBP") is not None
        and any((page_entry.get("_status") == "error") for page_entry in entry.get("_page_entries", []))
    )


def _build_preview_paragraphs(text: str) -> list[str]:
    raw = _degrade_orphan_ocr_images(normalize_latex_footnote_markers(ensure_str(text))).replace("\r\n", "\n").strip()
    raw = strip_html(raw).strip()
    if not raw:
        return []
    blocks = [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"\n{2,}", raw)
        if part and part.strip()
    ]
    if len(blocks) > 1:
        return blocks
    line_blocks = [
        re.sub(r"\s+", " ", line).strip()
        for line in raw.splitlines()
        if line and line.strip()
    ]
    if len(line_blocks) > 1:
        return line_blocks
    single = line_blocks[0] if line_blocks else ""
    if len(single) < 420:
        return line_blocks
    sentence_blocks = [
        part.strip()
        for part in re.split(r'(?<=[\.\!\?…:;»”])\s+(?=[A-ZÀ-ÖØ-Þ0-9«“])', single)
        if part and part.strip()
    ]
    return sentence_blocks or line_blocks


def _render_reading_body_text(text: str) -> str:
    cleaned = _clean_display_text(normalize_latex_footnote_markers(ensure_str(text)))
    return render_superscript_footnote_references(cleaned)


def _render_reading_footnotes_text(text: str) -> str:
    cleaned = _clean_display_text(normalize_latex_footnote_markers(ensure_str(text)))
    return render_reading_footnote_text(cleaned)


def load_fnm_diagnostic_entries(
    doc_id: str,
    *,
    pages: list[dict] | None = None,
    repo: SQLiteRepository | None = None,
) -> list[dict]:
    return list_fnm_diagnostic_entries(doc_id, pages=pages, repo=repo)


def load_fnm_diagnostic_view_entries(
    doc_id: str,
    *,
    pages: list[dict],
    visible_bps: list[int],
    repo: SQLiteRepository | None = None,
) -> list[dict]:
    repo = repo or SQLiteRepository()
    entries: list[dict] = []
    for bp in visible_bps or []:
        entry = get_fnm_diagnostic_entry_for_page(
            doc_id,
            int(bp),
            pages=pages,
            repo=repo,
            allow_fallback=True,
        )
        if entry:
            entries.append(entry)
    return entries


def fnm_translated_bps(
    doc_id: str,
    *,
    visible_bps: list[int] | None = None,
    pages: list[dict] | None = None,
    repo: SQLiteRepository | None = None,
) -> list[int]:
    entries = list_fnm_diagnostic_entries(doc_id, pages=pages, visible_bps=visible_bps, repo=repo)
    visible_set = {int(bp) for bp in (visible_bps or []) if bp is not None}
    page_bps = sorted(
        {
            int(entry.get("_pageBP"))
            for entry in entries
            if entry.get("_pageBP") is not None
            and any(
                str((page_entry or {}).get("_translation_source") or "").strip().lower() not in {"", "source"}
                for page_entry in list((entry or {}).get("_page_entries") or [])
                if isinstance(page_entry, dict)
            )
        }
    )
    if visible_set:
        return [bp for bp in page_bps if bp in visible_set]
    return page_bps


def _reading_done_pages_for_stats(
    snapshot: dict,
    translated_bps: list,
    partial_failed_bps: list,
) -> int:
    task_kind = str((snapshot.get("task") or {}).get("kind") or "")
    phase = str(snapshot.get("phase") or "idle")
    if task_kind == "fnm":
        return int(snapshot.get("done_pages") or 0)
    if task_kind in ("continuous", "glossary_retranslate") or phase in (
        "running",
        "stopping",
        "stopped",
        "error",
        "partial_failed",
    ):
        return int(snapshot.get("done_pages") or 0)
    partial_set = set(partial_failed_bps or [])
    return len([bp for bp in translated_bps if bp not in partial_set])


def build_reading_view_state(
    *,
    doc_id: str,
    view: str,
    pages: list[dict],
    visible_page_view: dict,
    disk_entries: list[dict],
    snapshot: dict,
    repo: SQLiteRepository | None = None,
) -> dict:
    repo = repo or SQLiteRepository()
    mode = str(view or "standard").strip().lower()
    mode = mode if mode in {"standard", "fnm"} else "standard"
    visible_bps = list(visible_page_view.get("visible_page_bps") or [])
    visible_bp_set = {int(bp) for bp in visible_bps if bp is not None}
    if mode == "fnm":
        translated_bps = fnm_translated_bps(
            doc_id,
            visible_bps=visible_bps,
            pages=pages,
            repo=repo,
        )
        translated_bp_set = set(translated_bps)
        return {
            "mode": "fnm",
            "page_bps": visible_bps,
            "translated_bps": translated_bps,
            "failed_bps": [],
            "partial_failed_bps": [],
            "source_only_bps": [bp for bp in visible_bps if bp not in translated_bp_set],
            "reading_stats_done_pages": len(translated_bps),
            "done_pages": len(translated_bps),
            "partial_failed_pages": 0,
            "failed_pages": 0,
            "page_total": len(visible_bps),
        }
    translated_bps = sorted(
        int(entry.get("_pageBP"))
        for entry in (disk_entries or [])
        if entry.get("_pageBP") is not None and int(entry.get("_pageBP")) in visible_bp_set
    )
    failed_bps = [
        int(bp) for bp in (snapshot.get("failed_bps") or [])
        if bp is not None and int(bp) in visible_bp_set
    ]
    partial_failed_bps = snapshot.get("partial_failed_bps")
    if partial_failed_bps is None:
        partial_failed_bps = _get_partial_failed_bps(doc_id, entries=disk_entries)
    partial_failed_bps = [
        int(bp) for bp in partial_failed_bps
        if bp is not None and int(bp) in visible_bp_set
    ]
    return {
        "mode": "standard",
        "page_bps": visible_bps,
        "translated_bps": translated_bps,
        "failed_bps": failed_bps,
        "partial_failed_bps": partial_failed_bps,
        "source_only_bps": [],
        "reading_stats_done_pages": _reading_done_pages_for_stats(
            snapshot,
            translated_bps,
            partial_failed_bps,
        ),
        "done_pages": len(translated_bps),
        "partial_failed_pages": len(partial_failed_bps),
        "failed_pages": len(failed_bps),
        "page_total": len(visible_bps),
    }


def reading_view_summary_text(state: dict, task_snapshot: dict, current_bp: int, last_page: int) -> str:
    mode = str(state.get("mode") or "standard")
    if mode == "fnm":
        return (
            f"已投影{len(state.get('translated_bps') or [])}页 · "
            f"已完成{int(task_snapshot.get('done_units', 0) or 0)}个 unit · "
            f"失败{int(task_snapshot.get('error_units', 0) or 0)}个 unit · "
            f"当前 PDF 第{int(current_bp)}页 / 第{int(last_page)}页"
        )
    return (
        f"已译{int(state.get('reading_stats_done_pages', 0) or 0)}页 · "
        f"部分完成{len(state.get('partial_failed_bps') or [])}页 · "
        f"失败{len(state.get('failed_bps') or [])}页 · "
        f"当前 PDF 第{int(current_bp)}页 / 第{int(last_page)}页"
    )


def enrich_translate_snapshot_for_reading_view(
    snapshot: dict,
    *,
    doc_id: str,
    entries: list[dict],
    visible_page_view: dict,
    view: str,
) -> dict:
    visible_bp_set = set(visible_page_view["visible_page_bps"])
    if view == "fnm":
        snapshot.update(build_fnm_unit_progress(doc_id, snapshot=snapshot))
        snapshot["translated_bps"] = fnm_translated_bps(
            doc_id,
            visible_bps=visible_page_view["visible_page_bps"],
        )
        snapshot["failed_bps"] = []
        snapshot["failed_pages"] = []
        snapshot["partial_failed_bps"] = []
        snapshot["reading_stats_done_pages"] = len(snapshot["translated_bps"])
        return snapshot
    snapshot["translated_bps"] = sorted(
        entry.get("_pageBP")
        for entry in entries
        if entry.get("_pageBP") is not None and int(entry.get("_pageBP")) in visible_bp_set
    )
    snapshot["failed_bps"] = [
        int(bp) for bp in snapshot.get("failed_bps", [])
        if bp is not None and int(bp) in visible_bp_set
    ]
    snapshot["failed_pages"] = [
        page for page in snapshot.get("failed_pages", [])
        if isinstance(page, dict) and page.get("bp") is not None and int(page.get("bp")) in visible_bp_set
    ]
    partial_failed_bps = snapshot.get("partial_failed_bps")
    if partial_failed_bps is None:
        partial_failed_bps = _get_partial_failed_bps(doc_id, entries=entries)
    snapshot["partial_failed_bps"] = [
        int(bp) for bp in partial_failed_bps
        if bp is not None and int(bp) in visible_bp_set
    ]
    snapshot["reading_stats_done_pages"] = _reading_done_pages_for_stats(
        snapshot,
        snapshot.get("translated_bps") or [],
        snapshot.get("partial_failed_bps") or [],
    )
    return snapshot


def build_display_entries(
    page_entries: list[dict],
    *,
    cur_page_bp: int,
    glossary: list[dict],
    page_lookup: dict[int, dict],
) -> list[dict]:
    display_entries = []
    for pe in page_entries or []:
        pe_copy = dict(pe)
        pe_copy["original_plain"] = ensure_str(pe_copy.get("original", "")).strip()
        for field in ("original", "translation"):
            pe_copy[field] = _render_reading_body_text(pe_copy.get(field))
        for field in ("footnotes", "footnotes_translation"):
            pe_copy[field] = _render_reading_footnotes_text(pe_copy.get(field))
        start_bp = pe_copy.get("_startBP")
        end_bp = pe_copy.get("_endBP")
        try:
            start_bp = int(start_bp) if start_bp is not None else cur_page_bp
        except (TypeError, ValueError):
            start_bp = cur_page_bp
        try:
            end_bp = int(end_bp) if end_bp is not None else start_bp
        except (TypeError, ValueError):
            end_bp = start_bp
        pe_copy["_startBP"] = start_bp
        pe_copy["_endBP"] = end_bp
        raw_print_label = str(pe_copy.get("_printPageLabel") or "").strip()
        if not raw_print_label:
            start_label = resolve_page_print_label(page_lookup.get(start_bp))
            end_label = resolve_page_print_label(page_lookup.get(end_bp))
            if start_label and end_label and start_label != end_label:
                raw_print_label = f"{start_label}-{end_label}"
            else:
                raw_print_label = start_label or end_label
            pe_copy["_printPageLabel"] = raw_print_label
        pe_copy["pages_display"] = format_print_page_display(raw_print_label)
        pe_copy["original_html"] = highlight_terms(_degrade_orphan_ocr_images(pe_copy["original"]), glossary)
        pe_copy["original_source_label"] = (
            "人工修订原文" if str(pe_copy.get("_original_source") or "") == "manual" else "OCR 原文"
        )
        pe_copy["section_path_display"] = " > ".join(
            str(item).strip()
            for item in (pe_copy.get("_section_path") or [])
            if str(item).strip()
        )
        pe_copy["fnm_ref_labels"] = [
            (
                ("FN" if str(ref.get("kind") or "") == "footnote" else "EN")
                + ":"
                + str(ref.get("note_id") or "").strip()
            )
            for ref in (pe_copy.get("_fnm_refs") or [])
            if isinstance(ref, dict) and str(ref.get("note_id") or "").strip()
        ]
        display_entries.append(pe_copy)
    return display_entries


def build_fnm_page_context(
    doc_id: str,
    *,
    current_bp: int,
    fnm_run: dict | None,
    repo: SQLiteRepository | None = None,
) -> dict:
    repo = repo or SQLiteRepository()
    section = repo.get_fnm_section_for_page(doc_id, current_bp) if fnm_run else None
    notes = list_fnm_diagnostic_notes(doc_id, repo=repo) if fnm_run else []
    footnotes = [
        note for note in notes
        if note.get("kind") == "footnote" and int(note.get("start_page") or 0) == int(current_bp)
    ]
    endnotes = [
        note for note in notes
        if note.get("kind") == "endnote"
        and section
        and note.get("section_id") == section.get("section_id")
    ]
    validation = None
    if fnm_run and fnm_run.get("validation_json"):
        try:
            validation = json.loads(fnm_run["validation_json"])
        except Exception:
            validation = None
    unresolved = []
    if isinstance(validation, dict):
        for item in validation.get("unresolved") or []:
            if not isinstance(item, dict):
                continue
            suggested_pages = item.get("suggested_pages") or []
            try:
                page_items = [int(x) for x in suggested_pages]
            except (TypeError, ValueError):
                page_items = []
            if int(current_bp) in page_items or not page_items:
                unresolved.append(item)
    retry_summary = build_fnm_retry_summary(doc_id, repo=repo) if fnm_run else {}
    failed_locations = list(retry_summary.get("failed_locations") or [])
    failed_here = [
        item for item in failed_locations
        if int(item.get("page_no") or 0) == int(current_bp)
    ]
    return {
        "section": section,
        "footnotes": footnotes,
        "endnotes": endnotes,
        "validation": validation,
        "unresolved_here": unresolved,
        "failed_here": failed_here,
        "retry_summary": retry_summary,
    }


def build_page_notes_panel(
    *,
    current_view: str,
    display_entries: list[dict],
    diagnostic_footnotes: list[dict] | None = None,
    diagnostic_endnotes: list[dict] | None = None,
    diagnostic_failed_locations: list[dict] | None = None,
    diagnostic_failed_summary: dict | None = None,
    next_bp: int | None = None,
) -> dict | None:
    mode = str(current_view or "standard").strip().lower()
    if mode == "fnm":
        groups = []
        failed_locations = list(diagnostic_failed_locations or [])
        failed_summary = dict(diagnostic_failed_summary or {})
        if failed_locations or failed_summary.get("manual_required_locations") or failed_summary.get("failed_locations"):
            groups.append({
                "kind": "fnm_diagnostic_failures",
                "label": "翻译失败",
                "items": failed_locations,
                "summary": failed_summary,
            })
        if diagnostic_footnotes:
            groups.append({
                "kind": "fnm_diagnostic_notes",
                "label": "本页脚注",
                "notes": list(diagnostic_footnotes or []),
            })
        if diagnostic_endnotes:
            groups.append({
                "kind": "fnm_diagnostic_notes",
                "label": "当前节尾注",
                "notes": list(diagnostic_endnotes or []),
            })
        if not groups:
            return None
        return {
            "title": "页面注释",
            "subtitle": "当前页脚注按页展示，当前节尾注按节展示。",
            "bridge": "",
            "next_bp": next_bp,
            "groups": groups,
        }

    originals = []
    translations = []
    for pe in display_entries or []:
        original_note = str(pe.get("footnotes") or "").strip()
        translated_note = str(pe.get("footnotes_translation") or "").strip()
        if original_note and original_note not in originals:
            originals.append(original_note)
        if translated_note and translated_note not in translations:
            translations.append(translated_note)
    if not originals and not translations:
        return None
    return {
        "title": "页面注释",
        "subtitle": "脚注统一放在整页正文之后，便于连续阅读和做笔记。",
        "bridge": "这一页的脚注仍属于当前阅读节奏，可以顺着正文往下看。",
        "next_bp": next_bp,
        "groups": [{
            "kind": "standard_page_footnotes",
            "label": "本页脚注",
            "original_text": "\n\n".join(originals).strip(),
            "translation_text": "\n\n".join(translations).strip(),
        }],
    }

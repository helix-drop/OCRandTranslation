"""FNM_RE 翻译单元与只读诊断 helper。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from FNM_RE.app.mainline import list_phase6_diagnostic_entries_for_doc, list_phase6_diagnostic_notes_for_doc
from FNM_RE.shared.refs import extract_note_refs, replace_frozen_refs
from FNM_RE.shared.segments import normalize_fnm_segment, segment_paragraphs, split_fnm_paragraphs
from persistence.storage import format_print_page_display, resolve_page_print_label
from document.text_utils import ensure_str
from document.text_processing import (
    assign_page_footnotes_to_paragraphs,
    get_page_context_for_translate,
    get_paragraph_bboxes,
    parse_page_markdown,
)
from persistence.sqlite_store import SQLiteRepository

if TYPE_CHECKING:
    pass


def frozen_body_text_for_page(units: list[dict], bp: int) -> str:
    """合并所有 body unit 中该 book_page 的 frozen source 段落。"""
    parts: list[str] = []
    for unit in units or []:
        if str(unit.get("kind") or "") != "body":
            continue
        for seg in unit.get("page_segments") or []:
            if int(seg.get("page_no") or 0) == int(bp):
                t = str(seg.get("source_text") or "").strip()
                if t:
                    parts.append(t)
    return "\n\n".join(parts).strip()


def should_translate_footnote_on_page(note: dict, bp: int) -> bool:
    """脚注仅在起始页翻译一次（source_text 已为整段合并内容）；跨页脚注的后续页不重复翻译。"""
    if str(note.get("kind") or "") != "footnote":
        return False
    return int(note.get("start_page") or 0) == int(bp)


def should_translate_endnote_on_page(note: dict, bp: int) -> bool:
    """尾注在 FNM 记录的起始页翻译。"""
    if str(note.get("kind") or "") != "endnote":
        return False
    return int(note.get("start_page") or 0) == int(bp)


def _fnm_note_job(
    *,
    note: dict,
    target_bp: int,
    ctx: dict,
    para_idx: int,
    para_total: int,
    content_role: str,
) -> dict:
    st = (ctx.get("print_page_display", "") or "").strip()
    return {
        "para_idx": para_idx,
        "source_idx": -1,
        "bp": target_bp,
        "heading_level": 0,
        "text": str(note.get("source_text") or "").strip(),
        "cross_page": None,
        "start_bp": target_bp,
        "end_bp": target_bp,
        "print_page_label": str(ctx.get("print_page_label", "") or "").strip(),
        "print_page_display": st,
        "bboxes": [],
        "footnotes": "",
        "prev_context": "",
        "next_context": "",
        "section_path": [],
        "content_role": content_role,
        "note_kind": content_role,
        "note_marker": str(note.get("original_marker") or "").strip(),
        "note_number": None,
        "note_section_title": str(note.get("section_title") or "").strip(),
        "note_confidence": 0.0,
        "fnm_note_id": str(note.get("note_id") or "").strip(),
        "para_total": para_total,
    }


def _body_job_from_parts(
    *,
    text: str,
    target_bp: int,
    ctx: dict,
    para_idx: int,
    para_total: int,
    heading_level: int,
    cross_page,
    print_page_label: str,
    print_page_display: str,
    prev_context: str,
    next_context: str,
    section_path: list,
) -> dict:
    return {
        "para_idx": para_idx,
        "source_idx": para_idx,
        "bp": target_bp,
        "heading_level": heading_level,
        "text": text,
        "cross_page": cross_page,
        "start_bp": target_bp,
        "end_bp": target_bp,
        "print_page_label": print_page_label,
        "print_page_display": print_page_display,
        "bboxes": [],
        "footnotes": "",
        "prev_context": prev_context,
        "next_context": next_context,
        "section_path": section_path,
        "content_role": "body",
        "note_kind": "",
        "note_marker": "",
        "note_number": None,
        "note_section_title": "",
        "note_confidence": 0.0,
        "fnm_note_id": "",
        "para_total": para_total,
    }


def prepare_page_translate_jobs(
    pages: list,
    target_bp: int,
    t_args: dict,
    doc_id: str,
    *,
    repo: SQLiteRepository | None = None,
) -> tuple[dict, list[dict], dict]:
    """
    构建 FNM 页级翻译任务。与 _prepare_page_translate_jobs 返回形状一致。
    无 FNM 正文时回退到标准 OCR 段落解析（仍带 is_fnm 流式翻译）。
    """
    repo = repo or SQLiteRepository()
    units = repo.list_fnm_translation_units(doc_id)
    notes = list_phase6_diagnostic_notes_for_doc(doc_id, repo=repo)

    ctx = get_page_context_for_translate(pages, target_bp)
    total_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }

    frozen = frozen_body_text_for_page(units, target_bp)
    md_paras = [
        para
        for para in parse_page_markdown(pages, target_bp)
        if not para.get("consumed_by_prev")
    ]
    context_window = 200

    def _trim_prev(s: str, limit: int) -> str:
        s = (s or "").strip()
        return s[-limit:] if len(s) > limit else s

    def _trim_next(s: str, limit: int) -> str:
        s = (s or "").strip()
        return s[:limit] if len(s) > limit else s

    def _build_para_jobs_from_frozen() -> list[dict]:
        parts = split_fnm_paragraphs(frozen) if frozen else []
        if not parts:
            return []
        n = max(len(md_paras), len(parts))
        jobs: list[dict] = []
        title_stack: list[str] = []
        for i in range(n):
            text = parts[i] if i < len(parts) else ""
            if not text.strip():
                continue
            if i < len(md_paras):
                p = md_paras[i]
                hlevel = int(p.get("heading_level", 0) or 0)
                cross = p.get("cross_page")
                plab = str(p.get("printPageLabel", "") or "").strip()
                pdis = (
                    f"原书 p.{plab}"
                    if plab
                    else str(ctx.get("print_page_display", "") or "").strip()
                )
            else:
                hlevel = 0
                cross = None
                plab = str(ctx.get("print_page_label", "") or "").strip()
                pdis = str(ctx.get("print_page_display", "") or "").strip()

            if hlevel > 0:
                while len(title_stack) >= hlevel:
                    title_stack.pop()
                title_stack.append(text)

            prev_text = ""
            next_text = ""
            for j in range(i - 1, -1, -1):
                if j < len(parts) and parts[j].strip():
                    prev_text = parts[j]
                    break
            for j in range(i + 1, len(parts)):
                if parts[j].strip():
                    next_text = parts[j]
                    break
            if not prev_text and cross in ("cont_prev", "cont_both"):
                prev_text = ctx.get("prev_tail", "") or ""
            if not next_text and cross in ("cont_next", "cont_both", "merged_next"):
                next_text = ctx.get("next_head", "") or ""

            prev_ctx = "" if hlevel > 0 else _trim_prev(prev_text, context_window)
            next_ctx = "" if hlevel > 0 else _trim_next(next_text, context_window)

            jobs.append(
                _body_job_from_parts(
                    text=text,
                    target_bp=target_bp,
                    ctx=ctx,
                    para_idx=len(jobs),
                    para_total=0,
                    heading_level=hlevel,
                    cross_page=cross,
                    print_page_label=plab,
                    print_page_display=pdis,
                    prev_context=prev_ctx,
                    next_context=next_ctx,
                    section_path=list(title_stack),
                )
            )
        return jobs

    para_jobs: list[dict] = []

    if frozen:
        para_jobs = _build_para_jobs_from_frozen()
    if not para_jobs and md_paras:
        from translation.service import _build_para_jobs

        para_bboxes = get_paragraph_bboxes(pages, target_bp, md_paras) if md_paras else []
        md_use = md_paras
        if md_use:
            md_use, _resolved = assign_page_footnotes_to_paragraphs(
                pages,
                target_bp,
                md_use,
                para_bboxes=para_bboxes,
            )
        para_jobs = _build_para_jobs(md_use, ctx, para_bboxes, target_bp, context_window=context_window)

    # FNM 脚注 / 尾注（独立翻译单元）
    for note in notes:
        if should_translate_footnote_on_page(note, target_bp):
            para_jobs.append(
                _fnm_note_job(
                    note=note,
                    target_bp=target_bp,
                    ctx=ctx,
                    para_idx=len(para_jobs),
                    para_total=0,
                    content_role="footnote",
                )
            )
        elif should_translate_endnote_on_page(note, target_bp):
            para_jobs.append(
                _fnm_note_job(
                    note=note,
                    target_bp=target_bp,
                    ctx=ctx,
                    para_idx=len(para_jobs),
                    para_total=0,
                    content_role="endnote",
                )
            )

    if not para_jobs:
        raise RuntimeError(f"第{target_bp}页未找到有效内容")

    for idx, job in enumerate(para_jobs):
        job["para_idx"] = idx
        job["para_total"] = len(para_jobs)

    return ctx, para_jobs, total_usage


def _page_lookup(pages: list[dict]) -> dict[int, dict]:
    return {
        int(page.get("bookPage")): page
        for page in (pages or [])
        if page.get("bookPage") is not None
    }


def _raw_pages_label(page_no: int, pages: list[dict]) -> str:
    page = _page_lookup(pages).get(int(page_no))
    return resolve_page_print_label(page) or str(int(page_no))


def _display_pages_label(page_no: int, pages: list[dict]) -> str:
    return format_print_page_display(_raw_pages_label(page_no, pages))


def _segment_paragraphs(
    segment: dict,
    *,
    section_title: str = "",
    pages: list[dict] | None = None,
) -> list[dict]:
    page_no = int(segment.get("page_no") or 0)
    print_page_label = (
        _raw_pages_label(page_no, pages or [])
        if page_no > 0 and pages is not None
        else ensure_str(segment.get("print_page_label", "")).strip() or (str(page_no) if page_no > 0 else "")
    )
    return segment_paragraphs(segment, section_title=section_title, print_page_label=print_page_label)


def _normalized_segment(
    segment: dict,
    *,
    section_title: str = "",
    pages: list[dict] | None = None,
) -> tuple[dict, bool]:
    page_no = int(segment.get("page_no") or 0)
    print_page_label = (
        _raw_pages_label(page_no, pages or [])
        if page_no > 0 and pages is not None
        else ensure_str(segment.get("print_page_label", "")).strip() or (str(page_no) if page_no > 0 else "")
    )
    return normalize_fnm_segment(segment, section_title=section_title, print_page_label=print_page_label)


def list_fnm_units_with_indices(doc_id: str, *, repo: SQLiteRepository | None = None) -> list[dict]:
    repo = repo or SQLiteRepository()
    units = repo.list_fnm_translation_units(doc_id)
    indexed: list[dict] = []
    for idx, unit in enumerate(units, start=1):
        item = dict(unit)
        item["unit_idx"] = idx
        indexed.append(item)
    return indexed


def unit_page_numbers(unit: dict) -> list[int]:
    page_numbers = sorted({
        int(segment.get("page_no"))
        for segment in (unit.get("page_segments") or [])
        if segment.get("page_no") is not None
    })
    if page_numbers:
        return page_numbers
    start_page = unit.get("page_start")
    end_page = unit.get("page_end")
    if start_page is None:
        return []
    start_page = int(start_page)
    end_page = int(end_page if end_page is not None else start_page)
    if end_page < start_page:
        end_page = start_page
    return list(range(start_page, end_page + 1))


def format_fnm_unit_pages(unit: dict) -> str:
    pages = unit_page_numbers(unit)
    if not pages:
        return "-"
    if len(pages) == 1:
        return str(pages[0])
    return f"{pages[0]}-{pages[-1]}"


def format_fnm_unit_label(unit: dict) -> str:
    kind = str(unit.get("kind") or "").strip()
    kind_label = {
        "body": "正文",
        "footnote": "脚注",
        "endnote": "尾注",
    }.get(kind, kind or "unit")
    section = ensure_str(unit.get("section_title") or unit.get("section_id") or "").strip()
    pages_label = format_fnm_unit_pages(unit)
    if section:
        return f"{kind_label} · {section} · p.{pages_label}"
    return f"{kind_label} · p.{pages_label}"


def build_fnm_body_unit_jobs(unit: dict, pages: list[dict]) -> list[dict]:
    paragraph_rows: list[dict] = []
    section_title = ensure_str(unit.get("section_title", "")).strip()
    for segment in unit.get("page_segments") or []:
        normalized_segment, _changed = _normalized_segment(segment, section_title=section_title, pages=pages)
        page_no = int(normalized_segment.get("page_no") or 0)
        if page_no <= 0:
            continue
        raw_label = _raw_pages_label(page_no, pages)
        display_label = format_print_page_display(raw_label)
        for paragraph in normalized_segment.get("paragraphs") or []:
            text = ensure_str(paragraph.get("source_text", "")).strip()
            if not text or paragraph.get("consumed_by_prev"):
                continue
            paragraph_rows.append({
                "page_no": page_no,
                "text": text,
                "heading_level": int(paragraph.get("heading_level", 0) or 0),
                "cross_page": paragraph.get("cross_page"),
                "print_page_label": raw_label,
                "print_page_display": display_label,
                "section_path": list(paragraph.get("section_path") or ([section_title] if section_title else [])),
            })
    jobs: list[dict] = []
    for idx, row in enumerate(paragraph_rows):
        prev_text = paragraph_rows[idx - 1]["text"] if idx > 0 else ""
        next_text = paragraph_rows[idx + 1]["text"] if idx + 1 < len(paragraph_rows) else ""
        jobs.append(
            {
                "para_idx": idx,
                "para_total": 0,
                "source_idx": idx,
                "bp": int(row["page_no"]),
                "heading_level": int(row.get("heading_level", 0) or 0),
                "text": row["text"],
                "cross_page": row.get("cross_page"),
                "start_bp": int(row["page_no"]),
                "end_bp": int(row["page_no"]),
                "print_page_label": row["print_page_label"],
                "print_page_display": row["print_page_display"],
                "bboxes": [],
                "footnotes": "",
                "prev_context": "" if int(row.get("heading_level", 0) or 0) > 0 else (prev_text[-200:] if prev_text else ""),
                "next_context": "" if int(row.get("heading_level", 0) or 0) > 0 else (next_text[:200] if next_text else ""),
                "section_path": list(row["section_path"]),
                "content_role": "body",
                "note_kind": "",
                "note_marker": "",
                "note_number": None,
                "note_section_title": "",
                "note_confidence": 0.0,
            }
        )
    for idx, job in enumerate(jobs):
        job["para_idx"] = idx
        job["para_total"] = len(jobs)
    return jobs


def apply_body_unit_translations(unit: dict, translated_paragraphs: list[str]) -> dict:
    translated = [ensure_str(text).strip() for text in (translated_paragraphs or [])]
    updated_segments: list[dict] = []
    cursor = 0
    total_parts = 0
    section_title = ensure_str(unit.get("section_title", "")).strip()
    for segment in unit.get("page_segments") or []:
        normalized_segment, _changed = _normalized_segment(segment, section_title=section_title)
        paragraphs = [
            dict(paragraph)
            for paragraph in (normalized_segment.get("paragraphs") or [])
            if not paragraph.get("consumed_by_prev")
        ]
        total_parts += len(paragraphs)
        next_cursor = cursor + len(paragraphs)
        if next_cursor > len(translated):
            raise RuntimeError("FNM body unit 段落数与译文数不一致")
        translated_parts = translated[cursor:next_cursor]
        cursor = next_cursor
        segment_payload = dict(normalized_segment)
        updated_paragraphs = []
        translated_iter = iter(translated_parts)
        for paragraph in normalized_segment.get("paragraphs") or []:
            paragraph_payload = dict(paragraph)
            if paragraph_payload.get("consumed_by_prev"):
                paragraph_payload["translated_text"] = ""
            else:
                paragraph_payload["translated_text"] = next(translated_iter, "")
            updated_paragraphs.append(paragraph_payload)
        segment_payload["paragraphs"] = updated_paragraphs
        segment_payload["translated_parts"] = list(translated_parts)
        segment_payload["translated_text"] = "\n\n".join(translated_parts).strip()
        updated_segments.append(segment_payload)
    if cursor != len(translated) or cursor != total_parts:
        raise RuntimeError("FNM body unit 段落数与译文数不一致")
    return {
        "translated_text": "\n\n".join(translated).strip(),
        "page_segments": updated_segments,
    }


def apply_body_unit_entry_result(
    unit: dict,
    entry: dict,
    *,
    apply_only_unresolved: bool = False,
) -> dict:
    page_entries = list(entry.get("_page_entries") or [])
    updated_segments: list[dict] = []
    failed_locations: list[dict] = []
    visible_translated_parts: list[str] = []
    cursor = 0
    section_title = ensure_str(unit.get("section_title", "")).strip()
    unresolved_statuses = {"error", "retry_pending", "retrying", "manual_required"}

    for segment in unit.get("page_segments") or []:
        normalized_segment, _changed = _normalized_segment(segment, section_title=section_title)
        segment_payload = dict(normalized_segment)
        updated_paragraphs = []
        segment_translated_parts: list[str] = []
        page_no = int(segment_payload.get("page_no") or 0)
        visible_idx = 0
        for paragraph in normalized_segment.get("paragraphs") or []:
            paragraph_payload = dict(paragraph)
            if paragraph_payload.get("consumed_by_prev"):
                paragraph_payload["translated_text"] = ""
                updated_paragraphs.append(paragraph_payload)
                continue
            if cursor >= len(page_entries):
                raise RuntimeError("FNM body unit 段落数与流式结果不一致")
            page_entry = dict(page_entries[cursor] or {})
            cursor += 1
            current_status = str(paragraph_payload.get("translation_status") or "").strip()
            should_apply = (not apply_only_unresolved) or (current_status in unresolved_statuses) or not current_status
            if should_apply:
                translated_text = ensure_str(page_entry.get("translation", "")).strip()
                error_text = ensure_str(page_entry.get("_error", "")).strip()
                entry_status = str(page_entry.get("_status") or "done").strip().lower() or "done"
                paragraph_payload["attempt_count"] = max(0, int(paragraph_payload.get("attempt_count", 0) or 0)) + 1
                paragraph_payload["manual_resolved"] = bool(paragraph_payload.get("manual_resolved"))
                if entry_status == "done" and translated_text and not translated_text.startswith("[翻译失败:"):
                    paragraph_payload["translated_text"] = translated_text
                    paragraph_payload["translation_status"] = (
                        "manual_resolved" if paragraph_payload.get("manual_resolved") else "done"
                    )
                    paragraph_payload["last_error"] = ""
                else:
                    paragraph_payload["translated_text"] = ""
                    paragraph_payload["translation_status"] = "error"
                    paragraph_payload["last_error"] = error_text or translated_text or "翻译失败"
            translated_text = ensure_str(paragraph_payload.get("translated_text", "")).strip()
            if translated_text:
                segment_translated_parts.append(translated_text)
                visible_translated_parts.append(translated_text)
            paragraph_status = str(paragraph_payload.get("translation_status") or "").strip()
            if paragraph_status in unresolved_statuses and not bool(paragraph_payload.get("manual_resolved")):
                failed_locations.append({
                    "unit_id": ensure_str(unit.get("unit_id") or "").strip(),
                    "section_title": section_title,
                    "page_no": page_no,
                    "para_idx": visible_idx,
                    "error": ensure_str(paragraph_payload.get("last_error", "")).strip(),
                    "status": paragraph_status,
                })
            updated_paragraphs.append(paragraph_payload)
            visible_idx += 1
        segment_payload["paragraphs"] = updated_paragraphs
        segment_payload["translated_parts"] = list(segment_translated_parts)
        segment_payload["translated_text"] = "\n\n".join(segment_translated_parts).strip()
        updated_segments.append(segment_payload)

    if cursor != len(page_entries):
        raise RuntimeError("FNM body unit 段落数与流式结果不一致")
    return {
        "translated_text": "\n\n".join(visible_translated_parts).strip(),
        "page_segments": updated_segments,
        "failed_locations": failed_locations,
    }


def collect_fnm_unit_failed_locations(unit: dict) -> list[dict]:
    section_title = ensure_str(unit.get("section_title", "")).strip()
    locations: list[dict] = []
    for segment in unit.get("page_segments") or []:
        page_no = int(segment.get("page_no") or 0)
        visible_idx = 0
        for paragraph in segment.get("paragraphs") or []:
            if paragraph.get("consumed_by_prev"):
                continue
            status = str(paragraph.get("translation_status") or "").strip()
            if status in {"error", "retry_pending", "retrying", "manual_required"} and not bool(paragraph.get("manual_resolved")):
                locations.append({
                    "unit_id": ensure_str(unit.get("unit_id") or "").strip(),
                    "section_title": section_title,
                    "page_no": page_no,
                    "para_idx": visible_idx,
                    "error": ensure_str(paragraph.get("last_error", "")).strip(),
                    "status": status,
                })
            visible_idx += 1
    return locations


def build_retry_summary(
    doc_id: str,
    *,
    snapshot: dict | None = None,
    repo: SQLiteRepository | None = None,
) -> dict:
    repo = repo or SQLiteRepository()
    if snapshot is None and doc_id:
        from translation.translate_store import _load_translate_state

        snapshot = _load_translate_state(doc_id)
    snapshot = dict(snapshot or {})
    failed_locations = snapshot.get("failed_locations")
    if not isinstance(failed_locations, list):
        failed_locations = []
    manual_required_locations = snapshot.get("manual_required_locations")
    if not isinstance(manual_required_locations, list):
        manual_required_locations = []
    if not failed_locations or not manual_required_locations:
        derived_failed: list[dict] = []
        derived_manual: list[dict] = []
        for unit in repo.list_fnm_translation_units(doc_id):
            if str(unit.get("kind") or "") != "body":
                continue
            for item in collect_fnm_unit_failed_locations(unit):
                derived_failed.append(item)
                if item.get("status") == "manual_required":
                    derived_manual.append(item)
        if not failed_locations:
            failed_locations = derived_failed
        if not manual_required_locations:
            manual_required_locations = derived_manual
    unresolved_count = max(
        0,
        int(snapshot.get("unresolved_count", len(failed_locations)) or 0),
    )
    manual_required_count = max(
        0,
        int(snapshot.get("manual_required_count", len(manual_required_locations)) or 0),
    )
    execution_mode = str(snapshot.get("execution_mode", "test") or "test").strip().lower() or "test"
    # real 模式下即使仍有失败项，也不再阻塞导出；失败信息仅用于提示与后续人工修订。
    blocking_export = False
    reason = ""
    if manual_required_count > 0:
        reason = "manual_required"
    elif unresolved_count > 0:
        reason = "unresolved"
    next_failed_location = snapshot.get("next_failed_location")
    if not isinstance(next_failed_location, dict):
        next_failed_location = (manual_required_locations or failed_locations or [None])[0]
    return {
        "execution_mode": execution_mode,
        "retry_progress": {
            "retry_round": max(0, int(snapshot.get("retry_round", 0) or 0)),
            "unresolved_count": unresolved_count,
            "manual_required_count": manual_required_count,
        },
        "failed_locations": failed_locations,
        "manual_required_locations": manual_required_locations,
        "next_failed_location": next_failed_location,
        "blocking_export": blocking_export,
        "blocking_reason": reason,
    }


def sync_fnm_retry_state(doc_id: str, *, repo: SQLiteRepository | None = None) -> dict:
    from translation.translate_store import _load_translate_state, _save_translate_state

    repo = repo or SQLiteRepository()
    snapshot = _load_translate_state(doc_id)
    summary = build_retry_summary(doc_id, snapshot=snapshot, repo=repo)
    _save_translate_state(
        doc_id,
        running=bool(snapshot.get("running", False)),
        stop_requested=bool(snapshot.get("stop_requested", False)),
        phase=snapshot.get("phase", "idle"),
        execution_mode=summary.get("execution_mode") or snapshot.get("execution_mode", "test"),
        retry_round=int(snapshot.get("retry_round", 0) or 0),
        unresolved_count=int(summary.get("retry_progress", {}).get("unresolved_count", 0) or 0),
        manual_required_count=int(summary.get("retry_progress", {}).get("manual_required_count", 0) or 0),
        next_failed_location=summary.get("next_failed_location"),
        failed_locations=summary.get("failed_locations") or [],
        manual_required_locations=summary.get("manual_required_locations") or [],
    )
    return summary


def _segment_translated_parts(segment: dict) -> list[str]:
    paragraphs = segment.get("paragraphs")
    if isinstance(paragraphs, list) and paragraphs:
        translated = [
            ensure_str(paragraph.get("translated_text", "")).strip()
            for paragraph in paragraphs
            if not paragraph.get("consumed_by_prev") and ensure_str(paragraph.get("translated_text", "")).strip()
        ]
        if translated:
            return translated
    translated_parts = segment.get("translated_parts")
    if isinstance(translated_parts, list) and translated_parts:
        return [ensure_str(text).strip() for text in translated_parts if ensure_str(text).strip()]
    translated_text = ensure_str(segment.get("translated_text", "")).strip()
    if translated_text:
        return split_fnm_paragraphs(translated_text)
    return []


def _body_unit_segments_with_translation(unit: dict) -> list[dict]:
    section_title = ensure_str(unit.get("section_title", "")).strip()
    segments = [_normalized_segment(segment, section_title=section_title)[0] for segment in (unit.get("page_segments") or [])]
    if not segments:
        return []
    if any(_segment_translated_parts(segment) for segment in segments):
        return segments
    translated_text = ensure_str(unit.get("translated_text", "")).strip()
    if not translated_text:
        return segments
    translated_parts = split_fnm_paragraphs(translated_text)
    cursor = 0
    for segment in segments:
        paragraphs = [
            paragraph for paragraph in (segment.get("paragraphs") or [])
            if not paragraph.get("consumed_by_prev")
        ]
        next_cursor = cursor + len(paragraphs)
        current_parts = translated_parts[cursor:next_cursor]
        cursor = next_cursor
        translated_iter = iter(current_parts)
        updated_paragraphs = []
        for paragraph in segment.get("paragraphs") or []:
            payload = dict(paragraph)
            if payload.get("consumed_by_prev"):
                payload["translated_text"] = ""
            else:
                payload["translated_text"] = next(translated_iter, "")
            updated_paragraphs.append(payload)
        segment["paragraphs"] = updated_paragraphs
        segment["translated_parts"] = list(current_parts)
        segment["translated_text"] = "\n\n".join(current_parts).strip()
    return segments


def _fnm_page_entry_item(page_no: int, pages: list[dict], paragraph: dict) -> dict:
    raw_label = _raw_pages_label(page_no, pages)
    display_label = _display_pages_label(page_no, pages)
    source_text = ensure_str(paragraph.get("display_text") or paragraph.get("source_text") or "").strip()
    translated_text = ensure_str(paragraph.get("translated_text", "")).strip()
    translation_status = str(paragraph.get("translation_status") or "").strip()
    paragraph_error = ensure_str(paragraph.get("last_error", "")).strip()
    body_text = replace_frozen_refs(translated_text or source_text)
    ref_payload: list[dict] = []
    seen_refs: set[tuple[str, str]] = set()
    for candidate in (
        paragraph.get("source_text"),
        paragraph.get("display_text"),
        paragraph.get("translated_text"),
        source_text,
        translated_text,
    ):
        for ref in extract_note_refs(ensure_str(candidate).strip()):
            key = (str(ref.get("kind") or ""), str(ref.get("note_id") or ""))
            if key in seen_refs:
                continue
            seen_refs.add(key)
            ref_payload.append({"kind": key[0], "note_id": key[1]})
    return {
        "original": replace_frozen_refs(source_text),
        "translation": body_text,
        "footnotes": "",
        "footnotes_translation": "",
        "heading_level": int(paragraph.get("heading_level", 0) or 0),
        "pages": display_label,
        "_startBP": int(page_no),
        "_endBP": int(page_no),
        "_printPageLabel": raw_label,
        "_status": "error" if translation_status in {"error", "retry_pending", "retrying", "manual_required"} else ("done" if translated_text else "pending"),
        "_error": paragraph_error,
        "_translation_source": "manual" if bool(paragraph.get("manual_resolved")) else ("model" if translated_text else "source"),
        "_machine_translation": body_text if translated_text else "",
        "_manual_translation": body_text if bool(paragraph.get("manual_resolved")) else "",
        "_cross_page": paragraph.get("cross_page"),
        "_section_path": list(paragraph.get("section_path") or []),
        "_fnm_refs": ref_payload,
        "_note_kind": "",
        "_note_marker": "",
        "_note_number": None,
        "_note_section_title": "",
        "_note_confidence": 0.0,
        "_translation_status": translation_status or ("done" if translated_text else "pending"),
        "_attempt_count": max(0, int(paragraph.get("attempt_count", 0) or 0)),
        "_manual_resolved": bool(paragraph.get("manual_resolved")),
    }


def rebuild_diagnostic_page_entries(
    doc_id: str,
    *,
    pages: list[dict] | None = None,
    repo: SQLiteRepository | None = None,
    only_pages: list[int] | None = None,
    force_overwrite_manual: bool = False,
) -> list[int]:
    del force_overwrite_manual
    entries = list_phase6_diagnostic_entries_for_doc(
        doc_id,
        pages=pages,
        repo=repo,
        visible_bps=only_pages,
    )
    return [int(entry.get("_pageBP")) for entry in entries if entry.get("_pageBP") is not None]



def build_unit_progress(doc_id: str, *, repo: SQLiteRepository | None = None, snapshot: dict | None = None) -> dict:
    repo = repo or SQLiteRepository()
    units = list_fnm_units_with_indices(doc_id, repo=repo)
    total_units = len(units)
    done_units = len([unit for unit in units if str(unit.get("status") or "") == "done"])
    error_unit_indices = [
        int(unit["unit_idx"])
        for unit in units
        if str(unit.get("status") or "") == "error"
    ]
    error_units = len(error_unit_indices)
    processed_units = done_units + error_units
    pending_units = max(0, total_units - processed_units)
    current_idx = None
    if isinstance(snapshot, dict):
        candidate = snapshot.get("current_bp")
        if candidate is not None:
            try:
                candidate = int(candidate)
            except (TypeError, ValueError):
                candidate = None
            if candidate and 1 <= candidate <= total_units:
                current_idx = candidate
    current_unit = units[current_idx - 1] if current_idx else None
    return {
        "total_units": total_units,
        "done_units": done_units,
        "error_units": error_units,
        "failed_unit_indices": error_unit_indices,
        "processed_units": processed_units,
        "pending_units": pending_units,
        "current_unit_idx": current_idx,
        "current_unit_id": current_unit.get("unit_id") if current_unit else None,
        "current_unit_kind": current_unit.get("kind") if current_unit else "",
        "current_unit_label": format_fnm_unit_label(current_unit) if current_unit else "",
        "current_unit_pages": format_fnm_unit_pages(current_unit) if current_unit else "",
        "unit_items": [
            {
                "unit_idx": int(unit["unit_idx"]),
                "unit_id": unit.get("unit_id"),
                "kind": unit.get("kind"),
                "label": format_fnm_unit_label(unit),
                "pages": format_fnm_unit_pages(unit),
                "status": str(unit.get("status") or "pending"),
                "error_msg": ensure_str(unit.get("error_msg", "")).strip(),
                "preview": replace_frozen_refs(
                    ensure_str(unit.get("translated_text") or unit.get("source_text") or "").strip()
                )[:120],
            }
            for unit in units
        ],
    }


# 兼容旧调用方，后续统一迁移到无 fnm_ 前缀 API。
prepare_fnm_page_translate_jobs = prepare_page_translate_jobs
build_fnm_retry_summary = build_retry_summary
rebuild_fnm_diagnostic_page_entries = rebuild_diagnostic_page_entries
build_fnm_unit_progress = build_unit_progress

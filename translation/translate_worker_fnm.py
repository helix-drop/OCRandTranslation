"""FNM 翻译 worker：按结构化 unit 顺序翻译，页级投影仅作诊断层。"""

from __future__ import annotations
import logging

from FNM_RE.page_translate import (
    apply_body_unit_entry_result,
    apply_body_unit_translations,
    build_fnm_body_unit_jobs,
    collect_fnm_unit_failed_locations,
    build_fnm_unit_progress,
    format_fnm_unit_label,
    format_fnm_unit_pages,
    list_fnm_units_with_indices,
    unit_page_numbers,
)
from persistence.sqlite_store import SQLiteRepository
from persistence.storage import format_print_page_display, resolve_page_print_label
from document.text_utils import ensure_str
from translation.translate_state import TASK_KIND_FNM, _build_translate_task_meta
from translation.translate_worker_common import run_translate_worker

logger = logging.getLogger(__name__)
_REAL_MODE_RETRY_LIMIT = 3


def _model_label(model_key: str, t_args: dict) -> str:
    return t_args.get("display_label") or t_args.get("model_id") or model_key


def _rebuild_fnm_diagnostic_page_entries(
    doc_id: str,
    *,
    pages: list[dict],
    repo: SQLiteRepository,
) -> list[int]:
    from FNM_RE import list_diagnostic_entries_for_doc

    del pages
    return [
        int(entry.get("_pageBP"))
        for entry in list_diagnostic_entries_for_doc(doc_id, repo=repo)
        if entry.get("_pageBP") is not None
    ]


def _page_lookup(pages: list[dict]) -> dict[int, dict]:
    return {
        int(page.get("bookPage")): page
        for page in (pages or [])
        if page.get("bookPage") is not None
    }


def _fresh_unit_segments(unit: dict) -> list[dict]:
    segments = []
    for segment in unit.get("page_segments") or []:
        payload = dict(segment)
        payload.pop("translated_parts", None)
        payload.pop("translated_text", None)
        segments.append(payload)
    return segments


def _reset_unit_for_rerun(repo: SQLiteRepository, doc_id: str, unit: dict) -> None:
    fields = {
        "translated_text": None,
        "status": "pending",
        "error_msg": "",
    }
    if str(unit.get("kind") or "") == "body":
        fields["page_segments"] = _fresh_unit_segments(unit)
    repo.update_fnm_translation_unit(doc_id, str(unit.get("unit_id") or ""), **fields)
    note_id = str(unit.get("note_id") or "").strip()
    if note_id:
        repo.update_fnm_note_translation(doc_id, note_id, "", status="pending")


def _find_resume_start_unit_idx(units: list[dict]) -> int | None:
    for unit in units:
        if str(unit.get("status") or "") == "error":
            return int(unit["unit_idx"])
    for unit in units:
        if str(unit.get("status") or "") != "done":
            return int(unit["unit_idx"])
    return None


def _explicit_start_unit_idx(snapshot: dict) -> int | None:
    candidate = snapshot.get("start_bp")
    if candidate is None:
        candidate = ((snapshot.get("task") or {}).get("start_unit_idx"))
    if candidate is None:
        return None
    try:
        return int(candidate)
    except (TypeError, ValueError):
        return None


def _unit_stream_context(unit: dict, pages: list[dict]) -> tuple[dict, list[dict]]:
    kind = str(unit.get("kind") or "")
    if kind == "body":
        return {"footnotes": ""}, build_fnm_body_unit_jobs(unit, pages)

    page_numbers = unit_page_numbers(unit)
    target_page = page_numbers[0] if page_numbers else int(unit.get("page_start") or 0)
    page = _page_lookup(pages).get(target_page)
    raw_label = resolve_page_print_label(page) or (str(target_page) if target_page > 0 else "")
    display_label = format_print_page_display(raw_label)
    para_jobs = [
        {
            "para_idx": 0,
            "para_total": 1,
            "source_idx": 0,
            "bp": target_page if target_page > 0 else int(unit.get("unit_idx") or 0),
            "heading_level": 0,
            "text": ensure_str(unit.get("source_text", "")).strip(),
            "cross_page": None,
            "start_bp": target_page,
            "end_bp": target_page,
            "print_page_label": raw_label,
            "print_page_display": display_label,
            "pages": display_label,
            "bboxes": [],
            "footnotes": "",
            "prev_context": "",
            "next_context": "",
            "section_path": [ensure_str(unit.get("section_title", "")).strip()] if ensure_str(unit.get("section_title", "")).strip() else [],
            "content_role": kind,
            "note_kind": kind,
            "note_marker": ensure_str(unit.get("original_marker", "")).strip(),
            "note_number": None,
            "note_section_title": ensure_str(unit.get("section_title", "")).strip(),
            "note_confidence": 0.0,
            "fnm_note_id": ensure_str(unit.get("note_id", "")).strip(),
        }
    ]
    return {"footnotes": ""}, para_jobs


def _unit_translated_paragraphs(diagnostic_entry: dict) -> list[str]:
    return [
        ensure_str(diagnostic_segment.get("translation", "")).strip()
        for diagnostic_segment in (diagnostic_entry.get("_page_entries") or [])
        if ensure_str(diagnostic_segment.get("translation", "")).strip()
    ]


def _find_unit_by_id(doc_id: str, unit_id: str, *, repo: SQLiteRepository) -> dict | None:
    for unit in repo.list_fnm_translation_units(doc_id):
        if str(unit.get("unit_id") or "").strip() == str(unit_id or "").strip():
            return dict(unit)
    return None


def _mark_unit_manual_required(unit: dict) -> dict:
    updated_segments = []
    for segment in unit.get("page_segments") or []:
        payload = dict(segment)
        paragraphs = []
        for paragraph in payload.get("paragraphs") or []:
            paragraph_payload = dict(paragraph)
            status = str(paragraph_payload.get("translation_status") or "").strip()
            if status in {"error", "retry_pending", "retrying"} and not bool(paragraph_payload.get("manual_resolved")):
                paragraph_payload["translation_status"] = "manual_required"
            paragraphs.append(paragraph_payload)
        payload["paragraphs"] = paragraphs
        updated_segments.append(payload)
    unit_payload = dict(unit)
    unit_payload["page_segments"] = updated_segments
    return unit_payload


def _save_real_mode_failure_state(doc_id: str, deps: dict, repo: SQLiteRepository, *, retry_round: int | None = None) -> dict:
    snapshot = deps["load_translate_state"](doc_id)
    failed_locations: list[dict] = []
    manual_required_locations: list[dict] = []
    for unit in repo.list_fnm_translation_units(doc_id):
        if str(unit.get("kind") or "") != "body":
            continue
        unit_failed = collect_fnm_unit_failed_locations(unit)
        failed_locations.extend(unit_failed)
        manual_required_locations.extend(
            item for item in unit_failed if str(item.get("status") or "") == "manual_required"
        )
    deps["save_translate_state"](
        doc_id,
        running=bool(snapshot.get("running", True)),
        stop_requested=bool(snapshot.get("stop_requested", False)),
        phase=snapshot.get("phase", "running"),
        execution_mode="real",
        retry_round=int(snapshot.get("retry_round", 0) if retry_round is None else retry_round),
        unresolved_count=len(failed_locations),
        manual_required_count=len(manual_required_locations),
        next_failed_location=(manual_required_locations or failed_locations or [None])[0],
        failed_locations=failed_locations,
        manual_required_locations=manual_required_locations,
    )
    return {
        "failed_locations": failed_locations,
        "manual_required_locations": manual_required_locations,
    }


def _retry_real_mode_failed_units(doc_id: str, deps: dict, repo: SQLiteRepository, *, pages: list[dict]) -> None:
    model_key, t_args = deps["get_active_translate_args"]()
    glossary = deps["get_glossary"](doc_id)
    for retry_round in range(1, _REAL_MODE_RETRY_LIMIT + 1):
        retry_units = [
            dict(unit)
            for unit in repo.list_fnm_translation_units(doc_id)
            if str(unit.get("kind") or "") == "body"
            and collect_fnm_unit_failed_locations(unit)
        ]
        if not retry_units:
            _save_real_mode_failure_state(doc_id, deps, repo, retry_round=retry_round - 1)
            return
        for unit in retry_units:
            unit_id = ensure_str(unit.get("unit_id", "")).strip()
            ctx, para_jobs = _unit_stream_context(unit, pages)
            entry = deps["translate_page_stream"](
                pages,
                int(unit.get("unit_idx") or unit.get("page_start") or 0),
                model_key,
                t_args,
                glossary,
                doc_id=doc_id,
                stop_checker=lambda: deps["is_stop_requested"](doc_id),
                prepared_ctx=ctx,
                prepared_para_jobs=para_jobs,
                prepared_total_usage={
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "request_count": 0,
                },
                prepared_is_fnm=True,
            )
            latest_unit = _find_unit_by_id(doc_id, unit_id, repo=repo) or unit
            translated_payload = apply_body_unit_entry_result(
                latest_unit,
                entry,
                apply_only_unresolved=True,
            )
            failed_locations = translated_payload["failed_locations"]
            if retry_round >= _REAL_MODE_RETRY_LIMIT and failed_locations:
                manual_payload = _mark_unit_manual_required({
                    **latest_unit,
                    "page_segments": translated_payload["page_segments"],
                })
                translated_payload["page_segments"] = manual_payload["page_segments"]
                failed_locations = collect_fnm_unit_failed_locations({
                    **latest_unit,
                    "page_segments": translated_payload["page_segments"],
                })
            repo.update_fnm_translation_unit(
                unit_id,
                translated_text=translated_payload["translated_text"],
                status="done" if not failed_locations else "error",
                error_msg=failed_locations[0]["error"] if failed_locations else "",
                page_segments=translated_payload["page_segments"],
            )
        _rebuild_fnm_diagnostic_page_entries(doc_id, pages=pages, repo=repo)
        _save_real_mode_failure_state(doc_id, deps, repo, retry_round=retry_round)


def _seed_fnm_unit_draft(deps: dict, doc_id: str, unit: dict, repo: SQLiteRepository, *, status: str, note: str, unit_error: str = "") -> None:
    unit_progress = build_fnm_unit_progress(doc_id, repo=repo)
    deps["save_stream_draft"](
        doc_id,
        mode="fnm_unit",
        bp=int(unit.get("unit_idx") or 0),
        unit_idx=int(unit.get("unit_idx") or 0),
        unit_id=ensure_str(unit.get("unit_id", "")).strip(),
        unit_kind=ensure_str(unit.get("kind", "")).strip(),
        unit_label=format_fnm_unit_label(unit),
        unit_pages=format_fnm_unit_pages(unit),
        unit_error=ensure_str(unit_error).strip(),
        unit_items=list(unit_progress.get("unit_items") or []),
        status=status,
        note=note,
    )


def run_fnm_worker(doc_id: str, doc_title: str, deps: dict):
    repo = SQLiteRepository()

    def build_plan():
        if not doc_id or not deps["get_doc_meta"](doc_id):
            return {
                "start_error": {
                    "start_bp": 1,
                    "error_code": "doc_not_found",
                    "message": "文档不存在或已删除",
                }
            }

        fnm_run = repo.get_latest_fnm_run(doc_id) or {}
        if str(fnm_run.get("status") or "") != "done":
            return {
                "start_error": {
                    "start_bp": 1,
                    "error_code": "fnm_unavailable",
                    "message": "FNM 注释分类未完成或失败，请先完成 OCR 与 FNM 分类。",
                }
            }

        pages, _ = deps["load_pages_from_disk"](doc_id)
        model_key, t_args = deps["get_active_translate_args"]()
        if not pages:
            return {
                "start_error": {
                    "start_bp": 1,
                    "error_code": "no_pages",
                    "message": "未找到可翻译页面",
                }
            }

        units = list_fnm_units_with_indices(doc_id, repo=repo)
        if not units:
            return {
                "start_error": {
                    "start_bp": 1,
                    "error_code": "fnm_empty",
                    "message": "当前文档没有可翻译的 FNM unit。",
                }
            }

        explicit_start_idx = _explicit_start_unit_idx(deps["load_translate_state"](doc_id))
        execution_mode = str(deps["load_translate_state"](doc_id).get("execution_mode", "test") or "test").strip().lower() or "test"
        total_units = len(units)
        if explicit_start_idx is not None and not (1 <= explicit_start_idx <= total_units):
            return {
                "start_error": {
                    "start_bp": explicit_start_idx,
                    "error_code": "invalid_start_unit_idx",
                    "message": f"start_unit_idx 超出范围（1-{total_units}）",
                    "total_pages": total_units,
                    "model_label": _model_label(model_key, t_args),
                }
            }

        if explicit_start_idx is not None:
            rerun_units = [unit for unit in units if int(unit["unit_idx"]) >= explicit_start_idx]
            for unit in rerun_units:
                _reset_unit_for_rerun(repo, doc_id, unit)
            units = list_fnm_units_with_indices(doc_id, repo=repo)

        if not t_args.get("api_key"):
            start_idx = explicit_start_idx or _find_resume_start_unit_idx(units) or 1
            return {
                "start_error": {
                    "start_bp": start_idx,
                    "error_code": "no_api_key",
                    "message": "缺少翻译 API Key",
                    "total_pages": len(units),
                    "model_label": _model_label(model_key, t_args),
                }
            }

        auto_start_idx = explicit_start_idx or _find_resume_start_unit_idx(units)
        if auto_start_idx is None:
            target_units = []
            start_idx = 1 if units else None
        elif explicit_start_idx is not None:
            start_idx = explicit_start_idx
            target_units = [unit for unit in units if int(unit["unit_idx"]) >= start_idx]
        else:
            start_idx = auto_start_idx
            target_units = [
                unit for unit in units
                if int(unit["unit_idx"]) >= start_idx and str(unit.get("status") or "") != "done"
            ]

        done_units = len([unit for unit in units if str(unit.get("status") or "") == "done"])
        task_meta = _build_translate_task_meta(
            kind=TASK_KIND_FNM,
            label="FNM 翻译",
            start_bp=start_idx,
            progress_mode="unit",
            start_unit_idx=start_idx,
            start_segment_index=0,
            target_bps=[int(unit["unit_idx"]) for unit in target_units],
            target_unit_ids=[ensure_str(unit.get("unit_id", "")).strip() for unit in target_units],
        )
        return {
            "worker_plan": {
                "start_bp": start_idx,
                "target_bps": [int(unit["unit_idx"]) for unit in target_units],
                "total_pages": total_units,
                "initial_done_pages": done_units,
                "initial_processed_pages": done_units,
                "initial_partial_failed_bps": [],
                "initial_page_idx": start_idx - 1 if start_idx else done_units,
                "task_meta": task_meta,
                "model_label": _model_label(model_key, t_args),
                "model_source": t_args.get("model_source", "builtin"),
                "model_key": t_args.get("model_key", model_key),
                "model_id": t_args.get("model_id", ""),
                "provider": t_args.get("provider", ""),
                "execution_mode": execution_mode,
                "page_idx_by_bp": {int(unit["unit_idx"]): int(unit["unit_idx"]) for unit in units},
            },
            "context": {
                "pages": pages,
                "doc_title": doc_title,
                "execution_mode": execution_mode,
                "unit_by_idx": {
                    int(unit["unit_idx"]): dict(unit)
                    for unit in units
                },
            },
        }

    def run_page(*, doc_id: str, bp: int, **_kwargs):
        unit = dict((_kwargs["context"].get("unit_by_idx") or {}).get(int(bp)) or {})
        if not unit:
            raise RuntimeError(f"未找到 FNM unit #{bp}")

        unit_id = ensure_str(unit.get("unit_id", "")).strip()
        note_id = ensure_str(unit.get("note_id", "")).strip()
        pages = _kwargs["context"]["pages"]
        execution_mode = str(
            _kwargs["context"].get("execution_mode")
            or deps["load_translate_state"](doc_id).get("execution_mode", "test")
            or "test"
        ).strip().lower() or "test"
        model_key, t_args = deps["get_active_translate_args"]()
        glossary = deps["get_glossary"](doc_id)

        repo.update_fnm_translation_unit(doc_id, unit_id, status="running", error_msg="")
        if note_id:
            repo.update_fnm_note_translation(doc_id, note_id, "", status="running")
        _seed_fnm_unit_draft(
            deps,
            doc_id,
            unit,
            repo,
            status="streaming",
            note="当前 unit 尚未提交到硬盘；如请求停止，将从该 unit 重新开始。",
        )
        ctx, para_jobs = _unit_stream_context(unit, pages)
        try:
            entry = deps["translate_page_stream"](
                pages,
                bp,
                model_key,
                t_args,
                glossary,
                doc_id=doc_id,
                stop_checker=lambda: deps["is_stop_requested"](doc_id),
                prepared_ctx=ctx,
                prepared_para_jobs=para_jobs,
                prepared_total_usage={
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "request_count": 0,
                },
                prepared_is_fnm=True,
            )
        except Exception:
            logger.exception("FNM unit 翻译失败 doc_id=%s unit_id=%s", doc_id, unit_id)
            if deps["runtime_stop_requested"](doc_id):
                repo.update_fnm_translation_unit(doc_id, unit_id, status="pending", error_msg="")
                if note_id:
                    repo.update_fnm_note_translation(doc_id, note_id, "", status="pending")
            raise

        kind = str(unit.get("kind") or "")
        translated_parts = _unit_translated_paragraphs(entry)
        if kind == "body":
            if execution_mode == "real":
                translated_payload = apply_body_unit_entry_result(unit, entry)
                failed_locations = translated_payload["failed_locations"]
                unit_status = "done" if not failed_locations else "error"
                unit_error = failed_locations[0]["error"] if failed_locations else ""
            else:
                translated_payload = apply_body_unit_translations(unit, translated_parts)
                failed_locations = []
                unit_status = "done"
                unit_error = ""
            repo.update_fnm_translation_unit(
                doc_id,
                unit_id,
                translated_text=translated_payload["translated_text"],
                status=unit_status,
                error_msg=unit_error,
                page_segments=translated_payload["page_segments"],
            )
            changed_pages = unit_page_numbers(unit)
            if execution_mode == "real":
                _save_real_mode_failure_state(doc_id, deps, repo)
            char_count = len(translated_payload["translated_text"])
        else:
            translated_text = translated_parts[0] if translated_parts else ""
            diagnostic_error = ensure_str(((entry.get("_page_entries") or [{}])[0]).get("_error", "")).strip()
            diagnostic_status = (
                str(((entry.get("_page_entries") or [{}])[0]).get("_status") or "done").strip().lower()
                or "done"
            )
            unit_status = "done"
            if execution_mode == "real" and (diagnostic_status != "done" or not translated_text):
                unit_status = "error"
            repo.update_fnm_translation_unit(
                doc_id,
                unit_id,
                translated_text=translated_text,
                status=unit_status,
                error_msg=diagnostic_error if unit_status == "error" else "",
            )
            if note_id:
                repo.update_fnm_note_translation(doc_id, note_id, translated_text, status=unit_status)
            changed_pages = []
            char_count = len(translated_text)
            failed_locations = []
            if execution_mode == "real" and unit_status == "error":
                failed_locations = [{"error": page_error or "翻译失败"}]

        _seed_fnm_unit_draft(
            deps,
            doc_id,
            unit,
            repo,
            status="streaming",
            note="当前 unit 已提交，准备继续后续 unit。",
        )
        return {
            "entry": entry,
            "entry_idx": changed_pages[0] if changed_pages else None,
            "affected_bps": changed_pages,
            "para_count": len(para_jobs),
            "char_count": char_count,
            "usage": entry.get("_usage", {}),
            "partial_failed": bool(execution_mode == "real" and failed_locations),
            "model_key": model_key,
        }

    def handle_page_exception(exc: Exception, *, doc_id: str, bp: int, **_kwargs):
        unit = dict((_kwargs["context"].get("unit_by_idx") or {}).get(int(bp)) or {})
        unit_id = ensure_str(unit.get("unit_id", "")).strip()
        note_id = ensure_str(unit.get("note_id", "")).strip()
        error_text = str(exc)
        if unit_id:
            repo.update_fnm_translation_unit(doc_id, unit_id, status="error", error_msg=error_text)
        if note_id:
            repo.update_fnm_note_translation(doc_id, note_id, "", status="error")
        _seed_fnm_unit_draft(
            deps,
            doc_id,
            unit,
            repo,
            status="error",
            note=f"{format_fnm_unit_label(unit)} 翻译失败，等待重试。",
            unit_error=error_text,
        )
        snapshot = deps["load_translate_state"](doc_id)
        draft = deps["default_stream_draft_state"]()
        draft.update(snapshot.get("draft") or {})
        return {
            "draft_error_patch": {
                "active": False,
                "mode": "fnm_unit",
                "bp": bp,
                "unit_idx": int(unit.get("unit_idx") or 0),
                "unit_id": unit_id,
                "unit_kind": ensure_str(unit.get("kind", "")).strip(),
                "unit_label": format_fnm_unit_label(unit) if unit else "",
                "unit_pages": format_fnm_unit_pages(unit) if unit else "",
                "unit_error": error_text,
                "unit_items": list(build_fnm_unit_progress(doc_id, repo=repo).get("unit_items") or []),
                "para_idx": draft.get("para_idx"),
                "para_total": draft.get("para_total", 0),
                "para_done": draft.get("para_done", 0),
                "paragraph_errors": draft.get("paragraph_errors", []),
                "paragraphs": draft.get("paragraphs", []),
                "status": "error",
                "note": f"{format_fnm_unit_label(unit)} 翻译失败，等待重试。",
                "last_error": error_text,
            },
            "model_key": getattr(exc, "_worker_model_key", _kwargs["worker_plan"].get("model_key", "")),
        }

    def after_target_loop(*, doc_id: str, context: dict, **_kwargs):
        execution_mode = str(context.get("execution_mode") or "test").strip().lower() or "test"
        if execution_mode != "real":
            _rebuild_fnm_diagnostic_page_entries(
                doc_id,
                pages=context.get("pages") or [],
                repo=repo,
            )
            return
        _retry_real_mode_failed_units(
            doc_id,
            deps,
            repo,
            pages=context.get("pages") or [],
        )
        _rebuild_fnm_diagnostic_page_entries(
            doc_id,
            pages=context.get("pages") or [],
            repo=repo,
        )

    return run_translate_worker(
        doc_id=doc_id,
        build_plan=build_plan,
        run_page=run_page,
        handle_page_exception=handle_page_exception,
        deps=deps,
        after_target_loop=after_target_loop,
    )

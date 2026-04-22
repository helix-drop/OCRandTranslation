"""翻译动作、状态查询与使用量相关的路由服务函数。"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from flask import Response, flash, jsonify, redirect, render_template, request, url_for

from FNM_RE import (
    annotate_review_note_links,
    build_doc_status as build_fnm_structure_status,
    build_unit_progress as build_fnm_unit_progress,
    build_retry_summary as build_fnm_retry_summary,
    collect_llm_suggestions,
    group_review_overrides,
    run_doc_pipeline as run_fnm_pipeline,
    run_llm_repair,
)
from web.services import TranslationServices


Deps = TranslationServices

_fnm_continue_docs: set[str] = set()
_fnm_continue_lock = threading.Lock()
_fnm_fullflow_docs: set[str] = set()
_fnm_fullflow_lock = threading.Lock()


def _request_doc_id(deps: Deps) -> str:
    return deps["_request_doc_id"]()


def _is_fnm_continue_running(doc_id: str) -> bool:
    with _fnm_continue_lock:
        return str(doc_id or "") in _fnm_continue_docs


def _set_fnm_continue_running(doc_id: str, running: bool) -> None:
    normalized = str(doc_id or "").strip()
    if not normalized:
        return
    with _fnm_continue_lock:
        if running:
            _fnm_continue_docs.add(normalized)
        else:
            _fnm_continue_docs.discard(normalized)


def _is_fnm_fullflow_running(doc_id: str) -> bool:
    with _fnm_fullflow_lock:
        return str(doc_id or "") in _fnm_fullflow_docs


def _set_fnm_fullflow_running(doc_id: str, running: bool) -> None:
    normalized = str(doc_id or "").strip()
    if not normalized:
        return
    with _fnm_fullflow_lock:
        if running:
            _fnm_fullflow_docs.add(normalized)
        else:
            _fnm_fullflow_docs.discard(normalized)


def _normalize_reason_counts(raw_counts: Any) -> dict[str, int]:
    if not isinstance(raw_counts, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, value in raw_counts.items():
        reason = str(key or "").strip()
        if not reason:
            continue
        try:
            count = int(value or 0)
        except Exception:
            continue
        if count <= 0:
            continue
        normalized[reason] = int(normalized.get(reason, 0) or 0) + count
    return normalized


def _build_module_reason_counts(structure_status: dict[str, Any]) -> dict[str, int]:
    review_counts = _normalize_reason_counts(structure_status.get("review_counts"))
    blocking_reasons = [
        str(item).strip()
        for item in list(structure_status.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    for reason in blocking_reasons:
        if reason not in review_counts:
            review_counts[reason] = 1
    if bool(structure_status.get("manual_toc_required")) and not (
        "toc_manual_toc_required" in review_counts
        or "manual_toc_required" in review_counts
    ):
        review_counts["toc_manual_toc_required"] = 1
    return review_counts


def _to_reason_count_items(review_counts: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {"reason": reason, "count": int(count)}
        for reason, count in sorted(review_counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
    ]


def _cached_fnm_structure_status(fnm_run: dict[str, Any], validation: dict[str, Any] | None) -> dict[str, Any]:
    summary = dict((validation or {}).get("summary") or {})
    return {
        "structure_state": str(fnm_run.get("structure_state") or "unknown"),
        "review_counts": dict(fnm_run.get("review_counts") or {}),
        "blocking_reasons": list(fnm_run.get("blocking_reasons") or []),
        "link_summary": dict(fnm_run.get("link_summary") or {}),
        "page_partition_summary": dict(fnm_run.get("page_partition_summary") or {}),
        "chapter_mode_summary": dict(fnm_run.get("chapter_mode_summary") or {}),
        "heading_review_summary": dict(summary.get("heading_review_summary") or {}),
        "chapter_source_summary": dict(summary.get("chapter_source_summary") or {}),
        "visual_toc_conflict_count": int(summary.get("visual_toc_conflict_count") or 0),
        "toc_export_coverage_summary": dict((validation or {}).get("toc_export_coverage_summary") or {}),
        "toc_alignment_summary": dict(summary.get("toc_alignment_summary") or {}),
        "toc_semantic_summary": dict(summary.get("toc_semantic_summary") or {}),
        "toc_role_summary": dict(summary.get("toc_role_summary") or {}),
        "container_titles": list(summary.get("container_titles") or []),
        "post_body_titles": list(summary.get("post_body_titles") or []),
        "back_matter_titles": list(summary.get("back_matter_titles") or []),
        "toc_semantic_contract_ok": bool(summary.get("toc_semantic_contract_ok", True)),
        "toc_semantic_blocking_reasons": list(summary.get("toc_semantic_blocking_reasons") or []),
        "chapter_title_alignment_ok": bool(summary.get("chapter_title_alignment_ok", True)),
        "chapter_section_alignment_ok": bool(summary.get("chapter_section_alignment_ok", True)),
        "chapter_endnote_region_alignment_ok": bool(summary.get("chapter_endnote_region_alignment_ok", True)),
        "chapter_endnote_region_alignment_summary": dict(summary.get("chapter_endnote_region_alignment_summary") or {}),
        "export_drift_summary": dict(summary.get("export_drift_summary") or {}),
        "chapter_local_endnote_contract_ok": bool(summary.get("chapter_local_endnote_contract_ok", True)),
        "export_semantic_contract_ok": bool(summary.get("export_semantic_contract_ok", True)),
        "front_matter_leak_detected": bool(summary.get("front_matter_leak_detected", False)),
        "toc_residue_detected": bool(summary.get("toc_residue_detected", False)),
        "mid_paragraph_heading_detected": bool(summary.get("mid_paragraph_heading_detected", False)),
        "duplicate_paragraph_detected": bool(summary.get("duplicate_paragraph_detected", False)),
        "manual_toc_required": bool((validation or {}).get("manual_toc_required")),
        "manual_toc_ready": bool((validation or {}).get("manual_toc_ready")),
        "manual_toc_summary": dict((validation or {}).get("manual_toc_summary") or {}),
        "chapter_progress_summary": dict(summary.get("chapter_progress_summary") or {}),
        "note_region_progress_summary": dict(summary.get("note_region_progress_summary") or {}),
        "chapter_count": int(fnm_run.get("section_count", 0) or 0),
        "section_head_count": 0,
        "export_ready_test": bool(summary.get("export_audit_summary", {}).get("can_ship", False)),
        "export_ready_real": bool(summary.get("export_audit_summary", {}).get("can_ship", False)),
    }


def _fnm_run_phase_label(*, run_status: str, translate_running: bool, can_translate: bool, export_ready_real: bool) -> str:
    status = str(run_status or "idle").strip().lower() or "idle"
    if translate_running:
        return "翻译进行中"
    if status in {"error", "failed"}:
        return "处理失败"
    if status == "running":
        return "解析进行中"
    if status == "done" and can_translate:
        return "可开始翻译"
    if status == "done" and export_ready_real:
        return "可导出"
    if status == "done":
        return "等待结构通过"
    return "等待开始"


def _resolve_fnm_workflow_state(
    *,
    run_status: str,
    full_flow_running: bool,
    continue_running: bool,
    translate_running: bool,
    can_translate: bool,
    export_ready_real: bool,
) -> tuple[str, str]:
    status = str(run_status or "idle").strip().lower() or "idle"
    if full_flow_running:
        return "full_flow_running", "一体化流程处理中"
    if continue_running:
        return "continuing", "继续处理中"
    if translate_running:
        return "translating", "翻译进行中"
    if status in {"error", "failed"}:
        return "failed", "处理失败"
    if status == "running":
        return "processing", "解析进行中"
    if status == "done" and can_translate:
        return "ready_translate", "可开始翻译"
    if status == "done" and export_ready_real:
        return "ready_export", "可导出"
    if status == "done":
        return "blocked", "等待结构通过"
    return "idle", "等待开始"


def _build_fnm_gate_summary(
    *,
    run_status: str,
    manual_toc_required: bool,
    structure_state: str,
    can_translate: bool,
    export_ready_real: bool,
    toc_semantic_contract_ok: bool,
    chapter_title_alignment_ok: bool,
    chapter_section_alignment_ok: bool,
    chapter_endnote_region_alignment_ok: bool,
    chapter_local_endnote_contract_ok: bool,
    export_semantic_contract_ok: bool,
    front_matter_leak_detected: bool,
    toc_residue_detected: bool,
    mid_paragraph_heading_detected: bool,
    duplicate_paragraph_detected: bool,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [
        {
            "key": "fnm_run_done",
            "label": "FNM 解析完成",
            "ok": str(run_status or "").strip().lower() == "done",
        },
        {
            "key": "manual_toc_ready",
            "label": "手动目录就绪",
            "ok": not bool(manual_toc_required),
        },
        {
            "key": "structure_ready",
            "label": "结构审查通过",
            "ok": str(structure_state or "").strip().lower() == "ready",
        },
        {
            "key": "toc_semantic_contract",
            "label": "目录语义契约通过",
            "ok": bool(toc_semantic_contract_ok),
        },
        {
            "key": "chapter_boundary_contract",
            "label": "章节边界契约通过",
            "ok": bool(
                chapter_title_alignment_ok
                and chapter_section_alignment_ok
                and chapter_endnote_region_alignment_ok
                and chapter_local_endnote_contract_ok
            ),
        },
        {
            "key": "export_semantic_contract",
            "label": "导出语义契约通过",
            "ok": bool(export_semantic_contract_ok),
        },
        {
            "key": "no_front_matter_leak",
            "label": "未检测到前书区泄漏",
            "ok": not bool(front_matter_leak_detected),
        },
        {
            "key": "no_toc_residue",
            "label": "未检测到目录残留",
            "ok": not bool(toc_residue_detected),
        },
        {
            "key": "no_mid_heading_noise",
            "label": "未检测到段内标题噪声",
            "ok": not bool(mid_paragraph_heading_detected),
        },
        {
            "key": "no_duplicate_paragraph",
            "label": "未检测到重复段落",
            "ok": not bool(duplicate_paragraph_detected),
        },
        {
            "key": "can_translate",
            "label": "允许启动翻译",
            "ok": bool(can_translate),
        },
        {
            "key": "export_ready_real",
            "label": "允许导出章节包",
            "ok": bool(export_ready_real),
        },
    ]
    pass_count = sum(1 for item in checks if bool(item.get("ok")))
    fail_items = [item for item in checks if not bool(item.get("ok"))]
    total_count = len(checks)
    return {
        "gate_checks": checks,
        "gate_pass_count": int(pass_count),
        "gate_fail_count": int(len(fail_items)),
        "gate_total_count": int(total_count),
        "gate_pass_rate": float(pass_count / total_count) if total_count else 0.0,
        "gate_failed_labels": [str(item.get("label") or "") for item in fail_items if str(item.get("label") or "")],
    }


def _stop_active_task_if_needed(force_restart: bool, deps: Deps):
    active_running = deps["has_active_translate_task"]()
    if not active_running:
        return None
    if not force_restart:
        return jsonify({"status": "already_running"})
    stop_requested = deps["request_stop_active_translate"]()
    if not stop_requested:
        return jsonify({"status": "switch_timeout", "error": "failed_to_request_stop"})
    if not deps["wait_for_translate_idle"](timeout_s=4.0, poll_interval_s=0.05):
        return jsonify({"status": "switch_timeout"})
    return None


def _load_reading_snapshot(doc_id: str, deps: Deps) -> tuple[list[dict], dict, list[dict], dict]:
    pages, _ = deps["load_pages_from_disk"](doc_id)
    visible_page_view = deps["load_visible_page_view"](doc_id, pages=pages)
    entries, _, _ = deps["load_entries_from_disk"](doc_id, pages=pages)
    snapshot = deps["get_translate_snapshot"](
        doc_id,
        pages=pages,
        entries=entries,
        visible_page_view=visible_page_view,
    )
    return pages, visible_page_view, entries, snapshot


def _provider_api_key_missing_response(provider: str, deps: Deps, redirect_endpoint: str, **query):
    name = deps["_provider_api_key_label"](provider)
    flash(f"请先在设置中输入 {name}。", "error")
    return redirect(url_for(redirect_endpoint, **query))


def _reading_entry_redirect(doc_id: str, start_bp: int, deps: Deps):
    return redirect(url_for("reading", bp=start_bp, auto=1, start_bp=start_bp, doc_id=doc_id))


def start_from_beginning(deps: Deps):
    """从首页开始阅读。"""
    doc_id = _request_doc_id(deps)
    if doc_id:
        deps["set_current_doc"](doc_id)
    pages, _ = deps["load_pages_from_disk"](doc_id)
    if not pages:
        flash("请先上传文件。", "error")
        return redirect(url_for("home"))

    translate_args = deps["get_translate_args"]()
    if not translate_args["api_key"]:
        return _provider_api_key_missing_response(
            translate_args.get("provider", "deepseek"),
            deps,
            "home",
        )

    visible_page_view = deps["build_visible_page_view"](pages)
    first_page = visible_page_view["first_visible_page"] or deps["get_page_range"](pages)[0]
    return _reading_entry_redirect(doc_id, first_page, deps)


def start_reading(deps: Deps):
    doc_id = _request_doc_id(deps)
    if doc_id:
        deps["set_current_doc"](doc_id)
    pages, src_name = deps["load_pages_from_disk"](doc_id)
    if not pages:
        flash("请先上传文件。", "error")
        return redirect(url_for("home"))

    translate_args = deps["get_translate_args"]()
    if not translate_args["api_key"]:
        return _provider_api_key_missing_response(
            translate_args.get("provider", "deepseek"),
            deps,
            "input_page",
        )

    start_page = request.form.get("start_page", type=int)
    doc_title = request.form.get("doc_title", "").strip() or src_name or "Untitled"
    visible_page_view = deps["build_visible_page_view"](pages)
    first = visible_page_view["first_visible_page"] or deps["get_page_range"](pages)[0]
    last = visible_page_view["last_visible_page"] or deps["get_page_range"](pages)[1]
    valid_pages = {int(page.get("bookPage")) for page in pages if page.get("bookPage") is not None}

    if not start_page or start_page not in valid_pages:
        flash(f"请输入有效页码 ({first}-{last})", "error")
        return redirect(url_for("input_page", doc_id=doc_id))

    resolved_start_page = deps["resolve_visible_page_bp"](pages, start_page)
    if resolved_start_page is None:
        flash("未找到可阅读页面。", "error")
        return redirect(url_for("input_page", doc_id=doc_id))

    page_lookup = {
        int(page.get("bookPage")): page for page in pages if page.get("bookPage") is not None
    }
    if start_page != resolved_start_page and page_lookup.get(int(start_page), {}).get("isPlaceholder"):
        flash(f"PDF 第{start_page}页为空白页，已跳转到 PDF 第{resolved_start_page}页。", "info")
    start_page = resolved_start_page

    deps["save_entries_to_disk"]([], doc_title, 0, doc_id)
    return _reading_entry_redirect(doc_id, start_page, deps)


def fetch_next(deps: Deps):
    """翻译下一页。"""
    doc_id = _request_doc_id(deps)
    if doc_id:
        deps["set_current_doc"](doc_id)
    pages, _ = deps["load_pages_from_disk"](doc_id)
    entries, doc_title, _ = deps["load_entries_from_disk"](doc_id, pages=pages)
    translate_args = deps["get_translate_args"]()

    if not pages or not entries or not translate_args["api_key"]:
        flash("数据不完整或缺少API Key", "error")
        return redirect(url_for("reading", doc_id=doc_id))

    last_entry = entries[-1]
    last_page_bp = last_entry.get("_pageBP") or last_entry.get("_endBP", 1)
    next_bp = deps["get_next_page_bp"](pages, last_page_bp)

    if next_bp is None:
        flash("已到末尾", "info")
        return redirect(url_for("reading", bp=last_page_bp, doc_id=doc_id))

    try:
        entry = deps["translate_page"](
            pages,
            next_bp,
            deps["get_model_key"](),
            translate_args,
            deps["get_glossary"](doc_id),
        )
        deps["save_entry_to_disk"](entry, doc_title, doc_id)
        deps["reconcile_translate_state_after_page_success"](doc_id, next_bp)
        return redirect(url_for("reading", bp=next_bp, doc_id=doc_id))
    except Exception as exc:
        deps["logger"].exception("单页翻译失败 doc_id=%s bp=%s", doc_id, next_bp)
        deps["reconcile_translate_state_after_page_failure"](doc_id, next_bp, str(exc))
        flash(f"翻译失败: {exc}", "error")
        return redirect(url_for("reading", bp=last_page_bp, doc_id=doc_id))


def retranslate(bp: int, deps: Deps):
    """重新翻译整页。"""
    doc_id = _request_doc_id(deps)
    if doc_id:
        deps["set_current_doc"](doc_id)
    pages, _ = deps["load_pages_from_disk"](doc_id)
    entries, doc_title, _ = deps["load_entries_from_disk"](doc_id, pages=pages)

    target = request.values.get("target", "").strip()
    if target == "custom":
        model_key = deps["get_model_key"]()
        translate_args = deps["get_translate_args"]("custom")
    elif target.startswith("builtin:"):
        model_key = target.split(":", 1)[1].strip()
        if model_key not in deps["MODELS"]:
            flash("重译目标无效", "error")
            return redirect(url_for("reading", bp=bp, doc_id=doc_id))
        translate_args = deps["get_translate_args"](target)
    else:
        flash("重译目标无效", "error")
        return redirect(url_for("reading", bp=bp, doc_id=doc_id))

    target_idx = None
    for index, entry in enumerate(entries):
        if entry.get("_pageBP") == bp:
            target_idx = index
            break

    if target_idx is None or not translate_args["api_key"]:
        flash("数据不完整或缺少API Key", "error")
        return redirect(url_for("reading", doc_id=doc_id))

    try:
        new_entry = deps["translate_page"](
            pages,
            bp,
            model_key,
            translate_args,
            deps["get_glossary"](doc_id),
        )
        deps["save_entry_to_disk"](new_entry, doc_title, doc_id)
        deps["reconcile_translate_state_after_page_success"](doc_id, bp)
        flash(
            f"重译完成 ({translate_args.get('display_label') or translate_args.get('model_id') or model_key})",
            "success",
        )
    except Exception as exc:
        deps["logger"].exception("重译失败 doc_id=%s bp=%s", doc_id, bp)
        deps["reconcile_translate_state_after_page_failure"](doc_id, bp, str(exc))
        flash(f"重译失败: {exc}", "error")

    return redirect(url_for("reading", bp=bp, doc_id=doc_id))


def save_manual_original(deps: Deps):
    """保存当前页某段人工修订原文。"""
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    payload = request.get_json(silent=True) or {}
    bp = payload.get("bp")
    segment_index = payload.get("segment_index")
    original = payload.get("original")
    base_updated_at = payload.get("base_updated_at")
    if bp is None or segment_index is None:
        return jsonify({"ok": False, "error": "缺少页码或段落索引"}), 400
    if original is None:
        return jsonify({"ok": False, "error": "缺少修订原文"}), 400
    repo = deps["SQLiteRepository"]()
    try:
        segment = repo.save_manual_original_segment(
            doc_id=doc_id,
            book_page=int(bp),
            segment_index=int(segment_index),
            original=str(original),
            updated_by="local_user",
            base_updated_at=int(base_updated_at) if base_updated_at is not None else None,
        )
        return jsonify({"ok": True, "segment": segment})
    except RuntimeError as exc:
        server_segment = repo.get_translation_segment(doc_id, int(bp), int(segment_index))
        return jsonify({"ok": False, "error": str(exc), "server_segment": server_segment}), 409
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404


def save_manual_revision(deps: Deps):
    """保存当前页某段人工修订译文。"""
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    payload = request.get_json(silent=True) or {}
    bp = payload.get("bp")
    segment_index = payload.get("segment_index")
    translation = payload.get("translation")
    base_updated_at = payload.get("base_updated_at")
    if bp is None or segment_index is None:
        return jsonify({"ok": False, "error": "缺少页码或段落索引"}), 400
    if translation is None:
        return jsonify({"ok": False, "error": "缺少修订译文"}), 400
    repo = deps["SQLiteRepository"]()
    try:
        segment = repo.save_manual_translation_segment(
            doc_id=doc_id,
            book_page=int(bp),
            segment_index=int(segment_index),
            translation=str(translation),
            updated_by="local_user",
            base_updated_at=int(base_updated_at) if base_updated_at is not None else None,
        )
        return jsonify({"ok": True, "segment": segment})
    except RuntimeError as exc:
        server_segment = repo.get_translation_segment(doc_id, int(bp), int(segment_index))
        return jsonify({"ok": False, "error": str(exc), "server_segment": server_segment}), 409
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404


def segment_history(deps: Deps):
    """返回某个段落的历史版本列表。"""
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    try:
        bp = int(request.args.get("bp", 0))
        segment_index = int(request.args.get("segment_index", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "无效页码或段落索引"}), 400
    revisions = deps["SQLiteRepository"]().list_segment_revisions(doc_id, bp, segment_index)
    return jsonify({"ok": True, "revisions": revisions})


def check_retranslate_warnings(deps: Deps):
    """返回当前页人工修订段落数，用于重译前警告提示。"""
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    try:
        bp = int(request.args.get("bp", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "无效页码"}), 400
    count = deps["SQLiteRepository"]().count_manual_segments(doc_id, bp)
    return jsonify({"ok": True, "manual_count": count})


def translate_all_sse(deps: Deps):
    """SSE 端点：推送后台翻译进度。"""
    doc_id = _request_doc_id(deps)

    def generate():
        cursor = 0
        start_time = time.time()
        idle_count = 0
        while True:
            if time.time() - start_time > 600:
                yield "event: timeout\ndata: {}\n\n"
                return

            events, running = deps["get_translate_events"](cursor, doc_id)
            cursor += len(events)

            for evt_type, evt_data in events:
                yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False)}\n\n"
                if evt_type in ("all_done", "stopped", "error"):
                    return

            if not running and not events:
                idle_count += 1
                if idle_count >= 3:
                    yield "event: idle\ndata: {}\n\n"
                    return
            else:
                idle_count = 0

            time.sleep(0.5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def start_translate_all(deps: Deps):
    """启动后台连续翻译。"""
    doc_id = _request_doc_id(deps)
    force_restart = request.form.get("force_restart", "").strip() == "1"

    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"error": "doc_not_found", "message": "文档不存在或已删除"})

    switch_response = _stop_active_task_if_needed(force_restart, deps)
    if switch_response is not None:
        return switch_response

    pages, src_name = deps["load_pages_from_disk"](doc_id)
    if not pages:
        return jsonify({"error": "no_pages", "message": "未找到可翻译页面"})

    translate_args = deps["get_translate_args"]()
    if not translate_args["api_key"]:
        return jsonify({"error": "no_api_key", "message": "缺少翻译 API Key"})

    start_bp = request.form.get("start_bp", type=int)
    doc_title = request.form.get("doc_title", "").strip() or src_name or "Untitled"
    if start_bp is None:
        start_bp = deps["load_visible_page_view"](doc_id, pages=pages)["first_visible_page"] or deps["get_page_range"](pages)[0]
    else:
        start_bp = deps["resolve_visible_page_bp"](pages, start_bp) or start_bp

    entries, _, _ = deps["load_entries_from_disk"](doc_id, pages=pages)
    if not entries:
        deps["save_entries_to_disk"]([], doc_title, 0, doc_id)

    deps["set_current_doc"](doc_id)
    started = deps["start_translate_task"](doc_id, start_bp, doc_title)
    if not started:
        return jsonify({"status": "switch_timeout"})
    return jsonify({
        "status": "switching" if force_restart else "started",
        "start_bp": start_bp,
    })


def api_doc_fnm_translate(doc_id: str, deps: Deps):
    """启动后台 FNM 翻译。"""
    doc_id = deps["normalize_doc_id"](doc_id)
    request_payload = request.get_json(silent=True) or {}
    force_restart = (
        request.form.get("force_restart", "").strip() == "1"
        or str(request_payload.get("force_restart", "")).strip() == "1"
    )
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"error": "doc_not_found", "message": "文档不存在或已删除"}), 404

    switch_response = _stop_active_task_if_needed(force_restart, deps)
    if switch_response is not None:
        return switch_response

    repo = deps["SQLiteRepository"]()
    fnm_run = repo.get_latest_fnm_run(doc_id)
    units = repo.list_fnm_translation_units(doc_id)
    if not fnm_run or fnm_run.get("status") != "done":
        return jsonify({
            "error": "fnm_unavailable",
            "message": "FNM 注释分类尚未完成，暂时不能启动 FNM 翻译。",
        })
    if not units:
        return jsonify({
            "error": "fnm_empty",
            "message": "当前文档没有可翻译的 FNM unit。",
        })

    _pages, src_name = deps["load_pages_from_disk"](doc_id)
    doc_meta = deps["get_doc_meta"](doc_id) or {}
    doc_title = (
        request.form.get("doc_title", "").strip()
        or str(request_payload.get("doc_title", "")).strip()
        or src_name
        or doc_meta.get("name")
        or "Untitled"
    )
    start_unit_idx = request.form.get("start_unit_idx", type=int)
    execution_mode = str(
        request.form.get("execution_mode", "").strip()
        or request_payload.get("execution_mode", "")
        or "real"
    ).strip().lower() or "real"
    if execution_mode not in {"real", "test"}:
        return jsonify({"error": "invalid_execution_mode", "message": "execution_mode 只能是 real 或 test"}), 400
    structure_status = build_fnm_structure_status(doc_id, repo=repo)
    if execution_mode == "real" and bool(structure_status.get("manual_toc_required")):
        return jsonify({
            "error": "fnm_manual_toc_required",
            "message": "FNM 正式链路要求先上传手动目录（manual_pdf/manual_images）。",
            "structure_state": structure_status["structure_state"],
            "blocking_reasons": structure_status["blocking_reasons"],
            "manual_toc_required": True,
            "manual_toc_ready": bool(structure_status.get("manual_toc_ready")),
            "manual_toc_summary": structure_status.get("manual_toc_summary") or {},
        }), 409
    if execution_mode == "real" and structure_status["structure_state"] != "ready":
        return jsonify({
            "error": "fnm_structure_not_ready",
            "message": "FNM 结构尚未通过，真实翻译已阻塞；请先处理结构复核项。",
            "structure_state": structure_status["structure_state"],
            "blocking_reasons": structure_status["blocking_reasons"],
        }), 409
    translate_args = deps["get_translate_args"]()
    if execution_mode == "real" and not translate_args["api_key"]:
        return jsonify({"error": "no_api_key", "message": "缺少翻译 API Key"})
    deps["set_current_doc"](doc_id)
    started = deps["start_fnm_translate_task"](doc_id, doc_title, start_unit_idx, execution_mode)
    if not started:
        return jsonify({"status": "switch_timeout"})
    return jsonify({
        "status": "switching" if force_restart else "started",
        "unit_count": len(units),
        "start_unit_idx": start_unit_idx,
        "execution_mode": execution_mode,
    })


def api_doc_fnm_continue(doc_id: str, deps: Deps):
    doc_id = deps["normalize_doc_id"](doc_id)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    repo = deps["SQLiteRepository"]()
    run_status = str((repo.get_latest_fnm_run(doc_id) or {}).get("status") or "").strip().lower()
    if run_status == "running" or _is_fnm_continue_running(doc_id):
        return jsonify({"ok": True, "status": "already_running", "doc_id": doc_id})
    deps["set_current_doc"](doc_id)
    _set_fnm_continue_running(doc_id, True)

    def _runner():
        try:
            run_fnm_pipeline(doc_id)
        except Exception:
            deps["logger"].exception("继续 FNM 处理失败 doc_id=%s", doc_id)
        finally:
            _set_fnm_continue_running(doc_id, False)

    thread = threading.Thread(target=_runner, daemon=True, name=f"fnm-continue-{doc_id}")
    thread.start()
    return jsonify({"ok": True, "status": "started", "doc_id": doc_id})


def api_doc_fnm_full_flow(doc_id: str, deps: Deps):
    doc_id = deps["normalize_doc_id"](doc_id)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    if _is_fnm_fullflow_running(doc_id):
        return jsonify({"ok": True, "status": "already_running", "doc_id": doc_id})
    request_payload = request.get_json(silent=True) if request.is_json else {}
    force_restart = (
        request.form.get("force_restart", "").strip() == "1"
        or str(request_payload.get("force_restart", "")).strip() == "1"
    )
    switch_response = _stop_active_task_if_needed(force_restart, deps)
    if switch_response is not None:
        return switch_response

    _pages, src_name = deps["load_pages_from_disk"](doc_id)
    doc_meta = deps["get_doc_meta"](doc_id) or {}
    doc_title = (
        request.form.get("doc_title", "").strip()
        or str(request_payload.get("doc_title", "")).strip()
        or src_name
        or doc_meta.get("name")
        or "Untitled"
    )
    start_unit_idx = request.form.get("start_unit_idx", type=int)
    execution_mode = str(
        request.form.get("execution_mode", "").strip()
        or request_payload.get("execution_mode", "")
        or "real"
    ).strip().lower() or "real"
    if execution_mode not in {"real", "test"}:
        return jsonify({"ok": False, "error": "invalid_execution_mode", "message": "execution_mode 只能是 real 或 test"}), 400

    deps["set_current_doc"](doc_id)
    _set_fnm_fullflow_running(doc_id, True)

    def _runner():
        try:
            repo = deps["SQLiteRepository"]()
            fnm_run = repo.get_latest_fnm_run(doc_id) or {}
            run_status = str(fnm_run.get("status", "idle") or "idle").strip().lower()
            if run_status != "done":
                run_fnm_pipeline(doc_id)
                repo = deps["SQLiteRepository"]()
                fnm_run = repo.get_latest_fnm_run(doc_id) or {}
                run_status = str(fnm_run.get("status", "idle") or "idle").strip().lower()
            units = repo.list_fnm_translation_units(doc_id)
            if run_status != "done" or not units:
                return
            structure_status = build_fnm_structure_status(doc_id, repo=repo)
            if execution_mode == "real" and bool(structure_status.get("manual_toc_required")):
                return
            if execution_mode == "real" and str(structure_status.get("structure_state") or "") != "ready":
                return
            translate_args = deps["get_translate_args"]()
            if execution_mode == "real" and not translate_args["api_key"]:
                return
            deps["start_fnm_translate_task"](doc_id, doc_title, start_unit_idx, execution_mode)
        except Exception:
            deps["logger"].exception("FNM 一体化流程执行失败 doc_id=%s", doc_id)
        finally:
            _set_fnm_fullflow_running(doc_id, False)

    thread = threading.Thread(target=_runner, daemon=True, name=f"fnm-fullflow-{doc_id}")
    thread.start()
    return jsonify({"ok": True, "status": "started", "doc_id": doc_id})


def stop_translate(deps: Deps):
    """停止后台翻译。"""
    doc_id = _request_doc_id(deps)
    stopped = deps["request_stop_translate"](doc_id)
    return jsonify({"status": "stopping" if stopped else "not_running"})


def translate_status(deps: Deps):
    """查询翻译状态。"""
    doc_id = _request_doc_id(deps)
    pages, visible_page_view, entries, snapshot = _load_reading_snapshot(doc_id, deps)
    task_kind = str(((snapshot.get("task") or {}).get("kind") or "")).strip()
    snapshot = deps["enrich_translate_snapshot_for_reading_view"](
        snapshot=snapshot,
        doc_id=doc_id,
        entries=entries,
        visible_page_view=visible_page_view,
        view="fnm" if task_kind == "fnm" else "standard",
    )
    return jsonify(snapshot)


def api_reading_view_state(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    view = deps["_normalize_reading_view"](request.args.get("view", "standard"))
    pages, visible_page_view, disk_entries, snapshot = _load_reading_snapshot(doc_id, deps)
    state = deps["build_reading_view_state"](
        doc_id=doc_id,
        view=view,
        pages=pages,
        visible_page_view=visible_page_view,
        disk_entries=disk_entries,
        snapshot=snapshot,
    )
    return jsonify({"ok": True, "doc_id": doc_id, **state})


def api_doc_fnm_status(doc_id: str, deps: Deps):
    doc_id = deps["normalize_doc_id"](doc_id)
    doc_dir = deps["get_doc_dir"](doc_id) if doc_id else ""
    if not doc_id or not deps["get_doc_meta"](doc_id) or not (doc_dir and os.path.isdir(doc_dir)):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    repo = deps["SQLiteRepository"]()
    fnm_run = repo.get_latest_fnm_run(doc_id) or {}
    run_status = str(fnm_run.get("status", "idle") or "idle").strip().lower() or "idle"
    units = repo.list_fnm_translation_units(doc_id)
    pages, visible_page_view, disk_entries, snapshot = _load_reading_snapshot(doc_id, deps)
    validation = None
    validation_json = fnm_run.get("validation_json")
    if validation_json:
        try:
            validation = json.loads(validation_json)
        except Exception:
            validation = None
    if run_status == "done" and validation:
        structure_status = _cached_fnm_structure_status(fnm_run, validation)
    else:
        structure_status = build_fnm_structure_status(doc_id, repo=repo, snapshot=snapshot)
    snapshot.update(build_fnm_unit_progress(doc_id, snapshot=snapshot))
    snapshot.setdefault("translated_bps", [])
    snapshot.setdefault("failed_bps", [])
    snapshot.setdefault("partial_failed_bps", [])
    snapshot["reading_stats_done_pages"] = len(snapshot.get("translated_bps") or [])
    task = dict(snapshot.get("task") or {})
    is_fnm_task = task.get("kind") == "fnm"
    retry_summary = build_fnm_retry_summary(doc_id, snapshot=snapshot, repo=repo)
    export_ready_real = bool(structure_status["export_ready_real"] and not retry_summary["blocking_export"])
    review_counts = _build_module_reason_counts(structure_status)
    review_reason_counts = _to_reason_count_items(review_counts)
    structure_ready = structure_status["structure_state"] == "ready"
    full_flow_running = _is_fnm_fullflow_running(doc_id)
    continue_running = _is_fnm_continue_running(doc_id)
    translate_running = bool(is_fnm_task and snapshot.get("running"))
    can_translate = bool(
        fnm_run
        and run_status == "done"
        and units
        and not bool(structure_status.get("manual_toc_required"))
        and structure_ready
    )
    workflow_state, workflow_state_label = _resolve_fnm_workflow_state(
        run_status=run_status,
        full_flow_running=full_flow_running,
        continue_running=continue_running,
        translate_running=translate_running,
        can_translate=can_translate,
        export_ready_real=export_ready_real,
    )
    draft = snapshot.get("draft") if isinstance(snapshot.get("draft"), dict) else {}
    gate_summary = _build_fnm_gate_summary(
        run_status=run_status,
        manual_toc_required=bool(structure_status.get("manual_toc_required")),
        structure_state=str(structure_status["structure_state"]),
        can_translate=can_translate,
        export_ready_real=export_ready_real,
        toc_semantic_contract_ok=bool(structure_status.get("toc_semantic_contract_ok", True)),
        chapter_title_alignment_ok=bool(structure_status.get("chapter_title_alignment_ok", True)),
        chapter_section_alignment_ok=bool(structure_status.get("chapter_section_alignment_ok", True)),
        chapter_endnote_region_alignment_ok=bool(structure_status.get("chapter_endnote_region_alignment_ok", True)),
        chapter_local_endnote_contract_ok=bool(structure_status.get("chapter_local_endnote_contract_ok")),
        export_semantic_contract_ok=bool(structure_status.get("export_semantic_contract_ok", True)),
        front_matter_leak_detected=bool(structure_status.get("front_matter_leak_detected", False)),
        toc_residue_detected=bool(structure_status.get("toc_residue_detected", False)),
        mid_paragraph_heading_detected=bool(structure_status.get("mid_paragraph_heading_detected", False)),
        duplicate_paragraph_detected=bool(structure_status.get("duplicate_paragraph_detected", False)),
    )
    payload = {
        "ok": True,
        "doc_id": doc_id,
        "run": fnm_run,
        "run_status": run_status,
        "fnm_fullflow_running": full_flow_running,
        "fnm_continue_running": continue_running,
        "workflow_state": workflow_state,
        "workflow_state_label": workflow_state_label,
        "state_persisted": bool(run_status == "done" and not continue_running),
        "state_hint": "FNM 结果已存储在数据库中，重启应用不会自动重跑。"
        if run_status == "done" and not continue_running
        else "",
        "continue_fnm_available": bool(
            not translate_running
            and not full_flow_running
            and not continue_running
            and (run_status in {"idle", "error", "failed"} or (run_status == "done" and not can_translate))
        ),
        "full_flow_available": bool(
            not translate_running
            and not full_flow_running
            and not continue_running
            and run_status != "running"
        ),
        "resume_translate_available": bool(
            can_translate
            and not translate_running
            and (int(snapshot.get("processed_units", 0) or 0) > 0 or int(snapshot.get("done_units", 0) or 0) > 0)
        ),
        "run_updated_at": float(fnm_run.get("updated_at", 0) or 0),
        "run_phase_label": workflow_state_label if continue_running else _fnm_run_phase_label(
            run_status=run_status,
            translate_running=translate_running,
            can_translate=can_translate,
            export_ready_real=export_ready_real,
        ),
        "view_available": False,
        "can_translate": can_translate,
        "has_diagnostic_entries": bool(snapshot.get("translated_bps")),
        "note_count": int(fnm_run.get("note_count", 0) or 0),
        "unit_count": int(fnm_run.get("unit_count", len(units)) or 0),
        "structure_state": structure_status["structure_state"],
        "review_counts": review_counts,
        "review_reason_counts": review_reason_counts,
        "blocking_reasons": structure_status["blocking_reasons"],
        "manual_toc_required": bool(structure_status.get("manual_toc_required")),
        "manual_toc_ready": bool(structure_status.get("manual_toc_ready")),
        "manual_toc_summary": structure_status.get("manual_toc_summary") or {},
        "chapter_progress_summary": structure_status.get("chapter_progress_summary") or {},
        "note_region_progress_summary": structure_status.get("note_region_progress_summary") or {},
        "link_summary": structure_status["link_summary"],
        "chapter_count": structure_status["chapter_count"],
        "section_head_count": structure_status["section_head_count"],
        "page_partition_summary": structure_status["page_partition_summary"],
        "chapter_mode_summary": structure_status["chapter_mode_summary"],
        "heading_review_summary": structure_status["heading_review_summary"],
        "chapter_source_summary": structure_status.get("chapter_source_summary") or {},
        "visual_toc_conflict_count": int(structure_status.get("visual_toc_conflict_count") or 0),
        "toc_export_coverage_summary": structure_status.get("toc_export_coverage_summary") or {},
        "toc_alignment_summary": structure_status.get("toc_alignment_summary") or {},
        "toc_semantic_summary": structure_status.get("toc_semantic_summary") or {},
        "toc_role_summary": structure_status.get("toc_role_summary") or {},
        "container_titles": list(structure_status.get("container_titles") or []),
        "post_body_titles": list(structure_status.get("post_body_titles") or []),
        "back_matter_titles": list(structure_status.get("back_matter_titles") or []),
        "toc_semantic_contract_ok": bool(structure_status.get("toc_semantic_contract_ok", True)),
        "toc_semantic_blocking_reasons": list(structure_status.get("toc_semantic_blocking_reasons") or []),
        "chapter_title_alignment_ok": bool(structure_status.get("chapter_title_alignment_ok", True)),
        "chapter_section_alignment_ok": bool(structure_status.get("chapter_section_alignment_ok", True)),
        "chapter_endnote_region_alignment_ok": bool(structure_status.get("chapter_endnote_region_alignment_ok", True)),
        "chapter_endnote_region_alignment_summary": structure_status.get("chapter_endnote_region_alignment_summary") or {},
        "export_drift_summary": structure_status.get("export_drift_summary") or {},
        "chapter_local_endnote_contract_ok": bool(structure_status.get("chapter_local_endnote_contract_ok")),
        "export_semantic_contract_ok": bool(structure_status.get("export_semantic_contract_ok", True)),
        "front_matter_leak_detected": bool(structure_status.get("front_matter_leak_detected", False)),
        "toc_residue_detected": bool(structure_status.get("toc_residue_detected", False)),
        "mid_paragraph_heading_detected": bool(structure_status.get("mid_paragraph_heading_detected", False)),
        "duplicate_paragraph_detected": bool(structure_status.get("duplicate_paragraph_detected", False)),
        "export_ready_test": structure_status["export_ready_test"],
        "export_ready_real": export_ready_real,
        "total_units": int(snapshot.get("total_units", len(units)) or 0),
        "done_units": int(snapshot.get("done_units", 0) or 0),
        "processed_units": int(snapshot.get("processed_units", 0) or 0),
        "pending_units": int(snapshot.get("pending_units", 0) or 0),
        "current_unit_idx": snapshot.get("current_unit_idx"),
        "current_unit_id": snapshot.get("current_unit_id"),
        "current_unit_kind": snapshot.get("current_unit_kind", ""),
        "current_unit_label": snapshot.get("current_unit_label", ""),
        "current_unit_pages": snapshot.get("current_unit_pages", ""),
        "unit_items": list(snapshot.get("unit_items") or []),
        "translate_running": translate_running,
        "translate_snapshot": snapshot if is_fnm_task else None,
        "translate_phase": str(snapshot.get("phase") or "idle"),
        "translate_last_error": str(snapshot.get("last_error") or ""),
        "translate_task_kind": str(task.get("kind") or ""),
        "translate_task_label": str(task.get("label") or ""),
        "translate_log_relpath": str(task.get("log_relpath") or ""),
        "draft_active": bool(draft.get("active")),
        "draft_status": str(draft.get("status") or ""),
        "draft_note": str(draft.get("note") or ""),
        "draft_para_idx": draft.get("para_idx"),
        "draft_para_done": int(draft.get("para_done", 0) or 0),
        "draft_para_total": int(draft.get("para_total", 0) or 0),
        "draft_last_error": str(draft.get("last_error") or ""),
        "validation": validation,
        "execution_mode": retry_summary["execution_mode"],
        "blocking_export": bool(retry_summary["blocking_export"] or not structure_status["export_ready_real"]),
        "blocking_reason": retry_summary["blocking_reason"] or (structure_status["blocking_reasons"][0] if structure_status["blocking_reasons"] else ""),
        "retry_progress": retry_summary["retry_progress"],
        "next_failed_location": retry_summary["next_failed_location"],
        "failed_locations": retry_summary["failed_locations"],
        "manual_required_locations": retry_summary["manual_required_locations"],
        **gate_summary,
    }
    return jsonify(payload)


def api_doc_fnm_review(doc_id: str, deps: Deps):
    doc_id = deps["normalize_doc_id"](doc_id)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    repo = deps["SQLiteRepository"]()
    return jsonify(_build_fnm_review_payload(doc_id, deps, repo=repo))


def _build_fnm_review_payload(doc_id: str, deps: Deps, *, repo=None) -> dict[str, Any]:
    repo = repo or deps["SQLiteRepository"]()
    structure_status = build_fnm_structure_status(doc_id, repo=repo)
    review_counts = _build_module_reason_counts(structure_status)
    structure_status = {
        **structure_status,
        "review_counts": review_counts,
        "review_reason_counts": _to_reason_count_items(review_counts),
    }
    review_overrides = group_review_overrides(repo.list_fnm_review_overrides(doc_id))
    note_links = annotate_review_note_links(repo.list_fnm_note_links(doc_id), review_overrides)
    return {
        "ok": True,
        "doc_id": doc_id,
        **structure_status,
        "pages": repo.list_fnm_pages(doc_id),
        "chapters": repo.list_fnm_chapters(doc_id),
        "heading_candidates": repo.list_fnm_heading_candidates(doc_id),
        "section_heads": repo.list_fnm_section_heads(doc_id),
        "note_regions": repo.list_fnm_note_regions(doc_id),
        "chapter_note_modes": repo.list_fnm_chapter_note_modes(doc_id),
        "note_items": repo.list_fnm_note_items(doc_id),
        "body_anchors": repo.list_fnm_body_anchors(doc_id),
        "note_links": note_links,
        "structure_reviews": repo.list_fnm_structure_reviews(doc_id),
        "review_overrides": review_overrides,
        "llm_suggestions": collect_llm_suggestions(review_overrides),
    }


def _fnm_review_rebuild_response(doc_id: str, deps: Deps):
    result = run_fnm_pipeline(doc_id)
    if not result.get("ok"):
        return jsonify({"ok": False, "error": "fnm_rebuild_failed", "message": result.get("error") or "FNM 重建失败"}), 500
    payload = _build_fnm_review_payload(doc_id, deps)
    payload["rebuild"] = result
    return jsonify(payload)


def api_doc_fnm_review_page(doc_id: str, page_no: int, deps: Deps):
    doc_id = deps["normalize_doc_id"](doc_id)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    payload = request.get_json(silent=True) or {}
    update: dict[str, Any] = {}
    if "page_role" in payload:
        page_role = str(payload.get("page_role") or "").strip()
        if page_role:
            update["page_role"] = page_role
    if not update:
        return jsonify({"ok": False, "error": "invalid_payload", "message": "缺少可保存的页面字段"}), 400
    deps["SQLiteRepository"]().save_fnm_review_override(doc_id, "page", str(int(page_no)), update)
    return _fnm_review_rebuild_response(doc_id, deps)


def api_doc_fnm_review_chapter(doc_id: str, chapter_id: str, deps: Deps):
    doc_id = deps["normalize_doc_id"](doc_id)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    payload = request.get_json(silent=True) or {}
    update: dict[str, Any] = {}
    if "title" in payload:
        title = str(payload.get("title") or "").strip()
        if title:
            update["title"] = title
    if "start_page" in payload:
        update["start_page"] = int(payload.get("start_page") or 0)
    if "end_page" in payload:
        update["end_page"] = int(payload.get("end_page") or 0)
    if not update:
        return jsonify({"ok": False, "error": "invalid_payload", "message": "缺少可保存的章节字段"}), 400
    deps["SQLiteRepository"]().save_fnm_review_override(doc_id, "chapter", chapter_id, update)
    return _fnm_review_rebuild_response(doc_id, deps)


def api_doc_fnm_review_note_region(doc_id: str, region_id: str, deps: Deps):
    doc_id = deps["normalize_doc_id"](doc_id)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    payload = request.get_json(silent=True) or {}
    update: dict[str, Any] = {}
    if "bound_chapter_id" in payload:
        chapter_id = str(payload.get("bound_chapter_id") or "").strip()
        if chapter_id:
            update["bound_chapter_id"] = chapter_id
    if "region_kind" in payload:
        region_kind = str(payload.get("region_kind") or "").strip()
        if region_kind:
            update["region_kind"] = region_kind
    if "title_hint" in payload:
        title_hint = str(payload.get("title_hint") or "").strip()
        if title_hint:
            update["title_hint"] = title_hint
    if "start_page" in payload:
        update["start_page"] = int(payload.get("start_page") or 0)
    if "end_page" in payload:
        update["end_page"] = int(payload.get("end_page") or 0)
    if "disabled" in payload:
        update["disabled"] = bool(payload.get("disabled"))
    if not update:
        return jsonify({"ok": False, "error": "invalid_payload", "message": "缺少可保存的注释区字段"}), 400
    deps["SQLiteRepository"]().save_fnm_review_override(doc_id, "region", region_id, update)
    return _fnm_review_rebuild_response(doc_id, deps)


def api_doc_fnm_review_link(doc_id: str, link_id: str, deps: Deps):
    doc_id = deps["normalize_doc_id"](doc_id)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip().lower()
    repo = deps["SQLiteRepository"]()
    if action == "restore":
        repo.delete_fnm_review_override(doc_id, "link", link_id)
        return _fnm_review_rebuild_response(doc_id, deps)
    if action == "ignore":
        repo.save_fnm_review_override(doc_id, "link", link_id, {"action": "ignore"})
        return _fnm_review_rebuild_response(doc_id, deps)
    if action == "match":
        note_item_id = str(payload.get("note_item_id") or payload.get("definition_id") or "").strip()
        anchor_id = str(payload.get("anchor_id") or payload.get("ref_id") or "").strip()
        if not note_item_id or not anchor_id:
            return jsonify({"ok": False, "error": "invalid_payload", "message": "手动匹配需要 note_item_id 和 anchor_id"}), 400
        repo.save_fnm_review_override(
            doc_id,
            "link",
            link_id,
            {
                "action": "match",
                "note_item_id": note_item_id,
                "anchor_id": anchor_id,
            },
        )
        return _fnm_review_rebuild_response(doc_id, deps)
    return jsonify({"ok": False, "error": "invalid_action", "message": "link action 必须是 ignore、match 或 restore"}), 400


def api_doc_fnm_review_llm_repair(doc_id: str, deps: Deps):
    doc_id = deps["normalize_doc_id"](doc_id)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    payload = request.get_json(silent=True) or {}
    cluster_limit = max(1, int(payload.get("cluster_limit") or 1))
    auto_apply = bool(payload.get("auto_apply", True))
    repo = deps["SQLiteRepository"]()
    try:
        repair_result = run_llm_repair(
            doc_id,
            repo=repo,
            cluster_limit=cluster_limit,
            auto_apply=auto_apply,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": "fnm_llm_repair_failed", "message": str(exc)}), 500
    if int(repair_result.get("auto_applied_count") or 0) > 0:
        result = run_fnm_pipeline(doc_id)
        if not result.get("ok"):
            return jsonify({"ok": False, "error": "fnm_rebuild_failed", "message": result.get("error") or "FNM 重建失败"}), 500
    review_payload = _build_fnm_review_payload(doc_id, deps, repo=repo)
    review_payload["llm_repair"] = repair_result
    return jsonify(review_payload)


def fnm_review_page(deps: Deps):
    doc_id = _request_doc_id(deps)
    if doc_id:
        deps["set_current_doc"](doc_id)
    doc_id = deps["normalize_doc_id"](doc_id)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        flash("请先选择文档。", "error")
        return redirect(url_for("home"))
    repo = deps["SQLiteRepository"]()
    review_payload = _build_fnm_review_payload(doc_id, deps, repo=repo)
    return render_template(
        "reading/fnm_review.html",
        doc_id=doc_id,
        doc_meta=deps["get_doc_meta"](doc_id),
        structure_status={
            "structure_state": review_payload["structure_state"],
            "review_counts": review_payload["review_counts"],
            "review_reason_counts": review_payload.get("review_reason_counts") or [],
            "blocking_reasons": review_payload["blocking_reasons"],
            "link_summary": review_payload["link_summary"],
            "chapter_count": review_payload["chapter_count"],
            "section_head_count": review_payload["section_head_count"],
            "page_partition_summary": review_payload["page_partition_summary"],
            "chapter_mode_summary": review_payload["chapter_mode_summary"],
            "heading_review_summary": review_payload["heading_review_summary"],
        },
        pages=review_payload["pages"],
        chapters=review_payload["chapters"],
        section_heads=review_payload["section_heads"],
        heading_candidates=review_payload["heading_candidates"][:300],
        note_regions=review_payload["note_regions"],
        chapter_note_modes=review_payload["chapter_note_modes"],
        note_items=review_payload["note_items"][:200],
        body_anchors=review_payload["body_anchors"][:200],
        structure_reviews=review_payload["structure_reviews"],
        note_links=review_payload["note_links"][:200],
        review_links=[
            link
            for link in review_payload["note_links"][:200]
            if str(link.get("status") or "") in {"orphan_note", "orphan_anchor", "ambiguous"}
        ],
        llm_suggestions=review_payload["llm_suggestions"][:100],
    )


def translate_api_usage(deps: Deps):
    """翻译 API 使用情况入口，统一回到阅读页内仪表盘。"""
    doc_id = _request_doc_id(deps)
    if doc_id:
        deps["set_current_doc"](doc_id)
    state = deps["get_app_state"](doc_id)
    bp = request.args.get("bp", type=int)
    if bp is None:
        entries = state.get("entries", [])
        if entries:
            bp = entries[max(0, min(state["entry_idx"], len(entries) - 1))].get("_pageBP", state["first_page"])
        else:
            bp = state["first_page"]
    return redirect(url_for("reading", bp=bp, usage=1, auto=request.args.get("auto", "0"), doc_id=doc_id))


def translate_api_usage_data(deps: Deps):
    """翻译 API 使用情况数据接口。"""
    doc_id = _request_doc_id(deps)
    pages, visible_page_view, disk_entries, snapshot = _load_reading_snapshot(doc_id, deps)
    view = deps["_normalize_reading_view"](request.args.get("view", "standard"))
    entries = (
        deps["load_fnm_diagnostic_entries"](doc_id, pages=pages)
        if view == "fnm"
        else disk_entries
    )
    return jsonify(deps["_build_translate_usage_payload"](doc_id, entries=entries, snapshot=snapshot))


def register_translation_routes(app, deps: Deps) -> None:
    app.add_url_rule("/start_from_beginning", endpoint="start_from_beginning", view_func=lambda: start_from_beginning(deps), methods=["POST"])
    app.add_url_rule("/start_reading", endpoint="start_reading", view_func=lambda: start_reading(deps), methods=["POST"])
    app.add_url_rule("/fetch_next", endpoint="fetch_next", view_func=lambda: fetch_next(deps), methods=["POST"])
    app.add_url_rule("/retranslate/<int:bp>", endpoint="retranslate", view_func=lambda bp: retranslate(bp, deps), methods=["POST"])
    app.add_url_rule("/save_manual_original", endpoint="save_manual_original", view_func=lambda: save_manual_original(deps), methods=["POST"])
    app.add_url_rule("/save_manual_revision", endpoint="save_manual_revision", view_func=lambda: save_manual_revision(deps), methods=["POST"])
    app.add_url_rule("/segment_history", endpoint="segment_history", view_func=lambda: segment_history(deps))
    app.add_url_rule("/check_retranslate_warnings", endpoint="check_retranslate_warnings", view_func=lambda: check_retranslate_warnings(deps))
    app.add_url_rule("/translate_all_sse", endpoint="translate_all_sse", view_func=lambda: translate_all_sse(deps))
    app.add_url_rule("/start_translate_all", endpoint="start_translate_all", view_func=lambda: start_translate_all(deps), methods=["POST"])
    app.add_url_rule("/api/doc/<doc_id>/fnm/translate", endpoint="api_doc_fnm_translate", view_func=lambda doc_id: api_doc_fnm_translate(doc_id, deps), methods=["POST"])
    app.add_url_rule("/api/doc/<doc_id>/fnm/full-flow", endpoint="api_doc_fnm_full_flow", view_func=lambda doc_id: api_doc_fnm_full_flow(doc_id, deps), methods=["POST"])
    app.add_url_rule("/api/doc/<doc_id>/fnm/continue", endpoint="api_doc_fnm_continue", view_func=lambda doc_id: api_doc_fnm_continue(doc_id, deps), methods=["POST"])
    app.add_url_rule("/stop_translate", endpoint="stop_translate", view_func=lambda: stop_translate(deps), methods=["POST"])
    app.add_url_rule("/translate_status", endpoint="translate_status", view_func=lambda: translate_status(deps))
    app.add_url_rule("/api/reading_view_state", endpoint="api_reading_view_state", view_func=lambda: api_reading_view_state(deps))
    app.add_url_rule("/api/doc/<doc_id>/fnm/status", endpoint="api_doc_fnm_status", view_func=lambda doc_id: api_doc_fnm_status(doc_id, deps))
    app.add_url_rule("/api/doc/<doc_id>/fnm/review", endpoint="api_doc_fnm_review", view_func=lambda doc_id: api_doc_fnm_review(doc_id, deps))
    app.add_url_rule("/api/doc/<doc_id>/fnm/review/page/<int:page_no>", endpoint="api_doc_fnm_review_page", view_func=lambda doc_id, page_no: api_doc_fnm_review_page(doc_id, page_no, deps), methods=["POST"])
    app.add_url_rule("/api/doc/<doc_id>/fnm/review/chapter/<chapter_id>", endpoint="api_doc_fnm_review_chapter", view_func=lambda doc_id, chapter_id: api_doc_fnm_review_chapter(doc_id, chapter_id, deps), methods=["POST"])
    app.add_url_rule("/api/doc/<doc_id>/fnm/review/note-region/<region_id>", endpoint="api_doc_fnm_review_note_region", view_func=lambda doc_id, region_id: api_doc_fnm_review_note_region(doc_id, region_id, deps), methods=["POST"])
    app.add_url_rule("/api/doc/<doc_id>/fnm/review/link/<link_id>", endpoint="api_doc_fnm_review_link", view_func=lambda doc_id, link_id: api_doc_fnm_review_link(doc_id, link_id, deps), methods=["POST"])
    app.add_url_rule("/api/doc/<doc_id>/fnm/review/llm-repair", endpoint="api_doc_fnm_review_llm_repair", view_func=lambda doc_id: api_doc_fnm_review_llm_repair(doc_id, deps), methods=["POST"])
    app.add_url_rule("/fnm_review", endpoint="fnm_review_page", view_func=lambda: fnm_review_page(deps))
    app.add_url_rule("/translate_api_usage", endpoint="translate_api_usage", view_func=lambda: translate_api_usage(deps))
    app.add_url_rule("/translate_api_usage_data", endpoint="translate_api_usage_data", view_func=lambda: translate_api_usage_data(deps))

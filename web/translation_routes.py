"""翻译动作、状态查询与使用量相关的路由服务函数。"""

from __future__ import annotations

import json
import time
from typing import Any

from flask import Response, flash, jsonify, redirect, request, url_for

from persistence.task_logs import append_doc_task_log, create_doc_task_log
from web.services import TranslationServices


Deps = TranslationServices




def _request_doc_id(deps: Deps) -> str:
    return deps["_request_doc_id"]()

















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





def stop_translate(deps: Deps):
    """停止后台翻译。"""
    doc_id = _request_doc_id(deps)
    stopped = deps["request_stop_translate"](doc_id)
    return jsonify({"status": "stopping" if stopped else "not_running"})


def translate_status(deps: Deps):
    """查询翻译状态。"""
    doc_id = _request_doc_id(deps)
    pages, visible_page_view, entries, snapshot = _load_reading_snapshot(doc_id, deps)
    snapshot = deps["enrich_translate_snapshot_for_reading_view"](
        snapshot=snapshot,
        doc_id=doc_id,
        entries=entries,
        visible_page_view=visible_page_view,
        view="standard",
    )
    return jsonify(snapshot)


def api_reading_view_state(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"}), 404
    view = "standard"
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
    del pages, visible_page_view
    return jsonify(deps["_build_translate_usage_payload"](doc_id, entries=disk_entries, snapshot=snapshot))


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
    app.add_url_rule("/stop_translate", endpoint="stop_translate", view_func=lambda: stop_translate(deps), methods=["POST"])
    app.add_url_rule("/translate_status", endpoint="translate_status", view_func=lambda: translate_status(deps))
    app.add_url_rule("/api/reading_view_state", endpoint="api_reading_view_state", view_func=lambda: api_reading_view_state(deps))
    app.add_url_rule("/translate_api_usage", endpoint="translate_api_usage", view_func=lambda: translate_api_usage(deps))
    app.add_url_rule("/translate_api_usage_data", endpoint="translate_api_usage_data", view_func=lambda: translate_api_usage_data(deps))

"""设置、词典、模型切换与重置相关路由服务函数。"""

from __future__ import annotations

from typing import Any

from flask import flash, jsonify, redirect, render_template, request, url_for

from web.services import SettingsServices


Deps = SettingsServices


def _request_doc_id(deps: Deps) -> str:
    return deps["_request_doc_id"]()


def settings(deps: Deps):
    requested_doc_id = deps["normalize_doc_id"](request.args.get("doc_id", ""))
    current_doc_id = (
        requested_doc_id
        if requested_doc_id and deps["get_doc_meta"](requested_doc_id)
        else deps["get_current_doc_id"]()
    )
    if requested_doc_id and current_doc_id == requested_doc_id:
        deps["set_current_doc"](current_doc_id)
    state = deps["get_app_state"](current_doc_id)
    toc_source, toc_offset = deps["load_toc_source_offset"](current_doc_id)
    toc_items = deps["load_user_toc_from_disk"](current_doc_id) if toc_source == "user" else []
    toc_file = deps["get_toc_file_info"](current_doc_id)
    toc_file["uploaded_at_display"] = deps["_format_unix_ts"](toc_file.get("uploaded_at"))
    return render_template(
        "settings.html",
        current_doc_id=current_doc_id,
        toc_source=toc_source,
        toc_offset=toc_offset,
        toc_item_count=len(toc_items),
        toc_file=toc_file,
        **state,
    )


def save_settings(deps: Deps):
    section = request.form.get("section")
    current_doc_id = _request_doc_id(deps)
    if current_doc_id:
        deps["set_current_doc"](current_doc_id)
    secret_sections = {
        "paddle": ("paddle_token", deps["set_paddle_token"], "PaddleOCR 令牌已保存"),
        "deepseek": ("deepseek_key", deps["set_deepseek_key"], "DeepSeek API Key 已保存"),
        "dashscope": ("dashscope_key", deps["set_dashscope_key"], "DashScope API Key 已保存"),
        "mimo": ("mimo_api_key", deps["set_mimo_api_key"], "MiMo API Key 已保存"),
        "glm": ("glm_api_key", deps["set_glm_api_key"], "智谱 GLM API Key 已保存"),
        "kimi": ("kimi_api_key", deps["set_kimi_api_key"], "Kimi API Key 已保存"),
    }
    secret_section = secret_sections.get(section)
    if secret_section:
        deps["_save_text_setting"](*secret_section)
    elif section == "translate_parallel":
        deps["_save_translate_parallel_section"]()
    else:
        model_pool_redirect = deps["_save_model_pool_section"](section, current_doc_id)
        if model_pool_redirect is not None:
            return model_pool_redirect
    return deps["_redirect_settings"](current_doc_id)


def save_glossary(deps: Deps):
    doc_id = _request_doc_id(deps)
    if doc_id:
        deps["set_current_doc"](doc_id)
    glossary = []
    seen_terms = set()
    for key in request.form:
        if not key.startswith("term_"):
            continue
        n = key[5:]
        term = request.form.get(f"term_{n}", "").strip()
        defn = request.form.get(f"defn_{n}", "").strip()
        if not term or not defn:
            continue
        normalized = term.lower()
        if normalized in seen_terms:
            continue
        seen_terms.add(normalized)
        glossary.append([term, defn])
    deps["set_glossary"](glossary, doc_id=doc_id)
    flash(f"词典已保存 ({len(glossary)} 条)", "success")
    return redirect(url_for("settings", doc_id=doc_id) + "#glossary")


def api_glossary_list(deps: Deps):
    doc_id = _request_doc_id(deps)
    return jsonify({"items": deps["list_glossary_items"](doc_id=doc_id)})


def api_glossary_create(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    data = request.get_json(silent=True) or {}
    term = str(data.get("term", "")).strip()
    defn = str(data.get("defn", "")).strip()
    if not term or not defn:
        return jsonify({"ok": False, "error": "term/defn 不能为空"}), 400
    items, updated = deps["upsert_glossary_item"](term, defn, doc_id=doc_id)
    return jsonify({"ok": True, "updated": updated, "items": items})


def api_glossary_update(term: str, deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    data = request.get_json(silent=True) or {}
    defn = str(data.get("defn", "")).strip()
    if not defn:
        return jsonify({"ok": False, "error": "defn 不能为空"}), 400
    items, _updated = deps["upsert_glossary_item"](term, defn, doc_id=doc_id)
    return jsonify({"ok": True, "updated": True, "items": items})


def api_glossary_delete(term: str, deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    items, deleted = deps["delete_glossary_item"](term, doc_id=doc_id)
    if not deleted:
        return jsonify({"ok": False, "error": "term 不存在", "items": items}), 404
    return jsonify({"ok": True, "deleted": True, "items": items})


def api_glossary_import(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "未上传文件"}), 400
    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"ok": False, "error": "未上传文件"}), 400
    mode = request.form.get("mode", "append")
    try:
        new_items = deps["parse_glossary_file"](uploaded)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "error": "文件解析失败，请检查格式"}), 400
    if not new_items:
        return jsonify({"ok": False, "error": "文件中未找到有效术语行"}), 400

    if mode == "overwrite":
        deps["set_glossary"](new_items, doc_id=doc_id)
        items = deps["list_glossary_items"](doc_id=doc_id)
    else:
        for term, defn in new_items:
            deps["upsert_glossary_item"](term, defn, doc_id=doc_id)
        items = deps["list_glossary_items"](doc_id=doc_id)
    preview = deps["build_glossary_retranslate_preview"](doc_id)
    return jsonify({
        "ok": True,
        "imported": len(new_items),
        "total": len(items),
        "items": items,
        "retranslate_preview": deps["_serialize_glossary_retranslate_preview"](preview),
    })


def api_glossary_retranslate_preview(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    start_bp = request.args.get("start_bp", type=int)
    start_segment_index = request.args.get("start_segment_index", type=int)
    preview = deps["build_glossary_retranslate_preview"](
        doc_id,
        start_bp=start_bp,
        start_segment_index=start_segment_index,
    )
    return jsonify(deps["_serialize_glossary_retranslate_preview"](preview))


def start_glossary_retranslate(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id or not deps["get_doc_meta"](doc_id):
        return jsonify({"ok": False, "error": "doc_not_found", "message": "文档不存在或已删除"})
    if deps["has_active_translate_task"]():
        preview = deps["build_glossary_retranslate_preview"](
            doc_id,
            start_bp=request.form.get("start_bp", type=int),
            start_segment_index=request.form.get("start_segment_index", type=int),
        )
        payload = deps["_serialize_glossary_retranslate_preview"](preview)
        payload.update({
            "ok": False,
            "status": "already_running",
            "message": preview.get("reason") or "当前已有后台翻译任务正在运行。",
        })
        return jsonify(payload)

    if doc_id:
        deps["set_current_doc"](doc_id)
    pages, src_name = deps["load_pages_from_disk"](doc_id)
    entries, doc_title, _ = deps["load_entries_from_disk"](doc_id, pages=pages)
    preview = deps["build_glossary_retranslate_preview"](
        doc_id,
        start_bp=request.form.get("start_bp", type=int),
        start_segment_index=request.form.get("start_segment_index", type=int),
        pages=pages,
        entries=entries,
    )
    if not preview.get("can_start"):
        payload = deps["_serialize_glossary_retranslate_preview"](preview)
        payload.update({
            "ok": False,
            "status": "cannot_start",
            "message": preview.get("reason") or "当前无法启动词典补重译。",
        })
        return jsonify(payload)

    started, latest_preview = deps["start_glossary_retranslate_task"](
        doc_id,
        start_bp=preview.get("start_bp"),
        start_segment_index=preview.get("start_segment_index", 0),
        doc_title=request.form.get("doc_title", "").strip() or doc_title or src_name or "Untitled",
    )
    payload = deps["_serialize_glossary_retranslate_preview"](latest_preview)
    payload["ok"] = bool(started)
    payload["status"] = "started" if started else "cannot_start"
    payload["message"] = "" if started else (latest_preview.get("reason") or "当前无法启动词典补重译。")
    return jsonify(payload)


def reset_text(deps: Deps):
    doc_id = _request_doc_id(deps)
    if doc_id:
        deps["set_current_doc"](doc_id)
    deps["clear_entries_from_disk"](doc_id)
    return redirect(url_for("input_page", doc_id=doc_id))


def reset_text_action(deps: Deps):
    doc_id = _request_doc_id(deps)
    if doc_id:
        deps["set_current_doc"](doc_id)
    deps["clear_entries_from_disk"](doc_id)
    flash("翻译数据已清除", "success")
    return deps["_redirect_settings"](doc_id)


def reset_all(deps: Deps):
    requested_doc_id = deps["normalize_doc_id"](request.values.get("doc_id", ""))
    doc_id = requested_doc_id or deps["get_current_doc_id"]()
    if requested_doc_id and not deps["get_doc_meta"](requested_doc_id):
        flash("文档不存在", "error")
        return redirect(url_for("home"))
    blocked = deps["_guard_doc_delete"](doc_id)
    if blocked:
        return blocked
    if doc_id and not deps["_delete_doc_with_verification"](doc_id):
        flash("删除失败，请稍后重试", "error")
        return redirect(url_for("home", doc_id=doc_id))
    flash("当前文档已删除", "success")
    return redirect(url_for("home"))


def paddle_quota_status():
    official_url = "https://aistudio.baidu.com/paddleocr"
    return jsonify({
        "supported": False,
        "status": "unavailable",
        "official_url": official_url,
        "message": "官方站内可查看 OCR 配额状态；当前应用未接入公开额度查询接口。若当日额度用尽，OCR 阶段会返回 429 提示。",
    })


def register_settings_routes(app, deps: Deps) -> None:
    app.add_url_rule("/paddle_quota_status", endpoint="paddle_quota_status", view_func=paddle_quota_status)
    app.add_url_rule("/settings", endpoint="settings", view_func=lambda: settings(deps))
    app.add_url_rule("/save_settings", endpoint="save_settings", view_func=lambda: save_settings(deps), methods=["POST"])
    app.add_url_rule("/save_glossary", endpoint="save_glossary", view_func=lambda: save_glossary(deps), methods=["POST"])
    app.add_url_rule("/api/glossary", endpoint="api_glossary_list", view_func=lambda: api_glossary_list(deps), methods=["GET"])
    app.add_url_rule("/api/glossary", endpoint="api_glossary_create", view_func=lambda: api_glossary_create(deps), methods=["POST"])
    app.add_url_rule("/api/glossary/<path:term>", endpoint="api_glossary_update", view_func=lambda term: api_glossary_update(term, deps), methods=["PUT", "PATCH"])
    app.add_url_rule("/api/glossary/<path:term>", endpoint="api_glossary_delete", view_func=lambda term: api_glossary_delete(term, deps), methods=["DELETE"])
    app.add_url_rule("/api/glossary/import", endpoint="api_glossary_import", view_func=lambda: api_glossary_import(deps), methods=["POST"])
    app.add_url_rule("/api/glossary_retranslate_preview", endpoint="api_glossary_retranslate_preview", view_func=lambda: api_glossary_retranslate_preview(deps))
    app.add_url_rule("/start_glossary_retranslate", endpoint="start_glossary_retranslate", view_func=lambda: start_glossary_retranslate(deps), methods=["POST"])
    app.add_url_rule("/reset_text", endpoint="reset_text", view_func=lambda: reset_text(deps), methods=["POST"])
    app.add_url_rule("/reset_text_action", endpoint="reset_text_action", view_func=lambda: reset_text_action(deps), methods=["POST"])
    app.add_url_rule("/reset_all", endpoint="reset_all", view_func=lambda: reset_all(deps), methods=["POST"])

"""首页、文档管理、上传与重解析相关路由服务函数。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from typing import Any

from flask import Response, flash, jsonify, redirect, render_template, request, session, url_for

from web.services import DocumentServices


Deps = DocumentServices


def _request_doc_id(deps: Deps) -> str:
    return deps["_request_doc_id"]()


def _task_options_for_fnm_mode(fnm_mode: bool) -> dict:
    enabled = bool(fnm_mode)
    return {
        "clean_header_footer": enabled,
        "auto_visual_toc": enabled,
    }


def _save_upload_to_temp(file_storage) -> tuple[str, str]:
    original_name = os.path.basename(str(file_storage.filename or "").strip())
    ext = os.path.splitext(original_name)[1].lower()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    file_storage.save(tmp)
    tmp.close()
    return tmp.name, original_name


def _collect_manual_toc_uploads() -> tuple[str | None, dict, list[dict]]:
    toc_pdf = request.files.get("toc_pdf")
    toc_screenshots = [item for item in request.files.getlist("toc_screenshots") if item and item.filename]
    if toc_pdf and toc_pdf.filename and toc_screenshots:
        return "目录 PDF 和目录截图请二选一上传。", {}, []

    if toc_pdf and toc_pdf.filename:
        temp_path, original_name = _save_upload_to_temp(toc_pdf)
        return None, {"path": temp_path, "filename": original_name}, []

    uploads: list[dict] = []
    for file_storage in toc_screenshots:
        temp_path, original_name = _save_upload_to_temp(file_storage)
        uploads.append({"path": temp_path, "filename": original_name})
    return None, {}, uploads


_GLOSSARY_ALLOWED_EXTS = {".csv", ".xlsx", ".xls"}


def _collect_glossary_upload() -> tuple[str | None, dict]:
    glossary = request.files.get("glossary_file")
    if not glossary or not glossary.filename:
        return None, {}
    filename = os.path.basename(str(glossary.filename or "").strip())
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _GLOSSARY_ALLOWED_EXTS:
        return "词典文件仅支持 .csv / .xlsx 格式。", {}
    temp_path, original_name = _save_upload_to_temp(glossary)
    return None, {"path": temp_path, "filename": original_name}


def _current_doc_fnm_mode(deps: Deps, doc_id: str) -> bool:
    return bool(deps["get_doc_cleanup_headers_footers"](doc_id))


def _resolve_home_doc_id(deps: Deps, requested_doc_id: str, docs: list[dict[str, Any]]) -> str:
    candidates: list[str] = []
    if requested_doc_id:
        candidates.append(requested_doc_id)
    candidates.append(deps["get_current_doc_id"]())
    for row in docs:
        doc_id = deps["normalize_doc_id"]((row or {}).get("id", ""))
        if doc_id:
            candidates.append(doc_id)
    for candidate in candidates:
        normalized = deps["normalize_doc_id"](candidate)
        if normalized and deps["get_doc_meta"](normalized):
            return normalized
    return ""


def home(deps: Deps):
    requested_doc_id = deps["normalize_doc_id"](request.args.get("doc_id", ""))
    docs = deps["list_docs"]()
    current_doc_id = _resolve_home_doc_id(deps, requested_doc_id, docs)
    deps["request_stop_active_translate"]()
    state = deps["get_app_state"](current_doc_id)
    logs = session.pop("logs", [])
    return render_template("home.html", logs=logs, docs=docs, current_doc_id=current_doc_id, **state)


def switch_doc(doc_id: str, deps: Deps):
    deps["set_current_doc"](doc_id)
    return redirect(url_for("home"))


def delete_doc_route(doc_id: str, deps: Deps):
    blocked = deps["_guard_doc_delete"](doc_id)
    if blocked:
        return blocked
    if not deps["_delete_doc_with_verification"](doc_id):
        flash("删除失败，请稍后重试", "error")
        return redirect(url_for("home", doc_id=doc_id))
    flash("文档已删除", "success")
    return redirect(url_for("home"))


def delete_docs_batch(deps: Deps):
    raw_ids = request.form.getlist("doc_ids")
    seen: set[str] = set()
    doc_ids: list[str] = []
    for raw in raw_ids:
        did = deps["normalize_doc_id"](str(raw or ""))
        if not did or did in seen:
            continue
        seen.add(did)
        if deps["get_doc_meta"](did):
            doc_ids.append(did)
    if not doc_ids:
        flash("请至少选择一个有效文档", "error")
        return redirect(url_for("home"))
    blocked: list[str] = []
    deletable: list[str] = []
    for did in doc_ids:
        if deps["is_translate_running"](did):
            blocked.append(did)
        else:
            deletable.append(did)
    deleted = 0
    failed = 0
    for did in deletable:
        if deps["_delete_doc_with_verification"](did):
            deleted += 1
        else:
            failed += 1
    if deleted:
        flash(f"已删除 {deleted} 个文档", "success")
    if failed:
        flash(f"{failed} 个文档删除失败，请稍后重试", "error")
    if blocked:
        preview = ", ".join(blocked[:5])
        if len(blocked) > 5:
            preview += "…"
        flash(f"以下 {len(blocked)} 个文档正在翻译中，已跳过：{preview}", "error")
    return redirect(url_for("home"))


def input_page(deps: Deps):
    requested_doc_id = deps["normalize_doc_id"](request.args.get("doc_id", ""))
    current_doc_id = (
        requested_doc_id
        if requested_doc_id and deps["get_doc_meta"](requested_doc_id)
        else deps["get_current_doc_id"]()
    )
    state = deps["get_app_state"](current_doc_id)
    if not state["has_pages"]:
        flash("请先上传文件。", "error")
        return redirect(url_for("home"))
    return render_template("input.html", current_doc_id=current_doc_id, **state)


def upload_file(deps: Deps):
    paddle_token = deps["get_paddle_token"]()
    if not paddle_token:
        return jsonify({"error": "请先在设置中输入 PaddleOCR 令牌。"}), 200

    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "请选择文件。"}), 200

    upload_error, toc_pdf_upload, toc_image_uploads = _collect_manual_toc_uploads()
    if upload_error:
        return jsonify({"error": upload_error}), 200
    glossary_error, glossary_upload = _collect_glossary_upload()
    if glossary_error:
        return jsonify({"error": glossary_error}), 200

    file_name = uploaded.filename
    ext = os.path.splitext(file_name)[1].lower()
    if ext == ".pdf":
        file_type = 0
    elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
        file_type = 1
    else:
        return jsonify({"error": f"不支持的文件类型: {ext}"}), 200

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    uploaded.save(tmp)
    tmp.close()

    fnm_mode = deps["_parse_bool_flag"](request.form.get("fnm_mode", ""))
    manual_toc_enabled = bool(toc_pdf_upload or toc_image_uploads)
    deps["set_upload_processing_preferences"](
        cleanup_headers_footers=fnm_mode,
        auto_visual_toc=fnm_mode or manual_toc_enabled,
    )

    task_id = uuid.uuid4().hex[:12]
    task_options = _task_options_for_fnm_mode(fnm_mode)
    if manual_toc_enabled:
        task_options["auto_visual_toc"] = True
    if toc_pdf_upload:
        task_options["toc_visual_pdf_upload"] = toc_pdf_upload
    if toc_image_uploads:
        task_options["toc_visual_image_uploads"] = toc_image_uploads
    if glossary_upload:
        task_options["glossary_upload"] = glossary_upload
    deps["create_task"](
        task_id,
        tmp.name,
        file_name,
        file_type,
        options=task_options,
    )
    threading.Thread(target=deps["process_file"], args=(task_id,), daemon=True).start()
    return jsonify({"task_id": task_id})


def api_upload_preferences(deps: Deps):
    payload = request.get_json(silent=True) or request.form
    fnm_mode = deps["_parse_bool_flag"]((payload or {}).get("fnm_mode", ""))
    deps["set_upload_processing_preferences"](
        cleanup_headers_footers=fnm_mode,
        auto_visual_toc=fnm_mode,
    )
    return jsonify({
        "ok": True,
        "fnm_mode": fnm_mode,
    })


def reparse(deps: Deps):
    if not deps["get_paddle_token"]():
        return jsonify({"error": "请先在设置中输入 PaddleOCR 令牌。"}), 200

    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"error": "没有活跃文档。"}), 200
    deps["set_current_doc"](doc_id)

    pdf_path = deps["get_pdf_path"](doc_id)
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "未找到 PDF 文件，无法重新解析。"}), 200

    _pages, file_name = deps["load_pages_from_disk"](doc_id)
    task_id = uuid.uuid4().hex[:12]
    fnm_mode = _current_doc_fnm_mode(deps, doc_id)
    deps["create_task"](
        task_id,
        pdf_path,
        file_name or "source.pdf",
        0,
        options=_task_options_for_fnm_mode(fnm_mode),
    )
    threading.Thread(target=deps["reparse_file"], args=(task_id, doc_id), daemon=True).start()
    return jsonify({"task_id": task_id})


def api_doc_reparse_enhanced(deps: Deps):
    if not deps["get_paddle_token"]():
        return jsonify({"error": "请先在设置中输入 PaddleOCR 令牌。"}), 200

    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"error": "没有活跃文档。"}), 200
    deps["set_current_doc"](doc_id)

    pdf_path = deps["get_pdf_path"](doc_id)
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "未找到 PDF 文件，无法增强重解析。"}), 200

    _pages, file_name = deps["load_pages_from_disk"](doc_id)
    deps["clear_entries_from_disk"](doc_id)
    deps["update_doc_meta"](doc_id, cleanup_headers_footers=True, auto_visual_toc_enabled=True)
    task_id = uuid.uuid4().hex[:12]
    deps["create_task"](
        task_id,
        pdf_path,
        file_name or "source.pdf",
        0,
        options=_task_options_for_fnm_mode(True),
    )
    threading.Thread(target=deps["reparse_file"], args=(task_id, doc_id), daemon=True).start()
    return jsonify({"task_id": task_id, "cleared_translations": True})


def reparse_page(page_bp: int, deps: Deps):
    if not deps["get_paddle_token"]():
        return jsonify({"error": "请先在设置中输入 PaddleOCR 令牌。"}), 200

    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"error": "没有活跃文档。"}), 200
    deps["set_current_doc"](doc_id)

    pdf_path = deps["get_pdf_path"](doc_id)
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "未找到 PDF 文件，无法重新解析。"}), 200

    pages, file_name = deps["load_pages_from_disk"](doc_id)
    file_idx = None
    for page in pages:
        if page["bookPage"] == page_bp:
            file_idx = page["fileIdx"]
            break
    if file_idx is None:
        return jsonify({"error": f"未找到页码 {page_bp}"}), 200

    task_id = uuid.uuid4().hex[:12]
    fnm_mode = _current_doc_fnm_mode(deps, doc_id)
    deps["create_task"](
        task_id,
        pdf_path,
        file_name or "source.pdf",
        0,
        options=_task_options_for_fnm_mode(fnm_mode),
    )
    threading.Thread(
        target=deps["reparse_single_page"],
        args=(task_id, doc_id, page_bp, file_idx),
        daemon=True,
    ).start()
    return jsonify({"task_id": task_id})


def api_doc_run_visual_toc(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "没有活跃文档。"}), 400
    deps["set_current_doc"](doc_id)

    pdf_path = deps["get_pdf_path"](doc_id)
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"ok": False, "error": "未找到 PDF 文件，无法生成自动视觉目录。"}), 400

    deps["update_doc_meta"](
        doc_id,
        auto_visual_toc_enabled=True,
        toc_visual_status="running",
        toc_visual_phase="queued",
        toc_visual_progress_pct=1,
        toc_visual_progress_label="自动视觉目录准备中",
        toc_visual_progress_detail="后台任务已启动，正在准备目录识别…",
        toc_visual_message="后台任务已启动，正在准备目录识别…",
        toc_visual_model_id=deps["resolve_visual_model_spec"]().model_id,
    )
    deps["start_auto_visual_toc_for_doc"](
        doc_id,
        pdf_path,
        model_spec=deps["resolve_visual_model_spec"](),
    )
    return jsonify({"ok": True, "doc_id": doc_id})


def api_doc_upload_toc_visual_source(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "没有活跃文档。"}), 400
    deps["set_current_doc"](doc_id)
    pdf_path = deps["get_pdf_path"](doc_id)
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"ok": False, "error": "未找到源 PDF，无法绑定目录页。"}), 400

    upload_error, toc_pdf_upload, toc_image_uploads = _collect_manual_toc_uploads()
    if upload_error:
        return jsonify({"ok": False, "error": upload_error}), 400
    if not toc_pdf_upload and not toc_image_uploads:
        return jsonify({"ok": False, "error": "请上传目录 PDF 或截图。"}), 400

    saved_mode = ""
    saved_count = 0
    try:
        if toc_pdf_upload:
            deps["save_toc_visual_manual_pdf"](
                doc_id,
                toc_pdf_upload["path"],
                original_name=toc_pdf_upload["filename"],
            )
            saved_mode = "manual_pdf"
            saved_count = 1
        else:
            saved_paths = deps["save_toc_visual_manual_screenshots"](doc_id, toc_image_uploads)
            saved_mode = "manual_images"
            saved_count = len(saved_paths)
        manual_inputs = deps["load_toc_visual_manual_inputs"](doc_id)
        resolved_page_count = int((manual_inputs or {}).get("page_count") or 0)
        if resolved_page_count > 0:
            saved_count = resolved_page_count
        deps["update_doc_meta"](
            doc_id,
            auto_visual_toc_enabled=True,
            toc_visual_status="running",
            toc_visual_phase="queued",
            toc_visual_progress_pct=1,
            toc_visual_progress_label="手动目录准备中",
            toc_visual_progress_detail="手动目录文件已保存，正在准备视觉目录识别…",
            toc_visual_message="手动目录文件已保存，正在准备视觉目录识别…",
            toc_visual_model_id=deps["resolve_visual_model_spec"]().model_id,
        )
        deps["start_auto_visual_toc_for_doc"](
            doc_id,
            pdf_path,
            model_spec=deps["resolve_visual_model_spec"](),
        )
        return jsonify({"ok": True, "doc_id": doc_id, "input_mode": saved_mode, "page_count": saved_count})
    finally:
        for row in [toc_pdf_upload] + toc_image_uploads:
            path = str((row or {}).get("path") or "").strip()
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass


def process_sse(deps: Deps):
    task_id = request.args.get("task_id")
    if not task_id or not deps["get_task"](task_id):
        return Response("data: {}\n\n", mimetype="text/event-stream")

    def generate():
        cursor = 0
        while True:
            events, exists = deps["get_task_events"](task_id, cursor)
            if not exists:
                break
            cursor += len(events)

            for evt_type, evt_data in events:
                yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False)}\n\n"
                if evt_type in ("done", "error_msg"):
                    if evt_type == "done" and evt_data.get("logs"):
                        deps["set_task_final"](task_id, evt_data["logs"], evt_data.get("summary", ""))

                    def cleanup():
                        time.sleep(10)
                        deps["remove_task"](task_id)

                    threading.Thread(target=cleanup, daemon=True).start()
                    return
            time.sleep(0.3)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def register_document_routes(app, deps: Deps) -> None:
    app.add_url_rule("/", endpoint="home", view_func=lambda: home(deps))
    app.add_url_rule("/switch_doc/<doc_id>", endpoint="switch_doc", view_func=lambda doc_id: switch_doc(doc_id, deps), methods=["POST"])
    app.add_url_rule("/delete_doc/<doc_id>", endpoint="delete_doc_route", view_func=lambda doc_id: delete_doc_route(doc_id, deps), methods=["POST"])
    app.add_url_rule("/delete_docs_batch", endpoint="delete_docs_batch", view_func=lambda: delete_docs_batch(deps), methods=["POST"])
    app.add_url_rule("/input", endpoint="input_page", view_func=lambda: input_page(deps))
    app.add_url_rule("/upload_file", endpoint="upload_file", view_func=lambda: upload_file(deps), methods=["POST"])
    app.add_url_rule("/api/upload_preferences", endpoint="api_upload_preferences", view_func=lambda: api_upload_preferences(deps), methods=["POST"])
    app.add_url_rule("/reparse", endpoint="reparse", view_func=lambda: reparse(deps), methods=["POST"])
    app.add_url_rule("/api/doc/reparse_enhanced", endpoint="api_doc_reparse_enhanced", view_func=lambda: api_doc_reparse_enhanced(deps), methods=["POST"])
    app.add_url_rule("/reparse_page/<int:page_bp>", endpoint="reparse_page", view_func=lambda page_bp: reparse_page(page_bp, deps), methods=["POST"])
    app.add_url_rule("/api/doc/run_visual_toc", endpoint="api_doc_run_visual_toc", view_func=lambda: api_doc_run_visual_toc(deps), methods=["POST"])
    app.add_url_rule("/api/doc/upload_toc_visual_source", endpoint="api_doc_upload_toc_visual_source", view_func=lambda: api_doc_upload_toc_visual_source(deps), methods=["POST"])
    app.add_url_rule("/process_sse", endpoint="process_sse", view_func=lambda: process_sse(deps))

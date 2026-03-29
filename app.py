"""
外文文献阅读器 - Flask 版
Foreign Literature Reader

功能流程：
1. 上传 PDF/图片 → 调用 PaddleOCR API 解析版面
2. 解析 OCR 结果，清理页眉页脚
3. 构建段落，调用 DeepSeek/Qwen API 翻译
4. 阅读、导航、导出
"""
import json
import os
import re
import secrets
import uuid
import tempfile
import threading
import time

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, send_file, jsonify, Response,
)
from io import BytesIO

from config import (
    MODELS, ensure_dirs, check_write_permission,
    get_paddle_token, set_paddle_token,
    get_deepseek_key, set_deepseek_key,
    get_dashscope_key, set_dashscope_key,
    set_translate_parallel_settings,
    get_glossary, set_glossary,
    list_glossary_items, upsert_glossary_item, delete_glossary_item, parse_glossary_file,
    get_model_key, set_model_key,
    get_custom_model_name, get_custom_model_enabled, get_custom_model_base_key,
    set_custom_model_enabled, save_custom_model_selection,
    get_pdf_virtual_window_radius, get_pdf_virtual_scroll_min_pages,
    get_current_doc_id, set_current_doc,
    get_doc_meta, get_doc_dir,
    list_docs, update_doc_meta, delete_doc,
    LOCAL_DATA_DIR,
)
from text_processing import get_page_range, get_next_page_bp, normalize_latex_footnote_markers
from pdf_extract import render_pdf_page
from storage import (
    save_pages_to_disk, load_pages_from_disk,
    save_entries_to_disk, save_entry_to_disk, save_entry_cursor, load_entries_from_disk, clear_entries_from_disk,
    get_translate_args, highlight_terms, _ensure_str,
    gen_markdown, get_app_state, has_pdf, get_pdf_path, load_pdf_toc_from_disk,
)
from sqlite_store import SQLiteRepository
from tasks import (
    create_task, get_task, get_task_events, set_task_final,
    remove_task, process_file, reparse_file,
    translate_page,
    start_translate_task, has_active_translate_task,
    is_translate_running, is_stop_requested, get_translate_snapshot,
    request_stop_translate, get_translate_events,
    request_stop_active_translate, wait_for_translate_idle,
    reconcile_translate_state_after_page_success,
    reconcile_translate_state_after_page_failure,
)

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
CUSTOM_MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
JSON_CSRF_ENDPOINTS = {
    "api_glossary_create",
    "api_glossary_update",
    "api_glossary_delete",
    "upload_file",
    "reparse",
    "reparse_page",
    "save_manual_revision",
    "set_pref",
    "start_translate_all",
    "stop_translate",
}


def _ensure_csrf_token() -> str:
    token = session.get("_csrf_token", "").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": _ensure_csrf_token()}


def _should_return_json_for_csrf_failure() -> bool:
    if request.endpoint in JSON_CSRF_ENDPOINTS:
        return True
    if request.path.startswith("/api/"):
        return True
    return bool(request.is_json)


def _csrf_token_is_valid() -> bool:
    session_token = session.get("_csrf_token", "").strip()
    if not session_token:
        return False
    request_token = request.form.get("_csrf_token", "").strip()
    header_token = request.headers.get("X-CSRF-Token", "").strip()
    provided_token = request_token or header_token
    if not provided_token:
        return False
    return secrets.compare_digest(session_token, provided_token)


@app.before_request
def verify_csrf_for_unsafe_methods():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if request.endpoint is None:
        return None
    if _csrf_token_is_valid():
        return None
    message = "CSRF 校验失败"
    if _should_return_json_for_csrf_failure():
        return jsonify({"ok": False, "error": "csrf_failed", "message": message}), 403
    return Response(message, status=403, mimetype="text/plain")


def _strip_html_table(t: str) -> str:
    """将 HTML <table> 转为制表符分隔的纯文本行。"""
    cleaned = re.sub(r"</?table[^>]*>", "", t)
    cleaned = re.sub(r"</?tbody[^>]*>", "", cleaned)
    cleaned = re.sub(r"</?thead[^>]*>", "", cleaned)
    cleaned = re.sub(r"</tr>", "\n", cleaned)
    cleaned = re.sub(r"<tr[^>]*>", "", cleaned)
    cleaned = re.sub(r"</t[dh]>", "\t", cleaned)
    cleaned = re.sub(r"<t[dh][^>]*>", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    lines = [ln.strip() for ln in cleaned.split("\n") if ln.strip()]
    return "\n".join(lines)


def _extract_json_translation(t: str) -> str | None:
    """尝试从 LLM 返回的 JSON 结构中提取 translation 字段。"""
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            for key in ("translation", "翻译", "text", "content"):
                if key in obj and isinstance(obj[key], str):
                    return obj[key].strip()
    except (json.JSONDecodeError, ValueError):
        pass
    for key in ("translation", "翻译"):
        m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', t, re.DOTALL)
        if m:
            return m.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
    for key in ("translation", "翻译"):
        marker = f'"{key}": "'
        idx = t.find(marker)
        if idx >= 0:
            rest = t[idx + len(marker):]
            end = 0
            while end < len(rest):
                if rest[end] == '"' and (end == 0 or rest[end - 1] != '\\'):
                    break
                end += 1
            if end > 0:
                return rest[:end].replace("\\n", "\n").replace('\\"', '"').strip()
    return None


def _clean_display_text(text: str) -> str:
    """清洗翻译/原文中的异常格式：JSON 泄漏提取翻译，HTML 表格转可读文本。"""
    if not text:
        return text
    t = text.strip()
    if t.startswith("{") and ('"translation"' in t or '"翻译"' in t):
        extracted = _extract_json_translation(t)
        if extracted:
            t = extracted
    if "<table" in t.lower() and "<td" in t.lower():
        t = _strip_html_table(t)
    return t


def _get_partial_failed_bps(doc_id: str) -> list[int]:
    entries, _, _ = load_entries_from_disk(doc_id)
    return sorted(
        entry.get("_pageBP")
        for entry in entries
        if entry.get("_pageBP") is not None
        and any((pe.get("_status") == "error") for pe in entry.get("_page_entries", []))
    )


def _build_preview_paragraphs(text: str) -> list[str]:
    raw = normalize_latex_footnote_markers(_ensure_str(text)).replace("\r\n", "\n").strip()
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


def _build_translate_usage_payload(doc_id: str) -> dict:
    """构建翻译 API 使用情况页面/接口的数据。"""
    entries, doc_title, _ = load_entries_from_disk(doc_id)
    snapshot = get_translate_snapshot(doc_id)
    snapshot["partial_failed_bps"] = _get_partial_failed_bps(doc_id)
    pages = []
    total_manual_revisions = 0
    pages_with_manual_revisions = 0
    for entry in entries:
        usage = entry.get("_usage") or {}
        manual_revision_count = sum(
            1 for seg in (entry.get("_page_entries") or [])
            if isinstance(seg, dict) and seg.get("_translation_source") == "manual"
        )
        total_manual_revisions += manual_revision_count
        if manual_revision_count > 0:
            pages_with_manual_revisions += 1
        pages.append({
            "page_bp": entry.get("_pageBP"),
            "model": entry.get("_model", ""),
            "request_count": int(usage.get("request_count", 0) or 0),
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
            "manual_revision_count": manual_revision_count,
        })
    return {
        "doc_id": doc_id,
        "doc_title": doc_title,
        "snapshot": snapshot,
        "pages": pages,
        "total_manual_revisions": total_manual_revisions,
        "pages_with_manual_revisions": pages_with_manual_revisions,
    }


def _request_doc_id() -> str:
    return request.values.get("doc_id", "").strip() or get_current_doc_id()


def _redirect_settings(doc_id: str = "", open_custom_model: bool = False):
    target_doc_id = (doc_id or get_current_doc_id() or "").strip()
    params = {}
    if target_doc_id:
        params["doc_id"] = target_doc_id
    if open_custom_model:
        params["open_custom_model"] = "1"
    target = url_for("settings", **params)
    if open_custom_model:
        target += "#customModelPanel"
    return redirect(target)


def _redirect_after_model_change(next_page: str, doc_id: str):
    if next_page == "reading":
        reading_params = {}
        if doc_id:
            reading_params["doc_id"] = doc_id
        bp = request.values.get("bp", type=int)
        if bp is not None:
            reading_params["bp"] = bp
        for key in ("usage", "orig", "pdf"):
            value = request.values.get(key, "").strip()
            if value in {"0", "1"}:
                reading_params[key] = value
        layout = request.values.get("layout", "").strip()
        if layout in {"side", "stack"}:
            reading_params["layout"] = layout
        return redirect(url_for("reading", **reading_params))
    if next_page == "input":
        return redirect(url_for("input_page", doc_id=doc_id))
    if next_page == "settings":
        return _redirect_settings(doc_id)
    return redirect(url_for("home", doc_id=doc_id))


def _save_text_setting(form_key: str, setter, success_message: str):
    setter(request.form.get(form_key, "").strip())
    flash(success_message, "success")


def _save_translate_parallel_section():
    enabled_values = [
        str(v).strip().lower()
        for v in request.form.getlist("translate_parallel_enabled")
    ]
    enabled = any(v in {"1", "true", "yes", "on"} for v in enabled_values)
    limit = request.form.get("translate_parallel_limit", "").strip()
    normalized_enabled, normalized_limit = set_translate_parallel_settings(enabled, limit)
    if normalized_enabled:
        flash(f"已开启段内并发翻译（上限 {normalized_limit}，实际会按模型自动调整）", "success")
    else:
        flash("已关闭段内并发翻译", "success")
    if has_active_translate_task():
        flash("当前页的翻译已经启动，新的并发设置会从下一页开始生效。", "info")


def _save_custom_model_section(section: str, current_doc_id: str):
    if section == "custom_model":
        custom_model_name = request.form.get("custom_model_name", "").strip()
        if custom_model_name and not CUSTOM_MODEL_NAME_PATTERN.fullmatch(custom_model_name):
            flash("自定义模型名格式无效：仅允许字母、数字、-、_、.", "error")
            return _redirect_settings(current_doc_id, open_custom_model=True)
        if custom_model_name:
            base_key = get_model_key()
            save_custom_model_selection(custom_model_name, True, base_key)
            flash(f"已保存自定义模型名：{custom_model_name}", "success")
        else:
            save_custom_model_selection("", False, "")
            flash("已清空自定义模型名，恢复使用默认模型 ID", "success")
        return _redirect_settings(current_doc_id, open_custom_model=True)

    if section == "custom_model_activate":
        custom_model_name = get_custom_model_name()
        custom_model_base_key = get_custom_model_base_key()
        if not custom_model_name or not custom_model_base_key:
            flash("还没有可启用的自定义模型，请先保存模型名。", "error")
        else:
            set_model_key(custom_model_base_key)
            set_custom_model_enabled(True)
            flash(f"已启用已保存的自定义模型：{custom_model_name}", "success")
        return _redirect_settings(current_doc_id, open_custom_model=True)

    if section == "custom_model_clear":
        save_custom_model_selection("", False, "")
        flash("已清空自定义模型名，恢复使用默认模型 ID", "success")
        return _redirect_settings(current_doc_id, open_custom_model=True)

    return None


def _guard_doc_delete(doc_id: str):
    """删除前统一校验，避免翻译中的文档被误删。"""
    if not doc_id:
        flash("暂无可删除的文档", "error")
        return redirect(url_for("home"))
    if is_translate_running(doc_id):
        flash("该文档正在翻译中，请先停止翻译后再删除。", "error")
        return redirect(url_for("home", doc_id=doc_id))
    return None


def _delete_doc_with_verification(doc_id: str) -> bool:
    """删除文档后做一次磁盘验收，避免假删除成功。"""
    doc_dir = get_doc_dir(doc_id)
    try:
        delete_doc(doc_id)
    except Exception:
        return False
    return not (doc_dir and os.path.isdir(doc_dir))


# ============ ROUTES: 首页与文档管理 ============

@app.route("/")
def home():
    requested_doc_id = request.args.get("doc_id", "").strip()
    current_doc_id = requested_doc_id if requested_doc_id and get_doc_meta(requested_doc_id) else get_current_doc_id()
    if requested_doc_id and current_doc_id == requested_doc_id:
        set_current_doc(current_doc_id)
    state = get_app_state(current_doc_id)
    logs = session.pop("logs", [])
    docs = list_docs()
    return render_template("home.html", logs=logs, docs=docs, current_doc_id=current_doc_id, **state)


@app.route("/switch_doc/<doc_id>", methods=["POST"])
def switch_doc(doc_id):
    """切换到指定文档。"""
    set_current_doc(doc_id)
    return redirect(url_for("home"))


@app.route("/delete_doc/<doc_id>", methods=["POST"])
def delete_doc_route(doc_id):
    """删除指定文档。"""
    blocked = _guard_doc_delete(doc_id)
    if blocked:
        return blocked
    if not _delete_doc_with_verification(doc_id):
        flash("删除失败，请稍后重试", "error")
        return redirect(url_for("home", doc_id=doc_id))
    flash("文档已删除", "success")
    return redirect(url_for("home"))


@app.route("/input")
def input_page():
    requested_doc_id = request.args.get("doc_id", "").strip()
    current_doc_id = requested_doc_id if requested_doc_id and get_doc_meta(requested_doc_id) else get_current_doc_id()
    if requested_doc_id and current_doc_id == requested_doc_id:
        set_current_doc(current_doc_id)
    state = get_app_state(current_doc_id)
    if not state["has_pages"]:
        flash("请先上传文件。", "error")
        return redirect(url_for("home"))
    return render_template("input.html", current_doc_id=current_doc_id, **state)


# ============ ROUTES: 阅读 ============

@app.route("/reading")
def reading():
    requested_doc_id = request.args.get("doc_id", "").strip()
    current_doc_id = requested_doc_id if requested_doc_id and get_doc_meta(requested_doc_id) else get_current_doc_id()
    if requested_doc_id and current_doc_id == requested_doc_id:
        set_current_doc(current_doc_id)
    state = get_app_state(current_doc_id)
    usage_open = request.args.get("usage", "0") == "1"
    show_original = request.args.get("orig", "0") == "1"
    layout_mode = request.args.get("layout", "stack").strip()
    pdf_requested = request.args.get("pdf", "0") == "1"
    if not state["has_pages"]:
        flash("请先上传文件。", "error")
        return redirect(url_for("home"))

    pages = state["pages"]
    page_bps = [pg["bookPage"] for pg in pages]
    entries = state["entries"]
    translate_snapshot = get_translate_snapshot(current_doc_id)
    show_initial_translate_snapshot = translate_snapshot.get("phase") in ("running", "stopping")
    failed_pages = translate_snapshot.get("failed_pages", [])
    failed_bps = sorted({
        page.get("bp") for page in failed_pages
        if isinstance(page, dict) and page.get("bp") is not None
    })
    entry_by_bp = {}
    for entry in entries:
        bp = entry.get("_pageBP")
        if bp is not None:
            entry_by_bp[bp] = entry

    requested_bp = request.args.get("bp", type=int)
    cur_page_bp = requested_bp
    if cur_page_bp not in page_bps:
        if requested_bp is not None and page_bps:
            flash(
                f"页码 {requested_bp} 不在范围 p.{page_bps[0]}-p.{page_bps[-1]} 内，已跳转到 p.{state.get('first_page', page_bps[0])}。",
                "info",
            )
        if entries:
            cur_page_bp = entries[max(0, min(state["entry_idx"], len(entries) - 1))].get("_pageBP", state.get("first_page", 1))
        else:
            cur_page_bp = state.get("first_page", 1)

    cur = entry_by_bp.get(cur_page_bp, {})
    page_entries = cur.get("_page_entries", [])
    glossary = state["glossary"]
    has_current_entry = bool(cur)
    current_page_data = next(
        (pg for pg in pages if pg.get("bookPage") == cur_page_bp),
        {},
    )
    current_page_markdown = _ensure_str(current_page_data.get("markdown", "")).strip()
    current_page_markdown_paragraphs = _build_preview_paragraphs(current_page_markdown)
    current_page_footnotes = normalize_latex_footnote_markers(
        _ensure_str(current_page_data.get("footnotes", ""))
    ).strip()

    display_entries = []
    for pe in page_entries:
        pe_copy = dict(pe)
        for field in ("original", "translation", "footnotes", "footnotes_translation"):
            pe_copy[field] = _clean_display_text(
                normalize_latex_footnote_markers(_ensure_str(pe_copy.get(field)))
            )
        pe_copy["original_html"] = highlight_terms(pe_copy["original"], glossary)
        display_entries.append(pe_copy)

    cur_model_label = ""
    m = cur.get("_model", "")
    if m and m in MODELS:
        cur_model_label = MODELS[m]["label"]

    # 构建 bookPage → fileIdx 映射表（供前端 PDF 定位）
    page_map = {}
    for pg in pages:
        page_map[pg["bookPage"]] = pg["fileIdx"]

    page_index = page_bps.index(cur_page_bp) if cur_page_bp in page_bps else 0
    prev_bp = page_bps[page_index - 1] if page_index > 0 else None
    next_bp = page_bps[page_index + 1] if page_index < len(page_bps) - 1 else None
    translated_bps = sorted(entry_by_bp.keys())
    partial_failed_bps = translate_snapshot.get("partial_failed_bps") or _get_partial_failed_bps(current_doc_id)
    pdf_virtual_window_radius = get_pdf_virtual_window_radius()
    pdf_virtual_scroll_min_pages = get_pdf_virtual_scroll_min_pages()
    if len(page_bps) >= pdf_virtual_scroll_min_pages:
        initial_start = max(0, page_index - pdf_virtual_window_radius)
        initial_end = min(len(page_bps), page_index + pdf_virtual_window_radius + 1)
        pdf_initial_mounted_bps = page_bps[initial_start:initial_end]
    else:
        pdf_initial_mounted_bps = list(page_bps)
    if cur_page_bp in translated_bps:
        save_entry_cursor(translated_bps.index(cur_page_bp), current_doc_id)
    current_page_failure = next(
        (page for page in failed_pages if isinstance(page, dict) and page.get("bp") == cur_page_bp),
        None,
    )

    side_by_side = session.get("side_by_side", False)
    if layout_mode == "side":
        side_by_side = True
    elif layout_mode == "stack":
        side_by_side = False
    pdf_available = has_pdf(current_doc_id)
    pdf_visible = pdf_available and pdf_requested
    export_md = ""

    return render_template(
        "reading.html",
        cur=cur,
        display_entries=display_entries,
        cur_page_bp=cur_page_bp,
        current_page_index=page_index,
        page_total=len(page_bps),
        prev_bp=prev_bp,
        next_bp=next_bp,
        page_bps=page_bps,
        translated_bps=translated_bps,
        has_translation_history=state.get("has_translation_history", False),
        partial_failed_bps=partial_failed_bps,
        failed_bps=failed_bps,
        has_current_entry=has_current_entry,
        current_page_failed=cur_page_bp in failed_bps and not has_current_entry,
        current_page_failure=current_page_failure,
        cur_model_label=cur_model_label,
        side_by_side=side_by_side,
        export_md=export_md,
        doc_title=state.get("doc_title", ""),
        model_key=state["model_key"],
        custom_model_name=state.get("custom_model_name", ""),
        models=MODELS,
        pages=pages,
        has_pages=state["has_pages"],
        has_entries=state["has_entries"],
        page_count=state["page_count"],
        first_page=state["first_page"],
        last_page=state["last_page"],
        entry_count=state["entry_count"],
        src_name=state["src_name"],
        glossary=glossary,
        has_pdf=pdf_available,
        page_map=page_map,
        current_doc_id=current_doc_id,
        usage_open=usage_open,
        show_original=show_original,
        pdf_visible=pdf_visible,
        current_page_markdown=current_page_markdown,
        current_page_markdown_paragraphs=current_page_markdown_paragraphs,
        current_page_footnotes=current_page_footnotes,
        translate_snapshot=translate_snapshot,
        show_initial_translate_snapshot=show_initial_translate_snapshot,
        pdf_virtual_window_radius=pdf_virtual_window_radius,
        pdf_virtual_scroll_min_pages=pdf_virtual_scroll_min_pages,
        pdf_initial_mounted_bps=pdf_initial_mounted_bps,
    )


# ============ ROUTES: 上传 (async with SSE) ============

@app.route("/upload_file", methods=["POST"])
def upload_file():
    """Step 1: receive file, save to temp, return task_id."""
    paddle_token = get_paddle_token()
    if not paddle_token:
        return jsonify({"error": "请先在设置中输入 PaddleOCR 令牌。"}), 200

    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件。"}), 200

    file_name = f.filename
    ext = os.path.splitext(file_name)[1].lower()

    if ext == ".pdf":
        file_type = 0
    elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
        file_type = 1
    else:
        return jsonify({"error": f"不支持的文件类型: {ext}"}), 200

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    f.save(tmp)
    tmp.close()

    task_id = uuid.uuid4().hex[:12]
    create_task(task_id, tmp.name, file_name, file_type)

    t = threading.Thread(target=process_file, args=(task_id,), daemon=True)
    t.start()

    return jsonify({"task_id": task_id})


@app.route("/reparse", methods=["POST"])
def reparse():
    """对当前文档重新执行 OCR 解析（保留翻译数据）。"""
    paddle_token = get_paddle_token()
    if not paddle_token:
        return jsonify({"error": "请先在设置中输入 PaddleOCR 令牌。"}), 200

    doc_id = _request_doc_id()
    if not doc_id:
        return jsonify({"error": "没有活跃文档。"}), 200
    set_current_doc(doc_id)

    pdf_path = get_pdf_path(doc_id)
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "未找到 PDF 文件，无法重新解析。"}), 200

    pages, file_name = load_pages_from_disk(doc_id)
    task_id = uuid.uuid4().hex[:12]
    create_task(task_id, pdf_path, file_name or "source.pdf", 0)

    from tasks import reparse_file
    t = threading.Thread(target=reparse_file, args=(task_id, doc_id), daemon=True)
    t.start()

    return jsonify({"task_id": task_id})


@app.route("/reparse_page/<int:page_bp>", methods=["POST"])
def reparse_page(page_bp):
    """对指定页码重新执行 OCR 解析（保留翻译数据）。"""
    paddle_token = get_paddle_token()
    if not paddle_token:
        return jsonify({"error": "请先在设置中输入 PaddleOCR 令牌。"}), 200

    doc_id = _request_doc_id()
    if not doc_id:
        return jsonify({"error": "没有活跃文档。"}), 200
    set_current_doc(doc_id)

    pdf_path = get_pdf_path(doc_id)
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "未找到 PDF 文件，无法重新解析。"}), 200

    # 查找该页码对应的 fileIdx
    pages, file_name = load_pages_from_disk(doc_id)
    file_idx = None
    for p in pages:
        if p["bookPage"] == page_bp:
            file_idx = p["fileIdx"]
            break

    if file_idx is None:
        return jsonify({"error": f"未找到页码 {page_bp}"}), 200

    task_id = uuid.uuid4().hex[:12]
    create_task(task_id, pdf_path, file_name or "source.pdf", 0)

    from tasks import reparse_single_page
    t = threading.Thread(target=reparse_single_page, args=(task_id, doc_id, page_bp, file_idx), daemon=True)
    t.start()

    return jsonify({"task_id": task_id})


@app.route("/process_sse")
def process_sse():
    """Step 2: SSE endpoint that streams progress events."""
    task_id = request.args.get("task_id")
    if not task_id or not get_task(task_id):
        return Response("data: {}\n\n", mimetype="text/event-stream")

    def generate():
        cursor = 0
        while True:
            events, exists = get_task_events(task_id, cursor)
            if not exists:
                break
            cursor += len(events)

            for evt_type, evt_data in events:
                yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False)}\n\n"
                if evt_type in ("done", "error_msg"):
                    if evt_type == "done" and evt_data.get("logs"):
                        set_task_final(task_id, evt_data["logs"], evt_data.get("summary", ""))
                    def cleanup():
                        time.sleep(10)
                        remove_task(task_id)
                    threading.Thread(target=cleanup, daemon=True).start()
                    return

            time.sleep(0.3)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============ ROUTES: 翻译 ============

@app.route("/start_from_beginning", methods=["POST"])
def start_from_beginning():
    """从首页开始阅读。"""
    doc_id = _request_doc_id()
    if doc_id:
        set_current_doc(doc_id)
    pages, _ = load_pages_from_disk(doc_id)
    if not pages:
        flash("请先上传文件。", "error")
        return redirect(url_for("home"))

    model_key = get_model_key()
    t_args = get_translate_args(model_key)
    if not t_args["api_key"]:
        provider = MODELS[model_key].get("provider", "deepseek")
        name = "DashScope API Key" if provider == "qwen" else "DeepSeek API Key"
        flash(f"请先在设置中输入 {name}。", "error")
        return redirect(url_for("home"))

    first_page, _ = get_page_range(pages)
    return redirect(url_for("reading", bp=first_page, auto=1, start_bp=first_page, doc_id=doc_id))


@app.route("/start_reading", methods=["POST"])
def start_reading():
    doc_id = request.form.get("doc_id", "").strip() or get_current_doc_id()
    if doc_id:
        set_current_doc(doc_id)
    pages, src_name = load_pages_from_disk(doc_id)
    if not pages:
        flash("请先上传文件。", "error")
        return redirect(url_for("home"))

    model_key = get_model_key()
    t_args = get_translate_args(model_key)
    if not t_args["api_key"]:
        provider = MODELS[model_key].get("provider", "deepseek")
        name = "DashScope API Key" if provider == "qwen" else "DeepSeek API Key"
        flash(f"请先在设置中输入 {name}。", "error")
        return redirect(url_for("input_page"))

    start_page = request.form.get("start_page", type=int)
    doc_title = request.form.get("doc_title", "").strip() or src_name or "Untitled"
    first, last = get_page_range(pages)

    if not start_page or start_page < first or start_page > last:
        flash(f"请输入有效页码 ({first}-{last})", "error")
        return redirect(url_for("input_page", doc_id=doc_id))

    save_entries_to_disk([], doc_title, 0, doc_id)
    return redirect(url_for("reading", bp=start_page, auto=1, start_bp=start_page, doc_id=doc_id))


@app.route("/fetch_next", methods=["POST"])
def fetch_next():
    """翻译下一页。"""
    doc_id = _request_doc_id()
    if doc_id:
        set_current_doc(doc_id)
    pages, _ = load_pages_from_disk(doc_id)
    entries, doc_title, entry_idx = load_entries_from_disk(doc_id)
    model_key = get_model_key()
    t_args = get_translate_args(model_key)

    if not pages or not entries or not t_args["api_key"]:
        flash("数据不完整或缺少API Key", "error")
        return redirect(url_for("reading", doc_id=doc_id))

    last_entry = entries[-1]
    last_page_bp = last_entry.get("_pageBP") or last_entry.get("_endBP", 1)
    next_bp = get_next_page_bp(pages, last_page_bp)

    if next_bp is None:
        flash("已到末尾", "info")
        return redirect(url_for("reading", bp=last_page_bp, doc_id=doc_id))

    try:
        p = translate_page(pages, next_bp, model_key, t_args, get_glossary(doc_id))
        save_entry_to_disk(p, doc_title, doc_id)
        reconcile_translate_state_after_page_success(doc_id, next_bp)
        return redirect(url_for("reading", bp=next_bp, doc_id=doc_id))
    except Exception as e:
        reconcile_translate_state_after_page_failure(doc_id, next_bp, str(e))
        flash(f"翻译失败: {e}", "error")
        return redirect(url_for("reading", bp=last_page_bp, doc_id=doc_id))


@app.route("/retranslate/<int:bp>/<model>", methods=["POST"])
def retranslate(bp, model):
    """重新翻译整页。"""
    doc_id = _request_doc_id()
    if doc_id:
        set_current_doc(doc_id)
    pages, _ = load_pages_from_disk(doc_id)
    entries, doc_title, _ = load_entries_from_disk(doc_id)

    if model not in MODELS:
        model = get_model_key()
    t_args = get_translate_args(model)

    target_idx = None
    for i, entry in enumerate(entries):
        if entry.get("_pageBP") == bp:
            target_idx = i
            break

    if target_idx is None or not t_args["api_key"]:
        flash("数据不完整或缺少API Key", "error")
        return redirect(url_for("reading", doc_id=doc_id))

    try:
        new_entry = translate_page(pages, bp, model, t_args, get_glossary(doc_id))
        save_entry_to_disk(new_entry, doc_title, doc_id)
        reconcile_translate_state_after_page_success(doc_id, bp)
        flash(f"重译完成 ({MODELS[model]['label']})", "success")
    except Exception as e:
        reconcile_translate_state_after_page_failure(doc_id, bp, str(e))
        flash(f"重译失败: {e}", "error")

    return redirect(url_for("reading", bp=bp, doc_id=doc_id))


@app.route("/save_manual_revision", methods=["POST"])
def save_manual_revision():
    """保存当前页某段人工修订译文。"""
    doc_id = _request_doc_id()
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
    try:
        segment = SQLiteRepository().save_manual_translation_segment(
            doc_id=doc_id,
            book_page=int(bp),
            segment_index=int(segment_index),
            translation=str(translation),
            updated_by="local_user",
            base_updated_at=int(base_updated_at) if base_updated_at is not None else None,
        )
        return jsonify({"ok": True, "segment": segment})
    except RuntimeError as e:
        server_segment = SQLiteRepository().get_translation_segment(
            doc_id, int(bp), int(segment_index)
        )
        return jsonify({"ok": False, "error": str(e), "server_segment": server_segment}), 409
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404


@app.route("/segment_history")
def segment_history():
    """返回某个段落的历史版本列表。"""
    doc_id = request.args.get("doc_id", "").strip() or get_current_doc_id()
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    try:
        bp = int(request.args.get("bp", 0))
        seg_idx = int(request.args.get("segment_index", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "无效页码或段落索引"}), 400
    revisions = SQLiteRepository().list_segment_revisions(doc_id, bp, seg_idx)
    return jsonify({"ok": True, "revisions": revisions})


@app.route("/check_retranslate_warnings")
def check_retranslate_warnings():
    """返回当前页人工修订段落数，用于重译前警告提示。"""
    doc_id = request.args.get("doc_id", "").strip() or get_current_doc_id()
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    try:
        bp = int(request.args.get("bp", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "无效页码"}), 400
    count = SQLiteRepository().count_manual_segments(doc_id, bp)
    return jsonify({"ok": True, "manual_count": count})


# ============ ROUTES: 后台翻译 SSE ============

@app.route("/translate_all_sse")
def translate_all_sse():
    """SSE 端点：推送后台翻译进度。"""
    doc_id = request.args.get("doc_id", "").strip() or get_current_doc_id()

    def generate():
        cursor = 0
        start_time = time.time()
        idle_count = 0
        while True:
            if time.time() - start_time > 600:
                yield f"event: timeout\ndata: {{}}\n\n"
                return

            events, running = get_translate_events(cursor, doc_id)
            cursor += len(events)

            for evt_type, evt_data in events:
                yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False)}\n\n"
                if evt_type in ("all_done", "stopped", "error"):
                    return

            if not running and not events:
                idle_count += 1
                if idle_count >= 3:
                    yield f"event: idle\ndata: {{}}\n\n"
                    return
            else:
                idle_count = 0

            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/start_translate_all", methods=["POST"])
def start_translate_all():
    """启动后台连续翻译。"""
    doc_id = request.form.get("doc_id", "").strip() or get_current_doc_id()
    force_restart = request.form.get("force_restart", "").strip() == "1"

    active_running = has_active_translate_task()
    if active_running and not force_restart:
        return jsonify({"status": "already_running"})
    if active_running and force_restart:
        stop_requested = request_stop_active_translate()
        if not stop_requested:
            return jsonify({"status": "switch_timeout", "error": "failed_to_request_stop"})
        if not wait_for_translate_idle(timeout_s=4.0, poll_interval_s=0.05):
            return jsonify({"status": "switch_timeout"})

    pages, src_name = load_pages_from_disk(doc_id)
    if not pages:
        return jsonify({"error": "no_pages"})

    model_key = get_model_key()
    t_args = get_translate_args(model_key)
    if not t_args["api_key"]:
        return jsonify({"error": "no_api_key"})

    start_bp = request.form.get("start_bp", type=int)
    doc_title = request.form.get("doc_title", "").strip() or src_name or "Untitled"
    if start_bp is None:
        start_bp, _ = get_page_range(pages)

    entries, _, _ = load_entries_from_disk(doc_id)
    if not entries:
        save_entries_to_disk([], doc_title, 0, doc_id)

    set_current_doc(doc_id)
    started = start_translate_task(doc_id, start_bp, doc_title)
    if not started:
        return jsonify({"status": "switch_timeout"})
    return jsonify({
        "status": "switching" if force_restart else "started",
        "start_bp": start_bp,
    })


@app.route("/stop_translate", methods=["POST"])
def stop_translate():
    """停止后台翻译。"""
    doc_id = _request_doc_id()
    stopped = request_stop_translate(doc_id)
    return jsonify({"status": "stopping" if stopped else "not_running"})


@app.route("/translate_status")
def translate_status():
    """查询翻译状态。"""
    doc_id = request.args.get("doc_id", "").strip() or get_current_doc_id()
    snapshot = get_translate_snapshot(doc_id)
    entries, _, _ = load_entries_from_disk(doc_id)
    snapshot["translated_bps"] = sorted(
        entry.get("_pageBP")
        for entry in entries
        if entry.get("_pageBP") is not None
    )
    snapshot["partial_failed_bps"] = snapshot.get("partial_failed_bps") or _get_partial_failed_bps(doc_id)
    return jsonify(snapshot)


@app.route("/translate_api_usage")
def translate_api_usage():
    """翻译 API 使用情况入口，统一回到阅读页内仪表盘。"""
    doc_id = request.args.get("doc_id", "").strip() or get_current_doc_id()
    if doc_id:
        set_current_doc(doc_id)
    state = get_app_state(doc_id)
    bp = request.args.get("bp", type=int)
    if bp is None:
        entries = state.get("entries", [])
        if entries:
            bp = entries[max(0, min(state["entry_idx"], len(entries) - 1))].get("_pageBP", state["first_page"])
        else:
            bp = state["first_page"]
    return redirect(url_for("reading", bp=bp, usage=1, auto=request.args.get("auto", "0"), doc_id=doc_id))


@app.route("/translate_api_usage_data")
def translate_api_usage_data():
    """翻译 API 使用情况数据接口。"""
    doc_id = request.args.get("doc_id", "").strip() or get_current_doc_id()
    return jsonify(_build_translate_usage_payload(doc_id))


@app.route("/paddle_quota_status")
def paddle_quota_status():
    """PaddleOCR 配额状态降级接口。"""
    official_url = "https://aistudio.baidu.com/paddleocr"
    return jsonify({
        "supported": False,
        "status": "unavailable",
        "official_url": official_url,
        "message": "官方站内可查看 OCR 配额状态；当前应用未接入公开额度查询接口。若当日额度用尽，OCR 阶段会返回 429 提示。",
    })


# ============ ROUTES: 设置 ============

@app.route("/settings")
def settings():
    requested_doc_id = request.args.get("doc_id", "").strip()
    current_doc_id = requested_doc_id if requested_doc_id and get_doc_meta(requested_doc_id) else get_current_doc_id()
    if requested_doc_id and current_doc_id == requested_doc_id:
        set_current_doc(current_doc_id)
    state = get_app_state(current_doc_id)
    custom_model_panel_open = request.args.get("open_custom_model", "0") == "1"
    return render_template(
        "settings.html",
        current_doc_id=current_doc_id,
        custom_model_panel_open=custom_model_panel_open,
        **state,
    )


@app.route("/save_settings", methods=["POST"])
def save_settings():
    section = request.form.get("section")
    current_doc_id = _request_doc_id()
    if current_doc_id:
        set_current_doc(current_doc_id)
    secret_sections = {
        "paddle": ("paddle_token", set_paddle_token, "PaddleOCR 令牌已保存"),
        "deepseek": ("deepseek_key", set_deepseek_key, "DeepSeek API Key 已保存"),
        "dashscope": ("dashscope_key", set_dashscope_key, "DashScope API Key 已保存"),
    }
    secret_section = secret_sections.get(section)
    if secret_section:
        _save_text_setting(*secret_section)
    elif section == "translate_parallel":
        _save_translate_parallel_section()
    else:
        custom_model_redirect = _save_custom_model_section(section, current_doc_id)
        if custom_model_redirect is not None:
            return custom_model_redirect
    return _redirect_settings(current_doc_id)


@app.route("/save_glossary", methods=["POST"])
def save_glossary():
    doc_id = _request_doc_id()
    if doc_id:
        set_current_doc(doc_id)
    glossary = []
    seen_terms = set()
    for key in request.form:
        if key.startswith("term_"):
            n = key[5:]
            term = request.form.get(f"term_{n}", "").strip()
            defn = request.form.get(f"defn_{n}", "").strip()
            if term and defn:
                normalized = term.lower()
                if normalized in seen_terms:
                    continue
                seen_terms.add(normalized)
                glossary.append([term, defn])
    set_glossary(glossary, doc_id=doc_id)
    flash(f"词典已保存 ({len(glossary)} 条)", "success")
    return redirect(url_for("settings", doc_id=doc_id) + "#glossary")


@app.route("/api/glossary")
def api_glossary_list():
    doc_id = _request_doc_id()
    return jsonify({"items": list_glossary_items(doc_id=doc_id)})


@app.route("/api/glossary", methods=["POST"])
def api_glossary_create():
    doc_id = _request_doc_id()
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    data = request.get_json(silent=True) or {}
    term = str(data.get("term", "")).strip()
    defn = str(data.get("defn", "")).strip()
    if not term or not defn:
        return jsonify({"ok": False, "error": "term/defn 不能为空"}), 400
    items, updated = upsert_glossary_item(term, defn, doc_id=doc_id)
    return jsonify({"ok": True, "updated": updated, "items": items})


@app.route("/api/glossary/<path:term>", methods=["PUT", "PATCH"])
def api_glossary_update(term):
    doc_id = _request_doc_id()
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    data = request.get_json(silent=True) or {}
    defn = str(data.get("defn", "")).strip()
    if not defn:
        return jsonify({"ok": False, "error": "defn 不能为空"}), 400
    items, _ = upsert_glossary_item(term, defn, doc_id=doc_id)
    return jsonify({"ok": True, "updated": True, "items": items})


@app.route("/api/glossary/<path:term>", methods=["DELETE"])
def api_glossary_delete(term):
    doc_id = _request_doc_id()
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    items, deleted = delete_glossary_item(term, doc_id=doc_id)
    if not deleted:
        return jsonify({"ok": False, "error": "term 不存在", "items": items}), 404
    return jsonify({"ok": True, "deleted": True, "items": items})


@app.route("/api/glossary/import", methods=["POST"])
def api_glossary_import():
    doc_id = _request_doc_id()
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "未上传文件"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "未上传文件"}), 400
    mode = request.form.get("mode", "append")
    try:
        new_items = parse_glossary_file(f)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception:
        return jsonify({"ok": False, "error": "文件解析失败，请检查格式"}), 400
    if not new_items:
        return jsonify({"ok": False, "error": "文件中未找到有效术语行"}), 400
    if mode == "overwrite":
        set_glossary(new_items, doc_id=doc_id)
        items = list_glossary_items(doc_id=doc_id)
    else:
        for term, defn in new_items:
            upsert_glossary_item(term, defn, doc_id=doc_id)
        items = list_glossary_items(doc_id=doc_id)
    return jsonify({"ok": True, "imported": len(new_items), "total": len(items), "items": items})


@app.route("/set_model/<key>", methods=["POST"])
def set_model(key):
    if key in MODELS:
        set_model_key(key)
        set_custom_model_enabled(False)
    next_page = request.values.get("next", "home")
    doc_id = request.values.get("doc_id", "").strip() or get_current_doc_id()
    if doc_id:
        set_current_doc(doc_id)
    return _redirect_after_model_change(next_page, doc_id)


@app.route("/set_pref", methods=["POST"])
def set_pref():
    data = request.get_json(silent=True) or {}
    if "side_by_side" in data:
        session["side_by_side"] = bool(data["side_by_side"])
    return jsonify({"ok": True})


# ============ ROUTES: 导出 ============

@app.route("/download_md")
def download_md():
    doc_id = request.args.get("doc_id", "").strip() or get_current_doc_id()
    entries, doc_title, _ = load_entries_from_disk(doc_id)
    md = "\ufeff" + gen_markdown(entries)
    buf = BytesIO(md.encode("utf-8"))
    filename = (doc_title or "export") + ".md"
    return send_file(buf, as_attachment=True, download_name=filename, mimetype="text/markdown")


@app.route("/export_md")
def export_md():
    """API端点：按需返回 markdown 内容供预览。"""
    doc_id = request.args.get("doc_id", "").strip() or get_current_doc_id()
    entries, doc_title, _ = load_entries_from_disk(doc_id)
    md = gen_markdown(entries)
    return jsonify({"markdown": md})


# ============ ROUTES: PDF 预览 ============

@app.route("/pdf_file")
def pdf_file():
    """提供当前文档的 PDF 文件用于内嵌预览。"""
    path = get_pdf_path(request.args.get("doc_id", "").strip())
    if not path or not os.path.exists(path):
        return "PDF 文件不存在", 404
    return send_file(path, mimetype="application/pdf")


@app.route("/pdf_page/<int:file_idx>")
def pdf_page(file_idx):
    """渲染 PDF 指定页为 PNG 图片。"""
    path = get_pdf_path(request.args.get("doc_id", "").strip())
    if not path or not os.path.exists(path):
        return "PDF 文件不存在", 404
    raw_scale = request.args.get("scale", "")
    scale = 2.0
    if raw_scale != "":
        scale = request.args.get("scale", type=float)
        if scale is None or scale <= 0:
            return "scale 参数无效", 400
    try:
        png_bytes = render_pdf_page(path, file_idx, scale=scale)
        return Response(png_bytes, mimetype="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})
    except Exception as e:
        return f"渲染失败: {e}", 400


@app.route("/pdf_toc")
def pdf_toc():
    doc_id = request.args.get("doc_id", "").strip() or get_current_doc_id()
    if not doc_id:
        return jsonify({"doc_id": "", "toc": []})
    return jsonify({"doc_id": doc_id, "toc": load_pdf_toc_from_disk(doc_id)})


# ============ ROUTES: 重置 ============

@app.route("/reset_text", methods=["POST"])
def reset_text():
    """清除当前文档的翻译数据，保留页面数据。"""
    doc_id = _request_doc_id()
    if doc_id:
        set_current_doc(doc_id)
    clear_entries_from_disk(doc_id)
    return redirect(url_for("input_page", doc_id=doc_id))


@app.route("/reset_text_action", methods=["POST"])
def reset_text_action():
    """从设置页清除当前文档翻译数据。"""
    doc_id = _request_doc_id()
    if doc_id:
        set_current_doc(doc_id)
    clear_entries_from_disk(doc_id)
    flash("翻译数据已清除", "success")
    return _redirect_settings(doc_id)


@app.route("/reset_all", methods=["POST"])
def reset_all():
    """删除当前文档。"""
    requested_doc_id = request.values.get("doc_id", "").strip()
    doc_id = requested_doc_id or get_current_doc_id()
    if requested_doc_id and not get_doc_meta(requested_doc_id):
        flash("文档不存在", "error")
        return redirect(url_for("home"))
    blocked = _guard_doc_delete(doc_id)
    if blocked:
        return blocked
    if doc_id and not _delete_doc_with_verification(doc_id):
        flash("删除失败，请稍后重试", "error")
        return redirect(url_for("home", doc_id=doc_id))
    flash("当前文档已删除", "success")
    return redirect(url_for("home"))


# ============ MAIN ============

if __name__ == "__main__":
    # 检查写入权限
    can_write, error_msg = check_write_permission()
    if not can_write:
        print("=" * 60)
        print("错误：无法访问数据目录")
        print("=" * 60)
        print(error_msg)
        print("-" * 60)
        print(f"数据目录: {LOCAL_DATA_DIR}")
        print("=" * 60)
        import sys
        sys.exit(1)

    ensure_dirs()
    print(f"数据目录: {LOCAL_DATA_DIR}")
    debug_env = os.getenv("FLASK_DEBUG", "").strip().lower()
    debug_mode = debug_env in ("1", "true", "yes", "on")
    app.run(debug=debug_mode, port=8080, threaded=True)

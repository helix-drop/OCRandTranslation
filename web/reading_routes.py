"""阅读页与阅读模式切换路由服务函数。"""

from __future__ import annotations

from typing import Any

from flask import flash, redirect, render_template, request, url_for

from FNM_RE import build_retry_summary
from web.services import ReadingServices

Deps = ReadingServices


def reading(deps: Deps):
    requested_doc_id = deps["normalize_doc_id"](request.args.get("doc_id", ""))
    current_doc_id = (
        requested_doc_id
        if requested_doc_id and deps["get_doc_meta"](requested_doc_id)
        else deps["get_current_doc_id"]()
    )
    state = deps["get_app_state"](current_doc_id)
    current_view = deps["_normalize_reading_view"](request.args.get("view", "standard"))
    usage_open = request.args.get("usage", "0") == "1"
    show_original = request.args.get("orig", "0") == "1"
    pdf_requested = request.args.get("pdf", "0") == "1"
    if not state["has_pages"]:
        flash("请先上传文件。", "error")
        return redirect(url_for("home"))

    pages = state["pages"]
    raw_page_bps = [pg["bookPage"] for pg in pages]
    visible_page_bps = list(state.get("visible_page_bps") or raw_page_bps)
    hidden_placeholder_bps = {
        int(bp) for bp in (state.get("hidden_placeholder_bps") or [])
    }
    page_lookup = {
        int(pg["bookPage"]): pg
        for pg in pages
        if pg.get("bookPage") is not None
    }
    repo = deps["SQLiteRepository"]()
    fnm_run = repo.get_latest_fnm_run(current_doc_id)
    fnm_retry_summary = build_retry_summary(current_doc_id, repo=repo) if fnm_run else {}
    fnm_export_ready = bool(
        fnm_run
        and fnm_run.get("status") == "done"
        and not bool(fnm_retry_summary.get("blocking_export"))
    )
    fnm_view_available = bool(fnm_run and fnm_run.get("status") == "done")
    if current_view == "fnm" and not fnm_view_available:
        current_view = "standard"
    disk_entries = state["entries"]
    entries = disk_entries
    if current_view == "fnm":
        entries = deps["load_fnm_diagnostic_view_entries"](
            current_doc_id,
            pages=pages,
            visible_bps=visible_page_bps,
            repo=repo,
        )
    task_snapshot = deps["get_translate_snapshot"](
        current_doc_id,
        pages=pages,
        entries=disk_entries,
        visible_page_view=state.get("visible_page_view"),
    )
    visible_page_view_for_snap = state.get("visible_page_view") or deps["load_visible_page_view"](current_doc_id, pages=pages)
    reading_view_state = deps["build_reading_view_state"](
        doc_id=current_doc_id,
        view=current_view,
        pages=pages,
        visible_page_view=visible_page_view_for_snap,
        disk_entries=disk_entries,
        snapshot=task_snapshot,
        repo=repo,
    )
    show_initial_translate_snapshot = task_snapshot.get("phase") in ("running", "stopping")
    failed_pages = task_snapshot.get("failed_pages", [])
    failed_bps = list(reading_view_state.get("failed_bps") or [])
    entry_by_bp = {
        entry.get("_pageBP"): entry
        for entry in entries
        if entry.get("_pageBP") is not None
    }

    requested_bp = request.args.get("bp", type=int)
    cur_page_bp = deps["_default_reading_bp"](
        visible_page_bps,
        entries,
        state.get("entry_idx", 0),
        state.get("first_page", 1),
    )
    if requested_bp in visible_page_bps:
        cur_page_bp = int(requested_bp)
    elif requested_bp is not None and visible_page_bps:
        target_bp = deps["resolve_visible_page_bp"](pages, requested_bp) or cur_page_bp
        if requested_bp in hidden_placeholder_bps:
            flash(f"PDF 第{requested_bp}页为空白页，已跳转到 PDF 第{target_bp}页。", "info")
            redirect_params = {"bp": target_bp, "doc_id": current_doc_id}
            for key in ("usage", "orig", "pdf", "auto", "start_bp"):
                value = request.args.get(key, "").strip()
                if value:
                    redirect_params[key] = value
            return redirect(url_for("reading", **redirect_params))
        if requested_bp < raw_page_bps[0] or requested_bp > raw_page_bps[-1]:
            target_bp = cur_page_bp
            flash(f"PDF 第{requested_bp}页超出范围，已跳转到 PDF 第{target_bp}页。", "info")
        else:
            target_bp = target_bp or cur_page_bp
            flash(f"PDF 第{requested_bp}页当前不可用，已跳转到 PDF 第{target_bp}页。", "info")
        cur_page_bp = target_bp

    cur = entry_by_bp.get(cur_page_bp, {})
    page_entries = cur.get("_page_entries", [])
    glossary = state["glossary"]
    has_current_entry = bool(cur)
    current_page_data = next(
        (pg for pg in pages if pg.get("bookPage") == cur_page_bp),
        {},
    )
    current_page_markdown = deps["ensure_str"](current_page_data.get("markdown", "")).strip()
    current_page_markdown_paragraphs = [
        deps["_render_reading_body_text"](paragraph)
        for paragraph in deps["_build_preview_paragraphs"](current_page_markdown)
    ]
    fnm_page_context = deps["build_fnm_page_context"](
        current_doc_id,
        current_bp=cur_page_bp,
        fnm_run=fnm_run if current_view == "fnm" else None,
        repo=repo,
    )
    diagnostic_footnotes = list(fnm_page_context.get("footnotes") or [])
    diagnostic_endnotes = list(fnm_page_context.get("endnotes") or [])
    fnm_validation = fnm_page_context.get("validation")
    fnm_unresolved_here = list(fnm_page_context.get("unresolved_here") or [])
    fnm_failed_here = list(fnm_page_context.get("failed_here") or [])
    fnm_retry_summary = dict(fnm_page_context.get("retry_summary") or {})
    if current_view == "fnm" and diagnostic_footnotes:
        current_page_footnotes = "\n\n".join(
            str(note.get("translated_text") or note.get("source_text") or "").strip()
            for note in diagnostic_footnotes
            if str(note.get("translated_text") or note.get("source_text") or "").strip()
        ).strip()
    elif current_view == "fnm":
        current_page_footnotes = ""
    else:
        current_page_footnotes = deps["_render_reading_footnotes_text"](
            deps["ensure_str"](current_page_data.get("footnotes", ""))
        ).strip()

    display_entries = deps["build_display_entries"](
        page_entries,
        cur_page_bp=cur_page_bp,
        glossary=glossary,
        page_lookup=page_lookup,
    )

    cur_model_label = ""
    if cur:
        if cur.get("_model_source") == "builtin" and cur.get("_model_key") in deps["MODELS"]:
            cur_model_label = deps["MODELS"][cur.get("_model_key")]["label"]
        else:
            cur_model_label = cur.get("_model_id") or cur.get("_model") or ""

    page_map = {pg["bookPage"]: pg["fileIdx"] for pg in pages}
    toc_source, toc_offset, toc_items = deps["load_effective_toc"](current_doc_id)
    toc_items = deps["_build_toc_reading_items"](toc_items, toc_offset, page_lookup)
    toc_unresolved_items = [
        item for item in toc_items
        if item.get("unresolved") and str(item.get("item_id") or "").strip()
    ]

    page_index = visible_page_bps.index(cur_page_bp) if cur_page_bp in visible_page_bps else 0
    prev_bp = visible_page_bps[page_index - 1] if page_index > 0 else None
    next_bp = visible_page_bps[page_index + 1] if page_index < len(visible_page_bps) - 1 else None
    page_notes_panel = deps["build_page_notes_panel"](
        current_view=current_view,
        display_entries=display_entries,
        diagnostic_footnotes=diagnostic_footnotes,
        diagnostic_endnotes=diagnostic_endnotes,
        diagnostic_failed_locations=fnm_failed_here,
        diagnostic_failed_summary=fnm_retry_summary,
        next_bp=next_bp,
    )
    translated_bps = list(reading_view_state.get("translated_bps") or [])
    partial_failed_bps = list(reading_view_state.get("partial_failed_bps") or [])
    pdf_virtual_window_radius = deps["get_pdf_virtual_window_radius"]()
    pdf_virtual_scroll_min_pages = deps["get_pdf_virtual_scroll_min_pages"]()
    if len(visible_page_bps) >= pdf_virtual_scroll_min_pages:
        initial_start = max(0, page_index - pdf_virtual_window_radius)
        initial_end = min(len(visible_page_bps), page_index + pdf_virtual_window_radius + 1)
        pdf_initial_mounted_bps = visible_page_bps[initial_start:initial_end]
    else:
        pdf_initial_mounted_bps = list(visible_page_bps)
    current_page_failure = next(
        (page for page in failed_pages if isinstance(page, dict) and page.get("bp") == cur_page_bp),
        None,
    )
    translate_task = dict(task_snapshot.get("task") or {})
    glossary_retranslate_blocked = bool(
        task_snapshot.get("running")
        and translate_task.get("kind") == "continuous"
    )
    glossary_retranslate_block_reason = (
        "当前有连续翻译正在运行，新词典会从下一页起生效；补重译请在当前任务停止或完成后再发起。"
        if glossary_retranslate_blocked
        else ""
    )
    page_manual_segment_count = (
        repo.count_manual_segments(current_doc_id, cur_page_bp)
        if current_view == "standard" and has_current_entry
        else 0
    )

    pdf_available = deps["has_pdf"](current_doc_id)
    pdf_visible = pdf_available and pdf_requested

    return render_template(
        "reading/index.html",
        cur=cur,
        display_entries=display_entries,
        cur_page_bp=cur_page_bp,
        current_page_index=page_index,
        page_total=len(visible_page_bps),
        prev_bp=prev_bp,
        next_bp=next_bp,
        page_bps=visible_page_bps,
        translated_bps=translated_bps,
        has_translation_history=state.get("has_translation_history", False),
        partial_failed_bps=partial_failed_bps,
        failed_bps=failed_bps,
        has_current_entry=has_current_entry,
        current_page_failed=cur_page_bp in failed_bps and not has_current_entry,
        current_page_failure=current_page_failure,
        glossary_retranslate_blocked=glossary_retranslate_blocked,
        glossary_retranslate_block_reason=glossary_retranslate_block_reason,
        page_manual_segment_count=page_manual_segment_count,
        cur_model_label=cur_model_label,
        active_model_mode=state["active_model_mode"],
        active_builtin_model_key=state["active_builtin_model_key"],
        export_md="",
        doc_title=state.get("doc_title", ""),
        model_key=state["model_key"],
        custom_model=state["custom_model"],
        custom_model_name=state.get("custom_model_name", ""),
        custom_model_enabled=state["custom_model_enabled"],
        current_model_source=state["current_model_source"],
        current_model_id=state["current_model_id"],
        current_model_label=state["current_model_label"],
        current_model_provider=state["current_model_provider"],
        models=deps["MODELS"],
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
        cur_page_print_display=deps["format_print_page_display"](
            deps["resolve_page_print_label"](current_page_data)
        ),
        task_snapshot=task_snapshot,
        translate_snapshot=task_snapshot,
        reading_view_state=reading_view_state,
        reading_view_summary_text=deps["reading_view_summary_text"](
            reading_view_state,
            task_snapshot,
            cur_page_bp,
            state["last_page"],
        ),
        show_initial_translate_snapshot=show_initial_translate_snapshot,
        pdf_virtual_window_radius=pdf_virtual_window_radius,
        pdf_virtual_scroll_min_pages=pdf_virtual_scroll_min_pages,
        pdf_initial_mounted_bps=pdf_initial_mounted_bps,
        toc_items=toc_items,
        toc_offset=toc_offset,
        toc_source=toc_source,
        toc_unresolved_items=toc_unresolved_items,
        current_view=current_view,
        fnm_view_available=fnm_view_available,
        fnm_export_ready=fnm_export_ready,
        fnm_run_status=(fnm_run or {}).get("status", "idle"),
        page_notes_panel=page_notes_panel,
        diagnostic_footnotes=diagnostic_footnotes,
        diagnostic_endnotes=diagnostic_endnotes,
        fnm_validation=fnm_validation,
        fnm_unresolved_here=fnm_unresolved_here,
    )


def switch_reading_mode(deps: Deps):
    doc_id = deps["normalize_doc_id"](request.values.get("doc_id", ""))
    if not doc_id or not deps["get_doc_meta"](doc_id):
        flash("文档无效或已删除。", "error")
        return redirect(url_for("home"))
    deps["set_current_doc"](doc_id)
    target_mode = deps["_normalize_reading_view"](request.values.get("target_mode", "standard"))
    if target_mode not in {"fnm", "standard"}:
        flash("无效的切换参数。", "error")
        return redirect(url_for("reading", doc_id=doc_id))

    reading_params: dict = {"doc_id": doc_id}
    bp = request.values.get("bp", type=int)
    if bp is not None:
        reading_params["bp"] = bp
    for key in ("usage", "orig", "pdf"):
        value = request.values.get(key, "").strip()
        if value in {"0", "1"}:
            reading_params[key] = value
    layout = request.values.get("layout", "").strip()
    if layout in {"stack", "side"}:
        reading_params["layout"] = layout

    if target_mode == "fnm":
        repo = deps["SQLiteRepository"]()
        fnm_run = repo.get_latest_fnm_run(doc_id) or {}
        if str(fnm_run.get("status") or "") != "done":
            flash("FNM 视图暂不可用（请先完成 FNM 注释分类）。", "error")
            return redirect(url_for("reading", **reading_params))
        reading_params["view"] = "fnm"
    return redirect(url_for("reading", **reading_params))


def register_reading_routes(app, deps: Deps) -> None:
    app.add_url_rule("/reading", endpoint="reading", view_func=lambda: reading(deps))
    app.add_url_rule("/switch_reading_mode", endpoint="switch_reading_mode", view_func=lambda: switch_reading_mode(deps), methods=["GET", "POST"])

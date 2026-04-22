"""导出、PDF 预览与目录数据相关路由服务函数。"""

from __future__ import annotations

import os
from io import BytesIO
from typing import Any

from flask import Response, jsonify, request, send_file

from FNM_RE import build_doc_status, build_retry_summary
from persistence.sqlite_store import SQLiteRepository
from web.services import ExportServices

Deps = ExportServices


def _request_doc_id(deps: Deps) -> str:
    return deps["_request_doc_id"]()


def _fnm_export_block_response(doc_id: str) -> tuple[dict, int] | None:
    if not doc_id:
        return None
    repo = SQLiteRepository()
    structure_status = build_doc_status(doc_id, repo=repo)
    retry_summary = build_retry_summary(doc_id, repo=repo)
    structure_blocked = not bool(structure_status.get("export_ready_test"))
    retry_blocked = bool(retry_summary.get("blocking_export"))
    if not structure_blocked and not retry_blocked:
        return None
    blocking_reasons = [
        str(item).strip()
        for item in list(structure_status.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    manual_toc_required = bool(structure_status.get("manual_toc_required"))
    if not manual_toc_required:
        manual_toc_required = any(
            reason_code in {"toc_manual_toc_required", "manual_toc_required"}
            for reason_code in blocking_reasons
        )
    reason = retry_summary.get("blocking_reason") or ""
    if not reason and manual_toc_required:
        reason = "manual_toc_required"
    if not reason and blocking_reasons:
        reason = blocking_reasons[0]
    return {
        "error": "fnm_export_blocked",
        "reason": reason or ("unresolved" if retry_blocked else "structure_review_required"),
        "structure_state": structure_status.get("structure_state"),
        "blocking_reasons": blocking_reasons,
        "manual_toc_required": manual_toc_required,
        "link_summary": structure_status.get("link_summary"),
        "execution_mode": retry_summary.get("execution_mode"),
        "retry_progress": retry_summary.get("retry_progress"),
        "next_failed_location": retry_summary.get("next_failed_location"),
        "failed_locations": retry_summary.get("failed_locations"),
        "manual_required_locations": retry_summary.get("manual_required_locations"),
    }, 409


def api_toc_chapters(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"chapters": []})
    chapters = deps["_load_toc_chapters_data"](doc_id)
    return jsonify({"chapters": chapters})


def download_md(deps: Deps):
    doc_id = _request_doc_id(deps)
    export_format = request.args.get("format", "").strip().lower()
    if export_format == "fnm_obsidian":
        blocked = _fnm_export_block_response(doc_id)
        if blocked is not None:
            payload, status = blocked
            return jsonify(payload), status
        zip_bytes = deps["build_fnm_obsidian_export_zip"](doc_id)
        buf = BytesIO(zip_bytes)
        filename = f"{deps['_sanitize_filename']((deps['get_doc_meta'](doc_id) or {}).get('name', 'export') or 'export')}.fnm.obsidian.zip"
        return send_file(buf, as_attachment=True, download_name=filename, mimetype="application/zip")

    pages, _ = deps["load_pages_from_disk"](doc_id)
    entries, doc_title, _ = deps["load_entries_from_disk"](doc_id)
    toc_depth_map = deps["_load_toc_depth_map"](doc_id)
    toc_title_map = deps["_load_toc_title_map"](doc_id)
    page_ranges = deps["_parse_bp_ranges"](request.args.get("bp_ranges", "")) or None
    exclude_boilerplate = deps["_parse_bool_flag"](request.args.get("exclude_boilerplate", ""))
    skip_bps = set()
    if exclude_boilerplate:
        chapters = deps["_load_toc_chapters_data"](doc_id)
        skip_bps = deps["compute_boilerplate_skip_bps"](entries, chapters)
    endnote_index, endnote_page_bps = deps["_build_endnote_data"](
        doc_id,
        entries,
        toc_depth_map,
        toc_title_map,
        pages=pages,
    )
    md = deps["gen_markdown"](
        entries,
        toc_depth_map=toc_depth_map,
        page_ranges=page_ranges,
        skip_bps=skip_bps,
        toc_title_map=toc_title_map,
        endnote_index=endnote_index,
        endnote_page_bps=endnote_page_bps,
    )
    buf = BytesIO(md.encode("utf-8"))
    base = deps["_sanitize_filename"](doc_title or "export")
    chapter_name = request.args.get("chapter_name", "").strip()
    if page_ranges and chapter_name:
        filename = f"{base} - {deps['_sanitize_filename'](chapter_name)}.md"
    elif page_ranges:
        filename = f"{base} - 选中章节.md"
    else:
        filename = f"{base}.md"
    return send_file(buf, as_attachment=True, download_name=filename, mimetype="text/markdown")


def export_md(deps: Deps):
    doc_id = _request_doc_id(deps)
    export_format = request.args.get("format", "").strip().lower()
    if export_format == "fnm_obsidian":
        blocked = _fnm_export_block_response(doc_id)
        if blocked is not None:
            payload, status = blocked
            return jsonify(payload), status
        export_payload = deps["build_fnm_obsidian_export"](doc_id)
        if isinstance(export_payload, dict):
            markdown = str(export_payload.get("markdown") or "")
            if not markdown:
                chapter_files = export_payload.get("chapter_files") or {}
                if isinstance(chapter_files, dict):
                    markdown = "\n\n".join(
                        str(content or "")
                        for _path, content in sorted(chapter_files.items(), key=lambda item: str(item[0]))
                    ).strip()
        else:
            markdown = str(export_payload or "")
        return jsonify({"markdown": markdown})
    pages, _ = deps["load_pages_from_disk"](doc_id)
    entries, _doc_title, _ = deps["load_entries_from_disk"](doc_id)
    toc_depth_map = deps["_load_toc_depth_map"](doc_id)
    toc_title_map = deps["_load_toc_title_map"](doc_id)
    page_ranges = deps["_parse_bp_ranges"](request.args.get("bp_ranges", "")) or None
    exclude_boilerplate = deps["_parse_bool_flag"](request.args.get("exclude_boilerplate", ""))
    skip_bps = set()
    if exclude_boilerplate:
        chapters = deps["_load_toc_chapters_data"](doc_id)
        skip_bps = deps["compute_boilerplate_skip_bps"](entries, chapters)
    endnote_index, endnote_page_bps = deps["_build_endnote_data"](
        doc_id,
        entries,
        toc_depth_map,
        toc_title_map,
        pages=pages,
    )
    md = deps["gen_markdown"](
        entries,
        toc_depth_map=toc_depth_map,
        page_ranges=page_ranges,
        skip_bps=skip_bps,
        toc_title_map=toc_title_map,
        endnote_index=endnote_index,
        endnote_page_bps=endnote_page_bps,
    )
    return jsonify({"markdown": md})


def export_pages_json(deps: Deps):
    doc_id = _request_doc_id(deps)
    pages, _ = deps["load_pages_from_disk"](doc_id)
    meta = deps["get_doc_meta"](doc_id) or {}
    return jsonify({
        "doc_id": doc_id,
        "name": str(meta.get("name") or ""),
        "page_count": len(pages),
        "pages": pages,
    })


def export_source_markdown(deps: Deps):
    doc_id = _request_doc_id(deps)
    pages, _ = deps["load_pages_from_disk"](doc_id)
    meta = deps["get_doc_meta"](doc_id) or {}
    parts: list[str] = []
    title = str(meta.get("name") or "").strip()
    if title:
        parts.append(f"# {title}")
    for page in pages:
        bp = int(page.get("bookPage") or 0)
        print_label = str(page.get("printPageLabel") or "").strip()
        heading = f"## PDF第{bp}页" if bp > 0 else "## 未知页"
        if print_label:
            heading += f" / 原书 p.{print_label}"
        parts.append(heading)
        parts.append(str(page.get("markdown") or "").rstrip())
    markdown = "\n\n".join(part for part in parts if part is not None).strip()
    return jsonify({
        "doc_id": doc_id,
        "name": title,
        "page_count": len(pages),
        "markdown": markdown,
    })


def pdf_file(deps: Deps):
    path = deps["get_pdf_path"](_request_doc_id(deps))
    if not path or not os.path.exists(path):
        return "PDF 文件不存在", 404
    return send_file(path, mimetype="application/pdf")


def pdf_page(file_idx: int, deps: Deps):
    path = deps["get_pdf_path"](_request_doc_id(deps))
    if not path or not os.path.exists(path):
        return "PDF 文件不存在", 404
    raw_scale = request.args.get("scale", "")
    scale = 2.0
    if raw_scale != "":
        scale = request.args.get("scale", type=float)
        if scale is None or scale <= 0:
            return "scale 参数无效", 400
    try:
        png_bytes = deps["render_pdf_page"](path, file_idx, scale=scale)
        return Response(
            png_bytes,
            mimetype="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except Exception as exc:
        deps["logger"].warning("PDF 页面渲染失败 path=%s idx=%s: %s", path, file_idx, exc)
        return f"渲染失败: {exc}", 400


def pdf_toc(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({
            "doc_id": "",
            "toc": [],
            "source": "auto",
            "offset": 0,
            "toc_file": deps["get_toc_file_info"](""),
            "auto_visual_toc": [],
            "has_toc_draft": False,
            "draft_pending_offset": 0,
        })
    source, offset, toc = deps["load_effective_toc"](doc_id)
    meta = deps["get_doc_meta"](doc_id) or {}
    draft_bundle = deps["load_toc_visual_draft"](doc_id)
    if source == deps["TOC_SOURCE_USER"]:
        auto_visual_editor = []
    elif draft_bundle:
        d_items, _d_off = draft_bundle
        auto_visual_editor = deps["_build_auto_visual_toc_editor_payload_from_items"](doc_id, d_items)
    else:
        auto_visual_editor = deps["_build_auto_visual_toc_editor_payload"](doc_id)
    return jsonify({
        "doc_id": doc_id,
        "toc": toc,
        "source": source,
        "offset": offset,
        "toc_file": deps["get_toc_file_info"](doc_id),
        "auto_visual_toc": auto_visual_editor,
        "has_toc_draft": bool(draft_bundle),
        "draft_pending_offset": int(draft_bundle[1]) if draft_bundle else 0,
        "toc_visual_status": str(meta.get("toc_visual_status", "idle") or "idle").strip() or "idle",
        "toc_visual_phase": str(meta.get("toc_visual_phase", "") or ""),
        "toc_visual_progress_pct": int(meta.get("toc_visual_progress_pct", 0) or 0),
        "toc_visual_progress_label": str(meta.get("toc_visual_progress_label", "") or ""),
        "toc_visual_progress_detail": str(meta.get("toc_visual_progress_detail", "") or ""),
        "toc_visual_message": str(meta.get("toc_visual_message", "") or ""),
    })


def api_doc_processing_status(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"doc_id": "", "has_doc": False})
    state = deps["get_app_state"](doc_id)
    return jsonify({
        "doc_id": doc_id,
        "has_doc": True,
        "cleanup_headers_footers_enabled": state.get("cleanup_headers_footers_enabled", False),
        "auto_visual_toc_enabled": state.get("auto_visual_toc_enabled", False),
        "has_translation_history": state.get("has_translation_history", False),
        "visual_toc_status_label": state.get("visual_toc_status_label", ""),
        "visual_toc_status_message": state.get("visual_toc_status_message", ""),
        "toc_visual_status": state.get("visual_toc_status", "idle"),
        "toc_visual_phase": state.get("visual_toc_phase", ""),
        "toc_visual_progress_pct": state.get("visual_toc_progress_pct", 0),
        "toc_visual_progress_label": state.get("visual_toc_progress_label", ""),
        "toc_visual_progress_detail": state.get("visual_toc_progress_detail", ""),
    })


def register_export_routes(app, deps: Deps) -> None:
    app.add_url_rule("/api/toc_chapters", endpoint="api_toc_chapters", view_func=lambda: api_toc_chapters(deps))
    app.add_url_rule("/download_md", endpoint="download_md", view_func=lambda: download_md(deps))
    app.add_url_rule("/export_md", endpoint="export_md", view_func=lambda: export_md(deps))
    app.add_url_rule("/export_pages_json", endpoint="export_pages_json", view_func=lambda: export_pages_json(deps))
    app.add_url_rule("/export_source_markdown", endpoint="export_source_markdown", view_func=lambda: export_source_markdown(deps))
    app.add_url_rule("/pdf_file", endpoint="pdf_file", view_func=lambda: pdf_file(deps))
    app.add_url_rule("/pdf_page/<int:file_idx>", endpoint="pdf_page", view_func=lambda file_idx: pdf_page(file_idx, deps))
    app.add_url_rule("/pdf_toc", endpoint="pdf_toc", view_func=lambda: pdf_toc(deps))
    app.add_url_rule("/api/doc_processing_status", endpoint="api_doc_processing_status", view_func=lambda: api_doc_processing_status(deps))

"""目录导入、偏移调整与视觉目录编辑相关路由服务函数。"""

from __future__ import annotations

from typing import Any

from flask import jsonify, request

from web.services import TocServices


Deps = TocServices


def _request_doc_id(deps: Deps) -> str:
    return deps["_request_doc_id"]()


def _target_pdf_page_from_book_page(book_page: int, offset: int, pages: list[dict]) -> int | None:
    for page in pages or []:
        try:
            pdf_page = int(page.get("bookPage") or 0)
        except (TypeError, ValueError):
            continue
        if pdf_page <= 0:
            continue
        print_label = str(page.get("printPageLabel") or page.get("printPage") or "").strip()
        if print_label and print_label.isdigit() and int(print_label) == int(book_page):
            return pdf_page
    candidate = int(book_page) + int(offset or 0)
    if candidate > 0:
        return candidate
    return None


def api_toc_import(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "未上传文件"}), 400
    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"ok": False, "error": "未上传文件"}), 400
    try:
        new_items = deps["parse_toc_file"](uploaded)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "error": "文件解析失败，请检查格式"}), 400
    if not new_items:
        return jsonify({"ok": False, "error": "文件中未找到有效目录行（需含标题、深度、页码三列）"}), 400

    auto_toc = deps["load_auto_visual_toc_from_disk"](doc_id) or deps["load_pdf_toc_from_disk"](doc_id)
    pages, _src_name = deps["load_pages_from_disk"](doc_id)
    offset, matched_title = deps["_guess_toc_offset"](new_items, auto_toc, pages=pages)

    enriched_items: list[dict] = []
    for item in new_items:
        payload = dict(item or {})
        target_pdf_page = _target_pdf_page_from_book_page(int(payload.get("book_page") or 0), offset, pages)
        if target_pdf_page is not None:
            payload["target_pdf_page"] = int(target_pdf_page)
        enriched_items.append(payload)

    deps["save_user_toc_to_disk"](doc_id, enriched_items)
    deps["save_toc_source_offset"](doc_id, "user", offset)
    try:
        uploaded.seek(0)
        deps["save_toc_file"](doc_id, uploaded)
    except Exception:
        deps["logger"].warning("TOC 文件持久化失败 doc_id=%s", doc_id)

    return jsonify({
        "ok": True,
        "imported": len(enriched_items),
        "offset": offset,
        "offset_matched_title": matched_title,
        "offset_auto": bool(matched_title),
        "toc_file": deps["get_toc_file_info"](doc_id),
    })


def api_toc_update_user(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    source, current_offset, _ = deps["load_effective_toc"](doc_id)
    if source != deps["TOC_SOURCE_USER"]:
        return jsonify({"ok": False, "error": "当前生效目录不是用户目录，无法在此保存"}), 400
    data = request.get_json(silent=True) or {}
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({"ok": False, "error": "缺少目录行"}), 400
    try:
        offset = int(data.get("offset", current_offset))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "offset 必须为整数"}), 400

    pages, _src_name = deps["load_pages_from_disk"](doc_id)
    normalized: list[dict] = []
    for raw in raw_items:
        title = str((raw or {}).get("title", "") or "").strip()
        if not title:
            return jsonify({"ok": False, "error": "目录标题不能为空"}), 400
        try:
            depth = int((raw or {}).get("depth", 0))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "深度必须为整数"}), 400
        if depth < 0:
            return jsonify({"ok": False, "error": "深度不能小于 0"}), 400
        raw_pdf = (raw or {}).get("pdf_page", None)
        target_pdf_page = None
        if raw_pdf is not None and raw_pdf != "":
            try:
                pdf_page = int(raw_pdf)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "PDF 页码必须为整数"}), 400
            if pdf_page < 1:
                return jsonify({"ok": False, "error": "PDF 页码必须大于等于 1"}), 400
            book_page = int(pdf_page) - int(offset)
            if book_page < 1:
                return jsonify({
                    "ok": False,
                    "error": f"在该 offset（{int(offset)}）下，PDF 第 {pdf_page} 页对应原书页码将小于 1，请提高 PDF 页码或调整 offset",
                }), 400
            target_pdf_page = int(pdf_page)
        else:
            try:
                book_page = int((raw or {}).get("book_page", 0))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "原书页码必须为整数"}), 400
            if book_page < 1:
                return jsonify({"ok": False, "error": "原书页码必须大于等于 1"}), 400
            target_pdf_page = _target_pdf_page_from_book_page(book_page, int(offset), pages)
        row = {"title": title, "depth": depth, "book_page": book_page}
        if target_pdf_page is not None:
            row["target_pdf_page"] = int(target_pdf_page)
        normalized.append(row)

    deps["save_user_toc_to_disk"](doc_id, normalized)
    deps["save_toc_source_offset"](doc_id, "user", int(offset))
    deps["save_user_toc_csv_generated"](doc_id, normalized)
    _source, _offset, toc = deps["load_effective_toc"](doc_id)
    return jsonify({
        "ok": True,
        "updated": len(normalized),
        "offset": int(offset),
        "toc": toc,
    })


def api_toc_set_offset(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    data = request.get_json(silent=True) or {}
    try:
        offset = int(data.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "offset 必须为整数"}), 400
    source, _current_offset, _toc = deps["load_effective_toc"](doc_id)
    deps["save_toc_source_offset"](doc_id, source, offset)
    return jsonify({"ok": True, "offset": offset, "source": source})


def api_toc_resolve_visual_item(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    data = request.get_json(silent=True) or {}
    item_id = str(data.get("item_id", "") or "").strip()
    if not item_id:
        return jsonify({"ok": False, "error": "缺少目录项 ID"}), 400
    try:
        pdf_page = int(data.get("pdf_page", 0))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "PDF 页码必须为整数"}), 400
    if pdf_page < 1:
        return jsonify({"ok": False, "error": "PDF 页码必须大于等于 1"}), 400

    pages, _src_name = deps["load_pages_from_disk"](doc_id)
    page_lookup = {
        int(page.get("bookPage")): page
        for page in pages
        if page.get("bookPage") is not None
    }
    target_page = page_lookup.get(pdf_page)
    if not target_page:
        return jsonify({"ok": False, "error": "未找到该 PDF 页码"}), 400

    visual_toc = deps["load_auto_visual_toc_from_disk"](doc_id)
    updated_items = []
    matched = False
    target_file_idx = int(target_page.get("fileIdx"))
    for item in visual_toc:
        clone = dict(item)
        if str(clone.get("item_id", "") or "").strip() == item_id:
            clone["file_idx"] = target_file_idx
            clone["target_pdf_page"] = int(pdf_page)
            clone["resolved_by_user"] = True
            clone["resolution_source"] = "manual_pdf_page"
            matched = True
        updated_items.append(clone)
    if not matched:
        return jsonify({"ok": False, "error": "未找到待补录的目录项"}), 404

    deps["save_auto_visual_toc_to_disk"](doc_id, updated_items)
    unresolved_count = sum(1 for item in updated_items if item.get("file_idx") is None)
    if unresolved_count > 0:
        deps["update_doc_meta"](
            doc_id,
            toc_visual_status="needs_offset",
            toc_visual_message=f"已识别 {len(updated_items)} 条目录，但仍有 {unresolved_count} 条无法稳定定位到 PDF 页。",
        )
    return jsonify({"ok": True, "item_id": item_id, "pdf_page": pdf_page, "file_idx": target_file_idx})


def api_toc_update_auto_visual(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    data = request.get_json(silent=True) or {}
    submitted_items = data.get("items")
    if not isinstance(submitted_items, list):
        return jsonify({"ok": False, "error": "缺少目录项数据"}), 400

    visual_toc = deps["load_auto_visual_toc_from_disk"](doc_id)
    updated_items, unresolved_count, err = deps["_merge_auto_visual_submission"](doc_id, submitted_items, visual_toc)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    deps["save_auto_visual_toc_to_disk"](doc_id, updated_items)
    if unresolved_count > 0:
        deps["update_doc_meta"](
            doc_id,
            toc_visual_status="needs_offset",
            toc_visual_message=f"已识别 {len(updated_items)} 条目录，但仍有 {unresolved_count} 条无法稳定定位到 PDF 页。",
        )
    else:
        deps["update_doc_meta"](
            doc_id,
            toc_visual_status="ready",
            toc_visual_message=f"已保存 {len(updated_items)} 条自动视觉目录调整。",
        )
    return jsonify({
        "ok": True,
        "updated": len(updated_items),
        "unresolved": unresolved_count,
        "auto_visual_toc": deps["_build_auto_visual_toc_editor_payload"](doc_id),
    })


def api_toc_save_visual_draft(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    data = request.get_json(silent=True) or {}
    submitted_items = data.get("items")
    if not isinstance(submitted_items, list):
        return jsonify({"ok": False, "error": "缺少目录项数据"}), 400
    try:
        pending_offset = int(data.get("pending_offset", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "pending_offset 必须为整数"}), 400

    base = deps["_visual_toc_base_for_draft_merge"](doc_id)
    updated_items, unresolved_count, err = deps["_merge_auto_visual_submission"](doc_id, submitted_items, base)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    deps["save_toc_visual_draft"](doc_id, updated_items, pending_offset)
    return jsonify({
        "ok": True,
        "saved": len(updated_items),
        "unresolved": unresolved_count,
        "auto_visual_toc": deps["_build_auto_visual_toc_editor_payload_from_items"](doc_id, updated_items),
        "has_toc_draft": True,
        "draft_pending_offset": pending_offset,
    })


def api_toc_commit_visual_draft(deps: Deps):
    doc_id = _request_doc_id(deps)
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    draft_bundle = deps["load_toc_visual_draft"](doc_id)
    if not draft_bundle:
        return jsonify({"ok": False, "error": "暂无草稿，请先保存草稿"}), 400
    items, draft_offset = draft_bundle
    data = request.get_json(silent=True) or {}
    try:
        final_offset = int(data.get("pending_offset", draft_offset))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "pending_offset 必须为整数"}), 400

    pages, _src_name = deps["load_pages_from_disk"](doc_id)
    _bp_by_pdf, pdf_page_by_file_idx = deps["_build_pdf_page_lookup"](pages)
    user_rows = deps["_visual_items_to_user_rows"](items, final_offset, pdf_page_by_file_idx)
    if not user_rows:
        return jsonify({"ok": False, "error": "没有可提交的目录行"}), 400

    deps["save_user_toc_to_disk"](doc_id, user_rows)
    deps["save_toc_source_offset"](doc_id, "user", final_offset)
    deps["save_user_toc_csv_generated"](doc_id, user_rows)
    deps["save_auto_visual_toc_to_disk"](doc_id, list(items))
    deps["clear_toc_visual_draft"](doc_id)
    return jsonify({
        "ok": True,
        "committed": len(user_rows),
        "offset": final_offset,
        "source": "user",
    })


def register_toc_routes(app, deps: Deps) -> None:
    app.add_url_rule("/api/toc/import", endpoint="api_toc_import", view_func=lambda: api_toc_import(deps), methods=["POST"])
    app.add_url_rule("/api/toc/update_user", endpoint="api_toc_update_user", view_func=lambda: api_toc_update_user(deps), methods=["POST"])
    app.add_url_rule("/api/toc/set_offset", endpoint="api_toc_set_offset", view_func=lambda: api_toc_set_offset(deps), methods=["POST"])
    app.add_url_rule("/api/toc/resolve_visual_item", endpoint="api_toc_resolve_visual_item", view_func=lambda: api_toc_resolve_visual_item(deps), methods=["POST"])
    app.add_url_rule("/api/toc/update_auto_visual", endpoint="api_toc_update_auto_visual", view_func=lambda: api_toc_update_auto_visual(deps), methods=["POST"])
    app.add_url_rule("/api/toc/save_visual_draft", endpoint="api_toc_save_visual_draft", view_func=lambda: api_toc_save_visual_draft(deps), methods=["POST"])
    app.add_url_rule("/api/toc/commit_visual_draft", endpoint="api_toc_commit_visual_draft", view_func=lambda: api_toc_commit_visual_draft(deps), methods=["POST"])

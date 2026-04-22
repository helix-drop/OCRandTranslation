"""整页编辑 API 路由。"""

from __future__ import annotations

from flask import jsonify, request

from web.services import PageEditorServices


Deps = PageEditorServices


def api_page_editor(deps: Deps):
    doc_id = deps["_request_doc_id"]()
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    request_payload = request.get_json(silent=True) if request.method == "POST" else {}
    view = deps["_normalize_reading_view"]((request_payload or {}).get("view") or request.values.get("view", "standard"))
    if view == "fnm":
        return jsonify({"ok": False, "error": "fnm_read_only", "message": "FNM 诊断页为只读视图，不支持整页编辑。"}), 403
    if request.method == "GET":
        try:
            bp = int(request.args.get("bp", 0))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "无效页码"}), 400
        payload = deps["build_page_editor_payload"](doc_id, bp, view=view)
        if not payload:
            return jsonify({"ok": False, "error": "当前页还没有可编辑内容"}), 404
        return jsonify({"ok": True, **payload})

    payload = request_payload or {}
    try:
        bp = int(payload.get("bp", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "无效页码"}), 400
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return jsonify({"ok": False, "error": "缺少有效段落数据"}), 400
    base_updated_at = payload.get("base_updated_at")
    try:
        saved = deps["save_page_editor_rows"](
            doc_id,
            bp,
            rows,
            view=view,
            base_updated_at=int(base_updated_at) if base_updated_at is not None else None,
        )
        return jsonify({"ok": True, **saved})
    except RuntimeError as exc:
        server_payload = deps["build_page_editor_payload"](doc_id, bp, view=view) or {}
        return jsonify({
            "ok": False,
            "error": str(exc),
            "server_page": server_payload.get("page"),
            "server_rows": server_payload.get("rows") or [],
        }), 409
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def api_page_editor_history(deps: Deps):
    doc_id = deps["_request_doc_id"]()
    if not doc_id:
        return jsonify({"ok": False, "error": "缺少文档 ID"}), 400
    view = deps["_normalize_reading_view"](request.args.get("view", "standard"))
    if view == "fnm":
        return jsonify({"ok": False, "error": "fnm_read_only", "message": "FNM 诊断页为只读视图，不支持编辑历史。"}), 403
    try:
        bp = int(request.args.get("bp", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "无效页码"}), 400
    revisions = deps["list_page_editor_revisions"](doc_id, bp, view=view)
    return jsonify({"ok": True, "doc_id": doc_id, "bp": bp, "revisions": revisions})


def register_page_editor_routes(app, deps: Deps) -> None:
    app.add_url_rule("/api/page_editor", endpoint="api_page_editor", view_func=lambda: api_page_editor(deps), methods=["GET", "POST"])
    app.add_url_rule("/api/page_editor/history", endpoint="api_page_editor_history", view_func=lambda: api_page_editor_history(deps))

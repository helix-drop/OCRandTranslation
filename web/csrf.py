"""CSRF token 注入与校验。"""

from __future__ import annotations

import secrets

from flask import Response, jsonify, request, session


JSON_CSRF_ENDPOINTS = {
    "api_glossary_create",
    "api_glossary_update",
    "api_glossary_delete",
    "api_upload_preferences",
    "upload_file",
    "reparse",
    "reparse_page",
    "save_manual_original",
    "save_manual_revision",
    "start_translate_all",
    "api_doc_fnm_translate",
    "start_glossary_retranslate",
    "stop_translate",
}


def ensure_csrf_token() -> str:
    token = session.get("_csrf_token", "").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def inject_csrf_token():
    return {"csrf_token": ensure_csrf_token()}


def should_return_json_for_csrf_failure() -> bool:
    if request.endpoint in JSON_CSRF_ENDPOINTS:
        return True
    if request.path.startswith("/api/"):
        return True
    return bool(request.is_json)


def csrf_token_is_valid() -> bool:
    session_token = session.get("_csrf_token", "").strip()
    if not session_token:
        return False
    request_token = request.form.get("_csrf_token", "").strip()
    header_token = request.headers.get("X-CSRF-Token", "").strip()
    provided_token = request_token or header_token
    if not provided_token:
        return False
    return secrets.compare_digest(session_token, provided_token)


def verify_csrf_for_unsafe_methods():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if request.endpoint is None:
        return None
    if csrf_token_is_valid():
        return None
    message = "CSRF 校验失败"
    if should_return_json_for_csrf_failure():
        return jsonify({"ok": False, "error": "csrf_failed", "message": message}), 403
    return Response(message, status=403, mimetype="text/plain")


def register_csrf(app) -> None:
    app.context_processor(inject_csrf_token)
    app.before_request(verify_csrf_for_unsafe_methods)

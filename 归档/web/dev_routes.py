"""FNM 开发者模式路由。

仅在 app.debug=True 或环境变量 FNM_DEV_MODE=1 时注册。
"""
from __future__ import annotations

import json
import os
import time

from flask import Flask, jsonify, render_template, request, send_file

from FNM_RE.dev.artifact_lookup import LookupError, lookup_artifact
from FNM_RE.dev.diagnostics import build_phase_diagnostics
from FNM_RE.dev.importer import import_doc_for_dev
from FNM_RE.dev.phase_runner import SUPPORTED_PHASES, launch_phase, safe_chapter_slug
from FNM_RE.dev.reset import reset_from_phase
from FNM_RE.dev.thread_pool import get_default_pool


DEV_MODE_ENV = "FNM_DEV_MODE"


def is_dev_mode_enabled(app: Flask) -> bool:
    if app.debug:
        return True
    flag = os.environ.get(DEV_MODE_ENV, "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def register_dev_routes(app: Flask) -> None:
    """条件注册开发者模式路由。"""
    if not is_dev_mode_enabled(app):
        return

    # 延迟 import，避免非 dev 环境加载
    from config import get_doc_dir
    from persistence.sqlite_store import SQLiteRepository
    from persistence.storage import load_pages_from_disk

    repo = SQLiteRepository()

    def _page():
        return render_template("dev/fnm_home.html")

    def _book_page(doc_id: str):
        doc_id = (doc_id or "").strip()
        return render_template("dev/fnm_book.html", doc_id=doc_id)

    def _api_import():
        payload = request.get_json(silent=True) or {}
        doc_id = str(payload.get("doc_id") or "").strip()
        if not doc_id:
            return jsonify({"ok": False, "error": "doc_id 不能为空"}), 400
        result = import_doc_for_dev(
            doc_id,
            repo=repo,
            get_doc_dir=get_doc_dir,
            load_pages_from_disk=load_pages_from_disk,
        )
        status = 200 if result.ok else 400
        return jsonify(result.to_dict()), status

    def _api_book_status(doc_id: str):
        doc_id = (doc_id or "").strip()
        if not doc_id:
            return jsonify({"ok": False, "error": "doc_id 不能为空"}), 400
        phase_runs = repo.list_phase_runs(doc_id)
        # 为每条 run 的 gate_report.failures/warnings 预注入 evidence_refs，
        # 前端无需再逐阶段轮询 /diagnostics。
        for run in phase_runs or []:
            diag = build_phase_diagnostics(run)
            gate_report = run.get("gate_report") or {}
            gate_report["failures"] = diag.get("failures", [])
            gate_report["warnings"] = diag.get("warnings", [])
            run["gate_report"] = gate_report
        return jsonify({"ok": True, "doc_id": doc_id, "phase_runs": phase_runs})

    def _api_books():
        docs = repo.list_documents() or []
        out = []
        for doc in docs:
            doc_id = doc.get("id") or doc.get("doc_id")
            if not doc_id:
                continue
            out.append(
                {
                    "doc_id": doc_id,
                    "name": doc.get("name"),
                    "updated_at": doc.get("updated_at"),
                    "phase_runs": repo.list_phase_runs(doc_id),
                }
            )
        return jsonify({"ok": True, "books": out})

    app.add_url_rule("/dev/fnm", "dev_fnm_home", _page, methods=["GET"])
    app.add_url_rule(
        "/dev/fnm/book/<doc_id>",
        "dev_fnm_book_page",
        _book_page,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/dev/fnm/import",
        "dev_fnm_import",
        _api_import,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/dev/fnm/books",
        "dev_fnm_books",
        _api_books,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/dev/fnm/book/<doc_id>/status",
        "dev_fnm_book_status",
        _api_book_status,
        methods=["GET"],
    )

    thread_pool = get_default_pool()

    def _api_phase_run(doc_id: str, phase: int):
        doc_id = (doc_id or "").strip()
        if not doc_id:
            return jsonify({"ok": False, "error": "doc_id 不能为空"}), 400
        try:
            phase_n = int(phase)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": f"非法 phase: {phase}"}), 400
        if phase_n not in SUPPORTED_PHASES:
            return (
                jsonify(
                    {
                        "ok": False,
                        "doc_id": doc_id,
                        "phase": phase_n,
                        "error": f"phase {phase_n} 暂未接入开发模式执行器",
                    }
                ),
                501,
            )
        payload = request.get_json(silent=True) or {}
        force_skip = bool(payload.get("force_skip"))
        execution_mode = str(payload.get("execution_mode") or "real").strip().lower()
        if execution_mode not in ("test", "real"):
            execution_mode = "real"
        result = launch_phase(
            doc_id,
            phase_n,
            repo=repo,
            pool=thread_pool,
            load_pages_from_disk=load_pages_from_disk,
            execution_mode=execution_mode,
            force_skip=force_skip,
        )
        if result.status == "busy":
            return jsonify(result.to_dict()), 409
        status_code = 202 if result.ok else 400
        return jsonify(result.to_dict()), status_code

    def _api_phase_reset(doc_id: str, phase: int):
        doc_id = (doc_id or "").strip()
        if not doc_id:
            return jsonify({"ok": False, "error": "doc_id 不能为空"}), 400
        try:
            phase_n = int(phase)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": f"非法 phase: {phase}"}), 400
        if thread_pool.is_busy(doc_id):
            return (
                jsonify(
                    {
                        "ok": False,
                        "doc_id": doc_id,
                        "phase_from": phase_n,
                        "error": "doc 正在跑任务，等结束后再 reset",
                        "status": "busy",
                    }
                ),
                409,
            )
        result = reset_from_phase(
            doc_id,
            phase_n,
            repo=repo,
            get_doc_dir=get_doc_dir,
        )
        status_code = 200 if result.ok else 400
        return jsonify(result.to_dict()), status_code

    app.add_url_rule(
        "/api/dev/fnm/book/<doc_id>/phase/<int:phase>/run",
        "dev_fnm_phase_run",
        _api_phase_run,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/dev/fnm/book/<doc_id>/phase/<int:phase>/reset",
        "dev_fnm_phase_reset",
        _api_phase_reset,
        methods=["POST"],
    )

    def _api_phase_diagnostics(doc_id: str, phase: int):
        doc_id = (doc_id or "").strip()
        if not doc_id:
            return jsonify({"ok": False, "error": "doc_id 不能为空"}), 400
        try:
            phase_n = int(phase)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": f"非法 phase: {phase}"}), 400
        phase_run = repo.get_phase_run(doc_id, phase_n)
        payload = build_phase_diagnostics(phase_run)
        payload["ok"] = True
        payload["doc_id"] = doc_id
        payload["phase"] = phase_n
        return jsonify(payload)

    app.add_url_rule(
        "/api/dev/fnm/book/<doc_id>/phase/<int:phase>/diagnostics",
        "dev_fnm_phase_diagnostics",
        _api_phase_diagnostics,
        methods=["GET"],
    )

    def _api_artifact_row(doc_id: str, phase: int, table: str):
        doc_id = (doc_id or "").strip()
        if not doc_id:
            return jsonify({"ok": False, "error": "doc_id 不能为空"}), 400
        row_key = (request.args.get("row_key") or "").strip()
        row_value = request.args.get("row_value")
        if not row_key or row_value is None:
            return (
                jsonify(
                    {"ok": False, "error": "缺少 row_key 或 row_value 查询参数"}
                ),
                400,
            )
        try:
            payload = lookup_artifact(repo, doc_id, table, row_key, row_value)
        except LookupError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        payload["doc_id"] = doc_id
        payload["phase"] = int(phase)
        return jsonify(payload)

    app.add_url_rule(
        "/api/dev/fnm/book/<doc_id>/artifact/<int:phase>/<table>",
        "dev_fnm_artifact_row",
        _api_artifact_row,
        methods=["GET"],
    )

    def _api_pdf(doc_id: str):
        doc_id = (doc_id or "").strip()
        if not doc_id:
            return jsonify({"ok": False, "error": "doc_id 不能为空"}), 400
        doc_dir = get_doc_dir(doc_id)
        pdf_path = os.path.join(doc_dir, "source.pdf")
        if not os.path.isfile(pdf_path):
            return jsonify({"ok": False, "error": "source.pdf 不存在"}), 404
        # Flask 的 send_file 默认 conditional=True，会处理 Range 请求
        return send_file(pdf_path, mimetype="application/pdf", conditional=True)

    app.add_url_rule(
        "/api/dev/fnm/book/<doc_id>/pdf",
        "dev_fnm_pdf",
        _api_pdf,
        methods=["GET"],
    )

    def _api_export_fragment(doc_id: str, chapter_id: str):
        doc_id = (doc_id or "").strip()
        chapter_id_s = (chapter_id or "").strip()
        if not doc_id or not chapter_id_s:
            return jsonify({"ok": False, "error": "doc_id/chapter_id 不能为空"}), 400
        doc_dir = get_doc_dir(doc_id)
        safe = safe_chapter_slug(chapter_id_s)
        md_path = os.path.join(doc_dir, "dev_exports", f"{safe}.md")
        if not os.path.isfile(md_path):
            return jsonify(
                {
                    "ok": True,
                    "doc_id": doc_id,
                    "chapter_id": chapter_id_s,
                    "available": False,
                    "reason": "Phase 6 尚未执行或章节未导出",
                    "markdown": "",
                }
            )
        try:
            with open(md_path, "r", encoding="utf-8") as fh:
                markdown = fh.read()
        except OSError as exc:
            return jsonify({"ok": False, "error": f"读取失败: {exc}"}), 500
        return jsonify(
            {
                "ok": True,
                "doc_id": doc_id,
                "chapter_id": chapter_id_s,
                "available": True,
                "markdown": markdown,
            }
        )

    def _api_snapshot_create(doc_id: str, phase: int):
        doc_id = (doc_id or "").strip()
        if not doc_id:
            return jsonify({"ok": False, "error": "doc_id 不能为空"}), 400
        try:
            phase_n = int(phase)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": f"非法 phase: {phase}"}), 400
        phase_run = repo.get_phase_run(doc_id, phase_n)
        if not phase_run:
            return jsonify({"ok": False, "error": f"phase {phase_n} 无记录"}), 404
        payload = request.get_json(silent=True) or {}
        note = str(payload.get("note") or "").strip() or None

        doc_dir = get_doc_dir(doc_id)
        snap_dir = os.path.join(doc_dir, "dev_snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        ts = int(time.time())
        filename = f"phase{phase_n}_{ts}.json"
        abs_path = os.path.join(snap_dir, filename)
        rel_path = os.path.relpath(abs_path, doc_dir)

        snapshot_body = {
            "doc_id": doc_id,
            "phase": phase_n,
            "created_at": ts,
            "status": phase_run.get("status"),
            "gate_pass": phase_run.get("gate_pass"),
            "gate_report": phase_run.get("gate_report") or {},
            "errors": phase_run.get("errors") or [],
        }
        try:
            with open(abs_path, "w", encoding="utf-8") as fh:
                json.dump(snapshot_body, fh, ensure_ascii=False, indent=2)
            size_bytes = os.path.getsize(abs_path)
        except OSError as exc:
            return jsonify({"ok": False, "error": f"写入失败: {exc}"}), 500

        try:
            snap_id = repo.save_dev_snapshot(
                doc_id,
                phase_n,
                rel_path,
                size_bytes=size_bytes,
                note=note,
            )
        except Exception as exc:
            # DB 失败：清理已写入的 JSON，避免孤儿文件
            try:
                os.unlink(abs_path)
            except OSError:
                pass
            return jsonify({"ok": False, "error": f"快照入库失败: {exc}"}), 500
        return jsonify(
            {
                "ok": True,
                "doc_id": doc_id,
                "phase": phase_n,
                "snapshot_id": snap_id,
                "blob_path": rel_path,
                "size_bytes": size_bytes,
                "created_at": ts,
                "note": note,
            }
        )

    def _api_snapshot_list(doc_id: str, phase: int):
        doc_id = (doc_id or "").strip()
        if not doc_id:
            return jsonify({"ok": False, "error": "doc_id 不能为空"}), 400
        try:
            phase_n = int(phase)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": f"非法 phase: {phase}"}), 400
        rows = repo.list_dev_snapshots(doc_id, phase=phase_n)
        return jsonify({"ok": True, "doc_id": doc_id, "phase": phase_n, "snapshots": rows})

    app.add_url_rule(
        "/api/dev/fnm/book/<doc_id>/export-fragment/<chapter_id>",
        "dev_fnm_export_fragment",
        _api_export_fragment,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/dev/fnm/book/<doc_id>/phase/<int:phase>/snapshot",
        "dev_fnm_phase_snapshot_create",
        _api_snapshot_create,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/dev/fnm/book/<doc_id>/phase/<int:phase>/snapshots",
        "dev_fnm_phase_snapshot_list",
        _api_snapshot_list,
        methods=["GET"],
    )

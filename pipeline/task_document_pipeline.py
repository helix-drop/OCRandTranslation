"""OCR 文档处理与重解析流水线。"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

Deps = dict[str, Any]


def _task_push(deps: Deps, task_id: str, event_type: str, data: dict) -> None:
    deps["task_push"](task_id, event_type, data)


def _read_binary_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _run_ocr_parse(
    *,
    task_id: str,
    file_bytes: bytes,
    file_type: int,
    deps: Deps,
    start_label: str,
    done_label: str,
    progress_detail_prefix: str = "分片",
    done_log: str | None = None,
    empty_error: str,
    emit_parse_logs: bool,
) -> tuple[dict | None, list[str]]:
    _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 5, "label": start_label, "detail": ""})

    def on_ocr_progress(chunk_i, total_chunks):
        pct = 5 + (chunk_i / total_chunks) * 60
        payload = {
            "pct": pct,
            "label": f"OCR 解析中… ({chunk_i}/{total_chunks})",
            "detail": f"{progress_detail_prefix} {chunk_i}/{total_chunks}",
        }
        if done_log:
            payload["log"] = f"OCR 分片 {chunk_i}/{total_chunks} 完成"
        _task_push(task_id=task_id, deps=deps, event_type="progress", data=payload)

    result = deps["call_paddle_ocr_bytes"](
        file_bytes=file_bytes,
        token=deps["get_paddle_token"](),
        file_type=file_type,
        on_progress=on_ocr_progress,
    )

    _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 65, "label": done_label, "detail": ""})
    if done_log:
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": done_log})

    parsed = deps["parse_ocr"](result)
    if not parsed["pages"]:
        _task_push(task_id=task_id, deps=deps, event_type="error_msg", data={"error": empty_error})
        return None, []

    logs = list(parsed.get("log") or [])
    if emit_parse_logs:
        for log_message in logs:
            _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": log_message})
    return parsed, logs


def _merge_pdf_text_layers(
    *,
    task_id: str,
    file_bytes: bytes,
    parsed_pages: list[dict],
    deps: Deps,
    success_event_message: str,
    fallback_event_message: str,
    fallback_log_message: str,
    emit_combined_logs: bool,
    include_success_in_logs: bool,
    merge_progress_label: str | None = None,
) -> tuple[list[dict], list[str]]:
    _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 72, "label": "提取 PDF 文字层…", "detail": ""})
    pdf_pages = deps["extract_pdf_text"](file_bytes)
    if not pdf_pages:
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": fallback_event_message})
        return parsed_pages, [fallback_log_message]

    if merge_progress_label:
        _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 78, "label": merge_progress_label, "detail": ""})
    combined = deps["combine_sources"](parsed_pages, pdf_pages)
    pages = combined["pages"]
    logs = list(combined.get("log") or [])
    success_message = success_event_message.format(page_count=len(pdf_pages))
    _task_push(
        task_id=task_id,
        deps=deps,
        event_type="log",
        data={"msg": success_message, "cls": "success"},
    )
    if emit_combined_logs:
        for log_message in logs:
            _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": log_message, "cls": "success"})
    return pages, ([success_message] if include_success_in_logs else []) + logs


def _cleanup_and_scan_pages(
    *,
    task_id: str,
    pages: list[dict],
    cleanup_enabled: bool,
    deps: Deps,
    cleanup_end_pct: int = 90,
    emit_cleanup_logs: bool,
    note_scan_target_bps: set[int] | None = None,
) -> tuple[list[dict], list[str]]:
    if cleanup_enabled:
        _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 85, "label": "清理页眉页脚…", "detail": ""})
        cleanup_result = deps["clean_header_footer"](
            pages,
            on_progress=lambda phase, pct, detail: deps["push_cleanup_progress"](
                task_id,
                phase,
                pct,
                detail,
                start_pct=85,
                end_pct=cleanup_end_pct,
            ),
        )
        final_pages = deps["apply_cleanup_mode_to_pages"](
            cleanup_result["pages"],
            cleanup_enabled=True,
        )
        logs = list(cleanup_result.get("log") or [])
        if emit_cleanup_logs:
            for log_message in logs:
                _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": log_message})
    else:
        _task_push(
            task_id=task_id,
            deps=deps,
            event_type="progress",
            data={
                "pct": 85,
                "label": "跳过页眉页脚清理…",
                "detail": "快速模式：直接进入脚注/尾注检测",
            },
        )
        skip_log = "已跳过页眉页脚清理（快速模式）"
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": skip_log, "cls": "success"})
        logs = [skip_log]
        final_pages = deps["apply_cleanup_mode_to_pages"](
            pages,
            cleanup_enabled=False,
        )
    final_pages = deps["annotate_note_scans"](
        final_pages,
        target_bps=note_scan_target_bps,
    )
    return final_pages, logs


def _copy_uploaded_pdf(task_id: str, file_path: str, doc_id: str, deps: Deps) -> str:
    pdf_dest = os.path.join(deps["get_doc_dir"](doc_id), "source.pdf")
    try:
        import shutil

        shutil.copy2(file_path, pdf_dest)
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": "PDF 已保存供预览"})
    except Exception as exc:
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": f"PDF保存失败: {exc}"})
    return pdf_dest


def _task_toc_visual_uploads(task: dict | None) -> tuple[dict, list[dict]]:
    options = (task or {}).get("options") or {}
    pdf_upload = dict(options.get("toc_visual_pdf_upload") or {}) if isinstance(options.get("toc_visual_pdf_upload"), dict) else {}
    image_uploads = list(options.get("toc_visual_image_uploads") or []) if isinstance(options.get("toc_visual_image_uploads"), list) else []
    return pdf_upload, [dict(row) for row in image_uploads if isinstance(row, dict)]


def _persist_toc_visual_manual_inputs(*, task_id: str, doc_id: str, task: dict | None, deps: Deps) -> tuple[str, int]:
    pdf_upload, image_uploads = _task_toc_visual_uploads(task)
    if pdf_upload.get("path"):
        saved_path = deps["save_toc_visual_manual_pdf"](
            doc_id,
            str(pdf_upload.get("path") or ""),
            original_name=str(pdf_upload.get("filename") or ""),
        )
        if saved_path:
            _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": "已保存手动目录 PDF，自动视觉目录将优先使用该文件。", "cls": "success"})
            return "manual_pdf", 1
    if image_uploads:
        saved_paths = deps["save_toc_visual_manual_screenshots"](doc_id, image_uploads)
        if saved_paths:
            _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": f"已保存 {len(saved_paths)} 张手动目录截图，自动视觉目录将优先使用这些截图。", "cls": "success"})
            return "manual_images", len(saved_paths)
    return "", 0


def _cleanup_toc_visual_upload_temps(task: dict | None) -> None:
    pdf_upload, image_uploads = _task_toc_visual_uploads(task)
    temp_paths = []
    if pdf_upload.get("path"):
        temp_paths.append(str(pdf_upload.get("path") or ""))
    for row in image_uploads:
        if row.get("path"):
            temp_paths.append(str(row.get("path") or ""))
    for path in temp_paths:
        if not path:
            continue
        try:
            os.unlink(path)
        except OSError:
            pass


class _PathFileShim:
    """把磁盘临时文件包装成带 filename / read() 的 file-like 对象，
    复用 parse_glossary_file 这类原本接收 werkzeug FileStorage 的函数。"""

    def __init__(self, path: str, filename: str) -> None:
        self.filename = filename
        self._path = path

    def read(self) -> bytes:
        with open(self._path, "rb") as fh:
            return fh.read()


def _task_glossary_upload(task: dict | None) -> dict:
    options = (task or {}).get("options") or {}
    upload = options.get("glossary_upload")
    return dict(upload) if isinstance(upload, dict) else {}


def _persist_glossary_upload(*, task_id: str, doc_id: str, task: dict | None, deps: Deps) -> None:
    upload = _task_glossary_upload(task)
    path = str(upload.get("path") or "").strip()
    filename = str(upload.get("filename") or "").strip()
    if not path or not os.path.exists(path):
        return
    try:
        items = deps["parse_glossary_file"](_PathFileShim(path, filename))
    except ValueError as exc:
        msg = f"词典解析失败：{exc}"
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": msg, "cls": "warning"})
        return
    except Exception as exc:  # noqa: BLE001 - 失败只记录不阻塞主流程
        msg = f"词典解析失败：{exc}"
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": msg, "cls": "warning"})
        return
    if not items:
        _task_push(
            task_id=task_id,
            deps=deps,
            event_type="log",
            data={"msg": "词典文件未解析到有效词条，已跳过。", "cls": "warning"},
        )
        return
    deps["set_glossary"](items, doc_id=doc_id)
    _task_push(
        task_id=task_id,
        deps=deps,
        event_type="log",
        data={"msg": f"已导入词典 {len(items)} 条（来自「{filename or '上传文件'}」）", "cls": "success"},
    )


def _cleanup_glossary_upload_temp(task: dict | None) -> None:
    upload = _task_glossary_upload(task)
    path = str(upload.get("path") or "").strip()
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _save_pdf_toc(
    *,
    task_id: str,
    doc_id: str,
    file_bytes: bytes,
    deps: Deps,
) -> None:
    toc_items = deps["extract_pdf_toc"](file_bytes)
    if not toc_items:
        toc_items = deps["extract_pdf_toc_from_links"](file_bytes)
        if toc_items:
            _task_push(
                task_id=task_id,
                deps=deps,
                event_type="log",
                data={"msg": f"已从目录页超链接提取目录 ({len(toc_items)} 条)", "cls": "success"},
            )
    deps["save_auto_pdf_toc_to_disk"](doc_id, toc_items)
    if toc_items:
        _task_push(
            task_id=task_id,
            deps=deps,
            event_type="log",
            data={"msg": f"已提取 PDF 目录 ({len(toc_items)} 条)", "cls": "success"},
        )
    else:
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": "PDF 未检测到目录书签"})


def _run_required_visual_toc_before_fnm(
    *,
    task_id: str,
    doc_id: str,
    pdf_path: str,
    run_enabled: bool,
    required: bool,
    deps: Deps,
) -> dict:
    result_payload = {
        "ok": True,
        "status": "skipped",
        "count": 0,
        "message": "",
        "log_messages": [],
    }
    if not run_enabled:
        return result_payload
    if not pdf_path or not os.path.exists(pdf_path):
        error_msg = "FNM 模式缺少源 PDF，无法先生成自动视觉目录。"
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": error_msg, "cls": "warning"})
        result_payload.update({"ok": False if required else True, "status": "failed", "message": error_msg})
        result_payload["log_messages"].append(("ERROR", error_msg))
        return result_payload

    _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 96, "label": "自动视觉目录识别…", "detail": ""})
    start_msg = "FNM 模式：开始同步生成自动视觉目录。"
    _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": start_msg, "cls": "success"})
    result_payload["log_messages"].append(("INFO", start_msg))

    try:
        result = deps["run_auto_visual_toc_for_doc"](
            doc_id,
            pdf_path,
            model_spec=deps["resolve_visual_model_spec"](),
        ) or {}
    except Exception as exc:
        error_msg = f"自动视觉目录请求失败：{exc}"
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": error_msg, "cls": "warning"})
        result_payload.update({
            "ok": False if required else True,
            "status": "failed",
            "message": error_msg,
        })
        result_payload["log_messages"].append(("ERROR", error_msg))
        return result_payload
    status = str(result.get("status") or "").strip().lower() or "failed"
    count = int(result.get("count", 0) or 0)
    result_payload["status"] = status
    result_payload["count"] = count

    if status in {"ready", "needs_offset"} and count > 0:
        success_msg = f"自动视觉目录已就绪：状态 {status}，共 {count} 条目录项。"
        _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": success_msg, "cls": "success"})
        result_payload["message"] = success_msg
        result_payload["log_messages"].append(("INFO", success_msg))
        return result_payload

    error_msg = str(result.get("message") or "").strip()
    if not error_msg:
        if status == "unsupported":
            error_msg = "当前视觉模型不支持自动视觉目录，FNM 模式已停止。"
        elif count <= 0:
            error_msg = "自动视觉目录没有生成任何可用目录项，FNM 模式已停止。"
        else:
            error_msg = f"自动视觉目录未就绪（{status}），FNM 模式已停止。"
    _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": error_msg, "cls": "warning"})
    result_payload.update({"ok": False if required else True, "message": error_msg})
    result_payload["log_messages"].append(("ERROR", error_msg))
    return result_payload


def process_file(task_id: str, deps: Deps) -> None:
    """后台线程：执行 OCR 上传解析并推送任务事件。"""
    task = deps["get_task_record"](task_id)
    if not task:
        return

    file_path = task["file_path"]
    file_name = task["file_name"]
    file_type = task["file_type"]
    cleanup_enabled = deps["resolve_cleanup_headers_footers"](task)
    auto_visual_toc_enabled = deps["resolve_auto_visual_toc"](task)
    doc_id = ""
    log_relpath = ""

    try:
        file_bytes = _read_binary_file(file_path)
        all_logs: list[str] = []

        parsed, parse_logs = _run_ocr_parse(
            task_id=task_id,
            file_bytes=file_bytes,
            file_type=file_type,
            deps=deps,
            start_label="调用 PaddleOCR 解析版面…",
            done_label="解析 OCR 结果…",
            done_log="OCR API 调用完成",
            empty_error="解析失败：未获取到任何页面数据",
            emit_parse_logs=True,
        )
        if not parsed:
            return
        all_logs.extend(parse_logs)

        if file_type == 0 and not cleanup_enabled:
            merged_pages, merge_logs = _merge_pdf_text_layers(
                task_id=task_id,
                file_bytes=file_bytes,
                parsed_pages=parsed["pages"],
                deps=deps,
                success_event_message="检测到PDF文字层 ({page_count}页)",
                fallback_event_message="PDF无有效文字层，使用OCR文字",
                fallback_log_message="PDF无有效文字层，使用OCR文字",
                emit_combined_logs=True,
                include_success_in_logs=True,
                merge_progress_label="合并 PDF 文字与 OCR 布局…",
            )
            parsed["pages"] = merged_pages
            all_logs.extend(merge_logs)

        cleanup_enabled, auto_visual_toc_enabled, refreshed_option_logs = deps["refresh_upload_task_runtime_options"](
            task_id,
            cleanup_enabled=cleanup_enabled,
            auto_visual_toc_enabled=auto_visual_toc_enabled,
        )
        for option_log in refreshed_option_logs:
            _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": option_log, "cls": "success"})
            all_logs.append(option_log)

        if cleanup_enabled:
            final_pages = deps["apply_cleanup_mode_to_pages"](
                parsed["pages"],
                cleanup_enabled=False,
            )
            skip_msg = "FNM 模式：已跳过文字层合并/页眉页脚清理/注释扫描，直接进入 FNM 主线处理。"
            _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": skip_msg, "cls": "success"})
            all_logs.append(skip_msg)
        else:
            final_pages, cleanup_logs = _cleanup_and_scan_pages(
                task_id=task_id,
                pages=parsed["pages"],
                cleanup_enabled=cleanup_enabled,
                deps=deps,
                emit_cleanup_logs=True,
            )
            all_logs.extend(cleanup_logs)

        _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 90, "label": "保存数据…", "detail": ""})
        doc_id = deps["create_doc"](
            file_name,
            cleanup_headers_footers=cleanup_enabled,
            auto_visual_toc_enabled=auto_visual_toc_enabled,
        )

        manual_input_mode, _manual_input_count = _persist_toc_visual_manual_inputs(
            task_id=task_id,
            doc_id=doc_id,
            task=task,
            deps=deps,
        )
        if manual_input_mode:
            auto_visual_toc_enabled = True
            deps["update_doc_meta"](doc_id, auto_visual_toc_enabled=True)

        _persist_glossary_upload(
            task_id=task_id,
            doc_id=doc_id,
            task=task,
            deps=deps,
        )

        pdf_dest = ""
        if file_type == 0:
            pdf_dest = _copy_uploaded_pdf(task_id, file_path, doc_id, deps)
            _save_pdf_toc(
                task_id=task_id,
                doc_id=doc_id,
                file_bytes=file_bytes,
                deps=deps,
            )
        else:
            deps["save_auto_pdf_toc_to_disk"](doc_id, [])

        _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 95, "label": "保存数据…", "detail": ""})
        deps["save_pages_to_disk"](final_pages, file_name, doc_id)
        log_relpath = deps["create_doc_task_log"](doc_id, "ocr_upload", task_id=task_id)
        for log_line in all_logs:
            deps["append_doc_task_log"](doc_id, log_relpath, log_line)
        if cleanup_enabled or auto_visual_toc_enabled:
            visual_toc_result = _run_required_visual_toc_before_fnm(
                task_id=task_id,
                doc_id=doc_id,
                pdf_path=pdf_dest,
                run_enabled=True,
                required=cleanup_enabled,
                deps=deps,
            )
            for level, message in list(visual_toc_result.get("log_messages") or []):
                deps["append_doc_task_log"](doc_id, log_relpath, message, level=level)
                all_logs.append(message)
            if cleanup_enabled and not visual_toc_result.get("ok"):
                _task_push(task_id=task_id, deps=deps, event_type="error_msg", data={
                    "error": str(visual_toc_result.get("message") or "自动视觉目录失败"),
                    "doc_id": doc_id,
                    "log_relpath": log_relpath,
                })
                return
            if cleanup_enabled:
                fnm_result = deps["run_fnm_pipeline_for_doc"](task_id, doc_id) or {}
            else:
                fnm_result = {}
            for level, message in list(fnm_result.get("log_messages") or []):
                deps["append_doc_task_log"](doc_id, log_relpath, message, level=level)
                all_logs.append(message)
        else:
            fnm_result = {}

        visible_page_view = deps["build_visible_page_view"](final_pages)
        first, last = deps["get_page_range"](final_pages)
        start_bp = visible_page_view["first_visible_page"] or first
        route_mode = "fnm_progress" if cleanup_enabled else "standard"
        redirect_allowed = not cleanup_enabled
        redirect_message = ""
        if cleanup_enabled:
            redirect_allowed = False
            if fnm_result.get("fnm_available"):
                redirect_message = str(fnm_result.get("message") or "").strip() or "FNM 分类完成；请留在首页点击“开始翻译”，并在首页查看进度与阻塞信息。"
            else:
                redirect_message = str(fnm_result.get("message") or "").strip()
        else:
            redirect_message = "快速模式解析完成后将直接进入标准阅读视图，并自动开始普通翻译。"
            deps["append_doc_task_log"](doc_id, log_relpath, redirect_message)
        summary = f"解析完成！{len(final_pages)}页 (p.{first}-{last})"
        deps["append_doc_task_log"](doc_id, log_relpath, summary)
        if cleanup_enabled:
            if redirect_message:
                deps["append_doc_task_log"](doc_id, log_relpath, f"首页保留在 FNM 进度模式：{redirect_message}", level="INFO")
        _task_push(task_id=task_id, deps=deps, event_type="done", data={
            "summary": summary,
            "logs": all_logs,
            "doc_id": doc_id,
            "start_bp": start_bp,
            "route_mode": route_mode,
            "redirect_allowed": redirect_allowed,
            "redirect_message": redirect_message,
            "log_relpath": log_relpath,
        })
    except Exception as exc:
        logger.exception("文件解析失败 doc_id=%s task_id=%s", doc_id, task_id)
        error_msg = f"解析失败: {exc}"
        if doc_id:
            log_relpath = log_relpath or deps["create_doc_task_log"](doc_id, "ocr_upload", task_id=task_id)
            deps["append_doc_task_log"](doc_id, log_relpath, error_msg, level="ERROR")
        _task_push(task_id=task_id, deps=deps, event_type="error_msg", data={"error": error_msg, "doc_id": doc_id, "log_relpath": log_relpath})
    finally:
        _cleanup_toc_visual_upload_temps(task)
        _cleanup_glossary_upload_temp(task)
        try:
            os.unlink(file_path)
        except OSError:
            pass


def reparse_file(task_id: str, doc_id: str, deps: Deps) -> None:
    """后台线程：对已有文档重新执行 OCR 解析。"""
    task = deps["get_task_record"](task_id)
    if not task:
        return

    file_path = task["file_path"]
    file_name = task["file_name"]
    cleanup_enabled = deps["resolve_cleanup_headers_footers"](task, doc_id=doc_id)
    auto_visual_toc_enabled = deps["resolve_auto_visual_toc"](task, doc_id=doc_id)
    log_relpath = deps["create_doc_task_log"](doc_id, "ocr_reparse", task_id=task_id)

    try:
        file_bytes = _read_binary_file(file_path)
        all_logs: list[str] = []

        parsed, parse_logs = _run_ocr_parse(
            task_id=task_id,
            file_bytes=file_bytes,
            file_type=0,
            deps=deps,
            start_label="重新调用 PaddleOCR…",
            done_label="解析 OCR 结果…",
            empty_error="重新解析失败：未获取到页面数据",
            emit_parse_logs=False,
        )
        if not parsed:
            return
        all_logs.extend(parse_logs)

        merged_pages, merge_logs = _merge_pdf_text_layers(
            task_id=task_id,
            file_bytes=file_bytes,
            parsed_pages=parsed["pages"],
            deps=deps,
            success_event_message="检测到有效PDF文字层 ({page_count}页)",
            fallback_event_message="PDF无有效文字层（或文字层已损坏），使用OCR文字",
            fallback_log_message="PDF无有效文字层，使用OCR文字",
            emit_combined_logs=False,
            include_success_in_logs=False,
        )
        parsed["pages"] = merged_pages
        all_logs.extend(merge_logs)

        final_pages, cleanup_logs = _cleanup_and_scan_pages(
            task_id=task_id,
            pages=parsed["pages"],
            cleanup_enabled=cleanup_enabled,
            deps=deps,
            emit_cleanup_logs=False,
        )
        all_logs.extend(cleanup_logs)

        _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 95, "label": "保存数据…", "detail": ""})
        deps["save_pages_to_disk"](final_pages, file_name, doc_id)
        for log_line in all_logs:
            deps["append_doc_task_log"](doc_id, log_relpath, log_line)
        if cleanup_enabled:
            visual_toc_result = _run_required_visual_toc_before_fnm(
                task_id=task_id,
                doc_id=doc_id,
                pdf_path=file_path,
                run_enabled=True,
                required=True,
                deps=deps,
            )
            for level, message in list(visual_toc_result.get("log_messages") or []):
                deps["append_doc_task_log"](doc_id, log_relpath, message, level=level)
                all_logs.append(message)
            if not visual_toc_result.get("ok"):
                _task_push(task_id=task_id, deps=deps, event_type="error_msg", data={
                    "error": str(visual_toc_result.get("message") or "自动视觉目录失败"),
                    "doc_id": doc_id,
                    "log_relpath": log_relpath,
                })
                return
            fnm_result = deps["run_fnm_pipeline_for_doc"](task_id, doc_id) or {}
            for level, message in list(fnm_result.get("log_messages") or []):
                deps["append_doc_task_log"](doc_id, log_relpath, message, level=level)
                all_logs.append(message)
        toc_items = deps["extract_pdf_toc"](file_bytes) or deps["extract_pdf_toc_from_links"](file_bytes)
        deps["save_auto_pdf_toc_to_disk"](doc_id, toc_items)

        first, last = deps["get_page_range"](final_pages)
        summary = f"重新解析完成！{len(final_pages)}页 (p.{first}-{last})"
        deps["append_doc_task_log"](doc_id, log_relpath, summary)
        _task_push(task_id=task_id, deps=deps, event_type="done", data={"summary": summary, "logs": all_logs, "doc_id": doc_id, "log_relpath": log_relpath})
    except Exception as exc:
        logger.exception("文件重新解析失败 doc_id=%s task_id=%s", doc_id, task_id)
        error_msg = f"重新解析失败: {exc}"
        deps["append_doc_task_log"](doc_id, log_relpath, error_msg, level="ERROR")
        _task_push(task_id=task_id, deps=deps, event_type="error_msg", data={"error": error_msg, "doc_id": doc_id, "log_relpath": log_relpath})


def _replace_page(pages: list[dict], target_bp: int, new_page: dict) -> list[dict]:
    updated_pages = []
    for page in pages:
        if page["bookPage"] == target_bp:
            updated_pages.append(new_page)
        else:
            updated_pages.append(page)
    return updated_pages


def _resolve_retranslate_model_key(entries: list[dict], target_bp: int, models: dict) -> str:
    for entry in entries:
        if entry.get("_pageBP") == target_bp and entry.get("_model") in models:
            return entry.get("_model")
    return ""


def reparse_single_page(task_id: str, doc_id: str, target_bp: int, file_idx: int, deps: Deps) -> None:
    """后台线程：对单页重新执行 OCR 解析并自动重译。"""
    from document.pdf_extract import extract_single_page_pdf

    task = deps["get_task_record"](task_id)
    if not task:
        return

    pdf_path = task["file_path"]
    file_name = task["file_name"]
    cleanup_enabled = deps["resolve_cleanup_headers_footers"](task, doc_id=doc_id)
    log_relpath = deps["create_doc_task_log"](doc_id, "ocr_reparse_page", task_id=task_id)

    try:
        deps["append_doc_task_log"](doc_id, log_relpath, f"开始单页重解析：PDF 第{target_bp}页。")
        _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 5, "label": f"提取第 {target_bp} 页…", "detail": ""})
        single_page_bytes = extract_single_page_pdf(pdf_path, file_idx)
        if not single_page_bytes:
            error_msg = f"无法提取第 {target_bp} 页"
            deps["append_doc_task_log"](doc_id, log_relpath, error_msg, level="ERROR")
            _task_push(task_id=task_id, deps=deps, event_type="error_msg", data={"error": error_msg, "doc_id": doc_id, "log_relpath": log_relpath})
            return

        _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 30, "label": "调用 PaddleOCR 解析…", "detail": ""})
        result = deps["call_paddle_ocr_bytes"](
            file_bytes=single_page_bytes,
            token=deps["get_paddle_token"](),
            file_type=0,
        )

        _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 65, "label": "解析 OCR 结果…", "detail": ""})
        parsed = deps["parse_ocr"](result)
        if not parsed["pages"]:
            error_msg = "OCR 未返回页面数据"
            deps["append_doc_task_log"](doc_id, log_relpath, error_msg, level="ERROR")
            _task_push(task_id=task_id, deps=deps, event_type="error_msg", data={"error": error_msg, "doc_id": doc_id, "log_relpath": log_relpath})
            return

        new_page = dict(parsed["pages"][0])
        new_page["bookPage"] = target_bp
        new_page["fileIdx"] = file_idx

        _task_push(
            task_id=task_id,
            deps=deps,
            event_type="progress",
            data={
                "pct": 75,
                "label": "保留 OCR 文字…",
                "detail": "手动重解析会跳过 PDF 文字层",
            },
        )
        _task_push(
            task_id=task_id,
            deps=deps,
            event_type="log",
            data={"msg": "手动重解析模式：跳过 PDF 文字层，强制使用 OCR 文字", "cls": "success"},
        )
        new_page["textSource"] = "ocr"

        if cleanup_enabled:
            _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 85, "label": "清理页眉页脚…", "detail": ""})
            cleanup_result = deps["clean_header_footer"](
                [new_page],
                on_progress=lambda phase, pct, detail: deps["push_cleanup_progress"](
                    task_id,
                    phase,
                    pct,
                    detail,
                    start_pct=85,
                    end_pct=92,
                ),
            )
            new_page = deps["apply_cleanup_mode_to_pages"](
                cleanup_result["pages"],
                cleanup_enabled=True,
            )[0]
        else:
            _task_push(
                task_id=task_id,
                deps=deps,
                event_type="progress",
                data={
                    "pct": 85,
                    "label": "跳过页眉页脚清理…",
                    "detail": "快速模式：直接进入脚注/尾注检测",
                },
            )
            _task_push(task_id=task_id, deps=deps, event_type="log", data={"msg": "已跳过页眉页脚清理（快速模式）", "cls": "success"})
            new_page = deps["apply_cleanup_mode_to_pages"](
                [new_page],
                cleanup_enabled=False,
            )[0]

        _task_push(task_id=task_id, deps=deps, event_type="progress", data={"pct": 95, "label": "保存数据…", "detail": ""})
        existing_pages, _ = deps["load_pages_from_disk"](doc_id)
        updated_pages = _replace_page(existing_pages, target_bp, new_page)
        updated_pages = deps["annotate_note_scans"](
            updated_pages,
            target_bps={max(1, target_bp - 1), target_bp, target_bp + 1},
        )

        deps["save_pages_to_disk"](updated_pages, file_name, doc_id)
        if cleanup_enabled:
            deps["run_fnm_pipeline_for_doc"](task_id, doc_id)
        entries, doc_title, _ = deps["load_entries_from_disk"](doc_id, pages=updated_pages)
        entry_title = doc_title or file_name

        try:
            model_key = _resolve_retranslate_model_key(entries, target_bp, deps["MODELS"])
            model_key, translate_args = deps["get_active_translate_args"](model_key)
            if not translate_args["api_key"]:
                raise RuntimeError("缺少翻译 API Key，请先在设置中配置。")

            model_label = deps["MODELS"].get(model_key, {}).get("label", model_key)
            _task_push(
                task_id=task_id,
                deps=deps,
                event_type="progress",
                data={"pct": 97, "label": "自动重译本页…", "detail": f"使用 {model_label}"},
            )
            _task_push(
                task_id=task_id,
                deps=deps,
                event_type="log",
                data={"msg": f"开始自动重译第 {target_bp} 页（{model_label}）", "cls": "success"},
            )
            new_entry = deps["translate_page"](
                updated_pages,
                target_bp,
                model_key,
                translate_args,
                deps["get_glossary"](doc_id),
            )
            deps["save_entry_to_disk"](new_entry, entry_title, doc_id)
            deps["reconcile_translate_state_after_page_success"](doc_id, target_bp)
        except Exception as exc:
            deps["reconcile_translate_state_after_page_failure"](doc_id, target_bp, str(exc))
            deps["append_doc_task_log"](doc_id, log_relpath, f"第 {target_bp} 页自动重译失败：{exc}", level="ERROR")
            _task_push(
                task_id=task_id,
                deps=deps,
                event_type="error_msg",
                data={"error": f"第 {target_bp} 页 OCR 重解析已完成，但自动重译失败: {exc}", "doc_id": doc_id, "log_relpath": log_relpath},
            )
            return

        summary = f"第 {target_bp} 页 OCR 重解析并重译完成"
        deps["append_doc_task_log"](doc_id, log_relpath, summary)
        _task_push(task_id=task_id, deps=deps, event_type="done", data={"summary": summary, "bp": target_bp, "doc_id": doc_id, "log_relpath": log_relpath})
    except Exception as exc:
        error_msg = f"重新解析失败: {exc}"
        deps["append_doc_task_log"](doc_id, log_relpath, error_msg, level="ERROR")
        _task_push(task_id=task_id, deps=deps, event_type="error_msg", data={"error": error_msg, "doc_id": doc_id, "log_relpath": log_relpath})

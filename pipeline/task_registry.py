"""文档任务注册与 SSE 事件缓存入口。"""

from __future__ import annotations

import threading


_tasks = {}
_tasks_lock = threading.Lock()


def task_push(task_id: str, event_type: str, data: dict):
    if event_type == "log":
        message = ""
        if isinstance(data, dict):
            message = str(data.get("msg") or "").strip()
        if not message:
            return
        data = dict(data or {})
        data["msg"] = message
    with _tasks_lock:
        if task_id in _tasks:
            _tasks[task_id]["events"].append((event_type, data))


def get_task(task_id: str) -> dict | None:
    with _tasks_lock:
        return _tasks.get(task_id)


def create_task(
    task_id: str,
    file_path: str,
    file_name: str,
    file_type: int,
    options: dict | None = None,
):
    normalized_options = {}
    if isinstance(options, dict) and "clean_header_footer" in options:
        normalized_options["clean_header_footer"] = bool(options.get("clean_header_footer"))
    if isinstance(options, dict) and "auto_visual_toc" in options:
        normalized_options["auto_visual_toc"] = bool(options.get("auto_visual_toc"))
    if isinstance(options, dict) and isinstance(options.get("toc_visual_pdf_upload"), dict):
        upload = dict(options.get("toc_visual_pdf_upload") or {})
        normalized_options["toc_visual_pdf_upload"] = {
            "path": str(upload.get("path") or "").strip(),
            "filename": str(upload.get("filename") or "").strip(),
        }
    if isinstance(options, dict) and isinstance(options.get("toc_visual_image_uploads"), list):
        uploads = []
        for row in options.get("toc_visual_image_uploads") or []:
            if not isinstance(row, dict):
                continue
            uploads.append({
                "path": str(row.get("path") or "").strip(),
                "filename": str(row.get("filename") or "").strip(),
            })
        normalized_options["toc_visual_image_uploads"] = uploads
    if isinstance(options, dict) and isinstance(options.get("glossary_upload"), dict):
        glossary = dict(options.get("glossary_upload") or {})
        normalized_options["glossary_upload"] = {
            "path": str(glossary.get("path") or "").strip(),
            "filename": str(glossary.get("filename") or "").strip(),
        }
    with _tasks_lock:
        _tasks[task_id] = {
            "status": "pending",
            "events": [],
            "file_path": file_path,
            "file_name": file_name,
            "file_type": file_type,
            "options": normalized_options,
        }


def update_task_options(task_id: str, **updates) -> dict | None:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        options = dict(task.get("options") or {})
        options.update(updates)
        task["options"] = options
        return dict(task)


def get_task_events(task_id: str, cursor: int) -> tuple[list, bool]:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if not task:
            return [], False
        events = task["events"][cursor:]
        return events, True


def set_task_final(task_id: str, logs: list, summary: str):
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task:
            task["final_logs"] = logs
            task["summary"] = summary


def remove_task(task_id: str):
    with _tasks_lock:
        _tasks.pop(task_id, None)


__all__ = [
    "create_task",
    "get_task",
    "get_task_events",
    "remove_task",
    "set_task_final",
    "task_push",
    "update_task_options",
]

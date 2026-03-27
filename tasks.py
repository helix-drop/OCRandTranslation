"""后台任务：OCR 文件处理、页面翻译、连续翻译 worker。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import queue
import re
import tempfile
import threading
import time

import config as app_config
from config import (
    MODELS,
    get_paddle_token, get_glossary, get_model_key,
    create_doc, get_doc_dir,
)
from sqlite_store import SQLiteRepository
from ocr_client import call_paddle_ocr_bytes
from text_processing import (
    parse_ocr, clean_header_footer,
    extract_pdf_text, combine_sources,
    get_page_range, get_next_page_bp,
    get_page_context_for_translate,
    get_paragraph_bboxes,
)
from translator import (
    TranslateStreamAborted,
    stream_translate_paragraph,
    translate_paragraph,
    structure_page,
)
from storage import (
    save_pages_to_disk, load_pages_from_disk,
    save_entries_to_disk, save_entry_to_disk, load_entries_from_disk,
    save_pdf_toc_to_disk,
    get_translate_args, _ensure_str,
)
from pdf_extract import extract_pdf_toc


# ============ OCR TASK MANAGEMENT ============

_tasks = {}  # task_id -> {"status", "events": [], "file_path", "file_name", "file_type"}
_tasks_lock = threading.Lock()


def task_push(task_id: str, event_type: str, data: dict):
    with _tasks_lock:
        if task_id in _tasks:
            _tasks[task_id]["events"].append((event_type, data))


def get_task(task_id: str) -> dict | None:
    with _tasks_lock:
        return _tasks.get(task_id)


def create_task(task_id: str, file_path: str, file_name: str, file_type: int):
    with _tasks_lock:
        _tasks[task_id] = {
            "status": "pending",
            "events": [],
            "file_path": file_path,
            "file_name": file_name,
            "file_type": file_type,
        }


def get_task_events(task_id: str, cursor: int) -> tuple[list, bool]:
    """获取从 cursor 开始的事件，返回 (events, task_exists)。"""
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


def process_file(task_id: str):
    """Background thread: run OCR pipeline and push SSE events."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return

    file_path = task["file_path"]
    file_name = task["file_name"]
    file_type = task["file_type"]
    paddle_token = get_paddle_token()

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        all_logs = []

        # Step 1: OCR
        task_push(task_id, "progress", {"pct": 5, "label": "调用 PaddleOCR 解析版面…", "detail": ""})

        def on_ocr_progress(chunk_i, total_chunks):
            pct = 5 + (chunk_i / total_chunks) * 60
            task_push(task_id, "progress", {
                "pct": pct,
                "label": f"OCR 解析中… ({chunk_i}/{total_chunks})",
                "detail": f"分片 {chunk_i}/{total_chunks}",
                "log": f"OCR 分片 {chunk_i}/{total_chunks} 完成",
            })

        result = call_paddle_ocr_bytes(
            file_bytes=file_bytes,
            token=paddle_token,
            file_type=file_type,
            on_progress=on_ocr_progress,
        )

        task_push(task_id, "progress", {"pct": 65, "label": "解析 OCR 结果…", "detail": ""})
        task_push(task_id, "log", {"msg": "OCR API 调用完成"})

        parsed = parse_ocr(result)
        if not parsed["pages"]:
            task_push(task_id, "error_msg", {"error": "解析失败：未获取到任何页面数据"})
            return
        all_logs.extend(parsed["log"])
        for lg in parsed["log"]:
            task_push(task_id, "log", {"msg": lg})

        # Step 2: PDF text extraction
        if file_type == 0:
            task_push(task_id, "progress", {"pct": 72, "label": "提取 PDF 文字层…", "detail": ""})
            pdf_pages = extract_pdf_text(file_bytes)
            if pdf_pages:
                task_push(task_id, "log", {"msg": f"检测到PDF文字层 ({len(pdf_pages)}页)", "cls": "success"})
                all_logs.append(f"检测到PDF文字层 ({len(pdf_pages)}页)")

                task_push(task_id, "progress", {"pct": 78, "label": "合并 PDF 文字与 OCR 布局…", "detail": ""})
                combined = combine_sources(parsed["pages"], pdf_pages)
                parsed["pages"] = combined["pages"]
                all_logs.extend(combined["log"])
                for lg in combined["log"]:
                    task_push(task_id, "log", {"msg": lg, "cls": "success"})
            else:
                task_push(task_id, "log", {"msg": "PDF无有效文字层，使用OCR文字"})
                all_logs.append("PDF无有效文字层，使用OCR文字")

        # Step 3: Clean headers/footers
        task_push(task_id, "progress", {"pct": 85, "label": "清理页眉页脚…", "detail": ""})
        hf = clean_header_footer(parsed["pages"])
        final_pages = hf["pages"]
        all_logs.extend(hf["log"])
        for lg in hf["log"]:
            task_push(task_id, "log", {"msg": lg})

        # Step 4: 创建文档目录并保存
        task_push(task_id, "progress", {"pct": 90, "label": "保存数据…", "detail": ""})
        doc_id = create_doc(file_name)

        # 保存 PDF 副本供预览
        if file_type == 0:
            pdf_dest = os.path.join(get_doc_dir(doc_id), "source.pdf")
            try:
                import shutil
                shutil.copy2(file_path, pdf_dest)
                task_push(task_id, "log", {"msg": "PDF 已保存供预览"})
            except Exception as e:
                task_push(task_id, "log", {"msg": f"PDF保存失败: {e}"})
            toc_items = extract_pdf_toc(file_bytes)
            save_pdf_toc_to_disk(doc_id, toc_items)
            if toc_items:
                task_push(task_id, "log", {"msg": f"已提取 PDF 目录 ({len(toc_items)} 条)", "cls": "success"})
            else:
                task_push(task_id, "log", {"msg": "PDF 未检测到目录书签"})
        else:
            save_pdf_toc_to_disk(doc_id, [])

        # Step 5: Save pages data
        task_push(task_id, "progress", {"pct": 95, "label": "保存数据…", "detail": ""})
        save_pages_to_disk(final_pages, file_name, doc_id)

        first, last = get_page_range(final_pages)
        summary = f"解析完成！{len(final_pages)}页 (p.{first}-{last})"
        task_push(task_id, "done", {"summary": summary, "logs": all_logs})

    except Exception as e:
        task_push(task_id, "error_msg", {"error": f"解析失败: {e}"})
    finally:
        try:
            os.unlink(file_path)
        except OSError:
            pass


# ============ 翻译核心 ============

def _needs_llm_fix(paragraphs: list) -> bool:
    """判断程序化解析结果是否需要 LLM 修正。"""
    if not paragraphs:
        return True

    has_ref_heading = any(
        p["heading_level"] > 0 and re.search(r"^(References|Bibliography|Works Cited)", p["text"], re.I)
        for p in paragraphs
    )
    if has_ref_heading:
        return False

    body = [p for p in paragraphs if p["heading_level"] == 0]
    if body:
        ref_like = sum(1 for p in body if re.search(r"\(\d{4}[a-z]?\)", p["text"][:80]))
        if ref_like >= len(body) * 0.5:
            return False

    short_count = sum(1 for p in body if len(p["text"]) < 30)
    if short_count > 3:
        return True

    return False


def _llm_fix_paragraphs(paragraphs: list, page_md: str, t_args: dict, page_num: int) -> list:
    """用 LLM 修正有问题的段落结构。"""
    empty_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }
    try:
        fixed = structure_page(
            blocks=[],
            markdown=page_md,
            page_num=page_num,
            **t_args,
        )
        if fixed and fixed.get("paragraphs"):
            return fixed["paragraphs"], fixed.get("usage", empty_usage)
    except Exception:
        pass
    return paragraphs, empty_usage


def _merge_usage(base: dict, delta: dict | None) -> dict:
    usage = dict(base)
    if not delta:
        return usage
    usage["prompt_tokens"] = usage.get("prompt_tokens", 0) + int(delta.get("prompt_tokens", 0) or 0)
    usage["completion_tokens"] = usage.get("completion_tokens", 0) + int(delta.get("completion_tokens", 0) or 0)
    usage["total_tokens"] = usage.get("total_tokens", 0) + int(delta.get("total_tokens", 0) or 0)
    usage["request_count"] = usage.get("request_count", 0) + int(delta.get("request_count", 0) or 0)
    return usage


def _trim_para_context(text: str, limit: int = 200, from_end: bool = False) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[-limit:] if from_end else text[:limit]


def _get_para_context_window() -> int:
    try:
        return max(50, min(500, int(getattr(app_config, "PARA_CONTEXT_WINDOW", 200) or 200)))
    except Exception:
        return 200


def _get_para_max_concurrency() -> int:
    try:
        return max(1, min(3, int(getattr(app_config, "PARA_MAX_CONCURRENCY", 3) or 3)))
    except Exception:
        return 3


def _entry_has_paragraph_error(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    return any((pe.get("_status") == "error") for pe in entry.get("_page_entries", []))


def _collect_partial_failed_bps(doc_id: str, target_bps: list[int] | None = None) -> list[int]:
    if not doc_id:
        return []
    target_bp_set = set(target_bps) if target_bps else None
    entries, _, _ = load_entries_from_disk(doc_id)
    partial_failed = set()
    for entry in entries:
        bp = entry.get("_pageBP")
        if bp is None:
            continue
        bp = int(bp)
        if target_bp_set is not None and bp not in target_bp_set:
            continue
        if _entry_has_paragraph_error(entry):
            partial_failed.add(bp)
    return sorted(partial_failed)


def _extract_page_footnote_summary(page_entries: list[dict], fallback_footnotes: str = "") -> tuple[str, str]:
    page_footnotes = _ensure_str(fallback_footnotes).strip()
    page_footnotes_translation = ""
    for entry in page_entries:
        if not isinstance(entry, dict):
            continue
        if not page_footnotes:
            page_footnotes = _ensure_str(entry.get("footnotes", "")).strip()
        if not page_footnotes_translation:
            page_footnotes_translation = _ensure_str(entry.get("footnotes_translation", "")).strip()
        if page_footnotes and page_footnotes_translation:
            break
    return page_footnotes, page_footnotes_translation


def _build_para_jobs(paragraphs: list, ctx: dict, para_bboxes: list, target_bp: int, context_window: int = 200) -> list[dict]:
    jobs = []
    title_stack = []
    first_para_idx = next((idx for idx, para in enumerate(paragraphs) if para.get("text", "").strip()), None)
    first_body_idx = next((idx for idx, para in enumerate(paragraphs) if para.get("heading_level", 0) == 0 and para.get("text", "").strip()), None)
    footnote_owner_idx = first_body_idx if first_body_idx is not None else first_para_idx
    page_footnotes = _ensure_str(ctx.get("footnotes", "")).strip()

    for idx, para in enumerate(paragraphs):
        hlevel = int(para.get("heading_level", 0) or 0)
        text = para.get("text", "").strip()
        if not text:
            continue

        if hlevel > 0:
            while len(title_stack) >= hlevel:
                title_stack.pop()
            title_stack.append(text)

        prev_text = ""
        next_text = ""
        for prev_idx in range(idx - 1, -1, -1):
            prev_candidate = paragraphs[prev_idx].get("text", "").strip()
            if prev_candidate:
                prev_text = prev_candidate
                break
        for next_idx in range(idx + 1, len(paragraphs)):
            next_candidate = paragraphs[next_idx].get("text", "").strip()
            if next_candidate:
                next_text = next_candidate
                break

        cross = para.get("cross_page")
        if not prev_text and cross in ("cont_prev", "cont_both"):
            prev_text = ctx.get("prev_tail", "") or ""
        if not next_text and cross in ("cont_next", "cont_both", "merged_next"):
            next_text = ctx.get("next_head", "") or ""

        jobs.append({
            "para_idx": len(jobs),
            "source_idx": idx,
            "bp": target_bp,
            "heading_level": hlevel,
            "text": text,
            "cross_page": cross,
            "bboxes": para_bboxes[idx] if idx < len(para_bboxes) else [],
            "footnotes": page_footnotes if idx == footnote_owner_idx else "",
            "prev_context": "" if hlevel > 0 else _trim_para_context(prev_text, limit=context_window, from_end=True),
            "next_context": "" if hlevel > 0 else _trim_para_context(next_text, limit=context_window, from_end=False),
            "section_path": list(title_stack),
        })
    for job in jobs:
        job["para_total"] = len(jobs)
    return jobs


def _make_page_entry(job: dict, target_bp: int, result: dict | None = None, error: str = "") -> dict:
    result = result or {}
    is_error = bool(error)
    translation = f"[翻译失败: {error}]" if is_error else _ensure_str(result.get("translation", ""))
    result_footnotes = _ensure_str(result.get("footnotes", "")).strip()
    job_footnotes = _ensure_str(job.get("footnotes", "")).strip()
    footnotes = result_footnotes or job_footnotes
    footnotes_translation = _ensure_str(result.get("footnotes_translation", "")).strip()
    return {
        "original": _ensure_str(result.get("original", job["text"])),
        "translation": translation,
        "footnotes": footnotes,
        "footnotes_translation": footnotes_translation,
        "heading_level": job["heading_level"],
        "pages": str(target_bp),
        "_rawText": job["text"],
        "_startBP": target_bp,
        "_endBP": target_bp,
        "_cross_page": job["cross_page"],
        "_bboxes": job["bboxes"],
        "_status": "error" if is_error else "done",
        "_error": str(error) if is_error else "",
    }


def _count_finished_paragraphs(states: list[str]) -> int:
    return sum(1 for state in states if state in ("done", "error"))


def _primary_para_idx(active_indices: set[int], states: list[str]) -> int | None:
    if active_indices:
        return min(active_indices)
    for idx in range(len(states) - 1, -1, -1):
        if states[idx] in ("done", "error", "aborted"):
            return idx
    return None


def translate_page(pages, target_bp, model_key, t_args, glossary):
    """翻译指定页面：基于 markdown 解析段落，处理跨页，逐段翻译。"""
    total_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }

    ctx = get_page_context_for_translate(pages, target_bp)
    paragraphs = ctx["paragraphs"]

    if not paragraphs:
        raise RuntimeError(f"第{target_bp}页未找到内容")

    # LLM 修正层
    if _needs_llm_fix(paragraphs):
        cur = None
        for pg in pages:
            if pg["bookPage"] == target_bp:
                cur = pg
                break
        page_md = cur.get("markdown", "") if cur else ""
        if page_md:
            paragraphs, structure_usage = _llm_fix_paragraphs(paragraphs, page_md, t_args, target_bp)
            total_usage = _merge_usage(total_usage, structure_usage)

    para_bboxes = get_paragraph_bboxes(pages, target_bp, paragraphs)
    para_jobs = _build_para_jobs(paragraphs, ctx, para_bboxes, target_bp, context_window=_get_para_context_window())

    if not para_jobs:
        raise RuntimeError(f"第{target_bp}页未找到有效内容")

    # 段内并发翻译，和流式路径保持同一上限。
    results = [None] * len(para_jobs)
    max_parallel = min(_get_para_max_concurrency(), len(para_jobs))

    def _do_translate(job: dict):
        return job["para_idx"], translate_paragraph(
            para_text=job["text"],
            para_pages=str(target_bp),
            footnotes=job["footnotes"],
            glossary=glossary,
            heading_level=job["heading_level"],
            para_idx=job["para_idx"],
            para_total=job["para_total"],
            prev_context=job["prev_context"],
            next_context=job["next_context"],
            section_path=job["section_path"],
            cross_page=job["cross_page"],
            **t_args,
        )

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {
            pool.submit(_do_translate, job): job
            for job in para_jobs
        }
        for future in as_completed(futures):
            job = futures[future]
            try:
                _, p = future.result()
            except Exception as e:
                p = {"original": job["text"], "translation": f"[翻译失败: {e}]",
                     "footnotes": "", "footnotes_translation": ""}
            total_usage = _merge_usage(total_usage, p.get("_usage"))
            results[job["para_idx"]] = _make_page_entry(job, target_bp, result=p)

    page_entries = [r for r in results if r is not None]
    page_footnotes, page_footnotes_translation = _extract_page_footnote_summary(
        page_entries,
        fallback_footnotes=ctx.get("footnotes", ""),
    )

    return {
        "_pageBP": target_bp,
        "_model": model_key,
        "_usage": total_usage,
        "_page_entries": page_entries,
        "footnotes": page_footnotes,
        "footnotes_translation": page_footnotes_translation,
        "pages": str(target_bp),
    }


def translate_page_stream(pages, target_bp, model_key, t_args, glossary, doc_id: str, stop_checker=None):
    """流式翻译指定页面：段内有界并发推送增量，但仅在整页完成后返回 entry。"""
    total_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }

    ctx = get_page_context_for_translate(pages, target_bp)
    paragraphs = ctx["paragraphs"]
    if not paragraphs:
        raise RuntimeError(f"第{target_bp}页未找到内容")

    if _needs_llm_fix(paragraphs):
        cur = None
        for pg in pages:
            if pg["bookPage"] == target_bp:
                cur = pg
                break
        page_md = cur.get("markdown", "") if cur else ""
        if page_md:
            paragraphs, structure_usage = _llm_fix_paragraphs(paragraphs, page_md, t_args, target_bp)
            total_usage = _merge_usage(total_usage, structure_usage)

    para_bboxes = get_paragraph_bboxes(pages, target_bp, paragraphs)
    para_jobs = _build_para_jobs(paragraphs, ctx, para_bboxes, target_bp, context_window=_get_para_context_window())

    if not para_jobs:
        raise RuntimeError(f"第{target_bp}页未找到有效内容")

    max_parallel = min(_get_para_max_concurrency(), len(para_jobs))
    results = [None] * len(para_jobs)
    paragraph_texts = [""] * len(para_jobs)
    paragraph_states = ["pending"] * len(para_jobs)
    paragraph_errors = [""] * len(para_jobs)
    active_para_indices = set()
    event_queue: queue.Queue = queue.Queue()
    pending_jobs = list(para_jobs)
    running_count = 0
    aborted = False
    scheduled_para_indices = set()
    finished_para_indices = set()

    def _save_parallel_draft(status: str, note: str, last_error: str = ""):
        ordered_active = sorted(active_para_indices)
        _save_stream_draft(
            doc_id,
            active=bool(active_para_indices) and status == "streaming",
            bp=target_bp,
            para_idx=_primary_para_idx(active_para_indices, paragraph_states),
            para_total=len(para_jobs),
            para_done=_count_finished_paragraphs(paragraph_states),
            parallel_limit=max_parallel,
            active_para_indices=ordered_active,
            paragraph_states=list(paragraph_states),
            paragraph_errors=list(paragraph_errors),
            paragraphs=list(paragraph_texts),
            status=status,
            note=note,
            last_error=last_error,
        )

    def _worker_stream(job: dict):
        event_queue.put({"type": "start", "job": job})
        try:
            for event in stream_translate_paragraph(
                para_text=job["text"],
                para_pages=str(target_bp),
                footnotes=job["footnotes"],
                glossary=glossary,
                stop_checker=None,
                heading_level=job["heading_level"],
                para_idx=job["para_idx"],
                para_total=job["para_total"],
                prev_context=job["prev_context"],
                next_context=job["next_context"],
                section_path=job["section_path"],
                cross_page=job["cross_page"],
                **t_args,
            ):
                payload = {"type": event["type"], "job": job}
                payload.update({k: v for k, v in event.items() if k != "type"})
                event_queue.put(payload)
        except TranslateStreamAborted:
            event_queue.put({"type": "aborted", "job": job})
        except Exception as e:
            event_queue.put({"type": "error", "job": job, "error": str(e)})

    def _submit_next_job(pool: ThreadPoolExecutor) -> bool:
        nonlocal running_count
        if aborted or not pending_jobs:
            return False
        job = None
        while pending_jobs:
            candidate = pending_jobs.pop(0)
            para_idx = candidate["para_idx"]
            if para_idx in scheduled_para_indices or para_idx in finished_para_indices:
                continue
            job = candidate
            break
        if not job:
            return False
        scheduled_para_indices.add(job["para_idx"])
        pool.submit(_worker_stream, job)
        running_count += 1
        return True

    translate_push("stream_page_init", {
        "doc_id": doc_id,
        "bp": target_bp,
        "para_total": len(para_jobs),
        "parallel_limit": max_parallel,
    })
    _save_stream_draft(
        doc_id,
        active=True,
        bp=target_bp,
        para_idx=0 if para_jobs else None,
        para_total=len(para_jobs),
        para_done=0,
        parallel_limit=max_parallel,
        paragraphs=[""] * len(para_jobs),
        active_para_indices=[],
        paragraph_states=["pending"] * len(para_jobs),
        paragraph_errors=[""] * len(para_jobs),
        status="streaming",
        note="当前页正在流式翻译，完整结束后才会写入硬盘。",
        last_error="",
    )

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        for _ in range(max_parallel):
            if not _submit_next_job(pool):
                break

        while running_count > 0:
            event = event_queue.get()
            job = event["job"]
            para_idx = job["para_idx"]
            evt_type = event["type"]

            if evt_type == "start":
                active_para_indices.add(para_idx)
                paragraph_states[para_idx] = "running"
                paragraph_errors[para_idx] = ""
                translate_push("stream_para_start", {
                    "doc_id": doc_id,
                    "bp": target_bp,
                    "para_idx": para_idx,
                })
                _save_parallel_draft("streaming", "当前页尚未提交到硬盘；如请求停止，将在本页完成后停止。")
                continue

            if evt_type == "delta":
                delta_text = event.get("text", "")
                if delta_text:
                    paragraph_texts[para_idx] = event.get("translation_so_far", paragraph_texts[para_idx] + delta_text)
                    translate_push("stream_para_delta", {
                        "doc_id": doc_id,
                        "bp": target_bp,
                        "para_idx": para_idx,
                        "delta": delta_text,
                        "translation_so_far": paragraph_texts[para_idx],
                    })
                    _save_parallel_draft("streaming", "当前页尚未提交到硬盘；如请求停止，将在本页完成后停止。")
                continue

            if evt_type == "usage":
                total_usage = _merge_usage(total_usage, event.get("usage"))
                translate_push("stream_usage", {
                    "doc_id": doc_id,
                    "bp": target_bp,
                    "para_idx": para_idx,
                    "usage": event.get("usage", {}),
                })
                continue

            running_count = max(0, running_count - 1)
            active_para_indices.discard(para_idx)
            finished_para_indices.add(para_idx)

            if evt_type == "done":
                p = event["result"]
                results[para_idx] = _make_page_entry(job, target_bp, result=p)
                paragraph_texts[para_idx] = _ensure_str(p.get("translation", ""))
                paragraph_states[para_idx] = "done"
                paragraph_errors[para_idx] = ""
                translate_push("stream_para_done", {
                    "doc_id": doc_id,
                    "bp": target_bp,
                    "para_idx": para_idx,
                    "translation": paragraph_texts[para_idx],
                })
                _save_parallel_draft("streaming", "该段已完成，正在继续翻译后续段落。")
            elif evt_type == "error":
                error_text = str(event.get("error", "未知错误"))
                results[para_idx] = _make_page_entry(job, target_bp, error=error_text)
                paragraph_texts[para_idx] = results[para_idx]["translation"]
                paragraph_states[para_idx] = "error"
                paragraph_errors[para_idx] = error_text
                translate_push("stream_para_error", {
                    "doc_id": doc_id,
                    "bp": target_bp,
                    "para_idx": para_idx,
                    "error": error_text,
                    "translation": paragraph_texts[para_idx],
                })
                _save_parallel_draft("streaming", "该段翻译失败，已记录失败占位文本。", last_error=error_text)
            elif evt_type == "aborted":
                paragraph_states[para_idx] = "aborted"
                aborted = True
            else:
                paragraph_states[para_idx] = "error"
                paragraph_errors[para_idx] = f"未知事件: {evt_type}"
                results[para_idx] = _make_page_entry(job, target_bp, error=f"未知事件: {evt_type}")
                paragraph_texts[para_idx] = results[para_idx]["translation"]
                translate_push("stream_para_error", {
                    "doc_id": doc_id,
                    "bp": target_bp,
                    "para_idx": para_idx,
                    "error": f"未知事件: {evt_type}",
                    "translation": paragraph_texts[para_idx],
                })
                _save_parallel_draft("streaming", "该段翻译失败，已记录失败占位文本。", last_error=f"未知事件: {evt_type}")

            while running_count < max_parallel and not aborted and pending_jobs:
                if not _submit_next_job(pool):
                    break

        if aborted:
            translate_push("stream_page_aborted", {
                "doc_id": doc_id,
                "bp": target_bp,
                "para_idx": _primary_para_idx(active_para_indices, paragraph_states),
            })
            _save_parallel_draft("aborted", "当前页已停止，草稿未提交到硬盘。")
            raise TranslateStreamAborted("用户停止流式翻译")

    page_entries = [entry for entry in results if entry is not None]

    if not page_entries:
        raise RuntimeError(f"第{target_bp}页未找到有效内容")

    page_footnotes, page_footnotes_translation = _extract_page_footnote_summary(
        page_entries,
        fallback_footnotes=ctx.get("footnotes", ""),
    )

    paragraph_texts = [_ensure_str(entry.get("translation", "")) if entry else "" for entry in results]
    paragraph_states = [
        ("error" if entry and entry.get("_status") == "error" else "done") if entry else state
        for entry, state in zip(results, paragraph_states)
    ]
    _save_parallel_draft("done", "当前页已完整提交到硬盘。")

    return {
        "_pageBP": target_bp,
        "_model": model_key,
        "_usage": total_usage,
        "_page_entries": page_entries,
        "footnotes": page_footnotes,
        "footnotes_translation": page_footnotes_translation,
        "pages": str(target_bp),
    }


# ============ 后台连续翻译 ============

_translate_task = {
    "running": False,
    "events": [],
    "stop": False,
    "doc_id": "",
}
_translate_lock = threading.Lock()


def _default_stream_draft_state() -> dict:
    return {
        "active": False,
        "bp": None,
        "para_idx": None,
        "para_total": 0,
        "para_done": 0,
        "parallel_limit": 0,
        "active_para_indices": [],
        "paragraph_states": [],
        "paragraph_errors": [],
        "paragraphs": [],
        "status": "idle",
        "note": "",
        "last_error": "",
        "updated_at": 0,
    }


def _default_translate_state(doc_id: str = "") -> dict:
    return {
        "doc_id": doc_id,
        "phase": "idle",
        "running": False,
        "stop_requested": False,
        "start_bp": None,
        "resume_bp": None,
        "total_pages": 0,
        "done_pages": 0,
        "processed_pages": 0,
        "pending_pages": 0,
        "current_bp": None,
        "current_page_idx": 0,
        "translated_chars": 0,
        "translated_paras": 0,
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "model": "",
        "last_error": "",
        "failed_bps": [],
        "partial_failed_bps": [],
        "failed_pages": [],
        "draft": _default_stream_draft_state(),
        "updated_at": 0,
    }


def _clamp_page_progress(total_pages: int, done_pages: int) -> tuple[int, int]:
    total = max(0, int(total_pages or 0))
    done = max(0, int(done_pages or 0))
    if total and done > total:
        done = total
    return total, done


def _remaining_pages(total_pages: int, processed_pages: int) -> int:
    total = max(0, int(total_pages or 0))
    processed = max(0, int(processed_pages or 0))
    if total and processed > total:
        processed = total
    return max(0, total - processed)


def _collect_target_bps(pages: list, start_bp: int | None) -> list[int]:
    if not pages:
        return []
    bp = start_bp
    if bp is None:
        bp, _ = get_page_range(pages)
    if bp is None:
        return []
    target_bps = []
    seen = set()
    while bp is not None and bp not in seen:
        target_bps.append(bp)
        seen.add(bp)
        bp = get_next_page_bp(pages, bp)
    return target_bps


def _compute_resume_bp(doc_id: str, state: dict) -> int | None:
    if not doc_id or not isinstance(state, dict):
        return None
    phase = state.get("phase", "idle")
    if phase in ("idle", "done"):
        return None
    pages, _ = load_pages_from_disk(doc_id)
    target_bps = _collect_target_bps(pages, state.get("start_bp"))
    if not target_bps:
        return None
    entries, _, _ = load_entries_from_disk(doc_id)
    translated_bps = {
        int(entry.get("_pageBP"))
        for entry in entries
        if entry.get("_pageBP") is not None and int(entry.get("_pageBP")) in target_bps
    }
    failed_bps = {
        int(bp)
        for bp in state.get("failed_bps", [])
        if bp is not None and int(bp) in target_bps
    }
    partial_failed_bps = {
        int(bp)
        for bp in state.get("partial_failed_bps", [])
        if bp is not None and int(bp) in target_bps
    }
    processed_bps = translated_bps | failed_bps
    current_bp = state.get("current_bp")
    current_bp = int(current_bp) if current_bp is not None else None

    if phase == "partial_failed":
        for bp in target_bps:
            if bp in failed_bps or bp in partial_failed_bps:
                return bp
        return None

    if phase == "error" and current_bp in target_bps:
        return current_bp

    if phase == "stopped" and current_bp in target_bps and current_bp not in processed_bps:
        return current_bp

    for bp in target_bps:
        if bp not in processed_bps:
            return bp
    return None


def _normalize_translate_state(state: dict, assume_inactive: bool = False) -> dict:
    """统一收口磁盘快照字段，避免前端读取到自相矛盾的状态。"""
    if not isinstance(state, dict):
        return _default_translate_state()

    state["start_bp"] = int(state.get("start_bp")) if state.get("start_bp") is not None else None
    state["resume_bp"] = int(state.get("resume_bp")) if state.get("resume_bp") is not None else None
    total_pages, done_pages = _clamp_page_progress(
        state.get("total_pages", 0),
        state.get("done_pages", 0),
    )
    state["total_pages"] = total_pages
    state["done_pages"] = done_pages
    processed_pages = max(0, int(state.get("processed_pages", done_pages) or 0))
    if total_pages and processed_pages > total_pages:
        processed_pages = total_pages
    if processed_pages < done_pages:
        processed_pages = done_pages
    state["processed_pages"] = processed_pages
    state["pending_pages"] = max(0, int(state.get("pending_pages", max(0, total_pages - done_pages)) or 0))
    current_page_idx = max(0, int(state.get("current_page_idx", 0) or 0))
    if total_pages and current_page_idx > total_pages:
        current_page_idx = total_pages
    state["current_page_idx"] = current_page_idx

    phase = state.get("phase", "idle")
    draft = state.get("draft")
    if not isinstance(draft, dict):
        draft = _default_stream_draft_state()
    if not isinstance(draft.get("active_para_indices"), list):
        draft["active_para_indices"] = []
    if not isinstance(draft.get("paragraph_states"), list):
        draft["paragraph_states"] = []
    if not isinstance(draft.get("paragraph_errors"), list):
        draft["paragraph_errors"] = []
    if not isinstance(draft.get("paragraphs"), list):
        draft["paragraphs"] = []
    if not isinstance(state.get("partial_failed_bps"), list):
        state["partial_failed_bps"] = []

    if phase in ("idle", "done", "partial_failed", "stopped", "error"):
        state["running"] = False
        state["stop_requested"] = False
    if phase == "done":
        state["processed_pages"] = total_pages
        state["pending_pages"] = 0
    elif phase == "partial_failed":
        state["processed_pages"] = total_pages
        state["pending_pages"] = 0

    if assume_inactive and phase in ("running", "stopping"):
        state["running"] = False
        state["stop_requested"] = False
        state["phase"] = "stopped"
        if draft.get("active"):
            draft["active"] = False
            draft["active_para_indices"] = []
            if draft.get("status") == "streaming":
                draft["status"] = "aborted"
                draft["note"] = "后台翻译未处于活动状态，当前页草稿已中断。"

    if state.get("phase") in ("done", "partial_failed", "stopped", "error"):
        draft["active"] = False
        draft["active_para_indices"] = []

    state["draft"] = draft
    state["total_tokens"] = state.get("prompt_tokens", 0) + state.get("completion_tokens", 0)
    return state


def _save_translate_state(doc_id: str, running: bool, stop_requested: bool, **extra):
    """保存翻译状态到 SQLite。"""
    if not doc_id:
        return
    state = _load_translate_state(doc_id)
    state.update(extra)
    state["doc_id"] = doc_id
    state["running"] = running
    state["stop_requested"] = stop_requested
    if "phase" not in extra:
        state["phase"] = "stopping" if stop_requested else ("running" if running else state.get("phase", "idle"))
    state["total_tokens"] = state.get("prompt_tokens", 0) + state.get("completion_tokens", 0)
    state["updated_at"] = time.time()
    payload = dict(state)
    payload.pop("doc_id", None)
    SQLiteRepository().save_translate_run(doc_id, **payload)


def _load_translate_state(doc_id: str) -> dict:
    """从 SQLite 加载翻译状态。"""
    default = _default_translate_state(doc_id)
    if not doc_id:
        return default
    repo = SQLiteRepository()
    data = repo.get_effective_translate_run(doc_id)
    if not isinstance(data, dict):
        return default
    default.update(data)
    failures = repo.list_translate_failures(doc_id)
    if failures:
        default["failed_pages"] = failures
        default["failed_bps"] = [int(item["bp"]) for item in failures if item.get("bp") is not None]
    default["doc_id"] = doc_id
    draft = default.get("draft")
    if not isinstance(draft, dict):
        draft = {}
    merged_draft = _default_stream_draft_state()
    merged_draft.update(draft)
    if not isinstance(merged_draft.get("active_para_indices"), list):
        merged_draft["active_para_indices"] = []
    if not isinstance(merged_draft.get("paragraph_states"), list):
        merged_draft["paragraph_states"] = []
    if not isinstance(merged_draft.get("paragraph_errors"), list):
        merged_draft["paragraph_errors"] = []
    if not isinstance(merged_draft.get("paragraphs"), list):
        merged_draft["paragraphs"] = []
    default["draft"] = merged_draft
    if not isinstance(default.get("failed_bps"), list):
        default["failed_bps"] = []
    if not isinstance(default.get("partial_failed_bps"), list):
        default["partial_failed_bps"] = []
    if not isinstance(default.get("failed_pages"), list):
        default["failed_pages"] = []
    return _normalize_translate_state(default)


def _clear_translate_state(doc_id: str):
    """清除 SQLite 中的翻译状态。"""
    if doc_id:
        SQLiteRepository().clear_translate_runs(doc_id)


def _save_stream_draft(doc_id: str, **fields):
    if not doc_id:
        return
    snapshot = _load_translate_state(doc_id)
    draft = _default_stream_draft_state()
    draft.update(snapshot.get("draft") or {})
    draft.update(fields)
    paragraphs = draft.get("paragraphs")
    draft["paragraphs"] = list(paragraphs) if isinstance(paragraphs, list) else []
    active_para_indices = draft.get("active_para_indices")
    draft["active_para_indices"] = list(active_para_indices) if isinstance(active_para_indices, list) else []
    paragraph_states = draft.get("paragraph_states")
    draft["paragraph_states"] = list(paragraph_states) if isinstance(paragraph_states, list) else []
    paragraph_errors = draft.get("paragraph_errors")
    draft["paragraph_errors"] = list(paragraph_errors) if isinstance(paragraph_errors, list) else []
    draft["updated_at"] = time.time()
    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        phase=snapshot.get("phase", "idle"),
        draft=draft,
    )


def _clear_failed_page_state(doc_id: str, bp: int):
    if not doc_id or bp is None:
        return
    snapshot = _load_translate_state(doc_id)
    failed_pages = [
        page for page in snapshot.get("failed_pages", [])
        if isinstance(page, dict) and page.get("bp") != bp
    ]
    failed_bps = [page.get("bp") for page in failed_pages if page.get("bp") is not None]
    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        phase=snapshot.get("phase", "idle"),
        failed_pages=failed_pages,
        failed_bps=sorted(failed_bps),
    )


def _mark_failed_page_state(doc_id: str, bp: int, error: str):
    if not doc_id or bp is None:
        return
    snapshot = _load_translate_state(doc_id)
    failed_pages = [
        page for page in snapshot.get("failed_pages", [])
        if isinstance(page, dict) and page.get("bp") != bp
    ]
    failed_pages.append({
        "bp": bp,
        "error": str(error),
        "updated_at": time.time(),
    })
    failed_pages.sort(key=lambda page: page.get("bp") or 0)
    failed_bps = [page.get("bp") for page in failed_pages if page.get("bp") is not None]
    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        phase=snapshot.get("phase", "idle"),
        failed_pages=failed_pages,
        failed_bps=failed_bps,
        last_error=str(error),
    )


def reconcile_translate_state_after_page_success(doc_id: str, bp: int):
    if not doc_id or bp is None:
        return
    _clear_failed_page_state(doc_id, bp)
    snapshot = _load_translate_state(doc_id)
    pages, _ = load_pages_from_disk(doc_id)
    target_bps = _collect_target_bps(pages, snapshot.get("start_bp"))
    total_pages = len(target_bps) if target_bps else int(snapshot.get("total_pages", 0) or 0)
    entries, _, _ = load_entries_from_disk(doc_id)
    translated_bps = {
        int(entry.get("_pageBP"))
        for entry in entries
        if entry.get("_pageBP") is not None and (not target_bps or int(entry.get("_pageBP")) in target_bps)
    }
    partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps)
    done_bps = translated_bps - set(partial_failed_bps)
    done_pages = min(total_pages, len(done_bps)) if total_pages else len(done_bps)
    failed_pages = [
        page for page in snapshot.get("failed_pages", [])
        if isinstance(page, dict) and page.get("bp") is not None and (not target_bps or int(page.get("bp")) in target_bps)
    ]
    failed_bps = sorted(int(page.get("bp")) for page in failed_pages)
    processed_floor = len(set(failed_bps) | translated_bps)
    processed_pages = max(processed_floor, int(snapshot.get("processed_pages", done_pages) or 0))
    if total_pages:
        processed_pages = min(total_pages, processed_pages)
    pending_pages = _remaining_pages(total_pages, processed_pages)
    previous_phase = snapshot.get("phase", "idle")

    if snapshot.get("running", False):
        phase = "stopping" if snapshot.get("stop_requested", False) else "running"
    elif failed_bps or partial_failed_bps:
        phase = "partial_failed" if pending_pages == 0 else previous_phase
        if phase == "done":
            phase = "partial_failed"
    else:
        if pending_pages == 0 and total_pages:
            phase = "done"
        elif previous_phase in ("error", "partial_failed"):
            phase = "stopped"
        else:
            phase = previous_phase

    next_last_error = failed_pages[0].get("error", "") if failed_pages else ""
    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        phase=phase,
        total_pages=total_pages,
        done_pages=done_pages,
        processed_pages=processed_pages,
        pending_pages=pending_pages,
        current_bp=snapshot.get("current_bp"),
        current_page_idx=snapshot.get("current_page_idx", 0),
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=snapshot.get("model", ""),
        failed_pages=failed_pages,
        failed_bps=failed_bps,
        partial_failed_bps=partial_failed_bps,
        last_error=next_last_error,
    )


def reconcile_translate_state_after_page_failure(doc_id: str, bp: int, error: str):
    if not doc_id or bp is None:
        return
    _mark_failed_page_state(doc_id, bp, error)
    snapshot = _load_translate_state(doc_id)
    pages, _ = load_pages_from_disk(doc_id)
    target_bps = _collect_target_bps(pages, snapshot.get("start_bp"))
    total_pages = len(target_bps) if target_bps else int(snapshot.get("total_pages", 0) or 0)
    entries, _, _ = load_entries_from_disk(doc_id)
    translated_bps = {
        int(entry.get("_pageBP"))
        for entry in entries
        if entry.get("_pageBP") is not None and (not target_bps or int(entry.get("_pageBP")) in target_bps)
    }
    partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps)
    done_bps = translated_bps - set(partial_failed_bps)
    done_pages = min(total_pages, len(done_bps)) if total_pages else len(done_bps)
    failed_pages = [
        page for page in snapshot.get("failed_pages", [])
        if isinstance(page, dict) and page.get("bp") is not None and (not target_bps or int(page.get("bp")) in target_bps)
    ]
    failed_bps = sorted(int(page.get("bp")) for page in failed_pages)
    processed_floor = len(set(failed_bps) | translated_bps)
    processed_pages = max(processed_floor, int(snapshot.get("processed_pages", done_pages) or 0))
    if total_pages:
        processed_pages = min(total_pages, processed_pages)
    pending_pages = _remaining_pages(total_pages, processed_pages)
    previous_phase = snapshot.get("phase", "idle")

    if snapshot.get("running", False):
        phase = "stopping" if snapshot.get("stop_requested", False) else "running"
    elif pending_pages == 0 and (failed_bps or partial_failed_bps):
        phase = "partial_failed"
    elif previous_phase in ("error", "partial_failed", "stopped"):
        phase = previous_phase
    else:
        phase = "stopped"

    _save_translate_state(
        doc_id,
        running=snapshot.get("running", False),
        stop_requested=snapshot.get("stop_requested", False),
        phase=phase,
        total_pages=total_pages,
        done_pages=done_pages,
        processed_pages=processed_pages,
        pending_pages=pending_pages,
        current_bp=bp,
        current_page_idx=snapshot.get("current_page_idx", 0),
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=snapshot.get("model", ""),
        failed_pages=failed_pages,
        failed_bps=failed_bps,
        partial_failed_bps=partial_failed_bps,
        last_error=str(error),
    )


def translate_push(event_type: str, data: dict):
    with _translate_lock:
        _translate_task["events"].append((event_type, data))


def get_translate_state() -> dict:
    """获取翻译任务状态（线程安全）。"""
    with _translate_lock:
        state = _load_translate_state(_translate_task["doc_id"]) if _translate_task["doc_id"] else _default_translate_state()
        return {
            "running": _translate_task["running"],
            "events": list(_translate_task["events"]),
            "doc_id": _translate_task["doc_id"],
            "state": state,
        }


def get_translate_events(cursor: int, doc_id: str) -> tuple[list, bool]:
    """获取从 cursor 开始的翻译事件，返回 (events, running)。"""
    with _translate_lock:
        if _translate_task["doc_id"] != doc_id:
            return [], False
        events = _translate_task["events"][cursor:]
        running = _translate_task["running"]
    return events, running


def has_active_translate_task() -> bool:
    """是否有任何后台翻译任务正在运行。"""
    with _translate_lock:
        return _translate_task["running"]


def get_translate_snapshot(doc_id: str) -> dict:
    """获取指定文档的翻译快照。"""
    if not doc_id:
        return _default_translate_state()
    state = _load_translate_state(doc_id)
    has_active_worker = False
    with _translate_lock:
        if _translate_task["doc_id"] == doc_id:
            has_active_worker = True
            state["running"] = _translate_task["running"]
            state["stop_requested"] = _translate_task["stop"]
            if state["running"] and state["phase"] not in ("running", "stopping"):
                state["phase"] = "stopping" if state["stop_requested"] else "running"
    state = _normalize_translate_state(state, assume_inactive=not has_active_worker)
    pages, _ = load_pages_from_disk(doc_id)
    target_bps = _collect_target_bps(pages, state.get("start_bp"))
    partial_failed_bps = _collect_partial_failed_bps(doc_id, target_bps)
    state["partial_failed_bps"] = partial_failed_bps
    if (
        partial_failed_bps
        and not state.get("running")
        and state.get("phase") not in ("running", "stopping", "error")
        and state.get("pending_pages", 0) == 0
    ):
        state["phase"] = "partial_failed"
    state["resume_bp"] = _compute_resume_bp(doc_id, state)
    return state


def is_translate_running(doc_id: str) -> bool:
    """检查指定文档的翻译是否正在运行。"""
    if not doc_id:
        return False
    return get_translate_snapshot(doc_id)["running"]


def is_stop_requested(doc_id: str) -> bool:
    """检查是否请求了停止翻译。"""
    if not doc_id:
        return False
    return get_translate_snapshot(doc_id).get("stop_requested", False)


def _runtime_stop_requested(doc_id: str) -> bool:
    """读取运行时 stop 标记，避免并发下被旧快照覆盖。"""
    if not doc_id:
        return False
    with _translate_lock:
        return bool(
            _translate_task["running"]
            and _translate_task["doc_id"] == doc_id
            and _translate_task["stop"]
        )


def request_stop_translate(doc_id: str) -> bool:
    """请求停止指定文档的翻译。"""
    if not doc_id:
        return False
    with _translate_lock:
        if not _translate_task["running"] or _translate_task["doc_id"] != doc_id:
            return False
        _translate_task["stop"] = True
    snapshot = _load_translate_state(doc_id)
    _save_translate_state(
        doc_id,
        running=True,
        stop_requested=True,
        phase="stopping",
        total_pages=snapshot.get("total_pages", 0),
        done_pages=snapshot.get("done_pages", 0),
        processed_pages=snapshot.get("processed_pages", snapshot.get("done_pages", 0)),
        pending_pages=snapshot.get("pending_pages", 0),
        current_bp=snapshot.get("current_bp"),
        current_page_idx=snapshot.get("current_page_idx", 0),
        translated_chars=snapshot.get("translated_chars", 0),
        translated_paras=snapshot.get("translated_paras", 0),
        request_count=snapshot.get("request_count", 0),
        prompt_tokens=snapshot.get("prompt_tokens", 0),
        completion_tokens=snapshot.get("completion_tokens", 0),
        model=snapshot.get("model", ""),
        last_error=snapshot.get("last_error", ""),
    )
    return True


def request_stop_active_translate() -> bool:
    """请求停止当前活动翻译任务（不关心 doc_id）。"""
    with _translate_lock:
        running = _translate_task.get("running", False)
        active_doc_id = _translate_task.get("doc_id", "")
    if not running or not active_doc_id:
        return False
    return request_stop_translate(active_doc_id)


def wait_for_translate_idle(timeout_s: float = 3.0, poll_interval_s: float = 0.05) -> bool:
    """等待后台翻译进入空闲状态。"""
    deadline = time.time() + max(0.0, float(timeout_s))
    interval = max(0.01, float(poll_interval_s))
    while time.time() <= deadline:
        with _translate_lock:
            if not _translate_task.get("running", False):
                return True
        time.sleep(interval)
    with _translate_lock:
        return not _translate_task.get("running", False)


def start_translate_task(doc_id: str, start_bp: int, doc_title: str) -> bool:
    """启动后台翻译任务，返回是否成功启动。"""
    if not doc_id:
        return False
    with _translate_lock:
        if _translate_task["running"]:
            return False
        _translate_task["running"] = True
        _translate_task["stop"] = False
        _translate_task["events"] = []
        _translate_task["doc_id"] = doc_id

    _save_translate_state(
        doc_id,
        running=True,
        stop_requested=False,
        phase="running",
        start_bp=start_bp,
        total_pages=0,
        done_pages=0,
        processed_pages=0,
        pending_pages=0,
        current_bp=None,
        current_page_idx=0,
        translated_chars=0,
        translated_paras=0,
        request_count=0,
        prompt_tokens=0,
        completion_tokens=0,
        model=get_model_key(),
        last_error="",
        failed_bps=[],
        partial_failed_bps=[],
        failed_pages=[],
        draft=_default_stream_draft_state(),
    )

    t = threading.Thread(target=_translate_all_worker, args=(doc_id, start_bp, doc_title), daemon=True)
    t.start()
    return True


def _translate_all_worker(doc_id: str, start_bp: int, doc_title: str):
    """后台线程：从 start_bp 开始逐页翻译，每页完成后写入磁盘。"""
    try:
        pages, _ = load_pages_from_disk(doc_id)
        entries, _, _ = load_entries_from_disk(doc_id)
        model_key = get_model_key()
        t_args = get_translate_args(model_key)
        glossary = get_glossary(doc_id)

        if not pages or not t_args["api_key"]:
            translate_push("error", {"msg": "数据不完整或缺少 API Key"})
            return

        first, last = get_page_range(pages)
        doc_bps = []
        bp = first
        while bp is not None:
            doc_bps.append(bp)
            bp = get_next_page_bp(pages, bp)

        all_bps = []
        bp = start_bp
        while bp is not None:
            all_bps.append(bp)
            bp = get_next_page_bp(pages, bp)

        doc_bp_set = set(doc_bps)
        partial_failed_doc_bps = set(_collect_partial_failed_bps(doc_id, doc_bps))
        done_bps = set()
        for e in entries:
            pbp = e.get("_pageBP")
            if pbp is not None and pbp in doc_bp_set and pbp not in partial_failed_doc_bps:
                done_bps.add(pbp)

        pending_bps = [b for b in all_bps if b not in done_bps]
        total_pages = len(doc_bps)
        done_pages = len(done_bps)

        translate_push("init", {
            "total_pages": total_pages,
            "done_pages": done_pages,
            "pending_pages": len(pending_bps),
        })
        _save_translate_state(
            doc_id,
            running=True,
            stop_requested=False,
            phase="running",
            start_bp=start_bp,
            total_pages=total_pages,
            done_pages=done_pages,
            processed_pages=done_pages,
            pending_pages=_remaining_pages(total_pages, done_pages),
            current_bp=None,
            current_page_idx=done_pages,
            translated_chars=0,
            translated_paras=0,
            request_count=0,
            prompt_tokens=0,
            completion_tokens=0,
            model=model_key,
            last_error="",
            failed_bps=[],
            partial_failed_bps=sorted(partial_failed_doc_bps),
            failed_pages=[],
            draft=_default_stream_draft_state(),
        )

        for i, bp in enumerate(pending_bps):
            should_stop = _runtime_stop_requested(doc_id)
            if should_stop:
                snapshot = _load_translate_state(doc_id)
                state_total, state_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", done_pages + i),
                )
                _save_translate_state(
                    doc_id,
                    running=False,
                    stop_requested=False,
                    phase="stopped",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=snapshot.get("processed_pages", state_done),
                    pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                    current_bp=snapshot.get("current_bp"),
                    current_page_idx=snapshot.get("current_page_idx", done_pages + i),
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=snapshot.get("model", model_key),
                    last_error="",
                )
                translate_push("stopped", {"msg": "翻译已停止"})
                return

            current_page_idx = doc_bps.index(bp) + 1 if bp in doc_bps else (done_pages + i + 1)
            snapshot = _load_translate_state(doc_id)
            state_total, state_done = _clamp_page_progress(
                snapshot.get("total_pages", total_pages),
                snapshot.get("done_pages", done_pages + i),
            )
            stop_requested_now = _runtime_stop_requested(doc_id)
            if stop_requested_now:
                _save_translate_state(
                    doc_id,
                    running=False,
                    stop_requested=False,
                    phase="stopped",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=snapshot.get("processed_pages", state_done),
                    pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                    current_bp=snapshot.get("current_bp"),
                    current_page_idx=snapshot.get("current_page_idx", done_pages + i),
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=snapshot.get("model", model_key),
                    last_error="",
                )
                translate_push("stopped", {"msg": "翻译已停止"})
                return
            _save_translate_state(
                doc_id,
                running=True,
                stop_requested=stop_requested_now,
                phase="stopping" if stop_requested_now else "running",
                total_pages=state_total,
                done_pages=state_done,
                processed_pages=snapshot.get("processed_pages", state_done),
                pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                current_bp=bp,
                current_page_idx=current_page_idx,
                translated_chars=snapshot.get("translated_chars", 0),
                translated_paras=snapshot.get("translated_paras", 0),
                request_count=snapshot.get("request_count", 0),
                prompt_tokens=snapshot.get("prompt_tokens", 0),
                completion_tokens=snapshot.get("completion_tokens", 0),
                model=model_key,
                last_error="",
            )
            translate_push("page_start", {
                "bp": bp,
                "page_idx": current_page_idx,
                "total": total_pages,
            })

            try:
                model_key = get_model_key()
                t_args = get_translate_args(model_key)
                entry = translate_page_stream(
                    pages,
                    bp,
                    model_key,
                    t_args,
                    glossary,
                    doc_id=doc_id,
                    stop_checker=lambda: is_stop_requested(doc_id),
                )

                entry_idx = save_entry_to_disk(entry, doc_title, doc_id)
                _clear_failed_page_state(doc_id, bp)

                para_count = len(entry.get("_page_entries", []))
                char_count = sum(len(pe.get("translation", "")) for pe in entry.get("_page_entries", []))
                entry_usage = entry.get("_usage", {})
                snapshot = _load_translate_state(doc_id)
                state_total, snapshot_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", 0),
                )
                page_has_partial_failure = _entry_has_paragraph_error(entry)
                next_processed_pages = min(
                    state_total,
                    int(snapshot.get("processed_pages", snapshot_done) or 0) + 1,
                )
                next_done_pages = min(state_total, snapshot_done + (0 if page_has_partial_failure else 1))
                translated_chars = snapshot.get("translated_chars", 0) + char_count
                translated_paras = snapshot.get("translated_paras", 0) + para_count
                request_count = snapshot.get("request_count", 0) + int(entry_usage.get("request_count", 0) or 0)
                prompt_tokens = snapshot.get("prompt_tokens", 0) + int(entry_usage.get("prompt_tokens", 0) or 0)
                completion_tokens = snapshot.get("completion_tokens", 0) + int(entry_usage.get("completion_tokens", 0) or 0)
                partial_failed_bps = _collect_partial_failed_bps(doc_id, doc_bps)

                _save_translate_state(
                    doc_id,
                    running=True,
                    stop_requested=_runtime_stop_requested(doc_id),
                    phase="stopping" if _runtime_stop_requested(doc_id) else "running",
                    total_pages=state_total,
                    done_pages=next_done_pages,
                    processed_pages=next_processed_pages,
                    pending_pages=_remaining_pages(state_total, next_processed_pages),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=translated_chars,
                    translated_paras=translated_paras,
                    request_count=request_count,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    model=model_key,
                    partial_failed_bps=partial_failed_bps,
                    last_error="",
                )
                stop_requested_now = _runtime_stop_requested(doc_id)
                if stop_requested_now:
                    stop_snapshot = _load_translate_state(doc_id)
                    stop_total, stop_done = _clamp_page_progress(
                        stop_snapshot.get("total_pages", total_pages),
                        stop_snapshot.get("done_pages", next_done_pages),
                    )
                    _save_translate_state(
                        doc_id,
                        running=False,
                        stop_requested=False,
                        phase="stopped",
                        total_pages=stop_total,
                        done_pages=stop_done,
                        processed_pages=stop_snapshot.get("processed_pages", stop_done),
                        pending_pages=_remaining_pages(stop_total, stop_snapshot.get("processed_pages", stop_done)),
                        current_bp=bp,
                        current_page_idx=current_page_idx,
                        translated_chars=stop_snapshot.get("translated_chars", translated_chars),
                        translated_paras=stop_snapshot.get("translated_paras", translated_paras),
                        request_count=stop_snapshot.get("request_count", request_count),
                        prompt_tokens=stop_snapshot.get("prompt_tokens", prompt_tokens),
                        completion_tokens=stop_snapshot.get("completion_tokens", completion_tokens),
                        model=stop_snapshot.get("model", model_key),
                        partial_failed_bps=stop_snapshot.get("partial_failed_bps", partial_failed_bps),
                        last_error="",
                    )
                    translate_push("page_done", {
                        "bp": bp,
                        "page_idx": current_page_idx,
                        "total": total_pages,
                        "entry_idx": entry_idx,
                        "para_count": para_count,
                        "char_count": char_count,
                        "usage": entry_usage,
                        "model": model_key,
                        "partial_failed": any((pe.get("_status") == "error") for pe in entry.get("_page_entries", [])),
                    })
                    translate_push("stopped", {"msg": "翻译已停止", "bp": bp})
                    return
                translate_push("page_done", {
                    "bp": bp,
                    "page_idx": current_page_idx,
                    "total": total_pages,
                    "entry_idx": entry_idx,
                    "para_count": para_count,
                    "char_count": char_count,
                    "usage": entry_usage,
                    "model": model_key,
                    "partial_failed": any((pe.get("_status") == "error") for pe in entry.get("_page_entries", [])),
                })

            except TranslateStreamAborted:
                snapshot = _load_translate_state(doc_id)
                state_total, state_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", done_pages + i),
                )
                _save_translate_state(
                    doc_id,
                    running=False,
                    stop_requested=False,
                    phase="stopped",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=snapshot.get("processed_pages", state_done),
                    pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=model_key,
                    last_error="",
                )
                translate_push("stopped", {"msg": "翻译已停止", "bp": bp})
                return
            except Exception as e:
                _mark_failed_page_state(doc_id, bp, str(e))
                snapshot = _load_translate_state(doc_id)
                draft = _default_stream_draft_state()
                draft.update(snapshot.get("draft") or {})
                if draft.get("bp") != bp:
                    draft = _default_stream_draft_state()
                    draft.update({
                        "bp": bp,
                        "para_total": 0,
                        "para_done": 0,
                        "paragraphs": [],
                    })
                _save_stream_draft(
                    doc_id,
                    active=False,
                    bp=bp,
                    para_idx=draft.get("para_idx"),
                    para_total=draft.get("para_total", 0),
                    para_done=draft.get("para_done", 0),
                    paragraph_errors=draft.get("paragraph_errors", []),
                    paragraphs=draft.get("paragraphs", []),
                    status="error",
                    note=f"p.{bp} 翻译失败，等待重试。",
                    last_error=str(e),
                )
                snapshot = _load_translate_state(doc_id)
                state_total, state_done = _clamp_page_progress(
                    snapshot.get("total_pages", total_pages),
                    snapshot.get("done_pages", done_pages + i),
                )
                next_processed_pages = min(
                    state_total,
                    int(snapshot.get("processed_pages", state_done) or 0) + 1,
                )
                _save_translate_state(
                    doc_id,
                    running=True,
                    stop_requested=snapshot.get("stop_requested", False),
                    phase="stopping" if snapshot.get("stop_requested", False) else "running",
                    total_pages=state_total,
                    done_pages=state_done,
                    processed_pages=next_processed_pages,
                    pending_pages=_remaining_pages(state_total, next_processed_pages),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=model_key,
                    partial_failed_bps=snapshot.get("partial_failed_bps", []),
                    last_error=str(e),
                )
                translate_push("page_error", {
                    "bp": bp,
                    "error": str(e),
                    "page_idx": current_page_idx,
                    "total": total_pages,
                })

        snapshot = _load_translate_state(doc_id)
        state_total, state_done = _clamp_page_progress(
            snapshot.get("total_pages", total_pages),
            snapshot.get("done_pages", total_pages),
        )
        final_failed_bps = [
            bp for bp in snapshot.get("failed_bps", [])
            if bp is not None
        ]
        final_partial_failed_bps = _collect_partial_failed_bps(doc_id, doc_bps)
        entries, _, _ = load_entries_from_disk(doc_id)
        translated_bps = {
            int(entry.get("_pageBP"))
            for entry in entries
            if entry.get("_pageBP") is not None and int(entry.get("_pageBP")) in doc_bp_set
        }
        final_done_pages = min(state_total, len(translated_bps - set(final_partial_failed_bps))) if state_total else len(translated_bps - set(final_partial_failed_bps))
        final_phase = "partial_failed" if (final_failed_bps or final_partial_failed_bps) else "done"
        _save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase=final_phase,
            total_pages=state_total,
            done_pages=final_done_pages,
            processed_pages=state_total,
            pending_pages=0,
            current_bp=snapshot.get("current_bp"),
            current_page_idx=snapshot.get("current_page_idx", state_total),
            translated_chars=snapshot.get("translated_chars", 0),
            translated_paras=snapshot.get("translated_paras", 0),
            request_count=snapshot.get("request_count", 0),
            prompt_tokens=snapshot.get("prompt_tokens", 0),
            completion_tokens=snapshot.get("completion_tokens", 0),
            model=snapshot.get("model", model_key),
            partial_failed_bps=final_partial_failed_bps,
            last_error=snapshot.get("last_error", ""),
        )
        translate_push("all_done", {
            "total_pages": total_pages,
            "total_entries": len(entries),
        })

    except Exception as e:
        snapshot = _load_translate_state(doc_id)
        state_total, state_done = _clamp_page_progress(
            snapshot.get("total_pages", 0),
            snapshot.get("done_pages", 0),
        )
        _save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="error",
            total_pages=state_total,
            done_pages=state_done,
            processed_pages=snapshot.get("processed_pages", state_done),
            pending_pages=_remaining_pages(state_total, snapshot.get("processed_pages", state_done)),
            current_bp=snapshot.get("current_bp"),
            current_page_idx=snapshot.get("current_page_idx", 0),
            translated_chars=snapshot.get("translated_chars", 0),
            translated_paras=snapshot.get("translated_paras", 0),
            request_count=snapshot.get("request_count", 0),
            prompt_tokens=snapshot.get("prompt_tokens", 0),
            completion_tokens=snapshot.get("completion_tokens", 0),
            model=snapshot.get("model", ""),
            last_error=str(e),
        )
        translate_push("error", {"msg": str(e)})
    finally:
        with _translate_lock:
            _translate_task["running"] = False
            _translate_task["stop"] = False
            _translate_task["doc_id"] = ""


# ============ 重新解析 ============

def reparse_file(task_id: str, doc_id: str):
    """后台线程：对已有文档重新执行 OCR 解析（保留翻译数据）。"""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return

    paddle_token = get_paddle_token()
    pdf_path = task["file_path"]
    file_name = task["file_name"]

    try:
        with open(pdf_path, "rb") as f:
            file_bytes = f.read()

        all_logs = []

        # Step 1: OCR
        task_push(task_id, "progress", {"pct": 5, "label": "重新调用 PaddleOCR…", "detail": ""})

        def on_ocr_progress(chunk_i, total_chunks):
            pct = 5 + (chunk_i / total_chunks) * 60
            task_push(task_id, "progress", {
                "pct": pct,
                "label": f"OCR 解析中… ({chunk_i}/{total_chunks})",
                "detail": f"分片 {chunk_i}/{total_chunks}",
            })

        result = call_paddle_ocr_bytes(
            file_bytes=file_bytes,
            token=paddle_token,
            file_type=0,
            on_progress=on_ocr_progress,
        )

        task_push(task_id, "progress", {"pct": 65, "label": "解析 OCR 结果…", "detail": ""})
        parsed = parse_ocr(result)
        if not parsed["pages"]:
            task_push(task_id, "error_msg", {"error": "重新解析失败：未获取到页面数据"})
            return
        all_logs.extend(parsed["log"])

        # Step 2: PDF text extraction（带污染检测）
        task_push(task_id, "progress", {"pct": 72, "label": "提取 PDF 文字层…", "detail": ""})
        pdf_pages = extract_pdf_text(file_bytes)
        if pdf_pages:
            task_push(task_id, "log", {"msg": f"检测到有效PDF文字层 ({len(pdf_pages)}页)", "cls": "success"})
            combined = combine_sources(parsed["pages"], pdf_pages)
            parsed["pages"] = combined["pages"]
            all_logs.extend(combined["log"])
        else:
            task_push(task_id, "log", {"msg": "PDF无有效文字层（或文字层已损坏），使用OCR文字"})
            all_logs.append("PDF无有效文字层，使用OCR文字")

        # Step 3: Clean headers/footers
        task_push(task_id, "progress", {"pct": 85, "label": "清理页眉页脚…", "detail": ""})
        hf = clean_header_footer(parsed["pages"])
        final_pages = hf["pages"]
        all_logs.extend(hf["log"])

        # Step 4: 保存页面数据（SQLite 主写入）
        task_push(task_id, "progress", {"pct": 95, "label": "保存数据…", "detail": ""})
        save_pages_to_disk(final_pages, file_name, doc_id)
        save_pdf_toc_to_disk(doc_id, extract_pdf_toc(file_bytes))

        first, last = get_page_range(final_pages)
        summary = f"重新解析完成！{len(final_pages)}页 (p.{first}-{last})"
        task_push(task_id, "done", {"summary": summary, "logs": all_logs})

    except Exception as e:
        task_push(task_id, "error_msg", {"error": f"重新解析失败: {e}"})


def reparse_single_page(task_id: str, doc_id: str, target_bp: int, file_idx: int):
    """后台线程：对单页重新执行 OCR 解析（保留翻译数据）。"""
    from pdf_extract import extract_single_page_pdf

    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return

    paddle_token = get_paddle_token()
    pdf_path = task["file_path"]
    file_name = task["file_name"]

    try:
        # 提取单页PDF
        task_push(task_id, "progress", {"pct": 5, "label": f"提取第 {target_bp} 页…", "detail": ""})
        single_page_bytes = extract_single_page_pdf(pdf_path, file_idx)
        if not single_page_bytes:
            task_push(task_id, "error_msg", {"error": f"无法提取第 {target_bp} 页"})
            return

        # 调用 PaddleOCR
        task_push(task_id, "progress", {"pct": 30, "label": "调用 PaddleOCR 解析…", "detail": ""})
        result = call_paddle_ocr_bytes(
            file_bytes=single_page_bytes,
            token=paddle_token,
            file_type=0,  # PDF
        )

        task_push(task_id, "progress", {"pct": 65, "label": "解析 OCR 结果…", "detail": ""})
        parsed = parse_ocr(result)
        if not parsed["pages"]:
            task_push(task_id, "error_msg", {"error": "OCR 未返回页面数据"})
            return

        # 单页结果
        new_page = parsed["pages"][0]
        new_page["bookPage"] = target_bp
        new_page["fileIdx"] = file_idx

        # 单页手动重解析固定走 OCR 文本，避免坏掉的 PDF 文字层再次覆盖版面文本。
        task_push(task_id, "progress", {
            "pct": 75,
            "label": "保留 OCR 文字…",
            "detail": "手动重解析会跳过 PDF 文字层",
        })
        task_push(task_id, "log", {
            "msg": "手动重解析模式：跳过 PDF 文字层，强制使用 OCR 文字",
            "cls": "success",
        })
        new_page["textSource"] = "ocr"

        # 清理页眉页脚
        task_push(task_id, "progress", {"pct": 85, "label": "清理页眉页脚…", "detail": ""})
        hf = clean_header_footer([new_page])
        new_page = hf["pages"][0]

        # 读取现有页面数据并更新
        task_push(task_id, "progress", {"pct": 95, "label": "保存数据…", "detail": ""})
        existing_pages, _ = load_pages_from_disk(doc_id)
        updated_pages = []
        for p in existing_pages:
            if p["bookPage"] == target_bp:
                updated_pages.append(new_page)
            else:
                updated_pages.append(p)

        save_pages_to_disk(updated_pages, file_name, doc_id)
        entries, doc_title, _ = load_entries_from_disk(doc_id)
        entry_title = doc_title or file_name

        try:
            model_key = ""
            for entry in entries:
                if entry.get("_pageBP") == target_bp and entry.get("_model") in MODELS:
                    model_key = entry.get("_model")
                    break
            if not model_key:
                model_key = get_model_key()
            t_args = get_translate_args(model_key)
            if not t_args["api_key"]:
                raise RuntimeError("缺少翻译 API Key，请先在设置中配置。")

            model_label = MODELS.get(model_key, {}).get("label", model_key)
            task_push(task_id, "progress", {
                "pct": 97,
                "label": "自动重译本页…",
                "detail": f"使用 {model_label}",
            })
            task_push(task_id, "log", {
                "msg": f"开始自动重译第 {target_bp} 页（{model_label}）",
                "cls": "success",
            })
            new_entry = translate_page(updated_pages, target_bp, model_key, t_args, get_glossary(doc_id))
            save_entry_to_disk(new_entry, entry_title, doc_id)
            reconcile_translate_state_after_page_success(doc_id, target_bp)
        except Exception as e:
            reconcile_translate_state_after_page_failure(doc_id, target_bp, str(e))
            task_push(task_id, "error_msg", {"error": f"第 {target_bp} 页 OCR 重解析已完成，但自动重译失败: {e}"})
            return

        summary = f"第 {target_bp} 页 OCR 重解析并重译完成"
        task_push(task_id, "done", {"summary": summary, "bp": target_bp})

    except Exception as e:
        task_push(task_id, "error_msg", {"error": f"重新解析失败: {e}"})

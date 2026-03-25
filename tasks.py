"""后台任务：OCR 文件处理、页面翻译、连续翻译 worker。"""
import json
import os
import re
import threading
import time

from config import (
    MODELS,
    get_paddle_token, get_glossary, get_model_key,
    create_doc, get_doc_dir,
)
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
    get_translate_args, _ensure_str,
)


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

    fn_filtered = ctx["footnotes"]

    # 获取段落对应的 bbox 坐标
    para_bboxes = get_paragraph_bboxes(pages, target_bp, paragraphs)

    # 预处理：构建翻译任务列表
    tasks = []
    fn_assigned = False
    for para in paragraphs:
        hlevel = para.get("heading_level", 0)
        text = para["text"].strip()
        cross = para.get("cross_page")
        if not text:
            continue
        if hlevel == 0 and not fn_assigned:
            fn_for_para = fn_filtered
            fn_assigned = True
        else:
            fn_for_para = ""
        bbox_idx = len(tasks)
        tasks.append((len(tasks), hlevel, text, cross, fn_for_para, bbox_idx))

    if not tasks:
        raise RuntimeError(f"第{target_bp}页未找到有效内容")

    # 并发翻译（max_workers=4）
    results = [None] * len(tasks)

    def _do_translate(idx, hlevel, text, fn):
        return idx, translate_paragraph(
            para_text=text,
            para_pages=str(target_bp),
            footnotes=fn if hlevel == 0 else "",
            glossary=glossary,
            **t_args,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_do_translate, idx, hlevel, text, fn): (idx, hlevel, text, cross, bbox_idx)
            for idx, hlevel, text, cross, fn, bbox_idx in tasks
        }
        for future in as_completed(futures):
            idx, hlevel, text, cross, bbox_idx = futures[future]
            try:
                _, p = future.result()
            except Exception as e:
                p = {"original": text, "translation": f"[翻译失败: {e}]",
                     "footnotes": "", "footnotes_translation": ""}
            total_usage = _merge_usage(total_usage, p.get("_usage"))
            results[idx] = {
                "original": _ensure_str(p.get("original", text)),
                "translation": _ensure_str(p.get("translation", "")),
                "footnotes": _ensure_str(p.get("footnotes", "")),
                "footnotes_translation": _ensure_str(p.get("footnotes_translation", "")),
                "heading_level": hlevel,
                "pages": str(target_bp),
                "_rawText": text,
                "_startBP": target_bp,
                "_endBP": target_bp,
                "_cross_page": cross,
                "_bboxes": para_bboxes[bbox_idx] if bbox_idx < len(para_bboxes) else [],
            }

    page_entries = [r for r in results if r is not None]

    return {
        "_pageBP": target_bp,
        "_model": model_key,
        "_usage": total_usage,
        "_page_entries": page_entries,
        "pages": str(target_bp),
    }


def translate_page_stream(pages, target_bp, model_key, t_args, glossary, doc_id: str, stop_checker=None):
    """流式翻译指定页面：逐段推送增量，但仅在整页完成后返回 entry。"""
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

    fn_filtered = ctx["footnotes"]
    para_bboxes = get_paragraph_bboxes(pages, target_bp, paragraphs)
    page_entries = []
    fn_assigned = False

    translate_push("stream_page_init", {
        "doc_id": doc_id,
        "bp": target_bp,
        "para_total": len(paragraphs),
    })
    _save_stream_draft(
        doc_id,
        active=True,
        bp=target_bp,
        para_idx=0 if paragraphs else None,
        para_total=len(paragraphs),
        para_done=0,
        paragraphs=[""] * len(paragraphs),
        status="streaming",
        note="当前页正在流式翻译，完整结束后才会写入硬盘。",
        last_error="",
    )

    for para_idx, para in enumerate(paragraphs):
        if stop_checker and stop_checker():
            translate_push("stream_page_aborted", {
                "doc_id": doc_id,
                "bp": target_bp,
                "para_idx": para_idx,
            })
            snapshot = _load_translate_state(doc_id)
            draft = _default_stream_draft_state()
            draft.update(snapshot.get("draft") or {})
            _save_stream_draft(
                doc_id,
                active=False,
                bp=target_bp,
                para_idx=para_idx,
                para_total=len(paragraphs),
                para_done=min(len(paragraphs), int(draft.get("para_done", 0) or 0)),
                paragraphs=draft.get("paragraphs", []),
                status="aborted",
                note="当前页已停止，草稿未提交到硬盘。",
            )
            raise TranslateStreamAborted("用户停止流式翻译")

        hlevel = para.get("heading_level", 0)
        text = para["text"].strip()
        cross = para.get("cross_page")
        if not text:
            continue

        if hlevel == 0 and not fn_assigned:
            fn_for_para = fn_filtered
            fn_assigned = True
        else:
            fn_for_para = ""

        partial_translation = []
        try:
            for event in stream_translate_paragraph(
                para_text=text,
                para_pages=str(target_bp),
                footnotes=fn_for_para if hlevel == 0 else "",
                glossary=glossary,
                stop_checker=stop_checker,
                **t_args,
            ):
                if event["type"] == "delta":
                    delta_text = event.get("text", "")
                    if delta_text:
                        partial_translation.append(delta_text)
                        snapshot = _load_translate_state(doc_id)
                        draft = _default_stream_draft_state()
                        draft.update(snapshot.get("draft") or {})
                        paragraphs_so_far = list(draft.get("paragraphs", []))
                        if len(paragraphs_so_far) < len(paragraphs):
                            paragraphs_so_far.extend([""] * (len(paragraphs) - len(paragraphs_so_far)))
                        paragraphs_so_far[para_idx] = "".join(partial_translation)
                        translate_push("stream_para_delta", {
                            "doc_id": doc_id,
                            "bp": target_bp,
                            "para_idx": para_idx,
                            "delta": delta_text,
                            "translation_so_far": "".join(partial_translation),
                        })
                        _save_stream_draft(
                            doc_id,
                            active=True,
                            bp=target_bp,
                            para_idx=para_idx,
                            para_total=len(paragraphs),
                            para_done=min(para_idx, int(draft.get("para_done", 0) or 0)),
                            paragraphs=paragraphs_so_far,
                            status="streaming",
                            note="当前页尚未提交到硬盘；停止后会丢弃这一页草稿。",
                            last_error="",
                        )
                elif event["type"] == "usage":
                    total_usage = _merge_usage(total_usage, event.get("usage"))
                    translate_push("stream_usage", {
                        "doc_id": doc_id,
                        "bp": target_bp,
                        "para_idx": para_idx,
                        "usage": event.get("usage", {}),
                    })
                elif event["type"] == "done":
                    p = event["result"]
                    page_entries.append({
                        "original": _ensure_str(p.get("original", text)),
                        "translation": _ensure_str(p.get("translation", "")),
                        "footnotes": _ensure_str(p.get("footnotes", "")),
                        "footnotes_translation": _ensure_str(p.get("footnotes_translation", "")),
                        "heading_level": hlevel,
                        "pages": str(target_bp),
                        "_rawText": text,
                        "_startBP": target_bp,
                        "_endBP": target_bp,
                        "_cross_page": cross,
                        "_bboxes": para_bboxes[para_idx] if para_idx < len(para_bboxes) else [],
                    })
                    translate_push("stream_para_done", {
                        "doc_id": doc_id,
                        "bp": target_bp,
                        "para_idx": para_idx,
                        "translation": _ensure_str(p.get("translation", "")),
                    })
                    snapshot = _load_translate_state(doc_id)
                    draft = _default_stream_draft_state()
                    draft.update(snapshot.get("draft") or {})
                    draft_paragraphs = list(draft.get("paragraphs", []))
                    if len(draft_paragraphs) < len(paragraphs):
                        draft_paragraphs.extend([""] * (len(paragraphs) - len(draft_paragraphs)))
                    draft_paragraphs[para_idx] = _ensure_str(p.get("translation", ""))
                    _save_stream_draft(
                        doc_id,
                        active=True,
                        bp=target_bp,
                        para_idx=para_idx,
                        para_total=len(paragraphs),
                        para_done=max(int(draft.get("para_done", 0) or 0), para_idx + 1),
                        paragraphs=draft_paragraphs,
                        status="streaming",
                        note="该段已完成，正在继续翻译后续段落。",
                        last_error="",
                    )
        except TranslateStreamAborted:
            translate_push("stream_page_aborted", {
                "doc_id": doc_id,
                "bp": target_bp,
                "para_idx": para_idx,
            })
            snapshot = _load_translate_state(doc_id)
            draft = _default_stream_draft_state()
            draft.update(snapshot.get("draft") or {})
            _save_stream_draft(
                doc_id,
                active=False,
                bp=target_bp,
                para_idx=para_idx,
                para_total=len(paragraphs),
                para_done=min(len(paragraphs), int(draft.get("para_done", 0) or 0)),
                paragraphs=draft.get("paragraphs", []),
                status="aborted",
                note="当前页已停止，草稿未提交到硬盘。",
            )
            raise
        except Exception as e:
            error_text = f"[翻译失败: {e}]"
            page_entries.append({
                "original": text,
                "translation": error_text,
                "footnotes": "",
                "footnotes_translation": "",
                "heading_level": hlevel,
                "pages": str(target_bp),
                "_rawText": text,
                "_startBP": target_bp,
                "_endBP": target_bp,
                "_cross_page": cross,
                "_bboxes": para_bboxes[para_idx] if para_idx < len(para_bboxes) else [],
            })
            snapshot = _load_translate_state(doc_id)
            draft = _default_stream_draft_state()
            draft.update(snapshot.get("draft") or {})
            draft_paragraphs = list(draft.get("paragraphs", []))
            if len(draft_paragraphs) < len(paragraphs):
                draft_paragraphs.extend([""] * (len(paragraphs) - len(draft_paragraphs)))
            draft_paragraphs[para_idx] = error_text
            _save_stream_draft(
                doc_id,
                active=True,
                bp=target_bp,
                para_idx=para_idx,
                para_total=len(paragraphs),
                para_done=max(int(draft.get("para_done", 0) or 0), para_idx + 1),
                paragraphs=draft_paragraphs,
                status="streaming",
                note="该段翻译失败，已记录失败占位文本。",
                last_error=str(e),
            )

    if not page_entries:
        raise RuntimeError(f"第{target_bp}页未找到有效内容")

    _save_stream_draft(
        doc_id,
        active=False,
        bp=target_bp,
        para_idx=(len(paragraphs) - 1) if paragraphs else None,
        para_total=len(paragraphs),
        para_done=len(page_entries),
        paragraphs=[_ensure_str(entry.get("translation", "")) for entry in page_entries],
        status="done",
        note="当前页已完整提交到硬盘。",
        last_error="",
    )

    return {
        "_pageBP": target_bp,
        "_model": model_key,
        "_usage": total_usage,
        "_page_entries": page_entries,
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
        "total_pages": 0,
        "done_pages": 0,
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


def _get_translate_state_path(doc_id: str) -> str:
    """获取翻译状态文件路径。"""
    if not doc_id:
        return ""
    from config import get_doc_dir
    d = get_doc_dir(doc_id)
    if not d:
        return ""
    return os.path.join(d, "translate_state.json")


def _save_translate_state(doc_id: str, running: bool, stop_requested: bool, **extra):
    """保存翻译状态到磁盘。"""
    path = _get_translate_state_path(doc_id)
    if not path:
        return
    try:
        state = _load_translate_state(doc_id)
        state.update(extra)
        state["doc_id"] = doc_id
        state["running"] = running
        state["stop_requested"] = stop_requested
        if "phase" not in extra:
            state["phase"] = "stopping" if stop_requested else ("running" if running else state.get("phase", "idle"))
        state["total_tokens"] = state.get("prompt_tokens", 0) + state.get("completion_tokens", 0)
        state["updated_at"] = time.time()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass


def _load_translate_state(doc_id: str) -> dict:
    """从磁盘加载翻译状态。"""
    default = _default_translate_state(doc_id)
    path = _get_translate_state_path(doc_id)
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return default
            default.update(data)
            default["doc_id"] = doc_id
            draft = default.get("draft")
            if not isinstance(draft, dict):
                draft = {}
            merged_draft = _default_stream_draft_state()
            merged_draft.update(draft)
            if not isinstance(merged_draft.get("paragraphs"), list):
                merged_draft["paragraphs"] = []
            default["draft"] = merged_draft
            if not isinstance(default.get("failed_bps"), list):
                default["failed_bps"] = []
            if not isinstance(default.get("failed_pages"), list):
                default["failed_pages"] = []
            default["total_tokens"] = default.get("prompt_tokens", 0) + default.get("completion_tokens", 0)
            return default
    except Exception:
        return default


def _clear_translate_state(doc_id: str):
    """清除磁盘上的翻译状态。"""
    path = _get_translate_state_path(doc_id)
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def _save_stream_draft(doc_id: str, **fields):
    if not doc_id:
        return
    snapshot = _load_translate_state(doc_id)
    draft = _default_stream_draft_state()
    draft.update(snapshot.get("draft") or {})
    draft.update(fields)
    paragraphs = draft.get("paragraphs")
    draft["paragraphs"] = list(paragraphs) if isinstance(paragraphs, list) else []
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
    with _translate_lock:
        if _translate_task["doc_id"] == doc_id:
            state["running"] = _translate_task["running"]
            state["stop_requested"] = _translate_task["stop"]
            if state["running"] and state["phase"] not in ("running", "stopping"):
                state["phase"] = "stopping" if state["stop_requested"] else "running"
    state["total_tokens"] = state.get("prompt_tokens", 0) + state.get("completion_tokens", 0)
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
        total_pages=0,
        done_pages=0,
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
        glossary = get_glossary()

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
        done_bps = set()
        for e in entries:
            pbp = e.get("_pageBP")
            if pbp is not None and pbp in doc_bp_set:
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
            total_pages=total_pages,
            done_pages=done_pages,
            pending_pages=max(0, total_pages - done_pages),
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
            failed_pages=[],
            draft=_default_stream_draft_state(),
        )

        for i, bp in enumerate(pending_bps):
            should_stop = False
            with _translate_lock:
                should_stop = _translate_task["stop"]
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
                    pending_pages=max(0, state_total - state_done),
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
            _save_translate_state(
                doc_id,
                running=True,
                stop_requested=snapshot.get("stop_requested", False),
                phase="stopping" if snapshot.get("stop_requested", False) else "running",
                total_pages=state_total,
                done_pages=state_done,
                pending_pages=max(0, state_total - state_done),
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
                next_done_pages = min(state_total, snapshot_done + 1)
                translated_chars = snapshot.get("translated_chars", 0) + char_count
                translated_paras = snapshot.get("translated_paras", 0) + para_count
                request_count = snapshot.get("request_count", 0) + int(entry_usage.get("request_count", 0) or 0)
                prompt_tokens = snapshot.get("prompt_tokens", 0) + int(entry_usage.get("prompt_tokens", 0) or 0)
                completion_tokens = snapshot.get("completion_tokens", 0) + int(entry_usage.get("completion_tokens", 0) or 0)

                _save_translate_state(
                    doc_id,
                    running=True,
                    stop_requested=snapshot.get("stop_requested", False),
                    phase="stopping" if snapshot.get("stop_requested", False) else "running",
                    total_pages=state_total,
                    done_pages=next_done_pages,
                    pending_pages=max(0, state_total - next_done_pages),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=translated_chars,
                    translated_paras=translated_paras,
                    request_count=request_count,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    model=model_key,
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
                    pending_pages=max(0, state_total - state_done),
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
                _save_translate_state(
                    doc_id,
                    running=True,
                    stop_requested=snapshot.get("stop_requested", False),
                    phase="stopping" if snapshot.get("stop_requested", False) else "running",
                    total_pages=state_total,
                    done_pages=state_done,
                    pending_pages=max(0, state_total - state_done),
                    current_bp=bp,
                    current_page_idx=current_page_idx,
                    translated_chars=snapshot.get("translated_chars", 0),
                    translated_paras=snapshot.get("translated_paras", 0),
                    request_count=snapshot.get("request_count", 0),
                    prompt_tokens=snapshot.get("prompt_tokens", 0),
                    completion_tokens=snapshot.get("completion_tokens", 0),
                    model=model_key,
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
        _save_translate_state(
            doc_id,
            running=False,
            stop_requested=False,
            phase="done",
            total_pages=state_total,
            done_pages=state_done,
            pending_pages=max(0, state_total - state_done),
            current_bp=snapshot.get("current_bp"),
            current_page_idx=snapshot.get("current_page_idx", state_total),
            translated_chars=snapshot.get("translated_chars", 0),
            translated_paras=snapshot.get("translated_paras", 0),
            request_count=snapshot.get("request_count", 0),
            prompt_tokens=snapshot.get("prompt_tokens", 0),
            completion_tokens=snapshot.get("completion_tokens", 0),
            model=snapshot.get("model", model_key),
            last_error="",
        )
        entries, _, _ = load_entries_from_disk(doc_id)
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
            pending_pages=max(0, state_total - state_done),
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

        # Step 4: 保存（覆盖 pages.json，保留 entries.json）
        task_push(task_id, "progress", {"pct": 95, "label": "保存数据…", "detail": ""})
        save_pages_to_disk(final_pages, file_name, doc_id)

        first, last = get_page_range(final_pages)
        summary = f"重新解析完成！{len(final_pages)}页 (p.{first}-{last})"
        task_push(task_id, "done", {"summary": summary, "logs": all_logs})

    except Exception as e:
        task_push(task_id, "error_msg", {"error": f"重新解析失败: {e}"})


def reparse_single_page(task_id: str, doc_id: str, target_bp: int, file_idx: int):
    """后台线程：对单页重新执行 OCR 解析（保留翻译数据）。"""
    from pdf_extract import extract_single_page_pdf, extract_pdf_text, combine_sources

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

        # PDF文字层提取
        task_push(task_id, "progress", {"pct": 75, "label": "提取 PDF 文字层…", "detail": ""})
        pdf_pages = extract_pdf_text(single_page_bytes)
        if pdf_pages:
            combined = combine_sources([new_page], pdf_pages)
            new_page = combined["pages"][0]

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

        summary = f"第 {target_bp} 页重新解析完成"
        task_push(task_id, "done", {"summary": summary, "bp": target_bp})

    except Exception as e:
        task_push(task_id, "error_msg", {"error": f"重新解析失败: {e}"})

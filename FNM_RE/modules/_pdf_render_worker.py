"""微进程 PDF 渲染器：每次调用渲染单页 → stdout 输出 JSON → exit，OS 回收全部内存。

模式：
  sup_l3_clip   — 5x、正文裁剪、PNG（复刻 sup_recovery._vision_find_superscript）
  repair_page  — 1.3x、全页、JPEG（复刻 llm_repair._render_repair_page_image）

JSON 输出字段：
  data_url, mime       — 渲染结果（成功时）
  render_ms            — 渲染耗时（不含 subprocess 启动开销）
  bytes_len            — 图像字节数（base64 编码前）
  peak_rss_mb          — 微进程峰值 RSS
  error                — 失败原因

不做任何 LLM 调用，不 import sup_recovery / llm_repair。
"""
import json, sys, time, resource


def _render_sup_l3(pdf_path: str, page_no: int) -> dict:
    t0 = time.monotonic()
    import fitz as _fitz
    doc = _fitz.open(pdf_path)
    try:
        page = doc[page_no - 1]
        rect = page.rect
        text_rect = _fitz.Rect(rect.x0 + 30, rect.y0 + 40, rect.x1 - 30, rect.y1 - 50)
        mat = _fitz.Matrix(5.0, 5.0)
        pix = page.get_pixmap(matrix=mat, clip=text_rect)
        img_bytes = pix.tobytes("png")
        pix = None
    finally:
        doc.close()
    import base64
    return {
        "data_url": "data:image/png;base64," + base64.b64encode(img_bytes).decode(),
        "mime": "image/png",
        "render_ms": int((time.monotonic() - t0) * 1000),
        "bytes_len": len(img_bytes),
        "peak_rss_mb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
    }


def _render_repair_page(pdf_path: str, file_idx: int) -> dict:
    t0 = time.monotonic()
    import fitz
    doc = fitz.open(pdf_path)
    try:
        if file_idx < 0 or file_idx >= len(doc):
            return {"error": f"page {file_idx} out of range (0-{len(doc)-1})"}
        page = doc[file_idx]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)
        img = pix.tobytes("jpg")
        pix = None
    finally:
        doc.close()
    import base64
    return {
        "data_url": "data:image/jpeg;base64," + base64.b64encode(img).decode(),
        "mime": "image/jpeg",
        "render_ms": int((time.monotonic() - t0) * 1000),
        "bytes_len": len(img),
        "peak_rss_mb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
    }


def main():
    params = json.loads(sys.stdin.buffer.read())
    mode = str(params.get("mode") or "")
    pdf_path = str(params.get("pdf_path") or "")
    if not pdf_path:
        sys.stdout.buffer.write(json.dumps({"error": "missing pdf_path"}).encode())
        return

    try:
        if mode == "sup_l3_clip":
            result = _render_sup_l3(pdf_path, int(params.get("page_no") or 0))
        elif mode == "repair_page":
            result = _render_repair_page(pdf_path, int(params.get("file_idx") or 0))
        else:
            result = {"error": f"unknown mode: {mode}"}
    except Exception as exc:
        result = {"error": str(exc)}

    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode())


if __name__ == "__main__":
    main()

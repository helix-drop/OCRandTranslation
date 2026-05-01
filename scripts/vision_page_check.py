#!/usr/bin/env python3
"""视觉模型 PDF 页面核对工具。

用法:
  python3 scripts/vision_page_check.py <doc_id> <book_page> <检查类型>

检查类型:
  - notes: 检查该页的尾注/脚注标记是否正确
  - headings: 检查该页的标题层级
  - content: 检查该页内容与 OCR 的一致性
  - anchors: 检查该页正文中的尾注锚点编号
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openai import OpenAI
from document.pdf_extract import render_pdf_page
from persistence.storage import get_pdf_path, resolve_visual_model_spec


def _image_to_data_url(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def call_vision(
    prompt: str,
    images: list[bytes],
    *,
    model_spec=None,
    max_tokens: int = 2000,
) -> dict[str, Any]:
    if model_spec is None:
        model_spec = resolve_visual_model_spec()

    client = OpenAI(
        api_key=str(getattr(model_spec, "api_key", "") or "").strip(),
        base_url=str(getattr(model_spec, "base_url", "") or "").strip(),
    )
    content = [{"type": "text", "text": prompt}]
    for img in images:
        data_url = _image_to_data_url(img)
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    response = client.chat.completions.create(
        model=str(getattr(model_spec, "model_id", "") or "").strip(),
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
    )
    return {
        "content": response.choices[0].message.content,
        "model": response.model,
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        } if response.usage else {},
    }


def check_page_notes(doc_id: str, book_page: int) -> dict:
    """检查指定页的尾注/脚注标记。"""
    pdf_path = get_pdf_path(doc_id)
    if not pdf_path:
        return {"error": "PDF not found"}

    # 从 raw_pages 获取 fileIdx
    from persistence.sqlite_store import SQLiteRepository
    repo = SQLiteRepository()
    pages = repo.load_pages(doc_id)
    file_to_book = {}
    for p in (pages or []):
        fi = int(p.get("fileIdx") or -1)
        bp = int(p.get("bookPage") or 0)
        if fi >= 0 and bp > 0:
            file_to_book[bp] = fi

    file_idx = file_to_book.get(book_page)
    if file_idx is None:
        # fallback: book_page == file_idx + 1
        file_idx = book_page - 1

    img_bytes = render_pdf_page(pdf_path, file_idx, scale=1.8)

    prompt = f"""这是书籍 "The Post-Revolutionary Self" (Goldstein, 2005) 的印刷页第 {book_page} 页。

请仔细检查这一页：
1. 正文中是否有上标数字（superscript numbers）作为尾注标记？如果有，列出每个标记的编号（如 1, 2, 3...）和它们所在的段落大意（前10个词）。
2. 页面底部是否有脚注（footnotes，用 * ** † ‡ 等符号标记的）？
3. 是否有任何图片说明（figure/illustration captions）被标注为注释？
4. OCR 可能遗漏或误识的标记有哪些？

请用 JSON 格式返回：
{{"page": {book_page}, "endnote_markers": [{{"number": 1, "context": "前几个词..."}}], "footnote_markers": [], "has_figure_captions": false, "ocr_warnings": []}}"""

    return call_vision(prompt, [img_bytes], max_tokens=1500)


def check_page_headings(doc_id: str, book_page: int) -> dict:
    """检查指定页的标题层级。"""
    pdf_path = get_pdf_path(doc_id)
    from persistence.sqlite_store import SQLiteRepository
    repo = SQLiteRepository()
    pages = repo.load_pages(doc_id)
    file_to_book = {}
    for p in (pages or []):
        fi = int(p.get("fileIdx") or -1)
        bp = int(p.get("bookPage") or 0)
        if fi >= 0 and bp > 0:
            file_to_book[bp] = fi
    file_idx = file_to_book.get(book_page, book_page - 1)

    img_bytes = render_pdf_page(pdf_path, file_idx, scale=1.8)

    prompt = f"""这是书籍 "The Post-Revolutionary Self" (Goldstein, 2005) 的印刷页第 {book_page} 页。

请分析这一页的标题和文本结构：
1. 这一页是否有章标题、节标题或子标题？如果有，列出层级关系。
2. 标题是居中、左对齐还是缩进？
3. 这一页的文本属于哪个章节/小节？
4. 是否有跨页的段落（从上一页延续或延续到下一页）？

请用 JSON 格式返回。"""

    return call_vision(prompt, [img_bytes], max_tokens=1000)


def check_page_ocr_quality(doc_id: str, book_page: int) -> dict:
    """对比 OCR 文本和 PDF 原页面，找出 OCR 错误。"""
    pdf_path = get_pdf_path(doc_id)
    from persistence.sqlite_store import SQLiteRepository
    repo = SQLiteRepository()
    pages = repo.load_pages(doc_id)
    file_to_book = {}
    ocr_text = ""
    for p in (pages or []):
        fi = int(p.get("fileIdx") or -1)
        bp = int(p.get("bookPage") or 0)
        if fi >= 0 and bp > 0:
            file_to_book[bp] = fi
        if bp == book_page:
            md = p.get("markdown", "")
            if isinstance(md, dict):
                ocr_text = str(md.get("text", ""))
            else:
                ocr_text = str(md)

    file_idx = file_to_book.get(book_page, book_page - 1)
    img_bytes = render_pdf_page(pdf_path, file_idx, scale=1.8)

    ocr_preview = ocr_text[:800].replace('\n', ' ')

    prompt = f"""这是书籍 "The Post-Revolutionary Self" 的印刷页第 {book_page} 页。

OCR 识别的文本开头是：
"{ocr_preview}"

请对比 PDF 页面图像和 OCR 文本，找出至少 3 处 OCR 错误（如果有的话）。关注：
1. 特殊字符误识（法语重音、引号、破折号）
2. 上标数字是否正确识别
3. 斜体/粗体词是否被保留
4. 人名、书名拼写是否准确
5. 段落边界是否正确

请用 JSON 格式返回错误列表。"""

    return call_vision(prompt, [img_bytes], max_tokens=1500)


CHECK_TYPES = {
    "notes": check_page_notes,
    "headings": check_page_headings,
    "ocr": check_page_ocr_quality,
}


def main():
    parser = argparse.ArgumentParser(description="视觉模型 PDF 页面核对")
    parser.add_argument("doc_id", help="文档 ID")
    parser.add_argument("book_page", type=int, help="印刷页号")
    parser.add_argument("check_type", choices=list(CHECK_TYPES), help="检查类型")
    parser.add_argument("--output", "-o", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    checker = CHECK_TYPES[args.check_type]
    result = checker(args.doc_id, args.book_page)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

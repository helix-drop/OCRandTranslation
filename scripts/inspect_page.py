#!/usr/bin/env python3
"""FNM 调试辅助：渲染 PDF 页面并调用视觉模型分析。

用法:
  # 检查单页
  .venv/bin/python scripts/inspect_page.py --slug Biopolitics --page 104

  # 检查连续多页
  .venv/bin/python scripts/inspect_page.py --slug Goldstein --page 160 --range 3

  # 使用自定义 prompt
  .venv/bin/python scripts/inspect_page.py --slug Biopolitics --page 111 \
      --prompt "这个页面是否有 ## NOTES 标题？列出所有编号的注释条目。"

  # 对比正文页和注释页
  .venv/bin/python scripts/inspect_page.py --slug Biopolitics --page 104 --compare 111

输出：每页保存 rendered_page_XXX.jpg + analysis.json 到 /tmp/fnm_inspect/
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_OUTPUT_DIR = Path("/tmp/fnm_inspect")


def _slug_to_doc_id(slug: str) -> str:
    from example_manifest import select_example_books
    books = select_example_books(slug=slug)
    if not books:
        raise SystemExit(f"未找到 slug={slug}")
    from persistence.sqlite_store import SQLiteRepository
    repo = SQLiteRepository()
    doc = repo.find_document(slug=books[0].slug, folder=books[0].folder)
    if not doc:
        raise SystemExit(f"未在 DB 中找到文档: {slug}")
    return doc.get("doc_id", "")


def _resolve_page(slug: str, page_no: int) -> dict:
    doc_id = _slug_to_doc_id(slug)
    from persistence.sqlite_store import SQLiteRepository
    repo = SQLiteRepository()
    pages = repo.load_pages(doc_id)
    for p in pages:
        if int(p.get("bookPage") or 0) == page_no:
            return {"page": dict(p), "doc_id": doc_id}
    raise SystemExit(f"未找到页面: slug={slug} page={page_no}")


def _render_page(pdf_path: str, file_idx: int) -> tuple[bytes, str]:
    from FNM_RE.llm_repair import _render_repair_page_image
    img_bytes, mime = _render_repair_page_image(pdf_path, file_idx)
    if not img_bytes:
        raise SystemExit(f"渲染失败: {pdf_path} file_idx={file_idx}")
    return img_bytes, mime


def _call_visual_model(
    image_b64: str,
    image_mime: str,
    prompt: str,
    *,
    model_args: dict | None = None,
) -> dict[str, Any]:
    from openai import OpenAI
    from FNM_RE.llm_repair import _resolve_repair_model_args
    from translation.translator import _merge_overrides_into_chat_kwargs

    args = dict(model_args or _resolve_repair_model_args())
    client = OpenAI(
        api_key=str(args.get("api_key") or ""),
        base_url=str(args.get("base_url") or ""),
        timeout=120.0,
    )
    content: list[dict] = [
        {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_b64}"}},
        {"type": "text", "text": prompt},
    ]
    create_kwargs: dict = {
        "model": str(args.get("model_id") or ""),
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": "你是一个学术书籍页面分析助手。请仔细观察图片并回答用户问题。直接给出分析结果，不要解释思考过程。"},
            {"role": "user", "content": content},
        ],
    }
    request_overrides = dict(args.get("request_overrides") or {})
    if not request_overrides and str(args.get("provider") or "").strip().lower() == "qwen":
        request_overrides = {"extra_body": {"enable_thinking": False}}
    _merge_overrides_into_chat_kwargs(create_kwargs, request_overrides)

    started = datetime.now()
    response = client.chat.completions.create(**create_kwargs)
    elapsed = (datetime.now() - started).total_seconds()
    text = response.choices[0].message.content or ""
    usage = {}
    if hasattr(response, "usage") and response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    return {"text": text.strip(), "usage": usage, "elapsed_seconds": round(elapsed, 1)}


def _format_page_summary(page_data: dict) -> str:
    p = page_data.get("page", page_data)
    md = p.get("markdown")
    if isinstance(md, dict):
        md_text = md.get("text", "")
    else:
        md_text = str(md or "")
    note_scan = p.get("_note_scan", {})
    return textwrap.dedent(f"""\
    页码: {p.get('bookPage')}  fileIdx: {p.get('fileIdx')}  pdfPage: {p.get('pdfPage')}
    page_kind: {note_scan.get('page_kind', 'N/A')}
    note_scan items: {len(note_scan.get('items', []))}
    fnBlocks: {len(p.get('fnBlocks') or [])}
    footnotes field: {bool(p.get('footnotes', ''))}
    markdown 长度: {len(md_text)}
    markdown 前 500 字: {md_text[:500]}
    """)


def _save_result(label: str, image_bytes: bytes, analysis: dict) -> Path:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    img_path = _OUTPUT_DIR / f"{label}.jpg"
    img_path.write_bytes(image_bytes)
    analysis_path = _OUTPUT_DIR / f"{label}_analysis.json"
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    return analysis_path


def _build_default_prompt(page_summary: str) -> str:
    return textwrap.dedent(f"""\
    请分析这个学术书籍页面：
    1. 页面顶部是否有 "Notes"/"Endnotes"/"NOTES" 标题？
    2. 页面上有哪些编号条目（如 "1. xxx"、"2. xxx"）？列出编号和文本摘要。
    3. 页面底部是否有脚注？脚注用什么标记（数字、星号 *、† 等）？
    4. 正文中是否有上标数字（如 $^{{17}}$ 或 <sup>18</sup>）？列出前 5 个。
    5. 这个页面是正文页、尾注页还是脚注页？

    页面程序数据摘要：
    {page_summary}
    """)


def main() -> int:
    parser = argparse.ArgumentParser(description="FNM 调试：PDF 页面视觉分析")
    parser.add_argument("--slug", required=True, help="书名 slug")
    parser.add_argument("--page", type=int, required=True, help="起始页码 (bookPage)")
    parser.add_argument("--range", type=int, default=1, help="连续检查页数")
    parser.add_argument("--prompt", default="", help="自定义 prompt（留空用默认分析）")
    parser.add_argument("--compare", type=int, default=0, help="对比页（如注释页 vs 正文页）")
    parser.add_argument("--no-vision", action="store_true", help="只导出页面数据，不调视觉模型")
    args = parser.parse_args()

    results: list[dict] = []
    for offset in range(max(1, args.range)):
        page_no = args.page + offset
        try:
            resolved = _resolve_page(args.slug, page_no)
        except SystemExit:
            print(f"跳过 p.{page_no}（未找到）")
            continue

        page_data = resolved["page"]
        doc_id = resolved["doc_id"]
        file_idx = int(page_data.get("fileIdx", max(0, page_no - 1)))
        from persistence.storage import get_pdf_path
        pdf_path = get_pdf_path(doc_id)
        if not pdf_path or not os.path.exists(pdf_path):
            print(f"p.{page_no}: PDF 不存在 ({pdf_path})")
            continue

        summary = _format_page_summary(page_data)
        print(f"\n{'='*60}")
        print(f"p.{page_no} — {args.slug}")
        print(summary)

        try:
            img_bytes, img_mime = _render_page(pdf_path, file_idx)
        except SystemExit as e:
            print(f"  渲染失败: {e}")
            continue
        print(f"  渲染: {len(img_bytes)} bytes ({img_mime})")

        analysis: dict = {"page_no": page_no, "slug": args.slug, "doc_id": doc_id}

        if not args.no_vision:
            prompt = args.prompt or _build_default_prompt(summary)
            print(f"  调用视觉模型...")
            try:
                result = _call_visual_model(
                    base64.b64encode(img_bytes).decode("ascii"),
                    img_mime,
                    prompt,
                )
                analysis["vision_response"] = result["text"]
                analysis["vision_usage"] = result.get("usage", {})
                analysis["vision_elapsed"] = result.get("elapsed_seconds", 0)
                print(f"  视觉模型回复 ({result.get('elapsed_seconds', 0)}s, "
                      f"tokens={result.get('usage', {}).get('total_tokens', '?')}):")
                print(f"  {result['text'][:600]}")
            except Exception as exc:
                print(f"  视觉模型调用失败: {exc}")
                analysis["vision_error"] = str(exc)

        label = f"p{page_no:04d}_{args.slug}"
        result_path = _save_result(label, img_bytes, analysis)
        print(f"  结果: {result_path}")
        results.append(analysis)

    if args.compare:
        try:
            resolved2 = _resolve_page(args.slug, args.compare)
        except SystemExit:
            print(f"对比页 p.{args.compare} 未找到")
            return 1
        page_data2 = resolved2["page"]
        file_idx2 = int(page_data2.get("fileIdx", max(0, args.compare - 1)))
        from persistence.storage import get_pdf_path
        pdf_path2 = get_pdf_path(resolved2["doc_id"])
        summary2 = _format_page_summary(page_data2)
        print(f"\n{'='*60}")
        print(f"对比页 p.{args.compare}")
        print(summary2)

        try:
            img_bytes2, mime2 = _render_page(pdf_path2, file_idx2)
        except SystemExit:
            img_bytes2, mime2 = b"", ""
        if img_bytes2:
            label2 = f"p{args.compare:04d}_{args.slug}"
            _save_result(label2, img_bytes2, {"page_no": args.compare, "slug": args.slug})

    # 写入汇总
    summary_path = _OUTPUT_DIR / f"summary_{args.slug}_p{args.page}.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n汇总: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

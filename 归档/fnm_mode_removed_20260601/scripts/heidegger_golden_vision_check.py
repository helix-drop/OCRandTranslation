#!/usr/bin/env python3
"""Heidegger golden 底本视觉核对。

对任意章节 PDF 渲染指定页，复用仓库已有视觉模型调用路径，
并强制使用 builtin:gemini-3.1-flash-lite。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from document.pdf_extract import render_pdf_page
from persistence.storage import resolve_visual_model_spec
from scripts.vision_page_check import call_vision


def _parse_pages(raw: str) -> list[int]:
    pages: list[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(part))
    return pages


def _build_prompt(labels: list[str], focus: str, mode: str) -> str:
    joined = "\n".join(f"- {label}" for label in labels)
    if mode == "transcribe":
        return f"""你正在逐页转录 Dominique Janicaud《Heidegger en France》的 PDF 页面图像。

图片顺序如下：
{joined}

请只依据图像转录，不要依赖 OCR 或已有 Markdown。要求：
1. 按页面和正常阅读顺序逐行转录可见文本。
   如果页面为双栏或多栏，先完整转录左栏自上而下，再转录右栏自上而下，不要把两栏同行合并。
2. 忽略页眉中的书名/章节名和独立页码，但保留真正的章节标题、小节标题、书目条目、索引条目、目录条目。
3. 保留法文重音、德文词、作者大写、小型大写无法表达时用普通大写。
4. 不要纠正作者原文，只纠正图像能明确显示的 OCR 误读。
5. 如果某处看不清，用 "[illisible]" 标出，不要猜。

额外关注：{focus or "逐行转录，保留条目边界。"}

请返回严格 JSON，不要 Markdown 包裹，结构如下：
{{
  "pages": [
    {{
      "label": "图片标签",
      "printed_page": "可见页码或空字符串",
      "lines": ["逐行文本"],
      "uncertain": ["看不清或需要人工复核的位置"]
    }}
  ]
}}"""
    return f"""你正在核对 Dominique Janicaud《Heidegger en France》的章节 PDF 页面图像。

图片顺序如下：
{joined}

请只依据图像回答，不要依赖 OCR 或已有 Markdown。重点核对：
1. 页眉、章标题、节标题，以及它们在页面中的层级。
2. 正文段落边界：按阅读顺序列出每个可见正文段落的开头 8-15 个词；如果段落从上一页延续或延续到下一页，请标明。
3. 页面底部脚注：列出每条脚注 marker 和开头 12-20 个词。
4. 正文中的上标注释引用：列出可见编号及其附近短语。
5. 明显 OCR/Markdown 风险：如多段被粘成一段、脚注定义漏掉、脚注编号和正文引用不对应。

额外关注：{focus or "段落切分、脚注编号、标题层级是否能作为 golden 修正依据。"}

请返回严格 JSON，不要 Markdown 包裹，结构如下：
{{
  "pages": [
    {{
      "label": "图片标签",
      "printed_page": "可见页码或空字符串",
      "headings": [{{"level": "chapter|section|subsection|running_header|unknown", "text": "...", "position": "top|body|footer"}}],
      "paragraph_starts": [{{"text": "...", "continues_from_previous": false, "continues_to_next": false}}],
      "body_note_refs": [{{"marker": "1", "context": "..."}}],
      "footnotes": [{{"marker": "1", "text_start": "..."}}],
      "risks": ["..."]
    }}
  ],
  "correction_guidance": ["..."]
}}"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Heidegger golden 视觉核对")
    parser.add_argument("--pdf", required=True, help="章节 PDF 路径")
    parser.add_argument("--chapter", required=True, help="章节标签，如 ch08")
    parser.add_argument("--pages", required=True, help="1-based 页码，支持 1,2,5-7")
    parser.add_argument("--focus", default="", help="本次核对重点")
    parser.add_argument(
        "--mode",
        choices=["check", "transcribe"],
        default="check",
        help="check=结构核对；transcribe=逐行转录",
    )
    parser.add_argument("--out", required=True, help="输出 JSON 路径")
    parser.add_argument("--image-dir", default="", help="可选：保存渲染 PNG 的目录")
    parser.add_argument("--scale", type=float, default=1.8)
    parser.add_argument("--max-tokens", type=int, default=6000)
    args = parser.parse_args()

    pdf = Path(args.pdf)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    image_dir = Path(args.image_dir) if args.image_dir else None
    if image_dir:
        image_dir.mkdir(parents=True, exist_ok=True)

    pages = _parse_pages(args.pages)
    images: list[bytes] = []
    labels: list[str] = []
    for page_no in pages:
        label = f"{args.chapter} PDF page {page_no}"
        image = render_pdf_page(str(pdf), page_no - 1, scale=args.scale)
        images.append(image)
        labels.append(label)
        if image_dir:
            (image_dir / f"{args.chapter}_p{page_no:03d}.png").write_bytes(image)

    spec = resolve_visual_model_spec("builtin:gemini-3.1-flash-lite")
    result = call_vision(
        _build_prompt(labels, args.focus, args.mode),
        images,
        model_spec=spec,
        max_tokens=args.max_tokens,
    )
    payload = {
        "pdf": str(pdf),
        "chapter": args.chapter,
        "pages": pages,
        "model": {
            "provider": spec.provider,
            "model_id": spec.model_id,
            "rate_limits": spec.rate_limits,
        },
        "result": result,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

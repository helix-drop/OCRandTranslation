"""Phase 3: bare_digit 假阳性的 LLM 视觉验证。

在 _positive_gate_bare_digit 之后，对条件 3（出现 >2 次）
或条件 4（非句末位置）被拒绝的候选，送 VLM 做语义判断。
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from openai import OpenAI

from FNM_RE.models import BodyAnchorRecord
from FNM_RE.llm_repair import _render_repair_page_image

_VERIFY_MAX_TOKENS = 1024
_LLM_TIMEOUT = 60.0
_MAX_CANDIDATES_PER_BOOK = 20

# 同页+同 marker 的 VLM 调用缓存
_VERIFY_CACHE: dict[tuple, dict] = {}


_LLM_SYSTEM_PROMPT = """\
You are an expert at reading academic book pages. Your task: determine whether \
a specific number on a page is a note/citation reference marker (endnote \
superscript) or just an ordinary number in the text.

A note reference marker is typically:
- A superscript number (smaller, raised) in the body text
- Located at the end of a sentence or clause
- Referencing a source in the endnotes/footnotes section

An ordinary number is:
- Part of a date, page number, or statistical figure
- Part of a proper name like "Article 7" or "Chapter 3"
- A list number or section number
- Any number that is the same font size as surrounding text

Return ONLY a JSON object:
{
  "is_note_marker": true or false,
  "confidence": "high" | "medium" | "low",
  "reasoning": "one brief sentence explaining your decision"
}"""


def _build_user_prompt(marker: int, source_text: str) -> str:
    snippet = (source_text or "")[:200]
    return (
        f"Look at this page image. The automated system detected the number"
        f" '{marker}' as a potential endnote reference marker"
        f" in this context: \"{snippet}\"\n\n"
        f"Is the number '{marker}' actually a superscript endnote marker"
        f" on this page, or is it just an ordinary number in the text?"
    )


def _render_page_cropped(
    pdf_path: str, page_no: int, pages: list[dict]
) -> tuple[bytes, str]:
    """渲染 PDF 页面为 JPEG（后续可扩展裁剪到 anchor 段落区域）。"""
    file_idx = page_no - 1
    for p in pages:
        try:
            if int(p.get("bookPage") or 0) == page_no:
                file_idx = int(p.get("fileIdx") or (page_no - 1))
                break
        except (TypeError, ValueError):
            continue
    try:
        return _render_repair_page_image(pdf_path, file_idx)
    except Exception:
        return (b"", "")


def _resolve_model_args() -> dict | None:
    try:
        from persistence.storage import resolve_visual_model_spec

        spec = resolve_visual_model_spec()
        if not spec or not str(spec.api_key or "").strip():
            return None
        return {
            "provider": str(getattr(spec, "provider", "") or "").strip(),
            "model_id": str(getattr(spec, "model_id", "") or "").strip(),
            "api_key": str(getattr(spec, "api_key", "") or "").strip(),
            "base_url": str(getattr(spec, "base_url", "") or "").strip(),
        }
    except Exception:
        return None


def _call_vision_for_bare_digit(
    pdf_path: str,
    page_no: int,
    pages: list[dict],
    marker: int,
    source_text: str,
    model_args: dict,
) -> dict:
    """对单个 bare_digit 候选做视觉验证（带缓存）。"""
    cache_key = (pdf_path, page_no, marker)
    if cache_key in _VERIFY_CACHE:
        return dict(_VERIFY_CACHE[cache_key])

    img_bytes, mime = _render_page_cropped(pdf_path, page_no, pages)
    if not img_bytes or not mime:
        result: dict = {"is_note_marker": False, "confidence": "low",
                         "reasoning": "page render failed", "error": "render_failed"}
        _VERIFY_CACHE[cache_key] = result
        return result

    encoded = base64.b64encode(img_bytes).decode("ascii")
    image_url = f"data:{mime};base64,{encoded}"

    client = OpenAI(
        api_key=str(model_args.get("api_key") or ""),
        base_url=str(model_args.get("base_url") or ""),
        timeout=_LLM_TIMEOUT,
    )

    resp = client.chat.completions.create(
        model=str(model_args.get("model_id") or ""),
        max_tokens=_VERIFY_MAX_TOKENS,
        messages=[
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": _build_user_prompt(marker, source_text)},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]},
        ],
    )

    raw = str(resp.choices[0].message.content or "")
    result = _parse_response(raw, marker)
    _VERIFY_CACHE[cache_key] = result
    return result


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _parse_response(raw: str, marker: int) -> dict:
    fenced = _JSON_BLOCK_RE.search(raw)
    text = fenced.group(1) if fenced else raw
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return {"is_note_marker": False, "confidence": "low",
                "reasoning": f"parse failed", "raw": raw[:200]}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"is_note_marker": False, "confidence": "low",
                "reasoning": "json error", "raw": raw[:200]}
    return {
        "is_note_marker": bool(parsed.get("is_note_marker", False)),
        "confidence": str(parsed.get("confidence", "low")),
        "reasoning": str(parsed.get("reasoning", "")),
    }


def verify_bare_digit_candidates(
    candidates: list[BodyAnchorRecord],
    *,
    pdf_path: str = "",
    pages: list[dict] | None = None,
    model_args: dict | None = None,
) -> tuple[list[BodyAnchorRecord], list[BodyAnchorRecord], dict]:
    """对 bare_digit 候选做 LLM 验证，返回 (accepted, rejected, summary)。

    candidates: 被条件 3/4 拒绝的 bare_digit 候选
    accepted: LLM 判定是真尾注标记的，应重新加入 anchor 列表
    rejected: LLM 确认是假阳性的
    """
    if not candidates or not pdf_path or not pages:
        return [], list(candidates), {"verified": 0, "accepted": 0, "rejected": 0}

    resolved_args = model_args or _resolve_model_args()
    if not resolved_args:
        return [], list(candidates), {"verified": 0, "accepted": 0, "rejected": 0,
                                       "error": "no_model"}

    accepted: list[BodyAnchorRecord] = []
    rejected: list[BodyAnchorRecord] = []
    limit = min(len(candidates), _MAX_CANDIDATES_PER_BOOK)

    for anchor in candidates[:limit]:
        try:
            marker_val = int(anchor.normalized_marker)
        except (ValueError, TypeError):
            rejected.append(anchor)
            continue

        result = _call_vision_for_bare_digit(
            pdf_path=pdf_path,
            page_no=int(anchor.page_no),
            pages=pages,
            marker=marker_val,
            source_text=str(anchor.source_text or ""),
            model_args=resolved_args,
        )

        if result.get("is_note_marker") and result.get("confidence") in ("high", "medium"):
            accepted.append(anchor)
        else:
            rejected.append(anchor)

    return accepted, rejected, {
        "verified": min(len(candidates), _MAX_CANDIDATES_PER_BOOK),
        "accepted": len(accepted),
        "rejected": len(rejected),
    }

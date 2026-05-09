"""Phase 1→2 之间：LLM 交叉验证书型分类。

每本书必经——用视觉模型看结构驱动选取的 7-15 页代表性页面，
确认 pipeline 的 book_type 判定。不一致时触发人工审核而非自动覆盖。
"""

from __future__ import annotations

import base64
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from FNM_RE.modules.contracts import GateReport, ModuleResult
from FNM_RE.modules.types import (
    BookNoteProfile,
    TocChapter,
    TocStructure,
)
from FNM_RE.shared.notes import _safe_int, scan_items_by_kind

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VERIFY_MAX_TOKENS = 4096
_VERIFY_TOTAL_CAP_RATIO = 0.10
_VERIFY_TOTAL_CAP_ABSOLUTE = 40
_CHAPTER_END_SAMPLE_RATE = 0.30
_CHAPTER_END_MIN_REGIONS = 3
_CHAPTER_END_MAX_REGIONS = 15
_FALSE_POSITIVE_ITEM_THRESHOLD = 50
_FALSE_POSITIVE_MAX_PAGES = 5
_BODY_BASELINE_MIN = 2
_LLM_TIMEOUT = 180.0

# ---------------------------------------------------------------------------
# Internal helpers — structure profile extraction
# ---------------------------------------------------------------------------


@dataclass
class _EndnoteRegionInfo:
    chapter_id: str = ""
    scope: str = ""  # "chapter" | "book"
    start_page: int = 0
    end_page: int = 0

    @property
    def page_count(self) -> int:
        return max(1, self.end_page - self.start_page + 1)


@dataclass
class _BookStructureProfile:
    total_pages: int = 0
    chapter_count: int = 0
    chapter_modes: dict[str, str] = None  # type: ignore[assignment]
    endnote_regions: list[_EndnoteRegionInfo] = None  # type: ignore[assignment]
    chapter_endnote_count: int = 0
    book_endnote_count: int = 0
    endnote_item_count: int = 0
    footnote_item_count: int = 0
    toc_has_notes_entry: bool = False
    toc_notes_printed_page: int | None = None
    mode_types: set[str] = None  # type: ignore[assignment]
    chapters: list[TocChapter] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.chapter_modes is None:
            self.chapter_modes = {}
        if self.endnote_regions is None:
            self.endnote_regions = []
        if self.mode_types is None:
            self.mode_types = set()
        if self.chapters is None:
            self.chapters = []


def _chapter_by_page(toc_structure: TocStructure) -> dict[int, str]:
    mapped: dict[int, str] = {}
    for chapter in toc_structure.chapters:
        chapter_id = str(chapter.chapter_id or "")
        if not chapter_id:
            continue
        for page_no in chapter.pages:
            if int(page_no) > 0:
                mapped[int(page_no)] = chapter_id
        start_page = int(chapter.start_page or 0)
        end_page = int(chapter.end_page or 0)
        if start_page > 0 and end_page >= start_page:
            for page_no in range(start_page, end_page + 1):
                mapped.setdefault(page_no, chapter_id)
    return mapped


def _nearest_prior_chapter_id(
    toc_structure: TocStructure, page_no: int
) -> str:
    candidates = [
        ch
        for ch in toc_structure.chapters
        if str(ch.chapter_id or "").strip()
        and int(ch.start_page or 0) <= int(page_no)
    ]
    if not candidates:
        return ""
    candidates.sort(
        key=lambda ch: (int(ch.start_page or 0), int(ch.end_page or 0))
    )
    return str(candidates[-1].chapter_id or "")


def _count_note_items(pages: list[dict], kind: str) -> int:
    total = 0
    for page in pages:
        for item in scan_items_by_kind(page, kind=kind):
            total += 1
    return total


def _compute_endnote_regions(
    pages: list[dict],
    toc_structure: TocStructure,
) -> list[_EndnoteRegionInfo]:
    """从 raw_pages 的 _note_scan 数据检测连续 endnote 页面并构建 region。

    仅使用 Phase 1 可用的数据（_note_scan、chapter_by_page）。
    """
    ch_by_page = _chapter_by_page(toc_structure)
    last_chapter_end = max(
        (int(ch.end_page or 0) for ch in toc_structure.chapters if ch.role == "chapter"),
        default=0,
    )

    # 找所有 endnote 候选页
    endnote_page_nos: set[int] = set()
    for page in pages:
        page_no = _safe_int(page.get("bookPage") or page.get("pdfPage") or 0)
        if page_no <= 0:
            continue
        note_scan = dict(page.get("_note_scan") or {})
        page_kind = str(note_scan.get("page_kind") or "").strip().lower()
        is_endnote_page = (
            page_kind == "endnote_collection"
            or bool(scan_items_by_kind(page, kind="endnote"))
        )
        if is_endnote_page:
            # fnBlocks 守卫（与 note_regions.py Phase 2 对齐）：
            # 有页底脚注且无尾注信号 → 拒绝；过渡页（同时有脚注+尾注信号）→ 允许
            fnb = page.get("fnBlocks")
            if isinstance(fnb, list) and len(fnb) > 0:
                reclassified = note_scan.get("has_reclassified_endnotes")
                if not reclassified:
                    continue
            endnote_page_nos.add(page_no)

    if not endnote_page_nos:
        return []

    # 分组为连续 region
    sorted_pages = sorted(endnote_page_nos)
    regions: list[_EndnoteRegionInfo] = []
    current_start = sorted_pages[0]
    current_end = sorted_pages[0]

    for page_no in sorted_pages[1:]:
        if page_no == current_end + 1:
            current_end = page_no
        else:
            regions.append(
                _EndnoteRegionInfo(
                    chapter_id=_resolve_region_chapter(
                        current_start, current_end, ch_by_page, toc_structure
                    ),
                    scope=_resolve_region_scope(current_start, last_chapter_end),
                    start_page=current_start,
                    end_page=current_end,
                )
            )
            current_start = page_no
            current_end = page_no

    regions.append(
        _EndnoteRegionInfo(
            chapter_id=_resolve_region_chapter(
                current_start, current_end, ch_by_page, toc_structure
            ),
            scope=_resolve_region_scope(current_start, last_chapter_end),
            start_page=current_start,
            end_page=current_end,
        )
    )

    return regions


def _resolve_region_chapter(
    start: int,
    end: int,
    ch_by_page: dict[int, str],
    toc_structure: TocStructure,
) -> str:
    for pn in range(start, end + 1):
        cid = ch_by_page.get(pn)
        if cid:
            return cid
    return _nearest_prior_chapter_id(toc_structure, start)


def _resolve_region_scope(page_no: int, last_chapter_end: int) -> str:
    return "book" if page_no > last_chapter_end else "chapter"


def _extract_book_structure_profile(
    toc_structure: TocStructure,
    book_type_profile: BookNoteProfile,
    pages: list[dict],
) -> _BookStructureProfile:
    chapters = [ch for ch in toc_structure.chapters if ch.role == "chapter"]
    chapter_modes: dict[str, str] = {}
    for row in book_type_profile.chapter_modes:
        chapter_modes[str(row.chapter_id or "")] = str(row.note_mode or "")

    endnote_regions = _compute_endnote_regions(pages, toc_structure)

    return _BookStructureProfile(
        total_pages=max(1, len(pages)),
        chapter_count=len(chapters),
        chapter_modes=chapter_modes,
        endnote_regions=endnote_regions,
        chapter_endnote_count=sum(
            1 for r in endnote_regions if r.scope == "chapter"
        ),
        book_endnote_count=sum(
            1 for r in endnote_regions if r.scope == "book"
        ),
        endnote_item_count=_count_note_items(pages, "endnote"),
        footnote_item_count=_count_note_items(pages, "footnote"),
        toc_has_notes_entry=any(
            str(getattr(node, "role", "") or "").strip().lower() == "endnotes"
            for node in (toc_structure.toc_tree or [])
        ),
        toc_notes_printed_page=_resolve_toc_notes_page(toc_structure),
        mode_types={
            str(row.note_mode or "")
            for row in book_type_profile.chapter_modes
            if str(row.note_mode or "").strip()
        },
        chapters=chapters,
    )


def _resolve_toc_notes_page(toc_structure: TocStructure) -> int | None:
    for node in toc_structure.toc_tree or []:
        if str(getattr(node, "role", "") or "").strip().lower() == "endnotes":
            target = getattr(node, "target_pdf_page", None)
            if target is not None and int(target) > 0:
                return int(target)
    return None


# ---------------------------------------------------------------------------
# Page selection — 6 rules
# ---------------------------------------------------------------------------


def _toc_page(
    profile: _BookStructureProfile, toc_pages: list | None = None
) -> int:
    """R1: 返回 TOC 页的 PDF 页码。"""
    if toc_pages:
        for tp in toc_pages:
            pn = _safe_int(getattr(tp, "page_no", 0))
            if pn > 0:
                return pn
    # 回退：第一章起始前一页
    if profile.chapters:
        first_start = min(
            int(ch.start_page or 1)
            for ch in profile.chapters
            if int(ch.start_page or 0) > 0
        )
        return max(1, first_start - 1)
    return 1


def _body_baseline_pages(profile: _BookStructureProfile) -> list[int]:
    """R2: 每种 chapter_mode 取 1 页正文中页，最少 2 页。"""
    pages: list[int] = []
    for mode in sorted(profile.mode_types):
        candidates = [
            ch
            for ch in profile.chapters
            if profile.chapter_modes.get(str(ch.chapter_id or "")) == mode
        ]
        if not candidates:
            continue
        ch = candidates[len(candidates) // 2]
        mid = int(ch.start_page or 1) + (
            int(ch.end_page or 1) - int(ch.start_page or 1)
        ) // 2
        pages.append(max(1, mid))

    while len(pages) < _BODY_BASELINE_MIN and profile.chapters:
        idx = len(pages) % len(profile.chapters)
        ch = profile.chapters[idx]
        mid = int(ch.start_page or 1) + (
            int(ch.end_page or 1) - int(ch.start_page or 1)
        ) // 2
        if mid not in pages:
            pages.append(max(1, mid))

    return pages[:_BODY_BASELINE_MIN]


def _chapter_end_boundary_pages(profile: _BookStructureProfile) -> list[int]:
    """R3: 对 scope=chapter 的 endnote region 抽样边界页。"""
    chapter_regions = [
        r for r in profile.endnote_regions if r.scope == "chapter"
    ]
    if not chapter_regions:
        return []

    n = len(chapter_regions)
    sample_n = max(
        _CHAPTER_END_MIN_REGIONS,
        min(_CHAPTER_END_MAX_REGIONS, math.ceil(n * _CHAPTER_END_SAMPLE_RATE)),
    )

    # 均匀间距抽样
    if n <= sample_n:
        sampled = chapter_regions
    else:
        step = (n - 1) / max(1, sample_n - 1)
        indices = [int(step * i) for i in range(sample_n)]
        sampled = [chapter_regions[i] for i in indices]

    pages: list[int] = []
    for region in sampled:
        # 末页正文（region 前 1 页）
        last_body = region.start_page - 1
        if last_body >= 1:
            pages.append(last_body)
        # 第一条注释
        pages.append(region.start_page)
        # 中间注释（region ≥ 3 页时）
        if region.page_count >= 3:
            pages.append(region.start_page + region.page_count // 2)

    return pages


def _book_notes_region_pages(profile: _BookStructureProfile) -> list[int]:
    """R4: book scope region —— 验证 Notes 起始 + 中间。"""
    book_regions = [r for r in profile.endnote_regions if r.scope == "book"]
    if not book_regions:
        return []

    # 合并所有 book scope region 的页面
    all_pages = sorted(
        {pn for r in book_regions for pn in range(r.start_page, r.end_page + 1)}
    )
    if not all_pages:
        return []

    first, last = all_pages[0], all_pages[-1]
    pages = [max(1, first - 1), first]
    if last - first >= 5:
        pages.append(first + (last - first) // 2)
    return pages


def _toc_offset_verification_pages(profile: _BookStructureProfile) -> list[int]:
    """R5: TOC Notes 偏移验证窗口。"""
    if not profile.toc_has_notes_entry or profile.toc_notes_printed_page is None:
        return []

    toc_claimed = profile.toc_notes_printed_page
    # pipeline 检测到的第一条 endnote 页
    pipeline_first = None
    for region in profile.endnote_regions:
        if pipeline_first is None or region.start_page < pipeline_first:
            pipeline_first = region.start_page

    if pipeline_first is None:
        return [toc_claimed] if toc_claimed > 0 else []

    return [
        p
        for p in (
            toc_claimed,
            pipeline_first - 2,
            pipeline_first,
            pipeline_first + 5,
        )
        if p > 0
    ]


def _false_positive_check_pages(profile: _BookStructureProfile) -> list[int]:
    """R6: 少量 endnote items 时验证是否为假阳性。"""
    if not (0 < profile.endnote_item_count < _FALSE_POSITIVE_ITEM_THRESHOLD):
        return []

    endnote_pages = sorted(
        {r.start_page for r in profile.endnote_regions}
        | {r.end_page for r in profile.endnote_regions}
    )
    return endnote_pages[:_FALSE_POSITIVE_MAX_PAGES]


# ---------------------------------------------------------------------------
# Main page selection
# ---------------------------------------------------------------------------


def select_verification_pages(
    toc_structure: TocStructure,
    book_type_profile: BookNoteProfile,
    pages: list[dict],
    *,
    profile: _BookStructureProfile | None = None,
) -> list[int]:
    """由书的结构参数决定送检页面（6 规则）。"""
    if profile is None:
        profile = _extract_book_structure_profile(
            toc_structure, book_type_profile, pages
        )

    selected: set[int] = set()

    # R1
    toc_pages_list = list(toc_structure.pages) if toc_structure.pages else []
    selected.add(_toc_page(profile, toc_pages=toc_pages_list))

    # R2
    selected.update(_body_baseline_pages(profile))

    # R3
    selected.update(_chapter_end_boundary_pages(profile))

    # R4
    selected.update(_book_notes_region_pages(profile))

    # R5
    selected.update(_toc_offset_verification_pages(profile))

    # R6
    selected.update(_false_positive_check_pages(profile))

    # 去重、过滤非法页码、应用上限
    valid = sorted(p for p in selected if 1 <= p <= profile.total_pages)
    cap = min(
        int(profile.total_pages * _VERIFY_TOTAL_CAP_RATIO),
        _VERIFY_TOTAL_CAP_ABSOLUTE,
    )
    return valid[:max(cap, 5)]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_LLM_VERIFY_SYSTEM_PROMPT = """\
You are an expert at analyzing book page layouts to determine the annotation \
(footnote/endnote) system of an academic book.

Your task: examine several scanned pages and verify the book's classification.

CRITICAL — page number distinction:
- "PDF file page": sequential page number in the PDF file (1-based).
  These are the numbers shown in the page labels like "p0100".
- "Printed book page": the number physically printed on the book page itself.
  Pages before chapter 1 often use Roman numerals (i, ii, ...) or are unnumbered.
- The Table of Contents (TOC) reports PRINTED book page numbers, NOT PDF file pages.
- There is often an offset: PDF page = printed page + offset.
- When you report page numbers in your JSON response, ALWAYS use PDF file page numbers.

For each page image, note:
- Whether there are footnote markers or footnote text at the bottom of the page
  (typically separated by a horizontal line, smaller font)
- Whether there are superscript markers (numbers, asterisks, letters) in the body text
- Whether the page appears to be a dedicated endnote page
  (with ## NOTES / Notes heading, or a list of numbered citations)
- Whether body text transitions into a notes section

Return ONLY a JSON object.  No markdown fences, no explanations outside the JSON.
Use EXACTLY these values for book_type:
  "endnote_only" — all notes are endnotes
  "footnote_only" — all notes are footnotes
  "mixed" — both footnotes AND endnotes appear

JSON schema:
{
  "book_type": "endnote_only" | "footnote_only" | "mixed",
  "confidence": "high" | "medium" | "low",
  "agrees_with_pipeline": true | false,
  "reasoning": "brief explanation of your decision (1-3 sentences)",
  "toc_notes_page_verified": true | false,
  "toc_notes_actual_pdf_page": <integer or null>,
  "suspected_false_positive_pages": [<integer, ...>]
}"""


def _build_user_prompt(
    *,
    book_type: str,
    page_infos: list[dict],
    toc_has_notes_entry: bool,
    toc_notes_page: int | None,
    chapter_count: int,
    mode_types: list[str],
    endnote_region_count: int,
    endnote_item_count: int,
) -> str:
    lines = [
        "The automated pipeline classified this book as:",
        f"  book_type = {book_type}",
        "",
        "Book structure:",
        f"  chapters: {chapter_count}",
        f"  chapter modes present: {', '.join(mode_types) if mode_types else 'none'}",
        f"  endnote regions detected: {endnote_region_count}",
        f"  endnote items (from OCR scan): {endnote_item_count}",
        f"  TOC has explicit 'Notes' / 'Endnotes' entry: {toc_has_notes_entry}",
    ]
    if toc_has_notes_entry and toc_notes_page is not None:
        lines.append(
            f"  TOC says Notes/Endnotes at PRINTED page {toc_notes_page}"
        )
        lines.append(
            "  (IMPORTANT: this is the printed book page number,"
            " NOT the PDF file page number)"
        )

    lines.extend([
        "",
        "Pages to examine (PDF file page → printed book page):",
    ])
    for info in page_infos:
        lines.append(
            f"  PDF p.{info['pdf_page']:04d}"
            f"  (printed page {info.get('printed_page', '?')})"
        )

    lines.extend([
        "",
        "Verify whether the pipeline's book_type is correct.",
        "If the TOC claims a Notes section at a certain printed page number,",
        "check whether that printed page number appears on the correct PDF file page.",
        "Report the ACTUAL PDF file page where the Notes section starts"
        " (if different from what the pipeline detected).",
        "If endnote items are very few (< 50), check whether they are real endnotes"
        " or high-numbered footnotes / appendix legal references misdetected.",
        "",
        "Return JSON.",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_page_image(
    pdf_path: str, page_no: int, pages: list[dict]
) -> tuple[bytes, str]:
    """渲染 PDF 中的一页为 JPEG。返回 (bytes, mime_type)。"""
    # 从 page dict 找准确的 fileIdx
    file_idx = page_no - 1
    for p in pages:
        try:
            if int(p.get("bookPage") or 0) == page_no:
                file_idx = int(p.get("fileIdx") or (page_no - 1))
                break
        except (TypeError, ValueError):
            continue

    try:
        from FNM_RE.llm_repair import _render_repair_page_image

        return _render_repair_page_image(pdf_path, file_idx)
    except Exception:
        return (b"", "")


def _render_selected_pages(
    pdf_path: str,
    page_numbers: list[int],
    pages: list[dict],
) -> list[dict]:
    """渲染选中页面为 base64 编码的 data URL 列表。"""
    rendered: list[dict] = []
    for pn in page_numbers:
        img_bytes, mime = _render_page_image(pdf_path, pn, pages)
        if not img_bytes or not mime:
            continue
        encoded = base64.b64encode(img_bytes).decode("ascii")
        rendered.append({
            "page_no": pn,
            "image_url": f"data:{mime};base64,{encoded}",
        })
    return rendered


# ---------------------------------------------------------------------------
# VLM call + response parsing
# ---------------------------------------------------------------------------


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
            "request_overrides": dict(
                getattr(spec, "request_overrides", {}) or {}
            ),
        }
    except Exception:
        return None


def _call_vision_llm(
    rendered: list[dict],
    system_prompt: str,
    user_prompt: str,
    model_args: dict,
) -> dict:
    client = OpenAI(
        api_key=str(model_args.get("api_key") or ""),
        base_url=str(model_args.get("base_url") or ""),
        timeout=_LLM_TIMEOUT,
    )

    user_content: list[dict] = [
        {"type": "text", "text": user_prompt},
    ]
    for rp in rendered:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": rp["image_url"]},
        })

    create_kwargs: dict = {
        "model": str(model_args.get("model_id") or ""),
        "max_tokens": _VERIFY_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    request_overrides = dict(model_args.get("request_overrides") or {})
    if not request_overrides and str(
        model_args.get("provider") or ""
    ).strip().lower() in ("qwen", "mimo_token_plan"):
        request_overrides = {"extra_body": {"enable_thinking": False}}
    for key, value in request_overrides.items():
        if isinstance(value, dict) and isinstance(create_kwargs.get(key), dict):
            create_kwargs[key] = {**create_kwargs[key], **value}
        else:
            create_kwargs[key] = value

    response = client.chat.completions.create(**create_kwargs)
    raw_text = ""
    if response.choices and getattr(response.choices[0], "message", None):
        raw_text = str(
            getattr(response.choices[0].message, "content", "") or ""
        )
    return _parse_llm_response(raw_text)


_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(.*?)\s*```", re.DOTALL
)
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _parse_llm_response(raw_text: str) -> dict:
    if not raw_text:
        return {"error": "empty_response", "book_type": None}

    fenced = _JSON_BLOCK_RE.search(raw_text)
    text = fenced.group(1) if fenced else raw_text
    match = _JSON_OBJECT_RE.search(text)

    if not match:
        return {
            "error": "no_json_found",
            "book_type": None,
            "raw": raw_text[:200],
        }

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {
            "error": "json_parse_error",
            "book_type": None,
            "raw": raw_text[:200],
        }

    if not isinstance(parsed, dict):
        return {"error": "not_a_dict", "book_type": None}

    valid_types = {"endnote_only", "footnote_only", "mixed"}
    book_type = parsed.get("book_type")
    if book_type not in valid_types:
        book_type = None

    return {
        "book_type": book_type,
        "confidence": str(parsed.get("confidence", "low")),
        "agrees_with_pipeline": bool(
            parsed.get("agrees_with_pipeline", False)
        ),
        "reasoning": str(parsed.get("reasoning", "")),
        "toc_notes_page_verified": bool(
            parsed.get("toc_notes_page_verified", False)
        ),
        "toc_notes_actual_pdf_page": parsed.get(
            "toc_notes_actual_pdf_page"
        ),
        "suspected_false_positive_pages": list(
            parsed.get("suspected_false_positive_pages", []) or []
        ),
        "raw_response": raw_text[:500],
    }


def _handle_content_filter_retry(
    pdf_path: str,
    page_numbers: list[int],
    pages: list[dict],
    system_prompt: str,
    user_prompt: str,
    model_args: dict,
) -> dict:
    """送检 + 审核拒绝时换页重试（最多 3 次）。"""
    offsets_to_try = [
        None,  # 原始页面
        [(-2, 2)],  # 第 1 次换页: 前后 ±2
        [(-1, 3)],  # 第 2 次换页: 前后 -1/+3
    ]

    for attempt, offsets in enumerate(offsets_to_try):
        if offsets is None:
            current_pages = list(page_numbers)
        else:
            current_pages = sorted(
                {
                    max(1, pn + offset)
                    for pn in page_numbers
                    for offset in offsets
                }
            )

        rendered = _render_selected_pages(
            pdf_path, current_pages, pages
        )
        if not rendered:
            continue

        result = _call_vision_llm(
            rendered, system_prompt, user_prompt, model_args
        )
        if result.get("book_type") is not None:
            return result

    return {
        "error": "content_filter_rejected_3_attempts",
        "fallback": "trust_rules",
        "book_type": None,
        "agrees_with_pipeline": None,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def verify_book_type_with_llm(
    *,
    toc_structure: TocStructure,
    book_type_profile: BookNoteProfile,
    pages: list[dict],
    pdf_path: str,
    model_args: dict | None = None,
) -> ModuleResult[dict]:
    """LLM 交叉验证书型分类——每本书必经。

    返回 ModuleResult，其 data 字段包含验证报告 dict。
    不一致时 gate_report.soft["llm.disagreement"] = True。
    """
    # Step 1: 提取结构参数（只做一次，供选页和 prompt 共用）
    profile = _extract_book_structure_profile(
        toc_structure, book_type_profile, pages
    )

    # Step 2: 结构驱动选页
    page_numbers = select_verification_pages(
        toc_structure, book_type_profile, pages, profile=profile
    )
    if not page_numbers:
        return ModuleResult(
            data={"error": "no_pages_selected", "book_type": None},
            gate_report=GateReport(
                module="llm_book_type_verify",
                hard={"llm.pages_selected": False},
                reasons=["no_pages_selected_for_verification"],
            ),
        )

    # Step 3: 解析模型配置
    resolved_args = model_args or _resolve_model_args()
    if not resolved_args:
        return ModuleResult(
            data={"error": "no_model_available", "book_type": None},
            gate_report=GateReport(
                module="llm_book_type_verify",
                hard={"llm.model_available": False},
                reasons=["no_vision_model_configured"],
            ),
        )

    # Step 4: 构建 prompt
    page_infos = _build_page_info_list(page_numbers, pages)
    user_prompt = _build_user_prompt(
        book_type=str(book_type_profile.book_type),
        page_infos=page_infos,
        toc_has_notes_entry=profile.toc_has_notes_entry,
        toc_notes_page=profile.toc_notes_printed_page,
        chapter_count=profile.chapter_count,
        mode_types=sorted(profile.mode_types),
        endnote_region_count=profile.chapter_endnote_count
        + profile.book_endnote_count,
        endnote_item_count=profile.endnote_item_count,
    )

    # Step 5: 调用 VLM（含审核拒绝换页重试）
    result = _handle_content_filter_retry(
        pdf_path=pdf_path,
        page_numbers=page_numbers,
        pages=pages,
        system_prompt=_LLM_VERIFY_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model_args=resolved_args,
    )

    # Step 6: 构建 gate report
    llm_responded = result.get("book_type") is not None
    pipeline_type = str(book_type_profile.book_type)
    llm_type = str(result.get("book_type") or "")
    disagreement = llm_responded and (llm_type != pipeline_type)

    evidence: dict[str, Any] = dict(result)
    evidence["pages_selected"] = page_numbers
    evidence["pipeline_book_type"] = pipeline_type

    return ModuleResult(
        data=result,
        gate_report=GateReport(
            module="llm_book_type_verify",
            hard={"llm.responded": llm_responded},
            soft={
                "llm.disagreement": disagreement,
            },
            reasons=(
                ["llm_verification_agreed"]
                if not disagreement
                else ["llm_verification_disagreed"]
            )
            if llm_responded
            else ["llm_no_response"],
            evidence=evidence,
        ),
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Helper: build page info list for user prompt
# ---------------------------------------------------------------------------


def _build_page_info_list(
    page_numbers: list[int],
    pages: list[dict],
) -> list[dict]:
    """为每页生成 PDF 页码 → 印刷页码 的对照信息。"""
    infos: list[dict] = []
    for pn in page_numbers:
        printed = pn  # 默认等于 PDF 页码
        for p in pages:
            try:
                if int(p.get("bookPage") or 0) == pn:
                    pp = p.get("printPage") or p.get("bookPage") or pn
                    try:
                        printed = int(pp)
                    except (TypeError, ValueError):
                        printed = pn
                    break
            except (TypeError, ValueError):
                continue
        infos.append({"pdf_page": pn, "printed_page": printed})
    return infos

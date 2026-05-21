"""Phase 2 尾部视觉 anchor 缺口恢复。

OCR (GlyphLessFont) 对上标数字存在系统性误识别（⁸→#/*, ¹→!, ⁰→°, ¹⁷→/?），
导致正文中的真实标注不可见。本模块在 Phase 2 文本扫描完成后、Phase 3 链接前，
使用 PDF 渲染图像 + VLM 从图像层定位被 OCR 丢失的上标 marker。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from FNM_RE.models import BodyAnchorRecord, Phase2Structure
from FNM_RE.shared.notes import normalize_note_marker

VISUAL_RECOVERY_MAX_IMAGES = 5
VISUAL_RECOVERY_MAX_OUTPUT_TOKENS = 1024
VISUAL_RECOVERY_ANCHOR_CERTAINTY = 0.85
VISUAL_RECOVERY_MAX_RETRY_MARKERS = 4

# —— CLI 可开关常量，保持模块级以利测试 ——
VISUAL_RECOVERY_ENABLED = True


@dataclass
class ChapterAnchorGap:
    chapter_id: str
    expected_markers: set[int]
    detected_markers: set[int]
    missing_markers: list[int]  # sorted
    gap_count: int
    gap_rate: float
    body_page_range: tuple[int, int]


# ---------------------------------------------------------------------------
# Gap 计算
# ---------------------------------------------------------------------------


def compute_chapter_anchor_gaps(
    phase2: Phase2Structure,
    body_anchors: list[BodyAnchorRecord],
) -> list[ChapterAnchorGap]:
    """计算每章尾注 anchor 缺口：expected (endnote items) vs detected (body anchors)。"""
    endnote_region_ids = {
        str(region.region_id or "").strip()
        for region in phase2.note_regions
        if str(region.note_kind or "").strip() == "endnote"
        and str(region.region_id or "").strip()
    }
    expected_by_chapter: dict[str, set[int]] = {}
    for item in phase2.note_items:
        if str(item.region_id or "").strip() not in endnote_region_ids:
            continue
        chapter_id = str(item.chapter_id or "").strip()
        if not chapter_id:
            continue
        try:
            marker = int(item.marker)
        except (ValueError, TypeError):
            continue
        if marker <= 0:
            continue
        expected_by_chapter.setdefault(chapter_id, set()).add(marker)

    detected_by_chapter: dict[str, set[int]] = {}
    for anchor in body_anchors:
        if str(anchor.anchor_kind or "").strip() == "footnote":
            continue
        chapter_id = str(anchor.chapter_id or "").strip()
        if not chapter_id:
            continue
        try:
            marker = int(anchor.normalized_marker)
        except (ValueError, TypeError):
            continue
        if marker <= 0:
            continue
        detected_by_chapter.setdefault(chapter_id, set()).add(marker)

    chapter_page_ranges: dict[str, tuple[int, int]] = {}
    for ch in phase2.chapters:
        chapter_id = str(ch.chapter_id or "").strip()
        if not chapter_id:
            continue
        cpages = list(ch.pages or [])
        if cpages:
            chapter_page_ranges[chapter_id] = (min(cpages), max(cpages))

    gaps: list[ChapterAnchorGap] = []
    for chapter_id, expected in expected_by_chapter.items():
        if not expected:
            continue
        detected = detected_by_chapter.get(chapter_id, set())
        missing = sorted(expected - detected)
        gap_count = len(missing)
        if not missing:
            continue
        gap_rate = gap_count / len(expected)
        # 阈值: gap >= 2 (绝对) 或 gap_rate >= 10%
        if gap_count < 2 and gap_rate < 0.10:
            continue

        gaps.append(
            ChapterAnchorGap(
                chapter_id=chapter_id,
                expected_markers=expected,
                detected_markers=detected,
                missing_markers=missing,
                gap_count=gap_count,
                gap_rate=gap_rate,
                body_page_range=chapter_page_ranges.get(chapter_id, (0, 0)),
            )
        )

    return gaps


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _page_payload_by_no(pages: list[dict]) -> dict[int, dict]:
    mapping: dict[int, dict] = {}
    for page in pages or []:
        try:
            page_no = int(page.get("bookPage") or 0)
        except (TypeError, ValueError):
            continue
        if page_no > 0:
            mapping[page_no] = dict(page)
    return mapping


def _chapter_body_page_range(
    chapter_id: str,
    phase2: Phase2Structure,
) -> tuple[int, int]:
    for ch in phase2.chapters:
        if str(ch.chapter_id or "").strip() == chapter_id:
            cpages = list(ch.pages or [])
            if cpages:
                return (min(cpages), max(cpages))
    return (0, 0)


def _representative_marker_page(pages: list[int]) -> int:
    cleaned = sorted(int(page) for page in pages if int(page or 0) > 0)
    if not cleaned:
        return 0
    return cleaned[len(cleaned) // 2]


def _resolve_gap_page_range(
    gap: ChapterAnchorGap,
    body_anchors: list[BodyAnchorRecord],
) -> tuple[int, int]:
    """根据编号相邻的已检测 marker 缩小搜索范围，带 ±1 页缓冲。"""
    chapter_id = gap.chapter_id
    marker_pages: dict[int, list[int]] = {}
    for a in body_anchors:
        if str(a.chapter_id or "").strip() != chapter_id:
            continue
        if str(a.anchor_kind or "").strip() == "footnote":
            continue
        try:
            m = int(a.normalized_marker)
        except (ValueError, TypeError):
            continue
        if m > 0:
            marker_pages.setdefault(m, []).append(int(a.page_no))

    body_min, body_max = gap.body_page_range
    if body_min <= 0 or body_max <= 0:
        return (body_min, body_max)

    if not gap.missing_markers:
        return (body_min, body_max)

    first_missing = gap.missing_markers[0]
    last_missing = gap.missing_markers[-1]

    lower_marker = max((m for m in marker_pages if m < first_missing), default=0)
    upper_marker = min((m for m in marker_pages if m > last_missing), default=0)
    lower_bound = (
        _representative_marker_page(marker_pages.get(lower_marker, []))
        if lower_marker > 0
        else 0
    )
    upper_bound = (
        _representative_marker_page(marker_pages.get(upper_marker, []))
        if upper_marker > 0
        else 0
    )

    min_page = max(body_min, lower_bound - 1) if lower_bound > 0 else body_min
    max_page = min(body_max, upper_bound + 1) if upper_bound > 0 else body_max
    if min_page > max_page:
        if lower_bound > 0 and upper_bound > 0:
            lo, hi = sorted((lower_bound, upper_bound))
            min_page = max(body_min, lo - 1)
            max_page = min(body_max, hi + 1)
        else:
            min_page, max_page = body_min, body_max
    if min_page > max_page:
        return (body_min, body_max)
    return (min_page, max_page)


def _sample_page_range(page_min: int, page_max: int, max_images: int) -> list[int]:
    """从连续页面范围抽样，确保不超过 max_images 页。"""
    if page_min <= 0 or page_max < page_min:
        return []
    if page_max - page_min + 1 <= max_images:
        return list(range(page_min, page_max + 1))
    step = (page_max - page_min) / max_images
    return [page_min + int(i * step) for i in range(max_images)]


# ---------------------------------------------------------------------------
# VLM 提示词
# ---------------------------------------------------------------------------

_VISUAL_RECOVERY_SYSTEM_PROMPT = """\
You are an expert at reading printed book pages. Your task is to locate \
superscript reference markers (endnote markers) in scanned book page images.

The book uses superscript numbers (like ⁸ or ¹⁰) in the body text to mark \
endnote references. OCR has failed to recognize these superscripts — they \
may look like regular numbers, symbols, or be missing entirely in the OCR output.

For each missing marker in the list:
1. Scan the page images for a superscript number matching that marker
2. Identify the word or short phrase (3-15 characters) immediately BEFORE the superscript
   IMPORTANT: the anchor_phrase MUST NOT include the superscript itself or text after it.
   For example, if the text is "intelligibilité⁸ de ce processus", the phrase is "intelligibilité".
3. Note the page number where you found it
4. Record the superscript in its original Unicode form (e.g. "⁸", "¹⁰", "¹⁷")

Return ONLY a JSON array of found markers. Each entry:
- "marker": integer marker number
- "page_no": the printed book page number as an INTEGER (e.g. 49, 127). Do NOT use Roman numerals.
- "anchor_phrase": ONLY the text BEFORE the superscript, 3-15 characters, no superscript digits
- "source_marker": superscript in Unicode form (e.g. "⁸", "¹⁰")

Only report markers you can clearly identify as superscript reference numbers. \
If you cannot find a marker, omit it from the output. \
Do not guess. Do not include explanations."""


def _build_visual_recovery_user_prompt(
    missing_markers: list[int],
    page_start: int,
    page_end: int,
) -> str:
    markers_str = ", ".join(str(m) for m in missing_markers)
    return (
        f"Find these missing endnote superscript markers in the body text: [{markers_str}].\n"
        f"Page range: {page_start} to {page_end}.\n"
        'Return a JSON array. Format: [{"marker": 8, "page_no": 49, '
        '"anchor_phrase": "intelligibilité", "source_marker": "⁸"}]'
    )


# ---------------------------------------------------------------------------
# VLM 响应解析
# ---------------------------------------------------------------------------

_JSON_ARRAY_RE = re.compile(r"\[\s*\{.*?\}\s*\]", re.DOTALL)

_ROMAN_VALUES: list[tuple[str, int]] = [
    ("M", 1000), ("CM", 900), ("D", 500), ("CD", 400),
    ("C", 100), ("XC", 90), ("L", 50), ("XL", 40),
    ("X", 10), ("IX", 9), ("V", 5), ("IV", 4), ("I", 1),
]
_ROMAN_RE = re.compile(
    r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$",
    re.IGNORECASE,
)


def _roman_to_int(s: str) -> int:
    """将罗马数字字符串转为整数；非罗马数字返回 0。"""
    upper = str(s or "").strip().upper()
    if not upper or not _ROMAN_RE.match(upper):
        return 0
    result = 0
    idx = 0
    for symbol, value in _ROMAN_VALUES:
        while upper[idx: idx + len(symbol)] == symbol:
            result += value
            idx += len(symbol)
    return result


def _parse_visual_findings(raw_text: str) -> list[dict[str, Any]]:
    """从 VLM 响应中提取 JSON 数组。"""
    if not raw_text:
        return []
    # 优先提取 ```json 代码块
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
    text = fenced.group(1) if fenced else raw_text
    # 找第一个 JSON 数组
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


# ---------------------------------------------------------------------------
# anchor_phrase → OCR 文本定位
# ---------------------------------------------------------------------------


def _fuzzy_find_phrase_in_page(
    phrase: str,
    page: dict,
    min_similarity: float = 0.50,
) -> tuple[int, int, int] | None:
    """在页面 blocks/markdown 中模糊匹配 phrase。

    使用 rapidfuzz partial_ratio 做基于 token 的模糊匹配，
    比简单编辑距离更能容忍 OCR 中的字符替换和缺失。

    Returns (paragraph_index, char_start, char_end) or None.
    """
    if not phrase or not str(phrase).strip():
        return None

    phrase_clean = str(phrase).strip()

    # 收集所有要搜索的文本源：markdown + enriched_markdown + blocks
    sources: list[tuple[int, str]] = []

    # enriched_markdown（sup_recovery 已修复过的）
    enriched = str(page.get("enriched_markdown") or "").strip()
    if enriched:
        sources.append((-1, enriched))

    # raw markdown
    md = ""
    try:
        md_val = page.get("markdown")
        if isinstance(md_val, dict):
            md = str(md_val.get("text") or "").strip()
        else:
            md = str(md_val or "").strip()
    except Exception:
        md = ""
    if md:
        sources.append((0, md))

    # blocks
    blocks = _safe_page_blocks(page)
    for i, block in enumerate(blocks):
        text = str(block.get("text") or "").strip()
        if text:
            sources.append((i + 1, text))

    if not sources:
        return None

    # 1) 精确匹配（大小写不敏感）
    phrase_lower = phrase_clean.lower()
    for para_idx, text in sources:
        text_lower = text.lower()
        pos = text_lower.find(phrase_lower)
        if pos >= 0:
            return (max(0, para_idx), pos, pos + len(phrase_clean))

    # 2) rapidfuzz partial_ratio 模糊匹配
    try:
        from rapidfuzz.fuzz import partial_ratio
    except ImportError:
        partial_ratio = None

    best_score = 0.0
    best_match: tuple[int, int, int] | None = None

    for para_idx, text in sources:
        if len(text) < 3:
            continue

        if partial_ratio is not None:
            score = partial_ratio(phrase_lower, text.lower()) / 100.0
        else:
            score = _simple_substring_similarity(phrase_lower, text.lower())

        if score > best_score and score >= min_similarity:
            best_score = score
            loc = _best_window_location(text.lower(), phrase_lower)
            if loc is not None:
                start, end = loc
                best_match = (max(0, para_idx), start, end)

    if best_match is not None:
        return best_match

    # 3) 全 phrase 匹配失败 → 逐词匹配回退
    words = [w for w in phrase_clean.split() if len(w) >= 3]
    if not words:
        return None

    for para_idx, text in sources:
        text_lower = text.lower()
        for word in words:
            pos = text_lower.find(word.lower())
            if pos >= 0:
                return (max(0, para_idx), pos, pos + len(word))

    return None


def _safe_page_blocks(page: dict) -> list[dict]:
    try:
        from FNM_RE.shared.text import page_blocks

        return page_blocks(page)
    except Exception:
        raw = page.get("blocks") or []
        if isinstance(raw, list):
            return raw
        return []


def _best_window_location(text: str, pattern: str) -> tuple[int, int] | None:
    """在 text 中找与 pattern 最相似的滑动窗口位置。"""
    pw = len(pattern)
    if pw > len(text):
        return None
    best_dist = pw + 1
    best_start = 0
    for start in range(len(text) - pw + 1):
        window = text[start : start + pw]
        dist = sum(1 for ca, cb in zip(window, pattern) if ca != cb)
        if dist < best_dist:
            best_dist = dist
            best_start = start
            if best_dist == 0:
                break
    return (best_start, best_start + pw)


# Unicode superscript range: U+2070, U+00B9, U+00B2, U+00B3, U+2074-U+2079
_SUPERSCRIPT_CHARS = set("⁰¹²³⁴⁵⁶⁷⁸⁹")


def _sanitize_anchor_phrase(raw: str) -> str:
    """清洗 VLM 返回的 anchor_phrase：去掉上标字符、换行、多余空格。"""
    if not raw:
        return ""
    # 去掉换行
    cleaned = raw.replace("\n", " ").replace("\r", " ")
    # 去掉上标字符
    cleaned = "".join(c for c in cleaned if c not in _SUPERSCRIPT_CHARS)
    # 折叠空格
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()


def _simple_substring_similarity(pattern: str, text: str) -> float:
    """不含 rapidfuzz 的简单子串相似度。"""
    if not pattern or not text:
        return 0.0
    pw = len(pattern)
    if pw > len(text):
        return 0.0
    best = 0
    for start in range(len(text) - pw + 1):
        matches = sum(1 for ca, cb in zip(pattern, text[start : start + pw]) if ca == cb)
        if matches > best:
            best = matches
            if best == pw:
                break
    return best / pw if pw > 0 else 0.0


# ---------------------------------------------------------------------------
# BodyAnchorRecord 构造
# ---------------------------------------------------------------------------

_VISUAL_ANCHOR_SERIAL = 0


def _next_visual_anchor_id() -> str:
    global _VISUAL_ANCHOR_SERIAL
    _VISUAL_ANCHOR_SERIAL += 1
    return f"visual-{_VISUAL_ANCHOR_SERIAL:05d}"


def _materialize_visual_findings(
    findings: list[dict[str, Any]],
    gap: ChapterAnchorGap,
    page_by_no: dict[int, dict],
    *,
    candidate_pages: list[int] | None = None,
) -> tuple[list[BodyAnchorRecord], dict[str, Any]]:
    """将 VLM 返回的 findings 转为 BodyAnchorRecord 列表。"""
    anchors: list[BodyAnchorRecord] = []
    seen_markers: set[int] = set()
    found = 0
    mapped = 0
    match_failed = 0
    allowed_pages = [
        int(page_no)
        for page_no in (candidate_pages or [])
        if int(page_no or 0) > 0
    ]

    for item in findings:
        try:
            marker = int(item.get("marker") or 0)
        except (ValueError, TypeError):
            continue
        if marker <= 0:
            continue
        if marker not in gap.missing_markers:
            continue
        if marker in seen_markers:
            continue
        seen_markers.add(marker)
        found += 1

        anchor_phrase = _sanitize_anchor_phrase(
            str(item.get("anchor_phrase") or "")
        )
        source_marker = str(item.get("source_marker") or "").strip()
        if not source_marker:
            # 降级：用 Unicode superscript 映射
            source_marker = _int_to_unicode_superscript(marker)

        try:
            page_no = int(item.get("page_no") or 0)
        except (ValueError, TypeError):
            page_no = 0

        para_index = 0
        char_start = 0
        char_end = 0
        resolved_page_no = page_no if page_no > 0 else 0

        search_pages: list[int] = []
        if resolved_page_no > 0 and (
            not allowed_pages or resolved_page_no in allowed_pages
        ):
            search_pages.append(resolved_page_no)
        for candidate_page in allowed_pages:
            if candidate_page not in search_pages:
                search_pages.append(candidate_page)
        if not search_pages and gap.body_page_range[0] > 0:
            search_pages.append(gap.body_page_range[0])

        if anchor_phrase:
            loc: tuple[int, int, int] | None = None
            matched_page_no = 0
            for search_page_no in search_pages:
                page = page_by_no.get(search_page_no, {})
                if not page:
                    continue
                loc = _fuzzy_find_phrase_in_page(anchor_phrase, page)
                if loc is not None:
                    matched_page_no = search_page_no
                    break
            if loc is not None and matched_page_no > 0:
                para_index, char_start, char_end = loc
                char_start = char_end  # anchor 位于 phrase 之后
                char_end = char_start + len(source_marker)
                resolved_page_no = matched_page_no
                mapped += 1
            else:
                match_failed += 1
                # 截取页面文本前 200 字符用于诊断
                preview_page_no = search_pages[0] if search_pages else page_no
                preview_page = page_by_no.get(preview_page_no, {})
                page_preview = str(
                    preview_page.get("markdown")
                    or preview_page.get("enriched_markdown")
                    or ""
                )[:200]
                print(
                    f"[visual_recovery] phrase not found: marker={marker} "
                    f"page={preview_page_no} phrase={anchor_phrase!r} "
                    f"page_preview={page_preview!r}"
                )
                continue
        else:
            match_failed += 1
            continue

        normalized_marker = normalize_note_marker(str(marker))
        anchor = BodyAnchorRecord(
            anchor_id=_next_visual_anchor_id(),
            chapter_id=gap.chapter_id,
            page_no=resolved_page_no if resolved_page_no > 0 else gap.body_page_range[0],
            paragraph_index=para_index,
            char_start=char_start,
            char_end=char_end,
            source_marker=source_marker,
            normalized_marker=normalized_marker,
            anchor_kind="endnote",
            certainty=VISUAL_RECOVERY_ANCHOR_CERTAINTY,
            source_text=anchor_phrase if anchor_phrase else "",
            source="visual_repair",
            synthetic=False,
            ocr_repaired_from_marker="",
        )
        anchors.append(anchor)

    summary = {
        "found": found,
        "mapped": mapped,
        "match_failed": match_failed,
        "total_anchors": len(anchors),
    }
    return anchors, summary


def _int_to_unicode_superscript(n: int) -> str:
    """整数 → Unicode 上标字符串。"""
    _SUP_MAP = {
        0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴",
        5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹",
    }
    return "".join(_SUP_MAP[int(d)] for d in str(n))


# ---------------------------------------------------------------------------
# VLM 调用
# ---------------------------------------------------------------------------


def _render_page_image(pdf_path: str, page_no: int) -> str | None:
    """微进程渲染单页为 JPEG data URL。子进程退出后 OS 回收全部内存。"""
    file_idx = max(0, page_no - 1)
    try:
        from FNM_RE.modules.pdf_render_subprocess import render_repair_page_data_url
        return render_repair_page_data_url(pdf_path, file_idx)
    except Exception:
        return None


def _request_visual_findings(
    *,
    model_args: dict,
    rendered: list[dict],
    missing_markers: list[int],
    page_start: int,
    page_end: int,
) -> list[dict[str, Any]]:
    client = OpenAI(
        api_key=str(model_args.get("api_key") or ""),
        base_url=str(model_args.get("base_url") or ""),
        timeout=180.0,
    )
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": _build_visual_recovery_user_prompt(
                missing_markers, page_start, page_end
            ),
        }
    ]
    for rp in rendered:
        user_content.append(
            {"type": "image_url", "image_url": {"url": rp["image_url"]}}
        )

    request_overrides = dict(model_args.get("request_overrides") or {})
    if (
        not request_overrides
        and str(model_args.get("provider") or "").strip().lower() == "qwen"
    ):
        request_overrides = {"extra_body": {"enable_thinking": False}}

    create_kwargs: dict[str, Any] = {
        "model": str(model_args.get("model_id") or ""),
        "max_tokens": VISUAL_RECOVERY_MAX_OUTPUT_TOKENS,
        "messages": [
            {"role": "system", "content": _VISUAL_RECOVERY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }
    for key, value in request_overrides.items():
        if isinstance(value, dict) and isinstance(create_kwargs.get(key), dict):
            create_kwargs[key] = {**create_kwargs[key], **value}
        else:
            create_kwargs[key] = value

    import time as _time, sys as _sys
    _vr_model_id = str(model_args.get("model_id") or "")
    print(
        f"[llm:req] model={_vr_model_id} stage=visual_recovery"
        f" pages={page_start}-{page_end} markers={missing_markers[:5]}",
        file=_sys.stderr, flush=True,
    )
    _t0 = _time.monotonic()
    try:
        response = client.chat.completions.create(**create_kwargs)
    except Exception as _api_exc:
        _dur = _time.monotonic() - _t0
        print(
            f"[llm:res] model={_vr_model_id} stage=visual_recovery"
            f" pages={page_start}-{page_end} dur={_dur:.1f}s err={_api_exc}",
            file=_sys.stderr, flush=True,
        )
        raise
    _dur = _time.monotonic() - _t0
    print(
        f"[llm:res] model={_vr_model_id} stage=visual_recovery"
        f" pages={page_start}-{page_end} dur={_dur:.1f}s ok",
        file=_sys.stderr, flush=True,
    )
    raw_text = ""
    if response.choices and getattr(response.choices[0], "message", None):
        try:
            from translation.translator import _extract_openai_message_text

            raw_text = _extract_openai_message_text(
                getattr(response.choices[0].message, "content", "")
            )
        except Exception:
            raw_text = str(getattr(response.choices[0].message, "content", "") or "")

    if not raw_text:
        return []
    return _parse_visual_findings(raw_text)


def _resolve_model_args() -> dict | None:
    try:
        from persistence.storage import resolve_fnm_model_pool_specs

        specs = resolve_fnm_model_pool_specs()
    except Exception:
        return None
    if not specs:
        return None
    spec = specs[0]
    if not str(spec.api_key or "").strip():
        return None
    return {
        "provider": str(spec.provider or "").strip(),
        "model_id": str(spec.model_id or "").strip(),
        "api_key": str(spec.api_key or "").strip(),
        "base_url": str(spec.base_url or "").strip(),
        "request_overrides": dict(spec.request_overrides or {}),
    }


def run_visual_anchor_recovery(
    gap: ChapterAnchorGap,
    phase2: Phase2Structure,
    pages: list[dict],
    pdf_path: str,
    body_anchors: list[BodyAnchorRecord] | None = None,
) -> list[BodyAnchorRecord]:
    """对单个章节缺口执行视觉 anchor 恢复。"""
    if not VISUAL_RECOVERY_ENABLED:
        return []
    if not pdf_path or not gap.missing_markers:
        return []

    page_by_no = _page_payload_by_no(pages)
    min_page, max_page = _resolve_gap_page_range(gap, list(body_anchors or []))

    if min_page <= 0 or max_page <= 0:
        return []

    sample_pages = _sample_page_range(min_page, max_page, VISUAL_RECOVERY_MAX_IMAGES)

    # 渲染页面（微进程，每次渲染后 OS 回收内存）
    rendered: list[dict] = []
    for pno in sample_pages:
        data_url = _render_page_image(pdf_path, pno)
        if data_url:
            rendered.append({"page_no": pno, "image_url": data_url})

    if not rendered:
        print(
            f"[visual_recovery] 无可渲染页面 chapter={gap.chapter_id} 跳过"
        )
        return []

    # 模型配置
    model_args = _resolve_model_args()
    if not model_args:
        print("[visual_recovery] 无可用模型配置，跳过")
        return []

    started = time.time()
    try:
        findings = _request_visual_findings(
            model_args=model_args,
            rendered=rendered,
            missing_markers=gap.missing_markers,
            page_start=min_page,
            page_end=max_page,
        )
    except Exception as exc:
        print(
            f"[visual_recovery] VLM 调用失败 (chapter={gap.chapter_id}): {exc}"
        )
        return []

    duration_ms = int(max(0.0, (time.time() - started) * 1000.0))
    if not findings:
        print(
            f"[visual_recovery] VLM 返回空响应 (chapter={gap.chapter_id})"
        )
        return []

    # 确保每个 finding 有有效的 page_no（VLM 可能漏填或返回罗马数字）
    for f in findings:
        raw_pno = f.get("page_no")
        try:
            page_no = int(raw_pno or 0)
        except (ValueError, TypeError):
            page_no = _roman_to_int(str(raw_pno or ""))
        if page_no <= 0:
            f["page_no"] = min_page
        else:
            f["page_no"] = page_no

    anchors, summary = _materialize_visual_findings(
        findings=findings,
        gap=gap,
        page_by_no=page_by_no,
        candidate_pages=sample_pages,
    )
    recovered_markers = {
        int(anchor.normalized_marker)
        for anchor in anchors
        if str(anchor.normalized_marker or "").isdigit()
    }
    retry_markers = [
        marker
        for marker in gap.missing_markers
        if marker not in recovered_markers
    ][:VISUAL_RECOVERY_MAX_RETRY_MARKERS]
    if retry_markers:
        retry_findings: list[dict[str, Any]] = []
        retry_started = time.time()
        for marker in retry_markers:
            try:
                retry_findings.extend(
                    _request_visual_findings(
                        model_args=model_args,
                        rendered=rendered,
                        missing_markers=[marker],
                        page_start=min_page,
                        page_end=max_page,
                    )
                )
            except Exception as exc:
                print(
                    f"[visual_recovery] VLM 重试失败 "
                    f"(chapter={gap.chapter_id}, marker={marker}): {exc}"
                )
        if retry_findings:
            retry_gap = ChapterAnchorGap(
                chapter_id=gap.chapter_id,
                expected_markers=set(gap.expected_markers),
                detected_markers=set(gap.detected_markers),
                missing_markers=retry_markers,
                gap_count=len(retry_markers),
                gap_rate=gap.gap_rate,
                body_page_range=gap.body_page_range,
            )
            retry_anchors, retry_summary = _materialize_visual_findings(
                findings=retry_findings,
                gap=retry_gap,
                page_by_no=page_by_no,
                candidate_pages=sample_pages,
            )
            for anchor in retry_anchors:
                try:
                    marker = int(anchor.normalized_marker)
                except (ValueError, TypeError):
                    continue
                if marker in recovered_markers:
                    continue
                recovered_markers.add(marker)
                anchors.append(anchor)
            summary["found"] += int(retry_summary.get("found") or 0)
            summary["mapped"] += int(retry_summary.get("mapped") or 0)
            summary["match_failed"] += int(retry_summary.get("match_failed") or 0)
            duration_ms += int(max(0.0, (time.time() - retry_started) * 1000.0))

    if summary.get("found"):
        print(
            f"[visual_recovery] chapter={gap.chapter_id}: "
            f"gap={gap.gap_count}, found={summary['found']}, "
            f"mapped={summary['mapped']}, failed={summary['match_failed']}, "
            f"duration={duration_ms}ms"
        )

    return anchors


# ---------------------------------------------------------------------------
# 顶层入口：输出 review overrides（与 LLM repair 一致的数据路径）
# ---------------------------------------------------------------------------


def build_visual_recovery_overrides(
    phase2: Phase2Structure,
    body_anchors: list[BodyAnchorRecord],
    pages: list[dict],
    pdf_path: str,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Phase 2 尾部 gap 检测 → 生成 anchor + link overrides。

    Returns {scope: {id: payload}}，scope ∈ {"anchor", "link"}。
    调用方负责合并到已有 overrides 中。
    """
    if not VISUAL_RECOVERY_ENABLED:
        return {}

    if not pdf_path:
        return {}

    gaps = compute_chapter_anchor_gaps(phase2, body_anchors)
    print(f"[visual_recovery] gaps found: {len(gaps)}")
    if not gaps:
        return {}

    # 构建 (chapter_id, marker) → note_item_id 查找
    note_item_lookup: dict[tuple[str, str], str] = {}
    for item in phase2.note_items:
        key = (str(item.chapter_id or "").strip(), str(item.marker or "").strip())
        if key[0] and key[1]:
            note_item_lookup[key] = str(item.note_item_id or "")

    anchor_overrides: dict[str, dict[str, Any]] = {}
    link_overrides: dict[str, dict[str, Any]] = {}
    chapter_results: list[dict] = []

    for gap in gaps:
        try:
            recovered = run_visual_anchor_recovery(
                gap=gap,
                phase2=phase2,
                pages=pages,
                pdf_path=pdf_path,
                body_anchors=body_anchors,
            )
        except Exception as exc:
            print(
                f"[visual_recovery] chapter={gap.chapter_id} 恢复失败，跳过: {exc}"
            )
            recovered = []
        chapter_results.append(
            {
                "chapter_id": gap.chapter_id,
                "gap_count": gap.gap_count,
                "gap_rate": round(gap.gap_rate, 3),
                "missing_markers": gap.missing_markers,
                "recovered_count": len(recovered),
            }
        )

        for anchor in recovered:
            anchor_overrides[anchor.anchor_id] = {
                "action": "create",
                "anchor_id": anchor.anchor_id,
                "chapter_id": anchor.chapter_id,
                "page_no": anchor.page_no,
                "paragraph_index": anchor.paragraph_index,
                "char_start": anchor.char_start,
                "char_end": anchor.char_end,
                "normalized_marker": anchor.normalized_marker,
                "source_marker": anchor.source_marker,
                "source": "visual_repair",
                "source_text": anchor.source_text,
                "synthetic": False,
                "certainty": anchor.certainty,
                "anchor_kind": "endnote",
            }

            ni_key = (
                str(anchor.chapter_id or "").strip(),
                str(anchor.normalized_marker or "").strip(),
            )
            note_item_id = note_item_lookup.get(ni_key, "")
            if note_item_id:
                link_id = f"visual-link-{anchor.anchor_id}"
                link_overrides[link_id] = {
                    "action": "match",
                    "note_item_id": note_item_id,
                    "anchor_id": anchor.anchor_id,
                }

    print(
        f"[visual_recovery] override_summary: "
        f"anchors={len(anchor_overrides)} links={len(link_overrides)} "
        f"chapters={[r['chapter_id'] for r in chapter_results]}"
    )

    result: dict[str, dict[str, dict[str, Any]]] = {}
    if anchor_overrides:
        result["anchor"] = anchor_overrides
    if link_overrides:
        result["link"] = link_overrides
    return result

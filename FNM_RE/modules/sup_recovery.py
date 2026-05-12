"""sup_recovery — 上标恢复模块

从三个数据源恢复 OCR 丢失的正文上标标记，写入 enriched_markdown 字段：
  Layer 0: Unicode 上标 → <sup>N</sup> 正则归一化（零 token）
  Layer 1: PyMuPDF 字体分析（仅限原生文字层 PDF）
  Layer 2: OCR raw block 文本对齐
  Layer 3: 视觉模型 PDF 页面裁剪识别（5x 文本区，仅用于 Layer 1+2 无法恢复的孤儿 marker）

恢复决策在**章级别**——因为"某章缺失 marker N"是章级事实，单页无法判断。
上游（Phase 1/2）提供 page_role 和 chapter 边界，本模块只消费、不重新推断。

调用点：pipeline.py Phase 2 之后、Phase 3 之前。
"""

from __future__ import annotations

import re
import gc
import os
import zlib
import struct
from typing import Optional, Callable

try:
    import fitz as _fitz
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

# ── 常量 ──────────────────────────────────────────────────────────────────

_BODY_SIZE_RATIO = 0.72
_FN_AREA_RATIO   = 0.65
_MAX_GAP_CHARS   = 15
_SUP_FMT         = "<sup>{}</sup>"
_VISION_TIMEOUT_SECONDS = 45.0

# ── 内存守卫 ──
_MEMORY_LIMIT_PCT = float(os.environ.get("SUP_RECOVERY_MEMORY_LIMIT", "90"))  # 默认 90%

def _check_memory():
    """当系统内存使用率 >= _MEMORY_LIMIT_PCT% 时，主动抛异常终止当前阶段。"""
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.split()[0])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        if total > 0:
            used_pct = (total - avail) / total * 100
            if used_pct >= _MEMORY_LIMIT_PCT:
                raise MemoryError(
                    f"内存使用率 {used_pct:.1f}% >= {_MEMORY_LIMIT_PCT:.0f}%，"
                    f" 主动终止 sup_recovery（已完成的结果已写入 pages）"
                )
    except MemoryError:
        raise
    except Exception:
        pass  # 非 Linux 环境跳过

_UNICODE_SUP_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_UNICODE_SUP_RE  = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")

# 已存在的显式上标检测（精确匹配特定 marker 值）
_HAS_MARKER_RE_TEMPLATE = (
    r"<sup>\s*{marker}\s*</sup>"
    r"|\$\s*\^\{{\s*{marker}\s*\}}\s*\$"
    r"|\[\^{marker}\]"
)

# 视觉调用缓存。key 必须包含 target_marker；同页不同 marker 不能共享负结果。
_LAYER3_CACHE: dict[tuple, dict | None] = {}

_vision_client: object | None = None
_vision_client_spec_hash: int = 0


def _get_or_create_vision_client(spec: object) -> object:
    """返回复用的 OpenAI vision client，避免每次调用重建导致 TCP 连接泄漏。"""
    global _vision_client, _vision_client_spec_hash
    spec_hash = hash((
        str(getattr(spec, "api_key", "") or ""),
        str(getattr(spec, "base_url", "") or ""),
        str(getattr(spec, "model_id", "") or ""),
    ))
    if _vision_client is None or _vision_client_spec_hash != spec_hash:
        if _vision_client is not None:
            try:
                _vision_client.close()
            except Exception:
                pass
        from openai import OpenAI
        _vision_client = OpenAI(
            api_key=str(getattr(spec, "api_key", "") or "").strip(),
            base_url=str(getattr(spec, "base_url", "") or "").strip(),
            timeout=_VISION_TIMEOUT_SECONDS,
            max_retries=0,
        )
        _vision_client_spec_hash = spec_hash
    return _vision_client


# ═══════════════════════════════════════════════════════════════════════════
# 公共 API
# ═══════════════════════════════════════════════════════════════════════════

def recover_book_chapter_scoped(
    pages: list[dict],
    chapter_note_markers: dict[str, set[str]],  # chapter_id → {"1","2",...,"18"}
    chapter_page_ranges: dict[str, tuple[int, int]],  # chapter_id → (start, end)
    *,
    pdf_path: str = "",
    persist_fn: Callable[[list[int]], None] | None = None,
) -> dict:
    """
    章级上标恢复。

    对每个 chapter，找出 marker 缺失的 body 页，逐级尝试恢复。
    返回 stats dict，同时原位修改 pages[i]['enriched_markdown']。

    若提供 persist_fn，每章处理后调用 persist_fn(modified_page_numbers)，
    调用方可写入 DB 并清理对应页面的 markdown 字段以释放内存。
    """
    _load_markdown_from_raw_pages(pages, pdf_path)

    stats = {
        "layer0_unicode": 0,
        "layer1_pymupdf": 0,
        "layer2_raw_blocks": 0,
        "layer3_vision": 0,
        "unrecovered": 0,
        "pages_enriched": 0,
    }

    doc = None
    if pdf_path and _FITZ_AVAILABLE:
        try:
            doc = _fitz.open(pdf_path)
        except Exception:
            pass

    for ch_id, expected_markers in chapter_note_markers.items():
        if ch_id not in chapter_page_ranges:
            continue
        _check_memory()
        start_page, end_page = chapter_page_ranges[ch_id]
        body_pages = _body_pages_in_range(pages, start_page, end_page)
        if not body_pages:
            continue

        # ── 收集已有的显式上标 ──────────────────────────────────────────
        found_map: dict[int, int] = {}  # marker_int → page_no
        for page in body_pages:
            pn = int(page.get("page_no") or page.get("pdfPage") or 0)
            if not pn:
                continue
            md = page.get("enriched_markdown") or page.get("markdown") or ""
            for m_str in expected_markers:
                if m_str.isdigit() and _has_marker(md, m_str):
                    found_map[int(m_str)] = pn

        # ── 找缺失 marker ───────────────────────────────────────────────
        missing = {int(m) for m in expected_markers if m.isdigit()} - set(found_map)
        if not missing:
            continue

        # ── Layer 0：仅对候选页做 Unicode 归一化（零 token）────────────
        for marker in sorted(missing):
            candidates = _narrow_candidates(marker, found_map, body_pages)
            for page in candidates:
                md = page.get("enriched_markdown") or page.get("markdown") or ""
                enriched, count = _normalize_unicode_superscripts(md)
                if count:
                    page["enriched_markdown"] = enriched
                    stats["layer0_unicode"] += count

        for marker in sorted(missing):
            candidates = _narrow_candidates(marker, found_map, body_pages)
            recovered = False

            for page in candidates:
                pn = int(page.get("page_no") or page.get("pdfPage") or 0)
                if not pn:
                    continue
                md = page.get("enriched_markdown") or page.get("markdown") or ""
                if _has_marker(md, str(marker)):
                    recovered = True
                    break

                # Layer 1: PyMuPDF 字体分析
                if doc and not recovered:
                    pdf_page = None
                    try:
                        pdf_page = doc[pn - 1]
                    except Exception:
                        pass
                    if pdf_page:
                        for r in _layer1_pymupdf(pdf_page, {str(marker)}):
                            pos = _find_insert_pos(md, r["before"], r["after"])
                            if pos >= 0:
                                md = _apply_insertions(md, [(pos, r["marker"], "layer1")])
                                page["enriched_markdown"] = md
                                stats["layer1_pymupdf"] += 1
                                stats["pages_enriched"] += 1
                                recovered = True
                                break

                # Layer 2: raw block 文本对齐
                if not recovered:
                    for r in _layer2_raw_blocks(page.get("blocks") or [], {str(marker)}):
                        replaced = _apply_layer2_recovery(md, r)
                        if replaced is not None:
                            md = replaced
                            page["enriched_markdown"] = md
                            stats["layer2_raw_blocks"] += 1
                            stats["pages_enriched"] += 1
                            recovered = True
                            break
                        pos = _find_insert_pos(md, r["before"], r["after"])
                        if pos >= 0:
                            md = _apply_insertions(md, [(pos, r["marker"], "layer2")])
                            page["enriched_markdown"] = md
                            stats["layer2_raw_blocks"] += 1
                            stats["pages_enriched"] += 1
                            recovered = True
                            break

                if recovered:
                    break

            # Layer 3: 视觉模型裁剪扫描（逐候选页尝试）
            # 注意：L3 阶段不信任 _has_marker 预检——到达这里说明 L0-L2 已
            # 穷尽且 marker 仍未恢复，_has_marker 的假阳性（如 OCR 把上标 8
            # 误读为 6 而裸数字 8 出现在 \"XVIIIe\" 中）不应阻断视觉扫描。
            if not recovered and pdf_path and candidates:
                for cp in candidates[:3]:
                    _check_memory()  # 每次 L3 视觉 API 调用前检查内存
                    cpn = int(_page_no(cp))
                    cp_md = cp.get("enriched_markdown") or cp.get("markdown") or ""
                    existing_on_page = [m for m in found_map if found_map[m] == cpn]
                    print(f"[sup_recovery] L3 scan ch={ch_id[:40]} marker={marker} page={cpn} existing={existing_on_page[:3]}")
                    r = _vision_find_superscript(pdf_path, cpn, marker)
                    if not r:
                        print(f"[sup_recovery] L3 not found marker={marker} page={cpn}")
                        continue
                    found_marker = str(r.get("marker") or "").strip()
                    if not found_marker.isdigit():
                        print(f"[sup_recovery] L3 REJECTED page={cpn}: marker missing")
                        continue
                    if int(found_marker) != int(marker):
                        print(
                            f"[sup_recovery] L3 REJECTED page={cpn}: "
                            f"requested marker {marker}, found {found_marker}"
                        )
                        continue
                    if int(found_marker) in existing_on_page:
                        print(f"[sup_recovery] L3 REJECTED page={cpn}: marker {found_marker} already exists")
                        continue
                    # L3 来自视觉模型，必须用双侧上下文唯一定位；不能落回
                    # after-only/before-only 的宽松文本搜索，否则会把模型给出的
                    # 常见词误插到同页另一处相似正文。
                    pos = _find_layer3_insert_pos(cp_md, r["before"], r["after"])
                    if pos < 0:
                        print(f"[sup_recovery] L3 REJECTED page={cpn}: context not found")
                        continue
                    print(f"[sup_recovery] L3 INJECTED marker={found_marker} page={cpn} pos={pos}")
                    tag = _SUP_FMT.format(found_marker)
                    cp_md = cp_md[:pos] + tag + cp_md[pos:]
                    cp["enriched_markdown"] = cp_md
                    stats["layer3_vision"] += 1
                    stats["pages_enriched"] += 1
                    recovered = True
                    break

            if not recovered:
                stats["unrecovered"] += 1
                if marker <= 18:
                    print(f"[sup_recovery] UNRECOVERED ch={ch_id[:40]} marker={marker}")

        # 每章结束：持久化已修改页面 + 释放内存
        if persist_fn and start_page > 0:
            modified_pns = [
                int(_page_no(p)) for p in body_pages
                if p.get("enriched_markdown")
            ]
            if modified_pns:
                try:
                    persist_fn(modified_pns)
                    # 释放已持久化页面的 markdown 文本以回收内存
                    for p in body_pages:
                        p.pop("markdown", None)
                        p.pop("enriched_markdown", None)
                except Exception:
                    pass  # 持久化失败不阻断流程
        _LAYER3_CACHE.clear()
        gc.collect()

    if doc:
        doc.close()
    return stats


# ═══════════════════════════════════════════════════════════════════════════
# Layer 0：Unicode 上标归一化
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_unicode_superscripts(markdown: str) -> tuple[str, int]:
    count = 0
    def _replace(m: re.Match) -> str:
        nonlocal count
        digits = m.group().translate(_UNICODE_SUP_MAP)
        if digits.isdigit():
            count += 1
            return _SUP_FMT.format(digits)
        return m.group()
    return _UNICODE_SUP_RE.sub(_replace, markdown), count


# ═══════════════════════════════════════════════════════════════════════════
# 候选页框定
# ═══════════════════════════════════════════════════════════════════════════

def _narrow_candidates(
    marker: int,
    found_map: dict[int, int],
    body_pages: list[dict],
) -> list[dict]:
    """用前后已知 marker 的页码框定缺失 marker 的候选页区间。"""
    prev_pn = max((pn for m, pn in found_map.items() if m < marker), default=None)
    next_pn = min((pn for m, pn in found_map.items() if m > marker), default=None)
    lo = prev_pn if prev_pn else _page_no(body_pages[0])
    hi = next_pn if next_pn else _page_no(body_pages[-1])
    return [p for p in body_pages if lo <= _page_no(p) <= hi]


def _body_pages_in_range(
    pages: list[dict],
    start_page: int,
    end_page: int,
) -> list[dict]:
    """筛选正文页（有 markdown 文本且 page_role=body）。"""
    result = []
    for p in pages:
        pn = int(p.get("page_no") or p.get("pdfPage") or 0)
        if not pn or pn < start_page or pn > end_page:
            continue
        role = p.get("page_role", "")
        if role and role != "body":
            continue
        md = p.get("enriched_markdown") or p.get("markdown") or ""
        if len(md) >= 200:
            result.append(p)
    return result


def _page_no(page: dict) -> int:
    return int(page.get("page_no") or page.get("pdfPage") or 0)


# ═══════════════════════════════════════════════════════════════════════════
# Marker 检测
# ═══════════════════════════════════════════════════════════════════════════

def _has_marker(markdown: str, marker: str) -> bool:
    """精确检测 markdown 中是否已有 marker 的显式上标格式。"""
    esc = re.escape(str(marker))
    return bool(re.search(
        rf"<sup>\s*{esc}\s*</sup>"
        rf"|\$\s*\^\{{\s*{esc}\s*\}}\s*\$"
        rf"|\[\^{esc}\]",
        markdown,
    ))


# ═══════════════════════════════════════════════════════════════════════════
# Layer 1：PyMuPDF 字体分析
# ═══════════════════════════════════════════════════════════════════════════

def _layer1_pymupdf(pdf_page: object, missing: set[str]) -> list[dict]:
    if not _FITZ_AVAILABLE:
        return []

    blocks_data = pdf_page.get_text("dict", flags=_fitz.TEXT_PRESERVE_WHITESPACE)
    size_counts: dict[float, int] = {}
    all_spans: list[dict] = []
    for block in blocks_data["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                sz = round(span["size"], 1)
                size_counts[sz] = size_counts.get(sz, 0) + len(span["text"])
                all_spans.append(span)

    if not size_counts:
        return []

    body_size = max(size_counts, key=size_counts.get)
    page_height = pdf_page.rect.height
    fn_cutoff = page_height * _FN_AREA_RATIO

    target_ints: set[int] = set()
    for m in missing:
        if m.isdigit():
            target_ints.add(int(m))

    results: list[dict] = []
    seen_markers: set[str] = set()

    for i, span in enumerate(all_spans):
        y = span["bbox"][1]
        raw_text = span["text"].strip()
        text = raw_text.rstrip("•·.,;: ")
        if not (
            span["size"] < body_size * _BODY_SIZE_RATIO
            and text.isdigit()
            and int(text) in target_ints
            and y < fn_cutoff
        ):
            continue

        marker = text
        if marker in seen_markers:
            continue
        seen_markers.add(marker)

        before = "".join(all_spans[j]["text"] for j in range(max(0, i - 5), i))
        after = "".join(all_spans[j]["text"] for j in range(i + 1, min(len(all_spans), i + 6)))
        results.append({
            "marker": marker,
            "before": before[-40:],
            "after": after[:40],
        })

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Layer 2：Raw block 文本对齐
# ═══════════════════════════════════════════════════════════════════════════

def _layer2_raw_blocks(blocks: list, missing: set[str]) -> list[dict]:
    results: list[dict] = []
    seen_markers: set[str] = set()

    for block in blocks:
        text = str(block.get("text") or "")
        if not text or len(text) < 3:
            continue
        for m in sorted(missing, key=lambda x: -len(x)):
            if not m.isdigit() or m in seen_markers:
                continue
            pattern = rf'([A-Za-zÀ-ÿ])({re.escape(m)})([•·\s,;:\.\)])'
            match = re.search(pattern, text)
            if not match:
                continue
            pos = match.start()
            before = text[max(0, pos - 30): pos + 1]
            after_start = match.end() - 1
            after = text[after_start: after_start + 40]
            seen_markers.add(m)
            results.append({"marker": m, "before": before, "after": after})

        for m in sorted(missing, key=lambda x: -len(x)):
            if not m.isdigit() or m in seen_markers:
                continue
            surrogate = _ocr_surrogate_for_marker(m)
            if not surrogate:
                continue
            pattern = rf"(?P<before>[A-Za-zÀ-ÿ])\s*(?P<surrogate>{surrogate})(?=\s+[A-Za-zÀ-ÿ])"
            match = re.search(pattern, text)
            if not match:
                continue
            pos = match.start("surrogate")
            before = text[max(0, pos - 40):pos].rstrip()
            after = text[match.end("surrogate"): match.end("surrogate") + 40]
            seen_markers.add(m)
            results.append({"marker": m, "before": before, "after": after})

        for m in sorted(missing, key=lambda x: -len(x)):
            if not m.isdigit() or m in seen_markers:
                continue
            suffix = _ocr_suffix_surrogate_for_marker(m)
            if not suffix:
                continue
            pattern = (
                rf"(?P<word>[A-Za-zÀ-ÿ]{{3,}})\s+"
                rf"(?P<suffix>{re.escape(suffix)})(?P<trail>[•·,;:\.\)\]])"
            )
            for match in re.finditer(pattern, text):
                pos = match.start("suffix")
                before = text[max(0, pos - 40):pos].rstrip()
                after = text[match.end("suffix"): match.end("suffix") + 40]
                seen_markers.add(m)
                results.append({
                    "marker": m,
                    "before": before,
                    "after": after,
                    "suffix": suffix,
                    "mode": "ocr_suffix",
                })
                break

        for m in sorted(missing, key=lambda x: -len(x)):
            if not m.isdigit() or m in seen_markers:
                continue
            symbol = _ocr_symbol_surrogate_for_marker(m)
            if not symbol:
                continue
            marker = re.escape(m)
            pattern = (
                rf"(?P<year>(?:\[\d{{2}}\]|(?:1[5-9]|20)\d{{0,2}}){marker})"
                rf"\s+(?P<symbol>{symbol})(?=\s+[A-Za-zÀ-ÿ])"
            )
            for match in re.finditer(pattern, text):
                pos = match.start("symbol")
                before = text[max(0, pos - 50):pos].rstrip()
                after = text[match.end("symbol"): match.end("symbol") + 50]
                seen_markers.add(m)
                results.append({
                    "marker": m,
                    "before": before,
                    "after": after,
                    "symbol": match.group("symbol"),
                    "mode": "ocr_symbol_after_year",
                })
                break

    return results


def _ocr_surrogate_for_marker(marker: str) -> str:
    normalized = str(marker or "").strip()
    if len(normalized) < 2 or set(normalized) != {"1"}:
        return ""
    return r"!{" + str(len(normalized)) + r",}"


def _ocr_suffix_surrogate_for_marker(marker: str) -> str:
    normalized = str(marker or "").strip()
    if len(normalized) != 2 or not normalized.isdigit():
        return ""
    if normalized[0] == normalized[1]:
        return ""
    return normalized[-1]


def _ocr_symbol_surrogate_for_marker(marker: str) -> str:
    normalized = str(marker or "").strip()
    if len(normalized) != 2 or not normalized.isdigit():
        return ""
    return r"[*#%?]{1,2}"


# ═══════════════════════════════════════════════════════════════════════════
# Layer 3：视觉模型 PDF 裁剪识别
# ═══════════════════════════════════════════════════════════════════════════

def _vision_find_superscript(
    pdf_path: str,
    page_no: int,
    target_marker: int,
) -> dict | None:
    """5x 文本区裁剪 → 视觉模型找特定上标 → 返回 {marker, before, after} 或 None。"""
    cache_key = ("vision", pdf_path, page_no, int(target_marker))
    if cache_key in _LAYER3_CACHE:
        cached = _LAYER3_CACHE[cache_key]
        return dict(cached) if cached else None

    # 渲染页面图片（3x 精度，JPEG 格式省内存）
    try:
        doc = _fitz.open(pdf_path)
        page = doc[page_no - 1]
        rect = page.rect
        text_rect = _fitz.Rect(rect.x0 + 30, rect.y0 + 40, rect.x1 - 30, rect.y1 - 50)
        mat = _fitz.Matrix(5.0, 5.0)
        pix = page.get_pixmap(matrix=mat, clip=text_rect)
        img_bytes = pix.tobytes("png")  # PNG 无损，保证上标清晰
        pix = None
        doc.close()
    except Exception:
        return None

    import base64
    b64 = base64.b64encode(img_bytes).decode()
    img_bytes = None
    data_url = "data:image/png;base64," + b64

    try:
        from persistence.storage import resolve_visual_model_spec
        spec = resolve_visual_model_spec()
    except Exception:
        return None

    if not spec or not getattr(spec, "supports_vision", False):
        return None

    prompt = (
        f"这个法文PDF页面正文片段中有一个上标数字 {target_marker}（小号数字标记）。"
        f"请找到它，并返回它紧前面和紧后面的文字上下文（各20-40个字符）。"
        f'只返回JSON：{{"marker":"{target_marker}","before":"前面的文字","after":"后面的文字"}}'
        f"如果找不到，返回 {{\"marker\":\"\",\"before\":\"\",\"after\":\"\"}}。"
    )

    try:
        client = _get_or_create_vision_client(spec)
        extra_body = dict(getattr(spec, "request_overrides", {}).get("extra_body", {}) or {})
        response = client.chat.completions.create(
            model=str(getattr(spec, "model_id", "") or "").strip(),
            max_tokens=400,
            timeout=_VISION_TIMEOUT_SECONDS,
            extra_body=extra_body,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
        )
        raw_text = response.choices[0].message.content or ""
    except Exception:
        return None

    import json as _json
    try:
        clean = raw_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rstrip("```")
        parsed = _json.loads(clean)
        if isinstance(parsed, dict):
            marker = str(parsed.get("marker", "") or "").strip()
            before = str(parsed.get("before", "") or "").strip()
            after = str(parsed.get("after", "") or "").strip()
            if marker and marker.isdigit() and int(marker) == int(target_marker):
                result = {"marker": marker, "before": before[-40:], "after": after[:40]}
                _LAYER3_CACHE[cache_key] = result
                return result
    except (_json.JSONDecodeError, TypeError, AttributeError):
        pass

    _LAYER3_CACHE[cache_key] = None
    return None


# ═══════════════════════════════════════════════════════════════════════════
# 位置查找 & 插入
# ═══════════════════════════════════════════════════════════════════════════

def _find_insert_pos(markdown: str, before_ctx: str, after_ctx: str) -> int:
    before_words = re.findall(r'[A-Za-zÀ-ÿ]{3,}', before_ctx)
    after_words  = re.findall(r'[A-Za-zÀ-ÿ]{3,}', after_ctx)

    if before_words and after_words:
        bw = re.escape(before_words[-1])
        aw = re.escape(after_words[0])
        m = re.search(rf'{bw}.{{0,{_MAX_GAP_CHARS}}}{aw}', markdown, re.IGNORECASE)
        if m:
            inner = re.search(bw, m.group(), re.IGNORECASE)
            if inner:
                return m.start() + inner.end()

    if after_words:
        aw = re.escape(after_words[0])
        m = re.search(rf'\b{aw}\b', markdown, re.IGNORECASE)
        if m:
            return m.start()

    if before_words:
        bw = re.escape(before_words[-1])
        matches = list(re.finditer(rf'\b{bw}\b', markdown, re.IGNORECASE))
        if matches:
            pos = matches[-1].end()
            while pos < len(markdown) and markdown[pos] in '•·?~=_':
                pos += 1
            return pos

    return -1


def _context_word_pattern(words: list[str]) -> str:
    return r"\b" + r".{0,12}".join(re.escape(word) for word in words) + r"\b"


def _find_layer3_insert_pos(markdown: str, before_ctx: str, after_ctx: str) -> int:
    before_words = re.findall(r"[A-Za-zÀ-ÿ]{3,}", str(before_ctx or ""))
    after_words = re.findall(r"[A-Za-zÀ-ÿ]{3,}", str(after_ctx or ""))
    if not before_words or not after_words:
        return -1

    max_before = min(3, len(before_words))
    max_after = min(3, len(after_words))
    for before_len in range(max_before, 0, -1):
        before_tail = before_words[-before_len:]
        before_pat = _context_word_pattern(before_tail)
        for after_len in range(max_after, 0, -1):
            after_head = after_words[:after_len]
            after_pat = _context_word_pattern(after_head)
            pattern = (
                rf"(?P<before>{before_pat})"
                rf"(?P<gap>.{{0,{_MAX_GAP_CHARS}}})"
                rf"(?P<after>{after_pat})"
            )
            matches = list(re.finditer(pattern, markdown, re.IGNORECASE | re.DOTALL))
            if len(matches) == 1:
                return int(matches[0].end("before"))
            if len(matches) > 1:
                return -1
    return -1


def _apply_layer2_recovery(markdown: str, recovery: dict) -> str | None:
    marker = str(recovery.get("marker") or "").strip()
    if not marker:
        return None
    mode = str(recovery.get("mode") or "")
    if mode not in {"ocr_suffix", "ocr_symbol_after_year"}:
        return None

    after_words = re.findall(r"[A-Za-zÀ-ÿ]{3,}", str(recovery.get("after") or ""))
    if mode == "ocr_suffix":
        suffix = str(recovery.get("suffix") or "").strip()
        if not suffix:
            return None
        before_words = re.findall(r"[A-Za-zÀ-ÿ]{3,}", str(recovery.get("before") or ""))
        if not before_words:
            return None
        before_word = re.escape(before_words[-1])
        pattern = (
            rf"(?P<before>\b{before_word})"
            rf"(?P<gap>\s+)"
            rf"(?P<target>{re.escape(suffix)})"
            rf"(?P<trail>[•·,;:\.\)\]])"
            rf"(?P<after>.{{0,80}})"
        )
    else:
        symbol = str(recovery.get("symbol") or "").strip()
        if not symbol:
            return None
        marker_esc = re.escape(marker)
        pattern = (
            rf"(?P<before>(?:\[\d{{2}}\]|(?:1[5-9]|20)\d{{0,2}}){marker_esc})"
            rf"(?P<gap>\s+)"
            rf"(?P<target>{re.escape(symbol)})"
            rf"(?P<after>.{{0,80}})"
        )
    matches = list(re.finditer(pattern, markdown, re.IGNORECASE | re.DOTALL))
    if after_words:
        after_word = re.compile(rf"\b{re.escape(after_words[0])}\b", re.IGNORECASE)
        matches = [m for m in matches if after_word.search(m.group("after"))]
    if len(matches) != 1:
        return None

    match = matches[0]
    start = int(match.start("gap"))
    end = int(match.end("target"))
    return markdown[:start] + _SUP_FMT.format(marker) + markdown[end:]


def _apply_insertions(markdown: str, insertions: list[tuple[int, str, str]]) -> str:
    if not insertions:
        return markdown
    seen: set[str] = set()
    deduped = []
    for pos, marker, src in insertions:
        if marker not in seen:
            seen.add(marker)
            deduped.append((pos, marker, src))
    result = markdown
    for pos, marker, _ in sorted(deduped, key=lambda x: x[0], reverse=True):
        result = result[:pos] + _SUP_FMT.format(marker) + result[pos:]
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 桥接：DB pages → raw_pages.json markdown 加载
# ═══════════════════════════════════════════════════════════════════════════

def _load_markdown_from_raw_pages(pages: list[dict], pdf_path: str) -> None:
    """从 raw_pages.json 逐页流式加载 markdown，只提取需要字段，避免全量加载。"""
    import os as _os, json as _json

    if pages and any(p.get("markdown") or p.get("enriched_markdown") for p in pages[:1]):
        return

    pdf_dir = _os.path.dirname(pdf_path)
    candidates = [pdf_dir]
    repo_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(pdf_dir)))
    test_dir = _os.path.join(repo_root, "test_example")
    if _os.path.isdir(test_dir):
        for entry in _os.listdir(test_dir):
            entry_path = _os.path.join(test_dir, entry)
            if _os.path.isdir(entry_path):
                candidates.append(entry_path)

    for candidate_dir in candidates:
        raw_path = _os.path.join(candidate_dir, "raw_pages.json")
        if not _os.path.isfile(raw_path):
            continue

        # 建目标页号集合
        target_pns = set()
        for page in pages:
            pn = page.get("pdfPage") or page.get("page_no")
            if pn:
                target_pns.add(int(pn))

        if not target_pns:
            return

        # 流式解析：只读需要页面的 markdown/blocks/fnBlocks，不加载整个 JSON
        md_map: dict[int, str] = {}
        block_map: dict[int, list] = {}
        fn_map: dict[int, list] = {}
        try:
            with open(raw_path, encoding="utf-8") as fh:
                # 跳过文件头 {"pages": [
                buf = ""
                in_pages = False
                decoder = _json.JSONDecoder()
                for line in fh:
                    buf += line
                    # 找到 pages 数组开始
                    if not in_pages:
                        idx = buf.find('"pages"')
                        if idx >= 0:
                            idx = buf.find("[", idx)
                            if idx >= 0:
                                buf = buf[idx+1:]  # 跳过 [
                                in_pages = True
                        continue

                    # 逐页解析：每次找到完整的 page 对象
                    while True:
                        # 跳过空白和逗号
                        stripped = buf.lstrip()
                        if not stripped:
                            break
                        if stripped[0] == "]":
                            buf = ""
                            break
                        if stripped[0] == ",":
                            buf = stripped[1:]
                            continue
                        if stripped[0] != "{":
                            buf = stripped
                            break

                        try:
                            obj, idx = decoder.raw_decode(stripped)
                            buf = stripped[idx:]
                            pn = obj.get("pdfPage") or obj.get("bookPage")
                            if pn and int(pn) in target_pns:
                                md = obj.get("markdown", "")
                                if md:
                                    md_map[int(pn)] = md
                                    block_map[int(pn)] = obj.get("blocks") or []
                                    fn_map[int(pn)] = obj.get("fnBlocks") or []
                                # 如果已收集完所有目标页，提前退出
                                if len(md_map) >= len(target_pns):
                                    buf = ""
                                    break
                        except _json.JSONDecodeError:
                            # 数据不完整，等下一行
                            break
        except Exception:
            continue

        if not md_map:
            continue

        for page in pages:
            pn = page.get("pdfPage") or page.get("page_no")
            if pn and int(pn) in md_map and not page.get("markdown"):
                page["markdown"] = md_map[int(pn)]
                if not page.get("blocks"):
                    page["blocks"] = block_map.get(int(pn), [])
                if not page.get("fnBlocks"):
                    page["fnBlocks"] = fn_map.get(int(pn), [])

        # 显式释放
        md_map.clear()
        block_map.clear()
        fn_map.clear()
        return

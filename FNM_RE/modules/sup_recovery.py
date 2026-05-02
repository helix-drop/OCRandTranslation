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
import zlib
import struct
from typing import Optional

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

_UNICODE_SUP_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_UNICODE_SUP_RE  = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")

# 已存在的显式上标检测（精确匹配特定 marker 值）
_HAS_MARKER_RE_TEMPLATE = (
    r"<sup>\s*{marker}\s*</sup>"
    r"|\$\s*\^\{{\s*{marker}\s*\}}\s*\$"
    r"|\[\^{marker}\]"
)

# 视觉调用缓存
_LAYER3_CACHE: dict[tuple, list[dict]] = {}


# ═══════════════════════════════════════════════════════════════════════════
# 公共 API
# ═══════════════════════════════════════════════════════════════════════════

def recover_book_chapter_scoped(
    pages: list[dict],
    chapter_note_markers: dict[str, set[str]],  # chapter_id → {"1","2",...,"18"}
    chapter_page_ranges: dict[str, tuple[int, int]],  # chapter_id → (start, end)
    *,
    pdf_path: str = "",
) -> dict:
    """
    章级上标恢复。

    对每个 chapter，找出 marker 缺失的 body 页，逐级尝试恢复。
    返回 stats dict，同时原位修改 pages[i]['enriched_markdown']。
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
            if not recovered and pdf_path and candidates:
                for cp in candidates[:3]:  # 最多试 3 个候选页
                    cpn = int(_page_no(cp))
                    cp_md = cp.get("enriched_markdown") or cp.get("markdown") or ""
                    if _has_marker(cp_md, str(marker)):
                        recovered = True
                        break
                    existing_on_page = [m for m in found_map if found_map[m] == cpn]
                    print(f"[sup_recovery] L3 scan ch={ch_id[:40]} marker={marker} page={cpn} existing={existing_on_page[:3]}")
                    r = _vision_find_superscript(pdf_path, cpn, marker)
                    if not r:
                        print(f"[sup_recovery] L3 not found marker={marker} page={cpn}")
                        continue
                    found_marker = r["marker"]
                    if int(found_marker) in existing_on_page:
                        print(f"[sup_recovery] L3 REJECTED page={cpn}: marker {found_marker} already exists")
                        continue
                    # 交叉验证：before/after 上下文必须在 markdown 中能找到
                    pos = _find_insert_pos(cp_md, r["before"], r["after"])
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
                if marker <= 18:  # only log low markers (most important)
                    print(f"[sup_recovery] UNRECOVERED ch={ch_id[:40]} marker={marker}")

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
    lo = (prev_pn + 1) if prev_pn else _page_no(body_pages[0])
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

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Layer 3：视觉模型 PDF 裁剪识别
# ═══════════════════════════════════════════════════════════════════════════

def _vision_find_superscript(
    pdf_path: str,
    page_no: int,
    target_marker: int,
) -> dict | None:
    """5x 文本区裁剪 → 视觉模型找特定上标 → 返回 {marker, before, after} 或 None。"""
    cache_key = ("vision", pdf_path, page_no)
    if cache_key in _LAYER3_CACHE:
        for r in _LAYER3_CACHE[cache_key]:
            if r["marker"] == str(target_marker):
                return r
        return None

    # 渲染 5x 精度文本区裁剪
    try:
        doc = _fitz.open(pdf_path)
        page = doc[page_no - 1]
        rect = page.rect
        text_rect = _fitz.Rect(rect.x0 + 30, rect.y0 + 40, rect.x1 - 30, rect.y1 - 50)
        mat = _fitz.Matrix(5.0, 5.0)
        pix = page.get_pixmap(matrix=mat, clip=text_rect)
        img_bytes = pix.tobytes("png")
        doc.close()
    except Exception:
        return None

    import base64
    data_url = "data:image/png;base64," + base64.b64encode(img_bytes).decode()

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
        from openai import OpenAI
        client = OpenAI(
            api_key=str(getattr(spec, "api_key", "") or "").strip(),
            base_url=str(getattr(spec, "base_url", "") or "").strip(),
        )
        extra_body = dict(getattr(spec, "request_overrides", {}).get("extra_body", {}) or {})
        response = client.chat.completions.create(
            model=str(getattr(spec, "model_id", "") or "").strip(),
            max_tokens=400,
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
            if marker and marker.isdigit():
                result = {"marker": marker, "before": before[-40:], "after": after[:40]}
                _LAYER3_CACHE.setdefault(cache_key, []).append(result)
                return result
    except (_json.JSONDecodeError, TypeError, AttributeError):
        pass

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
    """从 pdf_path 同目录的 raw_pages.json 加载 markdown 文本到 pages 中。"""
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
        try:
            with open(raw_path, encoding="utf-8") as fh:
                loaded = _json.load(fh)
        except Exception:
            continue
        loaded_pages = loaded.get("pages") or []
        md_map: dict[int, str] = {}
        block_map: dict[int, list] = {}
        fn_map: dict[int, list] = {}
        for lp in loaded_pages:
            pn = lp.get("pdfPage") or lp.get("bookPage")
            md = lp.get("markdown", "")
            if pn and md:
                md_map[int(pn)] = md
                block_map[int(pn)] = lp.get("blocks") or []
                fn_map[int(pn)] = lp.get("fnBlocks") or []

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
        return

"""sup_recovery — 上标恢复模块

从两个独立数据源恢复 OCR 丢失的正文脚注上标标记，写入 enriched_markdown 字段：
  Layer 1: PyMuPDF 字体分析（仅限原生文字层 PDF，textSource=pdf）
  Layer 2: OCR raw block 文本对齐（所有书通用）

不触碰 note_items / anchors / links 表，只写 page['enriched_markdown']。
下游 body_anchors 优先读 enriched_markdown，检测到 <sup>N</sup> 后
产出 certainty=1.0 的 HTML_SUP anchor，消灭 synthetic 路径。
"""

from __future__ import annotations

import re
from typing import Optional

try:
    import fitz as _fitz  # noqa: F401 — 仅检测是否可用
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

_BODY_SIZE_RATIO = 0.72   # span.size < body_size * N → 上标候选
_FN_AREA_RATIO   = 0.65   # y > page_height * N → 脚注区（跳过）
_MAX_GAP_CHARS   = 15     # 前后文锚之间允许的最大字符数
_SUP_FMT         = "<sup>{}</sup>"

# ─────────────────────────────────────────────────────────────────────────────
# 公共 API
# ─────────────────────────────────────────────────────────────────────────────

def recover_page_superscripts(
    page: dict,
    pdf_page: object = None,   # fitz.Page or None
) -> tuple[str, list[dict]]:
    """
    为单页 markdown 插入已恢复的上标标记。

    返回:
        enriched_markdown: 插入了 <sup>N</sup> 的 markdown 字符串
        log: [{marker, pos, source, recovered}] 恢复日志
    """
    markdown = str(page.get("enriched_markdown") or page.get("markdown") or "")
    fn_blocks = page.get("fnBlocks") or []

    expected = _expected_markers(fn_blocks)
    if not expected:
        return markdown, []

    missing = {m for m in expected if not _has_explicit_sup(markdown, m)}
    if not missing:
        return markdown, []

    insertions: list[tuple[int, str, str]] = []  # (pos, marker, source)

    # ── Layer 1：PyMuPDF 字体分析 ─────────────────────────────────────────────
    if pdf_page is not None and missing:
        for r in _layer1_pymupdf(pdf_page, missing):
            pos = _find_insert_pos(markdown, r["before"], r["after"])
            if pos >= 0:
                insertions.append((pos, r["marker"], "layer1"))
                missing.discard(r["marker"])

    # ── Layer 2：raw block 文本对齐 ───────────────────────────────────────────
    if missing:
        for r in _layer2_raw_blocks(page.get("blocks") or [], missing):
            pos = _find_insert_pos(markdown, r["before"], r["after"])
            if pos >= 0:
                insertions.append((pos, r["marker"], "layer2"))
                missing.discard(r["marker"])

    enriched = _apply_insertions(markdown, insertions)

    log: list[dict] = [
        {"marker": m, "pos": pos, "source": src, "recovered": True}
        for pos, m, src in insertions
    ] + [
        {"marker": m, "recovered": False}
        for m in missing
    ]

    return enriched, log


def recover_book(raw_pages: dict, pdf_path: str | None = None) -> tuple[dict, list[dict]]:
    """
    处理整本书所有页面，写入 enriched_markdown 并返回统计和详细日志。

    返回:
        stats: 汇总统计 dict
        detail: 每页每个 marker 的恢复记录
    """
    pages = raw_pages.get("pages") or []
    doc = None

    if pdf_path and _FITZ_AVAILABLE:
        import fitz as _fitz
        try:
            doc = _fitz.open(pdf_path)
        except Exception:
            pass

    stats = {
        "total_fn_markers": 0,
        "already_explicit": 0,
        "layer1_recovered": 0,
        "layer2_recovered": 0,
        "unrecovered": 0,
        "pages_enriched": 0,
    }
    detail: list[dict] = []

    for page in pages:
        pdf_page_no = page.get("pdfPage")
        pdf_page = None
        if doc is not None and pdf_page_no:
            try:
                pdf_page = doc[pdf_page_no - 1]
            except Exception:
                pass

        fn_markers = _expected_markers(page.get("fnBlocks") or [])
        if not fn_markers:
            continue

        markdown = str(page.get("markdown") or "")
        already = sum(1 for m in fn_markers if _has_explicit_sup(markdown, m))

        stats["total_fn_markers"] += len(fn_markers)
        stats["already_explicit"] += already

        enriched, log = recover_page_superscripts(page, pdf_page)

        l1 = sum(1 for r in log if r.get("recovered") and r.get("source") == "layer1")
        l2 = sum(1 for r in log if r.get("recovered") and r.get("source") == "layer2")
        unr = sum(1 for r in log if not r.get("recovered"))

        stats["layer1_recovered"] += l1
        stats["layer2_recovered"] += l2
        stats["unrecovered"] += unr

        if enriched != markdown:
            page["enriched_markdown"] = enriched
            stats["pages_enriched"] += 1

        for r in log:
            detail.append({
                "page_no": pdf_page_no,
                **r,
            })

    if doc:
        doc.close()

    return stats, detail


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1：PyMuPDF 字体分析
# ─────────────────────────────────────────────────────────────────────────────

def _layer1_pymupdf(pdf_page: object, missing: set[str]) -> list[dict]:
    """从 PDF span 字体大小检测上标位置，返回 [{marker, before, after}]。"""
    if not _FITZ_AVAILABLE:
        return []

    import fitz as _fitz
    blocks_data = pdf_page.get_text("dict", flags=_fitz.TEXT_PRESERVE_WHITESPACE)

    # 确定正文字号（出现字符最多的字号）
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

    # 收集可以作为目标的 marker 整数集合（避免字符串比较）
    target_ints: set[int] = set()
    for m in missing:
        if m.isdigit():
            target_ints.add(int(m))

    results: list[dict] = []
    seen_markers: set[str] = set()  # 每页每个 marker 只取第一次

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


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2：Raw block 文本对齐
# ─────────────────────────────────────────────────────────────────────────────

def _layer2_raw_blocks(blocks: list, missing: set[str]) -> list[dict]:
    """在 OCR raw block 文本中识别内联上标数字，返回 [{marker, before, after}]。"""
    results: list[dict] = []
    seen_markers: set[str] = set()

    for block in blocks:
        text = str(block.get("text") or "")
        if not text or len(text) < 3:
            continue

        for m in sorted(missing, key=lambda x: -len(x)):  # 长 marker 优先
            if not m.isdigit() or m in seen_markers:
                continue

            # 模式：字母 + marker数字 + 分隔符（•·空格,;:.)
            pattern = rf'([A-Za-zÀ-ÿ])({re.escape(m)})([•·\s,;:\.\)])'
            match = re.search(pattern, text)
            if not match:
                continue

            pos = match.start()
            before = text[max(0, pos - 30): pos + 1]   # 含匹配到的那个字母
            after_start = match.end() - 1               # 分隔符开始处
            after = text[after_start: after_start + 40]

            seen_markers.add(m)
            results.append({
                "marker": m,
                "before": before,
                "after": after,
            })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 位置查找
# ─────────────────────────────────────────────────────────────────────────────

def _find_insert_pos(markdown: str, before_ctx: str, after_ctx: str) -> int:
    """
    在 markdown 中找插入 <sup>N</sup> 的位置（字符偏移）。

    策略（按优先级）：
    1. 找 before_last_word + gap + after_first_word 的联合模式
    2. 找 after_first_word，插在它前面
    3. 找 before_last_word，插在它后面（跳过 OCR 噪声字符）
    """
    before_words = re.findall(r'[A-Za-zÀ-ÿ]{3,}', before_ctx)
    after_words  = re.findall(r'[A-Za-zÀ-ÿ]{3,}', after_ctx)

    # ── 策略 1：联合锚 ─────────────────────────────────────────────────────
    if before_words and after_words:
        bw = re.escape(before_words[-1])
        aw = re.escape(after_words[0])
        m = re.search(rf'{bw}.{{0,{_MAX_GAP_CHARS}}}{aw}', markdown, re.IGNORECASE)
        if m:
            # 插入点：bw 末尾之后
            inner = re.search(bw, m.group(), re.IGNORECASE)
            if inner:
                return m.start() + inner.end()

    # ── 策略 2：after 词前 ────────────────────────────────────────────────
    if after_words:
        aw = re.escape(after_words[0])
        m = re.search(rf'\b{aw}\b', markdown, re.IGNORECASE)
        if m:
            return m.start()

    # ── 策略 3：before 词后 ───────────────────────────────────────────────
    if before_words:
        bw = re.escape(before_words[-1])
        # 取最后一次出现（正文中更靠后的位置更可能是上标位置）
        matches = list(re.finditer(rf'\b{bw}\b', markdown, re.IGNORECASE))
        if matches:
            pos = matches[-1].end()
            # 跳过 OCR 噪声字符（? ~ • 等），不跳过真正的标点或空格
            while pos < len(markdown) and markdown[pos] in '•·?~=_':
                pos += 1
            return pos

    return -1


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _expected_markers(fn_blocks: list) -> set[str]:
    """从 fnBlocks 提取本页预期脚注标记。"""
    markers: set[str] = set()
    for fb in fn_blocks:
        text = str(fb.get("text") or "")
        m = re.match(r'(\d+)[.\)]\s', text)
        if m:
            markers.add(m.group(1))
        elif text.lstrip().startswith(("* ", "• ", "- ")):
            markers.add("*")
    return markers


def _has_explicit_sup(markdown: str, marker: str) -> bool:
    """检查 markdown 是否已有该 marker 的显式上标格式。"""
    esc = re.escape(marker)
    patterns = [
        rf'<sup>\s*{esc}\s*</sup>',
        rf'\$\s*\^\{{{esc}\}}\s*\$',
        rf'\[\^{esc}\]',
        rf'\[{esc}\]',
        r'[⁰¹²³⁴⁵⁶⁷⁸⁹]',
    ]
    return any(re.search(p, markdown, re.IGNORECASE) for p in patterns)


def _apply_insertions(markdown: str, insertions: list[tuple[int, str, str]]) -> str:
    """倒序应用所有插入（保持偏移量正确）。"""
    if not insertions:
        return markdown

    # 去重：同一 marker 只保留第一个
    seen: set[str] = set()
    deduped = []
    for pos, marker, src in insertions:
        if marker not in seen:
            seen.add(marker)
            deduped.append((pos, marker, src))

    result = markdown
    for pos, marker, _ in sorted(deduped, key=lambda x: x[0], reverse=True):
        tag = _SUP_FMT.format(marker)
        result = result[:pos] + tag + result[pos:]

    return result

"""FNM_RE 3a 阶段：Footnote 路径（layout 拆分 + 段落挂载）。

对每章每个 body 页：
1. Layout 拆分：识别底部 footnote 条带
   证据：horizontal rule、``^\\d+[\\.）)]\\s+`` 开头的短段落簇
2. 条目切分：按编号前缀切成若干条
3. 挂载规则 (按优先级)：
   (a) 有编号 + 正文找到对应 marker → 挂该段
   (b) 否则 → 挂本页最后一段
   (c) 跨页：尾条无结束标点 + 下页首条无编号开头 → 合并
4. 写入 fnm_paragraph_footnotes
"""

from __future__ import annotations

import re
from typing import Any

from FNM_RE.models import ParagraphFootnoteRecord, Phase1Structure
from FNM_RE.shared.text import page_markdown_text

# 分隔线
_SEPARATOR_RE = re.compile(r"^[-=_]{3,}\s*$")

# 编号脚注条目：1. / 1) / 1） / 1、 / 1] / "1 " 等
# 在 band 上下文中（分隔线后 / 连续编号簇），宽松匹配
_FOOTNOTE_ITEM_RE = re.compile(
    r"^\s*(\d{1,4})(?:\s*[\.、）)\]]\s*|\s+)(.*)",
    re.DOTALL,
)

# 符号型脚注条目：* / ** / *** / **** / † / ‡ / § / ¶
_SYMBOL_FOOTNOTE_ITEM_RE = re.compile(
    r"^\s*(\*{1,4}|†{1,2}|‡{1,2}|§|¶)\s+(.*)",
    re.DOTALL,
)

# 正文中的脚注标记（含符号标记）
_FOOTNOTE_MARKER_IN_BODY = re.compile(
    r"(?:\$\^\{(\d+)\}\$"
    r"|<sup>(\d+)</sup>"
    r"|\[(\d+)\]"
    r"|\$\s*\^\{\s*(\*{1,4})\s*\}\s*\$"          # $^{*}$, $^{**}$ 等
    r"|[\]](\*{1,4})"                               # ]*（括号后的符号标记）
    r"|[»](\*{1,4})"                                # »*（法式引号后的符号标记）
    r")",
)

# 有结束标点（不跨页）
_HAS_END_PUNCTUATION = re.compile(r"[。.!?？!]\s*$")

# 以编号开头（不是跨页续写）— 与 _FOOTNOTE_ITEM_RE 保持一致的分隔方式
_STARTS_WITH_NUMBER = re.compile(r"^\s*\d{1,4}(?:\s*[\.、）)\]]|\s)")


def _split_lines(text: str) -> list[str]:
    """将文本按换行切分为非空行。"""
    if not text:
        return []
    return [line.strip() for line in text.split("\n") if line.strip()]


def _detect_footnote_band(lines: list[str]) -> tuple[int, int]:
    """检测底部 footnote 条带范围。

    优先查找分隔线；无分隔线时从底部向上扫描连续编号行簇或符号行簇。
    至少需要 2 个连续编号行才认为是脚注条带；符号行（* 等）1 行即可。

    Returns:
        (start_line_idx, end_line_idx)，未检测到时返回 (-1, -1)
    """
    if len(lines) < 2:
        return -1, -1

    # 1. 找分隔线
    for i, line in enumerate(lines):
        if _SEPARATOR_RE.match(line):
            return i + 1, len(lines)

    # 2. 从底部扫描连续编号行
    consecutive = 0
    band_start = len(lines)

    for i in range(len(lines) - 1, -1, -1):
        if _FOOTNOTE_ITEM_RE.match(lines[i]):
            consecutive += 1
            if consecutive >= 2:
                band_start = i
                while band_start > 0:
                    prev = band_start - 1
                    if _FOOTNOTE_ITEM_RE.match(lines[prev]):
                        band_start = prev
                    else:
                        break
                return band_start, len(lines)
        else:
            consecutive = 0

    # 3. 从底部扫描符号型脚注行（* 等）
    for i in range(len(lines) - 1, -1, -1):
        if _SYMBOL_FOOTNOTE_ITEM_RE.match(lines[i]):
            # 找到底部最后一组连续符号行
            sym_end = len(lines)
            sym_start = i
            # 向上扩展（处理多个符号行在一起的情况）
            while sym_start > 0:
                prev = sym_start - 1
                if _SYMBOL_FOOTNOTE_ITEM_RE.match(lines[prev]):
                    sym_start = prev
                else:
                    break
            return sym_start, sym_end

    return -1, -1


def _parse_band_lines(lines: list[str]) -> list[dict]:
    """从 band 行中解析出脚注条目。

    编号行 / 符号行开新条目，非编号行续到上一条（多行文本）。
    如果 band 首行无编号/符号，标记为 preamble（跨页续写候选）。
    """
    items: list[dict] = []
    for line in lines:
        m = _FOOTNOTE_ITEM_RE.match(line)
        if m is None:
            m = _SYMBOL_FOOTNOTE_ITEM_RE.match(line)
        if m:
            items.append({
                "marker": m.group(1),
                "text": m.group(2).strip(),
            })
        elif items:
            # 无编号 → 续到上一条
            items[-1]["text"] += " " + line
        else:
            # 首行无编号 → 可能是跨页续写的正文片段
            items.append({"preamble": True, "text": line})
    return items


def _find_page_by_no(pages: list[dict], bp: int) -> dict | None:
    for p in pages:
        if int(p.get("bookPage", 0)) == bp:
            return p
    return None


def _scan_body_lines_for_marker(body_lines: list[str], marker: str) -> int | None:
    """在 body 行中查找匹配 marker 的行索引。"""
    for i, line in enumerate(body_lines):
        for m in _FOOTNOTE_MARKER_IN_BODY.finditer(line):
            matched = m.group(1) or m.group(2) or m.group(3) or m.group(4) or m.group(5) or m.group(6)
            if matched == marker:
                return i
    return None


def _body_page_nos_for_chapter(
    phase1: Phase1Structure,
    chapter_id: str,
) -> list[int]:
    chapter = next(
        (c for c in phase1.chapters if c.chapter_id == chapter_id), None
    )
    if not chapter:
        return []
    chapter_page_set = {int(p) for p in chapter.pages if int(p) > 0}
    return [
        int(p.page_no)
        for p in phase1.pages
        if int(p.page_no) in chapter_page_set
        and str(p.page_role) == "body"
    ]


def build_paragraph_footnotes(
    phase1: Phase1Structure,
    *,
    pages: list[dict],
    doc_id: str = "",
) -> tuple[list[ParagraphFootnoteRecord], dict]:
    """构建段落级脚注挂载。

    Args:
        phase1: 章节与页面角色信息
        pages: 原始页面数据（含 markdown 文本）
        doc_id: 文档 ID

    Returns:
        (ParagraphFootnoteRecord 列表, 统计摘要 dict)
    """
    all_records: list[ParagraphFootnoteRecord] = []
    chapter_stats: dict[str, dict] = {}

    for chapter in phase1.chapters:
        chapter_id = chapter.chapter_id
        body_page_nos = _body_page_nos_for_chapter(phase1, chapter_id)
        if not body_page_nos:
            continue

        # —— Pass 1：逐页检测 band 并解析条目 ——
        page_items: list[list[dict]] = []
        for bp in body_page_nos:
            md = page_markdown_text(_find_page_by_no(pages, bp))
            if not md:
                page_items.append([])
                continue
            lines = _split_lines(md)
            band_start, band_end = _detect_footnote_band(lines)
            if band_start < 0 or band_start >= band_end:
                page_items.append([])
                continue
            items = _parse_band_lines(lines[band_start:band_end])
            page_items.append(items)

        # —— Pass 2：跨页合并 ——
        for i in range(len(page_items) - 1):
            prev_items = page_items[i]
            curr_items = page_items[i + 1]
            if not curr_items:
                continue

            # 2a. 下页 band 首行无编号（preamble）→ 续到上页末条
            if curr_items and curr_items[0].get("preamble"):
                if prev_items:
                    prev_items[-1]["text"] += " " + curr_items[0]["text"]
                    prev_items[-1]["cross_page"] = True
                curr_items.pop(0)

            # 2b. 标准跨页规则
            if prev_items and curr_items:
                last_prev = prev_items[-1]
                first_curr = curr_items[0]
                last_text = last_prev.get("text", "")
                first_text = first_curr.get("marker", "") + " " + first_curr.get("text", "")
                if (not _HAS_END_PUNCTUATION.search(last_text)
                        and not _STARTS_WITH_NUMBER.match(first_text)):
                    last_prev["text"] += " " + first_curr.get("text", "")
                    last_prev["cross_page"] = True
                    curr_items.pop(0)

        # —— Pass 3：挂载到段落（行） ——
        for page_idx, bp in enumerate(body_page_nos):
            items = page_items[page_idx]
            if not items:
                continue

            md = page_markdown_text(_find_page_by_no(pages, bp))
            if not md:
                continue

            lines = _split_lines(md)
            band_start, band_end = _detect_footnote_band(lines)
            if band_start >= 0 and band_start < band_end:
                body_lines = lines[:band_start]
            else:
                body_lines = lines

            for item in items:
                marker = item["marker"]
                text = item["text"]
                cross_page = item.get("cross_page", False)

                if cross_page:
                    attachment_kind = "cross_page_tail"
                    para_idx = max(0, len(body_lines) - 1)
                else:
                    matched_idx = _scan_body_lines_for_marker(body_lines, marker)
                    if matched_idx is not None:
                        attachment_kind = "anchor_matched"
                        para_idx = matched_idx
                    else:
                        attachment_kind = "page_tail"
                        para_idx = max(0, len(body_lines) - 1)

                all_records.append(ParagraphFootnoteRecord(
                    doc_id=doc_id,
                    chapter_id=chapter_id,
                    page_no=bp,
                    paragraph_index=para_idx,
                    attachment_kind=attachment_kind,
                    source_marker=marker,
                    text=text,
                ))

        chapter_stats[chapter_id] = {
            "body_page_count": len(body_page_nos),
            "footnote_item_count": sum(len(items) for items in page_items),
            "cross_page_count": sum(
                1 for items in page_items for item in items if item.get("cross_page")
            ),
        }

    total_items = len(all_records)
    anchor_matched = sum(1 for r in all_records if r.attachment_kind == "anchor_matched")
    page_tail = sum(1 for r in all_records if r.attachment_kind == "page_tail")
    cross_tail = sum(1 for r in all_records if r.attachment_kind == "cross_page_tail")

    summary: dict[str, Any] = {
        "total_footnote_items": total_items,
        "anchor_matched": anchor_matched,
        "page_tail": page_tail,
        "cross_page_tail": cross_tail,
        "chapter_count": len(chapter_stats),
        "chapter_stats": chapter_stats,
    }
    return all_records, summary

"""
文本处理模块：段落构建引擎、跨页合并、脚注处理。

对外统一导出接口（兼容已有 import）：
- 从 ocr_parser 导出: parse_ocr, clean_header_footer
- 从 pdf_extract 导出: extract_pdf_text, combine_sources
- 从 text_utils 导出: strip_html, extract_heading_level, ends_mid, starts_low
- 本模块: parse_page_markdown, build_paragraphs, get_page_context_for_translate, ...
"""
import re

# Re-export: 兼容 `from text_processing import ...`
from text_utils import (  # noqa: F401
    strip_html, extract_heading_level,
    _is_meta_line, _is_metadata,
    ends_mid, starts_low,
)
from ocr_parser import parse_ocr, clean_header_footer  # noqa: F401
from pdf_extract import extract_pdf_text, extract_pdf_toc, combine_sources  # noqa: F401


# ============ 旧段落引擎（基于 blocks） ============

def build_paragraphs(pages: list, from_bp: int, to_bp: int) -> list:
    """构建段落，跨页合并。跳过元数据块。标题保持独立段落。

    每个段落包含:
        text, startBP, endBP, heading_level (0=正文, 1-6=标题)
    """
    units = []
    for pg in pages:
        if pg["bookPage"] < from_bp or pg["bookPage"] > to_bp:
            continue
        for bi, blk in enumerate(pg["blocks"]):
            txt = blk["text"].strip()
            if len(txt) < 3:
                continue
            if blk.get("is_meta"):
                continue

            hlevel = blk.get("heading_level", 0)

            if txt[-1] in "-\u2010":
                txt = txt[:-1]

            if hlevel > 0:
                units.append({
                    "text": txt,
                    "startBP": pg["bookPage"],
                    "endBP": pg["bookPage"],
                    "heading_level": hlevel,
                })
                continue

            is_short = len(txt) < 80

            merge = False
            if bi == 0 and units and units[-1]["heading_level"] == 0:
                if starts_low(txt):
                    merge = True
                elif ends_mid(units[-1]["text"]):
                    merge = True
                elif blk["x"] is not None and pg["indent"] is not None and blk["x"] < pg["indent"]:
                    merge = True

            if not merge and is_short and units and units[-1]["heading_level"] == 0:
                prev = units[-1]
                if prev["endBP"] == pg["bookPage"]:
                    merge = True

            if merge:
                u = units[-1]
                sep = "" if u["text"].endswith(" ") else " "
                u["text"] += sep + txt
                u["endBP"] = pg["bookPage"]
            else:
                units.append({
                    "text": txt,
                    "startBP": pg["bookPage"],
                    "endBP": pg["bookPage"],
                    "heading_level": 0,
                })

    return units


def fmt_pages(u: dict) -> str:
    if u["startBP"] == u["endBP"]:
        return str(u["startBP"])
    return f"{u['startBP']}-{u['endBP']}"


def find_para_at(pages: list, bp: int) -> dict | None:
    """定位包含指定页码的段落。"""
    units = build_paragraphs(pages, max(1, bp - 5), bp + 5)
    for u in units:
        if u["startBP"] <= bp <= u["endBP"]:
            return {"text": u["text"], "pages": fmt_pages(u), "startBP": u["startBP"], "endBP": u["endBP"], "all": units}
    for u in units:
        if u["startBP"] >= bp:
            return {"text": u["text"], "pages": fmt_pages(u), "startBP": u["startBP"], "endBP": u["endBP"], "all": units}
    return None


def find_next_paras(pages: list, end_bp: int, raw_text: str = "", count: int = 1) -> list:
    """查找后续段落。"""
    units = build_paragraphs(pages, max(1, end_bp - 3), end_bp + 20)
    if not units:
        return []

    def norm(s):
        return re.sub(r"\s+", " ", s).strip()

    rn = norm(raw_text or "")
    match_idx = -1

    for i, u in enumerate(units):
        un = norm(u["text"])
        if end_bp - 1 <= u["endBP"] <= end_bp + 1:
            tail = min(60, len(rn))
            if tail > 10 and rn[-tail:] in un:
                match_idx = i
                break
            head = min(60, len(rn))
            if head > 10 and rn[:head] in un:
                match_idx = i
                break

    if match_idx == -1:
        for j, u in enumerate(units):
            if u["endBP"] == end_bp:
                match_idx = j
                break
    if match_idx == -1:
        for k, u in enumerate(units):
            if u["startBP"] > end_bp:
                match_idx = k - 1
                break
    if match_idx == -1:
        match_idx = 0

    results = []
    for ri in range(match_idx + 1, len(units)):
        if len(results) >= count:
            break
        u = units[ri]
        results.append({"text": u["text"], "pages": fmt_pages(u), "startBP": u["startBP"], "endBP": u["endBP"]})
    return results


# ============ 脚注处理 ============

_LATEX_FOOTNOTE_MARK_RE = re.compile(r"\$\s*\^\{(\d+)\}\s*\$")
_PLAIN_FOOTNOTE_MARK_RE = re.compile(r"(?<![\w\[])\^\{(\d+)\}")


def normalize_latex_footnote_markers(text: str) -> str:
    """将 OCR 遗留的脚注标记（如 $ ^{12} $）标准化为 [12]。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    normalized = _LATEX_FOOTNOTE_MARK_RE.sub(r"[\1]", raw)
    normalized = _PLAIN_FOOTNOTE_MARK_RE.sub(r"[\1]", normalized)
    return normalized


# 非实质性脚注模式
_SKIP_FN_RE = [
    re.compile(r"Corresponding\s+author", re.I),
    re.compile(r"Email:\s*\S+@", re.I),
    re.compile(r"E-mail:\s*\S+@", re.I),
    re.compile(r"^\S+@\S+\.\S+$"),
    re.compile(r"^\d+,?\s+Sec\.", re.I),
    re.compile(r"University,?\s+\d+", re.I),
    re.compile(r"(Street|Road|Ave|Blvd|District),?\s", re.I),
    re.compile(r"(Taiwan|China|USA|UK|Japan|Korea)\s*\.?\s*$", re.I),
]


def _is_boilerplate_footnote(text: str) -> bool:
    """判断整段脚注是否为通讯作者/地址等样板内容。"""
    lines = text.strip().split("\n")
    nonempty_lines = [line.strip() for line in lines if line.strip()]
    if any(re.match(r"^\d+[\.\)]\s*", line) for line in nonempty_lines):
        return False
    match_count = 0
    for stripped in nonempty_lines:
        for pat in _SKIP_FN_RE:
            if pat.search(stripped):
                match_count += 1
                break
    total = len(nonempty_lines)
    return total > 0 and match_count >= total * 0.5


def _filter_footnote_lines(text: str) -> str:
    """过滤掉通讯作者、邮箱等非实质性脚注。"""
    text = normalize_latex_footnote_markers(text)
    if _is_boilerplate_footnote(text):
        return ""
    return text.strip()


def get_footnotes(pages: list, from_bp: int, to_bp: int) -> str:
    r = []
    for p in pages:
        if from_bp <= p["bookPage"] <= to_bp and p.get("footnotes"):
            filtered = _filter_footnote_lines(p["footnotes"])
            if filtered:
                r.append(filtered)
    return "\n".join(r)


def get_page_paragraphs(pages: list, bp: int) -> list[dict]:
    """
    获取指定页码的全部段落（以页面为单位，逐段返回）。
    如果段落跨页，把跨页段落完整包含。
    """
    paras = build_paragraphs(pages, max(1, bp - 2), bp + 2)

    relevant = []
    seen_keys = set()
    for p in paras:
        touches = (p["startBP"] <= bp <= p["endBP"]) or (p["startBP"] == bp)
        if touches:
            key = p["text"][:80]
            if key not in seen_keys:
                seen_keys.add(key)
                relevant.append(p)

    if not relevant:
        for pg in pages:
            if pg["bookPage"] == bp:
                for b in pg["blocks"]:
                    txt = b["text"].strip()
                    if len(txt) > 2 and not b.get("is_meta"):
                        relevant.append({
                            "text": txt,
                            "startBP": bp,
                            "endBP": bp,
                            "heading_level": b.get("heading_level", 0),
                        })
        if not relevant:
            return []

    relevant.sort(key=lambda p: (p["startBP"], p["endBP"]))

    result = []
    for p in relevant:
        fn = get_footnotes(pages, p["startBP"] - 1, p["endBP"] + 1)
        ps = fmt_pages(p)
        result.append({
            "text": p["text"],
            "startBP": p["startBP"],
            "endBP": p["endBP"],
            "heading_level": p.get("heading_level", 0),
            "footnotes": fn,
            "pages": ps,
        })

    return result


# ============ 新策略：基于 markdown 的页面解析 ============


def _find_page(pages: list, bp: int) -> dict | None:
    """按 bookPage 查找页面。"""
    for pg in pages:
        if pg["bookPage"] == bp:
            return pg
    return None


def parse_page_markdown(pages: list, bp: int) -> list[dict]:
    """
    逐行解析某页的 markdown 文本，返回段落结构。

    核心策略：
    - markdown 的 # 标记 → 标题（heading_level 1-6）
    - 连续非空行 → 一个正文段落（heading_level 0）
    - 空行 → 段落边界
    - 元数据行被过滤
    - 短碎片合并到相邻段落

    Returns:
        [{"heading_level": int, "text": str, "cross_page": str|None}, ...]
    """
    cur = _find_page(pages, bp)
    if not cur:
        return []

    md = cur.get("markdown", "").strip()
    if not md:
        return _fallback_blocks_to_paragraphs(cur, bp)

    # 获取前后页 markdown 用于跨页检测
    prev_pg = _find_page(pages, bp - 1)
    next_pg = _find_page(pages, bp + 1)
    prev_md = (prev_pg.get("markdown", "") if prev_pg else "").strip()
    next_md = (next_pg.get("markdown", "") if next_pg else "").strip()

    # ====== Step 1: 逐行分类 ======
    lines = md.split("\n")
    items = []

    for line in lines:
        stripped = normalize_latex_footnote_markers(line)
        if not stripped:
            items.append({"type": "blank", "level": 0, "text": ""})
            continue
        if _is_meta_line(stripped):
            continue

        hl, clean = extract_heading_level(stripped)
        if hl > 0:
            items.append({"type": "heading", "level": hl, "text": clean})
        else:
            items.append({"type": "text", "level": 0, "text": stripped})

    # ====== Step 2: 将连续 text 行合并为段落 ======
    segments = []
    buf = []

    def flush_buf():
        if buf:
            combined = " ".join(buf)
            if len(combined.strip()) > 1:
                segments.append({"heading_level": 0, "text": combined.strip()})
            buf.clear()

    for item in items:
        if item["type"] == "heading":
            flush_buf()
            segments.append({"heading_level": item["level"], "text": item["text"]})
        elif item["type"] == "text":
            buf.append(item["text"])
        elif item["type"] == "blank":
            flush_buf()

    flush_buf()

    if not segments:
        return _fallback_blocks_to_paragraphs(cur, bp)

    # ====== Step 3: 智能合并 ======
    _SENT_END_RE = re.compile(r"[.;!?。；！？»\"'\u201d\u00bb]\s*$")
    _ALLCAPS_TITLE_RE = re.compile(
        r"^[A-ZÀ-ÖØ-Þ\s\-,':«»\"\.!?()]+$"
    )

    def _is_ocr_line_break(prev_text: str, cur_text: str) -> bool:
        """判断两段之间是否为 OCR 行间断裂。"""
        pt = prev_text.rstrip()
        ct = cur_text.lstrip()
        if not pt or not ct:
            return False
        if pt.endswith("-"):
            return True
        if not _SENT_END_RE.search(pt) and ct[0].islower():
            return True
        if pt.endswith(","):
            return True
        return False

    def _looks_like_allcaps_title(txt: str) -> int:
        """检测全大写标题，返回 heading_level（0=不是标题）。"""
        clean = txt.strip()
        if len(clean) < 3 or len(clean) > 120:
            return 0
        if not _ALLCAPS_TITLE_RE.match(clean):
            return 0
        if re.search(r"[\u4e00-\u9fff\u3000-\u303f]", clean):
            return 0
        if re.match(r"^[\W\d\s]+$", clean):
            return 0
        letters = sum(1 for c in clean if c.isalpha())
        if letters / max(len(clean), 1) < 0.6:
            return 0
        words = [w for w in clean.split() if len(w) > 1 and w.isalpha()]
        if len(words) < 2:
            return 0
        if _SENT_END_RE.search(clean) and len(clean) > 60:
            return 0
        return 3

    merged = []
    for seg in segments:
        hl = seg["heading_level"]
        txt = seg["text"]

        if hl == 0:
            detected_hl = _looks_like_allcaps_title(txt)
            if detected_hl > 0:
                hl = detected_hl

        # --- 连续标题合并 ---
        if hl > 0 and merged and merged[-1]["heading_level"] > 0:
            prev_hl = merged[-1]["heading_level"]
            prev_txt = merged[-1]["text"]
            should_merge = False

            if prev_hl == hl and _ALLCAPS_TITLE_RE.match(prev_txt.strip()) and _ALLCAPS_TITLE_RE.match(txt.strip()):
                should_merge = True
            elif prev_hl == hl and re.match(r"^[IVXLC]+$", prev_txt.strip()):
                should_merge = True
            elif len(txt.strip()) <= 3:
                merged[-1]["text"] = prev_txt + " " + txt
                continue
            elif txt.strip()[0].islower():
                should_merge = True

            if should_merge:
                merged[-1]["text"] = prev_txt + " " + txt
                merged[-1]["heading_level"] = min(prev_hl, hl)
                continue

        # OCR 行间断裂合并
        if hl == 0 and merged and merged[-1]["heading_level"] == 0:
            prev_text = merged[-1]["text"]
            if _is_ocr_line_break(prev_text, txt):
                if prev_text.rstrip().endswith("-"):
                    merged[-1]["text"] = prev_text.rstrip()[:-1] + txt.lstrip()
                else:
                    merged[-1]["text"] = prev_text + " " + txt
                continue

        # 短碎片合并
        is_short = (hl == 0 and len(txt) < 60
                    and not _SENT_END_RE.search(txt.strip()))
        if hl == 0 and re.match(r"^\([^)]+\)$", txt.strip()):
            is_short = True

        if is_short and merged:
            prev = merged[-1]
            if prev["heading_level"] > 0:
                prev["_subtitle"] = prev.get("_subtitle", "") + "\n" + txt
            else:
                prev["text"] += " " + txt
        elif is_short and not merged:
            merged.append({"heading_level": 0, "text": txt})
        else:
            merged.append({"heading_level": hl, "text": txt})

    # ====== Step 4: 检测跨页并合并 ======
    result = []
    for i, seg in enumerate(merged):
        cross_page = None
        hl = seg["heading_level"]
        txt = seg["text"]

        if seg.get("_subtitle"):
            txt = txt + "\n" + seg["_subtitle"].strip()

        if i == 0 and hl == 0:
            if _is_continuation_from_prev(txt, prev_md):
                cross_page = "cont_prev"
        if i == len(merged) - 1 and hl == 0:
            if _is_continuation_to_next(txt, next_md):
                cross_page = "cont_both" if cross_page == "cont_prev" else "cont_next"

        result.append({
            "heading_level": hl,
            "text": txt,
            "cross_page": cross_page,
        })

    # ====== Step 5: 跨页段落处理 ======
    if result and result[0].get("cross_page") in ("cont_prev", "cont_both"):
        if len(result) > 1:
            result.pop(0)
        else:
            result[0]["cross_page"] = None

    if result and result[-1].get("cross_page") == "cont_next":
        chain_texts = []
        scan_pg = next_pg
        scan_md = next_md
        while scan_pg and scan_md:
            scan_paras = _parse_single_page_md(scan_pg, scan_md)
            if not scan_paras:
                break
            first_para = scan_paras[0]
            chain_texts.append(first_para["text"])
            if not ends_mid(first_para["text"]):
                break
            next_scan_bp = scan_pg["bookPage"] + 1
            scan_pg = _find_page(pages, next_scan_bp)
            scan_md = (scan_pg.get("markdown", "") if scan_pg else "").strip()
        if chain_texts:
            result[-1]["text"] = result[-1]["text"] + " " + " ".join(chain_texts)
            result[-1]["cross_page"] = "merged_next"

    return result


def _parse_single_page_md(pg: dict | None, md: str) -> list[dict]:
    """解析单页 markdown 为段落列表（不做跨页合并，避免递归）。"""
    if not pg or not md:
        return []

    lines = md.split("\n")
    items = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            items.append({"type": "blank", "level": 0, "text": ""})
            continue
        if _is_meta_line(stripped):
            continue
        hl, clean = extract_heading_level(stripped)
        if hl > 0:
            items.append({"type": "heading", "level": hl, "text": clean})
        else:
            items.append({"type": "text", "level": 0, "text": stripped})

    segments = []
    buf = []

    def flush():
        if buf:
            combined = " ".join(buf)
            if len(combined.strip()) > 1:
                segments.append({"heading_level": 0, "text": combined.strip()})
            buf.clear()

    for item in items:
        if item["type"] == "heading":
            flush()
            segments.append({"heading_level": item["level"], "text": item["text"]})
        elif item["type"] == "text":
            buf.append(item["text"])
        else:
            flush()
    flush()

    return segments


def _is_continuation_from_prev(text: str, prev_md: str) -> bool:
    """判断当前段落是否承接上一页。"""
    if not prev_md:
        return False
    if starts_low(text):
        return True
    prev_tail = prev_md.rstrip()
    if prev_tail and ends_mid(prev_tail):
        hl, _ = extract_heading_level(text)
        if hl == 0:
            return True
    return False


def _is_continuation_to_next(text: str, next_md: str) -> bool:
    """判断当前段落是否在页面末尾被截断。"""
    if not next_md:
        return False
    if ends_mid(text):
        next_head = next_md.lstrip()
        if starts_low(next_head):
            return True
        hl, _ = extract_heading_level(next_head.split("\n")[0])
        if hl == 0 and ends_mid(text):
            return True
    return False


def _fallback_blocks_to_paragraphs(pg: dict, bp: int) -> list[dict]:
    """当 markdown 不可用时，用 OCR blocks 回退。"""
    raw = []
    for b in pg.get("blocks", []):
        txt = normalize_latex_footnote_markers(b.get("text", ""))
        if len(txt) < 2:
            continue
        if b.get("is_meta"):
            continue

        hl = b.get("heading_level", 0)
        label = b.get("label", "text")

        if hl == 0 and label == "doc_title":
            hl = 1
        elif hl == 0 and label == "paragraph_title":
            hl = 2

        lines = txt.split("\n")
        clean_lines = [l for l in lines if l.strip() and not _is_meta_line(l.strip())]
        clean_text = " ".join(l.strip() for l in clean_lines).strip()
        if not clean_text:
            continue

        real_hl, clean_text = extract_heading_level(clean_text)
        if real_hl > 0:
            hl = real_hl

        raw.append({"heading_level": hl, "text": clean_text})

    merged = []
    for seg in raw:
        hl = seg["heading_level"]
        txt = seg["text"]
        is_short = (hl == 0 and len(txt) < 60
                    and not re.search(r"[.;!?。；！？]$", txt.strip()))
        if hl == 0 and re.match(r"^\([^)]+\)$", txt.strip()):
            is_short = True
        if is_short and merged:
            prev = merged[-1]
            if prev["heading_level"] > 0:
                prev["text"] += "\n" + txt
            else:
                prev["text"] += " " + txt
        else:
            merged.append({"heading_level": hl, "text": txt, "cross_page": None})

    return merged


def get_paragraph_bboxes(pages: list, bp: int, paragraphs: list) -> list:
    """将段落文本匹配回 OCR blocks 的 bbox 坐标。

    返回列表，每项为该段落对应的 bbox 列表 [[x1,y1,x2,y2], ...]。
    坐标基于 OCR 图像尺寸（imgW × imgH）。
    """
    pg = _find_page(pages, bp)
    if not pg:
        return [[] for _ in paragraphs]

    blocks = pg.get("blocks", [])
    if not blocks:
        return [[] for _ in paragraphs]

    # 预处理 block 文本 → 小写，去多余空白
    block_infos = []
    for blk in blocks:
        txt = blk.get("text", "").strip()
        bbox = blk.get("bbox")
        if txt and bbox and len(txt) >= 3 and not blk.get("is_meta"):
            block_infos.append({
                "norm": re.sub(r"\s+", " ", txt).lower(),
                "bbox": bbox,
                "used": False,
            })

    result = []
    for para in paragraphs:
        para_norm = re.sub(r"\s+", " ", para["text"]).lower()
        para_bboxes = []

        for bi in block_infos:
            if bi["used"]:
                continue
            # 用 block 文本的前 50 字符作为匹配键
            key = bi["norm"][:50]
            if len(key) < 5:
                continue
            if key in para_norm:
                para_bboxes.append(bi["bbox"])
                bi["used"] = True

        result.append(para_bboxes)

    return result


def get_page_context_for_translate(pages: list, bp: int) -> dict:
    """
    获取页面翻译所需的所有信息。

    Returns:
        {
            "paragraphs": [{"heading_level", "text", "cross_page"}, ...],
            "footnotes": str,
            "page_num": int,
            "prev_tail": str,
            "next_head": str,
        }
    """
    paragraphs = parse_page_markdown(pages, bp)

    cur = _find_page(pages, bp)
    fn = ""
    if cur:
        raw_fn = cur.get("footnotes", "") or ""
        # 清理控制字符污染（字体编码异常的 PDF 常见）
        ctrl_count = sum(1 for c in raw_fn if ord(c) < 0x20 and c not in '\n\r\t')
        if ctrl_count > len(raw_fn) * 0.3:
            raw_fn = ""
        fn = _filter_footnote_lines(raw_fn) if raw_fn else ""

    prev_pg = _find_page(pages, bp - 1)
    next_pg = _find_page(pages, bp + 1)
    prev_tail = ""
    next_head = ""
    if prev_pg and prev_pg.get("markdown"):
        prev_tail = prev_pg["markdown"].strip()[-300:]
    if next_pg and next_pg.get("markdown"):
        next_head = next_pg["markdown"].strip()[:300]

    return {
        "paragraphs": paragraphs,
        "footnotes": fn,
        "page_num": bp,
        "prev_tail": prev_tail,
        "next_head": next_head,
    }


# ============ 旧接口（保持兼容） ============

def get_page_text(pages: list, bp: int) -> dict | None:
    """兼容旧接口：获取页面全部文本（拼接版）。"""
    paras = parse_page_markdown(pages, bp)
    if not paras:
        return None

    text = "\n\n".join(p["text"] for p in paras)
    fn_text = ""
    cur = _find_page(pages, bp)
    if cur:
        fn_text = _filter_footnote_lines(cur.get("footnotes", "")) if cur.get("footnotes") else ""

    return {
        "text": text,
        "startBP": bp,
        "endBP": bp,
        "footnotes": fn_text,
        "pages": str(bp),
    }


def get_next_page_bp(pages: list, current_bp: int) -> int | None:
    """获取当前页之后的下一个有内容的页码。"""
    for pg in pages:
        if pg["bookPage"] > current_bp and (pg.get("markdown") or pg.get("blocks")):
            return pg["bookPage"]
    return None


def get_page_range(pages: list) -> tuple[int, int]:
    """返回 (first_page, last_page)。"""
    if not pages:
        return (1, 1)
    return (pages[0]["bookPage"], pages[-1]["bookPage"])

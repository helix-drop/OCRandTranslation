"""OCR 结果解析：PaddleOCR 数据解析、页码插值、插图页过滤、页眉页脚清理。"""
import math
import re

from text_utils import strip_html, extract_heading_level, _is_meta_line, _is_metadata


def _sanitize_text(text: str) -> str:
    """清理控制字符（\\x01 等），保留换行和空格。"""
    if not text:
        return text
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)


def parse_ocr(data) -> dict:
    """
    解析 PaddleOCR 返回的 layoutParsingResults 数据。

    Args:
        data: PaddleOCR API 返回的 result 字典，或 layoutParsingResults 列表，
              或旧格式的 pages/results 列表

    Returns:
        {"pages": [...], "log": [...]}
    """
    log = []
    raw = None

    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        if "layoutParsingResults" in data:
            raw = data["layoutParsingResults"]
        elif "pages" in data and isinstance(data["pages"], list):
            raw = data["pages"]
        elif "results" in data and isinstance(data["results"], list):
            raw = data["results"]

    if raw is None:
        return {"pages": [], "log": ["ERROR: 无法识别数据结构"]}

    log.append(f"{len(raw)} pages in file")

    all_pages = []
    for pi, pg in enumerate(raw):
        pr = pg.get("prunedResult", pg) if isinstance(pg, dict) else pg
        blocks_list = None
        if isinstance(pr, dict) and isinstance(pr.get("parsing_res_list"), list):
            blocks_list = pr["parsing_res_list"]
        elif isinstance(pg, dict) and isinstance(pg.get("parsing_res_list"), list):
            blocks_list = pg["parsing_res_list"]

        img_w = pr.get("width", 767) if isinstance(pr, dict) else 767
        img_h = pr.get("height", 1274) if isinstance(pr, dict) else 1274

        detected_page = None
        text_blocks = []
        fn_blocks = []
        footnotes = []

        if blocks_list and len(blocks_list) > 0:
            sorted_blocks = sorted(blocks_list, key=lambda b: (b.get("block_bbox", [0, 0])[1] if b.get("block_bbox") else 0))
            for b in sorted_blocks:
                label = (b.get("block_label", "") or "").lower()
                raw_content = _sanitize_text(strip_html(b.get("block_content", "") or "")).strip()
                heading_level, content = extract_heading_level(raw_content)
                bbox = b.get("block_bbox")

                # 根据 OCR label 确定标题层级
                if label == "doc_title" and heading_level == 0:
                    heading_level = 1
                elif label == "paragraph_title" and heading_level == 0:
                    heading_level = 2

                if label == "number":
                    m = re.match(r"^(\d{1,4})$", content or "")
                    if m:
                        detected_page = int(m.group(1))
                elif label in ("header", "header_image", "footer", "footer_image", "aside_text"):
                    pass  # skip
                elif label == "footnote":
                    fn_text = _sanitize_text(content or "")
                    footnotes.append(fn_text)
                    if bbox:
                        fn_blocks.append({"text": fn_text, "x": bbox[0], "bbox": bbox, "label": "footnote"})
                else:
                    is_meta = _is_metadata(content)
                    text_blocks.append({
                        "text": content or "",
                        "x": bbox[0] if bbox else None,
                        "bbox": bbox,
                        "label": label or "text",
                        "is_meta": is_meta,
                        "heading_level": heading_level,
                    })
        else:
            # Fallback: use markdown text
            md = ""
            if isinstance(pg, dict) and isinstance(pg.get("markdown"), dict):
                md = pg["markdown"].get("text", "")
            if md:
                parts = re.split(r"\n\n+", md)
                for mp in parts:
                    mp = mp.strip()
                    if len(mp) > 5:
                        text_blocks.append({"text": strip_html(mp), "x": None, "bbox": None, "label": "text"})

        # 提取 markdown 连续文本
        raw_markdown = ""
        if isinstance(pg, dict):
            md_field = pg.get("markdown")
            if isinstance(md_field, dict):
                raw_markdown = md_field.get("text", "")
            elif isinstance(md_field, str):
                raw_markdown = md_field

        all_pages.append({
            "fileIdx": pi,
            "bookPage": pi + 1,
            "pdfPage": pi + 1,
            "printPage": None,
            "printPageLabel": "",
            "detectedPage": detected_page,
            "imgW": img_w,
            "imgH": img_h,
            "blocks": text_blocks,
            "fnBlocks": fn_blocks,
            "footnotes": "\n".join(footnotes),
            "indent": None,
            "textSource": "ocr",
            "markdown": raw_markdown,
        })

    # Compute indent per page
    for p in all_pages:
        if len(p["blocks"]) <= 1:
            continue
        xs = [b["x"] for b in p["blocks"] if b["x"] is not None]
        if xs:
            xs.sort()
            p["indent"] = xs[0] + 10

    # 推断原书印刷页码（仅作为显示/引用辅助，不参与导航）
    anchors = []
    for ai, p in enumerate(all_pages):
        if p["detectedPage"] is not None and p["detectedPage"] > 0:
            anchors.append({"idx": ai, "bp": p["detectedPage"]})

    log.append(f"{len(anchors)}/{len(all_pages)} pages have detected numbers")

    if len(anchors) >= 2:
        # Filter non-increasing
        cl = [anchors[0]]
        for ci in range(1, len(anchors)):
            if anchors[ci]["bp"] >= cl[-1]["bp"]:
                cl.append(anchors[ci])
            else:
                log.append(f"WARN: 非递增 idx={anchors[ci]['idx']} bp={anchors[ci]['bp']}")
        anchors = cl

        # Interpolate between anchors
        for si in range(len(anchors) - 1):
            a1, a2 = anchors[si], anchors[si + 1]
            idx_span = a2["idx"] - a1["idx"]
            bp_span = a2["bp"] - a1["bp"]
            for fi in range(a1["idx"], a2["idx"] + 1):
                inferred = round(a1["bp"] + (fi - a1["idx"]) / idx_span * bp_span)
                if inferred > 0:
                    all_pages[fi]["printPage"] = inferred

        # 不再对前后封面/空白页强行外推印刷页码，避免制造错误数字。

    elif len(anchors) == 1:
        all_pages[anchors[0]["idx"]]["printPage"] = anchors[0]["bp"]
    else:
        log.append("WARN: 未检测到可靠原书页码，仅保留 PDF 实页导航")

    # OCR 直接识别到的页码优先
    for p in all_pages:
        if p["detectedPage"] is not None and p["detectedPage"] > 0:
            p["printPage"] = p["detectedPage"]

    for p in all_pages:
        if p.get("printPage"):
            p["printPageLabel"] = str(p["printPage"])
            p["printPageDisplay"] = f"原书 p.{p['printPageLabel']}"
        else:
            p["printPageLabel"] = ""
            p["printPageDisplay"] = ""
        p["isFigurePage"] = _is_figure_page(p)

    if all_pages:
        log.append(f"PDF Range: 第1页-第{len(all_pages)}页 ({len(all_pages)}页)")

    return {"pages": all_pages, "log": log}


# ============ 插图页检测 ============

_IMAGE_LABELS = {"image", "figure_title", "vision_footnote"}


def _is_figure_page(p):
    blocks = p.get("blocks", [])
    fn_blocks = p.get("fnBlocks", [])
    all_blocks = blocks + fn_blocks
    md = p.get("markdown", "")
    meaningful_text_blocks = [
        b for b in all_blocks
        if (b.get("label", "") in ("text", "paragraph_title", "doc_title") and len((b.get("text", "") or "").strip()) >= 20)
        or int(b.get("heading_level", 0) or 0) > 0
    ]

    if meaningful_text_blocks:
        return False

    # markdown 含 <img> 标签 → 插图页
    if "<img" in md:
        return True

    if not all_blocks:
        plain = re.sub(r"<[^>]+>", "", md).strip()
        return len(plain) < 50

    # 统计各类 block
    text_blocks = [b for b in all_blocks if b.get("label", "") in ("text", "paragraph_title", "doc_title")]
    img_blocks = [b for b in all_blocks if b.get("label", "") in _IMAGE_LABELS]

    # 无正文 block，全是图片/图注
    if not text_blocks and img_blocks:
        return True
    # 有图片 block，且 text block 都是短图注（每个<500字）
    if img_blocks and text_blocks:
        long_text = [b for b in text_blocks if len(b.get("text", "")) > 120]
        if not long_text:
            return True

    # 垃圾 OCR 检测
    plain = re.sub(r"<[^>]+>", "", md).strip()
    if len(plain) < 50:
        return True
    digit_chars = sum(1 for c in plain if c.isdigit())
    if len(plain) > 0 and digit_chars / len(plain) > 0.3:
        return True

    return False


# ============ 页眉页脚清理 ============

def clean_header_footer(pages: list) -> dict:
    """
    检测并移除页眉页脚。

    策略：
    1) Y坐标区域: 页面顶部12%和底部8%为页眉/页脚区
    2) 统计频率: 在这些区域出现的短文本(<120字)，如果在>25%的页面中重复出现 → 页眉/页脚
    3) 固定模式: 纯数字、数字+文字
    4) 移除匹配的区块
    """
    if len(pages) < 3:
        return {"pages": pages, "log": ["页数太少，跳过页眉页脚检测"]}

    log = []
    removed = 0
    HF_TOP_RATIO = 0.12
    HF_BOT_RATIO = 0.08

    # Collect candidate texts from header/footer zones
    top_texts = {}
    bot_texts = {}
    for pg in pages:
        h = pg["imgH"]
        top_y = h * HF_TOP_RATIO
        bot_y = h * (1 - HF_BOT_RATIO)
        for blk in pg["blocks"]:
            if not blk.get("bbox") or len(blk["text"]) > 120:
                continue
            by1 = blk["bbox"][1]
            by2 = blk["bbox"][3]
            mid_y = (by1 + by2) / 2
            norm = re.sub(r"\s+", " ", blk["text"]).strip().lower()
            if len(norm) < 2:
                continue
            if mid_y < top_y:
                top_texts[norm] = top_texts.get(norm, 0) + 1
            if mid_y > bot_y:
                bot_texts[norm] = bot_texts.get(norm, 0) + 1

    # Find recurring patterns (appear in >25% of pages)
    threshold = max(3, math.floor(len(pages) * 0.25))
    hf_patterns = {}
    for t, count in top_texts.items():
        if count >= threshold:
            hf_patterns[t] = "header"
    for t, count in bot_texts.items():
        if count >= threshold and t not in hf_patterns:
            hf_patterns[t] = "footer"

    # Common header/footer patterns
    FIXED_RE = [
        re.compile(r"^\d{1,4}$"),
        re.compile(r"^\d{1,4}\s+\w", re.I),
        re.compile(r"\w.*\d{1,4}$", re.I),
    ]

    if hf_patterns:
        log.append(f"检测到{len(hf_patterns)}种重复页眉/页脚模式")

    # Remove matching blocks
    for pg in pages:
        h = pg["imgH"]
        top_y = h * HF_TOP_RATIO
        bot_y = h * (1 - HF_BOT_RATIO)
        kept = []
        for blk in pg["blocks"]:
            should_remove = False
            if blk.get("bbox") and len(blk["text"]) <= 120:
                mid_y = (blk["bbox"][1] + blk["bbox"][3]) / 2
                in_hf_zone = mid_y < top_y or mid_y > bot_y
                if in_hf_zone:
                    norm = re.sub(r"\s+", " ", blk["text"]).strip().lower()
                    if norm in hf_patterns:
                        should_remove = True
                    if not should_remove:
                        for pattern in FIXED_RE:
                            if pattern.search(norm):
                                should_remove = True
                                break
                    if not should_remove and len(norm) < 50 and not re.search(r"[.;:?!]$", norm):
                        should_remove = True
            if should_remove:
                removed += 1
            else:
                kept.append(blk)
        pg["blocks"] = kept

    pages = [p for p in pages if p["blocks"] or p["fnBlocks"]]
    log.append(f"移除了{removed}个页眉/页脚区块")
    return {"pages": pages, "log": log}

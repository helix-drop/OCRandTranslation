"""PDF 文字层提取与 OCR 布局合并、按页渲染。"""
import io
import re
import unicodedata
from functools import lru_cache

from pypdf import PdfReader


def extract_pdf_text(file_bytes: bytes) -> list[dict]:
    """
    从PDF文件提取文字层信息。

    Returns:
        列表，每项 {"pageIdx": int, "pdfW": float, "pdfH": float,
                     "items": [{"str","x","y","w","h"}], "fullText": str}
        如果PDF无有效文字层，返回空列表。
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception:
        return []
    pdf_pages = []
    usable_chars = 0

    for i, page in enumerate(reader.pages):
        try:
            mediabox = page.mediabox
            pdf_w = float(mediabox.width)
            pdf_h = float(mediabox.height)
        except Exception:
            pdf_w = 0.0
            pdf_h = 0.0

        # pypdf extract_text for quick check
        try:
            raw_text = (page.extract_text() or "").strip()
        except Exception:
            raw_text = ""

        # Use visitor to get positioned text items
        items = []

        def visitor(text, cm, tm, font_dict, font_size):
            if not text or not text.strip():
                return
            x = tm[4]
            y_from_bottom = tm[5]
            y = pdf_h - y_from_bottom
            h = font_size if font_size else 12
            w = len(text) * h * 0.5  # approximate width
            items.append({
                "str": text,
                "x": x,
                "y": y,
                "w": w,
                "h": abs(h),
            })

        if raw_text:
            try:
                page.extract_text(visitor_text=visitor)
            except Exception:
                items = []

        full_text = " ".join(it["str"] for it in items).strip()
        full_text = re.sub(r"\s+", " ", full_text)
        page_sample = (full_text or raw_text or "")[:2000]
        if page_sample and not _is_pdf_text_layer_readable(page_sample):
            items = []
            full_text = ""
        if items and full_text:
            usable_chars += len(full_text)

        pdf_pages.append({
            "pageIdx": i,
            "pdfW": pdf_w,
            "pdfH": pdf_h,
            "items": items,
            "fullText": full_text,
        })

    # 只要最终没有留下任何可用文字层，就整体回退到 OCR
    if usable_chars < 20:
        return []

    return pdf_pages


def extract_pdf_toc(file_bytes: bytes) -> list[dict]:
    """提取 PDF 目录（书签）为扁平结构。"""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception:
        return []

    try:
        outline = reader.outline
    except Exception:
        return []
    if not outline:
        return []

    items = []

    def _resolve_page_idx(node) -> int | None:
        try:
            page_idx = reader.get_destination_page_number(node)
            if isinstance(page_idx, int) and page_idx >= 0:
                return page_idx
        except Exception:
            return None
        return None

    def _node_title(node) -> str:
        title = getattr(node, "title", "") or ""
        title = str(title).strip()
        return re.sub(r"\s+", " ", title)

    def _walk(nodes, depth: int):
        for node in nodes:
            if isinstance(node, list):
                _walk(node, depth + 1)
                continue
            title = _node_title(node)
            if not title:
                continue
            page_idx = _resolve_page_idx(node)
            if page_idx is None:
                continue
            items.append(
                {
                    "title": title,
                    "depth": max(0, depth),
                    "file_idx": int(page_idx),
                }
            )

    if isinstance(outline, list):
        _walk(outline, 0)
    else:
        _walk([outline], 0)
    return items


def _is_corrupted(text: str) -> bool:
    """检测文本是否被 \\x01 等控制字符污染（字体编码异常的 PDF 常见）。"""
    if not text:
        return False
    ctrl_count = sum(1 for c in text if ord(c) < 0x20 and c not in '\n\r\t')
    return ctrl_count > len(text) * 0.3


def _is_pdf_text_layer_readable(sample_text: str) -> bool:
    """对文字层做最小抽样判断，识别明显乱码或不可读文本。"""
    if not sample_text:
        return False

    sample = re.sub(r"\s+", " ", sample_text).strip()
    if not sample:
        return False
    if "\ufffd" in sample:
        return False
    if _is_corrupted(sample):
        return False

    total = len(sample)
    readable = 0
    weird = 0
    for ch in sample:
        cat = unicodedata.category(ch)
        if ch.isalnum() or cat.startswith("L") or cat.startswith("N"):
            readable += 1
            continue
        if cat.startswith("P") or cat.startswith("Z"):
            readable += 1
            continue
        if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf":
            readable += 1
            continue
        if cat in ("Cc", "Cf", "Co", "Cs", "So", "Sk"):
            weird += 1

    if total >= 20 and readable / total < 0.55:
        return False
    if total >= 20 and weird / total > 0.2:
        return False

    tokens = re.findall(r"[^\W\d_]{2,}", sample, flags=re.UNICODE)
    if total >= 60 and not tokens:
        return False

    return True


def combine_sources(layout_pages: list, pdf_pages: list) -> dict:
    """
    将PDF文字层映射到OCR布局块上。
    PDF文字为主，OCR仅提供布局结构。

    每个PDF文字项只分配给一个布局块（防止重复）。
    Returns:
        {"pages": layout_pages (已更新text), "log": [...]}
    """
    log = []
    matched = 0
    total = 0

    for lp in layout_pages:
        file_idx = lp["fileIdx"]
        if file_idx >= len(pdf_pages):
            continue
        pp = pdf_pages[file_idx]
        if not pp["items"]:
            continue

        sx = pp["pdfW"] / lp["imgW"] if lp["imgW"] else 1
        sy = pp["pdfH"] / lp["imgH"] if lp["imgH"] else 1

        used = [False] * len(pp["items"])
        all_blocks = lp["blocks"] + (lp.get("fnBlocks") or [])

        # Sort blocks by Y position (top to bottom)
        block_order = sorted(
            range(len(all_blocks)),
            key=lambda bi: all_blocks[bi]["bbox"][1] if all_blocks[bi].get("bbox") else 0,
        )

        for boi in block_order:
            blk = all_blocks[boi]
            total += 1
            if not blk.get("bbox"):
                continue

            PAD = 3
            bx1 = blk["bbox"][0] * sx - PAD
            by1 = blk["bbox"][1] * sy - PAD
            bx2 = blk["bbox"][2] * sx + PAD
            by2 = blk["bbox"][3] * sy + PAD

            # Collect unused items within this bbox
            hits = []
            for pi2, it in enumerate(pp["items"]):
                if used[pi2]:
                    continue
                if bx1 <= it["x"] <= bx2 and by1 <= it["y"] <= by2:
                    hits.append({"item": it, "idx": pi2})

            if not hits:
                continue

            # Mark as used
            for h in hits:
                used[h["idx"]] = True

            # Sort by Y then X
            hits.sort(key=lambda h: (h["item"]["y"], h["item"]["x"]))

            # Group into lines
            lines = []
            cur_line = [hits[0]["item"]]
            cur_y = hits[0]["item"]["y"]
            for hi in range(1, len(hits)):
                if abs(hits[hi]["item"]["y"] - cur_y) < 4:
                    cur_line.append(hits[hi]["item"])
                else:
                    lines.append(cur_line)
                    cur_line = [hits[hi]["item"]]
                    cur_y = hits[hi]["item"]["y"]
            lines.append(cur_line)

            # Build text per line
            line_texts = []
            for line_items in lines:
                line_items.sort(key=lambda it: it["x"])
                ls = ""
                for lii, li_item in enumerate(line_items):
                    if lii > 0 and li_item["x"] - (line_items[lii - 1]["x"] + line_items[lii - 1]["w"]) > 2:
                        ls += " "
                    ls += li_item["str"]
                line_texts.append(ls.strip())

            # Join lines with dehyphenation
            result = ""
            for ri, lt in enumerate(line_texts):
                if ri > 0:
                    if result and result[-1] in "-\u2010":
                        result = result[:-1]
                    else:
                        result += " "
                result += lt

            cl = re.sub(r"\s+", " ", result).strip()
            if cl and not _is_corrupted(cl):
                blk["text"] = cl
                blk["textSource"] = "pdf"
                matched += 1

        # Rebuild footnotes from fnBlocks (跳过被污染的文本)
        fn_blocks = lp.get("fnBlocks") or []
        if fn_blocks:
            fn_texts = [fb["text"] for fb in fn_blocks
                        if fb.get("text") and not _is_corrupted(fb["text"])]
            if fn_texts:
                lp["footnotes"] = "\n".join(fn_texts)

        lp["textSource"] = "pdf"

    log.append(f"PDF文字匹配: {matched}/{total} blocks")
    return {"pages": layout_pages, "log": log}


# ============ PDF 按页渲染 ============

@lru_cache(maxsize=64)
def render_pdf_page(pdf_path: str, file_idx: int, scale: float = 2.0) -> bytes:
    """渲染 PDF 指定页为 PNG 图片。

    Args:
        pdf_path: PDF 文件路径
        file_idx: 页面索引（从 0 开始）
        scale: 缩放比例（2.0 ≈ 144 DPI）

    Returns:
        PNG 图片的 bytes
    """
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    try:
        if file_idx < 0 or file_idx >= len(doc):
            raise ValueError(f"页码 {file_idx} 超出范围 (0-{len(doc)-1})")
        page = doc[file_idx]
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        return pix.tobytes("png")
    finally:
        doc.close()


def extract_single_page_pdf(source_pdf_path: str, file_idx: int) -> bytes | None:
    """从源PDF中提取单页，返回单页PDF的bytes。

    Args:
        source_pdf_path: 源PDF路径
        file_idx: 页面索引（从0开始）

    Returns:
        单页PDF的bytes，失败返回None
    """
    import fitz

    try:
        doc = fitz.open(source_pdf_path)
        try:
            if file_idx < 0 or file_idx >= len(doc):
                return None
            # 创建新文档，插入指定页
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=file_idx, to_page=file_idx)
            out = io.BytesIO()
            new_doc.save(out)
            new_doc.close()
            return out.getvalue()
        finally:
            doc.close()
    except Exception:
        return None

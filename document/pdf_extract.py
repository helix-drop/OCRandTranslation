"""PDF 文字层提取与 OCR 布局合并、按页渲染。"""
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache

from pypdf import PdfReader


def _xlsx_col_to_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in str(cell_ref or "") if ch.isalpha()).upper()
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - 64)
    return max(0, value - 1)


def _load_xlsx_rows_without_openpyxl(raw: bytes) -> list[list[str]]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
        "docrel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("main:si", ns):
                parts = [node.text or "" for node in si.findall(".//main:t", ns)]
                shared_strings.append("".join(parts))

        sheet_path = "xl/worksheets/sheet1.xml"
        try:
            workbook_xml = ET.fromstring(zf.read("xl/workbook.xml"))
            sheet = workbook_xml.find("main:sheets/main:sheet", ns)
            rel_id = sheet.attrib.get(f"{{{ns['docrel']}}}id", "") if sheet is not None else ""
            if rel_id and "xl/_rels/workbook.xml.rels" in zf.namelist():
                rels_xml = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
                for rel in rels_xml.findall("rel:Relationship", ns):
                    if rel.attrib.get("Id") == rel_id:
                        target = str(rel.attrib.get("Target", "")).lstrip("/")
                        if target:
                            sheet_path = f"xl/{target}" if not target.startswith("xl/") else target
                        break
        except Exception:
            pass

        root = ET.fromstring(zf.read(sheet_path))
        rows: list[list[str]] = []
        for row in root.findall(".//main:sheetData/main:row", ns):
            cells: dict[int, str] = {}
            max_idx = -1
            for cell in row.findall("main:c", ns):
                idx = _xlsx_col_to_index(cell.attrib.get("r", ""))
                max_idx = max(max_idx, idx)
                cell_type = cell.attrib.get("t", "")
                value = ""
                if cell_type == "inlineStr":
                    parts = [node.text or "" for node in cell.findall(".//main:t", ns)]
                    value = "".join(parts)
                else:
                    raw_value = (cell.findtext("main:v", "", ns) or "").strip()
                    if cell_type == "s":
                        try:
                            value = shared_strings[int(raw_value)]
                        except Exception:
                            value = ""
                    else:
                        value = raw_value
                cells[idx] = value
            if max_idx < 0:
                continue
            rows.append([cells.get(i, "") for i in range(max_idx + 1)])
        return rows


def parse_toc_file(file_storage) -> list[dict]:
    """解析用户上传的 xlsx/csv 目录文件，返回 [{title, depth, book_page}] 列表。

    格式：第一列标题，第二列深度（整数，0=章 1=节 2=小节），第三列原书印刷页码（整数）。
    首行含表头关键字时自动跳过，空行自动忽略。
    """
    filename = (file_storage.filename or "").lower()
    raw = file_storage.read()

    if filename.endswith(".csv"):
        import csv
        text = raw.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
    elif filename.endswith((".xlsx", ".xls")):
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            ws = wb.active
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append([str(c) if c is not None else "" for c in row])
            wb.close()
        except ModuleNotFoundError:
            if filename.endswith(".xls"):
                raise ValueError("缺少 xls 解析依赖，请安装 openpyxl 后重试")
            rows = _load_xlsx_rows_without_openpyxl(raw)
    else:
        raise ValueError("仅支持 .csv / .xlsx 格式")

    result: list[dict] = []
    for i, row in enumerate(rows):
        if len(row) < 3:
            continue
        title = str(row[0] or "").strip()
        raw_depth = str(row[1] or "").strip()
        raw_page = str(row[2] or "").strip()
        if not title or not raw_page:
            continue
        # 跳过表头行
        if i == 0:
            combined = (title + raw_depth + raw_page).lower()
            header_hints = ("title", "标题", "depth", "深度", "level", "层级", "page", "页码")
            if any(h in combined for h in header_hints):
                continue
        try:
            depth = max(0, int(raw_depth))
        except (ValueError, TypeError):
            depth = 0
        try:
            book_page = int(str(raw_page).split(".")[0])  # 兼容 "15.0" 格式
        except (ValueError, TypeError):
            continue
        if book_page <= 0:
            continue
        result.append({"title": title, "depth": depth, "book_page": book_page})
    return result


def write_user_toc_csv_bytes(items: list[dict]) -> bytes:
    """将 [{title, depth, book_page}, ...] 写成 UTF-8 BOM CSV 字节，供 toc_source.csv 使用。"""
    import csv

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["标题", "深度", "原书页码"])
    for it in items or []:
        try:
            depth = max(0, int(it.get("depth") or 0))
        except (TypeError, ValueError):
            depth = 0
        try:
            bp = max(1, int(it.get("book_page") or 1))
        except (TypeError, ValueError):
            bp = 1
        writer.writerow([str(it.get("title") or "").strip(), depth, bp])
    return buf.getvalue().encode("utf-8-sig")


def _normalize_pdf_font_name(font_dict) -> str:
    if not hasattr(font_dict, "get"):
        return ""
    raw_name = str(font_dict.get("/BaseFont") or font_dict.get("BaseFont") or "").strip()
    if raw_name.startswith("/"):
        raw_name = raw_name[1:]
    if "+" in raw_name:
        _subset_prefix, suffix = raw_name.split("+", 1)
        if suffix:
            raw_name = suffix
    return raw_name


def _font_weight_hint_from_name(font_name: str) -> str:
    lowered = str(font_name or "").strip().lower()
    if not lowered:
        return "unknown"
    heavy_hints = ("black", "heavy", "ultra", "extrabold", "extra-bold")
    bold_hints = ("bold", "demi", "semibold", "semi-bold", "medium")
    if any(token in lowered for token in heavy_hints):
        return "heavy"
    if any(token in lowered for token in bold_hints):
        return "bold"
    return "regular"


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
                "font_name": _normalize_pdf_font_name(font_dict),
                "font_weight_hint": _font_weight_hint_from_name(_normalize_pdf_font_name(font_dict)),
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


def extract_pdf_toc_from_links(file_bytes: bytes) -> list[dict]:
    """从 PDF 页面内嵌超链接提取目录结构（适用于无书签但目录页有内部链接的 PDF）。

    策略：
    1. 只扫描文档前 30% 的页面（目录通常在书首）
    2. 找出其中内部链接最多的连续区段（目录页）
    3. 链接目标页码须单调递增（区别于索引页的散乱跳转）
    4. 提取链接行的完整文本作为标题

    Returns:
        [{title, depth, file_idx}] 列表，depth 按文字缩进推断（0/1）。
    """
    try:
        import fitz
    except ImportError:
        return []

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return []

    try:
        total_pages = len(doc)
        # 只考虑前 30% 的页面，至多前 60 页
        scan_limit = min(total_pages, max(20, int(total_pages * 0.3)))

        # 统计前段各页的内部链接
        page_data = []
        for i in range(scan_limit):
            try:
                links = [lnk for lnk in doc[i].get_links() if lnk.get("kind") == 1]
            except Exception:
                links = []
            page_data.append((i, links))

        max_links = max((len(links) for _, links in page_data), default=0)
        if max_links < 3:
            return []

        # 选取链接数 >= 50% 最大值的页面作为目录候选
        threshold = max(3, max_links * 0.5)
        toc_page_indices = [i for i, links in page_data if len(links) >= threshold]
        if not toc_page_indices:
            return []

        items = []
        seen_targets = set()

        for page_idx in toc_page_indices:
            page = doc[page_idx]
            links = [lnk for lnk in page.get_links() if lnk.get("kind") == 1]
            if not links:
                continue

            # 按 Y 坐标排序，检查目标页码是否单调递增（目录特征）
            links_sorted = sorted(links, key=lambda lnk: lnk["from"].y0)
            targets = [lnk.get("page", -1) for lnk in links_sorted if lnk.get("page", -1) >= 0]
            if len(targets) < 3:
                continue
            # 至少 60% 的相邻对满足递增（允许索引中的重复/回跳）
            increasing = sum(1 for a, b in zip(targets, targets[1:]) if b >= a)
            if increasing / max(1, len(targets) - 1) < 0.6:
                continue  # 不像目录页，跳过

            # 计算页面最左侧链接的 x 坐标，用于推断缩进层级
            min_x = min(lnk["from"].x0 for lnk in links)
            indent_threshold = min_x + 15  # 超过此值视为子标题

            page_h = page.rect.height

            for lnk in links_sorted:
                target_page = lnk.get("page")
                if target_page is None or target_page < 0:
                    continue
                if target_page in seen_targets:
                    continue

                rect = lnk["from"]
                # 提取同一行文字：从页面左边到右边，同 Y 范围
                line_clip = fitz.Rect(0, rect.y0 - 2, page.rect.width, rect.y1 + 2)
                text = page.get_text("text", clip=line_clip).strip()
                text = re.sub(r"\s+", " ", text).strip()

                # 过滤空文本或纯数字
                if not text or re.match(r"^\d+$", text):
                    continue

                # 去掉末尾页码（如 "Introduction 11" → "Introduction"）
                text = re.sub(r"\s+\d+\s*$", "", text).strip()
                if not text:
                    continue

                depth = 1 if rect.x0 > indent_threshold else 0
                items.append({
                    "title": text,
                    "depth": depth,
                    "file_idx": int(target_page),
                })
                seen_targets.add(target_page)

        # 按目标页码升序排列
        items.sort(key=lambda x: x["file_idx"])
        return items
    finally:
        doc.close()


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


def extract_pdf_page_link_targets(pdf_path: str, file_idx: int) -> list[dict]:
    """提取指定 PDF 页中的内部链接目标，按视觉顺序返回。"""
    import fitz

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return []
    try:
        if file_idx < 0 or file_idx >= len(doc):
            return []
        page = doc[file_idx]
        raw_links = []
        for link in page.get_links():
            if link.get("kind") != 1:
                continue
            target = link.get("page")
            if target is None or int(target) < 0:
                continue
            rect = link.get("from")
            if rect is None:
                continue
            raw_links.append({
                "target_file_idx": int(target),
                "x0": float(rect.x0),
                "y0": float(rect.y0),
                "x1": float(rect.x1),
                "y1": float(rect.y1),
            })
        raw_links.sort(key=lambda item: (round(item["y0"], 1), item["x0"]))
        return [
            {
                "visual_order": index + 1,
                "target_file_idx": item["target_file_idx"],
                "bbox": [item["x0"], item["y0"], item["x1"], item["y1"]],
            }
            for index, item in enumerate(raw_links)
        ]
    finally:
        doc.close()


def read_pdf_page_labels(pdf_path: str) -> list[str]:
    """读取 PDF 页标签，返回与 file_idx 对齐的标签数组。"""
    try:
        reader = PdfReader(pdf_path)
        labels = list(getattr(reader, "page_labels", []) or [])
    except Exception:
        return []
    return [str(label or "").strip() for label in labels]

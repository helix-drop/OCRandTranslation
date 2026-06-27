#!/usr/bin/env python3
"""Prototype classifier for footnotes vs endnotes from PaddleOCR-VL JSON."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SUPERSCRIPT_TO_ASCII = str.maketrans(
    {
        "0": "0",
        "1": "1",
        "2": "2",
        "3": "3",
        "4": "4",
        "5": "5",
        "6": "6",
        "7": "7",
        "8": "8",
        "9": "9",
        "⁰": "0",
        "¹": "1",
        "²": "2",
        "³": "3",
        "⁴": "4",
        "⁵": "5",
        "⁶": "6",
        "⁷": "7",
        "⁸": "8",
        "⁹": "9",
    }
)

NOTES_HEADING_RE = re.compile(
    r"^\s*#{0,6}\s*(notes?|endnotes?|tail\s*notes?|尾注|注释|注解)\s*$",
    re.IGNORECASE,
)
MATH_REF_RE = re.compile(r"\$\s*\^\{([^}]+)\}\s*\$")
MD_REF_RE = re.compile(r"\[\^([^\]]+)\]")
BRACKET_NUM_REF_RE = re.compile(r"\[(\d{1,3})\]")
SUPERSCRIPT_REF_RE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
PLAIN_DIGIT_REF_RE = re.compile(
    r"(?<=[A-Za-zÀ-ÿ\]\)»”’])(\d{1,3})(?=[\s\]\)\.,;:!?»”’]|$)"
)
SPLIT_DIGIT_REF_RE = re.compile(
    r"(?<=[A-Za-zÀ-ÿ\]\)»”’])((?:\d[\s\u00A0]{1,2}){1,3}\d)(?=[\s\]\)\.,;:!?»”’]|$)"
)
SYMBOL_REF_RE = re.compile(
    r"(?<=[0-9A-Za-zÀ-ÿ\]\)»”’])(\*{1,3}|†+|‡+|§+)(?=[\s\]\)\.,;:!?»”’]|$)"
)
DEFINITION_MARKER_RE = re.compile(r"^\s*(\*{1,3}|†+|‡+|§+|\d+)[.)]?\s+")
NUMERIC_DEFINITION_MARKER_RE = re.compile(r"^\s*(\d+)[.)]?\s+")

# === 模块2增强:后置章节关键词 ===
BACK_MATTER_KEYWORDS = {
    "conclusion", "conclusions", "epilogue", "epilog", "afterword",
    "bibliography", "bibliographie", "references", "works cited",
    "index", "indices", "appendix", "appendices", "annexe", "annexes",
    "glossary", "glossaire", "acknowledgment", "acknowledgments", "acknowledgements",
    "remerciements", "about the author", "contributors", "notes", "endnotes",
}

BACK_MATTER_RE = re.compile(
    r"^\s*#{0,6}\s*("
    r"conclusion|conclusions|epilogue|epilog|afterword|"
    r"bibliography|bibliographie|references|works\s+cited|"
    r"index|indices|appendix|appendices|annexe|annexes|"
    r"glossary|glossaire|acknowledgments?|acknowledgements?|"
    r"remerciements|about\s+the\s+author|contributors|"
    r"notes?|endnotes?"
    r")\s*$",
    re.IGNORECASE,
)

# === 模块2增强:章节编号模式 ===
CHAPTER_NUMBER_RE = re.compile(
    r"^\s*#{0,6}\s*(?:chapter|chapitre|teil|part|partie)?\s*"
    r"(?:([IVXLCDM]+)|(\d{1,3}))\s*[.:—–-]?\s*",
    re.IGNORECASE,
)


# ============================================================
# 模块2增强:页面信号提取
# ============================================================

@dataclass
class PageSignals:
    """单页提取的结构化信号"""
    page_no: int
    doc_titles: list[dict] = field(default_factory=list)
    paragraph_titles: list[dict] = field(default_factory=list)
    notes_headings: list[dict] = field(default_factory=list)
    back_matter_headings: list[dict] = field(default_factory=list)
    headers: list[dict] = field(default_factory=list)  # 跑眉
    footnote_blocks: list[dict] = field(default_factory=list)
    bottom_text_blocks: list[dict] = field(default_factory=list)
    numeric_markers: list[int] = field(default_factory=list)
    marker_definitions: list[dict] = field(default_factory=list)
    is_sparse: bool = False
    
    def has_strong_boundary_signal(self) -> bool:
        return bool(self.doc_titles or self.notes_headings or self.back_matter_headings)
    
    def has_any_boundary_signal(self) -> bool:
        return self.has_strong_boundary_signal() or bool(self.paragraph_titles)


@dataclass
class BoundarySignal:
    """边界信号"""
    page_no: int
    signal_type: str
    strength: str
    title: str = ""
    section_kind: str = ""
    confidence: float = 1.0
    details: dict = field(default_factory=dict)


def classify_section_kind(title: str, has_notes_heading: bool = False) -> str:
    """根据标题判断 section 类型"""
    title_lower = title.lower().strip()
    
    if is_note_heading(title) or has_notes_heading:
        return "book_end_notes"
    if any(kw in title_lower for kw in ["bibliography", "bibliographie", "references", "works cited"]):
        return "bibliography"
    if any(kw in title_lower for kw in ["index", "indices"]):
        return "index"
    if any(kw in title_lower for kw in ["appendix", "appendices", "annexe", "annexes"]):
        return "appendix"
    if any(kw in title_lower for kw in ["glossary", "glossaire"]):
        return "glossary"
    if any(kw in title_lower for kw in ["acknowledgment", "acknowledgement", "remerciement"]):
        return "acknowledgments"
    return "body"


def extract_page_signals(page: dict, page_no: int, page_height: int = 0) -> PageSignals:
    """从单页提取所有结构信号"""
    signals = PageSignals(page_no=page_no)
    blocks = page_blocks(page)
    
    # 获取实际页面高度
    pr = page.get("prunedResult", {})
    actual_height = pr.get("height", 0) or page_height or 6000
    
    # 页顶阈值:前 20% 视为页顶
    top_threshold = actual_height * 0.20
    # 页底阈值:后 20% 视为页底
    bottom_threshold = actual_height * 0.80
    
    total_text_len = 0
    
    for block in blocks:
        label = block.get("block_label", "")
        content = block.get("block_content", "") or ""
        bbox = block.get("block_bbox") or []
        block_top = bbox[1] if len(bbox) > 1 else 0
        total_text_len += len(content)
        
        if label == "doc_title":
            text = normalize_heading(content)
            if text:
                # doc_title 需要在页顶才算真正的章节标题
                is_at_top = block_top < top_threshold
                entry = {"text": text, "bbox": bbox, "label": label, "at_top": is_at_top}
                if is_note_heading(content):
                    signals.notes_headings.append(entry)
                elif BACK_MATTER_RE.match(content):
                    signals.back_matter_headings.append(entry)
                else:
                    signals.doc_titles.append(entry)
        
        elif label == "paragraph_title":
            text = normalize_heading(content)
            if text:
                # paragraph_title 必须在页顶才可能是章节边界
                is_at_top = block_top < top_threshold
                entry = {"text": text, "bbox": bbox, "label": label, "at_top": is_at_top}
                if is_note_heading(content):
                    signals.notes_headings.append(entry)
                elif BACK_MATTER_RE.match(content):
                    signals.back_matter_headings.append(entry)
                else:
                    signals.paragraph_titles.append(entry)
        
        elif label == "header":
            # 记录跑眉, 用于检测后置章节首页
            text = normalize_heading(content)
            if text:
                is_at_top = block_top < top_threshold
                entry = {"text": text, "bbox": bbox, "label": label, "at_top": is_at_top}
                if BACK_MATTER_RE.match(text):
                    signals.headers.append(entry)
                else:
                    # 检测 Notes 类型跑眉(如 "Notes to Pages X-Y", "Note on Sources")
                    text_lower = text.lower()
                    if text_lower.startswith("note") or "notes " in text_lower:
                        signals.headers.append(entry)  # 作为普通跑眉记录, 由 find_boundary_signals 处理首次出现
        
        elif label == "footnote":
            marker = extract_definition_marker(content)
            signals.footnote_blocks.append({"text": content, "bbox": bbox, "marker": marker})
            if marker and marker.isdigit():
                signals.numeric_markers.append(int(marker))
                signals.marker_definitions.append({
                    "marker": int(marker), "text": content, "bbox": bbox, "source": "footnote_block",
                })
        
        elif label == "text" and block_top > bottom_threshold:
            marker = extract_definition_marker(content)
            if marker:
                signals.bottom_text_blocks.append({"text": content, "bbox": bbox, "marker": marker})
                if marker.isdigit():
                    signals.numeric_markers.append(int(marker))
    
    signals.is_sparse = total_text_len < 200
    return signals


def detect_marker_reset(prev_markers: list[int], curr_markers: list[int]) -> bool:
    """检测是否发生了编号重置"""
    if not prev_markers or not curr_markers:
        return False
    prev_max = max(prev_markers)
    curr_min = min(curr_markers)
    return prev_max >= 10 and curr_min <= 3


def extract_all_page_signals(pages: list[dict]) -> list[PageSignals]:
    """提取所有页面的信号"""
    all_signals = []
    for i, page in enumerate(pages):
        page_no = i + 1
        pr = page.get("prunedResult", {})
        page_height = pr.get("height", 1200) if isinstance(pr, dict) else 1200
        signals = extract_page_signals(page, page_no, page_height)
        all_signals.append(signals)
    return all_signals


def find_boundary_signals(all_signals: list[PageSignals], total_pages: int = 0) -> list[BoundarySignal]:
    """从所有页面信号中找出边界信号
    
    关键改进:
    1. doc_title/paragraph_title 必须在页顶才能作为边界
    2. Notes 标题区分 chapter_end_notes 和 book_end_notes
    3. marker_reset 只能作为辅助信号
    4. 跑眉首次出现可作为章节边界(仅限后置章节如 Bibliography, Index)
    """
    boundaries: list[BoundarySignal] = []
    prev_markers: list[int] = []
    seen_headers: set[str] = set()  # 已出现过的跑眉文本
    total_pages = total_pages or len(all_signals)
    
    # 书末阈值:后 15% 的页面视为书末区域
    book_end_threshold = int(total_pages * 0.85) if total_pages > 20 else total_pages - 3
    
    for signals in all_signals:
        page_no = signals.page_no
        is_in_book_end = page_no >= book_end_threshold
        
        for dt in signals.doc_titles:
            # doc_title 必须在页顶才是真正的章节边界
            if not dt.get("at_top", True):
                continue
            kind = classify_section_kind(dt["text"])
            boundaries.append(BoundarySignal(
                page_no=page_no, signal_type="doc_title", strength="strong",
                title=dt["text"], section_kind=kind, confidence=0.95,
            ))
        
        for nh in signals.notes_headings:
            # Notes 标题:书末区域的是 book_end_notes, 否则可能是 chapter_end_notes
            note_kind = "book_end_notes" if is_in_book_end else "chapter_end_notes"
            boundaries.append(BoundarySignal(
                page_no=page_no, signal_type="notes_heading", strength="strong",
                title=nh["text"], section_kind=note_kind, confidence=0.9,
            ))
        
        for bm in signals.back_matter_headings:
            # back_matter 标题必须在页顶
            if not bm.get("at_top", True):
                continue
            kind = classify_section_kind(bm["text"])
            boundaries.append(BoundarySignal(
                page_no=page_no, signal_type="back_matter", strength="strong",
                title=bm["text"], section_kind=kind, confidence=0.9,
            ))
        
        for pt in signals.paragraph_titles:
            # paragraph_title 必须在页顶 AND 匹配 back_matter 模式才能作为边界
            if not pt.get("at_top", False):
                continue
            if BACK_MATTER_RE.match(pt["text"]):
                kind = classify_section_kind(pt["text"])
                boundaries.append(BoundarySignal(
                    page_no=page_no, signal_type="paragraph_title", strength="medium",
                    title=pt["text"], section_kind=kind, confidence=0.7,
                ))
        
        # 检测跑眉首次出现(仅限后置章节)
        for hdr in signals.headers:
            header_text = hdr["text"].upper().strip()
            # 对于 "Notes to Pages X-Y" 格式, 只取 "NOTES" 部分作为 key
            header_key = header_text
            if header_text.startswith("NOTES TO"):
                header_key = "NOTES_SECTION"
            elif header_text.startswith("NOTE ON"):
                header_key = "NOTE_ON_SOURCES"
            
            if header_key not in seen_headers:
                seen_headers.add(header_key)
                # 跑眉首次出现, 可能是章节开始
                header_lower = hdr["text"].lower()
                
                # 检测 Notes 类型跑眉
                if header_lower.startswith("note"):
                    boundaries.append(BoundarySignal(
                        page_no=page_no, signal_type="header_first_occurrence", strength="medium",
                        title=hdr["text"], section_kind="book_end_notes", confidence=0.8,
                    ))
                    continue
                
                kind = classify_section_kind(hdr["text"])
                # 允许的后置章节类型(通过跑眉首次出现来识别)
                # 只有在书末区域才考虑 body 类型(如 epilogue, conclusion)
                allowed_header_kinds = ("bibliography", "index", "appendix", "glossary", "acknowledgments")
                if kind in allowed_header_kinds:
                    boundaries.append(BoundarySignal(
                        page_no=page_no, signal_type="header_first_occurrence", strength="medium",
                        title=hdr["text"], section_kind=kind, confidence=0.75,
                    ))
                elif kind == "body" and is_in_book_end:
                    # 书末区域的 body 类型跑眉(如 EPILOGUE, CONCLUSION)也可能是章节边界
                    boundaries.append(BoundarySignal(
                        page_no=page_no, signal_type="header_first_occurrence", strength="medium",
                        title=hdr["text"], section_kind=kind, confidence=0.7,
                    ))
        
        if detect_marker_reset(prev_markers, signals.numeric_markers):
            boundaries.append(BoundarySignal(
                page_no=page_no, signal_type="marker_reset", strength="weak",
                title="", section_kind="", confidence=0.5,
                details={"prev_max": max(prev_markers) if prev_markers else 0,
                         "curr_min": min(signals.numeric_markers) if signals.numeric_markers else 0},
            ))
        
        prev_markers = signals.numeric_markers
    
    return boundaries


def integrate_visual_toc_boundaries(
    boundaries: list[BoundarySignal],
    visual_toc: list[dict],
    total_pages: int,
) -> list[BoundarySignal]:
    """
    整合视觉目录信息到边界信号中
    
    视觉目录提供了高置信度的章节边界信息,可以:
    1. 确认已检测到的边界
    2. 补充缺失的边界
    3. 修正错误的边界位置
    
    Args:
        boundaries: 已检测的边界信号列表
        visual_toc: 视觉目录条目列表, 每项包含 title, file_idx/book_page, depth 等
        total_pages: 总页数
    
    Returns:
        整合后的边界信号列表
    """
    if not visual_toc:
        return boundaries
    
    # 按 visual_order 排序
    sorted_toc = sorted(visual_toc, key=lambda x: x.get("visual_order", 0))
    
    # 第一遍: 收集所有有效的页码
    valid_pages: list[tuple[int, dict]] = []
    for item in sorted_toc:
        page_no = item.get("file_idx")
        if page_no is not None:
            page_no = page_no + 1
        else:
            page_no = item.get("book_page")
        
        if page_no is not None and 1 <= page_no <= total_pages:
            valid_pages.append((page_no, item))
    
    if not valid_pages:
        return boundaries
    
    # 第二遍: 过滤掉顺序异常的条目
    # 如果一个条目的页码与前后条目相比明显不符合顺序,则跳过
    visual_boundaries: list[BoundarySignal] = []
    
    for i, (page_no, item) in enumerate(valid_pages):
        title = item.get("title", "")
        kind = classify_section_kind(title)
        
        # 检查顺序是否合理
        is_valid = True
        
        # 前置章节(如 Introduction)应该在书的前半部分
        is_front_matter = i < len(valid_pages) // 2 and kind == "body" and item.get("depth", 0) == 0
        
        if is_front_matter and page_no > total_pages * 0.7:
            # 前置章节不应该在书的后 30%
            is_valid = False
        
        # 检查与相邻条目的页码关系
        if i > 0:
            prev_page = valid_pages[i - 1][0]
            prev_kind = classify_section_kind(valid_pages[i - 1][1].get("title", ""))
            # 如果前一个是后置章节,当前不应该回退太多
            if prev_kind in ("bibliography", "index", "appendix"):
                if page_no < prev_page - 20 and kind not in ("bibliography", "index", "appendix"):
                    is_valid = False
        
        if not is_valid:
            continue
        
        depth = item.get("depth", 0)
        
        visual_boundaries.append(BoundarySignal(
            page_no=page_no,
            signal_type="visual_toc",
            strength="strong",
            title=title,
            section_kind=kind,
            confidence=0.95,
            details={"depth": depth, "source": "visual_toc"},
        ))
    
    if not visual_boundaries:
        return boundaries
    
    # 合并策略:
    # 1. 如果视觉目录边界和现有边界在同一页(±1页), 优先使用视觉目录的信息
    # 2. 否则添加视觉目录边界作为新边界
    
    existing_pages = {b.page_no for b in boundaries}
    merged: list[BoundarySignal] = []
    used_visual: set[int] = set()
    
    for b in boundaries:
        # 检查是否有对应的视觉目录边界
        matching_visual = None
        for vb in visual_boundaries:
            if abs(vb.page_no - b.page_no) <= 1 and vb.page_no not in used_visual:
                matching_visual = vb
                break
        
        if matching_visual:
            # 使用视觉目录信息增强现有边界
            used_visual.add(matching_visual.page_no)
            enhanced = BoundarySignal(
                page_no=matching_visual.page_no,  # 使用视觉目录的页码
                signal_type=f"{b.signal_type}+visual_toc",
                strength="strong",
                title=matching_visual.title or b.title,
                section_kind=matching_visual.section_kind or b.section_kind,
                confidence=max(b.confidence, matching_visual.confidence),
                details={**b.details, "visual_toc_confirmed": True},
            )
            merged.append(enhanced)
        else:
            merged.append(b)
    
    # 添加未匹配的视觉目录边界
    for vb in visual_boundaries:
        if vb.page_no not in used_visual:
            # 检查是否与现有边界太近
            too_close = any(abs(vb.page_no - b.page_no) <= 2 for b in merged)
            if not too_close:
                merged.append(vb)
    
    # 按页码排序
    merged.sort(key=lambda b: b.page_no)
    
    return merged


def merge_nearby_boundaries(boundaries: list[BoundarySignal], window: int = 2) -> list[BoundarySignal]:
    """
    合并相邻的边界信号
    
    只合并 section_kind 相同且标题相似的边界, 不同类型的边界不合并.
    例如 "Chapter 1" 和 "Notes" 即使相邻也应保留两个独立的边界.
    """
    if not boundaries:
        return []
    
    by_page: dict[int, list[BoundarySignal]] = {}
    for b in boundaries:
        by_page.setdefault(b.page_no, []).append(b)
    
    merged: list[BoundarySignal] = []
    processed: set[tuple[int, str]] = set()  # (page_no, section_kind) 已处理
    
    for page_no in sorted(by_page.keys()):
        for signal in by_page[page_no]:
            # 已处理的跳过
            key = (page_no, signal.section_kind)
            if key in processed:
                continue
            
            # 找窗口内相同 section_kind 的信号
            window_signals: list[BoundarySignal] = [signal]
            for p in range(page_no + 1, page_no + window + 1):
                if p in by_page:
                    for s in by_page[p]:
                        # 只合并相同 section_kind 的边界
                        if s.section_kind == signal.section_kind:
                            window_signals.append(s)
                            processed.add((p, s.section_kind))
            
            # 选择最强的信号
            best = max(window_signals, key=lambda b: (
                {"strong": 3, "medium": 2, "weak": 1}.get(b.strength, 0),
                b.confidence,
            ))
            merged.append(best)
            processed.add(key)
    
    # 按页码排序
    merged.sort(key=lambda b: b.page_no)
    
    # 过滤孤立的弱信号(如 marker_reset 没有伴随强信号标题)
    final: list[BoundarySignal] = []
    for i, b in enumerate(merged):
        if b.strength == "weak" and not b.section_kind:
            # 检查周围 ±2 页是否有强/中信号
            nearby_strong = False
            for j, other in enumerate(merged):
                if i != j and abs(b.page_no - other.page_no) <= 3:
                    if other.strength in ("strong", "medium"):
                        nearby_strong = True
                        break
            if not nearby_strong:
                # 孤立的弱信号, 跳过
                continue
        final.append(b)
    
    return final


@dataclass
class Note:
    note_id: str
    kind: str
    original_marker: str
    start_page: int
    section_id: str
    pages: list[int] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    def add_block(self, page_no: int, text: str) -> None:
        if not self.pages or self.pages[-1] != page_no:
            self.pages.append(page_no)
        self.text_parts.append(text.strip())

    @property
    def text(self) -> str:
        return "\n\n".join(part for part in self.text_parts if part)

    def to_dict(self) -> dict:
        return {
            "id": self.note_id,
            "kind": self.kind,
            "original_marker": self.original_marker,
            "start_page": self.start_page,
            "pages": self.pages,
            "text": self.text,
        }


@dataclass
class Section:
    index: int
    title: str
    section_id: str
    start_page: int
    end_page: int = 0
    pages: list[int] = field(default_factory=list)
    endnotes_start_page: int | None = None
    page_refs: dict[int, set[str]] = field(default_factory=dict)
    footnotes: list[Note] = field(default_factory=list)
    endnotes: list[Note] = field(default_factory=list)
    # Module 2 新增字段
    section_kind: str = "body"  # body, chapter_end_notes, book_end_notes, bibliography, index, appendix, glossary, acknowledgments
    boundary_confidence: float = 0.0
    boundary_signals: list[str] = field(default_factory=list)
    note_mode: str = "unknown"  # footnote_only, endnote_only, mixed, none
    note_source_section_id: str | None = None  # 仅书末尾注回挂时使用

    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "pages": self.pages,
            "endnotes_start_page": self.endnotes_start_page,
            "page_refs": {str(k): sorted(v) for k, v in self.page_refs.items()},
            "footnotes": [note.to_dict() for note in self.footnotes],
            "endnotes": [note.to_dict() for note in self.endnotes],
            # Module 2 新增输出
            "section_kind": self.section_kind,
            "boundary_confidence": self.boundary_confidence,
            "boundary_signals": self.boundary_signals,
            "note_mode": self.note_mode,
            "note_source_section_id": self.note_source_section_id,
        }


def normalize_marker(raw: str | None) -> str | None:
    if raw is None:
        return None
    marker = raw.strip().translate(SUPERSCRIPT_TO_ASCII)
    if re.fullmatch(r"(?:\d[\s\u00A0]*)+", marker):
        marker = re.sub(r"[\s\u00A0]+", "", marker)
    marker = marker.rstrip(".):")
    return marker or None


def normalize_heading(text: str) -> str:
    return re.sub(r"^\s*#+\s*", "", text.strip())


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "section"


def is_note_heading(text: str) -> bool:
    return bool(NOTES_HEADING_RE.match(text.strip()))


def page_blocks(page: dict) -> list[dict]:
    blocks = page.get("prunedResult", {}).get("parsing_res_list", [])
    
    def sort_key(block: dict) -> tuple:
        order = block.get("block_order")
        bbox = block.get("block_bbox") or [0, 0, 0, 0]
        return (
            order if order is not None else 10**9,
            bbox[1] if len(bbox) > 1 else 0,
            bbox[0] if len(bbox) > 0 else 0,
        )
    
    return sorted(blocks, key=sort_key)


def body_markdown(page: dict) -> str:
    markdown = page.get("markdown", "")
    if isinstance(markdown, dict):
        text = str(markdown.get("text", "") or "")
    else:
        text = str(markdown or "")
    kept_lines: list[str] = []
    for line in text.splitlines():
        if NOTES_HEADING_RE.match(line):
            break
        kept_lines.append(line)
    return "\n".join(kept_lines).rstrip()


def extract_refs(text: str) -> set[str]:
    refs: set[str] = set()

    for raw in MD_REF_RE.findall(text):
        marker = normalize_marker(raw)
        if marker:
            refs.add(marker)

    for raw in BRACKET_NUM_REF_RE.findall(text):
        marker = normalize_marker(raw)
        if marker:
            refs.add(marker)

    for raw in MATH_REF_RE.findall(text):
        marker = normalize_marker(raw)
        if marker and re.fullmatch(r"\d+|\*{1,3}|†+|‡+|§+", marker):
            refs.add(marker)

    for raw in SUPERSCRIPT_REF_RE.findall(text):
        marker = normalize_marker(raw)
        if marker:
            refs.add(marker)

    for raw in PLAIN_DIGIT_REF_RE.findall(text):
        marker = normalize_marker(raw)
        if marker:
            refs.add(marker)

    for raw in SPLIT_DIGIT_REF_RE.findall(text):
        marker = normalize_marker(raw)
        if marker:
            refs.add(marker)

    for raw in SYMBOL_REF_RE.findall(text):
        marker = normalize_marker(raw)
        if marker:
            refs.add(marker)

    return refs


def extract_definition_marker(text: str) -> str | None:
    match = DEFINITION_MARKER_RE.match(text)
    if not match:
        return None
    return normalize_marker(match.group(1))


def extract_numeric_definition_marker(text: str) -> str | None:
    match = NUMERIC_DEFINITION_MARKER_RE.match(text)
    if not match:
        return None
    return normalize_marker(match.group(1))


def is_numeric_marker(marker: str | None) -> bool:
    return bool(marker and re.fullmatch(r"\d+", marker))


def _infer_section_kind(title: str, boundary_signal: BoundarySignal | None) -> str:
    """根据标题和边界信号推断 section 类型"""
    if boundary_signal and boundary_signal.section_kind:
        return boundary_signal.section_kind
    
    title_lower = title.lower().strip()
    
    # 检查是否是书末尾注区
    if re.match(r'^(notes?|endnotes?|tail\s*notes?|尾注|注释|注解)$', title_lower, re.IGNORECASE):
        return "book_end_notes"
    
    # 检查是否是参考文献
    if re.match(r'^(bibliography|references?|works?\s+cited|文献|参考文献)', title_lower, re.IGNORECASE):
        return "bibliography"
    
    # 检查是否是索引
    if re.match(r'^(index|索引)', title_lower, re.IGNORECASE):
        return "index"
    
    # 检查是否是附录
    if re.match(r'^(appendix|appendices|附录)', title_lower, re.IGNORECASE):
        return "appendix"
    
    # 检查是否是术语表
    if re.match(r'^(glossary|术语表|词汇表)', title_lower, re.IGNORECASE):
        return "glossary"
    
    # 检查是否是致谢
    if re.match(r'^(acknowledgment|acknowledgement|致谢)', title_lower, re.IGNORECASE):
        return "acknowledgments"
    
    return "body"


def build_sections(pages: list[dict], visual_toc: list[dict] | None = None) -> list[Section]:
    """
    使用多信号边界切分构建章节列表
    
    信号优先级:
    - 强信号:doc_title, 明确的 Notes/Endnotes 标题, 后置章节关键词, 视觉目录
    - 中信号:paragraph_title with back matter keywords
    - 弱信号:脚注编号重置
    
    Args:
        pages: 页面数据列表
        visual_toc: 可选的视觉目录数据, 用于辅助边界检测
    """
    # 第一步:提取所有页面信号并找出边界
    all_signals: list[PageSignals] = []
    for page_no, page in enumerate(pages, start=1):
        signals = extract_page_signals(page, page_no)
        all_signals.append(signals)
    
    # 找出所有边界信号并合并相邻的
    total_pages = len(pages)
    boundaries = find_boundary_signals(all_signals, total_pages)
    
    # 整合视觉目录边界(如果提供)
    if visual_toc:
        boundaries = integrate_visual_toc_boundaries(boundaries, visual_toc, total_pages)
    
    boundaries = merge_nearby_boundaries(boundaries, window=2)
    
    # 第二步:根据边界信号构建 sections
    sections: list[Section] = []
    current: Section | None = None
    boundary_idx = 0
    
    for page_no, page in enumerate(pages, start=1):
        # 检查当前页是否有边界信号
        boundary_at_page: BoundarySignal | None = None
        if boundary_idx < len(boundaries) and boundaries[boundary_idx].page_no == page_no:
            boundary_at_page = boundaries[boundary_idx]
            boundary_idx += 1
        
        # 如果有边界信号, 开启新 section
        if boundary_at_page is not None:
            if current is not None:
                current.end_page = page_no - 1
                sections.append(current)
            
            title = boundary_at_page.title or "untitled"
            section_kind = _infer_section_kind(title, boundary_at_page)
            
            current = Section(
                index=len(sections) + 1,
                title=title,
                section_id=f"sec-{len(sections) + 1:02d}-{slugify(title)}",
                start_page=page_no,
                section_kind=section_kind,
                boundary_confidence=boundary_at_page.confidence,
                boundary_signals=[f"{boundary_at_page.signal_type}:{boundary_at_page.strength}"],
            )
        
        # 确保有一个当前 section
        if current is None:
            current = Section(
                index=1,
                title="untitled",
                section_id="sec-01-untitled",
                start_page=1,
                section_kind="body",
                boundary_confidence=0.5,
                boundary_signals=["implicit_start"],
            )
        
        current.pages.append(page_no)
        
        # 检测章末尾注开始页(保持兼容)
        if current.endnotes_start_page is None:
            blocks = page_blocks(page)
            for block in blocks:
                if is_note_heading(block.get("block_content", "")):
                    current.endnotes_start_page = page_no
                    break
    
    # 关闭最后一个 section
    if current is not None:
        current.end_page = len(pages)
        sections.append(current)
    
    # 第三步:后处理 - 合并章末尾注到前一章节
    sections = _merge_chapter_end_notes(sections)
    
    # 第四步:后处理 - 标记书末尾注并回挂到正文章节
    sections = _postprocess_book_endnotes(sections)
    
    return sections


def _merge_chapter_end_notes(sections: list[Section]) -> list[Section]:
    """
    合并章末尾注到前一个正文章节
    
    对于像 Biopolitics 这样的书, 每章后面紧跟着 NOTES:
    - 章节正文 (body) pages 17-38
    - NOTES (chapter_end_notes) pages 39-42
    - 章节正文 (body) pages 43-62
    - NOTES (chapter_end_notes) pages 63-66
    - ...
    
    我们应该把 NOTES 合并到前一章节, 而不是创建独立的 section.
    """
    if len(sections) < 2:
        return sections
    
    merged: list[Section] = []
    i = 0
    
    while i < len(sections):
        sec = sections[i]
        
        # 如果当前是 body section, 检查下一个是否是 chapter_end_notes
        if sec.section_kind == "body" and i + 1 < len(sections):
            next_sec = sections[i + 1]
            if next_sec.section_kind == "chapter_end_notes":
                # 合并:扩展 body section 的结束页到 chapter_end_notes 的结束页
                sec.end_page = next_sec.end_page
                sec.pages = list(range(sec.start_page, sec.end_page + 1))
                # 标记此 section 有章末尾注
                sec.note_mode = "chapter_end_notes"
                merged.append(sec)
                i += 2  # 跳过 chapter_end_notes section
                continue
        
        merged.append(sec)
        i += 1
    
    # 重新编号
    for idx, sec in enumerate(merged, start=1):
        sec.index = idx
    
    return merged


def _postprocess_book_endnotes(sections: list[Section]) -> list[Section]:
    """
    后处理:识别书末尾注区并建立与正文章节的关联
    
    书末尾注特征:
    - section_kind == "book_end_notes"
    - 或者标题包含 Notes/Endnotes 且位于书的后半部分
    """
    if len(sections) < 2:
        return sections
    
    # 找到书末尾注 section
    book_endnotes_section: Section | None = None
    body_sections: list[Section] = []
    
    for sec in sections:
        if sec.section_kind == "book_end_notes":
            book_endnotes_section = sec
        elif sec.section_kind == "body":
            body_sections.append(sec)
    
    # 如果找到了书末尾注, 为它设置来源关联(暂时指向最后一个正文章节)
    # 实际的尾注解析和回挂将在后续的 collect_notes 中处理
    if book_endnotes_section and body_sections:
        book_endnotes_section.note_source_section_id = body_sections[-1].section_id
    
    return sections


def first_footnote_block_before_notes(section: Section, pages: list[dict], page_no: int) -> dict | None:
    if page_no < section.start_page or page_no > section.end_page:
        return None

    for block in page_blocks(pages[page_no - 1]):
        if is_note_heading(block.get("block_content", "")):
            return None
        if block.get("block_label") == "footnote":
            return block
    return None


def next_page_continues_footnote(
    section: Section, pages: list[dict], page_no: int, current: Note | None
) -> bool:
    next_page = page_no + 1
    if next_page > section.end_page:
        return False

    first_block = first_footnote_block_before_notes(section, pages, next_page)
    if first_block is None:
        return False

    marker = extract_definition_marker(first_block.get("block_content", ""))
    if marker and current is not None and marker != current.original_marker:
        return False
    return not (marker and marker in section.page_refs.get(next_page, set()))


def _collect_page_ref_texts(page: dict) -> list[str]:
    chunks: list[str] = []
    seen: set[str] = set()

    def _append_text(value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        key = re.sub(r"\s+", " ", text)
        if key in seen:
            return
        seen.add(key)
        chunks.append(text)

    _append_text(body_markdown(page))

    in_note_zone = False
    for block in page_blocks(page):
        text = str(block.get("block_content", "") or "").strip()
        if not text:
            continue
        if is_note_heading(text):
            in_note_zone = True
            continue
        if in_note_zone:
            continue
        if block.get("block_label") == "footnote":
            continue
        if extract_definition_marker(text):
            continue
        if block.get("block_label") in {"text", "doc_title", "paragraph_title", "abstract"}:
            _append_text(text)

    for block in page.get("fnBlocks") or []:
        text = str(block.get("text") or block.get("content") or "").strip()
        if not text or extract_definition_marker(text):
            continue
        _append_text(text)

    return chunks


def collect_page_refs(section: Section, pages: list[dict]) -> None:
    for page_no in section.pages:
        refs: set[str] = set()
        for text in _collect_page_ref_texts(pages[page_no - 1]):
            refs.update(extract_refs(text))
        section.page_refs[page_no] = refs


def _detect_bottom_footnote_blocks(
    page: dict,
    page_no: int,
    page_refs: set[str],
    *,
    expected_numeric_refs: list[int] | None = None,
    recent_numeric_marker: int | None = None,
) -> list[dict]:
    """
    第二通道:在缺乏 footnote 标签的页面上, 启发式检测页底脚注
    
    识别信号:
    1. block 位于页面下半部分(y_top > 页面高度的 60%)
    2. block 以数字或符号 marker 开头
    3. marker 与正文引用 / 预期编号区间 / 最近编号存在上下文一致性
    4. 文本长度合理且处于页底优先区域
    """
    blocks = page_blocks(page)
    if not blocks:
        return []

    def _looks_like_footnote_text(text: str) -> bool:
        stripped = str(text or "").strip()
        if not (4 <= len(stripped) <= 2200):
            return False
        body = DEFINITION_MARKER_RE.sub("", stripped, count=1).strip()
        if len(body) < 3:
            return False
        alpha_count = sum(1 for ch in body if ch.isalpha())
        digit_count = sum(1 for ch in body if ch.isdigit())
        if alpha_count == 0 and digit_count <= 4:
            return False
        compact = re.sub(r"\s+", "", body)
        if compact and compact.isupper() and len(compact) <= 12:
            return False
        return True

    text_blocks = [block for block in blocks if block.get("block_label") == "text"]
    if not text_blocks:
        return []

    page_bottom_candidates = [
        bbox[3]
        for bbox in (block.get("block_bbox") or [0, 0, 0, 0] for block in blocks)
        if isinstance(bbox, list) and len(bbox) > 3 and isinstance(bbox[3], (int, float))
    ]
    page_bottom = float(max(page_bottom_candidates)) if page_bottom_candidates else 1000.0
    page_height_threshold = page_bottom * 0.58
    page_bottom_band = page_bottom * 0.76
    deep_bottom_band = page_bottom * 0.84
    normalized_refs = {normalized for ref in page_refs if (normalized := normalize_marker(ref))}
    expected_nums = sorted({int(n) for n in (expected_numeric_refs or []) if int(n) > 0})

    candidate_infos: list[dict] = []
    tail_window_start = max(0, len(text_blocks) - 4)

    for idx, block in enumerate(text_blocks):
        text = str(block.get("block_content", "") or "")
        marker = extract_definition_marker(text)
        if not marker:
            continue
        if is_note_heading(text):
            continue
        if not _looks_like_footnote_text(text):
            continue

        bbox = block.get("block_bbox") or [0, 0, 0, 0]
        y_top = float(bbox[1]) if len(bbox) > 1 and isinstance(bbox[1], (int, float)) else 0.0
        if y_top < page_height_threshold:
            continue

        in_tail_window = idx >= tail_window_start
        if not in_tail_window and y_top < page_bottom * 0.68:
            continue

        marker_num = int(marker) if is_numeric_marker(marker) else None
        score = 0
        context_score = 0

        if y_top >= deep_bottom_band:
            score += 3
        elif y_top >= page_bottom_band:
            score += 2
        else:
            score += 1
        if in_tail_window:
            score += 1

        if marker in normalized_refs:
            context_score += 5

        if marker_num is not None:
            if expected_nums:
                expected_min = min(expected_nums) - 5
                expected_max = max(expected_nums) + 40
                if marker_num in expected_nums:
                    context_score += 3
                elif expected_min <= marker_num <= expected_max:
                    context_score += 1

            if recent_numeric_marker is not None:
                delta = abs(marker_num - int(recent_numeric_marker))
                if delta <= 4:
                    context_score += 3
                elif delta <= 20:
                    context_score += 2
                elif marker_num > int(recent_numeric_marker) and delta <= 80:
                    context_score += 1

            if marker_num <= 3:
                context_score += 1
        else:
            context_score += 1

        score += context_score
        candidate_infos.append(
            {
                "block": block,
                "score": score,
                "context_score": context_score,
                "y_top": y_top,
                "in_tail_window": in_tail_window,
                "marker_num": marker_num,
            }
        )

    if not candidate_infos:
        return []

    if len(candidate_infos) >= 2:
        for info in candidate_infos:
            info["score"] += 1

    numeric_markers = [info["marker_num"] for info in candidate_infos if info["marker_num"] is not None]
    if len(numeric_markers) >= 2 and numeric_markers == sorted(numeric_markers):
        for info in candidate_infos:
            if info["marker_num"] is not None:
                info["score"] += 1

    footnote_candidates: list[dict] = []
    for info in candidate_infos:
        strong_layout = info["y_top"] >= page_bottom_band or info["in_tail_window"]
        if info["score"] >= 5:
            footnote_candidates.append(info["block"])
            continue
        if info["context_score"] == 0 and strong_layout:
            if len(candidate_infos) >= 2 or info["y_top"] >= deep_bottom_band:
                footnote_candidates.append(info["block"])

    return footnote_candidates


def collect_footnotes(section: Section, pages: list[dict]) -> None:
    """
    双通道脚注收集:
    - 第一通道:使用 block_label == "footnote" 的块
    - 第二通道:在缺乏 footnote 标签的页面上, 启发式检测页底脚注
    
    注意:book_end_notes, bibliography, index 等非正文 section 不进行脚注收集
    """
    # 非正文 section 不收集脚注
    if section.section_kind in {"book_end_notes", "bibliography", "index"}:
        return
    
    note_counter = 1
    current: Note | None = None
    recent_numeric_marker: int | None = None

    for page_no in section.pages:
        page = pages[page_no - 1]
        blocks = page_blocks(page)
        page_refs = section.page_refs.get(page_no, set())
        expected_numeric_refs = sorted(
            int(ref)
            for ref in page_refs
            if is_numeric_marker(ref)
        )
        saw_relevant_block = False
        first_page_footnote = first_footnote_block_before_notes(section, pages, page_no)
        first_page_marker = extract_definition_marker(
            first_page_footnote.get("block_content", "") if first_page_footnote else ""
        )
        numeric_footnote_mode = is_numeric_marker(first_page_marker)
        
        # 第一通道:收集标记为 footnote 的块
        footnote_blocks = [b for b in blocks if b.get("block_label") == "footnote"]
        used_inferred_channel = False
        
        # 第二通道:如果没有 footnote 标签块, 尝试启发式检测
        if not footnote_blocks:
            footnote_blocks = _detect_bottom_footnote_blocks(
                page,
                page_no,
                page_refs,
                expected_numeric_refs=expected_numeric_refs,
                recent_numeric_marker=recent_numeric_marker,
            )
            used_inferred_channel = bool(footnote_blocks)
            if footnote_blocks:
                # 标记使用了第二通道
                section.boundary_signals.append(f"page_{page_no}_footnote_inferred")

        if not numeric_footnote_mode and footnote_blocks:
            first_detected_marker = extract_definition_marker(
                footnote_blocks[0].get("block_content", "")
            )
            numeric_footnote_mode = is_numeric_marker(first_detected_marker)

        for block in footnote_blocks:
            if is_note_heading(block.get("block_content", "")):
                break

            saw_relevant_block = True
            text = block.get("block_content", "")
            marker = extract_definition_marker(text)
            starts_new_note = bool(marker and marker in page_refs)
            if is_numeric_marker(marker):
                recent_numeric_marker = int(marker)

            if (
                not starts_new_note
                and marker
                and current is not None
                and marker != current.original_marker
                and (used_inferred_channel or not page_refs or numeric_footnote_mode)
            ):
                starts_new_note = True

            # OCR occasionally drops the in-body superscript but still keeps
            # one footnote per block in pages that are clearly numeric notes.
            if (
                not starts_new_note
                and numeric_footnote_mode
                and is_numeric_marker(marker)
                and (current is None or current.original_marker != marker)
            ):
                starts_new_note = True

            if starts_new_note:
                if current is not None:
                    section.footnotes.append(current)
                current = Note(
                    note_id=f"fn-{section.index:02d}-{note_counter:04d}",
                    kind="footnote",
                    original_marker=marker,
                    start_page=page_no,
                    section_id=section.section_id,
                )
                note_counter += 1
            elif current is None:
                current = Note(
                    note_id=f"fn-{section.index:02d}-{note_counter:04d}",
                    kind="footnote",
                    original_marker=marker or "?",
                    start_page=page_no,
                    section_id=section.section_id,
                )
                note_counter += 1

            current.add_block(page_no, text)

        if (
            current is not None
            and saw_relevant_block
            and not next_page_continues_footnote(section, pages, page_no, current)
        ):
            section.footnotes.append(current)
            current = None

    if current is not None:
        section.footnotes.append(current)


def collect_endnotes(section: Section, pages: list[dict]) -> None:
    if section.endnotes_start_page is None:
        return

    note_counter = 1
    current: Note | None = None
    in_endnote_zone = False

    for page_no in section.pages:
        if page_no < section.endnotes_start_page:
            continue

        for block in page_blocks(pages[page_no - 1]):
            text = block.get("block_content", "")

            if not in_endnote_zone:
                if is_note_heading(text):
                    in_endnote_zone = True
                continue

            if block.get("block_label") not in {"text", "footnote"}:
                continue

            marker = extract_numeric_definition_marker(text)

            if marker:
                if current is not None:
                    section.endnotes.append(current)
                current = Note(
                    note_id=f"en-{section.index:02d}-{note_counter:04d}",
                    kind="endnote",
                    original_marker=marker,
                    start_page=page_no,
                    section_id=section.section_id,
                )
                note_counter += 1
            elif current is None:
                continue

            current.add_block(page_no, text)

    if current is not None:
        section.endnotes.append(current)


def _attach_book_endnotes_to_body_sections(sections: list[Section]) -> None:
    """
    将书末尾注回挂到正文章节
    
    策略:
    1. 先按 marker 重置拆分 run，避免跨章节的同号尾注互相覆盖。
    2. 再按每个 run 在各正文章节中的 marker 引用支持度分配目标章节。
    3. 若支持度不足，则采用顺序兜底（单 run 维持末章兜底，多 run 依次前推）。
    4. 无法分配的 run 会保留在 book_end_notes section，避免静默错挂。
    """
    book_endnotes_section: Section | None = None
    body_sections: list[Section] = []
    
    for sec in sections:
        if sec.section_kind == "book_end_notes":
            book_endnotes_section = sec
        elif sec.section_kind == "body":
            body_sections.append(sec)
    
    if not book_endnotes_section or not body_sections:
        return
    
    if not book_endnotes_section.endnotes:
        return
    
    # 找到 Notes 区之前的最后一个正文章节
    # 按 start_page 排序, 找到 start_page < book_endnotes_section.start_page 的最后一个
    preceding_body_sections = [
        sec for sec in body_sections 
        if sec.start_page < book_endnotes_section.start_page
    ]
    
    if not preceding_body_sections:
        preceding_body_sections = body_sections
    preceding_body_sections = sorted(preceding_body_sections, key=lambda section: section.start_page)

    def _section_marker_support(sec: Section, markers: set[str]) -> int:
        if not markers:
            return 0
        refs: set[str] = set()
        for values in (sec.page_refs or {}).values():
            refs.update(str(v) for v in (values or []))
        return len(markers & refs)

    def _split_endnote_runs(notes: list[Note]) -> list[list[Note]]:
        runs: list[list[Note]] = []
        current: list[Note] = []
        prev_marker: int | None = None
        for note in notes:
            marker = int(note.original_marker) if is_numeric_marker(note.original_marker) else None
            should_split = False
            if current and marker is not None and prev_marker is not None:
                if (marker <= prev_marker and marker <= 3) or (marker + 5 < prev_marker):
                    should_split = True
            if should_split:
                runs.append(current)
                current = []
            current.append(note)
            if marker is not None:
                prev_marker = marker
        if current:
            runs.append(current)
        return runs

    runs = _split_endnote_runs(list(book_endnotes_section.endnotes or []))
    if not runs:
        return

    unassigned: list[Note] = []
    last_target_idx = -1

    for run in runs:
        run_markers = {
            str(int(note.original_marker))
            for note in run
            if is_numeric_marker(note.original_marker)
        }
        supports = [
            _section_marker_support(section, run_markers)
            for section in preceding_body_sections
        ]
        max_support = max(supports) if supports else 0
        target_idx = -1

        if max_support > 0:
            candidate_indices = [
                idx for idx, score in enumerate(supports)
                if score == max_support
            ]
            target_idx = next(
                (idx for idx in candidate_indices if idx > last_target_idx),
                candidate_indices[0],
            )
        else:
            if len(runs) == 1:
                target_idx = len(preceding_body_sections) - 1
            else:
                target_idx = min(last_target_idx + 1, len(preceding_body_sections) - 1)

        if target_idx < 0 or target_idx >= len(preceding_body_sections):
            unassigned.extend(run)
            continue

        target = preceding_body_sections[target_idx]
        for note in run:
            note.section_id = target.section_id
            target.endnotes.append(note)
        target.note_mode = "mixed" if target.footnotes else "endnote_only"
        last_target_idx = target_idx

    book_endnotes_section.endnotes = unassigned


def build_manifest(input_path: Path, visual_toc: list[dict] | None = None) -> dict:
    pages = json.loads(input_path.read_text())
    sections = build_sections(pages, visual_toc=visual_toc)

    for section in sections:
        collect_page_refs(section, pages)
        collect_footnotes(section, pages)
        collect_endnotes(section, pages)
    
    # Module 2: 将书末尾注回挂到正文章节
    _attach_book_endnotes_to_body_sections(sections)

    return {
        "source_file": str(input_path),
        "page_count": len(pages),
        "sections": [section.to_dict() for section in sections],
    }


def iter_note_lines(notes: Iterable[dict]) -> Iterable[str]:
    for note in notes:
        preview = note["text"].replace("\n", " ")
        if len(preview) > 110:
            preview = preview[:107] + "..."
        yield (
            f"    - {note['id']} marker={note['original_marker']} "
            f"pages={note['pages']} text={preview}"
        )


def print_summary(manifest: dict) -> None:
    print(f"source: {manifest['source_file']}")
    print(f"pages: {manifest['page_count']}")
    for section in manifest["sections"]:
        print(
            f"- {section['section_id']} | title={section['title']} | "
            f"pages={section['start_page']}-{section['end_page']} | "
            f"footnotes={len(section['footnotes'])} | "
            f"endnotes={len(section['endnotes'])} | "
            f"endnotes_start_page={section['endnotes_start_page']}"
        )
        refs_preview = {
            page_no: refs
            for page_no, refs in section["page_refs"].items()
            if refs
        }
        if refs_preview:
            print(f"  body refs: {refs_preview}")
        if section["footnotes"]:
            print("  footnotes:")
            for line in iter_note_lines(section["footnotes"]):
                print(line)
        if section["endnotes"]:
            print("  endnotes:")
            for line in iter_note_lines(section["endnotes"]):
                print(line)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path, help="PaddleOCR-VL JSON file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full manifest as JSON instead of a summary.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_manifest(args.input_json)
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    print_summary(manifest)


if __name__ == "__main__":
    main()

"""Export planning helpers for Markdown export."""

from difflib import SequenceMatcher
import re

from document.text_utils import strip_html


_EXPORT_BOILERPLATE_STRONG_PATTERNS = [
    re.compile(r"\ball rights reserved\b", re.IGNORECASE),
    re.compile(r"\bcopyright\b", re.IGNORECASE),
    re.compile(r"\bisbn(?:-1[03])?\b", re.IGNORECASE),
    re.compile(r"\bcip\b", re.IGNORECASE),
    re.compile(r"版权所有"),
    re.compile(r"图书在版编目"),
]
_EXPORT_BOILERPLATE_WEAK_PATTERNS = [
    re.compile(r"\bpublisher\b", re.IGNORECASE),
    re.compile(r"\bprinted in\b", re.IGNORECASE),
    re.compile(r"\beditorial\b", re.IGNORECASE),
    re.compile(r"出版社"),
    re.compile(r"印刷"),
    re.compile(r"定价"),
]


def build_toc_chapters(toc_items: list, offset: int = 0, total_pages: int = 0) -> list[dict]:
    """将 TOC 条目转换为带页码范围的顶级章节列表。"""
    if not toc_items:
        return []

    def _bp(item: dict) -> int:
        bp = int(item.get("book_page") or 0)
        file_idx = item.get("file_idx")
        if not bp and file_idx is not None:
            bp = int(file_idx) + 1
        return bp + int(offset or 0) if bp > 0 else 0

    top_level = [item for item in toc_items if int(item.get("depth", 0) or 0) == 0]
    candidates = top_level if top_level else list(toc_items)

    chapters = []
    for item in candidates:
        bp = _bp(item)
        if bp > 0:
            chapters.append({
                "title": item.get("title", ""),
                "depth": int(item.get("depth", 0) or 0),
                "start_bp": bp,
                "end_bp": None,
            })

    if not chapters:
        return []

    chapters.sort(key=lambda chapter: chapter["start_bp"])

    for idx, chapter in enumerate(chapters):
        if idx + 1 < len(chapters):
            chapter["end_bp"] = chapters[idx + 1]["start_bp"] - 1
        else:
            chapter["end_bp"] = total_pages if total_pages > 0 else chapter["start_bp"]

    for idx, chapter in enumerate(chapters):
        chapter["index"] = idx

    return chapters


def build_toc_depth_map(toc_items: list, offset: int = 0) -> dict:
    """Build a {book_page: depth} lookup from TOC rows."""
    depth_map: dict[int, int] = {}
    for item in toc_items or []:
        depth = int(item.get("depth", 0) or 0)
        bp = int(item.get("book_page") or 0)
        fi = item.get("file_idx")
        if not bp and fi is not None:
            bp = int(fi) + 1
        if bp > 0:
            effective = bp + int(offset or 0)
            depth_map[effective] = depth
    return depth_map


def build_toc_title_map(toc_items: list, offset: int = 0, *, ensure_str) -> dict[int, str]:
    """Build a {book_page: title} lookup from TOC rows."""
    title_map: dict[int, str] = {}
    for item in toc_items or []:
        bp = int(item.get("book_page") or 0)
        fi = item.get("file_idx")
        if not bp and fi is not None:
            bp = int(fi) + 1
        if bp > 0:
            effective = bp + int(offset or 0)
            title_map[int(effective)] = ensure_str(item.get("title")).strip()
    return title_map


def _normalize_heuristic_text(raw: str, *, ensure_str) -> str:
    return re.sub(r"\s+", " ", ensure_str(raw)).strip().lower()


def _page_text_for_export_heuristic(
    entry: dict,
    *,
    ensure_str,
    normalize_footnote_markers,
    unwrap_translation_json,
) -> str:
    chunks: list[str] = []
    page_entries = entry.get("_page_entries") or []
    if page_entries:
        for page_entry in page_entries:
            orig = strip_html(
                normalize_footnote_markers(ensure_str(page_entry.get("original")).strip())
            ).strip()
            tr = strip_html(
                normalize_footnote_markers(
                    unwrap_translation_json(ensure_str(page_entry.get("translation")).strip())
                )
            ).strip()
            if orig:
                chunks.append(orig)
            if tr:
                chunks.append(tr)
    else:
        orig = strip_html(
            normalize_footnote_markers(ensure_str(entry.get("original")).strip())
        ).strip()
        tr = strip_html(
            normalize_footnote_markers(
                unwrap_translation_json(ensure_str(entry.get("translation")).strip())
            )
        ).strip()
        if orig:
            chunks.append(orig)
        if tr:
            chunks.append(tr)
    return "\n".join(chunks).strip()


def compute_boilerplate_skip_bps(
    entries: list[dict],
    chapters: list[dict] | None,
    *,
    ensure_str,
    normalize_footnote_markers,
    unwrap_translation_json,
    max_leading_scan: int = 12,
) -> set[int]:
    page_texts: dict[int, str] = {}
    for entry in entries or []:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp <= 0:
            continue
        text = _page_text_for_export_heuristic(
            entry,
            ensure_str=ensure_str,
            normalize_footnote_markers=normalize_footnote_markers,
            unwrap_translation_json=unwrap_translation_json,
        )
        if text:
            page_texts[bp] = text
    if not page_texts:
        return set()

    sorted_bps = sorted(page_texts.keys())
    last_bp = sorted_bps[-1]
    leading_limit_bp = min(last_bp, int(max_leading_scan))
    chapter_start_bp = None
    if chapters:
        starts = [int(ch.get("start_bp") or 0) for ch in chapters if int(ch.get("start_bp") or 0) > 0]
        if starts:
            chapter_start_bp = min(starts)

    if chapter_start_bp and chapter_start_bp > 1:
        candidate_bps = {bp for bp in sorted_bps if bp < chapter_start_bp}
    else:
        candidate_bps = {bp for bp in sorted_bps if bp <= leading_limit_bp}

    skip_bps: set[int] = set()
    normalized_by_bp = {
        bp: _normalize_heuristic_text(page_texts[bp], ensure_str=ensure_str)
        for bp in sorted_bps
    }
    length_by_bp = {bp: len(normalized_by_bp[bp]) for bp in sorted_bps}

    for bp in sorted_bps:
        text = normalized_by_bp[bp]
        text_len = length_by_bp[bp]
        if text_len == 0:
            continue
        in_candidate = bp in candidate_bps
        strong_hit = any(pattern.search(text) for pattern in _EXPORT_BOILERPLATE_STRONG_PATTERNS)
        weak_hit = any(pattern.search(text) for pattern in _EXPORT_BOILERPLATE_WEAK_PATTERNS)
        if (in_candidate or text_len <= 120) and strong_hit and text_len <= 1600:
            skip_bps.add(bp)
            continue
        if in_candidate and text_len <= 220 and weak_hit:
            skip_bps.add(bp)

    leading_bps = [bp for bp in sorted_bps if bp <= leading_limit_bp]
    for i in range(len(leading_bps)):
        a_bp = leading_bps[i]
        if a_bp in skip_bps:
            continue
        a_text = normalized_by_bp[a_bp]
        if len(a_text) < 24:
            continue
        for j in range(i + 1, len(leading_bps)):
            b_bp = leading_bps[j]
            if b_bp in skip_bps:
                continue
            b_text = normalized_by_bp[b_bp]
            if len(b_text) < 24:
                continue
            ratio = SequenceMatcher(None, a_text, b_text).ratio()
            if ratio >= 0.92 and len(b_text) <= 1600:
                skip_bps.add(b_bp)
    return skip_bps


def detect_book_index_pages(
    entries: list[dict],
    *,
    ensure_str,
    normalize_footnote_markers,
    unwrap_translation_json,
) -> set[int]:
    """Detect tail index pages that should be skipped in export."""
    page_texts: dict[int, str] = {}
    for entry in entries or []:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp <= 0:
            continue
        text = _page_text_for_export_heuristic(
            entry,
            ensure_str=ensure_str,
            normalize_footnote_markers=normalize_footnote_markers,
            unwrap_translation_json=unwrap_translation_json,
        )
        if text:
            page_texts[bp] = text
    if not page_texts:
        return set()

    sorted_bps = sorted(page_texts.keys())
    start_idx = int(len(sorted_bps) * 0.8)
    scan_bps = sorted_bps[start_idx:] if start_idx < len(sorted_bps) else []
    if not scan_bps:
        return set()

    def _looks_like_index_line(line: str) -> bool:
        normalized_line = line.strip()
        if not normalized_line:
            return False
        if not re.match(r"^[A-Za-zÀ-ÿ\u4e00-\u9fff]", normalized_line):
            return False
        if "," not in normalized_line and "，" not in normalized_line:
            return False
        nums = re.findall(r"\d+", normalized_line)
        return len(nums) >= 2

    stats_by_bp: dict[int, tuple[int, int, float]] = {}
    for bp in scan_bps:
        raw = ensure_str(page_texts.get(bp))
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            continue
        numeric_lines = [line for line in lines if re.search(r"\d", line)]
        if not numeric_lines:
            continue
        index_hits = sum(1 for line in numeric_lines if _looks_like_index_line(line))
        ratio = index_hits / max(len(numeric_lines), 1)
        stats_by_bp[bp] = (index_hits, len(numeric_lines), ratio)

    strong_hits = {
        bp for bp, (hits, _num_count, ratio) in stats_by_bp.items() if hits >= 5 and ratio >= 0.4
    }
    hit_bps: set[int] = set(strong_hits)
    if strong_hits:
        for bp, (hits, _num_count, ratio) in stats_by_bp.items():
            if bp in hit_bps:
                continue
            if hits >= 5 and ratio >= 0.22 and any(abs(bp - strong_bp) <= 2 for strong_bp in strong_hits):
                hit_bps.add(bp)
        for bp, (hits, _num_count, ratio) in stats_by_bp.items():
            if bp in hit_bps:
                continue
            if hits >= 4 and ratio >= 0.18 and any(abs(bp - hit_bp) <= 1 for hit_bp in hit_bps):
                hit_bps.add(bp)
    return hit_bps

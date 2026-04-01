"""自动视觉目录：候选页扫描、视觉能力预检与目录抽取。"""

from __future__ import annotations

import base64
import json
import os
import re
import struct
import unicodedata
import zlib

from openai import OpenAI

from config import update_doc_meta
from pdf_extract import (
    extract_pdf_page_link_targets,
    read_pdf_page_labels,
    render_pdf_page,
)
from sqlite_store import (
    SQLiteRepository,
    TOC_SOURCE_AUTO_VISUAL,
    TOC_SOURCE_USER,
)
from storage import load_pages_from_disk, load_user_toc_from_disk, resolve_model_spec, resolve_page_print_label


_VISION_PREFLIGHT_CACHE: dict[tuple[str, str, str], tuple[bool, str]] = {}
_TOC_CONTAINER_RE = re.compile(
    r"^(?:"
    r"table|table of contents|table des mati[eè]res|contents?|sommaire|toc|"
    r"目录|目錄|目次|목차|차례|"
    r"inhalt|inhaltsverzeichnis|"
    r"[ií]ndice|contenido|sum[aá]rio|sommario|"
    r"содержание|оглавление|"
    r"inhoud|inhoudsopgave|"
    r"المحتويات|الفهرس|"
    r"index"
    r")$",
    re.IGNORECASE,
)
_SENTENCE_PUNCT_RE = re.compile(r"[.:;!?]")
_TOC_HEADER_HINT_PATTERNS = (
    re.compile(r"^(?:table|table of contents|table des matieres?)$", re.IGNORECASE),
    re.compile(r"^(?:contents?|toc)$", re.IGNORECASE),
    re.compile(r"^(?:目录|目錄|目次)$"),
    re.compile(r"^(?:목차|차례)$"),
    re.compile(r"^(?:sommaire)$", re.IGNORECASE),
    re.compile(r"^(?:inhalt|inhaltsverzeichnis)$", re.IGNORECASE),
    re.compile(r"^(?:indice|indice\.|indice general|contenido|sumario|sommario)$", re.IGNORECASE),
    re.compile(r"^(?:содержание|оглавление)$", re.IGNORECASE),
    re.compile(r"^(?:inhoud|inhoudsopgave)$", re.IGNORECASE),
    re.compile(r"^(?:المحتويات|الفهرس)$"),
)
_INDEX_HEADER_HINT_PATTERNS = (
    re.compile(r"^(?:index|index of names|index of subjects|index nominum|index rerum)\b", re.IGNORECASE),
    re.compile(r"^(?:index des notions|index des noms|index des matieres)\b", re.IGNORECASE),
    re.compile(r"^(?:indices)$", re.IGNORECASE),
)
_BACKMATTER_HEADER_HINT_PATTERNS = (
    re.compile(r"^(?:notes?|bibliograph(?:y|ie)|references?|appendi(?:x|ces))$", re.IGNORECASE),
)
_TOC_TEXT_KEYWORD_PATTERNS = (
    re.compile(r"\btable of contents\b", re.IGNORECASE),
    re.compile(r"\bcontents?\b", re.IGNORECASE),
    re.compile(r"\btable des matieres?\b", re.IGNORECASE),
    re.compile(r"\bsommaire\b", re.IGNORECASE),
    re.compile(r"(?:目录|目錄|目次|목차|차례)"),
    re.compile(r"\b(?:inhalt|inhaltsverzeichnis)\b", re.IGNORECASE),
    re.compile(r"\b(?:indice|contenido|sumario|sommario)\b", re.IGNORECASE),
    re.compile(r"(?:содержание|оглавление)", re.IGNORECASE),
    re.compile(r"\b(?:inhoud|inhoudsopgave)\b", re.IGNORECASE),
    re.compile(r"(?:المحتويات|الفهرس)"),
)
_INDEX_TEXT_KEYWORD_PATTERNS = (
    re.compile(r"\bindex\b", re.IGNORECASE),
    re.compile(r"\bindices\b", re.IGNORECASE),
    re.compile(r"\bindex des notions\b", re.IGNORECASE),
    re.compile(r"\bindex des noms\b", re.IGNORECASE),
    re.compile(r"\bindex nominum\b", re.IGNORECASE),
)
_TOC_DOT_LEADER_RE = re.compile(r"\.{2,}\s*(?:\d+|[ivxlcdm]{1,10})\s*$", re.IGNORECASE)
_TOC_TRAILING_PAGE_RE = re.compile(r"(?:\s|\.{2,})(?:\d+|[ivxlcdm]{1,10})\s*$", re.IGNORECASE)
_LOCAL_VISUAL_SCAN_MAX_PAGES = 8


def _slugify_visual_toc_title(text: str) -> str:
    normalized = _fold_header_hint(text)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or "item"


def _set_visual_toc_progress(
    doc_id: str,
    *,
    status: str,
    phase: str,
    pct: int,
    label: str,
    detail: str,
    message: str = "",
    model_id: str = "",
) -> None:
    update_doc_meta(
        doc_id,
        toc_visual_status=str(status or "idle").strip() or "idle",
        toc_visual_phase=str(phase or "").strip(),
        toc_visual_progress_pct=max(0, min(100, int(pct or 0))),
        toc_visual_progress_label=str(label or ""),
        toc_visual_progress_detail=str(detail or ""),
        toc_visual_message=str(message or ""),
        toc_visual_model_id=str(model_id or ""),
    )


def choose_toc_candidate_indices(total_pages: int) -> tuple[list[int], list[int]]:
    """给出书首和书尾的候选扫描页。"""
    total = max(0, int(total_pages or 0))
    if total <= 0:
        return ([], [])
    scan_count = min(24, max(8, int(round(total * 0.15))))
    front = list(range(min(total, scan_count)))
    back_start = max(0, total - scan_count)
    back = list(range(back_start, total))
    if front and back and back[0] <= front[-1]:
        back = [idx for idx in back if idx > front[-1]]
    return (front, back)


def pick_best_toc_cluster(front_results: list[dict], back_results: list[dict]) -> list[dict]:
    """从书首和书尾的候选页分类结果中选出最稳定的一簇目录页。"""

    def _clusters(results: list[dict]) -> list[list[dict]]:
        ordered = sorted(results or [], key=lambda item: int(item.get("file_idx", -1)))
        clusters: list[list[dict]] = []
        current: list[dict] = []
        for item in ordered:
            label = str(item.get("label", "") or "").strip().lower()
            score = float(item.get("score", item.get("confidence", 0)) or 0)
            if label not in {"toc_start", "toc_continue"} or score < 0.55:
                if current:
                    clusters.append(current)
                    current = []
                continue
            if current and int(item.get("file_idx", -999)) - int(current[-1].get("file_idx", -999)) > 1:
                clusters.append(current)
                current = []
            current.append(item)
        if current:
            clusters.append(current)
        return clusters

    def _score(cluster: list[dict]) -> float:
        score = sum(float(item.get("score", item.get("confidence", 0)) or 0) for item in cluster)
        score += 0.15 * len(cluster)
        if any(str(item.get("label", "")).strip().lower() == "toc_start" for item in cluster):
            score += 0.4
        header_roles = [_classify_header_hint(item.get("header_hint")) for item in cluster]
        score += 1.6 * sum(1 for role in header_roles if role == "toc")
        score -= 1.8 * sum(1 for role in header_roles if role == "index")
        first_role = header_roles[0] if header_roles else "other"
        if first_role == "toc":
            score += 1.2
        elif first_role == "index":
            score -= 1.4
        return score

    candidates = _clusters(front_results) + _clusters(back_results)
    if not candidates:
        return []
    return max(
        candidates,
        key=lambda cluster: (
            _score(cluster),
            sum(1 for item in cluster if _classify_header_hint(item.get("header_hint")) == "toc"),
            -sum(1 for item in cluster if _classify_header_hint(item.get("header_hint")) == "index"),
            len(cluster),
            -int(cluster[0].get("file_idx", 0)),
        ),
    )


def filter_visual_toc_items(items: list[dict]) -> list[dict]:
    """过滤目录容器标题与 Biopolitique 一类的摘要说明块。"""
    filtered: list[dict] = []
    for index, item in enumerate(items or [], start=1):
        title = re.sub(r"\s+", " ", str(item.get("title", "") or "")).strip()
        if not title:
            continue
        printed_page = _coerce_positive_int(item.get("printed_page"))
        file_idx = _coerce_nonnegative_int(item.get("file_idx"))
        if _TOC_CONTAINER_RE.match(title) and printed_page is None and file_idx is None:
            continue
        if file_idx is None and printed_page is None and _looks_like_summary_text(title):
            continue
        filtered.append(
            {
                "title": title,
                "depth": max(0, int(item.get("depth", 0) or 0)),
                "printed_page": printed_page,
                "file_idx": file_idx,
                "visual_order": max(1, int(item.get("visual_order", index) or index)),
            }
        )
    return filtered


def map_visual_items_to_link_targets(items: list[dict], link_targets: list[dict]) -> list[dict]:
    """对没有页码的目录项，按视觉顺序对齐 PDF 内链目标页。"""
    order_map = {
        max(1, int(target.get("visual_order", 0) or 0)): int(target.get("target_file_idx"))
        for target in (link_targets or [])
        if target.get("target_file_idx") is not None
    }
    mapped: list[dict] = []
    for index, item in enumerate(items or [], start=1):
        clone = dict(item)
        visual_order = max(1, int(clone.get("visual_order", index) or index))
        if clone.get("file_idx") is None and visual_order in order_map:
            clone["file_idx"] = order_map[visual_order]
        mapped.append(clone)
    return mapped


def generate_auto_visual_toc_for_doc(doc_id: str, *, pdf_path: str, model_spec=None) -> dict:
    """为指定文档生成自动视觉目录。"""
    if not doc_id or not pdf_path or not os.path.exists(pdf_path):
        _set_visual_toc_progress(
            doc_id,
            status="failed",
            phase="failed",
            pct=0,
            label="自动视觉目录失败",
            detail="未找到源 PDF，无法生成自动视觉目录。",
            message="未找到源 PDF，无法生成自动视觉目录。",
        )
        return {"status": "failed", "count": 0}

    spec = model_spec or resolve_model_spec()
    model_id = str(getattr(spec, "model_id", "") or "").strip()
    repo = SQLiteRepository()
    repo.set_document_toc_for_source(doc_id, TOC_SOURCE_AUTO_VISUAL, [])
    _set_visual_toc_progress(
        doc_id,
        status="running",
        phase="confirming_model",
        pct=5,
        label="模型视觉能力确认",
        detail="正在确认当前模型是否支持视觉识别…",
        message="正在确认模型视觉能力…",
        model_id=model_id,
    )

    supported, support_message = confirm_model_supports_vision(spec)
    if not supported:
        _set_visual_toc_progress(
            doc_id,
            status="unsupported",
            phase="unsupported",
            pct=100,
            label="自动视觉目录不可用",
            detail=support_message,
            message=support_message,
            model_id=model_id,
        )
        return {"status": "unsupported", "count": 0}

    total_pages = _resolve_total_pages(pdf_path)
    if total_pages <= 0:
        _set_visual_toc_progress(
            doc_id,
            status="failed",
            phase="failed",
            pct=100,
            label="自动视觉目录失败",
            detail="无法读取 PDF 页数，自动视觉目录已跳过。",
            message="无法读取 PDF 页数，自动视觉目录已跳过。",
            model_id=model_id,
        )
        return {"status": "failed", "count": 0}

    _set_visual_toc_progress(
        doc_id,
        status="running",
        phase="local_candidate_scan",
        pct=18,
        label="本地候选扫描",
        detail=f"正在本地扫描目录候选页（共 {total_pages} 页）",
        message="正在本地扫描目录候选页…",
        model_id=model_id,
    )
    candidate_indices = _choose_local_toc_scan_indices(
        _extract_local_toc_page_features(pdf_path, total_pages),
        max_pages=_LOCAL_VISUAL_SCAN_MAX_PAGES,
    )
    if not candidate_indices:
        front_indices, back_indices = choose_toc_candidate_indices(total_pages)
        candidate_indices = sorted(set(front_indices[:4] + back_indices[-4:]))
    _set_visual_toc_progress(
        doc_id,
        status="running",
        phase="visual_review",
        pct=34,
        label="候选页视觉复核",
        detail=f"将复核 {len(candidate_indices)} 页目录候选页",
        message="正在视觉复核目录候选页…",
        model_id=model_id,
    )
    classified_results = _classify_toc_candidates(spec, pdf_path, candidate_indices)
    best_cluster = pick_best_toc_cluster([], classified_results)
    if not best_cluster:
        _set_visual_toc_progress(
            doc_id,
            status="failed",
            phase="failed",
            pct=100,
            label="自动视觉目录失败",
            detail="未找到稳定的目录页，已回退到现有目录来源。",
            message="未找到稳定的目录页，已回退到现有目录来源。",
            model_id=model_id,
        )
        return {"status": "failed", "count": 0}

    printed_page_lookup = _build_printed_page_lookup(doc_id, pdf_path)
    resolved_items: list[dict] = []
    unresolved_items = 0

    _set_visual_toc_progress(
        doc_id,
        status="running",
        phase="extracting_items",
        pct=50,
        label="目录项抽取",
        detail=f"正在抽取 {len(best_cluster)} 页目录项",
        message="正在抽取目录项…",
        model_id=model_id,
    )
    for page_index, page_result in enumerate(best_cluster, start=1):
        file_idx = int(page_result.get("file_idx", -1) or -1)
        if file_idx < 0:
            continue
        page_items = _extract_visual_toc_page_items(spec, pdf_path, file_idx)
        page_items = filter_visual_toc_items(page_items)
        page_items = _apply_printed_page_lookup(page_items, printed_page_lookup)
        page_items = map_visual_items_to_link_targets(
            page_items,
            extract_pdf_page_link_targets(pdf_path, file_idx),
        )
        _set_visual_toc_progress(
            doc_id,
            status="running",
            phase="mapping_targets",
            pct=min(82, 50 + int(page_index / max(1, len(best_cluster)) * 32)),
            label="页码/链接映射",
            detail=f"正在处理目录页 {page_index}/{len(best_cluster)}",
            message="正在映射目录页和目标页…",
            model_id=model_id,
        )
        for item in page_items:
            visual_order = max(1, int(item.get("visual_order", len(resolved_items) + 1) or len(resolved_items) + 1))
            normalized = {
                "title": item["title"],
                "depth": max(0, int(item.get("depth", 0) or 0)),
                "visual_order": visual_order,
                "item_id": f"visual-{file_idx}-{visual_order}-{_slugify_visual_toc_title(item['title'])[:24]}",
            }
            file_target = _coerce_nonnegative_int(item.get("file_idx"))
            printed_page = _coerce_positive_int(item.get("printed_page"))
            if file_target is not None:
                normalized["file_idx"] = file_target
            elif printed_page is not None:
                normalized["book_page"] = printed_page
                unresolved_items += 1
            else:
                continue
            resolved_items.append(normalized)

    resolved_items = _dedupe_toc_items(resolved_items)
    repo.set_document_toc_for_source(doc_id, TOC_SOURCE_AUTO_VISUAL, resolved_items)
    if not load_user_toc_from_disk(doc_id):
        repo.set_document_toc_source_offset(doc_id, TOC_SOURCE_AUTO_VISUAL, 0)

    if not resolved_items:
        _set_visual_toc_progress(
            doc_id,
            status="failed",
            phase="failed",
            pct=100,
            label="自动视觉目录失败",
            detail="目录页已找到，但没有抽取到稳定的目录条目。",
            message="目录页已找到，但没有抽取到稳定的目录条目。",
            model_id=model_id,
        )
        return {"status": "failed", "count": 0}

    ready_count = sum(1 for item in resolved_items if item.get("file_idx") is not None)
    if ready_count == len(resolved_items):
        _set_visual_toc_progress(
            doc_id,
            status="ready",
            phase="completed",
            pct=100,
            label="自动视觉目录已生成",
            detail=f"已生成 {len(resolved_items)} 条自动视觉目录。",
            message=f"已生成 {len(resolved_items)} 条自动视觉目录。",
            model_id=model_id,
        )
        return {"status": "ready", "count": len(resolved_items)}

    _set_visual_toc_progress(
        doc_id,
        status="needs_offset",
        phase="completed",
        pct=100,
        label="自动视觉目录已加载，仍需校准",
        detail=f"已识别 {len(resolved_items)} 条目录，但仍有 {unresolved_items} 条无法稳定定位到 PDF 页。",
        message=f"已识别 {len(resolved_items)} 条目录，但仍有 {unresolved_items} 条无法稳定定位到 PDF 页。",
        model_id=model_id,
    )
    return {"status": "needs_offset", "count": len(resolved_items)}


def confirm_model_supports_vision(spec) -> tuple[bool, str]:
    """对当前模型做一次真实视觉预检，并缓存结果。"""
    key = (
        str(getattr(spec, "provider", "") or "").strip(),
        str(getattr(spec, "base_url", "") or "").strip(),
        str(getattr(spec, "model_id", "") or "").strip(),
    )
    if key in _VISION_PREFLIGHT_CACHE:
        return _VISION_PREFLIGHT_CACHE[key]

    api_key = str(getattr(spec, "api_key", "") or "").strip()
    if not api_key:
        result = (False, "当前模型没有可用的 API Key，无法进行视觉目录识别。")
        _VISION_PREFLIGHT_CACHE[key] = result
        return result

    prompt = (
        "这是一个 4x4 黑白方格测试图。"
        "请数出每一行黑色方格的数量，只返回 JSON 对象。"
        '格式必须是 {"row_counts":[1,3,0,2],"supports_vision":true}。'
    )
    try:
        parsed = _call_vision_json(
            spec,
            prompt=prompt,
            images=[_build_vision_probe_data_url()],
            max_tokens=240,
        )
    except Exception as exc:
        result = (False, f"当前模型未通过视觉预检：{exc}")
        _VISION_PREFLIGHT_CACHE[key] = result
        return result

    row_counts = parsed.get("row_counts")
    if _vision_probe_passed(row_counts, parsed.get("supports_vision")):
        result = (True, "已确认当前模型支持视觉识别。")
    else:
        result = (False, "当前模型未通过视觉预检，已跳过自动视觉目录。")
    _VISION_PREFLIGHT_CACHE[key] = result
    return result


def _resolve_total_pages(pdf_path: str) -> int:
    labels = read_pdf_page_labels(pdf_path)
    if labels:
        return len(labels)
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        return len(reader.pages)
    except Exception:
        return 0


def _coerce_positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_nonnegative_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _looks_like_summary_text(title: str) -> bool:
    text = str(title or "").strip()
    if not text:
        return False
    words = re.findall(r"\S+", text)
    if len(words) >= 18:
        return True
    if len(text) >= 120:
        return True
    if len(words) >= 12 and _SENTENCE_PUNCT_RE.search(text):
        return True
    return False


def _normalize_header_hint(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _fold_header_hint(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", _normalize_header_hint(text))
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def _matches_any_header_pattern(patterns, raw_text: str, folded_text: str) -> bool:
    return any(pattern.match(raw_text) or pattern.match(folded_text) for pattern in patterns)


def _classify_header_hint(text: str) -> str:
    raw_text = _normalize_header_hint(text)
    if not raw_text:
        return "other"
    folded_text = _fold_header_hint(raw_text)
    lowered_text = raw_text.lower()
    if _matches_any_header_pattern(_TOC_HEADER_HINT_PATTERNS, lowered_text, folded_text):
        return "toc"
    if _matches_any_header_pattern(_INDEX_HEADER_HINT_PATTERNS, lowered_text, folded_text):
        return "index"
    if _matches_any_header_pattern(_BACKMATTER_HEADER_HINT_PATTERNS, lowered_text, folded_text):
        return "other"
    return "other"


def _classify_text_excerpt(text: str) -> str:
    raw_text = _normalize_header_hint(text)
    if not raw_text:
        return "other"
    folded_text = _fold_header_hint(raw_text)
    lowered_text = raw_text.lower()
    if _matches_any_header_pattern(_TOC_TEXT_KEYWORD_PATTERNS, lowered_text, folded_text):
        return "toc"
    if _matches_any_header_pattern(_INDEX_TEXT_KEYWORD_PATTERNS, lowered_text, folded_text):
        return "index"
    return "other"


def _score_local_toc_page(feature: dict) -> float:
    header_role = _classify_header_hint(feature.get("header_hint"))
    text_role = _classify_text_excerpt(feature.get("text_excerpt"))
    link_count = max(0, int(feature.get("link_count", 0) or 0))
    dot_leader_lines = max(0, int(feature.get("dot_leader_lines", 0) or 0))
    numbered_lines = max(0, int(feature.get("numbered_lines", 0) or 0))

    score = 0.0
    if header_role == "toc":
        score += 6.0
    elif header_role == "index":
        score -= 7.0

    if text_role == "toc":
        score += 2.5
    elif text_role == "index":
        score -= 3.5

    score += min(link_count, 12) * 0.35
    if dot_leader_lines >= 3:
        score += 1.5
    elif dot_leader_lines >= 1:
        score += 0.6
    if numbered_lines >= 4:
        score += 1.0
    elif numbered_lines >= 2:
        score += 0.5

    if header_role == "other" and text_role == "other" and link_count == 0 and dot_leader_lines == 0 and numbered_lines == 0:
        score -= 0.5
    return score


def _choose_local_toc_scan_indices(page_features: list[dict], max_pages: int = _LOCAL_VISUAL_SCAN_MAX_PAGES) -> list[int]:
    if not page_features:
        return []
    enriched = []
    for item in sorted(page_features, key=lambda page: int(page.get("file_idx", -1))):
        clone = dict(item)
        clone["local_score"] = _score_local_toc_page(clone)
        clone["header_role"] = _classify_header_hint(clone.get("header_hint"))
        enriched.append(clone)

    def _cluster_score(cluster: list[dict]) -> tuple[float, int, int, int]:
        return (
            sum(float(item.get("local_score", 0) or 0) for item in cluster),
            sum(1 for item in cluster if item.get("header_role") == "toc"),
            -sum(1 for item in cluster if item.get("header_role") == "index"),
            len(cluster),
        )

    anchor_ranges: list[tuple[int, int]] = []
    current_anchors: list[dict] = []
    for item in enriched:
        is_anchor = item.get("header_role") == "toc" or float(item.get("local_score", 0) or 0) >= 4.0
        if not is_anchor:
            continue
        if current_anchors and int(item.get("file_idx", -999)) - int(current_anchors[-1].get("file_idx", -999)) > 2:
            anchor_ranges.append(
                (
                    int(current_anchors[0].get("file_idx", -1)),
                    int(current_anchors[-1].get("file_idx", -1)),
                )
            )
            current_anchors = []
        current_anchors.append(item)
    if current_anchors:
        anchor_ranges.append(
            (
                int(current_anchors[0].get("file_idx", -1)),
                int(current_anchors[-1].get("file_idx", -1)),
            )
        )

    anchor_clusters = [
        [
            item for item in enriched
            if start_file_idx <= int(item.get("file_idx", -1)) <= end_file_idx and item.get("header_role") != "index"
        ]
        for start_file_idx, end_file_idx in anchor_ranges
    ]
    anchor_clusters = [cluster for cluster in anchor_clusters if cluster]
    if anchor_clusters:
        best_cluster = max(anchor_clusters, key=_cluster_score)
        file_indices = [int(item["file_idx"]) for item in best_cluster]
        if len(file_indices) <= max_pages:
            return file_indices
        first_toc_pos = next((index for index, item in enumerate(best_cluster) if item.get("header_role") == "toc"), 0)
        start = min(first_toc_pos, max(0, len(file_indices) - max_pages))
        return file_indices[start:start + max_pages]

    clusters: list[list[dict]] = []
    current: list[dict] = []
    has_anchor = False
    for item in enriched:
        score = float(item.get("local_score", 0) or 0)
        header_role = str(item.get("header_role", "other") or "other")
        is_candidate = score >= 1.5
        is_anchor = header_role == "toc" or score >= 3.0
        if not is_candidate:
            if current and has_anchor:
                clusters.append(current)
            current = []
            has_anchor = False
            continue
        if current and int(item.get("file_idx", -999)) - int(current[-1].get("file_idx", -999)) > 1:
            if has_anchor:
                clusters.append(current)
            current = []
            has_anchor = False
        current.append(item)
        has_anchor = has_anchor or is_anchor
    if current and has_anchor:
        clusters.append(current)

    if not clusters:
        fallbacks = [item for item in enriched if float(item.get("local_score", 0) or 0) > 0]
        return [int(item["file_idx"]) for item in fallbacks[:max_pages]]

    best_cluster = max(clusters, key=_cluster_score)
    file_indices = [int(item["file_idx"]) for item in best_cluster]
    if len(file_indices) <= max_pages:
        return file_indices

    first_toc_pos = next((index for index, item in enumerate(best_cluster) if item.get("header_role") == "toc"), 0)
    start = min(first_toc_pos, max(0, len(file_indices) - max_pages))
    return file_indices[start:start + max_pages]


def _extract_local_toc_page_features(pdf_path: str, total_pages: int) -> list[dict]:
    del total_pages  # 本地预筛选直接扫整本 PDF，不依赖外部页数参数。
    try:
        import fitz
    except Exception:
        return []

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return []

    features: list[dict] = []
    try:
        for file_idx in range(len(doc)):
            page = doc[file_idx]
            raw_text = page.get_text("text") or ""
            lines = [_normalize_header_hint(line) for line in raw_text.splitlines()]
            lines = [line for line in lines if line]
            excerpt_lines = lines[:24]
            internal_links = [
                link for link in page.get_links()
                if link.get("kind") == 1 and link.get("page") is not None and int(link.get("page")) >= 0
            ]
            dot_leader_lines = sum(1 for line in excerpt_lines if _TOC_DOT_LEADER_RE.search(line))
            numbered_lines = sum(1 for line in excerpt_lines if _TOC_TRAILING_PAGE_RE.search(line))
            features.append(
                {
                    "file_idx": file_idx,
                    "header_hint": lines[0] if lines else "",
                    "text_excerpt": "\n".join(excerpt_lines[:12]),
                    "link_count": len(internal_links),
                    "dot_leader_lines": dot_leader_lines,
                    "numbered_lines": numbered_lines,
                }
            )
    finally:
        doc.close()
    return features


def _vision_probe_passed(row_counts, supports_vision_flag) -> bool:
    if supports_vision_flag is not True:
        return False
    if not isinstance(row_counts, list) or len(row_counts) != 4:
        return False
    try:
        values = [int(value) for value in row_counts]
    except (TypeError, ValueError):
        return False
    # 探针图的关键关系：
    # 第 3 行没有黑块；第 2 行明显多于第 1 行；第 4 行也有黑块。
    return (
        values[2] == 0
        and values[0] >= 1
        and values[1] > values[0]
        and values[3] >= 1
    )


def _dedupe_toc_items(items: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for item in items or []:
        key = (
            re.sub(r"\s+", " ", str(item.get("title", "") or "")).strip().lower(),
            int(item.get("depth", 0) or 0),
            item.get("file_idx"),
            item.get("book_page"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _build_printed_page_lookup(doc_id: str, pdf_path: str) -> dict[int, int]:
    lookup: dict[int, int] = {}
    pages, _ = load_pages_from_disk(doc_id)
    for page in pages or []:
        label = resolve_page_print_label(page)
        if label.isdigit():
            printed_page = int(label)
            if printed_page > 0 and printed_page not in lookup:
                lookup[printed_page] = int(page.get("fileIdx", max(int(page.get("bookPage", 1)) - 1, 0)) or 0)
    if lookup:
        return lookup
    for file_idx, label in enumerate(read_pdf_page_labels(pdf_path)):
        if label.isdigit():
            printed_page = int(label)
            if printed_page > 0 and printed_page not in lookup:
                lookup[printed_page] = file_idx
    return lookup


def _apply_printed_page_lookup(items: list[dict], printed_page_lookup: dict[int, int]) -> list[dict]:
    resolved: list[dict] = []
    for item in items or []:
        clone = dict(item)
        printed_page = _coerce_positive_int(clone.get("printed_page"))
        if clone.get("file_idx") is None and printed_page in printed_page_lookup:
            clone["file_idx"] = printed_page_lookup[printed_page]
        resolved.append(clone)
    return resolved


def _classify_toc_candidates(spec, pdf_path: str, page_indices: list[int]) -> list[dict]:
    if not page_indices:
        return []
    batch_size = 4
    results: list[dict] = []
    for start in range(0, len(page_indices), batch_size):
        batch = page_indices[start:start + batch_size]
        prompt = (
            "你会依次看到若干 PDF 页面截图。"
            "请判断每张图是否是书籍目录页。"
            "常见目录标题包括：Contents、Table of Contents、Table、目录、目錄、目次、목차、차례、"
            "Sommaire、Table des matieres、Inhalt、Inhaltsverzeichnis、Indice、Índice、Contenido、"
            "Sumario、Sumário、Sommario、Содержание、Оглавление、Inhoud、Inhoudsopgave、المحتويات、الفهرس。"
            "特别注意：法语 Sommaire 常在书前，Table des matieres 常在书后；"
            "西班牙语/葡萄牙语/意大利语里的 Indice 往往是目录，不要和英语 Index 混淆；"
            "英语或法语语境下的 Index、Indices、Index des notions、Notes、Bibliography 都不是目录。"
            "如果页顶只有一个很大的 Table，也要把它视作强目录提示。"
            "返回 JSON 数组，每项格式为 "
            '[{"file_idx":12,"label":"not_toc|toc_start|toc_continue","score":0.0,"header_hint":"Table des matières"}]'
            "，顺序与输入一致。header_hint 必须是页顶最显眼的大标题，没有就返回空字符串。"
        )
        images = []
        for file_idx in batch:
            images.append((file_idx, _bytes_to_data_url(render_pdf_page(pdf_path, file_idx, scale=0.9))))
        try:
            parsed = _call_vision_json(spec, prompt=prompt, images=images, max_tokens=900)
        except Exception:
            parsed = []
        parsed_list = parsed if isinstance(parsed, list) else []
        by_file_idx = {
            int(item.get("file_idx")): item
            for item in parsed_list
            if item.get("file_idx") is not None
        }
        for file_idx in batch:
            item = by_file_idx.get(file_idx, {})
            results.append(
                {
                    "file_idx": file_idx,
                    "label": str(item.get("label", "not_toc") or "not_toc").strip().lower(),
                    "score": float(item.get("score", item.get("confidence", 0)) or 0),
                    "header_hint": _normalize_header_hint(item.get("header_hint")),
                }
            )
    return results


def _extract_visual_toc_page_items(spec, pdf_path: str, file_idx: int) -> list[dict]:
    prompt = (
        "你会看到一页书籍目录截图。"
        "请只提取真正可导航的目录项，并按从上到下的顺序返回 JSON 数组。"
        "每项格式必须是 "
        '[{"title":"章节标题","depth":0,"printed_page":12,"visual_order":1}]。'
        "规则："
        "1. depth 只能根据视觉缩进、字号、对齐和编号层级判断；"
        "2. 容器标题如 Contents、Sommaire、Table des matieres 不能输出；"
        "3. 标题下面很长的摘要、说明文字、介绍段落不能输出；"
        "4. 没有可见页码就把 printed_page 设为 null；"
        "5. 不要补全不可见文字，只做空白归一化。"
    )
    try:
        parsed = _call_vision_json(
            spec,
            prompt=prompt,
            images=[_bytes_to_data_url(render_pdf_page(pdf_path, file_idx, scale=2.0))],
            max_tokens=2200,
        )
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _call_vision_json(spec, *, prompt: str, images: list, max_tokens: int = 1200):
    client = OpenAI(
        api_key=str(getattr(spec, "api_key", "") or "").strip(),
        base_url=str(getattr(spec, "base_url", "") or "").strip(),
    )
    content = [{"type": "text", "text": prompt}]
    for index, image in enumerate(images, start=1):
        if isinstance(image, tuple):
            file_idx, data_url = image
            content.append({"type": "text", "text": f"页面 file_idx={file_idx}"})
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        else:
            content.append({"type": "image_url", "image_url": {"url": image}})
    create_kwargs = {
        "model": str(getattr(spec, "model_id", "") or "").strip(),
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    request_overrides = getattr(spec, "request_overrides", None)
    if isinstance(request_overrides, dict):
        create_kwargs.update(request_overrides)
    response = client.chat.completions.create(**create_kwargs)
    text = _extract_message_text(response)
    return _parse_json_payload(text)


def _extract_message_text(response) -> str:
    if not getattr(response, "choices", None):
        return ""
    message = getattr(response.choices[0], "message", None)
    if message is None:
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text", "")
            else:
                text = getattr(item, "text", "")
            if text:
                parts.append(str(text))
        return "".join(parts)
    return str(content or "")


def _parse_json_payload(text: str):
    raw = re.sub(r"```json\s*", "", str(text or ""))
    raw = re.sub(r"```\s*", "", raw).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass

    for open_char, close_char in (("{", "}"), ("[", "]")):
        depth = 0
        start = -1
        end = -1
        for index, char in enumerate(raw):
            if char == open_char:
                if depth == 0:
                    start = index
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0 and start >= 0:
                    end = index
                    break
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                continue
    raise ValueError("视觉模型返回的不是有效 JSON")


def _bytes_to_data_url(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _build_vision_probe_data_url() -> str:
    pattern = [
        [1, 0, 0, 0],
        [1, 1, 1, 0],
        [0, 0, 0, 0],
        [1, 0, 1, 0],
    ]
    cell_size = 24
    width = len(pattern[0]) * cell_size
    height = len(pattern) * cell_size
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        row_idx = y // cell_size
        for x in range(width):
            col_idx = x // cell_size
            is_black = bool(pattern[row_idx][col_idx])
            rows.extend((0, 0, 0) if is_black else (255, 255, 255))
    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    compressed = zlib.compress(bytes(rows), level=9)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )
    return _bytes_to_data_url(png)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack("!I", len(data))
        + tag
        + data
        + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )

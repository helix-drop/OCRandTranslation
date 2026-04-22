"""visual TOC 主编排与落盘。"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import struct
import tempfile
import time
import unicodedata
import zlib

from openai import OpenAI

from config import update_doc_meta
from document.pdf_extract import (
    extract_pdf_page_link_targets,
    read_pdf_page_labels,
    render_pdf_page,
)
from document.text_layer_fixer import detect_and_fix_text, detect_garbled_text
from persistence.sqlite_store import (
    SQLiteRepository,
    TOC_SOURCE_AUTO_VISUAL,
    TOC_SOURCE_USER,
)
from persistence.storage_toc import (
    clear_auto_visual_toc_bundle_from_disk,
    save_auto_visual_toc_bundle_to_disk,
)
from persistence.storage import (
    load_pages_from_disk,
    load_toc_visual_manual_inputs,
    load_user_toc_from_disk,
    resolve_page_print_label,
    resolve_visual_model_spec,
)

logger = logging.getLogger(__name__)


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
_FRONTMATTER_TITLE_PATTERNS = (
    re.compile(r"^(?:introduction|intro)\b", re.IGNORECASE),
    re.compile(r"^(?:acknowledg(?:e)?ments?)\b", re.IGNORECASE),
    re.compile(r"^(?:preface|foreword|prologue)\b", re.IGNORECASE),
    re.compile(r"^(?:avant-propos|avant propos|prelude)\b", re.IGNORECASE),
)
_NOTES_RANGE_TITLE_PATTERNS = (
    re.compile(r"^notes?\s+to\s+pages?\s+\d+\s*[-–]\s*\d+$", re.IGNORECASE),
    re.compile(r"^notes?\s+to\s+(?:pp?|pages?)\.?\s*\d+\s*[-–]\s*\d+$", re.IGNORECASE),
    re.compile(r"^notes?\s+on\s+sources?$", re.IGNORECASE),
    re.compile(r"^note\s+on\s+sources?$", re.IGNORECASE),
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
_LOCAL_VISUAL_SCAN_MAX_PAGES = 24
_TEXT_LAYER_MIN_SAMPLE_CHARS = 160
_TEXT_LAYER_DEGRADED_CONTROL_CHAR_RATIO = 0.12
_TEXT_LAYER_DEGRADED_REPLACEMENT_CHAR_RATIO = 0.02
_VISUAL_RETRY_NEIGHBOR_RADIUS = 1
_VISUAL_RETRY_MAX_EXTRA_PAGES = 8
_MAX_PRIMARY_RUNS = 3
_MAX_VISUAL_TOC_PAGES_TOTAL = 24
_MAX_VISUAL_TOC_PAGES_PER_RUN = 12
_CONTEXT_PAGES_PER_RUN_SIDE = 1
_DEGRADED_FRONT_WINDOW = 6
_DEGRADED_BACK_WINDOW = 12
_DEGRADED_EXPAND_STEP = 4
_DEGRADED_MAX_EXPAND_ROUNDS = 2
_VISUAL_TOC_ROLE_VALUES = {
    "container",
    "endnotes",
    "chapter",
    "section",
    "post_body",
    "back_matter",
    "front_matter",
}
_VISUAL_TOC_ROLE_ALIASES = {
    "part": "container",
    "book": "container",
    "course": "container",
    "cours": "container",
    "appendices": "container",
    "indices": "container",
    "notes": "endnotes",
    "endnote": "endnotes",
    "frontmatter": "front_matter",
    "backmatter": "back_matter",
    "postbody": "post_body",
    "book_title": "front_matter",
}
_VISUAL_TOC_CONTAINER_TITLE_RE = re.compile(
    r"^\s*(?:part|partie|livre|book|section)\s+(?:[ivxlcm]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"premi[eè]re?|deuxi[eè]me|troisi[eè]me|quatri[eè]me|cinqui[eè]me|sixi[eè]me|septi[eè]me|huiti[eè]me|neuvi[eè]me|dixi[eè]me)\b|"
    r"^\s*cours,\s*ann[eé]e\b|"
    r"^\s*appendices\b|"
    r"^\s*indices\b",
    re.IGNORECASE,
)
_VISUAL_TOC_POST_BODY_TITLE_RE = re.compile(
    r"^\s*(?:r[eé]sum[eé](?:\s+du\s+cours)?|situation(?:\s+des?\s+cours?)?|appendix\b|annex(?:e|es)?\b)",
    re.IGNORECASE,
)
_VISUAL_TOC_ENDNOTES_TITLE_RE = re.compile(
    r"^\s*(?:notes?\b|endnotes?\b|notes?\s+on\s+the\s+text\b|notes?\s+to\s+the\s+chapters?\b|chapter\s+notes?\b)",
    re.IGNORECASE,
)
_VISUAL_TOC_BACK_MATTER_TITLE_RE = re.compile(
    r"^\s*(?:index\b|indices?\b|bibliograph(?:y|ie|ies)\b|references?\b|works cited\b|note on sources?\b)",
    re.IGNORECASE,
)
_VISUAL_TOC_FRONT_MATTER_TITLE_RE = re.compile(
    r"^\s*(?:list of abbreviations|liste des abr[eé]viations|list of illustrations|liste des illustrations|"
    r"acknowledg(?:e)?ments?|remerciements?|foreword|preface|avant-propos|avant propos|avertissement|abstract)\b",
    re.IGNORECASE,
)
_VISUAL_TOC_CHAPTER_TITLE_RE = re.compile(
    r"^\s*(?:chapter|chapitre)\b|^(?:\d+|[ivxlcm]+)(?:[\.\):\-]|\s)\s*\S+|\ble[cç]on du\b|\bepilogue\b|\bconclusion\b|\bintroduction\b",
    re.IGNORECASE,
)
_VISUAL_TOC_ROMAN_CONTAINER_RE = re.compile(r"^\s*[ivxlcm]+\.\s+\S+", re.IGNORECASE)
_MANUAL_TOC_HEADER_LINE_RE = re.compile(
    r"^\s*(?:(?:[ivxlcdm\d]+\s*)?(?:contents?|table(?:\s+of\s+contents)?|table des mati[eè]res|sommaire)(?:\s*[ivxlcdm\d]+)?|(?:contents?|table(?:\s+of\s+contents)?|table des mati[eè]res|sommaire)(?:\s*[ivxlcdm\d]+)?)\s*$",
    re.IGNORECASE,
)
_MANUAL_TOC_HEADER_PREFIX_RE = re.compile(
    r"^\s*(?:[ivxlcdm\d]+\s*)?(?:contents?|table(?:\s+of\s+contents)?|table des mati[eè]res|sommaire)\s*",
    re.IGNORECASE,
)
_MANUAL_TOC_TRAILING_PAGE_RE = re.compile(
    r"^(?P<title>.+?)\s+(?P<page>\d{1,4}|[ivxlcdm]{1,8})\s*$",
    re.IGNORECASE,
)
_VISUAL_USAGE_STAGES = (
    "visual_toc.preflight",
    "visual_toc.classify_candidates",
    "visual_toc.extract_page_items",
    "visual_toc.manual_input_extract",
)

_PAGE_ITEM_ROLE_HINT_VALUES = {"container", "content", "back_matter"}
from . import manual_inputs as manual_inputs_mod, organization, scan_plan, vision
from .shared import (
    _VISUAL_USAGE_STAGES,
    VisionModelRequestError,
    _attach_trace_payload,
    _attach_usage_payload,
    _coerce_nonnegative_int,
    _coerce_positive_int,
    _format_visual_failure_message,
    _summarize_usage_events,
)

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
    normalized_status = str(status or "idle").strip() or "idle"
    normalized_phase = str(phase or "").strip()
    normalized_detail = str(detail or "")
    update_doc_meta(
        doc_id,
        toc_visual_status=normalized_status,
        toc_visual_phase=normalized_phase,
        toc_visual_progress_pct=max(0, min(100, int(pct or 0))),
        toc_visual_progress_label=str(label or ""),
        toc_visual_progress_detail=normalized_detail,
        toc_visual_message=str(message or ""),
        toc_visual_model_id=str(model_id or ""),
    )
    logger.info(
        "视觉目录状态 doc_id=%s status=%s phase=%s pct=%s detail=%s",
        doc_id,
        normalized_status,
        normalized_phase,
        int(max(0, min(100, int(pct or 0)))),
        normalized_detail,
    )

def _vision_failure_result(doc_id: str, model_id: str, exc: VisionModelRequestError) -> dict:
    reason = str(exc.detail or str(exc) or "视觉模型请求失败").strip()
    stage = str(exc.stage or "vision_call").strip()
    status_text = f"HTTP {exc.status_code}" if exc.status_code is not None else "unknown_http"
    failure_msg = f"{stage} 请求失败（{status_text}）：{reason}"
    logger.warning(
        "视觉目录请求失败 doc_id=%s stage=%s status=%s detail=%s",
        doc_id,
        stage,
        status_text,
        reason,
    )
    _set_visual_toc_progress(
        doc_id,
        status="failed",
        phase="failed",
        pct=100,
        label="自动视觉目录失败",
        detail=failure_msg,
        message=failure_msg,
        model_id=model_id,
    )
    return {
        "status": "failed",
        "count": 0,
        "reason_code": "vision_request_failed",
        "http_status": exc.status_code,
        "message": failure_msg,
    }

def generate_auto_visual_toc_for_doc(doc_id: str, *, pdf_path: str, model_spec=None) -> dict:
    """为指定文档生成自动视觉目录。"""
    if doc_id:
        clear_auto_visual_toc_bundle_from_disk(doc_id)
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

    spec = model_spec or resolve_visual_model_spec()
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

    usage_events: list[dict] = []
    trace_events: list[dict] = []
    supported, support_message = vision.confirm_model_supports_vision(
        spec,
        usage_events=usage_events,
        trace_events=trace_events,
        doc_id=doc_id,
    )
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
        return _attach_trace_payload(_attach_usage_payload({"status": "unsupported", "count": 0}, usage_events), trace_events)

    manual_inputs = load_toc_visual_manual_inputs(doc_id)
    manual_mode = str((manual_inputs or {}).get("mode") or "").strip().lower()
    if manual_mode in {"manual_pdf", "manual_images"}:
        try:
            return _generate_visual_toc_from_manual_inputs(
                doc_id=doc_id,
                pdf_path=pdf_path,
                spec=spec,
                model_id=model_id,
                manual_inputs=manual_inputs,
                repo=repo,
                usage_events=usage_events,
                trace_events=trace_events,
            )
        except VisionModelRequestError as exc:
            return _attach_trace_payload(_attach_usage_payload(_vision_failure_result(doc_id, model_id, exc), usage_events), trace_events)

    total_pages = scan_plan._resolve_total_pages(pdf_path)
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
        return _attach_trace_payload(_attach_usage_payload({"status": "failed", "count": 0}, usage_events), trace_events)

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
    page_features = scan_plan._extract_local_toc_page_features(pdf_path, total_pages)
    scan_result = scan_plan._build_visual_scan_plan(
        page_features,
        total_pages,
        max_pages=_LOCAL_VISUAL_SCAN_MAX_PAGES,
    )
    scan_mode = str(scan_result.get("mode", "normal") or "normal").strip().lower()
    scan_quality = scan_result.get("quality", {}) if isinstance(scan_result, dict) else {}
    candidate_source = str(scan_result.get("candidate_source", "unknown") or "unknown")
    run_summaries = list(scan_result.get("run_summaries") or [])
    planned_selected_run_count = sum(
        1
        for row in run_summaries
        if str((row or {}).get("selected_as") or "") in {"primary_run", "secondary_run"}
    )
    candidate_indices = scan_plan._sorted_unique_indices(list(scan_result.get("candidate_indices") or []))
    primary_run_pages = scan_plan._sorted_unique_indices(list(scan_result.get("primary_run_pages") or []))
    context_pages = scan_plan._sorted_unique_indices(list(scan_result.get("context_pages") or []))
    retry_indices = scan_plan._sorted_unique_indices(list(scan_result.get("retry_indices") or []))
    _set_visual_toc_progress(
        doc_id,
        status="running",
        phase="visual_review",
        pct=34,
        label="候选页视觉复核",
        detail=(
            f"将复核 {len(candidate_indices)} 页目录候选页"
            f"（模式: {scan_mode}，来源: {candidate_source}，"
            f"control_ratio={scan_quality.get('control_char_ratio', 0)}）"
        ),
        message=f"正在视觉复核目录候选页（{scan_mode}）…",
        model_id=model_id,
    )
    try:
        classified_results = vision._classify_toc_candidates(
            spec,
            pdf_path,
            candidate_indices,
            usage_events=usage_events,
            trace_events=trace_events,
            doc_id=doc_id,
            trace_image_meta=[
                {"source_path": str(pdf_path), "file_idx": int(file_idx), "source": "pdf_page"}
                for file_idx in candidate_indices
            ],
        )
    except VisionModelRequestError as exc:
        return _attach_trace_payload(_attach_usage_payload(_vision_failure_result(doc_id, model_id, exc), usage_events), trace_events)
    selected_clusters = scan_plan._collect_toc_clusters(classified_results)
    if not selected_clusters and retry_indices:
        _set_visual_toc_progress(
            doc_id,
            status="running",
            phase="visual_retry",
            pct=42,
            label="候选页邻域重试",
            detail=f"首轮未形成目录簇，正在重试复核 {len(retry_indices)} 页邻域候选页",
            message="首轮未命中目录簇，正在邻域重试…",
            model_id=model_id,
        )
        try:
            retry_results = vision._classify_toc_candidates(
                spec,
                pdf_path,
                retry_indices,
                usage_events=usage_events,
                trace_events=trace_events,
                doc_id=doc_id,
                trace_image_meta=[
                    {"source_path": str(pdf_path), "file_idx": int(file_idx), "source": "pdf_page"}
                    for file_idx in retry_indices
                ],
            )
        except VisionModelRequestError as exc:
            return _attach_trace_payload(_attach_usage_payload(_vision_failure_result(doc_id, model_id, exc), usage_events), trace_events)
        classified_results = classified_results + retry_results
        selected_clusters = scan_plan._collect_toc_clusters(classified_results)
    if not selected_clusters:
        reason_prefix = "degraded_text_layer" if scan_mode == "degraded" else "normal_text_layer"
        reason_code = f"{reason_prefix}/no_toc_cluster_after_retry"
        failure_message = _format_visual_failure_message(
            reason_code,
            "未找到稳定的目录页，已回退到现有目录来源。",
        )
        _set_visual_toc_progress(
            doc_id,
            status="failed",
            phase="failed",
            pct=100,
            label="自动视觉目录失败",
            detail=failure_message,
            message=failure_message,
            model_id=model_id,
        )
        return _attach_trace_payload(_attach_usage_payload({
            "status": "failed",
            "count": 0,
            "scan_mode": scan_mode,
            "candidate_source": candidate_source,
            "candidate_indices": candidate_indices,
            "candidate_pdf_pages": scan_plan._indices_to_pdf_pages(candidate_indices),
            "primary_run_pages": primary_run_pages,
            "context_pages": context_pages,
            "retry_indices": retry_indices,
            "retry_pdf_pages": scan_plan._indices_to_pdf_pages(retry_indices),
            "run_summaries": run_summaries,
            "selected_run_count": int(planned_selected_run_count),
            "selected_page_count": len(candidate_indices),
            "resolved_item_count": 0,
            "unresolved_item_count": 0,
            "suspected_partial_capture": False,
            "coverage_quality": "none",
        }, usage_events), trace_events)

    printed_page_lookup = organization._build_printed_page_lookup(doc_id, pdf_path)
    resolved_items: list[dict] = []
    unresolved_items = 0
    selected_page_indices = scan_plan._sorted_unique_indices(
        [
            _coerce_nonnegative_int(item.get("file_idx"))
            for cluster in selected_clusters
            for item in (cluster or [])
            if _coerce_nonnegative_int(item.get("file_idx")) is not None
        ]
    )
    extraction_page_count = len(selected_page_indices)
    selected_page_count = len(candidate_indices)
    selected_run_count = max(len(selected_clusters), int(planned_selected_run_count))

    _set_visual_toc_progress(
        doc_id,
        status="running",
        phase="extracting_items",
        pct=50,
        label="目录项抽取",
        detail=f"正在抽取 {extraction_page_count} 页目录项（{selected_run_count} 个run）",
        message="正在抽取目录项…",
        model_id=model_id,
    )
    for page_index, file_idx in enumerate(selected_page_indices, start=1):
        try:
            page_items = vision._extract_visual_toc_page_items_from_pdf(
                spec,
                pdf_path,
                file_idx,
                usage_events=usage_events,
                trace_events=trace_events,
                doc_id=doc_id,
                usage_stage="visual_toc.extract_page_items",
            )
        except VisionModelRequestError as exc:
            return _attach_trace_payload(_attach_usage_payload(_vision_failure_result(doc_id, model_id, exc), usage_events), trace_events)
        page_items = organization.filter_visual_toc_items(page_items)
        page_items = organization._apply_printed_page_lookup(page_items, printed_page_lookup)
        page_items = organization.map_visual_items_to_link_targets(
            page_items,
            extract_pdf_page_link_targets(pdf_path, file_idx),
        )
        _set_visual_toc_progress(
            doc_id,
            status="running",
            phase="mapping_targets",
            pct=min(82, 50 + int(page_index / max(1, extraction_page_count) * 32)),
            label="页码/链接映射",
            detail=f"正在处理目录页 {page_index}/{extraction_page_count}",
            message="正在映射目录页和目标页…",
            model_id=model_id,
        )
        for item in page_items:
            visual_order = len(resolved_items) + 1
            normalized = {
                "title": item["title"],
                "depth": max(0, int(item.get("depth", 0) or 0)),
                "visual_order": visual_order,
                "item_id": f"visual-{file_idx}-{visual_order}-{organization._slugify_visual_toc_title(item['title'])[:24]}",
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

    resolved_items = manual_inputs_mod._dedupe_toc_items(resolved_items)
    resolved_items = organization._filter_resolved_visual_toc_anomalies(resolved_items, total_pages)
    resolved_items, organization_summary = organization._annotate_visual_toc_organization(resolved_items)
    repo.set_document_toc_for_source(doc_id, TOC_SOURCE_AUTO_VISUAL, resolved_items)
    if not load_user_toc_from_disk(doc_id):
        repo.set_document_toc_source_offset(doc_id, TOC_SOURCE_AUTO_VISUAL, 0)

    endnotes_summary = organization._finalize_endnotes_summary(organization._default_endnotes_summary(), resolved_items)
    coverage_summary = scan_plan._build_coverage_quality_summary(
        resolved_items=resolved_items,
        unresolved_item_count=unresolved_items,
        selected_page_count=selected_page_count,
        selected_run_count=selected_run_count,
        total_pages=total_pages,
    )
    offset_summary = organization._build_offset_resolution_summary(resolved_items)
    result_payload = {
        "scan_mode": scan_mode,
        "candidate_source": candidate_source,
        "candidate_indices": candidate_indices,
        "candidate_pdf_pages": scan_plan._indices_to_pdf_pages(candidate_indices),
        "primary_run_pages": primary_run_pages,
        "context_pages": context_pages,
        "retry_indices": retry_indices,
        "retry_pdf_pages": scan_plan._indices_to_pdf_pages(retry_indices),
        "run_summaries": run_summaries,
        "organization_summary": dict(organization_summary or {}),
        "organization_nodes": list(resolved_items),
        "endnotes_summary": endnotes_summary,
        "manual_page_items_debug": [],
        "organization_bundle_debug": {},
        **coverage_summary,
        **offset_summary,
    }

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
        return _attach_trace_payload(_attach_usage_payload({"status": "failed", "count": 0, **result_payload}, usage_events), trace_events)

    unresolved_navigable_count = int(offset_summary.get("unresolved_navigable_count", 0) or 0)
    if unresolved_navigable_count <= 0:
        usage_summary = _summarize_usage_events(usage_events, required_stages=_VISUAL_USAGE_STAGES)
        save_auto_visual_toc_bundle_to_disk(
            doc_id,
            organization._build_visual_toc_runtime_bundle(
                items=resolved_items,
                endnotes_summary=endnotes_summary,
                organization_summary=organization_summary,
                usage_summary=usage_summary,
                run_summaries=run_summaries,
            ),
        )
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
        return _attach_trace_payload(_attach_usage_payload({"status": "ready", "count": len(resolved_items), **result_payload}, usage_events), trace_events)

    usage_summary = _summarize_usage_events(usage_events, required_stages=_VISUAL_USAGE_STAGES)
    save_auto_visual_toc_bundle_to_disk(
        doc_id,
        organization._build_visual_toc_runtime_bundle(
            items=resolved_items,
            endnotes_summary=endnotes_summary,
            organization_summary=organization_summary,
            usage_summary=usage_summary,
            run_summaries=run_summaries,
        ),
    )
    _set_visual_toc_progress(
        doc_id,
        status="needs_offset",
        phase="completed",
        pct=100,
        label="自动视觉目录已加载，仍需校准",
        detail=f"已识别 {len(resolved_items)} 条目录，但仍有 {unresolved_navigable_count} 条正文目录项无法稳定定位到 PDF 页。",
        message=f"已识别 {len(resolved_items)} 条目录，但仍有 {unresolved_navigable_count} 条正文目录项无法稳定定位到 PDF 页。",
        model_id=model_id,
    )
    return _attach_trace_payload(_attach_usage_payload({"status": "needs_offset", "count": len(resolved_items), **result_payload}, usage_events), trace_events)

def _generate_visual_toc_from_manual_inputs(
    *,
    doc_id: str,
    pdf_path: str,
    spec,
    model_id: str,
    manual_inputs: dict,
    repo,
    usage_events: list[dict] | None = None,
    trace_events: list[dict] | None = None,
) -> dict:
    mode = str((manual_inputs or {}).get("mode") or "").strip().lower()
    source_name = str((manual_inputs or {}).get("source_name") or "").strip()
    if mode == "manual_pdf":
        manual_pdf_path = str((manual_inputs or {}).get("pdf_path") or "").strip()
        if not manual_pdf_path or not os.path.exists(manual_pdf_path):
            _set_visual_toc_progress(
                doc_id,
                status="failed",
                phase="failed",
                pct=100,
                label="自动视觉目录失败",
                detail="未找到手动上传的目录 PDF。",
                message="未找到手动上传的目录 PDF。",
                model_id=model_id,
            )
            return _attach_trace_payload(_attach_usage_payload({"status": "failed", "count": 0}, usage_events), trace_events)
        manual_page_count = scan_plan._resolve_total_pages(manual_pdf_path)
        manual_image_bytes = [
            vision.render_pdf_page(manual_pdf_path, file_idx, scale=1.6)
            for file_idx in range(max(0, manual_page_count))
        ]
        manual_images = [
            vision._bytes_to_data_url(blob)
            for blob in manual_image_bytes
        ]
        manual_page_items = [
            vision._extract_visual_toc_page_items_from_pdf(
                spec,
                manual_pdf_path,
                file_idx,
                usage_events=usage_events,
                trace_events=trace_events,
                doc_id=doc_id,
                usage_stage="visual_toc.manual_input_extract",
            )
            for file_idx in range(max(0, manual_page_count))
        ]
        organization_trace_image_meta = [
            {"source_path": str(manual_pdf_path), "file_idx": int(file_idx), "source": "pdf_page"}
            for file_idx in range(max(0, manual_page_count))
        ]
    elif mode == "manual_images":
        image_paths = [str(path or "").strip() for path in (manual_inputs or {}).get("image_paths") or [] if str(path or "").strip()]
        if not image_paths:
            _set_visual_toc_progress(
                doc_id,
                status="failed",
                phase="failed",
                pct=100,
                label="自动视觉目录失败",
                detail="未找到手动上传的目录截图。",
                message="未找到手动上传的目录截图。",
                model_id=model_id,
            )
            return _attach_trace_payload(_attach_usage_payload({"status": "failed", "count": 0}, usage_events), trace_events)
        manual_page_count = len(image_paths)
        manual_image_bytes = [vision._read_image_bytes(image_path) for image_path in image_paths]
        manual_images = [vision._bytes_to_data_url(blob) for blob in manual_image_bytes]
        manual_page_items = [
            vision._extract_visual_toc_page_items_from_image(
                spec,
                image_path,
                usage_events=usage_events,
                trace_events=trace_events,
                doc_id=doc_id,
                usage_stage="visual_toc.manual_input_extract",
            )
            for image_path in image_paths
        ]
        organization_trace_image_meta = [
            {"source_path": str(image_path), "source": "manual_image"}
            for image_path in image_paths
        ]
    else:
        return _attach_trace_payload(_attach_usage_payload({"status": "failed", "count": 0}, usage_events), trace_events)
    manual_page_items_debug = [
        [dict(item) for item in (page_items or []) if isinstance(item, dict)]
        for page_items in (manual_page_items or [])
    ]

    _set_visual_toc_progress(
        doc_id,
        status="running",
        phase="manual_input_extract",
        pct=48,
        label="手动目录抽取",
        detail=f"正在从手动目录输入抽取 {manual_page_count} 页目录项",
        message="正在使用手动目录输入生成视觉目录…",
        model_id=model_id,
    )
    printed_page_lookup = organization._build_printed_page_lookup(doc_id, pdf_path)
    resolved_items: list[dict] = []
    unresolved_items = 0
    seed_titles: list[str] = []
    for page_index, page_items in enumerate(manual_page_items, start=1):
        page_items = organization.filter_visual_toc_items(page_items)
        page_items = organization._apply_printed_page_lookup(page_items, printed_page_lookup)
        for item in page_items:
            visual_order = len(resolved_items) + 1
            normalized = {
                "title": item["title"],
                "depth": max(0, int(item.get("depth", 0) or 0)),
                "visual_order": visual_order,
                "item_id": f"manual-{page_index}-{visual_order}-{organization._slugify_visual_toc_title(item['title'])[:24]}",
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
            seed_titles.append(str(item.get("title") or ""))

    organization_bundle = vision._extract_visual_toc_organization_bundle_from_images(
        spec,
        images=manual_images,
        seed_titles=seed_titles,
        usage_events=usage_events,
        trace_events=trace_events,
        doc_id=doc_id,
        usage_stage="visual_toc.manual_input_extract",
        trace_image_meta=organization_trace_image_meta,
    )
    organization_nodes = list(organization_bundle.get("items") or [])
    endnotes_summary = organization._normalize_endnotes_summary(organization_bundle.get("endnotes_summary"))
    outline_nodes: list[dict] = []
    prefer_outline_as_primary_items = False
    if mode == "manual_pdf":
        outline_nodes = manual_inputs_mod._extract_manual_toc_outline_nodes_from_pdf_text(manual_pdf_path)
        if outline_nodes:
            outline_nodes = organization.filter_visual_toc_items(outline_nodes)
            outline_nodes = organization._apply_printed_page_lookup(outline_nodes, printed_page_lookup)
            if organization_nodes:
                if organization._should_prefer_manual_outline_nodes(organization_nodes, outline_nodes):
                    organization_nodes = outline_nodes
                    prefer_outline_as_primary_items = True
                else:
                    organization_nodes = manual_inputs_mod._merge_manual_toc_organization_nodes(organization_nodes, outline_nodes)
            else:
                organization_nodes = outline_nodes
                prefer_outline_as_primary_items = True
    if organization_nodes:
        organization_nodes = organization.filter_visual_toc_items(organization_nodes)
        organization_nodes = organization._apply_printed_page_lookup(organization_nodes, printed_page_lookup)
        if prefer_outline_as_primary_items:
            resolved_items = [dict(item) for item in organization_nodes]
        else:
            resolved_items = manual_inputs_mod._merge_manual_toc_organization_nodes(resolved_items, organization_nodes)
    resolved_items = manual_inputs_mod._augment_manual_toc_organization_with_ocr_containers(
        resolved_items,
        manual_inputs_mod._extract_manual_toc_ocr_lines_from_image_bytes_list(manual_image_bytes),
    )

    resolved_items = manual_inputs_mod._dedupe_toc_items(resolved_items)
    resolved_items = organization._filter_resolved_visual_toc_anomalies(resolved_items, scan_plan._resolve_total_pages(pdf_path))
    resolved_items, organization_summary = organization._annotate_visual_toc_organization(resolved_items)
    repo.set_document_toc_for_source(doc_id, TOC_SOURCE_AUTO_VISUAL, resolved_items)
    if not load_user_toc_from_disk(doc_id):
        repo.set_document_toc_source_offset(doc_id, TOC_SOURCE_AUTO_VISUAL, 0)

    coverage_summary = scan_plan._build_coverage_quality_summary(
        resolved_items=resolved_items,
        unresolved_item_count=unresolved_items,
        selected_page_count=int(manual_page_count or 0),
        selected_run_count=1 if manual_page_count else 0,
        total_pages=max(1, int(manual_page_count or 0)),
    )
    offset_summary = organization._build_offset_resolution_summary(resolved_items)
    endnotes_summary = organization._finalize_endnotes_summary(
        organization_bundle.get("endnotes_summary"),
        resolved_items,
    )
    result_payload = {
        "scan_mode": mode,
        "candidate_source": "manual_toc_upload",
        "candidate_indices": [],
        "candidate_pdf_pages": [],
        "primary_run_pages": [],
        "context_pages": [],
        "retry_indices": [],
        "retry_pdf_pages": [],
        "run_summaries": [
            {
                "start_file_idx": 0,
                "end_file_idx": max(0, int(manual_page_count or 0) - 1),
                "page_count": int(manual_page_count or 0),
                "score": float(len(resolved_items)),
                "selected_as": "primary_run",
            }
        ] if manual_page_count else [],
        "organization_summary": dict(organization_summary or {}),
        "organization_nodes": list(resolved_items),
        "endnotes_summary": endnotes_summary,
        "manual_input_mode": mode,
        "manual_input_page_count": int(manual_page_count or 0),
        "manual_input_source_name": source_name,
        "manual_page_items_debug": manual_page_items_debug,
        "organization_bundle_debug": dict(organization_bundle or {}),
        **coverage_summary,
        **offset_summary,
    }

    if not resolved_items:
        _set_visual_toc_progress(
            doc_id,
            status="failed",
            phase="failed",
            pct=100,
            label="自动视觉目录失败",
            detail="手动目录已读取，但没有抽取到稳定目录项。",
            message="手动目录已读取，但没有抽取到稳定目录项。",
            model_id=model_id,
        )
        return _attach_trace_payload(_attach_usage_payload({"status": "failed", "count": 0, **result_payload}, usage_events), trace_events)

    unresolved_navigable_count = int(offset_summary.get("unresolved_navigable_count", 0) or 0)
    if unresolved_navigable_count <= 0:
        final_status = "ready"
        final_detail = f"已通过手动目录输入生成 {len(resolved_items)} 条自动视觉目录。"
    else:
        final_status = "needs_offset"
        final_detail = f"已通过手动目录输入生成 {len(resolved_items)} 条目录，但仍有 {unresolved_navigable_count} 条正文目录项无法稳定定位到 PDF 页。"
    usage_summary = _summarize_usage_events(usage_events, required_stages=_VISUAL_USAGE_STAGES)
    save_auto_visual_toc_bundle_to_disk(
        doc_id,
        organization._build_visual_toc_runtime_bundle(
            items=resolved_items,
            endnotes_summary=endnotes_summary,
            organization_summary=organization_summary,
            usage_summary=usage_summary,
            run_summaries=list(result_payload.get("run_summaries") or []),
            manual_page_items_debug=manual_page_items_debug,
            organization_bundle_debug=dict(organization_bundle or {}),
        ),
    )
    _set_visual_toc_progress(
        doc_id,
        status=final_status,
        phase="completed",
        pct=100,
        label="自动视觉目录已生成",
        detail=final_detail,
        message=final_detail,
        model_id=model_id,
    )
    return _attach_trace_payload(_attach_usage_payload({"status": final_status, "count": len(resolved_items), **result_payload}, usage_events), trace_events)

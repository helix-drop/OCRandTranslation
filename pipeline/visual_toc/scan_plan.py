"""visual TOC 候选页扫描与计划生成。"""

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
from .shared import _coerce_nonnegative_int

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

def _assess_text_layer_quality(page_features: list[dict], total_pages: int) -> dict:
    ordered = sorted(page_features or [], key=lambda page: int(page.get("file_idx", -1)))
    if not ordered:
        return {
            "mode": "normal",
            "reason_code": "normal_text_layer",
            "sample_pages": 0,
            "sample_chars": 0,
            "control_char_ratio": 0.0,
            "replacement_char_ratio": 0.0,
        }

    target_samples = max(12, min(64, int(round(max(1, int(total_pages or 0)) * 0.08))))
    sample_count = min(len(ordered), target_samples)
    if sample_count == len(ordered):
        sampled = ordered
    else:
        step = max(1, len(ordered) // sample_count)
        sampled = ordered[::step][:sample_count]
        if len(sampled) < sample_count:
            sampled = ordered[-sample_count:]

    sample_text = "\n".join(str(item.get("text_excerpt", "") or "") for item in sampled)
    signal_chars = [char for char in sample_text if not char.isspace()]
    if not signal_chars:
        return {
            "mode": "normal",
            "reason_code": "normal_text_layer",
            "sample_pages": len(sampled),
            "sample_chars": 0,
            "control_char_ratio": 0.0,
            "replacement_char_ratio": 0.0,
        }

    sample_chars = len(signal_chars)
    control_chars = sum(1 for char in signal_chars if ord(char) < 32 or 127 <= ord(char) <= 159)
    replacement_chars = sum(1 for char in signal_chars if char == "\ufffd")
    control_ratio = control_chars / sample_chars
    replacement_ratio = replacement_chars / sample_chars

    degraded = (
        sample_chars >= _TEXT_LAYER_MIN_SAMPLE_CHARS
        and (
            control_ratio >= _TEXT_LAYER_DEGRADED_CONTROL_CHAR_RATIO
            or replacement_ratio >= _TEXT_LAYER_DEGRADED_REPLACEMENT_CHAR_RATIO
        )
    )
    return {
        "mode": "degraded" if degraded else "normal",
        "reason_code": "degraded_text_layer" if degraded else "normal_text_layer",
        "sample_pages": len(sampled),
        "sample_chars": sample_chars,
        "control_char_ratio": round(control_ratio, 4),
        "replacement_char_ratio": round(replacement_ratio, 4),
    }

def _choose_degraded_toc_scan_indices(total_pages: int, max_pages: int = _LOCAL_VISUAL_SCAN_MAX_PAGES) -> list[int]:
    plan = _build_degraded_scan_plan(
        page_features=[],
        total_pages=total_pages,
        max_pages=max_pages,
    )
    return list(plan.get("candidate_indices") or [])

def _expand_candidate_indices_for_retry(
    candidate_indices: list[int],
    total_pages: int,
    *,
    radius: int = _VISUAL_RETRY_NEIGHBOR_RADIUS,
    max_extra_pages: int = _VISUAL_RETRY_MAX_EXTRA_PAGES,
) -> list[int]:
    total = max(0, int(total_pages or 0))
    if total <= 0:
        return []

    seed_set: set[int] = set()
    for value in candidate_indices or []:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= parsed < total:
            seed_set.add(parsed)
    if not seed_set:
        return []

    distance = max(0, int(radius or 0))
    expanded: set[int] = set()
    for seed in sorted(seed_set):
        for delta in range(-distance, distance + 1):
            idx = seed + delta
            if idx < 0 or idx >= total or idx in seed_set:
                continue
            expanded.add(idx)

    retry_indices = sorted(expanded)
    if not retry_indices:
        return []

    budget = max(1, int(max_extra_pages or _VISUAL_RETRY_MAX_EXTRA_PAGES))
    if len(retry_indices) <= budget:
        return retry_indices
    front_budget = max(1, budget // 2)
    back_budget = max(1, budget - front_budget)
    return sorted(set(retry_indices[:front_budget] + retry_indices[-back_budget:]))

def _build_visual_scan_plan(
    page_features: list[dict],
    total_pages: int,
    *,
    max_pages: int = _LOCAL_VISUAL_SCAN_MAX_PAGES,
) -> dict:
    quality = _assess_text_layer_quality(page_features, total_pages)
    mode = str(quality.get("mode", "normal") or "normal").strip().lower()
    if mode == "degraded":
        plan = _build_degraded_scan_plan(
            page_features=page_features,
            total_pages=total_pages,
            max_pages=max_pages,
        )
    else:
        plan = _build_local_scan_plan(
            page_features=page_features,
            total_pages=total_pages,
            max_pages=max_pages,
        )
        if not list(plan.get("candidate_indices") or []):
            front_indices, back_indices = choose_toc_candidate_indices(total_pages)
            fallback = _sorted_unique_indices(front_indices[:4] + back_indices[-4:])
            plan = {
                "candidate_source": "front_back_fallback",
                "primary_run_pages": fallback,
                "context_pages": [],
                "candidate_indices": fallback,
                "retry_indices": _expand_candidate_indices_for_retry(
                    fallback,
                    total_pages,
                    radius=_VISUAL_RETRY_NEIGHBOR_RADIUS,
                    max_extra_pages=_VISUAL_RETRY_MAX_EXTRA_PAGES,
                ),
                "run_summaries": [],
            }

    candidate_indices = _sorted_unique_indices(list(plan.get("candidate_indices") or []))
    if not candidate_indices:
        front_indices, back_indices = choose_toc_candidate_indices(total_pages)
        candidate_indices = _sorted_unique_indices(front_indices[:4] + back_indices[-4:])
        plan.setdefault("candidate_source", "degraded_window_expand" if mode == "degraded" else "front_back_fallback")
        plan["candidate_indices"] = candidate_indices
        plan.setdefault("primary_run_pages", candidate_indices)
        plan.setdefault("context_pages", [])
        plan["retry_indices"] = _expand_candidate_indices_for_retry(
            candidate_indices,
            total_pages,
            radius=_VISUAL_RETRY_NEIGHBOR_RADIUS,
            max_extra_pages=_VISUAL_RETRY_MAX_EXTRA_PAGES,
        )

    return {
        "mode": "degraded" if mode == "degraded" else "normal",
        "quality": quality,
        "candidate_source": str(plan.get("candidate_source") or "unknown"),
        "primary_run_pages": _sorted_unique_indices(list(plan.get("primary_run_pages") or [])),
        "context_pages": _sorted_unique_indices(list(plan.get("context_pages") or [])),
        "candidate_indices": candidate_indices,
        "retry_indices": _sorted_unique_indices(list(plan.get("retry_indices") or [])),
        "run_summaries": list(plan.get("run_summaries") or []),
    }

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

def _collect_toc_clusters(results: list[dict]) -> list[list[dict]]:
    ordered = sorted(results or [], key=lambda item: int(item.get("file_idx", -1)))
    clusters: list[list[dict]] = []
    current: list[dict] = []
    for item in ordered:
        label = str(item.get("label", "") or "").strip().lower()
        score = float(item.get("score", item.get("confidence", 0)) or 0.0)
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

def _indices_to_pdf_pages(indices: list[int]) -> list[int]:
    return [int(idx) + 1 for idx in _sorted_unique_indices(indices)]

def _build_coverage_quality_summary(
    *,
    resolved_items: list[dict],
    unresolved_item_count: int,
    selected_page_count: int,
    selected_run_count: int,
    total_pages: int,
) -> dict[str, int | bool | str]:
    resolved_count = len(resolved_items or [])
    resolved_pdf_pages = sorted(
        {
            int(item.get("file_idx")) + 1
            for item in (resolved_items or [])
            if _coerce_nonnegative_int(item.get("file_idx")) is not None
        }
    )
    suspected_partial_capture = False
    if resolved_count > 0:
        if selected_page_count <= 1 and resolved_count <= 4:
            suspected_partial_capture = True
        elif selected_run_count >= 2 and resolved_pdf_pages:
            first_page = int(resolved_pdf_pages[0])
            if first_page > max(1, int(total_pages * 0.55)):
                suspected_partial_capture = True
        elif selected_run_count <= 1 and resolved_pdf_pages:
            first_page = int(resolved_pdf_pages[0])
            last_page = int(resolved_pdf_pages[-1])
            if first_page > max(1, int(total_pages * 0.55)):
                suspected_partial_capture = True
            elif (last_page - first_page + 1) <= 2 and selected_page_count <= 2:
                suspected_partial_capture = True

    if resolved_count == 0:
        coverage_quality = "none"
    elif suspected_partial_capture:
        coverage_quality = "partial"
    elif unresolved_item_count > 0:
        coverage_quality = "mixed"
    else:
        coverage_quality = "good"

    return {
        "resolved_item_count": int(resolved_count),
        "unresolved_item_count": int(unresolved_item_count),
        "selected_page_count": int(selected_page_count),
        "selected_run_count": int(selected_run_count),
        "suspected_partial_capture": bool(suspected_partial_capture),
        "coverage_quality": coverage_quality,
    }

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

def _sorted_unique_indices(values: list[int]) -> list[int]:
    normalized: set[int] = set()
    for value in values or []:
        try:
            normalized.add(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(normalized)

def _enrich_local_toc_features(page_features: list[dict]) -> tuple[list[dict], dict[int, dict]]:
    enriched: list[dict] = []
    for item in sorted(page_features or [], key=lambda page: int(page.get("file_idx", -1))):
        file_idx = _coerce_nonnegative_int(item.get("file_idx"))
        if file_idx is None:
            continue
        clone = dict(item)
        clone["file_idx"] = file_idx
        clone["local_score"] = _score_local_toc_page(clone)
        clone["header_role"] = _classify_header_hint(clone.get("header_hint"))
        clone["is_anchor"] = bool(clone["header_role"] == "toc" or float(clone.get("local_score", 0) or 0.0) >= 4.0)
        clone["is_candidate"] = bool(float(clone.get("local_score", 0) or 0.0) >= 1.5)
        enriched.append(clone)
    return enriched, {int(item["file_idx"]): item for item in enriched}

def _score_local_toc_run(run_pages: list[int], feature_by_idx: dict[int, dict]) -> float:
    features = [feature_by_idx[idx] for idx in run_pages if idx in feature_by_idx]
    if not features:
        return 0.0
    toc_header_count = sum(1 for item in features if str(item.get("header_role") or "") == "toc")
    index_header_count = sum(1 for item in features if str(item.get("header_role") or "") == "index")
    dot_total = sum(max(0, int(item.get("dot_leader_lines", 0) or 0)) for item in features)
    numbered_total = sum(max(0, int(item.get("numbered_lines", 0) or 0)) for item in features)
    link_total = sum(max(0, int(item.get("link_count", 0) or 0)) for item in features)
    local_score_total = sum(float(item.get("local_score", 0.0) or 0.0) for item in features)
    score = (
        local_score_total
        + (toc_header_count * 1.6)
        + (dot_total * 0.35)
        + (numbered_total * 0.25)
        + (min(link_total, 24) * 0.12)
        - (index_header_count * 2.4)
        + (len(features) * 0.15)
    )
    return round(score, 4)

def _build_local_run_payload(
    run_pages: list[int],
    feature_by_idx: dict[int, dict],
) -> dict | None:
    pages = _sorted_unique_indices(run_pages)
    if not pages:
        return None
    features = [feature_by_idx[idx] for idx in pages if idx in feature_by_idx]
    if not features:
        return None
    header_role_counts = {"toc": 0, "index": 0, "other": 0}
    dot_total = 0
    numbered_total = 0
    link_total = 0
    for item in features:
        role = str(item.get("header_role") or "other")
        if role not in header_role_counts:
            role = "other"
        header_role_counts[role] += 1
        dot_total += max(0, int(item.get("dot_leader_lines", 0) or 0))
        numbered_total += max(0, int(item.get("numbered_lines", 0) or 0))
        link_total += max(0, int(item.get("link_count", 0) or 0))
    start_file_idx = min(pages)
    end_file_idx = max(pages)
    return {
        "run_id": f"run-{start_file_idx:04d}-{end_file_idx:04d}",
        "start_file_idx": start_file_idx,
        "end_file_idx": end_file_idx,
        "pages": pages,
        "page_count": len(pages),
        "score": _score_local_toc_run(pages, feature_by_idx),
        "header_role_counts": header_role_counts,
        "dot_leader_total": dot_total,
        "numbered_line_total": numbered_total,
        "link_count_total": link_total,
    }

def _merge_adjacent_local_runs(runs: list[dict], feature_by_idx: dict[int, dict]) -> list[dict]:
    if not runs:
        return []
    ordered = sorted(
        [dict(run) for run in runs if run],
        key=lambda run: (int(run.get("start_file_idx", 0) or 0), int(run.get("end_file_idx", 0) or 0)),
    )
    merged: list[dict] = []
    current = ordered[0]
    for run in ordered[1:]:
        current_end = int(current.get("end_file_idx", 0) or 0)
        run_start = int(run.get("start_file_idx", 0) or 0)
        gap = run_start - current_end - 1
        if gap <= 2:
            start_idx = int(current.get("start_file_idx", 0) or 0)
            end_idx = int(run.get("end_file_idx", 0) or 0)
            merged_pages = [
                idx
                for idx in range(start_idx, end_idx + 1)
                if idx in feature_by_idx and str(feature_by_idx[idx].get("header_role") or "") != "index"
            ]
            merged_payload = _build_local_run_payload(merged_pages, feature_by_idx)
            if merged_payload:
                current = merged_payload
            continue
        merged.append(current)
        current = run
    merged.append(current)
    return merged

def _build_local_toc_runs(page_features: list[dict]) -> tuple[list[dict], dict[int, dict]]:
    enriched, feature_by_idx = _enrich_local_toc_features(page_features)
    if not enriched:
        return [], feature_by_idx

    anchors = [
        item
        for item in enriched
        if bool(item.get("is_anchor"))
        and str(item.get("header_role") or "") != "index"
    ]
    runs: list[dict] = []
    if anchors:
        anchor_groups: list[list[dict]] = []
        current_group: list[dict] = []
        for anchor in anchors:
            if not current_group:
                current_group = [anchor]
                continue
            previous = current_group[-1]
            prev_idx = int(previous.get("file_idx", -1) or -1)
            curr_idx = int(anchor.get("file_idx", -1) or -1)
            gap = curr_idx - prev_idx - 1
            can_bridge = (
                gap <= 1
                or (
                    gap <= 2
                    and str(previous.get("header_role") or "") == "toc"
                    and str(anchor.get("header_role") or "") == "toc"
                )
            )
            if can_bridge:
                current_group.append(anchor)
            else:
                anchor_groups.append(current_group)
                current_group = [anchor]
        if current_group:
            anchor_groups.append(current_group)

        for group in anchor_groups:
            start_idx = int(group[0].get("file_idx", 0) or 0)
            end_idx = int(group[-1].get("file_idx", 0) or 0)

            left_idx = start_idx - 1
            while left_idx in feature_by_idx:
                feature = feature_by_idx[left_idx]
                if (
                    str(feature.get("header_role") or "") == "index"
                    or not bool(feature.get("is_candidate"))
                ):
                    break
                start_idx = left_idx
                left_idx -= 1

            right_idx = end_idx + 1
            while right_idx in feature_by_idx:
                feature = feature_by_idx[right_idx]
                if (
                    str(feature.get("header_role") or "") == "index"
                    or not bool(feature.get("is_candidate"))
                ):
                    break
                end_idx = right_idx
                right_idx += 1

            run_pages = [
                idx
                for idx in range(start_idx, end_idx + 1)
                if idx in feature_by_idx and str(feature_by_idx[idx].get("header_role") or "") != "index"
            ]
            payload = _build_local_run_payload(run_pages, feature_by_idx)
            if payload:
                runs.append(payload)
    else:
        candidate_pages = [
            int(item.get("file_idx", -1) or -1)
            for item in enriched
            if bool(item.get("is_candidate"))
            and str(item.get("header_role") or "") != "index"
        ]
        candidate_pages = _sorted_unique_indices(candidate_pages)
        if candidate_pages:
            start_idx = candidate_pages[0]
            current_pages = [start_idx]
            for idx in candidate_pages[1:]:
                if idx - current_pages[-1] <= 1:
                    current_pages.append(idx)
                    continue
                payload = _build_local_run_payload(current_pages, feature_by_idx)
                if payload:
                    runs.append(payload)
                current_pages = [idx]
            payload = _build_local_run_payload(current_pages, feature_by_idx)
            if payload:
                runs.append(payload)

    merged_runs = _merge_adjacent_local_runs(runs, feature_by_idx)
    return merged_runs, feature_by_idx

def _build_local_scan_plan(
    *,
    page_features: list[dict],
    total_pages: int,
    max_pages: int = _LOCAL_VISUAL_SCAN_MAX_PAGES,
) -> dict:
    total = max(0, int(total_pages or 0))
    max_total = max(1, min(int(max_pages or _MAX_VISUAL_TOC_PAGES_TOTAL), _MAX_VISUAL_TOC_PAGES_TOTAL))
    per_run_limit = max(1, min(_MAX_VISUAL_TOC_PAGES_PER_RUN, max_total))
    runs, feature_by_idx = _build_local_toc_runs(page_features)

    if not runs:
        return {
            "candidate_source": "local_multi_run",
            "primary_run_pages": [],
            "context_pages": [],
            "candidate_indices": [],
            "retry_indices": [],
            "run_summaries": [],
        }

    ranked_runs = sorted(
        runs,
        key=lambda run: (
            -float(run.get("score", 0.0) or 0.0),
            -int((run.get("header_role_counts") or {}).get("toc", 0) or 0),
            -int(run.get("dot_leader_total", 0) or 0),
            int(run.get("start_file_idx", 0) or 0),
        ),
    )
    ranked_runs = ranked_runs[:_MAX_PRIMARY_RUNS]

    remaining = max_total
    selected_runs: list[dict] = []
    primary_pages_all: list[int] = []
    for rank, run in enumerate(ranked_runs):
        if remaining <= 0:
            break
        run_pages = list(run.get("pages") or [])
        if not run_pages:
            continue
        toc_pages = [
            idx for idx in run_pages
            if str((feature_by_idx.get(idx) or {}).get("header_role") or "") == "toc"
        ]
        chosen: list[int] = []
        seen: set[int] = set()
        for idx in toc_pages + run_pages:
            if idx in seen:
                continue
            seen.add(idx)
            chosen.append(idx)
            if len(chosen) >= per_run_limit:
                break
        if len(chosen) > remaining:
            chosen = chosen[:remaining]
        if not chosen:
            continue
        selected_runs.append(
            {
                **run,
                "priority_rank": rank,
                "primary_pages": chosen,
            }
        )
        primary_pages_all.extend(chosen)
        remaining -= len(chosen)

    primary_pages = _sorted_unique_indices(primary_pages_all)
    context_pages: list[int] = []
    used_pages = set(primary_pages)
    if remaining > 0:
        for run in selected_runs:
            if remaining <= 0:
                break
            run_primary = _sorted_unique_indices(list(run.get("primary_pages") or []))
            if not run_primary:
                continue
            run_start = min(run_primary)
            run_end = max(run_primary)
            for delta in range(1, _CONTEXT_PAGES_PER_RUN_SIDE + 1):
                for idx in (run_start - delta, run_end + delta):
                    if remaining <= 0:
                        break
                    if idx < 0 or idx >= total or idx in used_pages:
                        continue
                    feature = feature_by_idx.get(idx)
                    if feature and str(feature.get("header_role") or "") == "index":
                        continue
                    used_pages.add(idx)
                    context_pages.append(idx)
                    remaining -= 1

    candidate_indices = _sorted_unique_indices(primary_pages + context_pages)
    retry_indices = _expand_candidate_indices_for_retry(
        candidate_indices,
        total,
        radius=_VISUAL_RETRY_NEIGHBOR_RADIUS,
        max_extra_pages=_VISUAL_RETRY_MAX_EXTRA_PAGES,
    )

    selected_run_ids = [str(run.get("run_id") or "") for run in selected_runs if str(run.get("run_id") or "")]
    context_set = set(context_pages)
    run_summaries: list[dict] = []
    for run in sorted(runs, key=lambda row: int(row.get("start_file_idx", 0) or 0)):
        run_id = str(run.get("run_id") or "")
        if run_id and run_id in selected_run_ids:
            selected_as = "primary_run" if selected_run_ids.index(run_id) == 0 else "secondary_run"
        elif context_set.intersection(set(run.get("pages") or [])):
            selected_as = "context_only"
        else:
            selected_as = "dropped"
        run_summaries.append(
            {
                "start_file_idx": int(run.get("start_file_idx", 0) or 0),
                "end_file_idx": int(run.get("end_file_idx", 0) or 0),
                "page_count": int(run.get("page_count", 0) or 0),
                "score": float(run.get("score", 0.0) or 0.0),
                "header_role_counts": dict(run.get("header_role_counts") or {}),
                "dot_leader_total": int(run.get("dot_leader_total", 0) or 0),
                "numbered_line_total": int(run.get("numbered_line_total", 0) or 0),
                "selected_as": selected_as,
            }
        )

    return {
        "candidate_source": "local_multi_run",
        "primary_run_pages": primary_pages,
        "context_pages": _sorted_unique_indices(context_pages),
        "candidate_indices": candidate_indices,
        "retry_indices": retry_indices,
        "run_summaries": run_summaries,
    }

def _build_degraded_scan_plan(
    *,
    page_features: list[dict],
    total_pages: int,
    max_pages: int = _MAX_VISUAL_TOC_PAGES_TOTAL,
) -> dict:
    total = max(0, int(total_pages or 0))
    budget = max(1, min(int(max_pages or _MAX_VISUAL_TOC_PAGES_TOTAL), _MAX_VISUAL_TOC_PAGES_TOTAL))
    if total <= 0:
        return {
            "candidate_source": "degraded_window_expand",
            "primary_run_pages": [],
            "context_pages": [],
            "candidate_indices": [],
            "retry_indices": [],
            "run_summaries": [],
        }
    if total <= budget:
        all_pages = list(range(total))
        return {
            "candidate_source": "degraded_window_expand",
            "primary_run_pages": all_pages,
            "context_pages": [],
            "candidate_indices": all_pages,
            "retry_indices": [],
            "run_summaries": [
                {
                    "start_file_idx": 0,
                    "end_file_idx": max(0, total - 1),
                    "page_count": total,
                    "score": 0.0,
                    "header_role_counts": {"toc": 0, "index": 0, "other": 0},
                    "dot_leader_total": 0,
                    "numbered_line_total": 0,
                    "selected_as": "primary_run",
                }
            ],
        }

    enriched, feature_by_idx = _enrich_local_toc_features(page_features)
    del enriched
    front_end = min(total - 1, _DEGRADED_FRONT_WINDOW - 1)
    back_start = max(front_end + 1, total - _DEGRADED_BACK_WINDOW)
    selected: set[int] = set(range(0, front_end + 1)) | set(range(back_start, total))

    def _edge_is_toc(idx: int) -> bool:
        feature = feature_by_idx.get(int(idx))
        if not feature:
            return False
        return bool(
            str(feature.get("header_role") or "") == "toc"
            or float(feature.get("local_score", 0.0) or 0.0) >= 3.0
        )

    for _round in range(_DEGRADED_MAX_EXPAND_ROUNDS):
        if len(selected) >= budget:
            break
        expanded = False
        can_expand_front = front_end + 1 < back_start
        can_expand_back = back_start - 1 > front_end
        if can_expand_front and _edge_is_toc(front_end):
            for idx in range(front_end + 1, min(back_start, front_end + 1 + _DEGRADED_EXPAND_STEP)):
                if len(selected) >= budget:
                    break
                selected.add(idx)
                front_end = max(front_end, idx)
                expanded = True
        if can_expand_back and (_edge_is_toc(back_start) or _edge_is_toc(total - 1)):
            for idx in range(back_start - 1, max(front_end, back_start - _DEGRADED_EXPAND_STEP) - 1, -1):
                if len(selected) >= budget:
                    break
                selected.add(idx)
                back_start = min(back_start, idx)
                expanded = True
        if not expanded:
            break

    candidate_indices = _sorted_unique_indices(list(selected))[:budget]
    retry_indices = _expand_candidate_indices_for_retry(
        candidate_indices,
        total,
        radius=_VISUAL_RETRY_NEIGHBOR_RADIUS,
        max_extra_pages=_VISUAL_RETRY_MAX_EXTRA_PAGES,
    )

    run_summaries: list[dict] = []
    if candidate_indices:
        run_start = candidate_indices[0]
        current = [run_start]
        segments: list[list[int]] = []
        for idx in candidate_indices[1:]:
            if idx - current[-1] <= 1:
                current.append(idx)
            else:
                segments.append(current)
                current = [idx]
        segments.append(current)
        for seg_idx, segment in enumerate(segments):
            run_summaries.append(
                {
                    "start_file_idx": int(segment[0]),
                    "end_file_idx": int(segment[-1]),
                    "page_count": len(segment),
                    "score": 0.0,
                    "header_role_counts": {"toc": 0, "index": 0, "other": len(segment)},
                    "dot_leader_total": 0,
                    "numbered_line_total": 0,
                    "selected_as": "primary_run" if seg_idx == 0 else "secondary_run",
                }
            )

    return {
        "candidate_source": "degraded_window_expand",
        "primary_run_pages": candidate_indices,
        "context_pages": [],
        "candidate_indices": candidate_indices,
        "retry_indices": retry_indices,
        "run_summaries": run_summaries,
    }

def _choose_local_toc_scan_indices(page_features: list[dict], max_pages: int = _LOCAL_VISUAL_SCAN_MAX_PAGES) -> list[int]:
    plan = _build_local_scan_plan(
        page_features=page_features,
        total_pages=max(
            (_coerce_nonnegative_int(item.get("file_idx")) or -1) + 1
            for item in (page_features or [{}])
        ),
        max_pages=max_pages,
    )
    return list(plan.get("candidate_indices") or [])

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
    # 值在合理范围 [0, 4] 内，至少一行有黑块，不是全零。
    if not all(0 <= v <= 4 for v in values):
        return False
    if sum(values) == 0:
        return False
    # 只要 supports_vision=True 且返回了合理的 row_counts（4 个 [0,4] 整数且不全零），
    # 就认为模型支持视觉。不再要求精确网格计数——有些模型（如 MiMo V2.5）在极小方格
    # 计数上不稳定，但实际 TOC 文字识别能力完全正常。
    return True

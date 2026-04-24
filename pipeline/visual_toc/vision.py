"""visual TOC 视觉模型调用与 JSON 解析。"""

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


def _deep_merge_dict(base: dict, incoming: dict) -> dict:
    merged = dict(base or {})
    for key, value in dict(incoming or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _merge_request_overrides(create_kwargs: dict, request_overrides: dict | None) -> dict:
    if not isinstance(request_overrides, dict):
        return create_kwargs
    merged = dict(create_kwargs)
    for key, value in request_overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


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
from .organization import (
    _default_endnotes_summary,
    _finalize_endnotes_summary,
    _normalize_endnotes_summary,
    _normalize_visual_toc_page_item_rows,
    filter_visual_toc_items,
)
from .scan_plan import _normalize_header_hint, _vision_probe_passed
from .shared import VisionModelRequestError, _coerce_usage_int, _compact_usage_context

def confirm_model_supports_vision(
    spec,
    *,
    usage_events: list[dict] | None = None,
    trace_events: list[dict] | None = None,
    doc_id: str = "",
    slug: str = "",
) -> tuple[bool, str]:
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
        call_result = _call_vision_json(
            spec,
            prompt=prompt,
            images=[_build_vision_probe_data_url()],
            max_tokens=240,
            stage="visual_toc.preflight",
            usage_doc_id=doc_id,
            usage_slug=slug,
            usage_context={"probe": "vision_preflight"},
            reason_for_request="确认当前视觉模型是否可用",
        )
        parsed, usage_event, trace = _parse_vision_call_result(call_result)
        if usage_event and usage_events is not None:
            usage_events.append(usage_event)
        if trace and trace_events is not None:
            trace["derived_truth"] = {
                "supports_vision": bool((parsed or {}).get("supports_vision")) if isinstance(parsed, dict) else False,
                "row_counts": list((parsed or {}).get("row_counts") or []) if isinstance(parsed, dict) else [],
            }
            trace_events.append(trace)
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

def _classify_toc_candidates(
    spec,
    pdf_path: str,
    page_indices: list[int],
    *,
    usage_events: list[dict] | None = None,
    trace_events: list[dict] | None = None,
    doc_id: str = "",
    slug: str = "",
    trace_image_meta: list[dict[str, object] | None] | None = None,
) -> list[dict]:
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
            call_result = _call_vision_json(
                spec,
                prompt=prompt,
                images=images,
                max_tokens=900,
                stage="visual_toc.classify_candidates",
                usage_doc_id=doc_id,
                usage_slug=slug,
                usage_context={
                    "batch_start_file_idx": int(batch[0]),
                    "batch_end_file_idx": int(batch[-1]),
                    "batch_size": int(len(batch)),
                },
                reason_for_request="判断哪些页面是目录页，以缩小后续视觉目录抽取范围",
                trace_image_meta=(trace_image_meta or [])[start:start + len(batch)] if trace_image_meta else None,
            )
            parsed, usage_event, trace = _parse_vision_call_result(call_result)
            if usage_event and usage_events is not None:
                usage_events.append(usage_event)
        except Exception as exc:
            if isinstance(exc, VisionModelRequestError) and exc.status_code == 400 and not exc.retryable:
                raise
            parsed = []
            trace = {}
        parsed_list = parsed if isinstance(parsed, list) else []
        if trace and trace_events is not None:
            trace["derived_truth"] = {
                "classified_pages": parsed_list,
            }
            trace_events.append(trace)
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

def _extract_visual_toc_page_items_from_pdf(
    spec,
    pdf_path: str,
    file_idx: int,
    *,
    usage_events: list[dict] | None = None,
    trace_events: list[dict] | None = None,
    doc_id: str = "",
    slug: str = "",
    usage_stage: str = "visual_toc.extract_page_items",
) -> list[dict]:
    prompt = (
        "你会看到一页书籍目录截图。"
        "请只提取真正可导航的目录项，并按从上到下的顺序返回 JSON 数组。"
        "每项格式必须是 "
        '[{"title":"章节标题","depth":0,"printed_page":12,"visual_order":1,"role_hint":"content","endnotes_candidate":false,"endnotes_subentry_candidate":false}]。'
        "规则："
        "1. depth 只做单页粗粒度层级判断：顶层正文/前后附记为 0，容器如 Part/Book/COURS/APPENDICES/INDICES/Notes 可为 1，章内子项可更深；"
        "2. role_hint 只能是 container/content/back_matter 之一；"
        "3. container 只用于组织层标题，如 Part、Book、COURS、APPENDICES、INDICES、Notes；它们不是正文 chapter；"
        "4. content 包括正文 chapter、章内 section，以及 front_matter/post_body 这类有页码的可导航条目；back_matter 只用于 Bibliography、References、Index、Note on Sources（单行独立）这类参考性材料；"
        "5. 目录页总标题如 Contents、Sommaire、Table des matieres 不输出；标题下面很长的摘要、说明文字、介绍段落不能输出；纯数字孤立行不要单独输出；"
        "5. 没有可见页码就把 printed_page 设为 null，绝不猜测；"
        "6. Notes、Endnotes、Notes on the Text、Notes to the Chapters、Chapter Notes 这类尾注容器可额外标 endnotes_candidate=true；"
        "7. Notes to Chapter 1、Notes to Introduction、或尾注容器下按章分组的子条目可额外标 endnotes_subentry_candidate=true；"
        "8. 不要补全不可见文字，只做空白归一化。"
    )
    try:
        call_result = _call_vision_json(
            spec,
            prompt=prompt,
            images=[_bytes_to_data_url(render_pdf_page(pdf_path, file_idx, scale=2.0))],
            max_tokens=2200,
            stage=usage_stage,
            usage_doc_id=doc_id,
            usage_slug=slug,
            usage_context={"source": "pdf", "file_idx": int(file_idx)},
            reason_for_request="从目录页截图中抽取单页原子目录项",
            trace_image_meta=[{"source_path": str(pdf_path), "file_idx": int(file_idx), "source": "pdf_page"}],
        )
        parsed, usage_event, trace = _parse_vision_call_result(call_result)
        if usage_event and usage_events is not None:
            usage_events.append(usage_event)
        if trace and trace_events is not None:
            normalized = _normalize_visual_toc_page_item_rows(parsed if isinstance(parsed, list) else [])
            trace["derived_truth"] = {"items": normalized}
            trace_events.append(trace)
    except Exception as exc:
        if isinstance(exc, VisionModelRequestError) and exc.status_code == 400 and not exc.retryable:
            raise
        return []
    return _normalize_visual_toc_page_item_rows(parsed if isinstance(parsed, list) else [])

def _extract_visual_toc_page_items_from_image(
    spec,
    image_path: str,
    *,
    usage_events: list[dict] | None = None,
    trace_events: list[dict] | None = None,
    doc_id: str = "",
    slug: str = "",
    usage_stage: str = "visual_toc.manual_input_extract",
) -> list[dict]:
    prompt = (
        "你会看到一页书籍目录截图。"
        "请只提取真正可导航的目录项，并按从上到下的顺序返回 JSON 数组。"
        "每项格式必须是 "
        '[{"title":"章节标题","depth":0,"printed_page":12,"visual_order":1,"role_hint":"content","endnotes_candidate":false,"endnotes_subentry_candidate":false}]。'
        "规则："
        "1. depth 只做单页粗粒度层级判断：顶层正文/前后附记为 0，容器如 Part/Book/COURS/APPENDICES/INDICES/Notes 可为 1，章内子项可更深；"
        "2. role_hint 只能是 container/content/back_matter 之一；"
        "3. container 只用于组织层标题，如 Part、Book、COURS、APPENDICES、INDICES、Notes；它们不是正文 chapter；"
        "4. content 包括正文 chapter、章内 section，以及 front_matter/post_body 这类有页码的可导航条目；back_matter 只用于 Bibliography、References、Index、Note on Sources（单行独立）这类参考性材料；"
        "5. 目录页总标题如 Contents、Sommaire、Table des matieres 不输出；标题下面很长的摘要、说明文字、介绍段落不能输出；纯数字孤立行不要单独输出；"
        "5. 没有可见页码就把 printed_page 设为 null，绝不猜测；"
        "6. Notes、Endnotes、Notes on the Text、Notes to the Chapters、Chapter Notes 这类尾注容器可额外标 endnotes_candidate=true；"
        "7. Notes to Chapter 1、Notes to Introduction、或尾注容器下按章分组的子条目可额外标 endnotes_subentry_candidate=true；"
        "8. 不要补全不可见文字，只做空白归一化。"
    )
    try:
        call_result = _call_vision_json(
            spec,
            prompt=prompt,
            images=[_bytes_to_data_url(_read_image_bytes(image_path))],
            max_tokens=2200,
            stage=usage_stage,
            usage_doc_id=doc_id,
            usage_slug=slug,
            usage_context={"source": "image", "name": os.path.basename(image_path)},
            reason_for_request="从手动上传的目录图片中抽取单页原子目录项",
            trace_image_meta=[{"source_path": str(image_path), "source": "manual_image"}],
        )
        parsed, usage_event, trace = _parse_vision_call_result(call_result)
        if usage_event and usage_events is not None:
            usage_events.append(usage_event)
        if trace and trace_events is not None:
            normalized = _normalize_visual_toc_page_item_rows(parsed if isinstance(parsed, list) else [])
            trace["derived_truth"] = {"items": normalized}
            trace_events.append(trace)
    except Exception as exc:
        if isinstance(exc, VisionModelRequestError) and exc.status_code == 400 and not exc.retryable:
            raise
        return []
    return _normalize_visual_toc_page_item_rows(parsed if isinstance(parsed, list) else [])

def _extract_visual_toc_organization_bundle_from_images(
    spec,
    *,
    images: list[str],
    seed_titles: list[str] | None = None,
    usage_events: list[dict] | None = None,
    trace_events: list[dict] | None = None,
    doc_id: str = "",
    slug: str = "",
    usage_stage: str = "visual_toc.manual_input_extract",
    trace_image_meta: list[dict[str, object] | None] | None = None,
) -> dict:
    if not images:
        return {"items": [], "endnotes_summary": _default_endnotes_summary()}
    seed_block = ""
    compact_seed_titles = [str(title or "").strip() for title in (seed_titles or []) if str(title or "").strip()]
    if compact_seed_titles:
        seed_block = "已抽到的目录标题草稿如下，请优先沿用可见标题原文和顺序，但可以补回漏掉的容器层：\n" + "\n".join(
            f"- {title}" for title in compact_seed_titles[:80]
        )
    prompt = (
        "你会依次看到一整份书籍目录页截图。"
        "请按整份目录的真实组织方式输出 JSON 对象，不要只做扁平标题提取。"
        '输出格式必须是 {"endnotes_summary":{"present":false,"container_title":null,"container_printed_page":null,"container_visual_order":null,"has_chapter_keyed_subentries_in_toc":false,"subentry_pattern":null},"items":[{"title":"章节标题","depth":0,"visual_order":1,"printed_page":12,"role_hint":"chapter","parent_title":"Part One"}]}。'
        "规则："
        "1. 必须保留无页码的容器层，例如 Part、Book、COURS、INDICES、APPENDICES；这些条目是 container，不是 chapter。"
        "2. chapter 是正文里最独立的可导航单元：显式编号章，以及有正文页码的 Introduction、Conclusion、Préambule、单独 Epilogue。chapter 挂在容器下时仍然是 chapter，不会因为容器存在而变成 section。"
        "3. front_matter 只用于第一条正文 chapter 之前的辅助材料，如 Acknowledgments、Remerciements、Preface、Foreword、List of Abbreviations、List of Illustrations。"
        "4. back_matter 只用于书末参考性材料，如 Bibliography、References、Index、Indices、Works Cited，以及单行独立的 Note on Sources。"
        "5. post_body 只用于最后一条正文 chapter 之后、back_matter 之前的实质性内容，如 RÉSUMÉ、SITUATION、Postambule、独立带页码的 Appendix。"
        "6. 书末独立的 Notes、Endnotes、Notes on the Text、Notes to the Chapters、Chapter Notes 是 endnotes 容器，不改变正文 chapter 的层级基准；Bibliography、References、Index 永远不要标成 endnotes。"
        "7. Note on Sources 只有在下方有按章 notes 子项时才允许判成 endnotes；如果只是单行独立条目，固定判成 back_matter。"
        "8. 如果目录里列出了尾注容器下按章分组的子条目，这些子条目标成 section，parent_title 写尾注容器标题。"
        "9. 目录页总标题如 Contents、Sommaire 不输出；标题下方的说明性斜体副标题、摘要句、时间说明如果不是独立可导航标题，不输出。"
        "10. parent_title 只写直接父标题；最顶层为空字符串；没有可见页码就把 printed_page 设为 null；请保持从前到后、从上到下的视觉顺序。"
        f"{seed_block}"
    )
    try:
        call_result = _call_vision_json(
            spec,
            prompt=prompt,
            images=images,
            max_tokens=3200,
            stage=usage_stage,
            usage_doc_id=doc_id,
            usage_slug=slug,
            usage_context={"source": "organization", "images_count": int(len(images))},
            reason_for_request="根据整份目录页重建目录树，并识别尾注容器与子项",
            trace_image_meta=trace_image_meta,
        )
        parsed, usage_event, trace = _parse_vision_call_result(call_result)
        if usage_event and usage_events is not None:
            usage_events.append(usage_event)
    except Exception as exc:
        if isinstance(exc, VisionModelRequestError) and exc.status_code == 400 and not exc.retryable:
            raise
        return {"items": [], "endnotes_summary": _default_endnotes_summary()}
    if not isinstance(parsed, dict):
        return {"items": [], "endnotes_summary": _default_endnotes_summary()}
    items = filter_visual_toc_items(list(parsed.get("items") or []))
    bundle = {
        "items": items,
        "endnotes_summary": _normalize_endnotes_summary(parsed.get("endnotes_summary")),
    }
    if trace and trace_events is not None:
        trace["derived_truth"] = {
            "items": list(bundle.get("items") or []),
            "endnotes_summary": dict(bundle.get("endnotes_summary") or {}),
        }
        trace_events.append(trace)
    return bundle

def _extract_visual_toc_organization_nodes_from_images(
    spec,
    *,
    images: list[str],
    seed_titles: list[str] | None = None,
    usage_events: list[dict] | None = None,
    trace_events: list[dict] | None = None,
    doc_id: str = "",
    slug: str = "",
    usage_stage: str = "visual_toc.manual_input_extract",
    trace_image_meta: list[dict[str, object] | None] | None = None,
) -> list[dict]:
    bundle = _extract_visual_toc_organization_bundle_from_images(
        spec,
        images=images,
        seed_titles=seed_titles,
        usage_events=usage_events,
        trace_events=trace_events,
        doc_id=doc_id,
        slug=slug,
        usage_stage=usage_stage,
        trace_image_meta=trace_image_meta,
    )
    return list(bundle.get("items") or [])

def _extract_vision_error_detail(exc: Exception) -> tuple[int | None, str]:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None) if response is not None else None
    detail = str(exc or "").strip()
    if response is not None:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                err = payload.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("message") or err.get("code") or detail or "").strip()
                elif err:
                    detail = str(err).strip()
        except Exception:
            try:
                raw = str(getattr(response, "text", "") or "").strip()
                if raw:
                    detail = raw
            except Exception:
                pass
    if len(detail) > 280:
        detail = detail[:280] + "..."
    return status_code, detail

def _build_vision_usage_event(
    response,
    *,
    stage: str,
    spec,
    doc_id: str = "",
    slug: str = "",
    context: dict | None = None,
) -> dict:
    usage = getattr(response, "usage", None)
    prompt_tokens = _coerce_usage_int(getattr(usage, "prompt_tokens", 0)) if usage is not None else 0
    completion_tokens = _coerce_usage_int(getattr(usage, "completion_tokens", 0)) if usage is not None else 0
    raw_total = getattr(usage, "total_tokens", None) if usage is not None else None
    total_tokens = _coerce_usage_int(raw_total if raw_total is not None else (prompt_tokens + completion_tokens))
    provider = str(getattr(spec, "provider", "") or "").strip() or "unknown"
    model_id = str(getattr(spec, "model_id", "") or "").strip() or "unknown"
    event = {
        "stage": str(stage or "").strip() or "unknown",
        "provider": provider,
        "model_id": model_id,
        "request_count": 1,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "total_tokens": int(total_tokens),
        "doc_id": str(doc_id or "").strip(),
        "slug": str(slug or "").strip(),
        "context": _compact_usage_context(context),
    }
    return event

def _parse_vision_call_result(call_result) -> tuple[object, dict, dict]:
    if isinstance(call_result, dict) and "parsed" in call_result:
        return (
            call_result.get("parsed"),
            dict(call_result.get("usage_event") or {}),
            dict(call_result.get("trace") or {}),
        )
    return call_result, {}, {}

def _image_trace_entry(
    image,
    *,
    fallback_label: str = "",
    trace_meta: dict[str, object] | None = None,
) -> dict[str, object]:
    file_idx = None
    data_url = image
    if isinstance(image, tuple):
        file_idx = image[0]
        data_url = image[1]
    raw_bytes = b""
    data_url_text = str(data_url or "")
    if data_url_text.startswith("data:") and "," in data_url_text:
        try:
            raw_bytes = base64.b64decode(data_url_text.split(",", 1)[1])
        except Exception:
            raw_bytes = b""
    entry: dict[str, object] = {
        "label": str(fallback_label or "").strip(),
        "file_idx": int(file_idx) if file_idx is not None else None,
        "byte_size": len(raw_bytes),
        "sha256": hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else "",
    }
    for key, value in dict(trace_meta or {}).items():
        if value is None:
            continue
        entry[str(key)] = value
    return entry

def _call_vision_json(
    spec,
    *,
    prompt: str,
    images: list,
    max_tokens: int = 1200,
    stage: str = "vision_call",
    usage_doc_id: str = "",
    usage_slug: str = "",
    usage_context: dict | None = None,
    reason_for_request: str = "",
    trace_image_meta: list[dict[str, object] | None] | None = None,
):
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
    create_kwargs.setdefault("timeout", 90.0)
    request_overrides = getattr(spec, "request_overrides", None)
    if isinstance(request_overrides, dict):
        create_kwargs = _merge_request_overrides(create_kwargs, request_overrides)
    started = time.time()
    try:
        response = client.chat.completions.create(**create_kwargs)
    except Exception as exc:
        status_code, detail = _extract_vision_error_detail(exc)
        retryable = status_code in {429, 500, 502, 503, 504}
        message = f"{stage} 视觉请求失败"
        if status_code is not None:
            message += f"（HTTP {status_code}）"
        if detail:
            message += f"：{detail}"
        raise VisionModelRequestError(
            message,
            stage=stage,
            status_code=status_code,
            retryable=retryable,
            detail=detail,
        ) from exc
    text = _extract_message_text(response)
    duration_ms = int(max(0.0, (time.time() - started) * 1000.0))
    image_entries: list[dict[str, object]] = []
    for index, image in enumerate(images or [], start=1):
        image_entries.append(
            _image_trace_entry(
                image,
                fallback_label=f"image-{index}",
                trace_meta=(trace_image_meta or [])[index - 1] if trace_image_meta and index - 1 < len(trace_image_meta) else None,
            )
        )
    return {
        "parsed": _parse_json_payload(text),
        "usage_event": _build_vision_usage_event(
            response,
            stage=stage,
            spec=spec,
            doc_id=usage_doc_id,
            slug=usage_slug,
            context=usage_context,
        ),
        "trace": {
            "stage": str(stage or "").strip() or "vision_call",
            "reason_for_request": str(reason_for_request or "").strip(),
            "model": {
                "provider": str(getattr(spec, "provider", "") or "").strip() or "unknown",
                "model_id": str(getattr(spec, "model_id", "") or "").strip() or "unknown",
                "base_url": str(getattr(spec, "base_url", "") or "").strip(),
            },
            "request_prompt": str(prompt or ""),
            "request_content": {
                "images": image_entries,
            },
            "request_context_summary": _compact_usage_context(usage_context),
            "response_raw_text": text,
            "response_parsed": _parse_json_payload(text),
            "derived_truth": {},
            "usage": _build_vision_usage_event(
                response,
                stage=stage,
                spec=spec,
                doc_id=usage_doc_id,
                slug=usage_slug,
                context=usage_context,
            ),
            "timing": {"duration_ms": duration_ms},
        },
    }

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

def _read_image_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()

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

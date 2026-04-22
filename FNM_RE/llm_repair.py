"""FNM unresolved cluster 的 LLM 修补。"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import signal
import time
from contextlib import contextmanager
from typing import Any

from openai import OpenAI
from rapidfuzz.fuzz import partial_ratio_alignment

from config import QWEN_BASE_URLS, get_dashscope_key, get_visual_custom_model_config
from document.pdf_extract import render_pdf_page
from FNM_RE.shared.notes import normalize_note_marker
from persistence.sqlite_store import SQLiteRepository
from persistence.storage import get_pdf_path
from translation.translator import _build_usage, _classify_provider_exception, _extract_openai_message_text


_JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# 官方模型列表写明 qwen3.5-plus 上下文长度为 1,000,000 token，
# 最大输入在思考模式下为 983,616 token、非思考模式下为 991,808 token。
QWEN35_PLUS_CONTEXT_TOKENS = 1_000_000
QWEN35_PLUS_MAX_INPUT_TOKENS_THINKING = 983_616
QWEN35_PLUS_MAX_INPUT_TOKENS_NO_THINK = 991_808

# LLM repair 只做 unresolved 小块修补，软预算故意压得远低于模型上限，
# 目的是降低延迟，而不是去吃满上下文。
LLM_REPAIR_SOFT_INPUT_TOKEN_BUDGET = 2_048
LLM_REPAIR_MAX_OUTPUT_TOKENS = 768
LLM_REPAIR_MAX_MATCHED_EXAMPLES = 2
LLM_REPAIR_MAX_UNMATCHED_DEFINITIONS = 8
LLM_REPAIR_MAX_UNMATCHED_REFS = 8
LLM_REPAIR_MAX_FOCUS_PAGES = 8
LLM_REPAIR_FOOTNOTE_PAGE_PADDING = 1

# Tier 1 fuzzy anchor synthesis:
# 当正文里找不到结构化 anchor 时，让 LLM 给出正文里的唯一短语片段，
# 再用 rapidfuzz 在本章正文里模糊定位，落地为一个真实坐标的 anchor。
FUZZY_SCORE_THRESHOLD = 88
# 过去按"簇内孤儿数 ≥3 才允许 synth 自动应用"做防抖，
# 但 cluster 是按 chapter×region 切的，单章单 region 常只带 1 条孤儿，
# 这样会把所有 fuzzy≥88 且 conf≥0.9 的高置信 synth 全部拦截。
# 现在保留 fuzzy / 置信度 / 非歧义三道闸，把簇内下限降到 1。
MIN_CHAPTER_UNMATCHED_FOR_AUTO = 1
FUZZY_AMBIGUITY_MARGIN = 5.0
_LLM_REPAIR_USAGE_STAGE = "llm_repair.cluster_request"


def _coerce_usage_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _compact_usage_context(context: dict | None) -> dict:
    if not isinstance(context, dict):
        return {}
    compact: dict[str, object] = {}
    for key, value in context.items():
        if value is None:
            continue
        if isinstance(value, (int, float, bool)):
            compact[str(key)] = value
            continue
        text = str(value).strip()
        if not text:
            continue
        compact[str(key)] = text[:96] + ("..." if len(text) > 96 else "")
    return compact


def _summarize_usage_events(
    events: list[dict] | None,
    *,
    required_stages: tuple[str, ...] = (),
) -> dict:
    by_stage: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    total = {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    for event in events or []:
        stage = str(event.get("stage") or "").strip() or "unknown"
        model_id = str(event.get("model_id") or "").strip() or "unknown"
        usage = {
            "request_count": _coerce_usage_int(event.get("request_count")),
            "prompt_tokens": _coerce_usage_int(event.get("prompt_tokens")),
            "completion_tokens": _coerce_usage_int(event.get("completion_tokens")),
            "total_tokens": _coerce_usage_int(event.get("total_tokens")),
        }
        stage_row = by_stage.setdefault(
            stage,
            {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        model_row = by_model.setdefault(
            model_id,
            {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        for key, value in usage.items():
            stage_row[key] += int(value)
            model_row[key] += int(value)
            total[key] += int(value)
    for stage in required_stages:
        by_stage.setdefault(
            stage,
            {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
    return {"by_stage": by_stage, "by_model": by_model, "total": total}


@contextmanager
def _time_limit(seconds: int):
    if seconds <= 0:
        yield
        return

    def _handler(_signum, _frame):
        raise TimeoutError(f"LLM repair request timed out after {seconds}s")

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _chapter_title_by_id(chapters: list[dict]) -> dict[str, str]:
    return {
        str(chapter.get("chapter_id") or ""): str(chapter.get("title") or "").strip()
        for chapter in chapters or []
    }


def _index_by_key(items: list[dict], key: str) -> dict[str, dict]:
    return {
        str(item.get(key) or "").strip(): dict(item)
        for item in items or []
        if str(item.get(key) or "").strip()
    }


def _cluster_page_range(cluster: dict) -> tuple[int | None, int | None]:
    pages: list[int] = []
    for note_item in cluster.get("unmatched_note_items") or []:
        try:
            value = int(note_item.get("page_no") or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            pages.append(value)
    for anchor in cluster.get("unmatched_anchors") or []:
        try:
            value = int(anchor.get("page_no") or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            pages.append(value)
    if not pages:
        return (None, None)
    return (min(pages), max(pages))


def build_unresolved_clusters(
    *,
    chapters: list[dict],
    note_items: list[dict],
    body_anchors: list[dict],
    note_links: list[dict],
) -> list[dict]:
    chapter_titles = _chapter_title_by_id(chapters)
    note_items_by_id = _index_by_key(note_items, "note_item_id")
    anchors_by_id = _index_by_key(body_anchors, "anchor_id")
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}

    for link in note_links or []:
        note_system = str(link.get("note_kind") or "").strip()
        status = str(link.get("status") or "").strip()
        if note_system not in {"endnote", "footnote"}:
            continue
        if status not in {"matched", "orphan_note", "orphan_anchor", "ambiguous"}:
            continue
        chapter_id = str(link.get("chapter_id") or "").strip()
        region_id = str(link.get("region_id") or "").strip() or chapter_id
        key = (chapter_id, region_id, note_system)
        cluster = grouped.setdefault(
            key,
            {
                "cluster_id": f"{chapter_id}:{region_id}:{note_system}",
                "chapter_id": chapter_id,
                "chapter_title": chapter_titles.get(chapter_id, chapter_id),
                "region_id": region_id,
                "note_system": note_system,
                "matched_examples": [],
                "unmatched_note_items": [],
                "unmatched_anchors": [],
            },
        )
        if status == "matched":
            note_item = note_items_by_id.get(str(link.get("note_item_id") or "").strip())
            anchor = anchors_by_id.get(str(link.get("anchor_id") or "").strip())
            if note_item and anchor:
                cluster["matched_examples"].append(
                    {
                        "link_id": str(link.get("link_id") or ""),
                        "note_item_id": note_item["note_item_id"],
                        "anchor_id": anchor["anchor_id"],
                        "marker": str(link.get("marker") or note_item.get("marker") or "").strip(),
                        "note_excerpt": str(note_item.get("source_text") or "").strip(),
                        "anchor_excerpt": str(anchor.get("source_text") or "").strip(),
                    }
                )
            continue
        if status in {"orphan_note", "ambiguous"}:
            note_item = note_items_by_id.get(str(link.get("note_item_id") or "").strip())
            if note_item:
                cluster["unmatched_note_items"].append(note_item)
        if status in {"orphan_anchor", "ambiguous"}:
            anchor = anchors_by_id.get(str(link.get("anchor_id") or "").strip())
            if anchor:
                cluster["unmatched_anchors"].append(anchor)

    clusters: list[dict] = []
    for cluster in grouped.values():
        note_item_seen: set[str] = set()
        anchor_seen: set[str] = set()
        cluster["matched_examples"] = cluster["matched_examples"][:3]
        cluster["unmatched_note_items"] = [
            item
            for item in cluster["unmatched_note_items"]
            if not (item["note_item_id"] in note_item_seen or note_item_seen.add(item["note_item_id"]))
        ]
        cluster["unmatched_anchors"] = [
            item
            for item in cluster["unmatched_anchors"]
            if not (item["anchor_id"] in anchor_seen or anchor_seen.add(item["anchor_id"]))
        ]
        if not cluster["unmatched_note_items"] and not cluster["unmatched_anchors"]:
            continue
        page_start, page_end = _cluster_page_range(cluster)
        cluster["page_start"] = page_start
        cluster["page_end"] = page_end
        cluster_pages = {
            int(page_no)
            for page_no in (
                [item.get("page_no") for item in (cluster.get("unmatched_note_items") or [])]
                + [item.get("page_no") for item in (cluster.get("unmatched_anchors") or [])]
            )
            if str(page_no or "").strip()
        }
        rebind_candidates: list[dict[str, Any]] = []
        seen_note_item_ids: set[str] = set()
        for link in note_links or []:
            if str(link.get("status") or "") != "matched":
                continue
            if str(link.get("chapter_id") or "").strip() != str(cluster.get("chapter_id") or "").strip():
                continue
            if str(link.get("note_kind") or "").strip() != str(cluster.get("note_system") or "").strip():
                continue
            note_item = note_items_by_id.get(str(link.get("note_item_id") or "").strip())
            anchor = anchors_by_id.get(str(link.get("anchor_id") or "").strip())
            if not note_item or not anchor:
                continue
            try:
                note_page_no = int(note_item.get("page_no") or 0)
            except (TypeError, ValueError):
                note_page_no = 0
            try:
                anchor_page_no = int(anchor.get("page_no") or 0)
            except (TypeError, ValueError):
                anchor_page_no = 0
            if cluster_pages and note_page_no not in cluster_pages and anchor_page_no not in cluster_pages:
                continue
            current_anchor_id = str(link.get("anchor_id") or "").strip()
            current_anchor_is_synthetic = bool(anchor.get("synthetic")) or current_anchor_id.startswith("synthetic-")
            if not (
                current_anchor_is_synthetic
                or note_page_no != anchor_page_no
            ):
                continue
            note_item_id = str(note_item.get("note_item_id") or "").strip()
            if not note_item_id or note_item_id in seen_note_item_ids:
                continue
            seen_note_item_ids.add(note_item_id)
            rebind_candidates.append(
                {
                    "link_id": str(link.get("link_id") or ""),
                    "note_item_id": note_item_id,
                    "current_anchor_id": current_anchor_id,
                    "marker": str(note_item.get("marker") or link.get("marker") or "").strip(),
                    "note_page_no": note_page_no,
                    "anchor_page_no": anchor_page_no,
                    "current_anchor_marker": str(
                        anchor.get("normalized_marker") or anchor.get("source_marker") or ""
                    ).strip(),
                    "note_excerpt": str(note_item.get("source_text") or "").strip(),
                    "anchor_excerpt": str(anchor.get("source_text") or "").strip(),
                    "current_anchor_synthetic": current_anchor_is_synthetic,
                }
            )
        if rebind_candidates:
            cluster["rebind_candidates"] = rebind_candidates[:8]
        clusters.append(cluster)
    clusters.sort(
        key=lambda item: (
            -(len(item.get("unmatched_note_items") or []) + len(item.get("unmatched_anchors") or [])),
            int(item.get("page_start") or 0),
            str(item.get("cluster_id") or ""),
        )
    )
    return clusters


def locate_anchor_phrase_in_body(body_text: str, phrase: str) -> dict:
    """在正文里用 rapidfuzz 模糊定位 anchor 短语。

    返回字段：
      - hit (bool): 是否达到 FUZZY_SCORE_THRESHOLD。
      - score (float): rapidfuzz partial_ratio 分数（0-100）。
      - char_start / char_end (int): 命中区间在 body 内的字符偏移。
      - matched_text (str): body[char_start:char_end]。
      - ambiguous (bool): 把主命中替换后再扫一次，若次命中分数仍 >= 主命中 - FUZZY_AMBIGUITY_MARGIN，视为歧义。

    未命中时 char_start / char_end 返回 -1，matched_text 返回空串。
    """
    text = str(body_text or "")
    needle = str(phrase or "").strip()
    empty = {
        "hit": False,
        "score": 0.0,
        "char_start": -1,
        "char_end": -1,
        "matched_text": "",
        "ambiguous": False,
    }
    if not text or not needle:
        return empty

    alignment = partial_ratio_alignment(needle, text)
    if alignment is None:
        return empty

    primary_score = float(alignment.score)
    dest_start = int(alignment.dest_start)
    dest_end = int(alignment.dest_end)
    matched_text = text[dest_start:dest_end]

    ambiguous = False
    if primary_score >= FUZZY_SCORE_THRESHOLD:
        masked = text[:dest_start] + (" " * (dest_end - dest_start)) + text[dest_end:]
        second = partial_ratio_alignment(needle, masked)
        if second is not None and float(second.score) >= max(
            FUZZY_SCORE_THRESHOLD, primary_score - FUZZY_AMBIGUITY_MARGIN
        ):
            ambiguous = True

    return {
        "hit": primary_score >= FUZZY_SCORE_THRESHOLD,
        "score": primary_score,
        "char_start": dest_start,
        "char_end": dest_end,
        "matched_text": matched_text,
        "ambiguous": ambiguous,
    }


def _repair_system_prompt() -> str:
    return (
        "你是 FNM 注释修补助手（同时处理 endnote 和 footnote 两种 note_system）。"
        "只处理已经确认的 unresolved cluster，不要改 section、note zone、标题或原文。"
        "优先依据页面截图判断，不要被 OCR 坏掉的数字误导。"
        "如果截图已经足够清楚，就不要退回 needs_review。"
        "你只能输出 JSON 数组；每项 action 只能是 match、ignore_ref、synthesize_anchor、synthesize_note_item 或 needs_review。"
        "match 需要 note_item_id、anchor_id、confidence、reason；"
        "ignore_ref 需要 anchor_id、confidence、reason；"
        "synthesize_anchor 仅在正文里能找到一个独一无二的短语锚点、但该锚点没有对应的结构化 anchor 记录时使用，"
        "需要 note_item_id、anchor_phrase（从正文中原样抄写的 3~12 词唯一短语，不要自编）、confidence、reason；"
        "synthesize_note_item 仅在截图里能清楚看到同页注释文本、但 OCR / 结构化流程完全没产出 note item 时使用，"
        "需要 anchor_id、marker、note_text、confidence、reason；"
        "若某条 note 当前只是错误地绑到了 synthetic / 跨页锚点，而截图清楚显示它应改绑到当前显式锚点，也直接用 match，不要 needs_review。"
        "needs_review 需要 reason。"
    )


def _trim_excerpt(text: str, limit: int = 240) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(raw) <= limit:
        return raw
    return raw[:limit].rstrip() + " ..."


def _estimate_prompt_tokens(text: str) -> int:
    raw = str(text or "")
    if not raw:
        return 0
    cjk_count = len(_CJK_CHAR_RE.findall(raw))
    non_cjk_count = max(0, len(raw) - cjk_count)
    # 这是保守估算，只用于 repair 小请求的软预算监控，不作为精确计费值。
    return int(cjk_count + math.ceil(non_cjk_count / 3.5) + 16)


def _slice_cluster_for_request(
    cluster: dict,
    *,
    max_matched_examples: int | None = None,
    max_unmatched_note_items: int | None = None,
    max_unmatched_anchors: int | None = None,
) -> dict:
    cap_matched = int(max_matched_examples) if max_matched_examples else LLM_REPAIR_MAX_MATCHED_EXAMPLES
    cap_notes = int(max_unmatched_note_items) if max_unmatched_note_items else LLM_REPAIR_MAX_UNMATCHED_DEFINITIONS
    cap_anchors = int(max_unmatched_anchors) if max_unmatched_anchors else LLM_REPAIR_MAX_UNMATCHED_REFS
    matched_examples = list(cluster.get("matched_examples") or [])[:cap_matched]
    unmatched_note_items = list(cluster.get("unmatched_note_items") or [])[:cap_notes]
    unmatched_anchors = list(cluster.get("unmatched_anchors") or [])[:cap_anchors]
    rebind_candidates = list(cluster.get("rebind_candidates") or [])[:cap_notes]
    has_body_text = bool(str(cluster.get("chapter_body_text") or "").strip())
    has_page_context = bool(list(cluster.get("page_contexts") or []))
    allowed_actions = ["needs_review"]
    request_mode = "review_only"
    if unmatched_note_items and unmatched_anchors:
        allowed_actions = ["match", "ignore_ref", "needs_review"]
        request_mode = "paired"
        if has_body_text:
            allowed_actions = ["match", "ignore_ref", "synthesize_anchor", "needs_review"]
    elif unmatched_anchors and rebind_candidates:
        allowed_actions = ["match", "ignore_ref", "needs_review"]
        request_mode = "anchor_rebind"
        # P0-1: 当 rebind_candidates 不能覆盖所有 unmatched_anchors 且有截图上下文时，
        # 追加 synthesize_note_item 以处理没有 rebind candidate 的孤儿 anchor。
        if has_page_context and len(unmatched_anchors) > len(rebind_candidates):
            allowed_actions = ["match", "ignore_ref", "synthesize_note_item", "needs_review"]
    elif unmatched_anchors:
        allowed_actions = ["ignore_ref", "needs_review"]
        request_mode = "ref_only"
        if has_page_context:
            allowed_actions = ["ignore_ref", "synthesize_note_item", "needs_review"]
            request_mode = "ref_only_visual"
    elif unmatched_note_items:
        if has_body_text:
            allowed_actions = ["synthesize_anchor", "needs_review"]
            request_mode = "note_only_with_body"
        else:
            allowed_actions = ["needs_review"]
            request_mode = "note_only"
    request_cluster = dict(cluster)
    request_cluster["matched_examples"] = matched_examples
    request_cluster["unmatched_note_items"] = unmatched_note_items
    request_cluster["unmatched_anchors"] = unmatched_anchors
    request_cluster["rebind_candidates"] = rebind_candidates
    request_cluster["allowed_actions"] = allowed_actions
    request_cluster["request_mode"] = request_mode
    request_cluster["request_caps"] = {
        "matched_examples": cap_matched,
        "unmatched_note_items": cap_notes,
        "unmatched_anchors": cap_anchors,
    }
    return request_cluster


def _repair_user_prompt(
    cluster: dict,
    *,
    max_matched_examples: int | None = None,
    max_unmatched_note_items: int | None = None,
    max_unmatched_anchors: int | None = None,
) -> str:
    request_cluster = _slice_cluster_for_request(
        cluster,
        max_matched_examples=max_matched_examples,
        max_unmatched_note_items=max_unmatched_note_items,
        max_unmatched_anchors=max_unmatched_anchors,
    )
    allowed_actions = list(request_cluster.get("allowed_actions") or ["needs_review"])
    payload = {
        "cluster_id": request_cluster.get("cluster_id"),
        "chapter_title": request_cluster.get("chapter_title"),
        "page_range": [request_cluster.get("page_start"), request_cluster.get("page_end")],
        "note_system": request_cluster.get("note_system"),
        "request_mode": request_cluster.get("request_mode"),
        "allowed_actions": allowed_actions,
        "page_contexts": [
            {
                "page_no": item.get("page_no"),
                "ocr_excerpt": _trim_excerpt(item.get("ocr_excerpt"), limit=1200),
            }
            for item in (request_cluster.get("page_contexts") or [])
        ],
        "matched_examples": [
            {
                "note_item_id": item.get("note_item_id"),
                "anchor_id": item.get("anchor_id"),
                "marker": item.get("marker"),
                "note_excerpt": _trim_excerpt(item.get("note_excerpt")),
                "anchor_excerpt": _trim_excerpt(item.get("anchor_excerpt")),
            }
            for item in (request_cluster.get("matched_examples") or [])
        ],
        "unmatched_note_items": [
            {
                "note_item_id": item.get("note_item_id"),
                "marker": item.get("marker"),
                "page_no": item.get("page_no"),
                "source_text": _trim_excerpt(item.get("source_text")),
            }
            for item in (request_cluster.get("unmatched_note_items") or [])
        ],
        "unmatched_anchors": [
            {
                "anchor_id": item.get("anchor_id"),
                "marker": item.get("normalized_marker") or item.get("source_marker"),
                "page_no": item.get("page_no"),
                "paragraph_index": item.get("paragraph_index"),
                "source_text": _trim_excerpt(item.get("source_text")),
            }
            for item in (request_cluster.get("unmatched_anchors") or [])
        ],
        "rebind_candidates": [
            {
                "link_id": item.get("link_id"),
                "note_item_id": item.get("note_item_id"),
                "current_anchor_id": item.get("current_anchor_id"),
                "marker": item.get("marker"),
                "note_page_no": item.get("note_page_no"),
                "anchor_page_no": item.get("anchor_page_no"),
                "current_anchor_marker": item.get("current_anchor_marker"),
                "current_anchor_synthetic": item.get("current_anchor_synthetic"),
                "note_excerpt": _trim_excerpt(item.get("note_excerpt")),
                "anchor_excerpt": _trim_excerpt(item.get("anchor_excerpt")),
            }
            for item in (request_cluster.get("rebind_candidates") or [])
        ],
    }
    chapter_body_text = str(request_cluster.get("chapter_body_text") or "").strip()
    if chapter_body_text and "synthesize_anchor" in allowed_actions:
        payload["chapter_body_excerpt"] = _trim_excerpt(chapter_body_text, limit=1800)
    action_hint = "、".join(allowed_actions)
    extra_rules = ""
    if "synthesize_anchor" in allowed_actions:
        extra_rules = (
            "\n若正文里确实能找到某条孤儿尾注对应的独一无二短语，且该短语没有对应的结构化 anchor 记录，"
            "才用 synthesize_anchor；anchor_phrase 必须逐字摘自 chapter_body_excerpt，长度 3~12 词，"
            "禁止自编、禁止填章节其他地方或通用短语。"
        )
    if "synthesize_note_item" in allowed_actions:
        extra_rules += (
            "\n若截图里清楚看到同页注释文本、但 OCR / 结构化数据里没有 note item，"
            "优先用 synthesize_note_item；marker 必须是截图上可见的数字，"
            "note_text 只抄注释正文，不要自编，不要补全看不清的部分。"
        )
    return (
        "/no_think\n"
        "下面是一个 FNM unresolved cluster。请只返回 JSON 数组，不要解释。\n"
        f"本次只允许动作：{action_hint}。\n"
        f"若截图已经能明确判断坏掉的数字或同页注释，请直接输出可自动落地的动作，不要退回 needs_review。{extra_rules}\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_llm_repair_actions(text: str) -> list[dict]:
    raw = str(text or "").strip()
    if not raw:
        return []
    block_match = _JSON_BLOCK_RE.search(raw)
    if block_match:
        raw = block_match.group(1).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(payload, dict):
        payload = payload.get("actions") or []
    if not isinstance(payload, list):
        return []
    actions: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip().lower()
        if action not in {"match", "ignore_ref", "needs_review", "synthesize_anchor", "synthesize_note_item"}:
            continue
        anchor_phrase = str(item.get("anchor_phrase") or "").strip()
        if action == "synthesize_anchor" and not anchor_phrase:
            continue
        marker = normalize_note_marker(str(item.get("marker") or ""))
        note_text = str(item.get("note_text") or "").strip()
        if action == "synthesize_note_item" and (not str(item.get("anchor_id") or "").strip() or not marker or not note_text):
            continue
        actions.append(
            {
                "action": action,
                "note_item_id": str(item.get("note_item_id") or item.get("definition_id") or "").strip(),
                "anchor_id": str(item.get("anchor_id") or item.get("ref_id") or "").strip(),
                "anchor_phrase": anchor_phrase,
                "marker": marker,
                "note_text": note_text,
                "confidence": float(item.get("confidence", 0.0) or 0.0),
                "reason": str(item.get("reason") or "").strip(),
            }
        )
    return actions


def select_auto_applicable_actions(
    actions: list[dict],
    *,
    confidence_threshold: float = 0.9,
    chapter_unmatched_count: int = 0,
) -> list[dict]:
    """筛选可自动应用的 LLM 动作。

    - match / ignore_ref: 沿用原门槛 confidence >= threshold + 互斥使用集合。
    - synthesize_anchor: 追加两道门槛：
        * fuzzy_score >= FUZZY_SCORE_THRESHOLD 且非 ambiguous（由调用方在 action dict 里提前附上）。
        * 本章未匹配 note 数量 >= MIN_CHAPTER_UNMATCHED_FOR_AUTO，
          单条孤儿章节仍交人工 review，避免误自动化。
    """
    selected: list[dict] = []
    used_definitions: set[str] = set()
    used_refs: set[str] = set()
    for action in actions or []:
        kind = str(action.get("action") or "").strip().lower()
        confidence = float(action.get("confidence", 0.0) or 0.0)
        if confidence < confidence_threshold:
            continue
        if kind == "match":
            note_item_id = str(action.get("note_item_id") or "").strip()
            anchor_id = str(action.get("anchor_id") or "").strip()
            if not note_item_id or not anchor_id:
                continue
            if note_item_id in used_definitions or anchor_id in used_refs:
                continue
            used_definitions.add(note_item_id)
            used_refs.add(anchor_id)
            selected.append(dict(action))
        elif kind == "ignore_ref":
            anchor_id = str(action.get("anchor_id") or "").strip()
            if not anchor_id or anchor_id in used_refs:
                continue
            used_refs.add(anchor_id)
            selected.append(dict(action))
        elif kind == "synthesize_anchor":
            note_item_id = str(action.get("note_item_id") or "").strip()
            if not note_item_id or note_item_id in used_definitions:
                continue
            if not str(action.get("anchor_phrase") or "").strip():
                continue
            fuzzy_score = float(action.get("fuzzy_score", 0.0) or 0.0)
            if fuzzy_score < FUZZY_SCORE_THRESHOLD:
                continue
            if bool(action.get("ambiguous")):
                continue
            if int(chapter_unmatched_count or 0) < MIN_CHAPTER_UNMATCHED_FOR_AUTO:
                continue
            used_definitions.add(note_item_id)
            selected.append(dict(action))
        elif kind == "synthesize_note_item":
            anchor_id = str(action.get("anchor_id") or "").strip()
            marker = normalize_note_marker(str(action.get("marker") or ""))
            note_text = str(action.get("note_text") or "").strip()
            if not anchor_id or anchor_id in used_refs:
                continue
            if not marker or not note_text:
                continue
            used_refs.add(anchor_id)
            selected.append(dict(action))
    return selected


def _resolve_qwen_repair_model_args() -> dict:
    cfg = get_visual_custom_model_config()
    model_id = str(cfg.get("model_id") or "").strip()
    provider = str(cfg.get("provider_type") or "").strip().lower()
    if not model_id or provider != "qwen":
        raise RuntimeError("未配置可用的 qwen3.5-plus 视觉自定义模型")
    api_key = get_dashscope_key()
    if not api_key:
        raise RuntimeError("未配置 DashScope API Key")
    region = str(cfg.get("qwen_region") or "cn").strip().lower()
    return {
        "provider": "qwen",
        "model_id": model_id,
        "api_key": api_key,
        "base_url": QWEN_BASE_URLS.get(region, QWEN_BASE_URLS["cn"]),
    }


def _cluster_focus_pages(cluster: dict) -> list[int]:
    pages: list[int] = []
    for item in cluster.get("unmatched_note_items") or []:
        try:
            page_no = int(item.get("page_no") or 0)
        except (TypeError, ValueError):
            page_no = 0
        if page_no > 0:
            pages.append(page_no)
    for item in cluster.get("unmatched_anchors") or []:
        try:
            page_no = int(item.get("page_no") or 0)
        except (TypeError, ValueError):
            page_no = 0
        if page_no > 0:
            pages.append(page_no)
    cross_page_rebind = False
    for item in cluster.get("rebind_candidates") or []:
        try:
            note_page_no = int(item.get("note_page_no") or 0)
        except (TypeError, ValueError):
            note_page_no = 0
        try:
            anchor_page_no = int(item.get("anchor_page_no") or 0)
        except (TypeError, ValueError):
            anchor_page_no = 0
        if note_page_no > 0:
            pages.append(note_page_no)
        if anchor_page_no > 0:
            pages.append(anchor_page_no)
        if note_page_no > 0 and anchor_page_no > 0 and note_page_no != anchor_page_no:
            cross_page_rebind = True
    ordered = []
    seen: set[int] = set()
    for page_no in sorted(pages):
        if page_no in seen:
            continue
        seen.add(page_no)
        ordered.append(page_no)
    note_system = str(cluster.get("note_system") or "").strip().lower()
    if note_system == "footnote" and ordered:
        span_start = max(1, min(ordered) - LLM_REPAIR_FOOTNOTE_PAGE_PADDING)
        span_end = max(ordered) + LLM_REPAIR_FOOTNOTE_PAGE_PADDING
        needs_contiguous_window = bool(cross_page_rebind or (max(ordered) - min(ordered) >= 1))
        if needs_contiguous_window:
            expanded = list(range(span_start, span_end + 1))
            if len(expanded) <= LLM_REPAIR_MAX_FOCUS_PAGES:
                return expanded
    return ordered[:LLM_REPAIR_MAX_FOCUS_PAGES]


def _trim_page_text(text: str, limit: int = 1400) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(raw) <= limit:
        return raw
    return raw[:limit].rstrip() + " ..."


def _build_chapter_body_text(
    doc_id: str,
    chapter: dict,
    *,
    repo: SQLiteRepository,
    fallback_contexts: list[dict] | None = None,
) -> tuple[str, list[tuple[int, int, int]]]:
    """拼接章节正文，同时返回 (page_no, char_start, char_end) 片段映射。

    当章节的 raw page markdown 全部为空（典型情况：page markdown 字段缺失或全被去掉）时，
    若调用方提供了 `fallback_contexts`（来自 `_build_cluster_page_contexts` 的 `ocr_excerpt`），
    则用 excerpt 拼接一个兜底正文，保证 synthesize_anchor 路径仍有模糊匹配的依据。
    兜底结果同样返回 spans，只不过 char 偏移只相对于 excerpt，无法还原到真实行。
    """
    try:
        start = int(chapter.get("start_page") or 0)
        end = int(chapter.get("end_page") or 0)
    except (TypeError, ValueError):
        start = 0
        end = 0
    parts: list[str] = []
    spans: list[tuple[int, int, int]] = []
    cursor = 0
    sep = "\n\n"
    if start > 0 and end >= start:
        raw_pages = repo.load_pages(doc_id)
        by_page = {
            int(p.get("bookPage") or 0): p
            for p in (raw_pages or [])
            if int(p.get("bookPage") or 0) > 0
        }
        for page_no in range(start, end + 1):
            page = by_page.get(page_no) or {}
            md = page.get("markdown")
            text = str(md.get("text") if isinstance(md, dict) else (md or "")).strip()
            if not text:
                continue
            if parts:
                parts.append(sep)
                cursor += len(sep)
            parts.append(text)
            spans.append((page_no, cursor, cursor + len(text)))
            cursor += len(text)
    if parts:
        return ("".join(parts), spans)
    return _build_fallback_body_text_from_contexts(fallback_contexts)


def _build_fallback_body_text_from_contexts(
    contexts: list[dict] | None,
) -> tuple[str, list[tuple[int, int, int]]]:
    parts: list[str] = []
    spans: list[tuple[int, int, int]] = []
    cursor = 0
    sep = "\n\n"
    for ctx in list(contexts or []):
        try:
            page_no = int(ctx.get("page_no") or 0)
        except (TypeError, ValueError):
            page_no = 0
        text = re.sub(r"\s+", " ", str(ctx.get("ocr_excerpt") or "")).strip()
        if not text:
            continue
        if parts:
            parts.append(sep)
            cursor += len(sep)
        parts.append(text)
        spans.append((page_no, cursor, cursor + len(text)))
        cursor += len(text)
    return ("".join(parts), spans)


def _resolve_page_from_offset(spans: list[tuple[int, int, int]], offset: int) -> int:
    for page_no, start, end in spans:
        if start <= offset < end:
            return page_no
    if spans:
        return spans[-1][0]
    return 0


def _build_cluster_page_contexts(doc_id: str, cluster: dict, *, repo: SQLiteRepository) -> list[dict]:
    raw_pages = repo.load_pages(doc_id)
    page_map = {
        int(page.get("bookPage") or 0): dict(page)
        for page in (raw_pages or [])
        if int(page.get("bookPage") or 0) > 0
    }
    pdf_path = get_pdf_path(doc_id)
    contexts: list[dict] = []
    for page_no in _cluster_focus_pages(cluster):
        page = page_map.get(int(page_no)) or {}
        markdown = page.get("markdown")
        if isinstance(markdown, dict):
            page_text = str(markdown.get("text") or "").strip()
        else:
            page_text = str(markdown or "").strip()
        try:
            file_idx = int(page.get("fileIdx") or max(int(page_no) - 1, 0))
        except (TypeError, ValueError):
            file_idx = max(int(page_no) - 1, 0)
        item = {
            "page_no": int(page_no),
            "file_idx": int(file_idx),
            "source_pdf_path": str(pdf_path or ""),
            "ocr_excerpt": _trim_page_text(page_text),
        }
        try:
            if pdf_path:
                rendered = render_pdf_page(pdf_path, file_idx, scale=1.3)
                if rendered:
                    encoded = base64.b64encode(rendered).decode("ascii")
                    item["image_url"] = f"data:image/png;base64,{encoded}"
        except Exception:
            pass
        contexts.append(item)
    return contexts


def request_llm_repair_actions(
    cluster: dict,
    *,
    model_args: dict | None = None,
    max_matched_examples: int | None = None,
    max_unmatched_note_items: int | None = None,
    max_unmatched_anchors: int | None = None,
    doc_id: str = "",
    slug: str = "",
) -> dict:
    resolved_args = dict(model_args or _resolve_qwen_repair_model_args())
    request_cluster = _slice_cluster_for_request(
        cluster,
        max_matched_examples=max_matched_examples,
        max_unmatched_note_items=max_unmatched_note_items,
        max_unmatched_anchors=max_unmatched_anchors,
    )
    system_prompt = _repair_system_prompt()
    user_prompt = _repair_user_prompt(
        request_cluster,
        max_matched_examples=max_matched_examples,
        max_unmatched_note_items=max_unmatched_note_items,
        max_unmatched_anchors=max_unmatched_anchors,
    )
    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for context in request_cluster.get("page_contexts") or []:
        image_url = str(context.get("image_url") or "").strip()
        if image_url:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                }
            )
    client = OpenAI(
        api_key=str(resolved_args.get("api_key") or ""),
        base_url=str(resolved_args.get("base_url") or ""),
        timeout=45.0,
    )
    image_refused = False
    started = time.time()

    def _page_context_trace_rows(page_contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in page_contexts or []:
            image_url = str(row.get("image_url") or "").strip()
            raw_bytes = b""
            if image_url.startswith("data:") and "," in image_url:
                try:
                    raw_bytes = base64.b64decode(image_url.split(",", 1)[1])
                except Exception:
                    raw_bytes = b""
            rows.append(
                {
                    "page_no": int(row.get("page_no") or 0),
                    "file_idx": int(row.get("file_idx") or 0),
                    "source_pdf_path": str(row.get("source_pdf_path") or ""),
                    "ocr_excerpt": str(row.get("ocr_excerpt") or ""),
                    "byte_size": len(raw_bytes),
                    "sha256": hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else "",
                }
            )
        return rows

    def _do_call(content: list[dict[str, Any]]):
        with _time_limit(60):
            return client.chat.completions.create(
                model=str(resolved_args.get("model_id") or ""),
                max_tokens=LLM_REPAIR_MAX_OUTPUT_TOKENS,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                extra_body={"enable_thinking": False},
            )
    try:
        response = _do_call(user_content)
    except Exception as exc:
        # DashScope 的内容审核偶尔拒绝整批图片（尤其是 OCR 扫描件里的图像）。
        # 只要存在图片，就剥离 image_url 再试一次纯文本路径，保证 Goldstein 这类
        # 扫描页面仍能得到 LLM 修补建议。
        msg = str(exc)
        if (
            "data_inspection_failed" in msg.lower()
            or "DataInspectionFailed" in msg
        ) and any(c.get("type") == "image_url" for c in user_content):
            image_refused = True
            text_only_content = [c for c in user_content if c.get("type") != "image_url"]
            try:
                response = _do_call(text_only_content)
            except Exception as exc2:
                raise _classify_provider_exception(exc2) from exc2
        else:
            raise _classify_provider_exception(exc) from exc
    usage = _build_usage(
        prompt_tokens=getattr(response.usage, "prompt_tokens", 0),
        completion_tokens=getattr(response.usage, "completion_tokens", 0),
        total_tokens=getattr(response.usage, "total_tokens", None),
    )
    raw_text = ""
    if response.choices and getattr(response.choices[0], "message", None):
        raw_text = _extract_openai_message_text(getattr(response.choices[0].message, "content", ""))
    duration_ms = int(max(0.0, (time.time() - started) * 1000.0))
    parsed_actions = parse_llm_repair_actions(raw_text)
    return {
        "raw_text": raw_text,
        "usage": usage,
        "usage_event": {
            "stage": _LLM_REPAIR_USAGE_STAGE,
            "provider": str(resolved_args.get("provider") or "qwen"),
            "model_id": str(resolved_args.get("model_id") or ""),
            "request_count": _coerce_usage_int(usage.get("request_count")),
            "prompt_tokens": _coerce_usage_int(usage.get("prompt_tokens")),
            "completion_tokens": _coerce_usage_int(usage.get("completion_tokens")),
            "total_tokens": _coerce_usage_int(usage.get("total_tokens")),
            "doc_id": str(doc_id or "").strip(),
            "slug": str(slug or "").strip(),
            "context": _compact_usage_context(
                {
                    "cluster_id": str(cluster.get("cluster_id") or ""),
                    "request_mode": str(request_cluster.get("request_mode") or ""),
                }
            ),
        },
        "actions": parsed_actions,
        "request_metrics": {
            "cluster_id": str(cluster.get("cluster_id") or ""),
            "request_mode": str(request_cluster.get("request_mode") or ""),
            "allowed_actions": list(request_cluster.get("allowed_actions") or []),
            "chars": len(system_prompt) + len(user_prompt),
            "estimated_prompt_tokens": _estimate_prompt_tokens(system_prompt) + _estimate_prompt_tokens(user_prompt),
            "soft_input_token_budget": LLM_REPAIR_SOFT_INPUT_TOKEN_BUDGET,
            "model_max_input_tokens_thinking": QWEN35_PLUS_MAX_INPUT_TOKENS_THINKING,
            "model_max_input_tokens_no_think": QWEN35_PLUS_MAX_INPUT_TOKENS_NO_THINK,
            "matched_examples": len(request_cluster.get("matched_examples") or []),
            "unmatched_note_items": len(request_cluster.get("unmatched_note_items") or []),
            "unmatched_anchors": len(request_cluster.get("unmatched_anchors") or []),
            "page_context_count": len(request_cluster.get("page_contexts") or []),
            "image_refused": image_refused,
            "truncated": (
                len(request_cluster.get("matched_examples") or []) < len(cluster.get("matched_examples") or [])
                or len(request_cluster.get("unmatched_note_items") or []) < len(cluster.get("unmatched_note_items") or [])
                or len(request_cluster.get("unmatched_anchors") or []) < len(cluster.get("unmatched_anchors") or [])
            ),
        },
        "llm_trace": {
            "stage": _LLM_REPAIR_USAGE_STAGE,
            "reason_for_request": "根据 unresolved cluster 请求 LLM 给出注释链接修补建议",
            "model": {
                "provider": str(resolved_args.get("provider") or "qwen"),
                "model_id": str(resolved_args.get("model_id") or ""),
                "base_url": str(resolved_args.get("base_url") or ""),
            },
            "request_prompt": {
                "system": system_prompt,
                "user": user_prompt,
            },
            "request_content": {
                "cluster": {
                    "cluster_id": str(request_cluster.get("cluster_id") or ""),
                    "chapter_title": str(request_cluster.get("chapter_title") or ""),
                    "request_mode": str(request_cluster.get("request_mode") or ""),
        "allowed_actions": list(request_cluster.get("allowed_actions") or []),
        "note_system": str(request_cluster.get("note_system") or ""),
        "page_range": [request_cluster.get("page_start"), request_cluster.get("page_end")],
        "matched_examples": list(request_cluster.get("matched_examples") or []),
        "unmatched_note_items": list(request_cluster.get("unmatched_note_items") or []),
        "unmatched_anchors": list(request_cluster.get("unmatched_anchors") or []),
        "rebind_candidates": list(request_cluster.get("rebind_candidates") or []),
    },
                "page_contexts": _page_context_trace_rows(list(request_cluster.get("page_contexts") or [])),
            },
            "request_context_summary": {
                "cluster_id": str(cluster.get("cluster_id") or ""),
                "request_mode": str(request_cluster.get("request_mode") or ""),
                "page_context_count": len(request_cluster.get("page_contexts") or []),
                "image_refused": bool(image_refused),
            },
            "response_raw_text": raw_text,
            "response_parsed": parsed_actions,
            "derived_truth": {
                "parsed_actions": parsed_actions,
            },
            "usage": dict(usage or {}),
            "timing": {"duration_ms": duration_ms},
        },
    }


_NOTE_LINK_REPAIRABLE_STATUSES = {"orphan_note", "ambiguous"}
_ANCHOR_LINK_REPAIRABLE_STATUSES = {"orphan_anchor", "ambiguous"}


def _find_link_id_for_match(note_links: list[dict], *, note_item_id: str, anchor_id: str) -> str:
    if note_item_id:
        for link in note_links or []:
            if (
                str(link.get("status") or "") in _NOTE_LINK_REPAIRABLE_STATUSES
                and str(link.get("note_item_id") or "").strip() == note_item_id
            ):
                return str(link.get("link_id") or "")
        for link in note_links or []:
            if (
                str(link.get("status") or "") == "matched"
                and str(link.get("note_item_id") or "").strip() == note_item_id
            ):
                return str(link.get("link_id") or "")
    if anchor_id:
        for link in note_links or []:
            if (
                str(link.get("status") or "") in _ANCHOR_LINK_REPAIRABLE_STATUSES
                and str(link.get("anchor_id") or "").strip() == anchor_id
            ):
                return str(link.get("link_id") or "")
        for link in note_links or []:
            if (
                str(link.get("status") or "") == "matched"
                and str(link.get("anchor_id") or "").strip() == anchor_id
            ):
                return str(link.get("link_id") or "")
    return ""


def _resolve_chapter_id_for_page(chapters: list, page_no: int) -> str:
    """按 page_no 在 chapters 中找落位章节；找不到包含关系时退化为最近章节。

    Goldstein 类场景：orphan note 指向 preface（pages 1-17），而 chapters 最早
    从 page 18 起步，link 的 chapter_id 是空串。合成 anchor 覆盖写入前必须把
    chapter_id 回填成非空值，否则 `_materialize_anchor_overrides` 会以
    `invalid_coords` 拒绝，llm-synth 锚点永远落不到 fnm_body_anchors。
    """
    if not chapters:
        return ""
    try:
        page_int = int(page_no)
    except (TypeError, ValueError):
        return ""
    if page_int <= 0:
        return ""
    best_id = ""
    best_dist: int | None = None
    for chapter in chapters:
        cid = str(chapter.get("chapter_id") or "").strip() if chapter else ""
        if not cid:
            continue
        try:
            sp = int(chapter.get("start_page") or 0)
            ep = int(chapter.get("end_page") or 0)
        except (TypeError, ValueError):
            continue
        if sp <= 0 or ep < sp:
            continue
        if sp <= page_int <= ep:
            return cid
        dist = sp - page_int if page_int < sp else page_int - ep
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_id = cid
    return best_id


def _find_link_id_for_ignore(note_links: list[dict], *, anchor_id: str) -> str:
    for link in note_links or []:
        if (
            str(link.get("status") or "") in _ANCHOR_LINK_REPAIRABLE_STATUSES
            and str(link.get("anchor_id") or "").strip() == anchor_id
        ):
            return str(link.get("link_id") or "")
    return ""


def run_llm_repair(
    doc_id: str,
    *,
    repo: SQLiteRepository | None = None,
    slug: str = "",
    cluster_limit: int | None = None,
    auto_apply: bool = True,
    confidence_threshold: float = 0.9,
    model_args: dict | None = None,
    max_matched_examples: int | None = None,
    max_unmatched_note_items: int | None = None,
    max_unmatched_anchors: int | None = None,
) -> dict:
    """运行 unresolved cluster 的 LLM 修补。

    - `cluster_limit=None` 或 `<=0` 表示跑全部 cluster。默认 None（全部）。
      历史版本默认 1，这里放宽，因为单次只跑 1 簇对 orphan 量大的书覆盖率极低。
    - `max_matched_examples / max_unmatched_note_items / max_unmatched_anchors`
      可覆盖 `LLM_REPAIR_MAX_*` 默认值，让外部脚本按书放大 per-cluster 样本量。
    """
    repo = repo or SQLiteRepository()
    chapters = repo.list_fnm_chapters(doc_id)
    note_items = repo.list_fnm_note_items(doc_id)
    body_anchors = repo.list_fnm_body_anchors(doc_id)
    links = repo.list_fnm_note_links(doc_id)
    clusters = build_unresolved_clusters(
        chapters=chapters,
        note_items=note_items,
        body_anchors=body_anchors,
        note_links=links,
    )
    limit_value = int(cluster_limit) if cluster_limit is not None else 0
    if limit_value > 0:
        clusters = clusters[:limit_value]

    repo.clear_fnm_review_overrides(doc_id, scope="llm_suggestion")
    repo.clear_fnm_review_overrides(doc_id, scope="anchor")
    repo.clear_fnm_review_overrides(doc_id, scope="note_item")
    chapter_by_id = {
        str(chapter.get("chapter_id") or ""): dict(chapter) for chapter in chapters or []
    }
    body_anchor_by_id = {
        str(anchor.get("anchor_id") or ""): dict(anchor)
        for anchor in body_anchors or []
        if str(anchor.get("anchor_id") or "").strip()
    }
    suggestions: list[dict] = []
    auto_applied: list[dict] = []
    request_metrics: list[dict] = []
    usage_events: list[dict] = []
    llm_traces: list[dict] = []

    for cluster_index, cluster in enumerate(clusters, start=1):
        cluster = dict(cluster)
        cluster["page_contexts"] = _build_cluster_page_contexts(doc_id, cluster, repo=repo)
        chapter_id = str(cluster.get("chapter_id") or "")
        chapter = chapter_by_id.get(chapter_id) or {}
        body_text, body_spans = _build_chapter_body_text(
            doc_id,
            chapter,
            repo=repo,
            fallback_contexts=cluster.get("page_contexts"),
        )
        cluster["chapter_body_text"] = body_text
        chapter_unmatched_count = len(cluster.get("unmatched_note_items") or [])
        llm_result = request_llm_repair_actions(
            cluster,
            model_args=model_args,
            max_matched_examples=max_matched_examples,
            max_unmatched_note_items=max_unmatched_note_items,
            max_unmatched_anchors=max_unmatched_anchors,
            doc_id=doc_id,
            slug=slug,
        )
        actions = list(llm_result.get("actions") or [])
        request_metrics.append(dict(llm_result.get("request_metrics") or {}))
        usage_event = dict(llm_result.get("usage_event") or {})
        if usage_event:
            usage_events.append(usage_event)
        llm_trace = dict(llm_result.get("llm_trace") or {})
        for action in actions:
            if action.get("action") != "synthesize_anchor":
                continue
            phrase = str(action.get("anchor_phrase") or "").strip()
            locate = locate_anchor_phrase_in_body(body_text, phrase)
            action["fuzzy_score"] = float(locate.get("score") or 0.0)
            action["ambiguous"] = bool(locate.get("ambiguous"))
            action["char_start"] = int(locate.get("char_start") or -1)
            action["char_end"] = int(locate.get("char_end") or -1)
            action["matched_text"] = str(locate.get("matched_text") or "")
            action["fuzzy_hit"] = bool(locate.get("hit"))
        auto_actions = select_auto_applicable_actions(
            actions,
            confidence_threshold=confidence_threshold,
            chapter_unmatched_count=chapter_unmatched_count,
        )
        cluster_auto_applied_start = len(auto_applied)
        for action_index, action in enumerate(actions, start=1):
            suggestion_id = f"llm-{cluster_index:02d}-{action_index:03d}"
            auto_selected = action in auto_actions
            payload = {
                "cluster_id": cluster.get("cluster_id"),
                "chapter_id": cluster.get("chapter_id"),
                "chapter_title": cluster.get("chapter_title"),
                "action": action.get("action"),
                "note_item_id": action.get("note_item_id"),
                "anchor_id": action.get("anchor_id"),
                "anchor_phrase": action.get("anchor_phrase", ""),
                "fuzzy_score": action.get("fuzzy_score"),
                "fuzzy_hit": action.get("fuzzy_hit"),
                "ambiguous": action.get("ambiguous"),
                "matched_text": action.get("matched_text", ""),
                "confidence": action.get("confidence"),
                "reason": action.get("reason"),
                "auto_selected": auto_selected,
            }
            repo.save_fnm_review_override(doc_id, "llm_suggestion", suggestion_id, payload)
            suggestions.append({"suggestion_id": suggestion_id, **payload})

        if auto_apply:
            for action in auto_actions:
                if action["action"] == "match":
                    link_id = _find_link_id_for_match(
                        links,
                        note_item_id=str(action.get("note_item_id") or "").strip(),
                        anchor_id=str(action.get("anchor_id") or "").strip(),
                    )
                    if not link_id:
                        continue
                    repo.save_fnm_review_override(
                        doc_id,
                        "link",
                        link_id,
                        {
                            "action": "match",
                            "note_item_id": str(action.get("note_item_id") or "").strip(),
                            "anchor_id": str(action.get("anchor_id") or "").strip(),
                        },
                    )
                    auto_applied.append({"link_id": link_id, **action})
                elif action["action"] == "ignore_ref":
                    link_id = _find_link_id_for_ignore(
                        links,
                        anchor_id=str(action.get("anchor_id") or "").strip(),
                    )
                    if not link_id:
                        continue
                    repo.save_fnm_review_override(
                        doc_id,
                        "link",
                        link_id,
                        {
                            "action": "ignore",
                            "anchor_id": str(action.get("anchor_id") or "").strip(),
                        },
                    )
                    auto_applied.append({"link_id": link_id, **action})
                elif action["action"] == "synthesize_anchor":
                    note_item_id = str(action.get("note_item_id") or "").strip()
                    if not note_item_id:
                        continue
                    link_id = _find_link_id_for_match(
                        links, note_item_id=note_item_id, anchor_id=""
                    )
                    if not link_id:
                        continue
                    new_anchor_id = f"llm-synth-{link_id}"
                    char_start = int(action.get("char_start") or -1)
                    char_end = int(action.get("char_end") or -1)
                    page_no = _resolve_page_from_offset(body_spans, char_start)
                    effective_chapter_id = chapter_id
                    if not effective_chapter_id:
                        effective_chapter_id = _resolve_chapter_id_for_page(chapters, page_no)
                    matched_text = str(action.get("matched_text") or "")
                    try:
                        confidence = float(action.get("confidence") or 0.0)
                    except (TypeError, ValueError):
                        confidence = 0.0
                    note_item = next(
                        (
                            item
                            for item in (cluster.get("unmatched_note_items") or [])
                            if str(item.get("note_item_id") or "") == note_item_id
                        ),
                        {},
                    )
                    normalized_marker = str(
                        note_item.get("normalized_marker") or note_item.get("marker") or ""
                    ).strip()
                    note_system = str(cluster.get("note_system") or "endnote").strip() or "endnote"
                    anchor_payload = {
                        "action": "create",
                        "anchor_id": new_anchor_id,
                        "chapter_id": effective_chapter_id,
                        "page_no": page_no,
                        "paragraph_index": 0,
                        "char_start": char_start,
                        "char_end": char_end,
                        "source_text": matched_text,
                        "normalized_marker": normalized_marker,
                        "anchor_kind": note_system,
                        "certainty": confidence,
                        "source": "llm",
                        "synthetic": False,
                        "anchor_phrase": str(action.get("anchor_phrase") or ""),
                        "fuzzy_score": float(action.get("fuzzy_score") or 0.0),
                    }
                    repo.save_fnm_review_override(doc_id, "anchor", new_anchor_id, anchor_payload)
                    repo.save_fnm_review_override(
                        doc_id,
                        "link",
                        link_id,
                        {
                            "action": "match",
                            "note_item_id": note_item_id,
                            "anchor_id": new_anchor_id,
                        },
                    )
                    auto_applied.append(
                        {"link_id": link_id, "anchor_id": new_anchor_id, **action}
                    )
                elif action["action"] == "synthesize_note_item":
                    anchor_id = str(action.get("anchor_id") or "").strip()
                    anchor = body_anchor_by_id.get(anchor_id) or {}
                    try:
                        page_no = int(anchor.get("page_no") or cluster.get("page_start") or 0)
                    except (TypeError, ValueError):
                        page_no = 0
                    effective_chapter_id = chapter_id or str(anchor.get("chapter_id") or "").strip()
                    if not effective_chapter_id:
                        effective_chapter_id = _resolve_chapter_id_for_page(chapters, page_no)
                    marker = normalize_note_marker(str(action.get("marker") or ""))
                    note_text = str(action.get("note_text") or "").strip()
                    if not anchor_id or not effective_chapter_id or page_no <= 0 or not marker or not note_text:
                        continue
                    note_item_id = f"llm-note-{anchor_id}"
                    note_system = str(cluster.get("note_system") or "endnote").strip() or "endnote"
                    repo.save_fnm_review_override(
                        doc_id,
                        "note_item",
                        note_item_id,
                        {
                            "action": "create",
                            "note_item_id": note_item_id,
                            "chapter_id": effective_chapter_id,
                            "page_no": page_no,
                            "marker": marker,
                            "note_kind": note_system,
                            "text": note_text,
                            "source": "llm",
                            "source_page_label": str(page_no),
                            "is_reconstructed": False,
                            "review_required": False,
                            "anchor_id": anchor_id,
                        },
                    )
                    auto_applied.append(
                        {
                            "note_item_id": note_item_id,
                            "anchor_id": anchor_id,
                            **action,
                        }
                    )

        if llm_trace:
            llm_trace["derived_truth"] = {
                "cluster_id": str(cluster.get("cluster_id") or ""),
                "chapter_title": str(cluster.get("chapter_title") or ""),
                "request_mode": str((llm_result.get("request_metrics") or {}).get("request_mode") or ""),
                "parsed_actions": actions,
                "auto_selected_actions": [
                    dict(action)
                    for action in auto_actions
                ],
                "auto_applied_actions": [
                    dict(action)
                    for action in auto_applied[cluster_auto_applied_start:]
                ],
            }
            llm_traces.append(llm_trace)

    action_counts: dict[str, int] = {}
    fuzzy_hit_count = 0
    fuzzy_ambiguous_count = 0
    synth_suggestion_count = 0
    synth_auto_applied_count = 0
    for item in suggestions:
        key = str(item.get("action") or "").strip() or "unknown"
        action_counts[key] = action_counts.get(key, 0) + 1
        if key == "synthesize_anchor":
            synth_suggestion_count += 1
            if item.get("fuzzy_hit"):
                fuzzy_hit_count += 1
            if item.get("ambiguous"):
                fuzzy_ambiguous_count += 1
    auto_action_counts: dict[str, int] = {}
    for item in auto_applied:
        key = str(item.get("action") or "").strip() or "unknown"
        auto_action_counts[key] = auto_action_counts.get(key, 0) + 1
        if key == "synthesize_anchor":
            synth_auto_applied_count += 1
    return {
        "cluster_count": len(clusters),
        "suggestion_count": len(suggestions),
        "auto_applied_count": len(auto_applied),
        "suggestions": suggestions,
        "auto_applied": auto_applied,
        "request_metrics": request_metrics,
        "usage_events": usage_events,
        "llm_traces": llm_traces,
        "usage_summary": _summarize_usage_events(
            usage_events,
            required_stages=(_LLM_REPAIR_USAGE_STAGE,),
        ),
        "action_counts": action_counts,
        "auto_action_counts": auto_action_counts,
        "synth_suggestion_count": synth_suggestion_count,
        "synth_auto_applied_count": synth_auto_applied_count,
        "fuzzy_hit_count": fuzzy_hit_count,
        "fuzzy_ambiguous_count": fuzzy_ambiguous_count,
        "caps": {
            "matched_examples": int(max_matched_examples) if max_matched_examples else LLM_REPAIR_MAX_MATCHED_EXAMPLES,
            "unmatched_note_items": int(max_unmatched_note_items) if max_unmatched_note_items else LLM_REPAIR_MAX_UNMATCHED_DEFINITIONS,
            "unmatched_anchors": int(max_unmatched_anchors) if max_unmatched_anchors else LLM_REPAIR_MAX_UNMATCHED_REFS,
            "cluster_limit": limit_value,
        },
    }

"""阶段 4 模块：引用冻结与 unit 规划。"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import asdict
from typing import Any

from FNM_RE.modules.contracts import GateReport, ModuleResult
from FNM_RE.modules.types import (
    BodyAnchorLayer,
    BookStructureModel,
    ChapterLayer,
    ChapterLayers,
    FrozenRefEntry,
    FrozenUnit,
    FrozenUnits,
    NoteLinkLayer,
    NoteLinkTable,
)
from FNM_RE.shared.refs import frozen_note_ref, replace_frozen_refs
from FNM_RE.stages.units import _chunk_body_page_segments, _segment_paragraphs_from_body_pages
from FNM_RE.shared.notes import _collect_chapter_page_numbers, _safe_int

_TOKEN_CANDIDATE_RE_TEMPLATE = r"\[\s*(?:\^)?\s*{marker}\s*\]"
# Unicode 上标数字 → 普通数字的反向映射，供 _inject_token_once 生成候选变体
_UNICODE_SUPERSCRIPT_DIGITS = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
}

def _chapter_order_map(chapter_layers: ChapterLayers) -> dict[str, int]:
    return {
        str(chapter.chapter_id or ""): index
        for index, chapter in enumerate(chapter_layers.chapters, start=1)
        if str(chapter.chapter_id or "").strip()
    }

def _chapter_page_bounds(chapter: ChapterLayer) -> tuple[int, int]:
    sorted_pages = _collect_chapter_page_numbers(chapter)
    if not sorted_pages:
        return 0, 0
    return int(sorted_pages[0]), int(sorted_pages[-1])

def _resolve_note_item_owner(
    item: Any,
    *,
    region_by_id: dict[str, Any],
    valid_chapter_ids: set[str],
) -> tuple[str, str]:
    region = region_by_id.get(str(getattr(item, "region_id", "") or ""))
    candidates = [
        ("item.owner_chapter_id", str(getattr(item, "owner_chapter_id", "") or "").strip()),
        ("item.chapter_id", str(getattr(item, "chapter_id", "") or "").strip()),
        ("region.owner_chapter_id", str(getattr(region, "owner_chapter_id", "") or "").strip()),
        ("region.chapter_id", str(getattr(region, "chapter_id", "") or "").strip()),
    ]
    for source, chapter_id in candidates:
        if chapter_id and chapter_id in valid_chapter_ids:
            return chapter_id, source
    return "", ""

from FNM_RE.shared.refs import cleanup_nested_note_refs as _cleanup_nested_note_refs
from FNM_RE.shared.refs import _NOTE_REF_TOKEN_RE


def _shift_coords_out_of_note_ref_token(
    payload: str,
    coord_start: int,
    coord_end: int,
) -> tuple[int, int]:
    """避免后续注入把已有 NOTE_REF token 切开。"""
    for match in _NOTE_REF_TOKEN_RE.finditer(str(payload or "")):
        token_start, token_end = match.span()
        overlaps = coord_start < token_end and coord_end > token_start
        insertion_inside = coord_start == coord_end and token_start < coord_start < token_end
        starts_inside = token_start < coord_start < token_end
        ends_inside = token_start < coord_end < token_end
        if overlaps or insertion_inside or starts_inside or ends_inside:
            return token_end, token_end
    return coord_start, coord_end


def _inject_token_once(
    text: str,
    *,
    anchor: BodyAnchorLayer,
    marker: str,
    note_id: str,
) -> tuple[str, bool]:
    payload = str(text or "")
    if not payload:
        return payload, False
    token = frozen_note_ref(note_id)
    if not token:
        return payload, False
    if token in payload:
        return payload, True
    normalized_marker = str(marker or "").strip()
    source_marker = str(anchor.source_marker or "").strip()
    anchor_source = str(anchor.source or "").strip()
    try:
        coord_start = int(anchor.char_start or 0)
        coord_end = int(anchor.char_end or 0)
    except (TypeError, ValueError):
        coord_start = 0
        coord_end = 0
    if 0 <= coord_start <= coord_end <= len(payload):
        coord_start, coord_end = _shift_coords_out_of_note_ref_token(
            payload, coord_start, coord_end
        )
        if anchor_source == "llm" and coord_end >= coord_start and coord_end > 0:
            return payload[:coord_end] + token + payload[coord_end:], True
        if anchor_source == "visual_repair" and coord_start > 0:
            return payload[:coord_start] + token + payload[coord_start:], True
        if coord_end > coord_start:
            coord_slice = payload[coord_start:coord_end]
            if (
                (source_marker and source_marker in coord_slice)
                or (normalized_marker and normalized_marker in coord_slice)
            ):
                return payload[:coord_start] + token + payload[coord_end:], True
    candidates = [
        f"[{str(marker or '').strip()}]",
    ]
    if source_marker and not source_marker.isdigit():
        candidates.insert(0, source_marker)
    # Unicode 上标变体：Goldstein ch5 marker 96 原文为 ⁹⁶，source_marker
    # 是 <sup>96</sup>，需逐个尝试所有上标字符组合。
    if str(marker or "").strip().isdigit():
        uni_sup = "".join(_UNICODE_SUPERSCRIPT_DIGITS.get(d, d) for d in str(marker))
        if uni_sup != str(marker):
            candidates.append(uni_sup)
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in payload:
            return payload.replace(candidate, token, 1), True
    if str(anchor.source or "").strip() in {"llm", "visual_repair"}:
        phrase = str(anchor.source_text or "").strip()
        if phrase and phrase in payload:
            return payload.replace(phrase, f"{phrase}{token}", 1), True
    if normalized_marker:
        pattern = re.compile(_TOKEN_CANDIDATE_RE_TEMPLATE.format(marker=re.escape(normalized_marker)))
        replaced, count = pattern.subn(token, payload, count=1)
        if count > 0:
            return replaced, True
    # 最后兜底：词边界内搜 marker 串（防止 "7" 匹配 "27" 或 "71"）
    marker_str = str(marker or "").strip()
    if marker_str:
        pattern = re.compile(rf"\b{re.escape(marker_str)}\b")
        replaced, count = pattern.subn(token, payload, count=1)
        if count > 0:
            return replaced, True
    return payload, False

def _unit_contract_issues(*, body_units: list[FrozenUnit], note_units: list[FrozenUnit]) -> list[str]:
    issues: list[str] = []
    for row in list(body_units) + list(note_units):
        if not str(row.unit_id or "").strip():
            issues.append("missing_unit_id")
        if not str(row.kind or "").strip():
            issues.append(f"missing_kind:{row.unit_id}")
        if not str(row.owner_kind or "").strip() or not str(row.owner_id or "").strip():
            issues.append(f"missing_owner:{row.unit_id}")
        if not str(row.section_id or "").strip():
            issues.append(f"missing_section_id:{row.unit_id}")
        if not isinstance(row.page_segments, list):
            issues.append(f"invalid_page_segments_type:{row.unit_id}")
    for row in body_units:
        if str(row.target_ref or "").strip():
            issues.append(f"body_target_ref_not_empty:{row.unit_id}")
    for row in note_units:
        if str(row.kind or "") not in {"footnote", "endnote"}:
            issues.append(f"note_kind_invalid:{row.unit_id}")
        if not str(row.note_id or "").strip():
            issues.append(f"note_id_missing:{row.unit_id}")
        if not str(row.target_ref or "").startswith("{{NOTE_REF:"):
            issues.append(f"note_target_ref_invalid:{row.unit_id}")
    return issues

def _compute_unit_hash(source_text: str, page_start: int, page_end: int, char_count: int, page_nos: list[int]) -> tuple[str, str]:
    """计算 unit 的 source_hash 和 segment_plan_hash。

    source_hash: source_text 前 200 字符的 sha256（轻量指纹，用于判定源文本是否变化）。
    segment_plan_hash: page span + char_count + page_no 序列的 sha256（用于判定 chunk 边界是否变化）。
    """
    source_fp = hashlib.sha256(str(source_text or "")[:200].encode()).hexdigest()[:16]
    plan_key = f"{page_start}|{page_end}|{char_count}|{','.join(str(p) for p in sorted(page_nos))}"
    plan_fp = hashlib.sha256(plan_key.encode()).hexdigest()[:16]
    return source_fp, plan_fp


def build_frozen_units(
    chapter_layers: ChapterLayers,
    note_link_table: NoteLinkTable,
    *,
    book_structure_model: BookStructureModel | None = None,
    max_body_chars: int = 6000,
    pipeline_run_id: str = "",
) -> ModuleResult[FrozenUnits]:
    chapter_order = _chapter_order_map(chapter_layers)
    chapter_by_id = {
        str(chapter.chapter_id or ""): chapter
        for chapter in chapter_layers.chapters
        if str(chapter.chapter_id or "").strip()
    }
    valid_chapter_ids = set(chapter_by_id.keys())
    region_by_id = {
        str(region.region_id or ""): region
        for region in chapter_layers.regions
        if str(region.region_id or "").strip()
    }
    anchor_by_id = {
        str(anchor.anchor_id or ""): anchor
        for anchor in note_link_table.anchors
        if str(anchor.anchor_id or "").strip()
    }
    matched_links = [
        row
        for row in note_link_table.effective_links
        if str(row.status or "") == "matched"
    ]
    anchor_to_note_ids: dict[str, set[str]] = {}
    for link in matched_links:
        anchor_id = str(link.anchor_id or "").strip()
        note_item_id = str(link.note_item_id or "").strip()
        if not anchor_id or not note_item_id:
            continue
        anchor_to_note_ids.setdefault(anchor_id, set()).add(note_item_id)
    conflict_anchor_ids = {
        anchor_id
        for anchor_id, note_ids in anchor_to_note_ids.items()
        if len(note_ids) > 1
    }
    matched_links.sort(
        key=lambda row: (
            int(chapter_order.get(str(row.chapter_id or ""), 10**6)),
            _safe_int(anchor_by_id.get(str(row.anchor_id or ""), BodyAnchorLayer("", "", 0, 0, 0, 0, "", "", "unknown", 0.0, "", "", False, "")).page_no),
            -_safe_int(anchor_by_id.get(str(row.anchor_id or ""), BodyAnchorLayer("", "", 0, 0, 0, 0, "", "", "unknown", 0.0, "", "", False, "")).char_start),
            str(row.link_id or ""),
        )
    )

    chapter_body_pages: dict[str, dict[int, dict[str, Any]]] = {}
    chapter_body_page_order: dict[str, list[int]] = {}
    for chapter in chapter_layers.chapters:
        chapter_id = str(chapter.chapter_id or "")
        page_map: dict[int, dict[str, Any]] = {}
        page_order: list[int] = []
        for page in chapter.body_pages:
            page_no = int(page.page_no)
            if page_no <= 0:
                continue
            page_map[page_no] = {"page_no": page_no, "text": str(page.text or "")}
            if page_no not in page_order:
                page_order.append(page_no)
        chapter_body_pages[chapter_id] = page_map
        chapter_body_page_order[chapter_id] = page_order

    ref_map: list[FrozenRefEntry] = []
    injected_anchor_ids: set[str] = set()
    skipped_reason_counts: Counter[str] = Counter()

    _SKIP_REASON_TO_CATEGORY: dict[str, str] = {
        "missing_anchor": "ceiling_skip",
        "synthetic_anchor": "ceiling_skip",
        "conflict_anchor": "error_skip",
        "duplicate_anchor": "policy_skip",
        "missing_body_page": "error_skip",
        "token_not_found": "ceiling_skip",
    }

    def _clean_skipped_marker(text: str, marker: str) -> str:
        payload = str(text or "")
        m = str(marker or "").strip()
        if not m:
            return payload
        # [N] 格式（排除 ^[N]: 定义行）
        payload = re.sub(rf"(?<!\^)\[{re.escape(m)}\](?!:)", "", payload)
        # <sup>N</sup> 格式
        payload = re.sub(rf"<sup>\s*{re.escape(m)}\s*</sup>", "", payload)
        return payload

    for link in matched_links:
        chapter_id = str(link.chapter_id or "")
        anchor_id = str(link.anchor_id or "").strip()
        note_item_id = str(link.note_item_id or "").strip()
        marker = str(link.marker or "")
        anchor = anchor_by_id.get(anchor_id)
        target_ref = frozen_note_ref(note_item_id)

        def _append_skipped(reason: str, page_no: int = 0) -> None:
            category = _SKIP_REASON_TO_CATEGORY.get(reason, "error_skip")
            skipped_reason_counts.update([reason])
            ref_map.append(
                FrozenRefEntry(
                    link_id=str(link.link_id or ""),
                    chapter_id=chapter_id,
                    anchor_id=anchor_id,
                    note_item_id=note_item_id,
                    target_ref=target_ref,
                    decision="skipped",
                    reason=reason,  # type: ignore[arg-type]
                    skip_category=category,
                    page_no=int(page_no or 0),
                )
            )
            # 对 ceiling_skip 和 policy_skip，清理 body text 中的 raw marker
            if category in {"ceiling_skip", "policy_skip"} and page_no > 0:
                body_page = chapter_body_pages.get(chapter_id, {}).get(page_no, {})
                if body_page:
                    body_page["text"] = _clean_skipped_marker(
                        str(body_page.get("text") or ""), marker
                    )

        if not anchor:
            _append_skipped("missing_anchor")
            continue
        if bool(anchor.synthetic):
            sm = str(anchor.source_marker or "").strip()
            nm = str(anchor.normalized_marker or "").strip()
            # source_marker 为空 → 无原文可匹配，直接跳过
            if not sm:
                _append_skipped("synthetic_anchor", page_no=int(anchor.page_no))
                continue
            if sm == nm:
                # bare digit source_marker 太宽泛，_inject_token_once 会在
                # 整页文本中裸搜 "7"，容易误匹配。只有带格式的 source_marker
                #（如 [7]、<sup>7</sup>）才能安全注入。
                _append_skipped("synthetic_anchor", page_no=int(anchor.page_no))
                continue
        if anchor_id in conflict_anchor_ids:
            _append_skipped("conflict_anchor", page_no=int(anchor.page_no))
            continue
        if anchor_id in injected_anchor_ids:
            _append_skipped("duplicate_anchor", page_no=int(anchor.page_no))
            continue
        payload = dict(chapter_body_pages.get(chapter_id, {}).get(int(anchor.page_no), {}))
        if not payload:
            _append_skipped("missing_body_page", page_no=int(anchor.page_no))
            continue
        updated_text, injected = _inject_token_once(
            str(payload.get("text") or ""),
            anchor=anchor,
            marker=marker,
            note_id=note_item_id,
        )
        if not injected:
            _append_skipped("token_not_found", page_no=int(anchor.page_no))
            continue
        payload["text"] = updated_text
        chapter_body_pages.setdefault(chapter_id, {})[int(anchor.page_no)] = payload
        injected_anchor_ids.add(anchor_id)
        ref_map.append(
            FrozenRefEntry(
                link_id=str(link.link_id or ""),
                chapter_id=chapter_id,
                anchor_id=anchor_id,
                note_item_id=note_item_id,
                target_ref=target_ref,
                decision="injected",
                reason="",
                page_no=int(anchor.page_no),
            )
        )

    for ch_id, page_map in chapter_body_pages.items():
        for page_no, payload in page_map.items():
            text = str(payload.get("text") or "")
            cleaned = _cleanup_nested_note_refs(text)
            if cleaned != text:
                payload["text"] = cleaned
                chapter_body_pages[ch_id][page_no] = payload

    body_units: list[FrozenUnit] = []
    chapter_unit_counts: dict[str, int] = {}
    empty_body_chapter_count = 0
    chapter_bounds = {
        str(chapter.chapter_id or ""): _chapter_page_bounds(chapter)
        for chapter in chapter_layers.chapters
    }
    for chapter in chapter_layers.chapters:
        chapter_id = str(chapter.chapter_id or "")
        page_order = [page_no for page_no in chapter_body_page_order.get(chapter_id, []) if page_no in chapter_body_pages.get(chapter_id, {})]
        frozen_body_pages = [chapter_body_pages[chapter_id][page_no] for page_no in page_order]
        if not frozen_body_pages:
            empty_body_chapter_count += 1
            chapter_unit_counts[chapter_id] = 0
            continue
        section_payload = {
            "section_id": chapter_id,
            "title": str(chapter.title or ""),
            "frozen_body_pages": list(frozen_body_pages),
            "obsidian_body_pages": [
                {"page_no": int(row.get("page_no") or 0), "text": replace_frozen_refs(str(row.get("text") or ""))}
                for row in frozen_body_pages
            ],
        }
        page_segments = _segment_paragraphs_from_body_pages(section_payload)
        chunks = _chunk_body_page_segments(page_segments, max_body_chars=int(max_body_chars or 6000))
        chapter_unit_counts[chapter_id] = len(chunks)
        section_start_page, section_end_page = chapter_bounds.get(chapter_id, (0, 0))
        for chunk_index, chunk in enumerate(chunks, start=1):
            ps = int(chunk.get("page_start") or 0)
            pe = int(chunk.get("page_end") or int(chunk.get("page_start") or 0))
            cc = int(chunk.get("char_count") or 0)
            st = str(chunk.get("source_text") or "")
            segs = [asdict(row) for row in list(chunk.get("page_segments") or [])]
            page_nos = sorted({int(s.get("page_no", 0)) for s in segs if int(s.get("page_no", 0)) > 0})
            src_hash, plan_hash = _compute_unit_hash(st, ps, pe, cc, page_nos)
            body_units.append(
                FrozenUnit(
                    unit_id=f"body-{chapter_id}-{chunk_index:04d}",
                    kind="body",
                    owner_kind="chapter",
                    owner_id=chapter_id,
                    section_id=chapter_id,
                    section_title=str(chapter.title or ""),
                    section_start_page=int(section_start_page),
                    section_end_page=int(section_end_page),
                    note_id="",
                    page_start=ps,
                    page_end=pe,
                    char_count=cc,
                    source_text=st,
                    translated_text="",
                    status="pending",
                    error_msg="",
                    target_ref="",
                    page_segments=segs,
                    source_hash=src_hash,
                    segment_plan_hash=plan_hash,
                    pipeline_run_id=str(pipeline_run_id or ""),
                )
            )

    note_units: list[FrozenUnit] = []
    seen_note_unit_keys: set[tuple[str, str]] = set()
    unresolved_note_item_ids: list[str] = []
    unresolved_note_item_id_set: set[str] = set()
    chapter_view_note_unit_count = 0
    owner_fallback_note_unit_count = 0

    def _append_note_unit(
        *,
        item: Any,
        resolved_chapter_id: str,
    ) -> bool:
        note_item_id = str(item.note_item_id or "")
        if not note_item_id:
            return False
        dedupe_key = (resolved_chapter_id, note_item_id)
        if dedupe_key in seen_note_unit_keys:
            return False
        chapter = chapter_by_id.get(resolved_chapter_id)
        section_start_page, section_end_page = chapter_bounds.get(
            resolved_chapter_id,
            (int(item.page_no or 0), int(item.page_no or 0)),
        )
        n_ps = int(item.page_no or 0)
        n_pe = int(item.page_no or 0)
        n_cc = len(str(item.text or ""))
        n_st = str(item.text or "")
        n_src_hash, n_plan_hash = _compute_unit_hash(n_st, n_ps, n_pe, n_cc, [n_ps])
        note_units.append(
            FrozenUnit(
                unit_id=f"{str(item.note_kind or 'note')}-{resolved_chapter_id}-{note_item_id}",
                kind=str(item.note_kind or "note"),
                owner_kind="note_region",
                owner_id=str(item.region_id or ""),
                section_id=resolved_chapter_id,
                section_title=str((chapter.title if chapter else resolved_chapter_id) or resolved_chapter_id),
                section_start_page=int(section_start_page),
                section_end_page=int(section_end_page),
                note_id=note_item_id,
                page_start=n_ps,
                page_end=n_pe,
                char_count=n_cc,
                source_text=n_st,
                source_hash=n_src_hash,
                segment_plan_hash=n_plan_hash,
                pipeline_run_id=str(pipeline_run_id or ""),
                translated_text="",
                status="pending",
                error_msg="",
                target_ref=frozen_note_ref(note_item_id),
                page_segments=[],
            )
        )
        seen_note_unit_keys.add(dedupe_key)
        return True

    for chapter in chapter_layers.chapters:
        chapter_note_items = [*list(chapter.footnote_items or []), *list(chapter.endnote_items or [])]
        for item in chapter_note_items:
            resolved_chapter_id, _source = _resolve_note_item_owner(
                item,
                region_by_id=region_by_id,
                valid_chapter_ids=valid_chapter_ids,
            )
            note_item_id = str(item.note_item_id or "")
            if not resolved_chapter_id:
                if note_item_id and note_item_id not in unresolved_note_item_id_set:
                    unresolved_note_item_ids.append(note_item_id)
                    unresolved_note_item_id_set.add(note_item_id)
                continue
            if _append_note_unit(item=item, resolved_chapter_id=resolved_chapter_id):
                chapter_view_note_unit_count += 1

    # 兜底路径：仅补录未被章节视图消费的 raw item
    ordered_note_items = sorted(
        chapter_layers.note_items,
        key=lambda row: (
            int(row.page_no or 0),
            str(row.note_item_id or ""),
        ),
    )
    for item in ordered_note_items:
        resolved_chapter_id, _source = _resolve_note_item_owner(
            item,
            region_by_id=region_by_id,
            valid_chapter_ids=valid_chapter_ids,
        )
        note_item_id = str(item.note_item_id or "")
        if not resolved_chapter_id:
            if note_item_id and note_item_id not in unresolved_note_item_id_set:
                unresolved_note_item_ids.append(note_item_id)
                unresolved_note_item_id_set.add(note_item_id)
            continue
        if _append_note_unit(item=item, resolved_chapter_id=resolved_chapter_id):
            owner_fallback_note_unit_count += 1

    body_units.sort(
        key=lambda row: (
            int(chapter_order.get(str(row.section_id or ""), 10**6)),
            int(row.page_start or 0),
            str(row.unit_id or ""),
        )
    )
    note_units.sort(
        key=lambda row: (
            int(chapter_order.get(str(row.section_id or ""), 10**6)),
            int(row.page_start or 0),
            str(row.unit_id or ""),
        )
    )

    matched_link_ids = {str(row.link_id or "") for row in matched_links}
    injected_rows = [row for row in ref_map if row.decision == "injected"]
    skipped_rows = [row for row in ref_map if row.decision == "skipped"]
    injected_count = len(injected_rows)
    skipped_count = len(ref_map) - injected_count
    synthetic_skipped_count = int(skipped_reason_counts.get("synthetic_anchor", 0))
    conflict_skipped_count = int(skipped_reason_counts.get("conflict_anchor", 0))
    skipped_note_item_ids = sorted(
        {
            str(row.note_item_id or "")
            for row in skipped_rows
            if str(row.note_item_id or "").strip()
        }
    )
    unit_contract_issues = _unit_contract_issues(body_units=body_units, note_units=note_units)
    unit_contract_issues.extend(f"unresolved_note_item:{note_item_id}" for note_item_id in unresolved_note_item_ids)

    error_skip_count = sum(
        1 for row in ref_map
        if row.decision == "skipped" and row.skip_category == "error_skip"
    )
    ceiling_skip_count = sum(
        1 for row in ref_map
        if row.decision == "skipped" and row.skip_category == "ceiling_skip"
    )
    policy_skip_count = sum(
        1 for row in ref_map
        if row.decision == "skipped" and row.skip_category == "policy_skip"
    )

    hard = {
        "freeze.only_matched_frozen": all(str(row.link_id or "") in matched_link_ids for row in injected_rows),
        "freeze.no_duplicate_injection": injected_count == len({str(row.anchor_id or "") for row in injected_rows}),
        "freeze.closed_without_error": (
            len(ref_map) == len(matched_links)
            and all(row.decision in {"injected", "skipped"} for row in ref_map)
            and error_skip_count == 0
        ),
        "freeze.unit_contract_valid": len(unit_contract_issues) == 0,
    }
    soft = {
        "freeze.ceiling_skip_warn": ceiling_skip_count == 0,
        "freeze.policy_skip_warn": policy_skip_count == 0,
        "freeze.synthetic_skip_warn": synthetic_skipped_count == 0,
        "freeze.conflict_skip_warn": conflict_skipped_count == 0,
    }
    reasons: list[str] = []
    if not hard["freeze.only_matched_frozen"]:
        reasons.append("freeze_only_matched_violation")
    if not hard["freeze.no_duplicate_injection"]:
        reasons.append("freeze_duplicate_injection")
    if not hard["freeze.closed_without_error"]:
        if len(ref_map) != len(matched_links) or not all(
            row.decision in {"injected", "skipped"} for row in ref_map
        ):
            reasons.append("freeze_accounting_unclosed")
        if error_skip_count > 0:
            reasons.append("freeze_error_skip_detected")
    if not hard["freeze.unit_contract_valid"]:
        reasons.append("freeze_unit_contract_invalid")

    freeze_summary = {
        "matched_link_count": int(len(matched_links)),
        "injected_count": int(injected_count),
        "skipped_count": int(skipped_count),
        "skip_reason_counts": dict(skipped_reason_counts),
        "skipped_note_item_count": int(len(skipped_note_item_ids)),
        "skipped_note_item_ids_preview": list(skipped_note_item_ids[:24]),
        "skipped_ref_preview": [
            {
                "link_id": str(row.link_id or ""),
                "chapter_id": str(row.chapter_id or ""),
                "anchor_id": str(row.anchor_id or ""),
                "note_item_id": str(row.note_item_id or ""),
                "reason": str(row.reason or ""),
                "skip_category": str(row.skip_category or ""),
                "page_no": int(row.page_no or 0),
            }
            for row in skipped_rows[:24]
        ],
        "skip_category_counts": {
            "ceiling_skip": ceiling_skip_count,
            "policy_skip": policy_skip_count,
            "error_skip": error_skip_count,
        },
        "synthetic_skipped_count": int(synthetic_skipped_count),
        "conflict_anchor_count": int(len(conflict_anchor_ids)),
        "body_unit_count": int(len(body_units)),
        "note_unit_count": int(len(note_units)),
        "chapter_view_note_unit_count": int(chapter_view_note_unit_count),
        "owner_fallback_note_unit_count": int(owner_fallback_note_unit_count),
        "unresolved_note_item_count": int(len(unresolved_note_item_ids)),
        "unresolved_note_item_ids_preview": list(unresolved_note_item_ids[:24]),
        "chapter_unit_counts": {str(key): int(value) for key, value in chapter_unit_counts.items()},
        "empty_body_chapter_count": int(empty_body_chapter_count),
        "max_body_chars": int(max_body_chars or 6000),
    }
    evidence = {
        "freeze_summary": dict(freeze_summary),
        "link_summary": dict(note_link_table.link_summary or {}),
        "matched_link_count": int(len(matched_links)),
    }
    diagnostics = {
        "unit_contract_issues": list(unit_contract_issues),
        "matched_link_ids": sorted(matched_link_ids),
        "conflict_anchor_ids": sorted(conflict_anchor_ids),
    }
    gate_report = GateReport(
        module="freeze",
        hard=hard,
        soft=soft,
        reasons=reasons,
        evidence=evidence,
        overrides_used=[],
    )
    data = FrozenUnits(
        body_units=body_units,
        note_units=note_units,
        ref_map=ref_map,
        freeze_summary=freeze_summary,
    )
    return ModuleResult(
        data=data,
        gate_report=gate_report,
        evidence=evidence,
        overrides_used=[],
        diagnostics=diagnostics,
    )

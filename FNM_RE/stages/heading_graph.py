"""phase1 heading graph 锚点优化器。"""

from __future__ import annotations

import re
from typing import Any

from FNM_RE.shared.title import normalize_title, normalized_title_key

_BODY_PAGE_ROLES = {"body", "front_matter"}
_HEADING_GRAPH_PREVIEW_LIMIT = 8

_LATEX_NOTE_MARKER_RE = re.compile(r"\$\s*\^\{[^}]+\}\s*\$")
_INLINE_NOTE_MARKER_RE = re.compile(r"\^\{[^}]+\}")
_TRAILING_NOTE_MARKER_RE = re.compile(r"(?:\s*(?:\[[0-9A-Za-z]{1,4}\]|[†‡*§]+))+\s*$")
_LEADING_QUOTES_RE = re.compile(r"^[\"'“”‘’«»\(\)\[\]\-–—:;,.]+")
_LEADING_CHAPTER_LABEL_WITH_NUMBER_RE = re.compile(
    r"^\s*(?:chapter|chapitre|part|partie|section|book|livre)\s+(?:\d+(?:\.\d+)*|[ivxlcdm]+)\b[\.\):\-–—]?\s*",
    re.IGNORECASE,
)
_LEADING_CHAPTER_LABEL_RE = re.compile(
    r"^\s*(?:chapter|chapitre|part|partie|section|book|livre)\b[:\s\-–—]*",
    re.IGNORECASE,
)
_LEADING_NUMBER_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\.\):\-–—]?\s+",
    re.IGNORECASE,
)
_PLAIN_NUMBER_RE = re.compile(r"^(?:\d+(?:\.\d+)*|[ivxlcdm]+)$", re.IGNORECASE)
_CHAPTER_NUMBER_LABEL_RE = re.compile(
    r"^(?:chapter|chapitre|part|partie|section|book|livre)\s+(?:\d+(?:\.\d+)*|[ivxlcdm]+)$",
    re.IGNORECASE,
)


def default_heading_graph_summary() -> dict[str, Any]:
    return {
        "toc_body_item_count": 0,
        "resolved_anchor_count": 0,
        "provisional_anchor_count": 0,
        "section_node_count": 0,
        "unresolved_titles_preview": [],
        "boundary_conflict_titles_preview": [],
        "promoted_section_titles_preview": [],
        "demoted_chapter_titles_preview": [],
        "optimized_anchor_count": 0,
        "residual_provisional_count": 0,
        "residual_provisional_titles_preview": [],
        "expanded_window_hit_count": 0,
        "composite_heading_count": 0,
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_font_weight_hint(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"regular", "bold", "heavy", "unknown"}:
        return token
    return "unknown"


def _normalize_align_hint(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"left", "center", "right", "unknown"}:
        return token
    return "unknown"


def _compact_unique_titles(values: list[str]) -> list[str]:
    compact: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_title(value)
        if not normalized:
            continue
        key = _heading_graph_title_key(normalized) or normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        compact.append(normalized)
    return compact


def _heading_graph_title_key(value: Any) -> str:
    normalized = normalize_title(value)
    if not normalized:
        return ""
    normalized = _LATEX_NOTE_MARKER_RE.sub(" ", normalized)
    normalized = _INLINE_NOTE_MARKER_RE.sub(" ", normalized)
    normalized = _TRAILING_NOTE_MARKER_RE.sub("", normalized).strip()
    normalized = _LEADING_QUOTES_RE.sub("", normalized).strip()
    previous = ""
    while normalized and normalized != previous:
        previous = normalized
        normalized = _LEADING_CHAPTER_LABEL_WITH_NUMBER_RE.sub("", normalized).strip()
        normalized = _LEADING_CHAPTER_LABEL_RE.sub("", normalized).strip()
        normalized = _LEADING_NUMBER_RE.sub("", normalized).strip()
        normalized = _LEADING_QUOTES_RE.sub("", normalized).strip()
    return normalized_title_key(normalized)


def _font_family_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    token = re.split(r"[-,]", token, maxsplit=1)[0]
    token = re.sub(r"[^a-z0-9]+", "", token)
    return token


def _candidate_page_role(candidate: dict[str, Any], page_role_by_no: dict[int, str]) -> str:
    return str(page_role_by_no.get(_safe_int(candidate.get("page_no"))) or "")


def _is_anchor_candidate(candidate: dict[str, Any], *, page_role_by_no: dict[int, str]) -> bool:
    page_no = _safe_int(candidate.get("page_no"))
    if page_no <= 0:
        return False
    if _candidate_page_role(candidate, page_role_by_no) not in _BODY_PAGE_ROLES:
        return False
    source = str(candidate.get("source") or "")
    if source in {"visual_toc", "note_heading"}:
        return False
    return True


def _is_section_candidate(candidate: dict[str, Any], *, page_role_by_no: dict[int, str]) -> bool:
    page_no = _safe_int(candidate.get("page_no"))
    if page_no <= 0:
        return False
    if _candidate_page_role(candidate, page_role_by_no) not in _BODY_PAGE_ROLES:
        return False
    if str(candidate.get("source") or "") in {"visual_toc", "note_heading"}:
        return False
    if bool(candidate.get("derived_heading")):
        return False
    heading_level_hint = _safe_int(candidate.get("heading_level_hint"))
    family = str(candidate.get("heading_family_guess") or "").strip().lower()
    return heading_level_hint >= 2 or family == "section" or bool(candidate.get("suppressed_as_chapter"))


def _is_section_style_candidate(candidate: dict[str, Any]) -> bool:
    heading_level_hint = _safe_int(candidate.get("heading_level_hint"))
    family = str(candidate.get("heading_family_guess") or "").strip().lower()
    return heading_level_hint >= 2 or family == "section"


def _is_chapter_number_candidate(text: str) -> bool:
    normalized = normalize_title(text)
    if not normalized:
        return False
    return bool(_PLAIN_NUMBER_RE.match(normalized) or _CHAPTER_NUMBER_LABEL_RE.match(normalized))


def _candidate_y(candidate: dict[str, Any]) -> float:
    return _safe_float(candidate.get("y")) or 0.0


def _candidate_x(candidate: dict[str, Any]) -> float:
    return _safe_float(candidate.get("x")) or 0.0


def _candidate_confidence(candidate: dict[str, Any]) -> float:
    return float(_safe_float(candidate.get("confidence")) or 0.0)


def _candidate_text(candidate: dict[str, Any]) -> str:
    return normalize_title(candidate.get("text") or "")


def _same_style_pdf_pair(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if str(left.get("source") or "") != "pdf_font_band" or str(right.get("source") or "") != "pdf_font_band":
        return False
    if _safe_int(left.get("page_no")) != _safe_int(right.get("page_no")):
        return False
    y_gap = _candidate_y(right) - _candidate_y(left)
    if y_gap <= 0.0 or y_gap > 54.0:
        return False
    align_left = _normalize_align_hint(left.get("align_hint"))
    align_right = _normalize_align_hint(right.get("align_hint"))
    if (
        align_left != "unknown"
        and align_right != "unknown"
        and align_left != align_right
        and not {align_left, align_right} <= {"left", "center"}
    ):
        return False
    family_left = _font_family_token(left.get("font_name"))
    family_right = _font_family_token(right.get("font_name"))
    if family_left and family_right and family_left != family_right:
        return False
    x_gap = abs(_candidate_x(right) - _candidate_x(left))
    if max(align_left, align_right) == "center":
        return x_gap <= 140.0
    return x_gap <= 96.0


def _compose_heading_parts(parts: list[dict[str, Any]], *, composite_kind: str) -> dict[str, Any] | None:
    texts = [_candidate_text(part) for part in parts]
    if any(not text for text in texts):
        return None
    page_no = _safe_int(parts[0].get("page_no"))
    text = normalize_title(" ".join(texts))
    if not text:
        return None
    width_values = [_safe_float(part.get("width_estimate")) for part in parts]
    confidence_values = [_candidate_confidence(part) for part in parts]
    heading_level_hint = min(
        (
            _safe_int(part.get("heading_level_hint"))
            for part in parts
            if _safe_int(part.get("heading_level_hint")) > 0
        ),
        default=1,
    )
    font_weight = "heavy" if any(_normalize_font_weight_hint(part.get("font_weight_hint")) == "heavy" for part in parts) else (
        "bold" if any(_normalize_font_weight_hint(part.get("font_weight_hint")) == "bold" for part in parts) else "regular"
    )
    align_hint = next(
        (
            _normalize_align_hint(part.get("align_hint"))
            for part in parts
            if _normalize_align_hint(part.get("align_hint")) != "unknown"
        ),
        "unknown",
    )
    return {
        "heading_id": f"heading-graph-{composite_kind}-{page_no}-{abs(hash((page_no, text))) % 10**8}",
        "page_no": page_no,
        "text": text,
        "normalized_text": text,
        "source": "pdf_font_band_composite",
        "block_label": "",
        "top_band": all(bool(part.get("top_band")) for part in parts),
        "confidence": max(confidence_values, default=0.0),
        "heading_family_guess": "chapter",
        "suppressed_as_chapter": False,
        "reject_reason": "",
        "font_height": max((_safe_float(part.get("font_height")) or 0.0) for part in parts),
        "x": min((_candidate_x(part) for part in parts), default=0.0),
        "y": min((_candidate_y(part) for part in parts), default=0.0),
        "width_estimate": sum(value for value in width_values if value is not None),
        "font_name": str(parts[0].get("font_name") or ""),
        "font_weight_hint": font_weight,
        "align_hint": align_hint,
        "width_ratio": max((_safe_float(part.get("width_ratio")) or 0.0) for part in parts),
        "heading_level_hint": heading_level_hint,
        "derived_heading": True,
        "composite_kind": composite_kind,
    }


def _build_same_style_pdf_composites(pdf_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    composites: list[dict[str, Any]] = []
    for index, candidate in enumerate(pdf_candidates):
        chain = [candidate]
        for next_index in range(index + 1, min(index + 4, len(pdf_candidates))):
            nxt = pdf_candidates[next_index]
            if not _same_style_pdf_pair(chain[-1], nxt):
                break
            chain.append(nxt)
            composed = _compose_heading_parts(chain, composite_kind="multiline")
            if composed is not None:
                composites.append(composed)
    return composites


def _build_chapter_number_pairs(pdf_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    composites: list[dict[str, Any]] = []
    for index, candidate in enumerate(pdf_candidates):
        if not _is_chapter_number_candidate(_candidate_text(candidate)):
            continue
        title_parts: list[dict[str, Any]] = []
        for next_index in range(index + 1, min(index + 4, len(pdf_candidates))):
            nxt = pdf_candidates[next_index]
            y_gap = _candidate_y(nxt) - (_candidate_y(title_parts[-1]) if title_parts else _candidate_y(candidate))
            if y_gap <= 0.0 or y_gap > 64.0:
                break
            if _is_chapter_number_candidate(_candidate_text(nxt)):
                break
            if title_parts and not _same_style_pdf_pair(title_parts[-1], nxt):
                break
            title_parts.append(nxt)
            composed = _compose_heading_parts([candidate, *title_parts], composite_kind="chapter_number_pair")
            if composed is not None:
                composites.append(composed)
    return composites


def _build_derived_heading_candidates(
    heading_candidates: list[dict[str, Any]],
    *,
    page_role_by_no: dict[int, str],
) -> tuple[list[dict[str, Any]], int]:
    pdf_by_page: dict[int, list[dict[str, Any]]] = {}
    for candidate in heading_candidates or []:
        if not _is_anchor_candidate(candidate, page_role_by_no=page_role_by_no):
            continue
        if str(candidate.get("source") or "") != "pdf_font_band":
            continue
        pdf_by_page.setdefault(_safe_int(candidate.get("page_no")), []).append(dict(candidate))

    derived: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for page_no, page_candidates in pdf_by_page.items():
        ordered = sorted(page_candidates, key=lambda item: (_candidate_y(item), _candidate_x(item)))
        page_derived = _build_same_style_pdf_composites(ordered) + _build_chapter_number_pairs(ordered)
        for candidate in page_derived:
            title = _candidate_text(candidate)
            title_key = _heading_graph_title_key(title)
            if not title_key:
                continue
            dedupe_key = (page_no, title_key, str(candidate.get("composite_kind") or ""))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            derived.append(candidate)
    return derived, len(derived)


def _candidate_source_score(candidate: dict[str, Any]) -> int:
    source = str(candidate.get("source") or "")
    block_label = str(candidate.get("block_label") or "")
    if source == "pdf_font_band_composite":
        return 320
    if source == "ocr_block" and block_label == "doc_title":
        return 300
    if source == "markdown_heading":
        return 220
    if source == "ocr_block":
        return 180
    if source == "pdf_font_band":
        return 160
    return 80


def _candidate_evidence_score(candidate: dict[str, Any]) -> int:
    score = _candidate_source_score(candidate)
    family = str(candidate.get("heading_family_guess") or "").strip().lower()
    if family in {"chapter", "book"}:
        score += 60
    elif family == "section":
        score += 12
    heading_level_hint = _safe_int(candidate.get("heading_level_hint"))
    if heading_level_hint == 1:
        score += 36
    elif heading_level_hint >= 2:
        score += 10
    if bool(candidate.get("top_band")):
        score += 20
    font_weight_hint = _normalize_font_weight_hint(candidate.get("font_weight_hint"))
    if font_weight_hint == "heavy":
        score += 16
    elif font_weight_hint == "bold":
        score += 10
    align_hint = _normalize_align_hint(candidate.get("align_hint"))
    if align_hint == "center":
        score += 12
    score += int(round(_candidate_confidence(candidate) * 10))
    return score


def _has_strong_chapter_evidence(candidate: dict[str, Any]) -> bool:
    source = str(candidate.get("source") or "")
    block_label = str(candidate.get("block_label") or "")
    if source == "pdf_font_band_composite":
        return True
    if source == "ocr_block" and block_label == "doc_title":
        return True
    if source == "markdown_heading":
        return True
    signals = 0
    family = str(candidate.get("heading_family_guess") or "").strip().lower()
    if family in {"chapter", "book"}:
        signals += 1
    if _safe_int(candidate.get("heading_level_hint")) == 1:
        signals += 1
    if bool(candidate.get("top_band")):
        signals += 1
    if _normalize_font_weight_hint(candidate.get("font_weight_hint")) in {"bold", "heavy"}:
        signals += 1
    if _normalize_align_hint(candidate.get("align_hint")) == "center":
        signals += 1
    required = 4 if _is_section_style_candidate(candidate) else 3
    return signals >= required


def _candidate_sort_key(
    candidate: dict[str, Any],
    *,
    target_page: int,
    prev_anchor_page: int,
    next_anchor_page: int,
) -> tuple[int, int, int, int, int, int]:
    page_no = _safe_int(candidate.get("page_no"))
    monotonic_ok = 1
    if prev_anchor_page > 0 and page_no <= prev_anchor_page:
        monotonic_ok = 0
    if next_anchor_page > 0 and page_no >= next_anchor_page:
        monotonic_ok = 0
    return (
        1,
        monotonic_ok,
        _candidate_evidence_score(candidate),
        -abs(page_no - target_page),
        int(round(_candidate_confidence(candidate) * 100)),
        -page_no,
    )


def _exact_matching_candidates(
    title_key: str,
    *,
    candidates: list[dict[str, Any]],
    start_page: int,
    end_page: int,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for candidate in candidates:
        page_no = _safe_int(candidate.get("page_no"))
        if page_no < start_page or page_no > end_page:
            continue
        if _heading_graph_title_key(candidate.get("text") or "") != title_key:
            continue
        matched.append(candidate)
    return matched


def _best_candidate(
    title_key: str,
    *,
    candidates: list[dict[str, Any]],
    start_page: int,
    end_page: int,
    target_page: int,
    prev_anchor_page: int,
    next_anchor_page: int,
    require_strong: bool,
) -> dict[str, Any] | None:
    exact_candidates = _exact_matching_candidates(
        title_key,
        candidates=candidates,
        start_page=start_page,
        end_page=end_page,
    )
    if require_strong:
        exact_candidates = [candidate for candidate in exact_candidates if _has_strong_chapter_evidence(candidate)]
    if not exact_candidates:
        return None
    ranked = sorted(
        exact_candidates,
        key=lambda candidate: _candidate_sort_key(
            candidate,
            target_page=target_page,
            prev_anchor_page=prev_anchor_page,
            next_anchor_page=next_anchor_page,
        ),
        reverse=True,
    )
    return dict(ranked[0]) if ranked else None


def _body_stop_pages(page_rows: list[dict[str, Any]]) -> list[int]:
    return sorted(
        {
            _safe_int(row.get("page_no"))
            for row in page_rows or []
            if _safe_int(row.get("page_no")) > 0
            and str(row.get("page_role") or "") not in _BODY_PAGE_ROLES
        }
    )


def _next_stop_page(stop_pages: list[int], *, after_page: int) -> int:
    for page_no in stop_pages:
        if page_no > after_page:
            return page_no
    return 0


def build_heading_graph(
    *,
    exportable_rows: list[dict],
    heading_candidates: list[dict],
    page_rows: list[dict],
) -> tuple[list[dict], dict[str, Any]]:
    if not exportable_rows:
        return [], default_heading_graph_summary()

    page_role_by_no = {
        _safe_int(row.get("page_no")): str(row.get("page_role") or "")
        for row in page_rows or []
        if _safe_int(row.get("page_no")) > 0
    }
    body_pages = [
        _safe_int(row.get("page_no"))
        for row in page_rows or []
        if _safe_int(row.get("page_no")) > 0 and str(row.get("page_role") or "") in _BODY_PAGE_ROLES
    ]
    max_body_page = max(body_pages) if body_pages else 0
    stop_pages = _body_stop_pages(page_rows)

    raw_candidates = [dict(candidate) for candidate in heading_candidates or []]
    derived_candidates, composite_heading_count = _build_derived_heading_candidates(
        raw_candidates,
        page_role_by_no=page_role_by_no,
    )
    anchor_candidates = [
        candidate
        for candidate in [*raw_candidates, *derived_candidates]
        if _is_anchor_candidate(candidate, page_role_by_no=page_role_by_no)
    ]

    graph_rows: list[dict[str, Any]] = []
    unresolved_titles: list[str] = []
    promoted_section_titles: list[str] = []
    demoted_titles = _compact_unique_titles(
        [
            str(candidate.get("text") or "")
            for candidate in raw_candidates
            if bool(candidate.get("suppressed_as_chapter"))
        ]
    )[:_HEADING_GRAPH_PREVIEW_LIMIT]

    prev_anchor_page = 0
    for index, row in enumerate(exportable_rows):
        current = dict(row)
        title = str(current.get("title") or "")
        title_key = _heading_graph_title_key(title)
        target_page = _safe_int(current.get("page_no"))
        local_start = max(1, target_page - 1) if target_page > 0 else 1
        local_end = max(local_start, target_page + 2) if target_page > 0 else 0
        next_target_page = _safe_int(exportable_rows[index + 1].get("page_no")) if index + 1 < len(exportable_rows) else 0
        local_candidate = None
        if title_key and local_end > 0:
            local_candidate = _best_candidate(
                title_key,
                candidates=anchor_candidates,
                start_page=local_start,
                end_page=local_end,
                target_page=target_page,
                prev_anchor_page=prev_anchor_page,
                next_anchor_page=next_target_page,
                require_strong=False,
            )

        anchor_page = 0
        anchor_state = "unresolved"
        anchor_candidate: dict[str, Any] | None = None
        anchor_strategy = "unresolved"
        optimized_anchor = False
        expanded_window_hit = False
        if local_candidate is not None:
            anchor_candidate = dict(local_candidate)
            anchor_page = _safe_int(anchor_candidate.get("page_no"))
            anchor_state = "resolved"
            anchor_strategy = "local_exact"
            optimized_anchor = anchor_page != target_page or _is_section_style_candidate(anchor_candidate)
            if _is_section_style_candidate(anchor_candidate):
                promoted_section_titles.append(title)
        elif target_page > 0 and str(page_role_by_no.get(target_page) or "") in _BODY_PAGE_ROLES:
            anchor_page = target_page
            if str(current.get("semantic_role") or "") == "post_body":
                anchor_state = "resolved"
                anchor_strategy = "post_body_target"
            else:
                anchor_state = "provisional"
                anchor_strategy = "provisional"
        else:
            unresolved_titles.append(title)

        graph_row = {
            **current,
            "anchor_page": anchor_page,
            "anchor_state": anchor_state,
            "anchor_candidate_source": str((anchor_candidate or {}).get("source") or ""),
            "anchor_strategy": anchor_strategy,
            "_target_page": target_page,
            "_optimized_anchor": bool(optimized_anchor),
            "_expanded_window_hit": bool(expanded_window_hit),
            "_anchor_candidate": dict(anchor_candidate) if anchor_candidate is not None else None,
        }
        graph_rows.append(graph_row)
        if anchor_page > 0:
            prev_anchor_page = anchor_page

    for index, row in enumerate(graph_rows):
        if str(row.get("anchor_state") or "") != "provisional":
            continue
        title = str(row.get("title") or "")
        title_key = _heading_graph_title_key(title)
        if not title_key:
            continue
        target_page = _safe_int(row.get("_target_page"))
        prev_final_anchor = max(
            (_safe_int(graph_rows[position].get("anchor_page")) for position in range(index - 1, -1, -1)),
            default=0,
        )
        next_anchor_or_target = 0
        if index + 1 < len(graph_rows):
            next_row = graph_rows[index + 1]
            next_anchor_or_target = _safe_int(next_row.get("anchor_page")) or _safe_int(next_row.get("_target_page"))
        left = max(prev_final_anchor + 1, target_page - 6)
        right_candidates = [target_page + 10]
        if next_anchor_or_target > 0:
            right_candidates.append(next_anchor_or_target - 1)
        next_stop = _next_stop_page(stop_pages, after_page=target_page)
        if next_stop > 0:
            right_candidates.append(next_stop - 1)
        right = min(right_candidates) if right_candidates else 0
        if left <= 0 or right <= 0 or right < left:
            continue
        expanded_candidate = _best_candidate(
            title_key,
            candidates=anchor_candidates,
            start_page=left,
            end_page=right,
            target_page=target_page,
            prev_anchor_page=prev_final_anchor,
            next_anchor_page=next_anchor_or_target,
            require_strong=True,
        )
        if expanded_candidate is None:
            continue
        row["anchor_page"] = _safe_int(expanded_candidate.get("page_no"))
        row["anchor_state"] = "resolved"
        row["anchor_candidate_source"] = str(expanded_candidate.get("source") or "")
        row["anchor_strategy"] = "expanded_exact"
        row["_anchor_candidate"] = dict(expanded_candidate)
        row["_expanded_window_hit"] = True
        row["_optimized_anchor"] = True
        if _is_section_style_candidate(expanded_candidate):
            promoted_section_titles.append(title)

    monotonic_target_upgrade_enabled = len(exportable_rows) >= 2
    for index, row in enumerate(graph_rows):
        if not monotonic_target_upgrade_enabled:
            continue
        if str(row.get("anchor_state") or "") != "provisional":
            continue
        target_page = _safe_int(row.get("_target_page"))
        if target_page <= 0:
            continue
        if str(page_role_by_no.get(target_page) or "") not in _BODY_PAGE_ROLES:
            continue
        prev_final_anchor = max(
            (_safe_int(graph_rows[position].get("anchor_page")) for position in range(index - 1, -1, -1)),
            default=0,
        )
        next_anchor_or_target = 0
        if index + 1 < len(graph_rows):
            next_row = graph_rows[index + 1]
            next_anchor_or_target = _safe_int(next_row.get("anchor_page")) or _safe_int(next_row.get("_target_page"))
        if prev_final_anchor > 0 and target_page <= prev_final_anchor:
            continue
        if next_anchor_or_target > 0 and target_page >= next_anchor_or_target:
            continue
        row["anchor_page"] = target_page
        row["anchor_state"] = "resolved"
        row["anchor_strategy"] = "monotonic_target"
        row["_optimized_anchor"] = True

    boundary_conflict_titles: list[str] = []
    previous_row: dict[str, Any] | None = None
    for row in graph_rows:
        anchor_page = _safe_int(row.get("anchor_page"))
        if anchor_page <= 0:
            continue
        if previous_row is not None and anchor_page <= _safe_int(previous_row.get("anchor_page")):
            boundary_conflict_titles.append(str(previous_row.get("title") or ""))
            boundary_conflict_titles.append(str(row.get("title") or ""))
        previous_row = row

    section_candidates = [
        candidate
        for candidate in raw_candidates
        if _is_section_candidate(candidate, page_role_by_no=page_role_by_no)
    ]
    section_nodes: list[dict[str, Any]] = []
    anchored_rows = [row for row in graph_rows if _safe_int(row.get("anchor_page")) > 0]
    for index, anchor_row in enumerate(anchored_rows):
        start_page = _safe_int(anchor_row.get("anchor_page"))
        next_page = _safe_int(anchored_rows[index + 1].get("anchor_page")) if index + 1 < len(anchored_rows) else max_body_page + 1
        for candidate in section_candidates:
            page_no = _safe_int(candidate.get("page_no"))
            if page_no < start_page:
                continue
            if next_page > 0 and page_no >= next_page:
                continue
            section_nodes.append(
                {
                    "title": str(candidate.get("text") or ""),
                    "page_no": page_no,
                    "chapter_title": str(anchor_row.get("title") or ""),
                }
            )

    seen_sections: set[tuple[int, str]] = set()
    unique_section_nodes: list[dict[str, Any]] = []
    for node in section_nodes:
        key = (_safe_int(node.get("page_no")), _heading_graph_title_key(node.get("title") or ""))
        if key in seen_sections:
            continue
        seen_sections.add(key)
        unique_section_nodes.append(node)

    residual_provisional_titles = [
        str(row.get("title") or "")
        for row in graph_rows
        if str(row.get("anchor_state") or "") == "provisional"
    ]
    summary = {
        "toc_body_item_count": len(exportable_rows),
        "resolved_anchor_count": sum(1 for row in graph_rows if str(row.get("anchor_state") or "") == "resolved"),
        "provisional_anchor_count": sum(1 for row in graph_rows if str(row.get("anchor_state") or "") == "provisional"),
        "section_node_count": len(unique_section_nodes),
        "unresolved_titles_preview": _compact_unique_titles(unresolved_titles)[:_HEADING_GRAPH_PREVIEW_LIMIT],
        "boundary_conflict_titles_preview": _compact_unique_titles(boundary_conflict_titles)[:_HEADING_GRAPH_PREVIEW_LIMIT],
        "promoted_section_titles_preview": _compact_unique_titles(promoted_section_titles)[:_HEADING_GRAPH_PREVIEW_LIMIT],
        "demoted_chapter_titles_preview": list(demoted_titles),
        "optimized_anchor_count": sum(1 for row in graph_rows if bool(row.get("_optimized_anchor"))),
        "residual_provisional_count": sum(1 for row in graph_rows if str(row.get("anchor_state") or "") == "provisional"),
        "residual_provisional_titles_preview": _compact_unique_titles(residual_provisional_titles)[:_HEADING_GRAPH_PREVIEW_LIMIT],
        "expanded_window_hit_count": sum(1 for row in graph_rows if bool(row.get("_expanded_window_hit"))),
        "composite_heading_count": composite_heading_count,
    }
    for row in graph_rows:
        row.pop("_target_page", None)
        row.pop("_optimized_anchor", None)
        row.pop("_expanded_window_hit", None)
        row.pop("_anchor_candidate", None)
    return graph_rows, summary

"""FNM_RE 第三阶段：body_anchors。"""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any

from FNM_RE.models import BodyAnchorRecord, Phase2Structure
from FNM_RE.shared.chapters import chapter_id_for_page, chapter_id_for_page as _chapter_id_for_page
from FNM_RE.shared.anchors import (
    _BARE_DIGIT_STRUCTURAL_PREFIX,
    resolve_anchor_kind,
    scan_anchor_markers,
)

_WEAK_EXPECTED_DIGIT_RE = re.compile(
    r"\s(\d{1,3})(?=(?:\s*[.,;:)\]\}»”’\"]|\s+[A-Za-zÀ-ÖØ-öø-ÿ]))"
)
_WEAK_DIGIT_LEFT_WORD_RE = re.compile(
    r"([A-Za-zàâäéèêëïîôöùûüÿçœÀÂÄÉÈÊËÏÎÔÖÙÛÜŸÇŒ]+)\s*$"
)
_WEAK_EXPECTED_SYMBOL_RE = re.compile(
    r"(?<=[A-Za-zÀ-ÖØ-öø-ÿ])(\*{1,3})(?=(?:\s|[.,;:)\]\}»”’\"]))"
)
_CONTEXT_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
_CONTEXT_STOPWORDS = frozenset(
    {
        "avec", "cette", "dans", "dont", "elle", "elles", "entre",
        "pour", "quand", "sans", "sont", "tout", "toute", "vous",
        "mais", "donc", "comme", "plus", "moins", "faire", "fait",
        "être", "etre", "cela", "ceci", "leur", "leurs",
        "dune", "dun", "dune",
    }
)


def _chapter_id_for_page(phase2: Phase2Structure, page_no: int) -> str:
    return chapter_id_for_page(phase2.chapters, page_no)


def _page_payload_by_no(pages: list[dict]) -> dict[int, dict]:
    mapping: dict[int, dict] = {}
    for page in pages or []:
        try:
            page_no = int(page.get("bookPage") or 0)
        except (TypeError, ValueError):
            continue
        if page_no > 0:
            mapping[page_no] = dict(page)
    return mapping


def _footnote_band_page_keys(phase2: Phase2Structure) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    for region in phase2.note_regions:
        if region.note_kind != "footnote":
            continue
        chapter_id = str(region.chapter_id or "").strip()
        if not chapter_id:
            continue
        for page_no in region.pages:
            if int(page_no) > 0:
                keys.add((chapter_id, int(page_no)))
    return keys


def _build_summary(
    anchors: list[BodyAnchorRecord], *, year_like_filtered_count: int
) -> dict[str, Any]:
    kind_counts = Counter(anchor.anchor_kind for anchor in anchors)
    explicit_count = sum(1 for anchor in anchors if not anchor.synthetic)
    synthetic_count = sum(1 for anchor in anchors if anchor.synthetic)
    uncertain_count = sum(
        1
        for anchor in anchors
        if anchor.anchor_kind == "unknown" or float(anchor.certainty) < 1.0
    )
    ocr_repaired_count = sum(
        1 for anchor in anchors if str(anchor.ocr_repaired_from_marker or "").strip()
    )
    return {
        "total_count": len(anchors),
        "explicit_count": int(explicit_count),
        "synthetic_count": int(synthetic_count),
        "kind_counts": dict(kind_counts),
        "uncertain_count": int(uncertain_count),
        "ocr_repaired_count": int(ocr_repaired_count),
        "year_like_filtered_count": int(year_like_filtered_count),
    }


def _build_chapter_marker_range(phase2: Phase2Structure) -> dict[str, tuple[int, int]]:
    chapter_markers: dict[str, list[int]] = {}
    for item in phase2.note_items:
        chapter_id = str(item.chapter_id or "").strip()
        if not chapter_id:
            continue
        try:
            marker = int(item.marker)
        except (ValueError, TypeError):
            continue
        if marker <= 0:
            continue
        chapter_markers.setdefault(chapter_id, []).append(marker)
    return {
        ch_id: (min(markers), max(markers))
        for ch_id, markers in chapter_markers.items()
        if markers
    }


def _build_chapter_note_items_set(phase2: Phase2Structure) -> dict[str, set[int]]:
    sets: dict[str, set[int]] = {}
    for item in phase2.note_items:
        chapter_id = str(item.chapter_id or "").strip()
        if not chapter_id:
            continue
        try:
            marker = int(item.marker)
        except (ValueError, TypeError):
            continue
        if marker <= 0:
            continue
        sets.setdefault(chapter_id, set()).add(marker)
    return sets


def _build_chapter_endnote_marker_set(phase2: Phase2Structure) -> dict[str, set[int]]:
    endnote_region_ids: set[str] = {
        str(r.region_id or "").strip()
        for r in phase2.note_regions
        if str(r.note_kind or "") == "endnote" and str(r.region_id or "").strip()
    }
    sets: dict[str, set[int]] = {}
    for item in phase2.note_items:
        if str(item.region_id or "").strip() not in endnote_region_ids:
            continue
        chapter_id = str(item.chapter_id or "").strip()
        if not chapter_id:
            continue
        try:
            marker = int(item.marker)
        except (ValueError, TypeError):
            continue
        if marker <= 0:
            continue
        sets.setdefault(chapter_id, set()).add(marker)
    return sets


def _build_chapter_endnote_text_by_marker(phase2: Phase2Structure) -> dict[str, dict[int, str]]:
    endnote_region_ids: set[str] = {
        str(r.region_id or "").strip()
        for r in phase2.note_regions
        if str(r.note_kind or "") == "endnote" and str(r.region_id or "").strip()
    }
    rows: dict[str, dict[int, str]] = defaultdict(dict)
    for item in phase2.note_items:
        if str(item.region_id or "").strip() not in endnote_region_ids:
            continue
        chapter_id = str(item.chapter_id or "").strip()
        marker = _int_marker(getattr(item, "marker", ""))
        if not chapter_id or marker is None:
            continue
        rows[chapter_id][marker] = str(getattr(item, "text", "") or "")
    return {chapter_id: dict(items) for chapter_id, items in rows.items()}


def _marker_in_expected_range(
    normalized_marker: str,
    *,
    pattern: str,
    marker_min: int,
    marker_max: int,
    has_page_footnote_band: bool = False,
) -> bool:
    if has_page_footnote_band:
        return True
    if marker_max <= 0:
        return True
    try:
        marker_val = int(normalized_marker)
    except (ValueError, TypeError):
        return True
    if pattern in {"latex", "latex_symbol_sup", "plain", "html", "unicode", "footnote_ref", "apostrophe_sup"}:
        return True
    if pattern == "bare_digit":
        return marker_min <= marker_val <= marker_max
    tolerance = max(3, int(marker_max * 0.03))
    return marker_min <= marker_val <= marker_max + tolerance


_BARE_DIGIT_VALID_SENTENCE_END = frozenset({".", ";", ":", "!", "?", ",", "—", "–", "-"})


def _is_bare_digit_false_positive_context(anchor: BodyAnchorRecord) -> bool:
    source_text = str(anchor.source_text or "").strip()
    if not source_text:
        return False
    char_end = int(anchor.char_end or 0)
    remainder = source_text[char_end:]
    if not remainder.strip():
        return False
    next_char = remainder.lstrip()[0] if remainder.lstrip() else ""
    if next_char in _BARE_DIGIT_VALID_SENTENCE_END:
        return False
    return True


def _positive_gate_bare_digit(
    anchors: list[BodyAnchorRecord],
    *,
    chapter_note_items: dict[str, set[int]],
    pdf_path: str = "",
    pages: list[dict] | None = None,
) -> tuple[list[BodyAnchorRecord], list[BodyAnchorRecord]]:
    """正向证据 gate：bare_digit 必须满足正向条件才能保留。
    条件 3/4 被拒绝的候选送 LLM 视觉验证做二次判断。"""
    non_bare: list[BodyAnchorRecord] = []
    bare_candidates: list[BodyAnchorRecord] = []
    for anchor in anchors:
        if anchor.source.endswith(":bare_digit"):
            bare_candidates.append(anchor)
        else:
            non_bare.append(anchor)

    if not bare_candidates:
        return anchors, []

    covered_by_chapter: dict[str, set[int]] = defaultdict(set)
    for anchor in non_bare:
        try:
            val = int(anchor.normalized_marker)
        except (ValueError, TypeError):
            continue
        covered_by_chapter[anchor.chapter_id].add(val)

    bare_count_by_chapter: dict[str, Counter[int]] = defaultdict(Counter)
    for anchor in bare_candidates:
        try:
            val = int(anchor.normalized_marker)
        except (ValueError, TypeError):
            continue
        bare_count_by_chapter[anchor.chapter_id][val] += 1

    accepted_bare: list[BodyAnchorRecord] = []
    llm_candidates: list[BodyAnchorRecord] = []
    for anchor in bare_candidates:
        chapter_id = anchor.chapter_id
        try:
            marker_val = int(anchor.normalized_marker)
        except (ValueError, TypeError):
            continue
        note_items_set = chapter_note_items.get(chapter_id)
        if not note_items_set or marker_val not in note_items_set:
            continue
        if marker_val in covered_by_chapter[chapter_id]:
            continue
        if bare_count_by_chapter[chapter_id][marker_val] > 2:
            llm_candidates.append(anchor)
            continue
        if _is_bare_digit_false_positive_context(anchor):
            llm_candidates.append(anchor)
            continue
        accepted_bare.append(anchor)

    llm_verified: list[BodyAnchorRecord] = []
    if llm_candidates and pdf_path and pages:
        try:
            from FNM_RE.modules.llm_bare_digit_verify import (
                verify_bare_digit_candidates,
            )  # lazy import：避免 body_anchors ↔ modules 循环依赖
            verified, _rejected, _summary = verify_bare_digit_candidates(
                llm_candidates, pdf_path=pdf_path, pages=pages,
            )
            llm_verified = list(verified)
        except Exception:
            pass

    return non_bare + accepted_bare + llm_verified, llm_verified


def _int_marker(value: Any) -> int | None:
    try:
        marker = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return marker if marker > 0 else None


def _scan_expected_gap_bare_digits(text: str, expected_markers: set[int]) -> list[dict]:
    if not expected_markers:
        return []
    content = str(text or "")
    matches: list[dict] = []
    for match in _WEAK_EXPECTED_DIGIT_RE.finditer(content):
        marker = _int_marker(match.group(1))
        if marker is None or marker not in expected_markers:
            continue
        left = content[: match.start(1)].rstrip()
        word_match = _WEAK_DIGIT_LEFT_WORD_RE.search(left)
        if not word_match:
            continue
        left_word = word_match.group(1).lower()
        if len(left_word) < 2 or left_word in _BARE_DIGIT_STRUCTURAL_PREFIX:
            continue
        right = content[match.end(1):]
        right_stripped = right.lstrip()
        if right_stripped and right_stripped[0].isdigit():
            continue
        matches.append({
            "marker": marker,
            "start": match.start(1),
            "end": match.end(1),
            "matched_text": match.group(0),
            "source_text": content[max(0, match.start(1)-30):min(len(content), match.end(1)+30)],
        })
    return matches


def _scan_expected_gap_symbols(text: str, expected_markers: set[str]) -> list[dict]:
    if not expected_markers:
        return []
    content = str(text or "")
    matches: list[dict] = []
    for match in _WEAK_EXPECTED_SYMBOL_RE.finditer(content):
        symbol = match.group(1)
        if symbol not in expected_markers:
            continue
        matches.append({
            "marker": symbol,
            "start": match.start(1),
            "end": match.end(1),
            "matched_text": match.group(0),
            "source_text": content[max(0, match.start(1)-30):min(len(content), match.end(1)+30)],
        })
    return matches


def _within_sequence_page_window(
    page_no: int,
    marker: int,
    known_pages_by_marker: dict[int, list[int]],
) -> bool:
    if page_no <= 0 or not known_pages_by_marker:
        return False
    lower_markers = [value for value in known_pages_by_marker if value < marker]
    upper_markers = [value for value in known_pages_by_marker if value > marker]
    lower_pages = (
        known_pages_by_marker[max(lower_markers)] if lower_markers else []
    )
    upper_pages = (
        known_pages_by_marker[min(upper_markers)] if upper_markers else []
    )
    min_page = min((lower_pages or [page_no]) + (upper_pages or [page_no]))
    max_page = max((lower_pages or [page_no]) + (upper_pages or [page_no]))
    padding = 2 if (max_page - min_page) >= 5 else 1
    return max(1, min_page - padding) <= page_no <= max_page + padding


def _known_endnote_marker_pages(
    anchors: list[BodyAnchorRecord],
    chapter_endnote_markers: dict[str, set[int]],
) -> dict[str, dict[int, list[int]]]:
    by_chapter: dict[str, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    for anchor in anchors:
        if anchor.anchor_kind != "endnote":
            continue
        cid = str(anchor.chapter_id or "")
        if not cid:
            continue
        try:
            marker = int(anchor.normalized_marker)
        except (ValueError, TypeError):
            continue
        if cid in chapter_endnote_markers and marker not in chapter_endnote_markers[cid]:
            continue
        by_chapter[cid][marker].add(int(anchor.page_no))
    return {cid: {marker: sorted(pages) for marker, pages in rows.items()} for cid, rows in by_chapter.items()}


def _recover_expected_gap_bare_digit_anchors(
    anchors: list[BodyAnchorRecord],
    *,
    phase2: Phase2Structure,
    page_by_no: dict[int, dict],
    page_role_by_no: dict[int, str],
    footnote_band_pages: set[tuple[str, int]],
    chapter_endnote_markers: dict[str, set[int]],
    seen: set[tuple[str, str, str, int]],
    anchor_counter: int,
) -> tuple[list[BodyAnchorRecord], int]:
    confirmed_markers: dict[str, set[int]] = defaultdict(set)
    for anchor in anchors:
        if anchor.anchor_kind != "endnote":
            continue
        try:
            marker = int(anchor.normalized_marker)
        except (ValueError, TypeError):
            continue
        confirmed_markers[anchor.chapter_id].add(marker)

    known_pages = _known_endnote_marker_pages(anchors, chapter_endnote_markers)

    # 从 region 获取 note_kind（NoteItemRecord 无 note_kind 字段）
    _region_kind_by_id: dict[str, str] = {
        str(r.region_id or ""): str(r.note_kind or "")
        for r in (phase2.note_regions or [])
    }
    gap_anchors: list[BodyAnchorRecord] = []
    for item in phase2.note_items:
        _item_kind = _region_kind_by_id.get(str(getattr(item, "region_id", "") or ""), "")
        if _item_kind != "endnote":
            continue
        chapter_id = str(item.chapter_id or "")
        if not chapter_id:
            continue
        try:
            marker = int(item.marker)
        except (ValueError, TypeError):
            continue
        if marker in confirmed_markers.get(chapter_id, set()):
            continue
        known = known_pages.get(chapter_id, {})
        candidate_pages: set[int] = set()
        for page_no, page_data in page_by_no.items():
            if _within_sequence_page_window(
                page_no, marker,
                known_pages_by_marker=known,
            ):
                text = str(page_data.get("markdown") or "")
                if not text.strip():
                    continue
                candidate_pages.add(page_no)

        found_any = False
        for page_no in sorted(candidate_pages)[:5]:
            text = str(page_by_no[page_no].get("markdown") or "")
            hits = _scan_expected_gap_bare_digits(text, {marker})
            count_by_marker: dict[tuple[str, int], int] = defaultdict(int)
            for hit in hits:
                count_by_marker[(chapter_id, hit["marker"])] += 1
            for hit in hits:
                mk = hit["marker"]
                if count_by_marker[(chapter_id, mk)] != 1:
                    continue
                anchor_counter += 1
                anchor_id = f"gap-bare-{anchor_counter:05d}"
                key = ("bare_digit", str(mk), chapter_id, page_no)
                if key in seen:
                    continue
                seen.add(key)
                gap_anchors.append(
                    BodyAnchorRecord(
                        anchor_id=anchor_id,
                        chapter_id=chapter_id,
                        page_no=page_no,
                        paragraph_index=0,
                        char_start=hit["start"],
                        char_end=hit["end"],
                        source_marker=str(mk),
                        normalized_marker=str(mk),
                        anchor_kind="endnote",
                        certainty=0.72,
                        source_text=hit["source_text"],
                        source="markdown:bare_digit",
                        synthetic=True,
                        ocr_repaired_from_marker="",
                    )
                )
                found_any = True
                break
            if found_any:
                break
    return anchors + gap_anchors, anchor_counter


def _recover_expected_gap_symbol_anchors(
    anchors: list[BodyAnchorRecord],
    *,
    phase2: Phase2Structure,
    page_by_no: dict[int, dict],
    page_role_by_no: dict[int, str],
    footnote_band_pages: set[tuple[str, int]],
    chapter_endnote_markers: dict[str, set[int]],
    chapter_endnote_text_by_marker: dict[str, dict[int, str]],
    seen: set[tuple[str, str, str, int]],
    anchor_counter: int,
) -> tuple[list[BodyAnchorRecord], int]:
    confirmed_markers: dict[str, set[str]] = defaultdict(set)
    for anchor in anchors:
        if anchor.anchor_kind != "endnote":
            continue
        try:
            int(anchor.normalized_marker)
            continue
        except (ValueError, TypeError):
            pass
        confirmed_markers[anchor.chapter_id].add(anchor.normalized_marker)

    known_pages = _known_endnote_marker_pages(anchors, chapter_endnote_markers)

    # 从 region 获取 note_kind（NoteItemRecord 无 note_kind 字段）
    _region_kind_by_id: dict[str, str] = {
        str(r.region_id or ""): str(r.note_kind or "")
        for r in (phase2.note_regions or [])
    }
    gap_anchors: list[BodyAnchorRecord] = []
    for item in phase2.note_items:
        _item_kind = _region_kind_by_id.get(str(getattr(item, "region_id", "") or ""), "")
        if _item_kind != "endnote":
            continue
        chapter_id = str(item.chapter_id or "")
        if not chapter_id:
            continue
        marker_str = str(item.marker or "")
        if not marker_str or marker_str.isdigit():
            continue
        if marker_str in confirmed_markers.get(chapter_id, set()):
            continue
        known = known_pages.get(chapter_id, {})
        for page_no, page_data in page_by_no.items():
            text = str(page_data.get("markdown") or "")
            if not text.strip():
                continue
            hits = _scan_expected_gap_symbols(text, {marker_str})
            for hit in hits:
                anchor_counter += 1
                anchor_id = f"gap-sym-{anchor_counter:05d}"
                key = ("symbol", marker_str, chapter_id, page_no)
                if key in seen:
                    continue
                seen.add(key)
                gap_anchors.append(
                    BodyAnchorRecord(
                        anchor_id=anchor_id,
                        chapter_id=chapter_id,
                        page_no=page_no,
                        paragraph_index=0,
                        char_start=hit["start"],
                        char_end=hit["end"],
                        source_marker=marker_str,
                        normalized_marker=marker_str,
                        anchor_kind="endnote",
                        certainty=0.72,
                        source_text=hit["source_text"],
                        source="markdown:symbol_gap",
                        synthetic=True,
                        ocr_repaired_from_marker="",
                    )
                )
                break
    return anchors + gap_anchors, anchor_counter


def build_body_anchors(
    phase2: Phase2Structure,
    *,
    pages: list[dict],
    pdf_path: str = "",
) -> tuple[list[BodyAnchorRecord], dict]:
    page_by_no = _page_payload_by_no(pages)
    page_role_by_no = {
        int(row.page_no): str(row.page_role)
        for row in phase2.pages
        if int(row.page_no) > 0
    }
    footnote_band_pages = _footnote_band_page_keys(phase2)
    chapter_marker_range = _build_chapter_marker_range(phase2)
    chapter_endnote_markers = _build_chapter_endnote_marker_set(phase2)
    chapter_endnote_text_by_marker = _build_chapter_endnote_text_by_marker(phase2)
    chapter_note_items = _build_chapter_note_items_set(phase2)

    anchors: list[BodyAnchorRecord] = []
    seen: set[tuple[str, str, str, int]] = set()
    anchor_counter = 0
    year_like_filtered_total = 0

    # 扫描所有页面（不限定 page_role）：尾注页/过渡页中可能混有正文内容，
    # 且 _positive_gate_bare_digit 后续会统一过滤假阳性。
    for page_no in sorted(page_by_no.keys()):
        page_data = page_by_no[page_no]
        text = str(page_data.get("markdown") or "")
        if not text.strip():
            continue
        chapter_id = _chapter_id_for_page(phase2, page_no)
        marker_min, marker_max = chapter_marker_range.get(chapter_id, (0, 0))
        is_footnote_page = (chapter_id, page_no) in footnote_band_pages

        refs, year_like_filtered = scan_anchor_markers(text)
        year_like_filtered_total += year_like_filtered

        for ref in refs:
            pattern = str(ref.get("pattern") or "")
            marker = str(ref.get("normalized_marker") or "")
            if not marker:
                continue
            if not _marker_in_expected_range(
                marker,
                pattern=pattern,
                marker_min=marker_min,
                marker_max=marker_max,
                has_page_footnote_band=is_footnote_page,
            ):
                continue
            key = (pattern, marker, chapter_id, page_no)
            if key in seen:
                continue
            seen.add(key)
            anchor_counter += 1
            anchor_id = f"anchor-{anchor_counter:05d}"
            anchor_kind = resolve_anchor_kind(
                normalized_marker=marker,
                pattern=pattern,
                has_page_footnote_band=is_footnote_page,
                chapter_endnote_markers=chapter_endnote_markers.get(chapter_id),
            )
            anchors.append(
                BodyAnchorRecord(
                    anchor_id=anchor_id,
                    chapter_id=chapter_id,
                    page_no=page_no,
                    paragraph_index=int(ref.get("paragraph_index") or 0),
                    char_start=int(ref.get("char_start") or 0),
                    char_end=int(ref.get("char_end") or 0),
                    source_marker=str(ref.get("source_marker") or marker),
                    normalized_marker=marker,
                    anchor_kind=anchor_kind,
                    certainty=float(ref.get("certainty") or 0.85),
                    source_text=str(ref.get("source_text") or ""),
                    source=f"{ref.get('source', 'markdown')}:{pattern}",
                    synthetic=False,
                    ocr_repaired_from_marker=str(ref.get("ocr_repaired_from_marker") or ""),
                )
            )

    anchors, llm_verified = _positive_gate_bare_digit(
        anchors, chapter_note_items=chapter_note_items,
        pdf_path=pdf_path, pages=pages,
    )
    anchors, anchor_counter = _recover_expected_gap_bare_digit_anchors(
        anchors,
        phase2=phase2,
        page_by_no=page_by_no,
        page_role_by_no=page_role_by_no,
        footnote_band_pages=footnote_band_pages,
        chapter_endnote_markers=chapter_endnote_markers,
        seen=seen,
        anchor_counter=anchor_counter,
    )
    anchors, anchor_counter = _recover_expected_gap_symbol_anchors(
        anchors,
        phase2=phase2,
        page_by_no=page_by_no,
        page_role_by_no=page_role_by_no,
        footnote_band_pages=footnote_band_pages,
        chapter_endnote_markers=chapter_endnote_markers,
        chapter_endnote_text_by_marker=chapter_endnote_text_by_marker,
        seen=seen,
        anchor_counter=anchor_counter,
    )
    summary = _build_summary(anchors, year_like_filtered_count=year_like_filtered_total)
    summary["llm_bare_digit_verified"] = len(llm_verified)
    return anchors, summary

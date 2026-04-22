"""Markdown 导出里的脚注、尾注与章节映射 helper。"""

from difflib import SequenceMatcher
import re
import unicodedata

from document.text_processing import normalize_footnote_markers_for_obsidian


_FN_LINE_NUM_RE = re.compile(r"^\s*(\d{1,4})\s*[\.\)、\]]\s*(.+?)\s*$")
_FN_LINE_BRACKET_RE = re.compile(r"^\s*\[(\d{1,4})\]\s*(.+?)\s*$")
_FN_LINE_LOOSE_RE = re.compile(r"^\s*(\d{1,4})\s{1,3}(\S.+?)\s*$")
_NOTES_HEADER_RE = re.compile(r"^\s*(?:notes?|注释|脚注|尾注)\s*$", re.IGNORECASE)
_BACKMATTER_TITLE_RE = re.compile(r"\b(?:notes?|index)\b|注释|尾注|索引|indices", re.IGNORECASE)
_CONTAINER_TITLE_RE = re.compile(r"^(?:cours|course|courses|lectures?|part|section|volume|book)\b", re.IGNORECASE)
_CONTENT_TITLE_RE = re.compile(
    r"^(?:\d+[\.\s]|chapter\b|introduction\b|epilogue\b|afterword\b|appendix\b|preface\b|conclusion\b|le[cç]on\b|lesson\b)",
    re.IGNORECASE,
)
_ENDNOTE_PAGE_MIN_RATIO = 0.5
_ENDNOTE_PAGE_MIN_ENTRIES = 3


from document.text_utils import ensure_str  # 统一定义在 text_utils.py


def _nonempty_markdown_lines(text) -> list[str]:
    return [line.strip() for line in ensure_str(text).split("\n") if line.strip()]


def _append_blockquote(md_lines: list[str], text) -> None:
    lines = _nonempty_markdown_lines(text)
    if not lines:
        return
    for line in lines:
        md_lines.append(f"> {line}")
    md_lines.append("")


def _append_paragraph(md_lines: list[str], text) -> None:
    content = ensure_str(text).strip()
    if not content:
        return
    md_lines.append(content)
    md_lines.append("")


def _append_labeled_block(md_lines: list[str], label: str, text) -> None:
    lines = _nonempty_markdown_lines(text)
    if not lines:
        return
    md_lines.append(f"[{label}] {lines[0]}")
    for line in lines[1:]:
        md_lines.append(line)
    md_lines.append("")


def _normalize_footnote_markers(text: str) -> str:
    return normalize_footnote_markers_for_obsidian(ensure_str(text))


def _extract_marked_footnote_labels(text: str) -> list[str]:
    normalized = _normalize_footnote_markers(text)
    labels = []
    seen = set()
    for match in re.finditer(r"\[\^([A-Za-z0-9_-]+)\]", normalized):
        label = match.group(1)
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def _split_footnote_items(text: str, strict: bool = True) -> list[tuple[str | None, str]]:
    """将脚注/尾注文本拆分为 (label, content) 列表。"""
    lines = [line.strip() for line in ensure_str(text).split("\n") if line.strip()]
    if not lines:
        return []
    items: list[tuple[str | None, str]] = []
    for line in lines:
        match_num = _FN_LINE_NUM_RE.match(line)
        if match_num:
            items.append((match_num.group(1), match_num.group(2).strip()))
            continue
        match_bracket = _FN_LINE_BRACKET_RE.match(line)
        if match_bracket:
            items.append((match_bracket.group(1), match_bracket.group(2).strip()))
            continue
        if not strict:
            match_loose = _FN_LINE_LOOSE_RE.match(line)
            if match_loose:
                items.append((match_loose.group(1), match_loose.group(2).strip()))
                continue
        items.append((None, line))
    return items


def _classify_note_scope(
    label: str,
    content: str,
    inline_labels: list[str],
    source_bp: int,
    chapter_end_bp: int | None,
    doc_last_bp: int,
    had_explicit_label: bool,
) -> tuple[str, str]:
    if label in set(inline_labels):
        return "footnote", "paragraph_or_page"
    if not had_explicit_label:
        return "footnote", "paragraph_or_page"

    is_numeric_label = str(label).isdigit()
    looks_long_note = len(ensure_str(content)) >= 220
    if is_numeric_label and looks_long_note:
        if chapter_end_bp is not None and source_bp >= max(1, int(chapter_end_bp) - 1):
            return "endnote", "chapter_end"
        if source_bp >= max(1, int(doc_last_bp) - 1):
            return "endnote", "book_end"
    return "footnote", "paragraph_or_page"


def _build_obsidian_footnote_defs(
    footnotes,
    footnotes_translation,
    existing_labels: list[str],
    preferred_labels: list[str] | None,
    source_bp: int,
    segment_idx: int,
    chapter_index: int | None,
    chapter_end_bp: int | None,
    doc_last_bp: int,
    fallback_prefix: str,
) -> tuple[list[dict], list[str], list[tuple[str, str]]]:
    items_fn = _split_footnote_items(footnotes)
    items_tr = _split_footnote_items(footnotes_translation)
    defs: list[dict] = []
    fallback_blocks: list[tuple[str, str]] = []
    labels_for_refs: list[str] = []

    count = max(len(items_fn), len(items_tr))
    if count == 0:
        return defs, labels_for_refs, fallback_blocks

    existing_set = set(existing_labels)
    preferred = [label for label in (preferred_labels or []) if label and label not in existing_set]
    preferred_idx = 0
    for idx in range(count):
        fn_label = items_fn[idx][0] if idx < len(items_fn) else None
        fn_content = items_fn[idx][1] if idx < len(items_fn) else ""
        tr_label = items_tr[idx][0] if idx < len(items_tr) else None
        tr_content = items_tr[idx][1] if idx < len(items_tr) else ""
        label = fn_label or tr_label
        if not label:
            if preferred_idx < len(preferred):
                label = preferred[preferred_idx]
                preferred_idx += 1
            else:
                if fn_content:
                    fallback_blocks.append(("脚注", fn_content))
                if tr_content:
                    fallback_blocks.append(("脚注翻译", tr_content))
                continue
        label = re.sub(r"[^A-Za-z0-9_-]", "-", str(label)).strip("-") or f"{fallback_prefix}-{idx + 1}"
        if label in existing_set:
            label = f"{label}-{fallback_prefix}"
        existing_set.add(label)
        labels_for_refs.append(label)

        merged = []
        if fn_content:
            merged.append(fn_content)
        if tr_content:
            merged.append(f"译：{tr_content}")
        merged_text = "\n".join(merged).strip()
        if merged_text:
            note_type, note_scope = _classify_note_scope(
                label=label,
                content=merged_text,
                inline_labels=preferred_labels or [],
                source_bp=source_bp,
                chapter_end_bp=chapter_end_bp,
                doc_last_bp=doc_last_bp,
                had_explicit_label=bool(fn_label or tr_label),
            )
            defs.append({
                "label": label,
                "content": merged_text,
                "source_bp": int(source_bp),
                "segment_idx": int(segment_idx),
                "chapter_index": chapter_index,
                "note_type": note_type,
                "note_scope": note_scope,
            })
        else:
            if ensure_str(footnotes).strip():
                fallback_blocks.append(("脚注", ensure_str(footnotes)))
            if ensure_str(footnotes_translation).strip():
                fallback_blocks.append(("脚注翻译", ensure_str(footnotes_translation)))
    return defs, labels_for_refs, fallback_blocks


def _extract_heading_number(text: str) -> int | None:
    match = re.match(r"^\s*(\d{1,4})\b", ensure_str(text))
    return int(match.group(1)) if match else None


def _looks_like_backmatter_title(title: str) -> bool:
    return bool(_BACKMATTER_TITLE_RE.search(ensure_str(title).strip()))


def _looks_like_container_title(title: str) -> bool:
    return bool(_CONTAINER_TITLE_RE.search(ensure_str(title).strip()))


def _looks_like_content_title(title: str) -> bool:
    return bool(_CONTENT_TITLE_RE.search(ensure_str(title).strip()))


def _collect_entry_lines(entry: dict, field: str) -> list[str]:
    lines: list[str] = []
    page_entries = entry.get("_page_entries") or []
    if page_entries:
        for page_entry in page_entries:
            raw = ensure_str(page_entry.get(field, "")).strip()
            if raw:
                lines.extend(line.strip() for line in raw.split("\n") if line.strip())
    else:
        raw = ensure_str(entry.get(field, "")).strip()
        if raw:
            lines.extend(line.strip() for line in raw.split("\n") if line.strip())
    return lines


def _extract_note_candidate_lines(lines: list[str]) -> list[str]:
    for idx, line in enumerate(lines):
        if _NOTES_HEADER_RE.match(line):
            return [item.strip() for item in lines[idx + 1:] if item.strip()]
    return [item.strip() for item in lines if item.strip()]


def _split_consecutive_bps(bps: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    current: list[int] = []
    for bp in sorted(int(value) for value in bps):
        if current and bp != current[-1] + 1:
            runs.append(current)
            current = [bp]
        else:
            current.append(bp)
    if current:
        runs.append(current)
    return runs


def _build_chapter_ranges_from_depth_map(
    toc_depth_map: dict[int, int],
    all_bps: list[int],
    toc_title_map: dict[int, str] | None = None,
) -> list[dict]:
    bps = sorted(int(bp) for bp in all_bps if bp is not None)
    if not bps:
        return []
    toc_items = sorted(
        (
            {
                "start_bp": int(bp),
                "depth": int(depth),
                "title": ensure_str((toc_title_map or {}).get(int(bp), "")).strip(),
            }
            for bp, depth in (toc_depth_map or {}).items()
            if int(bp) > 0
        ),
        key=lambda item: (int(item["start_bp"]), int(item["depth"])),
    )
    if not toc_items:
        return []
    min_depth = min(item["depth"] for item in toc_items)
    top_items = [item for item in toc_items if item["depth"] == min_depth]
    if not top_items:
        return []

    effective_items: list[dict] = []
    for idx, item in enumerate(top_items):
        section_start = int(item["start_bp"])
        section_end = int(top_items[idx + 1]["start_bp"]) - 1 if idx + 1 < len(top_items) else bps[-1]
        child_items = [
            candidate for candidate in toc_items
            if section_start < int(candidate["start_bp"]) <= section_end
            and int(candidate["depth"]) == min_depth + 1
        ]
        should_promote_children = (
            len(child_items) >= 3
            and (section_end - section_start + 1) >= 40
            and (_looks_like_container_title(item["title"]) or not _looks_like_content_title(item["title"]))
        )
        if should_promote_children:
            effective_items.extend(child_items)
        else:
            effective_items.append(item)

    effective_items = sorted(
        {int(item["start_bp"]): item for item in effective_items if int(item["start_bp"]) > 0}.values(),
        key=lambda item: int(item["start_bp"]),
    )
    ranges = []
    for idx, item in enumerate(effective_items):
        start_bp = int(item["start_bp"])
        end_bp = int(effective_items[idx + 1]["start_bp"]) - 1 if idx + 1 < len(effective_items) else bps[-1]
        ranges.append({
            "index": idx,
            "start_bp": start_bp,
            "end_bp": int(end_bp),
            "title": item["title"],
            "depth": int(item["depth"]),
        })
    return ranges


def _resolve_chapter_for_bp(chapter_ranges: list[dict], bp: int) -> dict | None:
    for chapter in chapter_ranges:
        if int(chapter["start_bp"]) <= int(bp) <= int(chapter["end_bp"]):
            return chapter
    return None


def _resolve_previous_content_chapter(chapter_ranges: list[dict], bp: int) -> dict | None:
    candidate = None
    for chapter in chapter_ranges:
        if int(chapter["start_bp"]) > int(bp):
            break
        if _looks_like_backmatter_title(chapter.get("title", "")):
            continue
        candidate = chapter
    return candidate


def detect_endnote_collection_pages(
    entries: list[dict],
    chapter_ranges: list[dict],
) -> dict[int | None, list[int]]:
    """检测正文中的尾注集合页，返回 {chapter_index: [bp, ...]}。"""
    result: dict[int | None, list[int]] = {}
    stats_by_bp: dict[int, dict] = {}
    for entry in entries or []:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp <= 0:
            continue
        raw_lines = _collect_entry_lines(entry, "original")
        all_orig = "\n".join(raw_lines).strip()
        if not all_orig:
            continue
        lines = [line.strip() for line in all_orig.split("\n") if line.strip()]
        numbered = sum(
            1 for line in lines
            if _FN_LINE_NUM_RE.match(line)
            or _FN_LINE_BRACKET_RE.match(line)
            or _FN_LINE_LOOSE_RE.match(line)
        )
        chapter = _resolve_chapter_for_bp(chapter_ranges, bp)
        chapter_index = int(chapter["index"]) if chapter else None
        ratio = numbered / max(len(lines), 1)
        has_notes_signal = any(
            _NOTES_HEADER_RE.match(line)
            or re.match(r"^\s*(?:notes?|注释|脚注|尾注)\b", line, re.IGNORECASE)
            for line in lines
        )
        chapter_end_bp = int(chapter["end_bp"]) if chapter else None
        near_chapter_end = bool(chapter_end_bp is not None and bp >= max(1, chapter_end_bp - 1))
        stats_by_bp[bp] = {
            "chapter_index": chapter_index,
            "chapter_end_bp": chapter_end_bp,
            "numbered": numbered,
            "ratio": ratio,
            "has_notes_signal": has_notes_signal,
            "near_chapter_end": near_chapter_end,
        }

    for bp, stats in stats_by_bp.items():
        if stats["numbered"] >= _ENDNOTE_PAGE_MIN_ENTRIES and stats["ratio"] >= _ENDNOTE_PAGE_MIN_RATIO:
            result.setdefault(stats["chapter_index"], []).append(bp)

    for bp, stats in stats_by_bp.items():
        chapter_index = stats["chapter_index"]
        if chapter_index is None:
            continue
        current = result.setdefault(chapter_index, [])
        if bp in current:
            continue
        if stats["near_chapter_end"] and stats["numbered"] >= 2 and (
            stats["ratio"] >= 0.34 or stats["has_notes_signal"]
        ):
            current.append(bp)

    for bp, stats in stats_by_bp.items():
        chapter_index = stats["chapter_index"]
        current = result.setdefault(chapter_index, [])
        if bp in current:
            continue
        if stats["numbered"] < 1 or not stats["has_notes_signal"]:
            continue
        if any(abs(bp - hit_bp) <= 1 for hit_bp in current):
            current.append(bp)

    for bp, stats in stats_by_bp.items():
        chapter_index = stats["chapter_index"]
        if chapter_index is None:
            continue
        current = result.setdefault(chapter_index, [])
        if bp in current:
            continue
        if stats["numbered"] < 2:
            continue
        if stats["ratio"] < 0.28:
            continue
        if any(abs(bp - hit_bp) <= 1 for hit_bp in current):
            current.append(bp)

    for chapter_index in list(result.keys()):
        cleaned_bps = sorted(set(result[chapter_index]))
        filtered_runs: list[int] = []
        for run in _split_consecutive_bps(cleaned_bps):
            if len(run) == 1:
                stats = stats_by_bp.get(int(run[0]), {})
                if not stats.get("has_notes_signal") and not stats.get("near_chapter_end"):
                    continue
            filtered_runs.extend(run)
        result[chapter_index] = filtered_runs
        if not result[chapter_index]:
            result.pop(chapter_index, None)
    return result


def _match_chapter_heading_line(line: str, chapter_ranges: list[dict]) -> dict | None:
    raw = ensure_str(line).strip()
    if not raw or _NOTES_HEADER_RE.match(raw):
        return None
    normalized_line = _normalize_heading_text_for_match(raw)
    if not normalized_line:
        return None
    best_match = None
    best_score = 0.0
    for chapter in chapter_ranges or []:
        title = ensure_str(chapter.get("title", "")).strip()
        if not title or _looks_like_backmatter_title(title):
            continue
        normalized_title = _normalize_heading_text_for_match(title)
        if not normalized_title:
            continue
        if normalized_line == normalized_title:
            score = 1.0
        elif normalized_line in normalized_title or normalized_title in normalized_line:
            score = min(len(normalized_line), len(normalized_title)) / max(len(normalized_line), len(normalized_title), 1)
        else:
            score = SequenceMatcher(None, normalized_line, normalized_title).ratio()
        if score > best_score:
            best_score = score
            best_match = chapter
    if best_score >= 0.84:
        return best_match
    return None


def _merge_numbered_note_items(raw_items: list[tuple[str | None, str]]) -> tuple[list[int], dict[int, str]]:
    ordered_numbers: list[int] = []
    merged: dict[int, str] = {}
    current_num: int | None = None
    current_parts: list[str] = []

    def _repair_number(parsed_num: int, expected_num: int, content: str) -> int | None:
        text = ensure_str(content).strip()
        if parsed_num == expected_num:
            return parsed_num
        if parsed_num < expected_num and len(text) >= 8:
            return expected_num
        if parsed_num >= 1000:
            return None
        if (
            parsed_num > expected_num
            and len(text) >= 8
            and len(str(parsed_num)) == len(str(expected_num))
            and str(parsed_num)[0] == str(expected_num)[0]
            and str(parsed_num)[-1] == str(expected_num)[-1]
        ):
            return expected_num
        return parsed_num

    def _flush_current() -> None:
        nonlocal current_num, current_parts
        if current_num is None:
            return
        text = " ".join(part for part in current_parts if part).strip()
        if current_num not in ordered_numbers:
            ordered_numbers.append(current_num)
        if text:
            existing = merged.get(current_num, "").strip()
            merged[current_num] = f"{existing} {text}".strip() if existing else text
        else:
            merged.setdefault(current_num, "")

    for label, content in raw_items:
        if label is not None and str(label).isdigit():
            parsed_num = int(label)
            if current_num is not None:
                repaired_num = _repair_number(parsed_num, current_num + 1, content)
                if repaired_num is None:
                    if content:
                        current_parts.append(content)
                    continue
                parsed_num = repaired_num
            _flush_current()
            current_num = parsed_num
            current_parts = [content] if content else []
            continue
        if current_num is not None and content:
            current_parts.append(content)
    _flush_current()
    return ordered_numbers, merged


def _resolve_endnote_run_default_chapter(run_pages: list[dict], chapter_ranges: list[dict]) -> dict | None:
    if not run_pages:
        return None
    default_chapter = _resolve_previous_content_chapter(chapter_ranges, int(run_pages[0]["bp"]))
    if default_chapter is None:
        default_chapter = _resolve_chapter_for_bp(chapter_ranges, int(run_pages[0]["bp"]))
        if default_chapter and _looks_like_backmatter_title(default_chapter.get("title", "")):
            default_chapter = _resolve_previous_content_chapter(chapter_ranges, int(run_pages[0]["bp"]))
    return default_chapter


def _new_endnote_section(chapter: dict | None) -> dict:
    return {
        "chapter_index": int(chapter["index"]) if chapter and chapter.get("index") is not None else None,
        "chapter_title": ensure_str(chapter.get("title", "")).strip() if chapter else "",
        "chapter_start_bp": int(chapter["start_bp"]) if chapter and chapter.get("start_bp") is not None else None,
        "heading_number": _extract_heading_number(chapter.get("title", "")) if chapter else None,
        "orig_lines": [],
    }


def _split_endnote_run_pages_into_sections(
    run_pages: list[dict],
    chapter_ranges: list[dict],
    line_key: str,
    forced_chapter: dict | None = None,
) -> list[dict]:
    if not run_pages:
        return []
    default_chapter = forced_chapter or _resolve_endnote_run_default_chapter(run_pages, chapter_ranges)
    allow_heading_split = forced_chapter is None
    sections: list[dict] = [_new_endnote_section(default_chapter)]
    for page in run_pages:
        page_lines = _extract_note_candidate_lines(page.get(line_key) or [])
        for line in page_lines:
            matched_chapter = _match_chapter_heading_line(line, chapter_ranges) if allow_heading_split else None
            if matched_chapter is not None:
                current = sections[-1]
                matched_index = int(matched_chapter["index"])
                if current["orig_lines"] or current["chapter_index"] != matched_index:
                    sections.append(_new_endnote_section(matched_chapter))
                else:
                    current["chapter_index"] = matched_index
                    current["chapter_title"] = ensure_str(matched_chapter.get("title", "")).strip()
                    current["chapter_start_bp"] = int(matched_chapter["start_bp"])
                    current["heading_number"] = _extract_heading_number(matched_chapter.get("title", ""))
                continue
            sections[-1]["orig_lines"].append(line)
    return sections


def _prepare_endnote_sections(raw_sections: list[dict]) -> list[dict]:
    prepared_sections: list[dict] = []
    for section in raw_sections:
        orig_order, orig_map = _merge_numbered_note_items(
            _split_footnote_items("\n".join(section["orig_lines"]), strict=False)
        )
        if not orig_order and not orig_map:
            continue
        prepared_sections.append({
            **section,
            "note_numbers": orig_order,
            "orig_map": orig_map,
        })
    return prepared_sections


def _merge_pdf_endnote_sections(prepared_sections: list[dict], pdf_sections: list[dict]) -> list[dict]:
    if not pdf_sections:
        return prepared_sections

    def _should_accept_pdf_number(number: int, existing_numbers: list[int]) -> bool:
        if not existing_numbers:
            return True
        if number in set(existing_numbers):
            return False
        first = existing_numbers[0]
        last = existing_numbers[-1]
        if number < first:
            return number >= max(1, first - 2)
        if number > last:
            return number <= last + 2
        for left, right in zip(existing_numbers, existing_numbers[1:]):
            if left < number < right:
                return (right - left) >= 2
        return False

    def _find_target(pdf_section: dict, section_idx: int) -> dict | None:
        chapter_index = pdf_section.get("chapter_index")
        if chapter_index is not None:
            same_chapter = [
                section for section in prepared_sections
                if section.get("chapter_index") == chapter_index
            ]
            if len(same_chapter) == 1:
                return same_chapter[0]
            if same_chapter:
                return same_chapter[0]
        if 0 <= section_idx < len(prepared_sections):
            return prepared_sections[section_idx]
        return None

    for section_idx, pdf_section in enumerate(pdf_sections):
        target = _find_target(pdf_section, section_idx)
        if target is None:
            target = {
                "chapter_index": pdf_section.get("chapter_index"),
                "chapter_title": pdf_section.get("chapter_title", ""),
                "chapter_start_bp": pdf_section.get("chapter_start_bp"),
                "heading_number": pdf_section.get("heading_number"),
                "orig_lines": [],
                "note_numbers": [],
                "orig_map": {},
                "tr_map": {},
            }
            prepared_sections.append(target)
        if not target.get("chapter_title") and pdf_section.get("chapter_title"):
            target["chapter_title"] = pdf_section["chapter_title"]
        if target.get("chapter_start_bp") is None and pdf_section.get("chapter_start_bp") is not None:
            target["chapter_start_bp"] = pdf_section["chapter_start_bp"]
        merged_numbers = {int(value) for value in target.get("note_numbers", [])}
        existing_numbers = sorted(merged_numbers)
        target_orig_map = target.setdefault("orig_map", {})
        for number, content in (pdf_section.get("orig_map") or {}).items():
            if not ensure_str(content).strip():
                continue
            if not _should_accept_pdf_number(int(number), existing_numbers):
                continue
            if not ensure_str(target_orig_map.get(number, "")).strip():
                target_orig_map[int(number)] = content
            merged_numbers.add(int(number))
            existing_numbers = sorted(merged_numbers)
        target["note_numbers"] = sorted(merged_numbers)
    prepared_sections.sort(
        key=lambda section: (
            section.get("chapter_index") is None,
            int(section.get("chapter_start_bp") or 10**9),
            ensure_str(section.get("chapter_title", "")),
        )
    )
    return prepared_sections


def _clone_endnote_section(section: dict) -> dict:
    return {
        "chapter_index": section.get("chapter_index"),
        "chapter_title": section.get("chapter_title", ""),
        "chapter_start_bp": section.get("chapter_start_bp"),
        "heading_number": section.get("heading_number"),
        "orig_lines": list(section.get("orig_lines") or []),
        "note_numbers": list(section.get("note_numbers") or []),
        "orig_map": dict(section.get("orig_map") or {}),
        "tr_map": dict(section.get("tr_map") or {}),
    }


def _endnote_section_score(section: dict | None) -> float:
    if not section:
        return float("-inf")
    note_numbers = [int(value) for value in (section.get("note_numbers") or [])]
    if not note_numbers:
        return float("-inf")
    uniq = sorted(set(note_numbers))
    span = max(uniq[-1] - uniq[0] + 1, 1)
    density = len(uniq) / span
    start_penalty = min(max(uniq[0] - 1, 0), 8) * 0.08
    order_resets = sum(
        1 for prev, cur in zip(note_numbers, note_numbers[1:])
        if int(cur) < int(prev)
    )
    return density - start_penalty - (order_resets * 0.2)


def _should_prefer_pdf_section(ocr_section: dict | None, pdf_section: dict | None) -> bool:
    if not pdf_section:
        return False
    if not ocr_section:
        return True
    return _endnote_section_score(pdf_section) >= (_endnote_section_score(ocr_section) - 0.05)


def _select_base_endnote_sections(ocr_sections: list[dict], pdf_sections: list[dict]) -> list[dict]:
    selected_sections: list[dict] = []
    max_len = max(len(ocr_sections), len(pdf_sections))
    for idx in range(max_len):
        ocr_section = ocr_sections[idx] if idx < len(ocr_sections) else None
        pdf_section = pdf_sections[idx] if idx < len(pdf_sections) else None
        supplement_section = None
        if ocr_section and pdf_section and ocr_section.get("chapter_index") != pdf_section.get("chapter_index"):
            if _endnote_section_score(pdf_section) > _endnote_section_score(ocr_section):
                selected_sections.append(_clone_endnote_section(ocr_section))
                base_section = _clone_endnote_section(pdf_section)
            else:
                selected_sections.append(_clone_endnote_section(pdf_section))
                base_section = _clone_endnote_section(ocr_section)
            supplement_section = None
        elif _should_prefer_pdf_section(ocr_section, pdf_section):
            if ocr_section and pdf_section and ocr_section.get("chapter_index") == pdf_section.get("chapter_index"):
                supplement_section = _clone_endnote_section(ocr_section)
            base_section = _clone_endnote_section(pdf_section)
        else:
            if ocr_section and pdf_section and ocr_section.get("chapter_index") == pdf_section.get("chapter_index"):
                supplement_section = _clone_endnote_section(pdf_section)
            base_section = _clone_endnote_section(ocr_section)

        if supplement_section is not None:
            selected_sections.extend(_merge_pdf_endnote_sections([base_section], [supplement_section]))
        else:
            selected_sections.append(base_section)
    return selected_sections


def _build_endnote_run_sections(
    run_pages: list[dict],
    chapter_ranges: list[dict],
    forced_chapter: dict | None = None,
) -> list[dict]:
    if not run_pages:
        return []
    all_tr_lines: list[str] = []
    for page in run_pages:
        all_tr_lines.extend(_extract_note_candidate_lines(page["tr_lines"]))

    ocr_sections = _prepare_endnote_sections(
        _split_endnote_run_pages_into_sections(
            run_pages,
            chapter_ranges,
            line_key="orig_lines",
            forced_chapter=forced_chapter,
        )
    )
    pdf_sections = _prepare_endnote_sections(
        _split_endnote_run_pages_into_sections(
            run_pages,
            chapter_ranges,
            line_key="pdf_orig_lines",
            forced_chapter=forced_chapter,
        )
    )
    prepared_sections = _select_base_endnote_sections(ocr_sections, pdf_sections)

    if not prepared_sections:
        return []

    tr_items = _split_footnote_items("\n".join(all_tr_lines), strict=False)
    assigned_tr_items: list[list[tuple[str | None, str]]] = [[] for _ in prepared_sections]
    section_idx = 0
    current_has_numeric = False
    last_numeric: int | None = None

    def _peek_next_numeric(from_idx: int) -> int | None:
        for future_label, _future_content in tr_items[from_idx:]:
            if future_label is not None and str(future_label).isdigit():
                return int(future_label)
        return None

    for item_idx, (label, content) in enumerate(tr_items):
        if section_idx >= len(prepared_sections):
            section_idx = len(prepared_sections) - 1
        if label is not None and str(label).isdigit():
            number = int(label)
            skipped_heading = False
            while section_idx + 1 < len(prepared_sections):
                next_section = prepared_sections[section_idx + 1]
                next_first = next_section["note_numbers"][0] if next_section["note_numbers"] else None
                next_heading = next_section.get("heading_number")
                next_numeric = _peek_next_numeric(item_idx + 1)
                if (
                    current_has_numeric
                    and next_heading is not None
                    and number == int(next_heading)
                    and next_first is not None
                    and next_numeric == int(next_first)
                ):
                    skipped_heading = True
                    break
                if (
                    current_has_numeric
                    and next_first is not None
                    and number == int(next_first)
                    and last_numeric is not None
                    and number < last_numeric
                ):
                    section_idx += 1
                    current_has_numeric = False
                    last_numeric = None
                    continue
                break
            if skipped_heading:
                continue
            assigned_tr_items[section_idx].append((label, content))
            current_has_numeric = True
            last_numeric = number
            continue
        if current_has_numeric or assigned_tr_items[section_idx]:
            assigned_tr_items[section_idx].append((label, content))

    for section, raw_tr_section_items in zip(prepared_sections, assigned_tr_items):
        _tr_order, tr_map = _merge_numbered_note_items(raw_tr_section_items)
        section["tr_map"] = tr_map

    return prepared_sections


def _normalize_note_title_hint(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", ensure_str(text)).lower()
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", normalized).strip()


def _match_chapter_by_note_title(chapter_ranges: list[dict], title: str) -> dict | None:
    target = _normalize_note_title_hint(title)
    if not target:
        return None
    best = None
    best_score = 0.0
    for chapter in chapter_ranges or []:
        chapter_title = ensure_str(chapter.get("title", "")).strip()
        if not chapter_title or _looks_like_backmatter_title(chapter_title):
            continue
        candidate = _normalize_note_title_hint(chapter_title)
        if not candidate:
            continue
        if target in candidate or candidate in target:
            return chapter
        score = SequenceMatcher(None, target, candidate).ratio()
        if score > best_score:
            best = chapter
            best_score = score
    return best if best_score >= 0.58 else None


def _build_structured_endnote_groups(
    entries: list[dict],
    chapter_ranges: list[dict] | None,
    pages: list[dict] | None,
) -> tuple[list[dict], set[int]]:
    if not pages:
        return [], set()
    page_by_bp = {
        int(page.get("bookPage") or 0): page
        for page in (pages or [])
        if int(page.get("bookPage") or 0) > 0
    }
    groups_by_key: dict[str, dict] = {}
    group_order: list[str] = []
    covered_bps: set[int] = set()

    for entry in entries or []:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp <= 0:
            continue
        page = page_by_bp.get(bp) or {}
        note_scan = page.get("_note_scan") if isinstance(page, dict) else {}
        segment_items = []
        for seg_idx, page_entry in enumerate(entry.get("_page_entries") or []):
            if ensure_str(page_entry.get("_note_kind", "")).strip() != "endnote":
                continue
            number = page_entry.get("_note_number")
            try:
                number = int(number)
            except (TypeError, ValueError):
                continue
            orig = ensure_str(page_entry.get("original", "")).strip()
            tr = ensure_str(page_entry.get("translation", "")).strip()
            if not orig and not tr:
                continue
            segment_items.append({
                "order": seg_idx,
                "number": number,
                "orig": orig,
                "tr": tr,
                "marker": ensure_str(page_entry.get("_note_marker", "")).strip(),
                "section_title": ensure_str(page_entry.get("_note_section_title", "")).strip(),
                "confidence": float(page_entry.get("_note_confidence", 0.0) or 0.0),
            })
        if not segment_items:
            continue
        covered_bps.add(bp)
        page_kind = ensure_str((note_scan or {}).get("page_kind", "")).strip()
        hint_title = ""
        for item in segment_items:
            if item["section_title"]:
                hint_title = item["section_title"]
                break
        if not hint_title:
            for hint in (note_scan or {}).get("section_hints") or []:
                hint = ensure_str(hint).strip()
                if hint and not _looks_like_backmatter_title(hint):
                    hint_title = hint
                    break
        chapter = _match_chapter_by_note_title(chapter_ranges or [], hint_title) if hint_title else None
        if chapter is None and page_kind == "mixed_body_endnotes":
            chapter = _resolve_chapter_for_bp(chapter_ranges or [], bp)
            if chapter and _looks_like_backmatter_title(chapter.get("title", "")):
                chapter = None
        chapter_index = int(chapter["index"]) if chapter is not None else None
        chapter_title = ensure_str(chapter.get("title", "")).strip() if chapter is not None else hint_title
        chapter_start_bp = chapter.get("start_bp") if chapter is not None else None
        if chapter_index is not None:
            group_key = f"chapter:{chapter_index}"
        elif hint_title:
            group_key = f"hint:{_normalize_note_title_hint(hint_title)}"
        else:
            group_key = f"book:{bp}"
        if group_key not in groups_by_key:
            groups_by_key[group_key] = {
                "group_key": group_key,
                "chapter_index": chapter_index,
                "chapter_title": chapter_title,
                "chapter_start_bp": chapter_start_bp,
                "note_scope": "chapter_end" if chapter_index is not None else "book_end",
                "notes": {},
            }
            group_order.append(group_key)
        group = groups_by_key[group_key]
        if not group.get("chapter_title") and chapter_title:
            group["chapter_title"] = chapter_title
        if group.get("chapter_start_bp") is None and chapter_start_bp is not None:
            group["chapter_start_bp"] = chapter_start_bp
        for item in sorted(segment_items, key=lambda data: (data["number"], data["order"])):
            note_entry = group["notes"].setdefault(
                int(item["number"]),
                {
                    "number": int(item["number"]),
                    "orig": "",
                    "tr": "",
                    "source_bps": [bp],
                },
            )
            if bp not in note_entry["source_bps"]:
                note_entry["source_bps"].append(bp)
            if item["orig"] and not note_entry.get("orig"):
                note_entry["orig"] = item["orig"]
            if item["tr"] and not note_entry.get("tr"):
                note_entry["tr"] = item["tr"]

    groups = [groups_by_key[key] for key in group_order]
    groups.sort(
        key=lambda group: (
            group.get("chapter_index") is None,
            int(group.get("chapter_start_bp") or 10**9),
            ensure_str(group.get("chapter_title", "")),
            ensure_str(group.get("group_key", "")),
        )
    )
    return groups, covered_bps


def build_endnote_index(
    entries: list[dict],
    endnote_page_map: dict[int | None, list[int]],
    chapter_ranges: list[dict] | None = None,
    pages: list[dict] | None = None,
    *,
    load_pdf_note_lines_by_bp=None,
) -> dict:
    """从尾注集合页解析章节尾注，返回分组后的尾注索引。"""
    structured_groups, structured_bps = _build_structured_endnote_groups(entries, chapter_ranges, pages)
    if not endnote_page_map and not structured_groups:
        return {"groups": []}

    entry_by_bp: dict[int, dict] = {}
    for entry in entries or []:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp > 0:
            entry_by_bp[bp] = entry
    doc_id = ensure_str(next(
        (
            entry.get("doc_id")
            for entry in entries or []
            if ensure_str(entry.get("doc_id")).strip()
        ),
        "",
    )).strip()
    endnote_bps = [bp for bps in (endnote_page_map or {}).values() for bp in (bps or [])]
    pdf_note_lines_by_bp = (
        load_pdf_note_lines_by_bp(doc_id, endnote_bps)
        if load_pdf_note_lines_by_bp is not None
        else {}
    )

    groups_by_key: dict[str, dict] = {
        ensure_str(group.get("group_key", "")): dict(group)
        for group in structured_groups
        if ensure_str(group.get("group_key", ""))
    }
    group_order: list[str] = [
        ensure_str(group.get("group_key", ""))
        for group in structured_groups
        if ensure_str(group.get("group_key", ""))
    ]

    for chapter_index, bps in endnote_page_map.items():
        candidate_chapter = None
        if chapter_index is not None:
            candidate_chapter = next(
                (
                    chapter for chapter in (chapter_ranges or [])
                    if chapter.get("index") == chapter_index
                ),
                None,
            )
        for run_bps in _split_consecutive_bps(bps):
            if run_bps and all(int(bp) in structured_bps for bp in run_bps):
                continue
            forced_chapter = None
            if candidate_chapter and not _looks_like_backmatter_title(candidate_chapter.get("title", "")):
                chapter_end_bp = int(candidate_chapter.get("end_bp") or 0)
                if int(run_bps[0]) <= chapter_end_bp + 2:
                    forced_chapter = candidate_chapter
            run_pages = []
            for bp in run_bps:
                entry = entry_by_bp.get(bp)
                if not entry:
                    continue
                run_pages.append({
                    "bp": int(bp),
                    "orig_lines": _collect_entry_lines(entry, "original"),
                    "tr_lines": _collect_entry_lines(entry, "translation"),
                    "pdf_orig_lines": list(pdf_note_lines_by_bp.get(int(bp), [])),
                })
            for section in _build_endnote_run_sections(
                run_pages,
                chapter_ranges or [],
                forced_chapter=forced_chapter,
            ):
                all_numbers = sorted(set(section.get("orig_map", {})) | set(section.get("tr_map", {})))
                if not all_numbers:
                    continue
                current_chapter_index = section.get("chapter_index")
                if current_chapter_index is None:
                    group_key = f"book:{run_bps[0]}:{len(group_order)}"
                else:
                    group_key = f"chapter:{int(current_chapter_index)}"
                if group_key not in groups_by_key:
                    groups_by_key[group_key] = {
                        "group_key": group_key,
                        "chapter_index": current_chapter_index,
                        "chapter_title": section.get("chapter_title", ""),
                        "chapter_start_bp": section.get("chapter_start_bp"),
                        "note_scope": "chapter_end" if current_chapter_index is not None else "book_end",
                        "notes": {},
                    }
                    group_order.append(group_key)
                group = groups_by_key[group_key]
                if not group.get("chapter_title") and section.get("chapter_title"):
                    group["chapter_title"] = section["chapter_title"]
                if group.get("chapter_start_bp") is None and section.get("chapter_start_bp") is not None:
                    group["chapter_start_bp"] = section["chapter_start_bp"]
                for number in all_numbers:
                    note_entry = group["notes"].setdefault(
                        int(number),
                        {
                            "number": int(number),
                            "orig": "",
                            "tr": "",
                            "source_bps": list(run_bps),
                        },
                    )
                    if section.get("orig_map", {}).get(number) and not note_entry.get("orig"):
                        note_entry["orig"] = section["orig_map"][number]
                    if section.get("tr_map", {}).get(number) and not note_entry.get("tr"):
                        note_entry["tr"] = section["tr_map"][number]

    groups = [groups_by_key[key] for key in group_order]
    groups.sort(
        key=lambda group: (
            group.get("chapter_index") is None,
            int(group.get("chapter_start_bp") or 10**9),
            ensure_str(group.get("chapter_title", "")),
        )
    )
    return {"groups": groups}


def _resolve_page_footnote_assignments(page_entries: list[dict]) -> dict[int, list[tuple[str, str]]]:
    assignments: dict[int, list[tuple[str, str]]] = {}
    body_indices = [
        idx for idx, page_entry in enumerate(page_entries)
        if int(page_entry.get("heading_level", 0) or 0) <= 0
        and (ensure_str(page_entry.get("original")).strip() or ensure_str(page_entry.get("translation")).strip())
    ]
    if not body_indices:
        body_indices = list(range(len(page_entries)))

    footnote_entries = []
    for idx, page_entry in enumerate(page_entries):
        footnotes = ensure_str(page_entry.get("footnotes")).strip()
        footnotes_translation = ensure_str(page_entry.get("footnotes_translation")).strip()
        if footnotes or footnotes_translation:
            footnote_entries.append((idx, footnotes, footnotes_translation))

    if not footnote_entries:
        return assignments

    if len(footnote_entries) == 1 and body_indices:
        idx, footnotes, footnotes_translation = footnote_entries[0]
        first_body_idx = body_indices[0]
        last_body_idx = body_indices[-1]
        if last_body_idx != idx and (idx not in body_indices or idx == first_body_idx):
            return {last_body_idx: [(footnotes, footnotes_translation)]}

    for idx, footnotes, footnotes_translation in footnote_entries:
        assignments.setdefault(idx, []).append((footnotes, footnotes_translation))
    return assignments


def _resolve_heading_toc_match(pe: dict, bp: int, toc_depth_map: dict) -> tuple[int, int] | None:
    if not toc_depth_map:
        return None
    probes: list[int] = []
    start_bp = pe.get("_startBP")
    if start_bp is not None:
        try:
            probes.append(int(start_bp))
        except (TypeError, ValueError):
            pass
    try:
        probes.append(int(bp))
    except (TypeError, ValueError):
        pass
    probes = [probe for probe in probes if probe > 0]
    seen = set()
    probes = [probe for probe in probes if not (probe in seen or seen.add(probe))]
    for probe in probes:
        depth = toc_depth_map.get(probe)
        if depth is not None:
            return int(probe), int(depth)
    keys = sorted(int(key) for key in toc_depth_map.keys())
    best_depth = None
    best_dist = None
    for probe in probes:
        for key in keys:
            dist = abs(int(key) - int(probe))
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_depth = int(toc_depth_map[key])
    if best_dist is not None and best_dist <= 1 and best_depth is not None:
        nearest_bp = None
        for probe in probes:
            for key in keys:
                if abs(int(key) - int(probe)) == best_dist:
                    nearest_bp = int(key)
                    break
            if nearest_bp is not None:
                break
        if nearest_bp is not None:
            return nearest_bp, best_depth
    return None


def _normalize_heading_text_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", ensure_str(text)).lower()
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", normalized).strip()


def _heading_matches_toc_title(orig: str, tr: str, toc_title: str) -> bool:
    title = _normalize_heading_text_for_match(toc_title)
    if not title:
        return True
    orig_norm = _normalize_heading_text_for_match(orig)
    tr_norm = _normalize_heading_text_for_match(tr)
    haystack = f"{orig_norm} {tr_norm}".strip()
    if not haystack:
        return False
    if title in haystack:
        return True
    ratio = SequenceMatcher(None, haystack, title).ratio()
    if ratio >= 0.5:
        return True
    tokens = [token for token in title.split() if len(token) >= 4]
    if tokens and any(token in haystack for token in tokens):
        return True
    return False


def _resolve_heading_level(pe: dict, toc_depth_map: dict, min_non_toc_level: int = 1, bp: int = 0) -> tuple[int, int | None]:
    hlevel = int(pe.get("heading_level", 0) or 0)
    if hlevel <= 0:
        return 0, None
    if not toc_depth_map:
        return hlevel, None
    match = _resolve_heading_toc_match(pe, bp=bp, toc_depth_map=toc_depth_map)
    if match is not None:
        matched_bp, depth = match
        return max(1, int(depth) + 1), matched_bp
    return 0, None


def _looks_like_heading_noise(text: str) -> bool:
    content = ensure_str(text).strip()
    if not content:
        return True
    if content in {"*", "#", "-", "—", "_"}:
        return True
    if re.match(r"^\d{1,3}[\.\)、]\s+", content):
        return True
    return False


def _should_demote_heading(
    *,
    hlevel: int,
    toc_depth_map: dict,
    bp: int,
    start_bp: int | None,
    title_text: str,
) -> bool:
    if hlevel <= 0:
        return False
    if _looks_like_heading_noise(title_text):
        return True
    if not toc_depth_map:
        return False

    top_level_starts = sorted(int(key) for key, depth in toc_depth_map.items() if int(depth) == 0)
    if top_level_starts:
        first_chapter_bp = top_level_starts[0]
        if int(bp) < int(first_chapter_bp):
            return True

    if start_bp is not None and int(start_bp) in toc_depth_map:
        return False
    return False


def _normalize_endnote_registry(
    endnote_index: dict | None,
    chapter_ranges: list[dict],
    toc_title_map: dict[int, str] | None,
) -> dict:
    if not endnote_index:
        return {
            "groups": [],
            "groups_by_chapter": {},
            "book_groups": [],
            "duplicate_chapter_numbers": set(),
            "global_duplicate_numbers": set(),
        }

    if isinstance(endnote_index, dict) and "groups" in endnote_index:
        raw_groups = list(endnote_index.get("groups") or [])
    else:
        raw_groups = []
        for chapter_index, notes in (endnote_index or {}).items():
            chapter = next(
                (item for item in chapter_ranges if item.get("index") == chapter_index),
                None,
            )
            chapter_title = ""
            chapter_start_bp = None
            if chapter is not None:
                chapter_title = ensure_str(chapter.get("title", "")).strip()
                chapter_start_bp = chapter.get("start_bp")
            if not chapter_title and chapter_start_bp is not None and toc_title_map:
                chapter_title = ensure_str(toc_title_map.get(int(chapter_start_bp), "")).strip()
            raw_groups.append({
                "group_key": f"chapter:{chapter_index}" if chapter_index is not None else "book:legacy",
                "chapter_index": chapter_index,
                "chapter_title": chapter_title,
                "chapter_start_bp": chapter_start_bp,
                "note_scope": "chapter_end" if chapter_index is not None else "book_end",
                "notes": {
                    int(number): {
                        "number": int(number),
                        "orig": ensure_str(value.get("orig", "")),
                        "tr": ensure_str(value.get("tr", "")),
                    }
                    for number, value in (notes or {}).items()
                    if str(number).isdigit()
                },
            })

    groups: list[dict] = []
    chapter_number_counts: dict[int, int] = {}
    global_number_counts: dict[int, int] = {}
    for group in raw_groups:
        notes = {
            int(number): {
                "number": int(number),
                "orig": ensure_str(value.get("orig", "")),
                "tr": ensure_str(value.get("tr", "")),
            }
            for number, value in (group.get("notes") or {}).items()
            if str(number).isdigit()
        }
        if not notes:
            continue
        normalized_group = {
            "group_key": ensure_str(group.get("group_key")).strip() or (
                f"chapter:{group.get('chapter_index')}"
                if group.get("chapter_index") is not None
                else f"book:{len(groups)}"
            ),
            "chapter_index": group.get("chapter_index"),
            "chapter_title": ensure_str(group.get("chapter_title", "")).strip(),
            "chapter_start_bp": group.get("chapter_start_bp"),
            "note_scope": ensure_str(group.get("note_scope", "")).strip() or (
                "chapter_end" if group.get("chapter_index") is not None else "book_end"
            ),
            "notes": notes,
        }
        if not normalized_group["chapter_title"] and normalized_group["chapter_index"] is not None:
            chapter = next(
                (
                    item for item in chapter_ranges
                    if item.get("index") == normalized_group["chapter_index"]
                ),
                None,
            )
            if chapter is not None:
                normalized_group["chapter_title"] = ensure_str(chapter.get("title", "")).strip()
                normalized_group["chapter_start_bp"] = chapter.get("start_bp")
        groups.append(normalized_group)
        for number in notes:
            global_number_counts[number] = global_number_counts.get(number, 0) + 1
            if normalized_group["chapter_index"] is not None:
                chapter_number_counts[number] = chapter_number_counts.get(number, 0) + 1

    groups.sort(
        key=lambda group: (
            group.get("chapter_index") is None,
            int(group.get("chapter_start_bp") or 10**9),
            ensure_str(group.get("chapter_title", "")),
        )
    )
    chapter_ordinal = 0
    for group in groups:
        if group.get("chapter_index") is None:
            group["chapter_label_prefix"] = ""
            continue
        group["chapter_label_prefix"] = f"ch{chapter_ordinal:02d}"
        chapter_ordinal += 1
    groups_by_chapter = {
        int(group["chapter_index"]): group
        for group in groups
        if group.get("chapter_index") is not None
    }
    book_groups = [group for group in groups if group.get("chapter_index") is None]
    return {
        "groups": groups,
        "groups_by_chapter": groups_by_chapter,
        "book_groups": book_groups,
        "duplicate_chapter_numbers": {
            number for number, count in chapter_number_counts.items() if count > 1
        },
        "global_duplicate_numbers": {
            number for number, count in global_number_counts.items() if count > 1
        },
    }


def _build_endnote_label(group: dict, number: int, registry: dict) -> str:
    num = int(number)
    chapter_index = group.get("chapter_index")
    if chapter_index is not None and num in set(registry.get("duplicate_chapter_numbers", set())):
        prefix = ensure_str(group.get("chapter_label_prefix", "")).strip() or f"ch{int(chapter_index)}"
        return f"{prefix}-{num}"
    if chapter_index is None and num in set(registry.get("global_duplicate_numbers", set())):
        return f"book-{num}"
    return str(num)

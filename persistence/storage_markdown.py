"""Markdown 导出渲染 helper。"""

from document.text_utils import strip_html


def _note_sort_key(note_def: dict, ensure_str) -> tuple[int, str]:
    explicit_number = note_def.get("number")
    if explicit_number is not None:
        return int(explicit_number), ensure_str(note_def.get("label", ""))
    label = ensure_str(note_def.get("label", ""))
    import re

    match = re.search(r"(\d+)$", label)
    return (int(match.group(1)) if match else 10**9, label)


def gen_markdown(
    entries: list,
    toc_depth_map: dict | None = None,
    page_ranges: list[tuple[int, int]] | None = None,
    skip_bps: set[int] | None = None,
    toc_title_map: dict[int, str] | None = None,
    endnote_index: dict | None = None,
    endnote_page_bps: set[int] | None = None,
    *,
    helpers: dict,
) -> str:
    """生成 Markdown 导出内容。"""
    ensure_str = helpers["ensure_str"]
    build_chapter_ranges_from_depth_map = helpers["build_chapter_ranges_from_depth_map"]
    normalize_endnote_registry = helpers["normalize_endnote_registry"]
    resolve_chapter_for_bp = helpers["resolve_chapter_for_bp"]
    resolve_heading_level = helpers["resolve_heading_level"]
    heading_matches_toc_title = helpers["heading_matches_toc_title"]
    should_demote_heading = helpers["should_demote_heading"]
    extract_marked_footnote_labels = helpers["extract_marked_footnote_labels"]
    build_obsidian_footnote_defs = helpers["build_obsidian_footnote_defs"]
    append_blockquote = helpers["append_blockquote"]
    append_paragraph = helpers["append_paragraph"]
    append_labeled_block = helpers["append_labeled_block"]
    nonempty_markdown_lines = helpers["nonempty_markdown_lines"]
    normalize_footnote_markers = helpers["normalize_footnote_markers"]
    unwrap_translation_json = helpers["unwrap_translation_json"]
    build_endnote_label = helpers["build_endnote_label"]
    resolve_page_footnote_assignments = helpers["resolve_page_footnote_assignments"]

    dm = toc_depth_map or {}
    if dm:
        min_non_toc_level = max(depth + 1 for depth in dm.values()) + 1
    else:
        min_non_toc_level = 1

    def _in_ranges(bp: int) -> bool:
        if page_ranges is None:
            return True
        return any(s <= bp <= e for s, e in page_ranges)

    skip_set = {int(bp) for bp in (skip_bps or set()) if int(bp) > 0}
    if endnote_page_bps:
        skip_set.update(int(bp) for bp in endnote_page_bps if int(bp) > 0)

    entries_for_export: list[dict] = []
    for entry in entries:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if bp > 0 and bp in skip_set:
            continue
        entries_for_export.append(entry)

    md_lines: list[str] = []
    all_bps = [
        int(entry.get("_pageBP") or entry.get("book_page") or 0)
        for entry in entries_for_export
        if int(entry.get("_pageBP") or entry.get("book_page") or 0) > 0
    ]
    if not all_bps:
        return ""

    doc_last_bp = max(all_bps) if all_bps else 1
    chapter_ranges = build_chapter_ranges_from_depth_map(dm, all_bps, toc_title_map=toc_title_map)
    endnote_registry = normalize_endnote_registry(endnote_index, chapter_ranges, toc_title_map)
    used_endnote_chapter_groups: set[int] = set()
    used_endnote_book_groups: set[str] = set()
    chapter_endnotes: dict[int, list[dict]] = {}
    book_endnotes: list[dict] = []
    seen_footnote_labels: set[str] = set()

    for entry in entries_for_export:
        bp = int(entry.get("_pageBP") or entry.get("book_page") or 0)
        if not _in_ranges(bp):
            continue
        page_entries = entry.get("_page_entries")
        if page_entries:
            footnote_assignments = resolve_page_footnote_assignments(page_entries)
            current_chapter = resolve_chapter_for_bp(chapter_ranges, bp)
            for idx, page_entry in enumerate(page_entries):
                hlevel, matched_toc_bp = resolve_heading_level(
                    page_entry,
                    dm,
                    min_non_toc_level,
                    bp=bp,
                )
                orig = strip_html(normalize_footnote_markers(ensure_str(page_entry.get("original")).strip())).strip()
                tr = strip_html(
                    normalize_footnote_markers(
                        unwrap_translation_json(ensure_str(page_entry.get("translation")).strip())
                    )
                ).strip()
                if hlevel > 0 and matched_toc_bp is not None and toc_title_map:
                    toc_title = ensure_str(toc_title_map.get(int(matched_toc_bp))).strip()
                    if toc_title and not heading_matches_toc_title(orig, tr, toc_title):
                        hlevel = 0
                if should_demote_heading(
                    hlevel=hlevel,
                    toc_depth_map=dm,
                    bp=bp,
                    start_bp=page_entry.get("_startBP"),
                    title_text=tr or orig,
                ):
                    hlevel = 0
                inline_labels = extract_marked_footnote_labels(f"{orig}\n{tr}")
                label_rewrites: dict[str, str] = {}
                if endnote_registry["groups"] and inline_labels:
                    current_chapter_index = int(current_chapter["index"]) if current_chapter else None
                    current_group = (
                        endnote_registry["groups_by_chapter"].get(current_chapter_index)
                        if current_chapter_index is not None
                        else None
                    )
                    for label in inline_labels:
                        if not label.isdigit():
                            continue
                        number = int(label)
                        matched_group = None
                        if current_group and number in current_group.get("notes", {}):
                            matched_group = current_group
                            used_endnote_chapter_groups.add(int(current_group["chapter_index"]))
                        else:
                            candidate_book_groups = [
                                group for group in endnote_registry["book_groups"]
                                if number in group.get("notes", {})
                            ]
                            if len(candidate_book_groups) == 1:
                                matched_group = candidate_book_groups[0]
                                used_endnote_book_groups.add(ensure_str(matched_group["group_key"]))
                            else:
                                candidate_chapter_groups = [
                                    group for group in endnote_registry["groups"]
                                    if group.get("chapter_index") is not None
                                    and number in group.get("notes", {})
                                ]
                                if len(candidate_chapter_groups) == 1:
                                    matched_group = candidate_chapter_groups[0]
                                    used_endnote_chapter_groups.add(int(candidate_chapter_groups[0]["chapter_index"]))
                        if matched_group is None:
                            continue
                        rewritten_label = build_endnote_label(matched_group, number, endnote_registry)
                        seen_footnote_labels.add(rewritten_label)
                        if rewritten_label != label:
                            label_rewrites[label] = rewritten_label
                if label_rewrites:
                    for old_label, new_label in label_rewrites.items():
                        orig = orig.replace(f"[^{old_label}]", f"[^{new_label}]")
                        tr = tr.replace(f"[^{old_label}]", f"[^{new_label}]")
                    inline_labels = [label_rewrites.get(label, label) for label in inline_labels]
                if hlevel > 0:
                    prefix = "#" * min(hlevel, 6)
                    if tr:
                        md_lines.append(f"{prefix} {tr}")
                        if orig and orig != tr:
                            md_lines.append(f"*{orig}*")
                        md_lines.append("")
                    elif orig:
                        md_lines.append(f"{prefix} {orig}")
                        md_lines.append("")
                else:
                    append_blockquote(md_lines, orig)
                    pending_ref_labels: list[str] = []
                    fallback_blocks: list[tuple[str, str]] = []
                    pending_footnote_defs: list[dict] = []
                    for footnotes, footnotes_translation in footnote_assignments.get(idx, []):
                        defs, parsed_labels, fallback = build_obsidian_footnote_defs(
                            footnotes=footnotes,
                            footnotes_translation=footnotes_translation,
                            existing_labels=list(seen_footnote_labels) + pending_ref_labels,
                            preferred_labels=inline_labels,
                            source_bp=bp,
                            segment_idx=idx,
                            chapter_index=current_chapter["index"] if current_chapter else None,
                            chapter_end_bp=current_chapter["end_bp"] if current_chapter else None,
                            doc_last_bp=doc_last_bp,
                            fallback_prefix=f"p{bp}-s{idx}",
                        )
                        for note_def in defs:
                            label = note_def["label"]
                            if label not in seen_footnote_labels:
                                seen_footnote_labels.add(label)
                                pending_ref_labels.append(label)
                                if note_def["note_type"] == "endnote":
                                    if note_def["note_scope"] == "chapter_end" and note_def.get("chapter_index") is not None:
                                        chapter_endnotes.setdefault(int(note_def["chapter_index"]), []).append(note_def)
                                    else:
                                        book_endnotes.append(note_def)
                                else:
                                    pending_footnote_defs.append(note_def)
                        fallback_blocks.extend(fallback)

                    tr_with_refs = tr
                    for label in pending_ref_labels:
                        marker = f"[^{label}]"
                        if marker not in tr_with_refs and marker not in orig:
                            tr_with_refs = (tr_with_refs + f" {marker}").strip() if tr_with_refs else marker
                    append_paragraph(md_lines, tr_with_refs)
                    for note_def in pending_footnote_defs:
                        content_lines = nonempty_markdown_lines(note_def.get("content"))
                        if not content_lines:
                            continue
                        md_lines.append(f"[^{note_def['label']}]: {content_lines[0]}")
                        for line in content_lines[1:]:
                            md_lines.append(f"    {line}")
                        md_lines.append("")
                    for fb_label, fb_text in fallback_blocks:
                        append_labeled_block(md_lines, fb_label, fb_text)
        else:
            orig = strip_html(normalize_footnote_markers(ensure_str(entry.get("original")).strip())).strip()
            tr_legacy = strip_html(
                normalize_footnote_markers(unwrap_translation_json(ensure_str(entry.get("translation")).strip()))
            ).strip()
            append_blockquote(md_lines, orig)
            append_paragraph(md_lines, tr_legacy)
            defs, _, fallback_blocks = build_obsidian_footnote_defs(
                entry.get("footnotes"),
                entry.get("footnotes_translation"),
                existing_labels=list(seen_footnote_labels),
                preferred_labels=extract_marked_footnote_labels(f"{orig}\n{tr_legacy}"),
                source_bp=bp,
                segment_idx=0,
                chapter_index=resolve_chapter_for_bp(chapter_ranges, bp)["index"] if resolve_chapter_for_bp(chapter_ranges, bp) else None,
                chapter_end_bp=resolve_chapter_for_bp(chapter_ranges, bp)["end_bp"] if resolve_chapter_for_bp(chapter_ranges, bp) else None,
                doc_last_bp=doc_last_bp,
                fallback_prefix=f"p{bp}-legacy",
            )
            for note_def in defs:
                label = note_def["label"]
                if label not in seen_footnote_labels:
                    seen_footnote_labels.add(label)
                    if note_def["note_type"] == "endnote":
                        if note_def["note_scope"] == "chapter_end" and note_def.get("chapter_index") is not None:
                            chapter_endnotes.setdefault(int(note_def["chapter_index"]), []).append(note_def)
                        else:
                            book_endnotes.append(note_def)
                    else:
                        content_lines = nonempty_markdown_lines(note_def.get("content"))
                        if content_lines:
                            md_lines.append(f"[^{label}]: {content_lines[0]}")
                            for line in content_lines[1:]:
                                md_lines.append(f"    {line}")
                            md_lines.append("")
            for fb_label, fb_text in fallback_blocks:
                append_labeled_block(md_lines, fb_label, fb_text)

    has_grouped_chapter_endnotes = bool(used_endnote_chapter_groups)
    has_extra_chapter_endnotes = any(chapter_endnotes.get(int(chapter["index"])) for chapter in chapter_ranges)
    if has_grouped_chapter_endnotes or has_extra_chapter_endnotes:
        if md_lines and md_lines[-1].strip():
            md_lines.append("")
        md_lines.append("## 本章尾注")
        md_lines.append("")
        for chapter in chapter_ranges:
            chapter_index = int(chapter["index"])
            group = (
                endnote_registry["groups_by_chapter"].get(chapter_index)
                if chapter_index in used_endnote_chapter_groups
                else None
            )
            notes = list(chapter_endnotes.get(chapter_index) or [])
            if not group and not notes:
                continue
            chapter_title = ensure_str(chapter.get("title", "")).strip()
            if group and group.get("chapter_title"):
                chapter_title = ensure_str(group.get("chapter_title", "")).strip()
            if not chapter_title and toc_title_map:
                chapter_title = ensure_str(toc_title_map.get(int(chapter.get("start_bp", 0)), "")).strip()
            if not chapter_title:
                chapter_title = f"章节 {chapter_index + 1}"
            md_lines.append(f"### {chapter_title}")
            md_lines.append("")
            if group:
                for number in sorted(int(value) for value in group.get("notes", {}).keys()):
                    note = group["notes"][number]
                    merged_parts = []
                    if note.get("orig"):
                        merged_parts.append(note["orig"])
                    if note.get("tr"):
                        merged_parts.append(f"译：{note['tr']}")
                    content_lines = nonempty_markdown_lines("\n".join(merged_parts).strip())
                    if not content_lines:
                        continue
                    label = build_endnote_label(group, number, endnote_registry)
                    md_lines.append(f"[^{label}]: {content_lines[0]}")
                    for line in content_lines[1:]:
                        md_lines.append(f"    {line}")
                    md_lines.append("")
            for note_def in sorted(notes, key=lambda item: _note_sort_key(item, ensure_str)):
                content_lines = nonempty_markdown_lines(note_def.get("content"))
                if not content_lines:
                    continue
                md_lines.append(f"[^{note_def['label']}]: {content_lines[0]}")
                for line in content_lines[1:]:
                    md_lines.append(f"    {line}")
                md_lines.append("")

    has_grouped_book_endnotes = bool(used_endnote_book_groups)
    if has_grouped_book_endnotes or book_endnotes:
        if md_lines and md_lines[-1].strip():
            md_lines.append("")
        md_lines.append("## 全书尾注")
        md_lines.append("")
        for group in endnote_registry["book_groups"]:
            if ensure_str(group.get("group_key")) not in used_endnote_book_groups:
                continue
            for number in sorted(int(value) for value in group.get("notes", {}).keys()):
                note = group["notes"][number]
                merged_parts = []
                if note.get("orig"):
                    merged_parts.append(note["orig"])
                if note.get("tr"):
                    merged_parts.append(f"译：{note['tr']}")
                content_lines = nonempty_markdown_lines("\n".join(merged_parts).strip())
                if not content_lines:
                    continue
                label = build_endnote_label(group, number, endnote_registry)
                md_lines.append(f"[^{label}]: {content_lines[0]}")
                for line in content_lines[1:]:
                    md_lines.append(f"    {line}")
                md_lines.append("")
        for note_def in sorted(book_endnotes, key=lambda item: _note_sort_key(item, ensure_str)):
            content_lines = nonempty_markdown_lines(note_def.get("content"))
            if not content_lines:
                continue
            md_lines.append(f"[^{note_def['label']}]: {content_lines[0]}")
            for line in content_lines[1:]:
                md_lines.append(f"    {line}")
            md_lines.append("")

    while md_lines and not md_lines[-1].strip():
        md_lines.pop()
    if not md_lines:
        return ""
    return "\n".join(md_lines) + "\n"

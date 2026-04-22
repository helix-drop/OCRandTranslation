"""阶段 5 模块：整书导出组装。"""

from __future__ import annotations

import re
from typing import Any

from document.text_layer_fixer import detect_and_fix_text
from FNM_RE.models import (
    ExportBundleRecord,
    ExportChapterRecord,
    Phase6Structure,
    Phase6Summary,
    StructureStatusRecord,
)
from FNM_RE.modules.contracts import GateReport, ModuleResult
from FNM_RE.modules.types import (
    ChapterMarkdownEntry,
    ChapterMarkdownSet,
    ExportAuditFile,
    ExportAuditReport,
    ExportBundle,
    TocStructure,
)
from FNM_RE.stages import export as export_stage
from FNM_RE.stages import export_audit as export_audit_stage
from FNM_RE.stages.export_audit import audit_phase6_export

_IMAGE_ONLY_PARAGRAPH_RE = re.compile(
    r"^\s*(?:!\[[^\]]*\]\([^)]+\)|<div[^>]*>\s*<img\b[^>]*>\s*</div>|<img\b[^>]*>)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SUSPECT_ASCII_GARBLED_RE = re.compile(r"[A-Z0-9@;:<>=?]{12,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([?!:;,])")
_MARKDOWN_PREFIX_PATTERNS = (
    re.compile(r"^(\s*\[\^[^\]]+\]:\s+)(.*)$"),
    re.compile(r"^(\s*#{1,6}\s+)(.*)$"),
    re.compile(r"^(\s*[-*+]\s+)(.*)$"),
    re.compile(r"^(\s*\d+\.\s+)(.*)$"),
    re.compile(r"^(\s*>\s+)(.*)$"),
)


def _summary_title_key(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    return text.casefold()


def _toc_titles_and_summary(toc_structure: TocStructure) -> tuple[list[str], list[str], list[str], dict[str, int]]:
    container_titles = [
        str(row.title or "").strip()
        for row in toc_structure.toc_tree
        if str(row.role or "") == "container" and str(row.title or "").strip()
    ]
    post_body_titles = [
        str(row.title or "").strip()
        for row in toc_structure.chapters
        if str(row.role or "") == "post_body" and str(row.title or "").strip()
    ]
    back_matter_titles = [
        str(row.title or "").strip()
        for row in toc_structure.toc_tree
        if str(row.role or "") == "back_matter" and str(row.title or "").strip()
    ]
    exported_title_keys = {
        _summary_title_key(row.title)
        for row in toc_structure.chapters
        if str(row.role or "") in {"chapter", "post_body"} and _summary_title_key(str(row.title or ""))
    }
    if exported_title_keys:
        container_titles = [
            title
            for title in container_titles
            if _summary_title_key(title) not in exported_title_keys
        ]
    toc_role_summary = {
        "container": len(container_titles),
        "chapter": sum(1 for row in toc_structure.chapters if str(row.role or "") == "chapter"),
        "post_body": len(post_body_titles),
        "back_matter": len(back_matter_titles),
    }
    return container_titles, post_body_titles, back_matter_titles, toc_role_summary


def _reorder_chapters(
    chapter_markdown_set: ChapterMarkdownSet,
    toc_structure: TocStructure,
) -> tuple[list[ChapterMarkdownEntry], list[str], list[str]]:
    chapter_by_id = {
        str(row.chapter_id or ""): row
        for row in chapter_markdown_set.chapters
        if str(row.chapter_id or "").strip()
    }
    toc_ids = [str(row.chapter_id or "") for row in toc_structure.chapters if str(row.chapter_id or "").strip()]
    expected_export_ids = [chapter_id for chapter_id in toc_ids if chapter_id in chapter_by_id]

    ordered: list[ChapterMarkdownEntry] = []
    for chapter_id in expected_export_ids:
        row = chapter_by_id.get(chapter_id)
        if row is None:
            continue
        ordered.append(row)
    ordered_ids = set(expected_export_ids)
    leftovers = [row for row in chapter_markdown_set.chapters if str(row.chapter_id or "") not in ordered_ids]
    ordered.extend(leftovers)
    ordered = [
        ChapterMarkdownEntry(
            order=index,
            chapter_id=str(row.chapter_id or ""),
            title=str(row.title or ""),
            path=str(row.path or ""),
            markdown_text=str(row.markdown_text or ""),
            start_page=int(row.start_page or 0),
            end_page=int(row.end_page or int(row.start_page or 0)),
            pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
        )
        for index, row in enumerate(ordered, start=1)
    ]

    missing = [chapter_id for chapter_id in toc_ids if chapter_id not in chapter_by_id]
    extra = [str(row.chapter_id or "") for row in leftovers if str(row.chapter_id or "").strip()]
    return ordered, missing, extra


def _to_export_chapter_records(chapters: list[ChapterMarkdownEntry]) -> list[ExportChapterRecord]:
    return [
        ExportChapterRecord(
            order=int(row.order or 0),
            section_id=str(row.chapter_id or ""),
            title=str(row.title or ""),
            path=str(row.path or ""),
            content=str(row.markdown_text or ""),
            start_page=int(row.start_page or 0),
            end_page=int(row.end_page or int(row.start_page or 0)),
            pages=[int(page_no) for page_no in list(row.pages or []) if int(page_no) > 0],
        )
        for row in chapters
        if str(row.path or "").strip()
    ]


def _to_export_audit_report(report: Any) -> ExportAuditReport:
    return ExportAuditReport(
        slug=str(report.slug or ""),
        doc_id=str(report.doc_id or ""),
        zip_path=str(report.zip_path or ""),
        structure_state=str(report.structure_state or ""),
        blocking_reasons=[str(item).strip() for item in list(report.blocking_reasons or []) if str(item).strip()],
        manual_toc_summary=dict(report.manual_toc_summary or {}),
        toc_role_summary=dict(report.toc_role_summary or {}),
        chapter_titles=[str(item).strip() for item in list(report.chapter_titles or []) if str(item).strip()],
        files=[
            ExportAuditFile(
                path=str(item.path or ""),
                title=str(item.title or ""),
                page_span=[int(page_no) for page_no in list(item.page_span or []) if int(page_no) > 0],
                issue_codes=[str(code).strip() for code in list(item.issue_codes or []) if str(code).strip()],
                issue_summary=[str(code).strip() for code in list(item.issue_summary or []) if str(code).strip()],
                severity=str(item.severity or "minor"),
                sample_opening=str(item.sample_opening or ""),
                sample_mid=str(item.sample_mid or ""),
                sample_tail=str(item.sample_tail or ""),
                footnote_endnote_summary=dict(item.footnote_endnote_summary or {}),
            )
            for item in list(report.files or [])
        ],
        blocking_issue_count=int(report.blocking_issue_count or 0),
        major_issue_count=int(report.major_issue_count or 0),
        can_ship=bool(report.can_ship),
        must_fix_before_next_book=[dict(item or {}) for item in list(report.must_fix_before_next_book or [])],
        recommended_followups=[dict(item or {}) for item in list(report.recommended_followups or [])],
    )


def _has_book_level_raw_marker_leak(chapter_files: dict[str, str]) -> bool:
    for content in chapter_files.values():
        body_text, definition_text = export_audit_stage.split_body_and_definitions(str(content or ""))
        allowed_markers = set(export_audit_stage.LOCAL_REF_RE.findall(body_text))
        allowed_markers.update(export_audit_stage.LOCAL_DEF_RE.findall(str(content or "")))
        if not allowed_markers:
            continue
        if any(
            True for _ in export_audit_stage._iter_raw_note_marker_hits(body_text, allowed_markers=allowed_markers)
        ):
            return True
        if any(
            True
            for _ in export_audit_stage._iter_raw_superscript_note_marker_hits(body_text, allowed_markers=allowed_markers)
        ):
            return True
        if export_audit_stage._definition_has_raw_note_marker(definition_text, allowed_markers=allowed_markers):
            return True
    return False


def _is_adjacent_duplicate_candidate(paragraph: str) -> bool:
    normalized = str(paragraph or "").strip()
    if not normalized:
        return False
    if _IMAGE_ONLY_PARAGRAPH_RE.match(normalized):
        return False
    if export_stage._looks_like_bibliography_entry(normalized):
        return False
    return bool(export_stage._is_semantic_duplicate_candidate(normalized))


def _canonicalize_adjacent_duplicate_paragraphs(markdown_text: str) -> tuple[str, int]:
    raw = str(markdown_text or "")
    body_text, definition_text = export_audit_stage.split_body_and_definitions(raw)
    body_paragraphs = [
        str(chunk or "").strip()
        for chunk in re.split(r"\n\s*\n+", body_text)
        if str(chunk or "").strip()
    ]
    if not body_paragraphs:
        return raw, 0

    kept: list[str] = []
    collapsed_count = 0
    for paragraph in body_paragraphs:
        if kept and _is_adjacent_duplicate_candidate(paragraph) and _is_adjacent_duplicate_candidate(kept[-1]):
            if export_stage._normalized_paragraph_key(paragraph) == export_stage._normalized_paragraph_key(kept[-1]):
                collapsed_count += 1
                continue
        kept.append(paragraph)

    if collapsed_count <= 0:
        return raw, 0

    rebuilt_parts: list[str] = []
    rebuilt_body = "\n\n".join(kept).strip()
    if rebuilt_body:
        rebuilt_parts.append(rebuilt_body)
    definition_block = str(definition_text or "").strip()
    if definition_block:
        rebuilt_parts.append(definition_block)
    canonicalized = "\n\n".join(rebuilt_parts).strip()
    if canonicalized:
        canonicalized += "\n"
    return canonicalized, collapsed_count


def _split_markdown_prefix(line: str) -> tuple[str, str]:
    raw = str(line or "")
    for pattern in _MARKDOWN_PREFIX_PATTERNS:
        matched = pattern.match(raw)
        if matched:
            return str(matched.group(1) or ""), str(matched.group(2) or "")
    matched = re.match(r"^(\s*)(.*)$", raw)
    if not matched:
        return "", raw
    return str(matched.group(1) or ""), str(matched.group(2) or "")


def _looks_like_garbled_export_block(text: str) -> bool:
    sample = str(text or "").strip()
    if not sample:
        return False
    visible_chars = [char for char in sample if not char.isspace()]
    if len(visible_chars) < 12:
        return False
    control_hit = bool(_CONTROL_CHAR_RE.search(sample))
    ascii_run_hit = bool(_SUSPECT_ASCII_GARBLED_RE.search(sample))
    suspect_ascii_count = sum(
        1
        for char in visible_chars
        if char.isupper() or char.isdigit() or char in "@;:<>=?"
    )
    cjk_count = len(_CJK_CHAR_RE.findall(sample))
    cjk_ratio = cjk_count / max(len(visible_chars), 1)
    suspect_ascii_ratio = suspect_ascii_count / max(len(visible_chars), 1)
    if cjk_ratio >= 0.3 and not control_hit and not ascii_run_hit:
        return False
    return bool(control_hit or ascii_run_hit or suspect_ascii_ratio >= 0.55)


def _repair_garbled_markdown_blocks(markdown_text: str) -> tuple[str, dict[str, Any]]:
    lines = str(markdown_text or "").splitlines(keepends=True)
    repaired_lines: list[str] = []
    repaired_count = 0
    method_counts: dict[str, int] = {}

    for line in lines:
        line_ending = ""
        base_line = line
        if line.endswith("\r\n"):
            line_ending = "\r\n"
            base_line = line[:-2]
        elif line.endswith("\n"):
            line_ending = "\n"
            base_line = line[:-1]

        prefix, content = _split_markdown_prefix(base_line)
        if not _looks_like_garbled_export_block(content):
            repaired_lines.append(line)
            continue

        sanitized_content = _CONTROL_CHAR_RE.sub(" ", content)
        sanitized_content = re.sub(r"[ \t]{2,}", " ", sanitized_content).strip()
        if not sanitized_content:
            repaired_lines.append(line)
            continue

        fixed_content, method = detect_and_fix_text(
            sanitized_content,
            raise_on_failure=False,
            custom_offsets=[46, -46],
        )
        repair_method = str(method or "").strip()
        accepted_content = ""
        if repair_method and repair_method != "original":
            accepted_content = str(fixed_content or "").strip()
        elif sanitized_content != content:
            accepted_content = sanitized_content
            repair_method = "control_char_cleanup"

        if not accepted_content:
            repaired_lines.append(line)
            continue

        repaired_count += 1
        method_counts[repair_method] = int(method_counts.get(repair_method, 0)) + 1
        repaired_lines.append(f"{prefix}{accepted_content}{line_ending}")

    repaired_markdown = "".join(repaired_lines)
    summary = {
        "garbled_block_repair_applied": bool(repaired_count > 0),
        "repaired_garbled_block_count": int(repaired_count),
        "garbled_repair_methods": sorted(method_counts),
        "garbled_repair_method_counts": dict(method_counts),
    }
    return repaired_markdown, summary


def _apply_semantic_canonicalization(
    ordered_chapters: list[ChapterMarkdownEntry],
) -> tuple[list[ChapterMarkdownEntry], dict[str, Any]]:
    normalized: list[ChapterMarkdownEntry] = []
    affected_files: list[str] = []
    collapsed_total = 0
    garbled_repair_total = 0
    garbled_repair_files: list[str] = []
    garbled_method_counts: dict[str, int] = {}

    for chapter in ordered_chapters:
        repaired_markdown, repair_summary = _repair_garbled_markdown_blocks(chapter.markdown_text)
        canonical_markdown, collapsed_count = _canonicalize_adjacent_duplicate_paragraphs(repaired_markdown)
        collapsed_total += int(collapsed_count or 0)
        repaired_count = int(repair_summary.get("repaired_garbled_block_count") or 0)
        garbled_repair_total += repaired_count
        if repaired_count > 0:
            garbled_repair_files.append(str(chapter.path or "").strip() or str(chapter.chapter_id or "").strip())
        for method_name, count in dict(repair_summary.get("garbled_repair_method_counts") or {}).items():
            method_key = str(method_name or "").strip()
            if not method_key:
                continue
            garbled_method_counts[method_key] = int(garbled_method_counts.get(method_key, 0)) + int(count or 0)
        if collapsed_count > 0:
            affected_files.append(str(chapter.path or "").strip() or str(chapter.chapter_id or "").strip())
        chapter_markdown = str(chapter.markdown_text or "")
        if repaired_count > 0 or collapsed_count > 0:
            chapter_markdown = canonical_markdown
        normalized.append(
            ChapterMarkdownEntry(
                order=int(chapter.order or 0),
                chapter_id=str(chapter.chapter_id or ""),
                title=str(chapter.title or ""),
                path=str(chapter.path or ""),
                markdown_text=chapter_markdown,
                start_page=int(chapter.start_page or 0),
                end_page=int(chapter.end_page or int(chapter.start_page or 0)),
                pages=[int(page_no) for page_no in list(chapter.pages or []) if int(page_no) > 0],
            )
        )

    summary = {
        "canonicalization_applied": bool(collapsed_total > 0),
        "collapsed_duplicate_paragraph_count": int(collapsed_total),
        "affected_file_count": len(affected_files),
        "affected_files_preview": affected_files[:12],
        "garbled_block_repair_applied": bool(garbled_repair_total > 0),
        "repaired_garbled_block_count": int(garbled_repair_total),
        "garbled_repair_file_count": len(garbled_repair_files),
        "garbled_repair_files_preview": garbled_repair_files[:12],
        "garbled_repair_methods": sorted(garbled_method_counts),
        "garbled_repair_method_counts": dict(garbled_method_counts),
    }
    return normalized, summary


def build_export_bundle(
    chapter_markdown_set: ChapterMarkdownSet,
    toc_structure: TocStructure,
    *,
    slug: str = "",
    doc_id: str = "",
) -> ModuleResult[ExportBundle]:
    ordered_chapters, missing_chapter_ids, extra_chapter_ids = _reorder_chapters(chapter_markdown_set, toc_structure)
    canonicalized_chapters, canonicalization_summary = _apply_semantic_canonicalization(ordered_chapters)
    export_chapters = _to_export_chapter_records(canonicalized_chapters)
    chapter_files = {
        str(row.path or ""): export_stage._normalize_markdown_content(str(row.content or ""))
        for row in export_chapters
        if str(row.path or "").strip()
    }
    files = dict(chapter_files)
    if export_chapters:
        files["index.md"] = export_stage._build_index_markdown(export_chapters)

    semantic = export_stage._compute_export_semantic_contract(
        chapters=export_chapters,
        chapter_files=chapter_files,
    )
    bundle_record = ExportBundleRecord(
        index_path="index.md",
        chapters_dir="chapters",
        chapters=list(export_chapters),
        chapter_files=dict(chapter_files),
        files=dict(files),
        export_semantic_contract_ok=bool(semantic.get("export_semantic_contract_ok", True)),
        front_matter_leak_detected=bool(semantic.get("front_matter_leak_detected", False)),
        toc_residue_detected=bool(semantic.get("toc_residue_detected", False)),
        mid_paragraph_heading_detected=bool(semantic.get("mid_paragraph_heading_detected", False)),
        duplicate_paragraph_detected=bool(semantic.get("duplicate_paragraph_detected", False)),
    )
    zip_bytes = export_stage.build_export_zip(bundle_record)

    container_titles, post_body_titles, back_matter_titles, toc_role_summary = _toc_titles_and_summary(toc_structure)
    phase6 = Phase6Structure(
        export_bundle=bundle_record,
        status=StructureStatusRecord(structure_state="done"),
        summary=Phase6Summary(
            container_titles=container_titles,
            post_body_titles=post_body_titles,
            back_matter_titles=back_matter_titles,
            toc_role_summary=toc_role_summary,
        ),
    )
    report_record, audit_summary = audit_phase6_export(
        phase6,
        slug=str(slug or ""),
        zip_bytes=None,
    )
    report = _to_export_audit_report(report_record)
    audit_issue_file_summary = [
        {
            "path": str(file_row.path or ""),
            "issue_codes": [str(code).strip() for code in list(file_row.issue_codes or []) if str(code).strip()],
        }
        for file_row in report.files
        if list(file_row.issue_codes or [])
    ][:24]

    toc_order_ids = [str(row.chapter_id or "") for row in toc_structure.chapters if str(row.chapter_id or "").strip()]
    exported_ids = [str(row.chapter_id or "") for row in canonicalized_chapters if str(row.chapter_id or "").strip()]
    exported_toc_ids = [chapter_id for chapter_id in exported_ids if chapter_id in set(toc_order_ids)]
    order_follows_toc = (
        len(missing_chapter_ids) == 0
        and len(extra_chapter_ids) == 0
        and exported_toc_ids == toc_order_ids
    )
    no_cross_chapter_contamination = all(
        "chapter_boundary_swallow_next" not in set(file_row.issue_codes or [])
        for file_row in report.files
    )
    no_raw_marker_leak_book_level = (
        not _has_book_level_raw_marker_leak(chapter_files)
        and all(
            "raw_note_marker_leak" not in set(file_row.issue_codes or [])
            and "legacy_note_token_leak" not in set(file_row.issue_codes or [])
            for file_row in report.files
        )
    )

    hard = {
        "export.order_follows_toc": bool(order_follows_toc),
        "export.semantic_contract_ok": bool(bundle_record.export_semantic_contract_ok),
        "export.audit_can_ship": bool(report.can_ship),
        "export.no_cross_chapter_contamination": bool(no_cross_chapter_contamination),
        "export.no_raw_marker_leak_book_level": bool(no_raw_marker_leak_book_level),
    }
    reasons: list[str] = []
    if not hard["export.order_follows_toc"]:
        reasons.append("export_order_not_follow_toc")
    if not hard["export.semantic_contract_ok"]:
        reasons.append("export_semantic_contract_broken")
    if not hard["export.audit_can_ship"]:
        reasons.append("export_audit_blocking")
    if not hard["export.no_cross_chapter_contamination"]:
        reasons.append("export_cross_chapter_contamination")
    if not hard["export.no_raw_marker_leak_book_level"]:
        reasons.append("export_raw_marker_leak")

    semantic_summary = {
        "chapter_count": len(export_chapters),
        "chapter_file_count": len(chapter_files),
        "file_count": len(files),
        "missing_chapter_ids": list(missing_chapter_ids),
        "extra_chapter_ids": list(extra_chapter_ids),
        **dict(canonicalization_summary),
        **dict(semantic or {}),
        **dict(audit_summary.get("export_audit_summary") or {}),
    }
    evidence = {
        "semantic_summary": dict(semantic_summary),
        "toc_role_summary": dict(toc_role_summary),
    }
    gate_report = GateReport(
        module="export",
        hard=hard,
        soft={},
        reasons=reasons,
        evidence=evidence,
        overrides_used=[],
    )
    data = ExportBundle(
        index_markdown=str(files.get("index.md") or ""),
        chapters=canonicalized_chapters,
        chapter_files=chapter_files,
        files=files,
        zip_bytes=zip_bytes,
        audit_report=report,
        semantic_summary=semantic_summary,
    )
    return ModuleResult(
        data=data,
        gate_report=gate_report,
        evidence=evidence,
        overrides_used=[],
        diagnostics={
            "audit_blocking_issue_count": int(report.blocking_issue_count or 0),
            "canonicalization_summary": dict(canonicalization_summary),
            "audit_issue_file_summary": audit_issue_file_summary,
        },
    )

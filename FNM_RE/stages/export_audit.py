"""FNM_RE 第六阶段：导出审计。"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from typing import Any

from FNM_RE.models import (
    ExportAuditFileRecord,
    ExportAuditReportRecord,
    ExportChapterRecord,
    Phase6Structure,
)

LOCAL_REF_RE = re.compile(r"\[\^([0-9]+)\]")
LOCAL_DEF_RE = re.compile(r"^\[\^([0-9]+)\]:", re.MULTILINE)
SECTION_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s*(.+?)\s*$", re.MULTILINE)
RAW_BRACKET_NOTE_REF_RE = re.compile(r"(?<!\d)\[(\d{1,4}[A-Za-z]?)\](?!\d)")
RAW_SUPERSCRIPT_NOTE_REF_RE = re.compile(
    r"\$\s*\^\{\s*\[?(\d{1,4}[A-Za-z]?)\]?\s*\}\s*\$"
    r"|<sup>\s*\[?(\d{1,4}[A-Za-z]?)\]?\s*</sup>"
    r"|([⁰¹²³⁴⁵⁶⁷⁸⁹]+)",
    re.IGNORECASE,
)
LEGACY_FOOTNOTE_RE = re.compile(r"\[FN-[^\]]+\]", re.IGNORECASE)
LEGACY_ENDNOTE_RE = re.compile(r"\[\^en-[^\]]+\]", re.IGNORECASE)
LEGACY_EN_BRACKET_RE = re.compile(r"\[EN-[^\]]+\]", re.IGNORECASE)
LEGACY_NOTE_TOKEN_RE = re.compile(r"\{\{(?:NOTE_REF|FN_REF|EN_REF):[^}]+\}\}", re.IGNORECASE)
TOC_LINE_RE = re.compile(r"(?im)^\s*.+\.{3,}\s*\d+\s*$")
TOC_HEADING_RE = re.compile(r"(?im)^\s*(?:table of contents|contents|table des mati[eè]res|sommaire|目录)\b")
FRONT_MATTER_TEXT_RE = re.compile(
    r"\b(?:copyright|all rights reserved|printed in|library of congress|isbn|gallimard|seuil|routledge introductions?)\b",
    re.IGNORECASE,
)
BACK_MATTER_TEXT_RE = re.compile(
    r"\b(?:bibliograph(?:y|ie)|index(?: des?| historique)?|glossary|works cited|references?)\b",
    re.IGNORECASE,
)
_LEADING_RAW_NOTE_MARKER_RE = re.compile(
    r"^\s*(?:\[\d{1,4}[A-Za-z]?\]|\(\d{1,4}[A-Za-z]?\)|\d{1,4}[A-Za-z]?[.)]|<sup>\s*\d{1,4}[A-Za-z]?\s*</sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)\s+",
    re.IGNORECASE,
)
_LOCAL_DEF_LINE_RE = re.compile(r"^\s*\[\^[^\]]+\]:")

ISSUE_SEVERITY = {
    "wrong_title": "blocking",
    "mid_sentence_opening": "major",
    "front_matter_leak": "blocking",
    "back_matter_leak": "major",
    "toc_residue": "blocking",
    "raw_note_marker_leak": "blocking",
    "legacy_note_token_leak": "blocking",
    "local_note_contract_broken": "blocking",
    "missing_note_definition": "blocking",
    "orphan_note_definition": "blocking",
    "mid_paragraph_heading": "major",
    "duplicated_heading": "major",
    "duplicate_paragraph": "major",
    "chapter_boundary_swallow_next": "blocking",
    "chapter_boundary_missing_tail": "major",
    "semantic_role_mismatch": "blocking",
    "manual_toc_mismatch": "blocking",
    "toc_organization_mismatch": "blocking",
    "missing_post_body_export": "blocking",
    "container_exported_as_chapter": "blocking",
    "export_depth_too_shallow": "blocking",
}
_SEVERITY_RANK = {"blocking": 3, "major": 2, "minor": 1}
_UNICODE_SUPERSCRIPT_TRANSLATION = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def _numeric_first_sort_key(value: str) -> tuple[int, int | str]:
    text = str(value or "").strip()
    if text.isdigit():
        return (0, int(text))
    return (1, text)


def _normalize_title_key(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text or "").strip().lower())


def split_body_and_definitions(content: str) -> tuple[str, str]:
    body_lines: list[str] = []
    definition_lines: list[str] = []
    in_definition_block = False
    for raw_line in str(content or "").splitlines():
        if LOCAL_DEF_RE.match(raw_line):
            in_definition_block = True
            definition_lines.append(raw_line)
            continue
        if in_definition_block and (raw_line.startswith("    ") or raw_line.startswith("\t")):
            definition_lines.append(raw_line)
            continue
        in_definition_block = False
        body_lines.append(raw_line)
    return "\n".join(body_lines), "\n".join(definition_lines)


def body_paragraphs(content: str) -> list[str]:
    body_text, _ = split_body_and_definitions(content)
    paragraphs: list[str] = []
    for chunk in re.split(r"\n\s*\n+", body_text):
        text = str(chunk or "").strip()
        if not text or text.startswith("#"):
            continue
        paragraphs.append(text)
    return paragraphs


def definition_lines(content: str) -> list[str]:
    _body, definition = split_body_and_definitions(content)
    return [line.rstrip() for line in definition.splitlines() if line.strip()]


def _file_title_from_content(content: str) -> str:
    for raw_line in str(content or "").splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        match = HEADING_RE.match(line)
        if match:
            return str(match.group(2) or "").strip()
        return line
    return ""


def _looks_like_mid_sentence_opening(paragraph: str) -> bool:
    text = str(paragraph or "").strip()
    if not text:
        return False
    if text.startswith(("[^", "(", "[", "\"", "“", "«")):
        return False
    if re.match(r"^[a-zà-ÿ]", text):
        return True
    if text.startswith(("and ", "or ", "but ", "et ", "ou ", "mais ")):
        return True
    return False


def _looks_like_bibliography_entry(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    if not normalized:
        return False
    if not re.search(r"\b\d{4}\.?\s*$", normalized):
        return False
    return bool(re.search(r":\s*[^:]{6,},\s*\d{4}\.?\s*$", normalized))


def _looks_like_missing_tail(paragraph: str) -> bool:
    text = re.sub(r"\[\^[0-9]+\]", "", str(paragraph or "").strip()).strip()
    if len(text) < 60:
        return False
    if _looks_like_bibliography_entry(text):
        return False
    text = re.sub(r"\s*\(\s*fin du m(?:s|anuscrit)\.?\s*\)\s*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*\*\s*$", "", text).strip()
    return not text.endswith((".", "!", "?", "。", "！", "？", "”", "\"", "»"))


def _detect_mid_paragraph_heading(body_text: str) -> bool:
    lines = str(body_text or "").splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("### "):
            continue
        prev = lines[idx - 1].strip() if idx > 0 else ""
        if prev and not prev.startswith("#"):
            return True
    return False


def _duplicate_heading_count(body_text: str) -> int:
    counts: dict[str, int] = {}
    for match in SECTION_HEADING_RE.finditer(str(body_text or "")):
        title = re.sub(r"\s+", " ", str(match.group(1) or "").strip()).strip().lower()
        if not title:
            continue
        counts[title] = counts.get(title, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _duplicate_paragraph_count(paragraphs: list[str]) -> int:
    counts: dict[str, int] = {}
    for paragraph in paragraphs:
        normalized = re.sub(r"\[\^[0-9]+\]", "", re.sub(r"\s+", " ", paragraph).strip().lower()).strip()
        if len(normalized) < 60:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _contains_other_chapter_heading(content: str, title: str, chapter_titles: list[str]) -> bool:
    current_key = _normalize_title_key(title)
    ordered_titles = [
        str(item or "").strip()
        for item in (chapter_titles or [])
        if _normalize_title_key(item)
    ]
    current_index = next(
        (
            index
            for index, item in enumerate(ordered_titles)
            if _normalize_title_key(item) == current_key
        ),
        -1,
    )
    if current_index < 0 or current_index >= len(ordered_titles) - 1:
        return False
    next_title_key = _normalize_title_key(ordered_titles[current_index + 1])
    if not next_title_key:
        return False
    for raw_line in str(content or "").splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        heading_match = HEADING_RE.match(line)
        if not heading_match:
            continue
        key = _normalize_title_key(str(heading_match.group(2) or "").strip())
        if key == next_title_key:
            return True
    return False


def _iter_raw_note_marker_hits(
    text: str,
    *,
    allowed_markers: set[str] | None = None,
) -> list[str]:
    cleaned_text = str(text or "")
    explicit_hits: list[str] = []
    allowed = None
    if allowed_markers is not None:
        allowed = {
            _normalize_title_key(value)
            for value in allowed_markers
            if _normalize_title_key(value)
        }
    for match in RAW_BRACKET_NOTE_REF_RE.finditer(cleaned_text):
        marker = str(match.group(1) or "").strip()
        if not marker:
            continue
        marker_key = _normalize_title_key(marker)
        if allowed is not None and marker_key not in allowed:
            continue
        explicit_hits.append(marker)
    return explicit_hits


def _iter_raw_superscript_note_marker_hits(
    text: str,
    *,
    allowed_markers: set[str] | None = None,
) -> list[str]:
    cleaned_text = str(text or "")
    explicit_sup_hits: list[str] = []
    allowed = None
    if allowed_markers is not None:
        allowed = {
            _normalize_title_key(value)
            for value in allowed_markers
            if _normalize_title_key(value)
        }
    for match in RAW_SUPERSCRIPT_NOTE_REF_RE.finditer(cleaned_text):
        marker = str(match.group(1) or match.group(2) or "").strip()
        if not marker:
            marker = str(match.group(3) or "").translate(_UNICODE_SUPERSCRIPT_TRANSLATION).strip()
        if not marker:
            continue
        marker_key = _normalize_title_key(marker)
        if allowed is not None and marker_key not in allowed:
            continue
        explicit_sup_hits.append(marker)
    return explicit_sup_hits


def _definition_has_raw_note_marker(
    definition_text: str,
    *,
    allowed_markers: set[str] | None = None,
) -> bool:
    """只判定定义块里有没有"行首裸标记"形式的未转换定义标签。

    定义正文（脚注/尾注 body）里出现的上标、方括号数字、圆括号数字等可能是
    档案编号、古籍叶码、嵌套引用等合法散文内容，不视为漏转。
    """
    del allowed_markers
    if not str(definition_text or "").strip():
        return False
    for line in str(definition_text or "").splitlines():
        stripped = str(line or "").strip()
        if not stripped:
            continue
        if _LOCAL_DEF_LINE_RE.match(stripped):
            continue
        if _LEADING_RAW_NOTE_MARKER_RE.match(stripped):
            return True
    return False


def _add_issue(issue_codes: list[str], issue_summary: list[str], code: str, detail: str = "") -> None:
    if code in issue_codes:
        return
    issue_codes.append(code)
    issue_summary.append(f"{code}: {detail}".strip(": "))


def audit_markdown_file(
    *,
    path: str,
    title: str,
    content: str,
    chapter_titles: list[str],
    expected_role: str,
    expected_title: str,
    page_span: list[int] | None = None,
    manual_toc_titles: list[str] | None = None,
    chapter_note_markers: set[str] | None = None,
) -> ExportAuditFileRecord:
    raw_text = str(content or "")
    body_text, definition_text = split_body_and_definitions(raw_text)
    paragraphs = body_paragraphs(raw_text)
    definitions = definition_lines(raw_text)
    refs = sorted(set(LOCAL_REF_RE.findall(body_text)), key=_numeric_first_sort_key)
    defs = sorted(set(LOCAL_DEF_RE.findall(raw_text)), key=_numeric_first_sort_key)
    file_title = _file_title_from_content(raw_text)
    issue_codes: list[str] = []
    issue_summary: list[str] = []
    normalized_role = str(expected_role or "").strip()

    if normalized_role == "index_file":
        return ExportAuditFileRecord(
            path=str(path or "").strip(),
            title=str(expected_title or title or file_title or "").strip(),
            page_span=list(page_span or []),
            issue_codes=[],
            issue_summary=[],
            severity="minor",
            sample_opening=paragraphs[0][:280] if paragraphs else "",
            sample_mid=paragraphs[len(paragraphs) // 2][:280] if paragraphs else "",
            sample_tail=paragraphs[-1][:280] if paragraphs else "",
            footnote_endnote_summary={
                "body_ref_count": len(refs),
                "definition_count": len(defs),
                "missing_definition_markers": [],
                "orphan_definition_markers": [],
                "raw_note_marker_count": 0,
                "legacy_token_count": 0,
                "definition_lines_preview": definitions[:6],
            },
        )

    if expected_title and _normalize_title_key(file_title) != _normalize_title_key(expected_title):
        _add_issue(issue_codes, issue_summary, "wrong_title", f"{file_title} != {expected_title}")
    if normalized_role in {"container", "back_matter"}:
        _add_issue(issue_codes, issue_summary, "semantic_role_mismatch", normalized_role)
    if manual_toc_titles:
        manual_keys = {_normalize_title_key(item) for item in manual_toc_titles if _normalize_title_key(item)}
        if _normalize_title_key(expected_title) and _normalize_title_key(expected_title) not in manual_keys:
            _add_issue(issue_codes, issue_summary, "manual_toc_mismatch", expected_title)
    if paragraphs and _looks_like_mid_sentence_opening(paragraphs[0]):
        _add_issue(issue_codes, issue_summary, "mid_sentence_opening", paragraphs[0][:120])
    if FRONT_MATTER_TEXT_RE.search("\n".join(paragraphs[:2])) and normalized_role == "chapter":
        _add_issue(issue_codes, issue_summary, "front_matter_leak", paragraphs[0][:120] if paragraphs else "")
    if BACK_MATTER_TEXT_RE.search("\n".join(paragraphs[:2])) and normalized_role == "chapter":
        _add_issue(issue_codes, issue_summary, "back_matter_leak", paragraphs[0][:120] if paragraphs else "")
    if TOC_HEADING_RE.search(raw_text) or TOC_LINE_RE.search(raw_text):
        _add_issue(issue_codes, issue_summary, "toc_residue", "detected")

    raw_note_hits = _iter_raw_note_marker_hits(body_text, allowed_markers=chapter_note_markers)
    raw_superscript_hits = _iter_raw_superscript_note_marker_hits(body_text, allowed_markers=chapter_note_markers)
    definition_raw_note_leak = _definition_has_raw_note_marker(
        definition_text,
        allowed_markers=chapter_note_markers,
    )
    if raw_note_hits or raw_superscript_hits or definition_raw_note_leak:
        _add_issue(issue_codes, issue_summary, "raw_note_marker_leak", "detected")
    if any(pattern.search(raw_text) for pattern in (LEGACY_FOOTNOTE_RE, LEGACY_ENDNOTE_RE, LEGACY_EN_BRACKET_RE, LEGACY_NOTE_TOKEN_RE)):
        _add_issue(issue_codes, issue_summary, "legacy_note_token_leak", "detected")

    missing_defs = sorted(set(refs) - set(defs), key=_numeric_first_sort_key)
    orphan_defs = sorted(set(defs) - set(refs), key=_numeric_first_sort_key)
    if missing_defs:
        _add_issue(issue_codes, issue_summary, "missing_note_definition", ",".join(missing_defs[:8]))
    if orphan_defs:
        _add_issue(issue_codes, issue_summary, "orphan_note_definition", ",".join(orphan_defs[:8]))
    if missing_defs or orphan_defs:
        _add_issue(issue_codes, issue_summary, "local_note_contract_broken", "refs_defs_mismatch")

    if _detect_mid_paragraph_heading(body_text):
        _add_issue(issue_codes, issue_summary, "mid_paragraph_heading", "detected")
    if _duplicate_heading_count(body_text) > 0:
        _add_issue(issue_codes, issue_summary, "duplicated_heading", "detected")
    if _duplicate_paragraph_count(paragraphs) > 0:
        _add_issue(issue_codes, issue_summary, "duplicate_paragraph", "detected")
    if _contains_other_chapter_heading(raw_text, expected_title or title or file_title, chapter_titles):
        _add_issue(issue_codes, issue_summary, "chapter_boundary_swallow_next", "detected")
    if paragraphs and _looks_like_missing_tail(paragraphs[-1]):
        _add_issue(issue_codes, issue_summary, "chapter_boundary_missing_tail", paragraphs[-1][-120:])

    severity = "minor"
    for code in issue_codes:
        code_severity = ISSUE_SEVERITY.get(code, "minor")
        if _SEVERITY_RANK[code_severity] > _SEVERITY_RANK[severity]:
            severity = code_severity

    return ExportAuditFileRecord(
        path=str(path or "").strip(),
        title=str(expected_title or title or "").strip(),
        page_span=list(page_span or []),
        issue_codes=issue_codes,
        issue_summary=issue_summary,
        severity=severity if issue_codes else "minor",
        sample_opening=paragraphs[0][:280] if paragraphs else "",
        sample_mid=paragraphs[len(paragraphs) // 2][:280] if paragraphs else "",
        sample_tail=paragraphs[-1][:280] if paragraphs else "",
        footnote_endnote_summary={
            "body_ref_count": len(refs),
            "definition_count": len(defs),
            "missing_definition_markers": missing_defs[:8],
            "orphan_definition_markers": orphan_defs[:8],
            "raw_note_marker_count": (
                len(raw_note_hits)
                + len(raw_superscript_hits)
                + (1 if definition_raw_note_leak else 0)
            ),
            "legacy_token_count": (
                len(LEGACY_FOOTNOTE_RE.findall(raw_text))
                + len(LEGACY_ENDNOTE_RE.findall(raw_text))
                + len(LEGACY_EN_BRACKET_RE.findall(raw_text))
                + len(LEGACY_NOTE_TOKEN_RE.findall(raw_text))
            ),
            "definition_lines_preview": definitions[:6],
        },
    )


def _read_zip_markdown_files(*, zip_bytes: bytes) -> dict[str, str]:
    payload = BytesIO(zip_bytes or b"")
    with zipfile.ZipFile(payload, "r") as archive:
        return {
            name: archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.endswith(".md")
        }


def _chapter_note_markers_by_section(phase6: Phase6Structure) -> dict[str, set[str]]:
    payload: dict[str, set[str]] = {}
    for item in phase6.note_items:
        chapter_id = str(item.chapter_id or "").strip()
        if not chapter_id:
            continue
        marker_set = payload.setdefault(chapter_id, set())
        marker = _normalize_title_key(str(item.marker or ""))
        if marker:
            marker_set.add(marker)
    return payload


def _chapter_by_path(chapters: list[ExportChapterRecord]) -> dict[str, ExportChapterRecord]:
    return {
        str(chapter.path or "").strip(): chapter
        for chapter in chapters
        if str(chapter.path or "").strip()
    }


def audit_phase6_export(
    phase6: Phase6Structure,
    *,
    slug: str = "",
    zip_bytes: bytes | None = None,
) -> tuple[ExportAuditReportRecord, dict[str, Any]]:
    summary = phase6.summary
    bundle = phase6.export_bundle
    chapter_rows = list(bundle.chapters or [])
    chapter_titles = [str(chapter.title or "").strip() for chapter in chapter_rows if str(chapter.title or "").strip()]
    manual_toc_titles = (
        list(summary.container_titles or [])
        + chapter_titles
        + list(summary.post_body_titles or [])
        + list(summary.back_matter_titles or [])
    )
    role_by_title_key: dict[str, str] = {}
    for title in summary.container_titles or []:
        role_by_title_key[_normalize_title_key(title)] = "container"
    for title in summary.post_body_titles or []:
        role_by_title_key[_normalize_title_key(title)] = "post_body"
    for title in summary.back_matter_titles or []:
        role_by_title_key[_normalize_title_key(title)] = "back_matter"

    markdown_files = (
        _read_zip_markdown_files(zip_bytes=zip_bytes)
        if zip_bytes is not None
        else {
            str(path): str(content)
            for path, content in dict(bundle.files or {}).items()
            if str(path).endswith(".md")
        }
    )
    path_to_chapter = _chapter_by_path(chapter_rows)
    chapter_note_markers = _chapter_note_markers_by_section(phase6)

    file_reports: list[ExportAuditFileRecord] = []
    for path in sorted(markdown_files.keys()):
        chapter = path_to_chapter.get(path)
        content = str(markdown_files.get(path) or "")
        inferred_title = _file_title_from_content(content)
        title = str((chapter.title if chapter else inferred_title) or inferred_title).strip()
        section_id = str((chapter.section_id if chapter else "") or "").strip()
        page_span: list[int] = []
        if chapter:
            page_span = [
                int(chapter.start_page or 0),
                int(chapter.end_page or int(chapter.start_page or 0)),
            ]
        expected_role = role_by_title_key.get(_normalize_title_key(title), "chapter")
        if path == str(bundle.index_path or "index.md"):
            expected_role = "index_file"
        file_reports.append(
            audit_markdown_file(
                path=path,
                title=title,
                content=content,
                chapter_titles=chapter_titles,
                expected_role=expected_role,
                expected_title=str((chapter.title if chapter else "") or "").strip(),
                page_span=page_span,
                manual_toc_titles=manual_toc_titles,
                chapter_note_markers=set(chapter_note_markers.get(section_id) or set()),
            )
        )

    exported_title_keys = {
        _normalize_title_key(chapter.title)
        for chapter in chapter_rows
        if _normalize_title_key(chapter.title)
    }
    missing_post_body_titles = [
        str(title or "").strip()
        for title in (summary.post_body_titles or [])
        if _normalize_title_key(title) and _normalize_title_key(title) not in exported_title_keys
    ]
    if missing_post_body_titles:
        file_reports.append(
            ExportAuditFileRecord(
                path="__book__/post_body",
                title=", ".join(missing_post_body_titles),
                page_span=[],
                issue_codes=["missing_post_body_export", "toc_organization_mismatch"],
                issue_summary=[
                    f"missing_post_body_export: {', '.join(missing_post_body_titles)}",
                    "toc_organization_mismatch: post_body_titles_missing_from_export",
                ],
                severity="blocking",
                sample_opening="",
                sample_mid="",
                sample_tail="",
                footnote_endnote_summary={},
            )
        )
    exported_container_titles = [
        str(title or "").strip()
        for title in (summary.container_titles or [])
        if _normalize_title_key(title) and _normalize_title_key(title) in exported_title_keys
    ]
    if exported_container_titles:
        file_reports.append(
            ExportAuditFileRecord(
                path="__book__/container",
                title=", ".join(exported_container_titles),
                page_span=[],
                issue_codes=["container_exported_as_chapter", "toc_organization_mismatch"],
                issue_summary=[
                    f"container_exported_as_chapter: {', '.join(exported_container_titles)}",
                    "toc_organization_mismatch: container_titles_present_in_export",
                ],
                severity="blocking",
                sample_opening="",
                sample_mid="",
                sample_tail="",
                footnote_endnote_summary={},
            )
        )
    expected_export_count = int(summary.toc_role_summary.get("chapter") or 0) + int(
        summary.toc_role_summary.get("post_body") or 0
    )
    actual_export_count = len(chapter_rows)
    if expected_export_count > 0 and actual_export_count > 0 and actual_export_count < expected_export_count:
        file_reports.append(
            ExportAuditFileRecord(
                path="__book__/organization_depth",
                title=slug or "phase6",
                page_span=[],
                issue_codes=["export_depth_too_shallow", "toc_organization_mismatch"],
                issue_summary=[
                    f"export_depth_too_shallow: expected>={expected_export_count}, actual={actual_export_count}",
                    "toc_organization_mismatch: export_chapter_count_below_toc_depth",
                ],
                severity="blocking",
                sample_opening="",
                sample_mid="",
                sample_tail="",
                footnote_endnote_summary={},
            )
        )

    blocking_files = [row for row in file_reports if str(row.severity or "") == "blocking"]
    major_files = [row for row in file_reports if str(row.severity or "") == "major"]
    issue_counts: dict[str, int] = {}
    for row in file_reports:
        for code in row.issue_codes:
            issue_counts[code] = issue_counts.get(code, 0) + 1
    recommended_followups = [
        {"issue_code": code, "count": count}
        for code, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]
    report = ExportAuditReportRecord(
        slug=str(slug or "").strip(),
        doc_id=str(slug or "").strip(),
        zip_path=f"{str(slug or 'phase6_export').strip()}.zip",
        structure_state=str(phase6.status.structure_state or "").strip(),
        blocking_reasons=[str(reason).strip() for reason in phase6.status.blocking_reasons if str(reason).strip()],
        manual_toc_summary=dict(phase6.status.manual_toc_summary or {}),
        toc_role_summary=dict(summary.toc_role_summary or {}),
        chapter_titles=chapter_titles,
        files=file_reports,
        blocking_issue_count=len(blocking_files),
        major_issue_count=len(major_files),
        can_ship=len(blocking_files) == 0,
        must_fix_before_next_book=[
            {"path": str(row.path or ""), "issue_codes": list(row.issue_codes or [])}
            for row in blocking_files
        ],
        recommended_followups=recommended_followups,
    )
    audit_summary = {
        "export_audit_summary": {
            "file_count": len(file_reports),
            "blocking_issue_count": int(report.blocking_issue_count),
            "major_issue_count": int(report.major_issue_count),
            "can_ship": bool(report.can_ship),
        }
    }
    return report, audit_summary

#!/usr/bin/env python3
"""Build Obsidian exports and translation manifests from PaddleOCR-VL JSON."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from scripts.footnote_endnote_filter_prototype import (
        DEFINITION_MARKER_RE,
        MATH_REF_RE,
        MD_REF_RE,
        NOTES_HEADING_RE,
        PLAIN_DIGIT_REF_RE,
        SUPERSCRIPT_REF_RE,
        SYMBOL_REF_RE,
        body_markdown,
        build_manifest,
        normalize_marker,
    )
except ModuleNotFoundError:
    from footnote_endnote_filter_prototype import (
        DEFINITION_MARKER_RE,
        MATH_REF_RE,
        MD_REF_RE,
        NOTES_HEADING_RE,
        PLAIN_DIGIT_REF_RE,
        SUPERSCRIPT_REF_RE,
        SYMBOL_REF_RE,
        body_markdown,
        build_manifest,
        normalize_marker,
    )


@dataclass(frozen=True)
class NoteRefMaps:
    footnotes_by_page: dict[int, dict[str, str]]
    endnotes_by_marker: dict[str, str]


_BODY_BLOCK_EXCLUDED_LABELS = {
    "footnote",
    "header",
    "header_image",
    "footer",
    "footer_image",
    "number",
    "reference_content",
}
_BODY_META_LINE_PATTERNS = (
    re.compile(r"^article$", re.I),
    re.compile(r"^article\s*reuse\s*guidelines:?$", re.I),
    re.compile(r"^doi:\s*10\.", re.I),
    re.compile(r"^10\.\d{4,}/"),
    re.compile(r"sagepub\.com|journals\.sagepub|springer\.com|wiley\.com", re.I),
    re.compile(r"^sage$", re.I),
    re.compile(r"^©"),
    re.compile(r"^history of psychiatry\b", re.I),
)


def load_pages(input_json: Path) -> list[dict]:
    return json.loads(input_json.read_text())


def strip_definition_marker(text: str) -> str:
    return DEFINITION_MARKER_RE.sub("", text, count=1).strip()


def _page_markdown_text(page: dict) -> str:
    markdown = page.get("markdown")
    if isinstance(markdown, dict):
        return str(markdown.get("text") or "")
    if isinstance(markdown, str):
        return markdown
    return ""


def _page_blocks(page: dict) -> list[dict]:
    blocks = (page.get("prunedResult") or {}).get("parsing_res_list") or []
    return sorted(
        blocks,
        key=lambda block: (
            block.get("block_order", 10**9),
            (block.get("block_bbox") or [0, 0, 0, 0])[1],
            (block.get("block_bbox") or [0, 0, 0, 0])[0],
        ),
    )


def _is_body_meta_line(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return True
    for pattern in _BODY_META_LINE_PATTERNS:
        if pattern.search(stripped):
            return True
    return False


def _normalize_body_block(block: dict) -> str:
    label = str(block.get("block_label") or "").strip().lower()
    if label in _BODY_BLOCK_EXCLUDED_LABELS:
        return ""
    raw = str(block.get("block_content") or "").strip()
    if not raw:
        return ""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return ""
    if label == "doc_title":
        return f"# {' '.join(lines)}".strip()
    if label == "paragraph_title":
        return f"## {' '.join(lines)}".strip()
    kept_lines = [line for line in lines if not _is_body_meta_line(line)]
    if not kept_lines:
        return ""
    return "\n".join(kept_lines).strip()


def _build_body_text_from_blocks(page: dict) -> str:
    parts: list[str] = []
    for block in _page_blocks(page):
        normalized = _normalize_body_block(block)
        if normalized:
            parts.append(normalized)
    return "\n\n".join(parts).strip()


def body_markdown_for_render(page: dict) -> str:
    block_text = _build_body_text_from_blocks(page)
    if block_text:
        return block_text
    return body_markdown(page).strip()


def alpha_index(value: int) -> str:
    value += 1
    letters: list[str] = []
    while value > 0:
        value -= 1
        value, rem = divmod(value, 26)
        letters.append(chr(ord("a") + rem))
    return "".join(reversed(letters))


def obsidian_footnote_ref(note_id: str) -> str:
    return f"[^{note_id}]"


def obsidian_endnote_ref(note_id: str, marker: str) -> str:
    return f"[E{marker}](#{note_id})"


def frozen_footnote_ref(note_id: str) -> str:
    return f"{{{{FN_REF:{note_id}}}}}"


def frozen_endnote_ref(note_id: str) -> str:
    return f"{{{{EN_REF:{note_id}}}}}"


def build_note_maps(section: dict) -> NoteRefMaps:
    footnotes_by_page: dict[int, dict[str, str]] = {}
    for note in section["footnotes"]:
        footnotes_by_page.setdefault(note["start_page"], {})[note["original_marker"]] = note["id"]
    endnotes_by_marker = {note["original_marker"]: note["id"] for note in section["endnotes"]}
    return NoteRefMaps(
        footnotes_by_page=footnotes_by_page,
        endnotes_by_marker=endnotes_by_marker,
    )


def make_ref_resolver(
    ref_maps: NoteRefMaps,
    page_no: int,
    section: dict,
    mode: str,
) -> Callable[[str], str | None]:
    endnote_markers = {
        note["id"]: note["original_marker"]
        for note in section["endnotes"]
    }

    def resolve(marker: str) -> str | None:
        footnote_id = ref_maps.footnotes_by_page.get(page_no, {}).get(marker)
        if footnote_id:
            if mode == "obsidian":
                return obsidian_footnote_ref(footnote_id)
            if mode == "frozen":
                return frozen_footnote_ref(footnote_id)
            raise ValueError(f"Unsupported mode: {mode}")

        endnote_id = ref_maps.endnotes_by_marker.get(marker)
        if endnote_id:
            if mode == "obsidian":
                return obsidian_endnote_ref(endnote_id, endnote_markers[endnote_id])
            if mode == "frozen":
                return frozen_endnote_ref(endnote_id)
            raise ValueError(f"Unsupported mode: {mode}")

        return None

    return resolve


def rewrite_body_refs(text: str, resolver: Callable[[str], str | None]) -> str:
    replacements: dict[str, str] = {}
    placeholder_index = 0

    def stash(value: str) -> str:
        nonlocal placeholder_index
        key = f"__NOTE_REF_{alpha_index(placeholder_index)}__"
        placeholder_index += 1
        replacements[key] = value
        return key

    def rewrite_pattern(
        current_text: str,
        pattern: re.Pattern[str],
        marker_getter: Callable[[re.Match[str]], str | None],
    ) -> str:
        def replacer(match: re.Match[str]) -> str:
            marker = marker_getter(match)
            if not marker:
                return match.group(0)
            resolved = resolver(marker)
            if not resolved:
                return match.group(0)
            return stash(resolved)

        return pattern.sub(replacer, current_text)

    text = rewrite_pattern(text, MD_REF_RE, lambda m: normalize_marker(m.group(1)))
    text = rewrite_pattern(text, MATH_REF_RE, lambda m: normalize_marker(m.group(1)))
    text = rewrite_pattern(text, SUPERSCRIPT_REF_RE, lambda m: normalize_marker(m.group(0)))
    text = rewrite_pattern(text, PLAIN_DIGIT_REF_RE, lambda m: normalize_marker(m.group(1)))
    text = rewrite_pattern(text, SYMBOL_REF_RE, lambda m: normalize_marker(m.group(1)))

    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def strip_duplicate_section_heading(text: str, title: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines:
        first = lines[0].strip()
        if first.startswith("#") and first.lstrip("#").strip() == title:
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines.pop(0)
    return "\n".join(lines).strip()


def render_footnote_definition(note_id: str, content_text: str) -> str:
    lines = content_text.splitlines() or [""]
    rendered = [f"[^{note_id}]: {lines[0]}"]
    for line in lines[1:]:
        rendered.append(f"  {line}" if line else "  ")
    return "\n".join(rendered)


def build_rendered_sections(input_json: Path, manifest: dict | None = None) -> list[dict]:
    manifest = manifest if manifest is not None else build_manifest(input_json)
    pages = load_pages(input_json)

    rendered_sections: list[dict] = []
    for section in manifest["sections"]:
        ref_maps = build_note_maps(section)
        obsidian_pages: list[dict] = []
        frozen_pages: list[dict] = []

        for page_no in section["pages"]:
            if (
                section["endnotes_start_page"] is not None
                and page_no > section["endnotes_start_page"]
            ):
                continue
            source_text = body_markdown_for_render(pages[page_no - 1]).strip()
            if not source_text:
                continue
            resolver_obsidian = make_ref_resolver(ref_maps, page_no, section, "obsidian")
            resolver_frozen = make_ref_resolver(ref_maps, page_no, section, "frozen")
            obsidian_text = rewrite_body_refs(source_text, resolver_obsidian)
            frozen_text = rewrite_body_refs(source_text, resolver_frozen)
            obsidian_pages.append({"page_no": page_no, "text": obsidian_text})
            frozen_pages.append({"page_no": page_no, "text": frozen_text})

        rendered_sections.append(
            {
                "section_id": section["section_id"],
                "title": section["title"],
                "start_page": section["start_page"],
                "end_page": section["end_page"],
                "pages": section["pages"],
                "endnotes_start_page": section["endnotes_start_page"],
                # Module 2: 传递 section_kind
                "section_kind": section.get("section_kind", "body"),
                "obsidian_body_pages": obsidian_pages,
                "frozen_body_pages": frozen_pages,
                "obsidian_body_markdown": "\n\n".join(page["text"] for page in obsidian_pages),
                "frozen_body_markdown": "\n\n".join(page["text"] for page in frozen_pages),
                "footnotes": [
                    {
                        **note,
                        "content_text": strip_definition_marker(note["text"]),
                        "obsidian_ref": obsidian_footnote_ref(note["id"]),
                        "frozen_ref": frozen_footnote_ref(note["id"]),
                    }
                    for note in section["footnotes"]
                ],
                "endnotes": [
                    {
                        **note,
                        "content_text": strip_definition_marker(note["text"]),
                        "obsidian_ref": obsidian_endnote_ref(note["id"], note["original_marker"]),
                        "frozen_ref": frozen_endnote_ref(note["id"]),
                    }
                    for note in section["endnotes"]
                ],
            }
        )

    return rendered_sections


def build_obsidian_markdown(input_json: Path) -> str:
    sections = build_rendered_sections(input_json)
    title = input_json.stem.replace("_by_PaddleOCR-VL-1.5", "")
    lines = [
        f"<!-- Generated from {input_json.name} -->",
        f"# {title}",
    ]

    for section in sections:
        lines.extend(
            [
                "",
                "---",
                "",
                f"## {section['title']}",
                "",
                f"<!-- pages {section['start_page']}-{section['end_page']} -->",
                "",
                section["obsidian_body_markdown"].strip(),
            ]
        )

        if section["endnotes"]:
            lines.extend(["", "### Endnotes", ""])
            for note in section["endnotes"]:
                lines.extend(
                    [
                        f"#### {note['id'].upper()}",
                        "",
                        note["content_text"],
                        "",
                    ]
                )

        if section["footnotes"]:
            lines.extend(
                [
                    "",
                    f"<!-- Obsidian footnote definitions for {section['section_id']} -->",
                    "",
                ]
            )
            for note in section["footnotes"]:
                lines.append(render_footnote_definition(note["id"], note["content_text"]))

    return "\n".join(lines).strip() + "\n"


def chunk_body_pages(body_pages: list[dict], max_chars: int) -> list[dict]:
    chunks: list[dict] = []
    current_parts: list[str] = []
    current_start: int | None = None
    current_end: int | None = None
    current_chars = 0

    def flush() -> None:
        nonlocal current_parts, current_start, current_end, current_chars
        if not current_parts:
            return
        chunks.append(
            {
                "page_start": current_start,
                "page_end": current_end,
                "source_text": "\n\n".join(current_parts),
                "char_count": current_chars,
            }
        )
        current_parts = []
        current_start = None
        current_end = None
        current_chars = 0

    for page in body_pages:
        page_no = page["page_no"]
        for paragraph in split_paragraphs(page["text"]):
            paragraph_len = len(paragraph)
            projected = current_chars + (2 if current_parts else 0) + paragraph_len
            if current_parts and projected > max_chars:
                flush()
            if current_start is None:
                current_start = page_no
            current_end = page_no
            if current_parts:
                current_chars += 2
            current_parts.append(paragraph)
            current_chars += paragraph_len

    flush()
    return chunks


def build_translation_manifest(input_json: Path, max_body_chars: int = 6000) -> dict:
    sections = build_rendered_sections(input_json)
    source_basename = input_json.stem.replace("_by_PaddleOCR-VL-1.5", "")
    manifest: dict = {
        "document_id": source_basename,
        "source_json": str(input_json),
        "max_body_chars": max_body_chars,
        "section_count": len(sections),
        "sections": [],
        "translation_units": [],
    }
    
    # Module 2: 非正文 section 不生成 body 翻译单元
    # book_end_notes, bibliography, index 等只作为注释定义来源
    _SKIP_BODY_SECTION_KINDS = {"book_end_notes", "bibliography", "index"}

    for section in sections:
        section_kind = section.get("section_kind", "body")
        skip_body = section_kind in _SKIP_BODY_SECTION_KINDS
        
        body_chunks = [] if skip_body else chunk_body_pages(section["frozen_body_pages"], max_body_chars)
        section_entry = {
            "section_id": section["section_id"],
            "title": section["title"],
            "start_page": section["start_page"],
            "end_page": section["end_page"],
            "endnotes_start_page": section["endnotes_start_page"],
            "section_kind": section_kind,
            "body_chunk_ids": [],
            "footnote_ids": [note["id"] for note in section["footnotes"]],
            "endnote_ids": [note["id"] for note in section["endnotes"]],
        }

        for chunk_index, chunk in enumerate(body_chunks, start=1):
            unit_id = f"body-{section['section_id']}-{chunk_index:04d}"
            section_entry["body_chunk_ids"].append(unit_id)
            manifest["translation_units"].append(
                {
                    "unit_id": unit_id,
                    "kind": "body",
                    "section_id": section["section_id"],
                    "title": section["title"],
                    "page_start": chunk["page_start"],
                    "page_end": chunk["page_end"],
                    "char_count": chunk["char_count"],
                    "source_text": chunk["source_text"],
                }
            )

        for note in section["footnotes"]:
            manifest["translation_units"].append(
                {
                    "unit_id": f"footnote-{note['id']}",
                    "kind": "footnote",
                    "section_id": section["section_id"],
                    "note_id": note["id"],
                    "original_marker": note["original_marker"],
                    "page_start": note["start_page"],
                    "page_end": note["pages"][-1] if note["pages"] else note["start_page"],
                    "char_count": len(note["content_text"]),
                    "source_text": note["content_text"],
                    "target_ref": note["frozen_ref"],
                }
            )

        for note in section["endnotes"]:
            manifest["translation_units"].append(
                {
                    "unit_id": f"endnote-{note['id']}",
                    "kind": "endnote",
                    "section_id": section["section_id"],
                    "note_id": note["id"],
                    "original_marker": note["original_marker"],
                    "page_start": note["start_page"],
                    "page_end": note["pages"][-1] if note["pages"] else note["start_page"],
                    "char_count": len(note["content_text"]),
                    "source_text": note["content_text"],
                    "target_ref": note["frozen_ref"],
                }
            )

        manifest["sections"].append(section_entry)

    return manifest


def default_obsidian_output(input_json: Path) -> Path:
    basename = input_json.stem.replace("_by_PaddleOCR-VL-1.5", "")
    return Path("output/obsidian") / f"{basename}.obsidian.md"


def default_translation_output(input_json: Path) -> Path:
    basename = input_json.stem.replace("_by_PaddleOCR-VL-1.5", "")
    return Path("output/translation") / f"{basename}.translation_manifest.json"


def write_text_output(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def write_json_output(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path

#!/usr/bin/env python3
"""生成并核对 FNM 段落级语义底本。

底本只从 ``golden_exports/real_golden_template`` 生成。每行保存一个可直接
回溯的真实段落，比较时可以逐章流式读取，不把整本书作为单个 JSON 对象加载。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "fnm-semantic-golden-v1"
BOOKS = {
    "Biopolitics": {
        "folder": "Biopolitics",
        "doc_id": "0d285c0800db",
    },
    "Goldstein": {
        "folder": "post-revolutionary",
        "doc_id": "7ba9bca783fd",
    },
}
INLINE_REF_RE = re.compile(r"\[\^([^\]]+)\](?!\s*:)")
DEFINITION_RE = re.compile(r"^\[\^([^\]]+)\]:", re.MULTILINE)
NOTES_HEADING_RE = re.compile(r"^#{2,6}\s+NOTES\s*$", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
TRANSLATION_PLACEHOLDER_RE = re.compile(r"^\[\s*待翻译\s*\]$")


def _book_paths(slug: str) -> tuple[Path, Path, Path]:
    config = BOOKS[slug]
    example_dir = REPO_ROOT / "test_example" / str(config["folder"])
    template_dir = example_dir / "golden_exports" / "real_golden_template"
    manifest_path = example_dir / "golden_exports" / "semantic_golden_v1.jsonl"
    db_path = REPO_ROOT / "local_data" / "user_data" / "data" / "documents" / str(config["doc_id"]) / "doc.db"
    return template_dir, manifest_path, db_path


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_comparable_text(text: str) -> str:
    """规范化可容忍的重音/空白差异，并将 marker 独立出文本比较。"""
    text = DEFINITION_RE.sub("[^]:", text)
    text = INLINE_REF_RE.sub("", text)
    text = _strip_accents(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(text: str) -> str:
    text = _strip_accents(text).casefold()
    return re.sub(r"[^\w]+", " ", text).strip()


def _paragraph_kind(text: str) -> str:
    first_line = text.splitlines()[0].strip() if text.strip() else ""
    if NOTES_HEADING_RE.match(first_line):
        return "notes_heading"
    if DEFINITION_RE.match(first_line):
        return "note_definition"
    if HEADING_RE.match(first_line):
        return "heading"
    return "body"


def parse_markdown_paragraphs(
    text: str,
    *,
    page_numbers: list[int | None] | None = None,
    source_file: str = "",
    trace: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if page_numbers is not None and len(page_numbers) != len(blocks):
        raise ValueError("page_numbers 必须与段落数量一致")
    paragraphs: list[dict[str, Any]] = []
    for ordinal, block in enumerate(blocks):
        comparable = normalize_comparable_text(block)
        refs = INLINE_REF_RE.findall(DEFINITION_RE.sub("", block))
        page_no = page_numbers[ordinal] if page_numbers is not None else None
        record: dict[str, Any] = {
            "paragraph_ordinal": ordinal,
            "kind": _paragraph_kind(block),
            "source_file": source_file,
            "source_text": block,
            "text_sha256": hashlib.sha256(comparable.encode("utf-8")).hexdigest(),
            "refs": refs,
            "ref_pages": [
                {
                    "marker": marker,
                    "page_no": page_no,
                    "method": "provided_paragraph_page" if page_no is not None else "unresolved",
                }
                for marker in refs
            ],
            "definitions": DEFINITION_RE.findall(block),
            "page_no": page_no,
        }
        if trace:
            record["actual_trace"] = trace
        paragraphs.append(record)
    return paragraphs


def _load_raw_page_text_index(template_dir: Path) -> list[tuple[int, str]]:
    raw_pages_path = template_dir.parent.parent / "raw_pages.json"
    if not raw_pages_path.exists():
        return []
    raw = json.loads(raw_pages_path.read_text(encoding="utf-8"))
    pages = raw.get("pages", []) if isinstance(raw, dict) else raw
    return [
        (
            int(page.get("bookPage") or 0),
            normalize_comparable_text(str(page.get("markdown") or "")),
        )
        for page in pages
        if int(page.get("bookPage") or 0) > 0
    ]


def _unique_context_page(context: str, pages: list[tuple[int, str]]) -> int | None:
    if len(context) < 50:
        return None
    hits = [page_no for page_no, page_text in pages if context in page_text]
    return hits[0] if len(hits) == 1 else None


def attach_reference_page_evidence(
    paragraphs: list[dict[str, Any]],
    raw_pages: list[tuple[int, str]],
) -> None:
    """用人工段落中 marker 周边正文，在原始 OCR 页中保守定位引用所在页。"""
    if not raw_pages:
        return
    for paragraph in paragraphs:
        if paragraph["kind"] != "body" or not paragraph["refs"]:
            continue
        body_text = DEFINITION_RE.sub("", paragraph["source_text"])
        evidence = []
        for match in INLINE_REF_RE.finditer(body_text):
            before = normalize_comparable_text(body_text[max(0, match.start() - 180) : match.start()])[-100:]
            after = normalize_comparable_text(body_text[match.end() : match.end() + 180])[:100]
            before_page = _unique_context_page(before, raw_pages)
            after_page = _unique_context_page(after, raw_pages)
            candidates = {page_no for page_no in (before_page, after_page) if page_no is not None}
            page_no = candidates.pop() if len(candidates) == 1 else None
            evidence.append(
                {
                    "marker": match.group(1),
                    "page_no": page_no,
                    "method": "raw_pages_context_unique" if page_no is not None else "unresolved",
                }
            )
        paragraph["ref_pages"] = evidence


def _template_markdown_files(template_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(template_dir.glob("*.md"))
        if path.name != "PROCESSING_NOTES.md"
    ]


def _source_path_for_manifest(template_dir: Path) -> str:
    try:
        return str(template_dir.relative_to(REPO_ROOT))
    except ValueError:
        return str(template_dir)


def _chapter_record(path: Path, paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    title = path.stem
    for paragraph in paragraphs:
        match = HEADING_RE.match(paragraph["source_text"].splitlines()[0])
        if match:
            title = match.group(1).strip()
            break
    return {
        "record_type": "chapter",
        "source_file": path.name,
        "chapter_key": path.stem,
        "title": title,
        "title_key": normalize_title(title),
        "paragraph_count": len(paragraphs),
    }


def build_manifest(slug: str, template_dir: Path) -> dict[str, Any]:
    """构建小规模内存对象，主要供测试和检查单章使用。CLI 写盘走流式路径。"""
    chapters = []
    for path in _template_markdown_files(template_dir):
        paragraphs = parse_markdown_paragraphs(
            path.read_text(encoding="utf-8"),
            source_file=path.name,
        )
        chapter = _chapter_record(path, paragraphs)
        chapter["paragraphs"] = paragraphs
        chapters.append(chapter)
    return {
        "schema": SCHEMA,
        "slug": slug,
        "source": {"dir": template_dir.name, "path": str(template_dir)},
        "chapters": chapters,
    }


def write_manifest(slug: str, template_dir: Path, output_path: Path) -> dict[str, Any]:
    """逐章写 JSONL；完整保存原段，失败报告无需重新猜测 expected 文本。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    source_files = _template_markdown_files(template_dir)
    raw_page_index = _load_raw_page_text_index(template_dir)
    paragraph_total = 0
    located_ref_total = 0
    ref_total = 0
    with temp_path.open("w", encoding="utf-8") as handle:
        meta = {
            "record_type": "meta",
            "schema": SCHEMA,
            "slug": slug,
            "source": {
                "dir": template_dir.name,
                "path": _source_path_for_manifest(template_dir),
                "immutable": True,
            },
            "policy": {
                "paragraph_order": "strict_1_to_1",
                "text_tolerance": ["unicode_accent_normalization", "whitespace_normalization"],
                "ref_relocation": "same_verified_page_last_body_paragraph_only",
                "page_evidence": "raw_pages_context_unique_or_unresolved",
            },
        }
        handle.write(json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + "\n")
        for path in source_files:
            paragraphs = parse_markdown_paragraphs(
                path.read_text(encoding="utf-8"),
                source_file=path.name,
            )
            attach_reference_page_evidence(paragraphs, raw_page_index)
            chapter = _chapter_record(path, paragraphs)
            handle.write(json.dumps(chapter, ensure_ascii=False, separators=(",", ":")) + "\n")
            for paragraph in paragraphs:
                row = {"record_type": "paragraph", "chapter_key": chapter["chapter_key"], **paragraph}
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                ref_total += len(paragraph["ref_pages"])
                located_ref_total += sum(1 for ref in paragraph["ref_pages"] if ref["page_no"] is not None)
            paragraph_total += len(paragraphs)
    temp_path.replace(output_path)
    return {
        "schema": SCHEMA,
        "slug": slug,
        "chapters": len(source_files),
        "paragraphs": paragraph_total,
        "reference_pages_located": located_ref_total,
        "references": ref_total,
        "path": str(output_path),
        "bytes": output_path.stat().st_size,
    }


def iter_manifest_chapters(path: Path) -> Iterator[tuple[dict[str, Any], list[dict[str, Any]]]]:
    current_chapter: dict[str, Any] | None = None
    paragraphs: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["record_type"] == "meta":
                continue
            if row["record_type"] == "chapter":
                if current_chapter is not None:
                    yield current_chapter, paragraphs
                current_chapter = row
                paragraphs = []
            elif row["record_type"] == "paragraph":
                paragraphs.append(row)
    if current_chapter is not None:
        yield current_chapter, paragraphs


def _last_body_paragraph_by_page(paragraphs: list[dict[str, Any]]) -> dict[int, int]:
    last: dict[int, int] = {}
    for index, paragraph in enumerate(paragraphs):
        page_no = paragraph.get("page_no")
        if isinstance(page_no, int) and paragraph["kind"] == "body":
            last[page_no] = index
    return last


def _allowed_ref_relocations(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> tuple[Counter[tuple[int, str]], list[dict[str, Any]]]:
    """只豁免有页证据、且实际落在同页末段的 marker 迁移。"""
    permitted: Counter[tuple[int, str]] = Counter()
    details: list[dict[str, Any]] = []
    actual_last = _last_body_paragraph_by_page(actual)
    for expected_index, expected_paragraph in enumerate(expected):
        for reference in expected_paragraph.get("ref_pages", []):
            marker = reference["marker"]
            expected_page = reference.get("page_no")
            if not isinstance(expected_page, int):
                continue
            if marker in actual[expected_index]["refs"]:
                continue
            target_index = actual_last.get(expected_page)
            if target_index is None or target_index == expected_index:
                continue
            target = actual[target_index]
            if marker in target["refs"] and target.get("page_no") == expected_page:
                permitted[(expected_index, marker)] += 1
                permitted[(target_index, marker)] -= 1
                details.append(
                    {
                        "marker": marker,
                        "page_no": expected_page,
                        "from_paragraph": expected_index,
                        "to_paragraph": target_index,
                    }
                )
    return permitted, details


def compare_paragraph_sequences(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    *,
    max_mismatches: int = 100,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "expected_paragraph_count": len(expected),
        "actual_paragraph_count": len(actual),
        "count_mismatch": len(expected) != len(actual),
        "text_mismatches": [],
        "reference_mismatches": [],
        "definition_mismatches": [],
        "allowed_ref_relocations": [],
    }
    if result["count_mismatch"]:
        result["ok"] = False

    pair_count = min(len(expected), len(actual))
    allowed, allowed_details = _allowed_ref_relocations(expected[:pair_count], actual[:pair_count])
    result["allowed_ref_relocations"] = allowed_details
    for index in range(pair_count):
        expected_row = expected[index]
        actual_row = actual[index]
        if expected_row["text_sha256"] != actual_row["text_sha256"]:
            result["ok"] = False
            if len(result["text_mismatches"]) < max_mismatches:
                result["text_mismatches"].append(
                    {
                        "paragraph_ordinal": index,
                        "expected_source_file": expected_row.get("source_file", ""),
                        "expected_text": expected_row["source_text"],
                        "actual_text": actual_row["source_text"],
                        "actual_trace": actual_row.get("actual_trace", {}),
                    }
                )
        expected_refs = Counter(expected_row["refs"])
        actual_refs = Counter(actual_row["refs"])
        for marker, adjustment in list(allowed.items()):
            if marker[0] != index:
                continue
            if adjustment > 0:
                expected_refs[marker[1]] -= adjustment
            elif adjustment < 0:
                actual_refs[marker[1]] += adjustment
        expected_refs += Counter()
        actual_refs += Counter()
        if expected_refs != actual_refs:
            result["ok"] = False
            if len(result["reference_mismatches"]) < max_mismatches:
                result["reference_mismatches"].append(
                    {
                        "paragraph_ordinal": index,
                        "expected_refs": list(expected_row["refs"]),
                        "actual_refs": list(actual_row["refs"]),
                        "expected_text": expected_row["source_text"],
                        "actual_text": actual_row["source_text"],
                        "actual_trace": actual_row.get("actual_trace", {}),
                    }
                )
        if expected_row["definitions"] != actual_row["definitions"]:
            result["ok"] = False
            if len(result["definition_mismatches"]) < max_mismatches:
                result["definition_mismatches"].append(
                    {
                        "paragraph_ordinal": index,
                        "expected_definitions": expected_row["definitions"],
                        "actual_definitions": actual_row["definitions"],
                        "expected_text": expected_row["source_text"],
                        "actual_text": actual_row["source_text"],
                        "actual_trace": actual_row.get("actual_trace", {}),
                    }
                )
    return result


def _first_heading_title(text: str, fallback: str) -> str:
    for block in re.split(r"\n\s*\n", text):
        first_line = block.strip().splitlines()[0] if block.strip() else ""
        match = HEADING_RE.match(first_line)
        if match:
            return match.group(1).strip()
    return fallback


def _contains_translation_placeholder(text: str) -> bool:
    paragraphs = parse_markdown_paragraphs(text)
    return any(
        TRANSLATION_PLACEHOLDER_RE.match(row["source_text"].strip())
        for row in paragraphs
    )


def _load_db_chapters(db_path: Path, layer: str) -> list[dict[str, Any]]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        if layer == "export":
            rows = connection.execute(
                """
                SELECT section_id, order_idx, title, path, content, start_page, end_page, pages_json
                  FROM fnm_export_chapters
                 ORDER BY order_idx
                """
            ).fetchall()
            return [dict(row) for row in rows]
        if layer == "markdown":
            rows = connection.execute(
                """
                SELECT chapter_id AS section_id, order_idx, title, path,
                       markdown_text AS content, start_page, end_page, pages_json
                  FROM fnm_chapter_markdowns
                 ORDER BY order_idx
                """
            ).fetchall()
            return [dict(row) for row in rows]
        rows = connection.execute(
            "SELECT chapter_id AS section_id, body_pages_json FROM fnm_chapter_body_pages ORDER BY row_id"
        ).fetchall()
        chapters: list[dict[str, Any]] = []
        for order_idx, row in enumerate(rows):
            payload = json.loads(str(row["body_pages_json"] or "{}"))
            body_pages = payload.get("body_pages", [])
            actual_paragraphs: list[dict[str, Any]] = []
            text_parts: list[str] = []
            page_numbers: list[int] = []
            for page in body_pages:
                page_no = int(page.get("page_no") or 0) or None
                page_text = str(page.get("text") or "")
                page_paragraphs = parse_markdown_paragraphs(page_text)
                actual_paragraphs.extend(
                    parse_markdown_paragraphs(
                        page_text,
                        page_numbers=[page_no] * len(page_paragraphs),
                    )
                )
                text_parts.append(page_text)
                if page_no is not None:
                    page_numbers.append(page_no)
            content = "\n\n".join(text_parts)
            title = _first_heading_title(content, str(row["section_id"]))
            chapters.append(
                {
                    "section_id": str(row["section_id"]),
                    "order_idx": order_idx,
                    "title": title,
                    "path": f"fnm_chapter_body_pages/{row['section_id']}",
                    "content": content,
                    "start_page": min(page_numbers) if page_numbers else None,
                    "end_page": max(page_numbers) if page_numbers else None,
                    "pages_json": json.dumps(page_numbers),
                    "actual_paragraphs": actual_paragraphs,
                }
            )
        return chapters
    finally:
        connection.close()


def _match_actual_chapter(
    expected: dict[str, Any],
    actual_chapters: list[dict[str, Any]],
    used: set[int],
    reserved_titles: Counter[str],
) -> tuple[int | None, float]:
    for index, row in enumerate(actual_chapters):
        if index in used:
            continue
        if normalize_title(str(row["title"])) == expected["title_key"]:
            return index, 1.0
    best_index: int | None = None
    best_score = 0.0
    for index, row in enumerate(actual_chapters):
        if index in used:
            continue
        if reserved_titles[normalize_title(str(row["title"]))] > 0:
            continue
        score = SequenceMatcher(None, expected["title_key"], normalize_title(str(row["title"]))).ratio()
        if score > best_score:
            best_score = score
            best_index = index
    if best_score < 0.55:
        return None, best_score
    return best_index, best_score


def compare_manifest_to_db(
    manifest_path: Path,
    db_path: Path,
    layer: str = "export",
    max_mismatches: int = 100,
) -> dict[str, Any]:
    actual_chapters = _load_db_chapters(db_path, layer)
    expected_chapters = list(iter_manifest_chapters(manifest_path))
    reserved_titles: Counter[str] = Counter(chapter["title_key"] for chapter, _ in expected_chapters)
    used: set[int] = set()
    chapter_reports: list[dict[str, Any]] = []
    for chapter, expected_paragraphs in expected_chapters:
        reserved_titles[chapter["title_key"]] -= 1
        actual_index, title_score = _match_actual_chapter(chapter, actual_chapters, used, reserved_titles)
        if actual_index is None:
            chapter_reports.append(
                {
                    "expected_source_file": chapter["source_file"],
                    "expected_title": chapter["title"],
                    "ok": False,
                    "missing_actual_chapter": True,
                    "title_match_score": title_score,
                }
            )
            continue
        used.add(actual_index)
        actual = actual_chapters[actual_index]
        trace = {
            "db_path": str(db_path),
            "table": {
                "export": "fnm_export_chapters",
                "markdown": "fnm_chapter_markdowns",
                "body-pages": "fnm_chapter_body_pages",
            }[layer],
            "section_id": actual["section_id"],
            "path": actual["path"],
            "start_page": actual["start_page"],
            "end_page": actual["end_page"],
        }
        if layer in {"export", "markdown"} and _contains_translation_placeholder(str(actual["content"])):
            chapter_reports.append(
                {
                    "expected_source_file": chapter["source_file"],
                    "expected_title": chapter["title"],
                    "actual_path": actual["path"],
                    "actual_section_id": actual["section_id"],
                    "actual_trace": trace,
                    "title_match_score": round(title_score, 4),
                    "ok": True,
                    "comparison_status": "accepted_translation_placeholder",
                    "text_comparison_performed": False,
                    "reason": "translation_placeholder_is_allowed_in_current_stage",
                }
            )
            continue
        if "actual_paragraphs" in actual:
            actual_paragraphs = actual["actual_paragraphs"]
            for paragraph in actual_paragraphs:
                paragraph["source_file"] = str(actual["path"])
                paragraph["actual_trace"] = trace
        else:
            actual_paragraphs = parse_markdown_paragraphs(
                str(actual["content"]),
                source_file=str(actual["path"]),
                trace=trace,
            )
        report = compare_paragraph_sequences(
            expected_paragraphs,
            actual_paragraphs,
            max_mismatches=max_mismatches,
        )
        report.update(
            {
                "expected_source_file": chapter["source_file"],
                "expected_title": chapter["title"],
                "actual_path": actual["path"],
                "actual_section_id": actual["section_id"],
                "title_match_score": round(title_score, 4),
                "comparison_status": "compared",
                "text_comparison_performed": True,
            }
        )
        chapter_reports.append(report)
    unmatched_actual = [
        {
            "section_id": row["section_id"],
            "path": row["path"],
            "title": row["title"],
        }
        for index, row in enumerate(actual_chapters)
        if index not in used
    ]
    status = (
        "failed"
        if not all(row.get("ok", False) for row in chapter_reports) or unmatched_actual
        else "accepted_with_translation_placeholders"
        if any(row.get("comparison_status") == "accepted_translation_placeholder" for row in chapter_reports)
        else "passed"
    )
    return {
        "schema": SCHEMA,
        "manifest_path": str(manifest_path),
        "db_path": str(db_path),
        "actual_layer": layer,
        "ok": status != "failed",
        "status": status,
        "chapters": chapter_reports,
        "unmatched_actual_chapters": unmatched_actual,
    }


def _print_compare_summary(report: dict[str, Any]) -> None:
    failed = [chapter for chapter in report["chapters"] if not chapter.get("ok", False)]
    print(f"status={'ok' if report['ok'] else 'failed'} chapters={len(report['chapters'])} failed={len(failed)}")
    for chapter in failed[:10]:
        if chapter.get("missing_actual_chapter"):
            print(f"- {chapter['expected_source_file']}: missing_actual_chapter")
            continue
        print(
            f"- {chapter['expected_source_file']}: "
            f"text={len(chapter.get('text_mismatches', []))}, "
            f"refs={len(chapter.get('reference_mismatches', []))}, "
            f"defs={len(chapter.get('definition_mismatches', []))}, "
            f"count_mismatch={chapter.get('count_mismatch', False)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--slug", choices=sorted(BOOKS), required=True)
    compare = subparsers.add_parser("compare-db")
    compare.add_argument("--slug", choices=sorted(BOOKS), required=True)
    compare.add_argument("--db-path", type=Path)
    compare.add_argument("--layer", choices=["export", "markdown", "body-pages"], default="export")
    compare.add_argument("--report", type=Path)
    compare.add_argument("--max-mismatches", type=int, default=100)
    args = parser.parse_args()

    template_dir, manifest_path, default_db_path = _book_paths(args.slug)
    if args.command == "build":
        summary = write_manifest(args.slug, template_dir, manifest_path)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    db_path = args.db_path or default_db_path
    report = compare_manifest_to_db(manifest_path, db_path, args.layer, args.max_mismatches)
    output = args.report or (
        REPO_ROOT / "output" / "fnm_golden_compare" / f"{args.slug.lower()}_{args.layer}_db_report.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_compare_summary(report)
    print(f"report={output}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

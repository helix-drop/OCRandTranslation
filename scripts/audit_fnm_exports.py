#!/usr/bin/env python3
"""审计 FNM 导出结果。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from FNM_RE import (
    audit_export_for_doc,
    build_export_bundle_for_doc as build_fnm_obsidian_export_bundle,
    build_export_zip_for_doc as build_fnm_obsidian_export_zip,
)
from FNM_RE.stages.export_audit import body_paragraphs, definition_lines, split_body_and_definitions
from example_manifest import select_example_books
from persistence.sqlite_store import SQLiteRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计 FNM 导出章节内容。")
    parser.add_argument(
        "--group",
        choices=("baseline", "extension", "all"),
        default="extension",
        help="默认只审计 extension 组。",
    )
    parser.add_argument("--slug", default="", help="只审计指定 manifest slug。")
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "output" / "fnm_extension_export_audit.json"),
        help="抽样模式 JSON 输出路径。",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="对每本书 zip 内全部 markdown 文件做全量审计。",
    )
    return parser.parse_args()


def _split_body_and_definitions(content: str) -> tuple[str, str]:
    return split_body_and_definitions(content)


def _body_paragraphs(content: str) -> list[str]:
    return body_paragraphs(content)


def _definition_lines(content: str) -> list[str]:
    return definition_lines(content)


def audit_doc(doc_id: str, doc_name: str, slug: str = "") -> dict[str, Any]:
    bundle = build_fnm_obsidian_export_bundle(doc_id)
    chapter_files = dict(bundle.get("chapter_files") or {})
    chapters = list(bundle.get("chapters") or [])
    repo = SQLiteRepository()
    chapter_rows = {
        str(row.get("chapter_id") or ""): dict(row)
        for row in repo.list_fnm_chapters(doc_id)
        if str(row.get("chapter_id") or "").strip()
    }

    chapter_audits: list[dict[str, Any]] = []
    for chapter in chapters:
        section_id = str(chapter.get("section_id") or "").strip()
        path = str(chapter.get("path") or "").strip()
        content = str(chapter_files.get(path) or "")
        body_text, _ = split_body_and_definitions(content)
        refs = sorted(set(re.findall(r"\[\^([0-9]+)\]", body_text)))
        defs = sorted(set(re.findall(r"^\[\^([0-9]+)\]:", content, re.MULTILINE)))
        defs_only = [value for value in defs if value not in refs]
        refs_only = [value for value in refs if value not in defs]
        row = chapter_rows.get(section_id) or {}
        pages = [int(page) for page in (row.get("pages") or []) if int(page) > 0]
        paragraphs = body_paragraphs(content)
        chapter_audits.append(
            {
                "title": str(chapter.get("title") or "").strip(),
                "section_id": section_id,
                "path": path,
                "page_count": len(pages),
                "sample_pages": pages[:5],
                "paragraph_count": len(paragraphs),
                "sample_paragraphs": paragraphs[:20],
                "sample_definitions": definition_lines(content)[:10],
                "body_ref_count": len(refs),
                "definition_count": len(defs),
                "defs_only": defs_only,
                "refs_only": refs_only,
                "section_heading_count": len(re.findall(r"^###\s+(.+?)\s*$", body_text, re.MULTILINE)),
                "body_contract_ok": not defs_only and not refs_only,
            }
        )

    return {
        "doc_id": doc_id,
        "doc_name": doc_name,
        "slug": slug,
        "chapter_count": len(chapter_audits),
        "chapters": chapter_audits,
    }


def build_markdown_report(results: list[dict[str, Any]]) -> str:
    lines = ["# FNM 导出抽样审计", ""]
    for item in results:
        lines.extend([
            f"## {item.get('doc_name', '')}",
            "",
            f"- Doc ID：`{item.get('doc_id', '')}`",
            f"- Slug：`{item.get('slug', '')}`",
            f"- 章节数：{item.get('chapter_count', 0)}",
            "",
        ])
        for chapter in item.get("chapters") or []:
            lines.extend([
                f"### {chapter.get('title', '')}",
                "",
                f"- 页数：{chapter.get('page_count', 0)}",
                f"- 抽样页：`{chapter.get('sample_pages', [])}`",
                f"- 正文段数：{chapter.get('paragraph_count', 0)}",
                f"- 正文引用 / 章末定义：{chapter.get('body_ref_count', 0)} / {chapter.get('definition_count', 0)}",
                f"- defs_only / refs_only：`{chapter.get('defs_only', [])}` / `{chapter.get('refs_only', [])}`",
                f"- 章内标题数：{chapter.get('section_heading_count', 0)}",
                f"- 正文闭合：{chapter.get('body_contract_ok', False)}",
                "",
                "样本文本：",
                "",
            ])
            for para in chapter.get("sample_paragraphs") or []:
                lines.append(f"- {para[:240]}")
            if chapter.get("sample_definitions"):
                lines.extend(["", "样本注释：", ""])
                for note in chapter.get("sample_definitions") or []:
                    lines.append(f"- {note[:240]}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_book_audit_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# 导出审计：{report.get('slug') or report.get('doc_id') or ''}",
        "",
        f"- can_ship: {bool(report.get('can_ship'))}",
        f"- blocking_issue_count: {int(report.get('blocking_issue_count') or 0)}",
        f"- major_issue_count: {int(report.get('major_issue_count') or 0)}",
        "",
    ]
    for row in (report.get("files") or []):
        issue_codes = [str(code).strip() for code in (row.get("issue_codes") or []) if str(code).strip()]
        if not issue_codes:
            continue
        lines.extend([
            f"## {str(row.get('path') or '').strip()}",
            "",
            f"- title: {str(row.get('title') or '').strip()}",
            f"- severity: {str(row.get('severity') or '').strip() or 'minor'}",
            f"- issue_codes: {', '.join(issue_codes)}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def _default_full_audit_dir() -> Path:
    return REPO_ROOT / "output" / "fnm_book_audits"


def _run_full_audit(books: list[Any]) -> int:
    repo = SQLiteRepository()
    doc_map = {str(doc.get("id") or ""): doc for doc in repo.list_documents()}
    output_dir = _default_full_audit_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for book in books:
        doc = doc_map.get(book.doc_id)
        if not doc:
            failures += 1
            continue
        zip_path = REPO_ROOT / "test_example" / str(book.folder or "") / "latest.fnm.obsidian.zip"
        zip_bytes = None if zip_path.exists() else build_fnm_obsidian_export_zip(book.doc_id)
        report = audit_export_for_doc(
            book.doc_id,
            slug=book.slug,
            zip_path=str(zip_path) if zip_path.exists() else "",
            zip_bytes=zip_bytes,
            repo=repo,
        )
        json_path = output_dir / f"{book.slug}.json"
        md_path = output_dir / f"{book.slug}.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(_build_book_audit_markdown(report), encoding="utf-8")
        if not bool(report.get("can_ship")):
            failures += 1
        print(
            f"{book.slug}: can_ship={bool(report.get('can_ship'))},"
            f" blocking={int(report.get('blocking_issue_count') or 0)},"
            f" major={int(report.get('major_issue_count') or 0)}"
        )
    print(f"全量审计输出目录: {output_dir}")
    return 0 if failures == 0 else 2


def main() -> int:
    args = parse_args()
    books = select_example_books(
        include_all=True,
        group="all" if str(args.slug or "").strip() else (args.group or "extension"),
        slug=args.slug or "",
    )
    if not books:
        print("⚠ 未找到可审计样本。")
        return 1

    if args.full:
        return _run_full_audit(books)

    doc_map = {str(doc.get("id") or ""): doc for doc in SQLiteRepository().list_documents()}
    results: list[dict[str, Any]] = []
    failed = 0
    for book in books:
        doc = doc_map.get(book.doc_id)
        if not doc:
            failed += 1
            results.append(
                {
                    "doc_id": book.doc_id,
                    "doc_name": book.doc_name,
                    "slug": book.slug,
                    "error": "doc_missing",
                    "chapter_count": 0,
                    "chapters": [],
                }
            )
            continue
        results.append(audit_doc(book.doc_id, str(doc.get("name") or book.doc_name), slug=book.slug))

    output_path = Path(str(args.output)).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = output_path.with_suffix(".md")
    report_path.write_text(build_markdown_report(results), encoding="utf-8")

    print(f"JSON 结果已保存到: {output_path}")
    print(f"Markdown 报告已保存到: {report_path}")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

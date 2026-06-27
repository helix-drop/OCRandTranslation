#!/usr/bin/env python3
"""将 test_example 中的目录.pdf 批量绑定到样本文档，并重跑视觉目录/FNM。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from example_manifest import ExampleBook, select_example_books
from FNM_RE import run_doc_pipeline as run_fnm_pipeline
from persistence.storage_toc import save_toc_visual_manual_pdf
from pipeline.document_tasks import run_auto_visual_toc_for_doc


TEST_EXAMPLE_ROOT = REPO_ROOT / "test_example"
DOCS_ROOT = REPO_ROOT / "local_data" / "user_data" / "data" / "documents"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="为样本文档绑定手动目录 PDF，并重跑视觉目录/FNM。")
    parser.add_argument("--slug", default="", help="只处理指定样本 slug。")
    parser.add_argument("--folder", default="", help="只处理指定样本目录。")
    parser.add_argument("--doc-id", default="", help="只处理指定 doc_id。")
    parser.add_argument(
        "--group",
        choices=("baseline", "extension", "all"),
        default="all",
        help="按 manifest 分组过滤；默认 all。",
    )
    parser.add_argument(
        "--skip-fnm",
        action="store_true",
        help="只重跑视觉目录，不继续跑 FNM pipeline。",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "output" / "manual_toc_apply_result.json"),
        help="结果 JSON 输出路径。",
    )
    return parser.parse_args()


def _select_books(args: argparse.Namespace) -> list[ExampleBook]:
    return select_example_books(
        include_all=True,
        group=args.group,
        slug=args.slug,
        folder=args.folder,
        doc_id=args.doc_id,
    )


def _source_pdf_for(book: ExampleBook) -> Path:
    doc_pdf = DOCS_ROOT / book.doc_id / "source.pdf"
    if doc_pdf.is_file():
        return doc_pdf
    for pdf_path in sorted((TEST_EXAMPLE_ROOT / book.folder).glob("*.pdf")):
        if pdf_path.name == "目录.pdf":
            continue
        return pdf_path
    raise FileNotFoundError(f"未找到原书 PDF：doc_id={book.doc_id} folder={book.folder}")


def _toc_pdf_for(book: ExampleBook) -> Path:
    toc_pdf = TEST_EXAMPLE_ROOT / book.folder / "目录.pdf"
    if not toc_pdf.is_file():
        raise FileNotFoundError(f"未找到目录 PDF：{toc_pdf}")
    return toc_pdf


def process_book(book: ExampleBook, *, run_fnm: bool) -> dict[str, Any]:
    toc_pdf = _toc_pdf_for(book)
    source_pdf = _source_pdf_for(book)
    saved_path = save_toc_visual_manual_pdf(book.doc_id, str(toc_pdf), original_name=toc_pdf.name)
    visual_result = run_auto_visual_toc_for_doc(book.doc_id, str(source_pdf)) or {}
    fnm_result: dict[str, Any] = {}
    if run_fnm:
        fnm_result = run_fnm_pipeline(book.doc_id) or {}
    return {
        "slug": book.slug,
        "folder": book.folder,
        "doc_id": book.doc_id,
        "toc_pdf": str(toc_pdf),
        "source_pdf": str(source_pdf),
        "saved_manual_toc_path": str(saved_path or ""),
        "visual_toc": visual_result,
        "fnm": fnm_result,
    }


def main() -> int:
    args = parse_args()
    books = _select_books(args)
    if not books:
        print("未找到匹配的样本。", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    failed = 0
    for book in books:
        try:
            result = process_book(book, run_fnm=not args.skip_fnm)
        except Exception as exc:
            failed += 1
            result = {
                "slug": book.slug,
                "folder": book.folder,
                "doc_id": book.doc_id,
                "error": str(exc),
            }
        results.append(result)
        status = (((result.get("visual_toc") or {}).get("status")) if isinstance(result, dict) else "") or ("failed" if result.get("error") else "")
        print(f"[{book.slug}] visual_toc={status} folder={book.folder}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "count": len(results),
                "failed": failed,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"结果已写入：{output_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

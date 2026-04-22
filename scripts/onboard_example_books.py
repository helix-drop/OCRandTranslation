#!/usr/bin/env python3
"""将扩展样本书纳入 test_example，并完成 OCR / 视觉目录 / FNM 快照。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import ensure_dirs, get_doc_dir, get_paddle_token
from document.note_detection import annotate_pages_with_note_scans
from document.pdf_extract import extract_pdf_toc, extract_pdf_toc_from_links
from document.text_processing import clean_header_footer, combine_sources, extract_pdf_text, parse_ocr
from example_manifest import ExampleBook, select_example_books
from FNM_RE import build_doc_status as build_fnm_structure_status
from FNM_RE import run_doc_pipeline as run_fnm_pipeline
from ocr_client import call_paddle_ocr_bytes
from persistence.sqlite_store import SQLiteRepository
from persistence.storage import save_pages_to_disk
from persistence.storage_toc import (
    load_auto_visual_toc_from_disk,
    save_auto_pdf_toc_to_disk,
)
from pipeline.document_tasks import run_auto_visual_toc_for_doc


TEST_EXAMPLE_ROOT = REPO_ROOT / "test_example"
DOCS_ROOT = REPO_ROOT / "local_data" / "user_data" / "data" / "documents"
RAW_PAGES_FILE = "raw_pages.json"
RAW_SOURCE_MD_FILE = "raw_source_markdown.md"
FNM_STATUS_FILE = "fnm_cleanup_status.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将扩展书目纳入 test_example，并生成 OCR/FNM 快照。")
    parser.add_argument("--slug", default="", help="只处理指定 manifest slug。")
    parser.add_argument("--folder", default="", help="只处理指定 manifest folder。")
    parser.add_argument("--doc-id", default="", help="只处理指定 manifest doc_id。")
    parser.add_argument(
        "--group",
        choices=("baseline", "extension", "all"),
        default="extension",
        help="默认只处理 extension 组。",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="若样本已具备 OCR / 视觉目录 / FNM 快照，则直接跳过。",
    )
    return parser.parse_args()


def _page_markdown_text(page: dict | None) -> str:
    if not isinstance(page, dict):
        return ""
    markdown = page.get("markdown")
    if isinstance(markdown, dict):
        return str(markdown.get("text") or "")
    return str(markdown or "")


def build_raw_pages_payload(*, book: ExampleBook, pages: list[dict]) -> dict[str, Any]:
    return {
        "doc_id": book.doc_id,
        "name": book.doc_name,
        "page_count": len(pages),
        "pages": pages,
    }


def build_raw_source_markdown(*, book: ExampleBook, pages: list[dict]) -> str:
    lines = [f"# {book.doc_name}", ""]
    for index, page in enumerate(pages or [], start=1):
        lines.append(f"## PDF第{index}页")
        lines.append("")
        text = _page_markdown_text(page).rstrip()
        if text:
            lines.append(text)
            lines.append("")
        else:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _target_folder(book: ExampleBook) -> Path:
    return TEST_EXAMPLE_ROOT / book.folder


def _target_doc_dir(book: ExampleBook) -> Path:
    return Path(get_doc_dir(book.doc_id))


def ensure_document_record(book: ExampleBook) -> dict[str, Any]:
    ensure_dirs()
    repo = SQLiteRepository()
    now = int(time.time())
    existing = repo.get_document(book.doc_id) or {}
    _target_doc_dir(book).mkdir(parents=True, exist_ok=True)
    repo.upsert_document(
        book.doc_id,
        book.doc_name,
        created_at=int(existing.get("created_at") or now),
        updated_at=now,
        page_count=int(existing.get("page_count") or 0),
        entry_count=int(existing.get("entry_count") or 0),
        last_entry_idx=int(existing.get("last_entry_idx") or 0),
        has_pdf=1,
        status="ready",
        source_pdf_path=book.source_pdf_path,
        cleanup_headers_footers=True,
        auto_visual_toc_enabled=True,
        toc_visual_status=str(existing.get("toc_visual_status") or "idle"),
        toc_visual_message=str(existing.get("toc_visual_message") or ""),
        toc_visual_model_id=str(existing.get("toc_visual_model_id") or ""),
    )
    return repo.get_document(book.doc_id) or {}


def _log_progress(message: str) -> None:
    print(message, flush=True)


def copy_pdf_into_places(book: ExampleBook) -> tuple[Path, Path]:
    source_pdf = Path(book.source_pdf_path)
    if not source_pdf.is_file():
        raise FileNotFoundError(f"未找到源 PDF：{source_pdf}")
    target_folder = _target_folder(book)
    target_folder.mkdir(parents=True, exist_ok=True)
    example_pdf = target_folder / source_pdf.name
    doc_pdf = _target_doc_dir(book) / "source.pdf"
    if not example_pdf.exists() or example_pdf.stat().st_size != source_pdf.stat().st_size:
        shutil.copy2(source_pdf, example_pdf)
    if not doc_pdf.exists() or doc_pdf.stat().st_size != source_pdf.stat().st_size:
        shutil.copy2(source_pdf, doc_pdf)
    return doc_pdf, example_pdf


def _apply_cleanup_flag(pages: list[dict], *, cleanup_enabled: bool) -> list[dict]:
    tagged: list[dict] = []
    for page in pages or []:
        payload = dict(page or {})
        payload["_cleanup_applied"] = bool(cleanup_enabled)
        tagged.append(payload)
    return tagged


def _build_placeholder_page(
    *,
    file_idx: int,
    fallback_text: str,
    template: dict[str, Any] | None,
) -> dict[str, Any]:
    base = dict(template or {})
    return {
        "fileIdx": file_idx,
        "bookPage": file_idx + 1,
        "pdfPage": file_idx + 1,
        "printPage": None,
        "printPageLabel": "",
        "detectedPage": None,
        "imgW": int(base.get("imgW") or 0),
        "imgH": int(base.get("imgH") or 0),
        "blocks": [],
        "fnBlocks": [],
        "footnotes": "",
        "indent": base.get("indent"),
        "textSource": "pdf" if fallback_text else "empty",
        "markdown": str(fallback_text or ""),
        "prunedResult": "",
        "isFigurePage": False,
        "_cleanup_applied": True,
        "_restored_missing_page": True,
    }


def restore_missing_pages(
    *,
    pages: list[dict],
    pdf_pages: list[dict],
) -> list[dict]:
    if not pages:
        return pages
    expected_count = max(len(pdf_pages or []), max(int(page.get("fileIdx") or 0) for page in pages) + 1)
    if expected_count <= len(pages):
        return sorted(pages, key=lambda page: int(page.get("fileIdx") or 0))

    by_idx = {int(page.get("fileIdx") or 0): dict(page) for page in pages if isinstance(page, dict)}
    sorted_pages = sorted(by_idx.values(), key=lambda page: int(page.get("fileIdx") or 0))
    default_template = next((page for page in sorted_pages if page.get("imgW") and page.get("imgH")), sorted_pages[0])

    restored: list[dict] = []
    restored_count = 0
    for file_idx in range(expected_count):
        existing = by_idx.get(file_idx)
        if existing is not None:
            restored.append(existing)
            continue
        fallback_text = ""
        if 0 <= file_idx < len(pdf_pages or []):
            fallback_text = str((pdf_pages[file_idx] or {}).get("fullText") or "").strip()
        restored.append(
            _build_placeholder_page(
                file_idx=file_idx,
                fallback_text=fallback_text,
                template=default_template,
            )
        )
        restored_count += 1
    if restored_count:
        _log_progress(f"补齐缺失页：恢复 {restored_count} 个被清理阶段移除的空白/无块页面")
    return restored


def _save_pdf_toc(doc_id: str, file_bytes: bytes) -> int:
    toc_items = extract_pdf_toc(file_bytes)
    if not toc_items:
        toc_items = extract_pdf_toc_from_links(file_bytes)
    save_auto_pdf_toc_to_disk(doc_id, toc_items or [])
    return len(toc_items or [])


def process_pdf(book: ExampleBook, *, doc_pdf_path: Path) -> dict[str, Any]:
    token = get_paddle_token()
    if not token:
        raise RuntimeError("请先在设置中配置 PaddleOCR 令牌。")
    file_bytes = doc_pdf_path.read_bytes()
    def _on_ocr_progress(current_chunk: int, total_chunks: int) -> None:
        _log_progress(f"[{book.slug}] OCR 分片进度 {current_chunk}/{total_chunks}")

    _log_progress(f"[{book.slug}] 开始 OCR：{doc_pdf_path.name}")
    result = call_paddle_ocr_bytes(
        file_bytes=file_bytes,
        token=token,
        file_type=0,
        on_progress=_on_ocr_progress,
    )
    _log_progress(f"[{book.slug}] OCR 完成，开始解析页面")
    parsed = parse_ocr(result)
    if not parsed.get("pages"):
        raise RuntimeError("OCR 未返回页面数据。")
    pages = list(parsed["pages"])
    pdf_pages = extract_pdf_text(file_bytes)
    if pdf_pages:
        pages = list((combine_sources(pages, pdf_pages) or {}).get("pages") or pages)
    cleanup_result = clean_header_footer(pages)
    cleaned_pages = _apply_cleanup_flag(list(cleanup_result.get("pages") or pages), cleanup_enabled=True)
    cleaned_pages = restore_missing_pages(pages=cleaned_pages, pdf_pages=pdf_pages)
    cleaned_pages = annotate_pages_with_note_scans(cleaned_pages)
    save_pages_to_disk(cleaned_pages, book.doc_name, book.doc_id)
    SQLiteRepository().upsert_document(
        book.doc_id,
        book.doc_name,
        page_count=len(cleaned_pages),
        updated_at=int(time.time()),
    )
    pdf_toc_count = _save_pdf_toc(book.doc_id, file_bytes)
    _log_progress(
        f"[{book.slug}] 页面已保存：{len(cleaned_pages)} 页，PDF 目录项 {pdf_toc_count} 条"
    )
    return {
        "page_count": len(cleaned_pages),
        "pages": cleaned_pages,
        "ocr_log": list(parsed.get("log") or []),
        "cleanup_log": list(cleanup_result.get("log") or []),
        "pdf_toc_count": pdf_toc_count,
    }


def write_book_snapshots(
    *,
    book: ExampleBook,
    pages: list[dict],
    fnm_result: dict[str, Any],
    structure_status: dict[str, Any],
) -> dict[str, str]:
    folder_dir = _target_folder(book)
    folder_dir.mkdir(parents=True, exist_ok=True)
    raw_pages_path = folder_dir / RAW_PAGES_FILE
    raw_source_md_path = folder_dir / RAW_SOURCE_MD_FILE
    fnm_status_path = folder_dir / FNM_STATUS_FILE

    raw_pages_payload = build_raw_pages_payload(book=book, pages=pages)
    raw_pages_path.write_text(
        json.dumps(raw_pages_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    raw_source_md_path.write_text(
        build_raw_source_markdown(book=book, pages=pages),
        encoding="utf-8",
    )
    fnm_status_path.write_text(
        json.dumps(
            {
                "doc_id": book.doc_id,
                "doc_name": book.doc_name,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "fnm_pipeline_result": fnm_result,
                "fnm_structure_status": structure_status,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "raw_pages_path": str(raw_pages_path),
        "raw_source_markdown_path": str(raw_source_md_path),
        "fnm_cleanup_status_path": str(fnm_status_path),
    }


def book_is_ready(book: ExampleBook) -> bool:
    repo = SQLiteRepository()
    doc = repo.get_document(book.doc_id) or {}
    folder_dir = _target_folder(book)
    if int(doc.get("page_count") or 0) <= 0:
        return False
    required_paths = [
        folder_dir / RAW_PAGES_FILE,
        folder_dir / RAW_SOURCE_MD_FILE,
        folder_dir / "auto_visual_toc.json",
        folder_dir / "auto_visual_toc.md",
    ]
    return all(path.exists() for path in required_paths)


def onboard_book(book: ExampleBook, *, skip_existing: bool = False) -> dict[str, Any]:
    _log_progress(f"[{book.slug}] 开始接入样本")
    ensure_document_record(book)
    doc_pdf_path, example_pdf_path = copy_pdf_into_places(book)
    if skip_existing and book_is_ready(book):
        _log_progress(f"[{book.slug}] 已有快照，跳过")
        return {
            "doc_id": book.doc_id,
            "slug": book.slug,
            "folder": book.folder,
            "status": "skipped_existing",
            "doc_pdf_path": str(doc_pdf_path),
            "example_pdf_path": str(example_pdf_path),
        }

    process_result = process_pdf(book, doc_pdf_path=doc_pdf_path)
    _log_progress(f"[{book.slug}] 开始生成自动视觉目录")
    visual_toc_result = run_auto_visual_toc_for_doc(book.doc_id, str(doc_pdf_path), model_spec=None) or {}
    _log_progress(f"[{book.slug}] 开始执行 FNM 流水线")
    fnm_result = run_fnm_pipeline(book.doc_id) or {}
    structure_status = build_fnm_structure_status(book.doc_id, repo=SQLiteRepository())
    snapshot_paths = write_book_snapshots(
        book=book,
        pages=list(process_result.get("pages") or []),
        fnm_result=fnm_result,
        structure_status=structure_status,
    )
    auto_visual = load_auto_visual_toc_from_disk(book.doc_id) or []
    return {
        "doc_id": book.doc_id,
        "slug": book.slug,
        "folder": book.folder,
        "status": "ok",
        "page_count": int(process_result.get("page_count") or 0),
        "expected_page_count": book.expected_page_count,
        "visual_toc_status": str(visual_toc_result.get("status") or ""),
        "visual_toc_count": len(auto_visual),
        "fnm_ok": bool(fnm_result.get("ok")),
        "structure_state": structure_status.get("structure_state"),
        "doc_pdf_path": str(doc_pdf_path),
        "example_pdf_path": str(example_pdf_path),
        **snapshot_paths,
    }


def main() -> int:
    args = parse_args()
    books = select_example_books(
        include_all=True,
        group=args.group or "extension",
        slug=args.slug or "",
        folder=args.folder or "",
        doc_id=args.doc_id or "",
    )
    if not books:
        print(json.dumps({"processed": 0, "results": [], "error": "未找到目标书目。"}, ensure_ascii=False, indent=2))
        return 1

    results: list[dict[str, Any]] = []
    has_error = False
    for book in books:
        try:
            results.append(onboard_book(book, skip_existing=bool(args.skip_existing)))
        except Exception as exc:
            has_error = True
            _log_progress(f"[{book.slug}] 处理失败：{exc}")
            results.append(
                {
                    "doc_id": book.doc_id,
                    "slug": book.slug,
                    "folder": book.folder,
                    "status": "error",
                    "error": str(exc),
                }
            )

    print(
        json.dumps(
            {
                "processed": len(books),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())

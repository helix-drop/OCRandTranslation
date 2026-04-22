#!/usr/bin/env python3
"""从 test_example/<folder>/ 的 PDF/JSON/MD 快照重新注入 8 本样书的 FNM 数据。

不重跑 PaddleOCR：读取已有 raw_pages.json 写回页面；若存在 auto_visual_toc.json
/ 目录.pdf，则同步绑定。随后清空该文档的 FNM 状态（含 review overrides），
重新执行 `run_fnm_pipeline`。

目的：为 Tier 1a LLM 修补提供一个干净、可复现的起点。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from FNM_RE import run_doc_pipeline as run_fnm_pipeline  # noqa: E402
from example_manifest import ExampleBook, select_example_books  # noqa: E402
from persistence.sqlite_store import SQLiteRepository  # noqa: E402
from persistence.storage_toc import (  # noqa: E402
    save_auto_visual_toc_bundle_to_disk,
    save_auto_visual_toc_to_disk,
    save_toc_visual_manual_pdf,
)
from pipeline.document_tasks import run_auto_visual_toc_for_doc  # noqa: E402

TEST_EXAMPLE_ROOT = REPO_ROOT / "test_example"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _book_folder(book: ExampleBook) -> Path:
    return TEST_EXAMPLE_ROOT / book.folder


def _ensure_doc_pdf(book: ExampleBook) -> Path:
    doc_dir = REPO_ROOT / "local_data" / "user_data" / "data" / "documents" / book.doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_pdf = doc_dir / "source.pdf"
    if not doc_pdf.exists() or doc_pdf.stat().st_size == 0:
        example_pdf = _book_folder(book) / book.doc_name
        if not example_pdf.is_file():
            raise FileNotFoundError(f"缺少示例 PDF：{example_pdf}")
        shutil.copy2(example_pdf, doc_pdf)
    return doc_pdf


def _load_raw_pages(book: ExampleBook) -> list[dict]:
    raw_path = _book_folder(book) / "raw_pages.json"
    if not raw_path.is_file():
        raise FileNotFoundError(f"缺少 raw_pages.json：{raw_path}")
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    pages = list(payload.get("pages") or [])
    if not pages:
        raise RuntimeError(f"raw_pages.json 无页面：{raw_path}")
    return pages


def _load_auto_visual_toc(book: ExampleBook) -> list[dict] | None:
    path = _book_folder(book) / "auto_visual_toc.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("toc") or []
        if isinstance(items, list):
            return items
    return None


def _load_auto_visual_toc_bundle(book: ExampleBook) -> dict[str, Any]:
    path = _book_folder(book) / "auto_visual_toc.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return {
        "items": list(payload.get("items") or []),
        "endnotes_summary": dict(payload.get("endnotes_summary") or {}),
        "organization_summary": dict(payload.get("organization_summary") or {}),
        "run_summaries": list(payload.get("run_summaries") or []),
        "manual_page_items_debug": list(payload.get("manual_page_items_debug") or []),
        "organization_bundle_debug": dict(payload.get("organization_bundle_debug") or {}),
    }


def _maybe_bind_manual_toc(book: ExampleBook) -> str | None:
    folder = _book_folder(book)
    pdf = folder / "目录.pdf"
    if not pdf.is_file():
        for candidate in sorted(folder.glob("*目录*.pdf")):
            if candidate.is_file():
                pdf = candidate
                break
    if not pdf.is_file():
        return None
    return save_toc_visual_manual_pdf(
        book.doc_id, str(pdf), original_name=pdf.name
    )


def reingest_book(
    book: ExampleBook,
    *,
    rerun_auto_toc: bool = False,
    restore_auto_visual_toc: bool = True,
    rebuild_fnm: bool = True,
) -> dict[str, Any]:
    _log(f"[{book.slug}] 开始重新注入")
    repo = SQLiteRepository()
    doc_pdf = _ensure_doc_pdf(book)
    pages = _load_raw_pages(book)
    repo.upsert_document(
        book.doc_id,
        book.doc_name,
        page_count=len(pages),
        updated_at=int(time.time()),
    )
    repo.replace_pages(book.doc_id, pages)
    _log(f"[{book.slug}] 页面已写入：{len(pages)} 页")

    toc_items = _load_auto_visual_toc(book) if restore_auto_visual_toc else None
    toc_bundle = _load_auto_visual_toc_bundle(book) if restore_auto_visual_toc else {}
    if toc_items:
        save_auto_visual_toc_to_disk(book.doc_id, toc_items)
        save_auto_visual_toc_bundle_to_disk(
            book.doc_id,
            {
                **toc_bundle,
                "items": list(toc_items or []),
            },
        )
        _log(f"[{book.slug}] 视觉目录已写入：{len(toc_items)} 条")

    manual_toc = _maybe_bind_manual_toc(book)
    if manual_toc:
        _log(f"[{book.slug}] 已绑定 目录.pdf → {manual_toc}")

    # 清空此前的 FNM 状态，含 review overrides，保证 LLM 修补从零开始。
    repo.clear_fnm_data(book.doc_id)
    _log(f"[{book.slug}] FNM 数据已清空")

    # 仅在显式要求重跑时触发自动视觉目录；restore_auto_visual_toc=False 时不应隐式重跑，
    # 否则会把“重注入”和“视觉目录阶段”重新混在一起。
    if rerun_auto_toc:
        try:
            visual = run_auto_visual_toc_for_doc(book.doc_id, str(doc_pdf), model_spec=None) or {}
            _log(f"[{book.slug}] 自动视觉目录：{visual.get('status')}")
        except Exception as exc:
            _log(f"[{book.slug}] 自动视觉目录失败：{exc}")

    fnm: dict[str, Any] = {}
    blocking: list[str] = []
    if rebuild_fnm:
        fnm = run_fnm_pipeline(book.doc_id) or {}
        blocking = list(fnm.get("blocking_reasons") or [])
        _log(
            f"[{book.slug}] FNM 重建完成：state={fnm.get('structure_state')} "
            f"notes={fnm.get('note_count')} links_ok={fnm.get('ok')} blocking={blocking}"
        )
    return {
        "slug": book.slug,
        "doc_id": book.doc_id,
        "page_count": len(pages),
        "visual_toc_count": len(toc_items or []),
        "manual_toc_bound": bool(manual_toc),
        "restore_auto_visual_toc": bool(restore_auto_visual_toc),
        "rebuild_fnm": bool(rebuild_fnm),
        "fnm_ok": bool(fnm.get("ok")),
        "fnm_state": fnm.get("structure_state"),
        "blocking_reasons": list(blocking),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 test_example 快照重新注入 FNM 数据。")
    parser.add_argument("--slug", default="", help="只处理指定 slug")
    parser.add_argument("--folder", default="")
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--group", default="all", choices=["baseline", "extension", "all"])
    parser.add_argument("--rerun-auto-toc", action="store_true", help="即便已有 auto_visual_toc.json 也重跑一次")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    books = select_example_books(
        include_all=True,
        group=args.group,
        slug=args.slug or "",
        folder=args.folder or "",
        doc_id=args.doc_id or "",
    )
    if not books:
        print(json.dumps({"processed": 0, "error": "未找到目标书目"}, ensure_ascii=False))
        return 1
    results: list[dict[str, Any]] = []
    for book in books:
        try:
            results.append(reingest_book(book, rerun_auto_toc=args.rerun_auto_toc))
        except Exception as exc:
            _log(f"[{book.slug}] 失败：{exc}")
            results.append({"slug": book.slug, "error": str(exc)})
    print(json.dumps({"processed": len(results), "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

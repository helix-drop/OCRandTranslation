#!/usr/bin/env python3
"""绕过结构检查，直接生成 FNM 导出 ZIP 并执行金版对比。

用法:
  python3 scripts/force_export_and_compare.py --slug Biopolitics
  python3 scripts/force_export_and_compare.py --slug Goldstein
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import list_docs
from example_manifest import select_example_books
from FNM_RE import (
    build_export_bundle_for_doc,
    build_export_zip_for_doc,
    load_doc_structure,
    run_doc_pipeline,
)
from FNM_RE.page_translate import (
    apply_body_unit_translations,
    build_fnm_body_unit_jobs,
    rebuild_fnm_diagnostic_page_entries,
)
from persistence.sqlite_store import SQLiteRepository
from persistence.storage import load_pages_from_disk
from document.text_utils import ensure_str
from translation.translate_state import TASK_KIND_FNM, _build_translate_task_meta
from translation.translate_store import _save_translate_state


def force_export(doc_id: str, example_dir: Path, zip_name: str) -> Path:
    """跳过所有结构检查，直接构建并保存导出 ZIP。"""
    repo = SQLiteRepository()

    # 载入文档结构（用作 snapshot）
    doc_structure = load_doc_structure(doc_id, slug=doc_id)

    # 占位翻译（与 materialize_test_placeholders 相同逻辑）
    pages, _ = load_pages_from_disk(doc_id)
    units = repo.list_fnm_translation_units(doc_id)
    for unit in units:
        unit_id = str(unit.get("unit_id") or "").strip()
        kind = str(unit.get("kind") or "").strip()
        if kind == "body":
            jobs = build_fnm_body_unit_jobs(unit, pages)
            translated_paragraphs = [ensure_str(job.get("text") or "").strip() for job in jobs]
            payload = apply_body_unit_translations(unit, translated_paragraphs)
            repo.update_fnm_translation_unit(
                doc_id, unit_id,
                translated_text=payload["translated_text"],
                status="done", error_msg="",
                page_segments=payload["page_segments"],
            )
        else:
            translated_text = ensure_str(unit.get("source_text") or "").strip()
            repo.update_fnm_translation_unit(
                doc_id, unit_id,
                translated_text=translated_text,
                status="done", error_msg="",
            )
            note_id = str(unit.get("note_id") or "").strip()
            if note_id:
                repo.update_fnm_note_translation(doc_id, note_id, translated_text, status="done")

    rebuild_fnm_diagnostic_page_entries(doc_id, pages=pages, repo=repo)

    # 构建导出包
    print("  构建导出包...")
    export_bundle = build_export_bundle_for_doc(doc_id, snapshot=doc_structure)
    print("  构建 ZIP...")
    zip_bytes = build_export_zip_for_doc(doc_id, snapshot=doc_structure)

    example_dir.mkdir(parents=True, exist_ok=True)
    zip_path = example_dir / zip_name
    zip_path.write_bytes(zip_bytes)
    print(f"  ✓ ZIP 已保存: {zip_path} ({len(zip_bytes)} bytes)")
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True, help="书籍 slug: Biopolitics 或 Goldstein")
    parser.add_argument("--zip-name", default="", help="自定义 ZIP 文件名，默认 latest.fnm.obsidian.zip")
    parser.add_argument("--skip-pipeline", action="store_true", help="跳过 pipeline 重跑")
    args = parser.parse_args()

    books = select_example_books(include_all=True, slug=args.slug)
    if not books:
        print(f"未找到 slug={args.slug} 的书籍")
        return 1

    book = books[0]
    doc_id = book.doc_id
    example_dir = REPO_ROOT / "test_example" / book.folder
    zip_name = args.zip_name or "latest.fnm.obsidian.zip"

    print(f"# 强制导出: {book.doc_name}")
    print(f"  doc_id={doc_id}, folder={book.folder}")

    if not args.skip_pipeline:
        print("\n[1/3] 重跑 Pipeline...")
        result = run_doc_pipeline(doc_id)
        if result.get("ok"):
            print(f"  ✓ Pipeline 完成: sections={result.get('section_count', 0)}, notes={result.get('note_count', 0)}")
        else:
            print(f"  ✗ Pipeline 失败: {result.get('error', 'unknown')}")
            return 1
    else:
        print("\n[1/3] 跳过 Pipeline (--skip-pipeline)")

    print("\n[2/3] 写入测试占位译文...")
    print("\n[3/3] 导出 ZIP...")
    zip_path = force_export(doc_id, example_dir, zip_name)

    # 同时存一份 golden comparison 用的命名
    golden_zip_name = f"latest.fnm.obsidian.{args.slug}.blocked.test.zip"
    golden_zip_path = example_dir / golden_zip_name
    golden_zip_path.write_bytes(zip_path.read_bytes())
    print(f"  ✓ 金版对比用 ZIP: {golden_zip_path}")

    # 写 export status
    status = {
        "doc_id": doc_id,
        "status": "ok",
        "reason": "force_exported_for_golden_comparison",
        "blocking_reasons": [],
        "generated_at": int(time.time()),
    }
    (example_dir / "latest_export_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n✅ 强制导出完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

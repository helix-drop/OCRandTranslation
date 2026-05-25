#!/usr/bin/env python3
"""从已验收的 Phase 1-3 数据回放 Rust Phase 4-6，不触发模型请求。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "output" / "fnm_downstream_replay"
UPSTREAM_TABLES = (
    "fnm_pages",
    "fnm_chapters",
    "fnm_heading_candidates",
    "fnm_section_heads",
    "fnm_note_regions",
    "fnm_note_items",
    "fnm_chapter_note_modes",
    "fnm_body_anchors",
    "fnm_note_links",
    "fnm_review_overrides_v2",
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from example_manifest import select_example_books  # noqa: E402
from FNM_RE import replay_phase4_to6, run_post_translate_export_checks_for_doc  # noqa: E402
from persistence.sqlite_db_paths import get_document_db_path  # noqa: E402
from scripts.test_fnm_batch import materialize_test_placeholders  # noqa: E402


def _table_digest(db_path: Path, table: str, doc_id: str) -> dict[str, Any]:
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE doc_id = ? ORDER BY rowid",
            (doc_id,),
        ).fetchall()
    encoded = json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8")
    return {"count": len(rows), "sha256": hashlib.sha256(encoded).hexdigest()}


def _upstream_digest(db_path: Path, doc_id: str) -> dict[str, Any]:
    return {table: _table_digest(db_path, table, doc_id) for table in UPSTREAM_TABLES}


def replay_book(slug: str, output_dir: Path) -> dict[str, Any]:
    books = select_example_books(include_all=True, slug=slug)
    if len(books) != 1:
        raise RuntimeError(f"找不到唯一样本书: {slug}")
    book = books[0]
    source_db = Path(get_document_db_path(book.doc_id))
    if not source_db.exists():
        raise FileNotFoundError(f"样本 DB 不存在: {source_db}")

    book_dir = output_dir / book.slug
    book_dir.mkdir(parents=True, exist_ok=True)
    replay_db = book_dir / "doc.db"
    shutil.copy2(source_db, replay_db)

    upstream_before = _upstream_digest(replay_db, book.doc_id)
    result = replay_phase4_to6(book.doc_id, db_path=str(replay_db), slug=book.slug)
    placeholders = materialize_test_placeholders(book.doc_id, db_path=str(replay_db))
    export_check = run_post_translate_export_checks_for_doc(
        book.doc_id,
        db_path=str(replay_db),
        max_repair_rounds=0,
    )
    upstream_after = _upstream_digest(replay_db, book.doc_id)
    upstream_unchanged = upstream_before == upstream_after
    report = {
        "slug": book.slug,
        "doc_id": book.doc_id,
        "source_db": str(source_db),
        "replay_db": str(replay_db),
        "upstream_unchanged": upstream_unchanged,
        "upstream_digest": upstream_after,
        "replay": result,
        "placeholders": placeholders,
        "export_check": export_check,
        "passed": (
            bool(result.get("ok"))
            and upstream_unchanged
            and bool(placeholders.get("ok"))
            and bool(export_check.get("export_ready_real"))
            and not list(result.get("blocking_reasons") or [])
        ),
    }
    (book_dir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--slug",
        action="append",
        dest="slugs",
        help="回放的样本 slug，可重复传入；默认 Biopolitics 与 Goldstein",
    )
    parser.add_argument("--tag", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    slugs = args.slugs or ["Biopolitics", "Goldstein"]
    output_dir = OUTPUT_ROOT / args.tag
    reports = [replay_book(slug, output_dir) for slug in slugs]
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "persisted_phase1_to_phase3_downstream_replay",
        "model_requests": 0,
        "passed": all(report["passed"] for report in reports),
        "books": reports,
    }
    (output_dir / "results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

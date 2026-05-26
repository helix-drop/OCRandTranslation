#!/usr/bin/env python3
"""从已验收的 Phase 1-3 数据回放 Rust Phase 4-6，不触发模型请求。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
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


def _copy_sqlite_snapshot(source_db: Path, replay_db: Path) -> None:
    """复制含 WAL 提交内容的一致性 SQLite 快照。"""
    for suffix in ("", "-wal", "-shm"):
        Path(f"{replay_db}{suffix}").unlink(missing_ok=True)
    with sqlite3.connect(f"file:{source_db}?mode=ro", uri=True) as source:
        with sqlite3.connect(str(replay_db)) as target:
            source.backup(target)


def _phase4_contract_evidence(
    db_path: Path,
    doc_id: str,
    replay_result: dict[str, Any],
    upstream_unchanged: bool,
) -> dict[str, Any]:
    """只读取 Phase4 所有的 translation units 与 freeze blocker 事实。"""
    with sqlite3.connect(str(db_path)) as conn:
        unit_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM fnm_translation_units WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()[0]
        )
        review_rows = conn.execute(
            """
            SELECT chapter_id, page_start, page_end, payload_json, severity
            FROM fnm_structure_reviews
            WHERE doc_id = ? AND review_type = 'freeze_matched_ref_not_injected'
            ORDER BY rowid
            """,
            (doc_id,),
        ).fetchall()

    freeze_blockers = []
    for chapter_id, page_start, page_end, payload_json, severity in review_rows:
        try:
            payload = json.loads(payload_json) if payload_json else None
        except json.JSONDecodeError:
            payload = {"invalid_payload_json": payload_json}
        freeze_blockers.append(
            {
                "chapter_id": chapter_id,
                "page_start": page_start,
                "page_end": page_end,
                "payload": payload,
                "severity": severity,
            }
        )
    reported_freeze_blockers = [
        str(reason)
        for reason in replay_result.get("blocking_reasons") or []
        if "freeze_matched_ref_not_injected" in str(reason)
    ]
    return {
        "passed": (
            bool(replay_result.get("ok"))
            and upstream_unchanged
            and unit_count > 0
            and not freeze_blockers
            and not reported_freeze_blockers
        ),
        "upstream_unchanged": upstream_unchanged,
        "translation_unit_count": unit_count,
        "freeze_blocker_count": len(freeze_blockers),
        "freeze_blockers": freeze_blockers,
        "reported_freeze_blocking_reasons": reported_freeze_blockers,
    }


def _build_summary(
    reports: list[dict[str, Any]], *, phase4_contract_only: bool
) -> dict[str, Any]:
    """同时保留完整回放与阶段 5 专属的两个判定口径。"""
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "persisted_phase1_to_phase3_downstream_replay",
        "model_requests": 0,
        "phase4_contract_only": phase4_contract_only,
        "phase4_contract_passed": all(
            report["phase4_contract_passed"] for report in reports
        ),
        "passed": all(report["passed"] for report in reports),
        "books": reports,
    }
    summary["exit_passed"] = (
        summary["phase4_contract_passed"]
        if phase4_contract_only
        else summary["passed"]
    )
    return summary


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
    _copy_sqlite_snapshot(source_db, replay_db)

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
    phase4_contract = _phase4_contract_evidence(
        replay_db, book.doc_id, result, upstream_unchanged
    )
    report = {
        "slug": book.slug,
        "doc_id": book.doc_id,
        "source_db": str(source_db),
        "replay_db": str(replay_db),
        "upstream_unchanged": upstream_unchanged,
        "upstream_digest": upstream_after,
        "replay": result,
        "phase4_contract": phase4_contract,
        "phase4_contract_passed": phase4_contract["passed"],
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


def _replay_book_isolated(slug: str, output_dir: Path) -> dict[str, Any]:
    """让每本书在独立进程中使用 SQLite/Rust 连接，避免跨书连接状态污染。"""
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--slug",
            slug,
            "--isolated-worker",
            "--worker-output-dir",
            str(output_dir),
        ],
        cwd=str(REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads((output_dir / slug / "result.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--slug",
        action="append",
        dest="slugs",
        help="回放的样本 slug，可重复传入；默认 Biopolitics 与 Goldstein",
    )
    parser.add_argument("--tag", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument(
        "--phase4-contract-only",
        action="store_true",
        help="以 Phase4 冻结/翻译单元合同作为退出状态，保留后续阶段结果仅供观察",
    )
    parser.add_argument("--isolated-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-output-dir", help=argparse.SUPPRESS)
    args = parser.parse_args()
    slugs = args.slugs or ["Biopolitics", "Goldstein"]
    output_dir = (
        Path(args.worker_output_dir) if args.isolated_worker else OUTPUT_ROOT / args.tag
    )
    if args.isolated_worker:
        if len(slugs) != 1:
            parser.error("--isolated-worker 仅允许一个 --slug")
        replay_book(slugs[0], output_dir)
        return 0
    reports = [_replay_book_isolated(slug, output_dir) for slug in slugs]
    summary = _build_summary(reports, phase4_contract_only=args.phase4_contract_only)
    (output_dir / "results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["exit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Freshness checks for FNM golden comparison scripts."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _latest_fnm_run_time(doc_id: str) -> tuple[int, str]:
    if not doc_id:
        return 0, "latest_export_status.json 缺少 doc_id，无法校验产物新鲜度"
    try:
        from persistence.sqlite_store import SQLiteRepository

        repo = SQLiteRepository()
        latest_run = repo.get_latest_fnm_run(doc_id) if hasattr(repo, "get_latest_fnm_run") else None
    except Exception as exc:
        return 0, f"无法读取 SQLite fnm_runs: {exc}"
    if not isinstance(latest_run, dict):
        return 0, "SQLite 中没有对应 doc_id 的 fnm_run，无法校验产物新鲜度"
    return _safe_int(latest_run.get("updated_at") or latest_run.get("created_at")), ""


def assert_export_is_fresh(example_dir: Path, zip_path: Path) -> bool:
    status_path = example_dir / "latest_export_status.json"
    if not status_path.is_file():
        print(f"缺少 latest_export_status.json，拒绝使用可能过期的 ZIP: {zip_path}")
        return False
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"无法读取 latest_export_status.json: {exc}")
        return False

    if bool(status.get("stale")):
        print("latest_export_status.json 已标记 stale，拒绝使用当前 ZIP。")
        return False

    doc_id = str(status.get("doc_id") or "").strip()
    latest_run_at, warning = _latest_fnm_run_time(doc_id)
    if warning:
        print(f"新鲜度校验警告: {warning}")
        return False

    status_generated_at = _safe_int(status.get("generated_at"))
    zip_mtime = int(zip_path.stat().st_mtime) if zip_path.is_file() else 0
    stale_reasons: list[str] = []
    if latest_run_at > 0 and status_generated_at > 0 and status_generated_at < latest_run_at:
        stale_reasons.append(
            f"status generated_at={status_generated_at} 早于 latest fnm_run={latest_run_at}"
        )
    if latest_run_at > 0 and zip_mtime > 0 and zip_mtime < latest_run_at:
        stale_reasons.append(
            f"zip mtime={zip_mtime} 早于 latest fnm_run={latest_run_at}"
        )
    if stale_reasons:
        print("导出产物已过期，拒绝金版对比：")
        for reason in stale_reasons:
            print(f"- {reason}")
        return False
    return True

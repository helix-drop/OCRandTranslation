#!/usr/bin/env python3
"""清理 catalog.db 中已删除文档残留的孤儿 app_state 记录。

用法:
    python3 scripts/cleanup_orphan_state.py           # 实际清理
    python3 scripts/cleanup_orphan_state.py --dry-run  # 仅预览，不清理
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import os

# Add the project root to sys.path so we can import config
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import normalize_doc_id
from persistence.sqlite_db_paths import get_catalog_db_path


def find_orphan_keys(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """找出 app_state 中 doc-scoped key 但文档已不存在的记录。"""
    doc_ids = {
        row[0]
        for row in conn.execute("SELECT id FROM documents").fetchall()
    }
    states = conn.execute(
        "SELECT state_key, state_value FROM app_state"
    ).fetchall()

    orphans: list[tuple[str, str]] = []
    for row in states:
        key = str(row[0] or "")
        if ":" not in key:
            continue
        suffix = normalize_doc_id(key.split(":", 1)[1])
        if suffix and suffix not in doc_ids:
            value_preview = str(row[1] or "")[:60]
            orphans.append((key, value_preview))
    return orphans


def cleanup(dry_run: bool = False) -> None:
    catalog_path = get_catalog_db_path()
    conn = sqlite3.connect(catalog_path)
    conn.row_factory = sqlite3.Row
    try:
        orphans = find_orphan_keys(conn)
        if not orphans:
            print("✓ 没有孤儿 state 记录，catalog.db 状态正常。")
            return

        print(f"发现 {len(orphans)} 条孤儿 state 记录：")
        for key, preview in orphans:
            print(f"  {key} = {preview}...")

        if dry_run:
            print(f"\n[DRY RUN] 共 {len(orphans)} 条，未实际清理。")
            return

        for key, _ in orphans:
            conn.execute(
                "DELETE FROM app_state WHERE state_key = ?",
                (key,),
            )
        conn.commit()
        print(f"\n✓ 已清理 {len(orphans)} 条孤儿 state 记录。")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理 catalog.db 中的孤儿 state 记录")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际清理")
    args = parser.parse_args()
    cleanup(dry_run=args.dry_run)

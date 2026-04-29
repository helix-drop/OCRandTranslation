#!/usr/bin/env python3
"""执行 legacy app.db -> catalog/doc 拆库迁移。"""

from __future__ import annotations

import argparse
import json

from persistence.sqlite_split_migration import migrate_legacy_app_db


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移到 catalog.db + per-doc doc.db")
    parser.add_argument("--no-backup", action="store_true", help="不备份 legacy app.db")
    parser.add_argument(
        "--keep-doc-db",
        action="store_true",
        help="保留已存在的 doc.db（默认覆盖）",
    )
    args = parser.parse_args()

    report = migrate_legacy_app_db(
        backup_legacy=not args.no_backup,
        overwrite_doc_dbs=not args.keep_doc_db,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


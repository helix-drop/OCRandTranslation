"""SQLite 初始化入口。"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterable

from config import get_sqlite_db_path, normalize_doc_id
from persistence.sqlite_catalog_schema import initialize_catalog_database
from persistence.sqlite_db_paths import get_catalog_db_path, get_document_db_path
from persistence.sqlite_schema import initialize_database
from persistence.sqlite_split_migration import (
    migrate_legacy_app_db,
    should_run_split_migration,
)

logger = logging.getLogger(__name__)


def _recover_orphan_documents(catalog_db_path: str, docs_dir: str) -> int:
    """扫描 documents/ 目录，将有 doc.db 但不在 catalog 中的文档注册进去。

    返回恢复的文档数量。
    """
    if not os.path.isdir(docs_dir):
        return 0
    catalog_conn = sqlite3.connect(catalog_db_path)
    catalog_conn.row_factory = sqlite3.Row
    recovered = 0
    try:
        existing_ids: set[str] = {
            str(row[0])
            for row in catalog_conn.execute("SELECT id FROM documents").fetchall()
        }
        for entry in os.scandir(docs_dir):
            if not entry.is_dir():
                continue
            doc_id = normalize_doc_id(entry.name)
            if not doc_id or doc_id in existing_ids:
                continue
            doc_db_path = os.path.join(entry.path, "doc.db")
            if not os.path.exists(doc_db_path):
                continue
            # 从 doc.db 读取文档元数据并注册到 catalog
            doc_conn = sqlite3.connect(doc_db_path)
            doc_conn.row_factory = sqlite3.Row
            try:
                row = doc_conn.execute(
                    "SELECT * FROM documents WHERE id = ? LIMIT 1",
                    (doc_id,),
                ).fetchone()
                if not row:
                    continue
                cols = row.keys()
                catalog_cols = {
                    r[1]
                    for r in catalog_conn.execute("PRAGMA table_info(documents)").fetchall()
                }
                shared_cols = [c for c in cols if c in catalog_cols]
                if not shared_cols:
                    continue
                col_sql = ", ".join(shared_cols)
                placeholders = ", ".join(["?"] * len(shared_cols))
                values = tuple(row[c] for c in shared_cols)
                catalog_conn.execute(
                    f"INSERT OR IGNORE INTO documents ({col_sql}) VALUES ({placeholders})",
                    values,
                )
                catalog_conn.commit()
                existing_ids.add(doc_id)
                recovered += 1
                logger.info("已恢复孤儿文档 doc_id=%s", doc_id)
            except Exception:
                logger.exception("恢复孤儿文档失败 doc_id=%s", doc_id)
            finally:
                doc_conn.close()
    finally:
        catalog_conn.close()
    return recovered


def initialize_runtime_databases(
    *,
    include_legacy_app_db: bool = False,
    include_catalog_db: bool = True,
    auto_migrate_split: bool = True,
    recover_orphan_docs: bool = True,
    document_ids: Iterable[str] | None = None,
) -> dict[str, str]:
    """显式初始化当前进程要使用的 SQLite 数据库。"""
    from config import DOCS_DIR

    results: dict[str, str] = {}
    if include_catalog_db:
        catalog_db_path = get_catalog_db_path()
        results[catalog_db_path] = initialize_catalog_database(catalog_db_path)
    if include_legacy_app_db:
        app_db_path = get_sqlite_db_path()
        results[app_db_path] = initialize_database(app_db_path)
    if auto_migrate_split and include_catalog_db and should_run_split_migration():
        migrate_legacy_app_db(backup_legacy=True, overwrite_doc_dbs=True)
    if recover_orphan_docs and include_catalog_db:
        _recover_orphan_documents(get_catalog_db_path(), DOCS_DIR)
    for raw_doc_id in document_ids or ():
        doc_id = normalize_doc_id(raw_doc_id)
        if not doc_id:
            continue
        doc_db_path = get_document_db_path(doc_id)
        results[doc_db_path] = initialize_database(doc_db_path)
    return results

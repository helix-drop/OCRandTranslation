"""legacy app.db -> catalog/doc 拆库迁移。"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from dataclasses import dataclass

from config import get_sqlite_db_path, normalize_doc_id
from persistence.sqlite_catalog_schema import initialize_catalog_database
from persistence.sqlite_db_paths import get_catalog_db_path, get_document_db_path
from persistence.sqlite_schema import initialize_database


DOC_SCOPED_TABLES = (
    "pages",
    "translation_pages",
    "translation_segments",
    "translate_runs",
    "translate_failures",
    "fnm_runs",
    "fnm_translation_units",
    "fnm_review_overrides_v2",
    "fnm_pages",
    "fnm_chapters",
    "fnm_heading_candidates",
    "fnm_note_regions",
    "fnm_chapter_note_modes",
    "fnm_section_heads",
    "fnm_note_items",
    "fnm_body_anchors",
    "fnm_note_links",
    "fnm_structure_reviews",
    "fnm_phase_runs",
    "fnm_dev_snapshots",
)


@dataclass
class MigrationStats:
    migrated_documents: int = 0
    migrated_doc_dbs: int = 0
    migrated_rows: int = 0
    migrated_global_state_keys: int = 0
    migrated_doc_state_keys: int = 0

    def to_dict(self) -> dict:
        return {
            "migrated_documents": self.migrated_documents,
            "migrated_doc_dbs": self.migrated_doc_dbs,
            "migrated_rows": self.migrated_rows,
            "migrated_global_state_keys": self.migrated_global_state_keys,
            "migrated_doc_state_keys": self.migrated_doc_state_keys,
        }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _insert_rows(conn: sqlite3.Connection, table: str, rows: list[sqlite3.Row]) -> int:
    if not rows:
        return 0
    columns = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    col_sql = ", ".join(columns)
    sql = f"INSERT OR REPLACE INTO {table} ({col_sql}) VALUES ({placeholders})"
    payload = [tuple(row[col] for col in columns) for row in rows]
    conn.executemany(sql, payload)
    return len(rows)


def _copy_doc_table(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    table: str,
    doc_id: str,
) -> int:
    if not _table_exists(src, table):
        return 0
    columns = _table_columns(src, table)
    if "doc_id" in columns:
        rows = src.execute(f"SELECT * FROM {table} WHERE doc_id = ?", (doc_id,)).fetchall()
    elif table == "translation_segments":
        rows = src.execute(
            """
            SELECT ts.*
            FROM translation_segments ts
            JOIN translation_pages tp ON tp.id = ts.translation_page_id
            WHERE tp.doc_id = ?
            """,
            (doc_id,),
        ).fetchall()
    else:
        rows = []
    return _insert_rows(dst, table, rows)


def _copy_revision_tables(src: sqlite3.Connection, dst: sqlite3.Connection, doc_id: str) -> int:
    count = 0
    if _table_exists(src, "segment_revisions"):
        rows = src.execute(
            """
            SELECT sr.*
            FROM segment_revisions sr
            JOIN translation_pages tp ON tp.id = sr.translation_page_id
            WHERE tp.doc_id = ?
            """,
            (doc_id,),
        ).fetchall()
        count += _insert_rows(dst, "segment_revisions", rows)
    if _table_exists(src, "translation_page_revisions"):
        rows = src.execute(
            """
            SELECT pr.*
            FROM translation_page_revisions pr
            JOIN translation_pages tp ON tp.id = pr.translation_page_id
            WHERE tp.doc_id = ?
            """,
            (doc_id,),
        ).fetchall()
        count += _insert_rows(dst, "translation_page_revisions", rows)
    return count


SPLIT_MIGRATION_DONE_KEY = "split_migration_done"


def _is_migration_marked_done(catalog_path: str) -> bool:
    """检查 catalog.db 是否已写入迁移完成标记。"""
    if not os.path.exists(catalog_path):
        return False
    conn = sqlite3.connect(catalog_path)
    try:
        if not _table_exists(conn, "schema_meta"):
            return False
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?",
            (SPLIT_MIGRATION_DONE_KEY,),
        ).fetchone()
        return bool(row and row[0] == "1")
    except Exception:
        return False
    finally:
        conn.close()


def _mark_migration_done(catalog_path: str) -> None:
    """在 catalog.db 的 schema_meta 中写入迁移完成标记。"""
    conn = sqlite3.connect(catalog_path)
    try:
        conn.execute(
            """
            INSERT INTO schema_meta(key, value)
            VALUES (?, '1')
            ON CONFLICT(key) DO UPDATE SET value='1'
            """,
            (SPLIT_MIGRATION_DONE_KEY,),
        )
        conn.commit()
    finally:
        conn.close()


def should_run_split_migration(
    *,
    legacy_db_path: str | None = None,
    catalog_db_path: str | None = None,
) -> bool:
    legacy_path = legacy_db_path or get_sqlite_db_path()
    catalog_path = catalog_db_path or get_catalog_db_path()
    if not os.path.exists(legacy_path):
        return False
    # 已写入完成标记 → 不再重复迁移
    if _is_migration_marked_done(catalog_path):
        return False
    if not os.path.exists(catalog_path):
        return True
    legacy_conn = sqlite3.connect(legacy_path)
    catalog_conn = sqlite3.connect(catalog_path)
    try:
        legacy_has_docs = _table_exists(legacy_conn, "documents")
        if not legacy_has_docs:
            return False
        legacy_count = int(legacy_conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        if legacy_count == 0:
            return False
        if not _table_exists(catalog_conn, "documents"):
            return True
        catalog_count = int(catalog_conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        return catalog_count == 0
    finally:
        legacy_conn.close()
        catalog_conn.close()


def migrate_legacy_app_db(
    *,
    legacy_db_path: str | None = None,
    catalog_db_path: str | None = None,
    backup_legacy: bool = True,
    overwrite_doc_dbs: bool = True,
) -> dict:
    legacy_path = legacy_db_path or get_sqlite_db_path()
    catalog_path = catalog_db_path or get_catalog_db_path()
    if not os.path.exists(legacy_path):
        raise FileNotFoundError(f"legacy app.db 不存在: {legacy_path}")

    if backup_legacy:
        ts = time.strftime("%Y%m%d%H%M%S")
        backup_path = f"{legacy_path}.bak.{ts}"
        if not os.path.exists(backup_path):
            shutil.copy2(legacy_path, backup_path)

    initialize_catalog_database(catalog_path)
    stats = MigrationStats()

    src = sqlite3.connect(legacy_path)
    src.row_factory = sqlite3.Row
    catalog = sqlite3.connect(catalog_path)
    catalog.row_factory = sqlite3.Row
    try:
        documents = src.execute("SELECT * FROM documents ORDER BY id ASC").fetchall()
        if documents:
            catalog_rows = []
            for row in documents:
                catalog_rows.append({
                    "id": row["id"],
                    "name": row["name"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "page_count": row["page_count"],
                    "entry_count": row["entry_count"],
                    "last_entry_idx": row["last_entry_idx"],
                    "cleanup_headers_footers": row["cleanup_headers_footers"],
                    "auto_visual_toc_enabled": row["auto_visual_toc_enabled"],
                    "toc_visual_status": row["toc_visual_status"],
                    "toc_visual_message": row["toc_visual_message"],
                    "toc_visual_model_id": row["toc_visual_model_id"],
                    "toc_visual_phase": row["toc_visual_phase"],
                    "toc_visual_progress_pct": row["toc_visual_progress_pct"],
                    "toc_visual_progress_label": row["toc_visual_progress_label"],
                    "toc_visual_progress_detail": row["toc_visual_progress_detail"],
                })
            cols = list(catalog_rows[0].keys())
            sql = f"""
                INSERT OR REPLACE INTO documents ({", ".join(cols)})
                VALUES ({", ".join(["?"] * len(cols))})
            """
            catalog.executemany(sql, [tuple(item[c] for c in cols) for item in catalog_rows])
            stats.migrated_documents = len(catalog_rows)

        app_state_rows = []
        if _table_exists(src, "app_state"):
            app_state_rows = src.execute("SELECT state_key, state_value, updated_at FROM app_state").fetchall()
        doc_ids = {normalize_doc_id(row["id"]) for row in documents}
        doc_ids.discard("")
        doc_state_map: dict[str, list[sqlite3.Row]] = {doc_id: [] for doc_id in doc_ids}
        global_state_rows: list[sqlite3.Row] = []
        skipped_orphan_keys = 0
        for row in app_state_rows:
            key = str(row["state_key"] or "")
            if ":" in key:
                suffix = normalize_doc_id(key.split(":", 1)[1])
                if suffix in doc_state_map:
                    doc_state_map[suffix].append(row)
                    continue
                # doc-scoped key 但对应文档已不存在，丢弃
                skipped_orphan_keys += 1
                continue
            global_state_rows.append(row)
        if global_state_rows:
            _insert_rows(catalog, "app_state", global_state_rows)
            stats.migrated_global_state_keys = len(global_state_rows)
        catalog.commit()

        for row in documents:
            doc_id = normalize_doc_id(row["id"])
            if not doc_id:
                continue
            doc_db_path = get_document_db_path(doc_id)
            if overwrite_doc_dbs and os.path.exists(doc_db_path):
                os.unlink(doc_db_path)
            initialize_database(doc_db_path)
            dst = sqlite3.connect(doc_db_path)
            dst.row_factory = sqlite3.Row
            try:
                # 保留一份文档元数据，便于 doc.db 独立诊断。
                _insert_rows(dst, "documents", [row])
                copied = 1
                for table in DOC_SCOPED_TABLES:
                    copied += _copy_doc_table(src, dst, table, doc_id)
                copied += _copy_revision_tables(src, dst, doc_id)
                per_doc_state = doc_state_map.get(doc_id) or []
                if per_doc_state:
                    copied += _insert_rows(dst, "app_state", per_doc_state)
                    stats.migrated_doc_state_keys += len(per_doc_state)
                dst.commit()
                stats.migrated_rows += copied
                stats.migrated_doc_dbs += 1
            finally:
                dst.close()
    finally:
        src.close()
        catalog.close()

    # 迁移成功：写入完成标记，防止下次启动时重复迁移（僵尸循环）。
    _mark_migration_done(catalog_path)

    # 重命名 legacy app.db，释放磁盘空间并彻底阻断重迁触发。
    migrated_path = f"{legacy_path}.migrated"
    try:
        if not os.path.exists(migrated_path):
            os.rename(legacy_path, migrated_path)
    except OSError:
        pass  # 重命名失败不影响迁移结果，标记已写入

    return {
        "legacy_db_path": legacy_path,
        "catalog_db_path": catalog_path,
        "migrated_legacy_path": migrated_path if os.path.exists(migrated_path) else legacy_path,
        **stats.to_dict(),
    }

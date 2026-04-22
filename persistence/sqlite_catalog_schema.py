"""catalog.db 专用 schema。"""

from __future__ import annotations

import sqlite3

from config import ensure_dirs
from persistence.sqlite_schema import get_connection

CATALOG_SCHEMA_VERSION = 2


_DOCUMENT_REQUIRED_COLUMNS = {
    "has_pdf": "INTEGER NOT NULL DEFAULT 0",
    "status": "TEXT NOT NULL DEFAULT 'ready'",
    "source_pdf_path": "TEXT",
    "toc_json": "TEXT",
    "toc_user_json": "TEXT",
    "toc_auto_pdf_json": "TEXT",
    "toc_auto_visual_json": "TEXT",
    "toc_source": "TEXT NOT NULL DEFAULT 'auto'",
    "toc_page_offset": "INTEGER NOT NULL DEFAULT 0",
    "toc_file_name": "TEXT",
    "toc_file_uploaded_at": "INTEGER",
}


def _read_catalog_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            """
            SELECT value
            FROM schema_meta
            WHERE key = 'catalog_schema_version'
            """
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return 0
        raise
    if not row:
        return 0
    try:
        return int(row[0] or 0)
    except Exception:
        return 0


def _create_catalog_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            page_count INTEGER NOT NULL DEFAULT 0,
            entry_count INTEGER NOT NULL DEFAULT 0,
            has_pdf INTEGER NOT NULL DEFAULT 0,
            last_entry_idx INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ready',
            source_pdf_path TEXT,
            toc_json TEXT,
            toc_user_json TEXT,
            toc_auto_pdf_json TEXT,
            toc_auto_visual_json TEXT,
            cleanup_headers_footers INTEGER NOT NULL DEFAULT 1,
            auto_visual_toc_enabled INTEGER NOT NULL DEFAULT 0,
            toc_visual_status TEXT NOT NULL DEFAULT 'idle',
            toc_visual_message TEXT,
            toc_visual_model_id TEXT,
            toc_visual_phase TEXT,
            toc_visual_progress_pct INTEGER NOT NULL DEFAULT 0,
            toc_visual_progress_label TEXT,
            toc_visual_progress_detail TEXT,
            toc_source TEXT NOT NULL DEFAULT 'auto',
            toc_page_offset INTEGER NOT NULL DEFAULT 0,
            toc_file_name TEXT,
            toc_file_uploaded_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents(updated_at);

        CREATE TABLE IF NOT EXISTS app_state (
            state_key TEXT PRIMARY KEY,
            state_value TEXT,
            updated_at INTEGER
        );
        """
    )
    conn.execute(
        """
        INSERT INTO schema_meta(key, value)
        VALUES ('catalog_schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (str(CATALOG_SCHEMA_VERSION),),
    )


def _ensure_documents_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(documents)").fetchall()
    }
    for col, ddl in _DOCUMENT_REQUIRED_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {ddl}")


def initialize_catalog_database(db_path: str) -> str:
    """初始化 catalog.db，仅创建全局轻量表。"""
    ensure_dirs()
    conn = get_connection(db_path)
    try:
        if _read_catalog_schema_version(conn) < CATALOG_SCHEMA_VERSION:
            _create_catalog_schema(conn)
            _ensure_documents_columns(conn)
            conn.commit()
        else:
            _ensure_documents_columns(conn)
            conn.commit()
        row = conn.execute("PRAGMA journal_mode").fetchone()
        return row[0] if row else ""
    finally:
        conn.close()

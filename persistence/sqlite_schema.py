"""SQLite schema 定义、迁移与连接管理。

从 sqlite_store.py 提取，保持 schema 版本、表结构、字段迁移和连接工具在一处。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager

from config import ensure_dirs, get_sqlite_db_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 25
_schema_init_lock = threading.Lock()

# ---- TOC 来源常量 ----
TOC_SOURCE_AUTO = "auto"
TOC_SOURCE_USER = "user"
TOC_SOURCE_AUTO_VISUAL = "auto_visual"
TOC_SOURCE_AUTO_PDF = "auto_pdf"
TOC_SOURCES = {
    TOC_SOURCE_AUTO,
    TOC_SOURCE_USER,
    TOC_SOURCE_AUTO_VISUAL,
    TOC_SOURCE_AUTO_PDF,
}


def _toc_column_for_source(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized == TOC_SOURCE_USER:
        return "toc_user_json"
    if normalized == TOC_SOURCE_AUTO_VISUAL:
        return "toc_auto_visual_json"
    if normalized in {TOC_SOURCE_AUTO, TOC_SOURCE_AUTO_PDF}:
        return "toc_auto_pdf_json"
    raise ValueError(f"不支持的目录来源: {source}")


# ---- 连接与 Pragma ----


class ManagedConnection(sqlite3.Connection):
    """让 `with get_connection(...)` 在退出时也显式关闭连接。"""

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(
        db_path or get_sqlite_db_path(),
        factory=ManagedConnection,
    )
    try:
        conn.row_factory = sqlite3.Row
        _apply_pragmas(conn)
        return conn
    except Exception:
        conn.close()
        raise


def _read_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            """
            SELECT value
            FROM schema_meta
            WHERE key = 'schema_version'
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


def initialize_database(db_path: str | None = None) -> str:
    with _schema_init_lock:
        conn = get_connection(db_path)
        try:
            if _read_schema_version(conn) < SCHEMA_VERSION:
                _create_schema(conn)
            else:
                # 旧进程可能已写入最新 schema_version，但中途缺少后续新增列。
                # 这里保持幂等补迁移，避免现有文档库读取状态时因缺列 500。
                _create_core_tables(conn)
                _migrate_documents_schema(conn)
                _migrate_translation_schema(conn)
                _write_schema_version(conn)
            conn.commit()
            row = conn.execute("PRAGMA journal_mode").fetchone()
            return row[0] if row else ""
        finally:
            conn.close()


@contextmanager
def transaction(db_path: str | None = None):
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        logger.exception("数据库事务回滚")
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def read_connection(db_path: str | None = None):
    """只读/查询连接：退出时显式关闭，避免 FD 泄漏。"""
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


# ---- Schema 迁移辅助 ----


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not _column_exists(conn, table, column):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        except sqlite3.OperationalError as exc:
            # 并发初始化时可能出现“检查时不存在、执行时已被其他连接补上”的竞态。
            if "duplicate column name" not in str(exc).lower():
                raise


def _ensure_columns(
    conn: sqlite3.Connection,
    table: str,
    columns: tuple[tuple[str, str], ...],
) -> None:
    for column, ddl in columns:
        _ensure_column(conn, table, column, ddl)



# ---- Schema 创建与迁移 ----


def _create_schema(conn: sqlite3.Connection) -> None:
    _create_core_tables(conn)
    _migrate_documents_schema(conn)
    _migrate_translation_schema(conn)
    _write_schema_version(conn)


def _create_core_tables(conn: sqlite3.Connection) -> None:
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
            toc_visual_progress_detail TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents(updated_at);

        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            book_page INTEGER NOT NULL,
            file_idx INTEGER NOT NULL,
            img_w INTEGER,
            img_h INTEGER,
            markdown TEXT,
            footnotes TEXT,
            text_source TEXT NOT NULL DEFAULT 'ocr',
            payload_json TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, book_page),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_pages_doc_file ON pages(doc_id, file_idx);

        CREATE TABLE IF NOT EXISTS translation_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            run_id INTEGER,
            book_page INTEGER NOT NULL,
            model_source TEXT,
            model_key TEXT,
            model_id TEXT,
            provider TEXT,
            status TEXT NOT NULL DEFAULT 'done',
            pages_label TEXT,
            usage_json TEXT,
            error_message TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, book_page),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY(run_id) REFERENCES translate_runs(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_translation_pages_doc_status
            ON translation_pages(doc_id, status);

        CREATE TABLE IF NOT EXISTS translation_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            translation_page_id INTEGER NOT NULL,
            segment_index INTEGER NOT NULL,
            original_text TEXT,
            translation_text TEXT,
            manual_translation_text TEXT,
            translation_source TEXT NOT NULL DEFAULT 'model',
            manual_updated_at INTEGER,
            manual_updated_by TEXT,
            footnotes_text TEXT,
            footnotes_translation_text TEXT,
            pages_label TEXT,
            start_book_page INTEGER,
            end_book_page INTEGER,
            print_page_label TEXT,
            note_kind TEXT,
            note_marker TEXT,
            note_number INTEGER,
            note_section_title TEXT,
            note_confidence REAL NOT NULL DEFAULT 0,
            heading_level INTEGER NOT NULL DEFAULT 0,
            segment_status TEXT NOT NULL DEFAULT 'done',
            error_message TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(translation_page_id, segment_index),
            FOREIGN KEY(translation_page_id) REFERENCES translation_pages(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS translate_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            execution_mode TEXT,
            model_source TEXT,
            model_key TEXT,
            model_id TEXT,
            provider TEXT,
            translation_model_label TEXT,
            translation_model_id TEXT,
            companion_model_label TEXT,
            companion_model_id TEXT,
            start_bp INTEGER,
            current_bp INTEGER,
            resume_bp INTEGER,
            stop_requested INTEGER NOT NULL DEFAULT 0,
            running INTEGER NOT NULL DEFAULT 0,
            done_pages INTEGER NOT NULL DEFAULT 0,
            total_pages INTEGER NOT NULL DEFAULT 0,
            processed_pages INTEGER NOT NULL DEFAULT 0,
            pending_pages INTEGER NOT NULL DEFAULT 0,
            current_page_idx INTEGER NOT NULL DEFAULT 0,
            translated_paras INTEGER NOT NULL DEFAULT 0,
            translated_chars INTEGER NOT NULL DEFAULT 0,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            request_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            failed_bps_json TEXT,
            partial_failed_bps_json TEXT,
            failed_pages_json TEXT,
            retry_round INTEGER NOT NULL DEFAULT 0,
            unresolved_count INTEGER NOT NULL DEFAULT 0,
            manual_required_count INTEGER NOT NULL DEFAULT 0,
            export_bundle_available INTEGER NOT NULL DEFAULT 0,
            export_has_blockers INTEGER NOT NULL DEFAULT 0,
            tail_blocking_summary_json TEXT,
            translation_attempt_history_json TEXT,
            next_failed_location_json TEXT,
            failed_locations_json TEXT,
            manual_required_locations_json TEXT,
            task_json TEXT,
            draft_json TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_translate_runs_doc_updated
            ON translate_runs(doc_id, updated_at);

        CREATE TABLE IF NOT EXISTS translate_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            run_id INTEGER,
            book_page INTEGER NOT NULL,
            failure_type TEXT NOT NULL,
            error_message TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            resolved_at INTEGER,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY(run_id) REFERENCES translate_runs(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_translate_failures_doc_page
            ON translate_failures(doc_id, book_page);

        CREATE TABLE IF NOT EXISTS app_state (
            state_key TEXT PRIMARY KEY,
            state_value TEXT,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS segment_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            translation_page_id INTEGER NOT NULL,
            segment_index INTEGER NOT NULL,
            revision_source TEXT NOT NULL,
            original_text TEXT,
            translation_text TEXT,
            manual_translation_text TEXT,
            run_id INTEGER,
            updated_by TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(translation_page_id) REFERENCES translation_pages(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_seg_rev_page_idx
            ON segment_revisions(translation_page_id, segment_index, created_at);

        CREATE TABLE IF NOT EXISTS translation_page_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            translation_page_id INTEGER NOT NULL,
            revision_source TEXT NOT NULL,
            entry_json TEXT NOT NULL,
            updated_by TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(translation_page_id) REFERENCES translation_pages(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_page_rev_page_created
            ON translation_page_revisions(translation_page_id, created_at);

        """
    )


def _migrate_documents_schema(conn: sqlite3.Connection) -> None:
    _ensure_columns(
        conn,
        "documents",
        (
            ("toc_json", "toc_json TEXT"),
            ("toc_source", "toc_source TEXT NOT NULL DEFAULT 'auto'"),
            ("toc_page_offset", "toc_page_offset INTEGER NOT NULL DEFAULT 0"),
            ("toc_file_name", "toc_file_name TEXT"),
            ("toc_file_uploaded_at", "toc_file_uploaded_at INTEGER"),
            (
                "cleanup_headers_footers",
                "cleanup_headers_footers INTEGER NOT NULL DEFAULT 1",
            ),
            ("toc_user_json", "toc_user_json TEXT"),
            ("toc_auto_pdf_json", "toc_auto_pdf_json TEXT"),
            ("toc_auto_visual_json", "toc_auto_visual_json TEXT"),
            (
                "auto_visual_toc_enabled",
                "auto_visual_toc_enabled INTEGER NOT NULL DEFAULT 0",
            ),
            ("toc_visual_status", "toc_visual_status TEXT NOT NULL DEFAULT 'idle'"),
            ("toc_visual_message", "toc_visual_message TEXT"),
            ("toc_visual_model_id", "toc_visual_model_id TEXT"),
            ("toc_visual_phase", "toc_visual_phase TEXT"),
            (
                "toc_visual_progress_pct",
                "toc_visual_progress_pct INTEGER NOT NULL DEFAULT 0",
            ),
            ("toc_visual_progress_label", "toc_visual_progress_label TEXT"),
            ("toc_visual_progress_detail", "toc_visual_progress_detail TEXT"),
        ),
    )
    _backfill_document_toc_columns(conn)


def _backfill_document_toc_columns(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE documents
        SET toc_user_json = CASE
                WHEN COALESCE(toc_user_json, '') = ''
                 AND COALESCE(toc_source, 'auto') = 'user'
                 AND COALESCE(toc_json, '') <> ''
                THEN toc_json
                ELSE toc_user_json
            END,
            toc_auto_pdf_json = CASE
                WHEN COALESCE(toc_auto_pdf_json, '') = ''
                 AND COALESCE(toc_source, 'auto') <> 'user'
                 AND COALESCE(toc_json, '') <> ''
                THEN toc_json
                ELSE toc_auto_pdf_json
            END
        WHERE COALESCE(toc_json, '') <> ''
        """
    )


def _migrate_translation_schema(conn: sqlite3.Connection) -> None:
    _ensure_columns(
        conn,
        "translation_pages",
        (
            ("model_source", "model_source TEXT"),
            ("model_key", "model_key TEXT"),
            ("model_id", "model_id TEXT"),
            ("provider", "provider TEXT"),
        ),
    )
    _ensure_columns(
        conn,
        "translate_runs",
        (
            ("execution_mode", "execution_mode TEXT"),
            ("model_source", "model_source TEXT"),
            ("model_key", "model_key TEXT"),
            ("model_id", "model_id TEXT"),
            ("provider", "provider TEXT"),
            ("retry_round", "retry_round INTEGER NOT NULL DEFAULT 0"),
            ("unresolved_count", "unresolved_count INTEGER NOT NULL DEFAULT 0"),
            (
                "manual_required_count",
                "manual_required_count INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "export_bundle_available",
                "export_bundle_available INTEGER NOT NULL DEFAULT 0",
            ),
            ("export_has_blockers", "export_has_blockers INTEGER NOT NULL DEFAULT 0"),
            ("tail_blocking_summary_json", "tail_blocking_summary_json TEXT"),
            (
                "translation_attempt_history_json",
                "translation_attempt_history_json TEXT",
            ),
            ("next_failed_location_json", "next_failed_location_json TEXT"),
            ("failed_locations_json", "failed_locations_json TEXT"),
            ("manual_required_locations_json", "manual_required_locations_json TEXT"),
            ("task_json", "task_json TEXT"),
            ("translation_model_label", "translation_model_label TEXT"),
            ("translation_model_id", "translation_model_id TEXT"),
            ("companion_model_label", "companion_model_label TEXT"),
            ("companion_model_id", "companion_model_id TEXT"),
        ),
    )
    _backfill_translation_model_identity(conn)
    _ensure_columns(
        conn,
        "translation_segments",
        (
            ("manual_translation_text", "manual_translation_text TEXT"),
            ("translation_source", "translation_source TEXT NOT NULL DEFAULT 'model'"),
            ("manual_updated_at", "manual_updated_at INTEGER"),
            ("manual_updated_by", "manual_updated_by TEXT"),
            ("pages_label", "pages_label TEXT"),
            ("start_book_page", "start_book_page INTEGER"),
            ("end_book_page", "end_book_page INTEGER"),
            ("print_page_label", "print_page_label TEXT"),
            ("note_kind", "note_kind TEXT"),
            ("note_marker", "note_marker TEXT"),
            ("note_number", "note_number INTEGER"),
            ("note_section_title", "note_section_title TEXT"),
            ("note_confidence", "note_confidence REAL NOT NULL DEFAULT 0"),
            ("manual_original_text", "manual_original_text TEXT"),
        ),
    )
    _ensure_columns(
        conn,
        "segment_revisions",
        (("manual_original_text", "manual_original_text TEXT"),),
    )


def _backfill_translation_model_identity(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE translation_pages
        SET model_source = COALESCE(NULLIF(model_source, ''), 'builtin'),
            model_id = COALESCE(NULLIF(model_id, ''), model_key),
            provider = COALESCE(
                NULLIF(provider, ''),
                CASE
                    WHEN model_key LIKE 'qwen-%' THEN 'qwen'
                    WHEN model_key LIKE 'deepseek-%' THEN 'deepseek'
                    ELSE ''
                END
            )
        """
    )
    conn.execute(
        """
        UPDATE translate_runs
        SET model_source = COALESCE(NULLIF(model_source, ''), 'builtin'),
            model_id = COALESCE(NULLIF(model_id, ''), model_key),
            provider = COALESCE(
                NULLIF(provider, ''),
                CASE
                    WHEN model_key LIKE 'qwen-%' THEN 'qwen'
                    WHEN model_key LIKE 'deepseek-%' THEN 'deepseek'
                    ELSE ''
                END
            )
        """
    )



def _write_schema_version(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO schema_meta(key, value)
        VALUES ('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (str(SCHEMA_VERSION),),
    )

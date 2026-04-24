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

SCHEMA_VERSION = 24
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
                _migrate_fnm_schema(conn)
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


def _drop_retired_fnm_v2_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name GLOB 'fnm_*_v2'
        """
    ).fetchall()
    for row in rows:
        table_name = str(row["name"] or "").strip()
        if not table_name or table_name == "fnm_review_overrides_v2":
            continue
        safe_table_name = table_name.replace('"', '""')
        conn.execute(f'DROP TABLE IF EXISTS "{safe_table_name}"')


# ---- Schema 创建与迁移 ----


def _create_schema(conn: sqlite3.Connection) -> None:
    _create_core_tables(conn)
    _migrate_documents_schema(conn)
    _migrate_translation_schema(conn)
    _migrate_fnm_schema(conn)
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
            fnm_tail_state TEXT,
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

        CREATE TABLE IF NOT EXISTS fnm_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            error_msg TEXT,
            page_count INTEGER NOT NULL DEFAULT 0,
            section_count INTEGER NOT NULL DEFAULT 0,
            note_count INTEGER NOT NULL DEFAULT 0,
            unit_count INTEGER NOT NULL DEFAULT 0,
            validation_json TEXT,
            structure_state TEXT,
            review_counts_json TEXT,
            blocking_reasons_json TEXT,
            link_summary_json TEXT,
            page_partition_summary_json TEXT,
            chapter_mode_summary_json TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_runs_doc_updated
            ON fnm_runs(doc_id, updated_at);

        CREATE TABLE IF NOT EXISTS fnm_translation_units (
            unit_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            owner_kind TEXT,
            owner_id TEXT,
            section_id TEXT NOT NULL,
            section_title TEXT,
            section_start_page INTEGER,
            section_end_page INTEGER,
            note_id TEXT,
            page_start INTEGER,
            page_end INTEGER,
            char_count INTEGER NOT NULL DEFAULT 0,
            source_text TEXT,
            translated_text TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error_msg TEXT,
            target_ref TEXT,
            page_segments_json TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_units_doc_status
            ON fnm_translation_units(doc_id, status, kind, page_start, page_end);
        CREATE INDEX IF NOT EXISTS idx_fnm_units_doc_section
            ON fnm_translation_units(doc_id, section_id, kind, page_start, page_end);

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
            ("fnm_tail_state", "fnm_tail_state TEXT"),
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


def _migrate_fnm_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS fnm_review_overrides_v2 (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            target_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, scope, target_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_review_overrides_v2_doc_scope
            ON fnm_review_overrides_v2(doc_id, scope, target_id);

        CREATE TABLE IF NOT EXISTS fnm_pages (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            target_pdf_page INTEGER,
            page_role TEXT NOT NULL,
            role_confidence REAL NOT NULL DEFAULT 0,
            role_reason TEXT,
            section_hint TEXT,
            has_note_heading INTEGER NOT NULL DEFAULT 0,
            note_scan_summary_json TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, page_no),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_pages_doc_role
            ON fnm_pages(doc_id, page_no, page_role);

        CREATE TABLE IF NOT EXISTS fnm_chapters (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            chapter_id TEXT NOT NULL,
            title TEXT,
            start_page INTEGER NOT NULL,
            end_page INTEGER NOT NULL,
            pages_json TEXT,
            source TEXT,
            boundary_state TEXT NOT NULL DEFAULT 'ready',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, chapter_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_chapters_doc_page
            ON fnm_chapters(doc_id, start_page, end_page);

        CREATE TABLE IF NOT EXISTS fnm_heading_candidates (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            heading_id TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            text TEXT NOT NULL,
            normalized_text TEXT NOT NULL,
            source TEXT NOT NULL CHECK(source IN ('visual_toc', 'ocr_block', 'pdf_font_band', 'markdown_heading', 'note_heading')),
            block_label TEXT,
            top_band INTEGER NOT NULL DEFAULT 0,
            font_height REAL,
            x REAL,
            y REAL,
            width_estimate REAL,
            confidence REAL NOT NULL DEFAULT 0,
            heading_family_guess TEXT NOT NULL CHECK(heading_family_guess IN ('book', 'chapter', 'section', 'note', 'other', 'unknown')),
            suppressed_as_chapter INTEGER NOT NULL DEFAULT 0,
            reject_reason TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, heading_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_heading_candidates_doc_page
            ON fnm_heading_candidates(doc_id, page_no, source, heading_family_guess);

        CREATE TABLE IF NOT EXISTS fnm_note_regions (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            region_id TEXT NOT NULL,
            region_kind TEXT NOT NULL,
            start_page INTEGER NOT NULL,
            end_page INTEGER NOT NULL,
            pages_json TEXT,
            title_hint TEXT,
            bound_chapter_id TEXT,
            region_start_first_source_marker TEXT,
            region_first_note_item_marker TEXT,
            region_marker_alignment_ok INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, region_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_note_regions_doc_page
            ON fnm_note_regions(doc_id, start_page, end_page, region_kind);

        CREATE TABLE IF NOT EXISTS fnm_chapter_note_modes (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            chapter_id TEXT NOT NULL,
            chapter_title TEXT,
            note_mode TEXT NOT NULL,
            sampled_pages_json TEXT,
            detection_confidence REAL NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, chapter_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_chapter_note_modes_doc_mode
            ON fnm_chapter_note_modes(doc_id, note_mode);

        CREATE TABLE IF NOT EXISTS fnm_section_heads (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            section_head_id TEXT NOT NULL,
            chapter_id TEXT,
            page_no INTEGER NOT NULL,
            text TEXT NOT NULL,
            normalized_text TEXT NOT NULL,
            source TEXT NOT NULL CHECK(source IN ('visual_toc', 'ocr_block', 'pdf_font_band', 'markdown_heading', 'note_heading')),
            confidence REAL NOT NULL DEFAULT 0,
            heading_family_guess TEXT NOT NULL CHECK(heading_family_guess IN ('book', 'chapter', 'section', 'note', 'other', 'unknown')),
            rejected_chapter_candidate INTEGER NOT NULL DEFAULT 0,
            reject_reason TEXT,
            derived_from_heading_id TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, section_head_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_section_heads_doc_page
            ON fnm_section_heads(doc_id, page_no, chapter_id, rejected_chapter_candidate);

        CREATE TABLE IF NOT EXISTS fnm_note_items (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            note_item_id TEXT NOT NULL,
            note_kind TEXT NOT NULL,
            chapter_id TEXT,
            region_id TEXT,
            marker TEXT,
            normalized_marker TEXT,
            occurrence INTEGER NOT NULL DEFAULT 0,
            source_text TEXT,
            page_no INTEGER NOT NULL,
            display_marker TEXT,
            source_marker TEXT,
            title_hint TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, note_item_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_note_items_doc_kind
            ON fnm_note_items(doc_id, note_kind, chapter_id, region_id, page_no);

        CREATE TABLE IF NOT EXISTS fnm_body_anchors (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            anchor_id TEXT NOT NULL,
            chapter_id TEXT,
            page_no INTEGER NOT NULL,
            paragraph_index INTEGER NOT NULL DEFAULT 0,
            char_start INTEGER NOT NULL DEFAULT 0,
            char_end INTEGER NOT NULL DEFAULT 0,
            source_marker TEXT,
            normalized_marker TEXT,
            anchor_kind TEXT NOT NULL,
            certainty REAL NOT NULL DEFAULT 0,
            source_text TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, anchor_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_body_anchors_doc_page
            ON fnm_body_anchors(doc_id, chapter_id, page_no, normalized_marker);

        CREATE TABLE IF NOT EXISTS fnm_note_links (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            link_id TEXT NOT NULL,
            chapter_id TEXT,
            region_id TEXT,
            note_item_id TEXT,
            anchor_id TEXT,
            status TEXT NOT NULL,
            resolver TEXT,
            confidence REAL NOT NULL DEFAULT 0,
            note_kind TEXT,
            marker TEXT,
            page_no_start INTEGER,
            page_no_end INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, link_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_note_links_doc_status
            ON fnm_note_links(doc_id, status, chapter_id, region_id);

        CREATE TABLE IF NOT EXISTS fnm_structure_reviews (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            review_type TEXT NOT NULL,
            chapter_id TEXT,
            page_start INTEGER,
            page_end INTEGER,
            payload_json TEXT,
            severity TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_structure_reviews_doc_type
            ON fnm_structure_reviews(doc_id, review_type, severity);

        CREATE TABLE IF NOT EXISTS fnm_phase_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            phase INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'idle',
            gate_pass INTEGER NOT NULL DEFAULT 0,
            gate_report_json TEXT,
            errors_json TEXT,
            execution_mode TEXT NOT NULL DEFAULT 'test',
            forced_skip INTEGER NOT NULL DEFAULT 0,
            started_at INTEGER,
            ended_at INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, phase),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_phase_runs_doc
            ON fnm_phase_runs(doc_id, phase);

        CREATE TABLE IF NOT EXISTS fnm_dev_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            phase INTEGER NOT NULL,
            blob_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            note TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_dev_snapshots_doc_phase
            ON fnm_dev_snapshots(doc_id, phase, created_at);
        """
    )
    _ensure_columns(
        conn,
        "fnm_translation_units",
        (
            ("owner_kind", "owner_kind TEXT"),
            ("owner_id", "owner_id TEXT"),
            ("section_title", "section_title TEXT"),
            ("section_start_page", "section_start_page INTEGER"),
            ("section_end_page", "section_end_page INTEGER"),
            ("target_ref", "target_ref TEXT"),
            ("page_segments_json", "page_segments_json TEXT"),
        ),
    )
    _ensure_columns(
        conn,
        "fnm_runs",
        (
            ("validation_json", "validation_json TEXT"),
            ("structure_state", "structure_state TEXT"),
            ("review_counts_json", "review_counts_json TEXT"),
            ("blocking_reasons_json", "blocking_reasons_json TEXT"),
            ("link_summary_json", "link_summary_json TEXT"),
            ("page_partition_summary_json", "page_partition_summary_json TEXT"),
            ("chapter_mode_summary_json", "chapter_mode_summary_json TEXT"),
        ),
    )
    _ensure_columns(
        conn,
        "fnm_note_regions",
        (
            (
                "region_start_first_source_marker",
                "region_start_first_source_marker TEXT",
            ),
            ("region_first_note_item_marker", "region_first_note_item_marker TEXT"),
            (
                "region_marker_alignment_ok",
                "region_marker_alignment_ok INTEGER NOT NULL DEFAULT 0",
            ),
        ),
    )
    _ensure_columns(
        conn,
        "fnm_heading_candidates",
        (
            ("font_name", "font_name TEXT"),
            ("font_weight_hint", "font_weight_hint TEXT"),
            ("align_hint", "align_hint TEXT"),
            ("width_ratio", "width_ratio REAL"),
            ("heading_level_hint", "heading_level_hint INTEGER"),
        ),
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_fnm_units_doc_owner
            ON fnm_translation_units(doc_id, owner_kind, owner_id, section_start_page, page_start)
        """
    )
    _drop_retired_fnm_v2_tables(conn)
    conn.executescript(
        """
        DROP TABLE IF EXISTS fnm_page_revisions;
        DROP TABLE IF EXISTS fnm_page_entries;
        DROP TABLE IF EXISTS fnm_notes;

        CREATE TABLE IF NOT EXISTS fnm_chapter_endnotes (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            chapter_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            marker TEXT,
            numbering_scheme TEXT NOT NULL DEFAULT 'per_chapter',
            text TEXT,
            source_page_no INTEGER,
            is_reconstructed INTEGER NOT NULL DEFAULT 0,
            review_required INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, chapter_id, ordinal),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_chapter_endnotes_doc_chapter
            ON fnm_chapter_endnotes(doc_id, chapter_id, ordinal);

        CREATE TABLE IF NOT EXISTS fnm_paragraph_footnotes (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            chapter_id TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            paragraph_index INTEGER NOT NULL DEFAULT 0,
            attachment_kind TEXT NOT NULL DEFAULT 'page_tail',
            source_marker TEXT,
            text TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_fnm_paragraph_footnotes_doc_chapter
            ON fnm_paragraph_footnotes(doc_id, chapter_id, page_no);

        CREATE TABLE IF NOT EXISTS fnm_chapter_anchor_alignment (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            chapter_id TEXT NOT NULL,
            alignment_status TEXT NOT NULL DEFAULT 'misaligned',
            body_anchor_count INTEGER NOT NULL DEFAULT 0,
            endnote_count INTEGER NOT NULL DEFAULT 0,
            mismatch_json TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(doc_id, chapter_id),
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
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

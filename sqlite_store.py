"""SQLite 基础存储层：schema、WAL、Repository 边界。"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager

from config import ensure_dirs, get_sqlite_db_path


SCHEMA_VERSION = 5


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _create_schema(conn: sqlite3.Connection) -> None:
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
            toc_json TEXT
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
            model_source TEXT,
            model_key TEXT,
            model_id TEXT,
            provider TEXT,
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
        """
    )
    _ensure_column(
        conn,
        "documents",
        "toc_json",
        "toc_json TEXT",
    )
    _ensure_column(
        conn,
        "translation_pages",
        "model_source",
        "model_source TEXT",
    )
    _ensure_column(
        conn,
        "translation_pages",
        "model_id",
        "model_id TEXT",
    )
    _ensure_column(
        conn,
        "translation_pages",
        "provider",
        "provider TEXT",
    )
    _ensure_column(
        conn,
        "translate_runs",
        "model_source",
        "model_source TEXT",
    )
    _ensure_column(
        conn,
        "translate_runs",
        "model_id",
        "model_id TEXT",
    )
    _ensure_column(
        conn,
        "translate_runs",
        "provider",
        "provider TEXT",
    )
    _ensure_column(
        conn,
        "documents",
        "toc_source",
        "toc_source TEXT NOT NULL DEFAULT 'auto'",
    )
    _ensure_column(
        conn,
        "documents",
        "toc_page_offset",
        "toc_page_offset INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(
        conn,
        "documents",
        "toc_file_name",
        "toc_file_name TEXT",
    )
    _ensure_column(
        conn,
        "documents",
        "toc_file_uploaded_at",
        "toc_file_uploaded_at INTEGER",
    )
    _ensure_column(
        conn,
        "translation_segments",
        "manual_translation_text",
        "manual_translation_text TEXT",
    )
    _ensure_column(
        conn,
        "translation_segments",
        "translation_source",
        "translation_source TEXT NOT NULL DEFAULT 'model'",
    )
    _ensure_column(
        conn,
        "translation_segments",
        "manual_updated_at",
        "manual_updated_at INTEGER",
    )
    _ensure_column(
        conn,
        "translation_segments",
        "manual_updated_by",
        "manual_updated_by TEXT",
    )
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
    conn.execute(
        """
        INSERT INTO schema_meta(key, value)
        VALUES ('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (str(SCHEMA_VERSION),),
    )


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(db_path or get_sqlite_db_path())
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def initialize_database(db_path: str | None = None) -> str:
    with read_connection(db_path) as conn:
        _create_schema(conn)
        row = conn.execute("PRAGMA journal_mode").fetchone()
        return row[0] if row else ""


@contextmanager
def transaction(db_path: str | None = None):
    conn = get_connection(db_path)
    try:
        _create_schema(conn)
        yield conn
        conn.commit()
    except Exception:
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


class SQLiteRepository:
    """最小 SQLite 仓储边界，供后续主链路切换。"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or get_sqlite_db_path()
        initialize_database(self.db_path)

    def upsert_document(self, doc_id: str, name: str, **fields) -> None:
        now = int(fields.pop("updated_at", time.time()))
        created_at = int(fields.pop("created_at", now))
        payload = {
            "page_count": int(fields.pop("page_count", 0)),
            "entry_count": int(fields.pop("entry_count", 0)),
            "has_pdf": int(fields.pop("has_pdf", 0)),
            "last_entry_idx": int(fields.pop("last_entry_idx", 0)),
            "status": fields.pop("status", "ready"),
            "source_pdf_path": fields.pop("source_pdf_path", None),
            "toc_json": fields.pop("toc_json", None),
        }
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO documents(
                    id, name, created_at, updated_at, page_count, entry_count,
                    has_pdf, last_entry_idx, status, source_pdf_path, toc_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    updated_at=excluded.updated_at,
                    page_count=excluded.page_count,
                    entry_count=excluded.entry_count,
                    has_pdf=excluded.has_pdf,
                    last_entry_idx=excluded.last_entry_idx,
                    status=excluded.status,
                    source_pdf_path=COALESCE(excluded.source_pdf_path, documents.source_pdf_path),
                    toc_json=COALESCE(excluded.toc_json, documents.toc_json)
                """,
                (
                    doc_id,
                    name,
                    created_at,
                    now,
                    payload["page_count"],
                    payload["entry_count"],
                    payload["has_pdf"],
                    payload["last_entry_idx"],
                    payload["status"],
                    payload["source_pdf_path"],
                    payload["toc_json"],
                ),
            )

    def get_document(self, doc_id: str) -> dict | None:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
            if not row:
                return None
            payload = dict(row)
            payload["created"] = payload.get("created_at", 0)
            return payload

    def list_documents(self) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC, id DESC"
            ).fetchall()
            docs = []
            for row in rows:
                payload = dict(row)
                payload["created"] = payload.get("created_at", 0)
                docs.append(payload)
            return docs

    def set_document_toc(self, doc_id: str, toc_items: list[dict]) -> None:
        now = int(time.time())
        toc_json = json.dumps(toc_items or [], ensure_ascii=False)
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE documents
                SET toc_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (toc_json, now, doc_id),
            )

    def get_document_toc(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT toc_json FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
            if not row or not row["toc_json"]:
                return []
            try:
                items = json.loads(row["toc_json"])
            except Exception:
                return []
            return items if isinstance(items, list) else []

    def set_document_toc_source_offset(self, doc_id: str, source: str, offset: int) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                "UPDATE documents SET toc_source = ?, toc_page_offset = ?, updated_at = ? WHERE id = ?",
                (source, int(offset), now, doc_id),
            )

    def get_document_toc_source_offset(self, doc_id: str) -> tuple[str, int]:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT toc_source, toc_page_offset FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
            if not row:
                return ("auto", 0)
            return (row["toc_source"] or "auto", int(row["toc_page_offset"] or 0))

    def set_document_toc_file_meta(self, doc_id: str, file_name: str, uploaded_at: int | None = None) -> None:
        now = int(time.time())
        effective_uploaded_at = int(uploaded_at or now)
        normalized_name = os.path.basename(str(file_name or "").strip())
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE documents
                SET toc_file_name = ?, toc_file_uploaded_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized_name, effective_uploaded_at, now, doc_id),
            )

    def delete_document(self, doc_id: str) -> None:
        with transaction(self.db_path) as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    def replace_pages(self, doc_id: str, pages: list[dict]) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
            for page in pages:
                conn.execute(
                    """
                    INSERT INTO pages(
                        doc_id, book_page, file_idx, img_w, img_h, markdown,
                        footnotes, text_source, payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        int(page["bookPage"]),
                        int(page.get("fileIdx", 0) or 0),
                        page.get("imgW"),
                        page.get("imgH"),
                        page.get("markdown"),
                        page.get("footnotes"),
                        page.get("textSource", "ocr"),
                        json.dumps(page, ensure_ascii=False),
                        now,
                        now,
                    ),
                )

    def load_pages(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT book_page, file_idx, img_w, img_h, markdown, footnotes, text_source, payload_json
                FROM pages
                WHERE doc_id = ?
                ORDER BY book_page ASC
                """,
                (doc_id,),
            ).fetchall()
            pages = []
            for row in rows:
                payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
                if not isinstance(payload, dict):
                    payload = {}
                payload.update({
                    "bookPage": row["book_page"],
                    "fileIdx": row["file_idx"],
                    "imgW": row["img_w"],
                    "imgH": row["img_h"],
                    "markdown": row["markdown"],
                    "footnotes": row["footnotes"],
                    "textSource": row["text_source"],
                })
                pages.append(payload)
            return pages

    def _row_to_translate_run(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["running"] = bool(payload.get("running", 0))
        payload["stop_requested"] = bool(payload.get("stop_requested", 0))
        payload["failed_bps"] = json.loads(payload.pop("failed_bps_json") or "[]")
        payload["partial_failed_bps"] = json.loads(payload.pop("partial_failed_bps_json") or "[]")
        payload["failed_pages"] = json.loads(payload.pop("failed_pages_json") or "[]")
        payload["draft"] = json.loads(payload.pop("draft_json") or "{}")
        if payload.get("model_key") and not payload.get("model"):
            payload["model"] = payload["model_key"]
        payload["model_source"] = payload.get("model_source") or "builtin"
        payload["model_id"] = payload.get("model_id") or payload.get("model_key") or ""
        payload["provider"] = payload.get("provider") or ""
        payload["updated_at"] = float(payload.get("updated_at", 0) or 0)
        return payload

    def save_translate_run(self, doc_id: str, **fields) -> int:
        now = int(time.time())
        payload = {
            "phase": fields.get("phase", "idle"),
            "model_source": fields.get("model_source") or "builtin",
            "model_key": fields.get("model_key") or fields.get("model") or "",
            "model_id": fields.get("model_id") or fields.get("model") or fields.get("model_key") or "",
            "provider": fields.get("provider") or "",
            "start_bp": fields.get("start_bp"),
            "current_bp": fields.get("current_bp"),
            "resume_bp": fields.get("resume_bp"),
            "stop_requested": int(fields.get("stop_requested", 0) or 0),
            "running": int(fields.get("running", 0) or 0),
            "done_pages": int(fields.get("done_pages", 0) or 0),
            "total_pages": int(fields.get("total_pages", 0) or 0),
            "processed_pages": int(fields.get("processed_pages", 0) or 0),
            "pending_pages": int(fields.get("pending_pages", 0) or 0),
            "current_page_idx": int(fields.get("current_page_idx", 0) or 0),
            "translated_paras": int(fields.get("translated_paras", 0) or 0),
            "translated_chars": int(fields.get("translated_chars", 0) or 0),
            "prompt_tokens": int(fields.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(fields.get("completion_tokens", 0) or 0),
            "total_tokens": int(fields.get("total_tokens", 0) or 0),
            "request_count": int(fields.get("request_count", 0) or 0),
            "last_error": fields.get("last_error"),
            "failed_bps_json": json.dumps(fields.get("failed_bps") or [], ensure_ascii=False),
            "partial_failed_bps_json": json.dumps(fields.get("partial_failed_bps") or [], ensure_ascii=False),
            "failed_pages_json": json.dumps(fields.get("failed_pages") or [], ensure_ascii=False),
            "draft_json": json.dumps(fields.get("draft"), ensure_ascii=False) if fields.get("draft") is not None else None,
        }
        if not payload["provider"] and payload["model_key"].startswith("qwen-"):
            payload["provider"] = "qwen"
        elif not payload["provider"] and payload["model_key"].startswith("deepseek-"):
            payload["provider"] = "deepseek"
        with transaction(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, created_at FROM translate_runs
                WHERE doc_id = ?
                ORDER BY running DESC, updated_at DESC, id DESC
                LIMIT 1
                """,
                (doc_id,),
            ).fetchone()
            if row and (payload["running"] or row["id"]):
                cur = conn.execute(
                    """
                    UPDATE translate_runs
                    SET phase = ?, model_source = ?, model_key = ?, model_id = ?, provider = ?, start_bp = ?, current_bp = ?, resume_bp = ?,
                        stop_requested = ?, running = ?, done_pages = ?, total_pages = ?,
                        processed_pages = ?, pending_pages = ?, current_page_idx = ?,
                        translated_paras = ?, translated_chars = ?, prompt_tokens = ?,
                        completion_tokens = ?, total_tokens = ?, request_count = ?,
                        last_error = ?, failed_bps_json = ?, partial_failed_bps_json = ?,
                        failed_pages_json = ?, draft_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        payload["phase"],
                        payload["model_source"],
                        payload["model_key"],
                        payload["model_id"],
                        payload["provider"],
                        payload["start_bp"],
                        payload["current_bp"],
                        payload["resume_bp"],
                        payload["stop_requested"],
                        payload["running"],
                        payload["done_pages"],
                        payload["total_pages"],
                        payload["processed_pages"],
                        payload["pending_pages"],
                        payload["current_page_idx"],
                        payload["translated_paras"],
                        payload["translated_chars"],
                        payload["prompt_tokens"],
                        payload["completion_tokens"],
                        payload["total_tokens"],
                        payload["request_count"],
                        payload["last_error"],
                        payload["failed_bps_json"],
                        payload["partial_failed_bps_json"],
                        payload["failed_pages_json"],
                        payload["draft_json"],
                        now,
                        row["id"],
                    ),
                )
                self._replace_translate_failures_in_conn(
                    conn,
                    doc_id,
                    int(row["id"]),
                    fields.get("failed_pages") or [],
                )
                return int(row["id"])
            cur = conn.execute(
                """
                INSERT INTO translate_runs(
                    doc_id, phase, model_source, model_key, model_id, provider, start_bp, current_bp, resume_bp,
                    stop_requested, running, done_pages, total_pages, processed_pages,
                    pending_pages, current_page_idx, translated_paras, translated_chars,
                    prompt_tokens, completion_tokens, total_tokens, request_count,
                    last_error, failed_bps_json, partial_failed_bps_json, failed_pages_json,
                    draft_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    payload["phase"],
                    payload["model_source"],
                    payload["model_key"],
                    payload["model_id"],
                    payload["provider"],
                    payload["start_bp"],
                    payload["current_bp"],
                    payload["resume_bp"],
                    payload["stop_requested"],
                    payload["running"],
                    payload["done_pages"],
                    payload["total_pages"],
                    payload["processed_pages"],
                    payload["pending_pages"],
                    payload["current_page_idx"],
                    payload["translated_paras"],
                    payload["translated_chars"],
                    payload["prompt_tokens"],
                    payload["completion_tokens"],
                    payload["total_tokens"],
                    payload["request_count"],
                    payload["last_error"],
                    payload["failed_bps_json"],
                    payload["partial_failed_bps_json"],
                    payload["failed_pages_json"],
                    payload["draft_json"],
                    now,
                    now,
                ),
            )
            run_id = int(cur.lastrowid)
            self._replace_translate_failures_in_conn(
                conn,
                doc_id,
                run_id,
                fields.get("failed_pages") or [],
            )
            return run_id

    def _replace_translate_failures_in_conn(
        self,
        conn: sqlite3.Connection,
        doc_id: str,
        run_id: int | None,
        failures: list[dict],
    ) -> None:
        conn.execute("DELETE FROM translate_failures WHERE doc_id = ?", (doc_id,))
        now = int(time.time())
        for item in failures:
            if not isinstance(item, dict) or item.get("bp") is None:
                continue
            conn.execute(
                """
                INSERT INTO translate_failures(
                    doc_id, run_id, book_page, failure_type, error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    run_id,
                    int(item.get("bp")),
                    item.get("failure_type", "page_error"),
                    item.get("error", ""),
                    int(item.get("updated_at", now) or now),
                    now,
                ),
            )

    def save_translation_page(self, doc_id: str, book_page: int, entry: dict) -> int:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            active_run = self.get_active_translate_run(doc_id)
            usage_json = json.dumps(entry.get("_usage") or {}, ensure_ascii=False)
            model_key = entry.get("_model_key", "")
            provider = entry.get("_provider", "")
            if not provider and str(model_key).startswith("qwen-"):
                provider = "qwen"
            elif not provider and str(model_key).startswith("deepseek-"):
                provider = "deepseek"
            conn.execute(
                """
                INSERT INTO translation_pages(
                    doc_id, run_id, book_page, model_source, model_key, model_id, provider, status, pages_label, usage_json,
                    error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id, book_page) DO UPDATE SET
                    model_source=excluded.model_source,
                    run_id=excluded.run_id,
                    model_key=excluded.model_key,
                    model_id=excluded.model_id,
                    provider=excluded.provider,
                    status=excluded.status,
                    pages_label=excluded.pages_label,
                    usage_json=excluded.usage_json,
                    error_message=excluded.error_message,
                    updated_at=excluded.updated_at
                """,
                (
                    doc_id,
                    active_run["id"] if active_run else None,
                    int(book_page),
                    entry.get("_model_source", "builtin"),
                    model_key,
                    entry.get("_model_id") or entry.get("_model") or entry.get("_model_key", ""),
                    provider,
                    entry.get("_status", "done"),
                    entry.get("pages"),
                    usage_json,
                    entry.get("_error"),
                    now,
                    now,
                ),
            )
            page_row = conn.execute(
                "SELECT id FROM translation_pages WHERE doc_id = ? AND book_page = ?",
                (doc_id, int(book_page)),
            ).fetchone()
            translation_page_id = int(page_row["id"])
            conn.execute(
                """
                INSERT INTO segment_revisions(
                    translation_page_id, segment_index, revision_source,
                    original_text, translation_text, manual_translation_text,
                    run_id, updated_by, created_at)
                SELECT
                    translation_page_id, segment_index, translation_source,
                    original_text, translation_text, manual_translation_text,
                    ?, manual_updated_by, updated_at
                FROM translation_segments
                WHERE translation_page_id = ?
                """,
                (active_run["id"] if active_run else None, translation_page_id),
            )
            conn.execute(
                "DELETE FROM translation_segments WHERE translation_page_id = ?",
                (translation_page_id,),
            )
            for idx, segment in enumerate(entry.get("_page_entries") or []):
                conn.execute(
                    """
                    INSERT INTO translation_segments(
                        translation_page_id, segment_index, original_text,
                        translation_text, footnotes_text, footnotes_translation_text,
                        heading_level, segment_status, error_message, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        translation_page_id,
                        idx,
                        segment.get("original"),
                        segment.get("translation"),
                        segment.get("footnotes"),
                        segment.get("footnotes_translation"),
                        int(segment.get("heading_level", 0) or 0),
                        segment.get("_status", "done"),
                        segment.get("_error"),
                        now,
                        now,
                    ),
                )
            return translation_page_id

    def set_app_state(self, key: str, value: str) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_state(state_key, state_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value=excluded.state_value,
                    updated_at=excluded.updated_at
                """,
                (key, value, now),
            )

    def get_app_state(self, key: str) -> str | None:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT state_value FROM app_state WHERE state_key = ?",
                (key,),
            ).fetchone()
            return row["state_value"] if row else None

    def set_translation_title(self, doc_id: str, title: str) -> None:
        self.set_app_state(f"translation_title:{doc_id}", title)

    def get_translation_title(self, doc_id: str) -> str:
        return self.get_app_state(f"translation_title:{doc_id}") or ""

    def get_latest_translate_run(self, doc_id: str) -> dict | None:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM translate_runs
                WHERE doc_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (doc_id,),
            ).fetchone()
            return self._row_to_translate_run(row)

    def get_active_translate_run(self, doc_id: str) -> dict | None:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM translate_runs
                WHERE doc_id = ? AND running = 1
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (doc_id,),
            ).fetchone()
            return self._row_to_translate_run(row)

    def get_effective_translate_run(self, doc_id: str) -> dict | None:
        active = self.get_active_translate_run(doc_id)
        if active:
            return active
        return self.get_latest_translate_run(doc_id)

    def clear_translate_runs(self, doc_id: str) -> None:
        with transaction(self.db_path) as conn:
            conn.execute("DELETE FROM translate_failures WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM translate_runs WHERE doc_id = ?", (doc_id,))

    def list_translate_failures(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT book_page, error_message, created_at, updated_at, failure_type
                FROM translate_failures
                WHERE doc_id = ?
                ORDER BY book_page ASC, id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [
                {
                    "bp": row["book_page"],
                    "error": row["error_message"],
                    "failure_type": row["failure_type"],
                    "updated_at": float(row["updated_at"] or 0),
                }
                for row in rows
            ]

    def get_effective_translation_page(self, doc_id: str, book_page: int) -> dict | None:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM translation_pages
                WHERE doc_id = ? AND book_page = ?
                LIMIT 1
                """,
                (doc_id, int(book_page)),
            ).fetchone()
            if not row:
                return None
            payload = dict(row)
            payload["_model_source"] = payload.get("model_source") or "builtin"
            payload["_model_key"] = payload.get("model_key") or ""
            payload["_model_id"] = payload.get("model_id") or payload.get("model_key") or ""
            payload["_provider"] = payload.get("provider") or ""
            payload["_model"] = payload["_model_id"]
            payload["_status"] = payload.get("status", "done")
            payload["_usage"] = json.loads(payload.get("usage_json") or "{}")
            payload["_error"] = payload.get("error_message")
            payload["_page_entries"] = self.list_translation_segments(int(row["id"]))
            return payload

    def list_effective_translation_pages(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM translation_pages
                WHERE doc_id = ?
                ORDER BY book_page ASC
                """,
                (doc_id,),
            ).fetchall()
            pages = []
            for row in rows:
                payload = dict(row)
                payload["_pageBP"] = payload.get("book_page")
                payload["_model_source"] = payload.get("model_source") or "builtin"
                payload["_model_key"] = payload.get("model_key") or ""
                payload["_model_id"] = payload.get("model_id") or payload.get("model_key") or ""
                payload["_provider"] = payload.get("provider") or ""
                payload["_model"] = payload["_model_id"]
                payload["_status"] = payload.get("status", "done")
                payload["_usage"] = json.loads(payload.get("usage_json") or "{}")
                payload["_error"] = payload.get("error_message")
                payload["pages"] = payload.get("pages_label")
                payload["_page_entries"] = self.list_translation_segments(int(row["id"]))
                pages.append(payload)
            return pages

    def clear_translation_pages(self, doc_id: str) -> None:
        with transaction(self.db_path) as conn:
            conn.execute("DELETE FROM translation_pages WHERE doc_id = ?", (doc_id,))

    def get_translation_segment(self, doc_id: str, book_page: int, segment_index: int) -> dict | None:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT s.*
                FROM translation_segments s
                JOIN translation_pages p ON p.id = s.translation_page_id
                WHERE p.doc_id = ? AND p.book_page = ? AND s.segment_index = ?
                LIMIT 1
                """,
                (doc_id, int(book_page), int(segment_index)),
            ).fetchone()
            if not row:
                return None
            return self._row_to_translation_segment_payload(row)

    def save_manual_translation_segment(
        self,
        doc_id: str,
        book_page: int,
        segment_index: int,
        translation: str,
        updated_by: str = "local_user",
        base_updated_at: int | None = None,
    ) -> dict:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT s.*
                FROM translation_segments s
                JOIN translation_pages p ON p.id = s.translation_page_id
                WHERE p.doc_id = ? AND p.book_page = ? AND s.segment_index = ?
                LIMIT 1
                """,
                (doc_id, int(book_page), int(segment_index)),
            ).fetchone()
            if not row:
                raise ValueError("目标段落不存在")
            current_updated_at = int(row["updated_at"] or 0)
            if base_updated_at is not None and current_updated_at > int(base_updated_at):
                raise RuntimeError("段落已被更新，请刷新后再保存（冲突）")

            conn.execute(
                """
                INSERT INTO segment_revisions(
                    translation_page_id, segment_index, revision_source,
                    original_text, translation_text, manual_translation_text,
                    run_id, updated_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(row["translation_page_id"]),
                    int(row["segment_index"]),
                    row["translation_source"] or "model",
                    row["original_text"],
                    row["translation_text"],
                    row["manual_translation_text"],
                    None,
                    row["manual_updated_by"],
                    current_updated_at,
                ),
            )

            conn.execute(
                """
                UPDATE translation_segments
                SET manual_translation_text = ?,
                    translation_source = 'manual',
                    manual_updated_at = ?,
                    manual_updated_by = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(translation or ""),
                    now,
                    updated_by,
                    now,
                    int(row["id"]),
                ),
            )
            conn.execute(
                """
                UPDATE translation_pages
                SET updated_at = ?
                WHERE doc_id = ? AND book_page = ?
                """,
                (now, doc_id, int(book_page)),
            )
            updated = conn.execute(
                "SELECT * FROM translation_segments WHERE id = ?",
                (int(row["id"]),),
            ).fetchone()
            return self._row_to_translation_segment_payload(updated)

    def _row_to_translation_segment_payload(self, row: sqlite3.Row) -> dict:
        payload = dict(row)
        manual_translation = payload.get("manual_translation_text")
        machine_translation = payload.get("translation_text")
        source = payload.get("translation_source") or ("manual" if manual_translation else "model")
        payload["original"] = payload.get("original_text")
        payload["translation"] = manual_translation if manual_translation not in (None, "") else machine_translation
        payload["_machine_translation"] = machine_translation
        payload["_manual_translation"] = manual_translation
        payload["_translation_source"] = source
        payload["_manual_updated_at"] = payload.get("manual_updated_at")
        payload["_manual_updated_by"] = payload.get("manual_updated_by")
        payload["footnotes"] = payload.get("footnotes_text")
        payload["footnotes_translation"] = payload.get("footnotes_translation_text")
        payload["_status"] = payload.get("segment_status", "done")
        payload["_error"] = payload.get("error_message")
        return payload

    def list_translation_segments(self, translation_page_id: int) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM translation_segments
                WHERE translation_page_id = ?
                ORDER BY segment_index ASC
                """,
                (translation_page_id,),
            ).fetchall()
            segments = []
            for row in rows:
                segments.append(self._row_to_translation_segment_payload(row))
            return segments

    def list_segment_revisions(
        self, doc_id: str, book_page: int, segment_index: int, limit: int = 20
    ) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT r.*
                FROM segment_revisions r
                JOIN translation_pages p ON p.id = r.translation_page_id
                WHERE p.doc_id = ? AND p.book_page = ? AND r.segment_index = ?
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (doc_id, int(book_page), int(segment_index), int(limit)),
            ).fetchall()
            return [dict(row) for row in rows]

    def count_manual_segments(self, doc_id: str, book_page: int) -> int:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM translation_segments s
                JOIN translation_pages p ON p.id = s.translation_page_id
                WHERE p.doc_id = ? AND p.book_page = ? AND s.translation_source = 'manual'
                """,
                (doc_id, int(book_page)),
            ).fetchone()
            return int(row["cnt"]) if row else 0

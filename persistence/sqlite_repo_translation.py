"""SQLite 翻译数据仓储 mixin。"""

from __future__ import annotations

import json
import sqlite3
import time

from persistence.sqlite_schema import read_connection, transaction


class TranslationRepoMixin:
    def _row_to_translate_run(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["running"] = bool(payload.get("running", 0))
        payload["stop_requested"] = bool(payload.get("stop_requested", 0))
        payload["execution_mode"] = payload.get("execution_mode") or "test"
        payload["failed_bps"] = json.loads(payload.pop("failed_bps_json") or "[]")
        payload["partial_failed_bps"] = json.loads(payload.pop("partial_failed_bps_json") or "[]")
        payload["failed_pages"] = json.loads(payload.pop("failed_pages_json") or "[]")
        payload["retry_round"] = int(payload.get("retry_round", 0) or 0)
        payload["unresolved_count"] = int(payload.get("unresolved_count", 0) or 0)
        payload["manual_required_count"] = int(payload.get("manual_required_count", 0) or 0)
        payload["next_failed_location"] = json.loads(payload.pop("next_failed_location_json") or "null")
        payload["failed_locations"] = json.loads(payload.pop("failed_locations_json") or "[]")
        payload["manual_required_locations"] = json.loads(payload.pop("manual_required_locations_json") or "[]")
        payload["task"] = json.loads(payload.pop("task_json") or "{}")
        payload["draft"] = json.loads(payload.pop("draft_json") or "{}")
        if payload.get("model_key") and not payload.get("model"):
            payload["model"] = payload["model_key"]
        payload["model_source"] = payload.get("model_source") or "builtin"
        payload["model_id"] = payload.get("model_id") or payload.get("model_key") or ""
        payload["provider"] = payload.get("provider") or ""
        payload["translation_model_label"] = payload.get("translation_model_label") or payload.get("model") or ""
        payload["translation_model_id"] = payload.get("translation_model_id") or payload.get("model_id") or ""
        payload["companion_model_label"] = payload.get("companion_model_label") or ""
        payload["companion_model_id"] = payload.get("companion_model_id") or ""
        payload["updated_at"] = float(payload.get("updated_at", 0) or 0)
        return payload

    def save_translate_run(self, doc_id: str, **fields) -> int:
        now = int(time.time())
        payload = {
            "phase": fields.get("phase", "idle"),
            "execution_mode": fields.get("execution_mode") or "test",
            "model_source": fields.get("model_source") or "builtin",
            "model_key": fields.get("model_key") or fields.get("model") or "",
            "model_id": fields.get("model_id") or fields.get("model") or fields.get("model_key") or "",
            "provider": fields.get("provider") or "",
            "translation_model_label": fields.get("translation_model_label") or fields.get("model") or fields.get("model_id") or fields.get("model_key") or "",
            "translation_model_id": fields.get("translation_model_id") or fields.get("model_id") or fields.get("model_key") or fields.get("model") or "",
            "companion_model_label": fields.get("companion_model_label") or "",
            "companion_model_id": fields.get("companion_model_id") or "",
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
            "retry_round": int(fields.get("retry_round", 0) or 0),
            "unresolved_count": int(fields.get("unresolved_count", 0) or 0),
            "manual_required_count": int(fields.get("manual_required_count", 0) or 0),
            "next_failed_location_json": json.dumps(fields.get("next_failed_location"), ensure_ascii=False) if fields.get("next_failed_location") is not None else None,
            "failed_locations_json": json.dumps(fields.get("failed_locations") or [], ensure_ascii=False),
            "manual_required_locations_json": json.dumps(fields.get("manual_required_locations") or [], ensure_ascii=False),
            "task_json": json.dumps(fields.get("task") or {}, ensure_ascii=False),
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
                conn.execute(
                    """
                    UPDATE translate_runs
                    SET phase = ?, execution_mode = ?, model_source = ?, model_key = ?, model_id = ?, provider = ?,
                        translation_model_label = ?, translation_model_id = ?, companion_model_label = ?, companion_model_id = ?,
                        start_bp = ?, current_bp = ?, resume_bp = ?,
                        stop_requested = ?, running = ?, done_pages = ?, total_pages = ?,
                        processed_pages = ?, pending_pages = ?, current_page_idx = ?,
                        translated_paras = ?, translated_chars = ?, prompt_tokens = ?,
                        completion_tokens = ?, total_tokens = ?, request_count = ?,
                        last_error = ?, failed_bps_json = ?, partial_failed_bps_json = ?,
                        failed_pages_json = ?, retry_round = ?, unresolved_count = ?, manual_required_count = ?,
                        next_failed_location_json = ?, failed_locations_json = ?, manual_required_locations_json = ?,
                        task_json = ?, draft_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        payload["phase"],
                        payload["execution_mode"],
                        payload["model_source"],
                        payload["model_key"],
                        payload["model_id"],
                        payload["provider"],
                        payload["translation_model_label"],
                        payload["translation_model_id"],
                        payload["companion_model_label"],
                        payload["companion_model_id"],
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
                        payload["retry_round"],
                        payload["unresolved_count"],
                        payload["manual_required_count"],
                        payload["next_failed_location_json"],
                        payload["failed_locations_json"],
                        payload["manual_required_locations_json"],
                        payload["task_json"],
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
                    doc_id, phase, execution_mode, model_source, model_key, model_id, provider,
                    translation_model_label, translation_model_id, companion_model_label, companion_model_id,
                    start_bp, current_bp, resume_bp,
                    stop_requested, running, done_pages, total_pages, processed_pages,
                    pending_pages, current_page_idx, translated_paras, translated_chars,
                    prompt_tokens, completion_tokens, total_tokens, request_count,
                    last_error, failed_bps_json, partial_failed_bps_json, failed_pages_json,
                    retry_round, unresolved_count, manual_required_count,
                    next_failed_location_json, failed_locations_json, manual_required_locations_json,
                    task_json, draft_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    payload["phase"],
                    payload["execution_mode"],
                    payload["model_source"],
                    payload["model_key"],
                    payload["model_id"],
                    payload["provider"],
                    payload["translation_model_label"],
                    payload["translation_model_id"],
                    payload["companion_model_label"],
                    payload["companion_model_id"],
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
                    payload["retry_round"],
                    payload["unresolved_count"],
                    payload["manual_required_count"],
                    payload["next_failed_location_json"],
                    payload["failed_locations_json"],
                    payload["manual_required_locations_json"],
                    payload["task_json"],
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
                    manual_original_text,
                    run_id, updated_by, created_at)
                SELECT
                    translation_page_id, segment_index, translation_source,
                    original_text, translation_text, manual_translation_text,
                    manual_original_text,
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
                source = str(segment.get("_translation_source") or "").strip() or "model"
                manual_translation = segment.get("_manual_translation")
                machine_translation = segment.get("_machine_translation")
                display_translation = segment.get("translation")
                if source == "manual":
                    if manual_translation in (None, ""):
                        manual_translation = display_translation
                    if machine_translation in (None, ""):
                        machine_translation = None
                else:
                    if machine_translation in (None, ""):
                        machine_translation = display_translation
                    if manual_translation in (None, ""):
                        manual_translation = None
                conn.execute(
                    """
                    INSERT INTO translation_segments(
                        translation_page_id, segment_index, original_text,
                        translation_text, manual_translation_text, translation_source,
                        manual_updated_at, manual_updated_by,
                        footnotes_text, footnotes_translation_text,
                        pages_label, start_book_page, end_book_page, print_page_label,
                        note_kind, note_marker, note_number, note_section_title, note_confidence,
                        heading_level, segment_status, error_message,
                        manual_original_text,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        translation_page_id,
                        idx,
                        segment.get("original"),
                        machine_translation,
                        manual_translation,
                        source,
                        int(segment.get("_manual_updated_at")) if segment.get("_manual_updated_at") is not None else None,
                        segment.get("_manual_updated_by"),
                        segment.get("footnotes"),
                        segment.get("footnotes_translation"),
                        segment.get("pages"),
                        int(segment.get("_startBP")) if segment.get("_startBP") is not None else None,
                        int(segment.get("_endBP")) if segment.get("_endBP") is not None else None,
                        segment.get("_printPageLabel"),
                        segment.get("_note_kind"),
                        segment.get("_note_marker"),
                        int(segment.get("_note_number")) if segment.get("_note_number") is not None else None,
                        segment.get("_note_section_title"),
                        float(segment.get("_note_confidence", 0.0) or 0.0),
                        int(segment.get("heading_level", 0) or 0),
                        segment.get("_status", "done"),
                        segment.get("_error"),
                        segment.get("_manual_original") or segment.get("manual_original_text"),
                        now,
                        now,
                    ),
                )
            return translation_page_id

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
                    manual_original_text,
                    run_id, updated_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(row["translation_page_id"]),
                    int(row["segment_index"]),
                    row["translation_source"] or "model",
                    row["original_text"],
                    row["translation_text"],
                    row["manual_translation_text"],
                    dict(row).get("manual_original_text"),
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

    def save_manual_original_segment(
        self,
        doc_id: str,
        book_page: int,
        segment_index: int,
        original: str,
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
                    manual_original_text,
                    run_id, updated_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(row["translation_page_id"]),
                    int(row["segment_index"]),
                    row["translation_source"] or "model",
                    row["original_text"],
                    row["translation_text"],
                    row["manual_translation_text"],
                    dict(row).get("manual_original_text"),
                    None,
                    row["manual_updated_by"],
                    current_updated_at,
                ),
            )

            conn.execute(
                """
                UPDATE translation_segments
                SET manual_original_text = ?,
                    manual_updated_at = ?,
                    manual_updated_by = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(original or ""),
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
        manual_original = payload.get("manual_original_text")
        base_original = payload.get("original_text")
        payload["original"] = (
            manual_original if manual_original not in (None, "") else base_original
        )
        payload["_original_source"] = "manual" if manual_original not in (None, "") else "ocr"
        payload["translation"] = manual_translation if manual_translation not in (None, "") else machine_translation
        payload["_machine_translation"] = machine_translation
        payload["_manual_translation"] = manual_translation
        payload["_translation_source"] = source
        payload["_manual_updated_at"] = payload.get("manual_updated_at")
        payload["_manual_updated_by"] = payload.get("manual_updated_by")
        payload["footnotes"] = payload.get("footnotes_text")
        payload["footnotes_translation"] = payload.get("footnotes_translation_text")
        payload["pages"] = payload.get("pages_label")
        payload["_startBP"] = payload.get("start_book_page")
        payload["_endBP"] = payload.get("end_book_page")
        payload["_printPageLabel"] = payload.get("print_page_label")
        payload["_note_kind"] = payload.get("note_kind")
        payload["_note_marker"] = payload.get("note_marker")
        payload["_note_number"] = payload.get("note_number")
        payload["_note_section_title"] = payload.get("note_section_title")
        payload["_note_confidence"] = float(payload.get("note_confidence", 0.0) or 0.0)
        payload["_status"] = payload.get("segment_status", "done")
        payload["_error"] = payload.get("error_message")
        return payload

    def remap_book_pages(self, doc_id: str, bp_map: dict[int, int]) -> None:
        normalized = {
            int(old_bp): int(new_bp)
            for old_bp, new_bp in (bp_map or {}).items()
            if old_bp is not None and new_bp is not None and int(old_bp) != int(new_bp)
        }
        if not normalized:
            return

        def _remap_bp(value):
            if value is None:
                return None
            try:
                return normalized.get(int(value), int(value))
            except (TypeError, ValueError):
                return value

        def _remap_bp_list(raw_json: str | None) -> str:
            try:
                items = json.loads(raw_json or "[]")
            except Exception:
                items = []
            if not isinstance(items, list):
                items = []
            return json.dumps([_remap_bp(item) for item in items], ensure_ascii=False)

        def _remap_failed_pages(raw_json: str | None) -> str:
            try:
                items = json.loads(raw_json or "[]")
            except Exception:
                items = []
            normalized_items = []
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    updated = dict(item)
                    if updated.get("bp") is not None:
                        updated["bp"] = _remap_bp(updated.get("bp"))
                    normalized_items.append(updated)
                else:
                    normalized_items.append(item)
            return json.dumps(normalized_items, ensure_ascii=False)

        def _remap_draft(raw_json: str | None) -> str:
            try:
                draft = json.loads(raw_json or "{}")
            except Exception:
                draft = {}
            if not isinstance(draft, dict):
                draft = {}
            if draft.get("bp") is not None:
                draft["bp"] = _remap_bp(draft.get("bp"))
            return json.dumps(draft, ensure_ascii=False)

        with transaction(self.db_path) as conn:
            page_rows = conn.execute(
                "SELECT id, book_page FROM translation_pages WHERE doc_id = ?",
                (doc_id,),
            ).fetchall()
            for row in page_rows:
                old_bp = int(row["book_page"])
                new_bp = normalized.get(old_bp)
                if new_bp is None:
                    continue
                conn.execute(
                    "UPDATE translation_pages SET book_page = ? WHERE id = ?",
                    (-new_bp, int(row["id"])),
                )
            conn.execute(
                "UPDATE translation_pages SET book_page = ABS(book_page) WHERE doc_id = ? AND book_page < 0",
                (doc_id,),
            )

            for column in ("start_bp", "current_bp", "resume_bp"):
                for old_bp, new_bp in normalized.items():
                    conn.execute(
                        f"UPDATE translate_runs SET {column} = ? WHERE doc_id = ? AND {column} = ?",
                        (-new_bp, doc_id, old_bp),
                    )
                conn.execute(
                    f"UPDATE translate_runs SET {column} = ABS({column}) WHERE doc_id = ? AND {column} < 0",
                    (doc_id,),
                )

            failure_rows = conn.execute(
                "SELECT id, book_page FROM translate_failures WHERE doc_id = ?",
                (doc_id,),
            ).fetchall()
            for row in failure_rows:
                old_bp = int(row["book_page"])
                new_bp = normalized.get(old_bp)
                if new_bp is None:
                    continue
                conn.execute(
                    "UPDATE translate_failures SET book_page = ? WHERE id = ?",
                    (-new_bp, int(row["id"])),
                )
            conn.execute(
                "UPDATE translate_failures SET book_page = ABS(book_page) WHERE doc_id = ? AND book_page < 0",
                (doc_id,),
            )

            run_rows = conn.execute(
                """
                SELECT id, failed_bps_json, partial_failed_bps_json, failed_pages_json, draft_json
                FROM translate_runs
                WHERE doc_id = ?
                """,
                (doc_id,),
            ).fetchall()
            for row in run_rows:
                conn.execute(
                    """
                    UPDATE translate_runs
                    SET failed_bps_json = ?, partial_failed_bps_json = ?, failed_pages_json = ?, draft_json = ?
                    WHERE id = ?
                    """,
                    (
                        _remap_bp_list(row["failed_bps_json"]),
                        _remap_bp_list(row["partial_failed_bps_json"]),
                        _remap_failed_pages(row["failed_pages_json"]),
                        _remap_draft(row["draft_json"]),
                        int(row["id"]),
                    ),
                )

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

    def save_translation_page_revision(
        self,
        doc_id: str,
        book_page: int,
        entry: dict,
        *,
        revision_source: str = "page_editor",
        updated_by: str = "local_user",
    ) -> int:
        target_page = self.get_effective_translation_page(doc_id, book_page)
        if not target_page:
            return 0
        translation_page_id = int(target_page["id"])
        now = int(time.time())
        with transaction(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO translation_page_revisions(
                    translation_page_id, revision_source, entry_json, updated_by, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    translation_page_id,
                    str(revision_source or "page_editor"),
                    json.dumps(entry or {}, ensure_ascii=False),
                    str(updated_by or "local_user"),
                    now,
                ),
            )
            return int(cur.lastrowid or 0)

    def list_translation_page_revisions(
        self,
        doc_id: str,
        book_page: int,
        limit: int = 20,
    ) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT r.*, p.book_page
                FROM translation_page_revisions r
                JOIN translation_pages p ON p.id = r.translation_page_id
                WHERE p.doc_id = ? AND p.book_page = ?
                ORDER BY r.created_at DESC, r.id DESC
                LIMIT ?
                """,
                (doc_id, int(book_page), int(limit)),
            ).fetchall()
            return [
                payload
                for payload in (
                    self._row_to_translation_page_revision_payload(row)
                    for row in rows
                )
                if payload
            ]

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

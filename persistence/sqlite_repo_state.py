"""SQLite 应用状态与通用 revision helper mixin。"""

from __future__ import annotations

import json
import sqlite3
import time

from persistence.sqlite_schema import read_connection, transaction


class StateRepoMixin:
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

    def set_glossary_state(self, doc_id: str, glossary_json: str) -> None:
        self.set_app_state(f"glossary:{doc_id}", glossary_json)

    def get_glossary_state(self, doc_id: str) -> str | None:
        return self.get_app_state(f"glossary:{doc_id}")

    _DOC_SCOPED_KEY_PREFIXES = ("glossary:", "translation_title:")

    def delete_doc_scoped_state(self, doc_id: str) -> None:
        if not doc_id:
            return
        with transaction(self.db_path) as conn:
            for prefix in self._DOC_SCOPED_KEY_PREFIXES:
                conn.execute(
                    "DELETE FROM app_state WHERE state_key = ?",
                    (f"{prefix}{doc_id}",),
                )

    @staticmethod
    def _row_to_revision_payload(row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        try:
            payload["entry"] = json.loads(payload.get("entry_json") or "{}")
        except Exception:
            payload["entry"] = {}
        return payload

    _row_to_translation_page_revision_payload = _row_to_revision_payload
    _row_to_fnm_page_revision_payload = _row_to_revision_payload

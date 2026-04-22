"""SQLite FNM 开发者模式仓储 mixin。

管理 `fnm_phase_runs`（每本书每阶段一行）与 `fnm_dev_snapshots`（快照）。
"""
from __future__ import annotations

import json
import sqlite3
import time

from persistence.sqlite_schema import read_connection, transaction


PHASES = (1, 2, 3, 4, 5, 6)

PHASE_STATUS_IDLE = "idle"
PHASE_STATUS_RUNNING = "running"
PHASE_STATUS_READY = "ready"
PHASE_STATUS_FAILED = "failed"
PHASE_STATUS_SKIPPED_FORCED = "skipped_forced"
PHASE_STATUS_UNSUPPORTED = "unsupported"

VALID_PHASE_STATUS = {
    PHASE_STATUS_IDLE,
    PHASE_STATUS_RUNNING,
    PHASE_STATUS_READY,
    PHASE_STATUS_FAILED,
    PHASE_STATUS_SKIPPED_FORCED,
    PHASE_STATUS_UNSUPPORTED,
}


def _validate_phase(phase: int) -> int:
    phase_int = int(phase)
    if phase_int not in PHASES:
        raise ValueError(f"invalid phase: {phase}")
    return phase_int


def _dump_json(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _load_json(raw, default):
    if raw is None or raw == "":
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


class DevRepoMixin:
    """开发者模式 DAO。方法签名以 `doc_id` 开头，依赖 SQLiteRepository 的 per-doc 路由。"""

    # ------------------- phase runs -------------------

    def _row_to_phase_run(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["gate_pass"] = bool(payload.get("gate_pass") or 0)
        payload["forced_skip"] = bool(payload.get("forced_skip") or 0)
        payload["gate_report"] = _load_json(payload.pop("gate_report_json", None), default={})
        payload["errors"] = _load_json(payload.pop("errors_json", None), default=[])
        for key in ("started_at", "ended_at", "created_at", "updated_at"):
            raw = payload.get(key)
            payload[key] = int(raw) if raw is not None else None
        return payload

    def upsert_phase_run(
        self,
        doc_id: str,
        phase: int,
        *,
        status: str | None = None,
        gate_pass: bool | None = None,
        gate_report=None,
        errors=None,
        execution_mode: str | None = None,
        forced_skip: bool | None = None,
        started_at: int | None = None,
        ended_at: int | None = None,
    ) -> dict:
        """插入或更新某阶段的 run 记录。

        未传的字段保留原值；首次写入时未传的字段取默认值。
        返回落盘后的行。
        """
        if not doc_id:
            raise ValueError("doc_id is required")
        phase_int = _validate_phase(phase)
        if status is not None and status not in VALID_PHASE_STATUS:
            raise ValueError(f"invalid phase status: {status}")

        now = int(time.time())
        with transaction(self.db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM fnm_phase_runs WHERE doc_id = ? AND phase = ?",
                (doc_id, phase_int),
            ).fetchone()

            if existing:
                payload = dict(existing)
                if status is not None:
                    payload["status"] = status
                if gate_pass is not None:
                    payload["gate_pass"] = 1 if gate_pass else 0
                if gate_report is not None:
                    payload["gate_report_json"] = _dump_json(gate_report)
                if errors is not None:
                    payload["errors_json"] = _dump_json(errors)
                if execution_mode is not None:
                    payload["execution_mode"] = execution_mode
                if forced_skip is not None:
                    payload["forced_skip"] = 1 if forced_skip else 0
                if started_at is not None:
                    payload["started_at"] = int(started_at)
                if ended_at is not None:
                    payload["ended_at"] = int(ended_at)
                payload["updated_at"] = now
                conn.execute(
                    """
                    UPDATE fnm_phase_runs
                    SET status = ?, gate_pass = ?, gate_report_json = ?, errors_json = ?,
                        execution_mode = ?, forced_skip = ?, started_at = ?, ended_at = ?,
                        updated_at = ?
                    WHERE doc_id = ? AND phase = ?
                    """,
                    (
                        payload.get("status", PHASE_STATUS_IDLE),
                        int(payload.get("gate_pass") or 0),
                        payload.get("gate_report_json"),
                        payload.get("errors_json"),
                        payload.get("execution_mode", "test"),
                        int(payload.get("forced_skip") or 0),
                        payload.get("started_at"),
                        payload.get("ended_at"),
                        now,
                        doc_id,
                        phase_int,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO fnm_phase_runs(
                        doc_id, phase, status, gate_pass, gate_report_json, errors_json,
                        execution_mode, forced_skip, started_at, ended_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        phase_int,
                        status or PHASE_STATUS_IDLE,
                        1 if gate_pass else 0,
                        _dump_json(gate_report),
                        _dump_json(errors),
                        execution_mode or "test",
                        1 if forced_skip else 0,
                        int(started_at) if started_at is not None else None,
                        int(ended_at) if ended_at is not None else None,
                        now,
                        now,
                    ),
                )
            row = conn.execute(
                "SELECT * FROM fnm_phase_runs WHERE doc_id = ? AND phase = ?",
                (doc_id, phase_int),
            ).fetchone()
            return self._row_to_phase_run(row)

    def get_phase_run(self, doc_id: str, phase: int) -> dict | None:
        if not doc_id:
            return None
        phase_int = _validate_phase(phase)
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM fnm_phase_runs WHERE doc_id = ? AND phase = ?",
                (doc_id, phase_int),
            ).fetchone()
            return self._row_to_phase_run(row)

    def list_phase_runs(self, doc_id: str) -> list[dict]:
        """返回该 doc 的所有阶段记录（按 phase 升序）。

        缺失的阶段会补齐一个 status=idle 的占位 dict（不落库）。
        """
        if not doc_id:
            return []
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fnm_phase_runs WHERE doc_id = ? ORDER BY phase ASC",
                (doc_id,),
            ).fetchall()
        existing = {int(r["phase"]): self._row_to_phase_run(r) for r in rows}
        result: list[dict] = []
        for phase in PHASES:
            if phase in existing:
                result.append(existing[phase])
            else:
                result.append(
                    {
                        "doc_id": doc_id,
                        "phase": phase,
                        "status": PHASE_STATUS_IDLE,
                        "gate_pass": False,
                        "gate_report": {},
                        "errors": [],
                        "execution_mode": "test",
                        "forced_skip": False,
                        "started_at": None,
                        "ended_at": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                )
        return result

    def delete_phase_runs_from(self, doc_id: str, phase_from: int) -> int:
        """级联清除 phase >= phase_from 的记录。返回被删除的行数。"""
        if not doc_id:
            return 0
        phase_int = _validate_phase(phase_from)
        with transaction(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM fnm_phase_runs WHERE doc_id = ? AND phase >= ?",
                (doc_id, phase_int),
            )
            return int(cur.rowcount or 0)

    def init_phase_runs(self, doc_id: str) -> list[dict]:
        """幂等地为 doc 初始化 6 条 idle 记录；已有记录不覆盖。"""
        if not doc_id:
            raise ValueError("doc_id is required")
        now = int(time.time())
        with transaction(self.db_path) as conn:
            existing_phases = {
                int(r["phase"])
                for r in conn.execute(
                    "SELECT phase FROM fnm_phase_runs WHERE doc_id = ?",
                    (doc_id,),
                ).fetchall()
            }
            for phase in PHASES:
                if phase in existing_phases:
                    continue
                conn.execute(
                    """
                    INSERT INTO fnm_phase_runs(
                        doc_id, phase, status, gate_pass, execution_mode,
                        forced_skip, created_at, updated_at
                    ) VALUES (?, ?, 'idle', 0, 'test', 0, ?, ?)
                    """,
                    (doc_id, phase, now, now),
                )
        return self.list_phase_runs(doc_id)

    # ------------------- snapshots -------------------

    def save_dev_snapshot(
        self,
        doc_id: str,
        phase: int,
        blob_path: str,
        *,
        size_bytes: int = 0,
        note: str | None = None,
    ) -> int:
        if not doc_id:
            raise ValueError("doc_id is required")
        phase_int = _validate_phase(phase)
        now = int(time.time())
        with transaction(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO fnm_dev_snapshots(
                    doc_id, phase, blob_path, size_bytes, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (doc_id, phase_int, str(blob_path), int(size_bytes or 0), note, now),
            )
            return int(cur.lastrowid)

    def list_dev_snapshots(self, doc_id: str, phase: int | None = None) -> list[dict]:
        if not doc_id:
            return []
        with read_connection(self.db_path) as conn:
            if phase is None:
                rows = conn.execute(
                    "SELECT * FROM fnm_dev_snapshots WHERE doc_id = ? ORDER BY created_at DESC, id DESC",
                    (doc_id,),
                ).fetchall()
            else:
                phase_int = _validate_phase(phase)
                rows = conn.execute(
                    "SELECT * FROM fnm_dev_snapshots WHERE doc_id = ? AND phase = ? ORDER BY created_at DESC, id DESC",
                    (doc_id, phase_int),
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_dev_snapshots_from(self, doc_id: str, phase_from: int) -> int:
        if not doc_id:
            return 0
        phase_int = _validate_phase(phase_from)
        with transaction(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM fnm_dev_snapshots WHERE doc_id = ? AND phase >= ?",
                (doc_id, phase_int),
            )
            return int(cur.rowcount or 0)

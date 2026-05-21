"""FNM 开发模式：级联重置。

`reset_from_phase(doc_id, phase_from, repo, ...)`

作用：把 phase>=phase_from 的所有状态回退到 idle。
具体清理：
  1. fnm_* 产物表中 phase>=phase_from 的行（借用 repo 的 `_delete_fnm_products_from_phase`）
  2. fnm_phase_runs 中 phase>=phase_from 的行
  3. fnm_dev_snapshots 中 phase>=phase_from 的行
  4. （可选）dev_exports/ 目录（phase 6 产物文件）

之后调用 `repo.init_phase_runs(doc_id)`，保证所有阶段行回到 idle。
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, asdict
from typing import Any, Callable, Optional

from persistence.sqlite_repo_dev import PHASES


@dataclass
class ResetResult:
    ok: bool
    doc_id: str
    phase_from: int
    deleted_phase_runs: int = 0
    deleted_snapshots: int = 0
    deleted_export_files: int = 0
    deleted_snapshot_files: int = 0
    error: str = ""
    phase_runs: list[dict] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("phase_runs") is None:
            data.pop("phase_runs")
        return data


def _validate_phase(phase_from: int) -> int:
    try:
        value = int(phase_from)
    except Exception as exc:
        raise ValueError(f"phase_from 必须是整数: {phase_from!r}") from exc
    if value not in PHASES:
        raise ValueError(f"phase_from 必须在 {PHASES} 范围内，收到 {value}")
    return value


def _clear_export_dir(doc_dir: str) -> int:
    """删除 `<doc_dir>/dev_exports` 目录，返回被删除的文件数。"""
    if not doc_dir:
        return 0
    export_dir = os.path.join(doc_dir, "dev_exports")
    if not os.path.isdir(export_dir):
        return 0
    count = 0
    for root, _dirs, files in os.walk(export_dir):
        count += len(files)
    shutil.rmtree(export_dir, ignore_errors=True)
    return count


def reset_from_phase(
    doc_id: str,
    phase_from: int,
    *,
    repo: Any,
    get_doc_dir: Optional[Callable[[str], str]] = None,
) -> ResetResult:
    """把 `doc_id` 回退到 phase_from 之前的状态。

    参数：
      - `repo`：SingleDBRepository（需要有 `_delete_fnm_products_from_phase`,
        `delete_phase_runs_from`, `delete_dev_snapshots_from`, `init_phase_runs`）。
      - `get_doc_dir`：返回文档目录；若为 None 且 phase_from<=6，则跳过 dev_exports 清理。
    """
    doc_id_s = str(doc_id or "").strip()
    if not doc_id_s:
        return ResetResult(ok=False, doc_id="", phase_from=0, error="doc_id 不能为空")

    try:
        phase_n = _validate_phase(phase_from)
    except ValueError as exc:
        return ResetResult(ok=False, doc_id=doc_id_s, phase_from=0, error=str(exc))

    # 1) 清产物表（事务内）——走 facade，确保拆库模式路由到正确的 per-doc repo
    deleted_phase_runs = 0
    deleted_snapshots = 0
    deleted_exports = 0
    deleted_snapshot_files = 0

    try:
        repo.delete_fnm_products_from_phase(doc_id_s, phase_n)
    except Exception as exc:  # pragma: no cover - 防御：写失败抛上去
        return ResetResult(
            ok=False,
            doc_id=doc_id_s,
            phase_from=phase_n,
            error=f"清理产物表失败: {exc}",
        )

    # 2) 清 phase_runs / snapshots
    try:
        deleted_phase_runs = int(repo.delete_phase_runs_from(doc_id_s, phase_n) or 0)
    except Exception as exc:
        return ResetResult(
            ok=False,
            doc_id=doc_id_s,
            phase_from=phase_n,
            error=f"清理 phase_runs 失败: {exc}",
        )

    # 收集将被删除的 snapshot blob_path（DB 删除后无从查询）
    snapshot_blob_paths: list[str] = []
    if get_doc_dir is not None:
        try:
            for row in repo.list_dev_snapshots(doc_id_s) or []:
                row_phase = int(row.get("phase") or 0)
                blob = str(row.get("blob_path") or "").strip()
                if row_phase >= phase_n and blob:
                    snapshot_blob_paths.append(blob)
        except Exception:
            snapshot_blob_paths = []

    try:
        deleted_snapshots = int(repo.delete_dev_snapshots_from(doc_id_s, phase_n) or 0)
    except Exception as exc:
        return ResetResult(
            ok=False,
            doc_id=doc_id_s,
            phase_from=phase_n,
            error=f"清理 dev_snapshots 失败: {exc}",
        )

    # 删除 snapshot 磁盘文件（DB 已删成功才走到这里）
    if snapshot_blob_paths and get_doc_dir is not None:
        try:
            doc_dir = get_doc_dir(doc_id_s)
        except Exception:
            doc_dir = ""
        if doc_dir:
            for rel in snapshot_blob_paths:
                abs_path = os.path.join(doc_dir, rel)
                try:
                    if os.path.isfile(abs_path):
                        os.unlink(abs_path)
                        deleted_snapshot_files += 1
                except OSError:
                    continue

    # 3) Phase 6 的导出文件（仅在明确传入 get_doc_dir 时清理）
    if phase_n <= 6 and get_doc_dir is not None:
        try:
            doc_dir = get_doc_dir(doc_id_s)
        except Exception:
            doc_dir = ""
        if doc_dir:
            deleted_exports = _clear_export_dir(doc_dir)

    # 4) 把被删的阶段行重新补回 idle
    phase_runs: list[dict] | None = None
    try:
        phase_runs = list(repo.init_phase_runs(doc_id_s) or [])
    except Exception:
        phase_runs = None

    return ResetResult(
        ok=True,
        doc_id=doc_id_s,
        phase_from=phase_n,
        deleted_phase_runs=deleted_phase_runs,
        deleted_snapshots=deleted_snapshots,
        deleted_export_files=deleted_exports,
        deleted_snapshot_files=deleted_snapshot_files,
        phase_runs=phase_runs,
    )

"""FNM 开发模式：单阶段执行器（Phase 1 ~ Phase 6）。

外部接口：
  - `launch_phase(doc_id, phase, *, repo, pool, ...)`：异步启动（提交线程池），立刻返回。
  - `execute_phase(doc_id, phase, *, repo, ...)`：同步执行（给测试/CLI 用）。

各阶段行为：
  - Phase 1/2：跑 pipeline + 写产物表（fnm_pages / fnm_chapters / ...）。
  - Phase 3/4：跑 pipeline + gate + 写 phase_run，不回写产物表（避免污染生产数据）。
  - Phase 5：
      - test 模式：跑 builder 后在内存里给每个 unit 打 pseudo_done 标记。
      - real 模式：未接入 FNM Worker，直接返回失败。
  - Phase 6：跑 builder → gate，同时把 export_bundle.chapter_markdowns 写到
    `{doc_dir}/dev_exports/<chapter_id>.md`。
"""
from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from FNM_RE.app.persist_helpers import (
    load_fnm_toc_items,
    load_fnm_visual_toc_bundle,
    serialize_chapter_note_modes_for_repo,
    serialize_heading_candidates_for_repo,
    serialize_note_items_for_repo,
    serialize_note_regions_for_repo,
    serialize_pages_for_repo,
    serialize_section_heads_for_repo,
    to_plain,
)
from FNM_RE.dev.gates import GateReport, judge_phase
from FNM_RE.dev.thread_pool import Busy, DevThreadPool, get_default_pool
from persistence.sqlite_repo_dev import (
    PHASE_STATUS_FAILED,
    PHASE_STATUS_READY,
    PHASE_STATUS_RUNNING,
    PHASE_STATUS_UNSUPPORTED,
)


SUPPORTED_PHASES = (1, 2, 3, 4, 5, 6)


# ---------- 结果对象 ----------


@dataclass
class PhaseLaunchResult:
    """异步启动的回执：仅说明是否进入了 running 态。"""

    ok: bool
    doc_id: str
    phase: int
    status: str = ""  # running / busy / error
    error: str = ""
    phase_run: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "ok": self.ok,
            "doc_id": self.doc_id,
            "phase": self.phase,
            "status": self.status,
            "error": self.error,
        }
        if self.phase_run is not None:
            data["phase_run"] = self.phase_run
        return data


@dataclass
class PhaseExecutionResult:
    """同步执行的回执。"""

    ok: bool
    doc_id: str
    phase: int
    status: str = ""  # ready / failed
    error: str = ""
    errors: list[dict] = field(default_factory=list)
    page_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "doc_id": self.doc_id,
            "phase": self.phase,
            "status": self.status,
            "error": self.error,
            "errors": list(self.errors),
            "page_count": self.page_count,
        }


# ---------- 辅助：输入加载 ----------


def _default_load_pages_from_disk(doc_id: str) -> tuple[list[dict], str]:
    from persistence.storage import load_pages_from_disk as _impl

    return _impl(doc_id)


def _collect_region_maps(region_rows: list[dict]) -> tuple[dict[str, list[int]], dict[str, str], dict[str, str]]:
    region_pages_by_id: dict[str, list[int]] = {}
    note_kind_by_region_id: dict[str, str] = {}
    title_hint_by_region_id: dict[str, str] = {}
    for row in region_rows:
        region_id = str(row.get("region_id") or "")
        if not region_id:
            continue
        region_pages_by_id[region_id] = list(row.get("pages") or [])
        kind = str(row.get("region_kind") or "")
        if kind.startswith("book_endnote") or kind.startswith("chapter_endnote") or kind == "endnote":
            note_kind_by_region_id[region_id] = "endnote"
        else:
            note_kind_by_region_id[region_id] = "footnote"
        title_hint_by_region_id[region_id] = str(row.get("title_hint") or "")
    return region_pages_by_id, note_kind_by_region_id, title_hint_by_region_id


# ---------- 同步执行 ----------


def execute_phase(
    doc_id: str,
    phase: int,
    *,
    repo: Any,
    load_pages_from_disk: Optional[Callable[[str], tuple[list[dict], str]]] = None,
    pdf_path: str = "",
    execution_mode: str = "real",
    force_skip: bool = False,
) -> PhaseExecutionResult:
    """同步跑 Phase N：读数据 → 跑 pipeline → 写产物 → 更新 phase_runs。

    调用方负责确保线程池里只有一个这样的任务在跑。函数内部会更新 phase_runs
    的 status/gate_report。
    """
    doc_id_s = str(doc_id or "").strip()
    if not doc_id_s:
        return PhaseExecutionResult(ok=False, doc_id="", phase=int(phase or 0), error="doc_id 不能为空")
    if int(phase) not in SUPPORTED_PHASES:
        return PhaseExecutionResult(
            ok=False,
            doc_id=doc_id_s,
            phase=int(phase),
            error=f"phase {phase} 暂未接入开发模式执行器（仅支持 {SUPPORTED_PHASES}）",
        )
    phase_n = int(phase)

    # 标记 running（如果上层还没写）
    try:
        repo.upsert_phase_run(
            doc_id_s,
            phase_n,
            status=PHASE_STATUS_RUNNING,
            execution_mode=execution_mode,
            errors=[],
        )
    except Exception as exc:
        return PhaseExecutionResult(
            ok=False,
            doc_id=doc_id_s,
            phase=phase_n,
            error=f"无法标记 running: {exc}",
        )

    pages_loader = load_pages_from_disk or _default_load_pages_from_disk

    try:
        pages, _name = pages_loader(doc_id_s)
    except Exception as exc:
        return _mark_failed(repo, doc_id_s, phase_n, f"加载 pages 失败: {exc}")
    pages = list(pages or [])
    if not pages:
        return _mark_failed(repo, doc_id_s, phase_n, "未找到 OCR 页面数据（raw_pages 为空）")

    toc_items, toc_offset = load_fnm_toc_items(doc_id_s, repo)
    visual_toc_bundle = load_fnm_visual_toc_bundle(doc_id_s)

    # Phase 5 real 模式：dev 不接入 FNM Worker，返回 unsupported（不是 failed）。
    if phase_n == 5 and execution_mode == "real":
        return _mark_unsupported(
            repo,
            doc_id_s,
            phase_n,
            "Phase 5 real 模式未接入开发执行器，请用 test 模式或回生产路径跑翻译",
            errors=[
                {
                    "code": "phase5_real_not_wired",
                    "message": "dev 模式不直接调用 FNM Worker",
                }
            ],
        )

    # 跑 pipeline —— 进这里再 import，避免 pipeline 的重依赖影响模块加载
    from FNM_RE.app.pipeline import (
        build_phase1_structure,
        build_phase2_structure,
        build_phase3_structure,
        build_phase4_structure,
        build_phase5_structure,
        build_phase6_structure,
    )

    try:
        if phase_n == 1:
            structure = build_phase1_structure(
                pages,
                toc_items=toc_items,
                toc_offset=toc_offset,
                pdf_path=pdf_path,
                visual_toc_bundle=visual_toc_bundle,
            )
            _persist_phase1(repo, doc_id_s, structure)
        elif phase_n == 2:
            structure = build_phase2_structure(
                pages,
                toc_items=toc_items,
                toc_offset=toc_offset,
                pdf_path=pdf_path,
                visual_toc_bundle=visual_toc_bundle,
            )
            _persist_phase2(repo, doc_id_s, structure)
        elif phase_n == 3:
            structure = build_phase3_structure(
                pages,
                toc_items=toc_items,
                toc_offset=toc_offset,
                pdf_path=pdf_path,
                visual_toc_bundle=visual_toc_bundle,
            )
        elif phase_n == 4:
            structure = build_phase4_structure(
                pages,
                toc_items=toc_items,
                toc_offset=toc_offset,
                pdf_path=pdf_path,
                visual_toc_bundle=visual_toc_bundle,
            )
        elif phase_n == 5:
            structure = build_phase5_structure(
                pages,
                toc_items=toc_items,
                toc_offset=toc_offset,
                pdf_path=pdf_path,
                visual_toc_bundle=visual_toc_bundle,
            )
            _mark_units_pseudo_done(structure)
        else:  # phase_n == 6
            structure = build_phase6_structure(
                pages,
                toc_items=toc_items,
                toc_offset=toc_offset,
                pdf_path=pdf_path,
                visual_toc_bundle=visual_toc_bundle,
            )
            _mark_units_pseudo_done(structure)
            _write_dev_export(doc_id_s, structure)
    except Exception as exc:
        tb_tail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return _mark_failed(
            repo,
            doc_id_s,
            phase_n,
            f"pipeline 执行失败: {tb_tail}",
            errors=[{"code": "pipeline_exception", "message": tb_tail}],
        )

    # 跑 Gate：failures 非空则转 failed，但产物保留（便于诊断）
    gate_kwargs: dict[str, Any] = {}
    if phase_n in (5, 6):
        gate_kwargs["execution_mode"] = execution_mode
    try:
        report = judge_phase(phase_n, structure, **gate_kwargs)
    except Exception as exc:
        tb_tail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return _mark_failed(
            repo,
            doc_id_s,
            phase_n,
            f"Gate 判据执行异常: {tb_tail}",
            errors=[{"code": "gate_exception", "message": tb_tail}],
        )

    if report.failures and not force_skip:
        errs = [
            {"code": f.code, "message": f.message, "hint": f.hint, "evidence": f.evidence}
            for f in report.failures
        ]
        try:
            repo.upsert_phase_run(
                doc_id_s,
                phase_n,
                status=PHASE_STATUS_FAILED,
                gate_pass=False,
                gate_report=report.to_dict(),
                errors=errs,
            )
        except Exception as exc:
            return _mark_failed(repo, doc_id_s, phase_n, f"标记 failed 失败: {exc}")
        return PhaseExecutionResult(
            ok=False,
            doc_id=doc_id_s,
            phase=phase_n,
            status=PHASE_STATUS_FAILED,
            error=f"Gate {phase_n} 未通过：{len(report.failures)} 项失败",
            errors=errs,
            page_count=len(pages),
        )

    gate_report_payload = report.to_dict()
    if force_skip and report.failures:
        gate_report_payload["forced_skip"] = True
    try:
        repo.upsert_phase_run(
            doc_id_s,
            phase_n,
            status=PHASE_STATUS_READY,
            gate_pass=True,
            gate_report=gate_report_payload,
            forced_skip=bool(force_skip and report.failures),
            errors=[],
        )
    except Exception as exc:
        return _mark_failed(repo, doc_id_s, phase_n, f"标记 ready 失败: {exc}")

    return PhaseExecutionResult(
        ok=True,
        doc_id=doc_id_s,
        phase=phase_n,
        status=PHASE_STATUS_READY,
        page_count=len(pages),
    )


def _mark_failed(
    repo: Any,
    doc_id: str,
    phase: int,
    error: str,
    *,
    errors: Optional[list[dict]] = None,
) -> PhaseExecutionResult:
    errs = list(errors or [{"code": "phase_failed", "message": error}])
    try:
        repo.upsert_phase_run(
            doc_id,
            phase,
            status=PHASE_STATUS_FAILED,
            gate_pass=False,
            errors=errs,
        )
    except Exception:
        pass
    return PhaseExecutionResult(
        ok=False,
        doc_id=doc_id,
        phase=phase,
        status=PHASE_STATUS_FAILED,
        error=error,
        errors=errs,
    )


def _mark_unsupported(
    repo: Any,
    doc_id: str,
    phase: int,
    error: str,
    *,
    errors: Optional[list[dict]] = None,
) -> PhaseExecutionResult:
    """标记为 unsupported：区别于 failed，表示功能未接入而非执行出错。"""
    errs = list(errors or [{"code": "phase_unsupported", "message": error}])
    try:
        repo.upsert_phase_run(
            doc_id,
            phase,
            status=PHASE_STATUS_UNSUPPORTED,
            gate_pass=False,
            errors=errs,
        )
    except Exception:
        pass
    return PhaseExecutionResult(
        ok=False,
        doc_id=doc_id,
        phase=phase,
        status=PHASE_STATUS_UNSUPPORTED,
        error=error,
        errors=errs,
    )


def _persist_phase1(repo: Any, doc_id: str, structure: Any) -> None:
    repo.replace_fnm_phase1_products(
        doc_id,
        pages=serialize_pages_for_repo(list(structure.pages or [])),
        chapters=[to_plain(row) for row in (structure.chapters or [])],
        heading_candidates=serialize_heading_candidates_for_repo(list(structure.heading_candidates or [])),
        section_heads=serialize_section_heads_for_repo(list(structure.section_heads or [])),
    )


def _persist_phase2(repo: Any, doc_id: str, structure: Any) -> None:
    chapter_title_by_id = {
        str(row.chapter_id or ""): str(getattr(row, "title", "") or "")
        for row in (structure.chapters or [])
        if str(getattr(row, "chapter_id", "") or "")
    }
    region_rows = serialize_note_regions_for_repo(list(structure.note_regions or []))
    region_pages_by_id, note_kind_by_region_id, title_hint_by_region_id = _collect_region_maps(region_rows)
    note_item_rows = serialize_note_items_for_repo(
        list(structure.note_items or []),
        note_kind_by_region_id=note_kind_by_region_id,
        title_hint_by_region_id=title_hint_by_region_id,
    )
    note_mode_rows = serialize_chapter_note_modes_for_repo(
        list(structure.chapter_note_modes or []),
        chapter_title_by_id=chapter_title_by_id,
        region_pages_by_id=region_pages_by_id,
    )

    repo.replace_fnm_phase2_products(
        doc_id,
        pages=serialize_pages_for_repo(list(structure.pages or [])),
        chapters=[to_plain(row) for row in (structure.chapters or [])],
        heading_candidates=serialize_heading_candidates_for_repo(list(structure.heading_candidates or [])),
        section_heads=serialize_section_heads_for_repo(list(structure.section_heads or [])),
        note_regions=region_rows,
        chapter_note_modes=note_mode_rows,
        note_items=note_item_rows,
    )


# ---------- Phase 5/6 辅助 ----------


def _mark_units_pseudo_done(structure: Any) -> None:
    """把 translation_units 标成 pseudo_done，并写入 【TEST】 前缀译文。

    在 Phase 5 test 模式与 Phase 6（test 走法）下调用，确保 Gate 5 判定通过。
    """
    units = getattr(structure, "translation_units", None)
    if not units:
        return
    for unit in units:
        source = str(getattr(unit, "source_text", "") or "")
        try:
            unit.translated_text = f"【TEST】{source[:40]}"
            unit.status = "pseudo_done"
            unit.error_msg = ""
        except Exception:
            # dataclass slots 外的情况（如 dict）—— 静默忽略
            pass


def safe_chapter_slug(chapter_id: str) -> str:
    """章节 id 转文件名安全 slug：/ 与空白替换为 _。"""
    return str(chapter_id or "").replace("/", "_").replace(" ", "_")


def _write_dev_export(doc_id: str, structure: Any) -> list[str]:
    """把 Phase 6 export_bundle 的章节 markdown 落到 {doc_dir}/dev_exports/。

    返回写入的文件列表（相对路径）。失败不抛，记到 errors（上层决定）。
    """
    from config import get_doc_dir

    doc_dir = get_doc_dir(doc_id)
    if not doc_dir:
        return []
    export_dir = os.path.join(doc_dir, "dev_exports")
    os.makedirs(export_dir, exist_ok=True)

    export_chapters = list(getattr(structure, "export_chapters", []) or [])
    written: list[str] = []
    for idx, chapter in enumerate(export_chapters, start=1):
        chapter_id = str(getattr(chapter, "chapter_id", "") or f"ch{idx:03d}")
        markdown = str(getattr(chapter, "markdown", "") or "")
        safe = safe_chapter_slug(chapter_id)
        path = os.path.join(export_dir, f"{safe}.md")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(markdown)
            written.append(os.path.relpath(path, doc_dir))
        except OSError:
            continue
    return written


# ---------- 异步启动 ----------


def launch_phase(
    doc_id: str,
    phase: int,
    *,
    repo: Any,
    pool: Optional[DevThreadPool] = None,
    load_pages_from_disk: Optional[Callable[[str], tuple[list[dict], str]]] = None,
    pdf_path: str = "",
    execution_mode: str = "real",
    force_skip: bool = False,
) -> PhaseLaunchResult:
    """提交 Phase N 到线程池，立即返回。

    - 若该 doc 已有任务在跑：返回 `status="busy"`，不触碰 phase_runs。
    - 否则把 phase_runs.status 置 running 并 spawn 线程；线程内部调 `execute_phase`。
    """
    doc_id_s = str(doc_id or "").strip()
    if not doc_id_s:
        return PhaseLaunchResult(ok=False, doc_id="", phase=int(phase or 0), status="error", error="doc_id 不能为空")
    phase_n = int(phase)
    if phase_n not in SUPPORTED_PHASES:
        return PhaseLaunchResult(
            ok=False,
            doc_id=doc_id_s,
            phase=phase_n,
            status="error",
            error=f"phase {phase_n} 不在支持范围内 {SUPPORTED_PHASES}",
        )
    thread_pool = pool or get_default_pool()

    if thread_pool.is_busy(doc_id_s):
        current = thread_pool.current(doc_id_s) or {}
        return PhaseLaunchResult(
            ok=False,
            doc_id=doc_id_s,
            phase=phase_n,
            status="busy",
            error=f"doc {doc_id_s} 正在跑 phase {current.get('phase')}，请等结束后再试",
        )

    # 先把 phase_runs 标 running（主线程里写一次，保证前端立即能看到）
    try:
        phase_run = repo.upsert_phase_run(
            doc_id_s,
            phase_n,
            status=PHASE_STATUS_RUNNING,
            execution_mode=execution_mode,
            errors=[],
        )
    except Exception as exc:
        return PhaseLaunchResult(
            ok=False,
            doc_id=doc_id_s,
            phase=phase_n,
            status="error",
            error=f"无法标记 running: {exc}",
        )

    def _worker() -> None:
        execute_phase(
            doc_id_s,
            phase_n,
            repo=repo,
            load_pages_from_disk=load_pages_from_disk,
            pdf_path=pdf_path,
            execution_mode=execution_mode,
            force_skip=force_skip,
        )

    try:
        thread_pool.spawn(doc_id_s, phase_n, _worker)
    except Busy:
        return PhaseLaunchResult(
            ok=False,
            doc_id=doc_id_s,
            phase=phase_n,
            status="busy",
            error=f"doc {doc_id_s} 已有任务在跑",
        )

    return PhaseLaunchResult(
        ok=True,
        doc_id=doc_id_s,
        phase=phase_n,
        status="running",
        phase_run=phase_run,
    )

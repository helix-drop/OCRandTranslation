"""FNM 开发者模式诊断聚合。

输入：某个 `fnm_phase_runs` 行（含 `gate_report = {failures, warnings}`）。
输出：前端抽屉渲染用的 `failures` 列表，每条附 `evidence_refs` —— 指向
PDF 页、产物行、导出片段的统一引用。

`EvidenceRef` 结构（dict）：
    {
        "kind": "page" | "artifact" | "export",
        "label": str,                          # 在按钮上显示
        "page_no": int | None,                 # 1-based PDF 页码
        "paragraph_idx": int | None,           # 段落级（暂未填）
        "artifact": {                          # kind == "artifact" 时
            "phase": int,
            "table": str,
            "row_key": str,                    # 过滤字段名（如 region_id）
            "row_value": str,
        } | None,
        "export": {                            # kind == "export" 时
            "chapter_id": str,
            "line_start": int | None,
            "line_end": int | None,
        } | None,
    }

目前只覆盖 Phase 1~3 Gate 产出的 failure code；未识别的 code 只回显
原始 `evidence` 字段，不强行推断 ref。
"""
from __future__ import annotations

from typing import Any, Callable, Iterable


# ---------- 代码 → 证据映射 ----------


def _page_ref(page_no: int | None, *, label: str | None = None) -> dict[str, Any]:
    if page_no is None:
        return {}
    return {
        "kind": "page",
        "label": label or f"PDF 第 {page_no} 页",
        "page_no": int(page_no),
        "paragraph_idx": None,
        "artifact": None,
        "export": None,
    }


def _artifact_ref(
    phase: int,
    table: str,
    row_key: str,
    row_value: str,
    *,
    label: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "artifact",
        "label": label or f"{table} · {row_key}={row_value}",
        "page_no": None,
        "paragraph_idx": None,
        "artifact": {
            "phase": int(phase),
            "table": table,
            "row_key": row_key,
            "row_value": str(row_value),
        },
        "export": None,
    }


def _chapter_ref(chapter_id: str, *, label: str | None = None) -> dict[str, Any]:
    return _artifact_ref(
        1,
        "fnm_chapters",
        "chapter_id",
        chapter_id,
        label=label or f"章节 {chapter_id}",
    )


def _expand_ids(evidence: dict[str, Any], key: str) -> list[str]:
    raw = evidence.get(key) or []
    if isinstance(raw, str):
        return [raw]
    try:
        return [str(x) for x in raw if x]
    except TypeError:
        return []


def build_evidence_refs(failure: dict[str, Any]) -> list[dict[str, Any]]:
    """根据 failure.code + failure.evidence 产出 evidence_refs 列表。"""
    code = str(failure.get("code") or "")
    evidence = dict(failure.get("evidence") or {})
    refs: list[dict[str, Any]] = []

    # Phase 1
    if code == "phase1.chapter_missing_pages":
        for item in evidence.get("chapters", []) or []:
            if isinstance(item, dict) and item.get("chapter_id"):
                refs.append(_chapter_ref(str(item["chapter_id"])))
                ps = item.get("page_start")
                if isinstance(ps, int) and ps > 0:
                    refs.append(_page_ref(ps))
    elif code == "phase1.toc_alignment_review_required":
        refs.append(
            _artifact_ref(1, "fnm_chapters", "doc_id", "*", label="所有章节（TOC）")
        )
    elif code == "phase1.chapter_without_section_heads":
        for cid in _expand_ids(evidence, "chapter_ids"):
            refs.append(_chapter_ref(cid))

    # Phase 2
    elif code in ("phase2.note_region_missing_kind", "phase2.region_marker_misaligned"):
        for rid in _expand_ids(evidence, "region_ids"):
            refs.append(
                _artifact_ref(2, "fnm_note_regions", "region_id", rid)
            )
    elif code in (
        "phase2.chapter_note_mode_review_required",
        "phase2.chapter_no_notes",
    ):
        for cid in _expand_ids(evidence, "chapter_ids"):
            refs.append(
                _artifact_ref(
                    2,
                    "fnm_chapter_note_modes",
                    "chapter_id",
                    cid,
                    label=f"note_mode · {cid}",
                )
            )

    # Phase 3
    elif code in (
        "phase3.footnote_orphan_anchor",
        "phase3.footnote_orphan_note",
        "phase3.endnote_orphan_anchor",
        "phase3.endnote_orphan_note",
        "phase3.ambiguous_note_link",
    ):
        refs.append(
            _artifact_ref(3, "fnm_note_links", "doc_id", "*", label="note_links 汇总")
        )
    elif code in (
        "phase3.freeze_unmatched_frozen",
        "phase3.freeze_duplicate_injection",
    ):
        refs.append(
            _artifact_ref(
                3,
                "fnm_pages",
                "doc_id",
                "*",
                label="frozen_text（所有页）",
            )
        )
    elif code == "phase3.synthetic_anchor_warn":
        refs.append(
            _artifact_ref(
                3, "fnm_body_anchors", "doc_id", "*", label="body_anchors 汇总"
            )
        )

    return refs


# ---------- 对外聚合 ----------


def build_phase_diagnostics(phase_run: dict[str, Any] | None) -> dict[str, Any]:
    """把 phase_run 聚合成前端抽屉用的 payload。"""
    if not phase_run:
        return {
            "phase": None,
            "status": "idle",
            "gate_pass": False,
            "failures": [],
            "warnings": [],
            "forced_skip": False,
        }

    gate_report = dict(phase_run.get("gate_report") or {})
    failures_raw: Iterable[dict] = gate_report.get("failures") or []
    warnings_raw: Iterable[dict] = gate_report.get("warnings") or []

    def _enrich(items: Iterable[dict]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in items or []:
            payload = dict(item)
            payload["evidence_refs"] = build_evidence_refs(payload)
            out.append(payload)
        return out

    errors_list = list(phase_run.get("errors") or [])

    return {
        "phase": phase_run.get("phase"),
        "status": phase_run.get("status") or "idle",
        "gate_pass": bool(phase_run.get("gate_pass")),
        "forced_skip": bool(phase_run.get("forced_skip")),
        "failures": _enrich(failures_raw),
        "warnings": _enrich(warnings_raw),
        "errors": errors_list,
    }


__all__ = ["build_evidence_refs", "build_phase_diagnostics"]

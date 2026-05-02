#!/usr/bin/env python3
"""FNM 增量测试：冻结已确认成果，层层推进修复。

设计意图：不是"省 token"，而是避免重复劳动——把已通过验证的成果冻结在
pipeline 中，每次只对剩余问题逐层处理。Phase 1 数据冻结后不再变动，
Phase 2 确认后进入 Phase 3，以此类推。

用法:
  # 只跑 pipeline（Phase 1-6，无 LLM，秒级完成）
  .venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics

  # pipeline + LLM repair（对剩余 orphan 调 LLM 修补，适用于 Phase 3 之后的收尾）
  .venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics --repair

  # 多本书
  .venv/bin/python scripts/test_fnm_incremental.py --slug "Biopolitics,Goldstein"

  # 只检查已有 DB 数据（不跑 pipeline，看 Persisted 快照）
  .venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics --check

输出：按 phase 分组的 blocker 列表 + Module Phase 2/3 统计 + Persisted readback 对照。
当 Module Phase3 matched 与 Persisted matched 不一致时，显式告警分叉量。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from FNM_RE import run_doc_pipeline, run_llm_repair
from persistence.sqlite_store import SQLiteRepository

MODE_ALIASES = {
    "chapter_endnotes": "chapter_endnote_primary",
    "book_endnotes": "book_endnote_bound",
    "body_only": "no_notes",
}


def _canonical_mode(value: str) -> str:
    mode = str(value or "no_notes").strip() or "no_notes"
    return MODE_ALIASES.get(mode, mode)


def _counts(rows: list[dict], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows or []:
        token = str(row.get(key) or "").strip() or "(empty)"
        result[token] = result.get(token, 0) + 1
    return dict(sorted(result.items()))


def _resolve_doc_id(slug: str) -> str:
    # 已知映射，增量测试不用每次都查 DB
    KNOWN = {
        "Biopolitics": "0d285c0800db",
        "Germany_Madness": "67356d1f7d9a",
        "Goldstein": "7ba9bca783fd",
        "Heidegger_en_France": "a5d9a08d6871",
        "Mad_Act": "bd05138cd773",
        "Napoleon": "5df1d3d7f9c1",
        "Neuropsychoanalysis_in_Practice": "e7f8a1b6c2d3",
        "Neuropsychoanalysis_Introduction": "a3c9e1f7b284",
    }
    doc_id = KNOWN.get(slug, "")
    if not doc_id:
        raise SystemExit(f"未找到 slug={slug} 的 doc_id，请在 KNOWN 中补充")
    return doc_id


def _check_phase1(doc_id: str) -> dict[str, Any]:
    """检查 Phase 1 冻结数据是否干净。"""
    repo = SQLiteRepository()
    chapters = repo.list_fnm_chapters(doc_id)
    note_modes = repo.list_fnm_chapter_note_modes(doc_id)
    mode_counts: dict[str, int] = {}
    for m in (note_modes or []):
        mode = _canonical_mode(str(m.get("note_mode") or "no_notes"))
        mode_counts[mode] = mode_counts.get(mode, 0) + 1

    return {
        "chapter_count": len(chapters),
        "mode_counts": mode_counts,
        "phase1_clean": "review_required" not in mode_counts,
    }


def _check_phase2(doc_id: str) -> dict[str, Any]:
    """检查 Phase 2 输出。"""
    repo = SQLiteRepository()
    note_items = repo.list_fnm_note_items(doc_id)
    anchors = repo.list_fnm_body_anchors(doc_id)

    # 按章统计
    by_chapter: dict[str, dict] = {}
    for item in (note_items or []):
        cid = str(item.get("owner_chapter_id") or item.get("chapter_id") or "")
        by_chapter.setdefault(cid, {"items": 0, "anchors": 0})
        by_chapter[cid]["items"] += 1

    for anchor in (anchors or []):
        cid = str(anchor.get("chapter_id") or "")
        by_chapter.setdefault(cid, {"items": 0, "anchors": 0})
        by_chapter[cid]["anchors"] += 1

    sparse: list[str] = []
    for cid, counts in sorted(by_chapter.items()):
        if counts["items"] == 0 and counts["anchors"] >= 10:
            sparse.append(cid)

    return {
        "total_items": len(note_items),
        "total_anchors": len(anchors),
        "item_kind_counts": _counts(note_items, "note_kind"),
        "anchor_kind_counts": _counts(anchors, "anchor_kind"),
        "sparse_chapters": sparse,
        "chapter_details": {
            cid[:50]: counts
            for cid, counts in sorted(by_chapter.items())
            if counts["anchors"] > 0
        },
    }


def _check_persisted_note_links(doc_id: str) -> dict[str, Any]:
    """读取 pipeline 落库后的 note_links。

    这里不是 Module Phase 3 原始链接表。Phase4/Phase5/Phase6 可能会为了导出态
    重新打开未注入的 matched link，所以只能作为持久化 readback 观察。
    """
    repo = SQLiteRepository()
    links = repo.list_fnm_note_links(doc_id)
    if not links:
        return {"error": "no links"}

    matched = sum(1 for l in links if str(l.get("status") or "") == "matched")
    orphan_note = sum(1 for l in links if str(l.get("status") or "") == "orphan_note")
    orphan_anchor = sum(1 for l in links if str(l.get("status") or "") == "orphan_anchor")
    fallback = sum(1 for l in links if str(l.get("resolver") or "") == "fallback")
    fallback_matched = sum(
        1 for l in links
        if str(l.get("status") or "") == "matched" and str(l.get("resolver") or "") == "fallback"
    )
    total = len(links)
    fallback_ratio = fallback_matched / matched if matched > 0 else 0

    return {
        "total_links": total,
        "matched": matched,
        "orphan_note": orphan_note,
        "orphan_anchor": orphan_anchor,
        "status_counts": _counts(links, "status"),
        "note_kind_counts": _counts(links, "note_kind"),
        "footnote_orphan_note": sum(
            1
            for l in links
            if str(l.get("note_kind") or "") == "footnote" and str(l.get("status") or "") == "orphan_note"
        ),
        "footnote_orphan_anchor": sum(
            1
            for l in links
            if str(l.get("note_kind") or "") == "footnote" and str(l.get("status") or "") == "orphan_anchor"
        ),
        "endnote_orphan_note": sum(
            1
            for l in links
            if str(l.get("note_kind") or "") == "endnote" and str(l.get("status") or "") == "orphan_note"
        ),
        "endnote_orphan_anchor": sum(
            1
            for l in links
            if str(l.get("note_kind") or "") == "endnote" and str(l.get("status") or "") == "orphan_anchor"
        ),
        "fallback_count": fallback,
        "fallback_match_ratio": round(fallback_ratio, 4),
    }


def _run_pipeline_and_report(doc_id: str, slug: str, with_repair: bool = False) -> dict[str, Any]:
    """跑 pipeline 并汇总各 phase 状态。"""
    print(f"  Pipeline...", flush=True)
    result = run_doc_pipeline(doc_id)

    if with_repair:
        print(f"  LLM repair...", flush=True)
        repair_result = run_llm_repair(doc_id, auto_apply=True)
        print(f"    clusters={repair_result.get('cluster_count')}, "
              f"suggestions={repair_result.get('suggestion_count')}, "
              f"auto_applied={repair_result.get('auto_applied_count')}", flush=True)
        print(f"  Rebuild...", flush=True)
        result = run_doc_pipeline(doc_id)

    blocking = list(result.get("blocking_reasons") or [])

    # Phase 级别归因
    phase1_blockers = [r for r in blocking if r.startswith("toc_")]
    phase2_blockers = [r for r in blocking if r.startswith("split_")]
    phase3_blockers = [r for r in blocking if r.startswith("link_") or r.startswith("contract_")]
    phase4_blockers = [r for r in blocking if r.startswith("freeze_")]
    phase5_blockers = [r for r in blocking if r.startswith("merge_")]
    phase6_blockers = [r for r in blocking if r.startswith("export_")]
    fallback_blockers = [r for r in blocking if r == "structure_review_required"]

    report = {
        "slug": slug,
        "doc_id": doc_id,
        "structure_state": result.get("structure_state"),
        "blocking_reasons": blocking,
        "run_counts": {
            "note_count": int(result.get("note_count") or 0),
            "unit_count": int(result.get("unit_count") or 0),
            "section_count": int(result.get("section_count") or 0),
            "page_count": int(result.get("page_count") or 0),
        },
        "module_phase2_detail": dict(result.get("module_phase2_detail") or {}),
        "module_phase3_detail": dict(result.get("module_phase3_detail") or {}),
        "module_phase3_reasons": list(result.get("module_phase3_reasons") or []),
        "by_phase": {
            "phase1": phase1_blockers,
            "phase2": phase2_blockers,
            "phase3": phase3_blockers,
            "phase4": phase4_blockers,
            "phase5": phase5_blockers,
            "phase6": phase6_blockers,
            "fallback": fallback_blockers,
        },
    }

    # Phase 2-3 详情
    if not phase1_blockers:
        report["phase2_detail"] = _check_phase2(doc_id)
        report["persisted_links_detail"] = _check_persisted_note_links(doc_id)
        db_item_count = int(report["phase2_detail"].get("total_items") or 0)
        persisted_matched = int(report["persisted_links_detail"].get("matched") or 0)
        module_matched = int(report["module_phase3_detail"].get("matched") or 0)
        report["persisted_readback"] = {
            "note_count_matches_run": db_item_count == int(result.get("note_count") or 0),
            "run_note_count": int(result.get("note_count") or 0),
            "db_note_item_count": db_item_count,
            "persisted_matched_matches_module": persisted_matched == module_matched,
            "module_phase3_matched": module_matched,
            "persisted_matched": persisted_matched,
            "divergence": "none"
            if persisted_matched == module_matched
            else f"Module Phase3 matched={module_matched} → Persisted matched={persisted_matched} (delta={module_matched - persisted_matched})",
        }

    return report


def _print_report(report: dict[str, Any]) -> None:
    if report.get("check_only"):
        print(f"  Persisted note_links only (no Module Phase 3 snapshot)", flush=True)
    else:
        print(f"  structure_state: {report.get('structure_state')}", flush=True)
        mp2 = report.get("module_phase2_detail", {})
        if mp2:
            print(
                f"  Module Phase 2 items: {mp2.get('total_items')} "
                f"items_by_kind={mp2.get('item_kind_counts')}",
                flush=True,
            )
        mp3 = report.get("module_phase3_detail", {})
        if mp3:
            print(
                f"  Module Phase 3 links: matched={mp3.get('matched')}, "
                f"orphan_note={int(mp3.get('footnote_orphan_note') or 0) + int(mp3.get('endnote_orphan_note') or 0)} "
                f"(footnote={mp3.get('footnote_orphan_note')}, endnote={mp3.get('endnote_orphan_note')}), "
                f"orphan_anchor={int(mp3.get('footnote_orphan_anchor') or 0) + int(mp3.get('endnote_orphan_anchor') or 0)} "
                f"(footnote={mp3.get('footnote_orphan_anchor')}, endnote={mp3.get('endnote_orphan_anchor')}), "
                f"fallback_ratio={mp3.get('fallback_match_ratio')} "
                f"reasons={report.get('module_phase3_reasons')}",
                flush=True,
            )
        for phase, blockers in report.get("by_phase", {}).items():
            if blockers:
                print(f"  {phase}: {blockers}", flush=True)
            else:
                print(f"  {phase}: clean", flush=True)

    pd2 = report.get("phase2_detail", {})
    if pd2:
        print(
            f"  Persisted Phase 2 rows: items/anchors={pd2['total_items']}/{pd2['total_anchors']} "
            f"items_by_kind={pd2.get('item_kind_counts')} anchors_by_kind={pd2.get('anchor_kind_counts')}",
            flush=True,
        )
        if pd2["sparse_chapters"]:
            print(f"    sparse_chapters: {pd2['sparse_chapters']}", flush=True)

    pd3 = report.get("persisted_links_detail", {})
    if pd3:
        print(
            f"  Persisted note_links: matched={pd3.get('matched')}, "
            f"orphan_note={pd3.get('orphan_note')} "
            f"(footnote={pd3.get('footnote_orphan_note')}, endnote={pd3.get('endnote_orphan_note')}), "
            f"orphan_anchor={pd3.get('orphan_anchor')} "
            f"(footnote={pd3.get('footnote_orphan_anchor')}, endnote={pd3.get('endnote_orphan_anchor')}), "
            f"fallback_ratio={pd3.get('fallback_match_ratio')}",
            flush=True,
        )

    readback = report.get("persisted_readback", {})
    if readback and not readback.get("note_count_matches_run", True):
        print(
            "  WARNING: run note_count != DB note_item_count "
            f"({readback.get('run_note_count')} != {readback.get('db_note_item_count')})",
            flush=True,
        )
    if readback and not readback.get("persisted_matched_matches_module", True):
        print(
            "  WARNING: Persisted note_links matched != Module Phase 3 matched "
            f"({readback.get('persisted_matched')} != {readback.get('module_phase3_matched')})",
            flush=True,
        )
        print(
            "    This is a post-pipeline readback; treat Module Phase 3 as the Phase 3 gate source.",
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="FNM 增量测试（Phase 1 已冻结）")
    parser.add_argument("--slug", required=True, help="书名 slug，逗号分隔多个")
    parser.add_argument("--repair", action="store_true", help="同时跑 LLM repair")
    parser.add_argument("--check", action="store_true", help="只检查已有 DB 数据，不跑 pipeline")
    args = parser.parse_args()

    slugs = [s.strip() for s in args.slug.split(",")]
    reports: list[dict] = []
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"run_ts={run_ts}", flush=True)

    for slug in slugs:
        print(f"\n{'='*50}", flush=True)
        print(f"{slug}", flush=True)
        doc_id = _resolve_doc_id(slug)

        # Phase 1 冻结检查
        p1 = _check_phase1(doc_id)
        print(f"  DB Phase 1: {p1['chapter_count']} chapters, canonical_modes={p1['mode_counts']}", flush=True)
        if not p1["phase1_clean"]:
            print(f"  WARNING: Phase 1 未冻结！存在 review_required 章节", flush=True)
            reports.append({"slug": slug, "error": "phase1_not_clean", **p1})
            continue

        if args.check:
            report = {
                "slug": slug,
                "doc_id": doc_id,
                "check_only": True,
                "phase2_detail": _check_phase2(doc_id),
                "persisted_links_detail": _check_persisted_note_links(doc_id),
                "blocking_reasons": [],
            }
            reports.append(report)
            _print_report(report)
            continue

        report = _run_pipeline_and_report(doc_id, slug, with_repair=args.repair)
        reports.append(report)
        _print_report(report)

    # 汇总
    print(f"\n{'='*50}", flush=True)
    print(f"SUMMARY (run_ts={run_ts})", flush=True)
    for r in reports:
        if r.get("check_only"):
            pd3 = r.get("persisted_links_detail", {})
            print(
                f"  {r['slug']}: check-only persisted matched={pd3.get('matched')}, "
                f"orphan_note={pd3.get('orphan_note')}, orphan_anchor={pd3.get('orphan_anchor')}",
                flush=True,
            )
            continue
        reasons = r.get("blocking_reasons", [])
        print(f"  {r['slug']}: {len(reasons)} blockers — {reasons}", flush=True)
        readback = r.get("persisted_readback", {})
        divergence = readback.get("divergence", "none")
        if divergence and divergence != "none":
            print(f"    DIVERGENCE: {divergence}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

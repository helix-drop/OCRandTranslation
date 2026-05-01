#!/usr/bin/env python3
"""FNM 增量测试：Phase 1 已冻结，只测 Phase 2+。

用法:
  # 只跑 pipeline（Phase 1-6，无 LLM）
  .venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics

  # pipeline + llm_repair
  .venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics --repair

  # 只检查已有数据（不跑 pipeline）
  .venv/bin/python scripts/test_fnm_incremental.py --slug Biopolitics --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from FNM_RE import run_doc_pipeline, run_llm_repair
from persistence.sqlite_store import SQLiteRepository


def _resolve_doc_id(slug: str) -> str:
    # 已知映射，增量测试不用每次都查 DB
    KNOWN = {
        "Biopolitics": "0d285c0800db",
        "Germany_Madness": "67356d1f7d9a",
        "Goldstein": "7ba9bca783fd",
        "Heidegger_en_France": "a5d9a08d6871",
        "Mad_Act": "bd05138cd773",
        "Napoleon": "5df1d3d7f9c1",
        "Neuropsychoanalysis_in_Practice": "",  # 按需补充
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
        mode = str(m.get("note_mode") or "no_notes")
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
        "sparse_chapters": sparse,
        "chapter_details": {
            cid[:50]: counts
            for cid, counts in sorted(by_chapter.items())
            if counts["anchors"] > 0
        },
    }


def _check_phase3(doc_id: str) -> dict[str, Any]:
    """检查 Phase 3 链接质量。"""
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
        "fallback_count": fallback,
        "fallback_match_ratio": round(fallback_ratio, 4),
    }


def _run_pipeline_and_report(doc_id: str, slug: str, with_repair: bool = False) -> dict[str, Any]:
    """跑 pipeline 并汇总各 phase 状态。"""
    print(f"  Pipeline...")
    result = run_doc_pipeline(doc_id)

    if with_repair:
        print(f"  LLM repair...")
        repair_result = run_llm_repair(doc_id, auto_apply=True)
        print(f"    clusters={repair_result.get('cluster_count')}, "
              f"suggestions={repair_result.get('suggestion_count')}, "
              f"auto_applied={repair_result.get('auto_applied_count')}")
        print(f"  Rebuild...")
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
        report["phase3_detail"] = _check_phase3(doc_id)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="FNM 增量测试（Phase 1 已冻结）")
    parser.add_argument("--slug", required=True, help="书名 slug，逗号分隔多个")
    parser.add_argument("--repair", action="store_true", help="同时跑 LLM repair")
    parser.add_argument("--check", action="store_true", help="只检查已有 DB 数据，不跑 pipeline")
    args = parser.parse_args()

    slugs = [s.strip() for s in args.slug.split(",")]
    reports: list[dict] = []

    for slug in slugs:
        print(f"\n{'='*50}")
        print(f"{slug}")
        doc_id = _resolve_doc_id(slug)

        # Phase 1 冻结检查
        p1 = _check_phase1(doc_id)
        print(f"  Phase 1: {p1['chapter_count']} chapters, modes={p1['mode_counts']}")
        if not p1["phase1_clean"]:
            print(f"  WARNING: Phase 1 未冻结！存在 review_required 章节")
            reports.append({"slug": slug, "error": "phase1_not_clean", **p1})
            continue

        if args.check:
            print(f"  Phase 2: {json.dumps(_check_phase2(doc_id), indent=2)}")
            print(f"  Phase 3: {json.dumps(_check_phase3(doc_id), indent=2)}")
            continue

        report = _run_pipeline_and_report(doc_id, slug, with_repair=args.repair)
        reports.append(report)

        # 打印摘要
        print(f"  structure_state: {report['structure_state']}")
        for phase, blockers in report.get("by_phase", {}).items():
            if blockers:
                print(f"  {phase}: {blockers}")
            else:
                print(f"  {phase}: clean")

        pd2 = report.get("phase2_detail", {})
        if pd2:
            print(f"  Phase 2 items/anchors: {pd2['total_items']}/{pd2['total_anchors']}")
            if pd2["sparse_chapters"]:
                print(f"    sparse_chapters: {pd2['sparse_chapters']}")

        pd3 = report.get("phase3_detail", {})
        if pd3:
            print(f"  Phase 3 links: matched={pd3.get('matched')}, orphan_note={pd3.get('orphan_note')}, "
                  f"orphan_anchor={pd3.get('orphan_anchor')}, fallback_ratio={pd3.get('fallback_match_ratio')}")

    # 汇总
    print(f"\n{'='*50}")
    print("SUMMARY")
    for r in reports:
        reasons = r.get("blocking_reasons", [])
        print(f"  {r['slug']}: {len(reasons)} blockers — {reasons}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

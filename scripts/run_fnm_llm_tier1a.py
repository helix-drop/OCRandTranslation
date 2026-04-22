#!/usr/bin/env python3
"""Tier 1a LLM 修补批量执行 + 报告生成。

针对 `example_manifest` 中的样本书（默认 baseline），执行以下流程：

1. 检查 FNM 结构态；若 `manual_toc_required=True` 且样本目录下存在 `目录.pdf`，
   自动绑定为手动视觉目录并重跑视觉 TOC + FNM pipeline。
2. 记录基线 orphan 统计。
3. 执行 `run_llm_repair(cluster_limit=None)`，自动应用高置信动作。
4. 自动应用 > 0 时重建 FNM pipeline。
5. 再次读取 orphan 统计，统计 `llm-synth-%` anchor 行数与 scope 覆盖情况。
6. 输出两级报告：
   - 单书 `test_example/<folder>/FNM_LLM_TIER1A_REPORT.md`
   - 汇总 `test_example/FNM_LLM_TIER1A_BATCH_REPORT.md`

该脚本**不调用**真实翻译接口，也不尝试跑导出；只关心 LLM 修补对结构态的影响。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_EXAMPLE_ROOT = REPO_ROOT / "test_example"
OUTPUT_ROOT = REPO_ROOT / "output" / "tier1a_runs"
DEFAULT_TOC_PDF_NAME = "目录.pdf"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from example_manifest import ExampleBook, select_example_books  # noqa: E402
from FNM_RE import run_doc_pipeline as run_fnm_pipeline, run_llm_repair  # noqa: E402
from persistence.sqlite_store import SQLiteRepository  # noqa: E402
from persistence.storage_toc import save_toc_visual_manual_pdf  # noqa: E402
from pipeline.document_tasks import run_auto_visual_toc_for_doc  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tier 1a LLM 修补批量跑。")
    parser.add_argument("--slug", default="", help="仅处理指定 slug")
    parser.add_argument("--folder", default="", help="仅处理指定 folder")
    parser.add_argument("--doc-id", default="", help="仅处理指定 doc_id")
    parser.add_argument(
        "--group",
        choices=("baseline", "extension", "all"),
        default="all",
        help="manifest 分组过滤。默认 all。",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="纳入 manifest 里 include_in_default_batch=False 的样本。",
    )
    parser.add_argument(
        "--cluster-limit",
        type=int,
        default=0,
        help="LLM 修补簇上限；<=0 表示全部（默认）。",
    )
    parser.add_argument(
        "--max-unmatched-notes",
        type=int,
        default=24,
        help="每簇送入 LLM 的孤儿 note_item 上限。默认 24。",
    )
    parser.add_argument(
        "--max-unmatched-anchors",
        type=int,
        default=24,
        help="每簇送入 LLM 的孤儿 anchor 上限。默认 24。",
    )
    parser.add_argument(
        "--max-matched-examples",
        type=int,
        default=0,
        help="每簇送入 LLM 的已匹配示例上限；<=0 使用模块默认。",
    )
    parser.add_argument(
        "--no-auto-apply",
        action="store_true",
        help="只生成建议，不自动应用高置信结果。",
    )
    parser.add_argument(
        "--no-manual-toc-fallback",
        action="store_true",
        help="关闭 `目录.pdf` 自动回退。",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.9,
        help="auto-apply 的置信度阈值。默认 0.9。",
    )
    parser.add_argument(
        "--batch-tag",
        default="",
        help="本批次标签；默认使用当前时间戳。",
    )
    return parser.parse_args()


def _positive_or_none(value: int) -> int | None:
    return int(value) if int(value or 0) > 0 else None


def _git_commit_short() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT), stderr=subprocess.DEVNULL
        )
        return out.decode("utf-8").strip()
    except Exception:
        return ""


def _collect_orphan_counts(links: list[dict]) -> dict[str, int]:
    counts = {
        "footnote_orphan_note": 0,
        "footnote_orphan_anchor": 0,
        "endnote_orphan_note": 0,
        "endnote_orphan_anchor": 0,
        "ambiguous": 0,
    }
    for row in links or []:
        status = str(row.get("status") or "").strip()
        kind = str(row.get("note_kind") or "").strip()
        if status == "ambiguous":
            counts["ambiguous"] += 1
            continue
        if status not in {"orphan_note", "orphan_anchor"}:
            continue
        if kind not in {"footnote", "endnote"}:
            continue
        counts[f"{kind}_{status}"] = counts.get(f"{kind}_{status}", 0) + 1
    return counts


def _decide_verdict(
    *,
    baseline: dict,
    after: dict,
    blocking_reasons: list[str],
) -> str:
    """Tier1a 判定：

    - baseline 没有任何 orphan note → SKIP（LLM 无合成输入，不是失败）。
    - 本轮写出了 llm-synth anchor（llm_synth_anchor_count>0 且 anchor scope>0）→ PASS。
    - 其余情况 → FAIL。
    """
    orphans = (baseline or {}).get("orphans") or {}
    orphan_notes = int(orphans.get("footnote_orphan_note") or 0) + int(
        orphans.get("endnote_orphan_note") or 0
    )
    if orphan_notes == 0:
        return "SKIP"
    llm_synth = int((after or {}).get("llm_synth_anchor_count") or 0)
    anchor_scope = int(
        ((after or {}).get("override_scope_counts") or {}).get("anchor") or 0
    )
    if llm_synth > 0 and anchor_scope > 0:
        return "PASS"
    return "FAIL"


def _count_llm_synth_anchors(anchors: list[dict]) -> int:
    count = 0
    for row in anchors or []:
        anchor_id = str(row.get("anchor_id") or "")
        source = str(row.get("source") or "")
        if anchor_id.startswith("llm-synth-") or source == "llm":
            count += 1
    return count


def _count_override_scopes(overrides: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in overrides or []:
        scope = str(row.get("scope") or "").strip() or "unknown"
        counts[scope] = counts.get(scope, 0) + 1
    return counts


def _resolve_source_pdf(book: ExampleBook) -> Path | None:
    for candidate in [
        REPO_ROOT / "local_data" / "user_data" / "data" / "documents" / book.doc_id / "source.pdf",
    ]:
        if candidate.is_file():
            return candidate
    folder = TEST_EXAMPLE_ROOT / book.folder
    if folder.is_dir():
        for pdf_path in sorted(folder.glob("*.pdf")):
            if pdf_path.name == DEFAULT_TOC_PDF_NAME:
                continue
            return pdf_path
    return None


def _try_manual_toc_fallback(book: ExampleBook, *, logs: list[str]) -> dict[str, Any]:
    folder = TEST_EXAMPLE_ROOT / book.folder
    toc_pdf = folder / DEFAULT_TOC_PDF_NAME
    if not toc_pdf.is_file():
        logs.append(f"[{book.slug}] 未找到 {toc_pdf}，跳过手动 TOC 回退")
        return {"attempted": False, "reason": "toc_pdf_not_found"}
    source_pdf = _resolve_source_pdf(book)
    if not source_pdf:
        logs.append(f"[{book.slug}] 未找到原书 PDF，跳过手动 TOC 回退")
        return {"attempted": False, "reason": "source_pdf_not_found"}
    try:
        saved = save_toc_visual_manual_pdf(book.doc_id, str(toc_pdf), original_name=toc_pdf.name)
    except Exception as exc:
        logs.append(f"[{book.slug}] 绑定手动 TOC 失败：{exc}")
        return {"attempted": True, "ok": False, "stage": "save_toc_visual_manual_pdf", "error": str(exc)}
    try:
        visual_result = run_auto_visual_toc_for_doc(book.doc_id, str(source_pdf)) or {}
    except Exception as exc:
        logs.append(f"[{book.slug}] 重跑视觉 TOC 失败：{exc}")
        return {
            "attempted": True,
            "ok": False,
            "stage": "run_auto_visual_toc_for_doc",
            "error": str(exc),
            "saved_path": str(saved or ""),
        }
    try:
        fnm_result = run_fnm_pipeline(book.doc_id) or {}
    except Exception as exc:
        logs.append(f"[{book.slug}] 手动 TOC 回退后重建 FNM 失败：{exc}")
        return {
            "attempted": True,
            "ok": False,
            "stage": "run_fnm_pipeline",
            "error": str(exc),
            "saved_path": str(saved or ""),
            "visual_toc": visual_result,
        }
    logs.append(
        f"[{book.slug}] 手动 TOC 回退：visual_toc={visual_result.get('status')}, "
        f"structure_state={fnm_result.get('structure_state')}, "
        f"manual_toc_required={fnm_result.get('manual_toc_required')}"
    )
    return {
        "attempted": True,
        "ok": True,
        "saved_path": str(saved or ""),
        "visual_toc": visual_result,
        "fnm": fnm_result,
    }


def _structure_snapshot(doc_id: str, repo: SQLiteRepository) -> dict[str, Any]:
    links = repo.list_fnm_note_links(doc_id)
    anchors = repo.list_fnm_body_anchors(doc_id)
    overrides = repo.list_fnm_review_overrides(doc_id)
    return {
        "orphans": _collect_orphan_counts(links),
        "link_count": len(links or []),
        "body_anchor_count": len(anchors or []),
        "llm_synth_anchor_count": _count_llm_synth_anchors(anchors),
        "override_scope_counts": _count_override_scopes(overrides),
    }


def _ensure_structure_ready(
    book: ExampleBook,
    *,
    manual_toc_fallback: bool,
    logs: list[str],
) -> dict[str, Any]:
    """返回 {'ok': bool, 'pipeline': dict, 'manual_toc_fallback': dict, 'notes': [...]}."""
    try:
        initial = run_fnm_pipeline(book.doc_id) or {}
    except Exception as exc:
        return {
            "ok": False,
            "reason": "initial_pipeline_exception",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    if not initial.get("ok") and initial.get("error") == "no_pages":
        return {"ok": False, "reason": "no_pages", "pipeline": initial}
    result: dict[str, Any] = {"ok": True, "pipeline": initial}
    if not manual_toc_fallback:
        return result
    if not initial.get("manual_toc_required"):
        return result
    fallback = _try_manual_toc_fallback(book, logs=logs)
    result["manual_toc_fallback"] = fallback
    if fallback.get("attempted") and fallback.get("ok"):
        result["pipeline"] = fallback.get("fnm") or initial
    return result


def _run_repair(
    doc_id: str,
    repo: SQLiteRepository,
    *,
    args: argparse.Namespace,
) -> dict[str, Any]:
    cluster_limit = int(args.cluster_limit or 0)
    try:
        return run_llm_repair(
            doc_id,
            repo=repo,
            cluster_limit=cluster_limit if cluster_limit > 0 else None,
            auto_apply=not args.no_auto_apply,
            confidence_threshold=float(args.confidence_threshold),
            max_matched_examples=_positive_or_none(args.max_matched_examples),
            max_unmatched_note_items=_positive_or_none(args.max_unmatched_notes),
            max_unmatched_anchors=_positive_or_none(args.max_unmatched_anchors),
        )
    except Exception as exc:
        return {
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "cluster_count": 0,
            "suggestion_count": 0,
            "auto_applied_count": 0,
            "suggestions": [],
            "auto_applied": [],
        }


def _process_book(
    book: ExampleBook,
    *,
    args: argparse.Namespace,
    batch_tag: str,
    commit: str,
    logs: list[str],
) -> dict[str, Any]:
    repo = SQLiteRepository()
    logs.append(f"[{book.slug}] ===== 开始 =====")
    ensure = _ensure_structure_ready(
        book,
        manual_toc_fallback=not args.no_manual_toc_fallback,
        logs=logs,
    )
    if not ensure.get("ok"):
        verdict = "SKIP" if ensure.get("reason") == "no_pages" else "FAIL"
        return {
            "slug": book.slug,
            "folder": book.folder,
            "doc_id": book.doc_id,
            "verdict": verdict,
            "stage_failed": "ensure_structure",
            "ensure": ensure,
            "batch_tag": batch_tag,
            "commit": commit,
        }
    pipeline = ensure.get("pipeline") or {}
    manual_toc_fallback = ensure.get("manual_toc_fallback") or {}
    baseline = _structure_snapshot(book.doc_id, repo)
    repair_result = _run_repair(book.doc_id, repo, args=args)
    rebuild: dict[str, Any] = {}
    if int(repair_result.get("auto_applied_count") or 0) > 0:
        try:
            rebuild = run_fnm_pipeline(book.doc_id) or {}
        except Exception as exc:
            rebuild = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}
    after = _structure_snapshot(book.doc_id, repo)
    final_status = rebuild if rebuild else pipeline
    blocking_reasons = list(final_status.get("blocking_reasons") or [])
    manual_toc_required = bool(final_status.get("manual_toc_required"))
    verdict = _decide_verdict(
        baseline=baseline,
        after=after,
        blocking_reasons=blocking_reasons,
    )
    return {
        "slug": book.slug,
        "folder": book.folder,
        "doc_id": book.doc_id,
        "verdict": verdict,
        "batch_tag": batch_tag,
        "commit": commit,
        "pipeline": final_status,
        "manual_toc_fallback": manual_toc_fallback,
        "baseline": baseline,
        "after": after,
        "repair": repair_result,
        "rebuild": rebuild,
        "blocking_reasons": blocking_reasons,
        "manual_toc_required": manual_toc_required,
    }


def _sum_orphans(orphans: dict[str, int]) -> dict[str, int]:
    fn = int(orphans.get("footnote_orphan_note", 0)) + int(orphans.get("footnote_orphan_anchor", 0))
    en = int(orphans.get("endnote_orphan_note", 0)) + int(orphans.get("endnote_orphan_anchor", 0))
    return {"fn": fn, "en": en}


def _format_orphan_delta(baseline: dict, after: dict) -> str:
    before = _sum_orphans(baseline.get("orphans") or {})
    now = _sum_orphans(after.get("orphans") or {})
    return f"`{before['fn']} / {before['en']}` → `{now['fn']} / {now['en']}`"


def _build_per_book_report(item: dict[str, Any]) -> str:
    slug = item.get("slug") or item.get("doc_id")
    verdict = str(item.get("verdict") or "FAIL")
    lines: list[str] = [
        f"# FNM Tier 1a LLM 修补测试报告 — {slug}",
        "",
        f"- doc_id: `{item.get('doc_id','')}`",
        f"- 测试批次: `{item.get('batch_tag','')}`",
        f"- 代码版本 / commit: `{item.get('commit','')}`",
        "",
    ]
    dashscope_ok = bool(os.environ.get("DASHSCOPE_API_KEY"))
    pipeline = item.get("pipeline") or {}
    lines += [
        "## 1. 前置检查",
        f"- shell 环境变量 `DASHSCOPE_API_KEY`: {'yes' if dashscope_ok else 'no（shell 检测为空）'}",
        f"- 入库 + 结构化管线: {'yes' if pipeline.get('ok', False) else 'no'}",
        f"- manual_toc_required（最终态）: {bool(item.get('manual_toc_required'))}",
        f"- blocking_reasons: `{list(item.get('blocking_reasons') or [])}`",
    ]
    manual_toc_fallback = item.get("manual_toc_fallback") or {}
    if manual_toc_fallback.get("attempted"):
        visual = (manual_toc_fallback.get("visual_toc") or {}).get("status") or ""
        fnm = (manual_toc_fallback.get("fnm") or {}).get("structure_state") or ""
        lines.append(
            f"- 手动 TOC 回退: attempted=yes, ok={manual_toc_fallback.get('ok')}, "
            f"visual_toc={visual}, structure_state={fnm}"
        )
        if not manual_toc_fallback.get("ok"):
            lines.append(f"  - 失败阶段: `{manual_toc_fallback.get('stage','')}` — {manual_toc_fallback.get('error','')}")
    else:
        lines.append(
            f"- 手动 TOC 回退: 未触发（reason=`{manual_toc_fallback.get('reason','not_needed')}`）"
        )
    lines.append("")
    baseline = item.get("baseline") or {}
    base_orphans = baseline.get("orphans") or {}
    lines += [
        "## 2. 基线 orphan 统计（LLM 前）",
        f"- footnote orphan_note: {int(base_orphans.get('footnote_orphan_note', 0))}",
        f"- endnote orphan_note: {int(base_orphans.get('endnote_orphan_note', 0))}",
        f"- footnote orphan_anchor: {int(base_orphans.get('footnote_orphan_anchor', 0))}",
        f"- endnote orphan_anchor: {int(base_orphans.get('endnote_orphan_anchor', 0))}",
        f"- ambiguous: {int(base_orphans.get('ambiguous', 0))}",
        "",
    ]
    repair = item.get("repair") or {}
    lines += [
        "## 3. Step A LLM dry-run 结果",
        f"- cluster_count: {int(repair.get('cluster_count') or 0)}",
        f"- suggestion_count: {int(repair.get('suggestion_count') or 0)}",
        f"- action 分布: `{repair.get('action_counts') or {}}`",
        f"- synth_suggestion_count: {int(repair.get('synth_suggestion_count') or 0)}",
        f"- fuzzy_hit_count / fuzzy_ambiguous_count: "
        f"{int(repair.get('fuzzy_hit_count') or 0)} / {int(repair.get('fuzzy_ambiguous_count') or 0)}",
        f"- caps: `{repair.get('caps') or {}}`",
        "",
        "## 4. Step B 自动应用结果",
        f"- auto_applied_count: {int(repair.get('auto_applied_count') or 0)}",
        f"- auto action 分布: `{repair.get('auto_action_counts') or {}}`",
        f"- synth_auto_applied_count: {int(repair.get('synth_auto_applied_count') or 0)}",
        f"- rebuild.ok: {item.get('rebuild', {}).get('ok', 'N/A（未触发）')}",
        "",
    ]
    after = item.get("after") or {}
    lines += [
        "## 5. Step C DB 验证",
        f"- scope 计数: `{after.get('override_scope_counts') or {}}`",
        f"- llm-synth anchor 行数: {int(after.get('llm_synth_anchor_count') or 0)}",
        f"- 结论: {'满足' if verdict == 'PASS' else '未满足'}硬性通过条件"
        f"（要求 llm-synth anchor 行数 > 0 且 scope='anchor' 覆盖写入）",
        "",
        "## 6. Step D orphan 收敛",
        f"- before→after: {_format_orphan_delta(baseline, after)}",
        "",
    ]
    final = item.get("pipeline") or {}
    lines += [
        "## 7. Step E 下游烟测",
        f"- pipeline: `sections={final.get('section_count', 0)}, "
        f"notes={final.get('note_count', 0)}, units={final.get('unit_count', 0)}`",
        f"- structure_state: `{final.get('structure_state', '')}`",
        f"- blocking_reasons: `{list(final.get('blocking_reasons') or [])}`",
        "",
        "## 8. 异常与待跟进",
    ]
    if "error" in repair:
        lines.append(f"- LLM 修补异常：`{repair.get('error')}`")
    if item.get("manual_toc_required"):
        lines.append("- 最终态仍存在 `manual_toc_required`，需要人工复核/手动 TOC。")
    if int(after.get("llm_synth_anchor_count") or 0) == 0:
        lines.append("- 本轮未产出 `llm-synth-%` anchor。")
    lines += [
        "",
        "## 9. 结论",
        f"**总体判定：{verdict}**",
        "",
    ]
    return "\n".join(lines)


def _build_batch_report(results: list[dict[str, Any]], *, batch_tag: str, commit: str) -> str:
    lines: list[str] = [
        f"# Tier 1a LLM 修补 — 批量报告",
        "",
        f"- 批次目录：`output/tier1a_runs/{batch_tag}`",
        f"- 代码版本 / commit：`{commit}`",
        "",
        "## 总览表",
        "",
        "| slug | doc_id | orphan before (fn/en) | orphan after (fn/en) | auto_applied | synth_anchors | verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    passed = failed = skipped = 0
    for item in results:
        verdict = str(item.get("verdict") or "FAIL")
        if verdict == "PASS":
            passed += 1
        elif verdict == "SKIP":
            skipped += 1
        else:
            failed += 1
        before = _sum_orphans((item.get("baseline") or {}).get("orphans") or {})
        now = _sum_orphans((item.get("after") or {}).get("orphans") or {})
        auto_applied = int((item.get("repair") or {}).get("auto_applied_count") or 0)
        synth = int((item.get("after") or {}).get("llm_synth_anchor_count") or 0)
        lines.append(
            f"| {item.get('slug','')} | `{item.get('doc_id','')}` | "
            f"`{before['fn']} / {before['en']}` | `{now['fn']} / {now['en']}` | "
            f"{auto_applied} | {synth} | {verdict} |"
        )
    lines += [
        "",
        f"- PASS: {passed}，FAIL: {failed}，SKIP: {skipped}",
        "",
        "## 跨书发现",
    ]
    synth_total = sum(int((item.get("after") or {}).get("llm_synth_anchor_count") or 0) for item in results)
    lines.append(f"- 所有书合计 llm-synth anchor 行数：{synth_total}")
    manual_toc_books = [
        item.get("slug", "") for item in results if item.get("manual_toc_required")
    ]
    if manual_toc_books:
        lines.append(f"- 仍 `manual_toc_required`：{manual_toc_books}")
    skipped_books = [
        item.get("slug", "") for item in results if str(item.get("verdict") or "") == "SKIP"
    ]
    if skipped_books:
        lines.append(f"- 跳过（onboard/OCR 前置失败）：{skipped_books}")
    lines += [
        "",
        "## 链接到各书详细报告",
        "",
    ]
    for item in results:
        folder = item.get("folder") or ""
        slug = item.get("slug") or ""
        rel = f"{folder}/FNM_LLM_TIER1A_REPORT.md"
        lines.append(f"- [{slug}]({rel})")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    batch_tag = str(args.batch_tag or time.strftime("%Y%m%d_%H%M%S"))
    commit = _git_commit_short()
    batch_dir = OUTPUT_ROOT / batch_tag
    batch_dir.mkdir(parents=True, exist_ok=True)

    books = select_example_books(
        include_all=bool(args.include_all),
        group=args.group or "all",
        slug=args.slug or "",
        folder=args.folder or "",
        doc_id=args.doc_id or "",
    )
    if not books:
        print("未匹配到任何样本。", file=sys.stderr)
        return 2

    logs: list[str] = []
    results: list[dict[str, Any]] = []
    for book in books:
        try:
            item = _process_book(
                book, args=args, batch_tag=batch_tag, commit=commit, logs=logs
            )
        except Exception as exc:
            item = {
                "slug": book.slug,
                "folder": book.folder,
                "doc_id": book.doc_id,
                "verdict": "FAIL",
                "stage_failed": "process_book_exception",
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "batch_tag": batch_tag,
                "commit": commit,
            }
            logs.append(f"[{book.slug}] 处理异常：{exc}")
        results.append(item)
        folder_dir = TEST_EXAMPLE_ROOT / book.folder
        if folder_dir.is_dir():
            (folder_dir / "FNM_LLM_TIER1A_REPORT.md").write_text(
                _build_per_book_report(item), encoding="utf-8"
            )
        (batch_dir / f"{book.slug or book.doc_id}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"[{item.get('verdict','?')}] {book.slug} "
            f"auto_applied={(item.get('repair') or {}).get('auto_applied_count', 0)} "
            f"synth={(item.get('after') or {}).get('llm_synth_anchor_count', 0)}"
        )

    batch_report = _build_batch_report(results, batch_tag=batch_tag, commit=commit)
    (TEST_EXAMPLE_ROOT / "FNM_LLM_TIER1A_BATCH_REPORT.md").write_text(batch_report, encoding="utf-8")
    (batch_dir / "batch_summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (batch_dir / "logs.txt").write_text("\n".join(logs) + "\n", encoding="utf-8")

    passed = sum(1 for item in results if str(item.get("verdict")) == "PASS")
    failed = sum(1 for item in results if str(item.get("verdict")) == "FAIL")
    skipped = sum(1 for item in results if str(item.get("verdict")) == "SKIP")
    print(f"\n汇总：PASS={passed}, FAIL={failed}, SKIP={skipped}")
    print(f"单书报告已写入 test_example/<folder>/FNM_LLM_TIER1A_REPORT.md")
    print(f"汇总报告：test_example/FNM_LLM_TIER1A_BATCH_REPORT.md")
    print(f"批次目录：{batch_dir}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

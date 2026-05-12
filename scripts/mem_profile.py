#!/usr/bin/env python3
"""FNM Pipeline 内存性能分析脚本。
逐阶段记录 RSS 峰值，检测异常和回滚。
用法: .venv/bin/python scripts/mem_profile.py --slug Heidegger_en_France [--streaming]
"""
from __future__ import annotations

import argparse, os, re, subprocess, sys, time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# ── Phase 映射 ──
PHASE_MAP = [
    (97.0, 98.5, "Phase 1a: toc_structure"),
    (98.5, 98.6, "Phase 1b: book_note_profile"),
    (98.6, 98.7, "Phase 1c: llm_book_type_verify"),
    (98.7, 99.2, "Phase 2a: chapter_layers"),
    (99.2, 99.5, "Phase 2b: sup_recovery (implicit)"),
    (99.5, 99.7, "Phase 3:  note_linking"),
    (99.7, 99.8, "Phase 4:  frozen_units"),
    (99.8, 99.9, "Phase 5:  chapter_markdown_set"),
    (99.9, 100.1, "Phase 6:  export_bundle"),
]


def get_rss(pid: int) -> float:
    try:
        return int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)]).strip()) / 1024
    except Exception:
        return 0.0


def resolve_doc_id(slug: str) -> str:
    # 使用 test 脚本的映射
    known = {
        "Biopolitics": "0d285c0800db",
        "Germany_Madness": "67356d1f7d9a",
        "Goldstein": "7ba9bca783fd",
        "Heidegger_en_France": "a5d9a08d6871",
        "Mad_Act": "bd05138cd773",
        "Napoleon": "5df1d3d7f9c1",
    }
    return known.get(slug, slug)


def run_test(slug: str, streaming: bool = False) -> dict[str, Any]:
    """跑一次完整测试，收集各阶段 RSS 和异常。"""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "test_fnm_incremental.py"),
        "--slug", slug,
        "--verbose",
    ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )

    stages: list[dict] = []  # [{pct, stage, rss, dur_ms, elapsed_s}]
    errors: list[str] = []
    start = time.time()
    prev_rss = 0.0

    # 收集 stdout 进度行
    for line in proc.stdout:
        m = re.search(r"\]\s+(\S+)\s+done\s+\((\d+)ms\)", line)
        if m:
            stage = m.group(1)
            dur_ms = int(m.group(2))
            pct = 0.0
            pct_m = re.search(r"\[\s*([\d.]+)\%\]", line)
            if pct_m:
                pct = float(pct_m.group(1))
            rss = get_rss(proc.pid)
            delta = rss - prev_rss if prev_rss else 0
            stages.append({
                "pct": pct, "stage": stage, "rss": rss,
                "delta": delta, "dur_ms": dur_ms, "elapsed_s": time.time() - start,
            })
            prev_rss = rss

    proc.wait()
    stderr_text = proc.stderr.read()

    # 收集 stderr 异常
    for line in stderr_text.splitlines():
        if "Traceback" in line or "Error" in line or "回滚" in line or "FAILED" in line:
            errors.append(line.strip())

    return {
        "exit_code": proc.returncode,
        "stages": stages,
        "errors": errors,
        "total_s": time.time() - start,
        "slug": slug,
    }


def phase_name(pct: float) -> str:
    for lo, hi, name in PHASE_MAP:
        if lo <= pct < hi:
            return name
    return "other"


def format_report(result: dict[str, Any]) -> str:
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  内存分析报告: {result['slug']}")
    lines.append(f"{'='*70}")

    stages = result["stages"]
    if not stages:
        lines.append("  ⚠ 未收集到任何阶段数据")
        return "\n".join(lines)

    # 错误
    if result["errors"]:
        lines.append(f"\n  ❌ 检测到 {len(result['errors'])} 个异常:")
        for e in result["errors"][:10]:
            lines.append(f"     {e[:100]}")
        if len(result["errors"]) > 10:
            lines.append(f"     ... 还有 {len(result['errors']) - 10} 个")
    else:
        lines.append(f"\n  ✅ 无异常")

    if result["exit_code"] != 0:
        lines.append(f"  ❌ exit_code={result['exit_code']}")

    # 阶段 RSS 时间线
    lines.append(f"\n  {'Stage':<35s} {'RSS':>7s} {'Δ':>7s} {'耗时':>8s}")
    lines.append(f"  {'-'*60}")
    for s in stages:
        ph = phase_name(s["pct"])
        lines.append(
            f"  [{s['pct']:5.1f}%] {s['stage']:<25s} {s['rss']:6.0f} MB {s['delta']:+6.0f} MB {s['dur_ms']/1000:7.1f}s"
        )

    # 按 Phase 聚合
    phase_peaks: dict[str, float] = {}
    phase_mins: dict[str, float] = {}
    for s in stages:
        ph = phase_name(s["pct"])
        phase_peaks[ph] = max(phase_peaks.get(ph, 0), s["rss"])
        phase_mins[ph] = min(phase_mins.get(ph, 9999), s["rss"])

    lines.append(f"\n  {'Phase':<45s} {'Min':>7s} {'Peak':>7s} {'范围':>7s}")
    lines.append(f"  {'-'*65}")
    baseline = 0.0
    for lo, hi, name in PHASE_MAP:
        if name in phase_peaks:
            p = phase_peaks[name]
            m = phase_mins[name]
            delta_from_start = p - baseline if baseline else 0
            if not baseline:
                baseline = p
            lines.append(f"  {name:<45s} {m:6.0f} MB {p:6.0f} MB {delta_from_start:+6.0f} MB")

    # 全局峰值
    peak = max(stages, key=lambda s: s["rss"])
    final = stages[-1]
    lines.append(f"\n  全局峰值: {peak['rss']:.0f} MB @ [{peak['pct']:.1f}%] {peak['stage']}")
    lines.append(f"  终态:     {final['rss']:.0f} MB @ [{final['pct']:.1f}%] {final['stage']}")
    lines.append(f"  总耗时:   {result['total_s']:.0f}s")
    lines.append(f"{'='*70}\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="FNM Pipeline 内存分析")
    parser.add_argument("--slug", default="Heidegger_en_France")
    parser.add_argument("--streaming", action="store_true", help="使用流式 page 加载")
    parser.add_argument("--runs", type=int, default=1, help="重复次数（取平均）")
    args = parser.parse_args()

    all_results = []
    for i in range(args.runs):
        if args.runs > 1:
            print(f"\nRun {i+1}/{args.runs}...", flush=True)
        result = run_test(args.slug, streaming=args.streaming)
        all_results.append(result)
        print(format_report(result))

    if args.runs > 1:
        # 平均
        for ph_name in [name for _, _, name in PHASE_MAP]:
            peaks = []
            for r in all_results:
                for s in r["stages"]:
                    if phase_name(s["pct"]) == ph_name:
                        peaks.append(s["rss"])
            if peaks:
                print(f"  {ph_name}: avg={sum(peaks)/len(peaks):.0f} MB (n={len(peaks)})")


if __name__ == "__main__":
    main()

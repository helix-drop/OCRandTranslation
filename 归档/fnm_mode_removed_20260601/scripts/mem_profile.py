#!/usr/bin/env python3
"""FNM Pipeline 内存性能分析脚本。
逐阶段记录 RSS 峰值，定期采样捕捉中间峰值，事后分析 DB 表大小。
用法: .venv/bin/python scripts/mem_profile.py --slug Heidegger_en_France [--detail]
"""
from __future__ import annotations

import argparse, json, os, re, subprocess, sys, threading, time
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
    """采样进程树 RSS（含所有子进程后代），确保 renderer 微进程峰值不被漏看。"""
    try:
        total = 0
        # 递归收集所有后代 PID
        pids = {pid}
        queue = [pid]
        while queue:
            parent = queue.pop()
            try:
                children = subprocess.check_output(
                    ["pgrep", "-P", str(parent)]
                ).decode().strip().split()
                for child in children:
                    child_pid = int(child)
                    if child_pid not in pids:
                        pids.add(child_pid)
                        queue.append(child_pid)
            except Exception:
                pass
        for p in pids:
            try:
                total += int(subprocess.check_output(
                    ["ps", "-o", "rss=", "-p", str(p)]
                ).strip())
            except Exception:
                pass
        return total / 1024
    except Exception:
        return 0.0


def resolve_doc_id(slug: str) -> str:
    known = {
        "Biopolitics": "0d285c0800db",
        "Germany_Madness": "67356d1f7d9a",
        "Goldstein": "7ba9bca783fd",
        "Heidegger_en_France": "a5d9a08d6871",
        "Mad_Act": "bd05138cd773",
        "Napoleon": "5df1d3d7f9c1",
    }
    return known.get(slug, slug)


def run_test(slug: str, detail: bool = False) -> dict[str, Any]:
    """跑一次完整测试，收集各阶段 RSS 和异常。外置定期采样捕捉峰值。"""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "test_fnm_incremental.py"),
        "--slug", slug,
        "--verbose",
    ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # 确保不在 pipeline 进程内做内存检测
    env.pop("FNM_MEMORY_TRACE", None)

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )

    stages: list[dict] = []
    errors: list[str] = []
    start = time.time()
    rss_samples: list[tuple[float, float]] = []
    sample_stop = threading.Event()
    stderr_lines: list[str] = []

    # 后台线程读 stderr（防止 pipe 满导致子进程死锁）
    def _drain_stderr():
        for line in proc.stderr:
            stderr_lines.append(line.rstrip())
    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    # 定期采样 + 存活检测线程
    last_report = start
    def _periodic_sample():
        nonlocal last_report
        while not sample_stop.is_set():
            rss = get_rss(proc.pid)
            alive = proc.poll() is None
            if rss > 0:
                rss_samples.append((time.time() - start, rss))
            # 每 30 秒报告存活状态
            now = time.time()
            if now - last_report >= 30:
                status = "ALIVE" if alive else "EXITED"
                print(f"  [watchdog {now-start:.0f}s] {status} RSS={rss:.0f}MB samples={len(rss_samples)}", flush=True)
                last_report = now
            time.sleep(1.0)

    sampler = threading.Thread(target=_periodic_sample, daemon=True)
    sampler.start()

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
            delta = rss - (stages[-1]["rss"] if stages else 0)
            stages.append({
                "pct": pct, "stage": stage, "rss": rss,
                "delta": delta, "dur_ms": dur_ms, "elapsed_s": time.time() - start,
            })

    sample_stop.set()
    sampler.join(timeout=2)
    proc.wait()
    stderr_thread.join(timeout=2)

    for line in stderr_lines:
        if "Traceback" in line or "Error" in line or "回滚" in line or "FAILED" in line:
            errors.append(line.strip())

    peak_sample = max(rss_samples, key=lambda x: x[1]) if rss_samples else (0, 0)

    return {
        "exit_code": proc.returncode,
        "stages": stages,
        "errors": errors,
        "total_s": time.time() - start,
        "slug": slug,
        "rss_samples": rss_samples,
        "peak_sample_elapsed": peak_sample[0],
        "peak_sample_rss": peak_sample[1],
    }


def phase_name(pct: float) -> str:
    for lo, hi, name in PHASE_MAP:
        if lo <= pct < hi:
            return name
    return "other"


def analyze_db(doc_id: str) -> dict[str, int]:
    """外置 DB 分析——读取各表行数和大小（不影响 pipeline 进程）。"""
    result: dict[str, int] = {}
    try:
        from persistence.sqlite_store import get_document_db_path
        import sqlite3
        db_path = get_document_db_path(doc_id)
        conn = sqlite3.connect(db_path)
        for table in ["fnm_pages", "fnm_chapters", "fnm_note_items", "fnm_body_anchors",
                       "fnm_note_links", "fnm_translation_units", "fnm_chapter_body_pages"]:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                size = conn.execute(f"SELECT SUM(LENGTH(page_segments_json)) FROM {table}").fetchone()[0] or 0 if table == "fnm_translation_units" else 0
                result[f"{table}_rows"] = count
                if size:
                    result[f"{table}_segments_mb"] = int(size / 1024 / 1024)
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    return result


def format_report(result: dict[str, Any], db_info: dict[str, int] | None = None) -> str:
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  内存分析报告: {result['slug']}")
    lines.append(f"{'='*70}")

    stages = result["stages"]
    if not stages:
        lines.append("  ⚠ 未收集到任何阶段数据")
        return "\n".join(lines)

    if result["errors"]:
        lines.append(f"\n  ❌ 检测到 {len(result['errors'])} 个异常:")
        for e in result["errors"][:10]:
            lines.append(f"     {e[:100]}")
    else:
        lines.append(f"\n  ✅ 无异常")

    if result["exit_code"] != 0:
        lines.append(f"  ❌ exit_code={result['exit_code']}")

    # 阶段 RSS 时间线
    lines.append(f"\n  {'Stage':<35s} {'RSS':>7s} {'Δ':>7s} {'耗时':>8s}")
    lines.append(f"  {'-'*60}")
    for s in stages:
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
    lines.append(f"\n  全局峰值 (event): {peak['rss']:.0f} MB @ [{peak['pct']:.1f}%] {peak['stage']}")
    lines.append(f"  全局峰值 (1s采样): {result['peak_sample_rss']:.0f} MB @ {result['peak_sample_elapsed']:.0f}s")
    lines.append(f"  终态:     {final['rss']:.0f} MB @ [{final['pct']:.1f}%] {final['stage']}")
    lines.append(f"  总耗时:   {result['total_s']:.0f}s")
    lines.append(f"{'='*70}")

    if db_info:
        lines.append(f"\n  DB 表行数:")
        for k, v in sorted(db_info.items()):
            lines.append(f"    {k}: {v}")
        lines.append(f"{'='*70}\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="FNM Pipeline 内存分析")
    parser.add_argument("--slug", default="Heidegger_en_France")
    parser.add_argument("--detail", action="store_true", help="包含 DB 表大小分析")
    parser.add_argument("--runs", type=int, default=1, help="重复次数（取平均）")
    args = parser.parse_args()

    all_results = []
    for i in range(args.runs):
        if args.runs > 1:
            print(f"\nRun {i+1}/{args.runs}...", flush=True)
        result = run_test(args.slug, detail=args.detail)
        all_results.append(result)
        db_info = analyze_db(resolve_doc_id(args.slug)) if args.detail else None
        print(format_report(result, db_info))

    if args.runs > 1:
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

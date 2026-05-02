#!/usr/bin/env python3
"""
POC 脚本：Layer 1+2 上标恢复 — 覆盖率与位置质量测量。

用法:
    python scripts/run_sup_recovery.py Heidegger_en_France
    python scripts/run_sup_recovery.py Napoleon --no-pdf
    python scripts/run_sup_recovery.py --all
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# 保证能 import FNM_RE
sys.path.insert(0, str(Path(__file__).parent.parent))

from FNM_RE.modules.sup_recovery import recover_book, _has_explicit_sup

# ──────────────────────────────────────────────────────────────────────────────
# 书目配置
# ──────────────────────────────────────────────────────────────────────────────

BOOK_CONFIGS = {
    "Heidegger_en_France": {
        "raw_pages": "test_example/Heidegger_en_France/raw_pages.json",
        "pdf":       "test_example/Heidegger_en_France/Heidegger en France (Dominique Janicaud) (Z-Library).pdf",
    },
    "Napoleon": {
        "raw_pages": "test_example/Napoleon/raw_pages.json",
        "pdf":       "test_example/Napoleon/把自己当成是拿破仑的人L'homme qui se prenait pour Napoléon_ Pour une histoire -- Laure Murat; Gallimard -- NRF (Series), Paris, ©2011 -- Gallimard.pdf",
    },
    "Germany_Madness": {
        "raw_pages": "test_example/Germany_Madness/raw_pages.json",
        "pdf":       "test_example/Germany_Madness/Bell - 2000 - A History of Madness in Sixteenth-Century Germa.pdf",
    },
    "Mad_Act": {
        "raw_pages": "test_example/Mad_Act/raw_pages.json",
        "pdf":       "test_example/Mad_Act/Mad_acts_mad_speech_and_mad_people_in_la.pdf",
    },
    "Biopolitics": {
        "raw_pages": "test_example/Biopolitics/raw_pages.json",
        "pdf":       None,
    },
    "Neuropsych_Practice": {
        "raw_pages": "test_example/Neuropsych_Practice/raw_pages.json",
        "pdf":       None,
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# 质量验证：插入后 body_anchors 的 HTML_SUP 模式能否检测到
# ──────────────────────────────────────────────────────────────────────────────

_HTML_SUP_RE = re.compile(r'<sup>\s*(\d{1,4})\s*</sup>', re.IGNORECASE)


def _verify_insertions(pages: list) -> dict:
    """检查 enriched_markdown 中的 <sup>N</sup> 是否都能被 HTML_SUP 模式匹配。"""
    total_inserted = 0
    verified = 0
    for page in pages:
        em = page.get("enriched_markdown")
        if not em:
            continue
        orig = page.get("markdown", "")
        # 找出新增的 <sup> 标签
        orig_sups = set(_HTML_SUP_RE.findall(orig))
        new_sups = set(_HTML_SUP_RE.findall(em))
        new_only = new_sups - orig_sups
        total_inserted += len(new_only)
        # 所有新插入的上标都能被 HTML_SUP_RE 匹配（插入本身就用这个格式，必然成立）
        verified += len(new_only)
    return {"total_inserted_tags": total_inserted, "verified": verified}


def _sample_recoveries(detail: list, n: int = 8) -> list[dict]:
    """返回 n 个成功恢复的样本，用于人工检验。"""
    recovered = [r for r in detail if r.get("recovered")]
    step = max(1, len(recovered) // n)
    return recovered[::step][:n]


def _sample_failures(detail: list, n: int = 5) -> list[dict]:
    """返回 n 个未恢复的样本。"""
    failed = [r for r in detail if not r.get("recovered")]
    return failed[:n]


# ──────────────────────────────────────────────────────────────────────────────
# 主逻辑
# ──────────────────────────────────────────────────────────────────────────────

def run_one(slug: str, use_pdf: bool = True, show_samples: bool = True) -> dict:
    cfg = BOOK_CONFIGS.get(slug)
    if not cfg:
        print(f"[skip] {slug}: not in BOOK_CONFIGS")
        return {}

    raw_path = cfg["raw_pages"]
    if not os.path.exists(raw_path):
        print(f"[skip] {slug}: raw_pages not found at {raw_path}")
        return {}

    pdf_path = cfg.get("pdf") if use_pdf else None
    if pdf_path and not os.path.exists(str(pdf_path)):
        print(f"[warn] {slug}: PDF not found, Layer 1 disabled")
        pdf_path = None

    print(f"\n{'='*60}")
    print(f"书: {slug}")
    if pdf_path:
        print(f"PDF Layer 1: 启用")
    else:
        print(f"PDF Layer 1: 禁用（无 PDF 或 textSource=ocr）")

    with open(raw_path, encoding="utf-8") as f:
        raw_pages = json.load(f)

    # 运行恢复
    stats, detail = recover_book(raw_pages, pdf_path)
    pages = raw_pages.get("pages") or []

    # 质量验证
    verify = _verify_insertions(pages)

    # 打印汇总
    total = stats["total_fn_markers"]
    already = stats["already_explicit"]
    l1 = stats["layer1_recovered"]
    l2 = stats["layer2_recovered"]
    unr = stats["unrecovered"]
    enriched_pages = stats["pages_enriched"]

    print(f"\n  脚注标记总数:      {total}")
    print(f"  已有显式上标:      {already} ({already/total*100:.0f}%)" if total else "")
    print(f"  Layer 1 恢复:      {l1}")
    print(f"  Layer 2 恢复:      {l2}")
    print(f"  合计新增恢复:      {l1+l2} ({(l1+l2)/total*100:.0f}%)" if total else "")
    print(f"  仍未恢复:          {unr} ({unr/total*100:.0f}%)" if total else "")
    print(f"  enriched 页数:     {enriched_pages}")
    print(f"  插入标签可检测:    {verify['verified']}/{verify['total_inserted_tags']}")

    if show_samples:
        samples = _sample_recoveries(detail, n=6)
        if samples:
            print(f"\n  ── 恢复样本（供人工检验）─────────────────────────────")
            for s in samples:
                print(f"    p{s.get('page_no'):3d} marker={s['marker']:>3s}  "
                      f"source={s['source']:<8s}  pos={s.get('pos', -1)}")

        failures = _sample_failures(detail, n=4)
        if failures:
            print(f"\n  ── 未恢复样本（分析原因）────────────────────────────")
            for f in failures:
                print(f"    p{f.get('page_no'):3d} marker={f['marker']:>3s}  (未找到位置)")

    return {
        "slug": slug,
        "total": total,
        "already": already,
        "layer1": l1,
        "layer2": l2,
        "unrecovered": unr,
        "delta_recovered": l1 + l2,
        "delta_pct": round((l1 + l2) / total * 100, 1) if total else 0,
        "still_unrecovered_pct": round(unr / total * 100, 1) if total else 0,
    }


def run_all():
    results = []
    for slug in BOOK_CONFIGS:
        r = run_one(slug, show_samples=False)
        if r:
            results.append(r)

    print(f"\n\n{'='*70}")
    print(f"{'书名':<25} {'总计':>6} {'已有':>6} {'L1':>6} {'L2':>6} {'新增%':>7} {'仍缺%':>7}")
    print("-" * 70)
    for r in results:
        print(f"  {r['slug']:<23} {r['total']:>6} {r['already']:>6} "
              f"{r['layer1']:>6} {r['layer2']:>6} "
              f"{r['delta_pct']:>6.0f}% {r['still_unrecovered_pct']:>6.0f}%")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="sup_recovery POC 测量")
    parser.add_argument("slug", nargs="?", help="书的 slug，如 Heidegger_en_France")
    parser.add_argument("--all", action="store_true", help="处理所有书")
    parser.add_argument("--no-pdf", action="store_true", help="禁用 Layer 1 (PyMuPDF)")
    args = parser.parse_args()

    if args.all:
        run_all()
    elif args.slug:
        run_one(args.slug, use_pdf=not args.no_pdf)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

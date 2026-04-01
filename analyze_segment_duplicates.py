#!/usr/bin/env python3
"""定位阅读段落重复来源的小工具。

用途：
1) 在 SQLite 中按文档名关键字定位目标书；
2) 用给定文本片段检索命中段落；
3) 输出命中段落的页码、段落索引、相似度、跨页字段；
4) 给出“更像跨页误合并 / 源文本本身重复 / 尚不确定”的提示。
"""

from __future__ import annotations

import argparse
import difflib
import re
from collections import defaultdict

from sqlite_store import SQLiteRepository


def _normalize_text(text: str) -> str:
    raw = (text or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"\s+", " ", raw)
    # 保留中英文数字，去掉标点和控制符，便于跨格式匹配
    cleaned_chars = []
    for ch in raw:
        code = ord(ch)
        if ch.isalnum() or 0x4E00 <= code <= 0x9FFF:
            cleaned_chars.append(ch)
    return "".join(cleaned_chars)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    a_cut = a[:2000]
    b_cut = b[:6000]
    return difflib.SequenceMatcher(None, a_cut, b_cut).ratio()


def _collect_docs(repo: SQLiteRepository, keyword: str) -> list[dict]:
    docs = repo.list_documents() or []
    key = (keyword or "").strip().lower()
    if not key:
        return docs
    return [doc for doc in docs if key in str(doc.get("name", "")).lower()]


def _flatten_segments(repo: SQLiteRepository, doc_id: str) -> list[dict]:
    pages = repo.list_effective_translation_pages(doc_id) or []
    rows = []
    for page in pages:
        bp = int(page.get("_pageBP") or page.get("book_page") or 0)
        segments = page.get("_page_entries") or []
        for idx, seg in enumerate(segments):
            translation = str(seg.get("translation") or "").strip()
            if not translation:
                continue
            rows.append(
                {
                    "bp": bp,
                    "segment_index": idx,
                    "translation": translation,
                    "translation_norm": _normalize_text(translation),
                    "start_bp": seg.get("_startBP"),
                    "end_bp": seg.get("_endBP"),
                    "print_label": seg.get("_printPageLabel"),
                    "source": seg.get("_translation_source"),
                    "status": seg.get("_status"),
                }
            )
    return rows


def _detect_duplicate_signals(matches: list[dict]) -> dict:
    exact_groups: dict[str, list[dict]] = defaultdict(list)
    for m in matches:
        key = m["translation_norm"]
        if len(key) >= 80:
            exact_groups[key].append(m)

    repeated_exact = [grp for grp in exact_groups.values() if len(grp) >= 2]

    cross_page_hits = [
        m
        for m in matches
        if m.get("start_bp") is not None
        and m.get("end_bp") is not None
        and int(m["end_bp"]) > int(m["start_bp"])
    ]

    return {
        "repeated_exact_groups": repeated_exact,
        "cross_page_hits": cross_page_hits,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="定位某段文本在阅读数据中的重复来源。")
    parser.add_argument("--doc-keyword", default="last man", help="文档名关键字（默认: last man）")
    parser.add_argument("--query", default="", help="要检索的文本片段（可选）")
    parser.add_argument("--min-score", type=float, default=0.45, help="最小相似度阈值（默认: 0.45）")
    parser.add_argument("--top", type=int, default=20, help="最多输出条数（默认: 20）")
    parser.add_argument(
        "--scan-global-duplicates",
        action="store_true",
        help="扫描整本书中重复长段（不依赖 query）",
    )
    args = parser.parse_args()

    repo = SQLiteRepository()
    docs = _collect_docs(repo, args.doc_keyword)
    if not docs:
        print(f"未找到文档：keyword={args.doc_keyword!r}")
        return
    if len(docs) > 1:
        print("匹配到多个文档，请改用更具体关键词：")
        for d in docs:
            print(f"- {d.get('id')} | {d.get('name')}")
        return

    doc = docs[0]
    doc_id = str(doc.get("id"))
    print(f"文档: {doc.get('name')} (doc_id={doc_id})")

    rows = _flatten_segments(repo, doc_id)
    if not rows:
        print("该文档暂无可检索译文段落。")
        return

    if args.scan_global_duplicates:
        global_groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            norm = row["translation_norm"]
            if len(norm) >= 120:
                global_groups[norm].append(row)
        groups = [grp for grp in global_groups.values() if len(grp) >= 2]
        groups.sort(key=lambda grp: (-len(grp), min(item["bp"] for item in grp)))
        print(f"\n全局重复长段分组: {len(groups)}")
        for gi, grp in enumerate(groups[: args.top], 1):
            locs = ", ".join(f"bp{m['bp']}#seg{m['segment_index']}" for m in grp[:10])
            preview = grp[0]["translation"].replace("\n", " ").strip()
            if len(preview) > 100:
                preview = preview[:100] + "..."
            print(f"- 组{gi} ({len(grp)} 次): {locs}")
            print(f"  片段: {preview}")
        if not args.query:
            return

    query_norm = _normalize_text(args.query)
    if not query_norm:
        print("query 为空，已跳过定向检索。")
        return

    matches = []
    for row in rows:
        score = _similarity(query_norm, row["translation_norm"])
        if score >= args.min_score:
            item = dict(row)
            item["score"] = score
            matches.append(item)
    matches.sort(key=lambda x: (-x["score"], x["bp"], x["segment_index"]))

    if not matches:
        print(f"无命中（min_score={args.min_score}）。可尝试降低阈值。")
        return

    print(f"\n命中段落: {len(matches)}（展示前 {min(args.top, len(matches))} 条）")
    for i, m in enumerate(matches[: args.top], 1):
        preview = m["translation"].replace("\n", " ").strip()
        if len(preview) > 120:
            preview = preview[:120] + "..."
        print(
            f"[{i:02d}] score={m['score']:.3f} bp={m['bp']} seg={m['segment_index']} "
            f"range={m.get('start_bp')}-{m.get('end_bp')} "
            f"source={m.get('source')} status={m.get('status')} "
            f"print={m.get('print_label')!r}"
        )
        print(f"     {preview}")

    signals = _detect_duplicate_signals(matches)
    repeated_groups = signals["repeated_exact_groups"]
    cross_page_hits = signals["cross_page_hits"]

    print("\n诊断提示:")
    if repeated_groups and cross_page_hits:
        print("- 命中中同时存在“完全相同长段多次出现”与“跨页段落”。")
        print("- 更可能是：跨页合并 + 下一页未被正确去重，或原文重复与跨页叠加。")
    elif repeated_groups:
        print("- 命中中存在完全相同长段的多次出现。")
        print("- 更像源文本或解析后内容重复，不像重译覆盖造成。")
    elif cross_page_hits:
        print("- 命中主要是跨页段落（end_bp > start_bp）。")
        print("- 更像跨页合并链路导致的视觉重复。")
    else:
        print("- 未观察到显著跨页/完全重复信号，需结合页级 markdown 再查。")

    if repeated_groups:
        print("\n完全相同长段分组（前 3 组）:")
        for gi, grp in enumerate(repeated_groups[:3], 1):
            locs = ", ".join(f"bp{m['bp']}#seg{m['segment_index']}" for m in grp[:8])
            print(f"- 组{gi}: {len(grp)} 次 -> {locs}")


if __name__ == "__main__":
    main()


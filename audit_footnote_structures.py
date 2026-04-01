#!/usr/bin/env python3
"""审计脚注/尾注结构，用于导出规则设计。"""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict

from sqlite_store import SQLiteRepository


SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
SUP_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")

RE_LATEX = re.compile(r"\$\s*\^\{(\d+)\}\s*\$")
RE_CARET = re.compile(r"\^\{(\d+)\}")
RE_BRACKET = re.compile(r"\[(\d{1,4})\]")
RE_SUP = re.compile(rf"[{SUPERSCRIPT_DIGITS}]{{1,5}}")
RE_FN_SPLIT = re.compile(r"^\s*(\d{1,4})\s*[\.\)、\]]\s*", re.M)
RE_FN_BRACKET_HEAD = re.compile(r"^\s*\[(\d{1,4})\]\s*", re.M)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _pick_docs(repo: SQLiteRepository, doc_ids: list[str], doc_keywords: list[str]) -> list[dict]:
    all_docs = repo.list_documents() or []
    by_id = {str(d.get("id")): d for d in all_docs}
    selected = []
    for doc_id in doc_ids:
        if doc_id in by_id:
            selected.append(by_id[doc_id])
    for kw in doc_keywords:
        low = kw.lower()
        for doc in all_docs:
            if low in str(doc.get("name", "")).lower() and doc not in selected:
                selected.append(doc)
                break
    return selected


def _classify_marker(text: str) -> list[str]:
    marks = []
    if RE_LATEX.search(text):
        marks.append("latex_$^{n}$")
    if RE_CARET.search(text):
        marks.append("caret_^{n}")
    if RE_SUP.search(text):
        marks.append("unicode_superscript")
    if RE_BRACKET.search(text):
        marks.append("bracket_[n]")
    return marks


def _extract_fn_item_labels(text: str) -> tuple[str, list[str]]:
    raw = (text or "").strip()
    if not raw:
        return "empty", []
    labels = []
    for m in RE_FN_SPLIT.finditer(raw):
        labels.append(m.group(1))
    if labels:
        return "numbered_lines", labels
    labels = []
    for m in RE_FN_BRACKET_HEAD.finditer(raw):
        labels.append(m.group(1))
    if labels:
        return "bracketed_lines", labels
    return "freeform", []


def main() -> None:
    parser = argparse.ArgumentParser(description="审计翻译段落中的脚注/尾注形态")
    parser.add_argument("--doc-id", action="append", default=[], help="指定文档 ID，可多次传入")
    parser.add_argument(
        "--doc-keyword",
        action="append",
        default=["last man", "foucault", "biopolitique"],
        help="按文档名关键字匹配，可多次传入",
    )
    parser.add_argument("--sample", type=int, default=8, help="每种形态最多展示示例数")
    args = parser.parse_args()

    repo = SQLiteRepository()
    docs = _pick_docs(repo, args.doc_id, args.doc_keyword)
    if not docs:
        print("未找到文档。")
        return

    for doc in docs:
        doc_id = str(doc.get("id"))
        print("=" * 90)
        print(f"文档: {doc.get('name')} (doc_id={doc_id})")
        pages = repo.list_effective_translation_pages(doc_id) or []
        segments = []
        for p in pages:
            bp = int(p.get("_pageBP") or p.get("book_page") or 0)
            for idx, seg in enumerate(p.get("_page_entries") or []):
                segments.append(
                    {
                        "bp": bp,
                        "seg_idx": idx,
                        "orig": _normalize(seg.get("original", "")),
                        "tr": _normalize(seg.get("translation", "")),
                        "fn": _normalize(seg.get("footnotes", "")),
                        "fn_tr": _normalize(seg.get("footnotes_translation", "")),
                    }
                )

        marker_counter = Counter()
        marker_examples = defaultdict(list)
        fn_shape_counter = Counter()
        fn_example = defaultdict(list)
        paired_label_stats = Counter()

        for seg in segments:
            joined = f"{seg['orig']}\n{seg['tr']}"
            marks = _classify_marker(joined)
            for mk in marks:
                marker_counter[mk] += 1
                if len(marker_examples[mk]) < args.sample:
                    marker_examples[mk].append(
                        f"bp={seg['bp']} seg={seg['seg_idx']} | {seg['tr'][:180]}"
                    )

            if seg["fn"] or seg["fn_tr"]:
                shape_fn, labels_fn = _extract_fn_item_labels(seg["fn"])
                shape_tr, labels_tr = _extract_fn_item_labels(seg["fn_tr"])
                fn_shape_counter[f"footnotes:{shape_fn}"] += 1
                fn_shape_counter[f"footnotes_translation:{shape_tr}"] += 1
                if len(fn_example[f"footnotes:{shape_fn}"]) < args.sample:
                    fn_example[f"footnotes:{shape_fn}"].append(
                        f"bp={seg['bp']} seg={seg['seg_idx']} | {seg['fn'][:180]}"
                    )
                if len(fn_example[f"footnotes_translation:{shape_tr}"]) < args.sample:
                    fn_example[f"footnotes_translation:{shape_tr}"].append(
                        f"bp={seg['bp']} seg={seg['seg_idx']} | {seg['fn_tr'][:180]}"
                    )
                if labels_fn and labels_tr:
                    paired_label_stats["label_count_equal" if len(labels_fn) == len(labels_tr) else "label_count_mismatch"] += 1
                elif labels_fn and not labels_tr:
                    paired_label_stats["only_fn_has_labels"] += 1
                elif labels_tr and not labels_fn:
                    paired_label_stats["only_fn_tr_has_labels"] += 1
                else:
                    paired_label_stats["both_no_labels"] += 1

        print(f"总页数: {len(pages)} | 总段落: {len(segments)}")
        print("\n正文脚注引用形态计数:")
        if marker_counter:
            for name, cnt in marker_counter.most_common():
                print(f"- {name}: {cnt}")
        else:
            print("- 无明显脚注引用形态")

        print("\n脚注文本结构计数:")
        if fn_shape_counter:
            for name, cnt in fn_shape_counter.most_common():
                print(f"- {name}: {cnt}")
        else:
            print("- 无脚注文本")

        if paired_label_stats:
            print("\nfootnotes 与 footnotes_translation 对齐统计:")
            for name, cnt in paired_label_stats.items():
                print(f"- {name}: {cnt}")

        print("\n示例（正文脚注引用）:")
        for name, rows in marker_examples.items():
            print(f"* {name}")
            for row in rows:
                print(f"  - {row}")

        print("\n示例（脚注文本结构）:")
        for name, rows in fn_example.items():
            print(f"* {name}")
            for row in rows:
                print(f"  - {row}")


if __name__ == "__main__":
    main()


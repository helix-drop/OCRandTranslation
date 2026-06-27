#!/usr/bin/env python3
"""金版段对段对比模块。

在现有整章相似度基础上，增加段落粒度的逐段 diff。
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


# ── 段落切分 ──────────────────────────────────────────────

def _split_paragraphs(text: str) -> list[str]:
    """按空行切分段落，每段去掉首尾空白后保留。"""
    blocks = re.split(r"\n\s*\n", text)
    return [block.strip() for block in blocks if block.strip()]


# ── 规范化 ───────────────────────────────────────────────

def _normalize_text_for_paragraph(text: str) -> str:
    """与 compare_golden 中 normalize_body_for_similarity 保持一致。"""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[\^\d+\]", " ", text)
    text = re.sub(r"\{\{NOTE_REF:[^}]+\}\}", " ", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    trans_map = {
        "'": "'", "'": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "‐": "-", "‑": "-",
    }
    text = text.translate(str.maketrans(trans_map))
    text = re.sub(r"[^\w\s#'-]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().casefold()


# ── 段对齐 ───────────────────────────────────────────────

def _align_paragraphs(
    golden_paragraphs: list[str],
    export_paragraphs: list[str],
    min_similarity: float = 0.6,
) -> tuple[list[dict[str, Any]], list[int]]:
    """将导出段落对齐到金版段落。

    Returns:
        aligned: 每个金版段落的对齐结果
        unmatched_export_indices: 未能匹配金版的导出段落索引
    """
    g_norm = [_normalize_text_for_paragraph(p) for p in golden_paragraphs]
    e_norm = [_normalize_text_for_paragraph(p) for p in export_paragraphs]

    aligned: list[dict[str, Any]] = []
    used_export: set[int] = set()

    for g_idx, g_norm_text in enumerate(g_norm):
        best_score = 0.0
        best_e_idx = -1
        for e_idx, e_norm_text in enumerate(e_norm):
            if e_idx in used_export:
                continue
            score = SequenceMatcher(None, g_norm_text, e_norm_text).ratio()
            if score > best_score:
                best_score = score
                best_e_idx = e_idx

        if best_score >= min_similarity and best_e_idx >= 0:
            used_export.add(best_e_idx)
            aligned.append({
                "golden_idx": g_idx,
                "export_idx": best_e_idx,
                "golden_text": golden_paragraphs[g_idx],
                "export_text": export_paragraphs[best_e_idx],
                "similarity": round(best_score, 4),
                "status": "matched",
            })
        else:
            aligned.append({
                "golden_idx": g_idx,
                "export_idx": -1,
                "golden_text": golden_paragraphs[g_idx],
                "export_text": "",
                "similarity": 0.0,
                "status": "missing",
            })

    unmatched_export = [i for i in range(len(export_paragraphs)) if i not in used_export]
    return aligned, unmatched_export


# ── 章段对比 ─────────────────────────────────────────────

def compare_chapter_paragraphs(
    export_text: str,
    golden_text: str,
    *,
    min_para_similarity: float = 0.6,
    low_similarity_threshold: float = 0.85,
) -> dict[str, Any]:
    """逐段对比一章的导出和金版文本。

    Returns 包含段落级差异详情和汇总统计。
    """
    # 先分离 body 和 notes
    exp_body, exp_notes = _split_body_and_notes(export_text)
    gld_body, gld_notes = _split_body_and_notes(golden_text)

    # 段落切分
    g_paras = _split_paragraphs(gld_body)
    e_paras = _split_paragraphs(exp_body)

    # 段对齐
    aligned, unmatched_e = _align_paragraphs(g_paras, e_paras)

    # 统计
    matched = [a for a in aligned if a["status"] == "matched"]
    missing = [a for a in aligned if a["status"] == "missing"]
    low_sim = [a for a in matched if a["similarity"] < low_similarity_threshold]
    added = [{"export_idx": i, "export_text": e_paras[i]} for i in unmatched_e]

    return {
        "golden_paragraph_count": len(g_paras),
        "export_paragraph_count": len(e_paras),
        "matched_count": len(matched),
        "missing_count": len(missing),
        "added_count": len(added),
        "low_similarity_count": len(low_sim),
        "paragraph_similarity_avg": (
            round(sum(a["similarity"] for a in matched) / len(matched), 4)
            if matched else 0.0
        ),
        "missing_paragraphs": [
            {"golden_idx": a["golden_idx"], "golden_text": a["golden_text"][:200]}
            for a in missing[:20]
        ],
        "added_paragraphs": [
            {"export_idx": a["export_idx"], "export_text": a["export_text"][:200]}
            for a in added[:20]
        ],
        "low_similarity_paragraphs": [
            {
                "golden_idx": a["golden_idx"],
                "export_idx": a["export_idx"],
                "similarity": a["similarity"],
                "golden_text": a["golden_text"][:200],
                "export_text": a["export_text"][:200],
            }
            for a in low_sim[:20]
        ],
        "details": aligned,
        "added_details": added,
    }


def _split_body_and_notes(text: str) -> tuple[str, str]:
    """在 ## NOTES 标题处分割正文和尾注区域。"""
    match = re.search(r"^#{2,6}\s+NOTES\s*$", text, re.MULTILINE)
    if not match:
        return text, ""
    return text[:match.start()], text[match.start():]


def format_paragraph_diff_report(chapter_name: str, diff: dict[str, Any]) -> str:
    """将逐段对比结果格式化为可读的报告。"""
    lines = [
        f"## {chapter_name} 段对段对比",
        "",
        f"- 金版段落数: {diff['golden_paragraph_count']}",
        f"- 导出段落数: {diff['export_paragraph_count']}",
        f"- 匹配: {diff['matched_count']}, 缺失: {diff['missing_count']}, 新增: {diff['added_count']}",
        f"- 低相似度段 (<{0.85}): {diff['low_similarity_count']}",
        f"- 平均段落相似度: {diff['paragraph_similarity_avg']:.1%}",
        "",
    ]

    if diff["missing_paragraphs"]:
        lines.append("### 缺失段落 (金版有，导出无)")
        lines.append("")
        for item in diff["missing_paragraphs"]:
            text = item["golden_text"].replace("\n", " ")
            lines.append(f"- **[金版#{item['golden_idx']}]** {text}")
        lines.append("")

    if diff["added_paragraphs"]:
        lines.append("### 新增段落 (导出有，金版无)")
        lines.append("")
        for item in diff["added_paragraphs"]:
            text = item["export_text"].replace("\n", " ")
            lines.append(f"- **[导出#{item['export_idx']}]** {text}")
        lines.append("")

    if diff["low_similarity_paragraphs"]:
        lines.append("### 低相似度段落")
        lines.append("")
        for item in diff["low_similarity_paragraphs"]:
            lines.append(f"- **G#{item['golden_idx']} ↔ E#{item['export_idx']}** sim={item['similarity']:.1%}")
            g_text = item["golden_text"].replace("\n", " ")
            e_text = item["export_text"].replace("\n", " ")
            lines.append(f"  - 金版: {g_text}")
            lines.append(f"  - 导出: {e_text}")
        lines.append("")

    return "\n".join(lines)

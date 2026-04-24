"""FNM_RE 3c 阶段：Chapter anchor alignment（DP 序列对齐）。

对每章，将正文中的 body anchor 标记序列与尾注条目标记序列做
Needleman-Wunsch 全局序列对齐，判断匹配程度：

- clean:     两条序列完全一致
- mismatches: 长度相同但部分标记不匹配
- misaligned: 长度不同，存在缺失 / 多余的标记

输出 ChapterAnchorAlignmentRecord 列表 + 摘要统计。
"""

from __future__ import annotations

from typing import Any

from FNM_RE.models import BodyAnchorRecord, ChapterAnchorAlignmentRecord, ChapterEndnoteRecord


def _body_markers_by_chapter(
    body_anchors: list[BodyAnchorRecord],
) -> dict[str, list[str]]:
    """按 chapter_id 分组提取 body anchor 的 normalized_marker 列。

    body_anchors 本身按 page_no → paragraph_index → char_start 有序。
    """
    result: dict[str, list[str]] = {}
    for anchor in body_anchors:
        result.setdefault(anchor.chapter_id, []).append(anchor.normalized_marker)
    return result


def _endnote_markers_by_chapter(
    paragraph_endnotes: list[ChapterEndnoteRecord],
) -> dict[str, list[str]]:
    """按 chapter_id 分组提取 endnote 条的 marker 列。

    endnote 条目在构建时已按 ordinal 排序。
    """
    result: dict[str, list[str]] = {}
    for en in paragraph_endnotes:
        result.setdefault(en.chapter_id, []).append(en.marker)
    return result


def _needleman_wunsch_align(
    seq_a: list[str],
    seq_b: list[str],
    *,
    match_score: int = 1,
    mismatch_penalty: int = -1,
    gap_penalty: int = -1,
) -> tuple[int, list[str], list[str]]:
    """Needleman-Wunsch 全局序列对齐。

    Returns:
        (score, aligned_a, aligned_b) — aligned sequences 用 None 表示 gap。
    """
    m, n = len(seq_a), len(seq_b)

    # DP 矩阵
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        dp[i][0] = dp[i - 1][0] + gap_penalty
    for j in range(1, n + 1):
        dp[0][j] = dp[0][j - 1] + gap_penalty

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            score = match_score if seq_a[i - 1] == seq_b[j - 1] else mismatch_penalty
            match = dp[i - 1][j - 1] + score
            delete = dp[i - 1][j] + gap_penalty
            insert = dp[i][j - 1] + gap_penalty
            dp[i][j] = max(match, delete, insert)

    # Traceback
    aligned_a: list[str] = []
    aligned_b: list[str] = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            score = match_score if seq_a[i - 1] == seq_b[j - 1] else mismatch_penalty
            if dp[i][j] == dp[i - 1][j - 1] + score:
                aligned_a.append(seq_a[i - 1])
                aligned_b.append(seq_b[j - 1])
                i -= 1
                j -= 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + gap_penalty:
            aligned_a.append(seq_a[i - 1])
            aligned_b.append(None)  # type: ignore[arg-type]
            i -= 1
        else:
            aligned_a.append(None)  # type: ignore[arg-type]
            aligned_b.append(seq_b[j - 1])
            j -= 1

    aligned_a.reverse()
    aligned_b.reverse()
    return dp[m][n], aligned_a, aligned_b


def _per_chapter_alignment(
    body_markers: list[str],
    endnote_markers: list[str],
) -> tuple[str, dict | None]:
    """对单个章节运行序列对齐。

    Returns:
        (alignment_status, mismatch_dict_or_None)
    """
    if body_markers == endnote_markers:
        return "clean", None

    score, _aligned_a, _aligned_b = _needleman_wunsch_align(
        body_markers, endnote_markers,
    )

    if len(body_markers) == len(endnote_markers):
        # 等长但不完全一致
        mismatched: list[list[str]] = [
            [body_markers[i], endnote_markers[i]]
            for i in range(len(body_markers))
            if body_markers[i] != endnote_markers[i]
        ]
        return "mismatches", {
            "type": "mismatched_pairs",
            "details": mismatched,
            "dp_score": score,
        }

    # 不等长 → misaligned：从对齐结果提取插入/删除
    body_extra: list[str] = []
    endnote_extra: list[str] = []
    for a, b in zip(_aligned_a, _aligned_b):
        if a is not None and b is None:
            body_extra.append(a)
        elif a is None and b is not None:
            endnote_extra.append(b)

    return "misaligned", {
        "body_count": len(body_markers),
        "endnote_count": len(endnote_markers),
        "dp_score": score,
        "body_extra_markers": body_extra,
        "endnote_extra_markers": endnote_extra,
    }


def build_chapter_anchor_alignment(
    body_anchors: list[BodyAnchorRecord],
    paragraph_endnotes: list[ChapterEndnoteRecord],
    *,
    doc_id: str = "",
) -> tuple[list[ChapterAnchorAlignmentRecord], dict]:
    """构建 chapter anchor alignment 记录。

    Args:
        body_anchors: body anchor 记录（含 normalized_marker, chapter_id）
        paragraph_endnotes: 段落级尾注条目（含 marker, chapter_id）
        doc_id: 文档 ID

    Returns:
        (ChapterAnchorAlignmentRecord 列表, 统计摘要 dict)
    """
    body_by_chapter = _body_markers_by_chapter(body_anchors)
    endnote_by_chapter = _endnote_markers_by_chapter(paragraph_endnotes)

    all_chapter_ids = sorted(set(body_by_chapter) | set(endnote_by_chapter))
    records: list[ChapterAnchorAlignmentRecord] = []
    chapter_status_map: dict[str, dict] = {}

    for cid in all_chapter_ids:
        bm = body_by_chapter.get(cid, [])
        em = endnote_by_chapter.get(cid, [])

        alignment_status, mismatch = _per_chapter_alignment(bm, em)

        records.append(ChapterAnchorAlignmentRecord(
            doc_id=doc_id,
            chapter_id=cid,
            alignment_status=alignment_status,
            body_anchor_count=len(bm),
            endnote_count=len(em),
            mismatch=mismatch,
        ))

        chapter_status_map[cid] = {
            "alignment_status": alignment_status,
            "body_anchor_count": len(bm),
            "endnote_count": len(em),
        }

    # 摘要统计
    total = len(records)
    clean = sum(1 for r in records if r.alignment_status == "clean")
    mismatches_count = sum(1 for r in records if r.alignment_status == "mismatches")
    misaligned_count = sum(1 for r in records if r.alignment_status == "misaligned")
    total_body = sum(r.body_anchor_count for r in records)
    total_endnote = sum(r.endnote_count for r in records)

    summary: dict[str, Any] = {
        "total_chapters": total,
        "clean": clean,
        "mismatches": mismatches_count,
        "misaligned": misaligned_count,
        "total_body_anchors": total_body,
        "total_endnote_items": total_endnote,
        "chapter_status": chapter_status_map,
    }
    return records, summary

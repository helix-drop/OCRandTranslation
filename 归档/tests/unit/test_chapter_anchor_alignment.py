"""Chapter anchor alignment (DP 序列对齐) 单元测试。"""

from __future__ import annotations

import unittest

from FNM_RE.models import BodyAnchorRecord, ChapterAnchorAlignmentRecord, ChapterEndnoteRecord
from FNM_RE.stages.chapter_anchor_alignment import build_chapter_anchor_alignment


def _body_anchor(
    chapter_id: str,
    normalized_marker: str,
    *,
    page_no: int = 1,
    paragraph_index: int = 0,
) -> BodyAnchorRecord:
    return BodyAnchorRecord(
        anchor_id=f"{chapter_id}-{normalized_marker}",
        chapter_id=chapter_id,
        page_no=page_no,
        paragraph_index=paragraph_index,
        char_start=0,
        char_end=1,
        source_marker=normalized_marker,
        normalized_marker=normalized_marker,
        anchor_kind="footnote",
        certainty=1.0,
        source_text=f"text_{normalized_marker}",
        source="test",
        synthetic=False,
        ocr_repaired_from_marker="",
    )


def _endnote(
    chapter_id: str,
    marker: str,
    *,
    ordinal: int = 1,
) -> ChapterEndnoteRecord:
    return ChapterEndnoteRecord(
        doc_id="",
        chapter_id=chapter_id,
        ordinal=ordinal,
        marker=marker,
        text=f"Note {marker} text",
    )


class ChapterAnchorAlignmentTest(unittest.TestCase):
    """build_chapter_anchor_alignment 单元测试。"""

    # ── clean ──────────────────────────────────────────────

    def test_clean_identical_sequences(self):
        """body anchor 与 endnote 标记完全一致 → clean."""
        body = [_body_anchor("ch-1", "1"), _body_anchor("ch-1", "2"), _body_anchor("ch-1", "3")]
        endnotes = [_endnote("ch-1", "1", ordinal=1), _endnote("ch-1", "2", ordinal=2), _endnote("ch-1", "3", ordinal=3)]

        records, summary = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].alignment_status, "clean")
        self.assertIsNone(records[0].mismatch)
        self.assertEqual(records[0].body_anchor_count, 3)
        self.assertEqual(records[0].endnote_count, 3)
        self.assertEqual(summary["clean"], 1)
        self.assertEqual(summary["misaligned"], 0)
        self.assertEqual(summary["mismatches"], 0)

    def test_clean_single_item(self):
        """单条 body anchor 和单条 endnote 一致 → clean."""
        body = [_body_anchor("ch-1", "1")]
        endnotes = [_endnote("ch-1", "1")]

        records, _ = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(records[0].alignment_status, "clean")

    def test_clean_both_empty_chapter(self):
        """有章节但 body 和 endnote 都为空 → clean."""
        body: list[BodyAnchorRecord] = []
        endnotes: list[ChapterEndnoteRecord] = []

        records, summary = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(len(records), 0)
        self.assertEqual(summary["total_chapters"], 0)

    def test_clean_chapter_with_empty_both(self):
        """某章节 body 和 endnote 均为空列表 → clean."""
        # 没有引用该章节的 body 或 endnote → 该章节不会出现在结果中
        body = [_body_anchor("ch-1", "1")]
        endnotes = [_endnote("ch-1", "1")]

        records, _ = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].alignment_status, "clean")

    # ── mismatches ──────────────────────────────────────────

    def test_mismatches_same_length_different_markers(self):
        """等长但标记不一致 → mismatches."""
        body = [_body_anchor("ch-1", "1"), _body_anchor("ch-1", "2"), _body_anchor("ch-1", "3")]
        endnotes = [_endnote("ch-1", "1", ordinal=1), _endnote("ch-1", "2", ordinal=2), _endnote("ch-1", "X", ordinal=3)]

        records, summary = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].alignment_status, "mismatches")
        self.assertIsNotNone(records[0].mismatch)
        self.assertEqual(records[0].mismatch["type"], "mismatched_pairs")
        self.assertEqual(records[0].body_anchor_count, 3)
        self.assertEqual(records[0].endnote_count, 3)
        self.assertEqual(summary["mismatches"], 1)
        self.assertEqual(summary["clean"], 0)

    def test_mismatches_multiple_differences(self):
        """多处不一致的等长序列."""
        body = [_body_anchor("ch-1", "1"), _body_anchor("ch-1", "2"), _body_anchor("ch-1", "3")]
        endnotes = [_endnote("ch-1", "X", ordinal=1), _endnote("ch-1", "2", ordinal=2), _endnote("ch-1", "Y", ordinal=3)]

        records, _ = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(records[0].alignment_status, "mismatches")
        self.assertEqual(len(records[0].mismatch["details"]), 2)

    # ── misaligned ──────────────────────────────────────────

    def test_misaligned_body_extra(self):
        """body anchor 比 endnote 多 → misaligned body_extra."""
        body = [_body_anchor("ch-1", "1"), _body_anchor("ch-1", "2"), _body_anchor("ch-1", "3")]
        endnotes = [_endnote("ch-1", "1", ordinal=1), _endnote("ch-1", "2", ordinal=2)]

        records, summary = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].alignment_status, "misaligned")
        self.assertIn("body_extra_markers", records[0].mismatch)
        self.assertEqual(records[0].body_anchor_count, 3)
        self.assertEqual(records[0].endnote_count, 2)
        self.assertEqual(summary["misaligned"], 1)

    def test_misaligned_endnote_extra(self):
        """endnote 比 body anchor 多 → misaligned endnote_extra."""
        body = [_body_anchor("ch-1", "1"), _body_anchor("ch-1", "2")]
        endnotes = [_endnote("ch-1", "1", ordinal=1), _endnote("ch-1", "2", ordinal=2), _endnote("ch-1", "3", ordinal=3)]

        records, _ = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(records[0].alignment_status, "misaligned")
        self.assertIn("endnote_extra_markers", records[0].mismatch)

    def test_misaligned_missing_middle_marker(self):
        """中间缺失某标记 → body_extra/misaligned."""
        body = [_body_anchor("ch-1", "1"), _body_anchor("ch-1", "3")]
        endnotes = [_endnote("ch-1", "1", ordinal=1), _endnote("ch-1", "2", ordinal=2), _endnote("ch-1", "3", ordinal=3)]

        records, _ = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(records[0].alignment_status, "misaligned")

    def test_misaligned_body_only(self):
        """有 body anchor 但没有 endnote → misaligned."""
        body = [_body_anchor("ch-1", "1"), _body_anchor("ch-1", "2")]
        endnotes: list[ChapterEndnoteRecord] = []

        records, summary = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].alignment_status, "misaligned")
        self.assertEqual(records[0].body_anchor_count, 2)
        self.assertEqual(records[0].endnote_count, 0)

    def test_misaligned_endnote_only(self):
        """有 endnote 但没有 body anchor → misaligned."""
        body: list[BodyAnchorRecord] = []
        endnotes = [_endnote("ch-1", "1"), _endnote("ch-1", "2")]

        records, _ = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].alignment_status, "misaligned")
        self.assertEqual(records[0].body_anchor_count, 0)
        self.assertEqual(records[0].endnote_count, 2)

    # ── multi-chapter ───────────────────────────────────────

    def test_multi_chapter_mixed_statuses(self):
        """多章节混合状态."""
        body = [
            _body_anchor("ch-1", "1"),
            _body_anchor("ch-1", "2"),
            _body_anchor("ch-2", "1"),
            _body_anchor("ch-3", "1"),
        ]
        endnotes = [
            _endnote("ch-1", "1", ordinal=1),
            _endnote("ch-1", "2", ordinal=2),
            _endnote("ch-2", "X", ordinal=1),
            _endnote("ch-3", "1", ordinal=1),
            _endnote("ch-3", "2", ordinal=2),
        ]

        records, summary = build_chapter_anchor_alignment(body, endnotes)

        status_map = {r.chapter_id: r.alignment_status for r in records}
        self.assertEqual(records[0].chapter_id, "ch-1")
        self.assertEqual(status_map["ch-1"], "clean")
        self.assertEqual(status_map["ch-2"], "mismatches")
        self.assertEqual(status_map["ch-3"], "misaligned")
        self.assertEqual(summary["clean"], 1)
        self.assertEqual(summary["mismatches"], 1)
        self.assertEqual(summary["misaligned"], 1)

    def test_chapter_only_in_body(self):
        """章节仅出现在 body 而不在 endnote 中 → 仍会出现在结果中."""
        body = [_body_anchor("ch-1", "1")]
        endnotes = [_endnote("ch-2", "1")]

        records, summary = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(len(records), 2)
        ch1 = [r for r in records if r.chapter_id == "ch-1"][0]
        ch2 = [r for r in records if r.chapter_id == "ch-2"][0]
        self.assertEqual(ch1.alignment_status, "misaligned")
        self.assertEqual(ch1.body_anchor_count, 1)
        self.assertEqual(ch1.endnote_count, 0)
        self.assertEqual(ch2.alignment_status, "misaligned")
        self.assertEqual(ch2.body_anchor_count, 0)
        self.assertEqual(ch2.endnote_count, 1)

    # ── summary ─────────────────────────────────────────────

    def test_summary_counts(self):
        """摘要统计应准确反映各状态的数量."""
        body = [
            _body_anchor("ch-clean", "1"),
            _body_anchor("ch-mismatch", "1"),
            _body_anchor("ch-misalign", "1"),
        ]
        endnotes = [
            _endnote("ch-clean", "1"),
            _endnote("ch-mismatch", "X"),
            _endnote("ch-misalign", "1"),
            _endnote("ch-misalign", "2"),
        ]

        records, summary = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(summary["total_chapters"], 3)
        self.assertEqual(summary["clean"], 1)
        self.assertEqual(summary["mismatches"], 1)
        self.assertEqual(summary["misaligned"], 1)
        self.assertEqual(summary["total_body_anchors"], 3)
        self.assertEqual(summary["total_endnote_items"], 4)
        self.assertEqual(len(summary["chapter_status"]), 3)

    def test_empty_inputs(self):
        """两侧均为空列表时无记录."""
        records, summary = build_chapter_anchor_alignment([], [])

        self.assertEqual(len(records), 0)
        self.assertEqual(summary["total_chapters"], 0)

    def test_large_body_anchor_delta(self):
        """大量 body anchor 与少量 endnote → misaligned."""
        body = [_body_anchor("ch-1", str(i)) for i in range(1, 21)]
        endnotes = [_endnote("ch-1", str(i), ordinal=i) for i in range(1, 4)]

        records, _ = build_chapter_anchor_alignment(body, endnotes)

        self.assertEqual(records[0].alignment_status, "misaligned")
        self.assertEqual(records[0].body_anchor_count, 20)
        self.assertEqual(records[0].endnote_count, 3)

    def test_dp_score_in_mismatch(self):
        """mismatch 和 misaligned 记录包含 dp_score."""
        body = [_body_anchor("ch-1", "1"), _body_anchor("ch-1", "2")]
        endnotes = [_endnote("ch-1", "X", ordinal=1), _endnote("ch-1", "Y", ordinal=2)]

        records, _ = build_chapter_anchor_alignment(body, endnotes)

        self.assertIn("dp_score", records[0].mismatch)


if __name__ == "__main__":
    unittest.main()

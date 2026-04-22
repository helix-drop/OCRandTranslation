"""Goldstein regression: synthesize_anchor override 写入时若 cluster 的
chapter_id 为空（孤儿 link 落在前置页/未归章的区域），必须能用 page_no
回填到 chapters 中距离最近的 chapter_id，否则下游
`_materialize_anchor_overrides` 会以 invalid_coords 拒掉，llm-synth 锚点
永远无法落到 fnm_body_anchors。
"""

from __future__ import annotations

import unittest

from FNM_RE.llm_repair import _resolve_chapter_id_for_page


class ResolveChapterIdForPageTest(unittest.TestCase):
    def _chapters(self):
        return [
            {"chapter_id": "ch-intro", "start_page": 18, "end_page": 37},
            {"chapter_id": "ch-1", "start_page": 38, "end_page": 76},
            {"chapter_id": "ch-epilogue", "start_page": 333, "end_page": 347},
        ]

    def test_page_inside_chapter_returns_that_id(self):
        self.assertEqual(
            _resolve_chapter_id_for_page(self._chapters(), 50),
            "ch-1",
        )

    def test_page_before_first_chapter_returns_nearest(self):
        # Goldstein 实际场景：page_no=10 在 Introduction 之前
        self.assertEqual(
            _resolve_chapter_id_for_page(self._chapters(), 10),
            "ch-intro",
        )

    def test_page_after_last_chapter_returns_nearest(self):
        self.assertEqual(
            _resolve_chapter_id_for_page(self._chapters(), 400),
            "ch-epilogue",
        )

    def test_page_in_gap_returns_closer_side(self):
        chapters = [
            {"chapter_id": "a", "start_page": 10, "end_page": 20},
            {"chapter_id": "b", "start_page": 40, "end_page": 50},
        ]
        self.assertEqual(_resolve_chapter_id_for_page(chapters, 25), "a")
        self.assertEqual(_resolve_chapter_id_for_page(chapters, 35), "b")

    def test_empty_chapters_returns_empty(self):
        self.assertEqual(_resolve_chapter_id_for_page([], 10), "")

    def test_invalid_page_returns_empty(self):
        self.assertEqual(_resolve_chapter_id_for_page(self._chapters(), 0), "")
        self.assertEqual(_resolve_chapter_id_for_page(self._chapters(), -3), "")

    def test_chapter_with_missing_range_is_skipped(self):
        chapters = [
            {"chapter_id": "bad", "start_page": 0, "end_page": 0},
            {"chapter_id": "ok", "start_page": 100, "end_page": 120},
        ]
        self.assertEqual(_resolve_chapter_id_for_page(chapters, 50), "ok")


if __name__ == "__main__":
    unittest.main()

"""Goldstein regression: synthesize_anchor override 写入时若 cluster 的
chapter_id 为空（孤儿 link 落在前置页/未归章的区域），必须能用 page_no
回填到 chapters 中距离最近的 chapter_id，否则下游
`_materialize_anchor_overrides` 会以 invalid_coords 拒掉，llm-synth 锚点
永远无法落到 fnm_body_anchors。
"""

from __future__ import annotations

import unittest

from FNM_RE.modules.llm_repair import (
    _build_chapter_body_text,
    _enrich_synthesize_anchor_actions,
    _resolve_chapter_id_for_page,
    select_auto_applicable_actions,
)


class _BodyTextRepo:
    def load_pages(self, _doc_id):
        return [
            {"bookPage": 10, "markdown": "body page marker 40"},
            {"bookPage": 11, "markdown": "note definition should stay out"},
        ]

    def list_fnm_pages(self, _doc_id):
        return [
            {"page_no": 10, "page_role": "body"},
            {"page_no": 11, "page_role": "note"},
        ]


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


class BuildChapterBodyTextTest(unittest.TestCase):
    def test_note_pages_are_not_used_as_chapter_body(self):
        text, spans = _build_chapter_body_text(
            "doc-1",
            {"chapter_id": "ch-1", "start_page": 10, "end_page": 11},
            repo=_BodyTextRepo(),
        )

        self.assertIn("body page marker 40", text)
        self.assertNotIn("note definition should stay out", text)
        self.assertEqual(spans, [(10, 0, len("body page marker 40"))])


class EnrichSynthesizeAnchorActionsTest(unittest.TestCase):
    def test_global_chapter_offset_is_converted_to_page_local_offset(self):
        first_page = "first page without target"
        second_page = "second page has anchor phrase here"
        body_text = f"{first_page}\n\n{second_page}"
        spans = [
            (10, 0, len(first_page)),
            (11, len(first_page) + 2, len(body_text)),
        ]

        enriched = _enrich_synthesize_anchor_actions(
            [
                {
                    "action": "synthesize_anchor",
                    "note_item_id": "en-1",
                    "anchor_phrase": "anchor phrase",
                    "confidence": 0.95,
                }
            ],
            cluster={"chapter_body_text": body_text},
            spans=spans,
        )

        expected_start = second_page.index("anchor phrase")
        expected_end = expected_start + len("anchor phrase")
        self.assertEqual(enriched[0]["page_no"], 11)
        self.assertEqual(enriched[0]["char_start"], expected_start)
        self.assertEqual(enriched[0]["char_end"], expected_end)
        self.assertEqual(enriched[0]["matched_text"], "anchor phrase")


class SynthesizeAnchorAutoApplyGateTest(unittest.TestCase):
    def test_footnote_synthesize_anchor_must_stay_in_note_page_window(self):
        selected = select_auto_applicable_actions(
            [
                {
                    "action": "synthesize_anchor",
                    "note_item_id": "fn-00008",
                    "anchor_phrase": "l'homme d'État anglais Walpole",
                    "page_no": 17,
                    "confidence": 0.95,
                    "fuzzy_score": 100,
                    "ambiguous": False,
                }
            ],
            chapter_unmatched_count=1,
            note_system="footnote",
            note_page_by_id={"fn-00008": 37},
        )

        self.assertEqual(selected, [])

    def test_endnote_synthesize_anchor_must_stay_in_candidate_body_pages(self):
        selected = select_auto_applicable_actions(
            [
                {
                    "action": "synthesize_anchor",
                    "note_item_id": "en-00216",
                    "anchor_phrase": "Autant les ordolibéraux cherchent",
                    "page_no": 174,
                    "confidence": 0.95,
                    "fuzzy_score": 100,
                    "ambiguous": False,
                }
            ],
            chapter_unmatched_count=1,
            note_system="endnote",
            allowed_synthesize_pages={158, 159},
        )

        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()

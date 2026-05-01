"""Tier 1 fuzzy anchor synthesis for FNM unresolved endnote clusters.

Covers the new `synthesize_anchor` LLM action, the rapidfuzz-based
`locate_anchor_phrase_in_body` locator, and the extended gating rules in
`select_auto_applicable_actions` (confidence + fuzzy_score + chapter-count
floor).
"""

from __future__ import annotations

import unittest

from FNM_RE.llm_repair import (
    FUZZY_SCORE_THRESHOLD,
    MIN_CHAPTER_UNMATCHED_FOR_AUTO,
    _cluster_focus_pages,
    _trim_page_text,
    locate_anchor_phrase_in_body,
    parse_llm_repair_actions,
    select_auto_applicable_actions,
)


class ParseSynthesizeAnchorTest(unittest.TestCase):
    def test_synthesize_anchor_action_accepted(self):
        raw = (
            '[{"action":"synthesize_anchor","note_item_id":"n-1",'
            '"anchor_phrase":"the last words of the body",'
            '"confidence":0.92,"reason":"clear context"}]'
        )
        actions = parse_llm_repair_actions(raw)
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["action"], "synthesize_anchor")
        self.assertEqual(action["note_item_id"], "n-1")
        self.assertEqual(action["anchor_phrase"], "the last words of the body")
        self.assertAlmostEqual(action["confidence"], 0.92)

    def test_synthesize_anchor_without_phrase_is_dropped(self):
        raw = '[{"action":"synthesize_anchor","note_item_id":"n-1","confidence":0.9}]'
        actions = parse_llm_repair_actions(raw)
        self.assertEqual(actions, [])

    def test_match_action_still_has_no_phrase_field(self):
        raw = (
            '[{"action":"match","note_item_id":"n-1","anchor_id":"a-1",'
            '"confidence":0.95,"reason":""}]'
        )
        actions = parse_llm_repair_actions(raw)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "match")
        self.assertEqual(actions[0].get("anchor_phrase", ""), "")

    def test_synthesize_note_item_action_accepted(self):
        raw = (
            '[{"action":"synthesize_note_item","anchor_id":"a-1","marker":"1",'
            '"note_text":"Visible note text.","confidence":0.96,"reason":"clear"}]'
        )
        actions = parse_llm_repair_actions(raw)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "synthesize_note_item")
        self.assertEqual(actions[0]["marker"], "1")
        self.assertEqual(actions[0]["note_text"], "Visible note text.")

    def test_synthesize_note_item_without_text_is_dropped(self):
        raw = '[{"action":"synthesize_note_item","anchor_id":"a-1","marker":"1","confidence":0.96}]'
        actions = parse_llm_repair_actions(raw)
        self.assertEqual(actions, [])


class LocateAnchorPhraseInBodyTest(unittest.TestCase):
    def test_exact_match_returns_position(self):
        body = "Chapter text with a unique landmark phrase here. Another paragraph follows."
        result = locate_anchor_phrase_in_body(body, "unique landmark phrase")
        self.assertTrue(result["hit"])
        self.assertGreaterEqual(result["score"], 95.0)
        self.assertEqual(
            body[result["char_start"]:result["char_end"]],
            "unique landmark phrase",
        )
        self.assertFalse(result["ambiguous"])

    def test_ocr_noisy_match_still_hits(self):
        # Real OCR noise: one char deleted and one substituted
        body = "Chapter text with a uniqe landmark phrese here. End."
        result = locate_anchor_phrase_in_body(body, "unique landmark phrase")
        self.assertTrue(result["hit"])
        self.assertGreaterEqual(result["score"], FUZZY_SCORE_THRESHOLD)

    def test_below_threshold_no_hit(self):
        body = "Completely different chapter content. Nothing remotely related here."
        result = locate_anchor_phrase_in_body(body, "unique landmark phrase")
        self.assertFalse(result["hit"])

    def test_repeated_phrase_is_flagged_ambiguous(self):
        body = (
            "First paragraph with landmark phrase one. "
            "Second paragraph with landmark phrase two. "
            "Third paragraph with landmark phrase three."
        )
        result = locate_anchor_phrase_in_body(body, "landmark phrase")
        self.assertTrue(result["hit"])
        self.assertTrue(result["ambiguous"])

    def test_empty_inputs_are_safe(self):
        self.assertFalse(locate_anchor_phrase_in_body("", "foo")["hit"])
        self.assertFalse(locate_anchor_phrase_in_body("some body", "")["hit"])


class SelectAutoApplicableSynthesizeTest(unittest.TestCase):
    def _action(self, **overrides):
        base = {
            "action": "synthesize_anchor",
            "note_item_id": "n-1",
            "anchor_id": "",
            "anchor_phrase": "some unique landmark phrase",
            "confidence": 0.95,
            "fuzzy_score": 92.0,
            "ambiguous": False,
            "reason": "",
        }
        base.update(overrides)
        return base

    def test_auto_applies_when_all_thresholds_met(self):
        actions = [self._action()]
        selected = select_auto_applicable_actions(
            actions,
            confidence_threshold=0.9,
            chapter_unmatched_count=MIN_CHAPTER_UNMATCHED_FOR_AUTO,
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["action"], "synthesize_anchor")

    def test_low_confidence_rejected(self):
        actions = [self._action(confidence=0.85)]
        selected = select_auto_applicable_actions(
            actions,
            confidence_threshold=0.9,
            chapter_unmatched_count=5,
        )
        self.assertEqual(selected, [])

    def test_low_fuzzy_score_rejected(self):
        actions = [self._action(fuzzy_score=70.0)]
        selected = select_auto_applicable_actions(
            actions,
            confidence_threshold=0.9,
            chapter_unmatched_count=5,
        )
        self.assertEqual(selected, [])

    def test_singleton_cluster_now_allowed(self):
        # cluster 通常按 chapter×region 切分，单条孤儿 note 是常态；
        # 只要 fuzzy、confidence、非歧义三道闸通过，就允许 synth 自动应用。
        actions = [self._action()]
        selected = select_auto_applicable_actions(
            actions,
            confidence_threshold=0.9,
            chapter_unmatched_count=1,
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["action"], "synthesize_anchor")

    def test_empty_cluster_rejected(self):
        # chapter_unmatched_count=0 视为非法语义，仍拒绝。
        actions = [self._action()]
        selected = select_auto_applicable_actions(
            actions,
            confidence_threshold=0.9,
            chapter_unmatched_count=0,
        )
        self.assertEqual(selected, [])

    def test_ambiguous_flag_rejected(self):
        actions = [self._action(ambiguous=True)]
        selected = select_auto_applicable_actions(
            actions,
            confidence_threshold=0.9,
            chapter_unmatched_count=5,
        )
        self.assertEqual(selected, [])

    def test_match_action_unaffected_by_new_gates(self):
        match_action = {
            "action": "match",
            "note_item_id": "n-1",
            "anchor_id": "a-1",
            "anchor_phrase": "",
            "confidence": 0.95,
            "reason": "",
        }
        selected = select_auto_applicable_actions(
            [match_action],
            confidence_threshold=0.9,
            chapter_unmatched_count=1,
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["action"], "match")

    def test_synthesize_note_item_uses_confidence_gate_only(self):
        action = {
            "action": "synthesize_note_item",
            "anchor_id": "a-1",
            "marker": "1",
            "note_text": "Visible note text.",
            "confidence": 0.95,
            "reason": "",
        }
        selected = select_auto_applicable_actions(
            [action],
            confidence_threshold=0.9,
            chapter_unmatched_count=1,
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["action"], "synthesize_note_item")

    def test_one_note_item_consumed_at_most_once(self):
        same_note = [
            self._action(anchor_phrase="phrase A"),
            self._action(anchor_phrase="phrase B"),
        ]
        selected = select_auto_applicable_actions(
            same_note,
            confidence_threshold=0.9,
            chapter_unmatched_count=5,
        )
        self.assertEqual(len(selected), 1)


class ClusterFocusPagesTest(unittest.TestCase):
    def test_focus_pages_returns_up_to_configured_cap(self):
        cluster = {
            "unmatched_note_items": [{"page_no": p} for p in (10, 20, 30, 40)],
            "unmatched_anchors": [{"page_no": p} for p in (50, 60, 70, 80)],
        }
        pages = _cluster_focus_pages(cluster)
        self.assertEqual(pages, [10, 20, 30, 40, 50, 60, 70, 80])
        self.assertLessEqual(len(pages), 8)

    def test_focus_pages_deduplicates(self):
        cluster = {
            "unmatched_note_items": [{"page_no": 15}, {"page_no": 15}, {"page_no": 25}],
            "unmatched_anchors": [{"page_no": 25}],
        }
        self.assertEqual(_cluster_focus_pages(cluster), [15, 25])


class TrimPageTextTest(unittest.TestCase):
    def test_default_limit_raised_to_1400(self):
        text = "a" * 1400
        self.assertEqual(_trim_page_text(text), text)

    def test_over_limit_is_truncated_with_marker(self):
        text = "a" * 2000
        out = _trim_page_text(text)
        self.assertTrue(out.endswith("..."))
        self.assertLessEqual(len(out), 1500)


if __name__ == "__main__":
    unittest.main()

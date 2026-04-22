"""Tier 1 扩展：footnote cluster 也进 LLM 修补。

覆盖：
  1. build_unresolved_clusters 不再硬过滤 footnote。
  2. _slice_cluster_for_request 对 footnote + 章节正文 → note_only_with_body。
  3. synthesize_anchor 自动应用时 anchor_kind 从 cluster.note_system 派生，
     footnote cluster 产出的 anchor payload 必须是 footnote（否则 note_linking
     的一致性校验会判 mismatch 而拒绝）。
"""

from __future__ import annotations

import unittest

from FNM_RE.llm_repair import (
    _slice_cluster_for_request,
    build_unresolved_clusters,
)


class BuildClusterIncludesFootnoteTest(unittest.TestCase):
    def _minimal_inputs(self, note_kind: str):
        chapters = [{"chapter_id": "ch-1", "title": "Chapter 1"}]
        note_items = [
            {
                "note_item_id": "n-1",
                "chapter_id": "ch-1",
                "region_id": "r-1",
                "marker": "1",
                "normalized_marker": "1",
                "page_no": 5,
                "source_text": "definition of note 1",
            }
        ]
        body_anchors: list[dict] = []
        note_links = [
            {
                "link_id": "L-1",
                "chapter_id": "ch-1",
                "region_id": "r-1",
                "note_kind": note_kind,
                "status": "orphan_note",
                "note_item_id": "n-1",
                "anchor_id": "",
                "marker": "1",
            }
        ]
        return chapters, note_items, body_anchors, note_links

    def test_endnote_cluster_still_built(self):
        c, n, b, l = self._minimal_inputs("endnote")
        clusters = build_unresolved_clusters(
            chapters=c, note_items=n, body_anchors=b, note_links=l
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["note_system"], "endnote")

    def test_footnote_cluster_now_built(self):
        c, n, b, l = self._minimal_inputs("footnote")
        clusters = build_unresolved_clusters(
            chapters=c, note_items=n, body_anchors=b, note_links=l
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["note_system"], "footnote")
        self.assertEqual(len(clusters[0]["unmatched_note_items"]), 1)

    def test_unknown_note_system_still_filtered(self):
        c, n, b, l = self._minimal_inputs("sidenote")
        clusters = build_unresolved_clusters(
            chapters=c, note_items=n, body_anchors=b, note_links=l
        )
        self.assertEqual(clusters, [])


class FootnoteNoteOnlyWithBodyTest(unittest.TestCase):
    def test_footnote_cluster_routes_to_synthesize(self):
        cluster = {
            "cluster_id": "ch-1:r-1:footnote",
            "chapter_id": "ch-1",
            "chapter_title": "Chapter 1",
            "region_id": "r-1",
            "note_system": "footnote",
            "matched_examples": [],
            "unmatched_note_items": [
                {"note_item_id": "n-1", "marker": "1"},
                {"note_item_id": "n-2", "marker": "2"},
                {"note_item_id": "n-3", "marker": "3"},
            ],
            "unmatched_anchors": [],
            "chapter_body_text": "body with some unique landmark phrase here.",
        }
        sliced = _slice_cluster_for_request(cluster)
        self.assertEqual(sliced["request_mode"], "note_only_with_body")
        self.assertIn("synthesize_anchor", sliced["allowed_actions"])

    def test_orphan_anchor_with_rebind_candidates_routes_to_match(self):
        chapters = [{"chapter_id": "ch-1", "title": "Chapter 1"}]
        note_items = [
            {
                "note_item_id": "n-65",
                "chapter_id": "ch-1",
                "region_id": "r-1",
                "marker": "65",
                "normalized_marker": "65",
                "page_no": 10,
                "source_text": "definition of note 65",
            }
        ]
        body_anchors = [
            {
                "anchor_id": "a-orphan",
                "chapter_id": "ch-1",
                "page_no": 10,
                "normalized_marker": "4",
                "source_marker": "4",
                "source_text": "broken superscript in body",
                "synthetic": False,
            },
            {
                "anchor_id": "synthetic-footnote-1",
                "chapter_id": "ch-1",
                "page_no": 10,
                "normalized_marker": "65",
                "source_marker": "65",
                "source_text": "synthetic fallback anchor",
            },
        ]
        note_links = [
            {
                "link_id": "L-orphan",
                "chapter_id": "ch-1",
                "region_id": "",
                "note_kind": "footnote",
                "status": "orphan_anchor",
                "note_item_id": "",
                "anchor_id": "a-orphan",
                "marker": "4",
            },
            {
                "link_id": "L-match",
                "chapter_id": "ch-1",
                "region_id": "r-1",
                "note_kind": "footnote",
                "status": "matched",
                "note_item_id": "n-65",
                "anchor_id": "synthetic-footnote-1",
                "marker": "65",
            },
        ]
        clusters = build_unresolved_clusters(
            chapters=chapters,
            note_items=note_items,
            body_anchors=body_anchors,
            note_links=note_links,
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]["rebind_candidates"]), 1)
        self.assertTrue(clusters[0]["rebind_candidates"][0]["current_anchor_synthetic"])

        sliced = _slice_cluster_for_request(clusters[0])
        self.assertEqual(sliced["request_mode"], "anchor_rebind")
        self.assertIn("match", sliced["allowed_actions"])

    def test_ref_only_visual_can_synthesize_note_item(self):
        cluster = {
            "cluster_id": "ch-1:r-1:endnote",
            "chapter_id": "ch-1",
            "chapter_title": "Chapter 1",
            "region_id": "r-1",
            "note_system": "endnote",
            "matched_examples": [],
            "unmatched_note_items": [],
            "unmatched_anchors": [
                {"anchor_id": "a-1", "marker": "1", "page_no": 10},
            ],
            "page_contexts": [{"page_no": 10, "ocr_excerpt": "page excerpt"}],
        }
        sliced = _slice_cluster_for_request(cluster)
        self.assertEqual(sliced["request_mode"], "ref_only_visual")
        self.assertIn("synthesize_note_item", sliced["allowed_actions"])


class SynthesizeAutoApplyPayloadShapeTest(unittest.TestCase):
    """Regression: synthesize_anchor 的 anchor_kind 必须来自 cluster.note_system。

    如果回退为硬编码 endnote，footnote 合成的 anchor 会被 note_linking 的
    _infer_note_kind_from_anchor 判为 endnote → 和 footnote note_item 不一致 →
    invalid_link_override，导致整条链路失败。这里只检查字符串常量本身以
    防止回退。
    """

    def test_auto_apply_references_cluster_note_system(self):
        import pathlib

        source = pathlib.Path("FNM_RE/llm_repair.py").read_text(encoding="utf-8")
        self.assertIn('"anchor_kind": note_system', source)
        self.assertNotIn('"anchor_kind": "endnote",', source)


if __name__ == "__main__":
    unittest.main()

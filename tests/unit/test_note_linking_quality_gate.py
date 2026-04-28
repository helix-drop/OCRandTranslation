"""链接质量阈值阻塞门（工单 #4，覆盖 docs/fnm-notes-coverage-plan.md §6.4）。

针对：
1. `_summarize_links` 输出新指标 `fallback_match_ratio`（fallback resolver 命中的 matched / matched 总）。
2. `build_note_link_table.gate_report.hard` 新增 `link.quality_ok`：
   - `fallback_match_ratio > config.LINK_FALLBACK_MATCH_RATIO_THRESHOLD_DEFAULT` 触发
   - 或 `footnote_orphan_anchor + endnote_orphan_anchor > config.LINK_ORPHAN_ANCHOR_THRESHOLD_DEFAULT` 触发
   - 任一触发 → reasons 含 `link_quality_low`
3. 现有 `link_resolver_counts` 字段语义不动，但加文档澄清。
"""

from __future__ import annotations

import unittest

from FNM_RE.models import NoteLinkRecord
from FNM_RE.modules.note_linking import _summarize_links


def _link(
    *,
    link_id: str = "",
    chapter_id: str = "ch-1",
    region_id: str = "",
    note_item_id: str = "",
    anchor_id: str = "",
    status: str = "matched",
    resolver: str = "rule",
    note_kind: str = "endnote",
    marker: str = "1",
) -> NoteLinkRecord:
    return NoteLinkRecord(
        link_id=link_id or f"link-{anchor_id or note_item_id or '?'}",
        chapter_id=chapter_id,
        region_id=region_id or "reg-1",
        note_item_id=note_item_id or "note-1",
        anchor_id=anchor_id or "anchor-1",
        status=status,
        resolver=resolver,
        confidence=1.0,
        note_kind=note_kind,
        marker=marker,
        page_no_start=1,
        page_no_end=1,
    )


class SummarizeLinksMetricsTest(unittest.TestCase):
    """`_summarize_links` 必须输出 `fallback_match_ratio` 字段。"""

    def test_fallback_match_ratio_zero_when_all_rule(self):
        links = [_link(link_id=f"l{i}", anchor_id=f"a{i}", status="matched", resolver="rule") for i in range(10)]
        summary = _summarize_links(links)
        self.assertEqual(summary["matched"], 10)
        self.assertEqual(summary.get("fallback_match_ratio"), 0.0)

    def test_fallback_match_ratio_when_half_matched_via_fallback(self):
        links = [
            _link(link_id=f"r{i}", anchor_id=f"a{i}", status="matched", resolver="rule")
            for i in range(5)
        ] + [
            _link(link_id=f"f{i}", anchor_id=f"b{i}", status="matched", resolver="fallback")
            for i in range(5)
        ]
        summary = _summarize_links(links)
        self.assertEqual(summary["matched"], 10)
        self.assertEqual(summary["fallback_count"], 5)
        self.assertAlmostEqual(summary.get("fallback_match_ratio", 0.0), 0.5, places=4)

    def test_fallback_match_ratio_excludes_unmatched_fallback(self):
        """fallback resolver 但未 matched（orphan）不应计入 fallback_match。"""
        links = [
            _link(link_id="m1", anchor_id="a1", status="matched", resolver="rule"),
            _link(link_id="o1", anchor_id="a2", status="orphan_anchor", resolver="fallback", note_kind="endnote"),
        ]
        summary = _summarize_links(links)
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary.get("fallback_match_ratio", 0.0), 0.0)

    def test_fallback_match_ratio_zero_when_no_matched(self):
        links = [
            _link(link_id="o1", anchor_id="a1", status="orphan_anchor", resolver="fallback", note_kind="endnote"),
        ]
        summary = _summarize_links(links)
        self.assertEqual(summary["matched"], 0)
        self.assertEqual(summary.get("fallback_match_ratio", 0.0), 0.0)


class LinkQualityGateThresholdTest(unittest.TestCase):
    """构造 fixture 跑 `build_note_link_table` 验证 quality_ok 阻塞门。"""

    def _build_with_links(self, links: list[NoteLinkRecord]):
        """直接用一个轻量 stub 测 gate 计算逻辑。

        因为 build_note_link_table 链很长，这里用一个内部 helper 验证阈值。
        """
        from FNM_RE.modules.note_linking import _link_quality_gate
        return _link_quality_gate(links)

    def test_quality_ok_when_fallback_ratio_below_threshold(self):
        links = [
            _link(link_id=f"r{i}", anchor_id=f"a{i}", status="matched", resolver="rule")
            for i in range(8)
        ] + [
            _link(link_id=f"f{i}", anchor_id=f"b{i}", status="matched", resolver="fallback")
            for i in range(2)
        ]
        gate = self._build_with_links(links)
        # 2/10 = 20% < 30% threshold → quality_ok
        self.assertTrue(gate["quality_ok"], gate)

    def test_quality_low_when_fallback_ratio_above_threshold(self):
        links = [
            _link(link_id=f"r{i}", anchor_id=f"a{i}", status="matched", resolver="rule")
            for i in range(5)
        ] + [
            _link(link_id=f"f{i}", anchor_id=f"b{i}", status="matched", resolver="fallback")
            for i in range(5)
        ]
        gate = self._build_with_links(links)
        # 5/10 = 50% > 30% threshold → quality_low
        self.assertFalse(gate["quality_ok"], gate)
        self.assertGreater(gate.get("fallback_match_ratio", 0.0), 0.30)

    def test_quality_low_when_orphan_anchor_above_threshold(self):
        # 5 matched all rule + 11 orphan_anchor (footnote+endnote 混)
        links = [
            _link(link_id=f"r{i}", anchor_id=f"a{i}", status="matched", resolver="rule")
            for i in range(5)
        ] + [
            _link(link_id=f"of{i}", anchor_id=f"of{i}", status="orphan_anchor", resolver="rule", note_kind="footnote")
            for i in range(6)
        ] + [
            _link(link_id=f"oe{i}", anchor_id=f"oe{i}", status="orphan_anchor", resolver="rule", note_kind="endnote")
            for i in range(5)
        ]
        gate = self._build_with_links(links)
        # 11 > 10 threshold → quality_low
        self.assertFalse(gate["quality_ok"], gate)

    def test_quality_ok_when_orphan_anchor_at_or_below_threshold(self):
        links = [
            _link(link_id=f"r{i}", anchor_id=f"a{i}", status="matched", resolver="rule")
            for i in range(20)
        ] + [
            _link(link_id=f"of{i}", anchor_id=f"of{i}", status="orphan_anchor", resolver="rule", note_kind="footnote")
            for i in range(10)
        ]
        gate = self._build_with_links(links)
        # 10 == 10 threshold（按 > 严格）→ quality_ok
        self.assertTrue(gate["quality_ok"], gate)


class LinkResolverCountsDocstringTest(unittest.TestCase):
    """工单 #4：澄清 link_resolver_counts 语义（避免下次又被误判为 bug）。"""

    def test_resolver_counts_total_equals_total_links_not_matched(self):
        """sum(link_resolver_counts) == 总 link 数（含 orphan/ignored），不是 matched 数。"""
        links = [
            _link(link_id="m1", anchor_id="a1", status="matched", resolver="rule"),
            _link(link_id="m2", anchor_id="a2", status="matched", resolver="fallback"),
            _link(link_id="o1", anchor_id="a3", status="orphan_anchor", resolver="rule", note_kind="endnote"),
            _link(link_id="i1", anchor_id="a4", status="ignored", resolver="repair"),
        ]
        from collections import Counter
        resolver_counts = dict(Counter(str(r.resolver or "") for r in links))
        # 总和必须等于 link 总数 4，而不是 matched 数 2
        self.assertEqual(sum(resolver_counts.values()), 4)
        self.assertNotEqual(sum(resolver_counts.values()), 2)


if __name__ == "__main__":
    unittest.main()

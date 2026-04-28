"""契约 v2：章级"对地"校验（工单 #3，覆盖 docs/fnm-notes-coverage-plan.md §6.3）。

针对两条契约链路：
1. `note_linking._chapter_contracts` → 输出 ChapterLinkContract 的新字段
   `has_marker_gap` / `def_anchor_mismatch` 以及不再被 `requires_endnote_contract` 短路的 `first_marker_is_one`
2. `scripts.test_fnm_batch._analyze_export_text` → 输出 `local_numbering_no_gap`

这层契约的目的：把"绿灯但缺一半"的根因（章 1/7/9/11 first_local_def_marker 不是 "1"
但模块仍报 contract_ok）翻成红灯。
"""

from __future__ import annotations

import unittest

from FNM_RE.models import BodyAnchorRecord, NoteLinkRecord
from FNM_RE.modules.note_linking import _chapter_contracts
from FNM_RE.modules.types import (
    BodyPageLayer,
    ChapterLayer,
    ChapterLayers,
    LayerNoteItem,
    LayerNoteRegion,
)


def _layer_item(
    chapter_id: str,
    region_id: str,
    note_item_id: str,
    marker: str,
    *,
    page_no: int = 100,
    note_kind: str = "endnote",
) -> LayerNoteItem:
    return LayerNoteItem(
        note_item_id=note_item_id,
        region_id=region_id,
        chapter_id=chapter_id,
        owner_chapter_id=chapter_id,
        page_no=page_no,
        marker=marker,
        source_marker=marker,
        normalized_marker=marker,
        synth_marker="",
        projection_mode="native",
        marker_type="numeric",
        text=f"Note {marker} text.",
        source="test",
        is_reconstructed=False,
        review_required=False,
        note_kind=note_kind,
    )


def _layer_region(
    region_id: str,
    chapter_id: str,
    *,
    note_kind: str = "chapter_endnotes",
    page_start: int = 100,
    page_end: int = 102,
) -> LayerNoteRegion:
    return LayerNoteRegion(
        region_id=region_id,
        chapter_id=chapter_id,
        owner_chapter_id=chapter_id,
        page_start=page_start,
        page_end=page_end,
        pages=list(range(page_start, page_end + 1)),
        note_kind=note_kind,
        scope="chapter",
        source_scope="chapter",
        source="rule",
        bind_method="rule",
        bind_confidence=1.0,
        heading_text="### NOTES",
        review_required=False,
    )


def _matched_link(
    chapter_id: str,
    note_item_id: str,
    anchor_id: str,
    marker: str,
    *,
    page_no: int = 50,
) -> NoteLinkRecord:
    return NoteLinkRecord(
        link_id=f"link-{note_item_id}",
        chapter_id=chapter_id,
        region_id=f"reg-{chapter_id}",
        note_item_id=note_item_id,
        anchor_id=anchor_id,
        status="matched",
        resolver="rule",
        confidence=1.0,
        note_kind="endnote",
        marker=marker,
        page_no_start=page_no,
        page_no_end=page_no,
    )


def _body_anchor(
    chapter_id: str,
    anchor_id: str,
    marker: str,
    *,
    page_no: int = 50,
    paragraph_index: int = 0,
    char_start: int = 0,
) -> BodyAnchorRecord:
    return BodyAnchorRecord(
        anchor_id=anchor_id,
        chapter_id=chapter_id,
        page_no=page_no,
        paragraph_index=paragraph_index,
        char_start=char_start,
        char_end=char_start + 3,
        source_marker=marker,
        normalized_marker=marker,
        anchor_kind="endnote",
        certainty=1.0,
        source_text="...",
        source="test",
        synthetic=False,
        ocr_repaired_from_marker="",
    )


def _chapter_layers_with_endnotes(
    *,
    chapter_id: str = "ch-1",
    markers: list[str],
    note_mode: str = "chapter_endnote_primary",
    book_type: str = "endnote_only",
    chapter_marker_counts: dict[str, int] | None = None,
) -> ChapterLayers:
    region = _layer_region(f"reg-{chapter_id}", chapter_id)
    items = [
        _layer_item(chapter_id, region.region_id, f"en-{marker}", marker, page_no=100 + idx)
        for idx, marker in enumerate(markers)
    ]
    chapter = ChapterLayer(
        chapter_id=chapter_id,
        title="Test Chapter",
        body_pages=[BodyPageLayer(page_no=50, text="Body.", split_reason="body_page", source_role="body")],
        endnote_items=list(items),
        endnote_regions=[region],
        policy_applied={"note_mode": note_mode, "book_type": book_type},
    )
    return ChapterLayers(
        chapters=[chapter],
        regions=[region],
        note_items=list(items),
        region_summary={},
        item_summary={},
        chapter_marker_counts=dict(chapter_marker_counts or {}),
    )


class ChapterContractV2Test(unittest.TestCase):
    """三类对地校验：first_marker_is_one / has_marker_gap / def_anchor_mismatch。"""

    # ── A. first_marker_is_one：不再被 requires_endnote_contract 短路 ──

    def test_first_marker_not_one_triggers_violation_even_when_mode_is_chapter_endnote(self):
        """章只有 [3,4,5] → first_marker_is_one == False（之前会被短路成 True）。"""
        layers = _chapter_layers_with_endnotes(markers=["3", "4", "5"])
        anchors = [
            _body_anchor("ch-1", "a-3", "3", page_no=50),
            _body_anchor("ch-1", "a-4", "4", page_no=51),
            _body_anchor("ch-1", "a-5", "5", page_no=52),
        ]
        links = [
            _matched_link("ch-1", "en-3", "a-3", "3", page_no=50),
            _matched_link("ch-1", "en-4", "a-4", "4", page_no=51),
            _matched_link("ch-1", "en-5", "a-5", "5", page_no=52),
        ]
        contracts, _ = _chapter_contracts(
            chapter_layers=layers,
            effective_links=links,
            body_anchors=anchors,
        )
        self.assertEqual(len(contracts), 1)
        self.assertFalse(contracts[0].first_marker_is_one,
                         f"first_marker_is_one 应为 False，markers=[3,4,5]; got {contracts[0]}")

    def test_first_marker_not_one_also_triggers_for_footnote_primary(self):
        """工单 #3 关键：mode=footnote_primary 且 endnote_items 为空，但 chapter_marker_counts > 0
        时应能通过 def_anchor_mismatch 暴露问题（first_marker_is_one 默认 True 因为没 def）。"""
        layers = _chapter_layers_with_endnotes(
            markers=[],
            note_mode="footnote_primary",
            book_type="footnote_only",
            chapter_marker_counts={"ch-1": 18},
        )
        contracts, _ = _chapter_contracts(
            chapter_layers=layers,
            effective_links=[],
            body_anchors=[],
        )
        self.assertEqual(len(contracts), 1)
        # 章正文有 18 个 anchor 但 def 0 → 必须 mismatch
        self.assertTrue(contracts[0].def_anchor_mismatch,
                        f"def_anchor_mismatch 应为 True，def_count=0 vs anchor_total=18; got {contracts[0]}")

    # ── B. marker_gap：编号断号 ──

    def test_marker_gap_triggers_when_def_markers_have_hole(self):
        """章有 [1,2,4]（缺 3）→ has_marker_gap == True。"""
        layers = _chapter_layers_with_endnotes(markers=["1", "2", "4"])
        anchors = [
            _body_anchor("ch-1", "a-1", "1", page_no=50),
            _body_anchor("ch-1", "a-2", "2", page_no=51),
            _body_anchor("ch-1", "a-4", "4", page_no=53),
        ]
        links = [
            _matched_link("ch-1", "en-1", "a-1", "1", page_no=50),
            _matched_link("ch-1", "en-2", "a-2", "2", page_no=51),
            _matched_link("ch-1", "en-4", "a-4", "4", page_no=53),
        ]
        contracts, _ = _chapter_contracts(
            chapter_layers=layers,
            effective_links=links,
            body_anchors=anchors,
        )
        self.assertEqual(len(contracts), 1)
        self.assertTrue(contracts[0].has_marker_gap,
                        f"has_marker_gap 应为 True，markers=[1,2,4] 缺 3; got {contracts[0]}")

    def test_marker_no_gap_when_def_markers_contiguous_from_one(self):
        """章有 [1,2,3,4] 完整连续 → has_marker_gap == False。"""
        layers = _chapter_layers_with_endnotes(markers=["1", "2", "3", "4"])
        anchors = [
            _body_anchor("ch-1", f"a-{m}", m, page_no=50 + idx)
            for idx, m in enumerate(["1", "2", "3", "4"])
        ]
        links = [
            _matched_link("ch-1", f"en-{m}", f"a-{m}", m, page_no=50 + idx)
            for idx, m in enumerate(["1", "2", "3", "4"])
        ]
        contracts, _ = _chapter_contracts(
            chapter_layers=layers,
            effective_links=links,
            body_anchors=anchors,
        )
        self.assertEqual(len(contracts), 1)
        self.assertFalse(contracts[0].has_marker_gap)
        self.assertTrue(contracts[0].first_marker_is_one)

    # ── C. def_anchor_mismatch：def 数与 anchor 全形态扫描数差距 ──

    def test_def_anchor_mismatch_when_def_count_below_anchor_total(self):
        """章 def 5 个但 anchor 全形态扫描出 18 → def_anchor_mismatch == True。"""
        layers = _chapter_layers_with_endnotes(
            markers=["1", "2", "3", "4", "5"],
            chapter_marker_counts={"ch-1": 18},
        )
        anchors = [
            _body_anchor("ch-1", f"a-{m}", m, page_no=50 + idx)
            for idx, m in enumerate(["1", "2", "3", "4", "5"])
        ]
        links = [
            _matched_link("ch-1", f"en-{m}", f"a-{m}", m, page_no=50 + idx)
            for idx, m in enumerate(["1", "2", "3", "4", "5"])
        ]
        contracts, _ = _chapter_contracts(
            chapter_layers=layers,
            effective_links=links,
            body_anchors=anchors,
        )
        self.assertEqual(len(contracts), 1)
        self.assertTrue(contracts[0].def_anchor_mismatch,
                        f"def_anchor_mismatch 应为 True，def=5 vs anchor=18; got {contracts[0]}")
        self.assertEqual(contracts[0].def_count, 5)
        self.assertEqual(contracts[0].anchor_total, 18)

    def test_def_anchor_aligned_when_counts_match(self):
        """章 def 5 个 + anchor 5 个 → def_anchor_mismatch == False。"""
        layers = _chapter_layers_with_endnotes(
            markers=["1", "2", "3", "4", "5"],
            chapter_marker_counts={"ch-1": 5},
        )
        anchors = [
            _body_anchor("ch-1", f"a-{m}", m, page_no=50 + idx)
            for idx, m in enumerate(["1", "2", "3", "4", "5"])
        ]
        links = [
            _matched_link("ch-1", f"en-{m}", f"a-{m}", m, page_no=50 + idx)
            for idx, m in enumerate(["1", "2", "3", "4", "5"])
        ]
        contracts, _ = _chapter_contracts(
            chapter_layers=layers,
            effective_links=links,
            body_anchors=anchors,
        )
        self.assertEqual(len(contracts), 1)
        self.assertFalse(contracts[0].def_anchor_mismatch)

    # ── D. 不应误伤：no_notes 章节 ──

    def test_no_notes_chapter_skips_all_three_checks(self):
        """章 mode=no_notes 且无 endnote_items → 三类校验都不触发。"""
        layers = _chapter_layers_with_endnotes(
            markers=[],
            note_mode="no_notes",
            book_type="no_notes",
            chapter_marker_counts={},
        )
        contracts, _ = _chapter_contracts(
            chapter_layers=layers,
            effective_links=[],
            body_anchors=[],
        )
        self.assertEqual(len(contracts), 1)
        self.assertTrue(contracts[0].first_marker_is_one)
        self.assertFalse(contracts[0].has_marker_gap)
        self.assertFalse(contracts[0].def_anchor_mismatch)


class AnalyzeExportTextNumberingNoGapTest(unittest.TestCase):
    """`_analyze_export_text` 输出新字段 `local_numbering_no_gap` 与 chapter_local_contract_ok。"""

    def _analyze(self, content: str) -> dict:
        from scripts.test_fnm_batch import _analyze_export_text
        return _analyze_export_text(content)

    def test_no_gap_when_defs_are_contiguous_from_one(self):
        content = """## Chapter\nBody[^1] and[^2] and[^3].\n\n### NOTES\n\n[^1]: 1. text.\n[^2]: 2. text.\n[^3]: 3. text.\n"""
        stats = self._analyze(content)
        self.assertTrue(stats.get("local_numbering_starts_at_one"))
        self.assertTrue(stats.get("local_numbering_no_gap"),
                        f"defs=1,2,3 应 no_gap; got {stats}")

    def test_gap_detected_when_defs_skip_a_number(self):
        content = """## Chapter\nBody[^1] and[^2] and[^4].\n\n### NOTES\n\n[^1]: 1. text.\n[^2]: 2. text.\n[^4]: 4. text.\n"""
        stats = self._analyze(content)
        self.assertTrue(stats.get("local_numbering_starts_at_one"))
        self.assertFalse(stats.get("local_numbering_no_gap"),
                         f"defs=1,2,4 应 has gap; got {stats}")

    def test_no_defs_means_no_gap(self):
        content = """## Chapter\nBody only, no notes.\n"""
        stats = self._analyze(content)
        self.assertTrue(stats.get("local_numbering_no_gap"))


if __name__ == "__main__":
    unittest.main()

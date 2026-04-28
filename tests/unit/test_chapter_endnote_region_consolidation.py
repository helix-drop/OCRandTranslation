"""章节末尾 NOTES 容器 region 合并 + 取证字段回填（工单 #2 最小集）。

工单 #2 原计划"合并被切碎的 chapter_endnotes region"已被工单 #5
（移除 footnote-band 短路）副作用解决——`_build_endnote_regions_raw` 自身按
contiguous page-no 自然成段。本测试钉死该状态，防止 footnote-band 短路被
重新引入而再次切碎章 5/6/7 等的 NOTES 容器。

同时验证 `NoteRegionRecord.region_first_note_item_marker` 已被回填（之前
4 处硬编码空字符串，导致下游契约校验缺少首条注号信息）。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BIOPOLITICS_RAW = REPO_ROOT / "test_example" / "Biopolitics" / "raw_pages.json"


def _load_biopolitics_pages() -> list[dict]:
    raw = json.loads(BIOPOLITICS_RAW.read_text(encoding="utf-8"))
    return list(raw.get("pages") or [])


class ChapterEndnoteRegionConsolidationTest(unittest.TestCase):
    """Biopolitics 端到端：每章 chapter_endnotes region 应为单一连续段。"""

    @classmethod
    def setUpClass(cls):
        from FNM_RE.modules.book_note_type import build_book_note_profile
        from FNM_RE.modules.chapter_split import build_chapter_layers
        from FNM_RE.modules.toc_structure import build_toc_structure
        from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc

        cls.pages = _load_biopolitics_pages()
        toc = build_toc_structure(cls.pages, load_auto_visual_toc("Biopolitics")).data
        profile = build_book_note_profile(toc, cls.pages).data
        cls.layers = build_chapter_layers(toc, profile, cls.pages).data

    def _endnote_regions_for(self, title_keyword: str):
        for ch in self.layers.chapters:
            if title_keyword.lower() in str(ch.title or "").lower():
                return list(ch.endnote_regions or [])
        return []

    def test_chapter_31_janvier_has_single_endnote_region(self):
        """金板章 5（LEÇON DU 31 JANVIER 1979），书页 111-118 应连成一段。"""
        regs = self._endnote_regions_for("31 JANVIER")
        self.assertEqual(len(regs), 1, f"应只有 1 段 endnote region，实际 {len(regs)}: {[r.pages for r in regs]}")
        # 应至少含 4 个连续页（金板 note_pages: 111-118 共 8 页，OCR 识别 7-8 页都可接受）
        self.assertGreaterEqual(len(regs[0].pages), 4)

    def test_chapter_7_fevrier_has_single_endnote_region(self):
        """金板章 6（LEÇON DU 7 FÉVRIER 1979），书页 139-148 应连成一段。"""
        regs = self._endnote_regions_for("7 F")  # 7 FÉVRIER
        # 找 février 章
        regs = []
        for ch in self.layers.chapters:
            t = str(ch.title or "").lower()
            if "f" in t and "vrier" in t and "7" in t:
                regs = list(ch.endnote_regions or [])
                break
        self.assertEqual(len(regs), 1, f"应只有 1 段 endnote region，实际 {len(regs)}: {[r.pages for r in regs]}")
        self.assertGreaterEqual(len(regs[0].pages), 5)

    def test_chapter_14_fevrier_has_single_endnote_region(self):
        """金板章 7（LEÇON DU 14 FÉVRIER 1979），书页 170-178 应连成一段。"""
        regs = []
        for ch in self.layers.chapters:
            t = str(ch.title or "").lower()
            if "14 f" in t:
                regs = list(ch.endnote_regions or [])
                break
        self.assertEqual(len(regs), 1, f"应只有 1 段 endnote region，实际 {len(regs)}: {[r.pages for r in regs]}")
        self.assertGreaterEqual(len(regs[0].pages), 5)


class RegionFirstNoteItemMarkerFillTest(unittest.TestCase):
    """`NoteRegionRecord.region_first_note_item_marker` 必须被回填（非空）。

    这是契约校验需要的取证字段：region 第一条 note item 的 marker（通常是 "1"）。
    在工单 #2 之前，4 处硬编码空字符串，导致下游 marker 顺序校验缺数据。
    """

    @classmethod
    def setUpClass(cls):
        from FNM_RE.modules.book_note_type import build_book_note_profile
        from FNM_RE.modules.chapter_split import build_chapter_layers
        from FNM_RE.modules.toc_structure import build_toc_structure
        from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc

        cls.pages = _load_biopolitics_pages()
        toc = build_toc_structure(cls.pages, load_auto_visual_toc("Biopolitics")).data
        profile = build_book_note_profile(toc, cls.pages).data
        cls.layers = build_chapter_layers(toc, profile, cls.pages).data

    def test_endnote_regions_have_first_note_item_marker_populated(self):
        """所有 endnote region（至少 8 个）必须有非空 region_first_note_item_marker。"""
        endnote_regions: list = []
        for ch in self.layers.chapters:
            endnote_regions.extend(list(ch.endnote_regions or []))
        # 应有至少 8 个 endnote region（章 2-12 中至少 8 章有）
        self.assertGreaterEqual(len(endnote_regions), 8, f"endnote region 数过少: {len(endnote_regions)}")
        empty_marker_regions = [
            r.region_id for r in endnote_regions if not str(r.region_first_note_item_marker or "").strip()
        ]
        self.assertEqual(
            empty_marker_regions,
            [],
            f"以下 endnote region 缺 region_first_note_item_marker（应填首条注号 marker）: {empty_marker_regions[:5]}",
        )

    def test_first_note_item_marker_typically_is_one(self):
        """章节末尾 NOTES 容器，第一条注通常是 marker '1'（可能少数 OCR 漏识第一条变 '2'）。"""
        first_markers: list[str] = []
        for ch in self.layers.chapters:
            for r in (ch.endnote_regions or []):
                first_markers.append(str(r.region_first_note_item_marker or ""))
        # 至少一半 region 的首注号是 "1"
        ones = sum(1 for m in first_markers if m == "1")
        self.assertGreaterEqual(
            ones,
            max(1, len(first_markers) // 2),
            f"过半 endnote region 首注号应为 '1'，实际 {ones}/{len(first_markers)}: {first_markers}",
        )


if __name__ == "__main__":
    unittest.main()

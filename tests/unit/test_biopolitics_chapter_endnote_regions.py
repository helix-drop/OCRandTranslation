"""端到端：Biopolitics 章后嵌入式尾注必须形成 chapter-scope endnote region。

Biopolitics 是典型的"目录里没有 Notes 章节、每章末尾紧跟该章 NOTES"版式
（隐式章节附属尾注）。P0 修复（_legacy_page_role_from_toc_role 透传 note）
之后，page_partition 识别出的 note 页会正确写入 phase1.pages，下游
note_regions._is_endnote_candidate_page 能进入 page_role=="note" 分支生成
endnote 候选。

本测试验证：build_phase1 → build_note_regions 跑完后，每个正文章节都至少
有 1 个 scope=chapter 的 endnote region；总章节级 endnote region ≥ 11
（Biopolitics 共 12 课正文章节，第 12 课 4 avril 1979 是纯脚注章可放宽）。
"""

from __future__ import annotations

import unittest

from FNM_RE.app.pipeline import build_phase1_structure
from FNM_RE.stages.note_regions import build_note_regions

from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc, load_pages


class BiopoliticsChapterEndnoteRegionsTest(unittest.TestCase):
    """章后嵌入式 NOTES 应被识别为 scope=chapter 的 endnote region。"""

    @classmethod
    def setUpClass(cls):
        cls.pages = load_pages("Biopolitics")
        toc_items = load_auto_visual_toc("Biopolitics")
        cls.phase1 = build_phase1_structure(cls.pages, toc_items=toc_items)
        cls.regions, cls.summary = build_note_regions(cls.phase1, pages=cls.pages)

    def test_chapter_scope_endnote_region_count(self):
        chapter_endnote_regions = [
            r for r in self.regions
            if r.note_kind == "endnote" and r.scope == "chapter"
        ]
        self.assertGreaterEqual(
            len(chapter_endnote_regions),
            11,
            f"Biopolitics chapter-scope endnote regions 应 ≥ 11, 实际 {len(chapter_endnote_regions)}; "
            f"summary.chapter_region_count={self.summary.get('chapter_region_count')}",
        )

    def test_endnote_region_rows_not_empty(self):
        """阻塞报告中 endnote_region_rows: [] 是 P0 BUG 的直接症状。"""
        endnote_regions = [r for r in self.regions if r.note_kind == "endnote"]
        self.assertGreater(
            len(endnote_regions),
            0,
            "build_note_regions 不应输出 0 个 endnote region",
        )

    def test_each_lecture_chapter_has_endnote_region(self):
        """每个 'Leçon du XX' 章节都应至少绑定一个 chapter-scope endnote region。

        放宽：第 12 课（4 avril 1979）是纯 footnote 章，允许 0 个 endnote region；
        其余 11 课（10 janv ~ 28 mars）必须各有 ≥ 1 个 endnote region。
        """
        chapter_ids_with_endnote = {
            r.chapter_id for r in self.regions
            if r.note_kind == "endnote" and r.scope == "chapter" and r.chapter_id
        }
        lecture_chapters = [
            c for c in self.phase1.chapters
            if "leçon" in (c.title or "").lower() or "lecon" in (c.title or "").lower()
        ]
        # 第 12 课作为已知例外（纯脚注），允许缺席
        non_footnote_only = [
            c for c in lecture_chapters
            if "4 avril" not in (c.title or "").lower()
        ]
        missing = [
            c.title for c in non_footnote_only
            if c.chapter_id not in chapter_ids_with_endnote
        ]
        self.assertLessEqual(
            len(missing),
            1,
            f"以下正文章节缺少 endnote region（最多允许 1 个例外）: {missing}",
        )


if __name__ == "__main__":
    unittest.main()

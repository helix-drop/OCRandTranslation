"""保护 _phase_pages_from_toc 不再把 note / noise 角色降级为 other。

背景：Biopolitics 章后 NOTES 页（如 p.40-42、63-65 等）由 page_partition 阶段
正确识别为 page_role=note，toc_structure._build_page_roles 也已保留该 role。
但 pipeline._legacy_page_role_from_toc_role 当时只覆盖 chapter / post_body /
front_matter 三种 role，其余一律返回 other。这导致：
- 65 页 note 角色在 _phase_pages_from_toc 重建 PagePartitionRecord 时全被打成 other
- 落库后 fnm_pages 没有任何 note 页，下游 note_regions / endnote_chapter_explorer
  的 candidate 选择全部失败，章后尾注无法形成 endnote_region

本测试既覆盖纯函数行为，也用 Biopolitics 真实 fixture 端到端断言下游 records
里的 note 数量。
"""

from __future__ import annotations

import unittest

from FNM_RE.app.pipeline import _legacy_page_role_from_toc_role, _phase_pages_from_toc
from FNM_RE.modules.toc_structure import build_toc_structure
from FNM_RE.modules.types import TocPageRole, TocStructure

from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc, load_pages


class LegacyPageRoleFromTocRoleTest(unittest.TestCase):
    """`_legacy_page_role_from_toc_role` 必须把 note / noise 透传，不归并到 other。"""

    def test_note_role_is_preserved(self):
        self.assertEqual(_legacy_page_role_from_toc_role("note"), "note")

    def test_endnotes_role_becomes_note(self):
        self.assertEqual(_legacy_page_role_from_toc_role("endnotes"), "note")

    def test_noise_role_is_preserved(self):
        self.assertEqual(_legacy_page_role_from_toc_role("noise"), "noise")

    def test_chapter_post_body_become_body(self):
        self.assertEqual(_legacy_page_role_from_toc_role("chapter"), "body")
        self.assertEqual(_legacy_page_role_from_toc_role("post_body"), "body")

    def test_front_matter_passes_through(self):
        self.assertEqual(_legacy_page_role_from_toc_role("front_matter"), "front_matter")

    def test_unknown_role_falls_back_to_other(self):
        self.assertEqual(_legacy_page_role_from_toc_role(""), "other")
        self.assertEqual(_legacy_page_role_from_toc_role("???"), "other")
        self.assertEqual(_legacy_page_role_from_toc_role("back_matter"), "other")


class PhasePagesFromTocPreservesNoteRoleTest(unittest.TestCase):
    """跑完整 build_toc_structure → _phase_pages_from_toc，验证 note role 保留。"""

    def test_phase_pages_convert_toc_endnotes_role_to_note_page_role(self):
        toc_structure = TocStructure(
            pages=[
                TocPageRole(
                    page_no=349,
                    role="endnotes",  # type: ignore[arg-type]
                    source_role="note",
                    reason="endnotes_start_page_hint",
                )
            ]
        )

        phase_pages = _phase_pages_from_toc(toc_structure)

        self.assertEqual(phase_pages[0].page_no, 349)
        self.assertEqual(phase_pages[0].page_role, "note")
        self.assertEqual(phase_pages[0].reason, "endnotes_start_page_hint")

    def test_biopolitics_phase_pages_keep_note_role(self):
        pages = load_pages("Biopolitics")
        toc_items = load_auto_visual_toc("Biopolitics")
        toc_structure = build_toc_structure(pages, toc_items).data
        phase_pages = _phase_pages_from_toc(toc_structure)
        note_count = sum(1 for row in phase_pages if str(row.page_role or "") == "note")
        self.assertGreaterEqual(
            note_count,
            30,
            f"Biopolitics 经 _phase_pages_from_toc 后 note 页数应 ≥ 30, 实际 {note_count}",
        )


if __name__ == "__main__":
    unittest.main()

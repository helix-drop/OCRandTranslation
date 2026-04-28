"""Mode 决策改用 endnote 容器优先（工单 #6，覆盖 docs/fnm-notes-coverage-plan.md §6.6）。

针对 [`FNM_RE/modules/book_note_type.py`](../FNM_RE/modules/book_note_type.py) `build_book_note_profile`
的 mode 决策算法：

- **旧行为**：当章节同时有 footnote 页和 endnote 页时，按"页数比较"决定 mode。
  - 这把"page footnote 1 页 1 条"和"NOTES 容器 1 页 7-8 条"当等量比较，
    导致 Biopolitics 11 章 endnote 主导被误判 footnote_primary，下游 endnote
    修复路径绕过，fallback_match_ratio 居高 (73%)。
- **新行为（C 路径，endnote 优先）**：只要章节有 ≥ 1 个 endnote 页，
  即标 chapter_endnote_primary。NOTES 容器的存在本身就是该章 endnote
  主导的强信号，page footnote（手稿星号等）是辅助补充。

边界保留：
- 仅 footnote 无 endnote → 仍 footnote_primary
- 仅 book_endnote_pages（章节后整书尾注）→ 仍 book_endnote_bound
- 都无 → no_notes
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BIOPOLITICS_RAW = REPO_ROOT / "test_example" / "Biopolitics" / "raw_pages.json"


def _make_page(page_no: int, *, markdown: str = "", footnotes: str = "", block_label: str = "", block_text: str = "") -> dict:
    page: dict = {
        "bookPage": page_no,
        "fileIdx": page_no - 1,
        "target_pdf_page": page_no,
        "markdown": markdown,
        "footnotes": footnotes,
        "prunedResult": {"height": 1200, "width": 900, "parsing_res_list": []},
    }
    if block_label or block_text:
        page["blocks"] = [{"block_label": block_label, "block_content": block_text}]
    return page


def _note_overrides(*page_nos: int) -> dict:
    return {
        "page": {
            str(pn): {"page_role": "note", "reason": "test_force_note"}
            for pn in page_nos
        }
    }


class ChapterModeRegionAwareTest(unittest.TestCase):
    """构造 mixed 章节 fixture，断言 mode = chapter_endnote_primary（不再被页数比较吞掉）。

    复用 build_phase2_structure（高层封装，与 [`tests/unit/test_fnm_re_phase2.py`](test_fnm_re_phase2.py)
    `test_chapter_note_modes_cover_three_primary_states` 同款入口）。
    """

    def test_mixed_chapter_footnote_page_count_exceeds_endnote_page_count_still_endnote(self):
        """mixed 章节：footnote 页（3）多于 endnote 页（1）—— 工单 #6 后应判 endnote。

        旧算法：3 ≥ 1 → footnote_primary
        新算法（endnote 优先）：endnote_pages 非空 → chapter_endnote_primary
        """
        from FNM_RE.app.pipeline import build_phase2_structure

        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody.",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="*. Manuscript footnote one.",
            ),
            _make_page(2, markdown="Body continuation.", footnotes="*. Another star."),
            _make_page(3, markdown="Body more.", footnotes="*. Third star."),
            _make_page(
                4,
                markdown=(
                    "# Notes\n"
                    "1. Endnote one.\n"
                    "2. Endnote two.\n"
                    "3. Endnote three.\n"
                    "4. Endnote four."
                ),
            ),
            _make_page(
                5,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]
        structure = build_phase2_structure(pages, page_overrides=_note_overrides(4))
        mode_by_chapter = {row.chapter_id: row.note_mode for row in structure.chapter_note_modes}
        ch1_id = structure.chapters[0].chapter_id
        self.assertEqual(
            mode_by_chapter.get(ch1_id),
            "chapter_endnote_primary",
            f"工单 #6：mixed 章节有 endnote 容器时应优先判 chapter_endnote_primary，"
            f"实际 {mode_by_chapter.get(ch1_id)}",
        )

    def test_only_footnote_no_endnote_remains_footnote_primary(self):
        """仅 footnote 页、无 endnote 页 → 仍 footnote_primary（边界保留）。"""
        from FNM_RE.app.pipeline import build_phase2_structure

        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nBody.",
                block_label="doc_title",
                block_text="Chapter One",
                footnotes="1. Footnote content.",
            ),
            _make_page(2, markdown="Body continuation."),
            _make_page(
                3,
                markdown="# Chapter Two\nBody.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]
        structure = build_phase2_structure(pages)
        mode_by_chapter = {row.chapter_id: row.note_mode for row in structure.chapter_note_modes}
        ch1_id = structure.chapters[0].chapter_id
        self.assertEqual(mode_by_chapter.get(ch1_id), "footnote_primary")

    def test_no_notes_chapter_remains_no_notes(self):
        """无 footnote 也无 endnote → no_notes（边界保留）。"""
        from FNM_RE.app.pipeline import build_phase2_structure

        pages = [
            _make_page(
                1,
                markdown="# Chapter One\nPure body.",
                block_label="doc_title",
                block_text="Chapter One",
            ),
            _make_page(2, markdown="More body."),
            _make_page(
                3,
                markdown="# Chapter Two\nMore body.",
                block_label="doc_title",
                block_text="Chapter Two",
            ),
        ]
        structure = build_phase2_structure(pages)
        mode_by_chapter = {row.chapter_id: row.note_mode for row in structure.chapter_note_modes}
        ch1_id = structure.chapters[0].chapter_id
        self.assertEqual(mode_by_chapter.get(ch1_id), "no_notes")

    # NB. book_endnote_bound 的边界已被 [`test_fnm_re_phase2.py`](test_fnm_re_phase2.py)
    # `test_chapter_note_modes_cover_three_primary_states` 钉死，该测试改后仍通过；
    # 此处不冗余覆盖（小 fixture 1 章时 nearest-prior 兜底会把唯一 NOTES 绑回唯一章）。


class ChapterModeBiopoliticsIntegrationTest(unittest.TestCase):
    """Biopolitics 端到端：至少 9 章 mode = chapter_endnote_primary（工单 #6 验收）。"""

    @classmethod
    def setUpClass(cls):
        if not BIOPOLITICS_RAW.exists():
            raise FileNotFoundError(BIOPOLITICS_RAW)
        from FNM_RE.modules.book_note_type import build_book_note_profile
        from FNM_RE.modules.toc_structure import build_toc_structure
        from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc

        cls.pages = json.loads(BIOPOLITICS_RAW.read_text(encoding="utf-8"))["pages"]
        toc = build_toc_structure(cls.pages, load_auto_visual_toc("Biopolitics"))
        cls.profile = build_book_note_profile(toc.data, cls.pages).data

    def test_biopolitics_endnote_primary_chapter_count(self):
        """Biopolitics 13 个 chapter（fallback chapters）中至少 11 章应是 chapter_endnote_primary。

        基线（修复前）：仅 2 章（ch.5/ch.7）；其余 11 章被页数比较错判 footnote_primary。
        修复后实测 11 章 chapter_endnote_primary（仅 ch.0 'AVERTISSEMENT' 和
        ch.13 'Situation du cours' 仍 footnote_primary——它们没有章末 NOTES 容器）。
        """
        modes = [row.note_mode for row in self.profile.chapter_modes]
        en_count = sum(1 for m in modes if m == "chapter_endnote_primary")
        self.assertGreaterEqual(
            en_count,
            11,
            f"工单 #6：Biopolitics 至少 11 章应是 chapter_endnote_primary，实际 {en_count}: {modes}",
        )


if __name__ == "__main__":
    unittest.main()

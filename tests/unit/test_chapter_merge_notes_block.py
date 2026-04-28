"""导出章节 NOTES 块格式（工单 #7，覆盖 docs/fnm-notes-coverage-plan.md §6.7）。

针对 [`FNM_RE/modules/chapter_merge.py`](../FNM_RE/modules/chapter_merge.py)
`_rewrite_residual_raw_markers_for_chapter`：

1. **NOTES 标题统一输出**：当章节有 ≥ 1 条新追加的定义（definitions 非空），
   且当前 body 末尾没有 `### NOTES` 标题时，应自动追加。原行为：直接堆 `[^N]:`
   行，导致除章 1（OCR 自带 `### NOTES`）外其余章节都缺标题。

2. **`N. ` 印刷编号前缀**：每条定义渲染为 `[^N]: N. <text>`。如果 text 已经
   以 `N. ` 开头则不重复（幂等）。原行为：直接 `[^N]: <text>` 缺前缀。

3. **抑制开关**（可选，本次跳过）：原计划用于章 14（manifest=0）时跳过 NOTES
   输出，但实际 Biopolitics fixture 数据下 ch.14 没有 endnote 定义，不会触发。
"""

from __future__ import annotations

import re
import unittest

from FNM_RE.modules.chapter_merge import _apply_notes_block_format
from FNM_RE.modules.types import ChapterMarkdownEntry  # noqa: F401  (used by setUpClass)


class NotesHeadingUniformOutputTest(unittest.TestCase):
    """工单 #7a：当章节末尾有 `[^N]:` 定义但缺 `### NOTES` 标题时自动追加。"""

    def test_appends_notes_heading_before_definitions_when_missing(self):
        """body 中没有 `### NOTES` 但末尾有 `[^N]:` 定义 → 追加标题。"""
        text = (
            "# Chapter Heading Test\n"
            "Body with [^1] reference.\n"
            "\n"
            "[^1]: Endnote one cached text.\n"
        )
        result = _apply_notes_block_format(text)
        self.assertIn("### NOTES", result, f"应追加 NOTES 标题；result:\n{result}")
        notes_idx = result.find("### NOTES")
        first_def_idx = result.find("[^1]:")
        self.assertLess(notes_idx, first_def_idx, "### NOTES 应在 [^1]: 定义之前")

    def test_does_not_duplicate_notes_heading_when_already_present(self):
        """body 已有 `### NOTES` 时不重复追加。"""
        text = (
            "# Chapter With Existing Heading\n"
            "Body with [^1] reference.\n"
            "\n"
            "### NOTES\n"
            "\n"
            "[^1]: Endnote one cached text.\n"
        )
        result = _apply_notes_block_format(text)
        self.assertEqual(
            result.count("### NOTES"),
            1,
            f"NOTES 标题应仅出现 1 次；result:\n{result}",
        )

    def test_no_definitions_no_notes_heading(self):
        """没有任何 [^N]: 定义行时不应追加标题。"""
        text = "# Chapter Without Notes\nPure body, no markers."
        result = _apply_notes_block_format(text)
        self.assertNotIn("### NOTES", result)


class DefinitionPrintedPrefixTest(unittest.TestCase):
    """工单 #7b：定义行 `[^N]: <text>` 自动改为 `[^N]: N. <text>`（幂等）。"""

    def test_appends_printed_prefix_when_text_lacks_it(self):
        """`[^1]: Walter Eucken...` → `[^1]: 1. Walter Eucken...`."""
        text = (
            "# Chapter Prefix Test\nBody [^1].\n\n"
            "### NOTES\n"
            "[^1]: Walter Eucken (1891-1950): chef de l'école.\n"
        )
        result = _apply_notes_block_format(text)
        self.assertIn("[^1]: 1. Walter Eucken", result, f"应加印刷前缀；result:\n{result}")

    def test_does_not_duplicate_prefix_when_text_already_has_it(self):
        """`[^1]: 1. Walter Eucken...` → 不重复（仍 `[^1]: 1. Walter Eucken...`）。"""
        text = (
            "# Chapter Idempotent Prefix\nBody [^1].\n\n"
            "### NOTES\n"
            "[^1]: 1. Walter Eucken (1891-1950).\n"
        )
        result = _apply_notes_block_format(text)
        self.assertNotIn("1. 1. ", result)
        self.assertIn("[^1]: 1. Walter Eucken", result)

    def test_multi_digit_marker_prefix(self):
        """多位数 marker `[^15]: ...` → `[^15]: 15. ...`."""
        text = (
            "# Chapter Multi Digit\nBody [^15].\n\n"
            "### NOTES\n"
            "[^15]: Multi digit endnote text.\n"
        )
        result = _apply_notes_block_format(text)
        self.assertIn("[^15]: 15. Multi digit", result, f"result:\n{result}")


class BiopoliticsExportEndToEndTest(unittest.TestCase):
    """端到端：跑完整 Biopolitics 流程后，章节 markdown 应满足两条新规则.

    1. 至少 8 章含 `### NOTES` 标题（基线只有 1 章 ch.1 自带）。
    2. 至少 8 章的首条定义行为 `[^1]: 1. ...`（基线 0 章带印刷前缀）。
    """

    @classmethod
    def setUpClass(cls):
        from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc, load_pages
        from FNM_RE.modules.book_note_type import build_book_note_profile
        from FNM_RE.modules.chapter_split import build_chapter_layers
        from FNM_RE.modules.toc_structure import build_toc_structure
        from FNM_RE.modules.note_linking import build_note_link_table
        from FNM_RE.modules.ref_freeze import build_frozen_units
        from FNM_RE.modules.chapter_merge import build_chapter_markdown_set

        cls.pages = load_pages("Biopolitics")
        toc = build_toc_structure(cls.pages, load_auto_visual_toc("Biopolitics")).data
        profile = build_book_note_profile(toc, cls.pages).data
        layers = build_chapter_layers(toc, profile, cls.pages).data
        link_table = build_note_link_table(layers, cls.pages).data
        frozen = build_frozen_units(layers, link_table).data
        cls.set_result = build_chapter_markdown_set(frozen, link_table, layers).data

    def test_biopolitics_chapters_have_notes_heading(self):
        chapters_with_heading = [
            row.title
            for row in self.set_result.chapters
            if "### NOTES" in str(row.markdown_text or "")
        ]
        self.assertGreaterEqual(
            len(chapters_with_heading),
            8,
            f"工单 #7a：至少 8 章应含 `### NOTES` 标题，实际 {len(chapters_with_heading)}: {chapters_with_heading}",
        )

    def test_biopolitics_def_lines_have_printed_prefix(self):
        """检查至少 8 章的 `[^N]:` 定义行带 `N. ` 印刷前缀。"""
        prefix_re = re.compile(r"^\[\^(\d+)\]:\s*(\d+)\.\s+", re.MULTILINE)
        chapters_with_prefix = []
        for row in self.set_result.chapters:
            text = str(row.markdown_text or "")
            for m in prefix_re.finditer(text):
                if m.group(1) == m.group(2):  # marker == 印刷编号
                    chapters_with_prefix.append(row.title)
                    break
        self.assertGreaterEqual(
            len(chapters_with_prefix),
            8,
            f"工单 #7b：至少 8 章应有 `[^N]: N. ` 前缀格式，实际 {len(chapters_with_prefix)}: {chapters_with_prefix}",
        )


if __name__ == "__main__":
    unittest.main()

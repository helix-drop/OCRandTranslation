"""长 note 不被截断回归（工单 #8 缩减为防回归）。

工单 #8 原计划：
1. 修 ch.5 [^4] 在导出时被截到 "vol." 的截断
2. 缓存命中遥测回写

调研结论（已固化到 PROGRESS.md）：
- 截断在工单 #1-#7 完成后**已自然解决**——`build_chapter_markdown_set` 流程中
  `_sanitize_note_text` 只做 markup 清理 + 空白归一，不截断长文本；ch.5 [^4]
  现在保留 787 字符（金板 cache 内容完整）。
- `owner_fallback_note_unit_count` 经审查后并非"cache 命中计数器"，而是
  `_resolve_note_item_owner` 兜底分配的章节归属计数，原工单描述存在误判。
- 因此 #8 在当前代码下无须代码修改，本测试仅作回归保护，防止以后某次重构
  又把长 note 切短。

回归契约：
- Biopolitics 章 5 (LEÇON DU 31 JANVIER 1979) [^4] 定义文本长度 ≥ 200 字符
- 所有 endnote 定义不应以 "vol." / "no." / "p." 等明显被截断的标识结尾
"""

from __future__ import annotations

import re
import unittest


class LongNoteNoTruncationRegressionTest(unittest.TestCase):
    """钉死长 note 不被截断到 OCR 引文缩写处。"""

    @classmethod
    def setUpClass(cls):
        from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc, load_pages
        from FNM_RE.modules.book_note_type import build_book_note_profile
        from FNM_RE.modules.chapter_split import build_chapter_layers
        from FNM_RE.modules.toc_structure import build_toc_structure
        from FNM_RE.modules.note_linking import build_note_link_table
        from FNM_RE.modules.ref_freeze import build_frozen_units
        from FNM_RE.modules.chapter_merge import build_chapter_markdown_set

        pages = load_pages("Biopolitics")
        toc = build_toc_structure(pages, load_auto_visual_toc("Biopolitics")).data
        profile = build_book_note_profile(toc, pages).data
        layers = build_chapter_layers(toc, profile, pages).data
        link_table = build_note_link_table(layers, pages).data
        frozen = build_frozen_units(layers, link_table).data
        cls.set_result = build_chapter_markdown_set(frozen, link_table, layers).data

    def _chapter_text(self, *title_keywords: str) -> str:
        for ch in self.set_result.chapters:
            t = str(ch.title or "")
            if all(kw in t for kw in title_keywords):
                return str(ch.markdown_text or "")
        return ""

    def test_ch5_note_4_definition_is_full_length(self):
        """章 5 (LEÇON DU 31 JANVIER 1979) [^4] 定义不应被截到 'vol.' 等引文缩写。"""
        text = self._chapter_text("31 JANVIER")
        self.assertTrue(text, "未找到章 5（31 JANVIER）markdown")
        m = re.search(r"^\[\^4\]:\s*4\.\s*(.+?)$", text, re.MULTILINE)
        self.assertIsNotNone(m, "ch.5 [^4]: 定义行未找到")
        body = m.group(1).strip()
        self.assertGreaterEqual(
            len(body),
            200,
            f"ch.5 [^4] 文本被截断（仅 {len(body)} 字符），疑似回退到截断 bug：\n{body[:200]!r}",
        )
        # 显式 negative 断言：不应以这些"裁切痕迹"结尾
        truncation_endings = ("vol.", "no.", "p.", "pp.", "vol")
        for ending in truncation_endings:
            self.assertFalse(
                body.rstrip().endswith(ending),
                f"ch.5 [^4] 以 {ending!r} 结尾，疑似被截断：\n{body[-120:]!r}",
            )

    def test_no_endnote_definition_truncated_to_citation_abbrev(self):
        """全书所有 endnote 定义不应在 OCR 引文缩写处被截断。

        负面模式要求"逗号/分号 + 空格 + 引文缩写词 + 句号"形态（如 `, vol.`、
        `; n°.`），表示后面应有引文卷号但被切了。这能排除合法引文结尾
        如 `... 2 vol.`（"2 卷本"，真实结尾）。
        """
        truncation_pattern = re.compile(
            r"[,;]\s+(?:vol|n[°o]|nos?|nr|p|pp|art|chap|t|tome|cf|infra|supra|ibid|loc|op|"
            r"voir|see|éd|ed|eds|dir|trad|tr)\.$",
            re.IGNORECASE,
        )
        violations: list[tuple[str, str, str]] = []
        for ch in self.set_result.chapters:
            text = str(ch.markdown_text or "")
            for m in re.finditer(r"^\[\^(\d+)\]:\s*\d+\.\s*(.+?)$", text, re.MULTILINE):
                marker = m.group(1)
                body = m.group(2).strip()
                # 短于 30 字符的定义大概率是真短注，不算截断
                if len(body) < 30:
                    continue
                if truncation_pattern.search(body):
                    violations.append((str(ch.title or ""), marker, body[-80:]))
        self.assertEqual(
            violations,
            [],
            f"以下定义疑似被截断到引文缩写："
            + "\n".join(f"  {title} [^{marker}]: ...{tail!r}" for title, marker, tail in violations[:5]),
        )


if __name__ == "__main__":
    unittest.main()

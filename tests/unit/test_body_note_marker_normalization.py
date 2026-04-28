"""正文注号多形态识别 + 干扰过滤（工单 #1，覆盖 docs/fnm-notes-coverage-plan.md §6.1）。

针对 `FNM_RE.shared.anchors.scan_anchor_markers` 的扩展能力做约束：
- 6 种 OCR 形态都能识别为 normalized_marker 数字
- Roman ordinal（XVIIIe / XX<sup>e</sup> / n°）不被误识
- 年份（4 位数 1500-2100）不被误识
- 真实 Biopolitics 章 1 段落能识别 ≥ 5 个不同 marker
"""

from __future__ import annotations

import unittest

from FNM_RE.shared.anchors import scan_anchor_markers


class BodyNoteMarkerNormalizationTest(unittest.TestCase):
    """覆盖 5+1 形态、Roman ordinal mask、年份过滤、真实段落。"""

    def _markers(self, text: str) -> list[str]:
        refs, _ = scan_anchor_markers(text)
        return [str(r["normalized_marker"]) for r in refs]

    # ── 5 主形态 ─────────────────────────────────

    def test_bracket_caret_form(self):
        """[^N] 形态识别为 N。"""
        self.assertEqual(
            sorted(set(self._markers("voir Walpole[^2] et Freud[^1]"))),
            ["1", "2"],
        )

    def test_bracket_bare_form(self):
        """裸方括号 [N] 识别为 N（章 1 注 6 形态）。"""
        text = "à cette notion [6]. Ce que j'avais essayé de repérer"
        self.assertIn("6", self._markers(text))

    def test_unicode_superscript_form(self):
        """Unicode 上标 ¹²³⁴⁵ 识别为对应数字（章 1 注 1-5 形态）。"""
        markers = self._markers("« Acheronta movebo¹. » ... Walpole² ... « Quieta non movere³ » ... folie ?⁴ ... ensuite⁵.")
        for expected in ["1", "2", "3", "4", "5"]:
            self.assertIn(expected, markers, f"漏识 Unicode 上标 {expected}; got {markers}")

    def test_html_sup_form(self):
        """<sup>10</sup> 识别为 10（章 1 注 10 形态）。"""
        self.assertIn("10", self._markers("comment ne pas trop gouverner<sup>10</sup>."))

    def test_latex_sup_form(self):
        """$ ^{N} $ 识别为 N（章 1 注 9 形态）。"""
        self.assertIn("9", self._markers("a établi la liste $ ^{9} $, le partage"))
        self.assertIn("6", self._markers("donné ensuite à cette notion $ ^{6} $. Ce que j'avais"))

    # ── Roman ordinal mask ──────────────────────

    def test_roman_ordinal_html_sup_e_not_marker(self):
        """`<sup>e</sup>`（XVIII<sup>e</sup>）不应被识别为 marker。"""
        text = "siècle XVIII<sup>e</sup> et XX<sup>e</sup>"
        self.assertEqual(self._markers(text), [])

    def test_roman_ordinal_inline_not_marker(self):
        """XIXe / XXe / XVIIIe inline ordinal 不应识别（混入真 marker 时只识真 marker）。"""
        text = "au XIXe et au XXe siècle, voir Walpole[^2]"
        self.assertEqual(self._markers(text), ["2"])

    def test_n_degree_not_marker(self):
        """法语 `n° 21` 序号不识别。"""
        text = "vol. 13, n° 21, 1933"
        self.assertEqual(self._markers(text), [])

    def test_p_page_citation_not_marker(self):
        """`p. 200` 这种页码引用不应被裸数字启发式误识。"""
        text = "voir Foucault, op. cit., p. 200, et infra p. 305-380."
        self.assertEqual(self._markers(text), [])

    # ── 年份过滤（已有 looks_like_year_marker） ──

    def test_year_in_brackets_filtered(self):
        """[1789] 四位数年份不识别为 marker。"""
        text = "voir [1789] et [1810], puis Walpole[^2]"
        self.assertEqual(self._markers(text), ["2"])

    # ── 真实 Biopolitics 章 1 段落 ─────────────

    def test_biopolitics_chapter1_p17_paragraph(self):
        """章 1 第 17 页第 1 段：注 1/2/3 (Unicode 上标)。"""
        text = (
            "[Vous connaissez] la citation de Freud : « Acheronta movebo¹. » "
            "Eh bien, je voudrais placer le cours de cette année sous le signe "
            "d'une autre citation moins connue et qui a été faite par quelqu'un "
            "de moins connu, enfin, d'une certaine façon, c'est l'homme d'État "
            "anglais Walpole² qui disait, à propos de sa propre manière de "
            "gouverner : « Quieta non movere³ »"
        )
        self.assertEqual(sorted(set(self._markers(text))), ["1", "2", "3"])

    def test_biopolitics_chapter1_mixed_5_forms(self):
        """模拟章 1 5 形态混合段：[^N] + Unicode 上标 + LaTeX + bracket + HTML sup。"""
        text = (
            "Walpole[^2] disait : « Quieta non movere ». La folie n'existe pas?⁴ "
            "Je reviendrai plus tard ensuite⁵. "
            "Cette notion $ ^{6} $ mérite d'être discutée. "
            "Bentham a établi la liste $ ^{9} $ ... "
            "Comment ne pas trop gouverner<sup>10</sup>."
        )
        markers = sorted(set(self._markers(text)))
        for expected in ["2", "4", "5", "6", "9", "10"]:
            self.assertIn(expected, markers, f"漏识 {expected}; got {markers}")

    # ── 第 6 形态：紧跟词后的裸数字（条件识别） ──

    def test_bare_digit_after_word_recognized(self):
        """`Encyclopédie 11` 形态：紧跟法语词后的 1-3 位裸数字应识别。"""
        text = (
            "article « Économie politique » de l'Encyclopédie 11 –, "
            "l'économie politique, c'est une sorte"
        )
        self.assertIn("11", self._markers(text))

    def test_bare_digit_in_isolation_not_recognized(self):
        """段内只有数量/章节号、没有任何明确 marker 形态时，裸数字不识别。

        启发式约束：紧跟"voir/cf/cf./infra/p/pp/vol/fig"等引用前缀的数字不识别。
        """
        text = "Section 1 introduction. Voir le tableau 5 ci-dessous."
        markers = self._markers(text)
        self.assertEqual(markers, [], f"段内无明确 marker 时不应识别裸数字; got {markers}")


if __name__ == "__main__":
    unittest.main()

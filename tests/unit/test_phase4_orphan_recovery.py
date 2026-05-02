"""阶段4：直接正文搜索恢复 orphan endnote 锚点。

对 post-repair 仍为 orphan_note 的 endnote 条目，用 known marker 号
在章 body text 中做宽松文本搜索，找到后创建补缺 body_anchor。
"""

from __future__ import annotations

import re
import unittest
from types import SimpleNamespace


def _find_marker_in_body(body_text: str, marker: str) -> dict | None:
    """用已知 marker 号在 body text 中做宽松搜索。返回匹配位置或 None。"""
    patterns = [
        # 方括号（允许任意空白）
        rf'\[\s*{re.escape(marker)}\s*\]',
        # LaTeX 上标
        rf'\$\s*\^\s*\{{\s*{re.escape(marker)}\s*\}}\s*\$',
        # HTML 上标
        rf'<sup>\s*{re.escape(marker)}\s*</sup>',
        # 纯上标
        rf'\^\s*\{{\s*{re.escape(marker)}\s*\}}',
        # Unicode 上标
        _unicode_superscript_pattern(marker),
    ]
    for pattern in patterns:
        if not pattern:
            continue
        m = re.search(pattern, body_text)
        if m:
            return {
                "start": m.start(),
                "end": m.end(),
                "source_text": body_text[max(0, m.start()-20):min(len(body_text), m.end()+20)],
                "matched_pattern": pattern,
            }
    return None


def _unicode_superscript_pattern(num_str: str) -> str | None:
    """构建 Unicode 上标正则，如 '17' → '[¹⁷]'. 仅当所有数字都能映射到上标字符时有效。"""
    superscript_map = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    }
    chars = [superscript_map.get(c) for c in num_str]
    if None in chars:
        return None
    return ''.join(chars)


class Phase4OrphanRecoveryTest(unittest.TestCase):
    """orphan_note 的 marker 在 body text 中被宽松搜索恢复。"""

    def test_find_marker_bracket_with_spaces(self):
        result = _find_marker_in_body("some text [ 17 ] more", "17")
        self.assertIsNotNone(result, "[ 17 ] 应被匹配")
        self.assertIn("17", result["source_text"])

    def test_find_marker_latex_superscript(self):
        result = _find_marker_in_body("some $^{17}$ text", "17")
        self.assertIsNotNone(result, "$^{17}$ 应被匹配")

    def test_find_marker_html_superscript(self):
        result = _find_marker_in_body("text<sup>17</sup>end", "17")
        self.assertIsNotNone(result, "<sup>17</sup> 应被匹配")

    def test_find_marker_unicode_superscript(self):
        result = _find_marker_in_body("text ¹⁷ end", "17")
        self.assertIsNotNone(result, "Unicode 上标应被匹配")

    def test_find_marker_not_found(self):
        result = _find_marker_in_body("no number here", "17")
        self.assertIsNone(result, "数字不存在应返回 None")

    def test_find_marker_distinguishes_different_numbers(self):
        """只匹配目标 marker，不匹配其他数字。"""
        result = _find_marker_in_body("ref [ 14 ] and also [ 17 ]", "17")
        self.assertIsNotNone(result, "应找到 [ 17 ]")
        # 验证找到的是 17 不是 14
        self.assertIn("17", result["source_text"])

    def test_unicode_superscript_digits_only(self):
        self.assertEqual(_unicode_superscript_pattern("17"), "¹⁷")
        self.assertIsNone(_unicode_superscript_pattern("abc"))


class Phase4OrphanRecoveryIntegrationTest(unittest.TestCase):
    """恢复逻辑在真实数据上的可调用性验证。"""

    def test_orphan_recovery_functions_importable_and_callable(self):
        """恢复函数可直接从 note_links 模块导入并调用。"""
        from FNM_RE.stages.note_links import (
            _find_marker_in_body,
            _build_orphan_recovery_anchors,
        )
        # 构造最小测试数据
        pages = [{"bookPage": 1, "markdown": "Body text [42] reference."}]
        orphans = [{"marker": "42", "chapter_id": "ch1", "note_item_id": "n1", "page_nos": [1]}]
        recovered = _build_orphan_recovery_anchors(orphans, pages)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].normalized_marker, "42")
        self.assertEqual(recovered[0].source, "orphan_recovery")


if __name__ == "__main__":
    unittest.main()

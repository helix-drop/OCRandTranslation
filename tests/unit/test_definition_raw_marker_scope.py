"""回归：`_definition_has_raw_note_marker` 只判定行首是裸标记，不扫定义正文。

历史实现对定义块逐行"剥离行首标记后扫剩余文本"，在三类实际书目里产生伪阳：

- Napoleon：`[^10]: AN, F¹⁵ 2606-2607.`（档案编号上标被误判为漏转）
- Mad_Act：`[^2]: ... [13] 3b-4a ...`（古籍叶码方括号被误判）
- Heidegger：`[^1]: ... néant² : ...`（脚注正文嵌套引用的单字符上标）

新语义：定义块里一行如果以 `[^N]:` 开头 → 合规；
只有行首本身是裸标记（`1)`、`(1)`、`[1]`、`<sup>1</sup>`、`¹` 等）且
后面没有 `[^N]:` 形式时，才视为漏转定义。
"""

from __future__ import annotations

import unittest

from FNM_RE.stages import export_audit as ea


class DefinitionRawMarkerScopeTest(unittest.TestCase):
    def test_archive_superscript_in_definition_body_not_flagged(self):
        text = "[^10]: AN, F¹⁵ 2606-2607. Le nom du médecin..."
        allowed = {"10", "15"}
        self.assertFalse(
            ea._definition_has_raw_note_marker(text, allowed_markers=allowed),
            "档案编号 F¹⁵ 不应被判为漏转标记",
        )

    def test_bracketed_folio_in_definition_body_not_flagged(self):
        text = "[^2]: The other sections: Wind (3b-4a), Cold (60a-69a). [13] 3b-4a (LiuWYQ: 89B)."
        allowed = {"2", "13"}
        self.assertFalse(
            ea._definition_has_raw_note_marker(text, allowed_markers=allowed),
            "古籍叶码 [13] 不应被判为漏转标记",
        )

    def test_nested_superscript_inside_footnote_body_not_flagged(self):
        text = "[^1]: L'Étre et le néant² : elle permet de retracer..."
        allowed = {"1", "2"}
        self.assertFalse(
            ea._definition_has_raw_note_marker(text, allowed_markers=allowed),
            "脚注正文内嵌套上标不应阻塞导出",
        )

    def test_leading_raw_marker_paren_flagged(self):
        text = "1) Smith, J. 1999. A Study.\n2) Doe, J. 2000."
        allowed = {"1", "2"}
        self.assertTrue(
            ea._definition_has_raw_note_marker(text, allowed_markers=allowed),
            "行首裸标记 `1)` 属于未转换的定义标签，应当判漏",
        )

    def test_leading_bracketed_raw_marker_flagged(self):
        text = "[1] Smith, J. 1999.\n[2] Doe, J."
        allowed = {"1", "2"}
        self.assertTrue(
            ea._definition_has_raw_note_marker(text, allowed_markers=allowed),
            "行首 `[1]` 属于未转换的定义标签，应当判漏",
        )

    def test_leading_unicode_superscript_flagged(self):
        text = "¹ Smith, J. 1999.\n² Doe, J."
        allowed = {"1", "2"}
        self.assertTrue(
            ea._definition_has_raw_note_marker(text, allowed_markers=allowed),
            "行首 unicode 上标属于未转换的定义标签，应当判漏",
        )

    def test_wellformed_local_ref_not_flagged(self):
        text = "[^1]: Smith, J.\n[^2]: Doe, J."
        allowed = {"1", "2"}
        self.assertFalse(
            ea._definition_has_raw_note_marker(text, allowed_markers=allowed),
            "合规的 `[^N]:` 定义不应被判漏",
        )


if __name__ == "__main__":
    unittest.main()

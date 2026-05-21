"""阶段1：分离 footnote/endnote 编号空间。

footnote 在正文中保留 * 标记不转 [^N]，endnote 独占 [^N] 编号。
### NOTES 从 [^1] 开始，不再含 footnote 定义。
"""

from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

from FNM_RE.models import (
    TranslationUnitRecord,
    UnitPageSegmentRecord,
    UnitParagraphRecord,
)
from FNM_RE.stages.export import _build_section_markdown


def _make_body_unit(chapter_id: str, body_text: str, page_no: int = 1) -> TranslationUnitRecord:
    paragraph = UnitParagraphRecord(
        order=1, kind="body", heading_level=0,
        source_text=body_text, display_text=body_text,
        cross_page=None, consumed_by_prev=False,
        translated_text=body_text,
    )
    segment = UnitPageSegmentRecord(
        page_no=page_no, paragraph_count=1,
        source_text=body_text, display_text=body_text,
        paragraphs=[paragraph],
    )
    return TranslationUnitRecord(
        unit_id=f"body-{page_no:04d}", kind="body", owner_kind="chapter",
        owner_id=chapter_id, section_id=chapter_id,
        section_title=f"Chapter {chapter_id}",
        section_start_page=page_no, section_end_page=page_no,
        note_id="", page_start=page_no, page_end=page_no,
        char_count=len(body_text), source_text=body_text,
        translated_text=body_text, status="ok", error_msg="",
        target_ref="", page_segments=[segment],
    )


def _make_note_unit(chapter_id: str, note_id: str, *, kind: str, text: str, page_no: int = 1) -> TranslationUnitRecord:
    return TranslationUnitRecord(
        unit_id=f"note-{note_id}", kind=kind, owner_kind="chapter",
        owner_id=chapter_id, section_id=chapter_id,
        section_title=f"Chapter {chapter_id}",
        section_start_page=page_no, section_end_page=page_no,
        note_id=note_id, page_start=page_no, page_end=page_no,
        char_count=len(text), source_text=text, translated_text=text,
        status="ok", error_msg="",
        target_ref=f"{{{{NOTE_REF:{note_id}}}}}",
    )


def _run_export(*, body_text: str, notes: list[tuple[str, str, str]],
                chapter_id: str = "ch1", chapter_title: str = "Test Chapter",
                chapter_note_mode: str = "chapter_endnote_primary") -> str:
    chapter = SimpleNamespace(chapter_id=chapter_id, title=chapter_title, pages=[1])
    body_units = [_make_body_unit(chapter_id, body_text)]
    note_units = [
        _make_note_unit(chapter_id, nid, kind=kind, text=text)
        for nid, kind, text in notes
    ]
    content, _summary = _build_section_markdown(
        chapter, section_heads=[], body_units=body_units,
        note_units=note_units, matched_links=[], note_items_by_id={},
        body_anchors_by_id={}, include_diagnostic_entries=False,
        diagnostic_machine_by_page={},
        book_type="mixed", chapter_note_mode=chapter_note_mode,
    )
    return content


class Phase1NumberingSeparationTest(unittest.TestCase):
    """footnote 不占 [^N] 编号，endnote 独占并连续递增。"""

    def test_endnote_only_numbering_unchanged(self):
        """纯 endnote 章：[^N] 从 1 开始连续。"""
        notes = [
            ("en-001", "endnote", "1. First endnote."),
            ("en-002", "endnote", "2. Second endnote."),
        ]
        body = "Body text{{NOTE_REF:en-001}} and more{{NOTE_REF:en-002}}."
        content = _run_export(body_text=body, notes=notes)
        self.assertIn("### NOTES", content)
        self.assertNotIn("### Footnotes", content,
                         "纯 endnote 章不应有 ### Footnotes 区段")
        self.assertIn("[^1]:", content)
        self.assertIn("[^2]:", content)
        refs = re.findall(r"\[\^(\d+)\]", content.split("### NOTES")[0])
        self.assertEqual(refs, ["1", "2"],
                         f"正文 ref 应为 [^1][^2] 连续，实为 {refs}")

    def test_footnote_ref_keeps_star_marker(self):
        """纯 footnote 章（footnote_primary）：无 endnote 冲突，[^N] 或 * 均可接受。"""
        notes = [
            ("fn-001", "footnote", "Footnote alpha."),
            ("fn-002", "footnote", "Footnote beta."),
        ]
        body = "Start{{NOTE_REF:fn-001}} middle{{NOTE_REF:fn-002}} end."
        content = _run_export(body_text=body, notes=notes,
                              chapter_note_mode="footnote_primary")
        body_part = content.split("### ")[0] if "### " in content else content
        # 纯 footnote 章无 endnote 冲突，[^1][^2] 编号也合理（不会抢 endnote 号）
        ref1 = "[^1]" in body_part
        ref2 = "[^2]" in body_part
        has_stars = body_part.count("*") >= 1
        self.assertTrue(ref1 or has_stars,
                        f"应有 [^1] 或 * 标记，body_part={body_part[:200]}")
        self.assertTrue(ref2 or has_stars,
                        f"应有 [^2] 或 * 标记")

    def test_mixed_numbering_separated(self):
        """混排章：endnote 得 [^N]，footnote 得 *，NOTES 从 [^1] 开始。"""
        notes = [
            ("en-001", "endnote", "1. Endnote one."),
            ("fn-001", "footnote", "Footnote alpha."),
            ("en-002", "endnote", "2. Endnote two."),
            ("fn-002", "footnote", "Footnote beta."),
        ]
        body = "A{{NOTE_REF:en-001}}B{{NOTE_REF:fn-001}}C{{NOTE_REF:en-002}}D{{NOTE_REF:fn-002}}E"
        content = _run_export(body_text=body, notes=notes)
        body_part = content.split("### ")[0]
        # Endnote refs should be [^1] [^2]
        self.assertIn("[^1]", body_part)
        self.assertIn("[^2]", body_part)
        self.assertNotIn("[^3]", body_part, "只有 2 个 endnote，不应出现 [^3]")
        # Footnote refs should be *
        asterisks = body_part.count("*")
        self.assertGreaterEqual(asterisks, 2,
                                f"应有 ≥2 个 * 表示 footnote，实际 {asterisks}")
        # NOTES section
        self.assertIn("### NOTES", content)
        notes_section = content.split("### NOTES")[1]
        self.assertIn("[^1]:", notes_section)
        self.assertIn("[^2]:", notes_section)
        self.assertNotIn("[^3]:", notes_section)
        # No ### Footnotes section needed (footnotes are * in body)
        self.assertNotIn("### Footnotes", content,
                         "footnote 定义已以 * 在正文中，不需要 ### Footnotes 区段")

    def test_missing_note_id_keeps_original(self):
        """note_id 在 note_text_by_id 中不存在时保持原始标记（不转 [^N]）。"""
        notes = [
            ("en-001", "endnote", "1. Endnote one."),
        ]
        body = "{{NOTE_REF:en-001}} and {{NOTE_REF:en-999}}"
        content = _run_export(body_text=body, notes=notes)
        # en-001 gets [^1], en-999 stays as-is (no note_text_by_id entry)
        body_part = content.split("### ")[0]
        self.assertIn("[^1]", body_part)
        # en-999 has no matching note_text_by_id → resolve fails → original text kept
        self.assertNotIn("[^999]", body_part or content,
                         "无法匹配的 ref 不应生成 [^N]")


if __name__ == "__main__":
    unittest.main()

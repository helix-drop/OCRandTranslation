"""阶段1.5：footnote 定义以 [footnote] \\* text 内联到对应段落后。"""

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
                chapter_id: str = "ch1", chapter_title: str = "Test Chapter") -> str:
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
        book_type="mixed", chapter_note_mode="chapter_endnote_primary",
    )
    return content


class Phase15InlineFootnoteTest(unittest.TestCase):
    """footnote 定义 [footnote] \\* text 紧跟在正文段落后。"""

    def test_footnote_definition_after_paragraph(self):
        """正文 * 标记后紧跟 [footnote] \\* 定义行。"""
        notes = [
            ("fn-001", "footnote", "Lapsus manifeste."),
        ]
        body = "Body text.{{NOTE_REF:fn-001}}"
        content = _run_export(body_text=body, notes=notes)
        body_part = content.split("### ")[0] if "### " in content else content
        self.assertIn("*", body_part)
        # footnote 定义应紧跟在正文后
        self.assertIn("[footnote] \\* Lapsus manifeste.", content)

    def test_multiple_footnotes_all_after_paragraph(self):
        """多个 footnote 全部列在正文后。"""
        notes = [
            ("fn-001", "footnote", "Alpha."),
            ("fn-002", "footnote", "Beta."),
        ]
        body = "A{{NOTE_REF:fn-001}} B{{NOTE_REF:fn-002}}"
        content = _run_export(body_text=body, notes=notes)
        self.assertIn("[footnote] \\* Alpha.", content)
        self.assertIn("[footnote] \\* Beta.", content)

    def test_mixed_endnote_numbered_footnote_inline(self):
        """endnote 进入 ### NOTES，footnote 内联在正文后。"""
        notes = [
            ("en-001", "endnote", "1. Endnote one."),
            ("fn-001", "footnote", "Page footnote."),
            ("en-002", "endnote", "2. Endnote two."),
        ]
        body = "A{{NOTE_REF:en-001}}B{{NOTE_REF:fn-001}}C{{NOTE_REF:en-002}}"
        content = _run_export(body_text=body, notes=notes)
        # 正文有 [^1]*[^2]
        body_part = content.split("### ")[0]
        self.assertIn("[^1]", body_part)
        self.assertIn("[^2]", body_part)
        self.assertIn("*", body_part)
        # footnote 定义在正文段落之后（before ### NOTES）
        self.assertIn("[footnote] \\* Page footnote.", content)
        # endnote 在 ### NOTES
        self.assertIn("### NOTES", content)
        notes_section = content.split("### NOTES")[1]
        self.assertIn("[^1]: Endnote one.", notes_section)
        self.assertIn("[^2]: Endnote two.", notes_section)

    def test_duplicate_footnote_id_only_once(self):
        """同一 footnote_id 多次引用只输出一次定义。"""
        notes = [
            ("fn-001", "footnote", "Same footnote."),
        ]
        body = "First{{NOTE_REF:fn-001}} and again{{NOTE_REF:fn-001}}"
        content = _run_export(body_text=body, notes=notes)
        count = content.count("[footnote] \\* Same footnote.")
        self.assertEqual(count, 1, f"重复引用只应一次定义，实际 {count}")


if __name__ == "__main__":
    unittest.main()

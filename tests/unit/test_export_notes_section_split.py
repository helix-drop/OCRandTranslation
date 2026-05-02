"""阶段1后更新：footnote 在正文中以 * 标记，不再有 ### Footnotes 区段。
endnote 独占 [^N] 编号空间，### NOTES 从 [^1] 开始。
"""

from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

from FNM_RE.models import (
    NoteLinkRecord,
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
                matched_links: list[NoteLinkRecord] | None = None,
                note_section_id: str | None = None,
                chapter_id: str = "ch1", chapter_title: str = "Test Chapter",
                return_summary: bool = False) -> str | tuple[str, dict[str, int]]:
    chapter = SimpleNamespace(chapter_id=chapter_id, title=chapter_title, pages=[1])
    body_units = [_make_body_unit(chapter_id, body_text)]
    note_units = [
        _make_note_unit(note_section_id or chapter_id, nid, kind=kind, text=text)
        for nid, kind, text in notes
    ]
    content, summary = _build_section_markdown(
        chapter, section_heads=[], body_units=body_units,
        note_units=note_units, matched_links=list(matched_links or []), note_items_by_id={},
        body_anchors_by_id={}, include_diagnostic_entries=False,
        diagnostic_machine_by_page={},
        book_type="mixed", chapter_note_mode="chapter_endnote_primary",
    )
    if return_summary:
        return content, summary
    return content


def _notes_section_defs(content: str) -> list[str]:
    """提取 ### NOTES 下所有 [^N]: 定义行。"""
    lines = content.splitlines()
    in_section = False
    found: list[str] = []
    for line in lines:
        if line.startswith("### "):
            if in_section:
                break
            if line.strip() == "### NOTES":
                in_section = True
            continue
        if in_section and re.match(r"^\[\^[^\]]+\]:" , line):
            found.append(line)
    return found


class ExportNotesSectionSplitTest(unittest.TestCase):
    """阶段1后：footnote 不参与 [^N] 编号，无 ### Footnotes 区段。"""

    def test_endnote_and_footnote_numbering_separated(self):
        """混排：5 endnote 得 [^1]-[^5]，3 footnote 得 * 标记。"""
        notes = [
            ("en-001", "endnote", "1. Endnote one."),
            ("en-002", "endnote", "2. Endnote two."),
            ("fn-001", "footnote", "Footnote alpha."),
            ("en-003", "endnote", "3. Endnote three."),
            ("fn-002", "footnote", "Footnote beta."),
            ("en-004", "endnote", "4. Endnote four."),
            ("fn-003", "footnote", "Footnote gamma."),
            ("en-005", "endnote", "5. Endnote five."),
        ]
        body = " ".join(f"text{{{{NOTE_REF:{nid}}}}}" for nid, _, _ in notes)
        content = _run_export(body_text=body, notes=notes)
        body_part = content.split("### ")[0]
        # Endnotes get [^1]-[^5]
        for i in range(1, 6):
            self.assertIn(f"[^{i}]", content)
        self.assertNotIn("[^6]", content, "只有 5 个 endnote，不应有 [^6]")
        # Footnotes get * in body
        self.assertIn("*", body_part)
        # NOTES section has 5 endnote defs, no footnotes
        self.assertEqual(len(_notes_section_defs(content)), 5)
        self.assertNotIn("### Footnotes", content, "footnote 不占区段")

    def test_endnote_only_no_footnote_section(self):
        notes = [
            ("en-001", "endnote", "1. Endnote one."),
            ("en-002", "endnote", "2. Endnote two."),
        ]
        body = " ".join(f"text{{{{NOTE_REF:{nid}}}}}" for nid, _, _ in notes)
        content = _run_export(body_text=body, notes=notes)
        self.assertIn("### NOTES", content)
        self.assertNotIn("### Footnotes", content)

    def test_footnote_only_no_notes_no_footnote_section(self):
        """纯 footnote 章：正文有 * 标记，无 ### NOTES 也无 ### Footnotes。"""
        notes = [
            ("fn-001", "footnote", "Footnote alpha."),
            ("fn-002", "footnote", "Footnote beta."),
        ]
        body = " ".join(f"text{{{{NOTE_REF:{nid}}}}}" for nid, _, _ in notes)
        content = _run_export(body_text=body, notes=notes)
        self.assertNotIn("### NOTES", content)
        self.assertNotIn("### Footnotes", content)
        self.assertIn("*", content)

    def test_no_notes_no_section(self):
        content = _run_export(body_text="Plain body without notes.", notes=[])
        self.assertNotIn("### NOTES", content)
        self.assertNotIn("### Footnotes", content)

    def test_local_ref_count_matches_endnote_definition_count(self):
        """ref/def 闭合：正文 [^N] 数 == ### NOTES 下 [^N]: 定义数。"""
        notes = [
            ("en-001", "endnote", "1. Endnote one."),
            ("fn-001", "footnote", "Footnote alpha."),
            ("en-002", "endnote", "2. Endnote two."),
        ]
        body = " ".join(f"text{{{{NOTE_REF:{nid}}}}}" for nid, _, _ in notes)
        content = _run_export(body_text=body, notes=notes)
        body_part = content.split("### ")[0]
        refs = sorted(set(re.findall(r"\[\^([0-9]+)\]", body_part)))
        endnote_defs = sorted(set(re.findall(r"^\[\^([0-9]+)\]:", content, re.MULTILINE)))
        self.assertEqual(len(refs), 2, f"正文应有 2 个 [^N]（2 endnote），实为 {len(refs)}")
        self.assertEqual(len(endnote_defs), 2, f"### NOTES 应有 2 条 endnote 定义")

    def test_body_ref_before_colon_counts_as_closed(self):
        """法语正文常见 `[^N] :`，不能误判为 orphan definition。"""
        content, summary = _run_export(
            body_text="Le problème pascalien{{NOTE_REF:en-001}} : qu'est-ce qui arrive ?",
            notes=[("en-001", "endnote", "1. Pascal note.")],
            return_summary=True,
        )

        self.assertIn("[^1] :", content)
        self.assertEqual(int(summary.get("missing_definition_count") or 0), 0)
        self.assertEqual(int(summary.get("orphan_definition_count") or 0), 0)

    def test_orphan_endnote_definition_is_not_exported_as_normal_note(self):
        link = NoteLinkRecord(
            link_id="link-1",
            chapter_id="ch1",
            region_id="nr1",
            note_item_id="en-001",
            anchor_id="missing-anchor",
            status="matched",
            resolver="fallback",
            confidence=1.0,
            note_kind="endnote",
            marker="1",
            page_no_start=1,
            page_no_end=1,
        )
        content = _run_export(
            body_text="Body without an explicit note ref.",
            notes=[("en-001", "endnote", "1. Orphan note text.")],
            matched_links=[link],
            note_section_id="orphan-owner",
        )

        self.assertNotIn("### NOTES", content)
        self.assertNotIn("[^1]:", content)
        self.assertNotRegex(content, r"(?m)^\[\^1\]$")

    def test_footnote_marks_body_with_star_not_bracket(self):
        """footnote ref 在正文中以 * 呈现，不在 ### NOTES 中。"""
        notes = [
            ("en-001", "endnote", "1. First endnote."),
            ("fn-001", "footnote", "Lapsus manifeste."),
            ("fn-002", "footnote", "Phrase inachevée."),
        ]
        body = " ".join(f"text{{{{NOTE_REF:{nid}}}}}" for nid, _, _ in notes)
        content = _run_export(body_text=body, notes=notes)
        body_part = content.split("### ")[0]
        self.assertIn("### NOTES", content)
        self.assertNotIn("### Footnotes", content)
        self.assertEqual(len(_notes_section_defs(content)), 1, "仅 1 条 endnote")
        asterisks = body_part.count("*")
        self.assertGreaterEqual(asterisks, 2, f"footnote 应有 ≥2 个 *，实际 {asterisks}")


if __name__ == "__main__":
    unittest.main()

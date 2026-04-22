from __future__ import annotations

import unittest

from FNM_RE.modules.book_assemble import build_export_bundle
from FNM_RE.modules.types import (
    ChapterMarkdownEntry,
    ChapterMarkdownSet,
    TocChapter,
    TocNode,
    TocStructure,
)


def _chapter_entry(order: int, chapter_id: str, title: str, body: str) -> ChapterMarkdownEntry:
    return ChapterMarkdownEntry(
        order=order,
        chapter_id=chapter_id,
        title=title,
        path=f"chapters/{order:03d}-{title}.md",
        markdown_text=f"## {title}\n\n{body}\n",
        start_page=order,
        end_page=order,
        pages=[order],
    )


def _toc_structure(chapters: list[TocChapter], toc_tree: list[TocNode] | None = None) -> TocStructure:
    return TocStructure(
        pages=[],
        toc_tree=list(toc_tree or []),
        chapters=chapters,
        section_heads=[],
    )


def _long_paragraph(seed: str) -> str:
    return (
        f"{seed} starts with a focused claim about reading practice and social context. "
        "It continues with evidence, interpretation, and a clear argumentative transition. "
        "Finally it closes with a concise synthesis that keeps punctuation and semantic continuity."
    )


class FnmReModule7ExportTest(unittest.TestCase):
    def test_order_and_index_follow_toc(self):
        toc = _toc_structure(
            chapters=[
                TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter"),
                TocChapter(chapter_id="c2", title="Chapter Two", start_page=2, end_page=2, pages=[2], role="chapter"),
            ]
        )
        chapter_set = ChapterMarkdownSet(
            chapters=[
                _chapter_entry(1, "c2", "Chapter Two", "Body two."),
                _chapter_entry(2, "c1", "Chapter One", "Body one."),
            ]
        )
        result = build_export_bundle(chapter_set, toc, slug="demo")

        self.assertTrue(result.gate_report.hard["export.order_follows_toc"])
        self.assertEqual([row.chapter_id for row in result.data.chapters], ["c1", "c2"])
        index_text = result.data.index_markdown
        self.assertLess(index_text.find("Chapter One"), index_text.find("Chapter Two"))
        self.assertEqual(result.gate_report.hard["export.audit_can_ship"], result.data.audit_report.can_ship)

    def test_extra_chapter_breaks_toc_order_gate_and_reason(self):
        toc = _toc_structure(
            chapters=[
                TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter"),
                TocChapter(chapter_id="c2", title="Chapter Two", start_page=2, end_page=2, pages=[2], role="chapter"),
            ]
        )
        chapter_set = ChapterMarkdownSet(
            chapters=[
                _chapter_entry(1, "c1", "Chapter One", "Body one."),
                _chapter_entry(2, "c2", "Chapter Two", "Body two."),
                _chapter_entry(3, "c3", "Chapter Three", "Extra chapter."),
            ]
        )
        result = build_export_bundle(chapter_set, toc, slug="demo")

        self.assertFalse(result.gate_report.hard["export.order_follows_toc"])
        self.assertIn("export_order_not_follow_toc", result.gate_report.reasons)
        self.assertEqual(result.data.semantic_summary.get("extra_chapter_ids"), ["c3"])

    def test_missing_post_body_export_is_blocking(self):
        toc = _toc_structure(
            chapters=[
                TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter"),
                TocChapter(chapter_id="c2", title="Appendix", start_page=2, end_page=2, pages=[2], role="post_body"),
            ],
            toc_tree=[
                TocNode(node_id="n1", title="Chapter One", role="chapter", level=1, target_pdf_page=1),
                TocNode(node_id="n2", title="Appendix", role="post_body", level=1, target_pdf_page=2),
            ],
        )
        chapter_set = ChapterMarkdownSet(chapters=[_chapter_entry(1, "c1", "Chapter One", "Body one.")])
        result = build_export_bundle(chapter_set, toc, slug="demo")

        self.assertFalse(result.gate_report.hard["export.audit_can_ship"])
        self.assertTrue(
            any("missing_post_body_export" in set(row.issue_codes or []) for row in result.data.audit_report.files)
        )

    def test_container_exported_as_chapter_is_blocking(self):
        toc = _toc_structure(
            chapters=[TocChapter(chapter_id="c1", title="Part I", start_page=1, end_page=1, pages=[1], role="chapter")],
            toc_tree=[TocNode(node_id="n1", title="Part I", role="container", level=1, target_pdf_page=1)],
        )
        chapter_set = ChapterMarkdownSet(chapters=[_chapter_entry(1, "c1", "Part I", "Body one.")])
        result = build_export_bundle(chapter_set, toc, slug="demo")

        self.assertFalse(result.gate_report.hard["export.audit_can_ship"])
        self.assertTrue(
            any(
                "container_exported_as_chapter" in set(row.issue_codes or [])
                for row in result.data.audit_report.files
            )
        )

    def test_cross_chapter_and_raw_marker_leak_are_blocking(self):
        toc = _toc_structure(
            chapters=[
                TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter"),
                TocChapter(chapter_id="c2", title="Chapter Two", start_page=2, end_page=2, pages=[2], role="chapter"),
            ]
        )
        chapter_set = ChapterMarkdownSet(
            chapters=[
                _chapter_entry(1, "c1", "Chapter One", "Body [1].\n\n[^1]: Note one.\n\n## Chapter Two"),
                _chapter_entry(2, "c2", "Chapter Two", "Body two."),
            ]
        )
        result = build_export_bundle(chapter_set, toc, slug="demo")

        self.assertFalse(result.gate_report.hard["export.no_cross_chapter_contamination"])
        self.assertFalse(result.gate_report.hard["export.no_raw_marker_leak_book_level"])
        self.assertFalse(result.gate_report.hard["export.audit_can_ship"])

    def test_definition_raw_and_legacy_marker_leak_blocks_export_reason(self):
        toc = _toc_structure(
            chapters=[TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter")]
        )
        chapter_set = ChapterMarkdownSet(
            chapters=[
                _chapter_entry(
                    1,
                    "c1",
                    "Chapter One",
                    "Body ref[^1].\n\n[^1]: Definition line.\n    [2] leaked marker.\n    {{NOTE_REF:legacy-token}}",
                )
            ]
        )
        result = build_export_bundle(chapter_set, toc, slug="demo")

        issue_codes = set(result.data.audit_report.files[0].issue_codes or [])
        self.assertFalse(result.gate_report.hard["export.no_raw_marker_leak_book_level"])
        self.assertIn("export_raw_marker_leak", result.gate_report.reasons)
        self.assertIn("raw_note_marker_leak", issue_codes)
        self.assertIn("legacy_note_token_leak", issue_codes)

    def test_export_depth_too_shallow_is_blocking(self):
        toc = _toc_structure(
            chapters=[
                TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter"),
                TocChapter(chapter_id="c2", title="Chapter Two", start_page=2, end_page=2, pages=[2], role="chapter"),
                TocChapter(chapter_id="c3", title="Chapter Three", start_page=3, end_page=3, pages=[3], role="chapter"),
            ],
            toc_tree=[
                TocNode(node_id="n1", title="Chapter One", role="chapter", level=1, target_pdf_page=1),
                TocNode(node_id="n2", title="Chapter Two", role="chapter", level=1, target_pdf_page=2),
                TocNode(node_id="n3", title="Chapter Three", role="chapter", level=1, target_pdf_page=3),
            ],
        )
        chapter_set = ChapterMarkdownSet(chapters=[_chapter_entry(1, "c1", "Chapter One", "Body one.")])
        result = build_export_bundle(chapter_set, toc, slug="demo")

        self.assertFalse(result.gate_report.hard["export.audit_can_ship"])
        self.assertTrue(
            any("export_depth_too_shallow" in set(row.issue_codes or []) for row in result.data.audit_report.files)
        )

    def test_adjacent_duplicate_long_body_paragraph_is_collapsed(self):
        duplicate = _long_paragraph("Duplicate paragraph")
        toc = _toc_structure(
            chapters=[TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter")]
        )
        chapter_set = ChapterMarkdownSet(
            chapters=[_chapter_entry(1, "c1", "Chapter One", f"{duplicate}\n\n{duplicate}")]
        )

        result = build_export_bundle(chapter_set, toc, slug="demo")

        self.assertTrue(result.gate_report.hard["export.semantic_contract_ok"])
        self.assertFalse(bool(result.data.semantic_summary.get("duplicate_paragraph_detected")))
        self.assertTrue(bool(result.data.semantic_summary.get("canonicalization_applied")))
        self.assertEqual(int(result.data.semantic_summary.get("collapsed_duplicate_paragraph_count") or 0), 1)
        self.assertEqual(int(result.data.semantic_summary.get("affected_file_count") or 0), 1)
        self.assertEqual(
            result.data.semantic_summary.get("affected_files_preview"),
            ["chapters/001-Chapter One.md"],
        )
        chapter_text = str(result.data.chapter_files.get("chapters/001-Chapter One.md") or "")
        self.assertEqual(chapter_text.count(duplicate), 1)
        self.assertIn("canonicalization_summary", result.diagnostics)
        self.assertIn("audit_issue_file_summary", result.diagnostics)

    def test_non_adjacent_duplicate_paragraph_remains_blocking(self):
        duplicate = _long_paragraph("Repeated non adjacent paragraph")
        middle = _long_paragraph("Middle paragraph")
        toc = _toc_structure(
            chapters=[TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter")]
        )
        chapter_set = ChapterMarkdownSet(
            chapters=[_chapter_entry(1, "c1", "Chapter One", f"{duplicate}\n\n{middle}\n\n{duplicate}")]
        )

        result = build_export_bundle(chapter_set, toc, slug="demo")

        self.assertFalse(result.gate_report.hard["export.semantic_contract_ok"])
        self.assertTrue(bool(result.data.semantic_summary.get("duplicate_paragraph_detected")))
        self.assertFalse(bool(result.data.semantic_summary.get("canonicalization_applied")))
        self.assertEqual(int(result.data.semantic_summary.get("collapsed_duplicate_paragraph_count") or 0), 0)

    def test_definition_block_duplicate_is_not_collapsed(self):
        duplicate_definition = _long_paragraph("Definition duplicate paragraph")
        toc = _toc_structure(
            chapters=[TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter")]
        )
        chapter_set = ChapterMarkdownSet(
            chapters=[
                _chapter_entry(
                    1,
                    "c1",
                    "Chapter One",
                    (
                        "Main body paragraph.\n\n"
                        f"[^1]: {duplicate_definition}\n\n"
                        f"[^2]: {duplicate_definition}"
                    ),
                )
            ]
        )

        result = build_export_bundle(chapter_set, toc, slug="demo")

        self.assertFalse(result.gate_report.hard["export.semantic_contract_ok"])
        self.assertTrue(bool(result.data.semantic_summary.get("duplicate_paragraph_detected")))
        self.assertFalse(bool(result.data.semantic_summary.get("canonicalization_applied")))
        self.assertEqual(int(result.data.semantic_summary.get("collapsed_duplicate_paragraph_count") or 0), 0)

    def test_heading_and_image_blocks_are_not_collapsed(self):
        toc = _toc_structure(
            chapters=[TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter")]
        )
        chapter_set = ChapterMarkdownSet(
            chapters=[
                _chapter_entry(
                    1,
                    "c1",
                    "Chapter One",
                    "### Figure Section\n\n### Figure Section\n\n![figure](image.png)\n\n![figure](image.png)\n\nShort caption.",
                )
            ]
        )

        result = build_export_bundle(chapter_set, toc, slug="demo")

        self.assertFalse(bool(result.data.semantic_summary.get("canonicalization_applied")))
        self.assertEqual(int(result.data.semantic_summary.get("collapsed_duplicate_paragraph_count") or 0), 0)
        chapter_text = str(result.data.chapter_files.get("chapters/001-Chapter One.md") or "")
        self.assertEqual(chapter_text.count("![figure](image.png)"), 2)

    def test_export_repairs_fixable_garbled_block_without_touching_chinese_text(self):
        toc = _toc_structure(
            chapters=[TocChapter(chapter_id="c1", title="Chapter One", start_page=1, end_page=1, pages=[1], role="chapter")]
        )
        chapter_set = ChapterMarkdownSet(
            chapters=[
                _chapter_entry(
                    1,
                    "c1",
                    "Chapter One",
                    (
                        "Intro paragraph with common words.\n\n"
                        "D85C5C3B9@DC G5B5D5=@<1D5C6?B45C3B929>7B51<9DI\n\n"
                        "中文引文保持原样。"
                    ),
                )
            ]
        )

        result = build_export_bundle(chapter_set, toc, slug="demo")

        chapter_text = str(result.data.chapter_files.get("chapters/001-Chapter One.md") or "")
        self.assertNotIn("D85C5C3B9@DC", chapter_text)
        self.assertIn("thesescripts", chapter_text.lower())
        self.assertIn("中文引文保持原样。", chapter_text)
        self.assertEqual(int(result.data.semantic_summary.get("repaired_garbled_block_count") or 0), 1)
        self.assertTrue(bool(result.data.semantic_summary.get("garbled_block_repair_applied")))


if __name__ == "__main__":
    unittest.main()

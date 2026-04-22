"""FNM Module 2 增强功能单元测试。

测试内容：
1. 多信号 section 切分
2. 页底脚注兜底识别（双通道）
3. 书末尾注回挂
4. 编号重置不再制造 gap 风暴
"""

from __future__ import annotations

import unittest

from FootNoteMachine.scripts.footnote_endnote_filter_prototype import (
    BoundarySignal,
    PageSignals,
    Section,
    extract_page_signals,
    find_boundary_signals,
    merge_nearby_boundaries,
    build_sections,
    _detect_bottom_footnote_blocks,
    collect_footnotes,
    extract_refs,
    _infer_section_kind,
    _attach_book_endnotes_to_body_sections,
)


class TestPageSignalExtraction(unittest.TestCase):
    """测试页面信号提取"""

    def test_extract_doc_title_signal(self):
        """测试 doc_title 信号提取"""
        page = {
            "prunedResult": {
                "parsing_res_list": [
                    {
                        "block_label": "doc_title",
                        "block_content": "Chapter 1: Introduction",
                        "block_order": 1,
                        "block_bbox": [50, 100, 500, 150],
                    },
                    {
                        "block_label": "text",
                        "block_content": "Body text here.",
                        "block_order": 2,
                        "block_bbox": [50, 200, 500, 800],
                    },
                ]
            }
        }
        signals = extract_page_signals(page, page_no=1)
        self.assertEqual(len(signals.doc_titles), 1)
        # extract_page_signals 返回的字典使用 "text" 键
        self.assertEqual(signals.doc_titles[0]["text"], "Chapter 1: Introduction")

    def test_extract_notes_heading_signal(self):
        """测试 Notes 标题信号提取"""
        page = {
            "prunedResult": {
                "parsing_res_list": [
                    {
                        "block_label": "doc_title",  # Notes 作为 doc_title 会被分到 notes_headings
                        "block_content": "Notes",
                        "block_order": 1,
                        "block_bbox": [50, 100, 200, 150],
                    },
                ]
            }
        }
        signals = extract_page_signals(page, page_no=31)
        self.assertEqual(len(signals.notes_headings), 1)

    def test_extract_back_matter_heading(self):
        """测试后置章节标题信号"""
        page = {
            "prunedResult": {
                "parsing_res_list": [
                    {
                        "block_label": "doc_title",
                        "block_content": "Bibliography",
                        "block_order": 1,
                        "block_bbox": [50, 100, 300, 150],
                    },
                ]
            }
        }
        signals = extract_page_signals(page, page_no=200)
        self.assertEqual(len(signals.back_matter_headings), 1)


class TestBoundarySignals(unittest.TestCase):
    """测试边界信号检测"""

    def test_find_doc_title_boundary(self):
        """doc_title 应产生强信号边界"""
        all_signals = [
            PageSignals(
                page_no=1,
                doc_titles=[{"text": "Chapter 1", "bbox": [0, 0, 100, 50], "label": "doc_title"}],
                paragraph_titles=[],
                notes_headings=[],
                back_matter_headings=[],
                footnote_blocks=[],
                bottom_text_blocks=[],
                numeric_markers=[],
            )
        ]
        boundaries = find_boundary_signals(all_signals)
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(boundaries[0].signal_type, "doc_title")
        self.assertEqual(boundaries[0].strength, "strong")

    def test_find_notes_heading_boundary(self):
        """Notes 标题应产生强信号边界"""
        all_signals = [
            PageSignals(
                page_no=31,
                doc_titles=[],
                paragraph_titles=[],
                notes_headings=[{"text": "Notes", "bbox": [0, 0, 100, 50], "label": "doc_title"}],
                back_matter_headings=[],
                footnote_blocks=[],
                bottom_text_blocks=[],
                numeric_markers=[],
            )
        ]
        boundaries = find_boundary_signals(all_signals)
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(boundaries[0].signal_type, "notes_heading")
        self.assertEqual(boundaries[0].section_kind, "book_end_notes")

    def test_merge_nearby_boundaries(self):
        """相邻页的边界信号应合并，保留最强的"""
        boundaries = [
            BoundarySignal(page_no=10, signal_type="doc_title", strength="strong", title="Chapter 1", section_kind="body", confidence=0.9, details=""),
            BoundarySignal(page_no=11, signal_type="paragraph_title", strength="medium", title="Chapter 1 subtitle", section_kind="body", confidence=0.7, details=""),
        ]
        merged = merge_nearby_boundaries(boundaries, window=2)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].strength, "strong")


class TestSectionKindInference(unittest.TestCase):
    """测试 section 类型推断"""

    def test_infer_body_section(self):
        """普通章节标题应推断为 body"""
        self.assertEqual(_infer_section_kind("Chapter 1: Introduction", None), "body")

    def test_infer_notes_section(self):
        """Notes 标题应推断为 book_end_notes"""
        self.assertEqual(_infer_section_kind("Notes", None), "book_end_notes")
        self.assertEqual(_infer_section_kind("Endnotes", None), "book_end_notes")

    def test_infer_bibliography_section(self):
        """Bibliography 标题应推断为 bibliography"""
        self.assertEqual(_infer_section_kind("Bibliography", None), "bibliography")
        self.assertEqual(_infer_section_kind("References", None), "bibliography")

    def test_infer_index_section(self):
        """Index 标题应推断为 index"""
        self.assertEqual(_infer_section_kind("Index", None), "index")


class TestBuildSections(unittest.TestCase):
    """测试多信号 section 切分"""

    def test_build_sections_with_notes_area(self):
        """应正确识别 Notes 区作为独立 section"""
        pages = [
            {
                "prunedResult": {
                    "parsing_res_list": [
                        {"block_label": "doc_title", "block_content": "Chapter 1", "block_order": 1, "block_bbox": [0, 0, 100, 50]},
                    ]
                },
                "markdown": {"text": "Chapter 1 content"},
            },
            {
                "prunedResult": {
                    "parsing_res_list": [
                        {"block_label": "doc_title", "block_content": "Notes", "block_order": 1, "block_bbox": [0, 0, 100, 50]},
                    ]
                },
                "markdown": {"text": "1. First note.\n2. Second note."},
            },
        ]
        sections = build_sections(pages)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0].section_kind, "body")
        self.assertEqual(sections[1].section_kind, "book_end_notes")


class TestBookEndnotesAttachment(unittest.TestCase):
    """测试书末尾注回挂"""

    def test_attach_endnotes_to_preceding_body_section(self):
        """书末尾注应回挂到 Notes 区之前的最后一个正文章节"""
        from FootNoteMachine.scripts.footnote_endnote_filter_prototype import Note
        
        sections = [
            Section(index=1, title="Chapter 1", section_id="sec-01-chapter-1", start_page=1, end_page=10, pages=list(range(1, 11)), section_kind="body"),
            Section(index=2, title="Chapter 2", section_id="sec-02-chapter-2", start_page=11, end_page=20, pages=list(range(11, 21)), section_kind="body"),
            Section(index=3, title="Notes", section_id="sec-03-notes", start_page=21, end_page=25, pages=list(range(21, 26)), section_kind="book_end_notes"),
        ]
        # 在 Notes 区添加一些尾注
        sections[2].endnotes = [
            Note(note_id="en-03-0001", kind="endnote", original_marker="1", start_page=21, section_id="sec-03-notes"),
            Note(note_id="en-03-0002", kind="endnote", original_marker="2", start_page=21, section_id="sec-03-notes"),
        ]
        
        _attach_book_endnotes_to_body_sections(sections)
        
        # 尾注应该被移到第二章
        self.assertEqual(len(sections[2].endnotes), 0)
        self.assertEqual(len(sections[1].endnotes), 2)
        # 尾注的 section_id 应该更新
        self.assertEqual(sections[1].endnotes[0].section_id, "sec-02-chapter-2")

    def test_attach_endnotes_splits_duplicate_marker_runs_across_body_sections(self):
        """当尾注 marker 在 Notes 区重置时，应按顺序分配到不同正文章节。"""
        from FootNoteMachine.scripts.footnote_endnote_filter_prototype import Note

        sec1 = Section(
            index=1,
            title="Chapter 1",
            section_id="sec-01",
            start_page=1,
            end_page=80,
            pages=list(range(1, 81)),
            section_kind="body",
        )
        sec2 = Section(
            index=2,
            title="Chapter 2",
            section_id="sec-02",
            start_page=81,
            end_page=160,
            pages=list(range(81, 161)),
            section_kind="body",
        )
        notes_sec = Section(
            index=3,
            title="Notes",
            section_id="sec-03-notes",
            start_page=161,
            end_page=190,
            pages=list(range(161, 191)),
            section_kind="book_end_notes",
        )
        sec1.page_refs = {5: {"1", "2"}, 12: {"1"}}
        sec2.page_refs = {90: {"1", "2"}, 97: {"2"}}

        n1 = Note(note_id="en-03-0001", kind="endnote", original_marker="1", start_page=162, section_id="sec-03-notes")
        n1.add_block(162, "1. first run note one")
        n2 = Note(note_id="en-03-0002", kind="endnote", original_marker="2", start_page=162, section_id="sec-03-notes")
        n2.add_block(162, "2. first run note two")
        n3 = Note(note_id="en-03-0003", kind="endnote", original_marker="1", start_page=170, section_id="sec-03-notes")
        n3.add_block(170, "1. second run note one")
        n4 = Note(note_id="en-03-0004", kind="endnote", original_marker="2", start_page=170, section_id="sec-03-notes")
        n4.add_block(170, "2. second run note two")
        notes_sec.endnotes = [n1, n2, n3, n4]

        sections = [sec1, sec2, notes_sec]
        _attach_book_endnotes_to_body_sections(sections)

        self.assertEqual([n.note_id for n in sec1.endnotes], ["en-03-0001", "en-03-0002"])
        self.assertEqual([n.note_id for n in sec2.endnotes], ["en-03-0003", "en-03-0004"])
        self.assertEqual(len(notes_sec.endnotes), 0)


class TestDualChannelFootnoteDetection(unittest.TestCase):
    """测试双通道脚注检测"""

    def test_detect_bottom_footnote_from_text_block(self):
        """页底 text 块以数字 marker 开头应被识别为脚注"""
        page = {
            "prunedResult": {
                "parsing_res_list": [
                    {"block_label": "text", "block_content": "Main body text.", "block_order": 1, "block_bbox": [50, 100, 500, 400]},
                    {"block_label": "text", "block_content": "1. This is footnote content.", "block_order": 2, "block_bbox": [50, 700, 500, 750]},
                ]
            }
        }
        page_refs = {"1"}
        candidates = _detect_bottom_footnote_blocks(page, page_no=5, page_refs=page_refs)
        self.assertEqual(len(candidates), 1)
        self.assertIn("footnote content", candidates[0]["block_content"])

    def test_skip_labeled_footnote_blocks(self):
        """已标记为 footnote 的块不应在第二通道重复检测"""
        page = {
            "prunedResult": {
                "parsing_res_list": [
                    {"block_label": "footnote", "block_content": "1. Already labeled footnote.", "block_order": 1, "block_bbox": [50, 700, 500, 750]},
                ]
            }
        }
        page_refs = {"1"}
        candidates = _detect_bottom_footnote_blocks(page, page_no=5, page_refs=page_refs)
        self.assertEqual(len(candidates), 0)

    def test_detect_high_marker_from_recent_marker_context(self):
        """当正文引用缺失时，高编号脚注可借助最近 marker 上下文识别。"""
        page = {
            "prunedResult": {
                "parsing_res_list": [
                    {"block_label": "text", "block_content": "Main body text.", "block_order": 1, "block_bbox": [50, 120, 500, 420]},
                    {"block_label": "text", "block_content": "37. High marker footnote content.", "block_order": 2, "block_bbox": [50, 760, 500, 820]},
                ]
            }
        }
        candidates = _detect_bottom_footnote_blocks(
            page,
            page_no=8,
            page_refs=set(),
            recent_numeric_marker=36,
        )
        self.assertEqual(len(candidates), 1)
        self.assertIn("37.", candidates[0]["block_content"])

    def test_detect_non_contiguous_bottom_markers(self):
        """页底出现跳号时，不应因为连续性不足而漏收。"""
        page = {
            "prunedResult": {
                "parsing_res_list": [
                    {"block_label": "text", "block_content": "Main body text.", "block_order": 1, "block_bbox": [50, 120, 500, 420]},
                    {"block_label": "text", "block_content": "3. Third note at page bottom.", "block_order": 2, "block_bbox": [50, 730, 500, 770]},
                    {"block_label": "text", "block_content": "9. Ninth note after numbering jump.", "block_order": 3, "block_bbox": [50, 790, 500, 840]},
                ]
            }
        }
        candidates = _detect_bottom_footnote_blocks(
            page,
            page_no=12,
            page_refs={"3"},
            expected_numeric_refs=[3],
        )
        self.assertEqual(len(candidates), 2)
        self.assertIn("3.", candidates[0]["block_content"])
        self.assertIn("9.", candidates[1]["block_content"])

    def test_detect_high_jump_marker_with_bottom_layout(self):
        """高编号跳号在页底且形态符合时，仍应识别为脚注候选。"""
        page = {
            "prunedResult": {
                "parsing_res_list": [
                    {"block_label": "text", "block_content": "Main body text.", "block_order": 1, "block_bbox": [50, 120, 500, 420]},
                    {"block_label": "text", "block_content": "128. High jump marker footnote content.", "block_order": 2, "block_bbox": [50, 840, 500, 900]},
                ]
            }
        }
        candidates = _detect_bottom_footnote_blocks(
            page,
            page_no=40,
            page_refs=set(),
            expected_numeric_refs=[12, 13, 14],
            recent_numeric_marker=14,
        )
        self.assertEqual(len(candidates), 1)
        self.assertIn("128.", candidates[0]["block_content"])

    def test_collect_footnotes_keeps_bottom_notes_when_markers_jump(self):
        """collect_footnotes 应允许跳号页底脚注进入 section.footnotes。"""
        section = Section(
            index=1,
            title="Chapter 1",
            section_id="sec-01-chapter-1",
            start_page=1,
            end_page=1,
            pages=[1],
            section_kind="body",
        )
        section.page_refs = {1: {"3"}}
        pages = [
            {
                "prunedResult": {
                    "parsing_res_list": [
                        {"block_label": "text", "block_content": "Main body text with ref 3.", "block_order": 1, "block_bbox": [50, 120, 500, 420]},
                        {"block_label": "text", "block_content": "3. Third note.", "block_order": 2, "block_bbox": [50, 730, 500, 770]},
                        {"block_label": "text", "block_content": "9. Ninth note after jump.", "block_order": 3, "block_bbox": [50, 790, 500, 840]},
                    ]
                }
            }
        ]

        collect_footnotes(section, pages)

        self.assertEqual(len(section.footnotes), 2)
        self.assertEqual([note.original_marker for note in section.footnotes], ["3", "9"])


class TestReferenceExtraction(unittest.TestCase):
    def test_extract_refs_supports_split_digits_and_bracket_numbers(self):
        refs = extract_refs("See argument6 7 and [68] for details.")
        self.assertIn("67", refs)
        self.assertIn("68", refs)


if __name__ == "__main__":
    unittest.main()

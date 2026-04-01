#!/usr/bin/env python3
"""前移脚注/尾注检测单元测试。"""

import unittest

from note_detection import NOTE_SCAN_VERSION, annotate_pages_with_note_scans


class NoteDetectionTest(unittest.TestCase):
    def test_detects_page_footnotes_from_fn_blocks(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph with marker [1].",
            "footnotes": "",
            "fnBlocks": [
                {"text": "1. First page note.", "bbox": [10, 900, 100, 930]},
                {"text": "2. Second page note.", "bbox": [10, 940, 100, 970]},
            ],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scanned[0]["_note_scan_version"], NOTE_SCAN_VERSION)
        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["kind"] for item in scan["items"]], ["footnote", "footnote"])
        self.assertEqual([item["number"] for item in scan["items"]], [1, 2])
        self.assertFalse(scan["reviewed_by_model"])

    def test_detects_mixed_body_endnotes_and_keeps_first_item(self):
        pages = [{
            "bookPage": 7,
            "markdown": "Closing body paragraph.\nNOTES\n1. first note line\n2. second note line",
            "footnotes": "",
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "mixed_body_endnotes")
        self.assertEqual(scan["note_start_line_index"], 1)
        self.assertEqual([item["number"] for item in scan["items"]], [1, 2])
        self.assertIn("NOTES", scan["section_hints"])

    def test_skips_isolated_dense_numbered_page_without_notes_signal(self):
        pages = [
            {
                "bookPage": 9,
                "markdown": "Regular body page.",
                "footnotes": "",
                "fnBlocks": [],
                "blocks": [],
            },
            {
                "bookPage": 10,
                "markdown": "\n".join([
                    "14. note fourteen",
                    "15. note fifteen",
                    "16. note sixteen",
                    "17. note seventeen",
                    "18. note eighteen",
                ]),
                "footnotes": "",
                "fnBlocks": [],
                "blocks": [],
            },
            {
                "bookPage": 11,
                "markdown": "Another regular body page.",
                "footnotes": "",
                "fnBlocks": [],
                "blocks": [],
            },
        ]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[1]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body")
        self.assertEqual(scan["items"], [])
        self.assertIn("isolated_numbered_page", scan["ambiguity_flags"])

    def test_only_ambiguous_page_triggers_reviewer(self):
        pages = [
            {
                "bookPage": 1,
                "markdown": "Clean body paragraph.",
                "footnotes": "",
                "fnBlocks": [],
                "blocks": [],
            },
            {
                "bookPage": 2,
                "markdown": "NOTES\nblurred OCR line",
                "footnotes": "",
                "fnBlocks": [],
                "blocks": [],
            },
        ]
        calls = []

        def _reviewer(*, page, prev_page, next_page, rule_scan):
            calls.append(page["bookPage"])
            return {
                "page_kind": "endnote_collection",
                "items": [
                    {
                        "kind": "endnote",
                        "marker": "1.",
                        "number": 1,
                        "text": "1. recovered note",
                        "order": 1,
                        "source": "model_review",
                        "confidence": 0.92,
                    }
                ],
                "section_hints": ["NOTES"],
                "ambiguity_flags": [],
            }

        scanned = annotate_pages_with_note_scans(pages, reviewer=_reviewer)

        self.assertEqual(calls, [2])
        self.assertFalse(scanned[0]["_note_scan"]["reviewed_by_model"])
        self.assertTrue(scanned[1]["_note_scan"]["reviewed_by_model"])
        self.assertEqual(scanned[1]["_note_scan"]["page_kind"], "endnote_collection")
        self.assertEqual(scanned[1]["_note_scan"]["items"][0]["number"], 1)


if __name__ == "__main__":
    unittest.main()

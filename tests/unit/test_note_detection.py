#!/usr/bin/env python3
"""前移脚注/尾注检测单元测试。"""

import unittest

from document.note_detection import NOTE_SCAN_VERSION, annotate_pages_with_note_scans


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

    def test_markdown_heading_notes_is_detected_as_mixed_body_endnotes(self):
        pages = [{
            "bookPage": 8,
            "markdown": "Closing body paragraph.\n## NOTES\n1. first note line\n2. second note line",
            "footnotes": "",
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "mixed_body_endnotes")
        self.assertEqual(scan["note_start_line_index"], 1)
        self.assertEqual([item["number"] for item in scan["items"]], [1, 2])

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

    def test_detects_comma_and_ocr_split_footnotes(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph.",
            "footnotes": "68, First note. 69. Second note.",
            "fnBlocks": [
                {"text": "132. Prior note.\n13 5. OCR split note.\n13 6. Next OCR split note.", "bbox": [10, 900, 100, 980]},
            ],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["number"] for item in scan["items"]], [132, 135, 136])

        pages_without_fn_blocks = [{
            "bookPage": 2,
            "markdown": "Body paragraph.",
            "footnotes": "68, First note. 69. Second note.",
            "fnBlocks": [],
            "blocks": [],
        }]
        scanned_without_fn_blocks = annotate_pages_with_note_scans(pages_without_fn_blocks)
        self.assertEqual(
            [item["number"] for item in scanned_without_fn_blocks[0]["_note_scan"]["items"]],
            [68, 69],
        )

    def test_trailing_marker_starts_new_footnote_item(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph.",
            "footnotes": "25. Prior note ends here. 26.\nIbid., p. 414.\n27. Next note.",
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual([item["number"] for item in scan["items"]], [25, 26, 27])
        self.assertIn("Ibid., p.", scan["items"][1]["text"])
        self.assertIn("414.", scan["items"][1]["text"])

    def test_embedded_marker_in_footnotes_text_is_recovered(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph with anchor [5].",
            "footnotes": (
                "spill spill spill spill spill spill spill spill spill spill "
                "5 What I here call brain-self differentiation remains recoverable."
            ),
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["number"] for item in scan["items"]], [5])
        self.assertIn("What I here call", scan["items"][0]["text"])

    def test_followup_marker_inside_same_footnotes_item_is_split(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph with anchors [46] [47].",
            "footnotes": (
                "46. Ibid., p. 197. , 47. Jean WAHL, Vers le concret. "
                "Études d'histoire de la philosophie contemporaine, Paris, Vrin, 1932."
            ),
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["number"] for item in scan["items"]], [46, 47])
        self.assertIn("Ibid., p. 197.", scan["items"][0]["text"])
        self.assertIn("Jean WAHL", scan["items"][1]["text"])

    def test_loose_marker_body_with_followup_marker_is_split(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph with anchors [7] [8].",
            "footnotes": (
                "7 Freud’s concept of the superego corresponds to the moral function of what "
                "Kant called reason when he characterized the mind by the categorical imperative. "
                "8 However, there is some debate about what Kant meant by innate."
            ),
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["number"] for item in scan["items"]], [7, 8])
        self.assertIn("categorical imperative", scan["items"][0]["text"])
        self.assertIn("what Kant meant by innate", scan["items"][1]["text"])

    def test_multiple_followup_markers_inside_same_footnotes_line_are_split(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph with anchors [106] [107] [108].",
            "footnotes": (
                "106. Sauf dans le cas de Kant und das Problem der Metaphysik, "
                "107. Martin HEIDEGGER, De l'essence de la vérité, trad. citée. "
                "Verbergung 108. Qui n'évite pas toujours le contresens."
            ),
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["number"] for item in scan["items"]], [106, 107, 108])

    def test_leading_noise_before_marker_is_recovered(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph with anchor [104].",
            "footnotes": "i 104. Voir ibid., pp. 94-95.",
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["number"] for item in scan["items"]], [104])

    def test_semicolon_and_leading_punctuation_markers_are_recovered(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph with anchors [38] [39] [16] [17].",
            "footnotes": (
                ".38. First recovered note.\n"
                "39. Second recovered note.\n"
                "16; Ibid., p. 42.\n"
                "'17. Next recovered note."
            ),
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["number"] for item in scan["items"]], [38, 39, 16, 17])

    def test_gap_lines_between_explicit_markers_are_synthesized_as_missing_notes(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph with anchors [13] [14] [15].",
            "footnotes": (
                "13. Ibid., p. 134.\n"
                "ad^ ybid^\\  ^ ace]acf^\n"
                "15. J. Goldstein, Consoler et classifier, op. cit., p. 220."
            ),
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["number"] for item in scan["items"]], [13, 14, 15])

    def test_trailing_garbled_line_after_last_marker_is_synthesized(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph with anchors [57] [58].",
            "footnotes": (
                "57. Ibid., p. 299.\n"
                "eh^ ybid^\\  ^ bic]bid^"
            ),
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["number"] for item in scan["items"]], [57, 58])

    def test_leading_garbled_line_before_next_marker_uses_previous_marker_gap(self):
        pages = [{
            "bookPage": 1,
            "markdown": "Body paragraph with anchors [91] [92] [93].",
            "footnotes": (
                "91. Prior note.\n"
                "ib^ ybid^\\  ^ eba]ebb^\n"
                "93. Ibid., p. 523."
            ),
            "fnBlocks": [],
            "blocks": [],
        }]

        scanned = annotate_pages_with_note_scans(pages)
        scan = scanned[0]["_note_scan"]

        self.assertEqual(scan["page_kind"], "body_with_page_footnotes")
        self.assertEqual([item["number"] for item in scan["items"]], [91, 92, 93])

    def test_illustration_list_is_not_misclassified_as_endnotes(self):
        pages = [
            {
                "bookPage": 1,
                "markdown": (
                    "# Liste des illustrations\n"
                    "1. Gravure. Musée Carnavalet. © Musée Carnavalet\n"
                    "2. Eau-forte, 13,5 cm. Bibliothèque nationale."
                ),
                "footnotes": "",
                "fnBlocks": [],
                "blocks": [],
            },
            {
                "bookPage": 2,
                "markdown": (
                    "10. Huile sur toile. Musée du Louvre. © RMN\n"
                    "11. Lithographie. Bibliothèque nationale de France."
                ),
                "footnotes": "",
                "fnBlocks": [],
                "blocks": [],
            },
        ]

        scanned = annotate_pages_with_note_scans(pages)
        self.assertEqual(scanned[0]["_note_scan"]["page_kind"], "body")
        self.assertEqual(scanned[1]["_note_scan"]["page_kind"], "body")
        self.assertFalse(scanned[0]["_note_scan"]["items"])
        self.assertFalse(scanned[1]["_note_scan"]["items"])


if __name__ == "__main__":
    unittest.main()

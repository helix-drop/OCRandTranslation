from __future__ import annotations

import unittest

from FNM_RE.shared.notes import parse_note_items_from_text


class SharedNoteParserTest(unittest.TestCase):
    def test_page_citation_abbreviations_do_not_split_inline_followup_notes(self):
        text = (
            "13. See Charles Landesman, Jr., \"Consciousness,\" in The Encyclopedia of "
            "Philosophy, 2: 191-95, esp. 192, and Eric Lormand, \"Consciousness,\" "
            "2: 581-96, esp. 590.\n"
            "14. Next real note."
        )

        items, _ = parse_note_items_from_text(text)

        self.assertEqual([item["marker"] for item in items], ["13", "14"])

    def test_paragraph_and_folio_citations_do_not_become_note_markers(self):
        text = (
            "36. See Pascal, Oeuvres completes, para. 130, p. 1123; para. 136, "
            "pp. 1126-27; para. 443, p. 1211.\n"
            "37. See Oxford English Dictionary.\n"
            "97. Renan, fol. 556, Summary of Cousin's Lesson 4.\n"
            "98. Ibid., fols. 554-554v."
        )

        items, _ = parse_note_items_from_text(text)

        self.assertEqual([item["marker"] for item in items], ["36", "37", "97", "98"])

    def test_large_dossier_number_continuation_does_not_start_new_note(self):
        text = (
            "93. AN: BB18 1242, doss.\n"
            "4359, letter of 21 January 1837.\n"
            "94. Procureur general, Cour royale de Lyon."
        )

        items, _ = parse_note_items_from_text(text)

        self.assertEqual([item["marker"] for item in items], ["93", "94"])
        self.assertIn("4359, letter", items[0]["text"])

    def test_note_body_starting_with_number_does_not_merge_into_previous_marker(self):
        text = (
            "24. Prior note.\n"
            "25 1. von Mises, quoted passage.\n"
            "26.\n"
            "1. von Mises, second quoted passage.\n"
            "27. Following note."
        )

        items, _ = parse_note_items_from_text(text)

        self.assertEqual([item["marker"] for item in items], ["24", "25", "26", "27"])
        self.assertIn("1. von Mises", items[1]["text"])
        self.assertIn("1. von Mises", items[2]["text"])

    def test_noisy_next_note_line_reconstructs_expected_marker(self):
        text = (
            "30. Previous complete note.\n"
            "!! 3er la distinction entre les actions conformes et non conformes.\n"
            "32. Following note."
        )

        items, _ = parse_note_items_from_text(text)

        self.assertEqual([item["marker"] for item in items], ["30", "31", "32"])
        self.assertIn("la distinction", items[1]["text"])
        self.assertTrue(items[1]["is_reconstructed"])


if __name__ == "__main__":
    unittest.main()

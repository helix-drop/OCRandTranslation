#!/usr/bin/env python3
"""自动视觉目录纯逻辑测试。"""

import unittest

from visual_toc import (
    _classify_header_hint,
    _choose_local_toc_scan_indices,
    _score_local_toc_page,
    _vision_probe_passed,
    choose_toc_candidate_indices,
    filter_visual_toc_items,
    map_visual_items_to_link_targets,
    pick_best_toc_cluster,
)


class VisualTocLogicTest(unittest.TestCase):
    def test_choose_toc_candidate_indices_scans_front_and_back(self):
        front, back = choose_toc_candidate_indices(120)

        self.assertGreaterEqual(len(front), 8)
        self.assertGreaterEqual(len(back), 8)
        self.assertEqual(front[0], 0)
        self.assertEqual(back[-1], 119)
        self.assertLess(front[-1], back[0])

    def test_pick_best_toc_cluster_prefers_higher_scoring_back_cluster(self):
        best = pick_best_toc_cluster(
            [
                {"file_idx": 2, "label": "toc_start", "score": 0.61},
                {"file_idx": 3, "label": "toc_continue", "score": 0.67},
            ],
            [
                {"file_idx": 180, "label": "toc_start", "score": 0.89},
                {"file_idx": 181, "label": "toc_continue", "score": 0.92},
                {"file_idx": 182, "label": "toc_continue", "score": 0.88},
            ],
        )

        self.assertEqual([item["file_idx"] for item in best], [180, 181, 182])

    def test_pick_best_toc_cluster_prefers_explicit_table_header_over_longer_index_cluster(self):
        best = pick_best_toc_cluster(
            [],
            [
                {"file_idx": 348, "label": "toc_start", "score": 0.95, "header_hint": "Indices"},
                {"file_idx": 349, "label": "toc_continue", "score": 0.90, "header_hint": "Index des notions"},
                {"file_idx": 350, "label": "toc_continue", "score": 0.98, "header_hint": ""},
                {"file_idx": 351, "label": "toc_continue", "score": 0.92, "header_hint": ""},
                {"file_idx": 352, "label": "toc_continue", "score": 0.91, "header_hint": ""},
                {"file_idx": 353, "label": "toc_continue", "score": 0.89, "header_hint": ""},
                {"file_idx": 363, "label": "toc_start", "score": 0.90, "header_hint": "Table"},
                {"file_idx": 364, "label": "toc_continue", "score": 0.90, "header_hint": ""},
                {"file_idx": 365, "label": "toc_continue", "score": 0.90, "header_hint": ""},
                {"file_idx": 366, "label": "toc_continue", "score": 0.95, "header_hint": ""},
            ],
        )

        self.assertEqual([item["file_idx"] for item in best], [363, 364, 365, 366])

    def test_classify_header_hint_supports_multilingual_toc_titles(self):
        self.assertEqual(_classify_header_hint("Table"), "toc")
        self.assertEqual(_classify_header_hint("Table des matières"), "toc")
        self.assertEqual(_classify_header_hint("Sommaire"), "toc")
        self.assertEqual(_classify_header_hint("Contents"), "toc")
        self.assertEqual(_classify_header_hint("目录"), "toc")
        self.assertEqual(_classify_header_hint("目次"), "toc")
        self.assertEqual(_classify_header_hint("Índice"), "toc")
        self.assertEqual(_classify_header_hint("Indice"), "toc")
        self.assertEqual(_classify_header_hint("Sumário"), "toc")
        self.assertEqual(_classify_header_hint("Содержание"), "toc")

    def test_classify_header_hint_keeps_index_trap_and_notebook_sections_out(self):
        self.assertEqual(_classify_header_hint("Index"), "index")
        self.assertEqual(_classify_header_hint("Indices"), "index")
        self.assertEqual(_classify_header_hint("Index des notions"), "index")
        self.assertEqual(_classify_header_hint("Notes"), "other")
        self.assertEqual(_classify_header_hint("Bibliography"), "other")

    def test_score_local_toc_page_distinguishes_indice_from_index(self):
        toc_score = _score_local_toc_page(
            {
                "file_idx": 12,
                "header_hint": "Índice",
                "text_excerpt": "Índice\nCapítulo 1 .... 7\nCapítulo 2 .... 19",
                "link_count": 0,
                "dot_leader_lines": 2,
                "numbered_lines": 2,
            }
        )
        index_score = _score_local_toc_page(
            {
                "file_idx": 340,
                "header_hint": "Index",
                "text_excerpt": "Index of names\nFoucault .... 399",
                "link_count": 0,
                "dot_leader_lines": 1,
                "numbered_lines": 1,
            }
        )

        self.assertGreater(toc_score, 0)
        self.assertLess(index_score, 0)

    def test_choose_local_toc_scan_indices_prefers_table_cluster_and_caps_pages(self):
        features = [
            {
                "file_idx": 348,
                "header_hint": "Indices",
                "text_excerpt": "Indices\nIndex des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 349,
                "header_hint": "Index des notions",
                "text_excerpt": "Index des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 350,
                "header_hint": "",
                "text_excerpt": "Index des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 351,
                "header_hint": "",
                "text_excerpt": "Index des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 352,
                "header_hint": "",
                "text_excerpt": "Index des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 353,
                "header_hint": "",
                "text_excerpt": "Index des notions",
                "link_count": 0,
                "dot_leader_lines": 4,
                "numbered_lines": 5,
            },
            {
                "file_idx": 362,
                "header_hint": "Table",
                "text_excerpt": "Table\nCours, année 1978-1979 .... 1",
                "link_count": 0,
                "dot_leader_lines": 5,
                "numbered_lines": 5,
            },
            {
                "file_idx": 363,
                "header_hint": "",
                "text_excerpt": "Leçon du 10 janvier 1979 .... 3",
                "link_count": 0,
                "dot_leader_lines": 5,
                "numbered_lines": 5,
            },
            {
                "file_idx": 364,
                "header_hint": "Table",
                "text_excerpt": "Table\nLeçon du 24 janvier 1979 .... 67",
                "link_count": 0,
                "dot_leader_lines": 5,
                "numbered_lines": 5,
            },
            {
                "file_idx": 365,
                "header_hint": "",
                "text_excerpt": "Leçon du 7 février 1979 .... 119",
                "link_count": 0,
                "dot_leader_lines": 5,
                "numbered_lines": 5,
            },
            {
                "file_idx": 366,
                "header_hint": "Table",
                "text_excerpt": "Table\nRésumé du cours .... 323",
                "link_count": 0,
                "dot_leader_lines": 5,
                "numbered_lines": 5,
            },
        ]

        self.assertEqual(_choose_local_toc_scan_indices(features, max_pages=6), [362, 363, 364, 365, 366])

    def test_choose_local_toc_scan_indices_bridges_low_signal_pages_between_table_headers(self):
        features = [
            {
                "file_idx": 362,
                "header_hint": "Table",
                "text_excerpt": "Table",
                "link_count": 0,
                "dot_leader_lines": 0,
                "numbered_lines": 0,
            },
            {
                "file_idx": 363,
                "header_hint": "352",
                "text_excerpt": "352\nNaissance de la biopolitique",
                "link_count": 0,
                "dot_leader_lines": 0,
                "numbered_lines": 0,
            },
            {
                "file_idx": 364,
                "header_hint": "Table",
                "text_excerpt": "Table",
                "link_count": 0,
                "dot_leader_lines": 0,
                "numbered_lines": 0,
            },
            {
                "file_idx": 365,
                "header_hint": "354",
                "text_excerpt": "354\nNaissance de la biopolitique",
                "link_count": 0,
                "dot_leader_lines": 0,
                "numbered_lines": 0,
            },
            {
                "file_idx": 366,
                "header_hint": "Table",
                "text_excerpt": "Table",
                "link_count": 0,
                "dot_leader_lines": 0,
                "numbered_lines": 0,
            },
        ]

        self.assertEqual(_choose_local_toc_scan_indices(features, max_pages=6), [362, 363, 364, 365, 366])

    def test_filter_visual_toc_items_ignores_container_titles_and_summary_blocks(self):
        items = filter_visual_toc_items(
            [
                {"title": "Table des matieres", "depth": 0, "printed_page": None, "visual_order": 1},
                {
                    "title": "Lecon du 10 janvier 1979",
                    "depth": 0,
                    "printed_page": 51,
                    "visual_order": 2,
                },
                {
                    "title": "Dans cette lecon Foucault resume longuement les problemes generaux de la raison d'Etat et de la gouvernementalite liberale.",
                    "depth": 1,
                    "printed_page": None,
                    "visual_order": 3,
                },
                {
                    "title": "1. Liberalism",
                    "depth": 1,
                    "printed_page": 61,
                    "visual_order": 4,
                },
            ]
        )

        self.assertEqual(
            [item["title"] for item in items],
            ["Lecon du 10 janvier 1979", "1. Liberalism"],
        )

    def test_filter_visual_toc_items_keeps_real_index_entry_when_it_has_a_page(self):
        items = filter_visual_toc_items(
            [
                {"title": "Index", "depth": 0, "printed_page": 411, "visual_order": 1},
            ]
        )

        self.assertEqual(items[0]["title"], "Index")
        self.assertEqual(items[0]["printed_page"], 411)

    def test_map_visual_items_to_link_targets_uses_visual_order_for_link_only_toc(self):
        mapped = map_visual_items_to_link_targets(
            [
                {"title": "Introduction", "depth": 0, "printed_page": None, "visual_order": 1},
                {"title": "Chapter 1", "depth": 0, "printed_page": None, "visual_order": 2},
            ],
            [
                {"visual_order": 1, "target_file_idx": 7},
                {"visual_order": 2, "target_file_idx": 19},
            ],
        )

        self.assertEqual(mapped[0]["file_idx"], 7)
        self.assertEqual(mapped[1]["file_idx"], 19)

    def test_vision_probe_accepts_relation_match_instead_of_exact_pixel_count(self):
        self.assertTrue(_vision_probe_passed([2, 4, 0, 2], True))
        self.assertFalse(_vision_probe_passed([2, 2, 1, 2], True))


if __name__ == "__main__":
    unittest.main()

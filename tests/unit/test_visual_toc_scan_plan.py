import unittest

from tests.unit.visual_toc_cases import VisualTocLogicTest as _Base


def _attach_selected_tests(target_cls: type[unittest.TestCase], names: list[str]) -> None:
    for name in names:
        setattr(target_cls, name, getattr(_Base, name))


class VisualTocScanPlanTest(unittest.TestCase):
    pass


_attach_selected_tests(
    VisualTocScanPlanTest,
    [
        "test_choose_toc_candidate_indices_scans_front_and_back",
        "test_pick_best_toc_cluster_prefers_higher_scoring_back_cluster",
        "test_pick_best_toc_cluster_prefers_explicit_table_header_over_longer_index_cluster",
        "test_classify_header_hint_supports_multilingual_toc_titles",
        "test_classify_header_hint_keeps_index_trap_and_notebook_sections_out",
        "test_score_local_toc_page_distinguishes_indice_from_index",
        "test_choose_local_toc_scan_indices_prefers_table_cluster_and_caps_pages",
        "test_choose_local_toc_scan_indices_bridges_low_signal_pages_between_table_headers",
        "test_assess_text_layer_quality_switches_to_degraded_when_control_chars_high",
        "test_build_visual_scan_plan_uses_front6_back12_for_degraded_mode",
        "test_expand_candidate_indices_for_retry_adds_neighbor_pages",
        "test_build_local_scan_plan_exposes_multi_run_summaries",
        "test_build_coverage_quality_summary_marks_partial_capture",
        "test_vision_probe_accepts_relation_match_instead_of_exact_pixel_count",
    ],
)

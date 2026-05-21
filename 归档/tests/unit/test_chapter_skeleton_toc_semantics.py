import unittest

from tests.unit.fnm_re_phase1_cases import FnmRePhase1Test as _Base


def _attach_selected_tests(target_cls: type[unittest.TestCase], names: list[str]) -> None:
    for name in names:
        setattr(target_cls, name, getattr(_Base, name))


class ChapterSkeletonTocSemanticsTest(unittest.TestCase):
    pass


_attach_selected_tests(
    ChapterSkeletonTocSemanticsTest,
    [
        "test_visual_toc_level_uses_role_hint_and_semantic_depth",
        "test_visual_toc_chapter_boundary_stops_before_back_matter_start",
        "test_phase1_semantic_depth_keeps_endnotes_out_of_chapter_tree",
        "test_phase1_treats_explicit_part_role_as_container_not_chapter",
        "test_goldstein_visual_toc_filters_composite_root_duplicate",
        "test_germany_madness_visual_toc_keeps_all_top_level_chapters",
        "test_heidegger_visual_toc_demotes_back_matter_subsections",
        "test_neuro_intro_sample_clean_visual_toc_exports_all_chapters",
        "test_neuro_intro_visual_toc_prefers_clean_titles_over_number_noise",
    ],
)

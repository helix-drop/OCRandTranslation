import unittest

from tests.unit.fnm_re_phase1_cases import FnmRePhase1Test as _Base


def _attach_selected_tests(target_cls: type[unittest.TestCase], names: list[str]) -> None:
    for name in names:
        setattr(target_cls, name, getattr(_Base, name))


class FnmRePhase1RegressionTest(unittest.TestCase):
    pass


_attach_selected_tests(
    FnmRePhase1RegressionTest,
    [
        "test_page_partition_marks_rear_toc_tail_and_author_blurb_as_other",
        "test_page_partition_marks_note_continuation_as_note",
        "test_page_partition_keeps_illustration_list_continuation_as_other",
        "test_page_partition_keeps_bibliography_remarks_tail_as_other",
        "test_page_partition_recovers_early_front_matter_continuation",
        "test_biopolitics_exports_lectures_plus_post_body_titles_without_container_as_chapter",
        "test_phase1_summary_accepts_visual_toc_endnotes_summary",
        "test_phase1_summary_defaults_visual_toc_endnotes_summary_to_empty",
        "test_heading_graph_residual_provisional_does_not_block_phase1",
        "test_mad_act_keeps_part_containers_and_exports_appendices",
        "test_napoleon_last_chapter_stops_before_rear_back_matter",
        "test_nip_manual_outline_keeps_part_i_to_iv_container_semantics",
        "test_phase1_smoke_for_remaining_sample_books_returns_non_empty_chapters",
        "test_goldstein_phase1_preserves_endnotes_role_in_visual_toc",
        "test_germany_madness_visual_toc_keeps_all_top_level_chapters",
        "test_heidegger_manual_visual_toc_does_not_keep_obvious_garbled_titles",
        "test_neuro_intro_heading_graph_flags_same_page_anchor_conflict",
        "test_neuro_intro_sample_clean_visual_toc_exports_all_chapters",
        "test_napoleon_heading_graph_resolves_long_french_titles_without_residual_provisional",
    ],
)

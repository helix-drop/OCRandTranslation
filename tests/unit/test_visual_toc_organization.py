import unittest

from tests.unit.visual_toc_cases import VisualTocLogicTest as _Base


def _attach_selected_tests(target_cls: type[unittest.TestCase], names: list[str]) -> None:
    for name in names:
        setattr(target_cls, name, getattr(_Base, name))


class VisualTocOrganizationTest(unittest.TestCase):
    pass


_attach_selected_tests(
    VisualTocOrganizationTest,
    [
        "test_extract_visual_toc_organization_bundle_defaults_missing_endnotes_summary",
        "test_extract_visual_toc_organization_bundle_appends_trace_with_derived_truth",
        "test_filter_visual_toc_items_ignores_container_titles_and_summary_blocks",
        "test_filter_visual_toc_items_keeps_role_hinted_container_and_post_body_without_pages",
        "test_filter_visual_toc_items_keeps_part_one_container_without_page",
        "test_normalize_visual_toc_role_hint_accepts_container_aliases_and_book_matter_aliases",
        "test_annotate_visual_toc_organization_marks_container_post_body_and_export_candidates",
        "test_annotate_visual_toc_organization_promotes_container_children_and_roman_root",
        "test_annotate_visual_toc_organization_overrides_explicit_part_root_to_container",
        "test_annotate_visual_toc_organization_overrides_explicit_roman_roots_with_children",
        "test_annotate_visual_toc_organization_normalizes_semantic_depth_for_endnotes_and_container_children",
        "test_annotate_visual_toc_organization_promotes_semantic_container_titles_even_if_prompt_marks_back_matter",
        "test_annotate_visual_toc_organization_demotes_long_root_book_title_before_containers",
        "test_filter_visual_toc_items_keeps_real_index_entry_when_it_has_a_page",
        "test_map_visual_items_to_link_targets_uses_visual_order_for_link_only_toc",
        "test_filter_resolved_visual_toc_anomalies_drops_tail_introduction_outlier",
        "test_filter_resolved_visual_toc_anomalies_drops_large_reverse_jump_between_neighbors",
        "test_filter_resolved_visual_toc_anomalies_drops_notes_range_reverse_jump",
        "test_filter_resolved_visual_toc_anomalies_drops_note_on_sources_reverse_jump",
    ],
)

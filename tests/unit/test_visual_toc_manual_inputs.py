import unittest

from tests.unit.visual_toc_cases import VisualTocLogicTest as _Base


def _attach_selected_tests(target_cls: type[unittest.TestCase], names: list[str]) -> None:
    for name in names:
        setattr(target_cls, name, getattr(_Base, name))


class VisualTocManualInputsTest(unittest.TestCase):
    pass


_attach_selected_tests(
    VisualTocManualInputsTest,
    [
        "test_merge_manual_toc_organization_nodes_skips_garbled_outline_rows",
        "test_merge_manual_toc_organization_nodes_skips_goldstein_like_container_chapter_composite_row",
        "test_merge_manual_toc_organization_nodes_prefers_clean_page_matched_title_over_garbled_outline",
        "test_merge_manual_toc_organization_nodes_preserves_missing_containers_and_page_matches",
        "test_merge_manual_toc_organization_nodes_reinserts_missing_middle_body_rows_in_order",
        "test_augment_manual_toc_organization_with_ocr_containers_injects_missing_parts",
        "test_augment_manual_toc_organization_with_ocr_containers_normalizes_roman_noise",
        "test_augment_manual_toc_organization_with_ocr_containers_normalizes_part_ocr_noise",
        "test_extract_manual_toc_outline_nodes_from_pdf_text_recovers_missing_container_and_chapters",
        "test_extract_manual_toc_outline_nodes_keeps_part_container_after_acknowledgments",
        "test_extract_manual_toc_outline_nodes_keeps_appendix_children_under_post_body",
        "test_extract_manual_toc_outline_nodes_keeps_endnotes_as_container_not_epilogue_section",
        "test_should_prefer_manual_outline_nodes_when_outline_recovers_missing_containers",
        "test_generate_visual_toc_manual_pdf_uses_outline_as_primary_items_when_outline_is_more_complete",
    ],
)

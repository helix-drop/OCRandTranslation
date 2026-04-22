import unittest

from tests.unit.visual_toc_cases import VisualTocLogicTest as _Base


def _attach_selected_tests(target_cls: type[unittest.TestCase], names: list[str]) -> None:
    for name in names:
        setattr(target_cls, name, getattr(_Base, name))


class VisualTocRuntimeTest(unittest.TestCase):
    pass


_attach_selected_tests(
    VisualTocRuntimeTest,
    [
        "test_generate_visual_toc_retry_failure_writes_structured_reason_code",
        "test_generate_visual_toc_prefers_manual_toc_pdf_over_pdf_page_scan",
        "test_generate_visual_toc_manual_pdf_marks_ready_when_only_container_lacks_page_target",
        "test_call_vision_json_returns_trace_without_inline_base64",
        "test_generate_auto_visual_toc_infers_endnotes_summary_from_final_items_when_prompt_misses_it",
        "test_generate_visual_toc_fails_fast_when_visual_call_returns_non_retryable_400",
    ],
)

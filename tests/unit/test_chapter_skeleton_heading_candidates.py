import unittest

from tests.unit.fnm_re_phase1_cases import FnmRePhase1Test as _Base


def _attach_selected_tests(target_cls: type[unittest.TestCase], names: list[str]) -> None:
    for name in names:
        setattr(target_cls, name, getattr(_Base, name))


class ChapterSkeletonHeadingCandidatesTest(unittest.TestCase):
    pass


_attach_selected_tests(
    ChapterSkeletonHeadingCandidatesTest,
    [
        "test_fallback_does_not_promote_sentence_like_paragraph_title_to_chapter",
        "test_section_heads_keep_suppressed_candidates_with_reject_reason",
    ],
)

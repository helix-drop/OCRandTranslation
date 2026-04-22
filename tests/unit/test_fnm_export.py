#!/usr/bin/env python3
"""FNM 导出回归（从 phase6 拆分出来的兼容测试入口）。"""

from __future__ import annotations

import unittest

from tests.unit.test_fnm_re_phase6 import FnmRePhase6Test


EXPORT_TEST_NAMES = (
    "test_phase6_modules_do_not_depend_on_legacy_export_wrappers",
    "test_build_phase6_outputs_bundle_index_and_chapter_files",
    "test_body_text_priority_manual_then_diagnostic_machine_then_pending",
    "test_only_referenced_notes_are_exported_as_definitions",
    "test_raw_bracket_and_superscript_markers_are_rewritten_to_local_refs",
    "test_non_exportable_section_heads_are_filtered_out",
    "test_trailing_image_only_block_removed",
    "test_phase6_status_projects_chapter_and_note_region_progress",
    "test_phase6_status_export_drift_summary_counts_legacy_and_orphans",
    "test_export_ready_flags_follow_audit_and_contract",
    "test_phase6_keeps_phase5_fields_and_does_not_mutate_phase5_truth",
)


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for name in EXPORT_TEST_NAMES:
        suite.addTest(FnmRePhase6Test(name))
    return suite


if __name__ == "__main__":
    unittest.main()

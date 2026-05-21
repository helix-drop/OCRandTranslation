#!/usr/bin/env python3
"""FNM 导出审计回归（从 phase6 拆分出来的兼容测试入口）。"""

from __future__ import annotations

import unittest

from tests.unit.test_fnm_re_phase6 import FnmRePhase6Test


EXPORT_AUDIT_TEST_NAMES = (
    "test_audit_missing_post_body_export_is_blocking",
    "test_audit_container_exported_as_chapter_is_blocking",
    "test_audit_export_depth_too_shallow_is_blocking",
)


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for name in EXPORT_AUDIT_TEST_NAMES:
        suite.addTest(FnmRePhase6Test(name))
    return suite


if __name__ == "__main__":
    unittest.main()

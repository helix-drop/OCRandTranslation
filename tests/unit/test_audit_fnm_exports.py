#!/usr/bin/env python3
"""FNM 导出抽样审计脚本测试。"""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_fnm_exports.py"
SCRIPT_NS = runpy.run_path(str(SCRIPT_PATH))

split_body = SCRIPT_NS["_split_body_and_definitions"]
body_paragraphs = SCRIPT_NS["_body_paragraphs"]
definition_lines = SCRIPT_NS["_definition_lines"]


class AuditFnmExportsScriptTest(unittest.TestCase):
    def test_split_body_and_definitions_separates_definition_block(self):
        body, defs = split_body("Body [^1].\n\n[^1]: Note one.\n[^2]: Note two.\n")
        self.assertIn("Body [^1].", body)
        self.assertIn("[^1]: Note one.", defs)
        self.assertIn("[^2]: Note two.", defs)

    def test_body_paragraphs_skips_section_headings(self):
        paragraphs = body_paragraphs("### Intro\n\nBody one.\n\nBody two.\n\n[^1]: Note.\n")
        self.assertEqual(paragraphs, ["Body one.", "Body two."])

    def test_definition_lines_returns_non_empty_lines(self):
        defs = definition_lines("Body.\n\n[^1]: Note one.\n    continued.\n")
        self.assertEqual(defs, ["[^1]: Note one.", "    continued."])


if __name__ == "__main__":
    unittest.main()

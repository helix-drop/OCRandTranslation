"""守护 document_tasks 到 task_document_pipeline 的依赖映射完整性。"""

from __future__ import annotations

import unittest

import pipeline.document_tasks as document_tasks


class DocumentTasksDepsTest(unittest.TestCase):
    def test_document_pipeline_deps_contains_required_state_hooks(self) -> None:
        deps = document_tasks._document_pipeline_deps()
        self.assertIn("update_doc_meta", deps)
        self.assertIn("parse_glossary_file", deps)
        self.assertIn("set_glossary", deps)


if __name__ == "__main__":
    unittest.main()

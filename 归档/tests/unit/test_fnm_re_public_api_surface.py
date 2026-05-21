from __future__ import annotations

import importlib
import unittest


GENERIC_PUBLIC_APIS = (
    "run_doc_pipeline",
    "load_doc_structure",
    "build_doc_status",
    "build_export_bundle_for_doc",
    "build_export_zip_for_doc",
    "audit_export_for_doc",
    "list_diagnostic_entries_for_doc",
    "get_diagnostic_entry_for_page",
    "list_diagnostic_notes_for_doc",
)

PHASE_ONLY_APIS = (
    "build_phase1_structure",
    "build_phase2_structure",
    "build_phase3_structure",
    "build_phase4_structure",
    "build_phase5_structure",
    "build_phase6_structure",
    "run_phase6_pipeline_for_doc",
    "load_phase6_for_doc",
    "build_phase6_status_for_doc",
    "build_phase6_export_bundle_for_doc",
    "build_phase6_export_zip_for_doc",
    "audit_phase6_export_for_doc",
    "list_phase6_diagnostic_entries_for_doc",
    "list_phase6_diagnostic_notes_for_doc",
)


class FnmRePublicApiSurfaceTest(unittest.TestCase):
    def test_generic_api_remains_importable(self):
        fnm_re = importlib.import_module("FNM_RE")
        fnm_re_app = importlib.import_module("FNM_RE.app")

        for name in GENERIC_PUBLIC_APIS:
            self.assertIn(name, fnm_re.__all__, msg=f"FNM_RE.__all__ 缺少 {name}")
            self.assertTrue(hasattr(fnm_re, name), msg=f"FNM_RE 缺少 {name}")
            self.assertIn(name, fnm_re_app.__all__, msg=f"FNM_RE.app.__all__ 缺少 {name}")
            self.assertTrue(hasattr(fnm_re_app, name), msg=f"FNM_RE.app 缺少 {name}")

    def test_phase_only_api_no_longer_public(self):
        fnm_re = importlib.import_module("FNM_RE")
        fnm_re_app = importlib.import_module("FNM_RE.app")

        for name in PHASE_ONLY_APIS:
            self.assertNotIn(name, fnm_re.__all__, msg=f"FNM_RE.__all__ 仍暴露 {name}")
            self.assertFalse(hasattr(fnm_re, name), msg=f"FNM_RE 仍暴露 {name}")
            self.assertNotIn(name, fnm_re_app.__all__, msg=f"FNM_RE.app.__all__ 仍暴露 {name}")
            self.assertFalse(hasattr(fnm_re_app, name), msg=f"FNM_RE.app 仍暴露 {name}")

            with self.assertRaises(ImportError):
                exec(f"from FNM_RE import {name}", {})
            with self.assertRaises(ImportError):
                exec(f"from FNM_RE.app import {name}", {})


if __name__ == "__main__":
    unittest.main()

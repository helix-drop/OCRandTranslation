"""FNM_RE 对外入口。"""

from FNM_RE.app.mainline import (
    audit_phase6_export_for_doc as audit_export_for_doc,
    build_phase6_export_bundle_for_doc as build_export_bundle_for_doc,
    build_phase6_export_zip_for_doc as build_export_zip_for_doc,
    build_phase6_status_for_doc as build_doc_status,
    get_phase6_diagnostic_entry_for_doc as get_diagnostic_entry_for_page,
    list_phase6_diagnostic_entries_for_doc as list_diagnostic_entries_for_doc,
    list_phase6_diagnostic_notes_for_doc as list_diagnostic_notes_for_doc,
    load_phase6_for_doc as load_doc_structure,
    run_phase6_pipeline_for_doc as run_doc_pipeline,
)

__all__ = [
    "run_doc_pipeline",
    "load_doc_structure",
    "build_doc_status",
    "build_export_bundle_for_doc",
    "build_export_zip_for_doc",
    "audit_export_for_doc",
    "list_diagnostic_notes_for_doc",
    "list_diagnostic_entries_for_doc",
    "get_diagnostic_entry_for_page",
]

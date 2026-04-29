"""FNM_RE 对外入口。"""

from __future__ import annotations


def prepare_page_translate_jobs(*args, **kwargs):
    from FNM_RE.page_translate import prepare_page_translate_jobs as impl

    return impl(*args, **kwargs)


def build_retry_summary(*args, **kwargs):
    from FNM_RE.page_translate import build_retry_summary as impl

    return impl(*args, **kwargs)


def build_unit_progress(*args, **kwargs):
    from FNM_RE.page_translate import build_unit_progress as impl

    return impl(*args, **kwargs)


def run_llm_repair(*args, **kwargs):
    from FNM_RE.llm_repair import request_llm_repair_actions as impl

    return impl(*args, **kwargs)


def group_review_overrides(*args, **kwargs):
    from FNM_RE.shared.review_overrides import group_review_overrides as impl

    return impl(*args, **kwargs)


def annotate_review_note_links(*args, **kwargs):
    from FNM_RE.review import annotate_review_note_links as impl

    return impl(*args, **kwargs)


def collect_llm_suggestions(*args, **kwargs):
    from FNM_RE.review import collect_llm_suggestions as impl

    return impl(*args, **kwargs)


def build_toc_structure(*args, **kwargs):
    from FNM_RE.modules.toc_structure import build_toc_structure as impl

    return impl(*args, **kwargs)


def build_book_note_profile(*args, **kwargs):
    from FNM_RE.modules.book_note_type import build_book_note_profile as impl

    return impl(*args, **kwargs)


def build_chapter_layers(*args, **kwargs):
    from FNM_RE.modules.chapter_split import build_chapter_layers as impl

    return impl(*args, **kwargs)


def build_note_link_table(*args, **kwargs):
    from FNM_RE.modules.note_linking import build_note_link_table as impl

    return impl(*args, **kwargs)


def build_frozen_units(*args, **kwargs):
    from FNM_RE.modules.ref_freeze import build_frozen_units as impl

    return impl(*args, **kwargs)


def build_chapter_markdown_set(*args, **kwargs):
    from FNM_RE.modules.chapter_merge import build_chapter_markdown_set as impl

    return impl(*args, **kwargs)


def build_export_bundle(*args, **kwargs):
    from FNM_RE.modules.book_assemble import build_export_bundle as impl

    return impl(*args, **kwargs)


def run_doc_pipeline(*args, **kwargs):
    from FNM_RE.app.mainline import run_phase6_pipeline_for_doc as impl

    return impl(*args, **kwargs)


def load_doc_structure(*args, **kwargs):
    from FNM_RE.app.mainline import load_phase6_for_doc as impl

    return impl(*args, **kwargs)


def build_doc_status(*args, **kwargs):
    from FNM_RE.app.mainline import build_phase6_status_for_doc as impl

    return impl(*args, **kwargs)


def build_export_bundle_for_doc(*args, **kwargs):
    from FNM_RE.app.mainline import build_phase6_export_bundle_for_doc as impl

    return impl(*args, **kwargs)


def build_export_zip_for_doc(*args, **kwargs):
    from FNM_RE.app.mainline import build_phase6_export_zip_for_doc as impl

    return impl(*args, **kwargs)


def run_post_translate_export_checks_for_doc(*args, **kwargs):
    from FNM_RE.app.mainline import run_post_translate_export_checks_for_doc as impl

    return impl(*args, **kwargs)


def audit_export_for_doc(*args, **kwargs):
    from FNM_RE.app.mainline import audit_phase6_export_for_doc as impl

    return impl(*args, **kwargs)


def list_diagnostic_entries_for_doc(*args, **kwargs):
    from FNM_RE.app.mainline import list_phase6_diagnostic_entries_for_doc as impl

    return impl(*args, **kwargs)


def get_diagnostic_entry_for_page(*args, **kwargs):
    from FNM_RE.app.mainline import get_phase6_diagnostic_entry_for_doc as impl

    return impl(*args, **kwargs)


def list_diagnostic_notes_for_doc(*args, **kwargs):
    from FNM_RE.app.mainline import list_phase6_diagnostic_notes_for_doc as impl

    return impl(*args, **kwargs)


__all__ = [
    "run_doc_pipeline",
    "load_doc_structure",
    "build_doc_status",
    "build_export_bundle_for_doc",
    "build_export_zip_for_doc",
    "run_post_translate_export_checks_for_doc",
    "audit_export_for_doc",
    "list_diagnostic_entries_for_doc",
    "get_diagnostic_entry_for_page",
    "list_diagnostic_notes_for_doc",
    "prepare_page_translate_jobs",
    "build_retry_summary",
    "build_unit_progress",
    "run_llm_repair",
    "group_review_overrides",
    "annotate_review_note_links",
    "collect_llm_suggestions",
    "build_toc_structure",
    "build_book_note_profile",
    "build_chapter_layers",
    "build_note_link_table",
    "build_frozen_units",
    "build_chapter_markdown_set",
    "build_export_bundle",
]

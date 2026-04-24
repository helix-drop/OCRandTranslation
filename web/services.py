"""Web 层 service dataclass 与依赖装配。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import config as app_config
import document.pdf_extract as pdf_extract
import document.text_processing as text_processing
import document.text_utils as text_utils
import persistence.sqlite_store as sqlite_store
import persistence.storage as storage
import pipeline.document_tasks as document_tasks
import pipeline.task_registry as task_registry
import translation.service as translation_service
import translation.translate_launch as translate_launch
import translation.translate_progress as translate_progress
import translation.translate_runtime as translate_runtime
from FNM_RE import build_export_bundle_for_doc, build_export_zip_for_doc
import web.common as common
import web.document_support as document_support
import web.export_support as export_support
import web.page_editor as page_editor
import web.reading_view as reading_view
import web.settings_support as settings_support
import web.toc_support as toc_support
import web.translation_support as translation_support


def _proxy(module, attr: str):
    return lambda *args, **kwargs: getattr(module, attr)(*args, **kwargs)


class _ServiceBag:
    def __getitem__(self, key: str):
        return getattr(self, key)


@dataclass(frozen=True)
class DocumentServices(_ServiceBag):
    _delete_doc_with_verification: Any
    _guard_doc_delete: Any
    _parse_bool_flag: Any
    _request_doc_id: Any
    clear_entries_from_disk: Any
    create_task: Any
    delete_doc: Any
    get_app_state: Any
    get_current_doc_id: Any
    get_doc_auto_visual_toc_enabled: Any
    get_doc_cleanup_headers_footers: Any
    get_doc_meta: Any
    get_paddle_token: Any
    get_pdf_path: Any
    get_task: Any
    get_task_events: Any
    is_translate_running: Any
    list_docs: Any
    load_toc_visual_manual_inputs: Any
    load_pages_from_disk: Any
    normalize_doc_id: Any
    process_file: Any
    reparse_file: Any
    reparse_single_page: Any
    remove_task: Any
    request_stop_active_translate: Any
    resolve_visual_model_spec: Any
    save_toc_visual_manual_pdf: Any
    save_toc_visual_manual_screenshots: Any
    set_current_doc: Any
    set_task_final: Any
    set_upload_processing_preferences: Any
    start_auto_visual_toc_for_doc: Any
    update_doc_meta: Any


@dataclass(frozen=True)
class ReadingServices(_ServiceBag):
    MODELS: Any
    SQLiteRepository: Any
    _build_preview_paragraphs: Any
    _build_toc_reading_items: Any
    _default_reading_bp: Any
    _normalize_reading_view: Any
    _render_reading_body_text: Any
    _render_reading_footnotes_text: Any
    build_display_entries: Any
    build_fnm_page_context: Any
    build_page_notes_panel: Any
    build_reading_view_state: Any
    ensure_str: Any
    format_print_page_display: Any
    get_app_state: Any
    get_current_doc_id: Any
    get_doc_meta: Any
    get_pdf_virtual_scroll_min_pages: Any
    get_pdf_virtual_window_radius: Any
    get_translate_snapshot: Any
    has_pdf: Any
    load_effective_toc: Any
    load_fnm_diagnostic_view_entries: Any
    load_visible_page_view: Any
    normalize_doc_id: Any
    reading_view_summary_text: Any
    resolve_page_print_label: Any
    resolve_visible_page_bp: Any
    save_entry_cursor: Any
    set_current_doc: Any


@dataclass(frozen=True)
class TranslationServices(_ServiceBag):
    MODELS: Any
    SQLiteRepository: Any
    _build_translate_usage_payload: Any
    _normalize_reading_view: Any
    _provider_api_key_label: Any
    _request_doc_id: Any
    build_reading_view_state: Any
    build_visible_page_view: Any
    enrich_translate_snapshot_for_reading_view: Any
    get_app_state: Any
    get_doc_cleanup_headers_footers: Any
    get_doc_dir: Any
    get_doc_meta: Any
    get_glossary: Any
    get_model_key: Any
    get_next_page_bp: Any
    get_page_range: Any
    get_translate_args: Any
    get_translate_events: Any
    get_translate_snapshot: Any
    has_active_translate_task: Any
    load_entries_from_disk: Any
    load_fnm_diagnostic_entries: Any
    load_pages_from_disk: Any
    load_visible_page_view: Any
    logger: Any
    normalize_doc_id: Any
    reconcile_translate_state_after_page_failure: Any
    reconcile_translate_state_after_page_success: Any
    request_stop_active_translate: Any
    request_stop_translate: Any
    resolve_visible_page_bp: Any
    save_entries_to_disk: Any
    save_entry_to_disk: Any
    set_current_doc: Any
    start_fnm_translate_task: Any
    start_translate_task: Any
    translate_page: Any
    wait_for_translate_idle: Any


@dataclass(frozen=True)
class SettingsServices(_ServiceBag):
    _format_unix_ts: Any
    _redirect_settings: Any
    _request_doc_id: Any
    _save_model_pool_section: Any
    _save_text_setting: Any
    _save_translate_parallel_section: Any
    _serialize_glossary_retranslate_preview: Any
    _delete_doc_with_verification: Any
    _guard_doc_delete: Any
    build_glossary_retranslate_preview: Any
    clear_entries_from_disk: Any
    delete_glossary_item: Any
    get_app_state: Any
    get_current_doc_id: Any
    get_doc_meta: Any
    get_toc_file_info: Any
    has_active_translate_task: Any
    list_glossary_items: Any
    load_entries_from_disk: Any
    load_pages_from_disk: Any
    load_toc_source_offset: Any
    load_user_toc_from_disk: Any
    normalize_doc_id: Any
    parse_glossary_file: Any
    set_current_doc: Any
    set_dashscope_key: Any
    set_deepseek_key: Any
    set_glossary: Any
    set_glm_api_key: Any
    set_kimi_api_key: Any
    set_mimo_api_key: Any
    set_paddle_token: Any
    start_glossary_retranslate_task: Any
    upsert_glossary_item: Any


@dataclass(frozen=True)
class ExportServices(_ServiceBag):
    TOC_SOURCE_USER: Any
    _build_auto_visual_toc_editor_payload: Any
    _build_auto_visual_toc_editor_payload_from_items: Any
    _build_endnote_data: Any
    _load_toc_chapters_data: Any
    _load_toc_depth_map: Any
    _load_toc_title_map: Any
    _parse_bool_flag: Any
    _parse_bp_ranges: Any
    _request_doc_id: Any
    _sanitize_filename: Any
    build_fnm_obsidian_export: Any
    build_fnm_obsidian_export_zip: Any
    compute_boilerplate_skip_bps: Any
    gen_markdown: Any
    get_app_state: Any
    get_doc_meta: Any
    get_pdf_path: Any
    get_toc_file_info: Any
    load_effective_toc: Any
    load_entries_from_disk: Any
    load_pages_from_disk: Any
    load_toc_visual_draft: Any
    logger: Any
    render_pdf_page: Any


@dataclass(frozen=True)
class TocServices(_ServiceBag):
    TOC_SOURCE_USER: Any
    _build_auto_visual_toc_editor_payload: Any
    _build_auto_visual_toc_editor_payload_from_items: Any
    _build_pdf_page_lookup: Any
    _guess_toc_offset: Any
    _merge_auto_visual_submission: Any
    _request_doc_id: Any
    _visual_items_to_user_rows: Any
    _visual_toc_base_for_draft_merge: Any
    clear_toc_visual_draft: Any
    get_toc_file_info: Any
    load_auto_visual_toc_from_disk: Any
    load_effective_toc: Any
    load_pages_from_disk: Any
    load_pdf_toc_from_disk: Any
    load_toc_visual_draft: Any
    logger: Any
    parse_toc_file: Any
    save_auto_visual_toc_to_disk: Any
    save_toc_file: Any
    save_toc_source_offset: Any
    save_toc_visual_draft: Any
    save_user_toc_csv_generated: Any
    save_user_toc_to_disk: Any
    update_doc_meta: Any


@dataclass(frozen=True)
class PageEditorServices(_ServiceBag):
    _normalize_reading_view: Any
    _request_doc_id: Any
    build_page_editor_payload: Any
    list_page_editor_revisions: Any
    save_page_editor_rows: Any


@dataclass(frozen=True)
class AppServices:
    document: DocumentServices
    reading: ReadingServices
    translation: TranslationServices
    settings: SettingsServices
    export: ExportServices
    toc: TocServices
    page_editor: PageEditorServices


def build_app_services() -> AppServices:
    logger = logging.getLogger("app")
    request_doc_id = lambda: common.request_doc_id(app_config.normalize_doc_id, app_config.get_current_doc_id)

    document = DocumentServices(
        _delete_doc_with_verification=document_support.delete_doc_with_verification,
        _guard_doc_delete=document_support.guard_doc_delete,
        _parse_bool_flag=common.parse_bool_flag,
        _request_doc_id=request_doc_id,
        clear_entries_from_disk=_proxy(storage, "clear_entries_from_disk"),
        create_task=_proxy(task_registry, "create_task"),
        delete_doc=_proxy(app_config, "delete_doc"),
        get_app_state=_proxy(storage, "get_app_state"),
        get_current_doc_id=_proxy(app_config, "get_current_doc_id"),
        get_doc_auto_visual_toc_enabled=_proxy(app_config, "get_doc_auto_visual_toc_enabled"),
        get_doc_cleanup_headers_footers=_proxy(app_config, "get_doc_cleanup_headers_footers"),
        get_doc_meta=_proxy(app_config, "get_doc_meta"),
        get_paddle_token=_proxy(app_config, "get_paddle_token"),
        get_pdf_path=_proxy(storage, "get_pdf_path"),
        get_task=_proxy(task_registry, "get_task"),
        get_task_events=_proxy(task_registry, "get_task_events"),
        is_translate_running=_proxy(translate_runtime, "is_translate_running"),
        list_docs=_proxy(app_config, "list_docs"),
        load_toc_visual_manual_inputs=_proxy(storage, "load_toc_visual_manual_inputs"),
        load_pages_from_disk=_proxy(storage, "load_pages_from_disk"),
        normalize_doc_id=_proxy(app_config, "normalize_doc_id"),
        process_file=_proxy(document_tasks, "process_file"),
        reparse_file=_proxy(document_tasks, "reparse_file"),
        reparse_single_page=_proxy(document_tasks, "reparse_single_page"),
        remove_task=_proxy(task_registry, "remove_task"),
        request_stop_active_translate=_proxy(translate_runtime, "request_stop_active_translate"),
        resolve_visual_model_spec=_proxy(storage, "resolve_visual_model_spec"),
        save_toc_visual_manual_pdf=_proxy(storage, "save_toc_visual_manual_pdf"),
        save_toc_visual_manual_screenshots=_proxy(storage, "save_toc_visual_manual_screenshots"),
        set_current_doc=_proxy(app_config, "set_current_doc"),
        set_task_final=_proxy(task_registry, "set_task_final"),
        set_upload_processing_preferences=_proxy(app_config, "set_upload_processing_preferences"),
        start_auto_visual_toc_for_doc=_proxy(document_tasks, "start_auto_visual_toc_for_doc"),
        update_doc_meta=_proxy(app_config, "update_doc_meta"),
    )

    reading = ReadingServices(
        MODELS=app_config.MODELS,
        SQLiteRepository=_proxy(sqlite_store, "SQLiteRepository"),
        _build_preview_paragraphs=reading_view._build_preview_paragraphs,
        _build_toc_reading_items=reading_view._build_toc_reading_items,
        _default_reading_bp=reading_view._default_reading_bp,
        _normalize_reading_view=common.normalize_reading_view,
        _render_reading_body_text=reading_view._render_reading_body_text,
        _render_reading_footnotes_text=reading_view._render_reading_footnotes_text,
        build_display_entries=reading_view.build_display_entries,
        build_fnm_page_context=reading_view.build_fnm_page_context,
        build_page_notes_panel=reading_view.build_page_notes_panel,
        build_reading_view_state=reading_view.build_reading_view_state,
        ensure_str=text_utils.ensure_str,
        format_print_page_display=_proxy(storage, "format_print_page_display"),
        get_app_state=_proxy(storage, "get_app_state"),
        get_current_doc_id=_proxy(app_config, "get_current_doc_id"),
        get_doc_meta=_proxy(app_config, "get_doc_meta"),
        get_pdf_virtual_scroll_min_pages=_proxy(app_config, "get_pdf_virtual_scroll_min_pages"),
        get_pdf_virtual_window_radius=_proxy(app_config, "get_pdf_virtual_window_radius"),
        get_translate_snapshot=_proxy(translate_runtime, "get_translate_snapshot"),
        has_pdf=_proxy(storage, "has_pdf"),
        load_effective_toc=_proxy(storage, "load_effective_toc"),
        load_fnm_diagnostic_view_entries=reading_view.load_fnm_diagnostic_view_entries,
        load_visible_page_view=_proxy(storage, "load_visible_page_view"),
        normalize_doc_id=_proxy(app_config, "normalize_doc_id"),
        reading_view_summary_text=reading_view.reading_view_summary_text,
        resolve_page_print_label=_proxy(storage, "resolve_page_print_label"),
        resolve_visible_page_bp=text_processing.resolve_visible_page_bp,
        save_entry_cursor=_proxy(storage, "save_entry_cursor"),
        set_current_doc=_proxy(app_config, "set_current_doc"),
    )

    translation = TranslationServices(
        MODELS=app_config.MODELS,
        SQLiteRepository=_proxy(sqlite_store, "SQLiteRepository"),
        _build_translate_usage_payload=translation_support.build_translate_usage_payload,
        _normalize_reading_view=common.normalize_reading_view,
        _provider_api_key_label=settings_support.provider_api_key_label,
        _request_doc_id=request_doc_id,
        build_reading_view_state=reading_view.build_reading_view_state,
        build_visible_page_view=text_processing.build_visible_page_view,
        enrich_translate_snapshot_for_reading_view=reading_view.enrich_translate_snapshot_for_reading_view,
        get_app_state=_proxy(storage, "get_app_state"),
        get_doc_cleanup_headers_footers=_proxy(app_config, "get_doc_cleanup_headers_footers"),
        get_doc_dir=_proxy(app_config, "get_doc_dir"),
        get_doc_meta=_proxy(app_config, "get_doc_meta"),
        get_glossary=_proxy(app_config, "get_glossary"),
        get_model_key=_proxy(app_config, "get_model_key"),
        get_next_page_bp=text_processing.get_next_page_bp,
        get_page_range=text_processing.get_page_range,
        get_translate_args=_proxy(storage, "get_translate_args"),
        get_translate_events=_proxy(translate_runtime, "get_translate_events"),
        get_translate_snapshot=_proxy(translate_runtime, "get_translate_snapshot"),
        has_active_translate_task=_proxy(translate_runtime, "has_active_translate_task"),
        load_entries_from_disk=_proxy(storage, "load_entries_from_disk"),
        load_fnm_diagnostic_entries=reading_view.load_fnm_diagnostic_entries,
        load_pages_from_disk=_proxy(storage, "load_pages_from_disk"),
        load_visible_page_view=_proxy(storage, "load_visible_page_view"),
        logger=logger,
        normalize_doc_id=_proxy(app_config, "normalize_doc_id"),
        reconcile_translate_state_after_page_failure=_proxy(translate_progress, "reconcile_translate_state_after_page_failure"),
        reconcile_translate_state_after_page_success=_proxy(translate_progress, "reconcile_translate_state_after_page_success"),
        request_stop_active_translate=_proxy(translate_runtime, "request_stop_active_translate"),
        request_stop_translate=_proxy(translate_runtime, "request_stop_translate"),
        resolve_visible_page_bp=text_processing.resolve_visible_page_bp,
        save_entries_to_disk=_proxy(storage, "save_entries_to_disk"),
        save_entry_to_disk=_proxy(storage, "save_entry_to_disk"),
        set_current_doc=_proxy(app_config, "set_current_doc"),
        start_fnm_translate_task=_proxy(translate_launch, "start_fnm_translate_task"),
        start_translate_task=_proxy(translate_launch, "start_translate_task"),
        translate_page=_proxy(translation_service, "translate_page"),
        wait_for_translate_idle=_proxy(translate_runtime, "wait_for_translate_idle"),
    )

    settings = SettingsServices(
        _format_unix_ts=common.format_unix_ts,
        _redirect_settings=settings_support.redirect_settings,
        _request_doc_id=request_doc_id,
        _save_model_pool_section=settings_support.save_model_pool_section,
        _save_text_setting=settings_support.save_text_setting,
        _save_translate_parallel_section=settings_support.save_translate_parallel_section,
        _serialize_glossary_retranslate_preview=settings_support.serialize_glossary_retranslate_preview,
        _delete_doc_with_verification=document_support.delete_doc_with_verification,
        _guard_doc_delete=document_support.guard_doc_delete,
        build_glossary_retranslate_preview=_proxy(translation_service, "build_glossary_retranslate_preview"),
        clear_entries_from_disk=_proxy(storage, "clear_entries_from_disk"),
        delete_glossary_item=_proxy(app_config, "delete_glossary_item"),
        get_app_state=_proxy(storage, "get_app_state"),
        get_current_doc_id=_proxy(app_config, "get_current_doc_id"),
        get_doc_meta=_proxy(app_config, "get_doc_meta"),
        get_toc_file_info=_proxy(storage, "get_toc_file_info"),
        has_active_translate_task=_proxy(translate_runtime, "has_active_translate_task"),
        list_glossary_items=_proxy(app_config, "list_glossary_items"),
        load_entries_from_disk=_proxy(storage, "load_entries_from_disk"),
        load_pages_from_disk=_proxy(storage, "load_pages_from_disk"),
        load_toc_source_offset=_proxy(storage, "load_toc_source_offset"),
        load_user_toc_from_disk=_proxy(storage, "load_user_toc_from_disk"),
        normalize_doc_id=_proxy(app_config, "normalize_doc_id"),
        parse_glossary_file=_proxy(app_config, "parse_glossary_file"),
        set_current_doc=_proxy(app_config, "set_current_doc"),
        set_dashscope_key=_proxy(app_config, "set_dashscope_key"),
        set_deepseek_key=_proxy(app_config, "set_deepseek_key"),
        set_glossary=_proxy(app_config, "set_glossary"),
        set_glm_api_key=_proxy(app_config, "set_glm_api_key"),
        set_kimi_api_key=_proxy(app_config, "set_kimi_api_key"),
        set_mimo_api_key=_proxy(app_config, "set_mimo_api_key"),
        set_paddle_token=_proxy(app_config, "set_paddle_token"),
        start_glossary_retranslate_task=_proxy(translate_launch, "start_glossary_retranslate_task"),
        upsert_glossary_item=_proxy(app_config, "upsert_glossary_item"),
    )

    export = ExportServices(
        TOC_SOURCE_USER=storage.TOC_SOURCE_USER,
        _build_auto_visual_toc_editor_payload=reading_view._build_auto_visual_toc_editor_payload,
        _build_auto_visual_toc_editor_payload_from_items=reading_view._build_auto_visual_toc_editor_payload_from_items,
        _build_endnote_data=export_support.build_endnote_data,
        _load_toc_chapters_data=export_support.load_toc_chapters_data,
        _load_toc_depth_map=export_support.load_toc_depth_map,
        _load_toc_title_map=export_support.load_toc_title_map,
        _parse_bool_flag=common.parse_bool_flag,
        _parse_bp_ranges=export_support.parse_bp_ranges,
        _request_doc_id=request_doc_id,
        _sanitize_filename=common.sanitize_filename,
        build_fnm_obsidian_export=build_export_bundle_for_doc,
        build_fnm_obsidian_export_zip=build_export_zip_for_doc,
        compute_boilerplate_skip_bps=_proxy(storage, "compute_boilerplate_skip_bps"),
        gen_markdown=_proxy(storage, "gen_markdown"),
        get_app_state=_proxy(storage, "get_app_state"),
        get_doc_meta=_proxy(app_config, "get_doc_meta"),
        get_pdf_path=_proxy(storage, "get_pdf_path"),
        get_toc_file_info=_proxy(storage, "get_toc_file_info"),
        load_effective_toc=_proxy(storage, "load_effective_toc"),
        load_entries_from_disk=_proxy(storage, "load_entries_from_disk"),
        load_pages_from_disk=_proxy(storage, "load_pages_from_disk"),
        load_toc_visual_draft=_proxy(storage, "load_toc_visual_draft"),
        logger=logger,
        render_pdf_page=_proxy(pdf_extract, "render_pdf_page"),
    )

    toc = TocServices(
        TOC_SOURCE_USER=storage.TOC_SOURCE_USER,
        _build_auto_visual_toc_editor_payload=reading_view._build_auto_visual_toc_editor_payload,
        _build_auto_visual_toc_editor_payload_from_items=reading_view._build_auto_visual_toc_editor_payload_from_items,
        _build_pdf_page_lookup=reading_view._build_pdf_page_lookup,
        _guess_toc_offset=toc_support.guess_toc_offset,
        _merge_auto_visual_submission=toc_support.merge_auto_visual_submission,
        _request_doc_id=request_doc_id,
        _visual_items_to_user_rows=toc_support.visual_items_to_user_rows,
        _visual_toc_base_for_draft_merge=toc_support.visual_toc_base_for_draft_merge,
        clear_toc_visual_draft=_proxy(storage, "clear_toc_visual_draft"),
        get_toc_file_info=_proxy(storage, "get_toc_file_info"),
        load_auto_visual_toc_from_disk=_proxy(storage, "load_auto_visual_toc_from_disk"),
        load_effective_toc=_proxy(storage, "load_effective_toc"),
        load_pages_from_disk=_proxy(storage, "load_pages_from_disk"),
        load_pdf_toc_from_disk=_proxy(storage, "load_pdf_toc_from_disk"),
        load_toc_visual_draft=_proxy(storage, "load_toc_visual_draft"),
        logger=logger,
        parse_toc_file=_proxy(pdf_extract, "parse_toc_file"),
        save_auto_visual_toc_to_disk=_proxy(storage, "save_auto_visual_toc_to_disk"),
        save_toc_file=_proxy(storage, "save_toc_file"),
        save_toc_source_offset=_proxy(storage, "save_toc_source_offset"),
        save_toc_visual_draft=_proxy(storage, "save_toc_visual_draft"),
        save_user_toc_csv_generated=_proxy(storage, "save_user_toc_csv_generated"),
        save_user_toc_to_disk=_proxy(storage, "save_user_toc_to_disk"),
        update_doc_meta=_proxy(app_config, "update_doc_meta"),
    )

    page_editor_services = PageEditorServices(
        _normalize_reading_view=common.normalize_reading_view,
        _request_doc_id=request_doc_id,
        build_page_editor_payload=page_editor.build_page_editor_payload,
        list_page_editor_revisions=page_editor.list_page_editor_revisions,
        save_page_editor_rows=page_editor.save_page_editor_rows,
    )

    return AppServices(
        document=document,
        reading=reading,
        translation=translation,
        settings=settings,
        export=export,
        toc=toc,
        page_editor=page_editor_services,
    )

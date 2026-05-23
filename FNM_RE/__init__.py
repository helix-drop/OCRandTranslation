"""FNM_RE 对外入口。"""

from __future__ import annotations


def prepare_page_translate_jobs(*args, **kwargs):
    """←→ Rust fnm_re_rs.prepare_page_translate_jobs_json"""
    import json as _json
    import fnm_re_rs

    pages = args[0] if len(args) > 0 else kwargs.get("pages")
    target_bp = args[1] if len(args) > 1 else kwargs.get("target_bp")
    t_args = args[2] if len(args) > 2 else kwargs.get("t_args")
    doc_id = args[3] if len(args) > 3 else kwargs.get("doc_id")

    pages_json = _json.dumps(pages, ensure_ascii=False)
    t_args_json = _json.dumps(t_args, ensure_ascii=False)

    result_json = fnm_re_rs.prepare_page_translate_jobs_json(
        pages_json,
        target_bp,
        t_args_json,
        doc_id,
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
    )
    result = _json.loads(result_json)
    return result[0], result[1], result[2]


def build_retry_summary(*args, **kwargs):
    """←→ Rust fnm_re_rs.build_retry_summary_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    result_json = fnm_re_rs.build_retry_summary_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
    )
    return _json.loads(result_json)


def build_unit_progress(*args, **kwargs):
    """←→ Rust fnm_re_rs.build_unit_progress_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    snapshot = kwargs.get("snapshot")
    snapshot_json = _json.dumps(snapshot) if snapshot else None
    use_lightweight = kwargs.get("use_lightweight", False)
    result_json = fnm_re_rs.build_unit_progress_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
        snapshot_json,
        use_lightweight,
    )
    return _json.loads(result_json)


def run_llm_repair(*args, **kwargs):
    """←→ Rust fnm_re_rs.run_llm_repair_json"""
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    pdf_path = kwargs.get("pdf_path", "")
    renderer = kwargs.get("renderer")
    slug = kwargs.get("slug", "")
    auto_apply = kwargs.get("auto_apply", True)
    confidence_threshold = kwargs.get("confidence_threshold", 0.9)
    cluster_limit = kwargs.get("cluster_limit")
    trace_callback = kwargs.get("trace_callback")
    result_json = fnm_re_rs.run_llm_repair_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
        pdf_path,
        renderer,
        slug,
        auto_apply,
        confidence_threshold,
        cluster_limit,
        trace_callback,
    )
    import json as _json
    return _json.loads(result_json)


def group_review_overrides(review_overrides):
    _KNOWN_SCOPES = {"page", "chapter", "region", "link", "llm_suggestion", "anchor", "note_item"}
    from typing import Mapping
    grouped = {scope: {} for scope in _KNOWN_SCOPES}
    if not review_overrides:
        return grouped
    if isinstance(review_overrides, list):
        for row in review_overrides:
            payload = dict(row or {})
            scope = str(payload.get("scope") or "").strip().lower()
            target_id = str(payload.get("target_id") or "").strip()
            data = dict(payload.get("payload") or {})
            if not scope or not target_id:
                continue
            grouped.setdefault(scope, {})[target_id] = data
        return grouped
    if isinstance(review_overrides, Mapping):
        if any(str(key) in _KNOWN_SCOPES for key in review_overrides.keys()):
            for sc, rows in dict(review_overrides).items():
                scope_key = str(sc or "").strip().lower()
                if scope_key not in _KNOWN_SCOPES:
                    continue
                if not isinstance(rows, Mapping):
                    continue
                grouped[scope_key] = {
                    str(target_id): dict(payload or {})
                    for target_id, payload in dict(rows).items()
                    if str(target_id or "").strip()
                }
            return grouped
    return grouped


def annotate_review_note_links(note_links, overrides):
    link_overrides = dict((overrides or {}).get("link") or {})
    annotated = []
    for link in note_links or []:
        payload = dict(link or {})
        override = dict(link_overrides.get(str(payload.get("link_id") or ""), {}) or {})
        if override:
            payload["review_override"] = override
            payload["review_action"] = str(override.get("action") or "").strip().lower()
        annotated.append(payload)
    return annotated


def collect_llm_suggestions(overrides):
    suggestions = []
    for suggestion_id, payload in sorted(dict((overrides or {}).get("llm_suggestion") or {}).items()):
        item = dict(payload or {})
        item["suggestion_id"] = suggestion_id
        suggestions.append(item)
    return suggestions


def run_doc_pipeline(*args, **kwargs):
    """←→ Rust fnm_re_rs.run_doc_pipeline_json"""
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    max_body_chars = kwargs.get("max_body_chars")
    start_phase = kwargs.get("start_phase", "toc")
    result_json = fnm_re_rs.run_doc_pipeline_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
        max_body_chars,
        start_phase,
    )
    import json as _json
    return _json.loads(result_json)


def load_doc_structure(*args, **kwargs):
    """←→ Rust fnm_re_rs.load_doc_structure_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    include_diag = kwargs.get("include_diagnostic_entries", False)
    result_json = fnm_re_rs.load_doc_structure_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
        include_diag,
    )
    return _json.loads(result_json)


def build_doc_status(*args, **kwargs):
    """←→ Rust fnm_re_rs.build_doc_status_json"""
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    start_phase = kwargs.get("start_phase", "toc")
    result_json = fnm_re_rs.build_doc_status_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
        start_phase,
    )
    import json as _json
    return _json.loads(result_json)


def build_export_bundle_for_doc(*args, **kwargs):
    """←→ Rust fnm_re_rs.build_export_bundle_for_doc_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    result_json = fnm_re_rs.build_export_bundle_for_doc_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
    )
    return _json.loads(result_json)


def build_export_zip_for_doc(*args, **kwargs):
    """←→ Rust fnm_re_rs.build_export_zip_for_doc_json"""
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    return fnm_re_rs.build_export_zip_for_doc_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
    )


def run_post_translate_export_checks_for_doc(*args, **kwargs):
    """←→ Rust fnm_re_rs.run_post_translate_export_checks_for_doc_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    max_repair_rounds = kwargs.get("max_repair_rounds", 3)
    db_path = _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo"))

    slug = doc_id
    pdf_path = kwargs.get("pdf_path", "") or ""

    from persistence.storage import resolve_fnm_model_pool_specs

    model_args_list = []
    for spec in resolve_fnm_model_pool_specs():
        model_args_list.append({
            "provider": str(spec.provider or "").strip(),
            "model_id": str(spec.model_id or "").strip(),
            "api_key": str(spec.api_key or "").strip(),
            "base_url": str(spec.base_url or "").strip(),
            "request_overrides": dict(spec.request_overrides or {}),
            "display_label": str(spec.display_label or spec.model_id or "").strip(),
        })
    model_args_json = _json.dumps(model_args_list, ensure_ascii=False)

    result_json = fnm_re_rs.run_post_translate_export_checks_for_doc_json(
        db_path,
        doc_id,
        slug,
        pdf_path,
        model_args_json,
        max_repair_rounds,
    )
    return _json.loads(result_json)


def audit_export_for_doc(*args, **kwargs):
    """←→ Rust fnm_re_rs.audit_export_for_doc_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    slug = kwargs.get("slug", "")
    zip_path = kwargs.get("zip_path", "") or ""
    zip_bytes = kwargs.get("zip_bytes")
    result_json = fnm_re_rs.audit_export_for_doc_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
        slug,
        zip_path if zip_path else None,
        zip_bytes,
    )
    return _json.loads(result_json)


def list_diagnostic_entries_for_doc(*args, **kwargs):
    """←→ Rust fnm_re_rs.list_diagnostic_entries_for_doc_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    visible_bps = kwargs.get("visible_bps")
    result_json = fnm_re_rs.list_diagnostic_entries_for_doc_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
        list(visible_bps) if visible_bps is not None else None,
    )
    return _json.loads(result_json)


def get_diagnostic_entry_for_page(*args, **kwargs):
    """←→ Rust fnm_re_rs.get_diagnostic_entry_for_page_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    bp = args[1] if len(args) > 1 else kwargs.get("bp", 0)
    allow_fallback = kwargs.get("allow_fallback", True)
    result_json = fnm_re_rs.get_diagnostic_entry_for_page_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
        bp,
        allow_fallback,
    )
    return _json.loads(result_json) if result_json != "null" else None


def list_diagnostic_notes_for_doc(*args, **kwargs):
    """←→ Rust fnm_re_rs.list_diagnostic_notes_for_doc_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    result_json = fnm_re_rs.list_diagnostic_notes_for_doc_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
    )
    return _json.loads(result_json)


def dump_traces(example_dir, doc_id=""):
    """←→ Rust fnm_re_rs.dump_traces_json"""
    import fnm_re_rs

    return fnm_re_rs.dump_traces_json(example_dir, doc_id)


def write_summary_traces(example_dir, usage_summary, doc_id=""):
    """←→ Rust fnm_re_rs.write_summary_traces_json"""
    import json as _json
    import fnm_re_rs

    return _json.loads(fnm_re_rs.write_summary_traces_json(example_dir, _json.dumps(usage_summary, ensure_ascii=False)))


def has_explicit_sup(markdown, marker):
    """←→ Rust fnm_re_rs.has_explicit_sup_json"""
    import fnm_re_rs

    return fnm_re_rs.has_explicit_sup_json(markdown, marker)


def recover_book(pages, pdf_path=""):
    """←→ Rust fnm_re_rs.recover_book_json"""
    import json as _json
    import fnm_re_rs

    return _json.loads(fnm_re_rs.recover_book_json(_json.dumps(pages, ensure_ascii=False), pdf_path))


def format_fnm_unit_label(unit):
    """←→ Rust fnm_re_rs.format_fnm_unit_label_json"""
    import json as _json
    import fnm_re_rs

    return fnm_re_rs.format_fnm_unit_label_json(_json.dumps(unit, ensure_ascii=False))


def format_fnm_unit_pages(unit):
    """←→ Rust fnm_re_rs.format_fnm_unit_pages_json"""
    import json as _json
    import fnm_re_rs

    return fnm_re_rs.format_fnm_unit_pages_json(_json.dumps(unit, ensure_ascii=False))


def collect_fnm_unit_failed_locations(unit):
    """←→ Rust fnm_re_rs.collect_fnm_unit_failed_locations_json"""
    import json as _json
    import fnm_re_rs

    return _json.loads(fnm_re_rs.collect_fnm_unit_failed_locations_json(
        _json.dumps(unit, ensure_ascii=False),
    ))


def list_fnm_units_with_indices(*args, **kwargs):
    """←→ Rust fnm_re_rs.list_fnm_units_with_indices_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    result_json = fnm_re_rs.list_fnm_units_with_indices_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
    )
    return _json.loads(result_json)


def sync_fnm_retry_state(*args, **kwargs):
    """←→ Rust fnm_re_rs.sync_fnm_retry_state_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    result_json = fnm_re_rs.sync_fnm_retry_state_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
    )
    return _json.loads(result_json)


def rebuild_fnm_diagnostic_page_entries(*args, **kwargs):
    """←→ Rust fnm_re_rs.rebuild_fnm_diagnostic_page_entries_json"""
    import json as _json
    import fnm_re_rs

    doc_id = args[0] if args else kwargs.get("doc_id", "")
    pages = kwargs.get("pages", [])
    result_json = fnm_re_rs.rebuild_fnm_diagnostic_page_entries_json(
        _resolve_db_path(kwargs.get("db_path"), kwargs.get("repo")),
        doc_id,
        _json.dumps(pages, ensure_ascii=False),
    )
    return _json.loads(result_json)


def build_fnm_body_unit_jobs(unit, pages):
    """←→ Rust fnm_re_rs.build_fnm_body_unit_jobs_json"""
    import json as _json
    import fnm_re_rs

    return _json.loads(fnm_re_rs.build_fnm_body_unit_jobs_json(
        _json.dumps(unit, ensure_ascii=False),
        _json.dumps(pages, ensure_ascii=False),
    ))


def apply_body_unit_translations(unit, translated_paragraphs):
    """←→ Rust fnm_re_rs.apply_body_unit_translations_json"""
    import json as _json
    import fnm_re_rs

    return _json.loads(fnm_re_rs.apply_body_unit_translations_json(
        _json.dumps(unit, ensure_ascii=False),
        _json.dumps(translated_paragraphs, ensure_ascii=False),
    ))


def apply_body_unit_entry_result(unit, entry, *, apply_only_unresolved=False):
    """←→ Rust fnm_re_rs.apply_body_unit_entry_result_json"""
    import json as _json
    import fnm_re_rs

    return _json.loads(fnm_re_rs.apply_body_unit_entry_result_json(
        _json.dumps(unit, ensure_ascii=False),
        _json.dumps(entry, ensure_ascii=False),
        apply_only_unresolved,
    ))


def resolve_repair_model_args():
    """←→ Rust fnm_re_rs.resolve_repair_model_args_json"""
    import json as _json
    import fnm_re_rs

    return _json.loads(fnm_re_rs.resolve_repair_model_args_json())


def render_repair_page_data_url(pdf_path, page_index, *, scale=1.3):
    """←→ Rust fnm_re_rs.render_repair_page_data_url_json"""
    import fnm_re_rs

    return fnm_re_rs.render_repair_page_data_url_json(pdf_path, page_index, scale)


def body_paragraphs(markdown):
    """←→ Rust fnm_re_rs.body_paragraphs_json"""
    import json as _json
    import fnm_re_rs

    return _json.loads(fnm_re_rs.body_paragraphs_json(markdown))


def definition_lines(markdown):
    """←→ Rust fnm_re_rs.definition_lines_json"""
    import json as _json
    import fnm_re_rs

    return _json.loads(fnm_re_rs.definition_lines_json(markdown))


def split_body_and_definitions(markdown):
    """←→ Rust fnm_re_rs.split_body_and_definitions_json"""
    import json as _json
    import fnm_re_rs

    return tuple(_json.loads(fnm_re_rs.split_body_and_definitions_json(markdown)))


def replace_frozen_refs(text, *, endnote_mode="standard"):
    """←→ Rust fnm_re_rs.replace_frozen_refs_json"""
    import fnm_re_rs

    return fnm_re_rs.replace_frozen_refs_json(text, endnote_mode)


def serialize_segments(*args, **kwargs):
    """←→ Rust fnm_re_rs.serialize_segments_json"""
    import json as _json
    import fnm_re_rs

    segments = args[0] if args else kwargs.get("segments", [])
    result_json = fnm_re_rs.serialize_segments_json(_json.dumps(segments, ensure_ascii=False))
    return _json.loads(result_json)


def deserialize_segments_to_dicts(*args, **kwargs):
    """←→ Rust fnm_re_rs.deserialize_segments_to_dicts_json"""
    import json as _json
    import fnm_re_rs

    payload = args[0] if args else kwargs.get("payload", [])
    result_json = fnm_re_rs.deserialize_segments_to_dicts_json(_json.dumps(payload, ensure_ascii=False))
    return _json.loads(result_json)


# ── Rust pipeline binding ────────────────────────────────────────
# 安装：cd fnm_re_rs/fnm-py && maturin develop
# 验证：FNM_RE.fnm_re_rs_version() 返回 "0.1.0" 表示就绪
#
# 与 Python 端 pipeline 区别：Rust 版本不读 SQLite documents/raw_pages 表，
# 调用方需自行准备 raw_pages list[dict] + toc_items list[dict] + config dict。
# 等价于 Python `build_module_pipeline_snapshot()`，返回 dict（JSON 序列化体）。


def fnm_re_rs_version() -> str | None:
    """返回已安装的 fnm_re_rs Rust binding 版本。未装时返回 None。"""
    try:
        import fnm_re_rs
    except ImportError:
        return None
    return fnm_re_rs.version()


def build_module_pipeline_snapshot_rust(
    pages: list[dict],
    toc_items: list[dict] | None = None,
    *,
    doc_id: str = "",
    slug: str = "",
    pdf_path: str = "",
    toc_offset: int = 0,
    max_body_chars: int = 6000,
    include_diagnostic_entries: bool = False,
    manual_toc_ready: bool = True,
    pipeline_state: str = "done",
    start_phase: str = "toc",
    db_path: str | None = None,
    enable_llm_repair: bool = False,
    renderer=None,
    auto_apply: bool = True,
    confidence_threshold: float = 0.9,
) -> dict:
    """调用 fnm_re_rs Rust binding 跑 phase1→6 pipeline。

    ←→ Rust `fnm_orchestrator::run_pipeline` / `run_pipeline_for_doc`

    Args:
        pages: raw OCR 页面 list[dict]（与 Python `build_module_pipeline_snapshot` 一致）
        toc_items: 目录项 list[dict]
        db_path: 传入则走 DB-driven 入口，每 phase 持久化到 SQLite；
                 不传则走纯内存版（不持久化）
        其余 kwargs 对齐 Python `build_module_pipeline_snapshot()` 同名参数

    Returns:
        dict（ModulePipelineSnapshot JSON 序列化体，含 phase1-6 + run_meta）

    Raises:
        ImportError: fnm-re-rs 未安装
        RuntimeError: pipeline 内部异常
    """
    import json as _json

    try:
        import fnm_re_rs
    except ImportError as e:
        raise ImportError(
            "fnm-re-rs 未安装。请运行：cd fnm_re_rs/fnm-py && maturin develop"
        ) from e

    config = {
        "doc_id": doc_id,
        "slug": slug,
        "pdf_path": pdf_path,
        "toc_offset": int(toc_offset or 0),
        "max_body_chars": int(max_body_chars or 6000),
        "include_diagnostic_entries": bool(include_diagnostic_entries),
        "manual_toc_ready": bool(manual_toc_ready),
        "pipeline_state": str(pipeline_state),
        "start_phase": str(start_phase),
    }
    pages_json = _json.dumps(pages)
    toc_json = _json.dumps(toc_items or [])
    config_json = _json.dumps(config)

    if enable_llm_repair:
        if not db_path:
            raise ValueError("enable_llm_repair=True 需要传 db_path（LLM repair 通过 DB 中转）")
        result_json = fnm_re_rs.run_pipeline_for_doc_with_llm_repair_json(
            db_path, doc_id, pages_json, toc_json, config_json,
            pdf_path, renderer, auto_apply, float(confidence_threshold),
        )
    elif db_path:
        result_json = fnm_re_rs.run_pipeline_for_doc_json(
            db_path, doc_id, pages_json, toc_json, config_json,
        )
    else:
        result_json = fnm_re_rs.run_pipeline_json(pages_json, toc_json, config_json)
    return _json.loads(result_json)


def _resolve_db_path(db_path=None, repo=None):
    """统一提取数据库路径。优先显式路径 > repo 路径 > 默认路径。"""
    if db_path:
        return db_path
    if repo is not None and hasattr(repo, "db_path"):
        return repo.db_path
    # 默认路径（与 persistence/sqlite_store 一致）
    import os
    _root = os.environ.get("FNM_BOOKS_ROOT", os.path.join(os.getcwd(), "data/fnm"))
    return os.path.join(_root, "fnm_books.db")


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
    "dump_traces",
    "write_summary_traces",
    "has_explicit_sup",
    "recover_book",
    "format_fnm_unit_label",
    "format_fnm_unit_pages",
    "collect_fnm_unit_failed_locations",
    "list_fnm_units_with_indices",
    "sync_fnm_retry_state",
    "rebuild_fnm_diagnostic_page_entries",
    "build_fnm_body_unit_jobs",
    "apply_body_unit_translations",
    "apply_body_unit_entry_result",
    "resolve_repair_model_args",
    "render_repair_page_data_url",
    "body_paragraphs",
    "definition_lines",
    "split_body_and_definitions",
    "replace_frozen_refs",
    "serialize_segments",
    "deserialize_segments_to_dicts",
    "build_module_pipeline_snapshot_rust",
    "fnm_re_rs_version",
]

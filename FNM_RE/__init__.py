"""FNM_RE 对外入口。"""

from __future__ import annotations


def prepare_page_translate_jobs(*args, **kwargs):
    from FNM_RE.app.page_translate import prepare_page_translate_jobs as impl

    return impl(*args, **kwargs)


def build_retry_summary(*args, **kwargs):
    from FNM_RE.app.page_translate import build_retry_summary as impl

    return impl(*args, **kwargs)


def build_unit_progress(*args, **kwargs):
    from FNM_RE.app.page_translate import build_unit_progress as impl

    return impl(*args, **kwargs)


def run_llm_repair(*args, **kwargs):
    from FNM_RE.modules.llm_repair import run_llm_repair as impl

    return impl(*args, **kwargs)


def group_review_overrides(*args, **kwargs):
    from FNM_RE.shared.review_overrides import group_review_overrides as impl

    return impl(*args, **kwargs)


def annotate_review_note_links(*args, **kwargs):
    from FNM_RE.shared.review import annotate_review_note_links as impl

    return impl(*args, **kwargs)


def collect_llm_suggestions(*args, **kwargs):
    from FNM_RE.shared.review import collect_llm_suggestions as impl

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
    from FNM_RE.app.mainline import list_phase6_diagnostic_entries_for_doc as impl

    return impl(*args, **kwargs)


def get_diagnostic_entry_for_page(*args, **kwargs):
    from FNM_RE.app.mainline import get_phase6_diagnostic_entry_for_doc as impl

    return impl(*args, **kwargs)


def list_diagnostic_notes_for_doc(*args, **kwargs):
    from FNM_RE.app.mainline import list_phase6_diagnostic_notes_for_doc as impl

    return impl(*args, **kwargs)


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


# ── Shadow mode ─────────────────────────────────────────────
# 信心建设工具：在 Python pipeline 旁路并行跑 Rust，把关键 counts 写日志，
# 不替换 Python 主路径。用法（嵌入到 Python build_module_pipeline_snapshot 调用前后）：
#
#     FNM_SHADOW_RUST_PHASES=1 python -m ...   # 启用 shadow
#
#     # 代码内：
#     rust_snapshot = FNM_RE.run_with_shadow(pages, toc_items, doc_id=doc_id)
#     # rust_snapshot 是 dict（启用时）或 None（未启用）
#     # 关键 counts 已 append 到 logs/fnm_rust_shadow.jsonl
#
# diff Python ↔ Rust：调用 `summarize_pipeline_snapshot(rust_or_py_snapshot)` 提取
# counts，再用 set/diff 工具人工比对。
#
# 由 env 控制是为了在生产里能开关，不必改代码。


def summarize_pipeline_snapshot(snapshot: dict) -> dict:
    """从 ModulePipelineSnapshot dict 提取各 phase 的关键 counts，用于 shadow diff。

    无论 Rust 还是 Python（dataclass.asdict()）产出的 snapshot 都能消费，
    只要按相同字段名暴露 phase1..6。

    ←→ Rust `SerPhase1..SerPhase6` 字段
    """
    counts: dict = {}
    p1 = snapshot.get("phase1") or {}
    counts["phase1"] = {
        "chapters": len(p1.get("chapters") or []),
        "pages": len(p1.get("pages") or []),
        "heading_candidates": len(p1.get("heading_candidates") or []),
        "section_heads": len(p1.get("section_heads") or []),
    }
    p2 = snapshot.get("phase2") or {}
    counts["phase2"] = {
        "note_regions": len(p2.get("note_regions") or []),
        "note_items": len(p2.get("note_items") or []),
        "chapter_note_modes": len(p2.get("chapter_note_modes") or []),
    }
    p3 = snapshot.get("phase3") or {}
    counts["phase3"] = {
        "body_anchors": len(p3.get("body_anchors") or []),
        "note_links": len(p3.get("note_links") or []),
    }
    p4 = snapshot.get("phase4") or {}
    counts["phase4"] = {
        "translation_units": len(p4.get("translation_units") or []),
        "structure_reviews": len(p4.get("structure_reviews") or []),
    }
    p5 = snapshot.get("phase5") or {}
    counts["phase5"] = {"chapter_count": int(p5.get("chapter_count") or 0)}
    p6 = snapshot.get("phase6") or {}
    bundle = p6.get("export_bundle") or {}
    counts["phase6"] = {
        "export_chapters": len(bundle.get("chapters") or []),
        "contract_ok": bool(bundle.get("export_semantic_contract_ok", False)),
    }
    counts["run_meta"] = snapshot.get("run_meta") or {}
    return counts


def run_with_shadow(
    pages: list[dict],
    toc_items: list[dict] | None = None,
    *,
    log_path: str | None = None,
    env_var: str = "FNM_SHADOW_RUST_PHASES",
    **kwargs,
) -> dict | None:
    """在 ``$FNM_SHADOW_RUST_PHASES`` 设置时跑 Rust pipeline 并把 counts append 到日志。

    嵌入 Python 主路径（不替换）：

    >>> py_snapshot = build_module_pipeline_snapshot(pages, toc_items, doc_id=doc_id)  # 主路径
    >>> rust_snapshot = FNM_RE.run_with_shadow(pages, toc_items, doc_id=doc_id)  # 旁路

    生产里 ``FNM_SHADOW_RUST_PHASES=1`` 启用；返回 ``dict | None``。
    日志默认 ``logs/fnm_rust_shadow.jsonl`` 每行一条 JSON。
    """
    import os
    import time
    import json as _json

    if not os.getenv(env_var):
        return None

    started_at = time.time()
    try:
        snapshot = build_module_pipeline_snapshot_rust(pages, toc_items, **kwargs)
        success = True
        err_msg = ""
    except Exception as exc:  # 防御性：shadow 路径绝不影响主路径
        snapshot = None
        success = False
        err_msg = f"{type(exc).__name__}: {exc}"

    elapsed = time.time() - started_at
    log_entry = {
        "ts": int(started_at),
        "elapsed_sec": round(elapsed, 3),
        "doc_id": kwargs.get("doc_id", ""),
        "slug": kwargs.get("slug", ""),
        "success": success,
        "error": err_msg,
        "counts": summarize_pipeline_snapshot(snapshot) if snapshot else None,
    }

    log_path = log_path or "logs/fnm_rust_shadow.jsonl"
    try:
        import pathlib
        pathlib.Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as fh:
            fh.write(_json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 日志写失败不影响主路径

    return snapshot


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
    "build_toc_structure",
    "build_book_note_profile",
    "build_chapter_layers",
    "build_note_link_table",
    "build_frozen_units",
    "build_chapter_markdown_set",
    "build_export_bundle",
    "build_module_pipeline_snapshot_rust",
    "fnm_re_rs_version",
    "run_with_shadow",
    "summarize_pipeline_snapshot",
]

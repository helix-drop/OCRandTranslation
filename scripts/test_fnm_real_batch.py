#!/usr/bin/env python3
"""真实视觉 + 真实LLM修补 + test占位翻译 的样本批跑脚本。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import traceback
from collections import Counter
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_EXAMPLE_ROOT = REPO_ROOT / "test_example"
OUTPUT_ROOT = REPO_ROOT / "output" / "fnm_real_batch"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from example_manifest import ExampleBook, select_example_books  # noqa: E402
from FNM_RE import (  # noqa: E402
    build_export_zip_for_doc as build_fnm_obsidian_export_zip,
    list_diagnostic_entries_for_doc,
    load_doc_structure as load_fnm_doc_structure,
    run_doc_pipeline as run_fnm_pipeline,
    run_llm_repair,
)
from persistence.sqlite_store import SQLiteRepository  # noqa: E402
from persistence.storage import get_pdf_path  # noqa: E402
from pipeline.document_tasks import run_auto_visual_toc_for_doc  # noqa: E402
from scripts.reingest_fnm_from_snapshots import reingest_book  # noqa: E402
from scripts.test_fnm_batch import (  # noqa: E402
    BLOCKED_EXPORT_ZIP_NAME,
    LATEST_EXPORT_ZIP_NAME,
    materialize_test_placeholders,
    verify_export,
    verify_fnm_structure,
)

REQUIRED_STAGE_ORDER = [
    "visual_toc.preflight",
    "visual_toc.classify_candidates",
    "visual_toc.extract_page_items",
    "visual_toc.manual_input_extract",
    "llm_repair.cluster_request",
    "translation_test",
]

BOOK_STAGE_ORDER = [
    "reingest",
    "visual_toc",
    "fnm_pipeline",
    "llm_repair",
    "fnm_pipeline_rebuild",
    "structure_verify",
    "placeholder_translate",
    "export_verify",
    "zip_finalize",
    "report_write",
]

_CLEANUP_GLOB_PATTERNS = (
    "llm_traces",
    "fnm_real_test_progress.json",
    "fnm_real_test_result.json",
    "fnm_real_test_modules.json",
    "FNM_REAL_TEST_REPORT.md",
    "FNM_LLM_TIER1A_REPORT.md",
    "auto_visual_toc.json",
    "auto_visual_toc.md",
    "latest_export_status.json",
    "latest.fnm.obsidian*",
    "latest.fnm.obsidian*.zip",
    "forced_export_*",
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slugify_stage_name(stage: str) -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "_", str(stage or "").strip())
    return text.strip("._-") or "trace"


def _json_dump(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _dedupe_strings(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _trim_preview(value: str, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _normalize_title_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _markdown_preview(path: Path, *, limit: int = 220) -> str:
    if not path.is_file():
        return ""
    try:
        return _trim_preview(path.read_text(encoding="utf-8"), limit=limit)
    except Exception:
        return ""


def _raw_pages_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if isinstance(payload, dict):
        return len(list(payload.get("pages") or []))
    return 0


def _describe_input_asset(
    key: str,
    path: Path,
    *,
    required: bool,
    used_by: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key": key,
        "path": str(path),
        "exists": path.is_file(),
        "required": bool(required),
        "used_by": list(used_by),
        "size_bytes": int(path.stat().st_size) if path.is_file() else 0,
        "sha256": _file_sha256(path) if path.is_file() else "",
    }
    if key == "raw_pages":
        payload["page_count"] = _raw_pages_count(path)
    if key == "raw_source_markdown":
        payload["preview"] = _markdown_preview(path)
        payload["usage_note"] = "本轮只作为输入资产校验与报告证据，不回灌数据库。"
    return payload


def _build_input_asset_manifest(asset_check: dict[str, Any]) -> dict[str, Any]:
    paths = {
        key: Path(value)
        for key, value in dict(asset_check.get("paths") or {}).items()
        if key != "folder" and str(value or "").strip()
    }
    return {
        "pdf": _describe_input_asset("pdf", paths.get("pdf", Path()), required=True, used_by=["reingest", "visual_toc", "llm_repair"]),
        "raw_pages": _describe_input_asset("raw_pages", paths.get("raw_pages", Path()), required=True, used_by=["reingest", "fnm_pipeline"]),
        "raw_source_markdown": _describe_input_asset(
            "raw_source_markdown",
            paths.get("raw_source_markdown", Path()),
            required=True,
            used_by=["asset_check", "report_evidence"],
        ),
        "manual_toc_pdf": _describe_input_asset(
            "manual_toc_pdf",
            paths.get("manual_toc_pdf", Path()),
            required=False,
            used_by=["visual_toc"],
        ),
    }


def _cleanup_example_results(example_dir: Path) -> dict[str, Any]:
    example_dir.mkdir(parents=True, exist_ok=True)
    removed: list[str] = []
    failed: list[dict[str, str]] = []
    for pattern in _CLEANUP_GLOB_PATTERNS:
        for path in sorted(example_dir.glob(pattern)):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed.append(str(path))
            except FileNotFoundError:
                continue
            except Exception as exc:
                failed.append({"path": str(path), "error": str(exc)})
    status = {
        "cleaned_at": _now_iso(),
        "example_dir": str(example_dir),
        "removed": removed,
        "removed_count": len(removed),
        "failed": failed,
        "failed_count": len(failed),
    }
    _json_dump(example_dir / "fnm_cleanup_status.json", status)
    return status


def _make_paragraph_locator(*, page_no: int | None = None, paragraph_index: int | None = None, text_preview: str = "") -> str:
    parts: list[str] = []
    if page_no:
        parts.append(f"原书 p.{int(page_no)}")
    if paragraph_index is not None and int(paragraph_index) >= 0:
        parts.append(f"¶{int(paragraph_index)}")
    locator = " ".join(parts).strip()
    preview = _trim_preview(text_preview, limit=80)
    if locator and preview:
        return f"{locator} — {preview}"
    return locator or preview


def _first_unit_locator(unit: dict[str, Any]) -> dict[str, Any]:
    for segment in list(unit.get("page_segments") or []):
        page_no = int(segment.get("page_no") or unit.get("page_start") or 0) or None
        paragraphs = list(segment.get("paragraphs") or [])
        for paragraph in paragraphs:
            preview = str(paragraph.get("display_text") or paragraph.get("source_text") or "").strip()
            if not preview:
                continue
            return {
                "page_no": page_no,
                "paragraph_index": int(paragraph.get("order") or 0) or None,
                "text_preview": preview,
            }
        preview = str(segment.get("display_text") or segment.get("source_text") or "").strip()
        if preview:
            return {
                "page_no": page_no,
                "paragraph_index": None,
                "text_preview": preview,
            }
    preview = str(unit.get("source_text") or unit.get("section_title") or "").strip()
    return {
        "page_no": int(unit.get("page_start") or 0) or None,
        "paragraph_index": None,
        "text_preview": preview,
    }


def _resolve_title_locator(
    title: str,
    *,
    title_to_item: dict[str, dict[str, Any]],
    section_heads_by_title: dict[str, dict[str, Any]],
    units_by_title: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    key = _normalize_title_key(title)
    visual_item = title_to_item.get(key) or {}
    section_head = section_heads_by_title.get(key) or {}
    unit = units_by_title.get(key) or {}
    if unit:
        unit_locator = _first_unit_locator(unit)
    else:
        unit_locator = {}
    page_no = (
        int(section_head.get("page_no") or 0)
        or int(unit_locator.get("page_no") or 0)
        or int(visual_item.get("printed_page") or 0)
        or None
    )
    paragraph_index = unit_locator.get("paragraph_index")
    preview = (
        str(unit_locator.get("text_preview") or "").strip()
        or str(section_head.get("text") or "").strip()
        or str(title or "").strip()
    )
    return {
        "page_no": page_no,
        "paragraph_index": paragraph_index,
        "text_preview": preview,
    }


def _usage_zero() -> dict[str, int]:
    return {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def _normalize_usage_row(row: dict[str, Any] | None) -> dict[str, int]:
    row = dict(row or {})
    return {
        "request_count": int(row.get("request_count") or 0),
        "prompt_tokens": int(row.get("prompt_tokens") or 0),
        "completion_tokens": int(row.get("completion_tokens") or 0),
        "total_tokens": int(row.get("total_tokens") or 0),
    }


def _merge_usage_rows(target: dict[str, int], incoming: dict[str, int]) -> dict[str, int]:
    target["request_count"] += int(incoming.get("request_count") or 0)
    target["prompt_tokens"] += int(incoming.get("prompt_tokens") or 0)
    target["completion_tokens"] += int(incoming.get("completion_tokens") or 0)
    target["total_tokens"] += int(incoming.get("total_tokens") or 0)
    return target


def _merge_usage_summaries(*summaries: dict[str, Any]) -> dict[str, Any]:
    by_stage: dict[str, dict[str, int]] = {stage: _usage_zero() for stage in REQUIRED_STAGE_ORDER}
    by_model: dict[str, dict[str, int]] = {}
    total = _usage_zero()
    for summary in summaries:
        data = dict(summary or {})
        for stage, row in dict(data.get("by_stage") or {}).items():
            stage_key = str(stage or "").strip() or "unknown"
            by_stage.setdefault(stage_key, _usage_zero())
            _merge_usage_rows(by_stage[stage_key], _normalize_usage_row(row))
        for model_id, row in dict(data.get("by_model") or {}).items():
            model_key = str(model_id or "").strip() or "unknown"
            by_model.setdefault(model_key, _usage_zero())
            _merge_usage_rows(by_model[model_key], _normalize_usage_row(row))
        _merge_usage_rows(total, _normalize_usage_row(data.get("total")))
    by_stage.setdefault("translation_test", _usage_zero())
    return {"by_stage": by_stage, "by_model": by_model, "total": total}


def _asset_paths(book: ExampleBook) -> dict[str, Path]:
    folder = TEST_EXAMPLE_ROOT / book.folder
    manual_toc_pdf = folder / "目录.pdf"
    if not manual_toc_pdf.is_file():
        for candidate in sorted(folder.glob("*目录*.pdf")):
            if candidate.is_file():
                manual_toc_pdf = candidate
                break
    return {
        "folder": folder,
        "pdf": folder / book.doc_name,
        "raw_pages": folder / "raw_pages.json",
        "raw_source_markdown": folder / "raw_source_markdown.md",
        "manual_toc_pdf": manual_toc_pdf,
    }


def _check_required_assets(book: ExampleBook) -> dict[str, Any]:
    paths = _asset_paths(book)
    missing: list[str] = []
    if not paths["pdf"].is_file():
        missing.append(str(paths["pdf"]))
    if not paths["raw_pages"].is_file():
        missing.append(str(paths["raw_pages"]))
    if not paths["raw_source_markdown"].is_file():
        missing.append(str(paths["raw_source_markdown"]))
    return {
        "ok": len(missing) == 0,
        "missing": missing,
        "manual_toc_exists": paths["manual_toc_pdf"].is_file(),
        "paths": {key: str(path) for key, path in paths.items()},
    }


def _resolve_example_dir(book: ExampleBook) -> Path:
    return TEST_EXAMPLE_ROOT / book.folder


def _write_zip_aliases(
    *,
    example_dir: Path,
    slug: str,
    blocked: bool,
    source_zip_path: Path | None,
    fallback_zip_bytes: bytes | None,
) -> dict[str, Any]:
    example_dir.mkdir(parents=True, exist_ok=True)
    if blocked:
        slug_zip = example_dir / f"latest.fnm.obsidian.{slug}.blocked.test.zip"
        alias_zip = example_dir / "latest.fnm.obsidian.blocked.test.zip"
        stale_zip = example_dir / f"latest.fnm.obsidian.{slug}.test.zip"
    else:
        slug_zip = example_dir / f"latest.fnm.obsidian.{slug}.test.zip"
        alias_zip = example_dir / "latest.fnm.obsidian.test.zip"
        stale_zip = example_dir / f"latest.fnm.obsidian.{slug}.blocked.test.zip"
    if stale_zip.exists():
        stale_zip.unlink()

    written = False
    reason = ""
    if source_zip_path and source_zip_path.is_file():
        shutil.copy2(source_zip_path, slug_zip)
        shutil.copy2(source_zip_path, alias_zip)
        written = True
    elif fallback_zip_bytes:
        slug_zip.write_bytes(fallback_zip_bytes)
        alias_zip.write_bytes(fallback_zip_bytes)
        written = True
    else:
        reason = "zip_not_found"
    return {
        "written": written,
        "slug_zip_path": str(slug_zip),
        "alias_zip_path": str(alias_zip),
        "reason": reason,
    }


def _resolve_source_zip_path(example_dir: Path, export_result: dict[str, Any], blocked: bool) -> Path | None:
    explicit = str(export_result.get("latest_export_zip_path") or "").strip()
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
    if blocked:
        blocked_candidate = example_dir / BLOCKED_EXPORT_ZIP_NAME
        if blocked_candidate.is_file():
            return blocked_candidate
    ready_candidate = example_dir / LATEST_EXPORT_ZIP_NAME
    if ready_candidate.is_file():
        return ready_candidate
    return None


def _initial_progress() -> dict[str, Any]:
    return {
        "status": "running",
        "current_stage": "reingest",
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "stage_history": [],
    }


def _append_stage_history(progress: dict[str, Any], *, stage: str, status: str, detail: str = "") -> None:
    progress["current_stage"] = str(stage or "")
    progress["status"] = str(status or "")
    progress["updated_at"] = _now_iso()
    progress.setdefault("stage_history", []).append(
        {
            "stage": str(stage or ""),
            "status": str(status or ""),
            "detail": str(detail or ""),
            "at": progress["updated_at"],
        }
    )


def _trace_index_entry(trace: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    usage = dict(trace.get("usage") or {})
    return {
        "stage": str(trace.get("stage") or ""),
        "file": str(trace_path),
        "reason_for_request": str(trace.get("reason_for_request") or ""),
        "model_id": str(dict(trace.get("model") or {}).get("model_id") or ""),
        "total_tokens": int(usage.get("total_tokens") or usage.get("total") or 0),
    }


def _preview_row_text(value: Any, *, limit: int = 140) -> str:
    return _trim_preview(str(value or ""), limit=limit)


def _group_list_rows(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows or []:
        token = str((row or {}).get(key) or "").strip()
        if not token:
            continue
        grouped[token].append(dict(row))
    return dict(grouped)


def _numeric_markers_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_markers: list[int] = []
    marker_preview: list[str] = []
    for row in rows or []:
        marker = str((row or {}).get("normalized_marker") or (row or {}).get("marker") or "").strip()
        if marker:
            marker_preview.append(marker)
        if marker.isdigit():
            numeric_markers.append(int(marker))
    unique_numeric = sorted(set(numeric_markers))
    contiguous = bool(
        unique_numeric
        and unique_numeric == list(range(unique_numeric[0], unique_numeric[-1] + 1))
    )
    return {
        "numeric_marker_count": len(unique_numeric),
        "numeric_marker_start": unique_numeric[0] if unique_numeric else None,
        "numeric_marker_end": unique_numeric[-1] if unique_numeric else None,
        "numeric_marker_contiguous": contiguous,
        "marker_preview": marker_preview[:8],
    }


def _sample_page_role_rows(pages: list[dict[str, Any]], *, limit_per_role: int = 3) -> list[dict[str, Any]]:
    by_role: dict[str, int] = defaultdict(int)
    sampled: list[dict[str, Any]] = []
    for row in sorted(pages or [], key=lambda item: int(item.get("page_no") or 0)):
        role = str(row.get("page_role") or "").strip() or "unknown"
        if by_role[role] >= limit_per_role:
            continue
        by_role[role] += 1
        sampled.append(
            {
                "page_no": int(row.get("page_no") or 0),
                "target_pdf_page": int(row.get("target_pdf_page") or 0),
                "page_role": role,
                "role_reason": str(row.get("role_reason") or ""),
                "role_confidence": float(row.get("role_confidence") or 0.0),
                "has_note_heading": bool(row.get("has_note_heading")),
                "section_hint": str(row.get("section_hint") or ""),
            }
        )
    return sampled


def _build_module_process_report(
    doc_id: str,
    *,
    structure: dict[str, Any],
    export_result: dict[str, Any],
    trace_index: list[dict[str, Any]],
) -> dict[str, Any]:
    repo = SQLiteRepository()
    pages = list(repo.list_fnm_pages(doc_id) or [])
    regions = list(repo.list_fnm_note_regions(doc_id) or [])
    note_items = list(repo.list_fnm_note_items(doc_id) or [])
    anchors = list(repo.list_fnm_body_anchors(doc_id) or [])
    links = list(repo.list_fnm_note_links(doc_id) or [])
    units = list(repo.list_fnm_translation_units(doc_id) or [])

    pages_sorted = sorted(pages, key=lambda row: int(row.get("page_no") or 0))
    page_role_counts = dict(Counter(str(row.get("page_role") or "").strip() or "unknown" for row in pages_sorted))
    first_body_page = next(
        (int(row.get("page_no") or 0) for row in pages_sorted if str(row.get("page_role") or "").strip() == "body"),
        None,
    )
    first_note_page = next(
        (int(row.get("page_no") or 0) for row in pages_sorted if str(row.get("page_role") or "").strip() == "note"),
        None,
    )

    regions_by_id = {str(row.get("region_id") or ""): dict(row) for row in regions}
    note_items_by_region = _group_list_rows(note_items, "region_id")
    note_units = [dict(row) for row in units if str(row.get("kind") or "").strip() != "body"]
    note_units_by_section = _group_list_rows(note_units, "section_id")
    chapter_stats = list(export_result.get("chapter_stats") or export_result.get("chapter_stats_preview") or [])
    chapter_stats_by_path = {str(row.get("path") or ""): dict(row) for row in chapter_stats}

    note_region_rows: list[dict[str, Any]] = []
    for row in sorted(regions, key=lambda item: (int(item.get("start_page") or 0), str(item.get("region_id") or ""))):
        region_id = str(row.get("region_id") or "")
        region_items = list(note_items_by_region.get(region_id) or [])
        marker_summary = _numeric_markers_summary(region_items)
        note_region_rows.append(
            {
                "region_id": region_id,
                "region_kind": str(row.get("region_kind") or ""),
                "bound_chapter_id": str(row.get("bound_chapter_id") or ""),
                "start_page": int(row.get("start_page") or 0),
                "end_page": int(row.get("end_page") or 0),
                "pages": list(row.get("pages") or []),
                "region_start_first_source_marker": str(row.get("region_start_first_source_marker") or ""),
                "region_first_note_item_marker": str(row.get("region_first_note_item_marker") or ""),
                "region_marker_alignment_ok": bool(row.get("region_marker_alignment_ok", True)),
                "item_count": len(region_items),
                **marker_summary,
                "sample_note_items": [
                    {
                        "note_item_id": str(item.get("note_item_id") or ""),
                        "page_no": int(item.get("page_no") or 0),
                        "marker": str(item.get("normalized_marker") or item.get("marker") or ""),
                        "source_text_preview": _preview_row_text(item.get("source_text")),
                    }
                    for item in region_items[:3]
                ],
            }
        )

    endnote_region_rows = [row for row in note_region_rows if row.get("region_kind") == "endnote"]
    note_array_rows: list[dict[str, Any]] = []
    for region_row in note_region_rows:
        note_array_rows.append(
            {
                "region_id": str(region_row.get("region_id") or ""),
                "region_kind": str(region_row.get("region_kind") or ""),
                "bound_chapter_id": str(region_row.get("bound_chapter_id") or ""),
                "item_count": int(region_row.get("item_count") or 0),
                "numeric_marker_start": region_row.get("numeric_marker_start"),
                "numeric_marker_end": region_row.get("numeric_marker_end"),
                "numeric_marker_contiguous": bool(region_row.get("numeric_marker_contiguous")),
                "marker_preview": list(region_row.get("marker_preview") or []),
            }
        )

    merge_rows: list[dict[str, Any]] = []
    for section_id, rows in sorted(note_units_by_section.items(), key=lambda item: str(item[0])):
        section_rows = list(rows or [])
        section_title = str((section_rows[0] or {}).get("section_title") or "")
        merge_rows.append(
            {
                "section_id": section_id,
                "section_title": section_title,
                "note_unit_count": len(section_rows),
                "note_unit_kind_counts": dict(Counter(str(row.get("kind") or "") for row in section_rows)),
                "target_ref_preview": [str(row.get("target_ref") or "") for row in section_rows[:5]],
                "page_span": [
                    min(int(row.get("page_start") or 0) for row in section_rows),
                    max(int(row.get("page_end") or 0) for row in section_rows),
                ] if section_rows else [],
            }
        )
    merge_rows_by_title = {_normalize_title_key(str(row.get("section_title") or "")): row for row in merge_rows}
    export_merge_rows: list[dict[str, Any]] = []
    for row in chapter_stats:
        title = str(row.get("title") or "").strip()
        merge_row = merge_rows_by_title.get(_normalize_title_key(title), {})
        export_merge_rows.append(
            {
                "title": title,
                "path": str(row.get("path") or ""),
                "note_unit_count": int(merge_row.get("note_unit_count") or 0),
                "local_ref_total": int(row.get("local_ref_total") or 0),
                "local_def_total": int(row.get("local_def_total") or 0),
                "first_local_def_marker": str(row.get("first_local_def_marker") or ""),
                "chapter_local_contract_ok": bool(row.get("chapter_local_contract_ok", False)),
                "orphan_local_definitions": list(row.get("orphan_local_definitions") or []),
                "orphan_local_refs": list(row.get("orphan_local_refs") or []),
            }
        )

    link_status_counts = dict(Counter(str(row.get("status") or "") for row in links))
    link_resolver_counts = dict(Counter(str(row.get("resolver") or "") for row in links))
    anchor_kind_counts = dict(Counter(str(row.get("anchor_kind") or "") for row in anchors))
    anchor_rows = sorted(
        anchors,
        key=lambda row: (int(row.get("page_no") or 0), int(row.get("paragraph_index") or -1), str(row.get("anchor_id") or "")),
    )
    anchor_samples = [
        {
            "anchor_id": str(row.get("anchor_id") or ""),
            "chapter_id": str(row.get("chapter_id") or ""),
            "page_no": int(row.get("page_no") or 0),
            "paragraph_index": int(row.get("paragraph_index") or 0),
            "marker": str(row.get("normalized_marker") or row.get("source_marker") or ""),
            "anchor_kind": str(row.get("anchor_kind") or ""),
            "certainty": float(row.get("certainty") or 0.0),
            "source_text_preview": _preview_row_text(row.get("source_text")),
        }
        for row in anchor_rows[:10]
    ]
    link_samples = [
        {
            "link_id": str(row.get("link_id") or ""),
            "chapter_id": str(row.get("chapter_id") or ""),
            "note_item_id": str(row.get("note_item_id") or ""),
            "anchor_id": str(row.get("anchor_id") or ""),
            "status": str(row.get("status") or ""),
            "resolver": str(row.get("resolver") or ""),
            "marker": str(row.get("marker") or ""),
            "page_span": [int(row.get("page_no_start") or 0), int(row.get("page_no_end") or 0)],
        }
        for row in links[:12]
    ]

    llm_trace_refs = [str(row.get("file") or "") for row in trace_index if str(row.get("stage") or "").startswith("llm_repair.")][:12]
    visual_trace_refs = [str(row.get("file") or "") for row in trace_index if str(row.get("stage") or "").startswith("visual_toc.")][:12]

    return {
        "boundary_detection": {
            "decision_basis": [
                "fnm_pages.page_role",
                "fnm_pages.role_reason",
                "fnm_pages.role_confidence",
                "fnm_pages.has_note_heading",
                "fnm_pages.section_hint",
            ],
            "page_role_counts": page_role_counts,
            "first_body_page": first_body_page,
            "first_note_page": first_note_page,
            "page_role_samples": _sample_page_role_rows(pages_sorted),
            "structure_page_partition_summary": dict(structure.get("page_partition_summary") or {}),
        },
        "note_region_detection": {
            "decision_basis": [
                "fnm_note_regions.region_kind/start_page/end_page/pages",
                "fnm_note_regions.bound_chapter_id",
                "fnm_note_regions.region_start_first_source_marker",
                "fnm_note_regions.region_first_note_item_marker",
                "structure.chapter_binding_summary",
                "structure.visual_toc_endnotes_summary",
            ],
            "visual_toc_endnotes_summary": dict(structure.get("visual_toc_endnotes_summary") or {}),
            "chapter_binding_summary": dict(structure.get("chapter_binding_summary") or {}),
            "chapter_endnote_region_alignment_summary": dict(structure.get("chapter_endnote_region_alignment_summary") or {}),
            "region_rows": note_region_rows,
            "endnote_region_rows": endnote_region_rows,
        },
        "endnote_array_building": {
            "decision_basis": [
                "fnm_note_items.region_id/chapter_id/page_no/marker",
                "按 region_id 聚合生成注释数组",
                "检查 numeric marker 连续性与首尾 marker",
            ],
            "note_capture_summary": dict(structure.get("note_capture_summary") or {}),
            "book_endnote_stream_summary": dict(structure.get("book_endnote_stream_summary") or {}),
            "array_rows": note_array_rows,
            "endnote_array_rows": [row for row in note_array_rows if row.get("region_kind") == "endnote"],
        },
        "endnote_merging": {
            "decision_basis": [
                "fnm_translation_units.kind/owner_kind/section_id/target_ref",
                "导出 chapter markdown 中 local refs/local defs 的闭合情况",
                "structure.freeze_note_unit_summary",
            ],
            "freeze_note_unit_summary": dict(structure.get("freeze_note_unit_summary") or {}),
            "note_unit_rows": merge_rows,
            "export_merge_rows": export_merge_rows,
        },
        "anchor_resolution": {
            "decision_basis": [
                "fnm_body_anchors.page_no/paragraph_index/char_start/char_end/source_marker",
                "fnm_note_links.status/resolver/confidence",
                "llm_repair traces（若 resolver=repair 或存在 unresolved cluster）",
            ],
            "link_summary": dict(structure.get("link_summary") or {}),
            "chapter_link_contract_summary": dict(structure.get("chapter_link_contract_summary") or {}),
            "anchor_kind_counts": anchor_kind_counts,
            "link_status_counts": link_status_counts,
            "link_resolver_counts": link_resolver_counts,
            "anchor_samples": anchor_samples,
            "link_samples": link_samples,
            "llm_repair_trace_refs": llm_trace_refs,
            "visual_toc_trace_refs": visual_trace_refs,
        },
    }


def _persist_traces(
    *,
    example_dir: Path,
    traces: list[dict[str, Any]],
    trace_counters: dict[str, int],
    trace_index: list[dict[str, Any]],
) -> None:
    trace_dir = example_dir / "llm_traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    for trace in traces or []:
        stage = str(trace.get("stage") or "trace")
        trace_counters[stage] = int(trace_counters.get(stage) or 0) + 1
        filename = f"{_slugify_stage_name(stage)}.{trace_counters[stage]:03d}.json"
        trace_path = trace_dir / filename
        _json_dump(trace_path, dict(trace))
        trace_index.append(_trace_index_entry(trace, trace_path))


def _build_trace_refs(trace_index: list[dict[str, Any]], *, prefix: str) -> list[str]:
    refs: list[str] = []
    for row in trace_index:
        stage = str(row.get("stage") or "").strip()
        if not stage.startswith(prefix):
            continue
        refs.append(str(row.get("file") or ""))
    return refs[:8]


def _build_blocking_details(
    doc_id: str,
    *,
    structure: dict[str, Any],
    export_result: dict[str, Any],
    visual_result: dict[str, Any],
    trace_index: list[dict[str, Any]],
    stage_errors: list[dict[str, Any]],
    blocking_reasons: list[str] | None = None,
) -> list[dict[str, Any]]:
    blocking_reason_set = {
        str(value or "").strip()
        for value in (blocking_reasons or [])
        if str(value or "").strip()
    }
    if not blocking_reason_set and not stage_errors and not bool((export_result or {}).get("blocked")):
        return []
    details: list[dict[str, Any]] = []
    visual_items = list(
        (visual_result or {}).get("organization_nodes")
        or (visual_result or {}).get("items")
        or []
    )
    title_to_item = {
        _normalize_title_key(item.get("title") or ""): dict(item)
        for item in visual_items
        if str(item.get("title") or "").strip()
    }
    heading_graph = dict((structure or {}).get("heading_graph_summary") or {})
    repo = SQLiteRepository()
    try:
        section_heads = list(getattr(repo, "list_fnm_section_heads", lambda _doc_id: [])(doc_id) or [])
        translation_units = list(getattr(repo, "list_fnm_translation_units", lambda _doc_id: [])(doc_id) or [])
        note_items = {str(row.get("note_item_id") or ""): dict(row) for row in repo.list_fnm_note_items(doc_id)}
        anchors = {str(row.get("anchor_id") or ""): dict(row) for row in repo.list_fnm_body_anchors(doc_id)}
        links = list(repo.list_fnm_note_links(doc_id) or [])
    except Exception:
        section_heads = []
        translation_units = []
        note_items = {}
        anchors = {}
        links = []
    section_heads_by_title = {
        _normalize_title_key(row.get("text") or ""): dict(row)
        for row in section_heads
        if str(row.get("text") or "").strip()
    }
    units_by_title = {
        _normalize_title_key(row.get("section_title") or ""): dict(row)
        for row in translation_units
        if str(row.get("section_title") or "").strip()
    }
    for title in list(heading_graph.get("unresolved_titles_preview") or []):
        locator = _resolve_title_locator(
            str(title or ""),
            title_to_item=title_to_item,
            section_heads_by_title=section_heads_by_title,
            units_by_title=units_by_title,
        )
        details.append(
            {
                "stage": "structure_verify",
                "reason_code": "heading_graph_incomplete",
                "page_no": locator.get("page_no"),
                "chapter_title": str(title or ""),
                "paragraph_locator": _make_paragraph_locator(
                    page_no=locator.get("page_no"),
                    paragraph_index=locator.get("paragraph_index"),
                    text_preview=str(locator.get("text_preview") or title or ""),
                ),
                "evidence_text_preview": str(locator.get("text_preview") or title or ""),
                "upstream_trace_refs": _build_trace_refs(trace_index, prefix="visual_toc."),
            }
        )
    for title in list(heading_graph.get("boundary_conflict_titles_preview") or []):
        locator = _resolve_title_locator(
            str(title or ""),
            title_to_item=title_to_item,
            section_heads_by_title=section_heads_by_title,
            units_by_title=units_by_title,
        )
        details.append(
            {
                "stage": "structure_verify",
                "reason_code": "heading_graph_boundary_conflict",
                "page_no": locator.get("page_no"),
                "chapter_title": str(title or ""),
                "paragraph_locator": _make_paragraph_locator(
                    page_no=locator.get("page_no"),
                    paragraph_index=locator.get("paragraph_index"),
                    text_preview=str(locator.get("text_preview") or title or ""),
                ),
                "evidence_text_preview": str(locator.get("text_preview") or title or ""),
                "upstream_trace_refs": _build_trace_refs(trace_index, prefix="visual_toc."),
            }
        )
    include_note_link_details = bool(
        blocking_reason_set.intersection(
            {
                "link_endnote_not_all_matched",
                "link_footnote_not_all_matched",
                "split_footnote_only_synthesis_failed",
                "export_audit_blocking",
                "structure_review_required",
            }
        )
        or str((export_result or {}).get("reason") or "").strip() in {"export_audit_blocking", "structure_review_required"}
    )
    for link in links:
        if not include_note_link_details:
            break
        status = str(link.get("status") or "").strip()
        if status not in {"orphan_note", "orphan_anchor", "ambiguous"}:
            continue
        note_item = note_items.get(str(link.get("note_item_id") or ""))
        anchor = anchors.get(str(link.get("anchor_id") or ""))
        page_no = int((anchor or {}).get("page_no") or (note_item or {}).get("page_no") or link.get("page_no_start") or 0) or None
        paragraph_index = (anchor or {}).get("paragraph_index")
        evidence = str((note_item or {}).get("source_text") or (anchor or {}).get("source_text") or "")
        details.append(
            {
                "stage": "structure_verify",
                "reason_code": f"note_link_{status}",
                "page_no": page_no,
                "chapter_title": str(link.get("chapter_id") or ""),
                "paragraph_locator": _make_paragraph_locator(
                    page_no=page_no,
                    paragraph_index=int(paragraph_index) if paragraph_index is not None else None,
                    text_preview=evidence,
                ),
                "evidence_text_preview": _trim_preview(evidence, 140),
                "upstream_trace_refs": _build_trace_refs(trace_index, prefix="llm_repair."),
            }
        )

    for row in list(structure.get("chapter_issue_summary") or []):
        issue_code = str(row.get("issue_code") or row.get("reason_code") or "chapter_issue").strip()
        page_no = int(row.get("page_no") or row.get("page_start") or 0) or None
        paragraph_index = row.get("paragraph_index")
        preview = str(
            row.get("text_preview")
            or row.get("source_text")
            or row.get("detail")
            or row.get("message")
            or row.get("chapter_title")
            or ""
        ).strip()
        details.append(
            {
                "stage": "structure_verify",
                "reason_code": issue_code,
                "page_no": page_no,
                "chapter_title": str(row.get("chapter_title") or row.get("section_title") or ""),
                "paragraph_locator": _make_paragraph_locator(
                    page_no=page_no,
                    paragraph_index=int(paragraph_index) if paragraph_index not in (None, "") else None,
                    text_preview=preview,
                ),
                "evidence_text_preview": _trim_preview(preview, 140),
                "upstream_trace_refs": _build_trace_refs(trace_index, prefix="visual_toc."),
            }
        )

    for row in list(structure.get("chapter_endnote_region_cross_next_chapter_preview") or []):
        page_no = int(row.get("start_page") or 0) or None
        preview = str(
            row.get("region_first_note_item_marker")
            or row.get("region_start_first_source_marker")
            or row.get("chapter_title")
            or ""
        ).strip()
        details.append(
            {
                "stage": "structure_verify",
                "reason_code": "endnote_region_cross_next_chapter",
                "page_no": page_no,
                "chapter_title": str(row.get("chapter_title") or ""),
                "paragraph_locator": _make_paragraph_locator(page_no=page_no, text_preview=preview),
                "evidence_text_preview": _trim_preview(preview, 140),
                "upstream_trace_refs": _build_trace_refs(trace_index, prefix="visual_toc."),
            }
        )

    for row in stage_errors:
        details.append(
            {
                "stage": str(row.get("stage") or ""),
                "reason_code": str(row.get("reason_code") or "runtime_exception"),
                "page_no": None,
                "chapter_title": "",
                "paragraph_locator": "",
                "evidence_text_preview": str(row.get("message") or ""),
                "upstream_trace_refs": [],
            }
        )

    if export_result and export_result.get("blocked"):
        details.append(
            {
                "stage": "export_verify",
                "reason_code": str(export_result.get("reason") or "export_blocked"),
                "page_no": None,
                "chapter_title": "",
                "paragraph_locator": "",
                "evidence_text_preview": json.dumps(export_result.get("blocking_reasons") or [], ensure_ascii=False),
                "upstream_trace_refs": [],
            }
        )
    return details[:48]


def _write_book_outputs(example_dir: Path, result: dict[str, Any]) -> None:
    _json_dump(example_dir / "fnm_real_test_progress.json", dict(result.get("progress") or {}))
    _json_dump(example_dir / "fnm_real_test_result.json", result)
    _json_dump(example_dir / "fnm_real_test_modules.json", dict(result.get("module_process") or {}))
    (example_dir / "FNM_REAL_TEST_REPORT.md").write_text(
        _build_book_report_markdown(result),
        encoding="utf-8",
    )


def _write_batch_outputs(output_dir: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    token_summary = _merge_usage_summaries(*[dict(item.get("usage_summary") or {}) for item in results])

    def _rank_by_total_tokens(item: dict[str, Any]) -> int:
        usage = dict(item.get("usage_summary") or {})
        return int((usage.get("total") or {}).get("total_tokens") or 0)

    per_book_token_ranking = [
        {
            "slug": str(item.get("slug") or ""),
            "total_tokens": _rank_by_total_tokens(item),
            "status": "blocked" if item.get("blocked") else "ready",
        }
        for item in sorted(results, key=_rank_by_total_tokens, reverse=True)
    ]
    by_model = dict(token_summary.get("by_model") or {})
    model_token_ranking = [
        {"model_id": model_id, "total_tokens": int((row or {}).get("total_tokens") or 0)}
        for model_id, row in sorted(
            by_model.items(),
            key=lambda kv: int((kv[1] or {}).get("total_tokens") or 0),
            reverse=True,
        )
    ]
    token_summary_with_ranking = {
        **token_summary,
        "per_book_token_ranking": per_book_token_ranking,
        "model_token_ranking": model_token_ranking,
    }
    results_path = output_dir / "results.json"
    token_path = output_dir / "token_summary.json"
    report_path = output_dir / "batch_report.md"
    _json_dump(results_path, results)
    _json_dump(token_path, token_summary_with_ranking)
    report_path.write_text(_build_batch_report_markdown(results, token_summary_with_ranking), encoding="utf-8")
    return {
        "results_path": str(results_path),
        "token_summary_path": str(token_path),
        "batch_report_path": str(report_path),
        "token_summary": token_summary_with_ranking,
    }


def _write_batch_runtime_status(output_dir: Path, payload: dict[str, Any]) -> None:
    _json_dump(output_dir / "runtime_status.json", dict(payload or {}))


def _build_book_report_markdown(result: dict[str, Any]) -> str:
    usage = dict(result.get("usage_summary") or {})
    by_stage = dict(usage.get("by_stage") or {})
    structure = dict(result.get("structure") or {})
    heading_graph_summary = dict(structure.get("heading_graph_summary") or {})
    toc_role_summary = dict(structure.get("toc_role_summary") or {})
    visual_toc = dict(result.get("visual_toc") or {})
    endnotes_summary = dict(visual_toc.get("endnotes_summary") or {})
    progress = dict(result.get("progress") or {})
    trace_index = list(result.get("trace_index") or [])
    blocking_details = list(result.get("blocking_details") or [])
    final_zip = dict(result.get("final_zip") or {})
    cleanup = dict(result.get("cleanup") or {})
    input_assets = dict(result.get("input_assets") or {})
    placeholders = dict(result.get("placeholders") or {})
    module_process = dict(result.get("module_process") or {})
    lines = [
        f"# FNM Real Test Report — {result.get('slug', '')}",
        "",
        f"- doc_id: `{result.get('doc_id', '')}`",
        f"- 状态: `{'blocked' if result.get('blocked') else 'ready'}`",
        f"- 导出可用: `{bool(result.get('all_ok'))}`",
        f"- 阻塞原因: `{json.dumps(result.get('blocking_reasons') or [], ensure_ascii=False)}`",
        f"- translation_mode: `{result.get('translation_mode') or ''}`",
        f"- translation_api_called: `{bool(result.get('translation_api_called'))}`",
        f"- current_stage: `{progress.get('current_stage') or ''}`",
        "",
        "## 输入资产",
    ]
    for key in ("pdf", "raw_pages", "raw_source_markdown", "manual_toc_pdf"):
        asset = dict(input_assets.get(key) or {})
        if not asset:
            continue
        lines.append(
            f"- {key}: exists=`{bool(asset.get('exists'))}` path=`{asset.get('path') or ''}` "
            f"size=`{asset.get('size_bytes') or 0}` sha256=`{asset.get('sha256') or ''}`"
        )
        if asset.get("page_count") is not None:
            lines.append(f"- {key}.page_count: `{asset.get('page_count')}`")
        if asset.get("usage_note"):
            lines.append(f"- {key}.usage_note: `{asset.get('usage_note')}`")
        if asset.get("preview"):
            lines.append(f"- {key}.preview: `{asset.get('preview')}`")
    lines.extend(
        [
            "",
            "## 清理结果",
            f"- removed_count: `{int(cleanup.get('removed_count') or 0)}`",
            f"- removed_preview: `{json.dumps(list(cleanup.get('removed') or [])[:8], ensure_ascii=False)}`",
            "",
            "## 占位翻译",
            f"- translation_mode: `{result.get('translation_mode') or ''}`",
            f"- translation_api_called: `{bool(result.get('translation_api_called'))}`",
            f"- translated_paras: `{int(placeholders.get('translated_paras') or 0)}`",
            "",
            "## 模块过程取证文件",
            f"- path: `{str((Path(result.get('input_assets', {}).get('pdf', {}).get('path', '')).parents[0] / 'fnm_real_test_modules.json')) if result.get('input_assets', {}).get('pdf', {}).get('path') else ''}`",
            "",
            "## Token by Stage",
        ]
    )
    for stage in REQUIRED_STAGE_ORDER:
        row = _normalize_usage_row(by_stage.get(stage))
        lines.append(
            f"- {stage}: request={row['request_count']}, prompt={row['prompt_tokens']}, completion={row['completion_tokens']}, total={row['total_tokens']}"
        )
    lines.extend(
        [
            "",
            "## Heading Graph",
            f"- optimized_anchor_count: `{int(heading_graph_summary.get('optimized_anchor_count') or 0)}`",
            f"- residual_provisional_count: `{int(heading_graph_summary.get('residual_provisional_count') or 0)}`",
            f"- expanded_window_hit_count: `{int(heading_graph_summary.get('expanded_window_hit_count') or 0)}`",
            f"- composite_heading_count: `{int(heading_graph_summary.get('composite_heading_count') or 0)}`",
            f"- residual_provisional_titles_preview: `{json.dumps(heading_graph_summary.get('residual_provisional_titles_preview') or [], ensure_ascii=False)}`",
            f"- `{json.dumps(heading_graph_summary, ensure_ascii=False)}`",
            "",
            "## Endnotes Summary",
            f"- present: `{bool(endnotes_summary.get('present'))}`",
            f"- container_title: `{endnotes_summary.get('container_title') or ''}`",
            f"- container_printed_page: `{endnotes_summary.get('container_printed_page') or ''}`",
            f"- container_visual_order: `{endnotes_summary.get('container_visual_order') or ''}`",
            f"- has_chapter_keyed_subentries_in_toc: `{bool(endnotes_summary.get('has_chapter_keyed_subentries_in_toc'))}`",
            f"- subentry_pattern: `{endnotes_summary.get('subentry_pattern') or ''}`",
            "",
            "## TOC Role Summary",
            f"- `{json.dumps(toc_role_summary, ensure_ascii=False)}`",
            "",
            "## Export",
            f"- slug zip: `{final_zip.get('slug_zip_path') or result.get('slug_zip_path', '')}`",
            f"- alias zip: `{final_zip.get('alias_zip_path') or result.get('alias_zip_path', '')}`",
            "",
            "## LLM 交互摘要",
            f"- trace_count: `{len(trace_index)}`",
        ]
    )
    for row in trace_index[:24]:
        lines.append(
            f"- {row.get('stage')}: {row.get('reason_for_request')} -> `{row.get('file')}`"
        )
    if module_process:
        boundary = dict(module_process.get("boundary_detection") or {})
        note_regions = dict(module_process.get("note_region_detection") or {})
        endnote_arrays = dict(module_process.get("endnote_array_building") or {})
        endnote_merging = dict(module_process.get("endnote_merging") or {})
        anchor_resolution = dict(module_process.get("anchor_resolution") or {})
        lines.extend(
            [
                "",
                "## 模块过程取证",
                "### 边界区分",
                f"- decision_basis: `{json.dumps(boundary.get('decision_basis') or [], ensure_ascii=False)}`",
                f"- page_role_counts: `{json.dumps(boundary.get('page_role_counts') or {}, ensure_ascii=False)}`",
                f"- first_body_page: `{boundary.get('first_body_page')}`",
                f"- first_note_page: `{boundary.get('first_note_page')}`",
                f"- page_role_samples: `{json.dumps(boundary.get('page_role_samples') or [], ensure_ascii=False)}`",
                "",
                "### 尾注区确定",
                f"- decision_basis: `{json.dumps(note_regions.get('decision_basis') or [], ensure_ascii=False)}`",
                f"- visual_toc_endnotes_summary: `{json.dumps(note_regions.get('visual_toc_endnotes_summary') or {}, ensure_ascii=False)}`",
                f"- chapter_binding_summary: `{json.dumps(note_regions.get('chapter_binding_summary') or {}, ensure_ascii=False)}`",
                f"- endnote_region_rows: `{json.dumps((note_regions.get('endnote_region_rows') or [])[:8], ensure_ascii=False)}`",
                "",
                "### 尾注数组建立",
                f"- decision_basis: `{json.dumps(endnote_arrays.get('decision_basis') or [], ensure_ascii=False)}`",
                f"- note_capture_summary: `{json.dumps(endnote_arrays.get('note_capture_summary') or {}, ensure_ascii=False)}`",
                f"- book_endnote_stream_summary: `{json.dumps(endnote_arrays.get('book_endnote_stream_summary') or {}, ensure_ascii=False)}`",
                f"- endnote_array_rows: `{json.dumps((endnote_arrays.get('endnote_array_rows') or [])[:8], ensure_ascii=False)}`",
                "",
                "### 尾注拼接",
                f"- decision_basis: `{json.dumps(endnote_merging.get('decision_basis') or [], ensure_ascii=False)}`",
                f"- freeze_note_unit_summary: `{json.dumps(endnote_merging.get('freeze_note_unit_summary') or {}, ensure_ascii=False)}`",
                f"- note_unit_rows: `{json.dumps((endnote_merging.get('note_unit_rows') or [])[:8], ensure_ascii=False)}`",
                f"- export_merge_rows: `{json.dumps((endnote_merging.get('export_merge_rows') or [])[:8], ensure_ascii=False)}`",
                "",
                "### 锚点寻找与链接",
                f"- decision_basis: `{json.dumps(anchor_resolution.get('decision_basis') or [], ensure_ascii=False)}`",
                f"- link_summary: `{json.dumps(anchor_resolution.get('link_summary') or {}, ensure_ascii=False)}`",
                f"- link_resolver_counts: `{json.dumps(anchor_resolution.get('link_resolver_counts') or {}, ensure_ascii=False)}`",
                f"- anchor_samples: `{json.dumps((anchor_resolution.get('anchor_samples') or [])[:8], ensure_ascii=False)}`",
                f"- link_samples: `{json.dumps((anchor_resolution.get('link_samples') or [])[:8], ensure_ascii=False)}`",
            ]
        )
    lines.extend(["", "## 阻塞定位明细"])
    for row in blocking_details[:24]:
        lines.append(
            f"- {row.get('stage')} / {row.get('reason_code')}: `{row.get('paragraph_locator') or row.get('page_no') or ''}` | `{row.get('evidence_text_preview') or ''}`"
        )
    return "\n".join(lines).rstrip() + "\n"


def _build_batch_report_markdown(results: list[dict[str, Any]], token_summary: dict[str, Any]) -> str:
    lines = [
        "# FNM Real Batch Report",
        "",
        "| slug | status | total_tokens | llm_repair_requests | endnotes | endnotes_page | blocking |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in results:
        usage = dict(item.get("usage_summary") or {})
        total_tokens = int((usage.get("total") or {}).get("total_tokens") or 0)
        llm_requests = int(
            ((usage.get("by_stage") or {}).get("llm_repair.cluster_request") or {}).get("request_count") or 0
        )
        visual_toc = dict(item.get("visual_toc") or {})
        endnotes_summary = dict(visual_toc.get("endnotes_summary") or {})
        blocking = ",".join(list(item.get("blocking_reasons") or [])) or "-"
        lines.append(
            f"| {item.get('slug', '')} | {'blocked' if item.get('blocked') else 'ready'} | {total_tokens} | {llm_requests} | "
            f"{'yes' if bool(endnotes_summary.get('present')) else 'no'} | {endnotes_summary.get('container_printed_page') or '-'} | {blocking} |"
        )
    lines.extend(
        [
            "",
            "## Heading Graph",
        ]
    )
    for item in results:
        structure = dict(item.get("structure") or {})
        heading_graph_summary = dict(structure.get("heading_graph_summary") or {})
        if not heading_graph_summary:
            continue
        unresolved = list(heading_graph_summary.get("unresolved_titles_preview") or [])
        conflicts = list(heading_graph_summary.get("boundary_conflict_titles_preview") or [])
        residual = list(heading_graph_summary.get("residual_provisional_titles_preview") or [])
        optimized = int(heading_graph_summary.get("optimized_anchor_count") or 0)
        lines.append(
            f"- {item.get('slug', '')}: optimized={optimized}, unresolved={json.dumps(unresolved, ensure_ascii=False)}, conflicts={json.dumps(conflicts, ensure_ascii=False)}, residual_provisional={json.dumps(residual, ensure_ascii=False)}"
        )
    lines.extend(
        [
            "",
            "## Batch token summary",
            f"- by_stage: `{json.dumps(token_summary.get('by_stage') or {}, ensure_ascii=False)}`",
            f"- by_model: `{json.dumps(token_summary.get('by_model') or {}, ensure_ascii=False)}`",
            f"- total: `{json.dumps(token_summary.get('total') or {}, ensure_ascii=False)}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _process_book(
    book: ExampleBook,
    *,
    stage_callback=None,
) -> dict[str, Any]:
    asset_check = _check_required_assets(book)
    example_dir = _resolve_example_dir(book)
    cleanup = _cleanup_example_results(example_dir)
    base_result: dict[str, Any] = {
        "slug": book.slug,
        "doc_id": book.doc_id,
        "folder": book.folder,
        "asset_check": asset_check,
        "input_assets": _build_input_asset_manifest(asset_check),
        "cleanup": cleanup,
        "all_ok": False,
        "blocked": True,
        "blocking_reasons": [],
        "blocking_details": [],
        "trace_index": [],
        "translation_mode": "placeholder",
        "translation_api_called": False,
        "final_zip": {},
        "module_process": {},
        "progress": _initial_progress(),
        "usage_summary": _merge_usage_summaries({"by_stage": {"translation_test": _usage_zero()}}),
    }
    trace_counters: dict[str, int] = defaultdict(int)
    stage_errors: list[dict[str, Any]] = []

    def _advance(stage: str, status: str, detail: str = "") -> None:
        _append_stage_history(base_result["progress"], stage=stage, status=status, detail=detail)
        if callable(stage_callback):
            stage_callback(
                {
                    "slug": book.slug,
                    "doc_id": book.doc_id,
                    "stage": stage,
                    "status": status,
                    "detail": detail,
                    "updated_at": base_result["progress"]["updated_at"],
                }
            )
        _write_book_outputs(example_dir, base_result)

    def _record_stage_error(stage: str, reason_code: str, exc: Exception | str) -> None:
        message = str(exc or "").strip()
        stage_errors.append({"stage": stage, "reason_code": reason_code, "message": message})
        base_result["blocking_reasons"] = _dedupe_strings(list(base_result.get("blocking_reasons") or []) + [reason_code])
        _advance(stage, "blocked", message)

    if not asset_check.get("ok"):
        base_result["blocking_reasons"] = ["missing_required_assets"]
        _advance("reingest", "blocked", "缺少必需输入文件")
        return base_result

    reingest_result: dict[str, Any] = {}
    visual_result: dict[str, Any] = {}
    pipeline_result: dict[str, Any] = {}
    repair_result: dict[str, Any] = {}
    rebuild_result: dict[str, Any] = {}
    structure: dict[str, Any] = {
        "blocking_reasons": [],
        "structure_state": "review_required",
        "heading_graph_summary": {},
    }
    placeholder_result: dict[str, Any] = {}
    export_result: dict[str, Any] = {}
    snapshot: Any | None = None
    blocked = True

    try:
        reingest_result = reingest_book(
            book,
            rerun_auto_toc=False,
            restore_auto_visual_toc=False,
            rebuild_fnm=False,
        )
        base_result["reingest"] = reingest_result
        _advance("reingest", "done", "已从源 PDF/JSON/MD/目录文件重置输入")
    except Exception as exc:
        _record_stage_error("reingest", "reingest_exception", exc)

    pdf_path = str(get_pdf_path(book.doc_id) or "").strip()
    try:
        if pdf_path:
            visual_result = run_auto_visual_toc_for_doc(book.doc_id, pdf_path) or {}
        base_result["visual_toc"] = visual_result
        _persist_traces(
            example_dir=example_dir,
            traces=list(visual_result.get("llm_traces") or []),
            trace_counters=trace_counters,
            trace_index=base_result["trace_index"],
        )
        _advance("visual_toc", "done", str(visual_result.get("status") or ""))
        if str(visual_result.get("status") or "") == "failed":
            base_result["blocking_reasons"] = _dedupe_strings(list(base_result.get("blocking_reasons") or []) + ["visual_toc_failed"])
    except Exception as exc:
        visual_result = {"status": "failed", "error": str(exc)}
        base_result["visual_toc"] = visual_result
        _record_stage_error("visual_toc", "visual_toc_exception", exc)

    try:
        pipeline_result = run_fnm_pipeline(book.doc_id) or {}
        base_result["pipeline"] = pipeline_result
        _advance("fnm_pipeline", "done", str(pipeline_result.get("structure_state") or ""))
        if not bool(pipeline_result.get("ok")):
            base_result["blocking_reasons"] = _dedupe_strings(
                list(base_result.get("blocking_reasons") or []) + list(pipeline_result.get("blocking_reasons") or []) + ["fnm_pipeline_failed"]
            )
    except Exception as exc:
        pipeline_result = {"ok": False, "error": str(exc), "blocking_reasons": ["fnm_pipeline_exception"]}
        base_result["pipeline"] = pipeline_result
        _record_stage_error("fnm_pipeline", "fnm_pipeline_exception", exc)

    try:
        repair_result = run_llm_repair(
            book.doc_id,
            slug=book.slug,
            cluster_limit=None,
            auto_apply=True,
        ) or {}
        base_result["llm_repair"] = repair_result
        _persist_traces(
            example_dir=example_dir,
            traces=list(repair_result.get("llm_traces") or []),
            trace_counters=trace_counters,
            trace_index=base_result["trace_index"],
        )
        _advance("llm_repair", "done", f"auto_applied={int(repair_result.get('auto_applied_count') or 0)}")
    except Exception as exc:
        repair_result = {"error": str(exc), "auto_applied_count": 0, "usage_summary": {}}
        base_result["llm_repair"] = repair_result
        _record_stage_error("llm_repair", "llm_repair_exception", exc)

    try:
        if int(repair_result.get("auto_applied_count") or 0) > 0:
            rebuild_result = run_fnm_pipeline(book.doc_id) or {}
        base_result["rebuild"] = rebuild_result
        _advance("fnm_pipeline_rebuild", "done", str(rebuild_result.get("structure_state") or "skipped"))
    except Exception as exc:
        rebuild_result = {"ok": False, "error": str(exc), "blocking_reasons": ["fnm_pipeline_rebuild_exception"]}
        base_result["rebuild"] = rebuild_result
        _record_stage_error("fnm_pipeline_rebuild", "fnm_pipeline_rebuild_exception", exc)

    try:
        snapshot = load_fnm_doc_structure(book.doc_id, slug=book.doc_id)
        structure = verify_fnm_structure(book.doc_id, snapshot=snapshot)
        base_result["structure"] = structure
        base_result["blocking_reasons"] = _dedupe_strings(
            list(base_result.get("blocking_reasons") or []) + list(structure.get("blocking_reasons") or [])
        )
        _advance("structure_verify", "done", str(structure.get("structure_state") or ""))
    except Exception as exc:
        structure = {
            "blocking_reasons": _dedupe_strings(list(base_result.get("blocking_reasons") or []) + ["structure_verify_exception"]),
            "structure_state": "review_required",
            "heading_graph_summary": {},
            "export_ready_test": False,
            "chapter_endnote_region_alignment_ok": True,
            "toc_semantic_contract_ok": True,
            "manual_toc_required": False,
        }
        base_result["structure"] = structure
        _record_stage_error("structure_verify", "structure_verify_exception", exc)

    try:
        placeholder_result = materialize_test_placeholders(book.doc_id)
        base_result["placeholders"] = placeholder_result
        _advance("placeholder_translate", "done", f"translated_paras={int(placeholder_result.get('translated_paras') or 0)}")
    except Exception as exc:
        placeholder_result = {"ok": False, "error": str(exc)}
        base_result["placeholders"] = placeholder_result
        _record_stage_error("placeholder_translate", "placeholder_translate_exception", exc)

    try:
        export_result = verify_export(
            book.doc_id,
            structure=structure,
            snapshot=snapshot,
            example_folder=book.folder,
            require_zip_persist=True,
            doc_slug=book.slug,
            doc_name=book.doc_name,
        )
        blocked = bool(export_result.get("blocked"))
        base_result["export"] = export_result
        if blocked:
            base_result["blocking_reasons"] = _dedupe_strings(
                list(base_result.get("blocking_reasons") or []) + list(export_result.get("blocking_reasons") or []) + [str(export_result.get("reason") or "export_blocked")]
            )
        _advance("export_verify", "done", str(export_result.get("reason") or "ok"))
    except Exception as exc:
        blocked = True
        export_result = {
            "ok": False,
            "blocked": True,
            "reason": "export_verify_exception",
            "blocking_reasons": _dedupe_strings(list(base_result.get("blocking_reasons") or []) + ["export_verify_exception"]),
            "latest_export_zip_path": "",
        }
        base_result["export"] = export_result
        _record_stage_error("export_verify", "export_verify_exception", exc)

    source_zip_path = _resolve_source_zip_path(example_dir, export_result, blocked)
    fallback_zip_bytes: bytes | None = None
    if source_zip_path is None:
        try:
            fallback_zip_bytes = build_fnm_obsidian_export_zip(book.doc_id, snapshot=snapshot)
        except Exception:
            fallback_zip_bytes = None
    zip_result = _write_zip_aliases(
        example_dir=example_dir,
        slug=book.slug,
        blocked=blocked,
        source_zip_path=source_zip_path,
        fallback_zip_bytes=fallback_zip_bytes,
    )
    base_result["final_zip"] = dict(zip_result)
    base_result["slug_zip_path"] = zip_result.get("slug_zip_path")
    base_result["alias_zip_path"] = zip_result.get("alias_zip_path")
    base_result["zip_written"] = bool(zip_result.get("written"))
    base_result["zip_reason"] = str(zip_result.get("reason") or "")
    _advance("zip_finalize", "done", str(zip_result.get("reason") or "ok"))

    visual_usage = dict(visual_result.get("usage_summary") or {})
    llm_usage = dict(repair_result.get("usage_summary") or {})
    translation_test_usage = {"by_stage": {"translation_test": _usage_zero()}, "by_model": {}, "total": _usage_zero()}
    base_result["usage_summary"] = _merge_usage_summaries(visual_usage, llm_usage, translation_test_usage)
    base_result["blocked"] = bool(blocked or base_result.get("blocking_reasons"))
    base_result["all_ok"] = bool(
        not base_result["blocked"]
        and base_result["zip_written"]
        and bool(pipeline_result.get("ok"))
    )
    base_result["blocking_reasons"] = _dedupe_strings(list(base_result.get("blocking_reasons") or []))
    try:
        base_result["module_process"] = _build_module_process_report(
            book.doc_id,
            structure=structure,
            export_result=export_result,
            trace_index=list(base_result.get("trace_index") or []),
        )
    except Exception as exc:
        base_result["module_process"] = {
            "error": str(exc),
        }
    base_result["blocking_details"] = _build_blocking_details(
        book.doc_id,
        structure=structure,
        export_result=export_result,
        visual_result=visual_result,
        trace_index=list(base_result.get("trace_index") or []),
        stage_errors=stage_errors,
        blocking_reasons=list(base_result.get("blocking_reasons") or []),
    )
    _advance("report_write", "done", "单书结果、报告、进度均已写入")
    return base_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="真实视觉 + 真实LLM修补批跑脚本。")
    parser.add_argument("--slug", default="", help="仅处理指定 slug")
    parser.add_argument("--folder", default="", help="仅处理指定 folder")
    parser.add_argument("--doc-id", default="", help="仅处理指定 doc_id")
    parser.add_argument("--group", default="all", choices=["baseline", "extension", "all"])
    parser.add_argument("--include-all", action="store_true", help="包含 manifest 中默认批次外的样本")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 本")
    parser.add_argument("--batch-tag", default="", help="输出目录标签；默认时间戳")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    books = select_example_books(
        include_all=bool(args.include_all),
        group=str(args.group or ""),
        slug=str(args.slug or ""),
        folder=str(args.folder or ""),
        doc_id=str(args.doc_id or ""),
    )
    limit = max(0, int(args.limit or 0))
    if limit > 0:
        books = books[:limit]
    if not books:
        print(json.dumps({"processed": 0, "error": "未找到匹配样本"}, ensure_ascii=False))
        return 1

    batch_tag = str(args.batch_tag or "").strip() or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_ROOT / batch_tag
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    _write_batch_runtime_status(
        output_dir,
        {
            "status": "running",
            "current_slug": "",
            "current_stage": "",
            "updated_at": _now_iso(),
            "processed": 0,
            "total": len(books),
        },
    )

    def _stage_callback(payload: dict[str, Any]) -> None:
        _write_batch_runtime_status(
            output_dir,
            {
                "status": "running",
                "current_slug": str(payload.get("slug") or ""),
                "current_doc_id": str(payload.get("doc_id") or ""),
                "current_stage": str(payload.get("stage") or ""),
                "current_stage_status": str(payload.get("status") or ""),
                "current_stage_detail": str(payload.get("detail") or ""),
                "updated_at": str(payload.get("updated_at") or _now_iso()),
                "processed": len(results),
                "total": len(books),
            },
        )

    batch_outputs: dict[str, Any] = {}
    for book in books:
        print(f"[{book.slug}] running...", flush=True)
        result = _process_book(book, stage_callback=_stage_callback)
        results.append(result)
        batch_outputs = _write_batch_outputs(output_dir, results) or {}
        _write_batch_runtime_status(
            output_dir,
            {
                "status": "running",
                "current_slug": book.slug,
                "current_doc_id": book.doc_id,
                "current_stage": "book_complete",
                "current_stage_status": "done",
                "current_stage_detail": "单书已完成并刷新批次汇总",
                "updated_at": _now_iso(),
                "processed": len(results),
                "total": len(books),
            },
        )

    summary = {
        "processed": len(results),
        "passed": sum(1 for item in results if bool(item.get("all_ok"))),
        "blocked": sum(1 for item in results if bool(item.get("blocked"))),
        "results_path": str(batch_outputs.get("results_path") or output_dir / "results.json"),
        "token_summary_path": str(batch_outputs.get("token_summary_path") or output_dir / "token_summary.json"),
        "batch_report_path": str(batch_outputs.get("batch_report_path") or output_dir / "batch_report.md"),
    }
    _write_batch_runtime_status(
        output_dir,
        {
            "status": "completed",
            "current_slug": "",
            "current_doc_id": "",
            "current_stage": "completed",
            "current_stage_status": "done",
            "current_stage_detail": "全部样本已处理完成",
            "updated_at": _now_iso(),
            "processed": len(results),
            "total": len(books),
            "summary": dict(summary),
        },
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

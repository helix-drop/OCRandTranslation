#!/usr/bin/env python3
"""FNM 样本批量测试脚本。

目标：
1. 清理并重跑 FNM pipeline
2. 不调用真实翻译接口，直接把 body/note unit 写入 test 占位译文
3. 重建 FNM 页面并验证 fnm_obsidian 导出
4. 汇总脚注 / 尾注，尤其是尾注引用与定义是否闭合

默认跑 manifest 中纳入硬门槛的全部样本书。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_EXAMPLE_ROOT = REPO_ROOT / "test_example"
LATEST_EXPORT_ZIP_NAME = "latest.fnm.obsidian.zip"
BLOCKED_EXPORT_ZIP_NAME = "latest.fnm.obsidian.blocked.zip"
LATEST_EXPORT_STATUS_NAME = "latest_export_status.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import list_docs
from document.text_utils import ensure_str
from example_manifest import select_example_books
from FNM_RE import (
    audit_export_for_doc as audit_export_bundle,
    build_doc_status as build_fnm_structure_status,
    build_export_bundle_for_doc as build_fnm_obsidian_export_bundle,
    build_export_zip_for_doc as build_fnm_obsidian_export_zip,
    load_doc_structure as load_fnm_doc_structure,
    run_doc_pipeline as run_fnm_pipeline,
)
from FNM_RE.page_translate import (
    apply_body_unit_translations,
    build_fnm_body_unit_jobs,
    build_fnm_retry_summary,
    rebuild_fnm_diagnostic_page_entries,
    sync_fnm_retry_state,
)
from persistence.sqlite_store import SQLiteRepository
from persistence.storage import load_pages_from_disk
from translation.translate_state import TASK_KIND_FNM, _build_translate_task_meta
from translation.translate_store import _save_translate_state

LOCAL_REF_RE = re.compile(r"\[\^([0-9]+)\]")
LOCAL_DEF_RE = re.compile(r"^\[\^([0-9]+)\]:", re.MULTILINE)
LEGACY_FOOTNOTE_RE = re.compile(r"\[FN-[^\]]+\]", re.IGNORECASE)
LEGACY_ENDNOTE_RE = re.compile(r"\[\^en-[^\]]+\]", re.IGNORECASE)
LEGACY_EN_BRACKET_RE = re.compile(r"\[EN-[^\]]+\]", re.IGNORECASE)
LEGACY_NOTE_TOKEN_RE = re.compile(r"\{\{(?:NOTE_REF|FN_REF|EN_REF):[^}]+\}\}", re.IGNORECASE)
RAW_NOTE_HEADING_RE = re.compile(r"^(?!##\s*)(NOTES|ENDNOTES)\s*$", re.IGNORECASE | re.MULTILINE)
SECTION_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
FORBIDDEN_SECTION_HEAD_PREFIX_RE = re.compile(
    r"^\d+\.\s*(?:ibid|cf\.?|see|supra|infra)\b",
    re.IGNORECASE,
)
SECTION_HEAD_INLINE_NOTE_TRACE_RE = re.compile(
    r"(?:<sup>|\[\^[^\]]+\]|\$\s*\^\{[^}]+\}\s*\$)",
    re.IGNORECASE,
)


def _numeric_first_sort_key(value: str) -> tuple[int, int | str]:
    text = str(value or "").strip()
    if text.isdigit():
        return (0, int(text))
    return (1, text)


def _normalize_text_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    no_accents = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch.lower() for ch in no_accents if ch.isalnum())


def _is_biopolitics_target(
    *,
    doc_slug: str = "",
    doc_name: str = "",
    chapter_titles: list[str] | None = None,
) -> bool:
    if _normalize_text_key(doc_slug) == "biopolitics":
        return True
    normalized_name = _normalize_text_key(doc_name)
    if "naissancedelabiopolitique" in normalized_name:
        return True
    normalized_titles = {_normalize_text_key(title) for title in (chapter_titles or [])}
    return (
        "coursannee19781979" in normalized_titles
        and "lecondu10janvier1979" in normalized_titles
    )


def _build_chapter_endnote_region_audit(
    chapters: list[dict[str, Any]],
    regions: list[dict[str, Any]],
) -> dict[str, Any]:
    sorted_chapters = sorted(
        [chapter for chapter in (chapters or []) if isinstance(chapter, dict)],
        key=lambda row: int(row.get("start_page") or 0),
    )
    chapter_title_by_id = {
        str(chapter.get("chapter_id") or ""): str(chapter.get("title") or "").strip()
        for chapter in sorted_chapters
    }
    next_start_by_chapter_id: dict[str, int | None] = {}
    for idx, chapter in enumerate(sorted_chapters):
        chapter_id = str(chapter.get("chapter_id") or "")
        if not chapter_id:
            continue
        next_start_by_chapter_id[chapter_id] = (
            int(sorted_chapters[idx + 1].get("start_page") or 0)
            if idx + 1 < len(sorted_chapters)
            else None
        )
    rows: list[dict[str, Any]] = []
    for region in sorted(
        [row for row in (regions or []) if isinstance(row, dict)],
        key=lambda row: int(row.get("start_page") or 0),
    ):
        if str(region.get("region_kind") or "") != "chapter_endnotes":
            continue
        chapter_id = str(region.get("bound_chapter_id") or "")
        next_start = next_start_by_chapter_id.get(chapter_id)
        start_page = int(region.get("start_page") or 0)
        end_page = int(region.get("end_page") or 0)
        not_cross_next = bool(
            next_start is None
            or int(next_start) <= start_page
            or end_page < int(next_start)
        )
        rows.append(
            {
                "region_id": str(region.get("region_id") or ""),
                "chapter_id": chapter_id,
                "chapter_title": chapter_title_by_id.get(chapter_id, ""),
                "start_page": start_page,
                "end_page": end_page,
                "next_chapter_start_page": int(next_start) if next_start is not None else None,
                "not_cross_next_chapter": not_cross_next,
                "region_start_first_source_marker": str(region.get("region_start_first_source_marker") or ""),
                "region_first_note_item_marker": str(region.get("region_first_note_item_marker") or ""),
                "region_marker_alignment_ok": (
                    bool(region.get("region_marker_alignment_ok"))
                    if region.get("region_marker_alignment_ok") is not None
                    else None
                ),
            }
        )
    cross_rows = [row for row in rows if not bool(row.get("not_cross_next_chapter"))]
    return {
        "rows": rows,
        "boundary_ok": len(cross_rows) == 0,
        "cross_next_chapter_count": len(cross_rows),
        "cross_next_chapter_preview": cross_rows[:8],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量测试 FNM 五书脚注/尾注与导出。")
    parser.add_argument(
        "--all-docs",
        action="store_true",
        help="测试数据库中的全部文档；默认只跑 manifest 中默认批测集合。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="只跑前 N 本，便于先做小范围试跑。",
    )
    parser.add_argument(
        "--group",
        choices=("default", "baseline", "extension", "all"),
        default="default",
        help="只测试 manifest 中指定分组；默认跑 include_in_default_batch=true 的全部样本。",
    )
    parser.add_argument(
        "--slug",
        default="",
        help="只测试 manifest 中指定 slug。",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "output" / "fnm_batch_test_result.json"),
        help="JSON 结果输出路径。",
    )
    return parser.parse_args()


def list_documents() -> list[dict[str, Any]]:
    docs = list_docs()
    normalized: list[dict[str, Any]] = []
    for doc in docs:
        normalized.append({
            "id": str(doc.get("id") or "").strip(),
            "name": str(doc.get("name") or "").strip(),
            "page_count": int(doc.get("page_count", 0) or 0),
        })
    return normalized


def select_documents(*, all_docs: bool, limit: int = 0) -> list[dict[str, Any]]:
    docs = list_documents()
    manifest_books = {
        book.doc_id: book
        for book in select_example_books(
            include_all=True,
            group="",
            slug="",
        )
    }
    if all_docs:
        enriched_docs: list[dict[str, Any]] = []
        for doc in docs:
            row = dict(doc)
            book = manifest_books.get(str(doc.get("id") or "").strip())
            if book is not None:
                row["slug"] = book.slug
                row["folder"] = book.folder
                row["group"] = book.group
                row["expected_page_count"] = book.expected_page_count
                row["manifest_doc_name"] = book.doc_name
            enriched_docs.append(row)
        docs = enriched_docs
        docs.sort(key=lambda item: item["name"])
        if limit > 0:
            docs = docs[:limit]
        return docs

    docs_by_id = {doc["id"]: dict(doc) for doc in docs}
    selected_books = [book for book in manifest_books.values() if book.include_in_default_batch]
    selected: list[dict[str, Any]] = []
    for book in selected_books:
        row = dict(docs_by_id.get(book.doc_id) or {})
        row.setdefault("id", book.doc_id)
        row.setdefault("name", book.doc_name)
        row.setdefault("page_count", book.expected_page_count)
        row["slug"] = book.slug
        row["folder"] = book.folder
        row["group"] = book.group
        row["expected_page_count"] = book.expected_page_count
        row["manifest_doc_name"] = book.doc_name
        selected.append(row)
    selected.sort(key=lambda item: item.get("name") or item.get("slug") or "")
    if limit > 0:
        selected = selected[:limit]
    return selected


def select_documents_from_manifest(*, group: str = "", slug: str = "", limit: int = 0) -> list[dict[str, Any]]:
    docs_by_id = {doc["id"]: dict(doc) for doc in list_documents()}
    normalized_group = "" if str(group or "").strip() == "default" else str(group or "").strip()
    selected_books = select_example_books(
        include_all=bool(normalized_group or slug),
        group=normalized_group,
        slug=slug or "",
    )
    selected: list[dict[str, Any]] = []
    for book in selected_books:
        row = dict(docs_by_id.get(book.doc_id) or {})
        row.setdefault("id", book.doc_id)
        row.setdefault("name", book.doc_name)
        row.setdefault("page_count", book.expected_page_count)
        row["slug"] = book.slug
        row["folder"] = book.folder
        row["group"] = book.group
        row["expected_page_count"] = book.expected_page_count
        row["manifest_doc_name"] = book.doc_name
        selected.append(row)
    selected.sort(key=lambda item: item.get("name") or item.get("slug") or "")
    if limit > 0:
        selected = selected[:limit]
    return selected


def _resolve_example_folder(doc_id: str, *, example_folder: str = "") -> str:
    normalized_folder = str(example_folder or "").strip()
    if normalized_folder:
        return normalized_folder
    matched_books = select_example_books(include_all=True, doc_id=str(doc_id or "").strip())
    if not matched_books:
        return ""
    return str(matched_books[0].folder or "").strip()


def _persist_latest_export_zip(doc_id: str, zip_bytes: bytes, *, example_folder: str = "") -> dict[str, Any]:
    normalized_folder = _resolve_example_folder(doc_id, example_folder=example_folder)
    if not normalized_folder:
        return {
            "saved": False,
            "reason": "example_folder_not_found",
            "path": "",
            "folder": "",
        }
    root_path = TEST_EXAMPLE_ROOT.resolve()
    target_dir = (root_path / normalized_folder).resolve()
    if target_dir != root_path and root_path not in target_dir.parents:
        raise ValueError(f"invalid example folder: {normalized_folder}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / LATEST_EXPORT_ZIP_NAME
    target_path.write_bytes(zip_bytes)
    return {
        "saved": True,
        "reason": "",
        "path": str(target_path),
        "folder": normalized_folder,
    }


def _resolve_example_target_dir(doc_id: str, *, example_folder: str = "") -> tuple[Path | None, str]:
    normalized_folder = _resolve_example_folder(doc_id, example_folder=example_folder)
    if not normalized_folder:
        return None, ""
    root_path = TEST_EXAMPLE_ROOT.resolve()
    target_dir = (root_path / normalized_folder).resolve()
    if target_dir != root_path and root_path not in target_dir.parents:
        raise ValueError(f"invalid example folder: {normalized_folder}")
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir, normalized_folder


def _write_latest_export_status(
    doc_id: str,
    *,
    example_folder: str = "",
    status: str,
    reason: str,
    blocking_reasons: list[str] | None = None,
) -> dict[str, Any]:
    target_dir, normalized_folder = _resolve_example_target_dir(doc_id, example_folder=example_folder)
    if target_dir is None:
        return {
            "saved": False,
            "reason": "example_folder_not_found",
            "path": "",
            "folder": "",
        }
    payload = {
        "doc_id": doc_id,
        "status": status,
        "reason": reason,
        "blocking_reasons": [str(item).strip() for item in (blocking_reasons or []) if str(item).strip()],
        "generated_at": int(time.time()),
    }
    status_path = target_dir / LATEST_EXPORT_STATUS_NAME
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "saved": True,
        "reason": "",
        "path": str(status_path),
        "folder": normalized_folder,
    }


def _handle_blocked_export_artifact(
    doc_id: str,
    *,
    example_folder: str = "",
    reason: str,
    blocking_reasons: list[str] | None = None,
) -> dict[str, Any]:
    target_dir, normalized_folder = _resolve_example_target_dir(doc_id, example_folder=example_folder)
    if target_dir is None:
        return {
            "saved": False,
            "path": "",
            "folder": "",
            "reason": "example_folder_not_found",
            "artifact_status": "missing_folder",
            "stale_detected": False,
            "status_file_path": "",
        }
    latest_zip = target_dir / LATEST_EXPORT_ZIP_NAME
    blocked_zip = target_dir / BLOCKED_EXPORT_ZIP_NAME
    stale_detected = latest_zip.exists()
    if blocked_zip.exists():
        blocked_zip.unlink()
    if latest_zip.exists():
        latest_zip.replace(blocked_zip)
    status_info = _write_latest_export_status(
        doc_id,
        example_folder=normalized_folder,
        status="blocked",
        reason=reason,
        blocking_reasons=blocking_reasons,
    )
    return {
        "saved": False,
        "path": "",
        "folder": normalized_folder,
        "reason": reason,
        "artifact_status": "blocked",
        "stale_detected": stale_detected,
        "status_file_path": str(status_info.get("path") or ""),
    }


def clear_fnm_data(doc_id: str) -> None:
    SQLiteRepository().clear_fnm_data(doc_id)


def run_pipeline(doc_id: str) -> dict[str, Any]:
    return run_fnm_pipeline(doc_id)


def _validation_reason_counts(validation: dict[str, Any]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    unresolved = validation.get("unresolved")
    if isinstance(unresolved, list):
        for item in unresolved:
            if not isinstance(item, dict):
                continue
            reason = str(item.get("reason") or item.get("type") or "unknown").strip() or "unknown"
            counter[reason] += 1
    if counter:
        return dict(counter)
    sections = validation.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            for item in section.get("unresolved") or []:
                if not isinstance(item, dict):
                    continue
                reason = str(item.get("reason") or item.get("type") or "unknown").strip() or "unknown"
                counter[reason] += 1
    return dict(counter)


def _normalize_reason_counts(raw_counts: Any) -> dict[str, int]:
    if not isinstance(raw_counts, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, value in raw_counts.items():
        reason = str(key or "").strip()
        if not reason:
            continue
        try:
            count = int(value or 0)
        except Exception:
            continue
        if count <= 0:
            continue
        normalized[reason] = int(normalized.get(reason, 0) or 0) + count
    return normalized


def _normalize_summary_rows(raw_rows: Any, *, limit: int = 0) -> list[dict[str, Any]]:
    if isinstance(raw_rows, tuple):
        rows = list(raw_rows)
    elif isinstance(raw_rows, list):
        rows = raw_rows
    else:
        rows = []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(dict(row) if isinstance(row, dict) else {})
        if limit > 0 and len(normalized) >= limit:
            break
    return normalized


def _collect_module_reason_counts(
    *,
    review_counts: Any,
    blocking_reasons: list[str] | None,
    manual_toc_required: bool,
) -> dict[str, int]:
    counts = _normalize_reason_counts(review_counts)
    for reason in blocking_reasons or []:
        reason_code = str(reason or "").strip()
        if not reason_code:
            continue
        if reason_code not in counts:
            counts[reason_code] = 1
    if manual_toc_required and not (
        "toc_manual_toc_required" in counts
        or "manual_toc_required" in counts
    ):
        counts["toc_manual_toc_required"] = 1
    return counts


def _format_reason_counts(reason_counts: Any) -> str:
    normalized = _normalize_reason_counts(reason_counts)
    if not normalized:
        return "none"
    return ", ".join(
        f"{reason}={count}"
        for reason, count in sorted(
            normalized.items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        )
    )


def verify_fnm_structure(doc_id: str, *, snapshot: Any | None = None) -> dict[str, Any]:
    repo = SQLiteRepository()
    latest_run = repo.get_latest_fnm_run(doc_id)
    if not latest_run:
        return {"ok": False, "error": "no_fnm_run"}

    pages = repo.list_fnm_pages(doc_id)
    chapters = repo.list_fnm_chapters(doc_id)
    section_heads = repo.list_fnm_section_heads(doc_id)
    heading_candidates = repo.list_fnm_heading_candidates(doc_id)
    regions = repo.list_fnm_note_regions(doc_id)
    note_items = repo.list_fnm_note_items(doc_id)
    anchors = repo.list_fnm_body_anchors(doc_id)
    links = repo.list_fnm_note_links(doc_id)
    reviews = repo.list_fnm_structure_reviews(doc_id)
    structure_status = build_fnm_structure_status(doc_id, repo=repo, snapshot=snapshot)
    footnote_items = [item for item in note_items if str(item.get("note_kind") or "") == "footnote"]
    endnote_items = [item for item in note_items if str(item.get("note_kind") or "") == "endnote"]
    linked_endnote_ids = {
        str(link.get("note_item_id") or "").strip()
        for link in links
        if str(link.get("note_kind") or "") == "endnote"
        and str(link.get("status") or "") == "matched"
        and str(link.get("note_item_id") or "").strip()
    }
    suppressed_candidates = [
        row for row in heading_candidates
        if bool(row.get("suppressed_as_chapter"))
    ]
    page_role_by_no = {int(page.get("page_no") or 0): str(page.get("page_role") or "") for page in pages}
    partition_heading_conflict_count = sum(
        1
        for row in heading_candidates
        if str(row.get("heading_family_guess") or "") in {"chapter", "section"}
        and page_role_by_no.get(int(row.get("page_no") or 0), "") in {"other", "note", "noise"}
    )

    validation = {}
    raw_validation = latest_run.get("validation_json")
    if raw_validation:
        try:
            validation = json.loads(raw_validation) if isinstance(raw_validation, str) else dict(raw_validation)
        except Exception:
            validation = {}

    toc_export_coverage_summary = dict(structure_status.get("toc_export_coverage_summary") or {})
    missing_body_items_preview = list(toc_export_coverage_summary.get("missing_body_items_preview") or [])
    toc_export_coverage_ok = len(missing_body_items_preview) == 0
    toc_alignment_summary = dict(structure_status.get("toc_alignment_summary") or {})
    toc_semantic_summary = dict(structure_status.get("toc_semantic_summary") or {})
    toc_semantic_contract_ok = bool(structure_status.get("toc_semantic_contract_ok", True))
    toc_semantic_blocking_reasons = [
        str(reason).strip()
        for reason in (structure_status.get("toc_semantic_blocking_reasons") or [])
        if str(reason).strip()
    ]
    chapter_title_alignment_ok = bool(structure_status.get("chapter_title_alignment_ok", True))
    chapter_section_alignment_ok = bool(structure_status.get("chapter_section_alignment_ok", True))
    chapter_endnote_region_alignment_ok = bool(
        structure_status.get("chapter_endnote_region_alignment_ok", True)
    )
    chapter_endnote_region_alignment_summary = dict(
        structure_status.get("chapter_endnote_region_alignment_summary") or {}
    )
    chapter_endnote_region_audit = _build_chapter_endnote_region_audit(chapters, regions)
    base_blocking_reasons = [
        str(item).strip()
        for item in list(structure_status.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    review_counts = _collect_module_reason_counts(
        review_counts=structure_status.get("review_counts"),
        blocking_reasons=base_blocking_reasons,
        manual_toc_required=bool(structure_status.get("manual_toc_required")),
    )
    blocking_reasons = list(base_blocking_reasons)
    if not chapter_endnote_region_alignment_ok:
        blocking_reasons.append("endnote_region_marker_misalignment")
        review_counts["endnote_region_marker_misalignment"] = int(
            review_counts.get("endnote_region_marker_misalignment", 0) or 0
        ) + 1
    if not bool(chapter_endnote_region_audit.get("boundary_ok", True)):
        blocking_reasons.append("endnote_region_cross_next_chapter")
        review_counts["endnote_region_cross_next_chapter"] = int(
            review_counts.get("endnote_region_cross_next_chapter", 0) or 0
        ) + 1
    blocking_reasons = list(dict.fromkeys(blocking_reasons))

    return {
        "ok": bool(
            str(latest_run.get("status") or "") == "done"
            and structure_status.get("structure_state") == "ready"
            and bool(chapter_endnote_region_audit.get("boundary_ok", True))
        ),
        "status": str(latest_run.get("status") or ""),
        "page_count": len(pages),
        "chapter_count": len(chapters),
        "section_head_count": len(section_heads),
        "note_region_count": len(regions),
        "note_item_count": len(note_items),
        "body_anchor_count": len(anchors),
        "note_link_count": len(links),
        "suppressed_chapter_candidate_count": len(suppressed_candidates),
        "partition_heading_conflict_count": partition_heading_conflict_count,
        "review_row_count": len(reviews),
        "footnote_count": len(footnote_items),
        "endnote_count": len(endnote_items),
        "linked_endnote_count": len(linked_endnote_ids),
        "structure_state": structure_status.get("structure_state"),
        "review_counts": review_counts,
        "blocking_reasons": blocking_reasons,
        "link_summary": dict(structure_status.get("link_summary") or {}),
        "page_partition_summary": dict(structure_status.get("page_partition_summary") or {}),
        "chapter_mode_summary": dict(structure_status.get("chapter_mode_summary") or {}),
        "heading_review_summary": dict(structure_status.get("heading_review_summary") or {}),
        "heading_graph_summary": dict(structure_status.get("heading_graph_summary") or {}),
        "chapter_source_summary": dict(structure_status.get("chapter_source_summary") or {}),
        "visual_toc_conflict_count": int(structure_status.get("visual_toc_conflict_count") or 0),
        "toc_export_coverage_summary": {
            "resolved_body_items": int(toc_export_coverage_summary.get("resolved_body_items") or 0),
            "exported_body_items": int(toc_export_coverage_summary.get("exported_body_items") or 0),
            "missing_body_items_preview": missing_body_items_preview[:8],
        },
        "toc_alignment_summary": {
            "chapter_level_body_items": int(toc_alignment_summary.get("chapter_level_body_items") or 0),
            "exported_chapter_count": int(toc_alignment_summary.get("exported_chapter_count") or 0),
            "missing_chapter_titles_preview": list(
                toc_alignment_summary.get("missing_chapter_titles_preview") or []
            )[:8],
            "misleveled_titles_preview": list(
                toc_alignment_summary.get("misleveled_titles_preview") or []
            )[:8],
            "reanchored_titles_preview": list(
                toc_alignment_summary.get("reanchored_titles_preview") or []
            )[:8],
            "missing_section_titles_preview": list(
                toc_alignment_summary.get("missing_section_titles_preview") or []
            )[:8],
        },
        "toc_semantic_summary": {
            "body_item_count": int(toc_semantic_summary.get("body_item_count") or 0),
            "chapter_item_count": int(toc_semantic_summary.get("chapter_item_count") or 0),
            "part_item_count": int(toc_semantic_summary.get("part_item_count") or 0),
            "back_matter_item_count": int(toc_semantic_summary.get("back_matter_item_count") or 0),
            "first_body_pdf_page": int(toc_semantic_summary.get("first_body_pdf_page") or 0),
            "last_body_pdf_page": int(toc_semantic_summary.get("last_body_pdf_page") or 0),
            "body_span_ratio": float(toc_semantic_summary.get("body_span_ratio") or 0.0),
            "nonbody_contamination_count": int(toc_semantic_summary.get("nonbody_contamination_count") or 0),
            "mixed_level_chapter_count": int(toc_semantic_summary.get("mixed_level_chapter_count") or 0),
        },
        "toc_role_summary": dict(structure_status.get("toc_role_summary") or {}),
        "container_titles": list(structure_status.get("container_titles") or []),
        "post_body_titles": list(structure_status.get("post_body_titles") or []),
        "back_matter_titles": list(structure_status.get("back_matter_titles") or []),
        "visual_toc_endnotes_summary": dict(structure_status.get("visual_toc_endnotes_summary") or {}),
        "toc_semantic_contract_ok": bool(toc_semantic_contract_ok),
        "toc_semantic_blocking_reasons": list(toc_semantic_blocking_reasons)[:8],
        "toc_export_coverage_ok": bool(toc_export_coverage_ok),
        "chapter_title_alignment_ok": bool(chapter_title_alignment_ok),
        "chapter_section_alignment_ok": bool(chapter_section_alignment_ok),
        "chapter_endnote_region_alignment_ok": bool(chapter_endnote_region_alignment_ok),
        "chapter_endnote_region_alignment_summary": chapter_endnote_region_alignment_summary,
        "chapter_endnote_region_boundary_ok": bool(chapter_endnote_region_audit.get("boundary_ok", True)),
        "chapter_endnote_region_cross_next_chapter_count": int(
            chapter_endnote_region_audit.get("cross_next_chapter_count") or 0
        ),
        "chapter_endnote_region_cross_next_chapter_preview": _normalize_summary_rows(
            chapter_endnote_region_audit.get("cross_next_chapter_preview"),
            limit=8,
        ),
        "chapter_endnote_region_audit_rows": _normalize_summary_rows(
            chapter_endnote_region_audit.get("rows"),
        ),
        "manual_toc_required": bool(structure_status.get("manual_toc_required")),
        "manual_toc_ready": bool(structure_status.get("manual_toc_ready")),
        "manual_toc_summary": dict(structure_status.get("manual_toc_summary") or {}),
        "chapter_binding_summary": dict(structure_status.get("chapter_binding_summary") or {}),
        "note_capture_summary": dict(structure_status.get("note_capture_summary") or {}),
        "footnote_synthesis_summary": dict(structure_status.get("footnote_synthesis_summary") or {}),
        "chapter_link_contract_summary": dict(structure_status.get("chapter_link_contract_summary") or {}),
        "book_endnote_stream_summary": dict(structure_status.get("book_endnote_stream_summary") or {}),
        "freeze_note_unit_summary": dict(structure_status.get("freeze_note_unit_summary") or {}),
        "chapter_issue_counts": dict(structure_status.get("chapter_issue_counts") or {}),
        "chapter_issue_summary": _normalize_summary_rows(
            structure_status.get("chapter_issue_summary"),
            limit=24,
        ),
        "export_drift_summary": dict(structure_status.get("export_drift_summary") or {}),
        "chapter_local_endnote_contract_ok": bool(structure_status.get("chapter_local_endnote_contract_ok")),
        "export_ready_test": bool(structure_status.get("export_ready_test")),
        "export_ready_real": bool(structure_status.get("export_ready_real")),
        "validation_needs_human_review": bool(validation.get("needs_human_review")),
        "validation_reason_counts": _validation_reason_counts(validation),
    }


def materialize_test_placeholders(doc_id: str) -> dict[str, Any]:
    repo = SQLiteRepository()
    pages, _ = load_pages_from_disk(doc_id)
    units = repo.list_fnm_translation_units(doc_id)
    total_chars = 0
    total_paragraphs = 0
    body_unit_count = 0
    note_unit_count = 0

    for unit_idx, unit in enumerate(units, start=1):
        unit_id = str(unit.get("unit_id") or "").strip()
        kind = str(unit.get("kind") or "").strip()
        if kind == "body":
            body_unit_count += 1
            jobs = build_fnm_body_unit_jobs(unit, pages)
            translated_paragraphs = [ensure_str(job.get("text") or "").strip() for job in jobs]
            payload = apply_body_unit_translations(unit, translated_paragraphs)
            repo.update_fnm_translation_unit(
                doc_id,
                unit_id,
                translated_text=payload["translated_text"],
                status="done",
                error_msg="",
                page_segments=payload["page_segments"],
            )
            total_chars += len(payload["translated_text"])
            total_paragraphs += len(translated_paragraphs)
        else:
            note_unit_count += 1
            translated_text = ensure_str(unit.get("source_text") or "").strip()
            repo.update_fnm_translation_unit(
                doc_id,
                unit_id,
                translated_text=translated_text,
                status="done",
                error_msg="",
            )
            note_id = str(unit.get("note_id") or "").strip()
            if note_id:
                repo.update_fnm_note_translation(doc_id, note_id, translated_text, status="done")
            total_chars += len(translated_text)
            total_paragraphs += 1 if translated_text else 0

    changed_pages = rebuild_fnm_diagnostic_page_entries(doc_id, pages=pages, repo=repo)
    task_meta = _build_translate_task_meta(
        kind=TASK_KIND_FNM,
        label="FNM 测试占位",
        start_bp=1 if units else None,
        progress_mode="unit",
        start_unit_idx=1 if units else None,
        target_bps=list(range(1, len(units) + 1)),
        target_unit_ids=[str(unit.get("unit_id") or "").strip() for unit in units],
    )
    _save_translate_state(
        doc_id,
        running=False,
        stop_requested=False,
        phase="done",
        execution_mode="test",
        total_pages=len(units),
        done_pages=len(units),
        processed_pages=len(units),
        pending_pages=0,
        current_bp=None,
        current_page_idx=len(units),
        translated_chars=total_chars,
        translated_paras=total_paragraphs,
        retry_round=0,
        unresolved_count=0,
        manual_required_count=0,
        next_failed_location=None,
        failed_locations=[],
        manual_required_locations=[],
        last_error="",
        task=task_meta,
    )
    retry_summary = sync_fnm_retry_state(doc_id, repo=repo)
    return {
        "ok": True,
        "body_unit_count": body_unit_count,
        "note_unit_count": note_unit_count,
        "changed_page_count": len(changed_pages),
        "translated_chars": total_chars,
        "translated_paras": total_paragraphs,
        "retry_summary": retry_summary,
    }


def _split_body_and_definition_text(content: str) -> tuple[str, str]:
    body_lines: list[str] = []
    definition_lines: list[str] = []
    in_definition_block = False
    for raw_line in str(content or "").splitlines():
        if LOCAL_DEF_RE.match(raw_line):
            in_definition_block = True
            definition_lines.append(raw_line)
            continue
        if in_definition_block and (raw_line.startswith("    ") or raw_line.startswith("\t")):
            definition_lines.append(raw_line)
            continue
        in_definition_block = False
        body_lines.append(raw_line)
    return "\n".join(body_lines), "\n".join(definition_lines)


def _looks_like_sentence_heading(title: str) -> bool:
    text = re.sub(r"\s+", " ", str(title or "").strip())
    if not text:
        return True
    words = [part for part in text.split(" ") if part]
    if len(words) >= 16 or len(text) >= 110:
        return True
    if text.endswith(("?", "!", ";")):
        return True
    if re.search(r"[.!;]\s+[A-Za-zÀ-ÖØ-öø-ÿ]", text):
        return True
    return False


def _analyze_export_text(content: str) -> dict[str, Any]:
    text = content or ""
    body_text, _definition_text = _split_body_and_definition_text(text)
    def_matches = list(LOCAL_DEF_RE.finditer(text))
    defs = [str(match.group(1) or "").strip() for match in def_matches]
    refs = [
        str(match.group(1) or "").strip()
        for match in LOCAL_REF_RE.finditer(body_text)
    ]
    forbidden_section_headings: list[str] = []
    for match in SECTION_HEADING_RE.finditer(body_text):
        heading_text = re.sub(r"\s+", " ", str(match.group(1) or "").strip())
        if not heading_text:
            continue
        if heading_text == "*":
            forbidden_section_headings.append(heading_text)
            continue
        if FORBIDDEN_SECTION_HEAD_PREFIX_RE.match(heading_text):
            forbidden_section_headings.append(heading_text)
            continue
        if SECTION_HEAD_INLINE_NOTE_TRACE_RE.search(heading_text):
            forbidden_section_headings.append(heading_text)
            continue
        if _looks_like_sentence_heading(heading_text):
            forbidden_section_headings.append(heading_text)
    all_numbers = {
        int(value)
        for value in refs + defs
        if str(value).isdigit()
    }
    starts_at_one = True if not all_numbers else min(all_numbers) == 1
    return {
        "local_ref_total": len(refs),
        "local_def_total": len(defs),
        "unique_local_refs": sorted(set(refs), key=_numeric_first_sort_key),
        "unique_local_defs": sorted(set(defs), key=_numeric_first_sort_key),
        "local_numbering_starts_at_one": starts_at_one,
        "legacy_footnote_ref_count": len(LEGACY_FOOTNOTE_RE.findall(text)),
        "legacy_endnote_ref_count": len(LEGACY_ENDNOTE_RE.findall(text)),
        "legacy_en_bracket_ref_count": len(LEGACY_EN_BRACKET_RE.findall(text)),
        "legacy_note_token_count": len(LEGACY_NOTE_TOKEN_RE.findall(text)),
        "pending_placeholder_count": str(content or "").count("[待翻译]"),
        "raw_note_heading_leak_count": len(RAW_NOTE_HEADING_RE.findall(content or "")),
        "section_heading_total": len(SECTION_HEADING_RE.findall(body_text)),
        "forbidden_section_heading_count": len(forbidden_section_headings),
        "forbidden_section_heading_preview": forbidden_section_headings[:8],
    }


def _first_local_definition_marker(content: str) -> str:
    match = LOCAL_DEF_RE.search(str(content or ""))
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def _build_biopolitics_export_audit(
    *,
    structure: dict[str, Any],
    chapter_stats: list[dict[str, Any]],
    chapter_files: dict[str, str],
) -> dict[str, Any]:
    title_to_first_def: dict[str, str] = {}
    for row in chapter_stats:
        title_key = _normalize_text_key(str(row.get("title") or ""))
        first_def = str(row.get("first_local_def_marker") or "")
        if title_key and first_def and title_key not in title_to_first_def:
            title_to_first_def[title_key] = first_def

    tri_rows: list[dict[str, Any]] = []
    for row in list(structure.get("chapter_endnote_region_audit_rows") or []):
        chapter_title = str(row.get("chapter_title") or "")
        export_first = title_to_first_def.get(_normalize_text_key(chapter_title), "")
        source_marker = str(row.get("region_start_first_source_marker") or "")
        first_item_marker = str(row.get("region_first_note_item_marker") or "")
        markers_present = bool(source_marker and first_item_marker and export_first)
        tri_ok = bool(markers_present and source_marker == first_item_marker == export_first)
        tri_rows.append(
            {
                "chapter_title": chapter_title,
                "start_page": int(row.get("start_page") or 0),
                "source_marker": source_marker,
                "first_note_item_marker": first_item_marker,
                "first_export_definition_marker": export_first,
                "markers_present": markers_present,
                "tri_alignment_ok": tri_ok,
            }
        )
    tri_missing = [row for row in tri_rows if not bool(row.get("markers_present"))]
    tri_misaligned = [
        row for row in tri_rows
        if bool(row.get("markers_present")) and not bool(row.get("tri_alignment_ok"))
    ]
    tri_alignment_ok = len(tri_missing) == 0 and len(tri_misaligned) == 0

    chapter_contract_rows: list[dict[str, Any]] = []
    for prefix in ("chapters/002-", "chapters/004-", "chapters/006-"):
        chapter_row = next(
            (row for row in chapter_stats if str(row.get("path") or "").startswith(prefix)),
            None,
        )
        first_def_marker = str((chapter_row or {}).get("first_local_def_marker") or "")
        chapter_ok = bool(chapter_row is not None and first_def_marker == "1")
        chapter_contract_rows.append(
            {
                "prefix": prefix,
                "path": str((chapter_row or {}).get("path") or ""),
                "title": str((chapter_row or {}).get("title") or ""),
                "first_export_definition_marker": first_def_marker,
                "ok": chapter_ok,
            }
        )
    chapter_contract_ok = all(bool(row.get("ok")) for row in chapter_contract_rows)

    keyword_source_row = next(
        (
            row for row in chapter_stats
            if _normalize_text_key(str(row.get("title") or "")) == _normalize_text_key("Leçon du 10 janvier 1979")
        ),
        None,
    )
    if keyword_source_row is None:
        keyword_source_row = next(
            (row for row in chapter_contract_rows if str(row.get("prefix") or "") == "chapters/002-"),
            None,
        )
    keyword_source_path = str((keyword_source_row or {}).get("path") or "")
    chapter_002_text = str(chapter_files.get(keyword_source_path) or "")
    keyword_hits = {
        "freud": bool(re.search(r"\bfreud\b", chapter_002_text, re.IGNORECASE)),
        "acheronta": bool(re.search(r"\bacheronta\b", chapter_002_text, re.IGNORECASE)),
        "virgil_or_virgile": bool(re.search(r"\bvirgil(?:e)?\b", chapter_002_text, re.IGNORECASE)),
    }
    keyword_recovery_ok = all(keyword_hits.values())

    boundary_ok = bool(structure.get("chapter_endnote_region_boundary_ok", True))
    overall_ok = bool(boundary_ok and tri_alignment_ok and chapter_contract_ok and keyword_recovery_ok)

    return {
        "applicable": True,
        "ok": overall_ok,
        "boundary_ok": boundary_ok,
        "tri_alignment_ok": tri_alignment_ok,
        "tri_alignment_total": len(tri_rows),
        "tri_alignment_misaligned_count": len(tri_misaligned),
        "tri_alignment_missing_marker_count": len(tri_missing),
        "tri_alignment_misaligned_preview": tri_misaligned[:8],
        "tri_alignment_missing_preview": tri_missing[:8],
        "chapter_contract_ok_002_004_006": chapter_contract_ok,
        "chapter_contract_rows_002_004_006": chapter_contract_rows,
        "keyword_recovery_ok": keyword_recovery_ok,
        "keyword_recovery_hits": keyword_hits,
    }


def verify_export(
    doc_id: str,
    *,
    structure: dict[str, Any],
    snapshot: Any | None = None,
    example_folder: str = "",
    require_zip_persist: bool = False,
    doc_slug: str = "",
    doc_name: str = "",
) -> dict[str, Any]:
    if bool(structure.get("manual_toc_required")):
        blocked_artifact = _handle_blocked_export_artifact(
            doc_id,
            example_folder=example_folder,
            reason="manual_toc_required",
            blocking_reasons=list(structure.get("blocking_reasons") or []),
        )
        return {
            "ok": False,
            "blocked": True,
            "reason": "manual_toc_required",
            "structure_state": structure.get("structure_state"),
            "blocking_reasons": list(structure.get("blocking_reasons") or []),
            "execution_mode": "test",
            "latest_export_zip_saved": False,
            "latest_export_zip_path": "",
            "latest_export_zip_folder": str(blocked_artifact.get("folder") or ""),
            "latest_export_zip_reason": "manual_toc_required",
            "stale_export_artifact_detected": bool(blocked_artifact.get("stale_detected")),
            "export_artifact_status": str(blocked_artifact.get("artifact_status") or "blocked"),
            "latest_export_status_path": str(blocked_artifact.get("status_file_path") or ""),
            "biopolitics_export_contract_ok": True,
            "biopolitics_export_audit": {"applicable": False, "ok": True},
        }
    if not bool(structure.get("chapter_endnote_region_alignment_ok", True)):
        blocked_artifact = _handle_blocked_export_artifact(
            doc_id,
            example_folder=example_folder,
            reason="endnote_alignment_export_blocked",
            blocking_reasons=list(structure.get("blocking_reasons") or []),
        )
        return {
            "ok": False,
            "blocked": True,
            "reason": "endnote_alignment_export_blocked",
            "structure_state": structure.get("structure_state"),
            "blocking_reasons": list(structure.get("blocking_reasons") or []),
            "execution_mode": "test",
            "latest_export_zip_saved": False,
            "latest_export_zip_path": "",
            "latest_export_zip_folder": str(blocked_artifact.get("folder") or ""),
            "latest_export_zip_reason": "endnote_alignment_export_blocked",
            "stale_export_artifact_detected": bool(blocked_artifact.get("stale_detected")),
            "export_artifact_status": str(blocked_artifact.get("artifact_status") or "blocked"),
            "latest_export_status_path": str(blocked_artifact.get("status_file_path") or ""),
            "biopolitics_export_contract_ok": True,
            "biopolitics_export_audit": {"applicable": False, "ok": True},
        }
    if not bool(structure.get("toc_semantic_contract_ok", True)):
        blocked_artifact = _handle_blocked_export_artifact(
            doc_id,
            example_folder=example_folder,
            reason="semantic_export_blocked",
            blocking_reasons=list(structure.get("blocking_reasons") or []),
        )
        return {
            "ok": False,
            "blocked": True,
            "reason": "semantic_export_blocked",
            "structure_state": structure.get("structure_state"),
            "blocking_reasons": list(structure.get("blocking_reasons") or []),
            "execution_mode": "test",
            "latest_export_zip_saved": False,
            "latest_export_zip_path": "",
            "latest_export_zip_folder": str(blocked_artifact.get("folder") or ""),
            "latest_export_zip_reason": "semantic_export_blocked",
            "stale_export_artifact_detected": bool(blocked_artifact.get("stale_detected")),
            "export_artifact_status": str(blocked_artifact.get("artifact_status") or "blocked"),
            "latest_export_status_path": str(blocked_artifact.get("status_file_path") or ""),
            "biopolitics_export_contract_ok": True,
            "biopolitics_export_audit": {"applicable": False, "ok": True},
        }
    if not bool(structure.get("export_ready_test")):
        blocked_artifact = _handle_blocked_export_artifact(
            doc_id,
            example_folder=example_folder,
            reason="structure_review_required",
            blocking_reasons=list(structure.get("blocking_reasons") or []),
        )
        return {
            "ok": False,
            "blocked": True,
            "reason": "structure_review_required",
            "structure_state": structure.get("structure_state"),
            "blocking_reasons": list(structure.get("blocking_reasons") or []),
            "execution_mode": "test",
            "latest_export_zip_saved": False,
            "latest_export_zip_path": "",
            "latest_export_zip_folder": str(blocked_artifact.get("folder") or ""),
            "latest_export_zip_reason": "structure_review_required",
            "stale_export_artifact_detected": bool(blocked_artifact.get("stale_detected")),
            "export_artifact_status": str(blocked_artifact.get("artifact_status") or "blocked"),
            "latest_export_status_path": str(blocked_artifact.get("status_file_path") or ""),
            "biopolitics_export_contract_ok": True,
            "biopolitics_export_audit": {"applicable": False, "ok": True},
        }
    bundle = build_fnm_obsidian_export_bundle(doc_id, snapshot=snapshot)
    files = dict(bundle.get("files") or {})
    chapters = list(bundle.get("chapters") or [])
    chapter_files = dict(bundle.get("chapter_files") or {})
    export_semantic_contract_ok = bool(bundle.get("export_semantic_contract_ok", True))
    front_matter_leak_detected = bool(bundle.get("front_matter_leak_detected", False))
    toc_residue_detected = bool(bundle.get("toc_residue_detected", False))
    mid_paragraph_heading_detected = bool(bundle.get("mid_paragraph_heading_detected", False))
    duplicate_paragraph_detected = bool(bundle.get("duplicate_paragraph_detected", False))
    zip_bytes = build_fnm_obsidian_export_zip(doc_id, snapshot=snapshot)
    zip_persist = _persist_latest_export_zip(doc_id, zip_bytes, example_folder=example_folder)
    latest_export_zip_saved = bool(zip_persist.get("saved"))
    latest_export_zip_path = str(zip_persist.get("path") or "")
    latest_export_zip_folder = str(zip_persist.get("folder") or "")
    latest_export_zip_reason = str(zip_persist.get("reason") or "")
    latest_export_status = _write_latest_export_status(
        doc_id,
        example_folder=example_folder,
        status="ready",
        reason="ok",
        blocking_reasons=[],
    )
    if latest_export_zip_folder:
        blocked_zip = TEST_EXAMPLE_ROOT / latest_export_zip_folder / BLOCKED_EXPORT_ZIP_NAME
        if blocked_zip.exists():
            blocked_zip.unlink()

    chapter_stats: list[dict[str, Any]] = []
    chapter_titles = [str(chapter.get("title") or "").strip() for chapter in chapters]
    all_unique_local_refs: set[str] = set()
    all_unique_local_defs: set[str] = set()
    total_local_ref_total = 0
    total_local_def_total = 0
    total_pending_placeholders = 0
    total_note_heading_leaks = 0
    total_legacy_footnote_refs = 0
    total_legacy_endnote_refs = 0
    total_legacy_en_bracket_refs = 0
    total_legacy_note_tokens = 0
    total_forbidden_section_headings = 0
    chapter_local_contract_ok = True
    for chapter in chapters:
        path = str(chapter.get("path") or "").strip()
        content = str(chapter_files.get(path) or "")
        stats = _analyze_export_text(content)
        first_local_def_marker = _first_local_definition_marker(content)
        unique_refs = set(stats["unique_local_refs"])
        unique_defs = set(stats["unique_local_defs"])
        orphan_defs = sorted(unique_defs - unique_refs, key=_numeric_first_sort_key)
        orphan_refs = sorted(unique_refs - unique_defs, key=_numeric_first_sort_key)
        chapter_ok = (
            bool(stats.get("local_numbering_starts_at_one"))
            and not orphan_defs
            and not orphan_refs
            and int(stats.get("legacy_footnote_ref_count", 0) or 0) == 0
            and int(stats.get("legacy_endnote_ref_count", 0) or 0) == 0
            and int(stats.get("legacy_en_bracket_ref_count", 0) or 0) == 0
            and int(stats.get("legacy_note_token_count", 0) or 0) == 0
            and int(stats.get("raw_note_heading_leak_count", 0) or 0) == 0
            and int(stats.get("forbidden_section_heading_count", 0) or 0) == 0
        )
        chapter_local_contract_ok = chapter_local_contract_ok and chapter_ok
        chapter_stats.append({
            "title": str(chapter.get("title") or "").strip(),
            "path": path,
            "first_local_def_marker": first_local_def_marker,
            "chapter_local_contract_ok": chapter_ok,
            "orphan_local_definitions": orphan_defs[:10],
            "orphan_local_refs": orphan_refs[:10],
            **stats,
        })
        all_unique_local_refs.update(stats["unique_local_refs"])
        all_unique_local_defs.update(stats["unique_local_defs"])
        total_local_ref_total += int(stats["local_ref_total"])
        total_local_def_total += int(stats["local_def_total"])
        total_pending_placeholders += int(stats["pending_placeholder_count"])
        total_note_heading_leaks += int(stats["raw_note_heading_leak_count"])
        total_legacy_footnote_refs += int(stats["legacy_footnote_ref_count"])
        total_legacy_endnote_refs += int(stats["legacy_endnote_ref_count"])
        total_legacy_en_bracket_refs += int(stats["legacy_en_bracket_ref_count"])
        total_legacy_note_tokens += int(stats["legacy_note_token_count"])
        total_forbidden_section_headings += int(stats.get("forbidden_section_heading_count", 0) or 0)

    orphan_local_definitions = sorted(
        all_unique_local_defs - all_unique_local_refs,
        key=_numeric_first_sort_key,
    )
    orphan_local_refs = sorted(
        all_unique_local_refs - all_unique_local_defs,
        key=_numeric_first_sort_key,
    )
    note_rows = SQLiteRepository().list_fnm_diagnostic_notes(doc_id)
    if note_rows:
        expected_note_count = sum(
            1 for note in note_rows
            if str(note.get("kind") or "") in {"footnote", "endnote"}
        )
    else:
        expected_note_count = int(
            (structure.get("link_summary") or {}).get(
                "matched",
                int(structure.get("linked_endnote_count", 0) or 0) + int(structure.get("footnote_count", 0) or 0),
            ) or 0
        )
    local_link_ok = (
        not orphan_local_definitions
        and not orphan_local_refs
        and (
            (total_local_def_total > 0 and total_local_ref_total > 0)
            if expected_note_count > 0
            else (total_local_def_total == 0 and total_local_ref_total == 0)
        )
    )
    legacy_contract_ok = (
        total_legacy_footnote_refs == 0
        and total_legacy_endnote_refs == 0
        and total_legacy_en_bracket_refs == 0
        and total_legacy_note_tokens == 0
    )
    biopolitics_export_audit: dict[str, Any] = {"applicable": False, "ok": True}
    if _is_biopolitics_target(
        doc_slug=doc_slug,
        doc_name=doc_name,
        chapter_titles=chapter_titles,
    ):
        biopolitics_export_audit = _build_biopolitics_export_audit(
            structure=structure,
            chapter_stats=chapter_stats,
            chapter_files=chapter_files,
        )
    biopolitics_export_contract_ok = bool(biopolitics_export_audit.get("ok", True))
    chapter_local_contract_ok = (
        chapter_local_contract_ok
        and local_link_ok
        and legacy_contract_ok
        and biopolitics_export_contract_ok
    )
    export_drift_summary = {
        "legacy_footnote_ref_count": total_legacy_footnote_refs,
        "legacy_endnote_ref_count": total_legacy_endnote_refs,
        "legacy_en_bracket_ref_count": total_legacy_en_bracket_refs,
        "legacy_note_token_count": total_legacy_note_tokens,
        "orphan_local_definition_count": len(orphan_local_definitions),
        "orphan_local_ref_count": len(orphan_local_refs),
    }
    preliminary_export_ok = (
        total_pending_placeholders == 0
        and total_note_heading_leaks == 0
        and total_forbidden_section_headings == 0
        and chapter_local_contract_ok
        and (
            latest_export_zip_saved
            if require_zip_persist
            else True
        )
    )
    full_audit_report = audit_export_bundle(
        doc_id=doc_id,
        slug=doc_slug,
        zip_path=latest_export_zip_path,
        zip_bytes=zip_bytes,
        repo=SQLiteRepository(),
    )
    full_audit_can_ship = bool(full_audit_report.get("can_ship"))
    full_audit_blocking_issue_count = int(full_audit_report.get("blocking_issue_count") or 0)
    export_ok = preliminary_export_ok and full_audit_can_ship

    return {
        "ok": export_ok,
        "blocked": False,
        "file_count": len(files),
        "chapter_count": len(chapters),
        "zip_size": len(zip_bytes),
        "execution_mode": "test",
        "local_ref_total": total_local_ref_total,
        "local_def_total": total_local_def_total,
        "unique_local_ref_count": len(all_unique_local_refs),
        "unique_local_def_count": len(all_unique_local_defs),
        "orphan_local_definition_count": len(orphan_local_definitions),
        "orphan_local_ref_count": len(orphan_local_refs),
        "orphan_local_definitions_preview": orphan_local_definitions[:10],
        "orphan_local_refs_preview": orphan_local_refs[:10],
        "pending_placeholder_count": total_pending_placeholders,
        "raw_note_heading_leak_count": total_note_heading_leaks,
        "legacy_footnote_ref_count": total_legacy_footnote_refs,
        "legacy_endnote_ref_count": total_legacy_endnote_refs,
        "legacy_en_bracket_ref_count": total_legacy_en_bracket_refs,
        "legacy_note_token_count": total_legacy_note_tokens,
        "forbidden_section_heading_count": total_forbidden_section_headings,
        "expected_note_count": expected_note_count,
        "chapter_local_endnote_contract_ok": chapter_local_contract_ok,
        "export_semantic_contract_ok": export_semantic_contract_ok,
        "front_matter_leak_detected": front_matter_leak_detected,
        "toc_residue_detected": toc_residue_detected,
        "mid_paragraph_heading_detected": mid_paragraph_heading_detected,
        "duplicate_paragraph_detected": duplicate_paragraph_detected,
        "preliminary_export_ok": preliminary_export_ok,
        "biopolitics_export_contract_ok": biopolitics_export_contract_ok,
        "biopolitics_export_audit": biopolitics_export_audit,
        "export_drift_summary": export_drift_summary,
        "latest_export_zip_saved": latest_export_zip_saved,
        "latest_export_zip_path": latest_export_zip_path,
        "latest_export_zip_folder": latest_export_zip_folder,
        "latest_export_zip_reason": latest_export_zip_reason,
        "stale_export_artifact_detected": False,
        "export_artifact_status": "ready" if latest_export_zip_saved else "save_failed",
        "latest_export_status_path": str(latest_export_status.get("path") or ""),
        "chapters": [str(chapter.get("title") or "") for chapter in chapters[:5]],
        "chapter_stats_preview": chapter_stats[:5],
        "full_audit_can_ship": full_audit_can_ship,
        "full_audit_blocking_issue_count": full_audit_blocking_issue_count,
        "full_audit_report_path": str((REPO_ROOT / "output" / "fnm_book_audits" / f"{doc_slug}.json").resolve()) if str(doc_slug or "").strip() else "",
        "full_audit_summary": {
            "must_fix_before_next_book": list(full_audit_report.get("must_fix_before_next_book") or [])[:8],
            "recommended_followups": list(full_audit_report.get("recommended_followups") or [])[:8],
        },
    }


def verify_retry_summary(doc_id: str) -> dict[str, Any]:
    summary = build_fnm_retry_summary(doc_id)
    return {
        "execution_mode": summary.get("execution_mode"),
        "blocking_export": summary.get("blocking_export"),
        "blocking_reason": summary.get("blocking_reason"),
        "retry_progress": dict(summary.get("retry_progress") or {}),
    }


def test_document(
    doc_id: str,
    doc_name: str,
    *,
    example_folder: str = "",
    doc_slug: str = "",
) -> dict[str, Any]:
    print(f"\n{'=' * 72}")
    print(f"测试文档: {doc_name}")
    print(f"文档 ID: {doc_id}")
    print(f"{'=' * 72}")

    result: dict[str, Any] = {
        "doc_id": doc_id,
        "doc_name": doc_name,
        "slug": str(doc_slug or "").strip(),
        "example_folder": str(example_folder or "").strip(),
        "steps": {},
    }

    print("\n[1/5] 清理 FNM 数据...")
    clear_fnm_data(doc_id)
    result["steps"]["clear"] = {"ok": True}
    print("  ✓ 已清理")

    print("\n[2/5] 重跑 FNM pipeline...")
    pipeline_result = run_pipeline(doc_id)
    result["steps"]["pipeline"] = pipeline_result
    if pipeline_result.get("ok"):
        print(f"  ✓ Pipeline 完成: sections={pipeline_result.get('section_count', 0)}, notes={pipeline_result.get('note_count', 0)}, units={pipeline_result.get('unit_count', 0)}")
    else:
        print(f"  ✗ Pipeline 失败: {pipeline_result.get('error', 'unknown')}")
        result["all_ok"] = False
        return result

    phase6_snapshot = load_fnm_doc_structure(doc_id, slug=doc_id)

    print("\n[3/5] 检查 FNM 结构...")
    structure = verify_fnm_structure(doc_id, snapshot=phase6_snapshot)
    result["steps"]["structure"] = structure
    print(
        "  ✓ 结构已读取:"
        f" state={structure.get('structure_state', 'idle')},"
        f" pages={structure.get('page_count', 0)},"
        f" chapters={structure.get('chapter_count', 0)},"
        f" section_heads={structure.get('section_head_count', 0)},"
        f" suppressed={structure.get('suppressed_chapter_candidate_count', 0)},"
        f" note_items={structure.get('note_item_count', 0)},"
        f" anchors={structure.get('body_anchor_count', 0)}"
    )
    if structure.get("link_summary"):
        print(f"    - link_summary={json.dumps(structure['link_summary'], ensure_ascii=False)}")
    if structure.get("blocking_reasons"):
        print(f"    - blocking={json.dumps(structure['blocking_reasons'], ensure_ascii=False)}")
    if structure.get("validation_reason_counts"):
        print(f"    - validation={json.dumps(structure['validation_reason_counts'], ensure_ascii=False)}")
    if structure.get("toc_export_coverage_summary"):
        print(f"    - toc_coverage={json.dumps(structure['toc_export_coverage_summary'], ensure_ascii=False)}")
    if structure.get("toc_alignment_summary"):
        print(f"    - toc_alignment={json.dumps(structure['toc_alignment_summary'], ensure_ascii=False)}")
    if structure.get("toc_semantic_summary"):
        print(f"    - toc_semantic={json.dumps(structure['toc_semantic_summary'], ensure_ascii=False)}")
    print(
        "    - chapter_alignment:"
        f" title={bool(structure.get('chapter_title_alignment_ok', True))},"
        f" section={bool(structure.get('chapter_section_alignment_ok', True))}"
    )
    print(
        "    - chapter_endnote_boundary_ok:"
        f" {bool(structure.get('chapter_endnote_region_boundary_ok', True))}"
        f" (cross_next={int(structure.get('chapter_endnote_region_cross_next_chapter_count', 0) or 0)})"
    )
    print(
        "    - toc_semantic_contract_ok:"
        f" {bool(structure.get('toc_semantic_contract_ok', True))}"
    )

    print("\n[4/5] 写入 test 占位译文并重建页面...")
    placeholder_result = materialize_test_placeholders(doc_id)
    result["steps"]["placeholders"] = placeholder_result
    print(
        "  ✓ 占位已写入:"
        f" body_units={placeholder_result.get('body_unit_count', 0)},"
        f" note_units={placeholder_result.get('note_unit_count', 0)},"
        f" pages={placeholder_result.get('changed_page_count', 0)}"
    )

    print("\n[5/5] 校验 FNM 导出...")
    try:
        export_result = verify_export(
            doc_id,
            structure=structure,
            snapshot=phase6_snapshot,
            example_folder=example_folder,
            require_zip_persist=bool(str(example_folder or "").strip()),
            doc_slug=doc_slug,
            doc_name=doc_name,
        )
        result["steps"]["export"] = export_result
        if export_result.get("blocked"):
            print(
                "  ✗ 导出阻塞:"
                f" structure_state={export_result.get('structure_state', '')},"
                f" reason={export_result.get('reason', '')}"
            )
        else:
            print(
                "  "
                + ("✓" if export_result.get("ok") else "✗")
                + f" 导出检查: local_refs={export_result.get('unique_local_ref_count', 0)},"
                f" local_defs={export_result.get('unique_local_def_count', 0)},"
                f" orphan_defs={export_result.get('orphan_local_definition_count', 0)},"
                f" placeholders={export_result.get('pending_placeholder_count', 0)},"
                f" pseudo_heads={export_result.get('forbidden_section_heading_count', 0)}"
            )
            biopolitics_audit = dict(export_result.get("biopolitics_export_audit") or {})
            if biopolitics_audit.get("applicable"):
                print(
                    "    - biopolitics_audit:"
                    f" tri_alignment_ok={bool(biopolitics_audit.get('tri_alignment_ok', True))},"
                    f" boundary_ok={bool(biopolitics_audit.get('boundary_ok', True))},"
                    f" chapter_002_004_006_ok={bool(biopolitics_audit.get('chapter_contract_ok_002_004_006', True))},"
                    f" keyword_recovery_ok={bool(biopolitics_audit.get('keyword_recovery_ok', True))}"
                )
        if export_result.get("latest_export_zip_saved"):
            print(f"  ✓ 导出包落盘: {export_result.get('latest_export_zip_path', '')}")
        elif export_result.get("latest_export_zip_reason"):
            print(
                "  ✗ 导出包未落盘:"
                f" reason={export_result.get('latest_export_zip_reason', '')}"
            )
    except Exception as exc:
        result["steps"]["export"] = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        print(f"  ✗ 导出异常: {exc}")

    retry_summary = verify_retry_summary(doc_id)
    result["retry_summary"] = retry_summary
    print(
        "  重试摘要:"
        f" execution_mode={retry_summary.get('execution_mode')},"
        f" blocking_export={retry_summary.get('blocking_export')}"
    )

    result["all_ok"] = all(
        bool((step or {}).get("ok"))
        for step in result["steps"].values()
    )
    print("\n" + ("✅ 文档测试通过" if result["all_ok"] else "❌ 文档测试未通过"))
    return result


def build_markdown_report(results: list[dict[str, Any]]) -> str:
    lines = [
        "# FNM 样本批量测试报告",
        "",
    ]
    for item in results:
        lines.extend([
            f"## {item.get('doc_name', '')}",
            "",
            f"- 文档 ID：`{item.get('doc_id', '')}`",
            f"- 总结果：{'通过' if item.get('all_ok') else '未通过'}",
        ])
        structure = (item.get("steps") or {}).get("structure") or {}
        export = (item.get("steps") or {}).get("export") or {}
        retry_summary = item.get("retry_summary") or {}
        review_counts = _collect_module_reason_counts(
            review_counts=structure.get("review_counts"),
            blocking_reasons=list(structure.get("blocking_reasons") or []),
            manual_toc_required=bool(structure.get("manual_toc_required")),
        )
        lines.extend([
            f"- 结构状态：{structure.get('structure_state', 'idle')}",
            f"- matched / review_reason_counts：{(structure.get('link_summary') or {}).get('matched', 0)} / {_format_reason_counts(review_counts)}",
            f"- page / chapter / section_head / region / note_item / anchor / link：{structure.get('page_count', 0)} / {structure.get('chapter_count', 0)} / {structure.get('section_head_count', 0)} / {structure.get('note_region_count', 0)} / {structure.get('note_item_count', 0)} / {structure.get('body_anchor_count', 0)} / {structure.get('note_link_count', 0)}",
            f"- 伪章节压制 / 分区冲突：{structure.get('suppressed_chapter_candidate_count', 0)} / {structure.get('partition_heading_conflict_count', 0)}",
            f"- 页面分区：noise={(structure.get('page_partition_summary') or {}).get('noise', 0)}, front_matter={(structure.get('page_partition_summary') or {}).get('front_matter', 0)}, body={(structure.get('page_partition_summary') or {}).get('body', 0)}, note={(structure.get('page_partition_summary') or {}).get('note', 0)}, other={(structure.get('page_partition_summary') or {}).get('other', 0)}",
            f"- 章节模式：footnote_primary={(structure.get('chapter_mode_summary') or {}).get('footnote_primary', 0)}, chapter_endnotes={(structure.get('chapter_mode_summary') or {}).get('chapter_endnotes', 0)}, book_endnotes={(structure.get('chapter_mode_summary') or {}).get('book_endnotes', 0)}, body_only={(structure.get('chapter_mode_summary') or {}).get('body_only', 0)}, mixed_or_unclear={(structure.get('chapter_mode_summary') or {}).get('mixed_or_unclear', 0)}",
            f"- 章节来源：`{json.dumps(structure.get('chapter_source_summary') or {}, ensure_ascii=False)}`",
            f"- visual_toc_conflict_count：{structure.get('visual_toc_conflict_count', 0)}",
            f"- toc_export_coverage_summary：`{json.dumps(structure.get('toc_export_coverage_summary') or {}, ensure_ascii=False)}`",
            f"- toc_alignment_summary：`{json.dumps(structure.get('toc_alignment_summary') or {}, ensure_ascii=False)}`",
            f"- heading_graph_summary：`{json.dumps(structure.get('heading_graph_summary') or {}, ensure_ascii=False)}`",
            f"- toc_semantic_summary：`{json.dumps(structure.get('toc_semantic_summary') or {}, ensure_ascii=False)}`",
            f"- toc_role_summary：`{json.dumps(structure.get('toc_role_summary') or {}, ensure_ascii=False)}`",
            f"- container/post_body/back_matter titles：`{(structure.get('container_titles') or [])}` / `{(structure.get('post_body_titles') or [])}` / `{(structure.get('back_matter_titles') or [])}`",
            f"- toc_semantic_contract_ok：{bool(structure.get('toc_semantic_contract_ok', True))}",
            f"- toc_semantic_blocking_reasons：`{structure.get('toc_semantic_blocking_reasons', [])}`",
            f"- chapter_title_alignment_ok / chapter_section_alignment_ok：{bool(structure.get('chapter_title_alignment_ok', True))} / {bool(structure.get('chapter_section_alignment_ok', True))}",
            f"- chapter_endnote_region_alignment_ok：{bool(structure.get('chapter_endnote_region_alignment_ok', True))}",
            f"- chapter_endnote_region_alignment_summary：`{json.dumps(structure.get('chapter_endnote_region_alignment_summary') or {}, ensure_ascii=False)}`",
            f"- chapter_endnote_region_boundary_ok / cross_next_count：{bool(structure.get('chapter_endnote_region_boundary_ok', True))} / {int(structure.get('chapter_endnote_region_cross_next_chapter_count', 0) or 0)}",
            f"- manual_toc_required / manual_toc_ready：{bool(structure.get('manual_toc_required', False))} / {bool(structure.get('manual_toc_ready', False))}",
            f"- manual_toc_summary：`{json.dumps(structure.get('manual_toc_summary') or {}, ensure_ascii=False)}`",
            f"- 脚注数 / 尾注数：{structure.get('footnote_count', 0)} / {structure.get('endnote_count', 0)}",
            f"- 阻塞原因：`{structure.get('blocking_reasons', [])}`",
            f"- export_ready_test / real：{structure.get('export_ready_test', False)} / {structure.get('export_ready_real', False)}",
            f"- retry summary：mode={retry_summary.get('execution_mode')}, blocking={retry_summary.get('blocking_export')}",
        ])
        if export.get("blocked"):
            lines.append(f"- 导出状态：blocked ({export.get('reason', '')})")
            zip_path = str(export.get("latest_export_zip_path") or "").strip()
            zip_reason = str(export.get("latest_export_zip_reason") or "").strip()
            if zip_path:
                lines.append(f"- 最新导出包：`{zip_path}`")
            elif zip_reason:
                lines.append(f"- 最新导出包：未落盘（{zip_reason}）")
        else:
            lines.extend([
                f"- 导出章节本地引用 / 定义：{export.get('unique_local_ref_count', 0)} / {export.get('unique_local_def_count', 0)}",
                f"- 孤立本地定义 / 引用：{export.get('orphan_local_definition_count', 0)} / {export.get('orphan_local_ref_count', 0)}",
                f"- 导出占位残留：{export.get('pending_placeholder_count', 0)}",
                f"- 原始 NOTES 泄漏：{export.get('raw_note_heading_leak_count', 0)}",
                f"- 旧口径泄漏 FN / [^en-*] / [EN-*] / NOTE_TOKEN：{export.get('legacy_footnote_ref_count', 0)} / {export.get('legacy_endnote_ref_count', 0)} / {export.get('legacy_en_bracket_ref_count', 0)} / {export.get('legacy_note_token_count', 0)}",
                f"- 禁用伪标题数：{export.get('forbidden_section_heading_count', 0)}",
                f"- chapter_local_endnote_contract_ok：{export.get('chapter_local_endnote_contract_ok', False)}",
                f"- export_semantic_contract_ok：{export.get('export_semantic_contract_ok', True)}",
                f"- front_matter_leak / toc_residue / mid_paragraph_heading / duplicate_paragraph：{export.get('front_matter_leak_detected', False)} / {export.get('toc_residue_detected', False)} / {export.get('mid_paragraph_heading_detected', False)} / {export.get('duplicate_paragraph_detected', False)}",
                f"- full_audit_can_ship / blocking_count：{export.get('full_audit_can_ship', True)} / {int(export.get('full_audit_blocking_issue_count', 0) or 0)}",
            ])
            biopolitics_audit = dict(export.get("biopolitics_export_audit") or {})
            if biopolitics_audit.get("applicable"):
                lines.extend([
                    f"- biopolitics_export_contract_ok：{bool(export.get('biopolitics_export_contract_ok', True))}",
                    f"- biopolitics_audit_summary：`{json.dumps({'tri_alignment_ok': bool(biopolitics_audit.get('tri_alignment_ok', True)), 'boundary_ok': bool(biopolitics_audit.get('boundary_ok', True)), 'chapter_002_004_006_ok': bool(biopolitics_audit.get('chapter_contract_ok_002_004_006', True)), 'keyword_recovery_ok': bool(biopolitics_audit.get('keyword_recovery_ok', True)), 'tri_total': int(biopolitics_audit.get('tri_alignment_total', 0) or 0), 'tri_misaligned': int(biopolitics_audit.get('tri_alignment_misaligned_count', 0) or 0), 'tri_missing': int(biopolitics_audit.get('tri_alignment_missing_marker_count', 0) or 0)}, ensure_ascii=False)}`",
                ])
            zip_path = str(export.get("latest_export_zip_path") or "").strip()
            zip_reason = str(export.get("latest_export_zip_reason") or "").strip()
            if zip_path:
                lines.append(f"- 最新导出包：`{zip_path}`")
            elif zip_reason:
                lines.append(f"- 最新导出包：未落盘（{zip_reason}）")
        validation_counts = structure.get("validation_reason_counts") or {}
        if validation_counts:
            lines.append(f"- validation：`{json.dumps(validation_counts, ensure_ascii=False)}`")
        preview_defs = export.get("orphan_local_definitions_preview") or []
        if preview_defs:
            lines.append(f"- 孤立本地定义示例：`{preview_defs}`")
        preview_refs = export.get("orphan_local_refs_preview") or []
        if preview_refs:
            lines.append(f"- 孤立本地引用示例：`{preview_refs}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_missing_document_result(doc: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(doc.get("id") or "").strip()
    doc_name = str(doc.get("name") or doc.get("manifest_doc_name") or "").strip()
    expected_pages = int(doc.get("expected_page_count") or doc.get("page_count") or 0)
    example_folder = str(doc.get("folder") or "").strip()
    return {
        "doc_id": doc_id,
        "doc_name": doc_name,
        "example_folder": example_folder,
        "slug": str(doc.get("slug") or "").strip(),
        "group": str(doc.get("group") or "").strip(),
        "all_ok": False,
        "steps": {
            "pipeline": {
                "ok": False,
                "error": "doc_missing",
                "message": "数据库中未找到该样本文档，请先运行 onboarding 脚本。",
            }
        },
        "expected_page_count": expected_pages,
        "retry_summary": {},
    }


def main() -> int:
    args = parse_args()
    if args.all_docs:
        docs = select_documents(all_docs=True, limit=max(0, int(args.limit or 0)))
    else:
        docs = select_documents_from_manifest(
            group=args.group or "",
            slug=args.slug or "",
            limit=max(0, int(args.limit or 0)),
        )
    if not docs:
        print("⚠ 没找到可测试文档。")
        return 1

    print("=" * 72)
    print("FNM 模式批量测试")
    print("=" * 72)
    print(f"本次共测试 {len(docs)} 本文档：")
    for doc in docs:
        extra = []
        if doc.get("slug"):
            extra.append(f"slug={doc['slug']}")
        if doc.get("group"):
            extra.append(f"group={doc['group']}")
        extra_text = f", {', '.join(extra)}" if extra else ""
        print(f"  - {doc['name']} (id={doc['id']}, pages={doc['page_count']}{extra_text})")

    results: list[dict[str, Any]] = []
    existing_doc_ids = {item["id"] for item in list_documents()}
    for doc in docs:
        if doc["id"] not in existing_doc_ids and not args.all_docs:
            results.append(build_missing_document_result(doc))
            continue
        results.append(
            test_document(
                doc["id"],
                doc["name"],
                example_folder=str(doc.get("folder") or "").strip(),
                doc_slug=str(doc.get("slug") or "").strip(),
            )
        )

    passed = sum(1 for item in results if item.get("all_ok"))
    failed = len(results) - passed
    print("\n" + "=" * 72)
    print("测试汇总")
    print("=" * 72)
    for item in results:
        status = "✅" if item.get("all_ok") else "❌"
        print(f"  {status} {item.get('doc_name', '')}")
    print(f"\n总计: {passed} 通过, {failed} 未通过")

    output_path = Path(str(args.output)).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = output_path.with_suffix(".md")
    report_path.write_text(build_markdown_report(results), encoding="utf-8")

    print(f"\nJSON 结果已保存到: {output_path}")
    print(f"Markdown 报告已保存到: {report_path}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

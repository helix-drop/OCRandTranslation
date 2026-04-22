#!/usr/bin/env python3
"""为五本基准书生成自动视觉目录快照（JSON + Markdown）。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import get_doc_meta
from example_manifest import select_example_books
from persistence.storage_toc import load_auto_visual_toc_bundle_from_disk, load_auto_visual_toc_from_disk
from pipeline.document_tasks import run_auto_visual_toc_for_doc


TEST_EXAMPLE_ROOT = REPO_ROOT / "test_example"
DOCS_ROOT = REPO_ROOT / "local_data" / "user_data" / "data" / "documents"
GENERATOR_NAME = "scripts/generate_visual_toc_snapshots.py"


@dataclass(frozen=True)
class SnapshotTarget:
    doc_id: str
    folder: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成自动视觉目录快照（默认五本基准书）。")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--doc-id", help="只处理指定文档 ID。")
    group.add_argument("--folder", help="只处理指定 test_example 子目录。")
    group.add_argument("--slug", help="只处理指定 manifest slug。")
    parser.add_argument(
        "--group",
        choices=("baseline", "extension", "all"),
        default="all",
        help="按 manifest 分组过滤；默认 all。",
    )
    return parser.parse_args()


def resolve_targets(*, doc_id: str = "", folder: str = "", slug: str = "", group: str = "all") -> list[SnapshotTarget]:
    books = select_example_books(
        include_all=True,
        doc_id=doc_id,
        folder=folder,
        slug=slug,
        group=group,
    )
    if not books:
        qualifier = doc_id or folder or slug or group or "all"
        raise ValueError(f"未在样本清单中找到目标：{qualifier}")
    return [SnapshotTarget(doc_id=book.doc_id, folder=book.folder) for book in books]


def _find_pdf_in_folder(folder_dir: Path) -> Path | None:
    pdf_paths = sorted(
        path
        for path in folder_dir.glob("*.pdf")
        if path.is_file() and path.name not in {"目录.pdf", "toc_visual_source.pdf"}
    )
    if not pdf_paths:
        return None
    return pdf_paths[0]


def resolve_book_paths(
    target: SnapshotTarget,
    *,
    test_example_root: Path = TEST_EXAMPLE_ROOT,
    docs_root: Path = DOCS_ROOT,
) -> tuple[Path, Path]:
    folder_dir = test_example_root / target.folder
    if not folder_dir.exists():
        raise FileNotFoundError(f"未找到目录：{folder_dir}")
    if not folder_dir.is_dir():
        raise NotADirectoryError(f"不是目录：{folder_dir}")

    example_pdf = _find_pdf_in_folder(folder_dir)
    if example_pdf is not None:
        return folder_dir, example_pdf

    fallback_pdf = docs_root / target.doc_id / "source.pdf"
    if fallback_pdf.is_file():
        return folder_dir, fallback_pdf

    raise FileNotFoundError(
        f"未找到源 PDF（folder={target.folder}, doc_id={target.doc_id}）。"
    )


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _coerce_nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _resolve_level(item: dict[str, Any]) -> int:
    level = _coerce_positive_int(item.get("level"))
    if level is not None:
        return level
    role_hint = str(item.get("role_hint") or "").strip().lower()
    depth = _coerce_nonnegative_int(item.get("depth"))
    if role_hint in {"container", "endnotes"}:
        return 1
    if role_hint == "chapter":
        return 2
    if role_hint == "section":
        return max(3, int(depth or 2) + 1)
    if role_hint in {"front_matter", "back_matter", "post_body"}:
        return 0
    if depth is not None:
        return depth + 1
    return 1


def normalize_toc_items(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items or [], start=1):
        if not isinstance(item, dict):
            continue
        clone: dict[str, Any] = dict(item)

        default_item_id = f"visual-item-{index}"
        clone["item_id"] = str(clone.get("item_id", default_item_id) or default_item_id)
        clone["title"] = str(clone.get("title", "") or "")
        clone["level"] = _resolve_level(clone)

        file_idx = _coerce_nonnegative_int(clone.get("file_idx"))
        clone["file_idx"] = file_idx

        target_pdf_page = _coerce_positive_int(clone.get("target_pdf_page"))
        if target_pdf_page is None and file_idx is not None:
            target_pdf_page = file_idx + 1
        clone["target_pdf_page"] = target_pdf_page

        book_page = _coerce_positive_int(clone.get("book_page"))
        clone["book_page"] = book_page

        print_page_label = str(clone.get("print_page_label", "") or "").strip()
        if not print_page_label and book_page is not None:
            print_page_label = str(book_page)
        clone["print_page_label"] = print_page_label

        if not str(clone.get("source", "") or "").strip():
            clone["source"] = "auto_visual"

        if "resolved" in clone:
            clone["resolved"] = bool(clone.get("resolved"))
        else:
            clone["resolved"] = target_pdf_page is not None

        normalized.append(clone)
    return normalized


def _normalize_index_list(values: Any, *, one_based: bool = False) -> list[int]:
    if not isinstance(values, list):
        return []
    normalized: list[int] = []
    seen: set[int] = set()
    for value in values:
        parsed = _coerce_nonnegative_int(value)
        if parsed is None:
            continue
        page_value = parsed + 1 if one_based else parsed
        if page_value in seen:
            continue
        seen.add(page_value)
        normalized.append(page_value)
    return normalized


def _normalize_run_summaries(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in values:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "start_file_idx": _coerce_nonnegative_int(row.get("start_file_idx")) or 0,
                "end_file_idx": _coerce_nonnegative_int(row.get("end_file_idx")) or 0,
                "page_count": _coerce_nonnegative_int(row.get("page_count")) or 0,
                "score": float(row.get("score", 0.0) or 0.0),
                "selected_as": str(row.get("selected_as", "") or ""),
            }
        )
    return rows


def build_snapshot_payload(
    *,
    target: SnapshotTarget,
    doc_name: str,
    source_pdf: Path,
    generated_at: str,
    meta: dict[str, Any],
    run_result: dict[str, Any],
    runtime_bundle: dict[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    status = str(meta.get("toc_visual_status", "idle") or "idle").strip() or "idle"
    message = str(meta.get("toc_visual_message", "") or "")
    phase = str(meta.get("toc_visual_phase", "") or "")
    endnotes_summary = dict((runtime_bundle or {}).get("endnotes_summary") or run_result.get("endnotes_summary") or {})
    payload: dict[str, Any] = {
        "doc_id": target.doc_id,
        "doc_name": doc_name,
        "source_pdf": str(source_pdf),
        "generated_at": generated_at,
        "generator": GENERATOR_NAME,
        "toc_visual_status": status,
        "toc_visual_message": message,
        "item_count": len(items),
        "scan_mode": str(run_result.get("scan_mode", "") or ""),
        "candidate_source": str(run_result.get("candidate_source", "") or ""),
        "candidate_indices": _normalize_index_list(run_result.get("candidate_indices"), one_based=False),
        "candidate_pdf_pages": _normalize_index_list(run_result.get("candidate_pdf_pages"), one_based=False),
        "retry_indices": _normalize_index_list(run_result.get("retry_indices"), one_based=False),
        "retry_pdf_pages": _normalize_index_list(run_result.get("retry_pdf_pages"), one_based=False),
        "primary_run_pages": _normalize_index_list(run_result.get("primary_run_pages"), one_based=False),
        "context_pages": _normalize_index_list(run_result.get("context_pages"), one_based=False),
        "run_summaries": _normalize_run_summaries(run_result.get("run_summaries")),
        "resolved_item_count": _coerce_nonnegative_int(run_result.get("resolved_item_count")) or 0,
        "unresolved_item_count": _coerce_nonnegative_int(run_result.get("unresolved_item_count")) or 0,
        "selected_page_count": _coerce_nonnegative_int(run_result.get("selected_page_count")) or 0,
        "selected_run_count": _coerce_nonnegative_int(run_result.get("selected_run_count")) or 0,
        "suspected_partial_capture": bool(run_result.get("suspected_partial_capture", False)),
        "coverage_quality": str(run_result.get("coverage_quality", "") or ""),
        "organization_summary": dict(run_result.get("organization_summary") or {}),
        "organization_nodes": list(run_result.get("organization_nodes") or items),
        "endnotes_summary": endnotes_summary,
        "manual_input_mode": str(run_result.get("manual_input_mode", "") or ""),
        "manual_input_page_count": _coerce_nonnegative_int(run_result.get("manual_input_page_count")) or 0,
        "manual_input_source_name": str(run_result.get("manual_input_source_name", "") or ""),
        "manual_page_items_debug": list(run_result.get("manual_page_items_debug") or []),
        "organization_bundle_debug": dict(run_result.get("organization_bundle_debug") or {}),
        "items": items,
    }
    if payload["resolved_item_count"] == 0 and items:
        payload["resolved_item_count"] = sum(1 for item in items if bool((item or {}).get("resolved")))
    if payload["unresolved_item_count"] == 0 and items:
        payload["unresolved_item_count"] = sum(1 for item in items if not bool((item or {}).get("resolved")))
    if payload["selected_page_count"] == 0:
        payload["selected_page_count"] = len(payload["candidate_indices"])
    if payload["selected_run_count"] == 0:
        payload["selected_run_count"] = sum(
            1
            for row in payload["run_summaries"]
            if str((row or {}).get("selected_as") or "") in {"primary_run", "secondary_run"}
        )
    if phase:
        payload["toc_visual_phase"] = phase
    return payload


def _safe_cell_text(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("|", r"\|")
    return text.replace("\n", " ")


def _item_pdf_page(item: dict[str, Any]) -> int | None:
    page = _coerce_positive_int(item.get("target_pdf_page"))
    if page is not None:
        return page
    file_idx = _coerce_nonnegative_int(item.get("file_idx"))
    if file_idx is None:
        return None
    return file_idx + 1


def build_markdown(payload: dict[str, Any]) -> str:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    resolved_count = sum(1 for item in items if bool((item or {}).get("resolved")))
    unresolved_items = [item for item in items if not bool((item or {}).get("resolved"))]
    max_level = max((_coerce_positive_int((item or {}).get("level")) or 1 for item in items), default=0)
    candidate_pdf_pages = payload.get("candidate_pdf_pages") if isinstance(payload.get("candidate_pdf_pages"), list) else []
    retry_pdf_pages = payload.get("retry_pdf_pages") if isinstance(payload.get("retry_pdf_pages"), list) else []
    run_summaries = payload.get("run_summaries") if isinstance(payload.get("run_summaries"), list) else []
    manual_input_mode = str(payload.get("manual_input_mode", "") or "").strip()
    manual_input_page_count = _coerce_nonnegative_int(payload.get("manual_input_page_count")) or 0
    manual_input_source_name = str(payload.get("manual_input_source_name", "") or "").strip()
    organization_summary = dict(payload.get("organization_summary") or {})
    endnotes_summary = dict(payload.get("endnotes_summary") or {})

    def _fmt_pages(values: list[Any]) -> str:
        if not values:
            return "-"
        pages = [str(value) for value in values if _coerce_positive_int(value) is not None]
        return ", ".join(pages) if pages else "-"

    lines: list[str] = [
        "# Auto Visual TOC",
        "",
        "## 基本信息",
        f"- Doc Name: {payload.get('doc_name', '')}",
        f"- Doc ID: {payload.get('doc_id', '')}",
        f"- PDF: {payload.get('source_pdf', '')}",
        f"- Generated At: {payload.get('generated_at', '')}",
        f"- Status: {payload.get('toc_visual_status', '')}",
        f"- Message: {payload.get('toc_visual_message', '')}",
        f"- Item Count: {payload.get('item_count', 0)}",
        "",
        "## 扫描诊断",
        f"- Scan Mode: {payload.get('scan_mode', '')}",
        f"- Candidate Source: {payload.get('candidate_source', '')}",
        f"- Candidate PDF Pages: {_fmt_pages(candidate_pdf_pages)}",
        f"- Retry PDF Pages: {_fmt_pages(retry_pdf_pages)}",
        f"- Selected Page Count: {payload.get('selected_page_count', 0)}",
        f"- Selected Run Count: {payload.get('selected_run_count', 0)}",
        f"- Coverage Quality: {payload.get('coverage_quality', '')}",
        f"- Suspected Partial Capture: {'Yes' if bool(payload.get('suspected_partial_capture')) else 'No'}",
    ]
    if manual_input_mode:
        lines.extend(
            [
            f"- Manual Input Mode: {manual_input_mode}",
            f"- Manual Input Page Count: {manual_input_page_count}",
            f"- Manual Input Source Name: {manual_input_source_name or '-'}",
            ]
        )
    lines.extend(
        [
            "",
            "## Run 摘要",
            "",
        ]
    )

    if run_summaries:
        lines.extend(
            [
                "| # | File Idx Range | Page Count | Selected As | Score |",
                "|---|---|---|---|---|",
            ]
        )
        for index, raw_row in enumerate(run_summaries, start=1):
            row = raw_row if isinstance(raw_row, dict) else {}
            start_idx = _coerce_nonnegative_int(row.get("start_file_idx"))
            end_idx = _coerce_nonnegative_int(row.get("end_file_idx"))
            page_count = _coerce_nonnegative_int(row.get("page_count")) or 0
            selected_as = _safe_cell_text(row.get("selected_as", ""))
            score = float(row.get("score", 0.0) or 0.0)
            range_text = "-" if start_idx is None or end_idx is None else f"{start_idx}-{end_idx}"
            lines.append(f"| {index} | {range_text} | {page_count} | {selected_as} | {score:.2f} |")
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## 组织方式",
            f"- Max Body Depth: {organization_summary.get('max_body_depth', 0)}",
            f"- Has Containers: {'Yes' if bool(organization_summary.get('has_containers')) else 'No'}",
            f"- Has Post Body: {'Yes' if bool(organization_summary.get('has_post_body')) else 'No'}",
            f"- Has Back Matter: {'Yes' if bool(organization_summary.get('has_back_matter')) else 'No'}",
            f"- Body Root Titles: {_fmt_pages([]) if not organization_summary.get('body_root_titles') else ', '.join(str(v) for v in organization_summary.get('body_root_titles') or [])}",
            f"- Container Titles: {_fmt_pages([]) if not organization_summary.get('container_titles') else ', '.join(str(v) for v in organization_summary.get('container_titles') or [])}",
            f"- Post Body Titles: {_fmt_pages([]) if not organization_summary.get('post_body_titles') else ', '.join(str(v) for v in organization_summary.get('post_body_titles') or [])}",
            f"- Back Matter Titles: {_fmt_pages([]) if not organization_summary.get('back_matter_titles') else ', '.join(str(v) for v in organization_summary.get('back_matter_titles') or [])}",
        ]
    )
    lines.extend(
        [
            "",
            "## 尾注容器",
            f"- Present: {'Yes' if bool(endnotes_summary.get('present')) else 'No'}",
            f"- Container Title: {endnotes_summary.get('container_title') or '-'}",
            f"- Container Printed Page: {endnotes_summary.get('container_printed_page') or '-'}",
            f"- Container Visual Order: {endnotes_summary.get('container_visual_order') or '-'}",
            f"- Has Chapter Keyed Subentries: {'Yes' if bool(endnotes_summary.get('has_chapter_keyed_subentries_in_toc')) else 'No'}",
            f"- Subentry Pattern: {endnotes_summary.get('subentry_pattern') or '-'}",
        ]
    )

    lines.extend(
        [
            "",
        "## 汇总",
        f"- 已定位条目数: {resolved_count}",
        f"- 未定位条目数: {len(unresolved_items)}",
        f"- 结果层已定位条目数: {payload.get('resolved_item_count', 0)}",
        f"- 结果层未定位条目数: {payload.get('unresolved_item_count', 0)}",
        f"- 最高 level: {max_level}",
        "",
        "## 目录表",
        "",
        "| # | Level | Title | Book Page | PDF Page | Resolved |",
        "|---|---|---|---|---|---|",
        ]
    )

    for index, raw_item in enumerate(items, start=1):
        item = raw_item if isinstance(raw_item, dict) else {}
        level = _coerce_positive_int(item.get("level")) or 1
        title = _safe_cell_text(item.get("title", ""))
        title_display = f"{'  ' * max(0, level - 1)}L{level} {title}".strip()
        book_page = _coerce_positive_int(item.get("book_page"))
        pdf_page = _item_pdf_page(item)
        resolved = "Yes" if bool(item.get("resolved")) else "No"
        lines.append(
            f"| {index} | L{level} | {title_display} | {book_page or ''} | {pdf_page or ''} | {resolved} |"
        )

    lines.extend(["", "## 未定位条目", ""])
    if unresolved_items:
        for raw_item in unresolved_items:
            item = raw_item if isinstance(raw_item, dict) else {}
            title = _safe_cell_text(item.get("title", "")) or "(Untitled)"
            level = _coerce_positive_int(item.get("level")) or 1
            book_page = _coerce_positive_int(item.get("book_page"))
            lines.append(f"- L{level} {title}（Book Page: {book_page or ''}）")
    else:
        lines.append("- 无")

    return "\n".join(lines) + "\n"


def write_snapshot_files(
    *,
    folder_dir: Path,
    payload: dict[str, Any],
) -> tuple[Path, Path]:
    folder_dir.mkdir(parents=True, exist_ok=True)
    json_path = folder_dir / "auto_visual_toc.json"
    md_path = folder_dir / "auto_visual_toc.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(build_markdown(payload), encoding="utf-8")
    return json_path, md_path


def process_target(
    target: SnapshotTarget,
    *,
    test_example_root: Path = TEST_EXAMPLE_ROOT,
    docs_root: Path = DOCS_ROOT,
    run_auto: Callable[..., dict[str, Any]] = run_auto_visual_toc_for_doc,
    load_toc: Callable[[str], list[dict[str, Any]]] = load_auto_visual_toc_from_disk,
    load_bundle: Callable[[str], dict[str, Any]] = load_auto_visual_toc_bundle_from_disk,
    read_meta: Callable[[str], dict[str, Any]] = get_doc_meta,
    generated_at: str | None = None,
) -> dict[str, Any]:
    folder_dir, source_pdf = resolve_book_paths(
        target,
        test_example_root=test_example_root,
        docs_root=docs_root,
    )

    run_result = run_auto(target.doc_id, str(source_pdf), model_spec=None) or {}
    meta = read_meta(target.doc_id) or {}
    raw_items = load_toc(target.doc_id) or []
    runtime_bundle = load_bundle(target.doc_id) or {}
    items = normalize_toc_items(raw_items)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    doc_name = str(meta.get("name", "") or source_pdf.name)
    payload = build_snapshot_payload(
        target=target,
        doc_name=doc_name,
        source_pdf=source_pdf,
        generated_at=timestamp,
        meta=meta,
        run_result=run_result,
        runtime_bundle=runtime_bundle,
        items=items,
    )
    json_path, md_path = write_snapshot_files(folder_dir=folder_dir, payload=payload)

    return {
        "doc_id": target.doc_id,
        "folder": target.folder,
        "run_status": str(run_result.get("status", "") or ""),
        "toc_visual_status": payload.get("toc_visual_status", ""),
        "item_count": payload.get("item_count", 0),
        "coverage_quality": payload.get("coverage_quality", ""),
        "selected_page_count": payload.get("selected_page_count", 0),
        "selected_run_count": payload.get("selected_run_count", 0),
        "json_path": str(json_path),
        "md_path": str(md_path),
    }


def main() -> int:
    args = parse_args()
    targets = resolve_targets(
        doc_id=args.doc_id or "",
        folder=args.folder or "",
        slug=args.slug or "",
        group=args.group or "all",
    )

    results: list[dict[str, Any]] = []
    has_error = False
    for target in targets:
        try:
            result = process_target(target)
            results.append(result)
        except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
            has_error = True
            results.append(
                {
                    "doc_id": target.doc_id,
                    "folder": target.folder,
                    "error": str(exc),
                }
            )

    print(
        json.dumps(
            {
                "generator": GENERATOR_NAME,
                "processed": len(targets),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())

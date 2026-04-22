#!/usr/bin/env python3
"""重建文档衍生物：FNM 分类与分段审计。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import get_doc_meta, set_current_doc
from FNM_RE import run_doc_pipeline as run_fnm_pipeline
from FNM_RE.page_translate import rebuild_fnm_diagnostic_page_entries
from persistence.storage import load_pages_from_disk
from persistence.storage_toc import load_effective_toc
from document.text_processing import (
    _looks_like_allcaps_title,
    _looks_like_colon_section_title,
    _parse_single_page_md,
    parse_page_markdown,
)
from document.text_utils import has_explicit_sentence_end, is_mid_sentence_continuation


def _toc_titles_by_page(doc_id: str) -> dict[int, list[str]]:
    _source, offset, items = load_effective_toc(doc_id)
    mapped: dict[int, list[str]] = {}
    for item in items or []:
        title = str(item.get("title", "") or "").strip()
        if not title:
            continue
        effective_bp = None
        if item.get("book_page") is not None:
            effective_bp = int(item.get("book_page") or 0) + int(offset or 0)
        elif item.get("file_idx") is not None:
            effective_bp = int(item.get("file_idx") or 0) + 1 + int(offset or 0)
        if effective_bp is None or effective_bp <= 0:
            continue
        mapped.setdefault(effective_bp, []).append(title)
    return mapped


def _is_audit_joinable_para(para: dict | None) -> bool:
    if not para:
        return False
    if int(para.get("heading_level", 0) or 0) > 0:
        return False
    text = str(para.get("text", "") or "").strip()
    if not text:
        return False
    if _looks_like_allcaps_title(text) > 0:
        return False
    if _looks_like_colon_section_title(text):
        return False
    return True


def find_uppercase_continuation_candidates(pages: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    ordered = sorted(
        (page for page in (pages or []) if page.get("bookPage") is not None),
        key=lambda page: int(page.get("bookPage") or 0),
    )
    by_bp = {int(page["bookPage"]): page for page in ordered}
    for page in ordered:
        bp = int(page.get("bookPage") or 0)
        next_page = by_bp.get(bp + 1)
        if not next_page:
            continue
        current_paras = _parse_single_page_md(page, str(page.get("markdown", "") or ""))
        next_paras = _parse_single_page_md(next_page, str(next_page.get("markdown", "") or ""))
        if not current_paras or not next_paras:
            continue
        last_para = current_paras[-1]
        first_para = next_paras[0]
        if not _is_audit_joinable_para(last_para) or not _is_audit_joinable_para(first_para):
            continue
        next_text = str(first_para.get("text", "") or "").strip()
        if not next_text or not next_text[0].isupper():
            continue
        if has_explicit_sentence_end(str(last_para.get("text", "") or "")):
            continue
        if not is_mid_sentence_continuation(
            str(last_para.get("text", "") or ""),
            next_text,
            allow_uppercase=True,
        ):
            continue
        candidates.append(
            {
                "book_page": bp,
                "next_book_page": int(next_page.get("bookPage") or 0),
                "tail_preview": str(last_para.get("text", "") or "")[-160:],
                "head_preview": next_text[:200],
                "next_starts_upper": True,
            }
        )
    return candidates


def audit_segmentation(doc_id: str) -> dict:
    set_current_doc(doc_id)
    pages, _ = load_pages_from_disk(doc_id)
    toc_by_page = _toc_titles_by_page(doc_id)
    uppercase_candidates = find_uppercase_continuation_candidates(pages)
    findings: list[dict] = []
    for page in pages:
        bp = int(page.get("bookPage") or 0)
        if bp <= 0:
            continue
        paragraphs = parse_page_markdown(pages, bp)
        headings = [
            {
                "text": str(para.get("text", "") or ""),
                "heading_level": int(para.get("heading_level", 0) or 0),
            }
            for para in paragraphs
            if int(para.get("heading_level", 0) or 0) > 0
        ]
        consumed = [
            str(para.get("text", "") or "")
            for para in paragraphs
            if para.get("consumed_by_prev")
        ]
        note_scan = page.get("_note_scan") if isinstance(page.get("_note_scan"), dict) else {}
        page_kind = str(note_scan.get("page_kind", "") or "").strip()
        if not headings and not consumed and not toc_by_page.get(bp) and not page_kind:
            continue
        findings.append(
            {
                "book_page": bp,
                "toc_titles": toc_by_page.get(bp) or [],
                "headings": headings,
                "consumed_by_prev": consumed,
                "page_kind": page_kind,
                "section_hints": list(note_scan.get("section_hints") or []),
            }
        )
    return {
        "doc_id": doc_id,
        "doc_name": str((get_doc_meta(doc_id) or {}).get("name", "") or ""),
        "pages": findings,
        "uppercase_continuation_candidates": uppercase_candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="重建文档的 FNM 衍生物或输出分段审计。")
    parser.add_argument("--doc-id", required=True, help="目标文档 ID")
    parser.add_argument("--rebuild-fnm", action="store_true", help="重跑 FNM 分类并更新 fnm_* 表")
    parser.add_argument("--audit-segmentation", action="store_true", help="输出当前解析规则下的分段审计 JSON")
    args = parser.parse_args()

    if not args.rebuild_fnm and not args.audit_segmentation:
        parser.error("至少选择 --rebuild-fnm 或 --audit-segmentation 之一")

    payload: dict = {"doc_id": args.doc_id}
    if args.rebuild_fnm:
        rebuild_result = run_fnm_pipeline(args.doc_id)
        pages, _ = load_pages_from_disk(args.doc_id)
        rebuilt_pages = rebuild_fnm_diagnostic_page_entries(args.doc_id, pages=pages)
        rebuild_result["rebuilt_page_entries"] = len(rebuilt_pages)
        rebuild_result["rebuilt_page_entry_pages"] = rebuilt_pages
        payload["fnm_rebuild"] = rebuild_result
    if args.audit_segmentation:
        payload["segmentation_audit"] = audit_segmentation(args.doc_id)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""test_example 样本清单加载与筛选。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = REPO_ROOT / "test_example" / "example_manifest.json"


@dataclass(frozen=True)
class ExampleBook:
    slug: str
    folder: str
    group: str
    doc_name: str
    source_pdf_path: str
    doc_id: str
    include_in_default_batch: bool
    expected_page_count: int


def load_example_manifest(path: Path | None = None) -> list[ExampleBook]:
    manifest_path = Path(path or MANIFEST_PATH)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    books = payload.get("books") if isinstance(payload, dict) else None
    normalized: list[ExampleBook] = []
    for raw in books or []:
        if not isinstance(raw, dict):
            continue
        normalized.append(
            ExampleBook(
                slug=str(raw.get("slug") or "").strip(),
                folder=str(raw.get("folder") or "").strip(),
                group=str(raw.get("group") or "baseline").strip() or "baseline",
                doc_name=str(raw.get("doc_name") or "").strip(),
                source_pdf_path=str(raw.get("source_pdf_path") or "").strip(),
                doc_id=str(raw.get("doc_id") or "").strip(),
                include_in_default_batch=bool(raw.get("include_in_default_batch")),
                expected_page_count=int(raw.get("expected_page_count") or 0),
            )
        )
    return normalized


def select_example_books(
    *,
    manifest_path: Path | None = None,
    include_all: bool = False,
    group: str = "",
    slug: str = "",
    folder: str = "",
    doc_id: str = "",
) -> list[ExampleBook]:
    books = load_example_manifest(manifest_path)
    normalized_group = str(group or "").strip().lower()
    normalized_slug = str(slug or "").strip()
    normalized_folder = str(folder or "").strip()
    normalized_doc_id = str(doc_id or "").strip()

    if normalized_slug:
        books = [book for book in books if book.slug == normalized_slug]
    if normalized_folder:
        books = [book for book in books if book.folder == normalized_folder]
    if normalized_doc_id:
        books = [book for book in books if book.doc_id == normalized_doc_id]
    if normalized_group and normalized_group != "all":
        books = [book for book in books if book.group == normalized_group]
    if not include_all and not normalized_slug and not normalized_folder and not normalized_doc_id and not normalized_group:
        books = [book for book in books if book.include_in_default_batch]
    return books


def manifest_doc_id_map(manifest_path: Path | None = None) -> dict[str, ExampleBook]:
    return {book.doc_id: book for book in load_example_manifest(manifest_path)}


def manifest_slug_map(manifest_path: Path | None = None) -> dict[str, ExampleBook]:
    return {book.slug: book for book in load_example_manifest(manifest_path)}


__all__ = [
    "ExampleBook",
    "MANIFEST_PATH",
    "load_example_manifest",
    "manifest_doc_id_map",
    "manifest_slug_map",
    "select_example_books",
]

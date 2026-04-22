"""SQLite 拆库路径 helper。"""

from __future__ import annotations

import os

import config


def get_catalog_db_path() -> str:
    """返回 catalog.db 路径。"""
    config.ensure_dirs()
    return os.path.join(config.DATA_DIR, "catalog.db")


def get_document_db_path(doc_id: str, *, ensure_parent_dir: bool = True) -> str:
    """返回文档私有 doc.db 路径。"""
    config.ensure_dirs()
    normalized_doc_id = config.normalize_doc_id(doc_id)
    if not normalized_doc_id:
        raise ValueError("doc_id 不能为空")
    doc_dir = os.path.join(config.DOCS_DIR, normalized_doc_id)
    if ensure_parent_dir:
        os.makedirs(doc_dir, exist_ok=True)
    return os.path.join(doc_dir, "doc.db")

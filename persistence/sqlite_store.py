"""SQLite Repository：文档、翻译、FNM 数据的组合仓储边界。"""

from __future__ import annotations

import inspect
import os
from typing import Any

from config import get_sqlite_db_path, normalize_doc_id
from persistence.sqlite_catalog_schema import initialize_catalog_database
from persistence.sqlite_db_paths import get_catalog_db_path, get_document_db_path
from persistence.sqlite_repo_dev import DevRepoMixin
from persistence.sqlite_repo_documents import DocumentRepoMixin
from persistence.sqlite_repo_fnm import FnmRepoMixin
from persistence.sqlite_repo_state import StateRepoMixin
from persistence.sqlite_repo_translation import TranslationRepoMixin
from persistence.sqlite_schema import (
    SCHEMA_VERSION,
    TOC_SOURCE_AUTO,
    TOC_SOURCE_AUTO_PDF,
    TOC_SOURCE_AUTO_VISUAL,
    TOC_SOURCE_USER,
    TOC_SOURCES,
    _toc_column_for_source,
    get_connection,
    initialize_database,
    read_connection,
    transaction,
)


class SingleDBRepository(
    DocumentRepoMixin,
    TranslationRepoMixin,
    FnmRepoMixin,
    DevRepoMixin,
    StateRepoMixin,
):
    """单库仓储实现。"""

    def __init__(self, db_path: str | None = None, *, initializer=initialize_database):
        self.db_path = db_path or get_sqlite_db_path()
        initializer(self.db_path)


class SQLiteRepository:
    """多库 facade：catalog + per-doc doc.db。

    - 传入 db_path 时，退化为单库模式（兼容测试/脚本）。
    - 不传 db_path 时，默认走拆库模式：
      - 文档目录/全局状态 -> catalog.db
      - 页、翻译、FNM、文档级状态 -> documents/{doc_id}/doc.db
    """

    _CATALOG_METHODS = {
        "upsert_document",
        "get_document",
        "list_documents",
        "set_document_toc",
        "get_document_toc",
        "set_document_toc_for_source",
        "get_document_toc_for_source",
        "set_document_visual_toc_status",
        "set_document_toc_source_offset",
        "get_document_toc_source_offset",
        "set_document_toc_file_meta",
        "delete_document",
        "set_app_state",
        "get_app_state",
    }
    _DOC_CONTEXT_METHODS = {
        "list_translation_segments",
        "list_segment_revisions",
        "save_translation_page_revision",
        "list_translation_page_revisions",
    }

    def __init__(self, db_path: str | None = None):
        self._single_repo: SingleDBRepository | None = None
        self._catalog_repo: SingleDBRepository | None = None
        self._doc_repos: dict[str, SingleDBRepository] = {}
        if db_path:
            self._single_repo = SingleDBRepository(db_path)
        else:
            self._catalog_repo = SingleDBRepository(
                get_catalog_db_path(),
                initializer=initialize_catalog_database,
            )

    def _get_catalog_repo(self) -> SingleDBRepository:
        if self._single_repo is not None:
            return self._single_repo
        if self._catalog_repo is None:
            self._catalog_repo = SingleDBRepository(
                get_catalog_db_path(),
                initializer=initialize_catalog_database,
            )
        return self._catalog_repo

    def _get_document_repo(self, doc_id: str) -> SingleDBRepository:
        if self._single_repo is not None:
            return self._single_repo
        normalized_doc_id = normalize_doc_id(doc_id)
        if not normalized_doc_id:
            return self._get_catalog_repo()
        repo = self._doc_repos.get(normalized_doc_id)
        if repo is None:
            repo = SingleDBRepository(get_document_db_path(normalized_doc_id))
            self._doc_repos[normalized_doc_id] = repo
        return repo

    def _resolve_doc_id_for_call(self, method_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        if self._single_repo is not None:
            return ""
        func = getattr(SingleDBRepository, method_name, None)
        if func is None or not callable(func):
            return ""
        try:
            sig = inspect.signature(func)
            bound = sig.bind_partial(None, *args, **kwargs)
            if "doc_id" in bound.arguments:
                return normalize_doc_id(bound.arguments.get("doc_id"))
        except Exception:
            return ""
        if method_name in self._DOC_CONTEXT_METHODS:
            current_doc_id = self._get_catalog_repo().get_app_state("current_doc_id")
            return normalize_doc_id(current_doc_id)
        return ""

    def _choose_repo(self, method_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> SingleDBRepository:
        if self._single_repo is not None:
            return self._single_repo
        if method_name in self._CATALOG_METHODS:
            return self._get_catalog_repo()
        doc_id = self._resolve_doc_id_for_call(method_name, args, kwargs)
        if doc_id:
            return self._get_document_repo(doc_id)
        return self._get_catalog_repo()

    def upsert_document(self, doc_id: str, name: str, **fields) -> None:
        if self._single_repo is not None:
            self._single_repo.upsert_document(doc_id, name, **fields)
            return
        normalized_doc_id = normalize_doc_id(doc_id)
        self._get_catalog_repo().upsert_document(normalized_doc_id, name, **fields)
        if normalized_doc_id:
            self._get_document_repo(normalized_doc_id).upsert_document(normalized_doc_id, name, **fields)

    def delete_document(self, doc_id: str) -> None:
        if self._single_repo is not None:
            self._single_repo.delete_doc_scoped_state(doc_id)
            self._single_repo.delete_document(doc_id)
            return
        normalized_doc_id = normalize_doc_id(doc_id)
        self._get_catalog_repo().delete_doc_scoped_state(normalized_doc_id)
        self._get_catalog_repo().delete_document(normalized_doc_id)
        if not normalized_doc_id:
            return
        doc_db_path = get_document_db_path(normalized_doc_id, ensure_parent_dir=False)
        if os.path.exists(doc_db_path):
            self._get_document_repo(normalized_doc_id).delete_document(normalized_doc_id)

    def __getattr__(self, item: str):
        if not hasattr(SingleDBRepository, item):
            raise AttributeError(item)

        def _call(*args, **kwargs):
            repo = self._choose_repo(item, args, kwargs)
            return getattr(repo, item)(*args, **kwargs)

        return _call


__all__ = [
    "SCHEMA_VERSION",
    "TOC_SOURCE_AUTO",
    "TOC_SOURCE_AUTO_PDF",
    "TOC_SOURCE_AUTO_VISUAL",
    "TOC_SOURCE_USER",
    "TOC_SOURCES",
    "_toc_column_for_source",
    "get_connection",
    "initialize_database",
    "read_connection",
    "transaction",
    "SingleDBRepository",
    "SQLiteRepository",
]

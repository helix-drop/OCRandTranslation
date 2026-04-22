"""doc.db 仓储边界。"""

from __future__ import annotations

from config import normalize_doc_id
from persistence.sqlite_db_paths import get_document_db_path
from persistence.sqlite_store import SingleDBRepository


class DocumentRepository(SingleDBRepository):
    """文档私有仓储（当前阶段先复用 SQLiteRepository 能力集）。"""

    def __init__(self, doc_id: str, db_path: str | None = None):
        normalized_doc_id = normalize_doc_id(doc_id)
        if not db_path and not normalized_doc_id:
            raise ValueError("doc_id 不能为空")
        self.doc_id = normalized_doc_id
        super().__init__(db_path or get_document_db_path(normalized_doc_id))

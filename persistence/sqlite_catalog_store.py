"""catalog.db 仓储边界。"""

from __future__ import annotations

from persistence.sqlite_catalog_schema import initialize_catalog_database
from persistence.sqlite_db_paths import get_catalog_db_path
from persistence.sqlite_store import SingleDBRepository


class CatalogRepository(SingleDBRepository):
    """全局 catalog 仓储（当前阶段先复用 SQLiteRepository 能力集）。"""

    def __init__(self, db_path: str | None = None):
        super().__init__(
            db_path or get_catalog_db_path(),
            initializer=initialize_catalog_database,
        )

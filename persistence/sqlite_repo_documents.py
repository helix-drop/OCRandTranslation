"""SQLite 文档与页面仓储 mixin。"""

from __future__ import annotations

import json
import os
import time

from config import get_sqlite_db_path
from persistence.sqlite_schema import (
    TOC_SOURCE_USER,
    _toc_column_for_source,
    initialize_database,
    read_connection,
    transaction,
)


class DocumentRepoMixin:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or get_sqlite_db_path()
        initialize_database(self.db_path)

    def upsert_document(self, doc_id: str, name: str, **fields) -> None:
        now = int(fields.pop("updated_at", time.time()))
        created_at = int(fields.pop("created_at", now))
        payload = {
            "page_count": int(fields.pop("page_count", 0)),
            "entry_count": int(fields.pop("entry_count", 0)),
            "has_pdf": int(fields.pop("has_pdf", 0)),
            "last_entry_idx": int(fields.pop("last_entry_idx", 0)),
            "status": fields.pop("status", "ready"),
            "source_pdf_path": fields.pop("source_pdf_path", None),
            "toc_json": fields.pop("toc_json", None),
            "cleanup_headers_footers": int(fields.pop("cleanup_headers_footers", 1) or 0),
            "toc_user_json": fields.pop("toc_user_json", None),
            "toc_auto_pdf_json": fields.pop("toc_auto_pdf_json", None),
            "toc_auto_visual_json": fields.pop("toc_auto_visual_json", None),
            "auto_visual_toc_enabled": int(fields.pop("auto_visual_toc_enabled", 0) or 0),
            "toc_visual_status": fields.pop("toc_visual_status", "idle"),
            "toc_visual_message": fields.pop("toc_visual_message", None),
            "toc_visual_model_id": fields.pop("toc_visual_model_id", None),
            "toc_visual_phase": fields.pop("toc_visual_phase", None),
            "toc_visual_progress_pct": int(fields.pop("toc_visual_progress_pct", 0) or 0),
            "toc_visual_progress_label": fields.pop("toc_visual_progress_label", None),
            "toc_visual_progress_detail": fields.pop("toc_visual_progress_detail", None),
        }
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO documents(
                    id, name, created_at, updated_at, page_count, entry_count,
                    has_pdf, last_entry_idx, status, source_pdf_path, toc_json,
                    toc_user_json, toc_auto_pdf_json, toc_auto_visual_json,
                    cleanup_headers_footers, auto_visual_toc_enabled,
                    toc_visual_status, toc_visual_message, toc_visual_model_id,
                    toc_visual_phase, toc_visual_progress_pct, toc_visual_progress_label, toc_visual_progress_detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    updated_at=excluded.updated_at,
                    page_count=excluded.page_count,
                    entry_count=excluded.entry_count,
                    has_pdf=excluded.has_pdf,
                    last_entry_idx=excluded.last_entry_idx,
                    status=excluded.status,
                    source_pdf_path=COALESCE(excluded.source_pdf_path, documents.source_pdf_path),
                    toc_json=COALESCE(excluded.toc_json, documents.toc_json),
                    toc_user_json=COALESCE(excluded.toc_user_json, documents.toc_user_json),
                    toc_auto_pdf_json=COALESCE(excluded.toc_auto_pdf_json, documents.toc_auto_pdf_json),
                    toc_auto_visual_json=COALESCE(excluded.toc_auto_visual_json, documents.toc_auto_visual_json),
                    cleanup_headers_footers=excluded.cleanup_headers_footers,
                    auto_visual_toc_enabled=excluded.auto_visual_toc_enabled,
                    toc_visual_status=COALESCE(excluded.toc_visual_status, documents.toc_visual_status),
                    toc_visual_message=COALESCE(excluded.toc_visual_message, documents.toc_visual_message),
                    toc_visual_model_id=COALESCE(excluded.toc_visual_model_id, documents.toc_visual_model_id),
                    toc_visual_phase=COALESCE(excluded.toc_visual_phase, documents.toc_visual_phase),
                    toc_visual_progress_pct=excluded.toc_visual_progress_pct,
                    toc_visual_progress_label=COALESCE(excluded.toc_visual_progress_label, documents.toc_visual_progress_label),
                    toc_visual_progress_detail=COALESCE(excluded.toc_visual_progress_detail, documents.toc_visual_progress_detail)
                """,
                (
                    doc_id,
                    name,
                    created_at,
                    now,
                    payload["page_count"],
                    payload["entry_count"],
                    payload["has_pdf"],
                    payload["last_entry_idx"],
                    payload["status"],
                    payload["source_pdf_path"],
                    payload["toc_json"],
                    payload["toc_user_json"],
                    payload["toc_auto_pdf_json"],
                    payload["toc_auto_visual_json"],
                    payload["cleanup_headers_footers"],
                    payload["auto_visual_toc_enabled"],
                    payload["toc_visual_status"],
                    payload["toc_visual_message"],
                    payload["toc_visual_model_id"],
                    payload["toc_visual_phase"],
                    payload["toc_visual_progress_pct"],
                    payload["toc_visual_progress_label"],
                    payload["toc_visual_progress_detail"],
                ),
            )

    def get_document(self, doc_id: str) -> dict | None:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
            if not row:
                return None
            payload = dict(row)
            payload["created"] = payload.get("created_at", 0)
            return payload

    def list_documents(self) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC, id DESC"
            ).fetchall()
            docs = []
            for row in rows:
                payload = dict(row)
                payload["created"] = payload.get("created_at", 0)
                docs.append(payload)
            return docs

    def set_document_toc(self, doc_id: str, toc_items: list[dict]) -> None:
        self.set_document_toc_for_source(doc_id, TOC_SOURCE_USER, toc_items)

    def get_document_toc(self, doc_id: str) -> list[dict]:
        return self.get_document_toc_for_source(doc_id, TOC_SOURCE_USER)

    def set_document_toc_for_source(self, doc_id: str, source: str, toc_items: list[dict]) -> None:
        now = int(time.time())
        toc_json = json.dumps(toc_items or [], ensure_ascii=False)
        column = _toc_column_for_source(source)
        with transaction(self.db_path) as conn:
            conn.execute(
                f"""
                UPDATE documents
                SET {column} = ?, updated_at = ?
                WHERE id = ?
                """,
                (toc_json, now, doc_id),
            )

    def get_document_toc_for_source(self, doc_id: str, source: str) -> list[dict]:
        column = _toc_column_for_source(source)
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                f"SELECT {column} AS toc_json FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
            if not row or not row["toc_json"]:
                return []
            try:
                items = json.loads(row["toc_json"])
            except Exception:
                return []
            return items if isinstance(items, list) else []

    def set_document_visual_toc_status(
        self,
        doc_id: str,
        status: str,
        *,
        message: str = "",
        model_id: str = "",
    ) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE documents
                SET toc_visual_status = ?, toc_visual_message = ?, toc_visual_model_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(status or "idle").strip() or "idle", str(message or ""), str(model_id or ""), now, doc_id),
            )

    def set_document_toc_source_offset(self, doc_id: str, source: str, offset: int) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                "UPDATE documents SET toc_source = ?, toc_page_offset = ?, updated_at = ? WHERE id = ?",
                (source, int(offset), now, doc_id),
            )

    def get_document_toc_source_offset(self, doc_id: str) -> tuple[str, int]:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT toc_source, toc_page_offset FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
            if not row:
                return ("auto", 0)
            return (row["toc_source"] or "auto", int(row["toc_page_offset"] or 0))

    def set_document_toc_file_meta(self, doc_id: str, file_name: str, uploaded_at: int | None = None) -> None:
        now = int(time.time())
        effective_uploaded_at = int(uploaded_at or now)
        normalized_name = os.path.basename(str(file_name or "").strip())
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE documents
                SET toc_file_name = ?, toc_file_uploaded_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized_name, effective_uploaded_at, now, doc_id),
            )

    def delete_document(self, doc_id: str) -> None:
        with transaction(self.db_path) as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    # P0-2: 清洗 OCR 输出中的编码乱码与有害控制字符
    _CONTROL_CHAR_RE = __import__("re").compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    def _sanitize_page_text(self, text) -> str | None:
        """清洗页面文本：先尝试编码偏移修复（处理系统性乱码），再做控制字符兜底清洗。"""
        if text is None:
            return None
        raw = str(text)
        if not raw.strip():
            return raw
        # 仅当检测到控制字符占比较高时才尝试编码修复（避免对正常文本做不必要的处理）
        control_count = len(self._CONTROL_CHAR_RE.findall(raw))
        visible_count = len(raw.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", ""))
        if visible_count > 0 and control_count / visible_count > 0.05:
            try:
                from document.text_layer_fixer import detect_and_fix_text
                fixed, method = detect_and_fix_text(raw, raise_on_failure=False)
                if method and method != "original":
                    return fixed
            except Exception:
                pass
        # 兜底：清洗残余控制字符
        cleaned = self._CONTROL_CHAR_RE.sub(" ", raw)
        return cleaned

    def replace_pages(self, doc_id: str, pages: list[dict]) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
            for page in pages:
                # 清洗 markdown / footnotes 中的控制字符
                raw_md = page.get("markdown")
                raw_fn = page.get("footnotes")
                clean_md = self._sanitize_page_text(raw_md) if isinstance(raw_md, str) else raw_md
                clean_fn = self._sanitize_page_text(raw_fn) if isinstance(raw_fn, str) else raw_fn
                # 如果 markdown 是 dict（带 text 子字段），递归清洗
                if isinstance(raw_md, dict):
                    clean_md = dict(raw_md)
                    if isinstance(clean_md.get("text"), str):
                        clean_md["text"] = self._sanitize_page_text(clean_md["text"])
                # payload_json 也同步清洗
                clean_page = dict(page)
                clean_page["markdown"] = clean_md
                clean_page["footnotes"] = clean_fn
                conn.execute(
                    """
                    INSERT INTO pages(
                        doc_id, book_page, file_idx, img_w, img_h, markdown,
                        footnotes, text_source, payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        int(page["bookPage"]),
                        int(page.get("fileIdx", 0) or 0),
                        page.get("imgW"),
                        page.get("imgH"),
                        clean_md if isinstance(clean_md, str) else json.dumps(clean_md, ensure_ascii=False) if clean_md else None,
                        clean_fn,
                        page.get("textSource", "ocr"),
                        json.dumps(clean_page, ensure_ascii=False),
                        now,
                        now,
                    ),
                )


    def load_pages(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT book_page, file_idx, img_w, img_h, markdown, footnotes, text_source, payload_json
                FROM pages
                WHERE doc_id = ?
                ORDER BY book_page ASC
                """,
                (doc_id,),
            ).fetchall()
            pages = []
            for row in rows:
                payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
                if not isinstance(payload, dict):
                    payload = {}
                payload.update({
                    "bookPage": row["book_page"],
                    "fileIdx": row["file_idx"],
                    "imgW": row["img_w"],
                    "imgH": row["img_h"],
                    "markdown": row["markdown"],
                    "footnotes": row["footnotes"],
                    "textSource": row["text_source"],
                })
                pages.append(payload)
            return pages

"""SQLite FNM 仓储 mixin。"""

from __future__ import annotations

import json
import sqlite3
import time

from persistence.sqlite_schema import read_connection, transaction


class FnmRepoMixin:
    def _row_to_fnm_run(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        for key in (
            "review_counts_json",
            "blocking_reasons_json",
            "link_summary_json",
            "page_partition_summary_json",
            "chapter_mode_summary_json",
        ):
            raw = payload.get(key)
            if raw:
                try:
                    payload[key[:-5]] = json.loads(raw)
                except Exception:
                    payload[key[:-5]] = raw
        payload["updated_at"] = float(payload.get("updated_at", 0) or 0)
        payload["created_at"] = float(payload.get("created_at", 0) or 0)
        return payload

    def _row_to_fnm_note(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["pages"] = json.loads(payload.pop("pages_json") or "[]")
        payload["updated_at"] = float(payload.get("updated_at", 0) or 0)
        payload["created_at"] = float(payload.get("created_at", 0) or 0)
        return payload

    def _row_to_fnm_unit(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["page_segments"] = json.loads(payload.pop("page_segments_json") or "[]")
        owner_kind = str(payload.get("owner_kind") or "").strip().lower()
        if not owner_kind:
            owner_kind = "chapter" if str(payload.get("kind") or "") == "body" else "note_region"
            payload["owner_kind"] = owner_kind
        owner_id = str(payload.get("owner_id") or "").strip()
        if not owner_id:
            payload["owner_id"] = str(payload.get("section_id") or "").strip()
        payload["updated_at"] = float(payload.get("updated_at", 0) or 0)
        payload["created_at"] = float(payload.get("created_at", 0) or 0)
        return payload

    def _row_to_fnm_page_entry(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = json.loads(row["entry_json"] or "{}") if row["entry_json"] else {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("_pageBP", int(row["book_page"]))
        payload.setdefault("pages", row["pages_label"] or str(row["book_page"]))
        payload["_fnm_source"] = json.loads(row["source_json"] or "{}") if row["source_json"] else {}
        payload["_fnm_section_id"] = row["section_id"]
        payload["_fnm_section_title"] = row["section_title"]
        payload["_fnm_section_start_page"] = row["section_start_page"]
        payload["_fnm_section_end_page"] = row["section_end_page"]
        payload["_updated_at"] = float(row["updated_at"] or 0)
        return payload

    @staticmethod
    def _loads_json(raw: str | None, *, default):
        if not raw:
            return default
        try:
            value = json.loads(raw)
        except Exception:
            return default
        return value

    def _row_to_fnm_review_override(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["payload"] = self._loads_json(payload.pop("payload_json", None), default={})
        return payload

    def _row_to_fnm_page(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["has_note_heading"] = bool(payload.get("has_note_heading"))
        payload["note_scan_summary"] = self._loads_json(payload.pop("note_scan_summary_json", None), default={})
        return payload

    def _row_to_fnm_chapter(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["pages"] = self._loads_json(payload.pop("pages_json", None), default=[])
        return payload

    def _row_to_fnm_heading_candidate(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["top_band"] = bool(payload.get("top_band"))
        payload["suppressed_as_chapter"] = bool(payload.get("suppressed_as_chapter"))
        payload["font_name"] = str(payload.get("font_name") or "")
        payload["font_weight_hint"] = str(payload.get("font_weight_hint") or "unknown")
        payload["align_hint"] = str(payload.get("align_hint") or "unknown")
        payload["heading_level_hint"] = int(payload.get("heading_level_hint") or 0)
        return payload

    def _row_to_fnm_note_region(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["pages"] = self._loads_json(payload.pop("pages_json", None), default=[])
        raw_alignment = payload.get("region_marker_alignment_ok")
        payload["region_marker_alignment_ok"] = (
            bool(raw_alignment) if raw_alignment is not None else None
        )
        return payload

    def _row_to_fnm_chapter_note_mode(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["sampled_pages"] = self._loads_json(payload.pop("sampled_pages_json", None), default=[])
        return payload

    def _row_to_fnm_section_head(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["rejected_chapter_candidate"] = bool(payload.get("rejected_chapter_candidate"))
        return payload

    def _row_to_fnm_structure_review(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["page_range"] = [payload.pop("page_start", None), payload.pop("page_end", None)]
        payload["payload_json"] = self._loads_json(payload.pop("payload_json", None), default={})
        return payload

    def create_fnm_run(self, doc_id: str, **fields) -> int:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO fnm_runs(
                    doc_id, status, error_msg, page_count, section_count, note_count, unit_count,
                    structure_state, review_counts_json, blocking_reasons_json, link_summary_json,
                    page_partition_summary_json, chapter_mode_summary_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    fields.get("status", "pending"),
                    fields.get("error_msg"),
                    int(fields.get("page_count", 0) or 0),
                    int(fields.get("section_count", 0) or 0),
                    int(fields.get("note_count", 0) or 0),
                    int(fields.get("unit_count", 0) or 0),
                    fields.get("structure_state"),
                    json.dumps(fields.get("review_counts") or {}, ensure_ascii=False),
                    json.dumps(fields.get("blocking_reasons") or [], ensure_ascii=False),
                    json.dumps(fields.get("link_summary") or {}, ensure_ascii=False),
                    json.dumps(fields.get("page_partition_summary") or {}, ensure_ascii=False),
                    json.dumps(fields.get("chapter_mode_summary") or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def update_fnm_run(self, doc_id: str, run_id: int, **fields) -> None:
        # doc_id 作为正式参数：让 SQLiteRepository 的 dispatcher 在拆库场景下
        # 能通过方法签名正确路由到对应文档库；否则依赖 app_state.current_doc_id
        # 会在批处理场景静默走空。
        del doc_id  # 实际写库由 dispatcher 选定，这里不直接使用。
        if not run_id:
            return
        now = int(time.time())
        with transaction(self.db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM fnm_runs WHERE id = ?",
                (int(run_id),),
            ).fetchone()
            if not existing:
                return
            payload = dict(existing)
            payload.update(fields)
            conn.execute(
                """
                UPDATE fnm_runs
                SET status = ?, error_msg = ?, page_count = ?, section_count = ?, note_count = ?, unit_count = ?,
                    validation_json = COALESCE(?, validation_json),
                    structure_state = COALESCE(?, structure_state),
                    review_counts_json = COALESCE(?, review_counts_json),
                    blocking_reasons_json = COALESCE(?, blocking_reasons_json),
                    link_summary_json = COALESCE(?, link_summary_json),
                    page_partition_summary_json = COALESCE(?, page_partition_summary_json),
                    chapter_mode_summary_json = COALESCE(?, chapter_mode_summary_json),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.get("status", "pending"),
                    payload.get("error_msg"),
                    int(payload.get("page_count", 0) or 0),
                    int(payload.get("section_count", 0) or 0),
                    int(payload.get("note_count", 0) or 0),
                    int(payload.get("unit_count", 0) or 0),
                    payload.get("validation_json"),
                    payload.get("structure_state"),
                    json.dumps(payload.get("review_counts"), ensure_ascii=False) if "review_counts" in payload else None,
                    json.dumps(payload.get("blocking_reasons"), ensure_ascii=False) if "blocking_reasons" in payload else None,
                    json.dumps(payload.get("link_summary"), ensure_ascii=False) if "link_summary" in payload else None,
                    json.dumps(payload.get("page_partition_summary"), ensure_ascii=False) if "page_partition_summary" in payload else None,
                    json.dumps(payload.get("chapter_mode_summary"), ensure_ascii=False) if "chapter_mode_summary" in payload else None,
                    now,
                    int(run_id),
                ),
            )

    def get_latest_fnm_run(self, doc_id: str) -> dict | None:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM fnm_runs
                WHERE doc_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (doc_id,),
            ).fetchone()
            return self._row_to_fnm_run(row)

    @staticmethod
    def _delete_fnm_cascade(
        conn,
        doc_id: str,
        *,
        include_notes_units: bool = True,
        include_structure: bool = True,
        include_review_overrides: bool = False,
    ) -> None:
        if include_review_overrides:
            conn.execute("DELETE FROM fnm_review_overrides_v2 WHERE doc_id = ?", (doc_id,))
        if include_structure:
            conn.execute("DELETE FROM fnm_structure_reviews WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_note_links WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_body_anchors WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_note_items WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_section_heads WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_chapter_note_modes WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_note_regions WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_heading_candidates WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_chapters WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_pages WHERE doc_id = ?", (doc_id,))
        if include_notes_units:
            conn.execute("DELETE FROM fnm_translation_units WHERE doc_id = ?", (doc_id,))

    def clear_fnm_data(self, doc_id: str) -> None:
        with transaction(self.db_path) as conn:
            self._delete_fnm_cascade(conn, doc_id, include_review_overrides=True)

    def replace_fnm_data(
        self,
        doc_id: str,
        *,
        notes: list[dict] | None = None,
        units: list[dict],
        preserve_structure: bool = False,
    ) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            self._delete_fnm_cascade(
                conn,
                doc_id,
                include_structure=not preserve_structure,
            )
            for unit in units or []:
                conn.execute(
                    """
                    INSERT INTO fnm_translation_units(
                        unit_id, doc_id, kind, owner_kind, owner_id, section_id, section_title, section_start_page, section_end_page,
                        note_id, page_start, page_end, char_count,
                        source_text, translated_text, status, error_msg, target_ref, page_segments_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        unit.get("unit_id"),
                        doc_id,
                        unit.get("kind"),
                        unit.get("owner_kind") or ("chapter" if str(unit.get("kind") or "") == "body" else "note_region"),
                        unit.get("owner_id") or unit.get("section_id"),
                        unit.get("section_id"),
                        unit.get("section_title"),
                        int(unit.get("section_start_page")) if unit.get("section_start_page") is not None else None,
                        int(unit.get("section_end_page")) if unit.get("section_end_page") is not None else None,
                        unit.get("note_id"),
                        int(unit.get("page_start")) if unit.get("page_start") is not None else None,
                        int(unit.get("page_end")) if unit.get("page_end") is not None else None,
                        int(unit.get("char_count", 0) or 0),
                        unit.get("source_text"),
                        unit.get("translated_text"),
                        unit.get("status", "pending"),
                        unit.get("error_msg"),
                        unit.get("target_ref"),
                        json.dumps(unit.get("page_segments") or [], ensure_ascii=False),
                        now,
                        now,
                    ),
                )

    def replace_fnm_structure(
        self,
        doc_id: str,
        *,
        pages: list[dict],
        chapters: list[dict],
        heading_candidates: list[dict],
        note_regions: list[dict],
        chapter_note_modes: list[dict],
        section_heads: list[dict],
        note_items: list[dict],
        body_anchors: list[dict],
        note_links: list[dict],
        structure_reviews: list[dict],
    ) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute("DELETE FROM fnm_structure_reviews WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_note_links WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_body_anchors WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_note_items WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_section_heads WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_chapter_note_modes WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_note_regions WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_heading_candidates WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_chapters WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_pages WHERE doc_id = ?", (doc_id,))

            for row in pages or []:
                conn.execute(
                    """
                    INSERT INTO fnm_pages(
                        doc_id, page_no, target_pdf_page, page_role, role_confidence, role_reason,
                        section_hint, has_note_heading, note_scan_summary_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        int(row.get("page_no") or 0),
                        int(row.get("target_pdf_page") or 0) if row.get("target_pdf_page") is not None else None,
                        row.get("page_role"),
                        float(row.get("role_confidence", 0.0) or 0.0),
                        row.get("role_reason"),
                        row.get("section_hint"),
                        1 if bool(row.get("has_note_heading")) else 0,
                        json.dumps(row.get("note_scan_summary") or {}, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            for row in chapters or []:
                conn.execute(
                    """
                    INSERT INTO fnm_chapters(
                        doc_id, chapter_id, title, start_page, end_page, pages_json, source, boundary_state,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        row.get("chapter_id"),
                        row.get("title"),
                        int(row.get("start_page") or 0),
                        int(row.get("end_page") or 0),
                        json.dumps(row.get("pages") or [], ensure_ascii=False),
                        row.get("source"),
                        row.get("boundary_state") or "ready",
                        now,
                        now,
                    ),
                )
            for row in heading_candidates or []:
                conn.execute(
                    """
                    INSERT INTO fnm_heading_candidates(
                        doc_id, heading_id, page_no, text, normalized_text, source, block_label,
                        top_band, font_height, x, y, width_estimate, font_name, font_weight_hint,
                        align_hint, width_ratio, heading_level_hint, confidence, heading_family_guess,
                        suppressed_as_chapter, reject_reason, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        row.get("heading_id"),
                        int(row.get("page_no") or 0),
                        row.get("text") or "",
                        row.get("normalized_text") or "",
                        row.get("source"),
                        row.get("block_label"),
                        1 if bool(row.get("top_band")) else 0,
                        float(row.get("font_height")) if row.get("font_height") is not None else None,
                        float(row.get("x")) if row.get("x") is not None else None,
                        float(row.get("y")) if row.get("y") is not None else None,
                        float(row.get("width_estimate")) if row.get("width_estimate") is not None else None,
                        row.get("font_name") or "",
                        row.get("font_weight_hint") or "unknown",
                        row.get("align_hint") or "unknown",
                        float(row.get("width_ratio")) if row.get("width_ratio") is not None else None,
                        int(row.get("heading_level_hint") or 0),
                        float(row.get("confidence", 0.0) or 0.0),
                        row.get("heading_family_guess") or "unknown",
                        1 if bool(row.get("suppressed_as_chapter")) else 0,
                        row.get("reject_reason"),
                        now,
                        now,
                    ),
                )
            for row in note_regions or []:
                conn.execute(
                    """
                    INSERT INTO fnm_note_regions(
                        doc_id, region_id, region_kind, start_page, end_page, pages_json, title_hint, bound_chapter_id,
                        region_start_first_source_marker, region_first_note_item_marker, region_marker_alignment_ok,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        row.get("region_id"),
                        row.get("region_kind"),
                        int(row.get("start_page") or 0),
                        int(row.get("end_page") or 0),
                        json.dumps(row.get("pages") or [], ensure_ascii=False),
                        row.get("title_hint"),
                        row.get("bound_chapter_id"),
                        row.get("region_start_first_source_marker"),
                        row.get("region_first_note_item_marker"),
                        1 if bool(row.get("region_marker_alignment_ok")) else 0,
                        now,
                        now,
                    ),
                )
            for row in chapter_note_modes or []:
                conn.execute(
                    """
                    INSERT INTO fnm_chapter_note_modes(
                        doc_id, chapter_id, chapter_title, note_mode, sampled_pages_json, detection_confidence,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        row.get("chapter_id"),
                        row.get("chapter_title"),
                        row.get("note_mode"),
                        json.dumps(row.get("sampled_pages") or [], ensure_ascii=False),
                        float(row.get("detection_confidence", 0.0) or 0.0),
                        now,
                        now,
                    ),
                )
            for row in section_heads or []:
                conn.execute(
                    """
                    INSERT INTO fnm_section_heads(
                        doc_id, section_head_id, chapter_id, page_no, text, normalized_text, source,
                        confidence, heading_family_guess, rejected_chapter_candidate, reject_reason,
                        derived_from_heading_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        row.get("section_head_id"),
                        row.get("chapter_id"),
                        int(row.get("page_no") or 0),
                        row.get("text") or "",
                        row.get("normalized_text") or "",
                        row.get("source"),
                        float(row.get("confidence", 0.0) or 0.0),
                        row.get("heading_family_guess") or "section",
                        1 if bool(row.get("rejected_chapter_candidate")) else 0,
                        row.get("reject_reason"),
                        row.get("derived_from_heading_id"),
                        now,
                        now,
                    ),
                )
            for row in note_items or []:
                conn.execute(
                    """
                    INSERT INTO fnm_note_items(
                        doc_id, note_item_id, note_kind, chapter_id, region_id, marker, normalized_marker,
                        occurrence, source_text, page_no, display_marker, source_marker, title_hint,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        row.get("note_item_id"),
                        row.get("note_kind"),
                        row.get("chapter_id"),
                        row.get("region_id"),
                        row.get("marker"),
                        row.get("normalized_marker"),
                        int(row.get("occurrence", 0) or 0),
                        row.get("source_text"),
                        int(row.get("page_no") or 0),
                        row.get("display_marker"),
                        row.get("source_marker"),
                        row.get("title_hint"),
                        now,
                        now,
                    ),
                )
            for row in body_anchors or []:
                conn.execute(
                    """
                    INSERT INTO fnm_body_anchors(
                        doc_id, anchor_id, chapter_id, page_no, paragraph_index, char_start, char_end,
                        source_marker, normalized_marker, anchor_kind, certainty, source_text,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        row.get("anchor_id"),
                        row.get("chapter_id"),
                        int(row.get("page_no") or 0),
                        int(row.get("paragraph_index", 0) or 0),
                        int(row.get("char_start", 0) or 0),
                        int(row.get("char_end", 0) or 0),
                        row.get("source_marker"),
                        row.get("normalized_marker"),
                        row.get("anchor_kind"),
                        float(row.get("certainty", 0.0) or 0.0),
                        row.get("source_text"),
                        now,
                        now,
                    ),
                )
            for row in note_links or []:
                conn.execute(
                    """
                    INSERT INTO fnm_note_links(
                        doc_id, link_id, chapter_id, region_id, note_item_id, anchor_id, status, resolver,
                        confidence, note_kind, marker, page_no_start, page_no_end, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        row.get("link_id"),
                        row.get("chapter_id"),
                        row.get("region_id"),
                        row.get("note_item_id"),
                        row.get("anchor_id"),
                        row.get("status"),
                        row.get("resolver"),
                        float(row.get("confidence", 0.0) or 0.0),
                        row.get("note_kind"),
                        row.get("marker"),
                        int(row.get("page_no_start")) if row.get("page_no_start") is not None else None,
                        int(row.get("page_no_end")) if row.get("page_no_end") is not None else None,
                        now,
                        now,
                    ),
                )
            for row in structure_reviews or []:
                page_range = list(row.get("page_range") or [None, None])
                conn.execute(
                    """
                    INSERT INTO fnm_structure_reviews(
                        doc_id, review_type, chapter_id, page_start, page_end, payload_json, severity,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        row.get("review_type"),
                        row.get("chapter_id"),
                        int(page_range[0]) if page_range[0] is not None else None,
                        int(page_range[1]) if len(page_range) > 1 and page_range[1] is not None else None,
                        json.dumps(row.get("payload_json") or {}, ensure_ascii=False),
                        row.get("severity") or "warning",
                        now,
                        now,
                    ),
                )

    # ------------------- 分阶段写入 -------------------

    @staticmethod
    def _insert_fnm_pages(conn, doc_id: str, rows: list[dict], now: int) -> None:
        for row in rows or []:
            conn.execute(
                """
                INSERT INTO fnm_pages(
                    doc_id, page_no, target_pdf_page, page_role, role_confidence, role_reason,
                    section_hint, has_note_heading, note_scan_summary_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    int(row.get("page_no") or 0),
                    int(row.get("target_pdf_page") or 0) if row.get("target_pdf_page") is not None else None,
                    row.get("page_role"),
                    float(row.get("role_confidence", 0.0) or 0.0),
                    row.get("role_reason"),
                    row.get("section_hint"),
                    1 if bool(row.get("has_note_heading")) else 0,
                    json.dumps(row.get("note_scan_summary") or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )

    @staticmethod
    def _insert_fnm_chapters(conn, doc_id: str, rows: list[dict], now: int) -> None:
        for row in rows or []:
            conn.execute(
                """
                INSERT INTO fnm_chapters(
                    doc_id, chapter_id, title, start_page, end_page, pages_json, source, boundary_state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    row.get("chapter_id"),
                    row.get("title"),
                    int(row.get("start_page") or 0),
                    int(row.get("end_page") or 0),
                    json.dumps(row.get("pages") or [], ensure_ascii=False),
                    row.get("source"),
                    row.get("boundary_state") or "ready",
                    now,
                    now,
                ),
            )

    @staticmethod
    def _insert_fnm_heading_candidates(conn, doc_id: str, rows: list[dict], now: int) -> None:
        for row in rows or []:
            conn.execute(
                """
                INSERT INTO fnm_heading_candidates(
                    doc_id, heading_id, page_no, text, normalized_text, source, block_label,
                    top_band, font_height, x, y, width_estimate, font_name, font_weight_hint,
                    align_hint, width_ratio, heading_level_hint, confidence, heading_family_guess,
                    suppressed_as_chapter, reject_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    row.get("heading_id"),
                    int(row.get("page_no") or 0),
                    row.get("text") or "",
                    row.get("normalized_text") or "",
                    row.get("source"),
                    row.get("block_label"),
                    1 if bool(row.get("top_band")) else 0,
                    float(row.get("font_height")) if row.get("font_height") is not None else None,
                    float(row.get("x")) if row.get("x") is not None else None,
                    float(row.get("y")) if row.get("y") is not None else None,
                    float(row.get("width_estimate")) if row.get("width_estimate") is not None else None,
                    row.get("font_name") or "",
                    row.get("font_weight_hint") or "unknown",
                    row.get("align_hint") or "unknown",
                    float(row.get("width_ratio")) if row.get("width_ratio") is not None else None,
                    int(row.get("heading_level_hint") or 0),
                    float(row.get("confidence", 0.0) or 0.0),
                    row.get("heading_family_guess") or "unknown",
                    1 if bool(row.get("suppressed_as_chapter")) else 0,
                    row.get("reject_reason"),
                    now,
                    now,
                ),
            )

    @staticmethod
    def _insert_fnm_section_heads(conn, doc_id: str, rows: list[dict], now: int) -> None:
        for row in rows or []:
            conn.execute(
                """
                INSERT INTO fnm_section_heads(
                    doc_id, section_head_id, chapter_id, page_no, text, normalized_text, source,
                    confidence, heading_family_guess, rejected_chapter_candidate, reject_reason,
                    derived_from_heading_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    row.get("section_head_id"),
                    row.get("chapter_id"),
                    int(row.get("page_no") or 0),
                    row.get("text") or "",
                    row.get("normalized_text") or "",
                    row.get("source"),
                    float(row.get("confidence", 0.0) or 0.0),
                    row.get("heading_family_guess") or "section",
                    1 if bool(row.get("rejected_chapter_candidate")) else 0,
                    row.get("reject_reason"),
                    row.get("derived_from_heading_id"),
                    now,
                    now,
                ),
            )

    @staticmethod
    def _insert_fnm_note_regions(conn, doc_id: str, rows: list[dict], now: int) -> None:
        for row in rows or []:
            conn.execute(
                """
                INSERT INTO fnm_note_regions(
                    doc_id, region_id, region_kind, start_page, end_page, pages_json, title_hint, bound_chapter_id,
                    region_start_first_source_marker, region_first_note_item_marker, region_marker_alignment_ok,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    row.get("region_id"),
                    row.get("region_kind"),
                    int(row.get("start_page") or 0),
                    int(row.get("end_page") or 0),
                    json.dumps(row.get("pages") or [], ensure_ascii=False),
                    row.get("title_hint"),
                    row.get("bound_chapter_id"),
                    row.get("region_start_first_source_marker"),
                    row.get("region_first_note_item_marker"),
                    1 if bool(row.get("region_marker_alignment_ok")) else 0,
                    now,
                    now,
                ),
            )

    @staticmethod
    def _insert_fnm_chapter_note_modes(conn, doc_id: str, rows: list[dict], now: int) -> None:
        for row in rows or []:
            conn.execute(
                """
                INSERT INTO fnm_chapter_note_modes(
                    doc_id, chapter_id, chapter_title, note_mode, sampled_pages_json, detection_confidence,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    row.get("chapter_id"),
                    row.get("chapter_title"),
                    row.get("note_mode"),
                    json.dumps(row.get("sampled_pages") or [], ensure_ascii=False),
                    float(row.get("detection_confidence", 0.0) or 0.0),
                    now,
                    now,
                ),
            )

    @staticmethod
    def _insert_fnm_note_items(conn, doc_id: str, rows: list[dict], now: int) -> None:
        for row in rows or []:
            conn.execute(
                """
                INSERT INTO fnm_note_items(
                    doc_id, note_item_id, note_kind, chapter_id, region_id, marker, normalized_marker,
                    occurrence, source_text, page_no, display_marker, source_marker, title_hint,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    row.get("note_item_id"),
                    row.get("note_kind"),
                    row.get("chapter_id"),
                    row.get("region_id"),
                    row.get("marker"),
                    row.get("normalized_marker"),
                    int(row.get("occurrence", 0) or 0),
                    row.get("source_text"),
                    int(row.get("page_no") or 0),
                    row.get("display_marker"),
                    row.get("source_marker"),
                    row.get("title_hint"),
                    now,
                    now,
                ),
            )

    # 清理：phase>=N 的产物表；保证下游也被清空
    @staticmethod
    def _delete_fnm_products_from_phase(conn, doc_id: str, phase_from: int) -> None:
        """清 phase>=phase_from 的产物表。和 PHASE_OUTPUT_TABLES 对齐。"""
        phase_from = int(phase_from)
        # Phase 4 及下游（含 5、6）：reviews + translation_units
        if phase_from <= 4:
            conn.execute("DELETE FROM fnm_structure_reviews WHERE doc_id = ?", (doc_id,))
        if phase_from <= 5:
            conn.execute("DELETE FROM fnm_translation_units WHERE doc_id = ?", (doc_id,))
        # Phase 3
        if phase_from <= 3:
            conn.execute("DELETE FROM fnm_note_links WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_body_anchors WHERE doc_id = ?", (doc_id,))
        # Phase 2
        if phase_from <= 2:
            conn.execute("DELETE FROM fnm_note_items WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_chapter_note_modes WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_note_regions WHERE doc_id = ?", (doc_id,))
        # Phase 1
        if phase_from <= 1:
            conn.execute("DELETE FROM fnm_section_heads WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_heading_candidates WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_chapters WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_pages WHERE doc_id = ?", (doc_id,))

    def replace_fnm_phase1_products(
        self,
        doc_id: str,
        *,
        pages: list[dict],
        chapters: list[dict],
        heading_candidates: list[dict],
        section_heads: list[dict],
    ) -> None:
        """Phase 1 产物写入：清 phase>=1 的产物（含下游），写 Phase 1 四表。"""
        now = int(time.time())
        with transaction(self.db_path) as conn:
            self._delete_fnm_products_from_phase(conn, doc_id, 1)
            self._insert_fnm_pages(conn, doc_id, pages, now)
            self._insert_fnm_chapters(conn, doc_id, chapters, now)
            self._insert_fnm_heading_candidates(conn, doc_id, heading_candidates, now)
            self._insert_fnm_section_heads(conn, doc_id, section_heads, now)

    def replace_fnm_phase2_products(
        self,
        doc_id: str,
        *,
        pages: list[dict],
        chapters: list[dict],
        heading_candidates: list[dict],
        section_heads: list[dict],
        note_regions: list[dict],
        chapter_note_modes: list[dict],
        note_items: list[dict],
    ) -> None:
        """Phase 2 产物写入：清 phase>=1 的产物（含下游），重写 Phase 1+2 七张表。

        由于 build_phase2_structure 内部会重算 Phase 1，所以 Phase 1 四表也要随之刷新。
        """
        now = int(time.time())
        with transaction(self.db_path) as conn:
            self._delete_fnm_products_from_phase(conn, doc_id, 1)
            self._insert_fnm_pages(conn, doc_id, pages, now)
            self._insert_fnm_chapters(conn, doc_id, chapters, now)
            self._insert_fnm_heading_candidates(conn, doc_id, heading_candidates, now)
            self._insert_fnm_section_heads(conn, doc_id, section_heads, now)
            self._insert_fnm_note_regions(conn, doc_id, note_regions, now)
            self._insert_fnm_chapter_note_modes(conn, doc_id, chapter_note_modes, now)
            self._insert_fnm_note_items(conn, doc_id, note_items, now)

    def delete_fnm_products_from_phase(self, doc_id: str, phase_from: int) -> None:
        """级联清理 phase>=phase_from 的 FNM 产物表。对外暴露，方便 dev 模式 reset 走 facade。"""
        with transaction(self.db_path) as conn:
            self._delete_fnm_products_from_phase(conn, doc_id, int(phase_from))

    def list_fnm_diagnostic_notes(self, doc_id: str) -> list[dict]:
        from FNM_RE import list_diagnostic_notes_for_doc

        return list_diagnostic_notes_for_doc(doc_id, repo=self)

    def list_fnm_translation_units(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_translation_units
                WHERE doc_id = ?
                ORDER BY
                    CASE
                        WHEN lower(COALESCE(owner_kind, '')) = 'chapter' THEN 0
                        WHEN lower(COALESCE(owner_kind, '')) = 'note_region' THEN 1
                        ELSE 2
                    END ASC,
                    COALESCE(section_start_page, page_start, 0) ASC,
                    page_start ASC,
                    unit_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [self._row_to_fnm_unit(row) for row in rows]

    def update_fnm_translation_unit(self, doc_id: str, unit_id: str, **fields) -> None:
        # doc_id 作为正式参数：让拆库场景下的 dispatcher 按签名路由到对应文档库，
        # 不再依赖 app_state.current_doc_id（批处理脚本不会写这个 key）。
        del doc_id
        if not unit_id:
            return
        now = int(time.time())
        with transaction(self.db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM fnm_translation_units WHERE unit_id = ?",
                (unit_id,),
            ).fetchone()
            if not existing:
                return
            payload = dict(existing)
            payload.update(fields)
            conn.execute(
                """
                UPDATE fnm_translation_units
                SET translated_text = ?, status = ?, error_msg = ?, target_ref = ?, page_segments_json = ?, updated_at = ?
                WHERE unit_id = ?
                """,
                (
                    payload.get("translated_text"),
                    payload.get("status", "pending"),
                    payload.get("error_msg"),
                    payload.get("target_ref"),
                    json.dumps(fields.get("page_segments", json.loads(payload.get("page_segments_json") or "[]")), ensure_ascii=False),
                    now,
                    unit_id,
                ),
            )

    def update_fnm_note_translation(self, doc_id: str, note_id: str, translated_text: str, *, status: str = "done") -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE fnm_translation_units
                SET translated_text = ?, status = ?, error_msg = CASE WHEN ? = 'error' THEN COALESCE(error_msg, '') ELSE '' END, updated_at = ?
                WHERE doc_id = ? AND note_id = ?
                """,
                (translated_text, status, status, now, doc_id, note_id),
            )

    def get_fnm_diagnostic_page(self, doc_id: str, book_page: int) -> dict | None:
        from FNM_RE import get_diagnostic_entry_for_page

        return get_diagnostic_entry_for_page(doc_id, int(book_page), repo=self)

    def list_fnm_diagnostic_entries(self, doc_id: str) -> list[dict]:
        from FNM_RE import list_diagnostic_entries_for_doc

        return list_diagnostic_entries_for_doc(doc_id, repo=self)

    def list_fnm_pages(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_pages
                WHERE doc_id = ?
                ORDER BY page_no ASC, row_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [self._row_to_fnm_page(row) for row in rows]

    def list_fnm_chapters(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_chapters
                WHERE doc_id = ?
                ORDER BY start_page ASC, row_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [self._row_to_fnm_chapter(row) for row in rows]

    def list_fnm_heading_candidates(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_heading_candidates
                WHERE doc_id = ?
                ORDER BY page_no ASC, row_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [self._row_to_fnm_heading_candidate(row) for row in rows]

    def list_fnm_note_regions(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_note_regions
                WHERE doc_id = ?
                ORDER BY start_page ASC, row_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [self._row_to_fnm_note_region(row) for row in rows]

    def list_fnm_chapter_note_modes(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_chapter_note_modes
                WHERE doc_id = ?
                ORDER BY row_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [self._row_to_fnm_chapter_note_mode(row) for row in rows]

    def list_fnm_section_heads(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_section_heads
                WHERE doc_id = ?
                ORDER BY page_no ASC, row_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [self._row_to_fnm_section_head(row) for row in rows]

    def list_fnm_note_items(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_note_items
                WHERE doc_id = ?
                ORDER BY page_no ASC, row_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_fnm_body_anchors(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_body_anchors
                WHERE doc_id = ?
                ORDER BY page_no ASC, paragraph_index ASC, char_start ASC, row_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_fnm_note_links(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_note_links
                WHERE doc_id = ?
                ORDER BY row_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_fnm_structure_reviews(self, doc_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM fnm_structure_reviews
                WHERE doc_id = ?
                ORDER BY row_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [self._row_to_fnm_structure_review(row) for row in rows]

    def list_fnm_review_overrides(self, doc_id: str, *, scope: str | None = None) -> list[dict]:
        with read_connection(self.db_path) as conn:
            if scope:
                rows = conn.execute(
                    """
                    SELECT * FROM fnm_review_overrides_v2
                    WHERE doc_id = ? AND scope = ?
                    ORDER BY scope ASC, target_id ASC
                    """,
                    (doc_id, scope),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM fnm_review_overrides_v2
                    WHERE doc_id = ?
                    ORDER BY scope ASC, target_id ASC
                    """,
                    (doc_id,),
                ).fetchall()
            return [self._row_to_fnm_review_override(row) for row in rows]

    def get_fnm_review_override(self, doc_id: str, scope: str, target_id: str) -> dict | None:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM fnm_review_overrides_v2
                WHERE doc_id = ? AND scope = ? AND target_id = ?
                LIMIT 1
                """,
                (doc_id, scope, target_id),
            ).fetchone()
            return self._row_to_fnm_review_override(row)

    def save_fnm_review_override(self, doc_id: str, scope: str, target_id: str, payload: dict) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO fnm_review_overrides_v2(
                    doc_id, scope, target_id, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id, scope, target_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    doc_id,
                    scope,
                    target_id,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )

    def delete_fnm_review_override(self, doc_id: str, scope: str, target_id: str) -> None:
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                DELETE FROM fnm_review_overrides_v2
                WHERE doc_id = ? AND scope = ? AND target_id = ?
                """,
                (doc_id, scope, target_id),
            )

    def clear_fnm_review_overrides(self, doc_id: str, *, scope: str | None = None) -> None:
        with transaction(self.db_path) as conn:
            if scope:
                conn.execute(
                    """
                    DELETE FROM fnm_review_overrides_v2
                    WHERE doc_id = ? AND scope = ?
                    """,
                    (doc_id, scope),
                )
            else:
                conn.execute(
                    """
                    DELETE FROM fnm_review_overrides_v2
                    WHERE doc_id = ?
                    """,
                    (doc_id,),
                )

    def get_fnm_section_for_page(self, doc_id: str, book_page: int) -> dict | None:
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT chapter_id AS section_id, title AS section_title, start_page AS section_start_page, end_page AS section_end_page
                FROM fnm_chapters
                WHERE doc_id = ?
                  AND start_page <= ?
                  AND end_page >= ?
                ORDER BY start_page ASC, end_page ASC
                LIMIT 1
                """,
                (doc_id, int(book_page), int(book_page)),
            ).fetchone()
            if row:
                return dict(row)
            row = conn.execute(
                """
                SELECT section_id, section_title, section_start_page, section_end_page
                FROM fnm_translation_units
                WHERE doc_id = ?
                  AND section_start_page IS NOT NULL
                  AND section_end_page IS NOT NULL
                  AND section_start_page <= ?
                  AND section_end_page >= ?
                ORDER BY section_start_page ASC, section_end_page ASC
                LIMIT 1
                """,
                (doc_id, int(book_page), int(book_page)),
            ).fetchone()
            return dict(row) if row else None

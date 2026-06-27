"""SQLite FNM 仓储 mixin。"""

from __future__ import annotations

import json
import sqlite3
import time

from persistence.sqlite_schema import read_connection, transaction


def _serialize_segments_for_db(segments):
    from FNM_RE import serialize_segments
    return serialize_segments(segments)


def _deserialize_segments(raw):
    import json as _json
    raw_list = _json.loads(raw) if isinstance(raw, str) else (raw or [])
    from FNM_RE import deserialize_segments_to_dicts
    return deserialize_segments_to_dicts(raw_list)


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
        from FNM_RE import deserialize_segments_to_dicts
        payload["page_segments"] = deserialize_segments_to_dicts(json.loads(payload.pop("page_segments_json") or "[]"))
        owner_kind = str(payload.get("owner_kind") or "").strip().lower()
        if not owner_kind:
            owner_kind = (
                "chapter" if str(payload.get("kind") or "") == "body" else "note_region"
            )
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
        payload["_fnm_source"] = (
            json.loads(row["source_json"] or "{}") if row["source_json"] else {}
        )
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
        payload["payload"] = self._loads_json(
            payload.pop("payload_json", None), default={}
        )
        return payload

    def _row_to_fnm_page(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["has_note_heading"] = bool(payload.get("has_note_heading"))
        payload["note_scan_summary"] = self._loads_json(
            payload.pop("note_scan_summary_json", None), default={}
        )
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
        payload["sampled_pages"] = self._loads_json(
            payload.pop("sampled_pages_json", None), default=[]
        )
        return payload

    def _row_to_fnm_section_head(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["rejected_chapter_candidate"] = bool(
            payload.get("rejected_chapter_candidate")
        )
        return payload

    def _row_to_fnm_structure_review(self, row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        payload = dict(row)
        payload["page_range"] = [
            payload.pop("page_start", None),
            payload.pop("page_end", None),
        ]
        payload["payload_json"] = self._loads_json(
            payload.pop("payload_json", None), default={}
        )
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
                    json.dumps(
                        fields.get("blocking_reasons") or [], ensure_ascii=False
                    ),
                    json.dumps(fields.get("link_summary") or {}, ensure_ascii=False),
                    json.dumps(
                        fields.get("page_partition_summary") or {}, ensure_ascii=False
                    ),
                    json.dumps(
                        fields.get("chapter_mode_summary") or {}, ensure_ascii=False
                    ),
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
                    json.dumps(payload.get("review_counts"), ensure_ascii=False)
                    if "review_counts" in payload
                    else None,
                    json.dumps(payload.get("blocking_reasons"), ensure_ascii=False)
                    if "blocking_reasons" in payload
                    else None,
                    json.dumps(payload.get("link_summary"), ensure_ascii=False)
                    if "link_summary" in payload
                    else None,
                    json.dumps(
                        payload.get("page_partition_summary"), ensure_ascii=False
                    )
                    if "page_partition_summary" in payload
                    else None,
                    json.dumps(payload.get("chapter_mode_summary"), ensure_ascii=False)
                    if "chapter_mode_summary" in payload
                    else None,
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
            conn.execute(
                "DELETE FROM fnm_review_overrides_v2 WHERE doc_id = ?", (doc_id,)
            )
        if include_structure:
            conn.execute(
                "DELETE FROM fnm_structure_reviews WHERE doc_id = ?", (doc_id,)
            )
            conn.execute("DELETE FROM fnm_note_links WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_body_anchors WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "DELETE FROM fnm_chapter_anchor_alignment WHERE doc_id = ?", (doc_id,)
            )
            conn.execute(
                "DELETE FROM fnm_paragraph_footnotes WHERE doc_id = ?", (doc_id,)
            )
            conn.execute("DELETE FROM fnm_chapter_endnotes WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_note_items WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_section_heads WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "DELETE FROM fnm_chapter_note_modes WHERE doc_id = ?", (doc_id,)
            )
            conn.execute("DELETE FROM fnm_note_regions WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "DELETE FROM fnm_heading_candidates WHERE doc_id = ?", (doc_id,)
            )
            conn.execute("DELETE FROM fnm_chapters WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_pages WHERE doc_id = ?", (doc_id,))
        if include_notes_units:
            conn.execute(
                "DELETE FROM fnm_translation_units WHERE doc_id = ?", (doc_id,)
            )

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
                        source_hash, segment_plan_hash, pipeline_run_id, stale_reason,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        unit.get("unit_id"),
                        doc_id,
                        unit.get("kind"),
                        unit.get("owner_kind")
                        or (
                            "chapter"
                            if str(unit.get("kind") or "") == "body"
                            else "note_region"
                        ),
                        unit.get("owner_id") or unit.get("section_id"),
                        unit.get("section_id"),
                        unit.get("section_title"),
                        int(unit.get("section_start_page"))
                        if unit.get("section_start_page") is not None
                        else None,
                        int(unit.get("section_end_page"))
                        if unit.get("section_end_page") is not None
                        else None,
                        unit.get("note_id"),
                        int(unit.get("page_start"))
                        if unit.get("page_start") is not None
                        else None,
                        int(unit.get("page_end"))
                        if unit.get("page_end") is not None
                        else None,
                        int(unit.get("char_count", 0) or 0),
                        unit.get("source_text"),
                        unit.get("translated_text"),
                        unit.get("status", "pending"),
                        unit.get("error_msg"),
                        unit.get("target_ref"),
                        json.dumps(_serialize_segments_for_db(unit.get("page_segments") or []), ensure_ascii=False),
                        str(unit.get("source_hash") or ""),
                        str(unit.get("segment_plan_hash") or ""),
                        str(unit.get("pipeline_run_id") or ""),
                        str(unit.get("stale_reason") or ""),
                        now,
                        now,
                    ),
                )

    def replace_fnm_translation_units(
        self, doc_id: str, *, units: list[dict]
    ) -> None:
        """只替换 fnm_translation_units 表，不动 structure/notes。"""
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                "DELETE FROM fnm_translation_units WHERE doc_id = ?", (doc_id,)
            )
            if units:
                FnmRepoMixin._batch_insert(conn,
                    """INSERT INTO fnm_translation_units(
                        unit_id, doc_id, kind, owner_kind, owner_id, section_id, section_title,
                        section_start_page, section_end_page,
                        note_id, page_start, page_end, char_count,
                        source_text, translated_text, status, error_msg, target_ref, page_segments_json,
                        source_hash, segment_plan_hash, pipeline_run_id, stale_reason,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(
                        unit.get("unit_id"), doc_id,
                        unit.get("kind"), unit.get("owner_kind"), unit.get("owner_id"),
                        unit.get("section_id"), unit.get("section_title"),
                        int(unit.get("section_start_page") or 0), int(unit.get("section_end_page") or 0),
                        unit.get("note_id"),
                        int(unit.get("page_start") or 0), int(unit.get("page_end") or 0),
                        int(unit.get("char_count") or 0),
                        str(unit.get("source_text") or ""), str(unit.get("translated_text") or ""),
                        unit.get("status", "pending"), unit.get("error_msg"), unit.get("target_ref"),
                        json.dumps(_serialize_segments_for_db(unit.get("page_segments") or []), ensure_ascii=False),
                        str(unit.get("source_hash") or ""), str(unit.get("segment_plan_hash") or ""),
                        str(unit.get("pipeline_run_id") or ""), str(unit.get("stale_reason") or ""),
                        now, now,
                    ) for unit in (units or [])]
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
            conn.execute(
                "DELETE FROM fnm_structure_reviews WHERE doc_id = ?", (doc_id,)
            )
            conn.execute("DELETE FROM fnm_note_links WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_body_anchors WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "DELETE FROM fnm_chapter_anchor_alignment WHERE doc_id = ?", (doc_id,)
            )
            conn.execute(
                "DELETE FROM fnm_paragraph_footnotes WHERE doc_id = ?", (doc_id,)
            )
            conn.execute("DELETE FROM fnm_chapter_endnotes WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_note_items WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_section_heads WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "DELETE FROM fnm_chapter_note_modes WHERE doc_id = ?", (doc_id,)
            )
            conn.execute("DELETE FROM fnm_note_regions WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "DELETE FROM fnm_heading_candidates WHERE doc_id = ?", (doc_id,)
            )
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
                        int(row.get("target_pdf_page") or 0)
                        if row.get("target_pdf_page") is not None
                        else None,
                        row.get("page_role"),
                        float(row.get("role_confidence", 0.0) or 0.0),
                        row.get("role_reason"),
                        row.get("section_hint"),
                        1 if bool(row.get("has_note_heading")) else 0,
                        json.dumps(
                            row.get("note_scan_summary") or {}, ensure_ascii=False
                        ),
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
                        float(row.get("font_height"))
                        if row.get("font_height") is not None
                        else None,
                        float(row.get("x")) if row.get("x") is not None else None,
                        float(row.get("y")) if row.get("y") is not None else None,
                        float(row.get("width_estimate"))
                        if row.get("width_estimate") is not None
                        else None,
                        row.get("font_name") or "",
                        row.get("font_weight_hint") or "unknown",
                        row.get("align_hint") or "unknown",
                        float(row.get("width_ratio"))
                        if row.get("width_ratio") is not None
                        else None,
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
                        int(row.get("page_no_start"))
                        if row.get("page_no_start") is not None
                        else None,
                        int(row.get("page_no_end"))
                        if row.get("page_no_end") is not None
                        else None,
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
                        int(page_range[1])
                        if len(page_range) > 1 and page_range[1] is not None
                        else None,
                        json.dumps(row.get("payload_json") or {}, ensure_ascii=False),
                        row.get("severity") or "warning",
                        now,
                        now,
                    ),
                )

    @staticmethod
    def _batch_insert(conn, sql, params_list):
        """批量插入，替代逐行 execute。"""
        if params_list:
            conn.executemany(sql, params_list)

    # ------------------- 分阶段写入 -------------------

    @staticmethod
    def _insert_fnm_pages(conn, doc_id: str, rows: list[dict], now: int) -> None:
        FnmRepoMixin._batch_insert(conn,
            """INSERT INTO fnm_pages(
                doc_id, page_no, target_pdf_page, page_role, role_confidence, role_reason,
                section_hint, has_note_heading, note_scan_summary_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
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
            ) for row in (rows or [])]
        )

    @staticmethod
    def _insert_fnm_chapters(conn, doc_id: str, rows: list[dict], now: int) -> None:
        FnmRepoMixin._batch_insert(conn,
            """INSERT INTO fnm_chapters(
                doc_id, chapter_id, title, start_page, end_page, pages_json, source, boundary_state,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
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
            ) for row in (rows or [])]
        )

    @staticmethod
    def _insert_fnm_heading_candidates(
        conn, doc_id: str, rows: list[dict], now: int
    ) -> None:
        FnmRepoMixin._batch_insert(conn,
            """INSERT INTO fnm_heading_candidates(
                doc_id, heading_id, page_no, text, normalized_text, source, block_label,
                top_band, font_height, x, y, width_estimate, font_name, font_weight_hint,
                align_hint, width_ratio, heading_level_hint, confidence, heading_family_guess,
                suppressed_as_chapter, reject_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
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
            ) for row in (rows or [])]
        )

    @staticmethod
    def _insert_fnm_section_heads(
        conn, doc_id: str, rows: list[dict], now: int
    ) -> None:
        FnmRepoMixin._batch_insert(conn,
            """INSERT INTO fnm_section_heads(
                doc_id, section_head_id, chapter_id, page_no, text, normalized_text, source,
                confidence, heading_family_guess, rejected_chapter_candidate, reject_reason,
                derived_from_heading_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
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
            ) for row in (rows or [])]
        )

    @staticmethod
    def _insert_fnm_note_regions(conn, doc_id: str, rows: list[dict], now: int) -> None:
        FnmRepoMixin._batch_insert(conn,
            """INSERT INTO fnm_note_regions(
                doc_id, region_id, region_kind, start_page, end_page, pages_json, title_hint, bound_chapter_id,
                region_start_first_source_marker, region_first_note_item_marker, region_marker_alignment_ok,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
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
            ) for row in (rows or [])]
        )

    @staticmethod
    def _insert_fnm_chapter_note_modes(
        conn, doc_id: str, rows: list[dict], now: int
    ) -> None:
        FnmRepoMixin._batch_insert(conn,
            """INSERT INTO fnm_chapter_note_modes(
                doc_id, chapter_id, chapter_title, note_mode, sampled_pages_json, detection_confidence,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
                doc_id,
                row.get("chapter_id"),
                row.get("chapter_title"),
                row.get("note_mode"),
                json.dumps(row.get("sampled_pages") or [], ensure_ascii=False),
                float(row.get("detection_confidence", 0.0) or 0.0),
                now,
                now,
            ) for row in (rows or [])]
        )

    @staticmethod
    def _insert_fnm_note_items(conn, doc_id: str, rows: list[dict], now: int) -> None:
        FnmRepoMixin._batch_insert(conn,
            """INSERT INTO fnm_note_items(
                doc_id, note_item_id, note_kind, chapter_id, region_id, marker, normalized_marker,
                occurrence, source_text, page_no, display_marker, source_marker, title_hint,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
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
            ) for row in (rows or [])]
        )

    @staticmethod
    def _delete_optional_fnm_table(conn, table_name: str, doc_id: str) -> None:
        """Delete from a Rust-only FNM table when the Python schema has not created it."""
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if row is not None:
            conn.execute(f"DELETE FROM {table_name} WHERE doc_id = ?", (doc_id,))

    # 清理：phase>=N 的产物表；保证下游也被清空
    @staticmethod
    def _delete_fnm_products_from_phase(conn, doc_id: str, phase_from: int) -> None:
        """清 phase>=phase_from 的产物表。和 PHASE_OUTPUT_TABLES 对齐。"""
        phase_from = int(phase_from)
        # Phase 6: Rust export products are absent from Python-only databases.
        if phase_from <= 6:
            for table_name in (
                "fnm_export_chapters",
                "fnm_export_audit",
                "fnm_export_bundle",
            ):
                FnmRepoMixin._delete_optional_fnm_table(conn, table_name, doc_id)
        # Phase 5: merged chapter markdown and diagnostics.
        if phase_from <= 5:
            for table_name in (
                "fnm_chapter_markdowns",
                "fnm_diagnostic_pages",
                "fnm_diagnostic_notes",
            ):
                FnmRepoMixin._delete_optional_fnm_table(conn, table_name, doc_id)
        # Phase 4: frozen source and translation units.
        if phase_from <= 4:
            conn.execute(
                "DELETE FROM fnm_structure_reviews WHERE doc_id = ?", (doc_id,)
            )
            conn.execute(
                "DELETE FROM fnm_translation_units WHERE doc_id = ?", (doc_id,)
            )
            FnmRepoMixin._delete_optional_fnm_table(
                conn, "fnm_chapter_body_pages", doc_id
            )
        # Phase 3
        if phase_from <= 3:
            conn.execute("DELETE FROM fnm_note_links WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fnm_body_anchors WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "DELETE FROM fnm_chapter_anchor_alignment WHERE doc_id = ?", (doc_id,)
            )
            conn.execute(
                "DELETE FROM fnm_paragraph_footnotes WHERE doc_id = ?", (doc_id,)
            )
            conn.execute("DELETE FROM fnm_chapter_endnotes WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "DELETE FROM fnm_review_overrides_v2 WHERE doc_id = ?", (doc_id,)
            )
        # Phase 2
        if phase_from <= 2:
            conn.execute("DELETE FROM fnm_note_items WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "DELETE FROM fnm_chapter_note_modes WHERE doc_id = ?", (doc_id,)
            )
            conn.execute("DELETE FROM fnm_note_regions WHERE doc_id = ?", (doc_id,))
        # Phase 1
        if phase_from <= 1:
            conn.execute("DELETE FROM fnm_section_heads WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "DELETE FROM fnm_heading_candidates WHERE doc_id = ?", (doc_id,)
            )
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

    def replace_fnm_phase3_products(
        self,
        doc_id: str,
        *,
        body_anchors: list[dict],
        note_links: list[dict],
        preserve: bool = False,
    ) -> None:
        """Phase 3 产物写入。默认清 phase>=3 的产物后写入；preserve=True 时追加。"""
        now = int(time.time())
        with transaction(self.db_path) as conn:
            if not preserve:
                self._delete_fnm_products_from_phase(conn, doc_id, 3)
            self._insert_fnm_body_anchors(conn, doc_id, body_anchors, now)
            self._insert_fnm_note_links(conn, doc_id, note_links, now)

    @staticmethod
    def _insert_fnm_body_anchors(conn, doc_id: str, rows: list[dict], now: int) -> None:
        FnmRepoMixin._batch_insert(conn,
            """INSERT INTO fnm_body_anchors(
                doc_id, anchor_id, chapter_id, page_no, paragraph_index, char_start, char_end,
                source_marker, normalized_marker, anchor_kind, certainty, source_text,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
                doc_id,
                str(row.get("anchor_id") or ""),
                str(row.get("chapter_id") or ""),
                int(row.get("page_no") or 0),
                int(row.get("paragraph_index") or 0),
                int(row.get("char_start") or 0),
                int(row.get("char_end") or 0),
                str(row.get("source_marker") or ""),
                str(row.get("normalized_marker") or ""),
                str(row.get("anchor_kind") or ""),
                float(row.get("certainty", 0.0) or 0.0),
                str(row.get("source_text") or ""),
                now, now,
            ) for row in (rows or [])]
        )

    @staticmethod
    def _insert_fnm_note_links(conn, doc_id: str, rows: list[dict], now: int) -> None:
        FnmRepoMixin._batch_insert(conn,
            """INSERT INTO fnm_note_links(
                doc_id, link_id, chapter_id, region_id, note_item_id, anchor_id,
                status, resolver, confidence, note_kind, marker,
                page_no_start, page_no_end, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
                doc_id,
                str(row.get("link_id") or ""),
                str(row.get("chapter_id") or ""),
                str(row.get("region_id") or ""),
                str(row.get("note_item_id") or ""),
                str(row.get("anchor_id") or ""),
                str(row.get("status") or ""),
                str(row.get("resolver") or ""),
                float(row.get("confidence", 0.0) or 0.0),
                str(row.get("note_kind") or ""),
                str(row.get("marker") or ""),
                int(row.get("page_no_start") or 0),
                int(row.get("page_no_end") or 0),
                now, now,
            ) for row in (rows or [])]
        )

    def delete_fnm_products_from_phase(self, doc_id: str, phase_from: int) -> None:
        """级联清理 phase>=phase_from 的 FNM 产物表。对外暴露，方便 dev 模式 reset 走 facade。"""
        with transaction(self.db_path) as conn:
            self._delete_fnm_products_from_phase(conn, doc_id, int(phase_from))

    # ── PDF font band candidates 缓存 ──

    def load_pdf_font_candidates(
        self, doc_id: str, pdf_hash: str, page_indices: str
    ) -> list[dict] | None:
        import json as _json
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT candidates_json FROM fnm_pdf_font_candidates "
                "WHERE doc_id=? AND pdf_hash=? AND page_indices=?",
                (doc_id, pdf_hash, page_indices),
            ).fetchone()
            return _json.loads(row[0]) if row else None

    def save_pdf_font_candidates(
        self, doc_id: str, pdf_hash: str, page_indices: str, candidates: list[dict],
    ) -> None:
        import json as _json
        now = int(__import__("time").time())
        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fnm_pdf_font_candidates "
                "(doc_id, pdf_hash, page_indices, candidates_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (doc_id, pdf_hash, page_indices,
                 _json.dumps(candidates, ensure_ascii=False), now),
            )

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

    def list_fnm_translation_unit_metadata(self, doc_id: str) -> list[dict]:
        """轻量查询：仅返回 unit_id/kind/status/section/page 元数据，不含 page_segments。
        供翻译 worker 的 build_plan 和进度报告使用，避免加载数十 MB 的 page_segments_json。
        """
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT unit_id, kind, owner_kind, owner_id, section_id, section_title,
                       section_start_page, section_end_page, note_id,
                       page_start, page_end, char_count,
                       status, error_msg, target_ref
                FROM fnm_translation_units
                WHERE doc_id = ?
                ORDER BY
                    CASE WHEN lower(COALESCE(owner_kind, '')) = 'chapter' THEN 0 ELSE 1 END ASC,
                    COALESCE(section_start_page, page_start, 0) ASC,
                    page_start ASC, unit_id ASC
                """,
                (doc_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_fnm_translation_unit_by_id(self, doc_id: str, unit_id: str) -> dict | None:
        """按 unit_id 查询单个翻译单元（含 page_segments），避免全表扫描。"""
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM fnm_translation_units WHERE doc_id = ? AND unit_id = ?",
                (doc_id, unit_id),
            ).fetchone()
            return self._row_to_fnm_unit(row)

    # ── 按章过滤的 list 方法（供逐章 DB 驱动 Phase 使用） ──

    def list_fnm_note_items_by_chapter(self, doc_id: str, chapter_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fnm_note_items WHERE doc_id = ? AND chapter_id = ? ORDER BY page_no ASC, row_id ASC",
                (doc_id, chapter_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_fnm_body_anchors_by_chapter(self, doc_id: str, chapter_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fnm_body_anchors WHERE doc_id = ? AND chapter_id = ? ORDER BY page_no ASC, paragraph_index ASC, char_start ASC, row_id ASC",
                (doc_id, chapter_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_fnm_note_links_by_chapter(self, doc_id: str, chapter_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fnm_note_links WHERE doc_id = ? AND chapter_id = ? ORDER BY row_id ASC",
                (doc_id, chapter_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_fnm_translation_units_by_chapter(self, doc_id: str, chapter_id: str) -> list[dict]:
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM fnm_translation_units WHERE doc_id = ? AND owner_id = ? ORDER BY page_start ASC, unit_id ASC",
                (doc_id, chapter_id),
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
                    json.dumps(
                        _serialize_segments_for_db(
                            fields.get(
                                "page_segments",
                                _deserialize_segments(payload.get("page_segments_json") or "[]"),
                            )
                        ),
                        ensure_ascii=False,
                    ),
                    now,
                    unit_id,
                ),
            )

    def update_fnm_note_translation(
        self, doc_id: str, note_id: str, translated_text: str, *, status: str = "done"
    ) -> None:
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

    def list_fnm_review_overrides(
        self, doc_id: str, *, scope: str | None = None
    ) -> list[dict]:
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

    def get_fnm_review_override(
        self, doc_id: str, scope: str, target_id: str
    ) -> dict | None:
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

    def save_fnm_review_override(
        self, doc_id: str, scope: str, target_id: str, payload: dict
    ) -> None:
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

    def batch_save_fnm_review_overrides(
        self, doc_id: str, rows: list[tuple[str, str, dict]]
    ) -> None:
        """批量写入 overrides，单事务完成。rows: [(scope, target_id, payload), ...]"""
        if not rows:
            return
        now = int(time.time())
        params = [
            (doc_id, scope, target_id, json.dumps(payload or {}, ensure_ascii=False), now, now)
            for scope, target_id, payload in rows
        ]
        with transaction(self.db_path) as conn:
            conn.executemany(
                """INSERT INTO fnm_review_overrides_v2(
                    doc_id, scope, target_id, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id, scope, target_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at""",
                params,
            )

    def delete_fnm_review_override(
        self, doc_id: str, scope: str, target_id: str
    ) -> None:
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                DELETE FROM fnm_review_overrides_v2
                WHERE doc_id = ? AND scope = ? AND target_id = ?
                """,
                (doc_id, scope, target_id),
            )

    def clear_fnm_review_overrides(
        self, doc_id: str, *, scope: str | None = None
    ) -> None:
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

    # ── 分章缓存：body_pages 读写 ──

    def save_chapter_body_pages(self, doc_id: str, chapter_id: str, body_pages_json: str) -> None:
        """写入单章 body_pages/body_segments JSON。先删后插兼容旧表结构。"""
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                "DELETE FROM fnm_chapter_body_pages WHERE doc_id = ? AND chapter_id = ?",
                (doc_id, chapter_id),
            )
            conn.execute(
                "INSERT INTO fnm_chapter_body_pages(doc_id, chapter_id, body_pages_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (doc_id, chapter_id, body_pages_json, now, now),
            )

    def load_chapter_body_pages(self, doc_id: str, chapter_id: str) -> dict | None:
        """读取单章 body_pages JSON，返回解析后的 dict 或 None。"""
        import json as _json
        with read_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT body_pages_json FROM fnm_chapter_body_pages WHERE doc_id = ? AND chapter_id = ?",
                (doc_id, chapter_id),
            ).fetchone()
            if row:
                try:
                    return _json.loads(row[0])
                except Exception:
                    return None
        return None

    def delete_chapter_body_pages(self, doc_id: str) -> None:
        """删除文档所有分章缓存。"""
        with transaction(self.db_path) as conn:
            conn.execute("DELETE FROM fnm_chapter_body_pages WHERE doc_id = ?", (doc_id,))

    def list_fnm_chapter_body_pages_all(self, doc_id: str) -> list[dict]:
        """列出文档所有分章缓存行，返回 [{chapter_id, body_pages_json}, ...]."""
        import json as _json
        with read_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT chapter_id, body_pages_json FROM fnm_chapter_body_pages WHERE doc_id = ? ORDER BY row_id",
                (doc_id,),
            ).fetchall()
            return [
                {"chapter_id": r[0], "body_pages_json": r[1]}
                for r in rows
            ]

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

    # ---- 新表：fnm_chapter_endnotes ----

    def list_fnm_chapter_endnotes(
        self, doc_id: str, *, chapter_id: str | None = None
    ) -> list[dict]:
        with read_connection(self.db_path) as conn:
            if chapter_id:
                rows = conn.execute(
                    """
                    SELECT * FROM fnm_chapter_endnotes
                    WHERE doc_id = ? AND chapter_id = ?
                    ORDER BY ordinal ASC
                    """,
                    (doc_id, chapter_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM fnm_chapter_endnotes
                    WHERE doc_id = ?
                    ORDER BY chapter_id ASC, ordinal ASC
                    """,
                    (doc_id,),
                ).fetchall()
            return [dict(row) for row in rows]

    def replace_fnm_chapter_endnotes(
        self,
        doc_id: str,
        chapter_id: str,
        *,
        endnotes: list[dict],
    ) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                "DELETE FROM fnm_chapter_endnotes WHERE doc_id = ? AND chapter_id = ?",
                (doc_id, chapter_id),
            )
            for row in endnotes or []:
                conn.execute(
                    """
                    INSERT INTO fnm_chapter_endnotes(
                        doc_id, chapter_id, ordinal, marker, numbering_scheme, text, source_page_no,
                        is_reconstructed, review_required, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        chapter_id,
                        int(row.get("ordinal") or 0),
                        row.get("marker"),
                        row.get("numbering_scheme") or "per_chapter",
                        row.get("text"),
                        int(row.get("source_page_no"))
                        if row.get("source_page_no") is not None
                        else None,
                        1 if bool(row.get("is_reconstructed")) else 0,
                        1 if row.get("review_required", True) else 0,
                        now,
                        now,
                    ),
                )

    def clear_fnm_chapter_endnotes(self, doc_id: str) -> None:
        with transaction(self.db_path) as conn:
            conn.execute("DELETE FROM fnm_chapter_endnotes WHERE doc_id = ?", (doc_id,))

    # ---- 新表：fnm_paragraph_footnotes ----

    def list_fnm_paragraph_footnotes(
        self, doc_id: str, *, chapter_id: str | None = None, page_no: int | None = None
    ) -> list[dict]:
        with read_connection(self.db_path) as conn:
            if chapter_id and page_no is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM fnm_paragraph_footnotes
                    WHERE doc_id = ? AND chapter_id = ? AND page_no = ?
                    ORDER BY paragraph_index ASC, row_id ASC
                    """,
                    (doc_id, chapter_id, int(page_no)),
                ).fetchall()
            elif chapter_id:
                rows = conn.execute(
                    """
                    SELECT * FROM fnm_paragraph_footnotes
                    WHERE doc_id = ? AND chapter_id = ?
                    ORDER BY page_no ASC, paragraph_index ASC, row_id ASC
                    """,
                    (doc_id, chapter_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM fnm_paragraph_footnotes
                    WHERE doc_id = ?
                    ORDER BY chapter_id ASC, page_no ASC, paragraph_index ASC, row_id ASC
                    """,
                    (doc_id,),
                ).fetchall()
            return [dict(row) for row in rows]

    def replace_fnm_paragraph_footnotes(
        self,
        doc_id: str,
        chapter_id: str,
        *,
        footnotes: list[dict],
    ) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                "DELETE FROM fnm_paragraph_footnotes WHERE doc_id = ? AND chapter_id = ?",
                (doc_id, chapter_id),
            )
            for row in footnotes or []:
                conn.execute(
                    """
                    INSERT INTO fnm_paragraph_footnotes(
                        doc_id, chapter_id, page_no, paragraph_index, attachment_kind,
                        source_marker, text, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        chapter_id,
                        int(row.get("page_no") or 0),
                        int(row.get("paragraph_index", 0) or 0),
                        row.get("attachment_kind") or "page_tail",
                        row.get("source_marker"),
                        row.get("text"),
                        now,
                        now,
                    ),
                )

    def clear_fnm_paragraph_footnotes(self, doc_id: str) -> None:
        with transaction(self.db_path) as conn:
            conn.execute(
                "DELETE FROM fnm_paragraph_footnotes WHERE doc_id = ?", (doc_id,)
            )

    # ---- 新表：fnm_chapter_anchor_alignment ----

    def list_fnm_chapter_anchor_alignment(
        self, doc_id: str, *, chapter_id: str | None = None
    ) -> list[dict]:
        with read_connection(self.db_path) as conn:
            if chapter_id:
                rows = conn.execute(
                    """
                    SELECT * FROM fnm_chapter_anchor_alignment
                    WHERE doc_id = ? AND chapter_id = ?
                    """,
                    (doc_id, chapter_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM fnm_chapter_anchor_alignment
                    WHERE doc_id = ?
                    ORDER BY chapter_id ASC
                    """,
                    (doc_id,),
                ).fetchall()
            result: list[dict] = []
            for row in rows:
                d = dict(row)
                if d.get("mismatch_json"):
                    try:
                        d["mismatch"] = json.loads(d.pop("mismatch_json"))
                    except Exception:
                        pass
                result.append(d)
            return result

    def upsert_fnm_chapter_anchor_alignment(
        self,
        doc_id: str,
        chapter_id: str,
        *,
        alignment_status: str = "misaligned",
        body_anchor_count: int = 0,
        endnote_count: int = 0,
        mismatch: dict | None = None,
    ) -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO fnm_chapter_anchor_alignment(
                    doc_id, chapter_id, alignment_status, body_anchor_count, endnote_count,
                    mismatch_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id, chapter_id) DO UPDATE SET
                    alignment_status = excluded.alignment_status,
                    body_anchor_count = excluded.body_anchor_count,
                    endnote_count = excluded.endnote_count,
                    mismatch_json = excluded.mismatch_json,
                    updated_at = excluded.updated_at
                """,
                (
                    doc_id,
                    chapter_id,
                    alignment_status,
                    int(body_anchor_count),
                    int(endnote_count),
                    json.dumps(mismatch, ensure_ascii=False) if mismatch else None,
                    now,
                    now,
                ),
            )

    def clear_fnm_chapter_anchor_alignment(self, doc_id: str) -> None:
        with transaction(self.db_path) as conn:
            conn.execute(
                "DELETE FROM fnm_chapter_anchor_alignment WHERE doc_id = ?", (doc_id,)
            )

    # ── 增量 checkpoint 支持 ────────────────────────────────

    def create_phase_run(
        self, doc_id: str, *, run_id: str, phase: int, gate_report: dict | None = None,
        counts: dict | None = None, hashes: dict | None = None,
    ) -> int:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            cur = conn.execute(
                """INSERT INTO fnm_phase_runs(doc_id, run_id, phase, status,
                   gate_report_json, counts_json, hash_json, started_at)
                   VALUES (?, ?, ?, 'running', ?, ?, ?, ?)""",
                (doc_id, run_id, int(phase),
                 json.dumps(gate_report or {}, ensure_ascii=False),
                 json.dumps(counts or {}, ensure_ascii=False),
                 json.dumps(hashes or {}, ensure_ascii=False),
                 now),
            )
            return cur.lastrowid or 0

    def finish_phase_run(self, doc_id: str, run_id: str, phase: int, status: str = "done") -> None:
        now = int(time.time())
        with transaction(self.db_path) as conn:
            conn.execute(
                "UPDATE fnm_phase_runs SET status=?, finished_at=? WHERE doc_id=? AND run_id=? AND phase=?",
                (str(status), now, doc_id, run_id, int(phase)),
            )

    def reset_from_phase(self, doc_id: str, phase: int) -> dict[str, int]:
        """清除 phase >= N 的所有产物。返回清除行数统计。
        委托 _delete_fnm_products_from_phase 保证表覆盖一致。"""
        phase = int(phase)
        with transaction(self.db_path) as conn:
            before = conn.total_changes
            self._delete_fnm_products_from_phase(conn, doc_id, phase)
            deleted = conn.total_changes - before
            conn.execute("DELETE FROM fnm_phase_runs WHERE doc_id=?", (doc_id,))
            conn.execute("DELETE FROM fnm_dev_snapshots WHERE doc_id=?", (doc_id,))
        return {"phase_from": phase, "deleted_rows": deleted}
